# -*- coding: utf-8 -*-
"""Puente: `rutas` vive en `grn_comun/rutas.py` desde el 20-oct-2026.

Se queda aquí, reexportando los mismos objetos, para no romper a quien la
importa desde `grn_bronce`: el CLI del paso 0, el tablero, `grn_verificacion`,
el CLI del bronce y dos scripts de `etapa2`, que está congelada. Cada uno se
muda a `grn_comun` al tocar su archivo, como pide CLAUDE.md para las rutas, y
cuando no quede ninguno este archivo se borra.

Solo biblioteca estándar.
"""

from grn_comun.rutas import (POR_OMISION, VARIABLE, de_donde,  # noqa: F401
                             raiz_datos, ruta)
