"""El paquete de la red: la red de `etapa2/red.py`, lista para usarse fuera.

POR QUÉ HACE FALTA
==================
En `red.tsv`, `tf` y `blanco` son **formas de presentación**, no identidades:
`etapa2/lexico.py` escribe el regulador como proteína (`forma_proteina`,
«LasR») y el blanco como gen (`forma_gen`, «lasR»). Un grafo armado con esas
dos columnas tal cual tiene dos nodos para el mismo gen, y la regulación que
pasa por LasR queda partida en dos componentes que no se tocan. Aquí los nodos
se unifican por **id canónico**: cada evidencia de `red_evidencias.tsv` lleva
su `id_par`, y en `pares.jsonl` ese par dice qué entidades marcó (`tf_id`,
`target_id`) y en qué locus caen (`tf_locus`, `target_locus`). Un gen que el
texto nombra por su símbolo y por su locus («lasR» y «PA1430») también queda
en un nodo: se unifica por locus (ver `unificar_por_locus`).

Lo que se escribe, junto a las entradas, en la carpeta del flujo:

- `nodos.tsv`: un nodo por id canónico (ver `armar_nodos`).
- `red.graphml`: la misma red como grafo dirigido, con los atributos escalares
  de cada fila de `red.tsv` y sin la oración representativa, que se queda en el
  TSV: en un visor de grafos es texto que nadie lee y pesa más que todo lo
  demás junto.
- `manifiesto.json`: de qué corrida del bronce, de qué modelo y de qué
  recursos sale el paquete, con el sha256 y los bytes de cada archivo.

LO QUE NO HACE
==============
No decide nada que `red.py` no haya decidido: el signo, la confianza y los
conteos de cada arista son los de su fila. Tampoco expande un operón a sus
genes, porque eso es la decisión D9 (PLAN.md §1.4), abierta: el operón es un
nodo, y sus genes van en su columna `locus`.

COLISIONES
==========
`red.py` agrupa por las formas de presentación. Si dos ids canónicos distintos
comparten forma (dos ids que solo difieren en la mayúscula inicial), su fila
junta la evidencia de dos pares, y su signo y sus conteos no son de ninguno.
Esa fila no entra al grafo: partirla sería volver a agregar, que es trabajo de
`red.py`, y pegarla a uno de los dos pares le daría la evidencia del otro. Se
lista en el manifiesto con cuántas evidencias trae de cada par. Se busca en
las evidencias que `red.py` publica, que son a lo más `max_por_par` por arista.

ANTES DE ESCRIBIR
=================
Lo que se junta aquí viene de tres pasos del flujo, y el peligro es el de
`grn_comun/procedencia.py`: archivos de corridas distintas que, cada uno por
separado, están bien formados. Se exige que `pares.jsonl` y `red.tsv` sean los
que sella `red_informe.json`; que `predicciones_meta.json` sea el de las
predicciones de esa red, porque si no el manifiesto le atribuiría la red a otro
modelo; que cada fila tenga en `red_evidencias.tsv` justo las `n_evidencias`
que declara, y que cada evidencia caiga en un par con sus mismas formas.

Biblioteca estándar y Python 3.8. No imprime: recibe un callable `log`.
"""

import collections
import datetime
import hashlib
import io
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ETAPA2 = os.path.join(_RAIZ, "etapa2")
for _p in (_RAIZ, _ETAPA2):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Los contratos se importan de quien escribe cada archivo, no se copian: si
# `red.py` agrega una columna, este lector tiene que fallar en el encabezado,
# y no leer cada columna que sigue con el nombre de la anterior.
import lexico as _lexico                       # noqa: E402  (etapa2/lexico.py)
import red as _red                             # noqa: E402  (etapa2/red.py)
from grn_bronce import operones as _operones   # noqa: E402
from grn_comun import procedencia              # noqa: E402
from grn_comun.archivos import borrar, reemplazar   # noqa: E402

# Sube cuando, con las mismas entradas, el paquete pasa a decir otra cosa.
VERSION = "1"

COLUMNAS_RED = _red.COLUMNAS_RED
COLUMNAS_EVIDENCIAS = _red.COLUMNAS_EVIDENCIAS
COLUMNAS_GENES = _lexico.COLUMNAS_GENES

RUTA_GENES = os.path.join(_RAIZ, "grn_bronce", "recursos", "genes_pao1.tsv")
# El catálogo VERSIONADO del paso 1, el mismo con que `puente.py` expandió los
# blancos que son operón. Nunca `operones_base.tsv` (`operones.RUTA_BASE`):
# lleva datos de BioCyc, cuya licencia restringe redistribuirlos, y este
# paquete está hecho para salir de la máquina.
RUTA_CATALOGO = _operones.RUTA_POR_OMISION

RED = "red.tsv"
EVIDENCIAS = "red_evidencias.tsv"
INFORME = "red_informe.json"
PARES = "pares.jsonl"
META = "predicciones_meta.json"
ESTADO = "estado.json"
NODOS = "nodos.tsv"
GRAPHML = "red.graphml"
MANIFIESTO = "manifiesto.json"

# Qué correr cuando falta cada entrada: «falta red.tsv» a secas no le dice a
# nadie qué paso le toca.
_QUIEN_ESCRIBE = {
    RED: "el paso «red» del flujo (etapa2/red.py)",
    EVIDENCIAS: "el paso «red» del flujo (etapa2/red.py)",
    INFORME: "el paso «red» del flujo (etapa2/red.py)",
    PARES: "el paso «pares» del flujo (python -m grn_verificacion.cli pares)",
    META: "el paso «biobert» del flujo (python -m grn_verificacion.cli "
          "biobert)",
}

# Lo que se toma de cada par. `tf` y `target` son sus formas de presentación:
# con ellas se comprueba que el par es el de la fila que lo cita.
CLAVES_PAR = ("tf_id", "target_id", "tf_locus", "target_locus", "tf",
              "target")

COLUMNAS_NODOS = ["id", "simbolo", "locus", "tipo", "es_tf", "operones",
                  "producto", "grado_salida", "grado_entrada"]
TIPOS = ("gen", "operon", "sin_locus")

# Los tipos de GraphML de cada atributo. Un visor que respeta `attr.type`
# ordena y filtra `n_evidencias` como número, no como texto.
_TIPOS_NODO = {"es_tf": "boolean", "grado_salida": "int",
               "grado_entrada": "int"}
_TIPOS_ARISTA = {"conflicto": "boolean", "autorregulacion": "boolean",
                 "n_evidencias": "int", "n_activates": "int",
                 "n_represses": "int", "n_regulates": "int",
                 "n_articulos": "int", "confianza": "double"}
ATRIBUTOS_NODO = [(c, _TIPOS_NODO.get(c, "string")) for c in COLUMNAS_NODOS
                  if c != "id"]
# Todas las columnas de `red.tsv` menos la oración. `tf` y `blanco` van
# también: son la llave para volver a `red_evidencias.tsv`, que está escrita
# con las formas de presentación y no con los ids canónicos.
FUERA_DEL_GRAFO = ("oracion_representativa",)
ATRIBUTOS_ARISTA = [(c, _TIPOS_ARISTA.get(c, "string")) for c in COLUMNAS_RED
                    if c not in FUERA_DEL_GRAFO]

# Lo que se copia de `red_informe.json` al manifiesto. Las rutas del informe
# no: son absolutas y dicen en qué máquina y bajo qué usuario se corrió.
PARAMETROS_INFORME = ("umbrales", "fuente_umbrales", "calibrado_en",
                      "mayoria", "max_por_par", "min_evidencias",
                      "min_articulos", "sin_pies", "sin_introduccion",
                      "incluir_autorregulacion")
CONTEOS_INFORME = ("n_predicciones", "descartes", "n_supervivientes",
                   "n_evidencias_distintas", "n_evidencias_colapsadas",
                   "n_evidencias_tras_tope", "n_aristas",
                   "n_aristas_descartadas_por_minimos", "n_tfs", "n_blancos",
                   "n_articulos", "reparto_signos", "n_conflictos",
                   "n_aristas_sin_confianza")

NOTAS = collections.OrderedDict([
    ("kb", "Sin cruce con una base de conocimiento: la red sale solo del "
           "texto. Compararla con la base curada es el diff del paso 3, y "
           "queda para cuando existan sus reglas."),
    ("go", "Los términos GO de cada gen salen de UniProt y piden red; quedan "
           "para otro día. Hasta entonces, la columna «producto» del "
           "diccionario es la única anotación funcional de un nodo."),
    ("colisiones", "Filas de red.tsv que juntan dos pares canónicos "
                   "distintos. No entran al grafo: sus conteos y su signo no "
                   "son de ninguno de los dos."),
    ("unificados", "Ids del mismo locus que el texto nombró de dos modos "
                   "(por símbolo y por locus): van a un solo nodo, el del "
                   "símbolo. Sus filas de red.tsv quedan como aristas "
                   "paralelas, porque sumarlas sería volver a agregar."),
    ("pmids", "En red.graphml los PMIDs de una arista van unidos con «;»; "
              "en red.tsv, con «|»."),
    ("red_informe", "red_informe.json va tal como lo escribe etapa2/red.py, "
                    "con las rutas absolutas de la máquina donde corrió; "
                    "este manifiesto no las repite."),
])

_NS_GRAPHML = "http://graphml.graphdrawing.org/xmlns"
_CABECERA_GRAPHML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<graphml xmlns="%s"'
    ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
    ' xsi:schemaLocation="%s %s/1.0/graphml.xsd">\n'
    % (_NS_GRAPHML, _NS_GRAPHML, _NS_GRAPHML))

# Lo que XML 1.0 admite (§2.2): tabulador, salto de línea, retorno de carro y
# de U+0020 en adelante, salvo los sustitutos y U+FFFE/U+FFFF. Los rangos se
# arman con chr() y no se escriben como caracteres: U+E000 no se ve en ningún
# editor, y un rango que no se ve no se puede revisar.
_ADMITIDOS_EN_XML = ((0x09, 0x09), (0x0A, 0x0A), (0x0D, 0x0D),
                     (0x20, 0xD7FF), (0xE000, 0xFFFD), (0x10000, 0x10FFFF))
_FUERA_DE_XML = re.compile("[^%s]" % "".join(
    "%s-%s" % (chr(desde), chr(hasta)) for desde, hasta in _ADMITIDOS_EN_XML))

_UNIDAD = re.compile(r"^[A-Za-z]:[\\/]")


class ErrorPaquete(RuntimeError):
    """Falta una entrada, o las entradas no son de la misma corrida."""


def _nada(_m):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------- lectura

def leer_tsv(ruta, columnas):
    """Las filas de un TSV como dicts, con el encabezado exacto de `columnas`.

    Se parte por tabulador y sin el módulo csv, con el criterio de
    `etapa2/lexico.py`: `red.py` garantiza que ninguna celda lleva tabulador
    ni salto de línea (`celda()`), y csv trataría como entrecomillada una celda
    que empezara por comilla doble. Una fila con otro número de campos se
    rechaza: es un archivo cortado o editado a mano, y leerla pondría el signo
    en la columna de los conteos.
    """
    nombre = os.path.basename(ruta)
    columnas = list(columnas)
    filas = []
    with io.open(ruta, encoding="utf-8-sig") as f:
        cabecera = f.readline().rstrip("\n").rstrip("\r").split("\t")
        if cabecera != columnas:
            raise ErrorPaquete("%s: el encabezado es %r y el contrato pide %r."
                               % (nombre, cabecera, columnas))
        for numero, linea in enumerate(f, 2):
            linea = linea.rstrip("\n").rstrip("\r")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            if len(partes) != len(columnas):
                raise ErrorPaquete("%s línea %d: %d campos, y el encabezado "
                                   "tiene %d." % (nombre, numero, len(partes),
                                                  len(columnas)))
            filas.append(dict(zip(columnas, partes)))
    return filas


def _leer_json(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        try:
            datos = json.load(f)
        except ValueError as e:
            raise ErrorPaquete("%s ilegible: %s" % (os.path.basename(ruta), e))
    if not isinstance(datos, dict):
        raise ErrorPaquete("%s no es un objeto JSON." % os.path.basename(ruta))
    return datos


def _leer_estado(carpeta):
    """`estado.json` de la carpeta, o {} si no está o no se lee.

    Solo aporta la corrida del bronce, y un manifiesto que dice «no se sabe»
    es mejor que ningún paquete: el CLI también se corre sobre carpetas que no
    armó el flujo.
    """
    ruta = os.path.join(carpeta, ESTADO)
    if not os.path.isfile(ruta):
        return {}
    try:
        with io.open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def pares_por_id(ruta_pares, ids):
    """{id_par: {tf_id, target_id, tf_locus, target_locus, tf, target}}.

    Solo de los `ids` pedidos, y leyendo `pares.jsonl` línea por línea: el de
    la corrida 4 pesa 78 MB y la red cita 46 mil de sus 73 mil pares, así que
    cargarlo entero para tirar un tercio no tiene caso. Un `id_par` pedido que
    no está, o que viene sin las claves que escribe
    `grn_verificacion/puente.py`, es error: el `pares.jsonl` de
    `etapa2/extraer_pares.py` no trae `tf_id`, y sin él no hay con qué
    unificar los nodos.
    """
    pedidos = set(ids)
    salida = {}
    with io.open(ruta_pares, encoding="utf-8") as f:
        for numero, linea in enumerate(f, 1):
            if not linea.strip():
                continue
            try:
                par = json.loads(linea)
            except ValueError as e:
                raise ErrorPaquete("%s línea %d ilegible: %s"
                                   % (PARES, numero, e))
            id_par = par.get("id_par")
            if id_par not in pedidos:
                continue
            if id_par in salida:
                raise ErrorPaquete("id_par repetido en %s: %s." % (PARES, id_par))
            faltan = [c for c in CLAVES_PAR if c not in par]
            if faltan:
                raise ErrorPaquete(
                    "%s línea %d: al par %s le faltan %s. Ese archivo no lo "
                    "escribió grn_verificacion.cli pares, y sin los ids "
                    "canónicos no se pueden unificar los nodos."
                    % (PARES, numero, id_par, ", ".join(faltan)))
            if (not par["tf_id"] or not par["target_id"]
                    or not isinstance(par["tf_locus"], list)
                    or not isinstance(par["target_locus"], list)):
                raise ErrorPaquete("%s línea %d: el par %s no trae sus ids "
                                   "canónicos o sus locus como lista."
                                   % (PARES, numero, id_par))
            salida[id_par] = dict((c, par[c]) for c in CLAVES_PAR)
    ausentes = sorted(pedidos - set(salida))
    if ausentes:
        raise ErrorPaquete(
            "%d evidencias citan un id_par que %s no tiene (el primero es %s): "
            "la red y los pares no son de la misma corrida."
            % (len(ausentes), PARES, ausentes[0]))
    return salida


def cargar_genes(ruta=RUTA_GENES):
    """{locus: {simbolo, producto, es_tf}} desde `genes_pao1.tsv`.

    Las entradas manuales sin locus (complejos y familias, como IHF o PrrF)
    van por su símbolo, que es su id canónico en `lexico.py`: son nodos de la
    red, y sin esto saldrían sin producto y sin la marca de TF.
    """
    genes = {}
    for fila in leer_tsv(ruta, COLUMNAS_GENES):
        locus = fila["locus_tag"].strip()
        simbolo = fila["simbolo"].strip()
        clave = locus or simbolo
        if not clave:
            continue
        genes[clave] = {"simbolo": simbolo,
                        "producto": fila["producto"].strip(),
                        "es_tf": fila["es_tf"].strip().lower() == "true"}
    return genes


def operones_por_locus(ruta=RUTA_CATALOGO):
    """{locus: [operones que lo contienen]} del catálogo versionado del paso 1.

    La tabla se lee con `grn_bronce.operones.leer` y se expande con
    `desde_filas`, que son el único lector y la única expansión operón → genes
    del proyecto: con una tercera, el paquete y el bronce podrían decir que un
    gen está en operones distintos. Los nombres van con la escritura de la
    tabla.
    """
    try:
        filas = _operones.leer(ruta)
    except ValueError as e:
        raise ErrorPaquete(str(e))
    _, locus_de = _operones.desde_filas(filas)
    nombre_de = {}
    for fila in filas:
        nombre = (fila.get("operon") or "").strip()
        if nombre:
            nombre_de.setdefault(_operones.clave(nombre), nombre)
    por_locus = collections.defaultdict(set)
    for clave, locus in locus_de.items():
        for lt in locus:
            por_locus[lt].add(nombre_de[clave])
    return dict((lt, sorted(nombres)) for lt, nombres in por_locus.items())


# ------------------------------------------------------------- la red

def _atributos_arista(fila):
    """Los escalares de una fila de `red.tsv`, como texto para el GraphML.

    Se validan aquí, antes de escribir nada: un conteo que no es entero o un
    booleano que no es «true» o «false» quiere decir que el archivo no lo
    escribió `red.py`, y un GraphML que lo declarara `int` no se podría leer.
    La confianza vacía queda en None (ver `escribir_graphml`).
    """
    arista = "%s -> %s" % (fila["tf"], fila["blanco"])
    valores = collections.OrderedDict()
    for columna, tipo in ATRIBUTOS_ARISTA:
        texto = fila[columna]
        if columna == "pmids":
            texto = ";".join(p for p in texto.split("|") if p)
        elif tipo == "int":
            try:
                texto = str(int(texto))
            except ValueError:
                raise ErrorPaquete("%s, arista %s: %s = %r no es un entero."
                                   % (RED, arista, columna, texto))
        elif tipo == "double":
            if texto == "":
                texto = None
            else:
                try:
                    finito = math.isfinite(float(texto))
                except ValueError:
                    finito = False
                if not finito:
                    raise ErrorPaquete("%s, arista %s: %s = %r no es un "
                                       "número." % (RED, arista, columna,
                                                    texto))
        elif tipo == "boolean" and texto not in ("true", "false"):
            raise ErrorPaquete("%s, arista %s: %s = %r no es true ni false."
                               % (RED, arista, columna, texto))
        valores[columna] = texto
    return valores


def aristas_canonicas(filas_red, evidencias, por_id):
    """Las filas de `red.tsv` sobre ids canónicos: `(aristas, colisiones)`.

    Cada arista es un dict con `fuente` y `destino` (los ids canónicos),
    `locus_fuente` y `locus_destino` (los de `pares.jsonl`) y `atributos` (ver
    `_atributos_arista`), en orden de (fuente, destino). Una colisión es una
    fila que junta dos pares canónicos distintos; no entra en `aristas`, y
    trae cuántas evidencias aporta cada par (ver el docstring del módulo).
    """
    citas = collections.OrderedDict()
    for e in evidencias:
        citas.setdefault((e["tf"], e["blanco"]), []).append(e["id_par"])
    vistas = set()
    aristas, colisiones = [], []
    for fila in filas_red:
        clave = (fila["tf"], fila["blanco"])
        if clave in vistas:
            # Las dos copias se llevarían las mismas evidencias y el GraphML
            # tendría dos aristas paralelas, que cada visor lee a su modo.
            raise ErrorPaquete("La arista %s -> %s está dos veces en %s, y "
                               "red.py escribe una fila por par."
                               % (clave[0], clave[1], RED))
        vistas.add(clave)
        atributos = _atributos_arista(fila)
        ids = citas.get(clave, [])
        if len(ids) != int(atributos["n_evidencias"]):
            raise ErrorPaquete(
                "La arista %s -> %s declara %s evidencias en %s y %s trae %d: "
                "las dos tablas no son de la misma corrida de red.py."
                % (clave[0], clave[1], atributos["n_evidencias"], RED,
                   EVIDENCIAS, len(ids)))
        canonicos = collections.Counter()
        locus = {}
        for id_par in ids:
            par = por_id[id_par]
            if (par["tf"], par["target"]) != clave:
                raise ErrorPaquete(
                    "El par %s es %s -> %s en %s y %s -> %s en %s: no son de "
                    "la misma corrida." % (id_par, par["tf"], par["target"],
                                          PARES, clave[0], clave[1],
                                          EVIDENCIAS))
            canonico = (par["tf_id"], par["target_id"])
            canonicos[canonico] += 1
            locus.setdefault(canonico, (par["tf_locus"], par["target_locus"]))
        if len(canonicos) > 1:
            colisiones.append(collections.OrderedDict([
                ("tf", clave[0]), ("blanco", clave[1]),
                ("pares", [collections.OrderedDict([
                    ("tf_id", tf_id), ("target_id", target_id),
                    ("n_evidencias", n)])
                    for (tf_id, target_id), n in sorted(canonicos.items())]),
            ]))
            continue
        canonico = list(canonicos)[0]
        aristas.append({"fuente": canonico[0], "destino": canonico[1],
                        "locus_fuente": sorted(set(locus[canonico][0])),
                        "locus_destino": sorted(set(locus[canonico][1])),
                        "atributos": atributos})
    huerfanas = [c for c in citas if c not in vistas]
    if huerfanas:
        raise ErrorPaquete(
            "%s trae evidencias de %d aristas que %s no tiene (la primera, "
            "%s -> %s): las dos tablas no son de la misma corrida de red.py."
            % (EVIDENCIAS, len(huerfanas), RED, huerfanas[0][0],
               huerfanas[0][1]))
    aristas.sort(key=lambda a: (a["fuente"], a["destino"]))
    colisiones.sort(key=lambda c: (c["tf"], c["blanco"]))
    return aristas, colisiones


def unificar_por_locus(aristas, por_locus):
    """Las aristas con un solo id por gen: `(aristas, unificados)`.

    `lexico.py` da a cada entrada del diccionario su id canónico, pero el
    texto también nombra un gen por su locus («PA1430» y no «lasR»), y ese par
    llega con otro `tf_id` y el mismo `tf_locus`. Dos nodos para un gen es el
    defecto que este paquete existe para quitar, así que todo extremo con un
    solo locus se reescribe al id que represente a ese locus: el que no es el
    locus mismo y, entre varios, el menor, para que el resultado no dependa
    del orden de las filas. Un operón no se toca aunque el catálogo le dé un
    solo locus: es otra entidad que su gen.

    Dos filas de `red.tsv` pueden quedar entonces sobre el mismo par de nodos.
    Se quedan las dos, como aristas paralelas: cada una es el agregado de
    `red.py` para su forma, y sumarlas sería volver a agregar. `unificados` es
    [{"id", "alias"}] de cada id que absorbió a otros, en orden.
    """
    conocidos = set(_operones.clave(n) for nombres in por_locus.values()
                    for n in nombres)

    def unico(id_nodo, locus):
        locus = sorted(set(locus))
        if len(locus) == 1 and _operones.clave(id_nodo) not in conocidos:
            return locus[0]
        return None

    ids_de = collections.defaultdict(set)
    for a in aristas:
        for id_nodo, locus in ((a["fuente"], a["locus_fuente"]),
                               (a["destino"], a["locus_destino"])):
            lt = unico(id_nodo, locus)
            if lt:
                ids_de[lt].add(id_nodo)
    representante = dict(
        (lt, sorted(ids, key=lambda i, lt=lt: (i == lt, i))[0])
        for lt, ids in ids_de.items())
    salida = []
    for a in aristas:
        a = dict(a)
        for lado in ("fuente", "destino"):
            lt = unico(a[lado], a["locus_" + lado])
            if lt:
                a[lado] = representante[lt]
        salida.append(a)
    salida.sort(key=lambda a: (a["fuente"], a["destino"],
                               a["atributos"]["tf"], a["atributos"]["blanco"]))
    unificados = [collections.OrderedDict([
        ("id", representante[lt]),
        ("alias", sorted(ids - set([representante[lt]])))])
        for lt, ids in ids_de.items() if len(ids) > 1]
    unificados.sort(key=lambda u: u["id"])
    return salida, unificados


def armar_nodos(aristas, genes, por_locus):
    """Un nodo por id canónico, con las columnas de COLUMNAS_NODOS, por id.

    - `locus`: los que `puente.py` resolvió con el diccionario y el catálogo
      (llegan en `pares.jsonl`), unidos con «|».
    - `tipo`: `operon` si el catálogo lo conoce por nombre o trae más de un
      locus; `gen` con uno; `sin_locus` sin ninguno, que son las entradas
      manuales del diccionario (complejos y familias como IHF) y los operones
      que el texto abrevia y la tabla no conoce (punto 34 del PLAN).
    - `simbolo`, `producto` y `es_tf`: los del diccionario, por el locus del
      gen o, sin locus propio, por su símbolo. Un operón no es TF, como en
      `lexico.py`, y su símbolo es su nombre.
    - `operones`: los del catálogo que contienen alguno de sus locus; a un
      operón lo incluye a él.
    - `grado_salida` y `grado_entrada`: cuántas aristas del paquete salen y
      llegan; una autorregulación cuenta en las dos.
    """
    locus = collections.defaultdict(set)
    salida = collections.Counter()
    entrada = collections.Counter()
    for a in aristas:
        locus[a["fuente"]].update(a["locus_fuente"])
        locus[a["destino"]].update(a["locus_destino"])
        salida[a["fuente"]] += 1
        entrada[a["destino"]] += 1
    conocidos = set(_operones.clave(n) for nombres in por_locus.values()
                    for n in nombres)
    nodos = []
    for id_nodo in sorted(locus):
        suyos = sorted(locus[id_nodo])
        if len(suyos) > 1 or _operones.clave(id_nodo) in conocidos:
            tipo = "operon"
        elif suyos:
            tipo = "gen"
        else:
            tipo = "sin_locus"
        if tipo == "gen":
            info = genes.get(suyos[0])
            simbolo = info["simbolo"] if info else ""
        else:
            info = genes.get(id_nodo) if tipo == "sin_locus" else None
            simbolo = id_nodo
        nodos.append(collections.OrderedDict([
            ("id", id_nodo),
            ("simbolo", simbolo),
            ("locus", "|".join(suyos)),
            ("tipo", tipo),
            ("es_tf", bool(info and info["es_tf"])),
            ("operones", "|".join(sorted(set(
                n for lt in suyos for n in por_locus.get(lt, ()))))),
            ("producto", _red.celda(info["producto"]) if info else ""),
            ("grado_salida", salida[id_nodo]),
            ("grado_entrada", entrada[id_nodo]),
        ]))
    return nodos


# ------------------------------------------------------------- escritura

def limpiar_xml(texto):
    """`texto` sin lo que XML 1.0 no admite.

    ElementTree escapa `&`, `<` y `>`, pero escribe tal cual un `\\x0c` o un
    `\\x01` que se haya colado desde un PDF o un XML de PMC, y con uno solo el
    GraphML entero es ilegible para cualquier lector, no solo esa celda.
    """
    return _FUERA_DE_XML.sub("", texto)


def _texto(valor):
    if isinstance(valor, bool):
        return _red.texto_bool(valor)
    return str(valor)


def escribir_nodos(ruta, nodos):
    """`nodos.tsv` en `ruta` tal cual; el temporal lo pone quien llama."""
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNAS_NODOS) + "\n")
        for nodo in nodos:
            f.write("\t".join(_red.celda(_texto(nodo[c]))
                              for c in COLUMNAS_NODOS) + "\n")


def _dato(elemento, clave, valor):
    if valor is None or valor == "":
        return
    ET.SubElement(elemento, "data", {"key": clave}).text = limpiar_xml(
        _texto(valor))


def escribir_graphml(ruta, nodos, aristas):
    """La red como GraphML dirigido, en `ruta` tal cual.

    Cada elemento se serializa con ElementTree, que escapa lo que hay que
    escapar, y va en su propia línea: sin `ET.indent`, que no existe en 3.8, el
    archivo sigue siendo legible y un diff entre dos corridas dice qué arista
    cambió. Los nodos van por id canónico y las aristas en el orden en que
    llegan, que `unificar_por_locus` deja fijo: dos corridas sobre las mismas
    entradas dan los mismos bytes.

    Un valor vacío no se escribe: en GraphML un dato ausente es «sin valor»,
    que es lo que dice la celda vacía del TSV (la `confianza` de un conflicto
    degradado a `regulates` sin un voto `regulates`). Escribir 0 inventaría una
    confianza.
    """
    ids = set()
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(_CABECERA_GRAPHML)
        for para, prefijo, atributos in (("node", "nodo_", ATRIBUTOS_NODO),
                                         ("edge", "arista_", ATRIBUTOS_ARISTA)):
            for nombre, tipo in atributos:
                clave = ET.Element("key", {"id": prefijo + nombre, "for": para,
                                           "attr.name": nombre,
                                           "attr.type": tipo})
                f.write("  %s\n" % ET.tostring(clave, encoding="unicode"))
        f.write('  <graph id="red" edgedefault="directed">\n')
        for nodo in nodos:
            id_xml = limpiar_xml(nodo["id"])
            if not id_xml or id_xml in ids:
                raise ErrorPaquete("El nodo %r queda vacío o repetido al "
                                   "quitarle lo que XML no admite."
                                   % nodo["id"])
            ids.add(id_xml)
            elemento = ET.Element("node", {"id": id_xml})
            for nombre, _tipo in ATRIBUTOS_NODO:
                _dato(elemento, "nodo_" + nombre, nodo[nombre])
            f.write("    %s\n" % ET.tostring(elemento, encoding="unicode"))
        for i, arista in enumerate(aristas):
            fuente = limpiar_xml(arista["fuente"])
            destino = limpiar_xml(arista["destino"])
            if fuente not in ids or destino not in ids:
                raise ErrorPaquete("La arista %s -> %s tiene un extremo que no "
                                   "es nodo." % (arista["fuente"],
                                                 arista["destino"]))
            elemento = ET.Element("edge", {"id": "e%d" % i, "source": fuente,
                                           "target": destino})
            for nombre, _tipo in ATRIBUTOS_ARISTA:
                _dato(elemento, "arista_" + nombre,
                      arista["atributos"][nombre])
            f.write("    %s\n" % ET.tostring(elemento, encoding="unicode"))
        f.write("  </graph>\n</graphml>\n")


def _escribir_json(ruta, objeto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)
        f.write("\n")


def sha256(ruta):
    """El sha256 entero del archivo, por bloques.

    Entero y no la huella recortada de `procedencia`: quien recibe el paquete
    lo comprueba con `sha256sum` o `Get-FileHash`, que dan los 64 caracteres.
    """
    h = hashlib.sha256()
    with io.open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


# ------------------------------------------------------------- manifiesto

def _ultimo_componente(ruta):
    """El último componente de una ruta, escrita en Windows o en POSIX.

    `os.path.basename` solo entiende los separadores de la máquina donde
    corre: en Linux, la ruta de un meta escrito en Windows salía entera, con
    el usuario adentro.
    """
    partes = [p for p in re.split(r"[\\/]+", str(ruta)) if p]
    return partes[-1] if partes else ""


def _sin_directorio(valor):
    if isinstance(valor, str) and re.search(r"[\\/]", valor):
        return _ultimo_componente(valor)
    return valor


def rutas_absolutas(objeto):
    """Las cadenas de `objeto`, claves incluidas, que parecen ruta absoluta.

    Se comprueba sobre el manifiesto ya armado y no campo por campo, para que
    un campo que se agregue mañana no se salte la regla: `red_informe.json` y
    `predicciones_meta.json` traen rutas absolutas, y copiar un campo de más
    bastaría para que viajaran.
    """
    halladas = []
    if isinstance(objeto, dict):
        for k, v in objeto.items():
            halladas += rutas_absolutas(k) + rutas_absolutas(v)
    elif isinstance(objeto, (list, tuple)):
        for v in objeto:
            halladas += rutas_absolutas(v)
    elif isinstance(objeto, str):
        if (objeto.startswith(("/", "\\")) or _UNIDAD.match(objeto)
                or ":\\" in objeto):
            halladas.append(objeto)
    return halladas


def _modelo(meta):
    """El modelo por el nombre de su carpeta, sus huellas y su orden de
    etiquetas. Su ruta no: dice en qué máquina se corrió y no distingue dos
    checkpoints de la misma receta, que es lo que hacen las huellas de los
    pesos."""
    nombre = _ultimo_componente(meta["modelo"]) if meta.get("modelo") else None
    return collections.OrderedDict([
        ("nombre", nombre),
        ("sha1_config", meta.get("sha1_config")),
        ("huellas_modelo", meta.get("huellas_modelo")),
        ("id2label", meta.get("id2label")),
        ("max_length", meta.get("max_length")),
        ("huella_pares", meta.get("huella_pares")),
        ("huella_predicciones", meta.get("huella_predicciones")),
    ])


def _de_la_red(informe):
    red = collections.OrderedDict()
    for clave in PARAMETROS_INFORME:
        red[clave] = _sin_directorio(informe.get(clave))
    red["conteos"] = collections.OrderedDict(
        (c, informe.get(c)) for c in CONTEOS_INFORME)
    huellas = collections.OrderedDict()
    for nombre, sello in sorted((informe.get("huellas") or {}).items()):
        if isinstance(sello, dict):
            huellas[nombre] = collections.OrderedDict([
                ("huella", sello.get("huella")), ("bytes", sello.get("bytes"))])
    red["huellas"] = huellas
    return red


def armar_manifiesto(carpeta, estado, informe, meta, archivos, recursos,
                     grafo, colisiones, unificados=()):
    """El manifiesto del paquete, como dict listo para `json.dump`.

    `archivos` es [(nombre publicado, ruta de donde medirlo)]: lo que todavía
    está en su temporal se mide ahí, como `procedencia.sellar_como`.
    `recursos` es [(clave, ruta)] del diccionario y del catálogo, que se
    miden sin CRLF, como en `pares_informe.json`, para que un checkout de
    Windows no parezca otro recurso.
    """
    manifiesto = collections.OrderedDict()
    manifiesto["version"] = VERSION
    manifiesto["corrida_bronce"] = estado.get("corrida_bronce")
    manifiesto["carpeta"] = os.path.basename(
        os.path.normpath(os.path.abspath(carpeta)))
    manifiesto["generado"] = _ahora()
    manifiesto["modelo"] = _modelo(meta)
    manifiesto["red"] = _de_la_red(informe)
    manifiesto["recursos"] = collections.OrderedDict(
        (clave, collections.OrderedDict([
            ("archivo", os.path.basename(ruta)),
            ("huella", procedencia.huella_texto(ruta))]))
        for clave, ruta in recursos)
    manifiesto["archivos"] = collections.OrderedDict(
        (nombre, collections.OrderedDict([("sha256", sha256(ruta)),
                                          ("bytes", os.path.getsize(ruta))]))
        for nombre, ruta in archivos)
    manifiesto["grafo"] = grafo
    manifiesto["colisiones"] = colisiones
    manifiesto["unificados"] = list(unificados)
    manifiesto["kb"] = None
    manifiesto["go"] = "pendiente"
    manifiesto["notas"] = collections.OrderedDict(NOTAS)
    return manifiesto


# ------------------------------------------------------------- empaquetar

def _exigir_misma_corrida(informe, meta, rutas, log=_nada):
    """Que `pares.jsonl` y `red.tsv` sean los que sella el informe, y que el
    meta sea el de las predicciones de esa red. Ver el docstring del módulo."""
    sello = informe.get("huellas") or {}
    if not sello:
        log("AVISO: %s no trae huellas: no se puede comprobar que %s y %s "
            "sean los de esa red." % (INFORME, PARES, RED))
    else:
        problemas, sin_sellar = procedencia.verificar(
            sello, {"pares": rutas[PARES], "red": rutas[RED]})
        if problemas:
            raise ErrorPaquete("Las entradas no son de la misma corrida: %s. "
                               "Vuelve a correr el paso «red»."
                               % "; ".join(problemas))
        if sin_sellar:
            log("AVISO: %s no trae huella de %s; esa parte no queda "
                "comprobada." % (INFORME, ", ".join(sorted(sin_sellar))))
    for clave, nombre in (("huella_pares", "pares"),
                          ("huella_predicciones", "predicciones")):
        sellada = (sello.get(nombre) or {}).get("huella")
        dicha = meta.get(clave)
        if sellada and dicha and sellada != dicha:
            raise ErrorPaquete(
                "%s describe otras predicciones que las de esta red (%s %s, "
                "y %s sella %s): el manifiesto le atribuiría la red a otro "
                "modelo. Vuelve a correr los pasos «biobert» y «red»."
                % (META, clave, dicha, INFORME, sellada))


def empaquetar(carpeta, log=_nada, genes=None, catalogo=None):
    """Arma el paquete de la red de `carpeta` y devuelve su manifiesto.

    `genes` y `catalogo` existen para las pruebas; el flujo usa los recursos
    versionados. Si falta una entrada, o las entradas no son de la misma
    corrida, lanza ErrorPaquete sin haber escrito nada. Los tres archivos se
    escriben a sus temporales y se publican juntos al final, el manifiesto el
    último: un paquete que se corta a medias no deja nodos nuevos junto al
    manifiesto viejo, cuyos sha256 hablarían de otros archivos.
    """
    genes = genes or RUTA_GENES
    catalogo = catalogo or RUTA_CATALOGO
    nombre = os.path.basename(os.path.normpath(os.path.abspath(carpeta)))
    rutas = dict((n, os.path.join(carpeta, n))
                 for n in (RED, EVIDENCIAS, INFORME, PARES, META))
    for n in (RED, EVIDENCIAS, INFORME, PARES, META):
        if not os.path.isfile(rutas[n]):
            raise ErrorPaquete("Falta %s en %s. Lo escribe %s."
                               % (n, carpeta, _QUIEN_ESCRIBE[n]))
    for ruta, que in ((genes, "el diccionario"),
                      (catalogo, "el catálogo de operones del paso 1")):
        if not os.path.isfile(ruta):
            raise ErrorPaquete("Falta %s: %s." % (que, ruta))

    log("Paquete de la red de %s" % nombre)
    informe = _leer_json(rutas[INFORME])
    meta = _leer_json(rutas[META])
    _exigir_misma_corrida(informe, meta, rutas, log)
    filas_red = leer_tsv(rutas[RED], COLUMNAS_RED)
    evidencias = leer_tsv(rutas[EVIDENCIAS], COLUMNAS_EVIDENCIAS)
    log("  %s: %d aristas; %s: %d evidencias" % (RED, len(filas_red),
                                                 EVIDENCIAS, len(evidencias)))
    por_id = pares_por_id(rutas[PARES], set(e["id_par"] for e in evidencias))
    aristas, colisiones = aristas_canonicas(filas_red, evidencias, por_id)
    por_locus = operones_por_locus(catalogo)
    aristas, unificados = unificar_por_locus(aristas, por_locus)
    pares_de_nodos = collections.Counter(
        (a["fuente"], a["destino"]) for a in aristas)
    paralelas = sum(n for n in pares_de_nodos.values() if n > 1)
    log("  %d aristas sobre ids canónicos; filas con colisión, fuera del "
        "grafo: %d" % (len(aristas), len(colisiones)))
    if unificados:
        log("  %d ids absorbieron a otro del mismo locus; %d aristas quedaron "
            "paralelas" % (len(unificados), paralelas))
    for c in colisiones[:5]:
        log("    %s -> %s junta %s" % (c["tf"], c["blanco"], ", ".join(
            "%s -> %s" % (p["tf_id"], p["target_id"]) for p in c["pares"])))
    nodos = armar_nodos(aristas, cargar_genes(genes), por_locus)
    por_tipo = collections.Counter(n["tipo"] for n in nodos)
    log("  %d nodos (%s)" % (len(nodos), ", ".join(
        "%s %d" % (t, por_tipo.get(t, 0)) for t in TIPOS)))

    destinos = [(n, os.path.join(carpeta, n))
                for n in (NODOS, GRAPHML, MANIFIESTO)]
    tmp = dict((n, r + ".tmp") for n, r in destinos)
    try:
        escribir_nodos(tmp[NODOS], nodos)
        escribir_graphml(tmp[GRAPHML], nodos, aristas)
        grafo = collections.OrderedDict([
            ("n_filas_red", len(filas_red)),
            ("n_aristas", len(aristas)),
            ("n_colisiones", len(colisiones)),
            ("n_aristas_paralelas", paralelas),
            ("n_nodos", len(nodos)),
            ("nodos_por_tipo", collections.OrderedDict(
                (t, por_tipo.get(t, 0)) for t in TIPOS)),
            ("n_reguladores", sum(1 for n in nodos if n["grado_salida"])),
            ("n_blancos", sum(1 for n in nodos if n["grado_entrada"])),
        ])
        manifiesto = armar_manifiesto(
            carpeta, _leer_estado(carpeta), informe, meta,
            [(RED, rutas[RED]), (EVIDENCIAS, rutas[EVIDENCIAS]),
             (INFORME, rutas[INFORME]), (NODOS, tmp[NODOS]),
             (GRAPHML, tmp[GRAPHML])],
            [("diccionario", genes), ("catalogo_operones", catalogo)],
            grafo, colisiones, unificados)
        halladas = rutas_absolutas(manifiesto)
        if halladas:
            raise ErrorPaquete("El manifiesto llevaría %d rutas absolutas (la "
                               "primera, %s), y se publica junto a la red."
                               % (len(halladas), halladas[0]))
        _escribir_json(tmp[MANIFIESTO], manifiesto)
    except BaseException:
        for ruta in tmp.values():
            try:
                borrar(ruta)
            except OSError:
                pass
        raise
    for n, ruta in destinos:
        reemplazar(tmp[n], ruta)
    log("%s, %s y %s -> %s" % (NODOS, GRAPHML, MANIFIESTO, nombre))
    return manifiesto
