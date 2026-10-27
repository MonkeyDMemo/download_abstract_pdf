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
  - la huella que guarda cada `corrida.json` (`agente.huella_prompt`: el
    sistema más la plantilla del mensaje):
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
