#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Donde se pierden las relaciones de CollecTF que la red no recupera.

POR QUE EXISTE ESTE ARCHIVO
---------------------------
La exhaustividad contra CollecTF sale del 38%, contra el 95% del patron de oro
propio. La pregunta que sigue es **si la culpa es del modelo o del corpus**, y
la respuesta cambia por completo que hacer despues.

Este analisis se hizo primero a mano, en una sesion, y de ahi salieron las
cifras que el informe de avance publicaba: 55% nunca fue candidato, 89% de esos
sin el blanco nombrado, 76.8% de exhaustividad sobre lo recuperable de prosa.
Una revision encontro dos defectos de ese trabajo a mano:

1. **Ningun script lo producia**, asi que nadie podia reproducirlo ni
   comprobarlo. Un numero de comite que solo vive en la memoria de quien lo
   calculo no es un numero.
2. **Se calculo sobre la corrida anterior** a la correccion del diccionario, y
   se publico junto a cifras de la corrida nueva. Dos corridas mezcladas en la
   misma tabla es exactamente el defecto que `procedencia.py` vino a impedir.

Por eso esto es un script, se sella con la huella de sus entradas, y publica el
denominador de cada porcentaje.

EL CORTE QUE HAY QUE MIRAR CON CUIDADO
--------------------------------------
La cifra mas delicada es la exhaustividad **sobre lo recuperable de prosa**, que
excluye del denominador los pares cuyo gen blanco no se nombra en ningun
articulo. Es legitima --ningun clasificador recupera un gen que el texto no
menciona-- pero es un denominador construido despues de ver los datos, y por eso
se publica siempre junto a la bruta y con su exclusion contada.

**Y tiene un supuesto que hay que declarar:** que el blanco "no se nombra" se
decide con el diccionario. Si el diccionario no sabe traducir un locus tag al
nombre que usa la prosa, el par cuenta como no recuperable cuando en realidad es
un fallo del diccionario. Ese caso se cuenta aparte.

    python etapa2/analizar_perdidas.py
"""

import argparse
import collections
import csv
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import procedencia                      # noqa: E402
import evaluar_oro as O                 # noqa: E402


def canonizar(dicc):
    def canon(n):
        s, b = set(), (n or "").lower()
        if b in dicc:
            s.add(dicc[b])
        for m in O.miembros_operon(n or ""):
            if m.lower() in dicc:
                s.add(dicc[m.lower()])
        return s or {b}
    return canon


def superficies_por_locus(ruta):
    sup = collections.defaultdict(set)
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            for k in ("locus_tag", "simbolo"):
                if r[k]:
                    sup[r["locus_tag"]].add(r[k])
            for a in (r["alias"] or "").split("|"):
                if a.strip():
                    sup[r["locus_tag"]].add(a.strip())
    return sup


def aparece(nombres, texto):
    for n in nombres:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])",
                     texto, re.I):
            return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Donde se pierden los pares de CollecTF que la red no recupera.")
    ap.add_argument("--red", default="datos_etapa2/red.tsv")
    ap.add_argument("--pares", default="datos_etapa2/pares.jsonl")
    ap.add_argument("--collectf", default="etapa2/collectf_pao1.tsv")
    ap.add_argument("--genes", default="etapa2/genes_pao1.tsv")
    ap.add_argument("--operones", default="etapa2/operones_pao1.tsv")
    ap.add_argument("--db", default="datos/grn.db")
    ap.add_argument("--fulltext", default="datos/fulltext/xml")
    ap.add_argument("--salida", default="datos_etapa2/perdidas_collectf.json")
    args = ap.parse_args(argv)

    dicc, _ = O.cargar_diccionario(args.genes)
    canon = canonizar(dicc)
    sup = superficies_por_locus(args.genes)

    cand = set()
    with open(args.pares, encoding="utf-8") as f:
        for l in f:
            if l.strip():
                d = json.loads(l)
                for a in canon(d["tf"]):
                    for b in canon(d["target"]):
                        cand.add((a, b))
    red = set()
    with open(args.red, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            for a in canon(r["tf"]):
                for b in canon(r["blanco"]):
                    red.add((a, b))

    txt = {}
    if os.path.isdir(args.fulltext):
        for n in os.listdir(args.fulltext):
            if n.endswith(".txt"):
                txt[n.split("_")[0]] = os.path.join(args.fulltext, n)
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    def cuerpo(pmid):
        if pmid in txt:
            with open(txt[pmid], encoding="utf-8", errors="replace") as f:
                return f.read()
        r = con.execute("SELECT titulo, abstract FROM documentos WHERE pmid=?",
                        (pmid,)).fetchone()
        return ((r["titulo"] or "") + " " + (r["abstract"] or "")) if r else ""

    with open(args.collectf, encoding="utf-8") as f:
        ct = list(csv.DictReader(f, delimiter="\t"))

    grupos = collections.Counter()
    tecnicas = collections.defaultdict(collections.Counter)
    detalle = collections.Counter()
    sin_superficie = 0

    for r in ct:
        par = [(a, b) for a in canon(r["tf"]) for b in canon(r["blanco"])]
        if any(p in red for p in par):
            g = "recuperada"
        elif any(p in cand for p in par):
            g = "candidato_sin_arista"
        elif r["en_corpus"] != "true":
            g = "articulo_ausente"
        else:
            g = "nunca_candidato"
        grupos[g] += 1
        for e in (r["experimento"] or "").split("|"):
            if e.strip():
                tecnicas[g][e.strip()] += 1

        if g != "nunca_candidato":
            continue
        # Por que nunca fue candidato: ¿se nombran los dos genes?
        ntf, nbl = set(), set()
        for lt in canon(r["tf"]):
            ntf |= sup.get(lt, {r["tf"]})
        for lt in canon(r["blanco"]):
            nbl |= sup.get(lt, {r["blanco"]})
        # Si el diccionario no sabe ninguna superficie ademas del locus tag, el
        # fallo es del diccionario y no del corpus. Se cuenta aparte.
        solo_locus = all(re.fullmatch(r"PA\d+", x) for x in nbl) if nbl else True
        vt = vb = False
        for p in (r["pmids"] or "").split(","):
            p = p.strip()
            if not p:
                continue
            t = cuerpo(p)
            if not t:
                continue
            vt = vt or aparece(ntf, t)
            vb = vb or aparece(nbl, t)
        if vt and vb:
            detalle["los_dos_se_nombran_pero_nunca_juntos"] += 1
        elif vt:
            detalle["el_blanco_no_se_nombra"] += 1
            if solo_locus:
                sin_superficie += 1
        elif vb:
            detalle["el_tf_no_se_nombra"] += 1
        else:
            detalle["ninguno_se_nombra"] += 1

    total = len(ct)
    recup = grupos["recuperada"]
    no_recup = total - recup
    no_nombrado = detalle["el_blanco_no_se_nombra"] + detalle["ninguno_se_nombra"]
    recuperable = total - no_nombrado - grupos["articulo_ausente"]

    r = collections.OrderedDict()
    r["que_es"] = ("Donde se pierden los pares de CollecTF. Cada porcentaje "
                   "lleva su denominador porque los grupos se cuentan sobre el "
                   "total y los detalles sobre el subgrupo.")
    r["pares_de_collectf"] = total
    r["grupos"] = collections.OrderedDict(
        (k, {"n": v, "de": total, "tasa": round(float(v) / total, 4)})
        for k, v in [(g, grupos[g]) for g in
                     ("recuperada", "candidato_sin_arista", "nunca_candidato",
                      "articulo_ausente")])
    r["por_que_nunca_fue_candidato"] = collections.OrderedDict(
        (k, {"n": v, "de": grupos["nunca_candidato"],
             "tasa": round(float(v) / max(grupos["nunca_candidato"], 1), 4)})
        for k, v in detalle.most_common())
    r["blancos_sin_superficie_en_el_diccionario"] = {
        "n": sin_superficie,
        "que_es": ("de los que 'no se nombran', cuantos son casos en que el "
                   "diccionario solo conoce el locus tag: ahi el fallo es del "
                   "diccionario, no del corpus")}
    r["exhaustividad"] = collections.OrderedDict([
        ("bruta", {"n": recup, "de": total, "tasa": round(float(recup)/total, 4)}),
        ("sobre_lo_recuperable_de_prosa",
         {"n": recup, "de": recuperable,
          "tasa": round(float(recup) / max(recuperable, 1), 4),
          "excluye": ("%d pares cuyo blanco no se nombra y %d sin articulo en "
                      "el corpus" % (no_nombrado, grupos["articulo_ausente"])),
          "aviso": ("denominador construido despues de ver los datos: se "
                    "publica solo junto a la bruta")}),
        ("no_recuperadas", no_recup),
    ])
    r["tecnicas"] = collections.OrderedDict()
    for g in ("recuperada", "nunca_candidato"):
        t = sum(tecnicas[g].values())
        r["tecnicas"][g] = collections.OrderedDict(
            (k, {"n": v, "de": t, "tasa": round(float(v)/max(t, 1), 4)})
            for k, v in tecnicas[g].most_common(8))
    r["huellas"] = procedencia.sellar({"red": args.red, "pares": args.pares,
                                       "collectf": args.collectf,
                                       "genes": args.genes})

    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)

    print("CollecTF: %d pares" % total)
    print()
    print("  %-26s %6s %8s" % ("donde queda", "n", "de 333"))
    print("  " + "-" * 44)
    for k, v in r["grupos"].items():
        print("  %-26s %6d %7.1f%%" % (k, v["n"], 100 * v["tasa"]))
    print()
    print("  de los %d que nunca fueron candidato:" % grupos["nunca_candidato"])
    for k, v in r["por_que_nunca_fue_candidato"].items():
        print("     %-42s %4d %6.1f%%" % (k, v["n"], 100 * v["tasa"]))
    if sin_superficie:
        print("     (%d de esos son blancos que el diccionario solo conoce por "
              "locus tag: fallo del diccionario)" % sin_superficie)
    print()
    e = r["exhaustividad"]
    print("  EXHAUSTIVIDAD bruta                    %.1f%%  (%d de %d)"
          % (100 * e["bruta"]["tasa"], e["bruta"]["n"], e["bruta"]["de"]))
    print("  EXHAUSTIVIDAD sobre lo recuperable     %.1f%%  (%d de %d)"
          % (100 * e["sobre_lo_recuperable_de_prosa"]["tasa"],
             e["sobre_lo_recuperable_de_prosa"]["n"],
             e["sobre_lo_recuperable_de_prosa"]["de"]))
    print("     excluye %s" % e["sobre_lo_recuperable_de_prosa"]["excluye"])
    print()
    for g in ("recuperada", "nunca_candidato"):
        print("  tecnicas de las '%s':" % g)
        for k, v in list(r["tecnicas"][g].items())[:5]:
            print("     %-44s %5.1f%%" % (k[:44], 100 * v["tasa"]))
    print()
    print("Escrito %s" % args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
