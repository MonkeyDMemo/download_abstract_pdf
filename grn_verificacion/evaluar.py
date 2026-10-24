"""El 44 % recalculado con el BioBERT conectado (PLAN.md:22).

El asesor aceptó el 44.0 % (22 de 50, la precisión del bronce juzgada a mano
el 11-sep) como línea base de un sistema sin entrenar, con el acuerdo de
recalcularlo al conectar el clasificador. Esto lo recalcula sobre las MISMAS
50 oraciones, con las reglas de `etapa2/unir_juicios.py`: los `dudoso` van al
denominador y nunca al numerador.

**Las métricas se fijaron antes de correr** (plan del 8-oct). No se ajusta
ningún umbral mirando estas 50: con n = 50 el intervalo es de unos ±14
puntos, y cualquier umbral elegido aquí mediría la elección, no el modelo.
Siempre se reporta la retención junto a la precisión: subir la precisión
tirando las relaciones buenas no es mejorar.

Las 50 se miraron al revisar el punto 30, así que para la sintaxis son
desarrollo, no prueba.

**Con `particion`** (la carpeta de los `entity_marked_*.jsonl` del modelo), el
P1 se separa en los juicios cuyo par el modelo vio al entrenar (en train o en
dev) y los que no: ver `por_par_visto`. Solo conteos.
"""

import collections
import csv
import io
import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ETAPA2 = os.path.join(_RAIZ, "etapa2")
if _ETAPA2 not in sys.path:
    sys.path.insert(0, _ETAPA2)

from grn_bronce.texto import normalizar_espacios   # noqa: E402
from grn_comun import signo_lexico                 # noqa: E402
from grn_verificacion import capa as _capa, puente  # noqa: E402
from grn_verificacion import entrenamiento          # noqa: E402

RUTA_JUICIOS = os.path.join(_RAIZ, "etapa2", "evaluacion",
                            "juicio_consolidado.csv")

# Líneas del CSV, con el encabezado como línea 1, como las cita
# `etapa2/evaluacion/criterios_juicio.md`.
INVERTIDAS = (8, 11, 20, 41, 44, 50)
# De las seis, 44 y 50 son proteína-proteína (FleN–FleQ): bien orientadas
# siguen siendo `no`. El techo realista de una corrección de dirección es 4.
RECUPERABLES = (8, 11, 20, 41)
DISCUTIBLES = (14, 27)

LINEA_BASE = {"si": 22, "n": 50}
MINIMO_UNIDAS = 45


class ErrorEvaluacion(RuntimeError):
    pass


def _nada(_m):
    pass


def wilson(k, n):
    """Intervalo de Wilson al 95 %, el mismo de `etapa2/muestrear_precision`."""
    from muestrear_precision import wilson as _w
    return _w(k, n)


def proporcion(k, n):
    if n == 0:
        return {"k": k, "n": n, "valor": None, "ic95": None}
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "valor": round(k / n, 4),
            "ic95": [round(lo, 4), round(hi, 4)]}


def leer_juicios(ruta=RUTA_JUICIOS):
    """Las 50 filas juzgadas, con su línea del CSV."""
    with io.open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    for i, fila in enumerate(filas):
        fila["_linea"] = i + 2
    return filas


def _clave(pmid, oracion, regulador, blanco):
    return (str(pmid), normalizar_espacios(oracion), regulador, blanco)


def unir(juicios, filas_capa):
    """{línea: fila de la capa del par juzgado} y las líneas sin unir.

    El par juzgado es el que orientó el bronce (regulador → blanco), y el
    regulador del bronce siempre es un TF, así que es el par que el
    clasificador vio con el regulador como `<e1>`.
    """
    por_clave = {}
    for f in filas_capa:
        por_clave.setdefault(_clave(f["pmid"], f["oracion"], f["tf_id"],
                                    f["target_id"]), f)
    unidas, sin_unir = {}, []
    for j in juicios:
        f = por_clave.get(_clave(j["pmid"], j["oracion"], j["regulador"],
                                 j["blanco"]))
        if f is None:
            sin_unir.append(j["_linea"])
        else:
            unidas[j["_linea"]] = f
    return unidas, sin_unir


def precision(juicios, retenida, relacion=None):
    """`si / (si + no + dudoso)` sobre las filas retenidas.

    `relacion` permite cambiar el juicio de algunas líneas (sensibilidad).
    """
    k = n = 0
    for j in juicios:
        if not retenida(j):
            continue
        rel = (relacion or {}).get(j["_linea"], j["relacion"])
        if rel not in ("si", "no", "dudoso"):
            continue
        n += 1
        k += rel == "si"
    return proporcion(k, n)


def _pasa_umbral(unidas, j):
    f = unidas.get(j["_linea"])
    return f is not None and f["pasa_umbral"] == "si"


def evaluar(juicios, unidas, sintaxis_presente=False):
    """Las métricas fijadas el 8-oct. Devuelve un dict serializable."""
    rel = collections.Counter(j["relacion"] for j in juicios)
    if rel["si"] != LINEA_BASE["si"] or len(juicios) != LINEA_BASE["n"]:
        raise ErrorEvaluacion(
            "La muestra juzgada no reproduce el 44.0 %% (%d de %d): el "
            "archivo de juicios cambió y esta comparación ya no es la del "
            "11-sep." % (rel["si"], len(juicios)))

    def pasa(j):
        return _pasa_umbral(unidas, j)

    def relacion_biobert(j):
        f = unidas.get(j["_linea"])
        return f is not None and f["prediccion"] != "no_relation"

    si = [j for j in juicios if j["relacion"] == "si"]
    no = [j for j in juicios if j["relacion"] == "no"]
    invertidas = [j for j in juicios if j["_linea"] in INVERTIDAS]

    resultado = collections.OrderedDict()
    resultado["muestra"] = {"n": len(juicios), "unidas": len(unidas),
                            "si": rel["si"], "no": rel["no"],
                            "dudoso": rel["dudoso"]}
    resultado["P0_bronce"] = precision(juicios, lambda j: True)
    resultado["P1_bronce_y_biobert_con_umbral"] = precision(juicios, pasa)
    resultado["P1_bronce_y_biobert_sin_umbral"] = precision(juicios,
                                                            relacion_biobert)
    resultado["R1_retencion_de_las_si"] = proporcion(
        sum(1 for j in si if pasa(j)), len(si))
    resultado["R1_retencion_sin_umbral"] = proporcion(
        sum(1 for j in si if relacion_biobert(j)), len(si))
    resultado["E1_no_descartadas"] = proporcion(
        sum(1 for j in no if not pasa(j)), len(no))
    resultado["E1_invertidas_descartadas"] = proporcion(
        sum(1 for j in invertidas if not pasa(j)), len(invertidas))

    # Signo, la primera medición sobre P. aeruginosa con relaciones juzgadas.
    # Solo las `si` con signo claro; `regulates` no afirma signo y cuenta como
    # no cubierta. La línea base es «siempre +», y cada acierto va contra la
    # suya sobre los mismos ítems: el 9/12 de la v2 se comparaba con un 73.3 %
    # de todas las `si` con signo claro, que no es k/12.
    con_signo = [j for j in si if j["signo_correcto"] in ("+", "-")]
    cubiertas = acertadas = positivos_cubiertas = 0
    cubiertas_umbral = acertadas_umbral = 0
    lexico_cubiertas = lexico_acertadas = 0
    for j in con_signo:
        f = unidas.get(j["_linea"])
        if f is None:
            continue
        s = _capa.SIGNO_DE_CLASE.get(f["prediccion"], "")
        if s in ("+", "-"):
            cubiertas += 1
            acertadas += s == j["signo_correcto"]
            positivos_cubiertas += j["signo_correcto"] == "+"
            if f["pasa_umbral"] == "si":
                cubiertas_umbral += 1
                acertadas_umbral += s == j["signo_correcto"]
        lexico = set(x for x in (f.get("signo_sugerido") or "").split(";")
                     if x)
        if lexico in ({"+"}, {"-"}):
            lexico_cubiertas += 1
            lexico_acertadas += lexico == {j["signo_correcto"]}
    positivos = sum(1 for j in con_signo if j["signo_correcto"] == "+")
    resultado["S1_signo"] = {
        "filas_con_signo_claro": len(con_signo),
        "biobert": {"cubiertas": cubiertas,
                    "acierto": proporcion(acertadas, cubiertas)},
        # Las dos lecturas, cada una con su «siempre +»: cuando BioBERT da
        # signo, y con la abstención como error sobre todas las de signo
        # claro (cuya línea base es `linea_base_siempre_mas`).
        "linea_base_siempre_mas_cubiertas": proporcion(positivos_cubiertas,
                                                       cubiertas),
        "biobert_abstencion_es_error": proporcion(acertadas, len(con_signo)),
        "biobert_con_umbral": {"cubiertas": cubiertas_umbral,
                               "acierto": proporcion(acertadas_umbral,
                                                     cubiertas_umbral)},
        "bronce_lexico": {"cubiertas": lexico_cubiertas,
                          "acierto": proporcion(lexico_acertadas,
                                                lexico_cubiertas)},
        "linea_base_siempre_mas": proporcion(positivos, len(con_signo)),
    }

    a_no = dict((l, "no") for l in DISCUTIBLES)
    resultado["sensibilidad_14_y_27_a_no"] = {
        "P0": precision(juicios, lambda j: True, a_no),
        "P1_con_umbral": precision(juicios, pasa, a_no),
    }

    if sintaxis_presente:
        def dir_(linea):
            f = unidas.get(linea)
            return f["direccion_sintaxis"] if f is not None else "sin_dato"
        corregidas = [l for l in INVERTIDAS if dir_(l) == "inversa"]
        rotas = [j["_linea"] for j in si if dir_(j["_linea"]) == "inversa"]
        concuerdan = [j["_linea"] for j in si
                      if dir_(j["_linea"]) == "concuerda"]
        recuperadas = [l for l in RECUPERABLES if l in corregidas]
        resultado["D_direccion_sintaxis"] = {
            "D1_corregidas_de_las_4_recuperables": proporcion(
                len(recuperadas), len(RECUPERABLES)),
            "D1_corregidas_de_las_6": proporcion(len(corregidas),
                                                 len(INVERTIDAS)),
            "lineas_corregidas": corregidas,
            "D2_si_que_concuerdan": proporcion(len(concuerdan), len(si)),
            "D2_si_que_se_romperian": proporcion(len(rotas), len(si)),
            "lineas_rotas": rotas,
            "precision_si_se_reorientara_simulada": proporcion(
                rel["si"] - len(rotas) + len(recuperadas), len(juicios)),
            "criterio_para_reorientar": "≥ 3 de 4 y 0 rotas",
            "cumple_criterio": len(recuperadas) >= 3 and not rotas,
            "nota": "Desarrollo, no prueba: estas 50 ya se miraron al "
                    "revisar el punto 30.",
        }
    resultado["notas"] = [
        "Mismas 50 oraciones y reglas de unir_juicios.py: dudoso al "
        "denominador, nunca al numerador.",
        "Umbrales 0.65/0.70/0.60 del servidor del asesor, sin calibrar; "
        "no se ajustan con esta muestra.",
        "n = 50: intervalos de Wilson al 95 %, anchos. Precisión siempre "
        "junto a retención.",
        "BioBERT entrenado en E. coli; el signo por oración es su punto "
        "débil (fenotipo del mutante).",
    ]
    return resultado


# ------------------------------------------------- lo que el modelo ya vio

def clave_par(tf, target):
    """El par dirigido (regulador, blanco), cada nombre en la forma canónica
    de `entrenamiento.canonico`: minúsculas y sin puntuación.

    Así LasR y lasR, o mexEF-oprN y «mexEF oprN», son el mismo nombre (gen y
    proteína son la misma entidad). Dirigido, como lo mide
    `etapa2/particionar.py` (`(tf, target)` en minúsculas): el modelo lee el
    regulador como `<e1>`, y el par al revés es otra entrada con otra
    etiqueta.
    """
    return (entrenamiento.canonico(tf or ""),
            entrenamiento.canonico(target or ""))


def leer_particion(carpeta):
    """Lo que el modelo vio al entrenar: train y dev, que elige la época; test
    no. Devuelve {'ejemplos': n, 'pares': set, 'pmids': set, 'textos': set}.

    Se lee como en `verificar` (I3): línea por línea, y un error dice el
    archivo y la línea, nunca la ruta ni el contenido, que deriva de la base
    curada. El par está explícito en cada ejemplo: `tf` y `target`, los
    campos que `particionar.py` exige y con los que mide la fuga por par.

    `~` se expande, como en `precision-ciega --particion`: desde una variable
    entre comillas simples llega sin expandir, y la misma ruta que allá
    funciona aquí decía que faltaba train.
    """
    carpeta = os.path.expanduser(carpeta)
    vista = {"ejemplos": 0, "pares": set(), "pmids": set(), "textos": set()}
    for nombre in entrenamiento.ARCHIVOS[:2]:
        ruta = os.path.join(carpeta, nombre)
        if not os.path.isfile(ruta):
            raise ErrorEvaluacion("Falta %s en la carpeta de --particion."
                                  % nombre)
        try:
            f = io.open(ruta, encoding="utf-8")
        except OSError:
            # Su str lleva la ruta, que en el servidor es la de la cuenta.
            raise ErrorEvaluacion("No pude leer %s de --particion." % nombre) \
                from None
        with f:
            for numero, linea in enumerate(f, 1):
                if not linea.strip():
                    continue
                try:
                    e = json.loads(linea)
                except ValueError:
                    raise ErrorEvaluacion("%s, línea %d ilegible."
                                          % (nombre, numero))
                if not isinstance(e, dict) or not all(
                        isinstance(e.get(c), str)
                        for c in ("text", "tf", "target")):
                    raise ErrorEvaluacion("%s, línea %d sin text, tf o "
                                          "target." % (nombre, numero))
                vista["ejemplos"] += 1
                vista["pares"].add(clave_par(e["tf"], e["target"]))
                vista["textos"].add(entrenamiento.canonico(e["text"]))
                pmid = entrenamiento.pmid_valido(e.get("pmid"))
                if pmid:
                    vista["pmids"].add(pmid)
    return vista


def por_par_visto(juicios, unidas, vista):
    """El P1 de las 50, separado por si el modelo vio su par al entrenar.

    Las 50 estaban reservadas: sus PMIDs y sus oraciones no entran al
    entrenamiento, así que lo que el modelo pudo memorizar de ellas es el par
    («LasR → lasB es activates», aprendido en otro artículo). Si el P1 de los
    pares vistos le gana al de los no vistos, parte de la cifra es memoria.
    El P0 con el mismo corte es el control: si para el bronce los pares
    vistos también son más ciertos, la diferencia es de los pares (los
    conocidos son los fáciles) y no del modelo. Que las 50 de verdad no estén
    en train ni dev se comprueba aquí mismo, por PMID y por texto canónico.

    El par de un juicio es el que leyó el modelo: `tf` y `target` de su fila
    de la capa, la forma de presentación de los ejemplos; sin esas columnas,
    el regulador y el blanco del juicio (ids canónicos del bronce), que con
    `clave_par` dan el mismo nombre. Solo conteos.
    """
    def visto(j):
        f = unidas.get(j["_linea"]) or {}
        return clave_par(f.get("tf") or j.get("regulador"),
                         f.get("target") or j.get("blanco")) in vista["pares"]

    def pasa(j):
        return _pasa_umbral(unidas, j)

    resultado = collections.OrderedDict()
    resultado["ejemplos_train_dev"] = vista["ejemplos"]
    resultado["criterio"] = ("par dirigido (tf, target) de los ejemplos de "
                             "train y dev, cada nombre en la forma canónica "
                             "de entrenamiento.canonico")
    resultado["juzgadas_con_par_visto"] = proporcion(
        sum(1 for j in juicios if visto(j)), len(juicios))
    resultado["P1_par_visto"] = precision(
        juicios, lambda j: pasa(j) and visto(j))
    resultado["P1_par_no_visto"] = precision(
        juicios, lambda j: pasa(j) and not visto(j))
    resultado["P0_par_visto"] = precision(juicios, visto)
    resultado["P0_par_no_visto"] = precision(juicios, lambda j: not visto(j))
    resultado["juzgadas_con_pmid_en_train_dev"] = sum(
        1 for j in juicios
        if entrenamiento.pmid_valido(j.get("pmid")) in vista["pmids"])
    resultado["juzgadas_con_texto_en_train_dev"] = sum(
        1 for j in juicios
        if entrenamiento.canonico(j.get("oracion") or "") in vista["textos"])
    return resultado


def _categoria(signos):
    signos = set(s for s in signos if s)
    con_signo = signos & {"+", "-"}
    if len(con_signo) == 2:
        return "contradictorio"
    if len(con_signo) == 1:
        return "mezcla" if "?" in signos else "unico"
    return "solo_interrogacion" if signos else "sin_disparador"


def disparador_dominante(filas_capa, vocab):
    """Punto 18 sobre los pares dirigidos del bronce (`par_del_bronce` =
    `directo`), con tres reglas para el signo de cada oración:

    - `bronce`: la unión de todos los disparadores de la oración (lo de hoy);
    - `control_lexico`: el disparador con signo más cercano al tramo entre las
      dos menciones, solo biblioteca estándar;
    - `sintaxis`: el signo del disparador dominante en el árbol, si corrió.

    Cada par agrega sus oraciones y queda en una categoría: `unico`,
    `mezcla`, `contradictorio` o `solo_interrogacion`. El techo es la suma
    de los pares con algún disparador con signo.
    """
    por_par = collections.defaultdict(lambda: {"bronce": [], "lexico": [],
                                               "sintaxis": []})
    for f in filas_capa:
        if f["par_del_bronce"] != "directo":
            continue
        par = por_par[(f["tf_id"], f["target_id"])]
        par["bronce"].extend((f.get("signo_sugerido") or "").split(";"))
        par["lexico"].append(_signo_cercano(f, vocab))
        par["sintaxis"].append(f.get("signo_dominante") or "")
    salida = {"pares_dirigidos": len(por_par)}
    for regla in ("bronce", "lexico", "sintaxis"):
        salida[regla] = dict(collections.Counter(
            _categoria(v[regla]) for v in por_par.values()))
    salida["techo"] = sum(1 for v in por_par.values()
                          if set(v["bronce"]) & {"+", "-"})
    return salida


def _signo_cercano(fila, vocab):
    """El signo del disparador con signo (+ o -) más cercano al tramo entre
    las dos menciones de una fila de la capa, o "" si no tiene ninguno.

    El algoritmo vive en `grn_comun/signo_lexico.py` desde el 23-oct-2026,
    sin cambios: la red lo puede usar como voto (`grn_red/signo.py`), y con
    una copia aquí y otra allá lo que mide el punto 18 y lo que vota en la
    red podían dejar de ser la misma regla.
    """
    return signo_lexico.signo_cercano(fila["oracion"], fila["mencion_tf"],
                                      fila["mencion_target"], vocab)


def evaluar_carpeta(carpeta, ruta_bronce=None, log=_nada, particion=None):
    """Escribe `evaluacion.json` en la carpeta del flujo. Con `particion`,
    además `P1_por_par_visto` (ver `por_par_visto`)."""
    from grn_bronce import vocabulario
    # Antes que nada: una partición que no se puede leer no deja a medias un
    # evaluacion.json sin la sección que se pidió.
    vista = leer_particion(particion) if particion else None
    ruta_capa = os.path.join(carpeta, "capa_pares.csv")
    with io.open(ruta_capa, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    sintaxis_presente = any(f.get("direccion_sintaxis") for f in filas)
    juicios = leer_juicios()
    unidas, sin_unir = unir(juicios, filas)
    if len(unidas) < MINIMO_UNIDAS:
        raise ErrorEvaluacion(
            "Solo %d de %d juicios se unieron con la capa (mínimo %d). Las "
            "oraciones o los pares ya no son los juzgados: la comparación no "
            "vale. Sin unir: líneas %s." % (len(unidas), len(juicios),
                                            MINIMO_UNIDAS, sin_unir))
    resultado = evaluar(juicios, unidas, sintaxis_presente)
    resultado["sin_unir"] = sin_unir
    resultado["disparador_dominante_punto_18"] = disparador_dominante(
        filas, vocabulario.Vocabulario.cargar())
    if vista is not None:
        resultado["P1_por_par_visto"] = por_par_visto(juicios, unidas, vista)
    puente.escribir_json(os.path.join(carpeta, "evaluacion.json"), resultado)

    def pct(d):
        return ("%.1f %% (%d/%d) [%.1f, %.1f]"
                % (100 * d["valor"], d["k"], d["n"], 100 * d["ic95"][0],
                   100 * d["ic95"][1])) if d["valor"] is not None else "n/d"
    log("Evaluación sobre las 50 oraciones juzgadas (unidas %d):"
        % len(unidas))
    log("  P0  bronce solo:                  %s" % pct(resultado["P0_bronce"]))
    log("  P1  bronce + BioBERT (umbral):    %s"
        % pct(resultado["P1_bronce_y_biobert_con_umbral"]))
    log("  P1' bronce + BioBERT (sin umbral): %s"
        % pct(resultado["P1_bronce_y_biobert_sin_umbral"]))
    log("  R1  sí retenidas (umbral):        %s"
        % pct(resultado["R1_retencion_de_las_si"]))
    log("  E1  no descartadas:               %s"
        % pct(resultado["E1_no_descartadas"]))
    s1 = resultado["S1_signo"]
    log("  S1  signo BioBERT, cuando lo da:  %s; «siempre +» en las mismas: %s"
        % (pct(s1["biobert"]["acierto"]),
           pct(s1["linea_base_siempre_mas_cubiertas"])))
    log("      con la abstención como error: %s; «siempre +» en la misma "
        "base: %s" % (pct(s1["biobert_abstencion_es_error"]),
                      pct(s1["linea_base_siempre_mas"])))
    if "D_direccion_sintaxis" in resultado:
        d = resultado["D_direccion_sintaxis"]
        log("  D1  dirección corregida (de 4):   %s"
            % pct(d["D1_corregidas_de_las_4_recuperables"]))
        log("  D2  sí que se romperían:          %s"
            % pct(d["D2_si_que_se_romperian"]))
    dd = resultado["disparador_dominante_punto_18"]
    log("  Punto 18, %d pares dirigidos (techo %d): bronce %s"
        % (dd["pares_dirigidos"], dd["techo"], dd["bronce"]))
    log("            control léxico %s" % dd["lexico"])
    if sintaxis_presente:
        log("            sintaxis %s" % dd["sintaxis"])
    if vista is not None:
        m = resultado["P1_por_par_visto"]
        log("  M1  P1, par visto al entrenar:    %s" % pct(m["P1_par_visto"]))
        log("      P1, par no visto:             %s"
            % pct(m["P1_par_no_visto"]))
        log("      P0 (control), visto / no:     %s / %s"
            % (pct(m["P0_par_visto"]), pct(m["P0_par_no_visto"])))
        log("      juzgadas con el par visto: %d de %d; con su PMID en "
            "train o dev: %d; con su texto: %d"
            % (m["juzgadas_con_par_visto"]["k"],
               m["juzgadas_con_par_visto"]["n"],
               m["juzgadas_con_pmid_en_train_dev"],
               m["juzgadas_con_texto_en_train_dev"]))
    return resultado
