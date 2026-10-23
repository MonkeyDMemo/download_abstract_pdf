# -*- coding: utf-8 -*-
"""Las consultas de solo lectura del bronce que no son de corridas.

Por ahora una: `vecinas()`, la oración en una posición y las dos que la
rodean, para la herramienta `contexto` de `grn_ouroboros`. Las oraciones son
sintéticas.

    python -m unittest grn_bronce.test_db
"""

import os
import shutil
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import db as bdb           # noqa: E402


def _unidad(con, corrida, num, texto, fuente="xml", pmid="1"):
    bdb.guardar_unidad(con, corrida, {
        "pmid": pmid, "fuente_texto": fuente, "seccion": "results",
        "num_oracion": num, "texto": texto, "offset_ini": 0,
        "offset_fin": len(texto), "contiguo": True})


class PruebasVecinas(unittest.TestCase):

    def setUp(self):
        self.con = bdb.conectar(":memory:")
        self.addCleanup(self.con.close)
        for pmid in ("1", "2"):
            self.con.execute(
                """INSERT INTO documentos (pmid, titulo, anio, extraido_en)
                   VALUES (?, 'Un título', '2020', ?)""", (pmid, bdb.ahora()))
        self.corrida = bdb.abrir_corrida(self.con, "1", "m", "1")
        self.otra = bdb.abrir_corrida(self.con, "1", "m", "2")
        _unidad(self.con, self.corrida, 0, "Resumen, última oración.",
                fuente="abstract")
        for num, texto in enumerate(["Primera.", "Segunda.", "Tercera."],
                                    start=1):
            _unidad(self.con, self.corrida, num, texto)
        # Lo que no tiene que colarse: la misma posición en otra corrida y
        # en otro artículo.
        _unidad(self.con, self.otra, 2, "De otra corrida.")
        _unidad(self.con, self.corrida, 3, "De otro artículo.", pmid="2")

    def test_la_del_medio_trae_sus_dos_vecinas(self):
        self.assertEqual(
            bdb.vecinas(self.con, self.corrida, "1", "xml", 2),
            {"anterior": "Primera.", "oracion": "Segunda.",
             "siguiente": "Tercera."})

    def test_la_fuente_no_se_cruza(self):
        """La 0 es del resumen: no es la anterior de la 1 del texto
        completo aunque el número sea correlativo."""
        r = bdb.vecinas(self.con, self.corrida, "1", "xml", 1)
        self.assertIsNone(r["anterior"])
        self.assertEqual(r["siguiente"], "Segunda.")

    def test_la_ultima_no_tiene_siguiente(self):
        r = bdb.vecinas(self.con, self.corrida, "1", "xml", 3)
        self.assertEqual(r["anterior"], "Segunda.")
        self.assertIsNone(r["siguiente"])

    def test_otra_corrida_y_otro_articulo_no_se_mezclan(self):
        self.assertEqual(
            bdb.vecinas(self.con, self.otra, "1", "xml", 2),
            {"anterior": None, "oracion": "De otra corrida.",
             "siguiente": None})
        self.assertEqual(
            bdb.vecinas(self.con, self.corrida, "2", "xml", 3)["oracion"],
            "De otro artículo.")

    def test_el_numero_de_la_llave_llega_como_texto(self):
        """`llave.csv` trae `num_oracion` como texto, y el PMID también."""
        self.assertEqual(
            bdb.vecinas(self.con, self.corrida, 1, "xml", "2")["oracion"],
            "Segunda.")

    def test_una_posicion_que_no_existe_da_todo_vacio(self):
        self.assertEqual(
            bdb.vecinas(self.con, self.corrida, "1", "xml", 40),
            {"anterior": None, "oracion": None, "siguiente": None})

    def test_lee_con_la_conexion_de_solo_lectura(self):
        """La herramienta abre la base con `conectar_lectura`."""
        carpeta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, carpeta, True)
        ruta = os.path.join(carpeta, "grn.db")
        con = bdb.conectar(ruta)
        con.execute(
            """INSERT INTO documentos (pmid, titulo, anio, extraido_en)
               VALUES ('1', 'Un título', '2020', ?)""", (bdb.ahora(),))
        corrida = bdb.abrir_corrida(con, "1", "m", "1")
        _unidad(con, corrida, 5, "Antes.")
        _unidad(con, corrida, 6, "Ahora.")
        con.commit()
        con.close()
        lectura = bdb.conectar_lectura(ruta)
        try:
            self.assertEqual(
                bdb.vecinas(lectura, corrida, "1", "xml", 6),
                {"anterior": "Antes.", "oracion": "Ahora.",
                 "siguiente": None})
        finally:
            lectura.close()


if __name__ == "__main__":
    unittest.main()
