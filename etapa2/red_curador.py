# -*- coding: utf-8 -*-
"""La red del lector por artículo, con las columnas de `red.tsv`.

    python etapa2/red_curador.py --relaciones DIR/relaciones.tsv --salida T
    python etapa2/red_curador.py --relaciones A [--relaciones B] \
        --carpeta-contraste D [--unir-con CARPETA] [--solo-acuerdo]

`grn_ouroboros.cli curar` deja `relaciones.tsv`: una fila por relación que un
artículo afirma, con sus citas comprobadas. Aquí se agregan las `valida` en
una arista por par de nodos, para que el evaluador, el contraste y el visor
que ya leen `red.tsv` la lean sin cambios.

- **Un voto por artículo y efecto.** Que un artículo repita la relación con
  otras citas no la hace más cierta.
- **El signo sale de la regla de mayoría de `red.py`** (`resolver_signo`), no
  de una segunda.
- `confianza` va vacía: el lector no da una probabilidad. La
  `oracion_representativa` también: las citas están en `relaciones.tsv`.

Para contrastar: una arista por par de locus
============================================
El contraste (`grn_verificacion.contraste`) lleva cada arista a sus locus y,
si dos aristas del mismo par de locus traen signos distintos, cuenta el par
como «mixto». Unir dos redes por nombre fabricaría mixtos donde una dice
`mexAB-oprM` y la otra `mexA`. Por eso `--carpeta-contraste` escribe una red
con **una arista por par dirigido de locus** (`red.tsv`, `red_evidencias.tsv`
y `pares.jsonl`, lo que el contraste lee):

- la red de `--unir-con` se reescribe con los signos que ya tiene: un par
  con un solo signo da una arista; un par mixto, una por signo, para que
  siga siendo mixto;
- el lector entra con su signo por par: un voto por artículo y efecto entre
  todos los `--relaciones`, con la mayoría de `red.py`;
- en la unión, por par: solo en la red, como está; solo en el lector, con el
  signo del lector; en las dos, vale lo de la red salvo que la red diga
  `regulates` y el lector dé signo;
- `--solo-acuerdo` deja del lector solo los pares que dan **todos** los
  `--relaciones`.

Sin `--relaciones`, la carpeta es la red de `--unir-con` reescrita: el
control de que reescribir no cambia nada.

Es del pipeline: no abre ninguna referencia. Solo biblioteca estándar.
"""

import argparse
import collections
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import red as R                                # noqa: E402
from grn_bronce.operones import clave          # noqa: E402

EFECTOS = ("activates", "represses", "regulates")


def leer_validas(ruta):
    """Las relaciones `valida` de un `relaciones.tsv` del curador."""
    with io.open(ruta, encoding="utf-8", newline="") as f:
        return [fila for fila in csv.DictReader(f, delimiter="\t")
                if fila["estado"] == "valida"]


def red_del_curador(validas, mayoria=0.66):
    """{(clave tf, clave blanco): fila} con las columnas de `red.tsv`."""
    votos = collections.OrderedDict()
    nombres = {}
    for fila in validas:
        llave = (clave(fila["nodo_regulador"]), clave(fila["nodo_blanco"]))
        nombres.setdefault(llave, (fila["nodo_regulador"],
                                   fila["nodo_blanco"]))
        if fila["efecto"] not in EFECTOS:
            raise ValueError("Efecto desconocido: %r." % fila["efecto"])
        votos.setdefault(llave, set()).add((fila["pmid"], fila["efecto"]))
    red = {}
    for llave in sorted(votos):
        cuenta = collections.Counter(efecto for _pmid, efecto in votos[llave])
        signo, conflicto = R.resolver_signo(cuenta["activates"],
                                            cuenta["represses"], mayoria)
        pmids = sorted(set(pmid for pmid, _efecto in votos[llave]))
        tf, blanco = nombres[llave]
        red[llave] = {
            "tf": tf, "blanco": blanco, "signo": signo,
            "conflicto": R.texto_bool(conflicto),
            "n_evidencias": str(len(votos[llave])),
            "n_activates": str(cuenta["activates"]),
            "n_represses": str(cuenta["represses"]),
            "n_regulates": str(cuenta["regulates"]),
            "n_articulos": str(len(pmids)), "confianza": "",
            "autorregulacion": "false", "secciones": "",
            "pmids": "|".join(pmids), "oracion_representativa": ""}
    return red


def unir(red, curador):
    """La unión de la red del paso 2 y la del curador. No modifica sus
    entradas.

    Las aristas de las dos. Donde la red del paso 2 no trae signo
    (`regulates`) y el curador sí, vale el del curador, con las cuentas de la
    red; donde las dos lo traen, vale el de la red del paso 2, que es la que
    ya está medida.
    """
    union = dict(red)
    for llave, fila in curador.items():
        vieja = union.get(llave)
        if vieja is None:
            union[llave] = fila
        elif vieja["signo"] == "regulates" and fila["signo"] != "regulates":
            union[llave] = dict(vieja, signo=fila["signo"])
    return union


def escribir_red(ruta, red):
    R.escribir_tsv(ruta, R.COLUMNAS_RED,
                   [[red[k][c] for c in R.COLUMNAS_RED] for k in sorted(red)])
    os.replace(ruta + ".tmp", ruta)


# ------------------------------------------------- por par de locus

SIGNADOS = ("activates", "represses")


def _locus(campo):
    return [x.strip() for x in (campo or "").split("|") if x.strip()]


def votos_por_par(validas):
    """{(locus regulador, locus blanco): {(pmid, efecto)}} de las relaciones
    válidas. Un blanco que es un operón da un par por gen; un par de un locus
    consigo mismo no entra."""
    votos = collections.defaultdict(set)
    for fila in validas:
        if fila["efecto"] not in EFECTOS:
            raise ValueError("Efecto desconocido: %r." % fila["efecto"])
        for a in _locus(fila["locus_regulador"]):
            for b in _locus(fila["locus_blanco"]):
                if a != b:
                    votos[(a, b)].add((fila["pmid"], fila["efecto"]))
    return dict(votos)


def pares_del_curador(lecturas, mayoria=0.66, solo_acuerdo=False):
    """{par: {signo: {pmid}}} de una lista de lecturas (cada una, las
    relaciones válidas de un lector). Cada par trae un solo signo.

    El signo sale de los votos de todas las lecturas juntas: un voto por
    artículo y efecto. Con `solo_acuerdo`, solo los pares que están en todas.
    """
    por_lectura = [votos_por_par(v) for v in lecturas]
    juntos = collections.defaultdict(set)
    for votos in por_lectura:
        for par, v in votos.items():
            juntos[par] |= v
    salida = {}
    for par in sorted(juntos):
        if solo_acuerdo and not all(par in votos for votos in por_lectura):
            continue
        cuenta = collections.Counter(efecto for _pmid, efecto in juntos[par])
        signo, _conflicto = R.resolver_signo(cuenta["activates"],
                                             cuenta["represses"], mayoria)
        salida[par] = {signo: set(pmid for pmid, _efecto in juntos[par])}
    return salida


def pares_de_la_red(carpeta):
    """{par: {signo: {pmid}}} de una carpeta del flujo, con la misma función
    con que el contraste lleva la red a locus (`aristas_en_locus`). Un par
    con más de un signo es el que el contraste llama «mixto»."""
    from grn_verificacion import contraste
    por_par, _conteos = contraste.aristas_en_locus(
        os.path.join(carpeta, "red.tsv"),
        os.path.join(carpeta, "red_evidencias.tsv"),
        os.path.join(carpeta, "pares.jsonl"))
    salida = {}
    for par, aristas in por_par.items():
        signos = {}
        for a in aristas:
            signos.setdefault(a["signo"], set()).update(a["pmids"])
        salida[par] = signos
    return salida


def _copia(signos):
    return dict((s, set(p)) for s, p in signos.items())


def unir_pares(de_la_red, del_curador):
    """(pares de la unión, conteos). La regla del docstring, por par."""
    union, cuenta = {}, collections.Counter()
    for par, r in de_la_red.items():
        c = del_curador.get(par)
        if c is None:
            union[par] = _copia(r)
            cuenta["solo_red"] += 1
            continue
        (signo, pmids), = c.items()
        if list(r) == ["regulates"] and signo in SIGNADOS:
            union[par] = {signo: set(r["regulates"]) | set(pmids)}
            cuenta["en_las_dos_signo_del_curador"] += 1
        else:
            union[par] = _copia(r)
            cuenta["en_las_dos_vale_la_red"] += 1
    for par, c in del_curador.items():
        if par not in de_la_red:
            union[par] = _copia(c)
            cuenta["solo_curador"] += 1
    return union, cuenta


def escribir_carpeta(salida, pares, resumen=None):
    """`red.tsv`, `red_evidencias.tsv` y `pares.jsonl` con una arista por par
    de locus y signo, y `derivada.json` con los conteos. Los nodos son los
    locus; en un par mixto cada signo va en su arista, con el blanco
    nombrado `locus~signo` para que sus artículos no se mezclen."""
    os.makedirs(salida, exist_ok=True)
    red, evidencias, lineas = [], [], []
    por_signo = collections.Counter()
    for (a, b) in sorted(pares):
        signos = pares[(a, b)]
        id_par = "lp-%s-%s" % (a, b)
        lineas.append(json.dumps(collections.OrderedDict([
            ("id_par", id_par), ("tf", a), ("target", b),
            ("tf_locus", [a]), ("target_locus", [b])])) + "\n")
        for signo in sorted(signos):
            if signo not in EFECTOS:
                raise ValueError("Signo desconocido: %r." % signo)
            pmids = sorted(signos[signo])
            blanco = b if len(signos) == 1 else "%s~%s" % (b, signo)
            por_signo[signo] += 1
            red.append([a, blanco, signo, R.texto_bool(len(signos) > 1),
                        len(pmids), int(signo == "activates"),
                        int(signo == "represses"), int(signo == "regulates"),
                        len(pmids), "", "false", "", "|".join(pmids), ""])
            for pmid in pmids or [""]:
                evidencias.append([a, blanco, id_par, pmid, "", "locus",
                                   signo, "", "", ""])
    for nombre, columnas, filas in (
            ("red.tsv", R.COLUMNAS_RED, red),
            ("red_evidencias.tsv", R.COLUMNAS_EVIDENCIAS, evidencias)):
        ruta = os.path.join(salida, nombre)
        R.escribir_tsv(ruta, columnas, filas)
        os.replace(ruta + ".tmp", ruta)
    with io.open(os.path.join(salida, "pares.jsonl"), "w", encoding="utf-8",
                 newline="") as f:
        f.writelines(lineas)
    conteos = collections.OrderedDict([
        ("pares_de_locus", len(pares)), ("aristas", len(red)),
        ("pares_mixtos", sum(1 for s in pares.values() if len(s) > 1)),
        ("por_signo", collections.OrderedDict(
            (s, por_signo[s]) for s in EFECTOS))])
    conteos.update(resumen or {})
    with io.open(os.path.join(salida, "derivada.json"), "w",
                 encoding="utf-8") as f:
        json.dump(conteos, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return conteos


def carpeta_para_contraste(salida, relaciones=(), unir_con=None,
                           solo_acuerdo=False, mayoria=0.66):
    """Escribe la carpeta y devuelve sus conteos."""
    if not relaciones and not unir_con:
        raise ValueError("Hace falta --relaciones, --unir-con o los dos.")
    del_curador = pares_del_curador(
        [leer_validas(r) for r in relaciones], mayoria, solo_acuerdo) \
        if relaciones else {}
    resumen = collections.OrderedDict([
        ("lecturas", len(relaciones)), ("solo_acuerdo", bool(solo_acuerdo)),
        ("pares_del_curador", len(del_curador))])
    if unir_con:
        de_la_red = pares_de_la_red(unir_con)
        pares, cuenta = unir_pares(de_la_red, del_curador)
        resumen["unida_con"] = os.path.basename(os.path.normpath(unir_con))
        resumen["pares_de_la_red"] = len(de_la_red)
        resumen["union"] = collections.OrderedDict(sorted(cuenta.items()))
    else:
        pares = del_curador
    return escribir_carpeta(salida, pares, resumen)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="La red del lector por artículo, con las columnas de "
                    "red.tsv.")
    ap.add_argument("--relaciones", action="append", default=[],
                    help="El relaciones.tsv de `grn_ouroboros.cli curar`; "
                         "se repite, uno por lector.")
    ap.add_argument("--salida", default=None,
                    help="El TSV de la red por nombre que se escribe.")
    ap.add_argument("--carpeta-contraste", dest="carpeta_contraste",
                    default=None,
                    help="La carpeta que se escribe para el contraste: una "
                         "arista por par de locus.")
    ap.add_argument("--unir-con", dest="unir_con", default=None,
                    help="La carpeta del flujo con la red del paso 2 que se "
                         "une a la del lector.")
    ap.add_argument("--solo-acuerdo", dest="solo_acuerdo",
                    action="store_true",
                    help="Del lector, solo los pares que dan todos los "
                         "--relaciones.")
    ap.add_argument("--mayoria", type=float, default=0.66)
    args = ap.parse_args(argv)
    if bool(args.salida) == bool(args.carpeta_contraste):
        ap.error("Va --salida o --carpeta-contraste, uno de los dos.")
    if args.carpeta_contraste:
        try:
            conteos = carpeta_para_contraste(
                args.carpeta_contraste, args.relaciones, args.unir_con,
                args.solo_acuerdo, args.mayoria)
        except ValueError as e:
            ap.error(str(e))
        print(json.dumps(conteos, ensure_ascii=False))
        return 0
    if len(args.relaciones) != 1 or args.unir_con or args.solo_acuerdo:
        ap.error("--salida va con un solo --relaciones y nada más.")
    red = red_del_curador(leer_validas(args.relaciones[0]), args.mayoria)
    escribir_red(args.salida, red)
    signos = collections.Counter(a["signo"] for a in red.values())
    print("aristas: %d (%s)" % (len(red), ", ".join(
        "%s %d" % (s, signos[s]) for s in EFECTOS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
