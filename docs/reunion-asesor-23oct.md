# Entrega del servicio social — red de regulación de *P. aeruginosa*

Del 22 de octubre de 2026. La reunión del 23 se canceló, y esta hoja reemplaza
el guion. **Cada decisión que estaba abierta va decidida por omisión**, con la
forma: «decidí X porque…; si prefiere Y, cambie el parámetro Z, y la cifra
pasa a W». Solo se pregunta antes lo que es permiso (§4).

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
- el recall contra la base curada está listo para correr;
- la muestra ciega de 200 está sorteada, con su rúbrica, su calibración, su
  página de revisión y su cálculo de precisión.

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
| Recall contra la base curada | script probado con bases sintéticas; falta correrlo (§4) | `docs/contraste-curada.md` |
| Precisión en una muestra ciega | 200 sorteadas de 4 864 (semilla 20261024); rúbrica con enmienda 1, calibración de 21 ítems; falta anotar | `cli muestra --tandas 1 --fraccion-doble 0`; la pestaña «Revisión» (`servidor.py --revision`); `cli precision-ciega` |
| Informe (formato FES Zaragoza) | se redacta en noviembre | — |

**La precisión es pareada.** Sobre los mismos 200 ítems salen dos cifras:
- **la del bronce**, que se compara con el 44 %;
- **la de la red final**, sobre los ítems cuya oración sostiene una arista.

Junto a la de la red va su retención. Con la red de hoy, 144 de las 200
oraciones sorteadas sostienen una arista (72 %, IC95 [65.4, 77.8]). Sus pares
están en la red por cualquier oración en 194 de 200 casos. El anotador no ve
ninguna salida de modelo.

**El tiempo del anotador** se registra por ítem en la página y por bloque de 25
en la hoja. Es el primer dato de esfuerzo.

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

---

## 4. Lo único que se pregunta: permiso para correr en su servidor con la base curada

1. **El contraste** (`docs/contraste-curada.md`): el recall del bronce y de la
   red contra la base curada.
   - Lo que mide: exigibles sin homología, con el estrato `Origen` BioBERT
     aparte y el PMID B excluido por archivo.
   - Lo que vuelve: solo el informe filtrado (`CONTRASTE.md`), sin filas,
     locus ni PMIDs. Las candidatas nuevas se quedan en la carpeta
     confidencial.
2. **La evaluación externa:** el 44 % con los tres modelos (*E. coli*, curada
   v1 y v2), con `flujo.py --modelo` en el servidor.
   - Hace falta subir la carpeta del flujo de la corrida 4.
   - Las salidas se quedan en el servidor; vuelven solo conteos.

| respuesta | qué hacemos |
|---|---|
| sí, a las dos | Se corren y la hoja se completa con el recall y el 44 % por modelo |
| solo el contraste | La ficha de la curada queda con la validación cruzada como única cifra |
| no | El recall queda con el cruce del 10-sep (`PLAN.md` §2.4) |

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

**d) El contraste**, con el método de `docs/contraste-curada.md`. Las cifras
llegan con el permiso del §4.

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

**g) El modelo del flujo sigue siendo el de *E. coli*.**
- **Decidí eso porque** ninguna versión curada cumple el criterio 2 de la
  enmienda 1 (tabla del §3).
- **El signo se decide con la muestra ciega:** `precision-ciega` mide el del
  bronce y el de la red contra el anotador.
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
  que 2 003 son exigibles al pipeline».
- No «el LLM saca 91.4 % y por eso va el multiagente». Sí: «91.4 % en 93
  oraciones difíciles de un solo subsistema; para decidir si entra hace falta
  una puerta que no cabe en el servicio social» (decisión i).

---

---

## 7. Lo que sigue

| cuándo | qué | depende de |
|---|---|---|
| al arrancar la anotación | sesión de calibración con las 21 sintéticas y la rúbrica v1.1 congelada | — |
| unas 6 horas de anotación | los 200 ítems, por la pestaña «Revisión» o por la hoja CSV | la calibración |
| al terminar | `precision-ciega` sobre lo anotado: bronce, red y retención | la anotación |
| con su permiso | el contraste y el 44 % con los tres modelos, en el servidor | §4 |
| noviembre | el informe del servicio social | todo lo anterior |
