"""Las cinco consultas que el juez puede hacer, sobre recursos que el
proyecto ya tiene.

| herramienta | qué responde | de dónde |
|---|---|---|
| `buscar_locus(nombre)` | símbolo o sinónimo -> locus tag | `genes_pao1.tsv` |
| `es_tf(locus)` | si el diccionario lo marca como regulador | columna `es_tf` |
| `operon_de(locus)` | los operones del catálogo que lo contienen | `operones_pao1.tsv` |
| `funcion_anotada(locus)` | el producto de RefSeq | columna `producto` |
| `contexto(id_item)` | la oración anterior y la siguiente | `texto_unidades` |

**Apagadas por omisión** (`herramientas="ninguna"`). El experto juzga solo la
oración (rúbrica §2), y un juez que sabe más deja de medir lo mismo; `es_tf`,
además, empuja justo a la heurística que el §3.4 prohíbe. La corrida con
herramientas es secundaria y pre-registrada (`docs/decisiones.md`,
«Ouroboros v0»): contesta si el conocimiento cambia el veredicto.

Las cinco son funciones puras de biblioteca estándar: reciben el argumento y
los `Recursos`, y no guardan estado entre llamadas. Los decoradores `@tool` de
Strands se aplican al vuelo en `para_strands()`, y solo cuando se piden
herramientas; ahí también se anota cada llamada (la trayectoria) y se pone el
tope de consultas por ítem.

`buscar_locus` respeta `sensible_mayusculas` como el reconocedor del bronce
(`etapa2/lexico.py`): una fila sensible solo coincide con su escritura exacta,
y eso es lo que separa el gen `tag` de la palabra «TAG». Cuando dos filas
reclaman el mismo nombre, el bronce no emite nada; aquí se devuelven las dos y
se dice que es ambiguo, porque quien pregunta es quien tiene que decidir.
Reconocer genes por nombre produce falsos positivos y no sustituye al
reconocimiento de entidades.

`contexto` lee de la llave del sorteo solo la posición del ítem (PMID, fuente
y número de oración) y nunca guarda las demás columnas: la dirección del
bronce, el par o la tanda no llegan ni a la memoria del proceso. Devuelve el
texto de las dos vecinas y nada más.

Biblioteca estándar y Python 3.8.
"""

import csv
import io
import os

from grn_bronce import db as _bdb
from grn_bronce import operones as _operones
from grn_bronce.texto import normalizar_espacios
from grn_comun import procedencia

_ESTE = os.path.abspath(__file__)
_RAIZ = os.path.dirname(os.path.dirname(_ESTE))
RUTA_GENES = os.path.join(_RAIZ, "grn_bronce", "recursos", "genes_pao1.tsv")
RUTA_OPERONES = _operones.RUTA_POR_OMISION

OPCIONES = ("ninguna", "buscar_locus", "todas")
TODAS = ("buscar_locus", "es_tf", "operon_de", "funcion_anotada", "contexto")

# Por ítem. Un modelo chico puede quedarse preguntando lo mismo: pasado el
# tope, cada herramienta contesta que ya no hay más consultas.
MAX_LLAMADAS = 8

COLUMNAS_GENES = ["locus_tag", "simbolo", "alias", "tipo", "producto",
                  "es_tf", "fuente_tf", "fuente", "sensible_mayusculas"]

# Lo único que se lee de la llave del sorteo.
COLUMNAS_POSICION = ("pmid", "fuente_texto", "num_oracion")

NOTA_OPERONES = ("Operones del catálogo del paso 1, predichos por adyacencia "
                 "de locus tags en RefSeq: no son operones verificados.")


def _leer_genes(ruta):
    """Las filas del diccionario con encabezado exacto, como
    `etapa2/lexico.py`: partir por tabulador es exacto porque ningún campo
    lleva tabulador, y `csv` con sus comillas no lo sería."""
    filas = []
    with io.open(ruta, encoding="utf-8") as f:
        cabecera = f.readline().rstrip("\r\n").split("\t")
        if cabecera != COLUMNAS_GENES:
            raise ValueError("genes_pao1.tsv no tiene el encabezado del "
                             "contrato.")
        for linea in f:
            linea = linea.rstrip("\r\n")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            partes += [""] * (len(COLUMNAS_GENES) - len(partes))
            d = dict(zip(COLUMNAS_GENES, partes))
            filas.append({
                "locus_tag": d["locus_tag"].strip(),
                "simbolo": d["simbolo"].strip(),
                "alias": [a.strip() for a in d["alias"].split("|")
                          if a.strip()],
                "producto": d["producto"].strip(),
                "es_tf": d["es_tf"].strip().lower() == "true",
                "de_refseq": "refseq" in d["fuente"].split("|"),
                "sensible": d["sensible_mayusculas"].strip().lower() == "true",
            })
    return filas


class _Diccionario(object):
    """Superficie -> filas, con la sensibilidad de cada fila."""

    def __init__(self, filas):
        self.filas = filas
        self._exactas, self._insensibles = {}, {}
        for i, f in enumerate(filas):
            superficies = set(f["alias"])
            for campo in ("locus_tag", "simbolo"):
                if f[campo]:
                    superficies.add(f[campo])
            for s in superficies:
                if f["sensible"]:
                    self._exactas.setdefault(s, set()).add(i)
                else:
                    self._insensibles.setdefault(s.lower(), set()).add(i)

    def buscar(self, nombre):
        nombre = (nombre or "").strip()
        if not nombre:
            return []
        indices = (self._exactas.get(nombre, set())
                   | self._insensibles.get(nombre.lower(), set()))
        return [self.filas[i] for i in sorted(
            indices, key=lambda i: (self.filas[i]["locus_tag"],
                                    self.filas[i]["simbolo"]))]


class ErrorContexto(ValueError):
    """La llave o la base no son de esta hoja."""


class Recursos(object):
    """Lo que leen las herramientas, cargado una vez y solo si se usa.

    `ruta_llave`, `ruta_db` y `corrida_bronce` solo hacen falta para
    `contexto`: la llave del sorteo (`llave.csv`), la base del proyecto y la
    corrida del bronce de la que salió la muestra (la 4 para las tandas de
    `corrida4_run22`).
    """

    def __init__(self, ruta_genes=RUTA_GENES, ruta_operones=RUTA_OPERONES,
                 ruta_llave=None, ruta_db=None, corrida_bronce=None):
        self.ruta_genes = ruta_genes
        self.ruta_operones = ruta_operones
        self.ruta_llave = ruta_llave
        self.ruta_db = ruta_db
        self.corrida_bronce = corrida_bronce
        self._diccionario = None
        self._operones = None
        self._posiciones = None

    @property
    def diccionario(self):
        if self._diccionario is None:
            self._diccionario = _Diccionario(_leer_genes(self.ruta_genes))
        return self._diccionario

    @property
    def operones_por_locus(self):
        """{locus: [fila]} del catálogo del paso 1, con los nombres tal como
        los escribe la tabla (`operones.leer`, el mismo lector del bronce)."""
        if self._operones is None:
            por_locus = {}
            for fila in _operones.leer(self.ruta_operones):
                locus = [x.strip() for x in fila["locus_tags"].split("|")
                         if x.strip()]
                entrada = {"operon": fila["operon"].strip(),
                           "miembros": [m.strip() for m in
                                        fila["miembros"].split("|")
                                        if m.strip()],
                           "locus_tags": locus}
                for lt in locus:
                    por_locus.setdefault(lt, []).append(entrada)
            self._operones = por_locus
        return self._operones

    @property
    def posiciones(self):
        """{id_item: (pmid, fuente_texto, num_oracion)} de la llave."""
        if self._posiciones is None:
            if not self.ruta_llave:
                raise ErrorContexto("contexto necesita la llave del sorteo.")
            posiciones = {}
            with io.open(self.ruta_llave, encoding="utf-8-sig",
                         newline="") as f:
                lector = csv.DictReader(f)
                faltan = [c for c in ("id_item",) + COLUMNAS_POSICION
                          if c not in (lector.fieldnames or [])]
                if faltan:
                    raise ErrorContexto("A la llave le faltan columnas: %s."
                                        % ", ".join(faltan))
                for fila in lector:
                    posiciones[(fila["id_item"] or "").strip()] = tuple(
                        (fila[c] or "").strip() for c in COLUMNAS_POSICION)
            self._posiciones = posiciones
        return self._posiciones

    def huellas(self, cuales):
        """La huella de lo que leen las herramientas pedidas y la de su
        código. Entra a la llave de la caché: con otro diccionario, otro
        veredicto.

        El código cuenta igual que los datos: los docstrings de
        `para_strands` son la descripción de cada herramienta que el modelo
        lee en la petición, y de aquí sale lo que contestan. Sin su huella,
        una descripción reescrita reusaría en la misma carpeta los
        veredictos de la vieja.
        """
        if cuales not in OPCIONES:
            raise ValueError("herramientas es ninguna, buscar_locus o todas.")
        if cuales == "ninguna":
            return {}
        huellas = {"herramientas.py": procedencia.huella_texto(_ESTE),
                   "genes_pao1.tsv": procedencia.huella_texto(
                       self.ruta_genes)}
        if cuales == "todas":
            huellas["operones_pao1.tsv"] = procedencia.huella_texto(
                self.ruta_operones)
            huellas["llave"] = procedencia.huella(self.ruta_llave)
            huellas["corrida_bronce"] = self.corrida_bronce
        return huellas

    def vecinas(self, id_item):
        """{"anterior", "oracion", "siguiente"} del ítem, o None si la llave
        no lo tiene. Abre la base en solo lectura en cada llamada: Strands
        puede correr las herramientas en otro hilo, y una conexión de SQLite
        no se comparte entre hilos."""
        posicion = self.posiciones.get(id_item)
        if posicion is None:
            return None
        if not self.ruta_db or self.corrida_bronce is None:
            raise ErrorContexto("contexto necesita la base y la corrida del "
                                "bronce.")
        con = _bdb.conectar_lectura(self.ruta_db)
        try:
            return _bdb.vecinas(con, self.corrida_bronce, *posicion)
        finally:
            con.close()

    def verificar_contexto(self, items):
        """Que la llave y la corrida sean las de la hoja: la oración que la
        base tiene en la posición de cada ítem es la de la hoja.

        Se comprueba antes de correr y no a la mitad: con la llave de otra
        tanda o con otra corrida, `contexto` daría las vecinas de otra
        oración sin que nada lo notara. El error solo da conteos.
        """
        sin_llave = sin_oracion = distintas = 0
        for item in items:
            r = self.vecinas(item["id_item"])
            if r is None:
                sin_llave += 1
            elif r["oracion"] is None:
                sin_oracion += 1
            elif (normalizar_espacios(r["oracion"])
                  != normalizar_espacios(item["oracion"])):
                distintas += 1
        if sin_llave or sin_oracion or distintas:
            raise ErrorContexto(
                "La llave o la corrida no son de esta hoja: %d ítems sin "
                "llave, %d sin oración en la base y %d con otra oración."
                % (sin_llave, sin_oracion, distintas))
        return len(items)


def _por_fila(fila):
    return {"locus_tag": fila["locus_tag"], "simbolo": fila["simbolo"]}


def buscar_locus(nombre, recursos):
    """{nombre, coincidencias: [{locus_tag, simbolo}], ambiguo}."""
    filas = recursos.diccionario.buscar(nombre)
    salida = {"nombre": (nombre or "").strip(),
              "coincidencias": [_por_fila(f) for f in filas],
              "ambiguo": len(filas) > 1}
    if not filas:
        salida["nota"] = ("No está en el diccionario de PAO1. Las entradas "
                          "cortas o que son palabras comunes solo coinciden "
                          "con su escritura exacta.")
    return salida


def es_tf(locus, recursos):
    """{consulta, resultados: [{locus_tag, simbolo, es_tf}]}. Acepta el locus
    tag o un nombre; si el nombre es ambiguo, responde por cada fila."""
    filas = recursos.diccionario.buscar(locus)
    return {"consulta": (locus or "").strip(),
            "resultados": [dict(_por_fila(f), es_tf=f["es_tf"])
                           for f in filas]}


def operon_de(locus, recursos):
    """{consulta, resultados: [{locus_tag, simbolo, operones}], nota}."""
    filas = recursos.diccionario.buscar(locus)
    resultados = []
    for f in filas:
        operones = sorted(recursos.operones_por_locus.get(f["locus_tag"], []),
                          key=lambda o: o["operon"].lower())
        resultados.append(dict(_por_fila(f), operones=operones))
    return {"consulta": (locus or "").strip(), "resultados": resultados,
            "nota": NOTA_OPERONES}


def funcion_anotada(locus, recursos):
    """{consulta, resultados: [{locus_tag, simbolo, producto}]}.

    Solo el producto de RefSeq: en las tres entradas manuales sin locus
    (complejos y familias) la columna `producto` es la justificación de
    quien las firmó, no una anotación, y sale vacía.
    """
    filas = recursos.diccionario.buscar(locus)
    return {"consulta": (locus or "").strip(),
            "resultados": [dict(_por_fila(f),
                                producto=f["producto"] if f["de_refseq"]
                                else "")
                           for f in filas]}


def contexto(id_item, recursos):
    """{anterior, siguiente}: el texto de las vecinas, vacío donde no hay.
    Nada más de la llave ni de la base sale de aquí."""
    r = recursos.vecinas(id_item)
    if r is None:
        return {"error": "No hay contexto para ese ítem."}
    return {"anterior": r["anterior"] or "", "siguiente": r["siguiente"] or ""}


def para_strands(recursos, cuales, item, registro, maximo=MAX_LLAMADAS):
    """Las herramientas pedidas, ya decoradas con `@tool` de Strands, para el
    agente de un solo ítem. `registro` es la lista donde queda cada llamada
    con su entrada y su salida.

    `contexto` no recibe argumentos: va atada al ítem que se juzga. Así el
    modelo no puede pedir el contexto de otro ítem ni inventarse un código.
    """
    if cuales not in OPCIONES:
        raise ValueError("herramientas es ninguna, buscar_locus o todas.")
    if cuales == "ninguna":
        return []
    from strands import tool

    def llamar(nombre, entrada, funcion):
        if len(registro) >= maximo:
            salida = {"error": "Se alcanzó el límite de %d consultas para "
                               "este ítem: responde ya con el JSON." % maximo}
        else:
            salida = funcion()
        registro.append({"herramienta": nombre, "entrada": entrada,
                         "salida": salida})
        return salida

    def _buscar_locus(nombre: str) -> dict:
        """Busca un nombre de gen o de proteína en el diccionario de
        P. aeruginosa PAO1 y devuelve su locus tag (PA####).

        Args:
            nombre: el nombre tal como aparece en la oración.
        """
        return llamar("buscar_locus", {"nombre": nombre},
                      lambda: buscar_locus(nombre, recursos))

    def _es_tf(locus: str) -> dict:
        """Dice si el diccionario marca ese gen como factor de
        transcripción o factor sigma.

        Args:
            locus: el locus tag (PA####) o el nombre del gen.
        """
        return llamar("es_tf", {"locus": locus},
                      lambda: es_tf(locus, recursos))

    def _operon_de(locus: str) -> dict:
        """Los operones del catálogo del proyecto que contienen ese gen.

        Args:
            locus: el locus tag (PA####) o el nombre del gen.
        """
        return llamar("operon_de", {"locus": locus},
                      lambda: operon_de(locus, recursos))

    def _funcion_anotada(locus: str) -> dict:
        """El producto que RefSeq anota para ese gen.

        Args:
            locus: el locus tag (PA####) o el nombre del gen.
        """
        return llamar("funcion_anotada", {"locus": locus},
                      lambda: funcion_anotada(locus, recursos))

    def _contexto() -> dict:
        """La oración anterior y la siguiente a la que juzgas, del mismo
        artículo."""
        return llamar("contexto", {},
                      lambda: contexto(item["id_item"], recursos))

    disponibles = {"buscar_locus": _buscar_locus, "es_tf": _es_tf,
                   "operon_de": _operon_de,
                   "funcion_anotada": _funcion_anotada,
                   "contexto": _contexto}
    nombres = ("buscar_locus",) if cuales == "buscar_locus" else TODAS
    return [tool(disponibles[n], name=n) for n in nombres]
