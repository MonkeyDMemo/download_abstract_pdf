"""gpt-oss en la lista blanca y su configuración `razonador`, los tokens que
lleva cada respuesta de Bedrock, y que con Ollama nada de eso cambie. Sin
red: el cliente de `bedrock-runtime` es el falso de `test_bedrock`, aquí con
un bloque de razonamiento antes del texto, como contesta gpt-oss.

    python -m unittest grn_ouroboros.test_gptoss
"""

import json
import unittest
from unittest import mock

from grn_ouroboros import agente, anotar, test_bedrock
from grn_ouroboros.test_bedrock import (ITEM, MOTIVO, TIENE_STRANDS,
                                        _entorno_aws_falso, _sin_red)

GPT_OSS = "openai.gpt-oss-120b-1:0"

RESPUESTA = json.dumps({"fragmento": "GenB activates genC", "motivo": "x",
                        "relacion": "si", "direccion": "1>2", "signo": "+",
                        "tipo": "no_se", "negada": "no",
                        "especulativa": "no", "comentario": ""})


class PruebasCandadoGptOss(unittest.TestCase):

    def test_acepta_los_dos_gpt_oss_y_sus_perfiles(self):
        for model_id in (GPT_OSS, "openai.gpt-oss-20b-1:0",
                         "us.openai.gpt-oss-120b-1:0",
                         "global.openai.gpt-oss-20b-1:0"):
            self.assertEqual(agente.validar_modelo_bedrock(model_id),
                             model_id)
            self.assertTrue(agente.es_gpt_oss(model_id))

    def test_nada_mas_de_openai_ni_claude(self):
        for model_id in ("openai.gpt-oss-safeguard-120b-1:0",
                         "openai.gpt-5-1:0", "us.openai.gpt-6-sol",
                         "openai.gpt-oss-120b", "openai.gpt-oss-70b-1:0",
                         "OPENAI.gpt-oss-120b-1:0", "eu.openai.gpt-oss-20b-1:0",
                         "openai.gpt-oss-120b-1:0\n",
                         "openai.gpt-oss-120b-1:0-claude",
                         "anthropic.openai.gpt-oss-120b-1:0"):
            with self.assertRaises(ValueError, msg=repr(model_id)):
                agente.validar_modelo_bedrock(model_id)
        with self.assertRaises(ValueError) as caja:
            agente.validar_modelo_bedrock("openai.gpt-oss-120b-1:0-claude")
        self.assertIn("nunca es Claude", str(caja.exception))

    def test_los_qwen_no_son_gpt_oss(self):
        self.assertFalse(agente.es_gpt_oss(agente.MODELO_BEDROCK))
        self.assertFalse(agente.es_gpt_oss(None))


class PruebasRazonador(unittest.TestCase):

    def test_la_configuracion(self):
        c = agente.configuracion("razonador")
        self.assertEqual((c["temperature"], c["top_p"], c["num_predict"],
                          c["razonamiento"]), (1.0, 1.0, 4096, "medium"))
        self.assertEqual(agente.configuracion(
            "razonador", razonamiento="low")["razonamiento"], "low")
        # Copia: la constante no cambia.
        self.assertEqual(agente.RAZONADOR["razonamiento"], "medium")

    def test_el_razonamiento_solo_en_razonador(self):
        with self.assertRaises(ValueError):
            agente.configuracion("principal", razonamiento="low")
        with self.assertRaises(ValueError):
            agente.configuracion("razonador", razonamiento="maximo")

    def test_las_de_antes_no_ganan_la_clave(self):
        self.assertNotIn("razonamiento", agente.PRINCIPAL)
        self.assertNotIn("razonamiento", agente.CON_THINK)

    def test_modelo_y_configuracion_van_juntos(self):
        razonador = agente.configuracion("razonador")
        agente.validar_modelo_y_config(GPT_OSS, razonador)
        agente.validar_modelo_y_config(agente.MODELO_BEDROCK,
                                       agente.PRINCIPAL)
        with self.assertRaises(ValueError):
            agente.validar_modelo_y_config(GPT_OSS, agente.PRINCIPAL)
        with self.assertRaises(ValueError):
            agente.validar_modelo_y_config(agente.MODELO_BEDROCK, razonador)

    def test_razonador_no_va_con_ollama(self):
        razonador = agente.configuracion("razonador")
        with self.assertRaises(ValueError):
            agente.validar_bedrock(razonador, "ninguna", "ollama")
        agente.validar_bedrock(razonador, "ninguna", "bedrock")

    def test_la_decodificacion_lleva_el_razonamiento(self):
        d = agente.decodificacion(agente.configuracion("razonador"),
                                  "ninguna", "bedrock")
        self.assertEqual((d["razonamiento"], d["max_tokens"], d["format"]),
                         ("medium", 4096, "en_el_prompt"))
        for clave in agente.SOLO_OLLAMA:
            self.assertIsNone(d[clave])
        otra = agente.decodificacion(
            agente.configuracion("razonador", razonamiento="high"),
            "ninguna", "bedrock")
        self.assertNotEqual(d, otra)


class _ClienteConRazonamiento(test_bedrock._ClienteBedrockFalso):
    """Contesta como gpt-oss: un bloque `reasoningContent` y luego el
    texto, con los tokens del razonamiento en la salida."""

    def converse_stream(self, **peticion):
        respuesta = super().converse_stream(**peticion)
        texto = respuesta["stream"][1]["contentBlockDelta"]["delta"]["text"]
        return {"stream": [
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"delta": {"reasoningContent": {
                "text": "Pienso en GenB y genC."}}, "contentBlockIndex": 0}},
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"contentBlockDelta": {"delta": {"text": texto},
                                   "contentBlockIndex": 1}},
            {"contentBlockStop": {"contentBlockIndex": 1}},
            {"messageStop": {"stopReason": self.razon}},
            {"metadata": {"usage": {"inputTokens": 1200, "outputTokens": 300,
                                    "totalTokens": 1500},
                          "metrics": {"latencyMs": 1}}},
        ]}


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasModeloGptOss(unittest.TestCase):

    def setUp(self):
        _entorno_aws_falso(self)
        _sin_red(self)

    def test_la_peticion_lleva_el_razonamiento(self):
        modelo = agente.crear_modelo(agente.configuracion("razonador"),
                                     proveedor="bedrock", modelo=GPT_OSS)
        self.assertIs(agente.exigir_juez(modelo), modelo)
        r = modelo.format_request(
            [{"role": "user", "content": [{"text": "hola"}]}], None,
            [{"text": "sistema"}])
        self.assertEqual(r["modelId"], GPT_OSS)
        self.assertEqual(r["inferenceConfig"], {"maxTokens": 4096,
                                                "temperature": 1.0,
                                                "topP": 1.0})
        self.assertEqual(r["additionalModelRequestFields"],
                         {"reasoning_effort": "medium"})

    def test_gpt_oss_con_principal_no_se_construye(self):
        from strands.models import bedrock
        with mock.patch.object(bedrock.BedrockModel, "__init__") as init:
            with self.assertRaises(ValueError):
                agente.crear_modelo(agente.PRINCIPAL, proveedor="bedrock",
                                    modelo=GPT_OSS)
            with self.assertRaises(ValueError):
                agente.crear_modelo(agente.configuracion("razonador"),
                                    proveedor="bedrock")
            init.assert_not_called()


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasAnotadorGptOss(unittest.TestCase):

    def setUp(self):
        import boto3
        _entorno_aws_falso(self)
        _sin_red(self)
        self.clientes = []

        def cliente(_sesion, service_name=None, config=None,
                    endpoint_url=None, region_name=None, **_k):
            falso = _ClienteConRazonamiento(region_name, config)
            self.clientes.append(falso)
            return falso

        parche = mock.patch.object(boto3.session.Session, "client", cliente)
        parche.start()
        self.addCleanup(parche.stop)

    def test_el_razonamiento_no_llega_al_texto_y_los_tokens_si(self):
        anotador = agente.crear_anotador(
            agente.configuracion("razonador", razonamiento="low"),
            "Sistema.", proveedor="bedrock", modelo=GPT_OSS)
        self.clientes[0].texto = RESPUESTA
        r = anotador(ITEM)
        self.assertNotIn("Pienso", r["texto"])
        self.assertEqual(r["uso"], {"entrada": 1200, "salida": 300})
        valor = anotar.juzgar(ITEM, r)
        self.assertFalse(valor["abstencion"])
        self.assertEqual(valor["uso"], {"entrada": 1200, "salida": 300})
        peticion = self.clientes[0].peticiones[0]
        self.assertEqual(peticion["additionalModelRequestFields"],
                         {"reasoning_effort": "low"})

    def test_truncada_tambien_trae_los_tokens(self):
        anotador = agente.crear_anotador(agente.configuracion("razonador"),
                                         "Sistema.", proveedor="bedrock",
                                         modelo=GPT_OSS)
        self.clientes[0].texto = '{"fragmento": "GenB'
        self.clientes[0].razon = "max_tokens"
        r = anotador(ITEM)
        self.assertTrue(r["truncado"])
        self.assertEqual(r["uso"], {"entrada": 1200, "salida": 300})

    def test_qwen_tambien_trae_los_tokens(self):
        """Con el mismo falso: los tokens salen de lo que Bedrock reporta,
        sea cual sea el modelo, y a un Qwen no se le pide razonamiento."""
        anotador = agente.crear_anotador(agente.PRINCIPAL, "Sistema.",
                                         proveedor="bedrock")
        self.clientes[0].texto = RESPUESTA
        r = anotador(ITEM)
        self.assertEqual(r["uso"], {"entrada": 1200, "salida": 300})
        self.assertNotIn("additionalModelRequestFields",
                         self.clientes[0].peticiones[0])


@unittest.skipUnless(TIENE_STRANDS, MOTIVO)
class PruebasOllamaSinUso(unittest.TestCase):
    """Con Ollama la respuesta trae las mismas claves de antes, y el
    veredicto, también."""

    def test_la_respuesta_no_gana_claves(self):
        import ollama
        from grn_ouroboros import test_agente
        falso = test_agente._ClienteFalso
        falso.peticiones, falso.construido_con = [], []
        falso.guion, falso.razon, falso.texto = None, "stop", RESPUESTA
        with mock.patch.object(ollama, "AsyncClient", falso):
            anotador = agente.crear_anotador(agente.PRINCIPAL, "Sistema.")
            r = anotador(dict(ITEM))
        self.assertEqual(sorted(r), ["done_reason", "texto", "trayectoria",
                                     "truncado"])
        self.assertNotIn("uso", anotar.juzgar(ITEM, r))


if __name__ == "__main__":
    unittest.main()
