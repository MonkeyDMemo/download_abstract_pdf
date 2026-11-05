"""El proveedor Bedrock: el candado que impide a Claude ser el juez, el
`BedrockModel` que se arma y la petición que sale de él, sin red.

El candado corre sin Strands. Lo demás se salta donde Strands no está, y ahí
nada sale a la red ni lee las credenciales de quien corre: las de AWS son
falsas y van en el entorno, los archivos de configuración de AWS apuntan a una
carpeta vacía, el servicio de metadatos de EC2 queda apagado y
`Endpoint.make_request` de botocore falla si algo intentara mandar una
petición. Las pruebas del anotador sustituyen además el cliente de
`bedrock-runtime` por uno falso que contesta como `ConverseStream`.

    python -m unittest grn_ouroboros.test_bedrock
"""

import importlib.util
import json
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from grn_ouroboros import agente, anotar

TIENE_STRANDS = importlib.util.find_spec("strands") is not None
MOTIVO = "strands no está instalado: es del .venv-ouroboros"

ITEM = {"id_item": "m-3001", "oracion": "GenB activates genC on purpose.",
        "entidad_1": "GenB", "entidad_2": "genC"}

RECHAZADOS = ("", None, "anthropic.claude-3-5-sonnet",
              "us.anthropic.claude-sonnet-4", "claude",
              "arn:aws:bedrock:us-east-1::foundation-model/"
              "qwen.qwen3-32b-v1:0",
              "arn:aws:bedrock:us-east-1:123456789012:inference-profile/"
              "us.anthropic.claude-sonnet-4",
              "meta.llama3-70b", "us.meta.llama3-70b-instruct-v1:0",
              "qwen.CLAUDE-x", "qwen.anthropic", "Qwen.qwen3-32b-v1:0",
              "eu.qwen.qwen3-32b-v1:0", "qwen.qwen3-32b-v1:0\n",
              " qwen.qwen3-32b-v1:0", "qwen.", 42)
ACEPTADOS = ("qwen.qwen3-235b-a22b-2507-v1:0", "us.qwen.qwen3-32b-v1:0",
             "global.qwen.qwen3-coder-480b-a35b-v1:0")


class PruebasCandado(unittest.TestCase):

    def test_rechaza_lo_que_no_es_un_qwen(self):
        for model_id in RECHAZADOS:
            with self.assertRaises(ValueError, msg=repr(model_id)):
                agente.validar_modelo_bedrock(model_id)

    def test_acepta_los_qwen(self):
        for model_id in ACEPTADOS:
            self.assertEqual(agente.validar_modelo_bedrock(model_id),
                             model_id)

    def test_claude_dice_por_que(self):
        for model_id in ("us.anthropic.claude-sonnet-4", "qwen.Claude-3"):
            with self.assertRaises(ValueError) as caja:
                agente.validar_modelo_bedrock(model_id)
            self.assertIn("nunca es Claude", str(caja.exception))

    def test_el_de_omision_pasa_y_no_es_el_de_strands(self):
        self.assertEqual(agente.validar_modelo_bedrock(agente.MODELO_BEDROCK),
                         "qwen.qwen3-235b-a22b-2507-v1:0")
        self.assertEqual(agente.REGION_BEDROCK, "us-west-2")

    def test_la_region(self):
        for region in ("us-east-1", "us-west-2", "us-gov-west-1",
                       "ap-northeast-1"):
            self.assertEqual(agente.validar_region(region), region)
        for region in ("", None, "us-east-1.evil.example", "US-EAST-1",
                       "us-east-1/", "localhost"):
            with self.assertRaises(ValueError, msg=repr(region)):
                agente.validar_region(region)

    def test_solo_sin_herramientas_y_sin_think(self):
        with self.assertRaises(ValueError):
            agente.validar_bedrock(agente.PRINCIPAL, "buscar_locus")
        with self.assertRaises(ValueError):
            agente.validar_bedrock(agente.CON_THINK)
        agente.validar_bedrock(agente.PRINCIPAL)
        # Con ollama no restringe nada.
        agente.validar_bedrock(agente.CON_THINK, "todas", "ollama")
        with self.assertRaises(ValueError):
            agente.validar_bedrock(agente.PRINCIPAL, "ninguna", "openai")

    def test_paralelo(self):
        self.assertEqual(agente.validar_paralelo(1), 1)
        self.assertEqual(agente.validar_paralelo(8, "bedrock"), 8)
        for malo in (0, -1, agente.PARALELO_MAXIMO + 1, True, "4", 2.0):
            with self.assertRaises(ValueError, msg=repr(malo)):
                agente.validar_paralelo(malo, "bedrock")
        with self.assertRaises(ValueError) as caja:
            agente.validar_paralelo(2, "ollama")
        self.assertIn("una sola GPU", str(caja.exception))


class PruebasDecodificacionBedrock(unittest.TestCase):

    def test_lo_que_converse_no_recibe_vale_none(self):
        d = agente.decodificacion(agente.PRINCIPAL, "ninguna", "bedrock")
        self.assertEqual(d["format"], "en_el_prompt")
        self.assertEqual(d["max_tokens"], agente.PRINCIPAL["num_predict"])
        self.assertIsNone(d["max_turnos"])
        for clave in agente.SOLO_OLLAMA:
            self.assertIsNone(d[clave], clave)
        self.assertEqual((d["temperature"], d["think"], d["nombre"]),
                         (0.0, False, "principal"))
        self.assertNotEqual(d, agente.decodificacion(agente.PRINCIPAL))

    def test_con_think_o_herramientas_no(self):
        with self.assertRaises(ValueError):
            agente.decodificacion(agente.CON_THINK, "ninguna", "bedrock")
        with self.assertRaises(ValueError):
            agente.decodificacion(agente.PRINCIPAL, "buscar_locus",
                                  "bedrock")

    def test_el_mismo_prompt_y_el_mismo_mensaje(self):
        """Bedrock lee lo mismo que Ollama: la huella es la registrada."""
        prompt = agente.leer_prompt()
        self.assertEqual(agente.sistema(prompt), prompt)
        self.assertEqual(agente.huella_prompt(prompt),
                         "2f80f09a5850fbf7860d8cb305dbf5fd47703b3aa97df86ab9"
                         "cc72ace9d7ddcc")

    def test_la_descripcion_no_sale_a_aws(self):
        d = agente.describir_bedrock()
        self.assertEqual(d, {"proveedor": "bedrock",
                             "modelo": agente.MODELO_BEDROCK,
                             "region": agente.REGION_BEDROCK})
        with self.assertRaises(ValueError):
            agente.describir_bedrock("anthropic.claude-3-5-sonnet")


class _ClienteBedrockFalso(object):
    """El cliente de `bedrock-runtime` que arma `BedrockModel`: contesta
    `converse_stream` con los eventos de ConverseStream, o lanza `error`.
    El texto puede ser una función de la petición, para ver que cada hilo
    recibe la respuesta de su ítem."""

    def __init__(self, region_name=None, config=None):
        self.meta = types.SimpleNamespace(region_name=region_name,
                                          config=config)
        self.peticiones = []
        self.texto = "{}"
        self.razon = "end_turn"
        self.error = None
        self.espera = 0.0
        self._candado = threading.Lock()
        self.en_vuelo = self.max_en_vuelo = 0

    def converse_stream(self, **peticion):
        with self._candado:
            self.peticiones.append(peticion)
            self.en_vuelo += 1
            self.max_en_vuelo = max(self.max_en_vuelo, self.en_vuelo)
        try:
            if self.espera:
                time.sleep(self.espera(peticion) if callable(self.espera)
                           else self.espera)
            if self.error is not None:
                raise self.error
            texto = (self.texto(peticion) if callable(self.texto)
                     else self.texto)
        finally:
            with self._candado:
                self.en_vuelo -= 1
        return {"stream": [
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"delta": {"text": texto},
                                   "contentBlockIndex": 0}},
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"messageStop": {"stopReason": self.razon}},
            {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5,
                                    "totalTokens": 15},
                          "metrics": {"latencyMs": 1}}},
        ]}


def _entorno_aws_falso(prueba):
    """Credenciales falsas en el entorno y nada de lo de quien corre: ni sus
    archivos de AWS, ni su perfil, ni el servicio de metadatos de EC2 (que,
    además de apagado, se sustituye por uno que no contesta)."""
    from botocore import credentials
    carpeta = tempfile.mkdtemp()
    prueba.addCleanup(shutil.rmtree, carpeta, True)
    parche = mock.patch.dict(os.environ)
    parche.start()
    prueba.addCleanup(parche.stop)
    for variable in list(os.environ):
        if variable.startswith("AWS_"):
            del os.environ[variable]
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "prueba",
        "AWS_SECRET_ACCESS_KEY": "prueba",
        "AWS_CONFIG_FILE": os.path.join(carpeta, "no_existe_config"),
        "AWS_SHARED_CREDENTIALS_FILE": os.path.join(carpeta,
                                                    "no_existe_credenciales"),
        "AWS_EC2_METADATA_DISABLED": "true",
    })
    parche = mock.patch.object(credentials.InstanceMetadataProvider, "load",
                               lambda _self: None)
    parche.start()
    prueba.addCleanup(parche.stop)


def _sin_red(prueba):
    """Si algo arma una petición HTTP de verdad, la prueba falla ahí."""
    from botocore import endpoint

    def prohibido(*_a, **_k):
        raise AssertionError("una petición iba a salir a AWS")

    parche = mock.patch.object(endpoint.Endpoint, "make_request", prohibido)
    parche.start()
    prueba.addCleanup(parche.stop)


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasModeloBedrock(unittest.TestCase):
    """El `BedrockModel` con un cliente de botocore de verdad: crearlo no
    llama a Bedrock."""

    def setUp(self):
        _entorno_aws_falso(self)
        _sin_red(self)

    def test_es_un_bedrock_model_con_el_id_y_la_region(self):
        from strands.models.bedrock import BedrockModel
        modelo = agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock")
        self.assertIsInstance(modelo, BedrockModel)
        self.assertEqual(modelo.config["model_id"], agente.MODELO_BEDROCK)
        self.assertEqual(modelo.client.meta.region_name, "us-west-2")
        otro = agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock",
                                   modelo="us.qwen.qwen3-32b-v1:0",
                                   region="us-west-2")
        self.assertEqual(otro.config["model_id"], "us.qwen.qwen3-32b-v1:0")
        self.assertEqual(otro.client.meta.region_name, "us-west-2")
        self.assertIs(agente.exigir_juez(modelo), modelo)

    def test_la_configuracion_y_los_reintentos(self):
        modelo = agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock")
        self.assertEqual(modelo.config["temperature"], 0.0)
        self.assertEqual(modelo.config["max_tokens"], 512)
        self.assertNotIn("top_p", modelo.config)
        self.assertNotIn("additional_request_fields", modelo.config)
        configuracion = modelo.client.meta.config
        # botocore lo normaliza: 10 reintentos son 11 intentos en total.
        self.assertEqual(configuracion.retries,
                         {"total_max_attempts": 11, "mode": "adaptive"})
        self.assertEqual(configuracion.read_timeout,
                         agente.ESPERA_LECTURA_BEDROCK)

    def test_la_peticion_no_lleva_lo_de_ollama(self):
        modelo = agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock")
        r = modelo.format_request(
            [{"role": "user", "content": [{"text": "hola"}]}], None,
            [{"text": "sistema"}])
        self.assertEqual(r["modelId"], agente.MODELO_BEDROCK)
        self.assertEqual(r["inferenceConfig"], {"maxTokens": 512,
                                                "temperature": 0.0})
        self.assertEqual(r["system"], [{"text": "sistema"}])
        for clave in ("additionalModelRequestFields", "toolConfig", "think",
                      "format", "options"):
            self.assertNotIn(clave, r)

    def test_con_herramientas_o_think_no_se_arma(self):
        from strands.models import bedrock
        with mock.patch.object(bedrock.BedrockModel, "__init__") as init:
            with self.assertRaises(ValueError):
                agente.crear_modelo(agente.PRINCIPAL,
                                    herramientas="buscar_locus",
                                    proveedor="bedrock")
            with self.assertRaises(ValueError):
                agente.crear_modelo(agente.CON_THINK, proveedor="bedrock")
            init.assert_not_called()

    def test_el_candado_va_antes_de_construir(self):
        """None no está: en `crear_modelo` quiere decir `MODELO_BEDROCK`,
        que es explícito."""
        from strands.models import bedrock
        with mock.patch.object(bedrock.BedrockModel, "__init__") as init:
            for model_id in RECHAZADOS:
                if model_id is None:
                    continue
                with self.assertRaises(ValueError, msg=repr(model_id)):
                    agente.crear_modelo(agente.PRINCIPAL, modelo=model_id,
                                        proveedor="bedrock")
            init.assert_not_called()

    def test_un_perfil_que_no_existe(self):
        with self.assertRaises(ValueError) as caja:
            agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock",
                                perfil_aws="no-existe")
        self.assertIn("no-existe", str(caja.exception))

    def test_sin_credenciales(self):
        del os.environ["AWS_ACCESS_KEY_ID"]
        del os.environ["AWS_SECRET_ACCESS_KEY"]
        with self.assertRaises(ValueError) as caja:
            agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock")
        self.assertIn("credenciales", str(caja.exception))

    def test_ollama_no_acepta_lo_de_aws(self):
        with self.assertRaises(ValueError):
            agente.crear_modelo(agente.PRINCIPAL, region="us-east-1")
        with self.assertRaises(ValueError):
            agente.crear_modelo(agente.PRINCIPAL, proveedor="vertex")

    def test_exigir_juez_rechaza_lo_demas(self):
        modelo = agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock")
        modelo.config["model_id"] = "us.anthropic.claude-sonnet-4"
        with self.assertRaises(RuntimeError):
            agente.exigir_juez(modelo)
        for otro in (None, "qwen.qwen3-32b-v1:0", object()):
            with self.assertRaises(RuntimeError):
                agente.exigir_juez(otro)


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasAnotadorBedrock(unittest.TestCase):
    """El anotador completo, con el cliente de `bedrock-runtime` falso."""

    def setUp(self):
        import boto3
        _entorno_aws_falso(self)
        _sin_red(self)
        self.clientes = []

        def cliente(_sesion, service_name=None, config=None,
                    endpoint_url=None, region_name=None, **_k):
            self.assertEqual(service_name, "bedrock-runtime")
            self.assertIsNone(endpoint_url)
            falso = _ClienteBedrockFalso(region_name, config)
            self.clientes.append(falso)
            return falso

        parche = mock.patch.object(boto3.session.Session, "client", cliente)
        parche.start()
        self.addCleanup(parche.stop)

    def anotador(self, **k):
        return agente.crear_anotador(agente.PRINCIPAL, "Sistema.",
                                     proveedor="bedrock", **k)

    def test_una_respuesta_completa(self):
        anotador = self.anotador()
        falso = self.clientes[0]
        falso.texto = json.dumps({"fragmento": "GenB activates genC",
                                  "motivo": "x", "relacion": "si",
                                  "direccion": "1>2", "signo": "+",
                                  "tipo": "no_se", "negada": "no",
                                  "especulativa": "no", "comentario": ""})
        r = anotador(ITEM)
        self.assertEqual((r["done_reason"], r["truncado"]), ("stop", False))
        self.assertFalse(anotar.juzgar(ITEM, r)["abstencion"])
        peticion = falso.peticiones[0]
        self.assertEqual(peticion["modelId"], agente.MODELO_BEDROCK)
        self.assertEqual(peticion["system"], [{"text": "Sistema."}])
        self.assertEqual(peticion["messages"][-1]["content"],
                         [{"text": agente.mensaje(ITEM)}])
        self.assertEqual(peticion["inferenceConfig"],
                         {"maxTokens": 512, "temperature": 0.0})
        self.assertNotIn("additionalModelRequestFields", peticion)
        self.assertNotIn("toolConfig", peticion)
        self.assertEqual(falso.meta.region_name, "us-west-2")
        self.assertEqual(falso.meta.config.retries,
                         {"max_attempts": 10, "mode": "adaptive"})

    def test_el_mismo_prompt_que_ollama(self):
        prompt = agente.leer_prompt()
        anotador = agente.crear_anotador(agente.PRINCIPAL, prompt,
                                         proveedor="bedrock")
        anotador(ITEM)
        self.assertEqual(self.clientes[0].peticiones[0]["system"],
                         [{"text": agente.sistema(prompt)}])

    def test_truncada_es_abstencion(self):
        anotador = self.anotador()
        self.clientes[0].texto = '{"fragmento": "GenB'
        self.clientes[0].razon = "max_tokens"
        r = anotador(ITEM)
        self.assertTrue(r["truncado"])
        self.assertEqual(anotar.juzgar(ITEM, r)["motivo_abstencion"],
                         "truncado")

    def test_un_error_definitivo_sube(self):
        """Como un Ollama caído: el anotador lanza y `ejecutar` detiene la
        corrida, sin guardar abstención."""
        from botocore.exceptions import ClientError
        anotador = self.anotador()
        self.clientes[0].error = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
            "ConverseStream")
        with self.assertRaises(ClientError):
            anotador(ITEM)

    def test_un_modelo_que_no_pasa_el_candado(self):
        with self.assertRaises(ValueError):
            self.anotador(modelo="anthropic.claude-3-5-sonnet")
        self.assertEqual(self.clientes, [])

    def test_la_comprobacion_por_item(self):
        """Si alguien cambia el id del modelo ya creado, el ítem siguiente
        no sale."""
        modelos = []
        original = agente.crear_modelo

        def guarda(*a, **k):
            modelos.append(original(*a, **k))
            return modelos[-1]

        with mock.patch.object(agente, "crear_modelo", guarda):
            anotador = self.anotador()
        modelos[0].config["model_id"] = "us.anthropic.claude-sonnet-4"
        with self.assertRaises(RuntimeError):
            anotador(ITEM)
        self.assertEqual(self.clientes[0].peticiones, [])

    def test_un_juez_que_no_es_de_los_permitidos(self):
        with mock.patch.object(agente, "crear_modelo",
                               lambda *a, **k: object()):
            with self.assertRaises(RuntimeError):
                agente.crear_anotador(agente.PRINCIPAL, "Sistema.")

    def test_varios_hilos_con_el_mismo_modelo(self):
        """Un `Agent` por ítem sobre el mismo `BedrockModel`: cada hilo
        recibe la respuesta de su ítem, aunque terminen en otro orden."""
        anotador = self.anotador()
        falso = self.clientes[0]
        items = [dict(ITEM, id_item="m-%d" % i, entidad_1="Gen%d" % i)
                 for i in range(8)]

        def entidad(peticion):
            texto = peticion["messages"][-1]["content"][0]["text"]
            return texto.split("entidad_1: ", 1)[1].split("\n", 1)[0]

        falso.texto = lambda p: json.dumps({"comentario": entidad(p)})
        falso.espera = lambda p: 0.01 * (8 - int(entidad(p)[3:]))
        salidas = {}

        def correr(item):
            salidas[item["id_item"]] = anotador(item)

        hilos = [threading.Thread(target=correr, args=(it,)) for it in items]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
        self.assertEqual(len(self.clientes), 1)
        self.assertGreater(falso.max_en_vuelo, 1)
        for item in items:
            self.assertEqual(json.loads(salidas[item["id_item"]]["texto"]),
                             {"comentario": item["entidad_1"]})


class PruebasEsquemaEnElPrompt(unittest.TestCase):
    """Sin `format`, la respuesta se lee del texto como en la ruta con
    herramientas: un cerco de código alrededor no la vuelve abstención."""

    def test_un_cerco_alrededor(self):
        valores = {"fragmento": "GenB activates genC", "motivo": "x",
                   "relacion": "si", "direccion": "1>2", "signo": "+",
                   "tipo": "no_se", "negada": "no", "especulativa": "no",
                   "comentario": ""}
        r = {"texto": "```json\n%s\n```" % json.dumps(valores),
             "done_reason": "stop", "truncado": False}
        valor = anotar.juzgar(ITEM, r)
        self.assertFalse(valor["abstencion"])
        self.assertEqual(valor["valores"]["relacion"], "si")
        self.assertEqual(valor["evidencia_invalida"], "no")


if __name__ == "__main__":
    unittest.main()
