# -*- coding: utf-8 -*-
"""Verificar una carpeta del flujo antes de citar sus cifras.

`flujo.py` deja en una carpeta por corrida (`salidas/flujo/corrida4_run22/`)
lo que produjo cada paso, y cada paso ya tiene sus guardas. Lo que ninguno
mira es la cadena entera: que las oraciones que contó el bronce sean las que
leyó el puente, que los pares de la capa sean los que clasificó BioBERT y los
que agregó la red, que la base siga diciendo lo mismo que los archivos. Cada
archivo por separado está bien formado, y por eso un eslabón cambiado no
protesta: `grn_comun/procedencia.py` lo midió, la misma red publica 80.6 % o
100.0 % según qué archivo se le ponga al lado.

Cinco invariantes, que se cumplen o no:

- I1. Normalización: al menos el 95 % de las menciones de gen, proteína u
  operón de la corrida llevan locus tag. La corrida 4 da 95.07 %; el umbral
  no se afloja para que pase.
- I2. La corrida: existe, es del paso 1, terminó «ok», tiene corpus, y
  ninguna de sus filas cuelga de otra corrida o de nada.
- I3. La partición, solo con `particion`: ningún PMID ni texto canónico de
  dev o de test está también en train, y, si `etapa2/barrido_resumen.csv`
  tiene fila del run del modelo, su huella es la que el barrido registró.
- I4. La cadena de conteos y huellas, del CSV del bronce a la red.
- I5. El corpus de la corrida tiene huella y sigue siendo el que se congeló.

Y avisos, que no hacen fallar: lo que no se puede comprobar (los recursos de
una corrida anterior al sellado), las corridas zombis, las del paso 2 que
apuntan a un bronce que ya no existe, y, cuando el barrido no tiene fila del
run, que el vínculo entre el checkpoint y la partición lo afirma el flag.

Código de salida: 0 si todo cumple; 1 si falla un invariante; 2 si no se
pudo verificar (falta la carpeta o su `estado.json`, hay un `.flujo.lock`, o
algo quedó sin comprobar). Un fallo manda sobre lo no verificable: es un
hallazgo, y lo otro es una pregunta abierta.

Escribe `verificacion.json` (en la carpeta, o donde diga `salida_json`) y,
con `salida_html`, un HTML autocontenido. Los dos son publicables: ni rutas
absolutas, ni oraciones, ni locus, ni PMIDs; conteos, huellas y nombres de
archivo, y antes de escribirse pasan por `reentrenar.verificar_publicable`.
Con el código 2 por una carpeta que no se puede leer no escribe nada.

La base se abre en solo lectura (`grn_bronce.db.conectar_lectura`):
verificar no puede cambiar lo que verifica. No imprime: recibe `log`.

Biblioteca estándar y Python 3.8.
"""

import collections
import csv
import datetime
import html
import io
import json
import os
import re
import sys

from grn_bronce import db as bdb
from grn_bronce import identificar
from grn_comun import procedencia, rutas
from grn_comun.archivos import reemplazar
from grn_etl import db as db0
from grn_verificacion import entrenamiento, evaluar, reentrenar

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UMBRAL_NORMALIZACION = 0.95
# CLAUDE.md: un experimento que pasa de 4 horas se detiene. Una corrida que
# lleva más que eso en «corriendo» no está corriendo: se cortó y nadie la
# cerró, y queda así para siempre.
HORAS_ZOMBI = 4
ARCHIVO_JSON = "verificacion.json"
CANDADO = ".flujo.lock"
VERSION_INFORME = 1

CUMPLE, FALLA, NO_VERIFICABLE, NO_APLICA = (
    "cumple", "falla", "no_verificable", "no_aplica")
VEREDICTOS = {0: CUMPLE, 1: FALLA, 2: NO_VERIFICABLE}
ETIQUETAS = {CUMPLE: "Cumple", FALLA: "Falla",
             NO_VERIFICABLE: "No verificable", NO_APLICA: "No aplica"}

ESTATUS_HECHO = ("ok", "saltado")
# Sin estos no hay cadena que verificar, y se exigen hechos. No se recorre la
# lista de pasos de `flujo.py`: el paquete no importa al orquestador que lo
# invoca, y un paso que el flujo agregue después (un «paquete» al final) no
# tiene por qué romper la verificación. De los demás se mira solo lo que
# `estado.json` traiga: que ninguno esté en error. La evaluación se omite con
# `--limite` (no está la muestra completa), y entonces solo se avisa.
PASOS_EXIGIDOS = ("bronce", "pares", "biobert", "red", "capa", "evaluar")
OMITIBLE_CON_LIMITE = ("evaluar",)

# La regla de `flujo._huella`, repetida por la misma razón: los recursos de
# texto del repositorio se miden sin CRLF; lo generado (bajo `salidas/`) y lo
# binario, por bytes. Medir con otra regla daría «cambió» en un checkout de
# Windows sin que nada cambiara.
_TEXTO = (".tsv", ".csv", ".py", ".md", ".txt")
_SALIDAS = os.path.join(RAIZ, "salidas") + os.sep

# Lo que `etapa2/barrido.py` deja por run: la huella de la partición con que
# entrenó (`barrido.huella`). Con eso I3 sabe si la partición que se le pasa
# es la del checkpoint, en vez de creérselo al flag.
BARRIDO_RESUMEN = os.path.join(RAIZ, "etapa2", "barrido_resumen.csv")

PARES = "pares.jsonl"
PARES_INFORME = "pares_informe.json"
PREDICCIONES = "predicciones.jsonl"
PREDICCIONES_META = "predicciones_meta.json"
RED = "red.tsv"
RED_INFORME = "red_informe.json"
CAPA = "capa_pares.csv"
CAPA_RESUMEN = "capa_resumen.json"
SINTAXIS = "sintaxis.jsonl"
EVALUACION = "evaluacion.json"
SUFIJO_CANDIDATAS = "_oraciones_candidatas.csv"
SUFIJO_RESUMEN = "_resumen.csv"

# Las filas del `_resumen.csv` del bronce que dicen lo mismo que `conteos_de`.
# Es lo que se cita; si la base cambió después de exportarlo, ya no es cierto.
RESUMEN_BRONCE = (
    ("Documentos procesados", "documentos"),
    ("Oraciones totales (todas, se guardan aunque no sean candidatas)",
     "unidades"),
    ("Oraciones candidatas", "candidatas"),
    ("Menciones totales", "menciones"),
)

# El orden en que se leen las métricas de `evaluacion.json`, el del plan del
# 8-oct: precisión, retención, descarte, signo, dirección y sensibilidad. Lo
# que no esté aquí va después, por nombre.
ORDEN_METRICAS = ("P0_bronce", "P1_bronce_y_biobert_con_umbral",
                  "P1_bronce_y_biobert_sin_umbral", "R1_retencion_de_las_si",
                  "R1_retencion_sin_umbral", "E1_no_descartadas",
                  "E1_invertidas_descartadas", "S1_signo",
                  "D_direccion_sintaxis", "sensibilidad_14_y_27_a_no")
TOLERANCIA_WILSON = 1e-4

VINCULO_PARTICION = (
    "El vínculo entre el checkpoint de esta corrida y la partición lo afirma "
    "el flag, no la máquina: nada en la carpeta dice con qué partición se "
    "entrenó el modelo, así que I3 vale para el modelo solo si de verdad se "
    "entrenó con esa.")

# Toda ruta absoluta: con unidad (C:\... o C:/...), de red (\\servidor\...),
# bajo el home (~/...) o POSIX de dos tramos o más. No cuenta lo pegado a una
# palabra o a un número: «dmis-lab/biobert» o «80/10/10» no son rutas.
_RUTA_ABSOLUTA = re.compile(
    r"[A-Za-z]:[\\/][^\s\"'<>|]*"
    r"|\\\\[^\s\"'<>|]+"
    r"|~[\\/][^\s\"'<>|]*"
    r"|(?<![\w.<>~-])/(?:[^\s\"'<>|/]+/)+[^\s\"'<>|/]*")
# Una fecha compacta en el nombre de un archivo (`..._20261020_...`) tiene la
# forma de un PMID para el filtro de publicación; con guiones dice lo mismo y
# deja de parecerlo.
_FECHA_COMPACTA = re.compile(
    r"(?<![0-9])((?:19|20)[0-9]{2})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])"
    r"(?![0-9])")
OMITIDO = "(texto omitido: no se puede publicar)"


def _nada(_m):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------- lo publicable

def _variantes(raices):
    """Las formas en que se escriben las raíces: con `\\` o con `/` (flujo
    guarda las rutas absolutas con `/` también en Windows), la más larga
    primero para que la carpeta gane sobre el repositorio que la contiene."""
    vistas = []
    for raiz in raices:
        for ruta in (os.path.abspath(raiz), os.path.realpath(raiz)):
            for v in (ruta, ruta.replace("\\", "/")):
                if len(v) > 3 and v not in vistas:
                    vistas.append(v)
    return sorted(vistas, key=len, reverse=True)


def _ultimo_tramo(ruta):
    tramos = [t for t in re.split(r"[\\/]+", ruta) if t]
    return u"…/" + tramos[-1] if tramos else u"…"


def _publicable(texto, variantes):
    s = str(texto)
    for v in variantes:
        s = s.replace(v + "\\", "").replace(v + "/", "")
    s = _RUTA_ABSOLUTA.sub(lambda m: _ultimo_tramo(m.group(0)), s)
    s = _FECHA_COMPACTA.sub(r"\1-\2-\3", s)
    try:
        reentrenar.verificar_publicable(s)
    except ValueError:
        return OMITIDO
    return s


def publicable(texto, raices=()):
    """El texto sin nada que no se pueda publicar, o `OMITIDO`.

    Lo de dentro de una raíz conocida (la carpeta, el repositorio) queda
    relativo a ella; cualquier otra ruta absoluta, reducida a su último tramo.
    Si después de eso queda un locus, un marcador de entidad o algo con forma
    de PMID, se omite el texto entero: no se recorta, porque un pedazo de
    oración sigue siendo la oración.
    """
    return _publicable(texto, _variantes(raices))


def _limpio(objeto, variantes):
    """El resultado entero con cada cadena (también las llaves) publicable."""
    if isinstance(objeto, dict):
        return collections.OrderedDict(
            (_publicable(k, variantes), _limpio(v, variantes))
            for k, v in objeto.items())
    if isinstance(objeto, (list, tuple)):
        return [_limpio(v, variantes) for v in objeto]
    if isinstance(objeto, str):
        return _publicable(objeto, variantes)
    return objeto


def _origen_humano(origen):
    """`rutas.de_donde` devuelve identificadores; esto es para leerlos."""
    return {"flag": "flag", "omision": u"omisión"}.get(
        origen, u"la variable GRN_DATOS" if str(origen).startswith("entorno")
        else str(origen))


# ------------------------------------------------------------- lectura

def _leer_json(ruta):
    """(objeto, problema). `problema` es None si se leyó un objeto JSON."""
    nombre = os.path.basename(ruta)
    if not os.path.isfile(ruta):
        return None, "falta %s" % nombre
    try:
        with io.open(ruta, encoding="utf-8") as f:
            objeto = json.load(f)
    except (OSError, ValueError):
        return None, "%s ilegible" % nombre
    if not isinstance(objeto, dict):
        return None, "%s no es un objeto JSON" % nombre
    return objeto, None


def _lineas(ruta):
    """Las líneas con contenido de un JSONL, o None si no está. Se cuentan en
    bytes y sin parsear: `pares.jsonl` pasa de 70 MB."""
    if not os.path.isfile(ruta):
        return None
    n = 0
    with io.open(ruta, "rb") as f:
        for linea in f:
            if linea.strip():
                n += 1
    return n


def _entero(valor):
    """Un conteo leído de un JSON o de un CSV, o None. Un booleano no es un
    conteo aunque Python lo deje sumar."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _leer_candidatas(ruta):
    """(filas, {corrida_id: filas}) del CSV de candidatas del bronce.

    Con el módulo csv y no contando líneas: una oración puede traer saltos de
    línea dentro de su celda.
    """
    corridas = collections.Counter()
    n = 0
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.reader(f)
        encabezado = next(lector, [])
        i = encabezado.index("corrida_id") if "corrida_id" in encabezado \
            else None
        for fila in lector:
            if not fila:
                continue
            n += 1
            if i is not None and i < len(fila):
                corridas[fila[i]] += 1
    return n, corridas


class _Capa(object):
    """Lo que la verificación necesita de `capa_pares.csv`, en una pasada.

    Las que pasan el umbral se guardan por (sección, autorregulación) y no ya
    contadas: así se les aplican después los mismos filtros con que `red.py`
    contó sus supervivientes, sean los que sean.
    """

    COLUMNAS = ("corrida_bronce", "pmid", "fuente_texto", "num_oracion",
                "seccion", "tf_id", "target_id", "autorregulacion",
                "pasa_umbral", "direccion_sintaxis")

    def __init__(self, ruta):
        self.filas = 0
        self.corridas = collections.Counter()
        self.pasan = collections.Counter()
        self.sin_dato = 0
        self.autorregulacion_estricta = 0
        oraciones = set()
        with io.open(ruta, encoding="utf-8-sig", newline="") as f:
            lector = csv.reader(f)
            encabezado = next(lector, [])
            faltan = [c for c in self.COLUMNAS if c not in encabezado]
            if faltan:
                raise ValueError("a capa_pares.csv le faltan columnas: %s"
                                 % ", ".join(faltan))
            i = dict((c, encabezado.index(c)) for c in self.COLUMNAS)
            for fila in lector:
                if not fila:
                    continue
                self.filas += 1
                d = dict((c, fila[i[c]] if i[c] < len(fila) else "")
                         for c in self.COLUMNAS)
                self.corridas[d["corrida_bronce"]] += 1
                oraciones.add((d["pmid"], d["fuente_texto"], d["num_oracion"]))
                if d["pasa_umbral"] == "si":
                    self.pasan[(d["seccion"], d["autorregulacion"] == "si")] \
                        += 1
                if d["direccion_sintaxis"] == "sin_dato":
                    self.sin_dato += 1
                if d["tf_id"] and d["tf_id"] == d["target_id"]:
                    self.autorregulacion_estricta += 1
        self.oraciones = len(oraciones)

    def supervivientes(self, sin_pies, sin_introduccion,
                       incluir_autorregulacion):
        """Las que pasan el umbral con los filtros de `red.filtrar`."""
        n = 0
        for (seccion, auto), cuantas in self.pasan.items():
            if sin_pies and seccion == "pie_de_figura":
                continue
            if sin_introduccion and seccion == "introduction":
                continue
            if auto and not incluir_autorregulacion:
                continue
            n += cuantas
        return n


def _leer_resumen_bronce(ruta):
    """{concepto: valor} del `_resumen.csv` del bronce, o None si no está."""
    if not os.path.isfile(ruta):
        return None
    salida = {}
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for fila in csv.reader(f):
            if len(fila) >= 2:
                salida[fila[0]] = fila[1]
    return salida


class _Huellas(object):
    """Cada archivo se mide una vez: `pares.jsonl` pasa de 70 MB y lo piden
    varias comprobaciones."""

    def __init__(self):
        self._bytes = {}
        self._flujo = {}

    def bytes(self, ruta):
        if ruta not in self._bytes:
            self._bytes[ruta] = procedencia.huella(ruta)
        return self._bytes[ruta]

    def como_flujo(self, ruta):
        """La huella con la regla de `flujo._huella`, para comparar contra
        lo que el flujo registró de fuera de la carpeta."""
        if ruta not in self._flujo:
            absoluta = os.path.abspath(ruta)
            if not os.path.isfile(absoluta):
                self._flujo[ruta] = None
            elif (absoluta.endswith(_TEXTO)
                  and absoluta.startswith(RAIZ + os.sep)
                  and not absoluta.startswith(_SALIDAS)):
                self._flujo[ruta] = procedencia.huella_texto(absoluta)
            else:
                self._flujo[ruta] = self.bytes(ruta)
        return self._flujo[ruta]


def _etiqueta(ruta):
    """El nombre con que un archivo sale en el informe. El CSV del bronce y
    su resumen llevan la fecha de exportación en el nombre, con forma de PMID
    para el filtro de publicación: se nombran por lo que son."""
    nombre = os.path.basename(str(ruta).replace("\\", "/").rstrip("/"))
    if nombre.endswith(SUFIJO_CANDIDATAS):
        return "CSV de candidatas"
    if nombre.startswith("bronce_") and nombre.endswith(SUFIJO_RESUMEN):
        return "resumen del bronce"
    if _FECHA_COMPACTA.search(nombre):
        return "un archivo con fecha en el nombre"
    return nombre


def _resolver(registrada, carpeta, nombre_carpeta):
    """(ruta de hoy, dentro) de un archivo que `estado.json` registró.

    El flujo guarda las rutas relativas a la raíz del repositorio (absolutas
    si caen fuera), así que no sirven tal cual para una carpeta copiada o
    movida. Lo que estaba en la carpeta del flujo se busca en la carpeta que
    se verifica, por nombre; lo demás, contra este repositorio.
    """
    normal = str(registrada).replace("\\", "/")
    padre, _sep, nombre = normal.rpartition("/")
    if padre and padre.rsplit("/", 1)[-1] == nombre_carpeta:
        return os.path.join(carpeta, nombre), True
    if os.path.isabs(registrada) or re.match(r"^[A-Za-z]:/", normal):
        return registrada, False
    return os.path.join(RAIZ, *normal.split("/")), False


# ------------------------------------------------------------- comprobaciones

def _comprobacion(clave, titulo, estatus, valores=(), nota=None):
    return collections.OrderedDict([
        ("clave", clave), ("titulo", titulo), ("estatus", estatus),
        ("valores", [list(v) for v in valores]), ("nota", nota)])


def _unir(*notas):
    return "; ".join(n for n in notas if n) or None


def _iguales(clave, titulo, valores, nota=None):
    """Cumple si todas las fuentes tienen dato y dicen lo mismo."""
    faltan = [fuente for fuente, valor in valores if valor is None]
    distintos = set(valor for _f, valor in valores if valor is not None)
    if faltan:
        return _comprobacion(clave, titulo, FALLA, valores,
                             _unir(nota, "sin dato: %s" % ", ".join(faltan)))
    return _comprobacion(clave, titulo,
                         CUMPLE if len(distintos) <= 1 else FALLA,
                         valores, nota)


def _estatus_de(comprobaciones):
    estatus = [c["estatus"] for c in comprobaciones]
    if FALLA in estatus:
        return FALLA
    if NO_VERIFICABLE in estatus:
        return NO_VERIFICABLE
    if CUMPLE in estatus:
        return CUMPLE
    return NO_APLICA


def _invariante(ident, titulo, comprobaciones, resumen, valor=None):
    return collections.OrderedDict([
        ("id", ident), ("titulo", titulo),
        ("estatus", _estatus_de(comprobaciones)), ("valor", valor),
        ("resumen", resumen), ("comprobaciones", comprobaciones)])


# ------------------------------------------------------------- la base

def _ruta_base(datos):
    """`grn.db` bajo la raíz de datos, con la precedencia de siempre.

    Una raíz relativa que llega por flag es relativa a quien llama; la del
    entorno o la de omisión, al repositorio, como en `flujo._conexion`: los
    pasos del flujo corren desde la raíz, y así se verifica la base que ellos
    abrieron y no otra.
    """
    raiz = rutas.raiz_datos(datos)
    if datos:
        raiz = os.path.abspath(raiz)
    elif not os.path.isabs(raiz):
        raiz = os.path.join(RAIZ, raiz)
    return os.path.join(raiz, "grn.db")


def _de_la_base(con, corrida_id):
    """Todo lo que la verificación le pregunta a la base, en un dict."""
    info = {"fila": bdb.corrida(con, corrida_id)}
    fila = info["fila"]
    info["conteos"] = bdb.conteos_de(con, corrida_id) if fila else None
    info["integridad"] = bdb.integridad_de_corrida(con, corrida_id)
    corpus_id = fila["corpus_id"] if fila else None
    info["corpus"] = None
    info["corpus_bien"] = None
    if corpus_id is not None:
        for c in db0.listar_corpus(con):
            if c["id"] == corpus_id:
                info["corpus"] = dict(c)
        if info["corpus"] is not None:
            info["corpus_bien"] = db0.verificar_corpus(con, corpus_id)
    info["corridas"] = bdb.corridas_por_estatus(con)
    return info


def _i1(info, sin_base):
    titulo = "Normalización a locus tag"
    if sin_base:
        return _invariante("I1", titulo, [_comprobacion(
            "normalizacion", titulo, NO_VERIFICABLE, nota=sin_base)],
            "sin la base no se puede contar")
    c = info["conteos"]
    if c is None:
        return _invariante("I1", titulo, [_comprobacion(
            "normalizacion", titulo, FALLA,
            nota="la corrida no está en la base")], "la corrida no existe")
    k, n = c["genes_normalizados"], c["genes_totales"]
    proporcion = round(float(k) / n, 4) if n else None
    # Se compara la proporción sin redondear: 0.94996 no es 0.95.
    cumple = bool(n) and float(k) / n >= UMBRAL_NORMALIZACION
    comprobacion = _comprobacion(
        "normalizacion",
        "Menciones de gen, proteína u operón con locus tag",
        CUMPLE if cumple else FALLA,
        [["con locus tag", k], ["de gen, proteína u operón", n],
         ["proporción", proporcion], ["umbral", UMBRAL_NORMALIZACION]],
        None if n else "la corrida no tiene menciones de gen")
    resumen = ("%.2f %% con locus tag (umbral %.0f %%)"
               % (100 * proporcion, 100 * UMBRAL_NORMALIZACION)
               if proporcion is not None else "sin menciones de gen")
    return _invariante("I1", titulo, [comprobacion], resumen, proporcion)


def _i2(info, corrida_id, sin_base):
    titulo = "La corrida del bronce"
    if sin_base:
        return _invariante("I2", titulo, [_comprobacion(
            "corrida", titulo, NO_VERIFICABLE, nota=sin_base)],
            "sin la base no se puede comprobar")
    fila = info["fila"]
    comprobaciones = [_comprobacion(
        "existe", "Existe en la base", CUMPLE if fila else FALLA,
        [["corrida", corrida_id]])]
    if fila is not None:
        comprobaciones += [
            _comprobacion("paso", "Es del paso 1",
                          CUMPLE if fila["paso"] == "1" else FALLA,
                          [["paso", fila["paso"]]]),
            _comprobacion("estatus", "Terminó «ok»",
                          CUMPLE if fila["estatus"] == "ok" else FALLA,
                          [["estatus", fila["estatus"]]]),
            _comprobacion("corpus", "Tiene corpus",
                          CUMPLE if fila["corpus_id"] is not None else FALLA,
                          [["corpus_id", fila["corpus_id"]]],
                          None if fila["corpus_id"] is not None else
                          "una corrida sin corpus no es reproducible"),
        ]
    integridad = info["integridad"]
    malas = sum(integridad.values())
    comprobaciones.append(_comprobacion(
        "integridad", "Ninguna fila cuelga de otra corrida ni de nada",
        CUMPLE if malas == 0 else FALLA, sorted(integridad.items())))
    resumen = ("corrida %d: %s" % (
        corrida_id, "paso %s, %s, corpus %s" % (
            fila["paso"], fila["estatus"], fila["corpus_id"])
        if fila else "no está en la base")
        + "; %d filas con problemas de integridad" % malas)
    return _invariante("I2", titulo, comprobaciones, resumen, malas)


def _i5(info, sin_base):
    titulo = "El corpus congelado"
    if sin_base:
        return _invariante("I5", titulo, [_comprobacion(
            "corpus", titulo, NO_VERIFICABLE, nota=sin_base)],
            "sin la base no se puede comprobar")
    fila = info["fila"]
    corpus = info["corpus"]
    if fila is None or fila["corpus_id"] is None:
        return _invariante("I5", titulo, [_comprobacion(
            "corpus", "La corrida tiene corpus", FALLA,
            nota="sin corpus no hay huella que verificar")],
            "la corrida no tiene corpus")
    if corpus is None:
        return _invariante("I5", titulo, [_comprobacion(
            "corpus", "El corpus de la corrida existe", FALLA,
            [["corpus_id", fila["corpus_id"]]])],
            "el corpus %s no está en la base" % fila["corpus_id"])
    hash_ = corpus.get("hash_pmids") or ""
    comprobaciones = [
        _comprobacion("hash", "Tiene huella de sus PMIDs",
                      CUMPLE if hash_ else FALLA, [["huella", hash_ or None]]),
        _comprobacion("huella", "Sigue siendo el que se congeló",
                      CUMPLE if info["corpus_bien"] else FALLA,
                      [["documentos al congelarlo", corpus.get("n_documentos")],
                       ["la huella de hoy coincide", bool(info["corpus_bien"])]],
                      None if info["corpus_bien"] else
                      "verificar_corpus da falso: se quitó o se agregó algún "
                      "documento después de congelarlo"),
    ]
    n_docs = corpus.get("n_documentos")
    resumen = "corpus «%s»: %s documentos, huella %s" % (
        corpus.get("nombre"),
        _miles(n_docs) if isinstance(n_docs, int) else n_docs,
        hash_ or "ninguna")
    return _invariante("I5", titulo, comprobaciones, resumen)


def _horas_desde(iso, ahora):
    try:
        momento = datetime.datetime.fromisoformat(str(iso).replace("Z",
                                                                   "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=datetime.timezone.utc)
    return (ahora - momento).total_seconds() / 3600.0


def _parametros(fila):
    try:
        datos = json.loads(fila.get("parametros") or "{}")
    except (TypeError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _avisos_de_la_base(info, corrida_id):
    avisos = []
    fila = info["fila"]
    if fila is not None:
        cambiados = identificar.recursos_cambiados(
            _parametros(dict(fila)).get("recursos"),
            identificar.huellas_de_recursos())
        if cambiados is None:
            avisos.append(
                "La corrida %d no registró la huella de sus recursos (es "
                "anterior al sellado): no se puede saber si se identificó con "
                "el diccionario y los vocabularios de hoy." % corrida_id)
        elif cambiados:
            avisos.append(
                "Desde la corrida %d cambiaron %s: sus cifras no reflejan los "
                "recursos de hoy." % (corrida_id, ", ".join(cambiados)))
    corridas = info["corridas"]
    ahora = datetime.datetime.now(datetime.timezone.utc)
    zombis = [f["id"] for f in corridas.get("corriendo", [])
              if (_horas_desde(f["iniciada_en"], ahora) or 0) > HORAS_ZOMBI]
    if zombis:
        avisos.append(
            "%d corridas siguen «corriendo» desde hace más de %d h (%s): se "
            "cortaron y nadie las cerró. No cuentan como hechas, pero sus "
            "filas a medias siguen en la base."
            % (len(zombis), HORAS_ZOMBI, ", ".join(str(z) for z in zombis)))
    del_bronce = {}
    for filas in corridas.values():
        for f in filas:
            if f["paso"] == "1":
                del_bronce[f["id"]] = f["estatus"]
    sueltas = []
    for filas in corridas.values():
        for f in filas:
            if f["paso"] != "2":
                continue
            bronce = _entero(_parametros(f).get("corrida_bronce"))
            if del_bronce.get(bronce) in (None, "rehecha"):
                sueltas.append("%s (bronce %s)" % (f["id"], bronce))
    if sueltas:
        avisos.append(
            "Corridas del paso 2 que apuntan a un bronce que no existe o ya "
            "se rehízo: %s." % ", ".join(sueltas))
    return avisos


# ------------------------------------------------------------- la partición

def _run_del_modelo(modelo):
    """El número de run del checkpoint por su nombre (`modelo_limpio_run22`
    → 22), o None si el nombre no lo dice."""
    nombre = os.path.basename(str(modelo or "").replace("\\", "/").rstrip("/"))
    m = re.search(r"run_?([0-9]+)", nombre)
    return int(m.group(1)) if m else None


def _huellas_del_barrido(run):
    """Las huellas de partición que `barrido_resumen.csv` registra para ese
    run, o un conjunto vacío si no hay archivo o no hay fila. Solo se leen
    las columnas `i` y `huella`; la de `datos` trae una ruta de otra máquina."""
    if run is None or not os.path.isfile(BARRIDO_RESUMEN):
        return set()
    huellas = set()
    with io.open(BARRIDO_RESUMEN, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            if _entero(fila.get("i")) == run and (fila.get("huella") or ""):
                huellas.add(fila["huella"].strip())
    return huellas


def _huella_particion(particion):
    """La huella de `etapa2/barrido.huella`, la misma que el barrido
    registró. Se importa aquí y no arriba: `etapa2` no es un paquete."""
    etapa2 = os.path.join(RAIZ, "etapa2")
    if etapa2 not in sys.path:
        sys.path.insert(0, etapa2)
    import barrido
    return barrido.huella(particion)


def _comprobar_vinculo(particion, modelo, avisos):
    """¿Es esta la partición con que se entrenó el checkpoint? Lo sabe
    `barrido_resumen.csv`, si tiene una fila del run; si no, lo afirma el
    flag y se avisa."""
    titulo = "Es la partición con que el barrido entrenó el checkpoint"
    run = _run_del_modelo(modelo)
    registradas = _huellas_del_barrido(run)
    if not registradas:
        avisos.append(VINCULO_PARTICION)
        return _comprobacion(
            "vinculo", titulo, NO_APLICA,
            nota="barrido_resumen.csv no tiene fila del run %s" % run
            if run is not None else
            "el nombre del modelo no dice de qué run es")
    hoy = _huella_particion(particion)
    return _comprobacion(
        "vinculo", titulo, CUMPLE if hoy in registradas else FALLA,
        [["huella de la partición", hoy],
         ["huella del run %d en barrido_resumen.csv" % run,
          " y ".join(sorted(registradas))]],
        None if hoy in registradas else
        "la partición no es la del run %d: I3 no dice nada del modelo" % run)


def _i3(particion, modelo, avisos, log):
    titulo = "La partición, sin fuga hacia train"
    if not particion:
        return _invariante("I3", titulo, [_comprobacion(
            "particion", titulo, NO_APLICA, nota="sin --particion")],
            "no se pidió")
    archivos = dict((n, os.path.join(particion, "entity_marked_%s.jsonl" % n))
                    for n in ("train", "dev", "test"))
    faltan = [n for n, r in sorted(archivos.items()) if not os.path.isfile(r)]
    if faltan:
        avisos.append(VINCULO_PARTICION)
        return _invariante("I3", titulo, [_comprobacion(
            "archivos", "Los tres archivos de la partición", NO_VERIFICABLE,
            nota="faltan: %s" % ", ".join(
                "entity_marked_%s.jsonl" % n for n in faltan))],
            "no se encuentra la partición")
    try:
        vinculo = _comprobar_vinculo(particion, modelo, avisos)
    except OSError:
        vinculo = _comprobacion(
            "vinculo", "Es la partición con que el barrido entrenó el "
            "checkpoint", NO_VERIFICABLE, nota="no se pudo leer la partición")
    log("Leyendo la partición (solo se cuenta; nada de su contenido sale).")
    try:
        conteo, pmids_tr, textos_tr = _leer_parte(archivos["train"])
        fuga = {}
        for nombre in ("dev", "test"):
            fuga[nombre] = _contar_fuga(archivos[nombre], pmids_tr, textos_tr)
    except ValueError as e:
        return _invariante("I3", titulo, [_comprobacion(
            "archivos", "Los tres archivos de la partición", NO_VERIFICABLE,
            nota=str(e))], "partición ilegible")
    tamanos = [["train", conteo], ["dev", fuga["dev"]["n"]],
               ["test", fuga["test"]["n"]]]
    vacias = [n for n, v in tamanos if not v]
    comprobaciones = [
        # Contra una parte vacía, toda pertenencia da falso y la partición se
        # declaraba limpia (el defecto de `particionar.py --folds 2`).
        _comprobacion("partes", "Ninguna parte vacía",
                      FALLA if vacias else CUMPLE, tamanos,
                      "vacías: %s" % ", ".join(vacias) if vacias else None),
        _comprobacion(
            "pmids", "Ningún PMID de dev o de test en train",
            CUMPLE if not (fuga["dev"]["pmids"] or fuga["test"]["pmids"])
            else FALLA,
            [["PMIDs de dev en train", fuga["dev"]["pmids"]],
             ["PMIDs de test en train", fuga["test"]["pmids"]]]),
        _comprobacion(
            "textos", "Ningún texto canónico de dev o de test en train",
            CUMPLE if not (fuga["dev"]["textos"] or fuga["test"]["textos"])
            else FALLA,
            [["ejemplos de dev con su texto en train", fuga["dev"]["textos"]],
             ["ejemplos de test con su texto en train",
              fuga["test"]["textos"]]],
            "texto canónico de entrenamiento.canonico, el mismo con que "
            "particionar.py verifica: sin marcadores, minúsculas y sin "
            "puntuación"),
        vinculo,
    ]
    total = sum(fuga[n][k] for n in fuga for k in ("pmids", "textos"))
    resumen = ("%s PMIDs y %s textos de dev o test en train"
               % (_miles(fuga["dev"]["pmids"] + fuga["test"]["pmids"]),
                  _miles(fuga["dev"]["textos"] + fuga["test"]["textos"])))
    return _invariante("I3", titulo, comprobaciones, resumen, total)


def _ejemplos(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        for numero, linea in enumerate(f, 1):
            if not linea.strip():
                continue
            try:
                e = json.loads(linea)
            except ValueError:
                # El número de línea y no la línea: es contenido de la base.
                raise ValueError("%s, línea %d ilegible"
                                 % (os.path.basename(ruta), numero))
            if not isinstance(e, dict) or not isinstance(e.get("text"), str) \
                    or e.get("pmid") in (None, ""):
                raise ValueError("%s, línea %d sin text o sin pmid"
                                 % (os.path.basename(ruta), numero))
            yield str(e["pmid"]).strip(), entrenamiento.canonico(e["text"])


def _leer_parte(ruta):
    n, pmids, textos = 0, set(), set()
    for pmid, texto in _ejemplos(ruta):
        n += 1
        pmids.add(pmid)
        textos.add(texto)
    return n, pmids, textos


def _contar_fuga(ruta, pmids_tr, textos_tr):
    n, pmids, textos = 0, set(), 0
    for pmid, texto in _ejemplos(ruta):
        n += 1
        if pmid in pmids_tr:
            pmids.add(pmid)
        if texto in textos_tr:
            textos += 1
    return {"n": n, "pmids": len(pmids), "textos": textos}


# ------------------------------------------------------------- la cadena

def _verdad(valor):
    """Los booleanos de `red_informe.json` llegan como "true"/"false"."""
    return valor is True or str(valor).strip().lower() == "true"


def _mismos_umbrales(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict) or set(a) != set(b):
        return False
    try:
        return all(abs(float(a[k]) - float(b[k])) < 1e-9 for k in a)
    except (TypeError, ValueError):
        return False


def _comprobar_pasos(estado, avisos):
    pasos = estado["pasos"]
    con_limite = bool(estado.get("limite"))
    orden = list(PASOS_EXIGIDOS) + sorted(
        str(p) for p in pasos if p not in PASOS_EXIGIDOS)
    valores, malos = [], []
    for paso in orden:
        registro = pasos.get(paso)
        estatus = (registro.get("estatus") if isinstance(registro, dict)
                   else None) or "pendiente"
        valores.append([paso, estatus])
        if estatus in ("error", "cancelado"):
            malos.append(paso)
        elif paso in PASOS_EXIGIDOS and estatus not in ESTATUS_HECHO and not (
                estatus == "omitido" and con_limite
                and paso in OMITIBLE_CON_LIMITE):
            malos.append(paso)
        elif estatus == "omitido":
            nota = registro.get("nota") if isinstance(registro, dict) else ""
            nota = nota.splitlines()[0] if isinstance(nota, str) and \
                nota.strip() else ""
            avisos.append("El paso «%s» quedó omitido%s." % (
                paso, " (%s)" % nota.rstrip(".") if nota else ""))
    return _comprobacion(
        "pasos", "Ningún paso en error y los exigidos hechos",
        FALLA if malos else CUMPLE, valores,
        "en error, cancelados o sin hacer: %s" % ", ".join(malos)
        if malos else None)


def _comprobar_registradas(estado, carpeta, huellas, avisos):
    """Las salidas y las entradas de cada paso hecho contra los archivos.

    En la carpeta, toda diferencia es un eslabón roto: una salida que cambió
    después de registrarse, o un paso que se hizo con otra versión de un
    archivo de otro paso (`--pasos pares` rehace los pares y deja la capa
    como estaba). Fuera de la carpeta (el código, los recursos), que una
    entrada cambie solo quiere decir que el flujo rehará ese paso: se avisa.
    """
    nombre = estado.get("carpeta") or os.path.basename(carpeta)
    salidas = {"comprobadas": 0, "problemas": []}
    entradas = {"comprobadas": 0, "problemas": []}
    salidas_fuera_sin_copia = []
    entradas_fuera = collections.Counter()
    for paso, registro in sorted(estado["pasos"].items()):
        if not isinstance(registro, dict) or \
                registro.get("estatus") not in ESTATUS_HECHO:
            continue
        for tipo, cuenta in (("salidas", salidas), ("entradas", entradas)):
            registradas = registro.get(tipo)
            if not isinstance(registradas, dict):
                continue
            for archivo, esperada in sorted(registradas.items()):
                ruta, dentro = _resolver(archivo, carpeta, nombre)
                if dentro:
                    # Todo lo de la carpeta es generado: el flujo lo mide por
                    # bytes, esté donde esté la carpeta.
                    hoy = huellas.bytes(ruta)
                    cuenta["comprobadas"] += 1
                    if hoy != esperada:
                        cuenta["problemas"].append(
                            ["%s: %s" % (paso, _etiqueta(ruta)),
                             esperada, hoy or "falta"])
                    continue
                if not os.path.isfile(ruta):
                    if esperada is None:
                        continue
                    if tipo == "salidas":
                        salidas_fuera_sin_copia.append(_etiqueta(ruta))
                    else:
                        entradas_fuera[paso] += 1
                    continue
                if esperada == huellas.como_flujo(ruta):
                    if tipo == "salidas":
                        cuenta["comprobadas"] += 1
                    continue
                if tipo == "salidas":
                    cuenta["comprobadas"] += 1
                    cuenta["problemas"].append(
                        ["%s: %s" % (paso, _etiqueta(ruta)),
                         esperada, huellas.como_flujo(ruta)])
                else:
                    entradas_fuera[paso] += 1
    if salidas_fuera_sin_copia:
        avisos.append(
            "Salidas de fuera de la carpeta que no están en esta copia del "
            "repositorio, sin comprobar: %s."
            % ", ".join(sorted(set(salidas_fuera_sin_copia))))
    if entradas_fuera:
        avisos.append(
            "Desde que corrieron, cambiaron entradas de fuera de la carpeta "
            "(código o recursos) en: %s. El flujo rehará esos pasos la "
            "próxima vez; las cifras de esta carpeta son las de entonces."
            % ", ".join("%s (%d)" % (p, n)
                        for p, n in sorted(entradas_fuera.items())))
    return [
        _comprobacion("salidas", "Las salidas registradas en estado.json "
                      "son los archivos de hoy",
                      FALLA if salidas["problemas"] else CUMPLE,
                      salidas["problemas"] or [["comprobadas",
                                                salidas["comprobadas"]]],
                      "%d comprobadas" % salidas["comprobadas"]),
        _comprobacion("entradas", "Cada paso se hizo con los archivos de "
                      "la carpeta que hay hoy",
                      FALLA if entradas["problemas"] else CUMPLE,
                      entradas["problemas"] or [["comprobadas",
                                                 entradas["comprobadas"]]],
                      "%d comprobadas" % entradas["comprobadas"]),
    ]


def _huella_contra(nombre, esperada, hoy):
    return [nombre, esperada, hoy]


def _comprobar_huellas(clave, titulo, filas, nota=None):
    """`filas`: [(nombre, sellada, de hoy)]. Sin nada sellado no se puede
    comprobar; una diferencia es una cadena rota."""
    if not filas:
        return _comprobacion(clave, titulo, NO_VERIFICABLE,
                             nota=_unir(nota, "no hay huellas selladas"))
    if any(sellada != hoy for _n, sellada, hoy in filas):
        return _comprobacion(clave, titulo, FALLA, filas, nota)
    return _comprobacion(clave, titulo, CUMPLE, filas, nota)


def _cadena(carpeta, estado, conteos, avisos, log):
    """I4 y lo que el embudo necesita de los archivos."""
    def ruta(nombre):
        return os.path.join(carpeta, nombre)

    huellas = _Huellas()
    corrida = estado["corrida_bronce"]
    comprobaciones = [_comprobar_pasos(estado, avisos)]
    log("Comprobando las huellas de lo que registró estado.json...")
    comprobaciones += _comprobar_registradas(estado, carpeta, huellas, avisos)

    nombre_cand = (estado.get("archivos") or {}).get("candidatas")
    ruta_cand = None
    if nombre_cand and os.path.basename(nombre_cand) == nombre_cand:
        ruta_cand = ruta(nombre_cand)
    filas_cand = corridas_cand = None
    if ruta_cand and os.path.isfile(ruta_cand):
        log("Contando el CSV de candidatas...")
        filas_cand, corridas_cand = _leer_candidatas(ruta_cand)
    pi, p_pi = _leer_json(ruta(PARES_INFORME))
    meta, p_meta = _leer_json(ruta(PREDICCIONES_META))
    red, p_red = _leer_json(ruta(RED_INFORME))
    cr, p_cr = _leer_json(ruta(CAPA_RESUMEN))
    pi, meta, red, cr = pi or {}, meta or {}, red or {}, cr or {}
    capa, p_capa = None, None
    if os.path.isfile(ruta(CAPA)):
        log("Contando capa_pares.csv...")
        try:
            capa = _Capa(ruta(CAPA))
        except ValueError as e:
            p_capa = str(e)
    else:
        p_capa = "falta %s" % CAPA
    faltan = [p for p in (p_pi, p_meta, p_red, p_cr, p_capa) if p]
    if ruta_cand is None or filas_cand is None:
        faltan.insert(0, "falta el CSV de candidatas")
    log("Contando pares.jsonl y predicciones.jsonl...")
    n_pares = _lineas(ruta(PARES))
    n_pred = _lineas(ruta(PREDICCIONES))

    # La corrida que dicen los archivos es la de estado.json.
    esperada = str(corrida)
    valores = [["estado.json", esperada]]
    if corridas_cand is not None:
        valores.append(["CSV de candidatas",
                        " y ".join(sorted(corridas_cand)) or None])
    if capa is not None:
        valores.append(["capa_pares.csv",
                        " y ".join(sorted(capa.corridas)) or None])
    otras = [v for _f, v in valores[1:] if v != esperada and v is not None]
    comprobaciones.append(_comprobacion(
        "corrida", "Los archivos son de la corrida de estado.json",
        FALLA if otras or len(valores) < 3 else CUMPLE, valores,
        None if len(valores) == 3 else "falta el CSV de candidatas o la capa"))

    sin_conteos = None if conteos is not None else \
        "sin la base no se compara con conteos_de"
    limite = _entero(pi.get("limite"))
    valores = [["filas del CSV de candidatas", filas_cand]]
    if conteos is not None:
        valores.append(["conteos_de: candidatas", conteos["candidatas"]])
    leidas = _entero(pi.get("oraciones_leidas"))
    if limite is None:
        valores.append(["pares_informe: oraciones_leidas", leidas])
        comprobaciones.append(_iguales("candidatas", "Oraciones candidatas",
                                       valores, sin_conteos))
    else:
        comprobaciones.append(_iguales("candidatas", "Oraciones candidatas",
                                       valores, sin_conteos))
        comprobaciones.append(_iguales(
            "oraciones_leidas", "Oraciones que leyó el puente, con --limite",
            [["las primeras %d del CSV" % limite,
              None if filas_cand is None else min(filas_cand, limite)],
             ["pares_informe: oraciones_leidas", leidas]]))

    comprobaciones.append(_iguales(
        "oraciones_con_par", "Oraciones con algún par",
        [["pares_informe: oraciones_con_par",
          _entero(pi.get("oraciones_con_par"))],
         ["capa_resumen: oraciones", _entero(cr.get("oraciones"))],
         ["oraciones distintas en capa_pares.csv",
          capa.oraciones if capa else None]]))

    comprobaciones.append(_iguales(
        "pares", "Pares, del puente a la red",
        [["líneas de pares.jsonl", n_pares],
         ["pares_informe: pares", _entero(pi.get("pares"))],
         ["capa_resumen: filas", _entero(cr.get("filas"))],
         ["filas de capa_pares.csv", capa.filas if capa else None],
         ["predicciones_meta: n_entrada", _entero(meta.get("n_entrada"))],
         ["predicciones_meta: n_salida", _entero(meta.get("n_salida"))],
         ["líneas de predicciones.jsonl", n_pred],
         ["red_informe: n_predicciones", _entero(red.get("n_predicciones"))]]))

    titulo = "Pasan el umbral sin autorregulación"
    if not (cr and red):
        comprobaciones.append(_comprobacion(
            "supervivientes", titulo, NO_APLICA,
            nota="falta capa_resumen.json o red_informe.json"))
    elif not _mismos_umbrales(cr.get("umbrales"), red.get("umbrales")):
        comprobaciones.append(_comprobacion(
            "supervivientes", titulo, NO_APLICA,
            nota="los umbrales de la capa y los de la red no coinciden"))
        avisos.append("Los umbrales de la capa y los de la red no coinciden: "
                      "no se comparan las que pasan el umbral con "
                      "n_supervivientes.")
    else:
        filtros = ("sin_pies", "sin_introduccion", "incluir_autorregulacion")
        activos = [f for f in filtros if _verdad(red.get(f))]
        comprobaciones.append(_iguales(
            "supervivientes", titulo,
            [["filas de la capa que pasan el umbral, con los filtros de la "
              "red", capa.supervivientes(*[_verdad(red.get(f))
                                           for f in filtros])
              if capa else None],
             ["red_informe: n_supervivientes",
              _entero(red.get("n_supervivientes"))]],
            "filtros de la red: %s" % (", ".join(activos) or "ninguno")))

    titulo = "Pares sin dato de sintaxis = autorregulación estricta"
    sintaxis = cr.get("sintaxis") if isinstance(cr.get("sintaxis"), dict) \
        else {}
    if not sintaxis.get("presente"):
        comprobaciones.append(_comprobacion(
            "sin_dato_sintaxis", titulo, NO_APLICA,
            nota="la capa se armó sin sintaxis" if cr
            else "falta capa_resumen.json"))
    else:
        descartes = pi.get("descartes_de_extraer_pares")
        # Un Counter volcado a JSON no trae las llaves en cero.
        antes_del_tope = (_entero(descartes.get(
            "pares_autorregulacion_antes_del_tope", 0))
            if isinstance(descartes, dict) else None)
        direccion = sintaxis.get("direccion")
        comprobaciones.append(_iguales(
            "sin_dato_sintaxis", titulo,
            [["filas de la capa con direccion_sintaxis = sin_dato",
              capa.sin_dato if capa else None],
             ["capa_resumen: sintaxis sin_dato",
              _entero(direccion.get("sin_dato", 0))
              if isinstance(direccion, dict) else None],
             ["filas de la capa con tf_id = target_id",
              capa.autorregulacion_estricta if capa else None],
             ["pares_informe: autorregulación antes del tope",
              antes_del_tope]],
            "la sintaxis trae una fila por par de entidades distintas; solo "
            "le faltan los pares de una entidad consigo misma"))

    log("Comprobando las huellas selladas...")
    sello = red.get("huellas") if isinstance(red.get("huellas"), dict) else {}
    rutas_red = {"pares": ruta(PARES), "predicciones": ruta(PREDICCIONES),
                 "red": ruta(RED)}
    if not sello:
        comprobaciones.append(_comprobacion(
            "huellas_red", "La red se hizo con estos pares y predicciones",
            NO_VERIFICABLE, nota="red_informe.json no trae huellas"))
    else:
        # Los mensajes de `procedencia.verificar` traen rutas y tamaños en
        # bytes: no se publican. Se dice solo qué archivo no coincide.
        problemas, sin_sellar = procedencia.verificar(sello, rutas_red)
        filas = [_huella_contra(n, (sello.get(n) or {}).get("huella"),
                                huellas.bytes(rutas_red[n]))
                 for n in sorted(rutas_red) if n not in sin_sellar]
        distintos = [f[0] for f in filas if f[1] != f[2]]
        estatus = FALLA if problemas else (
            NO_VERIFICABLE if sin_sellar else CUMPLE)
        comprobaciones.append(_comprobacion(
            "huellas_red", "La red se hizo con estos pares y predicciones",
            estatus, filas,
            _unir("no coinciden: %s" % ", ".join(distintos)
                  if problemas and distintos else None,
                  "sin sellar: %s" % ", ".join(sorted(sin_sellar))
                  if sin_sellar else None)))

    filas = []
    if meta:
        filas.append(_huella_contra("predicciones_meta: huella_pares",
                                    meta.get("huella_pares"),
                                    huellas.bytes(ruta(PARES))))
        if "huella_predicciones" in meta:
            filas.append(_huella_contra(
                "predicciones_meta: huella_predicciones",
                meta.get("huella_predicciones"),
                huellas.bytes(ruta(PREDICCIONES))))
    comprobaciones.append(_comprobar_huellas(
        "huellas_predicciones",
        "Las predicciones son de este pares.jsonl", filas,
        p_meta))

    sellado = pi.get("huellas") if isinstance(pi.get("huellas"), dict) else {}
    filas = []
    if sellado:
        filas = [_huella_contra("pares_informe: candidatas",
                                sellado.get("candidatas"),
                                huellas.bytes(ruta_cand) if ruta_cand
                                else None),
                 _huella_contra("pares_informe: pares", sellado.get("pares"),
                                huellas.bytes(ruta(PARES)))]
    comprobaciones.append(_comprobar_huellas(
        "huellas_puente", "Los pares salieron de este CSV de candidatas",
        filas, p_pi))

    if sintaxis.get("presente"):
        comprobaciones.append(_comprobar_huellas(
            "huella_sintaxis", "La capa se armó con este sintaxis.jsonl",
            [_huella_contra("capa_resumen: huella_sintaxis",
                            sintaxis.get("huella_sintaxis"),
                            huellas.bytes(ruta(SINTAXIS)))]
            if "huella_sintaxis" in sintaxis else []))

    comprobaciones.append(_comprobar_resumen_bronce(ruta_cand, conteos))

    fallan = sum(1 for c in comprobaciones if c["estatus"] == FALLA)
    aplican = sum(1 for c in comprobaciones if c["estatus"] != NO_APLICA)
    cumplen = sum(1 for c in comprobaciones if c["estatus"] == CUMPLE)
    resumen = "%d de %d comprobaciones cumplen" % (cumplen, aplican)
    if faltan:
        resumen += "; %s" % ", ".join(faltan)
    invariante = _invariante("I4", "La cadena de conteos y huellas",
                             comprobaciones, resumen, fallan)
    leido = {"filas_candidatas": filas_cand, "pares_informe": pi,
             "red_informe": red, "limite": limite}
    return invariante, leido


def _comprobar_resumen_bronce(ruta_cand, conteos):
    titulo = "El resumen del bronce dice lo que dice la base"
    if conteos is None:
        return _comprobacion("resumen_bronce", titulo, NO_APLICA,
                             nota="sin la base no hay contra qué comparar")
    if not ruta_cand or not ruta_cand.endswith(SUFIJO_CANDIDATAS):
        return _comprobacion("resumen_bronce", titulo, NO_APLICA,
                             nota="no hay CSV de candidatas")
    resumen = _leer_resumen_bronce(
        ruta_cand[:-len(SUFIJO_CANDIDATAS)] + SUFIJO_RESUMEN)
    if resumen is None:
        return _comprobacion("resumen_bronce", titulo, NO_APLICA,
                             nota="no está el _resumen.csv del bronce")
    valores = []
    distintos = []
    for concepto, clave in RESUMEN_BRONCE:
        dice = _entero(resumen.get(concepto))
        valores.append([concepto, dice, conteos[clave]])
        if dice != conteos[clave]:
            distintos.append(concepto)
    return _comprobacion(
        "resumen_bronce", titulo, FALLA if distintos else CUMPLE, valores,
        "cada fila: lo que dice el resumen y lo que cuenta la base hoy")


# ------------------------------------------------------------- lo demás

def _embudo(conteos, leido):
    pi, red = leido["pares_informe"], leido["red_informe"]

    def de(d, clave):
        return _entero(d.get(clave)) if d else None
    etapas = [
        ("documentos", "Documentos con texto",
         conteos["documentos"] if conteos else None),
        ("oraciones", "Oraciones (unidades de texto)",
         conteos["unidades"] if conteos else None),
        ("candidatas", "Oraciones candidatas",
         conteos["candidatas"] if conteos else leido["filas_candidatas"]),
        ("oraciones_con_par", "Oraciones con algún par",
         de(pi, "oraciones_con_par")),
        ("pares", "Pares que vio BioBERT", de(pi, "pares")),
        ("pasan_umbral", "Pasan el umbral, sin autorregulación",
         de(red, "n_supervivientes")),
        ("aristas", "Aristas de la red", de(red, "n_aristas")),
    ]
    return [collections.OrderedDict([("clave", c), ("titulo", t), ("n", n)])
            for c, t, n in etapas]


def _es_proporcion(d):
    return isinstance(d, dict) and all(k in d for k in ("k", "n", "valor",
                                                        "ic95"))


def _metricas(evaluacion):
    """Toda proporción con su IC de Wilson que traiga `evaluacion.json`."""
    salida = []

    def recorrer(nombre, objeto):
        if _es_proporcion(objeto):
            salida.append(collections.OrderedDict([
                ("nombre", nombre), ("k", objeto["k"]), ("n", objeto["n"]),
                ("valor", objeto["valor"]), ("ic95", objeto["ic95"])]))
            return
        if isinstance(objeto, dict):
            for clave in objeto:
                recorrer(u"%s › %s" % (nombre, clave) if nombre else clave,
                         objeto[clave])

    claves = [c for c in ORDEN_METRICAS if c in evaluacion]
    claves += sorted(c for c in evaluacion if c not in ORDEN_METRICAS)
    for clave in claves:
        recorrer(clave, evaluacion[clave])
    return salida


def _wilson_no_cuadra(metrica):
    """True si el valor o el IC no son los de `evaluar.proporcion(k, n)`."""
    k, n = _entero(metrica["k"]), _entero(metrica["n"])
    if k is None or n is None:
        return True
    esperado = evaluar.proporcion(k, n)
    if esperado["valor"] is None:
        return metrica["valor"] is not None
    try:
        return (abs(float(metrica["valor"]) - esperado["valor"])
                > TOLERANCIA_WILSON
                or any(abs(float(a) - b) > TOLERANCIA_WILSON
                       for a, b in zip(metrica["ic95"], esperado["ic95"]))
                or len(metrica["ic95"]) != 2)
    except (TypeError, ValueError):
        return True


def _evaluacion(carpeta, avisos):
    datos, problema = _leer_json(os.path.join(carpeta, EVALUACION))
    if problema:
        avisos.append("Sin métricas de evaluación: %s." % problema)
        return None, []
    metricas = _metricas(datos)
    malas = [m["nombre"] for m in metricas if _wilson_no_cuadra(m)]
    if malas:
        avisos.append("El IC de Wilson no cuadra con su k y su n en: %s."
                      % ", ".join(malas))
    notas = datos.get("notas") if isinstance(datos.get("notas"), list) \
        else []
    muestra = datos.get("muestra") if isinstance(datos.get("muestra"), dict) \
        else None
    return collections.OrderedDict([("muestra", muestra),
                                    ("notas", [str(n) for n in notas])]), \
        metricas


def _comparar(actual, previo):
    """Qué cambió contra otra verificación: invariantes, embudo, métricas.

    El otro archivo llega de fuera y puede ser de otra versión, o no ser de
    esta herramienta: de él solo se toman cadenas y números, y lo demás cuenta
    como «sin dato».
    """
    def por(lista, llave):
        if not isinstance(lista, list):
            return {}
        return collections.OrderedDict(
            (d[llave], d) for d in lista
            if isinstance(d, dict) and isinstance(d.get(llave), str))

    def escalar(valor):
        valor = _numero(valor)
        if isinstance(valor, (str, int, float)) or valor is None:
            return valor
        return None

    def resta(a, b):
        if isinstance(a, bool) or isinstance(b, bool):
            return None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(b - a, 4)
        return None

    antes_inv = por(previo.get("invariantes"), "id")
    invariantes = []
    for inv in actual["invariantes"]:
        previa = antes_inv.get(inv["id"], {})
        antes = previa.get("estatus") if previa.get("estatus") in ETIQUETAS \
            else None
        valor_antes = escalar(previa.get("valor"))
        invariantes.append(collections.OrderedDict([
            ("id", inv["id"]), ("antes", antes), ("ahora", inv["estatus"]),
            ("valor_antes", valor_antes), ("valor_ahora", inv["valor"]),
            ("cambia", antes != inv["estatus"]
             or valor_antes != inv["valor"])]))
    antes_emb = por(previo.get("embudo"), "clave")
    embudo = []
    for etapa in actual["embudo"]:
        a = escalar(antes_emb.get(etapa["clave"], {}).get("n"))
        embudo.append(collections.OrderedDict([
            ("clave", etapa["clave"]), ("titulo", etapa["titulo"]),
            ("antes", a), ("ahora", etapa["n"]),
            ("diferencia", resta(a, etapa["n"]))]))
    antes_met = por(previo.get("metricas"), "nombre")
    ahora_met = por(actual["metricas"], "nombre")
    nombres = list(ahora_met) + [n for n in antes_met if n not in ahora_met]
    metricas = []
    for nombre in nombres:
        a = escalar(antes_met.get(nombre, {}).get("valor"))
        b = ahora_met.get(nombre, {}).get("valor")
        metricas.append(collections.OrderedDict([
            ("nombre", nombre), ("antes", a), ("ahora", b),
            ("diferencia", resta(a, b))]))
    return collections.OrderedDict([
        ("verificado_en", escalar(previo.get("verificado_en"))),
        ("carpeta", escalar(previo.get("carpeta"))),
        ("corrida_bronce", escalar(previo.get("corrida_bronce"))),
        ("codigo_antes", escalar(previo.get("codigo"))),
        ("codigo_ahora", actual["codigo"]),
        ("invariantes", invariantes), ("embudo", embudo),
        ("metricas", metricas)])


def _codigo(invariantes):
    estatus = [i["estatus"] for i in invariantes]
    if FALLA in estatus:
        return 1
    if NO_VERIFICABLE in estatus:
        return 2
    return 0


# ------------------------------------------------------------- escribir

def _escribir(ruta, texto):
    """Escritura atómica: un informe a medias no se confunde con uno entero."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    reemplazar(tmp, ruta)


def _miles(n):
    """«72 969»: miles con espacio, como en el resto del proyecto. No es solo
    estilo: un conteo de siete u ocho cifras pegadas tiene la forma de un
    PMID, y el filtro de publicación lo rechaza con razón."""
    return u"{:,}".format(n).replace(",", " ")


_MILES = re.compile(r"^-?[0-9]{1,3}(?: [0-9]{3})+$")


def _numero(valor):
    """Lo inverso de `_miles` para lo que llega de otro informe; lo demás,
    tal cual."""
    if isinstance(valor, str) and _MILES.match(valor):
        return int(valor.replace(" ", ""))
    return valor


def _espaciado(objeto):
    """El resultado con cada entero de cuatro cifras o más escrito con
    `_miles`. Se aplica al escribir: en memoria los conteos siguen siendo
    números, para compararlos y dibujar el embudo."""
    if isinstance(objeto, dict):
        return collections.OrderedDict(
            (k, _espaciado(v)) for k, v in objeto.items())
    if isinstance(objeto, (list, tuple)):
        return [_espaciado(v) for v in objeto]
    if isinstance(objeto, int) and not isinstance(objeto, bool) and \
            abs(objeto) >= 1000:
        return _miles(objeto)
    return objeto


def _texto_json(resultado):
    return json.dumps(_espaciado(resultado), ensure_ascii=False,
                      indent=2) + "\n"


def _no_publicable(texto):
    """El motivo por el que no se puede publicar, o None. Dice el patrón y
    la línea, nunca el texto."""
    try:
        reentrenar.verificar_publicable(texto)
    except ValueError as e:
        return str(e)
    return None


# ------------------------------------------------------------- ejecutar

def ejecutar(carpeta, datos=None, particion=None, contra=None,
             salida_json=None, salida_html=None, log=_nada):
    """Verifica la carpeta y devuelve el resultado, con su `codigo`.

    `datos` es la raíz de datos (flag > `GRN_DATOS` > `./datos`), y de ahí
    sale `grn.db`. `particion` es la carpeta con los `entity_marked_*.jsonl`
    con que se entrenó el checkpoint de la corrida; `contra`, otro
    `verificacion.json` contra el que comparar.
    """
    carpeta = os.path.abspath(carpeta)
    nombre = os.path.basename(carpeta)
    variantes = _variantes([carpeta, RAIZ])
    log("Verificando la carpeta %s..." % _publicable(nombre, variantes))
    motivo = None
    estado = None
    if not os.path.isdir(carpeta):
        motivo = "no existe la carpeta %s" % nombre
    elif os.path.exists(os.path.join(carpeta, CANDADO)):
        motivo = ("hay un %s en la carpeta: una corrida del flujo la está "
                  "usando, o se cortó de golpe y dejó el candado. Si no hay "
                  "ninguna viva, bórralo y vuelve a verificar." % CANDADO)
    else:
        estado, motivo = _leer_json(os.path.join(carpeta, "estado.json"))
        if estado is not None:
            if not isinstance(estado.get("pasos"), dict):
                motivo = "estado.json no trae los pasos"
            elif _entero(estado.get("corrida_bronce")) is None:
                motivo = "estado.json no dice de qué corrida del bronce es"
    if motivo:
        motivo = _publicable(motivo, variantes)
        log("No se puede verificar: %s." % motivo.rstrip("."))
        return collections.OrderedDict([
            ("codigo", 2), ("veredicto", NO_VERIFICABLE),
            ("carpeta", _publicable(nombre, variantes)), ("motivo", motivo)])

    corrida = _entero(estado["corrida_bronce"])
    estado["corrida_bronce"] = corrida
    avisos = []
    if estado.get("limite"):
        avisos.append("Es una prueba con --limite %s: el embudo y los conteos "
                      "no son los del corpus." % estado.get("limite"))

    log("Abriendo la base en solo lectura (por %s)..."
        % _origen_humano(rutas.de_donde(datos)))
    info, sin_base = None, None
    try:
        con = bdb.conectar_lectura(_ruta_base(datos))
    except bdb.ErrorBase as e:
        con = None
        sin_base = "no se pudo abrir la base en solo lectura (%s)" % e
    if con is not None:
        try:
            info = _de_la_base(con, corrida)
            avisos += _avisos_de_la_base(info, corrida)
        except bdb.ErrorBase as e:
            sin_base = "la base no contesta lo que se le pregunta (%s)" % e
            info = None
        finally:
            con.close()
    conteos = info["conteos"] if info else None

    invariantes = [_i1(info, sin_base), _i2(info, corrida, sin_base),
                   _i3(particion, estado.get("modelo"), avisos, log)]
    cadena, leido = _cadena(carpeta, estado, conteos, avisos, log)
    invariantes.append(cadena)
    invariantes.append(_i5(info, sin_base))
    log("Leyendo la evaluación...")
    evaluacion, metricas = _evaluacion(carpeta, avisos)

    codigo = _codigo(invariantes)
    corpus = info["corpus"] if info else None
    resultado = collections.OrderedDict([
        ("informe", "verificacion de una carpeta del flujo"),
        ("version", VERSION_INFORME),
        ("verificado_en", _ahora()),
        ("codigo", codigo),
        ("veredicto", VEREDICTOS[codigo]),
        ("carpeta", nombre),
        ("corrida_bronce", corrida),
        ("modelo", os.path.basename(str(estado.get("modelo") or ""))
         .strip() or None),
        ("limite", estado.get("limite")),
        ("base", collections.OrderedDict([
            ("origen", rutas.de_donde(datos)), ("abierta", sin_base is None),
            ("solo_lectura", True)])),
        ("corpus", collections.OrderedDict([
            ("nombre", corpus.get("nombre")),
            ("n_documentos", corpus.get("n_documentos")),
            ("huella", corpus.get("hash_pmids"))]) if corpus else None),
        ("invariantes", invariantes),
        ("avisos", avisos),
        ("embudo", _embudo(conteos, leido)),
        ("evaluacion", evaluacion),
        ("metricas", metricas),
        ("contra", None),
        ("publicable", True),
    ])
    if contra:
        previo, problema = _leer_json(os.path.abspath(contra))
        if problema:
            avisos.append("No se compara con --contra: %s." % problema)
        else:
            resultado["contra"] = _comparar(resultado, previo)
            resultado["contra"]["archivo"] = os.path.basename(contra)

    resultado = _limpio(resultado, variantes)
    texto_json = _texto_json(resultado)
    texto_html = html_informe(resultado) if salida_html else None
    motivos = [m for m in (_no_publicable(texto_json),
                           texto_html and _no_publicable(texto_html)) if m]
    if motivos:
        # No debería pasar: todo texto ya pasó por `publicable`. Lo que queda
        # es un número suelto con forma de PMID (un conteo de siete cifras).
        resultado["publicable"] = False
        resultado["avisos"].append(
            "Este informe no pasa el filtro de publicación (%s): revísalo "
            "antes de compartirlo." % "; ".join(motivos))
        texto_json = _texto_json(resultado)
        texto_html = html_informe(resultado) if salida_html else None

    destino_json = salida_json or os.path.join(carpeta, ARCHIVO_JSON)
    _escribir(destino_json, texto_json)
    log("Escrito %s." % os.path.basename(destino_json))
    if salida_html:
        _escribir(salida_html, texto_html)
        log("Escrito %s." % os.path.basename(salida_html))
    for linea in lineas(resultado):
        log(linea)
    return resultado


def lineas(resultado):
    """El resultado en pocas líneas, para la terminal."""
    if "invariantes" not in resultado:
        return ["No se pudo verificar %s: %s." % (resultado.get("carpeta"),
                                                  resultado.get("motivo"))]
    salida = ["", "Verificación de %s (corrida %s del bronce): %s, código %d."
              % (resultado["carpeta"], resultado["corrida_bronce"],
                 ETIQUETAS[resultado["veredicto"]].lower(),
                 resultado["codigo"])]
    for inv in resultado["invariantes"]:
        salida.append("  %-3s %-15s %s: %s" % (
            inv["id"], ETIQUETAS[inv["estatus"]], inv["titulo"],
            inv["resumen"]))
        for c in inv["comprobaciones"]:
            if c["estatus"] in (FALLA, NO_VERIFICABLE):
                salida.append("        %s: %s%s" % (
                    ETIQUETAS[c["estatus"]], c["titulo"],
                    " (%s)" % c["nota"] if c["nota"] else ""))
    for aviso in resultado["avisos"]:
        salida.append("  AVISO: %s" % aviso)
    return salida


# ------------------------------------------------------------- el HTML

_CSS = """
:root {
  --fondo: #161826; --panel: #232532; --panel2: #1c1e2b;
  --borde: #3f424d; --borde2: #292b31; --texto: #e9e9ed; --tenue: #9397ab;
  --acento: #9184d9; --acento2: #2b2741;
  --ok: #7ddba4; --ok2: #1a3326; --alerta: #e8c37a; --alerta2: #352c14;
  --malo: #f0a09a; --malo2: #3b201e; --radio: 8px;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--fondo); color: var(--texto);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  font-size: 15px; line-height: 1.5;
}
main { max-width: 1000px; margin: 0 auto; padding: 28px 16px 56px; }
h1, h2, h3 { margin: 0; font-weight: 650; letter-spacing: -.01em; }
h1 { font-size: 22px; }
h2 { font-size: 16px; margin: 36px 0 12px; }
p { margin: 0; }
.sobre { color: var(--tenue); font-size: 13px; text-transform: uppercase;
  letter-spacing: .06em; margin-bottom: 6px; }
.meta { color: var(--tenue); font-size: 13px; margin-top: 6px; }
.veredicto { display: inline-block; margin-top: 16px; padding: 8px 14px;
  border-radius: var(--radio); border: 1px solid var(--borde); font-weight: 600; }
.veredicto.cumple, .estatus.cumple { color: var(--ok); border-color: var(--ok);
  background: var(--ok2); }
.veredicto.falla, .estatus.falla { color: var(--malo); border-color: var(--malo);
  background: var(--malo2); }
.veredicto.no_verificable, .estatus.no_verificable { color: var(--alerta);
  border-color: var(--alerta); background: var(--alerta2); }
.estatus { display: inline-block; font-size: 12px; font-weight: 600;
  padding: 1px 8px; border-radius: 999px; border: 1px solid var(--borde);
  color: var(--tenue); white-space: nowrap; }
details { background: var(--panel); border: 1px solid var(--borde2);
  border-radius: var(--radio); margin-bottom: 10px; }
summary { cursor: pointer; padding: 12px 14px; display: flex; gap: 12px;
  align-items: baseline; flex-wrap: wrap; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary .id { color: var(--acento); font-weight: 700; min-width: 26px; }
summary .titulo { font-weight: 600; }
summary .resumen { color: var(--tenue); font-size: 13px; flex-basis: 100%; }
.tabla { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; vertical-align: top; padding: 7px 10px;
  border-top: 1px solid var(--borde2); }
th { color: var(--tenue); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums;
  white-space: nowrap; }
ul.valores { margin: 0; padding-left: 16px; }
.nota { color: var(--tenue); font-size: 12px; margin-top: 4px; }
.panel { background: var(--panel); border: 1px solid var(--borde2);
  border-radius: var(--radio); padding: 6px 4px; }
.embudo { list-style: none; margin: 0; padding: 10px 14px; }
.embudo li { display: grid; grid-template-columns: minmax(150px, 2fr) 3fr
  minmax(70px, auto); gap: 12px; align-items: center; padding: 5px 0; }
.barra { height: 10px; background: var(--panel2); border-radius: 999px;
  overflow: hidden; }
.barra span { display: block; height: 100%; background: var(--acento); }
.cifra { text-align: right; font-variant-numeric: tabular-nums; }
.ic { position: relative; display: block; min-width: 120px; height: 10px;
  background: var(--panel2); border-radius: 999px; }
.ic .rango { position: absolute; top: 0; bottom: 0; background: var(--acento2);
  border: 1px solid var(--acento); border-radius: 999px; }
.ic .punto { position: absolute; top: -2px; width: 4px; height: 14px;
  margin-left: -2px; background: var(--texto); border-radius: 2px; }
ul.avisos { margin: 0; padding: 10px 14px 10px 32px; }
ul.avisos li { margin: 4px 0; }
.cambia td { color: var(--alerta); }
footer { margin-top: 40px; color: var(--tenue); font-size: 12px; }
@media (max-width: 560px) {
  .embudo li { grid-template-columns: 1fr auto; }
  .embudo li .barra { grid-column: 1 / -1; grid-row: 2; }
}
@media print {
  :root { --fondo: #ffffff; --panel: #ffffff; --panel2: #eeeeee;
    --borde: #bbbbbb; --borde2: #dddddd; --texto: #111111; --tenue: #555555;
    --acento: #4b3fb0; --acento2: #e4e1f7; --ok: #11663a; --ok2: #e3f4ea;
    --alerta: #7a5200; --alerta2: #fbf0d9; --malo: #9b1c13; --malo2: #fbe4e2; }
  details { break-inside: avoid; }
}
"""


def _e(texto):
    return html.escape("" if texto is None else str(texto), quote=True)


def _cifra(valor):
    """Un número para leer, con los miles como en el JSON (`_miles`)."""
    if valor is None:
        return u"—"
    if isinstance(valor, bool):
        return u"sí" if valor else "no"
    if isinstance(valor, int):
        return _miles(valor)
    if isinstance(valor, float):
        return ("%.4f" % valor).rstrip("0").rstrip(".")
    return str(valor)


def _porcentaje(valor, decimales=1):
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        return u"—"
    return (u"%." + str(decimales) + u"f\u00a0%%") % (100.0 * valor)


def _estatus_html(estatus):
    return '<span class="estatus %s">%s</span>' % (
        _e(estatus), _e(ETIQUETAS.get(estatus, estatus)))


def _valores_html(valores):
    if not valores:
        return ""
    elementos = []
    for v in valores:
        if len(v) == 3:
            elementos.append(u"%s: registrada %s, hoy %s"
                             % (_e(v[0]), _e(_cifra(v[1])), _e(_cifra(v[2]))))
        elif len(v) == 2:
            elementos.append(u"%s: %s" % (_e(v[0]), _e(_cifra(v[1]))))
        else:
            elementos.append(u" · ".join(_e(_cifra(x)) for x in v))
    return '<ul class="valores">%s</ul>' % "".join(
        "<li>%s</li>" % x for x in elementos)


def _invariantes_html(invariantes):
    partes = []
    for inv in invariantes:
        abierto = " open" if inv["estatus"] in (FALLA, NO_VERIFICABLE) else ""
        filas = []
        for c in inv["comprobaciones"]:
            nota = '<p class="nota">%s</p>' % _e(c["nota"]) if c["nota"] \
                else ""
            filas.append("<tr><td>%s</td><td>%s</td><td>%s%s</td></tr>" % (
                _e(c["titulo"]), _estatus_html(c["estatus"]),
                _valores_html(c["valores"]), nota))
        partes.append(
            '<details class="inv"%s><summary><span class="id">%s</span>'
            '<span class="titulo">%s</span>%s<span class="resumen">%s</span>'
            '</summary><div class="tabla"><table><thead><tr><th>Comprobación'
            '</th><th>Estado</th><th>Valores</th></tr></thead><tbody>%s'
            '</tbody></table></div></details>' % (
                abierto, _e(inv["id"]), _e(inv["titulo"]),
                _estatus_html(inv["estatus"]), _e(inv["resumen"]),
                "".join(filas)))
    return "".join(partes)


def _embudo_html(embudo):
    cifras = [e["n"] for e in embudo if isinstance(e["n"], int)]
    tope = max(cifras) if cifras else 0
    filas = []
    for etapa in embudo:
        ancho = (100.0 * etapa["n"] / tope) if tope and \
            isinstance(etapa["n"], int) else 0.0
        filas.append(
            '<li><span>%s</span><span class="barra"><span style="width: '
            '%.2f%%"></span></span><span class="cifra">%s</span></li>'
            % (_e(etapa["titulo"]), ancho, _e(_cifra(etapa["n"]))))
    return '<div class="panel"><ol class="embudo">%s</ol></div>' % "".join(
        filas)


def _metricas_html(metricas, evaluacion):
    if not metricas:
        return '<p class="nota">No hay métricas: falta evaluacion.json.</p>'
    filas = []
    for m in metricas:
        ic = m["ic95"] if isinstance(m["ic95"], list) and \
            len(m["ic95"]) == 2 else None
        if ic and all(isinstance(x, (int, float)) for x in ic) and \
                isinstance(m["valor"], (int, float)):
            barra = ('<span class="ic"><span class="rango" style="left: '
                     '%.2f%%; width: %.2f%%"></span><span class="punto" '
                     'style="left: %.2f%%"></span></span>'
                     % (100 * ic[0], 100 * (ic[1] - ic[0]), 100 * m["valor"]))
            intervalo = u"%s – %s" % (_porcentaje(ic[0]), _porcentaje(ic[1]))
        else:
            barra, intervalo = "", u"—"
        filas.append(
            '<tr><td>%s</td><td class="num">%s de %s</td><td class="num">%s'
            '</td><td class="num">%s</td><td>%s</td></tr>' % (
                _e(m["nombre"]), _e(_cifra(m["k"])), _e(_cifra(m["n"])),
                _e(_porcentaje(m["valor"])), _e(intervalo), barra))
    notas = ""
    if evaluacion and evaluacion.get("notas"):
        notas = '<ul class="valores nota">%s</ul>' % "".join(
            "<li>%s</li>" % _e(n) for n in evaluacion["notas"])
    return ('<div class="panel tabla"><table><thead><tr><th>Métrica</th>'
            '<th class="num">Aciertos</th><th class="num">Valor</th>'
            '<th class="num">IC 95&nbsp;%% (Wilson)</th><th></th></tr></thead>'
            '<tbody>%s</tbody></table></div>%s' % ("".join(filas), notas))


def _contra_html(contra):
    if not contra:
        return ""

    def tabla(encabezados, filas):
        return ('<div class="panel tabla"><table><thead><tr>%s</tr></thead>'
                '<tbody>%s</tbody></table></div>' % (
                    "".join("<th>%s</th>" % _e(e) for e in encabezados),
                    "".join(filas)))
    filas_inv = []
    for i in contra["invariantes"]:
        filas_inv.append('<tr%s><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            ' class="cambia"' if i["cambia"] else "", _e(i["id"]),
            _e(ETIQUETAS.get(i["antes"], i["antes"] or u"—")),
            _e(ETIQUETAS.get(i["ahora"], i["ahora"]))))
    filas_emb = []
    for e in contra["embudo"]:
        filas_emb.append(
            '<tr%s><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
            '<td class="num">%s</td></tr>' % (
                ' class="cambia"' if e["diferencia"] else "", _e(e["titulo"]),
                _e(_cifra(e["antes"])), _e(_cifra(e["ahora"])),
                _e(_cifra(e["diferencia"]))))
    filas_met = []
    for m in contra["metricas"]:
        dif = m["diferencia"]
        filas_met.append(
            '<tr%s><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
            '<td class="num">%s</td></tr>' % (
                ' class="cambia"' if dif else "", _e(m["nombre"]),
                _e(_porcentaje(m["antes"])), _e(_porcentaje(m["ahora"])),
                _e(u"%+.1f puntos" % (100 * dif) if dif is not None
                   else u"—")))
    return (
        '<h2>Comparación con %s</h2><p class="meta">Verificado %s, carpeta '
        '%s, código %s; hoy código %s.</p>%s%s%s' % (
            _e(contra.get("archivo")), _e(contra.get("verificado_en")),
            _e(contra.get("carpeta")), _e(contra.get("codigo_antes")),
            _e(contra.get("codigo_ahora")),
            tabla(["Invariante", "Antes", "Ahora"], filas_inv),
            tabla(["Etapa", "Antes", "Ahora", "Diferencia"], filas_emb),
            tabla(["Métrica", "Antes", "Ahora", "Diferencia"], filas_met)))


def html_informe(resultado):
    """El informe en un HTML autocontenido: ni scripts, ni fuentes, ni hojas
    de estilo de fuera, porque la máquina del laboratorio puede no tener red.
    Todo texto pasa por `html.escape`."""
    frases = {CUMPLE: "Cumple todos los invariantes",
              FALLA: "Falla al menos un invariante",
              NO_VERIFICABLE: "No se pudo verificar todo"}
    corpus = resultado.get("corpus") or {}
    avisos = resultado.get("avisos") or []
    lista_avisos = ('<div class="panel"><ul class="avisos">%s</ul></div>'
                    % "".join("<li>%s</li>" % _e(a) for a in avisos)
                    if avisos else '<p class="nota">Ninguno.</p>')
    cuerpo = (
        '<header><p class="sobre">Verificación de una carpeta del flujo</p>'
        '<h1>Corrida %s del bronce · %s</h1>'
        '<p class="meta">Modelo %s · corpus %s · base por %s, en solo lectura'
        ' · verificado %s</p>'
        '<p class="veredicto %s">%s (código %s)</p></header>'
        '<h2>Invariantes</h2>%s'
        '<h2>Embudo</h2>%s'
        '<h2>Métricas de la evaluación</h2>%s'
        '<h2>Avisos</h2>%s'
        '%s'
        '<footer>Informe de grn_verificacion.verificar, versión %s. Solo '
        'conteos, huellas y nombres de archivo: ni rutas, ni oraciones, ni '
        'locus, ni PMIDs.</footer>' % (
            _e(resultado["corrida_bronce"]), _e(resultado["carpeta"]),
            _e(resultado.get("modelo") or u"—"),
            _e(corpus.get("nombre") or u"—"),
            _e(_origen_humano((resultado.get("base") or {}).get("origen"))),
            _e(resultado["verificado_en"]), _e(resultado["veredicto"]),
            _e(frases[resultado["veredicto"]]), _e(resultado["codigo"]),
            _invariantes_html(resultado["invariantes"]),
            _embudo_html(resultado["embudo"]),
            _metricas_html(resultado["metricas"], resultado["evaluacion"]),
            lista_avisos, _contra_html(resultado.get("contra")),
            _e(resultado["version"])))
    return (
        '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '\n<title>Verificación corrida %s</title>\n<style>%s</style>\n'
        '</head>\n<body>\n<main>\n%s\n</main>\n</body>\n</html>\n' % (
            _e(resultado["corrida_bronce"]), _CSS, cuerpo))
