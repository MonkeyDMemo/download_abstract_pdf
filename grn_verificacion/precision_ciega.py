"""La precisión pareada sobre la muestra ciega de 200: bronce contra red final.

    python -m grn_verificacion.cli precision-ciega --anotacion A.csv \
        --llave llave.csv --carpeta salidas/flujo/corrida4_run22 [--json J]

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

**Signo.** Se mide sobre los `si` con la dirección del bronce y signo `+` o `-`.
- **La abstención cuenta como error:** un `signo_sugerido` ambiguo (`?` o
  `+;-`) o una arista `regulates` no le dan signo al curador.
- **Los ítems comunes van aparte**, como dato secundario.

La entrada es la hoja anotada (`hoja_tanda1.csv`) o el CSV que exporta la
página de revisión del tablero. Tienen las mismas columnas, y las de más
(`inicio`, `fin`, `segundos`) solo dan el tiempo.

Solo biblioteca estándar. No lee la base curada ni nada del laboratorio.
"""

import collections
import csv
import io
import json
import random
import statistics

from grn_bronce.texto import normalizar_espacios
from grn_verificacion import evaluar

RELACIONES = ("si", "no", "dudoso")
DIRECCIONES = ("1>2", "2>1", "ninguna")
SIGNOS_RED = {"activates": "+", "represses": "-"}
BLOQUE = 25
REPETICIONES_BOOTSTRAP = 2000
SEMILLA_BOOTSTRAP = 20261024


def _leer_csv(ruta):
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def leer_anotacion(ruta):
    """{id_item: fila}, validada contra la rúbrica §6. Un valor fuera de la
    rúbrica detiene todo: una cifra con un `Si` o un `sí` mal contado vale
    menos que un error a tiempo."""
    filas = _leer_csv(ruta)
    errores, salida = [], {}
    for i, f in enumerate(filas, start=2):
        rel = (f.get("relacion") or "").strip()
        dire = (f.get("direccion") or "").strip()
        if rel and rel not in RELACIONES:
            errores.append("línea %d: relacion %r" % (i, rel))
        if rel and dire not in DIRECCIONES:
            errores.append("línea %d: direccion %r" % (i, dire))
        if f.get("id_item") in salida:
            errores.append("línea %d: %s repetido" % (i, f.get("id_item")))
        salida[f.get("id_item")] = f
    if errores:
        raise ValueError("La anotación no sigue la rúbrica: "
                         + "; ".join(errores[:10]))
    return salida


def _pares_canonicos(carpeta):
    """{id_par: (tf_id, target_id, signo_sugerido, oración normalizada)}
    desde `capa_pares.csv`: es la tabla donde ya están los ids canónicos y el
    signo léxico del bronce, una fila por par."""
    pares = {}
    for f in _leer_csv("%s/capa_pares.csv" % carpeta):
        pares[f["id_par"]] = (f["tf_id"], f["target_id"],
                              f.get("signo_sugerido", ""),
                              normalizar_espacios(f.get("oracion", "")))
    return pares


def aristas_de_la_red(carpeta, pares):
    """{(tf_id, target_id): signo de la arista} de `red.tsv`.

    `red.tsv` trae formas de presentación (LasR como regulador, lasR como
    blanco), así que la arista se reconoce por sus evidencias: `id_par` de
    `red_evidencias.tsv` lleva al par canónico, como en `grn_red/paquete.py`.

    Devuelve también las evidencias como (par canónico, oración normalizada):
    `red.py` deduplica por (tf, blanco, oración) y se queda con un `id_par`
    representante, así que la oración, y no el `id_par`, dice si la del ítem
    entró.
    """
    signo = dict(((f["tf"], f["blanco"]), f["signo"])
                 for f in _leer_tsv("%s/red.tsv" % carpeta))
    aristas, evidencias = {}, set()
    for e in _leer_tsv("%s/red_evidencias.tsv" % carpeta):
        par = pares.get(e["id_par"])
        if par is not None:
            canon = (par[0], par[1])
            aristas[canon] = signo.get((e["tf"], e["blanco"]), "")
            evidencias.add((canon, normalizar_espacios(e.get("oracion", ""))))
    return aristas, evidencias


def _signo_bronce(sugerido):
    return sugerido if sugerido in ("+", "-") else ""


def _precisiones(items):
    """Con dirección y sin dirección, sobre la lista de ítems anotados."""
    n = len(items)
    con = sum(1 for it in items if it["relacion"] == "si" and it["dir_ok"])
    sin = sum(1 for it in items if it["relacion"] == "si")
    return {"con_direccion": evaluar.proporcion(con, n),
            "sin_direccion": evaluar.proporcion(sin, n)}


def _acierto_signo(items, clave):
    """Sobre los `si` bien orientados con signo `+`/`-` anotado. La
    abstención (`clave` vacía) cuenta como error; los comunes van aparte."""
    base = [it for it in items if it["relacion"] == "si" and it["dir_ok"]
            and it["signo"] in ("+", "-")]
    bien = sum(1 for it in base if it[clave] == it["signo"])
    comunes = [it for it in base if it[clave]]
    bien_c = sum(1 for it in comunes if it[clave] == it["signo"])
    return {"abstencion_es_error": evaluar.proporcion(bien, len(base)),
            "solo_comunes": evaluar.proporcion(bien_c, len(comunes))}


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


def _tiempos(anotados):
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
            "minutos_total": round(sum(segundos) / 60.0, 1),
            "segundos_mediana_por_item": round(statistics.median(segundos), 1),
            "minutos_por_bloque_de_%d" % BLOQUE: bloques}


def calcular(ruta_anotacion, ruta_llave, carpeta):
    anotacion = leer_anotacion(ruta_anotacion)
    llave = dict((f["id_item"], f) for f in _leer_csv(ruta_llave))
    sin_llave = sorted(set(anotacion) - set(llave))
    if sin_llave:
        raise ValueError("%d ítems de la anotación no están en la llave (%s)"
                         % (len(sin_llave), ", ".join(sin_llave[:5])))
    pares = _pares_canonicos(carpeta)
    aristas, evidencias = aristas_de_la_red(carpeta, pares)

    anotados, sin_anotar, sin_par = [], 0, []
    for id_item, fila in anotacion.items():
        if not (fila.get("relacion") or "").strip():
            sin_anotar += 1
            continue
        clave = llave[id_item]
        par = pares.get(clave["id_par"])
        if par is None:
            sin_par.append(id_item)
            continue
        canon = (par[0], par[1])
        anotados.append({
            "fila": fila,
            "relacion": fila["relacion"].strip(),
            "signo": (fila.get("signo") or "").strip(),
            "dir_ok": fila["direccion"].strip() == clave["direccion_bronce"],
            "retenido": (canon, par[3]) in evidencias,
            "par_en_la_red": canon in aristas,
            "signo_bronce": _signo_bronce(par[2]),
            "signo_red": SIGNOS_RED.get(aristas.get(canon, ""), ""),
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
    return {
        "metodo": "precision-ciega",
        "n_anotados": len(anotados),
        "n_sin_anotar": sin_anotar,
        "reparto_relacion": dict(collections.Counter(
            it["relacion"] for it in anotados)),
        "bronce": dict(_precisiones(anotados), signo=_acierto_signo(
            anotados, "signo_bronce")),
        "red": dict(_precisiones(retenidos), signo=_acierto_signo(
            retenidos, "signo_red")),
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
        "tiempo": _tiempos(anotados),
    }


def ejecutar(ruta_anotacion, ruta_llave, carpeta, ruta_json=None,
             log=lambda m: None):
    r = calcular(ruta_anotacion, ruta_llave, carpeta)
    fmt = lambda p: ("%s/%s = %.1f %% [%.1f, %.1f]" % (
        p["k"], p["n"], 100 * p["valor"], 100 * p["ic95"][0],
        100 * p["ic95"][1]) if p["valor"] is not None else "%s/%s" % (
        p["k"], p["n"]))
    log("ítems anotados: %d (sin anotar: %d)" % (r["n_anotados"],
                                                 r["n_sin_anotar"]))
    log("bronce, precisión con dirección: %s"
        % fmt(r["bronce"]["con_direccion"]))
    log("red, precisión con dirección:    %s" % fmt(r["red"]["con_direccion"]))
    log("red, retención total:            %s"
        % fmt(r["retencion_de_la_red"]["total"]))
    log("red, retención de los verdaderos: %s"
        % fmt(r["retencion_de_la_red"]["de_los_verdaderos"]))
    log("diferencia red − bronce, IC95 por bootstrap pareado: %s"
        % r["pareado"]["diferencia_red_menos_bronce_ic95"])
    if ruta_json:
        tmp = ruta_json + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(r, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        from grn_comun import archivos
        archivos.reemplazar(tmp, ruta_json)
    return r
