"""Ejemplos de entrenamiento del BioBERT desde la base curada.

Es supervisión distante. Una oración del corpus público se vuelve ejemplo
positivo cuando su par (regulador, blanco), llevado a locus PA####, coincide
con una interacción de la base curada **y** el artículo de la oración es uno
de los que esa fila cita. La etiqueta sale del signo de la fila: '+' ->
activates, '-' -> represses, '?' -> regulates. Los negativos (no_relation)
son otros pares de esos mismos artículos que no coinciden con ninguna
interacción curada, en ninguna dirección.

Qué no entra como positivo, y por qué
-------------------------------------
- Homología: el artículo citado no reporta la relación (PLAN.md 2.4, la regla
  b cubre el 0.3 % de esas filas aun con el texto completo a la mano).
- `Origen` BioBERT: esas filas las propuso el modelo del asesor, y entrenar
  con ellas le enseñaría al modelo sus propias predicciones. «Ambos» sí
  entra, porque la versión histórica de la base también la tiene.
- `d`: nadie ha dicho qué significa (PLAN.md, pregunta 3).
- Autorregulación (regulador igual a blanco): `red.py` la descarta por
  omisión en la inferencia, así que el modelo no la necesita, y sin sintaxis
  no se distingue «NalD reprime nalD» de una oración que nombra `nalD` dos
  veces, una como ΔnalD.
- Un par que en el mismo artículo recibe dos etiquetas distintas se descarta
  entero. Un '?' junto a un '+' también cuenta como conflicto: si la regla
  fuera «gana el signo resuelto», sería una decisión de etiquetado que hoy
  nadie ha tomado.
- Lo reservado para evaluar (ver `leer_reservas`) no entra ni como positivo
  ni como negativo.

Qué sale
--------
Los tres `entity_marked_{train,dev,test}.jsonl` del formato del asesor (`text`,
`label`, `pmid`, `tf`, `target`, más `id_par` para rastrear el ejemplo en el
`pares.jsonl` público), con todo en train y dev y test vacíos. No es un
descuido: la única partición aceptable es por PMID y con test retenido
(PLAN.md 1.3), y esa la hace `etapa2/particionar.py --por pmid`, que además
mide la fuga y rechaza la partición si queda alguna. Con dev y test vacíos,
esta salida no sirve para entrenar sin pasar antes por ahí.

Confidencialidad
----------------
Los ejemplos derivan de la base curada y son tan confidenciales como ella.
`ejecutar()` se niega a escribir dentro del repositorio o de cualquier copia
de trabajo de git, y reporta solo conteos: ni oraciones, ni genes, ni locus,
ni PMIDs. Lo que vuelve del servidor son números.

Biblioteca estándar y Python 3.8: corre con el intérprete del entorno conda
del asesor sin instalar nada.
"""

import collections
import csv
import datetime
import hashlib
import json
import os
import re

from grn_bronce import texto as _texto
from grn_comun import procedencia
from grn_verificacion import validacion

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fecha de arranque de esta pista, como las otras semillas del proyecto
# (20260904 la muestra de 50, 20260819 la partición de etapa2).
SEMILLA = 20261008
# Tres oraciones por (artículo, par). El artículo que estudia un par lo nombra
# en muchas oraciones, y la base ya está concentrada: cinco artículos sostienen
# el 32 % de sus filas exigibles (PLAN.md 2.4). Sin tope, esos pocos artículos
# pesarían todavía más en ejemplos, y el modelo aprendería su redacción en vez
# de la relación.
MAX_POR_PAR = 3
PROPORCION_NEGATIVOS = 1.0

ETIQUETA_DE_SIGNO = {"+": "activates", "-": "represses", "?": "regulates"}
SIN_RELACION = "no_relation"
# El orden de `etapa2/particionar.py`, que es el del checkpoint del servidor
# (alfabético). `test_entrenamiento` comprueba que no se separen.
ETIQUETAS = ("activates", "no_relation", "regulates", "represses")
ARCHIVOS = ("entity_marked_train.jsonl", "entity_marked_dev.jsonl",
            "entity_marked_test.jsonl")
ARCHIVO_CONTEOS = "conteos.json"

# Lo que se lee de cada línea del `pares.jsonl` del puente. El resto de las
# llaves se tira al leer: no hace falta y no se arrastra.
CAMPOS_PAR = ("text", "pmid", "tf", "target", "id_par", "oracion_cruda",
              "tf_locus", "target_locus", "autorregulacion")

# La muestra de 50 juicios con la que se mide el 44 % (PLAN.md 2.3). Son datos
# propios, versionados, sin nada de la base curada.
RUTA_JUICIOS = os.path.join(RAIZ_REPO, "etapa2", "evaluacion",
                            "juicio_consolidado.csv")

# En este orden se le asigna a cada fila excluida un solo motivo.
MOTIVOS_EXCLUSION = ("homologia", "biobert", "signo_d", "signo_ilegible",
                     "autorregulacion", "sin_pmid")

_MARCADORES = re.compile(r"</?e[12]>")
_NO_ALFANUM = re.compile(r"[^a-z0-9]+")
_PMID = re.compile(r"^[0-9]{1,9}$")
_TIPOS_RESERVA = {"pmid": "pmid", "oracion": "oracion", u"oración": "oracion"}


# ------------------------------------------------------------------ reservas

def _pmid_valido(valor):
    """El PMID como texto sin ceros a la izquierda, o None si no es número."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    if not _PMID.match(texto) or int(texto) == 0:
        return None
    return str(int(texto))


def leer_reservas(rutas):
    """({'pmids': set, 'oraciones': set}, conteos) de cero o más archivos.

    Formato de un archivo de reservas: texto UTF-8, una reserva por línea,
    `tipo<TAB>valor`.

        # comentario
        pmid	12345678
        oracion	LasR activates rhlR transcription.

    `pmid` aparta todos los pares de ese artículo; `oracion`, los de esa
    oración en cualquier artículo, y también los de toda oración del corpus
    que la contenga o sea un pedazo de ella, si el texto contenido tiene al
    menos `MINIMO_CONTENCION` caracteres (ver `_reservada`). La oración se
    compara con los espacios normalizados (`grn_bronce.texto.normalizar_espacios`
    sobre la `oracion_cruda` del par), así que un salto de línea o un doble
    espacio no la vuelven otra. Se ignoran las líneas vacías y las que
    empiezan con `#`.

    Un tipo desconocido, una línea sin tabulador o un PMID que no es número
    detienen la lectura con ValueError: una reserva mal escrita que se
    ignorara en silencio dejaría entrar al entrenamiento justo lo que se
    quería apartar.
    """
    if isinstance(rutas, str):
        # Una sola ruta suelta se recorrería letra por letra.
        rutas = [rutas]
    pmids, oraciones = set(), set()
    archivos = 0
    for ruta in rutas or ():
        archivos += 1
        with open(ruta, encoding="utf-8-sig") as f:
            for numero, linea in enumerate(f, 1):
                linea = linea.rstrip("\r\n")
                if not linea.strip() or linea.lstrip().startswith("#"):
                    continue
                tipo, tab, valor = linea.partition("\t")
                if not tab:
                    raise ValueError(
                        "%s, línea %d: falta el tabulador entre el tipo y el "
                        "valor." % (ruta, numero))
                tipo = _TIPOS_RESERVA.get(tipo.strip().lower())
                if tipo is None:
                    raise ValueError(
                        "%s, línea %d: tipo desconocido; se esperaba pmid u "
                        "oracion." % (ruta, numero))
                if tipo == "pmid":
                    pmid = _pmid_valido(valor)
                    if pmid is None:
                        raise ValueError("%s, línea %d: el PMID no es un "
                                         "número." % (ruta, numero))
                    pmids.add(pmid)
                else:
                    oracion = _texto.normalizar_espacios(valor)
                    if oracion:
                        oraciones.add(oracion)
    conteos = {"archivos": archivos, "pmids": len(pmids),
               "oraciones": len(oraciones)}
    return {"pmids": pmids, "oraciones": oraciones}, conteos


def _escribir_atomico(ruta, lineas):
    """Temporal y `os.replace`: si algo falla a media escritura, el archivo
    anterior queda intacto y no uno cortado que parezca bueno."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for linea in lineas:
            f.write(linea)
            f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta)


def escribir_reservas(ruta, pmids=(), oraciones=()):
    """Escribe un archivo de reservas (formato en `leer_reservas`).

    Devuelve {'pmids': n, 'oraciones': n}. Las oraciones se guardan ya
    normalizadas, así que no pueden traer un tabulador ni un salto de línea
    que rompa el formato.
    """
    limpios = set()
    for valor in pmids:
        pmid = _pmid_valido(valor)
        if pmid is None:
            raise ValueError("Un PMID por reservar no es un número.")
        limpios.add(pmid)
    frases = set()
    for oracion in oraciones:
        oracion = _texto.normalizar_espacios(oracion or "")
        if oracion:
            frases.add(oracion)
    lineas = [
        "# Reservas del entrenamiento: nada de aquí entra como positivo ni "
        "como negativo.",
        "# Una por línea, tipo<TAB>valor; tipo es pmid u oracion. "
        "Lo lee grn_verificacion.entrenamiento.leer_reservas.",
    ]
    lineas.extend("pmid\t%s" % p for p in sorted(limpios, key=int))
    lineas.extend("oracion\t%s" % o for o in sorted(frases))
    _escribir_atomico(ruta, lineas)
    return {"pmids": len(limpios), "oraciones": len(frases)}


def reservas_de_csv(ruta_csv, columna_pmid="pmid", columna_oracion=None):
    """(pmids, oraciones) de las columnas de un CSV, como conjuntos.

    Pensado para los CSV de evaluación propios (la muestra de 50 juicios). Un
    PMID que no es número detiene la lectura, por la misma razón que en
    `leer_reservas`.
    """
    with open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        campos = lector.fieldnames or []
        for columna in (columna_pmid, columna_oracion):
            if columna and columna not in campos:
                raise ValueError("%s no tiene la columna %s."
                                 % (ruta_csv, columna))
        pmids, oraciones = set(), set()
        for numero, fila in enumerate(lector, 2):
            if columna_pmid:
                valor = (fila.get(columna_pmid) or "").strip()
                if valor:
                    pmid = _pmid_valido(valor)
                    if pmid is None:
                        raise ValueError("%s, línea %d: el PMID no es un "
                                         "número." % (ruta_csv, numero))
                    pmids.add(pmid)
            if columna_oracion:
                oracion = _texto.normalizar_espacios(
                    fila.get(columna_oracion) or "")
                if oracion:
                    oraciones.add(oracion)
    return pmids, oraciones


def escribir_reservas_de_juicios(ruta_salida, ruta_csv=RUTA_JUICIOS,
                                 oraciones_extra=()):
    """El archivo de reservas con los PMIDs de la muestra de 50 juicios.

    Con esa muestra se recalcula el 44 % al conectar el clasificador (PLAN.md
    1.1); si sus artículos entraran al entrenamiento, la cifra nueva mediría
    memoria y no precisión. Se reserva por PMID, que cubre todas sus
    oraciones. `oraciones_extra` suma oraciones sueltas de otra evaluación.
    """
    pmids, _ = reservas_de_csv(ruta_csv, "pmid")
    return escribir_reservas(ruta_salida, pmids, oraciones_extra)


# --------------------------------------------------------------------- pares

def leer_pares(ruta):
    """Los pares del puente (`pares.jsonl`), con solo los campos de CAMPOS_PAR.

    Es el corpus público, así que los errores pueden decir línea y campo; aun
    así no repiten el contenido, por costumbre.
    """
    pares = []
    with open(ruta, encoding="utf-8") as f:
        for numero, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                fila = json.loads(linea)
            except ValueError:
                raise ValueError("%s, línea %d: no es JSON." % (ruta, numero))
            if not isinstance(fila, dict):
                raise ValueError("%s, línea %d: no es un objeto JSON."
                                 % (ruta, numero))
            faltan = [c for c in CAMPOS_PAR if c not in fila]
            if faltan:
                raise ValueError("%s, línea %d: faltan los campos %s."
                                 % (ruta, numero, ", ".join(faltan)))
            pares.append(dict((c, fila[c]) for c in CAMPOS_PAR))
    return pares


def _loci(valor):
    """Tupla ordenada de locus; () si no hay; None si alguno no es de PAO1.

    Un par con un locus que no es PA#### (un id sintético de operón, uno de
    PA14) no se puede comparar con la base: como positivo no coincidiría
    nunca, y como negativo podría ser una relación curada con otro nombre.
    """
    if valor is None:
        return ()
    if isinstance(valor, str):
        valor = [valor]
    loci = set()
    for x in valor:
        locus = str(x).strip().upper()
        if not locus:
            continue
        if not validacion.LOCUS.match(locus):
            return None
        loci.add(locus)
    return tuple(sorted(loci))


def _marcado_valido(texto):
    for marca in ("<e1>", "</e1>", "<e2>", "</e2>"):
        if texto.count(marca) != 1:
            return False
    return (texto.index("<e1>") < texto.index("</e1>")
            and texto.index("<e2>") < texto.index("</e2>"))


def canonico(texto):
    """El texto sin marcadores, en minúsculas y sin puntuación.

    Es la forma con la que `etapa2/particionar.py` VERIFICA la fuga (su
    `canonico()`), escrita aquí aparte porque `etapa2` está congelada y no es
    paquete; `test_entrenamiento` comprueba que las dos digan lo mismo. Dos
    ejemplos de artículos distintos con el mismo texto canónico pero distinta
    ventana caen en grupos distintos al particionar, y la verificación los
    encuentra como fuga y rechaza la partición entera.
    """
    return " ".join(
        _NO_ALFANUM.sub(" ", _MARCADORES.sub("", texto).lower()).split())


# ------------------------------------------------------------ la construcción

def _conteos_vacios():
    return {
        "pares_leidos": 0,
        "reservados_por_pmid": 0,
        "reservados_por_oracion": 0,
        "pmids_reservados_presentes": 0,
        "marcado_invalido": 0,
        "sin_locus": 0,
        "locus_no_pao1": 0,
        "filas_base": 0,
        "filas_elegibles": 0,
        "filas_excluidas": dict((m, 0) for m in MOTIVOS_EXCLUSION),
        "filas_elegibles_con_oracion": 0,
        "pares_con_fila_elegible": 0,
        "pares_solo_con_filas_excluidas": 0,
        "claves_en_conflicto": 0,
        "pares_en_conflicto": 0,
        "oraciones_duplicadas": 0,
        "recortados_por_tope": 0,
        "negativos_descartados_autorregulacion": 0,
        "negativos_descartados_par_curado": 0,
        "negativos_duplicados": 0,
        "negativos_recortados_por_tope": 0,
        "candidatos_negativos": 0,
        "negativos_muestreados": 0,
        "negativos_en_oracion_con_positivo": 0,
        "repetidos_entre_pmids": 0,
        "ejemplos": 0,
        "positivos": 0,
        "negativos": 0,
        "por_etiqueta": dict((e, 0) for e in ETIQUETAS),
        "positivos_por_origen": {},
        "pmids_distintos": 0,
        "pmids_con_positivo": 0,
        "ejemplos_en_los_5_pmids_mayores": 0,
    }


def _motivo_exclusion(fila):
    """Por qué una fila de la base no puede dar positivos, o None."""
    if fila["homologia"]:
        return "homologia"
    if fila["origen"] == "biobert":
        return "biobert"
    if fila["signo"] == "d":
        return "signo_d"
    if fila["signo"] not in ETIQUETA_DE_SIGNO:
        return "signo_ilegible"
    if fila["regulador"] == fila["blanco"]:
        return "autorregulacion"
    if not fila["pmids"]:
        return "sin_pmid"
    return None


def _indexar(interacciones, c):
    """(elegibles, excluidas, curados).

    `elegibles`: {(pmid, regulador, blanco): [(i, fila)]} de las filas que
    pueden dar positivos. `excluidas`: las mismas claves de las que no.
    `curados`: todo par de la base en las dos direcciones, de TODA fila, sin
    importar homología, origen, signo ni PMID. Es el conjunto que veta
    negativos: un par que la base da por cierto en cualquier artículo no se
    puede enseñar como «sin relación» en otro.
    """
    elegibles = collections.defaultdict(list)
    excluidas = set()
    curados = set()
    for i, fila in enumerate(interacciones):
        c["filas_base"] += 1
        a, b = fila["regulador"], fila["blanco"]
        curados.add((a, b))
        curados.add((b, a))
        motivo = _motivo_exclusion(fila)
        if motivo:
            c["filas_excluidas"][motivo] += 1
            for pmid in fila["pmids"]:
                excluidas.add((pmid, a, b))
            continue
        c["filas_elegibles"] += 1
        for pmid in fila["pmids"]:
            elegibles[(pmid, a, b)].append((i, fila))
    return elegibles, excluidas, curados


# El texto contenido más corto que todavía cuenta como la misma oración. Un
# fragmento corto, o la cadena vacía, que está contenida en cualquier otra,
# apartaría medio corpus.
MINIMO_CONTENCION = 40


def _reservada(oracion, oraciones_reservadas):
    """Si la oración del par es una reservada, la contiene o es un pedazo de
    ella.

    Igualdad no basta: el bronce y el conjunto ciego no siempre cortan igual.
    El 8-oct, 8 de las 182 oraciones ciegas llegaban a la corrida 4 como un
    fragmento de 127 a 214 caracteres, y comparando por igualdad se colaban
    16 pares al entrenamiento.
    """
    if oracion in oraciones_reservadas:
        return True
    for reservada in oraciones_reservadas:
        if len(reservada) <= len(oracion):
            if len(reservada) >= MINIMO_CONTENCION and reservada in oracion:
                return True
        elif len(oracion) >= MINIMO_CONTENCION and oracion in reservada:
            return True
    return False


def _filtrar_pares(pares, pmids_reservados, oraciones_reservadas, c):
    """Los pares que pueden ser ejemplo, ya normalizados."""
    vivos = []
    reservados_vistos = set()
    # Muchos pares comparten oración: la búsqueda por contención se hace una
    # vez por oración distinta y no una por par.
    decididas = {}
    for par in pares:
        c["pares_leidos"] += 1
        pmid = _pmid_valido(par["pmid"])
        if pmid is None:
            raise ValueError("Un par trae un pmid que no es un número.")
        oracion = _texto.normalizar_espacios(par.get("oracion_cruda") or "")
        # Las reservas van antes que todo lo demás: lo reservado no puede
        # aparecer ni en los conteos de candidatos.
        if pmid in pmids_reservados:
            c["reservados_por_pmid"] += 1
            reservados_vistos.add(pmid)
            continue
        reservada = decididas.get(oracion)
        if reservada is None:
            reservada = decididas[oracion] = _reservada(
                oracion, oraciones_reservadas)
        if reservada:
            c["reservados_por_oracion"] += 1
            continue
        texto = par.get("text") or ""
        if not _marcado_valido(texto):
            c["marcado_invalido"] += 1
            continue
        tf_locus = _loci(par.get("tf_locus"))
        target_locus = _loci(par.get("target_locus"))
        if tf_locus is None or target_locus is None:
            c["locus_no_pao1"] += 1
            continue
        if not tf_locus or not target_locus:
            c["sin_locus"] += 1
            continue
        vivos.append({
            "pmid": pmid,
            "oracion": oracion,
            "text": texto,
            "tf": par.get("tf"),
            "target": par.get("target"),
            "id_par": str(par.get("id_par")),
            "tf_locus": tf_locus,
            "target_locus": target_locus,
            # El operón que contiene al gen del propio regulador también es
            # autorregulación (PhoB -> phoBR), aunque el puente no la marque.
            "autorregulacion": bool(par.get("autorregulacion"))
            or bool(set(tf_locus) & set(target_locus)),
        })
    c["pmids_reservados_presentes"] = len(reservados_vistos)
    return vivos


def _clave(registro):
    return (registro["pmid"], registro["tf_locus"], registro["target_locus"])


def _orden_estable(registro):
    return (registro["id_par"], registro["text"])


def _elegir(registros, k, semilla, sal):
    """Los `k` registros de menor huella sembrada, en orden estable.

    Se ordena por sha256(semilla|sal|pmid|id_par) y no con `random`: la
    elección no depende de la versión de Python (el servidor corre 3.10, la
    laptop 3.12) ni del orden de llegada, y un par nuevo en el corpus no
    reacomoda lo que se eligió para los demás.
    """
    def orden(r):
        llave = "%d|%s|%s|%s" % (semilla, sal, r["pmid"], r["id_par"])
        return (hashlib.sha256(llave.encode("utf-8")).hexdigest(),
                r["id_par"], r["text"])
    return sorted(sorted(registros, key=orden)[:k], key=_orden_estable)


def _depurar_y_topar(registros, semilla, max_por_par):
    """(lista, duplicadas, recortadas) de un grupo (pmid, par).

    Primero una oración por texto: el mismo resumen llega a veces por la base
    y por el texto completo, y contarlo dos veces gastaría el tope en copias.
    Después, a lo más `max_por_par` oraciones distintas.
    """
    unicos = collections.OrderedDict()
    for r in sorted(registros, key=_orden_estable):
        unicos.setdefault(r["oracion"], r)
    duplicadas = len(registros) - len(unicos)
    lista = list(unicos.values())
    recortadas = 0
    if len(lista) > max_por_par:
        recortadas = len(lista) - max_por_par
        lista = _elegir(lista, max_por_par, semilla, "tope")
    return lista, duplicadas, recortadas


def _positivos(vivos, elegibles, excluidas, semilla, max_por_par, c):
    grupos = collections.OrderedDict()
    etiquetas, origenes = {}, {}
    encontradas = set()
    for r in vivos:
        coincidencias = []
        toca_excluida = False
        for a in r["tf_locus"]:
            for b in r["target_locus"]:
                coincidencias.extend(elegibles.get((r["pmid"], a, b), ()))
                toca_excluida = (toca_excluida
                                 or (r["pmid"], a, b) in excluidas)
        if not coincidencias:
            if toca_excluida:
                c["pares_solo_con_filas_excluidas"] += 1
            continue
        c["pares_con_fila_elegible"] += 1
        clave = _clave(r)
        grupos.setdefault(clave, []).append(r)
        etiquetas.setdefault(clave, set()).update(
            ETIQUETA_DE_SIGNO[f["signo"]] for _, f in coincidencias)
        origenes.setdefault(clave, set()).update(
            f["origen"] for _, f in coincidencias)
        encontradas.update(i for i, _ in coincidencias)
    c["filas_elegibles_con_oracion"] = len(encontradas)

    positivos = []
    for clave in sorted(grupos):
        if len(etiquetas[clave]) > 1:
            c["claves_en_conflicto"] += 1
            c["pares_en_conflicto"] += len(grupos[clave])
            continue
        etiqueta = next(iter(etiquetas[clave]))
        origen = "+".join(sorted(origenes[clave]))
        lista, duplicadas, recortadas = _depurar_y_topar(
            grupos[clave], semilla, max_por_par)
        c["oraciones_duplicadas"] += duplicadas
        c["recortados_por_tope"] += recortadas
        for r in lista:
            positivos.append(dict(r, label=etiqueta, origen=origen))
    return positivos, set(grupos)


def _negativos(vivos, positivos, claves_positivas, curados, semilla,
               max_por_par, proporcion, c):
    """Pares sin relación curada, de los artículos que dieron positivos.

    A diferencia del `no_relation` de E. coli (el 98.4 % comparte ventana Y
    par con un positivo y solo cambia qué mención lleva el marcador, ver
    etapa2/README.md), aquí un negativo es otro par: dos genes que coocurren
    sin que la base registre relación entre ellos en ninguna dirección. Es la
    negativa que el modelo encuentra en la inferencia sobre PAO1.

    Se toman solo de artículos con algún positivo porque son los que la base
    leyó: en un artículo que no cita, la ausencia de una fila no dice nada.
    """
    pmids_con_positivo = set(p["pmid"] for p in positivos)
    grupos = collections.OrderedDict()
    for r in vivos:
        if r["pmid"] not in pmids_con_positivo:
            continue
        clave = _clave(r)
        if clave in claves_positivas:
            continue
        if r["autorregulacion"]:
            c["negativos_descartados_autorregulacion"] += 1
            continue
        if any((a, b) in curados
               for a in r["tf_locus"] for b in r["target_locus"]):
            c["negativos_descartados_par_curado"] += 1
            continue
        grupos.setdefault(clave, []).append(r)

    candidatos = []
    for clave in sorted(grupos):
        lista, duplicadas, recortadas = _depurar_y_topar(
            grupos[clave], semilla, max_por_par)
        c["negativos_duplicados"] += duplicadas
        c["negativos_recortados_por_tope"] += recortadas
        candidatos.extend(lista)
    c["candidatos_negativos"] = len(candidatos)

    k = int(round(proporcion * len(positivos)))
    elegidos = (_elegir(candidatos, k, semilla, "negativos")
                if len(candidatos) > k else candidatos)
    c["negativos_muestreados"] = len(elegidos)
    con_positivo = set((p["pmid"], p["oracion"]) for p in positivos)
    c["negativos_en_oracion_con_positivo"] = sum(
        1 for r in elegidos if (r["pmid"], r["oracion"]) in con_positivo)
    return [dict(r, label=SIN_RELACION, origen="") for r in elegidos]


def _sin_repetidos_entre_pmids(ejemplos, c):
    """Una oración idéntica en dos artículos se queda solo en el de menor PMID.

    No aporta información nueva, y si los dos artículos cayeran en lados
    distintos de la partición sería fuga: el modelo se evaluaría sobre un
    texto que ya vio. `particionar.py` agrupa por texto exacto pero verifica
    por texto canónico, así que una diferencia de puntuación o de mayúsculas
    entre las dos copias la haría rechazar la partición entera.
    """
    pmids_de = collections.defaultdict(set)
    for e in ejemplos:
        pmids_de[canonico(e["text"])].add(int(e["pmid"]))
    salida = []
    for e in ejemplos:
        if int(e["pmid"]) != min(pmids_de[canonico(e["text"])]):
            c["repetidos_entre_pmids"] += 1
            continue
        salida.append(e)
    return salida


def _resumir(ejemplos, c):
    por_etiqueta = collections.Counter(e["label"] for e in ejemplos)
    c["por_etiqueta"] = dict((e, por_etiqueta.get(e, 0)) for e in ETIQUETAS)
    positivos = [e for e in ejemplos if e["label"] != SIN_RELACION]
    c["ejemplos"] = len(ejemplos)
    c["positivos"] = len(positivos)
    c["negativos"] = len(ejemplos) - len(positivos)
    por_origen = collections.Counter(e["origen"] for e in positivos)
    c["positivos_por_origen"] = dict(sorted(por_origen.items()))
    por_pmid = collections.Counter(e["pmid"] for e in ejemplos)
    c["pmids_distintos"] = len(por_pmid)
    c["pmids_con_positivo"] = len(set(e["pmid"] for e in positivos))
    c["ejemplos_en_los_5_pmids_mayores"] = sum(
        n for _, n in por_pmid.most_common(5))


def _a_salida(e):
    """El ejemplo en el formato del asesor, más `id_par` para rastrearlo."""
    return collections.OrderedDict([
        ("text", e["text"]),
        ("label", e["label"]),
        ("pmid", int(e["pmid"])),
        ("tf", e["tf"]),
        ("target", e["target"]),
        ("id_par", e["id_par"]),
    ])


def construir(pares, interacciones, reservas=None, semilla=SEMILLA,
              max_por_par=MAX_POR_PAR,
              proporcion_negativos=PROPORCION_NEGATIVOS):
    """(ejemplos, conteos).

    `pares`: los del puente (ver `leer_pares`). `interacciones`: las de
    `validacion.normalizar`. `reservas`: {'pmids': set, 'oraciones': set}
    como lo devuelve `leer_reservas`, o None.

    Un positivo es un par cuyo artículo está en los PMIDs de una fila elegible
    de la base, con el regulador de la fila en `tf_locus` y el blanco en
    `target_locus` (un operón se expande a sus genes en el puente). La clave
    del ejemplo es (pmid, tf_locus, target_locus): si esa clave junta
    etiquetas distintas, se descarta. Por clave quedan a lo más `max_por_par`
    oraciones distintas, elegidas con la semilla.

    Los negativos salen de los artículos con algún positivo, sin
    autorregulación, y solo si ninguna combinación de sus locus está curada
    en ninguna dirección. Se muestrean hasta `proporcion_negativos` veces el
    número de positivos.

    Todo es determinista para una misma entrada y semilla. Los conteos son
    solo números y categorías (etiquetas, orígenes, motivos).
    """
    if max_por_par < 1:
        raise ValueError("max_por_par tiene que ser 1 o más.")
    if proporcion_negativos < 0:
        raise ValueError("proporcion_negativos no puede ser negativa.")
    reservas = reservas or {}
    pmids_reservados = set(reservas.get("pmids") or ())
    oraciones_reservadas = set(reservas.get("oraciones") or ())

    c = _conteos_vacios()
    elegibles, excluidas, curados = _indexar(interacciones, c)
    vivos = _filtrar_pares(pares, pmids_reservados, oraciones_reservadas, c)
    positivos, claves_positivas = _positivos(
        vivos, elegibles, excluidas, semilla, max_por_par, c)
    negativos = _negativos(vivos, positivos, claves_positivas, curados,
                           semilla, max_por_par, proporcion_negativos, c)
    ejemplos = _sin_repetidos_entre_pmids(positivos + negativos, c)
    ejemplos.sort(key=lambda e: (int(e["pmid"]), e["id_par"], e["label"],
                                 e["text"]))
    _resumir(ejemplos, c)
    return [_a_salida(e) for e in ejemplos], c


# --------------------------------------------------------- dónde se escribe

def _contiene(raiz, ruta):
    a = os.path.normcase(os.path.realpath(os.path.abspath(raiz)))
    b = os.path.normcase(os.path.realpath(os.path.abspath(ruta)))
    try:
        return os.path.commonpath([a, b]) == a
    except ValueError:
        # En Windows, rutas en unidades distintas no tienen ancestro común.
        return False


def _copia_de_git(ruta):
    """La carpeta con `.git` que contiene a `ruta`, o None."""
    actual = os.path.realpath(os.path.abspath(ruta))
    while True:
        if os.path.exists(os.path.join(actual, ".git")):
            return actual
        padre = os.path.dirname(actual)
        if padre == actual:
            return None
        actual = padre


def exigir_fuera_del_repositorio(ruta, raiz=RAIZ_REPO):
    """ValueError si `ruta` cae dentro del repositorio o de una copia de git.

    Los ejemplos son confidenciales. Dentro del repositorio quedan a un `git
    add -f` de un remoto público, y a la vista de las herramientas de una
    sesión de Claude, que trabaja en esa carpeta: `.gitignore` frena a git,
    no a quien abre el archivo. La segunda comprobación cubre otra copia del
    repositorio o un paquete instalado fuera, donde `raiz` ya no lo señala.
    """
    if _contiene(raiz, ruta):
        raise ValueError(
            "La salida %s queda dentro del repositorio (%s). Los ejemplos "
            "derivan de la base curada y son confidenciales: escríbelos "
            "fuera, por ejemplo bajo $GRN_DATOS en el servidor." % (ruta, raiz))
    copia = _copia_de_git(ruta)
    if copia:
        raise ValueError(
            "La salida %s queda dentro de una copia de trabajo de git (%s). "
            "Los ejemplos son confidenciales: escríbelos fuera de cualquier "
            "repositorio." % (ruta, copia))


# --------------------------------------------------------------- el resumen

def _origenes_legibles(clave):
    return "+".join(validacion.ETIQUETA_ORIGEN.get(o, o)
                    for o in clave.split("+") if o)


def resumen(conteos):
    """Las líneas que ve quien corre esto: solo números y categorías."""
    b = conteos["base"]
    r = conteos["reservas"]
    e = conteos["entrenamiento"]
    s, o, x = b["signo"], b["origen"], e["filas_excluidas"]
    pe = e["por_etiqueta"]
    lineas = [
        "Base curada: %d filas con valores (%d vacías); %d con los dos locus "
        "válidos y %d descartadas por locus."
        % (b["filas"], b["filas_vacias"], b["interacciones"],
           b["locus_invalido"]),
        "  signo: + %d; - %d; ? %d; d %d; ilegible %d (%d con un locus corrido)."
        % (s["+"], s["-"], s["?"], s["d"], s["ilegible"],
           b["signo_locus_corrido"]),
        "  origen: Histórica %d; BioBERT %d; Ambos %d; otro %d."
        % (o["historica"], o["biobert"], o["ambos"], o["otro"]),
        "  homología %d; PMIDs distintos %d; filas sin PMID %d; DOIs "
        "descartados %d; números descartados %d."
        % (b["homologia"], b["pmids_distintos"], b["filas_sin_pmid"],
           b["dois_descartados"], b["numeros_descartados"]),
        "Reservas: PMIDs %d; oraciones %d; archivos leídos %d."
        % (r["pmids"], r["oraciones"], r["archivos"]),
        "Pares: leídos %d; reservados por PMID %d (artículos reservados "
        "presentes: %d); reservados por oración %d; sin locus %d; con un "
        "locus fuera de PAO1 %d; con el marcado roto %d."
        % (e["pares_leidos"], e["reservados_por_pmid"],
           e["pmids_reservados_presentes"], e["reservados_por_oracion"],
           e["sin_locus"], e["locus_no_pao1"], e["marcado_invalido"]),
        "Filas que pueden dar positivos: %d de %d (fuera: homología %d, "
        "BioBERT %d, d %d, signo ilegible %d, autorregulación %d, sin PMID "
        "%d); %d con alguna oración en los pares."
        % (e["filas_elegibles"], e["filas_base"], x["homologia"],
           x["biobert"], x["signo_d"], x["signo_ilegible"],
           x["autorregulacion"], x["sin_pmid"],
           e["filas_elegibles_con_oracion"]),
        "Positivos: %d pares coinciden con una fila elegible y %d solo con "
        "filas excluidas; %d claves en conflicto (%d pares); %d oraciones "
        "duplicadas; %d recortadas por el tope."
        % (e["pares_con_fila_elegible"], e["pares_solo_con_filas_excluidas"],
           e["claves_en_conflicto"], e["pares_en_conflicto"],
           e["oraciones_duplicadas"], e["recortados_por_tope"]),
        "Negativos: %d candidatos (fuera: autorregulación %d, par curado %d; "
        "duplicados %d; recortados por el tope %d); muestreados %d, de ellos "
        "%d en una oración con positivo."
        % (e["candidatos_negativos"],
           e["negativos_descartados_autorregulacion"],
           e["negativos_descartados_par_curado"], e["negativos_duplicados"],
           e["negativos_recortados_por_tope"], e["negativos_muestreados"],
           e["negativos_en_oracion_con_positivo"]),
        "Texto repetido entre artículos: %d ejemplos fuera."
        % e["repetidos_entre_pmids"],
        "Ejemplos: %d (activates %d; represses %d; regulates %d; "
        "no_relation %d)."
        % (e["ejemplos"], pe["activates"], pe["represses"], pe["regulates"],
           pe["no_relation"]),
        "  positivos por origen: %s."
        % ("; ".join("%s %d" % (_origenes_legibles(k), n)
                     for k, n in e["positivos_por_origen"].items())
           or "ninguno"),
        "  PMIDs: %d distintos, %d con positivo; los 5 con más ejemplos "
        "reúnen %d."
        % (e["pmids_distintos"], e["pmids_con_positivo"],
           e["ejemplos_en_los_5_pmids_mayores"]),
    ]
    if not r["archivos"]:
        lineas.append(
            "AVISO: sin reservas. Si con este modelo se va a recalcular el "
            "44 %, reserva antes los PMIDs de la muestra de 50 juicios.")
    elif r["pmids"] and not e["pmids_reservados_presentes"]:
        lineas.append(
            "AVISO: ninguno de los PMIDs reservados aparece en los pares; "
            "revisa que el archivo de reservas sea el que querías.")
    for etiqueta in ETIQUETAS:
        if e["ejemplos"] and not pe[etiqueta]:
            lineas.append("AVISO: la clase %s no tiene ejemplos; el modelo no "
                          "la va a aprender." % etiqueta)
    return lineas


# ------------------------------------------------------------------ ejecutar

def ejecutar(ruta_pares, ruta_base, rutas_reservas, salida, semilla=SEMILLA,
             max_por_par=MAX_POR_PAR,
             proporcion_negativos=PROPORCION_NEGATIVOS, hoja=None,
             log=lambda m: None):
    """Lee, construye y escribe los `entity_marked_*.jsonl` en `salida`.

    Devuelve los conteos: {'base': ..., 'reservas': ..., 'entrenamiento':
    ...}, solo números y categorías. Por `log` pasan las líneas de
    `resumen()` y nada más: ninguna oración, gen, locus ni PMID.

    La comprobación de la salida va antes de abrir nada: si la ruta está
    mal, la base no se llega a leer. Se escriben primero dev y test (vacíos)
    y al final train, cada uno de forma atómica, y junto a ellos
    `conteos.json` con los conteos, los parámetros y la huella de cada
    entrada, para saber después de qué salió esta carpeta.

    Lanza ValueError si la salida cae dentro de un repositorio, si una
    entrada está mal formada o si no sale ningún ejemplo.
    """
    # Antes de la guarda: con `--salida=~/...` la guarda revisaba la ruta
    # literal y los ejemplos acababan en una carpeta llamada `~`.
    salida = os.path.expanduser(salida)
    if salida.startswith("~"):
        raise ValueError("No pude expandir el ~ de --salida (¿usuario que no "
                         "existe?). Usa una ruta absoluta.")
    exigir_fuera_del_repositorio(salida)
    if isinstance(rutas_reservas, str):
        rutas_reservas = [rutas_reservas]
    # `~` llega sin expandir cuando la ruta viene de una variable definida
    # entre comillas simples (la guía usa `export BASE_CURADA='...'`), y el
    # zipfile reventaba con un traceback después de leer todos los pares.
    ruta_pares = os.path.expanduser(ruta_pares)
    ruta_base = os.path.expanduser(ruta_base)
    rutas_reservas = [os.path.expanduser(r) for r in rutas_reservas or ()]
    entradas = ([("--pares", ruta_pares), ("--base", ruta_base)]
                + [("--reservar", r) for r in rutas_reservas])
    for flag, ruta in entradas:
        if not os.path.isfile(ruta):
            # Sin la ruta en el mensaje: la de --base dice dónde vive la base.
            raise ValueError("No encuentro el archivo de %s. Usa una ruta "
                             "absoluta; entre comillas simples, ~ y $HOME no "
                             "se expanden." % flag)
    reservas, c_reservas = leer_reservas(rutas_reservas)
    pares = leer_pares(ruta_pares)
    interacciones, c_base = validacion.leer_base(ruta_base, hoja)
    ejemplos, c_entrenamiento = construir(
        pares, interacciones, reservas, semilla=semilla,
        max_por_par=max_por_par, proporcion_negativos=proporcion_negativos)
    conteos = collections.OrderedDict([
        ("base", c_base),
        ("reservas", c_reservas),
        ("entrenamiento", c_entrenamiento),
    ])
    for linea in resumen(conteos):
        log(linea)
    if not ejemplos:
        raise ValueError("No salió ningún ejemplo, así que no escribo nada. "
                         "Los conteos de arriba dicen dónde se quedaron.")

    if not os.path.isdir(salida):
        # 0o700: en el servidor, otras cuentas no entran a la carpeta.
        os.makedirs(salida, 0o700)
    for nombre in ARCHIVOS[1:]:
        _escribir_atomico(os.path.join(salida, nombre), [])
    _escribir_atomico(os.path.join(salida, ARCHIVOS[0]),
                      (json.dumps(e, ensure_ascii=False) for e in ejemplos))
    registro = collections.OrderedDict([
        ("generado_en", datetime.datetime.now(datetime.timezone.utc)
         .strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("parametros", collections.OrderedDict([
            ("semilla", semilla), ("max_por_par", max_por_par),
            ("proporcion_negativos", proporcion_negativos), ("hoja", hoja)])),
        # Solo en el archivo, no en el log: una huella hexadecimal puede
        # traer siete dígitos seguidos y pasar por un PMID a ojo.
        ("huellas", collections.OrderedDict([
            ("pares", procedencia.huella(ruta_pares)),
            ("base", procedencia.huella(ruta_base)),
            ("reservas", [procedencia.huella(r) for r in rutas_reservas])])),
        ("conteos", conteos),
    ])
    _escribir_atomico(os.path.join(salida, ARCHIVO_CONTEOS),
                      [json.dumps(registro, ensure_ascii=False, indent=2)])
    log("Escritos %d ejemplos en %s. dev y test van vacíos a propósito: "
        "pasa la carpeta por etapa2/particionar.py --por pmid antes de "
        "entrenar." % (len(ejemplos), salida))
    return conteos


# ------------------------------------------------------- para el CLI

def agregar_argumentos(parser):
    """Los argumentos del subcomando `datos-entrenamiento`."""
    parser.add_argument(
        "--pares", required=True,
        help="pares.jsonl del puente (corpus público).")
    parser.add_argument(
        "--base", required=True,
        help="Ruta del .xlsx de la base curada. Solo en el servidor; nunca "
             "se nombra en el código.")
    parser.add_argument(
        "--reservar", action="append", default=[], metavar="ARCHIVO",
        help="Archivo de reservas (pmid<TAB>número u oracion<TAB>texto). "
             "Se puede repetir.")
    parser.add_argument(
        "--salida", required=True,
        help="Carpeta de salida, fuera de todo repositorio.")
    parser.add_argument(
        "--hoja", default=None,
        help="Nombre de la hoja; por omisión, la primera del libro.")
    parser.add_argument("--semilla", type=int, default=SEMILLA)
    parser.add_argument(
        "--max-por-par", dest="max_por_par", type=int, default=MAX_POR_PAR,
        help="Oraciones por (artículo, par). Por omisión %d." % MAX_POR_PAR)
    parser.add_argument(
        "--proporcion-negativos", dest="proporcion_negativos", type=float,
        default=PROPORCION_NEGATIVOS,
        help="Negativos por cada positivo. Por omisión %.1f."
             % PROPORCION_NEGATIVOS)
    return parser


def desde_argumentos(args, log=lambda m: None):
    """`ejecutar` con lo que dejó `agregar_argumentos` en `args`."""
    return ejecutar(args.pares, args.base, args.reservar, args.salida,
                    semilla=args.semilla, max_por_par=args.max_por_par,
                    proporcion_negativos=args.proporcion_negativos,
                    hoja=args.hoja, log=log)
