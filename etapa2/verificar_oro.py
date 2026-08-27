# -*- coding: utf-8 -*-
"""Comprueba que cada oracion del patron de oro exista donde la fila dice.

El patron de oro (`oro_pseudomonas.tsv`) afirma, para cada relacion atestiguada,
la oracion literal del corpus que la sostiene. Esa afirmacion es la que permite
decir "si el modelo no recupera una relacion conocida, el fallo es del modelo y
no del corpus", asi que conviene poder rehacerla en un minuto en vez de creerle
a un numero escrito en la documentacion.

POR QUE LA COMPARACION NO ES LITERAL DEL TODO
---------------------------------------------
Comparar cadena contra cadena da falsos negativos por codificacion, no por
contenido. Se midio: sin normalizar salen 172 de 181; con ella, 179. Las siete
que se recuperan son diferencias de este tipo:

  * El patron de oro escribe `sigmaE` donde el corpus trae `sigma-E` con la
    sigma griega. El proyecto evita a proposito lo que cae fuera de Latin-1
    porque truena en la consola de Windows (ver CLAUDE.md).
  * Las revistas usan el guion U+2010, que no es el guion ASCII, dentro de
    cosas como `3OC12-HSL`.
  * El patron de oro deja la media y quita el error: `0.46` donde el articulo
    dice `0.46 +/- 0.006`.

Ninguna de las tres cambia lo que la oracion afirma. Se normalizan, y lo que
quede fuera despues de eso si es una diferencia de contenido.

Solo biblioteca estandar.
"""
import argparse
import collections
import csv
import io
import os
import re
import sqlite3
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

# Umbral para contar una oracion como "presente por fragmento contiguo": que el
# trozo mas largo que si aparece cubra al menos esta fraccion de la oracion.
COBERTURA_MINIMA = 0.60

GRIEGO = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "φ": "phi",
    "χ": "chi", "ψ": "psi", "ω": "omega",
    "Δ": "delta", "Σ": "sigma", "Ω": "omega", "Φ": "phi",
}

DIGITOS = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁰": "0", "¹": "1", "²": "2", "³": "3",
}

# Todas las rayas y guiones tipograficos, incluido el U+2010 que rompia la
# comparacion dentro de `3OC12-HSL`.
GUIONES = "–—−‐‑‒―"

INVISIBLES = "­​‌‍﻿"


def normalizar(s):
    """Deja la cadena comparable: mismo guion, mismo alfabeto, mismos espacios.

    No es un normalizador de proposito general; hace exactamente lo que hace
    falta para que una diferencia de codificacion no se confunda con una
    diferencia de contenido. Ver el docstring del modulo.
    """
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    for guion in GUIONES:
        s = s.replace(guion, "-")
    for invisible in INVISIBLES:
        s = s.replace(invisible, "")
    for griega, latina in GRIEGO.items():
        s = s.replace(griega, latina)
    for digito, llano in DIGITOS.items():
        s = s.replace(digito, llano)
    # "0.46 +/- 0.006" -> "0.46": el oro conserva la media y suelta el error.
    s = re.sub(r"\s*±\s*[\d.]+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def fragmento_mas_largo(frase, cuerpo):
    """Fraccion de la oracion cubierta por su trozo contiguo mas largo presente.

    Busqueda binaria sobre la longitud, recorriendo todos los comienzos: si un
    trozo de n palabras aparece, se prueba con mas; si no, con menos.
    """
    palabras = frase.split()
    if not palabras:
        return 0.0
    bajo, alto = 0, len(palabras)
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        presente = any(" ".join(palabras[i:i + medio]) in cuerpo
                       for i in range(len(palabras) - medio + 1))
        if presente:
            bajo = medio
        else:
            alto = medio - 1
    return bajo / float(len(palabras))


def cargar_textos(db, fulltext):
    """PMID -> lista de textos disponibles, ya normalizados."""
    textos = collections.defaultdict(list)
    if os.path.isdir(fulltext):
        for carpeta, _, archivos in os.walk(fulltext):
            for archivo in archivos:
                if not archivo.lower().endswith((".txt", ".xml")):
                    continue
                m = re.match(r"(\d+)", archivo)
                if not m:
                    continue
                ruta = os.path.join(carpeta, archivo)
                try:
                    with io.open(ruta, encoding="utf-8", errors="replace") as f:
                        textos[m.group(1)].append(normalizar(f.read()))
                except OSError:
                    continue
    if os.path.exists(db):
        uri = "file:%s?mode=ro" % db.replace("\\", "/")
        con = sqlite3.connect(uri, uri=True)
        try:
            for pmid, titulo, resumen in con.execute(
                    'SELECT pmid, COALESCE(titulo,""), COALESCE(abstract,"") '
                    "FROM documentos"):
                if titulo or resumen:
                    textos[str(pmid)].append(normalizar(titulo + " " + resumen))
        finally:
            con.close()
    return textos


def verificar(filas, textos):
    """Devuelve (conteos, lista de filas que no cuadran)."""
    conteo = collections.Counter()
    fallos = []
    for fila in filas:
        if fila.get("atestiguado") != "true":
            conteo["no_atestiguada"] += 1
            continue
        frase = normalizar(fila.get("oracion", ""))
        if not frase:
            conteo["sin_oracion"] += 1
            fallos.append((fila["tf"], fila["blanco"], "la fila no trae oracion", ""))
            continue
        pmids = [p.strip() for p in fila.get("pmids", "").split(",") if p.strip()]
        cuerpos = [c for p in pmids for c in textos.get(p, [])]
        if not cuerpos:
            conteo["sin_texto_del_pmid"] += 1
            fallos.append((fila["tf"], fila["blanco"],
                           "no hay texto de esos PMIDs", frase[:60]))
            continue
        if any(frase in cuerpo for cuerpo in cuerpos):
            conteo["exacta"] += 1
            continue
        cobertura = max(fragmento_mas_largo(frase, cuerpo) for cuerpo in cuerpos)
        if cobertura >= COBERTURA_MINIMA:
            conteo["fragmento_contiguo"] += 1
        else:
            conteo["no_encontrada"] += 1
            fallos.append((fila["tf"], fila["blanco"],
                           "cobertura %.0f%%" % (cobertura * 100), frase[:60]))
    return conteo, fallos


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--oro", default=os.path.join(AQUI, "oro_pseudomonas.tsv"))
    p.add_argument("--db", default=os.path.join(RAIZ, "datos", "grn.db"))
    p.add_argument("--fulltext", default=os.path.join(RAIZ, "datos", "fulltext"))
    p.add_argument("--estricto", action="store_true",
                   help="sale con codigo 1 si alguna oracion no se encuentra")
    args = p.parse_args(argv)

    with io.open(args.oro, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f, delimiter="\t"))

    textos = cargar_textos(args.db, args.fulltext)
    print("PMIDs con algun texto disponible: %d" % len(textos))
    if not textos:
        print("\nNo hay corpus. Copia datos/ a esta maquina; ver")
        print("docs/traspaso-maquina-nueva.md.")
        return 1

    conteo, fallos = verificar(filas, textos)

    print("")
    for clave in ("exacta", "fragmento_contiguo", "no_encontrada",
                  "sin_texto_del_pmid", "sin_oracion", "no_atestiguada"):
        if conteo[clave]:
            print("  %-22s %3d" % (clave, conteo[clave]))

    verificadas = conteo["exacta"] + conteo["fragmento_contiguo"]
    atestiguadas = len(filas) - conteo["no_atestiguada"]
    print("\n  verificadas: %d de %d atestiguadas" % (verificadas, atestiguadas))

    if fallos:
        print("\nlas que no cuadran (%d):" % len(fallos))
        for tf, blanco, motivo, frase in fallos:
            print("  %-8s -> %-14s %-26s %s" % (tf, blanco, motivo, frase))
        print("\nRevisa cada una a mano: puede ser una edicion menor de la")
        print("oracion, o una cita que no corresponde a la fila.")

    return 1 if (args.estricto and fallos) else 0


if __name__ == "__main__":
    sys.exit(main())
