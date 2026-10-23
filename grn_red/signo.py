# -*- coding: utf-8 -*-
"""El signo de la red con dos reglas más: el voto léxico y el voto por artículo.

APAGADAS POR OMISIÓN
====================
Son dos parámetros de `consolidar` (`signo_lexico` y `voto_articulo`) que por
omisión no corren: la red oficial sigue siendo la de `etapa2/red.py`, byte a
byte, y `consolidar` ni siquiera importa este módulo. Prendidas, la red va a
`red_<nombre>.tsv` con un nombre que hay que dar: sin él iría a
`red_recomendada.tsv`, la del perfil recomendado, y la pisaría. Se miden en la
tanda 2 de la muestra ciega, con la abstención como error y frente a «siempre
+» (`docs/decisiones.md`, «El signo de la red como parámetro»).

EL VOTO LÉXICO (`signo_lexico`)
===============================
En `red.py`, una evidencia que BioBERT predijo `regulates` no vota signo. Con
el voto léxico vota con el del control léxico del punto 18
(`grn_comun/signo_lexico.py`, la misma función que mide la evaluación): el
disparador con signo más cercano al tramo entre sus dos menciones, sobre la
oración cruda y las menciones de `pares.jsonl`. Sin disparador con signo no
vota, y se cuenta.

- `evidencias`, la variante principal: vota toda evidencia `regulates`. Es la
  lectura literal de «cuando la predicción sea regulates».
- `aristas`, la conservadora: igual, pero solo en las aristas sin ningún voto
  con signo de BioBERT (`n_activates + n_represses == 0`). Las que ya tienen
  signo de BioBERT no se tocan, y tampoco las que `red.py` dejó en conflicto,
  que también lo tienen.

El signo de la arista sale de `red.resolver_signo` con los votos de BioBERT
más los léxicos y la misma mayoría. Los conteos de `red.py` (`n_activates`,
`n_represses`, `n_regulates`) no cambian, porque son de BioBERT; los votos
léxicos van en `n_lexico_activates` y `n_lexico_represses`.

Es una propuesta léxica y no el reconocimiento de la relación: la negación, la
voz pasiva y el fenotipo del mutante invierten el signo de un disparador, y
el voto no lo ve. Por eso está apagado hasta medirlo.

EL VOTO POR ARTÍCULO (`voto_articulo`)
======================================
Solo en las aristas mixtas: con al menos un voto + y uno -, contados después
del voto léxico si está prendido. Por oración, un artículo que dice tres veces
lo mismo pesa tres; por artículo, cada uno resuelve sus votos con
`resolver_signo` y vota una vez.

- Los votos de un artículo son los de las evidencias que lo llevan en sus
  `pmids`. Una oración citada igual en dos artículos es una sola evidencia
  (`red.py` deduplica sin el PMID): cuenta una vez por oración y dos por
  artículo.
- Un artículo en conflicto, o sin votos con signo, se abstiene
  (`n_articulos_sin_signo`).
- La arista se decide con `resolver_signo(#artículos +, #artículos -)`. Si
  todos se abstienen queda en conflicto, aunque `resolver_signo(0, 0)` diga
  que no lo hay: una arista con votos de los dos signos que ningún artículo
  resuelve no dejó de contradecirse, y contarla como un conflicto resuelto
  inflaría lo que consigue la regla.

LO QUE SE RECALCULA
===================
Signo, conflicto, confianza y oración representativa, con las definiciones de
`red.agregar`:

- `confianza`: la media de p[signo] de las evidencias que BioBERT predijo con
  ese signo, redondeada a 4, y vacía si no hay ninguna. Una arista que firmó
  solo el léxico no tiene probabilidad que promediar: la p[signo] de una
  evidencia `regulates` no es la de su voto. El informe cuenta las vacías.
- `oracion_representativa`: entre los votantes finales, la de mayor p[signo],
  desempatada por `orden_evidencia`; si solo votó el léxico, la primera por
  `orden_evidencia`, por la misma razón.

Una arista que ninguna regla toca sale con lo que escribió `red.py`, y se
comprueba: si esta réplica de `agregar` se separara de la suya, las aristas
tocadas tampoco serían de fiar.

DE DÓNDE SALEN LAS EVIDENCIAS
=============================
`red.tsv` no trae la predicción ni las probabilidades de cada evidencia. Por
eso `recalcular` corre la cadena de `red.py` (cargar, unir, filtrar,
deduplicar, topar y agregar) con los parámetros que su informe dice que usó, y
`exigir_igual` comprueba que dé las mismas aristas con los mismos conteos
antes de votar: si no, el voto se haría sobre otras evidencias.

LAS COLUMNAS
============
Solo con alguna regla prendida, después de las de `red.py`:

- `signo_red_py`: el signo que dio `red.py`;
- con el voto léxico, `n_lexico_activates` y `n_lexico_represses`, vacías
  donde la regla no aplica (con `aristas`, las que ya tenían signo de BioBERT);
- con el voto por artículo, `n_articulos_activates`, `n_articulos_represses`
  y `n_articulos_sin_signo`, solo en las aristas mixtas y vacías en las demás.

EL INFORME
==========
`conteos.signo` de `red_<nombre>_informe.json`, sobre las aristas observadas:
`votos_lexicos` (+, - y sin signo; null sin el voto léxico),
`n_aristas_tocadas` (con algún voto léxico, o decididas por artículo),
`n_aristas_mixtas`, `n_aristas_con_otro_signo`, `transiciones` (de
`signo_red_py` al signo nuevo; la diagonal son las que no cambiaron),
`n_conflictos_creados`, `n_conflictos_resueltos` y `n_aristas_sin_confianza`.
`recursos.disparadores` lleva la huella del CSV de los disparadores, y `red_py`
el informe de `red.py` con su reparto de signos original.

Biblioteca estándar y Python 3.8. No imprime: recibe un callable `log`.
"""

import collections
import io
import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ETAPA2 = os.path.join(_RAIZ, "etapa2")
for _p in (_RAIZ, _ETAPA2):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import red as _red                                    # noqa: E402  (etapa2/red.py)
from grn_bronce import vocabulario as _vocabulario    # noqa: E402
from grn_comun.signo_lexico import signo_cercano      # noqa: E402
from grn_red.consolidar import (ErrorConsolidar, PARES,  # noqa: E402
                                PREDICCIONES)

# El CSV de los disparadores, por su nombre en `vocabulario.VOCABULARIOS`. La
# ruta se arma al usarla, con la carpeta de recursos que lee `Vocabulario`.
ARCHIVO_DISPARADORES = "disparadores.csv"

COLUMNAS_LEXICO = ["n_lexico_activates", "n_lexico_represses"]
COLUMNAS_ARTICULO = ["n_articulos_activates", "n_articulos_represses",
                     "n_articulos_sin_signo"]

# Lo que tiene que coincidir entre la red recalculada y la que escribió
# red.py: la arista, su signo y los votos de BioBERT, que es sobre lo que se
# vota. La confianza y la representativa se comprueban en `aplicar`, en las
# aristas que ninguna regla toca.
COMPARADAS = ("tf", "blanco", "signo", "conflicto", "n_evidencias",
              "n_activates", "n_represses", "n_regulates")

# Lo que las reglas vuelven a decidir de cada arista.
RECALCULADAS = ("signo", "conflicto", "confianza", "oracion_representativa")

_FIRMADOS = ("activates", "represses")
_CONTEOS = ("activates", "represses", "sin_signo")
_DEL_LEXICO = {"+": "activates", "-": "represses"}


def _nada(_m):
    pass


def columnas(signo_lexico, voto_articulo):
    """Las columnas que agregan las reglas, en su orden."""
    salida = ["signo_red_py"]
    if signo_lexico:
        salida += COLUMNAS_LEXICO
    if voto_articulo:
        salida += COLUMNAS_ARTICULO
    return salida


# ------------------------------------------------------------- entradas

def ruta_disparadores():
    return os.path.join(_vocabulario.RECURSOS, ARCHIVO_DISPARADORES)


def cargar_disparadores():
    """`(vocab, ruta)`: el vocabulario del bronce, el mismo que lee el control
    léxico de la evaluación, y la ruta de su CSV de disparadores.

    `Vocabulario.cargar` calla si falta un CSV y deja su tabla vacía. Aquí eso
    es error: sin disparadores el voto léxico no vota nada, y la red saldría
    con el nombre de una regla que no corrió.
    """
    ruta = ruta_disparadores()
    vocab = _vocabulario.Vocabulario.cargar()
    if not vocab.disparadores:
        raise ErrorConsolidar(
            "El voto léxico necesita los disparadores del bronce, y %s %s."
            % (ruta, "no trae ninguno" if os.path.isfile(ruta)
               else "no existe"))
    return vocab, ruta


def menciones_de(ruta_pares, ids):
    """{id_par: (oracion_cruda, mencion_tf, mencion_target)} de `pares.jsonl`,
    solo de los `ids` pedidos.

    La oración es la cruda, no la normalizada de `red.py`, con las menciones
    como las escribió el paso «pares»: lo mismo que la capa le da al control
    léxico de la evaluación.
    """
    ids = set(ids)
    salida = {}
    if not ids:
        return salida
    nombre = os.path.basename(ruta_pares)
    with io.open(ruta_pares, encoding="utf-8") as f:
        for numero, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                par = json.loads(linea)
            except ValueError as e:
                raise ErrorConsolidar("%s línea %d ilegible: %s"
                                      % (nombre, numero, e))
            if par.get("id_par") not in ids:
                continue
            campos = (par.get("oracion_cruda"), par.get("mencion_tf"),
                      par.get("mencion_target"))
            if not all(isinstance(c, str) for c in campos):
                raise ErrorConsolidar(
                    "%s línea %d: el par %s no trae oracion_cruda, mencion_tf "
                    "y mencion_target como texto, y el voto léxico mide la "
                    "distancia del disparador a las dos menciones. Lo escribe "
                    "el paso «pares» del flujo." % (nombre, numero,
                                                    par["id_par"]))
            salida[par["id_par"]] = campos
    faltan = sorted(ids - set(salida))
    if faltan:
        raise ErrorConsolidar(
            "%d evidencias de la red no están en %s (la primera es %s): los "
            "pares no son los de las predicciones." % (len(faltan), nombre,
                                                       faltan[0]))
    return salida


# ------------------------------------------------------------- la misma red

def parametros_de(informe_red):
    """Los parámetros con que corrió `red.py`, leídos de su informe.

    Del informe y no de la configuración: así son los que `red.py` usó, con
    los umbrales ya leídos si venían de un archivo, y no los que se supone que
    le llegaron.
    """
    try:
        return {
            "umbrales": dict((c, float(informe_red["umbrales"][c]))
                             for c in _red.SIGNOS),
            "mayoria": float(informe_red["mayoria"]),
            "max_por_par": int(informe_red["max_por_par"]),
            "min_evidencias": int(informe_red["min_evidencias"]),
            "min_articulos": int(informe_red["min_articulos"]),
            "sin_pies": _red.como_bool(informe_red["sin_pies"]),
            "sin_introduccion": _red.como_bool(
                informe_red["sin_introduccion"]),
            "incluir_autorregulacion": _red.como_bool(
                informe_red["incluir_autorregulacion"]),
        }
    except (KeyError, TypeError, ValueError) as e:
        raise ErrorConsolidar("El informe de etapa2/red.py no trae sus "
                              "parámetros (%r): sin ellos no se puede "
                              "recalcular la misma red." % (e,))


def recalcular(ruta_predicciones, ruta_pares, parametros, log=_nada):
    """Las aristas de `red.py` con sus evidencias, cada una con su predicción
    y sus probabilidades, que `red.tsv` no trae.

    Es la cadena de `red.main` sin escribir nada: las mismas funciones con los
    mismos `parametros` (los de `parametros_de`). `log` va a `unir_con_pares`,
    que por omisión imprime. Un `sys.exit` de `red.py` sale como
    ErrorConsolidar, como en `consolidar`.
    """
    p = parametros
    try:
        filas, _ = _red.cargar_predicciones(ruta_predicciones)
        filas = _red.unir_con_pares(filas, _red.cargar_pares(ruta_pares),
                                    ruta_pares, log)
        vivas = _red.filtrar(filas, p["umbrales"], p["sin_pies"],
                             p["sin_introduccion"],
                             p["incluir_autorregulacion"])
        aristas, _ = _red.agregar(
            _red.topar(_red.deduplicar(vivas), p["max_por_par"]),
            p["mayoria"], p["min_evidencias"], p["min_articulos"])
    except SystemExit as e:
        raise ErrorConsolidar("etapa2/red.py se detuvo al recalcular la red: "
                              "%s" % (e.code,))
    return aristas


def _como_la_escribe_red_py(arista):
    celdas = dict(zip(_red.COLUMNAS_RED,
                      (_red.celda(v) for v in _red.fila_red(arista))))
    return tuple(celdas[c] for c in COMPARADAS)


def _describir(valores):
    return ", ".join("%s=%s" % par for par in zip(COMPARADAS, valores))


def exigir_igual(aristas, filas):
    """Que las aristas recalculadas sean las que `red.py` escribió en `filas`,
    en el mismo orden y con los mismos votos. Si no, ErrorConsolidar."""
    recalculadas = [_como_la_escribe_red_py(a) for a in aristas]
    escritas = [tuple(f[c] for c in COMPARADAS) for f in filas]
    if recalculadas == escritas:
        return
    for i, (mia, suya) in enumerate(zip(recalculadas, escritas), 1):
        if mia != suya:
            raise ErrorConsolidar(
                "La red recalculada no es la que escribió etapa2/red.py: la "
                "arista %d da %s, y red.py escribió %s. El voto se haría sobre "
                "otras evidencias." % (i, _describir(mia), _describir(suya)))
    raise ErrorConsolidar(
        "La red recalculada tiene %d aristas y la de etapa2/red.py %d: el "
        "voto se haría sobre otras evidencias." % (len(recalculadas),
                                                   len(escritas)))


# ------------------------------------------------------------- el voto

def _con_lexico(arista, signo_lexico):
    """Si el voto léxico aplica en la arista."""
    if signo_lexico == "evidencias":
        return True
    return (signo_lexico == "aristas"
            and arista["n_activates"] + arista["n_represses"] == 0)


def _votos(arista, menciones, vocab, con_lexico):
    """Los votos con signo de la arista, `[(evidencia, signo, origen)]`, y la
    cuenta del léxico: `activates`, `represses` y `sin_signo`."""
    votos = []
    lexico = collections.Counter()
    for e in arista["evidencias"]:
        if e["prediccion"] in _FIRMADOS:
            votos.append((e, e["prediccion"], "biobert"))
        elif con_lexico and e["prediccion"] == "regulates":
            oracion, mencion_tf, mencion_blanco = menciones[e["id_par"]]
            signo = _DEL_LEXICO.get(signo_cercano(oracion, mencion_tf,
                                                  mencion_blanco, vocab))
            if signo:
                votos.append((e, signo, "lexico"))
            lexico[signo or "sin_signo"] += 1
    return votos, lexico


def _por_articulo(arista, votos, mayoria):
    """Cuántos artículos votan + y -, y cuántos se abstienen.

    Cada PMID de una evidencia recibe su voto: la oración repetida en dos
    artículos vota en los dos. Un artículo sin votos con signo, o en
    conflicto, se abstiene.
    """
    por_pmid = collections.defaultdict(collections.Counter)
    for e, signo, _origen in votos:
        for pmid in e["pmids"]:
            por_pmid[pmid][signo] += 1
    cuenta = collections.Counter()
    for pmid in arista["pmids"]:
        votos_del_articulo = por_pmid[pmid]
        signo, _ = _red.resolver_signo(votos_del_articulo["activates"],
                                       votos_del_articulo["represses"],
                                       mayoria)
        cuenta[signo if signo in _FIRMADOS else "sin_signo"] += 1
    return cuenta


def _decidir(arista, menciones, vocab, signo_lexico, voto_articulo, mayoria):
    """El signo de una arista con las reglas, y lo que lo explica."""
    con_lexico = _con_lexico(arista, signo_lexico)
    votos, lexico = _votos(arista, menciones, vocab, con_lexico)
    n = collections.Counter(signo for _e, signo, _origen in votos)
    mixta = n["activates"] > 0 and n["represses"] > 0
    articulos = None
    if voto_articulo and mixta:
        articulos = _por_articulo(arista, votos, mayoria)
        signo, conflicto = _red.resolver_signo(articulos["activates"],
                                               articulos["represses"], mayoria)
        # Si todos se abstuvieron, la contradicción sigue ahí: ver el
        # docstring del módulo.
        conflicto = conflicto or not (articulos["activates"]
                                      or articulos["represses"])
    else:
        signo, conflicto = _red.resolver_signo(n["activates"], n["represses"],
                                               mayoria)
    # Las definiciones de red.agregar(), sobre las evidencias en su orden, que
    # es también el de la suma de la confianza.
    de_biobert = [e for e in arista["evidencias"] if e["prediccion"] == signo]
    del_lexico = [e for e, s, origen in votos
                  if origen == "lexico" and s == signo]
    confianza = None
    if de_biobert:
        confianza = round(sum(e["p"][signo] for e in de_biobert)
                          / float(len(de_biobert)), 4)
        representativa = min(de_biobert + del_lexico,
                             key=lambda e: (-e["p"][signo],
                                            _red.orden_evidencia(e)))
    elif del_lexico:
        representativa = min(del_lexico, key=_red.orden_evidencia)
    else:
        representativa = min(arista["evidencias"],
                             key=lambda e: (-e["p"][signo],
                                            _red.orden_evidencia(e)))
    return {"signo": signo, "conflicto": conflicto, "confianza": confianza,
            "oracion": representativa["oracion"], "con_lexico": con_lexico,
            "lexico": lexico, "articulos": articulos, "mixta": mixta,
            "tocada": bool(lexico["activates"] or lexico["represses"]
                           or articulos is not None)}


def _exigir_lo_de_red_py(fila, nueva):
    distintas = [c for c in RECALCULADAS if fila[c] != nueva[c]]
    if distintas:
        raise ErrorConsolidar(
            "Ninguna regla toca la arista %s->%s y aquí sale con otro %s que "
            "en etapa2/red.py: la réplica de red.agregar() en grn_red/signo.py "
            "se separó de la suya, y las aristas tocadas tampoco serían de "
            "fiar." % (fila["tf"], fila["blanco"], ", ".join(distintas)))


def aplicar(filas, aristas, menciones, vocab, signo_lexico, voto_articulo,
            mayoria):
    """Las filas de `red.py` con el signo de las reglas.

    `filas` son las de su `red.tsv` y `aristas` las de `recalcular`, en el
    mismo orden (`exigir_igual`); `menciones`, las de `menciones_de` para las
    evidencias que el voto léxico mira. Devuelve `(filas, columnas, resumen)`:
    las filas con las columnas de las reglas, esas columnas en su orden y los
    conteos del informe.
    """
    transiciones = collections.OrderedDict(
        (antes, collections.OrderedDict((ahora, 0) for ahora in _red.SIGNOS))
        for antes in _red.SIGNOS)
    cuenta = collections.Counter()
    salida = []
    for fila, arista in zip(filas, aristas):
        d = _decidir(arista, menciones, vocab, signo_lexico, voto_articulo,
                     mayoria)
        nueva = dict(fila)
        nueva["signo_red_py"] = fila["signo"]
        nueva["signo"] = d["signo"]
        nueva["conflicto"] = _red.texto_bool(d["conflicto"])
        nueva["confianza"] = ("" if d["confianza"] is None
                              else "%.4f" % d["confianza"])
        nueva["oracion_representativa"] = _red.celda(d["oracion"])
        if not d["tocada"]:
            _exigir_lo_de_red_py(fila, nueva)
        if signo_lexico:
            for columna, clave in zip(COLUMNAS_LEXICO, _FIRMADOS):
                nueva[columna] = (str(d["lexico"][clave]) if d["con_lexico"]
                                  else "")
            if d["con_lexico"]:
                for clave in _CONTEOS:
                    cuenta["lexico_" + clave] += d["lexico"][clave]
        if voto_articulo:
            for columna, clave in zip(COLUMNAS_ARTICULO, _CONTEOS):
                nueva[columna] = ("" if d["articulos"] is None
                                  else str(d["articulos"][clave]))
        antes = fila["conflicto"] == "true"
        transiciones[fila["signo"]][d["signo"]] += 1
        cuenta["tocadas"] += d["tocada"]
        cuenta["mixtas"] += d["mixta"]
        cuenta["conflictos_creados"] += d["conflicto"] and not antes
        cuenta["conflictos_resueltos"] += antes and not d["conflicto"]
        cuenta["sin_confianza"] += d["confianza"] is None
        salida.append(nueva)

    resumen = collections.OrderedDict()
    resumen["votos_lexicos"] = (collections.OrderedDict(
        (clave, cuenta["lexico_" + clave]) for clave in _CONTEOS)
        if signo_lexico else None)
    resumen["n_aristas_tocadas"] = cuenta["tocadas"]
    resumen["n_aristas_mixtas"] = cuenta["mixtas"]
    resumen["n_aristas_con_otro_signo"] = sum(
        n for antes, fila in transiciones.items()
        for ahora, n in fila.items() if antes != ahora)
    # De signo_red_py (la fila) al signo nuevo (la columna); la diagonal son
    # las que no cambiaron.
    resumen["transiciones"] = transiciones
    resumen["n_conflictos_creados"] = cuenta["conflictos_creados"]
    resumen["n_conflictos_resueltos"] = cuenta["conflictos_resueltos"]
    resumen["n_aristas_sin_confianza"] = cuenta["sin_confianza"]
    return salida, columnas(signo_lexico, voto_articulo), resumen


def votar(carpeta, filas, informe_red, signo_lexico=None, voto_articulo=False,
          vocab=None, log=_nada):
    """La red de `red.py` (`filas`, las de su `red.tsv`, e `informe_red`, su
    informe) con las reglas del signo.

    Recalcula sus evidencias con los parámetros del informe, comprueba que
    sean las de esa red y vota. Devuelve lo mismo que `aplicar`. Con
    `signo_lexico` y sin `vocab`, carga el del bronce.
    """
    parametros = parametros_de(informe_red)
    ruta_pares = os.path.join(carpeta, PARES)
    aristas = recalcular(os.path.join(carpeta, PREDICCIONES), ruta_pares,
                         parametros, log)
    exigir_igual(aristas, filas)
    menciones = {}
    if signo_lexico:
        if vocab is None:
            vocab, _ = cargar_disparadores()
        menciones = menciones_de(ruta_pares, [
            e["id_par"] for a in aristas if _con_lexico(a, signo_lexico)
            for e in a["evidencias"] if e["prediccion"] == "regulates"])
    return aplicar(filas, aristas, menciones, vocab, signo_lexico,
                   voto_articulo, parametros["mayoria"])
