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
Lo mismo dos veces no vuelve a llamar al modelo. La comprobación de las citas
no entra a la llave: se rehace al escribir las salidas, así que un diccionario
nuevo cambia `relaciones.tsv` sin pagar otra lectura.

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
                       "locus_regulador", "locus_blanco", "efecto", "tipo",
                       "estado"]
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
    """(estado de `ESTADOS_LECTURA`, relaciones) de lo que devolvió el
    lector. Una respuesta cortada no se aprovecha a medias."""
    if respuesta.get("motivo") == "contexto_excedido":
        return "contexto_excedido", []
    if respuesta.get("truncado"):
        return "truncada", []
    objeto = _anotar.extraer_json(
        _anotar.quitar_razonamiento(respuesta.get("texto") or ""))
    if objeto is None:
        return "sin_json", []
    try:
        return "ok", validar_respuesta(objeto)
    except RespuestaInvalida:
        return "respuesta_invalida", []


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


def filas_de(lista_de_tareas, hechas, recursos):
    """Las filas de `relaciones.tsv`: cada relación de cada lectura `ok`,
    comprobada contra su bloque, en el orden de las tareas."""
    filas = []
    for t in lista_de_tareas:
        registro = hechas[t["llave"]]
        for relacion in registro.get("relaciones") or []:
            v = verificar(relacion, t["bloque"], recursos)
            filas.append(collections.OrderedDict([
                ("pmid", t["pmid"]), ("parte", t["parte"]),
                ("oraciones", "|".join(v["oraciones"])),
                ("regulador", v["regulador"]), ("blanco", v["blanco"]),
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
        estado, relaciones = interpretar(respuesta)
        registro = {
            "llave": t["llave"], "pmid": t["pmid"], "parte": t["parte"],
            "partes": t["partes"], "huella_bloque": huella_bloque(t["bloque"]),
            "n_oraciones": len(t["bloque"]), "estado": estado,
            "relaciones": relaciones, "cuando": _anotar.ahora(),
            "respuesta": {"texto": respuesta.get("texto") or "",
                          "done_reason": respuesta.get("done_reason"),
                          "truncado": bool(respuesta.get("truncado")),
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

    filas = filas_de(pendientes_de_leer, hechas, recursos)
    _escribir_relaciones(os.path.join(salida, RELACIONES), filas)
    registros = [hechas[t["llave"]] for t in pendientes_de_leer]
    lecturas = collections.Counter(r["estado"] for r in registros)
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
        ("relaciones_por_estado", collections.OrderedDict(
            (e, estados[e]) for e in ESTADOS)),
        ("articulos_con_relacion_valida", len(set(
            f["pmid"] for f in filas if f["estado"] == "valida"))),
        ("pares_de_locus_validos", len(set(
            (f["locus_regulador"], f["locus_blanco"]) for f in filas
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
