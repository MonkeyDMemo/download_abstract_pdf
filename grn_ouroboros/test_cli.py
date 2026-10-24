"""El CLI con un motor falso y un anotador falso: ni red ni Strands.

El motor falso es el Ollama de `test_motor`, puesto en lugar del abridor de
URL de `motor`; el anotador falso, el de `test_anotar`, puesto en lugar de
`agente.crear_anotador`. Las oraciones son inventadas, y se comprueba que
ninguna llegue a la terminal.

    python -m unittest grn_ouroboros.test_cli
"""

import contextlib
import csv
import importlib.util
import io
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from grn_ouroboros import (agente, anotar, calibracion, cli, evals, motor,
                           rubrica, test_anotar, test_motor)

TIENE_EVALS = importlib.util.find_spec("strands_evals") is not None

ORACIONES = {
    "m-2001": ("GenK activates genL in this invented sentence.", "GenK",
               "genL"),
    "m-2002": ("No effect of GenM on genN was seen here.", "GenM", "genN"),
    "m-2003": ("GenP represses genQ, we say on purpose.", "GenP", "genQ"),
}
RESPUESTAS = {
    "m-2001": test_anotar._json("GenK activates genL"),
    "m-2002": test_anotar._json("No effect of GenM on genN", relacion="no",
                                direccion="ninguna", signo="", tipo="",
                                negada="si"),
    "m-2003": test_anotar._json("GenP represses genQ", signo="-"),
}


def _escribir_hoja(ruta, oraciones=ORACIONES, **valores):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rubrica.COLUMNAS_HOJA)
        w.writeheader()
        for id_item, (oracion, e1, e2) in oraciones.items():
            w.writerow(dict(valores, id_item=id_item, oracion=oracion,
                            entidad_1=e1, entidad_2=e2))


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hoja = os.path.join(self.tmp, "hoja.csv")
        _escribir_hoja(self.hoja)
        self.salida = os.path.join(self.tmp, "salidas", "ouroboros", "t1")
        self.ollama = test_motor.OllamaFalso()
        parche = mock.patch.object(motor, "_ABRIDOR",
                                   types.SimpleNamespace(open=self.ollama))
        parche.start()
        self.addCleanup(parche.stop)
        self.anotador = test_anotar.AnotadorFalso(dict(RESPUESTAS))
        self.fabricados = []

        def fabrica(config, prompt, host=None, herramientas=None,
                    recursos=None):
            self.fabricados.append({"config": config, "host": host,
                                    "herramientas": herramientas,
                                    "recursos": recursos})
            return self.anotador

        parche = mock.patch.object(agente, "crear_anotador", fabrica)
        parche.start()
        self.addCleanup(parche.stop)
        # La variable de la caché KV del entorno de quien corre no entra.
        parche = mock.patch.dict(os.environ)
        parche.start()
        self.addCleanup(parche.stop)
        os.environ.pop(cli.VARIABLE_KV, None)

    def correr(self, *argv):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cli.main(list(argv))
        return codigo, salida.getvalue()

    def anotar(self, *extra):
        return self.correr("anotar", "--hoja", self.hoja, "--salida",
                           self.salida, "--config", "principal", *extra)

    def sin_oraciones(self, texto):
        for oracion, _e1, _e2 in ORACIONES.values():
            self.assertNotIn(oracion, texto)


class PruebasHumo(Base):

    def test_el_pre_registrado_sin_razonamiento(self):
        codigo, texto = self.correr("humo")
        self.assertEqual(codigo, cli.BIEN)
        self.assertIn("Ollama 0.12.6", texto)
        self.assertIn("digest 500a1f067a9f", texto)
        self.assertIn("cuantización Q4_K_M", texto)
        self.assertIn("Es el pre-registrado", texto)
        self.assertIn("think = false: sin razonamiento", texto)

    def test_con_razonamiento_falla(self):
        self.ollama.rutas["/api/chat"] = {
            "message": {"role": "assistant", "content": "listo",
                        "thinking": "Primero pienso."},
            "done_reason": "stop"}
        codigo, texto = self.correr("humo")
        self.assertEqual(codigo, cli.FALLA)
        self.assertIn("TRAE RAZONAMIENTO", texto)

    def test_otro_digest_falla(self):
        self.ollama.rutas["/api/tags"]["models"][1]["digest"] = "abc" * 20
        codigo, texto = self.correr("humo")
        self.assertEqual(codigo, cli.FALLA)
        self.assertIn("NO ES EL PRE-REGISTRADO", texto)

    def test_sin_ollama(self):
        self.ollama.fallar["/api/version"] = OSError("rechazada")
        codigo, texto = self.correr("humo")
        self.assertEqual(codigo, cli.FALLA)
        self.assertIn("ERROR", texto)


class PruebasAnotar(Base):

    def test_anota_la_hoja(self):
        codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertIn("Listo: 3 ítems, 3 válidos y 0 abstenciones.", texto)
        self.assertEqual(len(self.anotador.llamadas), 3)
        self.assertEqual(self.fabricados[0]["config"]["nombre"], "principal")
        self.assertEqual(self.fabricados[0]["herramientas"], "ninguna")
        self.assertIsNone(self.fabricados[0]["recursos"])
        filas = calibracion.leer_anotaciones(
            os.path.join(self.salida, anotar.ANOTACIONES))
        self.assertEqual(filas["m-2003"]["signo"], "-")
        self.sin_oraciones(texto)

    def test_antes_de_anotar_exige_el_modelo(self):
        self.ollama.rutas["/api/show"]["details"]["quantization_level"] = (
            "Q8_0")
        codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.FALLA)
        self.assertIn("Q8_0", texto)
        self.assertEqual(self.fabricados, [])
        self.assertEqual(self.anotador.llamadas, [])
        self.assertFalse(os.path.exists(self.salida))

    def test_otro_digest_tambien_detiene(self):
        self.ollama.rutas["/api/tags"]["models"][1]["digest"] = "f" * 64
        codigo, _texto = self.anotar()
        self.assertEqual(codigo, cli.FALLA)
        self.assertEqual(self.anotador.llamadas, [])

    def test_nunca_en_la_carpeta_del_experto(self):
        prohibida = os.path.join(self.tmp, "salidas", "revision",
                                 "muestra200", "ouro")
        codigo, texto = self.correr("anotar", "--hoja", self.hoja,
                                    "--salida", prohibida, "--config",
                                    "principal")
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("salidas/ouroboros/", texto)
        self.assertIn("el experto no las ve", texto)
        # Se rechaza antes de hablar con Ollama y antes de crear nada.
        self.assertEqual(self.ollama.peticiones, [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "salidas",
                                                     "revision")))

    def test_ni_por_una_ruta_que_resuelve_ahi(self):
        vuelta = os.path.join(self.tmp, "salidas", "ouroboros", "..",
                              "revision", "x")
        codigo, _texto = self.correr("anotar", "--hoja", self.hoja,
                                     "--salida", vuelta, "--config",
                                     "con_think")
        self.assertEqual(codigo, cli.ENTRADA)

    def test_num_ctx_y_cache_kv_quedan_en_la_corrida(self):
        codigo, texto = self.correr(
            "anotar", "--hoja", self.hoja, "--salida", self.salida,
            "--config", "con_think", "--num-ctx", "6144", "--kv-cache",
            "q8_0", "--semilla", "7")
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertIn("caché KV q8_0", texto)
        with io.open(os.path.join(self.salida, anotar.CORRIDA),
                     encoding="utf-8") as f:
            corrida = json.load(f)
        decodificacion = corrida["identidad"]["entradas"]["decodificacion"]
        self.assertEqual((decodificacion["num_ctx"], decodificacion["seed"],
                          decodificacion["kv_cache"], decodificacion["think"]),
                         (6144, 7, "q8_0", True))
        self.assertEqual(corrida["configuracion"]["prompt"],
                         os.path.basename(agente.RUTA_PROMPT))

    def test_las_herramientas_el_prompt_y_el_digest_entran_a_la_llave(self):
        """Lo que se pide por la línea de comandos llega a las entradas de
        la caché tal cual: unas herramientas o un prompt que no entraran
        harían que otra corrida reusara estos veredictos."""
        prompt = os.path.join(self.tmp, "otro_prompt.md")
        with io.open(prompt, "w", encoding="utf-8") as f:
            f.write("Prompt inventado para la prueba.\n")
        codigo, texto = self.anotar("--herramientas", "buscar_locus",
                                    "--prompt", prompt)
        self.assertEqual(codigo, cli.BIEN, texto)
        with io.open(os.path.join(self.salida, anotar.CORRIDA),
                     encoding="utf-8") as f:
            entradas = json.load(f)["identidad"]["entradas"]
        self.assertEqual(entradas["herramientas"], "buscar_locus")
        self.assertIn("genes_pao1.tsv", entradas["recursos"])
        self.assertEqual(entradas["prompt"], agente.huella_prompt(
            agente.leer_prompt(prompt), "buscar_locus"))
        self.assertEqual(entradas["modelo"]["digest"], test_motor.DIGEST)
        self.assertEqual(self.fabricados[0]["herramientas"], "buscar_locus")

    def test_la_cache_kv_del_entorno(self):
        os.environ[cli.VARIABLE_KV] = "q8_0"
        _codigo, texto = self.anotar()
        self.assertIn("caché KV q8_0", texto)

    def test_la_misma_carpeta_con_otra_semilla(self):
        self.assertEqual(self.anotar()[0], cli.BIEN)
        codigo, texto = self.anotar("--semilla", "43")
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("usa otra carpeta", texto)

    def test_la_segunda_vez_sale_de_la_cache(self):
        self.anotar()
        self.anotador.llamadas = []
        codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.BIEN)
        self.assertEqual(self.anotador.llamadas, [])
        self.assertIn("nuevos: 0, de la caché: 3", texto)

    def test_una_hoja_ya_anotada(self):
        _escribir_hoja(self.hoja, relacion="si")
        codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("sin anotar", texto)
        self.assertEqual(self.ollama.peticiones, [])

    def test_todas_sin_llave(self):
        codigo, texto = self.anotar("--herramientas", "todas")
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("--llave", texto)

    def test_un_host_que_no_es_local(self):
        codigo, _texto = self.anotar("--host", "http://10.0.0.2:11500")
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertEqual(self.ollama.peticiones, [])

    def test_sin_strands(self):
        def sin_strands(*_a, **_k):
            raise ImportError("No module named 'strands'")

        with mock.patch.object(agente, "crear_anotador", sin_strands):
            codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn(".venv-ouroboros", texto)

    def test_un_error_del_anotador_no_imprime_su_mensaje(self):
        oracion = ORACIONES["m-2002"][0]
        self.anotador.respuestas["m-2002"] = RuntimeError(
            "la petición llevaba: %s" % oracion)
        codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.FALLA)
        self.assertIn("RuntimeError", texto)
        self.sin_oraciones(texto)

    def test_interrumpida(self):
        falso = self.anotador

        def interrumpe(item):
            # KeyboardInterrupt no es Exception: el falso la devolvería.
            if item["id_item"] == "m-2002":
                raise KeyboardInterrupt
            return falso(item)

        self.anotador = interrumpe
        codigo, texto = self.anotar()
        self.assertEqual(codigo, cli.INTERRUMPIDA)
        self.assertIn(anotar.VEREDICTOS, texto)
        # Lo hecho queda, y volver a correr retoma solo lo que falta.
        self.anotador = falso
        falso.llamadas = []
        self.assertEqual(self.anotar()[0], cli.BIEN)
        self.assertEqual([it["id_item"] for it in falso.llamadas],
                         ["m-2002", "m-2003"])


class PruebasCalibracion(Base):

    def anotacion(self, cambios=None):
        """La llave misma como anotación, con los cambios que se pidan."""
        llave = calibracion.leer_llave()
        items = calibracion.leer_hoja(calibracion.RUTA_HOJA)
        ruta = os.path.join(self.tmp, "anotaciones.csv")
        with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rubrica.COLUMNAS_HOJA)
            w.writeheader()
            for item in items:
                fila = dict(item, comentario="")
                fila.update(calibracion.valores_de(llave[item["id_item"]]))
                fila.update((cambios or {}).get(item["id_item"], {}))
                w.writerow(fila)
        return ruta

    def test_la_llave_contra_si_misma(self):
        codigo, texto = self.correr("calibracion", "--anotacion",
                                    self.anotacion())
        self.assertEqual(codigo, cli.BIEN)
        self.assertIn("idénticos a la llave: 27", texto)
        self.assertIn("relacion      27/27 (100 %)", texto)
        self.assertIn("c01: igual", texto)

    def test_un_desacuerdo_y_una_abstencion(self):
        vacio = dict.fromkeys(rubrica.CAMPOS_CERRADOS, "")
        codigo, texto = self.correr("calibracion", "--anotacion",
                                    self.anotacion({"c27": {"tipo": "directa"},
                                                    "c03": vacio}))
        self.assertEqual(codigo, cli.BIEN)
        self.assertIn("c27: difiere en tipo", texto)
        self.assertIn("c03: abstención", texto)
        self.assertIn("tipo          25/27", texto)

    def test_una_hoja_que_no_es_la_calibracion(self):
        ruta = os.path.join(self.tmp, "otra.csv")
        _escribir_hoja(ruta)
        codigo, texto = self.correr("calibracion", "--anotacion", ruta)
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("ERROR", texto)


class PruebasEvals(Base):

    def test_sin_corrida(self):
        codigo, texto = self.correr("evals", "--salida", self.tmp)
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("corrida.json", texto)

    def test_nunca_en_la_carpeta_del_experto(self):
        codigo, _texto = self.correr("evals", "--salida", os.path.join(
            self.tmp, "salidas", "revision", "x"))
        self.assertEqual(codigo, cli.ENTRADA)

    def test_sin_strands_evals(self):
        self.anotar()
        with mock.patch.object(evals, "disponible", lambda: False):
            codigo, texto = self.correr("evals", "--salida", self.salida)
        self.assertEqual(codigo, cli.ENTRADA)
        self.assertIn("Strands Evals", texto)

    @unittest.skipUnless(TIENE_EVALS, "strands_evals no está instalado: es "
                                      "del .venv-ouroboros")
    def test_sobre_una_corrida_hecha(self):
        self.anotar()
        llamadas = len(self.anotador.llamadas)
        codigo, texto = self.correr("evals", "--salida", self.salida)
        self.assertEqual(codigo, cli.BIEN, texto)
        self.assertIn("validez_rubrica: 3 de 3", texto)
        self.assertIn("campo_relacion: no aplica", texto)
        self.assertEqual(len(self.anotador.llamadas), llamadas)
        for nombre in (evals.NOMBRE_EXPERIMENTO, evals.NOMBRE_INFORME):
            self.assertTrue(os.path.isfile(os.path.join(
                self.salida, nombre + ".json")))
        self.sin_oraciones(texto)


if __name__ == "__main__":
    unittest.main()
