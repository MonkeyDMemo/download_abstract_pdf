#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrae del corpus las oraciones sobre los represores de bombas RND.

Por que estos seis y no otros. MexR, NalC, NalD, NfxB, MexZ y MexL son
represores: la literatura no lo discute. Pero casi toda la evidencia esta
redactada desde el fenotipo del mutante --"mutations in nfxB lead to
overexpression of MexCD-OprJ"-- y un extractor que lea esa frase en
aislamiento saca ACTIVA cuando la relacion es REPRIME.

O sea que aqui hay un conjunto de prueba con la respuesta conocida de
antemano, y ademas es el subconjunto donde el modelo tiene mas probabilidad
de equivocarse. **Una oracion evaluable que el clasificador etiquete
'activates' es un error confirmado**, sin necesidad de anotar nada.

Tres cosas que se aprendieron leyendo lo que salia, y que estan aplicadas:

1. **Solo se buscan los pares TF -> bomba, no la autorregulacion.** Una
   oracion que nombra 'nalD' dos veces --una de ellas como 'DeltanalD'-- no
   afirma que NalD se regule a si mismo. Sin este corte, NalD -> nalD salia
   con 40 oraciones cuando el patron de oro lo da por no atestiguado, y tenia
   razon el patron.

2. **Solo son evaluables las oraciones que AFIRMAN la relacion**, o sea las
   redactadas de forma directa y las de fenotipo del mutante. Las que solo
   mencionan los dos genes juntos no dicen nada, y para ellas la etiqueta
   correcta seria 'no_relation', no 'represses'. Van en el archivo marcadas
   evaluable=false porque sirven de negativas realistas, que es justamente lo
   que le falta al entrenamiento.

3. **MexL no es solo represor.** Reprime mexJK pero ACTIVA los genes de
   fenazina (phz1, phz2, phzM), y el corpus lo dice con todas sus letras. El
   signo conocido vale para la bomba, no para el regulador entero.

Lo que produce: etapa2/auditoria_signo.tsv, una oracion por fila, con el signo
correcto, si es evaluable y como esta redactada. Se le puede pasar al modelo
tal cual.

Solo biblioteca estandar.

    python etapa2/auditar_signo.py
"""

import argparse
import collections
import csv
import json
import os
import re
import sqlite3
import sys

# Los seis, con las variantes con que el corpus los escribe. El gen va en
# minuscula y la proteina capitalizada, pero eso no se puede dar por hecho:
# los articulos mezclan las dos, asi que se busca sin distinguir mayusculas y
# se conserva la forma que aparecio.
#
# Los blancos incluyen los genes sueltos del operon: el corpus escribe tanto
# "mexAB-oprM" como "mexA" o "MexB" para la misma bomba.
BOMBA = {
    "mexAB-oprM": ["mexAB-oprM", "mexAB", "mexA", "mexB", "oprM"],
    "mexCD-oprJ": ["mexCD-oprJ", "mexCD", "mexC", "mexD", "oprJ"],
    "mexXY":      ["mexXY", "mexX", "mexY", "amrAB"],
    "mexJK":      ["mexJK", "mexJ", "mexK"],
    "armR":       ["armR", "PA3719", "PA3720-armR", "PA3720"],
}

# Solo el par TF -> bomba. La autorregulacion queda fuera a proposito: sin
# analisis sintactico no hay forma de distinguir "NalD reprime a nalD" de una
# oracion que nombra nalD dos veces, y al intentarlo salian 40 oraciones para
# un par que el patron de oro da por no atestiguado.
REPRESORES = {
    "MexR": {"alias": ["mexR"], "bomba": "mexAB-oprM"},
    "NalC": {"alias": ["nalC", "PA3721"], "bomba": "armR"},
    "NalD": {"alias": ["nalD", "PA3574"], "bomba": "mexAB-oprM"},
    "NfxB": {"alias": ["nfxB"], "bomba": "mexCD-oprJ"},
    "MexZ": {"alias": ["mexZ", "amrR", "PA2020"], "bomba": "mexXY"},
    # MexL reprime mexJK pero ACTIVA los genes de fenazina. El signo conocido
    # es el de la bomba; no se puede generalizar al regulador.
    "MexL": {"alias": ["mexL", "PA2390"], "bomba": "mexJK"},
}

# Las redacciones que AFIRMAN la relacion. Solo esas son evaluables: en las
# demas el modelo no se equivoca al no ver represion, porque no la hay escrita.
AFIRMAN = ("directa", "fenotipo_mutante")

# Redaccion desde el fenotipo del mutante: la trampa. Se exige que aparezcan
# las dos mitades --la perdida de funcion y el aumento de expresion-- porque
# por separado no significan nada.
PERDIDA = re.compile(
    r"\b(mutant|mutants|mutation|mutations|knockout|knock-out|deletion|"
    r"deleted|disrupt|disruption|inactivat|loss of|lacking|null|"
    r"insertional|Delta\s*|defective)", re.I)
AUMENTO = re.compile(
    r"\b(overexpress|over-express|overproduc|elevated|increased|"
    r"upregulat|up-regulat|hyperexpress|derepress|de-repress|"
    r"enhanced expression|higher levels?)", re.I)

# Redaccion directa: dice el signo con todas sus letras.
DIRECTA = re.compile(
    r"\b(repress|repressor|negative regulator|negatively regulat|"
    r"downregulat|down-regulat|silenc|represses)", re.I)

# La trampa al reves: dice "activa" de un represor. Casi siempre habla de otra
# cosa (activacion del sistema por el antirrepresor, por ejemplo), pero es
# justo lo que confunde a un extractor.
CONTRARIA = re.compile(
    r"\b(activat|positive regulator|positively regulat|induc|"
    r"upregulates|promotes expression)", re.I)

# Cortar en oraciones sin dependencias. El punto de una abreviatura comun no
# termina oracion; sin esta guarda, "et al." parte cada cita en dos.
ABREV = re.compile(
    r"\b(et al|e\.g|i\.e|vs|cf|Fig|Figs|Tab|approx|ca|no|No|spp|sp|"
    r"subsp|str|var|Dr|Prof|St|Inc|Ltd|min|sec|hr|h|mL|mg|kb|bp)\.$")


def oraciones(texto):
    """Parte en oraciones. Heuristica, suficiente para prosa cientifica."""
    trozos = re.split(r"(?<=[.!?])\s+", texto)
    salida, acumulado = [], ""
    for t in trozos:
        acumulado = (acumulado + " " + t).strip() if acumulado else t
        if ABREV.search(acumulado) or re.search(r"\b[A-Z]\.$", acumulado):
            continue
        salida.append(acumulado)
        acumulado = ""
    if acumulado:
        salida.append(acumulado)
    return salida


def patron(nombres):
    """Une varios nombres de gen en una expresion con frontera de palabra.

    El guion y los digitos cuentan como parte del nombre: sin eso, 'mexA'
    casaria dentro de 'mexAB-oprM' y se contaria dos veces la misma mencion.
    """
    partes = sorted((re.escape(n) for n in nombres), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(partes) + r")(?![A-Za-z0-9])", re.I)


def clasificar(oracion):
    """Como esta redactada la evidencia."""
    p, a = PERDIDA.search(oracion), AUMENTO.search(oracion)
    if p and a:
        return "fenotipo_mutante"
    if DIRECTA.search(oracion):
        return "directa"
    if CONTRARIA.search(oracion):
        return "contraria_aparente"
    return "otra"


def texto_de(pmid, salida):
    for nombre in os.listdir(salida):
        if nombre.startswith(pmid + "_") and nombre.endswith(".txt"):
            with open(os.path.join(salida, nombre), encoding="utf-8") as f:
                return f.read()
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Extrae oraciones sobre los represores de bombas RND.")
    ap.add_argument("--db", default="datos/grn.db")
    ap.add_argument("--fulltext", default="datos/fulltext/xml")
    ap.add_argument("--salida", default="etapa2/auditoria_signo.tsv")
    ap.add_argument("--max_por_par", type=int, default=40,
                    help="Tope de oraciones por par, para que un solo articulo "
                         "prolijo no domine el conjunto.")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    docs = con.execute(
        "SELECT pmid, titulo, abstract FROM documentos").fetchall()
    con.close()
    print("Corpus: %d documentos en la base." % len(docs))

    archivos = {}
    if os.path.isdir(args.fulltext):
        for n in os.listdir(args.fulltext):
            if n.endswith(".txt"):
                archivos[n.split("_")[0]] = os.path.join(args.fulltext, n)
    print("        %d con texto completo." % len(archivos))

    # Precompilar: son 12 pares y el corpus tiene millones de oraciones.
    pares = []
    for tf, d in REPRESORES.items():
        pares.append((tf, d["bomba"], patron(d["alias"]), patron(BOMBA[d["bomba"]])))
    print("        %d pares a buscar.\n" % len(pares))

    filas = []
    cuenta = collections.Counter()
    for i, doc in enumerate(docs, 1):
        pmid = str(doc["pmid"])
        piezas = []
        if doc["abstract"]:
            piezas.append(("abstract", doc["abstract"]))
        if pmid in archivos:
            with open(archivos[pmid], encoding="utf-8") as f:
                piezas.append(("fulltext", f.read()))

        for fuente, texto in piezas:
            # Filtro barato antes del caro: si el nombre del TF no esta en
            # todo el documento, no hay para que partirlo en oraciones.
            bajo = texto.lower()
            candidatos = [p for p in pares if p[2].search(bajo)]
            if not candidatos:
                continue
            for o in oraciones(texto):
                if len(o) < 40 or len(o) > 700:
                    continue
                for tf, blanco, rtf, rbl in candidatos:
                    if cuenta[(tf, blanco)] >= args.max_por_par:
                        continue
                    mtf, mbl = rtf.search(o), rbl.search(o)
                    if not (mtf and mbl) or mtf.span() == mbl.span():
                        continue
                    red = clasificar(o)
                    filas.append({
                        "pmid": pmid, "fuente": fuente,
                        "tf": tf, "blanco": blanco,
                        "signo_correcto": "represses" if red in AFIRMAN else "",
                        "evaluable": "true" if red in AFIRMAN else "false",
                        "redaccion": red,
                        "mencion_tf": mtf.group(0),
                        "mencion_blanco": mbl.group(0),
                        "oracion": " ".join(o.split()),
                    })
                    cuenta[(tf, blanco)] += 1
        if i % 500 == 0:
            print("  %d/%d documentos, %d oraciones" % (i, len(docs), len(filas)))

    # Quitar la misma oracion repetida para el mismo par: hay articulos que
    # citan textualmente a otros.
    vistas, unicas = set(), []
    for f in filas:
        k = (f["tf"], f["blanco"], f["oracion"])
        if k not in vistas:
            vistas.add(k)
            unicas.append(f)

    unicas.sort(key=lambda f: (f["tf"], f["blanco"], f["redaccion"], f["pmid"]))
    os.makedirs(os.path.dirname(args.salida) or ".", exist_ok=True)
    cols = ["pmid", "fuente", "tf", "blanco", "signo_correcto", "evaluable",
            "redaccion", "mencion_tf", "mencion_blanco", "oracion"]
    with open(args.salida, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t")
        w.writeheader()
        for r in unicas:
            w.writerow(r)

    print("\n%d oraciones unicas -> %s\n" % (len(unicas), args.salida))
    print("%-7s %-14s %6s  %s" % ("tf", "blanco", "n", "por redaccion"))
    print("-" * 78)
    porpar = collections.defaultdict(collections.Counter)
    for r in unicas:
        porpar[(r["tf"], r["blanco"])][r["redaccion"]] += 1
    for (tf, bl), c in sorted(porpar.items()):
        det = "  ".join("%s=%d" % (k, v) for k, v in c.most_common())
        print("%-7s %-14s %6d  %s" % (tf, bl, sum(c.values()), det))

    print("")
    tot = collections.Counter(r["redaccion"] for r in unicas)
    for k, v in tot.most_common():
        print("  %-20s %4d  (%2.0f%%)%s"
              % (k, v, 100.0 * v / len(unicas),
                 "   <- evaluable" if k in AFIRMAN else ""))

    ev = [r for r in unicas if r["evaluable"] == "true"]
    trampa = [r for r in ev if r["redaccion"] == "fenotipo_mutante"]
    print("")
    print("CONJUNTO EVALUABLE: %d oraciones, todas con signo conocido "
          "'represses'." % len(ev))
    print("  De ellas %d estan redactadas desde el fenotipo del mutante: la"
          % len(trampa))
    print("  represion se afirma DICIENDO LO CONTRARIO ('al romper el represor")
    print("  sube la expresion'). Ahi es donde un extractor saca 'activates'.")
    print("")
    print("Las %d no evaluables no son basura: son co-menciones sin relacion"
          % (len(unicas) - len(ev)))
    print("afirmada, o sea negativas realistas del mismo dominio. Es justo el")
    print("tipo de negativa que le falta al entrenamiento, donde el 98% de los")
    print("'no_relation' son 'marcaste la mencion equivocada'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
