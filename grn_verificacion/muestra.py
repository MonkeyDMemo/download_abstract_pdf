"""La muestra ciega para anotar con ayudantes: población, exclusiones, sorteo
y sus salidas (`docs/rubrica-anotacion.md`, §6 a §8).

    python -m grn_verificacion.cli muestra --carpeta C --reservas R --n N \
        --salida D [--semilla S] [--fraccion-doble F] [--tandas 1|2] \
        [--excluir-muestra DIR ...]

Por qué se sortea por oración y no por par
==========================================
La rúbrica (§8) define la población como las oraciones candidatas del bronce
con regulador y blanco, la misma de las 50, y el ítem como la oración con el
par que propone el bronce, sin decir cuál de los dos es el regulador. Sortear
pares la rompería por dos lados: una oración que nombra seis genes da quince
pares y sería quince veces más probable que una de dos, y entrarían pares que
el bronce no orientó, que la rúbrica deja a la revisión de candidatas nuevas.
La cifra dejaría de compararse con el 44 %.

De `capa_pares.csv` (una fila por par) cada oración entra con su fila
`par_del_bronce = directo`: el par del clasificador es el mismo que orientó el
bronce, y con su `id_par` la llave une cada ítem con lo que dijo cada capa de
la plata, que se mide sobre lo que acepta.

Lo que queda fuera, y en qué orden
==================================
Cada oración se cuenta en el primer motivo que le toca, en este orden. Las
reservas van primero, como en `entrenamiento.py`: lo reservado no cuenta ni
como repetido.

1. `pmid_reservado`: su artículo está en `reservas.tsv`.
2. `oracion_reservada_igual`: es una oración reservada, con los espacios
   normalizados (`entrenamiento.leer_reservas`).
3. `oracion_reservada_contenida`: contiene una reservada o es un pedazo de
   ella, de `entrenamiento.MINIMO_CONTENCION` caracteres o más
   (`entrenamiento.reservada`). El bronce y el conjunto ciego no siempre
   cortan igual la oración.
4. `pmid_de_otra_muestra`: su artículo está en la llave de una muestra
   anterior (`--excluir-muestra`, más abajo). El motivo solo existe, y solo
   sale en el resumen, cuando se pide.
5. `oracion_de_otra_muestra`: en otro artículo, el mismo texto canónico que
   una oración de esa llave. Como el anterior, solo con la opción.
6. `sin_par_directo`: el bronce la orientó, pero su par no está entre los que
   vio el clasificador (en la corrida 4, el bronce escribe `rsmZY` y el par
   `rsmYZ`). Sin `id_par` no se puede medir la plata sobre ella.
7. `repetida`: el mismo texto canónico (`entrenamiento.canonico`) que otra
   que ya entró; se queda la primera del orden estable. Quien anota juzga
   igual la misma oración dos veces: serían dos ítems y un solo juicio.

El sorteo
=========
Aleatorio simple, sin estratos: la rúbrica no los pide dentro de la muestra
ciega. Sus dos estratos, la muestra ciega y las candidatas nuevas, se sortean
en lugares distintos, y las nuevas donde vive la base (§8). Como en
`etapa2/evaluacion/muestrear_candidatas.py`, la población se ordena por una
clave estable (PMID, fuente, número de oración, `id_par`) antes de
`random.Random(semilla).sample`, así que la semilla significa lo mismo mañana.

- **Tandas** (§8). La primera mitad del sorteo es la tanda 1, que va directo
  a los ayudantes. La otra mitad es la parte ciega de la tanda 2: no se les
  entrega así, sino barajada en el servidor con las candidatas nuevas en una
  sola hoja, para que la hoja no diga qué pares faltan en la base.
- **Parte doble** (§7, punto 4). En cada tanda, la fracción pedida, el 25 %
  por omisión. Va en `dobles.csv` y en la llave, y no en la hoja: todos
  reciben la misma hoja, y qué ítems anotan dos personas lo decide quien
  reparte.
- **`id_item`**. Un código al azar del mismo sorteo (`m-` y cuatro cifras o
  más), no un consecutivo: un consecutivo diría el orden del sorteo y, al
  barajar la tanda 2, de qué estrato viene cada ítem. Las candidatas nuevas
  tienen que llevar códigos del mismo formato que no choquen con estos.

La parte doble y los códigos salen de generadores aparte, sembrados con la
misma semilla y una sal: cambiar la fracción no cambia qué oraciones salen.

Otra muestra sin los artículos ni los códigos de una anterior
=============================================================
`--excluir-muestra DIR`, que se puede repetir, lee `DIR/llave.csv` de un
sorteo anterior y deja fuera de la población todas las oraciones de sus
artículos, con el PMID normalizado como en `entrenamiento.py`. Es para una
tanda de prueba: un artículo que ya se vio en la anterior, al anotarla o al
ajustar algo con ella, haría que la nueva midiera en parte lo ya visto.

El PMID no aparta las copias de una oración juzgada en OTROS artículos (el
mismo resumen bajo dos PMIDs, una revisión que la cita literal), y en la
corrida 4 hay 44 textos canónicos que salen en dos PMIDs. Sin exclusiones la
copia es `repetida` de su original, pero el original sale por su PMID y la
copia entraría: quien anota juzgaría otra vez lo que ya juzgó. Por eso también
salen las oraciones con el mismo texto canónico que una de la llave, el mismo
criterio de `repetida`. Su texto sale de esta capa por la clave de cada fila
(PMID, fuente y número de oración): la llave tiene que ser de un sorteo sobre
la misma `capa_pares.csv`, y si una de sus oraciones no está, no se sortea. Se
apartan las copias de lo juzgado, no las de las demás oraciones de esos
artículos, que nadie vio.

También deja fuera sus `id_item`. Los códigos dependen solo de la semilla y
del tamaño, así que con la misma semilla y el mismo `n` saldrían los mismos, y
la anotación de una tanda se uniría sin error con la llave de la otra
(`precision_ciega.py` une por `id_item`). Los nuevos salen del mismo rango
menos los usados; si no alcanzan, no se sortea.

El resumen lleva `muestras_excluidas`: la huella de cada llave distinta, con
cuántos PMIDs y códigos trae, en el orden de las huellas, para que el orden en
que se dan las carpetas no vuelva otro el sorteo. La población que reporta es
la que queda tras excluirlas. Sin la opción, las salidas son las de siempre
byte a byte y el resumen no gana claves.

Las salidas, y a quién va cada una
==================================
- `hoja_tanda1.csv`: a los ayudantes.
- `hoja_tanda2_ciega.csv`: al servidor, para barajarla con las candidatas
  nuevas; no va directo a los ayudantes.
- `dobles.csv`: a quien reparte y adjudica la parte doble; solo `id_item` y
  tanda. La orientación del bronce no va ahí: un adjudicador que la ve
  desempata hacia el bronce.
- `llave.csv`: solo para el análisis, nunca a los ayudantes ni a quien
  adjudica.
- `resumen.json`: semilla, tamaño, población, exclusiones por motivo y
  huellas de las entradas, de las salidas y, si las hay, de las llaves
  excluidas; no lleva oraciones ni PMIDs.

Las hojas llevan exactamente las columnas del §6. Las entidades van en el
orden en que aparecen en la oración y escritas como en ella, que es lo que
pide el §6; ese orden lo da el texto, no la orientación del bronce. Las hojas
no llevan PMID, sección, tanda, predicciones, umbrales, `signo_sugerido`, ni
la dirección del bronce o de la sintaxis. Los CSV van en UTF-8 con BOM, para
que Excel lea bien los acentos.

Una carpeta de salida que ya tiene un sorteo con otra semilla, otro tamaño,
otras entradas u otras muestras excluidas no se sobrescribe: esa hoja pudo
haberse repartido ya. Un resumen sin `muestras_excluidas`, como los de antes
de la opción, es el de un sorteo sin ellas.

Biblioteca estándar y Python 3.8.
"""

import csv
import io
import json
import os
import random
import re

from grn_bronce import texto as _texto
from grn_comun import archivos, procedencia
from grn_verificacion import entrenamiento

VERSION = 1
SEMILLA = 20261024
FRACCION_DOBLE = 0.25
# Dos tandas cuando la segunda se baraja con las candidatas nuevas (§8); una
# para la muestra única de 200 del servicio social.
TANDAS = 2

NOMBRE_CAPA = "capa_pares.csv"
HOJA_TANDA1 = "hoja_tanda1.csv"
HOJA_TANDA2 = "hoja_tanda2_ciega.csv"
LLAVE = "llave.csv"
DOBLES = "dobles.csv"
RESUMEN = "resumen.json"

# Lo único que necesita quien reparte la parte doble y adjudica sus
# desacuerdos. Va aparte de la llave porque la llave dice cómo orientó el
# bronce cada par, y un adjudicador que lo ve desempata hacia el bronce: la
# cifra mediría el acuerdo con el pipeline y no lo que dice la oración.
COLUMNAS_DOBLES = ["id_item", "tanda"]

# Las de la rúbrica, §6, en su orden, y ninguna más.
COLUMNAS_HOJA = ["id_item", "oracion", "entidad_1", "entidad_2", "relacion",
                 "direccion", "signo", "tipo", "negada", "especulativa",
                 "comentario"]

# `direccion_bronce` es la orientación del bronce dicha en los términos de la
# hoja (`1>2` si su regulador es la entidad_1): con ella se cuenta la
# precisión con dirección sin volver a abrir la capa.
COLUMNAS_LLAVE = ["id_item", "tanda", "doble", "pmid", "fuente_texto",
                  "num_oracion", "id_par", "regulador", "blanco",
                  "direccion_bronce"]

# Lo que se lee de `capa_pares.csv`. Si el contrato de la capa cambia, el
# error lo dice antes de sortear.
COLUMNAS_CAPA = ["pmid", "fuente_texto", "num_oracion", "id_par", "oracion",
                 "regulador_candidato", "blanco_candidato", "par_del_bronce",
                 "mencion_tf", "mencion_target"]

# En el orden en que los prueba `_motivo`, que dice por qué el de otra
# muestra va donde va.
MOTIVOS = ["pmid_reservado", "oracion_reservada_igual",
           "oracion_reservada_contenida", "pmid_de_otra_muestra",
           "oracion_de_otra_muestra", "sin_par_directo", "repetida"]

# Solo con --excluir-muestra. Sin la opción no aparecen ni en cero: el resumen
# de un sorteo de antes tiene que salir igual byte a byte.
OTRA_MUESTRA = "pmid_de_otra_muestra"
COPIA_DE_OTRA_MUESTRA = "oracion_de_otra_muestra"
DE_OTRA_MUESTRA = (OTRA_MUESTRA, COPIA_DE_OTRA_MUESTRA)

ETIQUETAS = {
    "pmid_reservado": "PMID reservado",
    "oracion_reservada_igual": "oración reservada, igual",
    "oracion_reservada_contenida": "oración reservada, contenida (%d "
                                   "caracteres o más)"
                                   % entrenamiento.MINIMO_CONTENCION,
    "pmid_de_otra_muestra": "PMID de una muestra excluida",
    "oracion_de_otra_muestra": "mismo texto que una oración de una muestra "
                               "excluida",
    "sin_par_directo": "el par del bronce no llegó al clasificador",
    "repetida": "mismo texto que otra que ya entró",
}

# De la llave de una muestra excluida no hace falta más: el código, el
# artículo y dónde está la oración en la capa, que da el texto para apartar
# sus copias. Lo demás puede faltar.
COLUMNAS_LLAVE_EXCLUIDA = ["id_item", "pmid", "fuente_texto", "num_oracion"]

FORMATO_ID = "m-%d"


# ---------------------------------------------------------------- población

def _reemplaza(previo, directo, id_par):
    """Si la fila nueva de una oración gana a la que ya se guardó.

    La directa gana a la que no lo es. Dos directas son el mismo par en dos
    pares de menciones: gana la de menor `id_par`, para que la elección no
    dependa del orden del archivo.
    """
    if directo != previo["directo"]:
        return directo
    return directo and id_par < previo["id_par"]


def _leer_capa(ruta):
    """{(pmid, fuente, num_oracion): ítem} de las oraciones que el bronce
    orientó, con la fila de su par `directo` si la tiene.

    Si no la tiene, se guarda la primera fila que se vio: hace falta para
    contarla en el motivo que le toque, y las reservas van antes.
    """
    oraciones = {}
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        cabecera = lector.fieldnames or []
        faltan = [c for c in COLUMNAS_CAPA if c not in cabecera]
        if faltan:
            raise ValueError("A %s le faltan columnas: %s."
                             % (NOMBRE_CAPA, ", ".join(faltan)))
        for fila in lector:
            regulador = (fila["regulador_candidato"] or "").strip()
            blanco = (fila["blanco_candidato"] or "").strip()
            if not regulador or not blanco:
                continue
            pmid = entrenamiento.pmid_valido(fila["pmid"])
            if pmid is None:
                raise ValueError("Una fila de %s trae un pmid que no es un "
                                 "número." % NOMBRE_CAPA)
            clave = (pmid, fila["fuente_texto"], fila["num_oracion"])
            directo = fila["par_del_bronce"] == "directo"
            previo = oraciones.get(clave)
            if previo is not None and not _reemplaza(previo, directo,
                                                     fila["id_par"]):
                continue
            oracion = fila["oracion"] or ""
            oraciones[clave] = {
                "pmid": pmid,
                "fuente_texto": fila["fuente_texto"],
                "num_oracion": fila["num_oracion"],
                "id_par": fila["id_par"],
                "oracion": oracion,
                "normalizada": _texto.normalizar_espacios(oracion),
                "regulador": regulador,
                "blanco": blanco,
                "mencion_regulador": (fila["mencion_tf"] or "").strip()
                or regulador,
                "mencion_blanco": (fila["mencion_target"] or "").strip()
                or blanco,
                "directo": directo,
            }
    return oraciones


def _orden(item):
    num = item["num_oracion"]
    return (int(item["pmid"]), item["fuente_texto"],
            (0, int(num), "") if num.isdigit() else (1, 0, num),
            item["id_par"])


def _motivo(item, pmids, reservadas, vistas, otras=frozenset(),
            copias=frozenset()):
    if item["pmid"] in pmids:
        return "pmid_reservado"
    oracion = item["normalizada"]
    if oracion in reservadas:
        return "oracion_reservada_igual"
    if entrenamiento.reservada(oracion, reservadas):
        return "oracion_reservada_contenida"
    # Después de las reservas, que siguen primero: así sus conteos dependen
    # solo de la capa y de reservas.tsv, y dos sorteos con las mismas
    # reservas dicen lo mismo de ellas aunque uno excluya otra muestra. Antes
    # de los otros dos porque, como `pmid_reservado`, aparta por el artículo
    # del que viene la oración y no por cómo es ella: lo de otra muestra no se
    # cuenta como sin par ni como repetido, y esos dos motivos describen solo
    # los artículos que siguen en juego. El orden no cambia la población, solo
    # en qué motivo se cuenta cada oración.
    if item["pmid"] in otras:
        return OTRA_MUESTRA
    canon = entrenamiento.canonico(oracion)
    # La copia de una oración juzgada en otro artículo: su original salió por
    # el PMID y nunca llega a `vistas`, así que sin esto la copia ya no sería
    # repetida y entraría.
    if canon in copias:
        return COPIA_DE_OTRA_MUESTRA
    if not item["directo"]:
        return "sin_par_directo"
    if canon in vistas:
        return "repetida"
    return None


def _textos_excluidos(oraciones, claves):
    """El texto canónico de las oraciones de las muestras excluidas, sacado de
    la capa por su clave (pmid, fuente, número de oración).

    Una clave que no está detiene el sorteo: sin su texto, sus copias en otros
    artículos entrarían sin que nada avisara. Pasa si la llave salió de otra
    capa. El mensaje no dice cuál, porque la clave lleva el PMID.
    """
    faltan = sum(1 for clave in claves if clave not in oraciones)
    if faltan:
        raise ValueError(
            "Hay oraciones de las muestras excluidas que no están en %s (%d), "
            "y sus copias en otros artículos no se podrían apartar: la llave "
            "tiene que ser de un sorteo sobre esta misma capa."
            % (NOMBRE_CAPA, faltan))
    return frozenset(entrenamiento.canonico(oraciones[clave]["normalizada"])
                     for clave in claves)


def poblacion(ruta_capa, reservas, pmids_excluidos=None,
              oraciones_excluidas=None):
    """(ítems, conteos): las oraciones sorteables en su orden estable, y
    cuántas había y cuántas quedaron fuera por cada motivo.

    `reservas` es el primer valor de `entrenamiento.leer_reservas`;
    `pmids_excluidos` y `oraciones_excluidas`, los PMIDs y las claves
    (pmid, fuente, número de oración) de las muestras excluidas. Con los dos
    en None no hay motivos de otra muestra en los conteos, ni en cero.
    """
    oraciones = _leer_capa(ruta_capa)
    pmids = reservas.get("pmids") or set()
    reservadas = reservas.get("oraciones") or set()
    otras = frozenset(pmids_excluidos or ())
    copias = _textos_excluidos(oraciones, oraciones_excluidas or ())
    con_otras = (pmids_excluidos is not None
                 or oraciones_excluidas is not None)
    fuera = dict.fromkeys((m for m in MOTIVOS
                           if con_otras or m not in DE_OTRA_MUESTRA), 0)
    vistas = set()
    items = []
    for item in sorted(oraciones.values(), key=_orden):
        motivo = _motivo(item, pmids, reservadas, vistas, otras, copias)
        if motivo:
            fuera[motivo] += 1
            continue
        vistas.add(entrenamiento.canonico(item["normalizada"]))
        items.append(item)
    return items, {"oraciones_con_par_del_bronce": len(oraciones),
                   "exclusiones": fuera, "poblacion": len(items)}


# ------------------------------------------------------- muestras excluidas

def _leer_llave_excluida(carpeta):
    """(huella, pmids, códigos, claves) de `llave.csv` de un sorteo anterior.
    Las claves son (pmid, fuente, número de oración), como en `_leer_capa`.

    Los errores nombran la carpeta y no su ruta, como los demás de este
    módulo: la ruta absoluta lleva la cuenta de quien corre, y el mensaje
    acaba en la terminal o en la bitácora. Una fila sin PMID válido o sin
    código, o una llave sin filas, detienen la lectura: ignorarlas dejaría
    entrar justo lo que se pidió apartar.
    """
    nombre = os.path.basename(os.path.abspath(carpeta)) or carpeta
    ruta = os.path.join(carpeta, LLAVE)
    if not os.path.isfile(ruta):
        raise ValueError("No está %s en la muestra excluida «%s»."
                         % (LLAVE, nombre))
    # Antes de leer, como las de las entradas: describe lo que se leyó.
    huella = procedencia.huella(ruta)
    pmids, codigos, claves = set(), set(), set()
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        cabecera = lector.fieldnames or []
        faltan = [c for c in COLUMNAS_LLAVE_EXCLUIDA if c not in cabecera]
        if faltan:
            raise ValueError("A %s de la muestra excluida «%s» le faltan "
                             "columnas: %s." % (LLAVE, nombre,
                                                ", ".join(faltan)))
        for fila in lector:
            pmid = entrenamiento.pmid_valido(fila["pmid"])
            if pmid is None:
                raise ValueError("Una fila de %s de la muestra excluida «%s» "
                                 "trae un pmid que no es un número."
                                 % (LLAVE, nombre))
            codigo = (fila["id_item"] or "").strip()
            if not codigo:
                raise ValueError("Una fila de %s de la muestra excluida «%s» "
                                 "no trae id_item." % (LLAVE, nombre))
            pmids.add(pmid)
            codigos.add(codigo)
            # Sin recortar, como las escribe el sorteo y como las lee
            # `_leer_capa`: así la clave es la misma.
            claves.add((pmid, fila["fuente_texto"], fila["num_oracion"]))
    if not codigos:
        raise ValueError("La llave de la muestra excluida «%s» no tiene "
                         "ítems." % nombre)
    return huella, pmids, codigos, claves


def _muestras_excluidas(carpetas):
    """(pmids, códigos, claves, registro) de todas las llaves. El registro,
    que va al resumen, lleva una entrada por llave distinta en el orden de su
    huella: dar las carpetas en otro orden, o una dos veces, es el mismo
    sorteo."""
    if isinstance(carpetas, str):
        # Una sola carpeta suelta se recorrería letra por letra.
        carpetas = [carpetas]
    pmids, codigos, claves, registro = set(), set(), set(), {}
    for carpeta in carpetas:
        huella, de_la_llave, sus_codigos, sus_claves = _leer_llave_excluida(
            carpeta)
        pmids |= de_la_llave
        codigos |= sus_codigos
        claves |= sus_claves
        registro[huella] = {"llave": huella, "pmids": len(de_la_llave),
                            "codigos": len(sus_codigos)}
    return pmids, codigos, claves, [registro[h] for h in sorted(registro)]


# ------------------------------------------------------------------- sorteo

def _posicion(oracion, mencion):
    """Dónde aparece la mención por primera vez: como palabra entera si se
    puede, porque `lasR` también está dentro de `lasRI`."""
    m = re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(mencion),
                  oracion)
    if m:
        return m.start()
    i = oracion.find(mencion)
    return i if i >= 0 else len(oracion)


def entidades(item):
    """(entidad_1, entidad_2, direccion_bronce) del ítem.

    La entidad_1 es la que aparece primero en la oración, escrita como en
    ella (§6). Si las dos empiezan en el mismo lugar, decide el alfabeto.
    """
    oracion = item["oracion"]
    reg, bla = item["mencion_regulador"], item["mencion_blanco"]
    if ((_posicion(oracion, reg), reg.casefold(), reg)
            <= (_posicion(oracion, bla), bla.casefold(), bla)):
        return reg, bla, "1>2"
    return bla, reg, "2>1"


def sortear(items, n, semilla=SEMILLA, fraccion_doble=FRACCION_DOBLE,
            tandas=TANDAS, codigos_excluidos=()):
    """Los `n` ítems sorteados, ordenados por `id_item`, cada uno con su
    tanda, si es doble, sus entidades y la dirección del bronce.

    Con `tandas=1` todo va a la tanda 1: es la muestra única del servicio
    social, con un solo anotador y sin candidatas nuevas que barajar.

    `items` tiene que venir en el orden estable de `poblacion()`. Un tamaño
    mayor que la población es un error y no se sortea nada.
    `codigos_excluidos` son los `id_item` de las muestras excluidas: los
    códigos salen del mismo rango sin ellos, y si no alcanzan, tampoco se
    sortea.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("El tamaño de la muestra tiene que ser un entero "
                         "positivo.")
    if not 0 <= fraccion_doble <= 1:
        raise ValueError("La fracción doble tiene que estar entre 0 y 1.")
    if tandas not in (1, 2):
        raise ValueError("Las tandas son 1 o 2.")
    if n > len(items):
        raise ValueError(
            "Se pidieron %d ítems y la población, tras las exclusiones, "
            "tiene %d: no se sortea." % (n, len(items)))
    ancho = max(4, len(str(n)) + 1)
    libres = range(10 ** (ancho - 1), 10 ** ancho)
    if codigos_excluidos:
        usados = frozenset(codigos_excluidos)
        # En el orden del rango: `sample` elige por posición, y restar
        # conjuntos daría un orden que cambia de un proceso a otro
        # (PYTHONHASHSEED). La misma semilla tiene que dar los mismos códigos.
        libres = [c for c in libres if FORMATO_ID % c not in usados]
        if len(libres) < n:
            raise ValueError(
                "Las muestras excluidas dejan %d códigos de %d cifras libres "
                "para %d ítems: no se sortea." % (len(libres), ancho, n))
    elegidos = random.Random(semilla).sample(items, n)
    # Sin códigos excluidos, `libres` es el `range` de siempre: la carpeta de
    # un sorteo de antes se tiene que poder repetir byte a byte.
    codigos = random.Random("id_item|%d" % semilla).sample(libres, n)
    corte = n if tandas == 1 else (n + 1) // 2
    muestra = []
    for i, (item, codigo) in enumerate(zip(elegidos, codigos)):
        entidad_1, entidad_2, direccion = entidades(item)
        nuevo = dict(item)
        nuevo.update({"id_item": FORMATO_ID % codigo,
                      "tanda": 1 if i < corte else 2,
                      "doble": False,
                      "entidad_1": entidad_1, "entidad_2": entidad_2,
                      "direccion_bronce": direccion})
        muestra.append(nuevo)
    azar_doble = random.Random("doble|%d" % semilla)
    for tanda in (1, 2):
        de_la_tanda = [m for m in muestra if m["tanda"] == tanda]
        # Redondeo hacia arriba en el medio: `round()` redondea al par y
        # 2.5 daría 2.
        k = int(fraccion_doble * len(de_la_tanda) + 0.5)
        for m in azar_doble.sample(de_la_tanda, k):
            m["doble"] = True
    return sorted(muestra, key=lambda m: m["id_item"])


def fila_hoja(item):
    fila = dict.fromkeys(COLUMNAS_HOJA, "")
    fila.update({"id_item": item["id_item"], "oracion": item["oracion"],
                 "entidad_1": item["entidad_1"],
                 "entidad_2": item["entidad_2"]})
    return fila


def fila_llave(item):
    fila = dict((c, item[c]) for c in COLUMNAS_LLAVE)
    fila["doble"] = "si" if item["doble"] else "no"
    return fila


# ---------------------------------------------------------------- escritura

def _escribir_csv(ruta, columnas, filas):
    tmp = ruta + ".tmp"
    # Con BOM, como el paquete de exportación del paso 0: sin él, Excel abre
    # el CSV en cp1252 y los acentos de las oraciones salen rotos (§6).
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    archivos.reemplazar(tmp, ruta)


def _escribir_json(ruta, objeto):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    archivos.reemplazar(tmp, ruta)


def _exigir_mismo_sorteo(ruta_resumen, resumen):
    """Que la carpeta no tenga ya otro sorteo. El mismo se puede repetir: da
    los mismos archivos byte a byte.

    Las muestras excluidas son parte de la identidad: con otras, la población
    y los códigos son otros. Un resumen sin la clave, como los de antes de
    `--excluir-muestra`, cuenta como sin muestras excluidas, y así esa
    carpeta se sigue pudiendo repetir.
    """
    if not os.path.exists(ruta_resumen):
        return
    try:
        with open(ruta_resumen, encoding="utf-8") as f:
            previo = json.load(f)
    except ValueError:
        previo = {}
    campos = ("version", "semilla", "n", "fraccion_doble", "num_tandas",
              "entradas")
    if not isinstance(previo, dict) or any(
            previo.get(c) != resumen[c] for c in campos) or (
            previo.get("muestras_excluidas", [])
            != resumen.get("muestras_excluidas", [])):
        raise ValueError(
            "La carpeta de salida ya tiene un sorteo con otra semilla, otro "
            "tamaño, otras entradas u otras muestras excluidas, y esa hoja "
            "pudo haberse repartido: usa otra carpeta.")


def ejecutar(carpeta, ruta_reservas, n, salida, semilla=SEMILLA,
             fraccion_doble=FRACCION_DOBLE, tandas=TANDAS,
             excluir_muestras=None, log=lambda m: None):
    """Lee la capa y las reservas, excluye, sortea y escribe las salidas en
    `salida`. Devuelve el resumen. Nada se escribe si algo falla antes del
    sorteo, incluido un tamaño mayor que la población o una llave excluida
    que no se puede usar.

    `excluir_muestras` son carpetas de sorteos anteriores sobre la misma
    capa: ni sus artículos, ni las copias de sus oraciones en otros, ni sus
    códigos salen en este. Vacío o None, todo queda como sin la opción.
    """
    ruta_capa = os.path.join(carpeta, NOMBRE_CAPA)
    if not os.path.isfile(ruta_capa):
        raise ValueError("No está %s en la carpeta del flujo." % NOMBRE_CAPA)
    if not os.path.isfile(ruta_reservas):
        raise ValueError("No está el archivo de reservas.")
    # Las huellas van antes de leer: describen lo que se leyó.
    entradas = {
        NOMBRE_CAPA: procedencia.huella(ruta_capa),
        "reservas": procedencia.huella(ruta_reservas),
    }
    if excluir_muestras and not isinstance(excluir_muestras, str):
        # Un generador vacío es verdadero en el `if` de abajo, y el resumen
        # ganaría los motivos de otra muestra en cero.
        excluir_muestras = list(excluir_muestras)
    pmids_excluidos = claves_excluidas = None
    codigos_excluidos, excluidas = (), []
    if excluir_muestras:
        (pmids_excluidos, codigos_excluidos, claves_excluidas,
         excluidas) = _muestras_excluidas(excluir_muestras)
        log("muestras excluidas: %d, con %d PMIDs y %d códigos"
            % (len(excluidas), len(pmids_excluidos), len(codigos_excluidos)))
    reservas, conteos_reservas = entrenamiento.leer_reservas([ruta_reservas])
    items, conteos = poblacion(ruta_capa, reservas, pmids_excluidos,
                               claves_excluidas)
    log("%s: %d oraciones con el par del bronce"
        % (NOMBRE_CAPA, conteos["oraciones_con_par_del_bronce"]))
    for motivo in MOTIVOS:
        if motivo in conteos["exclusiones"]:
            log("  fuera, %s: %d" % (ETIQUETAS[motivo],
                                     conteos["exclusiones"][motivo]))
    log("población tras las exclusiones: %d oraciones" % conteos["poblacion"])

    muestra = sortear(items, n, semilla, fraccion_doble, tandas,
                      codigos_excluidos)
    hojas = (HOJA_TANDA1,) if tandas == 1 else (HOJA_TANDA1, HOJA_TANDA2)
    num_tandas, tandas = tandas, {}
    for tanda in range(1, num_tandas + 1):
        de_la_tanda = [m for m in muestra if m["tanda"] == tanda]
        tandas[str(tanda)] = {"items": len(de_la_tanda),
                              "dobles": sum(1 for m in de_la_tanda
                                            if m["doble"])}
    resumen = {
        "metodo": "muestra-anotacion",
        "version": VERSION,
        "semilla": semilla,
        "n": n,
        "fraccion_doble": fraccion_doble,
        "num_tandas": num_tandas,
        "unidad": "oracion",
        "estratos": "ninguno: aleatorio simple",
        "minimo_contencion": entrenamiento.MINIMO_CONTENCION,
        "oraciones_con_par_del_bronce":
            conteos["oraciones_con_par_del_bronce"],
        "exclusiones": conteos["exclusiones"],
        "poblacion": conteos["poblacion"],
        "reservas": conteos_reservas,
        "tandas": tandas,
        "dobles": sum(t["dobles"] for t in tandas.values()),
        "entradas": entradas,
    }
    if excluidas:
        resumen["muestras_excluidas"] = excluidas

    os.makedirs(salida, exist_ok=True)
    _exigir_mismo_sorteo(os.path.join(salida, RESUMEN), resumen)
    _escribir_csv(os.path.join(salida, HOJA_TANDA1), COLUMNAS_HOJA,
                  [fila_hoja(m) for m in muestra if m["tanda"] == 1])
    if num_tandas == 2:
        _escribir_csv(os.path.join(salida, HOJA_TANDA2), COLUMNAS_HOJA,
                      [fila_hoja(m) for m in muestra if m["tanda"] == 2])
    ordenada = sorted(muestra, key=lambda m: (m["tanda"], m["id_item"]))
    _escribir_csv(os.path.join(salida, LLAVE), COLUMNAS_LLAVE,
                  [fila_llave(m) for m in ordenada])
    _escribir_csv(os.path.join(salida, DOBLES), COLUMNAS_DOBLES,
                  [{"id_item": m["id_item"], "tanda": m["tanda"]}
                   for m in ordenada if m["doble"]])
    resumen["salidas"] = dict(
        (nombre, procedencia.huella(os.path.join(salida, nombre)))
        for nombre in hojas + (LLAVE, DOBLES))
    # El resumen va al final: si está, las anteriores ya se escribieron.
    _escribir_json(os.path.join(salida, RESUMEN), resumen)

    if num_tandas == 1:
        log("sorteo con semilla %d: %d ítems en una sola tanda; %d dobles"
            % (semilla, n, resumen["dobles"]))
    else:
        log("sorteo con semilla %d: %d ítems, %d en la tanda 1 y %d en la "
            "tanda 2; %d dobles" % (semilla, n, tandas["1"]["items"],
                                    tandas["2"]["items"], resumen["dobles"]))
    log("  %s: a quien anota" % HOJA_TANDA1)
    if num_tandas == 2:
        log("  %s: al servidor, para barajarla con las candidatas nuevas"
            % HOJA_TANDA2)
    log("  %s: a quien reparte y adjudica la parte doble" % DOBLES)
    log("  %s: solo para el análisis" % LLAVE)
    log("  %s: semilla, población, exclusiones y huellas" % RESUMEN)
    return resumen
