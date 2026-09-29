# -*- coding: utf-8 -*-
"""grn-bronce: la linea de comandos del paso 1.

    python -m grn_bronce.cli exportar [--corpus v0-agosto] [--datos RUTA]
    python -m grn_bronce.cli exportar --corrida N   # volcar sin identificar
    python -m grn_bronce.cli pares    [--corrida N]
    python -m grn_bronce.cli operones [--corrida N] [--solo-faltantes]

Parsea, llama a la orquestacion y formatea. Sin logica de negocio y sin SQL:
lo primero vive en `identificar.py` y lo segundo en `db.py`. Es el unico modulo
del paquete que imprime.
"""

import argparse
import datetime
import json
import os
import random
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import (db, exportar, identificar, operones, rutas,  # noqa: E402
                        vocabulario)
from grn_comun import procedencia                                  # noqa: E402

# Lo que dice el resumen de un conteo que solo existe al identificar, cuando
# se reexporta una corrida. Un cero ahí se leería como resultado.
ND = "n/d: solo se cuenta al identificar"

# Semilla fija: las diez filas de muestra tienen que ser las mismas si alguien
# repite el comando para comprobar lo que se reporto.
SEMILLA = 20260904

# La referencia de evaluacion del proyecto, por su tamano y no por su nombre.
# El nombre del archivo NO puede aparecer en el codigo de este paquete: el
# guardian de `etapa2/test_contaminacion.py` lo prohibe en los paquetes
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

    # `is not None` y no la verdad del valor: `--corrida 0` tiene que salir
    # como «no existe la corrida 0», no caer en identificar el corpus entero.
    if args.corrida is not None:
        return _reexportar(con, args)

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
        log("Es idempotente por (metodo, version). Usa --rehacer para forzar, "
            "o --corrida %d para volver a volcarla sin identificar."
            % previa["id"])
        return 0
    if previa is not None:
        log("Rehaciendo: se borran las filas de la corrida %d." % previa["id"])
        db.borrar_corrida(con, previa["id"])

    log("Cargando el diccionario y los vocabularios...")
    lex = identificar.cargar_lexico()
    locus = identificar.cargar_locus_tags()
    vocab = vocabulario.Vocabulario.cargar()
    log("  diccionario : %d superficies" % len(lex))
    log("  disparadores: %d   funciones: %d   evidencia: %d   "
        "contexto regulatorio: %d"
        % (len(vocab.disparadores), len(vocab.funciones),
           len(vocab.evidencia), len(vocab.contexto)))
    faltan = [n for n, v in (("disparadores", vocab.disparadores),
                             ("funciones", vocab.funciones),
                             ("evidencia", vocab.evidencia),
                             ("contexto_regulatorio", vocab.contexto)) if not v]

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

    resumen, candidatas, conteos, hubo_xlsx = _volcar(
        con, db.corrida(con, corrida_id), corpus_nombre, cuenta,
        time.time() - t0, faltan)
    db.cerrar_corrida(con, corrida_id, "ok", None, len(documentos),
                      len(candidatas))
    _mostrar(resumen, candidatas, cuenta, conteos, hubo_xlsx, faltan)
    return 0


def _reexportar(con, args, carpeta="salidas"):
    """Vuelve a volcar una corrida existente, sin identificar de nuevo.

    Existe para anotar una corrida ya hecha con lo que cambió después --hoy,
    a qué operones pertenecen los genes de cada oración-- sin tocar lo que
    detectó. Por eso **nunca** cierra la corrida: `cerrar_corrida` le
    reescribiría la hora de término y los conteos, y la fila dejaría de decir
    cuándo y con qué se identificó. Método, versión y corpus salen de la fila
    de la corrida, no de las constantes de hoy.
    """
    from grn_etl import db as db0

    if args.rehacer:
        sys.exit("--rehacer no va con --corrida: reexportar no toca la base, "
                 "y rehacer borraría las filas de la corrida que se quiere "
                 "volcar.")
    fila = db.corrida(con, args.corrida)
    if fila is None:
        sys.exit("No existe la corrida %d." % args.corrida)
    if fila["paso"] != "1" or fila["estatus"] != "ok":
        sys.exit("La corrida %d no es del paso 1 terminada bien (paso %s, "
                 "estatus %s)." % (args.corrida, fila["paso"], fila["estatus"]))

    parametros = json.loads(fila["parametros"] or "{}")
    corpus_nombre = parametros.get("corpus") or "(desconocido)"
    if fila["corpus_id"] is not None:
        corpus = db0.obtener_corpus(con, corpus_nombre)
        if corpus is None or corpus["id"] != fila["corpus_id"]:
            sys.exit("No se encuentra el corpus '%s' de la corrida %d."
                     % (corpus_nombre, args.corrida))
        if not db0.verificar_corpus(con, fila["corpus_id"]):
            sys.exit("El corpus '%s' ya no coincide con su huella: cualquier "
                     "cifra reportada contra el no es reproducible."
                     % corpus_nombre)

    log("Reexportando la corrida %d (%s / %s, corpus %s) sin volver a "
        "identificar." % (fila["id"], fila["metodo"], fila["version"],
                          corpus_nombre))
    log("--corpus se ignora: el corpus es el de la corrida.")
    resumen, candidatas, conteos, hubo_xlsx = _volcar(
        con, fila, corpus_nombre, None, _segundos_de(fila), [], carpeta)
    _mostrar(resumen, candidatas, None, conteos, hubo_xlsx, [])
    return 0


def _segundos_de(fila):
    """La duración de una corrida, desde sus fechas. None si no se sabe."""
    try:
        ini = datetime.datetime.fromisoformat(fila["iniciada_en"])
        fin = datetime.datetime.fromisoformat(fila["terminada_en"])
    except (TypeError, ValueError):
        return None
    return (fin - ini).total_seconds()


def _volcar(con, fila, corpus_nombre, cuenta, segundos, faltan,
            carpeta="salidas"):
    """Arma las hojas de una corrida y las escribe. No toca la corrida.

    Lo usan las dos vías: la corrida recién identificada, con su `cuenta`, y
    la reexportación, sin ella (`cuenta = None`).
    """
    corrida_id = fila["id"]
    log("")
    log("Consultando las tablas para exportar...")
    catalogo = operones.Catalogo.cargar(operones.RUTA_POR_OMISION)
    base_op = operones.BaseOperones.cargar(operones.RUTA_BASE)
    candidatas = exportar.filas_candidatas(con, db, corrida_id, catalogo,
                                           base_op)
    menciones = exportar.filas_menciones(con, db, corrida_id)
    filas_operones = exportar.filas_operones(con, db, corrida_id, catalogo)
    conteos = db.conteos_de(con, corrida_id)
    recursos = [
        ("Catalogo de operones del paso 1", operones.RUTA_POR_OMISION,
         len(catalogo), "operones"),
        ("Base de operones (pertenencia)", operones.RUTA_BASE,
         len(base_op) if base_op.presente else None, "unidades"),
    ]
    resumen = _armar_resumen(conteos, cuenta, corpus_nombre, fila, segundos,
                             faltan, filas_operones, candidatas, recursos)

    # La corrida va en el nombre, no solo el día: dos volcados del mismo día
    # --una corrida y la reexportación de otra-- se pisaban, y así se perdieron
    # los archivos de la corrida 3.
    dia = datetime.date.today().strftime("%Y%m%d")
    base = os.path.join(carpeta, "bronce_identificacion_corrida%d_%s"
                        % (corrida_id, dia))
    log("")
    log("Escribiendo (los CSV son el producto canonico):")
    exportar.escribir_csv(base + "_oraciones_candidatas.csv",
                          exportar.COLUMNAS_CANDIDATAS, candidatas, log)
    exportar.escribir_csv(base + "_menciones.csv",
                          exportar.COLUMNAS_MENCIONES, menciones, log)
    exportar.escribir_csv(base + "_operones.csv",
                          exportar.COLUMNAS_OPERONES, filas_operones, log)
    exportar.escribir_resumen_csv(base + "_resumen.csv", resumen, log)
    hubo_xlsx = exportar.escribir_xlsx(base + ".xlsx", candidatas, menciones,
                                       resumen, filas_operones, log)
    return resumen, candidatas, conteos, hubo_xlsx


def _armar_resumen(c, cuenta, corpus, fila_corrida, segundos, faltan,
                   filas_operones=(), candidatas=(), recursos=()):
    """Los numeros salen de `conteos_de()`, o sea de la base, no de memoria.

    `cuenta` solo existe al identificar: es un conteo en memoria que no se
    guarda. En una reexportación llega `None` y sus filas dicen «n/d» en vez
    de un cero que parecería un resultado.
    """
    def n(clave):
        return cuenta[clave] if cuenta is not None else ND

    t = c["por_tipo"]
    filas = [
        ("Corpus", corpus),
        ("Corrida", fila_corrida["id"]),
        ("Metodo y version", "%s / %s" % (fila_corrida["metodo"],
                                          fila_corrida["version"])),
        ("Documentos procesados", c["documentos"]),
        ("Documentos con texto completo (xml estatus ok)",
         c["documentos_con_fulltext"]),
        ("Documentos solo con resumen",
         c["documentos"] - c["documentos_con_fulltext"]),
        ("Oraciones totales (todas, se guardan aunque no sean candidatas)",
         c["unidades"]),
        ("  que cruzan un encabezado borrado (span no contiguo)",
         c["unidades_no_contiguas"]),
        ("  examinadas para candidata", n("oraciones_examinadas")),
        ("  descartadas por cortas (menos de %d caracteres)"
         % identificar.MIN_ORACION, n("oraciones_cortas")),
        ("  descartadas por largas (mas de %d)" % identificar.MAX_ORACION,
         n("oraciones_largas")),
        ("  descartadas por seccion excluida", n("oraciones_en_seccion_excluida")),
        ("Oraciones candidatas", c["candidatas"]),
        ("  con disparador", c["con_disparador"]),
        ("  con regulador y blanco asignados", c["con_regulador"]),
        ("  sin dos genes distintos", n("oraciones_sin_par")),
        ("  con mas de %d genes distintos" % identificar.MAX_MENCIONES,
         n("oraciones_con_demasiados_genes")),
        ("Menciones totales", c["menciones"]),
    ]
    for tipo in ("gen", "proteina", "operon", "disparador", "funcion",
                 "contexto_regulatorio", "evidencia", "organismo"):
        filas.append(("  de tipo %s" % tipo, t.get(tipo, 0)))
    sin_catalogo = [f for f in filas_operones if f["en_catalogo"] == "no"]
    filas += [
        ("Operones distintos nombrados por el corpus",
         c.get("operones_distintos", 0)),
        ("  que estan en operones_pao1.tsv",
         len(filas_operones) - len(sin_catalogo)),
        ("  que NO estan: huecos del catalogo", len(sin_catalogo)),
        ("  menciones que sostienen esos huecos",
         sum(f["n_menciones"] for f in sin_catalogo)),
        ("Oraciones candidatas con operón (nombrado o por pertenencia de "
         "sus genes; hay_operon = si)",
         sum(1 for f in candidatas if f.get("hay_operon") == "si")),
        ("  de ellas, que nombran un operón en el texto",
         c.get("candidatas_con_operon", 0)),
        ("Genes distintos (superficies)", c["genes_distintos"]),
        ("Tasa de normalizacion a locus tag",
         _tasa(c["genes_normalizados"], c["genes_totales"])),
        ("Documentos sin ninguna mencion",
         n("documentos_sin_ninguna_mencion")),
        ("Documentos con error", n("documentos_con_error")),
        ("Duracion de la corrida",
         _duracion(segundos) if segundos is not None else ND),
    ]
    for concepto, ruta, filas_recurso, unidad in recursos:
        if filas_recurso is None:
            valor = ("recurso ausente (%s): operones_en_oracion solo trae los "
                     "operones nombrados" % os.path.basename(ruta))
        else:
            valor = "%s, huella %s, %d %s" % (
                os.path.basename(ruta), procedencia.huella(ruta),
                filas_recurso, unidad)
        filas.append((concepto, valor))
    filas += [
        ("Por que quedan vacios regulador y blanco: dos o mas TF",
         n("dos_o_mas_tf")),
        ("Por que quedan vacios regulador y blanco: ningun TF",
         n("sin_tf")),
        ("Por que quedan vacios regulador y blanco: sin disparador",
         n("sin_disparador")),
        ("Por que queda vacio el blanco: mas de un candidato",
         n("sin_blanco_unico")),
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
        ("Diccionario", "genes_pao1.tsv, RefSeq+KEGG+UniProt. Pseudomonas "
                        "Genome DB no: su sitio esta tras un desafio de "
                        "Cloudflare"),
        ("NOTA operones_en_oracion",
         "la pertenencia sale de la base de operones (ODB, BioCyc, PGD) y no "
         "cambia lo que se detectó. Pendiente de la decisión 3: no usarla "
         "como rasgo del paso 2 hasta saber si la base curada del laboratorio "
         "usó esas fuentes"),
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
    if cuenta is None:
        # Reexportación: esos conteos se hacen al identificar y no se guardan.
        # Decir «0 documentos con error» sería afirmar algo que no se midió.
        p.append("Reexportación sin identificar: los conteos que solo existen "
                 "al identificar (oraciones examinadas, descartes, documentos "
                 "con error) salen n/d en el resumen.")
    else:
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


def cmd_pares(args):
    """Los pares dirigidos de una corrida, agregados y a CSV."""
    ruta_datos = rutas.raiz_datos(args.datos)
    con = db.conectar(os.path.join(ruta_datos, "grn.db"))
    try:
        corrida_id = args.corrida or _ultima_corrida(con)
        filas = [dict(f) for f in db.pares_candidatos(con, corrida_id)]
    finally:
        con.close()

    dos = [f for f in filas if f["n_documentos"] >= 2]
    dia = datetime.date.today().strftime("%Y%m%d")
    ruta = os.path.join("salidas", "pares_candidatos_%s.csv" % dia)
    exportar.escribir_csv(
        ruta, ["tf", "blanco", "n_documentos", "n_oraciones", "score_max",
               "signos_sugeridos"], filas, log)
    log("")
    log("  corrida                    : %d" % corrida_id)
    log("  pares distintos            : %d" % len(filas))
    log("  con 2 o mas documentos     : %d  (%.1f %%)"
        % (len(dos), 100.0 * len(dos) / len(filas) if filas else 0.0))
    log("  oraciones que los sostienen: %d"
        % sum(f["n_oraciones"] for f in filas))
    log("")
    log("  Ninguna de estas filas afirma que la relacion exista: son pares")
    log("  con respaldo, y decidir es del paso 2.")
    return 0


def _ultima_corrida(con):
    """La ultima corrida 'ok', o se sale con un mensaje.

    La consulta la hace `db.ultima_corrida()`: aqui solo queda decidir que
    hacer cuando no hay ninguna, que es formateo y no SQL.
    """
    corrida_id = db.ultima_corrida(con)
    if corrida_id is None:
        sys.exit("No hay ninguna corrida del bronce terminada.")
    return corrida_id


def cmd_operones(args):
    """El distinto de operones del corpus, y que le falta al catalogo.

    Lo que el asesor quiere ver es la ultima columna del informe: los operones
    que el texto nombra y `operones_pao1.tsv` no conoce. Esos no expanden a
    ningun gen, asi que hoy el bronce sabe que el articulo hablo de un operon
    pero no de cual. Cada uno es una fila que le falta al catalogo.
    """
    ruta_datos = rutas.raiz_datos(args.datos)
    catalogo = operones.Catalogo.cargar(operones.RUTA_POR_OMISION)
    con = db.conectar(os.path.join(ruta_datos, "grn.db"))
    try:
        corrida_id = args.corrida or _ultima_corrida(con)
        filas = exportar.filas_operones(con, db, corrida_id, catalogo)
    finally:
        con.close()

    # El resumen se cuenta SIEMPRE sobre todos los operones, aunque el CSV
    # lleve solo los faltantes. Contarlo despues de filtrar daba "103 de 103,
    # el 100 % de las menciones", que es verdad sobre lo filtrado y mentira
    # sobre el corpus, que es de lo que el lector cree que le estan hablando.
    faltan = [f for f in filas if f["en_catalogo"] == "no"]
    escritas = faltan if args.solo_faltantes else filas

    # El nombre lleva la corrida, no solo el dia. Sin ella, mirar la corrida 1
    # despues de la 2 --que es lo natural al comparar versiones-- machacaba el
    # CSV bueno con uno vacio, el mismo dia y sin avisar.
    dia = datetime.date.today().strftime("%Y%m%d")
    ruta = os.path.join("salidas",
                        "operones_corrida%d_%s.csv" % (corrida_id, dia))
    exportar.escribir_csv(ruta, exportar.COLUMNAS_OPERONES, escritas, log)

    log("")
    if not filas:
        # Una corrida anterior a la version 2 guardaba las menciones de operon
        # como 'gen' o 'proteina', asi que no tiene ninguna fila de tipo
        # 'operon' y este informe sale vacio. Sin este aviso, "0 operones" se
        # lee como "el corpus no nombra operones", que es falso: son 7 136
        # menciones que esa corrida etiqueto de otra forma.
        log("  La corrida %d no tiene menciones de tipo 'operon'." % corrida_id)
        log("  Si es una corrida de la version 1, es lo esperado: entonces el")
        log("  operon se guardaba como gen o proteina. Vuelve a correr")
        log("  'exportar' para producir una corrida de la version actual.")
        log("")
    log("  corrida                      : %d" % corrida_id)
    log("  catalogo operones_pao1.tsv   : %d operones" % len(catalogo))
    log("  operones distintos en corpus : %d" % len(filas))
    log("  en el catalogo               : %d" % (len(filas) - len(faltan)))
    log("  FUERA del catalogo           : %d  (%s de las menciones)"
        % (len(faltan),
           _tasa(sum(f["n_menciones"] for f in faltan),
                 sum(f["n_menciones"] for f in filas))))
    log("  menciones de operon totales  : %d"
        % sum(f["n_menciones"] for f in filas))
    if args.solo_faltantes:
        log("  (el CSV lleva solo los %d faltantes; el resumen, todos)"
            % len(faltan))
    if faltan:
        log("")
        log("  Los %d que le faltan al catalogo, por menciones:" % len(faltan))
        log("    %-20s %9s %9s  %s" % ("operon", "menciones", "articulos",
                                       "superficies"))
        for f in sorted(faltan, key=lambda x: -x["n_menciones"])[:args.top]:
            sup = f["superficies"][:44]
            log("    %-20s %9d %9d  %s"
                % (f["operon"], f["n_menciones"], f["n_documentos"], sup))
        if len(faltan) > args.top:
            log("    ... y %d mas; estan todos en el CSV."
                % (len(faltan) - args.top))
    log("")
    log("  Un operon fuera del catalogo no expande a ningun gen: el bronce")
    log("  sabe que el articulo nombro un operon y no de que se compone.")
    log("  La expansion es solo por tabla, nunca deducida del nombre.")
    return 0


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
    ex.add_argument("--corrida", type=int, default=None,
                    help="Volcar esa corrida sin volver a identificar: sirve "
                         "para anotarla con recursos nuevos (la pertenencia "
                         "a operones) sin tocar lo que detecto. No la cierra "
                         "ni la modifica.")
    ex.set_defaults(func=cmd_exportar)

    pa = sub.add_parser("pares", help="Pares dirigidos de una corrida, a CSV.")
    pa.add_argument("--datos", help="Raiz de datos; gana sobre GRN_DATOS.")
    pa.add_argument("--corrida", type=int, default=None)
    pa.set_defaults(func=cmd_pares)

    op = sub.add_parser(
        "operones",
        help="Operones del corpus y los que le faltan al catalogo.")
    op.add_argument("--datos", help="Raiz de datos; gana sobre GRN_DATOS.")
    op.add_argument("--corrida", type=int, default=None)
    op.add_argument("--solo-faltantes", action="store_true",
                    dest="solo_faltantes",
                    help="Solo los que no estan en operones_pao1.tsv.")
    op.add_argument("--top", type=int, default=30,
                    help="Cuantos faltantes listar en pantalla (el CSV los "
                         "lleva todos).")
    op.set_defaults(func=cmd_operones)

    args = ap.parse_args()
    if getattr(args, "corpus", None) == "":
        args.corpus = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
