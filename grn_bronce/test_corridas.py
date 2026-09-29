# -*- coding: utf-8 -*-
"""Las corridas del bronce: qué cuenta como hecho y qué deja `--rehacer`.

Las dos las encontró la revisión del 28-sep-2026, cuando el aviso de recursos
cambiados empezó a recomendar `--rehacer`:

- con `--corpus ""` (todos los documentos), una corrida sobre cualquier
  corpus contaba como hecha, y `--rehacer` borraba la ajena;
- `--rehacer` borraba la corrida anterior antes de identificar, así que una
  nueva cortada dejaba una corrida 'ok' vacía que nadie volvía a hacer; y
  tampoco miraba si la nueva había perdido documentos por error.

    python -m unittest discover .
"""

import argparse
import collections
import os
import sys
import types
import unittest
from unittest import mock

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import cli                 # noqa: E402
from grn_bronce import db as bdb           # noqa: E402
from grn_bronce import identificar as I    # noqa: E402
from grn_bronce import vocabulario as V    # noqa: E402
from grn_etl import db as db0              # noqa: E402


def _base():
    con = bdb.conectar(":memory:")
    con.execute(
        """INSERT INTO documentos (pmid, titulo, anio, extraido_en)
           VALUES ('1', 'Un titulo', '2020', ?)""", (bdb.ahora(),))
    return con


def _corrida_ok(con, corpus_id=None, metodo="m", version="1"):
    """Una corrida terminada bien, con una unidad de texto para poder ver si
    sus filas siguen ahí."""
    cid = bdb.abrir_corrida(con, "1", metodo, version,
                            {"corpus": "(todos los documentos)"}, corpus_id)
    bdb.guardar_unidad(con, cid, {
        "pmid": "1", "fuente_texto": "abstract", "seccion": "abstract",
        "num_oracion": 0, "texto": "MexA is required.", "offset_ini": 0,
        "offset_fin": 17, "contiguo": True})
    bdb.cerrar_corrida(con, cid, "ok", None, 1, 0)
    return cid


def _unidades(con, corrida_id):
    return con.execute("SELECT COUNT(*) FROM texto_unidades WHERE corrida_id = ?",
                       (corrida_id,)).fetchone()[0]


class PruebasCorridaPrevia(unittest.TestCase):

    def setUp(self):
        self.con = _base()
        self.addCleanup(self.con.close)
        self.corpus, _estado = db0.crear_corpus(self.con, "c", pmids=["1"])

    def test_sin_corpus_no_cuenta_la_de_otro_corpus(self):
        _corrida_ok(self.con, self.corpus)

        self.assertIsNone(bdb.corrida_previa(self.con, "m", "1", None))

    def test_con_corpus_no_cuenta_la_de_todos_los_documentos(self):
        """Guarda del caso simétrico, que ya funcionaba: el `corpus_id = ?`
        viejo nunca empataba con NULL. Vigila que el `IS ?` no lo rompa."""
        _corrida_ok(self.con, None)

        self.assertIsNone(bdb.corrida_previa(self.con, "m", "1", self.corpus))

    def test_cada_corpus_encuentra_la_suya(self):
        todos = _corrida_ok(self.con, None)
        congelado = _corrida_ok(self.con, self.corpus)

        self.assertEqual(bdb.corrida_previa(self.con, "m", "1", None)["id"],
                         todos)
        self.assertEqual(
            bdb.corrida_previa(self.con, "m", "1", self.corpus)["id"],
            congelado)

    def test_la_borrada_queda_rehecha_y_deja_de_contar(self):
        """Una 'ok' sin filas se seguía viendo terminada: `--corrida N` la
        volcaba vacía sin decir nada."""
        cid = _corrida_ok(self.con)

        bdb.borrar_corrida(self.con, cid)

        self.assertEqual(bdb.corrida(self.con, cid)["estatus"], "rehecha")
        self.assertEqual(_unidades(self.con, cid), 0)
        self.assertIsNone(bdb.corrida_previa(self.con, "m", "1", None))


class PruebasRehacer(unittest.TestCase):
    """`--rehacer` borra la corrida anterior solo si la nueva terminó bien.

    Lo caro (el diccionario, los vocabularios, identificar y volcar) se
    sustituye: lo que se prueba es el orden entre abrir, cerrar y borrar.
    """

    def setUp(self):
        self.con = _base()
        self.addCleanup(self.con.close)
        self.previa = _corrida_ok(self.con, None, I.METODO, I.VERSION)
        vocab = types.SimpleNamespace(disparadores=[1], funciones=[1],
                                      evidencia=[1], contexto=[1])
        for objeto, nombre, valor in (
                (cli, "log", lambda m: None),
                (I, "cargar_lexico", lambda: {}),
                (I, "cargar_locus_tags", lambda: {}),
                (V.Vocabulario, "cargar", lambda: vocab)):
            p = mock.patch.object(objeto, nombre, valor)
            p.start()
            self.addCleanup(p.stop)

    def _exportar(self):
        args = argparse.Namespace(corrida=None, corpus="", rehacer=True,
                                  datos=None)
        return cli._exportar(self.con, args, 0)

    def _nueva(self):
        return max(f["id"] for f in bdb.listar_corridas(self.con))

    def test_si_la_nueva_se_corta_la_anterior_queda_intacta(self):
        with mock.patch.object(I, "identificar",
                               side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self._exportar()

        self.assertEqual(bdb.corrida(self.con, self.previa)["estatus"], "ok")
        self.assertEqual(_unidades(self.con, self.previa), 1)
        self.assertEqual(
            bdb.corrida_previa(self.con, I.METODO, I.VERSION, None)["id"],
            self.previa, "el siguiente exportar tiene que ver la anterior")

    def test_si_la_nueva_falla_la_anterior_queda_intacta(self):
        with mock.patch.object(I, "identificar",
                               side_effect=RuntimeError("falla")):
            with self.assertRaises(RuntimeError):
                self._exportar()

        self.assertEqual(bdb.corrida(self.con, self._nueva())["estatus"],
                         "error")
        self.assertEqual(bdb.corrida(self.con, self.previa)["estatus"], "ok")
        self.assertEqual(_unidades(self.con, self.previa), 1)

    def test_si_el_volcado_falla_la_anterior_queda_intacta(self):
        """El borrado va después de `_volcar` y `cerrar_corrida`: si el
        volcado lanza, la nueva no terminó bien y la anterior sigue viva."""
        with mock.patch.object(I, "identificar",
                               return_value=collections.Counter()),                 mock.patch.object(cli, "_volcar",
                                  side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                self._exportar()

        self.assertNotEqual(bdb.corrida(self.con, self._nueva())["estatus"],
                            "ok")
        self.assertEqual(bdb.corrida(self.con, self.previa)["estatus"], "ok")
        self.assertEqual(_unidades(self.con, self.previa), 1)

    def test_si_fallan_documentos_la_anterior_se_conserva(self):
        """`identificar` atrapa el error de cada documento y sigue, así que
        la nueva cierra 'ok' aunque fallen todos. Borrar la anterior ahí
        cambiaba una corrida completa por una vacía."""
        with mock.patch.object(I, "procesar_documento",
                               side_effect=RuntimeError("recurso roto")),                 mock.patch.object(cli, "_volcar",
                                  return_value=(None, [], {}, False)),                 mock.patch.object(cli, "_mostrar"):
            self.assertEqual(self._exportar(), 0)

        self.assertEqual(bdb.corrida(self.con, self._nueva())["estatus"],
                         "ok")
        self.assertEqual(bdb.corrida(self.con, self.previa)["estatus"], "ok")
        self.assertEqual(_unidades(self.con, self.previa), 1)

    def test_la_primera_limpia_borra_todas_las_conservadas(self):
        """Un documento que falla en cada `--rehacer` conserva una copia
        entera del corpus por intento. La primera que termina limpia las
        borra todas, no solo la inmediata anterior."""
        with mock.patch.object(I, "procesar_documento",
                               side_effect=RuntimeError("recurso roto")), \
                mock.patch.object(cli, "_volcar",
                                  return_value=(None, [], {}, False)), \
                mock.patch.object(cli, "_mostrar"):
            self._exportar()
        con_errores = self._nueva()
        with mock.patch.object(I, "identificar",
                               return_value=collections.Counter()), \
                mock.patch.object(cli, "_volcar",
                                  return_value=(None, [], {}, False)), \
                mock.patch.object(cli, "_mostrar"):
            self._exportar()

        limpia = self._nueva()
        self.assertEqual(
            {f["id"]: f["estatus"] for f in bdb.listar_corridas(self.con)},
            {self.previa: "rehecha", con_errores: "rehecha", limpia: "ok"})
        self.assertEqual(_unidades(self.con, self.previa), 0)

    def test_si_la_nueva_termina_la_anterior_se_borra(self):
        with mock.patch.object(I, "identificar",
                               return_value=collections.Counter()), \
                mock.patch.object(cli, "_volcar",
                                  return_value=(None, [], {}, False)), \
                mock.patch.object(cli, "_mostrar"):
            self.assertEqual(self._exportar(), 0)

        nueva = self._nueva()
        self.assertNotEqual(nueva, self.previa)
        self.assertEqual(bdb.corrida(self.con, nueva)["estatus"], "ok")
        self.assertEqual(bdb.corrida(self.con, self.previa)["estatus"],
                         "rehecha")
        self.assertEqual(_unidades(self.con, self.previa), 0)


if __name__ == "__main__":
    unittest.main()
