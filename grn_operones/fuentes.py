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

URL_ODB = "https://operondb.jp/known"
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

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tablas += 1
        elif tag == "tr":
            self.filas += 1
        elif tag in ("td", "th"):
            self.celdas += 1


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
        d.update(tipo="html", tablas=p.tablas, filas=p.filas, celdas=p.celdas)
        # Una pagina con tablas pero sin filas de datos es la firma de un
        # render por JavaScript: el esqueleto llega y el contenido no.
        d["parece_render_js"] = p.tablas > 0 and p.filas <= 1
        d["locus_tags_visibles"] = len(set(LOCUS.findall(texto)))
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

def traer_odb(sesion, carpeta, max_paginas=500, log=lambda m: None):
    """Descarga las paginas de operones conocidos. Devuelve [(url, ruta, bytes)].

    Para cuando una pagina repite a la anterior o viene vacia. Repetir es la
    senal de que la paginacion se acabo y el servidor devuelve la ultima
    pagina valida, que es lo que hacen varios sitios en vez de un 404.
    """
    salida = []
    previo = None
    for p in range(1, max_paginas + 1):
        params = {"species": TAXID, "p": p}
        cuerpo = sesion.pedir(URL_ODB, params=params)
        if cuerpo is None:
            log("  [odb] la fuente contesto que no en la pagina %d" % p)
            break
        if not cuerpo.strip() or cuerpo == previo:
            log("  [odb] fin en la pagina %d" % (p - 1))
            break
        ruta = guardar_crudo(carpeta, "pagina_%04d.html" % p, cuerpo)
        salida.append(("%s?species=%s&p=%d" % (URL_ODB, TAXID, p), ruta,
                       cuerpo))
        previo = cuerpo
    return salida


def parsear_odb(cuerpo):
    """Operones de una pagina de ODB. Levanta si el HTML no trae datos.

    No se escribe a ciegas el mapeo de columnas: se comprueba primero que la
    pagina traiga filas y locus tags, y si no, se dice exactamente que llego.
    Ver la tarea 3 del encargo.
    """
    d = inspeccionar(cuerpo)
    if d.get("tipo") != "html" or not d.get("locus_tags_visibles"):
        raise FormatoDesconocido(
            "ODB no devolvio una tabla con locus tags de PAO1. Lo que llego: "
            "%s. Si `parece_render_js` es True, los datos los carga el "
            "navegador y hay que buscar el endpoint JSON en DevTools."
            % json.dumps(d, ensure_ascii=False, sort_keys=True))
    raise FormatoDesconocido(
        "ODB devolvio HTML con %d filas y %d locus tags, pero el mapeo de "
        "columnas no esta escrito: hace falta ver una pagina real para saber "
        "que columna es el operon y cual la lista de genes."
        % (d.get("filas", 0), d.get("locus_tags_visibles", 0)))


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
        cuerpo = sesion.pedir(URL_BIOCYC_QUERY,
                              params={"query": consulta, "detail": "full"},
                              timeout=600)
        if cuerpo is None:
            raise ErrorCredenciales(
                "BioCyc contesto que no a la consulta de %s. Lo habitual es "
                "que la cuenta no tenga acceso a %s, que requiere "
                "suscripcion." % (nombre, ORGID_BIOCYC))
        ruta = guardar_crudo(carpeta, nombre, cuerpo)
        salida.append((URL_BIOCYC_QUERY, ruta, cuerpo))
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
        filas.append({
            "fuente": "biocyc",
            "id_fuente": tu.get("frameid"),
            "genes_raw": "|".join(
                c.get("frameid") or "" for c in tu.findall("component/Gene")),
            "locus_tags": "|".join(locus),
            "cadena": None,
            "tipo_evidencia": ";".join(evid) or None,
            "pmid": None,
            "registro_raw": {"sin_mapear": sin_mapear} if sin_mapear else None,
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
    informe = {"fuente": fuente, "descargas": [], "filas": 0, "error": None}

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
        did = _db.registrar_descarga(con, fuente, u, ruta, cuerpo)
        ids.append(did)
        informe["descargas"].append(
            dict(ruta=ruta, descarga_id=did, **inspeccionar(cuerpo)))

    if not bajadas:
        return informe

    try:
        filas = _parsear(fuente, bajadas)
    except FormatoDesconocido as e:
        informe["error"] = str(e)
        log("  [%s] descargado, sin parsear: %s" % (fuente, e))
        return informe

    for f in filas:
        f.setdefault("descarga_id", ids[0] if ids else None)
    nuevas, actualizadas = _db.guardar_bronze(con, filas)
    informe["filas"] = len(filas)
    informe["nuevas"] = nuevas
    informe["actualizadas"] = actualizadas
    log("  [%s] %d filas al bronce (%d nuevas, %d actualizadas)"
        % (fuente, len(filas), nuevas, actualizadas))
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
