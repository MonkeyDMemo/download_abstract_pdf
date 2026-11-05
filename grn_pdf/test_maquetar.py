# -*- coding: utf-8 -*-
"""El maquetado de `grn_pdf`, con páginas sintéticas y sin PyMuPDF.

Las páginas son las estructuras que entrega `extraer.leer_paginas`, armadas a
mano: así se fija cada decisión (orden de lectura, guiones, cabezas de
página, encabezados, pies, tablas) sin depender de cómo componga un PDF una
versión de PyMuPDF. El contacto con PyMuPDF está en `test_conversor.py`.

Todo el texto es inventado; nada sale del corpus.

    python -m unittest grn_pdf.test_maquetar
"""

import os
import sys
import textwrap
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import texto as T          # noqa: E402
from grn_pdf import maquetar as M          # noqa: E402

ANCHO, ALTO = 600.0, 800.0


def span(texto, x0, base, tam=10.0, negrita=False, fuente="Times-Roman",
         cursiva=False):
    return {"texto": texto, "tam": tam, "negrita": negrita, "cursiva": cursiva,
            "sup": False, "fuente": fuente, "x0": x0,
            "x1": x0 + 0.5 * tam * len(texto), "base": base}


def linea(texto, x0, y0, tam=10.0, negrita=False, ancho=None, spans=None,
          fuente="Times-Roman"):
    """Un renglón de un solo tramo (o con los `spans` dados)."""
    spans = spans or [span(texto, x0, y0 + 0.8 * tam, tam, negrita, fuente)]
    x1 = x0 + (ancho if ancho is not None else 0.5 * tam * len(texto))
    return {"bbox": (x0, y0, x1, y0 + 1.2 * tam), "spans": spans}


def bloque(lineas):
    return {"bbox": (min(l["bbox"][0] for l in lineas),
                     min(l["bbox"][1] for l in lineas),
                     max(l["bbox"][2] for l in lineas),
                     max(l["bbox"][3] for l in lineas)),
            "lineas": lineas}


def parrafo(textos, x0, y0, tam=10.0, ancho=240.0, negrita=False):
    """Un bloque de renglones apilados, todos del ancho de la columna."""
    return bloque([linea(t, x0, y0 + 12.0 * i, tam, negrita, ancho)
                   for i, t in enumerate(textos)])


def pagina(numero, bloques):
    return {"numero": numero, "ancho": ANCHO, "alto": ALTO, "x0": 0.0,
            "y0": 0.0, "bloques": bloques}


def cabeza_y_pie(numero):
    """La cabeza corrida y el número de página de cada página."""
    return [bloque([linea("Running Head Journal Name", 50, 20, 8)]),
            bloque([linea(str(numero + 1), 300, 770, 8)])]


def secciones_de(md):
    """[(etiqueta normalizada, clase)] como las ve el bronce."""
    clases = T.cargar_clases()
    return [(e, clases.get(e, T.CLASE_DESCONOCIDA))
            for e, _c in T.bloques(md) if e]


class PruebasNormalizacion(unittest.TestCase):

    def test_ligaduras_y_guiones_de_compatibilidad(self):
        self.assertEqual(M.normalizar("speci\ufb01c \ufb02ow"), "specific flow")
        self.assertEqual(M.normalizar("mexEF\u2010oprN"), "mexEF-oprN")
        self.assertEqual(M.normalizar("a\u00a0b\x02c"), "a b c")

    def test_cita_volada_fuera_e_indice_griego_dentro(self):
        spans = [span("LasR", 50, 100), span("12,13", 70, 96, tam=6.0),
                 span(" activates rhlR", 80, 100)]
        texto, _tam, _neg, _cur = M.texto_de_linea(spans)
        self.assertEqual(" ".join(texto.split()), "LasR activates rhlR")
        spans = [span("s", 50, 100, fuente="Universal-GreekwithMathPi"),
                 span("54", 56, 96, tam=6.0), span(" and ", 66, 100),
                 span("D", 90, 100, fuente="Universal-GreekwithMathPi"),
                 span("lasR", 96, 100)]
        texto, _tam, _neg, _cur = M.texto_de_linea(spans)
        self.assertEqual(texto, "σ54 and ΔlasR")

    def test_guion_de_corte(self):
        vocab = {"arginine": 2}
        self.assertEqual(M.unir("of argi-", "nine", vocab), "of arginine")
        # Una mitad con mayúscula es nombre de gen u operón: el guion se queda.
        self.assertEqual(M.unir("the mexEF-", "oprN operon", {}),
                         "the mexEF-oprN operon")
        # El documento escribe la palabra con guion en otro lado.
        self.assertEqual(M.unir("a two-", "component system",
                                {"two-component": 3}),
                         "a two-component system")
        self.assertEqual(M.unir("sin", "corte", {}), "sin corte")


class PruebasEncabezados(unittest.TestCase):

    def test_claves_conocidas(self):
        self.assertEqual(M.etiqueta_conocida("2. Materials and Methods"),
                         "MATERIALS AND METHODS")
        self.assertEqual(M.etiqueta_conocida("R E S U L T S"), "RESULTS")
        self.assertEqual(M.etiqueta_conocida("Literature Cited"), "REFERENCES")
        self.assertEqual(M.etiqueta_conocida("Acknowledgements"),
                         "ACKNOWLEDGMENTS")
        self.assertIsNone(M.etiqueta_conocida("LasR regulates rhlR"))

    def test_toda_etiqueta_esta_en_secciones_tsv(self):
        """Un `##` que secciones.tsv no conoce sería clase 'otra' y entraría
        a las candidatas: las referencias y los agradecimientos tienen que
        ser 'excluir'."""
        clases = T.cargar_clases()
        faltan = [e for e in M.ETIQUETAS if T.normalizar_etiqueta(e)
                  not in clases]
        self.assertEqual(faltan, [])
        for e in ("REFERENCES", "ACKNOWLEDGMENTS", "MATERIALS AND METHODS",
                  "SUPPLEMENTARY MATERIAL", "FUNDING", "NOTES"):
            self.assertEqual(clases[T.normalizar_etiqueta(e)], "excluir", e)
        self.assertEqual(clases[T.normalizar_etiqueta(M.ETIQUETA_PIES)],
                         "pie_de_figura")


def _articulo():
    """Dos páginas a dos columnas, con resumen, cabezas, tabla y pie."""
    p0 = cabeza_y_pie(0) + [
        bloque([linea("A Synthetic Title About LasR", 50, 60, 18)]),
        bloque([linea("Ana Autora, Department of Biology, University", 50,
                      90, 9)]),
        bloque([linea("Abstract", 50, 120, 11, negrita=True)]),
        parrafo(["LasR activates rhlR in a synthetic world. This sentence",
                 "belongs to the abstract. It has three sentences."], 50, 140,
                ancho=500),
        # Columna izquierda.
        bloque([linea("Introduction", 50, 200, 11, negrita=True)]),
        parrafo(["The left column comes first. It talks about the argi-",
                 "nine pathway and the mexEF-",
                 "oprN operon of the synthetic strain."], 50, 220),
        # Columna derecha: va después de toda la izquierda.
        bloque([linea("Results", 320, 200, 11, negrita=True)]),
        parrafo(["The right column comes second. MexT binds the mexE",
                 "promoter in this invented text."], 320, 220),
        # Una fila de tabla: celdas separadas por un hueco ancho.
        bloque([linea("lasR", 320, 400, 8), linea("PA1430", 450, 400, 8)]),
        bloque([linea("rhlR", 320, 412, 8), linea("PA3477", 450, 412, 8)]),
        parrafo(["Figure 1. LasR and RhlR in a made up figure legend."], 320,
                450, tam=8),
    ]
    p1 = cabeza_y_pie(1) + [
        parrafo(["The results continue on the second page with the argi-",
                 "nine pathway again."], 50, 100),
        bloque([linea("Acknowledgments", 50, 200, 11, negrita=True)]),
        parrafo(["We thank LasR and RhlR for nothing."], 50, 220),
        bloque([linea("References", 50, 300, 11, negrita=True)]),
        parrafo(["1. Smith AB, Jones CD. LasR and rhlR. J Bacteriol 2001;",
                 "183:1-10."], 50, 320),
    ]
    return [pagina(0, p0), pagina(1, p1)]


class PruebasMaquetado(unittest.TestCase):

    def setUp(self):
        self.res = M.maquetar(_articulo())
        self.md = M.a_texto(self.res)

    def test_formato_de_jats_a_texto(self):
        self.assertTrue(self.md.startswith("# A Synthetic Title About LasR\n"))
        self.assertIn("\n\n\n## ABSTRACT\n\n", self.md)
        self.assertIn("\n\n\n## PIES DE FIGURA Y TABLA\n\n", self.md)
        # Un párrafo por línea: ningún renglón suelto del PDF.
        for parte in self.md.split("\n\n"):
            self.assertNotIn("\n", parte.strip("\n"))

    def test_secciones_y_clases(self):
        self.assertEqual(secciones_de(self.md), [
            ("abstract", "abstract"), ("introduction", "introduction"),
            ("results", "results"), ("acknowledgments", "excluir"),
            ("references", "excluir"),
            ("pies de figura y tabla", "pie_de_figura")])
        self.assertEqual(M.secciones_halladas(self.res), [
            "ABSTRACT", "INTRODUCTION", "RESULTS", "ACKNOWLEDGMENTS",
            "REFERENCES", "PIES DE FIGURA Y TABLA"])

    def test_orden_de_lectura_a_dos_columnas(self):
        self.assertLess(self.md.index("The left column comes first"),
                        self.md.index("The right column comes second"))

    def test_sin_cabezas_ni_numeros_de_pagina_ni_portada(self):
        self.assertNotIn("Running Head", self.md)
        self.assertNotIn("University", self.md)
        for parte in self.md.split("\n\n"):
            self.assertFalse(parte.strip().isdigit(), parte)

    def test_guiones_de_corte_resueltos(self):
        self.assertIn("the arginine pathway and the mexEF-oprN operon",
                      self.md)
        self.assertIn("second page with the arginine pathway", self.md)

    def test_tabla_fuera_y_pie_al_final(self):
        self.assertNotIn("PA1430", self.md)
        pies = self.md.split("## PIES DE FIGURA Y TABLA")[1]
        self.assertIn("Figure 1. LasR and RhlR in a made up figure legend.",
                      pies)
        self.assertEqual(self.md.count("made up figure legend"), 1)

    def test_las_referencias_quedan_excluidas(self):
        clases = T.cargar_clases()
        for etiqueta, cuerpo in T.bloques(self.md):
            if "Smith AB" in cuerpo or "for nothing" in cuerpo:
                self.assertEqual(clases.get(etiqueta), "excluir", etiqueta)

    def test_el_bronce_parte_las_oraciones(self):
        """El texto entra por el mismo camino del bronce y da oraciones
        enteras, sin el encabezado pegado."""
        oraciones = [o for _e, c in T.bloques(self.md) for o in T.oraciones(c)]
        self.assertIn("The left column comes first.", oraciones)
        self.assertNotIn("Results", " ".join(oraciones[:6]))


class PruebasPortada(unittest.TestCase):

    def test_resumen_e_introduccion_sin_etiqueta(self):
        """Como la ASM antes de 2014: el resumen en negrita a lo ancho y la
        introducción en dos columnas, ninguno rotulado."""
        prosa = ("This is an unlabeled synthetic abstract about LasR. It has "
                 "several sentences to look like prose. The style is bold and "
                 "wide. Nothing here comes from a real article, it is all "
                 "invented for the test. One more sentence closes it, and "
                 "this clause makes it long enough to count as prose.")
        intro = ("The introduction is not labeled either. It uses the body "
                 "font in a single column of the page. It still needs enough "
                 "words to be prose. This is the last sentence of it. And "
                 "this one is extra, written only to pass the length that "
                 "the converter asks of a paragraph.")
        p0 = [bloque([linea("A Title Big Enough For The Test", 50, 40, 18)]),
              parrafo(textwrap.wrap(prosa, 90), 50, 80, ancho=500,
                      negrita=True),
              parrafo(textwrap.wrap(intro, 45), 50, 200, ancho=240),
              bloque([linea("MATERIALS AND METHODS", 320, 200, 9,
                            negrita=True)]),
              parrafo(["Strains were grown in an invented medium."], 320,
                      220)]
        md = M.a_texto(M.maquetar([pagina(0, p0)]))
        self.assertEqual([e for e, _c in secciones_de(md)],
                         ["abstract", "introduction", "materials and methods"])
        self.assertIn("unlabeled synthetic abstract", md.split(
            "## INTRODUCTION")[0])
        self.assertIn("The introduction is not labeled", md.split(
            "## INTRODUCTION")[1])


class PruebasBibliografiaSinRotulo(unittest.TestCase):

    def test_entradas_sueltas_pasan_a_referencias(self):
        prosa = ["Prose paragraph number %d about LasR and rhlR." % i
                 for i in range(3)]
        entradas = ["%d. Jacob F, Monod J (19%02d) LasR and rhlR in title %d. "
                    "J Mol Biol 3:318-356" % (i, 60 + i, i)
                    for i in range(1, 9)]
        cuenta = M.collections.Counter()
        salida = M._separar_lista_de_referencias(
            [("INTRODUCTION", prosa + entradas)], cuenta)
        self.assertEqual(salida, [("INTRODUCTION", prosa),
                                  ("REFERENCES", entradas)])
        self.assertEqual(cuenta["bibliografia_por_entradas"], 1)

    def test_una_lista_numerada_corta_no_es_bibliografia(self):
        pasos = ["%d. Step %d was done in 2001 with LasR." % (i, i)
                 for i in range(1, 5)]
        salida = M._separar_lista_de_referencias(
            [("RESULTS", ["Intro."] + pasos + ["Closing prose."])],
            M.collections.Counter())
        self.assertEqual([e for e, _t in salida], ["RESULTS"])


if __name__ == "__main__":
    unittest.main()
