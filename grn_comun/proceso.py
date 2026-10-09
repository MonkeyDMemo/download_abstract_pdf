"""Correr un programa hijo y llevar su salida, línea por línea, a un `log`.

Lo usan el flujo (`flujo.py`) y el tablero para lanzar los pasos que ya tienen
su propio CLI: el bronce, los operones, `etapa2/clasificar.py`. Correrlos como
procesos aparte, y no importarlos, tiene tres razones:

- algunos necesitan otro intérprete (`clasificar.py` importa torch; la sintaxis
  vive en `.venv-nlp`, con otro numpy);
- sus CLI terminan con `sys.exit`, que dentro de un hilo del tablero se tragaba
  el error y la corrida aparecía como «terminó bien»;
- un proceso se puede matar; un hilo de Python no.

Biblioteca estándar y Python 3.8, como el resto del núcleo.
"""

import collections
import os
import signal
import subprocess
import threading
import time

# Cuántas líneas finales viajan en el error. Las suficientes para ver el
# traceback de un hijo que murió, no tantas como para tapar el mensaje.
ULTIMAS = 20


class ErrorProceso(RuntimeError):
    """El hijo terminó con un código que no estaba en `codigos_ok`."""

    def __init__(self, argv, codigo, ultimas):
        self.argv = list(argv)
        self.codigo = codigo
        self.ultimas = list(ultimas)
        cola = "\n".join(self.ultimas[-ULTIMAS:])
        super().__init__("%s terminó con código %s.%s" % (
            os.path.basename(_nombre(self.argv)), codigo,
            ("\nÚltimas líneas:\n" + cola) if cola else ""))


class Cancelado(RuntimeError):
    """Se pidió detener y el árbol del hijo se mató."""


def _nombre(argv):
    """El nombre legible del programa: `-m paquete` o el script, no python."""
    if "-m" in argv:
        i = argv.index("-m")
        if i + 1 < len(argv):
            return argv[i + 1]
    for parte in argv[1:]:
        if parte.endswith(".py"):
            return parte
    return argv[0]


def matar_arbol(proc):
    """Mata al hijo y a todos sus descendientes.

    No basta `proc.terminate()`: el paso `biobert` lanza a su vez
    `clasificar.py`, y en Windows `terminate()` solo mata al hijo directo; el
    nieto se quedaba clasificando en segundo plano, con la GPU o la CPU
    ocupadas y la base abierta. `taskkill /T` recorre el árbol; en POSIX el hijo
    nace en su propia sesión y se mata el grupo entero, que incluye a los
    nietos lanzados con `correr(..., nueva_sesion=False)`.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # Un hijo lanzado con nueva_sesion=False no encabeza su grupo: un
        # killpg con su pid no encuentra grupo, y antes se esperaban 5 s más
        # 10 s hasta el proc.kill() final. Se le manda la señal a él solo.
        try:
            lider = os.getpgid(proc.pid) == proc.pid
        except ProcessLookupError:
            lider = False

        def senal(sig):
            try:
                if lider:
                    os.killpg(proc.pid, sig)
                else:
                    os.kill(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

        senal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            senal(signal.SIGKILL)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def correr(argv, log=lambda m: None, detener=None, cwd=None, entorno=None,
           codigos_ok=(0,), archivo_log=None, nueva_sesion=True):
    """Corre `argv`, manda cada línea de su salida a `log` y devuelve
    `{"codigo", "segundos"}`.

    - `detener`: un `threading.Event`. Si se activa, se mata el árbol completo
      y se lanza `Cancelado`. Lo revisa un hilo vigía cada medio segundo, así
      que cancelar no espera a que el hijo escriba otra línea.
    - `codigos_ok`: los códigos que no son error. `evaluar_oro.py` sale con 2
      cuando la red no le gana a la línea base, y eso es un resultado.
    - `archivo_log`: además del `log`, anexa cada línea a ese archivo. El
      gestor del tablero guarda solo las últimas 400 líneas.
    - `nueva_sesion`: en POSIX, si el hijo nace en su propia sesión (y su
      propio grupo). Es lo correcto para un paso del flujo, que se cancela con
      `killpg` sobre ese grupo. Un proceso que a su vez lanza un nieto con
      `correr` (el paso `biobert` lanza `clasificar.py`) tiene que pasar
      `False`: si no, el nieto queda en otro grupo, el `killpg` del flujo no
      lo alcanza y sigue con la GPU. En Windows no cambia nada: `taskkill /T`
      recorre el árbol entero.

    `argv` se publica en el tablero: nunca debe llevar credenciales.
    """
    env = dict(os.environ)
    env.update(entorno or {})
    # El hijo escribe UTF-8 aunque la consola de Windows sea cp1252: si no, una
    # «ñ» o una sigma en la salida de un paso tumba la lectura de esta tubería.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    extra = {}
    if os.name == "nt":
        extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    elif nueva_sesion:
        extra["start_new_session"] = True

    inicio = time.monotonic()
    proc = subprocess.Popen(
        [str(a) for a in argv], cwd=cwd, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
        bufsize=1, **extra)

    cancelado = threading.Event()

    def vigia():
        while proc.poll() is None:
            if detener.wait(0.5):
                cancelado.set()
                matar_arbol(proc)
                return

    if detener is not None:
        threading.Thread(target=vigia, daemon=True).start()

    ultimas = collections.deque(maxlen=ULTIMAS)
    archivo = (open(archivo_log, "a", encoding="utf-8")
               if archivo_log else None)
    try:
        for linea in proc.stdout:
            linea = linea.rstrip("\r\n")
            ultimas.append(linea)
            log(linea)
            if archivo is not None:
                archivo.write(linea + "\n")
                archivo.flush()
        codigo = proc.wait()
    except BaseException:
        # Ctrl-C en la terminal, o un `log` que falló: el hijo no puede quedarse
        # huérfano. Con CREATE_NEW_PROCESS_GROUP no recibe el Ctrl-C del padre.
        matar_arbol(proc)
        raise
    finally:
        if archivo is not None:
            archivo.close()
        if proc.stdout is not None:
            proc.stdout.close()

    if cancelado.is_set():
        raise Cancelado("Cancelado a petición: %s" % _nombre(argv))
    if codigo not in codigos_ok:
        raise ErrorProceso(argv, codigo, ultimas)
    return {"codigo": codigo,
            "segundos": round(time.monotonic() - inicio, 1)}
