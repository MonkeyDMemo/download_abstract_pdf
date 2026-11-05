# -*- coding: utf-8 -*-
"""¿Cuánto del texto del XML sale del PDF? La medición con los duplicados.

Para cada artículo que tiene a la vez el `.txt` del XML de PMC y el `.txt`
convertido del PDF, se comparan las oraciones que el bronce examinaría en
cada uno: las de secciones que no son `excluir`, de 40 a 700 caracteres,
partidas con el mismo segmentador (`grn_bronce.texto.oraciones`, sobre los
cuerpos de `bloques_con_offset`). Es el camino exacto del bronce, para que la
cifra mida lo que el bronce va a leer y no otra cosa.

Cuatro fracciones por artículo:

- `recuperadas`: oraciones examinables del XML que están en el texto
  examinable del PDF;
- `ruido`: oraciones examinables del PDF que no están en ninguna parte del
  XML (cabezas de página que se colaron, celdas, columnas mal unidas);
- `candidatas_recuperadas` y `candidatas_ruido`: lo mismo restringido a las
  oraciones con 2 a 8 genes distintos del diccionario, que es el filtro de
  candidata de `identificar.py`. Son las que importan: una oración sin genes
  que se pierde no le cuesta nada a la red.

«Está» quiere decir, sobre el texto normalizado (minúsculas, NFKC y solo
letras y cifras, sin blancos: los cortes de renglón y la puntuación no
cuentan): que sea subcadena exacta del otro texto, o que su `difflib` ratio
con una oración del otro lado (o con dos o tres seguidas) llegue a 0.9.

El informe lleva PMID y cifras, nunca texto: los artículos son públicos, pero
el informe no necesita oraciones para decir cuánto se perdió.

Biblioteca estándar; se puede correr con cualquier intérprete del proyecto.
"""

import collections
import difflib
import glob
import io
import os
import re
import sys
import unicodedata

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from grn_bronce import texto as _texto              # noqa: E402

UMBRAL_RATIO = 0.9

# Los topes de `identificar.py`, leídos de ahí y no copiados: si el bronce los
# cambia, la validación mide lo nuevo.
def _topes():
    from grn_bronce import identificar
    return (identificar.MIN_ORACION, identificar.MAX_ORACION,
            identificar.MAX_MENCIONES, identificar.SECCIONES_FUERA)


def _nada(_m):
    pass


def normalizar(s):
    """Solo letras y cifras, en minúsculas y NFKC."""
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(c for c in s if c.isalnum())


_TOKEN = re.compile(r"[^\W_]{3,}", re.UNICODE)


def tokens(s):
    return set(_TOKEN.findall(unicodedata.normalize("NFKC", s).lower()))


def oraciones_de(md, clases, fuera):
    """[(clase, oración)] del texto, por el camino del bronce."""
    salida = []
    for etiqueta, cuerpo, _tramos in _texto.bloques_con_offset(md):
        clase = (clases.get(etiqueta, _texto.CLASE_DESCONOCIDA)
                 if etiqueta else _texto.CLASE_DESCONOCIDA)
        for o in _texto.oraciones(cuerpo):
            salida.append((clase, o))
    return salida


class Indice(object):
    """Las oraciones de un lado, listas para buscar las del otro."""

    def __init__(self, oraciones):
        self.norm = [normalizar(o) for o in oraciones]
        self.todo = "".join(self.norm)
        self.por_token = collections.defaultdict(set)
        for i, o in enumerate(oraciones):
            for t in tokens(o):
                self.por_token[t].add(i)

    def contiene(self, oracion):
        """True si la oración está: exacta o con ratio >= UMBRAL_RATIO."""
        n = normalizar(oracion)
        if not n:
            return True
        if n in self.todo:
            return True
        votos = collections.Counter()
        for t in tokens(oracion):
            for i in self.por_token.get(t, ()):
                votos[i] += 1
        for i, _ in votos.most_common(6):
            for a, b in ((i, i + 1), (i - 1, i + 1), (i, i + 2),
                         (i - 1, i + 2), (i - 2, i + 1)):
                if a < 0 or b > len(self.norm):
                    continue
                otra = "".join(self.norm[a:b])
                if abs(len(otra) - len(n)) > 0.25 * len(n) + 10:
                    continue
                m = difflib.SequenceMatcher(None, n, otra, autojunk=False)
                if (m.real_quick_ratio() >= UMBRAL_RATIO
                        and m.quick_ratio() >= UMBRAL_RATIO
                        and m.ratio() >= UMBRAL_RATIO):
                    return True
        return False


def _es_candidata(oracion, lex, max_menciones):
    distintos = set(g[3] for g in lex.menciones(oracion))
    return 2 <= len(distintos) <= max_menciones


def comparar(md_xml, md_pdf, clases, lex):
    """Las cifras de un artículo (solo conteos)."""
    minimo, maximo, max_m, fuera = _topes()
    xml = oraciones_de(md_xml, clases, fuera)
    pdf = oraciones_de(md_pdf, clases, fuera)

    def examinables(ors):
        return [o for c, o in ors
                if c not in fuera and minimo <= len(o) <= maximo]

    xml_ex, pdf_ex = examinables(xml), examinables(pdf)
    indice_pdf = Indice(pdf_ex)
    indice_xml = Indice([o for _c, o in xml])     # todo el XML, para el ruido

    xml_cand = [o for o in xml_ex if _es_candidata(o, lex, max_m)]
    pdf_cand = [o for o in pdf_ex if _es_candidata(o, lex, max_m)]

    def fraccion(lista, indice, presentes=True):
        if not lista:
            return None, 0
        n = sum(1 for o in lista if indice.contiene(o) == presentes)
        return n / float(len(lista)), n

    rec, n_rec = fraccion(xml_ex, indice_pdf)
    ruido, n_ruido = fraccion(pdf_ex, indice_xml, presentes=False)
    c_rec, n_c_rec = fraccion(xml_cand, indice_pdf)
    c_ruido, n_c_ruido = fraccion(pdf_cand, indice_xml, presentes=False)
    return {
        "oraciones_xml": len(xml_ex), "oraciones_pdf": len(pdf_ex),
        "recuperadas": n_rec, "frac_recuperadas": _r(rec),
        "ruido": n_ruido, "frac_ruido": _r(ruido),
        "candidatas_xml": len(xml_cand), "candidatas_pdf": len(pdf_cand),
        "candidatas_recuperadas": n_c_rec,
        "frac_candidatas_recuperadas": _r(c_rec),
        "candidatas_ruido": n_c_ruido, "frac_candidatas_ruido": _r(c_ruido),
    }


def _r(x):
    return None if x is None else round(x, 4)


def percentil(valores, q):
    """Percentil con interpolación lineal (el `type 7` de R), sin numpy."""
    v = sorted(valores)
    if not v:
        return None
    pos = (len(v) - 1) * q
    i = int(pos)
    j = min(i + 1, len(v) - 1)
    return round(v[i] + (v[j] - v[i]) * (pos - i), 4)


def resumen(filas, clave):
    valores = [f[clave] for f in filas if f.get(clave) is not None]
    return {"n": len(valores), "q1": percentil(valores, 0.25),
            "mediana": percentil(valores, 0.5),
            "q3": percentil(valores, 0.75),
            "minimo": min(valores) if valores else None,
            "maximo": max(valores) if valores else None}


def pares_xml_pdf(carpeta_xml, carpeta_pdf_txt):
    """{pmid: (ruta_txt_xml, ruta_txt_pdf)} de los que tienen los dos."""
    pdf = {}
    for r in glob.glob(os.path.join(carpeta_pdf_txt, "*.txt")):
        nombre = os.path.basename(r)[:-4]
        if nombre.isdigit():
            pdf[nombre] = r
    salida = {}
    for r in sorted(glob.glob(os.path.join(carpeta_xml, "*_PMC*.txt"))):
        pmid = os.path.basename(r).split("_", 1)[0]
        if pmid in pdf and pmid not in salida:
            salida[pmid] = (r, pdf[pmid])
    return salida


def validar(carpeta_xml, carpeta_pdf_txt, pmids=None, lex=None, log=_nada):
    """El informe completo: por artículo, agregados y peores casos."""
    from grn_bronce import identificar
    if lex is None:
        lex = identificar.cargar_lexico()
    clases = _texto.cargar_clases()
    pares = pares_xml_pdf(carpeta_xml, carpeta_pdf_txt)
    if pmids:
        pares = dict((p, v) for p, v in pares.items() if p in set(pmids))
    filas = []
    for i, (pmid, (r_xml, r_pdf)) in enumerate(sorted(pares.items()), 1):
        with io.open(r_xml, encoding="utf-8") as f:
            md_xml = f.read()
        with io.open(r_pdf, encoding="utf-8") as f:
            md_pdf = f.read()
        fila = {"pmid": pmid}
        fila.update(comparar(md_xml, md_pdf, clases, lex))
        filas.append(fila)
        if i % 10 == 0:
            log("  %d de %d artículos" % (i, len(pares)))

    def total(a, b):
        sa = sum(f[a] for f in filas)
        sb = sum(f[b] for f in filas)
        return round(sa / float(sb), 4) if sb else None

    con_cand = [f for f in filas if f["candidatas_xml"]]
    peores = sorted(con_cand, key=lambda f: (f["frac_candidatas_recuperadas"],
                                             f["pmid"]))[:10]
    ruidosos = sorted((f for f in filas if f["candidatas_pdf"]),
                      key=lambda f: (-f["frac_candidatas_ruido"],
                                     f["pmid"]))[:10]
    campos_peor = ("pmid", "candidatas_xml", "frac_candidatas_recuperadas",
                   "frac_recuperadas", "frac_ruido")
    campos_ruido = ("pmid", "candidatas_pdf", "frac_candidatas_ruido",
                    "frac_ruido")
    return {
        "articulos": len(filas),
        "umbral_ratio": UMBRAL_RATIO,
        "definiciones": {
            "examinables": "oraciones de secciones que no son 'excluir', de "
                           "40 a 700 caracteres, con el segmentador del bronce",
            "candidatas": "examinables con 2 a 8 genes distintos del "
                          "diccionario (el filtro de identificar.py)",
            "recuperadas": "del XML que están en el texto examinable del PDF",
            "ruido": "del PDF que no están en ninguna parte del XML",
            "esta": "subcadena exacta del texto normalizado, o difflib ratio "
                    ">= 0.9 con 1 a 3 oraciones seguidas del otro lado",
        },
        "por_articulo": {
            "frac_recuperadas": resumen(filas, "frac_recuperadas"),
            "frac_ruido": resumen(filas, "frac_ruido"),
            "frac_candidatas_recuperadas": resumen(
                filas, "frac_candidatas_recuperadas"),
            "frac_candidatas_ruido": resumen(filas, "frac_candidatas_ruido"),
        },
        "totales": {
            "oraciones_xml": sum(f["oraciones_xml"] for f in filas),
            "oraciones_pdf": sum(f["oraciones_pdf"] for f in filas),
            "candidatas_xml": sum(f["candidatas_xml"] for f in filas),
            "candidatas_pdf": sum(f["candidatas_pdf"] for f in filas),
            "frac_recuperadas": total("recuperadas", "oraciones_xml"),
            "frac_ruido": total("ruido", "oraciones_pdf"),
            "frac_candidatas_recuperadas": total("candidatas_recuperadas",
                                                 "candidatas_xml"),
            "frac_candidatas_ruido": total("candidatas_ruido",
                                           "candidatas_pdf"),
        },
        "peores_por_candidatas_recuperadas": [
            dict((k, f[k]) for k in campos_peor) for f in peores],
        "mas_ruido_en_candidatas": [
            dict((k, f[k]) for k in campos_ruido) for f in ruidosos],
        "articulos_detalle": filas,
    }
