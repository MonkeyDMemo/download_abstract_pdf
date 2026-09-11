#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sortea las 50 candidatas dirigidas que se juzgan a mano.

    python etapa2/evaluacion/muestrear_candidatas.py [--datos RUTA] [--salida RUTA]

Reproduce `etapa2/evaluacion/muestra_precision_50.csv` fila por fila: misma
poblacion, misma semilla, mismo barajado. El 4 de septiembre de 2026 el sorteo
se hizo con un script de un solo uso que no quedo en el repositorio, y el unico
numero de precision del paso 1 dependia de un archivo que nadie podia volver a
generar. Este archivo es ese script, versionado.

Que sortea
==========
De la corrida indicada, las oraciones candidatas que traen regulador y blanco
(5 833 en la corrida 1). Las que no tienen par no se pueden juzgar como
relacion dirigida, asi que no entran. La poblacion se ordena por el id de la
candidata, que es estable: la semilla significa lo mismo manana.

Se sortea sin reemplazo con `random.Random(SEMILLA)` y despues se baraja con
`SEMILLA + 1`. El barajado es aparte a proposito: en el orden de la base las
candidatas de un mismo articulo salen juntas y el criterio del juez se contagia
de una fila a la siguiente.

Lo que no lleva, a proposito
============================
Ni el score, ni el patron de oro, ni nada que diga si el par ya es conocido.
El `signo_sugerido` si va, porque `unir_juicios.py` lo compara con el juicio;
la vista que se le da al juez (`juicio_consolidado.csv`) lo quita.

Si la corrida cambia, la muestra cambia y los juicios ya hechos dejan de
corresponder: por eso la corrida es un argumento explicito y no "la ultima".

Solo biblioteca estandar.
"""

import argparse
import csv
import hashlib
import io
import os
import random
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.dirname(AQUI))
sys.path.insert(0, _RAIZ)

from grn_bronce import db, rutas                        # noqa: E402

SEMILLA = 20260904
TAMANO = 50
CORRIDA = 1

COLUMNAS = ["pmid", "oracion", "regulador", "blanco", "disparador",
            "signo_sugerido", "juicio", "signo_correcto"]

# La misma consulta que se corrio el 4 de septiembre. Vive aqui y no en
# `grn_bronce/db.py` por la misma razon que `evaluar_cobertura_bronce.py`
# tiene la suya: es un evaluador, nadie lo importa y el bronce no tiene por
# que saber como se le muestrea.
SQL_POBLACION = """
SELECT u.pmid, u.texto AS oracion,
       c.regulador_candidato AS regulador, c.blanco_candidato AS blanco,
       c.disparador, c.signo_sugerido
  FROM oraciones_candidatas c
  JOIN texto_unidades u ON u.id = c.unidad_id
 WHERE c.corrida_id = ? AND c.regulador_candidato <> ''
   AND c.blanco_candidato <> ''
 ORDER BY c.id
"""


def poblacion(con, corrida_id):
    return con.execute(SQL_POBLACION, (corrida_id,)).fetchall()


def sortear(filas, tamano=TAMANO, semilla=SEMILLA):
    muestra = random.Random(semilla).sample(list(filas), tamano)
    random.Random(semilla + 1).shuffle(muestra)
    return muestra


def escribir(muestra, ruta):
    tmp = ruta + ".tmp"
    # Saltos LF: `.gitattributes` normaliza los CSV a LF al guardarlos, asi que
    # escribir CRLF (lo que `csv` hace por omision) daria un archivo que nunca
    # coincide byte a byte con el versionado.
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, lineterminator="\n")
        w.writeheader()
        for fila in muestra:
            w.writerow({"pmid": fila["pmid"], "oracion": fila["oracion"],
                        "regulador": fila["regulador"],
                        "blanco": fila["blanco"],
                        "disparador": fila["disparador"],
                        "signo_sugerido": fila["signo_sugerido"],
                        "juicio": "", "signo_correcto": ""})
    os.replace(tmp, ruta)


def huella(ruta):
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--datos", default=None,
                    help="raiz de datos; si no, GRN_DATOS o ./datos")
    ap.add_argument("--corrida", type=int, default=CORRIDA)
    ap.add_argument("--semilla", type=int, default=SEMILLA)
    ap.add_argument("--n", type=int, default=TAMANO)
    ap.add_argument("--salida",
                    default=os.path.join(AQUI, "muestra_precision_50.csv"))
    args = ap.parse_args(argv)

    con = db.conectar(os.path.join(rutas.raiz_datos(args.datos), "grn.db"))
    try:
        filas = poblacion(con, args.corrida)
    finally:
        con.close()
    if len(filas) < args.n:
        sys.exit("La corrida %d tiene %d candidatas con par; no alcanzan "
                 "para %d." % (args.corrida, len(filas), args.n))

    muestra = sortear(filas, args.n, args.semilla)
    escribir(muestra, args.salida)

    print("corrida %d: %d candidatas con regulador y blanco"
          % (args.corrida, len(filas)))
    print("semilla %d (barajado con %d): %d filas, %d articulos distintos"
          % (args.semilla, args.semilla + 1, len(muestra),
             len(set(m["pmid"] for m in muestra))))
    print("escrito %s  sha256 %s" % (args.salida, huella(args.salida)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
