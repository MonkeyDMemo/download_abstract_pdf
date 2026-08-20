#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compara la red inferida contra el patrón de oro de *P. aeruginosa*.

Etapa 5 del contrato de datos. Es uno de los dos únicos scripts autorizados a
abrir `etapa2/oro_pseudomonas.tsv` (§0.4).

LO QUE MIDE Y LO QUE NO
-----------------------
Mide **exhaustividad** y **acierto de signo**. NO mide precisión, y el script
se niega a calcularla: el patrón cubre 6 subsistemas, así que una arista fuera
de ellos no está mal, simplemente no está en la lista. Ver `AVISO` más abajo,
que se imprime en la terminal, encabeza el TSV y viaja en el JSON.

LOS DOS DENOMINADORES
---------------------
Se reportan siempre los dos, etiquetados:

- **crudo (190)**: todas las filas del patrón.
- **honesto**: el crudo menos las filas que el corpus no puede sostener: las no
  atestiguadas (el corpus no las contiene), las de `signo=regulates` (la propia
  literatura no resuelve el signo) y las marcadas como *en disputa* (el corpus
  se contradice a sí mismo).

`etapa2/README.md` y `docs/informe-seminario-1.md` citan ~169 para el honesto.
Ese número sale de restar 9 + 6 + 5 suponiendo que las tres categorías no se
solapan, y sí se solapan: `MexT -> mexT` es a la vez no atestiguada y
`regulates`, y `RhlR -> rpoS` es a la vez `regulates` y la única fila que el
TSV marca como en disputa. Este script **no copia el 169**: lo calcula de la
propia tabla, publica cada categoría por separado y avisa cuando el número
calculado difiere del documentado. Un denominador que no se puede reconstruir
desde el dato es un número de fe.

LA LINEA BASE ALEATORIA
-----------------------
La exhaustividad de este archivo **se satura por azar**, y hasta que existió
este contrapeso nada lo delataba: con predicciones COMPLETAMENTE aleatorias
sobre el corpus entero el script publicaba 95.5 % de exhaustividad (105 de
110). La razón es estructural: un par del oro suele traer muchas oraciones
candidatas y basta que una salga con una clase distinta de `no_relation` para
darlo por recuperado.

Por eso cada corrida publica, al lado de la cifra real, **qué daría asignar
las clases al azar sobre exactamente los mismos candidatos**, con la semilla
fija de `--semilla`. El acierto de signo es el que puede despegar, y es el que
decide el código de salida. Pero **su línea base no es 50 %**: ver más abajo.

- **0** — el acierto de signo despega de sus DOS líneas base (p <= 0.05 en las
  dos) y el vocabulario del pipeline no está explicado por el del oro.
- **2** — no despega de alguna de las dos, no hay ninguna fila con signo
  comparable, o el vocabulario huele a copiado del oro. Los dos archivos
  **sí** se escriben: sin el detalle fila por fila no hay forma de
  diagnosticar. El código 1 sigue queriendo decir "la entrada no sirve y no
  escribo nada".
- La exhaustividad **no** decide el código de salida. Un guardián sobre ella
  saltaría incluso con un pipeline perfecto, y un guardián que salta siempre
  es tan inútil como uno que no salta nunca: este proyecto ya se llevó las dos
  versiones de ese error.

LA SEGUNDA LINEA BASE: LA CLASE MAYORITARIA
-------------------------------------------
El acierto de signo se compara además contra **la clase mayoritaria del
subconjunto que se está evaluando**, con una binomial exacta. Sin ella, un
clasificador constante que contesta siempre `activates` publicaba ACIERTO DE
SIGNO 69.8 % (97 de 139) --que es exactamente la proporción de `activates` de
esas 139 filas-- y este archivo lo certificaba con «se distingue del azar
(p = 0.005). Codigo 0». La línea base aleatoria no lo veía porque sortea las
dos clases equiprobables y da ~50 % pase lo que pase, mientras el oro y los
umbrales de `red.py` (activates 0.65, represses 0.70) dejan el reparto
desequilibrado. Las dos líneas base se publican y el código 0 exige despegar
de las dos.

DE DONDE SALIO EL DICCIONARIO
-----------------------------
Tres guardianes, y **el que manda mide contenido, no etiquetas**:

1. **Procedencia** (etiqueta): `genes_pao1.tsv` declara fila por fila de dónde
   salió y `oro` no es un valor válido (§2). Se puede mentir escribiendo
   `refseq`.
2. **Entidades útiles** (proxy de tamaño): filas con alguna superficie además
   del locus tag. Se puede satisfacer rellenando con símbolos inventados.
3. **Sustancia** (contenido, ver `medir_sustancia`): qué fracción de los pares
   que el pipeline propuso **desde el corpus** cae entera dentro del
   vocabulario que el propio patrón de oro escribe. Un diccionario copiado del
   oro no puede proponer casi nada más; uno genuino gasta la mayor parte de su
   trabajo en pares que el oro no nombra. Medido sobre el corpus completo:
   diccionario real 25.6 %, diccionario copiado del oro 66.1 %.

Los dos primeros preguntan qué dice ser el diccionario. El tercero mide qué
es. Los tres corren, porque los dos primeros son baratos y dan un mensaje más
concreto cuando aciertan.

LAS PROBABILIDADES TIENEN QUE SUMAR 1
-------------------------------------
La invariante de §4 vivía solo en `clasificar.py`, que es el único archivo que
necesita `torch` y por tanto el que menos gente corre. Si existe el
`predicciones.jsonl` de la corrida, este archivo la vuelve a comprobar antes
de creerse ninguna columna derivada de esas probabilidades. Medido: 65216
filas con las cuatro clases a 0.99 producían 9608 aristas con `confianza`
0.9900 --una columna que el contrato define como una probabilidad media-- y
EXHAUSTIVIDAD 95.1 % con código 0.

EMPAREJAMIENTO POR NOMBRE
-------------------------
El mismo gen aparece con varios nombres, así que además del nombre de la fila
se aceptan:

1. Los **alias anclados** de la columna `alias`. Solo se toma un alias cuando
   la cadena de equivalencia nombra explícitamente uno de los dos extremos de
   la fila (`MexR = NalB = PA0424`). Una cadena que nombra a los dos extremos
   se descarta entera por ambigua: en `adcA = PA4843 = AmrZ dependent cyclase A`
   el "AmrZ" final es prosa, y anclarla al TF convertiría a `adcA` en alias del
   propio TF.
2. La **equivalencia operón-gen**, y es asimétrica a propósito. El nombre de
   la REFERENCIA (el oro, CollecTF) se expande con `operones_pao1.tsv` y
   también mecánicamente (`mexAB-oprM` -> mexA, mexB, oprM): son tablas
   versionadas y escritas a mano, y el pipeline no puede fabricar sus nombres.
   El nombre que produjo el PIPELINE se expande **solo** con la tabla, que es
   lo único que §6.3 autoriza. Con la expansión mecánica de los dos lados, una
   sola arista inventada `LasR -> lasRIAB` --nombre que `lexico` acuña desde el
   texto-- contaba como recuperación de tres filas del oro a la vez.
   Esto es normalización de evaluación, no de construcción (§6.3): ocurre en
   el evaluador, después de que el pipeline ya decidió.

Uso:
    python etapa2/evaluar_oro.py --red datos_etapa2/red.tsv \
        --pares datos_etapa2/pares.jsonl --genes etapa2/genes_pao1.tsv
"""

import argparse
import collections
import datetime
import json
import math
import os
import random
import re
import sys


# ---------------------------------------------------------------------------
# Constantes del contrato
# ---------------------------------------------------------------------------

# §6.1. Se imprime, se escribe en el campo `aviso` del JSON y encabeza el TSV.
AVISO = (
    "La evaluación contra oro_pseudomonas.tsv da EXHAUSTIVIDAD y ACIERTO DE "
    "SIGNO, y NO da precisión. El patrón de oro cubre 6 subsistemas (Bombas "
    "RND, Quorum sensing, Factores sigma, Hierro y sideróforos, Biopelícula "
    "c-di-GMP, Dos componentes y T3SS) con 190 relaciones, 55 TFs y 110 "
    "blancos. Una arista fuera de esos subsistemas no está mal: simplemente no "
    "está en la lista. Calcular precisión contra el oro contaría como falso "
    "positivo cada arista correcta que el oro no cubre, y el número sería una "
    "calumnia contra el pipeline, no una medición."
)

COLUMNAS_ORO = ["tf", "blanco", "signo", "certeza_dominio", "subsistema",
                "alias", "atestiguado", "n_articulos", "pmids", "oracion"]
FILAS_ORO = 190

COLUMNAS_RED = ["tf", "blanco", "signo", "conflicto", "n_evidencias",
                "n_activates", "n_represses", "n_regulates", "n_articulos",
                "confianza", "autorregulacion", "secciones", "pmids",
                "oracion_representativa"]

COLUMNAS_GENES = ["locus_tag", "simbolo", "alias", "tipo", "producto", "es_tf",
                  "fuente_tf", "fuente", "sensible_mayusculas"]

COLUMNAS_OPERONES = ["operon", "miembros", "locus_tags", "fuente"]

COLUMNAS_COLLECTF = ["tf", "blanco", "experimento", "pmids", "en_corpus"]

# §2 salida A: la columna `fuente` del diccionario declara fila por fila de
# dónde salió, y **`oro` no es un valor válido**. Ese es el guardián de
# circularidad de este archivo. El anterior contaba LÍNEAS del TSV y exigía
# además cobertura del 100 %, así que rellenar el archivo con filas de símbolo
# vacío hasta 5700 lo desactivaba sin tocar nada de lo que decía vigilar:
# medido, un genes_pao1.tsv con 785 filas copiadas del patrón y 4915 de relleno
# pasaba y publicaba exhaustividad 81.7 %. Es el mismo patrón del verificador
# de fuga que medía con la clave del agrupamiento: la condición elegida no
# podía dispararse en el caso que quería atrapar.
FUENTES_VALIDAS = ("refseq", "kegg", "uniprot", "uniprot_especie", "manual")

# Cualquier procedencia que nombre al patrón o a la auditoría de signo. Se
# compara en minúsculas y por subcadena, así que `oro`, `ORO` y las dos formas
# largas con el nombre del archivo caen aquí igual. (El nombre literal del
# archivo de la auditoría no se escribe: test_contaminacion.py lo prohíbe
# fuera de evaluar_signo.py, y con razón.)
FUENTES_DEL_ORO = ("oro", "auditoria", "patron", "patrón")

# Lo que el conteo de filas pretendía comprobar y no comprobaba: entidades que
# el reconocedor puede encontrar en la prosa. Una fila cuyo único nombre es su
# locus tag casi nunca aparece escrita en un artículo, y una fila con el
# símbolo vacío no aparece nunca.
MINIMO_ENTIDADES_UTILES = 1000

# El tercer guardián, y el único que mira contenido en vez de etiquetas: qué
# fracción de los pares distintos que el pipeline propuso DESDE EL CORPUS cae
# entera dentro del vocabulario que el patrón de oro escribe. Un diccionario
# copiado del oro solo puede reconocer en la prosa los nombres que copió, así
# que casi todo su trabajo cae dentro; uno genuino conoce 5642 genes contra los
# 110 blancos del oro y gasta la mayor parte de su trabajo fuera.
#
# Los dos números son medidos sobre el corpus completo (918 textos, 2354
# resúmenes), no elegidos a ojo:
#
#   diccionario real (etapa2/genes_pao1.tsv)   2528 de 9876 pares = 25.6 %
#   diccionario copiado del oro, fuente=refseq,
#   relleno con símbolos inventados            2339 de 3541 pares = 66.1 %
#
# Ese segundo es el exploit literal que pasaba antes: publicaba cobertura
# 100.0 %, EXHAUSTIVIDAD 95.3 % y ACIERTO DE SIGNO 98.8 % con código 0, porque
# los otros dos guardianes miran la columna `fuente` y un conteo de filas, y
# las dos cosas se falsifican escribiendo texto en un TSV.
#
# Es **graduado a propósito**: la cifra se publica siempre, porque un
# diccionario 90 % legítimo con un 10 % copiado del oro también contamina y un
# umbral de todo o nada no lo vería. El aviso y el código 2 llegan antes que la
# muerte, para que la contaminación parcial se lea en la salida en vez de
# aparecer solo cuando ya es total.
UMBRAL_CIRCULARIDAD = 0.60
UMBRAL_AVISO_CIRCULARIDAD = 0.40

# §4: las cuatro clases del checkpoint y la tolerancia con la que el contrato
# exige que sumen 1.
ETIQUETAS = ("activates", "no_relation", "regulates", "represses")
TOLERANCIA_SOFTMAX = 1e-3

# Contrapeso de la exhaustividad (ver linea_base_aleatoria más abajo).
SEMILLA_POR_OMISION = 12345
REPETICIONES_POR_OMISION = 200
MAYORIA_POR_OMISION = 0.66
ALFA = 0.05

# Las 16 primeras son las del contrato §6, en su orden. Las tres últimas son
# añadidas. Las dos del denominador, porque sin una marca por fila el
# denominador honesto del JSON no se puede reconstruir leyendo el TSV, que es
# justo lo que se le pide a este archivo. `n_candidatos`, porque sin él la
# línea base aleatoria tampoco se puede reproducir: es el número de oraciones
# candidatas que sostienen la fila, y de él depende cuánto de la exhaustividad
# publicada lo da el azar.
COLUMNAS_SALIDA = ["tf", "blanco", "signo_oro", "certeza_dominio", "subsistema",
                   "atestiguado", "resuelto_tf", "resuelto_blanco",
                   "hubo_candidato", "coincidencia", "signo_red", "conflicto",
                   "n_evidencias", "n_articulos", "confianza", "veredicto",
                   "en_denominador_honesto", "motivo_exclusion",
                   "n_candidatos"]

SIGNOS = ("activates", "represses", "regulates")

# El honesto documentado en etapa2/README.md ("El denominador honesto son ~169,
# no 190") y en docs/informe-seminario-1.md. Se guarda para poder contrastar,
# nunca para usarlo como denominador.
HONESTO_DOCUMENTADO = 169
DISPUTADAS_DOCUMENTADAS = 5

# Banderas que este script se niega a aceptar (§6.1). Se revisan sobre argv
# antes de argparse: argparse contestaría "unrecognized arguments" y quien la
# pidió se quedaría sin saber por qué no existe.
PROHIBIDAS = ("precision", "precisión", "f1", "vp", "fp", "ppv",
              "falsos-positivos", "falsos_positivos",
              "verdaderos-positivos", "verdaderos_positivos")


# ---------------------------------------------------------------------------
# Utilidades de formato
# ---------------------------------------------------------------------------

def normalizar_espacios(s):
    return " ".join(s.split())


def limpiar_campo(s):
    """Ningún campo TSV puede llevar tabulador ni salto de línea (§0.2)."""
    return normalizar_espacios(s.replace("\t", " ").replace("\n", " "))


def leer_tsv(ruta, columnas, nombre):
    """Lee un TSV del contrato: sin comillas, sin campos multilínea.

    No se usa el módulo csv a propósito. El campo `oracion` del oro y el
    `oracion_representativa` de la red son prosa científica, y csv con sus
    reglas de comillas trataría un campo que empiece con comilla doble como
    campo entrecomillado y se comería el texto. El contrato garantiza que
    ningún campo lleva tabulador, así que partir por tabulador es exacto.
    """
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s (%s)." % (ruta, nombre))
    with open(ruta, encoding="utf-8-sig") as f:
        crudas = f.read().split("\n")
    lineas = [ln for ln in crudas if ln.strip() and not ln.startswith("#")]
    if not lineas:
        sys.exit("%s está vacío (%s)." % (ruta, nombre))
    cabecera = lineas[0].rstrip("\r").split("\t")
    if columnas is not None and cabecera != columnas:
        sys.exit("%s no tiene el encabezado esperado.\n  esperado: %s\n"
                 "  leído:    %s" % (ruta, "\t".join(columnas),
                                     "\t".join(cabecera)))
    filas = []
    for i, ln in enumerate(lineas[1:], start=2):
        campos = ln.rstrip("\r").split("\t")
        if len(campos) != len(cabecera):
            sys.exit("%s línea %d: %d columnas, se esperaban %d."
                     % (ruta, i, len(campos), len(cabecera)))
        filas.append(dict(zip(cabecera, campos)))
    return filas


def escribir_tsv(ruta, columnas, filas, comentario=None):
    """Escribe a .tmp y renombra: nadie lee una salida a medio escribir (§0.3)."""
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
            f.write("\t".join(limpiar_campo(str(fila.get(c, "")))
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
    """Toda métrica viaja con su numerador y su denominador a la vista."""
    return {"n": n, "d": d, "tasa": round(float(n) / d, 4) if d else None}


def bool_txt(v):
    return "true" if v else "false"


# ---------------------------------------------------------------------------
# Nombres, alias y operones
# ---------------------------------------------------------------------------

IDENT = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
LOCUS = re.compile(r"^PA\d{4}(\.\d)?$", re.I)
RANGO = re.compile(r"^PA(\d{4})-PA(\d{4})$", re.I)
GRUPO = re.compile(r"[A-Z][0-9]*")
CONCATENADO = re.compile(r"^([a-z]{2,4})((?:[A-Z][0-9]*)+)$")
LETRA = re.compile(r"^([A-Z])$")


def clave(nombre):
    """Los nombres se comparan en minúsculas.

    `mexT` (gen) y `MexT` (proteína) son la misma entidad, y el patrón de oro
    usa una forma en la columna tf y la otra en la columna blanco. Distinguir
    por mayúscula aquí perdería emparejamientos sin ganar nada: la mayúscula es
    convención de nomenclatura, no identidad.
    """
    return nombre.strip().lower()


def parece_identificador(tok):
    """Filtra la prosa que se cuela en las cadenas de equivalencia.

    "AlgP = proteina tipo histona" produciría el alias `proteina`. Los símbolos
    bacterianos son locus tags, llevan una mayúscula después de la primera
    letra, llevan dígito, o son de tres o cuatro letras minúsculas (`anr`,
    `pel`, `psl`). El resto es descripción para humanos.
    """
    if LOCUS.match(tok):
        return True
    if any(c.isdigit() for c in tok):
        return True
    if any(c.isupper() for c in tok[1:]):
        return True
    return tok.islower() and len(tok) <= 4


def expandir_rango(tok):
    """PA0425-PA0427 -> PA0425, PA0426, PA0427 (y al revés, PA2019-PA2018)."""
    m = RANGO.match(tok)
    if not m:
        return []
    a, b = int(m.group(1)), int(m.group(2))
    if abs(a - b) > 40:      # un rango enorme es un error de captura, no un operón
        return []
    return ["PA%04d" % n for n in range(min(a, b), max(a, b) + 1)]


def miembros_operon(nombre):
    """Expansión mecánica del nombre de un operón a sus genes.

    mexAB-oprM -> mexA, mexB, oprM ; pqsABCDE -> pqsA..pqsE ;
    phzA-G -> phzA..phzG ; narK1K2GHJI -> narK1, narK2, narG, narH, narJ, narI.

    Devuelve [] cuando el nombre no se descompone (`pel`, `psl`, `algD`): un
    solo miembro no es un operón para efectos de emparejar.
    """
    fuera = []
    prefijo = None
    for parte in nombre.split("-"):
        m = CONCATENADO.match(parte)
        if m:
            prefijo = m.group(1)
            for g in GRUPO.findall(m.group(2)):
                fuera.append(prefijo + g)
            continue
        m = LETRA.match(parte)
        if m and fuera and prefijo and fuera[-1][:-1] == prefijo:
            # phzA-G: la letra suelta cierra un rango alfabético sobre el
            # prefijo anterior.
            a, b = fuera[-1][-1], m.group(1)
            if a.isupper() and ord(b) > ord(a):
                for c in range(ord(a) + 1, ord(b) + 1):
                    fuera.append(prefijo + chr(c))
                continue
        fuera.append(parte)
        prefijo = None
    return fuera if len(fuera) > 1 else []


def cadenas_de_equivalencia(campo):
    """Trocea la columna `alias` en cadenas de nombres equivalentes.

    Dos formas, las únicas que el patrón usa de manera regular:
      "MexR = NalB = PA0424, familia MarR"   -> [MexR, NalB, PA0424]
      "ANR, anr"                             -> [ANR, anr]

    En una cadena con '=', de cada tramo se toma el último identificador antes
    del '=' y el primero después: "operon pel, pelA = PA3064" enlaza pelA con
    PA3064, no la palabra "operon" con PA3064.
    """
    fuera = []
    for segmento in campo.split(";"):
        tramos = segmento.split("=")
        if len(tramos) >= 2:
            cadena = []
            for i, tramo in enumerate(tramos):
                toks = IDENT.findall(tramo)
                if not toks:
                    continue
                cadena.append(toks[0] if i == len(tramos) - 1 else toks[-1])
            if len(cadena) >= 2:
                fuera.append(cadena)
            continue
        lista = []
        for trozo in re.split(r"[,/]", segmento):
            trozo = trozo.strip()
            toks = IDENT.findall(trozo)
            # Solo listas de nombres pelados: "ANR, anr" sí, "homologo de FNR" no.
            if len(toks) == 1 and toks[0] == trozo:
                lista.append(toks[0])
        if len(lista) >= 2:
            fuera.append(lista)
    return fuera


def alias_anclados(campo, nombre_tf, nombre_blanco):
    """(alias_del_tf, alias_del_blanco, cadenas_ambiguas) desde `alias`.

    Una cadena solo aporta alias si nombra exactamente a uno de los dos
    extremos. Si nombra a los dos, se descarta: no hay forma de saber cuál de
    los otros nombres pertenece a cuál, y equivocarse convierte al blanco en
    alias del TF.
    """
    ktf, kbl = clave(nombre_tf), clave(nombre_blanco)
    alias_tf, alias_bl = set(), set()
    ambiguas = 0
    for cadena in cadenas_de_equivalencia(campo):
        bajas = set(clave(c) for c in cadena)
        toca_tf, toca_bl = ktf in bajas, kbl in bajas
        if toca_tf and toca_bl:
            ambiguas += 1
            continue
        if not toca_tf and not toca_bl:
            continue
        destino = alias_tf if toca_tf else alias_bl
        ancla = ktf if toca_tf else kbl
        for tok in cadena:
            if clave(tok) == ancla:
                continue
            rango = expandir_rango(tok)
            if rango:
                # Se guarda la expansión, no "PA0425-PA0427": ninguna arista se
                # llama así.
                destino.update(clave(x) for x in rango)
            elif parece_identificador(tok):
                destino.add(clave(tok))
    return alias_tf, alias_bl, ambiguas


# ---------------------------------------------------------------------------
# Carga de las entradas
# ---------------------------------------------------------------------------

def cargar_oro(ruta):
    filas = leer_tsv(ruta, COLUMNAS_ORO, "patrón de oro")
    if len(filas) != FILAS_ORO:
        sys.exit("oro_pseudomonas.tsv no tiene la forma esperada "
                 "(190 filas, 10 columnas); leí %d filas." % len(filas))
    return filas


def cargar_red(ruta):
    filas = leer_tsv(ruta, COLUMNAS_RED, "red inferida")
    red = {}
    for fila in filas:
        red[(clave(fila["tf"]), clave(fila["blanco"]))] = fila
    return filas, red


def cargar_pares(ruta, operones):
    """(índice, n candidatos, pares distintos, entidades) desde pares.jsonl.

    El índice es tf -> [(target, miembros del operón, n oraciones candidatas)].

    Se guarda el par distinto y **cuántas oraciones lo sostienen**. El conteo
    no es adorno: es lo que la línea base aleatoria necesita para sortear sobre
    exactamente los mismos candidatos, y es también la explicación de por qué
    la exhaustividad se satura. Un par del oro suele traer muchas oraciones
    candidatas, y basta que UNA salga con una clase distinta de `no_relation`
    para que el par cuente como recuperado.
    """
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s. Corre antes etapa2/extraer_pares.py: sin "
                 "pares.jsonl no puedo distinguir 'nunca hubo candidato' de "
                 "'la red lo filtró', y esa diferencia es la mitad de lo que "
                 "este informe existe para decir." % ruta)
    vistos = collections.defaultdict(collections.Counter)
    entidades = collections.Counter()
    expansion, n = {}, 0
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            d = json.loads(linea)
            ktf, ktarget = clave(d["tf"]), clave(d["target"])
            vistos[ktf][ktarget] += 1
            entidades[ktf] += 1
            entidades[ktarget] += 1
            if ktarget not in expansion:
                expansion[ktarget] = miembros_de_tabla(d["target"], operones)
            n += 1
    indice = {}
    for ktf, cuenta in vistos.items():
        indice[ktf] = [(t, expansion[t], cuenta[t]) for t in sorted(cuenta)]
    # Los pares DISTINTOS, no las filas: la sustancia de un diccionario es
    # cuántas relaciones distintas sabe proponer, no cuántas veces repite las
    # mismas. Con filas, un solo par citado diez mil veces pesaría como diez
    # mil pares.
    pares = set((ktf, kt) for ktf, cuenta in vistos.items() for kt in cuenta)
    return indice, n, pares, entidades


SUSTANCIA_QUE_ES = (
    "De todos los pares (TF, blanco) DISTINTOS que el pipeline propuso "
    "leyendo el corpus, qué fracción tiene sus dos extremos dentro del "
    "vocabulario que el propio patrón de oro escribe. Es la única medida de "
    "circularidad que mira contenido: no pregunta de dónde dice el "
    "diccionario que salió --eso es una columna de texto y se escribe lo que "
    "sea-- sino qué sabe encontrar en la prosa. Un diccionario copiado del "
    "oro solo reconoce lo que copió; uno genuino tiene 5642 genes contra los "
    "110 blancos del oro y gasta la mayor parte de su trabajo en pares que el "
    "oro no nombra. Medido sobre el corpus completo: diccionario real 25.6 %, "
    "diccionario copiado del oro 66.1 %."
)

SUSTANCIA_ES_GRADUADA = (
    "La fracción se publica siempre, aunque no dispare nada. Un umbral de "
    "todo o nada no vería un diccionario 90 % legítimo con un 10 % copiado "
    "del oro, que también contamina: lo que se ve en ese caso es la fracción "
    "subiendo, y por eso el número va en el informe y en la terminal en vez "
    "de quedarse dentro de un `if`."
)


def vocabulario_del_oro(oro):
    """Todo nombre que el patrón de oro escribe, y lo que se deriva de ellos.

    Es lo que un copista podría llevarse del archivo: las dos columnas de
    nombres, cada identificador de la columna `alias` (con los rangos
    PA0425-PA0427 ya expandidos) y la expansión mecánica de los operones
    (`mexAB-oprM` -> mexA, mexB, oprM). Se toma ancho a propósito: cuanto más
    ancho, más entidades cuentan como "explicadas por el oro" y más
    conservadora es la medida de sustancia.
    """
    vocab = set()

    def anotar(nombre):
        if not nombre:
            return
        vocab.add(clave(nombre))
        for m in miembros_operon(nombre):
            vocab.add(clave(m))

    for fila in oro:
        anotar(fila["tf"])
        anotar(fila["blanco"])
        for tok in IDENT.findall(fila["alias"]):
            rango = expandir_rango(tok)
            if rango:
                for x in rango:
                    anotar(x)
            elif parece_identificador(tok):
                anotar(tok)
    return vocab


def medir_sustancia(pares, entidades, vocab):
    """Cuánto del trabajo del pipeline se explica por el vocabulario del oro.

    Defecto que corrige: los dos guardianes anteriores miraban la columna
    `fuente` del diccionario y un conteo de filas con símbolo. Un
    genes_pao1.tsv cuyas filas con contenido eran copia literal del oro,
    declarando `fuente=refseq` y con el relleno llevando símbolos inventados
    (zzz0001, zzz0002...), pasaba los dos y publicaba cobertura 100.0 %,
    EXHAUSTIVIDAD 95.3 % y ACIERTO DE SIGNO 98.8 % con código de salida 0. Los
    dos preguntaban qué decía ser el diccionario; ninguno medía qué era.
    """
    dentro = sorted(p for p in pares if p[0] in vocab and p[1] in vocab)
    un_extremo = sum(1 for p in pares if (p[0] in vocab) != (p[1] in vocab))
    ents_dentro = [e for e in entidades if e in vocab]
    fraccion = (float(len(dentro)) / len(pares)) if pares else None
    return collections.OrderedDict([
        ("que_es", SUSTANCIA_QUE_ES),
        ("es_graduada", SUSTANCIA_ES_GRADUADA),
        ("vocabulario_del_oro", len(vocab)),
        ("pares_distintos", len(pares)),
        ("pares_dentro_del_vocabulario_del_oro", len(dentro)),
        ("pares_con_un_solo_extremo_en_el_oro", un_extremo),
        ("pares_fuera_del_vocabulario_del_oro",
         len(pares) - len(dentro) - un_extremo),
        ("fraccion_explicada_por_el_oro", redondear(fraccion)),
        ("entidades_distintas", len(entidades)),
        ("entidades_dentro_del_vocabulario_del_oro", len(ents_dentro)),
        ("entidades_fuera", len(entidades) - len(ents_dentro)),
        ("umbral_de_aviso", UMBRAL_AVISO_CIRCULARIDAD),
        ("umbral_de_abandono", UMBRAL_CIRCULARIDAD),
        ("medido", "diccionario real 0.256; diccionario copiado del oro "
                   "0.661; corpus completo en los dos casos"),
    ])


def revisar_sustancia(sustancia, ruta_genes, ruta_pares):
    """Sale con 1 si el pipeline no sabe nada que el oro no le haya dicho.

    Es la mitad dura de la medida graduada. La mitad blanda es el aviso de
    UMBRAL_AVISO_CIRCULARIDAD, que deja escribir los archivos con código 2.
    """
    f = sustancia["fraccion_explicada_por_el_oro"]
    if f is None or f < UMBRAL_CIRCULARIDAD:
        return
    sys.exit(
        "El %.1f %% de los %d pares distintos que %s propuso desde el corpus "
        "tiene sus DOS extremos dentro del vocabulario que escribe el propio "
        "patrón de oro (el umbral es %.0f %%; un diccionario genuino mide "
        "25.6 %%). Solo %d pares caen enteros fuera. Eso no es un diccionario "
        "de PAO1 que resulta cubrir el oro: es el oro con otro nombre en la "
        "columna `fuente`, y la exhaustividad mediría el solapamiento del "
        "diccionario consigo mismo. Revisa %s. No escribo."
        % (100 * f, sustancia["pares_distintos"], ruta_pares,
           100 * UMBRAL_CIRCULARIDAD,
           sustancia["pares_fuera_del_vocabulario_del_oro"], ruta_genes))


def revisar_probabilidades_de_fila(d, ruta, i):
    """La invariante de §4 sobre una fila de predicciones. Devuelve |suma - 1|.

    Vive aquí y no en cada consumidor porque una invariante escrita dos veces
    diverge, y ya pasó en este proyecto. `evaluar_signo.py` la importa.
    """
    ps = dict((c, float(d.get("p_%s" % c, 0.0))) for c in ETIQUETAS)
    suma = sum(ps.values())
    if abs(suma - 1.0) > TOLERANCIA_SOFTMAX:
        sys.exit(
            "%s fila %d (id_par %s): las probabilidades no suman 1, suman "
            "%.6f. Revisa el softmax. Sin esto, la columna `confianza` de "
            "red.tsv y toda metrica que salga de ella son un numero sin "
            "unidades: medido, las cuatro clases a 0.99 daban 9608 aristas "
            "con confianza 0.9900 y exhaustividad 95.1 %% con codigo 0. No "
            "escribo." % (ruta, i, d.get("id_par", "?"), suma))
    etiqueta = d.get("prediccion")
    if etiqueta in ETIQUETAS:
        alta = max(ps.values())
        if ps[etiqueta] < alta - 1e-9:
            sys.exit(
                "%s fila %d (id_par %s): dice prediccion=%r con p=%.6f, y la "
                "probabilidad mas alta es %.6f. La seccion 4 del contrato "
                "define `prediccion` como la etiqueta de mayor probabilidad; "
                "si no lo es, el signo de la arista no describe lo que el "
                "modelo contesto. No escribo."
                % (ruta, i, d.get("id_par", "?"), etiqueta, ps[etiqueta],
                   alta))
    return abs(suma - 1.0)


def revisar_probabilidades(ruta):
    """La invariante de §4, aquí abajo: las cuatro probabilidades suman 1.

    Vivía solo en `clasificar.py`, el único archivo que necesita `torch` y por
    tanto el que menos gente corre. Medido: un predicciones.jsonl con las
    cuatro clases a 0.99 (suma 3.96) en las 65216 filas pasaba red.py con
    código 0 y producía 9608 aristas con `confianza` 0.9900 --una columna que
    el contrato define como la media de una probabilidad-- y este archivo
    publicaba EXHAUSTIVIDAD 95.1 % sin mirar nada.

    Se comprueba además que `prediccion` sea de verdad la clase de mayor
    probabilidad, que es como §4 la define. Es la misma clase de defecto: la
    columna es una etiqueta y hasta ahora nadie la contrastaba con los cuatro
    números que dice resumir.

    Devuelve None si el archivo no está: entonces el informe lo dice, en vez
    de callarse que la comprobación no se hizo.
    """
    if not ruta or not os.path.exists(ruta):
        return None
    n, peor = 0, 0.0
    with open(ruta, encoding="utf-8") as f:
        for i, linea in enumerate(f, start=1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                d = json.loads(linea)
            except ValueError as e:
                sys.exit("%s línea %d no es JSON: %s" % (ruta, i, e))
            n += 1
            peor = max(peor, revisar_probabilidades_de_fila(d, ruta, i))
    return collections.OrderedDict([
        ("ruta", ruta),
        ("filas", n),
        ("desviacion_maxima_de_la_suma", round(peor, 9)),
        ("tolerancia", TOLERANCIA_SOFTMAX),
        ("que_comprueba", "Que las cuatro probabilidades sumen 1 (§4) y que "
                          "`prediccion` sea de verdad la clase de mayor "
                          "probabilidad. La invariante existía solo en "
                          "clasificar.py, que es el único archivo que "
                          "necesita torch."),
    ])


def cargar_diccionario(ruta):
    """(superficie -> locus_tag, informe de procedencia y de tamaño útil).

    El informe trae los tres números con los que se decide si este diccionario
    puede sostener una evaluación: cuántas filas tiene, cuántas **entidades
    útiles** (filas con alguna superficie además del locus tag) y de dónde dice
    cada fila que salió. Los tres van al JSON, porque un lector tiene que poder
    ver la composición del diccionario sin abrirlo.
    """
    filas = leer_tsv(ruta, COLUMNAS_GENES, "diccionario de genes")
    if len(filas) < 5000:
        print("AVISO: el diccionario tiene %d filas; PAO1 tiene del orden de "
              "5700." % len(filas))
    mapa = {}
    utiles = 0
    fuentes = collections.Counter()
    del_oro, desconocidas = [], collections.Counter()
    for fila in filas:
        locus = fila["locus_tag"]
        superficies = [locus, fila["simbolo"]]
        superficies += [a for a in fila["alias"].split("|") if a]
        for s in superficies:
            if s:
                mapa.setdefault(clave(s), locus)
        # Útil = se puede encontrar en la prosa. Un locus tag pelado casi nunca
        # se escribe en un artículo y una fila con el símbolo vacío no aporta
        # ninguna superficie; contarla como "gen del diccionario" es lo que
        # permitía inflar el archivo hasta 5700 líneas sin entidades dentro.
        if any(s and clave(s) != clave(locus) for s in superficies):
            utiles += 1
        for f in [x for x in fila["fuente"].split("|") if x]:
            fuentes[f] += 1
            baja = clave(f)
            if any(marca in baja for marca in FUENTES_DEL_ORO):
                del_oro.append("%s (fuente=%s)" % (locus, f))
            elif baja not in FUENTES_VALIDAS:
                desconocidas[f] += 1
    info = collections.OrderedDict([
        ("ruta", ruta),
        ("filas", len(filas)),
        ("entidades_utiles", utiles),
        ("fuentes", collections.OrderedDict(sorted(fuentes.items()))),
        ("filas_con_procedencia_del_oro", del_oro),
        ("fuentes_desconocidas", collections.OrderedDict(
            sorted(desconocidas.items()))),
    ])
    return mapa, info


def revisar_procedencia(info):
    """El guardián de circularidad, y se comprueba SIEMPRE.

    Por procedencia, no por conteo. El diccionario declara su fuente fila por
    fila (§2 salida A) y `oro` no es un valor válido: si alguna fila viene del
    patrón, la exhaustividad mide el solapamiento del diccionario consigo
    mismo, no que el pipeline encuentre relaciones.

    Síntoma que corrige: el guardián anterior exigía cobertura del 100 % **y**
    menos de 1000 líneas en el TSV. Un genes_pao1.tsv con 785 filas copiadas
    del oro y 4915 filas de relleno vacías tenía 5700 líneas, así que no se
    disparaba, y el script publicaba cobertura_diccionario 100 %,
    exhaustividad 81.7 % y acierto de signo 82.5 % con código de salida 0.

    Una fuente que no está en el enum del contrato no aborta: no es prueba de
    circularidad, solo de que el diccionario no lo escribió
    construir_diccionario.py. Se avisa y se cuenta, para que se vea.
    """
    if info["filas_con_procedencia_del_oro"]:
        muestra = ", ".join(info["filas_con_procedencia_del_oro"][:8])
        sys.exit(
            "%d de las %d filas de %s declaran que su procedencia es el patrón "
            "de oro o la auditoría (%s%s). Eso hace circular la evaluación "
            "(sección 7 del contrato): la exhaustividad mediría el solapamiento "
            "del diccionario consigo mismo. La columna `fuente` solo admite %s. "
            "No escribo."
            % (len(info["filas_con_procedencia_del_oro"]), info["filas"],
               info["ruta"], muestra,
               ", ..." if len(info["filas_con_procedencia_del_oro"]) > 8 else "",
               ", ".join(FUENTES_VALIDAS)))


def cargar_operones(ruta):
    """operon -> [miembros]. Opcional: si falta, queda la expansión mecánica."""
    if not ruta or not os.path.exists(ruta):
        return {}, False
    filas = leer_tsv(ruta, COLUMNAS_OPERONES, "tabla de operones")
    mapa = {}
    for fila in filas:
        miembros = [m for m in fila["miembros"].split("|") if m]
        miembros += [m for m in fila["locus_tags"].split("|") if m]
        if miembros:
            mapa[clave(fila["operon"])] = [clave(m) for m in miembros]
    return mapa, True


# ---------------------------------------------------------------------------
# Emparejamiento
# ---------------------------------------------------------------------------

# Prioridad de la coincidencia, en el orden del enum del contrato.
RANGO_COINCIDENCIA = {"exacta": 0, "por_operon": 1, "por_alias": 2}


def miembros_de_tabla(nombre, operones):
    """Los genes de un operón **según `operones_pao1.tsv`, y solo según ella**.

    Es el único camino por el que se expande un nombre que produjo el pipeline.
    La expansión mecánica del nombre (`miembros_operon`) no vale aquí, y esa
    asimetría es el arreglo de un defecto demostrado: `lexico` acuña entidades
    sintéticas desde el texto en cuanto todos los miembros existen en el
    diccionario (`lasRIAB`, `rsmZA`, `gacAS`, `exoSTY`), y con la expansión
    mecánica una sola arista inventada `LasR -> lasRIAB` se contaba como
    recuperación de TRES filas del oro a la vez (lasA, lasB, lasI), las tres
    marcadas `por_operon`. Un nodo fabricado por una concatenación del texto
    subía la exhaustividad sin haber encontrado ninguna relación.

    §6.3 autoriza exactamente esta tabla, "derivada del diccionario sin mirar
    el oro", y nada más.
    """
    miembros = set(operones.get(clave(nombre), []))
    miembros.discard(clave(nombre))
    return frozenset(miembros)


def miembros_laxos(nombre, operones):
    """La tabla más la expansión mecánica. **Solo para el diagnóstico.**

    No entra en ninguna métrica. Sirve para contar cuántas filas del oro se
    habrían dado por recuperadas si el nombre del pipeline se expandiera
    mecánicamente, que es la diferencia entre lo que este archivo publicaba
    antes y lo que publica ahora. Sin ese número, el cambio de criterio se
    leería como una caída del pipeline.
    """
    miembros = set(clave(m) for m in miembros_operon(nombre))
    miembros.update(operones.get(clave(nombre), []))
    miembros.discard(clave(nombre))
    return frozenset(miembros)


def expandir_red(red, operones, laxa=False):
    """Cada arista con el blanco ya expandido a los genes de su operón.

    La equivalencia operón-gen tiene que valer en los dos sentidos. Hacia un
    lado, el oro nombra el operón y la red un gen (`mexAB-oprM` contra `mexA`).
    Hacia el otro, CollecTF nombra el locus tag del gen y la red nombra el
    operón (`PA2493` contra `mexEF-oprN`). Expandir solo el lado del oro dejaba
    fuera el segundo caso, que es justo el de la referencia que mide si el
    pipeline encuentra lo que nadie le enseñó.

    Este es el lado del PIPELINE, así que se expande solo por tabla. Con
    `laxa=True` se admite la expansión mecánica, y eso no se usa para medir:
    solo para el diagnóstico de `miembros_laxos()`.
    """
    expandir = miembros_laxos if laxa else miembros_de_tabla
    return [(ktf, kbl, expandir(fila["blanco"], operones), fila)
            for (ktf, kbl), fila in red.items()]


def claves_extremo(nombre, alias, operones):
    """{clase de coincidencia -> conjunto de claves} para un extremo del oro.

    Este es el lado de la REFERENCIA (el oro o CollecTF), y aquí sí entra la
    expansión mecánica del nombre además de la tabla. La diferencia con
    `miembros_de_tabla()` es deliberada: `oro_pseudomonas.tsv` es una tabla
    versionada, escrita a mano y de 190 filas fijas, así que sus nombres no los
    puede fabricar el pipeline. Expandir `mexCD-oprJ` a mexC, mexD y oprJ es
    leer un nombre que ya estaba escrito; expandir `lasRIAB` sería aceptar un
    nombre que el pipeline acaba de inventar. Solo lo segundo infla la métrica.
    """
    salida = {"exacta": set([clave(nombre)]), "por_alias": set(alias),
              "por_operon": set()}
    de_tabla = operones.get(clave(nombre), [])
    mecanicos = [clave(m) for m in miembros_operon(nombre)]
    salida["por_operon"].update(de_tabla)
    salida["por_operon"].update(mecanicos)
    # Un nombre nunca se empareja consigo mismo por dos vías distintas.
    salida["por_operon"] -= salida["exacta"]
    salida["por_alias"] -= salida["exacta"]
    salida["por_alias"] -= salida["por_operon"]
    return salida, bool(de_tabla), bool(mecanicos)


def clase_de(claves, k, miembros_del_otro=frozenset()):
    for clase in ("exacta", "por_operon"):
        if k in claves[clase]:
            return clase
    # El otro lado es el operón y nosotros uno de sus genes.
    if miembros_del_otro & (claves["exacta"] | claves["por_alias"]):
        return "por_operon"
    if k in claves["por_alias"]:
        return "por_alias"
    return None


def buscar_arista(claves_tf, claves_bl, red_expandida):
    """La mejor arista de la red que empareja con esta fila del oro.

    Mejor = coincidencia más fuerte; a igualdad, la de más evidencias; a
    igualdad, orden alfabético. El desempate es explícito para que dos corridas
    sobre la misma entrada den la misma fila.
    """
    mejor = None
    for ktf, kbl, miembros, fila in red_expandida:
        ctf = clase_de(claves_tf, ktf)
        cbl = clase_de(claves_bl, kbl, miembros)
        if ctf is None or cbl is None:
            continue
        clase = ctf if RANGO_COINCIDENCIA[ctf] >= RANGO_COINCIDENCIA[cbl] else cbl
        try:
            evid = int(fila["n_evidencias"])
        except ValueError:
            evid = 0
        orden = (RANGO_COINCIDENCIA[clase], -evid, fila["tf"], fila["blanco"])
        if mejor is None or orden < mejor[0]:
            mejor = (orden, clase, fila)
    if mejor is None:
        return None, "ninguna"
    return mejor[2], mejor[1]


def candidatos_de(claves_tf, claves_bl, indice_pares):
    """Cuántas oraciones candidatas sostienen esta fila del oro. 0 = ninguna.

    Acepta la equivalencia operón-gen en los dos sentidos, igual que
    buscar_arista(): si no, una fila del oro cuyo blanco es un operón saldría
    como "nunca hubo candidato" mientras el candidato existía con el nombre del
    gen, y el veredicto culparía al extractor en vez de a la red.

    Devuelve el número, no un booleano, porque es el tamaño de la muestra sobre
    la que sortea la línea base aleatoria: con N oraciones candidatas, el azar
    recupera el par con probabilidad 1 - (1/4)^N.
    """
    todas_bl = set().union(*claves_bl.values())
    n = 0
    for ktf in set().union(*claves_tf.values()):
        for ktarget, miembros, cuenta in indice_pares.get(ktf, ()):
            if ktarget in todas_bl or (miembros & todas_bl):
                n += cuenta
    return n


def resolver(nombre, alias, claves, diccionario):
    """id canónico del diccionario, o '' si el nombre no existe en PAO1.

    Devuelve además si hizo falta bajar a los miembros del operón, porque
    "resolvió directo" y "resolvió por operón" no son lo mismo.
    """
    for k in [clave(nombre)] + sorted(alias):
        if k in diccionario:
            return diccionario[k], False
    encontrados = [diccionario[m] for m in sorted(claves["por_operon"])
                   if m in diccionario]
    if encontrados:
        return "|".join(sorted(set(encontrados))), True
    return "", False


# ---------------------------------------------------------------------------
# Evaluación fila por fila
# ---------------------------------------------------------------------------

def evaluar(oro, red_expandida, red_laxa, indice_pares, diccionario,
            operones, disputadas):
    """Una fila de resultado por fila del oro, en el orden del oro.

    `red_laxa` es la misma red con los nombres del pipeline expandidos también
    de forma mecánica. No entra en ninguna métrica: solo sirve para contar las
    filas que se habrían dado por recuperadas con el criterio anterior, que es
    el que dejaba que `LasR -> lasRIAB` valiera por tres filas del oro.
    """
    salida = []
    ambiguas = 0
    for fila in oro:
        tf, blanco = fila["tf"], fila["blanco"]
        alias_tf, alias_bl, amb = alias_anclados(fila["alias"], tf, blanco)
        ambiguas += amb
        claves_tf, _, _ = claves_extremo(tf, alias_tf, operones)
        claves_bl, de_tabla, mecanico = claves_extremo(blanco, alias_bl, operones)

        rtf, rtf_op = resolver(tf, alias_tf, claves_tf, diccionario)
        rbl, rbl_op = resolver(blanco, alias_bl, claves_bl, diccionario)
        resuelta = bool(rtf) and bool(rbl)

        arista, coincidencia = buscar_arista(claves_tf, claves_bl,
                                             red_expandida)
        arista_laxa, _ = buscar_arista(claves_tf, claves_bl, red_laxa)
        n_candidatos = candidatos_de(claves_tf, claves_bl, indice_pares)
        candidato = n_candidatos > 0

        signo_oro = fila["signo"]
        if arista is not None:
            signo_red = arista["signo"]
            if signo_red not in SIGNOS:
                sys.exit("Signo desconocido en la red: %r. Revisa id2label del "
                         "checkpoint." % signo_red)
            comparable = (signo_oro in ("activates", "represses") and
                          signo_red in ("activates", "represses"))
            if comparable:
                veredicto = ("recuperada_signo_ok" if signo_red == signo_oro
                             else "recuperada_signo_mal")
            elif signo_red == signo_oro:
                veredicto = "recuperada_signo_ok"
            else:
                # El contrato define recuperada_sin_signo como "la red dijo
                # regulates y el oro tenía signo". Se usa el mismo veredicto
                # cuando el que no trae signo es el oro: en los dos casos el
                # signo no se puede comparar, y esas filas quedan fuera del
                # denominador honesto de todos modos.
                veredicto = "recuperada_sin_signo"
        else:
            signo_red = ""
            comparable = False
            if not resuelta:
                veredicto = "fuera_de_diccionario"
            elif candidato:
                veredicto = "no_recuperada_filtrada"
            else:
                veredicto = "no_recuperada_sin_candidato"

        motivo = ""
        if fila["atestiguado"] != "true":
            motivo = "no_atestiguada"
        elif signo_oro == "regulates":
            motivo = "signo_no_resuelto"
        elif (clave(tf), clave(blanco)) in disputadas:
            motivo = "en_disputa"

        salida.append({
            "tf": tf,
            "blanco": blanco,
            "signo_oro": signo_oro,
            "certeza_dominio": fila["certeza_dominio"],
            "subsistema": fila["subsistema"],
            "atestiguado": fila["atestiguado"],
            "resuelto_tf": rtf,
            "resuelto_blanco": rbl,
            "hubo_candidato": bool_txt(candidato),
            "coincidencia": coincidencia,
            "signo_red": signo_red,
            "conflicto": arista["conflicto"] if arista else "",
            "n_evidencias": arista["n_evidencias"] if arista else "0",
            "n_articulos": arista["n_articulos"] if arista else "0",
            "confianza": arista["confianza"] if arista else "",
            "veredicto": veredicto,
            "en_denominador_honesto": bool_txt(not motivo),
            "motivo_exclusion": motivo,
            "n_candidatos": str(n_candidatos),
            # Con guion bajo: no van al TSV, los usan las métricas.
            "_n_candidatos": n_candidatos,
            "_solo_con_expansion_mecanica": (arista is None and
                                             arista_laxa is not None),
            "_resuelta": resuelta,
            "_resuelta_por_operon": rtf_op or rbl_op,
            "_candidato": candidato,
            "_recuperada": arista is not None,
            "_comparable": comparable,
            "_acierto": comparable and signo_red == signo_oro,
            "_autorregulacion": clave(tf) == clave(blanco),
            "_operon_de_tabla": de_tabla,
            "_operon_mecanico": mecanico,
        })
    return salida, ambiguas


def metricas(filas):
    """Las cuatro de §6.2, cada una con su numerador y su denominador.

    Se reportan separadas a propósito. Una exhaustividad sola esconde de dónde
    viene: si el diccionario cubriera el 100 % del oro habría que sospechar que
    se construyó desde el oro, y solo `cobertura_diccionario` lo enseña.
    """
    total = len(filas)
    resueltas = [f for f in filas if f["_resuelta"]]
    con_candidato = [f for f in resueltas if f["_candidato"]]
    recuperadas = [f for f in filas if f["_recuperada"]]
    comparables = [f for f in recuperadas if f["_comparable"]]
    return {
        "filas": total,
        "cobertura_diccionario": tasa(len(resueltas), total),
        "cobertura_candidatos": tasa(len(con_candidato), len(resueltas)),
        "exhaustividad": tasa(sum(1 for f in con_candidato if f["_recuperada"]),
                              len(con_candidato)),
        "exhaustividad_sobre_universo": tasa(len(recuperadas), total),
        "acierto_signo": tasa(sum(1 for f in comparables if f["_acierto"]),
                              len(comparables)),
    }


def desglosar(filas, campo):
    salida = collections.OrderedDict()
    for llave in sorted(set(f[campo] for f in filas)):
        salida[llave] = metricas([f for f in filas if f[campo] == llave])
    return salida


# ---------------------------------------------------------------------------
# La línea base aleatoria: cuánto de la cifra publicada lo da el azar
# ---------------------------------------------------------------------------

QUE_ES = (
    "La misma evaluación, pero asignando al azar una de las cuatro clases del "
    "modelo (activates, no_relation, regulates, represses) a cada uno de los "
    "MISMOS candidatos de pares.jsonl, con la semilla fija de --semilla y "
    "repitiendo el sorteo --repeticiones-linea-base veces. Contesta la única "
    "pregunta que la exhaustividad sola no contesta: cuánto de esa cifra la "
    "da el azar. Medido antes de que esto existiera: predicciones "
    "COMPLETAMENTE aleatorias sobre el corpus entero daban 95.5 % de "
    "exhaustividad (105 de 110) y nada en la salida lo delataba."
)

# Este comentario afirmaba, y era falso, que "el acierto de signo no se
# satura: su línea base es 50 % venga de donde venga". No lo es. La línea base
# de un acierto sobre dos clases es la proporción de la clase mayoritaria del
# subconjunto que se evalúa, porque un clasificador constante la acierta
# entera sin leer una palabra. Síntoma medido: decir siempre `activates`
# publicaba ACIERTO DE SIGNO 69.8 % (97 de 139) --clavado en la proporción de
# `activates` de esas mismas 139 filas-- y este archivo cerraba con "se
# distingue del azar (p = 0.005). Codigo 0".
POR_QUE_SE_SATURA = (
    "La exhaustividad se satura por construcción: un par del oro suele traer "
    "muchas oraciones candidatas y basta que UNA salga con una clase distinta "
    "de no_relation para dar el par por recuperado, así que con N candidatos "
    "el azar lo recupera con probabilidad 1 - (1/4)^N. El acierto de signo no "
    "se satura así, pero su línea base TAMPOCO es 50 %: es la proporción de "
    "la clase mayoritaria de las filas que se están evaluando, porque un "
    "clasificador constante la acierta entera sin leer el texto. Medido: "
    "contestar siempre `activates` daba 69.8 % (97 de 139), que es "
    "exactamente la proporción de `activates` de esas 139 filas, y este "
    "archivo lo certificaba como distinto del azar con p = 0.005. Por eso el "
    "acierto de signo se contrasta contra DOS líneas base --el sorteo "
    "uniforme y la clase mayoritaria-- y el código 0 exige despegar de las "
    "dos."
)

# Este comentario decía que el sesgo va "a favor del azar, nunca a favor del
# pipeline". Para la exhaustividad es cierto; para el acierto de signo era
# falso y en el sentido que importa, porque de esa comparación colgaba el
# código de salida.
ES_GENEROSA = (
    "La línea base aleatoria no pasa por los umbrales de red.py: el azar no "
    "tiene probabilidades que comparar contra un umbral, así que se le regala "
    "que toda clase sorteada sobreviva. Para la EXHAUSTIVIDAD eso la convierte "
    "en una COTA SUPERIOR de lo que da el azar y sesga la comparación en "
    "contra del pipeline. Para el ACIERTO DE SIGNO el sesgo va al revés y hay "
    "que decirlo: el sorteo reparte `activates` y `represses` a partes "
    "iguales, así que da ~50 % pase lo que pase, mientras el camino real pasa "
    "por umbrales asimétricos (activates 0.65, represses 0.70) que filtran "
    "más la represión y heredan el desequilibrio del oro (117 activates "
    "contra 67 represses). Compararse contra ese ~50 % le regalaba al "
    "pipeline la diferencia entera. Para eso está la segunda línea base."
)

LINEA_MAYORITARIA_QUE_ES = (
    "El acierto de signo del clasificador más tonto que existe: el que "
    "contesta siempre la clase más frecuente del propio subconjunto que se "
    "evalúa, sin leer el texto. Es la línea base correcta del acierto de "
    "signo. El contraste es una binomial exacta de una cola: la probabilidad "
    "de que ese clasificador constante acierte al menos tantas filas como el "
    "pipeline."
)

LINEA_MAYORITARIA_ES_CONSERVADORA = (
    "La tasa base se estima sobre las MISMAS filas contra las que se compara, "
    "porque no hay un segundo patrón de oro del que sacarla. Eso le regala al "
    "clasificador constante conocer el reparto de clases de la muestra, así "
    "que la prueba pide un poco más de lo estrictamente necesario. Es el "
    "sesgo que queremos: en contra del pipeline, nunca a su favor."
)


def sortear_arista(rng, n, mayoria):
    """(hubo arista, signo) para n candidatos con la clase sorteada al azar.

    Reproduce el §5.2 de red.py sobre etiquetas uniformes: sobrevive toda
    evidencia que no sea `no_relation`, el signo sale de la mayoría entre
    `activates` y `represses` y un empate degrada a `regulates`.
    """
    act = rep = reg = 0
    for _ in range(n):
        x = rng.random()
        if x < 0.25:
            act += 1
        elif x < 0.50:
            rep += 1
        elif x < 0.75:
            reg += 1
        # el cuarto cuarto es no_relation y no vota
    if act + rep + reg == 0:
        return False, ""
    firmados = act + rep
    if firmados == 0:
        return True, "regulates"
    ganador, n_ganador = (("activates", act) if act >= rep
                          else ("represses", rep))
    if float(n_ganador) / firmados >= mayoria:
        return True, ganador
    return True, "regulates"


def binomial_cola_superior(k, n, p):
    """P(X >= k) con X ~ Binomial(n, p). Exacta, solo con la estándar.

    n aquí son las filas del oro con signo comparable (del orden de 140), así
    que sumar la cola entera con `math.comb` cuesta microsegundos y evita
    aproximaciones normales que en las colas mienten justo donde se decide.
    """
    if n <= 0:
        return None
    k = max(0, k)
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k <= n else 0.0
    total = 0.0
    for i in range(k, n + 1):
        total += math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
    return min(1.0, total)


def linea_base_mayoritaria(filas):
    """La línea base que faltaba: la clase mayoritaria, no el 50 %.

    Se calcula sobre exactamente las mismas filas que `metricas()` usa para el
    acierto de signo (recuperadas y con signo comparable en los dos lados), y
    con el mismo numerador. Sin esto, un clasificador constante que contesta
    siempre `activates` salía certificado: 69.8 % de acierto sobre 139 filas
    de las que 97 son `activates`, o sea la tasa base exacta, y el archivo
    imprimía "El acierto de signo se distingue del azar (p = 0.005)".
    """
    comparables = [f for f in filas if f["_recuperada"] and f["_comparable"]]
    n = len(comparables)
    reparto = collections.Counter(f["signo_oro"] for f in comparables)
    aciertos = sum(1 for f in comparables if f["_acierto"])
    if n:
        clase, n_clase = sorted(reparto.items(),
                                key=lambda kv: (-kv[1], kv[0]))[0]
        tasa_base = float(n_clase) / n
        real = float(aciertos) / n
        p_valor = binomial_cola_superior(aciertos, n, tasa_base)
        ventaja = 100.0 * (real - tasa_base)
    else:
        clase, tasa_base, real, p_valor, ventaja = "", None, None, None, None
    return collections.OrderedDict([
        ("que_es", LINEA_MAYORITARIA_QUE_ES),
        ("es_conservadora", LINEA_MAYORITARIA_ES_CONSERVADORA),
        ("filas_comparables", n),
        ("reparto_del_oro", collections.OrderedDict(sorted(reparto.items()))),
        ("clase_mayoritaria", clase),
        ("tasa_base", redondear(tasa_base)),
        ("real", redondear(real)),
        ("aciertos", aciertos),
        ("ventaja_puntos", redondear(ventaja, 1)),
        ("p_valor", redondear(p_valor)),
        ("prueba", "binomial exacta de una cola, P(X >= aciertos) con "
                   "X ~ Binomial(filas_comparables, tasa_base)"),
    ])


def percentil(valores, p):
    """Percentil por interpolación lineal. None si no hay ningún valor."""
    limpios = sorted(v for v in valores if v is not None)
    if not limpios:
        return None
    k = (len(limpios) - 1) * p
    bajo = int(k)
    alto = min(bajo + 1, len(limpios) - 1)
    return limpios[bajo] + (limpios[alto] - limpios[bajo]) * (k - bajo)


def redondear(v, n=4):
    return None if v is None else round(v, n)


def resumen_sorteos(valores, real):
    """La cifra real, la del azar y la probabilidad de que el azar la iguale.

    `p_valor` es el clásico de Monte Carlo, (1 + aciertos) / (1 + sorteos): la
    proporción de sorteos en los que el azar llegó tan lejos como el pipeline.
    Un p_valor alto no dice "el pipeline es azar", dice "con esta medición no
    se distingue del azar", que es exactamente lo que hay que publicar.
    """
    limpios = [v for v in valores if v is not None]
    media = sum(limpios) / float(len(limpios)) if limpios else None
    if real is None or not limpios:
        p = None
        ventaja = None
    else:
        p = (1 + sum(1 for v in limpios if v >= real)) / float(len(limpios) + 1)
        ventaja = 100.0 * (real - media)
    return collections.OrderedDict([
        ("real", redondear(real)),
        ("azar_media", redondear(media)),
        ("azar_p50", redondear(percentil(limpios, 0.50))),
        ("azar_p95", redondear(percentil(limpios, 0.95))),
        ("ventaja_puntos", redondear(ventaja, 1)),
        ("p_valor", redondear(p)),
        ("sorteos_con_dato", len(limpios)),
    ])


def linea_base_aleatoria(filas, reales, semilla, repeticiones, mayoria):
    """Qué exhaustividad y qué acierto de signo daría el puro azar.

    Sortea sobre EXACTAMENTE los mismos candidatos que tuvo el pipeline: la
    misma lista de filas del oro, cada una con su número de oraciones
    candidatas (`_n_candidatos`), y el mismo denominador. Lo único que cambia
    es que la clase de cada oración se saca de un dado de cuatro caras en vez
    de del modelo.
    """
    # El mismo conjunto exacto que usa metricas(): resuelta en el diccionario
    # Y con candidato. Si el denominador del azar no fuera el mismo, la
    # comparación no sería una comparación.
    con_candidato = [f for f in filas if f["_resuelta"] and f["_candidato"]]
    rng = random.Random(semilla)
    exhaustividades, aciertos = [], []
    for _ in range(repeticiones):
        recuperadas = comparables = correctas = 0
        for f in con_candidato:
            hubo, signo = sortear_arista(rng, f["_n_candidatos"], mayoria)
            if not hubo:
                continue
            recuperadas += 1
            if f["signo_oro"] in ("activates", "represses") and signo in (
                    "activates", "represses"):
                comparables += 1
                if signo == f["signo_oro"]:
                    correctas += 1
        exhaustividades.append(
            float(recuperadas) / len(con_candidato) if con_candidato else None)
        aciertos.append(
            float(correctas) / comparables if comparables else None)

    def real_de(llave):
        v = reales[llave]
        return float(v["n"]) / v["d"] if v["d"] else None

    oraciones = sum(f["_n_candidatos"] for f in con_candidato)
    return collections.OrderedDict([
        ("que_es", QUE_ES),
        ("por_que_se_satura", POR_QUE_SE_SATURA),
        ("es_generosa", ES_GENEROSA),
        ("semilla", semilla),
        ("repeticiones", repeticiones),
        ("mayoria", mayoria),
        ("filas_con_candidato", len(con_candidato)),
        ("oraciones_candidatas", oraciones),
        ("candidatos_por_fila", redondear(
            float(oraciones) / len(con_candidato) if con_candidato else None,
            2)),
        ("exhaustividad", resumen_sorteos(exhaustividades,
                                          real_de("exhaustividad"))),
        ("acierto_signo", resumen_sorteos(aciertos,
                                          real_de("acierto_signo"))),
    ])


def despega(azar, mayoritaria):
    """¿El acierto de signo despega de las DOS líneas base?

    None = no se puede saber (ninguna fila con signo comparable). Se exigen
    las dos porque miden cosas distintas: el sorteo uniforme dice si el
    pipeline hace algo más que tirar un dado, y la clase mayoritaria dice si
    hace algo más que contestar siempre lo mismo. Un clasificador constante
    pasaba la primera y falla la segunda; ese fue el exploit medido.
    """
    p_azar = azar["acierto_signo"]["p_valor"]
    p_may = mayoritaria["p_valor"]
    if p_azar is None or p_may is None:
        return None
    return p_azar <= ALFA and p_may <= ALFA


# ---------------------------------------------------------------------------
# CollecTF: la referencia que el oro no vio
# ---------------------------------------------------------------------------

def evaluar_collectf(ruta, red_expandida, diccionario, operones, tfs_del_oro):
    """Exhaustividad contra CollecTF, partida en TFs que el oro cubre y TFs que no.

    El segundo grupo es el número que más importa del contrato entero: son TFs
    reales de PAO1, con blancos y con artículos, que el patrón de oro no
    menciona. Miden si el pipeline encuentra relaciones que nadie le enseñó. Un
    pipeline circular saca cero ahí y se delata al instante.
    """
    filas = leer_tsv(ruta, COLUMNAS_COLLECTF, "CollecTF")
    # Un locus tag por sí solo casi nunca aparece en la prosa; el nombre que la
    # red usa es el símbolo. Se invierte el diccionario una vez para poder dar
    # las dos formas del mismo gen.
    por_locus = collections.defaultdict(set)
    for superficie, locus in diccionario.items():
        por_locus[locus].add(superficie)

    detalle = {"en_el_oro": [], "fuera_del_oro": []}
    for fila in filas:
        tf, blanco = fila["tf"], fila["blanco"]
        claves_tf, _, _ = claves_extremo(tf, set(), operones)
        alias_bl = set(por_locus.get(diccionario.get(clave(blanco), ""), set()))
        alias_bl.discard(clave(blanco))
        claves_bl, _, _ = claves_extremo(blanco, alias_bl, operones)
        arista, _ = buscar_arista(claves_tf, claves_bl, red_expandida)
        grupo = "en_el_oro" if clave(tf) in tfs_del_oro else "fuera_del_oro"
        detalle[grupo].append((tf, blanco, arista is not None,
                               fila["en_corpus"] == "true"))

    resumen = collections.OrderedDict()
    resumen["aviso"] = ("CollecTF son sitios de unión con evidencia "
                        "experimental y NO trae signo: aquí solo hay "
                        "exhaustividad. Sus PMIDs no se usan jamás para "
                        "entrenar ni para ajustar umbrales, solo para evaluar.")
    for grupo in ("en_el_oro", "fuera_del_oro"):
        items = detalle[grupo]
        en_corpus = [x for x in items if x[3]]
        resumen[grupo] = {
            "pares": len(items),
            "tfs": len(set(x[0] for x in items)),
            "exhaustividad": tasa(sum(1 for x in items if x[2]), len(items)),
            "exhaustividad_en_corpus": tasa(
                sum(1 for x in en_corpus if x[2]), len(en_corpus)),
            "recuperados": sorted("%s->%s" % (x[0], x[1])
                                  for x in items if x[2]),
        }
    return resumen


# ---------------------------------------------------------------------------
# Informe en la terminal
# ---------------------------------------------------------------------------

def porcentaje(v):
    """El porcentaje de una metrica de tasa(). Mismo formato que cifra()."""
    return cifra(v["tasa"])


def imprimir_metricas(titulo, m):
    print("  %s" % titulo)
    for etiqueta, llave in (("cobertura del diccionario",
                             "cobertura_diccionario"),
                            ("cobertura de candidatos  ",
                             "cobertura_candidatos"),
                            ("EXHAUSTIVIDAD            ", "exhaustividad"),
                            ("exhaustividad / universo ",
                             "exhaustividad_sobre_universo"),
                            ("ACIERTO DE SIGNO         ", "acierto_signo")):
        v = m[llave]
        print("    %s  %s   (%d de %d)"
              % (etiqueta, porcentaje(v), v["n"], v["d"]))


def imprimir_desglose(titulo, bloque):
    print("  %s" % titulo)
    for nombre in bloque:
        m = bloque[nombre]
        e, s = m["exhaustividad"], m["acierto_signo"]
        print("    %-24s exh %s (%d/%d)   signo %s (%d/%d)"
              % (nombre, porcentaje(e), e["n"], e["d"],
                 porcentaje(s), s["n"], s["d"]))


def cifra(v):
    """Un porcentaje, o n/d cuando el denominador es cero."""
    return "  n/d" if v is None else "%5.1f%%" % (100 * v)


def imprimir_linea_base(bloque):
    """El contrapeso de la exhaustividad, junto a la cifra que contrapesa."""
    print("  Contra la linea base aleatoria (semilla %s, %d sorteos sobre los "
          "mismos" % (bloque["semilla"], bloque["repeticiones"]))
    print("  %d candidatos, %.1f oraciones por fila):"
          % (bloque["oraciones_candidatas"],
             bloque["candidatos_por_fila"] or 0.0))
    for etiqueta, llave in (("EXHAUSTIVIDAD   ", "exhaustividad"),
                            ("ACIERTO DE SIGNO", "acierto_signo")):
        b = bloque[llave]
        ventaja = ("  n/d" if b["ventaja_puntos"] is None
                   else "%+5.1f pp" % b["ventaja_puntos"])
        pval = "n/d" if b["p_valor"] is None else "%.3f" % b["p_valor"]
        print("    %s  real %s   azar %s   ventaja %s   p %s"
              % (etiqueta, cifra(b["real"]), cifra(b["azar_media"]), ventaja,
                 pval))


def imprimir_linea_mayoritaria(bloque):
    """La línea base que un clasificador constante alcanza sin leer nada."""
    if not bloque["filas_comparables"]:
        print("  Contra la clase mayoritaria: no hay ninguna fila con signo "
              "comparable.")
        return
    reparto = ", ".join("%s %d" % kv for kv in bloque["reparto_del_oro"].items())
    print("  Contra la clase mayoritaria (%s; el oro de esas %d filas es %s):"
          % (bloque["clase_mayoritaria"], bloque["filas_comparables"], reparto))
    print("    ACIERTO DE SIGNO  real %s   constante %s   ventaja %s   p %s"
          % (cifra(bloque["real"]), cifra(bloque["tasa_base"]),
             "  n/d" if bloque["ventaja_puntos"] is None
             else "%+5.1f pp" % bloque["ventaja_puntos"],
             "n/d" if bloque["p_valor"] is None else "%.3f" % bloque["p_valor"]))


def imprimir_sustancia(bloque):
    """Cuánto del trabajo del pipeline lo explica el vocabulario del oro."""
    print("  Sustancia del diccionario (contenido, no procedencia declarada):")
    print("    pares distintos propuestos desde el corpus  %6d"
          % bloque["pares_distintos"])
    print("    con los DOS extremos en el vocabulario del oro %s (%d)"
          % (cifra(bloque["fraccion_explicada_por_el_oro"]),
             bloque["pares_dentro_del_vocabulario_del_oro"]))
    print("      medido: diccionario real  25.6%   copiado del oro  66.1%")
    print("    enteramente fuera del oro                  %6d"
          % bloque["pares_fuera_del_vocabulario_del_oro"])


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


# ---------------------------------------------------------------------------

def construir_parser():
    p = argparse.ArgumentParser(
        description="Compara la red inferida contra el patrón de oro. Da "
                    "exhaustividad y acierto de signo; NO da precisión.")
    p.add_argument("--red", default="datos_etapa2/red.tsv")
    p.add_argument("--pares", default="datos_etapa2/pares.jsonl")
    p.add_argument("--predicciones", default="datos_etapa2/predicciones.jsonl",
                   help="solo para comprobar que las cuatro probabilidades "
                        "suman 1 (invariante de la seccion 4); si no esta, se "
                        "avisa de que la comprobacion no se hizo")
    p.add_argument("--genes", default="etapa2/genes_pao1.tsv")
    p.add_argument("--operones", default="etapa2/operones_pao1.tsv")
    p.add_argument("--oro", default="etapa2/oro_pseudomonas.tsv")
    p.add_argument("--collectf", default=None,
                   help="segunda referencia, opcional")
    p.add_argument("--salida", default="datos_etapa2/evaluacion_oro.tsv")
    p.add_argument("--resumen", default="datos_etapa2/evaluacion_oro.json")
    p.add_argument("--incluir-no-atestiguadas", action="store_true",
                   help="mete en el universo las 9 filas que el corpus no "
                        "contiene (por omisión quedan fuera)")
    p.add_argument("--semilla", type=int, default=SEMILLA_POR_OMISION,
                   help="semilla de la linea base aleatoria; fija por omision "
                        "para que dos corridas den lo mismo")
    p.add_argument("--repeticiones-linea-base", type=int,
                   default=REPETICIONES_POR_OMISION,
                   help="sorteos de la linea base; mas sorteos, p_valor mas "
                        "fino")
    p.add_argument("--mayoria", type=float, default=MAYORIA_POR_OMISION,
                   help="la misma regla de mayoria que red.py (5.2); la linea "
                        "base la aplica sobre las clases sorteadas")
    p.add_argument("--disputadas", default=None,
                   help="TSV con columnas tf, blanco, justificacion. Si no se "
                        "pasa, se detectan por la marca 'disputa' de la "
                        "columna alias del oro")
    return p


def cargar_disputadas(ruta, oro):
    """Pares donde el corpus se contradice a sí mismo.

    Por omisión salen de la propia tabla: la columna `alias` marca "relacion en
    disputa". Hoy eso da UNA fila (RhlR -> rpoS) y la documentación habla de
    cinco sin nombrar las otras cuatro, así que el script avisa en vez de
    inventarlas. Un archivo con --disputadas permite nombrarlas el día que se
    identifiquen, sin tocar el código.
    """
    if ruta:
        filas = leer_tsv(ruta, ["tf", "blanco", "justificacion"],
                         "filas en disputa")
        sin_justificar = [f for f in filas if not f["justificacion"].strip()]
        if sin_justificar:
            sys.exit("Hay %d filas en %s sin justificación. Sacar una relación "
                     "del denominador sin decir por qué es exactamente como se "
                     "infla una métrica." % (len(sin_justificar), ruta))
        return set((clave(f["tf"]), clave(f["blanco"])) for f in filas), "archivo"
    marcadas = set()
    for fila in oro:
        if re.search(r"disputa", fila["alias"], re.I):
            marcadas.add((clave(fila["tf"]), clave(fila["blanco"])))
    return marcadas, "marca en la columna alias"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for arg in argv:
        if arg.startswith("--"):
            nombre = arg[2:].split("=")[0].lower()
            if nombre in PROHIBIDAS:
                print("\n".join(envolver(AVISO)))
                sys.exit("\nNo existe --%s y no va a existir." % nombre)

    args = construir_parser().parse_args(argv)

    oro = cargar_oro(args.oro)
    filas_red, red = cargar_red(args.red)
    diccionario, info_genes = cargar_diccionario(args.genes)
    # Guardián de circularidad, por procedencia y antes de nada más: si el
    # diccionario salió del patrón, no hay nada que medir aquí.
    revisar_procedencia(info_genes)
    operones, hay_tabla_operones = cargar_operones(args.operones)
    indice_pares, n_pares, pares_distintos, entidades_corpus = cargar_pares(
        args.pares, operones)
    # El guardián que mide contenido en vez de etiquetas. Va aquí, antes de
    # calcular una sola métrica: si el vocabulario del pipeline es el del oro,
    # la exhaustividad mide el solapamiento del diccionario consigo mismo y no
    # hay nada que escribir.
    sustancia = medir_sustancia(pares_distintos, entidades_corpus,
                                vocabulario_del_oro(oro))
    revisar_sustancia(sustancia, args.genes, args.pares)
    # La invariante de §4, que hasta ahora solo existía en clasificar.py.
    probabilidades = revisar_probabilidades(args.predicciones)
    disputadas, origen_disputadas = cargar_disputadas(args.disputadas, oro)

    red_expandida = expandir_red(red, operones)
    red_laxa = expandir_red(red, operones, laxa=True)
    todas, ambiguas = evaluar(oro, red_expandida, red_laxa, indice_pares,
                              diccionario, operones, disputadas)

    # §6, invariante: un diccionario que cubre todo el oro y es del tamaño del
    # oro es un diccionario hecho desde el oro. Se cuentan ENTIDADES ÚTILES, no
    # líneas: con líneas bastaba rellenar el TSV con filas de símbolo vacío
    # hasta 5700 para desactivar el guardián sin tocar nada de lo que vigila.
    cruda = metricas(todas)
    if (cruda["cobertura_diccionario"]["tasa"] == 1.0
            and info_genes["entidades_utiles"] < MINIMO_ENTIDADES_UTILES):
        sys.exit("El diccionario cubre el 100 %% del oro y solo tiene %d "
                 "entidades útiles (filas con alguna superficie además del "
                 "locus tag) en %d líneas. Eso es un diccionario hecho desde "
                 "el oro: la exhaustividad no mediría nada. Ver sección 7 del "
                 "contrato."
                 % (info_genes["entidades_utiles"], info_genes["filas"]))

    if args.incluir_no_atestiguadas:
        # La bandera revierte solo la exclusión por corpus; las de signo sin
        # resolver y las disputadas siguen fuera porque no son medibles.
        honestas = [f for f in todas
                    if f["motivo_exclusion"] in ("", "no_atestiguada")]
    else:
        honestas = [f for f in todas if f["motivo_exclusion"] == ""]

    # Dos conteos, y hacen falta los dos. El disjunto (por prioridad) es el que
    # suma al denominador; el crudo es el que se compara con la documentación.
    # Sin el crudo, "0 en disputa" parece decir que la marca no se encontró,
    # cuando lo que pasa es que esa fila ya salía por signo no resuelto.
    conteo_exclusiones = collections.Counter(
        f["motivo_exclusion"] for f in todas if f["motivo_exclusion"])
    con_solape = collections.OrderedDict([
        ("no_atestiguada", sum(1 for f in todas if f["atestiguado"] != "true")),
        ("signo_no_resuelto", sum(1 for f in todas
                                  if f["signo_oro"] == "regulates")),
        ("en_disputa", sum(1 for f in todas
                           if (clave(f["tf"]), clave(f["blanco"])) in disputadas)),
    ])
    atestiguadas = sum(1 for f in todas if f["atestiguado"] == "true")

    avisos = []
    if len(disputadas) != DISPUTADAS_DOCUMENTADAS:
        avisos.append(
            "etapa2/README.md habla de %d relaciones en disputa; en la tabla "
            "hay %d identificables (%s). Las otras %d no están marcadas en "
            "ningún dato, así que NO se restaron: el denominador honesto que "
            "publica este archivo es %d, no el %d de la documentación. Para "
            "restarlas hay que nombrarlas en un TSV y pasarlo con --disputadas."
            % (DISPUTADAS_DOCUMENTADAS, len(disputadas), origen_disputadas,
               max(0, DISPUTADAS_DOCUMENTADAS - len(disputadas)), len(honestas),
               HONESTO_DOCUMENTADO))
    if len(honestas) != HONESTO_DOCUMENTADO:
        avisos.append(
            "El honesto calculado (%d) no es el documentado (~%d). La resta "
            "9 + 6 + 5 de la documentación supone que las tres categorías no "
            "se solapan, y sí se solapan: MexT -> mexT es no atestiguada Y de "
            "signo sin resolver, y RhlR -> rpoS es de signo sin resolver Y en "
            "disputa. Manda el número calculado, que se puede reconstruir "
            "desde el TSV con la columna en_denominador_honesto."
            % (len(honestas), HONESTO_DOCUMENTADO))
    if not hay_tabla_operones:
        avisos.append(
            "No hay tabla de operones (%s). El lado del oro se sigue "
            "expandiendo mecánicamente, porque sus nombres están escritos a "
            "mano y no los puede fabricar el pipeline; el lado de la red no, "
            "así que una arista cuyo blanco sea un operón solo empareja por "
            "nombre exacto. Corre etapa2/construir_diccionario.py."
            % args.operones)
    if info_genes["fuentes_desconocidas"]:
        avisos.append(
            "El diccionario declara procedencias que no están en el enum "
            "de la seccion 2 del contrato (%s). No es prueba de circularidad, "
            "pero sí de que no lo "
            "escribió construir_diccionario.py, y con él no corrieron las "
            "invariantes anticircularidad de esa seccion."
            % ", ".join("%s=%d" % kv
                        for kv in info_genes["fuentes_desconocidas"].items()))
    contaminado = (
        sustancia["fraccion_explicada_por_el_oro"] is not None
        and sustancia["fraccion_explicada_por_el_oro"]
        >= UMBRAL_AVISO_CIRCULARIDAD)
    if contaminado:
        avisos.append(
            "El %.1f %% de los %d pares distintos que el pipeline propuso "
            "desde el corpus tiene sus dos extremos dentro del vocabulario "
            "que escribe el propio patrón de oro, y el umbral de aviso es "
            "%.0f %%. Un diccionario genuino mide 25.6 %% y uno copiado del "
            "oro 66.1 %%. Mientras eso no baje, la exhaustividad describe en "
            "buena parte el solapamiento del diccionario consigo mismo, así "
            "que este informe sale con código 2 aunque el acierto de signo "
            "despegue."
            % (100 * sustancia["fraccion_explicada_por_el_oro"],
               sustancia["pares_distintos"], 100 * UMBRAL_AVISO_CIRCULARIDAD))
    if probabilidades is None:
        avisos.append(
            "No encontré %s, así que NO comprobé que las cuatro "
            "probabilidades sumen 1 (la invariante de la seccion 4 del "
            "contrato). Esa comprobacion vive "
            "en clasificar.py, que es el único archivo que necesita torch: si "
            "las predicciones las escribió otra cosa, nadie ha mirado sus "
            "números. La columna `confianza` de red.tsv sale de ellos."
            % args.predicciones)
    solo_mecanica = [f for f in todas if f["_solo_con_expansion_mecanica"]]
    if solo_mecanica:
        avisos.append(
            "%d filas del oro se habrían dado por recuperadas si el nombre de "
            "la ARISTA se expandiera mecánicamente (%s). No se cuentan: la "
            "seccion 6.3 del contrato "
            "solo autoriza la tabla derivada del diccionario, y con la "
            "expansión mecánica una sola arista inventada LasR -> lasRIAB "
            "valía por tres filas del oro."
            % (len(solo_mecanica),
               ", ".join("%s->%s" % (f["tf"], f["blanco"])
                         for f in solo_mecanica[:8])))

    resumen = collections.OrderedDict()
    resumen["aviso"] = AVISO
    resumen["generado"] = datetime.datetime.now().replace(
        microsecond=0).isoformat()
    resumen["entradas"] = collections.OrderedDict([
        ("red", args.red), ("aristas", len(filas_red)),
        ("pares", args.pares), ("candidatos", n_pares),
        ("genes", args.genes), ("diccionario", info_genes),
        ("predicciones", args.predicciones),
        ("comprobacion_de_probabilidades", probabilidades or
         "no se hizo: no encontré el archivo de predicciones"),
        ("operones", args.operones if hay_tabla_operones else ""),
        ("oro", args.oro), ("collectf", args.collectf or ""),
    ])
    resumen["denominadores"] = collections.OrderedDict([
        ("crudo", len(todas)),
        ("atestiguadas", atestiguadas),
        ("honesto", len(honestas)),
        ("honesto_documentado", HONESTO_DOCUMENTADO),
        ("exclusiones", collections.OrderedDict([
            ("no_atestiguada", conteo_exclusiones.get("no_atestiguada", 0)),
            ("signo_no_resuelto", conteo_exclusiones.get("signo_no_resuelto", 0)),
            ("en_disputa", conteo_exclusiones.get("en_disputa", 0)),
            ("total", sum(conteo_exclusiones.values())),
            ("nota", "Reparto sin doble conteo: cada fila cae en una sola "
                     "categoria, por prioridad no_atestiguada > "
                     "signo_no_resuelto > en_disputa. La suma es el total que "
                     "se resta del crudo."),
        ])),
        ("categorias_con_solape", con_solape),
        ("origen_disputadas", origen_disputadas),
        ("que_significa", "crudo = las 190 filas del patrón. honesto = las "
                          "filas que el corpus puede sostener: sin las no "
                          "atestiguadas, sin las de signo no resuelto y sin "
                          "las que la literatura disputa."),
    ])
    resumen["avisos"] = avisos
    resumen["sustancia_del_diccionario"] = sustancia
    resumen["crudo"] = cruda
    resumen["honesto"] = metricas(honestas)
    resumen["linea_base_aleatoria"] = linea_base_aleatoria(
        honestas, resumen["honesto"], args.semilla,
        args.repeticiones_linea_base, args.mayoria)
    resumen["linea_base_aleatoria"]["crudo"] = linea_base_aleatoria(
        todas, cruda, args.semilla, args.repeticiones_linea_base,
        args.mayoria)
    mayoritaria = linea_base_mayoritaria(honestas)
    resumen["linea_base_mayoritaria"] = mayoritaria
    resumen["linea_base_mayoritaria"]["crudo"] = linea_base_mayoritaria(todas)
    despego = despega(resumen["linea_base_aleatoria"], mayoritaria)
    certifica = bool(despego) and not contaminado
    resumen["veredicto_del_signo"] = collections.OrderedDict([
        ("acierto_signo", resumen["honesto"]["acierto_signo"]),
        ("p_contra_el_azar",
         resumen["linea_base_aleatoria"]["acierto_signo"]["p_valor"]),
        ("p_contra_la_clase_mayoritaria", mayoritaria["p_valor"]),
        ("alfa", ALFA),
        ("despega_de_las_dos_lineas_base", despego),
        ("vocabulario_contaminado", contaminado),
        ("codigo_de_salida", 0 if certifica else 2),
        ("que_significa_el_codigo_de_salida",
         "0 = el acierto de signo despega de sus DOS líneas base (p_valor <= "
         "%s en las dos) y el vocabulario del pipeline no está explicado por "
         "el del oro. 2 = falla alguna de las tres cosas, o no hay ninguna "
         "fila con signo comparable, y entonces la cifra publicada no es un "
         "resultado. Los dos archivos se escriben en los dos casos, a "
         "propósito: la fila por fila del TSV es justo lo que hace falta para "
         "diagnosticar, y no escribirla dejaría sin evidencia a quien tenga "
         "que arreglarlo. El código 1 sigue significando lo de siempre, 'la "
         "entrada no sirve y no escribo nada'. La EXHAUSTIVIDAD no decide el "
         "código de salida: %s" % (ALFA, POR_QUE_SE_SATURA)),
        ("por_que_dos_lineas_base",
         "El sorteo uniforme dice si el pipeline hace algo más que tirar un "
         "dado; la clase mayoritaria dice si hace algo más que contestar "
         "siempre lo mismo. Son preguntas distintas y un clasificador "
         "constante pasaba la primera: medido, contestar siempre `activates` "
         "publicaba 69.8 % con «se distingue del azar (p = 0.005). Codigo 0»."),
    ])
    resumen["por_subsistema"] = desglosar(honestas, "subsistema")
    resumen["por_certeza"] = desglosar(honestas, "certeza_dominio")
    resumen["autorregulacion"] = collections.OrderedDict([
        ("aviso", "La autorregulación se excluye de la red por omisión "
                  "(sección 3.4 del contrato). "
                  "Va aparte porque ahí la precisión es mala por construcción."),
        ("filas_del_oro", sum(1 for f in todas if f["_autorregulacion"])),
        ("metricas", metricas([f for f in todas if f["_autorregulacion"]])),
    ])
    resumen["veredictos"] = collections.OrderedDict([
        ("crudo", dict(collections.Counter(f["veredicto"] for f in todas))),
        ("honesto", dict(collections.Counter(f["veredicto"] for f in honestas))),
    ])
    resumen["coincidencias"] = dict(collections.Counter(
        f["coincidencia"] for f in todas))
    resumen["equivalencia_operon"] = collections.OrderedDict([
        ("aviso", "20 de los blancos del oro son operones y ningún "
                  "diccionario de genes los tiene. La equivalencia se aplica "
                  "aquí, en el evaluador, no en el diccionario: al revés sería "
                  "circular (sección 6.3 del contrato)."),
        ("blancos_en_la_tabla_de_operones",
         sum(1 for f in todas if f["_operon_de_tabla"])),
        ("blancos_con_expansion_mecanica",
         sum(1 for f in todas if f["_operon_mecanico"])),
        ("filas_resueltas_por_operon",
         sum(1 for f in todas if f["_resuelta_por_operon"])),
        ("asimetria", "El nombre de la REFERENCIA (el oro, CollecTF) se "
                      "expande por tabla y también mecánicamente: son tablas "
                      "versionadas y escritas a mano, y el pipeline no puede "
                      "fabricar sus nombres. El nombre que produjo el PIPELINE "
                      "se expande solo por tabla. Sin esa asimetría, una sola "
                      "arista inventada LasR -> lasRIAB contaba como "
                      "recuperación de LasR->lasA, LasR->lasB y LasR->lasI a "
                      "la vez."),
        ("solo_con_expansion_mecanica_del_pipeline",
         sorted("%s->%s" % (f["tf"], f["blanco"]) for f in solo_mecanica)),
    ])
    resumen["fuera_de_diccionario"] = sorted(
        "%s->%s" % (f["tf"], f["blanco"]) for f in todas if not f["_resuelta"])
    resumen["cadenas_de_alias_ambiguas"] = ambiguas

    if args.collectf:
        if not os.path.exists(args.collectf):
            sys.exit("No encuentro %s." % args.collectf)
        tfs_del_oro = set(clave(f["tf"]) for f in oro)
        resumen["collectf"] = evaluar_collectf(
            args.collectf, red_expandida, diccionario, operones, tfs_del_oro)

    comentario = envolver(AVISO) + [
        "",
        "denominador crudo = %d filas; denominador honesto = %d filas "
        "(columna en_denominador_honesto)." % (len(todas), len(honestas)),
    ]
    for fila in todas:
        for k in [k for k in fila if k.startswith("_")]:
            del fila[k]
    escribir_tsv(args.salida, COLUMNAS_SALIDA, todas, comentario)
    escribir_json(args.resumen, resumen)

    print("")
    print("=" * 78)
    # Las mayúsculas acentuadas no existen en cp437, la página de códigos
    # de una consola de Windows en inglés, y un print con Ó ahí revienta
    # con UnicodeEncodeError. Los títulos van en caja mixta.
    print("Evaluación contra el patrón de oro")
    print("=" * 78)
    for linea in envolver(AVISO):
        print(linea)
    print("")
    print("Denominadores (los dos, sin ambigüedad):")
    print("  crudo    %3d filas   todas las del patrón" % len(todas))
    print("  honesto  %3d filas   el crudo menos %d filas excluidas"
          % (len(honestas), sum(conteo_exclusiones.values())))
    print("       categorías, con solape:  %d no atestiguadas, %d de signo no "
          "resuelto, %d en disputa"
          % (con_solape["no_atestiguada"], con_solape["signo_no_resuelto"],
             con_solape["en_disputa"]))
    print("       reparto sin doble conteo: %d + %d + %d = %d"
          % (conteo_exclusiones.get("no_atestiguada", 0),
             conteo_exclusiones.get("signo_no_resuelto", 0),
             conteo_exclusiones.get("en_disputa", 0),
             sum(conteo_exclusiones.values())))
    print("")
    imprimir_metricas("Sobre el denominador HONESTO (%d filas):" % len(honestas),
                      resumen["honesto"])
    print("")
    imprimir_linea_base(resumen["linea_base_aleatoria"])
    print("")
    imprimir_linea_mayoritaria(mayoritaria)
    print("")
    imprimir_sustancia(sustancia)
    print("")
    imprimir_metricas("Sobre el denominador CRUDO (%d filas):" % len(todas),
                      resumen["crudo"])
    print("")
    imprimir_desglose("Por subsistema (denominador honesto):",
                      resumen["por_subsistema"])
    imprimir_desglose("Por certeza de dominio (denominador honesto):",
                      resumen["por_certeza"])
    print("")
    print("  Veredictos (denominador honesto):")
    for nombre, n in sorted(resumen["veredictos"]["honesto"].items()):
        print("    %-32s %4d" % (nombre, n))
    if resumen["fuera_de_diccionario"]:
        print("")
        print("  Fuera del diccionario (%d): %s"
              % (len(resumen["fuera_de_diccionario"]),
                 ", ".join(resumen["fuera_de_diccionario"][:12])))
    if "collectf" in resumen:
        print("")
        print("  CollecTF, la referencia que el oro no vio (solo exhaustividad):")
        for grupo in ("en_el_oro", "fuera_del_oro"):
            b = resumen["collectf"][grupo]
            e = b["exhaustividad"]
            print("    %-14s %d TFs, %d pares, exh %s (%d/%d)"
                  % (grupo, b["tfs"], b["pares"], porcentaje(e), e["n"], e["d"]))
        print("    El grupo fuera_del_oro es el que dice si el pipeline")
        print("    encuentra relaciones que nadie le enseñó.")
    for aviso in avisos:
        print("")
        for linea in envolver("AVISO: " + aviso):
            print(linea)
    print("")
    print("Escrito %s" % args.salida)
    print("Escrito %s" % args.resumen)

    # El veredicto va al final, donde se lee, y decide el código de salida.
    print("")
    b = resumen["linea_base_aleatoria"]["acierto_signo"]
    if certifica:
        print("El acierto de signo despega de las dos lineas base: azar "
              "p = %.3f, clase" % b["p_valor"])
        print("mayoritaria (%s, %s) p = %.3f. Codigo 0."
              % (mayoritaria["clase_mayoritaria"],
                 cifra(mayoritaria["tasa_base"]).strip(),
                 mayoritaria["p_valor"]))
        return 0
    if despego is None:
        for linea in envolver(
                "NO HAY RESULTADO: ninguna fila del oro se recupero con signo "
                "comparable, asi que no hay nada que contrastar contra "
                "ninguna linea base. Los dos archivos estan escritos y la "
                "columna veredicto dice por que. Codigo de salida 2."):
            print(linea)
        return 2
    if despego and contaminado:
        for linea in envolver(
                "NO HAY RESULTADO: el acierto de signo (%s) si despega de sus "
                "dos lineas base, pero el %.1f %% de los pares que el pipeline "
                "propuso cae entero dentro del vocabulario del propio patron "
                "de oro. Con un diccionario asi la exhaustividad mide sobre "
                "todo su solapamiento consigo mismo, y la cifra no se puede "
                "citar. Los dos archivos estan escritos para poder "
                "diagnosticar. Codigo de salida 2."
                % (cifra(b["real"]).strip(),
                   100 * sustancia["fraccion_explicada_por_el_oro"])):
            print(linea)
        return 2
    p_may = mayoritaria["p_valor"]
    if b["p_valor"] > ALFA:
        motivo = ("no se distingue de asignar las clases al azar sobre los "
                  "mismos candidatos (%s de media, p = %.3f)"
                  % (cifra(b["azar_media"]).strip(), b["p_valor"]))
    else:
        motivo = ("no se distingue de contestar siempre '%s', que es la clase "
                  "mayoritaria de esas %d filas y acierta el %s sin leer una "
                  "palabra (p = %.3f)"
                  % (mayoritaria["clase_mayoritaria"],
                     mayoritaria["filas_comparables"],
                     cifra(mayoritaria["tasa_base"]).strip(), p_may))
    for linea in envolver(
            "NO HAY RESULTADO: el acierto de signo (%s) %s. Un clasificador "
            "roto se lee igual que este numero, asi que no es un resultado. "
            "Los dos archivos estan escritos para poder diagnosticar. Codigo "
            "de salida 2." % (cifra(b["real"]).strip(), motivo)):
        print(linea)
    return 2


if __name__ == "__main__":
    sys.exit(main())
