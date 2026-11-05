"""El contexto de cada ítem de una hoja: la oración anterior y la siguiente
del mismo artículo, en un CSV aparte.

    python -m grn_ouroboros.cli contexto --hoja H --llave L \\
        --corrida-bronce 4 [--db DB] --salida salidas/ouroboros/ctx_X.csv
    python -m grn_ouroboros.cli anotar ... --contexto \\
        salidas/ouroboros/ctx_X.csv

Por qué un archivo y no la herramienta `contexto`
=================================================
La herramienta (`herramientas.contexto`) solo existe con Ollama y depende de
que el modelo decida pedirla. En Bedrock no hay herramientas, y el jurado
corre varios modelos sobre la misma hoja: con el contexto escrito una vez,
todos leen exactamente lo mismo y la base se abre una sola vez, en la
máquina donde vive. El archivo lleva oraciones del corpus (públicas), pero
como sale de la hoja de una tanda cae bajo la misma ceguera que ella: va a
`salidas/ouroboros/`, nunca a `salidas/revision/`, y ninguna sesión lo abre.

Qué se lee y qué se escribe
===========================
- De la llave del sorteo, solo la posición de cada ítem (`Recursos.posiciones`:
  PMID, fuente y número de oración); la dirección del bronce, el par y la
  capa no llegan ni a la memoria.
- De la base, el texto de las vecinas, con `grn_bronce.db.vecinas` en solo
  lectura.
- Antes de escribir se comprueba que la oración que la base tiene en la
  posición de cada ítem es la de la hoja (`Recursos.verificar_contexto`): con
  la llave de otra tanda o con otra corrida del bronce, el contexto sería de
  otra oración sin que nada lo notara.

Columnas: `id_item`, `huella_oracion` (16 hexadecimales del sha256 de la
oración con los espacios normalizados), `anterior` y `siguiente` (vacías
donde la oración abre o cierra su sección). `anotar --contexto` exige que el
archivo cubra cada ítem de la hoja con la misma huella de oración: así un
contexto no se cruza con la hoja de otra tanda.

Biblioteca estándar y Python 3.8. No imprime: reporta por `log`.
"""

import csv
import hashlib
import io

from grn_bronce.texto import normalizar_espacios
from grn_comun import archivos

COLUMNAS = ["id_item", "huella_oracion", "anterior", "siguiente"]


def _nada(_mensaje):
    pass


class ErrorContexto(ValueError):
    """El archivo de contexto no es de esta hoja."""


def huella_oracion(oracion):
    texto = normalizar_espacios(oracion or "")
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def construir(items, recursos):
    """Las filas del contexto, en el orden de la hoja. `recursos` es un
    `herramientas.Recursos` con la llave, la base y la corrida del bronce."""
    recursos.verificar_contexto(items)
    filas = []
    for item in items:
        r = recursos.vecinas(item["id_item"])
        filas.append({"id_item": item["id_item"],
                      "huella_oracion": huella_oracion(item["oracion"]),
                      "anterior": r["anterior"] or "",
                      "siguiente": r["siguiente"] or ""})
    return filas


def escribir(ruta, filas):
    """En UTF-8 con BOM, como las hojas, a un `.tmp` que se pone en su lugar
    al final."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    archivos.reemplazar(tmp, ruta)


def leer(ruta):
    """{id_item: fila} del archivo, con el encabezado exacto."""
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != COLUMNAS:
            raise ErrorContexto("El archivo de contexto no tiene las "
                                "columnas %s." % ", ".join(COLUMNAS))
        salida = {}
        for n, fila in enumerate(lector, start=2):
            id_item = (fila["id_item"] or "").strip()
            if not id_item or id_item in salida:
                raise ErrorContexto("Línea %d del contexto: id_item vacío o "
                                    "repetido." % n)
            salida[id_item] = dict((c, fila[c] or "") for c in COLUMNAS)
    return salida


def para_hoja(items, ruta):
    """{id_item: {"anterior", "siguiente"}} para los ítems de la hoja, o
    `ErrorContexto` si el archivo no cubre alguno o trae otra oración. El
    error da conteos, nunca el texto."""
    filas = leer(ruta)
    faltan = otras = 0
    salida = {}
    for item in items:
        fila = filas.get(item["id_item"])
        if fila is None:
            faltan += 1
        elif fila["huella_oracion"] != huella_oracion(item["oracion"]):
            otras += 1
        else:
            salida[item["id_item"]] = {"anterior": fila["anterior"],
                                       "siguiente": fila["siguiente"]}
    if faltan or otras:
        raise ErrorContexto(
            "El contexto no es de esta hoja: %d ítems sin contexto y %d con "
            "otra oración." % (faltan, otras))
    return salida


def ejecutar(items, recursos, ruta_salida, log=_nada):
    """Construye y escribe el contexto de los ítems; devuelve los conteos."""
    filas = construir(items, recursos)
    escribir(ruta_salida, filas)
    conteos = {"items": len(filas),
               "con_anterior": sum(1 for f in filas if f["anterior"]),
               "con_siguiente": sum(1 for f in filas if f["siguiente"])}
    log("Contexto de %d ítems: %d con oración anterior y %d con siguiente."
        % (conteos["items"], conteos["con_anterior"],
           conteos["con_siguiente"]))
    return conteos
