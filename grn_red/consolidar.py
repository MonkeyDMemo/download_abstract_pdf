"""Las reglas de consolidación de la red, como parámetros.

POR OMISIÓN NO DECIDE NADA
==========================
Con la configuración por omisión, `consolidar()` llama a `etapa2/red.py`
(`main`) con los mismos argumentos que le pasaba el flujo, y la red es la de
siempre **byte por byte**: `red.tsv`, `red_evidencias.tsv` y `red_informe.json`
con su sello. No por imitación sino por construcción: no hay una segunda
implementación del filtro, la deduplicación, el tope ni el signo que se pueda
separar de la primera. Todo lo que lee `red.tsv` (el paquete, la evaluación
contra el oro, el contraste y `verificar`) sigue leyendo exactamente lo mismo.

LAS REGLAS QUE SE PUEDEN MOVER
==============================
Las del borrador para el asesor (`docs/reunion-asesor-23oct.md`, decisión f, y
`docs/operones-asesor.md`, D9):

- `autorregulacion`: `excluir` (la de `red.py`) o `marcar`, que pasa
  `--incluir-autorregulacion` y deja la fila con `autorregulacion=true`. La
  autorregulación existe en el dominio; sin análisis sintáctico no se
  distingue de una oración que nombra dos veces el gen, y por eso se marca en
  vez de afirmarse.
- `nivel_soporte`: agrega la columna `nivel_soporte`, `candidata` con un solo
  artículo y `soporte_multiple` con dos o más. Es una etiqueta sobre
  `n_articulos`, que ya estaba en la fila: no filtra nada.
- `operones`: `nodo` (la de `red.py`: el operón es un nodo) o `expandir`. Ver
  abajo.
- `mayoria`, `umbrales`, `min_evidencias` y `min_articulos`: los de `red.py`,
  que se le pasan tal cual. Sus valores por omisión son los suyos.
- `signo_lexico` (`evidencias` o `aristas`) y `voto_articulo` (23-oct-2026):
  el voto léxico de las evidencias que BioBERT dejó en `regulates` y un voto
  por artículo en las aristas con votos de los dos signos. Apagados por
  omisión y fuera de todo perfil, porque se miden en la tanda 2 de la muestra
  ciega. Ver `signo.py`. Con alguno prendido hay que dar `nombre`: sin él, la
  red iría a `red_recomendada.tsv` y pisaría la del perfil recomendado.

El perfil `recomendado` es el del borrador: autorregulación marcada, nivel de
soporte y operones expandidos, con el signo y los umbrales de `red.py`.

Toda configuración que no sea la por omisión escribe
`red_<nombre>.tsv`, `red_<nombre>_evidencias.tsv` y
`red_<nombre>_informe.json` (`nombre` es `recomendada` si no se dice otro) y
**nunca** toca `red.tsv`: la red de `red.py` es la que miden la evaluación y
el contraste, y una regla nueva no puede cambiarles la entrada a sus espaldas.

CÓMO SE CONSTRUYE UNA RED CON OTRAS REGLAS
==========================================
Primero `red.py` arma la red con los parámetros que le tocan (signo, umbrales,
mínimos, autorregulación) en una carpeta temporal; después se le agregan las
columnas y las aristas expandidas. Así lo que decide el signo sigue teniendo
una sola implementación, y la red con otras reglas es la de `red.py` más lo
que dice su informe que se le agregó.

Las reglas del signo van entre una cosa y otra: recalculan el signo de las
aristas de `red.py` con `red.resolver_signo` (`signo.py`) **antes** de
expandir, así una arista expandida copia el signo nuevo y sus columnas. El
orden de las columnas es el de `red.py`, las del signo, `nivel_soporte` y al
final `expandida_de`.

`red_<nombre>_evidencias.tsv` es el de `red.py` sin cambios: la evidencia es
de las aristas observadas. Una arista expandida no tiene evidencia propia; la
suya está bajo `(tf, expandida_de)`.

LA EXPANSIÓN DE OPERONES (D9)
=============================
Por cada arista cuyo **blanco** es un operón del catálogo del paso 1
(`grn_bronce/recursos/operones_pao1.tsv`, leído con `grn_bronce.operones`, la
única expansión operón → genes del proyecto) se agrega una arista por gen del
operón, con `expandida_de=<operón>`, y la arista del operón **se queda**: es la
procedencia, lo que el texto dijo. Las filas observadas llevan `expandida_de`
vacío.

- **Solo los blancos.** Un regulador es una proteína; «MexEF regula a X»
  nombra el producto de un operón, y repartirlo entre sus genes inventaría
  tantos reguladores como genes tenga. Un operón como `tf` se queda como está.
- **Solo lo que la tabla conoce**, como en el resto del proyecto: un operón
  que el texto nombra y el catálogo no tiene no expande a nada.
- **El gen se escribe con el símbolo del catálogo** (columna `miembros`, en
  forma de gen, como el `blanco` de `red.py`), o con su locus cuando el
  catálogo no le da símbolo. Una arista expandida y una observada sobre el
  mismo gen con otra escritura no se unifican aquí: unificar por locus es
  trabajo del paquete.
- **La arista expandida copia la fila del operón**: signo, conflicto,
  conteos, artículos, confianza, secciones, PMIDs y oración. Es la misma
  evidencia, y `expandida_de` dice que habla del operón, no del gen.
- **No se suman.** Si `LasR → mexE` ya estaba observada, o dos operones
  expanden al mismo gen, quedan filas paralelas, distintas por `expandida_de`:
  sumarlas sería volver a agregar, que es trabajo de `red.py`.
- **Una expandida puede ser autorregulación** aunque la del operón no lo sea
  (AlgU → algU-mucABD da AlgU → algU). Se reconoce por el nombre, sin
  mayúsculas, o por el locus; con `autorregulacion=excluir` se descarta, como
  `red.py` descarta las suyas, y con `marcar` va marcada.

Biblioteca estándar y Python 3.8. No imprime: recibe un callable `log`.
"""

import collections
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ETAPA2 = os.path.join(_RAIZ, "etapa2")
for _p in (_RAIZ, _ETAPA2):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import red as _red                             # noqa: E402  (etapa2/red.py)
from grn_bronce import operones as _operones   # noqa: E402
from grn_comun import procedencia              # noqa: E402
from grn_comun.archivos import borrar, reemplazar   # noqa: E402

# Sube cuando, con las mismas entradas y los mismos parámetros, una red con
# otras reglas pasa a decir otra cosa. La red por omisión no la lleva: es la
# de `red.py`.
VERSION = "1"

RED = "red.tsv"
EVIDENCIAS = "red_evidencias.tsv"
INFORME = "red_informe.json"
PREDICCIONES = "predicciones.jsonl"
META = "predicciones_meta.json"
PARES = "pares.jsonl"

NOMBRE_POR_OMISION = "recomendada"
# El nombre va en un nombre de archivo que el tablero lista y entrega: patrón
# cerrado. `evidencias` e `informe` quedan fuera porque `red_evidencias.tsv`
# y `red_informe.json` son de la red por omisión.
NOMBRE_VALIDO = re.compile(r"^[a-z0-9_]{1,40}$")
NOMBRES_RESERVADOS = ("evidencias", "informe")

AUTORREGULACION = ("excluir", "marcar")
OPERONES = ("nodo", "expandir")
# Los alcances del voto léxico; None lo apaga. Ver `signo.py`.
SIGNO_LEXICO = ("evidencias", "aristas")

CANDIDATA = "candidata"
SOPORTE_MULTIPLE = "soporte_multiple"

# Las de `red.py`. Copiarlas aquí permitiría que el «por omisión» de las dos
# se separara y la red por omisión dejara de ser la suya sin que nada avisara.
#
# Las dos últimas no son de `red.py`: apagadas, `_argv_red` ni las mira y la
# red por omisión sigue siendo la suya.
POR_OMISION = collections.OrderedDict([
    ("autorregulacion", "excluir"),
    ("nivel_soporte", False),
    ("operones", "nodo"),
    ("mayoria", 0.66),
    ("umbrales", None),
    ("min_evidencias", 1),
    ("min_articulos", 1),
    ("signo_lexico", None),
    ("voto_articulo", False),
])

PERFILES = collections.OrderedDict([
    ("omision", {}),
    ("recomendado", {"autorregulacion": "marcar", "nivel_soporte": True,
                     "operones": "expandir"}),
])

# Qué paso escribe cada entrada: «falta X» a secas no dice qué correr.
_QUIEN_ESCRIBE = {
    PREDICCIONES: "el paso «biobert» del flujo",
    META: "el paso «biobert» del flujo",
    PARES: "el paso «pares» del flujo",
}


class ErrorConsolidar(RuntimeError):
    """Falta una entrada, un parámetro no vale o `red.py` se negó."""


def _nada(_m):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------- configuración

def configuracion(perfil="omision", **cambios):
    """La configuración de un perfil con `cambios` encima, ya validada.

    Un cambio con valor None no cambia nada: así el CLI pasa todos sus flags
    y solo cuentan los que se dieron.
    """
    if perfil not in PERFILES:
        raise ErrorConsolidar("Perfil desconocido: %r. Hay %s."
                              % (perfil, ", ".join(PERFILES)))
    desconocidos = sorted(set(cambios) - set(POR_OMISION))
    if desconocidos:
        raise ErrorConsolidar("Parámetros desconocidos: %s."
                              % ", ".join(desconocidos))
    cfg = collections.OrderedDict(POR_OMISION)
    cfg.update(PERFILES[perfil])
    for clave, valor in cambios.items():
        if valor is not None:
            cfg[clave] = valor
    return _validar(cfg)


def _validar(cfg):
    if cfg["autorregulacion"] not in AUTORREGULACION:
        raise ErrorConsolidar("autorregulacion es %r y tiene que ser %s."
                              % (cfg["autorregulacion"],
                                 " o ".join(AUTORREGULACION)))
    if cfg["operones"] not in OPERONES:
        raise ErrorConsolidar("operones es %r y tiene que ser %s."
                              % (cfg["operones"], " o ".join(OPERONES)))
    if cfg["signo_lexico"] is not None and (
            cfg["signo_lexico"] not in SIGNO_LEXICO):
        raise ErrorConsolidar("signo_lexico es %r y tiene que ser %s, o "
                              "ninguno para apagarlo."
                              % (cfg["signo_lexico"], " o ".join(SIGNO_LEXICO)))
    cfg["nivel_soporte"] = bool(cfg["nivel_soporte"])
    cfg["voto_articulo"] = bool(cfg["voto_articulo"])
    try:
        cfg["mayoria"] = float(cfg["mayoria"])
    except (TypeError, ValueError):
        raise ErrorConsolidar("mayoria es %r y tiene que ser un número."
                              % (cfg["mayoria"],))
    for clave in ("min_evidencias", "min_articulos"):
        valor = cfg[clave]
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
            raise ErrorConsolidar("%s es %r y tiene que ser un entero mayor o "
                                  "igual que 1." % (clave, valor))
    umbrales = cfg["umbrales"]
    if isinstance(umbrales, dict):
        faltan = sorted(set(_red.SIGNOS) - set(umbrales))
        if faltan:
            raise ErrorConsolidar("Faltan umbrales para %s." % ", ".join(faltan))
        try:
            umbrales = dict((c, float(umbrales[c])) for c in _red.SIGNOS)
        except (TypeError, ValueError):
            raise ErrorConsolidar("Los umbrales tienen que ser números.")
        # Los de red.py escritos a mano siguen siendo los por omisión: si no,
        # pedir explícitamente lo mismo escribiría otra red con otro nombre.
        cfg["umbrales"] = (None if umbrales == _red.UMBRALES_POR_OMISION
                           else umbrales)
    elif umbrales is not None and not isinstance(umbrales, str):
        raise ErrorConsolidar("umbrales tiene que ser un dict por clase o la "
                              "ruta de un umbrales_sugeridos.json.")
    return cfg


def es_omision(cfg):
    """Si la configuración es la de `red.py`, que escribe `red.tsv`."""
    return cfg == _validar(collections.OrderedDict(POR_OMISION))


def _argv_red(carpeta, cfg, salida, evidencias, informe):
    """Los argumentos de `red.py` para `cfg`. Con la configuración por
    omisión son exactamente los que el flujo le pasaba antes del 22-oct-2026,
    y ningún flag más: la red por omisión es la suya."""
    argv = ["--predicciones", os.path.join(carpeta, PREDICCIONES),
            "--pares", os.path.join(carpeta, PARES),
            "--salida", salida, "--evidencias", evidencias,
            "--informe", informe]
    if cfg["mayoria"] != POR_OMISION["mayoria"]:
        argv += ["--mayoria", repr(cfg["mayoria"])]
    if cfg["min_evidencias"] != POR_OMISION["min_evidencias"]:
        argv += ["--min-evidencias", str(cfg["min_evidencias"])]
    if cfg["min_articulos"] != POR_OMISION["min_articulos"]:
        argv += ["--min-articulos", str(cfg["min_articulos"])]
    if isinstance(cfg["umbrales"], str):
        argv += ["--umbrales", cfg["umbrales"]]
    elif cfg["umbrales"]:
        for c in _red.SIGNOS:
            argv += ["--umbral-" + c, repr(cfg["umbrales"][c])]
    if cfg["autorregulacion"] == "marcar":
        argv += ["--incluir-autorregulacion"]
    return argv


def _correr_red(argv, log):
    """`red.py` en este proceso. Sale con `sys.exit("mensaje")` cuando la
    entrada no le sirve; aquí ese mensaje pasa a ErrorConsolidar, para que el
    CLI lo diga sin traceback y el flujo lo guarde."""
    try:
        codigo = _red.main(argv, log=log)
    except SystemExit as e:
        if e.code in (None, 0):
            return
        raise ErrorConsolidar("etapa2/red.py se detuvo: %s" % (e.code,))
    if codigo:
        raise ErrorConsolidar("etapa2/red.py salió con código %s." % codigo)


# ------------------------------------------------------------- operones

def genes_de_operones(ruta):
    """{clave del operón: (nombre, [(símbolo, locus)])} del catálogo del paso 1.

    La lista de locus es la de `operones.desde_filas`, la única expansión del
    proyecto, en el orden de la tabla. El símbolo de cada locus es el que la
    misma fila pone en `miembros` en la misma posición; si las dos columnas no
    tienen el mismo largo no hay forma segura de emparejarlas y el gen va con
    su locus.
    """
    try:
        filas = _operones.leer(ruta)
    except (IOError, OSError, ValueError) as e:
        raise ErrorConsolidar("No pude leer el catálogo de operones: %s" % e)
    _, locus_de = _operones.desde_filas(filas)
    simbolos = {}
    nombres = {}
    for fila in filas:
        nombre = (fila.get("operon") or "").strip()
        if not nombre:
            continue
        miembros = [x.strip() for x in (fila.get("miembros") or "").split("|")
                    if x.strip()]
        locus = [x.strip() for x in (fila.get("locus_tags") or "").split("|")
                 if x.strip()]
        k = _operones.clave(nombre)
        # La última fila gana, como en desde_filas: si no, el símbolo y el
        # locus de un operón repetido saldrían de filas distintas.
        simbolos[k] = (dict(zip(locus, miembros))
                       if len(miembros) == len(locus) else {})
        nombres[k] = nombre
    salida = {}
    for k, locus in locus_de.items():
        if not locus:
            continue
        genes, vistos = [], set()
        for lt in locus:
            simbolo = simbolos.get(k, {}).get(lt) or lt
            if simbolo in vistos:
                continue
            vistos.add(simbolo)
            genes.append((simbolo, lt))
        salida[k] = (nombres[k], genes)
    return salida


def _es_el_mismo(tf, simbolo, locus):
    """Si el regulador es el gen expandido: por nombre sin mayúsculas (LasR y
    lasR son la misma entidad en dos formas) o por locus."""
    tf = tf.strip().lower()
    return tf == simbolo.strip().lower() or tf == locus.strip().lower()


def expandir(filas, catalogo, autorregulacion):
    """Las filas de la red más una por gen de cada blanco que es operón.

    `filas` son dicts de `red.tsv`; las que se devuelven llevan además
    `expandida_de`. Devuelve `(filas, cuenta)`, con `cuenta` un Counter de lo
    expandido para el informe. Ver el docstring del módulo.
    """
    cuenta = collections.Counter()
    operones_vistos = set()
    salida = []
    for fila in filas:
        fila = dict(fila)
        fila["expandida_de"] = ""
        salida.append(fila)
        clave = _operones.clave(fila["blanco"])
        if clave not in catalogo:
            continue
        nombre, genes = catalogo[clave]
        cuenta["aristas_de_operon_expandidas"] += 1
        operones_vistos.add(nombre)
        for simbolo, locus in genes:
            if _operones.clave(simbolo) == clave:
                # Un operón de un gen que se llama como él: expandirlo daría
                # la misma arista dos veces.
                continue
            nueva = dict(fila)
            nueva["blanco"] = _red.celda(simbolo)
            nueva["expandida_de"] = fila["blanco"]
            if _es_el_mismo(fila["tf"], simbolo, locus):
                if autorregulacion == "excluir":
                    cuenta["expandidas_autorregulacion_excluidas"] += 1
                    continue
                nueva["autorregulacion"] = "true"
            cuenta["aristas_expandidas"] += 1
            salida.append(nueva)
    cuenta["operones_expandidos"] = len(operones_vistos)
    salida.sort(key=lambda f: (f["tf"], f["blanco"], f["expandida_de"]))
    return salida, cuenta


def nivel_de_soporte(n_articulos):
    return CANDIDATA if int(n_articulos) == 1 else SOPORTE_MULTIPLE


# ------------------------------------------------------------- escritura

def _leer_red(ruta):
    from grn_red import paquete
    try:
        return paquete.leer_tsv(ruta, _red.COLUMNAS_RED)
    except paquete.ErrorPaquete as e:
        raise ErrorConsolidar(str(e))


def _escribir_red(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(_red.celda(fila[c]) for c in columnas) + "\n")


def _escribir_json(ruta, objeto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)
        f.write("\n")


def nombres_de_salida(nombre):
    """(red, evidencias, informe) de una red con otras reglas."""
    return ("red_%s.tsv" % nombre, "red_%s_evidencias.tsv" % nombre,
            "red_%s_informe.json" % nombre)


# ------------------------------------------------------------- consolidar

def _con_reglas_de_signo(cfg):
    return bool(cfg["signo_lexico"] or cfg["voto_articulo"])


def _exigir_entradas(carpeta, cfg, catalogo):
    """ErrorConsolidar si falta algo. Con el voto léxico devuelve sus
    disparadores, `(vocab, ruta)`, y si no, None: se cargan una sola vez,
    aquí, para que los que se exigen sean los que votan."""
    for n in (PREDICCIONES, META, PARES):
        if not os.path.isfile(os.path.join(carpeta, n)):
            raise ErrorConsolidar("Falta %s en %s. Lo escribe %s."
                                  % (n, carpeta, _QUIEN_ESCRIBE[n]))
    if cfg["operones"] == "expandir" and not os.path.isfile(catalogo):
        raise ErrorConsolidar("Falta el catálogo de operones del paso 1: %s."
                              % catalogo)
    if isinstance(cfg["umbrales"], str) and not os.path.isfile(
            cfg["umbrales"]):
        raise ErrorConsolidar("No encuentro el archivo de umbrales %s."
                              % cfg["umbrales"])
    if cfg["signo_lexico"]:
        # Tarde, como `paquete` en `_leer_red`: signo.py importa de aquí, y
        # la red por omisión no tiene por qué cargarlo.
        from grn_red import signo
        return signo.cargar_disparadores()
    return None


def consolidar(carpeta, cfg=None, nombre=None, log=_nada, catalogo=None):
    """Arma la red de `carpeta` con las reglas de `cfg` y devuelve su resumen.

    Sin `cfg` y sin `nombre` es la red de `red.py`, en `red.tsv`. Con otra
    configuración, o con un `nombre`, va a `red_<nombre>*` (ver el docstring
    del módulo); con las reglas del signo el `nombre` es obligatorio.
    `catalogo` existe para las pruebas; por omisión es el catálogo versionado
    del paso 1. Lanza ErrorConsolidar sin haber publicado nada si falta una
    entrada o `red.py` se niega.
    """
    # Por `configuracion` y no tal cual: un dict con solo lo que cambia
    # también vale, y una clave mal escrita es error y no un parámetro que
    # nadie lee.
    cfg = configuracion(**dict(cfg or {}))
    catalogo = catalogo or _operones.RUTA_POR_OMISION
    if nombre is None and _con_reglas_de_signo(cfg):
        # Sin nombre, la red iría a red_recomendada.tsv: el flujo la escribe
        # con el perfil recomendado, y otra regla la pisaría sin decirlo.
        raise ErrorConsolidar(
            "El voto léxico y el voto por artículo piden un nombre "
            "(--nombre): sin él la red iría a %s y pisaría la del perfil "
            "recomendado." % nombres_de_salida(NOMBRE_POR_OMISION)[0])
    disparadores = _exigir_entradas(carpeta, cfg, catalogo)

    if nombre is None and es_omision(cfg):
        rutas = [os.path.join(carpeta, n) for n in (RED, EVIDENCIAS, INFORME)]
        _correr_red(_argv_red(carpeta, cfg, *rutas), log)
        return collections.OrderedDict([
            ("nombre", None), ("archivos", [RED, EVIDENCIAS, INFORME]),
            ("parametros", cfg)])

    nombre = NOMBRE_POR_OMISION if nombre is None else nombre
    if not NOMBRE_VALIDO.match(nombre) or nombre in NOMBRES_RESERVADOS:
        raise ErrorConsolidar(
            "El nombre %r no sirve: minúsculas, dígitos y «_», hasta 40, y "
            "ni «evidencias» ni «informe», que son de la red por omisión."
            % nombre)
    return _consolidar_con_reglas(carpeta, cfg, nombre, log, catalogo,
                                  disparadores)


def _consolidar_con_reglas(carpeta, cfg, nombre, log, catalogo,
                           disparadores=None):
    archivos = nombres_de_salida(nombre)
    destinos = [os.path.join(carpeta, n) for n in archivos]
    tmp = [r + ".tmp" for r in destinos]
    log("Red «%s» de %s" % (nombre, os.path.basename(
        os.path.normpath(os.path.abspath(carpeta)))))

    # La carpeta temporal va dentro de la del flujo: misma unidad que los
    # destinos, y nada fuera del árbol de salidas. Empieza por punto y es
    # carpeta, así que el tablero no la lista.
    base = tempfile.mkdtemp(prefix=".consolidar_", dir=carpeta)
    try:
        rutas_base = [os.path.join(base, n) for n in (RED, EVIDENCIAS, INFORME)]

        def log_red(m):
            # Las líneas de red.py que nombran la carpeta temporal dirían que
            # la red quedó donde no queda.
            if base not in m:
                log(m)

        _correr_red(_argv_red(carpeta, cfg, *rutas_base), log_red)
        filas = _leer_red(rutas_base[0])
        with io.open(rutas_base[2], encoding="utf-8") as f:
            informe_red = json.load(f, object_pairs_hook=collections.OrderedDict)

        columnas = list(_red.COLUMNAS_RED)
        resumen_signo = None
        if _con_reglas_de_signo(cfg):
            from grn_red import signo
            # Antes de expandir: la arista expandida copia la fila del operón,
            # y tiene que copiar el signo nuevo. Sin log: el aviso de
            # unir_con_pares ya salió en la corrida de red.py de arriba.
            filas, columnas_signo, resumen_signo = signo.votar(
                carpeta, filas, informe_red, cfg["signo_lexico"],
                cfg["voto_articulo"],
                vocab=disparadores[0] if disparadores else None)
            columnas += columnas_signo
        cuenta = collections.Counter()
        if cfg["operones"] == "expandir":
            filas, cuenta = expandir(filas, genes_de_operones(catalogo),
                                     cfg["autorregulacion"])
        if cfg["nivel_soporte"]:
            for fila in filas:
                fila["nivel_soporte"] = nivel_de_soporte(fila["n_articulos"])
            columnas.append("nivel_soporte")
        if cfg["operones"] == "expandir":
            # Después de `nivel_soporte`, que es una columna de toda fila: la
            # de la expansión solo dice algo en las filas expandidas.
            columnas.append("expandida_de")

        try:
            _escribir_red(tmp[0], columnas, filas)
            shutil.copyfile(rutas_base[1], tmp[1])
            informe = _informe(carpeta, cfg, nombre, archivos, columnas, filas,
                               cuenta, informe_red, catalogo, destinos, tmp,
                               resumen_signo, disparadores)
            _escribir_json(tmp[2], informe)
        except BaseException:
            for r in tmp:
                try:
                    borrar(r)
                except OSError:
                    pass
            raise
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # El informe al final: un corte a medias no deja un informe nuevo junto a
    # una red vieja, cuyo sello no casaría.
    for origen, destino in zip(tmp, destinos):
        reemplazar(origen, destino)
    conteos = informe["conteos"]
    log("  %d aristas (%d observadas, %d expandidas de %d operones); "
        "%d autorregulaciones" % (conteos["n_aristas"],
                                  conteos["n_aristas_observadas"],
                                  conteos["n_aristas_expandidas"],
                                  conteos["n_operones_expandidos"],
                                  conteos["n_autorregulaciones"]))
    if conteos["por_nivel"]:
        log("  %s %d, %s %d" % (CANDIDATA, conteos["por_nivel"][CANDIDATA],
                                SOPORTE_MULTIPLE,
                                conteos["por_nivel"][SOPORTE_MULTIPLE]))
    s = conteos["signo"]
    if s is not None:
        if s["votos_lexicos"] is not None:
            v = s["votos_lexicos"]
            log("  votos léxicos: %d +, %d -, %d sin signo"
                % (v["activates"], v["represses"], v["sin_signo"]))
        log("  signo: %d aristas tocadas (%d mixtas), %d con otro signo que "
            "red.py; %d conflictos creados y %d resueltos; %d sin confianza"
            % (s["n_aristas_tocadas"], s["n_aristas_mixtas"],
               s["n_aristas_con_otro_signo"], s["n_conflictos_creados"],
               s["n_conflictos_resueltos"], s["n_aristas_sin_confianza"]))
    log("%s, %s y %s" % archivos)
    return collections.OrderedDict([
        ("nombre", nombre), ("archivos", list(archivos)), ("parametros", cfg),
        ("conteos", conteos)])


def _informe(carpeta, cfg, nombre, archivos, columnas, filas, cuenta,
             informe_red, catalogo, destinos, tmp, resumen_signo=None,
             disparadores=None):
    """El informe de una red con otras reglas: los parámetros, los conteos,
    las huellas de lo que leyó y de lo que escribió, y el informe de `red.py`
    de la red de la que parte.

    `resumen_signo` es el de las reglas del signo (`signo.aplicar`), o None
    si están apagadas; `disparadores`, el `(vocab, ruta)` del voto léxico.
    `red_py` conserva el reparto de signos de `red.py`; el de `conteos` es el
    de esta red."""
    observadas = [f for f in filas if not f.get("expandida_de")]
    informe = collections.OrderedDict()
    informe["version"] = VERSION
    informe["fecha"] = _ahora()
    informe["nombre"] = nombre
    informe["parametros"] = collections.OrderedDict(cfg)
    informe["columnas"] = columnas
    informe["archivos"] = collections.OrderedDict(zip(
        ("red", "evidencias", "informe"), archivos))
    por_nivel = None
    if cfg["nivel_soporte"]:
        n = collections.Counter(f["nivel_soporte"] for f in filas)
        por_nivel = collections.OrderedDict(
            (k, n[k]) for k in (CANDIDATA, SOPORTE_MULTIPLE))
    signos = collections.Counter(f["signo"] for f in filas)
    informe["conteos"] = collections.OrderedDict([
        ("n_aristas", len(filas)),
        ("n_aristas_observadas", len(observadas)),
        ("n_aristas_expandidas", cuenta["aristas_expandidas"]),
        ("n_aristas_de_operon_expandidas",
         cuenta["aristas_de_operon_expandidas"]),
        ("n_operones_expandidos", cuenta["operones_expandidos"]),
        ("n_expandidas_autorregulacion_excluidas",
         cuenta["expandidas_autorregulacion_excluidas"]),
        ("n_autorregulaciones",
         sum(1 for f in filas if f["autorregulacion"] == "true")),
        ("por_nivel", por_nivel),
        ("reparto_signos", collections.OrderedDict(
            (s, signos[s]) for s in _red.SIGNOS)),
        ("n_conflictos", sum(1 for f in filas if f["conflicto"] == "true")),
        # De las aristas observadas, antes de expandir.
        ("signo", resumen_signo),
    ])
    recursos = collections.OrderedDict()
    if cfg["operones"] == "expandir":
        # Sin CRLF, como en el paquete: un checkout de Windows no es otro
        # catálogo.
        recursos["catalogo_operones"] = collections.OrderedDict([
            ("archivo", os.path.basename(catalogo)),
            ("huella", procedencia.huella_texto(catalogo))])
    if disparadores:
        recursos["disparadores"] = collections.OrderedDict([
            ("archivo", os.path.basename(disparadores[1])),
            ("huella", procedencia.huella_texto(disparadores[1]))])
    informe["recursos"] = recursos
    huellas = procedencia.sellar(collections.OrderedDict([
        ("pares", os.path.join(carpeta, PARES)),
        ("predicciones", os.path.join(carpeta, PREDICCIONES)),
        ("predicciones_meta", os.path.join(carpeta, META)),
    ]))
    # Medidas en su temporal, como en red.py: el nombre final todavía no
    # existe o es el de la corrida anterior.
    huellas["red"] = procedencia.sellar_como(destinos[0], tmp[0])
    huellas["evidencias"] = procedencia.sellar_como(destinos[1], tmp[1])
    informe["huellas"] = huellas
    # El informe de red.py sobre la red de la que se parte, con su barrido.
    # Sin sus huellas: sellan los archivos de la carpeta temporal, que ya no
    # existen.
    informe_red.pop("huellas", None)
    informe["red_py"] = informe_red
    return informe
