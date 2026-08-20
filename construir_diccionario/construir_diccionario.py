#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Construye un diccionario de genes de Pseudomonas aeruginosa PAO1 desde tres
fuentes publicas (RefSeq GFF, KEGG, UniProt), para reconocer menciones de genes
en texto cientifico. Solo biblioteca estandar de Python 3.8+.

QUE PRODUCE (en la carpeta diccionario_independiente/):
  - genes.tsv          un renglon por locus_tag PA####
  - operones.tsv       operones derivados del propio diccionario
  - sitios_union.tsv   pares TF -> blanco con evidencia experimental (del GFF)
  - cache/             respuestas crudas, para no re-golpear las fuentes

HONESTIDAD SOBRE LA MARCA es_tf (LEER):
  Ningun campo de estas fuentes dice, con autoridad, "esto es un factor de
  transcripcion". Los terminos GO (GO:0003700, GO:0006355) y las palabras clave
  de UniProt ("Transcription regulation", "Sigma factor", "Two-component
  regulatory system") son INFERENCIA CURADA, buena parte por similitud de
  dominio, no medicion directa. En consecuencia, la marca es_tf SOBRE-INCLUYE:
    - la mitad SENSORA de los sistemas de dos componentes (histidina-cinasas),
      que NO se une a ADN;
    - los factores anti-sigma.
  Esto no es un bug a corregir: es el costo de usar anotacion de secuencia en
  lugar de una lista de relaciones regulatorias. Se documenta y se deja asi.

NO-CONTAMINACION (importante para la evaluacion posterior):
  El diccionario NO se construye, ni parcial ni totalmente, a partir de ninguna
  lista de relaciones regulatorias conocidas. Sale solo del genoma y de las
  anotaciones de secuencia. Por eso la columna `fuente` solo admite: refseq,
  kegg, uniprot. Los sitios_union del GFF (salida C) son evidencia experimental
  de secuencia y viven en su propio archivo; NO alimentan la marca es_tf ni el
  conjunto de genes.

NOTA sobre pseudomonas.com: no se usa. Devuelve 403 a urllib (proteccion de
bot) y saltarlo exigiria un navegador headless; queda fuera del alcance.
"""

import os
import re
import gzip
import time
import urllib.request
import urllib.parse

# ---------------------------------------------------------------------------
# Rutas y fuentes
# ---------------------------------------------------------------------------
BASE = "diccionario_independiente"
CACHE = os.path.join(BASE, "cache")

URL_REFSEQ = ("https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/006/765/"
              "GCF_000006765.1_ASM676v1/GCF_000006765.1_ASM676v1_genomic.gff.gz")
URL_KEGG = "https://rest.kegg.jp/list/pae"
URL_UNIPROT = ("https://rest.uniprot.org/uniprotkb/search"
               "?query=proteome:UP000002438&format=tsv&size=500"
               "&fields=accession,gene_names,go_id,keyword")

UA = {"User-Agent": "diccionario-pao1/1.0 (Python urllib; uso academico)"}

# Cifras de control del GFF (si no salen, algo cambio en la fuente)
GFF_LEN_ESPERADO = 3243384
GFF_LOCUS_ESPERADO = 11599
GFF_PBS_ESPERADO = 532

# Palabras inglesas cortas que colisionan con simbolos de gen en texto en ingles
PALABRAS_COMUNES = {"cat", "his", "fur", "rho", "map", "sec", "ser", "leu",
                    "sad", "fis", "can", "top", "min", "pro", "met", "arg",
                    "lys", "ala", "gly", "thr"}

RE_LOCUS = re.compile(r"^PA\d{4}(\.\d)?$")
RE_LOCUS_EN_TEXTO = re.compile(r"PA\d{4}")
RE_SIMBOLO_OPERON = re.compile(r"^[a-z]{3}[A-Z]$")   # mexA, oprJ, pqsB
RE_SIMBOLO_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,11}$")
# El producto de RefSeq puede corroborar (no dispara es_tf, ver regla)
RE_PROD_TF = re.compile(
    r"transcriptional regulator|transcription factor|sigma[- ]?factor|"
    r"sigma-\d|two-component|response regulator|transcriptional activator|"
    r"transcriptional repressor|DNA-binding|helix-turn-helix|winged helix",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Descarga con cache (respuestas crudas en disco)
# ---------------------------------------------------------------------------
def _abrir(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=120)


def bajar(url, nombre_cache, binario=False):
    """Baja url una vez; guarda crudo en cache/nombre_cache y reutiliza."""
    ruta = os.path.join(CACHE, nombre_cache)
    modo_r = "rb" if binario else "r"
    if os.path.exists(ruta):
        with open(ruta, modo_r, encoding=None if binario else "utf-8") as fh:
            return fh.read()
    with _abrir(url) as resp:
        datos = resp.read()
    if not binario:
        datos = datos.decode("utf-8")
    modo_w = "wb" if binario else "w"
    with open(ruta, modo_w, encoding=None if binario else "utf-8") as fh:
        fh.write(datos)
    return datos


def bajar_uniprot():
    """UniProt paginando por la cabecera Link rel=next; cachea el TSV unido."""
    ruta = os.path.join(CACHE, "uniprot.tsv")
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fh:
            return fh.read()
    partes, url, encabezado, npag = [], URL_UNIPROT, None, 0
    while url:
        with _abrir(url) as resp:
            texto = resp.read().decode("utf-8")
            link = resp.headers.get("Link", "") or ""
        lineas = texto.splitlines()
        if not lineas:
            break
        if encabezado is None:
            encabezado = lineas[0]
            partes.append(encabezado)
        partes.extend(lineas[1:])          # sin repetir el encabezado
        npag += 1
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
        time.sleep(0.2)                    # cortesia con el servidor
    print(f"  UniProt: {npag} peticiones")
    tsv = "\n".join(partes) + "\n"
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(tsv)
    return tsv


# ---------------------------------------------------------------------------
# Parseo del GFF de RefSeq
# ---------------------------------------------------------------------------
def _attrs(campo):
    """Convierte 'k=v;k2=v2' en dict, decodificando %XX."""
    d = {}
    for par in campo.strip().split(";"):
        if "=" in par:
            k, v = par.split("=", 1)
            d[k] = urllib.parse.unquote(v)
    return d


TIPO_POR_BIOTYPE = {
    "protein_coding": "protein_coding", "tRNA": "tRNA", "rRNA": "rRNA",
    "pseudogene": "pseudogene", "ncRNA": "ncRNA", "tmRNA": "ncRNA",
    "antisense_RNA": "ncRNA", "SRP_RNA": "ncRNA", "RNase_P_RNA": "ncRNA",
    "misc_RNA": "ncRNA",
}


def parse_gff(texto):
    """Devuelve (genes, sitios). genes[locus] = dict; sitios = lista de dicts."""
    genes = {}
    sitios = []
    for linea in texto.split("\n"):
        if not linea or linea[0] == "#":
            continue
        f = linea.split("\t")
        if len(f) < 9:
            continue
        tipo_feat, hebra, attr = f[2], f[6], _attrs(f[8])
        lt = attr.get("locus_tag")

        if tipo_feat in ("gene", "pseudogene"):
            if not lt or not RE_LOCUS.match(lt):
                continue
            biotype = attr.get("gene_biotype", "")
            if tipo_feat == "pseudogene" or attr.get("pseudo") == "true":
                biotype = "pseudogene"
            g = genes.setdefault(lt, {"locus_tag": lt, "simbolo": "",
                                      "alias": set(), "tipo": "", "producto": "",
                                      "hebra": hebra})
            g["hebra"] = hebra
            g["tipo"] = TIPO_POR_BIOTYPE.get(biotype, "protein_coding")
            sym = attr.get("gene") or attr.get("Name") or ""
            if sym and not RE_LOCUS.match(sym):
                g["simbolo"] = sym
            for syn in attr.get("gene_synonym", "").split(","):
                syn = syn.strip()
                if syn and not RE_LOCUS.match(syn):
                    g["alias"].add(syn)

        elif tipo_feat == "protein_binding_site":
            nota = attr.get("Note", "")
            bm = attr.get("bound_moiety", "").strip()
            blancos = []
            if "regulation for" in nota:
                trozo = nota.split("regulation for", 1)[1]
                blancos = RE_LOCUS_EN_TEXTO.findall(trozo)
            exps = [e for e in re.split(r"[;,]", attr.get("experiment", "")) if e.strip()]
            pmids = re.findall(r"PMID:?\s*(\d+)",
                               attr.get("Dbxref", "") + " " + nota)
            sitios.append({"tf": bm, "blancos": blancos,
                           "experimento": [e.strip() for e in exps],
                           "pmids": pmids})
        else:
            # lineas con producto (CDS, tRNA, rRNA, ncRNA...) para rellenar
            prod = attr.get("product")
            if lt and RE_LOCUS.match(lt) and prod:
                g = genes.setdefault(lt, {"locus_tag": lt, "simbolo": "",
                                          "alias": set(), "tipo": "",
                                          "producto": "", "hebra": hebra})
                if not g["producto"]:
                    g["producto"] = prod.replace("\t", " ").replace("\n", " ")
                if not g["simbolo"]:
                    sym = attr.get("gene", "")
                    if sym and not RE_LOCUS.match(sym):
                        g["simbolo"] = sym
    for g in genes.values():
        g["fuentes"] = {"refseq"}
    return genes, sitios


# ---------------------------------------------------------------------------
# KEGG: aporta simbolos que RefSeq no trae (PA1003=mvfR, PA3574=nalD)
# ---------------------------------------------------------------------------
def parse_kegg(texto):
    out = {}
    for linea in texto.split("\n"):
        if not linea.strip():
            continue
        partes = linea.split("\t")
        if len(partes) < 2:
            continue
        ent = partes[0].split(":")[-1].strip()      # pae:PA1003 -> PA1003
        if not RE_LOCUS.match(ent):
            continue
        desc = partes[1]
        nombres = desc.split(";", 1)[0] if ";" in desc else ""
        toks = [t.strip() for t in nombres.split(",") if t.strip()]
        toks = [t for t in toks if RE_SIMBOLO_TOKEN.match(t)
                and not RE_LOCUS.match(t) and "_" not in t]
        if toks:
            out[ent] = {"simbolo": toks[0], "alias": set(toks[1:])}
    return out


# ---------------------------------------------------------------------------
# UniProt: simbolos + evidencia de es_tf (GO y keywords)
# ---------------------------------------------------------------------------
def parse_uniprot(tsv):
    out = {}
    lineas = tsv.split("\n")
    if not lineas:
        return out
    cols = lineas[0].split("\t")
    idx = {c: i for i, c in enumerate(cols)}
    ig, igo, ikw = idx.get("Gene Names"), idx.get("Gene Ontology IDs"), idx.get("Keywords")
    # nombres de columna alternos segun version del API
    if ig is None:
        ig = idx.get("gene_names")
    if igo is None:
        igo = idx.get("go_id")
    if ikw is None:
        ikw = idx.get("keyword")
    for linea in lineas[1:]:
        if not linea.strip():
            continue
        c = linea.split("\t")
        if len(c) <= max(x for x in (ig, igo, ikw) if x is not None):
            continue
        nombres = c[ig] if ig is not None else ""
        toks = nombres.split()
        locus = next((t for t in toks if RE_LOCUS.match(t)), None)
        if not locus:
            continue
        simbolos = [t for t in toks if not RE_LOCUS.match(t)
                    and RE_SIMBOLO_TOKEN.match(t) and "_" not in t]
        go = set(x.strip() for x in (c[igo] if igo is not None else "").split(";") if x.strip())
        kws = set(x.strip() for x in (c[ikw] if ikw is not None else "").split(";") if x.strip())
        rec = out.setdefault(locus, {"simbolo": "", "alias": set(), "go": set(), "kw": set()})
        if simbolos and not rec["simbolo"]:
            rec["simbolo"] = simbolos[0]
            rec["alias"].update(simbolos[1:])
        else:
            rec["alias"].update(simbolos)
        rec["go"].update(go)
        rec["kw"].update(kws)
    return out


# ---------------------------------------------------------------------------
# Marca es_tf (regla literal: union de 5 senales de UniProt)
# ---------------------------------------------------------------------------
def evidencia_tf(go, kw, producto):
    """Devuelve (es_tf, fuente_tf_lista). Regla es_tf = union de 5 senales
    UniProt (GO:0003700, GO:0006355, kw Transcription regulation, kw Sigma
    factor, kw Two-component regulatory system). producto_refseq NO dispara la
    marca; se anexa como corroboracion cuando la marca ya es true."""
    kw_l = {k.lower() for k in kw}
    fuentes = []
    if "GO:0003700" in go:
        fuentes.append("go_0003700")
    if "GO:0006355" in go:
        fuentes.append("go_0006355")
    if "transcription regulation" in kw_l:
        fuentes.append("kw_transcription_regulation")
    if "sigma factor" in kw_l:
        fuentes.append("kw_sigma_factor")
    if "two-component regulatory system" in kw_l:
        fuentes.append("kw_two_component")
    es_tf = len(fuentes) > 0
    if es_tf and producto and RE_PROD_TF.search(producto):
        fuentes.append("producto_refseq")   # corroboracion, no disparador
    return es_tf, fuentes


def es_sensible(superficies):
    """true si alguna superficie (en minusculas) tiene <=3 caracteres o es una
    palabra inglesa comun de la lista. Evita falsos positivos (fur, cat...)."""
    for s in superficies:
        sl = s.lower()
        if len(sl) <= 3 or sl in PALABRAS_COMUNES:
            return True
    return False


# ---------------------------------------------------------------------------
# Fusion de fuentes -> filas de genes.tsv
# ---------------------------------------------------------------------------
def construir_genes(gff_genes, kegg, uni):
    filas = []
    for lt, g in gff_genes.items():
        simbolo = g["simbolo"]
        alias = set(a for a in g["alias"] if RE_SIMBOLO_TOKEN.match(a))
        fuentes = set(g["fuentes"])

        if lt in kegg:
            fuentes.add("kegg")
            if not simbolo:
                simbolo = kegg[lt]["simbolo"]
            else:
                alias.add(kegg[lt]["simbolo"])
            alias.update(kegg[lt]["alias"])

        go, kw = set(), set()
        if lt in uni:
            fuentes.add("uniprot")
            u = uni[lt]
            if not simbolo:
                simbolo = u["simbolo"]
            elif u["simbolo"]:
                alias.add(u["simbolo"])
            alias.update(u["alias"])
            go, kw = u["go"], u["kw"]

        # limpiar alias: sin el simbolo elegido, sin el locus, sin duplicados
        alias.discard(simbolo)
        alias = sorted(a for a in alias
                       if a and not RE_LOCUS.match(a) and a != simbolo)

        es_tf, fuente_tf = evidencia_tf(go, kw, g["producto"])
        superficies = [x for x in ([simbolo] + alias) if x]
        sens = es_sensible(superficies)

        filas.append({
            "locus_tag": lt,
            "simbolo": simbolo,
            "alias": "|".join(alias),
            "tipo": g["tipo"] or "protein_coding",
            "producto": g["producto"],
            "es_tf": "true" if es_tf else "false",
            "fuente_tf": "|".join(fuente_tf) if es_tf else "",
            "fuente": "|".join(sorted(fuentes)),
            "sensible_mayusculas": "true" if sens else "false",
            "hebra": g.get("hebra", ""),   # interno (para operones), no se escribe
            "_go": go, "_kw": kw,          # internos, no se escriben
        })
    filas.sort(key=lambda r: _num_locus(r["locus_tag"]) or 0)
    return filas


# ---------------------------------------------------------------------------
# Operones (derivados del diccionario, con cuidado en la hebra menos)
# ---------------------------------------------------------------------------
def _num_locus(lt):
    m = re.match(r"^PA(\d{4})(?:\.(\d))?$", lt)
    return int(m.group(1)) if m else None


def construir_operones(filas):
    """Genes protein_coding con simbolo [3 min][1 may] y locus consecutivos, en
    la MISMA hebra, forman una corrida. Se ordenan en sentido de TRANSCRIPCION
    (ascendente en +, DESCENDENTE en -) y se nombran agrupando prefijos iguales
    y uniendo grupos distintos con guion.  mexC/mexD/oprJ (hebra -) -> mexCD-oprJ.
    """
    cand = []
    for r in filas:
        if r["tipo"] != "protein_coding":
            continue
        if not RE_SIMBOLO_OPERON.match(r["simbolo"]):
            continue
        n = _num_locus(r["locus_tag"])
        if n is None or "." in r["locus_tag"]:
            continue
        cand.append((n, r["locus_tag"], r["simbolo"], r["hebra"]))
    cand.sort()

    operones = []
    i, N = 0, len(cand)
    while i < N:
        j = i
        while (j + 1 < N and cand[j + 1][0] == cand[j][0] + 1
               and cand[j + 1][3] == cand[i][3]):
            j += 1
        corrida = cand[i:j + 1]
        if len(corrida) >= 2:
            hebra = corrida[0][3]
            orden = corrida if hebra == "+" else list(reversed(corrida))
            simbolos = [c[2] for c in orden]
            locus = [c[1] for c in orden]
            operones.append({
                "operon": _nombrar_operon(simbolos),
                "miembros": "|".join(simbolos),
                "locus_tags": "|".join(locus),
                "hebra": hebra,
            })
        i = j + 1
    return operones


def _nombrar_operon(simbolos):
    """['mexC','mexD','oprJ'] -> 'mexCD-oprJ' (agrupa prefijos consecutivos)."""
    grupos = []
    pref = None
    for s in simbolos:
        p, letra = s[:3], s[3]
        if p == pref:
            grupos[-1][1] += letra
        else:
            grupos.append([p, letra])
            pref = p
    return "-".join(p + letras for p, letras in grupos)


# ---------------------------------------------------------------------------
# Sitios de union (salida C)
# ---------------------------------------------------------------------------
def construir_sitios(sitios):
    pares = {}   # (tf, blanco) -> {exp:set, pmid:set}
    for s in sitios:
        tf = s["tf"]
        if not tf:
            continue
        for b in s["blancos"]:
            k = (tf, b)
            d = pares.setdefault(k, {"exp": set(), "pmid": set()})
            d["exp"].update(s["experimento"])
            d["pmid"].update(s["pmids"])
    filas = []
    for (tf, b), d in pares.items():
        # La existencia del feature protein_binding_site en el GFF ya ES la
        # evidencia experimental; experimento/pmids son metadatos que pueden
        # venir vacios en algunos features. Solo exigimos blanco valido.
        if not b:
            continue
        filas.append({"tf": tf, "blanco": b,
                      "experimento": "|".join(sorted(d["exp"])),
                      "pmids": "|".join(sorted(d["pmid"], key=lambda x: int(x)))})
    filas.sort(key=lambda r: (r["tf"], _num_locus(r["blanco"]) or 0))
    return filas


# ---------------------------------------------------------------------------
# Escritura TSV (UTF-8, LF, tab)
# ---------------------------------------------------------------------------
def escribir_tsv(ruta, columnas, filas):
    with open(ruta, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(columnas) + "\n")
        for r in filas:
            fh.write("\t".join(str(r.get(c, "")).replace("\t", " ").replace("\n", " ")
                               for c in columnas) + "\n")


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def main():
    os.makedirs(CACHE, exist_ok=True)

    print("1/3  RefSeq GFF ...")
    gz = bajar(URL_REFSEQ, "refseq.gff.gz", binario=True)
    texto = gzip.decompress(gz).decode("utf-8", errors="replace")
    n_locus = texto.count("locus_tag=")
    n_pbs = texto.count("protein_binding_site")
    print(f"     descomprimido: {len(texto)} caracteres "
          f"(esperado {GFF_LEN_ESPERADO})")
    print(f"     locus_tag=: {n_locus} (esperado {GFF_LOCUS_ESPERADO}) | "
          f"protein_binding_site: {n_pbs} (esperado {GFF_PBS_ESPERADO})")
    if len(texto) != GFF_LEN_ESPERADO or n_locus != GFF_LOCUS_ESPERADO:
        print("     AVISO: los numeros del GFF no coinciden; revisa la fuente.")
    gff_genes, sitios_raw = parse_gff(texto)

    print("2/3  KEGG ...")
    kegg = parse_kegg(bajar(URL_KEGG, "kegg_pae.txt"))

    print("3/3  UniProt ...")
    uni = parse_uniprot(bajar_uniprot())

    filas = construir_genes(gff_genes, kegg, uni)
    for f in filas:
        f.pop("_go", None); f.pop("_kw", None)
    operones = construir_operones(filas)
    sitios = construir_sitios(sitios_raw)

    escribir_tsv(os.path.join(BASE, "genes.tsv"),
                 ["locus_tag", "simbolo", "alias", "tipo", "producto",
                  "es_tf", "fuente_tf", "fuente", "sensible_mayusculas"], filas)
    escribir_tsv(os.path.join(BASE, "operones.tsv"),
                 ["operon", "miembros", "locus_tags", "hebra"], operones)
    escribir_tsv(os.path.join(BASE, "sitios_union.tsv"),
                 ["tf", "blanco", "experimento", "pmids"], sitios)

    # Conteos solicitados
    n_genes = len(filas)
    n_tf = sum(1 for f in filas if f["es_tf"] == "true")
    n_op = len(operones)
    n_op_menos = sum(1 for o in operones if o["hebra"] == "-")
    n_pares = len(sitios)
    n_factores = len({s["tf"] for s in sitios})
    print("\n=================  CONTEOS  =================")
    print(f"genes totales .................. {n_genes}")
    print(f"marcados es_tf (regla de 5) .... {n_tf}   (esperado ~545)")
    print(f"operones ....................... {n_op}")
    print(f"  de ellos en hebra menos ...... {n_op_menos}")
    print(f"sitios de union: pares ......... {n_pares}   (esperado ~332)")
    print(f"sitios de union: factores ...... {n_factores}   (esperado ~33)")
    print("=============================================")


if __name__ == "__main__":
    main()