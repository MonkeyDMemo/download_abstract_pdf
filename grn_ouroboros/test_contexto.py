"""El contexto de las oraciones vecinas, y el CLI del jurado del lado de
Ouroboros: `contexto`, `anotar --contexto`, gpt-oss con `razonador` y el
tope de gasto. Con una base temporal de oraciones inventadas, el motor falso
y el anotador falso de `test_cli`: ni red ni Strands.

    python -m unittest grn_ouroboros.test_contexto
"""

import csv
import io
import json
import os
import unittest

from grn_bronce import db as bdb
from grn_ouroboros import agente, anotar, cli, contexto, herramientas
from grn_ouroboros import test_anotar, test_cli
from grn_ouroboros.test_herramientas import LLAVE

# La posición de cada ítem de `test_cli.ORACIONES` en un artículo inventado.
VECINAS = {
    "m-2001": ("Una oración inventada que va antes.", None),
    "m-2002": ("Otra oración inventada, la de en medio.",
               "La última oración inventada del párrafo."),
    "m-2003": (None, "Lo que sigue, también inventado."),
}


def _base(tmp):
    """Una base con un artículo cuyas oraciones son las de la hoja y sus
    vecinas; devuelve (ruta, corrida, llave)."""
    ruta_db = os.path.join(tmp, "grn.db")
    con = bdb.conectar(ruta_db)
    con.execute("""INSERT INTO documentos (pmid, titulo, anio, extraido_en)
                   VALUES ('77', 'Un título', '2020', ?)""", (bdb.ahora(),))
    corrida = bdb.abrir_corrida(con, "1", "m", "1")
    posiciones, num = {}, 10
    for id_item, (oracion, _e1, _e2) in test_cli.ORACIONES.items():
        anterior, siguiente = VECINAS[id_item]
        # Cada ítem en su sección, separado por 10: sus vecinas no se tocan.
        for desplazamiento, texto in ((-1, anterior), (0, oracion),
                                      (1, siguiente)):
            if texto is None:
                continue
            bdb.guardar_unidad(con, corrida, {
                "pmid": "77", "fuente_texto": "xml", "seccion": "results",
                "num_oracion": num + desplazamiento, "texto": texto,
                "offset_ini": 0, "offset_fin": len(texto), "contiguo": True})
        posiciones[id_item] = num
        num += 10
    con.commit()
    con.close()
    llave = os.path.join(tmp, "llave.csv")
    with io.open(llave, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LLAVE)
        w.writeheader()
        for id_item, num in posiciones.items():
            w.writerow({"id_item": id_item, "tanda": 1, "doble": "no",
                        "pmid": "77", "fuente_texto": "xml",
                        "num_oracion": str(num), "id_par": "par-secreto",
                        "regulador": "PA0001", "blanco": "PA0002",
                        "direccion_bronce": "2>1"})
    return ruta_db, corrida, llave


class PruebasMensaje(unittest.TestCase):

    item = {"id_item": "m-1", "oracion": "GenX activates genY.",
            "entidad_1": "GenX", "entidad_2": "genY"}

    def test_sin_contexto_es_el_de_siempre(self):
        self.assertEqual(agente.mensaje(self.item),
                         "Oración:\nGenX activates genY.\n\nentidad_1: GenX\n"
                         "entidad_2: genY")

    def test_con_contexto_la_oracion_entre_sus_vecinas(self):
        item = dict(self.item, contexto={"anterior": "Antes.",
                                         "siguiente": ""})
        texto = agente.mensaje(item)
        self.assertLess(texto.index("Antes."),
                        texto.index("GenX activates genY."))
        self.assertIn("(contexto; no se anota):\n(no hay)", texto)
        self.assertTrue(texto.endswith("entidad_1: GenX\nentidad_2: genY"))

    def test_la_huella_cambia_con_el_contexto(self):
        prompt = agente.leer_prompt()
        self.assertEqual(agente.huella_prompt(prompt, "ninguna", False),
                         test_anotar.HUELLA_PRINCIPAL)
        self.assertNotEqual(agente.huella_prompt(prompt, "ninguna", True),
                            test_anotar.HUELLA_PRINCIPAL)

    def test_la_llave_cambia_con_las_vecinas(self):
        e = test_anotar._entradas()
        sin = anotar.llave_cache(self.item, e)
        con = anotar.llave_cache(dict(self.item, contexto={
            "anterior": "A.", "siguiente": ""}), e)
        otra = anotar.llave_cache(dict(self.item, contexto={
            "anterior": "B.", "siguiente": ""}), e)
        self.assertEqual(len({sin, con, otra}), 3)


class PruebasArchivo(unittest.TestCase):

    def setUp(self):
        self.tmp = test_cli.tempfile.mkdtemp()
        self.addCleanup(test_cli.shutil.rmtree, self.tmp, True)
        self.db, self.corrida, self.llave = _base(self.tmp)
        self.hoja = os.path.join(self.tmp, "hoja.csv")
        test_cli._escribir_hoja(self.hoja)
        self.items = anotar.calibracion.leer_hoja(self.hoja)
        self.recursos = herramientas.Recursos(
            ruta_llave=self.llave, ruta_db=self.db,
            corrida_bronce=self.corrida)
        self.ruta = os.path.join(self.tmp, "ctx.csv")

    def test_ida_y_vuelta(self):
        conteos = contexto.ejecutar(self.items, self.recursos, self.ruta)
        self.assertEqual(conteos, {"items": 3, "con_anterior": 2,
                                   "con_siguiente": 2})
        vecinas = contexto.para_hoja(self.items, self.ruta)
        self.assertEqual(vecinas["m-2002"],
                         {"anterior": VECINAS["m-2002"][0],
                          "siguiente": VECINAS["m-2002"][1]})
        self.assertEqual(vecinas["m-2001"]["siguiente"], "")

    def test_solo_las_vecinas_y_nada_de_la_llave(self):
        contexto.ejecutar(self.items, self.recursos, self.ruta)
        with io.open(self.ruta, encoding="utf-8-sig") as f:
            texto = f.read()
        for secreto in ("2>1", "par-secreto", "PA0001", "77,"):
            self.assertNotIn(secreto, texto)

    def test_otra_hoja_no_pasa(self):
        contexto.ejecutar(self.items, self.recursos, self.ruta)
        otra = [dict(self.items[0], oracion="Una oración distinta."),
                dict(self.items[1], id_item="m-9999")]
        with self.assertRaises(contexto.ErrorContexto) as caja:
            contexto.para_hoja(otra, self.ruta)
        mensaje = str(caja.exception)
        self.assertIn("1 ítems sin contexto y 1 con otra oración", mensaje)
        self.assertNotIn("distinta", mensaje)

    def test_la_base_de_otra_hoja_no_escribe(self):
        otra = [dict(self.items[0], oracion="Una oración distinta.")]
        with self.assertRaises(herramientas.ErrorContexto):
            contexto.ejecutar(otra, self.recursos, self.ruta)
        self.assertFalse(os.path.exists(self.ruta))


class PruebasCli(test_cli.Base):
    """`contexto` y `anotar` con lo del jurado, con el motor y el anotador
    falsos de `test_cli`."""

    def setUp(self):
        super().setUp()
        self.db, self.corrida_bronce, self.llave = _base(self.tmp)
        self.ctx = os.path.join(self.tmp, "salidas", "ouroboros", "ctx.csv")

    def contexto(self, *extra):
        return self.correr("contexto", "--hoja", self.hoja, "--llave",
                           self.llave, "--corrida-bronce",
                           str(self.corrida_bronce),
                           "--db", self.db, "--salida", self.ctx, *extra)

    def corrida(self):
        with io.open(os.path.join(self.salida, anotar.CORRIDA),
                     encoding="utf-8") as f:
            return json.load(f)

    def sin_vecinas(self, texto):
        for anterior, siguiente in VECINAS.values():
            for vecina in (anterior, siguiente):
                if vecina:
                    self.assertNotIn(vecina, texto)

    def test_contexto_escribe_y_no_imprime_oraciones(self):
        codigo, texto = self.contexto()
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertIn("Contexto de 3 ítems: 2 con oración anterior y 2 con "
                      "siguiente.", texto)
        self.assertTrue(os.path.isfile(self.ctx))
        self.sin_oraciones(texto)
        self.sin_vecinas(texto)

    def test_contexto_nunca_en_la_carpeta_del_experto(self):
        self.ctx = os.path.join(self.tmp, "salidas", "revision", "ctx.csv")
        codigo, texto = self.contexto()
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("salidas/revision", texto)
        self.assertFalse(os.path.exists(self.ctx))

    def test_anotar_con_contexto(self):
        self.assertEqual(self.contexto()[0], cli.BIEN)
        codigo, texto = self.anotar("--proveedor", "bedrock",
                                    "--contexto", self.ctx,
                                    "--prompt", agente.RUTA_PROMPT_V1)
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertIn("con contexto", texto)
        llamada = self.anotador.llamadas[1]
        self.assertEqual(llamada["contexto"],
                         {"anterior": VECINAS["m-2002"][0],
                          "siguiente": VECINAS["m-2002"][1]})
        entradas = self.corrida()["identidad"]["entradas"]
        self.assertEqual(entradas["contexto"]["plantilla"], "vecinas")
        self.assertEqual(entradas["prompt"], agente.huella_prompt(
            agente.leer_prompt(agente.RUTA_PROMPT_V1), "ninguna", True))
        self.assertEqual(self.corrida()["configuracion"]["prompt"],
                         "anotador_v1.md")
        self.sin_oraciones(texto)
        self.sin_vecinas(texto)
        # Con el mismo contexto, la segunda vez sale de la caché; sin él,
        # la carpeta no se reusa.
        codigo, texto = self.anotar("--proveedor", "bedrock",
                                    "--contexto", self.ctx,
                                    "--prompt", agente.RUTA_PROMPT_V1)
        self.assertIn("nuevos: 0, de la caché: 3", texto)
        codigo, texto = self.anotar("--proveedor", "bedrock",
                                    "--prompt", agente.RUTA_PROMPT_V1)
        self.assertEqual(codigo, cli.ENTRADA)

    def test_evals_pide_el_mismo_contexto(self):
        self.assertEqual(self.contexto()[0], cli.BIEN)
        self.assertEqual(self.anotar("--proveedor", "bedrock",
                                     "--contexto", self.ctx)[0], cli.BIEN)
        with self.assertRaises(ValueError):
            anotar.leer_corrida(self.salida)
        leida = anotar.leer_corrida(self.salida, ruta_contexto=self.ctx)
        self.assertEqual(len(leida["resultados"]), 3)

    def test_un_contexto_de_otra_hoja(self):
        self.assertEqual(self.contexto()[0], cli.BIEN)
        otra = os.path.join(self.tmp, "otra.csv")
        test_cli._escribir_hoja(otra, {"m-2001": ("Otra cosa distinta.",
                                                  "GenK", "genL")})
        codigo, texto = self.correr("anotar", "--hoja", otra, "--salida",
                                    self.salida, "--config", "principal",
                                    "--proveedor", "bedrock",
                                    "--contexto", self.ctx)
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("con otra oración", texto)
        self.assertNotIn("distinta", texto)

    def test_contexto_no_va_con_herramientas_todas(self):
        self.assertEqual(self.contexto()[0], cli.BIEN)
        codigo, texto = self.anotar("--herramientas", "todas", "--llave",
                                    self.llave, "--corrida-bronce",
                                    str(self.corrida_bronce),
                                    "--db", self.db, "--contexto", self.ctx)
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertEqual(self.fabricados, [])

    def test_gpt_oss_con_razonador(self):
        codigo, texto = self.correr(
            "anotar", "--hoja", self.hoja, "--salida", self.salida,
            "--config", "razonador", "--proveedor", "bedrock",
            "--modelo", "openai.gpt-oss-120b-1:0", "--razonamiento", "low",
            "--paralelo", "3")
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertIn("razonador (razonamiento low, T 1.0, max_tokens 4096",
                      texto)
        f = self.fabricados[0]
        self.assertEqual((f["modelo"], f["config"]["razonamiento"]),
                         ("openai.gpt-oss-120b-1:0", "low"))
        d = self.corrida()["identidad"]["entradas"]["decodificacion"]
        self.assertEqual((d["razonamiento"], d["max_tokens"]), ("low", 4096))
        # Hay precio de lista, así que se avisa la cota y queda el costo
        # (los falsos no reportan tokens: cero).
        self.assertIn("costo máximo si nada saliera de la caché", texto)
        self.assertEqual(self.corrida()["costo"]["usd_total"], 0)

    def test_lo_que_no_combina(self):
        for extra in (
                ("--config", "principal", "--proveedor", "bedrock",
                 "--modelo", "openai.gpt-oss-120b-1:0"),
                ("--config", "razonador", "--proveedor", "bedrock"),
                ("--config", "razonador"),
                ("--config", "principal", "--razonamiento", "low",
                 "--proveedor", "bedrock"),
                ("--config", "principal", "--tope-usd", "1"),
                ("--config", "principal", "--precios", "1,2"),
                ("--config", "principal", "--proveedor", "bedrock",
                 "--modelo", "qwen.qwen3-32b-v1:0", "--tope-usd", "1"),
                ("--config", "principal", "--proveedor", "bedrock",
                 "--tope-usd", "0")):
            codigo, _texto = self.correr("anotar", "--hoja", self.hoja,
                                         "--salida", self.salida, *extra)
            self.assertEqual(codigo, cli.ENTRADA, extra)
        self.assertEqual(self.fabricados, [])
        self.assertEqual(self.ollama.peticiones, [])
        self.assertFalse(os.path.exists(self.salida))

    def test_el_tope_detiene_y_retoma(self):
        for id_item in self.anotador.respuestas:
            self.anotador.respuestas[id_item] = {
                "texto": self.anotador.respuestas[id_item],
                "done_reason": "stop", "truncado": False,
                "uso": {"entrada": 3000, "salida": 400}}
        # gpt-oss-120b: cada reserva ronda 2.5 milésimas de dólar (la salida
        # entera de 4096) y cada llamada cuesta 0.69: caben dos.
        codigo, texto = self.correr(
            "anotar", "--hoja", self.hoja, "--salida", self.salida,
            "--config", "razonador", "--proveedor", "bedrock",
            "--modelo", "openai.gpt-oss-120b-1:0", "--tope-usd", "0.004")
        self.assertEqual(codigo, cli.FALLA, texto)
        self.assertIn("ALTO: Se alcanzó el tope de gasto", texto)
        self.assertEqual(self.corrida()["error"], "TopeAlcanzado")
        self.sin_oraciones(texto)
        hechas = len(self.anotador.llamadas)
        self.assertLess(hechas, 3)
        codigo, texto = self.correr(
            "anotar", "--hoja", self.hoja, "--salida", self.salida,
            "--config", "razonador", "--proveedor", "bedrock",
            "--modelo", "openai.gpt-oss-120b-1:0", "--tope-usd", "1")
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertEqual(len(self.anotador.llamadas), 3)
        costo = self.corrida()["costo"]
        self.assertAlmostEqual(costo["usd_total"],
                               3 * (3000 * 0.15 + 400 * 0.60) / 1e6)
        self.assertIn("tope de gasto: US$", texto)
        self.assertEqual(self.corrida()["configuracion"]["tope_usd"], 1.0)

    def test_el_v1_se_lee_igual(self):
        prompt = agente.leer_prompt(agente.RUTA_PROMPT_V1)
        for etiqueta in ("`fragmento`", "`motivo`", "`relacion`",
                         "`indirecta`", "`no_se`", "F11", "contexto"):
            self.assertIn(etiqueta, prompt)
        self.assertNotEqual(agente.huella_prompt(prompt),
                            test_anotar.HUELLA_PRINCIPAL)


if __name__ == "__main__":
    unittest.main()
