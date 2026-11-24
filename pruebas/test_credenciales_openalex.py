# -*- coding: utf-8 -*-
"""La llave de OpenAlex sale del entorno o de su archivo, nunca del código."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from grn_etl import credenciales


class PruebasLlaveOpenAlex(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archivo = Path(self.tmp.name) / "openalex.key"
        parche = mock.patch.object(credenciales, "ARCHIVO_LLAVE_OPENALEX",
                                   self.archivo)
        parche.start()
        self.addCleanup(parche.stop)

    def test_sin_entorno_ni_archivo_no_hay_llave(self):
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("OPENALEX_API_KEY", None)
            self.assertIsNone(credenciales.llave_openalex())

    def test_el_archivo_se_lee_sin_el_salto_de_linea(self):
        self.archivo.write_text("abc123\n", encoding="utf-8")
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop("OPENALEX_API_KEY", None)
            self.assertEqual(credenciales.llave_openalex(), "abc123")

    def test_el_entorno_gana_sobre_el_archivo(self):
        self.archivo.write_text("del-archivo\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"OPENALEX_API_KEY": "del-entorno"}):
            self.assertEqual(credenciales.llave_openalex(), "del-entorno")

    def test_el_archivo_real_lo_cubre_el_gitignore(self):
        raiz = credenciales.RAIZ
        ignorados = (raiz / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn("*.key", ignorados)
        self.assertTrue(str(credenciales.RAIZ / "openalex.key").endswith(".key"))


if __name__ == "__main__":
    unittest.main()
