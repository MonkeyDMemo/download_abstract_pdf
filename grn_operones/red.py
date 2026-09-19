# -*- coding: utf-8 -*-
"""Peticiones HTTP con sesion, control de tasa y reintentos. Solo estandar.

POR QUE NO SE REUSA `grn_etl/pubmed.py::Cliente`
================================================
Se reusa su **contrato**, que es lo que importa, y no su codigo, que no da:

- `Cliente` abre cada peticion con `urllib.request.urlopen` suelto, sin opener
  ni almacen de cookies. BioCyc exige `POST /credentials/login/` y despues
  arrastrar la cookie de sesion en cada consulta; sin cookies no hay forma.
- `Cliente.eutils()` hace POST solo contra endpoints de NCBI, con `tool`,
  `email` y `api_key` inyectados. Mandar eso a BioCyc no tiene sentido.
- `grn_etl/` esta cerrado, asi que anadirle sesiones no es una opcion.

**El contrato de errores si es el mismo, y eso no es simetria decorativa:**
`None` = el servidor contesto y la respuesta es no (404, 403); excepcion = no
pude preguntar (transporte caido, 5xx tras agotar intentos). Quien llama
traduce `None` a "esta fuente no tiene esto" y lo da por definitivo. Si un
corte de red se colara como `None`, una fuente entera quedaria marcada como
vacia cuando lo que paso es que no se pudo preguntar.

RESPETO A LAS FUENTES
=====================
`PAUSA` es de 2 segundos y es un piso, no un objetivo: el encargo lo fija y
estas son bases academicas pequenas, no NCBI. El User-Agent identifica al
proyecto y lleva un correo de contacto, que es lo que permite a un
administrador escribir en vez de bloquear.

Lo que este modulo **no** hace, a proposito: no reintenta un 403, no rota
User-Agents, no ejecuta JavaScript y no trae un navegador. Si una fuente
responde que no, la respuesta es que no. Evadir una deteccion de bots esta
fuera de alcance por contrato, y ademas rompe los terminos de uso que el propio
encargo manda respetar.
"""

import http.cookiejar
import time
import urllib.error
import urllib.parse
import urllib.request

# Mismo conjunto que `pubmed.HTTP_DEFINITIVOS`: el servidor contesto, y lo que
# contesto es que no. Reintentarlos gasta peticiones contra quien ya respondio.
HTTP_DEFINITIVOS = (401, 403, 404, 422, 451)

PAUSA = 2.0
INTENTOS = 4
TIMEOUT = 120

AGENTE = "grn-operones/0.1 (IIMAS UNAM; uso academico; %s)"


class ErrorFuente(Exception):
    """No se pudo preguntar. Distinto de que la fuente diga que no."""


class Sesion(object):
    """Un opener con cookies, pausa entre peticiones y reintentos.

    Una instancia por fuente: el almacen de cookies de BioCyc no tiene nada
    que hacer en una peticion a ODB, y la pausa se mide por servidor.
    """

    def __init__(self, correo, pausa=PAUSA):
        if not correo:
            raise ValueError(
                "hace falta un correo de contacto para identificar al agente")
        self.correo = correo
        self.pausa = pausa
        self._galletas = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._galletas))
        self._ultima = 0.0

    def _esperar(self):
        falta = self.pausa - (time.time() - self._ultima)
        if falta > 0:
            time.sleep(falta)
        self._ultima = time.time()

    def _abrir(self, url, datos=None, timeout=TIMEOUT):
        peticion = urllib.request.Request(
            url, data=datos, headers={"User-Agent": AGENTE % self.correo})
        with self._opener.open(peticion, timeout=timeout) as r:
            return r.read()

    def pedir(self, url, params=None, datos=None, intentos=INTENTOS,
              timeout=TIMEOUT):
        """Los bytes de la respuesta, `None` si la fuente dijo que no.

        Con `datos` va por POST. Lanza `ErrorFuente` al agotar los intentos:
        eso es "no pude preguntar", y quien llama no debe confundirlo con una
        respuesta vacia.
        """
        if params:
            url = "%s?%s" % (url, urllib.parse.urlencode(params))
        if isinstance(datos, dict):
            datos = urllib.parse.urlencode(datos).encode("utf-8")

        for i in range(1, intentos + 1):
            self._esperar()
            try:
                return self._abrir(url, datos, timeout)
            except urllib.error.HTTPError as e:
                if e.code in HTTP_DEFINITIVOS:
                    return None
                if i == intentos:
                    raise ErrorFuente("%s fallo tras %d intentos: HTTP %d"
                                      % (_sin_query(url), intentos, e.code))
            except Exception as e:                        # noqa: BLE001
                if i == intentos:
                    raise ErrorFuente("%s fallo tras %d intentos: %s"
                                      % (_sin_query(url), intentos, e))
            # Retroceso exponencial con tope, como en el paso 0.
            time.sleep(min(2 ** i, 20))


def _sin_query(url):
    """La URL sin su cadena de consulta.

    Los mensajes de error acaban en logs y en la bitacora, y una URL con
    parametros puede llevar un token de sesion.
    """
    return url.split("?")[0]
