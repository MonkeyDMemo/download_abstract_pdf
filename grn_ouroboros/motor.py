"""El Ollama del servidor, por su API HTTP: qué versión es, qué modelo sirve
y si es el que se pre-registró.

`describir()` lee tres rutas y devuelve lo que entra a la huella de cada
veredicto:

- `/api/version`: la versión del motor;
- `/api/tags`: el digest completo del modelo, que identifica los pesos;
- `/api/show`: la cuantización (`details.quantization_level`) y una huella
  del template de chat, que decide cómo llega el prompt al modelo.

`exigir()` detiene la corrida si el digest o la cuantización no son los
pre-registrados: un `qwen3:8b` que alguien volvió a bajar puede ser otro
modelo con el mismo nombre, y sus veredictos no serían comparables.

`humo()` es la prueba antes de anotar: describe el modelo, dice si es el
pre-registrado y comprueba que con `think: false` la respuesta llega sin
razonamiento.

Solo `http://127.0.0.1`: el juez es local, y lo que se le manda son las
oraciones de una hoja de anotación. Sin proxies, aunque el entorno los tenga:
`urllib` los respeta por omisión y mandaría la petición al proxy en vez de al
Ollama local.

Biblioteca estándar y Python 3.8. No imprime: lanza `ErrorMotor`.
"""

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

HOST = "http://127.0.0.1:11500"
MODELO = "qwen3:8b"
DIGEST_PREFIJO = "500a1f067a9f"
CUANTIZACION = "Q4_K_M"

# La prueba de humo: una instrucción inventada, sin nada del corpus, y un tope
# corto, porque solo se mira si la respuesta trae razonamiento.
PROMPT_HUMO = "Responde solo con la palabra: listo."
OPCIONES_HUMO = {"temperature": 0, "seed": 42, "num_predict": 64}

_BLOQUE_THINK = re.compile(r"<think>(.*?)</think>", re.S)

# Leer la versión o la lista de modelos es inmediato. Un chat puede esperar a
# que el modelo se cargue en la GPU y generar miles de tokens con think.
ESPERA_CONSULTA = 30
ESPERA_CHAT = 900

_ABRIDOR = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ErrorMotor(RuntimeError):
    """El Ollama no contestó, contestó algo inesperado o no es el
    pre-registrado."""


def validar_host(host):
    """`http://127.0.0.1:PUERTO` normalizado, o ErrorMotor.

    Ni `localhost` ni otra interfaz: `localhost` puede resolver a otra cosa en
    una máquina compartida, y cualquier otro host saca las oraciones del
    servidor.
    """
    partes = urllib.parse.urlsplit(host or "")
    if (partes.scheme != "http" or partes.hostname != "127.0.0.1"
            or partes.path not in ("", "/") or partes.query
            or partes.username or partes.password):
        raise ErrorMotor("El host de Ollama tiene que ser "
                         "http://127.0.0.1:PUERTO; se recibió otro.")
    try:
        puerto = partes.port
    except ValueError:
        raise ErrorMotor("El puerto de Ollama no es un número.")
    if puerto is None:
        raise ErrorMotor("Falta el puerto de Ollama (el del servidor es "
                         "11500).")
    return "http://127.0.0.1:%d" % puerto


def _pedir(host, ruta, cuerpo=None, espera=ESPERA_CONSULTA, abrir=None):
    """El JSON de una ruta de la API. Con cuerpo es POST."""
    url = validar_host(host) + ruta
    datos = None
    cabeceras = {"Accept": "application/json"}
    if cuerpo is not None:
        datos = json.dumps(cuerpo).encode("utf-8")
        cabeceras["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=datos, headers=cabeceras,
                                      method="POST" if datos else "GET")
    abrir = abrir or _ABRIDOR.open
    try:
        with abrir(peticion, timeout=espera) as respuesta:
            texto = respuesta.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ErrorMotor("Ollama respondió %d en %s." % (e.code, ruta))
    except (urllib.error.URLError, OSError) as e:
        raise ErrorMotor("No se pudo hablar con Ollama en %s (%s)."
                         % (ruta, type(e).__name__))
    try:
        return json.loads(texto)
    except ValueError:
        raise ErrorMotor("Ollama no devolvió JSON en %s." % ruta)


def huella_texto(texto):
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()


def describir(host=HOST, modelo=MODELO, abrir=None):
    """{host, ollama, modelo, digest, cuantizacion, huella_template, familia,
    parametros, capacidades} del modelo que sirve ese Ollama."""
    version = _pedir(host, "/api/version", abrir=abrir).get("version")
    if not version:
        raise ErrorMotor("Ollama no dijo su versión.")
    modelos = _pedir(host, "/api/tags", abrir=abrir).get("models") or []
    entrada = None
    for m in modelos:
        if modelo in (m.get("name"), m.get("model")):
            entrada = m
            break
    if entrada is None or not entrada.get("digest"):
        raise ErrorMotor("El modelo %s no está en ese Ollama." % modelo)
    show = _pedir(host, "/api/show", {"model": modelo}, abrir=abrir)
    detalles = show.get("details") or {}
    return {
        "host": validar_host(host),
        "ollama": version,
        "modelo": modelo,
        "digest": entrada["digest"],
        "cuantizacion": detalles.get("quantization_level") or "",
        "familia": detalles.get("family") or "",
        "parametros": detalles.get("parameter_size") or "",
        "huella_template": huella_texto(show.get("template")),
        "capacidades": sorted(show.get("capabilities") or []),
    }


def exigir(descripcion, digest_prefijo=DIGEST_PREFIJO,
           cuantizacion=CUANTIZACION):
    """La misma descripción si el modelo es el pre-registrado; si no,
    ErrorMotor con lo que no coincide."""
    problemas = []
    if not (descripcion.get("digest") or "").startswith(digest_prefijo):
        problemas.append("el digest empieza con %s y se esperaba %s"
                         % ((descripcion.get("digest") or "")[:12],
                            digest_prefijo))
    if descripcion.get("cuantizacion") != cuantizacion:
        problemas.append("la cuantización es %s y se esperaba %s"
                         % (descripcion.get("cuantizacion") or "(ninguna)",
                            cuantizacion))
    if problemas:
        raise ErrorMotor("El modelo no es el pre-registrado: %s."
                         % "; ".join(problemas))
    return descripcion


def chat(cuerpo, host=HOST, espera=ESPERA_CHAT, abrir=None):
    """Una petición a `/api/chat` sin streaming, para la prueba de humo. La
    anotación de verdad pasa por Strands (`agente.py`)."""
    cuerpo = dict(cuerpo, stream=False)
    return _pedir(host, "/api/chat", cuerpo, espera=espera, abrir=abrir)


def razonamiento_de(mensaje):
    """El razonamiento que trae un mensaje de `/api/chat`, o "".

    Es el campo `thinking` más lo que haya dentro de `<think>…</think>` en el
    contenido, o después de un `<think>` sin cierre. Un bloque vacío no
    cuenta: así marcan algunos templates que no hubo razonamiento.
    """
    partes = [mensaje.get("thinking") or ""]
    contenido = mensaje.get("content") or ""
    partes.extend(_BLOQUE_THINK.findall(contenido))
    resto = _BLOQUE_THINK.sub("", contenido)
    if "<think>" in resto:
        partes.append(resto.split("<think>", 1)[1])
    return "".join(p.strip() for p in partes)


def humo(host=HOST, modelo=MODELO, abrir=None):
    """La prueba de humo: {descripcion, problemas, sin_razonamiento,
    caracteres_de_razonamiento, done_reason, tokens, segundos}.

    `problemas` dice qué no coincide con lo pre-registrado; vacío, el modelo
    es el que se registró. Si con `think: false` llegara razonamiento, la
    corrida principal razonaría sin que su configuración lo dijera, y el tope
    de 512 tokens la truncaría. Lanza ErrorMotor si Ollama no contesta.
    """
    descripcion = describir(host, modelo, abrir=abrir)
    problemas = []
    try:
        exigir(descripcion)
    except ErrorMotor as e:
        problemas.append(str(e))
    respuesta = chat({"model": modelo,
                      "messages": [{"role": "user", "content": PROMPT_HUMO}],
                      "think": False, "options": dict(OPCIONES_HUMO)},
                     host=host, abrir=abrir)
    razonamiento = razonamiento_de(respuesta.get("message") or {})
    return {
        "descripcion": descripcion,
        "problemas": problemas,
        "sin_razonamiento": not razonamiento,
        "caracteres_de_razonamiento": len(razonamiento),
        "done_reason": respuesta.get("done_reason"),
        "tokens": respuesta.get("eval_count"),
        "segundos": round((respuesta.get("total_duration") or 0) / 1e9, 1),
    }
