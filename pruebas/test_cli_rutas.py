# -*- coding: utf-8 -*-
"""El CLI del paso 0 y el tablero abren la misma base.

Antes el CLI tenía `datos/grn.db` y `datos/fulltext` escritos a mano y el
tablero seguía `GRN_DATOS`. En la máquina del laboratorio, donde `GRN_DATOS`
apunta fuera del repositorio, cada frente abría su propia base: el tablero no
veía lo que ingestaba el CLI y volvía a bajarlo todo de NCBI.

    python -m unittest discover .
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

import cli
from pruebas.falsos import PruebaSinRed


class PruebasRutasDelCli(PruebaSinRed):

    def correr(self, argv, entorno):
        """`cli.main()` con `estado`, que solo lee la base y no sale a la
        red. Devuelve la ruta de la base que abrió."""
        abiertas = []
        conectar = cli.db.conectar

        def espia(ruta):
            abiertas.append(ruta)
            return conectar(ruta)

        with mock.patch.dict(os.environ, entorno, clear=False), \
                mock.patch.object(sys, "argv", ["cli.py"] + argv), \
                mock.patch.object(cli.db, "conectar", espia), \
                mock.patch.object(cli, "log", lambda *_a, **_k: None):
            if "GRN_DATOS" not in entorno:
                os.environ.pop("GRN_DATOS", None)
            cli.main()
        return abiertas[0]

    def test_sigue_grn_datos_como_el_tablero(self):
        with tempfile.TemporaryDirectory() as datos:
            ruta = self.correr(["estado"], {"GRN_DATOS": datos})
            self.assertEqual(ruta, os.path.join(datos, "grn.db"))

    def test_el_flag_gana_sobre_grn_datos(self):
        with tempfile.TemporaryDirectory() as datos, \
                tempfile.TemporaryDirectory() as flag:
            ruta = self.correr(["--datos", flag, "estado"],
                               {"GRN_DATOS": datos})
            self.assertEqual(ruta, os.path.join(flag, "grn.db"))
            db_explicita = os.path.join(flag, "otra.db")
            ruta = self.correr(["--db", db_explicita, "estado"],
                               {"GRN_DATOS": datos})
            self.assertEqual(ruta, db_explicita)


if __name__ == "__main__":
    unittest.main()
