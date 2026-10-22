"""La muestra ciega para anotar con ayudantes: población, exclusiones, sorteo
y sus salidas (`docs/rubrica-anotacion.md`, §6 a §8).

    python -m grn_verificacion.cli muestra --carpeta C --reservas R --n N \
        --salida D [--semilla S] [--fraccion-doble F]

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
   (`entrenamiento._reservada`). El bronce y el conjunto ciego no siempre
   cortan igual la oración.
4. `sin_par_directo`: el bronce la orientó, pero su par no está entre los que
   vio el clasificador (en la corrida 4, el bronce escribe `rsmZY` y el par
   `rsmYZ`). Sin `id_par` no se puede medir la plata sobre ella.
5. `repetida`: el mismo texto canónico (`entrenamiento.canonico`) que otra
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
  huellas de las entradas y las salidas; no lleva oraciones ni PMIDs.

Las hojas llevan exactamente las columnas del §6. Las entidades van en el
orden en que aparecen en la oración y escritas como en ella, que es lo que
pide el §6; ese orden lo da el texto, no la orientación del bronce. Las hojas
no llevan PMID, sección, tanda, predicciones, umbrales, `signo_sugerido`, ni
la dirección del bronce o de la sintaxis. Los CSV van en UTF-8 con BOM, para
que Excel lea bien los acentos.

Una carpeta de salida que ya tiene un sorteo con otra semilla, otro tamaño u
otras entradas no se sobrescribe: esa hoja pudo haberse repartido ya.

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

MOTIVOS = ["pmid_reservado", "oracion_reservada_igual",
           "oracion_reservada_contenida", "sin_par_directo", "repetida"]

ETIQUETAS = {
    "pmid_reservado": "PMID reservado",
    "oracion_reservada_igual": "oración reservada, igual",
    "oracion_reservada_contenida": "oración reservada, contenida (%d "
                                   "caracteres o más)"
                                   % entrenamiento.MINIMO_CONTENCION,
    "sin_par_directo": "el par del bronce no llegó al clasificador",
    "repetida": "mismo texto que otra que ya entró",
}


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
            pmid = entrenamiento._pmid_valido(fila["pmid"])
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


def _motivo(item, pmids, reservadas, vistas):
    if item["pmid"] in pmids:
        return "pmid_reservado"
    oracion = item["normalizada"]
    if oracion in reservadas:
        return "oracion_reservada_igual"
    if entrenamiento._reservada(oracion, reservadas):
        return "oracion_reservada_contenida"
    if not item["directo"]:
        return "sin_par_directo"
    if entrenamiento.canonico(oracion) in vistas:
        return "repetida"
    return None


def poblacion(ruta_capa, reservas):
    """(ítems, conteos): las oraciones sorteables en su orden estable, y
    cuántas había y cuántas quedaron fuera por cada motivo.

    `reservas` es el primer valor de `entrenamiento.leer_reservas`.
    """
    oraciones = _leer_capa(ruta_capa)
    pmids = reservas.get("pmids") or set()
    reservadas = reservas.get("oraciones") or set()
    fuera = dict.fromkeys(MOTIVOS, 0)
    vistas = set()
    items = []
    for item in sorted(oraciones.values(), key=_orden):
        motivo = _motivo(item, pmids, reservadas, vistas)
        if motivo:
            fuera[motivo] += 1
            continue
        vistas.add(entrenamiento.canonico(item["normalizada"]))
        items.append(item)
    return items, {"oraciones_con_par_del_bronce": len(oraciones),
                   "exclusiones": fuera, "poblacion": len(items)}


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


def sortear(items, n, semilla=SEMILLA, fraccion_doble=FRACCION_DOBLE):
    """Los `n` ítems sorteados, ordenados por `id_item`, cada uno con su
    tanda, si es doble, sus entidades y la dirección del bronce.

    `items` tiene que venir en el orden estable de `poblacion()`. Un tamaño
    mayor que la población es un error y no se sortea nada.
    """
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("El tamaño de la muestra tiene que ser un entero "
                         "positivo.")
    if not 0 <= fraccion_doble <= 1:
        raise ValueError("La fracción doble tiene que estar entre 0 y 1.")
    if n > len(items):
        raise ValueError(
            "Se pidieron %d ítems y la población, tras las exclusiones, "
            "tiene %d: no se sortea." % (n, len(items)))
    elegidos = random.Random(semilla).sample(items, n)
    ancho = max(4, len(str(n)) + 1)
    codigos = random.Random("id_item|%d" % semilla).sample(
        range(10 ** (ancho - 1), 10 ** ancho), n)
    corte = (n + 1) // 2
    muestra = []
    for i, (item, codigo) in enumerate(zip(elegidos, codigos)):
        entidad_1, entidad_2, direccion = entidades(item)
        nuevo = dict(item)
        nuevo.update({"id_item": "m-%d" % codigo,
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
    los mismos archivos byte a byte."""
    if not os.path.exists(ruta_resumen):
        return
    try:
        with open(ruta_resumen, encoding="utf-8") as f:
            previo = json.load(f)
    except ValueError:
        previo = {}
    campos = ("version", "semilla", "n", "fraccion_doble", "entradas")
    if not isinstance(previo, dict) or any(
            previo.get(c) != resumen[c] for c in campos):
        raise ValueError(
            "La carpeta de salida ya tiene un sorteo con otra semilla, otro "
            "tamaño u otras entradas, y esa hoja pudo haberse repartido: usa "
            "otra carpeta.")


def ejecutar(carpeta, ruta_reservas, n, salida, semilla=SEMILLA,
             fraccion_doble=FRACCION_DOBLE, log=lambda m: None):
    """Lee la capa y las reservas, excluye, sortea y escribe las salidas en
    `salida`. Devuelve el resumen. Nada se escribe si algo falla antes del
    sorteo, incluido un tamaño mayor que la población."""
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
    reservas, conteos_reservas = entrenamiento.leer_reservas([ruta_reservas])
    items, conteos = poblacion(ruta_capa, reservas)
    log("%s: %d oraciones con el par del bronce"
        % (NOMBRE_CAPA, conteos["oraciones_con_par_del_bronce"]))
    for motivo in MOTIVOS:
        log("  fuera, %s: %d" % (ETIQUETAS[motivo],
                                 conteos["exclusiones"][motivo]))
    log("población tras las exclusiones: %d oraciones" % conteos["poblacion"])

    muestra = sortear(items, n, semilla, fraccion_doble)
    tandas = {}
    for tanda in (1, 2):
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

    os.makedirs(salida, exist_ok=True)
    _exigir_mismo_sorteo(os.path.join(salida, RESUMEN), resumen)
    _escribir_csv(os.path.join(salida, HOJA_TANDA1), COLUMNAS_HOJA,
                  [fila_hoja(m) for m in muestra if m["tanda"] == 1])
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
        for nombre in (HOJA_TANDA1, HOJA_TANDA2, LLAVE, DOBLES))
    # El resumen va al final: si está, las anteriores ya se escribieron.
    _escribir_json(os.path.join(salida, RESUMEN), resumen)

    log("sorteo con semilla %d: %d ítems, %d en la tanda 1 y %d en la "
        "tanda 2; %d dobles" % (semilla, n, tandas["1"]["items"],
                                tandas["2"]["items"], resumen["dobles"]))
    log("  %s: a los ayudantes" % HOJA_TANDA1)
    log("  %s: al servidor, para barajarla con las candidatas nuevas"
        % HOJA_TANDA2)
    log("  %s: a quien reparte y adjudica la parte doble" % DOBLES)
    log("  %s: solo para el análisis" % LLAVE)
    log("  %s: semilla, población, exclusiones y huellas" % RESUMEN)
    return resumen
