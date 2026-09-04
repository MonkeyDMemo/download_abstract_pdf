#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cuánto del patrón de oro llega siquiera a coocurrir en una oración candidata.

Es el **techo del paso 1**: de las relaciones canónicas, cuántas tienen sus dos
extremos juntos en al menos una oración que el bronce marcó como candidata. Lo
que no aparece aquí, el paso 2 no lo puede verificar, porque nunca lo va a ver.

POR QUÉ ESTE ARCHIVO VIVE EN etapa2 Y NO EN grn_bronce
======================================================
Porque abre el patrón de oro, y el paquete bronce no puede. La regla no es
burocracia: si la referencia con la que se evalúa entra en la lógica que
extrae, las métricas dejan de medir lo que el pipeline encuentra y pasan a
medir lo que le sopla la referencia, con la misma etiqueta y la misma pinta de
correcto. `test_contaminacion.py` lo vigila, y este script está en su lista
blanca **como evaluador**: no produce nada que el pipeline consuma, y su única
salida es un informe.

EL DENOMINADOR, Y POR QUÉ SON DOS
=================================
Se reportan los dos, y el orden importa.

- **El honesto (~169)**: relaciones atestiguadas, con signo resuelto y sin
  disputa. Salen del cómputo las 9 que el corpus no contiene, las 6 que el
  corpus no resuelve y las que se contradicen. Pedirle al pipeline que
  recupere una relación cuyo texto no está en el corpus es medir el corpus, no
  el pipeline.
- **Sobre las 190**: para comparar, y porque es el número que la gente cita.
  Siempre sale más bajo, y esa diferencia es justo lo que el denominador
  honesto explica.

Reportar solo el segundo esconde el trabajo; reportar solo el primero parece
que se elige el denominador que favorece. Van los dos, juntos.

    python3 etapa2/evaluar_cobertura_bronce.py [--corrida N]

Solo biblioteca estándar.
"""

import argparse
import collections
import io
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
sys.path.insert(0, _RAIZ)

import evaluar_oro as E                                  # noqa: E402
from grn_bronce import db as bronce_db                   # noqa: E402
from grn_bronce import rutas                             # noqa: E402


def claves_de(fila, operones):
    """Las claves de los dos extremos de una fila del oro.

    Se reusa la maquinaria de `evaluar_oro.py` en vez de escribir otra: si dos
    evaluaciones emparejaran distinto, sus números dejarían de ser comparables
    y nadie sabría cuál mirar.
    """
    alias_tf, alias_bl, _ = E.alias_anclados(
        fila["alias"], fila["tf"], fila["blanco"])
    ktf, _, _ = E.claves_extremo(fila["tf"], alias_tf, operones)
    kbl, _, _ = E.claves_extremo(fila["blanco"], alias_bl, operones)
    return (ktf["exacta"] | ktf["por_alias"] | ktf["por_operon"],
            kbl["exacta"] | kbl["por_alias"] | kbl["por_operon"])


def leer_bronce(con, corrida_id):
    """(por_unidad, vistas) de la corrida.

    `por_unidad` es {unidad candidata -> claves de gen que contiene} y `vistas`
    son todas las claves de gen que el bronce menciona en cualquier oración,
    candidata o no. La segunda hace falta para distinguir "el gen no aparece en
    el corpus" de "aparece pero nunca junto al otro", que son dos fallos
    distintos y solo uno es del paso 1.
    """
    por_unidad = collections.defaultdict(set)
    for f in con.execute(
            """SELECT m.unidad_id, m.texto, m.id_normalizado
                 FROM menciones m
                 JOIN oraciones_candidatas c ON c.unidad_id = m.unidad_id
                WHERE m.corrida_id = ? AND m.tipo IN ('gen','proteina')""",
            (corrida_id,)):
        por_unidad[f["unidad_id"]].add(E.clave(f["texto"]))
        if f["id_normalizado"]:
            por_unidad[f["unidad_id"]].add(E.clave(f["id_normalizado"]))

    vistas = set()
    for f in con.execute(
            """SELECT DISTINCT texto, id_normalizado FROM menciones
                WHERE corrida_id = ? AND tipo IN ('gen','proteina')""",
            (corrida_id,)):
        vistas.add(E.clave(f["texto"]))
        if f["id_normalizado"]:
            vistas.add(E.clave(f["id_normalizado"]))
    return por_unidad, vistas


def contexto_de_perdidas(con, corrida_id):
    """Lo que hace falta para decir POR QUE se perdio una relacion.

    Tres mapas, y cada uno descarta una explicacion distinta:

    - `todas`: las claves de gen de TODA unidad, sea candidata o no. Si los dos
      extremos estan juntos en una unidad que no llego a candidata, el fallo no
      es del reconocimiento sino de un filtro, y el filtro se puede revisar.
    - `seccion`: en que seccion cayo cada unidad, para saber si el filtro fue
      la exclusion de METHODS.
    - `del_diccionario`: las superficies que el diccionario conoce. Un extremo
      que no aparece nunca puede ser que el corpus no lo mencione o que el
      diccionario no sepa nombrarlo, y son fallos de distinto dueno.
    """
    todas = collections.defaultdict(set)
    seccion = {}
    for f in con.execute(
            """SELECT m.unidad_id, m.texto, m.id_normalizado, u.seccion,
                      LENGTH(u.texto) largo
                 FROM menciones m JOIN texto_unidades u ON u.id = m.unidad_id
                WHERE m.corrida_id = ? AND m.tipo IN ('gen','proteina')""",
            (corrida_id,)):
        todas[f["unidad_id"]].add(E.clave(f["texto"]))
        if f["id_normalizado"]:
            todas[f["unidad_id"]].add(E.clave(f["id_normalizado"]))
        seccion[f["unidad_id"]] = (f["seccion"], f["largo"])
    return todas, seccion


def superficies_del_diccionario(ruta):
    """Todo lo que el diccionario sabe nombrar, en minusculas."""
    conocidas = set()
    with io.open(ruta, encoding="utf-8") as f:
        cols = f.readline().rstrip("\n").split("\t")
        for linea in f:
            if not linea.strip():
                continue
            d = dict(zip(cols, linea.rstrip("\n").split("\t")))
            for campo in ("locus_tag", "simbolo"):
                if d.get(campo):
                    conocidas.add(E.clave(d[campo]))
            for a in (d.get("alias") or "").split("|"):
                if a:
                    conocidas.add(E.clave(a))
    return conocidas


def imprimible(texto):
    """El texto, sin lo que la consola de Windows no sabe pintar.

    El corpus biomedico lleva sigmas griegas, simbolos matematicos y guiones
    tipograficos. La consola de Windows es cp1252: lo que cae fuera de Latin-1
    la hace reventar con UnicodeEncodeError, y una traza en medio de un informe
    es peor que un caracter sustituido. Los ARCHIVOS se siguen escribiendo en
    utf-8 explicito; esto es solo para la pantalla.
    """
    codificacion = getattr(sys.stdout, "encoding", None) or "utf-8"
    return texto.encode(codificacion, "replace").decode(codificacion)


def pmids_de(fila):
    return [p.strip() for p in (fila.get("pmids") or "").replace(",", ";")
            .split(";") if p.strip()]


def clasificar_perdida(fila, ktf, kbl, vistas, conocidas, todas, seccion,
                       con_xml, con_pdf, autorregulacion):
    """(causa, unidad de ejemplo o None). Las causas se prueban en orden.

    El orden importa: cada una descarta a la siguiente, y la ultima es la
    unica que no explica nada.
    """
    if autorregulacion:
        return "autorregulacion", None

    # ¿Estan los dos juntos en alguna unidad que no llego a candidata?
    for uid, claves in todas.items():
        if (ktf & claves) and (kbl & claves):
            sec, largo = seccion.get(uid, ("", 0))
            if sec == "excluir":
                return "oracion en seccion excluida", uid
            if largo < 40 or largo > 700:
                return "oracion fuera del rango de largo", uid
            return "otra", uid

    faltan = [(k, n) for k, n in ((ktf, "tf"), (kbl, "blanco"))
              if not (k & vistas)]
    if faltan:
        # Un extremo que no se vio: ¿el diccionario sabe nombrarlo siquiera?
        ciegos = [n for k, n in faltan if not (k & conocidas)]
        if ciegos:
            return ("alias o simbolo ausente del diccionario (%s)"
                    % "+".join(ciegos)), None
        pm = pmids_de(fila)
        if pm and not any(p in con_xml for p in pm) and any(p in con_pdf
                                                            for p in pm):
            return "evidencia solo en PDF no parseado", None
        if pm and not any(p in con_xml for p in pm):
            return "el corpus no tiene texto completo de esos articulos", None
        return "extremo nunca mencionado pese a estar en el diccionario", None

    return "extremos en oraciones distintas", None


def evaluar(oro, disputadas, operones, por_unidad, vistas):
    """Una fila de resultado por fila del oro."""
    salida = []
    for fila in oro:
        ktf, kbl = claves_de(fila, operones)
        par = (E.clave(fila["tf"]), E.clave(fila["blanco"]))

        tf_visto, bl_visto = bool(ktf & vistas), bool(kbl & vistas)

        # La autorregulación se decide ANTES de mirar la cobertura, y no
        # después. Si se mira después, una sola mención de `MexT` satisface los
        # dos extremos --son el mismo conjunto de claves-- y la fila sale
        # "cubierta" sin que el bronce haya emitido jamás ese par. Medido: eran
        # 10 filas contadas de más, el 5.7 % del denominador. El bronce exige
        # dos genes DISTINTOS por oración, así que `X -> x` no puede salir: no
        # es que no se encuentre, es que la regla lo excluye por construcción.
        autorregulacion = bool(ktf & kbl) or par[0] == par[1]
        cubierta = (not autorregulacion
                    and any((ktf & claves) and (kbl & claves)
                            for claves in por_unidad.values()))

        if cubierta:
            motivo = ""
        elif autorregulacion:
            motivo = "autorregulacion"
        elif not tf_visto and not bl_visto:
            motivo = "ningun_extremo_mencionado"
        elif not tf_visto or not bl_visto:
            motivo = "solo_un_extremo_mencionado"
        else:
            motivo = "mencionados_pero_nunca_juntos"

        salida.append({
            "tf": fila["tf"], "blanco": fila["blanco"],
            "signo": fila["signo"], "subsistema": fila["subsistema"],
            "atestiguado": fila["atestiguado"],
            "en_disputa": par in disputadas,
            "cubierta": cubierta, "motivo": motivo,
        })
    return salida


def es_del_denominador_honesto(r):
    """Atestiguada, con signo resuelto y sin disputa.

    Las tres condiciones son la misma idea: no se le puede exigir al pipeline
    que recupere lo que el corpus no dice, no resuelve o se contradice.
    """
    return (r["atestiguado"] == "true"
            and r["signo"] in ("activates", "represses")
            and not r["en_disputa"])


def informar(res, corrida_id, fuente_disputadas, log):
    honestas = [r for r in res if es_del_denominador_honesto(r)]
    cub_h = sum(1 for r in honestas if r["cubierta"])
    cub_t = sum(1 for r in res if r["cubierta"])

    log("=" * 72)
    log("COBERTURA DEL BRONCE SOBRE EL PATRON DE ORO   (corrida %d)"
        % corrida_id)
    log("=" * 72)
    log("")
    log("Que mide: de las relaciones canonicas, cuantas tienen sus DOS extremos")
    log("en al menos una oracion candidata. Es el techo del paso 1: lo que no")
    log("esta aqui, el paso 2 no lo puede verificar porque no lo va a ver.")
    log("")
    log("  Denominador honesto (atestiguada + signo resuelto + sin disputa)")
    log("    %d de %d   ->  %.1f %%" % (cub_h, len(honestas),
                                        100.0 * cub_h / len(honestas)))
    log("")
    log("  Sobre las %d filas del patron, para comparar" % len(res))
    log("    %d de %d   ->  %.1f %%" % (cub_t, len(res),
                                        100.0 * cub_t / len(res)))
    log("")
    log("  La diferencia entre los dos numeros es lo que el denominador")
    log("  honesto saca del computo, no una mejora del pipeline.")
    log("")

    fuera = collections.Counter()
    for r in res:
        if not es_del_denominador_honesto(r):
            if r["atestiguado"] != "true":
                fuera["no atestiguada: el corpus no la contiene"] += 1
            elif r["signo"] not in ("activates", "represses"):
                fuera["signo sin resolver en el corpus"] += 1
            else:
                fuera["en disputa: el corpus se contradice"] += 1
    log("  Por que salen %d filas del denominador honesto:" % (len(res) - len(honestas)))
    for motivo, n in sorted(fuera.items()):
        log("    %-46s %3d" % (motivo, n))
    log("    (las disputadas se detectaron por %s)" % fuente_disputadas)
    log("")

    perdidas = collections.Counter(r["motivo"] for r in honestas
                                   if not r["cubierta"])
    log("  Por que se pierden las %d del denominador honesto:"
        % (len(honestas) - cub_h))
    for motivo, n in perdidas.most_common():
        log("    %-46s %3d" % (motivo, n))
    log("")
    log("  Solo el ultimo motivo es fallo de la coocurrencia. Los dos primeros")
    log("  son limite del corpus o del diccionario, y la autorregulacion es una")
    log("  regla que el bronce todavia no tiene.")
    log("")

    auto = [r for r in res if r["motivo"] == "autorregulacion"]
    if auto:
        log("  Autorregulacion (mismo gen a los dos lados), %d filas:" % len(auto))
        for r in auto[:12]:
            log("    %s -> %s" % (r["tf"], r["blanco"]))
        log("")
    return {"corrida_id": corrida_id,
            "denominador_honesto": {"cubiertas": cub_h, "total": len(honestas)},
            "sobre_190": {"cubiertas": cub_t, "total": len(res)},
            "perdidas_por_motivo": dict(perdidas),
            "fuera_del_denominador": dict(fuera),
            "fuente_disputadas": fuente_disputadas}


def informar_detalle(con, corrida_id, oro, res, operones, conocidas, vistas,
                     log):
    """La tabla de causas de las perdidas del denominador honesto.

    No vuelca el oro: de cada causa sale UN ejemplo, y el ejemplo es una
    oracion del corpus con su PMID, no una fila de la referencia.
    """
    todas, seccion = contexto_de_perdidas(con, corrida_id)
    con_xml = set(f["pmid"] for f in con.execute(
        "SELECT pmid FROM descargas WHERE tipo='xml' AND estatus='ok'"))
    con_pdf = set(f["pmid"] for f in con.execute(
        "SELECT pmid FROM descargas WHERE tipo='pdf' AND estatus='ok'"))

    por_causa = collections.OrderedDict()
    for fila, r in zip(oro, res):
        if r["cubierta"] or not es_del_denominador_honesto(r):
            continue
        ktf, kbl = claves_de(fila, operones)
        causa, uid = clasificar_perdida(
            fila, ktf, kbl, vistas, conocidas, todas, seccion,
            con_xml, con_pdf, r["motivo"] == "autorregulacion")
        por_causa.setdefault(causa, []).append((fila, uid))

    total = sum(len(v) for v in por_causa.values())
    log("=" * 72)
    log("LAS %d PERDIDAS DEL DENOMINADOR HONESTO, POR CAUSA" % total)
    log("=" * 72)
    log("")
    log("  %-52s %s" % ("causa", "n"))
    log("  %s" % ("-" * 58))
    for causa, casos in sorted(por_causa.items(), key=lambda kv: -len(kv[1])):
        log("  %-52s %3d" % (causa, len(casos)))
    log("")

    ceros = [c for c in ("oracion en seccion excluida",
                         "oracion fuera del rango de largo",
                         "evidencia solo en PDF no parseado", "otra")
             if c not in por_causa]
    if ceros:
        log("  Causas que salieron en CERO, y eso informa:")
        for c in ceros:
            log("    %s" % c)
        log("")

    for causa, casos in sorted(por_causa.items(), key=lambda kv: -len(kv[1])):
        fila, uid = casos[0]
        log("  --- %s (%d) ---" % (causa, len(casos)))
        if uid is not None:
            f = con.execute(
                "SELECT pmid, seccion, texto FROM texto_unidades WHERE id=?",
                (uid,)).fetchone()
            log("    pmid %s, seccion %s" % (f["pmid"], f["seccion"]))
            t = f["texto"]
            log("    %s" % imprimible(
                t[:200] + (" [...]" if len(t) > 200 else "")))
        else:
            ktf, kbl = claves_de(fila, operones)
            log("    ninguna oracion junta los dos extremos.")
            visto = [(k, e) for k, e in ((ktf, "regulador"), (kbl, "blanco"))
                     if k & vistas]
            if visto:
                clave_vista = sorted(visto[0][0] & vistas)[0]
                f = con.execute(
                    """SELECT u.pmid, u.seccion, u.texto
                         FROM menciones m JOIN texto_unidades u ON u.id=m.unidad_id
                        WHERE m.corrida_id=? AND lower(m.texto)=? LIMIT 1""",
                    (corrida_id, clave_vista)).fetchone()
                if f is not None:
                    log("    el %s SI aparece; ejemplo pmid %s, seccion %s:"
                        % (visto[0][1], f["pmid"], f["seccion"]))
                    t = f["texto"]
                    log("      %s" % imprimible(
                        t[:190] + (" [...]" if len(t) > 190 else "")))
            else:
                pm = pmids_de(fila)
                log("    ningun extremo aparece en el corpus. Articulo citado")
                log("    por la referencia: pmid %s" % (pm[0] if pm else "-"))
        log("")
    return dict((c, len(v)) for c, v in por_causa.items())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=None,
                    help="Ruta de la base; gana sobre GRN_DATOS.")
    ap.add_argument("--oro", default=os.path.join(AQUI, "oro_pseudomonas.tsv"))
    ap.add_argument("--operones",
                    default=os.path.join(_RAIZ, "grn_bronce", "recursos",
                                         "operones_pao1.tsv"))
    ap.add_argument("--disputadas", default=None)
    ap.add_argument("--corrida", type=int, default=None,
                    help="Por omision, la ultima corrida 'ok' del bronce.")
    ap.add_argument("--salida", default=None, help="JSON con el resultado.")
    ap.add_argument("--detalle", action="store_true",
                    help="Clasificar las perdidas por causa, con un ejemplo.")
    ap.add_argument("--genes",
                    default=os.path.join(_RAIZ, "grn_bronce", "recursos",
                                         "genes_pao1.tsv"))
    args = ap.parse_args(argv)

    ruta_db = args.db or os.path.join(rutas.raiz_datos(), "grn.db")
    if not os.path.exists(ruta_db):
        sys.exit("No existe la base %s." % ruta_db)

    oro = E.cargar_oro(args.oro)
    operones, _ = E.cargar_operones(args.operones)
    disputadas, fuente = E.cargar_disputadas(args.disputadas, oro)
    if len(disputadas) < E.DISPUTADAS_DOCUMENTADAS:
        print("AVISO: la documentacion habla de %d relaciones en disputa y solo "
              "se detectan %d. Las otras no estan nombradas en ninguna parte, "
              "asi que el denominador honesto sale %d filas mas grande de lo "
              "que deberia."
              % (E.DISPUTADAS_DOCUMENTADAS, len(disputadas),
                 E.DISPUTADAS_DOCUMENTADAS - len(disputadas)), flush=True)

    con = bronce_db.conectar(ruta_db)
    try:
        if args.corrida:
            corrida_id = args.corrida
        else:
            fila = con.execute(
                """SELECT id FROM corridas WHERE paso='1' AND estatus='ok'
                    ORDER BY id DESC LIMIT 1""").fetchone()
            if fila is None:
                sys.exit("No hay ninguna corrida del bronce terminada.")
            corrida_id = fila["id"]

        por_unidad, vistas = leer_bronce(con, corrida_id)
        if not por_unidad:
            sys.exit("La corrida %d no tiene oraciones candidatas con genes."
                     % corrida_id)
        res = evaluar(oro, disputadas, operones, por_unidad, vistas)
        log = lambda m: print(m, flush=True)                 # noqa: E731
        resumen = informar(res, corrida_id, fuente, log)
        if args.detalle:
            conocidas = superficies_del_diccionario(args.genes)
            resumen["perdidas_por_causa"] = informar_detalle(
                con, corrida_id, oro, res, operones, conocidas, vistas, log)
    finally:
        con.close()
    if args.salida:
        tmp = args.salida + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(resumen, ensure_ascii=False, indent=2))
        os.replace(tmp, args.salida)
        print("Escrito %s" % args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
