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


def _leer_tsv(ruta):
    """Lee `operones_pao1.tsv` exigiendo el encabezado del contrato.

    No usa el modulo `csv`: el contrato garantiza que ningun campo lleva
    tabulador ni salto de linea, asi que partir por tabulador es exacto, y csv
    con sus reglas de comillas trataria un campo que empiece por comilla doble
    como campo entrecomillado. Es el mismo criterio que `etapa2/lexico.py`.
    """
    filas = []
    with io.open(ruta, encoding="utf-8-sig") as f:
        cabecera = f.readline().rstrip("\n").rstrip("\r").split("\t")
        if cabecera != COLUMNAS:
            raise ValueError(
                "%s: encabezado %r; el contrato pide %r."
                % (ruta, cabecera, COLUMNAS))
        for linea in f:
            linea = linea.rstrip("\n").rstrip("\r")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            partes += [""] * (len(COLUMNAS) - len(partes))
            filas.append(dict(zip(COLUMNAS, partes)))
    return filas


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
