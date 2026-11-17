# -*- coding: utf-8 -*-
"""El desglose por origen del texto: resumen contra cuerpo del artículo."""
import csv
import io
import json
import os
import shutil
import tempfile
import unittest

from grn_verificacion import cli, fuentes

CANDIDATAS = ["pmid", "fuente_texto", "seccion", "num_oracion", "oracion"]
CAPA = ["id_par", "pmid", "fuente_texto", "seccion", "pasa_umbral"]
EVIDENCIAS = ["tf", "blanco", "id_par", "pmid", "seccion", "fuente"]
EVIDENCIAS_JUEZ = EVIDENCIAS + ["veredicto_agente", "votos_si"]


def _csv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(columnas)
        w.writerows(filas)


def _tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(str(x) for x in fila) + "\n")


class PruebasOrigen(unittest.TestCase):

    def test_el_resumen_es_la_seccion_abstract_de_cualquier_articulo(self):
        o = fuentes.origen_del_texto
        self.assertEqual(o("abstract", "abstract"), "resumen")
        self.assertEqual(o("xml", "abstract"), "resumen")
        self.assertEqual(o("pdf", "Abstract"), "resumen")
        self.assertEqual(o("resumen", ""), "resumen")

    def test_el_cuerpo_se_separa_por_la_fuente(self):
        o = fuentes.origen_del_texto
        self.assertEqual(o("xml", "results"), "cuerpo_xml")
        self.assertEqual(o("fulltext", "discussion"), "cuerpo_xml")
        self.assertEqual(o("pdf", "results"), "cuerpo_pdf")

    def test_sin_fuente_ni_seccion_no_se_inventa(self):
        self.assertEqual(fuentes.origen_del_texto("", None), "sin_dato")


class PruebasCarpeta(unittest.TestCase):

    def setUp(self):
        self.c = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.c, True)
        _csv(os.path.join(self.c,
                          "bronce_identificacion_corrida1_20260101"
                          "_oraciones_candidatas.csv"), CANDIDATAS, [
            ("1", "abstract", "abstract", 1, "a"),
            ("2", "xml", "abstract", 1, "b"),
            ("2", "xml", "results", 9, "c"),
            ("2", "xml", "results", 10, "d"),
            ("3", "pdf", "discussion", 4, "e"),
        ])
        _csv(os.path.join(self.c, "capa_pares.csv"), CAPA, [
            ("p1", "1", "abstract", "abstract", "si"),
            ("p2", "2", "xml", "abstract", "no"),
            ("p3", "2", "xml", "results", "si"),
            ("p4", "2", "xml", "results", "si"),
            ("p5", "3", "pdf", "discussion", "si"),
        ])
        # A>b: resumen de un artículo solo con resumen y cuerpo de XML.
        # C>d: solo cuerpo de PDF. E>f: resumen y cuerpo del mismo XML.
        self.evidencias = [
            ("A", "b", "p1", "1", "abstract", "resumen"),
            ("A", "b", "p3", "2", "results", "fulltext"),
            ("C", "d", "p5", "3", "discussion", "pdf"),
            ("E", "f", "p2", "2", "abstract", "fulltext"),
            ("E", "f", "p4", "2", "results", "fulltext"),
            ("G", "h", "p1", "1", "abstract", "resumen"),
        ]
        _tsv(os.path.join(self.c, "red_evidencias.tsv"), EVIDENCIAS,
             self.evidencias)

    def con_juez(self):
        _tsv(os.path.join(self.c, "red_juez.tsv"), ["tf", "blanco", "nivel"],
             [("A", "b", "alta"), ("C", "d", "sin_respaldo"),
              ("E", "f", "media"), ("G", "h", "sin_respaldo")])
        veredictos = [("confirma", 3), ("", ""), ("rechaza", 0),
                      ("confirma", 2), ("", ""), ("rechaza", 0)]
        _tsv(os.path.join(self.c, "red_evidencias_juez.tsv"), EVIDENCIAS_JUEZ,
             [e + v for e, v in zip(self.evidencias, veredictos)])

    def test_el_embudo_cuenta_por_origen(self):
        e = fuentes.calcular(self.c)["embudo"]

        self.assertEqual(e["por_origen"]["resumen"], {
            "articulos": 2, "oraciones_candidatas": 2, "pares": 2,
            "pares_sobre_umbral": 1})
        self.assertEqual(e["por_origen"]["cuerpo_xml"]["pares_sobre_umbral"],
                         2)
        self.assertEqual(e["por_origen"]["cuerpo_pdf"]["articulos"], 1)
        self.assertEqual(e["articulos_por_fuente"],
                         {"abstract": 1, "pdf": 1, "xml": 1})

    def test_las_aristas_por_el_origen_de_su_evidencia(self):
        a = fuentes.calcular(self.c)["aristas"]

        self.assertEqual(a["aristas"], 4)
        self.assertEqual(
            [(c, g["aristas"]) for c, g in a["por_clase"].items()],
            [("solo_resumen", 1), ("resumen_y_cuerpo", 2),
             ("solo_cuerpo", 1)])
        self.assertEqual(a["con_evidencia_en"]["cuerpo_pdf"]["aristas"], 1)

    def test_en_los_articulos_con_texto_completo_no_entra_el_solo_resumen(
            self):
        t = fuentes.calcular(self.c)["aristas"][
            "articulos_con_texto_completo"]

        # A>b tiene resumen, pero de un artículo sin texto completo: en los
        # que sí lo tienen solo está en el cuerpo. G>h no entra.
        self.assertEqual(t["aristas"], 3)
        self.assertEqual(t["en_su_resumen"]["aristas"], 1)
        self.assertEqual(t["en_su_cuerpo"]["aristas"], 3)
        self.assertEqual(t["solo_en_su_cuerpo"]["aristas"], 2)
        self.assertEqual(t["solo_en_su_resumen"]["aristas"], 0)

    def test_sin_juez_no_hay_niveles_ni_jurado(self):
        r = fuentes.calcular(self.c)

        self.assertIsNone(r["jurado"])
        self.assertNotIn("nivel", r["aristas"]["por_clase"]["solo_cuerpo"])

    def test_con_juez_salen_los_niveles_y_el_veredicto_por_origen(self):
        self.con_juez()
        r = fuentes.calcular(self.c)

        self.assertEqual(
            r["aristas"]["por_clase"]["resumen_y_cuerpo"]["nivel"],
            {"alta": 1, "media": 1, "al_reves": 0, "sin_respaldo": 0})
        j = r["jurado"]
        # Las oraciones sin veredicto no se juzgaron y no cuentan.
        self.assertEqual((j["resumen"]["juzgadas"], j["resumen"]["confirma"],
                          j["resumen"]["rechaza"]), (3, 2, 1))
        self.assertEqual(j["resumen"]["confirma_unanime"], 1)
        self.assertEqual(j["cuerpo_pdf"]["rechaza"], 1)
        self.assertNotIn("cuerpo_xml", j)

    def test_el_cli_escribe_el_json_y_solo_dice_cifras(self):
        self.con_juez()
        ruta = os.path.join(self.c, "fuentes.json")
        dicho = []
        original, cli.log = cli.log, dicho.append
        self.addCleanup(setattr, cli, "log", original)

        codigo = cli.main(["fuentes", "--carpeta", self.c, "--json", ruta])

        self.assertEqual(codigo, 0)
        with io.open(ruta, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["aristas"]["aristas"], 4)
        self.assertTrue(any("solo_cuerpo 1" in linea for linea in dicho))

    def test_sin_la_capa_sale_con_1(self):
        os.remove(os.path.join(self.c, "capa_pares.csv"))
        dicho = []
        original, cli.log = cli.log, dicho.append
        self.addCleanup(setattr, cli, "log", original)

        self.assertEqual(cli.main(["fuentes", "--carpeta", self.c]), 1)
        self.assertTrue(dicho[-1].startswith("ERROR"))


if __name__ == "__main__":
    unittest.main()
