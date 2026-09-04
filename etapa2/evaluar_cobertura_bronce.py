#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cuánto del patrón de oro llega siquiera a coocurrir en una oración candidata.

Es el **techo del paso 1**: de las relaciones canónicas, cuántas tienen sus dos
extremos juntos en al menos una oración que el bronce marcó como candidata. Lo
que no aparece aquí, el paso 2 no lo puede verificar, porque nunca lo va a ver.

POR QUÉ ESTE ARCHIVO VIVE EN etapa2 Y NO EN grn_bronce
======================================================
Porque abre el patrón de oro, y el paquete bronce no puede. La regla no es
burocracia: si la referencia con la que se evalúa entra en la lógica que
extrae, las métricas dejan de medir lo que el pipeline encuentra y pasan a
medir lo que le sopla la referencia, con la misma etiqueta y la misma pinta de
correcto. `test_contaminacion.py` lo vigila, y este script está en su lista
blanca **como evaluador**: no produce nada que el pipeline consuma, y su única
salida es un informe.

EL DENOMINADOR, Y POR QUÉ SON DOS
=================================
Se reportan los dos, y el orden importa.

- **El honesto (~169)**: relaciones atestiguadas, con signo resuelto y sin
  disputa. Salen del cómputo las 9 que el corpus no contiene, las 6 que el
  corpus no resuelve y las que se contradicen. Pedirle al pipeline que
  recupere una relación cuyo texto no está en el corpus es medir el corpus, no
  el pipeline.
- **Sobre las 190**: para comparar, y porque es el número que la gente cita.
  Siempre sale más bajo, y esa diferencia es justo lo que el denominador
  honesto explica.

Reportar solo el segundo esconde el trabajo; reportar solo el primero parece
que se elige el denominador que favorece. Van los dos, juntos.

    python3 etapa2/evaluar_cobertura_bronce.py [--corrida N]

Solo biblioteca estándar.
"""

import argparse
import collections
import io
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
sys.path.insert(0, _RAIZ)

import evaluar_oro as E                                  # noqa: E402
from grn_bronce import db as bronce_db                   # noqa: E402
from grn_bronce import rutas                             # noqa: E402


def claves_de(fila, operones):
    """Las claves de los dos extremos de una fila del oro.

    Se reusa la maquinaria de `evaluar_oro.py` en vez de escribir otra: si dos
    evaluaciones emparejaran distinto, sus números dejarían de ser comparables
    y nadie sabría cuál mirar.
    """
    alias_tf, alias_bl, _ = E.alias_anclados(
        fila["alias"], fila["tf"], fila["blanco"])
    ktf, _, _ = E.claves_extremo(fila["tf"], alias_tf, operones)
    kbl, _, _ = E.claves_extremo(fila["blanco"], alias_bl, operones)
    return (ktf["exacta"] | ktf["por_alias"] | ktf["por_operon"],
            kbl["exacta"] | kbl["por_alias"] | kbl["por_operon"])


def leer_bronce(con, corrida_id):
    """(por_unidad, vistas) de la corrida.

    `por_unidad` es {unidad candidata -> claves de gen que contiene} y `vistas`
    son todas las claves de gen que el bronce menciona en cualquier oración,
    candidata o no. La segunda hace falta para distinguir "el gen no aparece en
    el corpus" de "aparece pero nunca junto al otro", que son dos fallos
    distintos y solo uno es del paso 1.
    """
    por_unidad = collections.defaultdict(set)
    for f in con.execute(
            """SELECT m.unidad_id, m.texto, m.id_normalizado
                 FROM menciones m
                 JOIN oraciones_candidatas c ON c.unidad_id = m.unidad_id
                WHERE m.corrida_id = ? AND m.tipo IN ('gen','proteina')""",
            (corrida_id,)):
        por_unidad[f["unidad_id"]].add(E.clave(f["texto"]))
        if f["id_normalizado"]:
            por_unidad[f["unidad_id"]].add(E.clave(f["id_normalizado"]))

    vistas = set()
    for f in con.execute(
            """SELECT DISTINCT texto, id_normalizado FROM menciones
                WHERE corrida_id = ? AND tipo IN ('gen','proteina')""",
            (corrida_id,)):
        vistas.add(E.clave(f["texto"]))
        if f["id_normalizado"]:
            vistas.add(E.clave(f["id_normalizado"]))
    return por_unidad, vistas


def evaluar(oro, disputadas, operones, por_unidad, vistas):
    """Una fila de resultado por fila del oro."""
    salida = []
    for fila in oro:
        ktf, kbl = claves_de(fila, operones)
        par = (E.clave(fila["tf"]), E.clave(fila["blanco"]))

        tf_visto, bl_visto = bool(ktf & vistas), bool(kbl & vistas)

        # La autorregulación se decide ANTES de mirar la cobertura, y no
        # después. Si se mira después, una sola mención de `MexT` satisface los
        # dos extremos --son el mismo conjunto de claves-- y la fila sale
        # "cubierta" sin que el bronce haya emitido jamás ese par. Medido: eran
        # 10 filas contadas de más, el 5.7 % del denominador. El bronce exige
        # dos genes DISTINTOS por oración, así que `X -> x` no puede salir: no
        # es que no se encuentre, es que la regla lo excluye por construcción.
        autorregulacion = bool(ktf & kbl) or par[0] == par[1]
        cubierta = (not autorregulacion
                    and any((ktf & claves) and (kbl & claves)
                            for claves in por_unidad.values()))

        if cubierta:
            motivo = ""
        elif autorregulacion:
            motivo = "autorregulacion"
        elif not tf_visto and not bl_visto:
            motivo = "ningun_extremo_mencionado"
        elif not tf_visto or not bl_visto:
            motivo = "solo_un_extremo_mencionado"
        else:
            motivo = "mencionados_pero_nunca_juntos"

        salida.append({
            "tf": fila["tf"], "blanco": fila["blanco"],
            "signo": fila["signo"], "subsistema": fila["subsistema"],
            "atestiguado": fila["atestiguado"],
            "en_disputa": par in disputadas,
            "cubierta": cubierta, "motivo": motivo,
        })
    return salida


def es_del_denominador_honesto(r):
    """Atestiguada, con signo resuelto y sin disputa.

    Las tres condiciones son la misma idea: no se le puede exigir al pipeline
    que recupere lo que el corpus no dice, no resuelve o se contradice.
    """
    return (r["atestiguado"] == "true"
            and r["signo"] in ("activates", "represses")
            and not r["en_disputa"])


def informar(res, corrida_id, fuente_disputadas, log):
    honestas = [r for r in res if es_del_denominador_honesto(r)]
    cub_h = sum(1 for r in honestas if r["cubierta"])
    cub_t = sum(1 for r in res if r["cubierta"])

    log("=" * 72)
    log("COBERTURA DEL BRONCE SOBRE EL PATRON DE ORO   (corrida %d)"
        % corrida_id)
    log("=" * 72)
    log("")
    log("Que mide: de las relaciones canonicas, cuantas tienen sus DOS extremos")
    log("en al menos una oracion candidata. Es el techo del paso 1: lo que no")
    log("esta aqui, el paso 2 no lo puede verificar porque no lo va a ver.")
    log("")
    log("  Denominador honesto (atestiguada + signo resuelto + sin disputa)")
    log("    %d de %d   ->  %.1f %%" % (cub_h, len(honestas),
                                        100.0 * cub_h / len(honestas)))
    log("")
    log("  Sobre las %d filas del patron, para comparar" % len(res))
    log("    %d de %d   ->  %.1f %%" % (cub_t, len(res),
                                        100.0 * cub_t / len(res)))
    log("")
    log("  La diferencia entre los dos numeros es lo que el denominador")
    log("  honesto saca del computo, no una mejora del pipeline.")
    log("")

    fuera = collections.Counter()
    for r in res:
        if not es_del_denominador_honesto(r):
            if r["atestiguado"] != "true":
                fuera["no atestiguada: el corpus no la contiene"] += 1
            elif r["signo"] not in ("activates", "represses"):
                fuera["signo sin resolver en el corpus"] += 1
            else:
                fuera["en disputa: el corpus se contradice"] += 1
    log("  Por que salen %d filas del denominador honesto:" % (len(res) - len(honestas)))
    for motivo, n in sorted(fuera.items()):
        log("    %-46s %3d" % (motivo, n))
    log("    (las disputadas se detectaron por %s)" % fuente_disputadas)
    log("")

    perdidas = collections.Counter(r["motivo"] for r in honestas
                                   if not r["cubierta"])
    log("  Por que se pierden las %d del denominador honesto:"
        % (len(honestas) - cub_h))
    for motivo, n in perdidas.most_common():
        log("    %-46s %3d" % (motivo, n))
    log("")
    log("  Solo el ultimo motivo es fallo de la coocurrencia. Los dos primeros")
    log("  son limite del corpus o del diccionario, y la autorregulacion es una")
    log("  regla que el bronce todavia no tiene.")
    log("")

    auto = [r for r in res if r["motivo"] == "autorregulacion"]
    if auto:
        log("  Autorregulacion (mismo gen a los dos lados), %d filas:" % len(auto))
        for r in auto[:12]:
            log("    %s -> %s" % (r["tf"], r["blanco"]))
        log("")
    return {"corrida_id": corrida_id,
            "denominador_honesto": {"cubiertas": cub_h, "total": len(honestas)},
            "sobre_190": {"cubiertas": cub_t, "total": len(res)},
            "perdidas_por_motivo": dict(perdidas),
            "fuera_del_denominador": dict(fuera),
            "fuente_disputadas": fuente_disputadas}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=None,
                    help="Ruta de la base; gana sobre GRN_DATOS.")
    ap.add_argument("--oro", default=os.path.join(AQUI, "oro_pseudomonas.tsv"))
    ap.add_argument("--operones",
                    default=os.path.join(_RAIZ, "grn_bronce", "recursos",
                                         "operones_pao1.tsv"))
    ap.add_argument("--disputadas", default=None)
    ap.add_argument("--corrida", type=int, default=None,
                    help="Por omision, la ultima corrida 'ok' del bronce.")
    ap.add_argument("--salida", default=None, help="JSON con el resultado.")
    args = ap.parse_args(argv)

    ruta_db = args.db or os.path.join(rutas.raiz_datos(), "grn.db")
    if not os.path.exists(ruta_db):
        sys.exit("No existe la base %s." % ruta_db)

    oro = E.cargar_oro(args.oro)
    operones, _ = E.cargar_operones(args.operones)
    disputadas, fuente = E.cargar_disputadas(args.disputadas, oro)
    if len(disputadas) < E.DISPUTADAS_DOCUMENTADAS:
        print("AVISO: la documentacion habla de %d relaciones en disputa y solo "
              "se detectan %d. Las otras no estan nombradas en ninguna parte, "
              "asi que el denominador honesto sale %d filas mas grande de lo "
              "que deberia."
              % (E.DISPUTADAS_DOCUMENTADAS, len(disputadas),
                 E.DISPUTADAS_DOCUMENTADAS - len(disputadas)), flush=True)

    con = bronce_db.conectar(ruta_db)
    try:
        if args.corrida:
            corrida_id = args.corrida
        else:
            fila = con.execute(
                """SELECT id FROM corridas WHERE paso='1' AND estatus='ok'
                    ORDER BY id DESC LIMIT 1""").fetchone()
            if fila is None:
                sys.exit("No hay ninguna corrida del bronce terminada.")
            corrida_id = fila["id"]

        por_unidad, vistas = leer_bronce(con, corrida_id)
        if not por_unidad:
            sys.exit("La corrida %d no tiene oraciones candidatas con genes."
                     % corrida_id)
        res = evaluar(oro, disputadas, operones, por_unidad, vistas)
    finally:
        con.close()

    resumen = informar(res, corrida_id, fuente, lambda m: print(m, flush=True))
    if args.salida:
        tmp = args.salida + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(resumen, ensure_ascii=False, indent=2))
        os.replace(tmp, args.salida)
        print("Escrito %s" % args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
