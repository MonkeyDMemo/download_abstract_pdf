# -*- coding: utf-8 -*-
"""grn-operones: la linea de comandos de la base de operones.

    python -m grn_operones.cli extraer [--fuente odb|biocyc|pgd|cdbprom|todo]
    python -m grn_operones.cli curar
    python -m grn_operones.cli exportar
    python -m grn_operones.cli estado

Parsea, llama a la orquestacion y formatea. Sin logica de negocio y sin SQL:
lo primero vive en `fuentes.py` y `curar.py`, lo segundo en `db.py`. Es el
unico modulo del paquete que imprime.
"""

import argparse
import datetime
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import rutas                                    # noqa: E402
from grn_etl import credenciales                                # noqa: E402
from grn_operones import curar as _curar                        # noqa: E402
from grn_operones import db, exportar, fuentes, red             # noqa: E402


def log(msg):
    print(msg, flush=True)


def _conectar(args):
    return db.conectar(os.path.join(rutas.raiz_datos(args.datos), "grn.db"))


def cmd_extraer(args):
    # El correo sale del entorno o de `.correo`, nunca de un flag: lo que se
    # teclea en la linea de comandos queda en el historial del shell. Es el
    # mismo criterio que aplica a BIOCYC_EMAIL y BIOCYC_PASSWORD, y la
    # interfaz tiene que ser una sola aunque el riesgo de cada dato difiera.
    correo = credenciales.correo()
    if not correo:
        sys.exit("Hace falta un correo de contacto para identificar al agente "
                 "ante las fuentes. Ponlo en NCBI_EMAIL o en el archivo "
                 ".correo; no hay flag a proposito, para que no quede en el "
                 "historial del shell.")
    pedidas = (fuentes.FUENTES if args.fuente == "todo" else (args.fuente,))

    log("Datos en %s (por %s)" % (rutas.raiz_datos(args.datos),
                                  rutas.de_donde(args.datos)))
    log("Fuentes: %s" % ", ".join(pedidas))
    log("Pausa entre peticiones: %.1f s" % args.pausa)
    log("")

    con = _conectar(args)
    informes = []
    try:
        for f in pedidas:
            log("%s" % f)
            # Una sesion por fuente: las cookies de BioCyc no tienen nada que
            # hacer en una peticion a ODB, y la pausa se mide por servidor.
            sesion = red.Sesion(correo, pausa=args.pausa)
            try:
                informes.append(fuentes.extraer(
                    con, f, sesion, args.datos, args.url, args.max_paginas,
                    log))
            except (fuentes.ErrorCredenciales, red.ErrorFuente) as e:
                log("  [%s] %s" % (f, e))
                informes.append({"fuente": f, "descargas": [], "filas": 0,
                                 "error": str(e)})
    finally:
        con.close()

    _informe_extraccion(informes)
    return 0


def _informe_extraccion(informes):
    log("")
    log("=" * 70)
    log("LO QUE DEVOLVIO CADA FUENTE")
    log("=" * 70)
    for i in informes:
        log("")
        log("  %s" % i["fuente"])
        if not i["descargas"]:
            log("    no se bajo nada")
        for d in i["descargas"]:
            partes = ["%s, %d bytes" % (d.get("tipo", "?"), d.get("bytes", 0))]
            for clave in ("tablas", "filas", "lineas", "locus_tags_visibles"):
                if d.get(clave):
                    partes.append("%s=%s" % (clave, d[clave]))
            if d.get("parece_render_js"):
                partes.append("PARECE RENDER POR JAVASCRIPT")
            log("    %s" % "  ".join(partes))
            log("      %s" % d["ruta"])
        if i.get("error"):
            log("    sin parsear: %s" % i["error"])
        elif i["filas"]:
            log("    %d filas al bronce (%d nuevas, %d actualizadas)"
                % (i["filas"], i.get("nuevas", 0), i.get("actualizadas", 0)))
    log("")
    log("  La descarga cruda se guarda aunque el parser no exista todavia:")
    log("  es justo lo que hace falta para escribirlo.")
    return 0


def cmd_curar(args):
    con = _conectar(args)
    try:
        conteos = db.conteos_bronze(con)
        if not conteos:
            sys.exit("No hay nada en operones_bronze. Corre `extraer` primero.")
        log("Bronce por fuente: %s"
            % ", ".join("%s=%d" % (k, v) for k, v in sorted(conteos.items())))
        resumen = _curar.curar(con, log)
    finally:
        con.close()

    log("")
    log("=" * 70)
    log("CAPA CURADA")
    log("=" * 70)
    log("  operones                       %d" % resumen["operones"])
    for nivel in _curar.NIVELES:
        log("    %-28s %d" % (nivel, resumen["por_nivel"].get(nivel, 0)))
    log("  con dos o mas fuentes          %d" % resumen["con_dos_o_mas_fuentes"])
    log("  unidades alternativas          %d" % resumen["alternativas"])
    log("  con promotor CDBProm           %d" % resumen["con_promotor"])
    log("  no adyacentes en el genoma     %d" % resumen["no_adyacentes"])
    log("  marcados para revisar          %d" % resumen["para_revisar"])
    log("  descartados por un solo gen    %d" % resumen["descartadas_un_gen"])
    log("  nombres sin resolver a locus   %d" % resumen["nombres_sin_resolver"])
    for nombre, n in resumen["top_sin_resolver"]:
        log("      %-24s %d" % (nombre, n))

    filas, con_sinonimo = resumen["sinonimos"]
    log("  sinonimos en el diccionario    %d de %d filas (%.1f %%)"
        % (con_sinonimo, filas, 100.0 * con_sinonimo / filas))

    if resumen["sin_foto"]:
        log("")
        log("  FUERA DE LA CURACION: sin ninguna extraccion completa")
        log("  Tienen bronce, pero su extraccion no termino bien. Con media")
        log("  foto no se puede decir que se retiro ni que sigue, asi que no")
        log("  se curan. Vuelve a correr `extraer` para esas fuentes.")
        for f in resumen["sin_foto"]:
            log("    %s" % f)

    if resumen["retirados"]:
        log("")
        log("  RETIRADOS POR LA FUENTE desde la extraccion anterior")
        log("  Estuvieron y ya no estan. Que desaparezcan es informacion:")
        log("  alguien los retiro por algo, y dejarlos caer en silencio los")
        log("  convierte en un hueco que nadie sabe explicar.")
        for f in sorted(resumen["retirados"]):
            ids = resumen["retirados"][f]
            log("    %-10s %d: %s%s"
                % (f, len(ids), ", ".join(ids[:8]),
                   " ..." if len(ids) > 8 else ""))

    if resumen["ambiguos"]:
        log("")
        log("  NOMBRES AMBIGUOS, sin resolver a proposito")
        log("  Elegir uno meteria un gen equivocado en un operon sin dejar")
        log("  rastro de que hubo una eleccion. Van a conflictos.")
        for nombre in sorted(resumen["ambiguos"]):
            log("    %-16s -> %s"
                % (nombre, ", ".join(resumen["ambiguos"][nombre])))

    log("")
    log("  COBERTURA DE MAPEO POR FUENTE")
    log("  La normalizacion falla en silencio: un nombre que el diccionario no")
    log("  conoce da un operon con un gen menos, indistinguible de uno que de")
    log("  verdad lo tiene. Por eso se mide antes de confiar en la curacion.")
    for f in sorted(resumen["cobertura"]):
        c = resumen["cobertura"][f]
        log("    %-10s %3d de %3d nombres  (%.1f %%)"
            % (f, c["mapeados"], c["nombres"], 100.0 * c["tasa"]))
        if c["huerfanos"]:
            log("       sin mapear (faltan del diccionario): %s%s"
                % (", ".join(c["huerfanos"][:10]),
                   " ..." if len(c["huerfanos"]) > 10 else ""))
        if c["ambiguos"]:
            log("       ambiguos (sobran candidatos): %s%s"
                % (", ".join(c["ambiguos"][:10]),
                   " ..." if len(c["ambiguos"]) > 10 else ""))
    log("")
    log("  `n_fuentes` cuenta fuentes distintas, y BioCyc con Pseudomonas.com")
    log("  valen por una: comparten el motor de prediccion de Pathway Tools,")
    log("  asi que coincidir no es confirmacion independiente.")
    return 0


def cmd_exportar(args):
    con = _conectar(args)
    try:
        silver = exportar.filas_silver(con, db)
        conflictos = exportar.filas_conflictos(con, db)
    finally:
        con.close()
    if not silver:
        sys.exit("La capa curada esta vacia. Corre `curar` primero.")

    dia = datetime.date.today().strftime("%Y%m%d")
    base = os.path.join("salidas", "operones_%s" % dia)
    log("Escribiendo (los CSV son el producto canonico):")
    exportar.escribir_csv(base + "_silver.csv", exportar.COLUMNAS_SILVER,
                          silver, log)
    exportar.escribir_csv(base + "_conflictos.csv",
                          exportar.COLUMNAS_CONFLICTOS, conflictos, log)
    log("")
    log("  %d operones curados, %d para revisar a mano." % (len(silver),
                                                            len(conflictos)))
    return 0


def cmd_estado(args):
    con = _conectar(args)
    try:
        conteos = db.conteos_bronze(con)
        descargas = db.descargas_de(con)
        resumen = db.resumen_silver(con) if conteos else None
    finally:
        con.close()

    log("=" * 70)
    log("BASE DE OPERONES")
    log("=" * 70)
    log("  descargas crudas registradas   %d" % len(descargas))
    por_fuente = {}
    for d in descargas:
        por_fuente.setdefault(d["fuente"], []).append(d)
    for f in sorted(por_fuente):
        ultima = por_fuente[f][0]
        log("    %-10s %2d archivos, la ultima %s"
            % (f, len(por_fuente[f]), ultima["descargado_en"]))
    log("  filas en bronce                %d" % sum(conteos.values()))
    for f in sorted(conteos):
        log("    %-10s %d" % (f, conteos[f]))
    if resumen:
        log("  operones curados               %d" % resumen["operones"])
        log("    para revisar                 %d" % resumen["para_revisar"])
    faltan = [f for f in fuentes.FUENTES if f not in conteos]
    if faltan:
        log("")
        log("  Sin datos todavia: %s" % ", ".join(faltan))
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="grn-operones",
        description="Base de operones de P. aeruginosa PAO1.")
    ap.add_argument("--datos", help="Raiz de datos; gana sobre GRN_DATOS.")
    sub = ap.add_subparsers(dest="sub", required=True)

    ex = sub.add_parser("extraer", help="Descargar y parsear una fuente.")
    ex.add_argument("--fuente", default="todo",
                    choices=list(fuentes.FUENTES) + ["todo"])
    ex.add_argument("--url", help="URL del archivo, para pgd y cdbprom.")
    ex.add_argument("--pausa", type=float, default=red.PAUSA,
                    help="Segundos entre peticiones (minimo del encargo: 2).")
    ex.add_argument("--max-paginas", type=int, default=500,
                    dest="max_paginas")
    ex.set_defaults(func=cmd_extraer)

    cu = sub.add_parser("curar", help="De bronce a curado: normalizar y validar.")
    cu.set_defaults(func=cmd_curar)

    ex2 = sub.add_parser("exportar", help="La base curada y sus conflictos, a CSV.")
    ex2.set_defaults(func=cmd_exportar)

    es = sub.add_parser("estado", help="Que hay descargado, en bronce y curado.")
    es.set_defaults(func=cmd_estado)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
