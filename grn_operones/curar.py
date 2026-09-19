# -*- coding: utf-8 -*-
"""De `operones_bronze` a `operones_silver`: normalizar, validar, deduplicar.

Las seis reglas del encargo, y las dos desviaciones que hubo que hacer:

1. **Normalizar a locus tag PAO1.** El encargo propone usar la anotacion de
   Pseudomonas.com como diccionario nombre -> locus tag. **No se usa**, y no
   por pereza: `pseudomonas.com` devuelve 403 a `urllib.request` y esta
   registrada como via cerrada en `docs/hallazgos.md`. En su lugar se usa
   `grn_bronce/recursos/genes_pao1.tsv`, que cubre lo mismo --5 642 genes con
   simbolo y alias-- y ademas viene de tres fuentes con procedencia declarada
   (RefSeq, KEGG, UniProt) en vez de una sola.
2. **Validar adyacencia.** Los locus tags de PAO1 son consecutivos por
   construccion, asi que la adyacencia se comprueba sobre su numeracion. La
   **hebra** solo se comprueba si el GFF de RefSeq esta en el cache local: no
   esta versionado, asi que en un clon limpio no existe. Cuando falta, la
   fila queda marcada `hebra_no_verificada` en vez de darse por buena.
3. **Deduplicar** por conjunto ordenado de locus tags. Los subconjuntos y los
   solapamientos **no se fusionan**: se conservan como unidades alternativas
   marcadas, porque un operon puede transcribirse entero o en parte y las dos
   cosas estan documentadas.
4. **Nivel de evidencia**: `conocido` (tiene PMID) > `curado` (BioCyc con
   evidence code de curacion) > `predicho`. Se cuenta cuantas fuentes lo
   respaldan.
5. **Promotor CDBProm** aguas arriba del primer gen, si hay datos de CDBProm.
6. Los conflictos salen a CSV; los produce `exportar.py`.

LA TRAMPA DE CONTAR FUENTES
===========================
`n_fuentes` cuenta fuentes **distintas**, no registros, y aun asi hay que
leerlo con cuidado: Pseudomonas.com y BioCyc usan predicciones de Pathway
Tools, asi que coincidir no es confirmacion independiente. `FUENTES_NO_
INDEPENDIENTES` lo deja escrito y `nivel_evidencia` no sube por esa via.

Solo biblioteca estandar.
"""

import collections
import gzip
import io
import os
import re

from grn_operones import db as _db

LOCUS = re.compile(r"^PA(\d{4})(?:\.(\d))?$")

RUTA_GENES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "grn_bronce", "recursos", "genes_pao1.tsv")

# El GFF vive en el cache del constructor del diccionario y NO esta
# versionado: en un clon limpio no existe, y por eso la hebra es opcional.
RUTAS_GFF = (
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "datos_etapa2", "cache_diccionario", "refseq_gff.gz"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "construir_diccionario", "diccionario_independiente", "cache",
                 "refseq.gff.gz"),
)

# Las dos que comparten motor de prediccion. Coincidir entre ellas no es
# confirmacion independiente y no sube el nivel de evidencia.
FUENTES_NO_INDEPENDIENTES = frozenset(["pgd", "biocyc"])

NIVELES = ("conocido", "curado", "predicho")

# Codigos de evidencia de BioCyc que indican curacion a partir de un
# experimento, no prediccion de Pathway Tools.
EVIDENCIA_CURADA = ("EV-EXP", "EV-COMP-HINF-SIMILAR-TO-CONSENSUS",
                    "EV-EXP-IDA", "EV-EXP-IEP", "EV-EXP-TAS")


def cargar_diccionario(ruta=RUTA_GENES):
    """{nombre en minusculas: locus_tag}, con simbolos y alias.

    El locus tag se mapea a si mismo para que normalizar sea idempotente:
    pasar dos veces por aqui no cambia nada.
    """
    mapa = {}
    with io.open(ruta, encoding="utf-8") as f:
        cols = f.readline().rstrip("\n").split("\t")
        for linea in f:
            if not linea.strip():
                continue
            d = dict(zip(cols, linea.rstrip("\n").split("\t")))
            lt = (d.get("locus_tag") or "").strip()
            if not lt:
                continue
            mapa[lt.lower()] = lt
            for campo in ("simbolo",):
                v = (d.get(campo) or "").strip()
                if v:
                    mapa.setdefault(v.lower(), lt)
            for a in (d.get("alias") or "").split("|"):
                a = a.strip()
                if a:
                    mapa.setdefault(a.lower(), lt)
    return mapa


def cargar_hebras(rutas=RUTAS_GFF):
    """{locus_tag: '+'/'-'} del GFF, o {} si el cache no esta.

    Devolver vacio y no reventar es deliberado: sin GFF la curacion sigue
    siendo util, solo que no puede afirmar nada sobre la hebra, y eso se
    marca fila por fila en vez de fingir que se comprobo.
    """
    for ruta in rutas:
        if not os.path.exists(ruta):
            continue
        hebras = {}
        with gzip.open(ruta, "rt", encoding="utf-8", errors="replace") as f:
            for linea in f:
                if linea.startswith("#"):
                    continue
                partes = linea.rstrip("\n").split("\t")
                if len(partes) < 9 or partes[2] not in ("gene", "pseudogene"):
                    continue
                m = re.search(r"locus_tag=([^;]+)", partes[8])
                if m:
                    hebras[m.group(1).strip()] = partes[6]
        if hebras:
            return hebras
    return {}


_SUFIJO = re.compile(r"^(.*?[a-zA-Z])(\d+)$")


def cargar_paralogos(diccionario):
    """{nombre base: [locus_tags]} de las familias con sufijo numerico.

    `phzA1` y `phzA2` comparten la base `phzA`, que no existe como entrada
    propia. La literatura escribe `phzA` a secas, y eso no identifica un gen:
    identifica dos.
    """
    familias = {}
    for nombre, lt in diccionario.items():
        m = _SUFIJO.match(nombre)
        if m:
            familias.setdefault(m.group(1), set()).add(lt)
    return dict((b, sorted(v)) for b, v in familias.items()
                if len(v) > 1 and b not in diccionario)


def normalizar(nombres, diccionario, paralogos=None):
    """([locus_tags], [sin_resolver], [(nombre, [candidatos])]).

    El orden de entrada se preserva y no se ordena: el orden de los miembros
    es el de transcripcion, y es lo que distingue `mexCD-oprJ` de `oprJ-mexDC`,
    que es el mismo operon leido al reves y un nombre que no existe.

    **Un nombre ambiguo no se resuelve, se reporta.** `phzA` puede ser
    `phzA1` (PA4210) o `phzA2` (PA1899), y elegir uno por orden alfabetico o
    por cercania meteria un gen equivocado en un operon sin dejar rastro de
    que hubo una eleccion. El registro va a conflictos con sus candidatos, y
    lo resuelve una persona.
    """
    paralogos = (cargar_paralogos(diccionario) if paralogos is None
                 else paralogos)
    locus, fuera, ambiguos = [], [], []
    for n in nombres:
        n = (n or "").strip()
        if not n:
            continue
        lt = diccionario.get(n.lower())
        if lt:
            if lt not in locus:
                locus.append(lt)
            continue
        candidatos = paralogos.get(n.lower())
        if candidatos:
            ambiguos.append((n, candidatos))
        else:
            fuera.append(n)
    return locus, fuera, ambiguos


def _numero(locus_tag):
    m = LOCUS.match(locus_tag)
    return int(m.group(1)) if m else None


def es_adyacente(locus_tags):
    """Si los locus tags son consecutivos, en cualquiera de los dos sentidos.

    Ascendente o descendente: un operon en la hebra menos se escribe en orden
    de transcripcion, que por locus tag va hacia abajo. Exigir solo ascendente
    marcaria como no adyacente a la mitad del genoma.
    """
    nums = [_numero(l) for l in locus_tags]
    if len(nums) < 2 or any(n is None for n in nums):
        return False
    pasos = [b - a for a, b in zip(nums, nums[1:])]
    return all(p == 1 for p in pasos) or all(p == -1 for p in pasos)


def misma_hebra(locus_tags, hebras):
    """(bool_o_None, hebra). `None` cuando el GFF no esta disponible."""
    if not hebras:
        return None, None
    vistas = set(hebras.get(l) for l in locus_tags)
    vistas.discard(None)
    if not vistas:
        return None, None
    return (len(vistas) == 1), (vistas.pop() if len(vistas) == 1 else None)


def nivel_de(filas):
    """El mejor nivel de evidencia entre las filas que respaldan un operon."""
    if any((f["pmid"] or "").strip() for f in filas):
        return "conocido"
    for f in filas:
        ev = (f["tipo_evidencia"] or "").upper()
        if any(c in ev for c in EVIDENCIA_CURADA):
            return "curado"
    return "predicho"


def clave_de(locus_tags):
    """El identificador de un operon curado: sus genes, en su orden.

    LIMITACION CONOCIDA, Y HAY QUE LEERLA ANTES DE USAR CDBPROM
    ===========================================================
    La clave son los genes y nada mas. Dos unidades de transcripcion con los
    **mismos genes y distinto sitio de inicio** colapsan en una sola fila de
    la capa curada, y la distincion se pierde.

    Para una base de operones --que es lo que pidio el asesor-- es aceptable:
    lo que interesa es que genes se cotranscriben. Deja de serlo en cuanto
    CDBProm entre para marcar promotores, porque **es justo ahi donde esa
    distincion vive**: dos TUs con los mismos genes y dos promotores distintos
    son dos formas de regular el mismo bloque, y con esta clave solo se ve una,
    con `promotor_cdbprom` puesto a si o a no sin decir a cual.

    El dia que haga falta, la salida es anadir el inicio de transcripcion a la
    clave, no cambiar el criterio de deduplicacion.
    """
    return "|".join(locus_tags)


def cobertura_mapeo(nombres, diccionario=None):
    """Cuantos nombres llegan a locus tag, y cuales no. Solo lectura.

    Existe porque la normalizacion falla **en silencio**: un nombre que el
    diccionario no conoce no produce error, produce un operon con un gen
    menos, que es indistinguible de un operon que de verdad tiene un gen
    menos. Medir la cobertura antes de confiar en la curacion es la unica
    forma de saber si eso esta pasando.

    Importa sobre todo con ODB, que viene de literatura y usa nombres
    historicos: `nalB` por `mexR`, por ejemplo. Medido sobre
    `genes_pao1.tsv`, solo 224 de sus 5 642 filas traen un sinonimo distinto
    del simbolo y del locus tag, asi que la cobertura de nombres antiguos es
    baja por construccion.
    """
    diccionario = cargar_diccionario() if diccionario is None else diccionario
    unicos = []
    for n in nombres:
        n = (n or "").strip()
        if n and n not in unicos:
            unicos.append(n)
    locus, huerfanos, ambiguos = normalizar(unicos, diccionario)
    mapeados = len(unicos) - len(huerfanos) - len(ambiguos)
    return {
        "nombres": len(unicos),
        "mapeados": mapeados,
        "huerfanos": huerfanos,
        # Separados de los huerfanos a proposito: son dos problemas distintos.
        # Un huerfano no esta en el diccionario y hay que anadirlo; un ambiguo
        # esta de sobra --`phzA` es `phzA1` y `phzA2`-- y hay que desambiguarlo
        # a mano. Mezclarlos daria una sola cifra que no dice que hacer.
        "ambiguos": [n for n, _c in ambiguos],
        "tasa": (float(mapeados) / len(unicos)) if unicos else 0.0,
    }


def contar_sinonimos(ruta=RUTA_GENES):
    """(filas, filas_con_sinonimo) del diccionario de genes.

    Un sinonimo es un nombre distinto del simbolo y del locus tag. Se cuenta
    en cada corrida y se reporta; **no hay prueba que lo acote**, porque una
    que fallara al crecer castigaria la mejora y rompería CI por una buena
    noticia. Las pruebas fijan comportamiento --que el mapeo sea correcto, que
    la ambiguedad se detecte, que lo no resuelto se reporte--; el tamano del
    catalogo es un hecho de la corrida y va al informe.
    """
    filas = con_sinonimo = 0
    with io.open(ruta, encoding="utf-8") as f:
        cols = f.readline().rstrip("\n").split("\t")
        for linea in f:
            if not linea.strip():
                continue
            d = dict(zip(cols, linea.rstrip("\n").split("\t")))
            filas += 1
            alias = [a.strip() for a in (d.get("alias") or "").split("|")
                     if a.strip()]
            if [a for a in alias
                    if a not in (d.get("locus_tag"), d.get("simbolo"))]:
                con_sinonimo += 1
    return filas, con_sinonimo


def cobertura_de_fuente(con, fuente, diccionario=None):
    """La cobertura de mapeo sobre los nombres reales que trajo una fuente.

    Se mide sobre `genes_raw` cuando lo hay, que es como la fuente escribio
    los nombres, y no sobre `locus_tags`, que ya vienen resueltos cuando la
    fuente los da. Si se midiera sobre los resueltos, la tasa saldria
    siempre alta y no diria nada.
    """
    nombres = []
    for f in _db.bronze_vigente(con):
        if f["fuente"] != fuente:
            continue
        crudos = [x for x in (f["genes_raw"] or "").split("|") if x.strip()]
        nombres.extend(crudos or
                       [x for x in (f["locus_tags"] or "").split("|") if x])
    return cobertura_mapeo(nombres, diccionario)


def curar(con, log=lambda m: None, diccionario=None, hebras=None):
    """Recorre el bronce y reescribe la capa curada. Devuelve el resumen.

    Rehace desde cero (`vaciar_silver`) en vez de actualizar fila a fila: la
    curacion es determinista sobre el bronce, y una regla que cambie puede
    fusionar dos operones que antes estaban separados. Eso no se expresa como
    actualizacion, y un diff a medias dejaria huerfanos que nadie limpia.
    """
    diccionario = cargar_diccionario() if diccionario is None else diccionario
    hebras = cargar_hebras() if hebras is None else hebras
    if not hebras:
        log("  aviso: sin GFF en cache, la hebra no se verifica")

    # 1 y 2. Normalizar y validar, agrupando por conjunto de genes.
    por_clave = collections.OrderedDict()
    sin_resolver = collections.Counter()
    sin_resolver_ambiguo = {}
    paralogos = cargar_paralogos(diccionario)
    descartadas = 0
    # `bronze_vigente` y no `bronze_de`: el bronce conserva una fila por
    # descarga, asi que la tabla entera trae versiones viejas de un mismo
    # operon junto a la corregida, las dos con la misma pinta de buenas.
    for f in _db.bronze_vigente(con):
        nombres = [x for x in (f["locus_tags"] or "").split("|") if x]
        if not nombres:
            nombres = [x for x in (f["genes_raw"] or "").split("|") if x]
        locus, fuera, ambiguos = normalizar(nombres, diccionario,
                                           paralogos)
        for x in fuera:
            sin_resolver[x] += 1
        for nombre, candidatos in ambiguos:
            sin_resolver_ambiguo[nombre] = candidatos
        if len(locus) < 2:
            # Un solo gen no es un operon. No es un error de la fuente: ODB y
            # BioCyc registran unidades de transcripcion de un gen.
            descartadas += 1
            continue
        por_clave.setdefault(clave_de(locus), []).append(
            (f, locus, fuera, ambiguos))

    # 3. Deduplicar: la clave ya agrupo los identicos. Los subconjuntos se
    # marcan como alternativas, no se fusionan.
    conjuntos = dict((k, frozenset(k.split("|"))) for k in por_clave)
    alternativas = set()
    for k, s in conjuntos.items():
        for otra, s2 in conjuntos.items():
            if k != otra and s < s2:
                alternativas.add(k)
                break

    _db.vaciar_silver(con)
    n = 0
    for clave, grupo in por_clave.items():
        filas = [g[0] for g in grupo]
        locus = grupo[0][1]
        fuentes = set(f["fuente"] for f in filas)
        independientes = fuentes - FUENTES_NO_INDEPENDIENTES
        adyacente = es_adyacente(locus)
        igual_hebra, hebra = misma_hebra(locus, hebras)

        revisar = []
        if not adyacente:
            revisar.append("no_adyacente")
        if igual_hebra is False:
            revisar.append("hebras_distintas")
        elif igual_hebra is None:
            revisar.append("hebra_no_verificada")
        if any(g[2] for g in grupo):
            revisar.append("genes_sin_resolver")
        if any(g[3] for g in grupo):
            revisar.append("nombre_ambiguo")

        pmids = sorted(set(
            p.strip() for f in filas for p in (f["pmid"] or "").split(";")
            if p.strip()))

        _db.guardar_silver(con, {
            "clave_genes": clave,
            "nombre": None,
            "locus_tags": "|".join(locus),
            "n_genes": len(locus),
            "cadena": hebra,
            "nivel_evidencia": nivel_de(filas),
            # Cuenta fuentes distintas, y las dos que comparten motor de
            # prediccion valen por una: coincidir no es confirmacion.
            "n_fuentes": len(independientes) + (1 if len(
                fuentes & FUENTES_NO_INDEPENDIENTES) else 0),
            "pmids": ";".join(pmids) or None,
            "adyacente": adyacente,
            "es_alternativa": clave in alternativas,
            # 5. Se marca solo si CDBProm respalda este mismo conjunto.
            "promotor_cdbprom": "cdbprom" in fuentes,
            "revisar": ";".join(revisar) or None,
        }, [(f["fuente"], f["id_fuente"]) for f in filas])
        n += 1

    resumen = _db.resumen_silver(con)
    resumen["descartadas_un_gen"] = descartadas
    resumen["nombres_sin_resolver"] = len(sin_resolver)
    resumen["top_sin_resolver"] = sin_resolver.most_common(15)
    resumen["cobertura"] = dict(
        (f, cobertura_de_fuente(con, f, diccionario))
        for f in sorted(set(x["fuente"] for x in _db.bronze_vigente(con))))
    # Lo que la fuente retiro entre dos extracciones completas. Va al informe
    # y no a una prueba: es un hecho de la corrida, no un contrato del codigo.
    resumen["retirados"] = _db.retirados(con)
    resumen["ambiguos"] = sin_resolver_ambiguo
    # El tamano del diccionario de sinonimos, por la misma razon. Una prueba
    # que fallara al crecer castigaria la mejora y romperia CI por una buena
    # noticia; el informe lo dice en cada corrida sin bloquear nada.
    resumen["sinonimos"] = contar_sinonimos()
    log("  %d operones curados desde %d filas de bronce"
        % (n, sum(len(v) for v in por_clave.values())))
    return resumen
