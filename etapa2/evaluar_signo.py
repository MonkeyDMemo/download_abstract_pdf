#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mide el acierto de signo oración por oración contra la auditoría.

Etapa 6 del contrato de datos. Es uno de los dos únicos scripts autorizados a
abrir `etapa2/auditoria_signo.tsv` (§0.4).

QUÉ MIDE
--------
`auditoria_signo.tsv` trae 198 oraciones sobre seis represores de bombas RND
(MexR, NalC, NalD, NfxB, MexZ, MexL). De esas, **93 afirman la relación y por
tanto tienen la respuesta puesta de antemano: `represses`**. Este script une
esas 93 con las predicciones del modelo y cuenta cuántas acierta.

Es la única medición de signo a nivel de oración que existe en el proyecto, y
por eso es la que dice si el error es del modelo o de la agregación de
`red.py`: aquí no hay umbrales de mayoría, ni dedup, ni votos. Una oración, una
respuesta.

LAS 24 DE LA TRAMPA, APARTE
---------------------------
De las 93, **69 están escritas de forma directa** ("MexL, the repressor of
mexJK") y **24 desde el fenotipo del mutante** ("mutations in nfxB lead to
overexpression of MexCD-OprJ"). Las segundas dicen el signo al revés: un
extractor descuidado lee "mutación" y "sobreexpresión" y contesta `activates`
cuando la relación es `represses`.

Por eso el desglose no es opcional: **un extractor que falle solo en las 24
tiene un problema distinto del que falla en las 69.** El primero necesita una
regla de inversión (§5.2 de `red.py`, `--invertir-fenotipo`); el segundo está
mal cargado o mal entrenado. Un número global de 74 % no distingue los dos
casos, y son arreglos opuestos.

EN QUÉ ORDEN SE LEYERON LOS LOGITS
----------------------------------
Antes de leer una sola predicción se abre `predicciones_meta.json` y se
comprueba `id2label` contra el orden del checkpoint, igual que hace `red.py`.
§8 cuelga este archivo directamente de `clasificar.py`, sin pasar por `red.py`,
así que esta rama del grafo no tenía ningún guardián del orden de las
etiquetas. Con el orden de `LABELS_DEFAULT` --que intercambia `represses` con
`no_relation`-- `red.py` se niega a producir la red pero este archivo publicaba
tan campante 93 de 93 `perdida_a_no_relation`, o una tasa limpia de
`signo_invertido`, y las dos se leen como un fallo del modelo cuando son un
fallo de carga.

LA EQUIVALENCIA DE OPERÓN EN LA UNIÓN
-------------------------------------
4 de los 6 represores tienen el blanco escrito con granularidad de operón
(`mexAB-oprM`, `mexCD-oprJ`, `mexXY`, `mexJK`) mientras la oración del artículo
nombra un gen suelto. Uniendo por `(pmid, tf, blanco)` literal se unían 76 de
93, el guardián de abajo saltaba y no se podía calcular nada. Se expande el
nombre que escribió la auditoría --tabla versionada, escrita a mano--, nunca el
que produjo el pipeline. Ver `claves_blanco()`.

EL CODIGO DE SALIDA, Y POR QUE NO SIEMPRE ES 0
----------------------------------------------
Este archivo era el único que cazaba a un clasificador constante --publicaba
EXACTITUD 0.0 % de 93 con el que contesta siempre `activates`-- y aun así
salía con código 0, mientras `evaluar_oro.py` decía 69.8 % «distinto del azar»
sobre las mismas predicciones. Dos scripts del mismo pipeline saliendo los dos
con 0 y diciendo cosas incompatibles: un guion que encadene las etapas y mire
códigos de salida no notaba nada.

Ahora la exactitud se contrasta contra **la tasa con la que el modelo contesta
esa misma clase en el resto del archivo de predicciones**, con una binomial
exacta. Esa es la línea base sin información: un clasificador que no lee la
oración acierta las 93 con la frecuencia con la que dice `represses` en
cualquier otra parte del corpus. Las 93 son todas de la misma clase, así que
una tasa de acierto alta no significa nada por sí sola: contestar siempre
`represses` las acierta las 93.

- **0** — la exactitud despega de esa tasa (p <= 0.05).
- **2** — no despega, o no hay con qué estimarla. Los dos archivos **sí** se
  escriben, como en `evaluar_oro.py`: el detalle fila por fila es justo lo que
  hace falta para diagnosticar. El código 1 sigue queriendo decir "la entrada
  no sirve y no escribo nada".

LAS PROBABILIDADES TIENEN QUE SUMAR 1
-------------------------------------
La invariante de §4 vivía solo en `clasificar.py`, el único archivo que
necesita `torch`. Aquí se comprueba fila por fila, con la misma función que
usa `evaluar_oro.py`, antes de creerse ninguna probabilidad. Medido: 65216
filas con las cuatro clases a 0.99 (suma 3.96) entraban sin que nada las
mirara.

EL GUARDIÁN DE 80 DE 93
-----------------------
Si menos de 80 de las 93 se unen con una predicción, el script sale con código
1 sin escribir métrica. Es el guardián más barato del contrato: si alguien
cambia la segmentación de oraciones, las 93 dejan de unirse y la exactitud se
calcularía sobre doce filas sin que nada fallara.

Uso:
    python etapa2/evaluar_signo.py --predicciones datos_etapa2/predicciones.jsonl
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # El módulo compartido manda: si `texto.py` cambia la normalización, esto la
    # sigue. El respaldo es literalmente el cuerpo que fija el contrato (§1.1)
    # para poder correr esta etapa antes de que aterrice `texto.py`; si los dos
    # divergieran, la unión con la auditoría dejaría de encontrar oraciones y el
    # guardián de 80/93 lo delataría en la misma corrida.
    from texto import normalizar_espacios
except ImportError:                                        # pragma: no cover
    def normalizar_espacios(s):
        return " ".join(s.split())

# El lector de `operones_pao1.tsv` y el segmentador de nombres de operón viven
# en evaluar_oro.py y se importan en vez de copiarse. Dos copias de la misma
# regla derivan, y §1 del contrato existe justamente porque eso ya pasó: si el
# segmentador de este archivo dejara de coincidir con el del otro, las mismas
# oraciones se unirían en una etapa y no en la otra. Importar no abre ningún
# archivo: las rutas del patrón de oro son valores por omisión de su argparse.
from evaluar_oro import (cargar_operones, miembros_operon,
                         binomial_cola_superior,
                         revisar_probabilidades_de_fila)


COLUMNAS_AUDITORIA = ["pmid", "fuente", "tf", "blanco", "signo_correcto",
                      "evaluable", "redaccion", "mencion_tf", "mencion_blanco",
                      "oracion"]
FILAS_AUDITORIA = 198

# Las 12 primeras son las de §7, en su orden. `equivalencia_blanco` es
# añadida: sin ella no se puede saber, leyendo el TSV, si la fila se unió por
# el nombre que la auditoría escribió o por un miembro de su operón, y esa es
# la diferencia entre 76 y 84 oraciones unidas.
COLUMNAS_SALIDA = ["pmid", "tf", "blanco", "signo_correcto", "redaccion",
                   "metodo_union", "prediccion", "p_prediccion", "p_represses",
                   "pasa_umbral", "acierto", "tipo_error",
                   "equivalencia_blanco"]

# El orden del checkpoint del servidor (config.json y label_mapping.json). Es
# el mismo que fija red.py, y test_evaluar.py comprueba que los dos coinciden:
# hay TRES órdenes distintos en el árbol del asesor y uno intercambia
# `represses` con `no_relation`.
ETIQUETAS = ("activates", "no_relation", "regulates", "represses")
CON_SIGNO = ("activates", "represses")

# Medidos sobre etapa2/auditoria_signo.tsv. Si cambian, la tabla cambió y hay
# que mirarla antes de leer ninguna métrica.
EVALUABLES = 93
MINIMO_UNIDAS = 80

# El mismo alfa que evaluar_oro.py. La comparación es contra la tasa con la
# que el modelo contesta la clase correcta FUERA de las filas evaluadas.
ALFA = 0.05

LINEA_SIN_INFORMACION_QUE_ES = (
    "Las 93 oraciones evaluables son todas de la misma clase (`represses`), "
    "así que una exactitud alta no dice nada por sí sola: contestar siempre "
    "`represses` las acierta las 93. La línea base es la frecuencia con la "
    "que el modelo contesta esa clase en el RESTO del archivo de "
    "predicciones, que es lo que acertaría un clasificador que no lee la "
    "oración. El contraste es una binomial exacta de una cola."
)

LINEA_SIN_INFORMACION_CAVEAT = (
    "La tasa se estima sobre predicciones sin respuesta conocida, así que si "
    "el corpus de verdad está lleno de afirmaciones de represión, la tasa "
    "sube y la prueba se vuelve más exigente. El sesgo va en contra del "
    "pipeline, nunca a su favor, que es como tiene que ir un guardián."
)
POR_REDACCION = {"directa": 69, "fenotipo_mutante": 24}

PREFIJO_UNION = 120

ENCABEZADO = re.compile(r"^\s*#{1,6}\s+")


def bool_txt(v):
    return "true" if v else "false"


def limpiar_campo(s):
    return normalizar_espacios(str(s).replace("\t", " ").replace("\n", " "))


def leer_tsv(ruta, columnas, nombre):
    """Igual que en evaluar_oro.py: partir por tabulador, sin reglas de comillas."""
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s (%s)." % (ruta, nombre))
    with open(ruta, encoding="utf-8-sig") as f:
        crudas = f.read().split("\n")
    lineas = [ln for ln in crudas if ln.strip() and not ln.startswith("#")]
    if not lineas:
        sys.exit("%s está vacío (%s)." % (ruta, nombre))
    cabecera = lineas[0].rstrip("\r").split("\t")
    if cabecera != columnas:
        sys.exit("auditoria_signo.tsv no tiene la forma esperada.\n"
                 "  esperado: %s\n  leído:    %s"
                 % ("\t".join(columnas), "\t".join(cabecera)))
    filas = []
    for i, ln in enumerate(lineas[1:], start=2):
        campos = ln.rstrip("\r").split("\t")
        if len(campos) != len(cabecera):
            sys.exit("%s línea %d: %d columnas, se esperaban %d."
                     % (ruta, i, len(campos), len(cabecera)))
        filas.append(dict(zip(cabecera, campos)))
    return filas


def escribir_tsv(ruta, columnas, filas, comentario=None):
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if carpeta and not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        if comentario:
            for linea in comentario:
                f.write(("# %s" % limpiar_campo(linea)).rstrip() + "\n")
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(limpiar_campo(fila.get(c, ""))
                              for c in columnas) + "\n")
    os.replace(tmp, ruta)


def escribir_json(ruta, objeto):
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if carpeta and not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, ruta)


def tasa(n, d):
    return {"n": n, "d": d, "tasa": round(float(n) / d, 4) if d else None}


def clave_entidad(nombre):
    """Los nombres de entidad se comparan en minúsculas; las oraciones NO.

    `mexL` y `MexL` son el mismo gen escrito como gen y como proteína. Las
    oraciones sí se comparan sensibles a mayúsculas, como manda §7: ahí la
    mayúscula distingue el texto que el artículo publicó del que no.
    """
    return nombre.strip().lower()


def claves_blanco(nombre, operones):
    """(claves exactas, claves equivalentes) con las que buscar el blanco.

    §7 une por `(pmid, tf, blanco)` literal, y así no se puede unir nunca lo
    que hay que unir: 4 de los 6 represores de la auditoría tienen el blanco
    escrito con granularidad de operón (`mexAB-oprM`, `mexCD-oprJ`, `mexXY`,
    `mexJK`) mientras la oración del artículo nombra un gen suelto (`mexA`,
    `oprJ`, `mexX`, `mexJ`). Medido sobre el corpus completo: se unían 76 de
    93, el guardián de 80/93 saltaba y el script salía con código 1 sin
    escribir nada, o sea que la única medición de signo del proyecto no se
    podía calcular. Con la equivalencia suben a 84. §6.3 se la concede a
    `evaluar_oro.py` por esta misma razón.

    **Se expande el nombre que escribió la AUDITORÍA, nunca el que produjo el
    pipeline.** `auditoria_signo.tsv` es una tabla versionada de 198 filas
    escritas a mano, así que sus nombres no los puede fabricar nadie; el lado
    del pipeline sí, porque `lexico` acuña entidades sintéticas desde el texto
    (`lasRIAB`, `gacAS`), y expandirlo dejaría que un nombre inventado se una
    con lo que quiera.
    """
    exacta = set([clave_entidad(nombre)])
    equivalentes = set(operones.get(clave_entidad(nombre), []))
    equivalentes.update(clave_entidad(m) for m in miembros_operon(nombre))
    # El camino inverso: la auditoría nombra el gen y el pipeline el operón.
    for operon, miembros in operones.items():
        if clave_entidad(nombre) in miembros:
            equivalentes.add(operon)
    equivalentes -= exacta
    return exacta, equivalentes


def quitar_encabezado(oracion):
    """Quita el encabezado markdown pegado al principio de una oración.

    De las 93 oraciones evaluables, 9 empiezan con "## RESULTS ### THE
    MULTIDRUG EFFLUX PUMP REPRESSOR MEXL DIRECTLY ACTIVATES...". Las escribió
    `auditar_signo.py`, que no separaba el encabezado del primer párrafo. El
    pipeline nuevo sí lo descarta (§1.1: "el texto del encabezado se descarta,
    no se pega a la primera oración"), así que esas 9 nunca se unirían y se
    perderían por un desajuste de formato, no por un fallo del modelo.

    El encabezado va en mayúsculas en todo el corpus, así que termina en el
    primer token que trae una minúscula. Si el recorte deja menos de 40
    caracteres se devuelve la oración intacta: mejor no unir que unir mal.
    """
    if not ENCABEZADO.match(oracion):
        return oracion
    tokens = oracion.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("#") or not any(c.islower() for c in tok):
            i += 1
            continue
        break
    resto = " ".join(tokens[i:])
    return resto if len(resto) >= 40 else oracion


def cargar_auditoria(ruta):
    filas = leer_tsv(ruta, COLUMNAS_AUDITORIA, "auditoría de signo")
    if len(filas) != FILAS_AUDITORIA:
        sys.exit("auditoria_signo.tsv no tiene la forma esperada "
                 "(198 filas, 10 columnas); leí %d filas." % len(filas))
    return filas


def ruta_meta(ruta_predicciones):
    """predicciones.jsonl -> predicciones_meta.json, junto a las predicciones."""
    base = os.path.splitext(ruta_predicciones)[0]
    propio = base + "_meta.json"
    if os.path.exists(propio):
        return propio
    canonico = os.path.join(os.path.dirname(ruta_predicciones) or ".",
                            "predicciones_meta.json")
    return canonico if os.path.exists(canonico) else propio


def cargar_meta(ruta_predicciones):
    """Comprueba en qué orden se leyeron los logits. Sin eso no hay medición.

    `red.py` ya se niega a construir la red si el meta declara otro orden, pero
    §8 cuelga este archivo directamente de `clasificar.py`, sin pasar por
    `red.py`: esta rama del grafo no tenía ningún guardián del orden de las
    etiquetas. El síntoma es el peor posible aquí. Si `clasificar.py` corriera
    con el orden de `LABELS_DEFAULT` --que intercambia `represses` con
    `no_relation`-- este script publicaría tan campante una tasa de
    `signo_invertido`, o 93 de 93 `perdida_a_no_relation`, y las dos se leen
    como un fallo del modelo cuando son un fallo de carga. Y es la única
    medición de signo a nivel de oración que existe en el proyecto.

    La comprobación es la misma de `red.py` y está escrita dos veces a
    sabiendas: `red.py` es un script hermano, no una biblioteca, y §8 los pone
    en ramas distintas del grafo. `test_evaluar.py` compara las dos listas de
    etiquetas para que no puedan divergir.
    """
    ruta = ruta_meta(ruta_predicciones)
    if not os.path.exists(ruta):
        sys.exit("No encuentro el meta de la inferencia. Sin él no sé en qué "
                 "orden se leyeron los logits, y leerlos con el orden "
                 "equivocado reporta la represión como 'sin relación' sin que "
                 "nada falle. Buscaba %s." % ruta)
    with open(ruta, encoding="utf-8") as f:
        try:
            meta = json.load(f)
        except ValueError as e:
            sys.exit("%s ilegible: %s" % (ruta, e))
    id2label = meta.get("id2label")
    if not isinstance(id2label, dict):
        sys.exit("El meta dice que los logits se leyeron con el orden %r. Las "
                 "predicciones no son de fiar." % (id2label,))
    try:
        orden = [id2label[k] for k in sorted(id2label, key=lambda x: int(x))]
    except (TypeError, ValueError):
        orden = list(id2label.values())
    if orden != list(ETIQUETAS):
        sys.exit("El meta dice que los logits se leyeron con el orden %r, y el "
                 "checkpoint del entrenamiento usa %r. Las predicciones no son "
                 "de fiar: con ese orden la represión se lee como otra clase y "
                 "la tasa de error de signo que publicaría este archivo sería "
                 "un fallo de carga disfrazado de fallo del modelo."
                 % (orden, list(ETIQUETAS)))
    return meta, ruta


def cargar_predicciones(ruta, pmids):
    """(filas de los artículos de la auditoría, reparto de clases del archivo).

    El reparto de TODO el archivo no es adorno: es la línea base sin
    información de `linea_base_sin_informacion()`. Y de paso se comprueba fila
    por fila la invariante de §4, que vivía solo en clasificar.py: las cuatro
    probabilidades suman 1 y `prediccion` es de verdad la de mayor
    probabilidad.
    """
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s. Corre antes etapa2/clasificar.py." % ruta)
    filas, reparto, total = [], collections.Counter(), 0
    with open(ruta, encoding="utf-8") as f:
        for i, linea in enumerate(f, start=1):
            linea = linea.strip()
            if not linea:
                continue
            d = json.loads(linea)
            revisar_probabilidades_de_fila(d, ruta, i)
            reparto[d.get("prediccion")] += 1
            total += 1
            if str(d.get("pmid")) in pmids:
                filas.append(d)
    return filas, reparto, total


def cargar_oraciones(ruta, pmids):
    """id_par -> oracion_cruda, desde pares.jsonl.

    Añadido al contrato por necesidad: §7 define la unión por igualdad de la
    oración, pero `predicciones.jsonl` (§4) no lleva ningún campo de texto. El
    único sitio donde vive `oracion_cruda` es `pares.jsonl`, y se une por
    `id_par`, que el contrato define justo como "clave de unión con la etapa 3".
    """
    if not ruta or not os.path.exists(ruta):
        return {}
    mapa = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            d = json.loads(linea)
            if str(d.get("pmid")) in pmids:
                mapa[d["id_par"]] = d.get("oracion_cruda", "")
    return mapa


def indexar(predicciones, oraciones):
    """(pmid, tf, blanco) -> [(oracion, prediccion), ...] en orden de archivo."""
    indice = collections.defaultdict(list)
    for d in predicciones:
        oracion = d.get("oracion_cruda") or oraciones.get(d.get("id_par"), "")
        llave = (str(d["pmid"]), clave_entidad(d["tf"]),
                 clave_entidad(d["target"]))
        indice[llave].append((normalizar_espacios(oracion), d))
    return indice


def unir(fila, indice, por_articulo, operones):
    """Une una fila de la auditoría con una predicción.

    Devuelve (prediccion, metodo_union, quito_encabezado, equivalencia,
    diagnostico). Primero se agota el nombre exacto del blanco y solo después
    los equivalentes por operón, para que `equivalencia_blanco` diga la verdad
    en la fila que se pudo unir de las dos formas.
    """
    esperada = normalizar_espacios(fila["oracion"])
    sin_encabezado = normalizar_espacios(quitar_encabezado(fila["oracion"]))
    ktf = clave_entidad(fila["tf"])
    exactas, equivalentes = claves_blanco(fila["blanco"], operones)

    hubo_par = False
    for equivalencia, blancos in (("exacta", sorted(exactas)),
                                  ("por_operon", sorted(equivalentes))):
        candidatas = []
        for kbl in blancos:
            candidatas.extend(indice.get((fila["pmid"], ktf, kbl), []))
        if not candidatas:
            continue
        hubo_par = True
        for quitado, texto in ((False, esperada), (True, sin_encabezado)):
            if quitado and texto == esperada:
                break
            for oracion, d in candidatas:
                if oracion == texto:
                    return d, "exacta", quitado, equivalencia, ""
            corte = texto[:PREFIJO_UNION]
            for oracion, d in candidatas:
                if corte and oracion[:PREFIJO_UNION] == corte:
                    return d, "prefijo", quitado, equivalencia, ""

    # Diagnóstico: sin él, un guardián que salta solo dice "no se unieron", y
    # la diferencia entre "el segmentador partió la oración" y "el blanco
    # resolvió a otro nombre" son dos arreglos distintos.
    diagnostico = "sin_pareja"
    if not hubo_par:
        mismos = por_articulo.get(fila["pmid"], [])
        if not mismos:
            diagnostico = "articulo_sin_predicciones"
        else:
            diagnostico = "par_distinto"
    return None, "ninguna", False, "", diagnostico


# §7 define `sin_candidato` como "extraer_pares nunca generó esa oración", y
# eso solo es cierto cuando el par sí se generó y lo que falta es la oración.
# Devolver `sin_candidato` para las otras dos causas manda a arreglar el
# segmentador cuando el defecto está en el diccionario: medido, 2 de las 17 no
# unidas de una corrida real eran `par_distinto` y salían etiquetadas
# `sin_candidato`. El enum del contrato no tiene valor para esas dos causas,
# así que se extiende con los dos nombres que el propio JSON ya usaba en
# `diagnostico_de_las_no_unidas`; extender un enum es preferible a que una
# columna diga algo que no es cierto.
ERROR_POR_DIAGNOSTICO = {
    "sin_pareja": "sin_candidato",
    "par_distinto": "par_distinto",
    "articulo_sin_predicciones": "articulo_sin_predicciones",
}


def clasificar_error(signo_correcto, prediccion, pasa_umbral, diagnostico=""):
    """El enum de §7, más las dos causas de no unión que §7 no distingue."""
    if prediccion is None:
        return ERROR_POR_DIAGNOSTICO.get(diagnostico, "sin_candidato")
    if prediccion == signo_correcto:
        return "" if pasa_umbral else "bajo_umbral"
    if prediccion in CON_SIGNO and signo_correcto in CON_SIGNO:
        return "signo_invertido"
    if prediccion == "no_relation":
        return "perdida_a_no_relation"
    if prediccion == "regulates":
        return "perdida_a_regulates"
    return "otro"


def evaluar(auditoria, indice, umbrales, operones):
    por_articulo = collections.defaultdict(list)
    for (pmid, _, _), items in indice.items():
        por_articulo[pmid].extend(items)

    filas, diagnosticos, quitados = [], collections.Counter(), 0
    equivalencias = collections.Counter()
    for fila in auditoria:
        if fila["evaluable"] != "true" or not fila["signo_correcto"]:
            continue
        d, metodo, quitado, equivalencia, diagnostico = unir(
            fila, indice, por_articulo, operones)
        quitados += 1 if quitado else 0
        if equivalencia:
            equivalencias[equivalencia] += 1
        if diagnostico:
            diagnosticos[diagnostico] += 1

        if d is None:
            prediccion, p_pred, p_rep, pasa = None, "", "", False
        else:
            prediccion = d["prediccion"]
            if prediccion not in ETIQUETAS:
                sys.exit("La predicción del par %s dice %r, que no es una de "
                         "las cuatro etiquetas. Revisa id2label del checkpoint "
                         "(sección 4 del contrato): leer los logits con otro "
                         "orden "
                         "reporta represión como 'sin relación'."
                         % (d.get("id_par", "?"), prediccion))
            p_pred = float(d.get("p_%s" % prediccion, 0.0))
            p_rep = float(d.get("p_represses", 0.0))
            pasa = prediccion in umbrales and p_pred >= umbrales[prediccion]

        tipo = clasificar_error(fila["signo_correcto"], prediccion, pasa,
                                diagnostico)
        filas.append({
            "pmid": fila["pmid"],
            "tf": fila["tf"],
            "blanco": fila["blanco"],
            "signo_correcto": fila["signo_correcto"],
            "redaccion": fila["redaccion"],
            "metodo_union": metodo,
            "prediccion": prediccion or "",
            "p_prediccion": "" if d is None else "%.4f" % p_pred,
            "p_represses": "" if d is None else "%.4f" % p_rep,
            "pasa_umbral": bool_txt(pasa),
            "acierto": bool_txt(prediccion == fila["signo_correcto"] and pasa),
            "tipo_error": tipo,
            "equivalencia_blanco": equivalencia,
            "_unida": d is not None,
            "_id_par": "" if d is None else d.get("id_par", ""),
            "_clase_ok": prediccion == fila["signo_correcto"],
            "_acierto": prediccion == fila["signo_correcto"] and pasa,
            "_oracion": fila["oracion"],
            "_diagnostico": diagnostico,
        })
    return filas, diagnosticos, quitados, equivalencias


def bloque(filas):
    """Las dos exactitudes, siempre juntas y siempre etiquetadas.

    `exactitud` es sobre la clase de mayor probabilidad, que es lo que mide al
    modelo. `exactitud_con_umbral` exige además pasar el umbral de `red.py`,
    que es lo que de verdad llega a la red. Publicar una sola de las dos deja
    sin saber si el problema es el clasificador o la política de corte.
    """
    n = len(filas)
    return collections.OrderedDict([
        ("n", n),
        ("unidas", tasa(sum(1 for f in filas if f["_unida"]), n)),
        ("exactitud", tasa(sum(1 for f in filas if f["_clase_ok"]), n)),
        ("exactitud_con_umbral", tasa(sum(1 for f in filas if f["_acierto"]), n)),
        ("predicciones", dict(collections.Counter(
            f["prediccion"] or "(sin unión)" for f in filas))),
        ("tipo_error", dict(collections.Counter(
            f["tipo_error"] or "(acierto)" for f in filas))),
    ])


def linea_base_sin_informacion(filas, reparto, total):
    """Lo que acierta un clasificador que no lee la oración.

    Defecto que corrige: este archivo publicaba EXACTITUD 0.0 % (0 de 93) con
    un clasificador constante y salía con código 0, mientras evaluar_oro.py
    decía 69.8 % «distinto del azar» sobre las mismas predicciones. Ahora la
    exactitud se contrasta contra la tasa con la que el modelo contesta la
    clase correcta FUERA de estas filas: el constante que dice siempre
    `represses` la tiene en 1.0 y no despega, y el que dice siempre
    `activates` la tiene en 0.0 pero tampoco acierta ninguna.

    Las filas evaluadas se descuentan del reparto para que la tasa base no se
    estime en parte sobre las respuestas que está juzgando.
    """
    unidas = [f for f in filas if f["_unida"]]
    # Por id_par y no por fila de la auditoria: dos oraciones auditadas pueden
    # unirse a la misma prediccion, y restarla dos veces dejaria el reparto de
    # fuera en negativo, o sea la tasa base mal estimada a favor del pipeline.
    propias = {}
    for f in unidas:
        propias[f["_id_par"]] = f["prediccion"]
    fuera = collections.Counter(reparto)
    fuera.subtract(collections.Counter(propias.values()))
    n_fuera = max(0, total - len(propias))
    aciertos = sum(1 for f in unidas if f["_clase_ok"])
    clases = sorted(set(f["signo_correcto"] for f in unidas))
    if n_fuera > 0 and unidas:
        # Media de la tasa de la clase correcta de cada fila. Con una sola
        # clase --que es el caso de la auditoría-- es exactamente la tasa de
        # esa clase, y la binomial es exacta.
        tasa_base = sum(max(0, fuera[f["signo_correcto"]])
                        for f in unidas) / float(len(unidas) * n_fuera)
        real = float(aciertos) / len(unidas)
        p_valor = binomial_cola_superior(aciertos, len(unidas), tasa_base)
        ventaja = 100.0 * (real - tasa_base)
    else:
        tasa_base = real = p_valor = ventaja = None
    return collections.OrderedDict([
        ("que_es", LINEA_SIN_INFORMACION_QUE_ES),
        ("caveat", LINEA_SIN_INFORMACION_CAVEAT),
        ("clases_evaluadas", clases),
        ("filas_unidas", len(unidas)),
        ("aciertos_de_clase", aciertos),
        ("predicciones_fuera_de_la_auditoria", n_fuera),
        ("reparto_fuera_de_la_auditoria",
         collections.OrderedDict((k or "(sin etiqueta)", v)
                                 for k, v in sorted(fuera.items()) if v > 0)),
        ("tasa_base", None if tasa_base is None else round(tasa_base, 4)),
        ("real", None if real is None else round(real, 4)),
        ("ventaja_puntos", None if ventaja is None else round(ventaja, 1)),
        ("p_valor", None if p_valor is None else round(p_valor, 4)),
        ("prueba", "binomial exacta de una cola, P(X >= aciertos_de_clase) "
                   "con X ~ Binomial(filas_unidas, tasa_base)"),
    ])


def comparar_umbrales(ruta, umbrales):
    """Aviso, no salida con 1: evaluar con otros umbrales es legítimo."""
    if not ruta or not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            informe = json.load(f)
    except ValueError:
        return "%s no es JSON válido." % ruta
    de_la_red = informe.get("umbrales") or {}
    distintos = []
    for clase, valor in sorted(umbrales.items()):
        suyo = de_la_red.get(clase, de_la_red.get("umbral_%s" % clase))
        if suyo is not None and abs(float(suyo) - valor) > 1e-9:
            distintos.append("%s %s vs %s" % (clase, suyo, valor))
    if distintos:
        return ("La red se construyó con otros umbrales (%s). Los números de "
                "este informe no describen las aristas de red.tsv."
                % "; ".join(distintos))
    return None


def envolver(texto, ancho=76):
    lineas, actual = [], ""
    for palabra in texto.split():
        if actual and len(actual) + 1 + len(palabra) > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = (actual + " " + palabra).strip()
    if actual:
        lineas.append(actual)
    return lineas


def porcentaje(v):
    return "  n/d" if v["tasa"] is None else "%5.1f%%" % (100 * v["tasa"])


def construir_parser():
    p = argparse.ArgumentParser(
        description="Acierto de signo oración por oración sobre las 93 "
                    "oraciones evaluables de la auditoría.")
    p.add_argument("--predicciones", default="datos_etapa2/predicciones.jsonl")
    p.add_argument("--pares", default="datos_etapa2/pares.jsonl",
                   help="de aquí sale oracion_cruda; predicciones.jsonl no "
                        "lleva texto y la unión es por oración")
    p.add_argument("--auditoria", default="etapa2/auditoria_signo.tsv")
    p.add_argument("--operones", default="etapa2/operones_pao1.tsv",
                   help="para la equivalencia operon-gen del blanco auditado: "
                        "4 de los 6 represores lo tienen escrito como operon "
                        "y la oracion nombra un gen suelto")
    p.add_argument("--salida", default="datos_etapa2/evaluacion_signo.tsv")
    p.add_argument("--resumen", default="datos_etapa2/evaluacion_signo.json")
    p.add_argument("--red-informe", default="datos_etapa2/red_informe.json",
                   help="solo para avisar si los umbrales no son los de la red")
    p.add_argument("--umbral-activates", type=float, default=0.65)
    p.add_argument("--umbral-represses", type=float, default=0.70)
    p.add_argument("--umbral-regulates", type=float, default=0.60)
    return p


def main(argv=None):
    args = construir_parser().parse_args(argv)
    umbrales = {"activates": args.umbral_activates,
                "represses": args.umbral_represses,
                "regulates": args.umbral_regulates}

    auditoria = cargar_auditoria(args.auditoria)
    evaluables = [f for f in auditoria
                  if f["evaluable"] == "true" and f["signo_correcto"]]
    pmids = set(f["pmid"] for f in auditoria)

    avisos = []
    if len(evaluables) != EVALUABLES:
        avisos.append("La auditoría trae %d oraciones evaluables, no %d. Los "
                      "desgloses documentados (69 directas, 24 desde el "
                      "fenotipo del mutante) ya no describen esta tabla."
                      % (len(evaluables), EVALUABLES))
    conteo_redaccion = collections.Counter(f["redaccion"] for f in evaluables)
    for redaccion, esperado in sorted(POR_REDACCION.items()):
        if conteo_redaccion.get(redaccion, 0) != esperado:
            avisos.append("Esperaba %d oraciones con redacción %s y hay %d."
                          % (esperado, redaccion,
                             conteo_redaccion.get(redaccion, 0)))

    # Antes de leer una sola predicción: en qué orden se leyeron los logits.
    # La existencia del archivo se comprueba aquí y no dentro de cargar_meta()
    # para que "no corriste clasificar.py" no salga disfrazado de "falta el
    # meta", que manda a buscar otra cosa.
    if not os.path.exists(args.predicciones):
        sys.exit("No encuentro %s. Corre antes etapa2/clasificar.py."
                 % args.predicciones)
    meta, ruta_del_meta = cargar_meta(args.predicciones)
    operones, hay_tabla_operones = cargar_operones(args.operones)
    if not hay_tabla_operones:
        avisos.append(
            "No hay tabla de operones (%s), así que la equivalencia "
            "operón-gen del blanco auditado se resolvió solo con la expansión "
            "mecánica del nombre que escribió la auditoría (mexAB-oprM -> "
            "mexA, mexB, oprM). Corre etapa2/construir_diccionario.py."
            % args.operones)

    predicciones, reparto_global, n_predicciones = cargar_predicciones(
        args.predicciones, pmids)
    oraciones = cargar_oraciones(args.pares, pmids)
    # Sin texto no hay unión posible, y el guardián de 80/93 diría "el
    # segmentador no reproduce las oraciones" cuando lo que falta es el
    # archivo. Dos causas muy distintas con el mismo síntoma.
    if not oraciones and not any(d.get("oracion_cruda") for d in predicciones):
        sys.exit("No encuentro las oraciones. La unión con la auditoría es por "
                 "texto y predicciones.jsonl no lleva ninguno: pasa "
                 "--pares con el pares.jsonl de la corrida (falta %s)."
                 % args.pares)
    indice = indexar(predicciones, oraciones)
    filas, diagnosticos, quitados, equivalencias = evaluar(
        auditoria, indice, umbrales, operones)

    unidas = sum(1 for f in filas if f["_unida"])
    if unidas < MINIMO_UNIDAS:
        sys.exit(
            "Solo %d de %d oraciones de la auditoría se unieron con una "
            "predicción. El generador de pares no está reproduciendo esas "
            "oraciones, así que la exactitud de signo mediría otra cosa. Revisa "
            "texto.oraciones() y el diccionario antes de leer ningún número.\n"
            "  Motivos: %s%s"
            % (unidas, len(filas),
               ", ".join("%s=%d" % kv for kv in sorted(diagnosticos.items()))
               or "ninguno registrado",
               "" if hay_tabla_operones else
               "\n  Y no hay tabla de operones: 4 de los 6 represores tienen "
               "el blanco escrito como operón (mexAB-oprM, mexCD-oprJ, mexXY, "
               "mexJK) y sin ella solo se unen por el nombre exacto."))

    aviso_umbrales = comparar_umbrales(args.red_informe, umbrales)
    if aviso_umbrales:
        avisos.append(aviso_umbrales)

    sin_candidato = [f for f in filas if not f["_unida"]]

    resumen = collections.OrderedDict()
    resumen["generado"] = datetime.datetime.now().replace(
        microsecond=0).isoformat()
    resumen["entradas"] = collections.OrderedDict([
        ("predicciones", args.predicciones),
        ("predicciones_leidas", len(predicciones)),
        ("pares", args.pares),
        ("auditoria", args.auditoria),
        ("operones", args.operones if hay_tabla_operones else ""),
        ("meta", ruta_del_meta),
        ("id2label", meta.get("id2label")),
        ("modelo", meta.get("modelo")),
        ("do_lower_case", meta.get("do_lower_case")),
    ])
    resumen["umbrales"] = umbrales
    resumen["avisos"] = avisos
    resumen["global"] = bloque(filas)
    base = linea_base_sin_informacion(filas, reparto_global, n_predicciones)
    certifica = base["p_valor"] is not None and base["p_valor"] <= ALFA
    resumen["linea_base_sin_informacion"] = base
    resumen["veredicto"] = collections.OrderedDict([
        ("exactitud", resumen["global"]["exactitud"]),
        ("tasa_base", base["tasa_base"]),
        ("p_valor", base["p_valor"]),
        ("alfa", ALFA),
        ("despega", certifica),
        ("codigo_de_salida", 0 if certifica else 2),
        ("que_significa_el_codigo_de_salida",
         "0 = la exactitud de clase despega de la tasa con la que el modelo "
         "contesta esa misma clase fuera de estas filas (p_valor <= %s). "
         "2 = no despega, o no hay predicciones fuera de la auditoria con que "
         "estimar esa tasa, y entonces la cifra no es un resultado: las 93 "
         "son todas de la misma clase y contestar siempre `represses` las "
         "acierta todas. Los dos archivos se escriben en los dos casos, para "
         "poder diagnosticar. El codigo 1 sigue significando 'la entrada no "
         "sirve y no escribo nada'. Sin esto, este archivo salia con codigo 0 "
         "publicando EXACTITUD 0.0 %% de 93, mientras evaluar_oro.py decia "
         "69.8 %% y «se distingue del azar» sobre las mismas predicciones."
         % ALFA),
    ])
    resumen["por_redaccion"] = collections.OrderedDict(
        (r, bloque([f for f in filas if f["redaccion"] == r]))
        for r in sorted(set(f["redaccion"] for f in filas)))
    resumen["la_trampa"] = collections.OrderedDict([
        ("que_es", "Las oraciones escritas desde el fenotipo del mutante "
                   "(\"mutations in nfxB lead to overexpression of "
                   "MexCD-OprJ\") dicen el signo al revés. Un extractor que "
                   "falle SOLO aquí necesita una regla de inversión "
                   "(--invertir-fenotipo en red.py, sección 5.2); uno que "
                   "falle "
                   "también en las directas está mal cargado o mal entrenado. "
                   "Son arreglos opuestos, así que el número va aparte."),
        ("fenotipo_mutante", bloque(
            [f for f in filas if f["redaccion"] == "fenotipo_mutante"])),
        ("directa", bloque([f for f in filas if f["redaccion"] == "directa"])),
    ])
    resumen["union"] = collections.OrderedDict([
        ("metodo", dict(collections.Counter(f["metodo_union"] for f in filas))),
        ("equivalencia_del_blanco", dict(equivalencias)),
        ("nota_equivalencia",
         "`por_operon` son las filas que se unieron porque el blanco de la "
         "auditoría es un operón (mexAB-oprM) y el pipeline nombró uno de sus "
         "genes (mexA). Sin esa equivalencia se unían 76 de 93 y el guardián "
         "de 80/93 abortaba la única medición de signo del proyecto. Se "
         "expande el nombre que escribió la auditoría, nunca el que produjo el "
         "pipeline."),
        ("tras_quitar_encabezado", quitados),
        ("diagnostico_de_las_no_unidas", dict(diagnosticos)),
        ("nota", "9 de las 93 oraciones traen pegado el encabezado markdown "
                 "(\"## RESULTS ### ...\") porque auditar_signo.py no lo "
                 "separaba. texto.secciones() sí lo descarta, así que para "
                 "unirlas se recorta el encabezado de la oración de la "
                 "auditoría. Sin ese recorte se perderían por formato, no por "
                 "el modelo."),
    ])
    resumen["no_unidas"] = collections.OrderedDict([
        ("n", len(sin_candidato)),
        ("aviso", "Ninguna es un fallo del modelo, pero no todas son el mismo "
                  "fallo: `sin_candidato` es del segmentador (el par existe y "
                  "la oración no), `par_distinto` es del diccionario (el "
                  "artículo dio predicciones, pero con otro nombre canónico) y "
                  "`articulo_sin_predicciones` es de más arriba todavía. El "
                  "TSV lo dice fila por fila en tipo_error."),
        ("por_causa", dict(collections.Counter(
            f["tipo_error"] for f in sin_candidato))),
        ("filas", [{"pmid": f["pmid"], "tf": f["tf"], "blanco": f["blanco"],
                    "redaccion": f["redaccion"], "causa": f["tipo_error"],
                    "oracion": f["_oracion"][:120]} for f in sin_candidato]),
    ])

    # Las 105 co-menciones sin relación afirmada no tienen respuesta conocida,
    # así que no entran en ninguna exactitud. Sí valen como negativas realistas:
    # cuántas veces el modelo afirma una relación donde la auditoría no ve
    # ninguna afirmada.
    no_evaluables = [f for f in auditoria
                     if f["evaluable"] != "true" or not f["signo_correcto"]]
    conteo_no_ev = collections.Counter()
    for fila in no_evaluables:
        d, _, _, _, _ = unir(fila, indice, collections.defaultdict(list),
                             operones)
        conteo_no_ev[d["prediccion"] if d else "(sin unión)"] += 1
    resumen["no_evaluables"] = collections.OrderedDict([
        ("n", len(no_evaluables)),
        ("aviso", "Co-menciones sin relación afirmada: no tienen respuesta "
                  "conocida y no entran en ninguna exactitud. Se cuentan "
                  "porque son negativas realistas del mismo dominio."),
        ("predicciones", dict(conteo_no_ev)),
    ])

    comentario = envolver(
        "Acierto de signo sobre las %d oraciones evaluables de "
        "auditoria_signo.tsv. Las %d escritas desde el fenotipo del mutante "
        "van desglosadas aparte en el JSON: dicen el signo al revés y son otro "
        "problema. Las %d co-menciones sin relación afirmada no aparecen aquí "
        "porque no tienen respuesta conocida."
        % (len(filas), conteo_redaccion.get("fenotipo_mutante", 0),
           len(no_evaluables)))
    for fila in filas:
        for k in [k for k in fila if k.startswith("_")]:
            del fila[k]
    escribir_tsv(args.salida, COLUMNAS_SALIDA, filas, comentario)
    escribir_json(args.resumen, resumen)

    g = resumen["global"]
    print("")
    print("=" * 78)
    # Caja mixta: cp437 (consola de Windows en inglés) no tiene Ó y el
    # print reventaría con UnicodeEncodeError en la máquina del compañero.
    print("Acierto de signo, oración por oración")
    print("=" * 78)
    print("  Oraciones evaluables      %d" % g["n"])
    print("  Unidas con una predicción %s (%d de %d)"
          % (porcentaje(g["unidas"]), g["unidas"]["n"], g["unidas"]["d"]))
    print("  EXACTITUD (clase)         %s (%d de %d)"
          % (porcentaje(g["exactitud"]), g["exactitud"]["n"],
             g["exactitud"]["d"]))
    print("  Exactitud con umbral      %s (%d de %d)"
          % (porcentaje(g["exactitud_con_umbral"]),
             g["exactitud_con_umbral"]["n"], g["exactitud_con_umbral"]["d"]))
    print("")
    print("  Contra la linea base sin informacion (la tasa de esa clase en el")
    print("  resto del archivo de predicciones, %d filas):"
          % base["predicciones_fuera_de_la_auditoria"])
    if base["p_valor"] is None:
        print("    no hay predicciones fuera de la auditoria: sin ellas no se")
        print("    puede saber si el modelo contesta asi solo aqui.")
    else:
        # El denominador va a la vista porque NO es el de la exactitud de
        # arriba: la comparacion solo puede correr sobre las filas unidas, y
        # las no unidas no son un fallo del modelo.
        print("    real %5.1f%% (%d de %d unidas)   sin informacion %5.1f%%   "
              "ventaja %+5.1f pp   p %.3f"
              % (100 * base["real"], base["aciertos_de_clase"],
                 base["filas_unidas"], 100 * base["tasa_base"],
                 base["ventaja_puntos"], base["p_valor"]))
    print("")
    print("  Todas las evaluables valen 'represses'. Reparto de lo predicho:")
    for etiqueta in list(ETIQUETAS) + ["(sin unión)"]:
        n = g["predicciones"].get(etiqueta, 0)
        if n:
            print("    %-14s %4d" % (etiqueta, n))
    print("")
    print("  Por redacción:")
    for redaccion in resumen["por_redaccion"]:
        b = resumen["por_redaccion"][redaccion]
        marca = "  <-- la trampa" if redaccion == "fenotipo_mutante" else ""
        print("    %-18s n=%3d  exactitud %s (%d/%d)%s"
              % (redaccion, b["n"], porcentaje(b["exactitud"]),
                 b["exactitud"]["n"], b["exactitud"]["d"], marca))
    print("")
    for linea in envolver(resumen["la_trampa"]["que_es"]):
        print("  " + linea)
    if equivalencias.get("por_operon"):
        print("")
        print("  %d de las %d se unieron por equivalencia de operon: la "
              "auditoria" % (equivalencias["por_operon"], len(filas)))
        print("  nombra el operon y el pipeline uno de sus genes.")
    if sin_candidato:
        print("")
        print("  No unidas (%d): fallo del segmentador o del diccionario, no "
              "del modelo." % len(sin_candidato))
        for causa, n in sorted(resumen["no_unidas"]["por_causa"].items()):
            print("    %-28s %3d" % (causa, n))
        # Se leen del resumen, que se armó antes de tirar los campos internos.
        for f in resumen["no_unidas"]["filas"][:10]:
            print("    %s %s->%s  %s  %s"
                  % (f["pmid"], f["tf"], f["blanco"], f["causa"],
                     f["oracion"][:50]))
    for aviso in avisos:
        print("")
        for linea in envolver("AVISO: " + aviso):
            print(linea)
    print("")
    print("Escrito %s" % args.salida)
    print("Escrito %s" % args.resumen)

    # El veredicto va al final, donde se lee, y decide el codigo de salida.
    print("")
    if certifica:
        print("La exactitud de signo sobre las %d unidas (%.1f %%) despega de "
              "la linea base" % (base["filas_unidas"], 100 * base["real"]))
        print("sin informacion (%.1f %%, p = %.3f). Codigo 0."
              % (100 * base["tasa_base"], base["p_valor"]))
        return 0
    if base["p_valor"] is None:
        for linea in envolver(
                "NO HAY RESULTADO: no hay ninguna prediccion fuera de las "
                "filas de la auditoria, asi que no se puede estimar con que "
                "frecuencia contesta el modelo esa clase cuando la oracion no "
                "afirma nada. Sin esa tasa, las 93 --que son todas de la "
                "misma clase-- las acierta enteras cualquier clasificador "
                "constante. Los dos archivos estan escritos. Codigo de salida "
                "2."):
            print(linea)
        return 2
    for linea in envolver(
            "NO HAY RESULTADO: la exactitud de signo sobre las %d unidas "
            "(%.1f %%) no se distingue de la tasa con la que este mismo "
            "modelo contesta esa clase fuera de la auditoria (%.1f %%, "
            "p = %.3f). Las %d oraciones evaluables son todas de la misma "
            "clase, asi que un clasificador constante saca ese numero sin "
            "leer nada. Los dos archivos estan escritos para poder "
            "diagnosticar. Codigo de salida 2."
            % (base["filas_unidas"], 100 * base["real"],
               100 * base["tasa_base"], base["p_valor"], g["n"])):
        print(linea)
    return 2


if __name__ == "__main__":
    sys.exit(main())
