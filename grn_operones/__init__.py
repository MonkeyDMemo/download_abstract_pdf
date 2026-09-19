# -*- coding: utf-8 -*-
"""Base de operones de *Pseudomonas aeruginosa* PAO1, desde cuatro fuentes.

Encargo del asesor: extraer los operones de PAO1 de ODB, BioCyc, Pseudomonas
Genome Database y CDBProm, curarlos hasta una sola base de operones, y que todo
el proceso sea automatizable y ejecutable por consola. El detalle esta en
`docs/CONTEXTO_OPERONES.md`.

POR QUE ES UN PAQUETE APARTE Y NO PARTE DEL BRONCE
==================================================
`grn_bronce/operones.py` ya existe y hace otra cosa: es la expansion de un
nombre de operon a sus genes, que consume `operones_pao1.tsv`. Esto de aqui
**construye** una base de operones desde fuentes externas; aquello **la usa**.
Meterlo en `grn_bronce/operones/` no era solo confuso: un directorio con ese
nombre tapa el modulo en cuanto se vuelve paquete, y con el se caen
`identificar.py`, `exportar.py`, `cli.py` y `etapa2/evaluar_oro.py`.

Tampoco va en `grn_etl/`, que el contrato da por cerrado.

Cuando esta base este curada y validada, sustituira a `operones_pao1.tsv` como
fuente del catalogo del bronce. Hasta entonces conviven: el bronce sigue
expandiendo con la tabla derivada por adyacencia, que es una prediccion, y esta
base aporta operones con evidencia de literatura.

DOS CAPAS, Y LA CRUDA NO SE TOCA
================================
`operones_bronze` guarda lo que cada fuente devolvio, sin interpretar, con su
huella y su fecha. `operones_silver` guarda el resultado de normalizar,
validar contra el genoma y deduplicar. Rehacer la curacion no exige volver a
descargar, y comparar dos curaciones sobre la misma descarga es posible porque
la descarga sigue ahi, byte a byte.

LIMITACIONES CONOCIDAS, ANTES DE CONFIAR EN LA SALIDA
=====================================================
1. **La clave de un operon curado son sus genes y nada mas.** Dos unidades de
   transcripcion con los mismos genes y **distinto sitio de inicio** colapsan
   en una sola fila. Para una base de operones es aceptable --lo que interesa
   es que genes se cotranscriben--, pero deja de serlo en cuanto CDBProm entre
   para marcar promotores, porque es justo ahi donde esa distincion vive. El
   detalle esta en `curar.py::clave_de`.
2. **El diccionario apenas trae sinonimos.** De las 5 642 filas de
   `genes_pao1.tsv`, solo 224 tienen un nombre distinto del simbolo y del
   locus tag. ODB viene de literatura y usa nombres historicos --`nalB` por
   `mexR`-- que no van a mapear, y la normalizacion falla en silencio. Por eso
   `curar` reporta la cobertura de mapeo por fuente: hay que mirarla antes de
   dar la curacion por buena.

Solo biblioteca estandar.
"""
