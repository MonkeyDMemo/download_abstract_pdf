#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Etapa 4: de predicciones sueltas a la red de aristas unicas.

Entra un .jsonl con una prediccion por candidato (una oracion, un par) y sale
una arista por par (TF, blanco) con su signo, sus conteos y la tabla de
evidencias que la sostiene. No se vuelve a llamar al modelo: la politica de
umbrales vive aqui justamente para poder cambiarla sin gastar otra vez la hora
de CPU de la etapa 3.

Cuatro decisiones vienen del contrato y aqui solo se obedecen:

1. El orden es filtrar, DEDUPLICAR y despues topar por par. En
   auditar_signo.py el contador de evidencias subia antes de la dedup, asi que
   una oracion citada textualmente por tres articulos gastaba tres de los cupos
   del par y despues se colapsaba a una sola: los pares que topaban acababan
   con menos oraciones distintas de las que cabian, y las oraciones nuevas que
   se habian descartado por el camino ya no volvian.

2. El pmid NO entra en la clave de dedup. Lo que se quiere colapsar es
   justamente la misma oracion citada por varios articulos. Pero el numero de
   articulos distintos que la contenian se conserva en n_articulos: "afirmado
   en 7 articulos" es la senal de confianza mas barata que existe y
   auditar_signo.py la perdia al deduplicar.

3. Un par sobre el que la literatura se contradice no se resuelve por mayoria
   simple ni se descarta: se degrada a 'regulates'. Esa clase existe en el
   dominio precisamente para la relacion establecida sin signo resuelto.
   Resolver 3 contra 2 por mayoria simple fabricaria un signo que la evidencia
   no sostiene; descartarlo tiraria una arista que si existe. Los tres conteos
   se escriben siempre, asi que la decision es auditable fila por fila y un
   revisor puede aplicar otra regla sin recorrer el pipeline.

4. La autorregulacion se emite marcada en la etapa 2 y se excluye aqui, salvo
   --incluir-autorregulacion. Sin analisis sintactico no hay como distinguir
   "NalD reprime a nalD" de una oracion que nombra nalD dos veces, una de ellas
   como delecion.

Las cuatro probabilidades de cada prediccion se COMPRUEBAN aqui, no se creen.
La invariante ("suman 1.0 +/- 1e-3") vivia solo en `clasificar.py`, que es el
unico archivo del repositorio que necesita torch y por tanto el unico que no
corre en las maquinas del laboratorio: cualquier `predicciones.jsonl` editado
a mano, reanudado a medias o escrito por otro script entraba por esta puerta
sin pasar por aquella. Ver revisar_probabilidades().

La columna `confianza` tiene una sola definicion --media de la probabilidad de
la clase ganadora sobre las evidencias que votaron por ella-- y se deja VACIA
cuando no hay ninguna, que es el caso de la arista en conflicto degradada a
'regulates' sin un solo voto 'regulates'. Rellenarla con la media sobre toda
la evidencia contradictoria publicaba otro numero bajo la misma etiqueta: en
una corrida de prueba, las 74 aristas 'regulates' eran las 74 en conflicto.

El campo `redaccion` NO invierte el signo. 'fenotipo_mutante' es donde se
espera que el modelo lo invierta, pero voltearlo con una heuristica sin medir
antes cuanto se equivoca seria cambiar un error por otro sin saber cual es
mayor. Se propaga hasta la tabla de evidencias para que la etapa 6 mida la
exactitud partida por redaccion; si ese numero respalda la inversion, entonces
se agrega --invertir-fenotipo.

Los umbrales por omision (0.65 / 0.70 / 0.60) reproducen la corrida del asesor
y NO estan justificados: no habia conjunto de calibracion. Por eso son
argumentos, quedan escritos en el informe y el informe trae siempre un barrido
de sensibilidad, para que quien lea la red vea de inmediato cuanto depende del
valor elegido. Cambiar los valores por omision exige un conjunto de
calibracion que no sea ninguno de los dos conjuntos de evaluacion de las
etapas 5 y 6: calibrar ahi convierte la evaluacion en ajuste.

Solo biblioteca estandar.

Uso:
    python etapa2/red.py --predicciones datos_etapa2/predicciones.jsonl \
                         --pares datos_etapa2/pares.jsonl
"""

import argparse
import collections
import datetime
import json
import os
import sys

# El orden del checkpoint del servidor (config.json y label_mapping.json).
# Se fija aqui para poder rechazar un meta que diga otra cosa: hay TRES ordenes
# distintos en el arbol del asesor y uno de ellos intercambia 'represses' con
# 'no_relation', o sea que leer los logits con el orden equivocado reporta la
# represion como "sin relacion" sin que nada falle.
ETIQUETAS = ["activates", "no_relation", "regulates", "represses"]

# Las tres clases que si son una arista. 'regulates' es tambien el destino de
# los pares en conflicto, ver resolver_signo().
SIGNOS = ["activates", "represses", "regulates"]

UMBRALES_POR_OMISION = {"activates": 0.65, "represses": 0.70, "regulates": 0.60}

# Tolerancia de la suma de las cuatro probabilidades. Es la de la seccion 4
# del contrato, aplicada aqui --donde las predicciones se CONSUMEN-- y no solo
# en el script que las produce. Ver revisar_probabilidades().
TOLERANCIA_SUMA = 1e-3

# Margen del desempate del argmax. Las cuatro probabilidades se escriben
# redondeadas a 6 decimales, asi que la clase declarada puede quedar por
# debajo del maximo por hasta 5e-7 sin que nadie haya hecho nada mal.
TOLERANCIA_ARGMAX = 1e-6

COLUMNAS_RED = ["tf", "blanco", "signo", "conflicto", "n_evidencias",
                "n_activates", "n_represses", "n_regulates", "n_articulos",
                "confianza", "autorregulacion", "secciones", "pmids",
                "oracion_representativa"]

COLUMNAS_EVIDENCIAS = ["tf", "blanco", "id_par", "pmid", "seccion", "fuente",
                       "prediccion", "probabilidad", "redaccion", "oracion"]

CLAVES_PREDICCION = ("id_par", "pmid", "tf", "target", "prediccion",
                     "p_activates", "p_no_relation", "p_regulates",
                     "p_represses", "seccion", "fuente", "autorregulacion",
                     "redaccion")

CLAVES_PAR = ("id_par", "oracion_cruda", "n_oracion")

# Del modulo compartido, no una copia local: la clave de dedup de esta etapa y
# la union de la etapa 6 con las oraciones auditadas tienen que normalizar el
# espaciado igual. Si cada etapa escribe su propio normalizador, esa union
# empieza a fallar en silencio y la exactitud de signo pasa a medir otra cosa.
from grn_bronce.texto import normalizar_espacios

# Para dejar escrito con QUE archivos se construyo esta red, por contenido y no
# por ruta. La ruta es siempre la misma y el contenido cambia; sin la huella,
# la evaluacion no puede saber que le pusieron al lado un archivo de otra
# corrida. Ver el docstring de procedencia.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from grn_comun import procedencia


def como_bool(v):
    """Los booleanos llegan como booleanos JSON, pero un .jsonl reescrito a
    mano trae 'true'/'false' de cadena, y bool("false") es True."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1")
    return bool(v)


def texto_bool(v):
    return "true" if v else "false"


# ------------------------------------------------------------------ entrada

def leer_jsonl(ruta, obligatorias, que):
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for i, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                r = json.loads(linea)
            except ValueError as e:
                sys.exit("%s linea %d ilegible: %s" % (ruta, i, e))
            faltan = set(obligatorias) - set(r)
            if faltan:
                sys.exit("%s linea %d: a %s le faltan los campos %s"
                         % (ruta, i, que, sorted(faltan)))
            filas.append(r)
    return filas


def revisar_probabilidades(filas, ruta):
    """Las cuatro probabilidades SON una distribucion y `prediccion` ES su
    argmax. Se mide; no se toma de la etiqueta.

    Por que vive aqui y no solo en `clasificar.py`
    ----------------------------------------------
    La invariante de la seccion 4 ("alguna suma de las cuatro fuera de
    1.0 +/- 1e-3") esta escrita para el script que produce el archivo, que es
    el unico del repositorio que importa torch y por lo tanto el unico que no
    corre en las maquinas del laboratorio. Todo lo demas lee
    `predicciones.jsonl` y se lo cree. Medido: 65216 filas con
    p_activates = p_no_relation = p_regulates = p_represses = 0.99 --que suman
    3.96-- pasaban por aqui con codigo 0 y producian 9608 aristas, todas
    'activates' y todas con confianza 0.9900, en una columna que el contrato
    define como la media de una probabilidad. Ese archivo seguia hasta la
    etapa 5, que publicaba exhaustividad 95.1 % sin que nada fallara. `red.py`
    ya comprobaba el meta y el id2label del archivo que consume: lo que
    faltaba era comprobar su contenido.

    Tres comprobaciones, y ninguna mira una etiqueta:

    1. cada probabilidad esta en [0, 1]. La comparacion tambien descarta `nan`
       e `inf`, que `json.loads` acepta como `NaN` e `Infinity` y que despues
       hacen que toda comparacion con un umbral sea falsa --la fila se
       descarta como "bajo umbral" y el motivo real no aparece en ningun
       lado--.
    2. las cuatro suman 1.0 +/- TOLERANCIA_SUMA.
    3. `prediccion` es la clase de mayor probabilidad.

    La tercera no esta en la lista de invariantes de la seccion 5, pero es la
    definicion literal que la seccion 4 le da a esa columna ("la etiqueta de
    mayor probabilidad, tomada de id2label del checkpoint"). Sin ella la
    segunda se esquiva con una distribucion legitima y una etiqueta falsa:
    p_represses = 0.9 declarado 'activates' pasa el umbral de activacion con
    un numero que pertenece a la represion, y la arista sale con el signo
    cambiado y una confianza de 0.9.

    Devuelve la medicion --desviacion maxima de la suma, cuantas filas venian
    empatadas-- para que el informe publique la evidencia de que la
    comprobacion corrio, y no solo su ausencia de quejas.
    """
    problemas = []
    desviacion_maxima = 0.0
    empatadas = 0
    for i, r in enumerate(filas, 1):
        p = r["p"]
        fuera = [e for e in ETIQUETAS if not (0.0 <= p[e] <= 1.0)]
        if fuera:
            problemas.append("fila %d: %s no esta en [0, 1] (%s)"
                             % (i, ", ".join("p_" + e for e in fuera),
                                ", ".join("%r" % p[e] for e in fuera)))
            continue
        suma = sum(p[e] for e in ETIQUETAS)
        desviacion = abs(suma - 1.0)
        if desviacion > desviacion_maxima:
            desviacion_maxima = desviacion
        if desviacion > TOLERANCIA_SUMA:
            problemas.append("fila %d: las probabilidades no suman 1 (suman "
                             "%.6f)" % (i, suma))
            continue
        maxima = max(p[e] for e in ETIQUETAS)
        if p[r["prediccion"]] < maxima - TOLERANCIA_ARGMAX:
            ganadora = [e for e in ETIQUETAS if p[e] >= maxima
                        - TOLERANCIA_ARGMAX]
            problemas.append(
                "fila %d: dice '%s' (p = %.6f) pero la clase mas probable es "
                "'%s' (p = %.6f)" % (i, r["prediccion"], p[r["prediccion"]],
                                     ganadora[0], maxima))
            continue
        if sum(1 for e in ETIQUETAS if p[e] >= maxima - TOLERANCIA_ARGMAX) > 1:
            empatadas += 1
    if problemas:
        sys.exit(
            "%s: %d de %d filas no son una distribucion de probabilidad sobre "
            "las cuatro clases, o su etiqueta no es la clase mas probable "
            "(%s%s). Revisa el softmax de la etapa 3: sin esto la columna "
            "`confianza` de la red publica como probabilidad media el promedio "
            "de unos numeros que no son probabilidades, y la etapa 5 mide "
            "exhaustividad sobre esa red."
            % (ruta, len(problemas), len(filas), "; ".join(problemas[:5]),
               "; ..." if len(problemas) > 5 else ""))
    return collections.OrderedDict([
        ("filas", len(filas)),
        ("tolerancia_suma", TOLERANCIA_SUMA),
        ("desviacion_maxima_de_la_suma", round(desviacion_maxima, 9)),
        ("filas_con_la_clase_ganadora_empatada", empatadas),
    ])


def cargar_predicciones(ruta):
    """Devuelve (filas, medicion de revisar_probabilidades()).

    La comprobacion de las probabilidades se hace AQUI, dentro de la carga, y
    no en `main()`: es la unica forma de que un consumidor nuevo de este
    modulo no pueda leer el archivo sin mirar lo que trae dentro.
    """
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s. Corre antes etapa2/clasificar.py." % ruta)
    crudas = leer_jsonl(ruta, CLAVES_PREDICCION, "una prediccion")
    filas = []
    for i, r in enumerate(crudas, 1):
        if r["prediccion"] not in ETIQUETAS:
            sys.exit("Signo desconocido: %r. Revisa id2label del checkpoint."
                     % r["prediccion"])
        try:
            p = dict((e, float(r["p_" + e])) for e in ETIQUETAS)
            pmid = int(r["pmid"])
        except (TypeError, ValueError) as e:
            sys.exit("%s linea %d: %s" % (ruta, i, e))
        filas.append({
            "id_par": r["id_par"], "pmid": pmid,
            "tf": r["tf"], "blanco": r["target"],
            "prediccion": r["prediccion"], "p": p,
            "seccion": r["seccion"], "fuente": r["fuente"],
            "autorregulacion": como_bool(r["autorregulacion"]),
            "redaccion": r["redaccion"],
        })
    return filas, revisar_probabilidades(filas, ruta)


def cargar_pares(ruta):
    """El indice id_par -> (oracion normalizada, n_oracion).

    --pares no esta en la lista de argumentos de la seccion 5 del contrato,
    pero el procedimiento que esa misma seccion fija lo necesita: la clave de
    dedup lleva la oracion cruda y el orden del tope es
    (pmid, seccion, n_oracion), y ninguno de los dos campos viaja en
    predicciones.jsonl. Sin unir por id_par no se pueden escribir ni
    oracion_representativa ni la tabla de evidencias, que son columnas
    obligatorias de la salida.
    """
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s. red.py une por id_par para recuperar la "
                 "oracion y n_oracion, que no viajan en las predicciones. "
                 "Corre antes etapa2/extraer_pares.py." % ruta)
    indice = {}
    for r in leer_jsonl(ruta, CLAVES_PAR, "un candidato"):
        if r["id_par"] in indice:
            sys.exit("id_par repetido en %s: %s." % (ruta, r["id_par"]))
        indice[r["id_par"]] = (normalizar_espacios(r["oracion_cruda"]),
                               int(r["n_oracion"]))
    return indice


def ruta_meta(ruta_predicciones):
    """El meta se busca junto a las predicciones y con su mismo nombre.

    predicciones.jsonl -> predicciones_meta.json, que es justo el par de
    valores por omision del contrato. Si el archivo se llama de otro modo se
    prueba tambien el nombre canonico en la misma carpeta.
    """
    base = os.path.splitext(ruta_predicciones)[0]
    propio = base + "_meta.json"
    if os.path.exists(propio):
        return propio
    canonico = os.path.join(os.path.dirname(ruta_predicciones) or ".",
                            "predicciones_meta.json")
    return canonico if os.path.exists(canonico) else propio


def cargar_meta(ruta_predicciones):
    ruta = ruta_meta(ruta_predicciones)
    if not os.path.exists(ruta):
        sys.exit("No encuentro el meta de la inferencia. Sin el no se en que "
                 "orden se leyeron los logits. Buscaba %s." % ruta)
    with open(ruta, encoding="utf-8") as f:
        try:
            meta = json.load(f)
        except ValueError as e:
            sys.exit("%s ilegible: %s" % (ruta, e))
    id2label = meta.get("id2label")
    if not isinstance(id2label, dict):
        sys.exit("El meta dice que los logits se leyeron con el orden %r. "
                 "Las predicciones no son de fiar." % (id2label,))
    try:
        orden = [id2label[k] for k in sorted(id2label, key=lambda x: int(x))]
    except (TypeError, ValueError):
        orden = list(id2label.values())
    if orden != ETIQUETAS:
        sys.exit("El meta dice que los logits se leyeron con el orden %r. "
                 "Las predicciones no son de fiar." % (orden,))
    return meta, ruta


def leer_umbrales(ruta):
    """Lee los tres umbrales de un umbrales_sugeridos.json."""
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s." % ruta)
    with open(ruta, encoding="utf-8") as f:
        try:
            obj = json.load(f)
        except ValueError as e:
            sys.exit("%s ilegible: %s" % (ruta, e))
    if not isinstance(obj, dict):
        sys.exit("%s no es un objeto con un umbral por clase." % ruta)
    # Se acepta el objeto plano y el anidado bajo "umbrales": el contrato fija
    # que clasificar.py --calibrar escribe ese archivo, no su forma exacta.
    d = obj.get("umbrales", obj)
    faltan = set(SIGNOS) - set(d or {})
    if faltan:
        sys.exit("%s no trae umbral para %s." % (ruta, sorted(faltan)))
    try:
        umbrales = dict((c, float(d[c])) for c in SIGNOS)
    except (TypeError, ValueError):
        sys.exit("%s tiene umbrales que no son numeros." % ruta)
    return umbrales, obj.get("calibrado_en")


def unir_con_pares(filas, indice, ruta_pares, log=print):
    """Pega la oracion y n_oracion a cada prediccion. Sin ellas no hay dedup."""
    sin_par = [r["id_par"] for r in filas if r["id_par"] not in indice]
    if sin_par:
        sys.exit("Hay %d predicciones cuyo id_par no esta en %s (la primera es "
                 "%s). Las predicciones y los candidatos no son de la misma "
                 "corrida, asi que la union no seria fiable."
                 % (len(sin_par), ruta_pares, sin_par[0]))
    if len(indice) != len(filas):
        log("AVISO: %d candidatos y %d predicciones. La red se arma con las "
            "predicciones que hay." % (len(indice), len(filas)))
    for r in filas:
        r["oracion"], r["n_oracion"] = indice[r["id_par"]]
    return filas


# ------------------------------------------------------- pasos del contrato

def filtrar(filas, umbrales, sin_pies=False, sin_introduccion=False,
            incluir_autorregulacion=False, cuenta=None):
    """Pasos 1 y 2: seccion, autorregulacion, no_relation y umbral por clase.

    La autorregulacion se descarta aqui, junto con las secciones, porque es
    propiedad del candidato y no de la arista. En auditar_signo.py quedaba
    fuera por estructura de datos (ningun represor tenia como bomba su propio
    gen), no por un condicional: al generalizar a pares arbitrarios esa
    proteccion desaparece sola y hay que reponerla explicita. La invariante de
    verificar() es el guardian de que este filtro corrio.
    """
    if cuenta is None:
        cuenta = collections.Counter()
    vivas = []
    for r in filas:
        if sin_pies and r["seccion"] == "pie_de_figura":
            cuenta["seccion_pie_de_figura"] += 1
            continue
        if sin_introduccion and r["seccion"] == "introduction":
            cuenta["seccion_introduction"] += 1
            continue
        if r["autorregulacion"] and not incluir_autorregulacion:
            cuenta["autorregulacion"] += 1
            continue
        if r["prediccion"] == "no_relation":
            cuenta["no_relation"] += 1
            continue
        # "Alcanzar" el umbral incluye la igualdad.
        if r["p"][r["prediccion"]] < umbrales[r["prediccion"]]:
            cuenta["bajo_umbral_" + r["prediccion"]] += 1
            continue
        vivas.append(r)
    return vivas


def deduplicar(filas):
    """Paso 3: una evidencia por (tf, blanco, oracion), sin el pmid en la clave.

    Cada evidencia se queda con la lista de PMIDs distintos que contenian esa
    oracion; ese es el conteo que alimenta n_articulos y el que se perdia al
    deduplicar sin guardarlo.

    El representante del grupo es la fila con mayor probabilidad de su clase
    predicha; los empates se rompen por (pmid, seccion, n_oracion, id_par) para
    que dos corridas den el mismo archivo.
    """
    grupos = collections.OrderedDict()
    for r in filas:
        grupos.setdefault((r["tf"], r["blanco"], r["oracion"]), []).append(r)
    evidencias = []
    for (tf, blanco, oracion), miembros in grupos.items():
        mejor = min(miembros, key=lambda r: (-r["p"][r["prediccion"]], r["pmid"],
                                             r["seccion"], r["n_oracion"],
                                             r["id_par"]))
        evidencias.append({
            "tf": tf, "blanco": blanco, "oracion": oracion,
            "id_par": mejor["id_par"], "pmid": mejor["pmid"],
            "seccion": mejor["seccion"], "fuente": mejor["fuente"],
            "prediccion": mejor["prediccion"], "p": mejor["p"],
            "redaccion": mejor["redaccion"], "n_oracion": mejor["n_oracion"],
            "autorregulacion": any(m["autorregulacion"] for m in miembros),
            "pmids": sorted(set(m["pmid"] for m in miembros)),
            "n_copias": len(miembros),
        })
    return evidencias


def orden_evidencia(e):
    return (e["pmid"], e["seccion"], e["n_oracion"], e["id_par"])


def topar(evidencias, max_por_par):
    """Paso 4: a lo mas max_por_par evidencias por arista, DESPUES de la dedup.

    Ordenar por (pmid, seccion, n_oracion) hace que el recorte sea el mismo en
    cada corrida y no dependa del orden en que se leyo el archivo.
    """
    grupos = collections.OrderedDict()
    for e in evidencias:
        grupos.setdefault((e["tf"], e["blanco"]), []).append(e)
    salida = []
    for clave in sorted(grupos):
        ordenadas = sorted(grupos[clave], key=orden_evidencia)
        if max_por_par is not None and max_por_par > 0:
            ordenadas = ordenadas[:max_por_par]
        salida.extend(ordenadas)
    return salida


def resolver_signo(n_activates, n_represses, mayoria):
    """Paso 5: el signo de la arista, o el conflicto degradado a 'regulates'."""
    firmados = n_activates + n_represses
    if firmados == 0:
        return "regulates", False
    if n_activates == n_represses:
        # Empate exacto: no existe "la mayor de las dos". Con --mayoria por
        # encima de 0.5 la razon 0.5 tampoco alcanzaria, pero el caso se
        # escribe aparte para que la funcion siga siendo correcta si alguien
        # afloja el umbral, y no le ponga signo a un empate.
        return "regulates", True
    ganador = "activates" if n_activates > n_represses else "represses"
    if float(max(n_activates, n_represses)) / firmados >= mayoria:
        return ganador, False
    return "regulates", True


def agregar(evidencias, mayoria, min_evidencias=1, min_articulos=1):
    """Agrupa por (tf, blanco) y arma la arista. Devuelve (aristas, descartadas)."""
    grupos = collections.OrderedDict()
    for e in evidencias:
        grupos.setdefault((e["tf"], e["blanco"]), []).append(e)

    aristas, descartadas = [], 0
    for clave in sorted(grupos):
        tf, blanco = clave
        pruebas = grupos[clave]
        cuenta = collections.Counter(e["prediccion"] for e in pruebas)
        signo, conflicto = resolver_signo(cuenta["activates"],
                                          cuenta["represses"], mayoria)
        # `confianza` tiene UNA definicion: la media de la probabilidad de la
        # clase ganadora sobre las evidencias QUE VOTARON POR ELLA. Cuando un
        # conflicto degrada la arista a 'regulates' y ninguna evidencia predijo
        # 'regulates', no hay tales evidencias y la columna se deja VACIA.
        #
        # Antes se rellenaba con la media de p_regulates sobre toda la
        # evidencia contradictoria. Es otro numero --la masa que el modelo le
        # dio a una clase que nadie predijo-- publicado bajo la misma etiqueta
        # y sin nada en el TSV que lo distinguiera. Medido en una corrida de
        # prueba: las 74 aristas 'regulates' eran las 74 en conflicto, o sea
        # que el 100 % de esa columna para ese signo venia de la definicion
        # alterna. Una cifra que no mide lo que dice su etiqueta es el peor
        # defecto posible aqui, y vale igual cuando la cifra es plausible.
        #
        # Vacio no es perdida de informacion: n_activates, n_represses,
        # n_regulates y conflicto estan en la misma fila, y el informe cuenta
        # cuantas aristas quedaron sin confianza.
        votantes = [e for e in pruebas if e["prediccion"] == signo]
        if votantes:
            confianza = round(sum(e["p"][signo] for e in votantes)
                              / float(len(votantes)), 4)
        else:
            confianza = None
        # La representativa se elige sobre toda la evidencia cuando no hay
        # votantes: es la oracion a la que el modelo mas cerca estuvo de
        # llamar 'regulates', y sirve para que la arista siga siendo legible.
        base = votantes if votantes else pruebas
        representativa = min(base, key=lambda e: (-e["p"][signo],
                                                  orden_evidencia(e)))
        pmids = sorted(set(p for e in pruebas for p in e["pmids"]))
        arista = {
            "tf": tf, "blanco": blanco, "signo": signo, "conflicto": conflicto,
            "n_evidencias": len(pruebas),
            "n_activates": cuenta["activates"],
            "n_represses": cuenta["represses"],
            "n_regulates": cuenta["regulates"],
            "n_articulos": len(pmids),
            "confianza": confianza,
            "autorregulacion": any(e["autorregulacion"] for e in pruebas),
            "secciones": sorted(set(e["seccion"] for e in pruebas)),
            "pmids": pmids,
            "oracion_representativa": representativa["oracion"],
            "evidencias": sorted(pruebas, key=orden_evidencia),
        }
        if (arista["n_evidencias"] < min_evidencias
                or arista["n_articulos"] < min_articulos):
            descartadas += 1
            continue
        aristas.append(arista)
    return aristas, descartadas


def verificar(aristas, incluir_autorregulacion):
    """Invariantes de la seccion 5. Se corren ANTES de escribir nada."""
    if not aristas:
        sys.exit("Cero aristas. O los umbrales estan mal, o la entrada no es "
                 "la que crees. No escribo un archivo vacio.")
    for a in aristas:
        if a["n_evidencias"] != (a["n_activates"] + a["n_represses"]
                                 + a["n_regulates"]):
            sys.exit("Arista %s->%s: los conteos no cuadran."
                     % (a["tf"], a["blanco"]))
        if a["signo"] not in SIGNOS:
            sys.exit("Signo desconocido: %r. Revisa id2label del checkpoint."
                     % a["signo"])
        if a["autorregulacion"] and not incluir_autorregulacion:
            sys.exit("Se colo una arista autorregulatoria (%s->%s). Ver "
                     "seccion 3.4." % (a["tf"], a["blanco"]))


def barrido_sensibilidad(filas, args, min_evidencias, min_articulos):
    """El mismo pipeline con un solo umbral para las tres clases, de 0.50 a 0.90.

    Va siempre en el informe: los umbrales por omision no estan justificados,
    asi que quien lea la red tiene derecho a ver cuanto de ella depende de
    ellos sin volver a correr nada.
    """
    filas_barrido = []
    for i in range(9):
        u = round(0.50 + 0.05 * i, 2)
        umbrales = dict((c, u) for c in SIGNOS)
        vivas = filtrar(filas, umbrales, args.sin_pies, args.sin_introduccion,
                        args.incluir_autorregulacion)
        aristas, _ = agregar(topar(deduplicar(vivas), args.max_por_par),
                             args.mayoria, min_evidencias, min_articulos)
        cuenta = collections.Counter(a["signo"] for a in aristas)
        filas_barrido.append({
            "umbral": u,
            "n_aristas": len(aristas),
            "activates": cuenta["activates"],
            "represses": cuenta["represses"],
            "regulates": cuenta["regulates"],
            "n_conflictos": sum(1 for a in aristas if a["conflicto"]),
            "n_tfs": len(set(a["tf"] for a in aristas)),
            "n_blancos": len(set(a["blanco"] for a in aristas)),
        })
    return filas_barrido


# ------------------------------------------------------------------- salida

def celda(v):
    """Ningun campo puede llevar tabulador ni salto de linea."""
    return " ".join(str(v).split())


def fila_red(a):
    return [a["tf"], a["blanco"], a["signo"], texto_bool(a["conflicto"]),
            a["n_evidencias"], a["n_activates"], a["n_represses"],
            a["n_regulates"], a["n_articulos"],
            "" if a["confianza"] is None else "%.4f" % a["confianza"],
            texto_bool(a["autorregulacion"]), "|".join(a["secciones"]),
            "|".join(str(p) for p in a["pmids"]),
            a["oracion_representativa"]]


def filas_evidencias(aristas):
    for a in aristas:
        for e in a["evidencias"]:
            yield [a["tf"], a["blanco"], e["id_par"], e["pmid"], e["seccion"],
                   e["fuente"], e["prediccion"],
                   "%.6f" % e["p"][e["prediccion"]], e["redaccion"],
                   e["oracion"]]


def escribir_tsv(ruta, columnas, filas):
    """A un temporal; el renombrado lo hace publicar()."""
    with open(ruta + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(celda(v) for v in fila) + "\n")
        f.flush()
        os.fsync(f.fileno())


def escribir_json(ruta, obj):
    with open(ruta + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def publicar(rutas):
    """El renombrado de los tres archivos, al final y solo si todo salio bien.

    Escribir directo dejaba, ante cualquier fallo a media escritura, una red
    cortada que parecia completa; y de paso borraba la anterior, que si servia.
    """
    for r in rutas:
        os.replace(r + ".tmp", r)


# --------------------------------------------------------------------- main

def main(argv=None, log=print):
    ap = argparse.ArgumentParser(
        description="Agrega las predicciones en la red de aristas unicas.")
    ap.add_argument("--predicciones", default="datos_etapa2/predicciones.jsonl")
    ap.add_argument("--pares", default="datos_etapa2/pares.jsonl",
                    help="Los candidatos de la etapa 2. De ahi salen la oracion "
                         "cruda y n_oracion, que no viajan en las predicciones.")
    ap.add_argument("--salida", default="datos_etapa2/red.tsv")
    ap.add_argument("--evidencias", default="datos_etapa2/red_evidencias.tsv")
    ap.add_argument("--informe", default="datos_etapa2/red_informe.json")
    ap.add_argument("--umbral-activates", type=float,
                    default=UMBRALES_POR_OMISION["activates"])
    ap.add_argument("--umbral-represses", type=float,
                    default=UMBRALES_POR_OMISION["represses"])
    ap.add_argument("--umbral-regulates", type=float,
                    default=UMBRALES_POR_OMISION["regulates"])
    ap.add_argument("--umbrales",
                    help="Lee los tres de un umbrales_sugeridos.json. "
                         "Gana sobre los tres flags.")
    ap.add_argument("--mayoria", type=float, default=0.66)
    ap.add_argument("--max-por-par", type=int, default=200,
                    help="Tope de evidencias por arista, DESPUES de deduplicar. "
                         "0 o negativo deja pasar todas.")
    ap.add_argument("--min-evidencias", type=int, default=1)
    ap.add_argument("--min-articulos", type=int, default=1)
    ap.add_argument("--incluir-autorregulacion", action="store_true")
    ap.add_argument("--sin-pies", action="store_true",
                    help="Descarta la seccion pie_de_figura.")
    ap.add_argument("--sin-introduccion", action="store_true",
                    help="Descarta la seccion introduction.")
    args = ap.parse_args(argv)

    if not (0.5 < args.mayoria <= 1.0):
        sys.exit("--mayoria tiene que estar en (0.5, 1]: por debajo de 0.5 no "
                 "es una mayoria y le pondria signo a un par que la literatura "
                 "deja empatado.")

    umbrales = {"activates": args.umbral_activates,
                "represses": args.umbral_represses,
                "regulates": args.umbral_regulates}
    fuente_umbrales, calibrado_en = "por omision", None
    if args.umbrales:
        umbrales, calibrado_en = leer_umbrales(args.umbrales)
        fuente_umbrales = args.umbrales
    for c, u in sorted(umbrales.items()):
        if not (0.0 <= u <= 1.0):
            sys.exit("El umbral de %s es %r y tiene que ser una probabilidad."
                     % (c, u))
    if umbrales == UMBRALES_POR_OMISION:
        log("AVISO: umbrales 0.65/0.70/0.60 por omision. Reproducen la corrida "
            "del asesor y NO estan justificados: no habia conjunto de "
            "calibracion. Mira el barrido de sensibilidad del informe antes de "
            "citar cualquier conteo de aristas.")
    if calibrado_en:
        log("Umbrales calibrados en: %s" % calibrado_en)

    meta, ruta_del_meta = cargar_meta(args.predicciones)
    filas, medicion = cargar_predicciones(args.predicciones)
    filas = unir_con_pares(filas, cargar_pares(args.pares), args.pares, log)
    log("%d predicciones de %d articulos; meta en %s."
        % (len(filas), len(set(r["pmid"] for r in filas)), ruta_del_meta))
    log("  las cuatro probabilidades suman 1 en las %d filas (desviacion "
        "maxima %.2e) y la etiqueta es la clase mas probable."
        % (medicion["filas"], medicion["desviacion_maxima_de_la_suma"]))

    cuenta = collections.Counter()
    vivas = filtrar(filas, umbrales, args.sin_pies, args.sin_introduccion,
                    args.incluir_autorregulacion, cuenta)
    evidencias = deduplicar(vivas)
    topadas = topar(evidencias, args.max_por_par)
    aristas, descartadas = agregar(topadas, args.mayoria, args.min_evidencias,
                                   args.min_articulos)
    verificar(aristas, args.incluir_autorregulacion)

    log("  %d pasan los umbrales -> %d evidencias distintas -> %d tras el tope"
        % (len(vivas), len(evidencias), len(topadas)))
    log("  %d aristas (%d descartadas por --min-evidencias/--min-articulos)"
        % (len(aristas), descartadas))
    reparto = collections.Counter(a["signo"] for a in aristas)
    for s in SIGNOS:
        log("    %-11s %5d" % (s, reparto[s]))
    log("    %-11s %5d" % ("conflictos",
                           sum(1 for a in aristas if a["conflicto"])))

    informe = collections.OrderedDict()
    informe["fecha"] = datetime.datetime.now().replace(microsecond=0).isoformat()
    informe["predicciones"] = args.predicciones
    informe["pares"] = args.pares
    informe["umbrales"] = dict((c, umbrales[c]) for c in SIGNOS)
    informe["fuente_umbrales"] = fuente_umbrales
    informe["calibrado_en"] = calibrado_en
    informe["mayoria"] = args.mayoria
    informe["max_por_par"] = args.max_por_par
    informe["min_evidencias"] = args.min_evidencias
    informe["min_articulos"] = args.min_articulos
    informe["sin_pies"] = texto_bool(args.sin_pies)
    informe["sin_introduccion"] = texto_bool(args.sin_introduccion)
    informe["incluir_autorregulacion"] = texto_bool(args.incluir_autorregulacion)
    informe["n_predicciones"] = len(filas)
    # La evidencia de que la comprobacion del softmax corrio sobre ESTE
    # archivo, con su numero. Una comprobacion que solo se nota cuando falla
    # es indistinguible de una comprobacion que no existe: quien lea la red no
    # tendria como saber si el `predicciones.jsonl` del que salio se miro.
    informe["probabilidades"] = medicion
    informe["descartes"] = dict(cuenta)
    informe["n_supervivientes"] = len(vivas)
    informe["n_evidencias_distintas"] = len(evidencias)
    informe["n_evidencias_colapsadas"] = sum(e["n_copias"] - 1
                                             for e in evidencias)
    informe["n_evidencias_tras_tope"] = len(topadas)
    informe["n_aristas"] = len(aristas)
    informe["n_aristas_descartadas_por_minimos"] = descartadas
    informe["n_tfs"] = len(set(a["tf"] for a in aristas))
    informe["n_blancos"] = len(set(a["blanco"] for a in aristas))
    informe["n_articulos"] = len(set(p for a in aristas for p in a["pmids"]))
    informe["reparto_signos"] = dict((s, reparto[s]) for s in SIGNOS)
    informe["n_conflictos"] = sum(1 for a in aristas if a["conflicto"])
    # Aristas cuya columna `confianza` va vacia: el conflicto las degrado a
    # 'regulates' y ninguna evidencia predijo esa clase, asi que no hay
    # evidencia que promediar. Va en el informe para que el hueco de la
    # columna sea un numero y no una sorpresa al abrir el TSV.
    informe["n_aristas_sin_confianza"] = sum(1 for a in aristas
                                             if a["confianza"] is None)
    informe["por_seccion"] = dict(collections.Counter(
        e["seccion"] for a in aristas for e in a["evidencias"]))
    informe["por_fuente"] = dict(collections.Counter(
        e["fuente"] for a in aristas for e in a["evidencias"]))
    informe["por_redaccion"] = dict(collections.Counter(
        e["redaccion"] for a in aristas for e in a["evidencias"]))
    informe["top_tf"] = collections.Counter(
        a["tf"] for a in aristas).most_common(30)
    informe["barrido"] = barrido_sensibilidad(filas, args, args.min_evidencias,
                                              args.min_articulos)
    informe["meta_inferencia"] = {
        "ruta": ruta_del_meta,
        "modelo": meta.get("modelo"),
        "id2label": meta.get("id2label"),
        "do_lower_case": meta.get("do_lower_case"),
        "exactitud_control": meta.get("exactitud_control"),
    }

    for ruta in (args.salida, args.evidencias, args.informe):
        d = os.path.dirname(ruta)
        if d:
            os.makedirs(d, exist_ok=True)
    escribir_tsv(args.salida, COLUMNAS_RED, [fila_red(a) for a in aristas])
    escribir_tsv(args.evidencias, COLUMNAS_EVIDENCIAS, filas_evidencias(aristas))

    # Las huellas se sellan DESPUES de escribir el TSV y ANTES del informe: es
    # el unico momento en que el contenido definitivo ya existe y nada lo ha
    # tocado. Van las dos entradas y la propia salida, asi la evaluacion puede
    # comprobar la cadena entera y no solo la mitad.
    informe["huellas"] = procedencia.sellar({
        "pares": args.pares,
        "predicciones": args.predicciones,
    })
    # La red se mide en su temporal. escribir_tsv() dejo el contenido en
    # .tmp y publicar() lo renombra al final, junto con este mismo informe, asi
    # que aqui el nombre final todavia no existe. Medirlo directamente daba
    # huella None y la evaluacion rechazaba la cadena por una discrepancia que
    # no era real: el guardian atrapo este error en su primera corrida.
    informe["huellas"]["red"] = procedencia.sellar_como(
        args.salida, args.salida + ".tmp")

    escribir_json(args.informe, informe)
    publicar([args.salida, args.evidencias, args.informe])

    log("")
    log("%d aristas -> %s" % (len(aristas), args.salida))
    log("%d evidencias -> %s" % (len(topadas), args.evidencias))
    log("informe -> %s (mira el barrido antes de citar los conteos)"
        % args.informe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
