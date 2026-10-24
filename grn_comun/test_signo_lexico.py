# -*- coding: utf-8 -*-
"""Pruebas de `grn_comun.signo_lexico.signo_cercano`.

Fijan las peculiaridades del algoritmo del 8-oct-2026, que se mudó aquí sin
cambios: son parte de lo que mide el punto 18 y de lo que vota la red, y
«arreglar» una cambiaría las dos cifras a la vez. Que la capa y esta función
digan lo mismo lo prueba `grn_verificacion/test_capa_evaluar.py`.

Oraciones y nombres inventados; nada del laboratorio.

    python -m unittest grn_comun.test_signo_lexico
"""

import ast
import io
import os
import unittest

from grn_comun import signo_lexico
from grn_comun.signo_lexico import signo_cercano


class _Vocab(object):
    """Un vocabulario falso: busca cada palabra tal cual y devuelve
    `[(ini, fin, palabra, signo)]` en orden de aparición, como
    `Vocabulario.disparadores_en`."""

    def __init__(self, signos):
        self.signos = signos

    def disparadores_en(self, oracion):
        salida = []
        for palabra, signo in self.signos.items():
            ini = oracion.find(palabra)
            while ini >= 0:
                salida.append((ini, ini + len(palabra), palabra, signo))
                ini = oracion.find(palabra, ini + 1)
        return sorted(salida)


VOCAB = _Vocab({"activates": "+", "represses": "-", "regulates": "?"})


class PruebasSignoCercano(unittest.TestCase):

    def test_dentro_del_tramo_gana(self):
        self.assertEqual(signo_cercano("QzaR represses wvaA, and activates "
                                       "nothing else.", "QzaR", "wvaA",
                                       VOCAB), "-")

    def test_el_orden_de_las_menciones_no_importa(self):
        oracion = "QzaR represses wvaA, and activates nothing else."
        self.assertEqual(signo_cercano(oracion, "wvaA", "QzaR", VOCAB),
                         signo_cercano(oracion, "QzaR", "wvaA", VOCAB))

    def test_cada_mencion_es_su_primera_aparicion(self):
        """El par marcado podría ser el de la segunda QzaR y la segunda wvaA,
        con «activates» entre las dos; `find` toma las primeras, y entre ellas
        queda «represses»."""
        oracion = ("QzaR represses many genes, and wvaA is activated when "
                   "QzaR activates wvaA.")
        self.assertEqual(signo_cercano(oracion, "QzaR", "wvaA", VOCAB), "-")

    def test_el_tramo_acaba_donde_empieza_la_segunda_mencion(self):
        """«represses» está a 4 caracteres de QzaR y «activates» a 5 del
        inicio de wvaA. Medido desde el final de wvaA estaría a 1, y ganaría
        el otro signo."""
        oracion = "represses at QzaR and wvaA activates"
        self.assertEqual(signo_cercano(oracion, "QzaR", "wvaA", VOCAB), "-")

    def test_en_un_empate_gana_el_primero_en_la_oracion(self):
        self.assertEqual(signo_cercano("QzaR activates or represses wvaA.",
                                       "QzaR", "wvaA", VOCAB), "+")
        self.assertEqual(signo_cercano("QzaR represses or activates wvaA.",
                                       "QzaR", "wvaA", VOCAB), "-")

    def test_el_interrogacion_no_cuenta(self):
        self.assertEqual(signo_cercano("QzaR regulates wvaA.", "QzaR",
                                       "wvaA", VOCAB), "")
        self.assertEqual(signo_cercano("QzaR regulates wvaA; it represses "
                                       "others.", "QzaR", "wvaA", VOCAB), "-")

    def test_una_mencion_que_no_aparece_deja_sin_signo(self):
        self.assertEqual(signo_cercano("QzaR represses wvaA.", "QzbR", "wvaA",
                                       VOCAB), "")

    def test_una_mencion_vacia_se_encuentra_al_principio(self):
        """`"".find` da 0: el tramo empieza en la posición 0, y el
        «represses» del principio queda dentro."""
        oracion = "It represses stuff, then QzaR activates far away."
        self.assertEqual(signo_cercano(oracion, "", "QzaR", VOCAB), "-")
        self.assertEqual(signo_cercano(oracion, "QzbR", "QzaR", VOCAB), "")

    def test_sin_disparadores(self):
        self.assertEqual(signo_cercano("QzaR and wvaA.", "QzaR", "wvaA",
                                       _Vocab({})), "")

    def test_con_el_vocabulario_del_bronce(self):
        """La firma es la de `Vocabulario.disparadores_en`, el de verdad."""
        from grn_bronce import vocabulario
        vocab = vocabulario.Vocabulario.cargar()
        self.assertEqual(signo_cercano("QzaR represses wvaA.", "QzaR", "wvaA",
                                       vocab), "-")
        self.assertEqual(signo_cercano("QzaR activates wvaA.", "QzaR", "wvaA",
                                       vocab), "+")


class PruebasCompatibilidad(unittest.TestCase):

    def test_python_3_8_y_no_imprime(self):
        ruta = os.path.abspath(signo_lexico.__file__)
        with io.open(ruta, encoding="utf-8") as f:
            arbol = ast.parse(f.read(), filename=ruta, feature_version=(3, 8))
        self.assertEqual([n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Name)
                          and n.func.id == "print"], [])
        # Nada de los pasos: los tres la importan, y si ella importara de
        # alguno la dependencia daría la vuelta.
        importados = set()
        for n in ast.walk(arbol):
            if isinstance(n, ast.Import):
                importados.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                importados.add(n.module or "")
        self.assertEqual([m for m in importados if m.startswith("grn_")
                          and not m.startswith("grn_comun")], [])


if __name__ == "__main__":
    unittest.main()
