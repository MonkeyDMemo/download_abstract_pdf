# -*- coding: utf-8 -*-
"""El CLI del paso 0 y el tablero abren la misma base.

Antes el CLI tenía `datos/grn.db` y `datos/fulltext` escritos a mano y el
tablero seguía `GRN_DATOS`. En la máquina del laboratorio, donde `GRN_DATOS`
apunta fuera del repositorio, cada frente abría su propia base: el tablero no
veía lo que ingestaba el CLI y volvía a bajarlo todo de NCBI.

Al final, que `run --tipo-fecha` llegue entero a la ingesta.

    python -m unittest discover .
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import cli
from grn_etl import db
from pruebas.falsos import ClienteFalso, PruebaSinRed


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


class PruebasTipoFechaDelCli(PruebaSinRed):
    """`run --tipo-fecha` con un cliente falso: el valor llega a esearch y a
    la bitácora, por omisión es pdat, y uno que no existe no corre nada."""

    def setUp(self):
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta = os.path.join(carpeta.name, "grn.db")
        con = db.conectar(self.ruta)
        db.alta_consulta(con, "pa", "query de pa")
        con.close()
        self.cliente = ClienteFalso(universo=["111", "222"])

    def correr(self, argv):
        with mock.patch.object(sys, "argv", ["cli.py", "--db", self.ruta]
                               + argv), \
                mock.patch.object(cli, "cliente_de",
                                  lambda _args: self.cliente), \
                mock.patch.object(cli, "log", lambda *_a, **_k: None):
            cli.main()

    def ejecuciones(self):
        con = db.conectar(self.ruta)
        try:
            return [json.loads(f["parametros"])
                    for f in db.historial(con, "pa")]
        finally:
            con.close()

    def test_edat_llega_a_esearch_y_a_la_bitacora(self):
        self.correr(["run", "pa", "--desde", "2026/08/20",
                     "--tipo-fecha", "edat"])

        self.assertEqual(self.cliente.llamadas[0][2]["datetype"], "edat")
        self.assertEqual(self.ejecuciones()[0]["tipo_fecha"], "edat")

    def test_sin_el_flag_es_pdat(self):
        self.correr(["run", "pa", "--desde", "2026"])

        self.assertEqual(self.cliente.llamadas[0][2]["datetype"], "pdat")
        self.assertEqual(self.ejecuciones()[0]["tipo_fecha"], "pdat")

    def test_un_tipo_que_no_existe_no_corre(self):
        with mock.patch.object(sys, "stderr"), \
                self.assertRaises(SystemExit) as ctx:
            self.correr(["run", "pa", "--tipo-fecha", "pubdate"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self.cliente.llamadas, [])
        self.assertEqual(self.ejecuciones(), [])


if __name__ == "__main__":
    unittest.main()
