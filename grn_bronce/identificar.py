# -*- coding: utf-8 -*-
"""Paso 1: localiza elementos y oraciones candidatas. No verifica nada.

Lo que entrega es el DONDE. Que una oracion salga aqui no afirma que exista la
relacion, ni cual es su signo: eso pertenece al paso 2. La columna
`signo_sugerido` es lo que dice el lexico del disparador, no lo que dice el
articulo, y en esta literatura las dos cosas se contradicen a menudo -- "the
expression of mexEF-oprN was increased in the mexT mutant" lleva un verbo de
aumento y significa represion. Por eso la columna va etiquetada NO VERIFICADO
en la exportacion y no se usa para nada aguas abajo.

No imprime: recibe un callable `log`, como el resto de la orquestacion.

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

from grn_bronce import texto as _texto            # noqa: E402
from grn_bronce import vocabulario as _vocab      # noqa: E402

VERSION = "1"
METODO = "baseline-deterministico"

# Una oracion mas corta que esto casi nunca es prosa; mas larga suele ser una
# tabla que el extractor de JATS aplano. Los mismos topes que ya usaba la
# etapa 2, para que las cifras sean comparables.
MIN_ORACION = 40
MAX_ORACION = 700

# Tope de menciones distintas por oracion. Hay parrafos que son listas de
# treinta genes ("the 30 most influential hubs"): ahi la coocurrencia no dice
# nada y solo multiplica pares.
MAX_MENCIONES = 8


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
    puente. Se guardan los dos: cambiar el id canonico romperia el cruce con
    todo lo que ya se midio.
    """
    ruta = os.path.join(AQUI, "recursos", "genes_pao1.tsv")
    mapa = {}
    with io.open(ruta, encoding="utf-8") as f:
        cols = f.readline().rstrip("\n").split("\t")
        for linea in f:
            if not linea.strip():
                continue
            d = dict(zip(cols, linea.rstrip("\n").split("\t")))
            lt = d.get("locus_tag") or ""
            simbolo = d.get("simbolo") or ""
            if lt:
                mapa[lt] = lt
                if simbolo:
                    mapa[simbolo] = lt
    return mapa


def _es_proteina(superficie):
    """La forma proteina va capitalizada (`MexT`), el gen no (`mexT`).

    Es la convencion de la nomenclatura bacteriana y la unica senal que da el
    texto. No es infalible --una oracion que empieza por el gen lo capitaliza
    igual-- y por eso se reporta la superficie tal cual junto al locus tag.
    """
    return bool(superficie) and superficie[0].isupper()


def _entre(ini, fin, marcas):
    """Cuantas marcas caen estrictamente entre dos posiciones."""
    a, b = min(ini, fin), max(ini, fin)
    return sum(1 for m in marcas if a < m[0] < b)


def calcular_score(hay_disparador, disparador_entre, n_tf, n_evidencia,
                   intercalados):
    """Un numero transparente entre 0 y 1, para ordenar. NO calibrado.

    Es una formula escrita a mano, no aprendida: no hay etiquetas con que
    aprender nada en esta capa. Sirve para poder pedir "las k mejores" y para
    que exista la columna que `PLAN.md` pide; **no se ha comprobado que
    ordenar por ella mejore la precision**, y hasta que se compruebe no debe
    usarse como umbral de decision.

    Los pesos salen de lo que ya se midio en este proyecto: exigir disparador
    en cualquier parte de la oracion sube la precision del entregable de
    31.7 % a 33.0 %, o sea dentro del intervalo de confianza. Por eso el peso
    grande se lo lleva el disparador ENTRE los dos genes, que es mas estricto y
    cuyo efecto esta sin medir, y no la mera presencia.
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
            clase = clases.get(etiqueta, _texto.CLASE_DESCONOCIDA) \
                if etiqueta else _texto.CLASE_DESCONOCIDA
            if clase == "abstract":
                tiene_resumen = True
            piezas.append(("xml", clase, cuerpo, tramos))
        if not tiene_resumen and (fila["abstract"] or "").strip():
            piezas.insert(0, ("abstract", "abstract",
                              fila["abstract"], None))
        return piezas
    if (fila["abstract"] or "").strip():
        piezas.append(("abstract", "abstract", fila["abstract"], None))
    return piezas


def procesar_documento(fila, ruta_txt, lex, vocab, locus, clases, cuenta):
    """(candidatas, menciones) de un documento. Listas de dict."""
    candidatas, menciones = [], []
    n_oracion = 0

    for fuente, seccion, cuerpo, _tramos in piezas_de_documento(
            fila, ruta_txt, clases):
        for _ini, _fin, oracion in _texto.oraciones_con_offset(cuerpo):
            largo = len(oracion)
            if largo < MIN_ORACION:
                cuenta["oraciones_cortas"] += 1
                continue
            if largo > MAX_ORACION:
                cuenta["oraciones_largas"] += 1
                continue
            cuenta["oraciones_examinadas"] += 1
            indice = n_oracion
            n_oracion += 1

            genes = lex.menciones(oracion)
            disp = vocab.disparadores_en(oracion)
            func = vocab.funciones_en(oracion)
            evid = vocab.evidencia_en(oracion)
            orgs = _vocab.organismos_en(oracion)

            base = {"pmid": fila["pmid"], "fuente_texto": fuente,
                    "seccion": seccion, "num_oracion": indice}
            for i, f_, s_, idc, _tf in genes:
                menciones.append(dict(
                    base, tipo="proteina" if _es_proteina(s_) else "gen",
                    texto=s_, id_normalizado=locus.get(idc, idc),
                    offset_ini=i, offset_fin=f_))
            for i, f_, s_, sig in disp:
                menciones.append(dict(base, tipo="disparador", texto=s_,
                                      id_normalizado=sig,
                                      offset_ini=i, offset_fin=f_))
            for i, f_, s_, cat in func:
                menciones.append(dict(base, tipo="funcion", texto=s_,
                                      id_normalizado=cat,
                                      offset_ini=i, offset_fin=f_))
            for i, f_, s_, tec in evid:
                menciones.append(dict(base, tipo="evidencia", texto=s_,
                                      id_normalizado=tec,
                                      offset_ini=i, offset_fin=f_))
            for i, f_, s_, forma in orgs:
                menciones.append(dict(base, tipo="organismo", texto=s_,
                                      id_normalizado=forma,
                                      offset_ini=i, offset_fin=f_))

            distintos = set(g[3] for g in genes)
            if len(distintos) < 2:
                cuenta["oraciones_sin_par"] += 1
                continue
            if len(distintos) > MAX_MENCIONES:
                cuenta["oraciones_con_demasiadas_menciones"] += 1
                continue

            tfs = sorted(set(g[3] for g in genes if g[4]))
            regulador = blanco = ""
            if disp:
                if len(tfs) == 1:
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
            else:
                cuenta["sin_disparador"] += 1

            entre = 0
            disp_entre = False
            if regulador and blanco:
                pr = [g for g in genes if g[3] == regulador]
                pb = [g for g in genes if g[3] == blanco]
                if pr and pb:
                    a, b = pr[0][0], pb[0][0]
                    disp_entre = _entre(a, b, disp) > 0
                    entre = _entre(a, b, genes)

            candidatas.append({
                "pmid": fila["pmid"], "doi": fila["doi"] or "",
                "titulo": fila["titulo"] or "", "anio": fila["anio"] or "",
                "revista": fila["revista"] or "",
                "fecha_ingesta": fila["extraido_en"] or "",
                "fuente_texto": fuente, "seccion": seccion,
                "num_oracion": indice, "oracion": oracion,
                "genes": ";".join(sorted(set(g[2] for g in genes))),
                "genes_locus_tag": ";".join(
                    sorted(set(locus[g[3]] for g in genes if g[3] in locus))),
                "proteinas": ";".join(
                    sorted(set(g[2] for g in genes if _es_proteina(g[2])))),
                "regulador_candidato": regulador,
                "blanco_candidato": blanco,
                "disparador": ";".join(sorted(set(d[2] for d in disp))),
                "signo_sugerido": ";".join(sorted(set(d[3] for d in disp))),
                "funciones_biologicas": ";".join(
                    sorted(set(f[2] for f in func))),
                "evidencia_experimental": ";".join(
                    sorted(set(e[3] for e in evid))),
                "organismo": ";".join(sorted(set(o[2] for o in orgs))),
                "score": calcular_score(bool(disp), disp_entre, len(tfs),
                                        len(evid), entre),
            })
    return candidatas, menciones


def identificar(documentos, fulltext, lex, vocab, locus, log=lambda m: None):
    """Recorre el corpus. Devuelve (candidatas, menciones, cuenta)."""
    clases = _texto.cargar_clases()
    cuenta = collections.Counter()
    candidatas, menciones = [], []
    sin_mencion = []

    for i, fila in enumerate(documentos, 1):
        if i % 250 == 0:
            log("  %d de %d documentos" % (i, len(documentos)))
        ruta = fulltext.get(fila["pmid"])
        cuenta["documentos"] += 1
        if ruta and os.path.exists(ruta):
            cuenta["documentos_con_fulltext"] += 1
        elif ruta:
            cuenta["ruta_de_fulltext_no_existe"] += 1
        try:
            c, m = procesar_documento(fila, ruta, lex, vocab, locus, clases,
                                      cuenta)
        except Exception as e:                       # noqa: BLE001
            cuenta["documentos_con_error"] += 1
            log("  ERROR en %s: %s" % (fila["pmid"], e))
            continue
        if not m:
            sin_mencion.append(fila["pmid"])
        candidatas.extend(c)
        menciones.extend(m)

    cuenta["documentos_sin_ninguna_mencion"] = len(sin_mencion)
    return candidatas, menciones, cuenta
