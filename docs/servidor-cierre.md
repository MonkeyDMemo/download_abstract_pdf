# Cierre en el servidor: lo que corre Hermes

Una guía única para las corridas del servidor del asesor durante el cierre del
servicio social (23-oct-2026 en adelante). La ejecuta Hermes, la sesión de
Claude del usuario que entra por SSH con llave, con el VoBo del asesor. La
sesión de la laptop no corre nada aquí: deja los comandos y lee los conteos que
Hermes reporta.

**Reglas** (`CLAUDE.md`, Confidencialidad):
- Se trabaja solo en `~/grn-guillermo`.
- Nunca se abren la base curada, `datos/`, `runs/`, las carpetas
  `--confidencial`, los juicios del experto ni la hoja de la tanda 2.
- De vuelta a la laptop solo viajan los informes filtrados (`CONTRASTE.md`,
  `TABLAS.md`) y las líneas que imprimen los comandos, que son conteos.
- La GPU es compartida: `nvidia-smi` antes de lanzar nada que la use, y
  detener lo propio al acabar.
- El host, la cuenta y la llave no se escriben aquí. La laptop entra con el
  alias `asesor` de su `~/.ssh/config`.

Cada comando se marca así:
- **[sintético]:** se verificó en la laptop con los datos sintéticos de sus
  pruebas.
- **[ayuda]:** solo se verificó su `--help`.
- **[servidor]:** solo se puede verificar allá.

## 0. Preparar

```bash
cd ~/grn-guillermo/download_abstract_pdf && git pull --ff-only && git rev-parse --short HEAD
source ~/grn-guillermo/entorno.sh          # PY (Python 3.10 de pseudoRE), RAIZ y BASE_CURADA
$PY -m unittest discover                   # la suite de la raíz con el Python de pseudoRE
python3 -m unittest discover               # y con el 3.8 del sistema, que es el que cubre el núcleo
```

**Lo que se espera:** las dos suites en verde, con el mismo conteo que la
laptop menos las pruebas que piden spaCy o Strands, que se saltan diciendo por
qué. En la laptop, con la fase 4 fusionada, la raíz da 1 772 (84 saltadas, las
de Strands entre ellas). Un revisor ya la corrió con un Python 3.8.20 en verde,
pero es la primera vez en el 3.8 del servidor. Una falla ahí se reporta con su
línea, no se arregla en el servidor.

## 1. Lo que sube la laptop

Lo sube el usuario con `scp` y el alias `asesor`. No pasa por una sesión de
Claude.

| qué | de la laptop | al servidor |
|---|---|---|
| la red recomendada | `salidas/flujo/corrida4_run22/red_recomendada.tsv`, `red_recomendada_evidencias.tsv` y `red_recomendada_informe.json` | `$RAIZ/flujo/corrida4_run22/` |
| la capa del sorteo de las tandas | `salidas/flujo/corrida4_run22/capa_pares.csv` | `$RAIZ/flujo/corrida4_run22/` |
| el XML del corpus, para las tablas | `<GRN_DATOS>/fulltext/xml/*.xml` | `$RAIZ/fulltext_xml/` |
| el respaldo de las tandas | `salidas/revision/muestra200/` y `salidas/revision/muestra200_t2/` | `~/grn-guillermo/revision/` |

El XML es corpus público. Las tandas se copian sin abrirlas: la 2 es ciega.

**Antes de la sección 2, el bronce del servidor tiene que ser el de la
laptop.** Hermes imprime cuál nombra el `estado.json` del servidor:

```bash
$PY -c "import json,sys; print(json.load(open(sys.argv[1]))['archivos']['candidatas'])" \
    $RAIZ/flujo/corrida4_run22/estado.json
```

En la laptop es `bronce_identificacion_corrida4_20261022_oraciones_candidatas.csv`.
Si el servidor nombra otra fecha, el usuario sube `estado.json` y los dos CSV
del 20261022 (`_oraciones_candidatas.csv` y `_menciones.csv`) antes de seguir,
como en `contraste-curada.md`. Las cifras de la sección 2 son las del contraste
del 23-oct: si el bronce cambia, se reportan como nuevas, no como las mismas.

## 2. Contraste con la red oficial: línea base, techo y conciliación [sintético]

```bash
C="--base $BASE_CURADA --carpeta $RAIZ/flujo/corrida4_run22 --excluir-pmids $RAIZ/excluir_pmid_b.tsv"
$PY -m grn_verificacion.cli contraste $C \
    --informe $RAIZ/resultados/contraste-corrida4/CONTRASTE.md \
    --confidencial $RAIZ/datos/contraste-corrida4
```

**Ya corrió una vez,** el 23-oct a las 19:40 UTC, con el código de las ramas
antes de su revisión (`salidas/contraste/CONTRASTE.md` en la laptop). Los
arreglos de la revisión no tocan conteos, así que con `main` tiene que dar
exactamente lo mismo:
- **Las cifras de antes:** 2 077 exigibles, regla b) con XML 259/859 y
  dirigido sin BioBERT 642/1 560.
- **El signo:**
  - 319/366 cuando la red lo da, contra 280/366 de «siempre activa»;
  - con la abstención como error, 319/605 contra 448/605.
- **La orientación:** 642/674. Por estrato, Histórica 505/536 y Ambos 137/138.
- **El techo de la regla a):** 720/1 560, con 0 filas de la red fuera de él.
- **La conciliación:** 6 filas con locus inválido, 80 que citan el artículo
  excluido junto con otro y 0 de homología que lo citen.

Cualquier diferencia se reporta antes de seguir.

**A la laptop vuelve** solo `CONTRASTE.md`.

## 3. Contraste con la red recomendada [sintético]

```bash
$PY -m grn_verificacion.cli contraste $C --red recomendada \
    --informe $RAIZ/resultados/contraste-corrida4-recomendada/CONTRASTE.md \
    --confidencial $RAIZ/datos/contraste-corrida4-recomendada
```

**Lo que se espera** (también corrió a las 19:40 UTC, en
`CONTRASTE_recomendada.md`):
- **Las aristas:** 10 592 = 8 747 llevadas a locus + 131 sin locus + 181
  autorregulaciones de un solo locus + 1 533 expandidas, que se omiten.
- **Los pares:** 9 012 de locus, con el mismo dirigido, 642/1 560.
- **El signo:** 313/360 cuando lo da; con la abstención como error, 313/605.
- **Candidatas nuevas:** 7 850.

**A la laptop vuelve** solo `CONTRASTE.md`, con el nombre
`CONTRASTE_recomendada.md` (`contraste-curada.md`, paso 5).

## 4. Tablas en los 5 artículos con más filas [sintético]

```bash
$PY -m grn_verificacion.cli tablas $C --xml $RAIZ/fulltext_xml \
    --informe $RAIZ/resultados/tablas-corrida4/TABLAS.md \
    --confidencial $RAIZ/datos/tablas-corrida4
```

**Lo que se espera:**
- **Las categorías** suman las 672 filas exigibles de esos 5 artículos:
  autorregulación, regla b), sin XML, misma fila, misma tabla, tabla y texto,
  solo texto y ninguno.
- **No se escribe ningún archivo fila por fila.**
- **Esto sí se rehace.** La corrida de las 19:40 UTC usó el código anterior a
  la revisión. La revisión arregló dos cosas: las celdas que abarcan varias
  filas (`rowspan`) y el título de un grupo de tablas. Las dos pueden mover
  filas entre «misma fila», «misma tabla» y «ninguno». Lo que vale es lo que
  salga ahora.
- **`--xml`** tiene que ser la carpeta con los `<pmid>_<pmcid>.xml`. Si no
  tiene ninguno, el comando se detiene antes de abrir la base.

**A la laptop vuelve** solo `TABLAS.md`.

## 5. Precisión de la tanda 1 sin el entrenamiento de cada modelo [sintético]

Sale todo ítem cuyo artículo estuvo en train o dev del modelo. Lo mismo se
corre con *E. coli*, para comparar sobre los mismos ítems.

Primero, los nombres de las carpetas de cada modelo. La de la v1 lleva el
nombre del checkpoint (`corrida4_run_22_…`, bitácora del 21-oct):

```bash
ls -d $RAIZ/flujo/corrida4_*
```

Después, con `V1` igual al nombre que imprimió para la v1:

```bash
A=~/grn-guillermo/revision/muestra200/anotacion_experto_tanda1_tal_cual.csv
L=~/grn-guillermo/revision/muestra200/llave.csv
K=$RAIZ/flujo/corrida4_run22/capa_pares.csv
for V in v1 v2; do
  if [ $V = v1 ]; then M=$V1; else M=corrida4_curada-v2; fi
  for CARPETA in $M corrida4_run22; do
    $PY -m grn_verificacion.cli precision-ciega --anotacion $A --llave $L \
        --carpeta $RAIZ/flujo/$CARPETA --capa $K \
        --particion $RAIZ/datos/curada-$V/por_pmid --etiqueta tanda1-sin-train-$V
  done
done
```

El bucle no usa `C`, que guarda los argumentos del contraste de la sección 2.

- **Son cuatro corridas:** cada modelo curado y *E. coli* (`corrida4_run22`),
  con la misma exclusión.
- **Lo que se espera:** cuántos ítems salen por PMID y cuántos de los que
  quedan tienen su oración en train. Después, el bronce y la red sobre los que
  quedan. Solo conteos.
- **La anotación es la normalizada:** `_tal_cual` cambia solo los códigos
  (`ninguna` y `?`). La sensibilidad con las negadas como `no` es
  `anotacion_experto_tanda1_negadas_no.csv`, y no se corre aquí.

## 6. El 44 % de las 50 juzgadas, separando los pares que el modelo vio [sintético]

`evaluar` lee las 50 del bronce de la corrida 4, el mismo de la sección 1:

```bash
B=$RAIZ/flujo/corrida4_run22/$($PY -c "import json,sys; print(json.load(open(sys.argv[1]))['archivos']['candidatas'])" $RAIZ/flujo/corrida4_run22/estado.json)
$PY -m grn_verificacion.cli evaluar --carpeta $RAIZ/flujo/corrida4_curada-v2 \
    --bronce "$B" --particion $RAIZ/datos/curada-v2/por_pmid
```

- **Lo mismo con la v1:** `--carpeta $RAIZ/flujo/$V1` y
  `--particion $RAIZ/datos/curada-v1/por_pmid`.
- **Lo que se espera:** el P1 de antes (v2 16/28, v1 5/9), partido en par
  visto y par no visto al entrenar.
- **`evaluar` reescribe `evaluacion.json`** en la carpeta del modelo. En el
  servidor esa carpeta no es la del flujo de la laptop, así que no pisa nada
  de aquí.

Las 50 estaban reservadas al entrenar, así que ningún artículo suyo entró. Lo
que se separa es el **par**: si el modelo vio el mismo par en otro artículo,
puede estar memorizando.

## 7. Ouroboros v0 (fase 4) [servidor]

La guía completa está en `docs/ouroboros-v0.md`: configuraciones, abstención,
caché y ceguera. Aquí va el orden con las rutas del servidor.

**Lo que ya está fijo del entorno:**
- **Ollama** está instalado en `~/grn-guillermo/ollama`, con la sha256
  verificada.
- **El modelo** es `qwen3:8b`, con digest `500a1f067a9f` y cuantización
  Q4_K_M. Corre en 127.0.0.1:11500: da unos 65-70 tokens/s y usa 6.7 GB de
  VRAM con `num_ctx` 4 096. Un digest o una cuantización distintos detienen la
  corrida antes de anotar.
- **El Python.** En SSH no interactivo, `python3` es el 3.8 del sistema, así
  que el entorno se crea con miniforge (3.12).

**Una sola vez**, desde el clon:

```bash
cd ~/grn-guillermo/download_abstract_pdf
~/miniforge3/bin/python3 -m venv .venv-ouroboros
.venv-ouroboros/bin/python -m pip install -r grn_ouroboros/requisitos-servidor.txt
mkdir -p salidas/ouroboros
```

`requisitos-servidor.txt` fija `strands-agents[ollama]`, `strands-agents-evals`,
`ollama`, `strands-agents-tools` y `pydantic`. Si pip no resuelve el `pydantic`
fijado, se reporta y no se cambia aquí.

**En cada sesión:**

```bash
cd ~/grn-guillermo/download_abstract_pdf && git pull --ff-only
OPY=.venv-ouroboros/bin/python
T1=~/grn-guillermo/revision/muestra200
$OPY -m unittest discover -s grn_ouroboros -t .   # aquí sí corren las de Strands
nvidia-smi                                        # la GPU es compartida
~/grn-guillermo/ollama.sh start
$OPY -m grn_ouroboros.cli humo                    # se anota lo que conteste
```

**1. Calibración**, que es sintética y pública:

```bash
$OPY -m grn_ouroboros.cli anotar --hoja docs/calibracion-hoja.csv \
    --salida salidas/ouroboros/calibracion_principal --config principal
$OPY -m grn_ouroboros.cli calibracion \
    --anotacion salidas/ouroboros/calibracion_principal/anotaciones.csv
$OPY -m grn_ouroboros.cli evals --salida salidas/ouroboros/calibracion_principal
```

- Lo mismo con `--config con_think` en `calibracion_con_think`, mirando
  `nvidia-smi`.
- Si los 8 192 de `con_think` no caben, se reinicia Ollama con
  `OLLAMA_KV_CACHE_TYPE=q8_0` y `OLLAMA_FLASH_ATTENTION=1`, y se corre con
  `--kv-cache q8_0` en otra carpeta. Solo si aún no caben, `--num-ctx` menor.
- **A la laptop vuelve** la salida de `calibracion`, que es por ítem pero de
  oraciones sintéticas, y la de `evals`.

**2. Tanda 1 con la principal.** Es de desarrollo, así que sus conteos pueden
servir para ajustar el prompt. Sus anotaciones son juicios y no salen del
servidor:

```bash
nohup $OPY -m grn_ouroboros.cli anotar --hoja $T1/hoja_tanda1.csv \
    --salida salidas/ouroboros/tanda1_principal --config principal \
    > salidas/ouroboros/tanda1_principal.log 2>&1 &
tail -n 5 salidas/ouroboros/tanda1_principal.log   # volver a lanzarla retoma
$OPY -m grn_verificacion.cli concordancia \
    --experto $T1/anotacion_experto_tanda1_tal_cual.csv \
    --modelo salidas/ouroboros/tanda1_principal/anotaciones.csv \
    --llave $T1/llave.csv --json salidas/ouroboros/tanda1_principal/concordancia.json
```

- **A la laptop vuelven** solo las líneas de `concordancia`, que son conteos.
- El acuerdo en `tipo` de la tanda 1 lleva su salvedad: el experto marcó
  «directa» donde la rúbrica pide `no_se`.
- Lo mismo con `con_think`, y con `--herramientas buscar_locus`, si hay
  tiempo. `todas` necesita la base de la corrida 4, que no está en el
  servidor.

**3. El congelamiento del prompt,** en la laptop y no aquí:
- con lo que vuelva de 1 y 2, la sesión principal ajusta el prompt si hace
  falta, y lo declara;
- después lo congela con un commit, y anota su sha256 en una enmienda de
  `docs/protocolo-tanda2.md`.

**4. Tanda 2:** solo después del congelamiento, y con el prompt de ese commit.

```bash
nohup $OPY -m grn_ouroboros.cli anotar --hoja ~/grn-guillermo/revision/muestra200_t2/hoja_tanda1.csv \
    --salida salidas/ouroboros/tanda2_principal --config principal \
    > salidas/ouroboros/tanda2_principal.log 2>&1 &
```

- **La ceguera:** Hermes no abre nada de `salidas/ouroboros/tanda2_*`.
- **A la laptop vuelven** solo `corrida.json` y lo que imprime `anotar`, que
  son conteos.
- **La concordancia de la tanda 2** se corre cuando el experto termine, con
  su exportación, y la decide el protocolo.

**Al terminar:** `~/grn-guillermo/ollama.sh stop`. Si algo pasa de 4 horas, se
detiene y se anota (`CLAUDE.md`, máquina del laboratorio).

## Qué reporta Hermes

Por cada sección:
- el commit en el que corrió (`git rev-parse --short HEAD`);
- las líneas que imprimió el comando;
- el código de salida.

Nunca una fila, un locus de la base, un PMID ni una oración.
