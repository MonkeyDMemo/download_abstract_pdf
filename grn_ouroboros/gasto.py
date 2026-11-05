"""Lo que cuesta una corrida en Bedrock y el tope de gasto.

Bedrock cobra por token, y cada respuesta trae los suyos (`uso`, que arma
`agente.crear_anotador`): los de entrada y los de salida, que en gpt-oss
incluyen el razonamiento. El costo es esa cuenta por el precio de lista.

El tope
=======
`--tope-usd X` es una garantía, no un aviso: la corrida no gasta más de X
dólares en esta invocación. Antes de cada llamada se **reserva** lo más que
puede costar (la entrada estimada a 2 caracteres por token, que en inglés y
en español es holgado porque un token ronda los 4, y la salida entera hasta
`max_tokens`); al volver se libera la reserva y se suma el costo real. Si la
reserva no cabe, la llamada no sale y lanza `TopeAlcanzado`, y desde ahí
ninguna otra sale: el tope agotado no se rehabilita aunque una reserva se
libere, para que en paralelo un ítem posterior no gaste en algo que
`anotar.ejecutar` va a descartar. La corrida se detiene como con cualquier
error de Bedrock: lo hecho queda en `veredictos.jsonl`, y volver a correr con
un tope mayor lo retoma sin pagar otra vez lo ya hecho.

El tope es por invocación: lo que sale de la caché no cuesta nada. El costo
acumulado de la carpeta queda en `corrida.json` (`costo`).

Los precios
===========
USD por millón de tokens, on-demand y de lista en us-west-2 (us-east-1 es
igual), consultados el 4-nov-2026 en la página de precios de Bedrock; el de
Qwen3-235B es el de la enmienda 5 de `docs/protocolo-tanda2.md`. Un perfil
de inferencia `us.` o `global.` cobra como el modelo. Para otro modelo de la
lista blanca, el precio se da con `--precios ENTRADA,SALIDA`.

Biblioteca estándar y Python 3.8. No imprime.
"""

import re
import threading

PRECIOS = {
    "qwen.qwen3-235b-a22b-2507-v1:0": (0.22, 0.88),
    "openai.gpt-oss-120b-1:0": (0.15, 0.60),
    "openai.gpt-oss-20b-1:0": (0.07, 0.30),
}

_PERFIL = re.compile(r"^(?:us|global)\.")

# Caracteres por token para la cota de la entrada: la mitad de lo usual, para
# que la reserva no se quede corta.
CARACTERES_POR_TOKEN = 2.0


class TopeAlcanzado(RuntimeError):
    """La siguiente llamada podría pasar del tope de gasto."""


def precio(model_id, precios=None):
    """(entrada, salida) en USD por millón de tokens, o None si no se sabe.
    `precios` gana sobre la tabla."""
    if precios is not None:
        return validar_precios(precios)
    return PRECIOS.get(_PERFIL.sub("", model_id or ""))


def validar_precios(precios):
    """La pareja (entrada, salida) como floats no negativos, o ValueError.
    Acepta el texto de `--precios` («0.15,0.60») o una pareja ya hecha."""
    if isinstance(precios, str):
        partes = [p.strip() for p in precios.split(",")]
    else:
        partes = list(precios)
    try:
        valores = tuple(float(p) for p in partes)
    except (TypeError, ValueError):
        valores = ()
    if len(valores) != 2 or any(v < 0 for v in valores):
        raise ValueError("Los precios son dos números en USD por millón de "
                         "tokens, entrada y salida: --precios 0.15,0.60.")
    return valores


def costo(uso, precio_por_millon):
    """USD de un `uso` ({entrada, salida}); 0 sin uso."""
    if not uso:
        return 0.0
    entrada, salida = precio_por_millon
    return (int(uso.get("entrada") or 0) * entrada
            + int(uso.get("salida") or 0) * salida) / 1e6


def sumar_uso(valores):
    """{entrada, salida, con_uso}: los tokens de los veredictos que traen
    `uso`. Los de Ollama no lo traen y no cuentan."""
    total = {"entrada": 0, "salida": 0, "con_uso": 0}
    for v in valores:
        uso = v.get("uso")
        if uso:
            total["entrada"] += int(uso.get("entrada") or 0)
            total["salida"] += int(uso.get("salida") or 0)
            total["con_uso"] += 1
    return total


def maximo_por_llamada(caracteres_de_entrada, max_tokens, precio_por_millon):
    """Lo más que puede costar una llamada: la cota de la entrada y la
    salida entera."""
    tokens = int(caracteres_de_entrada / CARACTERES_POR_TOKEN) + 1
    return costo({"entrada": tokens, "salida": max_tokens}, precio_por_millon)


class Tope(object):
    """El tope de gasto de una invocación, seguro entre hilos."""

    def __init__(self, usd, precio_por_millon):
        if usd is None or usd <= 0:
            raise ValueError("El tope de gasto es un monto positivo en USD.")
        self.usd = float(usd)
        self.precio = precio_por_millon
        self.gastado = 0.0
        self.reservado = 0.0
        self.llamadas = 0
        self.agotado = False
        self._candado = threading.Lock()

    def reservar(self, maximo):
        """Aparta `maximo` USD o lanza `TopeAlcanzado`."""
        with self._candado:
            if (self.agotado
                    or self.gastado + self.reservado + maximo > self.usd):
                self.agotado = True
                raise TopeAlcanzado(
                    "Se alcanzó el tope de gasto: US$%.4f gastados de "
                    "US$%.2f." % (self.gastado, self.usd))
            self.reservado += maximo

    def liberar(self, maximo, uso):
        with self._candado:
            self.reservado = max(0.0, self.reservado - maximo)
            self.gastado += costo(uso, self.precio)
            self.llamadas += 1


def con_tope(anotador, tope, medir, max_tokens):
    """El anotador envuelto: reserva antes de cada llamada y suma lo gastado
    al volver. `medir(item)` da los caracteres que el modelo lee por ese
    ítem (el sistema y el mensaje). Si la llamada lanza, se libera la
    reserva sin sumar: Bedrock no cobra lo que no contestó."""

    def envuelto(item):
        maximo = maximo_por_llamada(medir(item), max_tokens, tope.precio)
        tope.reservar(maximo)
        try:
            respuesta = anotador(item)
        except BaseException:
            tope.liberar(maximo, None)
            raise
        tope.liberar(maximo, respuesta.get("uso"))
        return respuesta

    return envuelto


def cota_de_la_corrida(items, medir, max_tokens, precio_por_millon):
    """Lo más que pueden costar esos ítems, para avisarlo antes de correr."""
    return sum(maximo_por_llamada(medir(item), max_tokens, precio_por_millon)
               for item in items)
