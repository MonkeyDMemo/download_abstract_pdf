"""El último paso de una escritura atómica: `os.replace`, que en Windows
aguanta a un lector momentáneo.

El flujo escribe cada salida a un `.tmp` y la pone en su lugar con
`os.replace`, para que un corte a media escritura no deje un archivo cortado
que parezca bueno. En Windows, `os.replace` falla con PermissionError mientras
otro proceso tiene abierto el destino, y el tablero los abre: lee
`estado.json` cada pocos segundos y sirve las salidas por bloques. El reemplazo
de `estado.json` va en un `finally` del flujo, así que un choque de
milisegundos con el sondeo abortaba la corrida entera.

Biblioteca estándar y Python 3.8.
"""

import os
import time

# Cuánto se aguanta a un lector antes de rendirse: el sondeo del tablero
# tiene el archivo abierto milisegundos; una descarga grande, algo más.
INTENTOS = 30
PAUSA = 0.1


def borrar(ruta, intentos=INTENTOS, pausa=PAUSA):
    """`os.remove(ruta)` si existe, reintentando ante PermissionError.

    En Windows tampoco se puede borrar un archivo que el tablero está
    sirviendo. Devuelve True si lo borró (o ya no estaba).
    """
    for intento in range(intentos):
        try:
            os.remove(ruta)
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if intento == intentos - 1:
                raise
            time.sleep(pausa)
    return False


def reemplazar(origen, destino, intentos=INTENTOS, pausa=PAUSA):
    """`os.replace(origen, destino)`, reintentando ante PermissionError.

    En POSIX un lector no bloquea el reemplazo, así que ahí un PermissionError
    es un permiso de verdad: se reintenta igual y se relanza al final, con el
    mismo error que habría dado `os.replace`.
    """
    for intento in range(intentos):
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if intento == intentos - 1:
                raise
            time.sleep(pausa)
