# -*- coding: utf-8 -*-
"""Donde viven los datos.

Una sola funcion, y existe para que la precedencia este escrita en un solo
sitio: **flag explicito > variable de entorno `GRN_DATOS` > `./datos`**.

El orden no es arbitrario. Quien pasa un flag lo hace mirando el comando y
sabe lo que quiere; la variable de entorno la pone quien monta la maquina, que
no esta presente cuando el comando corre; y el default sirve para que una copia
recien clonada funcione sin configurar nada. Si el entorno le ganara al flag,
un `--db otra.db` haria algo distinto de lo que dice, que es la peor clase de
sorpresa.

En la maquina del laboratorio `GRN_DATOS` apunta fuera del repositorio, con
respaldo, porque `datos/` esta en `.gitignore` y lo que no se versiona conviene
que ni siquiera este dentro.

Solo biblioteca estandar.
"""

import os

VARIABLE = "GRN_DATOS"
POR_OMISION = "datos"


def raiz_datos(flag=None):
    """La carpeta de datos, resuelta por precedencia.

    `flag` es lo que llego por linea de comandos, o None si no llego nada.
    """
    if flag:
        return flag
    del_entorno = os.environ.get(VARIABLE)
    if del_entorno:
        return del_entorno
    return POR_OMISION


def ruta(*partes, **kwargs):
    """Une un camino bajo la raiz de datos.

    `ruta("grn.db")` -> `datos/grn.db`
    `ruta("fulltext", "xml", flag=args.datos)` -> respeta el flag
    """
    return os.path.join(raiz_datos(kwargs.get("flag")), *partes)


def de_donde(flag=None):
    """Que gano la precedencia, para poder decirlo en un informe.

    Un numero que no dice de donde salio su insumo no es reproducible, y esta
    es la parte mas facil de olvidar.
    """
    if flag:
        return "flag"
    if os.environ.get(VARIABLE):
        return "entorno:" + VARIABLE
    return "omision"
