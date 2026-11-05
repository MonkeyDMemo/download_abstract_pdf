# -*- coding: utf-8 -*-
"""La validación contra el XML, con textos inventados y un diccionario de
juguete (sin cargar el de PAO1).

    python -m unittest grn_pdf.test_validar
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import texto as T          # noqa: E402
from grn_pdf import validar as V           # noqa: E402


class Lex(object):
    """Reconoce `lasR`, `rhlR`, `mexT` y `mexE`, como lo haría `Lexico`."""

    GENES = ("lasR", "rhlR", "mexT", "mexE")

    def menciones(self, oracion):
        salida = []
        for g in self.GENES:
            for m in re.finditer(r"\b%s\b" % g, oracion, re.IGNORECASE):
                salida.append((m.start(), m.end(), m.group(0), g, True))
        return salida


XML = """# Title

## ABSTRACT

LasR activates rhlR expression in the invented abstract of this test.

## RESULTS

The first result says that MexT binds the mexE promoter in vitro.

The second result shows that rhlR transcription requires LasR in the strain.

A sentence without any gene that is long enough to be examined.

## MATERIALS AND METHODS

The strains carrying lasR and rhlR were grown as described before.
"""


class PruebasComparar(unittest.TestCase):

    def setUp(self):
        self.clases = T.cargar_clases()
        self.lex = Lex()

    def test_identicos(self):
        r = V.comparar(XML, XML, self.clases, self.lex)
        self.assertEqual(r["oraciones_xml"], 4)    # métodos fuera
        self.assertEqual(r["candidatas_xml"], 3)
        self.assertEqual((r["frac_recuperadas"], r["frac_ruido"]), (1.0, 0.0))
        self.assertEqual((r["frac_candidatas_recuperadas"],
                          r["frac_candidatas_ruido"]), (1.0, 0.0))

    def test_cortes_de_renglon_y_puntuacion_no_cuentan(self):
        pdf = (XML.replace("transcription requires", "tran- scription  requires")
               .replace("in vitro.", "in vitro ."))
        r = V.comparar(XML, pdf, self.clases, self.lex)
        self.assertEqual(r["frac_candidatas_recuperadas"], 1.0)

    def test_parecido_con_ratio(self):
        pdf = XML.replace("The first result says", "The 1st result says")
        r = V.comparar(XML, pdf, self.clases, self.lex)
        self.assertEqual(r["frac_candidatas_recuperadas"], 1.0)

    def test_perdida_ruido_y_seccion_excluida(self):
        pdf = (XML.replace("The second result shows that rhlR transcription "
                           "requires LasR in the strain.", "")
               .replace("## RESULTS", "## RESULTS\n\nRunning head lasR rhlR "
                        "mexT Journal of Synthetic Tests volume one."))
        r = V.comparar(XML, pdf, self.clases, self.lex)
        self.assertEqual(r["candidatas_recuperadas"], 2)
        self.assertAlmostEqual(r["frac_candidatas_recuperadas"], 0.6667)
        self.assertEqual(r["candidatas_ruido"], 1)
        # Lo que el PDF deja en una sección excluida no está «recuperado».
        pdf = XML.replace("## RESULTS", "## REFERENCES")
        r = V.comparar(XML, pdf, self.clases, self.lex)
        self.assertAlmostEqual(r["frac_candidatas_recuperadas"], 0.3333)

    def test_percentiles(self):
        self.assertEqual(V.percentil([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(V.percentil([0.5], 0.25), 0.5)
        self.assertIsNone(V.percentil([], 0.5))


class PruebasInforme(unittest.TestCase):

    def test_solo_pmid_y_cifras(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        xml, pdf = os.path.join(d, "xml"), os.path.join(d, "pdf_txt")
        os.makedirs(xml)
        os.makedirs(pdf)
        for pmid in ("11", "22"):
            with open(os.path.join(xml, "%s_PMC9%s.txt" % (pmid, pmid)), "w",
                      encoding="utf-8") as f:
                f.write(XML)
            with open(os.path.join(pdf, pmid + ".txt"), "w",
                      encoding="utf-8") as f:
                f.write(XML)
        # Uno sin PDF: no entra.
        with open(os.path.join(xml, "33_PMC933.txt"), "w", encoding="utf-8") as f:
            f.write(XML)
        informe = V.validar(xml, pdf, lex=Lex())
        self.assertEqual(informe["articulos"], 2)
        self.assertEqual(informe["por_articulo"]["frac_candidatas_recuperadas"][
            "mediana"], 1.0)
        texto = repr(informe)
        self.assertNotIn("invented", texto)
        self.assertNotIn("promoter", texto)


if __name__ == "__main__":
    unittest.main()
