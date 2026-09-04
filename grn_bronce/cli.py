# -*- coding: utf-8 -*-
"""grn-bronce: la linea de comandos del paso 1.

    python -m grn_bronce.cli exportar [--corpus v0-agosto] [--datos RUTA]

Parsea, llama a la orquestacion y formatea. Sin logica de negocio y sin SQL:
lo primero vive en `identificar.py` y lo segundo en `db.py`. Es el unico modulo
del paquete que imprime.
"""

import argparse
import collections
import datetime
import os
import random
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import db, exportar, identificar, rutas, vocabulario  # noqa: E402

# Semilla fija: las diez filas de muestra tienen que ser las mismas si alguien
# repite el comando para comprobar lo que se reporto.
SEMILLA = 20260904


def log(msg):
    print(msg, flush=True)


def _tasa(parte, total):
    return "%.1f %%" % (100.0 * parte / total) if total else "n/d"


def _duracion(segundos):
    m, s = divmod(int(segundos), 60)
    return "%d min %d s" % (m, s) if m else "%d s" % s


def cmd_exportar(args):
    t0 = time.time()
    ruta_datos = rutas.raiz_datos(args.datos)
    log("Datos en %s (por %s)" % (ruta_datos, rutas.de_donde(args.datos)))

    con = db.conectar(os.path.join(ruta_datos, "grn.db"))
    try:
        return _exportar(con, args, ruta_datos, t0)
    finally:
        con.close()


def _exportar(con, args, ruta_datos, t0):
    from grn_etl import db as db0

    corpus_id, corpus_nombre = None, "(todos los documentos)"
    if args.corpus:
        fila = db0.obtener_corpus(con, args.corpus)
        if fila is None:
            sys.exit("No existe el corpus '%s'. Crealo con "
                     "`python cli.py corpus crear`." % args.corpus)
        corpus_id, corpus_nombre = fila["id"], fila["nombre"]
        if not db0.verificar_corpus(con, corpus_id):
            sys.exit("El corpus '%s' ya no coincide con su huella. Cualquier "
                     "cifra que se reporte contra el no es reproducible."
                     % args.corpus)

    previa = db.corrida_previa(con, identificar.METODO, identificar.VERSION,
                               corpus_id)
    if previa is not None and not args.rehacer:
        log("")
        log("Ya hay una corrida terminada con metodo=%s version=%s sobre este "
            "corpus (id %d, %s)." % (identificar.METODO, identificar.VERSION,
                                     previa["id"], previa["iniciada_en"]))
        log("Es idempotente por (metodo, version): no hay nada nuevo que "
            "calcular. Usa --rehacer para forzar.")
        return 0

    log("Cargando el diccionario y los vocabularios...")
    lex = identificar.cargar_lexico()
    locus = identificar.cargar_locus_tags()
    vocab = vocabulario.Vocabulario.cargar()
    log("  diccionario : %d superficies" % len(lex))
    log("  disparadores: %d   funciones: %d   evidencia: %d"
        % (len(vocab.disparadores), len(vocab.funciones),
           len(vocab.evidencia)))
    faltan_vocab = [n for n, v in (("disparadores", vocab.disparadores),
                                   ("funciones", vocab.funciones),
                                   ("evidencia", vocab.evidencia)) if not v]

    documentos = db.documentos_del_corpus(con, corpus_id)
    fulltext = db.fulltext_disponible(con, "xml")
    log("  documentos  : %d   con xml ok: %d"
        % (len(documentos), len(fulltext)))

    parametros = {"corpus": corpus_nombre, "min_oracion": identificar.MIN_ORACION,
                  "max_oracion": identificar.MAX_ORACION,
                  "max_menciones": identificar.MAX_MENCIONES,
                  "fuentes": "abstract+xml", "pdf": False,
                  "datos": rutas.de_donde(args.datos)}
    corrida_id = db.abrir_corrida(con, "1", identificar.METODO,
                                  identificar.VERSION, parametros, corpus_id)
    log("")
    log("Corrida %d registrada. Procesando..." % corrida_id)

    try:
        candidatas, menciones, cuenta = identificar.identificar(
            documentos, fulltext, lex, vocab, locus, log)
    except Exception as e:                            # noqa: BLE001
        db.cerrar_corrida(con, corrida_id, "error", str(e))
        raise

    fecha = db.ahora()
    for fila in candidatas:
        fila.update(metodo=identificar.METODO, version=identificar.VERSION,
                    corrida_id=corrida_id, fecha_corrida=fecha)
    for fila in menciones:
        fila.update(metodo=identificar.METODO, version=identificar.VERSION,
                    corrida_id=corrida_id)

    resumen = _armar_resumen(candidatas, menciones, cuenta, documentos,
                             corpus_nombre, corrida_id, time.time() - t0,
                             faltan_vocab)

    dia = datetime.date.today().strftime("%Y%m%d")
    base = os.path.join("salidas", "bronce_identificacion_%s" % dia)
    log("")
    log("Escribiendo (los CSV son el producto canonico):")
    exportar.escribir_csv(base + "_oraciones_candidatas.csv",
                          exportar.COLUMNAS_CANDIDATAS, candidatas, log)
    exportar.escribir_csv(base + "_menciones.csv",
                          exportar.COLUMNAS_MENCIONES, menciones, log)
    exportar.escribir_resumen_csv(base + "_resumen.csv", resumen, log)
    hubo_xlsx = exportar.escribir_xlsx(base + ".xlsx", candidatas, menciones,
                                       resumen, log)

    db.cerrar_corrida(con, corrida_id, "ok", None, len(documentos),
                      len(candidatas))

    _mostrar(resumen, candidatas, cuenta, hubo_xlsx, faltan_vocab)
    return 0


def _armar_resumen(candidatas, menciones, cuenta, documentos, corpus,
                   corrida_id, segundos, faltan_vocab):
    por_tipo = collections.Counter(m["tipo"] for m in menciones)
    genes = set(m["texto"] for m in menciones if m["tipo"] in ("gen", "proteina"))
    con_locus = sum(1 for m in menciones
                    if m["tipo"] in ("gen", "proteina")
                    and str(m["id_normalizado"]).startswith("PA"))
    n_genes = por_tipo["gen"] + por_tipo["proteina"]
    oraciones = (cuenta["oraciones_examinadas"] + cuenta["oraciones_cortas"]
                 + cuenta["oraciones_largas"])

    filas = [
        ("Corpus", corpus),
        ("Corrida", corrida_id),
        ("Metodo y version", "%s / %s" % (identificar.METODO,
                                          identificar.VERSION)),
        ("Documentos procesados", cuenta["documentos"]),
        ("Documentos con texto completo", cuenta["documentos_con_fulltext"]),
        ("Documentos solo con resumen",
         cuenta["documentos"] - cuenta["documentos_con_fulltext"]),
        ("Oraciones totales", oraciones),
        ("  examinadas (entre %d y %d caracteres)"
         % (identificar.MIN_ORACION, identificar.MAX_ORACION),
         cuenta["oraciones_examinadas"]),
        ("  descartadas por cortas", cuenta["oraciones_cortas"]),
        ("  descartadas por largas", cuenta["oraciones_largas"]),
        ("Oraciones candidatas", len(candidatas)),
        ("  sin dos genes distintos", cuenta["oraciones_sin_par"]),
        ("  con mas de %d genes distintos" % identificar.MAX_MENCIONES,
         cuenta["oraciones_con_demasiadas_menciones"]),
        ("Menciones totales", len(menciones)),
    ]
    for tipo in ("gen", "proteina", "disparador", "funcion", "evidencia",
                 "organismo"):
        filas.append(("  de tipo %s" % tipo, por_tipo[tipo]))
    filas += [
        ("Genes distintos (superficies)", len(genes)),
        ("Tasa de normalizacion a locus tag", _tasa(con_locus, n_genes)),
        ("Documentos sin ninguna mencion",
         cuenta["documentos_sin_ninguna_mencion"]),
        ("Documentos con error", cuenta["documentos_con_error"]),
        ("Duracion de la corrida", _duracion(segundos)),
    ]
    filas += [
        ("Candidatas sin regulador ni blanco: dos o mas TF",
         cuenta["dos_o_mas_tf"]),
        ("Candidatas sin regulador ni blanco: ningun TF", cuenta["sin_tf"]),
        ("Candidatas sin regulador ni blanco: sin disparador",
         cuenta["sin_disparador"]),
        ("Candidatas sin blanco unico", cuenta["sin_blanco_unico"]),
    ]
    filas += [
        ("Diccionario", "genes_pao1.tsv, RefSeq+KEGG+UniProt. "
                        "Pseudomonas Genome DB da 403"),
        ("Fuentes de texto", "abstract y XML de PMC con estatus ok"),
        ("PDF", "fuera de esta corrida; 184 documentos con pdf ok sin procesar"),
        ("OCR", "no implementado"),
    ]
    if faltan_vocab:
        filas.append(("AVISO: vocabularios vacios", ", ".join(faltan_vocab)))
    return filas


def _mostrar(resumen, candidatas, cuenta, hubo_xlsx, faltan_vocab):
    log("")
    log("=" * 72)
    log("HOJA RESUMEN")
    log("=" * 72)
    for concepto, valor in resumen:
        log("  %-52s %s" % (concepto, valor))

    log("")
    log("=" * 72)
    log("DIEZ RENGLONES AL AZAR DE oraciones_candidatas (semilla %d)" % SEMILLA)
    log("=" * 72)
    if not candidatas:
        log("  No hay ninguna. Ver la lista de pendientes de abajo.")
    else:
        r = random.Random(SEMILLA)
        for n, fila in enumerate(r.sample(candidatas,
                                          min(10, len(candidatas))), 1):
            log("")
            log("  --- %d de 10 ---" % n)
            for col in exportar.COLUMNAS_CANDIDATAS:
                valor = str(fila.get(col, ""))
                if col == "oracion" and len(valor) > 300:
                    valor = valor[:300] + " [...]"
                etiqueta = exportar._encabezado_visible(col)
                log("    %-28s %s" % (etiqueta, valor if valor else "(vacio)"))

    log("")
    log("=" * 72)
    log("LO QUE FALLO O QUEDO PENDIENTE")
    log("=" * 72)
    pendientes = []
    if faltan_vocab:
        pendientes.append(
            "Vocabularios vacios (%s): sus columnas salen en blanco."
            % ", ".join(faltan_vocab))
    if cuenta["documentos_con_error"]:
        pendientes.append("%d documentos fallaron al procesarse."
                          % cuenta["documentos_con_error"])
    if cuenta["ruta_de_fulltext_no_existe"]:
        pendientes.append(
            "%d filas de descargas dicen 'ok' pero su archivo no esta en disco."
            % cuenta["ruta_de_fulltext_no_existe"])
    pendientes += [
        "PDF: 184 documentos tienen pdf con estatus ok y no se procesaron. "
        "Queda para despues del viernes, con PyMuPDF.",
        "Las tablas texto_unidades, menciones y oraciones_candidatas NO se "
        "persisten todavia: CLAUDE.md exige aprobar el DDL antes. Hoy el "
        "contenido sale a CSV y Excel.",
        "El score no esta calibrado. Ordena, pero no debe usarse como umbral "
        "hasta medir si mejora la precision.",
        "La columna signo_sugerido es lexica, NO VERIFICADA: la redaccion "
        "desde el fenotipo del mutante invierte el signo y eso lo resuelve el "
        "paso 2.",
    ]
    if not hubo_xlsx:
        pendientes.append("No se genero el .xlsx: falta openpyxl.")
    for p in pendientes:
        log("  - %s" % p)
    log("")


def main():
    ap = argparse.ArgumentParser(
        prog="grn-bronce",
        description="Paso 1: identificacion de elementos (capa bronce).")
    sub = ap.add_subparsers(dest="sub", required=True)

    ex = sub.add_parser("exportar",
                        help="Identificar y volcar las tres hojas.")
    ex.add_argument("--corpus", default="v0-agosto",
                    help="Nombre del corpus congelado. Vacio = todos.")
    ex.add_argument("--datos", help="Raiz de datos; gana sobre GRN_DATOS.")
    ex.add_argument("--rehacer", action="store_true",
                    help="Rehacer aunque ya exista una corrida igual.")
    ex.set_defaults(func=cmd_exportar)

    args = ap.parse_args()
    if args.corpus == "":
        args.corpus = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
