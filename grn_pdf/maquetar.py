# -*- coding: utf-8 -*-
"""Páginas de líneas -> texto por secciones, en el formato de `jats_a_texto`.

Biblioteca estándar y Python 3.8: recibe lo que entrega `extraer.py` (o una
página sintética en las pruebas) y no sabe nada de PyMuPDF.

El formato de salida es el del `.txt` que `grn_etl.pubmed.jats_a_texto` deja
junto a cada XML, porque el bronce lee los dos con la misma función
(`grn_bronce.texto.bloques_con_offset`):

    # Título

    ## ABSTRACT

    párrafo

    ## RESULTS

    ### SUBTÍTULO

    párrafo

    ## PIES DE FIGURA Y TABLA

    pie

Partes unidas con una línea en blanco, cada encabezado precedido de otra, un
párrafo por línea. Los `##` llevan solo etiquetas que `secciones.tsv` ya
clasifica (`ETIQUETAS`): un encabezado que no se reconoce no abre sección,
sale como `###`, y el bronce lo borra del cuerpo como borra los del XML.

Lo que el JATS no trae tampoco sale aquí: autores, afiliaciones, fechas, cabezas
y pies de página, números de línea, el texto de las tablas y el de dentro de
las figuras. Las tablas no se pueden leer como prosa, y sus filas son listas de
genes: dejarlas pasaría por oración candidata lo que es una celda.

Las decisiones son heurísticas medidas contra los artículos que tienen XML y
PDF (`validar.py`); cada una dice por qué existe.
"""

import collections
import re
import unicodedata

# Sube cada vez que el mismo PDF pasa a dar otro texto. El registro de la
# conversión la guarda, y `convertir` rehace los `.txt` de otra versión.
VERSION = "2"

ETIQUETA_PIES = "PIES DE FIGURA Y TABLA"

# ----------------------------------------------------------- normalización

# Las ligaduras que MuPDF deja pasar cuando la fuente no las declara, y los
# blancos y guiones de compatibilidad. El guion duro U+2010 se vuelve `-`
# porque el diccionario reconoce `mexEF-oprN` con el guion ASCII.
_SUSTITUCIONES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u2002": " ",
    "\u2003": " ", "\u2004": " ", "\u2005": " ", "\u2006": " ",
    "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ", "\u205f": " ", "\u3000": " ",
    "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "", "\ufeff": "",
}
_TABLA_SUST = dict((ord(k), v) for k, v in _SUSTITUCIONES.items())
# Los caracteres de control son glifos sin Unicode (el U+0002 que Oxford
# deja en lugar de «©»): se vuelven blanco en vez de colarse al texto.
_TABLA_SUST.update((c, " ") for c in range(32) if c not in (9, 10, 13))

# El guion suave U+00AD solo aparece donde el tipógrafo partió la palabra: se
# marca para que el unidor de líneas lo trate como corte, y en medio de una
# línea se quita.
_GUION_SUAVE = "\u00ad"

# Fuentes de símbolos cuyo texto MuPDF entrega como ASCII: en las revistas de
# la ASM, `DlasR` es ΔlasR y `s54` es σ54. Sin el mapeo el diccionario no ve
# `lasR` dentro de `DlasR`.
_FUENTE_GRIEGA = re.compile(r"symbol|greek", re.IGNORECASE)
_GRIEGO = dict(zip(
    "abgdezhqiklmnxoprstufcywDGQLXPSUFYWjJ",
    "αβγδεζηθικλμνξοπρστυφχψωΔΓΘΛΞΠΣϒΦΨΩϕϑ"))


def normalizar(t):
    """Ligaduras, blancos y guiones de compatibilidad; NFC al final."""
    t = t.translate(_TABLA_SUST)
    return unicodedata.normalize("NFC", t)


# La «Universal-GreekwithMathPi» de la ASM también lleva los signos en
# cifras: `59 end` es 5′ end y `5 3 10212 M` es 5 × 10−12 M.
_FUENTE_ASM = re.compile(r"greekwithmathp", re.IGNORECASE)
_SIGNOS_ASM = {"9": "\u2032", "3": "\u00d7", "6": "\u00b1", "2": "\u2212",
               "1": "+"}


def _a_griego(t, fuente=""):
    tabla = dict(_GRIEGO)
    if _FUENTE_ASM.search(fuente):
        tabla.update(_SIGNOS_ASM)
    return "".join(tabla.get(c, c) if c.isascii() else c for c in t)


# Un superíndice que es solo cita o marca de nota: `lasR12,13`, `PAO1*`. Se
# quita, porque pegado al nombre el diccionario no reconoce el gen. Lo que
# lleva letras se queda (`Gmr`, `Mg2+`).
_CITA_SUP = re.compile(r"^[\s\d,;.\-\u2013\u2014*\u2020\u2021\u00a7\u00b6#]+$")


# Lo que puede ir antes de una cita volada: una letra latina, un cierre de
# puntuación o nada. Tras una griega o un glifo sin Unicode no es cita sino
# índice (`σ22`, `σ54`), y tras una cifra es exponente (`10^5`).
_ANTES_DE_CITA = re.compile(r"^[A-Za-z.,;:)\]\s]$")


def texto_de_linea(spans):
    """(texto, tamaño, fracción en negrita, fracción en cursiva) de una
    línea, sin las citas voladas."""
    if not spans:
        return "", 0.0, 0.0, 0.0
    tam_max = max(s["tam"] for s in spans)
    base = max(s["base"] for s in spans if s["tam"] >= tam_max - 0.2)
    partes, pesos, negritas, cursivas, n = [], collections.Counter(), 0, 0, 0
    for s in spans:
        t = s["texto"]
        if _FUENTE_GRIEGA.search(s.get("fuente") or ""):
            t = _a_griego(t, s.get("fuente") or "")
        volado = (s["tam"] <= 0.85 * tam_max
                  and s["base"] < base - 0.15 * s["tam"])
        previo = "".join(partes).rstrip()[-1:]
        if volado and _CITA_SUP.match(t) and _ANTES_DE_CITA.match(previo or " "):
            # Un espacio y no nada: «MexR12and» sale de quitar la cita entre
            # dos palabras que no traían blanco.
            partes.append(" ")
            continue
        partes.append(t)
        visibles = len(t.strip())
        if not volado:
            pesos[round(s["tam"] * 2) / 2.0] += visibles
        if s.get("negrita"):
            negritas += visibles
        if s.get("cursiva"):
            cursivas += visibles
        n += visibles
    texto = normalizar("".join(partes))
    tam = pesos.most_common(1)[0][0] if pesos else tam_max
    if not n:
        return texto, tam, 0.0, 0.0
    return texto, tam, negritas / float(n), cursivas / float(n)


# ------------------------------------------------------- encabezados conocidos

def _clave(texto):
    """Forma de comparación de un encabezado: sin numeración, sin
    puntuación, en minúsculas. `2.1. Results:` -> `results`."""
    t = normalizar(texto).strip().lower()
    t = t.replace("&", " and ").replace("\u2019", "'")
    t = re.sub(r"^\s*((\d+(\.\d+)*)|[ivxlc]+)\s*[.):]?\s+", "", t)
    t = re.sub(r"[^a-z' ]+", " ", t)
    t = " ".join(t.split())
    # Encabezados con letras espaciadas: «R E S U L T S».
    if re.match(r"^(?:[a-z] ){2,}[a-z]$", t):
        t = t.replace(" ", "")
    return t


# clave -> etiqueta que se escribe. Toda etiqueta está en secciones.tsv (lo
# vigila una prueba), así que su clase sale de ahí y no de este diccionario.
_CONOCIDAS_LISTA = [
    ("ABSTRACT", ["abstract", "summary", "author summary", "importance",
                  "significance", "graphical abstract", "synopsis"]),
    ("INTRODUCTION", ["introduction", "intro"]),
    ("BACKGROUND", ["background"]),
    ("RESULTS", ["results", "result"]),
    ("RESULTS AND DISCUSSION", ["results and discussion",
                                "results and discussions",
                                "result and discussion"]),
    ("DISCUSSION", ["discussion", "general discussion"]),
    ("DISCUSSION AND CONCLUSIONS", ["discussion and conclusions",
                                    "discussion and conclusion"]),
    ("CONCLUSIONS", ["conclusion", "conclusions", "conclusion and outlook",
                     "conclusions and outlook", "outlook", "perspectives",
                     "conclusion and perspectives", "future perspectives",
                     "conclusions and future perspectives",
                     "conclusions and perspectives", "concluding remarks",
                     "summary and conclusions"]),
    ("MATERIALS AND METHODS", ["materials and methods", "material and methods",
                               "materials and method", "methods and materials",
                               "materials methods"]),
    ("METHODS", ["methods", "method", "methodology", "online methods",
                 "star methods", "starmethods", "patients and methods",
                 "experimental"]),
    ("EXPERIMENTAL PROCEDURES", ["experimental procedures",
                                 "experimental procedure",
                                 "experimental section"]),
    ("ACKNOWLEDGMENTS", ["acknowledgments", "acknowledgements",
                         "acknowledgment", "acknowledgement"]),
    ("REFERENCES", ["references", "reference", "literature cited",
                    "bibliography", "references and notes",
                    "references cited", "cited literature"]),
    ("SUPPLEMENTARY MATERIAL", ["supplementary material",
                                "supplementary materials",
                                "supplementary information",
                                "supplementary data", "supplemental material",
                                "supplemental information",
                                "supplemental data", "supporting information",
                                "electronic supplementary material",
                                "additional files", "additional file",
                                "supplementary files", "supplementary file"]),
    ("FUNDING", ["funding", "funding information", "financial support",
                 "funding sources", "sources of funding"]),
    ("AUTHOR CONTRIBUTIONS", ["author contributions", "authors' contributions",
                              "author's contributions", "contributions",
                              "credit authorship contribution statement"]),
    ("CONFLICT OF INTEREST", ["conflict of interest", "conflicts of interest",
                              "conflict of interests", "competing interests",
                              "competing interest",
                              "declaration of competing interest",
                              "declaration of interests", "disclosures",
                              "conflict of interest statement"]),
    ("DATA AVAILABILITY", ["data availability", "data availability statement",
                           "availability of data and materials",
                           "data and code availability",
                           "data and software availability"]),
    ("ABBREVIATIONS", ["abbreviations", "list of abbreviations"]),
    ("ETHICS STATEMENT", ["ethics statement", "ethics approval",
                          "ethics approval and consent to participate"]),
    ("DECLARATIONS", ["declarations", "consent for publication"]),
    ("NOTES", ["notes", "footnotes", "author information", "author details",
               "additional information", "publisher's note", "orcid",
               "open access"]),
]

CONOCIDAS = {}
for _etiqueta, _claves in _CONOCIDAS_LISTA:
    for _c in _claves:
        CONOCIDAS[_c] = _etiqueta
        CONOCIDAS[_c.replace(" ", "")] = _etiqueta

ETIQUETAS = sorted(set(e for e, _ in _CONOCIDAS_LISTA) | {ETIQUETA_PIES})

# Encabezados que no abren sección sino el modo de pies: lo que sigue son
# leyendas de figura (manuscritos de autor, que las ponen tras las
# referencias).
_CLAVES_PIES = frozenset(["figure legends", "figure legend", "figure captions",
                          "legends to figures", "legends", "figures",
                          "figure titles and legends", "tables",
                          "figures and tables", "legends for figures"])

# Etiquetas que pueden ir «en línea» al principio de un párrafo, en negrita:
# `Abstract The ...`, `Acknowledgements We thank ...`. Las del resumen
# estructurado (`Background:`, `Results:`) no, porque partirían el resumen en
# secciones que el JATS no parte.
_EN_LINEA = frozenset(["ABSTRACT", "ACKNOWLEDGMENTS", "FUNDING",
                       "AUTHOR CONTRIBUTIONS", "CONFLICT OF INTEREST",
                       "DATA AVAILABILITY", "ABBREVIATIONS", "REFERENCES",
                       "SUPPLEMENTARY MATERIAL"])

# Las secciones principales del cuerpo. Deciden dos cosas de la portada: si
# lo que sigue a un resumen rotulado es ya el cuerpo (y entonces el resumen
# puede traer pegada la introducción sin etiqueta), y qué puede abrir la
# primera sección del documento.
_PRINCIPALES = frozenset(["INTRODUCTION", "BACKGROUND", "RESULTS",
                          "RESULTS AND DISCUSSION", "DISCUSSION",
                          "MATERIALS AND METHODS", "METHODS",
                          "EXPERIMENTAL PROCEDURES"])


# Lo que puede abrir la primera sección del documento. Lo demás, en la
# portada, es metadato.
_ABREN = _PRINCIPALES | frozenset(["ABSTRACT", "CONCLUSIONS",
                                   "DISCUSSION AND CONCLUSIONS"])


def etiqueta_conocida(texto):
    """La etiqueta de `##` de un encabezado conocido, o None."""
    return CONOCIDAS.get(_clave(texto))


# ---------------------------------------------------------- pies y metadatos

# El principio de un pie: `FIG. 1.`, `Figure 2 |`, `Table 1 Strains`,
# `Fig. S3:`. Lo que separa un pie de una oración que cita la figura
# («Figure 1 shows») es lo que va después del número: puntuación, una
# mayúscula o un paréntesis.
_PIE = re.compile(
    r"^\s*(?:supplementary\s+|supplemental\s+|extended\s+data\s+)?"
    r"(fig(?:ure)?s?\.?|tab(?:le)?\.?|scheme)\s*"
    r"((?:s|ev|e)?\d+|[ivx]+)[a-z]?(?:\s*[.:|\u2014\u2013]|\s+[A-Z(\[]|\s*$)",
    re.IGNORECASE)

# Bloques de metadatos que no son prosa del artículo: la caja de la primera
# página de PLoS, las notas de autor correspondiente, las fechas. Se tiran
# enteros. Van con dos puntos o con una fecha para no llevarse una oración
# que empiece por «Received signals...».
_METADATO = re.compile(
    r"^\s*[*\u2020\u2021\u00a7\u00b6#\d]*\s*(?:"
    r"(?:citation|editor|editors|academic editor|edited by|reviewed by|"
    r"specialty section|copyright|competing interests?|"
    r"conflicts? of interests?|e-?mail|correspondence|"
    r"corresponding authors?|present address|current address|"
    r"keywords?|key words|abbreviations|article history|"
    r"handling editor|data availability|funding|open access|license|"
    r"licence|issn|doi|published online|available online)\s*[:.]"
    r"|(?:received|accepted|published|revised|submitted)\b[^.\n]{0,60}"
    r"\d{4}"
    r"|\u00a9|copyright\b|(?:https?://)?(?:dx\.)?doi\.org/"
    r"|these authors contributed|corresponding author|to whom correspondence"
    r"|the authors?(?:\(s\))?,? \d{4}|published by\b"
    r"|this is an open access article|this article is"
    r"|creative commons|all rights reserved"
    r"|c\u20dd|\(c\)\s*\d{4}|for commercial re-?use|permissions@"
    r"|e?issn\b|editorial history|key ?words?\b|reviewers?:"
    r"|contributed by\b|author affiliations?:|author contributions:"
    r"|this article contains supporting information"
    r")",
    re.IGNORECASE)

# Líneas que no son texto: números de página y de línea, «Page 3 of 12».
_SOLO_NUMERO = re.compile(r"^\s*(?:page\s*)?\d{1,5}(?:\s*(?:of|/)\s*\d{1,5})?"
                          r"\s*$", re.IGNORECASE)

# El blanco entre tramos de un renglón, en múltiplos del tamaño de letra, a
# partir del cual el renglón es una fila de tabla.
HUECO_TABLA = 2.5

# Un bloque hecho solo de cifras y llamadas a figura: las ligas que quedan
# cuando el cuerpo de la página no trae capa de texto (PNAS 2026), o los
# números sueltos de un eje.
_SOLO_LLAMADAS = re.compile(
    r"^(?:\s|[\d,;.\u2013\u2014()\[\]-]|fig(?:ure)?s?\.?\s*s?\d+[a-z]?)+$",
    re.IGNORECASE)

# Lo que delata un renglón cortado a media oración (el final de una columna)
# y no un subtítulo: guion, coma o una palabra que no cierra frase.
_CORTADO = re.compile(r"(?:[-,;\u00ad]|\b(?:and|or|the|of|in|to|a|an|with|for|by|"
                      r"from|that|which|was|were|is|are|as|on|at))$")

_ES_TABLA = re.compile(r"^\s*(?:supplementary\s+)?tab(?:le)?\.?\s", re.IGNORECASE)

_FIN_ORACION = re.compile(r"[.!?][\"')\]\u201d\u2019]*$")


# ------------------------------------------------------------------ bloques

class Bloque(object):
    """Un bloque de texto de PyMuPDF con lo que el maquetado necesita."""

    __slots__ = ("pagina", "x0", "y0", "x1", "y1", "lineas", "tam",
                 "negrita", "col", "tabular", "usado")

    def __init__(self, pagina, lineas):
        self.pagina = pagina
        # [(texto, tam, negrita, bbox, spans, hueco, cursiva)], un renglón
        # cada una (ver `_renglones`).
        self.lineas = lineas
        self.x0 = min(l[3][0] for l in lineas)
        self.y0 = min(l[3][1] for l in lineas)
        self.x1 = max(l[3][2] for l in lineas)
        self.y1 = max(l[3][3] for l in lineas)
        pesos, neg, n = collections.Counter(), 0.0, 0
        for l in lineas:
            texto, tam, negrita = l[0], l[1], l[2]
            k = len(texto.strip())
            pesos[tam] += k
            neg += negrita * k
            n += k
        self.tam = pesos.most_common(1)[0][0] if pesos else 0.0
        self.negrita = neg / n if n else 0.0
        self.col = 0
        self.tabular = False
        self.usado = False

    @property
    def texto_crudo(self):
        return " ".join(l[0].strip() for l in self.lineas)

    @property
    def n_caracteres(self):
        return sum(len(l[0].strip()) for l in self.lineas)


def _bloques_de_pagina(pagina):
    """[Bloque] de una página, con las líneas ya convertidas a texto.

    Antes de nada se juntan los tramos de un mismo renglón. MuPDF parte un
    renglón justificado en varias «líneas» cuando el blanco entre palabras
    es ancho (`from` `diverse` `sources`, cada una con su bbox): sin
    juntarlos, cada párrafo justificado parecía una fila de tabla y se
    perdía entero.
    """
    salida = []
    for b in pagina["bloques"]:
        lineas = []
        for renglon in _renglones(b["lineas"]):
            spans, bbox, hueco = renglon
            texto, tam, negrita, cursiva = texto_de_linea(spans)
            if texto.strip():
                lineas.append((texto, tam, negrita, bbox, spans, hueco,
                               cursiva))
        if lineas:
            salida.append(Bloque(pagina["numero"], lineas))
    return salida


def _renglones(lineas):
    """[(spans, bbox, hueco_mayor)] con los tramos del mismo renglón juntos.

    `hueco_mayor` es el blanco más ancho entre dos tramos, en múltiplos del
    tamaño de letra: entre palabras de un renglón justificado no pasa de
    uno o dos; entre celdas de una tabla es de varios.
    """
    filas = []
    for l in sorted(lineas, key=lambda l: (l["bbox"][1], l["bbox"][0])):
        x0, y0, x1, y1 = l["bbox"]
        centro, alto = (y0 + y1) / 2.0, max(1.0, y1 - y0)
        for fila in filas:
            if abs(fila["centro"] - centro) < 0.45 * min(alto, fila["alto"]):
                fila["tramos"].append(l)
                break
        else:
            filas.append({"centro": centro, "alto": alto, "tramos": [l]})
    salida = []
    for fila in sorted(filas, key=lambda f: f["centro"]):
        tramos = _sin_numero_de_linea(
            sorted(fila["tramos"], key=lambda l: l["bbox"][0]))
        if not tramos:
            continue
        spans, hueco = [], 0.0
        for k, l in enumerate(tramos):
            if k:
                previo = tramos[k - 1]
                tam = max(s["tam"] for s in l["spans"]) or 1.0
                hueco = max(hueco, (l["bbox"][0] - previo["bbox"][2]) / tam)
                ultimo = spans[-1]["texto"] if spans else ""
                if ultimo and not ultimo.endswith(" "):
                    spans.append(dict(spans[-1], texto=" ", negrita=False))
            spans.extend(l["spans"])
        bbox = (min(l["bbox"][0] for l in tramos),
                min(l["bbox"][1] for l in tramos),
                max(l["bbox"][2] for l in tramos),
                max(l["bbox"][3] for l in tramos))
        salida.append((spans, bbox, hueco))
    return salida


def _clave_margen(texto):
    t = re.sub(r"\d+", "#", texto.lower())
    return " ".join(t.split())


def quitar_margenes(paginas, bloques_por_pagina):
    """Quita cabezas y pies de página repetidos, y números sueltos.

    Una línea del 8 % superior o inferior de la página que se repite (con los
    números cambiados por `#`) en al menos dos páginas y en un cuarto de
    ellas es una cabeza o pie corrido: `2460 LU ET AL. J. BACTERIOL.`. Las
    líneas que son solo un número, donde sea, son de página o de línea (los
    preprints numeran cada renglón).
    """
    n_pag = len(paginas)
    cuenta = collections.Counter()
    for pag, bloques in zip(paginas, bloques_por_pagina):
        y0, alto = pag.get("y0", 0.0), pag["alto"]
        vistas = set()
        for b in bloques:
            for l in b.lineas:
                bb = l[3]
                if bb[3] - y0 < 0.085 * alto or bb[1] - y0 > 0.915 * alto:
                    vistas.add(_clave_margen(l[0]))
        cuenta.update(vistas)
    umbral = max(2, int(0.25 * n_pag + 0.999))
    repetidas = set(k for k, n in cuenta.items() if n >= umbral and k)
    quitadas = 0
    salida = []
    for pag, bloques in zip(paginas, bloques_por_pagina):
        y0, alto = pag.get("y0", 0.0), pag["alto"]
        nuevos = []
        for b in bloques:
            lineas = []
            for l in b.lineas:
                bb = l[3]
                margen = (bb[3] - y0 < 0.085 * alto
                          or bb[1] - y0 > 0.915 * alto)
                if _SOLO_NUMERO.match(l[0]) or (
                        margen and _clave_margen(l[0]) in repetidas):
                    quitadas += 1
                    continue
                lineas.append(l)
            if lineas:
                nuevos.append(Bloque(b.pagina, lineas))
        salida.append(nuevos)
    return salida, quitadas


def _texto_de_tramo(l):
    return "".join(s["texto"] for s in l["spans"]).strip()


def _sin_numero_de_linea(tramos):
    """El renglón sin el número de línea de los preprints, que MuPDF a veces
    deja en el mismo renglón que el texto (`78 2.1 Evaluation of ...`): un
    tramo de puras cifras, separado del resto por más de una letra de ancho,
    al principio o al final. Un «2 mM» de un renglón justificado no se
    separa tanto."""
    def lejos(a, b):
        tam = max(s["tam"] for s in b["spans"]) or 10.0
        return b["bbox"][0] - a["bbox"][2] > max(6.0, tam)

    while (len(tramos) > 1 and re.match(r"^\d{1,5}$", _texto_de_tramo(tramos[0]))
           and lejos(tramos[0], tramos[1])):
        tramos = tramos[1:]
    while (len(tramos) > 1 and re.match(r"^\d{1,5}$", _texto_de_tramo(tramos[-1]))
           and lejos(tramos[-2], tramos[-1])):
        tramos = tramos[:-1]
    return tramos


def _marcar_tabulares(bloques):
    """Un bloque con un renglón partido por un blanco de varias letras de
    ancho es una fila de tabla: entre palabras de un renglón justificado el
    blanco no pasa de una o dos. PyMuPDF deja las celdas de una fila como
    tramos del mismo renglón."""
    for b in bloques:
        if any(l[5] >= HUECO_TABLA for l in b.lineas):
            b.tabular = True


def _marcar_regiones_de_tabla(bloques):
    """Las celdas sueltas dentro de una tabla también son tabla.

    PyMuPDF deja como bloque aparte la segunda línea de una celda (`pUC19`,
    `This study (Fig. 1)`), que no tiene hueco ancho y pasaba por párrafo:
    pegada por el orden de lectura a la última línea de una columna, metía
    la celda a media oración. Dos o más filas de tabla seguidas delimitan
    una región, y todo bloque corto cuyo centro cae dentro de ella es tabla.
    """
    filas = sorted((b for b in bloques if b.tabular), key=lambda b: b.y0)
    grupos = []
    for b in filas:
        g = grupos[-1] if grupos else None
        if (g is not None and b.y0 - g["y1"] <= 30
                and min(b.x1, g["x1"]) > max(b.x0, g["x0"])):
            g["n"] += 1
            g["x0"], g["x1"] = min(g["x0"], b.x0), max(g["x1"], b.x1)
            g["y1"] = max(g["y1"], b.y1)
        else:
            grupos.append({"x0": b.x0, "y0": b.y0, "x1": b.x1, "y1": b.y1,
                           "n": 1})
    regiones = [g for g in grupos if g["n"] >= 2]
    for b in bloques:
        if b.tabular or b.n_caracteres >= 200:
            continue
        cx, cy = (b.x0 + b.x1) / 2.0, (b.y0 + b.y1) / 2.0
        for g in regiones:
            if g["x0"] - 2 <= cx <= g["x1"] + 2 and g["y0"] - 2 <= cy <= g["y1"] + 2:
                b.tabular = True
                break


def ordenar(bloques):
    """El orden de lectura de una página a una o dos columnas.

    Los bloques que cruzan el canal entre columnas (título, resumen, una
    tabla o figura a lo ancho) parten la página en franjas; dentro de cada
    franja va primero la columna izquierda de arriba abajo y después la
    derecha. Es la regla de lectura de las revistas a dos columnas, y la que
    el orden de PyMuPDF (el del flujo del PDF) rompe cuando la tabla se
    compuso antes que el texto que la rodea.
    """
    if not bloques:
        return []
    x0 = min(b.x0 for b in bloques)
    x1 = max(b.x1 for b in bloques)
    ancho = (x1 - x0) or 1.0
    medio = (x0 + x1) / 2.0
    holgura = 0.04 * ancho
    for b in bloques:
        if b.x0 < medio - holgura and b.x1 > medio + holgura:
            b.col = 0
        elif (b.x0 + b.x1) / 2.0 < medio:
            b.col = 1
        else:
            b.col = 2
    anchos = sorted((b for b in bloques if b.col == 0), key=lambda b: b.y0)
    resto = [b for b in bloques if b.col != 0]
    salida, arriba = [], float("-inf")
    for corte in anchos + [None]:
        abajo = corte.y0 if corte is not None else float("inf")
        franja = [b for b in resto if arriba <= (b.y0 + b.y1) / 2.0 < abajo]
        for col in (1, 2):
            salida.extend(sorted((b for b in franja if b.col == col),
                                 key=lambda b: (b.y0, b.x0)))
        if corte is not None:
            salida.append(corte)
            arriba = corte.y0
    return salida


# ------------------------------------------------------------- unir líneas

_PALABRA = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")


def vocabulario(bloques):
    """Conteo de palabras del documento, con y sin guion. Decide si un guion
    de fin de renglón es corte (`argi-nine`) o parte del nombre
    (`two-component`)."""
    c = collections.Counter()
    for b in bloques:
        for l in b.lineas:
            c.update(w.lower() for w in _PALABRA.findall(l[0]))
    return c


_CORTE = re.compile(r"([A-Za-z0-9]+)[-\u00ad]$")
_INICIO = re.compile(r"^([A-Za-z0-9]+)")


def unir(previo, siguiente, vocab):
    """Pega dos tramos de texto (renglones o párrafos que siguen la misma
    oración), resolviendo el guion de corte.

    El guion se quita si la palabra unida aparece en el documento y la
    partida no; se conserva si es al revés, o si alguna mitad lleva
    mayúscula o cifra (`mexEF-` + `oprN`, `PA0762-`), que es como se ven los
    nombres de genes y operones que el diccionario necesita enteros. En la
    duda, se quita: un corte de renglón es mucho más común que un compuesto
    partido justo en su guion.
    """
    previo = previo.rstrip()
    siguiente = siguiente.lstrip()
    if not previo:
        return siguiente
    if not siguiente:
        return previo
    m = _CORTE.search(previo)
    n = _INICIO.match(siguiente)
    if m and n and previo[-1] in "-\u00ad":
        a, b = m.group(1), n.group(1)
        if previo[-1] == "\u00ad":
            return previo[:-1] + siguiente
        if not b[0].islower():
            return previo + siguiente
        unida, partida = (a + b).lower(), (a + "-" + b).lower()
        if vocab.get(partida, 0) > vocab.get(unida, 0):
            return previo + siguiente
        if vocab.get(unida, 0) > 0:
            return previo[:-1] + siguiente
        if any(c.isupper() or c.isdigit() for c in a):
            return previo + siguiente
        return previo[:-1] + siguiente
    return previo + " " + siguiente


def texto_de_bloque(lineas, vocab):
    texto = ""
    for l in lineas:
        texto = unir(texto, l[0], vocab)
    return _limpiar_parrafo(texto)


def _limpiar_parrafo(t):
    """Blancos colapsados y guiones suaves fuera, salvo el final: ese es un
    corte que todavía puede unirse con el párrafo siguiente."""
    final = t.rstrip().endswith(_GUION_SUAVE)
    t = " ".join(t.replace(_GUION_SUAVE, "").split())
    if final:
        t += _GUION_SUAVE
    # Un párrafo que empezara con `#` se leería como encabezado.
    return t.lstrip("#").lstrip()


# ---------------------------------------------------------------- maquetar

def _modo(valores_pesos):
    c = collections.Counter()
    for v, p in valores_pesos:
        c[v] += p
    return c.most_common(1)[0][0] if c else 0.0


def _mediana_ponderada(valores_pesos):
    pares = sorted(valores_pesos)
    total = sum(p for _, p in pares)
    acumulado = 0
    for v, p in pares:
        acumulado += p
        if acumulado * 2 >= total:
            return v
    return None


def _es_prosa(texto):
    """Un párrafo de verdad: largo, con oraciones, sin pinta de afiliación."""
    if len(texto) < 250:
        return False
    if len(re.findall(r"[a-z][.!?]\s+[A-Z(]", texto)) < 2:
        return False
    return not _afiliacion(texto)


def _afiliacion(texto):
    """Dos o más señas de afiliación o de metadatos de portada."""
    return len(re.findall(
        r"universit|department|institut|laborator|school of|faculty|"
        r"hospital|college|@|e-?mail|received|accepted|copyright|\u00a9",
        texto, re.IGNORECASE)) >= 2


def _estilo(b, ancho_col):
    """La firma tipográfica de un bloque: tamaño, negrita y si va a lo ancho.
    Distingue el resumen sin etiqueta (negrita y a lo ancho en la ASM) de la
    introducción sin etiqueta que le sigue."""
    return (round(b.tam * 2) / 2.0, b.negrita >= 0.5,
            (b.x1 - b.x0) > 1.25 * ancho_col)


class _Parrafo(object):
    """Un párrafo de salida y el bloque que lo abrió (para partir secciones
    por la letra de su primer bloque)."""

    __slots__ = ("texto", "bloque", "subtitulo")

    def __init__(self, texto, bloque, subtitulo=False):
        self.texto, self.bloque, self.subtitulo = texto, bloque, subtitulo


class _Doc(object):
    """El estado del recorrido: secciones abiertas, pies, lo descartado."""

    def __init__(self, vocab, cuenta):
        self.vocab = vocab
        self.secciones = []           # [[etiqueta, [_Parrafo]]]
        self.frente = []              # [_Parrafo] antes del primer `##`
        self.pies = []                # [texto]
        self.modo_pies = False
        self.cuenta = cuenta

    def abrir(self, etiqueta):
        self.modo_pies = False
        self.secciones.append([etiqueta, []])

    def tras_el_cuerpo(self):
        """Ya se abrió alguna sección del cuerpo y la abierta no es una que
        excluya el bronce (ahí la bibliografía ya no estorba)."""
        etiquetas = [s[0] for s in self.secciones]
        return (bool(_CUERPO.intersection(etiquetas))
                and etiquetas[-1] in _CUERPO | {"ABSTRACT", "INTRODUCTION",
                                                 "BACKGROUND"})

    def parrafo(self, texto, bloque, subtitulo=False):
        texto = texto.strip()
        if not texto:
            return
        destino = self.secciones[-1][1] if self.secciones else self.frente
        previo = destino[-1] if destino else None
        if (not subtitulo and previo is not None and not previo.subtitulo
                and _sigue(previo.texto, texto)):
            previo.texto = _limpiar_parrafo(unir(previo.texto, texto,
                                                 self.vocab))
            return
        destino.append(_Parrafo(texto, bloque, subtitulo))

    def pie(self, texto, nuevo):
        if nuevo or not self.pies:
            self.pies.append(texto)
        else:
            self.pies[-1] = _limpiar_parrafo(unir(self.pies[-1], texto,
                                                  self.vocab))


def _sigue(previo, siguiente):
    """El párrafo siguiente continúa la oración del previo: el previo no
    cierra oración y el siguiente empieza en minúscula (el salto de columna o
    de página cayó a media frase)."""
    if _FIN_ORACION.search(previo):
        return False
    return bool(siguiente) and (siguiente[0].islower()
                                or previo.endswith(("-", "\u00ad", ",")))


def _encabezado_en_linea(b, vocab):
    """(etiqueta, resto) si el bloque empieza con una etiqueta conocida en
    negrita o versalitas pegada al texto: `ABSTRACT The ...`."""
    primera = b.lineas[0]
    cabeza = ""
    for s in primera[4]:
        t = normalizar(s["texto"])
        if not (s.get("negrita") or (t.strip() and t.strip().isupper())):
            break
        cabeza += t
        if len(cabeza) > 60:
            return None
    cabeza = cabeza.strip()
    if not cabeza or len(cabeza) >= len(primera[0].strip()):
        return None
    etiqueta = etiqueta_conocida(cabeza)
    if etiqueta not in _EN_LINEA:
        return None
    resto = primera[0].strip()[len(cabeza):].lstrip(" .:\u2014\u2013-|")
    lineas = [(resto,) + tuple(primera[1:])] + list(b.lineas[1:])
    return etiqueta, texto_de_bloque(lineas, vocab)


def _subtitulo_en_linea(b, cuerpo_negrita):
    """El subtítulo con que empieza un bloque, o None.

    Dos formas, las dos un `###` en el XML:

    - en línea: una frase en negrita que termina en punto y sigue en
      redonda, `Construction of mutants. We ...` (la ASM);
    - en renglones propios: uno a tres renglones en negrita, sin punto, y el
      párrafo debajo en el mismo bloque (BMC, Frontiers, MDPI). Sin
      separarlo, el subtítulo se pegaba a la primera oración del párrafo
      y la volvía otra oración, con los genes del título incluidos.
    """
    if cuerpo_negrita or b.negrita >= 0.95:
        return None
    cabeza, renglones = "", 0
    for linea in b.lineas:
        for s in linea[4]:
            t = normalizar(s["texto"])
            if not s.get("negrita"):
                if not t.strip():
                    cabeza += t
                    continue
                c = " ".join(cabeza.split())
                en_renglones = (renglones > 0 and _empieza_renglon(linea, s)
                                and not c.endswith(","))
                if (3 <= len(c) <= 200 and _arranque_de_titulo(c)
                        and (c[-1] in ".:" or en_renglones)):
                    return c
                return None
            cabeza += t
        renglones += 1
        cabeza += " "
        if len(cabeza) > 200 or renglones > 3:
            return None
    return None


def _arranque_de_titulo(c):
    return c[0].isupper() or c[0].isdigit() or c[0] in "(\u0394\u03b1\u03b2"


def _empieza_renglon(linea, span):
    """El span es el primero visible de su renglón: el subtítulo ocupó
    renglones enteros."""
    for s in linea[4]:
        if s["texto"].strip():
            return s is span
    return False


def _quitar_cabeza(lineas, cabeza):
    """Las líneas del bloque sin los primeros caracteres visibles que ocupa
    `cabeza` (el subtítulo en línea)."""
    falta = len(re.sub(r"\s+", "", cabeza))
    salida = []
    for l in lineas:
        texto = l[0]
        if falta <= 0:
            salida.append(l)
            continue
        i = 0
        while i < len(texto) and falta > 0:
            if not texto[i].isspace():
                falta -= 1
            i += 1
        resto = texto[i:].lstrip(" .:\u2014\u2013")
        if resto.strip():
            salida.append((resto,) + tuple(l[1:]))
    return salida


def _es_pie(b, texto, cuerpo_tam, modo_pies):
    """El bloque empieza un pie de figura o tabla.

    Hace falta algo más que el patrón, porque «Figure 2. ...» también puede
    ser una oración del cuerpo que cita la figura con punto: el rótulo va
    con puntuación propia, o en negrita, o el bloque va en letra menor que el
    cuerpo, o ya se está en la sección de leyendas.
    """
    m = _PIE.match(texto)
    if not m:
        return False
    if modo_pies or b.tam < cuerpo_tam - 0.3:
        return True
    if m.group(0).rstrip()[-1:] in ".:|\u2014\u2013":
        return True
    primer = b.lineas[0][4][0] if b.lineas[0][4] else {}
    return bool(primer.get("negrita"))


def maquetar(paginas):
    """{titulo, secciones, pies, cuenta} desde las páginas de `extraer`.

    `secciones` es [(etiqueta, [párrafo])] en orden; un párrafo que empieza
    con `\\n### ` es un subtítulo. `cuenta` dice qué se descartó y por qué,
    para el registro de la conversión.
    """
    crudos = [_bloques_de_pagina(p) for p in paginas]
    por_pagina, quitadas = quitar_margenes(paginas, crudos)
    cuenta = collections.Counter(lineas_de_margen=quitadas)
    todos = [b for bs in por_pagina for b in bs]
    if not todos:
        return {"titulo": "", "secciones": [], "pies": [], "cuenta": cuenta}

    vocab = vocabulario(todos)
    # La letra y el ancho del cuerpo, contados por carácter sobre todos los
    # renglones y no sobre los bloques largos: en un manuscrito con números de
    # línea cada renglón es su propio bloque, y entonces los únicos «largos»
    # eran los rótulos de las figuras, con su letra menor; el cuerpo entero
    # parecía más grande que el cuerpo y cada renglón salía como subtítulo.
    renglones = [l for b in todos for l in b.lineas]
    cuerpo_tam = _modo((l[1], len(l[0].strip())) for l in renglones)
    total = float(sum(len(l[0].strip()) for l in renglones)) or 1.0
    cuerpo_negrita = sum(l[2] * len(l[0].strip()) for l in renglones) / total > 0.5
    ancho_col = _mediana_ponderada(
        [(l[3][2] - l[3][0], len(l[0].strip())) for l in renglones
         if len(l[0].strip()) >= 30]) or 300.0

    orden = []
    for bs in por_pagina:
        _marcar_tabulares(bs)
        _marcar_regiones_de_tabla(bs)
        orden.extend(ordenar(bs))

    # La letra de cada página. En un artículo de la ASM los métodos y la
    # bibliografía van en 7 puntos y los resultados en 9: contra los 7 del
    # documento, todo renglón suelto de los resultados parecía un subtítulo
    # «más grande». Un subtítulo es más grande que lo que le rodea.
    tam_pagina = {}
    for bs in por_pagina:
        if bs:
            tam_pagina[bs[0].pagina] = max(cuerpo_tam, _modo(
                (l[1], len(l[0].strip())) for b in bs for l in b.lineas))

    titulo = _titulo(por_pagina, cuerpo_tam)

    doc = _Doc(vocab, cuenta)
    pie_previo = None
    capitular = ""
    for b in orden:
        if b.usado:
            continue
        texto = texto_de_bloque(b.lineas, vocab)
        if not texto:
            continue
        # La letra capitular de la ASM: un bloque con una sola mayúscula
        # enorme. Sin pegarla, la introducción empezaba en «seudomonas».
        if len(texto) == 1 and texto.isupper() and b.tam >= 1.8 * cuerpo_tam:
            capitular = texto
            continue
        # Pies de figura y tabla: van al final, como en el JATS. El de una
        # tabla no se continúa con lo que sigue: debajo del título viene la
        # tabla misma, en la misma letra chica.
        if _es_pie(b, texto, cuerpo_tam, doc.modo_pies):
            doc.pie(texto, nuevo=True)
            pie_previo = None if _ES_TABLA.match(texto) else b
            cuenta["pies"] += 1
            continue
        if pie_previo is not None and _continua_pie(pie_previo, b, cuerpo_tam):
            doc.pie(texto, nuevo=False)
            pie_previo = b
            continue
        pie_previo = None
        etiqueta = etiqueta_conocida(texto) if len(texto) <= 80 else None
        if doc.modo_pies and not etiqueta:
            doc.pie(texto, nuevo=False)
            continue
        if b.tabular:
            cuenta["bloques_de_tabla"] += 1
            continue
        if _METADATO.match(texto) and len(texto) < 1500:
            cuenta["bloques_de_metadatos"] += 1
            continue
        if _texto_de_figura(b, texto, cuerpo_tam):
            cuenta["bloques_de_figura"] += 1
            continue

        # Encabezados: el bloque entero, su primera línea, o en línea.
        if etiqueta and not doc.secciones and etiqueta not in _ABREN:
            # «Open access», «Keywords», «Abbreviations» en la portada: si
            # abrieran sección, la introducción sin etiqueta que les sigue
            # quedaría como 'excluir'.
            cuenta["encabezados_de_portada"] += 1
            continue
        if etiqueta:
            doc.abrir(etiqueta)
            continue
        if len(texto) <= 60 and _clave(texto) in _CLAVES_PIES:
            doc.modo_pies = True
            continue
        primera = b.lineas[0][0].strip()
        etiqueta = etiqueta_conocida(primera) if len(primera) <= 60 else None
        # La primera línea es el encabezado y el resto del bloque su primer
        # párrafo. No se le exige estilo: un renglón que no dice otra cosa
        # que la etiqueta (`etiqueta_conocida` compara el renglón entero) no
        # es prosa, y a veces la negrita no se declara: «References» sobre
        # «1. Branski LK, ...» en BMC.
        if etiqueta and len(b.lineas) > 1:
            if doc.secciones or etiqueta in _ABREN:
                doc.abrir(etiqueta)
            else:
                cuenta["encabezados_de_portada"] += 1
            doc.parrafo(texto_de_bloque(b.lineas[1:], vocab), b)
            continue
        en_linea = _encabezado_en_linea(b, vocab)
        if en_linea and not doc.secciones and en_linea[0] not in _ABREN:
            cuenta["encabezados_de_portada"] += 1
            continue
        if en_linea:
            doc.abrir(en_linea[0])
            doc.parrafo(en_linea[1], b)
            continue
        if _encabezado_suelto(b, texto, tam_pagina.get(b.pagina, cuerpo_tam),
                              cuerpo_negrita):
            doc.parrafo(texto.rstrip(".:"), b, subtitulo=True)
            continue
        if _rotulo_suelto(b, texto, ancho_col):
            cuenta["rotulos_sueltos"] += 1
            continue
        sub = _subtitulo_en_linea(b, cuerpo_negrita)
        if sub:
            doc.parrafo(sub.rstrip(".:"), b, subtitulo=True)
            doc.parrafo(texto_de_bloque(_quitar_cabeza(b.lineas, sub), vocab),
                        b)
            continue
        if capitular:
            texto, capitular = capitular + texto, ""
        if _parece_bibliografia(texto) and doc.tras_el_cuerpo():
            # Una lista de referencias sin encabezado reconocible (Science
            # Advances, Scientific Reports): sin esto se quedaba en la
            # sección anterior, la discusión a veces, como si fuera prosa.
            doc.abrir("REFERENCES")
            cuenta["bibliografia_sin_encabezado"] += 1
        doc.parrafo(texto, b)

    secciones = _ordenar_frente(doc, ancho_col)
    secciones = _separar_lista_de_referencias(secciones, cuenta)
    return {"titulo": titulo, "secciones": secciones, "pies": doc.pies,
            "cuenta": cuenta}


# Una entrada de bibliografía numerada, un párrafo por entrada:
# `12. Jacob F, Monod J (1961) Genetic ... J Mol Biol 3:318–356`.
_ENTRADA = re.compile(r"^\s*(?:\[\d{1,4}\]|\d{1,4}\.)\s+[A-Z\u00c0-\u017f]")
_ANIO = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
MIN_ENTRADAS = 6


def _es_entrada(texto):
    return (len(texto) < 700 and bool(_ENTRADA.match(texto))
            and bool(_ANIO.search(texto)))


def _separar_lista_de_referencias(secciones, cuenta):
    """La bibliografía de entradas sueltas que se quedó en una sección del
    cuerpo pasa a REFERENCES.

    Es la de los artículos en otra lengua (`Literatura`, `Kaynaklar`), cuyo
    rótulo no está entre los conocidos: cada entrada es un párrafo con un
    solo año, así que `_parece_bibliografia` (la de listas en un párrafo)
    no la ve. Se corta donde empiezan `MIN_ENTRADAS` entradas seguidas, si
    desde ahí hasta el fin de la sección casi todo es entrada: los nombres
    de genes de los títulos citados no deben volverse oraciones candidatas.
    """
    salida = []
    for etiqueta, textos in secciones:
        corte = None
        if etiqueta not in ("REFERENCES", ETIQUETA_PIES):
            es = [_es_entrada(t) for t in textos]
            for i in range(len(textos) - MIN_ENTRADAS + 1):
                if all(es[i:i + MIN_ENTRADAS]) and \
                        sum(es[i:]) >= 0.8 * (len(textos) - i):
                    corte = i
                    break
        if corte is None:
            salida.append((etiqueta, textos))
            continue
        if corte:
            salida.append((etiqueta, textos[:corte]))
        salida.append(("REFERENCES", textos[corte:]))
        cuenta["bibliografia_por_entradas"] += 1
    return salida


def _con_estilo(linea, cuerpo_tam, cuerpo_negrita):
    texto, tam, negrita = linea[0], linea[1], linea[2]
    letras = [c for c in texto if c.isalpha()]
    mayusculas = len(letras) >= 4 and all(c.isupper() for c in letras)
    return (tam >= cuerpo_tam + 0.9 or (negrita >= 0.6 and not cuerpo_negrita)
            or mayusculas)


def _encabezado_suelto(b, texto, cuerpo_tam, cuerpo_negrita):
    """Un subtítulo en su propio bloque: corto, sin punto final, con letra
    distinta de la del cuerpo y empezando con mayúscula o cifra."""
    if len(b.lineas) > 3 or len(texto) > 200 or len(texto) < 3:
        return False
    if not _arranque_de_titulo(texto) or _CORTADO.search(texto):
        return False
    if texto.endswith("."):
        # Los subtítulos de la ASM desde 2014 llevan punto y van solos, en
        # negrita: se aceptan si el bloque entero es negrita o más grande.
        return ((b.negrita >= 0.9 and not cuerpo_negrita)
                or b.tam >= cuerpo_tam + 0.9)
    return _con_estilo((texto, b.tam, b.negrita), cuerpo_tam, cuerpo_negrita)


def _continua_pie(previo, b, cuerpo_tam):
    """El bloque sigue el pie anterior: misma página, mismo tamaño de letra
    (que no es el del cuerpo), pegado debajo y en la misma columna."""
    if b.pagina != previo.pagina or abs(b.tam - previo.tam) > 0.3:
        return False
    if abs(b.tam - cuerpo_tam) < 0.3:
        return False
    alto = max(1.0, (previo.y1 - previo.y0) / max(1, len(previo.lineas)))
    pegado = -alto <= b.y0 - previo.y1 <= 2.5 * alto
    traslape = min(b.x1, previo.x1) - max(b.x0, previo.x0) > 0
    return pegado and traslape


_CUERPO = frozenset(["RESULTS", "RESULTS AND DISCUSSION", "DISCUSSION",
                     "DISCUSSION AND CONCLUSIONS", "CONCLUSIONS"])

_REF_ANIO = re.compile(r"\((?:19|20)\d{2}[a-z]?\)|\b(?:19|20)\d{2}[a-z]?[;,:.]\s*\d+"
                       r"|\b\d+\s*:\s*\d+\s*[\u2013-]\s*\d+")
_REF_INICIO = re.compile(r"^\s*(?:\[\d+\]|\d{1,3}\.)\s+\S"
                         r"|^[A-Z][A-Za-z'\u2019-]+,?\s+(?:[A-Z]\.\s*){1,3}[,;]?"
                         r"|^[A-Z][A-Za-z'\u2019-]+\s+[A-Z]{1,3}[,.]")


def _parece_bibliografia(texto):
    """Un párrafo que es una lista de referencias: empieza como una (número
    o apellido con iniciales) y trae al menos tres años con volumen o
    páginas."""
    return (bool(_REF_INICIO.match(texto))
            and len(_REF_ANIO.findall(texto)) >= 3)


def _rotulo_suelto(b, texto, ancho_col):
    """Un bloque corto, angosto y sin puntuación de oración que no es
    encabezado: un rótulo de figura (`A B PA0601 PA0756`), una celda. Pegado
    al párrafo vecino por el orden de lectura, metía genes en una oración
    que no los nombra. Se deja pasar si empieza en minúscula: es la cola de
    una oración que siguió en otra columna."""
    if len(texto) > 80 or _FIN_ORACION.search(texto) or texto[0].islower():
        return False
    return all((l[3][2] - l[3][0]) < 0.5 * ancho_col for l in b.lineas)


def _texto_de_figura(b, texto, cuerpo_tam):
    """Rótulos de dentro de una figura o celdas sueltas: letra chica, corto y
    sin oraciones. Son nombres de genes sueltos que, pegados por el orden de
    lectura, fabricarían una oración con diez genes."""
    if _SOLO_LLAMADAS.match(texto):
        return True
    return (b.tam < cuerpo_tam - 1.2 and len(texto) < 200
            and not _FIN_ORACION.search(texto))


def _titulo(por_pagina, cuerpo_tam):
    """El título: lo más grande de la primera página, si es más grande que el
    cuerpo. Los bloques que lo forman se marcan como usados."""
    for bs in por_pagina[:2]:
        candidatos = [b for b in bs if b.tam >= cuerpo_tam + 1.5
                      and len(b.texto_crudo) >= 10
                      and not _METADATO.match(b.texto_crudo)]
        if not candidatos:
            continue
        mayor = max(b.tam for b in candidatos)
        partes = [b for b in sorted(bs, key=lambda b: (b.y0, b.x0))
                  if abs(b.tam - mayor) <= 0.6 and len(b.texto_crudo) >= 2]
        # Solo el primer grupo contiguo de ese tamaño: un subtítulo del mismo
        # cuerpo más abajo no es parte del título.
        grupo = [partes[0]]
        for b in partes[1:]:
            if b.y0 - grupo[-1].y1 <= mayor * 1.6:
                grupo.append(b)
            else:
                break
        for b in grupo:
            b.usado = True
        return " ".join(" ".join(b.texto_crudo.split()) for b in grupo)
    return ""


def _ordenar_frente(doc, ancho_col):
    """Las secciones finales, con la portada resuelta.

    Lo que va antes del primer `##` es la portada: autores, afiliaciones,
    fechas... y a veces el resumen y la introducción sin etiqueta (la ASM
    hasta 2014 no rotula ninguno de los dos). De la portada se queda solo la
    prosa (`_es_prosa`): el primer párrafo de prosa abre el `## ABSTRACT` y
    los que tienen su misma letra lo siguen; el resto es la introducción.

    Si el documento rotula el resumen pero no la introducción, y lo que
    sigue al resumen es una sección principal (o nada), el resumen se parte
    donde cambia la letra: lo de después es la introducción sin etiqueta.
    """
    secciones = [[e, list(ps)] for e, ps in doc.secciones]
    etiquetas = [s[0] for s in secciones]
    hay_resumen = "ABSTRACT" in etiquetas
    hay_intro = "INTRODUCTION" in etiquetas or "BACKGROUND" in etiquetas

    nuevas = []
    # Desde el primer párrafo de prosa, todo lo que no tenga pinta de
    # afiliación: la introducción sin etiqueta también tiene párrafos cortos,
    # y en un artículo sin ningún encabezado conocido (en polaco, en turco)
    # la portada es el artículo entero.
    inicio = next((k for k, p in enumerate(doc.frente)
                   if not p.subtitulo and _es_prosa(p.texto)), None)
    prosa = [] if inicio is None else [
        p for p in doc.frente[inicio:]
        if not p.subtitulo and not _afiliacion(p.texto)]
    # Con un resumen rotulado después, la prosa de la portada también se
    # queda si es mucha: PNAS pone el resumen sin etiqueta y el principio
    # de la introducción en la columna izquierda, antes del recuadro
    # «Significance» de la derecha; y las revistas en otra lengua ponen el
    # «Abstract» en inglés al final, después de todo el artículo.
    mucha = sum(len(p.texto) for p in prosa) >= 600
    if prosa and (not hay_resumen or mucha):
        firma = _estilo(prosa[0].bloque, ancho_col)
        sigue_intro = bool(secciones) and secciones[0][0] in (
            "INTRODUCTION", "BACKGROUND")
        resumen, intro = [prosa[0]], []
        for p in prosa[1:]:
            if not intro and (sigue_intro
                              or _estilo(p.bloque, ancho_col) == firma):
                resumen.append(p)
            else:
                intro.append(p)
        nuevas.append(["ABSTRACT", resumen])
        doc.cuenta["resumen_sin_etiqueta"] += 1
        if intro:
            nuevas.append(["INTRODUCTION", intro])
            doc.cuenta["introduccion_sin_etiqueta"] += 1
            hay_intro = True
    secciones = nuevas + secciones
    etiquetas = [s[0] for s in secciones]

    if "ABSTRACT" in etiquetas and not hay_intro:
        i = etiquetas.index("ABSTRACT")
        siguiente = etiquetas[i + 1] if i + 1 < len(etiquetas) else None
        if siguiente is None or siguiente in _PRINCIPALES:
            ps = secciones[i][1]
            k = _corte_por_estilo(ps, ancho_col)
            if k is not None:
                secciones.insert(i + 1, ["INTRODUCTION", ps[k:]])
                secciones[i][1] = ps[:k]
                doc.cuenta["introduccion_sin_etiqueta"] += 1

    salida = []
    for etiqueta, ps in secciones:
        textos = []
        for p in ps:
            t = p.texto.rstrip(_GUION_SUAVE)
            textos.append("\n### " + t.upper() if p.subtitulo else t)
        salida.append((etiqueta, textos))
    return salida


def _corte_por_estilo(parrafos, ancho_col):
    """El primer párrafo con letra distinta de la del primero, o None."""
    if len(parrafos) < 2:
        return None
    firma = _estilo(parrafos[0].bloque, ancho_col)
    for k, p in enumerate(parrafos[1:], 1):
        if (not p.subtitulo and len(p.texto) >= 150
                and _estilo(p.bloque, ancho_col) != firma):
            return k
    return None


def a_texto(resultado):
    """El texto final, con las partes unidas como las une `jats_a_texto`."""
    partes = []
    if resultado["titulo"]:
        partes.append("# " + " ".join(resultado["titulo"].split()))
    for etiqueta, parrafos in resultado["secciones"]:
        partes.append("\n## " + etiqueta)
        partes.extend(p for p in parrafos if p.strip())
    if resultado["pies"]:
        partes.append("\n## " + ETIQUETA_PIES)
        partes.extend(_cerrar(p.rstrip(_GUION_SUAVE))
                      for p in resultado["pies"] if p.strip())
    return "\n\n".join(partes)


def _cerrar(pie):
    """Un pie que no termina en puntuación de oración la recibe. El título
    de una tabla (`Table 1 Strains and plasmids`) no la trae, y el
    segmentador lo pegaba con el pie siguiente en una sola oración."""
    return pie if _FIN_ORACION.search(pie) else pie + "."


def secciones_halladas(resultado):
    """Las etiquetas de `##` del documento, sin repetir y en orden."""
    vistas = []
    for etiqueta, _ in resultado["secciones"]:
        if etiqueta not in vistas:
            vistas.append(etiqueta)
    if resultado["pies"]:
        vistas.append(ETIQUETA_PIES)
    return vistas
