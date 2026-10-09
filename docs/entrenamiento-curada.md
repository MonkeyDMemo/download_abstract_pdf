# Entrenar el BioBERT con la base curada

Guía para correr la pista D en el servidor del asesor por SSH: construir ejemplos de entrenamiento a partir de la base curada del
laboratorio, partirlos por PMID sin fuga y reentrenar el BioBERT con la
configuración del run 22.

**Todo corre en el servidor. La base curada, los ejemplos que salen de ella y
el modelo entrenado se quedan allá.** A la laptop vuelven números: conteos y
métricas.

## Lo que no se negocia

- **La base curada no se abre en una sesión de Claude**, ni en la laptop ni en
  el servidor, y no se copia a ningún lado. El código la recibe por ruta
  (`--base`) y solo imprime conteos. Lo mismo vale para los
  `entity_marked_*.jsonl` que salen de ella: son oraciones etiquetadas con la
  base. Esta pista no necesita Claude en el servidor, son comandos; si algún día
  se usa ahí, rige lo de CLAUDE.md (aviso al asesor, la base fuera de toda
  sesión).
- **La cuenta del servidor es compartida.** En el home hay carpetas de otras
  personas: no se entra, no se lista su contenido, no se escribe en ellas.
  `~/pseudomonas-trn` es del asesor: se lee y se corre su script de
  entrenamiento, nada más.
- **El entorno conda `pseudoRE` es del asesor.** Se usa para correr
  (`conda run -n pseudoRE ...`); no se instala, actualiza ni desinstala nada en
  él. Nuestro código es biblioteca estándar y Python 3.8, así que no le pide
  nada; torch y transformers ya están ahí.
- **Los perfiles de shell son de todos.** No se toca `~/.bashrc` ni
  `~/.profile`: las variables van en un archivo propio que se carga en cada
  sesión (paso 1).
- **La GPU es compartida** (RTX 3070, 8 GB). `nvidia-smi` antes de lanzar y al
  terminar; si alguien la está usando, se espera. Si el entrenamiento pasa de
  4 horas, se detiene y se anota en la bitácora.
- **Disco**: un entrenamiento con checkpoints ocupa del orden de 3 GB; el
  `df -h` del paso 0 dice cuánto queda.

## Qué hace `datos-entrenamiento`

Es supervisión distante (`grn_verificacion/entrenamiento.py`):

- **Positivo**: un par del corpus público cuyo regulador y blanco, llevados a
  locus PA####, coinciden con una fila de la base, en una oración de un
  artículo que esa fila cita. `+` da `activates`, `-` da `represses`,
  `Unknown` o vacío da `regulates`. Un operón cuenta por sus genes.
- **No dan positivos**: las filas de homología (el artículo citado no reporta
  la relación, PLAN.md 2.4), las de `Origen` BioBERT (las propuso el modelo del
  asesor; «Ambos» sí entra), las `d`, la autorregulación, y los pares que en
  un mismo artículo reciben dos etiquetas (un `Unknown` junto a un `+` también
  es conflicto).
- **Negativo** (`no_relation`): otro par de esos mismos artículos que la base
  no registra en ninguna dirección, contando también las filas de homología y
  de BioBERT. Uno por cada positivo, elegidos con la semilla.
- **Tope**: tres oraciones por (artículo, par), para que un artículo de
  revisión no domine.
- **Reservas**: lo que se aparta para evaluar no entra ni como positivo ni
  como negativo (paso 2).

Todo lo que imprime son conteos: ni oraciones, ni genes, ni locus, ni PMIDs.

## Paso 0. Reconocimiento (solo lectura)

Los comandos llaman `asesor` al servidor. El host y la cuenta no van en este
repositorio, que es público: defínelos una vez en el `~/.ssh/config` de la
laptop, que no se versiona, con lo que te dio el asesor:

```
Host asesor
    HostName <host del servidor>
    User <cuenta>
```

```bash
ssh asesor
nvidia-smi                                  # quién usa la GPU y cuánta memoria queda
conda env list                              # tiene que aparecer pseudoRE
ls ~                                        # solo para ubicarte
ls ~/pseudomonas-trn ~/pseudomonas-trn/04_modelling
python3 --version
conda run -n pseudoRE python --version      # la ficha dice 3.10
conda run -n pseudoRE python -c "import torch, transformers, datasets; print(torch.__version__, transformers.__version__, datasets.__version__, torch.cuda.is_available())"
nproc; free -g
df -h / /home/datos; ls -ld /home/datos
test -w /home/datos && echo "/home/datos es escribible"
ls ~/.cache/huggingface/hub 2>/dev/null | grep -i biobert
command -v git tmux
```

Si `conda` no está en el PATH (pasa en sesiones SSH no interactivas), búscalo
con `ls -d ~/miniforge3 /opt/miniforge3 2>/dev/null` y usa
`<esa ruta>/bin/conda` en lugar de `conda` en todos los comandos.

Qué anotar:

| qué | cómo | para qué |
|---|---|---|
| script de entrenamiento | `ls ~/pseudomonas-trn/04_modelling/bio_bert_re_finetune.py` (ruta de la ficha) | `--script` del paso 4 |
| sus flags | `conda run -n pseudoRE python <script> --help` | ver abajo |
| ruta del .xlsx de la base | te la da el asesor | `--base` del paso 3 |
| BioBERT en la caché | la línea `models--dmis-lab--biobert-base-cased-v1.1` | si falta, se baja en el paso 4 |
| `/home/datos` escribible | el `test -w` de arriba | dónde va `GRN_DATOS` |

Si no tienes la ruta de la base, búscala solo por nombre y sin salir de la
carpeta del asesor: `find ~/pseudomonas-trn -maxdepth 4 -iname '*.xlsx'
2>/dev/null`. **Anota la ruta y nada más: no abras el archivo, no lo copies.**

El `--help` del script tiene que listar `--train_jsonl`, `--dev_jsonl`,
`--test_jsonl`, `--labels_json`, `--out_dir`, `--model_name`, `--batch_size`,
`--epochs`, `--lr`, `--warmup_ratio`, `--weight_decay`, `--max_length`,
`--seed`, `--use_class_weights`, `--early_stopping` y
`--early_stopping_patience`, que son los que le pasa `etapa2/barrido.py`. Si
falta alguno, para: el script del servidor ya no es el que se copió en agosto.

## Paso 1. Carpeta propia y código

```bash
mkdir -p ~/grn-guillermo && chmod 700 ~/grn-guillermo && cd ~/grn-guillermo
git clone https://github.com/MonkeyDMemo/download_abstract_pdf.git
cd download_abstract_pdf
ls grn_verificacion/entrenamiento.py || git checkout flujo-biobert   # si aún no está en main
```

Las variables, en un archivo propio que se carga en cada sesión (también
dentro de tmux):

```bash
cat > ~/grn-guillermo/entorno.sh <<'EOF'
export GRN_DATOS=/home/datos/grn-guillermo      # si /home/datos no es escribible: $HOME/grn-guillermo/datos
export BASE_CURADA='<ruta ABSOLUTA del .xlsx>'   # entre comillas simples ni ~ ni $HOME se expanden
export SCRIPT_ASESOR=$HOME/pseudomonas-trn/04_modelling/bio_bert_re_finetune.py
EOF
source ~/grn-guillermo/entorno.sh
mkdir -p "$GRN_DATOS" && chmod 700 "$GRN_DATOS"
```

`GRN_DATOS` queda **fuera del clon**: `datos-entrenamiento` se niega a escribir
dentro del repositorio o de cualquier otra copia de git, porque lo que escribe
es confidencial. `chmod 700`, en `GRN_DATOS` y en `~/grn-guillermo` (donde
quedan `runs/`, con el modelo entrenado, y `entrada/`), deja las dos carpetas
fuera del alcance de otras cuentas de la máquina. No protege de quien entre
con la misma cuenta compartida: para eso vale la regla de no entrar en
carpetas ajenas.

Antes de darle la base, comprueba que el código corre con el Python del
servidor:

```bash
conda run -n pseudoRE python -m unittest grn_verificacion.test_validacion grn_verificacion.test_entrenamiento
```

Tiene que terminar en `OK`. Son pruebas con datos sintéticos y no leen la base.

## Paso 2. Llevar las entradas (desde la laptop)

Dos archivos, ninguno confidencial:

- `salidas/flujo/corrida4_run22/pares.jsonl`: los pares marcados del corpus
  público, la salida del puente (`grn_verificacion.cli pares`).
- `reservas.tsv`: lo que no puede entrar al entrenamiento. Como mínimo, los
  46 PMIDs distintos de la muestra de 50 juicios con la que se recalcula el
  44 %: si esos artículos entraran, la cifra nueva mediría memoria y no
  precisión. También las 182 oraciones distintas (198 filas) del conjunto
  ciego de la trampa del signo, para que siga sirviendo de evaluación
  externa. Ya quedó uno hecho el 8-oct en
  `salidas/flujo/reservas.tsv`; para rehacerlo:

```bash
# en la laptop, en la raíz del repositorio
python -m grn_verificacion.cli reservas --ciego datos_etapa2/ciego_198.tsv
```

Formato, por si hay que sumar algo: texto UTF-8, una reserva por línea,
`tipo<TAB>valor`. `pmid` aparta el artículo entero; `oracion` aparta esa
oración en cualquier artículo, comparada con los espacios normalizados, y
también toda oración del corpus que la contenga o sea un pedazo de ella (con
40 caracteres o más en común): el bronce y el conjunto ciego no siempre
cortan igual, y 8 de las 182 llegan a la corrida 4 cortadas de otra forma. Las
líneas que empiezan con `#` son comentarios. Un tipo desconocido o un PMID que
no es número detienen la corrida, a propósito: una reserva ignorada en
silencio dejaría entrar justo lo que se quería apartar.

```bash
ssh asesor 'mkdir -p ~/grn-guillermo/entrada'
scp salidas/flujo/corrida4_run22/pares.jsonl salidas/flujo/reservas.tsv asesor:grn-guillermo/entrada/
```

## Paso 3. Construir los ejemplos y partirlos por PMID

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
conda run --no-capture-output -n pseudoRE python -m grn_verificacion.cli datos-entrenamiento \
    --pares ~/grn-guillermo/entrada/pares.jsonl \
    --base "$BASE_CURADA" \
    --reservar ~/grn-guillermo/entrada/reservas.tsv \
    --salida "$GRN_DATOS/validacion/curada-v1"
```

`--no-capture-output` hace que `conda run` muestre la salida mientras corre y
no al final. Con los dos archivos del paso 2, las líneas de reservas y de
pares tienen que decir exactamente:

```
Reservas: PMIDs 46; oraciones 182; archivos leídos 1.
Pares: leídos 72969; reservados por PMID 6839 (artículos reservados presentes: 46); reservados por oración 516; sin locus 411; con un locus fuera de PAO1 0; con el marcado roto 0.
```

Si no, subiste otro `pares.jsonl` u otro `reservas.tsv`.

Antes de seguir, coteja las líneas de la base con lo medido el 10-sep (PLAN.md
2.4): 5 584 filas; signo `+` 4 060 (4 059 más el `+, +`), `?` 909 (786
`Unknown` más 123 vacías), `-` 598, `d` 14, ilegible 3 (los locus corridos);
origen Histórica 4 824, BioBERT 544, Ambos 216; homología 2 850; 310 PMIDs
distintos; 1 DOI. Si no coinciden, la base del servidor es otra versión:
anótalo antes de entrenar.

Lo que queda en `$GRN_DATOS/validacion/curada-v1`:

- `entity_marked_train.jsonl` con **todos** los ejemplos, y
  `entity_marked_dev.jsonl` y `entity_marked_test.jsonl` **vacíos**. Es a
  propósito: el único reparto aceptable es por PMID y con test retenido
  (PLAN.md 1.3), y lo hace `particionar.py`, que además mide la fuga.
- `conteos.json`: los mismos conteos, los parámetros (semilla, tope,
  proporción de negativos) y la huella de cada entrada.

La partición:

```bash
conda run --no-capture-output -n pseudoRE python etapa2/particionar.py \
    --entrada "$GRN_DATOS/validacion/curada-v1" \
    --salida  "$GRN_DATOS/validacion/curada-v1/por_pmid" \
    --por pmid
```

Tiene que decir `Particion limpia. Escrita en ...` (le siguen tres líneas sobre
`--labels_json`) y salir con código 0. Si dice **`PARTICION RECHAZADA`**, no
se entrena con ella aunque haya escrito archivos: trae a la laptop solo lo que
imprimió, que son conteos. Mira también los avisos de la tabla de clases: si
una clase no tiene ningún ejemplo en test, o sale de menos de 5 artículos
(«La celda mas flaca»), su F1 no sirve y la cifra honesta es la de validación
cruzada (paso 6).

## Paso 4. Entrenar con la configuración del run 22

`--solo 22` es `run_22_lr3e-5_ep8_bs16_wu0.1`: tasa 3e-5, 8 épocas, lote 16,
calentamiento 0.1, sobre `dmis-lab/biobert-base-cased-v1.1`, con pesos de
clase y paro temprano de paciencia 2, igual que el barrido del asesor.
`barrido.py` le pasa siempre `--labels_json` con el `label_mapping.json` de la
partición.

Si BioBERT no apareció en la caché en el paso 0, el primer uso lo baja
(433 MB). Para que la descarga quede en tu carpeta y no en la caché
compartida, exporta `HF_HOME=~/grn-guillermo/hf` **dentro de tmux**, después
del `source`: lo exportado antes no llega a una sesión de tmux si el servidor
de tmux de la cuenta compartida ya estaba corriendo. Si sí está en la caché,
no pongas `HF_HOME` (lo volvería a bajar); con `HF_HUB_OFFLINE=1` no sale a
internet.

```bash
nvidia-smi                       # ¿está libre?
tmux new -s grn-guillermo        # un corte de SSH no mata el entrenamiento
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
export HF_HUB_OFFLINE=1          # si BioBERT estaba en la caché (paso 0)
# export HF_HOME=~/grn-guillermo/hf   # en su lugar, si no estaba
conda run --no-capture-output -n pseudoRE python etapa2/barrido.py \
    --datos      "$GRN_DATOS/validacion/curada-v1/por_pmid" \
    --script     "$SCRIPT_ASESOR" \
    --trabajo    ~/grn-guillermo/runs \
    --resultados "$GRN_DATOS/validacion/curada-v1/resultados" \
    --solo 22 --conservar
```

Para dejarlo corriendo: `Ctrl-b d`; para volver: `tmux attach -t grn-guillermo`.

Sin tmux, el mismo comando completo con `nohup`:

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
export HF_HUB_OFFLINE=1          # o HF_HOME, como arriba
nohup conda run --no-capture-output -n pseudoRE python etapa2/barrido.py \
    --datos "$GRN_DATOS/validacion/curada-v1/por_pmid" --script "$SCRIPT_ASESOR" \
    --trabajo ~/grn-guillermo/runs --resultados "$GRN_DATOS/validacion/curada-v1/resultados" \
    --solo 22 --conservar > ~/grn-guillermo/barrido.log 2>&1 &
tail -f ~/grn-guillermo/barrido.log
```

**No quites `--conservar`:** sin él, `barrido.py` borra al terminar la carpeta
del run con el modelo, y el paso siguiente (y el 5) ya no tiene qué copiar.

Al final imprime el F1 de dev y de test. **Ignora la línea «Reportado en el
servidor con la particion con fuga: dev 0.9024 / test 0.8721»**: es el modelo
de E. coli, otro organismo y otro test.

Para que `etapa2/clasificar.py` acepte el modelo, el `label_mapping.json` tiene
que estar junto a los pesos (`trainer.save_model()` no lo escribe):

```bash
RUN=~/grn-guillermo/runs/run_22_lr3e-5_ep8_bs16_wu0.1
cp "$GRN_DATOS/validacion/curada-v1/por_pmid/label_mapping.json" "$RUN/"
conda run -n pseudoRE python -c "import json, sys; print(json.load(open(sys.argv[1]))['id2label'])" "$RUN/config.json"
```

La última línea tiene que decir `{'0': 'activates', '1': 'no_relation', '2':
'regulates', '3': 'represses'}`, el mismo orden del `label_mapping.json`. El
modelo queda en la raíz de `$RUN`: el script carga el mejor checkpoint al
terminar y lo guarda ahí. Las subcarpetas `checkpoint-*` traen además el
estado del optimizador; se pueden borrar para liberar un par de GB:
`rm -r "$RUN"/checkpoint-*`.

Para terminar: `nvidia-smi` otra vez, confirma que no quedó ningún proceso
tuyo, y cierra la sesión de tmux con `exit`.

## Paso 5. Lo que vuelve a la laptop

Solo números. Revisa cada archivo con `cat` en el servidor antes de copiarlo.

```bash
# en la laptop; cambia /home/datos/grn-guillermo si tu GRN_DATOS quedó en otro lado
mkdir -p salidas/curada-v1
scp asesor:/home/datos/grn-guillermo/validacion/curada-v1/conteos.json salidas/curada-v1/
scp asesor:/home/datos/grn-guillermo/validacion/curada-v1/resultados/run_22_lr3e-5_ep8_bs16_wu0.1.json salidas/curada-v1/
scp asesor:grn-guillermo/runs/run_22_lr3e-5_ep8_bs16_wu0.1/test_metrics.json salidas/curada-v1/
scp asesor:grn-guillermo/runs/run_22_lr3e-5_ep8_bs16_wu0.1/eval_metrics.json salidas/curada-v1/
```

Y lo que imprimieron `datos-entrenamiento` y `particionar.py`, pegado en la
bitácora.

**Nunca vuelven**: la base, los `entity_marked_*.jsonl` (ni los de
`curada-v1` ni los de `por_pmid`), el modelo ni sus checkpoints. Los ejemplos
son oraciones etiquetadas con la base, y el modelo se entrenó con ella.

Al cerrar, una entrada fechada en `docs/bitacora.md`: commit, conteos,
métricas de dev y test, de cuántos artículos salió el test, y lo que quede por
decidir.

## Paso 6. Cautelas para leer el número

- **Es supervisión distante.** Un positivo es «este par, en una oración de un
  artículo que la base cita para esa relación»; la oración no tiene por qué
  afirmarla. Un negativo es «un par que la base no registra», no «un par sin
  relación»: la base no lo sabe todo. Las dos clases traen ruido, y el F1 se
  mide contra etiquetas con el mismo ruido.
- **La base está concentrada.** Cinco PMIDs sostienen el 32 % de las filas
  exigibles (PLAN.md 2.4). El tope de tres oraciones por artículo y par lo
  amortigua, y `datos-entrenamiento` imprime cuántos ejemplos reúnen los cinco
  artículos con más; aun así, al partir por PMID el test puede quedar en manos
  de pocos artículos. Si `particionar.py` avisa que una clase de test sale de
  menos de 5 artículos, la cifra honesta es la de validación cruzada:
  `particionar.py ... --por pmid --folds 5` y un `barrido.py --solo 22` por
  pliegue (`--datos .../fold_0`, `fold_1`, ...), con `--trabajo` y
  `--resultados` distintos para cada uno. Son cinco entrenamientos.
- **No se añaden `<e1>`/`<e2>` como tokens especiales.** El script del asesor
  no lo hace, y `etapa2/clasificar.py` rechaza un tokenizador que los traiga:
  las piezas serían otras y las probabilidades no se compararían con las del
  barrido.
- **Siempre `--labels_json`.** `barrido.py` lo pasa solo. Si alguna vez corres
  el script del asesor a mano y lo olvidas, su `LABELS_DEFAULT` intercambia
  `represses` con `no_relation` sin avisar.
- **No es comparable con el 0.87 de E. coli** (otro organismo, otro test, y
  aquel con fuga) **ni con el 44 %**, que es la precisión del bronce juzgada a
  mano sobre 50 candidatas; esas 50 están reservadas justamente para poder
  recalcularla con este modelo.

## Si algo falla

| síntoma | qué hacer |
|---|---|
| `La salida ... queda dentro del repositorio` | `--salida` bajo `$GRN_DATOS`, fuera del clon |
| `... dentro de una copia de trabajo de git` y señala tu home | el home es un repositorio de git: usa `/home/datos/grn-guillermo` |
| `A la base le faltan las columnas ...` | la primera hoja no es la de la base: `--hoja <nombre>` |
| `No salió ningún ejemplo` | mira los conteos: si «Filas que pueden dar positivos» es 0, la base no se leyó bien; si hay filas pero ningún par coincide, revisa que `pares.jsonl` sea el de la corrida 4 |
| `PARTICION RECHAZADA` | no entrenar; traer solo lo que imprimió |
| `CUDA out of memory` | regla de CLAUDE.md: si no cabe con lote 8 y 512 tokens, se detiene y se anota; la configuración del run 22 no se cambia sin decidirlo |
| `conda: command not found` | paso 0: la ruta completa a `conda` |
| el servidor no llega a GitHub | en la laptop `git bundle create grn.bundle --all`, `scp` del bundle y en el servidor `git clone grn.bundle download_abstract_pdf`: sigue siendo un clon, no una copia suelta |
