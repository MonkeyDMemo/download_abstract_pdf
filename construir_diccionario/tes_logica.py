#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valida la logica que NO necesita red: nombrado de operones (con hebra menos),
marca es_tf, sensibilidad de mayusculas, parseo de atributos GFF y sitios.
Corre: python3 test_logica.py"""
import construir_diccionario as C

fallos = 0


def chk(cond, etiqueta, obtenido=None):
    global fallos
    if cond:
        print(f"  ok   {etiqueta}")
    else:
        fallos += 1
        print(f"  FALLA {etiqueta}  -> obtenido: {obtenido!r}")


print("== _nombrar_operon (agrupado de prefijos) ==")
chk(C._nombrar_operon(["mexC", "mexD", "oprJ"]) == "mexCD-oprJ",
    "mexC,mexD,oprJ -> mexCD-oprJ", C._nombrar_operon(["mexC", "mexD", "oprJ"]))
chk(C._nombrar_operon(["mexA", "mexB", "oprM"]) == "mexAB-oprM",
    "mexA,mexB,oprM -> mexAB-oprM", C._nombrar_operon(["mexA", "mexB", "oprM"]))
chk(C._nombrar_operon(["pqsA", "pqsB", "pqsC", "pqsD", "pqsE"]) == "pqsABCDE",
    "pqsA..pqsE -> pqsABCDE", C._nombrar_operon(["pqsA", "pqsB", "pqsC", "pqsD", "pqsE"]))
chk(C._nombrar_operon(["rhlA", "rhlB"]) == "rhlAB",
    "rhlA,rhlB -> rhlAB", C._nombrar_operon(["rhlA", "rhlB"]))

print("== construir_operones (orden de transcripcion segun hebra) ==")
# mexCD-oprJ vive en la hebra menos: locus ascendente PA4597=oprJ, 4598=mexD,
# 4599=mexC. En sentido de transcripcion (hebra -) el orden se invierte y debe
# quedar mexC, mexD, oprJ -> "mexCD-oprJ".
filas = [
    {"locus_tag": "PA4597", "simbolo": "oprJ", "tipo": "protein_coding", "hebra": "-"},
    {"locus_tag": "PA4598", "simbolo": "mexD", "tipo": "protein_coding", "hebra": "-"},
    {"locus_tag": "PA4599", "simbolo": "mexC", "tipo": "protein_coding", "hebra": "-"},
    # operon en hebra mas (orden ascendente = orden de transcripcion)
    {"locus_tag": "PA0996", "simbolo": "pqsA", "tipo": "protein_coding", "hebra": "+"},
    {"locus_tag": "PA0997", "simbolo": "pqsB", "tipo": "protein_coding", "hebra": "+"},
    {"locus_tag": "PA0998", "simbolo": "pqsC", "tipo": "protein_coding", "hebra": "+"},
    {"locus_tag": "PA0999", "simbolo": "pqsD", "tipo": "protein_coding", "hebra": "+"},
    {"locus_tag": "PA1000", "simbolo": "pqsE", "tipo": "protein_coding", "hebra": "+"},
    # gen aislado (no debe formar operon) y uno en otra hebra pegado
    {"locus_tag": "PA2000", "simbolo": "abcD", "tipo": "protein_coding", "hebra": "+"},
    {"locus_tag": "PA2001", "simbolo": "xyzE", "tipo": "protein_coding", "hebra": "-"},
    # simbolo que NO cumple el patron (no cuenta): 4 minusculas
    {"locus_tag": "PA3000", "simbolo": "abcdE", "tipo": "protein_coding", "hebra": "+"},
]
ops = C.construir_operones(filas)
por_nombre = {o["operon"]: o for o in ops}
chk("mexCD-oprJ" in por_nombre, "detecta operon mexCD-oprJ", list(por_nombre))
if "mexCD-oprJ" in por_nombre:
    o = por_nombre["mexCD-oprJ"]
    chk(o["hebra"] == "-", "mexCD-oprJ marcado hebra -", o["hebra"])
    chk(o["miembros"] == "mexC|mexD|oprJ",
        "miembros en orden de transcripcion", o["miembros"])
    chk(o["locus_tags"] == "PA4599|PA4598|PA4597",
        "locus_tags invertidos en hebra -", o["locus_tags"])
chk("pqsABCDE" in por_nombre, "detecta operon pqsABCDE", list(por_nombre))
if "pqsABCDE" in por_nombre:
    chk(por_nombre["pqsABCDE"]["miembros"] == "pqsA|pqsB|pqsC|pqsD|pqsE",
        "pqsABCDE en orden ascendente (hebra +)",
        por_nombre["pqsABCDE"]["miembros"])
chk(len(ops) == 2, "solo 2 operones (aislados no cuentan)", len(ops))

print("== evidencia_tf (regla union de 5 senales; producto no dispara) ==")
es, fu = C.evidencia_tf({"GO:0003700"}, set(), "")
chk(es and "go_0003700" in fu, "GO:0003700 dispara es_tf", (es, fu))
es, fu = C.evidencia_tf({"GO:0006355"}, set(), "")
chk(es and "go_0006355" in fu, "GO:0006355 dispara es_tf", (es, fu))
es, fu = C.evidencia_tf(set(), {"Sigma factor"}, "RNA polymerase sigma factor RpoD")
chk(es and "kw_sigma_factor" in fu and "producto_refseq" in fu,
    "kw Sigma factor dispara + producto corrobora", (es, fu))
es, fu = C.evidencia_tf(set(), {"Two-component regulatory system"}, "")
chk(es and "kw_two_component" in fu, "kw Two-component dispara", (es, fu))
es, fu = C.evidencia_tf(set(), {"Transcription regulation"}, "")
chk(es and "kw_transcription_regulation" in fu, "kw Transcription regulation dispara", (es, fu))
es, fu = C.evidencia_tf(set(), set(), "transcriptional regulator LysR family")
chk((not es) and fu == [], "producto SOLO no dispara es_tf", (es, fu))
es, fu = C.evidencia_tf(set(), set(), "hypothetical protein")
chk((not es) and fu == [], "sin senal -> false", (es, fu))

print("== es_sensible (colisiones con ingles) ==")
chk(C.es_sensible(["fur"]) is True, "fur (3 letras) sensible")
chk(C.es_sensible(["cat"]) is True, "cat (palabra comun) sensible")
chk(C.es_sensible(["mexC"]) is False, "mexC no sensible")
chk(C.es_sensible(["oprM", "fur"]) is True, "una superficie corta basta")
chk(C.es_sensible(["lasR", "rhlR"]) is False, "lasR/rhlR no sensibles")

print("== _attrs (decodifica %XX del GFF) ==")
d = C._attrs("ID=gene-PA0001;locus_tag=PA0001;gene=dnaA;Note=DNA%20polymerase")
chk(d.get("locus_tag") == "PA0001", "locus_tag", d.get("locus_tag"))
chk(d.get("Note") == "DNA polymerase", "Note con %20 -> espacio", d.get("Note"))

print("== parse_gff (mini GFF sintetico) ==")
mini = "\n".join([
    "##gff-version 3",
    "NC_002516.2\tRefSeq\tgene\t100\t200\t.\t-\t.\tID=gene-PA4599;locus_tag=PA4599;gene=mexC",
    "NC_002516.2\tRefSeq\tCDS\t100\t200\t.\t-\t0\tID=cds1;locus_tag=PA4599;product=multidrug efflux RND membrane fusion protein MexC",
    "NC_002516.2\tRefSeq\tprotein_binding_site\t50\t70\t.\t+\t.\tbound_moiety=NfxB;Note=binding site%3B regulation for PA4599 and PA4597;experiment=EXP-IDA;Dbxref=PMID:12345",
])
genes, sitios = C.parse_gff(mini)
chk("PA4599" in genes and genes["PA4599"]["simbolo"] == "mexC",
    "gen PA4599 con simbolo mexC", genes.get("PA4599"))
chk(genes["PA4599"]["hebra"] == "-", "hebra - propagada", genes["PA4599"]["hebra"])
chk(genes["PA4599"]["producto"].startswith("multidrug efflux"),
    "producto del CDS", genes["PA4599"]["producto"])
chk(len(sitios) == 1 and sitios[0]["tf"] == "NfxB",
    "1 sitio con tf NfxB", sitios)
chk(sitios and set(sitios[0]["blancos"]) == {"PA4599", "PA4597"},
    "blancos PA4599 y PA4597 extraidos del Note", sitios[0]["blancos"] if sitios else None)
chk(sitios and sitios[0]["pmids"] == ["12345"], "pmid extraido", sitios[0]["pmids"] if sitios else None)

print("== construir_sitios (dedup de pares, factores) ==")
sr = [
    {"tf": "LasR", "blancos": ["PA3724", "PA1430"], "experimento": ["EXP-IDA"], "pmids": ["12345"]},
    {"tf": "LasR", "blancos": ["PA3724"], "experimento": [], "pmids": ["99999"]},
    {"tf": "", "blancos": ["PA0001"], "experimento": [], "pmids": []},   # sin tf -> se salta
    {"tf": "RhlR", "blancos": ["PA3479"], "experimento": ["EXP"], "pmids": []},
]
sit = C.construir_sitios(sr)
pares = {(r["tf"], r["blanco"]) for r in sit}
chk(("LasR", "PA3724") in pares and ("LasR", "PA1430") in pares,
    "pares de LasR presentes", pares)
lasr_3724 = next(r for r in sit if (r["tf"], r["blanco"]) == ("LasR", "PA3724"))
chk(lasr_3724["pmids"] == "12345|99999", "pmids fusionados y ordenados", lasr_3724["pmids"])
chk(len({r["tf"] for r in sit}) == 2, "2 factores (LasR, RhlR); tf vacio excluido",
    {r["tf"] for r in sit})
chk(len(sit) == 3, "3 pares totales", len(sit))

print()
if fallos == 0:
    print("TODO OK: la logica sin red pasa todas las pruebas.")
else:
    print(f"HAY {fallos} FALLA(S).")
    raise SystemExit(1)