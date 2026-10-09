"""La capa: una tabla con la oración, sus funciones, sus operones y BioBERT.

Es lo que el usuario se comprometió a mostrar (2-oct-2026): «la capa con las
funciones biológicas, operones y la oración, para que el BioBERT lo pueda
conectar». Una fila por par que el clasificador vio: la oración y todo lo que
el bronce sabe de ella, el par marcado, a qué operones pertenece el blanco,
la predicción del modelo y, si corrió, lo que propone la sintaxis.

**Nada de esto está verificado.** La predicción es una propuesta del
clasificador, con umbrales sin calibrar; `signo_sugerido` es léxico; la
pertenencia a operones es anotación y no rasgo del paso 2 evaluado contra la
base curada mientras el asesor no conteste la decisión 3.
"""

import collections
import csv
import io
import json
import os
import re

from grn_comun import procedencia
from grn_comun.archivos import reemplazar
from grn_verificacion import puente

LOCUS = re.compile(r"^PA\d{4}")

# Los umbrales por omisión de `red.py`, los del servidor del asesor. Sin
# calibrar: moverlos cambia la exhaustividad entre 80.6 % y 93.8 %.
UMBRALES = {"activates": 0.65, "represses": 0.70, "regulates": 0.60}
SIGNO_DE_CLASE = {"activates": "+", "represses": "-", "regulates": "?",
                  "no_relation": ""}

COLUMNAS_CAPA = [
    # identidad
    "corrida_bronce", "pmid", "doi", "anio", "revista", "titulo",
    "fuente_texto", "seccion", "num_oracion", "id_par",
    # la oración y lo que el bronce sabe de ella
    "oracion", "genes", "genes_locus_tag", "proteinas",
    "operones", "hay_operon", "operones_en_oracion",
    "funciones_biologicas", "contexto_regulatorio", "evidencia_experimental",
    "organismo", "disparador", "signo_sugerido",
    "regulador_candidato", "blanco_candidato", "score",
    # el par que vio el clasificador
    "tf", "target", "tf_id", "target_id", "tf_locus", "target_locus",
    "mencion_tf", "mencion_target", "target_es_tf", "autorregulacion",
    "redaccion", "distancia", "par_del_bronce",
    # operones del par
    "blanco_es_operon", "operones_del_blanco",
    # BioBERT
    "prediccion", "p_activates", "p_no_relation", "p_regulates",
    "p_represses", "pasa_umbral", "signo_biobert", "origen_prediccion",
    # sintaxis (vacías si no corrió)
    "regulador_sintactico", "voz", "negada", "lema_dominante",
    "disparador_dominante", "signo_dominante", "direccion_sintaxis",
]

LEAME = """Capa del flujo: oración, funciones, operones y BioBERT
=====================================================

Una fila por par que vio el clasificador (`{n}` filas). Los encabezados son
los identificadores del contrato; esto explica qué dice cada grupo.

Lo que NO es: relaciones verificadas. Todo aquí es propuesta.

- Identidad: corrida del bronce, PMID, DOI, año, revista, título, fuente
  (`xml` o `abstract`), sección, número de oración e `id_par`.
- La oración y lo que el bronce sabe de ella: genes, locus, proteínas,
  operones nombrados, `hay_operon` y `operones_en_oracion` (nombrados más por
  pertenencia de sus genes a la base de operones), funciones biológicas,
  contexto regulatorio, evidencia experimental, organismo, disparador,
  `signo_sugerido` (léxico, NO verificado), regulador y blanco que orientó el
  bronce, y `score` (ordena; no es umbral).
- El par: `tf` es siempre `<e1>` (el modelo solo ve TF como regulador),
  `target` es `<e2>`; sus ids canónicos y locus tags; la redacción
  (`fenotipo_mutante` invierte el signo en el texto y el modelo no lo sabe);
  `par_del_bronce` dice si es el mismo par que orientó el bronce (`directo`),
  el contrario (`inverso`), otro, o si el bronce no orientó ninguno.
- Operones del par: si el blanco es un operón y a qué operones de la base
  pertenece. Es anotación: no se usa como rasgo del paso 2 evaluado contra la
  base curada hasta la decisión 3 del asesor.
- BioBERT (`modelo_limpio_run22`, entrenado en E. coli): la clase predicha,
  las cuatro probabilidades, si pasa el umbral de su clase (0.65 / 0.70 /
  0.60, sin calibrar), el signo que implica y si la predicción es nueva o se
  reutilizó de una corrida anterior con el mismo checkpoint y el mismo texto.
- Sintaxis (spaCy, si corrió): regulador que propone el árbol de
  dependencias, voz, negación, lema y disparador dominantes y su signo, y si
  la dirección concuerda con la del par (`concuerda`, `inversa`,
  `sin_orientar`, `sin_dato`).
"""


def _clave_oracion(pmid, fuente_texto, num_oracion):
    return (str(pmid), str(fuente_texto), str(num_oracion))


def _leer_sintaxis(ruta):
    """{(pmid, fuente, num, frozenset(a, b)): fila} del jsonl de sintaxis."""
    if not ruta or not os.path.isfile(ruta):
        return None
    indice = {}
    with io.open(ruta, encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                d = json.loads(linea)
                clave = _clave_oracion(d["pmid"], d["fuente_texto"],
                                       d["num_oracion"]) + (
                    frozenset((d["a"], d["b"])),)
                indice[clave] = d
    return indice


def es_operon(id_canonico, locus):
    """Lo que no es un locus ni un símbolo de gen del diccionario es un
    operón: del catálogo o sintético (abreviado en el texto)."""
    if not id_canonico or LOCUS.match(id_canonico):
        return False
    return not any(f in locus for f in (
        id_canonico, id_canonico[:1].lower() + id_canonico[1:],
        id_canonico[:1].upper() + id_canonico[1:]))


def direccion(sint, tf_id, target_id):
    if sint is None:
        return "sin_dato"
    reg = sint.get("regulador_sintactico") or ""
    if reg and reg == tf_id:
        return "concuerda"
    if reg and reg == target_id:
        return "inversa"
    return "sin_orientar"


def filas_capa(candidatas, pares, predicciones, nuevas, base_operones,
               locus, sintaxis=None):
    """Las filas de la capa, en el orden de `pares.jsonl`."""
    por_oracion = dict((_clave_oracion(c["pmid"], c.get("fuente_texto", ""),
                                       c["num_oracion"]), c)
                       for c in candidatas)
    salida = []
    for par in pares:
        c = por_oracion.get(_clave_oracion(par["pmid"], par["fuente_texto"],
                                           par["num_oracion"]), {})
        p = predicciones[par["id_par"]]
        clase = p["prediccion"]
        pasa = clase != "no_relation" and \
            p["p_" + clase] >= UMBRALES.get(clase, 1.1)
        if base_operones is not None and base_operones.presente:
            operones_blanco = "; ".join(
                base_operones.etiqueta(u)
                for u in base_operones.de_genes(par.get("target_locus") or []))
        else:
            operones_blanco = ""
        sint = None
        if sintaxis is not None:
            sint = sintaxis.get(_clave_oracion(
                par["pmid"], par["fuente_texto"], par["num_oracion"]) + (
                frozenset((par["tf_id"], par["target_id"])),))
        fila = collections.OrderedDict()
        fila["corrida_bronce"] = par.get("corrida_bronce", "")
        for col in ("pmid", "doi", "anio", "revista", "titulo"):
            fila[col] = c.get(col, par.get(col, ""))
        fila["fuente_texto"] = par["fuente_texto"]
        fila["seccion"] = par["seccion"]
        fila["num_oracion"] = par["num_oracion"]
        fila["id_par"] = par["id_par"]
        fila["oracion"] = par["oracion_cruda"]
        for col in ("genes", "genes_locus_tag", "proteinas", "operones",
                    "hay_operon", "operones_en_oracion",
                    "funciones_biologicas", "contexto_regulatorio",
                    "evidencia_experimental", "organismo", "disparador",
                    "signo_sugerido", "regulador_candidato",
                    "blanco_candidato", "score"):
            fila[col] = c.get(col, "")
        for col in ("tf", "target", "tf_id", "target_id"):
            fila[col] = par.get(col, "")
        fila["tf_locus"] = "|".join(par.get("tf_locus") or [])
        fila["target_locus"] = "|".join(par.get("target_locus") or [])
        fila["mencion_tf"] = par.get("mencion_tf", "")
        fila["mencion_target"] = par.get("mencion_target", "")
        fila["target_es_tf"] = "si" if par.get("target_es_tf") else "no"
        fila["autorregulacion"] = "si" if par.get("autorregulacion") else "no"
        fila["redaccion"] = par.get("redaccion", "")
        fila["distancia"] = par.get("distancia", "")
        fila["par_del_bronce"] = par.get("par_del_bronce", "")
        fila["blanco_es_operon"] = "si" if es_operon(par.get("target_id"),
                                                     locus) else "no"
        fila["operones_del_blanco"] = operones_blanco
        fila["prediccion"] = clase
        for e in puente.ETIQUETAS:
            fila["p_" + e] = p["p_" + e]
        fila["pasa_umbral"] = "si" if pasa else "no"
        fila["signo_biobert"] = SIGNO_DE_CLASE.get(clase, "")
        fila["origen_prediccion"] = ("nueva" if par["id_par"] in nuevas
                                     else "reutilizada")
        if sint is not None:
            fila["regulador_sintactico"] = sint.get("regulador_sintactico", "")
            fila["voz"] = sint.get("voz", "")
            fila["negada"] = "si" if sint.get("negada") else "no"
            fila["lema_dominante"] = sint.get("lema_dominante", "")
            fila["disparador_dominante"] = sint.get("disparador_dominante", "")
            fila["signo_dominante"] = sint.get("signo_dominante", "")
        else:
            for col in ("regulador_sintactico", "voz", "negada",
                        "lema_dominante", "disparador_dominante",
                        "signo_dominante"):
                fila[col] = ""
        fila["direccion_sintaxis"] = (direccion(sint, par["tf_id"],
                                                par["target_id"])
                                      if sintaxis is not None else "")
        salida.append(fila)
    return salida


def resumen_capa(filas, sintaxis, ruta_sintaxis, base_operones,
                 huella_base):
    cuenta = collections.Counter
    resumen = {
        "filas": len(filas),
        "oraciones": len(set((f["pmid"], f["fuente_texto"], f["num_oracion"])
                             for f in filas)),
        "articulos": len(set(f["pmid"] for f in filas)),
        "por_prediccion": dict(cuenta(f["prediccion"] for f in filas)),
        "pasan_umbral": sum(1 for f in filas if f["pasa_umbral"] == "si"),
        "pasan_umbral_por_signo": dict(cuenta(
            f["signo_biobert"] or "sin" for f in filas
            if f["pasa_umbral"] == "si")),
        "por_seccion": dict(cuenta(f["seccion"] for f in filas)),
        "origen_prediccion": dict(cuenta(f["origen_prediccion"]
                                         for f in filas)),
        "par_del_bronce": dict(cuenta(f["par_del_bronce"] for f in filas)),
        "redaccion_fenotipo_mutante": sum(
            1 for f in filas if f["redaccion"] == "fenotipo_mutante"),
        "operones": {
            "base_presente": bool(base_operones is not None
                                  and base_operones.presente),
            "huella_operones_base": huella_base,
            "oraciones_con_operon": len(set(
                (f["pmid"], f["fuente_texto"], f["num_oracion"])
                for f in filas if f["hay_operon"] == "si")),
            "pares_con_blanco_en_operon": sum(
                1 for f in filas if f["operones_del_blanco"]),
            "pares_con_blanco_operon": sum(
                1 for f in filas if f["blanco_es_operon"] == "si"),
        },
        "umbrales": UMBRALES,
    }
    if sintaxis is None:
        resumen["sintaxis"] = {"presente": False}
    else:
        reguladores_no_tf = 0
        with io.open(ruta_sintaxis, encoding="utf-8") as f:
            for linea in f:
                if not linea.strip():
                    continue
                d = json.loads(linea)
                reg = d.get("regulador_sintactico") or ""
                if reg and not (d.get("a_es_tf") if reg == d.get("a")
                                else d.get("b_es_tf")):
                    reguladores_no_tf += 1
        resumen["sintaxis"] = {
            "presente": True,
            "direccion": dict(cuenta(f["direccion_sintaxis"] for f in filas)),
            "voz": dict(cuenta(f["voz"] or "sin_dato" for f in filas)),
            # Pares que la sintaxis orienta con un regulador que no es TF:
            # el clasificador nunca los ve, porque solo marca TF como <e1>.
            "pares_con_regulador_no_tf": reguladores_no_tf,
            "huella_sintaxis": procedencia.huella(ruta_sintaxis),
        }
    return resumen


def escribir_csv(ruta, filas):
    """UTF-8 con BOM, para que Excel lea los acentos al abrirlo con doble
    clic. Escritura atómica: un CSV a medias no se confunde con uno entero."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNAS_CAPA)
        for fila in filas:
            w.writerow([fila.get(c, "") for c in COLUMNAS_CAPA])
    reemplazar(tmp, ruta)


def escribir_capa(carpeta, ruta_bronce, ruta_sintaxis=None, log=lambda m: None):
    from grn_bronce import identificar, operones
    log("Armando la capa...")
    pares_ruta = os.path.join(carpeta, "pares.jsonl")
    # La unión de abajo es por `id_par`, que no depende del texto marcado. Con
    # un `--pasos pares,capa` que se saltara biobert, un re-marcado del mismo
    # par se llevaba la predicción del texto viejo sin que nada avisara.
    with io.open(os.path.join(carpeta, "predicciones_meta.json"),
                 encoding="utf-8") as f:
        meta = json.load(f)
    if meta.get("huella_pares") != procedencia.huella(pares_ruta):
        raise ValueError("predicciones.jsonl no se hizo con este pares.jsonl: "
                         "corre antes el paso biobert.")
    candidatas = puente.leer_candidatas(ruta_bronce)
    pares = puente.leer_jsonl(pares_ruta)
    predicciones = dict((p["id_par"], p) for p in puente.leer_jsonl(
        os.path.join(carpeta, "predicciones.jsonl")))
    origen = os.path.join(carpeta, "predicciones_origen.json")
    nuevas = set()
    if os.path.isfile(origen):
        with io.open(origen, encoding="utf-8") as f:
            nuevas = set(json.load(f).get("nuevas", []))
    base = operones.BaseOperones.cargar(operones.RUTA_BASE)
    locus = identificar.cargar_locus_tags()
    sintaxis = _leer_sintaxis(ruta_sintaxis)
    filas = filas_capa(candidatas, pares, predicciones, nuevas, base, locus,
                       sintaxis)
    escribir_csv(os.path.join(carpeta, "capa_pares.csv"), filas)
    resumen = resumen_capa(filas, sintaxis, ruta_sintaxis, base,
                           procedencia.huella_texto(operones.RUTA_BASE))
    puente.escribir_json(os.path.join(carpeta, "capa_resumen.json"), resumen)
    with io.open(os.path.join(carpeta, "capa_leame.txt"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write(LEAME.format(n=len(filas)))
    log("  %d filas en %d oraciones de %d artículos; pasan el umbral %d."
        % (resumen["filas"], resumen["oraciones"], resumen["articulos"],
           resumen["pasan_umbral"]))
    if not resumen["operones"]["base_presente"]:
        log("  AVISO: falta operones_base.tsv; `operones_del_blanco` va vacía.")
    return resumen
