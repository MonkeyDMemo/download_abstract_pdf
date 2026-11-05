# -*- coding: utf-8 -*-
"""El agente (Ouroboros) integrado al flujo: juzga las evidencias de la red.

QUÉ HACE
========
El paso `juez` del flujo tiene dos mitades, y entre ellas corre Ouroboros en
el servidor, que es donde está la GPU:

1. `armar_hoja()`: una fila por evidencia de la red (`red_evidencias.tsv`),
   con la oración y las dos entidades escritas como en ella. Es la misma hoja
   de la rúbrica que anota el experto, así que Ouroboros la lee sin cambios:

       carpeta/juez/hoja.csv     id_item, oracion, entidad_1, entidad_2 (y las
                                 columnas de la rúbrica, vacías)
       carpeta/juez/llave.csv    id_item → arista (tf, blanco), id_par, pmid y
                                 la dirección de la red en términos de la hoja

2. Ouroboros, en el servidor (`docs/ouroboros-v0.md`):

       python -m grn_ouroboros.cli anotar --hoja juez/hoja.csv \\
           --salida juez/ouroboros --config principal

3. `unir()`: lee `juez/ouroboros/anotaciones.csv` y escribe, sin tocar la red:

       red_juez.tsv              red.tsv + el veredicto del agente por arista
       red_evidencias_juez.tsv   red_evidencias.tsv + el veredicto por oración
       juez_resumen.json         conteos y huellas

EL AGENTE MARCA, NO FILTRA
==========================
`red.tsv` no cambia: es la red que miden el contraste y la muestra ciega. El
juicio del agente es una columna más, para ordenar la revisión del experto.
Su calidad está medida aparte (`concordancia` en las tandas): es
exploratorio.

Veredicto por oración, con la etiqueta de la rúbrica que dio el agente:
- `confirma`: relación `si` en la dirección de la arista;
- `invierte`: relación `si` en la dirección contraria;
- `dudosa`: relación `dudoso`, o `si` sin dirección;
- `rechaza`: relación `no`;
- `abstiene`: anotación vacía (respuesta inválida o fragmento no literal).

Veredicto por arista: `confirmada` si alguna oración la confirma; si no,
`invertida` si alguna la invierte; si no, `dudosa`; si no, `rechazada`; y
`sin_juicio` si todas se abstuvieron.

NIVEL DE CONFIANZA (cuando juzga un jurado)
===========================================
Si las anotaciones son de un jurado (`grn_verificacion.cli jurado`), el
comentario de cada oración trae los votos («jurado 1 de 3: si 2, …»). Cada
arista lleva entonces `votos_si` (el máximo entre las oraciones que la
la confirman) y `nivel`, que dice si el jurado respalda la arista tal como
está escrita:
- `alta`: confirmada, con todos los jueces a favor en alguna oración;
- `media`: confirmada con menos votos;
- `al_reves`: invertida (el jurado respalda la flecha contraria, no esta);
- `sin_respaldo`: dudosa, rechazada o sin juicio.
Contra la base curada (corrida 4, 5-nov-2026), las aristas con 3 de 3 votos
están en ella 4 veces más que las de 0. Sin jurado, `nivel` va vacío.

TOPE POR ARISTA
===============
Una arista llega a tener 200 oraciones y la mitad de las aristas tiene una
sola: juzgarlas todas cuesta mucho y añade poco. Con `max_por_arista=N` la
hoja lleva, de cada arista, las N de mayor probabilidad del clasificador (a
igual probabilidad, por pmid e id_par): las mismas que enseña el visor. El
tope se guarda en `juez/parametros.json`, para que la segunda pasada arme la
misma hoja sin repetirlo, y el resumen lo declara. Las oraciones que quedan
fuera llevan el veredicto vacío: no se juzgaron.

Solo biblioteca estándar.
"""

import collections
import csv
import hashlib
import io
import json
import os
import re

from grn_verificacion import muestra as _muestra

CARPETA_JUEZ = "juez"
HOJA = "hoja.csv"
LLAVE = "llave.csv"
CARPETA_OUROBOROS = "ouroboros"
ANOTACIONES = "anotaciones.csv"
PARAMETROS = "parametros.json"

# `fuente_texto` y `num_oracion` son la posición de la oración en el bronce:
# con ellas `grn_ouroboros.cli contexto` encuentra la anterior y la siguiente.
COLUMNAS_LLAVE = ["id_item", "tf", "blanco", "id_par", "pmid", "fuente",
                  "direccion_red", "fuente_texto", "num_oracion"]
COLUMNAS_ARISTA = ["n_juzgadas", "n_confirma", "n_invierte", "n_dudosa",
                   "n_rechaza", "n_abstiene", "veredicto_agente",
                   "signo_agente", "votos_si", "n_jueces", "nivel"]
COLUMNAS_EVIDENCIA = ["id_item", "veredicto_agente", "signo_agente",
                      "votos_si"]
NIVELES = ("alta", "media", "al_reves", "sin_respaldo")
_VOTOS = re.compile(r"jurado \d+ de (\d+): si (\d+)")
VEREDICTOS_ARISTA = ("confirmada", "invertida", "dudosa", "rechazada",
                     "sin_juicio")


class ErrorJuez(Exception):
    pass


def _rutas(carpeta, red="red"):
    base = "red" if red in (None, "", "red") else "red_%s" % red
    juez = os.path.join(carpeta, CARPETA_JUEZ)
    return {
        "red": os.path.join(carpeta, base + ".tsv"),
        "evidencias": os.path.join(carpeta, base + "_evidencias.tsv"),
        "capa": os.path.join(carpeta, "capa_pares.csv"),
        "juez": juez,
        "hoja": os.path.join(juez, HOJA),
        "llave": os.path.join(juez, LLAVE),
        "anotaciones": os.path.join(juez, CARPETA_OUROBOROS, ANOTACIONES),
        "parametros": os.path.join(juez, PARAMETROS),
        "red_juez": os.path.join(carpeta, base + "_juez.tsv"),
        "evidencias_juez": os.path.join(carpeta, base + "_evidencias_juez.tsv"),
        "resumen": os.path.join(carpeta, "juez_resumen.json"),
    }


def _huella(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter="\t")
        return list(lector.fieldnames or []), list(lector)


def _escribir(ruta, columnas, filas, delimitador=","):
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    temporal = ruta + ".tmp"
    with io.open(temporal, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas,
                                  delimiter=delimitador, lineterminator="\n",
                                  extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)
    os.replace(temporal, ruta)


def _menciones_por_par(ruta_capa):
    """{id_par: (tf, target, mencion_tf, mencion_target)} de la capa."""
    if not os.path.isfile(ruta_capa):
        return {}
    pares = {}
    with io.open(ruta_capa, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            pares.setdefault(fila.get("id_par") or "", (
                (fila.get("tf") or "").strip(),
                (fila.get("target") or "").strip(),
                (fila.get("mencion_tf") or "").strip(),
                (fila.get("mencion_target") or "").strip()))
    return pares


def _posiciones_por_par(ruta_capa):
    """{id_par: (fuente_texto, num_oracion)} de la capa."""
    if not os.path.isfile(ruta_capa):
        return {}
    posiciones = {}
    with io.open(ruta_capa, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            posiciones.setdefault(fila.get("id_par") or "", (
                (fila.get("fuente_texto") or "").strip(),
                (fila.get("num_oracion") or "").strip()))
    return posiciones


def _menciones(evidencia, pares):
    """Cómo están escritos en la oración el regulador y el blanco."""
    tf, blanco = evidencia["tf"], evidencia["blanco"]
    par = pares.get(evidencia.get("id_par") or "")
    if par:
        c_tf, c_target, m_tf, m_target = par
        if (c_tf, c_target) == (tf, blanco):
            return m_tf or tf, m_target or blanco
        if (c_tf, c_target) == (blanco, tf):
            return m_target or tf, m_tf or blanco
    return tf, blanco


def _probabilidad(evidencia):
    try:
        return float(evidencia.get("probabilidad") or "")
    except ValueError:
        return float("-inf")


def recortar(evidencias, max_por_arista):
    """De cada arista, las `max_por_arista` de mayor probabilidad; a igual
    probabilidad, por pmid e id_par, para que el recorte no dependa del orden
    del archivo. Sin tope, todas."""
    if not max_por_arista:
        return list(evidencias)
    por_arista = collections.defaultdict(list)
    for ev in evidencias:
        por_arista[(ev["tf"], ev["blanco"])].append(ev)
    elegidas = []
    for grupo in por_arista.values():
        grupo.sort(key=lambda e: (-_probabilidad(e), e.get("pmid") or "",
                                  e.get("id_par") or ""))
        elegidas.extend(grupo[:max_por_arista])
    return elegidas


def leer_tope(carpeta):
    """El tope guardado en juez/parametros.json, o None (todas)."""
    ruta = _rutas(carpeta)["parametros"]
    if not os.path.isfile(ruta):
        return None
    with io.open(ruta, encoding="utf-8") as f:
        try:
            tope = json.load(f).get("max_por_arista")
        except (ValueError, AttributeError):
            raise ErrorJuez("juez/parametros.json ilegible: bórralo o vuelve "
                            "a pedir el tope con --max-por-arista.")
    if tope is not None and (not isinstance(tope, int) or tope < 1):
        raise ErrorJuez("juez/parametros.json: max_por_arista tiene que ser "
                        "un entero ≥ 1 o null.")
    return tope


def guardar_tope(carpeta, max_por_arista):
    ruta = _rutas(carpeta)["parametros"]
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"max_por_arista": max_por_arista}, f, indent=2)
        f.write("\n")


def armar_hoja(carpeta, red="red", max_por_arista=None):
    """Escribe juez/hoja.csv y juez/llave.csv. Devuelve el número de filas."""
    r = _rutas(carpeta, red)
    _, evidencias = _leer_tsv(r["evidencias"])
    evidencias = recortar(evidencias, max_por_arista)
    pares = _menciones_por_par(r["capa"])
    posiciones = _posiciones_por_par(r["capa"])
    evidencias.sort(key=lambda e: (e["tf"], e["blanco"], e.get("pmid") or "",
                                   e.get("id_par") or ""))
    ancho = max(5, len(str(len(evidencias))))
    hoja, llave = [], []
    for i, ev in enumerate(evidencias, start=1):
        m_tf, m_blanco = _menciones(ev, pares)
        e1, e2, direccion = _muestra.entidades({
            "oracion": ev.get("oracion") or "",
            "mencion_regulador": m_tf, "mencion_blanco": m_blanco})
        id_item = "e-%0*d" % (ancho, i)
        hoja.append(_muestra.fila_hoja({
            "id_item": id_item, "oracion": ev.get("oracion") or "",
            "entidad_1": e1, "entidad_2": e2}))
        fuente_texto, num_oracion = posiciones.get(ev.get("id_par") or "",
                                                   ("", ""))
        llave.append({"id_item": id_item, "tf": ev["tf"],
                      "blanco": ev["blanco"], "id_par": ev.get("id_par", ""),
                      "pmid": ev.get("pmid", ""), "fuente": ev.get("fuente", ""),
                      "direccion_red": direccion,
                      "fuente_texto": fuente_texto,
                      "num_oracion": num_oracion})
    _escribir(r["hoja"], _muestra.COLUMNAS_HOJA, hoja)
    _escribir(r["llave"], COLUMNAS_LLAVE, llave)
    return len(hoja)


def veredicto_oracion(anotacion, direccion_red):
    relacion = (anotacion.get("relacion") or "").strip()
    if not relacion:
        return "abstiene"
    if relacion == "no":
        return "rechaza"
    if relacion == "si":
        direccion = (anotacion.get("direccion") or "").strip()
        if direccion == direccion_red:
            return "confirma"
        if direccion in ("1>2", "2>1"):
            return "invierte"
    return "dudosa"


def veredicto_arista(conteo):
    if conteo["confirma"]:
        return "confirmada"
    if conteo["invierte"]:
        return "invertida"
    if conteo["dudosa"]:
        return "dudosa"
    if conteo["rechaza"]:
        return "rechazada"
    return "sin_juicio"


def _signo(signos):
    """Mayoría de + y − entre las oraciones que confirman; vacío si empatan."""
    c = collections.Counter(s for s in signos if s in ("+", "-"))
    if not c or c["+"] == c["-"]:
        return ""
    return "+" if c["+"] > c["-"] else "-"


def votos_de(anotacion):
    """(n_jueces, votos_si) del comentario de un jurado, o (None, None)."""
    m = _VOTOS.search(anotacion.get("comentario") or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def nivel(veredicto, votos_si, n_jueces):
    """alta, media, al_reves o sin_respaldo; vacío si no juzgó un jurado.
    `votos_si` son los de las oraciones que confirman la arista."""
    if not n_jueces:
        return ""
    if veredicto == "invertida":
        return "al_reves"
    if veredicto != "confirmada":
        return "sin_respaldo"
    return "alta" if n_jueces >= 2 and votos_si == n_jueces else "media"


def _leer_anotaciones(r):
    """{id_item: fila} de Ouroboros, comprobando que sea de esta hoja."""
    with io.open(r["hoja"], encoding="utf-8-sig", newline="") as f:
        hoja = {fila["id_item"]: fila for fila in csv.DictReader(f)}
    with io.open(r["anotaciones"], encoding="utf-8-sig", newline="") as f:
        anotaciones = {fila["id_item"]: fila for fila in csv.DictReader(f)}
    ajenos = [i for i in anotaciones if i not in hoja]
    distintos = [i for i, a in anotaciones.items() if i in hoja and any(
        (a.get(c) or "") != (hoja[i].get(c) or "")
        for c in ("oracion", "entidad_1", "entidad_2"))]
    if ajenos or distintos:
        raise ErrorJuez(
            "La anotación de Ouroboros no es de esta hoja (%d ítems ajenos, %d "
            "con otra oración o entidades): vuelve a correrla sobre "
            "juez/hoja.csv." % (len(ajenos), len(distintos)))
    return anotaciones


def unir(carpeta, red="red", max_por_arista=None):
    """Escribe red_juez.tsv, red_evidencias_juez.tsv y juez_resumen.json."""
    r = _rutas(carpeta, red)
    anotaciones = _leer_anotaciones(r)
    with io.open(r["llave"], encoding="utf-8-sig", newline="") as f:
        llave = list(csv.DictReader(f))
    por_par = {}
    por_arista = collections.defaultdict(collections.Counter)
    signos = collections.defaultdict(list)
    por_oracion = collections.Counter()
    votos_arista = {}
    jueces = None
    for fila in llave:
        if fila["id_item"] not in anotaciones:
            # Sin fila en la anotación: no se juzgó (por ejemplo, una
            # segunda oración que solo se pidió para algunas aristas). No es
            # una abstención y no cuenta en la arista.
            por_par[(fila["tf"], fila["blanco"], fila["id_par"])] = (
                fila["id_item"], "", "", "")
            por_oracion["no_juzgada"] += 1
            continue
        anot = anotaciones[fila["id_item"]]
        v = veredicto_oracion(anot, fila["direccion_red"])
        signo = (anot.get("signo") or "").strip()
        n_j, n_si = votos_de(anot)
        jueces = jueces or n_j
        por_par[(fila["tf"], fila["blanco"], fila["id_par"])] = (
            fila["id_item"], v, signo, "" if n_si is None else str(n_si))
        arista = (fila["tf"], fila["blanco"])
        por_arista[arista][v] += 1
        por_oracion[v] += 1
        if v == "confirma":
            signos[arista].append(signo)
        if n_si is not None and v in ("confirma", "invierte"):
            clave_v = (arista, v)
            votos_arista[clave_v] = max(votos_arista.get(clave_v, 0), n_si)

    cols_ev, evidencias = _leer_tsv(r["evidencias"])
    for ev in evidencias:
        id_item, v, signo, n_si = por_par.get(
            (ev["tf"], ev["blanco"], ev.get("id_par", "")), ("", "", "", ""))
        ev.update({"id_item": id_item, "veredicto_agente": v,
                   "signo_agente": signo, "votos_si": n_si})
    _escribir(r["evidencias_juez"], cols_ev + COLUMNAS_EVIDENCIA, evidencias,
              "\t")

    cols_red, aristas = _leer_tsv(r["red"])
    por_veredicto = collections.Counter()
    por_nivel = collections.Counter()
    for a in aristas:
        clave = (a["tf"], a["blanco"])
        c = por_arista.get(clave, collections.Counter())
        v = veredicto_arista(c)
        por_veredicto[v] += 1
        n_si = votos_arista.get(
            (clave, "invierte" if v == "invertida" else "confirma"),
            0 if jueces else "")
        nv = nivel(v, n_si, jueces)
        por_nivel[nv] += 1
        a.update({"votos_si": n_si, "n_jueces": jueces or "", "nivel": nv})
        a.update({"n_juzgadas": sum(c[k] for k in c if k != "abstiene"),
                  "n_confirma": c["confirma"], "n_invierte": c["invierte"],
                  "n_dudosa": c["dudosa"], "n_rechaza": c["rechaza"],
                  "n_abstiene": c["abstiene"], "veredicto_agente": v,
                  "signo_agente": _signo(signos.get(clave, []))})
    _escribir(r["red_juez"], cols_red + COLUMNAS_ARISTA, aristas, "\t")

    resumen = {
        "que_es": "Juicio del agente Ouroboros sobre las evidencias de la red. "
                  "Marca, no filtra: red.tsv no cambia.",
        "aristas": len(aristas),
        "aristas_por_veredicto": {k: por_veredicto[k]
                                  for k in VEREDICTOS_ARISTA},
        "aristas_por_nivel": ({k: por_nivel[k] for k in NIVELES}
                              if jueces else None),
        "jueces": jueces,
        "oraciones": len(llave),
        "oraciones_en_la_red": len(evidencias),
        "max_por_arista": max_por_arista,
        "oraciones_por_veredicto": dict(sorted(por_oracion.items())),
        "huellas": {"red": _huella(r["red"]),
                    "evidencias": _huella(r["evidencias"]),
                    "hoja": _huella(r["hoja"]),
                    "anotaciones": _huella(r["anotaciones"])},
    }
    with io.open(r["resumen"], "w", encoding="utf-8", newline="\n") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return resumen


def ejecutar(carpeta, red="red", log=print, max_por_arista=None):
    """El paso del flujo: siempre la hoja; la unión, si ya está el juicio.

    `max_por_arista` dado se guarda y vale para las pasadas siguientes; sin
    darlo, se usa el guardado (o todas)."""
    r = _rutas(carpeta, red)
    if max_por_arista is not None:
        if max_por_arista < 1:
            raise ErrorJuez("--max-por-arista tiene que ser ≥ 1.")
        guardar_tope(carpeta, max_por_arista)
    else:
        max_por_arista = leer_tope(carpeta)
    n = armar_hoja(carpeta, red, max_por_arista)
    log("Hoja del agente: %d oraciones de la red%s -> %s/%s"
        % (n, " (hasta %d por arista)" % max_por_arista
           if max_por_arista else "", CARPETA_JUEZ, HOJA))
    if not os.path.isfile(r["anotaciones"]):
        log("Falta el juicio del agente: corre Ouroboros sobre esa hoja en el "
            "servidor, con --salida %s/%s (docs/ouroboros-v0.md), y vuelve a "
            "correr este paso." % (CARPETA_JUEZ, CARPETA_OUROBOROS))
        return None
    resumen = unir(carpeta, red, max_por_arista)
    a = resumen["aristas_por_veredicto"]
    log("Aristas: %d. Según el agente: %s."
        % (resumen["aristas"], ", ".join("%s %d" % (k, a[k])
                                          for k in VEREDICTOS_ARISTA)))
    if resumen.get("aristas_por_nivel"):
        n = resumen["aristas_por_nivel"]
        log("Confianza (jurado de %d): %s." % (resumen["jueces"], ", ".join(
            "%s %d" % (k, n[k]) for k in NIVELES)))
    log("Escrito %s, %s y juez_resumen.json; red.tsv no cambia."
        % (os.path.basename(r["red_juez"]),
           os.path.basename(r["evidencias_juez"])))
    return resumen
