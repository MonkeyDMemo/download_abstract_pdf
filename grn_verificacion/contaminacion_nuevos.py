"""¿Ya pasó por el pipeline alguno de estos artículos? Los cruces de una lista
de artículos nuevos con lo que vieron el modelo, el bronce y la evaluación.

    python -m grn_verificacion.cli verificar-contaminacion \
        (--lista ARCHIVO | --consulta NOMBRE) [--corpus NOMBRE | --sin-corpus] \
        [--reservas TSV ...] [--muestra DIR ...] [--juzgadas CSV] \
        [--particion DIR ...] [--base XLSX [--hoja H]] \
        [--datos D] [--db RUTA] [--json J]

Para qué
========
La prueba con abstracts nuevos mide al pipeline sobre artículos que nadie le
enseñó ni le juzgó. Vale solo si de verdad son nuevos: uno que ya estaba en el
corpus de la corrida 4, en la partición con que se entrenó un modelo o en una
muestra de evaluación hace que la prueba mida en parte lo ya visto, con la
misma etiqueta de «nuevo» y la misma pinta de correcta. Esto se corre antes de
la prueba, y su salida es lo que se cita para decir que la lista no cruza.

La lista
========
`--lista` es un archivo con una columna `pmid` (CSV, o TSV si el encabezado
lleva tabuladores; la exportación de `cli.py export` sirve tal cual, y su
columna `doi` se usa) o con un PMID por línea. `--consulta` la toma de los
documentos ligados a una consulta de la base del paso 0, con su DOI. Las
líneas vacías y las que empiezan con `#` no cuentan. Un PMID que no es número
detiene la lectura: ignorarlo dejaría fuera justo el que podía cruzar. Por lo
mismo la detienen, en un archivo con encabezado, una fila sin PMID (una
columna corrida) y una que empieza con `#` pero trae un PMID (un título).

Las fuentes
===========
- `corpus`: el de la corrida 4 (`--corpus`, por omisión v0-agosto), con sus
  DOIs, de la base del paso 0 abierta en solo lectura. `--sin-corpus` lo salta,
  para correr donde esa base no está (el servidor).
- `reservas`: los PMIDs de archivos con el formato de `reservas.tsv`
  (`entrenamiento.leer_reservas`). Sus líneas de oración se leen y no se usan:
  una oración no es un artículo.
- `muestra`: la columna `pmid` de la `llave.csv` de cada carpeta de sorteo.
  Una fila sin PMID la detiene, como al excluir una muestra en `muestra`.
- `juzgadas`: la columna `pmid` de la muestra de 50 juzgada
  (`etapa2/evaluacion/muestra_precision_50.csv`, por omisión).
- `particion`: train, dev y test de un modelo (`entity_marked_*.jsonl`), con el
  lector de `verificar`. Las tres partes, no solo train: dev eligió el
  checkpoint y test dio la cifra, así que el modelo, o quien lo eligió, las vio.
- `base`: los PMIDs de la base curada, leídos con `validacion`. De todas sus
  filas, también las de homología o con un locus ilegible: el artículo está en
  la base aunque esa fila no sirva para entrenar. Solo en el servidor, y de
  ella sale solo el conteo. Se lee únicamente con `--base` explícito, nunca
  desde el entorno: así ninguna corrida la abre sin que se haya pedido.
- La calibración no aplica: sus oraciones son inventadas y no tienen PMID. La
  salida lo dice para que su ausencia no se lea como un olvido.

Por PMID y por DOI
==================
El mismo artículo puede llegar con otro PMID (un registro duplicado, uno
retirado y vuelto a dar de alta), y entonces cruzar solo por PMID da cero sin
serlo. Por eso se cruza también el DOI, normalizado: sin `https://doi.org/` ni
`doi:`, sin punto final y en minúsculas, porque el DOI no distingue
mayúsculas. Los DOIs de cada lado son los que la fuente trae (la columna `doi`
de la lista, los de `documentos` para el corpus o la consulta, los escritos en
la base curada) más los que `documentos` tiene para sus PMIDs, si la base del
paso 0 está. Sin ella el cruce por DOI se queda en lo que traen las fuentes, y
la salida lo dice. «Solo por DOI» cuenta los artículos que el cruce por PMID
no veía.

Qué sale
========
Por `log`, conteos por fuente y la huella de la lista: la del conjunto de
PMIDs, con la regla de `corpus.hash_pmids` (una lista igual a un corpus da su
huella) y, si es un archivo, la de sus bytes (`procedencia.huella`). Nunca un
PMID, un DOI ni una ruta. Todo pasa por `reentrenar.verificar_publicable` antes
de salir, y si no pasa no sale nada. Con `salida_json`, lo mismo en JSON.

El resultado lleva `codigo`: 0 si todos los cruces de las fuentes revisadas son
0; 1 si alguno no lo es, el de la base incluido. Lo que impide verificar (un
archivo que no está, un PMID mal escrito, una consulta o un corpus que no
existen, una fuente pedida que no trae ningún PMID) es ValueError, y el CLI
sale con 2, como `verificar`. Una fuente vacía no se da por limpia: contra
nada, todo cruce da 0.

Biblioteca estándar y Python 3.8.
"""

import collections
import csv
import datetime
import io
import json
import os
import re

from grn_bronce import db as bdb
from grn_comun import archivos, procedencia, rutas
from grn_etl import db as db0
from grn_verificacion import entrenamiento, muestra, reentrenar, validacion

# `verificar` se importa donde se lee la partición y no aquí: el CLI importa
# este módulo para armar sus subcomandos en cada llamada, también en
# `reentrenar` del servidor, y `verificar` arrastra `identificar` y `puente`,
# que meten etapa2 al sys.path y cargan `clasificar` y `extraer_pares`.

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VERSION = 1
CORPUS_POR_OMISION = "v0-agosto"
JUZGADAS_POR_OMISION = os.path.join(RAIZ, "etapa2", "evaluacion",
                                    "muestra_precision_50.csv")
PARTES = ("train", "dev", "test")
ARCHIVO_PARTE = "entity_marked_%s.jsonl"

# En el orden en que se reportan.
FUENTES = ("corpus", "reservas", "muestra", "juzgadas", "particion", "base")
NOMBRES = {"corpus": "corpus", "reservas": "reservas", "muestra": "muestra",
           "juzgadas": "juzgadas", "particion": "partición",
           "base": "base curada"}
NO_PEDIDA = {"corpus": "no se pidió (--sin-corpus)",
             "reservas": "no se pidió (--reservas)",
             "muestra": "no se pidió (--muestra)",
             "particion": "no se pidió (--particion)",
             "base": "no se pidió (--base, solo donde vive la base)"}
CALIBRACION = "no aplica, sus oraciones son sintéticas y no tienen PMIDs"

# Qué ganó la precedencia de la base del paso 0, dicho para quien lee.
POR = {"flag": "--datos", "entorno:" + rutas.VARIABLE: rutas.VARIABLE,
       "omision": "omisión", "db": "--db"}

_PREFIJO_DOI = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.I)
_FORMA_DOI = re.compile(r"^10\.[0-9]{4,9}/\S+$")


def _nada(_):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _n(x):
    """Miles con espacio, como el resto del proyecto: siete u ocho cifras
    pegadas tienen la forma de un PMID y el filtro rechazaría la salida."""
    return u"{:,}".format(x).replace(",", " ")


def _cuantos(n, singular, plural):
    return "%s %s" % (_n(n), singular if n == 1 else plural)


def normalizar_doi(valor):
    """El DOI sin prefijo de resolvedor, sin punto final y en minúsculas, o
    None si no tiene forma de DOI.

    En minúsculas porque el DOI no distingue mayúsculas, y PubMed, el editor
    y quien llenó la base no siempre lo escriben igual. El punto final es el
    de la oración en que venía escrito.
    """
    texto = _PREFIJO_DOI.sub("", (valor or "").strip()).strip().rstrip(".")
    if not _FORMA_DOI.match(texto):
        return None
    return texto.lower()


def _pmid(valor, donde):
    pmid = entrenamiento._pmid_valido(valor)
    if pmid is None:
        raise ValueError("%s: un PMID no es un número." % donde)
    return pmid


def _sin_rutas(texto, rutas_dadas, marca="el archivo"):
    """El mensaje sin las rutas dadas: los errores de los lectores las
    nombran, y la salida no lleva rutas."""
    for ruta in rutas_dadas:
        if not ruta:
            continue
        for variante in sorted(set([ruta, os.path.abspath(ruta)]), key=len,
                               reverse=True):
            texto = texto.replace(variante, marca)
    return texto


def _expandir(ruta):
    return os.path.expanduser(ruta) if ruta else ruta


def _nombre_de_carpeta(carpeta):
    """El nombre de la carpeta, sin la ruta: la absoluta lleva la cuenta de
    quien corre, y el mensaje acaba en la terminal o en la bitácora."""
    return os.path.basename(os.path.normpath(os.path.abspath(carpeta)))


# ------------------------------------------------------------------ la lista

def _delimitador(linea):
    if "\t" in linea:
        return "\t"
    if ";" in linea and "," not in linea:
        return ";"
    return ","


def leer_lista(ruta):
    """(pmids, dois) de un archivo: el conjunto de PMIDs y {pmid: {dois}} de
    los que trae una columna `doi`.

    Con encabezado si la primera línea con algo nombra una columna `pmid`, en
    cualquier mayúscula; si no, un PMID por línea. En los dos formatos se
    saltan las líneas vacías y las que empiezan con `#`. Con encabezado, una
    fila con algo y sin PMID, o una que empieza con `#` y trae uno, detienen
    la lectura, como un PMID que no es número. Los errores dicen la línea y
    no su contenido.
    """
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        texto = f.read()
    lineas = texto.splitlines(True)
    inicio = next((i for i, linea in enumerate(lineas)
                   if linea.strip() and not linea.lstrip().startswith("#")),
                  None)
    pmids, dois = set(), collections.defaultdict(set)
    if inicio is None:
        raise ValueError("--lista no trae ningún PMID.")
    delimitador = _delimitador(lineas[inicio])
    encabezado = [c.strip().lower() for c in
                  next(csv.reader([lineas[inicio]], delimiter=delimitador))]
    if "pmid" in encabezado:
        i_pmid = encabezado.index("pmid")
        i_doi = encabezado.index("doi") if "doi" in encabezado else None
        lector = csv.reader(io.StringIO("".join(lineas[inicio + 1:])),
                            delimiter=delimitador)
        for fila in lector:
            if not any(c.strip() for c in fila):
                continue
            donde = "--lista, línea %d" % (inicio + 1 + lector.line_num)
            valor = fila[i_pmid].strip() if i_pmid < len(fila) else ""
            if fila[0].lstrip().startswith("#"):
                # Un comentario no trae PMID. Si lo trae, puede ser un
                # artículo cuya primera celda empieza con # (un título):
                # saltarlo dejaría fuera justo el que podía cruzar, y no hay
                # cómo saber cuál de las dos cosas es.
                if entrenamiento._pmid_valido(valor) is not None:
                    raise ValueError(
                        "%s: empieza con # como un comentario y trae un PMID. "
                        "Si es un artículo, que no empiece con #; si es un "
                        "comentario, quítale el PMID." % donde)
                continue
            if not valor:
                # Una fila con algo y sin PMID es casi siempre una corrida de
                # columna: el PMID está en otra celda y se perdería callado.
                raise ValueError("%s: la fila no trae PMID." % donde)
            pmid = _pmid(valor, donde)
            pmids.add(pmid)
            if i_doi is not None and i_doi < len(fila):
                doi = normalizar_doi(fila[i_doi])
                if doi:
                    dois[pmid].add(doi)
    else:
        for numero, linea in enumerate(lineas, 1):
            limpia = linea.strip()
            if not limpia or limpia.startswith("#"):
                continue
            pmids.add(_pmid(limpia, "--lista, línea %d" % numero))
    if not pmids:
        raise ValueError("--lista no trae ningún PMID.")
    return pmids, dict(dois)


def _de_identificadores(pares):
    """(pmids, {pmid: {dois}}) de [(pmid, doi)] de la base del paso 0."""
    pmids, dois = set(), collections.defaultdict(set)
    for pmid, doi in pares:
        pmid = entrenamiento._pmid_valido(pmid) or pmid
        pmids.add(pmid)
        doi = normalizar_doi(doi)
        if doi:
            dois[pmid].add(doi)
    return pmids, dict(dois)


# --------------------------------------------------------------- las fuentes

def _exigir_pmids(pmids, donde):
    """`pmids`, o ValueError si una fuente pedida no trae ninguno.

    Contra un conjunto vacío todo cruce da 0, y una partición con sus partes
    vacías o una llave sin filas se leería como «la lista no cruza», con la
    misma pinta que el resultado de verdad. Es el defecto que `verificar` ya
    marca en una parte vacía y por el que `muestra` no acepta una llave sin
    filas.
    """
    if not pmids:
        raise ValueError("%s no trae ningún PMID: el cruce daría 0 sin haber "
                         "con qué cruzar." % donde)
    return pmids


def _pmids_de_reservas(rutas_reservas):
    """Los PMIDs de los archivos de reservas, con el lector del contraste y de
    `precision-ciega`: su error dice la línea y no la ruta."""
    pmids, _ = entrenamiento.leer_pmids(rutas_reservas, "--reservas")
    # Un archivo de solo oraciones es una reserva válida para el
    # entrenamiento, pero aquí no aporta nada: lo que se exige es el total.
    return _exigir_pmids(pmids, "--reservas")


def _columna_pmid(ruta, donde):
    try:
        pmids, _ = entrenamiento.reservas_de_csv(ruta, "pmid")
    except ValueError as e:
        raise ValueError("%s: %s" % (donde, _sin_rutas(str(e), [ruta]))) \
            from None
    except OSError:
        raise ValueError("No pude leer el archivo de %s." % donde) from None
    return pmids


def _pmids_de_llave(ruta, donde):
    """Los PMIDs de una `llave.csv`, que trae uno en cada fila.

    El sorteo escribe un PMID por ítem, y `muestra` no acepta al excluir una
    llave con una fila sin él: es una llave tocada a mano o cortada. Saltar
    la fila, como hace `reservas_de_csv` con una celda vacía, dejaría fuera
    un artículo que la muestra sí vio. Los errores dicen la línea y no su
    contenido.
    """
    try:
        with io.open(ruta, encoding="utf-8-sig", newline="") as f:
            lector = csv.DictReader(f)
            if "pmid" not in (lector.fieldnames or []):
                raise ValueError("%s: %s no tiene la columna pmid."
                                 % (donde, muestra.LLAVE))
            pmids = set()
            for fila in lector:
                linea = "%s, línea %d" % (donde, lector.line_num)
                valor = (fila.get("pmid") or "").strip()
                if not valor:
                    raise ValueError("%s: la fila no trae PMID." % linea)
                pmids.add(_pmid(valor, linea))
    except OSError:
        raise ValueError("No pude leer %s de %s." % (muestra.LLAVE, donde)) \
            from None
    return pmids


def _pmids_de_muestras(carpetas):
    pmids = set()
    for carpeta in carpetas:
        nombre = _nombre_de_carpeta(carpeta)
        ruta = os.path.join(carpeta, muestra.LLAVE)
        if not os.path.isfile(ruta):
            raise ValueError("No está %s en la carpeta «%s» de --muestra."
                             % (muestra.LLAVE, nombre))
        donde = "--muestra «%s»" % nombre
        pmids |= _exigir_pmids(_pmids_de_llave(ruta, donde), donde)
    return pmids


def _pmids_de_particiones(carpetas):
    """train ∪ dev ∪ test de cada carpeta, con el lector de `verificar`. Sin
    una de las tres no se sabe todo lo que vio el modelo, y se detiene."""
    from grn_verificacion import verificar
    pmids = set()
    for carpeta in carpetas:
        nombre = _nombre_de_carpeta(carpeta)
        de_la_carpeta = set()
        for parte in PARTES:
            archivo = ARCHIVO_PARTE % parte
            ruta = os.path.join(carpeta, archivo)
            if not os.path.isfile(ruta):
                raise ValueError("Falta %s en la carpeta «%s» de --particion."
                                 % (archivo, nombre))
            try:
                _, de_la_parte, _ = verificar._leer_parte(ruta)
            except ValueError as e:
                raise ValueError("--particion «%s»: %s." % (nombre, e)) \
                    from None
            except OSError:
                raise ValueError("No pude leer %s de la carpeta «%s» de "
                                 "--particion." % (archivo, nombre)) from None
            for valor in de_la_parte:
                de_la_carpeta.add(_pmid(valor, "--particion «%s», %s"
                                        % (nombre, archivo)))
        # Por carpeta: una vacía junto a otra llena también es un cruce que
        # no se hizo.
        pmids |= _exigir_pmids(de_la_carpeta, "--particion «%s»" % nombre)
    return pmids


def _pmids_y_dois_de_la_base(ruta, hoja=None):
    """(pmids, dois) de la columna Reference de TODAS las filas de la base.

    No pasa por `validacion.leer_base`: esa devuelve solo las filas con los
    dos locus válidos, y un artículo citado por una fila con el locus corrido
    sigue estando en la base. La columna se ubica y se lee como la lee
    `validacion.normalizar`, con las mismas reglas para los PMIDs, y los DOIs
    son los que su contador cuenta como `dois_descartados`. Nada de esto se
    imprime: sale el conteo.
    """
    encabezados, filas = validacion.leer_xlsx(ruta, hoja)
    indice = validacion._indice_columnas(encabezados)
    pmids, dois = set(), set()
    for _, valores in filas:
        referencia = validacion._celda(valores, indice, "Reference")
        pmids.update(validacion.pmids_de(referencia)[0])
        for crudo in validacion._DOI.findall(referencia or ""):
            doi = normalizar_doi(crudo)
            if doi:
                dois.add(doi)
    return pmids, dois


# ---------------------------------------------------------- la base del paso 0

def _abrir_paso0(datos, ruta_db, exigida):
    """(conexión en solo lectura o None, por dónde).

    `exigida` dice para qué hace falta (la consulta, el corpus) o es None.
    Con `--db`, o si hace falta, que no esté es error. Si no, no estar solo
    quita los DOIs de `documentos`, y la salida lo dice. Nunca se abre con
    `grn_etl.db.conectar`: esa crea el esquema y una base vacía donde no
    había nada, y el corpus «no existiría» en vez de no encontrarse.
    """
    if ruta_db:
        ruta, por = _expandir(ruta_db), POR["db"]
    else:
        ruta = os.path.join(_expandir(rutas.raiz_datos(datos)), "grn.db")
        por = POR.get(rutas.de_donde(datos), rutas.de_donde(datos))
    if not os.path.isfile(ruta):
        if ruta_db:
            raise ValueError("No encuentro la base del paso 0 que da --db.")
        if exigida:
            raise ValueError(
                "No encuentro la base del paso 0 (por %s), y hace falta para "
                "%s. Dala con --datos o --db%s."
                % (por, exigida, "" if exigida == "--consulta" else
                   ", o salta el corpus con --sin-corpus"))
        return None, por
    try:
        return bdb.conectar_lectura(ruta), por
    except bdb.ErrorBase:
        raise ValueError("No pude abrir la base del paso 0 en solo lectura "
                         "(por %s)." % por) from None


# --------------------------------------------------------------- los cruces

def cruzar(lista, dois_lista, pmids, dois):
    """(por PMID, por DOI, solo por DOI): cuántos PMIDs de la lista están en
    la fuente por su PMID, cuántos por alguno de sus DOIs y cuántos de estos
    no los veía el cruce por PMID."""
    por_pmid = lista & pmids
    por_doi = set(p for p in lista if dois_lista.get(p, set()) & dois)
    return len(por_pmid), len(por_doi), len(por_doi - por_pmid)


def _unir_dois(dois_por_pmid, de_documentos):
    """{pmid: {dois}} con los DOIs propios más los de `documentos`."""
    unidos = collections.defaultdict(set)
    for pmid, propios in dois_por_pmid.items():
        unidos[pmid] |= propios
    for pmid, doi in de_documentos.items():
        doi = normalizar_doi(doi)
        if doi:
            unidos[pmid].add(doi)
    return dict(unidos)


def _linea_fuente(f):
    if not f["revisada"]:
        return "  %s: %s." % (f["etiqueta"], f["motivo"])
    return ("  %s: %s y %s; cruces: %s por PMID, %s por DOI (%s solo por "
            "DOI)." % (f["etiqueta"], _cuantos(f["pmids"], "PMID", "PMIDs"),
                       _cuantos(f["dois"], "DOI", "DOIs"),
                       _n(f["cruces_pmid"]), _n(f["cruces_doi"]),
                       _n(f["solo_doi"])))


def resumen(resultado):
    """Las líneas que ve quien corre esto: conteos, la huella y nombres."""
    lista = resultado["lista"]
    origen = ("de la consulta «%s»" % lista["consulta"]
              if lista["origen"] == "consulta" else "de --lista")
    huellas = "huella del conjunto %s" % lista["huella"]
    if lista["huella_archivo"]:
        huellas += ", del archivo %s" % lista["huella_archivo"]
    paso0 = resultado["base_paso0"]
    lineas = [
        "Lista: %s %s, %s con DOI; %s."
        % (_cuantos(lista["pmids"], "PMID", "PMIDs"), origen,
           _n(lista["con_doi"]), huellas),
        ("Base del paso 0: en solo lectura, por %s." % paso0["por"])
        if paso0["abierta"] else
        ("Base del paso 0: no está (por %s); los DOIs son solo los que traen "
         "las fuentes." % paso0["por"]),
    ]
    lineas.extend(_linea_fuente(f) for f in resultado["fuentes"])
    lineas.append("  calibración: %s." % resultado["calibracion"])
    revisadas = [f for f in resultado["fuentes"] if f["revisada"]]
    con_cruces = [f for f in revisadas
                  if f["cruces_pmid"] or f["cruces_doi"]]
    # El participio concuerda con el conteo: con --sin-corpus y solo las
    # juzgadas, que siempre se revisan, la fuente revisada es una.
    de_revisadas = _cuantos(len(revisadas), "fuente revisada",
                            "fuentes revisadas")
    if con_cruces:
        lineas.append(
            "Con cruces en %s de %s (%s): la lista no es del todo nueva."
            % (_n(len(con_cruces)), de_revisadas,
               ", ".join(NOMBRES[f["fuente"]] for f in con_cruces)))
    else:
        lineas.append("Ningún cruce en %s." % de_revisadas)
    return lineas


def _escribir_json(ruta, resultado):
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n")
    archivos.reemplazar(tmp, ruta)


# ------------------------------------------------------------------ ejecutar

def _como_lista(valor):
    if not valor:
        return []
    # Una sola ruta suelta se recorrería letra por letra.
    return [valor] if isinstance(valor, str) else list(valor)


def ejecutar(lista=None, consulta=None, corpus=CORPUS_POR_OMISION,
             sin_corpus=False, reservas=(), muestras=(),
             juzgadas=JUZGADAS_POR_OMISION, particiones=(), base=None,
             hoja=None, datos=None, ruta_db=None, salida_json=None,
             log=_nada):
    """Cuenta los cruces de la lista con cada fuente y los reporta por `log`.

    `lista` es la ruta del archivo, o `consulta` el nombre de una consulta de
    la base del paso 0; una de las dos. `reservas`, `muestras` y
    `particiones` admiten varias rutas. `datos` y `ruta_db` ubican la base del
    paso 0 con la precedencia de siempre (`--db`, `--datos`, `GRN_DATOS`,
    `./datos`). `base` es la ruta del .xlsx de la base curada, o None.

    Todo se lee antes de decir nada: un error a media lectura no deja una
    salida a medias. Devuelve el resultado, solo conteos, con `codigo` 0 si
    ningún cruce revisado pasa de 0 y 1 si alguno sí. ValueError si no se pudo
    verificar.
    """
    if bool(lista) == bool(consulta):
        raise ValueError("Da --lista o --consulta, una de las dos.")
    lista = _expandir(lista)
    reservas = [_expandir(r) for r in _como_lista(reservas)]
    muestras = [_expandir(c) for c in _como_lista(muestras)]
    particiones = [_expandir(c) for c in _como_lista(particiones)]
    juzgadas = _expandir(juzgadas)
    base = _expandir(base)
    for flag, ruta in ([("--lista", lista), ("--juzgadas", juzgadas),
                        ("--base", base)]
                       + [("--reservas", r) for r in reservas]):
        if ruta and not os.path.isfile(ruta):
            # Sin la ruta: la de --base dice dónde vive la base.
            raise ValueError("No encuentro el archivo de %s. Usa una ruta "
                             "absoluta; entre comillas simples, ~ y $HOME no "
                             "se expanden." % flag)
    if not juzgadas:
        raise ValueError("Falta el archivo de --juzgadas.")
    for flag, carpeta in ([("--muestra", c) for c in muestras]
                          + [("--particion", c) for c in particiones]):
        if not os.path.isdir(carpeta):
            raise ValueError("No encuentro la carpeta «%s» de %s."
                             % (_nombre_de_carpeta(carpeta), flag))

    exigida = ("--consulta" if consulta else
               None if sin_corpus else "el corpus")
    con, por = _abrir_paso0(datos, ruta_db, exigida)
    try:
        if consulta:
            if db0.obtener_consulta(con, consulta) is None:
                raise ValueError("No existe la consulta «%s» en la base del "
                                 "paso 0." % consulta)
            pmids_lista, dois_lista = _de_identificadores(
                db0.pmids_y_dois_de_consulta(con, consulta))
            if not pmids_lista:
                raise ValueError("La consulta «%s» no tiene documentos: no hay "
                                 "lista que verificar." % consulta)
        else:
            pmids_lista, dois_lista = leer_lista(lista)

        # Por fuente: (etiqueta, pmids, {pmid: {dois}}, DOIs sin PMID).
        leidas = collections.OrderedDict()
        if not sin_corpus:
            fila = db0.obtener_corpus(con, corpus)
            if fila is None:
                raise ValueError("No existe el corpus «%s» en la base del "
                                 "paso 0." % corpus)
            pmids, dois = _de_identificadores(
                db0.pmids_y_dois_del_corpus(con, fila["id"]))
            _exigir_pmids(pmids, "El corpus «%s»" % corpus)
            leidas["corpus"] = ("corpus %s" % corpus, pmids, dois, set())
        if reservas:
            leidas["reservas"] = (
                "reservas (%s)" % _cuantos(len(reservas), "archivo",
                                           "archivos"),
                _pmids_de_reservas(reservas), {}, set())
        if muestras:
            leidas["muestra"] = (
                "muestra (%s)" % _cuantos(len(muestras), "carpeta",
                                          "carpetas"),
                _pmids_de_muestras(muestras), {}, set())
        leidas["juzgadas"] = (
            "juzgadas", _exigir_pmids(_columna_pmid(juzgadas, "--juzgadas"),
                                      "--juzgadas"), {}, set())
        if particiones:
            leidas["particion"] = (
                "partición (%s)" % _cuantos(len(particiones), "carpeta",
                                            "carpetas"),
                _pmids_de_particiones(particiones), {}, set())
        if base:
            pmids, sueltos = _pmids_y_dois_de_la_base(base, hoja)
            if not sueltos:
                # Un DOI escrito en la base también es con qué cruzar.
                _exigir_pmids(pmids, "La columna Reference de --base")
            leidas["base"] = ("base curada", pmids, {}, sueltos)

        if con is not None:
            # Los DOIs que `documentos` tiene para cada PMID, de los dos
            # lados: con ellos, el mismo artículo bajo otro PMID también cruza.
            dois_lista = _unir_dois(dois_lista,
                                    db0.dois_de_pmids(con, pmids_lista))
            for clave, (etiqueta, pmids, dois, sueltos) in list(
                    leidas.items()):
                leidas[clave] = (etiqueta, pmids, _unir_dois(
                    dois, db0.dois_de_pmids(con, pmids)), sueltos)
    finally:
        if con is not None:
            con.close()

    fuentes = []
    for clave in FUENTES:
        if clave not in leidas:
            fuentes.append(collections.OrderedDict([
                ("fuente", clave), ("etiqueta", NOMBRES[clave]),
                ("revisada", False), ("motivo", NO_PEDIDA[clave])]))
            continue
        etiqueta, pmids, dois_por_pmid, dois = leidas[clave]
        dois = set(dois)
        for de_uno in dois_por_pmid.values():
            dois |= de_uno
        por_pmid, por_doi, solo_doi = cruzar(pmids_lista, dois_lista, pmids,
                                             dois)
        fuentes.append(collections.OrderedDict([
            ("fuente", clave), ("etiqueta", etiqueta), ("revisada", True),
            ("pmids", len(pmids)), ("dois", len(dois)),
            ("cruces_pmid", por_pmid), ("cruces_doi", por_doi),
            ("solo_doi", solo_doi)]))

    con_cruces = [f["fuente"] for f in fuentes
                  if f["revisada"] and (f["cruces_pmid"] or f["cruces_doi"])]
    resultado = collections.OrderedDict([
        ("version", VERSION),
        ("generado_en", _ahora()),
        ("lista", collections.OrderedDict([
            ("origen", "consulta" if consulta else "archivo"),
            ("consulta", consulta or None),
            ("pmids", len(pmids_lista)),
            ("con_doi", sum(1 for p in pmids_lista if dois_lista.get(p))),
            ("huella", db0.huella_pmids(pmids_lista)),
            ("huella_archivo", procedencia.huella(lista) if lista else None),
        ])),
        ("base_paso0", collections.OrderedDict([
            ("abierta", con is not None), ("por", por)])),
        ("fuentes", fuentes),
        ("calibracion", CALIBRACION),
        ("fuentes_con_cruces", con_cruces),
        ("codigo", 1 if con_cruces else 0),
    ])
    lineas = resumen(resultado)
    texto_json = json.dumps(resultado, ensure_ascii=False, indent=2)
    try:
        reentrenar.verificar_publicable("\n".join(lineas))
        reentrenar.verificar_publicable(texto_json)
    except ValueError as e:
        # Lo único que puede traer algo así es un nombre de consulta o de
        # corpus: lo demás son conteos y huellas. Se dice, porque quien corre
        # no ve la línea que falló, y un nombre con la fecha sin guiones
        # («nuevos_» y ocho cifras) es justo el que se le pone a lo nuevo. El
        # mensaje no lleva cifras: el filtro del CLI lo dejaría vacío.
        raise ValueError(
            "La salida no pasó el filtro de publicación (%s): no se escribe "
            "nada. Lo único en ella que no es un conteo ni una huella son los "
            "nombres de la consulta y del corpus: con siete u ocho cifras "
            "seguidas, como una fecha sin guiones, parecen un PMID." % e) \
            from None
    if salida_json:
        _escribir_json(_expandir(salida_json), resultado)
    for linea in lineas:
        log(linea)
    return resultado
