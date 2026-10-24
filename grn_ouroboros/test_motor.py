"""El Ollama descrito y exigido, con la apertura de URL sustituida: ninguna
prueba sale a la red, ni siquiera a 127.0.0.1.

    python -m unittest grn_ouroboros.test_motor
"""

import io
import json
import unittest
import urllib.error
import urllib.request

from grn_ouroboros import motor

DIGEST = "500a1f067a9f" + "0" * 52


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class OllamaFalso(object):
    """Contesta por ruta, como el Ollama del servidor, y anota cada
    petición."""

    def __init__(self, digest=DIGEST, cuantizacion="Q4_K_M",
                 modelo="qwen3:8b", fallar=None):
        self.peticiones = []
        self.fallar = fallar or {}
        self.rutas = {
            "/api/version": {"version": "0.12.6"},
            "/api/tags": {"models": [
                {"name": "otro:1b", "model": "otro:1b", "digest": "f" * 64},
                {"name": modelo, "model": modelo, "digest": digest}]},
            "/api/show": {"template": "{{ .Prompt }}",
                          "details": {"family": "qwen3",
                                      "parameter_size": "8.2B",
                                      "quantization_level": cuantizacion},
                          "capabilities": ["tools", "completion",
                                           "thinking"]},
            "/api/chat": {"message": {"role": "assistant",
                                      "content": "{}"},
                          "done_reason": "stop"},
        }

    def __call__(self, peticion, timeout=None):
        ruta = peticion.full_url.split("11500", 1)[1]
        cuerpo = (json.loads(peticion.data.decode("utf-8"))
                  if peticion.data else None)
        self.peticiones.append((peticion.get_method(), ruta, cuerpo,
                                timeout))
        if ruta in self.fallar:
            raise self.fallar[ruta]
        return _Respuesta(json.dumps(self.rutas[ruta]).encode("utf-8"))


class PruebasHost(unittest.TestCase):

    def test_solo_127_0_0_1_con_puerto(self):
        self.assertEqual(motor.validar_host("http://127.0.0.1:11500/"),
                         "http://127.0.0.1:11500")
        for malo in ("http://localhost:11500", "https://127.0.0.1:11500",
                     "http://10.0.0.5:11500", "http://127.0.0.1",
                     "http://127.0.0.1:11500/api", "127.0.0.1:11500",
                     "http://user:clave@127.0.0.1:11500", "", None):
            with self.assertRaises(motor.ErrorMotor, msg=malo):
                motor.validar_host(malo)

    def test_el_abridor_no_usa_los_proxies_del_entorno(self):
        """`ProxyHandler({})` es como `urllib` deja de leer `http_proxy`:
        reemplaza al de omisión, y sin protocolos ni siquiera se instala."""
        proxies = [h.proxies for h in motor._ABRIDOR.handlers
                   if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual([p for p in proxies if p], [])


class PruebasDescribir(unittest.TestCase):

    def test_lee_version_digest_cuantizacion_y_template(self):
        falso = OllamaFalso()
        d = motor.describir(abrir=falso)
        self.assertEqual(d["ollama"], "0.12.6")
        self.assertEqual(d["digest"], DIGEST)
        self.assertEqual(d["cuantizacion"], "Q4_K_M")
        self.assertEqual(d["huella_template"],
                         motor.huella_texto("{{ .Prompt }}"))
        self.assertEqual(d["capacidades"], ["completion", "thinking",
                                             "tools"])
        self.assertEqual([p[1] for p in falso.peticiones],
                         ["/api/version", "/api/tags", "/api/show"])
        self.assertEqual(falso.peticiones[2][2], {"model": "qwen3:8b"})

    def test_un_modelo_que_no_esta(self):
        with self.assertRaises(motor.ErrorMotor):
            motor.describir(modelo="qwen3:32b", abrir=OllamaFalso())

    def test_sin_conexion_es_error_del_motor(self):
        falso = OllamaFalso(fallar={
            "/api/version": urllib.error.URLError("rechazada")})
        with self.assertRaises(motor.ErrorMotor):
            motor.describir(abrir=falso)

    def test_un_error_http(self):
        falso = OllamaFalso(fallar={"/api/show": urllib.error.HTTPError(
            "http://127.0.0.1:11500/api/show", 404, "no", {}, None)})
        with self.assertRaises(motor.ErrorMotor) as caja:
            motor.describir(abrir=falso)
        self.assertIn("404", str(caja.exception))


class PruebasExigir(unittest.TestCase):

    def test_el_pre_registrado_pasa(self):
        d = motor.describir(abrir=OllamaFalso())
        self.assertIs(motor.exigir(d), d)

    def test_otro_digest_detiene(self):
        d = motor.describir(abrir=OllamaFalso(digest="abc" * 20))
        with self.assertRaises(motor.ErrorMotor) as caja:
            motor.exigir(d)
        self.assertIn("digest", str(caja.exception))

    def test_otra_cuantizacion_detiene(self):
        d = motor.describir(abrir=OllamaFalso(cuantizacion="Q8_0"))
        with self.assertRaises(motor.ErrorMotor) as caja:
            motor.exigir(d)
        self.assertIn("Q8_0", str(caja.exception))


class PruebasChat(unittest.TestCase):

    def test_va_sin_streaming_por_post(self):
        falso = OllamaFalso()
        r = motor.chat({"model": "qwen3:8b", "messages": [], "think": False},
                       abrir=falso)
        self.assertEqual(r["done_reason"], "stop")
        metodo, ruta, cuerpo, espera = falso.peticiones[0]
        self.assertEqual((metodo, ruta), ("POST", "/api/chat"))
        self.assertIs(cuerpo["stream"], False)
        self.assertIs(cuerpo["think"], False)
        self.assertEqual(espera, motor.ESPERA_CHAT)


class PruebasHumo(unittest.TestCase):

    def responder(self, mensaje, **ollama):
        falso = OllamaFalso(**ollama)
        falso.rutas["/api/chat"] = {"message": dict(role="assistant",
                                                    **mensaje),
                                    "done_reason": "stop", "eval_count": 3,
                                    "total_duration": 2500000000}
        return motor.humo(abrir=falso), falso

    def test_el_pre_registrado_sin_razonamiento(self):
        r, falso = self.responder({"content": "listo"})
        self.assertEqual(r["problemas"], [])
        self.assertTrue(r["sin_razonamiento"])
        self.assertEqual((r["done_reason"], r["tokens"], r["segundos"]),
                         ("stop", 3, 2.5))
        _metodo, ruta, cuerpo, _espera = falso.peticiones[-1]
        self.assertEqual(ruta, "/api/chat")
        self.assertIs(cuerpo["think"], False)
        self.assertEqual(cuerpo["messages"][0]["content"], motor.PROMPT_HUMO)

    def test_con_razonamiento_en_el_campo_o_en_el_texto(self):
        for mensaje in ({"content": "listo", "thinking": "Pienso..."},
                        {"content": "<think>Pienso.</think>listo"},
                        {"content": "<think>Me corté"}):
            r, _ = self.responder(mensaje)
            self.assertFalse(r["sin_razonamiento"], mensaje)
            self.assertGreater(r["caracteres_de_razonamiento"], 0)

    def test_un_bloque_vacio_no_es_razonamiento(self):
        r, _ = self.responder({"content": "<think>\n\n</think>\n\nlisto"})
        self.assertTrue(r["sin_razonamiento"])

    def test_otro_modelo_es_un_problema_y_no_una_excepcion(self):
        r, _ = self.responder({"content": "listo"}, cuantizacion="Q8_0")
        self.assertEqual(len(r["problemas"]), 1)
        self.assertIn("Q8_0", r["problemas"][0])

    def test_sin_ollama_es_error_del_motor(self):
        falso = OllamaFalso(fallar={
            "/api/version": urllib.error.URLError("rechazada")})
        with self.assertRaises(motor.ErrorMotor):
            motor.humo(abrir=falso)


if __name__ == "__main__":
    unittest.main()
