#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Corre el barrido de hiperparametros sobre una particion sin fuga.

Pensado para Colab, donde la sesion se cae. De ahi salen cuatro decisiones:

1. **Cada corrida guarda su resultado apenas termina**, en un archivo propio,
   escrito de forma atomica (temporal mas os.replace). Sin lo atomico, una
   muerte a media escritura dejaba un JSON truncado que contaba como "ya
   hecha" y ademas tumbaba el resumen para siempre.
2. **Se salta lo ya hecho, pero solo si es lo mismo.** Cada resultado lleva
   la huella de los datos con los que se produjo. Reusar --resultados con
   otra particion no salta nada: avisa y se niega.
3. **Los checkpoints van a disco local, no a Drive**, y se borran tanto si la
   corrida sale bien como si truena. Cada epoca escribe ~433 MB; una tanda de
   fallos por falta de memoria llenaba el disco y tumbaba las siguientes.
4. **Un barrido incompleto no se presenta como completo.** Si falta una
   corrida, el resumen lo dice y no imprime ganadora.

No reimplementa el entrenamiento: invoca bio_bert_re_finetune.py tal como lo
hacia run_sweep_biobert.sh en el servidor. Cambiarlo alteraria el experimento
que se quiere comparar.

Uso tipico en Colab:

    python etapa2/barrido.py \
        --datos      datos_etapa2/por_pmid \
        --script     bio_bert_re_finetune.py \
        --trabajo    /content/runs \
        --resultados /content/drive/MyDrive/pseudomonas-trn/barrido_por_pmid
"""

import argparse
import csv
import glob
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import time

# La rejilla exacta de run_sweep_biobert.sh, con el mismo orden de bucles:
# lr por fuera, luego epocas, luego lote, y el calentamiento por dentro. El
# comentario del .sh dice "12 corridas" pero son 24; el comentario esta viejo.
#
# Los valores van como CADENA a proposito. Bash los escribia tal cual en el
# nombre de la carpeta ("lr3e-5"), y float("3e-5") formateado por Python da
# "3e-05". Guardarlos literales hace que run_22 de aqui se llame igual que
# run_22 del servidor, que es lo que permite comparar corrida contra corrida
# y no solo el mejor de cada barrido.
REJILLA = {
    "lr":      ["1e-5", "2e-5", "3e-5"],
    "epochs":  ["6", "8"],
    "batch":   ["16", "32"],
    "warmup":  ["0.06", "0.1"],
}

# Fijos en el .sh; se repiten aqui para que el experimento sea el mismo.
WEIGHT_DECAY = "0.01"
MAX_LENGTH = "512"
SEMILLA = "42"

ARCHIVOS = ("entity_marked_train.jsonl", "entity_marked_dev.jsonl",
            "entity_marked_test.jsonl")


def huella(datos):
    """Identifica la particion por su contenido, no por su ruta.

    Sin esto, la identidad de un resultado eran solo los cuatro
    hiperparametros: correr el barrido sobre otra particion con el mismo
    --resultados no entrenaba nada, imprimia "Ya estaban 24" y volvia a
    escribir el resumen con los numeros viejos como si fueran los nuevos.
    Justo el genero de error que esta correccion vino a eliminar: una cifra
    que no mide lo que su etiqueta dice.
    """
    h = hashlib.sha256()
    for n in ARCHIVOS:
        with open(os.path.join(datos, n), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def nombre_de(c):
    n = "run_%d_lr%s_ep%s_bs%s_wu%s" % (
        c["i"], c["lr"], c["epochs"], c["batch"], c["warmup"])
    # El .sh corria una sola semilla. Si se piden varias, el nombre lo dice;
    # con una sola se queda identico al del servidor.
    if c.get("semilla", SEMILLA) != SEMILLA:
        n += "_s%s" % c["semilla"]
    return n


def configuraciones(semillas):
    """Las 24, numeradas como las numeraba el .sh.

    El orden importa: run_22 tiene que ser lr3e-5_ep8_bs16_wu0.1, que es la
    que el servidor reporto como mejor.
    """
    llaves = ["lr", "epochs", "batch", "warmup"]
    for s in semillas:
        for i, vals in enumerate(itertools.product(*(REJILLA[k] for k in llaves)), 1):
            c = dict(zip(llaves, vals))
            c["i"] = i
            c["semilla"] = s
            yield c


def revisar_longitud(datos, modelo, max_length):
    """Comprueba que a 512 tokens no se trunque ningun ejemplo.

    Es solo diagnostico, y a proposito. En una version anterior este barrido
    bajaba max_length de 512 a la potencia de dos que cubriera el ejemplo mas
    largo, creyendo que aceleraba. No acelera nada: el script tokeniza SIN
    relleno y deja el relleno al DataCollatorWithPadding, que rellena hasta el
    mas largo de CADA LOTE. O sea que el costo ya es proporcional a la
    longitud real y max_length no interviene: lo unico que hace es marcar
    donde se corta. Bajarlo solo puede truncar evidencia.
    """
    try:
        from transformers import AutoTokenizer
    except ImportError:
        print("Sin transformers: me salto la revision de longitud.")
        return
    tok = AutoTokenizer.from_pretrained(modelo, use_fast=True)
    largos = []
    for nombre in ARCHIVOS:
        ruta = os.path.join(datos, nombre)
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                if linea.strip():
                    largos.append(len(tok(json.loads(linea)["text"])["input_ids"]))
    largos.sort()
    cortados = sum(1 for x in largos if x > int(max_length))
    print("Longitud en tokens: mediana=%d  p95=%d  max=%d  (techo %s)"
          % (largos[len(largos) // 2], largos[int(len(largos) * .95)],
             largos[-1], max_length))
    print("  %s" % ("AVISO: %d ejemplos se truncan y pierden texto." % cortados
                    if cortados else "Ninguno se trunca."))


def leer_metricas(directorio):
    r = {}
    for archivo, prefijo in (("eval_metrics.json", "dev"),
                             ("test_metrics.json", "test")):
        ruta = os.path.join(directorio, archivo)
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    r["%s_%s" % (prefijo, k.replace("eval_", ""))] = v
    return r


def guardar(ruta, obj):
    """Escritura atomica: temporal y despues os.replace.

    El archivo de resultado es tambien la marca de "esta corrida ya se hizo".
    Escrito directo, una desconexion a media escritura dejaba un JSON cortado
    que la reanudacion aceptaba como valido y que ademas hacia reventar el
    resumen en cada corrida posterior.
    """
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta)


def ya_hecha(destino, hue):
    """(saltar, motivo). Un JSON ilegible NO cuenta como hecha."""
    if not os.path.exists(destino):
        return False, None
    try:
        with open(destino, encoding="utf-8") as f:
            r = json.load(f)
    except ValueError:
        return False, "el JSON anterior estaba truncado; la repito"
    otra = r.get("huella")
    if otra and otra != hue:
        return None, ("se hizo con otra particion (huella %s, ahora %s)"
                      % (otra, hue))
    return True, None


COLUMNAS = ["nombre", "i", "lr", "epochs", "batch", "warmup", "semilla",
            "max_length", "dev_macro_f1", "dev_accuracy",
            "test_macro_f1", "test_accuracy", "segundos", "datos", "huella"]


def resumen(resultados, esperadas=None):
    filas, rotos = [], []
    for ruta in sorted(glob.glob(os.path.join(resultados, "*.json"))):
        if os.path.basename(ruta) == "resumen.json":
            continue
        try:
            with open(ruta, encoding="utf-8") as f:
                filas.append(json.load(f))
        except ValueError:
            rotos.append(os.path.basename(ruta))
    # Un .error cuyo .json existe es la marca de un intento anterior que
    # despues salio bien. Contarlo dejaba el barrido incompleto para siempre:
    # una corrida que fallo una vez y se rehizo seguia saliendo en FALLARON, y
    # con eso el barrido no volvia a anunciar ganadora nunca.
    fallidas = [os.path.basename(p)[:-11]
                for p in glob.glob(os.path.join(resultados, "*.json.error"))
                if not os.path.exists(p[:-len(".error")])]
    filas.sort(key=lambda r: r.get("dev_macro_f1") or 0, reverse=True)

    print("")
    if esperadas:
        print("%d de %d corridas completas." % (len(filas), esperadas))
    if fallidas:
        print("FALLARON %d: %s" % (len(fallidas), ", ".join(sorted(fallidas))))
    if rotos:
        print("ILEGIBLES %d: %s" % (len(rotos), ", ".join(rotos)))

    print("")
    print("%-30s %9s %9s %9s %9s" % ("corrida", "dev F1", "test F1",
                                     "dev acc", "test acc"))
    print("-" * 70)
    for r in filas:
        print("%-30s %9.4f %9.4f %9.4f %9.4f"
              % (r["nombre"],
                 r.get("dev_macro_f1") or 0, r.get("test_macro_f1") or 0,
                 r.get("dev_accuracy") or 0, r.get("test_accuracy") or 0))

    if filas:
        guardar(os.path.join(resultados, "resumen.json"), filas)
        with open(os.path.join(resultados, "resumen.csv"), "w",
                  encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
            w.writeheader()
            for r in filas:
                w.writerow(r)

    completo = not fallidas and not rotos and (
        esperadas is None or len(filas) == esperadas)
    if filas and completo:
        print("\nMejor: %s   dev %.4f / test %.4f"
              % (filas[0]["nombre"], filas[0].get("dev_macro_f1") or 0,
                 filas[0].get("test_macro_f1") or 0))
        print("Reportado en el servidor con la particion con fuga: "
              "dev 0.9024 / test 0.8721")
    elif filas:
        # No se anuncia ganadora de un barrido incompleto: si lo que fallo
        # fueron las 12 de lote 32, la conclusion sobre el tamano de lote
        # saldria de una rejilla que nunca lo probo.
        print("\nBarrido INCOMPLETO: no hay ganadora que reportar todavia.")
        print("Vuelve a lanzar el barrido; retoma solo lo que falta.")
    return filas


def main():
    ap = argparse.ArgumentParser(description="Barrido reanudable de BioBERT.")
    ap.add_argument("--datos", required=True,
                    help="Carpeta con entity_marked_{train,dev,test}.jsonl "
                         "y label_mapping.json")
    ap.add_argument("--script", default="bio_bert_re_finetune.py")
    ap.add_argument("--trabajo", default="runs",
                    help="Disco LOCAL para los checkpoints. Nunca Drive.")
    ap.add_argument("--resultados", required=True,
                    help="Donde sobreviven las metricas. Aqui si conviene Drive.")
    ap.add_argument("--modelo", default="dmis-lab/biobert-base-cased-v1.1")
    ap.add_argument("--max_length", default=MAX_LENGTH,
                    help="512, como el .sh. Solo es el techo de truncado: el "
                         "relleno lo hace el collator por lote, asi que bajarlo "
                         "no acelera, unicamente puede cortar texto.")
    ap.add_argument("--semillas", default=SEMILLA,
                    help="Lista separada por comas. El .sh usaba solo 42. Con "
                         "varias se puede dar el resultado con su dispersion, "
                         "que en fine-tuning de BERT sobre 1242 ejemplos es "
                         "del orden de la senal que el barrido mide.")
    ap.add_argument("--solo", type=int,
                    help="Correr una sola configuracion, por su numero de la "
                         "rejilla (1 a 24). Para la validacion cruzada, donde "
                         "correr las 24 en cada pliegue serian 120 corridas.")
    ap.add_argument("--conservar", action="store_true",
                    help="No borrar los checkpoints de cada corrida (come disco).")
    ap.add_argument("--solo_resumen", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.resultados, exist_ok=True)
    semillas = [s.strip() for s in args.semillas.split(",") if s.strip()]
    configs = list(configuraciones(semillas))
    if args.solo is not None:
        n_rejilla = len(configs) // len(semillas)
        if not 1 <= args.solo <= n_rejilla:
            sys.exit("--solo tiene que estar entre 1 y %d." % n_rejilla)
        configs = [c for c in configs if c["i"] == args.solo]

    if args.solo_resumen:
        resumen(args.resultados, len(configs))
        return 0

    for n in ARCHIVOS:
        r = os.path.join(args.datos, n)
        if not os.path.exists(r):
            # El caso realista: apuntar --datos a una particion de K pliegues.
            if os.path.exists(os.path.join(args.datos, "fold_0", n)):
                sys.exit("%s es una particion de varios pliegues. Apunta "
                         "--datos a una subcarpeta, por ejemplo %s/fold_0"
                         % (args.datos, args.datos.rstrip("/\\")))
            sys.exit("Falta %s. Corre antes etapa2/particionar.py" % r)
    etiquetas = os.path.join(args.datos, "label_mapping.json")
    if not os.path.exists(etiquetas):
        sys.exit("Falta %s: sin el, el script usa su LABELS_DEFAULT, que deja "
                 "'activates' en el id 0 pero intercambia 'represses' con "
                 "'no_relation'." % etiquetas)

    hue = huella(args.datos)
    print("Particion %s (huella %s)" % (args.datos, hue))
    revisar_longitud(args.datos, args.modelo, args.max_length)

    print("\n%d configuraciones (%d de la rejilla x %d semilla%s). Resultados "
          "en %s" % (len(configs), len(configs) // len(semillas), len(semillas),
                     "s" if len(semillas) > 1 else "", args.resultados))

    for i, c in enumerate(configs, 1):
        nombre = nombre_de(c)
        destino = os.path.join(args.resultados, nombre + ".json")
        saltar, motivo = ya_hecha(destino, hue)
        if saltar is None:
            sys.exit("\n%s %s.\nUsa un --resultados distinto para esta "
                     "particion, o borra la carpeta." % (nombre, motivo))
        if saltar:
            continue
        if motivo:
            print("  %s: %s" % (nombre, motivo))

        salida = os.path.join(args.trabajo, nombre)
        print("\n[%d/%d] %s" % (i, len(configs), nombre), flush=True)
        # -u: sin buffer. Con la salida del hijo almacenada en bloques, una
        # corrida que muere de una senal se lleva su ultimo bloque sin
        # escribirlo, y el diagnostico apunta a donde no fue.
        cmd = [sys.executable, "-u", args.script,
               "--train_jsonl", os.path.join(args.datos, ARCHIVOS[0]),
               "--dev_jsonl", os.path.join(args.datos, ARCHIVOS[1]),
               "--test_jsonl", os.path.join(args.datos, ARCHIVOS[2]),
               "--labels_json", etiquetas,
               "--out_dir", salida,
               "--model_name", args.modelo,
               "--batch_size", c["batch"],
               "--epochs", c["epochs"],
               "--lr", c["lr"],
               "--warmup_ratio", c["warmup"],
               "--weight_decay", WEIGHT_DECAY,
               "--max_length", str(args.max_length),
               "--seed", c["semilla"],
               "--use_class_weights",
               "--early_stopping", "--early_stopping_patience", "2"]

        # PYTHONFAULTHANDLER: si el hijo muere de una senal (SIGSEGV es -11),
        # imprime el traceback de Python de donde estaba. Sin esto, un fallo
        # asi solo deja el numero, y el numero no dice en que linea fue.
        entorno = dict(os.environ, PYTHONFAULTHANDLER="1")

        t0 = time.time()
        try:
            proc = subprocess.run(cmd, env=entorno)
            codigo = proc.returncode
        finally:
            # Se limpia pase lo que pase. Antes el borrado estaba despues del
            # 'continue' del camino de error, asi que cada fallo dejaba sus
            # checkpoints: doce fallos por falta de memoria llenaban el disco
            # y tumbaban las corridas que si habrian cabido.
            metricas = leer_metricas(salida)
            if not args.conservar:
                shutil.rmtree(salida, ignore_errors=True)

        dt = time.time() - t0
        if codigo != 0:
            # Una configuracion que truena no aborta el barrido: se anota y se
            # sigue. Mismo criterio que el ETL con un articulo que falla.
            print("  FALLO (codigo %d). Sigo con la siguiente." % codigo)
            guardar(destino + ".error",
                    {"nombre": nombre, "codigo": codigo, "huella": hue})
            continue

        r = {"nombre": nombre, "max_length": args.max_length,
             "segundos": round(dt, 1), "datos": os.path.abspath(args.datos),
             "huella": hue}
        r.update(c)
        r.update(metricas)
        guardar(destino, r)
        # La marca de fallo se va con la corrida que la produjo. Sin esto, el
        # .error de un intento viejo sobrevive al bueno en la misma carpeta de
        # Drive, que es la que se reusa al reanudar.
        if os.path.exists(destino + ".error"):
            os.remove(destino + ".error")
        print("  dev F1 %.4f  test F1 %.4f  (%.1f min)"
              % (r.get("dev_macro_f1") or 0, r.get("test_macro_f1") or 0,
                 dt / 60))

    resumen(args.resultados, len(configs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
