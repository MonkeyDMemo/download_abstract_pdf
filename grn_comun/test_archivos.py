# -*- coding: utf-8 -*-
"""Pruebas de `grn_comun.archivos.reemplazar`.

    python -m unittest discover .
"""

import ast
import os
import tempfile
import unittest
from unittest import mock

from grn_comun import archivos


class PruebasReemplazar(unittest.TestCase):

    def test_reemplaza(self):
        with tempfile.TemporaryDirectory() as carpeta:
            tmp = os.path.join(carpeta, "a.tmp")
            final = os.path.join(carpeta, "a.json")
            for ruta, texto in ((final, "viejo"), (tmp, "nuevo")):
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(texto)
            archivos.reemplazar(tmp, final)
            with open(final, encoding="utf-8") as f:
                self.assertEqual(f.read(), "nuevo")
            self.assertFalse(os.path.exists(tmp))

    def test_aguanta_a_un_lector_momentaneo(self):
        """Así falla Windows mientras el tablero tiene abierto el destino."""
        llamadas = []

        def falla_dos_veces(origen, destino):
            llamadas.append((origen, destino))
            if len(llamadas) < 3:
                raise PermissionError(13, "lo tiene abierto otro proceso")

        with mock.patch.object(archivos.os, "replace", falla_dos_veces):
            archivos.reemplazar("a.tmp", "a.json", pausa=0)
        self.assertEqual(len(llamadas), 3)

    def test_un_permiso_de_verdad_termina_en_error(self):
        def siempre(origen, destino):
            raise PermissionError(13, "sin permiso")

        with mock.patch.object(archivos.os, "replace", siempre):
            with self.assertRaises(PermissionError):
                archivos.reemplazar("a.tmp", "a.json", intentos=3, pausa=0)

    def test_borrar_aguanta_a_un_lector_y_no_falla_si_ya_no_esta(self):
        llamadas = []

        def falla_una_vez(ruta):
            llamadas.append(ruta)
            if len(llamadas) < 2:
                raise PermissionError(13, "lo tiene abierto otro proceso")

        with mock.patch.object(archivos.os, "remove", falla_una_vez):
            self.assertTrue(archivos.borrar("a.json", pausa=0))
        self.assertEqual(len(llamadas), 2)
        with tempfile.TemporaryDirectory() as carpeta:
            self.assertTrue(archivos.borrar(os.path.join(carpeta, "no.json")))

    def test_se_lee_con_la_gramatica_de_python_3_8(self):
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "archivos.py")
        with open(ruta, encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
