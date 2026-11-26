"""El lector por artículo: bloques, forma de la respuesta, comprobación de
las citas y la corrida con su caché. Con un artículo inventado, el
diccionario sintético de `test_herramientas` y un lector falso: ni base real,
ni red, ni Strands.

    python -m unittest grn_ouroboros.test_curador
"""

import io
import json
import os
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


ENTRADAS = curador.armar_entradas(
    {"proveedor": "bedrock", "modelo": "qwen.inventado-v1:0",
     "region": "us-west-2"},
    {"temperature": 0.0, "max_tokens": 8192}, curador.huella_prompt("P"))


def _respuesta(relaciones, **extra):
    r = {"texto": json.dumps({"relaciones": relaciones}),
         "done_reason": "stop", "truncado": False,
         "uso": {"entrada": 1000, "salida": 100}}
    r.update(extra)
    return r


class LectorFalso(object):
    """Contesta lo mismo a todo y cuenta las llamadas."""

    def __init__(self, relaciones=None, respuesta=None):
        self.respuesta = respuesta or _respuesta(relaciones or [])
        self.mensajes = []

    def __call__(self, texto):
        self.mensajes.append(texto)
        return dict(self.respuesta)


class PruebasInterpretar(unittest.TestCase):

    def test_el_mensaje_lleva_la_parte_y_los_identificadores(self):
        m = curador.mensaje(curador.articulo(UNIDADES), 2, 3)
        self.assertIn("parte 2 de 3", m)
        self.assertIn("[x1] The transcript measured was opeA.", m)

    def test_la_llave_cambia_con_el_mensaje_y_con_las_entradas(self):
        otras = curador.armar_entradas(
            ENTRADAS["modelo"], ENTRADAS["decodificacion"],
            curador.huella_prompt("otro prompt"))
        llaves = {curador.llave_cache("m", ENTRADAS),
                  curador.llave_cache("m2", ENTRADAS),
                  curador.llave_cache("m", otras)}
        self.assertEqual(len(llaves), 3)
        self.assertEqual(curador.llave_cache("m", ENTRADAS),
                         curador.llave_cache("m", dict(ENTRADAS)))

    def test_una_respuesta_buena(self):
        r = _relacion(["x0", "x1"], "regA", "opeA")
        self.assertEqual(curador.interpretar(_respuesta([r])),
                         ("ok", curador.validar_respuesta({"relaciones": [r]})))
        cercada = _respuesta([])
        cercada["texto"] = ("<think>veamos {</think>```json\n"
                            + json.dumps({"relaciones": [r]}) + "\n```")
        self.assertEqual(curador.interpretar(cercada)[0], "ok")
        self.assertEqual(len(curador.interpretar(cercada)[1]), 1)

    def test_lo_que_no_es_una_respuesta_no_trae_relaciones(self):
        r = _relacion(["x0"], "regA", "opeA")
        casos = [
            ("truncada", _respuesta([r], truncado=True)),
            ("contexto_excedido", _respuesta([r],
                                             motivo="contexto_excedido")),
            ("sin_json", dict(_respuesta([]), texto="No encontré nada.")),
            ("respuesta_invalida", dict(_respuesta([]),
                                        texto='{"relaciones": [{"x": 1}]}')),
            ("respuesta_invalida", dict(_respuesta([]),
                                        texto='{"otra": []}')),
        ]
        for estado, respuesta in casos:
            self.assertEqual(curador.interpretar(respuesta), (estado, []),
                             estado)

    def test_la_configuracion(self):
        self.assertEqual(curador.configuracion("lector")["temperature"], 0.0)
        c = curador.configuracion("lector_razonador", "medium")
        self.assertEqual(c["razonamiento"], "medium")
        self.assertEqual(curador.LECTOR_RAZONADOR["razonamiento"], "low")
        for argumentos in (("otra",), ("lector", "low"),
                           ("lector_razonador", "enorme")):
            with self.assertRaises(ValueError):
                curador.configuracion(*argumentos)


class PruebasEjecutar(Base):

    def setUp(self):
        super().setUp()
        self.salida = os.path.join(self.tmp, "curador")
        self.articulos = [("11", curador.articulo(UNIDADES)),
                          ("22", curador.articulo(UNIDADES[:2])),
                          ("33", [])]
        self.relaciones = [_relacion(["x0", "x1"], "regA", "opeA"),
                           _relacion(["x9"], "regA", "opeA"),
                           _relacion(["a1"], "zzzQ", "opeA")]

    def _correr(self, lector, **kw):
        return curador.ejecutar(self.articulos, self.salida, lector,
                                kw.pop("entradas", ENTRADAS), self.recursos,
                                **kw)

    def _leer(self, nombre):
        with io.open(os.path.join(self.salida, nombre),
                     encoding="utf-8") as f:
            return f.read()

    def test_escribe_las_tres_salidas(self):
        lector = LectorFalso(self.relaciones)
        r = self._correr(lector, precio=(1.0, 2.0))
        self.assertEqual(len(lector.mensajes), 2)
        self.assertEqual((r["articulos"], r["articulos_sin_texto"],
                          r["llamadas"], r["llamadas_nuevas"]), (3, 1, 2, 2))
        self.assertEqual(r["lecturas"]["ok"], 2)
        # El artículo 22 solo tiene el resumen: x0 y x1 no existen ahí.
        self.assertEqual(dict(r["relaciones_por_estado"]),
                         {"cita_inexistente": 3, "entidad_fuera_de_la_cita": 2,
                          "sin_locus": 0, "ambigua": 0, "mismo_gen": 0,
                          "valida": 1})
        self.assertEqual(r["articulos_con_relacion_valida"], 1)
        self.assertEqual(r["pares_de_locus_validos"], 1)
        self.assertAlmostEqual(r["costo"]["usd_total"],
                               2 * (1000 * 1.0 + 100 * 2.0) / 1e6)
        filas = self._leer(curador.RELACIONES).splitlines()
        self.assertEqual(filas[0].split("\t"), curador.COLUMNAS_RELACIONES)
        self.assertEqual(filas[1].split("\t"),
                         ["11", "1", "x0|x1", "regA", "opeA", "PA0001",
                          "PA0003", "activates", "no_se", "valida"])
        self.assertEqual(len(filas), 7)
        corrida = json.loads(self._leer(curador.CORRIDA))
        self.assertEqual(corrida["entradas"], json.loads(json.dumps(ENTRADAS)))
        self.assertEqual(corrida["resumen"]["relaciones"], 6)
        lecturas = [json.loads(x) for x in
                    self._leer(curador.LECTURAS).splitlines()]
        self.assertEqual([x["pmid"] for x in lecturas], ["11", "22"])
        self.assertEqual(lecturas[0]["n_oraciones"], 6)

    def test_lo_ya_leido_no_se_vuelve_a_pedir(self):
        self._correr(LectorFalso(self.relaciones))
        antes = self._leer(curador.RELACIONES)
        otro = LectorFalso([])
        r = self._correr(otro)
        self.assertEqual(otro.mensajes, [])
        self.assertEqual(r["llamadas_nuevas"], 0)
        self.assertEqual(self._leer(curador.RELACIONES), antes)

    def test_un_renglon_cortado_se_vuelve_a_leer(self):
        self._correr(LectorFalso(self.relaciones))
        ruta = os.path.join(self.salida, curador.LECTURAS)
        with open(ruta, "rb") as f:
            contenido = f.read()
        with open(ruta, "wb") as f:
            f.write(contenido[:-40])
        lector = LectorFalso(self.relaciones)
        self._correr(lector)
        self.assertEqual(len(lector.mensajes), 1)
        self.assertEqual(len(curador.leer_lecturas(ruta)), 2)

    def test_otra_corrida_no_cabe_en_la_misma_carpeta(self):
        self._correr(LectorFalso([]))
        otras = curador.armar_entradas(
            ENTRADAS["modelo"], ENTRADAS["decodificacion"],
            curador.huella_prompt("otro prompt"))
        with self.assertRaises(curador.CarpetaOcupada):
            self._correr(LectorFalso([]), entradas=otras)

    def test_si_el_lector_falla_la_corrida_se_detiene_y_se_retoma(self):
        class Falla(LectorFalso):
            def __call__(self, texto):
                if len(self.mensajes) == 1:
                    raise RuntimeError("sin red")
                return super().__call__(texto)

        with self.assertRaises(RuntimeError):
            self._correr(Falla(self.relaciones))
        self.assertFalse(os.path.exists(
            os.path.join(self.salida, curador.CORRIDA)))
        lector = LectorFalso(self.relaciones)
        r = self._correr(lector)
        self.assertEqual(len(lector.mensajes), 1)
        self.assertEqual(r["llamadas_nuevas"], 1)

    def test_en_paralelo_sale_lo_mismo(self):
        self._correr(LectorFalso(self.relaciones))
        en_serie = self._leer(curador.RELACIONES)
        self.salida = os.path.join(self.tmp, "curador_paralelo")
        self._correr(LectorFalso(self.relaciones), paralelo=4)
        self.assertEqual(self._leer(curador.RELACIONES), en_serie)

    def test_una_lectura_que_no_sirve_se_cuenta(self):
        r = self._correr(LectorFalso(respuesta=_respuesta(
            self.relaciones, truncado=True)))
        self.assertEqual(r["lecturas"]["truncada"], 2)
        self.assertEqual(r["relaciones"], 0)

    def test_un_articulo_largo_va_en_varias_llamadas(self):
        lector = LectorFalso([])
        r = self._correr(lector, max_caracteres=120)
        self.assertGreater(r["llamadas"], 2)
        self.assertEqual(len(lector.mensajes), r["llamadas"])
        self.assertTrue(any("parte 2 de" in m for m in lector.mensajes))

    def test_la_salida_no_cae_en_la_carpeta_del_experto(self):
        self.salida = os.path.join(self.tmp, "salidas", "revision", "x")
        with self.assertRaises(ValueError):
            self._correr(LectorFalso([]))


if __name__ == "__main__":
    unittest.main()
