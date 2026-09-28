# -*- coding: utf-8 -*-
"""La base curada y sus conflictos, a CSV. Escritura atomica.

Dos archivos y no uno: el operon curado va a `operones_silver.csv` y lo que
hay que mirar a mano va a `operones_conflictos.csv`. Separarlos es lo que hace
que el segundo sea util: una lista de revision mezclada con 3 000 filas
correctas no la revisa nadie.

Cuando hay datos de PGD sale un tercero, `operones_pgd.csv`: la vista de
operones de pseudomonas.com para todos sus operones, una fila por gen, tal
como la dio PGD y antes de curar.

Los CSV son el producto canonico y salen siempre con biblioteca estandar.

No imprime: recibe un callable `log`.
"""

import csv
import io
import json
import os
import re

COLUMNAS_SILVER = [
    "clave_genes", "nombre", "locus_tags", "n_genes", "monocistronico",
    "cadena", "nivel_evidencia",
    "n_fuentes", "fuentes", "pmids", "adyacente", "es_alternativa",
    "promotor_cdbprom", "revisar", "curado_en",
]

COLUMNAS_CONFLICTOS = [
    "clave_genes", "locus_tags", "n_genes", "motivo", "nivel_evidencia",
    "n_fuentes", "fuentes", "pmids",
]

# Lo que obliga a mirar a mano, y por que. El orden es el de urgencia: un
# operon cuyos genes no son adyacentes contradice al genoma y probablemente
# es un error de mapeo; una hebra sin verificar solo dice que faltaba el GFF.
MOTIVOS = {
    "no_adyacente": "los genes no son consecutivos en el genoma",
    "hebras_distintas": "los genes no comparten hebra: no comparten promotor",
    "genes_sin_resolver": "algun nombre no se pudo llevar a locus tag",
    "hebra_no_verificada": "sin GFF en cache, la hebra no se comprobo",
}


# La vista de operones de pseudomonas.com (`feature/show/?id=…&view=operons`),
# una fila por gen miembro. Las claves son identificadores; los encabezados
# son texto para quien abre el CSV.
COLUMNAS_PGD = [
    "operon_id", "operon", "locus_tag", "gen", "descripcion", "inicio",
    "fin", "hebra", "tipo", "evidencia", "pmid",
]
ENCABEZADOS_PGD = [
    "ID del operón", "Operón", "Locus tag", "Gen", "Descripción (RefSeq)",
    "Inicio", "Fin", "Hebra", "Tipo (RefSeq)", "Evidencia", "PMID",
]

# Como lo dice la página. PseudoCAP escribe la evidencia de cada operón en
# prosa, y esa prosa no viene en la tabla.
EVIDENCIA_PGD = {
    "DOOR": "Computationally-predicted (DOOR)",
    "PseudoCAP": "Literatura (PseudoCAP)",
}


def cargar_anotacion(ruta):
    """{locus_tag: (producto, tipo)} de `genes_pao1.tsv`.

    La tabla de operones de PGD no trae la descripción de cada gen, y la
    anotación de PGD está detrás del mismo desafío de Cloudflare que el resto
    del sitio. Se usa la de RefSeq, que ya está en el repositorio, y el
    encabezado lo dice, porque PGD la redacta distinto: `methionyl-tRNA
    synthetase` contra `methionine--tRNA ligase`.
    """
    salida = {}
    with io.open(ruta, encoding="utf-8", newline="") as f:
        for d in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            lt = (d.get("locus_tag") or "").strip()
            if lt:
                salida[lt] = ((d.get("producto") or "").strip(),
                              (d.get("tipo") or "").strip())
    return salida


def _orden_operon(id_fuente):
    """`operon-10` después de `operon-2`: el orden textual los invierte."""
    m = re.search(r"(\d+)$", id_fuente or "")
    return (int(m.group(1)) if m else float("inf"), id_fuente or "")


def filas_pgd(con, db, anotacion):
    """La vista de operones de PGD, una fila por gen, para todos sus operones.

    Sale del bronce vigente y no de silver, a propósito: es lo que dijo PGD,
    antes de normalizar, deduplicar o mezclar con otras fuentes. Los genes van
    en el orden del archivo, que es el de la página.

    El PMID de un operón de DOOR es el del método (Mao et al. 2009): el parser
    lo saca de `pmid` para que la curación no lo lea como literatura, y aquí
    vuelve a su columna porque la página lo muestra.
    """
    operones = [f for f in db.bronze_vigente(con) if f["fuente"] == "pgd"]
    operones.sort(key=lambda f: _orden_operon(f["id_fuente"]))
    filas = []
    for f in operones:
        crudo = json.loads(f["registro_raw"]) if f["registro_raw"] else {}
        base = crudo.get("source_database") or f["tipo_evidencia"] or ""
        pmid = f["pmid"] or crudo.get("referencia_metodo") or ""
        for g in crudo.get("genes") or []:
            producto, tipo = anotacion.get(g["locus_tag"], ("", ""))
            filas.append({
                "operon_id": f["id_fuente"],
                "operon": crudo.get("name") or "",
                "locus_tag": g["locus_tag"],
                "gen": g.get("gene_name") or "",
                "descripcion": producto,
                "inicio": g.get("start", ""),
                "fin": g.get("end", ""),
                "hebra": g.get("hebra") or f["cadena"] or "",
                "tipo": tipo,
                "evidencia": EVIDENCIA_PGD.get(base, base),
                "pmid": pmid,
            })
    return filas


def _fuentes(fila_id, mapa):
    return ";".join(sorted(set(f for f, _ in mapa.get(fila_id, []))))


def filas_silver(con, db, sin_monocistronicos=False):
    """La capa curada, a filas.

    `sin_monocistronicos` **apaga por omision**: la curacion conserva las
    unidades de un gen porque BioCyc registra 3 774 y descartarlas tiraba la
    mayor parte de esa fuente. Filtrar es una decision de quien lee el archivo,
    no de quien lo construye, asi que vive aqui y no en `curar`.
    """
    mapa = db.fuentes_de_silver(con)
    filas = []
    for s in db.silver_de(con):
        if sin_monocistronicos and s["monocistronico"]:
            continue
        filas.append({
            "clave_genes": s["clave_genes"],
            "nombre": s["nombre"] or "",
            "locus_tags": s["locus_tags"],
            "n_genes": s["n_genes"],
            "monocistronico": "si" if s["monocistronico"] else "no",
            "cadena": s["cadena"] or "",
            "nivel_evidencia": s["nivel_evidencia"],
            "n_fuentes": s["n_fuentes"],
            "fuentes": _fuentes(s["id"], mapa),
            "pmids": s["pmids"] or "",
            "adyacente": "si" if s["adyacente"] else "no",
            "es_alternativa": "si" if s["es_alternativa"] else "no",
            "promotor_cdbprom": "si" if s["promotor_cdbprom"] else "no",
            "revisar": s["revisar"] or "",
            "curado_en": s["curado_en"],
        })
    return filas


def filas_conflictos(con, db):
    """Una fila por operon que necesita ojo humano, con el motivo en prosa."""
    mapa = db.fuentes_de_silver(con)
    filas = []
    for s in db.silver_de(con):
        marcas = [m for m in (s["revisar"] or "").split(";") if m]
        if not marcas:
            continue
        filas.append({
            "clave_genes": s["clave_genes"],
            "nombre": s["nombre"] or "",
            "locus_tags": s["locus_tags"],
            "n_genes": s["n_genes"],
            "motivo": "; ".join(MOTIVOS.get(m, m) for m in marcas),
            "nivel_evidencia": s["nivel_evidencia"],
            "n_fuentes": s["n_fuentes"],
            "fuentes": _fuentes(s["id"], mapa),
            "pmids": s["pmids"] or "",
        })
    return filas


def escribir_csv(ruta, columnas, filas, log=lambda m: None, encabezados=None):
    """`encabezados` reemplaza la fila de encabezado sin tocar las claves.

    Así el CSV puede decir «Descripción (RefSeq)» mientras las claves de cada
    fila siguen siendo identificadores ASCII.
    """
    tmp = ruta + ".tmp"
    d = os.path.dirname(ruta)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        if encabezados:
            csv.writer(f).writerow(encabezados)
        else:
            w.writeheader()
        for fila in filas:
            w.writerow(fila)
    os.replace(tmp, ruta)
    log("  %s  (%d filas)" % (ruta, len(filas)))
    return len(filas)
