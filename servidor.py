#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tablero local del ETL: HTTP encima de las mismas capas que usa el CLI.

    python3 servidor.py --email tu@correo.unam.mx --abrir

Escucha SOLO en 127.0.0.1. No hay autenticacion de ninguna clase, y el
tablero puede lanzar descargas que gastan el limite de NCBI de todo el
laboratorio: exponerlo en 0.0.0.0 seria regalarle a cualquiera de la red
la capacidad de dejar sin servicio a los demas (NCBI bloquea por IP, no
por usuario) y de borrar documentos. Si algun dia hace falta acceso
remoto, va detras de un tunel SSH o de un proxy que autentique, nunca
cambiando el bind.

La pieza que importa es manejar(), que es una funcion normal:

    manejar(metodo, ruta, params, cuerpo, ctx) -> (codigo_http, objeto)

No abre sockets, no imprime y no lee archivos. La clase de http.server
solo la envuelve: lee el cuerpo, parsea la query string y serializa la
respuesta. Por eso las pruebas cubren la API completa sin levantar un
puerto ni depender de que el firewall de la maquina deje.

Como el resto del proyecto: no tiene logica de negocio. Valida lo que
llega, llama a db, a etl o al flujo, y formatea JSON. Cero SQL propio.
"""

import argparse
import http.server
import json
import os
import re
import sys
import traceback
import urllib.parse
import webbrowser
from pathlib import Path

import flujo
from grn_bronce import rutas
from grn_etl import credenciales, db, etl, pubmed, trabajos

# El tablero es un solo archivo, sin recursos externos. La ruta se resuelve
# contra __file__ y no contra el directorio de trabajo: asi 'python
# servidor.py' funciona igual desde donde sea.
RUTA_PAGINA = Path(__file__).resolve().parent / "web" / "index.html"
RUTA_LOGO = (Path(__file__).resolve().parent / "web"
             / "cropped-cropped-LogoUNAM_IIMAS_Color.png")

PUERTO_POR_OMISION = 8765

# Cuánto espera el cierre del servidor a que un trabajo cancelable se
# detenga. El vigía de cada paso del flujo mira el evento cada medio segundo
# y matar el árbol de procesos tarda un par de segundos más en Windows.
ESPERA_CIERRE = 20

# De a cuánto se manda un archivo. El CSV de candidatas pesa ~90 MB; leerlo
# entero a memoria por cada descarga era la forma de tumbar el tablero.
BLOQUE_ARCHIVO = 256 * 1024


def salida_por_omision(datos=None):
    """`<datos>/fulltext`, con la raíz de datos resuelta por precedencia:
    flag, luego `GRN_DATOS`, luego `./datos`. La resuelve `grn_bronce.rutas`
    para que la regla esté escrita en un solo sitio."""
    return os.path.join(rutas.raiz_datos(datos), "fulltext")


ORDENES = ("relevance", "pub_date")
TIPOS_ARCHIVO = ("xml", "pdf")

# Tope de filas de bitacora por peticion. Nadie pinta mas que eso, y sin
# tope una URL con n de seis cifras trae la bitacora entera a memoria.
# Contar filas con este endpoint no sirve y por eso el tablero ya no lo
# hace: al rebasar el tope el conteo se queda en el tope y miente hacia
# abajo. Para eso esta db.conteos_consulta().
MAX_EJECUCIONES = 1000

# 4 MB alcanza de sobra para el abstract mas largo o para una query
# booleana de varias paginas, y le pone un piso al dano de un cuerpo
# absurdo.
MAX_CUERPO = 4 * 1024 * 1024

# Los anios de PubMed son '2020' o a lo mas '2020/03/15'.
PATRON_FECHA = re.compile(r"^\d{4}(/\d{2}){0,2}$")


def es_json(tipo_contenido):
    """True si el Content-Type dice que el cuerpo es JSON.

    Se exige en toda peticion con cuerpo, y no por purismo: una pagina
    cualquiera abierta en el mismo navegador puede mandarle un formulario
    a 127.0.0.1 sin permiso de nadie, pero un formulario solo sabe mandar
    urlencoded, multipart o text/plain. Pedir JSON deja fuera esa via, y
    un fetch de otro origen con Content-Type JSON dispara el preflight
    OPTIONS, que aqui no se contesta. Como ademas no se manda ninguna
    cabecera CORS, nadie de fuera puede leer las respuestas.
    """
    principal = (tipo_contenido or "").split(";")[0].strip().lower()
    return principal == "application/json"


class Contexto:
    """Lo que necesita manejar() para trabajar.

    con:     conexion sqlite del hilo que atiende esta peticion.
    gestor:  el trabajos.Gestor unico del proceso.
    cliente: el pubmed.Cliente unico del proceso, o None si no hay correo
             configurado (el tablero arranca igual; lo unico que no se
             puede es lanzar trabajos).
    salida:  raiz donde el fulltext escribe. No se acepta por HTTP a
             proposito: una ruta que llega en un cuerpo JSON es permiso de
             escritura en cualquier parte del disco.
    flujo_raiz: raíz de las carpetas del flujo (salidas/flujo). Mismo
             criterio que 'salida': sale de --flujo al arrancar y jamás de
             una petición, porque de ahí se leen las descargas y ahí
             escribe el flujo.
    datos:   raíz de datos que se le pasa al flujo, ya resuelta y absoluta,
             o None para que el flujo la resuelva solo. Absoluta porque sus
             pasos corren con el directorio de trabajo en la raíz del
             repositorio, que no tiene por qué ser el del servidor.
    """

    def __init__(self, con, gestor, cliente=None, salida=None,
                 correo_explicito=None, al_cambiar_cliente=None,
                 flujo_raiz=None, datos=None):
        self.con = con
        self.gestor = gestor
        self.cliente = cliente
        self.salida = salida or salida_por_omision()
        self.flujo_raiz = flujo_raiz or flujo.RAIZ_FLUJO
        self.datos = datos
        # El Contexto se arma de nuevo en cada peticion, asi que un cliente
        # nuevo tiene que subir a quien lo guarda entre peticiones o se
        # perderia al terminar esta. El callable lo pone la capa HTTP; en
        # las pruebas no hace falta.
        self.al_cambiar_cliente = al_cambiar_cliente
        # Si el correo vino por --email, gana sobre lo guardado y no se
        # pisa desde el tablero: quien lo puso en la linea de comandos
        # sabia lo que hacia.
        self.correo_explicito = correo_explicito

    def rehacer_cliente(self):
        """Arma de nuevo el cliente con las credenciales de ahora.

        Se llama al guardar la configuracion, para no tener que reiniciar
        el servidor. Sigue habiendo UNO solo por proceso: el limitador de
        tasa vive en la instancia, y dos clientes creerian cada uno que
        respetan el limite mientras el conjunto lo rebasa.
        """
        correo = credenciales.correo(self.correo_explicito)
        self.cliente = (pubmed.Cliente(correo, credenciales.llave())
                        if correo else None)
        if self.al_cambiar_cliente:
            self.al_cambiar_cliente(self.cliente)
        return self.cliente


class Archivo:
    """Marca que la respuesta es un archivo de disco y no JSON.

    manejar() no lee nada del disco: devuelve esta marca y quien la
    envuelve decide como entregarla. Eso la deja probable sin tocar el
    sistema de archivos.

    descarga_como: si trae un nombre, el archivo se entrega como descarga
    (Content-Disposition: attachment) con ese nombre, en vez de abrirse en
    la pestaña. Es lo que piden las salidas del flujo: un CSV de 90 MB no
    se lee en el navegador.
    """

    def __init__(self, ruta, tipo_mime, descarga_como=None):
        self.ruta = Path(ruta)
        self.tipo_mime = tipo_mime
        self.descarga_como = descarga_como


PAGINA = Archivo(RUTA_PAGINA, "text/html; charset=utf-8")
# El escudo de la UNAM y del IIMAS, en el encabezado del tablero. Se sirve
# como archivo y no incrustado en el HTML porque en base64 creceria a 145 KB
# dentro de un archivo que se edita a mano.
LOGO = Archivo(RUTA_LOGO, "image/png")


class ErrorPeticion(Exception):
    """Peticion invalida. Trae el codigo con el que se contesta."""

    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


# --------------------------------------------------------------- validacion

def _no_encontrado(metodo, ruta):
    raise ErrorPeticion(404, f"no existe la ruta {metodo} {ruta}")


def _objeto(cuerpo):
    """El cuerpo tiene que ser un objeto JSON, no una lista ni un numero."""
    if not isinstance(cuerpo, dict):
        raise ErrorPeticion(400, "se esperaba un objeto JSON en el cuerpo")
    return cuerpo


def _texto(cuerpo, clave, obligatorio=False):
    valor = cuerpo.get(clave)
    if valor is None:
        if obligatorio:
            raise ErrorPeticion(400, f"falta '{clave}' en el cuerpo")
        return None
    if not isinstance(valor, str):
        raise ErrorPeticion(400, f"'{clave}' debe ser texto")
    valor = valor.strip()
    if not valor and obligatorio:
        raise ErrorPeticion(400, f"'{clave}' no puede ir vacío")
    return valor


def _entero(valor, nombre, minimo=None, maximo=None):
    """Convierte a entero o falla con 400. None y '' significan ausente.

    Se valida aqui y no en db.py porque quien manda 'pagina=abc' merece
    un 400 que se lo diga, no un ValueError convertido en 500.
    """
    if valor is None or valor == "":
        return None
    # bool es subclase de int; 'pagina=true' no es una pagina.
    if isinstance(valor, bool) or not isinstance(valor, (int, str)):
        raise ErrorPeticion(400, f"'{nombre}' debe ser un número entero")
    try:
        n = int(valor)
    except ValueError:
        raise ErrorPeticion(
            400, f"'{nombre}' debe ser un número entero, llegó '{valor}'")
    if minimo is not None and n < minimo:
        raise ErrorPeticion(400, f"'{nombre}' debe ser al menos {minimo}")
    if maximo is not None and n > maximo:
        raise ErrorPeticion(400, f"'{nombre}' no puede pasar de {maximo}")
    return n


def _booleano(valor, nombre, omision=False):
    if valor is None:
        return omision
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int):
        return valor != 0
    if isinstance(valor, str):
        if valor.lower() in ("1", "true", "si"):
            return True
        if valor.lower() in ("0", "false", "no", ""):
            return False
    raise ErrorPeticion(400, f"'{nombre}' debe ser verdadero o falso")


def _param(params, nombre):
    """Un parametro de la query string, o None si viene vacio."""
    valor = (params.get(nombre) or "").strip()
    return valor or None


def _paginacion(params):
    """(pagina, por_pagina) ya validados y acotados por db.paginado()."""
    pagina = _entero(params.get("pagina"), "pagina", minimo=0)
    por_pagina = _entero(params.get("por_pagina"), "por_pagina", minimo=0)
    pagina, por_pagina, _ = db.paginado(pagina, por_pagina)
    return pagina, por_pagina


def _filtro_abstract(params):
    """Tri-estado: '1' solo con, '0' solo sin, vacio ambos."""
    valor = (params.get("abstract") or "").strip()
    if valor == "":
        return None
    if valor == "1":
        return True
    if valor == "0":
        return False
    raise ErrorPeticion(
        400, "'abstract' debe ser '1' (solo con), '0' (solo sin) o vacío")


def _fecha(cuerpo, clave):
    valor = _texto(cuerpo, clave)
    if valor and not PATRON_FECHA.match(valor):
        raise ErrorPeticion(
            400, f"'{clave}' debe ser un año como 2020 o una fecha 2020/03/15")
    return valor


def _consulta_por_id(ctx, texto_id):
    """La fila de la consulta o 404. El id llega en la ruta, como texto."""
    consulta_id = _entero(texto_id, "id")
    if consulta_id is None:
        raise ErrorPeticion(400, "falta el id de la consulta")
    fila = db.obtener_consulta_por_id(ctx.con, consulta_id)
    if fila is None:
        raise ErrorPeticion(404, f"no existe la consulta con id {consulta_id}")
    return fila


def _consulta_por_nombre(ctx, nombre):
    fila = db.obtener_consulta(ctx.con, nombre)
    if fila is None:
        raise ErrorPeticion(404, f"no existe la consulta '{nombre}'")
    return fila


# ------------------------------------------------------------------ estado

def _ver_config(ctx):
    """Que credenciales hay, SIN decir cual es la llave.

    Devuelve si hay llave y de donde salio, nunca su valor. Una llave que
    entra por un formulario y puede volver a salir por un GET es una
    llave que cualquier pagina abierta en el mismo navegador podria
    leerse; que solo se pueda escribir es lo que lo impide.
    """
    correo = credenciales.correo(ctx.correo_explicito)
    return 200, {
        "correo": correo or "",
        "origen_correo": ("argumento" if ctx.correo_explicito
                          else credenciales.origen_correo()),
        "tiene_llave": bool(credenciales.llave()),
        "origen_llave": credenciales.origen_llave(),
        "puede_lanzar": bool(correo),
        "peticiones_por_segundo": 10 if credenciales.llave() else 3,
    }


def _guardar_config(ctx, cuerpo):
    """Guarda correo y llave, y rearma el cliente sin reiniciar nada.

    Escribe en los mismos archivos que ya se leian al arrancar, asi que
    la proxima vez el tablero ya sirve sin exportar nada a mano: esa era
    la friccion que hacia fallar el lanzamiento.
    """
    cuerpo = _objeto(cuerpo)
    cambios = []

    if "correo" in cuerpo:
        valor = _texto(cuerpo, "correo", obligatorio=True)
        try:
            credenciales.guardar_correo(valor)
        except ValueError as e:
            raise ErrorPeticion(400, str(e))
        cambios.append("correo")

    if "llave" in cuerpo:
        valor = (cuerpo.get("llave") or "").strip()
        if valor:
            try:
                credenciales.guardar_llave(valor)
            except ValueError as e:
                raise ErrorPeticion(400, str(e))
            cambios.append("llave")
        else:
            # Cadena vacia significa quitarla, no ignorarla.
            credenciales.borrar_llave()
            cambios.append("llave quitada")

    if not cambios:
        raise ErrorPeticion(400, "no llegó ni 'correo' ni 'llave'")

    # El cliente se rehace con lo nuevo. Sigue siendo uno solo por
    # proceso: el limitador de tasa vive en la instancia, y dos clientes
    # creerian cada uno que respeta el limite mientras el conjunto lo
    # rebasa.
    ctx.rehacer_cliente()
    codigo, estado = _ver_config(ctx)
    estado["cambios"] = cambios
    return codigo, estado


def _estado(ctx):
    r = db.resumen(ctx.con)
    return 200, {
        "consultas": r["consultas"],
        "documentos": r["documentos"],
        "con_abstract": r["con_abstract"],
        "vinculos": r["vinculos"],
        "descargas": [dict(f) for f in r["descargas"]],
        # Cuanto del corpus sirve para el clasificador, que no es lo mismo
        # que cuantos documentos hay y se confunde todo el tiempo.
        "cobertura": db.cobertura_texto(ctx.con),
    }


# --------------------------------------------------------------- consultas

def _listar_consultas(ctx):
    return 200, [dict(f) for f in db.listar_consultas(ctx.con)]


def _ver_consulta(ctx, texto_id):
    fila = _consulta_por_id(ctx, texto_id)
    consulta = dict(fila)
    # Los conteos van en el detalle para que la confirmacion del borrado
    # diga el numero exacto antes de que el usuario acepte. Es lo mismo que
    # hace _ver_documento(), y por la misma razon.
    conteos = db.conteos_consulta(ctx.con, fila["id"])
    consulta["n_vinculos"] = conteos["vinculos"]
    consulta["n_ejecuciones"] = conteos["ejecuciones"]
    return 200, consulta


def _alta_consulta(ctx, cuerpo):
    cuerpo = _objeto(cuerpo)
    nombre = _texto(cuerpo, "nombre", obligatorio=True)
    texto = _texto(cuerpo, "texto", obligatorio=True)
    descripcion = _texto(cuerpo, "descripcion")
    consulta_id, estado = db.alta_consulta(ctx.con, nombre, texto, descripcion)
    # 201 tambien cuando el nombre ya existia: alta_consulta es idempotente
    # y 'estado' dice cual de los tres casos fue. Al tablero le sirve mas
    # ese detalle que distinguir 200 de 201.
    return 201, {"id": consulta_id, "estado": estado}


def _editar_consulta(ctx, texto_id, cuerpo):
    fila = _consulta_por_id(ctx, texto_id)
    cuerpo = _objeto(cuerpo)

    campos = {}
    if "texto" in cuerpo:
        campos["texto"] = _texto(cuerpo, "texto", obligatorio=True)
    if "descripcion" in cuerpo:
        # Cadena vacia limpia la descripcion; None en db significa "no tocar".
        campos["descripcion"] = _texto(cuerpo, "descripcion") or ""
    if "activa" in cuerpo:
        campos["activa"] = _booleano(cuerpo.get("activa"), "activa")

    if not campos:
        raise ErrorPeticion(
            400, "no se mandó nada que cambiar (texto, descripción o activa)")

    db.actualizar_consulta(ctx.con, fila["id"], **campos)
    return 200, {"ok": True}


def _borrar_consulta(ctx, texto_id):
    fila = _consulta_por_id(ctx, texto_id)
    return 200, {"borrados": db.borrar_consulta(ctx.con, fila["id"])}


# -------------------------------------------------------------- documentos

# La tabla del tablero solo pinta estas columnas. Mandar el abstract de 50
# documentos en cada busqueda son cientos de KB por tecla, y el detalle
# (/api/documentos/<pmid>) ya trae el registro completo cuando se pide.
COLUMNAS_LISTADO = ("pmid", "anio", "revista", "titulo", "doi", "pmcid",
                    "tiene_abstract")


def _listar_documentos(ctx, params):
    pagina, por_pagina = _paginacion(params)
    total, filas = db.listar_documentos(
        ctx.con,
        texto=_param(params, "q"),
        consulta=_param(params, "consulta"),
        anio=_param(params, "anio"),
        con_abstract=_filtro_abstract(params),
        pagina=pagina, por_pagina=por_pagina,
    )
    return 200, {
        "total": total, "pagina": pagina, "por_pagina": por_pagina,
        "filas": [{c: f[c] for c in COLUMNAS_LISTADO} for f in filas],
    }


def _ver_documento(ctx, pmid):
    fila = db.obtener_documento(ctx.con, pmid)
    if fila is None:
        raise ErrorPeticion(404, f"no existe el documento con PMID {pmid}")
    doc = db.a_dict(fila)
    # Los conteos van en el detalle para que la confirmacion del borrado
    # diga el numero exacto antes de que el usuario acepte.
    conteos = db.conteos_documento(ctx.con, pmid)
    doc["n_vinculos"] = conteos["vinculos"]
    doc["n_descargas"] = conteos["descargas"]
    # Con esto el tablero sabe si ofrecer "Leer texto" o "Ver PDF" sin tener
    # que preguntar por separado, y que decir cuando no hay ninguno.
    doc["descargas"] = db.descargas_de(ctx.con, pmid)
    return 200, doc


# Un PMID es una sarta de digitos y un PMCID es PMC mas digitos. No es una
# suposicion: se verifico contra los 2263 documentos de la base. De esa
# estrechez depende que armar un nombre de archivo con ellos sea seguro.
PMID_VALIDO = re.compile(r"^\d{1,12}$")
PMCID_VALIDO = re.compile(r"^PMC\d{1,12}$")


def _dentro_de(raiz, ruta):
    """Si 'ruta' queda dentro de 'raiz', ya resueltas las dos.

    Path.is_relative_to existe desde Python 3.9 y el proyecto apunta a 3.8,
    asi que se compara por partes. Es el cinturon sobre los tirantes: los
    nombres ya se arman con identificadores validados, pero una comprobacion
    de contencion cuesta tres lineas y cubre el descuido de manana.
    """
    try:
        raiz = raiz.resolve()
        ruta = ruta.resolve()
    except OSError:
        return False
    return raiz == ruta or raiz in ruta.parents


def _archivo_de_documento(ctx, pmid, tipo):
    """Localiza en disco el texto o el PDF de un documento.

    La ruta se arma con el PMID y el PMCID de la base, los dos validados
    contra su patron, mas la convencion de nombres de CLAUDE.md. NUNCA
    se usa 'descargas.ruta': esa columna guarda una ruta relativa al
    directorio donde corrio el ETL, que no tiene por que ser el del
    servidor, y meter una cadena de la base en una ruta de disco es como se
    llega a servir un archivo que nadie queria servir.

    Devuelve None si el documento no tiene ese formato descargado.
    """
    if not PMID_VALIDO.match(pmid):
        return None
    fila = db.obtener_documento(ctx.con, pmid)
    if fila is None:
        return None

    raiz = Path(ctx.salida)
    if tipo == "pdf":
        ruta = raiz / "pdf" / (pmid + ".pdf")
    else:
        pmcid = fila["pmcid"] or ""
        if not PMCID_VALIDO.match(pmcid):
            return None
        ruta = raiz / "xml" / (pmid + "_" + pmcid + ".txt")

    if not _dentro_de(raiz, ruta) or not ruta.is_file():
        return None
    return ruta


def _texto_documento(ctx, pmid):
    """El texto completo extraido, como JSON.

    Va como JSON y no como archivo para que el tablero lo pinte con su
    helper y sin innerHTML: los articulos traen '<' y '>' de formulas y de
    nombres de genes. La mediana son 56 KB y el mayor 108 KB, asi que cabe
    de sobra en una respuesta.
    """
    ruta = _archivo_de_documento(ctx, pmid, "texto")
    if ruta is None:
        raise ErrorPeticion(404, f"no hay texto completo descargado de {pmid}")
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise ErrorPeticion(500, f"no se pudo leer el texto de {pmid}: {e}")
    return 200, {"pmid": pmid, "texto": texto, "caracteres": len(texto)}


def _pdf_documento(ctx, pmid):
    ruta = _archivo_de_documento(ctx, pmid, "pdf")
    if ruta is None:
        raise ErrorPeticion(404, f"no hay PDF descargado de {pmid}")
    return 200, Archivo(ruta, "application/pdf")


def _editar_documento(ctx, pmid, cuerpo):
    cuerpo = _objeto(cuerpo)
    # db.actualizar_documento ignora en silencio lo que no sea editable;
    # aqui se distingue "no mando nada util" de "no existe el documento",
    # que son 400 y 404 y no la misma cosa.
    if not any(c in cuerpo for c in db.COLUMNAS_EDITABLES):
        raise ErrorPeticion(
            400, "no se mandó ningún campo editable: "
                 + ", ".join(db.COLUMNAS_EDITABLES))
    for columna in db.COLUMNAS_EDITABLES:
        if columna in cuerpo and not isinstance(cuerpo[columna], str):
            raise ErrorPeticion(400, f"'{columna}' debe ser texto")

    if not db.actualizar_documento(ctx.con, pmid, cuerpo):
        raise ErrorPeticion(404, f"no existe el documento con PMID {pmid}")
    return 200, {"ok": True}


def _borrar_documento(ctx, pmid):
    if db.obtener_documento(ctx.con, pmid) is None:
        raise ErrorPeticion(404, f"no existe el documento con PMID {pmid}")
    return 200, {"borrados": db.borrar_documento(ctx.con, pmid)}


def _anios(ctx):
    return 200, db.anios_disponibles(ctx.con)


# --------------------------------------------------------------- descargas

def _listar_descargas(ctx, params):
    pagina, por_pagina = _paginacion(params)
    total, filas = db.listar_descargas(
        ctx.con, tipo=_param(params, "tipo"), estatus=_param(params, "estatus"),
        pagina=pagina, por_pagina=por_pagina,
    )
    return 200, {
        "total": total, "pagina": pagina, "por_pagina": por_pagina,
        "filas": [dict(f) for f in filas],
    }


def _borrar_descarga(ctx, pmid, tipo):
    if not db.borrar_descarga(ctx.con, pmid, tipo):
        raise ErrorPeticion(
            404, f"no hay descarga de tipo '{tipo}' para el PMID {pmid}")
    return 200, {"ok": True}


# -------------------------------------------------------------- ejecuciones

def _ejecuciones(ctx, params):
    n = _entero(params.get("n"), "n", minimo=1, maximo=MAX_EJECUCIONES) or 20
    filas = db.historial(ctx.con, _param(params, "nombre"), n)
    return 200, [dict(f) for f in filas]


# ----------------------------------------------------------------- trabajos

def _ver_trabajo(ctx):
    return 200, ctx.gestor.estado()


def _exigir_cliente(ctx):
    """El tablero arranca sin correo para poder ver y editar; lo que no se
    puede es salir a NCBI, que lo exige para identificar el tráfico. Solo
    lo piden los trabajos que salen a la red: el flujo es todo local."""
    if ctx.cliente is None:
        raise ErrorPeticion(
            400,
            "Falta el correo de contacto de NCBI. Ponlo en «Credenciales "
            "de NCBI», en el Panel, y se guarda para las próximas veces. "
            "NCBI lo exige en cada petición: es la dirección a la que "
            "avisan antes de bloquear la IP del laboratorio.")


# La prueba rápida del flujo existe para ver los pasos andar en minutos.
# Arriba de esto ya no es prueba, y sin tope una cifra con un cero de más
# llega intacta hasta los subprocesos.
LIMITE_FLUJO_MAX = 100000


def _pasos_del_cuerpo(cuerpo, clave, vacia_ok):
    """Una lista de pasos del flujo validada, o None si no llegó.

    Se devuelve en el orden de flujo.PASOS y sin repetidos: es lo que se
    publica en el estado del trabajo.
    """
    valor = cuerpo.get(clave)
    if valor is None:
        return None
    validos = ", ".join(flujo.PASOS)
    if not isinstance(valor, list) or not all(isinstance(p, str)
                                              for p in valor):
        raise ErrorPeticion(
            400, f"'{clave}' debe ser una lista de pasos: {validos}")
    desconocidos = [p for p in valor if p not in flujo.PASOS]
    if desconocidos:
        raise ErrorPeticion(
            400, f"'{clave}' trae pasos que no existen: "
                 f"{', '.join(desconocidos)}. Los pasos son: {validos}")
    if not valor and not vacia_ok:
        # flujo.correr toma una lista vacía como «todos». Quien desmarcó
        # todo no pidió eso.
        raise ErrorPeticion(
            400, f"'{clave}' no puede ir vacía; para correr todos los "
                 f"pasos, no la mandes")
    return [p for p in flujo.PASOS if p in valor]


def _argumentos_flujo(ctx, cuerpo):
    """Los kwargs de flujo.correr, sacados del cuerpo ya validados.

    Del cuerpo solo se toma qué correr. Dónde escribe (salida), de dónde lee
    (datos), el modelo y los intérpretes salen del servidor y nunca de la
    petición: un 'python_bert' que llegara por HTTP sería ejecutar el
    programa que diga quien mande la petición.
    """
    return {
        "corrida": _entero(cuerpo.get("corrida"), "corrida", minimo=1),
        "pasos": _pasos_del_cuerpo(cuerpo, "pasos", vacia_ok=False),
        "forzar": _pasos_del_cuerpo(cuerpo, "forzar", vacia_ok=True) or None,
        "limite": _entero(cuerpo.get("limite"), "limite", minimo=1,
                          maximo=LIMITE_FLUJO_MAX),
        "sin_reusar": not _booleano(cuerpo.get("reusar"), "reusar",
                                    omision=True),
        "salida": ctx.flujo_raiz,
        "datos": ctx.datos,
    }


def _cancelar_trabajo(ctx, cuerpo):
    # Se exige un cuerpo JSON aunque no traiga nada ({} basta). Un POST sin
    # cuerpo es una petición simple: cualquier página abierta en el mismo
    # navegador la puede mandar a 127.0.0.1 sin preflight, y cortaría el
    # flujo de quien lo esté corriendo. Con cuerpo, _leer_cuerpo exige
    # Content-Type JSON, que un formulario no sabe mandar.
    _objeto(cuerpo)
    if not ctx.gestor.cancelar():
        raise ErrorPeticion(
            409, "No hay un trabajo cancelable en curso. Solo el flujo se "
                 "puede cancelar; una corrida de PubMed o una descarga "
                 "terminan solas y retomarlas no repite lo hecho.")
    return 200, {"ok": True, "trabajo": ctx.gestor.estado()}


def _lanzar_trabajo(ctx, cuerpo):
    cuerpo = _objeto(cuerpo)
    tipo = _texto(cuerpo, "tipo", obligatorio=True)
    cancelable = False

    if tipo == "run":
        _exigir_cliente(ctx)
        nombre = _texto(cuerpo, "nombre", obligatorio=True)
        _consulta_por_nombre(ctx, nombre)          # 404 antes de lanzar nada
        orden = _texto(cuerpo, "orden") or "relevance"
        if orden not in ORDENES:
            raise ErrorPeticion(400, "'orden' debe ser " + " o ".join(ORDENES))
        argumentos = {
            "cliente": ctx.cliente,
            "nombre_consulta": nombre,
            "orden": orden,
            "limite": _entero(cuerpo.get("limite"), "limite", minimo=1),
            "mindate": _fecha(cuerpo, "desde"),
            "maxdate": _fecha(cuerpo, "hasta"),
        }
        funcion = etl.ingestar

    elif tipo == "fulltext":
        _exigir_cliente(ctx)
        tipo_archivo = _texto(cuerpo, "tipo_archivo", obligatorio=True)
        if tipo_archivo not in TIPOS_ARCHIVO:
            raise ErrorPeticion(
                400, "'tipo_archivo' debe ser " + " o ".join(TIPOS_ARCHIVO))
        nombre = _texto(cuerpo, "nombre")
        if nombre:
            _consulta_por_nombre(ctx, nombre)
        argumentos = {
            "cliente": ctx.cliente,
            "tipo": tipo_archivo,
            "nombre_consulta": nombre,
            "limite": _entero(cuerpo.get("limite"), "limite", minimo=1),
            "reintentar": _booleano(cuerpo.get("reintentar"), "reintentar"),
            "usar_unpaywall": not _booleano(cuerpo.get("sin_unpaywall"),
                                            "sin_unpaywall"),
            "salida": ctx.salida,
        }
        funcion = etl.descargar_fulltext

    elif tipo == "flujo":
        argumentos = _argumentos_flujo(ctx, cuerpo)
        funcion = flujo.correr
        # Cada paso es un proceso aparte que se puede matar; un run o un
        # fulltext corren en el hilo y no.
        cancelable = True

    else:
        raise ErrorPeticion(
            400, "'tipo' debe ser 'run', 'fulltext' o 'flujo'")

    # El gestor inyecta 'con' (su propia conexión, abierta en su hilo),
    # 'log' y, si es cancelable, 'detener'. Si ya hay uno corriendo lanza
    # TrabajoEnCurso, que arriba se traduce a 409.
    ctx.gestor.lanzar(tipo, funcion, cancelable=cancelable, **argumentos)
    return 202, {"ok": True, "trabajo": ctx.gestor.estado()}


# ------------------------------------------------------------------ flujo

# El tipo de cada extensión que flujo.ARCHIVO_VALIDO deja listar. Va
# explícito y con charset, no adivinado por mimetypes: el registro de
# Windows puede decir cualquier cosa de un .csv, y la cabecera nosniff hace
# que el navegador crea lo que aquí se diga.
TIPOS_FLUJO = {
    "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "jsonl": "application/x-ndjson; charset=utf-8",
    "log": "text/plain; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "xlsx": ("application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet"),
}

# Lo que con ?ver=1 se abre en la pestaña en vez de bajarse: los JSON de
# resumen, que el tablero lee para pintar las cifras, y flujo.log, que guarda
# entera la salida que la consola recorta a 400 líneas. Todo es texto que el
# navegador pinta como texto (con nosniff), nunca como HTML.
SE_PUEDEN_VER = ("json", "log", "txt")


def _ver_flujo(ctx):
    return 200, flujo.estado_general(ctx.con, ctx.flujo_raiz)


def _ver_carpeta_flujo(ctx, carpeta):
    datos = flujo.leer_carpeta(ctx.flujo_raiz, carpeta)
    if datos is None:
        raise ErrorPeticion(404, f"no existe la carpeta del flujo '{carpeta}'")
    return 200, datos


def _archivo_flujo(ctx, carpeta, nombre, params):
    """Una salida del flujo, como Archivo para descargar.

    La ruta la arma flujo.ruta_archivo: carpeta y nombre contra patrones
    cerrados, el archivo tiene que estar listado y quedar hijo directo de su
    carpeta. Aquí se comprueba otra vez que caiga dentro de la raíz del
    flujo, por si mañana alguien afloja el patrón.
    """
    ver = _booleano(params.get("ver"), "ver")
    ruta = flujo.ruta_archivo(ctx.flujo_raiz, carpeta, nombre)
    extension = nombre.rsplit(".", 1)[-1]
    if (ruta is None or extension not in TIPOS_FLUJO
            or not _dentro_de(Path(ctx.flujo_raiz), Path(ruta))):
        raise ErrorPeticion(
            404, f"no hay un archivo '{nombre}' en la carpeta '{carpeta}'")
    descarga = None if (ver and extension in SE_PUEDEN_VER) else nombre
    return 200, Archivo(ruta, TIPOS_FLUJO[extension], descarga_como=descarga)


# ------------------------------------------------------------------ ruteo

def _rutear(metodo, ruta, params, cuerpo, ctx):
    # Cada segmento se desescapa por separado: asi un %2f dentro de un PMID
    # no puede inventar un segmento nuevo.
    partes = [urllib.parse.unquote(p) for p in ruta.split("/") if p]

    if not partes:
        if metodo != "GET":
            _no_encontrado(metodo, ruta)
        # La ruta del archivo es fija y sale de __file__; no se compone con
        # nada de la peticion, asi que no hay '..' que sirva de nada.
        return 200, PAGINA

    if partes == ["logo.png"]:
        if metodo != "GET":
            _no_encontrado(metodo, ruta)
        return 200, LOGO

    if partes[0] != "api":
        # Cualquier otra cosa es 404 a proposito. Servir el directorio del
        # proyecto (SimpleHTTPRequestHandler y parecidos) expondria .key,
        # datos/ y el codigo entero a quien abra el navegador.
        #
        # Los archivos que si se sirven son una lista blanca de dos, cada uno
        # comparado por igualdad exacta contra su propia ruta fija. No hay
        # concatenacion con nada que venga de la peticion, asi que no existe
        # un '..' ni un %2e%2e que lleve a otro archivo.
        _no_encontrado(metodo, ruta)

    recurso = partes[1] if len(partes) > 1 else ""
    resto = partes[2:]

    if recurso == "config" and not resto:
        if metodo == "GET":
            return _ver_config(ctx)
        if metodo == "PUT":
            return _guardar_config(ctx, cuerpo)

    if recurso == "estado" and metodo == "GET" and not resto:
        return _estado(ctx)

    if recurso == "consultas":
        if not resto and metodo == "GET":
            return _listar_consultas(ctx)
        if not resto and metodo == "POST":
            return _alta_consulta(ctx, cuerpo)
        if len(resto) == 1 and metodo == "GET":
            return _ver_consulta(ctx, resto[0])
        if len(resto) == 1 and metodo == "PUT":
            return _editar_consulta(ctx, resto[0], cuerpo)
        if len(resto) == 1 and metodo == "DELETE":
            return _borrar_consulta(ctx, resto[0])

    if recurso == "documentos":
        if not resto and metodo == "GET":
            return _listar_documentos(ctx, params)
        if len(resto) == 1 and metodo == "GET":
            return _ver_documento(ctx, resto[0])
        if len(resto) == 1 and metodo == "PUT":
            return _editar_documento(ctx, resto[0], cuerpo)
        if len(resto) == 1 and metodo == "DELETE":
            return _borrar_documento(ctx, resto[0])
        # El segundo segmento es un nombre fijo que se compara por igualdad,
        # no algo que se concatene a una ruta.
        if len(resto) == 2 and metodo == "GET" and resto[1] == "texto":
            return _texto_documento(ctx, resto[0])
        if len(resto) == 2 and metodo == "GET" and resto[1] == "pdf":
            return _pdf_documento(ctx, resto[0])

    if recurso == "descargas":
        if not resto and metodo == "GET":
            return _listar_descargas(ctx, params)
        if len(resto) == 2 and metodo == "DELETE":
            return _borrar_descarga(ctx, resto[0], resto[1])

    if recurso == "ejecuciones" and metodo == "GET" and not resto:
        return _ejecuciones(ctx, params)

    if recurso == "anios" and metodo == "GET" and not resto:
        return _anios(ctx)

    if recurso == "trabajo":
        if not resto and metodo == "GET":
            return _ver_trabajo(ctx)
        if not resto and metodo == "POST":
            return _lanzar_trabajo(ctx, cuerpo)
        if resto == ["cancelar"] and metodo == "POST":
            return _cancelar_trabajo(ctx, cuerpo)

    # Tercera familia de rutas que entregan archivos, después del texto y el
    # PDF de un documento. Igual que allá, el nombre que llega no se pega a
    # una ruta sin más: 'archivos' se compara por igualdad, y carpeta y
    # nombre los valida flujo.ruta_archivo contra patrones cerrados.
    if recurso == "flujo" and metodo == "GET":
        if not resto:
            return _ver_flujo(ctx)
        if len(resto) == 1:
            return _ver_carpeta_flujo(ctx, resto[0])
        if len(resto) == 3 and resto[1] == "archivos":
            return _archivo_flujo(ctx, resto[0], resto[2], params)

    _no_encontrado(metodo, ruta)


def manejar(metodo, ruta, params, cuerpo, ctx):
    """Atiende una peticion ya parseada. Devuelve (codigo, objeto).

    'ruta' es el camino sin query string, 'params' el dict de la query
    string (un valor por llave, ya como cadena) y 'cuerpo' el JSON
    recibido o None. El objeto devuelto es lo que se serializa a JSON,
    salvo cuando es un Archivo, que dice "entrega este archivo".

    No abre sockets ni lee del disco: es una funcion como cualquier otra,
    y por eso las pruebas la llaman directo.
    """
    try:
        return _rutear(metodo, ruta, params or {}, cuerpo, ctx)
    except ErrorPeticion as e:
        return e.codigo, {"error": e.mensaje}
    except trabajos.TrabajoEnCurso as e:
        return 409, {"error": str(e)}
    except db.ErrorBase as e:
        # 'database is locked' es el caso realista (alguien corriendo el
        # CLI contra la misma base). Vale mas decirlo que esconderlo.
        # Se atrapa db.ErrorBase y no sqlite3.Error: aqui no se sabe que
        # motor hay debajo, y esa es justo la condicion para que migrar a
        # Postgres toque un solo archivo.
        return 500, {"error": f"error de la base de datos: {e}"}


# ------------------------------------------------------------------- HTTP

def host_permitido(host, puerto=None):
    """Si la cabecera Host nombra a esta máquina: 127.0.0.1 o localhost, con
    cualquier puerto o sin él.

    Escuchar solo en 127.0.0.1 no basta contra el DNS rebinding: una página
    hostil hace que su propio dominio resuelva a 127.0.0.1, queda en el mismo
    origen que el tablero y le manda JSON sin preflight. Lo que la delata es
    que el navegador sigue poniendo su dominio en Host. El puerto no ayuda y
    estorba: un túnel SSH a otro puerto local (`ssh -L 8766:127.0.0.1:8765`)
    o el reenvío de VS Code llegan con el puerto de la laptop, no con el del
    servidor. `puerto` queda por compatibilidad y no se usa.
    """
    if not host:
        return False
    nombre = re.sub(r":\d{1,5}$", "", host.strip().lower())
    return nombre in ("127.0.0.1", "localhost")


class ManejadorHTTP(http.server.BaseHTTPRequestHandler):
    """Envoltura de manejar(). Aqui no se decide nada de negocio."""

    # 1.1 para que el navegador reuse la conexion: el tablero sondea cada
    # 1.5 s y abrir un socket por sondeo es puro desperdicio. Obliga a
    # mandar Content-Length exacto en toda respuesta, cosa que se hace.
    protocol_version = "HTTP/1.1"
    server_version = "grn-tablero"
    sys_version = ""

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")

    def do_PUT(self):
        self._atender("PUT")

    def do_DELETE(self):
        self._atender("DELETE")

    def log_message(self, formato, *args):
        """Silencio. La terminal del servidor es para el arranque y para
        las fallas; una linea por sondeo la vuelve inservible."""

    # ---------------------------------------------------------- peticion

    def _atender(self, metodo):
        if not host_permitido(self.headers.get("Host")):
            # Antes de leer el cuerpo, y cerrando: lo que quede sin leer de
            # esta petición no puede tomarse por el principio de la siguiente.
            self.close_connection = True
            self._responder_json(403, {
                "error": "Host no permitido: el tablero solo atiende a "
                         "127.0.0.1 y localhost."})
            return
        url = urllib.parse.urlsplit(self.path)
        params = {k: v[-1] for k, v in
                  urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}

        try:
            cuerpo = self._leer_cuerpo()
        except ValueError as e:
            self._responder_json(400, {"error": str(e)})
            return

        con = None
        try:
            # Una conexion por peticion, cerrada al terminar. sqlite3
            # prohibe por omision usar una conexion desde otro hilo, y este
            # servidor atiende cada peticion en el suyo; compartir una sola
            # daria ProgrammingError. Es la misma decision que tomo
            # trabajos.Gestor, que abre la suya dentro del hilo del trabajo.
            con = db.conectar(self.server.ruta_db)
            servidor_obj = self.server

            def guardar_cliente(nuevo):
                servidor_obj.cliente = nuevo

            ctx = Contexto(con, self.server.gestor, self.server.cliente,
                           self.server.salida,
                           correo_explicito=self.server.correo_explicito,
                           al_cambiar_cliente=guardar_cliente,
                           flujo_raiz=self.server.flujo_raiz,
                           datos=self.server.datos)
            codigo, objeto = manejar(metodo, url.path, params, cuerpo, ctx)
        except Exception:
            # El detalle va a la terminal y no a la respuesta: un traceback
            # en el navegador no le sirve a nadie y puede arrastrar datos
            # que no tienen por que salir.
            traceback.print_exc()
            self._responder_json(500, {
                "error": "error interno del servidor; el detalle está en la "
                         "terminal donde corre servidor.py"})
            return
        finally:
            if con is not None:
                con.close()

        if isinstance(objeto, Archivo):
            self._responder_archivo(codigo, objeto)
        else:
            self._responder_json(codigo, objeto)

    def _leer_cuerpo(self):
        largo = self.headers.get("Content-Length")
        if not largo:
            return None
        try:
            n = int(largo)
        except ValueError:
            raise ValueError("Content-Length inválido")
        if n <= 0:
            return None
        if n > MAX_CUERPO:
            # No se lee lo que no se va a usar. Con la conexion reutilizada
            # el cuerpo sin leer se interpretaria como la siguiente
            # peticion, asi que se corta.
            self.close_connection = True
            raise ValueError("el cuerpo es demasiado grande")
        if not es_json(self.headers.get("Content-Type")):
            self.close_connection = True
            raise ValueError(
                "manda el cuerpo con Content-Type: application/json")
        crudo = self.rfile.read(n)
        try:
            return json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("el cuerpo no es JSON válido")

    # --------------------------------------------------------- respuesta

    def _responder_json(self, codigo, objeto):
        datos = json.dumps(objeto if objeto is not None else {},
                           ensure_ascii=False).encode("utf-8")
        self._encabezados(codigo, "application/json; charset=utf-8", len(datos))
        self.wfile.write(datos)

    def _responder_archivo(self, codigo, archivo):
        try:
            f = open(archivo.ruta, "rb")
        except OSError:
            # 404 y no 500: que falte el archivo no es una falla del
            # servidor. Pasa de verdad cuando el ETL corrio desde otro
            # directorio que el tablero, porque --salida no coincide.
            self._responder_json(404, {
                "error": f"no se encontró {archivo.ruta.name} en el disco. "
                         "Si el ETL corrió desde otra carpeta, arranca el "
                         "tablero con --salida apuntando a donde escribió."})
            return
        with f:
            # El largo sale del archivo ya abierto, no de leerlo entero: el
            # CSV de candidatas pesa ~90 MB y read_bytes() lo subía completo
            # a memoria en cada descarga.
            largo = os.fstat(f.fileno()).st_size
            self._encabezados(codigo, archivo.tipo_mime, largo,
                              descarga_como=archivo.descarga_como)
            # Se manda exactamente 'largo' y no hasta el fin del archivo
            # (que es lo que haría shutil.copyfileobj): flujo.log crece
            # mientras el flujo corre, y con HTTP/1.1 los bytes de más se
            # leerían como el principio de la siguiente respuesta.
            restante = largo
            try:
                while restante > 0:
                    bloque = f.read(min(BLOQUE_ARCHIVO, restante))
                    if not bloque:
                        break
                    self.wfile.write(bloque)
                    restante -= len(bloque)
            except ConnectionError:
                # Quien descargaba cerró la pestaña o canceló la descarga.
                # No es una falla del servidor y no amerita un traceback.
                self.close_connection = True
                return
            if restante:
                # El archivo se encogió a media entrega: lo prometido en
                # Content-Length ya no se puede cumplir. Cerrar es la única
                # forma de que el navegador no espere bytes que no vienen.
                self.close_connection = True

    def _encabezados(self, codigo, tipo, largo, descarga_como=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(largo))
        if descarga_como:
            # El nombre ya viene validado (flujo.ARCHIVO_VALIDO); se limpia
            # otra vez porque va dentro de una cabecera, donde un salto de
            # línea o unas comillas partirían la respuesta.
            limpio = re.sub(r"[^A-Za-z0-9_.-]", "_", str(descarga_como))
            self.send_header("Content-Disposition",
                             f'attachment; filename="{limpio}"')
        # Sin esto el navegador se queda con un tablero viejo despues de
        # actualizar el archivo, y con cifras congeladas entre sondeos.
        self.send_header("Cache-Control", "no-store")
        # El texto y el PDF son contenido de una editorial servido desde el
        # mismo origen que el tablero. Si un navegador lo olfateara como
        # HTML, ese HTML correria en 127.0.0.1 con acceso al API, que
        # incluye borrar documentos. El tipo va explicito; esto lo vuelve
        # garantia en vez de costumbre.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()


class Servidor(http.server.ThreadingHTTPServer):
    """El servidor con lo que comparten todas las peticiones."""

    daemon_threads = True      # un Ctrl-C no espera a los sondeos abiertos

    # En Windows SO_REUSEADDR deja que un segundo proceso se apodere de un
    # puerto que YA esta escuchando; bind() lo acepta sin chistar. Serian
    # dos servidores vivos, cada uno con su propio Gestor creyendo que es
    # el unico: dos trabajos a la vez, el limite de NCBI al doble (y NCBI
    # bloquea por IP, o sea a todo el laboratorio) y dos escritores sobre
    # SQLite. El candado de un-trabajo-a-la-vez es por proceso, asi que la
    # unica forma de sostenerlo es impedir el segundo proceso.
    # En Linux SO_REUSEADDR no permite apoderarse de un socket que escucha,
    # y ahi si sirve para no esperar el TIME_WAIT al reiniciar: se deja.
    allow_reuse_address = (sys.platform != "win32")

    def __init__(self, puerto, ruta_db, gestor, cliente, salida,
                 correo_explicito=None, flujo_raiz=None, datos=None):
        self.ruta_db = ruta_db
        self.gestor = gestor
        self.cliente = cliente
        self.salida = salida
        self.correo_explicito = correo_explicito
        self.flujo_raiz = flujo_raiz
        self.datos = datos
        # 127.0.0.1 y nada mas. Ver el docstring del modulo: sin
        # autenticacion, con capacidad de borrar y de gastar el limite de
        # NCBI de todo el laboratorio, atarlo a 0.0.0.0 seria abrirle eso a
        # la red entera.
        super().__init__(("127.0.0.1", puerto), ManejadorHTTP)


# ------------------------------------------------------------------- main

def detener_al_cerrar(gestor, espera=ESPERA_CIERRE, log=lambda m: None):
    """Al cerrar el tablero, deja en orden el trabajo que siga corriendo.

    El hilo del trabajo es daemon y muere con el proceso, pero los pasos del
    flujo son procesos aparte, nacidos en su propio grupo para que el Ctrl-C
    de la terminal no los alcance. Si el tablero se cerrara sin más, el paso
    en curso seguiría corriendo huérfano (con la GPU ocupada, si es BioBERT)
    y el candado .flujo.lock de su carpeta impediría la siguiente corrida.
    Cancelar mata el árbol, y el flujo alcanza a escribir estado.json y a
    soltar el candado.

    Devuelve True si al final no quedó nada corriendo.
    """
    estado = gestor.estado()
    if not estado["activo"]:
        return True
    if not gestor.cancelar():
        log("Había un trabajo en curso: se corta aquí. Su ejecución queda\n"
            "marcada 'corriendo' en la bitácora; el ETL es idempotente,\n"
            "así que volver a lanzarla retoma lo que falte.")
        return False
    log(f"Había un trabajo '{estado['tipo']}' en curso: se pidió cancelarlo "
        f"y se espera hasta {espera} s a que se detenga.")
    try:
        termino = gestor.esperar(espera)
    except KeyboardInterrupt:
        termino = False
    if termino:
        log("Se detuvo. Lo hecho quedó guardado; volver a lanzarlo retoma "
            "donde se quedó.")
    else:
        log("No se detuvo a tiempo y el tablero se cierra igual. Puede quedar\n"
            "un proceso hijo vivo; si el flujo no vuelve a arrancar, borra el\n"
            "archivo .flujo.lock de su carpeta.")
    return termino


# Cómo se dice en la terminal de dónde salió la raíz de datos.
ORIGEN_DATOS = {"flag": "por --datos", "omision": "por omisión"}


def main():
    ap = argparse.ArgumentParser(
        description="Tablero local del ETL. Escucha solo en 127.0.0.1.")
    ap.add_argument("--datos", default=None,
                    help="Raíz de datos; gana sobre GRN_DATOS "
                         "(por omisión, ./datos).")
    ap.add_argument("--db", default=None,
                    help="Ruta de la base SQLite (por omisión, "
                         "<datos>/grn.db).")
    ap.add_argument("--puerto", type=int, default=PUERTO_POR_OMISION)
    ap.add_argument("--email", help="Correo de contacto para NCBI.")
    ap.add_argument("--salida", default=None,
                    help="Raíz donde el fulltext escribe (por omisión, "
                         "<datos>/fulltext).")
    ap.add_argument("--flujo", default=flujo.RAIZ_FLUJO,
                    help="Raíz de las carpetas del flujo (por omisión, "
                         "salidas/flujo del repositorio).")
    ap.add_argument("--abrir", action="store_true",
                    help="Abrir el navegador al arrancar.")
    args = ap.parse_args()

    # La precedencia de siempre: flag, luego GRN_DATOS, luego ./datos. Un
    # --db o un --salida explícitos ganan sobre la raíz para su archivo.
    raiz_datos = rutas.raiz_datos(args.datos)
    ruta_db = args.db or os.path.join(raiz_datos, "grn.db")
    salida = args.salida or salida_por_omision(args.datos)
    flujo_raiz = os.path.abspath(args.flujo)
    # El flujo lee su base de <datos>/grn.db. Si --db apunta a otra, el
    # tablero listaría corridas del bronce que el flujo no encuentra.
    db_del_flujo = os.path.join(raiz_datos, "grn.db")
    db_distinta = os.path.abspath(ruta_db) != os.path.abspath(db_del_flujo)

    # Crear el esquema una vez aqui evita que la primera peticion se
    # encuentre una base vacia a medio construir.
    db.conectar(ruta_db).close()

    # Lee el entorno y, si no hay nada ahi, los archivos de la raiz. Eso
    # es lo que evita tener que exportar la llave a mano en cada sesion.
    email = credenciales.correo(args.email)
    api_key = credenciales.llave()

    # Un solo Cliente para todo el servidor, reusado por todos los
    # trabajos. El control de tasa vive en la instancia (pubmed.Cliente
    # _ultima), asi que una instancia unica mas un trabajo a la vez es lo
    # que de verdad hace que se respete el limite de NCBI. Dos instancias
    # creerian cada una que va sola y entre las dos lo rebasarian; NCBI
    # bloquea por IP y el bloqueo lo pagaria todo el laboratorio.
    cliente = pubmed.Cliente(email, api_key) if email else None
    gestor = trabajos.Gestor(ruta_db)

    try:
        servidor = Servidor(args.puerto, ruta_db, gestor, cliente, salida,
                            correo_explicito=args.email,
                            flujo_raiz=flujo_raiz,
                            datos=os.path.abspath(raiz_datos))
    except OSError as e:
        sys.exit(f"No se pudo abrir el puerto {args.puerto}: {e}\n"
                 f"Si ya hay otro tablero corriendo, usa --puerto.")

    origen = rutas.de_donde(args.datos)
    url = f"http://127.0.0.1:{args.puerto}/"
    banner = [
        f"Tablero en {url}",
        f"Datos  : {raiz_datos} "
        f"({ORIGEN_DATOS.get(origen, origen.replace('entorno:', 'por '))})",
        f"Base   : {ruta_db}",
        f"Salida : {salida}",
        f"Flujo  : {flujo_raiz}",
        # Se dice si hay API key, nunca cual.
        "API key: " + ("sí (10 peticiones/segundo)"
                       if api_key else "no (3 peticiones/segundo)"),
        f"Correo : {email}" if cliente else
        "Correo : sin configurar. Se puede ver y editar, pero no lanzar\n"
        "         trabajos que salen a PubMed. Usa --email o NCBI_EMAIL.",
        "Escucha solo en 127.0.0.1; nadie más de la red lo alcanza.",
        "Ctrl-C para salir.",
    ]
    if db_distinta:
        banner.insert(4, f"Ojo    : el flujo usa {db_del_flujo}, no --db. "
                         f"Para que coincidan, usa --datos.")
    # flush porque el proceso no termina nunca: sin el, redirigir la salida
    # a un archivo deja el archivo vacio hasta que se llena el buffer.
    print("\n".join(banner), flush=True)

    if args.abrir:
        webbrowser.open(url)

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando.", flush=True)
    finally:
        servidor.server_close()
        detener_al_cerrar(gestor, log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
