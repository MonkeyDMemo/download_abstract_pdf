"""Reentrenar el BioBERT con la base curada, de punta a punta y sin vigilancia.

Es la pista D (docs/entrenamiento-curada.md) envuelta en un solo comando para
el servidor del asesor:

    datos-entrenamiento -> etapa2/particionar.py --por pmid -> etapa2/barrido.py --solo 22

Por qué un orquestador y no tres comandos a mano:

- En el servidor no hay tmux, y un corte de SSH mataba el entrenamiento. Con
  `--desprender` (en `cli.py`) corre en su propia sesión y sobrevive al corte
  y al cierre de la sesión de Claude.
- `barrido.py` sale con 0 aunque el entrenamiento falle, y está congelado en
  etapa2/. Aquí el fallo se reconoce por lo que dejó escrito: sin el JSON del
  resultado no hay éxito, diga lo que diga el código de salida.
- Copiar y pegar la salida en la bitácora publicaba rutas del servidor (con
  la cuenta, si los datos caían bajo el home). Lo que se lee de una corrida es
  `reentrenar estado` y `RESULTADOS.md`, y los dos pasan por un filtro: sin
  rutas, sin oraciones marcadas, sin locus, sin nada con forma de PMID.

Confidencialidad. Los ejemplos y el modelo derivan de la base curada y se
quedan en `<raiz>/datos/<nombre>` y `<raiz>/runs/<nombre>`; este módulo no
los imprime nunca. Lo que no es confidencial (estado, log filtrado, métricas,
el informe) va a `<raiz>/resultados/<nombre>`. La base llega por argumento y
nunca se nombra aquí: `etapa2/test_contaminacion.py` vigila este paquete.

Robustez, en una línea por defensa:

- un candado `fcntl.flock`: el núcleo lo suelta si el proceso muere, así que
  no queda un candado viejo que haya que borrar a mano;
- cada hijo corre en su propia sesión (`grn_comun.proceso`), y detener mata
  el grupo entero, con el script del asesor dentro;
- si este proceso muere sin poder limpiar (SIGKILL, el OOM-killer), los
  huérfanos se buscan en /proc por la carpeta de su corrida y se matan antes
  de volver a entrenar;
- un tope de horas por entrenamiento (CLAUDE.md: más de 4 h se detiene);
- antes de tocar la GPU: memoria libre, CUDA de verdad (el script del asesor
  entrena en CPU sin avisar) y BioBERT en la caché sin salir a internet;
- los pasos se saltan por huella, y un entrenamiento a medias se borra antes
  de repetirlo, porque el script del asesor no puede reanudar.

Biblioteca estándar y Python 3.8. Solo POSIX: es para el servidor.
"""

import collections
import csv
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
import traceback

from grn_comun import archivos, procedencia, proceso
from grn_verificacion import entrenamiento as E

RAIZ_REPO = E.RAIZ_REPO
PARTICIONAR = os.path.join(RAIZ_REPO, "etapa2", "particionar.py")
BARRIDO = os.path.join(RAIZ_REPO, "etapa2", "barrido.py")

# run_22_lr3e-5_ep8_bs16_wu0.1, la mejor del barrido del asesor. Se cambia
# decidiéndolo, no con un flag.
CONFIGURACION = 22
MODELO = "dmis-lab/biobert-base-cased-v1.1"
MAX_LENGTH = "512"
# La semilla por omisión de particionar.py, explícita para que quede sellada.
SEMILLA_PARTICION = 20260819
HORAS = 4.0
# Con 1.2 GB de sesiones gráficas, la RTX 3070 deja unos 7 000 MiB.
GPU_MIN_MIB = 6500
# Dos checkpoints de ~1.3 GB (pesos y estado de AdamW) más el modelo final.
DISCO_MIN_GIB = 6
# El orden del label_mapping.json de particionar.py y del checkpoint.
ID2LABEL = {"0": "activates", "1": "no_relation", "2": "regulates",
            "3": "represses"}

# PLAN.md 2.4, medido el 10-sep-2026. Lo que no cuadre detiene la corrida:
# puede ser otra versión de la base o el lector, que hasta esta pista solo se
# había probado con .xlsx sintéticos. «otro» tiene que ser 0: una fila con un
# `Origen` desconocido sí da positivos, y si la versión nueva marcara de otra
# forma lo que propuso el modelo, el entrenamiento se volvería circular.
BASE_ESPERADA = collections.OrderedDict([
    ("filas", 5584),
    ("signo", collections.OrderedDict([
        ("+", 4060), ("-", 598), ("?", 909), ("d", 14), ("ilegible", 3)])),
    ("origen", collections.OrderedDict([
        ("historica", 4824), ("biobert", 544), ("ambos", 216), ("otro", 0)])),
    ("homologia", 2850),
    ("pmids_distintos", 310),
    ("dois_descartados", 1),
])

HASTA = ("datos", "particion", "entrenamiento")
# La variable que marca a los hijos de una corrida (ver `procesos_con`).
MARCA_ENTORNO = "GRN_REENTRENAR"
NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")

# Sin red y sin barras de progreso a cada segundo: cada refresco de tqdm es
# una línea del log. `expandable_segments` reduce la fragmentación cuando otro
# proceso ocupa la GPU a mitad del entrenamiento.
ENTORNO_HF = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TQDM_MININTERVAL": "30",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
}

# Un entrenamiento en CPU tarda horas sin decir nada: la sonda corre con el
# mismo intérprete y el mismo entorno que el entrenamiento, y carga el modelo
# sin red, que es también la prueba de que está en la caché.
SONDA = r'''
import json, sys
r = {}
try:
    import torch
    r["torch"] = torch.__version__
    r["cuda"] = bool(torch.cuda.is_available())
    if r["cuda"]:
        r["dispositivo"] = torch.cuda.get_device_name(0)
except Exception as e:
    r["cuda"] = False
    r["error_torch"] = type(e).__name__
try:
    import transformers
    r["transformers"] = transformers.__version__
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    AutoTokenizer.from_pretrained(sys.argv[1])
    AutoModelForSequenceClassification.from_pretrained(sys.argv[1], num_labels=4)
    r["modelo"] = True
except Exception as e:
    r["modelo"] = False
    r["error_modelo"] = type(e).__name__
r["python"] = "%d.%d.%d" % sys.version_info[:3]
print("SONDA " + json.dumps(r))
'''

MOTIVOS = {
    "ruta_en_repositorio": "una carpeta de la corrida cae dentro de un repositorio",
    "reservas": "el archivo de reservas no se pudo leer",
    "reservas_incompletas": "las reservas no cubren la muestra de juicios",
    "datos": "datos-entrenamiento se detuvo",
    "base_distinta": "la base no coincide con PLAN.md 2.4",
    "particion_rechazada": "particionar.py encontró fuga",
    "particion_error": "particionar.py no terminó",
    "gpu_no_disponible": "nvidia-smi no respondió",
    "gpu_ocupada": "la GPU no tiene memoria libre suficiente",
    "disco": "no hay disco libre suficiente",
    "sin_cuda": "el intérprete no ve CUDA",
    "modelo_no_en_cache": "BioBERT no carga sin red",
    "parametros_distintos": "ya hay un resultado de esta partición con otros parámetros",
    "sin_memoria_gpu": "CUDA se quedó sin memoria",
    "matado": "el entrenamiento murió por una señal",
    "script_fallo": "el script de entrenamiento falló",
    "sin_modelo": "el entrenamiento no dejó pesos",
    "id2label": "el orden de etiquetas del modelo no es el esperado",
    "tope": "se alcanzó el tope de horas",
    "detenido": "se pidió detener",
    "inesperado": "error inesperado del orquestador",
}


class ErrorReentreno(RuntimeError):
    """Un paso no puede seguir. `motivo` es una llave de MOTIVOS; `detalle`
    llega ya filtrado al estado."""

    def __init__(self, motivo, detalle=""):
        self.motivo = motivo
        self.detalle = detalle
        super().__init__("%s: %s" % (motivo, detalle))


class Ocupado(RuntimeError):
    """Ya corre una corrida con ese nombre (alguien tiene el candado)."""

    def __init__(self, pid):
        self.pid = pid
        super().__init__("Ya corre una corrida con ese nombre (PID %s)." % pid)


def _nada(_):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _hora():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")


# ------------------------------------------------------------------ rutas

def validar_nombre(nombre):
    if (not NOMBRE_VALIDO.match(nombre or "")) or nombre in (".", ".."):
        raise ValueError("--nombre: solo letras, dígitos, punto, guion y "
                         "guion bajo, hasta 40.")
    return nombre


def rutas(raiz, nombre):
    """Las carpetas y archivos de una corrida, absolutos."""
    raiz = os.path.abspath(os.path.expanduser(raiz))
    datos = os.path.join(raiz, "datos", nombre)
    runs = os.path.join(raiz, "runs", nombre)
    res = os.path.join(raiz, "resultados", nombre)
    return {
        "raiz": raiz,
        "datos": datos,
        "particion": os.path.join(datos, "por_pmid"),
        "runs": runs,
        "resultados": res,
        # Lo que escribe barrido.py va con lo confidencial: su JSON y su
        # resumen llevan la ruta absoluta de la partición (`datos`), y
        # barrido.py está congelado. A <resultados> llega solo una copia con
        # números (`entrenamiento.json`).
        "barrido": os.path.join(runs, "barrido"),
        "entrenamiento": os.path.join(res, "entrenamiento.json"),
        "entrenamiento_cv": os.path.join(res, "entrenamiento_cv.json"),
        "estado": os.path.join(res, "estado.json"),
        "log": os.path.join(res, "reentrenar.log"),
        "err": os.path.join(res, "reentrenar.err"),
        "candado": os.path.join(res, ".candado"),
        "informe": os.path.join(res, "RESULTADOS.md"),
        "particion_txt": os.path.join(res, "particion.txt"),
        "particion_cv_txt": os.path.join(res, "particion_cv.txt"),
        "conteos": os.path.join(res, "conteos.json"),
        "curva": os.path.join(res, "curva.json"),
    }


def _particion_cv(r, folds):
    return os.path.join(r["datos"], "por_pmid_k%d" % folds)


def preparar_carpetas(r):
    """Crea datos/, runs/ y resultados/ con 0o700, fuera de todo repositorio.

    Los ejemplos y el modelo son confidenciales: dentro de una copia de git
    quedan a un `git add -f` de un remoto público (ver
    `entrenamiento.exigir_fuera_del_repositorio`). Devuelve los avisos, que
    van al estado y al informe: con `--desprender` la salida estándar es
    /dev/null y un aviso impreso no lo vería nadie.
    """
    for llave in ("datos", "runs", "resultados"):
        try:
            E.exigir_fuera_del_repositorio(r[llave])
        except ValueError:
            raise ErrorReentreno(
                "ruta_en_repositorio",
                "--raiz queda dentro de un repositorio de git; usa una "
                "carpeta fuera de cualquier copia de trabajo.")
    for llave in ("datos", "runs", "resultados"):
        padre = os.path.dirname(r[llave])
        for carpeta in (r["raiz"], padre, r[llave]):
            if not os.path.isdir(carpeta):
                os.makedirs(carpeta, 0o700)
        for carpeta in (padre, r[llave]):
            # makedirs respeta el umask; chmod lo deja explícito aunque la
            # carpeta ya existiera con otros permisos.
            os.chmod(carpeta, 0o700)
    avisos = []
    info = os.stat(r["raiz"])
    if info.st_mode & 0o077:
        # La base vive en <raiz>: abierta al grupo u otros, otras cuentas de
        # la máquina la pueden leer. Si la carpeta es de esta cuenta, se
        # cierra; si no, solo se avisa.
        antes = info.st_mode & 0o777
        if info.st_uid == os.getuid():
            os.chmod(r["raiz"], 0o700)
            avisos.append("<raiz> tenía permisos %03o para el grupo u otros; "
                          "se cerró a 700." % antes)
        else:
            avisos.append("<raiz> tiene permisos %03o para el grupo u otros y "
                          "no es de esta cuenta: ciérrala a 700." % antes)
    return avisos


# ---------------------------------------------------------------- el filtro

_LOCUS = re.compile(r"PA[0-9]{4}")
_MARCAS = re.compile(r"</?e[12]>")
# Siete u ocho dígitos sueltos: la forma de un PMID. Sin letras a los lados,
# para no confundir una huella hexadecimal o un hash de commit, y sin ser
# parte de un decimal (0.12345678, 1234567.5) para no tomar una métrica. Un
# punto final de oración sí cuenta como borde: «…, PMID 1234567.».
_POSIBLE_PMID = re.compile(
    r"(?<![0-9A-Za-z.])[0-9]{7,8}(?![0-9A-Za-z]|\.[0-9])")
# Las semillas tienen forma de fecha y de PMID; son constantes conocidas.
_NUMEROS_PERMITIDOS = frozenset([str(E.SEMILLA), str(SEMILLA_PARTICION)])
# Toda ruta absoluta de dos o más tramos (/tmp/x, /srv/a/b, no solo /home) y
# toda ruta bajo el home (~/...). No cuenta lo que va pegado a una palabra,
# a un número o a un marcador: «dmis-lab/biobert», «80/10/10» y
# «<datos>/por_pmid» se pueden publicar.
_RUTA_ABSOLUTA = re.compile(
    r"(?<![\w.<>~-])/(?:[\w.-]+/)+[\w.-]*|~/|[A-Za-z]:\\")
LARGO_LINEA = 300


def _tiene_pmid(texto):
    return any(m.group(0) not in _NUMEROS_PERMITIDOS
               for m in _POSIBLE_PMID.finditer(texto))


class Saneador:
    """Lo que puede ver la sesión: rutas cambiadas por marcadores y fuera
    toda línea con algo que parezca contenido de la base.

    Una línea con un locus PA####, un marcador <e1>/<e2> (todo ejemplo lleva
    uno) o un posible PMID se omite entera, no se recorta: si una excepción
    del script imprimiera un ejemplo, no llega ni al log.
    """

    def __init__(self, r, extra=()):
        pares = list(extra)
        for llave, marca in (("datos", "<datos>"), ("runs", "<runs>"),
                             ("resultados", "<resultados>"),
                             ("raiz", "<raiz>")):
            pares.append((r[llave], marca))
        pares.append((RAIZ_REPO, "<repo>"))
        pares.append((os.path.expanduser("~"), "~"))
        vistos = []
        for ruta, marca in pares:
            if not ruta:
                continue
            for variante in (os.path.abspath(ruta), os.path.realpath(ruta)):
                if variante not in [v for v, _ in vistos] and len(variante) > 1:
                    vistos.append((variante, marca))
        # La más larga primero: <datos> antes que <raiz>, que la contiene.
        self.reemplazos = sorted(vistos, key=lambda p: -len(p[0]))

    def texto(self, s):
        s = str(s)
        for ruta, marca in self.reemplazos:
            s = s.replace(ruta, marca)
        return s

    def linea(self, s):
        """La línea saneada, o None si no se puede mostrar."""
        s = self.texto(s).rstrip()
        if _LOCUS.search(s) or _MARCAS.search(s) or _tiene_pmid(s):
            return None
        if len(s) > LARGO_LINEA:
            s = s[:LARGO_LINEA] + "…"
        return s


_PATRONES_PUBLICABLES = (
    ("ruta absoluta", _RUTA_ABSOLUTA),
    ("locus PA####", _LOCUS),
    ("marcador de entidad", _MARCAS),
)


def verificar_publicable(texto):
    """ValueError si el texto no se puede publicar. El mensaje dice qué
    patrón y en qué línea, nunca el texto: repetirlo sería publicarlo."""
    for numero, linea in enumerate(texto.splitlines(), 1):
        for nombre, patron in _PATRONES_PUBLICABLES:
            if patron.search(linea):
                raise ValueError("%s en la línea %d" % (nombre, numero))
        if _tiene_pmid(linea):
            raise ValueError("posible PMID en la línea %d" % numero)


# ----------------------------------------------------------------- candado

def tomar_candado(ruta):
    """El archivo abierto con `flock` exclusivo y el PID escrito, u Ocupado.

    `flock` y no un archivo creado con O_EXCL: el núcleo suelta el candado
    cuando el proceso muere, también por SIGKILL, así que no queda uno viejo
    que alguien tenga que borrar a mano (el defecto del `.flujo.lock`).
    """
    import fcntl
    f = open(ruta, "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        pid = f.read().strip()
        f.close()
        raise Ocupado(pid or "?")
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def soltar_candado(f):
    import fcntl
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def quien_corre(ruta):
    """El PID que tiene el candado, o None si nadie lo tiene."""
    if not os.path.exists(ruta):
        return None
    import fcntl
    with open(ruta, "a+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.seek(0)
            texto = f.read().strip()
            return int(texto) if texto.isdigit() else -1
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return None


# ------------------------------------------------------------------ estado

def leer_estado(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def escribir_estado(ruta, estado):
    estado["actualizado"] = _ahora()
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
        f.write("\n")
    archivos.reemplazar(tmp, ruta)


def _leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _escribir_texto(ruta, texto):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    archivos.reemplazar(tmp, ruta)


# --------------------------------------------------------- piezas puras

def verificar_reservas(rutas_reservas, ruta_juicios=E.RUTA_JUICIOS):
    """Cuántos PMIDs y oraciones de la muestra de juicios faltan en las
    reservas. Solo conteos.

    Si faltan, el 44 % recalculado con este modelo mediría memoria: esos
    artículos u oraciones se habrían visto al entrenar.
    """
    reservas, conteos = E.leer_reservas(rutas_reservas)
    pmids, oraciones = E.reservas_de_csv(ruta_juicios, "pmid", "oracion")
    return {
        "archivos": conteos["archivos"],
        "pmids": conteos["pmids"],
        "oraciones": conteos["oraciones"],
        "faltan_pmids": len(pmids - reservas["pmids"]),
        "faltan_oraciones": len(oraciones - reservas["oraciones"]),
    }


def filas_cotejo(medida, esperada=BASE_ESPERADA):
    """[(conteo, esperado, medido, coincide)] contra PLAN.md 2.4."""
    filas = []
    for clave, valor in esperada.items():
        if isinstance(valor, dict):
            sub_medida = medida.get(clave) or {}
            for sub, v in valor.items():
                m = sub_medida.get(sub)
                filas.append(["%s %s" % (clave, sub), v, m, m == v])
        else:
            m = medida.get(clave)
            filas.append([clave, valor, m, m == valor])
    return filas


def macro_f1(y, yhat):
    """El macro-F1 de `precision_recall_fscore_support(average="macro",
    zero_division=0)`, el que usa el script del asesor: promedio sobre las
    etiquetas que aparecen en `y` o en `yhat`."""
    etiquetas = sorted(set(y) | set(yhat))
    if not etiquetas:
        return 0.0
    total = 0.0
    for e in etiquetas:
        tp = sum(1 for a, b in zip(y, yhat) if a == e and b == e)
        fp = sum(1 for a, b in zip(y, yhat) if a != e and b == e)
        fn = sum(1 for a, b in zip(y, yhat) if a == e and b != e)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        total += 2 * p * r / (p + r) if p + r else 0.0
    return total / len(etiquetas)


def _mas_frecuente(contador):
    """La etiqueta más frecuente; un empate se rompe por el orden de
    ETIQUETAS, para que el resultado no dependa del orden de lectura."""
    return max(E.ETIQUETAS,
               key=lambda e: (contador.get(e, 0), -E.ETIQUETAS.index(e)))


def linea_base_memorizacion(entrena, prueba, llave):
    """Cuánto se acierta sin leer la oración, solo recordando el par.

    Para cada ejemplo de `prueba` cuyo par (`llave`) ya está en train, se
    predice la etiqueta más frecuente de ese par en train; para el resto, la
    clase mayoritaria de train. Por construcción de `entrenamiento`, un par
    registrado en la base nunca sale como no_relation y uno que no lo está
    nunca sale como relación, así que esta línea base puede ser alta: el
    modelo vale lo que le gana, no su F1 a secas. Devuelve solo números.
    """
    por_par = collections.defaultdict(collections.Counter)
    for e in entrena:
        k = llave(e)
        if k is not None:
            por_par[k][e["label"]] += 1
    mayoritaria = _mas_frecuente(
        collections.Counter(e["label"] for e in entrena))
    y, yhat = [], []
    cubiertos = aciertos = sin_llave = 0
    for e in prueba:
        k = llave(e)
        if k is None:
            sin_llave += 1
        if k is not None and k in por_par:
            cubiertos += 1
            pred = _mas_frecuente(por_par[k])
            aciertos += pred == e["label"]
        else:
            pred = mayoritaria
        y.append(e["label"])
        yhat.append(pred)
    n = len(prueba)
    return {
        "n": n,
        "con_par_en_train": cubiertos,
        "sin_llave": sin_llave,
        "acierto_en_cubiertos": round(aciertos / cubiertos, 4)
        if cubiertos else None,
        "accuracy": round(sum(1 for a, b in zip(y, yhat) if a == b) / n, 4)
        if n else None,
        "macro_f1": round(macro_f1(y, yhat), 4) if n else None,
        "macro_f1_mayoritaria": round(macro_f1(y, [mayoritaria] * n), 4)
        if n else None,
    }


def _leer_jsonl(ruta):
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                yield json.loads(linea)


def locus_por_ejemplo(ruta_train_datos, ruta_pares):
    """{(pmid, text): (tf_locus, target_locus)} de los ejemplos construidos.

    `particionar.py` no conserva `id_par`; el `entity_marked_train.jsonl` de
    `datos-entrenamiento` sí, y con él se llega al par del corpus público y a
    sus locus. Un operón y su gen tienen nombres distintos pero comparten
    locus: por nombres, la fuga por par se subestima.
    """
    ids = {}
    for e in _leer_jsonl(ruta_train_datos):
        ids[(str(e["pmid"]), e["text"])] = str(e.get("id_par"))
    necesarios = set(ids.values())
    locus = {}
    for p in _leer_jsonl(ruta_pares):
        i = str(p.get("id_par"))
        if i in necesarios:
            tf = E._loci(p.get("tf_locus"))
            tg = E._loci(p.get("target_locus"))
            if tf and tg:
                locus[i] = (tf, tg)
    return dict((k, locus.get(v)) for k, v in ids.items())


def pares_del_ciego(ruta):
    """{(regulador, blanco)} en minúsculas, del TSV del conjunto ciego."""
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f, delimiter="\t")
        campos = lector.fieldnames or []
        for columna in ("tf", "blanco"):
            if columna not in campos:
                raise ValueError("El conjunto ciego no tiene la columna %s."
                                 % columna)
        return set((fila["tf"].strip().lower(), fila["blanco"].strip().lower())
                   for fila in lector if fila.get("tf") and fila.get("blanco"))


def _por_nombre(e):
    return (str(e["tf"]).lower(), str(e["target"]).lower())


def leer_particion(carpeta):
    return dict((n, list(_leer_jsonl(os.path.join(
        carpeta, "entity_marked_%s.jsonl" % n))))
        for n in ("train", "dev", "test"))


def fuga_por_par(carpeta, locus, pares_ciego=None):
    """La línea base de memorización en dev y test, por nombres y por locus,
    y lo que entró del conjunto ciego. Solo números."""
    partes = leer_particion(carpeta)

    def por_locus(e):
        return locus.get((str(e["pmid"]), e["text"]))

    r = {}
    for nombre in ("dev", "test"):
        r[nombre] = {
            "nombres": linea_base_memorizacion(
                partes["train"], partes[nombre], _por_nombre),
            "locus": linea_base_memorizacion(
                partes["train"], partes[nombre], por_locus),
        }
    if pares_ciego:
        # Solo totales por parte, sin desglose por etiqueta. Los 6 pares tienen
        # nombre público, y en esta supervisión la etiqueta de un par sale de
        # la base: «represses 9» diría qué signo les da la base, y un
        # «no_relation» diría que no los registra. Eso ya son filas, no
        # conteos.
        reguladores = set(a for a, _ in pares_ciego)
        ciego = {"por_par": {}, "por_regulador": {}}
        for nombre, filas in partes.items():
            ciego["por_par"][nombre] = sum(
                1 for e in filas if _por_nombre(e) in pares_ciego)
            ciego["por_regulador"][nombre] = sum(
                1 for e in filas if str(e["tf"]).lower() in reguladores)
        r["ciego"] = ciego
    return r


_RE_VACIA = re.compile(r"AVISO: (\S+) no tiene ningun ejemplo de (\S+):")
_RE_FLACA = re.compile(r"La celda mas flaca: (\S+) en (\S+) son (\d+) "
                       r"ejemplos, pero de solo (\d+) articulos")
_RE_CASI = re.compile(r"AVISO: (\d+) ejemplos de (\S+) tienen su ventana "
                      r"contenida en una de train \(peor ([0-9.]+)\)")
_RE_FUGA = re.compile(r"^\s+(dev|test)\s+([0-9.]+)%\s+(\d+)\s+([0-9.]+)%"
                      r"\s+([0-9.]+)%\s*$")
_RE_CLASES = re.compile(r"^\s+(train|dev|test|TOTAL|fold_\d+)\s+(\d+)\s+"
                        r"(\d+)\s+((?:\d+\s+[0-9.]+%\s*){4})$")
_RE_CELDA = re.compile(r"(\d+)\s+[0-9.]+%")


def avisos_particion(lineas):
    """Lo que hay que saber de la salida de `particionar.py`, como datos.

    Lee el formato de `etapa2/particionar.py` (congelado): la tabla de
    clases, la de fuga contra train y sus AVISO. `test_reentrenar` lo
    comprueba contra la salida real, para enterarse si cambia.
    """
    a = {"tabla": {}, "fuga": {}, "clases_vacias": [], "celda_flaca": None,
         "menos_de_5_articulos": False, "casi_dup": {}, "fallas": 0,
         "rechazada": False, "limpia": False}
    for linea in lineas:
        m = _RE_CLASES.match(linea)
        if m:
            celdas = [int(x) for x in _RE_CELDA.findall(m.group(4))]
            a["tabla"][m.group(1)] = {
                "n": int(m.group(2)), "articulos": int(m.group(3)),
                "por_clase": dict(zip(E.ETIQUETAS, celdas))}
            continue
        m = _RE_FUGA.match(linea)
        if m:
            a["fuga"][m.group(1)] = {
                "texto": float(m.group(2)), "pmids": int(m.group(3)),
                "par": float(m.group(4)), "casi_dup": float(m.group(5))}
            continue
        m = _RE_VACIA.search(linea)
        if m:
            a["clases_vacias"].append([m.group(1), m.group(2)])
        m = _RE_FLACA.search(linea)
        if m:
            a["celda_flaca"] = {"clase": m.group(1), "parte": m.group(2),
                                "ejemplos": int(m.group(3)),
                                "articulos": int(m.group(4))}
        if "AVISO: con menos de 5 articulos" in linea:
            a["menos_de_5_articulos"] = True
        m = _RE_CASI.search(linea)
        if m:
            a["casi_dup"][m.group(2)] = {"n": int(m.group(1)),
                                         "peor": float(m.group(3))}
        if "FALLA:" in linea:
            a["fallas"] += 1
        if "PARTICION RECHAZADA" in linea:
            a["rechazada"] = True
        if linea.startswith("Particion limpia."):
            a["limpia"] = True
    a["recomendar_cv"] = bool(a["clases_vacias"]
                              or a["menos_de_5_articulos"])
    return a


_RE_TOKENS = re.compile(r"Longitud en tokens: mediana=(\d+)\s+p95=(\d+)\s+"
                        r"max=(\d+)")
_RE_TRUNCADOS = re.compile(r"AVISO: (\d+) ejemplos se truncan")


def tokens_de(lineas):
    """La revisión de longitud que imprime `barrido.py` antes de entrenar."""
    r = {}
    for linea in lineas:
        m = _RE_TOKENS.search(linea)
        if m:
            r.update(mediana=int(m.group(1)), p95=int(m.group(2)),
                     max=int(m.group(3)))
        m = _RE_TRUNCADOS.search(linea)
        if m:
            r["truncados"] = int(m.group(1))
        if "Ninguno se trunca" in linea:
            r["truncados"] = 0
    return r


def motivo_de_fallo(lineas, codigo):
    texto = "\n".join(lineas)
    if re.search(r"CUDA out of memory|OutOfMemoryError", texto):
        return "sin_memoria_gpu"
    # Sin memoria al crear el contexto o el handle de cuBLAS: en ese punto el
    # modelo apenas ocupa medio GB, así que la VRAM la tiene otro proceso. Es
    # «espera y relanza», no «el lote no cabe».
    if re.search(r"CUDA error: out of memory|CUBLAS_STATUS_ALLOC_FAILED",
                 texto):
        return "gpu_ocupada"
    if codigo in (-9, 137, -15, 143):
        return "matado"
    return "script_fallo"


def leer_gpu():
    """{total_mib, usada_mib, libre_mib} de la primera GPU.

    `memory.free` y no la lista de procesos: en este servidor
    `--query-compute-apps` no lista a nadie y aun así hay 1.2 GB tomados por
    sesiones gráficas.
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ErrorReentreno("gpu_no_disponible",
                             "nvidia-smi no está o no respondió.")
    lineas = [l for l in r.stdout.splitlines() if l.strip()]
    if r.returncode != 0 or not lineas:
        raise ErrorReentreno("gpu_no_disponible",
                             "nvidia-smi salió con código %d." % r.returncode)
    try:
        total, usada, libre = [int(float(x)) for x in lineas[0].split(",")]
    except ValueError:
        raise ErrorReentreno("gpu_no_disponible",
                             "No entendí la salida de nvidia-smi.")
    return {"total_mib": total, "usada_mib": usada, "libre_mib": libre}


def curva_de(run):
    """La curva de entrenamiento, solo números, del último checkpoint."""
    if not os.path.isdir(run):
        return None
    puntos = []
    for nombre in os.listdir(run):
        m = re.match(r"checkpoint-(\d+)$", nombre)
        if m:
            puntos.append((int(m.group(1)), nombre))
    if not puntos:
        return None
    estado = _leer_json(os.path.join(run, max(puntos)[1],
                                     "trainer_state.json"))
    if not estado:
        return None
    epocas = []
    perdida = None
    for h in estado.get("log_history") or []:
        if "loss" in h and "eval_loss" not in h:
            perdida = h["loss"]
        if "eval_loss" in h:
            epocas.append({
                "epoca": round(float(h.get("epoch") or 0), 2),
                "perdida_train": perdida,
                "perdida_dev": h.get("eval_loss"),
                "macro_f1_dev": h.get("eval_macro_f1"),
                "accuracy_dev": h.get("eval_accuracy"),
            })
    mejor = re.search(r"checkpoint-(\d+)",
                      str(estado.get("best_model_checkpoint") or ""))
    return {"epocas": epocas,
            "mejor_macro_f1_dev": estado.get("best_metric"),
            "mejor_paso": int(mejor.group(1)) if mejor else None,
            "pasos": estado.get("global_step"),
            "epocas_recorridas": estado.get("epoch")}


# ---------------------------------------------------------------- huérfanos

def _vivo(pid):
    """Vivo y no zombi. Un hijo muerto sin recoger sigue en /proc."""
    try:
        with open("/proc/%d/stat" % pid) as f:
            datos = f.read()
    except OSError:
        return False
    return datos.rsplit(")", 1)[-1].split()[0:1] != ["Z"]


def procesos_con(marca):
    """Los PID que llevan en su entorno `GRN_REENTRENAR=<marca>`.

    La marca la pone solo este orquestador, en el entorno de barrido.py, y se
    hereda al script del asesor y a lo que este lance. No se busca por la
    línea de comandos: la ruta de <runs> aparece también en la de quien USA
    el modelo (`flujo.py --modelo`, `clasificar.py`), y una corrida nueva lo
    habría matado creyéndolo huérfano. /proc/PID/environ solo se puede leer
    con la misma cuenta; los procesos ajenos se saltan.
    """
    buscado = ("%s=%s" % (MARCA_ENTORNO, marca)).encode("utf-8")
    propios = {os.getpid(), os.getppid()}
    encontrados = []
    for nombre in os.listdir("/proc"):
        if not nombre.isdigit() or int(nombre) in propios:
            continue
        try:
            with open("/proc/%s/environ" % nombre, "rb") as f:
                variables = f.read().split(b"\0")
        except OSError:
            continue
        if buscado in variables:
            encontrados.append(int(nombre))
    return sorted(encontrados)


def matar_huerfanos(marca, log=_nada, espera=5.0):
    """Mata los procesos de una corrida anterior que quedaron vivos.

    Pasa si este orquestador murió por SIGKILL o por el OOM-killer: no pudo
    matar el árbol, y `barrido.py` con el script del asesor siguen con la GPU.
    Se llama con el candado tomado, así que todo lo que encuentra es de una
    corrida muerta y no de una viva. Devuelve cuántos encontró.
    """
    pids = [p for p in procesos_con(marca) if _vivo(p)]
    if not pids:
        return 0
    log("Quedaban %d procesos de una corrida anterior; los detengo."
        % len(pids))
    propio = os.getpgrp()

    def senal(sig):
        for pid in pids:
            try:
                grupo = os.getpgid(pid)
                if grupo != propio:
                    os.killpg(grupo, sig)
                else:
                    os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    senal(signal.SIGTERM)
    limite = time.monotonic() + espera
    while time.monotonic() < limite and any(_vivo(p) for p in pids):
        time.sleep(0.2)
    if any(_vivo(p) for p in pids):
        senal(signal.SIGKILL)
    return len(pids)


# ------------------------------------------------------- la orquestación

_MODULOS = {}


def _etapa2(nombre):
    """Un script de etapa2/ como módulo, para reusar sus funciones (etapa2
    no es paquete). Se ejecuta su código de nivel superior, que solo define."""
    if nombre not in _MODULOS:
        ruta = os.path.join(RAIZ_REPO, "etapa2", nombre + ".py")
        spec = importlib.util.spec_from_file_location(
            "reentrenar_%s" % nombre, ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        _MODULOS[nombre] = modulo
    return _MODULOS[nombre]


def nombre_run():
    B = _etapa2("barrido")
    c = [c for c in B.configuraciones([B.SEMILLA])
         if c["i"] == CONFIGURACION][0]
    return B.nombre_de(c)


def _codigo():
    """El commit del repositorio y si hay cambios sin commitear."""
    try:
        commit = subprocess.run(
            ["git", "-C", RAIZ_REPO, "rev-parse", "--short=10", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=10).stdout.strip()
        cambios = subprocess.run(
            ["git", "-C", RAIZ_REPO, "status", "--porcelain",
             "--untracked-files=no"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "limpio": None}
    return {"commit": commit or None, "limpio": not cambios}


def _huellas(rutas_):
    return dict((os.path.basename(r), procedencia.huella(r)) for r in rutas_)


def _correr(argv, log, detener, cwd, entorno=None):
    """`proceso.correr` que devuelve el código en vez de lanzar ErrorProceso:
    sus `ultimas` líneas vienen sin filtrar y no deben viajar en un mensaje."""
    try:
        return proceso.correr(argv, log=log, detener=detener, cwd=cwd,
                              entorno=entorno)["codigo"]
    except proceso.ErrorProceso as e:
        return e.codigo


def _metricas_validas(r):
    return (isinstance(r, dict)
            and isinstance(r.get("dev_macro_f1"), (int, float))
            and isinstance(r.get("test_macro_f1"), (int, float)))


METRICAS = ("macro_f1", "accuracy", "precision", "recall", "loss",
            "samples_per_second")


def _metricas(r):
    m = {"segundos": r.get("segundos"), "max_length": r.get("max_length"),
         "epocas": r.get("dev_epoch")}
    for parte in ("dev", "test"):
        for k in METRICAS:
            m["%s_%s" % (parte, k)] = r.get("%s_%s" % (parte, k))
    return m


def ejecutar(raiz, nombre, base, pares, reservas, script, python=None,
             ciego=None, folds=None, hasta="entrenamiento",
             aceptar_base_distinta=False, horas=HORAS,
             gpu_min_mib=GPU_MIN_MIB, max_length=MAX_LENGTH,
             conservar_checkpoints=False, hoja=None, log=_nada,
             detener=None):
    """Corre la pista D y devuelve el estado final (el de `estado.json`).

    Los errores de un paso no se lanzan: quedan en el estado (`estatus`
    error o cancelado, con su `motivo`) y en RESULTADOS.md, que se escribe
    siempre. Lanza Ocupado si otra corrida con ese nombre tiene el candado,
    ErrorReentreno si las carpetas caen en un repositorio y ValueError si los
    argumentos no sirven.
    """
    if os.name == "nt":
        raise ValueError("reentrenar es para el servidor (POSIX).")
    validar_nombre(nombre)
    if hasta not in HASTA:
        raise ValueError("--hasta tiene que ser uno de %s." % ", ".join(HASTA))
    if folds is not None and folds < 3:
        raise ValueError("--folds tiene que ser 3 o más.")
    if isinstance(reservas, str):
        reservas = [reservas]
    entradas = [("--pares", pares), ("--base", base), ("--script", script)]
    entradas += [("--reservar", x) for x in reservas or ()]
    if ciego:
        entradas.append(("--ciego", ciego))
    for flag, ruta in entradas:
        if not ruta or not os.path.isfile(os.path.expanduser(ruta)):
            # Sin la ruta: la de --base dice dónde vive la base.
            raise ValueError("No encuentro el archivo de %s." % flag)
    if not reservas:
        raise ValueError("Falta --reservar: sin reservas, el 44 % "
                         "recalculado mediría memoria.")
    r = rutas(raiz, nombre)
    detener = detener or threading.Event()
    viejo = os.umask(0o077)
    try:
        avisos = preparar_carpetas(r)
        candado = tomar_candado(r["candado"])
        try:
            corrida = _Corrida(
                r, nombre, os.path.abspath(os.path.expanduser(base)),
                os.path.abspath(os.path.expanduser(pares)),
                [os.path.abspath(os.path.expanduser(x)) for x in reservas],
                os.path.abspath(os.path.expanduser(script)),
                python or os.environ.get("GRN_PYTHON_BERT") or sys.executable,
                os.path.abspath(os.path.expanduser(ciego)) if ciego else None,
                folds, hasta, aceptar_base_distinta, horas, gpu_min_mib,
                str(max_length), conservar_checkpoints, hoja, log, detener)
            corrida.estado["avisos"] = avisos
            return corrida.correr()
        finally:
            soltar_candado(candado)
    finally:
        os.umask(viejo)


class _Corrida:
    """Una corrida con el candado tomado. Cada paso es un método `_paso_*`
    que llena su entrada de `estado["pasos"]`."""

    def __init__(self, r, nombre, base, pares, reservas, script, python,
                 ciego, folds, hasta, aceptar_base_distinta, horas,
                 gpu_min_mib, max_length, conservar_checkpoints, hoja, log,
                 detener):
        self.r = r
        self.nombre = nombre
        self.base, self.pares, self.reservas = base, pares, reservas
        self.script, self.python, self.ciego = script, python, ciego
        self.folds, self.hasta = folds, hasta
        self.aceptar_base_distinta = aceptar_base_distinta
        self.horas, self.gpu_min_mib = horas, gpu_min_mib
        self.max_length = max_length
        self.conservar_checkpoints = conservar_checkpoints
        self.hoja = hoja
        self.salida = log
        self.detener = detener
        self.tope = threading.Event()
        # Las entradas pueden vivir fuera de <raiz> (/tmp, /srv): sin esto,
        # un error de lectura de una reserva publicaba su ruta.
        extra = [(base, "<base>"), (pares, "<pares>"), (script, "<script>")]
        extra += [(x, "<reservas>") for x in reservas]
        if ciego:
            extra.append((ciego, "<ciego>"))
        if os.path.isabs(python):
            extra.append((python, "<python>"))
        self.san = Saneador(r, extra=extra)
        self.previo = leer_estado(r["estado"]).get("pasos") or {}
        self.locus = None
        self.estado = collections.OrderedDict([
            ("version", 1), ("nombre", nombre), ("estatus", "corriendo"),
            ("motivo", None), ("detalle", None), ("pid", os.getpid()),
            ("inicio", _ahora()), ("fin", None), ("hasta", hasta),
            ("parametros", collections.OrderedDict([
                ("configuracion", CONFIGURACION), ("run", nombre_run()),
                ("modelo", MODELO), ("max_length", max_length),
                ("folds", folds), ("horas", horas),
                ("gpu_min_mib", gpu_min_mib),
                ("aceptar_base_distinta", aceptar_base_distinta),
                ("conservar_checkpoints", conservar_checkpoints),
                # El nombre de una hoja del libro confidencial no se guarda:
                # basta saber si se dio.
                ("hoja", hoja is not None),
                ("semilla_datos", E.SEMILLA),
                ("semilla_particion", SEMILLA_PARTICION),
                ("script_huella", procedencia.huella(script)),
                ("ciego", bool(ciego))])),
            ("codigo", _codigo()),
            ("pasos", collections.OrderedDict()),
            ("informe", None),
        ])
        self.archivo_log = None

    # ---- registro

    def registrar(self, linea):
        limpia = self.san.linea(linea)
        if limpia is None:
            self.estado["lineas_omitidas"] = (
                self.estado.get("lineas_omitidas", 0) + 1)
            return
        if self.archivo_log is not None:
            self.archivo_log.write("%s %s\n" % (_hora(), limpia))
            self.archivo_log.flush()
        self.salida(limpia)

    def guardar(self):
        escribir_estado(self.r["estado"], self.estado)

    def paso(self, nombre, funcion):
        if self.detener.is_set():
            raise proceso.Cancelado("antes de %s" % nombre)
        self.registrar("--- %s" % nombre)
        info = collections.OrderedDict([("estatus", "corriendo"),
                                        ("inicio", _ahora())])
        self.estado["pasos"][nombre] = info
        self.guardar()
        t0 = time.monotonic()
        try:
            resultado = funcion(info)
            if info["estatus"] == "corriendo":
                info["estatus"] = "ok"
            return resultado
        except (proceso.Cancelado, KeyboardInterrupt):
            info["estatus"] = "cancelado"
            raise
        except BaseException:
            info["estatus"] = "error"
            raise
        finally:
            info["fin"] = _ahora()
            info["segundos"] = round(time.monotonic() - t0, 1)
            self.guardar()

    def _reusar(self, nombre, info, **iguales):
        """Si el paso anterior terminó bien con las mismas entradas, copia su
        entrada del estado y devuelve True."""
        ant = self.previo.get(nombre) or {}
        if ant.get("estatus") not in ("ok", "saltado"):
            return False
        for llave, valor in iguales.items():
            if ant.get(llave) != valor:
                return False
        for llave, valor in ant.items():
            if llave not in ("estatus", "inicio", "fin", "segundos"):
                info[llave] = valor
        info["estatus"] = "saltado"
        self.registrar("%s: sin cambios desde la corrida anterior; se reusa."
                       % nombre)
        return True

    # ---- la corrida

    def correr(self):
        os.makedirs(self.r["barrido"], 0o700, exist_ok=True)
        self.archivo_log = open(self.r["log"], "a", encoding="utf-8")
        self.archivo_log.write("\n=== %s inicio (PID %d)\n"
                               % (_ahora(), os.getpid()))
        self.guardar()
        try:
            self.paso("reservas", self._paso_reservas)
            conteos = self.paso("datos", self._paso_datos)
            self.paso("base", lambda i: self._paso_base(i, conteos))
            if self.hasta != "datos":
                self.paso("particion", self._paso_particion)
                self.paso("fuga", self._paso_fuga)
                if self.folds:
                    self.paso("particion_cv", self._paso_particion_cv)
            if self.hasta == "entrenamiento":
                self.paso("entorno", self._paso_entorno)
                self.paso("entrenamiento", self._paso_entrenamiento)
                self.paso("modelo", self._paso_modelo)
                if self.folds:
                    self.paso("entrenamiento_cv", self._paso_entrenamiento_cv)
            self.estado["estatus"] = "ok"
        except (proceso.Cancelado, KeyboardInterrupt):
            self.estado["estatus"] = "cancelado"
            self.estado["motivo"] = "tope" if self.tope.is_set() else "detenido"
            self.estado["detalle"] = (
                "pasó de %s h; el entrenamiento se detuvo y no dejó resultado"
                % self.horas if self.tope.is_set() else "se pidió detener")
        except ErrorReentreno as e:
            self.estado["estatus"] = "error"
            self.estado["motivo"] = e.motivo
            self.estado["detalle"] = self.san.linea(e.detalle) or \
                "(detalle omitido por el filtro)"
        except Exception as e:
            self.estado["estatus"] = "error"
            self.estado["motivo"] = "inesperado"
            # Al estado, que va al informe publicable, solo el tipo; el
            # mensaje puede traer una ruta que el filtro no conoce. El
            # traceback va al log, línea por línea por el filtro.
            self.estado["detalle"] = "%s (el traceback está en " \
                "reentrenar.log)" % type(e).__name__
            for linea in traceback.format_exc().splitlines():
                self.registrar(linea)
        finally:
            self._cerrar()
        return self.estado

    def _heredar(self):
        """Los resultados de entrenamiento de una corrida anterior, si siguen
        valiendo para la partición de hoy.

        Sin esto, relanzar con `--hasta particion` (o para agregar `--ciego`)
        después de entrenar dejaba un RESULTADOS.md sin métricas: el estado se
        arma de cero en cada corrida. Se toman de `entrenamiento.json`, atado a
        la huella de la partición, y no del estado anterior, que una corrida
        intermedia puede haber reescrito sin esos pasos.
        """
        hue = (self.estado["pasos"].get("particion") or {}).get("huella")
        if not hue:
            return
        for paso, ruta in (("entrenamiento", self.r["entrenamiento"]),
                           ("entrenamiento_cv", self.r["entrenamiento_cv"])):
            if paso in self.estado["pasos"]:
                continue
            guardado = _leer_json(ruta) or {}
            if guardado.get("huella") == hue and guardado.get("info"):
                info = dict(guardado["info"])
                info["estatus"] = "previo"
                self.estado["pasos"][paso] = info
        if ("modelo" not in self.estado["pasos"]
                and "entrenamiento" in self.estado["pasos"]):
            curva = _leer_json(self.r["curva"])
            if curva:
                self.estado["pasos"]["modelo"] = {"estatus": "previo",
                                                  "curva": curva}

    def _cerrar(self):
        """Cierra la corrida. Nada de aquí puede lanzar: un disco lleno al
        escribir el informe no debe dejar un traceback con rutas en la
        terminal, ni el candado sin soltar."""
        self.estado["fin"] = _ahora()
        if self.estado["estatus"] in ("ok", "error"):
            try:
                self._heredar()
            except Exception as e:
                self.registrar("No pude leer el entrenamiento anterior (%s)."
                               % type(e).__name__)
        try:
            self.estado["huerfanos_al_cerrar"] = matar_huerfanos(
                self.r["runs"], self.registrar)
        except Exception:
            pass
        for intento in (self.guardar,
                        lambda: escribir_informe(self.r, self.estado,
                                                 self.san),
                        self.guardar):
            try:
                intento()
            except Exception as e:
                self.estado["error_al_cerrar"] = type(e).__name__
        motivo = self.estado.get("motivo")
        self.registrar("=== fin: %s%s" % (self.estado["estatus"],
                                          " (%s)" % motivo if motivo else ""))
        try:
            self.archivo_log.close()
        except Exception:
            pass
        self.archivo_log = None

    # ---- los pasos

    def _paso_reservas(self, info):
        try:
            v = verificar_reservas(self.reservas)
        except ValueError as e:
            raise ErrorReentreno("reservas", str(e))
        info.update(v)
        self.registrar("Reservas: %d archivos; %d PMIDs y %d oraciones; de la "
                       "muestra de juicios faltan %d PMIDs y %d oraciones."
                       % (v["archivos"], v["pmids"], v["oraciones"],
                          v["faltan_pmids"], v["faltan_oraciones"]))
        if v["faltan_pmids"] or v["faltan_oraciones"]:
            raise ErrorReentreno(
                "reservas_incompletas",
                "Faltan %d PMIDs y %d oraciones de la muestra de juicios. "
                "Regenera el archivo con `python -m grn_verificacion.cli "
                "reservas --ciego <conjunto ciego de etapa2> --salida ...`."
                % (v["faltan_pmids"], v["faltan_oraciones"]))

    def _paso_datos(self, info):
        r = self.r
        entradas = collections.OrderedDict([
            ("pares", procedencia.huella(self.pares)),
            ("base", procedencia.huella(self.base)),
            ("reservas", [procedencia.huella(x) for x in self.reservas]),
            ("codigo", _huellas([
                E.__file__.replace(".pyc", ".py"),
                os.path.join(RAIZ_REPO, "grn_verificacion", "validacion.py"),
                os.path.join(RAIZ_REPO, "grn_bronce", "texto.py")]))])
        # La hoja como huella: alcanza para saber si cambió, y el nombre de
        # una hoja del libro confidencial no llega al estado.
        hoja = (hashlib.sha256(self.hoja.encode("utf-8")).hexdigest()[:16]
                if self.hoja is not None else None)
        parametros = {"hoja": hoja, "semilla": E.SEMILLA,
                      "max_por_par": E.MAX_POR_PAR,
                      "proporcion_negativos": E.PROPORCION_NEGATIVOS}
        salidas = [os.path.join(r["datos"], n)
                   for n in E.ARCHIVOS + (E.ARCHIVO_CONTEOS,)]
        huellas_salida = (_huellas(salidas)
                          if all(os.path.isfile(s) for s in salidas) else None)
        if huellas_salida and self._reusar(
                "datos", info, entradas=entradas, parametros=parametros,
                salidas=huellas_salida):
            registro = _leer_json(os.path.join(r["datos"], E.ARCHIVO_CONTEOS))
            conteos = registro["conteos"]
        else:
            try:
                conteos = E.ejecutar(self.pares, self.base, self.reservas,
                                     r["datos"], hoja=self.hoja,
                                     log=self.registrar)
            except ValueError as e:
                raise ErrorReentreno("datos", str(e))
            except Exception as e:
                # Una excepción que no es ValueError puede traer el valor de
                # una celda en su mensaje: solo su tipo.
                raise ErrorReentreno(
                    "datos",
                    "%s al leer o construir. El detalle se omite porque puede "
                    "traer contenido de la base; para verlo, corre `cli "
                    "datos-entrenamiento` a mano en el servidor."
                    % type(e).__name__)
            info["entradas"] = entradas
            info["parametros"] = parametros
            info["salidas"] = _huellas(salidas)
        # A <resultados>, solo los conteos: el conteos.json de <datos> trae
        # también el nombre de la hoja y las huellas de las entradas.
        _escribir_texto(r["conteos"], json.dumps(
            {"conteos": conteos}, ensure_ascii=False, indent=2) + "\n")
        info["resumen"] = [l for l in (self.san.linea(x)
                                       for x in E.resumen(conteos)) if l]
        e = conteos["entrenamiento"]
        info["ejemplos"] = e["ejemplos"]
        info["por_etiqueta"] = e["por_etiqueta"]
        return conteos

    def _paso_base(self, info, conteos):
        filas = filas_cotejo(conteos["base"])
        distintas = [f for f in filas if not f[3]]
        info["cotejo"] = filas
        info["diferencias"] = len(distintas)
        for clave, esperado, medido, _ in distintas:
            self.registrar("Base: %s esperado %s, medido %s."
                           % (clave, esperado, medido))
        if not distintas:
            self.registrar("Base: coincide con PLAN.md 2.4 en los %d conteos."
                           % len(filas))
            return
        if not self.aceptar_base_distinta:
            raise ErrorReentreno(
                "base_distinta",
                "La base no coincide con PLAN.md 2.4 en %d conteos (ver "
                "RESULTADOS.md). Puede ser otra versión de la base o el "
                "lector, que nunca había leído la real. No se entrena hasta "
                "decidirlo; con --aceptar-base-distinta se sigue."
                % len(distintas))
        info["aceptada_distinta"] = True
        self.registrar("AVISO: se sigue con la base distinta "
                       "(--aceptar-base-distinta).")

    def _particionar(self, salida, extra, archivo_txt):
        """Corre particionar.py; (código, líneas filtradas)."""
        lineas = []

        def capturar(linea):
            limpia = self.san.linea(linea)
            if limpia is not None:
                lineas.append(limpia)
            self.registrar(linea)

        argv = [sys.executable, "-u", PARTICIONAR,
                "--entrada", self.r["datos"], "--salida", salida,
                "--por", "pmid", "--semilla", str(SEMILLA_PARTICION)] + extra
        codigo = _correr(argv, capturar, self.detener, cwd=self.r["datos"])
        _escribir_texto(archivo_txt, "\n".join(lineas) + "\n")
        return codigo, lineas

    def _paso_particion(self, info):
        P = self.r["particion"]
        B = _etapa2("barrido")
        entradas = {"train": procedencia.huella(os.path.join(
                        self.r["datos"], E.ARCHIVOS[0])),
                    "particionar": procedencia.huella(PARTICIONAR),
                    "semilla": SEMILLA_PARTICION}
        try:
            actual = B.huella(P)
        except OSError:
            actual = None
        if (actual and os.path.isfile(os.path.join(P, "label_mapping.json"))
                and os.path.isfile(self.r["particion_txt"])
                and self._reusar("particion", info, entradas=entradas,
                                 huella=actual)):
            return
        codigo, lineas = self._particionar(P, [], self.r["particion_txt"])
        avisos = avisos_particion(lineas)
        info["entradas"] = entradas
        info["codigo"] = codigo
        info["avisos"] = avisos
        if avisos["rechazada"] or codigo != 0 or not avisos["limpia"]:
            raise ErrorReentreno(
                "particion_rechazada" if avisos["rechazada"]
                else "particion_error",
                "particionar.py salió con código %d%s; no se entrena con esta "
                "partición aunque haya escrito archivos."
                % (codigo, " y dijo PARTICION RECHAZADA"
                   if avisos["rechazada"] else ""))
        info["huella"] = B.huella(P)
        if avisos["recomendar_cv"]:
            self.registrar("AVISO: una clase de dev o test falta o sale de "
                           "menos de 5 artículos: la cifra honesta es la de "
                           "validación cruzada (--folds 5).")

    def _locus(self):
        if self.locus is None:
            self.locus = locus_por_ejemplo(
                os.path.join(self.r["datos"], E.ARCHIVOS[0]), self.pares)
        return self.locus

    def _paso_fuga(self, info):
        entradas = {"particion": self.estado["pasos"]["particion"]["huella"],
                    "pares": procedencia.huella(self.pares),
                    "ciego": procedencia.huella(self.ciego)
                    if self.ciego else None}
        if self._reusar("fuga", info, entradas=entradas):
            return
        info["entradas"] = entradas
        ciego = pares_del_ciego(self.ciego) if self.ciego else None
        f = fuga_por_par(self.r["particion"], self._locus(), ciego)
        info.update(f)
        for parte in ("dev", "test"):
            n, l = f[parte]["nombres"], f[parte]["locus"]
            if not n["n"]:
                continue
            self.registrar(
                "Fuga por par en %s: par ya visto en train %.1f%% por nombres "
                "y %.1f%% por locus; línea base macro-F1 %s (clase "
                "mayoritaria %s)."
                % (parte, 100.0 * n["con_par_en_train"] / n["n"],
                   100.0 * l["con_par_en_train"] / l["n"], l["macro_f1"],
                   l["macro_f1_mayoritaria"]))

    def _paso_particion_cv(self, info):
        PCV = _particion_cv(self.r, self.folds)
        codigo, lineas = self._particionar(
            PCV, ["--folds", str(self.folds)], self.r["particion_cv_txt"])
        bloques, actual = {"global": []}, "global"
        for linea in lineas:
            m = re.match(r"--- pliegue (\d+):", linea)
            if m:
                actual = "fold_%s" % m.group(1)
                bloques[actual] = []
            bloques[actual].append(linea)
        info["codigo"] = codigo
        info["avisos"] = avisos_particion(bloques["global"])
        info["pliegues"] = dict(
            (k, avisos_particion(v)) for k, v in bloques.items()
            if k != "global")
        rechazada = any(a["fallas"] for a in info["pliegues"].values())
        if codigo != 0 or rechazada:
            raise ErrorReentreno(
                "particion_rechazada" if rechazada else "particion_error",
                "particionar.py --folds %d salió con código %d."
                % (self.folds, codigo))

    def _corridas_de_barrido(self):
        """[(partición, carpeta de resultados de barrido, carpeta de trabajo)]
        de lo que hay que entrenar: el run 22 y, con --folds, cada pliegue."""
        lista = [(self.r["particion"], self.r["barrido"], self.r["runs"])]
        if self.folds:
            PCV = _particion_cv(self.r, self.folds)
            for i in range(self.folds):
                trabajo = os.path.join(self.r["runs"], "cv", "fold_%d" % i)
                lista.append((os.path.join(PCV, "fold_%d" % i),
                              os.path.join(trabajo, "resultados"), trabajo))
        return lista

    def _entrenamiento_hecho(self):
        """Si ya hay resultado válido de cada entrenamiento con la partición
        de hoy, y pesos del run 22: entonces no hace falta la GPU."""
        B = _etapa2("barrido")
        nombre = nombre_run()
        for datos, resultados, _ in self._corridas_de_barrido():
            try:
                hue = B.huella(datos)
            except OSError:
                return False
            r = _leer_json(os.path.join(resultados, nombre + ".json"))
            if not (_metricas_validas(r) and r.get("huella") == hue
                    and str(r.get("max_length")) == self.max_length):
                return False
        run = os.path.join(self.r["runs"], nombre)
        return any(os.path.isfile(os.path.join(run, n))
                   for n in ("pytorch_model.bin", "model.safetensors"))

    def _paso_entorno(self, info):
        # Relanzar con todo entrenado (para agregar --ciego, para rehacer el
        # informe) no debe exigir GPU libre: en la GPU compartida la memoria
        # cambia todo el tiempo, y la corrida acababa en gpu_ocupada sin nada
        # que entrenar.
        if self._entrenamiento_hecho():
            info["estatus"] = "saltado"
            info["nota"] = ("el entrenamiento ya está hecho con esta "
                            "partición; no hace falta la GPU")
            self.registrar("entorno: %s." % info["nota"])
            return
        info["huerfanos"] = matar_huerfanos(self.r["runs"], self.registrar)
        gpu = leer_gpu()
        info["gpu"] = gpu
        self.registrar("GPU: %d MiB libres de %d (mínimo %d)."
                       % (gpu["libre_mib"], gpu["total_mib"],
                          self.gpu_min_mib))
        if gpu["libre_mib"] < self.gpu_min_mib:
            raise ErrorReentreno(
                "gpu_ocupada",
                "La GPU tiene %d MiB libres y hacen falta %d: alguien más la "
                "está usando. Espera y relanza; lo hecho no se repite."
                % (gpu["libre_mib"], self.gpu_min_mib))
        libre = shutil.disk_usage(self.r["runs"]).free / float(2 ** 30)
        info["disco_libre_gib"] = round(libre, 1)
        if libre < DISCO_MIN_GIB:
            raise ErrorReentreno(
                "disco", "Quedan %.1f GiB libres en <runs>; hacen falta %d."
                % (libre, DISCO_MIN_GIB))
        lineas = []
        codigo = _correr([self.python, "-c", SONDA, MODELO], lineas.append,
                         self.detener, cwd=self.r["runs"],
                         entorno=self._entorno_hijos())
        sonda = {}
        for linea in lineas:
            if linea.startswith("SONDA "):
                sonda = json.loads(linea[len("SONDA "):])
        info["sonda"] = sonda
        info["sonda_codigo"] = codigo
        self.registrar("Sonda: Python %s, torch %s, transformers %s, CUDA %s, "
                       "modelo en caché %s."
                       % (sonda.get("python"), sonda.get("torch"),
                          sonda.get("transformers"),
                          "sí" if sonda.get("cuda") else "no",
                          "sí" if sonda.get("modelo") else "no"))
        if not sonda.get("cuda"):
            raise ErrorReentreno(
                "sin_cuda",
                "El intérprete del entrenamiento no ve CUDA; el script del "
                "asesor entrenaría en CPU sin avisar. Revisa --python.")
        if not sonda.get("modelo"):
            raise ErrorReentreno(
                "modelo_no_en_cache",
                "BioBERT no carga sin red (%s). Revisa la caché de Hugging "
                "Face o HF_HOME." % sonda.get("error_modelo"))
        if os.environ.get("HF_HOME"):
            self.registrar("AVISO: HF_HOME está puesto; el modelo sale de esa "
                           "caché y no de la de la cuenta.")

    def _entorno_hijos(self):
        """Sin red, y con la marca que identifica a los hijos de esta corrida
        para `procesos_con`."""
        return dict(ENTORNO_HF, **{MARCA_ENTORNO: self.r["runs"]})

    def _barrido(self, datos, trabajo, resultados, conservar, info):
        """Corre barrido.py --solo 22 y devuelve su JSON de resultado.

        Lo que lo hace distinto de llamarlo a secas: el éxito se decide por el
        JSON con métricas y la huella de esta partición, no por el código de
        salida; un run a medias se borra antes; y hay tope de horas.
        """
        B = _etapa2("barrido")
        nombre = nombre_run()
        hue = B.huella(datos)
        os.makedirs(resultados, 0o700, exist_ok=True)
        os.makedirs(trabajo, 0o700, exist_ok=True)
        destino = os.path.join(resultados, nombre + ".json")
        anterior = _leer_json(destino)
        if anterior is not None:
            if anterior.get("huella") == hue:
                if str(anterior.get("max_length")) != self.max_length:
                    raise ErrorReentreno(
                        "parametros_distintos",
                        "Hay un resultado de esta partición con max_length %s "
                        "y se pidió %s: usa otro --nombre."
                        % (anterior.get("max_length"), self.max_length))
                if _metricas_validas(anterior):
                    info["estatus"] = "saltado"
                    info["huella"] = hue
                    # Los tokens no van en el JSON de barrido.py: van aparte,
                    # atados a la misma huella.
                    lado = _leer_json(destino + ".tokens") or {}
                    if lado.get("huella") == hue:
                        info["tokens"] = lado.get("tokens")
                    self.registrar("%s: ya estaba entrenado con esta "
                                   "partición; se reusa." % nombre)
                    return anterior
            # De otra partición: barrido.py se negaría a seguir. Se aparta.
            os.replace(destino, destino + ".anterior")
        run = os.path.join(trabajo, nombre)
        if os.path.isdir(run):
            # Sin resultado no hay modelo bueno ahí: son los checkpoint-* de un
            # intento cortado, que save_total_limit mezclaría con los nuevos.
            if os.path.dirname(os.path.abspath(run)) != os.path.abspath(
                    trabajo):
                raise ErrorReentreno("inesperado", "run fuera de <runs>")
            shutil.rmtree(run)
            self.registrar("Se borró un %s a medias de un intento anterior."
                           % nombre)
        if os.path.exists(destino + ".error"):
            os.remove(destino + ".error")
        argv = [self.python, "-u", BARRIDO, "--datos", datos,
                "--script", self.script, "--trabajo", trabajo,
                "--resultados", resultados, "--modelo", MODELO,
                "--max_length", self.max_length, "--solo", str(CONFIGURACION)]
        if conservar:
            argv.append("--conservar")
        crudas = collections.deque(maxlen=400)
        longitud = []

        def capturar(linea):
            # Las crudas solo sirven para reconocer el motivo de un fallo y
            # nunca se escriben.
            crudas.append(linea)
            if "Longitud en tokens" in linea or "se trunca" in linea:
                longitud.append(linea)
            self.registrar(linea)

        def disparar():
            self.tope.set()
            self.detener.set()

        reloj = threading.Timer(self.horas * 3600.0, disparar)
        reloj.daemon = True
        reloj.start()
        try:
            codigo = _correr(argv, capturar, self.detener, cwd=trabajo,
                             entorno=self._entorno_hijos())
        finally:
            reloj.cancel()
        info["tokens"] = tokens_de(longitud)
        info["huella"] = hue
        resultado = _leer_json(destino)
        if (_metricas_validas(resultado) and resultado.get("huella") == hue):
            # `.json.tokens` no lo recoge el resumen de barrido.py, que busca
            # `*.json` y `*.json.error`.
            _escribir_texto(destino + ".tokens", json.dumps(
                {"huella": hue, "tokens": info["tokens"]}) + "\n")
            return resultado
        error = _leer_json(destino + ".error") or {}
        cod = error.get("codigo", codigo)
        motivo = motivo_de_fallo(list(crudas), cod)
        raise ErrorReentreno(
            motivo, "El entrenamiento no dejó resultado (código %s). El "
                    "motivo está en reentrenar.log." % cod)

    def _paso_entrenamiento(self, info):
        res = self._barrido(self.r["particion"], self.r["runs"],
                            self.r["barrido"], True, info)
        info["metricas"] = _metricas(res)
        self.registrar("Run %d: dev macro-F1 %.4f, test macro-F1 %.4f."
                       % (CONFIGURACION, res["dev_macro_f1"],
                          res["test_macro_f1"]))
        self._guardar_entrenamiento(self.r["entrenamiento"], info)

    def _guardar_entrenamiento(self, ruta, info):
        """La copia con solo números que puede ver la sesión, atada a la huella
        de la partición (ver `_heredar`)."""
        copia = dict((k, v) for k, v in info.items()
                     if k not in ("estatus", "inicio", "fin", "segundos"))
        _escribir_texto(ruta, json.dumps(
            {"huella": self.estado["pasos"]["particion"]["huella"],
             "info": copia}, ensure_ascii=False, indent=2) + "\n")

    def _paso_modelo(self, info):
        run = os.path.join(self.r["runs"], nombre_run())
        if not any(os.path.isfile(os.path.join(run, n))
                   for n in ("pytorch_model.bin", "model.safetensors")):
            raise ErrorReentreno("sin_modelo",
                                 "No hay pesos en la carpeta del run.")
        # `trainer.save_model()` no escribe el mapa de etiquetas, y
        # `clasificar.py` lo exige junto a los pesos.
        shutil.copyfile(os.path.join(self.r["particion"], "label_mapping.json"),
                        os.path.join(run, "label_mapping.json"))
        config = _leer_json(os.path.join(run, "config.json")) or {}
        id2label = dict((str(k), v)
                        for k, v in (config.get("id2label") or {}).items())
        info["id2label_ok"] = id2label == ID2LABEL
        if not info["id2label_ok"]:
            raise ErrorReentreno(
                "id2label", "El config.json del modelo no trae el orden "
                            "activates, no_relation, regulates, represses.")
        curva = curva_de(run)
        if curva is None:
            # Los checkpoints ya se borraron en la corrida que entrenó.
            curva = _leer_json(self.r["curva"])
        if curva is not None:
            info["curva"] = curva
            _escribir_texto(self.r["curva"],
                            json.dumps(curva, indent=2) + "\n")
        borrados = 0
        if not self.conservar_checkpoints:
            for nombre in os.listdir(run):
                if re.match(r"checkpoint-\d+$", nombre):
                    shutil.rmtree(os.path.join(run, nombre))
                    borrados += 1
        info["checkpoints_borrados"] = borrados

    def _paso_entrenamiento_cv(self, info):
        pliegues = collections.OrderedDict()
        info["pliegues"] = pliegues
        for i, (datos, resultados, trabajo) in enumerate(
                self._corridas_de_barrido()[1:]):
            if self.detener.is_set():
                raise proceso.Cancelado("antes del pliegue %d" % i)
            pliegue = "fold_%d" % i
            self.registrar("Pliegue %d de %d." % (i + 1, self.folds))
            sub = {"estatus": "corriendo"}
            res = self._barrido(datos, trabajo, resultados, False, sub)
            m = _metricas(res)
            partes = leer_particion(datos)
            m["linea_base_macro_f1_test"] = linea_base_memorizacion(
                partes["train"], partes["test"],
                lambda e: self._locus().get((str(e["pmid"]), e["text"]))
            )["macro_f1"]
            m["tokens"] = sub.get("tokens")
            pliegues[pliegue] = m
            self.guardar()
        agregado = collections.OrderedDict()
        for llave in ("test_macro_f1", "dev_macro_f1", "test_accuracy",
                      "linea_base_macro_f1_test"):
            valores = [p[llave] for p in pliegues.values()
                       if isinstance(p.get(llave), (int, float))]
            if valores:
                agregado[llave] = {
                    "media": round(statistics.mean(valores), 4),
                    "sd": round(statistics.stdev(valores), 4)
                    if len(valores) > 1 else None,
                    "min": round(min(valores), 4),
                    "max": round(max(valores), 4)}
        info["agregado"] = agregado
        self._guardar_entrenamiento(self.r["entrenamiento_cv"], info)


# ----------------------------------------------------------------- informe

def _pct(a, b):
    return "%.1f %%" % (100.0 * a / b) if b else "—"


def _num(x, fmt="%.4f"):
    if x is None:
        return "—"
    if isinstance(x, (int, float)):
        return fmt % x
    return str(x)


def informe(estado, r=None):
    """RESULTADOS.md: solo conteos y métricas, armado desde el estado.

    Se escribe siempre, también si la corrida se detuvo, para que lo hecho
    hasta ahí no haya que leerlo del log. Antes de escribirse pasa por
    `verificar_publicable`.
    """
    p = estado.get("pasos") or {}
    par = estado.get("parametros") or {}
    cod = estado.get("codigo") or {}
    s = []
    w = s.append
    motivo = estado.get("motivo")
    w("# Reentrenamiento del BioBERT con la base curada: %s"
      % estado.get("nombre"))
    w("")
    w("- Estado: **%s**%s." % (estado.get("estatus"),
                               " (%s: %s)" % (motivo, MOTIVOS.get(motivo, ""))
                               if motivo else ""))
    if estado.get("detalle"):
        w("- Detalle: %s" % estado["detalle"])
    w("- Inicio %s; fin %s (UTC)." % (estado.get("inicio"),
                                      estado.get("fin") or "—"))
    w("- Commit `%s`%s." % (cod.get("commit"),
                            "" if cod.get("limpio") else
                            ", con cambios sin commitear"))
    w("")
    w("`<datos>`, `<runs>` y `<resultados>` son carpetas del servidor. Los "
      "ejemplos y el modelo no salen de ahí; este archivo lleva solo conteos "
      "y métricas.")
    w("")

    w("## 1. Receta")
    w("")
    w("- Run %s (`%s`): lr 3e-5, 8 épocas, lote 16, calentamiento 0.1, "
      "weight decay 0.01, max_length %s, semilla 42, pesos de clase y paro "
      "temprano con paciencia 2, sobre `%s`."
      % (par.get("configuracion"), par.get("run"), par.get("max_length"),
         par.get("modelo")))
    w("- Partición por PMID, 80/10/10%s."
      % ("; validación cruzada de %d pliegues" % par["folds"]
         if par.get("folds") else ""))
    w("- Tope por entrenamiento: %s h. GPU libre mínima: %s MiB."
      % (par.get("horas"), par.get("gpu_min_mib")))
    w("")

    w("## 2. Reservas")
    w("")
    rv = p.get("reservas") or {}
    if rv:
        w("- %s PMIDs y %s oraciones reservados; de la muestra de 50 juicios "
          "faltan %s PMIDs y %s oraciones."
          % (rv.get("pmids"), rv.get("oraciones"), rv.get("faltan_pmids"),
             rv.get("faltan_oraciones")))
    else:
        w("- Sin datos.")
    w("")

    w("## 3. La base contra PLAN.md 2.4")
    w("")
    b = p.get("base") or {}
    if b.get("cotejo"):
        w("| conteo | esperado | medido | |")
        w("|---|---:|---:|---|")
        for clave, esperado, medido, ok in b["cotejo"]:
            w("| %s | %s | %s | %s |" % (clave, esperado, medido,
                                         "coincide" if ok else "**DIFIERE**"))
        w("")
        if not b.get("diferencias"):
            w("Coincide en todo.")
        elif b.get("aceptada_distinta"):
            w("**Difiere en %d conteos y se siguió con "
              "`--aceptar-base-distinta`.**" % b["diferencias"])
        else:
            w("**Difiere en %d conteos: no se entrenó.** Puede ser otra "
              "versión de la base o el lector; se decide antes de seguir."
              % b["diferencias"])
    else:
        w("Sin datos.")
    w("")

    w("## 4. Ejemplos")
    w("")
    d = p.get("datos") or {}
    if d.get("resumen"):
        w("```text")
        s.extend(d["resumen"])
        w("```")
    else:
        w("Sin datos.")
    w("")

    w("## 5. Partición por PMID")
    w("")
    pa = p.get("particion") or {}
    av = pa.get("avisos") or {}
    texto = None
    if r is not None and pa and os.path.isfile(r["particion_txt"]):
        with open(r["particion_txt"], encoding="utf-8") as f:
            texto = f.read().rstrip("\n")
    if texto:
        w("```text")
        w(texto)
        w("```")
        w("")
        w("- Veredicto: %s." % ("limpia" if av.get("limpia") else
                                "**RECHAZADA o incompleta**"))
        for parte, clase in av.get("clases_vacias") or []:
            w("- **%s no tiene ningún ejemplo de %s**: el macro-F1 de esa "
              "parte promedia sobre una clase menos." % (parte, clase))
        cf = av.get("celda_flaca")
        if cf:
            w("- La celda más flaca es %s en %s: %d ejemplos de %d artículos. "
              "particionar.py nombra una sola celda para dev y test juntos "
              "(en un empate, dev): que diga «%s» no quiere decir que la otra "
              "parte esté bien." % (cf["clase"], cf["parte"], cf["ejemplos"],
                                    cf["articulos"], cf["parte"]))
        for parte, c in sorted((av.get("casi_dup") or {}).items()):
            w("- %d ejemplos de %s tienen su ventana contenida en una de train "
              "(peor %.2f): fuga real que el corte por PMID no evita. La cifra "
              "de %s va con esa salvedad." % (c["n"], parte, c["peor"],
                                              parte))
        if av.get("recomendar_cv"):
            w("- **La cifra honesta es la de validación cruzada** "
              "(`--folds 5`, sección 8).")
    else:
        w("Sin datos.")
    w("")

    w("## 6. Fuga por par y línea base de memorización")
    w("")
    fu = p.get("fuga") or {}
    if fu.get("test"):
        w("Aquí la etiqueta depende casi solo del par: un par que la base "
          "registra nunca sale como `no_relation`, y uno que no registra "
          "nunca sale como relación. Partir por PMID no impide que el mismo "
          "par caiga en train y en test. La línea base predice, para cada "
          "ejemplo, la etiqueta más frecuente de su par en train (o la clase "
          "mayoritaria si el par no está): el modelo vale lo que le gana.")
        w("")
        w("| | dev | test |")
        w("|---|---:|---:|")
        dv, te = fu.get("dev") or {}, fu.get("test") or {}

        def fila(nombre, f):
            w("| %s | %s | %s |" % (nombre, f(dv), f(te)))

        fila("ejemplos", lambda x: (x.get("locus") or {}).get("n", "—"))
        fila("par ya visto en train, por nombres",
             lambda x: _pct((x.get("nombres") or {}).get("con_par_en_train", 0),
                            (x.get("nombres") or {}).get("n", 0)))
        fila("par ya visto en train, por locus",
             lambda x: _pct((x.get("locus") or {}).get("con_par_en_train", 0),
                            (x.get("locus") or {}).get("n", 0)))
        fila("acierto de la etiqueta del par, en los ya vistos",
             lambda x: _num((x.get("locus") or {}).get(
                 "acierto_en_cubiertos")))
        fila("línea base: accuracy",
             lambda x: _num((x.get("locus") or {}).get("accuracy")))
        fila("línea base: macro-F1",
             lambda x: _num((x.get("locus") or {}).get("macro_f1")))
        fila("clase mayoritaria: macro-F1",
             lambda x: _num((x.get("locus") or {}).get(
                 "macro_f1_mayoritaria")))
        w("")
        ci = fu.get("ciego")
        if ci:
            w("Conjunto ciego de la trampa del signo (6 pares). Reservar sus "
              "oraciones no aparta sus pares: entran desde otras oraciones "
              "con la etiqueta que les da la base. **Para este modelo la "
              "trampa no es una evaluación externa.** Van solo los totales: "
              "por etiqueta dirían qué registra la base de esos pares, que "
              "tienen nombre público.")
            w("")
            w("| ejemplos | train | dev | test |")
            w("|---|---:|---:|---:|")
            for clave, nombre in (("por_regulador",
                                   "con uno de sus 6 reguladores"),
                                  ("por_par", "con uno de sus 6 pares")):
                w("| %s | %s |" % (nombre, " | ".join(
                    str(ci[clave].get(x, 0)) for x in ("train", "dev",
                                                       "test"))))
            w("")
    else:
        w("Sin datos.")
        w("")

    w("## 7. Entrenamiento del run %s" % par.get("configuracion"))
    w("")
    if (p.get("entrenamiento") or {}).get("estatus") == "previo":
        w("Estas cifras son de una corrida anterior con la misma partición; "
          "en esta no se entrenó.")
        w("")
    en = p.get("entorno") or {}
    if en.get("sonda"):
        so, gpu = en["sonda"], en.get("gpu") or {}
        w("- Entorno: %s, %s MiB libres de %s; Python %s, torch %s, "
          "transformers %s; sin red." % (
              so.get("dispositivo"), gpu.get("libre_mib"),
              gpu.get("total_mib"), so.get("python"), so.get("torch"),
              so.get("transformers")))
    tr = p.get("entrenamiento") or {}
    tk = tr.get("tokens") or {}
    if tk:
        w("- Longitud en tokens: mediana %s, p95 %s, máximo %s; truncados "
          "%s." % (tk.get("mediana"), tk.get("p95"), tk.get("max"),
                   tk.get("truncados", "—")))
    m = tr.get("metricas")
    if m:
        w("- Duración %.1f min; épocas recorridas %s."
          % ((m.get("segundos") or 0) / 60.0, _num(m.get("epocas"), "%.1f")))
        w("")
        w("| | dev | test |")
        w("|---|---:|---:|")
        for k, nombre in (("macro_f1", "macro-F1"), ("accuracy", "accuracy"),
                          ("precision", "precisión macro"),
                          ("recall", "exhaustividad macro"),
                          ("loss", "pérdida"),
                          ("samples_per_second", "ejemplos por segundo")):
            fmt = "%.1f" if k == "samples_per_second" else "%.4f"
            w("| %s | %s | %s |" % (nombre, _num(m.get("dev_" + k), fmt),
                                    _num(m.get("test_" + k), fmt)))
        w("")
        lb = ((fu.get("test") or {}).get("locus") or {}).get("macro_f1")
        if isinstance(lb, (int, float)) and isinstance(
                m.get("test_macro_f1"), (int, float)):
            w("- **Modelo menos línea base**, macro-F1 de test: %+.4f."
              % (m["test_macro_f1"] - lb))
        w("- El F1 es macro sobre las cuatro clases, `no_relation` "
          "incluida.")
    mo = p.get("modelo") or {}
    cu = mo.get("curva")
    if cu and cu.get("epocas"):
        w("")
        w("| época | pérdida train | pérdida dev | macro-F1 dev |")
        w("|---:|---:|---:|---:|")
        for e in cu["epocas"]:
            w("| %s | %s | %s | %s |" % (
                _num(e.get("epoca"), "%.1f"), _num(e.get("perdida_train")),
                _num(e.get("perdida_dev")), _num(e.get("macro_f1_dev"))))
        w("")
        w("- Mejor macro-F1 de dev %s, en el paso %s de %s."
          % (_num(cu.get("mejor_macro_f1_dev")), cu.get("mejor_paso"),
             cu.get("pasos")))
    if mo.get("estatus") in ("ok", "saltado"):
        w("- El modelo quedó en `<runs>/%s`, con `label_mapping.json` "
          "junto a los pesos y el orden de etiquetas verificado; %d "
          "checkpoints borrados." % (par.get("run"),
                                     mo.get("checkpoints_borrados", 0)))
    if not (m or en.get("sonda")):
        w("Sin entrenamiento en esta corrida.")
    w("")

    w("## 8. Validación cruzada")
    w("")
    cv = p.get("entrenamiento_cv") or {}
    if cv.get("pliegues"):
        w("Cada pliegue entrena con el 60 % del corpus (dev y test son 20 % "
          "cada uno): sus cifras no se comparan punto a punto con las del "
          "reparto 80/10/10. Una sola semilla (42): la desviación mezcla la "
          "partición con el azar del entrenamiento.")
        w("")
        w("| pliegue | dev macro-F1 | test macro-F1 | test accuracy | "
          "línea base test |")
        w("|---|---:|---:|---:|---:|")
        for nombre, f in cv["pliegues"].items():
            w("| %s | %s | %s | %s | %s |" % (
                nombre, _num(f.get("dev_macro_f1")),
                _num(f.get("test_macro_f1")), _num(f.get("test_accuracy")),
                _num(f.get("linea_base_macro_f1_test"))))
        ag = cv.get("agregado") or {}
        if ag:
            w("| **media ± sd** | %s | %s | %s | %s |" % tuple(
                "%s ± %s" % (_num((ag.get(k) or {}).get("media")),
                             _num((ag.get(k) or {}).get("sd")))
                for k in ("dev_macro_f1", "test_macro_f1", "test_accuracy",
                          "linea_base_macro_f1_test")))
    else:
        w("No se corrió%s." % (" (se recomienda: ver sección 5)"
                               if av.get("recomendar_cv") else ""))
    w("")

    w("## 9. Cómo leer estas cifras")
    w("")
    w("- **Es supervisión distante.** Un positivo es «este par, en una "
      "oración de un artículo que la base cita para esa relación»; la "
      "oración no tiene por qué afirmarla. Un negativo es «un par que la base "
      "no registra», no «un par sin relación». Las dos clases traen ruido, y "
      "el F1 se mide contra etiquetas con el mismo ruido.")
    w("- **La proporción de clases no es la del flujo.** Hay una "
      "`no_relation` por positivo, tomada de los artículos que la base cita. "
      "En el flujo el modelo clasifica todos los pares de la corrida 4, la "
      "mayoría de artículos que la base no cita y con muchos más pares sin "
      "relación: con la misma tasa de falsos positivos, la precisión de las "
      "tres clases de relación será menor que aquí.")
    w("- **No es comparable con el 0.87 de E. coli** (otro organismo, otro "
      "test, y aquel con fuga) **ni con el 44 %**, que es la precisión del "
      "bronce juzgada a mano sobre 50 candidatas, reservadas para "
      "recalcularla con este modelo.")
    w("")

    w("## 10. Avisos y decisiones pendientes")
    w("")
    avisos = list(estado.get("avisos") or [])
    if estado.get("estatus") != "ok":
        avisos.append("La corrida no terminó bien: %s." % (
            MOTIVOS.get(motivo, motivo) if motivo else estado.get("estatus")))
    if estado.get("error_al_cerrar"):
        avisos.append("Al cerrar falló una escritura (%s): el estado o este "
                      "informe pueden estar incompletos."
                      % estado["error_al_cerrar"])
    if b.get("diferencias"):
        avisos.append("La base difiere de PLAN.md 2.4 en %d conteos."
                      % b["diferencias"])
    if av.get("recomendar_cv") and not cv.get("pliegues"):
        avisos.append("particionar.py recomienda validación cruzada "
                      "(`--folds 5`).")
    if tk.get("truncados"):
        avisos.append("%d ejemplos se truncan a %s tokens."
                      % (tk["truncados"], par.get("max_length")))
    if estado.get("lineas_omitidas"):
        avisos.append("El filtro omitió %d líneas del log por traer algo con "
                      "forma de contenido de la base." % estado[
                          "lineas_omitidas"])
    if estado.get("huerfanos_al_cerrar"):
        avisos.append("Al cerrar quedaban %d procesos de la corrida; se "
                      "detuvieron." % estado["huerfanos_al_cerrar"])
    if not avisos:
        avisos.append("Ninguno.")
    for a in avisos:
        w("- %s" % a)
    w("")
    return "\n".join(s)


def escribir_informe(r, estado, san=None):
    """Escribe RESULTADOS.md si pasa `verificar_publicable`; si no, lo borra
    y lo deja dicho en el estado. Nunca deja uno que no se pueda publicar."""
    texto = informe(estado, r)
    if san is not None:
        texto = san.texto(texto)
    try:
        verificar_publicable(texto)
    except ValueError as e:
        estado["informe"] = {"estatus": "no_publicable", "detalle": str(e)}
        if os.path.exists(r["informe"]):
            os.remove(r["informe"])
        return None
    _escribir_texto(r["informe"], texto)
    estado["informe"] = {"estatus": "ok", "archivo": "RESULTADOS.md"}
    return r["informe"]


# --------------------------------------------- estado, detener, desprender

def resumen_estado(raiz, nombre, lineas=15):
    """Lo que puede ver la sesión de una corrida: el estado y la cola del log,
    todo por el filtro. Devuelve líneas."""
    validar_nombre(nombre)
    r = rutas(raiz, nombre)
    san = Saneador(r)
    estado = leer_estado(r["estado"])
    if not estado:
        return ["No hay ninguna corrida %s en <raiz>." % nombre]
    pid = quien_corre(r["candado"])
    salida = []
    motivo = estado.get("motivo")
    estatus = estado.get("estatus")
    if estatus == "corriendo" and pid is None:
        estatus = "murió sin cerrar (el estado dice corriendo y nadie tiene " \
                  "el candado)"
    salida.append("Corrida %s: %s%s%s" % (
        nombre, estatus, " (%s)" % motivo if motivo else "",
        "; corre en el PID %d" % pid if pid else ""))
    salida.append("  inicio %s; actualizado %s; fin %s" % (
        estado.get("inicio"), estado.get("actualizado"),
        estado.get("fin") or "—"))
    if estado.get("detalle"):
        salida.append("  detalle: %s" % estado["detalle"])
    for aviso in estado.get("avisos") or []:
        salida.append("  AVISO: %s" % aviso)
    pasos = estado.get("pasos") or {}
    salida.append("  pasos: " + "; ".join(
        "%s %s%s" % (n, i.get("estatus"),
                     " (%.0f s)" % i["segundos"] if i.get("segundos") else "")
        for n, i in pasos.items()))
    m = (pasos.get("entrenamiento") or {}).get("metricas")
    if m:
        salida.append("  run %s: dev macro-F1 %s, test macro-F1 %s" % (
            CONFIGURACION, _num(m.get("dev_macro_f1")),
            _num(m.get("test_macro_f1"))))
    if (estado.get("informe") or {}).get("estatus") == "ok":
        salida.append("  informe: <resultados>/RESULTADOS.md")
    elif estado.get("informe"):
        salida.append("  informe: no publicable (%s)"
                      % estado["informe"].get("detalle"))
    for titulo, ruta in (("log", r["log"]), ("salida de error", r["err"])):
        if not os.path.isfile(ruta) or not os.path.getsize(ruta):
            continue
        with open(ruta, encoding="utf-8", errors="replace") as f:
            cola = collections.deque(f, maxlen=lineas)
        mostrables = [l for l in (san.linea(x) for x in cola) if l]
        if mostrables:
            salida.append("Últimas líneas del %s:" % titulo)
            salida.extend("  " + l for l in mostrables)
    return [san.texto(l) for l in salida]


def detener_corrida(raiz, nombre, esperar=60.0):
    """Detiene la corrida: SIGTERM al orquestador, que mata el árbol y cierra
    el estado; si no suelta el candado en `esperar` s, SIGKILL y se matan los
    huérfanos. Devuelve un dict con lo que pasó."""
    validar_nombre(nombre)
    r = rutas(raiz, nombre)
    pid = quien_corre(r["candado"])
    forzado = False
    if pid and pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        limite = time.monotonic() + esperar
        while time.monotonic() < limite and quien_corre(r["candado"]):
            time.sleep(0.5)
        if quien_corre(r["candado"]):
            forzado = True
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(1)
    huerfanos = matar_huerfanos(r["runs"]) if os.path.isdir("/proc") else 0
    estado = leer_estado(r["estado"])
    if estado.get("estatus") == "corriendo" and not quien_corre(r["candado"]):
        estado["estatus"] = "cancelado"
        estado["motivo"] = "detenido"
        estado["detalle"] = ("detenido a la fuerza: no cerró a tiempo"
                             if forzado else "detenido sin que cerrara")
        estado["fin"] = _ahora()
        escribir_estado(r["estado"], estado)
    return {"pid": pid, "forzado": forzado, "huerfanos": huerfanos}


def desprender(argv_cli, raiz, nombre, base=None):
    """Lanza `python -m grn_verificacion.cli <argv_cli>` en su propia sesión.

    Sin tmux en el servidor, es lo que hace que un corte de SSH o el cierre
    de la sesión de Claude no maten el entrenamiento: sin terminal que cuelgue
    no hay SIGHUP. La salida estándar va a /dev/null porque el orquestador
    escribe su propio log filtrado; los errores que no alcance a atrapar van
    a `reentrenar.err`, que `estado` muestra también por el filtro.

    La ruta de la base viaja en el entorno (`BASE_CURADA`) y no en `argv_cli`:
    la línea de comandos de un proceso la ve cualquier cuenta de la máquina
    (`ps`) durante las horas que dura la corrida; su entorno, solo la misma
    cuenta.
    """
    validar_nombre(nombre)
    r = rutas(raiz, nombre)
    entorno = dict(os.environ)
    if base:
        entorno["BASE_CURADA"] = os.path.abspath(os.path.expanduser(base))
    viejo = os.umask(0o077)
    try:
        for carpeta in (r["raiz"], os.path.dirname(r["resultados"]),
                        r["resultados"]):
            if not os.path.isdir(carpeta):
                os.makedirs(carpeta, 0o700)
        err = open(r["err"], "ab")
    finally:
        os.umask(viejo)
    try:
        return subprocess.Popen(
            [sys.executable, "-u", "-m", "grn_verificacion.cli"]
            + list(argv_cli),
            cwd=RAIZ_REPO, env=entorno, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=err, close_fds=True,
            start_new_session=True)
    finally:
        err.close()
