# -*- coding: utf-8 -*-
"""Paso 1: localiza elementos y oraciones candidatas. No verifica nada.

Lo que entrega es el DONDE. Que una oracion salga aqui no afirma que exista la
relacion, ni cual es su signo: eso pertenece al paso 2. La columna
`signo_sugerido` es lo que dice el lexico del disparador, no lo que dice el
articulo, y en esta literatura las dos cosas se contradicen a menudo -- "the
expression of mexEF-oprN was increased in the mexT mutant" lleva un verbo de
aumento y significa represion. Por eso va etiquetada NO VERIFICADO y no se usa
para nada aguas abajo.

**Escribe en las tablas del bronce, no en memoria.** La exportacion sale
despues de consultar esas tablas. Si la exportacion tuviera su propio camino,
un dia el archivo y la base dirian cosas distintas y no habria forma de saber
cual miente.

Se guardan TODAS las oraciones en `texto_unidades`, incluidas las que ningun
filtro deja pasar a candidata. Asi cambiar un umbral es una consulta y no una
relectura del corpus, y `n_oracion` indexa el documento completo.

No imprime: recibe un callable `log`.

Solo biblioteca estandar.
"""

import collections
import io
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, _RAIZ)
# `lexico` sigue viviendo en etapa2, que esta congelada. Se importa en vez de
# copiarse: dos diccionarios que divergen es el defecto que este proyecto no se
# puede permitir. Su mudanza a grn_bronce esta anotada como pendiente.
sys.path.insert(0, os.path.join(_RAIZ, "etapa2"))

from grn_bronce import db as _db                  # noqa: E402
from grn_bronce import texto as _texto            # noqa: E402
from grn_bronce import vocabulario as _vocab      # noqa: E402

VERSION = "1"
METODO = "baseline-deterministico"

# Una oracion mas corta que esto casi nunca es prosa; mas larga suele ser una
# tabla que el extractor de JATS aplano. Los mismos topes que ya usaba la
# etapa 2, para que las cifras sean comparables. Se aplican al elegir
# candidatas, no al guardar: la unidad se persiste igual.
MIN_ORACION = 40
MAX_ORACION = 700

# Tope de genes distintos por oracion. Hay parrafos que son listas de treinta
# ("the 30 most influential hubs"): ahi la coocurrencia no dice nada.
MAX_MENCIONES = 8

# Secciones que no aportan relaciones y si mucho ruido de nombres.
SECCIONES_FUERA = frozenset(["excluir"])


def cargar_lexico():
    """El diccionario PAO1, desde los recursos versionados del bronce."""
    from lexico import Lexico
    rec = os.path.join(AQUI, "recursos")
    return Lexico.cargar(os.path.join(rec, "genes_pao1.tsv"),
                         os.path.join(rec, "operones_pao1.tsv"))


def cargar_locus_tags():
    """{id_canonico: locus_tag}.

    El id canonico del lexico es el simbolo cuando existe y el locus tag
    cuando no. `PLAN.md` pide normalizar a locus tag, asi que hace falta el
    puente. No se cambia el id canonico: eso romperia el cruce con todo lo que
    ya se midio.
    """
    ruta = os.path.join(AQUI, "recursos", "genes_pao1.tsv")
    mapa = {}
    with io.open(ruta, encoding="utf-8") as f:
        cols = f.readline().rstrip("\n").split("\t")
        for linea in f:
            if not linea.strip():
                continue
            d = dict(zip(cols, linea.rstrip("\n").split("\t")))
            lt, simbolo = d.get("locus_tag") or "", d.get("simbolo") or ""
            if lt:
                mapa[lt] = lt
                if simbolo:
                    mapa[simbolo] = lt
    return mapa


def _es_proteina(superficie):
    """La forma proteina va capitalizada (`MexT`), el gen no (`mexT`).

    Es la convencion de la nomenclatura bacteriana y la unica senal que da el
    texto. No es infalible --una oracion que empieza por el gen lo capitaliza
    igual-- y por eso se guarda la superficie tal cual junto al locus tag.
    """
    return bool(superficie) and superficie[0].isupper()


def _entre(ini, fin, marcas):
    a, b = min(ini, fin), max(ini, fin)
    return sum(1 for m in marcas if a < m[0] < b)


def calcular_score(hay_disparador, disparador_entre, n_tf, n_evidencia,
                   intercalados):
    """Un numero transparente entre 0 y 1, para ordenar. NO calibrado.

    Formula escrita a mano, no aprendida: en esta capa no hay etiquetas con que
    aprender nada. Sirve para pedir "las k mejores"; **no se ha comprobado que
    ordenar por ella mejore la precision**, y hasta comprobarlo no debe usarse
    como umbral de decision.

    Los pesos salen de lo ya medido: exigir disparador en cualquier parte de la
    oracion movio la precision del entregable de 31.7 % a 33.0 %, o sea dentro
    del intervalo de confianza. Por eso el peso grande se lo lleva el
    disparador ENTRE los dos genes, que es mas estricto y cuyo efecto esta sin
    medir, y no la mera presencia.
    """
    s = 0.0
    if disparador_entre:
        s += 0.40
    elif hay_disparador:
        s += 0.20
    if n_tf == 1:
        s += 0.20
    if n_evidencia:
        s += 0.15
    s += 0.15 * (1.0 - min(intercalados, 5) / 5.0)
    return round(min(s, 1.0), 3)


def piezas_de_documento(fila, ruta_txt, clases):
    """[(fuente_texto, seccion, cuerpo, tramos)] en el orden del contrato.

    Abstract siempre; texto completo despues, y solo si `descargas` lo da por
    bueno. Si el documento tiene `.txt`, su resumen sale de ahi y no de la
    base: los dos son el mismo texto y contarlo dos veces inflaria la
    evidencia de cada arista.
    """
    piezas = []
    if ruta_txt and os.path.exists(ruta_txt):
        with io.open(ruta_txt, encoding="utf-8") as f:
            md = f.read()
        tiene_resumen = False
        for etiqueta, cuerpo, tramos in _texto.bloques_con_offset(md):
            clase = (clases.get(etiqueta, _texto.CLASE_DESCONOCIDA)
                     if etiqueta else _texto.CLASE_DESCONOCIDA)
            if clase == "abstract":
                tiene_resumen = True
            piezas.append(("xml", clase, cuerpo, tramos))
        if not tiene_resumen and (fila["abstract"] or "").strip():
            piezas.insert(0, ("abstract", "abstract", fila["abstract"], None))
        return piezas
    if (fila["abstract"] or "").strip():
        piezas.append(("abstract", "abstract", fila["abstract"], None))
    return piezas


def _menciones_de_oracion(oracion, lex, vocab, locus):
    """Las cinco clases, en la forma que espera `db.guardar_menciones()`."""
    genes = lex.menciones(oracion)
    disp = vocab.disparadores_en(oracion)
    func = vocab.funciones_en(oracion)
    evid = vocab.evidencia_en(oracion)
    orgs = _vocab.organismos_en(oracion)

    filas = []
    for i, f_, s_, idc, _tf in genes:
        filas.append({"tipo": "proteina" if _es_proteina(s_) else "gen",
                      "texto": s_, "id_normalizado": locus.get(idc, idc),
                      "offset_ini": i, "offset_fin": f_})
    for etiqueta, datos in (("disparador", disp), ("funcion", func),
                            ("evidencia", evid), ("organismo", orgs)):
        for i, f_, s_, extra in datos:
            filas.append({"tipo": etiqueta, "texto": s_,
                          "id_normalizado": extra,
                          "offset_ini": i, "offset_fin": f_})
    return filas, genes, disp, evid


def procesar_documento(con, corrida_id, fila, ruta_txt, lex, vocab, locus,
                       clases, cuenta):
    """Persiste las unidades, menciones y candidatas de un documento."""
    n_oracion = 0
    hubo_mencion = False

    for fuente, seccion, cuerpo, tramos in piezas_de_documento(
            fila, ruta_txt, clases):
        for ini, fin, oracion in _texto.oraciones_con_offset(cuerpo):
            if tramos is not None:
                a, b, contiguo = _texto.traducir_span(tramos, ini, fin)
                if a is None:
                    a, b, contiguo = ini, fin, False
            else:
                a, b, contiguo = ini, fin, True

            unidad_id = _db.guardar_unidad(con, corrida_id, {
                "pmid": fila["pmid"], "fuente_texto": fuente,
                "seccion": seccion, "num_oracion": n_oracion,
                "texto": oracion, "offset_ini": a, "offset_fin": b,
                "contiguo": contiguo})
            indice = n_oracion
            n_oracion += 1
            if not contiguo:
                cuenta["unidades_no_contiguas"] += 1

            filas_m, genes, disp, evid = _menciones_de_oracion(
                oracion, lex, vocab, locus)
            ids = _db.guardar_menciones(con, corrida_id, METODO, unidad_id,
                                        filas_m)
            if filas_m:
                hubo_mencion = True

            # --- de unidad a candidata
            largo = len(oracion)
            if largo < MIN_ORACION:
                cuenta["oraciones_cortas"] += 1
                continue
            if largo > MAX_ORACION:
                cuenta["oraciones_largas"] += 1
                continue
            if seccion in SECCIONES_FUERA:
                cuenta["oraciones_en_seccion_excluida"] += 1
                continue
            cuenta["oraciones_examinadas"] += 1

            distintos = set(g[3] for g in genes)
            if len(distintos) < 2:
                cuenta["oraciones_sin_par"] += 1
                continue
            if len(distintos) > MAX_MENCIONES:
                cuenta["oraciones_con_demasiados_genes"] += 1
                continue

            tfs = sorted(set(g[3] for g in genes if g[4]))
            regulador = blanco = ""
            if not disp:
                cuenta["sin_disparador"] += 1
            elif len(tfs) == 1:
                regulador = tfs[0]
                otros = sorted(distintos - {regulador})
                if len(otros) == 1:
                    blanco = otros[0]
                else:
                    cuenta["sin_blanco_unico"] += 1
            elif len(tfs) > 1:
                cuenta["dos_o_mas_tf"] += 1
            else:
                cuenta["sin_tf"] += 1

            entre, disp_entre = 0, False
            if regulador and blanco:
                pr = [g for g in genes if g[3] == regulador]
                pb = [g for g in genes if g[3] == blanco]
                if pr and pb:
                    x, y = pr[0][0], pb[0][0]
                    disp_entre = _entre(x, y, disp) > 0
                    entre = _entre(x, y, genes)

            _db.guardar_candidata(con, corrida_id, METODO, unidad_id, {
                "disparador": ";".join(sorted(set(d[2] for d in disp))),
                "signo_sugerido": ";".join(sorted(set(d[3] for d in disp))),
                "regulador_candidato": regulador,
                "blanco_candidato": blanco,
                "score": calcular_score(bool(disp), disp_entre, len(tfs),
                                        len(evid), entre),
            }, ids)
            _ = indice
    return hubo_mencion


def identificar(con, corrida_id, documentos, fulltext, lex, vocab, locus,
                log=lambda m: None):
    """Recorre el corpus y lo escribe en las tablas. Devuelve los contadores."""
    clases = _texto.cargar_clases()
    cuenta = collections.Counter()

    for i, fila in enumerate(documentos, 1):
        if i % 200 == 0:
            log("  %d de %d documentos" % (i, len(documentos)))
        ruta = fulltext.get(fila["pmid"])
        cuenta["documentos"] += 1
        if ruta and os.path.exists(ruta):
            cuenta["documentos_con_fulltext"] += 1
        elif ruta:
            cuenta["ruta_de_fulltext_no_existe"] += 1
        try:
            hubo = procesar_documento(con, corrida_id, fila, ruta, lex, vocab,
                                      locus, clases, cuenta)
            con.commit()
        except Exception as e:                       # noqa: BLE001
            con.rollback()
            cuenta["documentos_con_error"] += 1
            log("  ERROR en %s: %s" % (fila["pmid"], e))
            continue
        if not hubo:
            cuenta["documentos_sin_ninguna_mencion"] += 1

    return cuenta
