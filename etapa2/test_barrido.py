# -*- coding: utf-8 -*-
"""Pruebas del barrido.

La que no puede faltar: un `.error` de un intento que despues salio bien no
puede seguir contando como fallo. Si cuenta, el barrido se declara incompleto
para siempre y no vuelve a anunciar ganadora nunca, que es la unica salida que
de verdad se lee de todo esto. Paso de verdad: run_13 murio con SIGSEGV, se
rehizo bien, y el resumen seguia diciendo FALLARON.

    python -m unittest discover etapa2
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

import barrido as B


class PruebasResumen(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def corrida_buena(self, nombre, **campos):
        fila = {"nombre": nombre, "dev_macro_f1": 0.5, "test_macro_f1": 0.4,
                "dev_accuracy": 0.6, "test_accuracy": 0.5, "huella": "abc"}
        fila.update(campos)
        with open(os.path.join(self.dir, nombre + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(fila, f)

    def marca_de_fallo(self, nombre, codigo=-11):
        with open(os.path.join(self.dir, nombre + ".json.error"), "w",
                  encoding="utf-8") as f:
            json.dump({"nombre": nombre, "codigo": codigo, "huella": "abc"}, f)

    def correr(self, esperadas):
        pantalla = io.StringIO()
        with contextlib.redirect_stdout(pantalla):
            filas = B.resumen(self.dir, esperadas)
        return filas, pantalla.getvalue()

    def test_error_de_un_intento_que_luego_salio_bien_no_cuenta(self):
        self.corrida_buena("run_13", dev_macro_f1=0.9)
        self.marca_de_fallo("run_13")
        filas, salida = self.correr(1)
        self.assertEqual(len(filas), 1)
        self.assertNotIn("FALLARON", salida)
        self.assertIn("Mejor: run_13", salida)

    def test_error_sin_corrida_buena_si_bloquea_la_ganadora(self):
        self.corrida_buena("run_12")
        self.marca_de_fallo("run_13")
        filas, salida = self.correr(2)
        self.assertEqual(len(filas), 1)
        self.assertIn("FALLARON 1: run_13", salida)
        self.assertIn("INCOMPLETO", salida)
        self.assertNotIn("Mejor:", salida)

    def test_barrido_al_que_le_faltan_corridas_no_anuncia_ganadora(self):
        self.corrida_buena("run_1")
        filas, salida = self.correr(24)
        self.assertIn("1 de 24 corridas completas", salida)
        self.assertNotIn("Mejor:", salida)

    def test_json_truncado_sale_como_ilegible_y_no_como_ganadora(self):
        self.corrida_buena("run_1")
        with open(os.path.join(self.dir, "run_2.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"nombre": "run_2", "dev_ma')
        filas, salida = self.correr(2)
        self.assertEqual(len(filas), 1)
        self.assertIn("ILEGIBLES 1: run_2.json", salida)
        self.assertNotIn("Mejor:", salida)


if __name__ == "__main__":
    unittest.main()
