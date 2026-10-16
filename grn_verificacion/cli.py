"""CLI del paso 2. Parsea, llama y formatea; la lógica vive en los módulos.

    python -m grn_verificacion.cli pares --bronce CSV --carpeta DIR [--limite N]
    python -m grn_verificacion.cli biobert --carpeta DIR --modelo DIR [--reusar-de DIR]
    python -m grn_verificacion.cli capa --carpeta DIR --bronce CSV [--sintaxis JSONL]
    python -m grn_verificacion.cli evaluar --carpeta DIR --bronce CSV
    python -m grn_verificacion.cli datos-entrenamiento --pares JSONL --base XLSX ...

Lo normal es no llamarlo a mano: `python flujo.py` corre los pasos en orden y
se salta lo que ya está hecho.
"""

import argparse
import json
import os
import re
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

log = print


def _etiqueta_modelo(modelo):
    nombre = os.path.basename(os.path.normpath(modelo))
    m = re.search(r"run_?(\d+)", nombre)
    return "run%s" % m.group(1) if m else nombre


def _rel(ruta):
    """Relativa a la raíz, con `/`; absoluta si está en otra unidad de
    Windows, donde `os.path.relpath` lanza ValueError y tumbaba el paso."""
    absoluta = os.path.abspath(ruta)
    try:
        return os.path.relpath(absoluta, _RAIZ).replace(os.sep, "/")
    except ValueError:
        return absoluta.replace(os.sep, "/")


def cmd_pares(args):
    from grn_verificacion import puente
    puente.construir_pares(args.bronce, args.carpeta, limite=args.limite,
                           log=log)
    return 0


def _corrida_bronce_de(carpeta):
    with open(os.path.join(carpeta, "pares.jsonl"), encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                return json.loads(linea).get("corrida_bronce")
    return None


def cmd_biobert(args):
    from grn_bronce import db as bdb, rutas
    from grn_verificacion import puente

    modelo = os.path.abspath(args.modelo)
    reusar = args.reusar_de or []
    # Una sola vez: huellea los pesos (cientos de MB).
    firma = puente.firma_del_modelo(modelo)
    con = None
    corrida_id = None
    if not args.sin_registrar:
        # Toda corrida de procesamiento deja su fila ANTES de procesar
        # (CLAUDE.md). Es una fila del paso 2 en la misma tabla `corridas`:
        # `ultima_corrida()` filtra por paso, así que no confunde al bronce.
        corrida_bronce = _corrida_bronce_de(args.carpeta)
        con = bdb.conectar(os.path.join(rutas.raiz_datos(args.datos),
                                        "grn.db"))
        fila_bronce = bdb.corrida(con, corrida_bronce) \
            if corrida_bronce is not None else None
        # El método dice «run22» para cualquier checkpoint de esa receta; lo
        # que distingue a uno de otro es la firma, con la huella de los pesos.
        corrida_id = bdb.abrir_corrida(
            con, "2", "biobert-%s" % _etiqueta_modelo(modelo), "1",
            {"corrida_bronce": corrida_bronce,
             "modelo": _rel(modelo),
             "sha1_config": firma["sha1_config"],
             "huellas_modelo": firma["huellas_modelo"],
             "carpeta": _rel(args.carpeta),
             "umbrales": {"activates": 0.65, "represses": 0.70,
                          "regulates": 0.60},
             "reusar_de": [_rel(d) for d in reusar],
             "sin_cache": bool(args.sin_cache)},
            fila_bronce["corpus_id"] if fila_bronce is not None else None)
        log("Corrida %d del paso 2 registrada." % corrida_id)
    try:
        r = puente.clasificar_pares(args.carpeta, modelo, python=args.python,
                                    reusar_de=reusar, log=log,
                                    usar_cache=not args.sin_cache,
                                    firma=firma)
    except BaseException as e:
        if con is not None:
            bdb.cerrar_corrida(con, corrida_id, "error", str(e))
            con.close()
        raise
    if con is not None:
        n = r.get("reutilizadas", 0) + r.get("nuevas", 0)
        bdb.cerrar_corrida(con, corrida_id, "ok", None, n, n)
        con.close()
    log("Reutilizadas %d, clasificadas %d." % (r.get("reutilizadas", 0),
                                               r.get("nuevas", 0)))
    return 0


def cmd_capa(args):
    from grn_verificacion import capa
    capa.escribir_capa(args.carpeta, args.bronce, ruta_sintaxis=args.sintaxis,
                       log=log)
    return 0


def cmd_evaluar(args):
    from grn_verificacion import evaluar
    evaluar.evaluar_carpeta(args.carpeta, args.bronce, log=log)
    return 0


def cmd_datos_entrenamiento(args):
    from grn_verificacion import entrenamiento
    # `ejecutar` ya reporta por `log`, y solo conteos: la base curada y lo que
    # sale de ella no se imprimen nunca.
    try:
        entrenamiento.desde_argumentos(args, log=log)
    except ValueError as e:
        log("ERROR: %s" % e)
        return 1
    return 0


def cmd_reservas(args):
    """El archivo de lo que no entra al entrenamiento: los PMIDs de la muestra
    de 50 juicios (con ella se recalcula el 44 %) y, si se da, las oraciones del
    conjunto ciego de la trampa del signo."""
    import csv
    from grn_bronce.texto import normalizar_espacios
    from grn_verificacion import entrenamiento
    oraciones = []
    if args.ciego:
        # El conjunto ciego es un TSV con columna `oracion`; se reserva por
        # oración porque no trae PMID.
        with open(args.ciego, encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f, delimiter="	"):
                texto = normalizar_espacios(fila.get("oracion") or "")
                if texto:
                    oraciones.append(texto)
    os.makedirs(os.path.dirname(os.path.abspath(args.salida)), exist_ok=True)
    # Se reporta lo que quedó escrito, no lo leído: la muestra de 50 juicios
    # trae 46 PMIDs distintos, y las 198 filas del conjunto ciego son 182
    # oraciones distintas. Son las cifras que va a repetir `datos-entrenamiento`.
    escritas = entrenamiento.escribir_reservas_de_juicios(
        args.salida, oraciones_extra=oraciones)
    log("Reservas escritas en %s: %d PMIDs de la muestra de juicios y %d "
        "oraciones distintas del conjunto ciego (%d filas)."
        % (args.salida, escritas["pmids"], escritas["oraciones"],
           len(oraciones)))
    return 0


def consola_tolerante():
    """La consola de Windows imprime cp1252: los acentos caben, pero la barra
    de progreso de transformers («█») o una sigma no, y un `print` con ellos
    tumbaba la corrida entera desde el padre. Se reemplaza lo que no cabe en
    vez de reventar; los archivos de datos se escriben siempre en UTF-8."""
    for flujo_salida in (sys.stdout, sys.stderr):
        if hasattr(flujo_salida, "reconfigure"):
            flujo_salida.reconfigure(errors="replace")


def main(argv=None):
    consola_tolerante()
    ap = argparse.ArgumentParser(prog="grn_verificacion.cli",
                                 description="Paso 2: verificación.")
    sub = ap.add_subparsers(dest="sub", required=True)

    pa = sub.add_parser("pares", help="Pares marcados desde el bronce.")
    pa.add_argument("--bronce", required=True,
                    help="CSV de oraciones candidatas del bronce.")
    pa.add_argument("--carpeta", required=True)
    pa.add_argument("--limite", type=int, default=None)
    pa.set_defaults(func=cmd_pares)

    bb = sub.add_parser("biobert", help="Clasificar los pares con BioBERT.")
    bb.add_argument("--carpeta", required=True)
    bb.add_argument("--modelo", required=True)
    bb.add_argument("--python", default=None,
                    help="Intérprete con torch y transformers.")
    bb.add_argument("--reusar-de", dest="reusar_de", action="append",
                    help="Carpeta con predicciones del mismo modelo.")
    bb.add_argument("--datos", default=None,
                    help="Raíz de datos; gana sobre GRN_DATOS.")
    bb.add_argument("--sin-registrar", dest="sin_registrar",
                    action="store_true",
                    help="No dejar fila en `corridas` (pruebas rápidas).")
    bb.add_argument("--sin-cache", dest="sin_cache", action="store_true",
                    help="Clasificar todo de nuevo: ni las predicciones de "
                         "la carpeta, ni su caché, ni otras carpetas.")
    bb.set_defaults(func=cmd_biobert)

    ca = sub.add_parser("capa", help="La capa: oración, funciones, operones "
                                     "y BioBERT.")
    ca.add_argument("--carpeta", required=True)
    ca.add_argument("--bronce", required=True)
    ca.add_argument("--sintaxis", default=None)
    ca.set_defaults(func=cmd_capa)

    ev = sub.add_parser("evaluar", help="Recalcula el 44 %% con BioBERT.")
    ev.add_argument("--carpeta", required=True)
    ev.add_argument("--bronce", required=True)
    ev.set_defaults(func=cmd_evaluar)

    from grn_verificacion import entrenamiento
    de = sub.add_parser("datos-entrenamiento",
                        help="Datos de entrenamiento desde la base curada "
                             "(se corre en la máquina donde vive la base).")
    entrenamiento.agregar_argumentos(de)
    de.set_defaults(func=cmd_datos_entrenamiento)

    rs = sub.add_parser("reservas",
                        help="Lo que no entra al entrenamiento: la muestra "
                             "de 50 y el conjunto ciego.")
    rs.add_argument("--salida",
                    default=os.path.join("salidas", "flujo", "reservas.tsv"))
    rs.add_argument("--ciego", default=None,
                    help="TSV con columna `oracion` (datos_etapa2/ciego_198.tsv).")
    rs.set_defaults(func=cmd_reservas)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
