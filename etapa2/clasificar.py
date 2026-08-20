#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Etapa 3: clasifica los pares candidatos con el BioBERT afinado.

Es el ÚNICO archivo del repositorio que importa torch y transformers, y por eso
vive aparte: los demás scripts lo invocan por subprocess, igual que barrido.py
invoca a bio_bert_re_finetune.py. Nunca se importa.

Los dos imports pesados viven DENTRO de las funciones que los usan, no en la
cabecera. Así test_clasificar.py corre en la laptop del laboratorio, que no
tiene torch, y cubre todo lo que no es la pasada hacia adelante: el mapa de
etiquetas, la reanudación, las invariantes de salida y el manejo de errores.

Solo inferencia: el modelo en eval() y todo bajo torch.no_grad(). No entrena,
no ajusta nada contra los datos de evaluación y **no decide ninguna arista**:
las cuatro probabilidades se escriben enteras y quien aplica umbrales es red.py.
Así cambiar un umbral cuesta segundos y no otra hora de CPU.

Cuatro decisiones que este script defiende:

1. **El orden de las etiquetas se lee de label_mapping.json y jamás se escribe
   en el código.** Hay tres órdenes distintos en el árbol del asesor. El del
   propio script de entrenamiento, LABELS_DEFAULT =
   ["activates","represses","regulates","no_relation"], intercambia 'represses'
   con 'no_relation' respecto al del checkpoint. Leer los logits con la lista
   equivocada reporta represión como "sin relación" sin que nada falle: saldría
   una red completa, con los signos volteados y cero errores en la terminal. Si
   falta el archivo, salgo con código 1; si config.json dice otra cosa que
   label_mapping.json, también, porque ahí no hay nada que adivinar.

2. **La corrida es reanudable.** Cien mil pares son alrededor de una hora de
   CPU y la sesión se cae. Cada lote se escribe y se vacía el buffer en el acto
   sobre <salida>.parcial; al reanudar se descarta la última línea si quedó a
   medias y se continúa. El nombre definitivo solo aparece al final, con
   os.replace(), así que nadie encuentra nunca un predicciones.jsonl a medio
   escribir. Sin --reanudar, un .parcial existente NO se pisa: salgo con 1 y
   digo cuántos pares ya estaban, porque tirar una hora de CPU en silencio es
   peor que molestar.

3. **La entrada se valida antes de cargar 433 MB de pesos.** Un marcado que no
   sea el del entrenamiento no da error en ninguna capa: da probabilidades, y
   esas probabilidades son ruido con aspecto de resultado.

4. **El avance se imprime sin buffer.** Una muerte por señal no se puede llevar
   el diagnóstico; sin eso, lo único que queda de una corrida de una hora es
   que no hay archivo.

Uso:

    python etapa2/clasificar.py --modelo RUTA/run_22_lr3e-5_ep8_bs16_wu0.1
    python etapa2/clasificar.py --modelo RUTA --reanudar
    python etapa2/clasificar.py --modelo RUTA \
        --calibrar datos_etapa2/por_pmid/entity_marked_dev.jsonl
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

# El orden de esta lista NO se usa para leer logits. Sirve para dos cosas: para
# comprobar que el conjunto de etiquetas del checkpoint es el que esperamos, y
# para fijar el orden de las columnas p_* de la salida, que el contrato congela.
# El orden real de los logits sale siempre de label_mapping.json.
ETIQUETAS_ESPERADAS = ["activates", "no_relation", "regulates", "represses"]

# Los tres umbrales por omisión de red.py. Aquí solo sirven de respaldo cuando
# la calibración se queda sin datos de una clase. No se aplican nunca a la
# salida: este script no filtra nada.
UMBRALES_POR_OMISION = {"activates": 0.65, "represses": 0.70, "regulates": 0.60}

# La regex de validación del entrenamiento. La retrorreferencia \1 evita dar por
# bueno un "<e1> X </e2>", y el \S+ exige que la mención no lleve espacios.
MARCADO = re.compile(r"<e([12])> (\S+) </e\1>")

# Contrato, sección 4: una línea por línea de entrada, con estas claves y en
# este orden. Se construye a mano para que el orden no dependa del checkpoint.
CLAVES_SALIDA = ["id_par", "pmid", "tf", "target", "prediccion",
                 "p_activates", "p_no_relation", "p_regulates", "p_represses",
                 "seccion", "fuente", "autorregulacion", "redaccion"]

# Contrato, sección 4: control de cordura.
EXACTITUD_MINIMA_CONTROL = 0.50

# Debajo de este número no se exige que haya más de una clase predicha. La
# invariante del contrato ("todas la misma clase = modelo mal cargado") es
# correcta a escala de corpus y absurda con --limite 5, que es justo para
# depurar.
MINIMO_PARA_EXIGIR_VARIEDAD = 20

# Los pesos pueden venir en cualquiera de los dos formatos. El checkpoint del
# asesor se guardó con save_safetensors=False, o sea pytorch_model.bin.
PESOS = ("pytorch_model.bin", "model.safetensors")

ARCHIVOS_MODELO = [
    ("config.json", "la arquitectura y el id2label del checkpoint"),
    (PESOS, "los pesos"),
    ("vocab.txt", "el vocabulario del tokenizador"),
    ("tokenizer_config.json", "la configuración del tokenizador (do_lower_case)"),
]

RIESGO_ETIQUETAS = (
    "Sin label_mapping.json no sé en qué orden salen los cuatro logits, y NO lo "
    "adivino. El LABELS_DEFAULT de bio_bert_re_finetune.py es "
    '["activates","represses","regulates","no_relation"], que comparado con el '
    "orden del checkpoint intercambia 'represses' con 'no_relation'. Leer los "
    "logits con la lista equivocada reporta represión como 'sin relación' sin "
    "que nada falle: saldría una red completa, con los signos volteados y cero "
    "errores en la terminal.")


# ------------------------------------------------------------- utilidades

def formato_tiempo(segundos):
    """Duración para leer de reojo mientras la corrida avanza."""
    if segundos < 90:
        return "%.0f s" % segundos
    if segundos < 5400:
        return "%.1f min" % (segundos / 60.0)
    return "%.1f h" % (segundos / 3600.0)


def escribir_json(ruta, objeto):
    """JSON atómico: temporal más os.replace(), como pide el contrato."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, ruta)


def sha1_de(ruta):
    h = hashlib.sha1()
    with open(ruta, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# -------------------------------------------------------- mapa de etiquetas

def normalizar_etiquetas(dato):
    """Acepta las tres formas en que el orden puede venir escrito.

    particionar.py escribe una lista; config.json trae {"0": "activates", ...};
    y hay quien guarda el label2id, {"activates": 0, ...}. Las tres dicen lo
    mismo. Devuelve la lista indexada por id, o None si no se puede interpretar.
    """
    if isinstance(dato, list):
        if dato and all(isinstance(x, str) for x in dato):
            return list(dato)
        return None
    if isinstance(dato, dict):
        if not dato:
            return None
        valores = list(dato.values())
        # id2label: las claves son los ids.
        if all(isinstance(v, str) for v in valores):
            try:
                pares = sorted((int(k), v) for k, v in dato.items())
            except (TypeError, ValueError):
                return None
            if [i for i, _ in pares] != list(range(len(pares))):
                return None
            return [v for _, v in pares]
        # label2id: los ids son los valores.
        if (all(isinstance(k, str) for k in dato) and
                all(isinstance(v, int) and not isinstance(v, bool) for v in valores)):
            if sorted(valores) != list(range(len(valores))):
                return None
            return [k for k, _ in sorted(dato.items(), key=lambda kv: kv[1])]
    return None


def leer_etiquetas(ruta_mapa, ruta_config=None):
    """El orden de los logits. Sale con código 1 antes que adivinarlo."""
    if not ruta_mapa or not os.path.exists(ruta_mapa):
        sys.exit("No encuentro label_mapping.json (busqué en %s).\n\n%s\n\n"
                 "Cópialo del árbol del asesor o pásalo con --etiquetas RUTA. "
                 "particionar.py escribe uno correcto en la carpeta de la "
                 "partición." % (ruta_mapa or "ninguna ruta", RIESGO_ETIQUETAS))
    try:
        with open(ruta_mapa, encoding="utf-8") as f:
            crudo = json.load(f)
    except ValueError as e:
        sys.exit("%s no es JSON válido (%s).\n\n%s"
                 % (ruta_mapa, e, RIESGO_ETIQUETAS))

    etiquetas = normalizar_etiquetas(crudo)
    if etiquetas is None:
        sys.exit("No entiendo el contenido de %s: esperaba una lista de "
                 "etiquetas o un mapa id<->etiqueta, y trae %r.\n\n%s"
                 % (ruta_mapa, crudo, RIESGO_ETIQUETAS))
    if sorted(etiquetas) != ETIQUETAS_ESPERADAS:
        sys.exit("%s declara las etiquetas %r. No son las cuatro esperadas "
                 "(%r). Leer los logits con otro conjunto reporta represión "
                 "como 'sin relación' sin que nada falle."
                 % (ruta_mapa, etiquetas, ETIQUETAS_ESPERADAS))

    # El cruce con config.json es el guardián de verdad. Un checkpoint entrenado
    # sin --labels_json trae en su config.json el orden de LABELS_DEFAULT; si el
    # label_mapping.json que se le pone al lado es el del servidor, los dos
    # archivos existen, los dos parecen sanos, y el signo sale volteado.
    if ruta_config and os.path.exists(ruta_config):
        try:
            with open(ruta_config, encoding="utf-8") as f:
                cfg = json.load(f)
        except ValueError:
            cfg = {}
        del_config = (normalizar_etiquetas(cfg.get("id2label"))
                      if isinstance(cfg, dict) else None)
        if del_config is not None and del_config != etiquetas:
            sys.exit("Los dos archivos del checkpoint declaran órdenes "
                     "distintos:\n  %s -> %r\n  %s -> %r\n"
                     "No elijo por ti. Averigua con cuál se entrenó antes de "
                     "leer un solo logit: la diferencia es que 'represses' y "
                     "'no_relation' cambian de lugar."
                     % (os.path.basename(ruta_mapa), etiquetas,
                        os.path.basename(ruta_config), del_config))
    return etiquetas


def leer_do_lower_case(dir_modelo):
    """Dice si la mayúscula que distingue LasR de lasR es señal o ruido.

    No es motivo de salir con 1, pero sin este dato no se interpreta ninguna
    métrica: si es true, la convención de la sección 3.1(g) del contrato (TF en
    forma de proteína, blanco en forma de gen) es convención de nuestros campos
    y no señal para el modelo.
    """
    ruta = os.path.join(dir_modelo, "tokenizer_config.json")
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            cfg = json.load(f)
    except ValueError:
        return None
    valor = cfg.get("do_lower_case") if isinstance(cfg, dict) else None
    return bool(valor) if isinstance(valor, bool) else None


# ------------------------------------------------------------ el checkpoint

def archivos_que_faltan(dir_modelo):
    """Lista de (nombre, para qué sirve) de lo que no está en la carpeta."""
    faltan = []
    for nombre, para_que in ARCHIVOS_MODELO:
        opciones = nombre if isinstance(nombre, tuple) else (nombre,)
        if not any(os.path.exists(os.path.join(dir_modelo, o)) for o in opciones):
            faltan.append((" o ".join(opciones), para_que))
    return faltan


def exigir_modelo(dir_modelo, ruta_etiquetas):
    """Comprueba el checkpoint y devuelve la ruta del mapa de etiquetas.

    Sale con código 1 y NOMBRA los archivos, en vez del error seco de argparse:
    quien corre esto suele estar copiando 433 MB de otra máquina, y lo que
    necesita saber es exactamente qué le faltó traer.
    """
    ayuda = (
        "--modelo tiene que apuntar a la carpeta del checkpoint afinado\n"
        "(run_22_lr3e-5_ep8_bs16_wu0.1 en el árbol del asesor), que necesita:\n\n"
        "  config.json             la arquitectura y el id2label del checkpoint\n"
        "  pytorch_model.bin       los pesos (o model.safetensors)\n"
        "  vocab.txt               el vocabulario del tokenizador\n"
        "  tokenizer_config.json   de ahí sale do_lower_case\n"
        "  label_mapping.json      el ORDEN de las cuatro etiquetas\n\n"
        "El label_mapping.json puede ir aparte, con --etiquetas RUTA, porque\n"
        "trainer.save_model() no lo escribe junto a los pesos.\n\n"
        "Uso:\n"
        "  python etapa2/clasificar.py --modelo RUTA/run_22_lr3e-5_ep8_bs16_wu0.1")

    if not dir_modelo:
        sys.exit("No me diste --modelo, y sin el checkpoint no hay nada que "
                 "clasificar.\n\n" + ayuda)
    if not os.path.isdir(dir_modelo):
        sys.exit("--modelo %s no es una carpeta.\n\n%s" % (dir_modelo, ayuda))

    faltan = archivos_que_faltan(dir_modelo)
    if faltan:
        detalle = "\n".join("  %-23s %s" % (n, p) for n, p in faltan)
        sys.exit("A la carpeta %s le faltan archivos del checkpoint:\n\n%s\n\n%s"
                 % (dir_modelo, detalle, ayuda))

    if not ruta_etiquetas:
        ruta_etiquetas = os.path.join(dir_modelo, "label_mapping.json")
    return ruta_etiquetas


def elegir_dispositivo(pedido, hay_cuda):
    """'auto' no le pregunta nada al usuario: GPU si la hay, CPU si no.

    Se separa de torch a propósito, para poder probarla sin torch instalado.
    """
    if pedido == "cpu":
        return "cpu"
    if pedido == "cuda":
        if not hay_cuda:
            sys.exit("Pediste --dispositivo cuda y torch no ve ninguna GPU. "
                     "Quita el flag para que caiga solo a CPU (alrededor de una "
                     "hora para cien mil pares) o revisa la instalación de CUDA.")
        return "cuda"
    return "cuda" if hay_cuda else "cpu"


# ---------------------------------------------------------------- la entrada

def leer_jsonl(ruta, que_es="entrada"):
    """Generador de (número de línea, dict). Sale con 1 ante una línea rota."""
    if not os.path.exists(ruta):
        sys.exit("No encuentro %s (%s). Corre antes etapa2/extraer_pares.py."
                 % (ruta, que_es))
    with open(ruta, encoding="utf-8") as f:
        for n, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                yield n, json.loads(linea)
            except ValueError as e:
                sys.exit("%s, línea %d: no es JSON válido (%s)." % (ruta, n, e))


def validar_par(fila, n):
    """Devuelve el mensaje del problema, o None si la fila sirve.

    Se corre ANTES de cargar el modelo. Un marcado que no sea el del
    entrenamiento no falla en ninguna capa: el modelo devuelve probabilidades
    igual, y esas probabilidades son ruido con aspecto de resultado.
    """
    for clave in ("text", "id_par", "pmid", "tf", "target"):
        if clave not in fila:
            return "Fila %d de la entrada no trae la clave '%s'." % (n, clave)
    if not isinstance(fila["text"], str):
        return "Fila %d: 'text' no es una cadena." % n
    try:
        int(fila["pmid"])
    except (TypeError, ValueError):
        return "Fila %d: pmid %r no es un entero." % (n, fila["pmid"])
    marcas = sorted(m[0] for m in MARCADO.findall(fila["text"]))
    if marcas != ["1", "2"]:
        return ("Fila %d: el marcado no cumple el formato del entrenamiento. Se "
                "espera exactamente un '<e1> nombre </e1>' y un "
                "'<e2> nombre </e2>', con un espacio dentro de cada etiqueta y "
                "sin espacios en el nombre. Ver sección 3.1 del contrato. "
                "text=%r" % (n, fila["text"][:120]))
    return None


def leer_etiquetados(ruta, que_es):
    """Filas con 'label', para --control y --calibrar."""
    filas = []
    for n, fila in leer_jsonl(ruta, que_es):
        if "text" not in fila or "label" not in fila:
            sys.exit("%s, línea %d: %s tiene que traer 'text' y 'label'."
                     % (ruta, n, que_es))
        if fila["label"] not in ETIQUETAS_ESPERADAS:
            sys.exit("%s, línea %d: la etiqueta %r no es una de las cuatro."
                     % (ruta, n, fila["label"]))
        filas.append(fila)
    if not filas:
        sys.exit("%s no tiene ninguna fila." % ruta)
    return filas


# ------------------------------------------------------------- reanudación

def sanear_parcial(ruta):
    """Deja el .parcial en la última línea completa y devuelve (ids, sobrantes).

    Una muerte por señal parte la última línea a la mitad. Si se reanudara sin
    cortarla, el archivo tendría un JSON roto en medio y la unión por id_par de
    la etapa 4 fallaría mucho después, lejos de la causa. Se trabaja en bytes
    porque los offsets de un archivo UTF-8 no son offsets de caracteres.
    """
    if not os.path.exists(ruta):
        return [], 0
    with open(ruta, "rb") as f:
        datos = f.read()
    ids = []
    pos = 0
    corte = 0
    while True:
        fin = datos.find(b"\n", pos)
        if fin < 0:
            break
        linea = datos[pos:fin]
        if linea.strip():
            try:
                ids.append(json.loads(linea.decode("utf-8"))["id_par"])
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                break
        pos = fin + 1
        corte = pos
    sobrantes = datos[corte:]
    # La cola sin salto de línea final es la línea que quedó a medias, y cuenta
    # como una más. Sumar 1 por cualquier resto no vacío contaba de más cuando
    # lo que sobraba eran líneas enteras que empezaban con una rota.
    n_sobrantes = sobrantes.count(b"\n")
    if sobrantes.rsplit(b"\n", 1)[-1].strip():
        n_sobrantes += 1
    if sobrantes:
        with open(ruta, "r+b") as f:
            f.truncate(corte)
    return ids, n_sobrantes


def comprobar_prefijo(hechos, ids_entrada):
    """El .parcial tiene que ser el principio exacto de esta entrada.

    Si no lo es, se produjo con otro pares.jsonl, y continuar mezclaría dos
    corridas en un archivo que después se une por id_par sin sospechar nada.
    """
    if len(hechos) > len(ids_entrada):
        return ("El archivo a medias tiene %d predicciones y la entrada solo %d "
                "candidatos: no salieron del mismo pares.jsonl."
                % (len(hechos), len(ids_entrada)))
    for i, (a, b) in enumerate(zip(hechos, ids_entrada)):
        if a != b:
            return ("El archivo a medias se desvía de la entrada en la posición "
                    "%d (dice %s, la entrada dice %s): se produjo con otro "
                    "pares.jsonl. Bórralo o vuelve a extraer los pares."
                    % (i + 1, a, b))
    return None


# ------------------------------------------------------------------ salida

def fila_salida(par, etiquetas, probs):
    """Una línea de predicciones.jsonl, con las claves en el orden del contrato.

    `probs` viene en el orden de los logits, o sea el de `etiquetas`. Las
    columnas p_* se escriben por NOMBRE: así el archivo es estable aunque el
    checkpoint use otro orden interno.
    """
    por_nombre = dict(zip(etiquetas, probs))
    # El argmax se hace en Python, no en torch: ante un empate gana el índice
    # menor y la salida es la misma en CPU y en GPU.
    mejor = max(range(len(probs)), key=lambda i: probs[i])
    d = {
        "id_par": par["id_par"],
        "pmid": int(par["pmid"]),
        "tf": par["tf"],
        "target": par["target"],
        "prediccion": etiquetas[mejor],
    }
    for nombre in ETIQUETAS_ESPERADAS:
        d["p_" + nombre] = round(por_nombre[nombre], 6)
    d["seccion"] = par.get("seccion", "")
    d["fuente"] = par.get("fuente", "")
    d["autorregulacion"] = bool(par.get("autorregulacion", False))
    d["redaccion"] = par.get("redaccion", "")
    return d


def verificar_salida(ruta, ids_entrada, exigir_variedad=None):
    """Las invariantes de la sección 4 del contrato. Lista vacía = todo bien.

    Se corre sobre el archivo ya escrito, no sobre lo que quedó en memoria: lo
    que hay que defender es el archivo.
    """
    problemas = []
    ids = []
    predicciones = []
    with open(ruta, encoding="utf-8") as f:
        for n, linea in enumerate(f, 1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                d = json.loads(linea)
            except ValueError:
                problemas.append("Línea %d de la salida ilegible." % n)
                return problemas
            # El orden de las claves es parte del contrato, no cosmética: al
            # reanudar, la cabeza del archivo la escribió otra corrida, que
            # pudo ser de otra versión de este script.
            if list(d.keys()) != CLAVES_SALIDA:
                problemas.append("Fila %d no tiene las claves del contrato en "
                                 "su orden: %r." % (n, list(d.keys())))
                return problemas
            ids.append(d.get("id_par"))
            predicciones.append(d.get("prediccion"))
            suma = sum(float(d.get("p_" + e, 0.0)) for e in ETIQUETAS_ESPERADAS)
            if abs(suma - 1.0) > 1e-3:
                problemas.append("Fila %d: las probabilidades suman %.6f, no 1. "
                                 "Revisa el softmax." % (n, suma))

    if len(ids) != len(ids_entrada):
        problemas.append("Escribí %d predicciones para %d candidatos. La unión "
                         "por id_par no sería fiable."
                         % (len(ids), len(ids_entrada)))
    if set(ids) != set(ids_entrada):
        faltan = len(set(ids_entrada) - set(ids))
        sobran = len(set(ids) - set(ids_entrada))
        problemas.append("Los id_par de salida no coinciden con los de entrada "
                         "(faltan %d, sobran %d)." % (faltan, sobran))

    if exigir_variedad is None:
        exigir_variedad = len(predicciones) >= MINIMO_PARA_EXIGIR_VARIEDAD
    if exigir_variedad and predicciones and len(set(predicciones)) == 1:
        problemas.append("Las %d predicciones son todas '%s'. Eso no es un "
                         "resultado, es un modelo mal cargado."
                         % (len(predicciones), predicciones[0]))
    return problemas


# ------------------------------------------------------------- calibración

def umbral_optimo(observaciones, clase):
    """Umbral de `clase` que maximiza su F1, y ese F1.

    `observaciones` son ternas (probabilidades_por_nombre, predicción, verdad).
    Se cuenta como positivo lo que el modelo YA predice como esa clase y además
    llega al umbral, que es exactamente lo que hará red.py.

    Ante un empate de F1 gana el umbral menor: entre dos cortes que miden igual,
    el que deja pasar más evidencia. Y sobre todo, gana siempre el mismo, que es
    lo que hace reproducible el archivo.
    """
    verdaderos = sum(1 for _, _, y in observaciones if y == clase)
    candidatos = sorted({p[clase] for p, pred, _ in observaciones if pred == clase})
    if not candidatos:
        return None, 0.0, verdaderos
    mejor_umbral, mejor_f1 = candidatos[0], -1.0
    for t in candidatos:
        vp = fp = 0
        for p, pred, y in observaciones:
            if pred == clase and p[clase] >= t:
                if y == clase:
                    vp += 1
                else:
                    fp += 1
        if vp == 0:
            f1 = 0.0
        else:
            precision = vp / float(vp + fp)
            exhaustividad = vp / float(verdaderos) if verdaderos else 0.0
            f1 = (0.0 if precision + exhaustividad == 0 else
                  2 * precision * exhaustividad / (precision + exhaustividad))
        if f1 > mejor_f1:
            mejor_umbral, mejor_f1 = t, f1
    return mejor_umbral, mejor_f1, verdaderos


def calibrar(observaciones, ruta_origen):
    """El JSON de umbrales sugeridos que lee red.py --umbrales.

    El único conjunto legítimo es el dev de la repartición sin fuga que produce
    particionar.py --por pmid, o sea E. coli. Calibrar sobre el patrón de oro o
    sobre las oraciones de la auditoría de signo convierte la evaluación en
    ajuste y está prohibido por el contrato: los números de las etapas 5 y 6
    dejarían de significar nada.
    """
    # Los tres van anidados bajo "umbrales" y con el nombre de la clase, que es
    # como los lee red.py --umbrales. La cuarta clase (no_relation) no lleva
    # umbral: red.py descarta esas filas antes de mirar ninguna probabilidad.
    umbrales = {}
    detalle = {}
    for clase in ETIQUETAS_ESPERADAS:
        umbral, f1, verdaderos = umbral_optimo(observaciones, clase)
        sin_datos = umbral is None
        if sin_datos:
            umbral = UMBRALES_POR_OMISION.get(clase)
        detalle[clase] = {"umbral": None if umbral is None else round(umbral, 6),
                          "f1": round(f1, 4),
                          "n_verdaderas": verdaderos,
                          "sin_datos": sin_datos}
        if clase in UMBRALES_POR_OMISION:
            umbrales[clase] = round(umbral, 6)
    aciertos = sum(1 for _, pred, y in observaciones if pred == y)
    salida = {"umbrales": umbrales}
    salida["calibrado_en"] = os.path.abspath(ruta_origen)
    salida["n"] = len(observaciones)
    salida["exactitud"] = round(aciertos / float(len(observaciones)), 4)
    salida["por_clase"] = detalle
    salida["aviso"] = ("Umbrales calibrados sobre un conjunto etiquetado ajeno a "
                       "la evaluación. Calibrarlos contra el patrón de oro o "
                       "contra las oraciones de auditoría convertiría la "
                       "evaluación en ajuste, y está prohibido por el contrato.")
    salida["fecha"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return salida


# ------------------------------------------------------- torch y el modelo

def cargar_modelo(dir_modelo, dispositivo, etiquetas):
    """Tokenizador y modelo, en eval() y sobre el dispositivo elegido."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(dir_modelo)
    modelo = AutoModelForSequenceClassification.from_pretrained(dir_modelo)
    n = int(getattr(modelo.config, "num_labels", 0))
    if n != len(etiquetas):
        sys.exit("El checkpoint tiene %d salidas y el mapa de etiquetas trae %d. "
                 "No son el mismo modelo." % (n, len(etiquetas)))
    modelo.eval()
    modelo.to(dispositivo)
    return tok, modelo


def comprobar_tokenizador(tok):
    """Los marcadores tienen que sobrevivir al tokenizador.

    En el entrenamiento <e1> no es token especial: se parte en <, e, ##1, >. Si
    aquí saliera [UNK], o si alguien los hubiera añadido al vocabulario, las
    piezas serían otras y el modelo estaría leyendo algo que nunca vio.
    """
    piezas = tok.tokenize("<e1> IHF </e1>")
    unk = getattr(tok, "unk_token", None)
    if not piezas or (unk is not None and unk in piezas):
        sys.exit("El tokenizador convierte <e1> en [UNK]: el formato de marcado "
                 "no coincide con el del entrenamiento.")
    especiales = set(getattr(tok, "all_special_tokens", None) or [])
    if "<e1>" in especiales or "<e2>" in especiales:
        sys.exit("Este tokenizador trae <e1>/<e2> como tokens especiales y el "
                 "del entrenamiento no. Las piezas son otras, así que las "
                 "probabilidades no serían comparables con las del barrido.")
    return piezas


def probabilidades(textos, tok, modelo, dispositivo, max_length):
    """Una pasada hacia adelante sobre un lote. Devuelve listas de 4 flotantes."""
    import torch

    cod = tok(textos, padding=True, truncation=True, max_length=max_length,
              return_tensors="pt")
    cod = {k: v.to(dispositivo) for k, v in cod.items()}
    # El softmax va DENTRO del no_grad(), no después: así ninguna operación de
    # esta función construye grafo, ni siquiera la que solo normaliza.
    with torch.no_grad():
        logits = modelo(**cod).logits
        probs = torch.softmax(logits.float(), dim=-1)
    return probs.cpu().tolist()


def en_lotes(secuencia, tam):
    lote = []
    for x in secuencia:
        lote.append(x)
        if len(lote) >= tam:
            yield lote
            lote = []
    if lote:
        yield lote


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Clasifica los pares candidatos con el BioBERT afinado.")
    ap.add_argument("--modelo", help="Carpeta del checkpoint afinado.")
    ap.add_argument("--etiquetas",
                    help="label_mapping.json, si no está junto al checkpoint.")
    ap.add_argument("--entrada",
                    default=os.path.join("datos_etapa2", "pares.jsonl"))
    ap.add_argument("--salida",
                    default=os.path.join("datos_etapa2", "predicciones.jsonl"))
    ap.add_argument("--meta",
                    default=os.path.join("datos_etapa2", "predicciones_meta.json"))
    ap.add_argument("--lote", type=int, default=32)
    ap.add_argument("--max_length", type=int, default=512)
    ap.add_argument("--dispositivo", default="auto",
                    choices=["auto", "cpu", "cuda"])
    ap.add_argument("--control", help="jsonl etiquetado de control (cordura).")
    ap.add_argument("--calibrar",
                    help="jsonl etiquetado de dev: escribe umbrales y termina.")
    ap.add_argument("--umbrales-salida", dest="umbrales_salida",
                    default=os.path.join("datos_etapa2", "umbrales_sugeridos.json"))
    ap.add_argument("--reanudar", action="store_true",
                    help="Continúa la corrida a medias de <salida>.parcial.")
    ap.add_argument("--limite", type=int, help="Solo para depurar.")
    ap.add_argument("--avance", type=int, default=2000,
                    help="Cada cuántos pares se imprime el avance.")
    args = ap.parse_args()

    if args.lote < 1:
        sys.exit("--lote tiene que ser 1 o más.")

    # 1. El checkpoint y el orden de las etiquetas, antes que nada.
    ruta_etiquetas = exigir_modelo(args.modelo, args.etiquetas)
    ruta_config = os.path.join(args.modelo, "config.json")
    etiquetas = leer_etiquetas(ruta_etiquetas, ruta_config)
    print("Etiquetas (orden de los logits, leído de %s):" % ruta_etiquetas,
          flush=True)
    for i, e in enumerate(etiquetas):
        print("  %d  %s" % (i, e), flush=True)

    dlc = leer_do_lower_case(args.modelo)
    if dlc is True:
        print("AVISO: el tokenizador trae do_lower_case=true pese a ser un "
              "checkpoint cased. 'lasR' y 'LasR' se colapsan, así que la "
              "mayúscula que distingue proteína de gen es ruido para el modelo.",
              flush=True)
    elif dlc is False:
        print("do_lower_case=false: la mayúscula es señal. Las menciones de TF "
              "en minúscula que cuenta el informe de la etapa 2 quedan fuera de "
              "distribución.", flush=True)
    else:
        print("AVISO: el tokenizador no declara do_lower_case. Sin ese dato no "
              "se sabe si la mayúscula de LasR es señal o ruido.", flush=True)

    modo_calibrar = bool(args.calibrar)

    # 2. La entrada, validada antes de cargar 433 MB de pesos.
    ids_entrada = []
    if not modo_calibrar:
        leidas = 0
        for n, fila in leer_jsonl(args.entrada, "pares candidatos"):
            problema = validar_par(fila, n)
            if problema:
                sys.exit(problema)
            ids_entrada.append(fila["id_par"])
            leidas += 1
            if args.limite and leidas >= args.limite:
                break
        if not ids_entrada:
            sys.exit("%s no tiene ningún candidato." % args.entrada)
        if len(set(ids_entrada)) != len(ids_entrada):
            sys.exit("id_par repetido en la entrada: %d filas y %d id_par "
                     "distintos. La unión con la etapa 4 no sería fiable."
                     % (len(ids_entrada), len(set(ids_entrada))))
        print("\n%d candidatos en %s." % (len(ids_entrada), args.entrada),
              flush=True)

    # 3. La reanudación se decide antes de cargar el modelo, para que negarse
    #    cueste un segundo y no un minuto.
    ruta_parcial = args.salida + ".parcial"
    hechos = []
    if not modo_calibrar:
        if (args.reanudar and not os.path.exists(ruta_parcial)
                and os.path.exists(args.salida)):
            # Una corrida que llegó al final deja el nombre definitivo. Se
            # adopta como parcial en vez de copiarlo: son decenas de MB.
            os.replace(args.salida, ruta_parcial)
            print("Adopto %s como punto de partida." % args.salida, flush=True)
        if os.path.exists(ruta_parcial):
            hechos, sobrantes = sanear_parcial(ruta_parcial)
            if not hechos and os.path.getsize(ruta_parcial) == 0:
                # Un .parcial vacío es una corrida que murió antes del primer
                # lote: no hay ninguna predicción que proteger, así que exigir
                # --reanudar para poder seguir sería puro estorbo.
                os.remove(ruta_parcial)
            elif not args.reanudar:
                sys.exit("Hay una corrida a medias en %s, con %d predicciones. "
                         "No la piso solo: vuelve a lanzar con --reanudar para "
                         "continuar, o borra ese archivo para empezar de cero."
                         % (ruta_parcial, len(hechos)))
            else:
                if sobrantes:
                    print("Descarto %d línea(s) a medias del final de %s."
                          % (sobrantes, ruta_parcial), flush=True)
                problema = comprobar_prefijo(hechos, ids_entrada)
                if problema:
                    # Se nombra el archivo: si venía de adoptar una salida ya
                    # completa, ahora se llama .parcial y hay que poder
                    # encontrarlo. Su contenido está intacto.
                    sys.exit("%s\nEl archivo en cuestión es %s."
                             % (problema, ruta_parcial))
                print("Reanudo: ya estaban %d de %d."
                      % (len(hechos), len(ids_entrada)), flush=True)
            if not os.path.exists(ruta_parcial):
                hechos = []

    pendientes = len(ids_entrada) - len(hechos)

    # 4. El modelo.
    import torch
    import transformers

    dispositivo = elegir_dispositivo(args.dispositivo, torch.cuda.is_available())
    print("\nDispositivo: %s  (torch %s, transformers %s)"
          % (dispositivo, torch.__version__, transformers.__version__), flush=True)
    print("Cargando %s ..." % args.modelo, flush=True)
    t0 = time.time()
    tok, modelo = cargar_modelo(args.modelo, dispositivo, etiquetas)
    comprobar_tokenizador(tok)
    print("Cargado en %s." % formato_tiempo(time.time() - t0), flush=True)

    # El id2label del objeto cargado tiene que decir lo mismo que
    # label_mapping.json. Es la tercera copia del mismo dato y la única que el
    # modelo usa de verdad.
    crudo = getattr(modelo.config, "id2label", None)
    del_modelo = (normalizar_etiquetas({str(k): v for k, v in crudo.items()})
                  if isinstance(crudo, dict) else None)
    if del_modelo is not None and del_modelo != etiquetas:
        sys.exit("El modelo cargado declara id2label=%r y label_mapping.json "
                 "dice %r. Las predicciones no serían de fiar."
                 % (del_modelo, etiquetas))

    # 5. Control de cordura.
    exactitud_control = None
    if args.control:
        filas = leer_etiquetados(args.control, "conjunto de control")
        aciertos = 0
        for lote in en_lotes(filas, args.lote):
            probs = probabilidades([f["text"] for f in lote], tok, modelo,
                                   dispositivo, args.max_length)
            for fila, p in zip(lote, probs):
                mejor = max(range(len(p)), key=lambda i: p[i])
                if etiquetas[mejor] == fila["label"]:
                    aciertos += 1
        exactitud_control = aciertos / float(len(filas))
        print("Control: exactitud %.4f sobre %d filas de %s"
              % (exactitud_control, len(filas), args.control), flush=True)
        if exactitud_control < EXACTITUD_MINIMA_CONTROL:
            sys.exit("El checkpoint no reproduce el conjunto de control "
                     "(exactitud %.4f). Algo está mal cargado; no gasto una "
                     "hora de CPU para producir ruido." % exactitud_control)

    # 6. Calibración: mide, escribe los umbrales y termina.
    if modo_calibrar:
        filas = leer_etiquetados(args.calibrar, "conjunto de calibración")
        observaciones = []
        for lote in en_lotes(filas, args.lote):
            probs = probabilidades([f["text"] for f in lote], tok, modelo,
                                   dispositivo, args.max_length)
            for fila, p in zip(lote, probs):
                por_nombre = dict(zip(etiquetas, p))
                mejor = max(range(len(p)), key=lambda i: p[i])
                observaciones.append((por_nombre, etiquetas[mejor], fila["label"]))
        sugeridos = calibrar(observaciones, args.calibrar)
        escribir_json(args.umbrales_salida, sugeridos)
        print("\nUmbrales sugeridos, en %s" % args.umbrales_salida, flush=True)
        for clase in ("activates", "represses", "regulates"):
            print("  %-12s %.4f  (F1 %.4f)"
                  % (clase, sugeridos["umbrales"][clase],
                     sugeridos["por_clase"][clase]["f1"]), flush=True)
        print("Solo sirven para red.py --umbrales. No se calibra contra el "
              "patrón de oro ni contra las oraciones de auditoría: eso "
              "convertiría la evaluación en ajuste.", flush=True)
        return 0

    # 7. La corrida.
    print("\nQuedan %d pares por clasificar, en lotes de %d."
          % (pendientes, args.lote), flush=True)
    carpeta = os.path.dirname(os.path.abspath(ruta_parcial))
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    def por_hacer():
        """Los candidatos que faltan, en el orden de la entrada.

        Se salta por posición, no por pertenencia a un conjunto de id_par: el
        prefijo ya se comprobó, y así la memoria no crece con el corpus.
        """
        saltar = len(hechos)
        vistos = 0
        for _, fila in leer_jsonl(args.entrada, "pares candidatos"):
            vistos += 1
            if args.limite and vistos > args.limite:
                break
            if vistos <= saltar:
                continue
            yield fila

    t0 = time.time()
    ultimo_aviso = t0
    nuevos = 0
    # newline="\n" a propósito: en Windows el modo texto escribiría \r\n y el
    # contrato pide LF.
    with open(ruta_parcial, "a", encoding="utf-8", newline="\n") as f:
        for lote in en_lotes(por_hacer(), args.lote):
            probs = probabilidades([p["text"] for p in lote], tok, modelo,
                                   dispositivo, args.max_length)
            for par, p in zip(lote, probs):
                f.write(json.dumps(fila_salida(par, etiquetas, p),
                                   ensure_ascii=False) + "\n")
            # Vaciar en cada lote es lo que hace reanudable la corrida. Con el
            # buffer por omisión, una muerte por señal se lleva hasta 8 KB de
            # predicciones que ya estaban calculadas.
            f.flush()
            os.fsync(f.fileno())
            nuevos += len(lote)
            ahora = time.time()
            if (nuevos % args.avance) < args.lote or ahora - ultimo_aviso > 30:
                ritmo = nuevos / max(ahora - t0, 1e-9)
                print("  %d/%d  (%.1f%%)  %.1f pares/s  faltan ~%s"
                      % (len(hechos) + nuevos, len(ids_entrada),
                         100.0 * (len(hechos) + nuevos) / len(ids_entrada),
                         ritmo,
                         formato_tiempo((pendientes - nuevos) / ritmo if ritmo
                                        else 0)),
                      flush=True)
                ultimo_aviso = ahora

    dt = time.time() - t0
    print("\n%d pares clasificados en %s." % (nuevos, formato_tiempo(dt)),
          flush=True)

    # 8. Las invariantes, sobre el archivo escrito y antes de darle el nombre
    #    definitivo. Un predicciones.jsonl que no las cumpla no debe existir.
    problemas = verificar_salida(ruta_parcial, ids_entrada)
    if problemas:
        print("\nNo escribo %s. El trabajo queda en %s."
              % (args.salida, ruta_parcial), flush=True)
        for p in problemas:
            print("  " + p, flush=True)
        return 1

    os.replace(ruta_parcial, args.salida)

    # n_salida se cuenta sobre el archivo final, no se copia de n_entrada: son
    # dos números que tienen que salir iguales, y darlos por iguales es
    # justamente lo que la invariante quiere impedir.
    reparto = {}
    n_salida = 0
    with open(args.salida, encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                clase = json.loads(linea)["prediccion"]
                reparto[clase] = reparto.get(clase, 0) + 1
                n_salida += 1

    escribir_json(args.meta, {
        "modelo": os.path.abspath(args.modelo),
        "sha1_config": sha1_de(ruta_config),
        "etiquetas_de": os.path.abspath(ruta_etiquetas),
        "id2label": {str(i): e for i, e in enumerate(etiquetas)},
        "do_lower_case": dlc,
        "max_length": args.max_length,
        "lote": args.lote,
        "transformers": transformers.__version__,
        "torch": torch.__version__,
        "dispositivo": dispositivo,
        "n_entrada": len(ids_entrada),
        "n_salida": n_salida,
        "reparto": reparto,
        "exactitud_control": (None if exactitud_control is None
                              else round(exactitud_control, 4)),
        "segundos": round(dt, 1),
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })

    print("Escritos %s y %s." % (args.salida, args.meta), flush=True)
    for clase in ETIQUETAS_ESPERADAS:
        n = reparto.get(clase, 0)
        print("  %-12s %6d  (%.1f%%)"
              % (clase, n, 100.0 * n / len(ids_entrada)), flush=True)
    print("\nEste script no aplica umbrales ni decide aristas. Eso es red.py.",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
