"""Paso 3, consolidación: la red de regulación como producto (capa gold).

El paso 3 es el que un día va a decidir qué aristas forman la red de
*P. aeruginosa*: juntar la evidencia de varios artículos, resolver qué se hace
con los operones (expandirlos a sus genes o dejarlos como anotación, la
decisión D9 de PLAN.md §1.4) y comparar la red con lo que ya se sabe. Esas
reglas todavía no están decididas, y este paquete no las impone.

Su primera pieza, `paquete.py` (21-oct-2026), solo **empaqueta** la red que ya
produce `etapa2/red.py`, sin volver a decidir ningún signo ni ningún umbral:
los nodos unificados por id canónico (`nodos.tsv`), la red como grafo dirigido
para abrirla en un visor de grafos (`red.graphml`) y un manifiesto que dice de
qué corrida del bronce, de qué modelo y de qué recursos sale cada archivo
(`manifiesto.json`). Lo corre el paso «paquete» de `flujo.py`, el último, para
que si falla no corte la sintaxis, la capa ni la evaluación.

La segunda, `consolidar.py` (22-oct-2026), pone las reglas del borrador como
parámetros: autorregulación, nivel de soporte, expansión de operones, mayoría,
umbrales y mínimos. Por omisión es `etapa2/red.py` byte por byte, y es lo que
corre el paso «red»; el perfil recomendado va a `red_recomendada*.tsv` en el
paso «red_recomendada» y nunca toca `red.tsv`.

La tercera, `signo.py` (23-oct-2026), son dos reglas más para el signo de la
arista, apagadas por omisión y fuera de todo perfil: el voto léxico de las
evidencias que BioBERT dejó en `regulates` y el voto por artículo en las
aristas con votos de los dos signos. Se prenden con `consolidar
--signo-lexico` y `--voto-articulo`, siempre con `--nombre`, y se miden en la
tanda 2 de la muestra ciega.

Biblioteca estándar y Python 3.8, como `grn_verificacion/` y `flujo.py`: corre
en las máquinas del laboratorio, sin nada que instalar.
"""
