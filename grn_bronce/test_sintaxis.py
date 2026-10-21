# -*- coding: utf-8 -*-
"""Las reglas v1 de `sintaxis.py`, su alineación v2 y su contacto con spaCy.

Dos clases de prueba, y la diferencia importa:

- **Las reglas, sin spaCy.** Corren siempre, también en el `.venv` del
  proyecto. Los árboles son tokens falsos que copian lo que el parser de
  `en_core_sci_md` produjo sobre estas mismas oraciones SINTÉTICAS: así la
  prueba fija las reglas contra estructuras realistas sin depender del modelo.
- **El contacto con spaCy.** Solo corren donde spaCy y el modelo están
  instalados (`.venv-nlp`); en otro lado se saltan, no fallan.

Todas las oraciones son sintéticas. Ninguna sale del corpus ni de los datos del
laboratorio, y ninguna de la muestra juzgada de la evaluación: las reglas se
miden contra esa muestra, no se escriben con ella.

    .venv/Scripts/python -m unittest grn_bronce.test_sintaxis
    .venv-nlp/Scripts/python -m unittest grn_bronce.test_sintaxis
"""

import argparse
import collections
import csv
import importlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import sintaxis as S                 # noqa: E402
from grn_bronce import vocabulario as V              # noqa: E402

# Un subconjunto del vocabulario de disparadores, con las claves normalizadas
# igual que las de `Vocabulario`. Fijo para que la prueba no se mueva cuando
# alguien amplíe `disparadores.csv`.
SIGNOS = dict((V.normalizar(k), v) for k, v in [
    ("activate", "+"), ("activates", "+"), ("activated", "+"),
    ("repress", "-"), ("repressed", "-"), ("regulates", "?"),
    ("negatively regulates", "-"), ("regulator", "?"),
    ("positive regulator", "+"), ("dependent", "?"), ("require", "?"),
    ("requires", "?"), ("required", "?")])

HAY_SPACY = (importlib.util.find_spec("spacy") is not None
             and importlib.util.find_spec(S.MODELO) is not None)


class Tok(object):
    """La interfaz mínima de token que usan las reglas."""

    def __init__(self, i, text, lemma, pos, tag, dep):
        self.i, self.text, self.lemma_ = i, text, lemma
        self.pos_, self.tag_, self.dep_ = pos, tag, dep
        self.head = self
        self._hijos = []

    @property
    def children(self):
        return iter(self._hijos)


def arbol(filas):
    """[(texto, lema, pos, tag, dep, cabeza)] -> [Tok], con hijos en orden."""
    toks = [Tok(i, *f[:5]) for i, f in enumerate(filas)]
    for t, f in zip(toks, filas):
        t.head = toks[f[5]]
        if f[5] != t.i:
            toks[f[5]]._hijos.append(t)
    return toks


def orientar(filas, ia, ib, mutante=False):
    return S.orientar(arbol(filas), ia, ib, mutante, SIGNOS)


# Los árboles. Comentario = la oración sintética de la que salen.

# LasR activates rhlR expression.
ACTIVA = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 1),
    ("activates", "activate", "VERB", "VBZ", "ROOT", 1),
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 3),
    ("expression", "expression", "NOUN", "NN", "dobj", 1),
    (".", ".", "PUNCT", ".", "punct", 1),
]

# rhlR is activated by LasR.  (estilo del modelo: "by" es `case` de un nmod)
PASIVA = [
    ("rhlR", "rhlr", "NOUN", "NN", "nsubjpass", 2),
    ("is", "be", "AUX", "VBZ", "auxpass", 2),
    ("activated", "activate", "VERB", "VBN", "ROOT", 2),
    ("by", "by", "ADP", "IN", "case", 4),
    ("LasR", "lasr", "NOUN", "NN", "nmod", 2),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# La misma pasiva en estilo ClearNLP: "by" es `prep` y la entidad su `pobj`.
PASIVA_CLEARNLP = [
    ("rhlR", "rhlr", "NOUN", "NN", "nsubjpass", 2),
    ("is", "be", "AUX", "VBZ", "auxpass", 2),
    ("activated", "activate", "VERB", "VBN", "ROOT", 2),
    ("by", "by", "ADP", "IN", "prep", 2),
    ("LasR", "lasr", "NOUN", "NN", "pobj", 3),
]

# Expression of rhlR by LasR requires an autoinducer.
NOMINAL_POR = [
    ("Expression", "expression", "NOUN", "NN", "nsubj", 5),
    ("of", "of", "ADP", "IN", "case", 2),
    ("rhlR", "rhlr", "NOUN", "NN", "nmod", 0),
    ("by", "by", "ADP", "IN", "case", 4),
    ("LasR", "lasr", "NOUN", "NN", "nmod", 0),
    ("requires", "require", "VERB", "VBZ", "ROOT", 5),
    ("an", "an", "DET", "DT", "det", 7),
    ("autoinducer", "autoinducer", "NOUN", "NN", "dobj", 5),
    (".", ".", "PUNCT", ".", "punct", 5),
]

# LasR-dependent expression of rhlR was observed.
NOMINAL_SUFIJO = [
    ("LasR-dependent", "lasr-dependent", "ADJ", "JJ", "amod", 1),
    ("expression", "expression", "NOUN", "NN", "nsubjpass", 5),
    ("of", "of", "ADP", "IN", "case", 3),
    ("rhlR", "rhlr", "NOUN", "NN", "nmod", 1),
    ("was", "be", "AUX", "VBD", "auxpass", 5),
    ("observed", "observe", "VERB", "VBN", "ROOT", 5),
    (".", ".", "PUNCT", ".", "punct", 5),
]

# rhlR expression is LasR-dependent.
SUFIJO_COPULATIVO = [
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 1),
    ("expression", "expression", "NOUN", "NN", "nsubj", 3),
    ("is", "be", "AUX", "VBZ", "cop", 3),
    ("LasR-dependent", "lasr-dependent", "ADJ", "JJ", "ROOT", 3),
    (".", ".", "PUNCT", ".", "punct", 3),
]

# MexT is a positive regulator of mexEF-oprN.
COPULATIVO = [
    ("MexT", "mext", "NOUN", "NN", "nsubj", 4),
    ("is", "be", "AUX", "VBZ", "cop", 4),
    ("a", "a", "DET", "DT", "det", 4),
    ("positive", "positive", "ADJ", "JJ", "amod", 4),
    ("regulator", "regulator", "NOUN", "NN", "ROOT", 4),
    ("of", "of", "ADP", "IN", "case", 6),
    ("mexEF-oprN", "mexef-oprn", "NOUN", "NN", "nmod", 4),
    (".", ".", "PUNCT", ".", "punct", 4),
]

# the effect of LasR on rhlR expression
EFECTO = [
    ("effect", "effect", "NOUN", "NN", "ROOT", 0),
    ("of", "of", "ADP", "IN", "case", 2),
    ("LasR", "lasr", "NOUN", "NN", "nmod", 0),
    ("on", "on", "ADP", "IN", "case", 5),
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 5),
    ("expression", "expression", "NOUN", "NN", "nmod", 0),
]

# Expression of mexEF-oprN was increased in the mexT mutant.
MUTANTE_TEXTO = "Expression of mexEF-oprN was increased in the mexT mutant."
MUTANTE = [
    ("Expression", "expression", "NOUN", "NN", "nsubjpass", 4),
    ("of", "of", "ADP", "IN", "case", 2),
    ("mexEF-oprN", "mexef-oprn", "NOUN", "NN", "nmod", 0),
    ("was", "be", "AUX", "VBD", "auxpass", 4),
    ("increased", "increase", "VERB", "VBN", "ROOT", 4),
    ("in", "in", "ADP", "IN", "case", 8),
    ("the", "the", "DET", "DT", "det", 8),
    ("mexT", "mext", "NOUN", "NN", "compound", 8),
    ("mutant", "mutant", "NOUN", "NN", "nmod", 4),
    (".", ".", "PUNCT", ".", "punct", 4),
]

# LasR and RhlR activate rhlA.
COORD_SUJETOS_TEXTO = "LasR and RhlR activate rhlA."
COORD_SUJETOS = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 3),
    ("and", "and", "CCONJ", "CC", "cc", 0),
    ("RhlR", "rhlr", "NOUN", "NN", "conj", 0),
    ("activate", "activate", "VERB", "VBP", "ROOT", 3),
    ("rhlA", "rhla", "NOUN", "NN", "dobj", 3),
    (".", ".", "PUNCT", ".", "punct", 3),
]

# LasR activates rhlR and rhlI.
COORD_OBJETOS = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 1),
    ("activates", "activate", "VERB", "VBZ", "ROOT", 1),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 1),
    ("and", "and", "CCONJ", "CC", "cc", 2),
    ("rhlI", "rhli", "NOUN", "NN", "conj", 2),
    (".", ".", "PUNCT", ".", "punct", 1),
]

# LasR binds to the promoter and activates rhlR.
COORD_VERBOS = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 1),
    ("binds", "bind", "VERB", "VBZ", "ROOT", 1),
    ("to", "to", "PART", "TO", "case", 4),
    ("the", "the", "DET", "DT", "det", 4),
    ("promoter", "promoter", "NOUN", "NN", "nmod", 1),
    ("and", "and", "CCONJ", "CC", "cc", 1),
    ("activates", "activate", "VERB", "VBZ", "conj", 1),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 6),
    (".", ".", "PUNCT", ".", "punct", 1),
]

# rhlR is activated by LasR and repressed by RsaL.
COORD_PASIVAS = [
    ("rhlR", "rhlr", "NOUN", "NN", "nsubjpass", 2),
    ("is", "be", "AUX", "VBZ", "auxpass", 2),
    ("activated", "activate", "VERB", "VBN", "ROOT", 2),
    ("by", "by", "ADP", "IN", "case", 4),
    ("LasR", "lasr", "NOUN", "NN", "nmod", 2),
    ("and", "and", "CCONJ", "CC", "cc", 2),
    ("repressed", "repress", "VERB", "VBN", "conj", 2),
    ("by", "by", "ADP", "IN", "case", 8),
    ("RsaL", "rsal", "NOUN", "NN", "nmod", 6),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# LasR, which activates rhlR, is a quorum sensing regulator.
RELATIVA_ACTIVA = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 10),
    (",", ",", "PUNCT", ",", "punct", 0),
    ("which", "which", "DET", "WDT", "nsubj", 3),
    ("activates", "activate", "VERB", "VBZ", "acl:relcl", 0),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 3),
    (",", ",", "PUNCT", ",", "punct", 0),
    ("is", "be", "AUX", "VBZ", "cop", 10),
    ("a", "a", "DET", "DT", "det", 10),
    ("quorum", "quorum", "ADJ", "JJ", "amod", 10),
    ("sensing", "sensing", "NOUN", "NN", "compound", 10),
    ("regulator", "regulator", "NOUN", "NN", "ROOT", 10),
    (".", ".", "PUNCT", ".", "punct", 10),
]

# The rhlR gene, which is repressed by RsaL, encodes a regulator.
RELATIVA_PASIVA = [
    ("The", "the", "DET", "DT", "det", 2),
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 2),
    ("gene", "gene", "NOUN", "NN", "nsubj", 10),
    (",", ",", "PUNCT", ",", "punct", 2),
    ("which", "which", "DET", "WDT", "nsubjpass", 6),
    ("is", "be", "AUX", "VBZ", "auxpass", 6),
    ("repressed", "repress", "VERB", "VBN", "acl:relcl", 2),
    ("by", "by", "ADP", "IN", "case", 8),
    ("RsaL", "rsal", "NOUN", "NN", "nmod", 6),
    (",", ",", "PUNCT", ",", "punct", 2),
    ("encodes", "encode", "VERB", "VBZ", "ROOT", 10),
    ("a", "a", "DET", "DT", "det", 12),
    ("regulator", "regulator", "NOUN", "NN", "dobj", 10),
    (".", ".", "PUNCT", ".", "punct", 10),
]

# LasR activates rhlR, which is repressed by RsaL.
RELATIVA_ANIDADA = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 1),
    ("activates", "activate", "VERB", "VBZ", "ROOT", 1),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 1),
    (",", ",", "PUNCT", ",", "punct", 2),
    ("which", "which", "DET", "WDT", "nsubjpass", 6),
    ("is", "be", "AUX", "VBZ", "auxpass", 6),
    ("repressed", "repress", "VERB", "VBN", "acl:relcl", 2),
    ("by", "by", "ADP", "IN", "case", 8),
    ("RsaL", "rsal", "NOUN", "NN", "nmod", 6),
    (".", ".", "PUNCT", ".", "punct", 1),
]

# LasR does not activate rhlR.
NEGADA = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 3),
    ("does", "do", "AUX", "VBZ", "aux", 3),
    ("not", "not", "PART", "RB", "neg", 3),
    ("activate", "activate", "VERB", "VB", "ROOT", 3),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 3),
    (".", ".", "PUNCT", ".", "punct", 3),
]

# LasR negatively regulates rhlR.
MODIFICADA = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 2),
    ("negatively", "negatively", "ADV", "RB", "advmod", 2),
    ("regulates", "regulate", "VERB", "VBZ", "ROOT", 2),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 2),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# LasR was shown to activate rhlR.
XCOMP = [
    ("LasR", "lasr", "NOUN", "NN", "nsubjpass", 2),
    ("was", "be", "AUX", "VBD", "auxpass", 2),
    ("shown", "show", "VERB", "VBN", "ROOT", 2),
    ("to", "to", "PART", "TO", "mark", 4),
    ("activate", "activate", "VERB", "VB", "xcomp", 2),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 4),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# rhlR transcription requires LasR.
INVERSO_ACTIVA = [
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 1),
    ("transcription", "transcription", "NOUN", "NN", "nsubj", 2),
    ("requires", "require", "VERB", "VBZ", "ROOT", 2),
    ("LasR", "lasr", "NOUN", "NN", "dobj", 2),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# LasR is required for rhlR expression.
INVERSO_PASIVA = [
    ("LasR", "lasr", "NOUN", "NN", "nsubjpass", 2),
    ("is", "be", "AUX", "VBZ", "auxpass", 2),
    ("required", "require", "VERB", "VBN", "ROOT", 2),
    ("for", "for", "ADP", "IN", "case", 5),
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 5),
    ("expression", "expression", "NOUN", "NN", "nmod", 2),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# rhlR expression depends on LasR.
INVERSO_COMPLEMENTO = [
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 1),
    ("expression", "expression", "NOUN", "NN", "nsubj", 2),
    ("depends", "depend", "VERB", "VBZ", "ROOT", 2),
    ("on", "on", "ADP", "IN", "case", 4),
    ("LasR", "lasr", "NOUN", "NN", "nmod", 2),
    (".", ".", "PUNCT", ".", "punct", 2),
]

# LasR activates lasB in the rhlR strain.
CONTEXTO = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 1),
    ("activates", "activate", "VERB", "VBZ", "ROOT", 1),
    ("lasB", "lasb", "NOUN", "NN", "dobj", 1),
    ("in", "in", "ADP", "IN", "case", 6),
    ("the", "the", "DET", "DT", "det", 6),
    ("rhlR", "rhlr", "NOUN", "NN", "compound", 6),
    ("strain", "strain", "NOUN", "NN", "nmod", 1),
    (".", ".", "PUNCT", ".", "punct", 1),
]

# Dos raíces: lo que dejaría un parser que no respetara el corte fijado.
DOS_RAICES = [
    ("LasR", "lasr", "NOUN", "NN", "nsubj", 1),
    ("activates", "activate", "VERB", "VBZ", "ROOT", 1),
    ("rhlR", "rhlr", "NOUN", "NN", "dobj", 1),
    ("RhlR", "rhlr", "NOUN", "NN", "nsubj", 4),
    ("activates", "activate", "VERB", "VBZ", "ROOT", 4),
    ("rhlA", "rhla", "NOUN", "NN", "dobj", 4),
]

# LasR/RhlR activate lasB.  (el tokenizador deja «LasR/RhlR» en un token)
COMPARTIDO = [
    ("LasR/RhlR", "lasr/rhlr", "NOUN", "NN", "nsubj", 1),
    ("activate", "activate", "VERB", "VBP", "ROOT", 1),
    ("lasB", "lasb", "NOUN", "NN", "dobj", 1),
    (".", ".", "PUNCT", ".", "punct", 1),
]

# El esquema y las voces de la v1, escritos a mano: la v2 agrega una voz al
# final y no toca el esquema, y el consumidor que los recorra no se entera.
CAMPOS_V1 = ("pmid", "fuente_texto", "seccion", "num_oracion",
             "huella_oracion", "a", "b", "a_es_tf", "b_es_tf",
             "regulador_sintactico", "blanco_sintactico", "voz", "negada",
             "lema_dominante", "disparador_dominante", "signo_dominante",
             "camino", "longitud_camino", "modelo", "spacy", "version")
VOCES_V1 = ("activa", "pasiva", "nominal", "mutante", "indeterminada",
            "sin_camino", "sin_alineacion")


class PruebasVoz(unittest.TestCase):
    """Activa, pasiva, nominal, mutante."""

    def test_activa_sujeto_regula(self):
        r = orientar(ACTIVA, 0, 2)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "activa"))
        self.assertEqual(r["lema_dominante"], "activate")
        self.assertEqual((r["disparador_dominante"], r["signo_dominante"]),
                         ("activates", "+"))
        self.assertEqual(r["camino"], "nsubj< >dobj >compound")
        self.assertEqual(r["longitud_camino"], 3)
        self.assertFalse(r["negada"])

    def test_el_orden_de_los_tokens_no_cambia_la_propuesta(self):
        r = orientar(ACTIVA, 2, 0)
        self.assertEqual((r["regulador"], r["voz"]), ("b", "activa"))
        self.assertEqual(r["camino"], "compound< dobj< >nsubj")

    def test_pasiva_el_agente_regula(self):
        r = orientar(PASIVA, 0, 4)
        self.assertEqual((r["regulador"], r["voz"]), ("b", "pasiva"))
        self.assertEqual(r["signo_dominante"], "+")

    def test_pasiva_en_estilo_clearnlp(self):
        # Un modelo con `prep`/`pobj` no deja muda a la regla.
        r = orientar(PASIVA_CLEARNLP, 0, 4)
        self.assertEqual((r["regulador"], r["voz"]), ("b", "pasiva"))

    def test_nominal_expression_of_x_by_y(self):
        r = orientar(NOMINAL_POR, 4, 2)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "nominal"))
        self.assertEqual(r["lema_dominante"], "expression")
        # `expression` no es disparador: no se inventa un signo.
        self.assertEqual(r["signo_dominante"], "")

    def test_nominal_por_sufijo(self):
        r = orientar(NOMINAL_SUFIJO, 0, 3)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "nominal"))
        # El gobernante (`expression`) no es disparador; manda el sufijo.
        self.assertEqual((r["lema_dominante"], r["disparador_dominante"],
                          r["signo_dominante"]),
                         ("dependent", "dependent", "?"))

    def test_sufijo_como_predicado(self):
        r = orientar(SUFIJO_COPULATIVO, 3, 0)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "nominal"))

    def test_copulativo_con_sustantivo_agentivo(self):
        r = orientar(COPULATIVO, 0, 6)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "nominal"))
        self.assertEqual((r["disparador_dominante"], r["signo_dominante"]),
                         ("positive regulator", "+"))

    def test_effect_of_y_on_x(self):
        r = orientar(EFECTO, 2, 4)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "nominal"))

    def test_mutante_no_se_orienta(self):
        r = orientar(MUTANTE, 2, 7, mutante=True)
        self.assertEqual((r["regulador"], r["voz"]), ("", "mutante"))
        # El resto se sigue reportando: dice qué hay, no quién regula.
        self.assertEqual(r["lema_dominante"], "increase")
        self.assertGreater(r["longitud_camino"], 0)

    def test_sin_bandera_de_mutante_tampoco_se_inventa_un_regulador(self):
        r = orientar(MUTANTE, 2, 7)
        self.assertEqual((r["regulador"], r["voz"]), ("", "indeterminada"))


class PruebasEstructura(unittest.TestCase):
    """Coordinación, relativas, negación, inversos y lo que no se orienta."""

    def test_sujetos_coordinados_regulan_los_dos(self):
        self.assertEqual(orientar(COORD_SUJETOS, 0, 4)["regulador"], "a")
        self.assertEqual(orientar(COORD_SUJETOS, 2, 4)["regulador"], "a")

    def test_dos_coordinados_entre_si_no_se_orientan(self):
        r = orientar(COORD_SUJETOS, 0, 2)
        self.assertEqual((r["regulador"], r["voz"]), ("", "indeterminada"))
        self.assertEqual(r["lema_dominante"], "")

    def test_objetos_coordinados(self):
        self.assertEqual(orientar(COORD_OBJETOS, 0, 4)["regulador"], "a")
        self.assertEqual(orientar(COORD_OBJETOS, 2, 4)["voz"],
                         "indeterminada")

    def test_verbos_coordinados_heredan_el_sujeto(self):
        r = orientar(COORD_VERBOS, 0, 7)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "activa"))
        self.assertEqual(r["lema_dominante"], "activate")

    def test_pasivas_coordinadas(self):
        r = orientar(COORD_PASIVAS, 8, 0)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "pasiva"))
        self.assertEqual((r["lema_dominante"], r["signo_dominante"]),
                         ("repress", "-"))
        # Los dos agentes entre sí: ninguno regula al otro.
        self.assertEqual(orientar(COORD_PASIVAS, 4, 8)["regulador"], "")

    def test_relativa_activa(self):
        r = orientar(RELATIVA_ACTIVA, 0, 4)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "activa"))
        self.assertEqual(r["lema_dominante"], "activate")

    def test_relativa_pasiva_con_antecedente_compuesto(self):
        r = orientar(RELATIVA_PASIVA, 1, 8)
        self.assertEqual((r["regulador"], r["voz"]), ("b", "pasiva"))
        self.assertEqual(r["lema_dominante"], "repress")

    def test_una_relativa_anidada_no_se_atribuye_al_verbo_de_arriba(self):
        r = orientar(RELATIVA_ANIDADA, 0, 8)
        self.assertEqual((r["regulador"], r["voz"]), ("", "indeterminada"))
        self.assertEqual(orientar(RELATIVA_ANIDADA, 2, 8)["regulador"], "b")

    def test_negacion(self):
        r = orientar(NEGADA, 0, 4)
        self.assertTrue(r["negada"])
        # La negación se reporta; no cambia quién sería el regulador.
        self.assertEqual((r["regulador"], r["voz"]), ("a", "activa"))

    def test_modificador_del_disparador(self):
        r = orientar(MODIFICADA, 0, 3)
        self.assertEqual((r["disparador_dominante"], r["signo_dominante"]),
                         ("negatively regulates", "-"))

    def test_xcomp_hereda_el_sujeto(self):
        r = orientar(XCOMP, 0, 5)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "activa"))
        self.assertEqual(r["lema_dominante"], "activate")

    def test_inversos(self):
        self.assertEqual(orientar(INVERSO_ACTIVA, 0, 3)["regulador"], "b")
        r = orientar(INVERSO_PASIVA, 0, 4)
        self.assertEqual((r["regulador"], r["voz"]), ("a", "pasiva"))
        self.assertEqual(orientar(INVERSO_COMPLEMENTO, 0, 4)["regulador"],
                         "b")

    def test_un_complemento_de_contexto_no_es_blanco(self):
        self.assertEqual(orientar(CONTEXTO, 0, 5)["voz"], "indeterminada")
        self.assertEqual(orientar(CONTEXTO, 0, 2)["regulador"], "a")

    def test_sin_camino(self):
        r = orientar(DOS_RAICES, 0, 5)
        self.assertEqual((r["regulador"], r["voz"], r["camino"],
                          r["longitud_camino"]),
                         ("", "sin_camino", "", 0))


def mencion(oracion, superficie, idc, es_tf, desde=0):
    ini = oracion.index(superficie, desde)
    return (ini, ini + len(superficie), superficie, idc, es_tf)


class PruebasPares(unittest.TestCase):
    """`analizar_doc`: pares, ocurrencias y alineación, sin spaCy."""

    def test_tres_entidades(self):
        texto = COORD_SUJETOS_TEXTO
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "RhlR", "rhlR", True),
                     mencion(texto, "rhlA", "rhlA", False)]
        pares = S.analizar_doc(arbol(COORD_SUJETOS), texto, menciones,
                               {0: 0, 1: 2, 2: 4}, SIGNOS)
        resumen = [(p["a"], p["b"], p["regulador_sintactico"],
                    p["blanco_sintactico"], p["voz"]) for p in pares]
        self.assertEqual(resumen, [
            ("lasR", "rhlA", "lasR", "rhlA", "activa"),
            ("lasR", "rhlR", "", "", "indeterminada"),
            ("rhlA", "rhlR", "rhlR", "rhlA", "activa"),
        ])
        self.assertEqual([(p["a_es_tf"], p["b_es_tf"]) for p in pares],
                         [(True, False), (True, True), (False, True)])
        for p in pares:
            self.assertEqual(tuple(p), S.CAMPOS_PAR)

    def test_la_frase_de_mutante_suspende_la_orientacion(self):
        texto = MUTANTE_TEXTO
        menciones = [mencion(texto, "mexEF-oprN", "mexEF-oprN", False),
                     mencion(texto, "mexT", "mexT", True)]
        pares = S.analizar_doc(arbol(MUTANTE), texto, menciones,
                               {0: 2, 1: 7}, SIGNOS)
        self.assertEqual(len(pares), 1)
        self.assertEqual((pares[0]["voz"], pares[0]["regulador_sintactico"]),
                         ("mutante", ""))

    def test_mencion_sin_alinear(self):
        # Lo que dejaba la v1 en «LasR/RhlR»: una de las dos menciones fuera
        # de `alineacion`. Desde la v2 `preparar_doc` alinea a las dos (ver
        # `test_dos_menciones_en_un_token`), pero una mención que de verdad
        # se queda sin token --un `char_span` None, un traslape a medias--
        # sigue dejando todos sus pares en `sin_alineacion`.
        texto = "LasR/RhlR activate lasB."
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "RhlR", "rhlR", True),
                     mencion(texto, "lasB", "lasB", False)]
        toks = arbol(COMPARTIDO)
        pares = S.analizar_doc(toks, texto, menciones, {0: 0, 2: 2}, SIGNOS)
        por_par = dict(((p["a"], p["b"]), p) for p in pares)
        self.assertEqual(por_par[("lasB", "lasR")]["regulador_sintactico"],
                         "lasR")
        for par in (("lasB", "rhlR"), ("lasR", "rhlR")):
            p = por_par[par]
            self.assertEqual((p["voz"], p["regulador_sintactico"],
                              p["camino"], p["longitud_camino"]),
                             ("sin_alineacion", "", "", 0))

    def test_dos_menciones_en_un_token(self):
        # La v2: las dos menciones de «LasR/RhlR» apuntan al mismo token.
        # Entre ellas no hay camino; con lasB, cada una se orienta como lo
        # haría la otra.
        texto = "LasR/RhlR activate lasB."
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "RhlR", "rhlR", True),
                     mencion(texto, "lasB", "lasB", False)]
        pares = S.analizar_doc(arbol(COMPARTIDO), texto, menciones,
                               {0: 0, 1: 0, 2: 2}, SIGNOS)
        por_par = dict(((p["a"], p["b"]), p) for p in pares)
        p = por_par[("lasR", "rhlR")]
        self.assertEqual((p["voz"], p["regulador_sintactico"],
                          p["blanco_sintactico"], p["lema_dominante"],
                          p["camino"], p["longitud_camino"]),
                         ("mismo_token", "", "", "", "", 0))
        con_lasr, con_rhlr = por_par[("lasB", "lasR")], por_par[("lasB",
                                                                 "rhlR")]
        self.assertEqual((con_lasr["regulador_sintactico"], con_lasr["voz"]),
                         ("lasR", "activa"))
        self.assertEqual((con_rhlr["regulador_sintactico"], con_rhlr["voz"]),
                         ("rhlR", "activa"))
        for campo in S.CAMPOS_PAR:
            if campo not in ("b", "regulador_sintactico"):
                self.assertEqual(con_lasr[campo], con_rhlr[campo], campo)

    def test_mismo_token_aunque_la_oracion_sea_de_mutante(self):
        # La frase de mutante deja los demás pares en `mutante`; el de las
        # dos menciones del token sigue diciendo por qué no hay camino.
        texto = "LasR/RhlR mutants overproduce lasB."
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "RhlR", "rhlR", True),
                     mencion(texto, "lasB", "lasB", False)]
        toks = arbol([
            ("LasR/RhlR", "lasr/rhlr", "NOUN", "NN", "compound", 1),
            ("mutants", "mutant", "NOUN", "NNS", "nsubj", 2),
            ("overproduce", "overproduce", "VERB", "VBP", "ROOT", 2),
            ("lasB", "lasb", "NOUN", "NN", "dobj", 2),
            (".", ".", "PUNCT", ".", "punct", 2)])
        pares = S.analizar_doc(toks, texto, menciones, {0: 0, 1: 0, 2: 3},
                               SIGNOS)
        self.assertEqual([(p["a"], p["b"], p["voz"]) for p in pares], [
            ("lasB", "lasR", "mutante"),
            ("lasB", "rhlR", "mutante"),
            ("lasR", "rhlR", "mismo_token"),
        ])

    def test_la_ocurrencia_es_la_que_elige_extraer_pares(self):
        # rhlR aparece dos veces; `elegir_ocurrencias` toma la más cercana a
        # LasR, que es la primera. Si esa no se alineó, el par queda
        # `sin_alineacion`: no se cambia a otra ocurrencia, porque entonces ya
        # no sería el par de tokens que marca BioBERT.
        texto = "rhlR, LasR activates rhlR."
        menciones = [mencion(texto, "rhlR", "rhlR", True),
                     mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "rhlR", "rhlR", True, desde=5)]
        toks = arbol([("rhlR", "rhlr", "NOUN", "NN", "dep", 3),
                      (",", ",", "PUNCT", ",", "punct", 3),
                      ("LasR", "lasr", "NOUN", "NN", "nsubj", 3),
                      ("activates", "activate", "VERB", "VBZ", "ROOT", 3),
                      ("rhlR", "rhlr", "NOUN", "NN", "dobj", 3),
                      (".", ".", "PUNCT", ".", "punct", 3)])
        lejana_sin_alinear = S.analizar_doc(toks, texto, menciones,
                                            {0: 0, 1: 2}, SIGNOS)
        cercana_sin_alinear = S.analizar_doc(toks, texto, menciones,
                                             {1: 2, 2: 4}, SIGNOS)
        self.assertNotEqual(lejana_sin_alinear[0]["voz"], "sin_alineacion")
        self.assertEqual(cercana_sin_alinear[0]["voz"], "sin_alineacion")

    def test_una_sola_entidad_no_da_pares(self):
        texto = "LasR binds LasR."
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "LasR", "lasR", True, desde=5)]
        self.assertEqual(S.analizar_doc([], texto, menciones, {}, SIGNOS), [])

    def test_la_voz_y_el_regulador_son_coherentes(self):
        texto = COORD_SUJETOS_TEXTO
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "RhlR", "rhlR", True),
                     mencion(texto, "rhlA", "rhlA", False)]
        for p in S.analizar_doc(arbol(COORD_SUJETOS), texto, menciones,
                                {0: 0, 1: 2, 2: 4}, SIGNOS):
            self.assertIn(p["voz"], S.VOCES)
            self.assertLess(p["a"], p["b"])
            orientada = p["voz"] in ("activa", "pasiva", "nominal")
            self.assertEqual(bool(p["regulador_sintactico"]), orientada)
            self.assertEqual(bool(p["blanco_sintactico"]), orientada)


class PruebasAlineacionV2(unittest.TestCase):
    """`contenedores` y lo que la v2 deja como estaba, sin spaCy. Los tramos
    son `(ini_char, fin_char, k)`, como los arma `preparar_doc`."""

    def test_un_tramo_identico_se_alinea_a_su_contenedor(self):
        # «LasR/RhlR activate lasB»: las dos primeras menciones se expanden al
        # mismo token y `filter_spans` se queda con la primera.
        tramos = [(0, 9, 0), (0, 9, 1), (19, 23, 2)]
        conservados = [(0, 9, 0), (19, 23, 2)]
        self.assertEqual(S.contenedores(tramos, conservados), {1: 0})

    def test_un_tramo_contenido_se_alinea_a_su_contenedor(self):
        # La que perdió es el último token de un tramo de tres que se fusiona.
        tramos = [(4, 14, 0), (10, 14, 1)]
        self.assertEqual(S.contenedores(tramos, [(4, 14, 0)]), {1: 0})

    def test_un_traslape_parcial_no_se_asigna(self):
        # Tras fusionar el tramo conservado, ningún token es entero de la que
        # perdió: asignarla sería inventarle un token.
        tramos = [(0, 9, 0), (5, 14, 1)]
        self.assertEqual(S.contenedores(tramos, [(0, 9, 0)]), {})

    def test_sin_perdedoras_no_hay_nada_que_asignar(self):
        tramos = [(0, 4, 0), (15, 19, 1)]
        self.assertEqual(S.contenedores(tramos, tramos), {})

    def test_en_token_compartido(self):
        self.assertEqual(S.en_token_compartido({0: 0, 1: 0, 2: 2}), 1)
        self.assertEqual(S.en_token_compartido({0: 0, 2: 2}), 0)
        self.assertEqual(S.en_token_compartido({}), 0)

    def test_el_esquema_es_el_de_la_v1(self):
        self.assertEqual(S.CAMPOS, CAMPOS_V1)

    def test_mismo_token_va_al_final_de_las_voces(self):
        self.assertEqual(S.VOCES, VOCES_V1 + ("mismo_token",))


def linea_jsonl(pmid, num, a, b, voz, regulador="", version="1"):
    """Una línea del JSONL con el esquema entero; lo que no se pasa, vacío."""
    blanco = (b if regulador == a else a) if regulador else ""
    return collections.OrderedDict([
        ("pmid", pmid), ("fuente_texto", "xml"), ("seccion", "results"),
        ("num_oracion", num), ("huella_oracion", "0" * 16), ("a", a),
        ("b", b), ("a_es_tf", True), ("b_es_tf", False),
        ("regulador_sintactico", regulador), ("blanco_sintactico", blanco),
        ("voz", voz), ("negada", False), ("lema_dominante", ""),
        ("disparador_dominante", ""), ("signo_dominante", ""),
        ("camino", ""), ("longitud_camino", 0),
        ("modelo", "en_core_sci_md-0.5.4"), ("spacy", "3.7.5"),
        ("version", version)])


def escribir_jsonl(ruta, lineas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        for d in lineas:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


class PruebasComparar(unittest.TestCase):
    """`comparar_salidas` y `sintaxis --comparar`, sin spaCy. PMIDs y pares
    inventados."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.carpeta = tmp.name
        self.antes = os.path.join(self.carpeta, "v1.jsonl")
        self.despues = os.path.join(self.carpeta, "v2.jsonl")
        igual = linea_jsonl("90101", 0, "lasB", "lasR", "activa", "lasR")
        alterada = linea_jsonl("90101", 1, "lasR", "rhlA", "activa", "lasR")
        escribir_jsonl(self.antes, [
            igual, alterada,
            linea_jsonl("90102", 0, "lasR", "rhlR", "sin_alineacion"),
            linea_jsonl("90102", 0, "lasB", "rhlR", "sin_alineacion"),
            linea_jsonl("90103", 2, "lasB", "rhlA", "sin_alineacion"),
            linea_jsonl("90104", 0, "lasR", "mexT", "indeterminada"),
        ])
        escribir_jsonl(self.despues, [
            linea_jsonl("90101", 0, "lasB", "lasR", "activa", "lasR", "2"),
            # La que cambió sin deber: antes orientada, ahora no.
            linea_jsonl("90101", 1, "lasR", "rhlA", "indeterminada", "", "2"),
            linea_jsonl("90102", 0, "lasR", "rhlR", "mismo_token", "", "2"),
            linea_jsonl("90102", 0, "lasB", "rhlR", "activa", "rhlR", "2"),
            linea_jsonl("90103", 2, "lasB", "rhlA", "sin_alineacion", "", "2"),
            linea_jsonl("90105", 0, "lasR", "mexT", "indeterminada", "", "2"),
        ])

    def test_cuenta_lo_que_pide_el_criterio(self):
        d = S.comparar_salidas(self.antes, self.despues)
        self.assertEqual((d["lineas_antes"], d["lineas_despues"]), (6, 6))
        self.assertEqual((d["claves_antes"], d["claves_despues"]), (6, 6))
        self.assertEqual((d["claves_solo_antes"], d["claves_solo_despues"]),
                         (1, 1))
        self.assertEqual((d["claves_repetidas_antes"],
                          d["claves_repetidas_despues"]), (0, 0))
        self.assertEqual((d["versiones_antes"], d["versiones_despues"]),
                         ({"1": 6}, {"2": 6}))
        self.assertEqual((d["sin_alineacion_antes"],
                          d["sin_alineacion_despues"],
                          d["mismo_token_despues"]), (3, 1, 1))
        # Solo la `version` distinta no cuenta como cambio; la alterada sí.
        self.assertEqual(d["cambiadas_fuera_de_sin_alineacion"], 1)
        self.assertEqual(d["campos_cambiados_fuera_de_sin_alineacion"],
                         {"blanco_sintactico": 1, "regulador_sintactico": 1,
                          "voz": 1})
        self.assertEqual(d["ejemplos_cambiadas_fuera_de_sin_alineacion"],
                         [["90101", "xml", "1", "lasR", "rhlA"]])
        # Recuperadas: la de `mismo_token` y la que se orientó; la que sigue
        # `sin_alineacion` no.
        self.assertEqual((d["recuperadas"], d["recuperadas_orientadas"]),
                         (2, 1))
        self.assertEqual(list(d["recuperadas_por_voz"].items()),
                         [("activa", 1), ("mismo_token", 1)])
        self.assertEqual(tuple(d["por_voz_antes"]), S.VOCES)
        self.assertEqual((d["por_voz_antes"]["activa"],
                          d["por_voz_antes"]["sin_alineacion"],
                          d["por_voz_antes"]["mismo_token"]), (2, 3, 0))
        self.assertEqual((d["por_voz_despues"]["indeterminada"],
                          d["por_voz_despues"]["mismo_token"]), (2, 1))

    def test_una_clave_repetida_se_cuenta_aparte(self):
        repetida = linea_jsonl("90101", 0, "lasB", "lasR", "pasiva", "lasR",
                               "2")
        with io.open(self.despues, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(repetida) + "\n")
        d = S.comparar_salidas(self.antes, self.despues)
        self.assertEqual((d["lineas_despues"], d["claves_despues"],
                          d["claves_repetidas_despues"]), (7, 6, 1))
        # La repetida no se compara: cuenta la primera línea de la clave.
        self.assertEqual(d["cambiadas_fuera_de_sin_alineacion"], 1)

    def test_una_voz_desconocida_no_se_pierde(self):
        escribir_jsonl(self.despues, [
            linea_jsonl("90101", 0, "lasB", "lasR", "otra_voz", "", "3")])
        d = S.comparar_salidas(self.antes, self.despues)
        self.assertEqual(d["por_voz_despues"]["otra_voz"], 1)
        self.assertEqual(list(d["por_voz_despues"])[-1], "otra_voz")

    def test_escribir_comparacion(self):
        d = S.comparar_salidas(self.antes, self.despues)
        ruta = os.path.join(self.carpeta, "sub", "comparacion.json")
        S.escribir_comparacion(ruta, d)
        self.assertFalse(os.path.exists(ruta + ".tmp"))
        with io.open(ruta, encoding="utf-8") as f:
            leido = json.load(f)
        self.assertEqual(list(leido), list(d))
        self.assertEqual(leido["recuperadas_orientadas"], 1)

    def _args(self, **cambios):
        args = dict(comparar=self.antes, salida=self.despues, json=None,
                    entrada=None, limite=None, diagnostico=False)
        args.update(cambios)
        return argparse.Namespace(**args)

    def test_la_cli_compara_sin_spacy(self):
        from grn_bronce import cli
        ruta = os.path.join(self.carpeta, "comparacion.json")
        lineas = []
        # Con `spacy` en None, cualquier `import spacy` del camino revienta.
        with mock.patch.dict(sys.modules, {"spacy": None}), \
                mock.patch.object(cli, "log", lineas.append):
            self.assertEqual(cli.cmd_sintaxis(self._args(json=ruta)), 0)
        self.assertIn("  cambiadas_fuera_de_sin_alineacion: 1", lineas)
        self.assertIn("  recuperadas: 2", lineas)
        self.assertIn('  recuperadas_por_voz: {"activa": 1, "mismo_token": 1}',
                      lineas)
        with io.open(ruta, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["claves_solo_despues"], 1)

    def test_la_cli_no_mezcla_comparar_con_analizar(self):
        from grn_bronce import cli
        for cambios in ({"salida": None}, {"entrada": "candidatas.csv"},
                        {"limite": 10}, {"diagnostico": True},
                        {"comparar": os.path.join(self.carpeta, "no.jsonl")},
                        {"comparar": None, "json": "r.json"}):
            with mock.patch.object(cli, "log", lambda m: None):
                with self.assertRaises(SystemExit, msg=str(cambios)):
                    cli.cmd_sintaxis(self._args(**cambios))


class PruebasRecursos(unittest.TestCase):
    """Lo que no necesita spaCy: vocabulario, huella, lectura del CSV."""

    def test_el_vocabulario_real_carga_con_signo(self):
        signos = S.cargar_signos()
        self.assertEqual(signos.get("activates"), "+")
        self.assertEqual(signos.get("represses"), "-")
        self.assertEqual(signos.get("regulates"), "?")
        self.assertEqual(signos.get("positive regulator"), "+")

    def test_huella_ignora_los_espacios(self):
        h = S.huella_oracion("LasR  activates\nrhlR.")
        self.assertEqual(h, S.huella_oracion("LasR activates rhlR."))
        self.assertEqual(len(h), 16)
        int(h, 16)

    def test_leer_candidatas(self):
        carpeta = tempfile.mkdtemp()
        try:
            ruta = os.path.join(carpeta, "c.csv")
            with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["pmid", "doi", "fuente_texto", "seccion",
                            "num_oracion", "oracion"])
                w.writerow(["1", "", "abstract", "abstract", "0", "Uno."])
                w.writerow(["2", "", "xml", "results", "4", "Dos."])
            filas = S.leer_candidatas(ruta)
            self.assertEqual(filas[1]["oracion"], "Dos.")
            self.assertEqual(sorted(filas[0]), sorted(S.COLUMNAS_ENTRADA))
            self.assertEqual(len(S.leer_candidatas(ruta, limite=1)), 1)

            mala = os.path.join(carpeta, "m.csv")
            with io.open(mala, "w", encoding="utf-8", newline="") as f:
                f.write("pmid,texto\n1,Uno.\n")
            with self.assertRaises(ValueError):
                S.leer_candidatas(mala)
        finally:
            shutil.rmtree(carpeta)


class PruebasImportacion(unittest.TestCase):

    def test_importar_el_modulo_no_importa_spacy(self):
        """El bronce corre sin el extra: importar `sintaxis` no puede
        arrastrar a spaCy. Con `sys.modules["spacy"] = None`, cualquier
        `import spacy` a nivel de módulo revienta aquí."""
        import grn_bronce
        guardados = dict((k, v) for k, v in sys.modules.items()
                         if k == "spacy" or k.startswith("spacy."))
        previo = sys.modules.pop("grn_bronce.sintaxis", None)
        for k in guardados:
            del sys.modules[k]
        sys.modules["spacy"] = None
        try:
            modulo = importlib.import_module("grn_bronce.sintaxis")
            self.assertTrue(callable(modulo.orientar))
            self.assertIsNone(sys.modules.get("spacy"))
        finally:
            del sys.modules["spacy"]
            sys.modules.update(guardados)
            if previo is not None:
                sys.modules["grn_bronce.sintaxis"] = previo
                grn_bronce.sintaxis = previo


# ------------------------------------------------------------ con spaCy

# Lo que escribió la v1 (`en_core_sci_md` 0.5.4, spaCy 3.7.5) el 21-oct-2026,
# antes de cambiar la alineación, con el léxico de juguete y `SIGNOS`: una
# tupla por par en el orden de `CAMPOS_PAR`. La primera oración no tiene
# menciones que compartan token; en la segunda, «LasR/RhlR-dependent» es un
# token con dos. Si cambian el modelo o las reglas, sube VERSION y esto se
# vuelve a escribir a propósito, no se ajusta hasta que pase.
SIN_COMPARTIR = "rhlA is activated by RhlR, whereas LasR represses lasB."
CON_COMPARTIDO = "LasR/RhlR-dependent expression of rhlA was reduced."
V1_PARES = {
    SIN_COMPARTIR: [
        ("lasB", "lasR", False, True, "lasR", "lasB", "activa", False,
         "repress", "repress", "-", "dobj< >nsubj", 2),
        ("lasB", "rhlA", False, False, "", "", "indeterminada", False,
         "activate", "activated", "+", "dobj< advcl< >nsubjpass", 3),
        ("lasB", "rhlR", False, True, "", "", "indeterminada", False,
         "activate", "activated", "+", "dobj< advcl< >nmod", 3),
        ("lasR", "rhlA", True, False, "", "", "indeterminada", False,
         "activate", "activated", "+", "nsubj< advcl< >nsubjpass", 3),
        ("lasR", "rhlR", True, True, "", "", "indeterminada", False,
         "activate", "activated", "+", "nsubj< advcl< >nmod", 3),
        ("rhlA", "rhlR", False, True, "rhlR", "rhlA", "pasiva", False,
         "activate", "activated", "+", "nsubjpass< >nmod", 2),
    ],
    CON_COMPARTIDO: [
        ("lasR", "rhlA", True, False, "lasR", "rhlA", "nominal", False,
         "dependent", "dependent", "?", "amod< >nmod", 2),
        ("lasR", "rhlR", True, True, "", "", "sin_alineacion", False,
         "", "", "", "", 0),
        ("rhlA", "rhlR", False, True, "", "", "sin_alineacion", False,
         "", "", "", "", 0),
    ],
}


def tuplas(pares):
    return [tuple(p[c] for c in S.CAMPOS_PAR) for p in pares]


def lexico_de_juguete(carpeta):
    """Un `Lexico` de verdad sobre un diccionario sintético de seis genes y
    dos operones: el reconocimiento es el del pipeline, los datos no."""
    from lexico import COLUMNAS_GENES, COLUMNAS_OPERONES, Lexico
    genes = os.path.join(carpeta, "genes.tsv")
    operones = os.path.join(carpeta, "operones.tsv")
    filas = [("PA9001", "lasR", "true"), ("PA9002", "rhlR", "true"),
             ("PA9003", "lasB", "false"), ("PA9004", "mexR", "true"),
             ("PA9005", "mexT", "true"), ("PA9006", "rhlA", "false")]
    with io.open(genes, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNAS_GENES) + "\n")
        for locus, simbolo, tf in filas:
            f.write("\t".join([locus, simbolo, "", "gen", "", tf, "", "manual",
                               "false"]) + "\n")
    with io.open(operones, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLUMNAS_OPERONES) + "\n")
        f.write("mexAB-oprM\tmexA|mexB|oprM\t\tmanual\n")
        f.write("mexEF-oprN\tmexE|mexF|oprN\t\tmanual\n")
    return Lexico.cargar(genes, operones)


@unittest.skipUnless(HAY_SPACY, "spaCy o %s no están instalados" % S.MODELO)
class PruebasConSpacy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.nlp = S.cargar_modelo()
        cls.carpeta = tempfile.mkdtemp()
        cls.lex = lexico_de_juguete(cls.carpeta)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.carpeta)

    def parsear(self, oracion):
        menciones = self.lex.menciones(oracion)
        doc, alineacion = S.preparar_doc(self.nlp, oracion, menciones)
        return self.nlp(doc), menciones, alineacion

    def test_una_unidad_es_una_oracion(self):
        doc, _, _ = self.parsear(S.HUMO_CORTE)
        self.assertEqual(len(list(doc.sents)), 1)
        # Dos oraciones en una unidad: el corte fijado manda sobre el parser.
        doc, _, _ = self.parsear("LasR activates rhlR. RhlR activates rhlA.")
        self.assertEqual(len(list(doc.sents)), 1)
        self.assertEqual(sum(1 for t in doc if t.head.i == t.i), 1)

    def test_alineacion_sin_excepcion(self):
        for oracion in S.HUMO_ALINEACION:
            menciones = self.lex.menciones(oracion)
            self.assertGreaterEqual(len(menciones), 2, oracion)
            pares = S.analizar_oracion(self.nlp, oracion, menciones, SIGNOS)
            self.assertTrue(pares)
            for p in pares:
                self.assertIn(p["voz"], S.VOCES)
        # ΔmexR y mexEF-oprN se alineaban ya en la v1; desde la v2, también
        # las dos menciones de «LasR/RhlR», que comparten token.
        for oracion in S.HUMO_ALINEACION:
            _, menciones, alineacion = self.parsear(oracion)
            self.assertEqual(len(alineacion), len(menciones), oracion)

    def test_las_dos_menciones_del_token_llevan_el_sufijo(self):
        doc, menciones, alineacion = self.parsear(CON_COMPARTIDO)
        k = dict((m[3], i) for i, m in enumerate(menciones))
        self.assertEqual(len(alineacion), len(menciones))
        self.assertEqual(alineacion[k["lasR"]], alineacion[k["rhlR"]])
        self.assertEqual(doc[alineacion[k["lasR"]]].text,
                         "LasR/RhlR-dependent")
        pares = S.analizar_doc(doc, CON_COMPARTIDO, menciones, alineacion,
                               SIGNOS)
        resumen = dict(((p["a"], p["b"]),
                        (p["regulador_sintactico"], p["blanco_sintactico"],
                         p["voz"], p["lema_dominante"]))
                       for p in pares)
        self.assertEqual(resumen, {
            ("lasR", "rhlA"): ("lasR", "rhlA", "nominal", "dependent"),
            ("rhlA", "rhlR"): ("rhlR", "rhlA", "nominal", "dependent"),
            ("lasR", "rhlR"): ("", "", "mismo_token", ""),
        })
        # El par que la v1 ya alineaba sale igual que en la v1.
        self.assertEqual(tuplas(pares)[0], V1_PARES[CON_COMPARTIDO][0])

    def test_sin_token_compartido_la_salida_es_la_de_la_v1(self):
        _, menciones, alineacion = self.parsear(SIN_COMPARTIR)
        self.assertEqual(S.en_token_compartido(alineacion), 0)
        pares = S.analizar_oracion(self.nlp, SIN_COMPARTIR, menciones, SIGNOS)
        self.assertEqual(tuplas(pares), V1_PARES[SIN_COMPARTIR])

    def test_ejecutar_cuenta_las_menciones_en_token_compartido(self):
        entrada = os.path.join(self.carpeta, "compartido.csv")
        salida = os.path.join(self.carpeta, "compartido.jsonl")
        with io.open(entrada, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pmid", "fuente_texto", "seccion", "num_oracion",
                        "oracion"])
            w.writerow(["21", "xml", "results", "3",
                        "LasR/RhlR activate lasB transcription."])
        cuenta = S.ejecutar(entrada, salida, lex=self.lex, nlp=self.nlp,
                            vocab_signos=SIGNOS)
        self.assertEqual((cuenta["menciones"],
                          cuenta["menciones_sin_alineacion"],
                          cuenta["menciones_en_token_compartido"]),
                         (3, 0, 1))
        self.assertEqual(cuenta["pares"], 3)
        self.assertEqual((cuenta["por_voz"]["activa"],
                          cuenta["por_voz"]["mismo_token"],
                          cuenta["por_voz"]["sin_alineacion"]), (2, 1, 0))
        with io.open(salida, encoding="utf-8") as f:
            lineas = [json.loads(l) for l in f]
        self.assertEqual(set(r["version"] for r in lineas), {"2"})

    def test_comparar_la_v1_congelada_con_la_v2(self):
        """La medición de la §7 en chico: lo que escribió la v1 contra lo que
        escribe hoy `ejecutar`, con el mismo modelo y la misma entrada."""
        import spacy
        entrada = os.path.join(self.carpeta, "v1v2.csv")
        antes = os.path.join(self.carpeta, "v1.jsonl")
        despues = os.path.join(self.carpeta, "v2.jsonl")
        filas = [
            {"pmid": "31", "fuente_texto": "xml", "seccion": "results",
             "num_oracion": "0", "oracion": SIN_COMPARTIR},
            {"pmid": "32", "fuente_texto": "abstract", "seccion": "abstract",
             "num_oracion": "4", "oracion": CON_COMPARTIDO},
        ]
        with io.open(entrada, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(S.COLUMNAS_ENTRADA))
            w.writeheader()
            w.writerows(filas)
        S.ejecutar(entrada, despues, lex=self.lex, nlp=self.nlp,
                   vocab_signos=SIGNOS)
        lineas = []
        for fila in filas:
            for t in V1_PARES[fila["oracion"]]:
                r = S._registro(fila, S.huella_oracion(fila["oracion"]),
                                dict(zip(S.CAMPOS_PAR, t)),
                                S.nombre_modelo(self.nlp), spacy.__version__)
                r["version"] = "1"
                lineas.append(r)
        escribir_jsonl(antes, lineas)

        d = S.comparar_salidas(antes, despues)
        self.assertEqual((d["claves_antes"], d["claves_despues"],
                          d["claves_solo_antes"], d["claves_solo_despues"]),
                         (9, 9, 0, 0))
        self.assertEqual(d["cambiadas_fuera_de_sin_alineacion"], 0)
        self.assertEqual((d["sin_alineacion_antes"],
                          d["sin_alineacion_despues"],
                          d["mismo_token_despues"]), (2, 0, 1))
        self.assertEqual((d["recuperadas"], d["recuperadas_orientadas"]),
                         (2, 1))
        self.assertEqual((d["versiones_antes"], d["versiones_despues"]),
                         ({"1": 9}, {"2": 9}))

    def test_esquema_de_analizar_oracion(self):
        menciones = self.lex.menciones(S.HUMO_CORTE)
        pares = S.analizar_oracion(self.nlp, S.HUMO_CORTE, menciones, SIGNOS)
        self.assertEqual(len(pares), 1)
        p = pares[0]
        self.assertEqual(tuple(p), S.CAMPOS_PAR)
        for clave in ("a", "b", "regulador_sintactico", "blanco_sintactico",
                      "voz", "lema_dominante", "disparador_dominante",
                      "signo_dominante", "camino"):
            self.assertIsInstance(p[clave], str, clave)
        for clave in ("a_es_tf", "b_es_tf", "negada"):
            self.assertIsInstance(p[clave], bool, clave)
        self.assertIsInstance(p["longitud_camino"], int)
        self.assertIn(p["signo_dominante"], ("+", "-", "?", ""))
        # La oración de humo es activa de libro: el parser real la orienta.
        self.assertEqual((p["regulador_sintactico"], p["voz"]),
                         ("lasR", "activa"))

    def test_ejecutar_escribe_el_esquema_fijo(self):
        entrada = os.path.join(self.carpeta, "candidatas.csv")
        salida = os.path.join(self.carpeta, "sub", "sintaxis.jsonl")
        nueve = " ".join("g%d" % i for i in range(9))
        with io.open(entrada, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pmid", "fuente_texto", "seccion", "num_oracion",
                        "oracion", "genes"])
            w.writerow(["11", "abstract", "abstract", "0",
                        "LasR is a quorum sensing regulator.", ""])
            w.writerow(["12", "xml", "results", "7",
                        "LasR activates rhlR expression.", ""])
            w.writerow(["13", "xml", "results", "8", nueve, ""])

        class Lex(object):
            """Las nueve entidades `g0`..`g8` para la fila del tope."""
            def menciones(_s, oracion):
                if oracion == nueve:
                    return [(3 * i, 3 * i + 2, "g%d" % i, "g%d" % i, False)
                            for i in range(9)]
                return self.lex.menciones(oracion)

        cuenta = S.ejecutar(entrada, salida, lex=Lex(), nlp=self.nlp,
                            vocab_signos=SIGNOS)
        self.assertEqual(cuenta["filas_leidas"], 3)
        self.assertEqual(cuenta["oraciones_sin_par"], 1)
        self.assertEqual(cuenta["oraciones_demasiadas_entidades"], 1)
        self.assertEqual(cuenta["oraciones_analizadas"], 1)
        self.assertEqual(cuenta["oraciones_partidas_por_el_parser"], 0)
        self.assertEqual(cuenta["pares"], 1)
        self.assertEqual(sum(cuenta["por_voz"].values()), 1)
        self.assertFalse(os.path.exists(salida + ".tmp"))
        with io.open(salida, encoding="utf-8") as f:
            lineas = [json.loads(l) for l in f]
        self.assertEqual(len(lineas), 1)
        r = lineas[0]
        self.assertEqual(tuple(r), S.CAMPOS)
        self.assertEqual((r["pmid"], r["num_oracion"], r["a"], r["b"]),
                         ("12", 7, "lasR", "rhlR"))
        self.assertEqual(r["huella_oracion"],
                         S.huella_oracion("LasR activates rhlR expression."))
        self.assertTrue(r["modelo"].startswith(S.MODELO + "-"))
        self.assertEqual(r["version"], S.VERSION)

    def test_diagnostico(self):
        info = S.diagnostico(lex=self.lex)
        self.assertTrue(info["ok"], info)
        self.assertTrue(info["cargado_sin_scispacy"])
        self.assertNotIn("ner", info["componentes"])
        self.assertIn("parser", info["componentes"])
        # «LasR/RhlR activate lasB transcription.»: una de las tres comparte
        # token y ya ninguna se queda sin alinear.
        compartido = info["humo"]["alineacion"][0]
        self.assertEqual((compartido["en_token_compartido"],
                          compartido["sin_alineacion"]), (1, []))


if __name__ == "__main__":
    unittest.main()
