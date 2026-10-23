"""El contraste del bronce y de la red con la base curada (PLAN.md 2.4).

La base curada es la referencia externa del proyecto: sus relaciones existen
porque son ciertas, no porque una oración del corpus las diga. Contra ella se
hacen dos preguntas, cada una con su regla:

- ¿Llega el paso 1 a la evidencia? De las filas exigibles, cuántas tienen sus
  dos locus juntos en una oración candidata del bronce. La regla a) acepta
  cualquier oración del corpus y mide lo que el paso 3 podría juntar sumando
  artículos; la b) exige una oración del artículo que la fila cita y mide si
  el paso 1 recupera la evidencia citada. Es el techo del paso 1: lo que no
  coocurre en una candidata, el paso 2 no lo ve nunca.
- ¿La recupera la red? De esas mismas filas, cuántas son una arista de
  `red.tsv` en la dirección de la base, cuántas solo al revés, y si el signo
  coincide.

El denominador
--------------
Salen las filas de homología: el artículo citado no reporta la relación, y
aun con el texto completo a la mano la regla b cubre el 0.3 % de ellas. Salen
también las filas cuyos PMIDs están todos en el archivo de exclusiones, que es
por donde llega el artículo de 731 filas que el bronce no puede leer (PDF sin
XML): su PMID no se escribe en el repositorio. Una fila que cita ese artículo
junto con otro se queda, porque la regla es «todos sus PMIDs», y se cuenta
aparte (`citan_excluido_y_otro`), como las de homología que lo citan: con esa
regla y la homología primero salen 651 filas y no las 731 de PLAN.md 2.4. La
autorregulación se queda en el denominador y nunca cuenta como cubierta: el
bronce exige dos genes distintos por oración y `red.py` la descarta, así que
no es que no se encuentre, es que la regla la excluye por construcción.

El estrato BioBERT
------------------
Las filas con `Origen` BioBERT las propuso el modelo del asesor, con la misma
receta del run 22 que el modelo que clasifica los pares de la red. Su recall
mediría al modelo contra sus propias propuestas y saldría alto por
construcción: van en su estrato y fuera de la cifra principal.

El signo contra una línea base, y el techo de la red
----------------------------------------------------
Entre las exigibles hay más del doble de `+` que de `-` (1 238 contra 579 el
23-oct-2026), así que un acuerdo de signo alto puede salir de decir siempre
activates. Cada estrato lleva esa línea base: sobre las filas en que la red
resolvió el signo (acuerdo o contrario) y sobre todas las dirigidas con signo
en la base, donde la red se abstiene (regulates, mixto) y la línea base no.

La red sale de las oraciones candidatas del bronce: una fila que encuentra,
en cualquier dirección, tiene sus dos locus juntos en alguna candidata. La
cobertura de la regla a) con expansión sobre las filas de la cifra principal
es su techo (`techo_sin_biobert`).

Otra red
--------
Con `red` (`--red NOMBRE`) se contrasta `red_<NOMBRE>.tsv`, la que arma
`grn_red.consolidar` con otras reglas, en vez de `red.tsv`. Sus aristas
expandidas de un operón se omiten: no tienen evidencia propia, y la arista
del operón, que se queda en la red, ya da un par de locus por gen.

Confidencialidad
----------------
La base llega solo por argumento y su ruta no se imprime. Lo que sale fila por
fila (`cobertura_por_fila.tsv`) y la lista de aristas que la base no registra
(`candidatas_nuevas.tsv`: su complemento dice qué registra) derivan de ella y
van a la carpeta confidencial, que tiene que quedar fuera de toda copia de
git. Lo único publicable es el informe, que antes de escribirse pasa por
`reentrenar.verificar_publicable`: conteos, proporciones e intervalos, sin
locus, PMIDs ni rutas.

Las coincidencias dependen del reconocimiento de genes del bronce, que es por
diccionario: produce falsos positivos y no sustituye al reconocimiento de
entidades. Una coocurrencia es un candidato, no una relación.

Biblioteca estándar y Python 3.8: corre con el intérprete del entorno del
asesor sin instalar nada.
"""

import collections
import csv
import datetime
import glob
import io
import json
import os
import re

from grn_comun import archivos, procedencia, redes
from grn_verificacion import entrenamiento, evaluar, reentrenar, validacion

GRUPOS = ("todas", "en_corpus", "con_xml", "solo_abstract")
REGLAS = ("a", "b")
VARIANTES = ("con_expansion", "sin_expansion")
# La cifra principal junta los estratos que no son circulares; BioBERT se
# reporta aparte (ver el docstring del módulo).
ESTRATOS = ("historica", "ambos", "otro", "biobert")
PRINCIPAL = "sin_biobert"
# `+` contra activates y `-` contra represses. El `?` de la base no tiene signo
# con qué comparar, y la `d` nadie ha dicho qué significa (PLAN.md, pregunta 3).
ACUERDO = {"+": "activates", "-": "represses"}
SIGNOS_RED = ("activates", "represses", "regulates")
JUICIOS = ("acuerdo", "contrario", "regulates", "mixto")

NOMBRE_GRUPO = {"todas": "todas", "en_corpus": "en el corpus",
                "con_xml": "con XML", "solo_abstract": "solo abstract"}
NOMBRE_REGLA = {"a": "a) cualquier oración candidata",
                "b": "b) oración del artículo citado"}
NOMBRE_VARIANTE = {"con_expansion": "con expansión",
                   "sin_expansion": "sin expansión"}
NOMBRE_ESTRATO = {"sin_biobert": "sin BioBERT (la cifra principal)",
                  "historica": u"Histórica", "ambos": "Ambos",
                  "otro": "otro", "biobert": "BioBERT (circular, aparte)"}

SUFIJO_CANDIDATAS = "_oraciones_candidatas.csv"
SUFIJO_MENCIONES = "_menciones.csv"
ARCHIVO_POR_FILA = "cobertura_por_fila.tsv"
ARCHIVO_NUEVAS = "candidatas_nuevas.tsv"
ARCHIVO_REGISTRO = "contraste.json"

COLUMNAS_POR_FILA = (
    "fila_origen", "motivo", "regulador", "blanco", "signo", "origen",
    "pmids", "grupo", "autorregulacion",
    "a_con_expansion", "a_sin_expansion", "b_con_expansion",
    "b_sin_expansion", "red", "red_signo", "juicio_signo", "test",
    "red_test")
COLUMNAS_NUEVAS = ("regulador", "blanco", "signo", "n_aristas", "aristas",
                   "n_articulos", "pmids")

# PLAN.md 2.4, medido el 10-sep-2026 sobre la corrida 1. Es referencia y no
# criterio: el corpus de otra corrida tiene otros artículos con XML, y una
# base nueva cambia todo. Lo que sí detiene el contraste es el cotejo de la
# base (`reentrenar.BASE_ESPERADA`), que no depende del corpus.
REFERENCIA_DENOMINADOR = collections.OrderedDict([
    ("homologia", 2850), ("excluidas_por_archivo", 731), ("exigibles", 2003),
    ("en_corpus", 1488), ("con_xml", 791), ("solo_abstract", 697),
    ("autorregulacion", 43)])
CORRIDA_DE_REFERENCIA = 1
# (variante, regla, grupo) -> (cubiertas, filas). La tabla de PLAN.md 2.4 es
# con la expansión de operones; sin ella, la a) con XML bajaba a 37.9 %, que
# son las 53 filas que aportaba la expansión.
REFERENCIA_COBERTURA = collections.OrderedDict([
    (("con_expansion", "a", "todas"), (857, 2003)),
    (("con_expansion", "a", "en_corpus"), (656, 1488)),
    (("con_expansion", "a", "con_xml"), (353, 791)),
    (("con_expansion", "a", "solo_abstract"), (303, 697)),
    (("con_expansion", "b", "todas"), (346, 2003)),
    (("con_expansion", "b", "en_corpus"), (346, 1488)),
    (("con_expansion", "b", "con_xml"), (239, 791)),
    (("con_expansion", "b", "solo_abstract"), (107, 697)),
    (("sin_expansion", "a", "con_xml"), (300, 791)),
])

_PMID = re.compile(r"^[0-9]{1,9}$")


def _nada(_):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _pmid(valor):
    """El PMID como texto sin ceros a la izquierda, o None si no es número."""
    texto = str(valor if valor is not None else "").strip()
    if not _PMID.match(texto) or int(texto) == 0:
        return None
    return str(int(texto))


def _loci_de_celda(celda):
    """Los locus de una celda «a;b;c» del bronce. Lo que no tiene forma de
    locus de PAO1 se ignora: no se puede comparar con la base."""
    salida = set()
    for parte in (celda or "").split(";"):
        locus = parte.strip().upper()
        if validacion.LOCUS.match(locus):
            salida.add(locus)
    return salida


def _loci_de_lista(valor):
    """Los locus de PAO1 de una lista de `pares.jsonl` (`tf_locus`)."""
    if valor is None:
        return set()
    if isinstance(valor, str):
        valor = [valor]
    return set(str(x).strip().upper() for x in valor
               if validacion.LOCUS.match(str(x).strip().upper()))


def _indices(encabezado, columnas, que):
    faltan = [c for c in columnas if c not in encabezado]
    if faltan:
        raise ValueError("A %s le faltan las columnas %s."
                         % (que, ", ".join(faltan)))
    return dict((c, encabezado.index(c)) for c in columnas)


def _celda_de(valores, indice, columna):
    i = indice.get(columna)
    if i is None or i >= len(valores):
        return ""
    return valores[i]


def _filas_csv(ruta, columnas, que, opcionales=(), delimitador=",",
               sin_comillas=False):
    """(columnas opcionales presentes, generador de {columna: valor}).

    Los TSV de `red.py` no entrecomillan: leídos con el `csv` por omisión,
    una oración que empezara con comillas se comería las líneas siguientes
    hasta la próxima comilla. Los CSV del bronce sí entrecomillan.
    """
    f = io.open(ruta, encoding="utf-8-sig", newline="")
    try:
        lector = csv.reader(f, delimiter=delimitador,
                            quoting=csv.QUOTE_NONE if sin_comillas
                            else csv.QUOTE_MINIMAL)
        encabezado = next(lector, None) or []
        indice = _indices(encabezado, columnas, que)
        presentes = tuple(c for c in opcionales if c in encabezado)
        for c in presentes:
            indice[c] = encabezado.index(c)
    except Exception:
        f.close()
        raise

    def filas():
        with f:
            for valores in lector:
                if not any(v.strip() for v in valores):
                    continue
                yield dict((c, _celda_de(valores, indice, c)) for c in indice)
    return presentes, filas()


# ------------------------------------------------------------------ bronce

def documentos_del_bronce(ruta_menciones):
    """{pmid: 'xml' o 'abstract'} de los artículos que el bronce leyó.

    Un PMID es de XML si alguna de sus unidades viene del texto completo: con
    el XML a la mano, el bronce leyó el artículo entero y no solo el resumen.
    Hoy el bronce no conoce otra fuente (`identificar.piezas_de_documento`);
    cualquiera que se agregue cuenta como abstract hasta que alguien decida
    otra cosa.

    Se lee del CSV de menciones y no del de candidatas: un artículo sin
    ninguna candidata también está en el corpus, y sus filas cuentan en el
    grupo «en el corpus». Uno sin ninguna mención (ni la del organismo) no
    aparece en ninguno de los dos y cuenta como fuera del corpus: el grupo
    «en el corpus» que sale de aquí es una cota inferior.
    """
    fuentes = collections.defaultdict(set)
    _, filas = _filas_csv(ruta_menciones, ("pmid", "fuente_texto"),
                          "el CSV de menciones")
    for numero, fila in enumerate(filas, 2):
        pmid = _pmid(fila["pmid"])
        if pmid is None:
            raise ValueError("El CSV de menciones, línea %d: el pmid no es "
                             "un número." % numero)
        fuentes[pmid].add(fila["fuente_texto"].strip())
    return dict((p, "xml" if "xml" in f else "abstract")
                for p, f in fuentes.items())


def _leer_candidatas(ruta_candidatas):
    """([(pmid, locus, expandidos)], corridas, trae_expandidos).

    Una sola lectura del CSV para las dos variantes: el de la corrida 4 pesa
    17 MB.
    """
    presentes, filas = _filas_csv(
        ruta_candidatas, ("pmid", "genes_locus_tag"),
        "el CSV de oraciones candidatas",
        opcionales=("genes_expandidos", "corrida_id"))
    oraciones, corridas = [], set()
    for numero, fila in enumerate(filas, 2):
        pmid = _pmid(fila["pmid"])
        if pmid is None:
            raise ValueError("El CSV de oraciones candidatas, línea %d: el "
                             "pmid no es un número." % numero)
        oraciones.append((pmid, _loci_de_celda(fila["genes_locus_tag"]),
                          _loci_de_celda(fila.get("genes_expandidos"))))
        corrida = (fila.get("corrida_id") or "").strip()
        if corrida.isdigit():
            corridas.add(int(corrida))
    return oraciones, corridas, "genes_expandidos" in presentes


def _pares(oraciones, expandir):
    cualquiera = set()
    por_pmid = collections.defaultdict(set)
    for pmid, locus, expandidos in oraciones:
        juntos = sorted(locus | expandidos if expandir else locus)
        if len(juntos) < 2:
            continue
        del_articulo = por_pmid[pmid]
        for i in range(len(juntos)):
            for j in range(i + 1, len(juntos)):
                par = (juntos[i], juntos[j])
                cualquiera.add(par)
                del_articulo.add(par)
    return cualquiera, dict(por_pmid)


def pares_del_bronce(ruta_candidatas, expandir=True):
    """(cualquiera, por_pmid): los pares no ordenados de locus que coocurren
    en una oración candidata.

    `cualquiera` es el conjunto del corpus entero (regla a); `por_pmid`, uno
    por artículo (regla b). Un par es la tupla (menor, mayor): la coocurrencia
    no tiene dirección.

    Con `expandir`, los locus de la oración son `genes_locus_tag` más
    `genes_expandidos`, así que un operón nombrado cuenta por sus genes, como
    en el cruce de PLAN.md 2.4. La expansión sale del catálogo y no del texto:
    una oración que solo nombra `mexAB-oprM` pone juntos a sus tres genes, y
    una fila de la base entre dos genes del mismo operón queda cubierta sin
    que el texto la diga. Sin expandir, solo los genes que el texto nombra.
    """
    oraciones, _, _ = _leer_candidatas(ruta_candidatas)
    return _pares(oraciones, expandir)


# ------------------------------------------------------------- denominador

def motivo_de(fila, excluir):
    """'homologia', 'excluida_por_archivo' o 'exigible'.

    La homología va primero, como en PLAN.md 2.4 (5 584 − 2 850 − 731): una
    fila de homología del artículo excluido cuenta como homología. Una fila
    sin PMID se queda: «todos sus PMIDs en el archivo» no se cumple con
    ninguno, y quitarla sería decidir algo que el archivo no dice.
    """
    if fila["homologia"]:
        return "homologia"
    if excluir and fila["pmids"] and all(p in excluir for p in fila["pmids"]):
        return "excluida_por_archivo"
    return "exigible"


def _concentracion(filas, cuantos=5):
    """Cuántas filas citan alguno de los `cuantos` artículos con más filas.

    Las filas de un mismo artículo no son independientes: si pocos artículos
    sostienen muchas, el intervalo de Wilson, que las trata como sueltas, es
    optimista. PLAN.md 2.4: cinco PMIDs sostenían el 32.1 % del denominador.
    """
    por_pmid = collections.Counter()
    for f in filas:
        for p in set(f["pmids"]):
            por_pmid[p] += 1
    mayores = set(p for p, _ in sorted(por_pmid.items(),
                                       key=lambda x: (-x[1], int(x[0])))
                  [:cuantos])
    return sum(1 for f in filas if mayores & set(f["pmids"]))


def denominador(interacciones, excluir=()):
    """(exigibles, conteos): las filas sobre las que se mide, y por qué
    salieron las demás.

    Quita las filas de homología (`homologia` de `validacion.normalizar`, que
    las reconoce porque `Reference` dice «homolog») y las filas cuyos PMIDs
    están todos en `excluir`. La autorregulación se queda y se cuenta aparte,
    porque nunca puede contar como cubierta. Los conteos son solo números.

    Dos conteos concilian con PLAN.md 2.4, que restó 731 filas por el
    artículo excluido: `citan_excluido_y_otro`, las exigibles que lo citan
    junto con otro artículo y se quedan por la regla «todos sus PMIDs», y
    `homologia_que_cita_excluido`, las que lo citan pero ya salieron por
    homología. Citar el excluido es citar algún PMID de `excluir`.
    """
    excluir = set(excluir or ())
    c = collections.OrderedDict([
        ("base", 0), ("homologia", 0), ("excluidas_por_archivo", 0),
        ("exigibles", 0), ("autorregulacion", 0), ("sin_pmid", 0),
        ("citan_excluido_y_otro", 0), ("homologia_que_cita_excluido", 0),
        ("signo", collections.OrderedDict(
            (s, 0) for s in validacion.SIGNOS + ("ilegible",))),
        ("origen", collections.OrderedDict(
            (o, 0) for o in validacion.ORIGENES)),
        ("en_los_5_articulos_mayores", 0),
    ])
    exigibles = []
    for fila in interacciones:
        c["base"] += 1
        cita_excluido = any(p in excluir for p in fila["pmids"])
        motivo = motivo_de(fila, excluir)
        if motivo == "homologia":
            c["homologia"] += 1
            if cita_excluido:
                c["homologia_que_cita_excluido"] += 1
            continue
        if motivo == "excluida_por_archivo":
            c["excluidas_por_archivo"] += 1
            continue
        exigibles.append(fila)
        c["exigibles"] += 1
        if cita_excluido:
            # Exigible y citando al excluido: tiene por fuerza otro PMID
            # fuera del archivo.
            c["citan_excluido_y_otro"] += 1
        if fila["regulador"] == fila["blanco"]:
            c["autorregulacion"] += 1
        if not fila["pmids"]:
            c["sin_pmid"] += 1
        signo = fila["signo"] if fila["signo"] in c["signo"] else "ilegible"
        c["signo"][signo] += 1
        origen = fila["origen"] if fila["origen"] in c["origen"] else "otro"
        c["origen"][origen] += 1
    c["en_los_5_articulos_mayores"] = _concentracion(exigibles)
    return exigibles, c


# --------------------------------------------------------------- cobertura

def grupo_de(fila, docs):
    """'con_xml', 'solo_abstract' o 'fuera', según los artículos que cita.

    Con un artículo del corpus que tenga XML basta: el bronce pudo leer ahí
    la evidencia completa, aunque la fila cite también otros.
    """
    fuentes = [docs[p] for p in fila["pmids"] if p in docs]
    if not fuentes:
        return "fuera"
    return "con_xml" if "xml" in fuentes else "solo_abstract"


def _par(a, b):
    return (a, b) if a <= b else (b, a)


def cubierta(fila, pares, regla):
    """Si la fila coocurre en una candidata, por la regla 'a' o la 'b'.

    `pares` es lo que devuelve `pares_del_bronce`. La autorregulación se
    decide antes de mirar: el bronce exige dos genes distintos por oración,
    así que una fila «X regula a X» no puede salir, y `evaluar_cobertura_bronce`
    ya contó de más cuando se miraba después.
    """
    if fila["regulador"] == fila["blanco"]:
        return False
    clave = _par(fila["regulador"], fila["blanco"])
    cualquiera, por_pmid = pares
    if regla == "a":
        return clave in cualquiera
    return any(clave in por_pmid.get(p, ()) for p in fila["pmids"])


def cobertura_bronce(exigibles, docs, pares):
    """La cobertura del bronce por regla, grupo y variante. Solo números.

    `pares`: {'con_expansion': (cualquiera, por_pmid), 'sin_expansion':
    (...)}, como los da `pares_del_bronce`; la variante que falte no se mide.
    Grupos: todas las filas; las que citan algún artículo del corpus; y de
    esas, las que citan alguno con XML y las que solo tienen abstract. Cada
    cifra es `evaluar.proporcion`, con su intervalo de Wilson. La
    autorregulación queda en el denominador y se cuenta aparte, y
    `solo_por_expansion` dice cuántas filas cubre solo la expansión.
    """
    variantes = [v for v in VARIANTES if v in pares]
    n = collections.Counter()
    auto = collections.Counter()
    cubiertas = collections.Counter()
    solo_expansion = collections.Counter()
    for fila in exigibles:
        grupo = grupo_de(fila, docs)
        grupos = (("todas",) if grupo == "fuera"
                  else ("todas", "en_corpus", grupo))
        es_auto = fila["regulador"] == fila["blanco"]
        for g in grupos:
            n[g] += 1
            if es_auto:
                auto[g] += 1
        for regla in REGLAS:
            hecho = dict((v, cubierta(fila, pares[v], regla))
                         for v in variantes)
            for v in variantes:
                if hecho[v]:
                    for g in grupos:
                        cubiertas[(v, regla, g)] += 1
            if hecho.get("con_expansion") and hecho.get("sin_expansion") \
                    is False:
                for g in grupos:
                    solo_expansion[(regla, g)] += 1
    salida = collections.OrderedDict()
    salida["n"] = collections.OrderedDict((g, n[g]) for g in GRUPOS)
    salida["autorregulacion"] = collections.OrderedDict(
        (g, auto[g]) for g in GRUPOS)
    for v in variantes:
        salida[v] = collections.OrderedDict(
            (r, collections.OrderedDict(
                (g, evaluar.proporcion(cubiertas[(v, r, g)], n[g]))
                for g in GRUPOS))
            for r in REGLAS)
    if len(variantes) == len(VARIANTES):
        salida["solo_por_expansion"] = collections.OrderedDict(
            (r, collections.OrderedDict(
                (g, solo_expansion[(r, g)]) for g in GRUPOS))
            for r in REGLAS)
    return salida


def estrato_de(fila):
    """'historica', 'ambos', 'biobert' u 'otro': el estrato de `Origen`.

    Una sola definición para el recall de la red y para su techo: si cada uno
    decidiera por su cuenta qué filas son «sin BioBERT», el techo se mediría
    sobre otras filas que la cifra que acota.
    """
    return fila["origen"] if fila["origen"] in ESTRATOS else "otro"


def techo_sin_biobert(exigibles, docs, pares, aristas=None):
    """La cobertura del bronce en las filas de la cifra principal de la red.

    La red sale de las oraciones candidatas del bronce, que el puente vuelve a
    leer con el léxico de etapa2: una fila que la red encuentra, en cualquier
    dirección, tiene sus dos locus juntos en alguna candidata. La regla a)
    con expansión es su techo. Se mide sobre las mismas filas que el recall
    «sin BioBERT» (`estrato_de`), con las reglas, variantes y grupos de
    `cobertura_bronce`.

    `red_cualquiera_fuera_de_a` cuenta las filas que la red encuentra y la
    regla a) con expansión no cubre. Por construcción debería ser 0; si no lo
    es, es un dato y no un error: el puente llevó a locus en una oración algo
    que el bronce no llevó, o lo llevó a otro. None sin red.
    """
    filas = [f for f in exigibles if estrato_de(f) != "biobert"]
    fuera = None
    if aristas is not None and "con_expansion" in pares:
        fuera = sum(1 for f in filas
                    if en_red(f, aristas)[0] != "no"
                    and not cubierta(f, pares["con_expansion"], "a"))
    return collections.OrderedDict([
        ("n", len(filas)),
        ("cobertura", cobertura_bronce(filas, docs, pares)),
        ("red_cualquiera_fuera_de_a", fuera)])


# --------------------------------------------------------------------- red

def _locus_de_pares(ruta_pares, necesarios):
    """{id_par: (tf_locus, target_locus)} de los `id_par` que se piden.

    `pares.jsonl` pasa de 70 MB: se recorre una vez y se guarda solo lo que
    la red usa.
    """
    locus = {}
    with io.open(ruta_pares, encoding="utf-8") as f:
        for numero, linea in enumerate(f, 1):
            if not linea.strip():
                continue
            try:
                par = json.loads(linea)
            except ValueError:
                raise ValueError("pares.jsonl, línea %d: no es JSON." % numero)
            if not isinstance(par, dict):
                raise ValueError("pares.jsonl, línea %d: no es un objeto."
                                 % numero)
            i = str(par.get("id_par"))
            if i in necesarios:
                locus[i] = (_loci_de_lista(par.get("tf_locus")),
                            _loci_de_lista(par.get("target_locus")))
    return locus


def _verdadero(valor):
    """Un booleano de los TSV de `red.py`, que escribe true/false."""
    return (valor or "").strip().lower() in ("true", "1")


def aristas_en_locus(ruta_red, ruta_evidencias, ruta_pares):
    """({(regulador, blanco): [arista, ...]}, conteos).

    Una arista de `red.tsv` tiene nombres (MexT, mexT) y no locus. Sus locus
    salen de sus evidencias: cada una trae un `id_par`, y el par de
    `pares.jsonl` trae `tf_locus` y `target_locus`, con el operón ya
    expandido a sus genes. Una arista hacia un operón da un par dirigido por
    gen. Cada arista del resultado lleva su `signo` y sus `pmids` (los de
    `red.tsv` y los de sus evidencias).

    Dos aristas caen en el mismo par cuando el texto nombra al gen y a la
    proteína, o cuando un operón se expande: por eso cada par lleva una
    lista. Un par de un locus consigo mismo no se guarda (es
    autorregulación). Un `id_par` de las evidencias que no está en
    `pares.jsonl` detiene todo: la red y los pares no son de la misma
    corrida.

    Una red de `grn_red.consolidar` con otras reglas trae dos columnas que
    aquí son opcionales. Las filas con `expandida_de` se omiten y se cuentan
    en `expandidas_omitidas`: no tienen evidencia propia (la suya es la de la
    arista del operón, que se queda en la red) y esa arista ya da un par de
    locus por gen. Una fila con `autorregulacion` cuyo par queda en un solo
    locus se cuenta en `solo_autorregulacion` y no en `sin_locus`: tiene
    locus de PAO1, lo que no tiene es un segundo gen.
    """
    nombre_red = os.path.basename(ruta_red)
    nombre_evidencias = os.path.basename(ruta_evidencias)
    _, red = _filas_csv(ruta_red, ("tf", "blanco", "signo", "pmids"),
                        nombre_red, opcionales=("expandida_de",
                                                "autorregulacion"),
                        delimitador="\t", sin_comillas=True)
    red = list(red)
    ids = collections.defaultdict(set)
    pmids_ev = collections.defaultdict(set)
    _, evidencias = _filas_csv(ruta_evidencias,
                               ("tf", "blanco", "id_par", "pmid"),
                               nombre_evidencias, delimitador="\t",
                               sin_comillas=True)
    for fila in evidencias:
        clave = (fila["tf"], fila["blanco"])
        ids[clave].add(fila["id_par"].strip())
        pmid = _pmid(fila["pmid"])
        if pmid:
            pmids_ev[clave].add(pmid)
    necesarios = set()
    for valores in ids.values():
        necesarios |= valores
    locus = _locus_de_pares(ruta_pares, necesarios)
    faltan = len(necesarios - set(locus))
    if faltan:
        raise ValueError(
            "%d id_par de %s no están en pares.jsonl: la red y los pares no "
            "son de la misma corrida. Corre antes el paso red del flujo."
            % (faltan, nombre_evidencias))

    c = collections.Counter()
    por_signo = collections.Counter()
    por_par = collections.defaultdict(list)
    for fila in red:
        c["aristas"] += 1
        clave = (fila["tf"], fila["blanco"])
        signo = fila["signo"].strip()
        if signo not in SIGNOS_RED:
            raise ValueError("%s trae una arista con un signo que no es "
                             "activates, represses ni regulates." % nombre_red)
        if (fila.get("expandida_de") or "").strip():
            # Antes de exigir evidencia: en red_recomendada.tsv de la corrida
            # 4, 838 de las 1 533 expandidas no tienen ninguna bajo su nombre,
            # y el contraste se detenía en la primera. Las otras la tienen
            # porque una arista observada se llama igual, y esa se cuenta
            # sola.
            c["expandidas_omitidas"] += 1
            continue
        if clave not in ids:
            raise ValueError("Una arista de %s no tiene evidencias en %s: no "
                             "son de la misma corrida."
                             % (nombre_red, nombre_evidencias))
        dirigidos = set()
        de_tf, de_blanco = set(), set()
        for i in ids[clave]:
            tf_locus, target_locus = locus[i]
            de_tf |= tf_locus
            de_blanco |= target_locus
            for a in tf_locus:
                for b in target_locus:
                    if a != b:
                        dirigidos.add((a, b))
        if not dirigidos:
            if (_verdadero(fila.get("autorregulacion")) and de_tf
                    and de_tf == de_blanco and len(de_tf) == 1):
                c["solo_autorregulacion"] += 1
            else:
                c["sin_locus"] += 1
            continue
        c["con_locus"] += 1
        por_signo[signo] += 1
        if len(dirigidos) > 1:
            c["expandidas"] += 1
        pmids = set(p for p in (_pmid(x) for x in fila["pmids"].split("|"))
                    if p)
        arista = {"tf": fila["tf"], "blanco": fila["blanco"], "signo": signo,
                  "pmids": frozenset(pmids | pmids_ev[clave])}
        for par in dirigidos:
            por_par[par].append(arista)
    # aristas = con_locus + sin_locus + solo_autorregulacion +
    # expandidas_omitidas; `expandidas` son las de más de un par de locus.
    conteos = collections.OrderedDict([
        ("aristas", c["aristas"]), ("con_locus", c["con_locus"]),
        ("sin_locus", c["sin_locus"]),
        ("solo_autorregulacion", c["solo_autorregulacion"]),
        ("expandidas_omitidas", c["expandidas_omitidas"]),
        ("expandidas", c["expandidas"]),
        ("pares_locus", len(por_par)),
        ("por_signo", collections.OrderedDict(
            (s, por_signo[s]) for s in SIGNOS_RED)),
    ])
    return dict(por_par), conteos


def signo_par(aristas):
    """El signo de un par de locus: el de sus aristas si todas dicen lo
    mismo, «mixto» si no, None si no hay ninguna. No se vota: resolver por
    mayoría entre dos nombres del mismo gen sería decidir un signo que
    `red.py` no decidió."""
    signos = set(a["signo"] for a in aristas)
    if not signos:
        return None
    if len(signos) == 1:
        return signos.pop()
    return "mixto"


def _vistas(aristas, solo):
    if solo is None:
        return list(aristas)
    return [a for a in aristas if a["pmids"] & solo]


def en_red(fila, aristas, solo=None):
    """(estado, signo) de una fila de la base en la red.

    `estado` es 'dirigido' (la red tiene regulador → blanco), 'inverso' (solo
    blanco → regulador: el par es correcto y la dirección no) o 'no'. `signo`
    es el de las aristas dirigidas (ver `signo_par`). Con `solo`, cuentan
    solo las aristas con evidencia en esos artículos.
    """
    a, b = fila["regulador"], fila["blanco"]
    if a == b:
        return "no", None
    directas = _vistas(aristas.get((a, b), ()), solo)
    if directas:
        return "dirigido", signo_par(directas)
    if _vistas(aristas.get((b, a), ()), solo):
        return "inverso", None
    return "no", None


def juicio_signo(signo_base, signo_red):
    """'acuerdo', 'contrario', 'regulates' o 'mixto'; None si la fila no
    tiene signo que juzgar."""
    if signo_base not in ACUERDO or signo_red is None:
        return None
    if signo_red == ACUERDO[signo_base]:
        return "acuerdo"
    if signo_red in ACUERDO.values():
        return "contrario"
    return signo_red


def en_test(fila, solo):
    """'evaluada' si todos sus PMIDs están en `solo`, 'mezcla' si solo
    algunos, 'fuera' si ninguno (o si no tiene PMID)."""
    dentro = [p in solo for p in fila["pmids"]]
    if dentro and all(dentro):
        return "evaluada"
    if any(dentro):
        return "mezcla"
    return "fuera"


def recall_red(exigibles, aristas, solo_pmids=None):
    """El recall de la red por estrato de `Origen`. Solo números.

    Por fila: dirigido, solo al revés (inverso) o en cualquier dirección. El
    signo se juzga en las filas encontradas en su dirección y con `+` o `-`
    en la base; una arista `regulates` o un par «mixto» no es acuerdo, y se
    cuentan aparte. La autorregulación queda en el denominador y nunca se
    encuentra, como en la cobertura.

    Estratos: Histórica, Ambos, otro y BioBERT, más «sin BioBERT», la cifra
    principal, que junta los tres primeros. BioBERT va aparte porque esas
    filas las propuso el modelo del asesor con la receta del run 22, la del
    modelo de la red: su recall sería circular.

    Por estrato van también la `orientacion` (dirigido entre dirigido más
    solo al revés: de lo que la red encuentra, cuánto va en la dirección de
    la base) y la línea base de decir siempre activates, sin la cual un
    acuerdo alto no dice si la red lee el signo (ver el docstring del
    módulo). `acuerdo_si_da_signo` y `linea_base_siempre_mas` se miden en las
    `resueltas`, las filas en que la red dijo activates o represses (acuerdo
    más contrario); `linea_base_siempre_mas_con_abstencion`, en todas las
    dirigidas con signo en la base, contra el `acuerdo` de siempre: ahí la
    red se abstiene en las regulates y las mixtas, y la línea base no.

    `solo_pmids`, para una red armada con un modelo entrenado con la base: se
    evalúan solo las filas cuyos PMIDs están todos en ese conjunto (los de
    test), y de la red solo cuentan las aristas con evidencia en alguno de
    esos artículos. Una fila que cita un artículo de test y otro que no pudo
    entrar al entrenamiento por el otro: queda fuera y se cuenta como
    «mezcla». Cuidado: el signo de una arista lo decidió `red.py` con todas
    sus evidencias, también las de artículos de entrenamiento.
    """
    solo = set(solo_pmids) if solo_pmids is not None else None
    filas = list(exigibles)
    reparto = None
    if solo is not None:
        clases = collections.Counter(en_test(f, solo) for f in filas)
        filas = [f for f in filas if en_test(f, solo) == "evaluada"]
        reparto = collections.OrderedDict([
            ("pmids", len(solo)), ("evaluadas", clases["evaluada"]),
            ("mezcla", clases["mezcla"]), ("fuera", clases["fuera"])])
    acumulado = collections.defaultdict(collections.Counter)
    for fila in filas:
        estrato = estrato_de(fila)
        destinos = ((estrato,) if estrato == "biobert"
                    else (estrato, PRINCIPAL))
        estado, signo = en_red(fila, aristas, solo)
        juicio = juicio_signo(fila["signo"], signo) \
            if estado == "dirigido" else None
        mas = fila["signo"] == "+"
        for d in destinos:
            c = acumulado[d]
            c["n"] += 1
            if fila["regulador"] == fila["blanco"]:
                c["autorregulacion"] += 1
            c[estado] += 1
            if juicio:
                c["con_signo"] += 1
                c[juicio] += 1
                if mas:
                    c["con_signo_mas"] += 1
                if juicio in ("acuerdo", "contrario"):
                    c["resueltas"] += 1
                    if mas:
                        c["resueltas_mas"] += 1
    estratos = collections.OrderedDict()
    for nombre in (PRINCIPAL,) + ESTRATOS:
        c = acumulado[nombre]
        estratos[nombre] = collections.OrderedDict([
            ("n", c["n"]), ("autorregulacion", c["autorregulacion"]),
            ("dirigido", evaluar.proporcion(c["dirigido"], c["n"])),
            ("inverso", evaluar.proporcion(c["inverso"], c["n"])),
            ("cualquiera", evaluar.proporcion(c["dirigido"] + c["inverso"],
                                              c["n"])),
            ("orientacion", evaluar.proporcion(
                c["dirigido"], c["dirigido"] + c["inverso"])),
            ("signo", collections.OrderedDict([
                ("n", c["con_signo"]),
                ("acuerdo", evaluar.proporcion(c["acuerdo"], c["con_signo"])),
                ("contrario", c["contrario"]),
                ("regulates", c["regulates"]),
                ("mixto", c["mixto"]),
                ("resueltas", c["resueltas"]),
                ("resueltas_mas", c["resueltas_mas"]),
                ("con_signo_mas", c["con_signo_mas"]),
                ("acuerdo_si_da_signo", evaluar.proporcion(
                    c["acuerdo"], c["resueltas"])),
                ("linea_base_siempre_mas", evaluar.proporcion(
                    c["resueltas_mas"], c["resueltas"])),
                ("linea_base_siempre_mas_con_abstencion", evaluar.proporcion(
                    c["con_signo_mas"], c["con_signo"]))])),
        ])
    return collections.OrderedDict([("solo_pmids", reparto),
                                    ("estratos", estratos)])


def curados_de(interacciones):
    """Todo par de la base en las dos direcciones, de TODA fila: también las
    de homología, las de BioBERT y las del artículo excluido. Lo que la base
    registra de cualquier forma no es nuevo."""
    curados = set()
    for fila in interacciones:
        curados.add((fila["regulador"], fila["blanco"]))
        curados.add((fila["blanco"], fila["regulador"]))
    return curados


def candidatas_nuevas(aristas, curados):
    """Las aristas que la base no registra en ninguna dirección, por par de
    locus. Es una lista confidencial: lo que falta en ella es lo que la base
    sí registra."""
    salida = []
    for (a, b) in sorted(aristas):
        if (a, b) in curados or (b, a) in curados:
            continue
        lista = aristas[(a, b)]
        pmids = set()
        for arista in lista:
            pmids |= arista["pmids"]
        salida.append(collections.OrderedDict([
            ("regulador", a), ("blanco", b), ("signo", signo_par(lista)),
            ("n_aristas", len(lista)),
            ("aristas", ";".join(sorted(set(
                "%s>%s" % (x["tf"], x["blanco"]) for x in lista)))),
            ("n_articulos", len(pmids)),
            ("pmids", "|".join(sorted(pmids, key=int))),
        ]))
    return salida


def _conteo_nuevas(nuevas):
    por_signo = collections.Counter(n["signo"] for n in nuevas)
    return collections.OrderedDict([
        ("pares", len(nuevas)),
        ("por_signo", collections.OrderedDict(
            (s, por_signo[s]) for s in SIGNOS_RED + ("mixto",)))])


# ------------------------------------------------------------- por fila

def filas_por_fila(interacciones, excluir, docs, pares, aristas=None,
                   solo_pmids=None):
    """Una fila por interacción de la base: su motivo, su grupo y qué la
    cubre. Es lo que va a la carpeta confidencial: lleva locus y PMIDs."""
    excluir = set(excluir or ())
    solo = set(solo_pmids) if solo_pmids is not None else None
    salida = []
    for fila in interacciones:
        r = collections.OrderedDict([
            ("fila_origen", fila["fila_origen"]),
            ("motivo", motivo_de(fila, excluir)),
            ("regulador", fila["regulador"]), ("blanco", fila["blanco"]),
            ("signo", fila["signo"] if fila["signo"] else "ilegible"),
            ("origen", fila["origen"]),
            ("pmids", "|".join(fila["pmids"])),
            ("grupo", grupo_de(fila, docs)),
            ("autorregulacion", fila["regulador"] == fila["blanco"]),
        ])
        for regla in REGLAS:
            for v in VARIANTES:
                if v in pares:
                    r["%s_%s" % (regla, v)] = cubierta(fila, pares[v], regla)
        if aristas is not None:
            estado, signo = en_red(fila, aristas)
            r["red"] = estado
            r["red_signo"] = signo
            r["juicio_signo"] = (juicio_signo(fila["signo"], signo)
                                 if estado == "dirigido" else None)
            if solo is not None:
                r["test"] = en_test(fila, solo)
                if r["test"] == "evaluada":
                    r["red_test"] = en_red(fila, aristas, solo)[0]
        salida.append(r)
    return salida


# ------------------------------------------------------------- el informe

def _n(x):
    """Un entero con los miles separados por espacio, como PLAN.md.

    Además de leerse mejor: siete u ocho cifras seguidas tienen forma de PMID
    y el filtro de publicación rechazaría el informe entero por un conteo.
    """
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "sí" if x else "no"
    if isinstance(x, int):
        return format(x, ",").replace(",", " ")
    return str(x)


def _cuantas(n, singular, plural):
    """«1 fila», «2 filas»: con la base real sale una sola fila sin PMID."""
    return "%s %s" % (_n(n), singular if n == 1 else plural)


def _enumerar(partes):
    """«a», «a y b», «a, b y c»."""
    if len(partes) < 2:
        return "".join(partes)
    return "%s y %s" % (", ".join(partes[:-1]), partes[-1])


def _pct(p):
    if not p or not p.get("n"):
        return "—"
    return "%.1f %%" % (100.0 * p["k"] / p["n"])


def _prop(p):
    if not p or not p.get("n"):
        return "—"
    bajo, alto = p["ic95"]
    return "%s/%s (%.1f %%) [%.1f, %.1f]" % (
        _n(p["k"]), _n(p["n"]), 100.0 * p["k"] / p["n"], 100.0 * bajo,
        100.0 * alto)


def _prop_referencia(k, n):
    return "%s/%s (%.1f %%)" % (_n(k), _n(n), 100.0 * k / n)


def _corrida(corrida):
    return "desconocida" if corrida is None else _n(corrida)


def _tabla_recall(w, recall):
    w("| estrato | filas | autorregulación | dirigido | solo al revés | "
      "cualquier dirección | orientación | acuerdo de signo |")
    w("|---|---:|---:|---|---|---|---|---|")
    for nombre in (PRINCIPAL,) + ESTRATOS:
        e = recall["estratos"][nombre]
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            NOMBRE_ESTRATO[nombre], _n(e["n"]), _n(e["autorregulacion"]),
            _prop(e["dirigido"]), _prop(e["inverso"]), _prop(e["cualquiera"]),
            _prop(e["orientacion"]), _prop(e["signo"]["acuerdo"])))
    w("")
    w("| estrato | dirigidas con signo en la base | acuerdo | contrario | "
      "regulates | mixto | acuerdo cuando da signo | siempre activa en esas "
      "filas |")
    w("|---|---:|---:|---:|---:|---:|---|---|")
    for nombre in (PRINCIPAL,) + ESTRATOS:
        s = recall["estratos"][nombre]["signo"]
        w("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            NOMBRE_ESTRATO[nombre], _n(s["n"]), _n(s["acuerdo"]["k"]),
            _n(s["contrario"]), _n(s["regulates"]), _n(s["mixto"]),
            _prop(s["acuerdo_si_da_signo"]),
            _prop(s["linea_base_siempre_mas"])))
    w("")


def _tabla_cobertura(w, cob):
    w("| regla | variante | todas | en el corpus | con XML | solo abstract |")
    w("|---|---|---|---|---|---|")
    for regla in REGLAS:
        for v in VARIANTES:
            if v in cob:
                w("| %s | %s | %s |" % (
                    NOMBRE_REGLA[regla], NOMBRE_VARIANTE[v],
                    " | ".join(_prop(cob[v][regla][g]) for g in GRUPOS)))
    w("")


def _archivo_red(red):
    """El nombre del archivo de la red contrastada, `red.tsv` o el de
    `--red`: el informe dice cuál midió."""
    return red.get("archivo") or redes.RED


def _techo_markdown(w, techo, principal):
    """La subsección del techo, con la red de la cifra principal al lado."""
    w("### El techo de la regla a), sin BioBERT")
    w("")
    w("La red sale de las oraciones candidatas del bronce: una fila que "
      "encuentra, en cualquier dirección, tiene sus dos locus juntos en "
      "alguna candidata, así que la regla a) con expansión es su techo. Es "
      "la cobertura de la sección 3 sobre las mismas %s de la cifra "
      "principal." % _cuantas(techo["n"], "fila", "filas"))
    w("")
    _tabla_cobertura(w, techo["cobertura"])
    w("- La red en esas filas: dirigido %s; cualquier dirección %s."
      % (_prop(principal["dirigido"]), _prop(principal["cualquiera"])))
    fuera = techo["red_cualquiera_fuera_de_a"]
    if fuera == 0:
        w("- Filas que la red encuentra en alguna dirección y la regla a) "
          "con expansión no cubre: 0, como debe ser.")
    elif fuera:
        w("- Filas que la red encuentra en alguna dirección y la regla a) "
          "con expansión no cubre: **%s**. Debería ser 0, y es un dato, no "
          "un error: el puente vuelve a leer las oraciones del bronce con el "
          "léxico de etapa2, y en esas filas llevó a locus algo que el bronce "
          "no llevó, o lo llevó a otro." % _n(fuera))
    w("")


def informe_markdown(resultado):
    """El informe publicable: solo conteos, proporciones e intervalos.

    Antes de devolverse pasa por `reentrenar.verificar_publicable`, el mismo
    filtro de RESULTADOS.md: si trae una ruta, un locus o algo con forma de
    PMID, lanza ValueError y no hay informe a medias.
    """
    s = []
    w = s.append
    b = resultado["bronce"]
    red = resultado.get("red")
    base = resultado["base"]
    d = resultado["denominador"]
    cob = resultado["cobertura"]
    ref = REFERENCIA_DENOMINADOR

    w("# Contraste con la base curada")
    w("")
    w("- Generado el %s (UTC)." % resultado["generado_en"])
    w("- Bronce: corrida %s; %s artículos leídos (%s con XML, %s solo "
      "abstract) y %s oraciones candidatas."
      % (_corrida(b["corrida"]), _n(b["documentos"]), _n(b["con_xml"]),
         _n(b["solo_abstract"]), _n(b["oraciones"])))
    if red:
        w("- Red: %s aristas de `%s`%s."
          % (_n(red["conteos"]["aristas"]), _archivo_red(red),
             "; con `--solo-pmids`" if red.get("recall_test") else ""))
    else:
        w("- Red: no se contrastó (`--sin-red`).")
    w("")
    w("Este informe lleva solo conteos, proporciones e intervalos de Wilson "
      "al 95 %. Lo que sale fila por fila de la base "
      "(`cobertura_por_fila.tsv`), la lista de aristas que la base no "
      "registra (`candidatas_nuevas.tsv`) y el registro con las huellas de "
      "las entradas (`contraste.json`) se quedan en la carpeta confidencial.")
    w("")

    w("## 1. La base contra PLAN.md 2.4")
    w("")
    w("| conteo | esperado | medido | |")
    w("|---|---:|---:|---|")
    for clave, esperado, medido, coincide in base["cotejo"]:
        w("| %s | %s | %s | %s |" % (clave, _n(esperado), _n(medido),
                                     "coincide" if coincide
                                     else "**DIFIERE**"))
    w("")
    if not base["diferencias"]:
        w("Coincide en todo.")
    else:
        w("**Difiere en %s conteos y se siguió con `--aceptar-base-distinta`."
          "** Es otra versión de la base, o el lector no la leyó como la de "
          "PLAN.md 2.4: las cifras de abajo no se comparan con las suyas sin "
          "decirlo." % _n(base["diferencias"]))
    w("")

    w("## 2. El denominador")
    w("")
    w("| | filas | PLAN.md 2.4 |")
    w("|---|---:|---:|")
    w("| Base (filas con los dos locus) | %s | %s |"
      % (_n(d["base"]), _n(reentrenar.BASE_ESPERADA.get("filas"))))
    w("| Fuera por homología | %s | %s |"
      % (_n(d["homologia"]), _n(ref["homologia"])))
    w("| Fuera por el archivo de exclusiones | %s | %s |"
      % (_n(d["excluidas_por_archivo"]), _n(ref["excluidas_por_archivo"])))
    w("| **Exigibles** | **%s** | **%s** |"
      % (_n(d["exigibles"]), _n(ref["exigibles"])))
    w("| en el corpus | %s | %s |"
      % (_n(cob["n"]["en_corpus"]), _n(ref["en_corpus"])))
    w("| con XML | %s | %s |" % (_n(cob["n"]["con_xml"]), _n(ref["con_xml"])))
    w("| solo abstract | %s | %s |"
      % (_n(cob["n"]["solo_abstract"]), _n(ref["solo_abstract"])))
    w("| autorregulación | %s | %s |"
      % (_n(d["autorregulacion"]), _n(ref["autorregulacion"])))
    w("")
    w("La columna de PLAN.md 2.4 es la medición del 10-sep-2026 sobre la "
      "corrida 1: referencia, no criterio. Con otro corpus cambian los "
      "artículos con XML, y una base nueva cambia todo.")
    w("")
    if "locus_invalido" in base:
        # La primera fila de la tabla contra las filas de PLAN.md 2.4: la
        # diferencia son filas que el lector descarta, no filas perdidas.
        w("- %s con valores, %s con los dos locus: %s con un locus inválido."
          % (_cuantas(base["filas"], "fila", "filas"),
             _n(base["interacciones"]), _n(base["locus_invalido"])))
    sg, og = d["signo"], d["origen"]
    w("- Signo de las exigibles: + %s; - %s; ? %s; d %s; ilegible %s."
      % (_n(sg["+"]), _n(sg["-"]), _n(sg["?"]), _n(sg["d"]),
         _n(sg["ilegible"])))
    w("- Origen de las exigibles: Histórica %s; Ambos %s; BioBERT %s; "
      "otro %s." % (_n(og["historica"]), _n(og["ambos"]), _n(og["biobert"]),
                    _n(og["otro"])))
    w("- Sin PMID: %s. Sin artículo citado no hay regla b, y la fila cuenta "
      "fuera del corpus." % _cuantas(d["sin_pmid"], "fila", "filas"))
    w("- Concentración: los 5 artículos con más filas exigibles reúnen %s "
      "de ellas. Las filas de un mismo artículo no son independientes, así "
      "que los intervalos de abajo son optimistas."
      % _n(d["en_los_5_articulos_mayores"]))
    ex = resultado["exclusiones"]
    w("- Archivo de exclusiones: %s con %s, %s por la base."
      % (_cuantas(ex["archivos"], "archivo", "archivos"),
         _cuantas(ex["pmids"], "PMID", "PMIDs"),
         _cuantas(ex["pmids_citados"], "citado", "citados")))
    if ex["archivos"] and "citan_excluido_y_otro" in d:
        # Concilia la fila del archivo con las 731 de PLAN.md 2.4: la
        # diferencia sale de «todos sus PMIDs» y de descontar antes la
        # homología, y aquí se cuentan las dos en vez de deducirlas.
        otro = d["citan_excluido_y_otro"]
        uno = ex["pmids_citados"] <= 1
        w("- %s %s %s junto con otro y %s, porque la regla es «todos sus "
          "PMIDs». Las de homología que %s citan (%s) salen antes, por "
          "homología."
          % (_n(otro), "cita" if otro == 1 else "citan",
             "el artículo excluido" if uno else "un artículo excluido",
             "se queda" if otro == 1 else "se quedan", "lo" if uno else "los",
             _n(d["homologia_que_cita_excluido"])))
    w("")

    w("## 3. Cobertura del bronce")
    w("")
    w("De las filas exigibles, cuántas tienen sus dos locus juntos en una "
      "oración candidata. La regla a) acepta cualquier oración del corpus: "
      "es lo que el paso 3 podría juntar sumando artículos. La b) exige una "
      "oración del artículo que la fila cita: es si el paso 1 recupera la "
      "evidencia citada. Con expansión, un operón cuenta por sus genes.")
    w("")
    _tabla_cobertura(w, cob)
    if "solo_por_expansion" in cob:
        se = cob["solo_por_expansion"]
        w("- Solo por la expansión de operones: regla a) %s filas (%s con "
          "XML); regla b) %s (%s con XML)."
          % (_n(se["a"]["todas"]), _n(se["a"]["con_xml"]),
             _n(se["b"]["todas"]), _n(se["b"]["con_xml"])))
    w("- La autorregulación (%s) está en el denominador y nunca cuenta como "
      "cubierta." % _cuantas(cob["autorregulacion"]["todas"], "fila",
                             "filas"))
    w("")
    if b["corrida"] == CORRIDA_DE_REFERENCIA:
        w("### Frente a PLAN.md 2.4, la misma corrida 1")
        w("")
        w("Comparación y no criterio: el lector, el diccionario y el corpus "
          "pudieron cambiar desde el 10-sep-2026.")
        w("")
        w("| regla | variante | grupo | ahora | PLAN.md 2.4 |")
        w("|---|---|---|---|---|")
        for (v, regla, g), (k, n) in REFERENCIA_COBERTURA.items():
            actual = (cob.get(v) or {}).get(regla, {}).get(g)
            w("| %s) | %s | %s | %s | %s |" % (
                regla, NOMBRE_VARIANTE[v], NOMBRE_GRUPO[g], _prop(actual),
                _prop_referencia(k, n)))
        w("")
    h = resultado["homologia"]
    if "con_expansion" in h and h["n"]["todas"]:
        w("### Contraste de homología")
        w("")
        w("Filas de homología: %s (%s con XML). Con expansión, regla a) %s; "
          "regla b) %s. Si se cubrieran como las exigibles, sacarlas del "
          "denominador sería un error%s."
          % (_n(h["n"]["todas"]), _n(h["n"]["con_xml"]),
             _prop(h["con_expansion"]["a"]["todas"]),
             _prop(h["con_expansion"]["b"]["todas"]),
             "; PLAN.md 2.4 midió 4.7 % y 0.3 % en la corrida 1"
             if b["corrida"] == CORRIDA_DE_REFERENCIA else ""))
        w("")

    w("## 4. La red")
    w("")
    if not red:
        w("No se contrastó: se corrió con `--sin-red`.")
        w("")
    else:
        cr = red["conteos"]
        partes = ["%s llevadas a locus por `id_par` y `pares.jsonl` (%s con "
                  "más de un par porque un extremo es un operón)"
                  % (_n(cr["con_locus"]), _n(cr["expandidas"])),
                  "%s sin locus de PAO1" % _n(cr["sin_locus"])]
        # Solo las trae una red con otras reglas: en la de red.py serían
        # dos ceros que no dicen nada.
        auto = cr.get("solo_autorregulacion")
        omitidas = cr.get("expandidas_omitidas")
        if auto:
            partes.append("%s de autorregulación con un solo locus"
                          % _n(auto))
        if omitidas:
            partes.append("%s de un operón" % _cuantas(
                omitidas, "expandida", "expandidas"))
        w("- %s de `%s`: %s; en total, %s de locus dirigidos."
          % (_cuantas(cr["aristas"], "arista", "aristas"), _archivo_red(red),
             _enumerar(partes), _cuantas(cr["pares_locus"], "par", "pares")))
        if auto:
            w("- La autorregulación con un solo locus no da par: no tiene un "
              "segundo gen.")
        if omitidas:
            w("- %s: no %s evidencia propia, y la arista del operón, que "
              "sigue en la red, ya da un par de locus por gen."
              % ("La expandida se omite" if omitidas == 1
                 else "Las expandidas se omiten",
                 "tiene" if omitidas == 1 else "tienen"))
        w("")
        w("Por fila de la base: **dirigido** si la red tiene la arista del "
          "regulador al blanco; **solo al revés** si solo tiene la del blanco "
          "al regulador. La **orientación** es dirigido entre cualquier "
          "dirección: de lo que la red encuentra, cuánto va en la dirección "
          "de la base. El signo se juzga en las dirigidas con `+` o `-` en "
          "la base, contra activates y represses de la red. Una arista "
          "`regulates` o un par cuyas aristas no dicen lo mismo (mixto) no "
          "es acuerdo.")
        w("")
        w("Con %s `+` y %s `-` entre las exigibles, el signo se lee contra la "
          "línea base de decir siempre activates. **Acuerdo cuando da signo** "
          "cuenta solo las filas en que la red resolvió activates o represses "
          "(acuerdo más contrario), y **siempre activa en esas filas** es lo "
          "que acertaría la línea base en ellas: las que la base dice `+`."
          % (_n(d["signo"]["+"]), _n(d["signo"]["-"])))
        w("")
        _tabla_recall(w, red["recall"])
        w("BioBERT va aparte: esas filas las propuso el modelo del asesor con "
          "la receta del run 22, la misma del clasificador de la red, y su "
          "recall sería circular. La cifra principal es la de «sin BioBERT».")
        w("")
        sp = red["recall"]["estratos"][PRINCIPAL]["signo"]
        w("- Con abstención, sin BioBERT: de las %s dirigidas con signo en la "
          "base, la red acuerda en %s y decir siempre activates acertaría en "
          "%s. La red se abstiene en las regulates y las mixtas; la línea "
          "base no."
          % (_n(sp["n"]), _prop(sp["acuerdo"]),
             _prop(sp["linea_base_siempre_mas_con_abstencion"])))
        nv = red["candidatas_nuevas"]
        ps = nv["por_signo"]
        w("- Candidatas nuevas: %s pares de locus de la red que la base no "
          "registra en ninguna dirección (activates %s; represses %s; "
          "regulates %s; mixto %s). La lista se queda en la carpeta "
          "confidencial: su complemento dice qué registra la base."
          % (_n(nv["pares"]), _n(ps["activates"]), _n(ps["represses"]),
             _n(ps["regulates"]), _n(ps["mixto"])))
        w("")
        techo = resultado.get("techo_sin_biobert")
        if techo:
            _techo_markdown(w, techo, red["recall"]["estratos"][PRINCIPAL])
        rt = red.get("recall_test")
        if rt:
            rp = rt["solo_pmids"]
            w("### Solo los artículos de test")
            w("")
            w("Para una red armada con un modelo entrenado con la base, con "
              "%s en `--solo-pmids`. Se evalúan las filas cuyos PMIDs están "
              "todos ahí (%s), y de la red cuentan solo las aristas con "
              "evidencia en alguno de esos artículos. Las que citan además un "
              "artículo que pudo entrar al entrenamiento quedan fuera (%s), "
              "como las que no citan ninguno de test (%s). El signo de una "
              "arista lo decidió `red.py` con todas sus evidencias."
              % (_cuantas(rp["pmids"], "PMID", "PMIDs"), _n(rp["evaluadas"]),
                 _n(rp["mezcla"]), _n(rp["fuera"])))
            w("")
            _tabla_recall(w, rt)

    w("## 5. Cautelas")
    w("")
    w("- Es un piso: una mención que el bronce no llevó a locus no cuenta, y "
      "una relación repartida en dos oraciones tampoco.")
    w("- La cobertura mide coocurrencia, no dirección ni signo: es el techo "
      "del paso 1. La dirección y el signo están en la sección 4.")
    w("- La expansión sale del catálogo de operones y no del texto: una "
      "oración que solo nombra un operón pone juntos a todos sus genes.")
    w("- El corpus es lo que el bronce leyó con alguna mención: un artículo "
      "sin ninguna cuenta como fuera del corpus, así que «en el corpus» es "
      "una cota inferior.")
    if resultado.get("avisos"):
        w("")
        w("## Avisos")
        w("")
        for aviso in resultado["avisos"]:
            w("- %s" % aviso)
    texto = "\n".join(s) + "\n"
    try:
        reentrenar.verificar_publicable(texto)
    except ValueError as e:
        raise ValueError("El informe no se puede publicar (%s): no se "
                         "escribe." % e) from None
    return texto


def resumen(resultado):
    """Las líneas de la terminal: las cifras principales y los avisos."""
    b = resultado["bronce"]
    d = resultado["denominador"]
    cob = resultado["cobertura"]
    ref = REFERENCIA_DENOMINADOR
    base = resultado["base"]
    lineas = []
    if base["diferencias"]:
        lineas.append("Base: difiere de PLAN.md 2.4 en %s conteos; se sigue "
                      "con --aceptar-base-distinta." % _n(base["diferencias"]))
    else:
        lineas.append("Base: coincide con PLAN.md 2.4 en los %s conteos."
                      % _n(len(base["cotejo"])))
    lineas.append(
        "Denominador: %s exigibles de %s (fuera: homología %s, archivo de "
        "exclusiones %s); autorregulación %s. PLAN.md 2.4: %s y %s."
        % (_n(d["exigibles"]), _n(d["base"]), _n(d["homologia"]),
           _n(d["excluidas_por_archivo"]), _n(d["autorregulacion"]),
           _n(ref["exigibles"]), _n(ref["autorregulacion"])))
    lineas.append(
        "  en el corpus %s (PLAN.md 2.4: %s): con XML %s (%s), solo abstract "
        "%s (%s)." % (_n(cob["n"]["en_corpus"]), _n(ref["en_corpus"]),
                      _n(cob["n"]["con_xml"]), _n(ref["con_xml"]),
                      _n(cob["n"]["solo_abstract"]),
                      _n(ref["solo_abstract"])))
    lineas.append("Bronce: corrida %s; %s artículos (%s con XML); %s "
                  "oraciones candidatas."
                  % (_corrida(b["corrida"]), _n(b["documentos"]),
                     _n(b["con_xml"]), _n(b["oraciones"])))
    if "con_expansion" in cob:
        ce = cob["con_expansion"]
        lineas.append(
            "Cobertura con expansión: regla a %s en todas y %s con XML; "
            "regla b %s en todas y %s con XML."
            % (_pct(ce["a"]["todas"]), _pct(ce["a"]["con_xml"]),
               _pct(ce["b"]["todas"]), _pct(ce["b"]["con_xml"])))
    red = resultado.get("red")
    if red:
        e = red["recall"]["estratos"]
        sp = e[PRINCIPAL]["signo"]
        lineas.append(
            "Red: %s aristas de %s, %s llevadas a locus. Sin BioBERT: "
            "dirigido %s, solo al revés %s, acuerdo de signo %s."
            % (_n(red["conteos"]["aristas"]), _archivo_red(red),
               _n(red["conteos"]["con_locus"]),
               _pct(e[PRINCIPAL]["dirigido"]), _pct(e[PRINCIPAL]["inverso"]),
               _pct(sp["acuerdo"])))
        lineas.append(
            "  Sin BioBERT: orientación %s; acuerdo cuando da signo %s, "
            "siempre activa en esas filas %s; siempre activa en las dirigidas "
            "con signo %s."
            % (_pct(e[PRINCIPAL]["orientacion"]),
               _pct(sp["acuerdo_si_da_signo"]),
               _pct(sp["linea_base_siempre_mas"]),
               _pct(sp["linea_base_siempre_mas_con_abstencion"])))
        techo = resultado.get("techo_sin_biobert")
        if techo and "con_expansion" in techo["cobertura"]:
            lineas.append(
                "  Techo sin BioBERT: la regla a con expansión cubre %s; la "
                "red encuentra %s en cualquier dirección; fuera de la regla "
                "a: %s."
                % (_pct(techo["cobertura"]["con_expansion"]["a"]["todas"]),
                   _pct(e[PRINCIPAL]["cualquiera"]),
                   _n(techo["red_cualquiera_fuera_de_a"])))
        lineas.append("  BioBERT, aparte por circular: dirigido %s."
                      % _pct(e["biobert"]["dirigido"]))
        rt = red.get("recall_test")
        if rt:
            lineas.append(
                "  Solo test: %s filas evaluadas (%s fuera por citar otro "
                "artículo); dirigido sin BioBERT %s."
                % (_n(rt["solo_pmids"]["evaluadas"]),
                   _n(rt["solo_pmids"]["mezcla"]),
                   _pct(rt["estratos"][PRINCIPAL]["dirigido"])))
        lineas.append("Candidatas nuevas: %s pares de locus que la base no "
                      "registra." % _n(red["candidatas_nuevas"]["pares"]))
    for aviso in resultado.get("avisos") or ():
        lineas.append("AVISO: %s" % aviso)
    return lineas


# ---------------------------------------------------------------- ejecutar

def _como_lista(valor):
    if not valor:
        return []
    if isinstance(valor, str):
        # Una sola ruta suelta se recorrería letra por letra.
        return [valor]
    return list(valor)


def _expandir(ruta, flag):
    if not ruta:
        raise ValueError("Falta %s." % flag)
    ruta = os.path.expanduser(ruta)
    if ruta.startswith("~"):
        raise ValueError("No pude expandir el ~ de %s (¿usuario que no "
                         "existe?). Usa una ruta absoluta." % flag)
    return ruta


def exigir_confidencial_fuera(ruta):
    """ValueError, sin rutas en el mensaje, si `ruta` cae dentro del
    repositorio o de una copia de git.

    Es `entrenamiento.exigir_fuera_del_repositorio`, cuyo mensaje trae la
    ruta y la del repositorio: la CLI imprime el error, y la ruta de la
    carpeta confidencial dice dónde vive lo que deriva de la base.
    """
    try:
        entrenamiento.exigir_fuera_del_repositorio(ruta)
    except ValueError:
        # `from None`: encadenado, un traceback mostraría el mensaje original.
        raise ValueError(
            "--confidencial queda dentro del repositorio o de una copia de "
            "trabajo de git. Lo que se escribe ahí deriva de la base curada: "
            "usa una carpeta fuera de cualquier repositorio, por ejemplo bajo "
            "$GRN_DATOS.") from None


def archivos_de_red(red=None, sin_red=False):
    """(red, evidencias, informe) de la red que se contrasta, o ValueError.

    Sin `red`, los de la red por omisión (`red.tsv`); con él, los de
    `grn_comun.redes`, la misma fuente de los nombres que usa
    `grn_red.consolidar` para escribirlos. El mensaje de error no repite el
    nombre: lo que llega por --red puede ser una ruta.

    Un nombre que `grn_red` acepta todavía puede no servir aquí: el informe y
    la terminal nombran el archivo de la red y pasan por el filtro de
    publicación, que toma siete u ocho dígitos seguidos por un PMID
    (`red_umbral_20261023.tsv`). Se dice antes de abrir la base; si no, el
    contraste corría entero y se detenía al final con «posible PMID en la
    línea 5».
    """
    if red is None:
        return redes.archivos_de_red()
    if sin_red:
        raise ValueError("--red y --sin-red se excluyen: --red elige qué red "
                         "se contrasta y --sin-red no contrasta ninguna.")
    try:
        nombres = redes.archivos_de_red(red)
    except ValueError as e:
        raise ValueError("--red: %s" % e) from None
    try:
        reentrenar.verificar_publicable(nombres[0])
    except ValueError:
        # Con el patrón de `redes` (minúsculas, dígitos y «_») no cabe una
        # ruta, un locus ni un marcador: lo único que el filtro puede ver es
        # la forma de un PMID.
        raise ValueError("--red: el nombre lleva siete u ocho dígitos "
                         "seguidos, con forma de PMID, y el informe que lo "
                         "nombra no pasaría el filtro de publicación. Arma "
                         "esa red con otro nombre (`python -m grn_red.cli "
                         "consolidar --nombre`).") from None
    return nombres


def ubicar_archivos(carpeta, sin_red=False, red=None):
    """Las rutas de lo que se lee de la carpeta del flujo.

    El CSV de candidatas es el que `flujo.py` anotó en `estado.json` (el
    nombre lleva la fecha y en una carpeta puede haber varios); si no hay
    estado, el más reciente. Las menciones son las del mismo volcado. La red
    es `red.tsv`, o con `red` la `red_<red>.tsv` de `grn_red.consolidar`, con
    sus evidencias y su informe (`archivos_de_red`).
    """
    nombres_red = archivos_de_red(red, sin_red)
    if not os.path.isdir(carpeta):
        raise ValueError("No encuentro la carpeta de --carpeta.")
    candidatas = None
    try:
        with io.open(os.path.join(carpeta, "estado.json"),
                     encoding="utf-8") as f:
            estado = json.load(f)
        nombre = ((estado.get("archivos") or {}).get("candidatas")
                  if isinstance(estado, dict) else None)
    except (OSError, ValueError, AttributeError):
        nombre = None
    if nombre and os.path.basename(nombre) == nombre and \
            os.path.isfile(os.path.join(carpeta, nombre)):
        candidatas = os.path.join(carpeta, nombre)
    else:
        hallados = sorted(glob.glob(os.path.join(
            glob.escape(carpeta),
            "bronce_identificacion_*" + SUFIJO_CANDIDATAS)),
            key=os.path.getmtime)
        if hallados:
            candidatas = hallados[-1]
    if not candidatas or not candidatas.endswith(SUFIJO_CANDIDATAS):
        raise ValueError("La carpeta no tiene el CSV de oraciones candidatas "
                         "del bronce: corre antes el paso bronce del flujo.")
    menciones = candidatas[:-len(SUFIJO_CANDIDATAS)] + SUFIJO_MENCIONES
    if not os.path.isfile(menciones):
        raise ValueError("La carpeta tiene el CSV de candidatas pero no el "
                         "de menciones del mismo volcado del bronce.")
    rutas = {"carpeta": carpeta, "candidatas": candidatas,
             "menciones": menciones}
    if not sin_red:
        nombre_red, nombre_evidencias, nombre_informe = nombres_red
        if red is None:
            pista = "corre antes el paso red del flujo, o usa --sin-red"
        else:
            pista = ("arma antes esa red con `python -m grn_red.cli "
                     "consolidar` (la recomendada la arma el paso "
                     "red_recomendada del flujo)")
        for llave, nombre in (("red", nombre_red),
                              ("evidencias", nombre_evidencias),
                              ("pares", "pares.jsonl")):
            ruta = os.path.join(carpeta, nombre)
            if not os.path.isfile(ruta):
                # Solo el nombre: con --red, ya pasó por el patrón cerrado de
                # `redes` y no es una ruta.
                raise ValueError("Falta %s en la carpeta: %s." % (nombre,
                                                                  pista))
            rutas[llave] = ruta
        rutas["red_informe"] = os.path.join(carpeta, nombre_informe)
    return rutas


def comprobar_procedencia_red(rutas):
    """Los avisos, o ValueError si la red se armó con otro `pares.jsonl`.

    La red se une con los pares por `id_par`, que depende de la oración y no
    del marcado: con un `pares.jsonl` rehecho después de la red la unión no
    falla, y una arista se lleva a los locus de otro diccionario sin que
    nada avise. `red.py` sella en su informe la huella de los pares que leyó.
    """
    sello = procedencia.leer_sello(rutas["red_informe"])
    anotada = (sello.get("pares") or {}).get("huella")
    if not anotada:
        return ["la carpeta no trae red_informe.json con la huella de "
                "pares.jsonl: no se pudo comprobar que la red salió de estos "
                "pares."]
    if anotada != procedencia.huella(rutas["pares"]):
        raise ValueError("La red se armó con otro pares.jsonl (las huellas no "
                         "coinciden): corre antes el paso red del flujo.")
    return []


# Vive en `entrenamiento` desde el 23-oct: la usan también `precision-ciega`
# y `verificar-contaminacion`.
_leer_pmids = entrenamiento.leer_pmids


def mensaje_publicable(error, rutas=()):
    """El mensaje de un error como se puede imprimir.

    Sin las rutas que se pasan (la de la base y la de la carpeta
    confidencial) y sin nada que `verificar_publicable` rechace; si no pasa,
    solo el tipo. Un OSError se dice por su `strerror`: su `str` lleva el
    nombre del archivo.
    """
    if isinstance(error, OSError):
        texto = error.strerror or ""
    else:
        texto = str(error)
    for ruta in rutas:
        if not ruta:
            continue
        expandida = os.path.expanduser(ruta)
        for variante in sorted(set([ruta, expandida,
                                    os.path.abspath(expandida),
                                    os.path.realpath(expandida)]),
                               key=len, reverse=True):
            if len(variante) > 1:
                texto = texto.replace(variante, "<ruta>")
    try:
        reentrenar.verificar_publicable(texto)
    except ValueError:
        texto = ""
    if isinstance(error, ValueError) and not isinstance(
            error, UnicodeError) and texto:
        return texto
    return "%s%s" % (type(error).__name__, ": %s" % texto if texto else "")


def _celda(valor):
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "si" if valor else "no"
    return " ".join(str(valor).split())


def _escribir_tsv(ruta, columnas, filas):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter="\t", lineterminator="\n")
        escritor.writerow(columnas)
        for fila in filas:
            escritor.writerow([_celda(fila.get(c)) for c in columnas])
    archivos.reemplazar(tmp, ruta)


def _escribir_texto(ruta, texto):
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    archivos.reemplazar(tmp, ruta)


def ejecutar(base, carpeta, confidencial, informe=None, hoja=None,
             excluir=(), solo=(), sin_red=False, aceptar_base_distinta=False,
             red=None, log=_nada):
    """Contrasta el bronce y la red de `carpeta` con la base y escribe.

    `base`: el .xlsx, por ruta. `carpeta`: la del flujo (CSV del bronce y,
    salvo `sin_red`, `red.tsv`, `red_evidencias.tsv` y `pares.jsonl`).
    `red`: el nombre de una red con otras reglas, para contrastar
    `red_<red>.tsv` y sus evidencias en vez de `red.tsv`; no va con
    `sin_red`. `excluir` y `solo`: archivos con el formato de `reservas.tsv`.
    `confidencial`: carpeta fuera de todo repositorio para
    `cobertura_por_fila.tsv`, `candidatas_nuevas.tsv` y `contraste.json`.
    `informe`: dónde va el Markdown publicable, o None para no escribirlo.

    Las comprobaciones van antes de abrir la base: los argumentos, la carpeta
    confidencial, que existan las entradas y que la red sea de estos pares.
    Después, la base se coteja con `reentrenar.BASE_ESPERADA` y, si no
    cuadra, se detiene con ValueError salvo `aceptar_base_distinta`. El
    informe y las líneas de `log` pasan por `verificar_publicable` antes de
    escribir nada. Devuelve el resultado: solo conteos, proporciones e
    intervalos.
    """
    # Primero: es un error de argumentos, y no hace falta tocar nada para
    # decirlo.
    archivos_de_red(red, sin_red)
    confidencial = _expandir(confidencial, "--confidencial")
    exigir_confidencial_fuera(confidencial)
    base = _expandir(base, "--base")
    carpeta = _expandir(carpeta, "--carpeta")
    excluir = [_expandir(r, "--excluir-pmids") for r in _como_lista(excluir)]
    solo = [_expandir(r, "--solo-pmids") for r in _como_lista(solo)]
    if informe:
        informe = _expandir(informe, "--informe")
    for flag, ruta in ([("--base", base)]
                       + [("--excluir-pmids", r) for r in excluir]
                       + [("--solo-pmids", r) for r in solo]):
        if not os.path.isfile(ruta):
            # Sin la ruta: la de --base dice dónde vive la base.
            raise ValueError("No encuentro el archivo de %s. Usa una ruta "
                             "absoluta; entre comillas simples, ~ y $HOME no "
                             "se expanden." % flag)
    rutas = ubicar_archivos(carpeta, sin_red, red)
    avisos = []
    if not sin_red:
        avisos.extend(comprobar_procedencia_red(rutas))
    pmids_excluir, c_excluir = _leer_pmids(excluir, "--excluir-pmids")
    pmids_solo = _leer_pmids(solo, "--solo-pmids")[0] if solo else None
    if solo and sin_red:
        avisos.append("--solo-pmids no tiene efecto con --sin-red: solo se "
                      "aplica al recall de la red.")

    interacciones, c_base = validacion.leer_base(base, hoja)
    # BASE_ESPERADA se lee aquí y no como valor por omisión de filas_cotejo,
    # que se fija al importar: así una prueba la puede sustituir.
    cotejo = reentrenar.filas_cotejo(c_base, reentrenar.BASE_ESPERADA)
    distintas = [f for f in cotejo if not f[3]]
    for clave, esperado, medido, _ in distintas:
        log("Base: %s esperado %s, medido %s." % (clave, _n(esperado),
                                                  _n(medido)))
    if distintas and not aceptar_base_distinta:
        raise ValueError(
            "La base no coincide con PLAN.md 2.4 en %d conteos (arriba). "
            "Puede ser otra versión de la base o el lector: no se contrasta "
            "hasta decidirlo; con --aceptar-base-distinta se sigue."
            % len(distintas))

    citados = set()
    for fila in interacciones:
        citados.update(fila["pmids"])
    if not excluir:
        avisos.append("sin --excluir-pmids: el denominador conserva el "
                      "artículo de 731 filas que el bronce no puede leer "
                      "(PLAN.md 2.4).")
    elif not pmids_excluir & citados:
        avisos.append("ninguno de los PMIDs de --excluir-pmids aparece en la "
                      "base; revisa que el archivo sea el que querías.")

    docs = documentos_del_bronce(rutas["menciones"])
    oraciones, corridas, trae_expandidos = _leer_candidatas(
        rutas["candidatas"])
    if not trae_expandidos:
        avisos.append("el CSV de candidatas no trae genes_expandidos (un "
                      "bronce anterior a la expansión de operones): con y sin "
                      "expansión dan lo mismo.")
    if len(corridas) > 1:
        avisos.append("el CSV de candidatas mezcla %s corridas del bronce."
                      % _n(len(corridas)))
    pares = collections.OrderedDict(
        (v, _pares(oraciones, v == "con_expansion")) for v in VARIANTES)
    exigibles, c_den = denominador(interacciones, pmids_excluir)
    cobertura = cobertura_bronce(exigibles, docs, pares)
    homologia = cobertura_bronce([f for f in interacciones if f["homologia"]],
                                 docs, pares)

    # `contrastada` y no `red`, que es el nombre que llegó por argumento y va
    # a los parámetros del registro.
    contrastada, aristas, nuevas = None, None, []
    if not sin_red:
        aristas, c_red = aristas_en_locus(rutas["red"], rutas["evidencias"],
                                          rutas["pares"])
        nuevas = candidatas_nuevas(aristas, curados_de(interacciones))
        recall_test = (recall_red(exigibles, aristas, pmids_solo)
                       if pmids_solo is not None else None)
        if recall_test is not None and \
                not recall_test["solo_pmids"]["evaluadas"]:
            avisos.append("ninguna fila exigible tiene todos sus PMIDs en "
                          "--solo-pmids: el recall de test queda vacío.")
        contrastada = collections.OrderedDict([
            ("archivo", os.path.basename(rutas["red"])),
            ("conteos", c_red),
            ("recall", recall_red(exigibles, aristas)),
            ("recall_test", recall_test),
            ("candidatas_nuevas", _conteo_nuevas(nuevas)),
        ])
    techo = techo_sin_biobert(exigibles, docs, pares, aristas)

    resultado = collections.OrderedDict([
        ("generado_en", _ahora()),
        ("base", collections.OrderedDict([
            ("filas", c_base["filas"]),
            ("interacciones", c_base["interacciones"]),
            ("locus_invalido", c_base["locus_invalido"]),
            ("cotejo", cotejo),
            ("diferencias", len(distintas)),
            ("aceptada_distinta", bool(distintas))])),
        ("exclusiones", collections.OrderedDict([
            ("archivos", c_excluir["archivos"]),
            ("pmids", len(pmids_excluir)),
            ("pmids_citados", len(pmids_excluir & citados)),
            ("oraciones_ignoradas", c_excluir["oraciones"])])),
        ("denominador", c_den),
        ("bronce", collections.OrderedDict([
            ("corrida", next(iter(corridas)) if len(corridas) == 1
             else None),
            ("documentos", len(docs)),
            ("con_xml", sum(1 for v in docs.values() if v == "xml")),
            ("solo_abstract", sum(1 for v in docs.values() if v != "xml")),
            ("oraciones", len(oraciones)),
            ("pares", collections.OrderedDict(
                (v, len(pares[v][0])) for v in VARIANTES))])),
        ("cobertura", cobertura),
        ("homologia", homologia),
        ("techo_sin_biobert", techo),
        ("red", contrastada),
        ("avisos", avisos),
    ])
    texto = informe_markdown(resultado)
    lineas = resumen(resultado)
    try:
        reentrenar.verificar_publicable("\n".join(lineas))
    except ValueError as e:
        raise ValueError("El resumen de la terminal no pasó el filtro de "
                         "publicación (%s): no se escribe nada." % e)

    if not os.path.isdir(confidencial):
        # 0o700: en el servidor, otras cuentas no entran a la carpeta.
        os.makedirs(confidencial, 0o700)
    _escribir_tsv(os.path.join(confidencial, ARCHIVO_POR_FILA),
                  COLUMNAS_POR_FILA,
                  filas_por_fila(interacciones, pmids_excluir, docs, pares,
                                 aristas, pmids_solo))
    if sin_red:
        # Una lista de una corrida anterior con red se leería como de esta.
        archivos.borrar(os.path.join(confidencial, ARCHIVO_NUEVAS))
    else:
        _escribir_tsv(os.path.join(confidencial, ARCHIVO_NUEVAS),
                      COLUMNAS_NUEVAS, nuevas)
    huellas = collections.OrderedDict(
        (llave, procedencia.huella(rutas[llave]))
        for llave in ("candidatas", "menciones", "red", "evidencias",
                      "pares") if llave in rutas)
    huellas["base"] = procedencia.huella(base)
    huellas["excluir"] = [procedencia.huella(r) for r in excluir]
    huellas["solo"] = [procedencia.huella(r) for r in solo]
    registro = collections.OrderedDict([
        ("parametros", collections.OrderedDict([
            ("hoja", hoja), ("sin_red", bool(sin_red)), ("red", red),
            ("aceptar_base_distinta", bool(aceptar_base_distinta)),
            ("archivos_excluir", len(excluir)),
            ("archivos_solo", len(solo))])),
        ("huellas", huellas),
        ("resultado", resultado),
    ])
    _escribir_texto(os.path.join(confidencial, ARCHIVO_REGISTRO),
                    json.dumps(registro, ensure_ascii=False, indent=2) + "\n")
    if informe:
        _escribir_texto(informe, texto)

    for linea in lineas:
        log(linea)
    escritos = ([ARCHIVO_POR_FILA] + ([] if sin_red else [ARCHIVO_NUEVAS])
                + [ARCHIVO_REGISTRO])
    log("Escritos en la carpeta de --confidencial: %s y %s%s."
        % (", ".join(escritos[:-1]), escritos[-1],
           "; el informe, en la ruta de --informe" if informe else ""))
    return resultado
