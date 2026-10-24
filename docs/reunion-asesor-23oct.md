# Entrega del servicio social — red de regulación de *P. aeruginosa*

Del 22 de octubre de 2026, actualizada el 23 con el contraste, el 44 % con los
tres modelos y la tanda 1. La reunión del 23 se canceló, y esta hoja reemplaza
el guion. **Cada decisión que estaba abierta va decidida por omisión**, con la
forma: «decidí X porque…; si prefiere Y, cambie el parámetro Z, y la cifra
pasa a W». Solo se pregunta lo que es permiso (§4).

Cada cifra dice de dónde sale: un archivo versionado, un commit o una salida
del flujo. Ninguna es de memoria. De la base curada aquí van solo conteos ya
publicados en `PLAN.md` §2.4 y en los informes filtrados del servidor: ninguna
fila, ninguna oración del laboratorio.

---

## 1. Fe de erratas del Documento de Tesis v1

El documento del 20 de octubre mezcla corridas y trae cifras redondeadas que
no son las medidas. Lo que dice, y lo que vale:

| dice (página) | vale | fuente |
|---|---|---|
| «488 221 menciones en seis tipos» (p. 23) | Es la corrida 1. El flujo usa la **corrida 4: 495 382 menciones en ocho tipos** (gen, proteína, operón, disparador, función, contexto regulatorio, evidencia, organismo). La misma tabla da 1 min 20 s y 19 746 con disparador; la corrida 4 da 1 min 31 s y 19 747 | `PLAN.md:78-79`; `salidas/flujo/corrida4_run22/*_resumen.csv`; `CLAUDE.md`, modelo de datos |
| «8 339 con regulador y blanco» (p. 23) | **En la corrida 4, 8 339 tienen regulador y 5 833 tienen regulador y blanco**; las 5 833 son las mismas de la corrida 1. Las otras 2 506 traen un solo TF y más de un blanco posible, así que el bronce deja el blanco vacío. La fila del resumen del bronce contaba solo el regulador y decía «y blanco»; se corrigió el 22-oct. Las 50 juzgadas salieron de las 5 833 | `grn_bronce/db.py`, `conteos_de`; CSV de candidatas de la corrida 4; `etapa2/evaluacion/muestrear_candidatas.py:15-16` |
| «Documentos procesados: 2 361 (918 texto completo, 1 436 solo resumen)» (p. 23) | 918 + 1 436 = 2 354, no 2 361. **Se procesaron 2 354 de los 2 361** del corpus: 7 no tienen resumen ni XML | `PLAN.md:70`, `PLAN.md:77`; resumen de la corrida 4 |
| «la base curada del laboratorio (~2 000 genes, ~3 500 interacciones)» (p. 6 y p. 8) | **5 584 interacciones, 3 006 locus distintos y 310 identificadores de referencia: 309 PMIDs y 1 DOI** | `PLAN.md:95`, `PLAN.md:101-102` |
| «Base curada: 5,584 interacciones, 310 PMIDs distintos» y «208 de 310 (67.1 %)» (p. 23) | Los 310 son 309 PMIDs y 1 DOI; el 67.1 % se calculó con 310 en el denominador | `PLAN.md:101` |
| «~53,600 líneas … (70 % indeterminado por scispaCy, corrida 4)» (p. 16) | **53 646 de 76 453** líneas de `sintaxis.jsonl` tienen voz indeterminada. Y no es el paquete `scispacy`: es **spaCy 3.7.5 con el modelo `en_core_sci_md`** 0.5.4 de scispaCy, en `.venv-nlp` | `docs/plan-sintaxis-bronce.md:107`, `:114-115`; `docs/hallazgos.md:186-188`; `CLAUDE.md`, restricciones |
| «Sintaxis (scispaCy)» (p. 23) y «análisis de dependencias (scispaCy)» (p. 7) | Igual: spaCy con `en_core_sci_md` | ídem |
| Signo del BioBERT: 87.6 % y 46.3 % puestos lado a lado | **Tienen denominadores y líneas base distintos.** *E. coli*: 92/105 = 87.6 %, contra «siempre activa» de 77.1 %. curada-v1: 38/82 = 46.3 %, contra 70.7 %. Una cifra de signo sin su denominador y su línea base no se compara | `salidas/flujo/corrida4_run22/evaluacion_oro.json:202-210`; `bitacora.md:29-30` |
| «BioBERT reentrenado: métricas por traer» (p. 22-23 y p. 25) | **Ya están, en dos versiones**: curada-v1 (16-oct) y curada-v2 (21-oct). Sección 3 | `docs/resultados-curada-v1.md`, `docs/resultados-curada-v2.md` |
| «Contraste formal (17–30 nov según plan)» (p. 25) | Contradice el calendario del mismo documento (p. 1), que pone el contraste del 21 al 27 de octubre. Vale el calendario | `PLAN.md:148` |
| CollecTF | **37.8 % (126/333)**. `bitacora.md:2377` dice 38.8 %: es una errata de la bitácora. `decisiones.md` cita esas dos líneas como 2094 y 2326, con la numeración anterior a la entrada del 20 y 21-oct | `bitacora.md:2145`; `decisiones.md`, entrada de CollecTF |

---

---

## 2. El estado en una frase

El servicio social cierra con la capa determinista:
- el pipeline corre de punta a punta;
- la red sale versionada, y sus reglas de consolidación son parámetros;
- el recall contra la base curada está medido: 41.2 % dirigido, sin el estrato
  BioBERT;
- la tanda 1 de la muestra ciega está anotada: la red sube la precisión del
  bronce de 53.0 % a 61.3 %, con la diferencia pareada en [+3.7, +12.6];
- **el signo de la red no le gana a decir siempre «activa»** cuando la
  abstención cuenta como error. En la tanda 1 da 42/60, contra 41/60; en la
  base curada, 319/605 contra 448/605. Cuando sí da signo, acierta más que la
  línea base en las dos;
- la tanda 2, de prueba, está sorteada y se anota en la página.

El LLM sobre la oración pasa a la tesis (`decisiones.md`, «El LLM sobre la
oración es trabajo de tesis»).

---

## 3. Lo que se entrega

| entregable | estado | cómo se reproduce |
|---|---|---|
| Pipeline: ETL, bronce y flujo | hecho; la segunda corrida sale toda «saltado» | `python flujo.py --corrida 4` |
| Red versionada | 8 827 aristas, y el paquete con 1 809 nodos (`nodos.tsv`, `red.graphml`, `manifiesto.json`) | el paso `paquete` del flujo |
| Reglas de consolidación como parámetros | por omisión, la red de `etapa2/red.py` byte a byte; la configuración recomendada en `red_recomendada.tsv` (§5, f) | `python -m grn_red.cli consolidar --carpeta C [--perfil recomendado]` |
| Invariantes de la corrida | `verificar` sale con 0 | `python -m grn_verificacion.cli verificar --carpeta C` |
| Recall contra la base curada | medido el 23-oct: dirigido 41.2 % (642/1 560) sin el estrato BioBERT; regla b) con XML 30.2 % (259/859); §5 d | `docs/contraste-curada.md` |
| Precisión en una muestra ciega | tanda 1 (desarrollo) anotada: 198 de 200; tanda 2 (prueba) sorteada sin los PMIDs ni los códigos de la tanda 1; rúbrica con enmiendas 1 y 2; calibración v1.2 de 27 ítems | `cli muestra --tandas 1 --fraccion-doble 0 [--excluir-muestra D]`; la pestaña «Revisión» (`servidor.py --revision`); `cli precision-ciega` |
| Informe (formato FES Zaragoza) | se redacta en noviembre | — |

**La precisión es pareada.** Sobre los mismos 200 ítems salen dos cifras:
- **la del bronce**, que se compara con el 44 %;
- **la de la red final**, sobre los ítems cuya oración sostiene una arista.

Junto a la de la red va su retención. El anotador no ve ninguna salida de
modelo.

**Tanda 1** (el experto, con la red de *E. coli*):

| | con dirección | sin exigirla |
|---|---|---|
| bronce, los 198 anotados | **53.0 % (105/198) [46.1, 59.9]** | 72.7 % |
| red, los 142 cuya oración sostiene una arista | **61.3 % (87/142) [53.1, 68.9]** | 77.5 % |

- **La diferencia pareada,** red menos bronce, es **[+3.7, +12.6]** puntos,
  por bootstrap. Se calcula sobre los mismos ítems.
- **La red retiene** el 71.7 % del total y el **82.9 % de las verdaderas
  (87/105)**.
- **La pérdida más grande son las inversiones:** 39 de 144 relaciones
  verdaderas (27.1 %) [20.5, 34.9] tienen la dirección contraria a la que
  propuso el bronce. Entre las que la red retiene son 23 de 110 (20.9 %).
- **El signo de la red,** con «siempre +» sobre los mismos ítems:

  | | la red | «siempre +» |
  |---|---|---|
  | cuando da signo (48) | 42/48 = 87.5 % [75.3, 94.1] | 35/48 = 72.9 % |
  | con la abstención como error (60) | 42/60 = 70.0 % [57.5, 80.1] | 41/60 = 68.3 % |

  - Con la abstención como error, **empatan**.
  - El 70.7 % que se citaba antes era la base del bronce (53/75), no la de la
    red.
  - Tomar el signo por (par, oración) no movió ninguna de las dos cifras de la
    red.
- **Sensibilidad.** Con las 5 negadas anotadas `si` tratadas como `no`, el
  bronce da 51.0 % y la red 59.9 %, con diferencia [+4.3, +13.2]. La
  conclusión no cambia.
- **Normalización.** Se corrigieron solo códigos: 46 direcciones vacías pasaron
  a `ninguna` y 43 signos `0` a `?`.

**El tiempo del anotador.** La tanda 1 se anotó en la hoja CSV y no tiene
tiempos, ni por bloque, lo que es una desviación del protocolo (rúbrica,
enmienda 2). La tanda 2 se anota en la página, que registra el tiempo por ítem:
será el primer dato de esfuerzo.

### El BioBERT reentrenado con la base curada: v1 (16-oct) y v2 (21-oct)

| | v1 | v2 | *E. coli* (8-oct) |
|---|---:|---:|---:|
| validación cruzada: macro-F1 | 0.4917 | 0.4853 | — |
| diferencia contra la memorización del par, IC95 | +0.110 [0.022, 0.193] | +0.104 [0.022, 0.182] | — |
| F1 activates / no_relation / represses | 0.49 / 0.70 / 0.28 | 0.55 / 0.73 / 0.18 | — |
| red de la corrida 4: aristas (activación / represión) | 1 025 (236 / 744) | 4 003 (3 412 / 380) | 8 827 |
| oro: exhaustividad | 93/144 = 64.6 % | 135/144 = 93.8 % | 137/144 = 95.1 % |
| oro: acierto de signo | 38/82 = 46.3 % | 90/126 = 71.4 % | 92/105 = 87.6 % |
| «siempre activa» en esas mismas filas | 70.7 % | 70.6 % | 77.1 % |
| criterio 2 de la enmienda 1 | no | no (p = 0.47) | sí |
| las 50 juzgadas: precisión del filtro | 5/9 = 55.6 % [26.7, 81.1] | 16/28 = 57.1 % [39.1, 73.5] | 16/37 = 43.2 % |
| las 50 juzgadas: correctas que retiene, de 22 | 5 | 16 | 16 |

Fuente: `bitacora.md:21-31`; `resultados-curada-v1.md:197`,
`resultados-curada-v2.md:200`; para *E. coli*,
`evaluacion_oro.json:202-240`.

**Lectura.** Las dos versiones superan a la línea base de memorización: leen
algo de la oración, y la ventaja está en los pares nuevos (0.48 contra 0.23 en
la v1, `resultados-curada-v1.md:244`). **Ninguna lee el signo.** Con pesos, el
sesgo va a la represión; sin pesos, a la activación, y el 71.4 % de la v2 es
lo que da contestar siempre «activa». Según la regla de la enmienda 1, escrita
antes de entrenar la v2, **ninguna reemplaza al modelo de *E. coli***
(`protocolo-curada-v1.md:243-285`; `bitacora.md:33-43`).

La enmienda 1 es **posterior a ver las cifras de la v1**: la comparación v1
contra v2 es exploratoria (`protocolo-curada-v1.md:245-248`).

**Sobre las 50 juzgadas** (el 44 %, recalculado el 23-oct en el servidor):
- **La v2 filtra mejor que *E. coli*:** con la misma retención, 16 de las 22
  correctas, acepta 28 y no 37.
- **La v1 retiene solo 5 de las 22.**
- **El signo de la v2:** 9/12 = 75 % contra 73.3 % de «siempre +», que tampoco
  es k/12. `evaluar` ya da cada acierto con su línea base sobre los mismos
  ítems. Con *E. coli*:
  - cuando da signo, 11/11 contra 9/11;
  - con la abstención como error, 11/15 contra 11/15. El 73.3 % es esa base.
  - Las curadas se recalculan en el servidor.
- **La v2 se eligió después de ver las 50,** así que es exploratoria.
- **El par visto al entrenar** (memorización; `evaluar --particion`): 12 de
  las 50 tienen el par visto.
  - En la v2, 5/8 con el par visto y 11/20 sin él. En la v1, 2/3 y 3/6.
  - El bronce sin filtro también acierta más en los vistos (6/12 contra 16/38).
    Son más fáciles para todos, así que **no hay evidencia de memorización**.
  - El signo de la v2 con la abstención como error da 9/15, contra 11/15 de
    «siempre +».
- **La tanda 1 sin los artículos del entrenamiento de las curadas**
  (`precision-ciega --particion`):
  - **Lo que se excluye:** 92 PMIDs, 30 ítems. Quedan 169 anotados.
  - **Bronce:** 86/169 = 50.9 %.

  | modelo | red, con dirección | retiene de las verdaderas | diferencia pareada |
  |---|---|---|---|
  | *E. coli* | 73/121 = 60.3 % [51.4, 68.6] | 84.9 % | [+4.7, +14.9] |
  | curada v2 | 70/112 = 62.5 % [53.3, 70.9] | 81.4 % | [+6.2, +17.3] |
  | curada v1 | 10/13 = 76.9 % [49.7, 91.8] | 11.6 % | [+2.1, +47.9] |

  - **La v2 no supera a *E. coli*** sobre ítems limpios: las diferencias caen
    dentro de los intervalos.
  - **Su signo empata con «siempre +»** (39/53 contra 39/53).
  - **La v1 descarta casi todo.**
  - Esto sostiene la decisión g: el flujo sigue con *E. coli*.

---

## 4. Permisos

**Concedido el 23-oct.** El asesor dio su visto bueno para operar el servidor
por SSH con llave. Con eso, la sesión «Hermes» corrió el contraste
(`docs/contraste-curada.md`) y el 44 % con los tres modelos, siempre con
informes filtrados: sin filas, locus ni PMIDs. Las cifras están en el §3 y en
el §5 d y g. Las candidatas nuevas se quedan en la carpeta confidencial.

**Lo que falta preguntar:**
1. **¿Se puede usar Bedrock?**
   - Por omisión, no: todo corre local, con Ollama en el servidor, y ningún
     juez es Claude.
   - Si lo autoriza, Ouroboros podría comparar contra un modelo grande. Hoy no
     hace falta.
2. **¿Se publican las oraciones de evidencia y los juicios del experto?**
   - Por omisión, no: hasta decidirlo, los juicios no van al repositorio
     público. Lo publicable son las cifras.
   - Si lo autoriza, se puede versionar la hoja anotada con sus oraciones,
     que son del corpus público.

---

## 5. Decisiones tomadas por omisión

**a) La rúbrica, con los siete puntos de su §9 tal como están.**
- **Decidí eso porque** formalizan el juicio de las 50 y dejan comparable el
  44 %.
- **Si prefiere** que «X activates Y» sea `directa` (el eje del 4-sep): cambie
  la regla del §3.3. Cambia solo la columna `tipo`, y ninguna cifra de
  precisión.
- **Si prefiere** que otro organismo sea `si` y no `dudoso` (§9, punto 3): esos
  ítems pasan al numerador. La cifra se recalcula con `precision-ciega`
  cambiando esa celda de la hoja.

**b) Un anotador experto, sin parte doble.**
- **Decidí eso porque** es un servicio social, con un anotador pagado por
  hora. Sin parte doble no hay κ, y eso se reporta como limitación (rúbrica,
  enmienda 1).
- **Si prefiere** medir la concordancia: se sortea en otra carpeta con
  `--fraccion-doble 0.25`. Salen las mismas oraciones (hay una prueba que lo
  exige) y 50 ítems para una segunda persona, unas 1.5 horas más.

**c) CollecTF como segunda referencia, fuera de la base de conocimiento y de `es_tf`.**
- **Decidí eso porque** es una red curada: consultarla desde la plata sería
  confirmar contra la respuesta.
- **Lo medido:** de las 572 marcas `es_tf`, 29 traen `collectf` y ninguna
  depende solo de esa fuente, así que excluirla cambia 0 marcas.

**d) El contraste**, con el método de `docs/contraste-curada.md`, corrido el
23-oct.
- **Denominador: 2 077 exigibles.** Son 1 562 en el corpus (859 con XML y 703
  solo abstract) y 46 de autorregulación.
  - PLAN §2.4 daba 2 003. La conciliación es 2 077 = 2 003 − 6 + 80, contada
    en el servidor.
  - Las 6 son filas sin dos locus válidos (5 578 de 5 584).
  - Las 80 citan el artículo excluido junto con otro. `motivo_de` excluye una
    fila solo si **todos** sus PMIDs están en el archivo de exclusiones: son
    651 frente a 731.
  - Ninguna fila de homología cita el artículo excluido.
- **Cobertura del bronce:**
  - regla b) con XML, 30.2 % (259/859) [27.2, 33.3];
  - 24.8 % sin la expansión de operones;
  - regla a), 43.1 % en todas.
- **La red:**
  - **dirigido,** sin el estrato BioBERT, 41.2 % (642/1 560) [38.7, 43.6];
  - **orientación,** 95.3 % (642/674): Histórica 505/536 y Ambos 137/138;
  - **el techo de la regla a)** en esas 1 560 es 720 (46.2 %). Las 674 que la
    red encuentra en alguna dirección caen todas dentro: 0 fuera;
  - **el signo,** con «siempre activa» sobre los mismos ítems:
    - cuando lo da, 319/366 [83.3, 90.2], contra 280/366 (76.5 %);
    - con la abstención como error, 319/605 (52.7 %) contra 448/605 (74.0 %).
      **Ahí la red pierde,** porque el 39.5 % se queda sin signo;
  - **candidatas nuevas:** 7 849 pares que la base no registra, reportados como
    candidatas y no como hallazgos.
- **Las cifras de la fase 2,** confirmadas con `main` el mismo día
  (`servidor-cierre.md` §2 a §4). Dan lo mismo que la primera corrida, hecha
  con el código aún sin revisar.
- **Tablas** (5 artículos, 672 filas):
  - 3 de los 5 no tienen XML: 367 filas.
  - En el 2.º, de 191 filas, a 188 les falta del XML al menos uno de los dos
    locus. Lo probable es que la base cite su material suplementario.
  - Ninguna fila tiene los dos locus en una misma tabla.

**e) La evidencia de PA14 se anota como cualquier otra, con su cepa en el comentario.**
- **Decidí eso porque** es *P. aeruginosa* (rúbrica, paso 5 del árbol), y la
  marca permite apartarla después.
- **Hoy no hay mapeo PA14 → PAO1:** los 377 locus `PA14_#####` (837
  menciones) siguen fuera del diccionario.
- **Si prefiere** excluirla: en el paso 5 pase la cepa a `dudoso`. La cifra
  se recalcula con los ítems que lleven «cepa PA14».

**f) La red oficial es la de `etapa2/red.py`, y la recomendada va al lado.**
- **Decidí eso porque** es la que ya se evaluó (oro, signo, contraste), y
  cambiarla mueve todas esas cifras.

| | por omisión (`red.tsv`) | recomendada (`red_recomendada.tsv`) |
|---|---:|---:|
| aristas | 8 827 | 10 592 |
| observadas / expandidas de operones | 8 827 / 0 | 9 059 / 1 533 (de 541 aristas a 146 operones) |
| autorregulaciones | 0 (se excluyen) | 341, marcadas |
| con 1 artículo / con 2 o más | 6 252 / 2 575 | 7 393 candidatas / 3 199 de soporte múltiple |
| activa / reprime / regula | 2 594 / 1 591 / 4 642 | 3 302 / 1 976 / 5 314 |
| conflictos de signo | 537 | 666 |

- **Diferencias entre las dos:**
  - la recomendada conserva la autorregulación marcada (`--autorregulacion
    marcar`);
  - etiqueta el nivel de soporte (`--nivel-soporte`);
  - expande cada arista a un operón en una por gen, con el catálogo del paso 1
    y la arista original como procedencia (`--operones expandir`, la D9 de
    `operones-asesor.md`).
- **El signo y los umbrales son los de `red.py` en las dos:** mayoría de 0.66
  y conflicto marcado; umbrales 0.65 / 0.70 / 0.60, sin calibrar.
- **Si prefiere la recomendada como red oficial,** las reglas ya son
  parámetros (`grn_red.cli consolidar`). Falta que el paquete y la evaluación
  lean `red_recomendada.tsv`, que es un cambio pequeño en `flujo.py`.
- **Su contraste,** medido el 23-oct (`contraste --red recomendada`):
  - **Las aristas:** de las 10 592, se omiten y se cuentan las 1 533
    expandidas, que no tienen evidencia propia.
  - **Los pares:** da 9 012 pares de locus, uno más que `red.tsv`, y el mismo
    dirigido, 642/1 560.
  - **El signo:** 313/360 cuando lo da, contra 276/360 de «siempre activa».
    Con la abstención como error, 313/605.
  - **Por qué baja el signo:** sus autorregulaciones marcadas le cambian el
    signo a 28 pares que `red.tsv` ya tenía. Por eso queda 313 y no 319.

**g) El modelo del flujo sigue siendo el de *E. coli*.**
- **Decidí eso porque** ninguna versión curada cumple el criterio 2 de la
  enmienda 1 (tabla del §3).
- **El signo se decide con la muestra ciega:** `precision-ciega` mide el del
  bronce y el de la red contra el anotador. En la tanda 1, la red acierta 42/48
  cuando da signo. El signo léxico y el voto por artículo entran como
  parámetros apagados (§5 j), y se miden en la tanda 2.
- **Si prefiere** otro modelo: `flujo.py --modelo <checkpoint>`. Toda la
  cadena se rehace por huella.

**h) Decisión 3 de operones: la pertenencia solo anota.**
- **Decidí eso porque** sigue sin respuesta escrita, y usarla como rasgo
  arriesgaría evaluar con la fuente que pudo construir la referencia.
- **La pregunta, si quiere contestarla:**

> ¿Hubo filas de la base curada inferidas por pertenencia a operón? Es decir,
> si un artículo dice «LasR activa el operón rhlAB», ¿se registró solo lo que
> dice el artículo, o también una fila por cada gen del operón? Basta con sí,
> no o no lo sé.

- Las demás decisiones de operones (D1 a D9) siguen en `operones-asesor.md`
  §7. La D9 es la expansión de la red recomendada.

**i) El LLM sobre la oración pasa a la tesis**, con su puerta de decisión
(`plan-tesis-plata-llm.md`). En el servicio social no se usa EC2.
- **Ouroboros v0 se adelanta como comparación exploratoria:** un CLI aparte, en
  el servidor, con qwen3:8b local y fuera del flujo y de la red.
- **Decidí** las herramientas apagadas por omisión y la corrida principal sin
  think, con T = 0. Con think, T = 0.6, como secundaria.
- **El código está desde el 23-oct** (`grn_ouroboros`, `docs/ouroboros-v0.md`)
  y corre en el servidor (`servidor-cierre.md` §7). Lo decidido por omisión al
  construirlo:
  - una respuesta truncada, sin JSON válido o fuera de la rúbrica es
    abstención, y cuenta como error en todos los campos;
  - con herramientas, el esquema va en el prompt y no restringido, porque la
    restricción impediría llamarlas;
  - `--num-ctx` y `--kv-cache` se pueden cambiar por corrida, y entran a la
    llave de la caché. El tipo de caché KV se declara, porque Ollama no lo
    informa.
- **Su cifra no entra a la red ni a la entrega:** es una comparación.
- **Si prefiere** que juzgue con herramientas: `--herramientas todas`. La
  corrida queda como secundaria, porque un juez que sabe más que el experto
  deja de medir lo mismo (`decisiones.md`).

**j) El signo de la red como parámetro, apagado por omisión.**
- **Decidí** el voto léxico por evidencia como regla principal, que es la
  lectura literal de «cuando la predicción sea `regulates`».
- **La variante por arista va como secundaria.** Solo vota en las aristas sin
  ningún voto con signo de BioBERT: 4 105 de las 4 642 que `red.py` dejó
  `regulates`.
  - Las otras 537 son conflictos de BioBERT (votos + y −), y no se tocan.
  - Con la lectura amplia, 36 de esos conflictos cambiarían de signo.
- **Voto por artículo:** solo en las aristas con votos + y −. Cada artículo
  vota con su mayoría, y la arista con la mayoría de los artículos.
  - Si todos los artículos se abstienen, la arista sigue `regulates` y con
    `conflicto` = sí. En la corrida 4 son 170.
  - Contarlas como conflictos resueltos inflaría lo que logra la regla.
- **Si prefiere otra,** se cambia `--signo-lexico` en `grn_red.cli
  consolidar`. Ninguna toca la red oficial.
- **Las cifras salen de la tanda 2,** con la abstención como error y contra
  «siempre +» sobre la misma base.

**k) La tanda 1 es de desarrollo y la tanda 2 de prueba.**
- **Decidí eso porque** la tanda 1 ya se vio. Una regla nueva ajustada mirándola
  inflaría su cifra (rúbrica, enmienda 2).
- **Cómo:** la tanda 2 excluye los PMIDs, los códigos y las copias de las
  oraciones de la tanda 1, y nada se ajusta mirándola.
  - Los 152 PMIDs de la tanda 1 se llevan 2 214 oraciones, así que la tanda 2
    sale de 2 670.
  - Se comprobó: 0 artículos, 0 códigos y 0 pares compartidos. Para el bronce y la red por omisión, que se fijaron antes,
  la tanda 1 sí es de prueba.

---

## 6. Qué decir y qué no

- No «el BioBERT reentrenado da 0.49 de F1». Sí: «0.49 de macro-F1 en
  validación cruzada contra 0.38 de memorizar el par, +0.110 [0.022, 0.193];
  contra etiquetas de supervisión distante, no contra juicio humano».
- No «la v2 corrige el signo». Sí: «la v2 acierta 90 de 126 (71.4 %), lo
  mismo que contestar siempre "activa" (70.6 %, p = 0.47)».
- No «la v1 mejora al de *E. coli*». Sí: «la v1 acierta el signo en 38 de 82
  (46.3 %), debajo de "siempre activa" (70.7 %); *E. coli* 92 de 105 (87.6 %)
  contra 77.1 %».
- No «87.6 % contra 46.3 %» como si fueran comparables. Sí: cada una con su
  denominador y su línea base.
- No «el 0.49 es peor que el 0.87 de *E. coli*». Sí: «no se comparan: otro
  organismo, otro test, y aquel con fuga» (`resultados-curada-v1.md:276`).
- No «el modelo nuevo ya está en el flujo». Sí: «sigue el de *E. coli*;
  ninguna versión cumple el criterio 2 de la enmienda 1».
- No «la sintaxis orienta las candidatas». Sí: «orienta 10 299 de 76 453
  pares (13.5 %) y recuperó 1 de 4 invertidas, sin romper ninguna de las 22;
  queda informativa» (`plan-sintaxis-bronce.md:109`; `hallazgos.md:190-194`).
- No «la alineación v2 resuelve la sintaxis». Sí: la cifra C1-C4 de esta
  noche con su antes, el 11 % de los pares.
- No «la precisión del pipeline es 44 %». Sí: «44.0 % (22/50, IC95 [31.2,
  57.7]) del bronce, juzgada a mano; con el BioBERT de *E. coli* y umbral,
  16/37 = 43.2 %: el filtro no la sube» (`PLAN.md:89`, `PLAN.md:180`).
- No «la base curada tiene ~3 500 interacciones». Sí: «5 584 filas, de las
  que 2 077 son exigibles con la regla versionada (2 003 en PLAN §2.4)».
- No «el signo de la red acierta 87.2 %» sin su base. Sí: «319/366 cuando da
  signo, contra 280/366 de "siempre activa"; con la abstención como error,
  319/605 contra 448/605».
- No «el signo de la red le gana a la línea base». Sí: «cuando da signo, sí
  (42/48 contra 35/48 en la tanda 1). Con la abstención como error, empata en
  la tanda 1 (42/60 contra 41/60) y pierde contra la base curada (319/605
  contra 448/605)».
- No «la precisión subió del 44 % al 53 %». Sí: «53.0 % [46.1, 59.9] en la
  tanda 1, contra 44.0 % [31.2, 57.7] en las 50. Son muestras distintas y los
  intervalos se solapan».
- No «la red es más precisa» sin la retención. Sí: «61.3 % contra 53.0 %, con
  la diferencia pareada en [+3.7, +12.6], y retiene el 82.9 % de las
  verdaderas».
- No «el LLM saca 91.4 % y por eso va el multiagente». Sí: «91.4 % en 93
  oraciones difíciles de un solo subsistema; para decidir si entra hace falta
  una puerta que no cabe en el servicio social» (decisión i).

---

## 7. Lo que sigue

| cuándo | qué | depende de |
|---|---|---|
| hoy | «Calibración 2»: 12 ítems, unos 30 minutos (`calibracion-anotacion.md` v1.2) | — |
| unas 6 horas de anotación | la tanda 2, en la pestaña «Revisión», con el tiempo por ítem | la calibración 2 |
| en el servidor (Hermes) | §0 a §6 hechos el 23-oct con `main`: todo coincide. Sigue §7, Ouroboros: calibración, tanda 1 y, con el prompt congelado, la tanda 2 (`docs/servidor-cierre.md`) | la fase 4, ya en `main` |
| antes de evaluar la tanda 2 | `docs/protocolo-tanda2.md`: qué se mide y con qué reglas, commiteado | las fases 3 y 4 |
| al terminar la tanda 2 | `precision-ciega` sobre la tanda 2: bronce, red, el signo como parámetro y Ouroboros | la tanda 2 |
| noviembre | el informe del servicio social | todo lo anterior |
