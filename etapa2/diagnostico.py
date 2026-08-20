#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostico del entorno de Colab antes de gastar GPU.

Existe porque un barrido de 24 corridas murio 24 veces con SIGSEGV en cuatro
minutos, y lo unico que quedaba de cada una era el numero -11. Un numero no
dice en que linea fue.

Hace tres cosas, y las tres acaban en la bitacora:

1. **Anota que versiones hay de verdad, incluidas las que nadie fijo.** Al
   fijar numpy 1.26 se fijaron tambien pandas y datasets, pero pyarrow,
   tokenizers, triton y el propio torch entraron por debajo sin que pip
   dijera nada. La primera vez el culpable fue triton, que nadie habia
   pedido y que torch importa solo al construir el optimizador; las
   sospechas sobre pyarrow y pandas resultaron falsas, y estan aqui las dos
   versiones para no volver a sospechar a ciegas.
2. **Corre el script de entrenamiento de verdad**, sobre 40 ejemplos y una
   epoca, con dos variables de entorno que valen mas que cualquier sonda:
   PYTHONFAULTHANDLER convierte la senal en un traceback de Python, y
   CUDA_LAUNCH_BLOCKING hace que un fallo de kernel salga en la linea que lo
   lanzo y no cinco llamadas despues.
3. **Escribe todo a un archivo**, no solo a la pantalla. Una celda de Colab
   que se desconecta se lleva su salida; un archivo en Drive no. Y el hijo se
   lanza con -u: sin eso, su ultimo bloque de stdout se pierde justo cuando
   mas hace falta, y el diagnostico apunta a donde no fue.

Uso:

    python diagnostico.py --datos limpia_por_pmid \\
        --bitacora /content/drive/MyDrive/pseudomonas-trn/diagnostico.log
"""

import argparse
import os
import shutil
import subprocess
import sys

ARCHIVOS = ("entity_marked_train.jsonl", "entity_marked_dev.jsonl",
            "entity_marked_test.jsonl")

# En subproceso, siempre: lo que importa es que hay en el disco, no que quedo
# en la memoria del proceso que corre esto.
VERSIONES = r'''
import sys
print("python           %s" % sys.version.split()[0])
for m in ("numpy", "pandas", "pyarrow", "torch", "transformers", "datasets",
          "accelerate", "tokenizers", "huggingface_hub", "sklearn"):
    try:
        mod = __import__(m)
        print("%-16s %s" % (m, getattr(mod, "__version__", "?")))
    except Exception as e:
        print("%-16s NO IMPORTA: %s" % (m, e))
try:
    import torch
    print("torch.version.cuda %s" % torch.version.cuda)
    print("gpu              %s" % (torch.cuda.get_device_name(0)
                                   if torch.cuda.is_available() else "no hay"))
except Exception as e:
    print("torch/cuda NO: %s" % e)
'''


def muestra(datos, destino):
    """Recorta la particion a algo que entrene en dos minutos.

    A saltos y no los primeros N: el corpus viene agrupado por articulo, asi
    que los primeros ejemplos suelen ser del mismo PMID y de la misma clase, y
    una prueba con una sola clase no ejerce los pesos por clase.
    """
    os.makedirs(destino, exist_ok=True)
    for nombre, cuantos in zip(ARCHIVOS, (40, 16, 16)):
        with open(os.path.join(datos, nombre), encoding="utf-8") as f:
            lineas = f.readlines()
        paso = max(1, len(lineas) // cuantos)
        with open(os.path.join(destino, nombre), "w", encoding="utf-8") as f:
            f.writelines(lineas[::paso][:cuantos])
    shutil.copy(os.path.join(datos, "label_mapping.json"), destino)


def correr(cmd, entorno=None):
    """Devuelve (codigo, salida). Junta stdout y stderr en el orden que salen."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          env=entorno)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--datos", default="limpia_por_pmid")
    ap.add_argument("--script", default="bio_bert_re_finetune.py")
    ap.add_argument("--bitacora", required=True,
                    help="Donde se escribe todo. En Drive, para que sobreviva "
                         "a la desconexion de la sesion.")
    ap.add_argument("--trabajo", default="/content/_diagnostico",
                    help="Disco LOCAL para los pesos de la prueba. Nunca Drive.")
    args = ap.parse_args()

    for n in ARCHIVOS + ("label_mapping.json",):
        if not os.path.exists(os.path.join(args.datos, n)):
            sys.exit("Falta %s. Corre antes particionar.py, y comprueba que "
                     "estas en la carpeta de trabajo." % os.path.join(args.datos, n))
    if not os.path.exists(args.script):
        sys.exit("Falta %s en %s." % (args.script, os.getcwd()))

    partes = []

    def anotar(titulo, texto):
        partes.append("===== %s =====\n%s" % (titulo, texto))
        print("\n===== %s =====" % titulo, flush=True)
        print(texto, flush=True)

    anotar("DONDE", "cwd      %s\nejecutable %s\ndatos    %s"
           % (os.getcwd(), sys.executable, os.path.abspath(args.datos)))

    codigo, texto = correr([sys.executable, "-u", "-c", VERSIONES])
    anotar("VERSIONES (codigo %d)" % codigo, texto)

    shutil.rmtree(args.trabajo, ignore_errors=True)
    muestra(args.datos, os.path.join(args.trabajo, "datos"))

    datos = os.path.join(args.trabajo, "datos")
    cmd = [sys.executable, "-u", args.script,
           "--train_jsonl", os.path.join(datos, ARCHIVOS[0]),
           "--dev_jsonl", os.path.join(datos, ARCHIVOS[1]),
           "--test_jsonl", os.path.join(datos, ARCHIVOS[2]),
           "--labels_json", os.path.join(datos, "label_mapping.json"),
           "--out_dir", os.path.join(args.trabajo, "salida"),
           "--batch_size", "8", "--epochs", "1", "--max_length", "128",
           "--lr", "3e-5", "--warmup_ratio", "0.1", "--seed", "42",
           "--use_class_weights"]

    # PYTHONFAULTHANDLER: una senal deja traceback en vez de solo un numero.
    # CUDA_LAUNCH_BLOCKING: un fallo de kernel sale donde se lanzo. Cuesta
    # velocidad, y en una prueba de 40 ejemplos la velocidad no importa.
    entorno = dict(os.environ, PYTHONFAULTHANDLER="1", CUDA_LAUNCH_BLOCKING="1")
    codigo, texto = correr(cmd, entorno)
    anotar("PRUEBA DE HUMO (codigo %d)" % codigo, texto)

    if codigo < 0:
        anotar("LECTURA", "Codigo %d: el proceso murio de la senal %d. Con "
                          "faulthandler puesto, el traceback de arriba dice en "
                          "que linea estaba." % (codigo, -codigo))
    elif codigo:
        anotar("LECTURA", "Codigo %d: excepcion de Python, no senal." % codigo)
    else:
        anotar("LECTURA", "La prueba de humo paso: este entorno entrena. Si "
                          "aun asi el barrido cae, la diferencia esta en la "
                          "escala (lote 16/32, ventana 512) y no en la pila.")

    shutil.rmtree(args.trabajo, ignore_errors=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.bitacora)), exist_ok=True)
    with open(args.bitacora, "w", encoding="utf-8") as f:
        f.write("\n\n".join(partes) + "\n")
        f.flush()
        os.fsync(f.fileno())
    print("\nBitacora escrita en %s" % args.bitacora)
    return 0


if __name__ == "__main__":
    sys.exit(main())
