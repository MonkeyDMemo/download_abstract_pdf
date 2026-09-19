# -*- coding: utf-8 -*-
"""La base curada y sus conflictos, a CSV. Escritura atomica.

Dos archivos y no uno: el operon curado va a `operones_silver.csv` y lo que
hay que mirar a mano va a `operones_conflictos.csv`. Separarlos es lo que hace
que el segundo sea util: una lista de revision mezclada con 3 000 filas
correctas no la revisa nadie.

Los CSV son el producto canonico y salen siempre con biblioteca estandar.

No imprime: recibe un callable `log`.
"""

import csv
import io
import os

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


def escribir_csv(ruta, columnas, filas, log=lambda m: None):
    tmp = ruta + ".tmp"
    d = os.path.dirname(ruta)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    os.replace(tmp, ruta)
    log("  %s  (%d filas)" % (ruta, len(filas)))
    return len(filas)
