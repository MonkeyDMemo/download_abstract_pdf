"""Paso 2: verificación de las relaciones que el bronce localizó.

El bronce entrega el *dónde*: oraciones candidatas con sus menciones. Este
paquete decide el *si* y el signo con métodos que se comparan entre sí sobre
el mismo conjunto:

- `puente`: lleva las candidatas del bronce al BioBERT afinado
  (`etapa2/clasificar.py`, por subproceso) y une sus predicciones.
- `capa`: junta en una tabla la oración, sus funciones, sus operones y la
  propuesta del clasificador.
- `evaluar`: recalcula el 44 % de la muestra juzgada con el clasificador
  conectado.
- `validacion` y `entrenamiento`: leen la base curada del laboratorio por
  ruta, nunca por nombre, para preparar datos de entrenamiento en la máquina
  donde vive esa base.

El núcleo es biblioteca estándar y compatible con Python 3.8: lo que necesita
`torch` corre en otro proceso. Nada de aquí escribe en las tablas del bronce,
y ninguna tabla del paso 2 tiene llave foránea hacia ellas: el `--rehacer` del
bronce las borra.
"""
