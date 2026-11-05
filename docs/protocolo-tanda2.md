# Protocolo: lo que se mide en la tanda 2

Pre-registro de la tanda de prueba de la muestra ciega (rúbrica, enmienda 2).
Se commitea **antes** de correr cualquier medición sobre la tanda 2, y antes de
que una sesión de Claude vea un solo conteo suyo. Cualquier cambio posterior va
al final, como enmienda con fecha, y dice si es anterior o posterior a ver
alguna cifra.

## La muestra

- **De dónde sale:** 200 ítems de `salidas/revision/muestra200_t2/`, con la
  semilla 20261023. La población es de 2 670 oraciones, sin los artículos, los
  códigos ni las copias de las oraciones de la tanda 1.
- **Quién y cómo anota:** el experto, en la página de revisión, con la rúbrica
  v1 y sus enmiendas 1 y 2, después de la sesión «Calibración 2». La página
  registra el tiempo por ítem y rechaza `si` con `negada = si`.
- **Lo que no se hace:** nada se ajusta mirando la tanda 2. Ni reglas, ni
  umbrales, ni el prompt, ni el diccionario.

## Lo que se mide

**1. Las redes, con `precision-ciega` sobre la misma anotación.**

| red | cómo se arma | papel |
|---|---|---|
| oficial (`red.tsv`) | `red.py`, como hoy | la principal de la entrega |
| recomendada | `consolidar --perfil recomendado` | secundaria |
| `signo` | `consolidar --signo-lexico evidencias --voto-articulo --nombre signo` | **la principal del signo** |
| `signo_conservador` | `--signo-lexico aristas --voto-articulo` | secundaria |
| `signo_lexico` | `--signo-lexico evidencias`, sola | secundaria |
| `signo_articulo` | `--voto-articulo`, sola | secundaria |

Las redes de signo se arman en la laptop, sobre la carpeta de la corrida 4,
**antes** de que el experto termine la tanda 2. Sus huellas se anotan aquí en
una enmienda, antes de medir.

**Lo que hace cada regla** (`grn_red/signo.py`, `decisiones.md`):

- **`--signo-lexico evidencias`** da un voto léxico a cada evidencia que
  BioBERT dejó `regulates`. Es el control del punto 18 (`signo_cercano`).
- **`--signo-lexico aristas`** solo vota en las aristas sin ningún voto con
  signo de BioBERT. Los conflictos de `red.py` (votos + y − de BioBERT) no se
  tocan.
- **`--voto-articulo`** decide las aristas con votos + y −. Cada artículo vota
  por mayoría, y la arista va con la mayoría de los artículos. Si todos los
  artículos se abstienen, la arista sigue `regulates` y con `conflicto` = sí.

**Las comparaciones principales**, fijadas desde ya:

- **La precisión con dirección:** la red oficial contra el bronce, como en la
  tanda 1. Es la que confirma o no la tanda 1 sobre datos de prueba.
- **El signo:** `signo` contra la red oficial, sobre los mismos ítems, con la
  abstención como error y la diferencia pareada por bootstrap. Las dos redes
  tienen las mismas aristas y solo cambia el signo, así que la base es la
  misma.
- **Lo demás es secundario,** y se reporta sin elegir después la que mejor
  salga.

**De cada red se reporta:**
- la precisión con dirección del bronce (los 200) y de la red (los ítems cuya
  oración sostiene una arista), con su IC de Wilson;
- la diferencia pareada por bootstrap;
- la retención, del total y de las verdaderas;
- las inversiones;
- el acierto de signo con la abstención como error, «cuando lo da» y
  **«siempre +» sobre la misma base**.

**2. Ouroboros v0** (`grn_ouroboros`, exploratorio). El prompt se congela con un
commit y su huella antes de correr sobre la tanda 2.

| corrida | configuración | papel |
|---|---|---|
| principal | sin think, T = 0, semilla 42, `num_ctx` 4 096, `num_predict` 512, sin herramientas | la que se reporta primero |
| con think | T = 0.6, top_p 0.95, top_k 20, `num_ctx` 8 192 (q8_0 si no cabe), `num_predict` 4 096 | secundaria |
| con herramientas | la principal con `--herramientas todas` (o `buscar_locus`, si las demás no llegaron) | secundaria |
| tres semillas | la de think con las semillas 42, 43 y 44, si hay tiempo | variabilidad |

**De cada corrida se reporta** (`cli concordancia`):
- el acuerdo con el experto por campo;
- el κ en `relacion`;
- las matrices de confusión;
- las abstenciones, contadas como error;
- los fragmentos inválidos, marcados y no borrados;
- el tiempo por ítem;
- Ouroboros como filtro: su precisión y su retención frente al bronce.

## Sensibilidades, declaradas desde ya

- **Modelos entrenados con la base (curadas v1 y v2):** sin los ítems de
  artículos de su train ∪ dev (`precision-ciega --particion`, en el servidor).
  *E. coli*, con la misma exclusión, para comparar sobre los mismos ítems.
- **La página impide la negada anotada `si`,** así que la sensibilidad de la
  tanda 1 («negadas como `no`») debería dar 0 cambios. Se reporta igual.
- **El campo `tipo`** se compara sin salvedad en la tanda 2: la calibración 2
  repasó «activates» → `no_se`.

## Lo que no se puede concluir

- Una sola anotadora, sin κ entre humanos.
- Los intervalos tratan las oraciones como independientes. La tanda 2 no
  repite artículos de la tanda 1, pero varias oraciones de un mismo artículo
  sí pueden caer juntas.
- Ouroboros es exploratorio: su cifra no entra a la red ni a la entrega.

## Enmienda 1 (23-oct-2026): las huellas de las redes, antes de medir

Es anterior a ver cualquier cifra de la tanda 2. De las redes de signo solo se
conocen los conteos de cuántas aristas cambian, y ninguno dice si aciertan.

Las cuatro redes de signo se armaron en la laptop, sobre
`salidas/flujo/corrida4_run22`, con `main` en `456f1be`:

```bash
python -m grn_red.cli consolidar --carpeta salidas/flujo/corrida4_run22 \
    --signo-lexico evidencias --voto-articulo --nombre signo
#   lo mismo con --signo-lexico aristas --voto-articulo --nombre signo_conservador,
#   --signo-lexico evidencias --nombre signo_lexico
#   y --voto-articulo --nombre signo_articulo
```

| red | sha256 del `.tsv` | aristas con otro signo que `red.py` |
|---|---|---:|
| oficial (`red.tsv`) | `5f9dc6d4664548ee8cd56e7a3708b303ad850cf996c0b7c9755c13b55ed14946` | — |
| recomendada | `ab23197989729995774092aa0dde2879e079d9373150da863ddcb44226845731` | — |
| `signo` | `ff979bc97daba33cf28f0a13cd97fb7c80b685482965b02da8a1c8b98e349745` | 571 |
| `signo_conservador` | `888734efc38d3e31cf3fd847120ee33ec10c06004ef673dda7c08a2bf5049bb8` | 464 |
| `signo_lexico` | `76d94830a0428a6a318eff5ea318e54d01ba00ff8c0810ada625bbaaafd083b8` | 375 |
| `signo_articulo` | `62c802148f3fc81109d7f4a28007e15be93bee2429ffcb67da87c5410c8a3817` | 202 |

- **Las evidencias** de las cuatro redes de signo son las de `red.tsv`: el
  mismo `red_evidencias.tsv` byte a byte
  (`e6c54e56ea67a279f7f3f58e26e5de524d75bc7f2fde06ca06037b6ffbfeb4aa`). Solo
  cambia el signo de las aristas, así que los ítems que sostienen una arista
  son los mismos en las cinco y el signo se compara sobre la misma base.
- **La recomendada** tiene sus propias evidencias
  (`65f94c5fa0251c746a12477910a6543f7643f8c33ca01df4895d052eee659dec`).
- **Antes de medir** se comprueban estas huellas. Si una no coincide, la red se
  vuelve a armar con el mismo commit, o la diferencia se declara aquí.

## Enmienda 2 (23-oct-2026): la tanda 2 se anota con la página portátil

Es anterior a ver cualquier cifra de la tanda 2. Nadie ha anotado todavía: la
carpeta no tiene `anotaciones.jsonl`.

- **Cambia cómo se anota, no qué se mide.** El experto anota en un solo HTML,
  sin servidor (`revision_portatil.py`), y no en la pestaña «Revisión» del
  tablero. Lo hizo Hermes y entró al repositorio con pruebas.
  - Lleva solo las cuatro columnas de la hoja, nada de la llave.
  - Valida como `revision.validar`: rechaza `si` con negada = sí.
  - Exporta el mismo CSV que el tablero, byte a byte.
  - Las pruebas lo comprueban en node.
- **La página de la tanda 2:**
  - `salidas/revision/muestra200_t2/revision_tanda2.html`, generada con
    `python revision_portatil.py exportar-html --carpeta
    salidas/revision/muestra200_t2`;
  - 200 ítems, con la huella de la hoja `dcb5547596826331…`.
  - La guía que lleva dentro es `docs/guia-anotacion.md`.
- **El tiempo** se mide por tramos, como en el tablero. **Un tramo de más de 15
  minutos no se suma** y se cuenta en `tramos_largos`. El tablero aplica desde
  hoy el mismo tope, así que las dos miden igual.
  - `precision-ciega` reporta cuántos tramos quedaron fuera y en cuántos
    ítems.
  - Las horas son las del navegador de quien anota.
- **Lo que se recibe:**
  - el CSV que exporta la página, que lee `precision-ciega` tal cual;
  - o su respaldo, que `python revision_portatil.py desde-respaldo` convierte
    en el mismo CSV.
- **El κ entre humanos** no es de la tanda 2, que sigue con una sola
  anotadora. Sale de la segunda anotadora sobre 50 ítems de la tanda 1, y es
  exploratorio (bitácora del 23-oct).

## Enmienda 3 (27-oct-2026): el prompt de Ouroboros, congelado sin cambios

Es anterior a correr Ouroboros sobre la tanda 2. Lo que se vio antes son las
cifras de la calibración, que es sintética, y las de la tanda 1, que es de
desarrollo (bitácora del 27-oct).

- **El prompt v0 no se ajustó** con la calibración ni con la tanda 1. Se
  congela tal como entró en `e4d2071`, sin cambios:
  - `grn_ouroboros/prompts/anotador_v0.md`, sha256
    `0871a83924ca8bfe936434f9630a459b318d534aa0c7ef757c3282221ed77796`;
  - la huella que guarda cada `corrida.json` en el campo
    `identidad.entradas.prompt` (el sistema más la plantilla del mensaje):
    - sin herramientas, `2f80f09a5850fbf7860d8cb305dbf5fd47703b3aa97df86ab9cc72ace9d7ddcc`;
    - con `buscar_locus`, `c90cf9f2317ad4ea0a254a931c7ca60b455f9adcf5412a8cf1a57d06b412647c`.
  - Una corrida de la tanda 2 con otra huella no cuenta.
- **Las tres corridas sobre la tanda 2:**

  | corrida | configuración | papel |
  |---|---|---|
  | principal | sin think, T = 0, semilla 42, `num_ctx` 4 096, `num_predict` 512 | la que se reporta primero |
  | `buscar_locus` | la principal con `--herramientas buscar_locus` | secundaria |
  | con think | T = 0.6, top_p 0.95, top_k 20, `num_ctx` 8 192, `num_predict` 4 096, **caché KV q8_0** | secundaria |

- **Con think va con la caché q8_0** y `OLLAMA_FLASH_ATTENTION=1`. Con f16, el
  contexto de 8 192 no cabe en los 8 GB: ocupa 6.15 GiB, de los que solo
  5.33 quedan en VRAM y el resto se descarga a la CPU. Es la salida que la
  tabla de arriba ya preveía, y no recorta el contexto.
- **Las herramientas son solo `buscar_locus`.** `todas` necesita la base de la
  corrida 4, que no está en el servidor. Las otras cuatro pasan a la tesis,
  como estaba previsto si había atraso.
- **Las tres semillas no se corren.** Siguen siendo opcionales, si sobra
  tiempo, y entonces se reportan como variabilidad.
- **Cómo se reporta:** igual que en la tanda 1, con `concordancia` contra la
  exportación del experto, la abstención como error y el filtro con la llave.
  En la tanda 2, `tipo` se compara sin salvedad.

## Fe de erratas de la enmienda 3 (27-oct-2026)

Es anterior a ver cualquier cifra de concordancia de la tanda 2: nadie ha
abierto sus salidas.
- **Lo que decía:** que la huella era `agente.huella_prompt`. Esa es la
  función que la calcula.
- **Lo correcto:** el campo de `corrida.json` donde queda es
  `identidad.entradas.prompt`.
- **Lo que no cambia:** las huellas, ni nada de lo que se mide.

## Desviación 1 (30-oct-2026): una sesión de Claude vio un respaldo parcial del experto

Es anterior a medir cualquier cifra de la tanda 2.
- **Qué pasó.** Al compartir en el chat el respaldo de la página portátil
  (`respaldo_revision_dcb55475.json`), su contenido entró completo al contexto
  de la sesión «Hermes» (Claude). Su huella, `dcb55475…`, es la de la hoja de
  `muestra200_t2`. Trae, para los primeros 50 ítems anotados, el id, los juicios
  del experto (relación, dirección, signo, tipo, negada, especulativa y
  comentario) y sus horas. No trae oraciones, PMIDs, la llave ni predicciones.
- **Por qué no cambia lo que se mide.** Todo lo que se compara con el experto
  quedó congelado antes de que empezara a anotar, el 29-oct a las 22:36, hora
  del centro de México:
  - las redes y sus huellas, en la enmienda 1 (23-oct);
  - el prompt de Ouroboros, en la enmienda 3 (`451f20a`, 27-oct, 01:04);
  - las tres corridas de Ouroboros sobre la tanda 2, terminadas el 27-oct entre
    las 01:18 y las 02:14, con las huellas de la enmienda 3.

  Después de esto no se toca ningún parámetro, umbral ni prompt, y Hermes no
  analizó esos juicios.
- **Lo que se hace desde ahora.** Los archivos de la tanda 2 (respaldos y
  exportación) no se pegan ni se adjuntan en ninguna sesión de Claude. Se
  guardan en `salidas/revision/muestra200_t2/` y se procesan con los comandos
  de `docs/servidor-cierre.md`, que imprimen solo conteos.
- **Cómo se reporta.** En el informe va como desviación, junto a las cifras de
  la tanda 2.

## Enmienda 4 (4-nov-2026): un corte intermedio con los primeros 100 ítems

Es anterior a medir cualquier cifra de la tanda 2: nadie ha corrido
`precision-ciega` ni `concordancia` sobre ella.
- **El estado.** El experto lleva 100 de 200 ítems (respaldo exportado el
  2026-11-04 a las 00:39 UTC, huella de la hoja `dcb55475…`). Son exactamente
  las filas 1 a 100 de la hoja, cuyo orden quedó fijo en el sorteo del 23-oct,
  antes de anotar: el corte no se eligió. Incluye los 51 ítems de la
  desviación 1.
- **Por qué.** La revisión con el asesor del 6-nov.
- **Lo que se mide en el corte:** todo lo de «Lo que se mide», sobre esos 100
  ítems y con las mismas comparaciones principales, marcado «corte intermedio
  (100/200)». Antes de medir se comprobó que las seis redes y las evidencias
  de la recomendada siguen con las huellas de la enmienda 1.
- **Reglas:**
  - el corte no cambia nada: ni redes, ni umbrales, ni el prompt, ni la
    rúbrica;
  - el experto termina los 200, sin importar lo que salga y sin conocer
    ninguna cifra;
  - **la cifra de prueba es la de los 200.** El corte se reporta junto a ella,
    sin reemplazarla, y si difieren se reportan las dos;
  - el respaldo se convierte con `revision_portatil.py desde-respaldo` a
    `anotacion_experto_tanda2_corte100.csv`, que no se abre.

## Enmienda 5 (5-nov-2026): una configuración exploratoria de Ouroboros en Amazon Bedrock

Es anterior a correr cualquier modelo de Bedrock sobre cualquier hoja.

- **Qué.** Ouroboros con el prompt congelado de la enmienda 3
  (`anotador_v0.md`, sha256 `0871a839…`), sin herramientas y con la
  decodificación de la principal, pero con otro modelo: **Qwen3-235B-A22B-2507
  en Amazon Bedrock** (`qwen.qwen3-235b-a22b-2507-v1:0`, us-east-1). Es la
  misma familia que la principal (Qwen3-8B), unas 30 veces más grande. Un solo
  modelo: no se prueba otro ni se toca el prompt según lo que salga.
- **Por qué.** La principal tarda ~4 s por oración en la GPU del servidor, y la
  red completa no cabe en el tiempo del cierre. Además, la pregunta de si un
  modelo mayor de la misma familia juzga mejor.
- **Diferencias con la principal, declaradas:** el modelo y el proveedor; el
  formato de la respuesta va solo en el prompt, porque Bedrock no tiene el
  `format` de Ollama; se corre en paralelo, lo que no cambia el resultado (lo
  fija una prueba). Para Bedrock no aplican `think`,
  `format`, la semilla, `num_ctx`, `top_k` ni la caché KV; quedan la
  temperatura 0 y `max_tokens` = 512, el `num_predict` de la principal. A
  temperatura 0 Bedrock no garantiza la misma respuesta dos veces: **vale la
  primera corrida, y no se repite para escoger**.
- **Sobre qué corre:** la calibración (`6286017b…`), la tanda 1
  (`378168b0…`), **los 200 ítems de la tanda 2** (`dcb55475…`) y las hojas del
  paso `juez`: la red de agosto con tope de 3 oraciones por arista
  (`e60e7b37…`, 15,410 oraciones) y la de artículos nuevos.
- **Estatus: exploratorio.**
  - En los 100 ítems del corte (enmienda 4) la medición es exploratoria: sus
    juicios ya se conocen, aunque el modelo no los ve.
  - **Los ítems 101 a 200 son la prueba limpia:** sus predicciones quedan
    fijas antes de que el experto los anote.
  - La principal pre-registrada sigue siendo Qwen3-8B; esta no la reemplaza.
- **Lo que sale del laboratorio:** solo las columnas de la hoja (`id_item`,
  oración y entidades), oraciones de artículos públicos. Nunca la llave, los
  juicios del experto ni la base curada. Las credenciales de AWS viven solo en
  la laptop; nunca en el servidor compartido ni en el repositorio.
- **Regla para juzgar la red completa con este modelo:** en el corte de 100 de
  la tanda 2, su precisión como filtro no es menor que la de la principal
  (71.7 %) y retiene al menos el 80 % de las verdaderas. Si no la cumple, no
  juzga la red y se reporta igual.
- **Costo:** ~US$1 las tandas y ~US$12 la red de agosto con el tope, a precio
  de lista (US$0.22 y US$0.88 por millón de tokens de entrada y de salida).
- **Huellas:** el sistema y el mensaje son idénticos a los de la principal,
  así que la huella del prompt es la misma, `2f80f09a…`; la corrida se
  distingue por `proveedor`, `model_id` y `region` en `identidad.entradas`
  de su `corrida.json`. El código es el de este mismo commit, que es anterior
  a cualquier llamada a Bedrock.
- **Ceguera:** sigue la regla de `CLAUDE.md`: ninguna sesión de Claude abre la
  hoja de la tanda 2 ni lo que este modelo diga de ella; las sesiones solo ven
  las cifras de `concordancia`.

## Fe de erratas de la enmienda 5 (5-nov-2026)

Antes de correr cualquier hoja: **la región es us-west-2, no us-east-1.** En
us-east-1 Bedrock no ofrece `qwen.qwen3-235b-a22b-2507-v1:0`; en us-west-2
sí, y es la región de la cuenta. El modelo, el prompt, la decodificación y
todo lo demás de la enmienda siguen igual. La única llamada hecha antes de
esta corrección fue una prueba de acceso con un texto trivial, que no es de
ninguna hoja. La región por omisión del código pasa a us-west-2.

## Desviación 2 (5-nov-2026): la tanda 2 se queda en 100 ítems

- **Qué cambia.** El experto no anotará los ítems 101 a 200: lo decidió el
  responsable del proyecto, que lo financia, por costo. **La cifra de prueba
  de la tanda 2 es la del corte de 100** (enmienda 4), no la de 200. Las
  predicciones fijadas para los ítems 101 a 200 (enmiendas 3 y 5) quedan sin
  evaluar.
- **Cómo se miden desde ahora las mejoras del filtro** (el jurado de agentes,
  las reglas, los textos completos):
  - se diseñan y se ajustan **solo con la tanda 1** (desarrollo) y la
    calibración;
  - se congelan en una enmienda, con huellas, **antes** de correrlas sobre el
    corte de 100;
  - se miden **una vez** sobre el corte de 100, y se reporta lo que salga;
  - ninguna sesión de Claude abre la hoja de la tanda 2 ni las respuestas de
    los agentes sobre ella: solo las cifras de `concordancia`.
- **La salvedad.** Las cifras del corte de 100 ya se conocen (enmienda 4,
  desviación 1), aunque sus oraciones y juicios no se usan para diseñar: la
  prueba es menos limpia que la de unos ítems nunca medidos, y con 100 ítems
  solo se distinguen diferencias grandes (de unos 15 puntos).

## Enmienda 6 (5-nov-2026): el jurado de agentes, congelado antes de la tanda 2

Es anterior a correr el prompt v1 o cualquier juez del jurado sobre la tanda 2.
Todo se diseñó con la tanda 1 y la calibración (desviación 2).

- **El jurado.** Tres jueces en Amazon Bedrock (us-west-2), cada uno con el
  prompt v1 (`grn_ouroboros/prompts/anotador_v1.md`, sha256
  `e1885012b1e1b1bec04919208c6ee1599046be537933e9f308b7db11001c7f5f`) y con la
  oración anterior y la siguiente como contexto (`grn_ouroboros.cli contexto`,
  de la corrida 4 del bronce):
  - `openai.gpt-oss-120b-1:0`, configuración `razonador`, razonamiento medium
    (T 1.0, top_p 1.0, max_tokens 4096);
  - `openai.gpt-oss-20b-1:0`, la misma configuración;
  - `qwen.qwen3-235b-a22b-2507-v1:0`, configuración `principal` (T 0,
    max_tokens 512).
  Ninguno es Claude. El código es el de `fc95798`.
- **La regla de agregación** (`grn_verificacion.cli jurado`): relación `si`
  con **al menos 1 voto de 3**; la dirección es la mayoritaria entre los que
  dijeron `si` (puede voltear la del bronce; empate, `dudoso`). El umbral lo
  eligió en la tanda 1 una regla fijada antes de ver resultados: la mayor
  precisión que retenga al menos el 80 % de las verdaderas, con la dirección
  del bronce.
- **Lo que dio en la tanda 1 (desarrollo, optimista):** como filtro con la
  dirección del bronce, 88/94 = 93.6 % [86.8, 97.0], retiene 88/105 = 83.8 %;
  con reorientación, 113/120 = 94.2 %, retiene 113/144 = 78.5 %; relación
  73.2 % (κ 0.463). La principal local con el v0 dio 94.3 % y 62.9 %.
- **Lo que se mide en el corte de 100, una sola vez:**
  - **principal:** el jurado como filtro con la dirección del bronce,
    precisión y retención, contra la red oficial (47.8 %, 82.0 %) y la
    principal local con v0 (71.7 %, 84.6 %);
  - **secundarias:** el filtro con reorientación, el acuerdo por campo y
    cada juez por separado.
- **Regla de adopción:** el jurado reemplaza a la principal como juez del
  paso `juez` si en el corte de 100 su precisión no es menor que 71.7 % y
  retiene al menos el 80 %. Si no la cumple, se reporta igual y la principal
  sigue.
- **A temperatura 1 los gpt-oss no repiten la misma respuesta:** vale la
  primera corrida de cada juez sobre la tanda 2; no se repite para escoger.
- **Costo de referencia:** la tanda 1 completa costó US$0.47 con los tres.
