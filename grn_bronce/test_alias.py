# -*- coding: utf-8 -*-
"""Pruebas de la capa de alias adicionales (`grn_bronce/alias.py`)."""

import io
import os
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import alias as A   # noqa: E402


def gen(locus, simbolo="", alias=""):
    return {"locus_tag": locus, "simbolo": simbolo, "alias": alias}


GENES = [gen("PA0001", "dnaA", "PA0001"), gen("PA0002", "", "PA0002"),
         gen("PA0003", "recF", "PA0003|uvrF"), gen("PA0004", "", "PA0004"),
         gen("PA0005", "", "PA0005"), gen("PA0006", "", "PA0006"),
         gen("", "IHF", "ihf")]


class PruebasGenerar(unittest.TestCase):

    def generar(self, pares, **kw):
        filas, conteos = A.generar(pares, GENES, **kw)
        return [(f["locus_tag"], f["alias"]) for f in filas], conteos

    def test_entra_el_nombre_que_el_diccionario_no_conoce(self):
        filas, conteos = self.generar([("PA0002", "kinB"), ("PA0001", "dnaA"),
                                       ("PA0004", "PA0004"), ("PA0005", "")])
        self.assertEqual(filas, [("PA0002", "kinB")])
        self.assertEqual((conteos["ya_es_del_mismo_gen"],
                          conteos["sin_nombre"]), (1, 2))
        self.assertEqual(sum(conteos.values()), 3)

    def test_la_fila_lleva_la_fuente_y_sale_ordenada(self):
        filas, _ = A.generar([("PA0004", "zzzB"), ("PA0002", "kinB")], GENES)
        self.assertEqual([list(f.items()) for f in filas], [
            [("locus_tag", "PA0002"), ("alias", "kinB"),
             ("fuente", A.FUENTE_PGD)],
            [("locus_tag", "PA0004"), ("alias", "zzzB"),
             ("fuente", A.FUENTE_PGD)]])

    def test_tambien_sobre_una_fila_que_ya_tiene_simbolo(self):
        filas, _ = self.generar([("PA0001", "dnaX")])
        self.assertEqual(filas, [("PA0001", "dnaX")])

    def test_un_nombre_que_ya_usa_otro_gen_no_entra(self):
        # Con dos dueños el léxico no emite mención para ninguno. Tampoco si
        # solo difiere en mayúsculas, ni si es el alias de otra fila o el
        # símbolo de una entidad sin locus.
        for nombre in ("recF", "RecF", "uvrf", "ihf", "IHF"):
            filas, conteos = self.generar([("PA0002", nombre)])
            self.assertEqual(filas, [], nombre)
        self.assertEqual(self.generar([("PA0002", "recF")])[1]
                         ["ya_es_de_otro_gen"], 1)

    def test_un_locus_que_el_diccionario_no_tiene_no_entra(self):
        filas, conteos = self.generar([("PA9999", "kinB")])
        self.assertEqual((filas, conteos["locus_desconocido"]), ([], 1))

    def test_corto_palabra_comun_generico_y_sin_forma(self):
        filas, conteos = self.generar(
            [("PA0002", "abc"), ("PA0004", "cold"), ("PA0005", "orfX"),
             ("PA0006", "ORF12"), ("PA0002", "kin B"), ("PA0002", "9kin")],
            palabras=["Cold"])
        self.assertEqual(filas, [])
        self.assertEqual((conteos["corto_o_palabra_comun"],
                          conteos["generico"], conteos["forma"]), (2, 2, 2))

    def test_un_nombre_con_dos_locus_en_la_fuente_no_entra(self):
        filas, conteos = self.generar([("PA0002", "kinB"), ("PA0004", "KinB"),
                                       ("PA0005", "cdrA"), ("PA0005", "cdrA")])
        self.assertEqual(filas, [("PA0005", "cdrA")])
        self.assertEqual((conteos["ambiguo_en_la_fuente"],
                          conteos["repetido"]), (2, 1))

    def test_el_nombre_de_un_operon_no_entra(self):
        filas, conteos = self.generar([("PA0002", "kinAB")],
                                      operones=["KinAB", "mexAB-oprM"])
        self.assertEqual((filas, conteos["es_un_operon"]), ([], 1))


class PruebasFormas(unittest.TestCase):

    def test_la_de_la_fuente_y_la_de_la_proteina(self):
        self.assertEqual(A.formas("kinB"), ("kinB", "KinB"))
        self.assertEqual(A.formas("lip2"), ("lip2", "Lip2"))
        self.assertEqual(A.formas("Hcp3"), ("Hcp3",))

    def test_con_alias_agrega_sin_repetir_ni_tocar_lo_que_habia(self):
        capa = {"PA0002": ["kinB", "KINB2"], "PA0004": ["zzzB"]}
        self.assertEqual(A.con_alias(["PA0002", "Kinb"], "PA0002", capa),
                         ["PA0002", "Kinb", "KINB2"])
        self.assertEqual(A.con_alias(["x"], "PA0003", capa), ["x"])


class PruebasArchivo(unittest.TestCase):

    def escribir(self, texto):
        ruta = os.path.join(tempfile.mkdtemp(), "capa.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(texto)
        return ruta

    def test_ida_y_vuelta(self):
        filas, _ = A.generar([("PA0004", "zzzB"), ("PA0002", "kinB")], GENES)
        ruta = self.escribir("")
        A.escribir(ruta, filas)
        leidas = A.leer(ruta)
        self.assertEqual([dict(f) for f in leidas], [dict(f) for f in filas])
        self.assertEqual(dict(A.por_locus(leidas)),
                         {"PA0002": ["kinB"], "PA0004": ["zzzB"]})

    def test_lee_con_saltos_de_windows(self):
        ruta = self.escribir("locus_tag\talias\tfuente\r\n"
                             "PA0002\tkinB\tx\r\n")
        self.assertEqual(A.leer(ruta)[0]["alias"], "kinB")

    def test_rechaza_lo_mal_hecho_sin_decir_la_ruta(self):
        for texto in ("locus\talias\tfuente\nPA0002\tkinB\tx\n",
                      "locus_tag\talias\tfuente\nPA2\tkinB\tx\n",
                      "locus_tag\talias\tfuente\nPA0002\tkin B\tx\n",
                      "locus_tag\talias\tfuente\nPA0002\tkinB\tx\n"
                      "PA0004\tKinB\tx\n"):
            ruta = self.escribir(texto)
            with self.assertRaises(ValueError) as e:
                A.leer(ruta)
            self.assertNotIn(os.path.dirname(ruta), str(e.exception))

    def test_otra_version_de_la_fuente_no_entra(self):
        ruta = self.escribir('"locus_tag","gene_name"\n"PA0002","kinB"\n')
        with self.assertRaises(ValueError) as e:
            A.generar_de_pgd(ruta)
        self.assertIn("huella", str(e.exception))
        self.assertEqual(A.pares_de_pgd(ruta), [("PA0002", "kinB")])


class PruebasLaCapaVersionada(unittest.TestCase):
    """`recursos/alias_adicionales.tsv` contra el diccionario de hoy."""

    @classmethod
    def setUpClass(cls):
        cls.filas = A.leer()
        cls.genes = A._leer_tsv(A.RUTA_GENES, ["locus_tag", "simbolo",
                                               "alias"])

    def test_las_formas_son_las_del_constructor_del_diccionario(self):
        sys.path.insert(0, os.path.join(_RAIZ, "etapa2"))
        try:
            import construir_diccionario as C
        finally:
            sys.path.pop(0)
        self.assertEqual(A.LOCUS.pattern, C.LOCUS.pattern)
        self.assertEqual(A.ALIAS_SANO.pattern, C.ALIAS_SANO.pattern)

    def test_cada_fila_pasa_las_reglas_con_el_diccionario_de_hoy(self):
        # Si el diccionario gana un nombre que la capa ya daba, o cambia la
        # lista de palabras, la capa se regenera: aquí se nota.
        operones = [f["operon"] for f in A._leer_tsv(A.RUTA_OPERONES,
                                                     ["operon"])]
        pares = [(f["locus_tag"], f["alias"]) for f in self.filas]
        otra_vez, conteos = A.generar(pares, self.genes, operones,
                                      A.leer_palabras())
        self.assertEqual(sum(conteos.values()), 0, dict(conteos))
        self.assertEqual([dict(f) for f in otra_vez],
                         [dict(f) for f in self.filas])

    def test_no_cambia_ningun_id_canonico(self):
        # Solo superficies de filas que existen, y ninguna es un símbolo.
        locus = set(g["locus_tag"] for g in self.genes if g["locus_tag"])
        simbolos = set(g["simbolo"].lower() for g in self.genes
                       if g["simbolo"])
        for f in self.filas:
            self.assertIn(f["locus_tag"], locus)
            self.assertNotIn(f["alias"].lower(), simbolos)
            self.assertEqual(f["fuente"], A.FUENTE_PGD)

    def test_se_regenera_igual_desde_la_foto_publica(self):
        crudo = os.path.join(_RAIZ, "datos", "operones_crudo", "pgd",
                             "2026-09-27", "PAO1-operons-2021-07-19.csv")
        if not os.path.exists(crudo):
            self.skipTest("la foto de PGD no está en esta máquina (datos/ no "
                          "se versiona)")
        filas, _ = A.generar_de_pgd(crudo)
        self.assertEqual([dict(f) for f in filas],
                         [dict(f) for f in self.filas])


if __name__ == "__main__":
    unittest.main()
