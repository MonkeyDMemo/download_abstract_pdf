#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Etapa 2: pares candidatos (TF, blanco) del corpus, con las menciones
marcadas en el formato exacto del entrenamiento.

Recorre los 918 textos completos y los resumenes de la base, corta en
oraciones, reconoce menciones con `lexico.Lexico`, forma los pares dirigidos
que coocurren en una misma oracion y escribe una linea por par.

    python etapa2/extraer_pares.py

--------------------------------------------------------------------------
EL RETO DE ESCALA, Y COMO SE RESUELVE

`auditar_signo.py` compila dos expresiones regulares por par (TF, blanco) y
las corre sobre cada oracion. Con seis represores y cinco bombas son doce
pares y funciona. Con 536 TFs y 5700 genes el espacio de pares es de 3.05
millones, y una alternancia de 5700 ramas cuesta 7.22 s en 20 documentos
--proyeccion de 331 s al corpus solo para el primer patron--. Con el bucle por
pares no termina.

La solucion invierte el bucle. En vez de preguntar "¿aparece este par?" 3.05
millones de veces por oracion, se pregunta una sola vez "¿que nombres hay
aqui?":

1. Un unico `re.finditer` por oracion parte el texto en tokens candidatos.
   Es el mismo trabajo lineal sobre el texto, sin importar cuantos genes tenga
   el diccionario.
2. Cada token se resuelve con un `dict` --coste constante-- a su entidad
   canonica. Medido: 0.06 s en los mismos 20 documentos, contra 7.22 s.
3. Los pares se forman **entre las menciones que de verdad aparecieron**, que
   son a lo mas `--max-menciones` (8 por omision), o sea 56 pares dirigidos en
   el peor caso, no 3.05 millones.

El coste deja de depender del tamano del diccionario y pasa a depender del
tamano del corpus, que es lo que se recorre de todas formas. El reconocimiento
vive en `lexico.py`; aqui solo se consume.

--------------------------------------------------------------------------
LO QUE ESTE SCRIPT NO HACE

No decide ninguna arista y no aplica ningun umbral: emite candidatos. Un
candidato es "estos dos nombres coocurren en esta oracion", no "existe esta
relacion". Quien decide es la etapa 4, sobre las probabilidades de la etapa 3.

El reconocimiento de genes por diccionario y por patron produce falsos
positivos y no sustituye al reconocimiento de entidades: una lista enumerativa
de genes, un nombre de cepa o un plasmido con nombre de gen entran igual.

Lo que si comprueba, antes de leer un solo documento, es de donde salio el
diccionario que consume: procedencia declarada fila por fila (la etiqueta) y
cuantas de sus entidades aparecen de verdad en el corpus (el contenido). Las
dos comprobaciones vivian solo en la etapa 5, o sea despues de escribir
`pares.jsonl`, `predicciones.jsonl` y `red.tsv`. **La red es el artefacto que
se comparte**, y quien corra hasta ahi y ensene el TSV tiene derecho a que
algo le haya dicho que su diccionario venia del patron de referencia. Ver
revisar_procedencia() y revisar_lo_que_el_diccionario_encuentra().

--------------------------------------------------------------------------
LOS OPERONES QUE NADIE ESCRIBE

La tabla de operones se deriva del genoma emitiendo **todas** las sub-corridas
contiguas de longitud >= 2 (seccion 2, salida B), asi que junto a `mexAB-oprM`
aparecen combinaciones que ningun articulo escribe, como `mexB-oprM`.

Medido sobre los 918 textos completos: **244 de los 3030 nombres de la tabla
aparecen alguna vez; 2786 no aparecen nunca**, y `mexB-oprM` es uno de esos.
Los que si aparecen son mayoritariamente formas cortas legitimas que la
literatura usa de verdad (`mexEF` 126 menciones, `mexAB` 80, `pqsBC` 118), no
ruido.

**Decidido: no se filtran.** Tres razones, en orden:

1. El ruido que se les atribuia no es medible. Cargar la tabla entera o no
   cargarla deja las mismas 5 superficies ambiguas, o sea que las 2786 que no
   aparecen no le quitan ni una mencion a ningun gen: no reconocen nada y no
   tapan nada.
2. Filtrar por presencia en el corpus haria que una tabla que el contrato
   define como derivada del genoma pasara a depender del corpus, y encogiera
   sola cada vez que el corpus cambia. Esa tabla es ademas la que la etapa 5
   usa para la equivalencia operon-gen; una normalizacion de evaluacion que se
   mueve con los datos que se evaluan es peor que unas filas muertas.
3. La tabla no se escribe aqui, sino en la etapa 1. Filtrarla desde el
   consumidor dejaria dos versiones de la misma tabla en circulacion.

Lo que si se hace es publicar el numero en el informe (`operones_de_la_tabla`
y `operones_vistos_en_el_corpus`), para que la decision se pueda revisar con
evidencia de la corrida y no de memoria.

--------------------------------------------------------------------------

Tampoco decide sobre la autorregulacion. El par `X -> x` se EMITE con
`autorregulacion: true` --seccion 3.4 del contrato, que manda sobre la 3.2
regla 5-- y quien lo excluye por omision es `red.py`. Descartarlo aqui hacia
que las 10 filas autorregulatorias del patron de oro salieran de la evaluacion
con el veredicto `no_recuperada_sin_candidato`, que declara que los dos
extremos nunca coocurrieron en una oracion: era falso, y el evaluador le
atribuia al extractor una decision de politica.

Solo biblioteca estandar.
"""

import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lexico as _lexico
from grn_bronce import texto as _texto

# Clases de seccion que entran. `excluir` y `otra` quedan fuera; `otra` se
# puede revertir con --incluir-otras.
#
# Se excluyen METHODS y companía porque son prosa densa en nombres de gen
# (0.60-1.09 menciones por Kchar) que describe construccion de plasmidos y
# cepas, no regulacion: "The coding regions of LasR, RhlR and QscR were
# amplified by PCR...". Un extractor lee ahi tres genes coocurriendo y no hay
# ninguna relacion que extraer. Es un quinto del corpus a cambio de casi
# ninguna arista y de ruido garantizado.
SECCIONES_QUE_ENTRAN = frozenset([
    "abstract", "introduction", "results", "discussion",
    "results_and_discussion", "background", "conclusion", "pie_de_figura",
])

# Redaccion desde el fenotipo del mutante: la trampa. Se exige que aparezcan
# las dos mitades --la perdida de funcion y el aumento de expresion-- porque
# por separado no significan nada.
#
# La letra griega esta anadida respecto de `auditar_signo.py:90-93`, que
# buscaba la palabra `Delta`. Sintoma medido: 1039 `Δ` contra 4 `Delta` en 60
# documentos, con `PERDIDA.search("ΔmexR strain")` devolviendo False, o sea
# que las oraciones de fenotipo escritas con la letra --que son casi todas--
# se clasificaban como `otra` y se perdia justo la particion que la etapa 6
# existe para medir.
PERDIDA = re.compile(
    u"(\\b(mutant|mutants|mutation|mutations|knockout|knock-out|deletion|"
    u"deleted|disrupt|disruption|inactivat|loss of|lacking|null|"
    u"insertional|defective)|[Dd]elta\\s*|Δ|∆)", re.I)
AUMENTO = re.compile(
    r"\b(overexpress|over-express|overproduc|elevated|increased|"
    r"upregulat|up-regulat|hyperexpress|derepress|de-repress|"
    r"enhanced expression|higher levels?)", re.I)

# Redaccion directa: dice el signo con todas sus letras.
DIRECTA = re.compile(
    r"\b(repress|repressor|negative regulator|negatively regulat|"
    r"downregulat|down-regulat|silenc|activat|positive regulator|"
    r"positively regulat|induc|promotes expression|transcriptional regulator|"
    r"regulon|regulates|regulated by|controls expression|under the control)",
    re.I)

# La trampa al reves: habla de activacion donde el signo conocido es lo
# contrario. Se conserva la clase de `auditar_signo.clasificar()` para que la
# etapa 6 pueda unir sus filas.
CONTRARIA = re.compile(
    r"\b(activat|positive regulator|positively regulat|induc|"
    r"upregulates|promotes expression)", re.I)

# Formato del marcado, verificado fila por fila antes de escribir. La
# retrorreferencia evita el falso positivo `<e1> X </e2>`.
MARCADO = re.compile(r"<e([12])> (\S+) </e\1>")

CLAVES = ["text", "label", "pmid", "tf", "target", "id_par", "seccion",
          "fuente", "n_oracion", "oracion_cruda", "mencion_tf",
          "mencion_target", "pos_tf", "pos_target", "distancia",
          "autorregulacion", "redaccion", "n_menciones_oracion",
          "target_es_tf"]

# Limites de longitud de oracion. Medido: sobrevive el 96.1 %. Lo que cae por
# abajo son encabezados sueltos y fragmentos colgantes; lo que cae por arriba
# son casi todas tablas volcadas sin puntuacion, tipo
# "Enrich.Distance to ATGGenes affectedaConserved motifbPMW scorebPA0139ahpC...".
MIN_ORACION = 40
MAX_ORACION = 700

# Tope duro del `text` que se le entrega al modelo. La invariante del contrato
# aborta la corrida si alguna fila lo rebasa; el filtro previo hace que no
# llegue a pasar. Una oracion de 700 caracteres muy cargada de puntuacion
# puede crecer hasta ~880 al pretokenizar, y los marcadores anaden 24 mas.
MAX_TEXTO = 900

# Seccion 2, salida A: la columna `fuente` del diccionario declara fila por
# fila de donde salio cada gen, y el patron de referencia NO es un valor
# valido. La lista es la misma que la de `construir_diccionario.py` (que la
# escribe) y la de `evaluar_oro.py` (que la vigila en la ultima etapa);
# `test_extraer_pares.py` compara las tres para que no puedan divergir.
FUENTES_VALIDAS = ("refseq", "kegg", "uniprot", "uniprot_especie", "manual")

# Cualquier procedencia que nombre al patron de referencia o a la auditoria de
# signo. Se compara en minusculas y por subcadena, asi que `oro`, `ORO` y las
# formas largas con el nombre del archivo caen aqui igual. (El nombre literal
# de esos dos archivos no se escribe: la seccion 0.4 prohibe teclearlo fuera
# de los dos evaluadores, y este script es del pipeline.)
FUENTES_DEL_ORO = ("oro", "auditoria", "patron", u"patrón")

# Forma del locus tag, la misma que la clave primaria del diccionario. Aqui se
# usa para NO contar las menciones que se reconocieron por el locus tag: un
# `PA\d{4}` se fabrica en dos lineas y no demuestra que quien escribio el
# diccionario supiera nada. `test_extraer_pares.py` compara este patron con el
# de `lexico.py` para que no puedan divergir.
LOCUS_TAG = re.compile(r"^PA\d{4}(\.\d)?$")

# Entidades canonicas distintas, reconocidas por un NOMBRE, que el diccionario
# tiene que encontrar en el corpus completo. Ver
# revisar_lo_que_el_diccionario_encuentra().
MINIMO_ENTIDADES_VISTAS = 1500

# Banda de la invariante de escala. Estaban escritos dentro de `main()`, y ahi
# no habia forma de probar sobre un corpus de juguete que la comprobacion que
# va DESPUES de ellos --la de lo que el diccionario encuentra-- se llama de
# verdad: la corrida completa de dos documentos moria siempre en la banda. Con
# nombre, una prueba puede aflojar la banda y comprobar la siguiente.
MIN_PARES = 20000
MAX_PARES = 400000


def leer_diccionario(ruta):
    """Las filas del diccionario, con el mismo lector que usa `Lexico`.

    Se lee una segunda vez a proposito y con el lector del modulo compartido:
    asi el encabezado se valida contra `COLUMNAS_GENES` una sola vez en un
    solo sitio, y un TSV con las columnas cambiadas de orden --que haria que
    `fuente` se leyera de otra columna-- muere aqui en vez de pasar
    inadvertido. Antes esta comprobacion era `sum(1 for _ in f) - 1`, que
    cuenta lineas y no mira ni una cabecera.
    """
    return _lexico._leer_tsv(ruta, _lexico.COLUMNAS_GENES)


def revisar_procedencia(filas, ruta):
    """El guardian de circularidad, en la ETAPA 2 y no solo en la 5.

    Vivia unicamente en `evaluar_oro.py`, o sea despues de que `pares.jsonl`,
    `predicciones.jsonl` y `red.tsv` ya se hubieran escrito con un diccionario
    circular. Demostrado: un `genes_pao1.tsv` con `fuente=oro` en las 5700
    filas producia 86217 pares y 3353 aristas con codigo 0 en las dos etapas,
    sin una sola queja sobre la procedencia.

    **Importa porque la red es el artefacto que se comparte.** Quien corra
    hasta `red.py` y ensene el TSV --que es el uso normal: la evaluacion es
    opcional y va despues-- no recibia ningun aviso de que su diccionario
    venia del patron de referencia, y la red se ve exactamente igual. El aviso
    no puede vivir solo en la ultima etapa.

    Una fuente que no esta en el enum del contrato no aborta: no es prueba de
    circularidad, solo de que el diccionario no lo escribio
    `construir_diccionario.py`. Se avisa y se cuenta.

    Devuelve el conteo por fuente para el informe.
    """
    fuentes = collections.Counter()
    del_patron, desconocidas = [], collections.Counter()
    for fila in filas:
        for token in [t for t in fila["fuente"].split("|") if t]:
            fuentes[token] += 1
            bajo = token.strip().lower()
            if any(marca in bajo for marca in FUENTES_DEL_ORO):
                del_patron.append("%s (fuente=%s)"
                                  % (fila["locus_tag"], token))
            elif bajo not in FUENTES_VALIDAS:
                desconocidas[token] += 1
    if del_patron:
        sys.exit(
            "%d de las %d filas de %s declaran que su procedencia es el patron "
            "de referencia o la auditoria de signo (%s%s). Eso hace circular "
            "todo lo que salga de aqui (seccion 7 del contrato): los pares se "
            "formarian con los nombres que la evaluacion va a buscar, y la "
            "exhaustividad de la etapa 5 mediria el solapamiento del "
            "diccionario consigo mismo. La columna `fuente` solo admite %s. "
            "No escribo."
            % (len(del_patron), len(filas), ruta, ", ".join(del_patron[:8]),
               ", ..." if len(del_patron) > 8 else "",
               ", ".join(FUENTES_VALIDAS)))
    if desconocidas:
        print("AVISO: %d filas declaran una procedencia que no esta en el enum "
              "del contrato (%s). No lo escribio construir_diccionario.py."
              % (sum(desconocidas.values()),
                 ", ".join(sorted(desconocidas))))
    return collections.OrderedDict(sorted(fuentes.items())), desconocidas


def revisar_lo_que_el_diccionario_encuentra(por_nombre, n_entidades, ruta):
    """Cuantas entidades del diccionario aparecen DE VERDAD en el corpus,
    escritas con un nombre.

    La comprobacion de arriba mira una etiqueta, y una etiqueta se puede
    escribir: quien copie el patron de referencia y ponga `refseq` en la
    columna `fuente` la pasa entera. Demostrado en la etapa 5, con ese mismo
    truco y con relleno de simbolos inventados (`zzz0001`...) para cruzar el
    guardian de tamano que la acompanaba: un conteo de filas se satisface con
    filas.

    Esta mide contenido, y contra la unica referencia que esta etapa tiene
    derecho a abrir: **el corpus**. Un diccionario que dice ser el genoma de
    PAO1 tiene que reconocer miles de genes distintos, por su nombre, en 918
    articulos sobre PAO1. Uno copiado de una lista escrita a mano solo puede
    reconocer los nombres de esa lista.

    **Las menciones que se reconocieron por el locus tag no cuentan, y esa es
    la mitad que hace que la medicion sirva.** Medido: un diccionario con solo
    1100 simbolos de verdad y 4542 filas de relleno inventado seguia
    reconociendo 2646 entidades en el corpus, porque conservaba los 5642 locus
    tags y la literatura de PAO1 escribe muchos `PA\\d{4}`. Contando solo las
    reconocidas por un nombre, ese mismo diccionario cae a 1112. Un locus tag
    se genera con un bucle; un simbolo de gen, no.

    Los tres numeros medidos sobre los 918 textos completos:

    | diccionario                                   | por nombre |
    |-----------------------------------------------|------------|
    | el real de la etapa 1 (2150 filas con simbolo)|       1979 |
    | 771 simbolos reales + 4871 de relleno         |        865 |
    | 1100 simbolos reales + 4542 de relleno        |       1112 |

    771 filas con contenido es el tamano del diccionario del ataque, o sea el
    techo de lo que se puede sacar de una lista de 165 nombres enriquecida con
    sus propios alias. El umbral de 1500 queda 1.7 veces por encima de eso y
    un 24 % por debajo del diccionario real. Para acercarse al umbral hay que
    aportar mas de mil simbolos de gen que la literatura de PAO1 use de
    verdad, y eso ya no es una copia: es un genoma.

    Como toda medicion contra el corpus, solo vale sobre el corpus completo:
    con --limite-docs no se comprueba, igual que la invariante de escala.
    """
    if len(por_nombre) >= MINIMO_ENTIDADES_VISTAS:
        return
    sys.exit(
        "El diccionario %s define %d entidades canonicas, pero solo %d se "
        "encuentran en el corpus escritas con un nombre (el minimo es %d; las "
        "que solo aparecen como locus tag no cuentan, porque un PAxxxx se "
        "genera con un bucle). Un diccionario del genoma reconoce miles de "
        "genes por su nombre en 918 articulos sobre PAO1; uno copiado de una "
        "lista escrita a mano reconoce los de la lista y nada mas, por muchas "
        "filas de relleno que traiga. O el diccionario no es del genoma, o el "
        "corpus no es el que crees. No escribo."
        % (ruta, n_entidades, len(por_nombre), MINIMO_ENTIDADES_VISTAS))


def clasificar(oracion):
    """Como esta redactada la evidencia.

    Generalizacion de `auditar_signo.clasificar()`. **No decide el signo y no
    se usa para invertirlo**: es una caracteristica que se propaga hasta la
    evidencia para que la etapa 6 pueda medir la exactitud partida por
    redaccion. Voltear el signo segun una heuristica de regex, sin medir antes
    cuanto se equivoca, seria cambiar un error por otro sin saber cual es
    mayor.
    """
    if PERDIDA.search(oracion) and AUMENTO.search(oracion):
        return "fenotipo_mutante"
    if DIRECTA.search(oracion):
        return "directa"
    if CONTRARIA.search(oracion):
        return "contraria_aparente"
    return "otra"


def indice_fulltext(directorio):
    """{pmid: ruta} listando el directorio UNA vez.

    **Nunca se usa `descargas.ruta`**: el PMCID esta en `db.COLUMNAS_EDITABLES`
    y venir de la base no lo hace de fiar.
    """
    indice = {}
    if not os.path.isdir(directorio):
        return indice
    for nombre in sorted(os.listdir(directorio)):
        if not nombre.endswith(".txt"):
            continue
        pmid = nombre.split("_")[0]
        if pmid.isdigit():
            indice[pmid] = os.path.join(directorio, nombre)
    return indice


def leer_documentos(ruta_db):
    """[(pmid, abstract)] de la base, en modo de solo lectura."""
    uri = pathlib.Path(ruta_db).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        filas = con.execute(
            "SELECT pmid, abstract FROM documentos").fetchall()
    finally:
        con.close()
    salida = []
    for pmid, abstract in filas:
        pmid = str(pmid).strip()
        if pmid.isdigit():
            salida.append((pmid, abstract or ""))
    salida.sort(key=lambda t: int(t[0]))
    return salida


def piezas_de_documento(pmid, abstract, ruta_txt, clases, incluir_otras,
                        cuenta_desconocidas):
    """[(clase, cuerpo, fuente)] ya filtrado por seccion.

    **Si el PMID tiene texto completo, su resumen sale del `.txt`; el de la
    base solo se lee para los documentos sin texto completo.** Medido: los
    primeros 120 caracteres de `documentos.abstract` aparecen literales dentro
    del `.txt` en 777 de 918 casos, y los primeros 60 en 22 mas, o sea 799 de
    918 (87 %). `auditar_signo.py:199-203` procesaba las dos piezas y leia el
    resumen de esos 799 articulos dos veces; su dedup por texto de oracion lo
    tapaba por accidente, pero con `pmid` y `seccion` en la clave dejaria de
    taparlo y cada arista de resumen contaria doble su evidencia.

    **La `fuente` va por pieza y no por documento, y eso es lo que mantiene
    viva la invariante de la seccion 3.3.** Mientras la funcion devolvia un
    solo valor por documento, dos filas del mismo PMID compartian `fuente`
    siempre, asi que el guardian de "este resumen se leyo dos veces" no podia
    dispararse en una corrida: estaba vivo en su prueba y muerto en
    produccion. Con la fuente por pieza, la tentacion evidente --caerse a
    `documentos.abstract` cuando el .txt no trae `## ABSTRACT`, que son 4 de
    918-- produce una pieza `resumen` dentro de un documento `fulltext`, y esa
    es exactamente la forma que `verificar()` detecta.
    """
    if ruta_txt is None:
        if not abstract.strip():
            return []
        return [("abstract", abstract, "resumen")]

    with open(ruta_txt, encoding="utf-8") as f:
        markdown = f.read()
    piezas = []
    for etiqueta, cuerpo in _texto.bloques(markdown):
        clase = clases.get(etiqueta, "otra") if etiqueta else "otra"
        if clase == "otra":
            cuenta_desconocidas[etiqueta or "(antes del primer ##)"] += len(cuerpo)
            if not incluir_otras:
                continue
        elif clase not in SECCIONES_QUE_ENTRAN:
            # METHODS y compania. Es el 19.6 % del corpus y la unica linea que
            # lo deja fuera: si se neutraliza, entra prosa de construccion de
            # plasmidos donde tres genes coocurren sin ninguna relacion que
            # extraer. La prueba que lo cubre corre esta funcion con un
            # documento que tiene seccion de metodos, no asserta constantes.
            continue
        if cuerpo.strip():
            piezas.append((clase, cuerpo, "fulltext"))
    return piezas


def elegir_ocurrencias(ocs_tf, ocs_target):
    """La combinacion de ocurrencias de minima distancia.

    **Esta es la regla que decide si el pipeline funciona o no.** Medido sobre
    las 493 filas `no_relation` del entrenamiento: 485 (98.4 %) comparten
    ventana Y par con una fila positiva, y en 484 de esas lo unico que cambia
    es donde va el marcador. O sea que `no_relation` no significa "este TF no
    regula este gen", sino "esta ocurrencia concreta no es la que el anotador
    eligio". Si el generador marcara todas las combinaciones, produciria
    masivamente entradas con la forma exacta que el modelo aprendio a llamar
    `no_relation`, y la exhaustividad se hundiria por construccion.

    Cuando hubo eleccion posible (823 filas), los positivos marcan el par mas
    cercano en 244 de 331 casos (73.7 %).

    Empates: menor `pos_tf`, y despues menor `pos_target`.
    """
    mejor = None
    for a in ocs_tf:
        for b in ocs_target:
            if a[0] == b[0] and a[1] == b[1]:
                continue
            distancia = max(a[0], b[0]) - min(a[1], b[1])
            clave = (distancia, a[0], b[0])
            if mejor is None or clave < mejor[0]:
                mejor = (clave, a, b)
    if mejor is None:
        return None
    return mejor[1], mejor[2], mejor[0][0]


def candidatos_de_oracion(pmid, seccion, fuente, n_oracion, oracion, lex,
                          max_menciones, cuenta, vistas=None):
    """Los pares de una oracion, o [] si la oracion se descarta.

    `vistas`, si se pasa, es un dict {entidad canonica: se vio por un nombre}
    con lo que el diccionario ha encontrado en el corpus. Se alimenta con
    TODAS las menciones reconocidas, incluidas las de las oraciones que
    despues se descartan por tener demasiadas entidades o por no traer ningun
    TF: lo que mide es si este diccionario reconoce este corpus, y eso no
    depende de la politica de pares. El valor distingue la mencion escrita con
    un nombre de la escrita con un locus tag, que es lo que hace util la
    medicion. Ver revisar_lo_que_el_diccionario_encuentra().
    """
    menciones = lex.menciones(oracion)
    if not menciones:
        cuenta["oraciones_sin_mencion"] += 1
        return []

    por_entidad = collections.OrderedDict()
    for ini, fin, superficie, idc, es_tf in menciones:
        por_entidad.setdefault(idc, []).append((ini, fin, superficie, es_tf))
        if vistas is not None and not vistas.get(idc):
            vistas[idc] = not LOCUS_TAG.match(superficie)
    n_distintas = len(por_entidad)

    if n_distintas > max_menciones:
        # Hay parrafos con 40 genes distintos (780 pares posibles) y otro con
        # 23 ("TABLE I The 30 most influential hubs ... lasR 99 fur ..."). Una
        # lista enumerativa no afirma nada y aportaria cientos de pares falsos.
        cuenta["oraciones_demasiadas_menciones"] += 1
        return []

    tfs = [idc for idc in por_entidad if lex.es_tf(idc)]
    if not tfs:
        cuenta["oraciones_sin_tf"] += 1
        return []

    # Una sola entidad en la oracion todavia puede dar un par: el
    # autorregulatorio, si el TF aparece dos veces. Este atajo esta antes de
    # pretokenizar porque la oracion de una sola mencion es el caso mas comun
    # del corpus y pretokenizarla para nada costaria la mitad de la corrida.
    if n_distintas < 2 and not any(len(por_entidad[t]) >= 2 for t in tfs):
        cuenta["oraciones_sin_par"] += 1
        return []

    protegidos = [(m[0], m[1]) for m in menciones]
    pretokenizado, nuevos = _texto.pretokenizar(oracion, protegidos)
    mapa = dict(zip(protegidos, nuevos))
    redaccion = clasificar(oracion)

    salida = []
    for tf_id in tfs:
        for target_id in por_entidad:
            # EL PAR X -> x SE EMITE, MARCADO. El contrato se contradecia a si
            # mismo: la seccion 3.2 regla 5 exige
            # `id_canonico_tf != id_canonico_target`, y la 3.4 dice que
            # `extraer_pares.py` lo EMITE con `autorregulacion: true` y que
            # `red.py` lo excluye salvo --incluir-autorregulacion. Se resuelve
            # a favor de la 3.4, que es la que razona la decision: la
            # autorregulacion existe en el dominio, esta en el patron de oro y
            # tirarla en la extraccion falsea el problema.
            #
            # Sintoma de descartarla aqui: las 10 filas autorregulatorias del
            # oro (MexR->mexR, MexZ->mexZ, NfxB->nfxB, AlgU->algU, AmrZ->amrZ,
            # PchR->pchR, MexL->mexL...) salian con veredicto
            # `no_recuperada_sin_candidato`, cuyo significado declarado es "los
            # dos extremos resolvieron pero nunca coocurrieron en una oracion".
            # Era falso: hay 1228 oraciones en 300 de los 918 textos donde un
            # TF aparece dos o mas veces. El evaluador atribuia al extractor
            # una decision de politica que estaba tomada aqui.
            #
            # La proteccion no desaparece, se muda: `red.py` la excluye por
            # omision, porque sin analisis sintactico no hay como distinguir
            # "NalD reprime a nalD" de una oracion que nombra `nalD` dos veces,
            # una de ellas como `ΔnalD` --al intentarlo salian 40 oraciones
            # para NalD -> nalD, un par que el oro da por no atestiguado, y
            # tenia razon el oro--.
            #
            # Lo que si se exige siempre son DOS OCURRENCIAS distintas: con una
            # sola, `elegir_ocurrencias()` devuelve None y no hay par.
            elegido = elegir_ocurrencias(por_entidad[tf_id],
                                         por_entidad[target_id])
            if elegido is None:
                if target_id == tf_id:
                    # El TF se encuentra a si mismo pero solo aparece una vez.
                    # Este contador cuenta candidatos autorregulatorios que no
                    # existen, no combinaciones (oracion, TF): el contador
                    # anterior, `pares_misma_entidad`, subia una vez por cada
                    # TF de cada oracion --el TF siempre se encuentra a si
                    # mismo-- y el informe lo imprimia junto a los conteos de
                    # oraciones, donde se leia como "18185 candidatos de
                    # autorregulacion descartados". No contaba eso.
                    cuenta["autorregulacion_sin_segunda_ocurrencia"] += 1
                continue
            oc_tf, oc_tg, distancia = elegido

            tf = lex.forma_proteina(tf_id)
            target = lex.forma_gen(target_id)
            span_tf = mapa[(oc_tf[0], oc_tf[1])]
            span_tg = mapa[(oc_tg[0], oc_tg[1])]
            marcado = _texto.marcar(pretokenizado, span_tf, span_tg)
            if len(marcado) > MAX_TEXTO:
                # La invariante del contrato aborta la corrida si esto llega a
                # la salida. Se filtra antes para no tirar 100 mil pares
                # buenos por una oracion cargada de parentesis.
                cuenta["pares_texto_largo"] += 1
                continue

            # Las dos formas de autorregulacion del contrato: la misma entidad
            # canonica a los dos lados (NalD -> nalD) y el operon que contiene
            # al propio gen del regulador (PhoB -> phoBR).
            auto = (target_id == tf_id
                    or tf_id in lex.miembros_operon(target_id))
            if target_id == tf_id:
                cuenta["pares_autorregulacion_antes_del_tope"] += 1

            crudo = "%d|%s|%d|%s|%s" % (int(pmid), seccion, n_oracion, tf,
                                        target)
            fila = collections.OrderedDict()
            fila["text"] = marcado
            fila["label"] = ""
            fila["pmid"] = int(pmid)
            fila["tf"] = tf
            fila["target"] = target
            fila["id_par"] = hashlib.sha1(
                crudo.encode("utf-8")).hexdigest()[:16]
            fila["seccion"] = seccion
            fila["fuente"] = fuente
            fila["n_oracion"] = n_oracion
            fila["oracion_cruda"] = oracion
            fila["mencion_tf"] = oc_tf[2]
            fila["mencion_target"] = oc_tg[2]
            fila["pos_tf"] = oc_tf[0]
            fila["pos_target"] = oc_tg[0]
            fila["distancia"] = distancia
            fila["autorregulacion"] = auto
            fila["redaccion"] = redaccion
            fila["n_menciones_oracion"] = n_distintas
            fila["target_es_tf"] = lex.es_tf(target_id)
            salida.append((fila, pretokenizado))
    return salida


def candidatos_de_documento(pmid, piezas, lex, max_menciones, cuenta,
                            vistas=None):
    """Todos los candidatos de un documento, numerando las oraciones.

    `piezas` son las de `piezas_de_documento()`: (clase, cuerpo, fuente). La
    fuente viaja por pieza, no por documento; ver ahi por que.

    `n_oracion` es el indice 0-based de la oracion dentro de las oraciones
    CONSERVADAS del documento, en orden de aparicion. "Conservadas" quiere
    decir: las que sobrevivieron al filtro de seccion y al de longitud. El
    filtro de menciones no cuenta a proposito, porque depende del diccionario y
    un diccionario nuevo correria todos los indices --y con ellos todos los
    `id_par`-- de documentos que no cambiaron.
    """
    salida = []
    n_oracion = 0
    for seccion, cuerpo, fuente in piezas:
        for oracion in _texto.oraciones(cuerpo):
            largo = len(oracion)
            if largo < MIN_ORACION:
                cuenta["oraciones_cortas"] += 1
                continue
            if largo > MAX_ORACION:
                cuenta["oraciones_largas"] += 1
                continue
            cuenta["oraciones_examinadas"] += 1
            salida.extend(candidatos_de_oracion(
                pmid, seccion, fuente, n_oracion, oracion, lex,
                max_menciones, cuenta, vistas))
            n_oracion += 1
    return salida


def topar_por_par(candidatos, max_por_par):
    """Deja a lo mas `max_por_par` ORACIONES DISTINTAS por (tf, target).

    El tope se aplica DESPUES de deduplicar, y se cuentan oraciones distintas,
    no filas. Defecto real que esto corrige: en `auditar_signo.py` el contador
    se incrementaba en la linea 232, antes de la dedup de las lineas 238-243,
    asi que una oracion citada por tres articulos consumia tres de los 40 cupos
    y luego se colapsaba a una; los pares que topaban quedaban con menos de 40
    oraciones distintas y se habian descartado oraciones nuevas que si habrian
    pasado.

    Las filas de una misma oracion citada por varios articulos se conservan
    todas: `red.py` las colapsa, pero necesita los PMIDs distintos para
    `n_articulos`, que es la senal de confianza mas barata que existe.
    """
    vistas = collections.defaultdict(set)
    salida, descartadas = [], 0
    for fila, pretok in candidatos:
        clave = (fila["tf"], fila["target"])
        oracion = fila["oracion_cruda"]
        conjunto = vistas[clave]
        if oracion not in conjunto:
            if len(conjunto) >= max_por_par:
                descartadas += 1
                continue
            conjunto.add(oracion)
        salida.append((fila, pretok))
    return salida, descartadas


def verificar(candidatos):
    """Invariantes del contrato. Devuelve un mensaje o None."""
    vistos_clave = {}
    vistos_id = {}
    vistos_texto = {}
    for i, (fila, pretokenizado) in enumerate(candidatos, 1):
        encontrados = MARCADO.findall(fila["text"])
        if sorted(e[0] for e in encontrados) != ["1", "2"]:
            return ("Fila %d: el marcado no cumple el formato del "
                    "entrenamiento. Ver seccion 3.1 del contrato." % i)
        marcadas = dict(encontrados)
        if (marcadas["1"] != fila["mencion_tf"]
                or marcadas["2"] != fila["mencion_target"]):
            return ("Fila %d: e1/e2 no corresponden a las menciones "
                    "registradas." % i)
        desnudo = _texto.normalizar_espacios(
            fila["text"].replace("<e1>", "").replace("</e1>", "")
                        .replace("<e2>", "").replace("</e2>", ""))
        if desnudo != pretokenizado:
            return "Fila %d: el marcado altero el texto." % i
        if len(fila["text"]) > MAX_TEXTO:
            return "Fila %d excede la ventana segura del modelo." % i

        clave = (fila["pmid"], fila["seccion"], fila["n_oracion"],
                 fila["tf"], fila["target"])
        if clave in vistos_clave:
            vistos_clave[clave] += 1
        else:
            vistos_clave[clave] = 1
        if fila["id_par"] in vistos_id:
            vistos_id[fila["id_par"]] += 1
        else:
            vistos_id[fila["id_par"]] = 1
        clave_texto = (fila["pmid"], fila["oracion_cruda"], fila["tf"],
                       fila["target"])
        vistos_texto.setdefault(clave_texto, set()).add(fila["fuente"])

    repetidos = sum(v - 1 for v in vistos_clave.values() if v > 1)
    if repetidos:
        return ("Hay %d pares duplicados: la seleccion de minima distancia "
                "corrio dos veces sobre la misma oracion." % repetidos)
    colisiones = sum(v - 1 for v in vistos_id.values() if v > 1)
    if colisiones:
        return "id_par colisiona: %d." % colisiones
    dobles = sum(1 for f in vistos_texto.values() if len(f) > 1)
    if dobles:
        return ("%d resumenes se leyeron dos veces (base y texto completo). "
                "Ver seccion 3.3." % dobles)
    return None


def escribir_jsonl(ruta, candidatos):
    """Escribe a `<ruta>.tmp` y renombra. Si algo falla antes, el archivo
    anterior queda intacto."""
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for fila, _ in candidatos:
            f.write(json.dumps(fila, ensure_ascii=False))
            f.write("\n")
    os.replace(tmp, ruta)


def escribir_json(ruta, objeto):
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, ruta)


def construir_informe(candidatos, cuenta, desconocidas, lex, docs_leidos,
                      topadas, argumentos, corrida_completa=True,
                      diccionario=None, vistas=None, operones=None):
    """El informe que se revisa a ojo ANTES de gastar una hora de CPU.

    `diccionario` es lo que `revisar_procedencia()` midio sobre la columna
    `fuente`; `vistas`, las entidades canonicas que aparecieron de verdad en
    el corpus; `operones`, los nombres de la tabla de operones. Los tres van
    escritos porque son la composicion de la entrada: sin ellos el informe
    describe la salida de una corrida cuya entrada nadie puede reconstruir.
    """
    por_seccion = collections.Counter()
    por_fuente = collections.Counter()
    por_redaccion = collections.Counter()
    por_tf = collections.Counter()
    por_target = collections.Counter()
    minusculas = 0
    autorregulacion = 0
    autorregulacion_misma_entidad = 0
    for fila, _ in candidatos:
        por_seccion[fila["seccion"]] += 1
        por_fuente[fila["fuente"]] += 1
        por_redaccion[fila["redaccion"]] += 1
        por_tf[fila["tf"]] += 1
        por_target[fila["target"]] += 1
        if fila["mencion_tf"][:1].islower():
            minusculas += 1
        if fila["autorregulacion"]:
            autorregulacion += 1
            if fila["tf"].lower() == fila["target"].lower():
                autorregulacion_misma_entidad += 1

    informe = collections.OrderedDict()
    informe["argumentos"] = argumentos
    # false = se corrio con --limite-docs, la invariante de escala no corrio y
    # ningun conteo de este archivo describe el corpus.
    informe["corrida_completa"] = corrida_completa
    informe["documentos"] = docs_leidos
    informe["pares"] = len(candidatos)
    informe["por_seccion"] = collections.OrderedDict(
        sorted(por_seccion.items()))
    informe["por_fuente"] = collections.OrderedDict(sorted(por_fuente.items()))
    informe["por_redaccion"] = collections.OrderedDict(
        sorted(por_redaccion.items()))
    informe["oraciones"] = collections.OrderedDict(sorted(cuenta.items()))
    informe["pares_topados"] = topadas
    # Las dos formas de autorregulacion por separado. Juntas no se pueden
    # leer: `X -> x` es la que el patron de oro nombra, y el operon que
    # contiene al propio regulador (`PhoB -> phoBR`) es otra cosa.
    informe["autorregulacion"] = autorregulacion
    informe["autorregulacion_misma_entidad"] = autorregulacion_misma_entidad
    informe["autorregulacion_por_operon"] = (autorregulacion
                                             - autorregulacion_misma_entidad)
    # Los campos `tf` y `target` llevan la forma canonica, pero `text` marca la
    # superficie literal como el articulo la escribio: reescribir `mexT` a
    # `MexT` dentro de la oracion fabricaria una frase que nadie publico y
    # destruiria el rastro de auditoria. Este contador mide el efecto, y su
    # relevancia depende de `do_lower_case`, que resuelve la etapa 3.
    informe["mencion_tf_en_minuscula"] = minusculas
    # La composicion del diccionario que produjo estos pares: de donde dice
    # cada fila que salio, y --lo que no se puede escribir en una columna--
    # cuantas de sus entidades aparecen de verdad en el corpus.
    if diccionario is not None:
        informe["diccionario"] = diccionario
    if vistas is not None:
        # Los dos numeros, y separados. El primero se infla solo con locus
        # tags, que se generan con un bucle; el segundo es el que mide si el
        # diccionario sabe COMO se llaman los genes. Ver
        # revisar_lo_que_el_diccionario_encuentra().
        informe["entidades_del_diccionario"] = len(lex)
        informe["entidades_vistas_en_el_corpus"] = len(vistas)
        informe["entidades_vistas_por_un_nombre"] = sum(
            1 for con_nombre in vistas.values() if con_nombre)
    # Los operones que la tabla deriva del genoma incluyen todas las
    # sub-corridas contiguas de longitud >= 2 (seccion 2, salida B), asi que
    # trae nombres sin uso en la literatura junto a los que si se escriben.
    # Medido sobre los 918 textos completos: 244 de los 3030 aparecen alguna
    # vez y 2786 no aparecen nunca --`mexB-oprM`, el ejemplo de siempre, sale
    # con cero--. No se filtran; el numero se publica para que la decision se
    # pueda revisar con evidencia y no de memoria. La razon esta en el
    # docstring del modulo.
    if operones is not None and vistas is not None:
        vistos = sorted(o for o in operones if o in vistas)
        informe["operones_de_la_tabla"] = len(operones)
        informe["operones_vistos_en_el_corpus"] = len(vistos)
        informe["operones_vistos_top"] = vistos[:60]
    informe["menciones_ambiguas"] = sum(lex.ambiguas.values())
    informe["menciones_ambiguas_top"] = collections.OrderedDict(
        lex.ambiguas.most_common(30))
    informe["operones_sinteticos"] = collections.OrderedDict(
        lex.sinteticos.most_common(30))
    informe["top_tf"] = collections.OrderedDict(por_tf.most_common(30))
    informe["top_target"] = collections.OrderedDict(por_target.most_common(30))
    informe["etiquetas_desconocidas"] = collections.OrderedDict(
        sorted(desconocidas.items(), key=lambda kv: (-kv[1], kv[0]))[:60])
    informe["caracteres_en_otra"] = sum(desconocidas.values())
    return informe


def main():
    ap = argparse.ArgumentParser(
        description="Etapa 2: pares candidatos (TF, blanco) del corpus.")
    ap.add_argument("--db", default="datos/grn.db")
    ap.add_argument("--fulltext", default="datos/fulltext/xml")
    ap.add_argument("--genes", default="etapa2/genes_pao1.tsv")
    ap.add_argument("--operones", default="etapa2/operones_pao1.tsv")
    ap.add_argument("--secciones", default="grn_bronce/secciones.tsv")
    ap.add_argument("--salida", default="datos_etapa2/pares.jsonl")
    ap.add_argument("--informe", default="datos_etapa2/pares_informe.json")
    ap.add_argument("--max-menciones", type=int, default=8,
                    dest="max_menciones",
                    help="Descarta la oracion si tiene mas entidades canonicas "
                         "distintas.")
    ap.add_argument("--max-por-par", type=int, default=200, dest="max_por_par",
                    help="Tope de oraciones distintas por (tf, blanco).")
    ap.add_argument("--incluir-otras", action="store_true",
                    dest="incluir_otras",
                    help="Mete la clase de seccion 'otra'.")
    ap.add_argument("--limite-docs", type=int, default=0, dest="limite_docs",
                    help="Solo para depurar. Un corpus recortado no puede "
                         "cumplir la invariante de escala, asi que con este "
                         "flag la salida queda marcada como incompleta.")
    args = ap.parse_args()

    if not os.path.isfile(args.genes):
        sys.exit("El diccionario no esta construido. Corre antes "
                 "etapa2/construir_diccionario.py.")
    filas_genes = leer_diccionario(args.genes)
    n_genes = len(filas_genes)
    if n_genes < 5000:
        sys.exit("El diccionario no esta construido. Corre antes "
                 "etapa2/construir_diccionario.py.")
    if not os.path.isfile(args.operones):
        sys.exit("Falta %s. Corre antes etapa2/construir_diccionario.py."
                 % args.operones)
    # Antes de leer un solo documento: si la procedencia es circular, no hay
    # corrida que valga y no se ha gastado nada.
    fuentes, fuentes_desconocidas = revisar_procedencia(filas_genes,
                                                        args.genes)

    lex = _lexico.Lexico.cargar(args.genes, args.operones)
    nombres_operones = set(
        fila["operon"] for fila in _lexico._leer_tsv(
            args.operones, _lexico.COLUMNAS_OPERONES) if fila["operon"])
    clases = _texto.cargar_clases(args.secciones)
    print("Diccionario: %d entidades canonicas (%d filas de genes, %d "
          "operones), procedencias %s."
          % (len(lex), n_genes, len(nombres_operones),
             ", ".join("%s=%d" % kv for kv in fuentes.items())))

    indice = indice_fulltext(args.fulltext)
    documentos = leer_documentos(args.db)
    if args.limite_docs:
        documentos = documentos[:args.limite_docs]
    print("Corpus: %d documentos, %d con texto completo.\n"
          % (len(documentos), len(indice)))

    cuenta = collections.Counter()
    desconocidas = collections.Counter()
    # {entidad canonica: se vio escrita con un nombre y no con su locus tag}
    vistas = {}
    candidatos = []
    sin_resumen_en_txt = 0
    for i, (pmid, abstract) in enumerate(documentos, 1):
        ruta = indice.get(pmid)
        piezas = piezas_de_documento(
            pmid, abstract, ruta, clases, args.incluir_otras, desconocidas)
        if ruta is not None and abstract.strip() and not any(
                c == "abstract" for c, _, _ in piezas):
            # El .txt no trae `## ABSTRACT`. Medido: pasa en 4 de 918. No se
            # cae a la base, porque la regla de la seccion 3.3 es que el
            # resumen de un documento con texto completo sale del .txt; se
            # cuenta para que la perdida sea visible.
            sin_resumen_en_txt += 1
        candidatos.extend(candidatos_de_documento(
            pmid, piezas, lex, args.max_menciones, cuenta, vistas))
        if i % 200 == 0:
            print("  %d/%d documentos, %d candidatos"
                  % (i, len(documentos), len(candidatos)))

    cuenta["resumenes_sin_abstract_en_txt"] = sin_resumen_en_txt
    candidatos, topadas = topar_por_par(candidatos, args.max_por_par)

    problema = verificar(candidatos)
    if problema:
        sys.exit(problema)

    # La invariante de escala solo se salta cuando el corpus viene recortado
    # con --limite-docs, y no por una bandera propia.
    #
    # Habia una, `--sin-invariante-escala`, que no esta en el contrato y que
    # nada obligaba a combinar con --limite-docs: su ayuda decia "solo tiene
    # sentido con --limite-docs" y ahi acababa la garantia. Demostrado: con un
    # diccionario de 5700 filas de las que solo 3 traian simbolo, la bandera
    # dejo escribir pares.jsonl con 11 pares sobre el corpus COMPLETO sin una
    # queja; ese archivo fluye a la etapa 3 y sale una red entera construida
    # sobre nada. La invariante existe justamente para ser el aviso barato de
    # "revisa el diccionario antes de gastar una hora de GPU", asi que no
    # puede tener un interruptor de uso general.
    corrida_completa = not args.limite_docs
    if corrida_completa and not (MIN_PARES <= len(candidatos) <= MAX_PARES):
        sys.exit("Sali con %d pares candidatos; la escala esperada es del "
                 "orden de 100 mil. Revisa el diccionario antes de gastar una "
                 "hora de GPU." % len(candidatos))
    # Va DESPUES de la invariante de escala a proposito: un corpus vacio o un
    # diccionario de tres genes fallan las dos, y el mensaje util ahi es el de
    # la escala. Esta habla de otra cosa --de que el diccionario no sea el
    # genoma-- y su caso propio es el que si produce cien mil pares.
    por_nombre = set(idc for idc, con_nombre in vistas.items() if con_nombre)
    if corrida_completa:
        revisar_lo_que_el_diccionario_encuentra(por_nombre, len(lex),
                                                args.genes)
    if not corrida_completa:
        print("\nAVISO: corrida de depuracion sobre %d documentos. La "
              "invariante de escala no corrio, asi que este pares.jsonl no "
              "es defendible como corpus: el informe lo marca con "
              "corrida_completa=false." % args.limite_docs)

    escribir_jsonl(args.salida, candidatos)
    argumentos = collections.OrderedDict(sorted(vars(args).items()))
    diccionario = collections.OrderedDict([
        ("ruta", args.genes),
        ("filas", n_genes),
        ("fuentes", fuentes),
        ("fuentes_desconocidas", collections.OrderedDict(
            sorted(fuentes_desconocidas.items()))),
    ])
    informe = construir_informe(candidatos, cuenta, desconocidas, lex,
                                len(documentos), topadas, argumentos,
                                corrida_completa, diccionario, vistas,
                                nombres_operones)
    escribir_json(args.informe, informe)

    print("\n%d pares candidatos -> %s" % (len(candidatos), args.salida))
    print("informe -> %s\n" % args.informe)
    for clave in ("por_fuente", "por_seccion", "por_redaccion"):
        print("%s:" % clave)
        for k, v in informe[clave].items():
            print("  %-24s %8d" % (k, v))
    print("\noraciones:")
    for k, v in informe["oraciones"].items():
        print("  %-34s %8d" % (k, v))
    print("\nentidades del diccionario vistas en el corpus: %d de %d "
          "(%d por un nombre y no por su locus tag; el minimo es %d)"
          % (informe["entidades_vistas_en_el_corpus"],
             informe["entidades_del_diccionario"],
             informe["entidades_vistas_por_un_nombre"],
             MINIMO_ENTIDADES_VISTAS))
    print("operones de la tabla vistos en el corpus: %d de %d"
          % (informe["operones_vistos_en_el_corpus"],
             informe["operones_de_la_tabla"]))
    print("menciones ambiguas descartadas: %d"
          % informe["menciones_ambiguas"])
    print("mencion de TF con inicial minuscula: %d de %d"
          % (informe["mencion_tf_en_minuscula"], len(candidatos)))
    print("caracteres que cayeron en la clase 'otra': %d"
          % informe["caracteres_en_otra"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
