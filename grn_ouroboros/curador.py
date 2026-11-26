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

Aquí no se importa ningún modelo: el lector llega inyectado, como el
anotador en `anotar.py` (un callable `lector(texto) -> respuesta`, que con
Bedrock arma `agente.crear_lector` y en las pruebas es un falso). Este módulo
es la parte determinista, que se prueba sin Strands y sin red:

- `leer_articulo` y `bloques`: el artículo en oraciones con identificador
  (`a3`, `x120`, `p45`: la fuente y el número de oración del bronce), partido
  en bloques que caben en una llamada;
- `texto_bloque`: lo que lee el modelo;
- `esquema` y `validar_respuesta`: la respuesta, una lista de relaciones con
  etiquetas cerradas;
- `verificar`: cada relación cita oraciones que están en el bloque, nombra al
  regulador y al blanco como aparecen en ellas y se lleva a locus con el
  diccionario del bronce. Lo que no pasa se marca y no entra a la red;
- `ejecutar`: la corrida sobre una lista de artículos, con caché por
  entradas, y sus salidas (`lecturas.jsonl`, `relaciones.tsv`,
  `corrida.json`).

La caché
========
La llave de cada llamada es el sha256 de lo que decide la respuesta: el
mensaje (el bloque con sus identificadores), la huella del prompt, el
proveedor, el modelo y la región, la decodificación y la versión del esquema.
Lo mismo dos veces no vuelve a llamar al modelo. Lo que se guarda es el texto
que devolvió el modelo. Leer ese texto (`interpretar`) y comprobar las citas
(`verificar`) no entran a la llave: se rehacen al escribir las salidas, así
que un diccionario nuevo o una regla de forma corregida cambian
`relaciones.tsv` sin pagar otra lectura.

Si el lector lanza una excepción, la corrida se detiene: «no pude preguntar»
no es una respuesta. Lo ya leído queda en `lecturas.jsonl`, y volver a correr
lo retoma.

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
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import re
import threading

from grn_bronce import db as _bdb
from grn_bronce import identificar as _identificar
from grn_bronce import operones as _operones
from grn_ouroboros import anotar as _anotar
from grn_ouroboros import gasto as _gasto
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
           "ambigua", "regulador_operon", "mismo_gen", "valida")

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


# Los guiones que no son el de ASCII (gpt-oss escribe U+2011 donde el texto
# trae «-», y los PDF traen rayas donde el autor puso un guion) y los espacios
# que no son el espacio. `mexAB‑oprM` y `mexAB-oprM` son el mismo nombre.
_GUIONES = re.compile(u"[\u2010-\u2015\u2212\u00ad\ufe58\ufe63\uff0d]")
_ESPACIOS = re.compile(u"[\u00a0\u2000-\u200b\u202f\u205f\u3000]")


def normalizar(texto):
    """El texto con guiones y espacios de ASCII. Solo para comparar nombres:
    lo que se guarda y lo que lee el modelo no se toca."""
    return _ESPACIOS.sub(" ", _GUIONES.sub("-", texto or ""))


def _texto(valor, campo):
    if not isinstance(valor, str) or not valor.strip():
        raise RespuestaInvalida("«%s» tiene que ser un texto no vacío."
                                % campo)
    return " ".join(normalizar(valor).split())


_CAMPOS = frozenset(("oraciones", "regulador", "blanco", "efecto", "tipo"))


def _limpiar(r):
    """Una relación con la forma de `esquema()`, limpia; si no la tiene,
    `RespuestaInvalida`."""
    if not isinstance(r, dict) or set(r) != _CAMPOS:
        raise RespuestaInvalida("Cada relación lleva exactamente: %s."
                                % ", ".join(sorted(_CAMPOS)))
    citas = r["oraciones"]
    if not isinstance(citas, list) or not 1 <= len(citas) <= MAX_CITAS:
        raise RespuestaInvalida("«oraciones» lleva de 1 a %d "
                                "identificadores." % MAX_CITAS)
    citas = [_texto(c, "oraciones").strip("[]") for c in citas]
    if len(set(citas)) != len(citas):
        raise RespuestaInvalida("«oraciones» repite un identificador.")
    if r["efecto"] not in EFECTOS or r["tipo"] not in TIPOS:
        raise RespuestaInvalida("«efecto» o «tipo» fuera de sus valores.")
    return collections.OrderedDict([
        ("oraciones", citas),
        ("regulador", _texto(r["regulador"], "regulador")),
        ("blanco", _texto(r["blanco"], "blanco")),
        ("efecto", r["efecto"]), ("tipo", r["tipo"])])


def separar(objeto):
    """(relaciones limpias y sin repetir, cuántas no tenían la forma).

    Lanza `RespuestaInvalida` si lo que falla es la respuesta entera: no es
    un objeto con «relaciones» y nada más, o la lista pasa de
    `MAX_RELACIONES`. Una relación mal formada (más citas de las permitidas,
    una etiqueta fuera de sus valores, un campo de más o de menos) se cuenta
    y se deja fuera sin tirar las demás: el defecto es de esa relación, no de
    la lectura. Dos relaciones iguales (mismas citas, nombres y etiquetas)
    cuentan una vez; el orden de las citas no importa.
    """
    if not isinstance(objeto, dict) or set(objeto) != {"relaciones"}:
        raise RespuestaInvalida("La respuesta es un objeto con «relaciones» "
                                "y nada más.")
    lista = objeto["relaciones"]
    if not isinstance(lista, list) or len(lista) > MAX_RELACIONES:
        raise RespuestaInvalida("«relaciones» es una lista de a lo más %d."
                                % MAX_RELACIONES)
    salida, vistas, mal = [], set(), 0
    for r in lista:
        try:
            limpia = _limpiar(r)
        except RespuestaInvalida:
            mal += 1
            continue
        llave = (tuple(sorted(limpia["oraciones"])), limpia["regulador"],
                 limpia["blanco"], limpia["efecto"], limpia["tipo"])
        if llave not in vistas:
            vistas.add(llave)
            salida.append(limpia)
    return salida, mal


def validar_respuesta(objeto):
    """Las relaciones de una respuesta en la que **todas** tienen la forma de
    `esquema()`; si alguna no, `RespuestaInvalida`. La versión estricta de
    `separar`."""
    relaciones, mal = separar(objeto)
    if mal:
        raise RespuestaInvalida("%d relaciones no tienen la forma del "
                                "esquema." % mal)
    return relaciones


# Las palabras que acompañan a un nombre sin ser parte de él: `barA operon`,
# `the barA gene`, `barA promoter region`. Se quitan para buscar el nombre, y
# nada más: `fooR regulon` o `foo system` no son el gen `fooR`.
_ACOMPANAN = re.compile(
    r"^(?:the\s+)?(.+?)(?:\s+(?:operons?|genes?|promoters?(?:\s+region)?|"
    r"locus|cluster|mrna|transcripts?|proteins?))+$", re.I)


def nucleo(nombre):
    """El nombre sin las palabras que lo acompañan (`_ACOMPANAN`)."""
    nombre = " ".join(normalizar(nombre).split())
    m = _ACOMPANAN.match(nombre)
    return m.group(1).strip() if m else nombre


def _aparece(nombre, textos, promotor=False):
    """Si el nombre está escrito en alguna de las oraciones, como palabra
    entera y sin distinguir mayúsculas: el gen `fooR` y su proteína `FooR`
    son la misma entidad (rúbrica §2). Los guiones y los espacios se comparan
    normalizados.

    Con `promotor`, también vale la notación del promotor, una P pegada al
    nombre (`PbarA`): la actividad del promotor de un gen es su expresión.
    Solo se usa para el blanco.
    """
    patron = re.compile(r"(?<![A-Za-z0-9])%s%s(?![A-Za-z0-9])"
                        % ("[Pp]?" if promotor else "",
                           re.escape(normalizar(nombre))), re.I)
    return any(patron.search(normalizar(t)) for t in textos)


def _resolver(nombre, recursos):
    """{nodo, locus, operon, falla} de un nombre, con los recursos del
    bronce y nada más.

    Primero el diccionario de genes: un solo locus, o nada. Si no está ahí,
    el catálogo de operones, **solo por tabla** (`grn_bronce.operones`): un
    nombre que el catálogo no conoce no se expande leyéndolo. `nodo` es el
    nombre con que la entidad va a la red: el símbolo del diccionario (el
    locus si no tiene) o el operón como lo escribe la tabla, que es como los
    nombra la red del paso 2. `locus` es una lista: los genes del operón, o
    el único del gen.
    """
    nombre = normalizar(nombre)
    coincidencias = _herramientas.buscar_locus(
        nombre, recursos)["coincidencias"]
    por_locus = dict((c["locus_tag"], c) for c in coincidencias
                     if c["locus_tag"])
    if len(por_locus) == 1:
        c = list(por_locus.values())[0]
        return {"nodo": c["simbolo"] or c["locus_tag"],
                "locus": [c["locus_tag"]], "operon": False, "falla": None}
    if len(por_locus) > 1:
        return {"nodo": "", "locus": [], "operon": False, "falla": "ambigua"}
    operon = recursos.operones_por_nombre.get(_operones.clave(nombre))
    if operon is not None:
        return {"nodo": operon["operon"], "locus": list(operon["locus_tags"]),
                "operon": True, "falla": None}
    return {"nodo": "", "locus": [], "operon": False, "falla": "sin_locus"}


def verificar(relacion, bloque, recursos):
    """La relación con su `estado` (uno de `ESTADOS`), sus locus y los
    nombres con que va a la red (`nodo_regulador`, `nodo_blanco`).

    En orden: las citas están en el bloque; el regulador y el blanco están
    escritos en alguna oración citada (cada uno puede estar en una distinta:
    eso es una relación repartida en dos oraciones); cada nombre lleva a un
    solo locus del diccionario, o el blanco a un operón del catálogo; el
    regulador es un gen y no un operón; y no son el mismo gen. Solo `valida`
    entra a la red; las demás se cuentan, porque dicen qué le falta al lector
    o al diccionario.

    Un blanco que es un operón del catálogo es válido: `locus_blanco` trae
    sus genes separados por `|` y `nodo_blanco` el nombre del operón, como en
    la red del paso 2.
    """
    por_id = dict((o.id, o) for o in bloque)
    salida = collections.OrderedDict(relacion)
    salida.update({"locus_regulador": "", "locus_blanco": "",
                   "nodo_regulador": "", "nodo_blanco": ""})
    if any(c not in por_id for c in relacion["oraciones"]):
        salida["estado"] = "cita_inexistente"
        return salida
    textos = [por_id[c].texto for c in relacion["oraciones"]]
    regulador, blanco = nucleo(relacion["regulador"]), nucleo(relacion["blanco"])
    if not (_aparece(regulador, textos)
            and _aparece(blanco, textos, promotor=True)):
        salida["estado"] = "entidad_fuera_de_la_cita"
        return salida
    r = _resolver(regulador, recursos)
    b = _resolver(blanco, recursos)
    salida.update({"locus_regulador": "|".join(r["locus"]),
                   "locus_blanco": "|".join(b["locus"]),
                   "nodo_regulador": r["nodo"], "nodo_blanco": b["nodo"]})
    fallas = [x["falla"] for x in (r, b) if x["falla"]]
    if fallas:
        salida["estado"] = ("sin_locus" if "sin_locus" in fallas
                            else "ambigua")
    elif r["operon"]:
        salida["estado"] = "regulador_operon"
    elif r["locus"] == b["locus"]:
        salida["estado"] = "mismo_gen"
    else:
        salida["estado"] = "valida"
    return salida


def conteos(verificadas):
    """Cuántas relaciones cayeron en cada estado, con todos los estados."""
    cuenta = collections.Counter(v["estado"] for v in verificadas)
    return collections.OrderedDict((e, cuenta[e]) for e in ESTADOS)


# ---------------------------------------------------------------- la corrida

LECTURAS = "lecturas.jsonl"
RELACIONES = "relaciones.tsv"
CORRIDA = "corrida.json"

# El lector devuelve una lista, no una etiqueta: necesita más salida que el
# juez. Con gpt-oss el razonamiento también gasta de aquí.
MAX_TOKENS = 8192
LECTOR = {"nombre": "lector", "think": False, "temperature": 0.0,
          "top_p": None, "top_k": None, "seed": None, "num_ctx": None,
          "num_predict": MAX_TOKENS, "kv_cache": None}
# gpt-oss razona siempre; va con el muestreo de su fabricante, como el juez.
LECTOR_RAZONADOR = dict(LECTOR, nombre="lector_razonador", temperature=1.0,
                        top_p=1.0, razonamiento="low")
CONFIGURACIONES = {"lector": LECTOR, "lector_razonador": LECTOR_RAZONADOR}
NIVELES_RAZONAMIENTO = ("low", "medium", "high")

PLANTILLA = ("Texto del artículo, parte {parte} de {partes}. Cada renglón es "
             "una oración con su identificador.\n\n{texto}\n"
             "Devuelve el objeto JSON con las relaciones que este texto "
             "afirma.")

# Lo que pasó con una llamada. Solo `ok` trae relaciones.
ESTADOS_LECTURA = ("ok", "truncada", "contexto_excedido", "sin_json",
                   "respuesta_invalida")
COLUMNAS_RELACIONES = ["pmid", "parte", "oraciones", "regulador", "blanco",
                       "nodo_regulador", "nodo_blanco", "locus_regulador",
                       "locus_blanco", "efecto", "tipo", "estado"]
AVISO_CADA = 25


class CarpetaOcupada(ValueError):
    """La carpeta de salida ya tiene una corrida con otras entradas."""


def _nada(_mensaje):
    pass


def configuracion(nombre, razonamiento=None):
    """Una copia de la configuración del lector, con otro nivel de
    razonamiento si se pide (solo `lector_razonador`, de gpt-oss)."""
    if nombre not in CONFIGURACIONES:
        raise ValueError("La configuración es %s."
                         % ", ".join(sorted(CONFIGURACIONES)))
    config = dict(CONFIGURACIONES[nombre])
    if razonamiento is not None:
        if "razonamiento" not in config:
            raise ValueError("--razonamiento es de la configuración "
                             "lector_razonador (gpt-oss).")
        if razonamiento not in NIVELES_RAZONAMIENTO:
            raise ValueError("El razonamiento es %s."
                             % ", ".join(NIVELES_RAZONAMIENTO))
        config["razonamiento"] = razonamiento
    return config


def mensaje(bloque, parte=1, partes=1):
    """Lo que recibe el modelo por un bloque."""
    return PLANTILLA.format(parte=parte, partes=partes,
                            texto=texto_bloque(bloque))


def huella_prompt(prompt):
    """sha256 de todo lo que el modelo lee además del bloque: el sistema y
    la plantilla del mensaje."""
    texto = json.dumps({"sistema": prompt, "plantilla": PLANTILLA},
                       ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def armar_entradas(descripcion, decodificacion, huella_del_prompt):
    """Lo que decide una respuesta además del bloque: entra a cada llave y
    es la identidad de la carpeta."""
    return {"metodo": METODO, "version": VERSION,
            "esquema": VERSION_ESQUEMA, "prompt": huella_del_prompt,
            "modelo": dict(descripcion),
            "decodificacion": dict(decodificacion)}


def llave_cache(texto_mensaje, entradas):
    crudo = json.dumps([texto_mensaje, entradas], ensure_ascii=False,
                       sort_keys=True)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def interpretar(respuesta):
    """(estado de `ESTADOS_LECTURA`, relaciones, cuántas mal formadas) de lo
    que devolvió el lector. Una respuesta cortada no se aprovecha a medias:
    no se sabría qué faltó."""
    if respuesta.get("motivo") == "contexto_excedido":
        return "contexto_excedido", [], 0
    if respuesta.get("truncado"):
        return "truncada", [], 0
    objeto = _anotar.extraer_json(
        _anotar.quitar_razonamiento(respuesta.get("texto") or ""))
    if objeto is None:
        return "sin_json", [], 0
    try:
        relaciones, mal = separar(objeto)
    except RespuestaInvalida:
        return "respuesta_invalida", [], 0
    return "ok", relaciones, mal


def tareas(articulos, entradas, max_caracteres=MAX_CARACTERES):
    """Una tarea por bloque, en el orden de `articulos` ([(pmid,
    [Oracion])]). Un artículo sin oraciones no da ninguna."""
    salida = []
    for pmid, oraciones in articulos:
        partes = bloques(oraciones, max_caracteres)
        for i, bloque in enumerate(partes, 1):
            texto = mensaje(bloque, i, len(partes))
            salida.append({"pmid": str(pmid), "parte": i,
                           "partes": len(partes), "bloque": bloque,
                           "mensaje": texto,
                           "llave": llave_cache(texto, entradas)})
    return salida


def leer_lecturas(ruta):
    """{llave: registro} de `lecturas.jsonl`. Un renglón cortado (un corte a
    media escritura) se ignora: esa llamada se vuelve a hacer."""
    hechas = {}
    if not os.path.isfile(ruta):
        return hechas
    with io.open(ruta, encoding="utf-8") as f:
        for linea in f:
            try:
                registro = json.loads(linea)
            except ValueError:
                continue
            if isinstance(registro, dict) and registro.get("llave"):
                hechas[registro["llave"]] = registro
    return hechas


def _exigir_misma_corrida(ruta, entradas):
    if not os.path.isfile(ruta):
        return
    with io.open(ruta, encoding="utf-8") as f:
        previa = json.load(f).get("entradas")
    if previa != json.loads(json.dumps(entradas)):
        raise CarpetaOcupada(
            "La carpeta de salida ya tiene una corrida con otro modelo, otro "
            "prompt u otra configuración. Cada corrida va en su carpeta.")


def _escribir_json(ruta, objeto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def filas_de(lista_de_tareas, lecturas, recursos):
    """Las filas de `relaciones.tsv`: cada relación de cada lectura `ok`,
    comprobada contra su bloque, en el orden de las tareas. `lecturas` es
    {llave: (estado, relaciones, mal formadas)}."""
    filas = []
    for t in lista_de_tareas:
        for relacion in lecturas[t["llave"]][1]:
            v = verificar(relacion, t["bloque"], recursos)
            filas.append(collections.OrderedDict([
                ("pmid", t["pmid"]), ("parte", t["parte"]),
                ("oraciones", "|".join(v["oraciones"])),
                ("regulador", v["regulador"]), ("blanco", v["blanco"]),
                ("nodo_regulador", v["nodo_regulador"]),
                ("nodo_blanco", v["nodo_blanco"]),
                ("locus_regulador", v["locus_regulador"]),
                ("locus_blanco", v["locus_blanco"]),
                ("efecto", v["efecto"]), ("tipo", v["tipo"]),
                ("estado", v["estado"])]))
    return filas


def _escribir_relaciones(ruta, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNAS_RELACIONES, delimiter="\t",
                           lineterminator="\n")
        w.writeheader()
        w.writerows(filas)


def _usd(registros, precio):
    if precio is None:
        return None
    return round(sum(_gasto.costo((r.get("respuesta") or {}).get("uso"),
                                  precio) for r in registros), 6)


def ejecutar(articulos, salida, lector, entradas, recursos, paralelo=1,
             precio=None, configuracion=None,
             max_caracteres=MAX_CARACTERES, log=_nada, paquetes=()):
    """Lee los artículos y escribe las tres salidas; devuelve el resumen.

    `articulos` es [(pmid, [Oracion])]; `lector`, el callable que recibe el
    mensaje de un bloque. Con `paralelo` N van N llamadas a la vez y las
    salidas son las mismas que en serie: se arman al final, en el orden de
    los artículos, desde lo guardado.
    """
    salida = _anotar.validar_salida(salida)
    os.makedirs(salida, exist_ok=True)
    ruta_lecturas = os.path.join(salida, LECTURAS)
    ruta_corrida = os.path.join(salida, CORRIDA)
    _exigir_misma_corrida(ruta_corrida, entradas)
    pendientes_de_leer = tareas(articulos, entradas, max_caracteres)
    hechas = leer_lecturas(ruta_lecturas)
    faltan, vistas = [], set()
    for t in pendientes_de_leer:
        if t["llave"] not in hechas and t["llave"] not in vistas:
            vistas.add(t["llave"])
            faltan.append(t)
    de_cache = len(pendientes_de_leer) - len(faltan)
    log("%d artículos, %d llamadas (%d ya en la caché)."
        % (len(articulos), len(pendientes_de_leer), de_cache))
    nuevos = []
    candado = threading.Lock()

    def una(t):
        respuesta = lector(t["mensaje"])
        # Se guarda lo que dijo el modelo; qué relaciones trae se lee de ahí
        # cada vez (`interpretar`), para que corregir una regla de forma no
        # cueste otra lectura.
        registro = {
            "llave": t["llave"], "pmid": t["pmid"], "parte": t["parte"],
            "partes": t["partes"], "huella_bloque": huella_bloque(t["bloque"]),
            "n_oraciones": len(t["bloque"]), "cuando": _anotar.ahora(),
            "respuesta": {"texto": respuesta.get("texto") or "",
                          "done_reason": respuesta.get("done_reason"),
                          "truncado": bool(respuesta.get("truncado")),
                          "motivo": respuesta.get("motivo"),
                          "uso": respuesta.get("uso")}}
        with candado:
            _anotar.anexar(ruta_lecturas, registro)
            hechas[t["llave"]] = registro
            nuevos.append(registro)
            if len(nuevos) % AVISO_CADA == 0:
                log("%d de %d llamadas" % (len(nuevos), len(faltan)))

    if paralelo <= 1:
        for t in faltan:
            una(t)
    else:
        error = None
        with concurrent.futures.ThreadPoolExecutor(paralelo) as grupo:
            futuros = [grupo.submit(una, t) for t in faltan]
            for futuro in concurrent.futures.as_completed(futuros):
                try:
                    futuro.result()
                except concurrent.futures.CancelledError:
                    pass
                except BaseException as e:  # noqa: B902
                    if error is None:
                        error = e
                    for otro in futuros:
                        otro.cancel()
        if error is not None:
            raise error

    registros = [hechas[t["llave"]] for t in pendientes_de_leer]
    leidas = dict((r["llave"], interpretar(r["respuesta"]))
                  for r in registros)
    filas = filas_de(pendientes_de_leer, leidas, recursos)
    _escribir_relaciones(os.path.join(salida, RELACIONES), filas)
    lecturas = collections.Counter(leidas[t["llave"]][0]
                                   for t in pendientes_de_leer)
    estados = collections.Counter(f["estado"] for f in filas)
    con_texto = set(t["pmid"] for t in pendientes_de_leer)
    resumen = collections.OrderedDict([
        ("articulos", len(articulos)),
        ("articulos_sin_texto", len(articulos) - len(con_texto)),
        ("llamadas", len(pendientes_de_leer)),
        ("llamadas_nuevas", len(nuevos)),
        ("lecturas", collections.OrderedDict(
            (e, lecturas[e]) for e in ESTADOS_LECTURA)),
        ("relaciones", len(filas)),
        ("relaciones_mal_formadas", sum(leidas[t["llave"]][2]
                                        for t in pendientes_de_leer)),
        ("relaciones_por_estado", collections.OrderedDict(
            (e, estados[e]) for e in ESTADOS)),
        ("articulos_con_relacion_valida", len(set(
            f["pmid"] for f in filas if f["estado"] == "valida"))),
        ("pares_validos", len(set(
            (f["nodo_regulador"], f["nodo_blanco"]) for f in filas
            if f["estado"] == "valida"))),
    ])
    if precio is not None:
        resumen["costo"] = {
            "usd_esta_corrida": _usd(nuevos, precio),
            "usd_total": _usd(registros, precio),
            "precio_usd_por_millon": list(precio)}
    _escribir_json(ruta_corrida, {
        "metodo": METODO, "version": VERSION, "entradas": entradas,
        "configuracion": configuracion or {}, "cuando": _anotar.ahora(),
        "versiones": _anotar.versiones(paquetes), "resumen": resumen})
    return resumen
