"""El puente del bronce al BioBERT (punto 33 del PLAN).

Hasta el 8-oct el clasificador no leía el bronce: `etapa2/extraer_pares.py`
armaba sus pares directo del corpus y las dos ramas corrían en paralelo. Aquí
se le pasan las oraciones candidatas del bronce a la MISMA función que generó
los pares de inferencia del 27-ago (`candidatos_de_oracion`), cuyo marcado
`<e1>`/`<e2>` reproduce línea por línea el de los datos de entrenamiento, y se
clasifican con el MISMO `clasificar.py`, por subproceso. `etapa2/` no se toca.

Dos piezas:

- `pares_de_candidatas`: candidatas del bronce → pares marcados, con la guarda
  `verificar()` del contrato y columnas para volver a la oración del bronce.
- `clasificar_pares`: predicciones para esos pares. Lo ya clasificado con el
  mismo checkpoint (mismos pesos, tokenizador y `config.json`, mismo
  `id2label`, mismo `max_length`; ver `firma_del_modelo`) se reutiliza por
  texto marcado idéntico: la predicción solo depende del modelo, del texto y
  del `max_length`. El 8-oct eso era el 81.8 % de los pares; el resto lo
  clasifica `clasificar.py`.

Reconocer genes por diccionario produce falsos positivos y no sustituye al
reconocimiento de entidades: los pares son candidatos, no relaciones.
"""

import collections
import csv
import io
import json
import os
import re
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ETAPA2 = os.path.join(_RAIZ, "etapa2")
for _p in (_RAIZ, _ETAPA2):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import clasificar as _clasificar        # noqa: E402  (no importa torch al cargar)
import extraer_pares as _extraer        # noqa: E402
from grn_comun import procedencia       # noqa: E402
from grn_comun.archivos import borrar, reemplazar   # noqa: E402

LOCUS = re.compile(r"^PA\d{4}")
MAX_MENCIONES = 8
# La caché propia de cada carpeta, por texto marcado y atada a la firma del
# modelo. No se reutiliza la carpeta uniendo su `pares.jsonl` con su
# `predicciones.jsonl` por `id_par`: `pares.jsonl` se reescribe en cada
# corrida, y si un diccionario nuevo cambiara el marcado de un mismo `id_par`,
# la predicción vieja quedaría pegada a un texto que el modelo no vio.
CACHE = "cache_predicciones.jsonl"
CACHE_META = "cache_predicciones_meta.json"
TOLERANCIA_SUMA = 1e-3
TOLERANCIA_ARGMAX = 1e-6
MAX_LENGTH = 512
# Lo que decide qué predice un checkpoint además de su config.json. El
# config.json de un BERT afinado no depende de los pesos: dos
# reentrenamientos con la receta del run 22 lo escriben idéntico byte a byte,
# y con solo él la caché le pegaba al modelo nuevo las predicciones del viejo.
PESOS = ("model.safetensors", "pytorch_model.bin")
TOKENIZADOR = ("tokenizer.json", "tokenizer_config.json", "vocab.txt",
               "special_tokens_map.json")
# Lo que la clasificación deja a medias en la carpeta y se borra al unir.
PENDIENTES = "pares_pendientes.jsonl"
PENDIENTES_FIRMA = "pares_pendientes_firma.json"
NUEVAS = "predicciones_nuevas.jsonl"
NUEVAS_META = "predicciones_nuevas_meta.json"

# El bronce dice `xml`/`abstract`; el contrato de los pares del 27-ago dice
# `fulltext`/`resumen`. Se usa el del contrato en `fuente` para que los
# informes de `red.py` sean comparables, y el del bronce va en `fuente_texto`.
FUENTE_CONTRATO = {"xml": "fulltext", "abstract": "resumen"}

COLUMNAS_PREDICCION = list(_clasificar.CLAVES_SALIDA)
ETIQUETAS = list(_clasificar.ETIQUETAS_ESPERADAS)


class ErrorPuente(RuntimeError):
    pass


def _nada(_m):
    pass


# ------------------------------------------------------------- lectura

def leer_candidatas(ruta):
    """Las filas del CSV de candidatas que vuelca `grn_bronce.cli exportar`.

    El encabezado del CSV son los identificadores del contrato (`pmid`,
    `oracion`...): los encabezados con acento son solo los del .xlsx.
    """
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def leer_jsonl(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def escribir_json(ruta, objeto):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    reemplazar(tmp, ruta)


def escribir_jsonl(ruta, filas):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False))
            f.write("\n")
    reemplazar(tmp, ruta)


# ------------------------------------------------------------- pares

def locus_de(id_canonico, locus, catalogo):
    """Los locus tags de una entidad del léxico, como lista.

    Un gen da uno (su símbolo o su propio locus). Un operón del catálogo da
    sus genes, solo por tabla: un operón sintético que el texto abrevia
    (`exoSTY`) no se expande, por la misma regla que `grn_bronce.operones`. Lo
    que no se resuelve da `[]`, no se adivina.
    """
    if not id_canonico:
        return []
    if LOCUS.match(id_canonico):
        return [id_canonico]
    for forma in (id_canonico, id_canonico[:1].lower() + id_canonico[1:],
                  id_canonico[:1].upper() + id_canonico[1:]):
        if forma in locus:
            return [locus[forma]]
    if catalogo is not None and catalogo.tiene(id_canonico):
        return catalogo.locus_tags(id_canonico)
    return []


def par_del_bronce(tf_id, target_id, regulador, blanco):
    """Cómo se relaciona este par con el que orientó el bronce."""
    if not regulador or not blanco:
        return "sin_par"
    if (tf_id, target_id) == (regulador, blanco):
        return "directo"
    if (tf_id, target_id) == (blanco, regulador):
        return "inverso"
    return "otro"


def pares_de_candidatas(filas, lex, locus, catalogo=None,
                        max_menciones=MAX_MENCIONES, limite=None, log=_nada):
    """Los pares marcados de las candidatas del bronce, con su informe.

    Devuelve `(candidatos, informe)`; `candidatos` son tuplas `(fila,
    pretokenizado)`, el formato de `extraer_pares`, para pasar por su
    `verificar()` sin reescribirlo.

    No se aplica `topar_por_par` (máximo de oraciones por par): esa es una
    guarda de la corrida sobre el corpus entero, y el tope lo vuelve a poner
    `red.py` después de deduplicar. Tampoco las invariantes de escala, que no
    aplican a una prueba con `--limite`.
    """
    cuenta = collections.Counter()
    candidatos = []
    por_seccion = collections.Counter()
    por_fuente = collections.Counter()
    relacion_bronce = collections.Counter()
    oraciones_con_par = 0
    n = 0
    for c in filas:
        if limite is not None and n >= limite:
            break
        n += 1
        oracion = c["oracion"]
        fuente_texto = c.get("fuente_texto", "")
        num = int(c["num_oracion"])
        res = _extraer.candidatos_de_oracion(
            c["pmid"], c["seccion"], FUENTE_CONTRATO.get(fuente_texto,
                                                         fuente_texto),
            num, oracion, lex, max_menciones, cuenta)
        if not res:
            continue
        oraciones_con_par += 1
        # Los ids canónicos de las dos ocurrencias marcadas, por su posición.
        # Las formas `tf`/`target` (MexT/mexT) son de presentación y no
        # sirven para cruzar con el bronce ni con la base curada.
        por_posicion = dict((m[0], m[3]) for m in lex.menciones(oracion))
        for fila, pretok in res:
            tf_id = por_posicion.get(fila["pos_tf"], "")
            target_id = por_posicion.get(fila["pos_target"], "")
            regulador = c.get("regulador_candidato", "") or ""
            blanco = c.get("blanco_candidato", "") or ""
            relacion = par_del_bronce(tf_id, target_id, regulador, blanco)
            fila.update({
                "corrida_bronce": int(c["corrida_id"]) if c.get("corrida_id")
                else None,
                "fuente_texto": fuente_texto,
                "num_oracion": num,
                "tf_id": tf_id,
                "target_id": target_id,
                "tf_locus": locus_de(tf_id, locus, catalogo),
                "target_locus": locus_de(target_id, locus, catalogo),
                "par_del_bronce": relacion,
                "regulador_candidato": regulador,
                "blanco_candidato": blanco,
            })
            candidatos.append((fila, pretok))
            por_seccion[fila["seccion"]] += 1
            por_fuente[fuente_texto] += 1
            relacion_bronce[relacion] += 1
        if n % 5000 == 0:
            log("  %d oraciones, %d pares" % (n, len(candidatos)))

    problema = _extraer.verificar(candidatos)
    if problema:
        raise ErrorPuente("La guarda del contrato de pares falló: %s"
                          % problema)
    informe = {
        "oraciones_leidas": n,
        "oraciones_con_par": oraciones_con_par,
        "pares": len(candidatos),
        "pares_por_seccion": dict(por_seccion),
        "pares_por_fuente": dict(por_fuente),
        "relacion_con_el_par_del_bronce": dict(relacion_bronce),
        "autorregulacion": sum(1 for f, _ in candidatos
                               if f["autorregulacion"]),
        "sin_locus_tf": sum(1 for f, _ in candidatos if not f["tf_locus"]),
        "sin_locus_blanco": sum(1 for f, _ in candidatos
                                if not f["target_locus"]),
        "descartes_de_extraer_pares": dict(cuenta),
    }
    return candidatos, informe


def construir_pares(ruta_candidatas, carpeta, limite=None, log=_nada):
    """Lee el CSV del bronce, arma los pares y escribe `pares.jsonl`."""
    from grn_bronce import identificar, operones
    log("Leyendo las candidatas del bronce...")
    filas = leer_candidatas(ruta_candidatas)
    log("  %d oraciones candidatas" % len(filas))
    lex = identificar.cargar_lexico()
    locus = identificar.cargar_locus_tags()
    catalogo = operones.Catalogo.cargar(operones.RUTA_POR_OMISION)
    candidatos, informe = pares_de_candidatas(filas, lex, locus, catalogo,
                                              limite=limite, log=log)
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "pares.jsonl")
    escribir_jsonl(ruta, [fila for fila, _ in candidatos])
    informe["huellas"] = {
        "candidatas": procedencia.huella(ruta_candidatas),
        "pares": procedencia.huella(ruta),
        "genes_pao1.tsv": procedencia.huella_texto(
            os.path.join(_RAIZ, "grn_bronce", "recursos", "genes_pao1.tsv")),
    }
    informe["limite"] = limite
    escribir_json(os.path.join(carpeta, "pares_informe.json"), informe)
    log("  %d pares en %d oraciones -> %s" % (
        informe["pares"], informe["oraciones_con_par"], ruta))
    return informe


# ------------------------------------------------------------- clasificar

def etiquetas_del_modelo(modelo):
    """El orden de los logits del checkpoint, de su `label_mapping.json`."""
    ruta = os.path.join(modelo, "label_mapping.json")
    with io.open(ruta, encoding="utf-8") as f:
        etiquetas = _clasificar.normalizar_etiquetas(json.load(f))
    if not etiquetas or sorted(etiquetas) != sorted(ETIQUETAS):
        raise ErrorPuente("label_mapping.json de %s no trae las cuatro "
                          "etiquetas esperadas" % modelo)
    return etiquetas


def archivos_del_modelo(modelo):
    """Los archivos de pesos y de tokenizador del checkpoint que existen.

    Lanza ErrorPuente si no hay pesos: un checkpoint sin ellos no puede haber
    producido ninguna predicción.
    """
    pesos = [n for n in PESOS if os.path.isfile(os.path.join(modelo, n))]
    if not pesos:
        raise ErrorPuente("%s no trae pesos (%s)" % (modelo, " ni ".join(PESOS)))
    return [os.path.join(modelo, n) for n in pesos[:1] + [
        t for t in TOKENIZADOR if os.path.isfile(os.path.join(modelo, t))]]


def firma_del_modelo(modelo):
    """Lo que tiene que coincidir para reutilizar una predicción."""
    etiquetas = etiquetas_del_modelo(modelo)
    return {"sha1_config": _clasificar.sha1_de(os.path.join(modelo,
                                                           "config.json")),
            "huellas_modelo": dict(
                (os.path.basename(r), procedencia.huella(r))
                for r in archivos_del_modelo(modelo)),
            "id2label": dict((str(i), e) for i, e in enumerate(etiquetas)),
            "max_length": MAX_LENGTH}


def _meta_compatible(meta, firma):
    """Todo lo de la firma tiene que coincidir. Un meta anterior al 9-oct no
    trae `huellas_modelo` y no es compatible: no hay cómo saber de qué pesos
    salió."""
    return all(meta.get(k) == v for k, v in firma.items())


def _meta_de_clasificar_compatible(meta, firma, modelo):
    """El meta que escribe `clasificar.py` no sabe de huellas de pesos: se
    exige lo que sí trae, y que sea el mismo checkpoint por ruta. Lo que pasa
    por aquí es lo que se acaba de clasificar con ese mismo modelo."""
    return (meta.get("sha1_config") == firma["sha1_config"]
            and meta.get("id2label") == firma["id2label"]
            and meta.get("max_length") == firma["max_length"]
            and os.path.normcase(os.path.abspath(meta.get("modelo") or ""))
            == os.path.normcase(os.path.abspath(modelo)))


def indice_reutilizable(carpetas, firma, log=_nada):
    """{texto marcado: predicción} de las carpetas con el mismo modelo.

    Una carpeta entra solo si su meta coincide con la firma del modelo
    (`_meta_compatible`) y si su `pares.jsonl` es el que se clasificó; si no,
    se dice por qué se descarta. Lo segundo importa porque aquí la unión
    entre pares y predicciones es por `id_par`, que no depende del texto
    marcado: un `pares.jsonl` rehecho junto a unas predicciones viejas le
    pegaría a un texto nuevo la predicción de otro. Las probabilidades se
    toman tal como se escribieron, y la clase predicha también: recalcular el
    argmax sobre valores redondeados a 6 decimales podría voltear un empate.
    """
    indice = {}
    fuentes = []
    for carpeta in carpetas:
        meta_ruta = os.path.join(carpeta, "predicciones_meta.json")
        pares_ruta = os.path.join(carpeta, "pares.jsonl")
        pred_ruta = os.path.join(carpeta, "predicciones.jsonl")
        if not all(os.path.isfile(r) for r in (meta_ruta, pares_ruta,
                                               pred_ruta)):
            continue
        with io.open(meta_ruta, encoding="utf-8") as f:
            meta = json.load(f)
        if not _meta_compatible(meta, firma):
            log("  no se reutiliza %s: otro modelo, otras etiquetas, otro "
                "max_length, o un meta sin la huella de los pesos" % carpeta)
            continue
        esperada = meta.get("huella_pares")
        if esperada is not None and esperada != procedencia.huella(pares_ruta):
            log("  no se reutiliza %s: su pares.jsonl no es el que se "
                "clasificó" % carpeta)
            continue
        texto_de = {}
        with io.open(pares_ruta, encoding="utf-8") as f:
            for linea in f:
                if linea.strip():
                    d = json.loads(linea)
                    texto_de[d["id_par"]] = d["text"]
        if esperada is None and meta.get("n_entrada") != len(texto_de):
            # El meta de clasificar.py no guarda la huella de su entrada; el
            # conteo es lo único con qué atrapar un pares.jsonl rehecho.
            log("  no se reutiliza %s: su meta dice %s pares y pares.jsonl "
                "trae %d" % (carpeta, meta.get("n_entrada"), len(texto_de)))
            continue
        antes = len(indice)
        with io.open(pred_ruta, encoding="utf-8") as f:
            for linea in f:
                if not linea.strip():
                    continue
                p = json.loads(linea)
                texto = texto_de.get(p["id_par"])
                if texto is not None and texto not in indice:
                    indice[texto] = {"prediccion": p["prediccion"],
                                     "p": dict(("p_" + e, p["p_" + e])
                                               for e in ETIQUETAS)}
        fuentes.append({"carpeta": carpeta, "textos": len(indice) - antes,
                        "huella_predicciones": procedencia.huella(pred_ruta),
                        "transformers": meta.get("transformers"),
                        "torch": meta.get("torch"),
                        "do_lower_case": meta.get("do_lower_case")})
        log("  reutilizables de %s: %d" % (carpeta, len(indice) - antes))
    return indice, fuentes


def cargar_cache(carpeta, firma, indice, log=_nada):
    """Suma al índice la caché propia de la carpeta, si es del mismo modelo.

    Devuelve cuántos textos aportó, o None si no había caché compatible.
    """
    meta_ruta = os.path.join(carpeta, CACHE_META)
    ruta = os.path.join(carpeta, CACHE)
    if not (os.path.isfile(meta_ruta) and os.path.isfile(ruta)):
        return None
    with io.open(meta_ruta, encoding="utf-8") as f:
        if not _meta_compatible(json.load(f), firma):
            log("  la caché de la carpeta es de otro modelo; no se usa")
            return None
    antes = len(indice)
    with io.open(ruta, encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                d = json.loads(linea)
                indice.setdefault(d["text"], {
                    "prediccion": d["prediccion"],
                    "p": dict(("p_" + e, d["p_" + e]) for e in ETIQUETAS)})
    return len(indice) - antes


def guardar_cache(carpeta, firma, indice):
    """Toda predicción conocida de esta carpeta, por texto marcado."""
    filas = []
    for texto in sorted(indice):
        d = collections.OrderedDict([("text", texto),
                                     ("prediccion",
                                      indice[texto]["prediccion"])])
        for e in ETIQUETAS:
            d["p_" + e] = indice[texto]["p"]["p_" + e]
        filas.append(d)
    escribir_jsonl(os.path.join(carpeta, CACHE), filas)
    escribir_json(os.path.join(carpeta, CACHE_META), dict(firma))


def fila_prediccion(par, prediccion):
    """Una línea de predicciones.jsonl con las claves y el orden de
    `clasificar.CLAVES_SALIDA`. `seccion`, `fuente` y `redaccion` salen del
    par nuevo, no del archivo de donde se reutilizó la predicción."""
    d = collections.OrderedDict()
    d["id_par"] = par["id_par"]
    d["pmid"] = int(par["pmid"])
    d["tf"] = par["tf"]
    d["target"] = par["target"]
    d["prediccion"] = prediccion["prediccion"]
    for e in ETIQUETAS:
        d["p_" + e] = prediccion["p"]["p_" + e]
    d["seccion"] = par.get("seccion", "")
    d["fuente"] = par.get("fuente", "")
    d["autorregulacion"] = bool(par.get("autorregulacion", False))
    d["redaccion"] = par.get("redaccion", "")
    return d


def verificar_predicciones(pares, predicciones):
    """Mismo conteo, mismos `id_par`, probabilidades que suman 1 y clase
    predicha que es el argmax. Devuelve un mensaje o None."""
    if len(pares) != len(predicciones):
        return "hay %d pares y %d predicciones" % (len(pares),
                                                   len(predicciones))
    if [p["id_par"] for p in pares] != [p["id_par"] for p in predicciones]:
        return "los id_par no coinciden con los de pares.jsonl"
    for i, p in enumerate(predicciones, 1):
        probs = [p["p_" + e] for e in ETIQUETAS]
        if abs(sum(probs) - 1.0) > TOLERANCIA_SUMA:
            return "fila %d: las probabilidades no suman 1" % i
        if p["p_" + p["prediccion"]] < max(probs) - TOLERANCIA_ARGMAX:
            return "fila %d: la clase predicha no es el argmax" % i
    return None


def _borrar(*rutas):
    """Los intermedios. Si el tablero tiene uno abierto y no se deja borrar ni
    después de reintentar, se queda: la firma de los pendientes descarta lo
    que no sea de este modelo y esta lista, así que no hace daño, y tumbar el
    paso después de escribir bien las predicciones sí lo haría."""
    for ruta in rutas:
        try:
            borrar(ruta)
        except OSError:
            pass


def clasificar_pares(carpeta, modelo, python=None, reusar_de=(),
                     log=_nada, detener=None, usar_cache=True, firma=None):
    """Escribe `predicciones.jsonl` y su meta para los pares de la carpeta.

    Devuelve un resumen con cuántas se reutilizaron y cuántas se
    clasificaron. Si ya hay predicciones para esta misma huella de pares y
    este mismo modelo, no hace nada. Con `usar_cache=False` se clasifica todo
    de nuevo: ni esas predicciones, ni la caché de la carpeta, ni otras
    carpetas, ni un `predicciones_nuevas.jsonl` a medias. `firma` evita
    volver a huellear los pesos si quien llama ya la tiene.
    """
    from grn_comun import proceso
    pares_ruta = os.path.join(carpeta, "pares.jsonl")
    pred_ruta = os.path.join(carpeta, "predicciones.jsonl")
    meta_ruta = os.path.join(carpeta, "predicciones_meta.json")
    pend_ruta = os.path.join(carpeta, PENDIENTES)
    pend_firma_ruta = os.path.join(carpeta, PENDIENTES_FIRMA)
    nuevas_ruta = os.path.join(carpeta, NUEVAS)
    nuevas_meta_ruta = os.path.join(carpeta, NUEVAS_META)
    firma = firma or firma_del_modelo(modelo)
    huella_pares = procedencia.huella(pares_ruta)

    if usar_cache and os.path.isfile(pred_ruta) and os.path.isfile(meta_ruta):
        with io.open(meta_ruta, encoding="utf-8") as f:
            meta = json.load(f)
        if (_meta_compatible(meta, firma)
                and meta.get("huella_pares") == huella_pares
                and meta.get("huella_predicciones")
                == procedencia.huella(pred_ruta)):
            log("Las predicciones ya están hechas para estos pares y este "
                "modelo.")
            return {"hecho": False, "reutilizadas": meta["reutilizadas"]["n"],
                    "nuevas": meta["nuevas"]["n"]}

    pares = leer_jsonl(pares_ruta)
    if usar_cache:
        log("Pares: %d. Buscando predicciones reutilizables del mismo "
            "modelo..." % len(pares))
        externas = [d for d in reusar_de
                    if os.path.abspath(d) != os.path.abspath(carpeta)]
        indice, fuentes = indice_reutilizable(externas, firma, log)
        propias = cargar_cache(carpeta, firma, indice, log)
    else:
        log("Pares: %d. Se clasifican todos de nuevo (sin caché)." % len(pares))
        indice, fuentes, propias = {}, [], None
        _borrar(nuevas_ruta, nuevas_ruta + ".parcial", nuevas_meta_ruta)
    if propias:
        log("  reutilizables de la caché de esta carpeta: %d" % propias)
        fuentes.append({"carpeta": carpeta, "textos": propias,
                        "huella_predicciones": procedencia.huella(
                            os.path.join(carpeta, CACHE))})
    pendientes = [p for p in pares if p["text"] not in indice]
    reutilizadas = len(pares) - len(pendientes)
    log("  reutilizadas: %d   por clasificar: %d" % (reutilizadas,
                                                     len(pendientes)))

    nuevas_meta = None
    segundos_nuevas = 0.0
    nuevas_ids = []
    if pendientes:
        claves = ("text", "label", "pmid", "tf", "target", "id_par",
                  "seccion", "fuente", "autorregulacion", "redaccion")
        tmp = pend_ruta + ".nuevo"
        escribir_jsonl(tmp, [dict((k, p.get(k)) for k in claves)
                             for p in pendientes])
        # `clasificar.py --reanudar` adopta lo que encuentre a medias. Se
        # conserva solo si es de esta misma lista de pendientes Y de este
        # mismo modelo: con la misma lista, un modelo B adoptaba completo el
        # archivo del modelo A, «clasificaba» 0 pares y lo firmaba como suyo.
        lanzada = {"modelo": os.path.abspath(modelo), "firma": firma}
        previa = None
        if os.path.isfile(pend_firma_ruta):
            with io.open(pend_firma_ruta, encoding="utf-8") as f:
                previa = json.load(f)
        if (procedencia.huella(tmp) != procedencia.huella(pend_ruta)
                or previa != lanzada):
            _borrar(nuevas_ruta, nuevas_ruta + ".parcial", nuevas_meta_ruta)
        reemplazar(tmp, pend_ruta)
        escribir_json(pend_firma_ruta, lanzada)
        inicio = time.monotonic()
        proceso.correr(
            [python or sys.executable, "-u",
             os.path.join(_ETAPA2, "clasificar.py"),
             "--modelo", modelo, "--entrada", pend_ruta,
             "--salida", nuevas_ruta, "--meta", nuevas_meta_ruta,
             "--reanudar"],
            log=log, detener=detener, cwd=_RAIZ,
            # Sin barras de progreso: cada refresco llega como una línea y
            # llenaba la bitácora del tablero (400 líneas) de «Loading
            # weights». El avance real lo imprime clasificar.py cada --avance.
            entorno={"TQDM_DISABLE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1",
                     "TRANSFORMERS_VERBOSITY": "error"},
            # En el grupo de este proceso y no en uno propio: en Linux, el
            # killpg con que el flujo cancela este paso no alcanzaba a un
            # nieto en otra sesión, y clasificar.py seguía con la GPU.
            nueva_sesion=False)
        segundos_nuevas = round(time.monotonic() - inicio, 1)
        with io.open(nuevas_meta_ruta, encoding="utf-8") as f:
            nuevas_meta = json.load(f)
        if not _meta_de_clasificar_compatible(nuevas_meta, firma, modelo):
            raise ErrorPuente("clasificar.py usó otro modelo o otro orden de "
                              "etiquetas que el pedido")
        texto_de = dict((p["id_par"], p["text"]) for p in pendientes)
        for p in leer_jsonl(nuevas_ruta):
            indice[texto_de[p["id_par"]]] = {
                "prediccion": p["prediccion"],
                "p": dict(("p_" + e, p["p_" + e]) for e in ETIQUETAS)}
            nuevas_ids.append(p["id_par"])

    predicciones = [fila_prediccion(p, indice[p["text"]]) for p in pares]
    problema = verificar_predicciones(pares, predicciones)
    if problema:
        raise ErrorPuente("Las predicciones unidas no pasan la guarda: %s"
                          % problema)
    escribir_jsonl(pred_ruta, predicciones)
    guardar_cache(carpeta, firma,
                  dict((p["text"], indice[p["text"]]) for p in pares))
    reparto = collections.Counter(p["prediccion"] for p in predicciones)
    base = nuevas_meta or (fuentes[0] if fuentes else {})
    meta = {
        "modelo": os.path.abspath(modelo),
        "sha1_config": firma["sha1_config"],
        "huellas_modelo": firma["huellas_modelo"],
        "etiquetas_de": os.path.abspath(os.path.join(modelo,
                                                     "label_mapping.json")),
        "id2label": firma["id2label"],
        "max_length": firma["max_length"],
        "do_lower_case": base.get("do_lower_case"),
        "transformers": base.get("transformers"),
        "torch": base.get("torch"),
        "dispositivo": (nuevas_meta or {}).get("dispositivo"),
        "exactitud_control": None,
        "n_entrada": len(pares),
        "n_salida": len(predicciones),
        "reparto": dict(reparto),
        "reutilizadas": {"n": reutilizadas, "fuentes": fuentes},
        "nuevas": {"n": len(pendientes), "segundos": segundos_nuevas},
        "huella_pares": huella_pares,
        "huella_predicciones": procedencia.huella(pred_ruta),
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    escribir_json(meta_ruta, meta)
    # Lo nuevo ya está en predicciones.jsonl y en la caché. Dejar los
    # archivos intermedios era dejarle a la siguiente corrida un
    # `predicciones_nuevas.jsonl` que `--reanudar` adoptaría.
    _borrar(pend_ruta, pend_firma_ruta, nuevas_ruta, nuevas_ruta + ".parcial",
            nuevas_meta_ruta)
    if nuevas_ids:
        escribir_json(os.path.join(carpeta, "predicciones_origen.json"),
                      {"nuevas": sorted(nuevas_ids)})
    elif os.path.exists(os.path.join(carpeta, "predicciones_origen.json")):
        borrar(os.path.join(carpeta, "predicciones_origen.json"))
    log("Predicciones: %d (%s)" % (len(predicciones), ", ".join(
        "%s %d" % (e, reparto.get(e, 0)) for e in ETIQUETAS)))
    return {"hecho": True, "reutilizadas": reutilizadas,
            "nuevas": len(pendientes), "segundos_nuevas": segundos_nuevas,
            "reparto": dict(reparto)}
