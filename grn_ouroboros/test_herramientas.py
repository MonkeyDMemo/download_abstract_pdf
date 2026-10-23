"""Las cinco herramientas, una por una, sobre recursos sintéticos: un
diccionario y un catálogo de pocas filas, una base temporal y una llave
inventada. La última clase mira el diccionario versionado del proyecto, que
es público.

Las pruebas que arman los `@tool` de Strands se saltan donde no está.

    python -m unittest grn_ouroboros.test_herramientas
"""

import csv
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest

from grn_bronce import db as bdb
from grn_ouroboros import herramientas as H

TIENE_STRANDS = importlib.util.find_spec("strands") is not None

GENES = [
    # locus, símbolo, alias, tipo, producto, es_tf, fuente_tf, fuente, sensible
    ("PA0001", "regA", "RegA|PA0001", "protein_coding",
     "transcriptional regulator RegA", "true", "go", "refseq|kegg", "false"),
    ("PA0002", "tag", "PA0002", "protein_coding", "glycosidase", "false", "",
     "refseq|kegg", "true"),
    ("PA0003", "opeA", "PA0003|dup", "protein_coding", "efflux protein A",
     "false", "", "refseq", "false"),
    ("PA0004", "opeB", "PA0004|dup", "protein_coding", "efflux protein B",
     "false", "", "refseq", "false"),
    ("", "CPX", "cpx", "complejo", "TF: justificación de quien firmó.",
     "true", "manual", "manual", "true"),
]
OPERONES = [
    ("opeAB", "opeA|opeB", "PA0003|PA0004", "refseq_adyacencia"),
    ("opeAB-tag", "opeA|opeB|tag", "PA0003|PA0004|PA0002",
     "refseq_adyacencia"),
]
LLAVE = ["id_item", "tanda", "doble", "pmid", "fuente_texto", "num_oracion",
         "id_par", "regulador", "blanco", "direccion_bronce"]


def _tsv(ruta, encabezado, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(encabezado) + "\n")
        for fila in filas:
            f.write("\t".join(fila) + "\n")


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.genes = os.path.join(self.tmp, "genes_pao1.tsv")
        self.operones = os.path.join(self.tmp, "operones_pao1.tsv")
        _tsv(self.genes, H.COLUMNAS_GENES, GENES)
        _tsv(self.operones, ["operon", "miembros", "locus_tags", "fuente"],
             OPERONES)
        self.recursos = H.Recursos(self.genes, self.operones)


class PruebasBuscarLocus(Base):

    def test_simbolo_y_alias_sin_distinguir_mayusculas(self):
        for nombre in ("regA", "RegA", "REGA", "PA0001"):
            r = H.buscar_locus(nombre, self.recursos)
            self.assertEqual(r["coincidencias"],
                             [{"locus_tag": "PA0001", "simbolo": "regA"}],
                             nombre)
            self.assertFalse(r["ambiguo"])

    def test_una_fila_sensible_exige_su_escritura(self):
        """`tag` es un gen y «TAG» o «Tag» son otra cosa: la defensa de
        `sensible_mayusculas`, no una lista negra."""
        self.assertEqual(
            H.buscar_locus("tag", self.recursos)["coincidencias"][0]
            ["locus_tag"], "PA0002")
        for nombre in ("TAG", "Tag"):
            r = H.buscar_locus(nombre, self.recursos)
            self.assertEqual(r["coincidencias"], [], nombre)
            self.assertIn("nota", r)

    def test_un_nombre_de_dos_filas_es_ambiguo(self):
        r = H.buscar_locus("dup", self.recursos)
        self.assertTrue(r["ambiguo"])
        self.assertEqual([c["locus_tag"] for c in r["coincidencias"]],
                         ["PA0003", "PA0004"])

    def test_vacio_o_desconocido(self):
        for nombre in ("", "   ", None, "lacZ"):
            self.assertEqual(
                H.buscar_locus(nombre, self.recursos)["coincidencias"], [])

    def test_es_pura(self):
        a = H.buscar_locus("dup", self.recursos)
        H.buscar_locus("regA", self.recursos)
        self.assertEqual(H.buscar_locus("dup", self.recursos), a)


class PruebasEsTf(Base):

    def test_por_locus_y_por_nombre(self):
        self.assertEqual(H.es_tf("PA0001", self.recursos)["resultados"],
                         [{"locus_tag": "PA0001", "simbolo": "regA",
                           "es_tf": True}])
        self.assertFalse(
            H.es_tf("opeA", self.recursos)["resultados"][0]["es_tf"])

    def test_una_entrada_sin_locus(self):
        r = H.es_tf("CPX", self.recursos)["resultados"]
        self.assertEqual(r, [{"locus_tag": "", "simbolo": "CPX",
                              "es_tf": True}])

    def test_desconocido(self):
        self.assertEqual(H.es_tf("PA9999", self.recursos)["resultados"], [])


class PruebasOperonDe(Base):

    def test_todos_los_operones_que_lo_contienen(self):
        r = H.operon_de("PA0003", self.recursos)
        operones = r["resultados"][0]["operones"]
        self.assertEqual([o["operon"] for o in operones],
                         ["opeAB", "opeAB-tag"])
        self.assertEqual(operones[0]["locus_tags"], ["PA0003", "PA0004"])
        self.assertIn("adyacencia", r["nota"])

    def test_un_gen_fuera_de_todo_operon(self):
        r = H.operon_de("regA", self.recursos)
        self.assertEqual(r["resultados"][0]["operones"], [])

    def test_sin_locus_no_hay_operon(self):
        self.assertEqual(
            H.operon_de("CPX", self.recursos)["resultados"][0]["operones"],
            [])


class PruebasFuncionAnotada(Base):

    def test_el_producto_de_refseq(self):
        self.assertEqual(
            H.funcion_anotada("PA0004", self.recursos)["resultados"],
            [{"locus_tag": "PA0004", "simbolo": "opeB",
              "producto": "efflux protein B"}])

    def test_la_justificacion_de_una_entrada_manual_no_sale(self):
        r = H.funcion_anotada("CPX", self.recursos)["resultados"]
        self.assertEqual(r[0]["producto"], "")


class PruebasContexto(Base):

    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.tmp, "grn.db")
        con = bdb.conectar(self.db)
        con.execute(
            """INSERT INTO documentos (pmid, titulo, anio, extraido_en)
               VALUES ('77', 'Un título', '2020', ?)""", (bdb.ahora(),))
        self.corrida = bdb.abrir_corrida(con, "1", "m", "1")
        for num, texto in ((4, "Antes viene esto."),
                           (5, "GenX activates genY."),
                           (6, "Después viene aquello.")):
            bdb.guardar_unidad(con, self.corrida, {
                "pmid": "77", "fuente_texto": "xml", "seccion": "results",
                "num_oracion": num, "texto": texto, "offset_ini": 0,
                "offset_fin": len(texto), "contiguo": True})
        con.commit()
        con.close()
        self.llave = os.path.join(self.tmp, "llave.csv")
        with io.open(self.llave, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LLAVE)
            w.writeheader()
            w.writerow({"id_item": "m-1001", "tanda": 1, "doble": "no",
                        "pmid": "77", "fuente_texto": "xml",
                        "num_oracion": "5", "id_par": "par-secreto",
                        "regulador": "PA0001", "blanco": "PA0002",
                        "direccion_bronce": "2>1"})
        self.recursos = H.Recursos(self.genes, self.operones,
                                   ruta_llave=self.llave, ruta_db=self.db,
                                   corrida_bronce=self.corrida)
        self.item = {"id_item": "m-1001", "oracion": "GenX  activates genY.",
                     "entidad_1": "GenX", "entidad_2": "genY"}

    def test_las_dos_vecinas_y_nada_mas(self):
        r = H.contexto("m-1001", self.recursos)
        self.assertEqual(r, {"anterior": "Antes viene esto.",
                             "siguiente": "Después viene aquello."})
        texto = json.dumps(r)
        for secreto in ("2>1", "par-secreto", "77", "PA0001"):
            self.assertNotIn(secreto, texto)

    def test_la_llave_solo_guarda_la_posicion(self):
        self.assertEqual(self.recursos.posiciones,
                         {"m-1001": ("77", "xml", "5")})

    def test_un_item_que_no_esta_en_la_llave(self):
        self.assertIn("error", H.contexto("m-9999", self.recursos))

    def test_verificar_acepta_la_hoja_de_esta_llave(self):
        """Con los espacios normalizados, como compara el sorteo."""
        self.assertEqual(self.recursos.verificar_contexto([self.item]), 1)

    def test_verificar_rechaza_otra_oracion_sin_decirla(self):
        otro = dict(self.item, oracion="Una oración distinta.")
        with self.assertRaises(H.ErrorContexto) as caja:
            self.recursos.verificar_contexto([otro, dict(otro,
                                                         id_item="m-2")])
        mensaje = str(caja.exception)
        self.assertIn("1 ítems sin llave", mensaje)
        self.assertIn("1 con otra oración", mensaje)
        self.assertNotIn("distinta", mensaje)

    def test_sin_base_no_hay_contexto(self):
        sin_base = H.Recursos(self.genes, self.operones,
                              ruta_llave=self.llave)
        with self.assertRaises(H.ErrorContexto):
            H.contexto("m-1001", sin_base)


class PruebasHuellas(Base):

    def test_cada_modo_mide_lo_que_lee(self):
        self.assertEqual(self.recursos.huellas("ninguna"), {})
        self.assertEqual(list(self.recursos.huellas("buscar_locus")),
                         ["genes_pao1.tsv"])
        todas = H.Recursos(self.genes, self.operones, ruta_llave=self.genes,
                           corrida_bronce=4).huellas("todas")
        self.assertEqual(sorted(todas), ["corrida_bronce", "genes_pao1.tsv",
                                         "llave", "operones_pao1.tsv"])
        self.assertEqual(todas["corrida_bronce"], 4)

    def test_otro_diccionario_otra_huella(self):
        antes = self.recursos.huellas("buscar_locus")
        with io.open(self.genes, "a", encoding="utf-8") as f:
            f.write("PA0005\tnuevo\tPA0005\tprotein_coding\tx\tfalse\t\t"
                    "refseq\tfalse\n")
        self.assertNotEqual(H.Recursos(self.genes).huellas("buscar_locus"),
                            antes)

    def test_un_modo_desconocido(self):
        with self.assertRaises(ValueError):
            self.recursos.huellas("algunas")


class PruebasDiccionarioDelProyecto(unittest.TestCase):
    """El `genes_pao1.tsv` versionado, que es público."""

    def setUp(self):
        self.recursos = H.Recursos()

    def test_lasR_y_la_forma_de_proteina(self):
        for nombre in ("lasR", "LasR"):
            r = H.buscar_locus(nombre, self.recursos)["coincidencias"]
            self.assertEqual([c["locus_tag"] for c in r], ["PA1430"])

    def test_fur_es_sensible_y_tiene_su_alias(self):
        self.assertEqual(
            [c["locus_tag"] for c in H.buscar_locus(
                "Fur", self.recursos)["coincidencias"]], ["PA4764"])
        self.assertEqual(
            H.buscar_locus("FUR", self.recursos)["coincidencias"], [])

    def test_rhlA_esta_en_rhlAB(self):
        operones = H.operon_de("rhlA", self.recursos)["resultados"][0][
            "operones"]
        self.assertIn("rhlAB", [o["operon"] for o in operones])


@unittest.skipUnless(TIENE_STRANDS, "strands no está instalado: es del "
                                    ".venv-ouroboros del servidor")
class PruebasParaStrands(Base):

    def test_ninguna_no_arma_nada(self):
        self.assertEqual(H.para_strands(self.recursos, "ninguna", {}, []), [])

    def test_los_nombres_y_la_trayectoria(self):
        registro = []
        item = {"id_item": "m-1"}
        uno = H.para_strands(self.recursos, "buscar_locus", item, registro)
        self.assertEqual([t.tool_name for t in uno], ["buscar_locus"])
        todas = H.para_strands(self.recursos, "todas", item, registro)
        self.assertEqual([t.tool_name for t in todas], list(H.TODAS))
        uno[0](nombre="regA")
        self.assertEqual(registro[0]["herramienta"], "buscar_locus")
        self.assertEqual(registro[0]["entrada"], {"nombre": "regA"})

    def test_el_tope_de_consultas(self):
        registro = []
        (buscar,) = H.para_strands(self.recursos, "buscar_locus", {},
                                   registro, maximo=2)
        for _ in range(3):
            salida = buscar(nombre="regA")
        self.assertIn("error", salida)
        self.assertEqual(len(registro), 3)


if __name__ == "__main__":
    unittest.main()
