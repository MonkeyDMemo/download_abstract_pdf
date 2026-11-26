# -*- coding: utf-8 -*-
"""La red del lector por artículo, con las columnas de `red.tsv`.

    python etapa2/red_curador.py --relaciones DIR/relaciones.tsv --salida T

`grn_ouroboros.cli curar` deja `relaciones.tsv`: una fila por relación que un
artículo afirma, con sus citas comprobadas. Aquí se agregan las `valida` en
una arista por par de nodos, para que el evaluador, el contraste y el visor
que ya leen `red.tsv` la lean sin cambios.

- **Un voto por artículo y efecto.** Que un artículo repita la relación con
  otras citas no la hace más cierta.
- **El signo sale de la regla de mayoría de `red.py`** (`resolver_signo`), no
  de una segunda.
- `confianza` va vacía: el lector no da una probabilidad. La
  `oracion_representativa` también: las citas están en `relaciones.tsv`.

Es del pipeline: no abre ninguna referencia. Solo biblioteca estándar.
"""

import argparse
import collections
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import red as R                                # noqa: E402
from grn_bronce.operones import clave          # noqa: E402

EFECTOS = ("activates", "represses", "regulates")


def leer_validas(ruta):
    """Las relaciones `valida` de un `relaciones.tsv` del curador."""
    with io.open(ruta, encoding="utf-8", newline="") as f:
        return [fila for fila in csv.DictReader(f, delimiter="\t")
                if fila["estado"] == "valida"]


def red_del_curador(validas, mayoria=0.66):
    """{(clave tf, clave blanco): fila} con las columnas de `red.tsv`."""
    votos = collections.OrderedDict()
    nombres = {}
    for fila in validas:
        llave = (clave(fila["nodo_regulador"]), clave(fila["nodo_blanco"]))
        nombres.setdefault(llave, (fila["nodo_regulador"],
                                   fila["nodo_blanco"]))
        if fila["efecto"] not in EFECTOS:
            raise ValueError("Efecto desconocido: %r." % fila["efecto"])
        votos.setdefault(llave, set()).add((fila["pmid"], fila["efecto"]))
    red = {}
    for llave in sorted(votos):
        cuenta = collections.Counter(efecto for _pmid, efecto in votos[llave])
        signo, conflicto = R.resolver_signo(cuenta["activates"],
                                            cuenta["represses"], mayoria)
        pmids = sorted(set(pmid for pmid, _efecto in votos[llave]))
        tf, blanco = nombres[llave]
        red[llave] = {
            "tf": tf, "blanco": blanco, "signo": signo,
            "conflicto": R.texto_bool(conflicto),
            "n_evidencias": str(len(votos[llave])),
            "n_activates": str(cuenta["activates"]),
            "n_represses": str(cuenta["represses"]),
            "n_regulates": str(cuenta["regulates"]),
            "n_articulos": str(len(pmids)), "confianza": "",
            "autorregulacion": "false", "secciones": "",
            "pmids": "|".join(pmids), "oracion_representativa": ""}
    return red


def unir(red, curador):
    """La unión de la red del paso 2 y la del curador. No modifica sus
    entradas.

    Las aristas de las dos. Donde la red del paso 2 no trae signo
    (`regulates`) y el curador sí, vale el del curador, con las cuentas de la
    red; donde las dos lo traen, vale el de la red del paso 2, que es la que
    ya está medida.
    """
    union = dict(red)
    for llave, fila in curador.items():
        vieja = union.get(llave)
        if vieja is None:
            union[llave] = fila
        elif vieja["signo"] == "regulates" and fila["signo"] != "regulates":
            union[llave] = dict(vieja, signo=fila["signo"])
    return union


def escribir_red(ruta, red):
    R.escribir_tsv(ruta, R.COLUMNAS_RED,
                   [[red[k][c] for c in R.COLUMNAS_RED] for k in sorted(red)])
    os.replace(ruta + ".tmp", ruta)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="La red del lector por artículo, con las columnas de "
                    "red.tsv.")
    ap.add_argument("--relaciones", required=True,
                    help="El relaciones.tsv de `grn_ouroboros.cli curar`.")
    ap.add_argument("--salida", required=True, help="El TSV que se escribe.")
    ap.add_argument("--mayoria", type=float, default=0.66)
    args = ap.parse_args(argv)
    red = red_del_curador(leer_validas(args.relaciones), args.mayoria)
    escribir_red(args.salida, red)
    signos = collections.Counter(a["signo"] for a in red.values())
    print("aristas: %d (%s)" % (len(red), ", ".join(
        "%s %d" % (s, signos[s]) for s in EFECTOS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
