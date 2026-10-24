"""El acuerdo de Ouroboros con el experto sobre la misma hoja.

    python -m grn_verificacion.cli concordancia --experto A.csv \
        --modelo anotaciones.csv [--llave llave.csv] [--json J]

Ouroboros (`grn_ouroboros`, exploratorio y fuera del pipeline) anota las
mismas hojas que el experto, con las mismas columnas. Los dos CSV se leen con
`precision_ciega.leer_anotacion`, el mismo lector que valida la rúbrica, y se
comparan **sobre los ítems que el experto anotó**:

- el acuerdo exacto por campo, con su intervalo de Wilson;
- el κ de Cohen en `relacion`, y en cada campo;
- las matrices de confusión de los seis campos cerrados (filas: el experto;
  columnas: el modelo);
- las abstenciones del modelo. En su CSV, la abstención es un ítem con los
  campos de anotación vacíos, y **cuenta como error** en todos los campos.
  En el κ es una categoría más, que el experto nunca usa: nunca coincide y no
  suma al acuerdo esperado.

Con `--llave` (la `llave.csv` del sorteo), además, el modelo como filtro de
los pares del bronce: **acepta** el ítem si dice `relacion` = `si` con la
dirección del bronce. Es la misma pregunta que `precision-ciega` le hace a la
red final, y con las mismas reglas: verdadero es `si` con la dirección del
bronce, y `dudoso` va al denominador, nunca al numerador. Se reporta su
precisión contra el experto, su retención de las verdaderas y la diferencia
con la precisión del bronce, con un IC 95 % por bootstrap pareado con la
semilla y las repeticiones de `precision_ciega`. De la llave se leen solo
`id_item` y `direccion_bronce`.

Con `--entre-humanos`, la segunda anotación es de otra persona sobre una
parte de la hoja: el acuerdo y el κ por campo (exploratorio) sobre los ítems
que anotaron las dos, sin abstenciones ni filtro (ver `calcular`).

Solo conteos en el log y en el JSON: ninguna oración, ningún PMID, ningún
`id_item`. La tanda 2 es ciega para toda sesión de Claude hasta evaluarla, y
sus cifras son lo único que se publica.

Biblioteca estándar y Python 3.8. No imprime: reporta por `log`.
"""

import collections
import csv
import io
import json
import random
import re

from grn_bronce.texto import normalizar_espacios
from grn_verificacion import evaluar, precision_ciega

CAMPOS = ("relacion", "direccion", "signo", "tipo", "negada", "especulativa")
ABSTENCION = "abstencion"
VACIO = "vacio"
# `leer_anotacion` solo valida relación y dirección: en signo, tipo, negada
# o especulativa puede llegar texto libre (una nota en la columna que no era,
# con un PMID, por ejemplo), y las etiquetas de la matriz salen en el log y
# en el JSON. Por eso un valor fuera de la rúbrica se cuenta aquí y nunca
# sale tal cual.
FUERA = "fuera_de_rubrica"

# El orden en que salen las filas y columnas de cada matriz; el vacío y lo
# que cae en FUERA van al final.
ORDEN = {
    "relacion": ("si", "no", "dudoso"),
    "direccion": ("1>2", "2>1", "ninguna"),
    "signo": ("+", "-", "?", VACIO),
    "tipo": ("directa", "indirecta", "no_se", VACIO),
    "negada": ("si", "no"),
    "especulativa": ("si", "no"),
}

NOTAS = (
    "La abstención del modelo cuenta como error en todos los campos.",
    "En la tanda 1 el experto marcó «directa» donde la rúbrica pide no_se "
    "(§3.3; calibración 2, punto 4): el acuerdo en tipo de la tanda 1 lleva "
    "esa salvedad.",
)


NOTAS_HUMANOS = (
    "Acuerdo entre dos anotadoras humanas, sobre los ítems que anotaron las "
    "dos. Es exploratorio: con unos 50 ítems el kappa tiene un intervalo "
    "ancho y aquí no se calcula.",
    NOTAS[1],
)


_LINEA = re.compile(r"línea (\d+)")


def _leer(ruta, quien):
    """`precision_ciega.leer_anotacion`, con sus errores reducidos a los
    números de línea: su mensaje trae tal cual el valor que no sigue la
    rúbrica, o el `id_item` repetido, y de aquí solo salen conteos."""
    try:
        return precision_ciega.leer_anotacion(ruta)
    except ValueError as e:
        lineas = sorted(set(int(n) for n in _LINEA.findall(str(e))))
        # `from None`: un traceback encadenado volvería a mostrar el
        # mensaje original.
        raise ValueError("La anotación %s no sigue la rúbrica (§6)%s." % (
            quien, " en las líneas %s" % ", ".join(str(n) for n in lineas)
            if lineas else "")) from None


def _valores(fila):
    return dict((c, (fila.get(c) or "").strip()) for c in CAMPOS)


def _etiqueta(campo, valor):
    """La categoría de un valor en la matriz: el mismo si es de la rúbrica,
    VACIO si no hay, y FUERA si es cualquier otra cosa."""
    if not valor:
        return VACIO
    return valor if valor in ORDEN[campo] else FUERA


def kappa(pares):
    """El κ de Cohen de una lista de (experto, modelo), o None si el acuerdo
    esperado es 1 (los dos usaron una sola y la misma categoría) o no hay
    pares: ahí el κ no está definido."""
    n = len(pares)
    if not n:
        return None
    observado = sum(1 for e, m in pares if e == m) / float(n)
    del_experto = collections.Counter(e for e, _m in pares)
    del_modelo = collections.Counter(m for _e, m in pares)
    esperado = sum(del_experto[c] * del_modelo[c]
                   for c in del_experto) / float(n * n)
    if esperado >= 1:
        return None
    return round((observado - esperado) / (1 - esperado), 4)


def matriz(pares, orden=()):
    """{valor del experto: {valor del modelo: conteo}}.

    Las filas y las columnas son todas las categorías de la rúbrica, en su
    orden, aunque nadie las haya usado, y la abstención va siempre de última
    columna: así dos corridas se comparan celda por celda. El vacío y FUERA
    se agregan al final cuando aparecen.
    """
    conteo = collections.Counter(pares)
    vistos = set(e for e, _m in pares) | set(m for _e, m in pares)
    categorias = list(orden) + sorted(vistos - set(orden) - {ABSTENCION})
    return collections.OrderedDict(
        (e, collections.OrderedDict((m, conteo[(e, m)])
                                    for m in categorias + [ABSTENCION]))
        for e in categorias)


def _misma_hoja(fila_e, fila_m):
    """Si la fila del modelo es del mismo ítem: la misma oración (con los
    espacios normalizados) y las mismas entidades, cuando las dos las
    traen."""
    for columna in ("oracion", "entidad_1", "entidad_2"):
        e = normalizar_espacios(fila_e.get(columna) or "")
        m = normalizar_espacios(fila_m.get(columna) or "")
        if e and m and e != m:
            return False
    return True


def _leer_direcciones(ruta_llave):
    """{id_item: direccion_bronce}. Las demás columnas de la llave no se
    guardan."""
    with io.open(ruta_llave, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        faltan = [c for c in ("id_item", "direccion_bronce")
                  if c not in (lector.fieldnames or [])]
        if faltan:
            raise ValueError("A la llave le faltan columnas: %s."
                             % ", ".join(faltan))
        return dict(((fila["id_item"] or "").strip(),
                     (fila["direccion_bronce"] or "").strip())
                    for fila in lector)


def _bootstrap_diferencia(items,
                          repeticiones=precision_ciega.REPETICIONES_BOOTSTRAP,
                          semilla=precision_ciega.SEMILLA_BOOTSTRAP):
    """IC 95 % percentil de (precisión del filtro − precisión del bronce),
    remuestreando ítems: las dos cifras salen de los mismos ítems y no son
    independientes. `items` es [(verdadero, aceptado)]. Es el mismo
    procedimiento que `precision_ciega` usa para la red final."""
    rnd = random.Random(semilla)
    n = len(items)
    difs = []
    for _ in range(repeticiones):
        mu = [items[rnd.randrange(n)] for _ in range(n)]
        aceptados = [v for v, a in mu if a]
        if not aceptados:
            continue
        difs.append(sum(aceptados) / float(len(aceptados))
                    - sum(v for v, _a in mu) / float(n))
    if not difs:
        return None
    difs.sort()
    return [round(difs[int(0.025 * len(difs))], 4),
            round(difs[int(0.975 * len(difs)) - 1], 4)]


def _filtro(comparados, direcciones):
    items = []
    for id_item, e, m, abstencion in comparados:
        bronce = direcciones[id_item]
        verdadero = e["relacion"] == "si" and e["direccion"] == bronce
        aceptado = (not abstencion and m["relacion"] == "si"
                    and m["direccion"] == bronce)
        items.append((verdadero, aceptado))
    n = len(items)
    aceptados = [v for v, a in items if a]
    verdaderos = [a for v, a in items if v]
    bronce = evaluar.proporcion(sum(v for v, _a in items), n)
    filtro = evaluar.proporcion(sum(aceptados), len(aceptados))
    tabla = collections.Counter(
        ("verdadero" if v else "falso", "acepta" if a else "rechaza")
        for v, a in items)
    return {
        "regla": "acepta = relación si con la dirección del bronce",
        "bronce_precision_con_direccion": bronce,
        "filtro_precision_con_direccion": filtro,
        "retencion_de_los_verdaderos": evaluar.proporcion(sum(verdaderos),
                                                          len(verdaderos)),
        "retencion_total": evaluar.proporcion(len(aceptados), n),
        "tabla": dict(("%s|%s" % k, v) for k, v in sorted(tabla.items())),
        "diferencia_filtro_menos_bronce": (
            round(filtro["valor"] - bronce["valor"], 4)
            if filtro["valor"] is not None and bronce["valor"] is not None
            else None),
        "diferencia_ic95": _bootstrap_diferencia(items) if n else None,
    }


def _anotado(fila):
    return bool((fila.get("relacion") or "").strip())


def calcular(ruta_experto, ruta_modelo, ruta_llave=None, entre_humanos=False):
    """Con `entre_humanos`, la segunda anotación es de otra persona sobre una
    parte de la hoja (la segunda anotadora anota 50 ítems de la tanda 1): se
    comparan los ítems que anotaron las dos, y un ítem que la segunda no
    anotó queda fuera y se cuenta, porque no es una abstención sino un ítem
    que no le tocó. Sin la llave: el filtro es una pregunta para un modelo."""
    if entre_humanos and ruta_llave:
        raise ValueError("Entre humanas no hay filtro: --llave es para una "
                         "corrida de Ouroboros.")
    experto = _leer(ruta_experto, "del experto")
    modelo = _leer(ruta_modelo, "de la segunda anotadora" if entre_humanos
                   else "del modelo")
    anotados = sorted(i for i, f in experto.items() if _anotado(f))
    fuera_de_la_segunda = solo_en_la_segunda = 0
    if entre_humanos:
        solo_en_la_segunda = sum(1 for i, f in modelo.items()
                                 if _anotado(f) and i not in anotados)
        fuera_de_la_segunda = sum(1 for i in anotados
                                  if not _anotado(modelo.get(i, {})))
        anotados = [i for i in anotados if _anotado(modelo.get(i, {}))]
        if not anotados:
            raise ValueError("Ningún ítem lo anotaron las dos: no son la "
                             "misma hoja o la segunda está vacía.")
    faltan = [i for i in anotados if i not in modelo]
    if faltan:
        raise ValueError("%d ítems que anotó el experto no están en la "
                         "anotación del modelo: no son la misma hoja."
                         % len(faltan))
    otros = sum(1 for i in anotados
                if not _misma_hoja(experto[i], modelo[i]))
    if otros:
        raise ValueError("%d ítems tienen otra oración u otras entidades en "
                         "la anotación del modelo: no son la misma hoja."
                         % otros)
    comparados, mal_formados = [], 0
    for id_item in anotados:
        e, m = _valores(experto[id_item]), _valores(modelo[id_item])
        abstencion = not m["relacion"]
        if abstencion and any(m.values()):
            mal_formados += 1
        comparados.append((id_item, e, m, abstencion))
    if mal_formados:
        raise ValueError("%d ítems del modelo vienen sin relación pero con "
                         "otros valores: la abstención es con todos los "
                         "campos vacíos." % mal_formados)

    n = len(comparados)
    acuerdo, matrices = {}, {}
    for campo in CAMPOS:
        # El acuerdo, con los valores tal cual: dos valores distintos fuera
        # de la rúbrica caen los dos en FUERA y no son un acuerdo.
        acuerdo[campo] = evaluar.proporcion(
            sum(1 for _i, e, m, abstencion in comparados
                if not abstencion and e[campo] == m[campo]), n)
        pares = [(_etiqueta(campo, e[campo]),
                  ABSTENCION if abstencion else _etiqueta(campo, m[campo]))
                 for _i, e, m, abstencion in comparados]
        matrices[campo] = matriz(pares, ORDEN[campo])
    abstenciones = sum(1 for c in comparados if c[3])
    kappas = dict((campo, kappa([
        (_etiqueta(campo, e[campo]),
         ABSTENCION if abstencion else _etiqueta(campo, m[campo]))
        for _i, e, m, abstencion in comparados])) for campo in CAMPOS)
    resultado = {
        "metodo": "concordancia_entre_humanos" if entre_humanos
                  else "concordancia",
        "n_anotados_por_el_experto": n,
        "n_sin_anotar_por_el_experto": len(experto) - n - fuera_de_la_segunda,
        "abstenciones_del_modelo": (None if entre_humanos
                                    else evaluar.proporcion(abstenciones, n)),
        "acuerdo_por_campo": acuerdo,
        "kappa_relacion": kappas["relacion"],
        "kappa_por_campo": kappas,
        "matrices": matrices,
        "filtro": None,
        "notas": list(NOTAS_HUMANOS if entre_humanos else NOTAS),
    }
    if entre_humanos:
        resultado["n_comunes"] = n
        resultado["n_del_experto_que_la_segunda_no_anoto"] = \
            fuera_de_la_segunda
        resultado["n_que_solo_anoto_la_segunda"] = solo_en_la_segunda
    if ruta_llave:
        direcciones = _leer_direcciones(ruta_llave)
        sin_llave = sum(1 for i in anotados if i not in direcciones)
        if sin_llave:
            raise ValueError("%d ítems anotados no están en la llave: no es "
                             "la llave de esta hoja." % sin_llave)
        resultado["filtro"] = _filtro(comparados, direcciones)
    return resultado


def _fmt(p):
    if p["valor"] is None:
        return "%s/%s" % (p["k"], p["n"])
    return "%s/%s = %.1f %% [%.1f, %.1f]" % (
        p["k"], p["n"], 100 * p["valor"], 100 * p["ic95"][0],
        100 * p["ic95"][1])


def _lineas_matriz(campo, m, columnas_de="modelo"):
    columnas = list(next(iter(m.values())).keys()) if m else []
    ancho = max([len(c) for c in columnas] + [len(f) for f in m] + [7])
    lineas = ["  %s (filas: experto; columnas: %s)" % (campo, columnas_de),
              "    " + " " * ancho + "".join(c.rjust(ancho + 1)
                                           for c in columnas)]
    for fila, conteos in m.items():
        lineas.append("    " + fila.ljust(ancho) + "".join(
            str(conteos[c]).rjust(ancho + 1) for c in columnas))
    return lineas


def _k(valor):
    return "no definido" if valor is None else "%.3f" % valor


def ejecutar(ruta_experto, ruta_modelo, ruta_llave=None, ruta_json=None,
             log=lambda m: None, entre_humanos=False):
    r = calcular(ruta_experto, ruta_modelo, ruta_llave, entre_humanos)
    if entre_humanos:
        log("ítems que anotaron las dos: %d (del experto que la segunda no "
            "anotó: %d; que solo anotó la segunda: %d)"
            % (r["n_comunes"], r["n_del_experto_que_la_segunda_no_anoto"],
               r["n_que_solo_anoto_la_segunda"]))
    else:
        log("ítems anotados por el experto: %d (sin anotar: %d)"
            % (r["n_anotados_por_el_experto"],
               r["n_sin_anotar_por_el_experto"]))
        log("abstenciones del modelo: %s" % _fmt(r["abstenciones_del_modelo"]))
    log("acuerdo por campo:")
    for campo in CAMPOS:
        log("  %-13s %s" % (campo, _fmt(r["acuerdo_por_campo"][campo])))
    # «kappa» y no la letra griega: fuera de Latin-1 no imprime en la consola
    # de Windows.
    log("kappa de Cohen en relación: %s" % _k(r["kappa_relacion"]))
    log("kappa de Cohen por campo: %s" % "; ".join(
        "%s %s" % (campo, _k(r["kappa_por_campo"][campo]))
        for campo in CAMPOS))
    log("matrices de confusión:")
    for campo in CAMPOS:
        for linea in _lineas_matriz(campo, r["matrices"][campo],
                                    "segunda" if entre_humanos else "modelo"):
            log(linea)
    f = r["filtro"]
    if f:
        log("el modelo como filtro del bronce (%s):" % f["regla"])
        log("  bronce, precisión con dirección:  %s"
            % _fmt(f["bronce_precision_con_direccion"]))
        log("  filtro, precisión con dirección:  %s"
            % _fmt(f["filtro_precision_con_direccion"]))
        log("  filtro, retención de los verdaderos: %s"
            % _fmt(f["retencion_de_los_verdaderos"]))
        log("  filtro - bronce: %s, IC95 por bootstrap pareado: %s"
            % (f["diferencia_filtro_menos_bronce"], f["diferencia_ic95"]))
    for nota in r["notas"]:
        log("Nota: %s" % nota)
    if ruta_json:
        tmp = ruta_json + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        from grn_comun import archivos
        archivos.reemplazar(tmp, ruta_json)
    return r
