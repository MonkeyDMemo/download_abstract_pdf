# -*- coding: utf-8 -*-
"""Paso 1: orientación sintáctica de los pares de entidades de cada oración
candidata. Es una PROPUESTA etiquetada, no una afirmación.

El bronce entrega el DÓNDE: oraciones con dos o más entidades del diccionario
PAO1. Este módulo añade, por cada par NO ORDENADO de entidades distintas de la
oración, lo que propone el árbol de dependencias: quién sería el regulador si
la relación existe, en qué voz lo dice la oración, si lo que gobierna el par va
negado y qué disparador domina el camino entre las dos. Decidir si la relación
existe, y con qué signo, sigue siendo del paso 2: `regulador_sintactico` dice
lo que propone el parser, no lo que afirma el artículo.

Pares no ordenados, y no (TF, blanco), a propósito. El bronce y BioBERT solo
orientan desde un factor de transcripción, así que un regulador que el
diccionario no marca como TF --un sRNA, una proteína de unión a ARN, una
cinasa-- nunca puede quedar como regulador. Aquí la orientación sale de la
sintaxis: si la oración pone a `rsmA` de sujeto de `represses`, `rsmA` se
propone como regulador aunque su `es_tf` sea falso.

Las entidades salen del diccionario (`lexico.menciones()`), que reconoce por
patrón: produce falsos positivos y no sustituye a un reconocimiento de
entidades. Una lista de genes que el diccionario lee como entidades se analiza
igual que una oración de verdad.

Es el ÚNICO módulo del proyecto que importa spaCy, y lo importa dentro de las
funciones. Sin spaCy el paquete se importa igual y el resto del bronce corre:
el método es opcional y vive en su propio entorno (`.venv-nlp`, con spaCy
3.7.5, numpy < 2 y el modelo `en_core_sci_md` 0.5.4 de scispaCy, que carga sin
importar `scispacy`). No imprime: recibe un callable `log`.

TRES CORRECCIONES QUE NO SON OPCIONALES
=======================================

1. **`filter_spans` antes de fusionar.** Cada mención se alinea con
   `char_span(..., alignment_mode="expand")` y se fusiona en un solo token para
   que la entidad sea un nodo del árbol. Pero el tokenizador del modelo deja
   `LasR/RhlR` como UN token: las dos menciones se expanden al mismo tramo y
   fusionar los dos lanza E102. `filter_spans` se queda con uno; la mención que
   pierde, o cuyo `char_span` sale `None`, se reporta como `sin_alineacion` en
   sus pares, nunca como excepción.
2. **El corte de oración está congelado.** Una unidad del bronce es una
   oración (93 golden en `test_texto.py`), y el parser del modelo segmenta por
   su cuenta. Antes de parsear se fija `is_sent_start` en el primer token y se
   apaga en todos los demás; el parser respeta esos límites (comprobado: "LasR
   activates rhlR. RhlR activates rhlA." como una unidad sale con una sola
   raíz). Si alguna vez no los respetara, `ejecutar` lo cuenta en
   `oraciones_partidas_por_el_parser` y el par cae en `sin_camino`.
3. **Las mismas ocurrencias que marca BioBERT.** Si una entidad aparece dos
   veces, la ocurrencia la elige `extraer_pares.elegir_ocurrencias()`, con el
   TF primero cuando solo uno de los dos lo es: es el orden en que esa función
   rompe empates en la etapa 2. Así lo que se compara entre los dos métodos es
   el mismo par de tokens.

REGLAS v1
=========

Congeladas el 8 de octubre de 2026, antes de ver una sola salida sobre el
corpus, y escritas con oraciones sintéticas. La muestra juzgada de la
evaluación no se consultó para escribirlas ni para ajustarlas: es el conjunto
con que se van a medir, y ajustar sobre ella mediría el ajuste. Cambiar una
regla sube `VERSION`.

Son funciones puras sobre una interfaz mínima de token (`i`, `text`, `lemma_`,
`pos_`, `tag_`, `dep_`, `head`, `children`), para que las pruebas las cubran
sin spaCy.

- **Camino.** El camino más corto entre los dos tokens pasa por su ancestro
  común. `camino` lo escribe de `a` hacia `b`: `etiqueta<` sube hacia la
  cabeza y `>etiqueta` baja hacia el dependiente.
- **Gobernante.** El ancestro común si es verbo. Si no lo es y el camino
  cruza una relativa (`acl:relcl`, `acl`), el verbo de la relativa: en "the
  rhlR gene, which is repressed by RsaL" el ancestro común es `gene`, pero
  quien relaciona a los dos es `repressed`. Si no, el ancestro común, o el nodo
  interior más cercano a él cuando el ancestro es una de las dos entidades.
  Desde un verbo se baja por `xcomp` y `conj` sin sujeto propio, que heredan el
  del verbo de arriba ("LasR was shown to activate rhlR", "LasR binds the
  promoter and activates rhlR").
- **Rol** de cada entidad ante el gobernante, por el primer arco del camino:
  sujeto, sujeto pasivo, agente (`agent`, o `prep`/`nmod`/`obl` con "by"),
  objeto, complemento con su preposición, modificador; `anidado` si entre los
  dos hay otro verbo. El antecedente de una relativa toma el rol del pronombre
  relativo, o el de un participio reducido.
- **Activa**: sujeto de un verbo -> regulador; el otro tiene que ser objeto o
  complemento preposicional. Las preposiciones de contexto (`in`, `during`,
  `under`, `after`...) no cuentan: "in a lasR mutant" no es un blanco.
- **Pasiva**: el agente es el regulador y el sujeto pasivo el blanco.
- **Inversos** (`require`, `depend`, `need`, `rely`, `respond`): el regulador
  es el complemento y el blanco el sujeto ("rhlR requires LasR"); en pasiva,
  el sujeto pasivo es el regulador ("LasR is required for rhlR expression").
- **Nominal**: "expression of X by Y" (o "X expression by Y") -> Y regula;
  "effect of Y on X" -> Y regula; "Y-dependent", "Y-mediated", "Y-regulated" y
  afines -> Y regula, si solo una de las dos entidades lleva el sufijo; y el
  predicado copulativo: "Y is a regulator of X", "Y is required for X" -> Y
  regula, "X is dependent on Y", "X is a target of Y" -> Y regula.
- **Mutante**: si `extraer_pares.clasificar(oracion)` dice
  `fenotipo_mutante`, el par sale con `voz = "mutante"` y SIN orientar: esa
  redacción invierte el signo y a veces el sentido ("expression of mexEF-oprN
  was increased in the mexT mutant").
- **Negación**: un hijo `neg` del gobernante, o de un verbo por el que se
  bajó, da `negada = True`. No cambia la orientación.
- Si nada orienta, `voz = "indeterminada"`; sin camino entre los dos tokens,
  `sin_camino`.
- **Disparador dominante**: el lema del gobernante, buscado en
  `recursos/disparadores.csv` por superficie y por lema, primero junto con su
  modificador (`positively regulates`, `negative regulator`). Si el par se
  orientó por un sufijo y el gobernante no es disparador, manda el sufijo
  (`dependent`, `mediate`). `signo_dominante` es el signo LÉXICO de esa tabla
  (`+`, `-`, `?`) o vacío: hereda todas sus advertencias.

El esquema de etiquetas del modelo es el de Stanford (GENIA + OntoNotes): no
hay `agent`, el "by" de la pasiva es `case` de un `nmod`, las relativas son
`acl:relcl` y la cópula cuelga como `cop` del predicado. Las reglas aceptan
además las formas de ClearNLP (`prep`/`pobj`/`agent`) y de UD (`obl`,
`nsubj:pass`), para que un cambio de modelo no las deje mudas en silencio.
"""

import collections
import csv
import hashlib
import io
import json
import os
import platform
import sys
import time
import warnings

AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, _RAIZ)
# `extraer_pares` (y el `lexico` que usa) siguen en etapa2, congelada. Se
# importan como en `identificar.py`: copiar `elegir_ocurrencias` o
# `clasificar` abriría la puerta a que la ocurrencia que se orienta aquí y la
# que marca BioBERT dejen de ser la misma sin que nada avise.
sys.path.insert(0, os.path.join(_RAIZ, "etapa2"))

import extraer_pares as _extraer_pares            # noqa: E402
from grn_bronce import texto as _texto            # noqa: E402
from grn_bronce import vocabulario as _vocab      # noqa: E402
from grn_comun.archivos import reemplazar         # noqa: E402

MODELO = "en_core_sci_md"

# Sube cada vez que una línea de la salida pasa a decir algo distinto de la
# misma oración: una regla nueva, un cambio de modelo o de versión de spaCy.
VERSION = "1"

VOCES = ("activa", "pasiva", "nominal", "mutante", "indeterminada",
         "sin_camino", "sin_alineacion")

# El esquema de cada línea del JSONL. Otro código lo consume: se agrega al
# final o se sube VERSION, nunca se reordena en silencio.
CAMPOS = ("pmid", "fuente_texto", "seccion", "num_oracion", "huella_oracion",
          "a", "b", "a_es_tf", "b_es_tf",
          "regulador_sintactico", "blanco_sintactico", "voz", "negada",
          "lema_dominante", "disparador_dominante", "signo_dominante",
          "camino", "longitud_camino", "modelo", "spacy", "version")
# Lo que depende solo de la oración y del par; el resto lo pone `ejecutar`.
CAMPOS_PAR = CAMPOS[5:18]

COLUMNAS_ENTRADA = ("pmid", "fuente_texto", "seccion", "num_oracion",
                    "oracion")

# Oraciones de la prueba de humo. Sintéticas: ninguna sale del corpus ni de los
# datos del laboratorio.
HUMO_CORTE = "In P. aeruginosa, LasR activates rhlR expression."
HUMO_ALINEACION = (
    "LasR/RhlR activate lasB transcription.",
    u"The ΔmexR mutant overexpresses mexAB-oprM.",
    "MexT activates mexEF-oprN expression.",
)

# --------------------------------------------------------------- etiquetas

SUJETO = frozenset(["nsubj", "csubj", "nsubj:xsubj"])
SUJETO_PASIVO = frozenset(["nsubjpass", "csubjpass", "nsubj:pass",
                           "csubj:pass"])
AUX_PASIVA = frozenset(["auxpass", "aux:pass"])
OBJETO = frozenset(["dobj", "obj", "iobj", "dative", "attr", "oprd",
                    "ccomp", "xcomp"])
# Arcos que llevan la preposición en el propio token (`prep`, `agent`, estilo
# ClearNLP) o en un hijo `case` (`nmod`, `obl`, estilo Stanford y UD).
CON_PREPOSICION = frozenset(["prep", "agent", "nmod", "obl", "nmod:tmod"])
MODIFICADOR = frozenset(["compound", "amod", "amod@nmod", "nmod:poss", "poss",
                         "nmod:npmod", "npadvmod", "appos", "nn", "nummod"])
RELATIVAS = frozenset(["acl:relcl", "relcl", "acl"])

# Preposiciones de contexto. Un complemento introducido por ellas dice dónde o
# cuándo, no a quién: en "LasR activates lasB in the rhlR strain", `rhlR` no
# es un blanco de LasR.
PREP_CONTEXTO = frozenset([
    "in", "during", "under", "after", "before", "within", "without",
    "throughout", "than", "as", "despite", "via", "through", "between",
    "among", "across", "like", "unlike"])

# Verbos cuyo sujeto es el regulado y no el regulador.
INVERSOS = frozenset(["require", "depend", "need", "rely", "respond"])

# Predicados copulativos. Con los primeros el sujeto es el regulador ("MexT is
# a positive regulator of mexEF-oprN", "LasR is essential for rhlR
# expression"); con los segundos lo es el complemento ("rhlR is dependent on
# LasR", "rhlR is a target of LasR", "rhlR is part of the LasR regulon").
REGULADOR_SUJETO = frozenset([
    "activator", "repressor", "regulator", "inducer", "modulator",
    "suppressor", "transactivator", "coactivator", "corepressor",
    "co-repressor", "antiactivator", "anti-activator", "antiterminator",
    "essential", "necessary", "sufficient", "required", "important",
    "critical", "crucial", "indispensable", "responsible", "upstream"])
REGULADOR_COMPLEMENTO = frozenset([
    "dependent", "responsive", "target", "member", "part", "downstream"])

# "Y-dependent", "Y-mediated"...: la entidad que lleva el sufijo es la que
# regula. Clave = el sufijo como se escribe; valor = su lema, para que
# `lema_dominante` cuente igual "mediated" que "mediate" en un verbo.
SUFIJOS = {
    "dependent": "dependent", "mediated": "mediate", "regulated": "regulate",
    "controlled": "control", "induced": "induce", "activated": "activate",
    "repressed": "repress", "driven": "drive", "directed": "direct",
    "responsive": "responsive", "inducible": "inducible",
    "repressible": "repressible",
}
_GUIONES = ("-", u"‐", u"‑", u"–")

# --------------------------------------------------------- reglas, puras


def _lema(t):
    return (t.lemma_ or t.text).lower()


def _limpio(texto):
    """Sin la puntuación final que el tokenizador a veces deja pegada: el
    modelo produce `LasR.` y `regulator.` como un solo token."""
    return texto.lower().rstrip(".,;:")


def _es_verbo(t):
    return t.pos_ == "VERB"


def _ancestros(tok):
    """[tok, su cabeza, la cabeza de esta, ..., la raíz]."""
    cadena, vistos = [tok], set([tok.i])
    while tok.head.i != tok.i:
        tok = tok.head
        if tok.i in vistos:
            # Un árbol de verdad no tiene ciclos; uno falso de prueba podría,
            # y colgarse ahí sería peor que cortar.
            break
        vistos.add(tok.i)
        cadena.append(tok)
    return cadena


def ruta(ta, tb):
    """`(subida, ancestro_comun, bajada)`, o None si no hay camino.

    `subida` son los nodos de `ta` hacia arriba sin el ancestro común, y
    `bajada` lo mismo desde `tb`. Si `ta` es el ancestro, `subida` es vacía.
    """
    anc_a, anc_b = _ancestros(ta), _ancestros(tb)
    pos_b = dict((t.i, k) for k, t in enumerate(anc_b))
    for k, t in enumerate(anc_a):
        if t.i in pos_b:
            return anc_a[:k], t, anc_b[:pos_b[t.i]]
    return None


def texto_camino(subida, bajada):
    """`nsubj< >dobj >compound`: de `a` hacia `b`. `<` sube, `>` baja."""
    return " ".join(["%s<" % t.dep_ for t in subida]
                    + [">%s" % t.dep_ for t in reversed(bajada)])


def _bajo(g, t):
    """`[t, ..., hijo de g]` si `t` cuelga de `g`; None si no."""
    cadena = _ancestros(t)
    for k, n in enumerate(cadena):
        if n.i == g.i:
            return cadena[:k] or None
    return None


def gobernante(ta, tb, subida, lca, bajada):
    """El token que relaciona a las dos entidades, o None. Ver el docstring
    del módulo."""
    extremos = (ta.i, tb.i)
    if lca.i not in extremos and _es_verbo(lca) and _lema(lca) != "be":
        return lca
    # Distancia de cada nodo interior al ancestro común: el hijo directo del
    # ancestro está a 1.
    interior = []
    for lado in (subida, bajada):
        for k, n in enumerate(lado):
            if n.i not in extremos:
                interior.append((len(lado) - k, n))
    relativas = [(d, n) for d, n in interior
                 if n.dep_ in RELATIVAS and _es_verbo(n)]
    if relativas:
        return min(relativas, key=lambda x: x[0])[1]
    if lca.i not in extremos:
        return lca
    if interior:
        return min(interior, key=lambda x: x[0])[1]
    return None


def _preposicion(t):
    if t.dep_ in ("prep", "agent"):
        return t.text.lower()
    for c in t.children:
        if c.dep_ == "case":
            return c.text.lower()
    return ""


def rol_de_arco(c):
    """El rol que da el arco `c.dep_`, mirando la preposición si la hay."""
    dep = c.dep_
    if dep in SUJETO:
        return "sujeto"
    if dep in SUJETO_PASIVO:
        return "sujeto_pasivo"
    if dep == "agent" or dep.endswith(":agent"):
        return "agente"
    if dep in OBJETO:
        return "objeto"
    if dep in CON_PREPOSICION:
        p = _preposicion(c)
        if p == "by":
            return "agente"
        return "complemento:" + p if p else "modificador"
    if dep in MODIFICADOR:
        return "modificador"
    return "otro:" + dep


def _rol_de_antecedente(g):
    """El rol del antecedente de la relativa `g`: el de su pronombre relativo
    o, en una relativa reducida, el que dice el participio."""
    for c in g.children:
        if c.tag_ in ("WDT", "WP") or c.text.lower() in ("which", "that",
                                                           "who"):
            r = rol_de_arco(c)
            if r in ("sujeto", "sujeto_pasivo", "objeto"):
                return r
    if g.tag_ == "VBN":
        return "sujeto_pasivo"
    if g.tag_ == "VBG":
        return "sujeto"
    return "antecedente"


def rol(g, t):
    """Rol de la entidad `t` ante el gobernante `g`, o None si no lo tiene."""
    cadena = _bajo(g, t)
    if cadena is not None:
        # Entre `g` y `t` hay otra cláusula: `t` es argumento de ese otro
        # verbo, no de `g`.
        if any(_es_verbo(n) for n in cadena[1:]):
            return "anidado"
        return rol_de_arco(cadena[-1])
    if g.dep_ in RELATIVAS:
        cadena = _ancestros(t)
        ids = [n.i for n in cadena]
        if g.head.i in ids:
            k = ids.index(g.head.i)
            if not any(_es_verbo(n) for n in cadena[1:k]):
                return _rol_de_antecedente(g)
    return None


def _tiene_sujeto(v):
    return any(c.dep_ in SUJETO or c.dep_ in SUJETO_PASIVO
               for c in v.children)


def _es_pasivo(v):
    return any(c.dep_ in AUX_PASIVA for c in v.children)


def bajar(g, ta, tb, heredado):
    """Baja de `g` por `xcomp` y `conj` verbales sin sujeto propio.

    "LasR was shown to activate rhlR": el ancestro común es `shown`, pero quien
    relaciona es `activate`, cuyo sujeto es el de `shown`. Devuelve el nuevo
    gobernante y la cadena de verbos recorrida; `heredado` recibe el rol que
    la entidad sujeto conserva abajo.
    """
    cadena = [g]
    while True:
        movido = False
        for s, o in ((ta, tb), (tb, ta)):
            r = heredado.get(s.i) or rol(g, s)
            if r not in ("sujeto", "sujeto_pasivo"):
                continue
            camino = _bajo(g, o)
            if not camino:
                continue
            c = camino[-1]
            if (c.i == o.i or not _es_verbo(c)
                    or c.dep_ not in ("xcomp", "conj") or _tiene_sujeto(c)):
                continue
            if c.dep_ == "conj":
                heredado[s.i] = r
            else:
                heredado[s.i] = "sujeto_pasivo" if _es_pasivo(c) else "sujeto"
            g = c
            cadena.append(c)
            movido = True
            break
        if not movido:
            return g, cadena


def sufijo(toks, t):
    """El sufijo de "LasR-dependent" que lleva la entidad `t`, o "".

    El tokenizador del modelo deja `LasR-dependent` como un token, y como la
    mención se alinea con `expand`, el token de la entidad lo incluye. Se mira
    también la forma partida (`LasR`, `-`, `dependent`) por si otro modelo
    tokeniza distinto.
    """
    texto = _limpio(t.text)
    for g in _GUIONES:
        if g in texto:
            cola = texto.rsplit(g, 1)[1]
            if cola in SUFIJOS:
                return cola
    i = t.i
    if (i + 2 < len(toks) and toks[i + 1].text in _GUIONES
            and _limpio(toks[i + 2].text) in SUFIJOS):
        return _limpio(toks[i + 2].text)
    return ""


def disparador_de(g, vocab_signos):
    """`(disparador, signo)` del gobernante en el vocabulario, o `("", "")`.

    Primero con su modificador, porque "negatively regulates" dice `-` y
    "regulates" solo dice `?`.
    """
    if g is None or not vocab_signos:
        return "", ""
    texto, lema = _limpio(g.text), _lema(g)
    candidatos = []
    for c in g.children:
        if c.dep_ in ("advmod", "amod"):
            m = _limpio(c.text)
            candidatos += [m + " " + texto, m + " " + lema]
    candidatos += [texto, lema]
    return _buscar_signo(candidatos, vocab_signos)


def _buscar_signo(candidatos, vocab_signos):
    for c in candidatos:
        clave = _vocab.normalizar(c)
        if clave in (vocab_signos or {}):
            return clave, vocab_signos[clave]
    return "", ""


def _regla(ra, rb, es_regulador, es_blanco):
    """'a' o 'b' si exactamente una asignación cuadra; '' si ninguna o las
    dos."""
    a = es_regulador(ra) and es_blanco(rb)
    b = es_regulador(rb) and es_blanco(ra)
    if a and not b:
        return "a"
    if b and not a:
        return "b"
    return ""


def _complemento(r):
    if r == "objeto":
        return True
    if r and r.startswith("complemento:"):
        return r.split(":", 1)[1] not in PREP_CONTEXTO
    return False


def _complemento_o_modificador(r):
    return _complemento(r) or r == "modificador"


def _orientar_verbal(g, ra, rb):
    inverso = _lema(g) in INVERSOS
    if (_es_pasivo(g) or "sujeto_pasivo" in (ra, rb)
            or "agente" in (ra, rb)):
        if inverso:
            # "LasR is required for rhlR expression": el sujeto pasivo regula.
            x = _regla(ra, rb, lambda r: r == "sujeto_pasivo",
                       lambda r: r == "agente" or _complemento(r))
        else:
            x = _regla(ra, rb, lambda r: r == "agente",
                       lambda r: r == "sujeto_pasivo")
        return x, "pasiva"
    if inverso:
        x = _regla(ra, rb, _complemento, lambda r: r == "sujeto")
    else:
        x = _regla(ra, rb, lambda r: r == "sujeto", _complemento)
    return x, "activa"


def _orientar_copulativo(g, ra, rb):
    claves = (_lema(g), _limpio(g.text))
    if any(k in REGULADOR_SUJETO for k in claves):
        return _regla(ra, rb, lambda r: r == "sujeto",
                      _complemento_o_modificador), "nominal"
    if any(k in REGULADOR_COMPLEMENTO for k in claves):
        return _regla(ra, rb, _complemento_o_modificador,
                      lambda r: r == "sujeto"), "nominal"
    return "", "indeterminada"


def _orientar_nominal(ra, rb):
    x = _regla(ra, rb, lambda r: r == "agente",
               lambda r: r in ("complemento:of", "modificador"))
    if not x:
        # "the effect of LasR on rhlR expression"
        x = _regla(ra, rb, lambda r: r == "complemento:of",
                   lambda r: r in ("complemento:on", "complemento:upon"))
    return x, "nominal"


def _vacio(voz):
    return {"regulador": "", "voz": voz, "negada": False,
            "lema_dominante": "", "disparador_dominante": "",
            "signo_dominante": "", "camino": "", "longitud_camino": 0}


def orientar(toks, ia, ib, mutante=False, vocab_signos=None):
    """La propuesta de las reglas v1 para el par de tokens `ia`, `ib`.

    `toks` es la oración ya parseada: un `Doc` o cualquier secuencia de
    tokens con la interfaz mínima. Devuelve un dict con `regulador` (`"a"`,
    `"b"` o `""`, relativo al orden de `ia` e `ib`), `voz`, `negada`,
    `lema_dominante`, `disparador_dominante`, `signo_dominante`, `camino` y
    `longitud_camino`. `longitud_camino` es 0 cuando no hay camino.
    """
    ta, tb = toks[ia], toks[ib]
    r = ruta(ta, tb)
    if r is None:
        return _vacio("sin_camino")
    subida, lca, bajada = r
    res = _vacio("indeterminada")
    res["camino"] = texto_camino(subida, bajada)
    res["longitud_camino"] = len(subida) + len(bajada)

    g = gobernante(ta, tb, subida, lca, bajada)
    heredado, cadena = {}, []
    if g is not None:
        cadena = [g]
        if _es_verbo(g):
            g, cadena = bajar(g, ta, tb, heredado)
        res["negada"] = any(c.dep_ == "neg" for v in cadena
                            for c in v.children)
        res["lema_dominante"] = _lema(g)
        res["disparador_dominante"], res["signo_dominante"] = (
            disparador_de(g, vocab_signos))
    if mutante:
        res["voz"] = "mutante"
        return res

    regulador, voz = "", "indeterminada"
    if g is not None:
        ra = heredado.get(ta.i) or rol(g, ta)
        rb = heredado.get(tb.i) or rol(g, tb)
        if _es_verbo(g) and _lema(g) != "be":
            regulador, voz = _orientar_verbal(g, ra, rb)
        elif any(c.dep_ == "cop" for c in g.children):
            regulador, voz = _orientar_copulativo(g, ra, rb)
        elif g.pos_ in ("NOUN", "PROPN"):
            regulador, voz = _orientar_nominal(ra, rb)
    if not regulador:
        sa, sb = sufijo(toks, ta), sufijo(toks, tb)
        if bool(sa) != bool(sb):
            regulador, voz = ("a" if sa else "b"), "nominal"
            if not res["disparador_dominante"]:
                # "LasR-dependent expression of rhlR": el gobernante es
                # `expression`, que no es disparador; el que lo es va pegado
                # a la entidad.
                s = sa or sb
                res["lema_dominante"] = SUFIJOS[s]
                res["disparador_dominante"], res["signo_dominante"] = (
                    _buscar_signo([s, SUFIJOS[s]], vocab_signos))
    res["regulador"] = regulador
    res["voz"] = voz if regulador else "indeterminada"
    return res


# ------------------------------------------------------------ por oración


def _por_entidad(menciones):
    """{id_canonico: [(ini, fin, superficie, es_tf, k)]}, con `k` el índice de
    la mención en la lista que se recibió."""
    por = collections.OrderedDict()
    for k, (ini, fin, superficie, idc, es_tf) in enumerate(menciones):
        por.setdefault(idc, []).append((ini, fin, superficie, es_tf, k))
    return por


def huella_oracion(oracion):
    """Los 16 primeros hex del sha1 de la oración con espacios normalizados.

    Permite unir esta salida con otra que haya guardado la misma oración sin
    depender de `num_oracion`, que se mueve si cambia el corte.
    """
    return hashlib.sha1(_texto.normalizar_espacios(oracion)
                        .encode("utf-8")).hexdigest()[:16]


def preparar_doc(nlp, oracion, menciones):
    """`(doc, alineacion)`: el Doc tokenizado, con cada mención fusionada en
    un token y el corte de oración fijado, listo para el pipeline.

    `alineacion` es `{indice de mención: indice de token}` y solo trae las
    menciones que quedaron alineadas. Ver las correcciones 1 y 2 del docstring
    del módulo.
    """
    from spacy.util import filter_spans
    doc = nlp.make_doc(oracion)
    tramos = []
    for k, m in enumerate(menciones):
        tramo = doc.char_span(m[0], m[1], label=str(k),
                              alignment_mode="expand")
        if tramo is not None:
            tramos.append(tramo)
    conservados = filter_spans(tramos)
    inicios = dict((t.start_char, int(t.label_)) for t in conservados)
    with doc.retokenize() as r:
        for t in conservados:
            if len(t) > 1:
                r.merge(t)
    alineacion = {}
    for t in doc:
        k = inicios.get(t.idx)
        if k is not None:
            alineacion[k] = t.i
    for t in doc:
        t.is_sent_start = (t.i == 0)
    return doc, alineacion


def analizar_doc(doc, oracion, menciones, alineacion, vocab_signos):
    """Una propuesta por par no ordenado de entidades distintas, con las
    claves de `CAMPOS_PAR`. `a < b` en orden lexicográfico.

    `doc` ya pasó por el pipeline; basta con que se pueda indexar por token.
    """
    mutante = _extraer_pares.clasificar(oracion) == "fenotipo_mutante"
    por = _por_entidad(menciones)
    ids = sorted(por)
    salida = []
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]
            tf_a, tf_b = bool(por[a][0][3]), bool(por[b][0][3])
            if tf_b and not tf_a:
                ob, oa, _ = _extraer_pares.elegir_ocurrencias(por[b], por[a])
            else:
                oa, ob, _ = _extraer_pares.elegir_ocurrencias(por[a], por[b])
            ia, ib = alineacion.get(oa[4]), alineacion.get(ob[4])
            if ia is None or ib is None:
                p = _vacio("sin_alineacion")
            else:
                p = orientar(doc, ia, ib, mutante, vocab_signos)
            regulador = {"a": a, "b": b}.get(p["regulador"], "")
            blanco = {"a": b, "b": a}.get(p["regulador"], "")
            salida.append(collections.OrderedDict([
                ("a", a), ("b", b), ("a_es_tf", tf_a), ("b_es_tf", tf_b),
                ("regulador_sintactico", regulador),
                ("blanco_sintactico", blanco),
                ("voz", p["voz"]), ("negada", p["negada"]),
                ("lema_dominante", p["lema_dominante"]),
                ("disparador_dominante", p["disparador_dominante"]),
                ("signo_dominante", p["signo_dominante"]),
                ("camino", p["camino"]),
                ("longitud_camino", p["longitud_camino"]),
            ]))
    return salida


def analizar_oracion(nlp, oracion, menciones, vocab_signos):
    """Las propuestas de una oración. `menciones` es exactamente lo que
    devuelve `lex.menciones(oracion)`: `(ini, fin, superficie, id_canonico,
    es_tf)` con offsets sobre la oración cruda. Menos de dos entidades
    distintas, lista vacía."""
    if len(set(m[3] for m in menciones)) < 2:
        return []
    doc, alineacion = preparar_doc(nlp, oracion, menciones)
    doc = nlp(doc)
    return analizar_doc(doc, oracion, menciones, alineacion, vocab_signos)


# --------------------------------------------------------------- recursos


def cargar_modelo(nombre=MODELO):
    """El pipeline sin NER: tokenizador, tagger, lematizador y parser.

    El modelo de scispaCy carga sin importar `scispacy`: su tokenizador viene
    serializado dentro del modelo. Solo si eso falla se intenta con
    `scispacy`, por si una versión futura del modelo registrara funciones
    propias.
    """
    import importlib.util
    import spacy
    with warnings.catch_warnings():
        # Python 3.12 avisa de "Possible set union" al compilar una regex
        # del tokenizador serializado. Es del modelo, no un error, y sin el
        # filtro sale en cada carga.
        warnings.filterwarnings("ignore", message="Possible set union",
                                category=FutureWarning)
        try:
            return spacy.load(nombre, exclude=["ner"])
        except Exception:                             # noqa: BLE001
            # Sin scispacy instalado no hay segundo intento: se relanza el
            # error de la carga, que es el que dice qué falta.
            if importlib.util.find_spec("scispacy") is None:
                raise
            import scispacy                           # noqa: F401
            return spacy.load(nombre, exclude=["ner"])


def nombre_modelo(nlp):
    """`en_core_sci_md-0.5.4`, para la columna `modelo`."""
    meta = nlp.meta
    return "%s_%s-%s" % (meta.get("lang", ""), meta.get("name", ""),
                         meta.get("version", ""))


def cargar_signos():
    """{disparador normalizado: signo} de `recursos/disparadores.csv`."""
    return dict(_vocab.Vocabulario.cargar().disparadores)


def leer_candidatas(ruta, limite=None):
    """Las columnas de `COLUMNAS_ENTRADA` del CSV de candidatas de `exportar`.

    El encabezado del CSV usa los identificadores de las columnas; los
    encabezados visibles con aviso solo van al `.xlsx`. Se lee con
    `utf-8-sig` para que un CSV guardado con BOM no esconda la primera
    columna.
    """
    filas = []
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        faltan = [c for c in COLUMNAS_ENTRADA
                  if c not in (lector.fieldnames or [])]
        if faltan:
            raise ValueError(
                "%s no trae las columnas %s. ¿Es el CSV de oraciones "
                "candidatas que escribe `python -m grn_bronce.cli exportar`?"
                % (ruta, ", ".join(faltan)))
        for fila in lector:
            filas.append(dict((c, fila[c]) for c in COLUMNAS_ENTRADA))
            if limite and len(filas) >= limite:
                break
    return filas


# ------------------------------------------------------------- diagnóstico


def diagnostico(log=lambda m: None, lex=None):
    """Versiones, carga del modelo y prueba de humo. Nunca lanza: reporta.

    La prueba de humo comprueba (a) que `HUMO_CORTE` siga siendo UNA oración
    después de parsear, y (b) que cada mención de `HUMO_ALINEACION` se alinee
    o salga como `sin_alineacion`, sin excepción. Las menciones las pone el
    diccionario real (`identificar.cargar_lexico()`) salvo que se pase `lex`.
    """
    info = collections.OrderedDict()
    info["python"] = platform.python_version()
    info["plataforma"] = platform.platform()
    info["spacy"] = info["numpy"] = None
    info["modelo"] = MODELO
    info["version_modelo"] = None
    info["componentes"] = []
    info["cargado_sin_scispacy"] = None
    info["humo"] = collections.OrderedDict()
    info["ok"] = False
    log("Python %s en %s" % (info["python"], info["plataforma"]))
    try:
        import numpy
        import spacy
        info["spacy"], info["numpy"] = spacy.__version__, numpy.__version__
        log("spaCy %s, numpy %s" % (info["spacy"], info["numpy"]))
        nlp = cargar_modelo()
        info["version_modelo"] = nlp.meta.get("version")
        info["componentes"] = list(nlp.pipe_names)
        info["cargado_sin_scispacy"] = "scispacy" not in sys.modules
        log("Modelo %s, componentes %s; %s"
            % (nombre_modelo(nlp), ", ".join(info["componentes"]),
               "cargó sin importar scispacy" if info["cargado_sin_scispacy"]
               else "necesitó importar scispacy"))
        if lex is None:
            from grn_bronce import identificar as _identificar
            lex = _identificar.cargar_lexico()
    except Exception as e:                            # noqa: BLE001
        info["error"] = "%s: %s" % (type(e).__name__, e)
        log("ERROR: %s" % info["error"])
        return info

    menciones = lex.menciones(HUMO_CORTE)
    doc, _ = preparar_doc(nlp, HUMO_CORTE, menciones)
    doc = nlp(doc)
    n = len(list(doc.sents))
    info["humo"]["corte"] = collections.OrderedDict([
        ("oracion", HUMO_CORTE), ("oraciones_tras_parsear", n),
        ("ok", n == 1)])
    log("Humo (a), corte: %d oración(es) tras parsear: %s"
        % (n, "bien" if n == 1 else "MAL"))

    alineacion_ok = True
    info["humo"]["alineacion"] = []
    for oracion in HUMO_ALINEACION:
        menciones = lex.menciones(oracion)
        caso = collections.OrderedDict([
            ("oracion", oracion), ("menciones", len(menciones)),
            ("alineadas", 0), ("sin_alineacion", []), ("pares", 0),
            ("error", ""), ("ok", False)])
        try:
            doc, alineacion = preparar_doc(nlp, oracion, menciones)
            doc = nlp(doc)
            pares = analizar_doc(doc, oracion, menciones, alineacion, {})
            caso["alineadas"] = len(alineacion)
            caso["sin_alineacion"] = [m[2] for k, m in enumerate(menciones)
                                      if k not in alineacion]
            caso["pares"] = len(pares)
            caso["ok"] = (len(menciones) >= 2
                          and all(p["voz"] in VOCES for p in pares))
        except Exception as e:                        # noqa: BLE001
            caso["error"] = "%s: %s" % (type(e).__name__, e)
        alineacion_ok = alineacion_ok and caso["ok"]
        info["humo"]["alineacion"].append(caso)
        # Sin la oración: el `Δ` de una de ellas no existe en cp1252 y
        # tumbaría la consola de Windows; el conteo basta.
        log("Humo (b), alineación: %d menciones, %d alineadas, %d sin "
            "alinear%s" % (caso["menciones"], caso["alineadas"],
                           len(caso["sin_alineacion"]),
                           ", ERROR " + caso["error"] if caso["error"]
                           else ""))
    info["ok"] = info["humo"]["corte"]["ok"] and alineacion_ok
    return info


# --------------------------------------------------------------- ejecución


def _registro(fila, huella, par, modelo, version_spacy):
    r = collections.OrderedDict()
    r["pmid"] = str(fila["pmid"])
    r["fuente_texto"] = fila["fuente_texto"]
    r["seccion"] = fila["seccion"]
    r["num_oracion"] = int(fila["num_oracion"])
    r["huella_oracion"] = huella
    for c in CAMPOS_PAR:
        r[c] = par[c]
    r["modelo"] = modelo
    r["spacy"] = version_spacy
    r["version"] = VERSION
    return r


def ejecutar(entrada_csv, salida_jsonl, limite=None, log=lambda m: None,
             lex=None, nlp=None, vocab_signos=None, lote=256):
    """Recorre el CSV de candidatas y escribe una línea JSON por (oración,
    par no ordenado). Devuelve los conteos.

    La escritura es atómica: a `<salida>.tmp` y `os.replace` al final
    (`grn_comun.archivos.reemplazar`). Una corrida cortada deja intacto el
    archivo anterior.

    Las oraciones con menos de dos entidades distintas no dan líneas, y las
    que tienen más de `identificar.MAX_MENCIONES` se saltan y se cuentan,
    igual que en el bronce: una lista de treinta genes no afirma nada.
    """
    t0 = time.time()
    from grn_bronce import identificar as _identificar
    max_menciones = _identificar.MAX_MENCIONES
    if lex is None:
        log("Cargando el diccionario PAO1...")
        lex = _identificar.cargar_lexico()
    if vocab_signos is None:
        vocab_signos = cargar_signos()
    if nlp is None:
        log("Cargando el modelo %s..." % MODELO)
        nlp = cargar_modelo()
    import spacy
    modelo, version_spacy = nombre_modelo(nlp), spacy.__version__

    filas = leer_candidatas(entrada_csv, limite)
    log("%d filas de %s; modelo %s, spaCy %s"
        % (len(filas), entrada_csv, modelo, version_spacy))

    cuenta = collections.Counter()
    por_voz = collections.Counter()

    def vaciar(pendientes, f):
        docs = nlp.pipe([p[3] for p in pendientes], batch_size=lote)
        for (fila, oracion, menciones, _, alineacion), doc in zip(
                pendientes, docs):
            cuenta["oraciones_analizadas"] += 1
            if sum(1 for t in doc if t.head.i == t.i) > 1:
                cuenta["oraciones_partidas_por_el_parser"] += 1
            huella = huella_oracion(oracion)
            for par in analizar_doc(doc, oracion, menciones, alineacion,
                                    vocab_signos):
                f.write(json.dumps(_registro(fila, huella, par, modelo,
                                             version_spacy),
                                   ensure_ascii=False))
                f.write("\n")
                cuenta["pares"] += 1
                por_voz[par["voz"]] += 1
                if par["regulador_sintactico"]:
                    cuenta["con_regulador"] += 1
                    es_tf = (par["a_es_tf"]
                             if par["regulador_sintactico"] == par["a"]
                             else par["b_es_tf"])
                    if not es_tf:
                        cuenta["regulador_no_tf"] += 1
                if par["negada"]:
                    cuenta["negadas"] += 1

    carpeta = os.path.dirname(salida_jsonl)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    tmp = salida_jsonl + ".tmp"
    try:
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            pendientes = []
            for n, fila in enumerate(filas, 1):
                oracion = fila["oracion"]
                menciones = lex.menciones(oracion)
                distintas = len(set(m[3] for m in menciones))
                if distintas < 2:
                    cuenta["oraciones_sin_par"] += 1
                elif distintas > max_menciones:
                    cuenta["oraciones_demasiadas_entidades"] += 1
                else:
                    doc, alineacion = preparar_doc(nlp, oracion, menciones)
                    cuenta["menciones"] += len(menciones)
                    cuenta["menciones_sin_alineacion"] += (
                        len(menciones) - len(alineacion))
                    pendientes.append((fila, oracion, menciones, doc,
                                       alineacion))
                if len(pendientes) >= lote:
                    vaciar(pendientes, f)
                    pendientes = []
                if n % 2000 == 0:
                    log("  %d de %d filas, %d pares"
                        % (n, len(filas), cuenta["pares"]))
            if pendientes:
                vaciar(pendientes, f)
        reemplazar(tmp, salida_jsonl)
    except BaseException:
        # Un .tmp a medias no sirve para nada y confunde a quien lo
        # encuentre; el archivo anterior, si lo había, sigue intacto.
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    resumen = collections.OrderedDict()
    resumen["entrada"] = entrada_csv
    resumen["salida"] = salida_jsonl
    resumen["filas_leidas"] = len(filas)
    for clave in ("oraciones_analizadas", "oraciones_sin_par",
                  "oraciones_demasiadas_entidades",
                  "oraciones_partidas_por_el_parser", "menciones",
                  "menciones_sin_alineacion", "pares", "con_regulador",
                  "regulador_no_tf", "negadas"):
        resumen[clave] = cuenta[clave]
    resumen["por_voz"] = collections.OrderedDict(
        (v, por_voz[v]) for v in VOCES)
    resumen["max_menciones"] = max_menciones
    resumen["modelo"] = modelo
    resumen["spacy"] = version_spacy
    resumen["version"] = VERSION
    resumen["segundos"] = round(time.time() - t0, 1)
    log("%d pares de %d oraciones en %.0f s -> %s"
        % (resumen["pares"], resumen["oraciones_analizadas"],
           resumen["segundos"], salida_jsonl))
    return resumen
