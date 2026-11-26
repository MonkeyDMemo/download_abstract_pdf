# -*- coding: utf-8 -*-
"""La red del lector por artículo contra el patrón de oro propio.

Es la medición de **desarrollo** del agente curador (`docs/agente-curador.md`,
fase 2): con ella se ajusta el prompt y se elige el modelo. No es la prueba:
la prueba es contra la base curada, una vez, en el servidor.

    python etapa2/evaluar_curador.py \\
        --relaciones salidas/ouroboros/curador/v0_qwen235b/relaciones.tsv \\
        --carpeta salidas/flujo/corrida27_run22 [--resumen J]

Es un **evaluador**, con la condición de la lista blanca de
`test_contaminacion.py`: nadie lo importa, no escribe ningún archivo que el
pipeline consuma y su salida es un informe. Abre el patrón para medir; el
lector (`grn_ouroboros.curador`) y su prompt no lo abren ni lo nombran.

Qué hace
========
1. Arma la red del lector con `red_curador.py` (una arista por par de
   nodos, un voto por artículo y efecto, el signo de la regla de mayoría de
   `red.py`).
2. La evalúa con las funciones de `evaluar_oro.py` (`evaluar`, `metricas`),
   las mismas que evalúan la red del paso 2: mismo patrón, mismos alias, misma
   equivalencia operón-gen.
3. Evalúa igual la red de `--carpeta` y la unión de las dos, y las pone lado
   a lado.

La unión es la de `red_curador.unir`: las aristas de las dos redes; donde la
red del paso 2 no trae signo y el curador sí, vale el del curador; donde las
dos lo traen, vale el de la red del paso 2, que es la que ya está medida.

Qué NO dice
===========
Como `evaluar_oro.py`: da exhaustividad y acierto de signo, **no precisión**.
El patrón no dice qué relaciones son falsas. Además, los artículos de
`--relaciones` son los que el propio patrón cita: la exhaustividad del curador
aquí es «de lo que el patrón dice que está en estos artículos, cuánto leyó»,
no la de todo el corpus.

Solo biblioteca estándar.
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluar_oro as O     # noqa: E402
import red_curador as RC   # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


def medir(oro, red, indice_pares, diccionario, operones, disputadas):
    """Los conteos de una red sobre las filas del denominador honesto."""
    todas, _ambiguas = O.evaluar(
        oro, O.expandir_red(red, operones),
        O.expandir_red(red, operones, laxa=True), indice_pares, diccionario,
        operones, disputadas)
    honestas = [f for f in todas if f["en_denominador_honesto"] == "true"]
    m = O.metricas(honestas)
    veredictos = collections.Counter(f["veredicto"] for f in honestas)
    return collections.OrderedDict([
        ("aristas", len(red)),
        ("filas", len(honestas)),
        ("recuperadas", sum(1 for f in honestas if f["_recuperada"])),
        ("con_signo_comparable", m["acierto_signo"]["d"]),
        ("signo_correcto", m["acierto_signo"]["n"]),
        ("signo_mal", veredictos["recuperada_signo_mal"]),
        ("sin_signo", veredictos["recuperada_sin_signo"]),
        ("por_subsistema", collections.OrderedDict(
            (s, "%d/%d" % (sum(1 for f in honestas
                               if f["subsistema"] == s and f["_recuperada"]),
                           sum(1 for f in honestas if f["subsistema"] == s)))
            for s in sorted(set(f["subsistema"] for f in honestas)))),
    ]), honestas


def en_su_articulo(oro, honestas, validas, operones):
    """De las filas del denominador honesto con artículos, en cuántas el
    curador da el par leyendo **alguno de los artículos que el patrón cita
    para ella**. (n, d). `honestas` son las filas que devolvió `medir`."""
    cuentan = set((f["tf"], f["blanco"]) for f in honestas)
    por_pmid = collections.defaultdict(list)
    for fila in validas:
        por_pmid[fila["pmid"]].append(fila)
    n = d = 0
    for fila in oro:
        if (fila["tf"], fila["blanco"]) not in cuentan:
            continue
        pmids = [p.strip() for p in fila["pmids"].replace(";", "|")
                 .replace(",", "|").split("|") if p.strip()]
        if not pmids:
            continue
        d += 1
        propias = [r for p in pmids for r in por_pmid.get(p, [])]
        alias_tf, alias_bl, _amb = O.alias_anclados(fila["alias"], fila["tf"],
                                                    fila["blanco"])
        claves_tf, _, _ = O.claves_extremo(fila["tf"], alias_tf, operones)
        claves_bl, _, _ = O.claves_extremo(fila["blanco"], alias_bl, operones)
        arista, _clase = O.buscar_arista(
            claves_tf, claves_bl,
            O.expandir_red(RC.red_del_curador(propias), operones))
        n += arista is not None
    return n, d


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="La red del lector por artículo contra el patrón de oro "
                    "propio (desarrollo).")
    ap.add_argument("--relaciones", required=True,
                    help="El relaciones.tsv de `grn_ouroboros.cli curar`.")
    ap.add_argument("--carpeta", required=True,
                    help="La carpeta del flujo con la red del paso 2 contra "
                         "la que se compara (red.tsv y pares.jsonl).")
    ap.add_argument("--genes", default=os.path.join(AQUI, "genes_pao1.tsv"))
    ap.add_argument("--operones",
                    default=os.path.join(AQUI, "operones_pao1.tsv"))
    ap.add_argument("--oro", default=os.path.join(AQUI, "oro_pseudomonas.tsv"))
    ap.add_argument("--mayoria", type=float, default=0.66)
    ap.add_argument("--resumen", default=None, help="JSON con los conteos.")
    args = ap.parse_args(argv)

    oro = O.cargar_oro(args.oro)
    diccionario, info = O.cargar_diccionario(args.genes)
    O.revisar_procedencia(info)
    operones, _hay = O.cargar_operones(args.operones)
    indice_pares = O.cargar_pares(os.path.join(args.carpeta, "pares.jsonl"),
                                  operones)[0]
    disputadas, _origen = O.cargar_disputadas(None, oro)
    _filas, red = O.cargar_red(os.path.join(args.carpeta, "red.tsv"))
    validas = RC.leer_validas(args.relaciones)
    curador = RC.red_del_curador(validas, args.mayoria)

    resultado = collections.OrderedDict()
    filas_de = {}
    for nombre, una in (("red", red), ("curador", curador),
                        ("union", RC.unir(red, curador))):
        resultado[nombre], filas_de[nombre] = medir(
            oro, una, indice_pares, diccionario, operones, disputadas)
    por_red = dict(((f["tf"], f["blanco"]), f) for f in filas_de["red"])
    solo_curador = sum(1 for f in filas_de["curador"] if f["_recuperada"]
                       and not por_red[(f["tf"], f["blanco"])]["_recuperada"])
    gana_signo = sum(
        1 for f in filas_de["curador"] if f["_acierto"]
        and por_red[(f["tf"], f["blanco"])]["veredicto"]
        == "recuperada_sin_signo")
    n, d = en_su_articulo(oro, filas_de["curador"], validas, operones)
    resultado["curador_frente_a_la_red"] = collections.OrderedDict([
        ("articulos_leidos_con_relacion_valida",
         len(set(f["pmid"] for f in validas))),
        ("relaciones_validas", len(validas)),
        ("aristas_que_la_red_no_tiene",
         sum(1 for k in curador if k not in red)),
        ("filas_del_oro_que_solo_recupera_el_curador", solo_curador),
        ("filas_sin_signo_en_la_red_con_signo_correcto_del_curador",
         gana_signo),
        ("filas_recuperadas_en_un_articulo_que_el_oro_cita", "%d/%d" % (n, d)),
    ])
    for nombre in ("red", "curador", "union"):
        r = resultado[nombre]
        print("%-8s aristas %6d | recupera %3d/%d | signo correcto %3d de "
              "%3d comparables, mal %d, sin signo %d"
              % (nombre, r["aristas"], r["recuperadas"], r["filas"],
                 r["signo_correcto"], r["con_signo_comparable"],
                 r["signo_mal"], r["sin_signo"]))
    for clave, valor in resultado["curador_frente_a_la_red"].items():
        print("  %s: %s" % (clave, valor))
    if args.resumen:
        O.escribir_json(args.resumen, resultado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
