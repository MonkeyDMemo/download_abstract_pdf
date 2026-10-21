"""El script de entrenamiento del asesor, sin pesos de clase.

`etapa2/barrido.py` (congelado) le pasa siempre `--use_class_weights`, y el
script pondera la pérdida por la inversa de la frecuencia en train. En la
curada v1 eso sesgó el modelo hacia `represses`, la clase más chica: en la red
de la corrida 4, 744 de 1 025 aristas salieron como represión (enmienda 1 del
protocolo). Este envoltorio quita ese flag y ejecuta el script real, que llega
en `GRN_SCRIPT_REAL`: la pérdida queda como entropía cruzada sin ponderar.

`reentrenar --sin-pesos-de-clase` lo pone en lugar del script. Se reemplaza a sí
mismo con `os.execv`, así que el PID es el mismo y el tope y `detener` lo
alcanzan igual que al script.
"""

import os
import sys

VARIABLE = "GRN_SCRIPT_REAL"
FLAG = "--use_class_weights"


def argumentos(argv):
    """Los argumentos para el script real: los mismos, sin el de los pesos."""
    return [a for a in argv if a != FLAG]


def main(argv=None):
    real = os.environ.get(VARIABLE)
    if not real or not os.path.isfile(real):
        sys.exit("sin_pesos.py: falta %s con la ruta del script de "
                 "entrenamiento." % VARIABLE)
    resto = argumentos(sys.argv[1:] if argv is None else argv)
    os.execv(sys.executable, [sys.executable, "-u", real] + resto)


if __name__ == "__main__":
    main()
