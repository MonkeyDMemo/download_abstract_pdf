"""CLI del paso 3. Parsea, llama y formatea; la lógica vive en `paquete.py` y
en `consolidar.py`.

    python -m grn_red.cli consolidar --carpeta salidas/flujo/corrida4_run22
    python -m grn_red.cli consolidar --carpeta ... --perfil recomendado
    python -m grn_red.cli paquete --carpeta salidas/flujo/corrida4_run22

Lo normal es no llamarlo a mano: `python flujo.py` corre `consolidar` en los
pasos «red» (por omisión, la red de `etapa2/red.py`) y «red_recomendada», y
`paquete` al final, después de la evaluación; se los salta si nada cambió.
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


def cmd_consolidar(args):
    from grn_red import consolidar
    try:
        cfg = consolidar.configuracion(
            args.perfil, autorregulacion=args.autorregulacion,
            nivel_soporte=args.nivel_soporte, operones=args.operones,
            mayoria=args.mayoria, umbrales=args.umbrales,
            min_evidencias=args.min_evidencias,
            min_articulos=args.min_articulos)
        resumen = consolidar.consolidar(args.carpeta, cfg, nombre=args.nombre,
                                        log=log)
    except consolidar.ErrorConsolidar as e:
        # Una entrada que falta o un parámetro que no vale: el mensaje dice
        # qué hacer, y un traceback lo taparía.
        log("ERROR: %s" % e)
        return 1
    if resumen["nombre"] is None:
        log("Red por omisión (la de etapa2/red.py) en %s."
            % ", ".join(resumen["archivos"]))
    else:
        log("Red «%s» lista: %s. red.tsv no se tocó."
            % (resumen["nombre"], ", ".join(resumen["archivos"])))
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
    cs = sub.add_parser(
        "consolidar",
        help="La red con las reglas de consolidación como parámetros. Por "
             "omisión, la de etapa2/red.py en red.tsv; con otras reglas, en "
             "red_<nombre>.tsv, sin tocar red.tsv.")
    cs.add_argument("--carpeta", required=True,
                    help="Carpeta del flujo con predicciones.jsonl, "
                         "predicciones_meta.json y pares.jsonl.")
    cs.add_argument("--perfil", default="omision",
                    choices=["omision", "recomendado"],
                    help="omision: la de red.py. recomendado: autorregulación "
                         "marcada, nivel de soporte y operones expandidos.")
    cs.add_argument("--autorregulacion", default=None,
                    choices=["excluir", "marcar"])
    cs.add_argument("--nivel-soporte", dest="nivel_soporte",
                    action="store_const", const=True, default=None,
                    help="Columna nivel_soporte: candidata con un artículo, "
                         "soporte_multiple con dos o más.")
    cs.add_argument("--operones", default=None, choices=["nodo", "expandir"],
                    help="expandir: una arista por gen de cada blanco que es "
                         "operón del catálogo, con expandida_de; la del "
                         "operón se queda.")
    cs.add_argument("--mayoria", type=float, default=None,
                    help="La de red.py (0.66 por omisión).")
    cs.add_argument("--umbrales", default=None,
                    help="Un umbrales_sugeridos.json, como en red.py.")
    cs.add_argument("--min-evidencias", dest="min_evidencias", type=int,
                    default=None)
    cs.add_argument("--min-articulos", dest="min_articulos", type=int,
                    default=None)
    cs.add_argument("--nombre", default=None,
                    help="Las salidas van a red_<nombre>*.tsv/json "
                         "(recomendada, si las reglas no son las por "
                         "omisión).")
    cs.set_defaults(func=cmd_consolidar)
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
