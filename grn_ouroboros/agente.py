"""El anotador de Strands: un modelo explícito y un `Agent` nuevo por ítem.

El juez es el `OllamaModel` local o un Qwen en Bedrock con id explícito;
nunca Claude. `crear_anotador(config, prompt, ...)` devuelve el callable que
espera `anotar.ejecutar`: recibe un ítem y devuelve el texto del modelo con su
`done_reason`, si se truncó y la trayectoria de herramientas. Strands y boto3
se importan dentro de las funciones: el módulo se importa y sus constantes se
leen sin ellos, en el Python 3.8 del servidor o en la laptop.

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
  sin avisar. Aquí siempre va una instancia de `OllamaModel`, o de
  `BedrockModel` con un Qwen que pasa el candado, y se comprueba.
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

Las dos con la caché KV de Ollama en `f16`, la de omisión.

Las herramientas son otra dimensión (`ninguna` por omisión). Tres valores se
pueden cambiar por corrida, y los tres entran a la llave:

- la semilla (`--semilla`);
- `num_ctx` (`--num-ctx`), para recortar el de la corrida con think si los
  8 192 no caben en la GPU ni con la caché comprimida;
- el tipo de caché KV (`--kv-cache q8_0`), que es lo primero que se prueba
  antes de recortar (`docs/decisiones.md`, «Ouroboros v0»). Es una variable
  del servidor (`OLLAMA_KV_CACHE_TYPE`), no de la petición: no se manda ni se
  puede leer por la API, así que la corrida la declara. Entra a la llave
  porque una caché comprimida cambia los números con que el modelo decide.

El proveedor Bedrock
====================
`--proveedor bedrock` cambia el motor, no la pregunta: el mismo prompt, la
misma plantilla del mensaje y la misma lectura de la respuesta. Con
`ollama`, que es el de omisión, nada de esta sección se toca: la decodificación,
las entradas de la caché y `corrida.json` son los de antes, byte por byte.

- **El candado.** `validar_modelo_bedrock` acepta solo un id explícito de la
  lista blanca de Qwen (`qwen.…`, `us.qwen.…`, `global.qwen.…`) y rechaza todo
  lo que diga `anthropic` o `claude`, sin importar mayúsculas, los ARN y los
  perfiles de inferencia de otros proveedores. Strands sin `model_id` cae en
  Claude, así que el id nunca se deja a Strands: si no llega, se usa
  `MODELO_BEDROCK`, explícito. La comprobación por ítem (`exigir_juez`) mira
  otra vez el `BedrockModel` que el `Agent` va a usar.
- **Lo que se verificó en el código instalado** (strands-agents 1.62.0,
  boto3 1.43): `BedrockModel(*, boto_session, boto_client_config,
  region_name, endpoint_url, api_key, **config)`, y `region_name` no convive
  con `boto_session`; por eso la región va en la sesión, que también lleva el
  perfil. `max_tokens`, `temperature` y `top_p` van a `inferenceConfig` de
  Converse. Crear el cliente resuelve las credenciales, pero no llama a
  Bedrock.
- **El formato.** Converse no tiene `format`: el esquema se pide en el prompt,
  que ya lo describe entero («## Respuesta»), como en la ruta con
  herramientas, y la decodificación lo registra (`format = en_el_prompt`). El
  sistema y el mensaje son los mismos de Ollama, así que `huella_prompt` da
  la misma huella (`2f80f09a…` con el v0): lo que cambia la llave es el
  proveedor, el modelo, la región y la decodificación.
- **think.** Qwen3-235B-A22B-2507 es instruct, sin modo de pensamiento, y el
  código no agrega marcas como `/no_think`: el texto queda idéntico y solo se
  omite lo que Converse no acepta (`think`, `format`, la semilla, `num_ctx`,
  `top_k`, la caché KV, que en la decodificación de Bedrock valen None). Por
  eso Bedrock corre solo la configuración sin think, sin herramientas, y sin
  `--semilla` ni `--num-ctx`. El límite de generación es el mismo:
  `num_predict` pasa como `max_tokens`.
- **Los errores.** El cliente reintenta el throttling con el modo `adaptive`
  de botocore (`REINTENTOS_BEDROCK`), y lo que sobrevive lo reintenta Strands
  (`ModelThrottledException`, seis veces con espera creciente). Lo que queda
  es «no pude preguntar» y detiene la corrida igual que un Ollama caído: lo
  hecho queda en la caché y volver a correr lo retoma.
- **Los hilos.** Con `--paralelo N`, los N hilos comparten un solo
  `BedrockModel`: el cliente de boto3 es seguro entre hilos, y su limitador
  adaptativo, compartido, frena a todos cuando Bedrock pide calma; con un
  cliente por hilo cada uno creería que va solo. Del modelo, durante una
  llamada, solo se lee la configuración: los dos atributos que Strands
  escribe se tocan con herramientas o con el razonamiento de Claude, y aquí
  no hay ni uno ni otro. El `Agent` es uno por ítem, así que la conversación
  no se comparte.
"""

import hashlib
import io
import json
import os
import re

from grn_ouroboros import herramientas as _herramientas
from grn_ouroboros import motor, rubrica

_AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_PROMPT = os.path.join(_AQUI, "prompts", "anotador_v0.md")

PRINCIPAL = {"nombre": "principal", "think": False, "temperature": 0.0,
             "top_p": None, "top_k": None, "seed": 42, "num_ctx": 4096,
             "num_predict": 512, "kv_cache": "f16"}
CON_THINK = {"nombre": "con_think", "think": True, "temperature": 0.6,
             "top_p": 0.95, "top_k": 20, "seed": 42, "num_ctx": 8192,
             "num_predict": 4096, "kv_cache": "f16"}
CONFIGURACIONES = {"principal": PRINCIPAL, "con_think": CON_THINK}

# Los que acepta `OLLAMA_KV_CACHE_TYPE`; q8_0 y q4_0 piden flash attention.
TIPOS_KV = ("f16", "q8_0", "q4_0")

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

PROVEEDORES = ("ollama", "bedrock")

# El juez de Bedrock por omisión: el Qwen3 grande, instruct y sin modo de
# pensamiento. Va siempre explícito.
MODELO_BEDROCK = "qwen.qwen3-235b-a22b-2507-v1:0"
REGION_BEDROCK = "us-east-1"
# La lista blanca: un Qwen de Bedrock, directo o por un perfil de inferencia
# `us.` o `global.`. Un ARN, `meta.…` o `us.anthropic.…` no casan.
_QWEN_BEDROCK = re.compile(r"^(?:us\.|global\.)?qwen\.[a-z0-9][a-z0-9.:-]*$")
# Se rechazan aunque casen con la lista blanca (`qwen.claude-x` casaría).
_NUNCA = ("anthropic", "claude")
_REGION = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]{1,2}$")
# botocore reintenta el throttling con espera y frena solo (modo adaptive);
# 120 s es lo que Strands pone por omisión entre fragmentos del streaming.
REINTENTOS_BEDROCK = {"max_attempts": 10, "mode": "adaptive"}
ESPERA_LECTURA_BEDROCK = 120
ESPERA_CONEXION_BEDROCK = 30
# Lo que Converse no recibe: en la decodificación de Bedrock valen None.
SOLO_OLLAMA = ("seed", "num_ctx", "top_k", "kv_cache")
# Se agregan a las versiones de `corrida.json` solo con Bedrock.
PAQUETES_BEDROCK = ("boto3", "botocore")
# Con Ollama, 1: hay una sola GPU. El tope es contra un error de dedo que
# dispararía el throttling.
PARALELO_MAXIMO = 32


def configuracion(nombre, semilla=None, num_ctx=None, kv_cache=None):
    """Una copia de la configuración pre-registrada, con otra semilla, otro
    `num_ctx` u otro tipo de caché KV si se piden. Copia: nadie modifica las
    constantes por accidente."""
    if nombre not in CONFIGURACIONES:
        raise ValueError("La configuración es principal o con_think.")
    config = dict(CONFIGURACIONES[nombre])
    if semilla is not None:
        config["seed"] = int(semilla)
    if num_ctx is not None:
        # El contexto lleva el prompt, la oración y la respuesta: con uno que
        # no pasa de num_predict, ninguna respuesta completa cabría y todo
        # saldría abstención.
        if int(num_ctx) <= config["num_predict"]:
            raise ValueError("num_ctx tiene que pasar de num_predict (%d)."
                             % config["num_predict"])
        config["num_ctx"] = int(num_ctx)
    if kv_cache is not None:
        if kv_cache not in TIPOS_KV:
            raise ValueError("La caché KV es %s." % ", ".join(TIPOS_KV))
        config["kv_cache"] = kv_cache
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


def decodificacion(config, herramientas="ninguna", proveedor="ollama"):
    """La configuración de decodificación completa, para la llave de la
    caché: todo lo que cambia lo que genera el modelo.

    Con Ollama es la de siempre. Con Bedrock, lo que Converse no recibe vale
    None (`SOLO_OLLAMA`), el límite se dice como `max_tokens` y el formato va
    en el prompt."""
    salida = dict(config)
    if proveedor == "ollama":
        salida["format"] = ("esquema" if con_format(herramientas)
                            else "en_el_prompt")
        salida["max_turnos"] = (MAX_TURNOS if herramientas != "ninguna"
                                else None)
        return salida
    validar_bedrock(config, herramientas, proveedor)
    for clave in SOLO_OLLAMA:
        salida[clave] = None
    salida["max_tokens"] = config["num_predict"]
    salida["format"] = "en_el_prompt"
    salida["max_turnos"] = None
    return salida


# ------------------------------------------------------------ el candado

def validar_modelo_bedrock(model_id):
    """El id si es un Qwen de la lista blanca; si no, ValueError.

    Exige el id explícito: vacío o None es Strands eligiendo, y Strands elige
    Claude. Lo que diga `anthropic` o `claude` se rechaza antes de mirar la
    lista blanca, sin importar mayúsculas.
    """
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("Con bedrock el modelo va explícito (--modelo): un "
                         "Qwen, por ejemplo %s." % MODELO_BEDROCK)
    if any(prohibido in model_id.lower() for prohibido in _NUNCA):
        raise ValueError("El juez nunca es Claude: el modelo %r no se acepta."
                         % model_id)
    if not _QWEN_BEDROCK.fullmatch(model_id):
        raise ValueError("Con bedrock solo se acepta un Qwen (qwen.…, "
                         "us.qwen.… o global.qwen.…), sin ARN; %r no lo es."
                         % model_id)
    return model_id


def validar_region(region):
    """La región si tiene forma de región de AWS (`us-east-1`); si no,
    ValueError. La región arma el host del cliente."""
    if not isinstance(region, str) or not _REGION.fullmatch(region):
        raise ValueError("La región de AWS tiene la forma us-east-1; se "
                         "recibió %r." % (region,))
    return region


def validar_bedrock(config, herramientas="ninguna", proveedor="bedrock"):
    """ValueError si la corrida no se puede hacer en Bedrock: solo sin
    herramientas y sin think (ver el docstring del módulo)."""
    if proveedor not in PROVEEDORES:
        raise ValueError("El proveedor es ollama o bedrock.")
    if proveedor != "bedrock":
        return
    if herramientas != "ninguna":
        raise ValueError("Con bedrock solo se corre sin herramientas "
                         "(--herramientas ninguna).")
    if config.get("think"):
        raise ValueError("Con bedrock solo la configuración sin think "
                         "(principal): Converse no tiene cómo pedirlo, y el "
                         "Qwen por omisión es instruct, sin modo de "
                         "pensamiento.")


def validar_paralelo(paralelo, proveedor="ollama"):
    """Cuántos ítems a la vez, o ValueError. Con Ollama, 1."""
    if (isinstance(paralelo, bool) or not isinstance(paralelo, int)
            or not 1 <= paralelo <= PARALELO_MAXIMO):
        raise ValueError("--paralelo va de 1 a %d." % PARALELO_MAXIMO)
    if proveedor == "ollama" and paralelo != 1:
        raise ValueError("Con ollama, --paralelo es 1: hay una sola GPU, y "
                         "dos peticiones a la vez solo se forman.")
    return paralelo


def describir_bedrock(modelo=MODELO_BEDROCK, region=REGION_BEDROCK):
    """Lo que hace con Bedrock la descripción de `motor.describir`: el
    proveedor, el id y la región, que entran a la llave
    (`anotar.armar_entradas`). No llama a AWS: de un modelo de Bedrock no hay
    digest que leer, y su id es el que se registra."""
    return {"proveedor": "bedrock", "modelo": validar_modelo_bedrock(modelo),
            "region": validar_region(region)}


def exigir_juez(modelo):
    """El mismo modelo si es un juez permitido: el `OllamaModel` local o un
    `BedrockModel` cuyo id pasa el candado. Si no, RuntimeError."""
    from strands.models.bedrock import BedrockModel
    from strands.models.ollama import OllamaModel
    if isinstance(modelo, OllamaModel):
        return modelo
    if isinstance(modelo, BedrockModel):
        try:
            validar_modelo_bedrock((getattr(modelo, "config", None) or {})
                                   .get("model_id"))
            return modelo
        except ValueError:
            pass
    raise RuntimeError("El juez tiene que ser el OllamaModel local o un Qwen "
                       "de Bedrock con id explícito; nunca Claude.")


# ---------------------------------------------------------------- modelos

def crear_modelo(config, host=motor.HOST, herramientas="ninguna",
                 modelo=None, proveedor="ollama", region=None,
                 perfil_aws=None):
    """El modelo de la configuración: el `OllamaModel` contra un Ollama de
    127.0.0.1 (`modelo` por omisión, `motor.MODELO`) o, con
    `proveedor="bedrock"`, el `BedrockModel` de un Qwen (por omisión
    `MODELO_BEDROCK` en `REGION_BEDROCK`)."""
    if proveedor == "bedrock":
        return _crear_bedrock(config, herramientas, modelo, region,
                              perfil_aws)
    if proveedor != "ollama":
        raise ValueError("El proveedor es ollama o bedrock.")
    if region is not None or perfil_aws is not None:
        raise ValueError("La región y el perfil de AWS son de bedrock.")
    if modelo is None:
        modelo = motor.MODELO
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


def _crear_bedrock(config, herramientas, modelo, region, perfil_aws):
    """El `BedrockModel`. Todo se valida antes de importar boto3: un id que
    no pasa el candado no llega ni a crear la sesión."""
    validar_bedrock(config, herramientas)
    modelo = validar_modelo_bedrock(MODELO_BEDROCK if modelo is None
                                    else modelo)
    region = validar_region(REGION_BEDROCK if region is None else region)
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ProfileNotFound
    from strands.models.bedrock import BedrockModel
    try:
        sesion = boto3.Session(profile_name=perfil_aws, region_name=region)
        # Crear el cliente las resuelve igual; aquí se pide antes para que
        # su falta detenga la corrida antes de escribir nada.
        if sesion.get_credentials() is None:
            raise ValueError("No hay credenciales de AWS: pásalas con "
                             "--perfil-aws o con las variables del entorno.")
    except ProfileNotFound:
        raise ValueError("El perfil de AWS %r no existe." % perfil_aws)
    argumentos = {
        "model_id": modelo,
        "temperature": config["temperature"],
        # El mismo límite de generación que num_predict en Ollama.
        "max_tokens": config["num_predict"],
    }
    if config.get("top_p") is not None:
        argumentos["top_p"] = config["top_p"]
    reintentos = Config(retries=dict(REINTENTOS_BEDROCK),
                        read_timeout=ESPERA_LECTURA_BEDROCK,
                        connect_timeout=ESPERA_CONEXION_BEDROCK)
    return BedrockModel(boto_session=sesion, boto_client_config=reintentos,
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
                   recursos=None, modelo=None, proveedor="ollama",
                   region=None, perfil_aws=None):
    """El callable `anotador(item) -> respuesta` de `anotar.ejecutar`.

    Con Bedrock se puede llamar desde varios hilos a la vez: cada llamada
    arma su propio `Agent`, y el modelo, que se comparte, solo se lee (ver el
    docstring del módulo). Con Ollama va de uno en uno, como siempre."""
    from strands import Agent
    from strands.types.exceptions import (ContextWindowOverflowException,
                                          MaxTokensReachedException)

    if herramientas not in _herramientas.OPCIONES:
        raise ValueError("herramientas es ninguna, buscar_locus o todas.")
    if herramientas != "ninguna" and recursos is None:
        recursos = _herramientas.Recursos()
    juez = exigir_juez(crear_modelo(config, host, herramientas, modelo,
                                    proveedor, region, perfil_aws))
    texto_sistema = sistema(prompt, herramientas)

    def anotador(item):
        registro = []
        tools = _herramientas.para_strands(recursos, herramientas, item,
                                           registro)
        # Uno nuevo por ítem: lo que se habló de un ítem no puede llegar al
        # siguiente.
        agente = Agent(model=juez, system_prompt=texto_sistema, tools=tools,
                       callback_handler=None)
        exigir_juez(agente.model)
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
