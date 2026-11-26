"""El lector por artículo, fase 0: el artículo en bloques de oraciones
numeradas, la forma de la respuesta y la comprobación de sus citas.

Qué es
======
Ouroboros v0 juzga una oración y un par que el bronce ya eligió. El lector
recibe el artículo como lo partió el bronce y devuelve las relaciones de
regulación que el artículo afirma, cada una con las oraciones que la
sostienen. El plan, lo que se espera de él y cómo se mide están en
`docs/agente-curador.md`. Es exploratorio y de la tesis: no es un paso de
`flujo.py`, y ninguna cifra del servicio social depende de él.

Aquí no hay modelo. Este módulo es la parte determinista, que se prueba sin
Strands y sin red:

- `leer_articulo` y `bloques`: el artículo en oraciones con identificador
  (`a3`, `x120`, `p45`: la fuente y el número de oración del bronce), partido
  en bloques que caben en una llamada;
- `texto_bloque`: lo que lee el modelo;
- `esquema` y `validar_respuesta`: la respuesta, una lista de relaciones con
  etiquetas cerradas;
- `verificar`: cada relación cita oraciones que están en el bloque, nombra al
  regulador y al blanco como aparecen en ellas y se lleva a locus con el
  diccionario del bronce. Lo que no pasa se marca y no entra a la red.

Por qué se cita por identificador y no por fragmento
====================================================
El juez copia un fragmento de la oración y a veces lo altera: el veredicto
queda marcado como `evidencia_invalida`. Aquí cada oración llega numerada y
la cita es su número. Comprobar que existe es exacto, y la oración citada es
la que el bronce guardó, con su posición, para el visor y para el juez.

Las etiquetas
=============
`efecto` usa las clases de `etapa2/red.py` (`activates`, `represses`,
`regulates`), para que su red se lea con el contraste y el visor que ya
existen. `tipo` usa los valores de la rúbrica del experto (`directa`,
`indirecta`, `no_se`).

Biblioteca estándar y Python 3.8. No imprime.
"""

import collections
import hashlib
import re

from grn_bronce import db as _bdb
from grn_bronce import identificar as _identificar
from grn_ouroboros import herramientas as _herramientas
from grn_ouroboros import rubrica as _rubrica

VERSION = 0
METODO = "ouroboros-curador-v0"
VERSION_ESQUEMA = 1

# La letra de cada fuente del bronce en el identificador de una oración.
PREFIJOS = collections.OrderedDict(
    [("abstract", "a"), ("xml", "x"), ("pdf", "p")])
EFECTOS = ("activates", "represses", "regulates")
TIPOS = tuple(_rubrica.OPCIONES["tipo"])
# Las secciones de las que el bronce no saca candidatas (métodos, referencias,
# agradecimientos): el lector tampoco las lee. Son 4 de cada 10 oraciones.
SECCIONES_FUERA = _identificar.SECCIONES_FUERA

# Un artículo mediano con texto completo ronda los 46 mil caracteres (25-nov,
# corrida 27): con 60 mil, dos de cada tres van en una sola llamada.
MAX_CARACTERES = 60000
# Una relación repartida en dos oraciones cita las dos; más de tres citas es
# un párrafo, y deja de ser evidencia que alguien pueda revisar.
MAX_CITAS = 3
MAX_RELACIONES = 200

# El orden importa: una relación cae en el primer estado que le aplica.
ESTADOS = ("cita_inexistente", "entidad_fuera_de_la_cita", "sin_locus",
           "ambigua", "mismo_gen", "valida")

Oracion = collections.namedtuple("Oracion", "id fuente seccion num texto")


class RespuestaInvalida(ValueError):
    """La respuesta del modelo no tiene la forma de `esquema()`."""


def identificador(fuente, num_oracion):
    """`a3`, `x120` o `p45`. Una fuente que el bronce no escribe es un
    error: el identificador tiene que poder deshacerse sin ambigüedad."""
    if fuente not in PREFIJOS:
        raise ValueError("Fuente de texto desconocida: %r." % (fuente,))
    return "%s%d" % (PREFIJOS[fuente], int(num_oracion))


def articulo(unidades, fuera=SECCIONES_FUERA):
    """[Oracion] desde las tuplas de `grn_bronce.db.unidades_de`, sin las
    secciones de `fuera`. Los identificadores no se recorren: una oración
    conserva el número que le dio el bronce."""
    return [Oracion(identificador(fuente, num), fuente, seccion or "",
                    int(num), texto)
            for fuente, seccion, num, texto in unidades
            if (seccion or "") not in fuera]


def leer_articulo(con, corrida_id, pmid, fuera=SECCIONES_FUERA):
    """El artículo como lo partió el bronce en esa corrida, en orden de
    lectura y sin las secciones de `fuera`. Lista vacía si la corrida no lo
    leyó."""
    return articulo(_bdb.unidades_de(con, corrida_id, pmid), fuera)


def _largo(oracion):
    # Lo que ocupa en `texto_bloque`: «[x12] », el texto y el salto.
    return len(oracion.id) + len(oracion.texto) + 4


def bloques(oraciones, max_caracteres=MAX_CARACTERES):
    """El artículo en bloques de a lo más `max_caracteres`, sin partir una
    sección mientras quepa.

    Las oraciones seguidas de una misma fuente y sección forman un grupo. Los
    grupos se van juntando en orden; el que no cabe en lo que queda abre
    bloque, y el que no cabe ni solo se parte entre oraciones. Una oración
    nunca se parte, aunque sola pase del tope. Cada oración queda en un
    bloque y solo en uno, en el orden del artículo.
    """
    if max_caracteres < 1:
        raise ValueError("max_caracteres tiene que ser positivo.")
    grupos = []
    for o in oraciones:
        if grupos and (grupos[-1][-1].fuente, grupos[-1][-1].seccion) == (
                o.fuente, o.seccion):
            grupos[-1].append(o)
        else:
            grupos.append([o])
    salida, actual, ocupado = [], [], 0
    for grupo in grupos:
        largo = sum(_largo(o) for o in grupo)
        if actual and ocupado + largo > max_caracteres:
            salida.append(actual)
            actual, ocupado = [], 0
        if largo <= max_caracteres:
            actual.extend(grupo)
            ocupado += largo
            continue
        for o in grupo:
            if actual and ocupado + _largo(o) > max_caracteres:
                salida.append(actual)
                actual, ocupado = [], 0
            actual.append(o)
            ocupado += _largo(o)
    if actual:
        salida.append(actual)
    return salida


def texto_bloque(bloque):
    """Lo que lee el modelo: cada oración en su renglón, con su
    identificador entre corchetes, y un encabezado donde cambia la sección."""
    renglones, anterior = [], None
    for o in bloque:
        donde = (o.fuente, o.seccion)
        if donde != anterior:
            if renglones:
                renglones.append("")
            renglones.append("## %s" % (
                "RESUMEN" if o.fuente == "abstract"
                else (o.seccion or "(sin sección)")))
            anterior = donde
        renglones.append("[%s] %s" % (o.id, o.texto))
    return "\n".join(renglones) + "\n"


def huella_bloque(bloque):
    """16 hexadecimales del sha256 de lo que lee el modelo."""
    return hashlib.sha256(
        texto_bloque(bloque).encode("utf-8")).hexdigest()[:16]


def esquema():
    """El JSON Schema de la respuesta. Las citas van primero: el modelo
    señala las oraciones antes de decidir las etiquetas."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["relaciones"],
        "properties": {"relaciones": {
            "type": "array",
            "maxItems": MAX_RELACIONES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["oraciones", "regulador", "blanco", "efecto",
                             "tipo"],
                "properties": collections.OrderedDict([
                    ("oraciones", {"type": "array", "minItems": 1,
                                   "maxItems": MAX_CITAS,
                                   "items": {"type": "string"}}),
                    ("regulador", {"type": "string", "minLength": 1}),
                    ("blanco", {"type": "string", "minLength": 1}),
                    ("efecto", {"type": "string", "enum": list(EFECTOS)}),
                    ("tipo", {"type": "string", "enum": list(TIPOS)}),
                ]),
            },
        }},
    }


def _texto(valor, campo):
    if not isinstance(valor, str) or not valor.strip():
        raise RespuestaInvalida("«%s» tiene que ser un texto no vacío."
                                % campo)
    return valor.strip()


def validar_respuesta(objeto):
    """Las relaciones de una respuesta, limpias y sin repetir.

    Lanza `RespuestaInvalida` si la forma no es la de `esquema()`: una
    respuesta a medias no se aprovecha por partes, porque no se sabría qué
    faltó. Dos relaciones iguales (mismas citas, nombres y etiquetas) cuentan
    una vez; el orden de las citas no importa.
    """
    if not isinstance(objeto, dict) or set(objeto) != {"relaciones"}:
        raise RespuestaInvalida("La respuesta es un objeto con «relaciones» "
                                "y nada más.")
    lista = objeto["relaciones"]
    if not isinstance(lista, list) or len(lista) > MAX_RELACIONES:
        raise RespuestaInvalida("«relaciones» es una lista de a lo más %d."
                                % MAX_RELACIONES)
    campos = {"oraciones", "regulador", "blanco", "efecto", "tipo"}
    salida, vistas = [], set()
    for r in lista:
        if not isinstance(r, dict) or set(r) != campos:
            raise RespuestaInvalida("Cada relación lleva exactamente: %s."
                                    % ", ".join(sorted(campos)))
        citas = r["oraciones"]
        if (not isinstance(citas, list) or not 1 <= len(citas) <= MAX_CITAS
                or len(set(citas)) != len(citas)):
            raise RespuestaInvalida("«oraciones» lleva de 1 a %d "
                                    "identificadores distintos." % MAX_CITAS)
        citas = [_texto(c, "oraciones").strip("[]") for c in citas]
        if r["efecto"] not in EFECTOS or r["tipo"] not in TIPOS:
            raise RespuestaInvalida("«efecto» o «tipo» fuera de sus valores.")
        limpia = collections.OrderedDict([
            ("oraciones", citas),
            ("regulador", _texto(r["regulador"], "regulador")),
            ("blanco", _texto(r["blanco"], "blanco")),
            ("efecto", r["efecto"]), ("tipo", r["tipo"])])
        llave = (tuple(sorted(citas)), limpia["regulador"], limpia["blanco"],
                 limpia["efecto"], limpia["tipo"])
        if llave not in vistas:
            vistas.add(llave)
            salida.append(limpia)
    return salida


def _aparece(nombre, textos):
    """Si el nombre está escrito en alguna de las oraciones, como palabra
    entera y sin distinguir mayúsculas: el gen `fooR` y su proteína `FooR`
    son la misma entidad (rúbrica §2)."""
    patron = re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])"
                        % re.escape(nombre), re.I)
    return any(patron.search(t) for t in textos)


def _locus(nombre, recursos):
    """(locus, estado) con el diccionario del bronce: un solo locus o nada."""
    coincidencias = _herramientas.buscar_locus(
        nombre, recursos)["coincidencias"]
    locus = sorted(set(c["locus_tag"] for c in coincidencias
                       if c["locus_tag"]))
    if len(locus) == 1:
        return locus[0], None
    return "", ("ambigua" if len(locus) > 1 else "sin_locus")


def verificar(relacion, bloque, recursos):
    """La relación con su `estado` (uno de `ESTADOS`) y sus dos locus.

    En orden: las citas están en el bloque; el regulador y el blanco están
    escritos en alguna oración citada (cada uno puede estar en una distinta:
    eso es una relación repartida en dos oraciones); cada nombre lleva a un
    solo locus del diccionario; y no son el mismo gen. Solo `valida` entra a
    la red; las demás se cuentan, porque dicen qué le falta al lector o al
    diccionario.
    """
    por_id = dict((o.id, o) for o in bloque)
    salida = collections.OrderedDict(relacion)
    salida.update({"locus_regulador": "", "locus_blanco": ""})
    if any(c not in por_id for c in relacion["oraciones"]):
        salida["estado"] = "cita_inexistente"
        return salida
    textos = [por_id[c].texto for c in relacion["oraciones"]]
    if not (_aparece(relacion["regulador"], textos)
            and _aparece(relacion["blanco"], textos)):
        salida["estado"] = "entidad_fuera_de_la_cita"
        return salida
    locus_r, falla_r = _locus(relacion["regulador"], recursos)
    locus_b, falla_b = _locus(relacion["blanco"], recursos)
    salida.update({"locus_regulador": locus_r, "locus_blanco": locus_b})
    fallas = [f for f in (falla_r, falla_b) if f]
    if fallas:
        salida["estado"] = ("sin_locus" if "sin_locus" in fallas
                            else "ambigua")
    elif locus_r == locus_b:
        salida["estado"] = "mismo_gen"
    else:
        salida["estado"] = "valida"
    return salida


def conteos(verificadas):
    """Cuántas relaciones cayeron en cada estado, con todos los estados."""
    cuenta = collections.Counter(v["estado"] for v in verificadas)
    return collections.OrderedDict((e, cuenta[e]) for e in ESTADOS)
