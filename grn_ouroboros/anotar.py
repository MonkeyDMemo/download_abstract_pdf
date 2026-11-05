"""La corrida de Ouroboros sobre una hoja: cada ítem una vez, con caché por
sus entradas, abstención explícita y las salidas en una carpeta.

El anotador llega inyectado: es un callable `anotador(item) -> respuesta`,
que en el servidor arma `agente.crear_anotador` con Strands y en las pruebas
es un falso. Este módulo no importa nada de terceros.

La respuesta del anotador es un dict:

- `texto`: lo que devolvió el modelo, tal cual;
- `done_reason`: el de Ollama (`stop`, `length`...), o None;
- `truncado`: si el modelo se quedó sin tokens (`num_predict`);
- `trayectoria`: las llamadas a herramientas, si hubo;
- `motivo_abstencion`, opcional: cuando no hubo respuesta que leer por algo
  que depende de las entradas (el contexto no cupo, se acabaron los turnos).

Si el anotador lanza una excepción, la corrida se detiene: «no pude
preguntar» no es un veredicto, y guardarlo como abstención haría que la caché
lo repitiera para siempre. Lo ya hecho queda en `veredictos.jsonl`, y volver a
correr retoma desde ahí. Vale igual para Ollama que para Bedrock, y en serie
que con `paralelo` (ver `ejecutar`): con N hilos, las salidas son las mismas
que en serie, byte por byte.

La caché
========
La llave de cada ítem es el sha256 de sus **entradas**, no del ítem ni de la
hora: la oración y sus dos entidades, la huella del prompt, el digest y la
cuantización del modelo, la huella de su template, la versión de Ollama, la
configuración de decodificación completa, la versión y la huella del esquema,
las herramientas, la huella de su código y la de sus recursos. Con Bedrock,
en lugar del digest, el template y la versión de Ollama entran el proveedor,
el id del modelo y la región. Con `contexto`
encendida entra también el `id_item`, porque lo que esa herramienta devuelve
depende de dónde está la oración y no solo de su texto. Con el contexto en
archivo (`ejecutar(..., contexto=...)`, `contexto.py`) entra el texto de las
dos vecinas del ítem, y las entradas llevan la huella del archivo. Lo mismo
dos veces no vuelve a llamar al modelo; cualquier cambio en lo que decide el
veredicto, sí.
La reproducibilidad no depende de T = 0: la da esta caché
(`docs/decisiones.md`, «El LLM sobre la oración es trabajo de tesis»).

`veredictos.jsonl` es de solo anexar, con flush y fsync por línea: una corrida
cortada conserva cada veredicto que alcanzó a escribir, y una línea cortada a
la mitad se salta al leer.

La abstención
=============
Pre-registrada antes de correr: una respuesta truncada, sin un objeto JSON,
con un campo de menos o de más, con una etiqueta fuera de la rúbrica o con una
combinación que `revision.validar` rechaza es **abstención**. En la hoja sale
con los campos de anotación vacíos, y en la evaluación cuenta como error. El
bloque `<think>…</think>` se quita antes de leer el JSON.

El fragmento tiene que estar literal en la oración, y se guardan sus offsets.
Si no está, el veredicto se conserva con `evidencia_invalida = si`: se marca,
no se borra.

Las salidas
===========
- `veredictos.jsonl`: la caché, con todo lo de cada ítem.
- `anotaciones.csv`: exactamente las columnas de la hoja, en UTF-8 con BOM,
  para leerla con `precision_ciega.leer_anotacion` como la del experto.
- `corrida.json`: versiones, configuración, huellas y conteos. Se escribe al
  empezar (`corriendo`) y al terminar (`ok` o `error`), como una fila de
  `corridas`. No lleva oraciones. Con Bedrock, los conteos suman además los
  tokens de entrada y de salida, y con un precio (`gasto.py`) lleva `costo`:
  el de toda la carpeta y el de esta corrida. Con Ollama no gana campos.

Una carpeta que ya tiene una corrida con otra hoja, otro prompt, otro modelo u
otra configuración no se reutiliza: esa corrida pudo estar pre-registrada.

La carpeta nunca cae dentro de `salidas/revision`, que es la del experto
(`validar_salida`): las salidas de Ouroboros van a `salidas/ouroboros/`, y sus
veredictos no pueden quedar donde se anota.

`leer_corrida` devuelve los ítems y los veredictos de una corrida terminada,
para evaluarla otra vez (`evals.py`) sin volver a llamar al modelo.

Biblioteca estándar y Python 3.8. No imprime: reporta por `log`.
"""

import collections
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import platform
import re
import time
from datetime import datetime, timezone

from grn_comun import archivos, procedencia
from grn_ouroboros import calibracion, gasto, rubrica

VERSION = 1
METODO = "ouroboros-v0"

VEREDICTOS = "veredictos.jsonl"
ANOTACIONES = "anotaciones.csv"
CORRIDA = "corrida.json"

CLAVES_ENTRADAS = ("prompt", "modelo", "ollama", "decodificacion", "esquema",
                   "herramientas", "recursos")

# Lo que se reporta en `corrida.json`; si no está instalado sale None.
PAQUETES = ("strands-agents", "strands-agents-evals", "strands-agents-tools",
            "ollama", "pydantic", "httpx")

_THINK = re.compile(r"<think>.*?</think>", re.S)

# La carpeta del experto: ahí viven la hoja que anota, sus anotaciones y la
# llave del sorteo (`servidor.py --revision salidas/revision/...`).
CARPETA_DEL_EXPERTO = ("salidas", "revision")


def _nada(_mensaje):
    pass


def _en_la_del_experto(ruta):
    partes = [os.path.normcase(p)
              for p in os.path.normpath(ruta).split(os.sep)]
    prohibida = [os.path.normcase(p) for p in CARPETA_DEL_EXPERTO]
    return any(partes[i:i + 2] == prohibida for i in range(len(partes) - 1))


def validar_salida(salida):
    """La carpeta resuelta, o ValueError si cae dentro de salidas/revision.

    Se mira la ruta dos veces, componente por componente y con `normcase`,
    que en Windows no distingue mayúsculas (`Salidas\\Revision` es la misma
    carpeta):

    - como se escribió, absoluta y sin `..`: si `salidas` es un enlace a una
      carpeta con otro nombre, la resuelta ya no dice salidas/revision;
    - resuelta, sin enlaces: un atajo a la carpeta del experto no lo dice
      como se escribió.

    Por componentes y no por la raíz del repositorio, para que tampoco pase
    la `salidas/revision` de otro clon o de otro worktree.
    """
    escrita = os.path.abspath(salida)
    resuelta = os.path.realpath(escrita)
    if _en_la_del_experto(escrita) or _en_la_del_experto(resuelta):
        raise ValueError(
            "La salida cae dentro de salidas/revision, la carpeta del "
            "experto. Las salidas de Ouroboros van a salidas/ouroboros/: "
            "el experto no las ve, y sus veredictos no pueden quedar "
            "donde se anota.")
    return resuelta


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- entradas

def armar_entradas(descripcion, decodificacion, huella_prompt, herramientas,
                   huellas_recursos):
    """El dict de entradas que entra a la llave de la caché, a partir de lo
    que describe `motor.describir` (o `agente.describir_bedrock`) y de lo que
    decide la corrida.

    Con Ollama son las de siempre, sin una clave más: las corridas ya hechas
    conservan su llave. Con otro proveedor el modelo es su id y su región, la
    versión de Ollama vale None y `proveedor` lo dice, para que sus veredictos
    nunca se mezclen con los de Ollama.
    """
    proveedor = descripcion.get("proveedor", "ollama")
    if proveedor == "ollama":
        modelo = {"nombre": descripcion["modelo"],
                  "digest": descripcion["digest"],
                  "cuantizacion": descripcion["cuantizacion"],
                  "huella_template": descripcion["huella_template"]}
        ollama = descripcion["ollama"]
    else:
        modelo = {"model_id": descripcion["modelo"],
                  "region": descripcion["region"]}
        ollama = None
    entradas = {
        "prompt": huella_prompt,
        "modelo": modelo,
        "ollama": ollama,
        "decodificacion": decodificacion,
        "esquema": {"version": rubrica.VERSION_ESQUEMA,
                    "huella": rubrica.huella_esquema()},
        "herramientas": herramientas,
        "recursos": huellas_recursos,
    }
    if proveedor != "ollama":
        entradas["proveedor"] = proveedor
    return entradas


def _exigir_entradas(entradas):
    faltan = [c for c in CLAVES_ENTRADAS if c not in entradas]
    if faltan:
        raise ValueError("A las entradas de la caché les falta: %s."
                         % ", ".join(faltan))


def llave_cache(item, entradas):
    """sha256 de las entradas del ítem (ver el docstring del módulo)."""
    _exigir_entradas(entradas)
    propio = dict((c, item[c]) for c in ("oracion", "entidad_1", "entidad_2"))
    if entradas["herramientas"] == "todas":
        propio["id_item"] = item["id_item"]
    if "contexto" in item:
        propio["contexto"] = item["contexto"]
    texto = json.dumps({"item": propio, "entradas": entradas},
                       sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ------------------------------------------------------- lectura del modelo

def quitar_razonamiento(texto):
    """El texto sin los bloques `<think>…</think>`.

    También sin lo que va antes de un `</think>` suelto (el template puso la
    apertura) y sin lo que va después de un `<think>` sin cierre (el
    razonamiento se cortó): en los dos casos eso es razonamiento, no
    respuesta.
    """
    texto = _THINK.sub("", texto or "")
    if "</think>" in texto:
        texto = texto.rsplit("</think>", 1)[1]
    if "<think>" in texto:
        texto = texto.split("<think>", 1)[0]
    return texto.strip()


def extraer_json(texto):
    """El primer objeto JSON del texto, o None. Tolera un cerco de código o
    una frase alrededor, que sin `format` (con herramientas) aparecen."""
    inicio = (texto or "").find("{")
    if inicio < 0:
        return None
    try:
        objeto, _fin = json.JSONDecoder().raw_decode(texto, inicio)
    except ValueError:
        return None
    return objeto if isinstance(objeto, dict) else None


def ubicar_fragmento(oracion, fragmento):
    """[inicio, fin) del fragmento en la oración, o None si no está literal.
    Solo se recortan los espacios de las orillas: lo demás tiene que ser
    carácter por carácter."""
    fragmento = (fragmento or "").strip()
    if not fragmento:
        return None
    i = oracion.find(fragmento)
    return [i, i + len(fragmento)] if i >= 0 else None


def juzgar(item, respuesta):
    """El veredicto de un ítem a partir de la respuesta del anotador."""
    texto = respuesta.get("texto") or ""
    valor = {
        "valores": None, "abstencion": True, "motivo_abstencion": "",
        "errores": [], "avisos": [],
        "fragmento": "", "fragmento_offsets": None, "motivo": "",
        "evidencia_invalida": "",
        "trayectoria": list(respuesta.get("trayectoria") or []),
        "done_reason": respuesta.get("done_reason"),
        "truncado": bool(respuesta.get("truncado")),
        "texto": texto,
    }
    # Solo Bedrock trae `uso`: un veredicto de Ollama queda como antes.
    if respuesta.get("uso") is not None:
        valor["uso"] = respuesta["uso"]
    if respuesta.get("motivo_abstencion"):
        valor["motivo_abstencion"] = respuesta["motivo_abstencion"]
        return valor
    # Truncada es abstención aunque lo que llegó parezca un JSON completo:
    # la regla se fijó antes de correr y no se decide caso por caso.
    if valor["truncado"]:
        valor["motivo_abstencion"] = "truncado"
        return valor
    objeto = extraer_json(quitar_razonamiento(texto))
    if objeto is None:
        valor["motivo_abstencion"] = "json_invalido"
        return valor
    valores, extras, errores_esquema, errores_rubrica, avisos = (
        rubrica.validar_respuesta(objeto))
    if errores_esquema:
        valor.update(motivo_abstencion="esquema", errores=errores_esquema)
        return valor
    if errores_rubrica:
        valor.update(motivo_abstencion="rubrica", errores=errores_rubrica)
        return valor
    fragmento = extras["fragmento"].strip()
    offsets = ubicar_fragmento(item["oracion"], fragmento)
    valor.update(valores=valores, abstencion=False, avisos=avisos,
                 fragmento=fragmento, fragmento_offsets=offsets,
                 motivo=extras["motivo"].strip(),
                 evidencia_invalida="no" if offsets else "si")
    return valor


# ------------------------------------------------------------------ archivos

def leer_veredictos(ruta):
    """{llave: valor} del JSONL; gana la última línea de cada llave. Lo que
    no se lee (una línea cortada) se salta: el archivo es de solo anexar y no
    hay otra forma de que se descomponga."""
    cache = {}
    if not os.path.isfile(ruta):
        return cache
    with io.open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                registro = json.loads(linea)
            except ValueError:
                continue
            if (isinstance(registro, dict)
                    and isinstance(registro.get("llave"), str)
                    and isinstance(registro.get("valor"), dict)):
                cache[registro["llave"]] = registro["valor"]
    return cache


def anexar(ruta, registro):
    """Una línea más, ya en disco al volver. Si la última quedó cortada (un
    corte de luz a media escritura), se cierra con un salto antes: pegada a
    ella, la nueva sería ilegible y se perdería con la vieja."""
    linea = (json.dumps(registro, ensure_ascii=False, sort_keys=True)
             + "\n").encode("utf-8")
    with open(ruta, "a+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                linea = b"\n" + linea
        f.write(linea)
        f.flush()
        os.fsync(f.fileno())


def escribir_anotaciones(ruta, items, resultados):
    """La hoja con lo que anotó el modelo, en el orden de la hoja. Se escribe
    a un `.tmp` y se pone en su lugar al final."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rubrica.COLUMNAS_HOJA)
        w.writeheader()
        for item in items:
            fila = dict.fromkeys(rubrica.COLUMNAS_HOJA, "")
            for c in rubrica.COLUMNAS_ITEM:
                fila[c] = item[c]
            valor = resultados.get(item["id_item"])
            if valor and not valor["abstencion"]:
                fila.update(valor["valores"])
            w.writerow(fila)
    archivos.reemplazar(tmp, ruta)


def _escribir_json(ruta, objeto):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    archivos.reemplazar(tmp, ruta)


def versiones(paquetes=PAQUETES):
    """Las versiones instaladas de lo que decide la corrida."""
    import importlib.metadata as metadatos
    salida = {"python": platform.python_version()}
    for paquete in paquetes:
        try:
            salida[paquete] = metadatos.version(paquete)
        except metadatos.PackageNotFoundError:
            salida[paquete] = None
    return salida


def _normalizar(objeto):
    """Como queda después de pasar por JSON: así se compara con lo leído."""
    return json.loads(json.dumps(objeto, ensure_ascii=False))


class CarpetaOcupada(ValueError):
    """La carpeta ya tiene una corrida con otras entradas. Tiene clase propia
    para que el CLI la distinga de un error del anotador, cuyo mensaje no se
    imprime."""


def _exigir_misma_corrida(ruta, identidad):
    if not os.path.isfile(ruta):
        return
    try:
        with io.open(ruta, encoding="utf-8") as f:
            previo = json.load(f)
    except ValueError:
        previo = {}
    if not isinstance(previo, dict) or previo.get("identidad") != identidad:
        raise CarpetaOcupada(
            "La carpeta de salida ya tiene una corrida de Ouroboros con otra "
            "hoja, otro prompt, otro modelo u otra configuración, y pudo "
            "estar pre-registrada: usa otra carpeta.")


def conteos(resultados):
    """Los conteos de `corrida.json`: solo números. Los tokens, solo si algún
    veredicto trae `uso` (Bedrock): con Ollama, los de antes."""
    valores = list(resultados.values())
    abstenciones = [v for v in valores if v["abstencion"]]
    salida = {
        "items": len(valores),
        "validas": len(valores) - len(abstenciones),
        "abstenciones": len(abstenciones),
        "abstenciones_por_motivo": dict(sorted(collections.Counter(
            v["motivo_abstencion"] for v in abstenciones).items())),
        "fragmentos_invalidos": sum(
            1 for v in valores
            if not v["abstencion"] and v["evidencia_invalida"] == "si"),
        "con_avisos": sum(1 for v in valores if v.get("avisos")),
        "llamadas_a_herramientas": sum(len(v.get("trayectoria") or [])
                                       for v in valores),
        "segundos_totales": round(sum(v.get("segundos") or 0
                                      for v in valores), 1),
    }
    uso = gasto.sumar_uso(valores)
    if uso["con_uso"]:
        salida["tokens_entrada"] = uso["entrada"]
        salida["tokens_salida"] = uso["salida"]
    return salida


# ------------------------------------------------------------------ corrida

def _llamar(anotador, item, reloj):
    """(respuesta, segundos) de un ítem. Corre en el hilo que toque: no
    escribe nada ni toca la caché."""
    t0 = reloj()
    respuesta = anotador(item)
    return respuesta, reloj() - t0


def _esperar(futuro):
    """El resultado del futuro, o la excepción del anotador. Se espera en
    vueltas cortas porque en Windows una espera sin tope no la corta Ctrl-C;
    y se mira `done()`, no `TimeoutError`, porque un anotador también puede
    lanzar `TimeoutError` (el de un socket, desde 3.10)."""
    while not futuro.done():
        concurrent.futures.wait([futuro], timeout=0.5)
    return futuro.result()


def _costo(precio, resultados, nuevos):
    """El costo de la hoja (todos sus veredictos, también los de la caché) y
    el de esta corrida (los nuevos), con el precio usado."""
    def usd(valores):
        return round(sum(gasto.costo(v.get("uso"), precio) for v in valores),
                     6)
    return {"precio_usd_por_millon": list(precio),
            "usd_total": usd(resultados.values()),
            "usd_esta_corrida": usd(nuevos)}


def _con_contexto(items, contexto):
    """Los ítems con sus vecinas (`contexto.para_hoja`); ValueError si a
    alguno le falta."""
    faltan = sum(1 for item in items if item["id_item"] not in contexto)
    if faltan:
        raise ValueError("%d ítems de la hoja no tienen contexto." % faltan)
    for item in items:
        vecinas = contexto[item["id_item"]]
        item["contexto"] = {"anterior": vecinas.get("anterior") or "",
                            "siguiente": vecinas.get("siguiente") or ""}
    return items


def ejecutar(ruta_hoja, salida, anotador, entradas, configuracion=None,
             descripcion=None, log=_nada, reloj=time.monotonic, paralelo=1,
             paquetes=PAQUETES, contexto=None, precio=None):
    """Anota la hoja con `anotador` y escribe las salidas en `salida`.

    Devuelve {"items", "resultados" ({id_item: veredicto}), "resumen"}. Los
    `segundos_totales` suman lo que tardó el modelo en cada ítem, también los
    que salieron de la caché; `segundos_esta_corrida` es el reloj de esta.

    Con `paralelo` N > 1, N hilos llaman al anotador a la vez, y nada más: el
    hilo principal recorre la hoja en orden, espera a cada ítem y es el único
    que juzga, escribe `veredictos.jsonl`, toca la caché y reporta el avance.
    Así las salidas salen en el mismo orden y con el mismo contenido que en
    serie, y no dependen de N. Un ítem repetido (la misma llave) se pide una
    sola vez y el segundo sale de la caché, como en serie. Si un ítem lanza,
    la corrida se detiene igual que en serie: se guarda lo anterior a él, los
    que no habían empezado se cancelan, y lo que ya estaba en vuelo (a lo
    más N - 1 ítems) se espera y se descarta, para que `veredictos.jsonl`
    quede como lo habría dejado la corrida en serie; volver a correr lo pide
    otra vez. `segundos` de cada ítem es lo que tardó su llamada, así que en
    paralelo `segundos_totales` pasa del reloj de la corrida.

    `contexto` ({id_item: {anterior, siguiente}}, de `contexto.para_hoja`)
    agrega las vecinas a cada ítem: el anotador las recibe y entran a la
    llave. `precio` ((entrada, salida) en USD por millón, de `gasto.precio`)
    agrega `costo` a `corrida.json`. Sin los dos, todo es como antes.
    """
    _exigir_entradas(entradas)
    if (isinstance(paralelo, bool) or not isinstance(paralelo, int)
            or paralelo < 1):
        raise ValueError("paralelo es un entero de 1 en adelante.")
    validar_salida(salida)
    items = calibracion.leer_hoja(ruta_hoja)
    if contexto is not None:
        _con_contexto(items, contexto)
    os.makedirs(salida, exist_ok=True)
    ruta_veredictos = os.path.join(salida, VEREDICTOS)
    ruta_anotaciones = os.path.join(salida, ANOTACIONES)
    ruta_corrida = os.path.join(salida, CORRIDA)
    identidad = _normalizar({"hoja": procedencia.huella(ruta_hoja),
                             "entradas": entradas})
    _exigir_misma_corrida(ruta_corrida, identidad)

    resumen = {
        "metodo": METODO, "version": VERSION, "estatus": "corriendo",
        "iniciada_en": ahora(), "identidad": identidad,
        "configuracion": configuracion, "modelo": descripcion,
        "versiones": versiones(paquetes), "n_items": len(items),
    }
    _escribir_json(ruta_corrida, resumen)
    cache = leer_veredictos(ruta_veredictos)
    resultados = {}
    nuevos = []
    reutilizadas = nuevas = 0
    t_corrida = reloj()
    hilos, futuros = None, {}
    try:
        if paralelo > 1:
            hilos = concurrent.futures.ThreadPoolExecutor(
                max_workers=paralelo, thread_name_prefix="ouroboros")
            for item in items:
                llave = llave_cache(item, entradas)
                if llave not in cache and llave not in futuros:
                    futuros[llave] = hilos.submit(_llamar, anotador, item,
                                                  reloj)
        for i, item in enumerate(items, 1):
            llave = llave_cache(item, entradas)
            valor = cache.get(llave)
            if valor is not None:
                reutilizadas += 1
            else:
                if hilos is None:
                    respuesta, segundos = _llamar(anotador, item, reloj)
                else:
                    respuesta, segundos = _esperar(futuros[llave])
                valor = juzgar(item, respuesta)
                valor["segundos"] = round(segundos, 3)
                anexar(ruta_veredictos, {"llave": llave,
                                         "id_item": item["id_item"],
                                         "hora": ahora(), "valor": valor})
                cache[llave] = valor
                nuevos.append(valor)
                nuevas += 1
            resultados[item["id_item"]] = valor
            if i % 10 == 0 or i == len(items):
                log("%d de %d ítems (%d de la caché)"
                    % (i, len(items), reutilizadas))
    except BaseException as e:
        for futuro in futuros.values():
            futuro.cancel()
        # Solo el tipo: el mensaje de una excepción puede traer el texto de
        # la petición, y corrida.json no lleva oraciones.
        resumen.update(estatus="error", error=type(e).__name__,
                       terminada_en=ahora(), conteos=conteos(resultados),
                       reutilizadas=reutilizadas, nuevas=nuevas)
        if precio is not None:
            resumen["costo"] = _costo(precio, resultados, nuevos)
        _escribir_json(ruta_corrida, resumen)
        raise
    finally:
        if hilos is not None:
            hilos.shutdown(wait=True)
    escribir_anotaciones(ruta_anotaciones, items, resultados)
    resumen.update(
        estatus="ok", terminada_en=ahora(), conteos=conteos(resultados),
        reutilizadas=reutilizadas, nuevas=nuevas,
        segundos_esta_corrida=round(reloj() - t_corrida, 1),
        salidas={ANOTACIONES: procedencia.huella(ruta_anotaciones),
                 VEREDICTOS: procedencia.huella(ruta_veredictos)})
    if precio is not None:
        resumen["costo"] = _costo(precio, resultados, nuevos)
    _escribir_json(ruta_corrida, resumen)
    return {"items": items, "resultados": resultados, "resumen": resumen}


# ------------------------------------------------------ una corrida hecha

def _items_de(ruta_anotaciones):
    """Los ítems de `anotaciones.csv`, que trae las cuatro columnas de la
    hoja tal como se leyeron: con ellas sale la misma llave de la caché."""
    with io.open(ruta_anotaciones, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if lector.fieldnames != rubrica.COLUMNAS_HOJA:
            raise ValueError("%s no tiene las columnas de la hoja."
                             % ANOTACIONES)
        return [dict((c, fila[c] or "") for c in rubrica.COLUMNAS_ITEM)
                for fila in lector]


def leer_corrida(salida, ruta_contexto=None):
    """{"items", "resultados", "resumen"} de una corrida terminada, como los
    devuelve `ejecutar`, sin llamar al modelo.

    Se exige que la corrida haya terminado bien y que `anotaciones.csv` y
    `veredictos.jsonl` sean los que dejó (sus huellas están en
    `corrida.json`): si cambiaron después, ya no describen esa corrida. Cada
    veredicto se busca por la llave que dan las entradas de la corrida, no
    por el `id_item` del JSONL: dos ítems con la misma oración y las mismas
    entidades comparten llave, y el segundo nunca llegó a escribirse. Una
    corrida con contexto pide el mismo archivo de contexto (`contexto.py`):
    las vecinas son parte de la llave.
    """
    ruta_corrida = os.path.join(salida, CORRIDA)
    if not os.path.isfile(ruta_corrida):
        raise ValueError("La carpeta no tiene una corrida de Ouroboros "
                         "(falta %s)." % CORRIDA)
    try:
        with io.open(ruta_corrida, encoding="utf-8") as f:
            resumen = json.load(f)
    except ValueError:
        raise ValueError("%s no se puede leer." % CORRIDA)
    if not isinstance(resumen, dict) or resumen.get("estatus") != "ok":
        raise ValueError(
            "La corrida no terminó bien: vuelve a correr anotar con la misma "
            "hoja y la misma configuración para retomarla.")
    salidas = resumen.get("salidas") or {}
    for nombre in (ANOTACIONES, VEREDICTOS):
        ruta = os.path.join(salida, nombre)
        if procedencia.huella(ruta) != salidas.get(nombre):
            raise ValueError("%s no es el que dejó la corrida." % nombre)
    entradas = (resumen.get("identidad") or {}).get("entradas") or {}
    _exigir_entradas(entradas)
    items = _items_de(os.path.join(salida, ANOTACIONES))
    if "contexto" in entradas:
        if ruta_contexto is None:
            raise ValueError("La corrida se hizo con contexto: pásalo con "
                             "--contexto, el mismo archivo.")
        from grn_ouroboros import contexto
        _con_contexto(items, contexto.para_hoja(items, ruta_contexto))
    elif ruta_contexto is not None:
        raise ValueError("La corrida se hizo sin contexto.")
    cache = leer_veredictos(os.path.join(salida, VEREDICTOS))
    resultados, faltan = {}, 0
    for item in items:
        valor = cache.get(llave_cache(item, entradas))
        if valor is None:
            faltan += 1
        else:
            resultados[item["id_item"]] = valor
    if faltan:
        raise ValueError("Faltan los veredictos de %d ítems en %s."
                         % (faltan, VEREDICTOS))
    return {"items": items, "resultados": resultados, "resumen": resumen}
