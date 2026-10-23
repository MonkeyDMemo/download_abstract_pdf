"""El anotador de Strands: un `OllamaModel` explícito y un `Agent` nuevo por
ítem.

`crear_anotador(config, prompt, ...)` devuelve el callable que espera
`anotar.ejecutar`: recibe un ítem y devuelve el texto del modelo con su
`done_reason`, si se truncó y la trayectoria de herramientas. Strands se
importa dentro de las funciones: el módulo se importa y sus constantes se
leen sin él, en el Python 3.8 del servidor o en la laptop.

Lo que se verificó en el código instalado (strands-agents 1.62.0, ollama
0.6.3) y no se cambia sin volver a verificar:

- `OllamaModel(host, *, ollama_client_args, model_id, temperature, top_p,
  max_tokens, options, keep_alive, additional_args)`. `think` no es campo de
  la configuración: va en `additional_args`, que entra al nivel superior de
  la petición, igual que `format`. Necesita el cliente `ollama` 0.5 o más.
- `num_predict` va en `options`; `max_tokens` no se pasa, porque lo pisaría.
- Strands lee solo `message.content`, no `message.thinking`: con think, el
  razonamiento no llega al texto. Si un template lo deja en el contenido, el
  bloque `<think>` lo quita `anotar.quitar_razonamiento`.
- Un `Agent` sin modelo, o con `model="texto"`, crea un `BedrockModel` (Claude)
  sin avisar. Aquí siempre va una instancia de `OllamaModel`, y se comprueba.
- `callback_handler=None`, para que no imprima.
- Al llegar a `num_predict`, el loop lanza `MaxTokensReachedException`; si el
  contexto no cabe, `ContextWindowOverflowException`. Las dos son de las
  entradas y se devuelven como respuesta (truncada o abstención); cualquier
  otra excepción sube, porque es «no pude preguntar».

`format` y las herramientas no conviven
=======================================
Con `format`, Ollama restringe la salida a la gramática del esquema desde el
primer token, y las llamadas a herramientas las saca del texto generado: el
modelo ya no puede escribir una llamada, contesta directo y la corrida «con
herramientas» sería, sin avisar, una sin ellas. Por eso, con herramientas, no
se manda `format`: el esquema se pide en el prompt (que ya lo describe) y la
respuesta se valida igual, y una respuesta sin JSON válido es abstención.
Sin herramientas, `format` va siempre. El modo queda en la configuración de
decodificación y por eso en la llave de la caché. Con herramientas el agente
lleva además un tope de turnos (`limits`, que el loop de Strands respeta sin
lanzar nada): al llegar, la respuesta no trae JSON y es abstención.

Configuraciones pre-registradas
===============================
- `PRINCIPAL`: sin think, T = 0, semilla 42, `num_ctx` 4096, `num_predict`
  512. Con T = 0 la decodificación es voraz y `top_p`/`top_k` no entran.
- `CON_THINK`: think, T = 0.6, `top_p` 0.95, `top_k` 20, `num_ctx` 8192,
  `num_predict` 4096, lo que recomienda Qwen: con T = 0 y think se degrada.

Las herramientas son otra dimensión (`ninguna` por omisión); la semilla se
puede cambiar por corrida (`--semilla`) y entra a la llave.
"""

import hashlib
import io
import json
import os

from grn_ouroboros import herramientas as _herramientas
from grn_ouroboros import motor, rubrica

_AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_PROMPT = os.path.join(_AQUI, "prompts", "anotador_v0.md")

PRINCIPAL = {"nombre": "principal", "think": False, "temperature": 0.0,
             "top_p": None, "top_k": None, "seed": 42, "num_ctx": 4096,
             "num_predict": 512}
CON_THINK = {"nombre": "con_think", "think": True, "temperature": 0.6,
             "top_p": 0.95, "top_k": 20, "seed": 42, "num_ctx": 8192,
             "num_predict": 4096}
CONFIGURACIONES = {"principal": PRINCIPAL, "con_think": CON_THINK}

# Lo que el modelo se queda cargado después de la última petición. No cambia
# ningún veredicto, así que no entra a la llave.
KEEP_ALIVE = "5m"
# Por petición. Con streaming, httpx lo aplica entre fragmentos: cubre la
# carga del modelo en la GPU y un servidor que dejó de contestar.
ESPERA_CLIENTE = motor.ESPERA_CHAT
# Una vuelta por cada consulta permitida, más la respuesta final.
MAX_TURNOS = _herramientas.MAX_LLAMADAS + 2

PLANTILLA_MENSAJE = ("Oración:\n{oracion}\n\n"
                     "entidad_1: {entidad_1}\n"
                     "entidad_2: {entidad_2}")

APENDICE_HERRAMIENTAS = (
    "\n\n## Herramientas\n\n"
    "Tienes herramientas que consultan el diccionario de *P. aeruginosa* "
    "PAO1 y, si están, el contexto de la oración. Consulta solo lo que "
    "necesites y, al terminar, responde solo con el objeto JSON descrito "
    "arriba.\n")


def configuracion(nombre, semilla=None):
    """Una copia de la configuración pre-registrada, con otra semilla si se
    pide. Copia: nadie modifica las constantes por accidente."""
    if nombre not in CONFIGURACIONES:
        raise ValueError("La configuración es principal o con_think.")
    config = dict(CONFIGURACIONES[nombre])
    if semilla is not None:
        config["seed"] = int(semilla)
    return config


def leer_prompt(ruta=RUTA_PROMPT):
    """El prompt del sistema, con los saltos de línea normalizados: el mismo
    archivo con CRLF y con LF es el mismo prompt."""
    with io.open(ruta, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def sistema(prompt, herramientas="ninguna"):
    """El texto del sistema que recibe el modelo."""
    if herramientas == "ninguna":
        return prompt
    return prompt.rstrip("\n") + APENDICE_HERRAMIENTAS


def huella_prompt(prompt, herramientas="ninguna"):
    """sha256 de todo lo que el modelo lee además del ítem: el sistema y la
    plantilla del mensaje."""
    texto = json.dumps({"sistema": sistema(prompt, herramientas),
                        "plantilla": PLANTILLA_MENSAJE}, ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def mensaje(item):
    """El mensaje del usuario para un ítem: la oración y las dos entidades.
    El `id_item` no va: es un código opaco y el modelo no lo necesita."""
    return PLANTILLA_MENSAJE.format(oracion=item["oracion"],
                                    entidad_1=item["entidad_1"],
                                    entidad_2=item["entidad_2"])


def opciones(config):
    """Las `options` de Ollama. Las que valen None no se mandan: Ollama usa
    las suyas, y con T = 0 no cuentan."""
    salida = {}
    for clave in ("seed", "num_ctx", "num_predict", "top_k"):
        if config.get(clave) is not None:
            salida[clave] = config[clave]
    return salida


def con_format(herramientas):
    """`format` solo sin herramientas (ver el docstring del módulo)."""
    return herramientas == "ninguna"


def argumentos_adicionales(config, herramientas="ninguna"):
    """Lo que va al nivel superior de la petición: `think` y, sin
    herramientas, el esquema en `format`."""
    adicionales = {"think": bool(config["think"])}
    if con_format(herramientas):
        adicionales["format"] = rubrica.esquema()
    return adicionales


def decodificacion(config, herramientas="ninguna"):
    """La configuración de decodificación completa, para la llave de la
    caché: todo lo que cambia lo que genera el modelo."""
    salida = dict(config)
    salida["format"] = "esquema" if con_format(herramientas) else "en_el_prompt"
    salida["max_turnos"] = MAX_TURNOS if herramientas != "ninguna" else None
    return salida


def crear_modelo(config, host=motor.HOST, herramientas="ninguna",
                 modelo=motor.MODELO):
    """El `OllamaModel` de la configuración, contra un Ollama de 127.0.0.1."""
    # Antes de importar Strands: un host ajeno se rechaza aunque no esté.
    host = motor.validar_host(host)
    from strands.models.ollama import OllamaModel
    argumentos = {
        "model_id": modelo,
        "temperature": config["temperature"],
        "options": opciones(config),
        "additional_args": argumentos_adicionales(config, herramientas),
        "keep_alive": KEEP_ALIVE,
    }
    if config.get("top_p") is not None:
        argumentos["top_p"] = config["top_p"]
    # Sin `trust_env`, httpx mandaría la petición al proxy del entorno en vez
    # de al Ollama local.
    return OllamaModel(host,
                       ollama_client_args={"timeout": ESPERA_CLIENTE,
                                           "trust_env": False},
                       **argumentos)


def _texto_del_ultimo(agente):
    """El texto del último mensaje del agente: tras `MaxTokensReachedException`
    Strands deja ahí lo que alcanzó a generar."""
    try:
        bloques = agente.messages[-1].get("content") or []
    except (AttributeError, IndexError, TypeError):
        return ""
    return "".join(b.get("text", "") for b in bloques if isinstance(b, dict))


def crear_anotador(config, prompt, host=motor.HOST, herramientas="ninguna",
                   recursos=None, modelo=motor.MODELO):
    """El callable `anotador(item) -> respuesta` de `anotar.ejecutar`."""
    from strands import Agent
    from strands.models.ollama import OllamaModel
    from strands.types.exceptions import (ContextWindowOverflowException,
                                          MaxTokensReachedException)

    if herramientas not in _herramientas.OPCIONES:
        raise ValueError("herramientas es ninguna, buscar_locus o todas.")
    if herramientas != "ninguna" and recursos is None:
        recursos = _herramientas.Recursos()
    ollama = crear_modelo(config, host, herramientas, modelo)
    texto_sistema = sistema(prompt, herramientas)

    def anotador(item):
        registro = []
        tools = _herramientas.para_strands(recursos, herramientas, item,
                                           registro)
        # Uno nuevo por ítem: lo que se habló de un ítem no puede llegar al
        # siguiente.
        agente = Agent(model=ollama, system_prompt=texto_sistema, tools=tools,
                       callback_handler=None)
        if not isinstance(agente.model, OllamaModel):
            raise RuntimeError("El juez tiene que ser el OllamaModel local.")
        try:
            if tools:
                resultado = agente(mensaje(item),
                                   limits={"turns": MAX_TURNOS})
            else:
                resultado = agente(mensaje(item))
        except MaxTokensReachedException:
            return {"texto": _texto_del_ultimo(agente),
                    "done_reason": "length", "truncado": True,
                    "trayectoria": registro}
        except ContextWindowOverflowException:
            return {"texto": "", "done_reason": None, "truncado": False,
                    "trayectoria": registro,
                    "motivo_abstencion": "contexto_excedido"}
        razon = getattr(resultado, "stop_reason", None)
        respuesta = {"texto": str(resultado),
                     "done_reason": {"end_turn": "stop",
                                     "max_tokens": "length"}.get(razon, razon),
                     "truncado": razon == "max_tokens",
                     "trayectoria": registro}
        if razon == "limit_turns":
            respuesta["motivo_abstencion"] = "limite_turnos"
        return respuesta

    return anotador
