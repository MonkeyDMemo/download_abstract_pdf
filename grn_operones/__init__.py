# -*- coding: utf-8 -*-
"""Base de operones de *Pseudomonas aeruginosa* PAO1, desde cuatro fuentes.

Encargo del asesor: extraer los operones de PAO1 de ODB, BioCyc, Pseudomonas
Genome Database y CDBProm, curarlos hasta una sola base de operones, y que todo
el proceso sea automatizable y ejecutable por consola. Cómo funciona, cómo se
mantiene y cómo se regenera: `docs/guia-operones.md`. Cada fuente y el
diccionario de datos: `docs/catalogo-operones.md`. El encargo original, que ya
no describe el código, está en `docs/CONTEXTO_OPERONES.md`.

POR QUÉ ES UN PAQUETE APARTE Y NO PARTE DEL BRONCE
==================================================
`grn_bronce/operones.py` ya existe y hace otra cosa: es la expansión de un
nombre de operón a sus genes, que consume `operones_pao1.tsv`. Esto de aquí
**construye** una base de operones desde fuentes externas; aquello **la usa**.
Meterlo en `grn_bronce/operones/` no era solo confuso: un directorio con ese
nombre tapa el módulo en cuanto se vuelve paquete, y con él se caen
`identificar.py`, `exportar.py`, `cli.py` y `etapa2/evaluar_oro.py`.

Tampoco va en `grn_etl/`, que el contrato da por cerrado.

**La base no sustituye a `operones_pao1.tsv`.** Meterla en la detección del
bronce se midió el 27-sep-2026 y salió peor: resolvía 1 o 2 de los 103
operones que le faltan al catálogo del paso 1 y metía cientos de menciones
falsas (`docs/decisiones.md`, «La base de operones anota el bronce, no lo
detecta»). El bronce sigue detectando y expandiendo con la tabla derivada por
adyacencia. Esta base solo anota: `catalogo --paso1` escribe
`grn_bronce/recursos/operones_base.tsv`, y con él el bronce dice a qué
operones pertenecen los genes de cada oración.

DOS CAPAS, Y LA CRUDA NO SE TOCA
================================
`operones_bronze` guarda lo que cada fuente devolvió, sin interpretar, con su
huella y su fecha. `operones_silver` guarda el resultado de normalizar,
validar contra el genoma y deduplicar. Rehacer la curación no exige volver a
descargar, y comparar dos curaciones sobre la misma descarga es posible porque
la descarga sigue ahí, byte a byte.

LIMITACIONES CONOCIDAS, ANTES DE CONFIAR EN LA SALIDA
=====================================================
1. **La clave de un operón curado son sus genes y nada más.** Dos unidades de
   transcripción con los mismos genes y **distinto sitio de inicio** colapsan
   en una sola fila. Para la pertenencia es aceptable --lo que interesa es qué
   genes se cotranscriben--, pero CDBProm marca promotores desde el
   25-sep-2026, y es justo ahí donde esa distinción vive: el promotor no dice
   a cuál de las dos unidades pertenece. El detalle está en `curar.py::clave_de`.
2. **El diccionario apenas trae sinónimos.** De las 5 642 filas de
   `genes_pao1.tsv`, solo 224 tienen un nombre distinto del símbolo y del
   locus tag. ODB viene de literatura y usa nombres históricos --`nalB` por
   `mexR`-- que no van a mapear, y la normalización falla en silencio. Por eso
   `curar` reporta la cobertura de mapeo por fuente: hay que mirarla antes de
   dar la curación por buena.

Solo biblioteca estándar, con una excepción acotada: el `.xlsx` opcional del
catálogo maestro usa openpyxl si está instalado (`exportar.py`). Sin él, el
catálogo sale igual en CSV.
"""
