# -*- coding: utf-8 -*-
"""Las cuatro fuentes de operones de PAO1. Descarga cruda y fechada.

Cada fuente hace dos cosas separadas a proposito: **traer** los bytes y
**parsearlos**. Traer se hace una vez y se guarda; parsear se rehace tantas
veces como haga falta sobre los mismos bytes. Si las dos estuvieran juntas,
corregir un parser costaria una descarga contra bases academicas pequenas que
no tienen por que pagar nuestros errores.

LOS PARSERS SE ESCRIBEN CONTRA EL ARCHIVO REAL, NO A CIEGAS
===========================================================
Cada parser se escribió después de ver el archivo real de su fuente: el XML
de BioVelo, el volcado de ODB, el de CDBProm y la tabla de operones de PGD.
Un parser escrito a ciegas produce código que parece funcionar y devuelve
cero filas, que es la peor forma de fallar: silenciosa y con pinta de
correcta. Por eso los de ODB, CDBProm y PGD exigen su contrato (encabezado,
columnas, valores de hebra) y, si no se cumple, lanzan `FormatoDesconocido`
en vez de leer columnas corridas. El de BioCyc todavía no lo hace: un XML sin
TUs da cero filas y un cuerpo que no es XML lanza `ET.ParseError`.
`inspeccionar()` dice **qué llegó de verdad** --tipo,
tamaño, si trae tablas, si trae JSON--, que es lo que hace falta cuando una
fuente cambia de formato o devuelve una página en lugar de datos.

Solo biblioteca estandar.
"""

import csv
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

# La tabla de operones de Pseudomonas Genome DB (PGD) para PAO1, tal como la
# exportó su curador. **No sale de pseudomonas.com**, por dos razones medidas
# el 27 de septiembre de 2026 (`docs/hallazgos.md`):
#
# - Todo ese host está detrás de un desafío administrado de Cloudflare (403
#   con `Cf-Mitigated: challenge`), `/downloads/` y `robots.txt` incluidos, y
#   su `robots.txt` prohíbe la recolección automatizada sin permiso escrito.
# - El sitio no ofrece un archivo bulk de operones. Solo existe la vista HTML
#   de cada gen, y rasparla exigiría pasar el desafío. Eso es evasión y no se
#   hace.
#
# Esta es la tabla que alimenta esa vista: Geoff Winsor, curador de PGD, se la
# entregó al laboratorio Greene (Lee et al. 2023, mSystems,
# doi:10.1128/msystems.00342-22), que la publicó con licencia BSD-3. Contiene
# predicciones de DOOR y operones de PseudoCAP, en una foto del 2021-07-19.
# La URL va fijada a un commit, así que sus bytes no pueden cambiar, y por eso
# `extraer` no la vuelve a pedir si ya la tiene. Una versión más nueva se pide
# a pseudocap-mail@sfu.ca y entra con `--url`, `PGD_OPERONES_URL` o
# `--archivo`.
URL_PGD = ("https://raw.githubusercontent.com/greenelab/"
           "core-accessory-interactome/"
           "25539b82d51aa088c9e2f241a71ea1cc996fddae/"
           "data/metadata/PAO1-operons-2021-07-19.csv")

# Las variables de entorno que apuntan a otro archivo. La de CDBProm es la
# única vía de esa fuente además de `--archivo`; la de PGD gana sobre
# `URL_PGD`.
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
# 18-sep-2026: 9 480 líneas (encabezado y 9 479 filas de datos), 33 de ellas
# del taxid de PAO1.
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
        # Los PMIDs salen de TODO el subárbol de la TU (`iter`), no de los
        # `<dblink>`: mirar solo los dblink daba cero PMIDs para toda la
        # fuente. Ojo con el alcance, medido el 27-sep-2026: de las 64 TUs con
        # PMID, solo 41 lo traen en su `citation`; 16 lo traen únicamente por
        # su `component/Promoter`, que es evidencia del promotor y no de la
        # unidad. Lo mismo pasa con `Evidence-Code`. Restringirlo cambiaría
        # el conjunto de «conocidos» y es una decisión pendiente, no un arreglo
        # de paso (`docs/catalogo-operones.md`).
        pmids = sorted(set(p.text.strip() for p in tu.iter("pubmed-id")
                           if (p.text or "").strip()))
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
            "pmid": ";".join(pmids) or None,
            "registro_raw": crudo,
        })
    return filas




# ----------------------------------------------------------------- CDBProm

# Las diez columnas del volcado, en su orden. Los nombres son nuestros: el
# encabezado del archivo es prosa descriptiva, no una fila de cabecera.
COLUMNAS_CDBPROM = ["ncbi_id", "organismo", "locus_tag", "inicio", "fin",
                    "cadena", "score", "etiqueta", "secuencia", "anotacion"]

CABECERA_CDBPROM = 10

# El volcado escribe D y R donde el encabezado dice F y R. Se acepta `D` como
# directa y se RECHAZA cualquier otro valor en vez de adivinar: una cadena mal
# leida invierte el sentido del promotor, y un promotor aguas arriba del gen
# equivocado es peor que no tener promotor.
CADENA_CDBPROM = {"D": "+", "R": "-"}

# La fuente ya filtro por score; el minimo declarado es 0.5. No se vuelve a
# filtrar aqui --el dato llega filtrado y volver a cortar seria cortar dos
# veces-- pero se comprueba, porque una fila por debajo significa que el
# volcado no es el que se describio.
SCORE_MINIMO_CDBPROM = 0.5


def parsear_cdbprom(cuerpo):
    """Los promotores de PAO1 del volcado de CDBProm.

    **Esto no son operones, son promotores**, y por eso cada fila trae UN
    locus tag. La capa curada no crea un operon por cada uno: los usa para
    marcar `promotor_cdbprom` en el operon cuyo primer gen tiene promotor, que
    es la regla 5 del encargo. Meterlos como operones habria fabricado 1 972
    unidades monocistronicas que nadie ha observado transcribirse.

    El formato, comprobado contra el archivo bajado del sitio del IIMAS
    (descarga por organismo, 18-sep-2026):

    - Diez lineas de encabezado descriptivo antes de los datos. No es una fila
      de cabecera con nombres de columna: es prosa, y por eso se saltan por
      conteo y no buscando un patron.
    - Diez columnas separadas por tabulador.
    - La cadena viene como `D`/`R` aunque el encabezado dice `F`/`R`.
    - Las coordenadas abarcan 80 pb y la secuencia mide 60 nt. **Las dos se
      guardan tal cual, sin interpretar posiciones exactas**: la discrepancia
      es del volcado y resolverla a ojo seria inventar una convencion que la
      fuente no declara.
    """
    texto = cuerpo.decode("utf-8", "replace")
    lineas = texto.splitlines()
    if len(lineas) <= CABECERA_CDBPROM:
        raise FormatoDesconocido(
            "cdbprom: el volcado tiene %d lineas y el encabezado solo ocupa %d"
            % (len(lineas), CABECERA_CDBPROM))

    filas, por_locus, avisos = [], {}, []
    for n, linea in enumerate(lineas[CABECERA_CDBPROM:],
                              start=CABECERA_CDBPROM + 1):
        if not linea.strip():
            continue
        partes = linea.rstrip("\n").split("\t")
        if len(partes) < len(COLUMNAS_CDBPROM):
            raise FormatoDesconocido(
                "cdbprom: la linea %d tiene %d columnas y el contrato pide %d. "
                "El volcado cambio de formato y el parseo se detiene en vez de "
                "leer columnas corridas." % (n, len(partes),
                                             len(COLUMNAS_CDBPROM)))
        d = dict(zip(COLUMNAS_CDBPROM, partes))

        bruta = d["cadena"].strip().upper()
        if bruta not in CADENA_CDBPROM:
            raise FormatoDesconocido(
                "cdbprom: cadena %r en la linea %d. Solo se aceptan D y R; "
                "adivinar el sentido de un promotor lo pondria aguas arriba "
                "del gen equivocado." % (d["cadena"], n))

        locus = d["locus_tag"].strip()
        if not LOCUS.match(locus):
            avisos.append((n, locus))
            continue
        if locus in por_locus:
            # El perfil dice un promotor maximo por locus tag. Si llegan dos,
            # se conserva el de mayor score y se anota: elegir en silencio
            # dejaria al operon marcado por un promotor que no es el mejor.
            if _score(d) <= _score(por_locus[locus]):
                continue
        por_locus[locus] = d

    for locus, d in por_locus.items():
        filas.append({
            "fuente": "cdbprom",
            "id_fuente": locus,
            "genes_raw": None,
            "locus_tags": locus,
            "cadena": CADENA_CDBPROM[d["cadena"].strip().upper()],
            "tipo_evidencia": "promotor_predicho",
            "pmid": None,
            # Coordenadas y secuencia tal cual, sin interpretar: el rango
            # abarca 80 pb y la secuencia mide 60 nt, y esa diferencia es del
            # volcado. Se guarda lo que dijo y se deja constancia del desajuste.
            "registro_raw": {
                "inicio": d["inicio"].strip(),
                "fin": d["fin"].strip(),
                "score": d["score"].strip(),
                "etiqueta": d["etiqueta"].strip(),
                "secuencia": d["secuencia"].strip(),
                "anotacion": d["anotacion"].strip(),
                "cadena_original": d["cadena"].strip(),
                "largo_rango": _largo(d),
                "largo_secuencia": len(d["secuencia"].strip()),
            },
        })

    if not filas:
        raise FormatoDesconocido(
            "cdbprom: ninguna de las %d lineas de datos trae un locus tag de "
            "PAO1" % (len(lineas) - CABECERA_CDBPROM))
    if avisos:
        # No se levanta: el resto del volcado sirve. Queda en el registro para
        # que el informe lo diga.
        filas[0]["registro_raw"]["locus_no_pao1"] = [l for _n, l in avisos[:20]]
    return filas


def _score(d):
    try:
        return float(d["score"])
    except (TypeError, ValueError):
        return -1.0


def _largo(d):
    try:
        return abs(int(d["fin"]) - int(d["inicio"])) + 1
    except (TypeError, ValueError):
        return None

# --------------------------------------------------------------------- PGD

# Las nueve columnas de la tabla de PGD, comprobadas contra el archivo real el
# 27-sep-2026: 3 816 filas, 1 290 operones.
COLUMNAS_PGD = ["operon-id", "operon_name", "locus_tag", "start", "end",
                "strand", "gene_name", "source_database", "pmid"]

# Solo 1 y -1. Otro valor se RECHAZA en vez de adivinarse, por la misma razón
# que en CDBProm: una hebra mal leída invierte el orden de transcripción.
HEBRA_PGD = {"1": "+", "-1": "-"}

# Los dos orígenes que mezcla PGD. DOOR es predicción, y su única cita es la
# del método. PseudoCAP es literatura curada: cada operón cita los artículos
# que lo describen (tres de los 125 citan dos).
BASES_PGD = ("DOOR", "PseudoCAP")


def parsear_pgd(cuerpo):
    """Los operones de PAO1 de la tabla de PGD: una fila por `operon-id`.

    El archivo trae una fila por GEN y no por operón. De ahí salen tres cosas
    que no son obvias, las tres medidas sobre el archivo real:

    - Las filas de un operón **no siempre van juntas** (103 de 1 290), así que
      se agrupa por `operon-id` y no por filas contiguas.
    - Tres operones de PseudoCAP repiten cada gen una vez por artículo. Sin
      quitar la repetición, `oprE` saldría `PA0291|PA0291`.
    - Las filas van ascendentes por coordenada en las dos hebras, y en la
      hebra menos ese es el orden inverso al de transcripción: `PA0006-lptA`
      son PA0006 y luego PA0005. `locus_tags` se entrega en orden de
      transcripción, ordenando por coordenada e invirtiendo en `-`.

    DOOR cita en todas sus filas el artículo del MÉTODO (Mao et al. 2009,
    PMID 18988623), no una demostración del operón. Por eso va a
    `registro_raw["referencia_metodo"]` y no a `pmid`, donde la capa curada lo
    leería como literatura.

    Un locus tag que no pasa `LOCUS.fullmatch` detiene el parseo en vez de
    recortarse: `findall` convertiría `PA4726.11` en `PA4726`, que es otro gen
    (`cbrB`). Todos los tags del archivo real pasan.
    """
    # `utf-8-sig`: un archivo guardado desde Excel trae BOM y, sin quitarlo,
    # el encabezado no coincidiría con el contrato por un carácter invisible.
    texto = cuerpo.decode("utf-8-sig", "replace")
    try:
        renglones = [r for r in csv.reader(io.StringIO(texto, newline=""))
                     if r]
    except csv.Error as e:
        # Un cuerpo que no es CSV (un campo gigante, un salto de línea suelto
        # dentro de comillas) tiene que salir como FormatoDesconocido: es el
        # contrato del que dependen `extraer` y `reparsear` para conservar la
        # descarga y decir que no se pudo leer.
        raise FormatoDesconocido(
            "pgd: el cuerpo no se deja leer como CSV (%s). Lo que llegó: %s"
            % (e, json.dumps(inspeccionar(cuerpo), ensure_ascii=False,
                             sort_keys=True)))
    if not renglones or renglones[0] != COLUMNAS_PGD:
        raise FormatoDesconocido(
            "pgd: el encabezado no es el del contrato %r. El formato cambió o "
            "no llegó la tabla. Lo que llegó: %s"
            % (COLUMNAS_PGD, json.dumps(inspeccionar(cuerpo),
                                        ensure_ascii=False, sort_keys=True)))

    operones = {}
    for n, partes in enumerate(renglones[1:], start=2):
        if len(partes) != len(COLUMNAS_PGD):
            raise FormatoDesconocido(
                "pgd: el renglón %d tiene %d columnas y el contrato pide %d"
                % (n, len(partes), len(COLUMNAS_PGD)))
        d = dict(zip(COLUMNAS_PGD, (p.strip() for p in partes)))
        if not LOCUS.fullmatch(d["locus_tag"]):
            raise FormatoDesconocido(
                "pgd: locus tag %r en el renglón %d. Se rechaza en vez de "
                "recortarse a otro gen." % (d["locus_tag"], n))
        if d["strand"] not in HEBRA_PGD:
            raise FormatoDesconocido(
                "pgd: hebra %r en el renglón %d. Solo se aceptan 1 y -1."
                % (d["strand"], n))
        if d["source_database"] not in BASES_PGD:
            raise FormatoDesconocido(
                "pgd: origen %r en el renglón %d. Solo se conocen %s, y un "
                "origen nuevo necesita decidir si es predicción o literatura."
                % (d["source_database"], n, ", ".join(BASES_PGD)))
        try:
            d["start"], d["end"] = int(d["start"]), int(d["end"])
        except ValueError:
            raise FormatoDesconocido(
                "pgd: coordenadas %r..%r en el renglón %d no son enteros"
                % (d["start"], d["end"], n))
        operones.setdefault(d["operon-id"], []).append(d)

    filas = []
    for oid, renglones_op in operones.items():
        bases = set(d["source_database"] for d in renglones_op)
        if len(bases) > 1:
            raise FormatoDesconocido(
                "pgd: el operón %s mezcla %s. Cada operón viene de un solo "
                "origen y el nivel de evidencia depende de cuál."
                % (oid, ", ".join(sorted(bases))))
        base = bases.pop()

        genes, vistos = [], set()
        for d in renglones_op:
            if d["locus_tag"] not in vistos:
                vistos.add(d["locus_tag"])
                genes.append(d)
        hebras = set(HEBRA_PGD[d["strand"]] for d in genes)
        cadena = hebras.pop() if len(hebras) == 1 else None
        por_coordenada = [d["locus_tag"]
                          for d in sorted(genes, key=lambda d: d["start"])]
        if cadena == "-":
            por_coordenada.reverse()
        pmids = sorted(set(d["pmid"] for d in renglones_op if d["pmid"]),
                       key=lambda p: (len(p), p))

        crudo = {
            "name": renglones_op[0]["operon_name"],
            "source_database": base,
            # En el orden del archivo: es lo que dijo la fuente, y la vista
            # de la página se reconstruye de aquí.
            "genes": [{"locus_tag": d["locus_tag"],
                       "gene_name": d["gene_name"],
                       "start": d["start"], "end": d["end"],
                       "hebra": HEBRA_PGD[d["strand"]]} for d in genes],
        }
        if base == "DOOR":
            crudo["referencia_metodo"] = ";".join(pmids) or None
        filas.append({
            "fuente": "pgd",
            "id_fuente": oid,
            # Vacío, como en ODB y BioCyc: el locus tag ya viene resuelto y
            # los nombres faltan en 1 983 de 3 816 filas, así que no hay nada
            # que mapear. Los nombres van en `registro_raw["genes"]`.
            "genes_raw": None,
            "locus_tags": "|".join(por_coordenada),
            "cadena": cadena,
            "tipo_evidencia": base,
            "pmid": (";".join(pmids) or None) if base == "PseudoCAP" else None,
            "registro_raw": crudo,
        })
    if not filas:
        raise FormatoDesconocido("pgd: la tabla trae el encabezado y ningún "
                                 "operón")
    return filas


# ------------------------------------------------------- archivo por URL

def traer_archivo(sesion, fuente, var_entorno, carpeta, url=None,
                  log=lambda m: None):
    """Baja un archivo cuya URL llega por flag, por entorno o fijada.

    CDBProm no tiene URL pública: su archivo se baja a mano del sitio del
    IIMAS (descarga por organismo) y entra con `--archivo`, así que sin
    `--url` ni `CDBPROM_URL` la fuente se omite con un aviso en vez de fallar
    la corrida entera. PGD llega aquí con `URL_PGD` como último recurso.
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


def foto_sana(con, fuente):
    """De dónde salió la foto vigente de `fuente`, si sirve; si no, `None`.

    Sirve cuando la última extracción completa dejó filas en el bronce y sus
    archivos siguen en disco con la huella registrada. Que la extracción
    figure como completa no basta, por dos casos que ya se reprodujeron:

    - Un parseo fallido también cierra la extracción como completa, con 0
      filas. Si eso contara como «ya está», PGD se quedaría vacía para
      siempre.
    - Si falta el crudo, `reparsear` pide volver a extraer. Si `extraer`
      contestara «ya está, usa reparsear», cada comando mandaría al otro.
    """
    eid = _db.ultima_extraccion_completa(con).get(fuente)
    if not eid or not _db.filas_bronze_de_extraccion(con, eid):
        return None
    descargas = _db.descargas_de_extraccion(con, eid)
    for d in descargas:
        if not os.path.exists(d["ruta"]):
            return None
        with io.open(d["ruta"], "rb") as f:
            if _db.huella(f.read()) != d["sha256"]:
                return None
    return descargas[0]["url"] if descargas else None


# ------------------------------------------------------------- orquestacion

def extraer(con, fuente, sesion, flag_datos=None, url=None, max_paginas=500,
            log=lambda m: None, archivo=None):
    """Trae una fuente, guarda lo crudo, lo registra y lo parsea si se puede.

    Devuelve un informe: que se bajo, que se pudo leer y que no. **No aborta
    la corrida si el parser no existe todavia**: la descarga es util por si
    sola --es lo que permite escribir el parser-- y perderla porque no se sabe
    leerla seria tirar la unica parte que si se consiguio.
    """
    if fuente == "pgd" and not archivo:
        explicita = url or os.environ.get(VAR_PGD)
        # `URL_PGD` solo se usa para la primera carga, o para rehacer una foto
        # que no sirve. Con una foto sana ya no aporta nada: si la foto salió
        # de ella, sus bytes, fijados a un commit, no pueden haber cambiado;
        # si salió de una tabla más nueva (`--archivo`, `--url`), bajarla
        # devolvería la de 2021 y daría por retirados los operones nuevos.
        # Se comprueba antes de abrir la extracción, porque una abierta y sin
        # cerrar contaría como corrida fallida en `edad_de_la_foto`.
        origen = None if explicita else foto_sana(con, "pgd")
        if origen:
            log("  [pgd] ya está: la foto vigente salió de %s y sigue entera "
                "en disco. Para reemplazarla, pasa --url o --archivo (--url "
                "con la tabla fijada vuelve a la de 2021). Para volver a "
                "leerla sin red: `reparsear --fuente pgd`." % origen)
            return {"fuente": fuente, "extraccion_id": None,
                    "descargas": [], "filas": 0, "error": None,
                    "completa": True, "ya_estaba": True}
        url = explicita or URL_PGD

    carpeta = carpeta_cruda(fuente, flag_datos)
    # Identifica esta corrida y agrupa sus archivos. Se marca completa al
    # final y solo si no hubo error: una extraccion a medias no la mira la
    # capa curada.
    extraccion_id = _db.abrir_extraccion(con, fuente)
    informe = {"fuente": fuente, "extraccion_id": extraccion_id,
               "descargas": [],
               "filas": 0, "error": None, "completa": False}

    if archivo:
        # Gana sobre la via de red de la fuente, sea cual sea: si alguien
        # pasa un archivo es porque lo tiene, y pedirselo otra vez a la
        # fuente seria trafico para nada.
        bajadas = traer_archivo_local(archivo, fuente, carpeta, log)
    elif fuente == "odb":
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
    if fuente == "cdbprom":
        return parsear_cdbprom(bajadas[0][2])
    if fuente == "pgd":
        return parsear_pgd(bajadas[0][2])
    raise FormatoDesconocido("%s: no hay parser para esta fuente" % fuente)


def reparsear(con, fuente, log=lambda m: None):
    """Vuelve a parsear los archivos de la ultima extraccion completa.

    Es la razon de ser de la capa cruda: corregir un parser no debe costar una
    peticion a la fuente. Los bytes estan en disco con su huella registrada, y
    se comprueba antes de usarlos --si el archivo cambio, se para-- porque
    re-parsear bytes distintos de los que se descargaron produciria un bronce
    cuya procedencia dice otra cosa de la que tiene.
    """
    eid = _db.ultima_extraccion_completa(con).get(fuente)
    if not eid:
        raise FormatoDesconocido(
            "%s no tiene ninguna extraccion completa que re-parsear" % fuente)

    bajadas = []
    for d in _db.descargas_de_extraccion(con, eid):
        if not os.path.exists(d["ruta"]):
            raise FormatoDesconocido(
                "falta el archivo %s de la extraccion %d. Sin el crudo no se "
                "puede re-parsear; hay que volver a extraer." % (d["ruta"], eid))
        with io.open(d["ruta"], "rb") as f:
            cuerpo = f.read()
        sha = _db.huella(cuerpo)
        if sha != d["sha256"]:
            raise FormatoDesconocido(
                "%s no coincide con su huella registrada (%s contra %s). Esos "
                "no son los bytes que se descargaron, asi que el bronce que "
                "saldria de ellos no tendria la procedencia que dice tener."
                % (d["ruta"], sha[:16], d["sha256"][:16]))
        bajadas.append((d["url"], d["ruta"], cuerpo))
        log("  [%s] %s  (%d bytes, huella ok)"
            % (fuente, os.path.basename(d["ruta"]), len(cuerpo)))

    filas = _parsear(fuente, bajadas)
    for f in filas:
        f.setdefault("descarga_id", _db.descargas_de_extraccion(con, eid)[0]["id"])
    _db.borrar_bronze_de_extraccion(con, eid)
    insertadas, _ya = _db.guardar_bronze(con, filas)
    log("  [%s] %d filas re-parseadas en la extraccion %d"
        % (fuente, insertadas, eid))
    return {"fuente": fuente, "extraccion_id": eid, "filas": insertadas,
            "archivos": len(bajadas)}


# ------------------------------------------------------- archivo local

def traer_archivo_local(ruta_archivo, fuente, carpeta, log=lambda m: None):
    """Ingesta un archivo que ya esta en disco. Devuelve [(url, ruta, bytes)].

    La "url" registrada es `archivo-local:<nombre>`, que no es una URL y lo
    dice: la procedencia de este archivo no es una peticion que se pueda
    repetir, es alguien que lo entrego. Ponerle una URL inventada habria hecho
    creer que se puede volver a bajar.

    El archivo se COPIA a la carpeta de crudos en vez de referenciarse donde
    este. Un volcado que vive en la carpeta de descargas de alguien se mueve o
    se borra, y entonces `reparsear` deja de funcionar y la huella registrada
    apunta a nada.

    Sirve para el archivo de CDBProm, que se baja a mano del sitio del IIMAS
    y no tiene URL que se pueda pedir, y
    para una tabla de PGD que llegue por otra vía, por ejemplo una versión
    más nueva que mande su curador.
    """
    if not os.path.exists(ruta_archivo):
        raise FormatoDesconocido("no existe el archivo %s" % ruta_archivo)
    with io.open(ruta_archivo, "rb") as f:
        cuerpo = f.read()
    nombre = os.path.basename(ruta_archivo)
    destino = guardar_crudo(carpeta, nombre, cuerpo)
    log("  [%s] %s  (%d bytes, de %s)"
        % (fuente, destino, len(cuerpo), ruta_archivo))
    return [("archivo-local:%s" % nombre, destino, cuerpo)]
