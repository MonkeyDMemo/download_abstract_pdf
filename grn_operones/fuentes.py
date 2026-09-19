# -*- coding: utf-8 -*-
"""Las cuatro fuentes de operones de PAO1. Descarga cruda y fechada.

Cada fuente hace dos cosas separadas a proposito: **traer** los bytes y
**parsearlos**. Traer se hace una vez y se guarda; parsear se rehace tantas
veces como haga falta sobre los mismos bytes. Si las dos estuvieran juntas,
corregir un parser costaria una descarga contra bases academicas pequenas que
no tienen por que pagar nuestros errores.

LOS PARSERS QUE FALTAN, Y POR QUE NO SE INVENTAN
================================================
De las cuatro fuentes solo se conoce con certeza el formato de BioCyc, que
devuelve el XML de BioVelo. ODB entrega HTML que puede venir renderizado por
JavaScript; el archivo de Pseudomonas.com y el volcado de CDBProm no se han
visto todavia.

Escribir esos parsers a ciegas produciria codigo que parece funcionar y
devuelve cero filas, que es la peor forma de fallar: silenciosa y con pinta de
correcta. En vez de eso, `inspeccionar()` dice **que llego de verdad** --tipo,
tamano, si trae tablas, si trae JSON-- y los parsers que faltan levantan
`FormatoDesconocido` con esa descripcion en el mensaje. Es la tarea 1 del
encargo: verificar cada fuente con una corrida real y reportar lo que devuelve.

Solo biblioteca estandar.
"""

import io
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser

from grn_operones import db as _db
from grn_operones import red

# `rutas` vive en `grn_bronce` y se importa en vez de copiarse: la precedencia
# de `GRN_DATOS` tiene que estar escrita en un solo sitio, y dos copias que
# divergen es el defecto que este proyecto no se puede permitir. Su sitio
# natural es `grn_comun/`, que es justo "lo que usan los tres pasos"; moverlo
# toca los imports de `grn_bronce` y se deja anotado en vez de hacerlo de paso.
from grn_bronce import rutas

TAXID = "208964"
ORGID_BIOCYC = "PAER208964"
GENOMA = "NC_002516.2"

FUENTES = ("odb", "biocyc", "pgd", "cdbprom")

# El volcado de texto plano que el propio sitio ofrece en la pagina de la
# tabla ("Download Known Operons (Plain text)"). Es UNA peticion en vez de
# paginar, y es la via que el sitio quiere que se use.
#
# La paginacion HTML que se intento primero no sirve, y la razon merece
# quedar escrita: **ODB v4 es una aplicacion de JavaScript**. `GET /known`
# devuelve 689 bytes de esqueleto --`<div id="app"></div>` mas un `<script>`--
# sin un solo dato, y cualquier ruta del sitio devuelve ese mismo esqueleto,
# `robots.txt` incluido. Un parser sobre ese HTML habria devuelto cero filas
# para siempre. Comprobado el 18 de septiembre de 2026.
URL_ODB = "https://operondb.jp/download/known_operon.download.txt"
URL_ODB_TABLA = "https://operondb.jp/known"
URL_BIOCYC_LOGIN = "https://websvc.biocyc.org/credentials/login/"
URL_BIOCYC_QUERY = "https://websvc.biocyc.org/xmlquery"

# Las dos fuentes cuyo archivo no tiene URL estable publica. La del asesor
# llega como volcado; la de Pseudomonas.com hay que localizarla (tarea 2).
VAR_PGD = "PGD_OPERONES_URL"
VAR_CDBPROM = "CDBPROM_URL"

LOCUS = re.compile(r"\bPA\d{4}(?:\.\d)?\b")


class FormatoDesconocido(Exception):
    """Llegaron bytes pero no se sabe leerlos. No es un fallo de red."""


# ------------------------------------------------------------------- utiles

def carpeta_cruda(fuente, flag_datos=None, dia=None):
    """`<GRN_DATOS>/operones_crudo/<fuente>/<fecha>/`, creada si no esta.

    Bajo la raiz de datos y no en `datos/` a secas: en la maquina del
    laboratorio `GRN_DATOS` apunta fuera del repositorio, y una ruta literal
    dejaria estas descargas dentro del clon.
    """
    ruta = os.path.join(rutas.raiz_datos(flag_datos), "operones_crudo", fuente,
                        dia or date.today().isoformat())
    os.makedirs(ruta, exist_ok=True)
    return ruta


def guardar_crudo(carpeta, nombre, cuerpo):
    """Escritura atomica: primero `.tmp` y despues `os.replace`."""
    destino = os.path.join(carpeta, nombre)
    tmp = destino + ".tmp"
    with io.open(tmp, "wb") as f:
        f.write(cuerpo)
    os.replace(tmp, destino)
    return destino


def credenciales_biocyc():
    """(email, password) del entorno. Nunca del codigo ni de un archivo.

    BioCyc no tiene, como NCBI, un archivo de credenciales previsto en el
    proyecto, asi que aqui solo se admite el entorno. El valor no se imprime
    ni se anota en la base en ningun punto.
    """
    email = os.environ.get("BIOCYC_EMAIL")
    clave = os.environ.get("BIOCYC_PASSWORD")
    if not email or not clave:
        raise ErrorCredenciales(
            "BioCyc necesita BIOCYC_EMAIL y BIOCYC_PASSWORD en el entorno. "
            "No se leen de ningun archivo ni se escriben en la base.")
    return email, clave


class ErrorCredenciales(Exception):
    """Falta una credencial. Se distingue de un fallo de red a proposito."""


# ------------------------------------------------------------- inspeccionar

class _Tablas(HTMLParser):
    """Cuenta tablas y filas de un HTML. Solo para describir lo que llego."""

    def __init__(self):
        HTMLParser.__init__(self)
        self.tablas = 0
        self.filas = 0
        self.celdas = 0
        self.scripts = 0
        self.divs = 0
        self.texto = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tablas += 1
        elif tag == "tr":
            self.filas += 1
        elif tag in ("td", "th"):
            self.celdas += 1
        elif tag == "script":
            self.scripts += 1
        elif tag == "div":
            self.divs += 1

    def handle_data(self, datos):
        if datos.strip():
            self.texto += len(datos.strip())


def inspeccionar(cuerpo):
    """Que son estos bytes, en una linea. Es la salida de la tarea 1.

    No intenta parsear: intenta **describir**, que es lo que hace falta para
    decidir si una fuente entrega datos o entrega una pagina vacia que los
    carga por JavaScript despues.
    """
    d = {"bytes": len(cuerpo)}
    try:
        texto = cuerpo.decode("utf-8")
    except UnicodeDecodeError:
        d["tipo"] = "binario"
        return d

    recorte = texto[:4096].lstrip()
    d["empieza"] = recorte[:60].replace("\n", " ")

    if recorte[:1] in "{[":
        try:
            json.loads(texto)
            d["tipo"] = "json"
            return d
        except ValueError:
            pass
    if recorte[:5].lower() in ("<?xml", "<rdf:") or recorte.startswith("<ptools"):
        d["tipo"] = "xml"
        return d
    if "<html" in recorte.lower() or "<!doctype html" in recorte.lower():
        p = _Tablas()
        p.feed(texto)
        d.update(tipo="html", tablas=p.tablas, filas=p.filas,
                 celdas=p.celdas, scripts=p.scripts,
                 texto_visible=p.texto)
        d["locus_tags_visibles"] = len(set(LOCUS.findall(texto)))
        # HTML que no lleva datos, en sus dos formas. La primera version de
        # esto exigia `tablas > 0` y se le escapo el caso real: ODB v4 es una
        # aplicacion de JavaScript y su esqueleto no tiene NINGUNA tabla, solo
        # un `<div id="app">` vacio y un `<script>`. Exigir tabla era suponer
        # que el sitio al menos intenta renderizar algo en el servidor.
        d["sin_datos"] = (not d["locus_tags_visibles"] and p.filas <= 1)
        d["parece_render_js"] = bool(
            d["sin_datos"] and p.scripts and p.texto < 200)
        return d
    lineas = [l for l in texto.splitlines() if l.strip()]
    d["tipo"] = "texto"
    d["lineas"] = len(lineas)
    if lineas:
        d["separador"] = ("tabulador" if "\t" in lineas[0]
                          else "coma" if "," in lineas[0] else "?")
    d["locus_tags_visibles"] = len(set(LOCUS.findall(texto)))
    return d


# --------------------------------------------------------------------- ODB

def traer_odb(sesion, carpeta, max_paginas=None, log=lambda m: None):
    """Trae el volcado completo de operones conocidos. Una sola peticion.

    `max_paginas` se conserva en la firma pero ya no se usa: la paginacion
    HTML no da datos y la sustituye este volcado. Se deja para no romper a
    quien llame con el argumento.
    """
    cuerpo = sesion.pedir(URL_ODB, timeout=300)
    if cuerpo is None:
        log("  [odb] la fuente contesto que no")
        return []
    ruta = guardar_crudo(carpeta, "known_operon.download.txt", cuerpo)
    log("  [odb] %s  (%d bytes)" % (ruta, len(cuerpo)))
    return [(URL_ODB, ruta, cuerpo)]


# Las seis columnas del volcado, comprobadas contra el archivo real del
# 18-sep-2026: 9 480 filas, 33 de ellas del taxid de PAO1.
COLUMNAS_ODB = ["koid", "org", "name", "op", "definition", "source"]


def parsear_odb(cuerpo, taxid=TAXID):
    """Los operones de PAO1 del volcado de ODB.

    El archivo trae todos los organismos, asi que se filtra por `org`, que es
    el taxid. `op` son los locus tags separados por coma --de PAO1 salen como
    `PA3569,PA3570`-- y `source` es el PMID del articulo que sostiene el
    operon, que es lo que hace de ODB la unica fuente con evidencia de
    literatura directa.

    Se exige el encabezado del contrato: si ODB cambia el formato, esto falla
    en vez de leer columnas corridas en silencio.
    """
    texto = cuerpo.decode("utf-8", "replace")
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        raise FormatoDesconocido("odb: el volcado llego vacio")
    cabecera = lineas[0].split("	")
    if cabecera != COLUMNAS_ODB:
        raise FormatoDesconocido(
            "odb: encabezado %r; el contrato pide %r. El volcado cambio de "
            "formato y el parseo se detiene en vez de leer columnas corridas."
            % (cabecera, COLUMNAS_ODB))

    filas = []
    for linea in lineas[1:]:
        partes = linea.split("	")
        partes += [""] * (len(COLUMNAS_ODB) - len(partes))
        d = dict(zip(COLUMNAS_ODB, partes))
        if d["org"].strip() != taxid:
            continue
        genes = [g.strip() for g in d["op"].split(",") if g.strip()]
        if not genes:
            continue
        crudo = {}
        if d["name"].strip():
            crudo["name"] = d["name"].strip()
        if d["definition"].strip():
            crudo["definition"] = d["definition"].strip()
        filas.append({
            "fuente": "odb",
            "id_fuente": d["koid"].strip(),
            # `genes_raw` queda vacio, como en BioCyc y por el mismo motivo:
            # esta columna es para los nombres de GEN tal como los escribio la
            # fuente, y ODB no da nombres de gen. Da locus tags en `op` y, en
            # `name`, el nombre del OPERON (`mmsAB`, `mexAB-oprM`), que es una
            # etiqueta y no una lista de genes. Ponerlo aqui hacia que la
            # cobertura de mapeo diera 3.2 %, alarmante y falso: no hay nada
            # que mapear porque el locus tag ya viene resuelto. El nombre va a
            # `registro_raw` y de ahi lo toma la capa curada.
            "genes_raw": None,
            "locus_tags": "|".join(genes),
            "cadena": None,
            "tipo_evidencia": "literatura",
            # ODB separa varios PMID con espacios; el resto del
            # proyecto usa ";" y la capa curada parte por ese.
            "pmid": ";".join(d["source"].split()) or None,
            "registro_raw": crudo or None,
        })
    if not filas:
        raise FormatoDesconocido(
            "odb: el volcado tiene %d filas pero ninguna del taxid %s"
            % (len(lineas) - 1, taxid))
    return filas


# ------------------------------------------------------------------ BioCyc

def entrar_biocyc(sesion):
    """Inicia sesion. La cookie queda en la sesion, no se devuelve ni se anota."""
    email, clave = credenciales_biocyc()
    cuerpo = sesion.pedir(URL_BIOCYC_LOGIN,
                          datos={"email": email, "password": clave})
    if cuerpo is None:
        raise ErrorCredenciales(
            "BioCyc rechazo las credenciales (el servidor contesto que no). "
            "Comprueba BIOCYC_EMAIL y BIOCYC_PASSWORD, y que la cuenta tenga "
            "acceso a %s." % ORGID_BIOCYC)


def traer_biocyc(sesion, carpeta, log=lambda m: None):
    """Las dos consultas BioVelo: unidades de transcripcion y genes."""
    salida = []
    for nombre, consulta in (
            ("tus.xml", "[x:x<-%s^^Transcription-Units]" % ORGID_BIOCYC),
            ("genes.xml", "[x:x<-%s^^Genes]" % ORGID_BIOCYC)):
        params = {"query": consulta, "detail": "full"}
        # La URL que se REGISTRA lleva los parametros, y eso no es cosmetico.
        # Las dos consultas de BioVelo van al mismo endpoint `/xmlquery` y solo
        # se distinguen por `query`: registrando el endpoint pelado, la clave
        # `(extraccion_id, url)` las daba por el mismo archivo y la segunda
        # caia por DO NOTHING. Paso de verdad el 18-sep-2026: `genes.xml`, de
        # 9 MB, quedo en disco sin fila de procedencia.
        url_registrada = "%s?%s" % (URL_BIOCYC_QUERY,
                                    urllib.parse.urlencode(params))
        cuerpo = sesion.pedir(URL_BIOCYC_QUERY, params=params, timeout=600)
        if cuerpo is None:
            raise ErrorCredenciales(
                "BioCyc contesto que no a la consulta de %s. Lo habitual es "
                "que la cuenta no tenga acceso a %s, que requiere "
                "suscripcion." % (nombre, ORGID_BIOCYC))
        ruta = guardar_crudo(carpeta, nombre, cuerpo)
        salida.append((url_registrada, ruta, cuerpo))
        log("  [biocyc] %s  (%d bytes)" % (nombre, len(cuerpo)))
    return salida


def parsear_biocyc(xml_tus, xml_genes):
    """[{id_fuente, locus_tags, tipo_evidencia, ...}] de las TUs de BioCyc.

    El XML nombra los genes por `frameid`, que es interno de BioCyc, y el
    locus tag va en `accession-1`. Sin ese puente las TUs no se pueden cruzar
    con nada: se construye primero el mapa desde el XML de genes.
    """
    raiz_genes = ET.fromstring(xml_genes)
    frame_a_locus = {}
    for g in raiz_genes.iter("Gene"):
        acc = g.findtext("accession-1")
        if g.get("frameid") and acc:
            frame_a_locus[g.get("frameid")] = acc.strip()

    raiz_tus = ET.fromstring(xml_tus)
    filas = []
    for tu in raiz_tus.iter("Transcription-Unit"):
        evid = sorted(set(e.get("frameid", "")
                          for e in tu.iter("Evidence-Code") if e.get("frameid")))
        locus, sin_mapear = [], []
        for comp in tu.findall("component/Gene"):
            fid = comp.get("frameid")
            if frame_a_locus.get(fid):
                locus.append(frame_a_locus[fid])
            elif fid:
                sin_mapear.append(fid)
        if not locus:
            continue
        frameids = [c.get("frameid") or ""
                    for c in tu.findall("component/Gene")]
        crudo = {"frameids": frameids}
        if sin_mapear:
            crudo["sin_mapear"] = sin_mapear
        filas.append({
            "fuente": "biocyc",
            "id_fuente": tu.get("frameid"),
            # `genes_raw` queda vacio a proposito. Esta columna es para los
            # nombres de gen **tal como los escribio la fuente**, y BioCyc no
            # escribe nombres: escribe `frameid` internos (`G-1`) que no
            # identifican nada fuera de su base. Ponerlos aqui hacia que la
            # medicion de cobertura de mapeo diera 0 % para BioCyc, que es
            # alarmante y falso: BioCyc entrega el locus tag resuelto en
            # `accession-1` y no hay ningun nombre que mapear. Los frameids se
            # conservan en `registro_raw`, que es donde va lo que la fuente
            # dijo y nosotros no interpretamos.
            "genes_raw": None,
            "locus_tags": "|".join(locus),
            "cadena": None,
            "tipo_evidencia": ";".join(evid) or None,
            "pmid": None,
            "registro_raw": crudo,
        })
    return filas


# ------------------------------------------------------------ PGD y CDBProm

def traer_archivo(sesion, fuente, var_entorno, carpeta, url=None,
                  log=lambda m: None):
    """Baja un archivo cuya URL llega por flag o por entorno.

    Pseudomonas.com y CDBProm no tienen una URL estable que se pueda fijar en
    el codigo: la primera hay que localizarla (tarea 2) y la segunda es un
    volcado que entrega el asesor. Mientras no las haya, la fuente se omite
    con un aviso en vez de fallar la corrida entera.
    """
    url = url or os.environ.get(var_entorno)
    if not url:
        log("  [%s] omitida: define %s o pasa --url" % (fuente, var_entorno))
        return []
    cuerpo = sesion.pedir(url, timeout=600)
    if cuerpo is None:
        log("  [%s] la fuente contesto que no (403/404). No se reintenta: "
            "evadir una deteccion de bots esta fuera de alcance." % fuente)
        return []
    nombre = url.rstrip("/").split("/")[-1].split("?")[0] or ("%s.dat" % fuente)
    ruta = guardar_crudo(carpeta, nombre, cuerpo)
    log("  [%s] %s  (%d bytes)" % (fuente, ruta, len(cuerpo)))
    return [(url, ruta, cuerpo)]


def parsear_tabular(cuerpo, fuente):
    """Parser generico para un volcado tabular con locus tags.

    Sirve para PGD y CDBProm mientras no se vea el formato real: reconoce
    separador por tabulador o coma, busca la columna que trae locus tags de
    PAO1 y levanta con una descripcion si no la encuentra. No adivina cual es
    el identificador del operon, porque inventarlo produciria ids que no
    corresponden a nada en la fuente.
    """
    d = inspeccionar(cuerpo)
    if not d.get("locus_tags_visibles"):
        raise FormatoDesconocido(
            "%s no trae locus tags PA#### reconocibles. Lo que llego: %s"
            % (fuente, json.dumps(d, ensure_ascii=False, sort_keys=True)))
    raise FormatoDesconocido(
        "%s trae %d locus tags distintos en %s, pero el mapeo de columnas no "
        "esta escrito: hace falta ver el archivo real para saber cual es el "
        "identificador del operon y cual la lista de genes."
        % (fuente, d.get("locus_tags_visibles", 0), d.get("tipo")))


# ------------------------------------------------------------- orquestacion

def extraer(con, fuente, sesion, flag_datos=None, url=None, max_paginas=500,
            log=lambda m: None):
    """Trae una fuente, guarda lo crudo, lo registra y lo parsea si se puede.

    Devuelve un informe: que se bajo, que se pudo leer y que no. **No aborta
    la corrida si el parser no existe todavia**: la descarga es util por si
    sola --es lo que permite escribir el parser-- y perderla porque no se sabe
    leerla seria tirar la unica parte que si se consiguio.
    """
    carpeta = carpeta_cruda(fuente, flag_datos)
    # Identifica esta corrida y agrupa sus archivos. Se marca completa al
    # final y solo si no hubo error: una extraccion a medias no la mira la
    # capa curada.
    extraccion_id = _db.abrir_extraccion(con, fuente)
    informe = {"fuente": fuente, "extraccion_id": extraccion_id,
               "descargas": [],
               "filas": 0, "error": None, "completa": False}

    if fuente == "odb":
        bajadas = traer_odb(sesion, carpeta, max_paginas, log)
    elif fuente == "biocyc":
        entrar_biocyc(sesion)
        bajadas = traer_biocyc(sesion, carpeta, log)
    elif fuente == "pgd":
        bajadas = traer_archivo(sesion, "pgd", VAR_PGD, carpeta, url, log)
    elif fuente == "cdbprom":
        bajadas = traer_archivo(sesion, "cdbprom", VAR_CDBPROM, carpeta, url,
                                log)
    else:
        raise ValueError("fuente desconocida: %r" % fuente)

    ids = []
    for u, ruta, cuerpo in bajadas:
        did = _db.registrar_descarga(con, extraccion_id, u, ruta, cuerpo)
        ids.append(did)
        informe["descargas"].append(
            dict(ruta=ruta, descarga_id=did, **inspeccionar(cuerpo)))

    if not bajadas:
        # Sin archivos no hay foto: se cierra incompleta para que la capa
        # curada no la tome por una extraccion vacia legitima.
        _db.cerrar_extraccion(con, extraccion_id, completa=False)
        return informe

    try:
        filas = _parsear(fuente, bajadas)
    except FormatoDesconocido as e:
        # La descarga si termino: se marca completa aunque no se sepa leer.
        # El parser es un problema nuestro, no una foto a medias de la fuente,
        # y dejarla incompleta escondería una extraccion que si esta entera.
        _db.cerrar_extraccion(con, extraccion_id)
        informe["completa"] = True
        informe["error"] = str(e)
        log("  [%s] descargado, sin parsear: %s" % (fuente, e))
        return informe

    for f in filas:
        f.setdefault("descarga_id", ids[0] if ids else None)
    insertadas, ya_estaban = _db.guardar_bronze(con, filas)
    # Solo aqui, y solo si no hubo error en ningun paso anterior.
    _db.cerrar_extraccion(con, extraccion_id)
    informe["completa"] = True
    informe["filas"] = len(filas)
    informe["insertadas"] = insertadas
    informe["ya_estaban"] = ya_estaban
    log("  [%s] %d filas al bronce (%d nuevas, %d ya estaban)"
        % (fuente, len(filas), insertadas, ya_estaban))
    return informe


def _parsear(fuente, bajadas):
    if fuente == "biocyc":
        por_nombre = dict((os.path.basename(r), c) for _, r, c in bajadas)
        if "tus.xml" not in por_nombre or "genes.xml" not in por_nombre:
            raise FormatoDesconocido(
                "biocyc: faltan tus.xml o genes.xml en la descarga")
        return parsear_biocyc(por_nombre["tus.xml"], por_nombre["genes.xml"])
    if fuente == "odb":
        filas = []
        for _, _, cuerpo in bajadas:
            filas.extend(parsear_odb(cuerpo))
        return filas
    return parsear_tabular(bajadas[0][2], fuente)
