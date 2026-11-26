# -*- coding: utf-8 -*-
"""La red del lector por artículo y su unión con la del paso 2, con
relaciones inventadas.

    python -m unittest etapa2.test_red_curador
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import red as R             # noqa: E402
import red_curador as C     # noqa: E402


def _valida(pmid, tf, blanco, efecto, estado="valida"):
    return {"pmid": pmid, "nodo_regulador": tf, "nodo_blanco": blanco,
            "efecto": efecto, "estado": estado}


class PruebasRed(unittest.TestCase):

    def test_un_voto_por_articulo_y_efecto(self):
        red = C.red_del_curador([
            _valida("1", "fooR", "barA", "activates"),
            _valida("1", "FooR", "barA", "activates"),
            _valida("2", "fooR", "barA", "activates"),
            _valida("3", "fooR", "barA", "represses"),
            _valida("3", "fooR", "bazC", "regulates"),
        ])
        self.assertEqual(sorted(red), [("foor", "bara"), ("foor", "bazc")])
        a = red[("foor", "bara")]
        self.assertEqual((a["tf"], a["signo"], a["conflicto"],
                          a["n_evidencias"], a["n_activates"],
                          a["n_represses"], a["n_articulos"], a["pmids"]),
                         ("fooR", "activates", "false", "3", "2", "1", "3",
                          "1|2|3"))
        self.assertEqual(red[("foor", "bazc")]["signo"], "regulates")
        self.assertEqual(set(a), set(R.COLUMNAS_RED))

    def test_el_signo_es_el_de_la_regla_de_red_py(self):
        empate = C.red_del_curador([_valida("1", "fooR", "barA", "activates"),
                                    _valida("2", "fooR", "barA", "represses")])
        self.assertEqual((empate[("foor", "bara")]["signo"],
                          empate[("foor", "bara")]["conflicto"]),
                         ("regulates", "true"))
        self.assertEqual(R.resolver_signo(1, 1, 0.66), ("regulates", True))

    def test_un_efecto_desconocido_es_un_error(self):
        with self.assertRaises(ValueError):
            C.red_del_curador([_valida("1", "fooR", "barA", "inhibits")])

    def test_la_union(self):
        red = {("a", "b"): {"signo": "regulates", "n_evidencias": "9"},
               ("a", "c"): {"signo": "activates", "n_evidencias": "2"}}
        curador = {("a", "b"): {"signo": "represses", "n_evidencias": "1"},
                   ("a", "c"): {"signo": "represses", "n_evidencias": "1"},
                   ("a", "d"): {"signo": "activates", "n_evidencias": "1"}}
        union = C.unir(red, curador)
        # Sin signo en la red: vale el del curador, con las cuentas de la red.
        self.assertEqual(union[("a", "b")],
                         {"signo": "represses", "n_evidencias": "9"})
        # Los dos traen signo: vale el de la red.
        self.assertEqual(union[("a", "c")]["signo"], "activates")
        self.assertEqual(union[("a", "d")]["signo"], "activates")
        self.assertEqual(red[("a", "b")]["signo"], "regulates")

    def test_lee_solo_las_validas_y_escribe_la_red(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ruta = os.path.join(tmp, "relaciones.tsv")
        columnas = ["pmid", "nodo_regulador", "nodo_blanco", "efecto",
                    "estado"]
        filas = [_valida("1", "fooR", "barA", "activates"),
                 _valida("1", "", "", "activates", estado="sin_locus")]
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write("\t".join(columnas) + "\n")
            for fila in filas:
                f.write("\t".join(fila[c] for c in columnas) + "\n")
        salida = os.path.join(tmp, "red_curador.tsv")
        with contextlib.redirect_stdout(io.StringIO()) as dicho:
            self.assertEqual(
                C.main(["--relaciones", ruta, "--salida", salida]), 0)
        self.assertIn("aristas: 1", dicho.getvalue())
        with io.open(salida, encoding="utf-8") as f:
            renglones = f.read().splitlines()
        self.assertEqual(renglones[0].split("\t"), R.COLUMNAS_RED)
        self.assertEqual(len(renglones), 2)
        self.assertEqual(renglones[1].split("\t")[:3],
                         ["fooR", "barA", "activates"])
        self.assertFalse(os.path.exists(salida + ".tmp"))


if __name__ == "__main__":
    unittest.main()
