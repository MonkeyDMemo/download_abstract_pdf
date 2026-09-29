# -*- coding: utf-8 -*-
"""El catalogo de operones y la unica expansion de operon a genes del proyecto.

El bronce guarda **las dos cosas**: la mencion del operon tal como aparece en
el texto, y su expansion a los genes que contiene. El texto dice `mexEF-oprN`;
el grafo necesita PA2493, PA2494 y PA2495. Ninguna de las dos sustituye a la
otra, y por eso viven en columnas distintas y no mezcladas.

POR QUE ESTE MODULO EXISTE
==========================
La expansion se usaba en dos sitios --el evaluador contra el oro y la medicion
del cruce contra la base curada, que era un script de un solo uso-- y estaba a
punto de escribirse una tercera vez para el bronce. Dos expansiones que se
separan sin que nadie lo note es el mismo defecto que ya obligo a copiar
`genes_pao1.tsv` en vez de reescribirlo: las cifras siguen saliendo, con la
misma etiqueta y la misma pinta de correctas, pero medidas sobre otra regla.
Aqui vive una sola, y `etapa2/evaluar_oro.py` la importa en lugar de repetirla.

EL CRITERIO DE EXPANSION, Y POR QUE ES SOLO POR TABLA
=====================================================
Un nombre se expande **unicamente** con lo que dice `operones_pao1.tsv`. La
expansion mecanica del nombre --leer `pqsABCDE` y deducir pqsA..pqsE-- queda
fuera a proposito, y no es una preferencia de estilo: `etapa2/lexico.py` acuna
operones sinteticos desde el texto en cuanto todos los miembros existen en el
diccionario (`lasRIAB`, `rsmZA`, `gacAS`, `exoSTY`), y con la expansion
mecanica una sola arista inventada `LasR -> lasRIAB` se contaba como
recuperacion de tres filas del oro a la vez. Un nodo fabricado por una
concatenacion del texto subia la exhaustividad sin haber encontrado ninguna
relacion. El detalle medido esta en `etapa2/evaluar_oro.py::miembros_de_tabla`.

La consecuencia buscada: un operon que el texto nombra y la tabla no conoce
**no expande a nada**, y aparece en el informe de operones como hueco del
catalogo. Es el entregable, no un fallo: es la lista de lo que falta.

DOS VISTAS DE LA MISMA TABLA
============================
- `miembros()` devuelve simbolos y locus tags juntos, en minusculas. Es lo que
  el evaluador necesita, porque las referencias nombran los extremos de las dos
  formas y el emparejamiento es por clave en minusculas.
- `locus_tags()` devuelve solo los `PA####`, tal como estan escritos. Es lo que
  alimenta la columna `genes_expandidos`, porque el grafo se arma sobre locus
  tags y no sobre simbolos.

Son dos lecturas de las mismas filas, no dos reglas.

Solo biblioteca estandar.
"""

import io
import os
import re

COLUMNAS = ["operon", "miembros", "locus_tags", "fuente"]

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_POR_OMISION = os.path.join(AQUI, "recursos", "operones_pao1.tsv")

# La base de operones curada (ODB, BioCyc, PGD), tal como la entrega
# `grn_operones`. El contrato vive aquí, en el paquete que la lee: quien la
# escribe (`python -m grn_operones.cli catalogo --paso1`) importa esta ruta y
# este encabezado en vez de repetirlos. Sirve para decir a qué operones
# pertenecen los genes de una oración. NO entra en la detección ni en la
# expansión de los operones nombrados, que siguen siendo solo por
# `operones_pao1.tsv` (ver `docs/decisiones.md`).
RUTA_BASE = os.path.join(AQUI, "recursos", "operones_base.tsv")
COLUMNAS_BASE = ["clave_genes", "nombre", "locus_tags", "genes",
                 "nivel_evidencia", "es_alternativa", "monocistronico"]

# Un locus tag de PAO1. La forma con sufijo (`PA0762.1`) existe en el genoma y
# el resto del proyecto la acepta, asi que aqui tambien.
_LOCUS = re.compile(r"^PA\d{4}(\.\d)?$", re.I)


def clave(nombre):
    """Los nombres de operon se comparan en minusculas.

    `MexAB-OprM` y `mexAB-oprM` son el mismo operon: la mayuscula es convencion
    de nomenclatura --forma proteina contra forma gen-- y no identidad. Es la
    misma `clave()` que usa `etapa2/evaluar_oro.py`, y tiene que seguir
    siendolo: si las dos divergieran, el evaluador y el bronce emparejarian
    distinto y sus numeros dejarian de ser comparables.
    """
    return nombre.strip().lower()


def _partes(campo):
    return [x.strip() for x in (campo or "").split("|") if x.strip()]


def desde_filas(filas):
    """[{operon, miembros, locus_tags}] -> ({clave: [miembros]}, {clave: [PA]}).

    El primer mapa mezcla la columna `miembros` con la columna `locus_tags` en
    una sola lista en minusculas, que es exactamente lo que
    `evaluar_oro.cargar_operones()` construia. El segundo se queda solo con los
    locus tags y conserva su escritura.

    Una fila sin ningun miembro no entra: un operon de cero genes no expande
    nada y solo ensuciaria el conteo de los que si.
    """
    mapa_miembros, mapa_locus = {}, {}
    for fila in filas:
        nombre = (fila.get("operon") or "").strip()
        if not nombre:
            continue
        miembros = _partes(fila.get("miembros"))
        locus = _partes(fila.get("locus_tags"))
        if not miembros and not locus:
            continue
        k = clave(nombre)
        mapa_miembros[k] = [clave(m) for m in miembros + locus]
        mapa_locus[k] = [x for x in locus if _LOCUS.match(x)]
    return mapa_miembros, mapa_locus


def miembros_de_tabla(nombre, operones):
    """Los genes de un operon **segun la tabla, y solo segun ella**.

    Es la funcion que `etapa2/evaluar_oro.py` expone con este mismo nombre y
    que ahora delega aqui. Se descarta el propio nombre del conjunto: un
    operon nunca se empareja consigo mismo por la via de la expansion.
    """
    miembros = set(operones.get(clave(nombre), []))
    miembros.discard(clave(nombre))
    return frozenset(miembros)


def _leer_tsv(ruta, columnas=COLUMNAS):
    """Lee una tabla de este modulo exigiendo el encabezado de su contrato.

    No usa el modulo `csv`: el contrato garantiza que ningun campo lleva
    tabulador ni salto de linea, asi que partir por tabulador es exacto, y csv
    con sus reglas de comillas trataria un campo que empiece por comilla doble
    como campo entrecomillado. Es el mismo criterio que `etapa2/lexico.py`.
    """
    filas = []
    with io.open(ruta, encoding="utf-8-sig") as f:
        cabecera = f.readline().rstrip("\n").rstrip("\r").split("\t")
        if cabecera != columnas:
            raise ValueError(
                "%s: encabezado %r; el contrato pide %r."
                % (ruta, cabecera, columnas))
        for linea in f:
            linea = linea.rstrip("\n").rstrip("\r")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            partes += [""] * (len(columnas) - len(partes))
            filas.append(dict(zip(columnas, partes)))
    return filas


def leer(ruta=RUTA_POR_OMISION):
    """Las filas de la tabla, con los nombres en su escritura original.

    `Catalogo` guarda las claves en minúsculas, que es lo que necesita para
    emparejar. Quien necesita mostrar el nombre tal como lo escribe la tabla
    (el catálogo maestro de `grn_operones`) lo lee aquí, con el mismo lector
    y el mismo contrato de encabezado. Así no hay un segundo lector de este
    archivo.
    """
    return _leer_tsv(ruta)


class Catalogo(object):
    """`operones_pao1.tsv` cargado, con sus dos vistas.

    Se instancia una vez por corrida y se consulta por nombre. La tabla tiene
    3 030 filas; construir los dos diccionarios de una pasada y consultarlos
    despues cuesta lo mismo que leerla, y buscar linea por linea por cada
    mencion costaria 7 136 recorridos.
    """

    def __init__(self, miembros=None, locus=None):
        self._miembros = miembros or {}
        self._locus = locus or {}

    @classmethod
    def cargar(cls, ruta):
        """Lee la tabla. Si no esta, el catalogo queda vacio y no expande nada.

        Vacio y no excepcion: sin tabla, la columna `operones` sigue diciendo
        que operones nombra el texto --que es informacion del texto, no del
        catalogo-- y `genes_expandidos` sale en blanco. Reventar aqui dejaria
        sin la primera por no tener la segunda.
        """
        if not ruta or not os.path.exists(ruta):
            return cls()
        return cls(*desde_filas(_leer_tsv(ruta)))

    def tiene(self, nombre):
        """Si el catalogo conoce ese operon. Lo que devuelve False es el hueco
        que el asesor pidio ver."""
        return clave(nombre) in self._miembros

    def miembros(self, nombre):
        """frozenset de simbolos y locus tags en minusculas. Para emparejar."""
        return miembros_de_tabla(nombre, self._miembros)

    def locus_tags(self, nombre):
        """[PA####] ordenados, tal como los escribe la tabla. Para el grafo."""
        return sorted(set(self._locus.get(clave(nombre), [])))

    def n_genes(self, nombre):
        """Cuantos genes contiene segun el catalogo. 0 si no lo conoce."""
        return len(self._locus.get(clave(nombre), []))

    def expandir_varios(self, nombres):
        """La union de los locus tags de varios operones, ordenada.

        Es lo que llena `genes_expandidos` de una oracion: si la oracion
        nombra dos operones, la columna trae los genes de los dos, sin
        repetir y sin decir cual vino de cual. Para saberlo esta `operones`,
        que va al lado.
        """
        salida = set()
        for n in nombres:
            salida.update(self._locus.get(clave(n), []))
        return sorted(salida)

    def __len__(self):
        return len(self._miembros)

    def __contains__(self, nombre):
        return self.tiene(nombre)


class BaseOperones(object):
    """`operones_base.tsv`: a qué operones pertenece cada gen.

    Responde una sola pregunta: dados los genes de una oración, ¿a qué
    operones de la base pertenecen? No detecta nada en el texto ni cambia lo
    que el catálogo del paso 1 expande. Meter la base en la detección se midió
    el 27-sep-2026 y no sirve: resuelve 1 o 2 de los 103 operones faltantes y
    agrega cientos de menciones falsas (`psl`, `amidase`, `CbrA-CbrB`).

    Qué unidades cuentan para la pertenencia:
    - las de más de un gen, porque la unidad de un solo gen es el gen mismo y
      decir que `mexR` está en el «operón mexR» no dice nada;
    - las principales, y además las alternativas cuyo nivel no es solo
      predicción. Una alternativa es cualquier subconjunto de otra unidad, sea
      cual sea su evidencia: sin esta regla quedaban ocultas 32 unidades con
      evidencia (31 conocidas y 1 curada; 11 respaldadas por ODB, las demás
      por BioCyc o PseudoCAP), 20 de ellas dentro de unidades solo predichas.
      Ejemplos: `rnc-era-recO` (ODB), `tolQR` (PseudoCAP), `bphOP` (BioCyc
      y PGD).
    """

    def __init__(self, filas=None, presente=False):
        self.presente = presente
        self._filas = list(filas or [])
        self._por_gen = {}
        incluidas = [f for f in self._filas if self._cuenta(f)]
        for f in incluidas:
            for lt in f["locus_tags"].split("|"):
                if lt:
                    self._por_gen.setdefault(lt, []).append(f)
        # Un nombre que dan dos unidades incluidas (`amidase`) no identifica
        # a ninguna: la etiqueta le agrega la clave de genes.
        vistos = {}
        for f in incluidas:
            if f["nombre"]:
                vistos[f["nombre"]] = vistos.get(f["nombre"], 0) + 1
        self._repetidos = set(n for n, k in vistos.items() if k > 1)

    @staticmethod
    def _cuenta(fila):
        if fila.get("monocistronico") == "si":
            return False
        return (fila.get("es_alternativa") != "si"
                or fila.get("nivel_evidencia") != "predicho")

    @classmethod
    def cargar(cls, ruta=RUTA_BASE):
        """Lee la tabla. Si no está, la base queda vacía y lo dice.

        `presente` distingue «no hay recurso» de «ningún gen de esta oración
        pertenece a un operón»: sin esa marca, las dos se verían igual en la
        salida.
        """
        if not ruta or not os.path.exists(ruta):
            return cls()
        return cls(_leer_tsv(ruta, COLUMNAS_BASE), presente=True)

    def de_genes(self, locus_tags):
        """Las unidades que contienen alguno de esos genes, sin repetir."""
        salida = {}
        for lt in locus_tags:
            for f in self._por_gen.get(lt, []):
                salida[f["clave_genes"]] = f
        return sorted(salida.values(), key=self.etiqueta)

    def etiqueta(self, fila):
        """El nombre de la unidad, o sus genes entre llaves si no tiene.

        Las llaves son para que una unidad sin nombre (las de BioCyc, cuyo
        parser no toma el `common-name` que traen 94 TUs) no se
        lea como si lo tuviera: `{mexA mexB oprM}` es una lista de genes, no
        el nombre de un operón.
        """
        nombre = fila.get("nombre") or ""
        if not nombre:
            return "{%s}" % fila.get("genes", "")
        if nombre in self._repetidos:
            return "%s (%s)" % (nombre, fila["clave_genes"])
        return nombre

    def __len__(self):
        return len(self._filas)
