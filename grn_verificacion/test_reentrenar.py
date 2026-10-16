"""Pruebas del orquestador de la pista D, sin GPU y con datos SINTÉTICOS.

El script del asesor, torch, transformers y nvidia-smi son falsos: viven en
una carpeta temporal y entran por PYTHONPATH y PATH. Lo que se prueba es lo
que el orquestador promete: que detecta los fallos que barrido.py calla, que
detener y el tope matan el árbol entero, que se salta lo hecho, y que nada de
lo que ve la sesión (estado, log, informe) lleva contenido de la base.
"""

import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from grn_verificacion import cli
from grn_verificacion import entrenamiento as E
from grn_verificacion import reentrenar as R
from grn_verificacion.test_entrenamiento import (CODIGOS, PMID_AJENO,
                                                 PMID_BASE, _corpus, par)
from grn_verificacion.test_validacion import construir_xlsx

POSIX = os.name != "nt" and os.path.isdir("/proc")

TORCH_FALSO = '''
import os
__version__ = "0.0-falso"
class _Cuda:
    @staticmethod
    def is_available():
        return os.environ.get("FALSO_CUDA", "1") == "1"
    @staticmethod
    def get_device_name(i):
        return "GPU falsa"
cuda = _Cuda()
'''

TRANSFORMERS_FALSO = '''
import os
__version__ = "0.0-falso"
def _revisar():
    if os.environ.get("FALSO_SIN_MODELO") == "1":
        raise OSError("sin red")
class AutoTokenizer:
    @classmethod
    def from_pretrained(cls, nombre, **kw):
        _revisar()
        return cls()
    def __call__(self, texto):
        return {"input_ids": texto.split()}
class AutoModelForSequenceClassification:
    @classmethod
    def from_pretrained(cls, nombre, **kw):
        _revisar()
        return cls()
'''

NVIDIA_FALSO = '''#!%s
import os, sys
if os.environ.get("FALSO_GPU_FALLA") == "1":
    sys.exit(9)
libre = int(os.environ.get("FALSO_GPU_LIBRE", "7000"))
print("8192, %%d, %%d" %% (8192 - libre, libre))
'''

SCRIPT_FALSO = '''
import argparse, json, os, subprocess, sys, time
ap = argparse.ArgumentParser()
for flag in ("--train_jsonl", "--dev_jsonl", "--test_jsonl", "--labels_json",
             "--out_dir", "--model_name"):
    ap.add_argument(flag)
args, _ = ap.parse_known_args()
modo = os.environ.get("FALSO_MODO", "ok")
if modo == "terco":
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    modo = "lento"
if os.environ.get("FALSO_CUENTA"):
    with open(os.environ["FALSO_CUENTA"], "a") as f:
        f.write("x\\n")
os.makedirs(args.out_dir, exist_ok=True)
# Como un traceback del script real que trajera un ejemplo: si el filtro se
# desconecta, esto llega a lo que ve la sesión.
print("Ejemplo: <e1> QzaaR </e1> regula <e2> wvaaA </e2> (PMID 30000001, "
      "PA1000) en " + args.train_jsonl, flush=True)
if modo == "oom":
    print("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate "
          "20.00 MiB", flush=True)
    sys.exit(1)
if modo == "lento":
    nieto = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(120)"])
    with open(os.environ["FALSO_PIDS"] + ".tmp", "w") as f:
        f.write("%d %d" % (os.getpid(), nieto.pid))
    os.replace(os.environ["FALSO_PIDS"] + ".tmp", os.environ["FALSO_PIDS"])
    time.sleep(120)
    sys.exit(0)
with open(args.labels_json) as f:
    etiquetas = json.load(f)
if modo == "id2label_mal":
    etiquetas = list(reversed(etiquetas))
historial = [
    {"loss": 1.2, "epoch": 0.5, "step": 5},
    {"eval_loss": 1.0, "eval_macro_f1": 0.61, "eval_accuracy": 0.7,
     "epoch": 1.0, "step": 10},
    {"loss": 0.9, "epoch": 1.5, "step": 15},
    {"eval_loss": 1.1, "eval_macro_f1": 0.58, "eval_accuracy": 0.68,
     "epoch": 2.0, "step": 20},
]
for paso, n in ((10, 2), (20, 4)):
    cp = os.path.join(args.out_dir, "checkpoint-%d" % paso)
    os.makedirs(cp, exist_ok=True)
    with open(os.path.join(cp, "trainer_state.json"), "w") as f:
        json.dump({"best_metric": 0.61, "global_step": paso,
                   "epoch": paso / 10.0, "log_history": historial[:n],
                   "best_model_checkpoint":
                       os.path.join(args.out_dir, "checkpoint-10")}, f)
with open(os.path.join(args.out_dir, "pytorch_model.bin"), "wb") as f:
    f.write(b"falso")
with open(os.path.join(args.out_dir, "config.json"), "w") as f:
    json.dump({"id2label": dict((str(i), e)
                                for i, e in enumerate(etiquetas))}, f)
metricas = {"eval_loss": 1.0, "eval_accuracy": 0.7, "eval_macro_f1": 0.61,
            "eval_precision": 0.6, "eval_recall": 0.62, "eval_runtime": 1.0,
            "eval_samples_per_second": 100.0, "eval_steps_per_second": 7.0,
            "epoch": 2.0}
with open(os.path.join(args.out_dir, "eval_metrics.json"), "w") as f:
    json.dump(metricas, f)
with open(os.path.join(args.out_dir, "test_metrics.json"), "w") as f:
    json.dump(dict(metricas, eval_macro_f1=0.55), f)
print("Done. Best model in:", args.out_dir)
'''

ORACION_RESERVADA = "QzjbR  controls nyjbC after florbination jb."


def _escribir(ruta, texto, modo=None):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    if modo:
        os.chmod(ruta, modo)
    return ruta


class _Escenario(unittest.TestCase):
    """Una raíz temporal con base, pares, reservas y los falsos."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grn_reent_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        entrada = os.path.join(self.tmp, "entrada")
        os.makedirs(entrada)
        filas, pares, self.nombres = _corpus()
        self.base = construir_xlsx(os.path.join(entrada, "base.xlsx"),
                                   [("Hoja1", filas)])
        self.pares = os.path.join(entrada, "pares.jsonl")
        with open(self.pares, "w", encoding="utf-8") as f:
            for p in pares:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        # Las reservas de verdad (la muestra de juicios, que el orquestador
        # exige) más una del corpus de juguete.
        self.reservas = [os.path.join(entrada, "reservas.tsv"),
                         os.path.join(entrada, "reservas_juguete.tsv")]
        E.escribir_reservas_de_juicios(self.reservas[0])
        E.escribir_reservas(self.reservas[1], [PMID_BASE + 29],
                            [ORACION_RESERVADA])
        self.ciego = _escribir(
            os.path.join(entrada, "ciego.tsv"),
            "tf\tblanco\toracion\nQzaaR\twvaaA\tx\nQzbaR\twvbaA\ty\n")
        falsos = os.path.join(self.tmp, "falsos")
        _escribir(os.path.join(falsos, "py", "torch", "__init__.py"),
                  TORCH_FALSO)
        _escribir(os.path.join(falsos, "py", "transformers", "__init__.py"),
                  TRANSFORMERS_FALSO)
        _escribir(os.path.join(falsos, "bin", "nvidia-smi"),
                  NVIDIA_FALSO % sys.executable, 0o755)
        self.script = _escribir(os.path.join(falsos, "script_falso.py"),
                                SCRIPT_FALSO)
        self.cuenta = os.path.join(self.tmp, "llamadas.txt")
        self.pids = os.path.join(self.tmp, "pids.txt")
        self.raiz = os.path.join(self.tmp, "raiz")
        self.entorno = {
            "PATH": os.path.join(falsos, "bin") + os.pathsep
            + os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join(
                [os.path.join(falsos, "py"), E.RAIZ_REPO]),
            "FALSO_CUENTA": self.cuenta,
            "FALSO_PIDS": self.pids,
            "FALSO_MODO": "ok",
        }
        parche = mock.patch.dict(os.environ, self.entorno)
        parche.start()
        self.addCleanup(parche.stop)
        for llave in ("HF_HOME", "GRN_PYTHON_BERT", R.DESPRENDIDO,
                      R.HOJA_ENTORNO):
            os.environ.pop(llave, None)
        # /tmp puede ser un tmpfs chico; el disco se prueba aparte.
        disco = mock.patch.object(R, "DISCO_MIN_GIB", 0)
        disco.start()
        self.addCleanup(disco.stop)
        self.r = R.rutas(self.raiz, "curada-v1")
        # Si una prueba falla a la mitad, barrido.py, el script falso y su
        # nieto llevan la marca: se matan aquí, antes del rmtree del temporal
        # (los addCleanup corren al revés).
        self.addCleanup(self._limpiar)

    def _limpiar(self):
        try:
            R.matar_huerfanos(self.r["runs"])
        except R.Ocupado as e:
            R.detener_corrida(self.raiz, "curada-v1", esperar=5)
            try:
                os.kill(int(e.pid), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def correr(self, **kwargs):
        kwargs.setdefault("aceptar_base_distinta", True)
        kwargs.setdefault("ciego", self.ciego)
        lineas = []
        estado = R.ejecutar(self.raiz, "curada-v1", self.base, self.pares,
                            self.reservas, self.script,
                            python=sys.executable, log=lineas.append,
                            **kwargs)
        return estado, lineas

    def llamadas(self):
        if not os.path.exists(self.cuenta):
            return 0
        with open(self.cuenta) as f:
            return len(f.read().split())

    def leer(self, ruta):
        with open(ruta, encoding="utf-8") as f:
            return f.read()

    def popen_cli(self, *extra, **kwargs):
        """La CLI como proceso, con SIGINT y SIGHUP en su valor por omisión:
        si el proceso de pruebas los ignora, el hijo los heredaría ignorados
        y la CLI los respetaría (es lo que hace con `nohup`)."""
        def preparar():
            for sig in (signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, signal.SIG_DFL)
            if kwargs.get("ignorar_sighup"):
                signal.signal(signal.SIGHUP, signal.SIG_IGN)
        proc = subprocess.Popen(self.argv_cli(*extra), cwd=E.RAIZ_REPO,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                preexec_fn=preparar)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc

    def correr_cli(self, *extra):
        return subprocess.run(self.argv_cli(*extra), cwd=E.RAIZ_REPO,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,
                              universal_newlines=True, timeout=60)

    def argv_cli(self, *extra):
        return [sys.executable, "-m", "grn_verificacion.cli", "reentrenar",
                "correr", "--raiz", self.raiz, "--base", self.base,
                "--pares", self.pares, "--reservar", self.reservas[0],
                "--reservar", self.reservas[1], "--script", self.script,
                "--python", sys.executable,
                "--aceptar-base-distinta"] + list(extra)

    def esperar_pids(self, limite=30):
        fin = time.monotonic() + limite
        while time.monotonic() < fin:
            if os.path.exists(self.pids):
                with open(self.pids) as f:
                    return [int(x) for x in f.read().split()]
            time.sleep(0.2)
        self.fail("El script falso nunca arrancó.")

    def assertMuertos(self, pids, limite=15):
        fin = time.monotonic() + limite
        while time.monotonic() < fin and any(R._vivo(p) for p in pids):
            time.sleep(0.2)
        self.assertFalse([p for p in pids if R._vivo(p)],
                         "quedaron procesos vivos")


# ---------------------------------------------------------- piezas puras

class PruebasPiezas(unittest.TestCase):

    def test_cotejo_de_la_base(self):
        medida = {"filas": 5584, "homologia": 2850, "pmids_distintos": 310,
                  "dois_descartados": 1,
                  "signo": {"+": 4060, "-": 598, "?": 909, "d": 14,
                            "ilegible": 3},
                  "origen": {"historica": 4824, "biobert": 544, "ambos": 216,
                             "otro": 0}}
        self.assertTrue(all(f[3] for f in R.filas_cotejo(medida)))
        medida["origen"]["otro"] = 2
        distintas = [f for f in R.filas_cotejo(medida) if not f[3]]
        self.assertEqual([["origen otro", 0, 2, False]], distintas)

    def test_macro_f1_como_sklearn(self):
        y = ["a", "a", "b", "b", "c"]
        yhat = ["a", "b", "b", "b", "a"]
        # a: p 1/2 r 1/2 f 0.5; b: p 2/3 r 1 f 0.8; c: 0.
        self.assertAlmostEqual((0.5 + 0.8 + 0.0) / 3, R.macro_f1(y, yhat))
        # Una etiqueta que solo aparece en las predicciones cuenta, con F1 0:
        # a tiene p 1, r 1/2, f 2/3; d, 0.
        self.assertAlmostEqual(1.0 / 3, R.macro_f1(["a", "a"], ["a", "d"]))
        self.assertEqual(0.0, R.macro_f1([], []))

    def test_linea_base_de_memorizacion(self):
        def ej(tf, tg, label):
            return {"tf": tf, "target": tg, "label": label}
        entrena = [ej("A", "b", "activates"), ej("A", "b", "activates"),
                   ej("C", "d", "no_relation"), ej("C", "d", "no_relation"),
                   ej("C", "d", "no_relation")]
        prueba = [ej("a", "B", "activates"), ej("C", "d", "represses"),
                  ej("X", "y", "no_relation")]
        r = R.linea_base_memorizacion(entrena, prueba, R._por_nombre)
        self.assertEqual(3, r["n"])
        self.assertEqual(2, r["con_par_en_train"])
        self.assertEqual(0.5, r["acierto_en_cubiertos"])
        # a-b -> activates (bien); C-d -> no_relation (mal); X-y ->
        # mayoritaria no_relation (bien).
        self.assertAlmostEqual(0.6667, r["accuracy"], places=4)
        self.assertEqual(3, R.linea_base_memorizacion(
            entrena, prueba, lambda e: None)["sin_llave"])

    def test_avisos_de_particionar(self):
        lineas = [
            "  parte          n  arts  activates   no_relation regulates   "
            "represses  ",
            "  train         40    20    10  25.0%   10  25.0%   10  25.0%   "
            "10  25.0%",
            "  test           6     3     2  33.3%    2  33.3%    2  33.3%    "
            "0   0.0%",
            "  AVISO: test no tiene ningun ejemplo de represses: el F1 de esa "
            "clase ahi no se mide.",
            "  La celda mas flaca: regulates en dev son 2 ejemplos, pero de "
            "solo 1 articulos",
            "  AVISO: con menos de 5 articulos independientes el F1 de esa "
            "clase es ruido,",
            "  dev               0.0%      0   50.0%      12.5%",
            "     AVISO: 1 ejemplos de dev tienen su ventana contenida en una "
            "de train (peor 0.90).",
            "Particion limpia. Escrita en <datos>/por_pmid",
        ]
        a = R.avisos_particion(lineas)
        self.assertEqual({"n": 6, "articulos": 3, "por_clase": {
            "activates": 2, "no_relation": 2, "regulates": 2,
            "represses": 0}}, a["tabla"]["test"])
        self.assertEqual([["test", "represses"]], a["clases_vacias"])
        self.assertEqual("dev", a["celda_flaca"]["parte"])
        self.assertTrue(a["menos_de_5_articulos"])
        self.assertEqual({"n": 1, "peor": 0.9}, a["casi_dup"]["dev"])
        self.assertEqual(50.0, a["fuga"]["dev"]["par"])
        self.assertTrue(a["limpia"])
        self.assertTrue(a["recomendar_cv"])
        self.assertFalse(R.avisos_particion(
            ["PARTICION RECHAZADA: quedo fuga."])["limpia"])

    def test_tokens_y_motivo_de_fallo(self):
        t = R.tokens_de(["Longitud en tokens: mediana=40  p95=90  max=300  "
                         "(techo 512)", "  Ninguno se trunca."])
        self.assertEqual({"mediana": 40, "p95": 90, "max": 300,
                          "truncados": 0}, t)
        self.assertEqual(7, R.tokens_de(
            ["  AVISO: 7 ejemplos se truncan y pierden texto."])["truncados"])
        self.assertEqual("sin_memoria_gpu", R.motivo_de_fallo(
            ["RuntimeError: CUDA out of memory. Tried"], 1))
        self.assertEqual("matado", R.motivo_de_fallo([], -9))
        self.assertEqual("script_fallo", R.motivo_de_fallo(["x"], 1))
        # Sin memoria al arrancar: la GPU la tiene otro, no es que no quepa.
        for linea in ("RuntimeError: CUDA error: out of memory",
                      "RuntimeError: CUDA error: CUBLAS_STATUS_ALLOC_FAILED "
                      "when calling `cublasCreate(handle)`"):
            self.assertEqual("gpu_ocupada", R.motivo_de_fallo([linea], 1))

    def test_el_filtro(self):
        r = R.rutas("/srv/cuenta/grn", "curada-v1")
        san = R.Saneador(r, extra=[("/srv/cuenta/grn/base.xlsx", "<base>")])
        self.assertEqual(
            "Escritos 5 ejemplos en <datos>. Particion <datos>/por_pmid",
            san.linea("Escritos 5 ejemplos en /srv/cuenta/grn/datos/curada-v1."
                      " Particion /srv/cuenta/grn/datos/curada-v1/por_pmid"))
        self.assertEqual("<base>", san.linea("/srv/cuenta/grn/base.xlsx"))
        for mala in ("gen PA1234 aquí", "<e1> LasR </e1> activa",
                     "pmid 12345678 suelto", "pmid 1234567."):
            self.assertIsNone(san.linea(mala), mala)
        for buena in ("huella 1234567a9b0c1d2e", "f1 0.12345678",
                      "commit 1a2b3c4d5e", "2026-10-09T10:00:00Z",
                      "semilla 20260819", "lr 2.9999999999999997e-05"):
            self.assertIsNotNone(san.linea(buena), buena)
        self.assertLessEqual(len(san.linea("x" * 1000)), R.LARGO_LINEA + 1)

    def test_verificar_publicable_no_repite_el_texto(self):
        R.verificar_publicable(
            "# Título\n| a | 0.5 |\n`<datos>/por_pmid`\n`<runs>/run_22`\n"
            "sobre `dmis-lab/biobert-base-cased-v1.1`, reparto 80/10/10")
        for malo, patron in (("ver /home/cuenta/x", "ruta absoluta"),
                             ("en /tmp/x/reservas.tsv, línea 5",
                              "ruta absoluta"),
                             ("de /srv/lab/datos", "ruta absoluta"),
                             ("'~/miniforge3/bin/python'", "ruta absoluta"),
                             ("PA0001 y más", "locus"),
                             ("<e2>x</e2>", "marcador"),
                             ("pmid 31415926", "PMID")):
            with self.assertRaises(ValueError) as ctx:
                R.verificar_publicable("ok\n" + malo)
            self.assertIn(patron, str(ctx.exception))
            self.assertIn("línea 2", str(ctx.exception))
            self.assertNotIn(malo, str(ctx.exception))

    def test_reservas_incompletas(self):
        tmp = tempfile.mkdtemp(prefix="grn_res_")
        self.addCleanup(shutil.rmtree, tmp, True)
        solo_pmids = os.path.join(tmp, "r.tsv")
        pmids, _ = E.reservas_de_csv(E.RUTA_JUICIOS, "pmid", "oracion")
        E.escribir_reservas(solo_pmids, pmids, [])
        v = R.verificar_reservas([solo_pmids])
        self.assertEqual(0, v["faltan_pmids"])
        self.assertEqual(50, v["faltan_oraciones"])
        completas = os.path.join(tmp, "c.tsv")
        E.escribir_reservas_de_juicios(completas)
        v = R.verificar_reservas([completas])
        self.assertEqual((0, 0), (v["faltan_pmids"], v["faltan_oraciones"]))

    def test_fuga_por_locus_ve_lo_que_los_nombres_no(self):
        """Un operón y su gen tienen nombres distintos y el mismo locus."""
        tmp = tempfile.mkdtemp(prefix="grn_fuga_")
        self.addCleanup(shutil.rmtree, tmp, True)
        datos, part = os.path.join(tmp, "datos"), os.path.join(tmp, "part")
        os.makedirs(datos)
        os.makedirs(part)
        pares = [par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "p1"),
                 par(22222222, "QzaR", "wvaAB", ["PA0001"], ["PA0002"], "p2"),
                 par(33333333, "QzbR", "wvbA", ["PA0003"], ["PA0004"], "p3")]
        with open(os.path.join(tmp, "pares.jsonl"), "w") as f:
            for p in pares:
                f.write(json.dumps(p) + "\n")

        def ejemplo(p, label):
            return {"text": p["text"], "label": label, "pmid": p["pmid"],
                    "tf": p["tf"], "target": p["target"], "id_par": p["id_par"]}

        construidos = [ejemplo(pares[0], "activates"),
                       ejemplo(pares[1], "activates"),
                       ejemplo(pares[2], "no_relation")]
        with open(os.path.join(datos, E.ARCHIVOS[0]), "w") as f:
            for e in construidos:
                f.write(json.dumps(e) + "\n")
        for nombre, filas in (("train", construidos[:1] + construidos[2:]),
                              ("dev", construidos[2:]),
                              ("test", construidos[1:2])):
            with open(os.path.join(part, "entity_marked_%s.jsonl" % nombre),
                      "w") as f:
                for e in filas:
                    del_id = dict((k, v) for k, v in e.items()
                                  if k != "id_par")
                    f.write(json.dumps(del_id) + "\n")
        locus = R.locus_por_ejemplo(os.path.join(datos, E.ARCHIVOS[0]),
                                    os.path.join(tmp, "pares.jsonl"))
        f = R.fuga_por_par(part, locus)
        self.assertEqual(0, f["test"]["nombres"]["con_par_en_train"])
        self.assertEqual(1, f["test"]["locus"]["con_par_en_train"])
        self.assertEqual(1.0, f["test"]["locus"]["acierto_en_cubiertos"])

    def test_sintaxis_de_python_3_8(self):
        for modulo in (R, cli):
            ruta = modulo.__file__
            if ruta.endswith(".pyc"):
                ruta = ruta[:-1]
            with open(ruta, encoding="utf-8") as f:
                ast.parse(f.read(), filename=ruta, feature_version=(3, 8))


# ------------------------------------------------------- la orquestación

@unittest.skipUnless(POSIX, "el orquestador es para el servidor (POSIX)")
class PruebasCorrida(_Escenario):

    def test_punta_a_punta(self):
        estado, lineas = self.correr()
        self.assertEqual("ok", estado["estatus"], estado.get("detalle"))
        pasos = estado["pasos"]
        self.assertEqual(
            ["reservas", "datos", "base", "particion", "fuga", "entorno",
             "entrenamiento", "modelo"], list(pasos))
        self.assertTrue(all(p["estatus"] == "ok" for p in pasos.values()))
        self.assertEqual(1, self.llamadas())
        run = os.path.join(self.r["runs"], R.nombre_run())
        self.assertTrue(os.path.isfile(os.path.join(run,
                                                    "label_mapping.json")))
        self.assertFalse([n for n in os.listdir(run)
                          if n.startswith("checkpoint-")])
        self.assertEqual(2, pasos["modelo"]["checkpoints_borrados"])
        self.assertEqual(0.55, pasos["entrenamiento"]["metricas"][
            "test_macro_f1"])
        self.assertEqual(2, len(pasos["modelo"]["curva"]["epocas"]))
        self.assertTrue(pasos["particion"]["avisos"]["limpia"])
        self.assertIn("ciego", pasos["fuga"])
        informe = self.leer(self.r["informe"])
        for seccion in ("## 3. La base", "## 5. Partición", "## 6. Fuga",
                        "## 7. Entrenamiento", "Modelo menos línea base",
                        "no es una evaluación externa"):
            self.assertIn(seccion, informe)
        self.assertEqual("ok", estado["informe"]["estatus"])
        self.assertEqual(0, estado["huerfanos_al_cerrar"])
        # Los permisos: lo confidencial, solo para la cuenta.
        for carpeta in (self.r["datos"], self.r["runs"],
                        self.r["resultados"]):
            self.assertEqual(0o700, os.stat(carpeta).st_mode & 0o777)
        self.assertEqual(0o600, os.stat(os.path.join(
            self.r["datos"], E.ARCHIVOS[0])).st_mode & 0o777)

    def test_una_raiz_abierta_se_cierra_y_se_avisa(self):
        os.makedirs(self.raiz)
        os.chmod(self.raiz, 0o775)
        estado, _ = self.correr(hasta="datos")
        self.assertEqual(0o700, os.stat(self.raiz).st_mode & 0o777)
        self.assertTrue(estado["avisos"])
        self.assertIn("se cerró a 700", self.leer(self.r["informe"]))

    def test_nada_de_contenido_en_lo_que_ve_la_sesion(self):
        estado, lineas = self.correr(folds=3)
        self.assertEqual("ok", estado["estatus"])
        # El script falso imprime un ejemplo en cada entrenamiento: el filtro
        # tuvo algo que quitar (sin esto, la prueba solo mide que nadie
        # imprimió contenido).
        self.assertGreaterEqual(estado.get("lineas_omitidas", 0), 4)
        textos = {
            "salida": "\n".join(lineas),
            "estado": "\n".join(R.resumen_estado(self.raiz, "curada-v1", 400)),
            "cli estado": subprocess.run(
                [sys.executable, "-m", "grn_verificacion.cli", "reentrenar",
                 "estado", "--raiz", self.raiz, "--lineas", "400"],
                cwd=E.RAIZ_REPO, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True,
                timeout=60).stdout,
        }
        # Todo lo que hay en <resultados>, no una lista: el JSON de barrido.py
        # vivía ahí con la ruta absoluta de la partición y nadie lo miraba.
        for carpeta, _, archivos in os.walk(self.r["resultados"]):
            for nombre in archivos:
                ruta = os.path.join(carpeta, nombre)
                textos[os.path.relpath(ruta, self.r["resultados"])] = \
                    self.leer(ruta)
        self.assertIn("RESULTADOS.md", textos)
        self.assertIn("entrenamiento.json", textos)
        pmids = [str(PMID_BASE + i) for i in range(len(CODIGOS))]
        pmids.append(str(PMID_AJENO))
        # El nombre único del temporal sobrevive a «~» (si TMPDIR cae bajo el
        # home) y a <raiz>: una ruta de entrada escapada lo lleva siempre.
        unico = os.path.basename(self.tmp)
        for nombre, texto in textos.items():
            for pmid in pmids:
                self.assertNotIn(pmid, texto, nombre)
            for gen in self.nombres:
                self.assertNotIn(gen.lower(), texto.lower(), nombre)
            self.assertNotIn("florbination", texto, nombre)
            self.assertIsNone(re.search(r"PA[0-9]{4}", texto), nombre)
            self.assertNotIn(self.tmp, texto, nombre)
            self.assertNotIn(unico, texto, nombre)
            self.assertNotIn("<e1>", texto, nombre)
        R.verificar_publicable(textos["RESULTADOS.md"])

    def test_la_segunda_corrida_no_repite_nada(self):
        primero, _ = self.correr()
        # Con todo entrenado no hace falta la GPU: si nvidia-smi falla, sigue.
        os.environ["FALSO_GPU_FALLA"] = "1"
        estado, _ = self.correr()
        self.assertEqual("ok", estado["estatus"], estado.get("detalle"))
        for paso in ("datos", "particion", "fuga", "entorno",
                     "entrenamiento"):
            self.assertEqual("saltado", estado["pasos"][paso]["estatus"], paso)
        self.assertEqual(1, self.llamadas())
        # La curva y los tokens sobreviven aunque no se haya entrenado.
        self.assertTrue(estado["pasos"]["modelo"]["curva"]["epocas"])
        self.assertEqual(primero["pasos"]["entrenamiento"]["tokens"],
                         estado["pasos"]["entrenamiento"]["tokens"])
        self.assertTrue(estado["pasos"]["entrenamiento"]["tokens"])

    def test_el_tramo_1_despues_de_entrenar_conserva_las_metricas(self):
        self.correr()
        os.environ["FALSO_GPU_FALLA"] = "1"
        estado, _ = self.correr(hasta="particion")
        self.assertEqual("ok", estado["estatus"])
        self.assertEqual("previo", estado["pasos"]["entrenamiento"]["estatus"])
        self.assertEqual(0.55, estado["pasos"]["entrenamiento"]["metricas"][
            "test_macro_f1"])
        informe = self.leer(self.r["informe"])
        self.assertIn("de una corrida anterior", informe)
        self.assertIn("Modelo menos línea base", informe)
        self.assertEqual(1, self.llamadas())

    def test_una_base_distinta_se_detiene_antes_de_particionar(self):
        estado, _ = self.correr(aceptar_base_distinta=False)
        self.assertEqual(("error", "base_distinta"),
                         (estado["estatus"], estado["motivo"]))
        self.assertNotIn("particion", estado["pasos"])
        self.assertIn("DIFIERE", self.leer(self.r["informe"]))

    def test_hasta_datos_no_particiona(self):
        os.environ["FALSO_GPU_FALLA"] = "1"
        estado, _ = self.correr(hasta="datos")
        self.assertEqual("ok", estado["estatus"], estado.get("detalle"))
        self.assertEqual(["reservas", "datos", "base"], list(estado["pasos"]))
        self.assertFalse(os.path.exists(self.r["particion"]))
        self.assertFalse(os.path.exists(self.r["particion_txt"]))
        self.assertEqual(0, self.llamadas())
        self.assertIn("## 3. La base", self.leer(self.r["informe"]))

    def test_hasta_particion_no_toca_la_gpu(self):
        os.environ["FALSO_GPU_FALLA"] = "1"
        estado, _ = self.correr(hasta="particion")
        self.assertEqual("ok", estado["estatus"])
        self.assertNotIn("entorno", estado["pasos"])
        self.assertEqual(0, self.llamadas())

    def test_barrido_sale_con_0_pero_el_fallo_se_ve(self):
        os.environ["FALSO_MODO"] = "oom"
        estado, _ = self.correr()
        self.assertEqual(("error", "sin_memoria_gpu"),
                         (estado["estatus"], estado["motivo"]))
        self.assertTrue(os.path.exists(os.path.join(
            self.r["barrido"], R.nombre_run() + ".json.error")))
        self.assertNotIn("modelo", estado["pasos"])

    def test_un_run_a_medias_se_borra_antes_de_repetir(self):
        run = os.path.join(self.r["runs"], R.nombre_run())
        # Un archivo que el paso modelo no borra: si sobrevive, nadie borró
        # el run a medias (el checkpoint-9 solo no lo prueba, porque el paso
        # modelo borra todo checkpoint-* al final).
        resto = _escribir(os.path.join(run, "resto_del_intento.txt"), "x")
        os.makedirs(os.path.join(run, "checkpoint-9"))
        estado, lineas = self.correr()
        self.assertEqual("ok", estado["estatus"])
        self.assertTrue(any("a medias" in l for l in lineas))
        self.assertFalse(os.path.exists(resto))
        self.assertEqual(2, estado["pasos"]["modelo"]["checkpoints_borrados"])

    def test_sin_pesos_se_vuelve_a_entrenar(self):
        """Antes, un resultado sin modelo dejaba la corrida en sin_modelo
        para siempre, sin volver a entrenar."""
        self.correr()
        os.remove(os.path.join(self.r["runs"], R.nombre_run(),
                               "pytorch_model.bin"))
        estado, _ = self.correr()
        self.assertEqual("ok", estado["estatus"], estado.get("detalle"))
        self.assertEqual("ok", estado["pasos"]["entrenamiento"]["estatus"])
        self.assertEqual(2, self.llamadas())

    def test_si_cambia_la_particion_el_modelo_anterior_se_aparta(self):
        """Antes se borraba antes de reentrenar: si el reentrenamiento
        fallaba, no quedaba ningún modelo."""
        self.correr()
        E.escribir_reservas(self.reservas[1], [PMID_BASE + 29, PMID_BASE + 28],
                            [ORACION_RESERVADA])
        os.environ["FALSO_MODO"] = "oom"
        estado, _ = self.correr()
        self.assertEqual(("error", "sin_memoria_gpu"),
                         (estado["estatus"], estado["motivo"]))
        anterior = os.path.join(self.r["runs"], R.nombre_run() + ".anterior")
        self.assertTrue(os.path.isfile(os.path.join(anterior,
                                                    "pytorch_model.bin")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.r["barrido"], R.nombre_run() + ".json.anterior")))

    def test_el_tope_mata_al_hijo_y_al_nieto(self):
        os.environ["FALSO_MODO"] = "lento"
        t0 = time.monotonic()
        estado, _ = self.correr(horas=4.0 / 3600)
        self.assertLess(time.monotonic() - t0, 60,
                        "no los mató el tope: el árbol terminó solo")
        self.assertEqual(("cancelado", "tope"),
                         (estado["estatus"], estado["motivo"]))
        # Si los hubiera matado la barrida final por la marca, el tope no
        # alcanzó al grupo.
        self.assertEqual(0, estado["huerfanos_al_cerrar"])
        self.assertMuertos(self.esperar_pids(1))

    def test_el_tope_alcanza_a_un_script_que_ignora_sigterm(self):
        """El hijo directo (barrido.py) muere con SIGTERM y el script no: sin
        SIGKILL al grupo, el tope esperaba a que terminara solo."""
        os.environ["FALSO_MODO"] = "terco"
        t0 = time.monotonic()
        estado, _ = self.correr(horas=4.0 / 3600)
        self.assertLess(time.monotonic() - t0, 60)
        self.assertEqual(("cancelado", "tope"),
                         (estado["estatus"], estado["motivo"]))
        self.assertMuertos(self.esperar_pids(1))

    def test_gpu_ocupada_sin_cuda_sin_modelo_y_sin_disco_no_entrenan(self):
        for variable, valor, motivo in (
                ("FALSO_GPU_LIBRE", "1000", "gpu_ocupada"),
                ("FALSO_CUDA", "0", "sin_cuda"),
                ("FALSO_SIN_MODELO", "1", "modelo_no_en_cache"),
                ("FALSO_GPU_FALLA", "1", "gpu_no_disponible")):
            with mock.patch.dict(os.environ, {variable: valor}):
                estado, _ = self.correr()
            self.assertEqual(("error", motivo),
                             (estado["estatus"], estado["motivo"]))
        with mock.patch.object(R, "DISCO_MIN_GIB", 10 ** 9):
            estado, _ = self.correr()
        self.assertEqual(("error", "disco"),
                         (estado["estatus"], estado["motivo"]))
        self.assertEqual(0, self.llamadas())

    def test_id2label_al_reves_es_error(self):
        os.environ["FALSO_MODO"] = "id2label_mal"
        estado, _ = self.correr()
        self.assertEqual(("error", "id2label"),
                         (estado["estatus"], estado["motivo"]))

    def test_otro_max_length_con_la_misma_particion_se_detiene(self):
        self.correr()
        estado, _ = self.correr(max_length="256")
        self.assertEqual(("error", "parametros_distintos"),
                         (estado["estatus"], estado["motivo"]))
        self.assertEqual(1, self.llamadas())

    def test_candado_ocupado(self):
        os.makedirs(self.r["resultados"])
        candado = R.tomar_candado(self.r["candado"])
        self.addCleanup(R.soltar_candado, candado)
        with self.assertRaises(R.Ocupado) as ctx:
            self.correr()
        self.assertEqual(str(os.getpid()), str(ctx.exception.pid))
        self.assertEqual(os.getpid(), R.quien_corre(self.r["candado"]))
        r = self.correr_cli()
        self.assertEqual(4, r.returncode, r.stdout)

    def test_un_huerfano_de_otra_corrida_muere_antes_de_entrenar(self):
        dormir = [sys.executable, "-c", "import time; time.sleep(120)",
                  os.path.join(self.r["runs"], R.nombre_run())]
        # Un hijo de una corrida muerta lleva la marca en su entorno...
        huerfano = subprocess.Popen(
            dormir, start_new_session=True,
            env=dict(os.environ, **{R.MARCA_ENTORNO: self.r["runs"]}))
        self.addCleanup(huerfano.wait)
        self.addCleanup(huerfano.kill)
        # ...y quien solo USA el modelo (flujo.py --modelo, clasificar.py)
        # nombra la misma carpeta en su línea de comandos, pero no es nuestro.
        usuario = subprocess.Popen(dormir, start_new_session=True)
        self.addCleanup(usuario.wait)
        self.addCleanup(usuario.kill)
        estado, _ = self.correr()
        self.assertEqual("ok", estado["estatus"])
        self.assertEqual(1, estado["pasos"]["entorno"]["huerfanos"])
        # Lo mató el paso entorno y no la barrida del cierre.
        self.assertEqual(0, estado["huerfanos_al_cerrar"])
        self.assertMuertos([huerfano.pid])
        self.assertIsNone(usuario.poll(), "mató a quien usaba el modelo")

    def test_validacion_cruzada(self):
        estado, _ = self.correr(folds=3)
        self.assertEqual("ok", estado["estatus"], estado.get("detalle"))
        cv = estado["pasos"]["entrenamiento_cv"]
        self.assertEqual(["fold_0", "fold_1", "fold_2"], list(cv["pliegues"]))
        self.assertEqual(0.55, cv["agregado"]["test_macro_f1"]["media"])
        self.assertEqual(0.0, cv["agregado"]["test_macro_f1"]["sd"])
        self.assertEqual(4, self.llamadas())
        # Sin --conservar: los pliegues no dejan modelo.
        cv_runs = os.path.join(self.r["runs"], "cv")
        self.assertFalse([d for _, ds, _ in os.walk(cv_runs) for d in ds
                          if d.startswith("run_")])
        self.assertIn("media ± sd", self.leer(self.r["informe"]))

    def test_un_pliegue_rechazado_no_entrena(self):
        real = R._Corrida._particionar

        def con_fuga(corrida, salida, extra, archivo_txt):
            codigo, lineas = real(corrida, salida, extra, archivo_txt)
            if "--folds" in extra:
                lineas = lineas + ["--- pliegue 1: train=1 dev=1 test=1",
                                   "     FALLA: 1 PMIDs de test tambien en "
                                   "train"]
            return codigo, lineas

        with mock.patch.object(R._Corrida, "_particionar", con_fuga):
            estado, _ = self.correr(folds=3)
        self.assertEqual(("error", "particion_rechazada"),
                         (estado["estatus"], estado["motivo"]))
        self.assertNotIn("entorno", estado["pasos"])
        self.assertEqual(0, self.llamadas())

    def test_un_informe_no_publicable_no_queda_escrito(self):
        self.correr(hasta="datos")
        self.assertTrue(os.path.exists(self.r["informe"]))
        real = R.informe
        with mock.patch.object(R, "informe", lambda estado, r=None:
                               real(estado, r) + "\nver /srv/lab/x\n"):
            estado, _ = self.correr(hasta="datos")
        self.assertEqual("no_publicable", estado["informe"]["estatus"])
        self.assertIn("ruta absoluta", estado["informe"]["detalle"])
        # Una corrida cuyo resultado no se puede publicar no terminó bien.
        self.assertEqual(("error", "informe_no_publicable"),
                         (estado["estatus"], estado["motivo"]))
        self.assertFalse(os.path.exists(self.r["informe"]))
        self.assertNotIn("/srv/lab", json.dumps(R.leer_estado(
            self.r["estado"])))
        self.assertIn("no publicable", "\n".join(
            R.resumen_estado(self.raiz, "curada-v1")))

    def test_el_ciego_va_sin_desglose_por_etiqueta(self):
        estado, _ = self.correr()
        ciego = estado["pasos"]["fuga"]["ciego"]
        for clave in ("por_par", "por_regulador"):
            for parte in ("train", "dev", "test"):
                self.assertIsInstance(ciego[clave][parte], int)
        # Los dos pares del ciego de juguete; sus reguladores salen además en
        # los negativos de sus artículos.
        self.assertEqual(2, sum(ciego["por_par"].values()))
        self.assertGreater(sum(ciego["por_regulador"].values()), 2)

    def test_la_hoja_no_queda_en_lo_que_ve_la_sesion(self):
        estado, _ = self.correr(hoja="Hoja1")
        self.assertEqual("ok", estado["estatus"], estado.get("detalle"))
        for carpeta, _, archivos in os.walk(self.r["resultados"]):
            for nombre in archivos:
                self.assertNotIn("Hoja1", self.leer(os.path.join(carpeta,
                                                                 nombre)))


@unittest.skipUnless(POSIX, "el orquestador es para el servidor (POSIX)")
class PruebasProcesos(_Escenario):
    """La CLI como proceso aparte: señales, desprender y detener."""

    def _detener_con(self, sig, modo="lento"):
        os.environ["FALSO_MODO"] = modo
        if os.path.exists(self.pids):
            os.remove(self.pids)
        proc = self.popen_cli()
        pids = self.esperar_pids()
        proc.send_signal(sig)
        return proc, pids

    def test_sigterm_sighup_y_sigint_detienen_y_matan_el_arbol(self):
        """SIGHUP es el corte de SSH de una corrida sin --desprender."""
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(sig=sig):
                proc, pids = self._detener_con(sig)
                self.assertEqual(3, proc.wait(60))
                self.assertMuertos(pids)
                estado = R.leer_estado(self.r["estado"])
                self.assertEqual(("cancelado", "detenido"),
                                 (estado["estatus"], estado["motivo"]))
                self.assertEqual(0, estado["huerfanos_al_cerrar"])

    def test_con_sighup_ignorado_un_corte_de_ssh_no_la_detiene(self):
        """Así la deja `nohup`: capturar SIGHUP anulaba el nohup."""
        os.environ["FALSO_MODO"] = "lento"
        proc = self.popen_cli(ignorar_sighup=True)
        pids = self.esperar_pids()
        proc.send_signal(signal.SIGHUP)
        time.sleep(2)
        self.assertIsNone(proc.poll(), "un SIGHUP ignorado la detuvo")
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(3, proc.wait(60))
        self.assertMuertos(pids)

    def test_la_segunda_senal_corta_aunque_el_script_ignore_sigterm(self):
        proc, pids = self._detener_con(signal.SIGTERM, modo="terco")
        time.sleep(2)
        self.assertIsNone(proc.poll(), "con el script terco, a los 2 s la "
                                       "primera señal todavía no alcanza")
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(3, proc.wait(30))
        self.assertMuertos(pids)
        estado = R.leer_estado(self.r["estado"])
        self.assertEqual(("cancelado", "detenido"),
                         (estado["estatus"], estado["motivo"]))

    def test_desprender_estado_y_detener(self):
        os.environ["FALSO_MODO"] = "lento"
        t0 = time.monotonic()
        r = self.correr_cli("--desprender")
        # Pase lo que pase después, el orquestador desprendido no sobrevive a
        # la prueba (la barrida de la marca no lo alcanza: él no la lleva).
        self.addCleanup(R.detener_corrida, self.raiz, "curada-v1", 5)
        self.assertEqual(0, r.returncode, r.stdout)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertIn("segundo plano", r.stdout)
        # El aviso no lleva la ruta absoluta de la raíz.
        self.assertNotIn(self.tmp, r.stdout)
        self.assertIn("--raiz <raiz>", r.stdout)
        pids = self.esperar_pids()
        orquestador = R.quien_corre(self.r["candado"])
        self.assertTrue(orquestador)
        # La ruta de la base viaja en el entorno, no en la línea de comandos
        # que ve cualquier cuenta con `ps`.
        with open("/proc/%d/cmdline" % orquestador, "rb") as f:
            self.assertNotIn(self.base.encode("utf-8"), f.read())
        self.assertIn("corre en el PID %d" % orquestador,
                      "\n".join(R.resumen_estado(self.raiz, "curada-v1")))
        resultado = R.detener_corrida(self.raiz, "curada-v1", esperar=30)
        self.assertEqual(orquestador, resultado["pid"])
        self.assertFalse(resultado["forzado"])
        self.assertMuertos(pids + [orquestador])
        self.assertIsNone(R.quien_corre(self.r["candado"]))
        estado = R.leer_estado(self.r["estado"])
        self.assertEqual("cancelado", estado["estatus"])
        self.assertEqual(0, estado["huerfanos_al_cerrar"])
        # reentrenar.err vive en <resultados>, crudo.
        err = self.leer(self.r["err"])
        self.assertNotIn(self.tmp, err)
        self.assertNotIn("Traceback", err)

    def test_desprender_valida_antes_de_lanzar(self):
        argv = self.argv_cli("--desprender")
        argv[argv.index("--reservar") + 1] = os.path.join(self.tmp, "no.tsv")
        r = subprocess.run(argv, cwd=E.RAIZ_REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True,
                           timeout=60)
        self.assertEqual(2, r.returncode, r.stdout)
        self.assertIn("No encuentro el archivo de --reservar", r.stdout)
        self.assertFalse(os.path.exists(self.r["estado"]))

    def test_desprender_que_muere_al_arrancar_dice_por_que(self):
        """Antes el error se perdía en /dev/null y se mostraba el estado de
        la corrida anterior."""
        dentro = os.path.join(self.tmp, "copia_git")
        os.makedirs(os.path.join(dentro, ".git"))
        argv = self.argv_cli("--desprender")
        argv[argv.index("--raiz") + 1] = os.path.join(dentro, "raiz")
        r = subprocess.run(argv, cwd=E.RAIZ_REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True,
                           timeout=60)
        self.assertNotEqual(0, r.returncode, r.stdout)
        self.assertIn("terminó al arrancar", r.stdout)
        self.assertIn("repositorio", r.stdout)
        self.assertNotIn(self.tmp, r.stdout)

    def test_un_kill_9_al_orquestador_se_ve_en_estado_y_detener_limpia(self):
        os.environ["FALSO_MODO"] = "lento"
        proc = self.popen_cli()
        pids = self.esperar_pids()
        proc.kill()
        proc.wait(10)
        resumen = "\n".join(R.resumen_estado(self.raiz, "curada-v1"))
        self.assertIn("murió sin cerrar", resumen)
        # barrido.py, el script y su nieto.
        self.assertIn("quedan 3 procesos", resumen)
        # El RESULTADOS.md de una corrida anterior no queda diciendo «ok».
        self.assertIn("**corriendo**", self.leer(self.r["informe"]))
        r = R.detener_corrida(self.raiz, "curada-v1", esperar=5)
        self.assertEqual(3, r["huerfanos"])
        self.assertMuertos(pids)
        self.assertIn("**cancelado**", self.leer(self.r["informe"]))

    def test_con_el_candado_borrado_no_se_mata_la_corrida_viva(self):
        """Si alguien borra .candado, la siguiente corrida tomaba uno nuevo y
        mataba el entrenamiento vivo creyéndolo huérfano."""
        os.environ["FALSO_MODO"] = "lento"
        proc = self.popen_cli()
        pids = self.esperar_pids()
        os.remove(self.r["candado"])
        with self.assertRaises(R.Ocupado) as ctx:
            self.correr()
        self.assertEqual(proc.pid, int(ctx.exception.pid))
        self.assertFalse([p for p in pids if not R._vivo(p)],
                         "mató a la corrida viva")
        r = R.detener_corrida(self.raiz, "curada-v1", esperar=30)
        self.assertEqual(proc.pid, r["pid"])
        self.assertEqual(3, proc.wait(30))
        self.assertMuertos(pids)

    def test_detener_fuerza_con_sigkill_si_no_suelta_el_candado(self):
        os.makedirs(self.r["resultados"])
        R.escribir_estado(self.r["estado"], {"estatus": "corriendo",
                                             "pasos": {}})
        terco = subprocess.Popen(
            [sys.executable, "-c",
             "import signal, sys, time\n"
             "from grn_verificacion import reentrenar as R\n"
             "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
             "c = R.tomar_candado(sys.argv[1])\n"
             "print('listo', flush=True)\n"
             "time.sleep(600)\n", self.r["candado"]],
            cwd=E.RAIZ_REPO, stdout=subprocess.PIPE,
            universal_newlines=True)
        self.addCleanup(terco.stdout.close)
        self.addCleanup(terco.wait)
        self.addCleanup(terco.kill)
        self.assertEqual("listo", terco.stdout.readline().strip())
        r = R.detener_corrida(self.raiz, "curada-v1", esperar=1)
        self.assertEqual((terco.pid, True), (r["pid"], r["forzado"]))
        self.assertEqual(-signal.SIGKILL, terco.wait(10))
        self.assertIsNone(R.quien_corre(self.r["candado"]))
        estado = R.leer_estado(self.r["estado"])
        self.assertEqual(("cancelado", "detenido"),
                         (estado["estatus"], estado["motivo"]))
        self.assertIn("a la fuerza", estado["detalle"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root escribe aunque la carpeta sea 500")
    def test_un_error_de_la_cli_no_sale_como_traceback(self):
        """Una --raiz donde no se puede escribir: antes salía el traceback de
        Python, con rutas del repositorio y la que falló."""
        cerrada = os.path.join(self.tmp, "cerrada")
        os.makedirs(cerrada)
        os.chmod(cerrada, 0o500)
        self.addCleanup(os.chmod, cerrada, 0o700)
        argv = self.argv_cli()
        argv[argv.index("--raiz") + 1] = os.path.join(cerrada, "raiz")
        r = subprocess.run(argv, cwd=E.RAIZ_REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, universal_newlines=True,
                           timeout=60)
        self.assertEqual(1, r.returncode, r.stdout)
        self.assertIn("PermissionError", r.stdout)
        self.assertNotIn("Traceback", r.stdout)
        self.assertNotIn(self.tmp, r.stdout)
        self.assertNotIn(E.RAIZ_REPO, r.stdout)


if __name__ == "__main__":
    unittest.main()
