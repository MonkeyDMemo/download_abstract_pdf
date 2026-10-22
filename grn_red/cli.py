"""CLI del paso 3. Parsea, llama y formatea; la lógica vive en `paquete.py`.

    python -m grn_red.cli paquete --carpeta salidas/flujo/corrida4_run22

Lo normal es no llamarlo a mano: `python flujo.py` lo corre al final, después de
la evaluación, y se lo salta si nada cambió.
"""

import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

log = print


def cmd_paquete(args):
    from grn_red import paquete
    try:
        manifiesto = paquete.empaquetar(args.carpeta, log=log)
    except paquete.ErrorPaquete as e:
        # Es una entrada que falta o que no es de esta corrida, no un defecto
        # del código: el mensaje dice qué paso correr, y un traceback lo
        # taparía.
        log("ERROR: %s" % e)
        return 1
    grafo = manifiesto["grafo"]
    log("Paquete listo: %d nodos y %d aristas; %d filas con colisión quedaron "
        "fuera del grafo (ver manifiesto.json)."
        % (grafo["n_nodos"], grafo["n_aristas"], grafo["n_colisiones"]))
    return 0


def consola_tolerante():
    """La consola de Windows imprime cp1252: los acentos caben, una sigma no.
    Se reemplaza lo que no cabe en vez de reventar a media salida."""
    for flujo_salida in (sys.stdout, sys.stderr):
        if hasattr(flujo_salida, "reconfigure"):
            flujo_salida.reconfigure(errors="replace")


def main(argv=None):
    consola_tolerante()
    ap = argparse.ArgumentParser(prog="grn_red.cli",
                                 description="Paso 3: la red como producto.")
    sub = ap.add_subparsers(dest="sub", required=True)
    pq = sub.add_parser(
        "paquete",
        help="nodos.tsv, red.graphml y manifiesto.json desde la red de una "
             "carpeta del flujo.")
    pq.add_argument("--carpeta", required=True,
                    help="Carpeta del flujo con red.tsv, red_evidencias.tsv, "
                         "red_informe.json, pares.jsonl y "
                         "predicciones_meta.json.")
    pq.set_defaults(func=cmd_paquete)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
