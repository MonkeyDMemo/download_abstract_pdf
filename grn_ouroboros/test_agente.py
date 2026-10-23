"""El anotador de Strands: las configuraciones pre-registradas, lo que va en
la petición a Ollama y cómo se lee lo que vuelve.

Las clases que necesitan Strands se saltan donde no está (la laptop, el
Python 3.8 del servidor): corren en `.venv-ouroboros`. Ahí la petición se
arma de verdad con `OllamaModel.format_request` y el cliente de `ollama` se
sustituye por uno falso: ninguna prueba sale a la red.

    python -m unittest grn_ouroboros.test_agente
"""

import importlib.util
import io
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from grn_ouroboros import agente, anotar, rubrica

TIENE_STRANDS = importlib.util.find_spec("strands") is not None
MOTIVO = "strands no está instalado: es del .venv-ouroboros del servidor"

ITEM = {"id_item": "m-1001", "oracion": "GenX activates genY on purpose.",
        "entidad_1": "GenX", "entidad_2": "genY"}


class PruebasConfiguraciones(unittest.TestCase):

    def test_las_pre_registradas(self):
        p = agente.configuracion("principal")
        self.assertEqual((p["think"], p["temperature"], p["seed"],
                          p["num_ctx"], p["num_predict"]),
                         (False, 0.0, 42, 4096, 512))
        t = agente.configuracion("con_think")
        self.assertEqual((t["think"], t["temperature"], t["top_p"],
                          t["top_k"], t["num_ctx"], t["num_predict"]),
                         (True, 0.6, 0.95, 20, 8192, 4096))

    def test_son_copias_y_la_semilla_se_cambia(self):
        c = agente.configuracion("con_think", semilla=7)
        self.assertEqual(c["seed"], 7)
        c["temperature"] = 1.5
        self.assertEqual(agente.CON_THINK["temperature"], 0.6)
        self.assertEqual(agente.CON_THINK["seed"], 42)
        with self.assertRaises(ValueError):
            agente.configuracion("otra")

    def test_options_sin_los_vacios(self):
        self.assertEqual(agente.opciones(agente.PRINCIPAL),
                         {"seed": 42, "num_ctx": 4096, "num_predict": 512})
        self.assertEqual(agente.opciones(agente.CON_THINK),
                         {"seed": 42, "num_ctx": 8192, "num_predict": 4096,
                          "top_k": 20})

    def test_format_va_solo_sin_herramientas(self):
        sin = agente.argumentos_adicionales(agente.PRINCIPAL)
        self.assertEqual(sin, {"think": False, "format": rubrica.esquema()})
        con = agente.argumentos_adicionales(agente.CON_THINK, "buscar_locus")
        self.assertEqual(con, {"think": True})

    def test_la_decodificacion_dice_el_modo_del_formato(self):
        self.assertEqual(agente.decodificacion(agente.PRINCIPAL)["format"],
                         "esquema")
        todas = agente.decodificacion(agente.PRINCIPAL, "todas")
        self.assertEqual(todas["format"], "en_el_prompt")
        self.assertEqual(todas["max_turnos"], agente.MAX_TURNOS)


class PruebasPrompt(unittest.TestCase):

    def setUp(self):
        self.prompt = agente.leer_prompt()

    def test_lleva_las_etiquetas_exactas_y_las_claves(self):
        for opciones in rubrica.OPCIONES.values():
            for etiqueta in opciones:
                self.assertIn("`%s`" % etiqueta, self.prompt)
        for clave in rubrica.CAMPOS_RESPUESTA:
            self.assertIn("`%s`" % clave, self.prompt)

    def test_la_regla_del_experto(self):
        self.assertIn("Juzga solo lo que afirma la oración, no lo que sabes",
                      self.prompt)

    def test_crlf_es_el_mismo_prompt(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        ruta = os.path.join(tmp, "p.md")
        with io.open(ruta, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(self.prompt)
        self.assertEqual(agente.leer_prompt(ruta), self.prompt)

    def test_la_huella_cambia_con_las_herramientas(self):
        self.assertNotEqual(agente.huella_prompt(self.prompt),
                            agente.huella_prompt(self.prompt, "todas"))
        self.assertEqual(agente.huella_prompt(self.prompt, "buscar_locus"),
                         agente.huella_prompt(self.prompt, "todas"))

    def test_el_mensaje_no_lleva_el_id(self):
        texto = agente.mensaje(ITEM)
        self.assertIn(ITEM["oracion"], texto)
        self.assertIn("entidad_2: genY", texto)
        self.assertNotIn("m-1001", texto)

    def test_un_host_que_no_es_local_no_se_acepta(self):
        from grn_ouroboros import motor
        with self.assertRaises(motor.ErrorMotor):
            agente.crear_modelo(agente.PRINCIPAL, host="http://10.0.0.2:1")


class _ClienteFalso(object):
    """El `ollama.AsyncClient` que usa Strands, con una respuesta fija o con
    un guion: `guion` es una lista de (texto, llamadas a herramientas) que se
    consume una por petición, y se repite la última."""

    peticiones = []
    construido_con = []
    texto = ""
    razon = "stop"
    guion = None

    def __init__(self, host=None, **argumentos):
        _ClienteFalso.construido_con.append((host, argumentos))

    async def chat(self, **peticion):
        _ClienteFalso.peticiones.append(peticion)
        texto, llamadas = _ClienteFalso.texto, None
        if _ClienteFalso.guion:
            paso = min(len(_ClienteFalso.peticiones),
                       len(_ClienteFalso.guion)) - 1
            texto, nombres = _ClienteFalso.guion[paso]
            llamadas = [types.SimpleNamespace(function=types.SimpleNamespace(
                name=n, arguments=a)) for n, a in nombres] or None
        evento = types.SimpleNamespace(
            message=types.SimpleNamespace(content=texto, tool_calls=llamadas),
            done_reason=_ClienteFalso.razon, prompt_eval_count=10,
            eval_count=5, total_duration=1000000)

        async def eventos():
            yield evento
        return eventos()


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasPeticion(unittest.TestCase):
    """Lo que `OllamaModel.format_request` arma con cada configuración."""

    def peticion(self, config, herramientas="ninguna"):
        modelo = agente.crear_modelo(config, herramientas=herramientas)
        return modelo.format_request(
            [{"role": "user", "content": [{"text": "hola"}]}], None,
            "sistema")

    def test_es_un_ollama_model(self):
        from strands.models.ollama import OllamaModel
        self.assertIsInstance(agente.crear_modelo(agente.PRINCIPAL),
                              OllamaModel)

    def test_principal(self):
        r = self.peticion(agente.PRINCIPAL)
        self.assertEqual(r["model"], "qwen3:8b")
        self.assertIs(r["think"], False)
        self.assertEqual(r["format"], rubrica.esquema())
        self.assertEqual(r["options"], {"seed": 42, "num_ctx": 4096,
                                        "num_predict": 512,
                                        "temperature": 0.0})
        self.assertEqual(r["keep_alive"], agente.KEEP_ALIVE)
        self.assertEqual(r["messages"][0], {"role": "system",
                                            "content": "sistema"})

    def test_con_think(self):
        r = self.peticion(agente.CON_THINK)
        self.assertIs(r["think"], True)
        self.assertEqual(r["options"], {"seed": 42, "num_ctx": 8192,
                                        "num_predict": 4096, "top_k": 20,
                                        "temperature": 0.6, "top_p": 0.95})

    def test_con_herramientas_no_va_format(self):
        r = self.peticion(agente.PRINCIPAL, "buscar_locus")
        self.assertNotIn("format", r)
        self.assertIs(r["think"], False)


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasAnotador(unittest.TestCase):
    """El anotador completo con el cliente de `ollama` sustituido."""

    def setUp(self):
        import ollama
        _ClienteFalso.peticiones = []
        _ClienteFalso.construido_con = []
        _ClienteFalso.guion = None
        _ClienteFalso.razon = "stop"
        parche = mock.patch.object(ollama, "AsyncClient", _ClienteFalso)
        parche.start()
        self.addCleanup(parche.stop)
        self.anotador = agente.crear_anotador(agente.PRINCIPAL, "Sistema.")

    def responder(self, texto, razon="stop"):
        _ClienteFalso.texto = texto
        _ClienteFalso.razon = razon
        return self.anotador(ITEM)

    def test_una_respuesta_completa(self):
        valido = json.dumps({"fragmento": "GenX activates genY",
                             "motivo": "x", "relacion": "si",
                             "direccion": "1>2", "signo": "+",
                             "tipo": "no_se", "negada": "no",
                             "especulativa": "no", "comentario": ""})
        r = self.responder(valido)
        self.assertEqual(r["done_reason"], "stop")
        self.assertFalse(r["truncado"])
        valor = anotar.juzgar(ITEM, r)
        self.assertFalse(valor["abstencion"])
        peticion = _ClienteFalso.peticiones[0]
        self.assertIs(peticion["think"], False)
        self.assertEqual(peticion["format"], rubrica.esquema())
        self.assertEqual(peticion["tools"], [])
        self.assertEqual(peticion["messages"][-1]["content"],
                         agente.mensaje(ITEM))
        host, argumentos = _ClienteFalso.construido_con[0]
        self.assertEqual(host, "http://127.0.0.1:11500")
        self.assertIs(argumentos["trust_env"], False)

    def test_truncada_es_abstencion(self):
        r = self.responder('{"fragmento": "GenX', razon="length")
        self.assertTrue(r["truncado"])
        self.assertEqual(r["done_reason"], "length")
        self.assertEqual(anotar.juzgar(ITEM, r)["motivo_abstencion"],
                         "truncado")

    def test_un_agente_nuevo_por_item(self):
        self.responder("{}")
        self.responder("{}")
        segunda = _ClienteFalso.peticiones[1]["messages"]
        self.assertEqual([m["role"] for m in segunda], ["system", "user"])

    def test_con_herramientas_la_trayectoria_y_sin_format(self):
        anotador = agente.crear_anotador(agente.PRINCIPAL, "Sistema.",
                                         herramientas="buscar_locus")
        _ClienteFalso.guion = [
            ("", [("buscar_locus", {"nombre": "lasR"})]),
            ('{"relacion": "no"}', []),
        ]
        r = anotador(ITEM)
        self.assertEqual(len(_ClienteFalso.peticiones), 2)
        primera = _ClienteFalso.peticiones[0]
        self.assertNotIn("format", primera)
        self.assertEqual([t["function"]["name"] for t in primera["tools"]],
                         ["buscar_locus"])
        self.assertEqual(r["trayectoria"][0]["herramienta"], "buscar_locus")
        self.assertEqual(r["trayectoria"][0]["salida"]["coincidencias"][0][
            "locus_tag"], "PA1430")
        self.assertEqual(r["texto"].strip(), '{"relacion": "no"}')

    def test_el_tope_de_turnos_es_abstencion(self):
        anotador = agente.crear_anotador(agente.PRINCIPAL, "Sistema.",
                                         herramientas="buscar_locus")
        _ClienteFalso.guion = [("", [("buscar_locus", {"nombre": "lasR"})])]
        r = anotador(ITEM)
        self.assertLessEqual(len(_ClienteFalso.peticiones), agente.MAX_TURNOS)
        self.assertEqual(r["motivo_abstencion"], "limite_turnos")
        self.assertEqual(anotar.juzgar(ITEM, r)["motivo_abstencion"],
                         "limite_turnos")


if __name__ == "__main__":
    unittest.main()
