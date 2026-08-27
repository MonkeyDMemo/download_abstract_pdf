# -*- coding: utf-8 -*-
"""Pruebas del muestreo para precision.

La que mas importa es la de la ponderacion: en un muestreo estratificado la
precision global es la suma ponderada por el tamano de cada estrato, no el
promedio de los tres, y con estratos de tamanos muy distintos las dos cifras
se separan muchisimo. Es el error facil de este metodo.

    python -m unittest discover etapa2
"""

import csv
import io
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import muestrear_precision as M


def arista(tf, blanco, signo="activates", n_art=5, conflicto="false",
           n_ev=7, conf="0.95"):
    return {"tf": tf, "blanco": blanco, "signo": signo, "conflicto": conflicto,
            "n_evidencias": str(n_ev), "n_activates": "5", "n_represses": "0",
            "n_regulates": "2", "n_articulos": str(n_art), "confianza": conf,
            "autorregulacion": "false", "secciones": "results",
            "pmids": "1", "oracion_representativa": "x"}


def juicio(estrato, veredicto):
    return {"estrato": estrato, "veredicto": veredicto}


class PruebasEstratos(unittest.TestCase):

    def test_con_signo_y_respaldo_es_A(self):
        self.assertEqual(M.estrato_de(arista("LasR", "rhlR", n_art=3)), "A")

    def test_con_signo_pero_pocos_articulos_es_B(self):
        self.assertEqual(M.estrato_de(arista("LasR", "rhlR", n_art=2)), "B")

    def test_con_conflicto_baja_a_B(self):
        """Una arista donde las evidencias se contradicen no es del entregable
        aunque tenga muchos articulos."""
        self.assertEqual(
            M.estrato_de(arista("LasR", "rhlR", n_art=9, conflicto="true")), "B")

    def test_sin_signo_es_C_aunque_tenga_respaldo(self):
        self.assertEqual(
            M.estrato_de(arista("LasR", "rhlR", signo="regulates", n_art=9)), "C")


class PruebasWilson(unittest.TestCase):

    def test_cae_dentro_de_cero_y_uno_en_los_extremos(self):
        """Es la razon de usar Wilson y no el normal: con 20 de 20 el normal
        da un intervalo que se sale del 1."""
        baja, alta = M.wilson(20, 20)
        self.assertLessEqual(alta, 1.0)
        self.assertGreater(baja, 0.75)
        baja, alta = M.wilson(0, 20)
        self.assertGreaterEqual(baja, 0.0)
        self.assertLess(alta, 0.25)

    def test_contiene_la_proporcion_observada(self):
        baja, alta = M.wilson(70, 100)
        self.assertLess(baja, 0.70)
        self.assertGreater(alta, 0.70)

    def test_se_angosta_al_crecer_la_muestra(self):
        a = M.wilson(35, 50)
        b = M.wilson(350, 500)
        self.assertLess(b[1] - b[0], a[1] - a[0])

    def test_sin_datos_no_inventa_intervalo(self):
        self.assertEqual(M.wilson(0, 0), (None, None))


class PruebasPonderacion(unittest.TestCase):
    """El error facil de este metodo, con numeros que lo hacen evidente."""

    def _mudo(self, *a):
        pass

    def test_la_global_no_es_el_promedio_de_los_estratos(self):
        # A es chico y perfecto; C es enorme y malo. El promedio simple diria
        # 60%; la ponderada tiene que acercarse al 20% de C, que pesa 90%.
        censo = {"A": 100, "B": 100, "C": 1800}
        muestra = ([juicio("A", "si")] * 20
                   + [juicio("B", "si")] * 10 + [juicio("B", "no")] * 10
                   + [juicio("C", "si")] * 4 + [juicio("C", "no")] * 16)
        r = M.resumir(muestra, censo, self._mudo)
        prom = (1.0 + 0.5 + 0.2) / 3
        g = r["global_ponderada"]["precision"]
        self.assertAlmostEqual(prom, 0.5667, places=3)
        self.assertLess(g, 0.35, "la ponderada tiene que irse hacia el estrato grande")
        self.assertGreater(g, 0.20)

    def test_los_pesos_suman_uno(self):
        censo = {"A": 945, "B": 3188, "C": 4520}
        muestra = ([juicio("A", "si")] * 5 + [juicio("B", "si")] * 5
                   + [juicio("C", "si")] * 5)
        r = M.resumir(muestra, censo, self._mudo)
        pesos = [r["por_estrato"][e]["peso"] for e in M.ESTRATOS]
        self.assertAlmostEqual(sum(pesos), 1.0, places=3)

    def test_la_correccion_por_poblacion_finita_angosta_el_intervalo(self):
        """Muestrear 50 de 60 deja poca incertidumbre; muestrear 50 de 100000
        deja la binomial entera."""
        muestra = [juicio("A", "si")] * 35 + [juicio("A", "no")] * 15
        chico = M.resumir(muestra, {"A": 60, "B": 0, "C": 0}, self._mudo)
        grande = M.resumir(muestra, {"A": 100000, "B": 0, "C": 0}, self._mudo)
        anchura = lambda r: (r["global_ponderada"]["ic95"][1]
                             - r["global_ponderada"]["ic95"][0])
        self.assertLess(anchura(chico), anchura(grande))


class PruebasAciertos(unittest.TestCase):
    """Que cuenta como acierto depende del estrato, y no es un detalle."""

    def _mudo(self, *a):
        pass

    def test_sin_signo_es_error_en_A_pero_acierto_en_C(self):
        censo = {"A": 10, "B": 0, "C": 10}
        r = M.resumir([juicio("A", "sin_signo")] * 10
                      + [juicio("C", "sin_signo")] * 10, censo, self._mudo)
        self.assertEqual(r["por_estrato"]["A"]["precision"], 0.0)
        self.assertEqual(r["por_estrato"]["C"]["precision"], 1.0)

    def test_signo_mal_es_error_y_se_cuenta_aparte_de_no(self):
        censo = {"A": 10, "B": 0, "C": 0}
        r = M.resumir([juicio("A", "signo_mal")] * 6 + [juicio("A", "no")] * 4,
                      censo, self._mudo)
        self.assertEqual(r["por_estrato"]["A"]["precision"], 0.0)
        v = r["por_estrato"]["A"]["veredictos"]
        self.assertEqual(v["signo_mal"], 6)
        self.assertEqual(v["no"], 4)

    def test_no_se_sale_del_denominador(self):
        censo = {"A": 10, "B": 0, "C": 0}
        r = M.resumir([juicio("A", "si")] * 8 + [juicio("A", "no_se")] * 2,
                      censo, self._mudo)
        self.assertEqual(r["por_estrato"]["A"]["en_el_denominador"], 8)
        self.assertEqual(r["por_estrato"]["A"]["precision"], 1.0)

    def test_las_filas_sin_juzgar_no_cuentan_y_se_avisan(self):
        censo = {"A": 10, "B": 0, "C": 0}
        r = M.resumir([juicio("A", "si")] * 5 + [juicio("A", "")] * 5,
                      censo, self._mudo)
        self.assertEqual(r["por_estrato"]["A"]["sin_juzgar"], 5)
        self.assertEqual(r["por_estrato"]["A"]["en_el_denominador"], 5)


class PruebasMuestreo(unittest.TestCase):

    def setUp(self):
        self.red = ([arista("TF%d" % i, "g%d" % i, n_art=5) for i in range(50)]
                    + [arista("TU%d" % i, "h%d" % i, n_art=1) for i in range(40)]
                    + [arista("TV%d" % i, "k%d" % i, signo="regulates")
                       for i in range(30)])

    def test_es_reproducible(self):
        a, _ = M.muestrear(self.red, {"A": 10, "B": 10, "C": 10}, 7)
        b, _ = M.muestrear(self.red, {"A": 10, "B": 10, "C": 10}, 7)
        self.assertEqual([(e, r["tf"]) for e, r in a],
                         [(e, r["tf"]) for e, r in b])

    def test_otra_semilla_da_otra_muestra(self):
        a, _ = M.muestrear(self.red, {"A": 10, "B": 10, "C": 10}, 7)
        b, _ = M.muestrear(self.red, {"A": 10, "B": 10, "C": 10}, 8)
        self.assertNotEqual([r["tf"] for _, r in a], [r["tf"] for _, r in b])

    def test_respeta_el_reparto_por_estrato(self):
        el, _ = M.muestrear(self.red, {"A": 12, "B": 7, "C": 5}, 3)
        import collections
        c = collections.Counter(e for e, _ in el)
        self.assertEqual((c["A"], c["B"], c["C"]), (12, 7, 5))

    def test_no_repite_aristas(self):
        el, _ = M.muestrear(self.red, {"A": 50, "B": 40, "C": 30}, 3)
        claves = [(r["tf"], r["blanco"]) for _, r in el]
        self.assertEqual(len(claves), len(set(claves)))

    def test_pide_mas_de_las_que_hay_y_no_revienta(self):
        el, _ = M.muestrear(self.red, {"A": 999, "B": 999, "C": 999}, 3)
        self.assertEqual(len(el), 120)

    def test_sale_barajada_entre_estratos(self):
        """Si viniera ordenada, el juez cambiaria de criterio al cambiar de
        bloque. Se comprueba que hay alternancia."""
        el, _ = M.muestrear(self.red, {"A": 20, "B": 20, "C": 20}, 11)
        seq = [e for e, _ in el]
        cambios = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
        self.assertGreater(cambios, 20, "la muestra salio en bloques")


class PruebasCircularidad(unittest.TestCase):
    """El juez no puede ver nada que le diga la respuesta."""

    def test_la_muestra_no_expone_el_patron_de_oro(self):
        for c in M.COLUMNAS:
            self.assertNotIn("oro", c.lower())
            self.assertNotIn("gold", c.lower())
            self.assertNotIn("canonic", c.lower())

    def test_el_modulo_no_lee_el_patron_de_oro(self):
        """Si alguien importara el oro aqui, el juicio dejaria de ser ciego."""
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "muestrear_precision.py")
        with io.open(ruta, encoding="utf-8") as f:
            cuerpo = f.read()
        # Se permite nombrarlo en la documentacion, no abrirlo.
        self.assertNotIn("oro_pseudomonas.tsv", cuerpo.split('"""')[-1])
        self.assertNotIn("cargar_oro", cuerpo)

    def test_la_probabilidad_del_modelo_no_va_junto_a_la_oracion(self):
        """La confianza de la arista si va --es parte del respaldo-- pero la
        probabilidad de cada oracion no, porque ancla el juicio fila a fila."""
        self.assertNotIn("probabilidad", M.COLUMNAS)


class PruebasArchivo(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="muestra_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_escribe_hasta_tres_evidencias_de_articulos_distintos(self):
        ev = {("LasR", "rhlR"): [
            {"pmid": "1", "seccion": "results", "oracion": "una"},
            {"pmid": "2", "seccion": "abstract", "oracion": "dos"},
            {"pmid": "3", "seccion": "results", "oracion": "tres"}]}
        ruta = os.path.join(self.d, "m.tsv")
        M.escribir_muestra([("A", arista("LasR", "rhlR"))], ev, ruta)
        with open(ruta, encoding="utf-8") as f:
            fila = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual((fila["oracion"], fila["oracion_2"], fila["oracion_3"]),
                         ("una", "dos", "tres"))
        self.assertEqual(fila["veredicto"], "")

    def test_una_arista_con_una_sola_evidencia_deja_las_otras_vacias(self):
        ev = {("LasR", "rhlR"): [
            {"pmid": "1", "seccion": "results", "oracion": "sola"}]}
        ruta = os.path.join(self.d, "m.tsv")
        M.escribir_muestra([("A", arista("LasR", "rhlR"))], ev, ruta)
        with open(ruta, encoding="utf-8") as f:
            fila = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(fila["oracion"], "sola")
        self.assertEqual(fila["oracion_2"], "")

    def test_las_evidencias_vienen_de_pmids_distintos(self):
        ruta = os.path.join(self.d, "ev.tsv")
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(["tf", "blanco", "id_par", "pmid", "seccion", "fuente",
                        "prediccion", "probabilidad", "redaccion", "oracion"])
            for i in range(5):
                w.writerow(["LasR", "rhlR", "x", "7", "results", "fulltext",
                            "activates", "0.9", "otra", "del mismo articulo %d" % i])
            w.writerow(["LasR", "rhlR", "x", "8", "results", "fulltext",
                        "activates", "0.9", "otra", "de otro articulo"])
        por = M.evidencias_por_arista(ruta)
        pmids = [e["pmid"] for e in por[("LasR", "rhlR")]]
        self.assertEqual(sorted(pmids), ["7", "8"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
