"""La hoja que se anota, la llave de la calibración y su comparación.

La calibración (`docs/calibracion-anotacion.md`) son 27 ítems sintéticos y
públicos, escritos para la sesión con el experto: ninguno sale del corpus.
Por eso son lo único con lo que se ajusta el prompt de Ouroboros
(`docs/decisiones.md`, «Ouroboros v0»), y la única referencia que este
paquete lee. Los juicios del experto sobre las tandas no pasan por aquí: su
acuerdo se mide en `grn_verificacion/concordancia.py`.

- `leer_hoja`: los ítems de una hoja de la rúbrica (§6), la de la calibración
  o la de una tanda. Rechaza una hoja que ya trae anotaciones: el juez recibe
  la hoja en blanco, como el experto.
- `leer_llave`: la tabla «La llave» del documento de calibración, donde «—»
  es celda vacía.
- `comparar`: el acuerdo por campo y los desacuerdos por ítem.

Biblioteca estándar y Python 3.8.
"""

import csv
import io
import os
import re

from grn_ouroboros import rubrica

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_LLAVE = os.path.join(_RAIZ, "docs", "calibracion-anotacion.md")
RUTA_HOJA = os.path.join(_RAIZ, "docs", "calibracion-hoja.csv")

# `c01` en la calibración, `m-1234` en las tandas. Holgado a propósito, pero
# sin espacios ni separadores: el id viaja a nombres de caso y a la caché.
PATRON_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")

TITULO_LLAVE = "## La llave"
VACIO = "—"   # el guion largo de la tabla: celda vacía


class ErrorHoja(ValueError):
    """La hoja no tiene la forma de la rúbrica §6."""


def leer_hoja(ruta):
    """[{id_item, oracion, entidad_1, entidad_2}] en el orden de la hoja.

    Las columnas tienen que ser las de la rúbrica, en su orden. Los errores
    dicen la línea y nunca el texto de la oración: el mensaje acaba en la
    terminal o en una bitácora.
    """
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != rubrica.COLUMNAS_HOJA:
            raise ErrorHoja("La hoja no tiene las columnas de la rúbrica "
                            "(§6), en su orden: %s."
                            % ", ".join(rubrica.COLUMNAS_HOJA))
        items, vistos = [], set()
        for n, fila in enumerate(lector, start=2):
            id_item = (fila.get("id_item") or "").strip()
            if not PATRON_ID.fullmatch(id_item):
                raise ErrorHoja("Línea %d: el id_item no tiene una forma "
                                "válida." % n)
            if id_item in vistos:
                raise ErrorHoja("Línea %d: el id_item %s está repetido."
                                % (n, id_item))
            vistos.add(id_item)
            # Si la hoja ya trae juicios, no es la hoja en blanco que recibe
            # el experto: es la anotada. El juez no la necesita, y leerla
            # sería la forma más corta de que un juicio llegara a un prompt.
            if any((fila.get(c) or "").strip()
                   for c in rubrica.COLUMNAS_VALORES):
                raise ErrorHoja("Línea %d: la hoja ya trae anotaciones. "
                                "Ouroboros recibe la hoja sin anotar." % n)
            oracion = fila.get("oracion") or ""
            e1 = (fila.get("entidad_1") or "").strip()
            e2 = (fila.get("entidad_2") or "").strip()
            if not oracion.strip() or not e1 or not e2:
                raise ErrorHoja("Línea %d: falta la oración o una entidad."
                                % n)
            items.append({"id_item": id_item, "oracion": oracion,
                          "entidad_1": e1, "entidad_2": e2})
    if not items:
        raise ErrorHoja("La hoja no tiene ítems.")
    return items


def _celdas(linea):
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def leer_llave(ruta=RUTA_LLAVE):
    """{id: {entidad_1, entidad_2, relacion, direccion, signo, tipo, negada,
    especulativa}} desde la tabla «La llave».

    La columna «anotación» trae los seis valores en el orden de la hoja,
    separados por comas; «—» es celda vacía. La tabla se busca por su título
    y sus columnas por su encabezado, no por posición: si el documento gana
    una columna, la lectura no se corre de lugar.
    """
    with io.open(ruta, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    try:
        inicio = lineas.index(TITULO_LLAVE)
    except ValueError:
        raise ValueError("El documento de calibración no tiene la sección "
                         "«La llave».")
    tabla = []
    for linea in lineas[inicio + 1:]:
        if linea.startswith("#"):
            break
        if linea.lstrip().startswith("|"):
            tabla.append(linea)
        elif tabla:
            break
    if len(tabla) < 3:
        raise ValueError("La sección «La llave» no tiene tabla.")
    encabezado = [c.lower() for c in _celdas(tabla[0])]
    for nombre in ("id", "entidad 1", "entidad 2", "anotación"):
        if nombre not in encabezado:
            raise ValueError("La tabla de la llave no tiene la columna «%s»."
                             % nombre)
    i_id = encabezado.index("id")
    i_e1 = encabezado.index("entidad 1")
    i_e2 = encabezado.index("entidad 2")
    i_an = encabezado.index("anotación")
    llave = {}
    for linea in tabla[2:]:
        celdas = _celdas(linea)
        if len(celdas) != len(encabezado):
            raise ValueError("Una fila de la llave no tiene %d columnas."
                             % len(encabezado))
        valores = [v.strip() for v in celdas[i_an].split(",")]
        if len(valores) != len(rubrica.CAMPOS_CERRADOS):
            raise ValueError("La anotación de %s no trae %d valores."
                             % (celdas[i_id], len(rubrica.CAMPOS_CERRADOS)))
        fila = {"entidad_1": celdas[i_e1], "entidad_2": celdas[i_e2]}
        for campo, valor in zip(rubrica.CAMPOS_CERRADOS, valores):
            fila[campo] = "" if valor == VACIO else valor
        if celdas[i_id] in llave:
            raise ValueError("El id %s está dos veces en la llave."
                             % celdas[i_id])
        llave[celdas[i_id]] = fila
    return llave


def valores_de(fila):
    """Los seis campos cerrados de una fila de la llave, sin las entidades."""
    return dict((c, fila[c]) for c in rubrica.CAMPOS_CERRADOS)


def leer_anotaciones(ruta):
    """{id_item: valores o None} de un CSV con las columnas de la hoja, como
    el `anotaciones.csv` de Ouroboros. None es una abstención: la relación
    vacía y todo lo demás también.

    Un valor que no pasa la rúbrica detiene la lectura: en lo que escribe
    Ouroboros sería un defecto, no un juicio.
    """
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != rubrica.COLUMNAS_HOJA:
            raise ErrorHoja("La anotación no tiene las columnas de la hoja, "
                            "en su orden.")
        salida = {}
        for n, fila in enumerate(lector, start=2):
            id_item = (fila.get("id_item") or "").strip()
            if id_item in salida:
                raise ErrorHoja("Línea %d: %s repetido." % (n, id_item))
            valores = dict((c, (fila.get(c) or "").strip())
                           for c in rubrica.COLUMNAS_VALORES)
            if not valores["relacion"]:
                if any(valores[c] for c in rubrica.CAMPOS_CERRADOS):
                    raise ErrorHoja("Línea %d: sin relación pero con otros "
                                    "valores." % n)
                salida[id_item] = None
                continue
            limpios, errores, _avisos = rubrica.validar_valores(valores)
            if errores:
                raise ErrorHoja("Línea %d: %s" % (n, " ".join(errores)))
            salida[id_item] = limpios
    return salida


def comparar(anotaciones, llave):
    """El acuerdo por campo y los desacuerdos por ítem.

    `anotaciones` es {id: valores o None}; `llave`, la de `leer_llave`. Se
    compara sobre los ítems de la anotación, que tienen que estar todos en la
    llave: la calibración 2 es un subconjunto de 12. Una abstención cuenta
    como desacuerdo en los seis campos, la misma regla que en la evaluación.
    """
    ajenos = sorted(set(anotaciones) - set(llave))
    if ajenos:
        raise ValueError("Hay ítems que no están en la llave de la "
                         "calibración: %s." % ", ".join(ajenos[:5]))
    ids = sorted(anotaciones)
    por_campo = dict((c, 0) for c in rubrica.CAMPOS_CERRADOS)
    por_item = {}
    for id_item in ids:
        valores = anotaciones[id_item]
        esperado = llave[id_item]
        if valores is None:
            por_item[id_item] = {"abstencion": True,
                                 "difiere": list(rubrica.CAMPOS_CERRADOS)}
            continue
        difiere = [c for c in rubrica.CAMPOS_CERRADOS
                   if valores.get(c, "") != esperado[c]]
        for c in rubrica.CAMPOS_CERRADOS:
            if c not in difiere:
                por_campo[c] += 1
        por_item[id_item] = {"abstencion": False, "difiere": difiere}
    return {
        "n": len(ids),
        "por_campo": dict((c, {"k": k, "n": len(ids)})
                          for c, k in por_campo.items()),
        "por_item": por_item,
        "abstenciones": sum(1 for r in por_item.values() if r["abstencion"]),
        "identicos": sum(1 for r in por_item.values() if not r["difiere"]),
    }


def referencia_si_es_calibracion(items, ruta_hoja=RUTA_HOJA,
                                 ruta_llave=RUTA_LLAVE):
    """{id: valores de la llave} si los ítems son de la hoja de calibración
    (los mismos ids, oraciones y entidades, o un subconjunto), o None.

    Es la única referencia que Ouroboros usa para sus evaluadores: con
    cualquier otra hoja, como una tanda, no hay referencia y los evaluadores
    por campo quedan como «no aplica».
    """
    if not os.path.isfile(ruta_hoja) or not os.path.isfile(ruta_llave):
        return None
    calibracion = dict((it["id_item"], it) for it in leer_hoja(ruta_hoja))
    for item in items:
        propio = calibracion.get(item["id_item"])
        if propio is None or any(propio[c] != item[c]
                                 for c in rubrica.COLUMNAS_ITEM):
            return None
    llave = leer_llave(ruta_llave)
    return dict((item["id_item"], valores_de(llave[item["id_item"]]))
                for item in items)
