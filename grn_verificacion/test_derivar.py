# -*- coding: utf-8 -*-
"""Las redes derivadas: cortes por nivel, B1 (voltear) y B2 (signo)."""
import io
import json
import os
import tempfile
import unittest

from grn_verificacion import contraste, derivar

COLUMNAS_RED = ("tf", "blanco", "signo", "pmids", "signo_agente", "votos_si",
                "nivel")
COLUMNAS_EV = ("tf", "blanco", "id_par", "pmid")
# tf, blanco, signo, signo del jurado, votos, nivel, locus del tf y del blanco
ARISTAS = (
    ("LasR", "rhlR", "regulates", "+", "3", "alta", "PA1430", "PA3477"),
    ("mexA", "MexT", "regulates", "-", "2", "al_reves", "PA0425", "PA2492"),
    ("pslA", "FleQ", "activates", "+", "1", "al_reves", "PA2231", "PA1097"),
    ("algD", "AlgU", "regulates", "+", "3", "al_reves", "PA3540", "PA0762"),
    ("AlgU", "algD", "regulates", "", "1", "media", "PA0762", "PA3540"),
    ("PqsR", "pqsA", "regulates", "", "0", "sin_respaldo", "PA1003", "PA0996"),
)


class PruebasDerivar(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.carpeta = os.path.join(tmp.name, "corrida")
        self.salida = os.path.join(tmp.name, "derivada")
        os.makedirs(self.carpeta)
        red, evidencias, pares = [], [], []
        for i, (tf, blanco, signo, agente, votos, nivel, la, lb) in enumerate(
                ARISTAS):
            red.append((tf, blanco, signo, "1000000%d" % i, agente, votos,
                        nivel))
            evidencias.append((tf, blanco, "id%d" % i, "1000000%d" % i))
            pares.append({"id_par": "id%d" % i, "tf": tf, "target": blanco,
                          "tf_locus": [la], "target_locus": [lb]})
        pares.append({"id_par": "ajeno", "tf_locus": ["PA0001"],
                      "target_locus": ["PA0002"]})
        self._tsv("red_juez.tsv", COLUMNAS_RED, red)
        self._tsv("red_evidencias.tsv", COLUMNAS_EV, evidencias)
        with io.open(os.path.join(self.carpeta, "pares.jsonl"), "w",
                     encoding="utf-8") as f:
            for par in pares:
                f.write(json.dumps(par) + "\n")

    def _tsv(self, nombre, columnas, filas):
        with io.open(os.path.join(self.carpeta, nombre), "w",
                     encoding="utf-8", newline="") as f:
            f.write("\t".join(columnas) + "\n")
            for fila in filas:
                f.write("\t".join(fila) + "\n")

    def _locus(self, **kw):
        resumen = derivar.ejecutar(self.carpeta, self.salida, **kw)
        por_par, conteos = contraste.aristas_en_locus(
            os.path.join(self.salida, "red.tsv"),
            os.path.join(self.salida, "red_evidencias.tsv"),
            os.path.join(self.salida, "pares.jsonl"))
        return resumen["conteos"], por_par, conteos

    def test_sin_opciones_es_la_misma_red(self):
        cuenta, por_par, conteos = self._locus()
        self.assertEqual(cuenta["aristas"], len(ARISTAS))
        self.assertEqual(conteos["con_locus"], len(ARISTAS))
        self.assertIn(("PA0425", "PA2492"), por_par)
        self.assertNotIn("volteadas", cuenta)

    def test_el_corte_de_alta_deja_solo_las_altas(self):
        cuenta, por_par, _ = self._locus(niveles=("alta",))
        self.assertEqual(cuenta["aristas"], 1)
        self.assertEqual(list(por_par), [("PA1430", "PA3477")])
        self.assertEqual(cuenta["pares"], 1)

    def test_voltear_cambia_el_sentido_con_dos_votos(self):
        cuenta, por_par, _ = self._locus(voltear=True)
        self.assertIn(("PA2492", "PA0425"), por_par, "MexT -> mexA")
        self.assertNotIn(("PA0425", "PA2492"), por_par)
        self.assertEqual(por_par[("PA2492", "PA0425")][0]["tf"], "MexT")
        self.assertEqual(cuenta["volteadas"], 1)

    def test_con_un_voto_la_arista_no_se_voltea(self):
        _, por_par, _ = self._locus(voltear=True)
        self.assertIn(("PA2231", "PA1097"), por_par, "pslA -> FleQ se queda")

    def test_la_volteada_que_ya_esta_no_se_duplica(self):
        cuenta, por_par, _ = self._locus(voltear=True)
        self.assertEqual(cuenta["volteadas_ya_en_la_red"], 1)
        self.assertEqual(len(por_par[("PA0762", "PA3540")]), 1)
        self.assertNotIn(("PA3540", "PA0762"), por_par)
        self.assertEqual(cuenta["aristas"], len(ARISTAS) - 1)

    def test_el_corte_con_volteadas_no_trae_las_de_un_voto(self):
        cuenta, por_par, _ = self._locus(
            niveles=("alta", "media", "volteadas"), voltear=True)
        self.assertEqual(sorted(por_par), [("PA0762", "PA3540"),
                                           ("PA1430", "PA3477"),
                                           ("PA2492", "PA0425")])
        self.assertEqual(cuenta["aristas"], 3)

    def test_el_signo_del_jurado_solo_donde_la_red_se_abstiene(self):
        cuenta, por_par, _ = self._locus(voltear=True, signo=True)
        self.assertEqual(por_par[("PA1430", "PA3477")][0]["signo"],
                         "activates")
        self.assertEqual(por_par[("PA2492", "PA0425")][0]["signo"],
                         "represses", "la volteada toma el signo del jurado")
        self.assertEqual(por_par[("PA2231", "PA1097")][0]["signo"],
                         "activates", "la red ya le había dado signo")
        self.assertEqual(por_par[("PA0762", "PA3540")][0]["signo"],
                         "regulates", "el jurado no dio signo")
        self.assertEqual(cuenta["signo_del_jurado"], 2)

    def test_sin_voltear_el_signo_no_toca_las_al_reves(self):
        cuenta, por_par, _ = self._locus(signo=True)
        self.assertEqual(por_par[("PA0425", "PA2492")][0]["signo"],
                         "regulates")
        self.assertEqual(cuenta["signo_del_jurado"], 1)

    def test_un_id_par_ausente_detiene_todo(self):
        with io.open(os.path.join(self.carpeta, "pares.jsonl"), "w",
                     encoding="utf-8") as f:
            f.write(json.dumps({"id_par": "id0", "tf_locus": ["PA1430"],
                                "target_locus": ["PA3477"]}) + "\n")
        with self.assertRaises(ValueError):
            derivar.ejecutar(self.carpeta, self.salida)


if __name__ == "__main__":
    unittest.main()
