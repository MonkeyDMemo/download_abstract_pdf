# -*- coding: utf-8 -*-
"""Los recursos del bronce: el diccionario copiado y los vocabularios semilla.

La que no puede faltar es la de divergencia. `genes_pao1.tsv` existe hoy en dos
sitios --`etapa2/`, que sigue usandolo y esta congelada, y `grn_bronce/recursos/`,
que es el de registro-- y dos diccionarios que se separan sin que nadie lo note
es exactamente el defecto que este proyecto no se puede permitir: las cifras
seguirian saliendo, con la misma etiqueta y la misma pinta de correctas, pero
medidas sobre otro vocabulario.

    python -m unittest discover .
"""

import csv
import hashlib
import io
import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import vocabulario as V   # noqa: E402

RECURSOS = os.path.join(_RAIZ, "grn_bronce", "recursos")
ETAPA2 = os.path.join(_RAIZ, "etapa2")

COPIADOS = ("genes_pao1.tsv", "operones_pao1.tsv", "manual_pao1.tsv",
            "palabras_comunes.txt")

VOCABULARIOS = (
    ("disparadores.csv", ("palabra", "signo_sugerido")),
    ("funciones_semilla.csv", ("termino", "categoria")),
    ("evidencia_experimental.csv", ("termino", "tecnica")),
)


def huella(ruta):
    h = hashlib.sha256()
    with io.open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()[:16]


class PruebasCopiaDelDiccionario(unittest.TestCase):

    def test_las_dos_copias_no_divergen(self):
        """Mientras etapa2 siga congelada hay dos copias. Si se separan, cada
        etapa mide sobre un vocabulario distinto y nada lo delata."""
        for nombre in COPIADOS:
            a = os.path.join(ETAPA2, nombre)
            b = os.path.join(RECURSOS, nombre)
            if not os.path.exists(a):
                continue          # etapa2 ya se migro; la copia es la unica
            self.assertTrue(os.path.exists(b), "falta %s en recursos" % nombre)
            self.assertEqual(
                huella(a), huella(b),
                "%s difiere entre etapa2/ y grn_bronce/recursos/" % nombre)

    def test_el_diccionario_trae_las_columnas_del_contrato(self):
        ruta = os.path.join(RECURSOS, "genes_pao1.tsv")
        with io.open(ruta, encoding="utf-8") as f:
            cabecera = f.readline().rstrip("\n").split("\t")

        for col in ("locus_tag", "simbolo", "alias", "es_tf",
                    "sensible_mayusculas"):
            self.assertIn(col, cabecera)

    def test_sensible_mayusculas_sigue_cubriendo_las_cuatro_colisiones(self):
        """folD, hemE, pilI y minD sostenian 193 de 8653 aristas. Si alguna
        deja de estar marcada, vuelven."""
        ruta = os.path.join(RECURSOS, "genes_pao1.tsv")
        sensibles = set()
        with io.open(ruta, encoding="utf-8") as f:
            cols = f.readline().rstrip("\n").split("\t")
            for linea in f:
                if not linea.strip():
                    continue
                d = dict(zip(cols, linea.rstrip("\n").split("\t")))
                if d.get("sensible_mayusculas") == "true":
                    sensibles.add(d.get("simbolo"))

        for simbolo in ("folD", "hemE", "pilI", "minD"):
            self.assertIn(simbolo, sensibles,
                          "%s dejo de ser sensible a mayusculas" % simbolo)


class PruebasVocabularios(unittest.TestCase):
    """Estos archivos los escribe una persona o un agente; conviene que el
    formato no dependa de que nadie se equivoque."""

    def _filas(self, nombre):
        ruta = os.path.join(RECURSOS, nombre)
        if not os.path.exists(ruta):
            self.skipTest("%s no existe todavia" % nombre)
        with io.open(ruta, encoding="utf-8", newline="") as f:
            lineas = [l for l in f
                      if l.strip() and not l.lstrip().startswith("#")]
        return list(csv.DictReader(lineas))

    def test_tienen_las_columnas_pedidas(self):
        for nombre, columnas in VOCABULARIOS:
            filas = self._filas(nombre)
            self.assertTrue(filas, "%s esta vacio" % nombre)
            for col in columnas:
                self.assertIn(col, filas[0], "%s no trae %s" % (nombre, col))

    def test_no_hay_terminos_repetidos(self):
        """Un termino duplicado no rompe nada, pero delata que el archivo se
        edito a mano sin releerlo, y eso si suele traer companyia."""
        for nombre, columnas in VOCABULARIOS:
            filas = self._filas(nombre)
            claves = [f[columnas[0]].strip().lower() for f in filas]
            repetidos = sorted(set(k for k in claves if claves.count(k) > 1))
            self.assertEqual(repetidos, [], "%s repite %s" % (nombre, repetidos))

    def test_el_signo_sugerido_solo_toma_tres_valores(self):
        filas = self._filas("disparadores.csv")
        vistos = set(f["signo_sugerido"].strip() for f in filas)

        self.assertTrue(vistos <= {"+", "-", "?"},
                        "signo_sugerido trae valores raros: %s"
                        % sorted(vistos - {"+", "-", "?"}))

    def test_ningun_vocabulario_nombra_un_gen(self):
        """Anticircularidad, en su forma barata de comprobar: un disparador o
        una funcion que sea un simbolo de gen indica que el archivo se escribio
        mirando el patron de oro, y ademas produce menciones dobles."""
        simbolos = set()
        with io.open(os.path.join(RECURSOS, "genes_pao1.tsv"),
                     encoding="utf-8") as f:
            cols = f.readline().rstrip("\n").split("\t")
            for linea in f:
                if not linea.strip():
                    continue
                d = dict(zip(cols, linea.rstrip("\n").split("\t")))
                s = (d.get("simbolo") or "").strip()
                if len(s) >= 4:        # los de 3 o menos chocan con todo
                    simbolos.add(s.lower())

        for nombre, columnas in VOCABULARIOS:
            for fila in self._filas(nombre):
                termino = fila[columnas[0]].strip().lower()
                self.assertNotIn(
                    termino, simbolos,
                    "%s incluye %r, que es un simbolo de gen" % (nombre, termino))


class PruebasDeteccion(unittest.TestCase):

    def test_el_organismo_abreviado_se_reconoce(self):
        oracion = "MexT regulates efflux in P. aeruginosa PAO1."

        salida = V.organismos_en(oracion)

        self.assertEqual([s[2] for s in salida], ["P. aeruginosa"])

    def test_una_frase_cualquiera_no_es_un_organismo(self):
        """Sin el filtro de generos, el patron de binomio casa 'Table shows'
        y mete una mencion de organismo en cada tabla del corpus."""
        for oracion in ("Table shows the results.",
                        "These results demonstrate that."):
            self.assertEqual(V.organismos_en(oracion), [], oracion)

    def test_el_genero_completo_conocido_si(self):
        salida = V.organismos_en("Grown in Pseudomonas aeruginosa cultures.")

        self.assertEqual([s[2] for s in salida], ["Pseudomonas aeruginosa"])


if __name__ == "__main__":
    unittest.main()
