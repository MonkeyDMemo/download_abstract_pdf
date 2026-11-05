"""El jurado: varias anotaciones de Ouroboros sobre la misma hoja votan cada
ítem, y el veredicto sale por votos con un umbral.

    python -m grn_verificacion.cli jurado --modelo A.csv --modelo B.csv \\
        --modelo C.csv --umbral K --salida salidas/ouroboros/jurado_X
    python -m grn_verificacion.cli jurado-barrido --modelo A.csv \\
        --modelo B.csv --modelo C.csv --experto E.csv --llave L.csv \\
        [--retencion-minima 0.80] [--json J]

Para qué
========
Un solo modelo como filtro de los pares del bronce es preciso o retiene, no
las dos cosas: el agente local retiene mucho y acepta de más; Qwen3-235B en
Bedrock es más estricto y deja fuera a una de cada tres verdaderas. El jurado
junta modelos que se equivocan distinto (otra familia, otro prompt, con o sin
contexto) y sube o baja la exigencia con un solo número: cuántos tienen que
decir `si`.

La regla de agregación, fija y sin mirar la oración
===================================================
Cada jurado es un `anotaciones.csv` con las columnas de la hoja; un ítem con
`relacion` vacía es su abstención y no vota. Con n jurados y umbral k:

1. **Relación.** Si al menos k jurados dicen `si` (con cualquier dirección),
   el jurado dice `si`. La abstención cuenta como no haber dicho `si`.
2. **Dirección, la mayoritaria entre los que dijeron `si`.** Así el jurado
   puede reorientar la arista del bronce: si la mayoría lee la flecha al
   revés, el veredicto va al revés. Con empate entre `1>2` y `2>1` no hay
   flecha que dar, y el ítem queda `dudoso` (con la dirección del primer
   jurado de la lista que dijo `si`, porque `dudoso` la exige) y el
   comentario lo dice.
3. **Bajo el umbral se rechaza.** El ítem va `dudoso` solo si, entre los que
   no dijeron `si`, hubo más `dudoso` que `no`; si no, va `no`. Si todos se
   abstuvieron, el jurado se abstiene.
4. **Los demás campos**, por mayoría entre los jurados que respaldan el
   veredicto (los del `si` con la dirección ganadora, los del `dudoso` con su
   dirección, o los del `no`), y en empate el valor neutro: signo `?`, tipo
   `no_se`, negada y especulativa `no`. Con `si`, negada va siempre `no`,
   como pide la rúbrica. El comentario lleva la cuenta de los votos.

El umbral no se elige aquí: se elige con `jurado-barrido` en la tanda 1, que
es de desarrollo, y se fija antes de medir la tanda 2 (una enmienda del
protocolo). Elegirlo mirando la tanda 2 haría que su cifra midiera la
elección y no al jurado.

Las dos métricas del barrido
============================
Para cada k de 1 a n, y para cada jurado solo como referencia:

- **Filtro con la dirección del bronce**, la de `concordancia` (la misma
  función, así que las cifras casan): acepta el ítem si el jurado dice `si`
  con la dirección del bronce; es verdadero si el experto dijo `si` con esa
  dirección. Precisión, retención de los verdaderos e IC.
- **Filtro con reorientación**: acepta si el jurado dice `si` con cualquier
  dirección, y es correcto si el experto dijo `si` con esa misma dirección.
  La retención es sobre todos los ítems donde el experto dijo `si`, con la
  dirección que sea. Mide la red que sale de reorientar las aristas.

Con `--retencion-minima` se marca, para cada métrica, el k de mayor precisión
entre los que retienen al menos eso.

Lo que sale
===========
`jurado` escribe en su carpeta `anotaciones.csv`, con las columnas de la hoja
(lo leen `concordancia`, `precision-ciega` y el paso `juez` del flujo como el
de cualquier corrida), y `jurado.json`, con la regla, los jurados (nombre y
huella) y conteos. La carpeta nunca cae dentro de `salidas/revision`, la del
experto. `jurado-barrido` solo da conteos, en la terminal y en el JSON:
ninguna oración, ningún `id_item`.

Biblioteca estándar y Python 3.8. No imprime: reporta por `log`.
"""

import collections
import csv
import io
import json
import os
import re
import shutil
import tempfile

from grn_bronce.texto import normalizar_espacios
from grn_comun import archivos, procedencia
from grn_verificacion import concordancia, evaluar, precision_ciega
from grn_verificacion.muestra import COLUMNAS_HOJA

METODO = "jurado"
VERSION = 1
ANOTACIONES = "anotaciones.csv"
INFORME = "jurado.json"
DIRECCIONES = ("1>2", "2>1")
CAMPOS = ("relacion", "direccion", "signo", "tipo", "negada", "especulativa")
COLUMNAS_ITEM = COLUMNAS_HOJA[:4]
# El valor de un campo cuando los que respaldan el veredicto empatan.
NEUTRO = {"signo": "?", "tipo": "no_se", "negada": "no",
          "especulativa": "no"}
CARPETA_DEL_EXPERTO = ("salidas", "revision")
REGLA = ("si con al menos k votos de si; la dirección, la mayoritaria entre "
         "los si (empate: dudoso); bajo el umbral, dudoso solo si hubo más "
         "dudoso que no entre los demás; los otros campos por mayoría de "
         "quienes respaldan el veredicto")

_LINEA = re.compile(r"línea (\d+)")


def _nada(_mensaje):
    pass


class ErrorJurado(ValueError):
    """Las anotaciones no son de la misma hoja, o la salida no sirve."""


# ------------------------------------------------------------------ lectura

def _leer(ruta, quien):
    """`precision_ciega.leer_anotacion`, con el error reducido a los números
    de línea: su mensaje trae el valor, que es un juicio."""
    try:
        return precision_ciega.leer_anotacion(ruta)
    except ValueError as e:
        lineas = sorted(set(int(n) for n in _LINEA.findall(str(e))))
        raise ErrorJurado("La anotación %s no sigue la rúbrica (§6)%s." % (
            quien, " en las líneas %s" % ", ".join(str(n) for n in lineas)
            if lineas else "")) from None


def _item(fila):
    return dict((c, fila.get(c) or "") for c in COLUMNAS_ITEM)


def _misma(fila_a, fila_b):
    return all(normalizar_espacios(fila_a.get(c) or "")
               == normalizar_espacios(fila_b.get(c) or "")
               for c in ("oracion", "entidad_1", "entidad_2"))


def leer_jurados(rutas):
    """[{id_item: fila}] de cada jurado, en el orden dado, y la lista de
    ítems en el orden del primero. Todos tienen que ser de la misma hoja:
    los mismos ítems con la misma oración y las mismas entidades. El error
    da conteos, nunca el texto."""
    if len(rutas) < 2:
        raise ErrorJurado("Un jurado necesita al menos dos anotaciones.")
    jurados = [_leer(r, "del jurado %d" % (i + 1)) for i, r in
               enumerate(rutas)]
    primero = jurados[0]
    orden = list(primero)
    for i, otro in enumerate(jurados[1:], 2):
        faltan = sum(1 for id_item in orden if id_item not in otro)
        sobran = sum(1 for id_item in otro if id_item not in primero)
        distintas = sum(1 for id_item in orden if id_item in otro
                        and not _misma(primero[id_item], otro[id_item]))
        if faltan or sobran or distintas:
            raise ErrorJurado(
                "El jurado %d no es de la misma hoja que el 1: %d ítems de "
                "menos, %d de más y %d con otra oración u otras entidades."
                % (i, faltan, sobran, distintas))
    items = [_item(primero[id_item]) for id_item in orden]
    return jurados, items


# ---------------------------------------------------------------- los votos

def _valores(fila):
    return dict((c, (fila.get(c) or "").strip()) for c in CAMPOS)


def _mayoria(valores, neutro):
    """El valor más votado, o `neutro` si hay empate en la cima o no hay
    votos."""
    conteo = collections.Counter(v for v in valores if v)
    if not conteo:
        return neutro
    (primero, n1), = conteo.most_common(1)
    if sum(1 for n in conteo.values() if n == n1) > 1:
        return neutro
    return primero


def _campos_de(votos, relacion):
    salida = {}
    for campo in ("signo", "tipo", "negada", "especulativa"):
        salida[campo] = _mayoria([v[campo] for v in votos], NEUTRO[campo])
    if relacion == "si":
        salida["negada"] = "no"
    if relacion == "no":
        salida["signo"] = salida["tipo"] = ""
    return salida


def votar(votos, umbral):
    """El veredicto del jurado para un ítem. `votos` son los valores de cada
    jurado en el orden de la lista; devuelve los campos de la hoja (vacíos si
    todos se abstuvieron) y la cuenta."""
    validos = [v for v in votos if v["relacion"]]
    cuenta = collections.Counter(v["relacion"] for v in validos)
    cuenta["abstencion"] = len(votos) - len(validos)
    comentario = ("jurado %d de %d: si %d, no %d, dudoso %d, abstenciones %d"
                  % (umbral, len(votos), cuenta["si"], cuenta["no"],
                     cuenta["dudoso"], cuenta["abstencion"]))
    vacio = dict.fromkeys(CAMPOS + ("comentario",), "")
    if not validos:
        return vacio, cuenta
    del_si = [v for v in validos if v["relacion"] == "si"
              and v["direccion"] in DIRECCIONES]
    if len(del_si) >= umbral:
        por_dir = collections.Counter(v["direccion"] for v in del_si)
        if por_dir["1>2"] == por_dir["2>1"]:
            direccion = del_si[0]["direccion"]
            respaldo = [v for v in del_si if v["direccion"] == direccion]
            fila = dict(vacio, relacion="dudoso", direccion=direccion,
                        comentario=comentario + "; empate en la dirección")
            fila.update(_campos_de(respaldo, "dudoso"))
            return fila, cuenta
        direccion = "1>2" if por_dir["1>2"] > por_dir["2>1"] else "2>1"
        respaldo = [v for v in del_si if v["direccion"] == direccion]
        fila = dict(vacio, relacion="si", direccion=direccion,
                    comentario=comentario)
        fila.update(_campos_de(respaldo, "si"))
        return fila, cuenta
    del_dudoso = [v for v in validos if v["relacion"] == "dudoso"
                  and v["direccion"] in DIRECCIONES]
    del_no = [v for v in validos if v["relacion"] == "no"]
    if len(del_dudoso) > len(del_no):
        direccion = _mayoria([v["direccion"] for v in del_dudoso],
                             del_dudoso[0]["direccion"])
        respaldo = [v for v in del_dudoso if v["direccion"] == direccion]
        fila = dict(vacio, relacion="dudoso", direccion=direccion,
                    comentario=comentario)
        fila.update(_campos_de(respaldo, "dudoso"))
        return fila, cuenta
    fila = dict(vacio, relacion="no", direccion="ninguna",
                comentario=comentario)
    fila.update(_campos_de(del_no, "no"))
    return fila, cuenta


def agregar(jurados, items, umbral):
    """[fila de la hoja] del jurado con umbral k, en el orden de la hoja."""
    n = len(jurados)
    if (isinstance(umbral, bool) or not isinstance(umbral, int)
            or not 1 <= umbral <= n):
        raise ErrorJurado("El umbral va de 1 a %d (el número de jurados)."
                          % n)
    filas = []
    for item in items:
        votos = [_valores(j[item["id_item"]]) for j in jurados]
        valores, _cuenta = votar(votos, umbral)
        filas.append(dict(item, **valores))
    return filas


def conteos(filas):
    c = collections.Counter(f["relacion"] or "abstencion" for f in filas)
    return {"items": len(filas), "si": c["si"], "no": c["no"],
            "dudoso": c["dudoso"], "abstencion": c["abstencion"]}


# ----------------------------------------------------------------- salidas

def _en_la_del_experto(ruta):
    partes = [os.path.normcase(p)
              for p in os.path.normpath(ruta).split(os.sep)]
    prohibida = [os.path.normcase(p) for p in CARPETA_DEL_EXPERTO]
    return any(partes[i:i + 2] == prohibida for i in range(len(partes) - 1))


def validar_salida(salida):
    """La carpeta, o ErrorJurado si cae dentro de salidas/revision: como la
    escrita y como la resuelta, igual que `grn_ouroboros.anotar`."""
    escrita = os.path.abspath(salida)
    if (_en_la_del_experto(escrita)
            or _en_la_del_experto(os.path.realpath(escrita))):
        raise ErrorJurado("La salida cae dentro de salidas/revision, la "
                          "carpeta del experto: el jurado va a "
                          "salidas/ouroboros/.")
    return escrita


def escribir_hoja(ruta, filas):
    """Las columnas de la hoja, en UTF-8 con BOM, como `anotaciones.csv` de
    Ouroboros."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_HOJA)
        w.writeheader()
        for fila in filas:
            w.writerow(dict((c, fila.get(c, "")) for c in COLUMNAS_HOJA))
    archivos.reemplazar(tmp, ruta)


def _escribir_json(ruta, objeto):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)
        f.write("\n")
    archivos.reemplazar(tmp, ruta)


def _describir(rutas):
    return [{"archivo": os.path.basename(os.path.dirname(os.path.abspath(r)))
             + "/" + os.path.basename(r), "huella": procedencia.huella(r)}
            for r in rutas]


def ejecutar(rutas, umbral, salida, log=_nada):
    """Escribe la anotación del jurado y su informe; devuelve el informe."""
    validar_salida(salida)
    jurados, items = leer_jurados(rutas)
    filas = agregar(jurados, items, umbral)
    os.makedirs(salida, exist_ok=True)
    ruta = os.path.join(salida, ANOTACIONES)
    escribir_hoja(ruta, filas)
    informe = {"metodo": METODO, "version": VERSION, "regla": REGLA,
               "umbral": umbral, "n_jurados": len(rutas),
               "jurados": _describir(rutas), "conteos": conteos(filas),
               "salidas": {ANOTACIONES: procedencia.huella(ruta)}}
    _escribir_json(os.path.join(salida, INFORME), informe)
    c = informe["conteos"]
    log("Jurado de %d con umbral %d: %d ítems, si %d, no %d, dudoso %d, "
        "abstenciones %d." % (len(rutas), umbral, c["items"], c["si"],
                              c["no"], c["dudoso"], c["abstencion"]))
    return informe


# ------------------------------------------------------------------ barrido

def filtro_reorientado(experto, modelo):
    """El filtro con reorientación sobre los ítems que anotó el experto:
    acepta si el modelo dice `si` con una dirección; correcto si el experto
    dijo `si` con esa misma. La retención es sobre los `si` del experto."""
    aceptados = correctos = verdaderos = 0
    for id_item, fila_e in experto.items():
        e = _valores(fila_e)
        if not e["relacion"]:
            continue
        m = _valores(modelo.get(id_item) or {})
        es_si = e["relacion"] == "si" and e["direccion"] in DIRECCIONES
        acepta = m["relacion"] == "si" and m["direccion"] in DIRECCIONES
        verdaderos += es_si
        aceptados += acepta
        correctos += acepta and es_si and m["direccion"] == e["direccion"]
    return {"regla": "acepta = relación si con la dirección que diga el "
                     "modelo; correcto = el experto dijo si con esa misma",
            "precision": evaluar.proporcion(correctos, aceptados),
            "retencion_de_los_si_del_experto": evaluar.proporcion(
                correctos, verdaderos),
            "aceptados": aceptados}


def _reorientadas(modelo, direcciones, experto):
    """Cuántos aceptados van al revés del bronce, y cuántos de esos son
    correctos para el experto: lo que la reorientación agrega."""
    n = buenas = 0
    for id_item, fila_e in experto.items():
        e = _valores(fila_e)
        if not e["relacion"]:
            continue
        m = _valores(modelo.get(id_item) or {})
        bronce = direcciones.get(id_item)
        if (m["relacion"] == "si" and m["direccion"] in DIRECCIONES
                and bronce in DIRECCIONES and m["direccion"] != bronce):
            n += 1
            buenas += (e["relacion"] == "si"
                       and e["direccion"] == m["direccion"])
    return {"aceptadas_al_reves_del_bronce": n,
            "de_ellas_correctas": buenas}


def _medir(ruta_experto, ruta_modelo, ruta_llave, experto, direcciones):
    r = concordancia.calcular(ruta_experto, ruta_modelo, ruta_llave)
    modelo = precision_ciega.leer_anotacion(ruta_modelo)
    f = r["filtro"]
    return {
        "filtro_bronce": {
            "precision": f["filtro_precision_con_direccion"],
            "retencion": f["retencion_de_los_verdaderos"],
            "diferencia_ic95": f["diferencia_ic95"]},
        "filtro_reorientado": filtro_reorientado(experto, modelo),
        "reorientacion": _reorientadas(modelo, direcciones, experto),
        "acuerdo_relacion": r["acuerdo_por_campo"]["relacion"],
        "kappa_relacion": r["kappa_relacion"],
        "abstenciones": r["abstenciones_del_modelo"],
        "bronce_precision": f["bronce_precision_con_direccion"],
    }


def _elegir(filas, metrica, clave_ret, minima):
    """El k de mayor precisión entre los que retienen al menos `minima`; en
    empate, el de más retención y luego el menor k."""
    candidatas = []
    for fila in filas:
        m = fila[metrica]
        prec, ret = m["precision"]["valor"], m[clave_ret]["valor"]
        if prec is not None and ret is not None and ret >= minima:
            candidatas.append((prec, ret, -fila["umbral"], fila["umbral"]))
    return max(candidatas)[3] if candidatas else None


def barrer(rutas, ruta_experto, ruta_llave, retencion_minima=0.80):
    """Las métricas de cada jurado solo y del jurado con cada umbral."""
    jurados, items = leer_jurados(rutas)
    experto = _leer(ruta_experto, "del experto")
    direcciones = concordancia._leer_direcciones(ruta_llave)
    tmp = tempfile.mkdtemp(prefix="jurado_")
    try:
        individuales = []
        for i, ruta in enumerate(rutas, 1):
            medida = _medir(ruta_experto, ruta, ruta_llave, experto,
                            direcciones)
            individuales.append(dict(medida, jurado=i,
                                     archivo=_describir([ruta])[0]))
        por_umbral = []
        for k in range(1, len(rutas) + 1):
            filas = agregar(jurados, items, k)
            ruta = os.path.join(tmp, "jurado_%d.csv" % k)
            escribir_hoja(ruta, filas)
            medida = _medir(ruta_experto, ruta, ruta_llave, experto,
                            direcciones)
            por_umbral.append(dict(medida, umbral=k,
                                   conteos=conteos(filas)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "metodo": "jurado_barrido", "regla": REGLA,
        "n_jurados": len(rutas), "jurados": _describir(rutas),
        "retencion_minima": retencion_minima,
        "individuales": individuales, "por_umbral": por_umbral,
        "elegido": {
            "filtro_bronce": _elegir(por_umbral, "filtro_bronce",
                                     "retencion", retencion_minima),
            "filtro_reorientado": _elegir(
                por_umbral, "filtro_reorientado",
                "retencion_de_los_si_del_experto", retencion_minima)},
        "notas": [
            "Las dos métricas son sobre los ítems que anotó el experto; la "
            "abstención no acepta.",
            "El umbral se elige en la tanda 1 (desarrollo) y se fija antes "
            "de medir la tanda 2.",
        ],
    }


def _fmt(p):
    if p is None or p["valor"] is None:
        return "%s/%s" % (p["k"], p["n"]) if p else "-"
    return "%d/%d = %.1f %% [%.1f, %.1f]" % (
        p["k"], p["n"], 100 * p["valor"], 100 * p["ic95"][0],
        100 * p["ic95"][1])


def _lineas(etiqueta, m):
    b, r = m["filtro_bronce"], m["filtro_reorientado"]
    return [
        "%s" % etiqueta,
        "    con la dirección del bronce: precisión %s; retiene %s"
        % (_fmt(b["precision"]), _fmt(b["retencion"])),
        "    con reorientación:           precisión %s; retiene %s"
        % (_fmt(r["precision"]), _fmt(r["retencion_de_los_si_del_experto"])),
        "    al revés del bronce: %d aceptadas, %d correctas; relación %s, "
        "kappa %s; abstenciones %d"
        % (m["reorientacion"]["aceptadas_al_reves_del_bronce"],
           m["reorientacion"]["de_ellas_correctas"],
           _fmt(m["acuerdo_relacion"]),
           "no definido" if m["kappa_relacion"] is None
           else "%.3f" % m["kappa_relacion"], m["abstenciones"]["k"]),
    ]


def ejecutar_barrido(rutas, ruta_experto, ruta_llave, ruta_json=None,
                     retencion_minima=0.80, log=_nada):
    r = barrer(rutas, ruta_experto, ruta_llave, retencion_minima)
    log("Barrido del umbral con %d jurados (%s)." % (r["n_jurados"],
                                                    REGLA))
    if r["por_umbral"]:
        log("bronce sin filtro, precisión con dirección: %s"
            % _fmt(r["por_umbral"][0]["bronce_precision"]))
    for m in r["individuales"]:
        for linea in _lineas("jurado %d solo (%s)" % (
                m["jurado"], m["archivo"]["archivo"]), m):
            log(linea)
    for m in r["por_umbral"]:
        c = m["conteos"]
        for linea in _lineas("umbral %d de %d (si %d, no %d, dudoso %d)" % (
                m["umbral"], r["n_jurados"], c["si"], c["no"], c["dudoso"]),
                m):
            log(linea)
    for metrica, nombre in (("filtro_bronce", "con la dirección del bronce"),
                            ("filtro_reorientado", "con reorientación")):
        k = r["elegido"][metrica]
        log("mayor precisión reteniendo al menos %.0f %%, %s: %s"
            % (100 * retencion_minima, nombre,
               "umbral %d" % k if k else "ninguno"))
    for nota in r["notas"]:
        log("Nota: %s" % nota)
    if ruta_json:
        _escribir_json(ruta_json, r)
    return r
