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
llega, llama a db o a etl y formatea JSON. Cero SQL propio.
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

from grn_etl import db, etl, pubmed, trabajos

# El tablero es un solo archivo, sin recursos externos. La ruta se resuelve
# contra __file__ y no contra el directorio de trabajo: asi 'python
# servidor.py' funciona igual desde donde sea.
RUTA_PAGINA = Path(__file__).resolve().parent / "web" / "index.html"

PUERTO_POR_OMISION = 8765
SALIDA_POR_OMISION = "datos/fulltext"

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
    """

    def __init__(self, con, gestor, cliente=None, salida=SALIDA_POR_OMISION):
        self.con = con
        self.gestor = gestor
        self.cliente = cliente
        self.salida = salida


class Archivo:
    """Marca que la respuesta es un archivo de disco y no JSON.

    manejar() no lee nada del disco: devuelve esta marca y quien la
    envuelve decide como entregarla. Eso la deja probable sin tocar el
    sistema de archivos.
    """

    def __init__(self, ruta, tipo_mime):
        self.ruta = ruta
        self.tipo_mime = tipo_mime


PAGINA = Archivo(RUTA_PAGINA, "text/html; charset=utf-8")


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

def _estado(ctx):
    r = db.resumen(ctx.con)
    return 200, {
        "consultas": r["consultas"],
        "documentos": r["documentos"],
        "con_abstract": r["con_abstract"],
        "vinculos": r["vinculos"],
        "descargas": [dict(f) for f in r["descargas"]],
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
    return 200, doc


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


def _lanzar_trabajo(ctx, cuerpo):
    cuerpo = _objeto(cuerpo)
    tipo = _texto(cuerpo, "tipo", obligatorio=True)

    if ctx.cliente is None:
        # El tablero arranca sin correo para poder ver y editar; lo que no
        # se puede es salir a NCBI, que lo exige para identificar el
        # trafico.
        raise ErrorPeticion(
            400, "falta el correo de contacto de NCBI: arranca el servidor con "
                 "--email o con la variable de entorno NCBI_EMAIL. Sin él se "
                 "puede ver y editar, pero no lanzar trabajos.")

    if tipo == "run":
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

    else:
        raise ErrorPeticion(400, "'tipo' debe ser 'run' o 'fulltext'")

    # El gestor inyecta 'con' (su propia conexion, abierta en su hilo) y
    # 'log'. Si ya hay uno corriendo lanza TrabajoEnCurso, que arriba se
    # traduce a 409.
    ctx.gestor.lanzar(tipo, funcion, **argumentos)
    return 202, {"ok": True, "trabajo": ctx.gestor.estado()}


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

    if partes[0] != "api":
        # Cualquier otra cosa es 404 a proposito. Servir el directorio del
        # proyecto (SimpleHTTPRequestHandler y parecidos) expondria .key,
        # datos/ y el codigo entero a quien abra el navegador.
        _no_encontrado(metodo, ruta)

    recurso = partes[1] if len(partes) > 1 else ""
    resto = partes[2:]

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

    if recurso == "descargas":
        if not resto and metodo == "GET":
            return _listar_descargas(ctx, params)
        if len(resto) == 2 and metodo == "DELETE":
            return _borrar_descarga(ctx, resto[0], resto[1])

    if recurso == "ejecuciones" and metodo == "GET" and not resto:
        return _ejecuciones(ctx, params)

    if recurso == "anios" and metodo == "GET" and not resto:
        return _anios(ctx)

    if recurso == "trabajo" and not resto:
        if metodo == "GET":
            return _ver_trabajo(ctx)
        if metodo == "POST":
            return _lanzar_trabajo(ctx, cuerpo)

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
            ctx = Contexto(con, self.server.gestor, self.server.cliente,
                           self.server.salida)
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
            datos = archivo.ruta.read_bytes()
        except OSError:
            self._responder_json(500, {
                "error": f"no se encontró {archivo.ruta.name}; el tablero se "
                         "sirve desde web/index.html"})
            return
        self._encabezados(codigo, archivo.tipo_mime, len(datos))
        self.wfile.write(datos)

    def _encabezados(self, codigo, tipo, largo):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(largo))
        # Sin esto el navegador se queda con un tablero viejo despues de
        # actualizar el archivo, y con cifras congeladas entre sondeos.
        self.send_header("Cache-Control", "no-store")
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

    def __init__(self, puerto, ruta_db, gestor, cliente, salida):
        self.ruta_db = ruta_db
        self.gestor = gestor
        self.cliente = cliente
        self.salida = salida
        # 127.0.0.1 y nada mas. Ver el docstring del modulo: sin
        # autenticacion, con capacidad de borrar y de gastar el limite de
        # NCBI de todo el laboratorio, atarlo a 0.0.0.0 seria abrirle eso a
        # la red entera.
        super().__init__(("127.0.0.1", puerto), ManejadorHTTP)


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Tablero local del ETL. Escucha solo en 127.0.0.1.")
    ap.add_argument("--db", default="datos/grn.db", help="Ruta de la base SQLite.")
    ap.add_argument("--puerto", type=int, default=PUERTO_POR_OMISION)
    ap.add_argument("--email", help="Correo de contacto para NCBI.")
    ap.add_argument("--salida", default=SALIDA_POR_OMISION,
                    help="Raíz donde el fulltext escribe.")
    ap.add_argument("--abrir", action="store_true",
                    help="Abrir el navegador al arrancar.")
    args = ap.parse_args()

    # Crear el esquema una vez aqui evita que la primera peticion se
    # encuentre una base vacia a medio construir.
    db.conectar(args.db).close()

    email = args.email or os.environ.get("NCBI_EMAIL")
    api_key = os.environ.get("NCBI_API_KEY")

    # Un solo Cliente para todo el servidor, reusado por todos los
    # trabajos. El control de tasa vive en la instancia (pubmed.Cliente
    # _ultima), asi que una instancia unica mas un trabajo a la vez es lo
    # que de verdad hace que se respete el limite de NCBI. Dos instancias
    # creerian cada una que va sola y entre las dos lo rebasarian; NCBI
    # bloquea por IP y el bloqueo lo pagaria todo el laboratorio.
    cliente = pubmed.Cliente(email, api_key) if email else None
    gestor = trabajos.Gestor(args.db)

    try:
        servidor = Servidor(args.puerto, args.db, gestor, cliente, args.salida)
    except OSError as e:
        sys.exit(f"No se pudo abrir el puerto {args.puerto}: {e}\n"
                 f"Si ya hay otro tablero corriendo, usa --puerto.")

    url = f"http://127.0.0.1:{args.puerto}/"
    banner = [
        f"Tablero en {url}",
        f"Base   : {args.db}",
        f"Salida : {args.salida}",
        # Se dice si hay API key, nunca cual.
        "API key: " + ("sí (10 peticiones/segundo)"
                       if api_key else "no (3 peticiones/segundo)"),
        f"Correo : {email}" if cliente else
        "Correo : sin configurar. Se puede ver y editar, pero no lanzar\n"
        "         trabajos. Usa --email o la variable NCBI_EMAIL.",
        "Escucha solo en 127.0.0.1; nadie más de la red lo alcanza.",
        "Ctrl-C para salir.",
    ]
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
        if gestor.estado()["activo"]:
            print("Había un trabajo en curso: se corta aquí. Su ejecución queda\n"
                  "marcada 'corriendo' en la bitácora; el ETL es idempotente,\n"
                  "así que volver a lanzarla retoma lo que falte.", flush=True)


if __name__ == "__main__":
    main()
