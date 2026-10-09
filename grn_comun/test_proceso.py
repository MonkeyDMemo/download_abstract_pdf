# -*- coding: utf-8 -*-
"""Pruebas de `grn_comun.proceso`: la salida llega entera y cancelar mata todo.

La que no puede faltar es la del nieto. El paso `biobert` lanza
`clasificar.py`, y un `terminate()` a secas en Windows mata solo al hijo: el
nieto seguía clasificando, con la base abierta, después de que el tablero
decía «cancelado».

    python -m unittest discover .
"""

import ast
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_comun import proceso   # noqa: E402

PY = sys.executable


def _vivo(pid):
    """Si el proceso sigue vivo. `os.kill(pid, 0)` no sirve en Windows."""
    if os.name == "nt":
        salida = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
        return str(pid).encode() in salida
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class PruebasSalida(unittest.TestCase):

    def test_las_lineas_llegan_en_orden_y_con_acentos(self):
        lineas = []
        r = proceso.correr(
            [PY, "-c", "print('señal'); print('ñandú'); print('σ fuera de cp1252')"],
            log=lineas.append)
        self.assertEqual(r["codigo"], 0)
        self.assertEqual(lineas, ["señal", "ñandú", "σ fuera de cp1252"])

    def test_un_codigo_no_aceptado_es_error_con_las_ultimas_lineas(self):
        with self.assertRaises(proceso.ErrorProceso) as ctx:
            proceso.correr([PY, "-c", "print('antes'); import sys; sys.exit(3)"])
        self.assertEqual(ctx.exception.codigo, 3)
        self.assertEqual(ctx.exception.ultimas, ["antes"])
        self.assertIn("antes", str(ctx.exception))

    def test_codigos_ok_acepta_resultados_que_no_son_cero(self):
        r = proceso.correr([PY, "-c", "import sys; sys.exit(2)"],
                           codigos_ok=(0, 2))
        self.assertEqual(r["codigo"], 2)

    def test_respeta_cwd_y_entorno(self):
        with tempfile.TemporaryDirectory() as carpeta:
            lineas = []
            proceso.correr(
                [PY, "-c", "import os; print(os.getcwd()); print(os.environ['X_PRUEBA'])"],
                log=lineas.append, cwd=carpeta, entorno={"X_PRUEBA": "valor"})
            self.assertEqual(os.path.normcase(os.path.realpath(lineas[0])),
                             os.path.normcase(os.path.realpath(carpeta)))
            self.assertEqual(lineas[1], "valor")

    def test_archivo_log_recibe_lo_mismo_que_el_log(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "paso.log")
            proceso.correr([PY, "-c", "print('uno'); print('dos')"],
                           archivo_log=ruta)
            with open(ruta, encoding="utf-8") as f:
                self.assertEqual(f.read(), "uno\ndos\n")


class PruebasCancelar(unittest.TestCase):

    def test_cancelar_mata_al_hijo_y_al_nieto(self):
        self._cancelar_con_nieto(
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', %r]); "
            "print('hijo listo', flush=True); time.sleep(60)")

    def test_cancelar_alcanza_al_nieto_lanzado_con_correr(self):
        """Así es el paso `biobert`: el CLI lanza `clasificar.py` con
        `proceso.correr`. En Linux, con sesión propia, el nieto quedaba fuera
        del grupo que mata el flujo y seguía con la GPU; por eso el CLI lo
        lanza con `nueva_sesion=False`."""
        self._cancelar_con_nieto(
            "import sys, time; from grn_comun import proceso; "
            "proceso.correr([sys.executable, '-c', %r], nueva_sesion=False)",
            entorno={"PYTHONPATH": _RAIZ})

    def _cancelar_con_nieto(self, plantilla_hijo, entorno=None):
        with tempfile.TemporaryDirectory() as carpeta:
            marca = os.path.join(carpeta, "nieto.pid")
            nieto = ("import os, time; "
                     "open(%r, 'w').write(str(os.getpid())); "
                     "time.sleep(60)" % marca)
            hijo = plantilla_hijo % nieto
            detener = threading.Event()
            errores = []

            def lanzar():
                try:
                    proceso.correr([PY, "-c", hijo], detener=detener,
                                   entorno=entorno)
                except BaseException as e:   # noqa: BLE001
                    errores.append(e)

            hilo = threading.Thread(target=lanzar)
            hilo.start()
            limite = time.monotonic() + 20
            while not os.path.exists(marca) and time.monotonic() < limite:
                time.sleep(0.1)
            self.assertTrue(os.path.exists(marca), "el nieto no arrancó")
            time.sleep(0.3)
            with open(marca) as f:
                pid_nieto = int(f.read())
            self.assertTrue(_vivo(pid_nieto))

            inicio = time.monotonic()
            detener.set()
            hilo.join(15)
            self.assertFalse(hilo.is_alive())
            self.assertLess(time.monotonic() - inicio, 10)
            self.assertEqual(len(errores), 1)
            self.assertIsInstance(errores[0], proceso.Cancelado)
            limite = time.monotonic() + 5
            while _vivo(pid_nieto) and time.monotonic() < limite:
                time.sleep(0.2)
            self.assertFalse(_vivo(pid_nieto), "el nieto quedó vivo")


class PruebasMatarSinGrupoPropio(unittest.TestCase):

    @unittest.skipIf(os.name == "nt", "en Windows taskkill /T recorre el árbol")
    def test_un_hijo_que_no_encabeza_su_grupo_muere_sin_esperar(self):
        """Así queda clasificar.py, lanzado con nueva_sesion=False: un killpg
        con su pid no encontraba grupo y se esperaban 15 s."""
        proc = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        inicio = time.monotonic()
        proceso.matar_arbol(proc)
        self.assertIsNotNone(proc.poll())
        self.assertLess(time.monotonic() - inicio, 4)


class PruebasCompatibilidad(unittest.TestCase):

    def test_se_lee_con_la_gramatica_de_python_3_8(self):
        ruta = os.path.join(_RAIZ, "grn_comun", "proceso.py")
        with open(ruta, encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
