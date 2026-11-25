# -*- coding: utf-8 -*-
"""La base en el artículo que cita: misma oración, mismo artículo o falta."""
import io
import os
import tempfile
import unittest

from grn_verificacion import cobertura_articulo as ca
from grn_verificacion import contraste

A, B, C, D = "PA0001", "PA0002", "PA0003", "PA0004"
HISTORICA = [e for e in contraste.ESTRATOS if e != "biobert"][0]


def fila(regulador, blanco, pmids, origen=HISTORICA):
    return {"regulador": regulador, "blanco": blanco, "pmids": list(pmids),
            "origen": origen}


class PruebasCaso(unittest.TestCase):

    def setUp(self):
        self.loci = {1: {A, B, C}, 2: {A}, 3: {D}}
        self.por_pmid = {1: {contraste._par(A, B)}}

    def caso(self, regulador, blanco, pmids):
        return ca.caso_de(fila(regulador, blanco, pmids), self.loci,
                          self.por_pmid)

    def test_los_dos_en_una_candidata_del_articulo(self):
        self.assertEqual(self.caso(B, A, [1]), "misma_oracion")

    def test_los_dos_en_el_articulo_pero_en_otra_oracion(self):
        self.assertEqual(self.caso(A, C, [1]), "mismo_articulo")

    def test_cada_uno_en_un_articulo_citado_distinto(self):
        self.assertEqual(self.caso(A, D, [2, 3]), "articulos_distintos")

    def test_falta_el_blanco(self):
        self.assertEqual(self.caso(A, D, [2]), "solo_regulador")

    def test_falta_el_regulador(self):
        self.assertEqual(self.caso(B, A, [2]), "solo_blanco")

    def test_no_esta_ninguno(self):
        self.assertEqual(self.caso(B, C, [3]), "ninguno")

    def test_un_articulo_fuera_del_corpus_no_cuenta(self):
        self.assertEqual(self.caso(A, B, [2, 99]), "solo_regulador")


class PruebasContar(unittest.TestCase):

    def test_grupos_estrato_y_autorregulacion(self):
        loci = {1: {A, B, C}, 2: {A}}
        tipo = {1: "completo", 2: "resumen"}
        por_pmid = {1: {contraste._par(A, B)}}
        filas = [fila(A, B, [1]), fila(A, C, [1]), fila(A, A, [1]),
                 fila(A, B, [2]), fila(A, B, [2, 1]), fila(C, D, [77]),
                 fila(A, B, [1], origen="biobert")]
        r = ca.contar(filas, loci, tipo, por_pmid)
        self.assertEqual(r["completo"]["filas"], 4)
        self.assertEqual(r["completo"]["misma_oracion"], 2)
        self.assertEqual(r["completo"]["mismo_articulo"], 1)
        self.assertEqual(r["completo"]["autorregulacion"], 1)
        self.assertEqual(r["resumen"]["filas"], 1)
        self.assertEqual(r["resumen"]["solo_regulador"], 1)
        self.assertEqual(r["fuera"], {"filas": 1, "autorregulacion": 0})
        total = sum(r[g]["filas"] for g in ca.GRUPOS)
        self.assertEqual(total, 6, "la fila de BioBERT no entra")
        for g in ("completo", "resumen"):
            self.assertEqual(
                r[g]["filas"],
                r[g]["autorregulacion"] + sum(r[g][c] for c in ca.CASOS))


class PruebasLoci(unittest.TestCase):

    def test_menciones_candidatas_y_tipo_de_texto(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ruta = os.path.join(tmp.name, "menciones.csv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write("pmid,fuente_texto,tipo,id_normalizado\n"
                    "1,abstract,gen,PA0001\n"
                    "1,pdf,proteina,PA0002\n"
                    "1,pdf,operon,mexAB-oprM\n"
                    "1,pdf,disparador,PA0009\n"
                    "2,abstract,organismo,\n")
        # Los PMID son texto, como los deja `contraste._pmid`.
        loci, tipo = ca.loci_por_articulo(ruta, [("1", {C}, {D})])
        self.assertEqual(loci["1"], {A, B, C, D})
        self.assertEqual(tipo, {"1": "completo", "2": "resumen"})
        self.assertNotIn("2", loci)

    def test_las_lineas_pasan_el_filtro_de_publicacion(self):
        r = {"carpeta": "corrida25_run22",
             "articulos_del_corpus": {"completo": 1436, "resumen": 925},
             "por_grupo": ca.contar([], {}, {}, {})}
        for linea in ca.lineas(r):
            contraste.reentrenar.verificar_publicable(linea)


if __name__ == "__main__":
    unittest.main()
