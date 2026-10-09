# -*- coding: utf-8 -*-
"""Gestor de trabajos en segundo plano.

Vive en la capa de servicio, arriba del ETL: se apoya en 'db' para la hora
y para abrir conexiones, pero no escribe SQL propio ni imprime. El ETL no
se entera de que existe.

Por que existe: una corrida sobre las consultas reales tarda varios
minutos, mas de lo que aguanta una peticion HTTP sincrona. El endpoint
lanza el trabajo aqui, devuelve de inmediato, y el tablero sondea
estado() para ver el avance.

No importa 'etl' a proposito: recibe el callable a correr, asi que sirve
igual para ingestar(), descargar_fulltext() o lo que venga, y las pruebas
no tienen que arrastrar el ETL para probar la concurrencia.

Un solo trabajo a la vez, y eso no es pereza:

  - El control de tasa de NCBI vive en la instancia de pubmed.Cliente
    (atributo _ultima). Con dos trabajos en paralelo cada uno cree que
    respeta el limite mientras el conjunto lo rebasa. NCBI bloquea por IP,
    no por usuario: un worker mal portado deja sin servicio a todo el
    laboratorio, incluidos los que no estaban usando el sistema.
  - SQLite serializa escrituras. Dos ingestas simultaneas producen
    'database is locked' y una de las dos muere a media corrida.

Cuando exista el limitador compartido (token bucket) y la base sea
Postgres, el tope se podra subir sin tocar a quien llama.

Cancelar es cooperativo. Un trabajo lanzado con cancelable=True recibe un
threading.Event en el kwarg 'detener', y cancelar() solo lo enciende: el
gestor no mata nada, porque un hilo de Python no se puede matar. Quien
hace caso es la función (flujo.correr se lo pasa a cada proceso hijo, que
lo vigila cada medio segundo y mata el árbol entero).
"""

import threading
from collections import deque

from . import db

# Tope de lineas retenidas. Suficiente para seguir una corrida en vivo sin
# que el JSON de estado() crezca sin limite en una corrida de horas.
MAX_LINEAS = 400

# El error con el que queda un trabajo al que se le pidió detenerse. Es
# texto para una persona: lo pinta el tablero.
CANCELADO = "Cancelado a petición"


class TrabajoEnCurso(RuntimeError):
    """Se pidio lanzar un trabajo mientras otro seguia corriendo."""


def _describir_error(e):
    """El texto del error para el tablero, o None si no fue error.

    SystemExit entra aquí porque los CLI del proyecto terminan con
    sys.exit("mensaje"), y no hereda de Exception: dentro del hilo escapaba
    al except, el hilo moría en silencio y el tablero decía «terminó bien».
    sys.exit() y sys.exit(0) sí son salidas limpias.
    """
    if isinstance(e, SystemExit):
        codigo = e.code
        if codigo is None or codigo == 0:
            return None
        if isinstance(codigo, int):
            return f"SystemExit: terminó con código {codigo}"
        return f"SystemExit: {codigo}"
    return f"{type(e).__name__}: {e}"


# Lo que sobrevive a json.dumps sin sorpresas. Los parametros que no
# entran aqui (el pubmed.Cliente, la conexion, el callable log) no se
# publican: no son serializables y no le dicen nada a quien mira el
# tablero.
_SIMPLES = (str, int, float, bool, type(None))


def _publicable(valor):
    if isinstance(valor, _SIMPLES):
        return True
    if isinstance(valor, (list, tuple)):
        return all(_publicable(v) for v in valor)
    return False


class Gestor:
    """Corre un trabajo a la vez en un hilo aparte y guarda su avance.

    ruta_db: si se da, cada trabajo abre su PROPIA conexion dentro del
    hilo y la recibe como kwarg 'con'. sqlite3 prohibe por omision usar
    una conexion desde un hilo distinto al que la creo (lanza
    ProgrammingError), asi que pasarle la conexion del servidor no es
    opcion. Abrirla y cerrarla aqui tambien evita que un trabajo largo
    deje una transaccion abierta estorbando a las lecturas del tablero.

    La funcion que se lance debe devolver algo serializable a JSON:
    etl.ingestar y etl.descargar_fulltext devuelven dicts de contadores.
    """

    def __init__(self, ruta_db=None):
        # Un solo lock para todo el estado mutable. NO se sostiene durante
        # la corrida: si se sostuviera, estado() se bloquearia justo
        # cuando el tablero mas lo consulta. Quien niega la entrada a un
        # segundo trabajo es la bandera _activo, leida y escrita bajo el
        # lock para que la revision y el apartado sean un solo paso.
        self._lock = threading.Lock()
        self._ruta_db = ruta_db
        self._lineas = deque(maxlen=MAX_LINEAS)
        self._hilo = None
        self._activo = False
        self._tipo = None
        self._parametros = {}
        self._iniciado_en = None
        self._terminado_en = None
        self._error = None
        self._resultado = None
        # El evento del trabajo actual si se lanzó cancelable, o None. Se
        # guarda aunque el trabajo termine: estado() lo lee para decir si
        # el último se canceló.
        self._detener = None
        self._cancelado = False

    # ------------------------------------------------------------ lanzar

    def lanzar(self, tipo, funcion, /, *, cancelable=False, **kw):
        """Arranca 'funcion' en un hilo daemon con los kwargs dados.

        tipo es la etiqueta que ve el tablero ('run', 'fulltext', 'flujo').
        La función recibe además un kwarg 'log' que apunta a este gestor.
        Lanza TrabajoEnCurso si ya hay uno corriendo.

        cancelable: si es True, la función recibe también 'detener', un
        threading.Event que cancelar() enciende. Pisa cualquier 'detener'
        que venga en kw, igual que 'con': el evento que cuenta es el que el
        gestor puede encender. No se publica en estado().

        La barra deja 'tipo' y 'funcion' como posicionales-only (Python
        3.8+). Sin ella no se puede lanzar etl.descargar_fulltext, que
        tiene su propio parámetro 'tipo' ('xml' / 'pdf'): la llamada
        chocaría con el de aquí y saldría un TypeError. Un despachador
        genérico no puede reservarse nombres de uso común. 'cancelable' sí
        queda reservado, y por eso es de solo palabra clave.

        El hilo es daemon para que un Ctrl-C en el servidor no se quede
        esperando a que termine una descarga de media hora.
        """
        with self._lock:
            if self._activo:
                raise TrabajoEnCurso(
                    f"ya hay un trabajo '{self._tipo}' en curso; "
                    f"espera a que termine")

            # Los parámetros se toman antes de inyectar el evento: no es
            # un dato para quien mira el tablero, y json.dumps no lo sabe
            # serializar.
            parametros = {k: v for k, v in kw.items() if _publicable(v)}
            detener = threading.Event() if cancelable else None
            if detener is not None:
                kw["detener"] = detener

            self._activo = True
            self._tipo = tipo
            self._parametros = parametros
            self._detener = detener
            self._cancelado = False
            self._iniciado_en = db.ahora()
            self._terminado_en = None
            self._error = None
            self._resultado = None
            self._lineas.clear()

            hilo = threading.Thread(
                target=self._correr, args=(funcion, kw),
                name=f"trabajo-{tipo}", daemon=True,
            )

            # start() va DENTRO del candado, y _hilo se publica solo si
            # arranco. Si se publicara antes, esperar() podria alcanzarlo
            # sin arrancar y join() truena con 'cannot join thread before
            # it is started'. Sostener el candado un instante mas es
            # barato: lo unico que espera es otro lanzar() o un estado().
            try:
                hilo.start()
            except Exception:
                # start() falla cuando el sistema operativo no da mas
                # hilos. La bandera ya quedo puesta arriba y aqui no hay
                # hilo que la baje en su finally: sin esto el gestor queda
                # apartado por un trabajo que nunca corrio, y nadie puede
                # lanzar nada hasta reiniciar el servidor.
                self._activo = False
                self._terminado_en = db.ahora()
                self._error = "no se pudo arrancar el hilo del trabajo"
                raise

            self._hilo = hilo

    def esperar(self, timeout=None):
        """Bloquea hasta que el trabajo actual termine. True si termino.

        Para el cierre ordenado del servidor y para las pruebas, que no
        deben sondear con sleeps.
        """
        with self._lock:
            hilo = self._hilo
        if hilo is None:
            return True
        hilo.join(timeout)
        return not hilo.is_alive()

    def cancelar(self):
        """Pide detener el trabajo en curso. True si había uno cancelable.

        No espera ni mata nada: enciende el evento que la función recibió
        en 'detener' y vuelve. Quien quiera esperar a que se detenga llama
        a esperar(). Pedirlo dos veces no es error: mientras el trabajo
        siga vivo, la segunda también devuelve True.
        """
        with self._lock:
            if not self._activo or self._detener is None:
                return False
            if not self._detener.is_set():
                self._detener.set()
                # Directo al deque y no por _anotar(): el candado ya está
                # tomado y no es reentrante.
                self._lineas.append({
                    "t": db.ahora(),
                    "texto": "Cancelación pedida; esperando a que el "
                             "trabajo se detenga."})
            return True

    # ------------------------------------------------------------- estado

    def estado(self):
        """Retrato del trabajo actual o del ultimo, listo para json.dumps.

        Devuelve copias: el hilo del trabajo sigue escribiendo lineas
        mientras el del HTTP serializa lo que se lleva. Sin la copia, el
        deque puede mutar a media serializacion.

        cancelable dice si el trabajo se lanzó cancelable (vale también
        para el último, ya terminado); cancelando, que se pidió detenerlo y
        sigue vivo; cancelado, que terminó después de pedirlo.
        """
        with self._lock:
            detener = self._detener
            return {
                "activo": self._activo,
                "tipo": self._tipo,
                "cancelable": detener is not None,
                "cancelando": bool(self._activo and detener is not None
                                   and detener.is_set()),
                "cancelado": self._cancelado,
                "parametros": {
                    k: (list(v) if isinstance(v, (list, tuple)) else v)
                    for k, v in self._parametros.items()
                },
                "iniciado_en": self._iniciado_en,
                "terminado_en": self._terminado_en,
                "error": self._error,
                "resultado": (dict(self._resultado)
                              if isinstance(self._resultado, dict)
                              else self._resultado),
                "lineas": [dict(l) for l in self._lineas],
            }

    # -------------------------------------------------------------- hilo

    def _anotar(self, texto):
        """Es el callable 'log' que recibe el ETL. Lo llama el otro hilo."""
        with self._lock:
            self._lineas.append({"t": db.ahora(), "texto": str(texto)})

    def _correr(self, funcion, kw):
        resultado = None
        error = None
        con = None
        try:
            if self._ruta_db is not None:
                # Pisa cualquier 'con' que venga de fuera a proposito: una
                # conexion abierta en otro hilo truena con ProgrammingError
                # de sqlite3 en la primera consulta.
                con = db.conectar(self._ruta_db)
                kw["con"] = con
            kw["log"] = self._anotar
            resultado = funcion(**kw)
        except (Exception, SystemExit) as e:
            # Un trabajo que truena no puede dejar el gestor apartado: si
            # se quedara activo, nadie del laboratorio podria lanzar nada
            # hasta reiniciar el servidor. De ahi el finally.
            error = _describir_error(e)
            # Si se pidió cancelar, lo que la función lance al detenerse (el
            # hijo muerto, su excepción de cancelado) es la consecuencia
            # esperada y no un error que haya que gritar en la consola.
            if error is not None and not self._se_pidio_cancelar():
                self._anotar(f"ERROR: {error}")
        finally:
            if con is not None:
                con.close()
            with self._lock:
                # Se decide por el evento y no por el tipo de excepción: el
                # gestor no sabe qué corre, y una función puede hacer caso
                # de la cancelación volviendo antes en vez de lanzar.
                cancelado = (self._detener is not None
                             and self._detener.is_set())
                if cancelado:
                    error = CANCELADO
                    self._lineas.append({"t": db.ahora(),
                                         "texto": CANCELADO + "."})
                self._resultado = resultado
                self._error = error
                self._cancelado = cancelado
                self._terminado_en = db.ahora()
                self._activo = False

    def _se_pidio_cancelar(self):
        with self._lock:
            return self._detener is not None and self._detener.is_set()
