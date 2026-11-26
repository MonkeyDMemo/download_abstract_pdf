"""El lector por artículo, fase 0: bloques, forma de la respuesta y
comprobación de las citas. Con un artículo inventado y el diccionario
sintético de `test_herramientas`: ni base real, ni red, ni Strands.

    python -m unittest grn_ouroboros.test_curador
"""

import json
import unittest

from grn_bronce import db as bdb
from grn_ouroboros import curador
from grn_ouroboros.test_herramientas import Base

UNIDADES = [
    ("abstract", "", 0, "RegA controls efflux in this invented organism."),
    ("abstract", "", 1, "We studied the opeA gene."),
    ("xml", "results", 0, "Deletion of regA lowered the transcript."),
    ("xml", "results", 1, "The transcript measured was opeA."),
    ("xml", "results", 2, "The tag gene did not change."),
    ("xml", "discussion", 3, "A regulator named zzzQ may act on opeB."),
]


def _relacion(citas, regulador, blanco, efecto="activates", tipo="no_se"):
    return {"oraciones": list(citas), "regulador": regulador,
            "blanco": blanco, "efecto": efecto, "tipo": tipo}


class PruebasArticulo(unittest.TestCase):

    def setUp(self):
        self.oraciones = curador.articulo(UNIDADES)

    def test_el_identificador_lleva_la_fuente_y_el_numero(self):
        self.assertEqual([o.id for o in self.oraciones],
                         ["a0", "a1", "x0", "x1", "x2", "x3"])
        self.assertEqual(curador.identificador("pdf", "45"), "p45")

    def test_las_secciones_que_el_bronce_excluye_no_se_leen(self):
        unidades = UNIDADES + [("xml", "excluir", 4, "Strains and primers.")]
        self.assertEqual(curador.articulo(unidades), self.oraciones)
        todas = curador.articulo(unidades, fuera=())
        self.assertEqual(todas[-1].id, "x4")

    def test_una_fuente_desconocida_es_un_error(self):
        with self.assertRaises(ValueError):
            curador.identificador("ocr", 1)

    def test_lee_de_la_base_en_orden_de_lectura(self):
        con = bdb.conectar(":memory:")
        self.addCleanup(con.close)
        con.execute("""INSERT INTO documentos (pmid, titulo, anio,
                       extraido_en) VALUES ('7', 'T', '2020', ?)""",
                    (bdb.ahora(),))
        corrida = bdb.abrir_corrida(con, "1", "m", "1")
        for fuente, seccion, num, texto in reversed(UNIDADES):
            bdb.guardar_unidad(con, corrida, {
                "pmid": "7", "fuente_texto": fuente, "seccion": seccion,
                "num_oracion": num, "texto": texto, "offset_ini": 0,
                "offset_fin": len(texto)})
        self.assertEqual(curador.leer_articulo(con, corrida, "7"),
                         self.oraciones)
        self.assertEqual(curador.leer_articulo(con, corrida, "8"), [])

    def test_un_articulo_que_cabe_va_en_un_bloque(self):
        self.assertEqual(curador.bloques(self.oraciones), [self.oraciones])

    def test_los_bloques_no_parten_una_seccion_que_cabe(self):
        # El resumen cabe solo; «results» cabe solo; juntos no.
        tope = sum(curador._largo(o) for o in self.oraciones[2:5])
        partes = curador.bloques(self.oraciones, tope)
        self.assertEqual([[o.id for o in b] for b in partes],
                         [["a0", "a1"], ["x0", "x1", "x2"], ["x3"]])

    def test_una_seccion_que_no_cabe_se_parte_entre_oraciones(self):
        partes = curador.bloques(self.oraciones, 60)
        self.assertEqual([o for b in partes for o in b], self.oraciones,
                         "cada oración una vez y en orden")
        self.assertTrue(all(len(b) == 1 for b in partes))

    def test_el_texto_lleva_identificadores_y_encabezados(self):
        texto = curador.texto_bloque(self.oraciones)
        self.assertTrue(texto.startswith("## RESUMEN\n[a0] RegA controls"))
        self.assertIn("\n\n## results\n[x0] Deletion of regA", texto)
        self.assertIn("\n\n## discussion\n[x3] ", texto)
        self.assertEqual(texto.count("## "), 3)
        self.assertEqual(len(curador.huella_bloque(self.oraciones)), 16)


class PruebasRespuesta(unittest.TestCase):

    def test_el_esquema_es_json_y_pide_las_citas_primero(self):
        esquema = json.loads(json.dumps(curador.esquema()))
        item = esquema["properties"]["relaciones"]["items"]
        self.assertEqual(list(curador.esquema()["properties"]["relaciones"]
                              ["items"]["properties"])[0], "oraciones")
        self.assertEqual(item["properties"]["efecto"]["enum"],
                         ["activates", "represses", "regulates"])
        self.assertEqual(item["properties"]["tipo"]["enum"],
                         ["directa", "indirecta", "no_se"])

    def test_limpia_y_no_repite(self):
        r = _relacion(["[x0]", "x1"], " regA ", "opeA")
        igual = _relacion(["x1", "x0"], "regA", "opeA")
        salida = curador.validar_respuesta({"relaciones": [r, igual]})
        self.assertEqual(len(salida), 1)
        self.assertEqual(salida[0]["oraciones"], ["x0", "x1"])
        self.assertEqual(salida[0]["regulador"], "regA")

    def test_sin_relaciones_es_una_respuesta_valida(self):
        self.assertEqual(curador.validar_respuesta({"relaciones": []}), [])

    def test_rechaza_lo_que_no_tiene_la_forma(self):
        malas = [
            [],
            {"relaciones": [], "nota": "x"},
            {"relaciones": "ninguna"},
            {"relaciones": [_relacion([], "regA", "opeA")]},
            {"relaciones": [_relacion(["x0", "x0"], "regA", "opeA")]},
            {"relaciones": [_relacion(["x0", "x1", "x2", "x3"], "regA",
                                      "opeA")]},
            {"relaciones": [_relacion(["x0"], "", "opeA")]},
            {"relaciones": [_relacion(["x0"], "regA", "opeA",
                                      efecto="induces")]},
            {"relaciones": [_relacion(["x0"], "regA", "opeA", tipo="?")]},
            {"relaciones": [dict(_relacion(["x0"], "regA", "opeA"),
                                 motivo="porque sí")]},
        ]
        for mala in malas:
            with self.assertRaises(curador.RespuestaInvalida, msg=mala):
                curador.validar_respuesta(mala)


class PruebasVerificar(Base):

    def setUp(self):
        super(PruebasVerificar, self).setUp()
        self.bloque = curador.articulo(UNIDADES)

    def estado(self, *args, **kwargs):
        return curador.verificar(_relacion(*args, **kwargs), self.bloque,
                                 self.recursos)

    def test_una_relacion_repartida_en_dos_oraciones_es_valida(self):
        v = self.estado(["x0", "x1"], "regA", "opeA")
        self.assertEqual(v["estado"], "valida")
        self.assertEqual((v["locus_regulador"], v["locus_blanco"]),
                         ("PA0001", "PA0003"))

    def test_el_gen_y_su_proteina_son_el_mismo_nombre(self):
        self.assertEqual(self.estado(["a0", "a1"], "regA", "OPEA")["estado"],
                         "valida")

    def test_una_cita_que_no_esta_en_el_bloque(self):
        self.assertEqual(self.estado(["x9"], "regA", "opeA")["estado"],
                         "cita_inexistente")

    def test_un_nombre_que_no_esta_en_lo_citado(self):
        v = self.estado(["x0"], "regA", "opeA")
        self.assertEqual(v["estado"], "entidad_fuera_de_la_cita")
        self.assertEqual(v["locus_blanco"], "")

    def test_el_nombre_tiene_que_ser_una_palabra_entera(self):
        # «tag» no es «tagged», y «opeA» no es «opeAB».
        bloque = curador.articulo([
            ("xml", "r", 0, "RegA tagged the opeAB operon.")])
        v = curador.verificar(_relacion(["x0"], "regA", "tag"), bloque,
                              self.recursos)
        self.assertEqual(v["estado"], "entidad_fuera_de_la_cita")

    def test_un_nombre_que_el_diccionario_no_conoce(self):
        self.assertEqual(self.estado(["x3"], "zzzQ", "opeB")["estado"],
                         "sin_locus")

    def test_un_nombre_con_dos_locus_es_ambiguo(self):
        bloque = curador.articulo([("xml", "r", 0, "RegA represses dup.")])
        v = curador.verificar(_relacion(["x0"], "regA", "dup"), bloque,
                              self.recursos)
        self.assertEqual(v["estado"], "ambigua")

    def test_el_mismo_gen_no_es_una_arista(self):
        bloque = curador.articulo([
            ("xml", "r", 0, "RegA binds the PA0001 promoter.")])
        v = curador.verificar(_relacion(["x0"], "RegA", "PA0001"), bloque,
                              self.recursos)
        self.assertEqual(v["estado"], "mismo_gen")

    def test_los_conteos_traen_todos_los_estados(self):
        c = curador.conteos([self.estado(["x0", "x1"], "regA", "opeA"),
                             self.estado(["x9"], "regA", "opeA")])
        self.assertEqual(list(c), list(curador.ESTADOS))
        self.assertEqual((c["valida"], c["cita_inexistente"], c["ambigua"]),
                         (1, 1, 0))


if __name__ == "__main__":
    unittest.main()
