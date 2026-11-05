# -*- coding: utf-8 -*-
"""La conversión de punta a punta con un PDF sintético hecho con PyMuPDF.

Se saltan donde PyMuPDF no está (el `.venv` del proyecto, el Python del
sistema), como las de spaCy; corren en `.venv-pdf`:

    .venv-pdf/Scripts/python -m unittest grn_pdf.test_conversor

El PDF se genera en la prueba, con texto inventado: dos páginas, cabeza
corrida y número de página, resumen, dos columnas, una palabra partida por
guion, un pie de figura y la bibliografía.
"""

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import texto as T          # noqa: E402
from grn_pdf import convertir as C         # noqa: E402

HAY_PYMUPDF = importlib.util.find_spec("pymupdf") is not None


def escribir_pdf(ruta, variante=""):
    """Un artículo de dos páginas a dos columnas, todo inventado."""
    import pymupdf
    doc = pymupdf.open()
    for n in range(2):
        p = doc.new_page(width=600, height=800)
        p.insert_text((50, 30), "Synthetic Journal of Tests", fontsize=8)
        p.insert_text((300, 785), str(n + 1), fontsize=8)
        if n == 0:
            p.insert_text((50, 70), "A Synthetic Title About LasR" + variante,
                          fontsize=18, fontname="hebo")
            p.insert_text((50, 110), "Abstract", fontsize=11, fontname="hebo")
            for i, t in enumerate([
                    "LasR activates rhlR in this invented abstract. It has",
                    "a second sentence. And a third one closes it."]):
                p.insert_text((50, 130 + 12 * i), t, fontsize=10)
            p.insert_text((50, 200), "Introduction", fontsize=11,
                          fontname="hebo")
            for i, t in enumerate([
                    "The left column comes first and talks",
                    "about the argi-",
                    "nine pathway of the strain."]):
                p.insert_text((50, 220 + 12 * i), t, fontsize=10)
            p.insert_text((320, 200), "Results", fontsize=11, fontname="hebo")
            for i, t in enumerate([
                    "The right column comes second. MexT",
                    "binds the mexE promoter here."]):
                p.insert_text((320, 220 + 12 * i), t, fontsize=10)
            p.insert_text((320, 400), "Figure 1. A made up figure legend.",
                          fontsize=8)
        else:
            p.insert_text((50, 100), "The results end on the second page.",
                          fontsize=10)
            p.insert_text((50, 200), "References", fontsize=11,
                          fontname="hebo")
            p.insert_text((50, 220), "1. Smith AB. LasR and rhlR. J Bact 2001.",
                          fontsize=8)
    doc.save(ruta)
    doc.close()


@unittest.skipUnless(HAY_PYMUPDF, "PyMuPDF no está: corre con .venv-pdf")
class PruebasConvertir(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.entrada = os.path.join(self.dir, "pdf")
        self.salida = os.path.join(self.dir, "pdf_txt")
        os.makedirs(self.entrada)
        escribir_pdf(os.path.join(self.entrada, "123.pdf"))

    def _texto(self):
        with io.open(os.path.join(self.salida, "123.txt"), encoding="utf-8") as f:
            return f.read()

    def _registro(self):
        with io.open(os.path.join(self.salida, C.NOMBRE_REGISTRO),
                     encoding="utf-8") as f:
            return json.load(f)

    def test_el_texto_sale_en_el_formato_del_xml(self):
        cuenta = C.convertir_carpeta(self.entrada, self.salida)
        self.assertEqual((cuenta["convertidos"], cuenta["errores"]), (1, 0))
        md = self._texto()
        self.assertTrue(md.startswith("# A Synthetic Title About LasR\n"))
        clases = T.cargar_clases()
        etiquetas = [e for e, _c in T.bloques(md) if e]
        self.assertEqual(etiquetas, ["abstract", "introduction", "results",
                                     "references", "pies de figura y tabla"])
        self.assertEqual(clases["references"], "excluir")
        self.assertLess(md.index("left column comes first"),
                        md.index("right column comes second"))
        self.assertIn("about the arginine pathway", md)
        self.assertNotIn("Synthetic Journal of Tests", md)
        self.assertIn("Figure 1. A made up figure legend.",
                      md.split("## PIES DE FIGURA Y TABLA")[1])

    def test_registro(self):
        C.convertir_carpeta(self.entrada, self.salida)
        ficha = self._registro()["documentos"]["123"]
        self.assertEqual(ficha["estatus"], "ok")
        self.assertEqual(ficha["paginas"], 2)
        self.assertEqual(ficha["caracteres"], len(self._texto()))
        self.assertEqual(ficha["huella_pdf"], C.huella_bytes(
            os.path.join(self.entrada, "123.pdf")))
        self.assertIn("REFERENCES", ficha["secciones"])

    def test_idempotente(self):
        C.convertir_carpeta(self.entrada, self.salida)
        ruta = os.path.join(self.salida, "123.txt")
        antes = os.stat(ruta).st_mtime_ns
        cuenta = C.convertir_carpeta(self.entrada, self.salida)
        self.assertEqual((cuenta["convertidos"], cuenta["al_dia"]), (0, 1))
        self.assertEqual(os.stat(ruta).st_mtime_ns, antes)

    def test_rehace_si_cambia_el_pdf_o_falta_el_texto(self):
        C.convertir_carpeta(self.entrada, self.salida)
        escribir_pdf(os.path.join(self.entrada, "123.pdf"), " Again")
        self.assertEqual(C.convertir_carpeta(self.entrada, self.salida)[
            "convertidos"], 1)
        self.assertIn("About LasR Again", self._texto())
        os.remove(os.path.join(self.salida, "123.txt"))
        self.assertEqual(C.convertir_carpeta(self.entrada, self.salida)[
            "convertidos"], 1)

    def test_un_pdf_roto_queda_en_error_y_se_reintenta(self):
        with open(os.path.join(self.entrada, "999.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 cortado a media descarga")
        cuenta = C.convertir_carpeta(self.entrada, self.salida)
        self.assertEqual((cuenta["convertidos"], cuenta["errores"]), (1, 1))
        self.assertEqual(self._registro()["documentos"]["999"]["estatus"],
                         "error")
        self.assertFalse(os.path.exists(os.path.join(self.salida, "999.txt")))
        cuenta = C.convertir_carpeta(self.entrada, self.salida)
        self.assertEqual((cuenta["al_dia"], cuenta["errores"]), (1, 1))


class PruebasSinPyMuPDF(unittest.TestCase):
    """Lo que no necesita PyMuPDF: qué archivos cuentan y cuándo está al día."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_solo_pmid_punto_pdf(self):
        for nombre in ("123.pdf", "45.PDF", "abc.pdf", "123_PMC1.pdf", "9.txt"):
            open(os.path.join(self.dir, nombre), "wb").close()
        self.assertEqual(sorted(C.pdfs_de(self.dir)), ["123", "45"])

    def test_al_dia_mira_version_huellas_y_texto(self):
        pdf = os.path.join(self.dir, "1.pdf")
        txt = os.path.join(self.dir, "1.txt")
        with open(pdf, "wb") as f:
            f.write(b"%PDF uno")
        C.escribir_texto(txt, "# t\n")
        from grn_pdf import maquetar
        ficha = {"estatus": "ok", "version_maquetado": maquetar.VERSION,
                 "pymupdf": "1.0", "huella_pdf": C.huella_bytes(pdf),
                 "huella_txt": C.huella_texto("# t\n")}
        self.assertTrue(C.al_dia(ficha, pdf, txt, "1.0"))
        self.assertFalse(C.al_dia(ficha, pdf, txt, "2.0"))
        self.assertFalse(C.al_dia(dict(ficha, version_maquetado="0"), pdf,
                                  txt, "1.0"))
        self.assertFalse(C.al_dia(dict(ficha, estatus="error"), pdf, txt,
                                  "1.0"))
        C.escribir_texto(txt, "# editado a mano\n")
        self.assertFalse(C.al_dia(ficha, pdf, txt, "1.0"))

    def test_registro_ilegible_se_aparta(self):
        with open(os.path.join(self.dir, C.NOMBRE_REGISTRO), "w") as f:
            f.write("{no es json")
        self.assertEqual(C.leer_registro(self.dir), {"documentos": {}})
        self.assertTrue(os.path.exists(os.path.join(
            self.dir, C.NOMBRE_REGISTRO + ".ilegible")))


class PruebasFrontera(unittest.TestCase):
    """Lo que mantiene a PyMuPDF dentro de su entorno."""

    def test_la_version_fija_es_la_misma_en_los_dos_lados(self):
        with io.open(os.path.join(_RAIZ, "grn_pdf", "requisitos.txt"),
                     encoding="utf-8") as f:
            requisito = [l.strip() for l in f
                         if l.strip() and not l.startswith("#")]
        with io.open(os.path.join(_RAIZ, "pyproject.toml"),
                     encoding="utf-8") as f:
            extra = re.search(r'(?m)^pdf = \["([^"]+)"\]', f.read())
        self.assertIsNotNone(extra, "falta el extra [pdf] en pyproject.toml")
        self.assertEqual(requisito, [extra.group(1)])

    def test_solo_extraer_importa_pymupdf_y_todo_parsea_en_38(self):
        """El núcleo es 3.8 y estándar: PyMuPDF solo dentro de las funciones
        de `extraer.py`, y nadie fuera del paquete importa `grn_pdf`."""
        import ast
        carpeta = os.path.join(_RAIZ, "grn_pdf")
        for nombre in sorted(os.listdir(carpeta)):
            if not nombre.endswith(".py"):
                continue
            with io.open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
                arbol = ast.parse(f.read(), nombre, feature_version=(3, 8))
            for nodo in arbol.body:
                if isinstance(nodo, (ast.Import, ast.ImportFrom)):
                    modulos = ([a.name for a in nodo.names]
                               if isinstance(nodo, ast.Import)
                               else [nodo.module or ""])
                    for m in modulos:
                        self.assertFalse(m.split(".")[0] in ("pymupdf", "fitz"),
                                         "%s importa %s arriba" % (nombre, m))
        for paquete in ("grn_bronce", "grn_etl", "grn_comun"):
            raiz = os.path.join(_RAIZ, paquete)
            for nombre in os.listdir(raiz):
                if nombre.endswith(".py"):
                    with io.open(os.path.join(raiz, nombre),
                                 encoding="utf-8") as f:
                        self.assertNotRegex(
                            f.read(), r"(?m)^\s*(from|import) grn_pdf\b",
                            "%s/%s importa grn_pdf" % (paquete, nombre))


if __name__ == "__main__":
    unittest.main()
