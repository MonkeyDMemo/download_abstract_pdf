# Ouroboros v0

Guía para correr el juez LLM en el servidor del asesor. La leen Hermes y el
usuario.

## Qué es

Un anotador automático que anota las mismas hojas que el experto
(`docs/calibracion-hoja.csv` y las hojas de las tandas), con las etiquetas
exactas de la rúbrica, y deja su anotación con las columnas de la hoja. Su
acuerdo con el experto se mide con `grn_verificacion.cli concordancia`.

Es **exploratorio y está fuera del pipeline**: no es un paso de `flujo.py`,
no toca la base ni la red, y nada de la entrega depende de él
(`docs/decisiones.md`, «Ouroboros v0»). Corre contra el Ollama del servidor
(`http://127.0.0.1:11500`), con `qwen3:8b` de digest `500a1f067a9f…` en
Q4_K_M. Cualquier otro digest u otra cuantización detienen la corrida antes
de anotar. El juez nunca es Claude: el modelo va siempre explícito.

## Configuraciones pre-registradas

| | `principal` | `con_think` |
|---|---|---|
| think | no | sí |
| temperatura | 0 | 0.6 |
| top_p / top_k | — | 0.95 / 20 |
| semilla | 42 | 42 |
| `num_ctx` | 4 096 | 8 192 |
| `num_predict` | 512 | 4 096 |
| caché KV | f16 | f16 |

- **En el servidor, `con_think` corre con la caché q8_0.** Con f16, los 8 192
  de contexto no caben en los 8 GB. Se arranca Ollama con
  `OLLAMA_KV_CACHE_TYPE=q8_0` y `OLLAMA_FLASH_ATTENTION=1`, y la corrida lleva
  `--kv-cache q8_0` (`protocolo-tanda2.md`, enmienda 3).
- **Herramientas**, la otra dimensión: `ninguna` (por omisión), `buscar_locus`
  o `todas` (además `es_tf`, `operon_de`, `funcion_anotada` y `contexto`).
- **Sin herramientas, la respuesta va restringida al esquema** (`format`).
  Con herramientas, el esquema se pide en el prompt, porque `format`
  impediría las llamadas, y el agente lleva un tope de turnos.
- **Por corrida se pueden cambiar tres cosas**, y las tres entran a la llave
  de la caché:
  - `--semilla`;
  - `--kv-cache q8_0`: se declara cuando Ollama arrancó con
    `OLLAMA_KV_CACHE_TYPE=q8_0`, porque la API no lo dice;
  - `--num-ctx`: solo si los 8 192 de `con_think` no caben ni con la caché
    comprimida.

## Abstención y caché

**Abstención**, fijada antes de correr:

- Es abstención una respuesta truncada, sin un objeto JSON, con un campo de
  menos o de más, con una etiqueta fuera de la rúbrica o con una combinación
  que `revision.validar` rechaza.
- En la hoja sale con la anotación vacía, y en `calibracion`, `evals` y
  `concordancia` cuenta como error en todos los campos.
- Un fragmento que no está literal en la oración no es abstención: el
  veredicto se queda y se marca (`evidencia_invalida`).

**Caché** (`veredictos.jsonl`, de solo anexar). La llave de cada ítem es el
sha256 de sus entradas:

- la oración y sus dos entidades, y el `id_item` solo con `contexto`;
- la huella del prompt;
- el digest, la cuantización y la huella del template del modelo;
- la versión de Ollama;
- la decodificación completa (think, temperatura, top_p, top_k, semilla,
  `num_ctx`, `num_predict`, caché KV, `format` y el tope de turnos);
- la versión y la huella del esquema de la respuesta;
- las herramientas, la huella de su código (sus descripciones son parte de
  lo que el modelo lee) y la de los recursos que leen.

Lo mismo dos veces no vuelve a llamar al modelo. Una corrida cortada se
retoma corriendo el mismo comando. Una carpeta con otra corrida no se
reutiliza.

## Ceguera

- Las salidas van a `salidas/ouroboros/`. El CLI rechaza una `--salida`
  dentro de `salidas/revision`, la carpeta del experto, y el experto no ve
  nada de Ouroboros.
- Ninguna sesión de Claude, la principal ni Hermes, abre lo que Ouroboros
  deja de la tanda 2 antes de evaluarla: `anotaciones.csv`,
  `veredictos.jsonl`, `experimento.json` e `informe_evals.json` de esa
  carpeta. Llevan sus veredictos o las oraciones de la hoja, que también es
  ciega: `experimento.json` no trae veredictos, pero copia la hoja entera.
  Lo que se ve son los conteos que imprimen `anotar`, `evals` y
  `concordancia`, y `corrida.json`, que no lleva oraciones.
- La hoja del experto la lee `concordancia`; ninguna sesión la abre.
- La tanda 2 se corre solo con el prompt congelado en un commit y con
  `docs/protocolo-tanda2.md` commiteado. La huella del prompt queda en
  `corrida.json`.
- Ninguna oración del corpus, de las tandas ni de la calibración entra al
  prompt (`grn_ouroboros/test_frontera.py`). Las salidas sobre las tandas no
  se copian a docs, pruebas, prompts ni mensajes: lo publicable son las
  cifras.

## Herramientas

Apagadas por omisión: el experto juzga solo la oración (rúbrica §2).

- La corrida con herramientas es secundaria, pre-registrada, y va después de
  la principal.
- Tiene límite de tiempo: si hay atraso, solo `buscar_locus`, y las otras
  cuatro pasan a la tesis.
- `todas` necesita, para `contexto`:
  - `--llave <muestra_t1>/llave.csv`, de la que se lee solo la posición de
    cada ítem;
  - `--corrida-bronce 4`;
  - la base con esa corrida (`--db`, o `<datos>/grn.db`).

  Si la base no está en el servidor, `todas` no corre ahí.

## En el servidor, en orden

Todo desde el clon, `~/grn-guillermo/download_abstract_pdf`: las rutas
relativas de abajo (`.venv-ouroboros`, `docs/`, `salidas/ouroboros`) son de
ahí. Los marcadores entre `<>` son rutas de datos que no se escriben aquí;
`docs/servidor-cierre.md` §7 dice cuáles son en el servidor:

- `<muestra_t1>` y `<muestra_t2>`: las carpetas de los sorteos;
- `<hoja_normalizada_t1>`: la hoja de la tanda 1 anotada por el experto, ya
  normalizada.

```bash
# Una sola vez: el entorno, con el Python 3.10+ de miniforge
~/miniforge3/bin/python3 -m venv .venv-ouroboros
.venv-ouroboros/bin/python -m pip install -r grn_ouroboros/requisitos-servidor.txt
mkdir -p salidas/ouroboros

# En cada sesión
OPY=.venv-ouroboros/bin/python
$OPY -m unittest discover -s grn_ouroboros -t .   # sin red: aquí sí corren las de Strands

# 1. La GPU es compartida
nvidia-smi

# 2. Ollama
~/grn-guillermo/ollama.sh start

# 3. Humo: versión, digest, cuantización y think = false sin razonamiento
$OPY -m grn_ouroboros.cli humo

# 4. Calibración: anotar, comparar con la llave y Strands Evals
$OPY -m grn_ouroboros.cli anotar --hoja docs/calibracion-hoja.csv \
    --salida salidas/ouroboros/calibracion_principal --config principal
$OPY -m grn_ouroboros.cli calibracion \
    --anotacion salidas/ouroboros/calibracion_principal/anotaciones.csv
$OPY -m grn_ouroboros.cli evals --salida salidas/ouroboros/calibracion_principal
#    Lo mismo con --config con_think en calibracion_con_think, mirando
#    nvidia-smi: si 8 192 no cabe, Ollama con OLLAMA_KV_CACHE_TYPE=q8_0 (y
#    flash attention) y --kv-cache q8_0 en otra carpeta; solo si aún no
#    cabe, --num-ctx menor.

# 5. Tanda 1 con la principal (con nohup sobrevive a un corte de SSH;
#    volver a lanzarla retoma)
nohup $OPY -m grn_ouroboros.cli anotar --hoja <muestra_t1>/hoja_tanda1.csv \
    --salida salidas/ouroboros/tanda1_principal --config principal \
    > salidas/ouroboros/tanda1_principal.log 2>&1 &
tail -n 5 salidas/ouroboros/tanda1_principal.log

# 6. Concordancia con el experto (biblioteca estándar; solo conteos)
$OPY -m grn_verificacion.cli concordancia --experto <hoja_normalizada_t1> \
    --modelo salidas/ouroboros/tanda1_principal/anotaciones.csv \
    --llave <muestra_t1>/llave.csv \
    --json salidas/ouroboros/tanda1_principal/concordancia.json

# 7. Tanda 2: solo después de congelar el prompt con un commit
nohup $OPY -m grn_ouroboros.cli anotar --hoja <muestra_t2>/hoja_tanda1.csv \
    --salida salidas/ouroboros/tanda2_principal --config principal \
    > salidas/ouroboros/tanda2_principal.log 2>&1 &

# 8. Al terminar
~/grn-guillermo/ollama.sh stop
```

**Códigos de salida del CLI:**

- 0: bien;
- 1: el modelo no es el pre-registrado, Ollama no contesta o la corrida se
  detuvo;
- 2: argumentos o entradas que no sirven;
- 3: interrumpida.

**Lo que deja cada corrida en su carpeta:**

- `anotaciones.csv`: las columnas de la hoja;
- `veredictos.jsonl`: la caché, con el fragmento, el motivo y los tiempos;
- `corrida.json`: versiones, configuración, huellas y conteos, sin
  oraciones;
- con `evals`, además `experimento.json` (un caso por ítem, con su oración)
  e `informe_evals.json` (los casos con el veredicto y lo que dijo cada
  evaluador).

## Lo medido antes de la tanda 2

Hermes lo corrió en el servidor con `main` en `67e9179`.
- **El entorno:** `.venv-ouroboros` con Python 3.12.11 y las versiones fijadas.
- **Las pruebas:** pasan las 199 del paquete.
- **El humo** confirma el digest `500a1f067a9f` y la cuantización Q4_K_M.

El prompt v0 no se ajustó con nada de esto, y quedó congelado
(`protocolo-tanda2.md`, enmienda 3).

**Calibración** (27 ítems sintéticos; acuerdo con la llave):

| | idénticos | relación | dirección | signo | tipo | negada | especulativa | abstenciones | s por ítem |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| principal | 11/27 | 74 % | 81 % | 63 % | 67 % | 89 % | 93 % | 1 | 3.6 |
| con think (q8_0) | 15/27 | 85 % | 89 % | 81 % | 67 % | 96 % | 96 % | 1 | 18.6 |

La primera corrida con think, con caché f16, quedó incompleta porque no cabía,
y se descarta. Valen `calibracion_con_think_q8` y `tanda1_con_think_q8`.

**Tanda 1** (198 anotadas por el experto; la abstención cuenta como error):

| | relación (κ) | dirección (κ) | signo (κ) | tipo | negada | especulativa | abstenciones | s por ítem |
|---|---|---|---|---:|---:|---:|---:|---:|
| principal | 60.1 % (0.316) | 72.2 % (0.562) | 58.6 % (0.433) | 43.4 % | 93.4 % | 84.3 % | 8 | 4.2 |
| `buscar_locus` | 63.6 % (0.329) | 73.2 % (0.571) | 61.1 % (0.463) | 45.5 % | 92.9 % | 80.3 % | 11 | — |
| con think (q8_0) | 62.1 % (0.353) | 72.2 % (0.585) | 63.6 % (0.507) | 48.0 % | 94.4 % | 90.4 % | 6, 1 truncada | 16.9 |

**Como filtro de los pares del bronce:** acepta si dice `si` con la dirección
del bronce.

| | precisión con dirección | retiene de las verdaderas | filtro − bronce, IC 95 % |
|---|---|---|---|
| principal | 66/70 = 94.3 % [86.2, 97.8] | 66/105 = 62.9 % | [+33.8, +48.9] |
| `buscar_locus` | 74/84 = 88.1 % [79.5, 93.4] | 70.5 % | [+27.5, +42.4] |
| con think (q8_0) | 72/75 = 96.0 % [88.9, 98.6] | 68.6 % | [+35.8, +50.2] |

**Lectura, con sus cautelas:**
- **Sobre los mismos ítems, la red de *E. coli*** da 87/142 = 61.3 % y retiene
  el 82.9 % de las verdaderas.
- **Ouroboros como filtro** es mucho más preciso y retiene menos: descarta una
  de cada tres verdaderas.
- **El acuerdo campo por campo es moderado:** κ de 0.32 a 0.35 en relación.
- **El acuerdo en `tipo`** lleva la salvedad de la tanda 1: el experto marcó
  «directa» donde la rúbrica pide `no_se`.
- **La tanda 1 es de desarrollo.** El prompt se escribió el 23-oct,
  sabiendo ya en qué se había desviado el experto en ella (la calibración 2).
  Que no se haya ajustado con sus cifras no la vuelve de prueba. La cifra que
  cuenta es la de la tanda 2.
