# Entrenar el BioBERT con la base curada

Guía de la pista D en el servidor del asesor: construir ejemplos de
entrenamiento a partir de la base curada del laboratorio, partirlos por PMID
sin fuga y reentrenar el BioBERT con la configuración del run 22.

Todo va en un solo comando, `python -m grn_verificacion.cli reentrenar`, que
corre los tres pasos en orden. Lo puede lanzar el usuario o una sesión de
Claude abierta en el servidor (autorizado el 9-oct-2026, con el asesor
avisado). Se puede dejar corriendo en segundo plano, sobrevive a un corte de
SSH y al final escribe un `RESULTADOS.md` con conteos y métricas, sin rutas ni
contenido de la base. Ese archivo es lo que se lee, se trae y se publica:
**nada se copia y pega de la terminal.**

**La base curada, los ejemplos que salen de ella y el modelo entrenado se
quedan en el servidor.**

## Lo que no se negocia

- **El contenido de la base no entra a ninguna sesión de Claude.** El código
  la recibe por ruta (`--base`) e imprime solo conteos. Lo mismo vale para los
  `entity_marked_*.jsonl` y para el modelo: son oraciones etiquetadas con la
  base, y un modelo entrenado con ella. Una sesión de Claude corre
  `reentrenar` y lee solo `reentrenar estado` y `RESULTADOS.md`, que pasan por
  un filtro. Nunca abre con Read, `cat` o `head` el `.xlsx`, `datos/` ni
  `runs/`. Las reglas deny de `.claude/settings.local.json` (paso 1) frenan a
  sus herramientas de lectura, no a un comando: la regla de conducta es la que
  manda.
- **La cuenta del servidor es compartida.** En el home hay carpetas de otras
  personas: no se entra, no se lista su contenido y no se escribe en ellas.
  `~/pseudomonas-trn` es del asesor: se lee y se corre su script de
  entrenamiento, nada más.
- **El entorno conda `pseudoRE` es del asesor.** Se usa para correr, llamando
  a su intérprete directo (`~/miniforge3/envs/pseudoRE/bin/python`). No se
  instala, actualiza ni desinstala nada en él. Nuestro código es biblioteca
  estándar y Python 3.8, así que no le pide nada; torch y transformers ya
  están ahí.
- **Los perfiles de shell son de todos.** No se toca `~/.bashrc` ni
  `~/.profile`: las variables van en un archivo propio (paso 1).
- **La GPU es compartida** (RTX 3070, 8 GB). `reentrenar` revisa antes de
  lanzar que haya al menos 6 500 MiB libres; si no los hay, no entrena y lo
  dice. Un entrenamiento que pasa de 4 horas se detiene solo (CLAUDE.md).
- **El host y la cuenta no van en este repositorio, que es público.** Por eso
  lo que se publica es `RESULTADOS.md`, que se comprueba sin rutas antes de
  escribirse, y no lo que imprimió la terminal.

## Qué hace `datos-entrenamiento`

Es supervisión distante (`grn_verificacion/entrenamiento.py`):

- **Positivo**: un par del corpus público cuyo regulador y blanco, llevados a
  locus PA####, coinciden con una fila de la base, en una oración de un
  artículo que esa fila cita. `+` da `activates`, `-` da `represses`,
  `Unknown` o vacío da `regulates`. Un operón cuenta por sus genes.
- **No dan positivos**: las filas de homología (el artículo citado no reporta
  la relación, PLAN.md 2.4), las de `Origen` BioBERT (las propuso el modelo del
  asesor; «Ambos» sí entra), las `d`, las filas de autorregulación (regulador
  igual a blanco) y los pares que en un mismo artículo reciben dos etiquetas
  (un `Unknown` junto a un `+` también es conflicto).
- **Negativo** (`no_relation`): otro par de esos mismos artículos que la base
  no registra en ninguna dirección, contando también las filas de homología y
  de BioBERT. Uno por cada positivo, elegidos con la semilla.
- **Tope**: tres oraciones por (artículo, par), para que un artículo de
  revisión no domine.
- **Reservas**: lo que se aparta para evaluar no entra ni como positivo ni
  como negativo (paso 1).

Todo lo que imprime son conteos: ni oraciones, ni genes, ni locus, ni PMIDs.

## Dónde queda cada cosa

Todo vive en la carpeta propia, fuera del clon:

```
~/grn-guillermo/                  700
  GRN_experimental.xlsx           600   la base: nunca se abre ni se copia
  pares.jsonl, reservas.tsv             entradas, no confidenciales
  entorno.sh                            las variables (paso 1)
  download_abstract_pdf/                el clon
  datos/curada-v1/                700   CONFIDENCIAL: entity_marked_*, conteos.json,
                                        sin_regulates/ (sin la clase excluida), por_pmid/
                                        y por_pmid_k5/ (los pliegues)
  runs/curada-v1/                 700   CONFIDENCIAL: el modelo entrenado; barrido/ con lo
                                        que escribe barrido.py (lleva rutas); prediccion/ y
                                        cv/fold_i/ con resultados y predicciones por semilla
                                        (las predicciones llevan tf y target; los modelos de
                                        pliegue se borran después de predecir)
  resultados/curada-v1/           700   lo que se lee: RESULTADOS.md, estado.json,
                                        reentrenar.log (filtrado) y, solo con números,
                                        entrenamiento.json, curva.json, prediccion.json,
                                        entrenamiento_cv.json y evaluacion.json
```

`curada-v1` es el `--nombre` de la corrida. Otro nombre arma otras tres
carpetas y no toca estas.

## Paso 1. Preparar (una vez)

Por SSH, en el servidor (o en la terminal de la sesión de Claude que corre
ahí). Los comandos llaman `asesor` al servidor; el host y la cuenta se
definen en el `~/.ssh/config` de la laptop, que no se versiona.

**El clon y los permisos:**

```bash
cd ~/grn-guillermo/download_abstract_pdf
git fetch && git checkout flujo-biobert && git pull --ff-only   # o main, cuando se fusione
git rev-parse --short HEAD                                       # el commit que va a la bitácora
chmod 700 ~/grn-guillermo && chmod 600 ~/grn-guillermo/GRN_experimental.xlsx
```

Si el servidor no llega a GitHub: en la laptop, `git bundle create grn.bundle
flujo-biobert main`, `scp` del bundle, y en el servidor `git clone grn.bundle
download_abstract_pdf` y `git checkout flujo-biobert`. Sigue siendo un clon y
no una copia suelta; para actualizarlo, otro bundle y `git pull
../grn.bundle flujo-biobert`.

**Las variables**, en un archivo propio que se carga en cada sesión:

```bash
cat > ~/grn-guillermo/entorno.sh <<'EOF'
export PY=$HOME/miniforge3/envs/pseudoRE/bin/python
export RAIZ=$HOME/grn-guillermo
export BASE_CURADA=$HOME/grn-guillermo/GRN_experimental.xlsx
export SCRIPT_ASESOR=$HOME/pseudomonas-trn/04_modelling/bio_bert_re_finetune.py
EOF
source ~/grn-guillermo/entorno.sh
```

El heredoc va entre comillas: `$HOME` se escribe tal cual y se expande cada
vez que se carga el archivo.

**La base curada, si no está en el servidor.** Es el único archivo
confidencial que viaja, y viaja una sola vez: de la laptop directo a
`~/grn-guillermo/`, fuera del clon (el repositorio es público, y un archivo
dentro del clon se puede commitear por error). La copia la haces tú, no una
sesión de Claude. En la laptop, desde PowerShell, la huella (un hash, no el
contenido) y la copia:

```powershell
Get-FileHash -Algorithm SHA256 "<ruta local del .xlsx>"
scp "<ruta local del .xlsx>" asesor:grn-guillermo/GRN_experimental.xlsx
```

En el servidor, ciérrala y comprueba que llegó entera:

```bash
chmod 600 ~/grn-guillermo/GRN_experimental.xlsx
sha256sum ~/grn-guillermo/GRN_experimental.xlsx   # el mismo hash, en minúsculas
```

`chmod 600` la cierra a las otras cuentas de la máquina, no a quien entre con
la misma cuenta compartida. Si se queda o se borra al terminar, lo decide el
asesor.

**Las reservas.** Lo que no puede entrar al entrenamiento:

- los 46 PMIDs y las 50 oraciones de la muestra de juicios con la que se
  recalcula el 44 %;
- las 182 oraciones distintas (198 filas) del conjunto ciego de la trampa del
  signo.

Si entraran, la cifra nueva mediría memoria y no precisión. Se regeneran con
el código del clon:

```bash
cd ~/grn-guillermo/download_abstract_pdf
$PY -m grn_verificacion.cli reservas --ciego etapa2/auditoria_signo.tsv \
    --salida ~/grn-guillermo/reservas.tsv
```

Tiene que decir 46 PMIDs y 232 oraciones distintas. `reentrenar` comprueba
además que las reservas cubran toda la muestra de juicios, y si no, se niega a
seguir.

Formato, por si hay que sumar algo:

- Texto UTF-8, una reserva por línea, `tipo<TAB>valor`.
- `pmid` aparta el artículo entero.
- `oracion` aparta esa oración en cualquier artículo. Se compara con los
  espacios normalizados, y también aparta toda oración del corpus que la
  contenga o que esté contenida en ella, si el texto contenido mide 40
  caracteres o más. El bronce y el conjunto ciego no siempre cortan igual: 8
  de las 182 llegan a la corrida 4 cortadas de otra forma.
- Las líneas que empiezan con `#` son comentarios.
- Un tipo desconocido o un PMID que no es número detienen la corrida, a
  propósito: una reserva ignorada en silencio dejaría entrar justo lo que se
  quería apartar.

**Las reglas deny**, para que una sesión de Claude no abra por descuido la
base ni lo que sale de ella. Van en `.claude/settings.local.json` del clon y
en `~/grn-guillermo/.claude/settings.local.json`; los dos están fuera de git.
Las rutas absolutas llevan doble barra:

```json
{"permissions": {"deny": [
  "Read(//<home>/grn-guillermo/GRN_experimental.xlsx)",
  "Read(//<home>/grn-guillermo/datos/**)",
  "Read(//<home>/grn-guillermo/runs/**)",
  "Read(//<home>/grn-guillermo/**/entity_marked_*.jsonl)",
  "Edit(//<home>/grn-guillermo/GRN_experimental.xlsx)",
  "Edit(//<home>/grn-guillermo/datos/**)",
  "Edit(//<home>/grn-guillermo/runs/**)"]}}
```

`<home>` es la ruta del home sin la barra inicial; no se escribe aquí porque
lleva el nombre de la cuenta.

**Antes de darle la base**, las pruebas con el Python del servidor. Son datos
sintéticos y no leen la base:

```bash
$PY -m unittest grn_verificacion.test_validacion grn_verificacion.test_entrenamiento grn_verificacion.test_reentrenar
```

Tiene que terminar en `OK`.

## Paso 2. Tramo 1: datos y partición (segundos, sin GPU)

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
$PY -m grn_verificacion.cli reentrenar correr --raiz "$RAIZ" --nombre curada-v1 \
    --pares "$RAIZ/pares.jsonl" --reservar "$RAIZ/reservas.tsv" \
    --ciego etapa2/auditoria_signo.tsv --hasta particion --folds 5
```

`--base` y `--script` salen de `BASE_CURADA` y `SCRIPT_ASESOR`. `regulates`
queda fuera por omisión (`--excluir-etiqueta`, ver el protocolo). Con
`--folds 5` arma también los pliegues de la validación cruzada y su línea
base, sin entrenar. Al terminar se lee
`~/grn-guillermo/resultados/curada-v1/RESULTADOS.md`. Qué revisar ahí:

1. **La base contra PLAN.md 2.4** (sección 3). Se coteja contra lo medido el
   10-sep:
   - 5 584 filas;
   - signo `+` 4 060 (4 059 más el `+, +`), `?` 909 (786 `Unknown` más 123
     vacías), `-` 598, `d` 14, ilegible 3 (los locus corridos);
   - origen Histórica 4 824, BioBERT 544, Ambos 216, **otro 0**;
   - homología 2 850; 309 PMIDs distintos, 1 fila sin PMID y 1 DOI (PLAN.md
     dice «310 PMIDs»: son 310 identificadores, porque la fila sin PMID es
     justo la del DOI; conciliado el 15-oct).

   **Si algo no coincide, la corrida se detiene y no se entrena.** Puede ser
   otra versión de la base o el lector, que hasta esta pista solo se había
   probado con `.xlsx` sintéticos. Se decide con el asesor. Seguir con
   `--aceptar-base-distinta` es una decisión que queda anotada.
2. **Los ejemplos** (sección 4). Las líneas de reservas y de pares tienen que
   decir exactamente:

   ```
   Reservas: PMIDs 46; oraciones 232; archivos leídos 1.
   Pares: leídos 72969; reservados por PMID 6839 (artículos reservados presentes: 46); reservados por oración 516; sin locus 411; con un locus fuera de PAO1 0; con el marcado roto 0.
   ```

   Si no, se usó otro `pares.jsonl` u otro `reservas.tsv`.
3. **La partición** (sección 5). Tiene que estar limpia. Los avisos se leen
   así:
   - Una clase sin ejemplos en dev o en test, o la «celda más flaca» con menos
     de 5 artículos, quiere decir que la cifra honesta es la de validación
     cruzada: el tramo 2 va con `--folds 5`.
   - `particionar.py` nombra una sola celda para dev y test juntos, y en un
     empate nombra dev. Que diga «dev» no quiere decir que test esté bien.
   - Un `casi-dup` distinto de cero no tumba la partición, pero es fuga real
     que el corte por PMID no evita: la cifra de test va con esa salvedad.
   - Que `regulates` falte en dev y en test no es un aviso: quedó fuera antes
     de particionar, y la sección lo dice con sus ejemplos y artículos.
4. **Los pliegues** (sección 5.1): artículos y ejemplos por clase del test de
   cada pliegue, y la línea base de memorización fuera de pliegue, que es la
   cifra contra la que se compara el modelo. Se conoce antes de entrenar y va
   al protocolo.
5. **La fuga por par** (sección 6): qué parte de dev y de test tiene su par
   ya visto en train, y cuánto acierta una línea base que solo recuerda el
   par. Ver el paso 5.

El tramo 1 se puede repetir: lo que no cambió se salta.

## Paso 2b. El protocolo, antes del tramo 2

`docs/protocolo-curada-v1.md` fija qué se mide, la regla de decisión, las
semillas y los pliegues. Su sección 2 se llena con los conteos de las
secciones 4, 5 y 5.1 del `RESULTADOS.md` del tramo 1. Después se commitea, y
el usuario lo aprueba **antes** de lanzar el tramo 2. Al asesor se le avisa
por escrito de la exclusión de `regulates`.

El informe del tramo 2 dice el commit del protocolo y si es anterior al inicio
de la corrida. Si no lo es, o si el archivo tiene cambios sin commitear, la
sección 10 avisa que las cifras de la sección 8 no son pre-registradas. Una
vez commiteado, el protocolo cambia solo por enmienda fechada (su sección 12).

## Paso 3. Tramo 2: entrenar (en segundo plano)

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
$PY -m grn_verificacion.cli reentrenar correr --raiz "$RAIZ" --nombre curada-v1 \
    --pares "$RAIZ/pares.jsonl" --reservar "$RAIZ/reservas.tsv" \
    --ciego etapa2/auditoria_signo.tsv --folds 5 --semillas 42,43,44 --desprender
```

Es la corrida del protocolo, con su commit anterior a este comando (paso 2b).
Entrena 16 modelos, en este orden:

1. **El desplegable** (partición única, semilla 42). Predice su test con
   `etapa2/clasificar.py`, en CPU, y coteja la accuracy contra la del script.
   Si no cuadran, se detiene (`cotejo_clasificar`).
2. **Los 15 de la validación cruzada**, semilla por semilla (42, 43, 44) y
   pliegue por pliegue. Cada uno entrena, predice su test en CPU y se borra.
   Sus predicciones se quedan en `runs/`.
3. **La evaluación**: el bootstrap del protocolo, en segundos.

Con los 446 s que tardó el run 22, son entre 1 h y 1 h 40 min de GPU, más
entre 10 y 25 min de predicción en CPU. Mientras corre, se mira el avance con
`estado`, no las métricas (protocolo, sección 9).

`--desprender` lo deja corriendo en su propia sesión: no hace falta tmux, que
el servidor no tiene, y un corte de SSH o el cierre de la sesión de Claude no
lo matan. Se salta lo que el tramo 1 ya hizo. Antes de tocar la GPU, revisa
que haya memoria libre, que el intérprete vea CUDA (el script del asesor
entrenaría en CPU sin avisar) y que BioBERT cargue sin red desde la caché. Si
algo falla, no entrena y lo dice.

Para ver cómo va, y para detenerlo:

```bash
$PY -m grn_verificacion.cli reentrenar estado  --raiz "$RAIZ" --nombre curada-v1
$PY -m grn_verificacion.cli reentrenar detener --raiz "$RAIZ" --nombre curada-v1
```

`estado` muestra el estado de cada paso y las últimas líneas del log, ya
filtradas. `detener` detiene el árbol entero, con el script del asesor dentro,
y deja el estado en «cancelado». No basta con matar un PID: en la cuenta
compartida todos los procesos son del mismo usuario, y matar solo al padre
dejaría el entrenamiento huérfano con la GPU tomada.

Detalles de cómo entrena:

- La configuración es la del run 22, `run_22_lr3e-5_ep8_bs16_wu0.1`: tasa
  3e-5, 8 épocas, lote 16, calentamiento 0.1, weight decay 0.01, 512 tokens,
  semilla 42, sobre `dmis-lab/biobert-base-cased-v1.1`, con pesos de clase y
  paro temprano de paciencia 2, igual que el barrido del asesor. `barrido.py`
  le pasa siempre `--labels_json` con el `label_mapping.json` de la partición.
- El modelo queda en `~/grn-guillermo/runs/curada-v1/run_22_lr3e-5_ep8_bs16_wu0.1`,
  con `label_mapping.json` junto a los pesos, que es lo que pide
  `etapa2/clasificar.py`. Antes de darlo por bueno se verifica que su
  `id2label` sea activates, no_relation, regulates, represses. Los
  `checkpoint-*` se borran.
- Si el entrenamiento se corta (`detener`, el tope de 4 h, un corte de luz),
  relanzar el mismo comando repite solo el modelo que se cortó. Los que ya
  tienen resultado y predicciones se saltan, aunque sus modelos de pliegue ya
  no estén. El script del asesor no puede reanudar a mitad de un
  entrenamiento, pero el run 22 tardó 446 s con 1 242 ejemplos, así que
  rehacerlo cuesta poco. Antes de repetirlo, `reentrenar` borra el intento a
  medias.
- Un modelo de pliegue se borra solo después de predecir. Si `clasificar.py`
  falla, el modelo se queda, y al relanzar solo se predice.
- Agregar una semilla después (`--semillas 42,43,44,45`) entrena solo la
  nueva, pero es una desviación del protocolo y el informe la lista.
- Si `barrido.py` falla, sale con 0 de todos modos. `reentrenar` no se fía del
  código de salida: sin el JSON del resultado no hay éxito.
- Relanzar cuando ya está todo entrenado (para agregar `--ciego`, o para
  rehacer el informe) no pide GPU, y `RESULTADOS.md` conserva las métricas del
  run 22, marcadas como de una corrida anterior. Lo mismo vale para el tramo 1
  después de entrenar, mientras la partición no cambie. Las de la validación
  cruzada se conservan solo con los mismos `--folds` y `--semillas`: con
  otros, el informe diría unos parámetros y mostraría cifras de otros. La
  evaluación se recalcula en cada corrida completa: son segundos.
- Con `--desprender`, la ruta de la base viaja en el entorno del proceso y no
  en su línea de comandos, que cualquier cuenta de la máquina ve con `ps`. Lo
  que se puede comprobar antes de lanzar (archivos, nombre, otra corrida en
  marcha) se comprueba en primer plano; si el proceso muere al arrancar, la
  terminal dice por qué.
- Si cambia la partición, el modelo anterior no se borra antes de
  reentrenar: queda en `run_22_….anterior`, por si el reentrenamiento falla.
- Para detener, `reentrenar detener`, nunca `kill -9`. Un `kill -9` al
  orquestador deja el entrenamiento vivo y sin tope; `estado` lo avisa y
  `detener` lo limpia.

## Paso 4. Lo que se trae y se publica

`RESULTADOS.md` ya está hecho para publicarse. Antes de escribirlo,
`reentrenar` comprueba que no traiga rutas (ni absolutas ni con `~/`), locus,
marcadores de entidad ni nada con forma de PMID; si algo no pasa, no lo
escribe y lo dice el estado. Del conjunto ciego trae solo totales por parte:
desglosados por etiqueta dirían qué registra la base de seis pares con nombre
público. Al terminar:

```bash
# en el servidor, desde el clon
cp ~/grn-guillermo/resultados/curada-v1/RESULTADOS.md docs/resultados-curada-v1.md
git add docs/resultados-curada-v1.md && git commit -m "docs: resultados del reentrenamiento curada-v1"
```

En `docs/bitacora.md` va una entrada fechada con el commit, las cifras
principales y lo que quede por decidir. Con las mismas cifras se llena la
ficha, `docs/modelo-curada-v1.md`. Las cifras se toman del `RESULTADOS.md`,
que ya va en el repositorio, y no de la terminal.

**Nunca salen del servidor:** la base, los `entity_marked_*.jsonl` (ni los de
`datos/` ni los de `por_pmid/`), el modelo y sus checkpoints. Tampoco
`reentrenar.err` sin revisar: es lo único que no pasa por el filtro (los
errores del propio orquestador), y `estado` lo muestra filtrado.

## Paso 5. Cómo leer el número

- **Es supervisión distante.** Un positivo es «este par, en una oración de un
  artículo que la base cita para esa relación»; la oración no tiene por qué
  afirmarla. Un negativo es «un par que la base no registra», no «un par sin
  relación»: la base no lo sabe todo. Las dos clases traen ruido, y el F1 se
  mide contra etiquetas con el mismo ruido.
- **Partir por PMID no impide memorizar el par.** Aquí la etiqueta depende
  casi solo del par: uno que la base registra nunca sale como `no_relation`, y
  uno que no registra nunca sale como relación. Si el mismo par cae en train y
  en test, el modelo puede acertar por el nombre sin leer la oración. Por eso
  `RESULTADOS.md` trae una línea base que solo recuerda el par, y lo que vale
  es **cuánto le gana el modelo**, no su F1 a secas. El argumento con que la
  ficha del modelo descartaba este riesgo en E. coli (176 de 332 pares con más
  de una etiqueta) aquí no aplica.
- **La trampa del signo ya no es una evaluación externa para este modelo.**
  Reservar sus 182 oraciones no aparta sus 6 pares (MexR, NalC, NalD, NfxB,
  MexZ y MexL, todos `represses`): si la base los registra, entran desde otras
  oraciones con su etiqueta. `RESULTADOS.md` cuenta cuántos entraron. Un
  acierto alto en la trampa con este modelo no prueba que lea el signo.
- **La proporción de clases no es la del flujo.** Hay una `no_relation` por
  positivo, de los artículos que la base cita. En el flujo, el modelo
  clasifica todos los pares de la corrida 4 (72 969, de 1 444 artículos, la
  mayoría no citados por la base), y ahí los pares sin relación son muchos
  más. Con la misma tasa de falsos positivos, la precisión de las tres clases
  de relación será menor que en test.
- **La cifra principal es el macro-F1 sobre tres clases fijas**
  (`activates`, `no_relation`, `represses`; protocolo, sección 5). El script
  del asesor promedia sobre las clases presentes en cada test, que cambian de
  un pliegue a otro. Su cifra sale por pliegue en la sección 8.5, para
  compararla con su barrido, pero no es la principal.
- **La base está concentrada.** Cinco PMIDs sostienen el 32 % de las filas
  exigibles (PLAN.md 2.4). El tope de tres oraciones por artículo y par lo
  amortigua, y `RESULTADOS.md` dice cuántos ejemplos reúnen los cinco
  artículos con más. Aun así, al partir por PMID el test puede quedar en manos
  de pocos artículos.
- **La validación cruzada es la cifra** (sección 8 de `RESULTADOS.md`):
  - Se juntan las predicciones de test de los 5 pliegues de cada semilla. Cada
    ejemplo aparece una vez, predicho por un modelo que no vio su artículo. Se
    calcula el macro-F1 de cada semilla y se reporta la media de las tres, con
    su desviación.
  - El intervalo al 95 % es un bootstrap que remuestrea artículos, no
    ejemplos.
  - Lo que decide es la diferencia contra la línea base de memorización,
    pareada en las mismas réplicas. El modelo la supera solo si el límite
    inferior de su intervalo es mayor que 0.
  - Cada pliegue entrena con el 60 % de los artículos (dev y test son 20 %
    cada uno), así que su cifra no se compara punto a punto con la del reparto
    80/10/10.
  - Los pliegues no conservan su modelo; el que queda es el de la partición
    única, y su test (sección 7.1) es descriptivo.
- **No se añaden `<e1>`/`<e2>` como tokens especiales.** El script del asesor
  no lo hace, y `etapa2/clasificar.py` rechaza un tokenizador que los traiga:
  las piezas serían otras y las probabilidades no se compararían con las del
  barrido.
- **Siempre `--labels_json`.** `barrido.py` lo pasa solo. Si alguna vez corres
  el script del asesor a mano y lo olvidas, su `LABELS_DEFAULT` intercambia
  `represses` con `no_relation` sin avisar.
- **No es comparable con el 0.87 de E. coli** (otro organismo, otro test, y
  aquel con fuga) **ni con el 44 %**, que es la precisión del bronce juzgada a
  mano sobre 50 candidatas. Esas 50 están reservadas justamente para poder
  recalcularla con este modelo: eso es otra corrida del flujo
  (`flujo.py --modelo` apuntando al modelo nuevo), y como el modelo no sale
  del servidor, corre ahí.

## Paso 6. Probar el modelo en el flujo

La validación cruzada dice si el modelo lee la oración. Lo que importa para la
red es cómo se comporta sobre los pares del corpus, y sobre todo el signo. La
prueba son los 72 969 pares de la corrida 4 (`pares.jsonl`): unos 3 minutos en
la GPU, más la red y el patrón de oro.

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
C=$RAIZ/flujo/corrida4_curada-v1           # una carpeta por modelo, fuera del clon
(umask 077; mkdir -p "$C") && cp "$RAIZ/pares.jsonl" "$C/"
$PY -m grn_verificacion.cli biobert --carpeta "$C" --python $PY --sin-registrar \
    --modelo "$RAIZ/runs/curada-v1/run_22_lr3e-5_ep8_bs16_wu0.1"
$PY etapa2/red.py --predicciones "$C/predicciones.jsonl" --pares "$C/pares.jsonl" \
    --salida "$C/red.tsv" --evidencias "$C/red_evidencias.tsv" --informe "$C/red_informe.json"
$PY etapa2/evaluar_oro.py --red "$C/red.tsv" --pares "$C/pares.jsonl" \
    --predicciones "$C/predicciones.jsonl" --red-informe "$C/red_informe.json" \
    --salida "$C/evaluacion_oro.tsv" --resumen "$C/evaluacion_oro.json"
```

- **Una carpeta por modelo, con nombre propio.** Todos los checkpoints de
  `reentrenar` se llaman `run_22_…`, así que `flujo.py --modelo` les daría la
  misma carpeta, y la red y la capa de uno pisarían las del otro.
- **`--sin-registrar`:** el servidor no tiene la base del corpus.
- **Las predicciones se quedan en el servidor.** Sobre los pares que
  entraron al entrenamiento repiten etiquetas de la base. A la sesión llegan
  solo los conteos de `red_informe.json` y `evaluacion_oro.json`.
- **Qué mirar en el oro:** `honesto.acierto_signo` y
  `veredicto_del_signo.despega_de_las_dos_lineas_base`. El signo tiene que
  ganarle también a «siempre activa», no solo al azar (enmienda 1 del
  protocolo).
- **El 44 %** necesita además el bronce de la corrida 4: la carpeta
  `salidas/flujo/corrida4_run22` de la laptop.

**Entrenar sin pesos de clase:** `reentrenar correr ... --sin-pesos-de-clase`,
con otro `--nombre` (la v2 fue `curada-v2`). Un resultado entrenado con otros
pesos no se reusa, y el informe lista `pesos_clase` como desviación.

## Si algo falla

`reentrenar estado` dice el motivo. Lo que hay que hacer en cada caso:

| motivo | qué hacer |
|---|---|
| `reservas_incompletas` | regenerar `reservas.tsv` (paso 1) |
| `reservas` | el archivo de reservas está mal escrito: el estado dice la línea |
| `datos` | lo dice el detalle. «No encuentro el archivo de --base»: revisa `BASE_CURADA`. «A la base le faltan las columnas ...»: la base no está en la primera hoja, o tiene un título arriba de los encabezados. No abras el `.xlsx` para averiguarlo: pídele al asesor el nombre exacto de la hoja y usa `--hoja '<nombre>'` (`--hoja 1` busca una hoja llamada «1»). Si el detalle dice que se omitió, corre `cli datos-entrenamiento` a mano en el servidor para verlo |
| `base_distinta` | no entrenar; llevar el cotejo de `RESULTADOS.md` al asesor |
| `particion_rechazada` | no entrenar; `particion.txt` dice dónde quedó la fuga |
| `gpu_ocupada` | alguien usa la GPU: esperar y relanzar. Lo hecho no se repite. Sale también si el entrenamiento murió al arrancar con «CUDA error: out of memory» o «CUBLAS_STATUS_ALLOC_FAILED»: en ese punto el modelo apenas ocupa memoria, así que la tenía otro |
| `sin_cuda`, `modelo_no_en_cache` | revisar `$PY` y la caché de Hugging Face; no se instala nada en `pseudoRE` |
| `sin_memoria_gpu` | regla de CLAUDE.md: si no cabe con lote 8 y 512 tokens, se detiene y se anota. La configuración del run 22 no se cambia sin decidirlo, y `barrido.py` no tiene lote 8 |
| `tope` | pasó de 4 h: anotarlo en la bitácora; no se relanza sin decidirlo |
| `script_fallo`, `matado` | el log (`estado --lineas 60`) muestra el final de la salida del script |
| `id2label` | el modelo quedó con otro orden de etiquetas: no se usa |
| `sin_modelo` | el entrenamiento terminó sin pesos: relanzar lo repite (un resultado sin modelo no se reusa) |
| `test_invalido` | algún ejemplo de test no tiene el marcado que exige `clasificar.py`; el estado dice cuántos, nunca cuáles. Sale en el tramo 1, al particionar, antes de gastar GPU. Es un defecto de `datos-entrenamiento`: se corrige antes de seguir |
| `prediccion_fallo` | `clasificar.py` no dejó predicciones válidas: el log dice por qué. Relanzar solo predice, porque el modelo se queda |
| `cotejo_clasificar` | la accuracy de `clasificar.py` y la del script no cuadran en el modelo desplegable: la unión de predicciones con ejemplos, o el orden de etiquetas, está mal. No se lee ninguna cifra hasta corregirlo (protocolo, sección 9) |
| `parametros_distintos` | ya hay un resultado de esta partición con otro `max_length`: usar otro `--nombre` |
| `disco`, `gpu_no_disponible` | falta disco libre, o `nvidia-smi` no respondió: resolverlo y relanzar |
| `inesperado` | un error del orquestador: el traceback, filtrado, está en el log |
| `otra_corrida` | otra corrida viva usa las mismas carpetas sin el candado (alguien borró `.candado`): `estado` y `detener` |
| `informe_no_publicable` | `RESULTADOS.md` traía algo que no se puede publicar y no se escribió; el estado dice qué patrón y en qué línea |
| `estado` dice «quedan N procesos de esta corrida sin orquestador» | el orquestador murió a la fuerza (`kill -9`) y el entrenamiento siguió sin tope: `reentrenar detener` |
| `ruta_en_repositorio` | `--raiz` cae dentro de una copia de git: usa una carpeta fuera |
| ya corre una corrida (código 4) | `estado` para verla; `detener` si quedó colgada |

## Apéndice: los mismos pasos a mano

Para depurar un paso suelto, en primer plano. Rigen las mismas reglas de
arriba, y nada de esto se pega en la bitácora: la salida trae rutas del
servidor. Para dejar un entrenamiento corriendo, `reentrenar --desprender`, que
es lo que sabe detener el árbol entero.

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
D=$RAIZ/datos/a-mano
$PY -m grn_verificacion.cli datos-entrenamiento --pares "$RAIZ/pares.jsonl" \
    --base "$BASE_CURADA" --reservar "$RAIZ/reservas.tsv" --salida "$D"
$PY etapa2/particionar.py --entrada "$D" --salida "$D/por_pmid" --por pmid
$PY -u etapa2/barrido.py --datos "$D/por_pmid" --script "$SCRIPT_ASESOR" \
    --trabajo "$RAIZ/runs/a-mano" --resultados "$RAIZ/resultados/a-mano" \
    --solo 22 --conservar
```

Ctrl-C en esa terminal detiene a `barrido.py` y al script del asesor, que
están en su mismo grupo. `barrido.py` sale con 0 aunque falle: el éxito es que
exista `$RAIZ/resultados/a-mano/run_22_lr3e-5_ep8_bs16_wu0.1.json`. Después
hay que copiar `label_mapping.json` de la partición junto a los pesos.
