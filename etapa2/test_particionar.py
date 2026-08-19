# -*- coding: utf-8 -*-
"""Pruebas del particionador.

La que no puede faltar: pasarle a verificar() una particion deliberadamente
sucia y afirmar que la rechaza. Sin ella el guardian puede volver a quedarse
en codigo muerto sin que nadie se entere, que es como se colo la fuga del
0.87 en primer lugar.

    python -m unittest discover etapa2
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import particionar as P


def fila(texto, etiqueta="activates", pmid=1, tf="AraC", target="araBAD"):
    return {"text": texto, "label": etiqueta, "pmid": pmid,
            "tf": tf, "target": target}


class PruebasVentana(unittest.TestCase):

    def test_los_marcadores_se_quitan_sin_dejar_espacio(self):
        """Sustituirlos por un espacio partia el mismo fragmento en dos
        ventanas cuando la etiqueta tocaba un caracter que no era espacio."""
        a = P.ventana("<e1>CRP</e1>-dependent AraC activates <e2>araBAD</e2> .")
        b = P.ventana("CRP-dependent <e1>AraC</e1> activates <e2>araBAD</e2> .")
        self.assertEqual(a, b)
        self.assertEqual(a, "CRP-dependent AraC activates araBAD .")

    def test_el_espaciado_se_normaliza(self):
        self.assertEqual(P.ventana("uno   dos\n\ttres"), "uno dos tres")


class PruebasCanonico(unittest.TestCase):
    """canonico() tiene que ser INDEPENDIENTE de ventana(). Si fueran la
    misma funcion, verificar() mediria con la clave del agrupamiento y daria
    cero pasara lo que pasara."""

    def test_canonico_no_es_ventana(self):
        t = "El regulador LasR, activa a rhlR."
        self.assertNotEqual(P.canonico(t), P.ventana(t))

    def test_canonico_ignora_puntuacion_y_mayusculas(self):
        self.assertEqual(P.canonico("LasR, activa a rhlR."),
                         P.canonico("lasr activa a rhlr"))

    def test_canonico_reconoce_lo_que_ventana_dejaria_pasar(self):
        """Dos textos que ventana() ve distintos por una coma, canonico()
        los ve iguales. Esa es justo la fuga que el guardian debe atrapar."""
        a, b = "AraC activa a araBAD", "AraC activa, a araBAD"
        self.assertNotEqual(P.ventana(a), P.ventana(b))
        self.assertEqual(P.canonico(a), P.canonico(b))


class PruebasGuardian(unittest.TestCase):
    """verificar() tiene que poder devolver False."""

    def _mudo(self, *a):
        pass

    def test_rechaza_una_particion_con_texto_repetido(self):
        t = "AraC activates <e2>araBAD</e2> in Escherichia coli ."
        tr = [fila(t, pmid=1)]
        te = [fila(t, pmid=2)]          # mismo texto, otro articulo
        todas = tr + te
        self.assertFalse(
            P.verificar([tr, te], ["train", "test"], "pmid", todas, self._mudo))

    def test_rechaza_una_particion_con_el_pmid_repetido(self):
        tr = [fila("uno dos tres cuatro", pmid=7)]
        te = [fila("cinco seis siete ocho", pmid=7)]
        todas = tr + te
        self.assertFalse(
            P.verificar([tr, te], ["train", "test"], "pmid", todas, self._mudo))

    def test_rechaza_una_parte_vacia(self):
        """Con --folds 2 el train salia vacio, y como toda pertenencia contra
        un conjunto vacio es falsa, la particion se declaraba limpia."""
        tr = []
        te = [fila("uno dos tres", pmid=1)]
        self.assertFalse(
            P.verificar([tr, te], ["train", "test"], "pmid", te, self._mudo))

    def test_rechaza_si_faltan_filas(self):
        a, b = fila("uno dos tres", pmid=1), fila("cuatro cinco", pmid=2)
        c = fila("seis siete", pmid=3)
        self.assertFalse(
            P.verificar([[a], [b]], ["train", "test"], "pmid",
                        [a, b, c], self._mudo))

    def test_acepta_una_particion_limpia(self):
        tr = [fila("uno dos tres cuatro cinco", pmid=1)]
        te = [fila("seis siete ocho nueve diez", pmid=2, tf="LasR", target="rhlR")]
        todas = tr + te
        self.assertTrue(
            P.verificar([tr, te], ["train", "test"], "pmid", todas, self._mudo))

    def test_el_guardian_no_mide_con_la_clave_del_agrupamiento(self):
        """Si verificar() usara ventana(), esta particion pasaria: los dos
        textos difieren en una coma, asi que caen en grupos distintos."""
        tr = [fila("AraC activates araBAD in Escherichia coli", pmid=1)]
        te = [fila("AraC activates, araBAD in Escherichia coli", pmid=2)]
        todas = tr + te
        self.assertNotEqual(P.ventana(tr[0]["text"]), P.ventana(te[0]["text"]))
        self.assertFalse(
            P.verificar([tr, te], ["train", "test"], "pmid", todas, self._mudo))


class PruebasAgrupamiento(unittest.TestCase):

    def test_la_misma_ventana_no_se_puede_partir(self):
        """Dos pares marcados sobre el mismo fragmento van juntos aunque el
        criterio sea el par."""
        t1 = "<e1>AraC</e1> regula a <e2>araBAD</e2> y a araC ."
        t2 = "AraC regula a araBAD y a <e2>araC</e2> ."
        f1 = fila(t1, pmid=1, tf="AraC", target="araBAD")
        f2 = fila(t2, pmid=1, tf="AraC", target="araC")
        grupos = P.agrupar([f1, f2], "par")
        self.assertEqual(len(grupos), 1)

    def test_la_ventana_compartida_une_dos_articulos(self):
        t = "MelR activates the melAB promoter in Escherichia coli ."
        grupos = P.agrupar([fila(t, pmid=1), fila(t, pmid=2)], "pmid")
        self.assertEqual(len(grupos), 1)


class PruebasReparto(unittest.TestCase):

    def test_es_determinista(self):
        grupos = [[fila("t%d palabra palabra" % i, pmid=i)] for i in range(40)]
        a, _ = P.repartir(grupos, [.8, .1, .1], 7, 20)
        b, _ = P.repartir(grupos, [.8, .1, .1], 7, 20)
        self.assertEqual([len(x) for x in a], [len(x) for x in b])

    def test_reparte_todos_los_grupos(self):
        grupos = [[fila("t%d palabra" % i, pmid=i)] for i in range(30)]
        partes, _ = P.repartir(grupos, [.8, .1, .1], 3, 20)
        self.assertEqual(sum(len(p) for p in partes), 30)


class PruebasCasiDuplicados(unittest.TestCase):

    def test_detecta_una_ventana_contenida_en_otra(self):
        largo = ("the role of MelR and the cyclic AMP receptor protein at the "
                 "melAB promoter of Escherichia coli was examined in detail")
        corto = ("the role of MelR and the cyclic AMP receptor protein at the "
                 "melAB promoter")
        cd = P.casi_duplicados([fila(largo, pmid=1)], [fila(corto, pmid=2)])
        self.assertEqual(len(cd), 1)

    def test_no_marca_textos_sin_relacion(self):
        a = "AraC activates the araBAD operon under arabinose induction here"
        b = "LasR controls quorum sensing genes in Pseudomonas aeruginosa PAO1"
        self.assertEqual(P.casi_duplicados([fila(a, pmid=1)], [fila(b, pmid=2)]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
