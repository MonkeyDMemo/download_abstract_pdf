# -*- coding: utf-8 -*-
"""La red del lector por artículo y su unión con la del paso 2, con
relaciones inventadas.

    python -m unittest etapa2.test_red_curador
"""

import contextlib
import io
import json
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


def _rel(pmid, locus_r, locus_b, efecto, estado="valida"):
    return {"pmid": pmid, "nodo_regulador": "r", "nodo_blanco": "b",
            "locus_regulador": locus_r, "locus_blanco": locus_b,
            "efecto": efecto, "estado": estado}


def _tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(str(fila.get(c, "")) for c in columnas) + "\n")


class PruebasPorLocus(unittest.TestCase):
    """La red por par de locus, con una red de juguete: un operón, un gen
    nombrado de dos maneras con signos distintos (mixto) y una
    autorregulación."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.flujo = os.path.join(self.tmp, "corridaX")
        os.makedirs(self.flujo)
        red = [
            {"tf": "FooR", "blanco": "barAB", "signo": "regulates",
             "pmids": "1|2"},
            {"tf": "FooR", "blanco": "zorK", "signo": "activates",
             "pmids": "3"},
            {"tf": "fooR", "blanco": "zorK", "signo": "represses",
             "pmids": "4"},
            {"tf": "FooR", "blanco": "quxB", "signo": "activates",
             "pmids": "5"},
            {"tf": "FooR", "blanco": "fooR", "signo": "regulates",
             "pmids": "6", "autorregulacion": "true"},
        ]
        _tsv(os.path.join(self.flujo, "red.tsv"), R.COLUMNAS_RED,
             [dict({"conflicto": "false", "autorregulacion": "false"}, **f)
              for f in red])
        evidencias = [("FooR", "barAB", "p1", "1"), ("FooR", "barAB", "p1", "2"),
                      ("FooR", "zorK", "p2", "3"), ("fooR", "zorK", "p3", "4"),
                      ("FooR", "quxB", "p4", "5"), ("FooR", "quxB", "p4", "7"),
                      ("FooR", "fooR", "p5", "6")]
        _tsv(os.path.join(self.flujo, "red_evidencias.tsv"),
             R.COLUMNAS_EVIDENCIAS,
             [dict(zip(("tf", "blanco", "id_par", "pmid"), e))
              for e in evidencias])
        pares = [("p1", ["PA0001"], ["PA0010", "PA0011"]),
                 ("p2", ["PA0001"], ["PA0020"]), ("p3", ["PA0001"], ["PA0020"]),
                 ("p4", ["PA0001"], ["PA0030"]), ("p5", ["PA0001"], ["PA0001"])]
        with io.open(os.path.join(self.flujo, "pares.jsonl"), "w",
                     encoding="utf-8") as f:
            for i, a, b in pares:
                f.write(json.dumps({"id_par": i, "tf": "x", "target": "y",
                                    "tf_locus": a, "target_locus": b}) + "\n")
        self.de_la_red = {
            ("PA0001", "PA0010"): {"regulates": {"1", "2"}},
            ("PA0001", "PA0011"): {"regulates": {"1", "2"}},
            ("PA0001", "PA0020"): {"activates": {"3"}, "represses": {"4"}},
            ("PA0001", "PA0030"): {"activates": {"5", "7"}},
        }

    def test_la_red_en_pares_de_locus(self):
        self.assertEqual(C.pares_de_la_red(self.flujo), self.de_la_red)

    def test_reescribir_la_red_no_cambia_nada(self):
        salida = os.path.join(self.tmp, "locus")
        conteos = C.carpeta_para_contraste(salida, unir_con=self.flujo)
        self.assertEqual((conteos["pares_de_locus"], conteos["aristas"],
                          conteos["pares_mixtos"]), (4, 5, 1))
        # Lo que el contraste ve en la carpeta reescrita es lo mismo.
        self.assertEqual(C.pares_de_la_red(salida), self.de_la_red)
        self.assertEqual(
            sorted(os.listdir(salida)),
            ["derivada.json", "pares.jsonl", "red.tsv", "red_evidencias.tsv"])

    def test_los_votos_por_par(self):
        votos = C.votos_por_par([
            _rel("1", "PA0001", "PA0010|PA0011", "activates"),
            _rel("1", "PA0001", "PA0010", "activates"),
            _rel("2", "PA0001", "PA0001", "activates"),
        ])
        self.assertEqual(votos, {
            ("PA0001", "PA0010"): {("1", "activates")},
            ("PA0001", "PA0011"): {("1", "activates")}})

    def test_el_signo_del_curador_y_el_acuerdo(self):
        uno = [_rel("1", "PA0001", "PA0010", "activates"),
               _rel("2", "PA0001", "PA0040", "represses")]
        otro = [_rel("1", "PA0001", "PA0010", "activates"),
                _rel("3", "PA0001", "PA0010", "represses"),
                _rel("4", "PA0001", "PA0010", "activates")]
        juntos = C.pares_del_curador([uno, otro])
        # El mismo artículo y efecto en los dos lectores es un voto: 2 a 1,
        # que con mayoría 0.66 alcanza.
        self.assertEqual(juntos, {
            ("PA0001", "PA0010"): {"activates": {"1", "3", "4"}},
            ("PA0001", "PA0040"): {"represses": {"2"}}})
        self.assertEqual(sorted(C.pares_del_curador([uno, otro],
                                                    solo_acuerdo=True)),
                         [("PA0001", "PA0010")])
        empate = C.pares_del_curador([otro[:2]])
        self.assertEqual(list(empate[("PA0001", "PA0010")]), ["regulates"])

    def test_la_union_por_par(self):
        curador = {
            ("PA0001", "PA0010"): {"activates": {"9"}},   # la red: regulates
            ("PA0001", "PA0011"): {"regulates": {"9"}},   # ninguno da signo
            ("PA0001", "PA0020"): {"activates": {"9"}},   # la red: mixto
            ("PA0001", "PA0030"): {"represses": {"9"}},   # la red: activates
            ("PA0001", "PA0050"): {"represses": {"9"}},   # la red no lo tiene
        }
        union, cuenta = C.unir_pares(self.de_la_red, curador)
        self.assertEqual(union, {
            ("PA0001", "PA0010"): {"activates": {"1", "2", "9"}},
            ("PA0001", "PA0011"): {"regulates": {"1", "2"}},
            ("PA0001", "PA0020"): {"activates": {"3"}, "represses": {"4"}},
            ("PA0001", "PA0030"): {"activates": {"5", "7"}},
            ("PA0001", "PA0050"): {"represses": {"9"}}})
        self.assertEqual(dict(cuenta), {
            "en_las_dos_signo_del_curador": 1, "en_las_dos_vale_la_red": 3,
            "solo_curador": 1})
        # No toca sus entradas.
        self.assertEqual(self.de_la_red[("PA0001", "PA0010")],
                         {"regulates": {"1", "2"}})

    def test_la_carpeta_de_la_union(self):
        relaciones = os.path.join(self.tmp, "relaciones.tsv")
        _tsv(relaciones, ["pmid", "nodo_regulador", "nodo_blanco",
                          "locus_regulador", "locus_blanco", "efecto",
                          "estado"],
             [_rel("9", "PA0001", "PA0010|PA0011", "activates"),
              _rel("9", "PA0001", "PA0050", "represses"),
              _rel("9", "PA0001", "PA0060", "represses", estado="sin_locus")])
        salida = os.path.join(self.tmp, "union")
        with contextlib.redirect_stdout(io.StringIO()) as dicho:
            self.assertEqual(C.main(["--relaciones", relaciones,
                                     "--carpeta-contraste", salida,
                                     "--unir-con", self.flujo]), 0)
        conteos = json.loads(dicho.getvalue())
        self.assertEqual(conteos["union"], {
            "en_las_dos_signo_del_curador": 2, "solo_curador": 1,
            "solo_red": 2})
        self.assertEqual((conteos["pares_del_curador"],
                          conteos["pares_de_la_red"],
                          conteos["pares_de_locus"]), (3, 4, 5))
        visto = C.pares_de_la_red(salida)
        self.assertEqual(visto[("PA0001", "PA0010")],
                         {"activates": {"1", "2", "9"}})
        self.assertEqual(visto[("PA0001", "PA0050")], {"represses": {"9"}})
        self.assertEqual(visto[("PA0001", "PA0020")],
                         self.de_la_red[("PA0001", "PA0020")])
        # El lector solo, sin unir.
        solo = os.path.join(self.tmp, "solo")
        conteos = C.carpeta_para_contraste(solo, [relaciones])
        self.assertEqual(sorted(C.pares_de_la_red(solo)),
                         [("PA0001", "PA0010"), ("PA0001", "PA0011"),
                          ("PA0001", "PA0050")])

    def test_los_argumentos_que_no_van_juntos(self):
        for argumentos in ([], ["--salida", "x", "--carpeta-contraste", "y"],
                           ["--carpeta-contraste", os.path.join(self.tmp, "z")],
                           ["--salida", "x", "--relaciones", "a",
                            "--relaciones", "b"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    C.main(argumentos)


if __name__ == "__main__":
    unittest.main()
