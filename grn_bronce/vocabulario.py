# -*- coding: utf-8 -*-
"""Los vocabularios semilla del bronce, y como se buscan en una oracion.

Cuatro tipos de mencion que no son genes: disparador de regulacion, funcion
biologica, evidencia experimental y organismo. Los tres primeros se leen de
CSV versionados en `recursos/`; el cuarto sale de un patron, por la razon que
se explica abajo.

Todos devuelven la misma forma que `lexico.menciones()`:
`[(ini, fin, superficie, id_normalizado, extra)]`, con los offsets **relativos
a la oracion que se paso**. Asi el resto del pipeline trata a las cinco clases
igual y no hay que recordar cual devuelve que.

Solo biblioteca estandar.
"""

import csv
import io
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
RECURSOS = os.path.join(AQUI, "recursos")

# Un termino solo cuenta si esta rodeado de algo que no sea letra, digito o
# guion. Sin esta guarda "induces" casaria dentro de "reinduces" y "chip"
# dentro de "chipping".
_BORDE_IZQ = r"(?<![A-Za-z0-9-])"
_BORDE_DER = r"(?![A-Za-z0-9-])"

# Organismo. No va por lista de especies porque la lista util es abierta: el
# corpus nombra decenas de bacterias de paso. Va por las dos formas en que la
# nomenclatura binomial se escribe de verdad en esta literatura:
#
#   - abreviada: "P. aeruginosa", "E. coli", "S. aureus". Es la dominante.
#   - completa:  "Pseudomonas aeruginosa", "Escherichia coli".
#
# El genero completo exige mayuscula inicial y al menos cuatro letras, que es
# lo que evita casar "The results" o "In vitro". El epiteto va en minusculas.
_ORGANISMO = re.compile(
    r"(?<![A-Za-z])("
    r"[A-Z]\.\s?[a-z]{3,}"              # P. aeruginosa
    r"|[A-Z][a-z]{3,}\s[a-z]{3,}"       # Pseudomonas aeruginosa
    r")(?![A-Za-z])")

# Generos que de verdad aparecen; el patron completo sin este filtro casa
# cualquier "Table shows" o "Figure demonstrates". Se comprueba solo la primera
# palabra, y solo cuando viene completa.
_GENEROS = frozenset("""
pseudomonas escherichia staphylococcus streptococcus salmonella klebsiella
acinetobacter burkholderia bacillus vibrio yersinia mycobacterium neisseria
enterococcus listeria campylobacter helicobacter clostridium shigella
haemophilus legionella bordetella xanthomonas erwinia agrobacterium
sinorhizobium rhizobium caulobacter serratia proteus enterobacter
stenotrophomonas achromobacter aeromonas candida aspergillus saccharomyces
""".split())


def _leer_csv(nombre, columnas):
    """Lee un CSV de recursos/ y devuelve [(valor de cada columna)].

    Se salta lineas vacias y comentarios que empiecen con `#`, para que los
    vocabularios puedan llevar una nota arriba sin romper el parseo.
    """
    ruta = os.path.join(RECURSOS, nombre)
    if not os.path.exists(ruta):
        return []
    filas = []
    with io.open(ruta, encoding="utf-8", newline="") as f:
        lineas = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    for fila in csv.DictReader(lineas):
        if not fila:
            continue
        valores = [(fila.get(c) or "").strip() for c in columnas]
        if valores[0]:
            filas.append(tuple(valores))
    return filas


class Vocabulario(object):
    """Los tres CSV cargados y compilados en un patron por tipo.

    Se compila UN patron por tipo con todas sus alternativas en vez de buscar
    termino por termino. Con ~400 terminos y ~273 000 oraciones, la diferencia
    entre una pasada y cuatrocientas no es un detalle.
    """

    def __init__(self, disparadores, funciones, evidencia):
        self.disparadores = dict(disparadores)      # palabra -> signo
        self.funciones = dict(funciones)            # termino -> categoria
        self.evidencia = dict(evidencia)            # termino -> tecnica
        self._pat_disp = self._compilar(self.disparadores)
        self._pat_func = self._compilar(self.funciones)
        self._pat_evid = self._compilar(self.evidencia)

    @staticmethod
    def _compilar(mapa):
        if not mapa:
            return None
        # De mas largo a mas corto: asi "chromatin immunoprecipitation" gana
        # sobre "immunoprecipitation" y no se reporta la mencion corta dentro
        # de la larga.
        claves = sorted(mapa, key=len, reverse=True)
        cuerpo = "|".join(re.escape(k) for k in claves)
        return re.compile(_BORDE_IZQ + "(" + cuerpo + ")" + _BORDE_DER,
                          re.IGNORECASE)

    @classmethod
    def cargar(cls):
        return cls(
            _leer_csv("disparadores.csv", ("palabra", "signo_sugerido")),
            _leer_csv("funciones_semilla.csv", ("termino", "categoria")),
            _leer_csv("evidencia_experimental.csv", ("termino", "tecnica")),
        )

    def _buscar(self, patron, mapa, oracion):
        if patron is None:
            return []
        salida, ocupado = [], []
        for m in patron.finditer(oracion):
            ini, fin = m.span(1)
            # Sin solapes: la coincidencia mas larga ya gano por el orden del
            # patron, y lo que caiga dentro de ella no se vuelve a reportar.
            if any(a <= ini < b for a, b in ocupado):
                continue
            ocupado.append((ini, fin))
            superficie = oracion[ini:fin]
            salida.append((ini, fin, superficie, mapa[superficie.lower()]
                           if superficie.lower() in mapa else
                           mapa.get(superficie, "")))
        salida.sort(key=lambda t: t[0])
        return salida

    def disparadores_en(self, oracion):
        """[(ini, fin, palabra, signo_sugerido)]"""
        return self._buscar(self._pat_disp, self.disparadores, oracion)

    def funciones_en(self, oracion):
        """[(ini, fin, termino, categoria)]"""
        return self._buscar(self._pat_func, self.funciones, oracion)

    def evidencia_en(self, oracion):
        """[(ini, fin, termino, tecnica)]"""
        return self._buscar(self._pat_evid, self.evidencia, oracion)

    def __len__(self):
        return (len(self.disparadores) + len(self.funciones)
                + len(self.evidencia))


def organismos_en(oracion):
    """[(ini, fin, superficie, forma)] con `forma` en {abreviada, completa}."""
    salida = []
    for m in _ORGANISMO.finditer(oracion):
        texto = m.group(1)
        primera = texto.split()[0].rstrip(".").lower()
        if "." in texto.split()[0]:
            salida.append((m.start(1), m.end(1), texto, "abreviada"))
        elif primera in _GENEROS:
            salida.append((m.start(1), m.end(1), texto, "completa"))
    return salida
