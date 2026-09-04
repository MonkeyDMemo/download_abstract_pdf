# -*- coding: utf-8 -*-
"""grn-bronce: la linea de comandos del paso 1.

    python -m grn_bronce.cli exportar [--corpus v0-agosto] [--datos RUTA]

Parsea, llama a la orquestacion y formatea. Sin logica de negocio y sin SQL:
lo primero vive en `identificar.py` y lo segundo en `db.py`. Es el unico modulo
del paquete que imprime.
"""

import argparse
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

# La referencia de evaluacion del proyecto, por su tamano y no por su nombre.
# El nombre del archivo NO puede aparecer en el codigo de este paquete: el
# guardian de `etapa2/test_contaminacion.py` lo prohibe en los tres paquetes
# del pipeline, y partir la cadena para colarla seria evadir la propia guarda.
# Que el bronce no pueda ni nombrar la referencia con la que luego se evalua es
# el punto de la regla, no un efecto colateral.
ORO_PARES = 190
ORO_DOCUMENTOS = 312
ORO_SUBSISTEMAS = 6


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
        return _exportar(con, args, t0)
    finally:
        con.close()


def _exportar(con, args, t0):
    from grn_etl import db as db0

    corpus_id, corpus_nombre = None, "(todos los documentos)"
    if args.corpus:
        fila = db0.obtener_corpus(con, args.corpus)
        if fila is None:
            sys.exit("No existe el corpus '%s'." % args.corpus)
        corpus_id, corpus_nombre = fila["id"], fila["nombre"]
        if not db0.verificar_corpus(con, corpus_id):
            sys.exit("El corpus '%s' ya no coincide con su huella: cualquier "
                     "cifra reportada contra el no es reproducible."
                     % args.corpus)

    previa = db.corrida_previa(con, identificar.METODO, identificar.VERSION,
                               corpus_id)
    if previa is not None and not args.rehacer:
        log("")
        log("Ya hay una corrida terminada con metodo=%s version=%s sobre este "
            "corpus (id %d, %s)." % (identificar.METODO, identificar.VERSION,
                                     previa["id"], previa["iniciada_en"]))
        log("Es idempotente por (metodo, version). Usa --rehacer para forzar.")
        return 0
    if previa is not None:
        log("Rehaciendo: se borran las filas de la corrida %d." % previa["id"])
        db.borrar_corrida(con, previa["id"])

    log("Cargando el diccionario y los vocabularios...")
    lex = identificar.cargar_lexico()
    locus = identificar.cargar_locus_tags()
    vocab = vocabulario.Vocabulario.cargar()
    log("  diccionario : %d superficies" % len(lex))
    log("  disparadores: %d   funciones: %d   evidencia: %d"
        % (len(vocab.disparadores), len(vocab.funciones), len(vocab.evidencia)))
    faltan = [n for n, v in (("disparadores", vocab.disparadores),
                             ("funciones", vocab.funciones),
                             ("evidencia", vocab.evidencia)) if not v]

    documentos = db.documentos_del_corpus(con, corpus_id)
    fulltext = db.fulltext_disponible(con, "xml")
    log("  documentos  : %d   con xml ok: %d" % (len(documentos), len(fulltext)))

    parametros = {"corpus": corpus_nombre,
                  "min_oracion": identificar.MIN_ORACION,
                  "max_oracion": identificar.MAX_ORACION,
                  "max_menciones": identificar.MAX_MENCIONES,
                  "fuentes": "abstract+xml", "pdf": False, "ocr": False,
                  "datos": rutas.de_donde(args.datos)}
    corrida_id = db.abrir_corrida(con, "1", identificar.METODO,
                                  identificar.VERSION, parametros, corpus_id)
    log("")
    log("Corrida %d registrada. Procesando..." % corrida_id)

    try:
        cuenta = identificar.identificar(con, corrida_id, documentos, fulltext,
                                         lex, vocab, locus, log)
    except Exception as e:                            # noqa: BLE001
        db.cerrar_corrida(con, corrida_id, "error", str(e))
        raise

    log("")
    log("Consultando las tablas para exportar...")
    candidatas = exportar.filas_candidatas(con, db, corrida_id)
    menciones = exportar.filas_menciones(con, db, corrida_id)
    conteos = db.conteos_de(con, corrida_id)
    resumen = _armar_resumen(conteos, cuenta, corpus_nombre, corrida_id,
                             time.time() - t0, faltan)

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
    _mostrar(resumen, candidatas, cuenta, conteos, hubo_xlsx, faltan)
    return 0


def _armar_resumen(c, cuenta, corpus, corrida_id, segundos, faltan):
    """Los numeros salen de `conteos_de()`, o sea de la base, no de memoria."""
    t = c["por_tipo"]
    filas = [
        ("Corpus", corpus),
        ("Corrida", corrida_id),
        ("Metodo y version", "%s / %s" % (identificar.METODO,
                                          identificar.VERSION)),
        ("Documentos procesados", c["documentos"]),
        ("Documentos con texto completo (xml estatus ok)",
         c["documentos_con_fulltext"]),
        ("Documentos solo con resumen",
         c["documentos"] - c["documentos_con_fulltext"]),
        ("Oraciones totales (todas, se guardan aunque no sean candidatas)",
         c["unidades"]),
        ("  que cruzan un encabezado borrado (span no contiguo)",
         c["unidades_no_contiguas"]),
        ("  examinadas para candidata", cuenta["oraciones_examinadas"]),
        ("  descartadas por cortas (menos de %d caracteres)"
         % identificar.MIN_ORACION, cuenta["oraciones_cortas"]),
        ("  descartadas por largas (mas de %d)" % identificar.MAX_ORACION,
         cuenta["oraciones_largas"]),
        ("  descartadas por seccion excluida", cuenta["oraciones_en_seccion_excluida"]),
        ("Oraciones candidatas", c["candidatas"]),
        ("  con disparador", c["con_disparador"]),
        ("  con regulador y blanco asignados", c["con_regulador"]),
        ("  sin dos genes distintos", cuenta["oraciones_sin_par"]),
        ("  con mas de %d genes distintos" % identificar.MAX_MENCIONES,
         cuenta["oraciones_con_demasiados_genes"]),
        ("Menciones totales", c["menciones"]),
    ]
    for tipo in ("gen", "proteina", "disparador", "funcion", "evidencia",
                 "organismo"):
        filas.append(("  de tipo %s" % tipo, t.get(tipo, 0)))
    filas += [
        ("Genes distintos (superficies)", c["genes_distintos"]),
        ("Tasa de normalizacion a locus tag",
         _tasa(c["genes_normalizados"], c["genes_totales"])),
        ("Documentos sin ninguna mencion",
         cuenta["documentos_sin_ninguna_mencion"]),
        ("Documentos con error", cuenta["documentos_con_error"]),
        ("Duracion de la corrida", _duracion(segundos)),
    ]
    filas += [
        ("Por que quedan vacios regulador y blanco: dos o mas TF",
         cuenta["dos_o_mas_tf"]),
        ("Por que quedan vacios regulador y blanco: ningun TF",
         cuenta["sin_tf"]),
        ("Por que quedan vacios regulador y blanco: sin disparador",
         cuenta["sin_disparador"]),
        ("Por que queda vacio el blanco: mas de un candidato",
         cuenta["sin_blanco_unico"]),
    ]
    filas += [
        ("NOTA score", "ordena, no es umbral; sin calibrar"),
        ("NOTA signo_sugerido", "lexico del disparador, NO VERIFICADO"),
        ("Referencia de evaluacion del proyecto",
         "%d pares canonicos sobre %d subsistemas, citando %d documentos"
         % (ORO_PARES, ORO_SUBSISTEMAS, ORO_DOCUMENTOS)),
        ("Precision contra esa referencia",
         "no se calcula aqui: la referencia lista PARES y esta capa produce "
         "ORACIONES, y ademas cubre 6 subsistemas, asi que una candidata "
         "fuera de la lista no esta mal, solo no esta listada"),
        ("Recall contra esa referencia",
         "no disponible en esta capa: se mide en el paso 3, sobre aristas"),
        ("Sobre el 31.7 % citado en el plan",
         "no salio de esa referencia sino de muestreo estratificado de la red "
         "del paso 2; es precision de ARISTAS del estrato A, no de esta capa"),
        ("Diccionario", "genes_pao1.tsv, RefSeq+KEGG+UniProt. "
                        "Pseudomonas Genome DB responde 403"),
        ("Fuentes de texto", "resumen y XML de PMC con estatus ok"),
        ("PDF", "fuera de esta corrida; queda para despues, con PyMuPDF"),
        ("OCR", "no implementado"),
    ]
    if faltan:
        filas.append(("AVISO: vocabularios vacios", ", ".join(faltan)))
    return filas


def _mostrar(resumen, candidatas, cuenta, conteos, hubo_xlsx, faltan):
    log("")
    log("=" * 74)
    log("HOJA RESUMEN")
    log("=" * 74)
    for concepto, valor in resumen:
        texto = str(valor)
        if len(texto) > 58:
            log("  %s:" % concepto)
            for i in range(0, len(texto), 68):
                log("      %s" % texto[i:i + 68])
        else:
            log("  %-52s %s" % (concepto, texto))

    log("")
    log("=" * 74)
    log("DIEZ RENGLONES AL AZAR DE oraciones_candidatas (semilla %d)" % SEMILLA)
    log("=" * 74)
    if not candidatas:
        log("  No hay ninguna. Ver los pendientes de abajo.")
    else:
        r = random.Random(SEMILLA)
        for n, fila in enumerate(
                r.sample(candidatas, min(10, len(candidatas))), 1):
            log("")
            log("  --- %d de 10 ---" % n)
            for col in exportar.COLUMNAS_CANDIDATAS:
                valor = str(fila.get(col, ""))
                if col == "oracion" and len(valor) > 260:
                    valor = valor[:260] + " [...]"
                log("    %-42s %s" % (exportar._encabezado_visible(col),
                                      valor if valor else "(vacio)"))

    log("")
    log("=" * 74)
    log("LO QUE FALLO O QUEDO PENDIENTE")
    log("=" * 74)
    p = []
    if faltan:
        p.append("Vocabularios vacios (%s): sus columnas salen en blanco."
                 % ", ".join(faltan))
    if cuenta["documentos_con_error"]:
        p.append("%d documentos fallaron al procesarse."
                 % cuenta["documentos_con_error"])
    if cuenta["ruta_de_fulltext_no_existe"]:
        p.append("%d filas de descargas dicen 'ok' pero su archivo no esta."
                 % cuenta["ruta_de_fulltext_no_existe"])
    if conteos["unidades_no_contiguas"]:
        p.append("%d oraciones cruzan un encabezado borrado: su span incluye "
                 "el titulo que se quito. Van marcadas contiguo=0."
                 % conteos["unidades_no_contiguas"])
    p += [
        "PDF: los documentos con pdf estatus ok no se procesaron. Queda para "
        "despues, con PyMuPDF.",
        "El score no esta calibrado. Ordena, pero no debe usarse como umbral "
        "hasta medir si mejora la precision.",
        "signo_sugerido es lexico y NO VERIFICADO: la redaccion desde el "
        "fenotipo del mutante invierte el signo, y eso lo resuelve el paso 2.",
        "Precision y recall de esta capa contra la referencia del proyecto no "
        "se calculan aqui: son de otro nivel (pares contra oraciones) y el "
        "bronce no puede leer la referencia, por la regla de anticircularidad.",
        "lexico.py sigue en etapa2/ y se importa: su mudanza a grn_bronce esta "
        "anotada en la bitacora.",
    ]
    if not hubo_xlsx:
        p.append("No se genero el .xlsx: falta openpyxl.")
    for x in p:
        log("  - %s" % x)
    log("")


def main():
    ap = argparse.ArgumentParser(
        prog="grn-bronce",
        description="Paso 1: identificacion de elementos (capa bronce).")
    sub = ap.add_subparsers(dest="sub", required=True)

    ex = sub.add_parser("exportar", help="Identificar y volcar las tres hojas.")
    ex.add_argument("--corpus", default="v0-agosto",
                    help="Corpus congelado. Cadena vacia = todos.")
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
