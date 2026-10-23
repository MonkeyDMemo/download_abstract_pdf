"""Los nombres de archivo de una red: la oficial y las que salen con otras reglas.

Vive aquí porque lo usan el paso 3, que las escribe (`grn_red.consolidar`), y
el paso 2, que las lee (`contraste`, `precision_ciega`). El paso 2 no importa
`grn_red`, y una copia del patrón en cada lado ya se había desviado: una usaba
`match` con `$` y la otra `fullmatch`.

Solo biblioteca estándar y compatible con 3.8.
"""

import re

RED = "red.tsv"
EVIDENCIAS = "red_evidencias.tsv"
INFORME = "red_informe.json"

# El nombre va dentro de un nombre de archivo que el tablero lista y entrega:
# patrón cerrado. `evidencias` e `informe` quedan fuera porque
# `red_evidencias.tsv` y `red_informe.json` son de la red por omisión.
NOMBRE_VALIDO = re.compile(r"[a-z0-9_]{1,40}")
NOMBRES_RESERVADOS = ("evidencias", "informe")


def nombre_valido(nombre):
    """Si `nombre` sirve para una red con otras reglas.

    `fullmatch` y no `match` con `$`: `$` acepta un salto de línea al final, y
    ese nombre terminaría en un archivo `red_x\\n.tsv` que nadie encuentra.
    """
    return (isinstance(nombre, str)
            and NOMBRE_VALIDO.fullmatch(nombre) is not None
            and nombre not in NOMBRES_RESERVADOS)


def archivos_de_red(nombre=None):
    """(red, evidencias, informe). Sin nombre, los de la red por omisión."""
    if nombre is None:
        return (RED, EVIDENCIAS, INFORME)
    if not nombre_valido(nombre):
        raise ValueError(
            "El nombre de la red tiene que ser de 1 a 40 minúsculas, dígitos o "
            "«_», y no puede ser «evidencias» ni «informe».")
    return ("red_%s.tsv" % nombre, "red_%s_evidencias.tsv" % nombre,
            "red_%s_informe.json" % nombre)
