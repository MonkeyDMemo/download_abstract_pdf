#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Muestrea la red para medir PRECISION con juicio humano.

POR QUE ESTO Y NO evaluar_oro.py
--------------------------------
`evaluar_oro.py` da exhaustividad y acierto de signo, y **prohibe calcular
precision**, con razon: el patron de oro cubre 6 subsistemas con 190
relaciones, asi que una arista fuera de esa lista no esta mal, simplemente no
esta en la lista. Contarla como falso positivo seria una calumnia contra el
pipeline, no una medicion.

Cuando la referencia no es exhaustiva, la forma valida de medir precision --y
es lo estandar en extraccion de informacion-- es **muestrear la salida del
sistema y juzgar cada elemento**. Eso hace este archivo: prepara la muestra y,
cuando alguien la llena, la resume.

EL MUESTREO ES ESTRATIFICADO, Y POR QUE IMPORTA
-----------------------------------------------
La red tiene 8 653 aristas muy desiguales:

    A  con signo, >=3 articulos, sin conflicto      945  (10.9%)  <- el entregable
    B  con signo, evidencia mas debil             3 188  (36.8%)
    C  sin signo resuelto (regulates)             4 520  (52.2%)

Un muestreo proporcional de 250 le daria 27 juicios al estrato A --margen de
+-19 puntos, inservible-- por medir bien la precision de las 8 653, que nadie
va a usar. El reparto 120/65/65 da +-8.9 en el entregable y +-7.8 en el global
ponderado.

**La estimacion global es la suma ponderada por el tamano de cada estrato, no
el promedio de los tres.** Es el error facil de este metodo y tiene prueba.

LO QUE ESTE ARCHIVO NO HACE, A PROPOSITO
----------------------------------------
- **No lee el patron de oro ni dice si la arista esta en el.** Si el juez ve
  que la relacion es conocida, contesta `si` por reconocimiento y la medicion
  se vuelve circular. Hay una prueba que falla si alguien agrega esa columna.
- **No muestra la probabilidad del modelo junto a la oracion**, porque ancla el
  juicio.
- **No ordena por estrato ni por confianza.** La muestra sale barajada: si las
  120 del estrato A vinieran seguidas, el juez cambiaria de criterio al pasar
  al siguiente bloque, y la fatiga sesga hacia contestar `si` por inercia.

Solo biblioteca estandar.

    python etapa2/muestrear_precision.py                      # prepara la muestra
    python etapa2/muestrear_precision.py --resumir            # cuando este llena
"""

import argparse
import collections
import csv
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grn_comun import procedencia      # noqa: E402


# Criterio de cada estrato. El orden importa: se evalua de arriba abajo y la
# primera que case manda.
def estrato_de(fila):
    con_signo = fila["signo"] != "regulates"
    fuerte = (int(fila["n_articulos"] or 0) >= 3
              and fila.get("conflicto") != "true")
    if con_signo and fuerte:
        return "A"
    if con_signo:
        return "B"
    return "C"


ESTRATOS = ("A", "B", "C")

DESCRIPCION = {
    "A": "con signo, 3+ articulos, sin conflicto (el entregable)",
    "B": "con signo, evidencia mas debil",
    "C": "sin signo resuelto (regulates)",
}

REPARTO = {"A": 120, "B": 65, "C": 65}

# El vocabulario del veredicto. Se imprime en la cabecera del TSV para que
# quien juzga no tenga que buscarlo en otro lado.
VEREDICTOS = collections.OrderedDict([
    ("si", "la evidencia afirma la relacion CON ESE SIGNO"),
    ("signo_mal", "la relacion esta, pero el signo esta al reves"),
    ("sin_signo", "hay relacion, la evidencia no resuelve el signo"),
    ("no", "la evidencia no afirma ninguna relacion regulatoria"),
    ("no_se", "no se puede decidir con lo que hay"),
])

# Que cuenta como acierto, y depende del estrato. En A y B el sistema AFIRMO un
# signo, asi que 'sin_signo' es sobreafirmacion y cuenta como error. En C el
# sistema dijo 'regulates', o sea que no se comprometio: ahi 'sin_signo' es
# exactamente lo que el sistema dijo, y acierta.
ACIERTOS = {"A": {"si"}, "B": {"si"}, "C": {"si", "sin_signo"}}

# 'no_se' sale del denominador y se reporta aparte: no es un error del sistema,
# es una fila donde el juicio no se pudo emitir. Si son muchas, el problema
# esta en el diseno de la tarea y no en el pipeline.
FUERA_DEL_DENOMINADOR = {"no_se", ""}

COLUMNAS = ["id", "estrato", "tf", "blanco", "signo", "n_articulos",
            "n_evidencias", "confianza", "pmid", "seccion", "oracion",
            "pmid_2", "oracion_2", "pmid_3", "oracion_3",
            "veredicto", "nota"]

Z = 1.959963984540054                   # 95%


def wilson(exitos, n, z=Z):
    """Intervalo de Wilson. Devuelve (baja, alta), o (None, None) si n=0.

    Se usa este y no el normal porque con n de 65 y proporciones que pueden
    acercarse a 0 o a 1, el normal se sale del [0,1] y da intervalos que no
    existen. El de Wilson no.
    """
    if n <= 0:
        return (None, None)
    p = float(exitos) / n
    d = 1.0 + z * z / n
    centro = (p + z * z / (2.0 * n)) / d
    medio = (z / d) * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return (max(0.0, centro - medio), min(1.0, centro + medio))


def leer_tsv(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def evidencias_por_arista(ruta, max_por_arista=3):
    """{(tf,blanco): [fila, ...]} con hasta N evidencias de PMIDs DISTINTOS.

    De artículos distintos a proposito: tres oraciones del mismo articulo dicen
    lo mismo con otras palabras y no ayudan a decidir. Tres de tres articulos
    son tres testimonios.
    """
    por = collections.defaultdict(list)
    vistos = collections.defaultdict(set)
    for r in leer_tsv(ruta):
        k = (r["tf"], r["blanco"])
        if len(por[k]) >= max_por_arista:
            continue
        if r["pmid"] in vistos[k]:
            continue
        vistos[k].add(r["pmid"])
        por[k].append(r)
    return por


# ------------------------------------------------------------------ muestrear

def muestrear(red, reparto, semilla):
    """Sortea sin reemplazo dentro de cada estrato. Devuelve (filas, censo)."""
    por_estrato = collections.defaultdict(list)
    for r in red:
        por_estrato[estrato_de(r)].append(r)

    censo = dict((e, len(por_estrato[e])) for e in ESTRATOS)
    rnd = random.Random(semilla)
    elegidas = []
    for e in ESTRATOS:
        pila = sorted(por_estrato[e], key=lambda r: (r["tf"], r["blanco"]))
        n = min(reparto.get(e, 0), len(pila))
        for r in rnd.sample(pila, n):
            elegidas.append((e, r))

    # Barajado final: el juez no debe poder anticipar de que estrato viene la
    # siguiente fila. Con las 120 del estrato A seguidas, el criterio deriva al
    # cambiar de bloque.
    rnd.shuffle(elegidas)
    return elegidas, censo


def escribir_muestra(elegidas, evidencias, ruta):
    filas = []
    for i, (e, r) in enumerate(elegidas, 1):
        ev = evidencias.get((r["tf"], r["blanco"]), [])
        fila = {
            "id": "%03d" % i,
            "estrato": e,
            "tf": r["tf"],
            "blanco": r["blanco"],
            "signo": r["signo"],
            "n_articulos": r["n_articulos"],
            "n_evidencias": r["n_evidencias"],
            "confianza": r["confianza"],
            "veredicto": "",
            "nota": "",
        }
        for j in range(3):
            suf = "" if j == 0 else "_%d" % (j + 1)
            d = ev[j] if j < len(ev) else None
            if j == 0:
                fila["pmid"] = d["pmid"] if d else ""
                fila["seccion"] = d["seccion"] if d else ""
                fila["oracion"] = " ".join(d["oracion"].split()) if d else ""
            else:
                fila["pmid" + suf] = d["pmid"] if d else ""
                fila["oracion" + suf] = (" ".join(d["oracion"].split())
                                         if d else "")
        filas.append(fila)

    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter="\t",
                           extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    return filas


# -------------------------------------------------------------------- resumir

def resumir(muestra, censo, salida=print):
    """Precision por estrato y global ponderada. Devuelve el dict del resumen."""
    por_estrato = collections.defaultdict(list)
    for r in muestra:
        por_estrato[r["estrato"]].append(r)

    total_red = sum(censo.get(e, 0) for e in ESTRATOS)
    resumen = collections.OrderedDict()
    resumen["que_es"] = (
        "Precision medida por muestreo estratificado con juicio humano. La "
        "estimacion global es la suma ponderada por el tamano de cada estrato, "
        "NO el promedio de los tres.")
    resumen["aristas_en_la_red"] = total_red
    resumen["por_estrato"] = collections.OrderedDict()

    p_global = 0.0
    var_global = 0.0
    faltan_total = 0
    hay_todo = True

    salida("")
    salida("%-8s %-46s %6s %7s %8s  %s"
           % ("estrato", "que es", "N", "juzgadas", "aciertos", "precision (IC 95%)"))
    salida("-" * 108)

    for e in ESTRATOS:
        filas = por_estrato.get(e, [])
        N = censo.get(e, 0)
        faltan = sum(1 for r in filas
                     if (r.get("veredicto") or "").strip() == "")
        faltan_total += faltan
        usables = [r for r in filas
                   if (r.get("veredicto") or "").strip()
                   not in FUERA_DEL_DENOMINADOR]
        n = len(usables)
        ok = sum(1 for r in usables
                 if (r["veredicto"] or "").strip() in ACIERTOS[e])
        p = (float(ok) / n) if n else None
        baja, alta = wilson(ok, n)

        detalle = collections.Counter((r.get("veredicto") or "").strip()
                                      for r in filas)
        resumen["por_estrato"][e] = collections.OrderedDict([
            ("que_es", DESCRIPCION[e]),
            ("aristas", N),
            ("peso", round(float(N) / total_red, 4) if total_red else None),
            ("sorteadas", len(filas)),
            ("sin_juzgar", faltan),
            ("en_el_denominador", n),
            ("aciertos", ok),
            ("precision", round(p, 4) if p is not None else None),
            ("ic95", [round(baja, 4), round(alta, 4)]
             if baja is not None else None),
            ("veredictos", dict(detalle)),
        ])

        salida("%-8s %-46s %6d %7d %8d  %s"
               % (e, DESCRIPCION[e][:46], N, n, ok,
                  ("%.1f%%  [%.1f, %.1f]" % (100 * p, 100 * baja, 100 * alta))
                  if p is not None else "sin datos"))

        # Un estrato que no existe en la red pesa cero y no estorba. Uno que
        # existe pero no se ha juzgado si impide ponderar: sin su precision no
        # se puede componer la global, y publicarla sin el seria inventarse la
        # parte que falta.
        if N == 0:
            continue
        if p is None:
            hay_todo = False
            continue
        W = float(N) / total_red
        p_global += W * p
        # Con correccion por poblacion finita: se muestrea sin reemplazo de un
        # estrato de tamano N, asi que la varianza es menor que la binomial.
        fpc = max(0.0, 1.0 - float(n) / N) if N else 1.0
        var_global += (W * W) * (p * (1.0 - p) / n) * fpc

    if hay_todo:
        se = math.sqrt(var_global)
        lo, hi = max(0.0, p_global - Z * se), min(1.0, p_global + Z * se)
        resumen["global_ponderada"] = collections.OrderedDict([
            ("precision", round(p_global, 4)),
            ("ic95", [round(lo, 4), round(hi, 4)]),
            ("nota", "ponderada por el tamano de cada estrato, con correccion "
                     "por poblacion finita"),
        ])
        salida("-" * 108)
        salida("%-8s %-46s %6d %7s %8s  %.1f%%  [%.1f, %.1f]"
               % ("GLOBAL", "ponderada por tamano de estrato", total_red, "", "",
                  100 * p_global, 100 * lo, 100 * hi))

    # El desglose de errores, que es lo que el comite pregunto: no es lo mismo
    # una arista inventada que una con el signo al reves.
    todos = collections.Counter((r.get("veredicto") or "").strip()
                                for r in muestra)
    resumen["veredictos"] = dict(todos)
    resumen["sin_juzgar"] = faltan_total
    salida("")
    salida("  veredictos emitidos:")
    for v, d in VEREDICTOS.items():
        salida("    %-10s %4d   %s" % (v, todos.get(v, 0), d))
    if faltan_total:
        salida("")
        salida("  FALTAN %d filas por juzgar de %d. Las cifras de arriba son "
               "parciales." % (faltan_total, len(muestra)))
    nose = todos.get("no_se", 0)
    if nose and len(muestra):
        salida("")
        salida("  %d 'no_se' (%.0f%%). Si pasa del 10%%, el problema esta en "
               "como esta planteado" % (nose, 100.0 * nose / len(muestra)))
        salida("  el juicio y no en el pipeline: hay que revisar la evidencia "
               "que se le da al juez.")
    return resumen


# ----------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Muestrea la red para medir precision con juicio humano.")
    ap.add_argument("--red", default="datos_etapa2/red.tsv")
    ap.add_argument("--evidencias", default="datos_etapa2/red_evidencias.tsv")
    ap.add_argument("--salida", default="datos_etapa2/muestra_precision.tsv")
    ap.add_argument("--resumen", default="datos_etapa2/precision.json")
    ap.add_argument("--red-informe", default="datos_etapa2/red_informe.json")
    ap.add_argument("--semilla", type=int, default=20260827)
    for e in ESTRATOS:
        ap.add_argument("--n-%s" % e.lower(), type=int, default=REPARTO[e],
                        help="juicios del estrato %s (%s)" % (e, DESCRIPCION[e]))
    ap.add_argument("--resumir", action="store_true",
                    help="leer la muestra ya juzgada y publicar las cifras")
    args = ap.parse_args(argv)

    reparto = dict((e, getattr(args, "n_%s" % e.lower())) for e in ESTRATOS)

    if not os.path.exists(args.red):
        sys.exit("No encuentro %s. Corre antes etapa2/red.py" % args.red)
    red = leer_tsv(args.red)
    censo = collections.Counter(estrato_de(r) for r in red)

    if args.resumir:
        if not os.path.exists(args.salida):
            sys.exit("No encuentro %s. Preparala primero sin --resumir."
                     % args.salida)
        # Mismo guardian que las evaluaciones: unos juicios hechos sobre una red
        # y aplicados a otra dan una precision que no es de nadie.
        if not procedencia.exigir(args.red_informe, {"red": args.red}):
            return 1
        muestra = leer_tsv(args.salida)
        malos = sorted(set((r.get("veredicto") or "").strip() for r in muestra)
                       - set(VEREDICTOS) - {""})
        if malos:
            sys.exit("Veredictos que no existen en la muestra: %s.\nLos "
                     "validos son: %s" % (", ".join(malos),
                                          ", ".join(VEREDICTOS)))
        resumen = resumir(muestra, censo)
        resumen["red"] = args.red
        resumen["huellas"] = procedencia.sellar({"red": args.red,
                                                 "muestra": args.salida})
        with open(args.resumen, "w", encoding="utf-8") as f:
            json.dump(resumen, f, ensure_ascii=False, indent=2)
        print("")
        print("Escrito %s" % args.resumen)
        return 0

    if not os.path.exists(args.evidencias):
        sys.exit("No encuentro %s. Corre antes etapa2/red.py" % args.evidencias)

    print("Red: %d aristas" % len(red))
    for e in ESTRATOS:
        print("  %s  %-46s %6d" % (e, DESCRIPCION[e], censo.get(e, 0)))

    elegidas, censo_d = muestrear(red, reparto, args.semilla)
    evid = evidencias_por_arista(args.evidencias)
    filas = escribir_muestra(elegidas, evid, args.salida)

    sin_ev = sum(1 for f in filas if not f["oracion"])
    print("")
    print("Muestra de %d aristas -> %s" % (len(filas), args.salida))
    for e in ESTRATOS:
        n = sum(1 for f in filas if f["estrato"] == e)
        N = censo.get(e, 0)
        lo, hi = wilson(int(round(0.5 * n)), n)
        margen = (hi - lo) / 2 if lo is not None else 0
        print("  %s  %3d de %5d   margen esperado +-%.1f pp" % (e, n, N, 100 * margen))
    if sin_ev:
        print("  AVISO: %d filas sin oracion de evidencia; revisa %s"
              % (sin_ev, args.evidencias))

    with open(args.resumen.replace(".json", "_muestra.json"), "w",
              encoding="utf-8") as f:
        json.dump({"semilla": args.semilla, "reparto": reparto,
                   "censo": dict(censo_d),
                   "huellas": procedencia.sellar({"red": args.red,
                                                  "evidencias": args.evidencias})},
                  f, ensure_ascii=False, indent=2)

    print("")
    print("Ahora hay que llenar la columna 'veredicto'. Los valores validos:")
    for v, d in VEREDICTOS.items():
        print("   %-10s %s" % (v, d))
    print("")
    print("Se puede parar y seguir: las filas vacias se ignoran y el resumen")
    print("dice cuantas faltan. Conviene juzgar las primeras 20, revisarlas, y")
    print("ajustar el criterio antes de gastar las otras %d." % max(len(filas) - 20, 0))
    print("")
    print("Cuando este llena:")
    print("   python etapa2/muestrear_precision.py --resumir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
