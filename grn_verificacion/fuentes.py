# -*- coding: utf-8 -*-
"""De qué parte del texto sale la evidencia: el resumen o el cuerpo del artículo.

    python -m grn_verificacion.cli fuentes --carpeta salidas/flujo/corrida20_run22 \\
        [--json J]

Responde, con conteos, qué aporta el texto completo frente al resumen. Cada
oración tiene un **origen**:

- `resumen`: está en la sección `abstract`, sea de un artículo del que solo
  hay resumen o de uno con texto completo;
- `cuerpo_xml`: cualquier otra sección de un artículo con XML de PMC;
- `cuerpo_pdf`: cualquier otra sección de un artículo cuyo texto sale del PDF.

Lo que cuenta
=============
- **Embudo por origen**: artículos con alguna oración candidata, oraciones
  candidatas (el CSV del bronce), pares que clasifica el BioBERT y pares
  sobre el umbral (`capa_pares.csv`).
- **Aristas por el origen de su evidencia** (`red_evidencias.tsv`):
  `solo_resumen`, `resumen_y_cuerpo` o `solo_cuerpo`. Con el juicio del
  jurado (`red_juez.tsv`), el nivel de confianza de cada clase.
- **En los artículos con texto completo**: cuántas aristas sostiene su
  resumen y cuántas su cuerpo, y cuántas están solo en el cuerpo. Es la
  comparación sobre los mismos artículos.
- **El jurado por origen** (`red_evidencias_juez.tsv`): de las oraciones que
  juzgó, cuántas confirma, invierte, deja dudosas o rechaza. El jurado lee
  la oración de mayor probabilidad de cada arista, no una muestra al azar:
  es una comparación entre orígenes, no la precisión de cada uno.

Solo conteos: ni oraciones ni PMIDs. La precisión contra el experto por
origen la da `precision-ciega` (`por_origen`), con esta misma definición.
"""
import collections
import csv
import glob
import io
import json
import os

from grn_comun import redes

ORIGENES = ("resumen", "cuerpo_xml", "cuerpo_pdf")
SIN_DATO = "sin_dato"
CLASES_ARISTA = ("solo_resumen", "resumen_y_cuerpo", "solo_cuerpo")
VEREDICTOS = ("confirma", "invierte", "dudosa", "rechaza", "abstiene")
NIVELES = ("alta", "media", "al_reves", "sin_respaldo")
SUFIJO_CANDIDATAS = "_oraciones_candidatas.csv"
CAPA = "capa_pares.csv"
RED_JUEZ = "red_juez.tsv"
EVIDENCIAS_JUEZ = "red_evidencias_juez.tsv"
# La fuente de un artículo del que solo hay resumen: así la llaman la capa
# (`fuente_texto`) y las evidencias de la red (`fuente`).
SOLO_RESUMEN = ("abstract", "resumen")


class ErrorFuentes(ValueError):
    pass


def _nada(_mensaje):
    pass


def origen_del_texto(fuente, seccion):
    """`resumen`, `cuerpo_xml` o `cuerpo_pdf`; `sin_dato` si no hay con qué."""
    fuente = (fuente or "").strip().lower()
    seccion = (seccion or "").strip().lower()
    if not fuente and not seccion:
        return SIN_DATO
    if seccion == "abstract" or fuente in SOLO_RESUMEN:
        return "resumen"
    return "cuerpo_pdf" if fuente == "pdf" else "cuerpo_xml"


def _filas(ruta, delimitador=","):
    csv.field_size_limit(2 ** 31 - 1)
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f, delimiter=delimitador):
            yield fila


def csv_candidatas(carpeta):
    """El CSV de oraciones candidatas de la carpeta: el que `flujo.py` anotó
    en `estado.json` o, sin estado, el más reciente."""
    nombre = None
    try:
        with io.open(os.path.join(carpeta, "estado.json"),
                     encoding="utf-8") as f:
            nombre = (json.load(f).get("archivos") or {}).get("candidatas")
    except (OSError, ValueError, AttributeError):
        pass
    if nombre and os.path.basename(nombre) == nombre and \
            os.path.isfile(os.path.join(carpeta, nombre)):
        return os.path.join(carpeta, nombre)
    hallados = sorted(glob.glob(os.path.join(
        glob.escape(carpeta), "bronce_identificacion_*" + SUFIJO_CANDIDATAS)),
        key=os.path.getmtime)
    if not hallados:
        raise ErrorFuentes("La carpeta no tiene el CSV de oraciones "
                           "candidatas del bronce.")
    return hallados[-1]


def embudo(ruta_candidatas, ruta_capa):
    """Por origen: artículos, oraciones candidatas, pares y pares sobre el
    umbral. `articulos_por_fuente` cuenta cada artículo una vez, por la
    fuente de su texto."""
    filas = dict((o, {"articulos": set(), "oraciones_candidatas": 0,
                      "pares": 0, "pares_sobre_umbral": 0})
                 for o in ORIGENES + (SIN_DATO,))
    fuente_de = {}
    for f in _filas(ruta_candidatas):
        o = origen_del_texto(f.get("fuente_texto"), f.get("seccion"))
        filas[o]["articulos"].add(f.get("pmid"))
        filas[o]["oraciones_candidatas"] += 1
        fuente_de[f.get("pmid")] = (f.get("fuente_texto") or "").strip()
    for f in _filas(ruta_capa):
        o = origen_del_texto(f.get("fuente_texto"), f.get("seccion"))
        filas[o]["pares"] += 1
        filas[o]["pares_sobre_umbral"] += f.get("pasa_umbral") == "si"
    por_origen = collections.OrderedDict()
    for o in ORIGENES + (SIN_DATO,):
        if filas[o]["oraciones_candidatas"] or filas[o]["pares"]:
            por_origen[o] = dict(filas[o], articulos=len(filas[o]["articulos"]))
    return {"por_origen": por_origen,
            "articulos_por_fuente": dict(sorted(collections.Counter(
                fuente_de.values()).items())),
            "articulos_con_candidatas": len(fuente_de)}


def _clase(origenes):
    if "resumen" not in origenes:
        return "solo_cuerpo"
    return "solo_resumen" if origenes == {"resumen"} else "resumen_y_cuerpo"


def _niveles(aristas, nivel):
    cuenta = collections.Counter(nivel.get(a, "") for a in aristas)
    return dict((n, cuenta[n]) for n in NIVELES)


def aristas_por_origen(ruta_evidencias, ruta_red_juez=None):
    """Las aristas según de dónde sale su evidencia, y la comparación sobre
    los artículos con texto completo. Con `ruta_red_juez`, el nivel de
    confianza de cada grupo."""
    todas = collections.defaultdict(set)
    con_texto = collections.defaultdict(set)
    for e in _filas(ruta_evidencias, "\t"):
        arista = (e["tf"], e["blanco"])
        o = origen_del_texto(e.get("fuente"), e.get("seccion"))
        todas[arista].add(o)
        if (e.get("fuente") or "").strip().lower() not in SOLO_RESUMEN:
            con_texto[arista].add("resumen" if o == "resumen" else "cuerpo")
    nivel = None
    if ruta_red_juez and os.path.isfile(ruta_red_juez):
        nivel = dict(((a["tf"], a["blanco"]), a.get("nivel") or "")
                     for a in _filas(ruta_red_juez, "\t"))
        if not any(nivel.values()):
            nivel = None

    def grupo(aristas):
        g = {"aristas": len(aristas)}
        if nivel is not None:
            g["nivel"] = _niveles(aristas, nivel)
        return g

    clases = collections.defaultdict(list)
    for arista, origenes in todas.items():
        clases[_clase(origenes)].append(arista)
    resumen = [a for a, o in con_texto.items() if "resumen" in o]
    cuerpo = [a for a, o in con_texto.items() if "cuerpo" in o]
    return {
        "aristas": len(todas),
        "por_clase": collections.OrderedDict(
            (c, grupo(clases[c])) for c in CLASES_ARISTA),
        "con_evidencia_en": collections.OrderedDict(
            (o, grupo([a for a, os_ in todas.items() if o in os_]))
            for o in ORIGENES),
        "articulos_con_texto_completo": collections.OrderedDict([
            ("aristas", len(con_texto)),
            ("en_su_resumen", grupo(resumen)),
            ("en_su_cuerpo", grupo(cuerpo)),
            ("solo_en_su_cuerpo", grupo(
                [a for a in cuerpo if "resumen" not in con_texto[a]])),
            ("solo_en_su_resumen", grupo(
                [a for a in resumen if "cuerpo" not in con_texto[a]])),
        ]),
    }


def jurado_por_origen(ruta_evidencias_juez):
    """De las oraciones que juzgó el jurado, el veredicto por origen."""
    cuenta = collections.Counter()
    unanimes = collections.Counter()
    votos = []
    for e in _filas(ruta_evidencias_juez, "\t"):
        v = (e.get("veredicto_agente") or "").strip()
        if not v:
            continue
        o = origen_del_texto(e.get("fuente"), e.get("seccion"))
        cuenta[(o, v)] += 1
        if v == "confirma" and (e.get("votos_si") or "").isdigit():
            votos.append((o, int(e["votos_si"])))
    jueces = max([n for _o, n in votos] or [0])
    for o, n in votos:
        unanimes[o] += n == jueces
    salida = collections.OrderedDict()
    for o in ORIGENES + (SIN_DATO,):
        n = sum(cuenta[(o, v)] for v in VEREDICTOS)
        if n:
            salida[o] = dict(((v, cuenta[(o, v)]) for v in VEREDICTOS),
                             juzgadas=n, confirma_unanime=unanimes[o])
    return salida


def calcular(carpeta, red=None):
    if not os.path.isdir(carpeta):
        raise ErrorFuentes("No encuentro la carpeta de --carpeta.")
    _red, evidencias, _ = redes.archivos_de_red(red)
    ruta_capa = os.path.join(carpeta, CAPA)
    ruta_evidencias = os.path.join(carpeta, evidencias)
    for ruta, que in ((ruta_capa, CAPA), (ruta_evidencias, evidencias)):
        if not os.path.isfile(ruta):
            raise ErrorFuentes("Falta %s en la carpeta." % que)
    con_juez = red is None
    resultado = collections.OrderedDict([
        ("metodo", "fuentes"),
        ("evidencias", evidencias),
        ("embudo", embudo(csv_candidatas(carpeta), ruta_capa)),
        ("aristas", aristas_por_origen(
            ruta_evidencias,
            os.path.join(carpeta, RED_JUEZ) if con_juez else None)),
    ])
    ruta_juez = os.path.join(carpeta, EVIDENCIAS_JUEZ)
    resultado["jurado"] = (jurado_por_origen(ruta_juez)
                           if con_juez and os.path.isfile(ruta_juez) else None)
    return resultado


def _pct(k, n):
    return "%d de %d (%.1f %%)" % (k, n, 100.0 * k / n) if n else "0 de 0"


def lineas(r):
    """Lo que ve quien corre esto: solo cifras."""
    salida = ["Embudo por origen del texto:"]
    for o, f in r["embudo"]["por_origen"].items():
        salida.append(
            "  %-11s artículos %d; oraciones candidatas %d; pares %d; sobre "
            "el umbral %s" % (o, f["articulos"], f["oraciones_candidatas"],
                              f["pares"], _pct(f["pares_sobre_umbral"],
                                               f["pares"])))
    a = r["aristas"]
    salida.append("Aristas: %d. Por el origen de su evidencia: %s." % (
        a["aristas"], ", ".join("%s %d" % (c, g["aristas"])
                                for c, g in a["por_clase"].items())))
    for c, g in a["por_clase"].items():
        if "nivel" in g:
            salida.append("  %s: %s" % (c, ", ".join(
                "%s %s" % (n, _pct(g["nivel"][n], g["aristas"]))
                for n in NIVELES)))
    t = a["articulos_con_texto_completo"]
    salida.append(
        "En los artículos con texto completo: su resumen sostiene %d "
        "aristas y su cuerpo %d; solo en el cuerpo, %d; solo en el resumen, "
        "%d." % (t["en_su_resumen"]["aristas"], t["en_su_cuerpo"]["aristas"],
                 t["solo_en_su_cuerpo"]["aristas"],
                 t["solo_en_su_resumen"]["aristas"]))
    if r["jurado"]:
        salida.append("El jurado, por origen de la oración que juzgó:")
        for o, j in r["jurado"].items():
            salida.append("  %-11s juzgadas %d: confirma %s (unánime %d), "
                          "invierte %d, dudosa %d, rechaza %d, abstiene %d"
                          % (o, j["juzgadas"],
                             _pct(j["confirma"], j["juzgadas"]),
                             j["confirma_unanime"], j["invierte"],
                             j["dudosa"], j["rechaza"], j["abstiene"]))
    else:
        salida.append("Sin juicio del jurado en la carpeta.")
    return salida


def ejecutar(carpeta, red=None, ruta_json=None, log=_nada):
    resultado = calcular(carpeta, red)
    if ruta_json:
        with io.open(ruta_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=1)
            f.write("\n")
    for linea in lineas(resultado):
        log(linea)
    return resultado
