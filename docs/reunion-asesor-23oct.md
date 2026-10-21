# Reunión con el asesor — 23 de octubre de 2026

Guion de estado y de decisiones. Cada cifra dice de dónde sale: un archivo
versionado con su línea, un commit o una salida del flujo. Ninguna es de
memoria. Las citas `archivo:línea` son de `main` en `f05951a`, que ya trae el
segundo informe del servidor (curada-v2).

De la base curada aquí van solo conteos ya publicados en `PLAN.md` §2.4 y en
los informes filtrados del servidor. Ninguna fila, ninguna oración del
laboratorio.

---

## 1. Fe de erratas del Documento de Tesis v1

El documento del 20 de octubre mezcla corridas y trae cifras redondeadas que
no son las medidas. Lo que dice, y lo que vale:

| dice (página) | vale | fuente |
|---|---|---|
| «488 221 menciones en seis tipos» (p. 23) | Es la corrida 1. El flujo usa la **corrida 4: 495 382 menciones en ocho tipos** (gen, proteína, operón, disparador, función, contexto regulatorio, evidencia, organismo). La misma tabla da 1 min 20 s y 19 746 con disparador; la corrida 4 da 1 min 31 s y 19 747 | `PLAN.md:78-79`; `salidas/flujo/corrida4_run22/*_resumen.csv`; `CLAUDE.md`, modelo de datos |
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

## 2. El estado en una frase

El BioBERT reentrenado con la base curada existe en dos versiones que le ganan
a memorizar el par pero no leen el signo, así que el modelo de *E. coli* sigue
en el flujo; el cierre técnico del 4 de noviembre depende de que hoy se validen
la rúbrica, el calendario y el contraste, y de que usted autorice la
evaluación externa en el servidor.

---

## 3. Lo que se entrega

### A. La pista D: `reentrenar`, de punta a punta en el servidor

- Un orquestador desprendible (`grn_verificacion/reentrenar.py`) que arma los
  datos por supervisión distante, parte por PMID, entrena el run 22 en 5
  pliegues × 3 semillas y publica solo un informe filtrado, sin rutas, locus,
  marcadores ni PMIDs (`bitacora.md:369-372`).
- **La conciliación con `PLAN.md` §2.4 coincide en los 14 conteos** después
  de dos correcciones: el `Origen` se reconoce por palabra clave y los «310
  PMIDs» son 309 y un DOI (`bitacora.md:376-383`;
  `resultados-curada-v1.md:25-42`).
- **`regulates` queda fuera de esta versión**: 6 ejemplos de 2 artículos,
  ninguno en dev ni en test (`bitacora.md:387-389`;
  `resultados-curada-v1.md:98`).
- El protocolo se commiteó antes del primer entrenamiento: las cifras de la
  v1 son pre-registradas (`resultados-curada-v1.md:16`).

### B. curada-v1 (16-oct, con pesos de clase) y curada-v2 (21-oct, sin pesos)

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

### C. La rúbrica de anotación

`docs/rubrica-anotacion.md`: definiciones, árbol de decisión, 15 casos
frontera sintéticos, la hoja, el protocolo con ayudantes y el tamaño de la
muestra. Es la decisión a.

### D. Lo de esta noche

- **Alineación v2 de la sintaxis.** Hoy la alineación de menciones de la
  sintaxis alcanza al 11 % de los pares (`pendientes.md`, nuevos).
- **El paquete de la red (`grn_red`).** Ojo: `CLAUDE.md` todavía pone «crear
  `grn_red/`» en «Fuera de alcance»; si se fusiona, ese renglón cambia en el
  mismo commit.
- **`verificar-corrida`**: el comando que falla si una corrida no cumple sus
  invariantes (tesis v1, p. 14).
- **El contraste con la base curada, listo para correr** (`docs/contraste-curada.md`),
  sin correrlo: dónde y quién lo corre es la decisión d.

**Cifras de la noche (las llena el orquestador al cierre)**

| renglón | cifra | fuente |
|---|---|---|
| alineación v2 (C1-C4) | | |
| paquete de la red | | |
| verificar-corrida | | |
| suites | | |

---

## 4. Las decisiones que se piden

Cada una es una pregunta cerrada con nuestra recomendación. La decisión es
suya.

### a) ¿Se valida la rúbrica?

`docs/rubrica-anotacion.md`, con los siete puntos de su §9.

- **Recomendación:** validarla con los siete puntos tal como están. El que
  más pesa es el 1: «X activates Y» se anota `no_se` y no `directa`, que se
  aparta del eje léxico del 4-sep (`PLAN.md:29`).
- **Costo:** la sesión de calibración (20 oraciones sintéticas, unos 36
  minutos por persona más la discusión) y un solo ajuste, la v1.1.

| respuesta | qué hacemos |
|---|---|
| sí, tal cual | Se escriben las 20 de calibración y arranca la anotación el 24-oct |
| sí, con cambios en §9 | Se aplican antes de la calibración, en la v1 |
| no | La anotación no arranca; se recorta el carril y se reporta como limitación |

### b) ¿Se valida el calendario de 15 días y el protocolo con ayudantes?

`PLAN.md:137-156` y la rúbrica §7. Cinco carriles del 21-oct al 4-nov; el del
servidor ya se cumplió el 16-oct.

- **Recomendación:** validarlo, con el orden de recorte que trae: primero el
  agente revisor con Strands, luego Playwright, luego el NER complementario.
  El contraste y la red no se recortan (`PLAN.md:154-156`).
- **Costo:** la anotación pide unas 11.3 horas-persona para 300 ítems con 25 %
  doble (rúbrica §8), más calibración y adjudicación. Hacen falta al menos dos
  ayudantes y un adjudicador.

| respuesta | qué hacemos |
|---|---|
| sí | Cierre técnico el 4-nov, informe en noviembre |
| sí, con menos ayudantes | Se baja la muestra ciega a 100 (IC95 de ± 9.5 puntos en vez de ± 6.8) |
| no | Se rehace el calendario contra la fecha de cierre del 29-dic |

### c) ¿CollecTF queda como segunda referencia, fuera de la base de conocimiento y de `es_tf`?

Decidido por el autor el 20-oct (`decisiones.md`, entrada de CollecTF;
commit `26efa52`).

- **Lo medido:** de las 572 marcas `es_tf`, **29 traen `collectf` en
  `fuente_tf` y ninguna depende solo de esa fuente**. Sacarla no cambia
  ninguna marca.
- **Recomendación:** confirmarlo. Es una red curada: consultarla desde el
  agente confirmaría contra la respuesta.
- **Costo:** ninguno en la red. Una prueba del bronce que falle si una marca
  llega a depender solo de CollecTF.

| respuesta | qué hacemos |
|---|---|
| sí | El recall se reporta contra la base curada y contra CollecTF, por separado |
| no, puede entrar a la KB | Deja de servir como referencia: se evaluaría contra lo que el agente consultó |

### d) ¿Se formaliza el contraste con la base curada así?

- **Dos grupos.** Las exigibles (sin homología, con su artículo en el
  corpus: 2 003 y 1 488 de ellas en el corpus, `PLAN.md:104-113`) miden
  **recall**. Lo que el pipeline propone fuera de la base mide **precisión,
  por revisión de una muestra** (las 100 candidatas nuevas de la rúbrica §8).
  Una relación ausente de la base no es falsa.
- **El estrato `Origen` BioBERT va aparte.** Son 544 filas BioBERT y 216
  Ambos (`PLAN.md:97`): medir un BioBERT contra filas que puso otro BioBERT
  es medir acuerdo entre modelos.
- **Para un modelo entrenado con la base, el recall se mide solo en PMIDs de
  test.** Con el modelo desplegable de la curada eso son 4 artículos
  (`resultados-curada-v1.md:169`): no da una cifra. Hoy el del flujo es el de
  *E. coli*, que no vio la base.
- **El script está listo** (`docs/contraste-curada.md`); falta decidir dónde y
  quién lo corre. Lee la base, así que corre en el servidor y publica solo
  conteos.
- **Recomendación:** formalizarlo así y que lo corra el usuario en el
  servidor, con el mismo filtro de `RESULTADOS.md`.

| respuesta | qué hacemos |
|---|---|
| sí, en el servidor | Se corre esta semana; al repositorio llegan solo conteos y recall con IC |
| sí, pero lo corre usted | Se le entrega el comando y la guía; nosotros recibimos el informe filtrado |
| no | Queda el cruce del 10-sep (`PLAN.md` §2.4) como única cifra contra la base |

### e) ¿Se acepta evidencia obtenida en PA14 para la red de PAO1?

- **Lo medido:** 377 locus `PA14_#####` distintos, 837 menciones en 83
  documentos, ninguno reconocido por `genes_pao1.tsv` (`PLAN.md:208`).
- **La homología de la base, 2 850 filas, viene de PA14.** Aquí el PLAN se
  contradice: `PLAN.md:99` dice que solo «una variante» de la etiqueta indica
  inferencia desde PA14, y `PLAN.md:208` dice que de PA14 «provienen las 2 850
  interacciones por homología». Hay que saber cuál es antes de usarlo.
- **Recomendación:** sí, marcada como `cepa = PA14` y nunca mezclada con la
  de PAO1 sin la marca. El mapeo PA14 → PAO1 por ortología va antes que
  arreglar el tokenizador (`PLAN.md:208`).
- **Costo:** el mapeo por ortología, que hoy no existe.

| respuesta | qué hacemos |
|---|---|
| sí, marcada | Se construye el mapeo; la arista lleva la cepa |
| no | Las 837 menciones quedan fuera, documentadas como hueco del diccionario |
| solo como anotación | Se mapean, pero no promueven aristas |

### f) ¿Qué reglas de consolidación valen: las del borrador o las de `etapa2/red.py`?

El borrador de la tesis (p. 22) y `red.py`, que es lo que corre hoy, difieren
en cuatro de cinco reglas:

| regla | borrador (tesis, p. 22) | `etapa2/red.py` hoy | diferencia |
|---|---|---|---|
| promoción | una oración aceptada con confianza ≥ umbral | umbral por clase 0.65 / 0.70 / 0.60, sin calibrar (`red.py:60-66`, `:93`) | igual en forma; los umbrales no tienen conjunto de calibración |
| soporte | 1 documento = candidata; ≥ 2 = soporte múltiple | cuenta `n_articulos` y la lista de PMIDs; `--min-articulos` vale 1 (`red.py:548-555`) | la etiqueta de nivel no existe |
| signo | el mayoritario; empate o signos opuestos entre artículos → `?` y marca contradictoria | mayoría ≥ 0.66 de las predicciones con signo; si no, o en empate, `regulates` con `conflicto` (`red.py:489-503`, `:693`) | el borrador es ambiguo («mayoritario» y a la vez «opuestos → ?»); `red.py` tolera hasta 34 % en contra y cuenta oraciones, no artículos |
| operones | se expanden a sus genes antes de comparar | no expande nada | la expansión vive en la evaluación (`grn_bronce/operones.py`); en la red es la D9 de operones |
| autorregulación | se conserva con su marca | se excluye salvo `--incluir-autorregulacion` (`red.py:34-37`) | opuesta |

- **Recomendación:** adoptar las de `red.py` para signo (mayoría de 0.66 y
  conflicto marcado) y las del borrador para soporte (la etiqueta de nivel) y
  autorregulación (conservarla marcada); operones según la D9.
- **Costo:** `etapa2` está congelada: los cambios van en el paquete de la red,
  no en `red.py`.

| respuesta | qué hacemos |
|---|---|
| la recomendación | El paquete de la red las implementa con prueba por regla |
| todas las del borrador | Hay que precisar la regla de signo antes de implementarla |
| todas las de `red.py` | La red sigue como hoy, sin autorregulación ni nivel de soporte |

### g) La base curada: aviso, reemplazo, evaluación externa y signo

Cuatro preguntas que vienen del servidor (`bitacora.md:54-58`, `:458-462`):

1. **Aviso por escrito** de que `regulates` quedó fuera y de la conciliación
   (309 PMIDs y 1 DOI). Solo hay que acusarlo de recibido.
2. **¿Reemplaza alguna versión al modelo de *E. coli* en el flujo?**
   **Recomendación: no; quedarse con el de *E. coli*.** Es lo que dice la
   regla escrita antes de entrenar la v2.
3. **¿Autoriza la evaluación externa?** El 44 % recalculado con los tres
   modelos (`flujo.py --modelo` en el servidor; `protocolo-curada-v1.md:208-217`).
   Hace falta subir la carpeta del flujo de la laptop (el bronce de la corrida
   4). Las salidas se quedan en el servidor; llegan solo conteos.
   **Recomendación: sí.** Antes hay que resolver que `flujo.py --modelo` da la
   misma carpeta a todos los checkpoints `run_22_…`: hoy se prueban a mano en
   carpetas propias (`pendientes.md`, nuevos).
4. **¿Qué hacemos con el signo?**

| opción | qué es | costo | riesgo |
|---|---|---|---|
| A. corrección de la prior | ajustar a posteriori las probabilidades de las predicciones fuera de pliegue a la proporción de clases del flujo | una enmienda declarada posterior a ver las cifras; horas de código | exploratoria por construcción; no rescata un modelo que no lee el signo |
| B. sintaxis o control léxico | el signo sale del disparador o del árbol, no del BioBERT | ya medido: control léxico 537 de 674 pares consistentes, sintaxis 166 (`PLAN.md:201`) | es consistencia, no acierto: falta medirlo contra signos juzgados |
| C. esperar la muestra ciega | la rúbrica anota el signo; con ella se mide cada opción | ninguno extra: va en la anotación | el signo queda abierto hasta el 2-nov |

**Recomendación:** C, y medir B contra ella; A solo como enmienda declarada y
exploratoria.

| respuesta | qué hacemos |
|---|---|
| todo según la recomendación | *E. coli* sigue; se sube la carpeta y se corre el 44 % con los tres; el signo se decide con la muestra ciega |
| no autoriza la evaluación externa | La ficha de la curada queda con la validación cruzada como única cifra |
| prefiere A | Se escribe la enmienda 2 antes de mirar ninguna cifra nueva |

### h) Decisión 3 de operones

Sigue abierta: respuesta verbal, probable (semana del 5 al 9 de octubre), sin
confirmar por escrito (`operones-asesor.md:229-232`). La pregunta va tal cual
está en `operones-asesor.md` §8; aquí con el nombre de la base sustituido:

> Dr. Galán: en la semana del 5 al 9 de octubre me comentó que la base de
> operones es una cosa y que [la base curada] es la base de la red
> regulatoria; así lo registré. Para cerrar este punto por escrito me falta un
> dato: ¿alguna relación de [la base curada] se creó o se amplió por
> pertenencia a un operón —es decir, de «el regulador X actúa sobre el operón
> Y» se pasó a una fila por cada gen de Y— usando los operones de ODB,
> BioCyc/PseudoCyc o Pseudomonas Genome DB? Basta con sí, no o no lo sé; si es
> sí, ¿con cuál de esas fuentes?

| respuesta | qué hacemos |
|---|---|
| no | Se cierra. La pertenencia puede entrar como rasgo del paso 2 |
| sí | La pertenencia sigue solo como anotación; las filas ampliadas se apartan al evaluar y al entrenar |
| no lo sé | Todo sigue como hoy: la pertenencia anota y no decide |

Las otras decisiones de operones, D1 a D9, siguen en `operones-asesor.md` §7.

### i) Permiso para enviar oraciones del corpus público a EC2

Solo se lista: no se prepara nada de AWS para esta reunión (tesis, p. 15-17).

---

## 5. Qué decir y qué no

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

---

## 6. Siguientes pasos contra el calendario

| fecha (`PLAN.md:145-152`) | qué | depende de |
|---|---|---|
| 23-oct | esta reunión | — |
| 24-oct | 20 oraciones sintéticas de calibración y la sesión | a |
| 24-oct al 2-nov | anotación: 200 ciegas y 100 candidatas nuevas | a, b, d |
| 21 al 27-oct | fusionar alineación v2, paquete de la red y `verificar-corrida`; correr el contraste en el servidor | d, f |
| esta semana | subir la carpeta del flujo al servidor; el 44 % con los tres modelos | g |
| 28-oct al 3-nov | LLM sobre el residuo y consolidación con las reglas de f | f, i |
| 2 al 3-nov | el signo con la muestra ciega: *E. coli*, control léxico y sintaxis | g, anotación |
| 4-nov | cierre técnico | — |

Si algo se atrasa, se recorta en el orden de `PLAN.md:154-156`.
