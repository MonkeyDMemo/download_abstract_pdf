# -*- coding: utf-8 -*-
"""La revisión ciega de la muestra: la cola, las anotaciones y su exportación.

Lo usa la pestaña «Revisión» del tablero para que una sola persona, la
anotadora experta, juzgue los ítems de `hoja_tanda1.csv` con la rúbrica
(`docs/rubrica-anotacion.md`, §2, §4 y §6). La carpeta es la que deja
`grn_verificacion/muestra.py` y la fija `servidor.py --revision` al arrancar,
nunca una petición.

De esa carpeta se lee **un solo archivo**, la hoja, y de ella solo cuatro
columnas: `id_item`, `oracion`, `entidad_1` y `entidad_2`. La llave, los
dobles y el resumen viven al lado y aquí no se nombran a propósito: la llave
dice qué capa propuso cada par y en qué dirección, y una anotadora que lo ve
deja de juzgar la oración para juzgar al pipeline (rúbrica §6, «Lo que la hoja
no lleva»). Lo único que se escribe es `anotaciones.jsonl` y, al exportar,
`anotaciones_exportadas.csv`.

Las anotaciones van en un JSONL de solo anexar, una línea por evento:

- `inicio`: la anotadora abrió el ítem. La hora es la del servidor.
- `guardado`: los valores que dio, con la hora del servidor como fin.

Nada se reescribe. Retomar es releer el archivo: **gana el último `guardado`
de cada ítem** para los valores. El tiempo se mide por tramos: un tramo va
del primer `inicio` posterior al `guardado` anterior del mismo ítem (o del
primero de todos, si es su primer guardado) hasta ese `guardado`.

- `segundos` es la **suma de los tramos** del ítem: corregir un ítem es
  esfuerzo de curación y se suma; el rato entre tramos no cuenta.
- Un `guardado` sin `inicio` propio (corregir tras retomar sin reabrir) no
  aporta tramo, pero **no borra** lo ya medido: una corrección nunca deja al
  ítem sin tiempo. Sin ningún tramo, `inicio` y `segundos` quedan vacíos.
- `inicio` es el del primer tramo y `fin` el último `guardado`; con varios
  tramos, `segundos` no es `fin − inicio`.

Si la anotadora abre un ítem, pasa a otro y vuelve, el tiempo de en medio
cuenta para el primero: es una simplificación a sabiendas, porque medir
foco de ventana desde el navegador es más frágil que la cifra que corrige.

Biblioteca estándar y Python 3.8, como el núcleo. Sin print(): lo que haya
que decir sale como excepción o como valor de retorno.
"""

import csv
import io
import json
import os
import re
import threading
from datetime import datetime, timezone

from grn_comun import archivos

HOJA = "hoja_tanda1.csv"
ANOTACIONES = "anotaciones.jsonl"
EXPORTADA = "anotaciones_exportadas.csv"

PATRON_ID = re.compile(r"^m-\d{4,7}$")

# Las de la rúbrica, §6, en su orden. Es copia de muestra.COLUMNAS_HOJA y no
# un import: servidor.py importa este módulo y no puede arrastrar
# grn_verificacion. Una prueba vigila que las dos listas sigan iguales.
COLUMNAS_HOJA = ["id_item", "oracion", "entidad_1", "entidad_2", "relacion",
                 "direccion", "signo", "tipo", "negada", "especulativa",
                 "comentario"]
COLUMNAS_ITEM = COLUMNAS_HOJA[:4]
COLUMNAS_VALORES = COLUMNAS_HOJA[4:]
COLUMNAS_EXPORTADAS = COLUMNAS_HOJA + ["inicio", "fin", "segundos"]

# Los valores cerrados de §6. El comentario es texto libre.
OPCIONES = {
    "relacion": ("si", "no", "dudoso"),
    "direccion": ("1>2", "2>1", "ninguna"),
    "signo": ("+", "-", "?"),
    "tipo": ("directa", "indirecta", "no_se"),
    "negada": ("si", "no"),
    "especulativa": ("si", "no"),
}

# Holgado para un comentario de la rúbrica («F6; otro organismo: E. coli»)
# y con techo, para que un pegado accidental no infle el JSONL.
MAX_COMENTARIO = 2000

# El servidor atiende cada petición en su hilo. Con una sola anotadora dos
# guardados simultáneos son raros, pero dos líneas entrelazadas en el JSONL
# serían una anotación perdida sin aviso.
_CANDADO = threading.Lock()


class HojaAusente(LookupError):
    """La carpeta no tiene `hoja_tanda1.csv`."""


class HojaInvalida(ValueError):
    """La hoja existe pero no tiene la forma que deja muestra.py."""


def ahora():
    """ISO 8601 UTC al segundo, como `db.ahora()` del paso 0."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ruta_hoja(carpeta):
    return os.path.join(carpeta, HOJA)


def ruta_anotaciones(carpeta):
    return os.path.join(carpeta, ANOTACIONES)


def ruta_exportada(carpeta):
    return os.path.join(carpeta, EXPORTADA)


def id_valido(id_item):
    # fullmatch y no match: el '$' de Python también acepta un salto de línea
    # al final, y 'm-1234\n' llegaría como un id distinto del de la hoja.
    return isinstance(id_item, str) and bool(PATRON_ID.fullmatch(id_item))


# -------------------------------------------------------------------- cola

def posicion(oracion, mencion, evitar=None):
    """[inicio, fin) de la primera aparición de `mencion` como palabra
    entera y con sus mayúsculas, o None.

    Es la idea de `muestra._posicion`, reescrita para no importar el paso 2:
    palabra entera porque `lasR` también está dentro de `lasRI`. Sin el
    respaldo por subcadena de allá: aquí la posición solo sirve para
    resaltar, y resaltar media palabra confunde más que no resaltar.

    `evitar` es el tramo de la otra entidad. Sin él, `oprN` caería dentro de
    `mexEF-oprN` (el guion no es letra) y las dos marcas se pisarían.

    Los índices son de puntos de código de Python; la página corta la
    oración con Array.from, que cuenta igual, y no con los UTF-16 de JS.
    """
    if not mencion:
        return None
    patron = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(mencion)
    for m in re.finditer(patron, oracion):
        if evitar and m.start() < evitar[1] and evitar[0] < m.end():
            continue
        return [m.start(), m.end()]
    return None


def leer_cola(carpeta):
    """Los ítems de la hoja, en su orden, con lo único que la página puede
    mostrar: id, oración, las dos entidades y dónde están.

    Lanza HojaAusente si no hay hoja y HojaInvalida si sus columnas no son
    las de §6, si un `id_item` no tiene la forma `m-NNNN` o si se repite.
    Las columnas de anotación de la hoja se ignoran: vienen vacías de
    muestra.py, y lo que vale es lo que se guarde aquí.
    """
    ruta = ruta_hoja(carpeta)
    if not os.path.isfile(ruta):
        raise HojaAusente(
            "La carpeta de revisión no tiene %s. Es la hoja que deja "
            "`grn_verificacion.cli muestra`." % HOJA)
    # utf-8-sig: la hoja lleva BOM para Excel (§6), y sin quitarlo la
    # primera columna se llamaría '﻿id_item'.
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != COLUMNAS_HOJA:
            raise HojaInvalida(
                "La hoja %s no tiene las columnas de la rúbrica (§6), en "
                "su orden: %s." % (HOJA, ", ".join(COLUMNAS_HOJA)))
        items, vistos = [], set()
        for n, fila in enumerate(lector, start=2):
            id_item = (fila.get("id_item") or "").strip()
            if not id_valido(id_item):
                raise HojaInvalida(
                    "Línea %d de %s: el id_item '%s' no tiene la forma "
                    "m-NNNN." % (n, HOJA, id_item[:40]))
            if id_item in vistos:
                raise HojaInvalida(
                    "Línea %d de %s: el id_item %s está repetido."
                    % (n, HOJA, id_item))
            vistos.add(id_item)
            oracion = fila.get("oracion") or ""
            e1 = (fila.get("entidad_1") or "").strip()
            e2 = (fila.get("entidad_2") or "").strip()
            p1 = posicion(oracion, e1)
            p2 = posicion(oracion, e2, evitar=p1)
            items.append({"id_item": id_item, "oracion": oracion,
                          "entidad_1": e1, "entidad_2": e2,
                          "posiciones": [p1, p2]})
    return items


# ------------------------------------------------------------- anotaciones

def _anexar(carpeta, evento):
    """Una línea más en el JSONL, ya en disco al volver.

    Si la última línea quedó cortada (un corte de luz a media escritura),
    se cierra con un salto antes de seguir: pegada a ella, la línea nueva
    sería ilegible y se perdería con la vieja.
    """
    linea = (json.dumps(evento, ensure_ascii=False, sort_keys=True)
             + "\n").encode("utf-8")
    ruta = ruta_anotaciones(carpeta)
    with _CANDADO:
        with open(ruta, "a+b") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    linea = b"\n" + linea
            # En modo 'a' toda escritura va al final, lea uno donde lea.
            f.write(linea)
            f.flush()
            os.fsync(f.fileno())


def _eventos(carpeta):
    """Los eventos legibles del JSONL, en orden. Lo que no se entiende (una
    línea cortada, un id que no es de la hoja) se salta: el archivo es de
    solo anexar y no hay otra forma de que se descomponga."""
    ruta = ruta_anotaciones(carpeta)
    if not os.path.isfile(ruta):
        return []
    eventos = []
    with io.open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                ev = json.loads(linea)
            except ValueError:
                continue
            if (not isinstance(ev, dict) or not id_valido(ev.get("id_item"))
                    or ev.get("evento") not in ("inicio", "guardado")
                    or not isinstance(ev.get("hora"), str)):
                continue
            if ev["evento"] == "guardado" and not isinstance(
                    ev.get("valores"), dict):
                continue
            eventos.append(ev)
    return eventos


def anotaciones(carpeta):
    """{id_item: {"valores", "inicio", "fin", "segundos"}} con el último
    guardado de cada ítem. `segundos` es un entero o None. Las reglas del
    tiempo están en el docstring del módulo."""
    abierto = {}     # id -> primer inicio desde su último guardado
    vigentes = {}
    for ev in _eventos(carpeta):
        id_item = ev["id_item"]
        if ev["evento"] == "inicio":
            abierto.setdefault(id_item, ev["hora"])
            continue
        valores = dict((c, str(ev["valores"].get(c) or ""))
                       for c in COLUMNAS_VALORES)
        previo = vigentes.get(id_item) or {}
        inicio_tramo = abierto.pop(id_item, None)
        tramo = _segundos(inicio_tramo, ev["hora"])
        segundos = previo.get("segundos")
        if tramo is not None:
            segundos = (segundos or 0) + tramo
        vigentes[id_item] = {"valores": valores,
                             "inicio": previo.get("inicio") or inicio_tramo,
                             "fin": ev["hora"],
                             "segundos": segundos}
    return vigentes


def registrar_inicio(carpeta, id_item, hora=None):
    hora = hora or ahora()
    _anexar(carpeta, {"evento": "inicio", "id_item": id_item, "hora": hora})
    return hora


def guardar(carpeta, id_item, valores, hora=None):
    """Anexa un guardado con valores ya validados (ver validar())."""
    hora = hora or ahora()
    _anexar(carpeta, {"evento": "guardado", "id_item": id_item,
                      "hora": hora, "valores": valores})
    return hora


# -------------------------------------------------------------- validación

def validar(valores):
    """(limpios, errores, avisos) de lo que mandó la anotadora, contra §3.6,
    §4 y §6 de la rúbrica.

    Errores son lo que la hoja no admite: un valor fuera de su lista o una
    combinación que la rúbrica prohíbe («no» con signo, «sí» sin dirección,
    «sí» con negada = sí). Con un error el tablero no guarda nada.

    Avisos son lo que se señala sin bloquear el guardado: «sí» con
    especulativa = sí (abajo, el porqué de la diferencia con la negación) y
    el comentario obligatorio de un «dudoso», que se avisa y no se exige
    porque el caso frontera o la marca que lo vuelven obligatorio no se
    pueden detectar desde aquí y exigir solo uno de los tres casos sería
    engañoso.
    """
    errores, avisos = [], []
    if not isinstance(valores, dict):
        return {}, ["Se esperaba un objeto con los valores de la anotación."], []
    desconocidas = sorted(set(valores) - set(COLUMNAS_VALORES))
    if desconocidas:
        errores.append("Campos que la hoja no tiene: %s."
                       % ", ".join(str(c)[:40] for c in desconocidas))
    limpios = {}
    for columna in COLUMNAS_VALORES:
        v = valores.get(columna)
        if v is None:
            v = ""
        if not isinstance(v, str):
            errores.append("«%s» tiene que ser texto." % columna)
            v = ""
        limpios[columna] = v.strip()

    def en(columna, permitidos, cuando=""):
        if limpios[columna] not in permitidos:
            errores.append("«%s» tiene que ser %s%s." % (
                columna, " o ".join("«%s»" % p for p in permitidos), cuando))

    en("relacion", OPCIONES["relacion"])
    relacion = limpios["relacion"]
    if relacion == "no":
        en("direccion", ("ninguna",), " cuando la relación es «no»")
        for columna in ("signo", "tipo"):
            if limpios[columna]:
                errores.append("«%s» va vacío cuando la relación es «no»."
                               % columna)
    elif relacion in ("si", "dudoso"):
        en("direccion", ("1>2", "2>1"), " cuando la relación es «%s»"
           % relacion)
        en("signo", OPCIONES["signo"])
        en("tipo", OPCIONES["tipo"])
    en("negada", OPCIONES["negada"])
    en("especulativa", OPCIONES["especulativa"])

    # La negación es error y la especulación aviso, aunque el árbol saque a
    # las dos del «sí». La regla de la negación es explícita y no deja hueco:
    # §3.6 y §4 (paso 3) la mandan a «no», con F5 como única salida a
    # «dudoso», y no está entre lo que el asesor tiene que validar (§9). La
    # frontera de la especulación sigue abierta, si «suggest» en indicativo
    # especula (§9, punto 5), y un «sí» con especulativa = sí es una forma de
    # anotar un «suggest» leído como conclusión con reserva: bloquearlo
    # borraría el dato que hace falta para cerrar ese punto.
    #
    # El mensaje da las dos salidas porque desde aquí no se sabe cuál de los
    # dos campos está mal: puede ser un efecto negado anotado «si» (F6) o una
    # negación que no niega el efecto, como la de F7 o la del par de X con Y
    # en «X activates Y but not Z» (§3.6), y ahí lo que se corrige es negada.
    # Ofrecer solo «no» empujaría a «no» un «si» bien anotado; ese «no» se
    # guarda sin aviso, y la precisión medida bajaría sin que nada lo dijera.
    if relacion == "si" and limpios["negada"] == "si":
        errores.append("Con negada = sí, la relación no va «si». Si la "
                       "oración niega el efecto, la relación va «no», o "
                       "«dudoso» si además afirma la unión al promotor (F5); "
                       "si lo negado es otra cosa (F7) u otro par, negada va "
                       "«no» (§3.6 y §4, paso 3).")

    if len(limpios["comentario"]) > MAX_COMENTARIO:
        errores.append("El comentario pasa de %d caracteres." % MAX_COMENTARIO)

    if not errores:
        if relacion == "dudoso" and not limpios["comentario"]:
            avisos.append("La rúbrica pide comentario cuando el ítem es "
                          "«dudoso» (§4, paso 9).")
        if relacion == "si" and limpios["especulativa"] == "si":
            avisos.append("Una relación planteada como posibilidad va "
                          "«dudoso» (§4, paso 4).")
    return limpios, errores, avisos


# ------------------------------------------------------------- exportación

def _segundos(inicio, fin):
    """Segundos enteros de `inicio` a `fin`, o None si falta o no se lee
    alguna de las dos horas."""
    try:
        a = datetime.fromisoformat(inicio)
        b = datetime.fromisoformat(fin)
    except (TypeError, ValueError):
        return None
    return max(0, int((b - a).total_seconds()))


def exportar_csv(carpeta):
    """Escribe `anotaciones_exportadas.csv` y devuelve su ruta.

    Las columnas de la hoja, en su orden, más `inicio`, `fin` y `segundos`;
    una fila por ítem en el orden de la hoja, con las de anotación vacías si
    el ítem no se anotó. UTF-8 con BOM, como la hoja (§6). Se escribe a un
    `.tmp` y se pone en su lugar al final: un corte a media escritura no
    deja un CSV a medias que parezca completo.
    """
    items = leer_cola(carpeta)
    vigentes = anotaciones(carpeta)
    ruta = ruta_exportada(carpeta)
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_EXPORTADAS)
        w.writeheader()
        for item in items:
            fila = dict.fromkeys(COLUMNAS_EXPORTADAS, "")
            for c in COLUMNAS_ITEM:
                fila[c] = item[c]
            hecho = vigentes.get(item["id_item"])
            if hecho:
                fila.update(hecho["valores"])
                fila["inicio"] = hecho["inicio"] or ""
                fila["fin"] = hecho["fin"]
                fila["segundos"] = ("" if hecho["segundos"] is None
                                    else str(hecho["segundos"]))
            w.writerow(fila)
    archivos.reemplazar(tmp, ruta)
    return ruta
