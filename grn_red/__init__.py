"""Paso 3, consolidación: la red de regulación como producto (capa gold).

El paso 3 es el que un día va a decidir qué aristas forman la red de
*P. aeruginosa*: juntar la evidencia de varios artículos, resolver qué se hace
con los operones (expandirlos a sus genes o dejarlos como anotación, la
decisión D9 de PLAN.md §1.4) y comparar la red con lo que ya se sabe. Esas
reglas todavía no existen, y este paquete no las inventa.

Su primera pieza, `paquete.py` (21-oct-2026), solo **empaqueta** la red que ya
produce `etapa2/red.py`, sin volver a decidir ningún signo ni ningún umbral:
los nodos unificados por id canónico (`nodos.tsv`), la red como grafo dirigido
para abrirla en un visor de grafos (`red.graphml`) y un manifiesto que dice de
qué corrida del bronce, de qué modelo y de qué recursos sale cada archivo
(`manifiesto.json`). Lo corre el paso «paquete» de `flujo.py`, el último, para
que si falla no corte la sintaxis, la capa ni la evaluación.

Biblioteca estándar y Python 3.8, como `grn_verificacion/` y `flujo.py`: corre
en las máquinas del laboratorio, sin nada que instalar.
"""
