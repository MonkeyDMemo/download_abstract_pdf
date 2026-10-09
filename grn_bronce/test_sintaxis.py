# -*- coding: utf-8 -*-
"""Las reglas v1 de `sintaxis.py` y su contacto con spaCy.

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
        # "LasR/RhlR" es un token: solo una de las dos menciones se alinea.
        texto = "LasR/RhlR activate lasB."
        menciones = [mencion(texto, "LasR", "lasR", True),
                     mencion(texto, "RhlR", "rhlR", True),
                     mencion(texto, "lasB", "lasB", False)]
        toks = arbol([("LasR/RhlR", "lasr/rhlr", "NOUN", "NN", "nsubj", 1),
                      ("activate", "activate", "VERB", "VBP", "ROOT", 1),
                      ("lasB", "lasb", "NOUN", "NN", "dobj", 1),
                      (".", ".", "PUNCT", ".", "punct", 1)])
        pares = S.analizar_doc(toks, texto, menciones, {0: 0, 2: 2}, SIGNOS)
        por_par = dict(((p["a"], p["b"]), p) for p in pares)
        self.assertEqual(por_par[("lasB", "lasR")]["regulador_sintactico"],
                         "lasR")
        for par in (("lasB", "rhlR"), ("lasR", "rhlR")):
            p = por_par[par]
            self.assertEqual((p["voz"], p["regulador_sintactico"],
                              p["camino"], p["longitud_camino"]),
                             ("sin_alineacion", "", "", 0))

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
        # ΔmexR y mexEF-oprN se alinean; en LasR/RhlR puede perder una.
        for oracion in S.HUMO_ALINEACION[1:]:
            _, menciones, alineacion = self.parsear(oracion)
            self.assertEqual(len(alineacion), len(menciones), oracion)

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


if __name__ == "__main__":
    unittest.main()
