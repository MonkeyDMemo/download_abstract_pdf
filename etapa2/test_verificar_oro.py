# -*- coding: utf-8 -*-
"""Pruebas de verificar_oro.py.

Lo que hay que proteger es la normalizacion: si se relaja de mas, dejaria pasar
oraciones que no son las del corpus, y la verificacion perderia sentido. Cada
caso de abajo salio de una fila real del patron de oro que fallaba antes.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verificar_oro as V


class PruebasNormalizar(unittest.TestCase):
    """Las tres diferencias de codificacion que se midieron en el corpus."""

    def test_la_sigma_griega_se_translitera(self):
        # El oro escribe "sigmaE"; el articulo trae la sigma griega.
        self.assertEqual(V.normalizar("AlgU (sigmaE, sigma22)"),
                         V.normalizar("AlgU (σE, σ22)"))

    def test_el_guion_tipografico_equivale_al_ascii(self):
        # Las revistas usan U+2010 dentro de 3OC12-HSL.
        self.assertEqual(V.normalizar("3OC12-HSL"),
                         V.normalizar("3OC12‐HSL"))

    def test_se_suelta_el_error_de_la_media(self):
        # El oro conserva "0.46" donde el articulo dice "0.46 +/- 0.006".
        self.assertEqual(V.normalizar("RQ 0.46, p 0.002"),
                         V.normalizar("RQ 0.46±0.006, p 0.002"))

    def test_los_espacios_se_colapsan(self):
        self.assertEqual(V.normalizar("MexT   activates\n\n mexEF"),
                         "mext activates mexef")

    def test_no_confunde_dos_oraciones_distintas(self):
        """La normalizacion no puede ser tan laxa que iguale contenidos."""
        self.assertNotEqual(V.normalizar("MexT activates mexEF-oprN"),
                            V.normalizar("MexT represses mexEF-oprN"))
        self.assertNotEqual(V.normalizar("AlgU regulates algD"),
                            V.normalizar("AlgU regulates algR"))


class PruebasFragmento(unittest.TestCase):

    def test_la_oracion_entera_cubre_todo(self):
        frase = "mext activates the efflux pump"
        self.assertEqual(V.fragmento_mas_largo(frase, "here mext activates the efflux pump ."),
                         1.0)

    def test_media_oracion_cubre_la_mitad(self):
        frase = "uno dos tres cuatro"
        cobertura = V.fragmento_mas_largo(frase, "algo uno dos y luego tres cuatro")
        self.assertAlmostEqual(cobertura, 0.5)

    def test_nada_en_comun_da_cero(self):
        self.assertEqual(V.fragmento_mas_largo("alpha beta", "gamma delta"), 0.0)

    def test_frase_vacia_no_revienta(self):
        self.assertEqual(V.fragmento_mas_largo("", "lo que sea"), 0.0)


class PruebasVerificar(unittest.TestCase):

    def test_cuenta_exacta_fragmento_y_ausente(self):
        filas = [
            {"tf": "A", "blanco": "b", "atestiguado": "true", "pmids": "1",
             "oracion": "A activates b"},
            {"tf": "C", "blanco": "d", "atestiguado": "true", "pmids": "2",
             "oracion": "uno dos tres cuatro cinco seis siete ocho"},
            {"tf": "E", "blanco": "f", "atestiguado": "true", "pmids": "3",
             "oracion": "esto no aparece en ninguna parte del corpus"},
            {"tf": "G", "blanco": "h", "atestiguado": "false", "pmids": "",
             "oracion": ""},
        ]
        textos = {
            "1": [V.normalizar("el articulo dice A activates b claramente")],
            "2": [V.normalizar("uno dos tres cuatro cinco seis nueve diez")],
            "3": [V.normalizar("un texto sin relacion alguna")],
        }
        conteo, fallos = V.verificar(filas, textos)
        self.assertEqual(conteo["exacta"], 1)
        self.assertEqual(conteo["fragmento_contiguo"], 1)
        self.assertEqual(conteo["no_encontrada"], 1)
        self.assertEqual(conteo["no_atestiguada"], 1)
        self.assertEqual(len(fallos), 1)
        self.assertEqual(fallos[0][0], "E")

    def test_avisa_cuando_no_hay_texto_del_pmid(self):
        filas = [{"tf": "A", "blanco": "b", "atestiguado": "true",
                  "pmids": "999", "oracion": "lo que sea"}]
        conteo, fallos = V.verificar(filas, {})
        self.assertEqual(conteo["sin_texto_del_pmid"], 1)
        self.assertIn("PMIDs", fallos[0][2])

    def test_una_fila_atestiguada_sin_oracion_es_un_fallo(self):
        filas = [{"tf": "A", "blanco": "b", "atestiguado": "true",
                  "pmids": "1", "oracion": "   "}]
        conteo, fallos = V.verificar(filas, {"1": ["algo"]})
        self.assertEqual(conteo["sin_oracion"], 1)
        self.assertEqual(len(fallos), 1)


if __name__ == "__main__":
    unittest.main()
