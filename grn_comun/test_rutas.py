# -*- coding: utf-8 -*-
"""La precedencia de las rutas de datos: flag > `GRN_DATOS` > `./datos`.

Hasta el 20-oct-2026 vivía en `grn_bronce` y no tenía prueba propia: la
cubrían de lado las del CLI del paso 0 y las del tablero.

    python -m unittest discover .
"""

import os
import unittest
from unittest import mock

from grn_comun import rutas


class PruebasPrecedencia(unittest.TestCase):

    def test_el_flag_le_gana_al_entorno(self):
        with mock.patch.dict(os.environ, {rutas.VARIABLE: "/del_entorno"}):
            self.assertEqual(rutas.raiz_datos("/del_flag"), "/del_flag")
            self.assertEqual(rutas.de_donde("/del_flag"), "flag")

    def test_sin_flag_manda_el_entorno(self):
        with mock.patch.dict(os.environ, {rutas.VARIABLE: "/del_entorno"}):
            self.assertEqual(rutas.raiz_datos(), "/del_entorno")
            self.assertEqual(rutas.de_donde(), "entorno:GRN_DATOS")

    def test_sin_nada_es_datos(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(rutas.VARIABLE, None)
            self.assertEqual(rutas.raiz_datos(), "datos")
            self.assertEqual(rutas.de_donde(), "omision")

    def test_ruta_une_bajo_la_raiz(self):
        self.assertEqual(rutas.ruta("grn.db", flag="D"),
                         os.path.join("D", "grn.db"))


class PruebasPuente(unittest.TestCase):

    def test_grn_bronce_reexporta_los_mismos_objetos(self):
        """Quien importa `grn_bronce.rutas` sigue usando esta misma
        precedencia, no una copia."""
        from grn_bronce import rutas as puente
        for nombre in ("raiz_datos", "ruta", "de_donde", "VARIABLE",
                       "POR_OMISION"):
            self.assertIs(getattr(puente, nombre), getattr(rutas, nombre))


if __name__ == "__main__":
    unittest.main()
