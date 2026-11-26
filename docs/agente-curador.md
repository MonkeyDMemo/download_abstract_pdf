# El agente curador: un lector por artículo

Plan del 25 de noviembre de 2026. **Todavía no es un protocolo.** Se vuelve
protocolo, con fecha, huellas y commit, antes de la primera corrida de prueba
(fase 3). Es trabajo de la tesis y es exploratorio: ninguna cifra del servicio
social depende de él, y la red oficial no cambia.

## Qué es

Hoy el sistema decide oración por oración: el bronce marca las oraciones con
dos genes, BioBERT clasifica cada par y el jurado relee una o dos oraciones
por relación. El agente curador hace lo que hace quien cura: recibe **un
artículo** y devuelve **las relaciones de regulación que ese artículo
afirma**, cada una con las oraciones que la sostienen.

Es la segunda pieza de Ouroboros. La primera, el juez, califica lo que otro
propuso; esta propone.

## Qué puede ganar y qué no

Lo medido el 25-nov contra la base curada (bitácora de ese día):

| Dónde está lo que hoy no se recupera | Cuánto | ¿Lo alcanza un lector por artículo? |
|---|---|---|
| Los dos genes en el artículo, en oraciones distintas | 9 % de las relaciones con artículo completo | Sí |
| En una tabla del XML | a lo más 6 % de las exigibles | En la fase 4 |
| Un nombre que el diccionario no resuelve | no medido | En parte |
| La red la tiene, pero sin signo | 300 de 686 filas con signo en la base | Sí: lee el contexto |
| No está en el artículo (material suplementario) | 21 % de las exigibles | No |
| El artículo citado no se tiene | 48 % de las exigibles | No |

Lo que se espera de él, entonces, es **signo, dirección y relaciones
repartidas en varias oraciones**, y un producto con otra forma: una ficha por
artículo, que es como trabaja el curador. No se espera un salto de cobertura:
ese depende de conseguir artículos y material suplementario.

## Reglas que hereda

Son las de `docs/decisiones.md` («El LLM sobre la oración es trabajo de
tesis») y `docs/plan-tesis-plata-llm.md`:

- **Lo determinista se queda determinista.** El modelo lee; llevar un nombre
  a su locus, expandir un operón y comprobar una cita lo hace el código.
- **Cada relación cita su evidencia, y un programa la comprueba.** Lo que no
  pasa la comprobación no entra a la red.
- **El lector nunca es Claude,** y el juez es de otra familia que el lector.
- **Se reproduce por caché,** no volviendo a llamar al modelo.
- **A la nube solo sale texto de artículos publicados.** La base curada y los
  juicios del experto no salen de donde están, y la base no se usa para
  escribir el prompt.
- **Marca, no filtra.** Su red va en archivos aparte.
- **Se gana su lugar con una medición,** con la regla escrita antes.

## Diseño

```mermaid
flowchart LR
    A["Artículo<br/>como lo partió el bronce"] --> B["Bloques de oraciones<br/>numeradas"]
    B --> C["Lector<br/>un modelo abierto"]
    C --> D["Relaciones<br/>con sus citas"]
    D --> E["Comprobación<br/>citas, nombres, locus"]
    E --> F["Red del curador<br/>archivos aparte"]
    F --> G["Jurado<br/>otra familia"]
```

1. **Entrada.** Las oraciones del artículo en una corrida del bronce
   (`texto_unidades`), sin las secciones que el bronce excluye (métodos,
   referencias). Cada oración lleva un identificador con su fuente y su
   número: `a3`, `x120`, `p45`. Un artículo largo se parte en bloques de
   60 mil caracteres, sin partir una sección mientras quepa.
2. **Lector.** Un modelo abierto en Bedrock, con Strands, el prompt
   `grn_ouroboros/prompts/curador_v0.md` y los criterios de la rúbrica del
   experto. Devuelve una lista: regulador, blanco, efecto (`activates`,
   `represses`, `regulates`), tipo (`directa`, `indirecta`, `no_se`) y de una
   a tres oraciones citadas por su identificador.
3. **Comprobación** (`curador.verificar`). En orden: las citas existen; el
   regulador y el blanco están escritos en alguna oración citada; cada nombre
   lleva a un solo locus del diccionario, o el blanco a un operón del
   catálogo (solo por tabla, con `grn_bronce.operones`); el regulador es un
   gen y no un operón; no son el mismo gen. Los estados que no son `valida`
   se cuentan: dicen qué le falta al lector o al diccionario.
   - Los nombres se comparan con guiones y espacios de ASCII (gpt-oss
     escribe `mexAB‑oprM` con un guion que no es el del texto) y sin las
     palabras que los acompañan (`barA operon`, `the barA gene`).
   - `PbarA`, la notación del promotor, vale como el blanco `barA`.
   - Una relación mal formada (más de tres citas, una etiqueta fuera de sus
     valores) se cuenta y se deja fuera sin tirar las demás del artículo.
   - Se guarda el texto que devolvió el modelo; leerlo y comprobarlo se
     rehace cada vez, así que corregir una regla no cuesta otra lectura.
4. **Salida.** `relaciones.tsv`, una fila por relación con su estado, y con
   `etapa2/red_curador.py` una red con las columnas de `red.tsv` (un voto por
   artículo y efecto; el signo, con la regla de mayoría de `red.py`), para
   que el contraste y el visor que ya existen la lean sin cambios.
5. **Juez.** El jurado relee las oraciones citadas y pone el nivel de
   confianza.

Se cita por identificador y no copiando un fragmento porque el juez, al
copiar, a veces altera el texto. Con el número, la comprobación es exacta y
la oración citada es la que el bronce guardó.

## Cómo se mide

No hay anotación nueva del experto, así que la medición usa lo que existe.

**Desarrollo (laptop, datos públicos).** Aquí se ajusta el prompt y se elige
el modelo.

- El patrón de oro propio (`etapa2/oro_pseudomonas.tsv`, 190 pares con sus
  artículos), con `etapa2/evaluar_curador.py`, que usa las funciones de
  `evaluar_oro.py`. La red de hoy recupera 140 de las 176 filas que el corpus
  puede sostener y deja 32 sin signo: es la línea base. El lector y su prompt
  no abren el patrón (lo vigila `etapa2/test_contaminacion.py`), pero el
  prompt se ajusta mirando estas cifras: **para el lector el patrón es
  conjunto de desarrollo, y sus cifras aquí no son su medición.**
- La tanda 1 del experto (198 oraciones, de desarrollo): de las oraciones que
  el lector cita y que están en ella, cuántas dijo el experto que sí.

**Congelamiento.** Prompt, modelo y parámetros, con su huella, en una
enmienda antes de la prueba.

**Prueba (servidor, una vez).** Contra la base curada, sobre las mismas 1 560
filas de la cifra principal. Para que la lista de artículos que cita la base
no salga del servidor, el lector lee **todos** los artículos del corpus, no
los que la base cita, y el servidor cuenta. Se reporta, junto a la red
vigente:

- el dirigido del curador solo y el de la unión red ∪ curador;
- la orientación;
- el signo: acuerdo, y en cuántas filas lo da;
- los conteos de la comprobación y qué fracción confirma el jurado.

**La regla (propuesta; se fija antes de la prueba).**

| Resultado | Condición |
|---|---|
| Aporta | La unión recupera al menos 3 puntos más que la red sola (47 filas de 1 560), o da signo correcto en al menos 60 filas más |
| No aporta | La unión gana menos de 1 punto y el signo correcto gana menos de 20 filas |
| No concluyente | Lo demás. Se reporta así, nunca como «no sirve» |

Guarda: el jurado tiene que confirmar las relaciones del curador al menos
tanto como las de la red (25 % en la corrida 25). Un lector que gana cobertura
inventando no pasa.

**Precisión.** No se puede volver a medir con el experto: su anotación está
cerrada y la prueba de 100 oraciones ya se usó. Lo que queda es la
comprobación de las citas, el jurado y la tanda 1 como desarrollo.

## Desarrollo: lo medido el 25-nov

Los 312 artículos que cita el patrón de oro propio (278 con texto completo),
leídos de la corrida 27 del bronce con dos modelos y dos prompts. La red del
paso 2 es la corrida 27 entera, que leyó 2 356 artículos; el lector, solo
esos 312.

| | Relaciones que devuelve | Válidas | Pares | Recupera de 176 | Signo correcto | Signo mal | Sin signo |
|---|---|---|---|---|---|---|---|
| Red del paso 2 (corrida 27) | — | — | 11 443 | 140 | 102 | 6 | 32 |
| gpt-oss-120b, prompt v0 | 3 017 | 1 150 | 655 | 113 | 107 | 1 | 5 |
| gpt-oss-120b, prompt v1 | 2 016 | 1 042 | 600 | 109 | 100 | 3 | 6 |
| Qwen3-235B, prompt v0 | 4 998 | 1 731 | 989 | 119 | 112 | 1 | 6 |
| Qwen3-235B, prompt v1 | 4 532 | 1 638 | 964 | 118 | 109 | 1 | 8 |
| Los dos lectores, v0, unión | — | — | 1 112 | 123 | 117 | 0 | 6 |
| Los dos lectores, v0, solo donde coinciden | — | — | 532 | 107 | 103 | 0 | 4 |
| **Red ∪ los dos lectores (v0)** | — | — | 11 721 | **145** | **131** | 6 | 8 |

Lo que dice:

- **El lector aporta el signo.** Unido a la red, las filas con signo
  correcto pasan de 102 a 131 y las que quedan sin signo, de 32 a 8. En
  filas recuperadas gana poco: de 140 a 145.
- **El prompt v1 no mejora.** Se escribió para que el lector citara la
  oración donde está cada nombre, diera un nombre por campo y dejara fuera
  fenotipos y moléculas. Con gpt-oss bajó el ruido (de 3 017 a 2 016
  relaciones) sin subir las válidas ni lo recuperado; con Qwen casi no
  cambió. **Se queda el v0.**
- **Dos lecturas no dan lo mismo.** De los pares que dan dos lecturas,
  comparten 61 % (gpt-oss, una con cada prompt), 69 % (Qwen, una con cada
  prompt) y 48 % (los dos modelos con el v0). Parte de la diferencia es del
  prompt y parte del modelo, que con gpt-oss muestrea. La unión recupera más
  y donde coinciden no hubo un solo signo mal: el acuerdo entre lectores
  sirve como nivel de confianza.
- **De cada 100 relaciones que devuelve el lector, valen entre 35 y 52.** Lo
  demás: un nombre que no está en las oraciones citadas (uno de cada cinco),
  y nombres que no son genes (PQS, T3SS, pyocyanin) o que el diccionario no
  conoce.
- **El diccionario tiene huecos.** Unos 170 (gpt-oss) y unos 300 (Qwen)
  nombres con forma de gen que los lectores usaron no están en
  `genes_pao1.tsv`: ARN pequeños (ErsA,
  PrrH, CrcZ) y genes con nombre (KinB, SadB, CdrA). Es el mismo hueco que
  limita al bronce, ahora con lista.

Lo que no dice: precisión. El patrón no marca errores, y sus relaciones son
las más conocidas de la especie, las que un modelo grande puede saber sin
leer. La comprobación de las citas exige que los nombres estén en la oración,
pero no que la oración afirme la relación: eso lo mide el jurado.

## Costo

Medido: los 312 artículos de desarrollo (10.9 millones de caracteres, 334
llamadas) costaron US$0.67 con gpt-oss-120b y US$1.00 con Qwen3-235B. El
corpus entero son 2 356 artículos, 57.8 millones de caracteres y 2 446
llamadas.

| Qué | Costo |
|---|---|
| Humo: 8 artículos, dos modelos | US$0.03 |
| Desarrollo: dos vueltas, dos modelos | US$3.34 |
| Todo el corpus con gpt-oss-120b | unos US$3.7 (estimado) |
| Todo el corpus con Qwen3-235B | unos US$5.5 (estimado) |
| El jurado sobre lo que extraiga | unos US$0.002 por relación con los tres jueces |

El tope de la nube era de US$30. El 25-nov el usuario lo subió en **US$15
para el agente curador** (US$45). Gastado al cierre del desarrollo: unos
US$32. Lo que queda alcanza para leer todo el corpus con los dos modelos y
pasar el jurado sobre una muestra, no sobre todo lo extraído.

## Fases

| Fase | Qué | Estado |
|---|---|---|
| 0 | Lo determinista: artículo en bloques, forma de la respuesta, comprobación de citas. Con pruebas, sin modelo | **Hecho** (`grn_ouroboros/curador.py`, `grn_bronce.db.unidades_de`) |
| 1 | El lector con Strands, caché y tope de gasto; `cli curar`; humo con 8 artículos | **Hecho** (`agente.crear_lector`, `curador.ejecutar`) |
| 2 | Desarrollo con el oro propio; elegir modelo y prompt | **Hecho** el 25-nov con el oro propio; falta la tanda 1 |
| 3 | Congelar, leer todo el corpus, medir en el servidor | Necesita la regla y los lectores aprobados |
| 4 | Tablas del XML; material suplementario; aprender de la base | Tesis |

## Lo que la v0 no hace

- **No aprende de la base curada.** Es de cero ejemplos. Aprender de ella
  pide partirla por artículo (unos para aprender, otros para medir) y un
  modelo que corra en el servidor, porque nada de la base sale de ahí.
- **No lee tablas ni material suplementario.**
- **No usa herramientas dentro del modelo.** Los nombres se resuelven
  después, con el diccionario.
- **No junta bloques.** Una relación entre dos bloques de un artículo muy
  largo se pierde; 2 290 de 2 356 artículos van en un solo bloque.

## Decisiones abiertas

1. ~~El tope de gasto para las fases 2 y 3.~~ Resuelto el 25-nov: US$15.
2. **Los lectores.** El desarrollo dice que dos lectores recuperan más que
   uno y que su acuerdo sirve de nivel de confianza. Propuesta: leer todo el
   corpus con los dos (unos US$9), con el prompt v0, y dar a cada relación
   un nivel: `dos_lectores` o `un_lector`. La alternativa barata es solo
   gpt-oss-120b (unos US$3.7).
   - Con los dos de lectores, el jurado de otra familia no existe: los tres
     jueces son de estas dos. El jurado se usa entonces como segunda
     opinión sobre una muestra, y se dice así.
3. **La regla de la prueba,** con sus umbrales (usuario y asesor).
4. **Si la tanda 2 se usa una vez más,** con cifra agregada, para dar una
   precisión del curador (usuario). La propuesta es no usarla.
