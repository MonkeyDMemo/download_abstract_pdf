"""Ouroboros v0: un juez LLM local que anota las mismas hojas que el experto.

Qué es
======
Un anotador automático de relaciones de regulación. Recibe una hoja de la
rúbrica (`docs/rubrica-anotacion.md` §6: la calibración o una tanda de la
muestra ciega) y la anota con las etiquetas exactas que usa el experto, ítem
por ítem, juzgando solo la oración. Su salida tiene las columnas de la hoja,
así que el acuerdo con el experto se mide con el mismo lector que valida la
rúbrica (`python -m grn_verificacion.cli concordancia`).

Es **exploratorio** y está **fuera del pipeline**: no es un paso de
`flujo.py`, no toca la base ni la red, y nada de la entrega depende de él
(`docs/decisiones.md`, «Ouroboros v0»). Es la comparación que la reunión del
23-oct adelantó a la tesis, declarada como tal y sin puerta de decisión.

Dónde corre
===========
En el servidor del asesor, contra el Ollama que vive ahí
(`http://127.0.0.1:11500`, `qwen3:8b` en Q4_K_M), con el entorno
`.venv-ouroboros` (Python 3.10 o más) y el extra `[ouroboros]`. Cómo se arma
y se corre está en `docs/ouroboros-v0.md`.

Lo que no se cruza
==================
- Este paquete es el único que importa Strands, Strands Evals, `ollama` o
  pydantic, y lo hace **dentro de las funciones**: todo él se lee con la
  gramática de Python 3.8 y se importa sin esas dependencias, porque la suite
  de la raíz lo recoge con el Python del sistema. Nada fuera de él lo importa.
- El juez nunca es Claude: el modelo va siempre explícito (un `OllamaModel`),
  porque Strands sin modelo cae en Bedrock sin avisar, y una prueba falla si
  se construye uno de Bedrock.
- Nunca lee los juicios del experto: su única referencia es la llave de la
  calibración, que es sintética y pública. El acuerdo con el experto se
  calcula fuera, en `grn_verificacion/concordancia.py`.

Módulos: `rubrica` (columnas, opciones y el esquema de la respuesta),
`calibracion` (la hoja y la llave), `motor` (Ollama por HTTP), `herramientas`
(cinco consultas a recursos del proyecto), `agente` (Strands), `anotar`
(caché, abstención y salidas), `evals` (Strands Evals) y `cli`.
"""
