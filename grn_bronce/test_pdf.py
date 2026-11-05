# -*- coding: utf-8 -*-
"""El texto de los PDF en el bronce: solo sin XML, nunca los dos, y opt-in.

Lo que se vigila:

- un documento con XML `ok` se lee del XML aunque tenga `.txt` de PDF, y sus
  filas son las mismas con y sin `--con-pdf`;
- uno sin XML pero con PDF `ok` y `.txt` convertido se lee del PDF, con
  `fuente_texto` 'pdf';
- sin `--con-pdf` todo es como antes: el mismo método, los mismos
  parámetros sellados, la misma hoja resumen;
- con `--con-pdf` la corrida es otro método, así que no empata con las de
  solo XML ni las borra con `--rehacer`.

Biblioteca estándar, base en memoria y archivos temporales; los textos son
inventados.

    python -m unittest grn_bronce.test_pdf
"""

import argparse
import collections
import io
import json
import os
import re
import shutil
import sys
import tempfile
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

XML = """# Un titulo

## ABSTRACT

LasR activates rhlR expression in this invented abstract text.

## RESULTS

MexT binds the mexE promoter, as this invented result says.
"""

PDF = """# Un titulo

## ABSTRACT

LasR activates rhlR expression in the abstract of the converted PDF.

## RESULTS

The converted PDF says that MexT represses the mexE promoter here.

## REFERENCES

1. Smith AB. LasR and rhlR in an invented reference. 2001.
"""


class Lex(object):
    """`lasR`, `rhlR`, `mexT`, `mexE`, como los devolvería `Lexico`."""

    def __len__(self):
        return 4

    def menciones(self, oracion):
        salida = []
        for g in ("lasR", "rhlR", "mexT", "mexE"):
            for m in re.finditer(r"\b%s\b" % g, oracion, re.IGNORECASE):
                salida.append((m.start(), m.end(), m.group(0), g,
                               g in ("lasR", "mexT")))
        return sorted(salida)

    def es_operon(self, _idc):
        return False


class Vocab(object):
    disparadores = funciones = evidencia = contexto = [1]

    def disparadores_en(self, oracion):
        return [(m.start(), m.end(), m.group(0), "+")
                for m in re.finditer(r"activates", oracion)]

    def funciones_en(self, _o):
        return []

    evidencia_en = contexto_en = funciones_en


def _base(carpeta):
    """Tres documentos: 1 con XML y PDF, 2 solo con PDF, 3 solo resumen."""
    con = bdb.conectar(":memory:")
    for pmid in ("1", "2", "3"):
        con.execute(
            """INSERT INTO documentos (pmid, titulo, anio, extraido_en,
                                       abstract, tiene_abstract)
               VALUES (?, 'Un titulo', '2020', ?, ?, 1)""",
            (pmid, bdb.ahora(),
             "LasR activates rhlR expression in the database abstract."))
    xml = os.path.join(carpeta, "1_PMC1.txt")
    for ruta, texto in ((xml, XML), (os.path.join(carpeta, "1.txt"), PDF),
                        (os.path.join(carpeta, "2.txt"), PDF)):
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
    db0.registrar_descarga(con, "1", "xml", "ok", ruta=xml)
    db0.registrar_descarga(con, "1", "pdf", "ok", ruta="1.pdf")
    db0.registrar_descarga(con, "2", "pdf", "ok", ruta="2.pdf")
    db0.registrar_descarga(con, "3", "pdf", "no_disponible")
    return con


def _filas(con, corrida, pmid):
    return [tuple(f) for f in con.execute(
        """SELECT fuente_texto, seccion, num_oracion, texto, offset_ini,
                  offset_fin FROM texto_unidades
            WHERE corrida_id = ? AND pmid = ? ORDER BY num_oracion""",
        (corrida, pmid))]


class PruebasTextosDePdf(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_solo_sin_xml_con_pdf_ok_y_txt(self):
        for p in ("1", "2", "4"):
            open(os.path.join(self.dir, p + ".txt"), "w").close()
        textos = I.textos_de_pdf(
            {"1": "x", "2": "x", "3": "x", "../9": "x"}, self.dir,
            {"1": "xml"})
        # 1 tiene XML; 3 no tiene .txt; 4 tiene .txt pero su PDF no está ok;
        # «../9» no es un PMID.
        self.assertEqual(sorted(textos), ["2"])
        self.assertEqual(textos["2"], os.path.join(self.dir, "2.txt"))

    def test_sello_cambia_con_el_texto(self):
        ruta = os.path.join(self.dir, "2.txt")
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(PDF)
        a = I.sello_textos_pdf({"2": ruta})
        self.assertEqual(a["documentos"], 1)
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(PDF + "\nOtro parrafo.\n")
        self.assertNotEqual(I.sello_textos_pdf({"2": ruta})["huella"],
                            a["huella"])
        self.assertEqual(I.sello_textos_pdf({})["documentos"], 0)


class PruebasIdentificar(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.con = _base(self.dir)
        self.addCleanup(self.con.close)
        self.docs = bdb.documentos_del_corpus(self.con, None)
        self.xml = bdb.fulltext_disponible(self.con, "xml")
        self.textos = I.textos_de_pdf(bdb.fulltext_disponible(self.con, "pdf"),
                                      self.dir, self.xml)

    def _correr(self, metodo, pdf_txt):
        cid = bdb.abrir_corrida(self.con, "1", metodo, I.VERSION)
        cuenta = I.identificar(self.con, cid, self.docs, self.xml, Lex(),
                               Vocab(), {}, pdf_txt=pdf_txt)
        return cid, cuenta

    def test_el_pdf_solo_entra_sin_xml(self):
        cid, cuenta = self._correr(I.METODO_CON_PDF, self.textos)
        fuentes = dict((p, set(f[0] for f in _filas(self.con, cid, p)))
                       for p in ("1", "2", "3"))
        self.assertEqual(fuentes, {"1": {"xml"}, "2": {"pdf"},
                                   "3": {"abstract"}})
        self.assertEqual(cuenta["documentos_con_texto_pdf"], 1)
        self.assertEqual(cuenta["documentos_con_fulltext"], 1)
        # El resumen del PDF reemplaza al de la base, como el del XML; y la
        # bibliografía del PDF queda excluida.
        textos_2 = [f[3] for f in _filas(self.con, cid, "2")]
        self.assertNotIn("database abstract", " ".join(textos_2))
        secciones_2 = dict((f[3], f[1]) for f in _filas(self.con, cid, "2"))
        self.assertTrue(any(s == "excluir" for s in secciones_2.values()))
        candidatas = [f[0] for f in self.con.execute(
            """SELECT u.texto FROM oraciones_candidatas c
                 JOIN texto_unidades u ON u.id = c.unidad_id
                WHERE c.corrida_id = ? AND u.pmid = '2'""", (cid,))]
        self.assertFalse(any("reference" in t for t in candidatas))

    def test_con_xml_las_filas_no_cambian(self):
        sin, _ = self._correr(I.METODO, None)
        con, _ = self._correr(I.METODO_CON_PDF, self.textos)
        self.assertEqual(_filas(self.con, sin, "1"), _filas(self.con, con, "1"))
        self.assertEqual(_filas(self.con, sin, "3"), _filas(self.con, con, "3"))
        # Sin PDF, el documento 2 es solo su resumen de la base.
        self.assertEqual(set(f[0] for f in _filas(self.con, sin, "2")),
                         {"abstract"})

    def test_piezas_con_fuente_pdf(self):
        fila = {"abstract": "LasR activates rhlR expression."}
        piezas = I.piezas_de_documento(fila, self.textos["2"],
                                       {"abstract": "abstract",
                                        "results": "results",
                                        "references": "excluir"}, "pdf")
        self.assertEqual([(p[0], p[1]) for p in piezas],
                         [("pdf", "otra"), ("pdf", "abstract"),
                          ("pdf", "results"), ("pdf", "excluir")])
        # Por omisión, la de siempre.
        piezas = I.piezas_de_documento(fila, self.textos["2"], {})
        self.assertEqual(set(p[0] for p in piezas), {"xml", "abstract"})


class PruebasExportar(unittest.TestCase):
    """Lo que `exportar` decide: método, parámetros y qué corridas toca. Lo
    caro (diccionario, vocabularios, volcado) se sustituye, como en
    `test_corridas.py`."""

    PARAMETROS_DE_SIEMPRE = {"corpus", "min_oracion", "max_oracion",
                             "max_menciones", "fuentes", "pdf", "ocr", "datos",
                             "recursos", "secciones_fuera",
                             "etiquetas_excluidas"}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.con = _base(self.dir)
        self.addCleanup(self.con.close)
        vocab = types.SimpleNamespace(disparadores=[1], funciones=[1],
                                      evidencia=[1], contexto=[1])
        self.llamadas = []

        def identificar(con, cid, docs, xml, lex, voc, locus, log,
                        pdf_txt=None):
            self.llamadas.append(pdf_txt)
            return collections.Counter()

        for objeto, nombre, valor in (
                (cli, "log", lambda m: None),
                (I, "cargar_lexico", lambda: {}),
                (I, "cargar_locus_tags", lambda: {}),
                (V.Vocabulario, "cargar", lambda: vocab),
                (I, "identificar", identificar),
                (cli, "_volcar", lambda *a, **k: (None, [], {}, False)),
                (cli, "_mostrar", lambda *a, **k: None)):
            p = mock.patch.object(objeto, nombre, valor)
            p.start()
            self.addCleanup(p.stop)

    def _exportar(self, con_pdf, rehacer=False):
        args = argparse.Namespace(corrida=None, corpus="", rehacer=rehacer,
                                  datos=None)
        if con_pdf:
            args.con_pdf, args.pdf_txt = True, self.dir
        return cli._exportar(self.con, args, 0)

    def _ultima(self):
        return bdb.listar_corridas(self.con)[0]

    def test_por_omision_es_lo_de_siempre(self):
        self.assertEqual(self._exportar(False), 0)
        fila = self._ultima()
        self.assertEqual(fila["metodo"], I.METODO)
        parametros = json.loads(fila["parametros"])
        self.assertEqual(set(parametros), self.PARAMETROS_DE_SIEMPRE)
        self.assertEqual((parametros["fuentes"], parametros["pdf"]),
                         ("abstract+xml", False))
        self.assertEqual(self.llamadas, [None])

    def test_con_pdf_es_otra_corrida_y_sella_los_textos(self):
        self._exportar(False)
        xml_sola = self._ultima()["id"]
        self.assertEqual(self._exportar(True), 0)
        fila = self._ultima()
        self.assertNotEqual(fila["id"], xml_sola, "no empató con la de XML")
        self.assertEqual(fila["metodo"], I.METODO_CON_PDF)
        parametros = json.loads(fila["parametros"])
        self.assertEqual((parametros["fuentes"], parametros["pdf"]),
                         ("abstract+xml+pdf", True))
        self.assertEqual(parametros["pdf_txt"]["documentos"], 1)
        self.assertEqual(sorted(self.llamadas[-1]), ["2"])
        # La segunda vez ya está hecha: idempotente por su propia clave.
        n = len(bdb.listar_corridas(self.con))
        self._exportar(True)
        self.assertEqual(len(bdb.listar_corridas(self.con)), n)

    def test_rehacer_con_pdf_no_borra_la_de_solo_xml(self):
        self._exportar(False)
        xml_sola = self._ultima()["id"]
        self._exportar(True)
        self._exportar(True, rehacer=True)
        self.assertEqual(bdb.corrida(self.con, xml_sola)["estatus"], "ok")

    def test_carpeta_por_omision_bajo_datos(self):
        datos = os.path.join(self.dir, "datos")
        carpeta = os.path.join(datos, I.CARPETA_PDF_TXT)
        os.makedirs(carpeta)
        shutil.copy(os.path.join(self.dir, "2.txt"), carpeta)
        args = argparse.Namespace(corrida=None, corpus="", rehacer=False,
                                  datos=datos, con_pdf=True, pdf_txt=None)
        self.assertEqual(cli._exportar(self.con, args, 0), 0)
        self.assertEqual(self.llamadas[-1],
                         {"2": os.path.join(carpeta, "2.txt")})


class PruebasResumen(unittest.TestCase):

    def _resumen(self, parametros, documentos_con_pdf):
        con = bdb.conectar(":memory:")
        self.addCleanup(con.close)
        cid = bdb.abrir_corrida(con, "1", I.METODO, I.VERSION, parametros)
        fila = bdb.corrida(con, cid)
        c = collections.defaultdict(int, por_tipo={},
                                    documentos=10, documentos_con_fulltext=4,
                                    documentos_con_pdf=documentos_con_pdf)
        return dict(cli._armar_resumen(c, None, "c", fila, None, []))

    def test_sin_pdf_la_hoja_no_cambia(self):
        r = self._resumen({"pdf": False}, 0)
        self.assertNotIn("Documentos con texto del PDF (sin XML; fuente_texto "
                         "pdf)", r)
        self.assertEqual(r["Documentos solo con resumen"], 6)
        self.assertEqual(r["PDF"], "fuera de esta corrida; queda para "
                                   "despues, con PyMuPDF")

    def test_con_pdf_dice_cuantos(self):
        r = self._resumen({"pdf": True, "pdf_txt": {"documentos": 3,
                                                    "huella": "abc"}}, 3)
        self.assertEqual(r["Documentos con texto del PDF (sin XML; "
                           "fuente_texto pdf)"], 3)
        self.assertEqual(r["Documentos solo con resumen"], 3)
        self.assertIn("abc", r["PDF"])


if __name__ == "__main__":
    unittest.main()
