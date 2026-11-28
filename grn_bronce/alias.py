# -*- coding: utf-8 -*-
"""La capa de alias adicionales: nombres de gen que una fuente publica da a un
locus de PAO1 y `genes_pao1.tsv` no conoce.

POR QUE EXISTE
==============
De los 5 642 genes del diccionario, 3 492 solo tienen locus tag. Varios tienen
nombre en la literatura (`cdrA` es PA4625, `kinB` es PA5484, `vqsR` es PA2591)
y RefSeq, KEGG y UniProt no lo traen. El texto los nombra y el diccionario no
los reconoce.

La fuente que los tiene completos es Pseudomonas Genome DB, y es una via
cerrada (`CLAUDE.md`, `docs/hallazgos.md`): el sitio esta tras un desafio de
Cloudflare y su `robots.txt` prohibe la recoleccion automatizada. Lo que si es
publico es la exportacion de operones que su curador entrego al laboratorio
Greene, publicada con licencia BSD-3 y fijada a un commit
(`grn_operones/fuentes.py::URL_PGD`). Cada fila trae un locus tag y el nombre
del gen. De ahi sale esta capa, y por eso **solo nombra genes que estan en un
operon de esa tabla**.

POR QUE ES UNA CAPA Y NO UN CAMBIO A `genes_pao1.tsv`
====================================================
`genes_pao1.tsv` tiene dos copias que no pueden divergir, la del bronce y la
de `etapa2/`, y `etapa2/` esta congelada: su constructor verifica la
procedencia de cada fila contra las cuatro fuentes con que se armo. Una fuente
nueva ahi seria un cambio funcional a codigo congelado. Esta capa deja el
diccionario intacto y se lee aparte, de modo que quien no la pide obtiene
exactamente lo de antes.

LO QUE HACE Y LO QUE NO
=======================
- **Solo agrega superficies a filas que ya existen.** Nunca crea un gen ni
  cambia el simbolo: el id canonico de la fila sigue siendo el mismo (el
  simbolo si lo tiene, el locus tag si no), y con el todo cruce con lo ya
  medido.
- **Entran todos los nombres de la fuente que pasan las reglas, no los que
  convienen.** Ninguna regla mira una referencia de evaluacion.
- **Un nombre que el diccionario ya usa no entra**, sea del mismo gen o de
  otro. Con dos duenos, `Lexico` marca la superficie como ambigua y no emite
  mencion para ninguno (regla 4 de su contrato): se perderia un gen que hoy
  se reconoce.
- **Un nombre de tres caracteres o menos, o que es palabra comun en ingles,
  no entra.** En `genes_pao1.tsv` esos nombres vuelven la fila sensible a
  mayusculas; aqui no se puede sin cambiar como se reconoce lo que la fila ya
  tenia, asi que se quedan fuera y se cuentan.
- **Un nombre generico de marco de lectura (`orf...`) no entra.** La fuente
  llama `orfX` a PA1664, y en el corpus `orfX` son al menos cinco genes
  distintos: el que esta junto a `vfr`, el del operon de `fumC`, el vecino de
  `anr`, el de `agmR`. Es un nombre provisional que cada articulo reusa.
- **Cada alias se reconoce en dos escrituras exactas y ninguna otra:** como
  lo da la fuente (`kinB`) y con la primera letra en mayuscula (`KinB`), que
  es la forma de la proteina. Ver `formas`. Medido el 27-nov-2026 sobre las
  350 134 oraciones de la corrida 27 del bronce, sin distinguir mayusculas:
  `pcr2` casaba 43 veces con el vector `pCR2.1` y 3 con el gen; `nppC`, 35
  de 35 con la sigla `NPPC`; `mepM`, 16 de 16 con `MEPM` (meropenem);
  `lysE`, 29 de 31 con el verbo `lyse`; `ptrC`, 16 de 39 con el promotor
  `Ptrc`. Con las dos escrituras exactas esas desaparecen por regla, sin
  lista negra, y se pierden las erratas de mayusculas (una mencion por alias
  en los pocos que las tienen).
- Reconocer genes por diccionario produce falsos positivos y no sustituye al
  reconocimiento de entidades. Las dos escrituras quitan las colisiones
  medidas, no todas las posibles.

Uso:
    python -m grn_bronce.alias generar --pgd CSV [--salida TSV]
"""

from __future__ import print_function

import argparse
import collections
import csv
import hashlib
import io
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RECURSOS = os.path.join(AQUI, "recursos")
RUTA = os.path.join(RECURSOS, "alias_adicionales.tsv")
RUTA_GENES = os.path.join(RECURSOS, "genes_pao1.tsv")
RUTA_OPERONES = os.path.join(RECURSOS, "operones_pao1.tsv")
RUTA_PALABRAS = os.path.join(RECURSOS, "palabras_comunes.txt")

COLUMNAS = ["locus_tag", "alias", "fuente"]

# La foto publica del 2021-07-19 (`grn_operones/fuentes.py::URL_PGD`), por sus
# bytes. La version 22.1 llego por correo del curador y no se ha declarado
# redistribuible: con otra huella, `generar` se niega.
FUENTE_PGD = "pgd_operones_2021"
HUELLA_PGD = ("605109c9c827d2820a01fd295a7155941b15e7ac3b19ad9be5f9495a1812d2"
              "55")

# Las mismas formas que `etapa2/construir_diccionario.py` (`LOCUS`,
# `ALIAS_SANO`); `test_alias.py` comprueba que no se separen.
LOCUS = re.compile(r"^PA\d{4}(\.\d)?$")
ALIAS_SANO = re.compile(r"^[A-Za-z][A-Za-z0-9_.'-]{0,29}$")
MAX_CORTO = 3

GENERICO = re.compile(r"^orf", re.I)

MOTIVOS = ("sin_nombre", "locus_desconocido", "forma", "corto_o_palabra_comun",
           "generico", "ya_es_del_mismo_gen", "ya_es_de_otro_gen",
           "es_un_operon", "ambiguo_en_la_fuente", "repetido")


def formas(alias):
    """Las dos escrituras con que se reconoce un alias de esta capa: la de la
    fuente y la de la proteina (primera letra en mayuscula). Quien use la
    capa compara con estas, con mayusculas exactas."""
    proteina = alias[:1].upper() + alias[1:]
    return (alias,) if proteina == alias else (alias, proteina)


def _leer_tsv(ruta, columnas):
    """Filas de un TSV con encabezado exacto. Partir por tabulador es exacto
    porque ningun campo lo lleva, como en `etapa2/lexico.py`."""
    filas = []
    with io.open(ruta, encoding="utf-8") as f:
        cabecera = f.readline().rstrip("\r\n").split("\t")
        if cabecera[:len(columnas)] != list(columnas):
            raise ValueError("%s no tiene el encabezado esperado."
                             % os.path.basename(ruta))
        for linea in f:
            linea = linea.rstrip("\r\n")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            partes += [""] * (len(cabecera) - len(partes))
            filas.append(dict(zip(cabecera, partes)))
    return filas


def leer(ruta=RUTA):
    """Las filas de la capa, validadas: encabezado exacto, locus tag y alias
    con forma, y ningun alias con dos duenos."""
    filas = _leer_tsv(ruta, COLUMNAS)
    duenos = {}
    for fila in filas:
        locus, alias = fila["locus_tag"].strip(), fila["alias"].strip()
        if not LOCUS.match(locus) or not ALIAS_SANO.match(alias):
            raise ValueError("%s: una fila no tiene locus tag o alias con "
                             "forma." % os.path.basename(ruta))
        if duenos.setdefault(alias.lower(), locus) != locus:
            raise ValueError("%s: un alias tiene dos locus."
                             % os.path.basename(ruta))
        fila["locus_tag"], fila["alias"] = locus, alias
    return filas


def por_locus(filas):
    """{locus_tag: [alias, ...]} en el orden del archivo."""
    salida = collections.OrderedDict()
    for fila in filas:
        salida.setdefault(fila["locus_tag"], []).append(fila["alias"])
    return salida


def leer_palabras(ruta=RUTA_PALABRAS):
    """Como `construir_diccionario.leer_palabras_comunes`."""
    palabras = set()
    if not os.path.exists(ruta):
        return palabras
    with io.open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.split("#", 1)[0].strip().lower()
            if linea:
                palabras.add(linea)
    return palabras


def superficies_del_diccionario(genes):
    """{superficie en minusculas: {locus o simbolo de la fila}} de todo el
    diccionario, sin distinguir mayusculas: un alias nuevo que solo difiere
    en mayusculas de una superficie existente tambien choca."""
    duenos = collections.defaultdict(set)
    for fila in genes:
        locus, simbolo = fila["locus_tag"].strip(), fila["simbolo"].strip()
        quien = locus or simbolo
        for s in [locus, simbolo] + fila["alias"].split("|"):
            s = s.strip()
            if s:
                duenos[s.lower()].add(quien)
    return duenos


def pares_de_pgd(ruta):
    """(locus_tag, nombre) de la exportacion de operones de PGD, en el orden
    del archivo. Solo lee esas dos columnas."""
    pares = []
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if not {"locus_tag", "gene_name"} <= set(lector.fieldnames or []):
            raise ValueError("El CSV no trae locus_tag y gene_name.")
        for fila in lector:
            pares.append(((fila["locus_tag"] or "").strip(),
                          (fila["gene_name"] or "").strip()))
    return pares


def generar(pares, genes, operones=(), palabras=(), fuente=FUENTE_PGD):
    """(filas, conteos): los alias que entran y cuantos pares se quedaron
    fuera por cada motivo de `MOTIVOS`.

    `pares` son (locus_tag, nombre) de la fuente; `genes`, las filas de
    `genes_pao1.tsv`; `operones`, los nombres del catalogo de operones, que
    tambien son superficies del lexico.
    """
    duenos = superficies_del_diccionario(genes)
    conocidos = set(f["locus_tag"].strip() for f in genes
                    if f["locus_tag"].strip())
    de_operon = set(o.strip().lower() for o in operones if o.strip())
    palabras = set(p.lower() for p in palabras)
    conteos = collections.Counter()
    candidatos = collections.OrderedDict()   # (locus, nombre en minusculas)
    for locus, nombre in pares:
        if not nombre or LOCUS.match(nombre) or nombre == locus:
            conteos["sin_nombre"] += 1
        elif locus not in conocidos:
            conteos["locus_desconocido"] += 1
        elif not ALIAS_SANO.match(nombre):
            conteos["forma"] += 1
        elif len(nombre) <= MAX_CORTO or nombre.lower() in palabras:
            conteos["corto_o_palabra_comun"] += 1
        elif GENERICO.match(nombre):
            conteos["generico"] += 1
        elif locus in duenos.get(nombre.lower(), ()):
            conteos["ya_es_del_mismo_gen"] += 1
        elif nombre.lower() in duenos:
            conteos["ya_es_de_otro_gen"] += 1
        elif nombre.lower() in de_operon:
            conteos["es_un_operon"] += 1
        elif (locus, nombre.lower()) in candidatos:
            conteos["repetido"] += 1
        else:
            candidatos[(locus, nombre.lower())] = nombre
    locus_de = collections.defaultdict(set)
    for locus, clave in candidatos:
        locus_de[clave].add(locus)
    filas = []
    for (locus, clave), nombre in candidatos.items():
        if len(locus_de[clave]) > 1:
            conteos["ambiguo_en_la_fuente"] += 1
            continue
        filas.append(collections.OrderedDict([
            ("locus_tag", locus), ("alias", nombre), ("fuente", fuente)]))
    filas.sort(key=lambda f: (f["locus_tag"], f["alias"].lower(), f["alias"]))
    return filas, collections.OrderedDict((m, conteos[m]) for m in MOTIVOS)


def escribir(ruta, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNAS) + "\n")
        for fila in filas:
            f.write("\t".join(fila[c] for c in COLUMNAS) + "\n")


def con_alias(alias_de_la_fila, locus, adicionales):
    """Los alias de una fila mas los de la capa para su locus, sin repetir
    y sin tocar los que ya tenia. `adicionales` es `por_locus(leer())`."""
    salida = list(alias_de_la_fila)
    vistos = set(a.lower() for a in salida)
    for a in adicionales.get(locus, ()):
        if a.lower() not in vistos:
            salida.append(a)
            vistos.add(a.lower())
    return salida


def huella_de(ruta):
    h = hashlib.sha256()
    with io.open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def generar_de_pgd(ruta_csv, ruta_genes=RUTA_GENES,
                   ruta_operones=RUTA_OPERONES, ruta_palabras=RUTA_PALABRAS):
    """(filas, conteos) desde la foto publica de PGD, o ValueError si el
    archivo no es esa foto."""
    if huella_de(ruta_csv) != HUELLA_PGD:
        raise ValueError("El archivo no es la foto publica del 2021-07-19 "
                         "(su huella no coincide con HUELLA_PGD). Otra "
                         "version no entra sin saber que se puede "
                         "redistribuir.")
    genes = _leer_tsv(ruta_genes, ["locus_tag", "simbolo", "alias"])
    operones = [f["operon"] for f in _leer_tsv(ruta_operones, ["operon"])]
    return generar(pares_de_pgd(ruta_csv), genes, operones,
                   leer_palabras(ruta_palabras))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="La capa de alias adicionales del diccionario.")
    sub = ap.add_subparsers(dest="comando")
    g = sub.add_parser("generar", help="Escribe la capa desde la exportacion "
                                       "publica de operones de PGD.")
    g.add_argument("--pgd", required=True,
                   help="PAO1-operons-2021-07-19.csv, la foto de URL_PGD.")
    g.add_argument("--salida", default=RUTA)
    args = ap.parse_args(argv)
    if args.comando != "generar":
        ap.print_help()
        return 2
    try:
        filas, conteos = generar_de_pgd(args.pgd)
    except (ValueError, OSError) as e:
        print("ERROR: %s" % e)
        return 1
    escribir(args.salida, filas)
    print("%d alias para %d locus -> %s"
          % (len(filas), len(set(f["locus_tag"] for f in filas)),
             os.path.relpath(args.salida)))
    print("fuera: " + ", ".join("%s %d" % (m, n) for m, n in conteos.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
