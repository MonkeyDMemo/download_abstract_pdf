"""La precisión pareada sobre la muestra ciega de 200: bronce contra red final.

    python -m grn_verificacion.cli precision-ciega --anotacion A.csv \
        --llave llave.csv --carpeta salidas/flujo/corrida4_run22 [--json J] \
        [--red NOMBRE]

La muestra sale de la misma población que el 44 %: las oraciones del bronce
con regulador y blanco (`docs/rubrica-anotacion.md` §8, enmienda 1). Cada ítem
es una oración con el par que orientó el bronce, así que sobre los MISMOS ítems
se miden dos cosas:

- **El bronce**: los 200, porque todos son pares que propuso.
- **La red final** (`red.tsv`): solo los ítems cuya oración sostiene una
  arista, es decir, que está entre las evidencias de `red_evidencias.tsv`.
  Junto a su precisión va su retención; subir la precisión tirando relaciones
  buenas no es mejorar.

Retener «por oración» y no «por par» importa: un par puede llegar a la red por
otra oración del corpus aunque el clasificador haya descartado la del ítem, y
entonces el juicio del ítem no dice nada de esa arista. En la muestra real,
194 de 200 pares están en la red; cuántas de sus oraciones la sostienen es lo
que se mide. La cifra por par va aparte, como dato secundario. Las evidencias
de más de 200 por par que `red.py` recorta no cuentan como retenidas.

Las reglas son las de `etapa2/unir_juicios.py` y `evaluar.py`:
- `dudoso` va al denominador y nunca al numerador;
- un ítem sin anotar sale de todo, y se cuenta aparte.

La precisión «con dirección» exige además que la dirección anotada sea la del
bronce. Es la que se compara con el 44 %, que contó las inversiones como `no`.
Las inversiones (`si` con la dirección contraria a la del bronce, entre todos
los `si`) van aparte, para el bronce y para lo que la red retiene: en la
tanda 1 fueron la pérdida más grande.

**Signo.** Se mide sobre los `si` con la dirección del bronce y signo `+` o `-`.
- **La abstención cuenta como error:** un `signo_sugerido` ambiguo (`?` o
  `+;-`) o una arista `regulates` no le dan signo al curador.
- **Los ítems comunes van aparte**, como dato secundario.
- **La línea base «siempre +» se calcula sobre la misma base** que la cifra
  con la que se compara, y sobre los comunes otra vez: una línea base de otro
  denominador (el 70.7 % frente a un k/60 de la tanda 1) no se puede restar.

**La red que se mide.** Por omisión `red.tsv` y `red_evidencias.tsv`; con
`red`, una red con otras reglas de `grn_red/consolidar.py`
(`red_<nombre>.tsv`), con los nombres de `grn_comun/redes.py`. Sus filas
expandidas (`expandida_de` no vacío) no se leen: copian el signo del operón y
no tienen evidencia propia, y una que cae en el mismo (tf, blanco) que una
observada le pisaba el signo.

**El signo de la red es el de la oración.** El de un ítem es el de la arista
que sostiene SU oración: (par canónico, oración normalizada) lleva al signo de
la arista de esa evidencia. Con un signo por par, LasR → lasB y lasR → lasB
con signos distintos se pisaban y ganaba la última arista del archivo. Los
pares canónicos cuyas aristas no dicen lo mismo se cuentan
(`pares_con_signo_mixto`), y también las evidencias con un `id_par` que la
capa no tiene (`evidencias_sin_par_en_capa`), que dicen que la capa y la red
no son de la misma corrida.

**Validación.** Un valor fuera de la rúbrica (§6) detiene todo. Las
combinaciones que §4 no admite (un `no` con signo, un `si` con negada, una
`negada` vacía...) no detienen: las cuenta `avisos_de_rubrica`, porque la
tanda 1 se anotó en la hoja, sin la validación de la página, y sus cifras ya
se reportaron. La sensibilidad `sensibilidad_negadas_como_no` dice cuánto
pesan los `si` con negada.

La entrada es la hoja anotada (`hoja_tanda1.csv`) o el CSV que exporta la
página de revisión del tablero. Tienen las mismas columnas, y las de más
(`inicio`, `fin`, `segundos`) solo dan el tiempo.

Solo biblioteca estándar. No lee la base curada ni nada del laboratorio.
"""

import collections
import csv
import io
import json
import os
import random
import statistics

from grn_bronce.texto import normalizar_espacios
from grn_comun import redes
from grn_verificacion import evaluar

RELACIONES = ("si", "no", "dudoso")
DIRECCIONES = ("1>2", "2>1", "ninguna")
# Los valores de la rúbrica §6; vacío, porque un `no` no lleva signo ni tipo y
# un ítem sin anotar no lleva nada.
SIGNOS = ("", "+", "-", "?")
TIPOS = ("", "directa", "indirecta", "no_se")
SI_NO = ("", "si", "no")
SIGNOS_RED = {"activates": "+", "represses": "-"}
CAPA = "capa_pares.csv"
# Las combinaciones de §4 que no detienen el cálculo, en el orden del informe.
AVISOS_RUBRICA = ("no_con_signo_o_tipo", "no_sin_ninguna", "si_con_negada",
                  "si_o_dudoso_sin_signo_o_tipo",
                  "negada_o_especulativa_vacia")
NOMBRE_AVISO = {
    "no_con_signo_o_tipo": "«no» con signo o tipo",
    "no_sin_ninguna": "«no» sin dirección «ninguna»",
    "si_con_negada": "«si» con negada = si",
    "si_o_dudoso_sin_signo_o_tipo": "«si» o «dudoso» sin signo o sin tipo",
    "negada_o_especulativa_vacia": "negada o especulativa vacía",
}
BLOQUE = 25
REPETICIONES_BOOTSTRAP = 2000
SEMILLA_BOOTSTRAP = 20261024


def _leer_csv(ruta):
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _leer_tsv(ruta):
    """Los TSV de `etapa2/red.py` no entrecomillan (su `celda` solo colapsa
    los blancos). Con el `csv` por omisión, una oración que empezaba con
    comillas se leía sin ellas, y con unas comillas sin cerrar se comía las
    líneas siguientes: la evidencia dejaba de casar con la oración del ítem."""
    with io.open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t",
                                   quoting=csv.QUOTE_NONE))


def _valor(fila, columna):
    return (fila.get(columna) or "").strip()


def leer_anotacion(ruta):
    """{id_item: fila}, validada contra la rúbrica §6. Un valor fuera de la
    rúbrica detiene todo: una cifra con un `Si`, un `sí` o un signo `0` mal
    contado vale menos que un error a tiempo.

    `negada` y `especulativa` vacías no detienen, aunque la rúbrica pide
    siempre `si` o `no`: la tanda 1 las dejó vacías en ítems ya contados. Las
    cuenta `avisos_de_rubrica`, con las demás combinaciones de §4.
    """
    filas = _leer_csv(ruta)
    errores, salida = [], {}
    for i, f in enumerate(filas, start=2):
        rel = _valor(f, "relacion")
        dire = _valor(f, "direccion")
        if rel and rel not in RELACIONES:
            errores.append("línea %d: relacion %r" % (i, rel))
        if rel and dire not in DIRECCIONES:
            errores.append("línea %d: direccion %r" % (i, dire))
        for columna, validos in (("signo", SIGNOS), ("tipo", TIPOS),
                                 ("negada", SI_NO), ("especulativa", SI_NO)):
            valor = _valor(f, columna)
            if valor not in validos:
                errores.append("línea %d: %s %r" % (i, columna, valor))
        if f.get("id_item") in salida:
            errores.append("línea %d: %s repetido" % (i, f.get("id_item")))
        salida[f.get("id_item")] = f
    if errores:
        raise ValueError("La anotación no sigue la rúbrica: "
                         + "; ".join(errores[:10]))
    return salida


def avisos_de_rubrica(anotacion):
    """Counter de las combinaciones que la rúbrica §4 no admite, una por ítem
    anotado y por combinación. No detienen nada (ver `leer_anotacion`).

    - `no` lleva `direccion = ninguna` y ni signo ni tipo;
    - `si` y `dudoso` llevan siempre signo y tipo (`?` y `no_se` si la
      oración no los dice);
    - `si` con `negada = si` es un efecto negado anotado como relación: la
      página lo rechaza desde la enmienda 2;
    - `negada` y `especulativa` llevan siempre `si` o `no`.
    """
    avisos = collections.Counter()
    for fila in anotacion.values():
        rel = _valor(fila, "relacion")
        if not rel:
            continue
        signo, tipo = _valor(fila, "signo"), _valor(fila, "tipo")
        if rel == "no":
            if signo or tipo:
                avisos["no_con_signo_o_tipo"] += 1
            if _valor(fila, "direccion") != "ninguna":
                avisos["no_sin_ninguna"] += 1
        elif not signo or not tipo:
            avisos["si_o_dudoso_sin_signo_o_tipo"] += 1
        if rel == "si" and _valor(fila, "negada") == "si":
            avisos["si_con_negada"] += 1
        if not _valor(fila, "negada") or not _valor(fila, "especulativa"):
            avisos["negada_o_especulativa_vacia"] += 1
    return avisos


def _pares_canonicos(ruta_capa):
    """{id_par: (tf_id, target_id, signo_sugerido, oración normalizada)}
    desde `capa_pares.csv`: es la tabla donde ya están los ids canónicos y el
    signo léxico del bronce, una fila por par."""
    pares = {}
    for f in _leer_csv(ruta_capa):
        pares[f["id_par"]] = (f["tf_id"], f["target_id"],
                              f.get("signo_sugerido") or "",
                              normalizar_espacios(f.get("oracion") or ""))
    return pares


def aristas_de_la_red(carpeta, pares, red=None):
    """Lo que la red de `carpeta` dice de los pares canónicos de `pares`.

    `red.tsv` trae formas de presentación (LasR como regulador, lasR como
    blanco), así que la arista se reconoce por sus evidencias: `id_par` de
    `red_evidencias.tsv` lleva al par canónico, como en `grn_red/paquete.py`.
    `red.py` deduplica por (tf, blanco, oración) y se queda con un `id_par`
    representante, así que la oración, y no el `id_par`, dice si la del ítem
    entró. `red` es el nombre de una red con otras reglas
    (`redes.archivos_de_red`); sus filas con `expandida_de` no se leen.

    Devuelve un dict:
    - `signo_de_evidencia`: {(par canónico, oración normalizada): signo de la
      arista que esa evidencia sostiene}; vacío si la misma oración del mismo
      par sostuviera aristas con signos distintos, porque no se vota;
    - `pares`: los pares canónicos con alguna evidencia en la red;
    - `pares_con_signo_mixto`: cuántos de esos pares tienen aristas que no
      dicen el mismo signo;
    - `evidencias_sin_par_en_capa`: evidencias con un `id_par` que la capa no
      tiene.
    """
    nombre_red, nombre_evidencias, _ = redes.archivos_de_red(red)
    signo = {}
    for f in _leer_tsv(os.path.join(carpeta, nombre_red)):
        if (f.get("expandida_de") or "").strip():
            continue
        signo[(f["tf"], f["blanco"])] = f["signo"]
    por_par = collections.defaultdict(set)
    por_evidencia = collections.defaultdict(set)
    sin_par = 0
    for e in _leer_tsv(os.path.join(carpeta, nombre_evidencias)):
        par = pares.get(e["id_par"])
        if par is None:
            sin_par += 1
            continue
        canon = (par[0], par[1])
        s = signo.get((e["tf"], e["blanco"]), "")
        por_par[canon].add(s)
        por_evidencia[(canon, normalizar_espacios(e.get("oracion") or ""))
                      ].add(s)
    return {
        "signo_de_evidencia": dict(
            (k, next(iter(v)) if len(v) == 1 else "")
            for k, v in por_evidencia.items()),
        "pares": set(por_par),
        "pares_con_signo_mixto": sum(1 for v in por_par.values()
                                     if len(v) > 1),
        "evidencias_sin_par_en_capa": sin_par,
    }


def _signo_bronce(sugerido):
    return sugerido if sugerido in ("+", "-") else ""


def _precisiones(items):
    """Con dirección y sin dirección, sobre la lista de ítems anotados."""
    n = len(items)
    con = sum(1 for it in items if it["relacion"] == "si" and it["dir_ok"])
    sin = sum(1 for it in items if it["relacion"] == "si")
    return {"con_direccion": evaluar.proporcion(con, n),
            "sin_direccion": evaluar.proporcion(sin, n)}


def _inversiones(items):
    """Los `si` con una dirección distinta de la del bronce, entre los `si`:
    relaciones ciertas que la precisión con dirección cuenta como error."""
    si = [it for it in items if it["relacion"] == "si"]
    return evaluar.proporcion(sum(1 for it in si if not it["dir_ok"]),
                              len(si))


def _acierto_signo(items, clave):
    """Sobre los `si` bien orientados con signo `+`/`-` anotado. La
    abstención (`clave` vacía) cuenta como error; los comunes van aparte.
    «Siempre +» va sobre cada una de las dos bases: es la cifra que tiene
    que ganar quien da signo, y solo se puede restar si el denominador es el
    mismo."""
    base = [it for it in items if it["relacion"] == "si" and it["dir_ok"]
            and it["signo"] in ("+", "-")]
    bien = sum(1 for it in base if it[clave] == it["signo"])
    comunes = [it for it in base if it[clave]]
    bien_c = sum(1 for it in comunes if it[clave] == it["signo"])
    return {"abstencion_es_error": evaluar.proporcion(bien, len(base)),
            "linea_base_siempre_mas": evaluar.proporcion(
                sum(1 for it in base if it["signo"] == "+"), len(base)),
            "solo_comunes": evaluar.proporcion(bien_c, len(comunes)),
            "linea_base_siempre_mas_comunes": evaluar.proporcion(
                sum(1 for it in comunes if it["signo"] == "+"),
                len(comunes))}


def _bootstrap_diferencia(items, repeticiones=REPETICIONES_BOOTSTRAP,
                          semilla=SEMILLA_BOOTSTRAP):
    """IC 95 % percentil de (precisión de la red − precisión del bronce), con
    dirección, remuestreando ítems: las dos cifras salen de los mismos ítems
    y no son independientes."""
    rnd = random.Random(semilla)
    n = len(items)
    difs = []
    for _ in range(repeticiones):
        mu = [items[rnd.randrange(n)] for _ in range(n)]
        bien = [it["relacion"] == "si" and it["dir_ok"] for it in mu]
        red = [b for b, it in zip(bien, mu) if it["retenido"]]
        if not red:
            continue
        difs.append(sum(red) / len(red) - sum(bien) / n)
    if not difs:
        return None
    difs.sort()
    return [round(difs[int(0.025 * len(difs))], 4),
            round(difs[int(0.975 * len(difs)) - 1], 4)]


def _sensibilidad_negadas(anotados):
    """Los `si` con `negada = si` pasados a `no`, y las precisiones con
    dirección recalculadas. La rúbrica (§3.6) anota el efecto negado como
    `no`; la tanda 1 tiene `si` con negada, y esto dice cuánto pesan. La
    diferencia es el IC del mismo bootstrap pareado."""
    def negada(it):
        return it["relacion"] == "si" and it["negada"] == "si"
    cambiados = [dict(it, relacion="no") if negada(it) else it
                 for it in anotados]
    retenidos = [it for it in cambiados if it["retenido"]]
    return {"n_negadas": sum(1 for it in anotados if negada(it)),
            "bronce": _precisiones(cambiados)["con_direccion"],
            "red": _precisiones(retenidos)["con_direccion"],
            "diferencia": _bootstrap_diferencia(cambiados)
            if cambiados else None}


def _tiempos(anotados):
    """Tiempo de anotación, o None si ningún ítem trae `segundos`. Cuenta
    también los anotados sin tiempo: si faltan muchos, la cifra no vale."""
    segundos = []
    for it in anotados:
        try:
            segundos.append(float(it["fila"].get("segundos") or ""))
        except ValueError:
            pass
    if not segundos:
        return None
    bloques = [round(sum(segundos[i:i + BLOQUE]) / 60.0, 1)
               for i in range(0, len(segundos), BLOQUE)]
    return {"items_con_tiempo": len(segundos),
            "items_sin_tiempo": len(anotados) - len(segundos),
            "minutos_total": round(sum(segundos) / 60.0, 1),
            "segundos_mediana_por_item": round(statistics.median(segundos), 1),
            "minutos_por_bloque_de_%d" % BLOQUE: bloques}


def calcular(ruta_anotacion, ruta_llave, carpeta, red=None):
    """El resultado completo, solo con cifras (ver el docstring del módulo).

    `red`: nombre de una red con otras reglas, o None para `red.tsv`.
    """
    anotacion = leer_anotacion(ruta_anotacion)
    filas_llave = _leer_csv(ruta_llave)
    llave = dict((f["id_item"], f) for f in filas_llave)
    sin_llave = sorted(set(anotacion) - set(llave))
    if sin_llave:
        raise ValueError("%d ítems de la anotación no están en la llave (%s)"
                         % (len(sin_llave), ", ".join(sin_llave[:5])))
    ruta_capa = os.path.join(carpeta, CAPA)
    nombre_red, nombre_evidencias, _ = redes.archivos_de_red(red)
    pares = _pares_canonicos(ruta_capa)
    leida = aristas_de_la_red(carpeta, pares, red)
    evidencias = leida["signo_de_evidencia"]

    anotados, sin_anotar, sin_par = [], 0, []
    for id_item, fila in anotacion.items():
        if not _valor(fila, "relacion"):
            sin_anotar += 1
            continue
        clave = llave[id_item]
        par = pares.get(clave["id_par"])
        if par is None:
            sin_par.append(id_item)
            continue
        canon = (par[0], par[1])
        signo_red = evidencias.get((canon, par[3]))
        anotados.append({
            "fila": fila,
            "relacion": _valor(fila, "relacion"),
            "signo": _valor(fila, "signo"),
            "negada": _valor(fila, "negada"),
            "dir_ok": _valor(fila, "direccion") == clave["direccion_bronce"],
            "retenido": signo_red is not None,
            "par_en_la_red": canon in leida["pares"],
            "signo_bronce": _signo_bronce(par[2]),
            "signo_red": SIGNOS_RED.get(signo_red or "", ""),
        })
    if sin_par:
        raise ValueError("%d ítems con un id_par que la capa no tiene (%s): "
                         "la llave no es de esta carpeta"
                         % (len(sin_par), ", ".join(sin_par[:5])))
    anotados.sort(key=lambda it: it["fila"].get("inicio") or "")

    retenidos = [it for it in anotados if it["retenido"]]
    verdaderos = [it for it in anotados
                  if it["relacion"] == "si" and it["dir_ok"]]
    tabla = collections.Counter(
        ("bien" if it["relacion"] == "si" and it["dir_ok"] else "mal",
         "en_la_red" if it["retenido"] else "fuera")
        for it in anotados)
    avisos = avisos_de_rubrica(anotacion)
    return {
        "metodo": "precision-ciega",
        "entradas": {"red": nombre_red, "evidencias": nombre_evidencias},
        "n_anotados": len(anotados),
        "n_sin_anotar": sin_anotar,
        "reparto_relacion": dict(collections.Counter(
            it["relacion"] for it in anotados)),
        "bronce": dict(_precisiones(anotados),
                       inversiones=_inversiones(anotados),
                       signo=_acierto_signo(anotados, "signo_bronce")),
        "red": dict(_precisiones(retenidos),
                    inversiones=_inversiones(retenidos),
                    signo=_acierto_signo(retenidos, "signo_red")),
        "retencion_de_la_red": {
            "total": evaluar.proporcion(len(retenidos), len(anotados)),
            "de_los_verdaderos": evaluar.proporcion(
                sum(1 for it in verdaderos if it["retenido"]),
                len(verdaderos)),
            "par_en_la_red_por_cualquier_oracion": evaluar.proporcion(
                sum(1 for it in anotados if it["par_en_la_red"]),
                len(anotados)),
        },
        "pareado": {
            "tabla": dict(("%s|%s" % k, v) for k, v in sorted(tabla.items())),
            "diferencia_red_menos_bronce_ic95": _bootstrap_diferencia(
                anotados) if anotados else None,
        },
        "sensibilidad_negadas_como_no": _sensibilidad_negadas(anotados),
        "avisos_rubrica": dict((k, avisos[k]) for k in AVISOS_RUBRICA),
        "pares_con_signo_mixto": leida["pares_con_signo_mixto"],
        "evidencias_sin_par_en_capa": leida["evidencias_sin_par_en_capa"],
        "tiempo": _tiempos(anotados),
    }


def _fmt(p):
    if p["valor"] is None:
        return "%s/%s" % (p["k"], p["n"])
    return "%s/%s = %.1f %% [%.1f, %.1f]" % (
        p["k"], p["n"], 100 * p["valor"], 100 * p["ic95"][0],
        100 * p["ic95"][1])


def lineas(r):
    """Lo que ve quien corre esto: solo cifras y nombres de archivo."""
    e = r["entradas"]
    salida = [
        "red: %s y %s" % (e["red"], e["evidencias"]),
        "ítems anotados: %d (sin anotar: %d)" % (r["n_anotados"],
                                                r["n_sin_anotar"]),
    ]
    b, red = r["bronce"], r["red"]
    salida += [
        "bronce, precisión con dirección: %s" % _fmt(b["con_direccion"]),
        "red, precisión con dirección:    %s" % _fmt(red["con_direccion"]),
        "red, retención total:            %s"
        % _fmt(r["retencion_de_la_red"]["total"]),
        "red, retención de los verdaderos: %s"
        % _fmt(r["retencion_de_la_red"]["de_los_verdaderos"]),
        "diferencia red − bronce, IC95 por bootstrap pareado: %s"
        % r["pareado"]["diferencia_red_menos_bronce_ic95"],
        "bronce, inversiones (de los si):          %s"
        % _fmt(b["inversiones"]),
        "red, inversiones (de los si que retiene): %s"
        % _fmt(red["inversiones"]),
    ]
    for nombre, d in (("bronce", b), ("red", red)):
        s = d["signo"]
        salida.append("%s, signo con la abstención como error: %s; «siempre "
                      "+» en la misma base: %s" % (
                          nombre, _fmt(s["abstencion_es_error"]),
                          _fmt(s["linea_base_siempre_mas"])))
        salida.append("%s, signo solo en los comunes: %s; «siempre +» en "
                      "los mismos: %s" % (
                          nombre, _fmt(s["solo_comunes"]),
                          _fmt(s["linea_base_siempre_mas_comunes"])))
    s = r["sensibilidad_negadas_como_no"]
    if s["n_negadas"]:
        salida.append("sensibilidad, los %d «si» con negada = si como «no»: "
                      "bronce %s; red %s; diferencia, IC95: %s" % (
                          s["n_negadas"], _fmt(s["bronce"]), _fmt(s["red"]),
                          s["diferencia"]))
    else:
        salida.append("sensibilidad: ningún «si» lleva negada = si; las "
                      "cifras no cambian")
    avisos = r["avisos_rubrica"]
    if any(avisos.values()):
        salida.append("avisos de la rúbrica (§4): " + "; ".join(
            "%s %d" % (NOMBRE_AVISO[k], avisos[k])
            for k in AVISOS_RUBRICA if avisos[k]))
    if r["pares_con_signo_mixto"]:
        salida.append("AVISO: %d pares canónicos con aristas de signo "
                      "distinto en la red; el signo de cada ítem es el de la "
                      "arista de su oración" % r["pares_con_signo_mixto"])
    if r["evidencias_sin_par_en_capa"]:
        salida.append("AVISO: %d evidencias de la red con un id_par que la "
                      "capa no tiene: ¿son de la misma corrida?"
                      % r["evidencias_sin_par_en_capa"])
    t = r["tiempo"]
    if t:
        salida.append("tiempo: %.1f min en %d ítems (mediana %.1f s por "
                      "ítem); sin tiempo: %d" % (
                          t["minutos_total"], t["items_con_tiempo"],
                          t["segundos_mediana_por_item"],
                          t["items_sin_tiempo"]))
    else:
        salida.append("tiempo: ningún ítem trae `segundos` (¿se anotó en la "
                      "hoja?)")
    return salida


def ejecutar(ruta_anotacion, ruta_llave, carpeta, ruta_json=None,
             log=lambda m: None, red=None):
    r = calcular(ruta_anotacion, ruta_llave, carpeta, red=red)
    for linea in lineas(r):
        log(linea)
    if ruta_json:
        tmp = ruta_json + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        from grn_comun import archivos
        archivos.reemplazar(tmp, ruta_json)
    return r
