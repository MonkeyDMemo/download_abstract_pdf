# Informe del primer seminario

**Corpus de literatura para inferir la red de regulación de *Pseudomonas aeruginosa***

| | |
|---|---|
| Presenta | Guillermo Reséndiz |
| Asesor | Dr. Edgardo Galán Vásquez |
| Adscripción | IIMAS · UNAM — Laboratorio de Datos Biológicos y Redes Complejas (BioMiNet) |
| Línea | Redes de Regulación Génica (GRN) |
| Corte del corpus | 19 de agosto de 2026 (`datos/grn.db`) |
| Corte del barrido | 20 de agosto de 2026 — **24 de 24 corridas, completo** |

Objetivos formativos del servicio social: integrar múltiples fuentes
biológicas, aplicar aprendizaje supervisado y minería de textos, y validar
críticamente las interacciones obtenidas.

Este documento acompaña al primer seminario. Las diapositivas están en
`salidas/Seminario_GRN_IIMAS_final.pptx`, pero aquí no hacen falta.

**Dónde está cada cosa que se pidió:**

| se pidió | está en |
|---|---|
| Protocolo | «Las reglas que se siguieron» |
| Metodología | «Etapa 1 — construir el corpus» y «Etapa 2 — extraer las relaciones» |
| Resultados | las mismas dos secciones, más «Resultados del barrido» |
| Conclusiones | «Conclusiones» y «Lo que todavía no está medido» |

---

## Cómo leer este informe

Está escrito para el asesor, y se puede leer sin abrir ningún otro archivo. Cada
cifra dice de dónde sale. Cuando el detalle vive en otro documento del
repositorio, hay una liga en vez de una copia.

Cuatro etiquetas marcan qué tan firme es cada dato:

- **medido** — sale de un archivo de este repositorio, y se dice cuál.
- **parcial** — la medición se hizo, pero no completa; se dice cuánto abarca y
  por qué se detuvo ahí.
- **heredado** — viene del servidor del asesor. No se volvió a medir aquí.
- **pendiente** — no está medido, y se dice qué lo produciría.

### Qué cambió desde las diapositivas

Las láminas 1 a 6 siguen vigentes. Las tres últimas se quedaron atrás en los
días posteriores al corte del 18 de agosto:

| lo que decían las láminas 7 a 9 | lo que es cierto hoy |
|---|---|
| La etapa 2 es un prototipo: diccionario de entidades más reglas léxicas | Existe un modelo BioBERT afinado para clasificar relaciones, heredado del servidor del asesor |
| «Sin conjunto de referencia no hay métrica»; candidato RegulomePA, por confirmar | Hay un patrón de oro provisional propio de *P. aeruginosa*: 190 relaciones, 181 encontradas en el corpus |
| Siguiente paso: escalar de la línea base a BERT | Ya se hizo, y al hacerlo apareció un problema en cómo se estaba evaluando ese modelo |
| — | Se rehizo la partición de los datos y se corrieron las 24 configuraciones sobre ella, sin contaminación |

Nada de esto contradice las diapositivas: es lo que pasó después.

### Palabras que se usan aquí

- **Factor de transcripción (TF)**: proteína que enciende o apaga la expresión
  de otros genes.
- **Relación regulatoria**: la afirmación «el factor X regula al gen Y», con un
  signo: lo activa, lo reprime, o lo regula sin que el artículo diga en qué
  sentido.
- **Corpus**: el conjunto de artículos científicos descargados.
- **Resumen y texto completo**: el resumen basta para encontrar un artículo; el
  detalle experimental donde se afirma la regulación suele estar solo en el
  texto completo.
- **Contaminación de datos**: cuando el material con el que se evalúa un modelo
  ya apareció en el material con el que se entrenó. La calificación deja de
  medir lo que aprendió y empieza a medir lo que memorizó.
- **Partición**: el reparto del material anotado en tres montones —
  entrenamiento (el modelo aprende), validación (se elige la mejor
  configuración) y prueba (se mide una sola vez, al final).
- **Macro-F1**: promedio simple del desempeño en cada una de las cuatro clases,
  sin darle más peso a las clases que tienen más ejemplos. Es la métrica dura:
  una clase rara mal clasificada sí se nota.
- **Época, lote, tasa de aprendizaje, calentamiento**: los cuatro ajustes que se
  barrieron. Cuántas veces el modelo recorre todos los datos, cuántos ejemplos
  procesa de golpe, qué tan grandes son los pasos que da, y qué fracción del
  entrenamiento usa para acelerar poco a poco al principio.
- **Patrón de oro**: la lista de relaciones que se dan por ciertas, contra la
  cual se compara lo que el modelo propone.

---

## Resumen: qué hay y de dónde sale

| pieza | cifra | estado y fuente |
|---|---|---|
| Corpus construido | 2 361 artículos, 1 006 con texto completo, ~750 MB | **medido** — `datos/grn.db` |
| Descargas evitadas | 56 % (5 331 vínculos consulta-documento contra 2 361 descargas) | **medido** — `datos/grn.db` |
| Modelo de clasificación | BioBERT afinado, cuatro clases | **heredado** — `ficha-modelo-bert.md` |
| Contaminación de la evaluación heredada | 73.9 % del montón de prueba ya se había visto en el de entrenamiento | **medido** — `etapa2/particionar.py` |
| Partición nueva | 1242 / 163 / 157, contaminación de texto 0.0 % | **medido** — `etapa2/particionar.py` |
| Barrido sin contaminación | la misma configuración que el servidor reportó como suya da 0.9335 en prueba; 12 de las 24 superan el 0.8721 | **medido** — `etapa2/barrido_resumen.csv` |
| Patrón de oro de *P. aeruginosa* | 190 relaciones, ~169 evaluables | **medido** — `etapa2/oro_pseudomonas.tsv` |
| Auditoría de signo | 93 oraciones con la respuesta conocida de antemano | **medido** — `etapa2/auditoria_signo.tsv` |
| Diccionario de genes de PAO1 | 5 642 genes, 572 factores; reconoce 43 de los 55 factores del oro con fuentes públicas, 53 con la capa manual | **medido** — `etapa2/genes_pao1.tsv` |
| Conjunto anotado a mano de PAO1 | — | **pendiente** |

---

## Las reglas que se siguieron

Esto es el protocolo. No son buenas intenciones: casi todas están puestas en el
código, y el código se niega a continuar cuando alguna se rompe.

- **Solo se descarga lo que los servicios exponen legalmente.** PubMed Central,
  Europe PMC y Unpaywall. No se raspa el sitio web de PMC ni se disfraza el
  programa de navegador para saltarse un bloqueo. La razón no es solo legal:
  el NCBI bloquea por dirección IP, así que un programa mal portado deja sin
  servicio al laboratorio entero, no a quien lo corrió.
- **Lo que ya se bajó no se vuelve a bajar.** Un artículo que aparece en cinco
  consultas se guarda una vez y se liga cinco veces. Hay una prueba automática
  que corre la misma consulta dos veces y falla si la segunda genera tráfico.
- **Ninguna métrica se reporta sin decir sobre qué se midió** y qué comparte ese
  material con el de entrenamiento. Esta regla es la que originó la mitad de
  este informe.
- **El programa se niega antes que mentir.** `particionar.py` no escribe la
  partición si detecta contaminación, y la verifica con un criterio
  deliberadamente distinto del que usó para repartir, para que la verificación
  no pueda salir bien por construcción. `barrido.py` no anuncia configuración
  ganadora mientras falte una corrida.
- **Lo que no se pudo conseguir se entrega como lista, no se esconde.** Los
  1 345 artículos sin acceso abierto salen en un archivo con su liga, para
  pedirlos por biblioteca.
- **349 pruebas automáticas en la etapa 1 y 21 en la etapa 2.** Ninguna toca la
  red: se les inyecta un cliente falso, y una prueba que intente salir a
  internet de verdad falla.

---

## Etapa 1 — construir el corpus

### Cómo se construye

Se registra una consulta booleana con nombre. El sistema pregunta a PubMed qué
artículos la satisfacen, resta los que ya están guardados, y descarga solo la
diferencia. Después, en un segundo paso, busca el texto completo: primero el XML
de PubMed Central, y solo para lo que no lo tenga, el PDF, probando en cascada
PMC, Europe PMC y Unpaywall.

El orden importa. El XML llega con las secciones separadas y los pies de figura
identificados; un PDF vuelto a convertir a texto pierde los subíndices de los
genes y entrelaza las columnas. El XML alimenta al clasificador; el PDF es para
que lo lea una persona.

El estado vive en una base SQLite, así que una corrida interrumpida se retoma
sin perder lo hecho. Se opera desde la terminal o desde un tablero local.

### Qué hay dentro

| | artículos |
|---|---|
| Total | **2 361** |
| Con texto completo | 1 006 |
| Solo con resumen | 1 348 |
| Sin resumen ni texto completo | 7 |

De los 1 006 con texto completo, 918 tienen el XML de PubMed Central, 184 tienen
PDF, y 96 tienen los dos. Todo junto ocupa unos 750 MB en disco.

La distinción entre esas dos primeras filas es la que importa para la etapa 2:
el resumen basta para encontrar el artículo, pero el detalle experimental donde
se afirma la regulación casi siempre está en el texto completo.

### Por qué 2 263 y 2 361 son la misma medida en dos fechas

En el repositorio conviven dos cifras del tamaño del corpus. No es un error:
`README.md` y las diapositivas viejas reportan 2 263, que era el resultado de la
primera consulta; `docs/traspaso-etapa-2.md` y este informe reportan 2 361, que
es el total tras una ejecución posterior. La diferencia son 98 artículos, y se
comprueba porque el conteo de resúmenes se movió igual (2 256 a 2 354).

**La cifra viva es 2 361**, y sale de consultar la base directamente. Un aviso
para quien vaya a «corregir» los documentos: en `CLAUDE.md`, `structure.md` y
`tech.md` el número 2 263 aparece hablando de romper el contrato de columnas de
la base, no del tamaño del corpus. Ahí no hay nada que corregir.

### Cómo se verificó

- **56 % de descargas evitadas.** Las seis consultas registradas suman 5 331
  vínculos artículo-consulta; descargas se hicieron 2 361. El solapamiento entre
  consultas sobre *P. aeruginosa* no es marginal: es la mayor parte del trabajo.
- **Cuatro fuentes de PDF medidas, tres descartadas.** De veinte descargas de
  prueba, quince se lograron por Europe PMC. Las otras fuentes se midieron y se
  documentó por qué no se construyeron.
- **349 pruebas automáticas**, y siete defectos silenciosos corregidos gracias a
  ellas.
- **1 345 artículos sin acceso abierto**, exportados con su liga para
  solicitarlos por biblioteca. Lo que falta responde a disponibilidad legal, no
  a una limitación de la herramienta.

---

## Etapa 2 — extraer las relaciones

Aquí es donde el trabajo cambió más desde el seminario.

### El punto de comparación: Varela-Vega 2024

El trabajo de referencia directo es Varela-Vega y colaboradores (2024, CCG-UNAM):
reconstruyen una red regulatoria bacteriana extrayendo relaciones de texto con un
modelo de lenguaje tipo BERT, y la comparan contra RegulonDB. Reportan F1 de
0.87.

Esa cifra fija la vara, pero **no se compara renglón con renglón** con las de
este informe: es otro organismo, otro corpus y otra partición. Sirve para saber
en qué orden de magnitud se mueve el problema, no para decir quién gana.

Los otros seis artículos del marco de referencia están en la lámina 3.

### El modelo se entrenó con *E. coli* y se va a usar en *P. aeruginosa*

Es la premisa central del trabajo y conviene tenerla presente al leer cualquier
número de aquí en adelante.

El modelo es `dmis-lab/biobert-base-cased-v1.1` afinado para clasificar
relaciones en cuatro clases: activa, reprime, regula sin signo, y sin relación.
Se entrenó con `ecoli_curated.tsv`: **1 562 ejemplos de 119 artículos**, en
formato RegulonDB, todos de *Escherichia coli*. La distribución de clases es
desigual: 593 activa (38.0 %), 493 sin relación (31.6 %), 269 reprime (17.2 %) y
207 regula (13.3 %).

**No hay un solo ejemplo de *P. aeruginosa* anotado a mano en el entrenamiento.**
Todo el trabajo descansa en que lo aprendido en una bacteria transfiera a otra.
Es una apuesta razonable —la forma de escribir «X reprime a Y» no cambia entre
especies— pero es una apuesta, y hasta ahora no se ha medido.

El detalle completo del modelo (arquitectura, formato de entrada, orden de las
etiquetas, umbrales de decisión, la red de 789 aristas que ya infirió) está en
[`ficha-modelo-bert.md`](ficha-modelo-bert.md).

### Qué heredé y qué hice yo

En un informe de servicio social esto no es cortesía, es el objeto del documento.

| heredado del servidor del asesor | trabajo propio |
|---|---|
| El modelo afinado y sus pesos entrenados | Todo el corpus y la etapa 1 completa |
| `bio_bert_re_finetune.py` y el script del barrido original | La auditoría del servidor: [`ficha-modelo-bert.md`](ficha-modelo-bert.md) |
| `ecoli_curated.tsv` y su partición original | La medición de la contaminación |
| La rejilla de 24 configuraciones | `particionar.py`, su verificador y sus 17 pruebas |
| El diccionario de PAO1 del servidor (`pseudomonas_genes.tsv`, reconocimiento por expresiones regulares) | `barrido.py` reanudable y el traslado a Google Colab |
| El programa de inferencia y las 789 relaciones que ya propuso | `oro_pseudomonas.tsv`, el patrón de oro de *P. aeruginosa* |
| | `auditar_signo.py` y su auditoría de 198 oraciones |
| | `construir_diccionario.py` y el diccionario nuevo, desde RefSeq, KEGG y UniProt |
| | El programa local de inferencia: `extraer_pares.py`, `red.py`, `evaluar_oro.py` |

El modelo no es mío. Lo que hice fue auditarlo, encontrar que su calificación no
medía lo que decía medir, y volver a medirla bien.

### El problema: el modelo se estaba evaluando con datos que ya había visto

Imagina un examen donde el 74 % de las preguntas ya venían resueltas en la guía
de estudio. La calificación sale alta, pero no dice cuánto aprendió el alumno.
Eso es exactamente lo que pasaba.

El corpus de entrenamiento tiene **1 562 ejemplos, pero solo 694 fragmentos de
texto distintos**: cada fragmento genera un ejemplo por cada par (factor, gen)
que contiene, así que el mismo texto aparece en promedio 2.25 veces. Al repartir
los tres montones al azar a nivel de ejemplo, copias del mismo fragmento caen a
ambos lados de la línea.

Lo que salió al medirlo:

| | validación | prueba |
|---|---|---|
| Ejemplos cuyo texto ya estaba en entrenamiento | 68.6 % | **73.9 %** |
| Artículos compartidos con entrenamiento | 65 de 68 | 61 de 64 |
| Pares (factor, gen) ya vistos | 89.7 % | 86.6 % |

La métrica que se reportaba con esa partición era macro-F1 de 0.9024 en
validación y 0.8721 en prueba. Ese número mide sobre todo memorización.

**Qué cuenta exactamente como «el mismo texto».** La comprobación compara la
ventana sin sus marcadores de entidad, así que ese 73.9 % significa «la misma
ventana de texto, quizá con otro par marcado», no «la misma entrada carácter por
carácter». Es la medida pertinente —lo que preocupa es que el modelo ya hubiera
visto el pasaje— pero conviene decirlo, porque hay dos cifras vecinas que no
dependen de ninguna canonización y que por eso son más duras de discutir: **61 de
los 64 artículos** de prueba están también en entrenamiento, contado por PMID sin
tocar el texto, y el **86.6 % de los pares** de prueba ya aparecen en
entrenamiento.

**No invalida el trabajo: invalida el número.** El modelo puede ser bueno; lo que
no se podía era saberlo.

### La partición nueva, y por qué el programa se niega a escribirla si hay contaminación

La solución es no repartir ejemplos sueltos, sino grupos: todo lo que comparta
artículo o fragmento de texto viaja junto. Se probaron cuatro criterios de
agrupamiento y se eligió **artículo más fragmento**, que es el único que deja
grupos manejables. Exigir además que no se comparta ningún par (factor, gen)
colapsa el corpus en un solo bloque con el 89 % de los ejemplos: es imposible
partirlo, hay que elegir una pregunta u otra.

El reparto usa semilla fija (20260819) y busca el balance de clases que menos se
desvía de las proporciones globales. El resultado, contra la partición original:

| | entrenamiento | validación | prueba |
|---|---|---|---|
| Partición original | 1 249 | 156 | 157 |
| **Partición nueva** | **1 242** (102 artículos) | **163** (9) | **157** (8) |

Mismo tamaño, mismas proporciones de clase. Lo único que cambia es la
contaminación, que pasa de 73.9 % a **0.0 %**, con cero artículos compartidos.

Dos cosas que el verificador reportó y conviene leer:

- **7.6 % de los ejemplos de prueba tienen su fragmento casi contenido en uno de
  entrenamiento**, y uno al 100 %. Es un título de artículo que aparece citado
  en la bibliografía de otro. Ningún criterio basado en el artículo lo evita, así
  que se reporta como aviso y no como falla.
- **La clase «regula» tiene en validación 24 ejemplos, pero salen de solo 3
  artículos, y 12 de ellos del mismo.** Contar ejemplos exagera cuánta
  información hay. Lo que fija la incertidumbre real es el número de artículos
  independientes, y con menos de cinco el F1 de esa clase es ruido por bien que
  se vea el conteo.

El detalle del mecanismo está en [`../etapa2/README.md`](../etapa2/README.md).

### Resultados del barrido

Se recorren 24 configuraciones: tres tasas de aprendizaje, por dos números de
épocas, por dos tamaños de lote, por dos calentamientos. Lo demás queda fijo
como en el barrido original del servidor, para que la comparación sea justa:
`weight_decay` 0.01, ventana de 512 tokens, semilla 42, pesos por clase inversos
a su frecuencia y paro temprano con paciencia de 2 épocas.

**Estado: 24 de 24 corridas, cero fallos, tres horas de GPU.** Las 24 llevan la
misma huella de datos (`3d2cb9d4a0378177`), o sea que todas se midieron sobre la
misma partición; `barrido.py` se habría negado a mezclar dos.

| corrida | tasa | épocas | lote | calent. | macro-F1 validación | macro-F1 prueba |
|---|---|---|---|---|---|---|
| **22** | 3e-5 | 8 | 16 | 0.1 | **0.9086** | **0.9335** |
| 21 | 3e-5 | 8 | 16 | 0.06 | 0.8911 | 0.9333 |
| 13 | 2e-5 | 8 | 16 | 0.06 | 0.8908 | 0.9028 |
| 23 | 3e-5 | 8 | 32 | 0.06 | 0.8773 | 0.8806 |
| 17 | 3e-5 | 6 | 16 | 0.06 | 0.8754 | 0.9234 |
| 24 | 3e-5 | 8 | 32 | 0.1 | 0.8734 | 0.8782 |
| 16 | 2e-5 | 8 | 32 | 0.1 | 0.8720 | 0.8945 |
| 10 | 2e-5 | 6 | 16 | 0.1 | 0.8696 | 0.8939 |
| 14 | 2e-5 | 8 | 16 | 0.1 | 0.8694 | 0.9150 |
| 20 | 3e-5 | 6 | 32 | 0.1 | 0.8663 | 0.8915 |
| 19 | 3e-5 | 6 | 32 | 0.06 | 0.8632 | 0.8785 |
| 9 | 2e-5 | 6 | 16 | 0.06 | 0.8534 | 0.8890 |
| 15 | 2e-5 | 8 | 32 | 0.06 | 0.8503 | 0.8709 |
| 11 | 2e-5 | 6 | 32 | 0.06 | 0.8407 | 0.8386 |
| 18 | 3e-5 | 6 | 16 | 0.1 | 0.8396 | 0.8550 |
| 5 | 1e-5 | 8 | 16 | 0.06 | 0.8369 | 0.8346 |
| 12 | 2e-5 | 6 | 32 | 0.1 | 0.8265 | 0.8408 |
| 7 | 1e-5 | 8 | 32 | 0.06 | 0.8069 | 0.8201 |
| 2 | 1e-5 | 6 | 16 | 0.1 | 0.8042 | 0.8108 |
| 1 | 1e-5 | 6 | 16 | 0.06 | 0.8037 | 0.8321 |
| 6 | 1e-5 | 8 | 16 | 0.1 | 0.8030 | 0.8197 |
| 8 | 1e-5 | 8 | 32 | 0.1 | 0.7860 | 0.8294 |
| 3 | 1e-5 | 6 | 32 | 0.06 | 0.7377 | 0.7336 |
| 4 | 1e-5 | 6 | 32 | 0.1 | 0.7024 | 0.7436 |

**Cómo leer las dos columnas de métrica.** La de validación se calcula sobre el
modelo que esa misma métrica eligió como mejor, así que es optimista por
construcción y sirve para ordenar configuraciones, no para reportar desempeño.
**La cifra limpia es la de prueba**, que se mira una sola vez.

**El patrón.** Todo lo que aumenta el número de pasos de optimización ayuda. Con
tasa 1e-5 el modelo se queda corto de entrenamiento: ese bloque entero se mueve
entre 0.70 y 0.84, y sus dos peores corridas son las de lote grande con pocas
épocas, que son las que menos pasos dan. Al subir a 2e-5 el bloque salta a
0.83-0.89 en validación. La corrida 18 es la primera que activó el paro temprano
—se detuvo en la época 5 de 6—, señal de que con tasa 3e-5 ya se empieza a
llegar antes al techo.

**El resultado, y la comparación que faltaba.** La regla de selección es la
validación. Gana la **corrida 22** con 0.9086, y esa da **0.9335 en prueba**. Y
la corrida 22 no es una cualquiera: es **exactamente la configuración que el
servidor reportó como su mejor** (tasa 3e-5, 8 épocas, lote 16, calentamiento
0.1). O sea que la comparación de una configuración contra sí misma, que era lo
que faltaba, ya se puede hacer:

| corrida 22 | validación | prueba |
|---|---|---|
| en el servidor, **con** contaminación | 0.9024 | 0.8721 |
| aquí, **sin** contaminación | **0.9086** | **0.9335** |

Sube en las dos. Y **12 de las 24 corridas superan el 0.8721**, o sea que no
depende de qué corrida se elija.

Hay algo más que decir, y favorece al trabajo heredado: **la elección de
hiperparámetros del servidor era correcta.** Las dos primeras de la tabla limpia
son 22 y 21, las dos de tasa 3e-5 con 8 épocas y lote 16, que es la familia que
el servidor había identificado. Lo que estaba mal era la medición, no la
búsqueda.

Lo que se puede afirmar: **ese nivel de desempeño se alcanza sin contaminación
alguna, y la misma configuración medida bien da más, no menos.** Lo que sigue sin
poderse afirmar es cuánto de la diferencia se debe a haber quitado la
contaminación, por dos razones que la corrida 22 no elimina:

1. **No es el mismo conjunto de prueba.** Son 157 ejemplos en los dos casos,
   pero no los mismos 157, y los de ahora vienen de 8 artículos contra 64.
2. **157 ejemplos son pocos para cuatro clases.** Acertar dos ejemplos más de la
   clase rara mueve el macro-F1 varias centésimas.

Las dos piden el **brazo de control** —la misma partición repartida a nivel de
ejemplo—, que no depende de tener GPU sino de que `particionar.py` lo produzca.

### Un error del mismo tipo, en este trabajo

Conviene decirlo aquí y no esperar a que alguien lo encuentre. **La primera
versión de este informe encabezaba el resultado con 0.9234**, que es el máximo de
la columna de prueba sobre 18 corridas. Eso es dejar que la prueba participe en
la selección del modelo: la misma clase de defecto que este trabajo vino a
corregir, en versión más pequeña. Y el propio informe decía dos párrafos antes que
la prueba se mira una sola vez.

Está corregido arriba: la selección se fija en validación. Al completar las 24
el problema se disolvió solo —la corrida 22 gana en validación **y** en prueba, y
además es la del servidor—, pero eso fue suerte, no método: con las 18 primeras
la regla y el máximo no coincidían. De aquí en adelante la regla queda escrita
antes de mirar la tabla, y cada configuración debería repetirse con varias
semillas para reportar dispersión en vez de puntos.

Aplicarse el mismo criterio con el que se juzga un trabajo ajeno es lo que
convierte una auditoría en un método y no en un reproche.

### La misma configuración entrenada dos veces no da el mismo número

Esto salió sin buscarlo, al guardar los pesos de la mejor corrida para poder
usar el modelo. Se volvió a entrenar la configuración 13 con **los mismos
hiperparámetros, los mismos datos y la misma semilla**, y dio otra cosa:

| | en el barrido | al reentrenarla | diferencia |
|---|---|---|---|
| macro-F1 validación | 0.8908 | 0.9003 | +0.0095 |
| macro-F1 prueba | 0.9028 | 0.8903 | −0.0125 |

No es variación de semilla: la semilla fue 42 en las dos. Fijar la semilla fija
los generadores de números aleatorios, pero **no hace determinista el
entrenamiento en GPU**: la selección de núcleos de cálculo y las sumas atómicas
del paso hacia atrás no garantizan el mismo orden de operaciones entre corridas,
y en punto flotante el orden cambia el resultado. Forzar el determinismo se
puede, y cuesta velocidad.

**La consecuencia para la tabla de arriba hay que decirla.** Si reentrenar la
misma configuración la mueve 0.0125 en prueba, entonces las diferencias entre
configuraciones vecinas —la 13 y la 14 se llevan 0.012; la 16 y la 10, menos de
una milésima— están **dentro del ruido de volver a entrenar**. Ordenar las 18 por
décimas de punto es ordenar en parte por azar, y las de arriba de la tabla están
empatadas aunque la lista dé un ganador.

Lo que **no** queda tocado es el patrón de bloques: el salto del bloque de tasa
1e-5 (0.73 a 0.83) al de 2e-5 en adelante (0.89 a 0.92) es varias veces mayor que
este ruido. Y tampoco la comparación contra el número heredado: 0.8903, que es la
peor de las dos mediciones de esa configuración, sigue por encima de 0.8721.

Esto ya estaba anticipado en la lista de lo que falta, como advertencia teórica
sobre repetir con varias semillas. Ahora es una medición, y salió **sin cambiar
la semilla siquiera**, que es peor de lo que se había supuesto.

### El diccionario de genes, y por qué se reporta 43 de 55

Para encontrar relaciones en el texto hace falta antes reconocer los genes. Eso
lo hace un diccionario de los **5 642 genes de PAO1**, construido aquí desde tres
fuentes públicas de anotación de secuencia: el genoma de referencia en RefSeq,
KEGG y UniProt. Ninguna de las tres es una lista de relaciones regulatorias, y
eso importa: **si el diccionario se construyera a partir del patrón de oro,
cualquier evaluación posterior mediría el solapamiento del diccionario consigo
mismo.** Por eso la columna de procedencia no admite el valor `oro`.

De ahí salen también **572 genes marcados como factores de transcripción** y
**333 pares con evidencia experimental de unión**, que vienen de los sitios de
unión anotados en el mismo genoma.

**La cifra que se reporta es la reproducible.** El diccionario tiene además una
capa manual de 22 filas, escritas a mano y versionadas, y la cobertura de los 55
factores del patrón de oro cambia mucho según se cuente con ella o sin ella:

| | factores del oro reconocidos |
|---|---|
| Solo con las tres fuentes públicas | **43 de 55 (78.2 %)** |
| Añadiendo la capa manual | 53 de 55 (96.4 %) |

**Se reporta 43 de 55**, que es lo que cualquiera puede reproducir bajando las
mismas tres fuentes. El 53 depende de que una persona escribiera 22 filas, y una
cifra que sube porque alguien la ayudó a mano no es la misma clase de cifra.

Los doce que faltan sin la capa manual son `Anr`, `CpxR`, `CzcR`, `Fur`, `HasI`,
`HptB`, `IHF`, `MexL`, `PirR`, `PqsR`, `PrrF` y `Vfr`, y **ninguno es un gen
desconocido**. Conviene decir qué le pasa a cada uno, porque el número se lee
peor de lo que es. Son cinco situaciones distintas:

- **Cuatro locus que ninguna fuente pública nombra** — `CzcR`, `HasI`, `HptB`,
  `MexL`. El gen existe en RefSeq, pero su registro **no trae campo de nombre**:
  se llama `PA2523`, `PA3410`, `PA3345` y `PA3678` y nada más. Quien escribe
  `MexL` en un artículo está usando un nombre que la anotación de secuencia no
  conoce. Es la capa manual la que le pone el símbolo.
- **Tres que RefSeq sí nombra, pero en minúsculas** — `Fur`, `Anr`, `Vfr`. Los
  símbolos `fur`, `anr` y `vfr` están ahí. Pero son de tres letras, y por eso su
  fila exige coincidencia exacta de mayúsculas: `fur` suelto en un texto en
  inglés sería un falso positivo constante. La literatura escribe la proteína
  capitalizada —`Fur` aparece 573 veces en este corpus— y `Fur` no casa con
  `fur`. El programa **se niega a propósito a inventar la forma capitalizada**:
  hacerlo para todos reintroduciría el falso positivo que la marca existe para
  matar, así que un gen sensible que necesite su forma de proteína la lleva
  declarada a mano, donde alguien la firma.
- **Uno al que las bases llaman de otra forma** — `PqsR`. RefSeq, KEGG y UniProt
  coinciden en llamar `mvfR` a `PA1003`. Es un sinónimo de verdad.
- **Dos que no son un gen** — `IHF` es un heterodímero: RefSeq trae sus dos
  subunidades (`ihfA`, `ihfB`), no el nombre del conjunto. `PrrF` es un par de
  ARN pequeños: la base trae `prrF1` y `prrF2`, no el colectivo.
- **Dos que no resuelve nadie, ni siquiera la capa manual** — `CpxR` y `PirR`.
  Sus filas existen y están marcadas como factor de transcripción por evidencia
  pública, pero ninguna fuente les da símbolo y su única superficie es el locus
  tag. Aquí el constructor se negó deliberadamente a adivinar: la asignación
  habitual de `CpxR` contradice a RefSeq, que llama a ese gen sensor de dos
  componentes. **Prefirió 53 de 55 honestos a 55 de 55 copiando locus tags del
  patrón de oro.**

Cada fila de la capa manual lleva su justificación escrita y se eligió **por
frecuencia en el corpus, no por el patrón de oro**: `Fur` aparece en 81
artículos, `PqsR` en 155. Aun así es una elección humana que sube justo la
métrica que se va a reportar, y por eso se declara aparte en vez de fundirse en
el total.

**Llegar a 55 de 55 queda pendiente**, y no es un trabajo de escribir más filas
a mano. Son tres cosas de dificultad muy distinta:

1. **Que la firma sea una cita y no un juicio.** Los ocho que la capa manual
   repone hoy dependen de que una persona escribiera el nombre. Lo que los
   volvería reproducibles es tomarlo de una fuente pública que registre nombres
   de proteína y sinónimos de gen —UniProt los tiene— en vez de dejarlos a
   criterio de quien construye.
2. **Que el diccionario admita cosas que no son un gen.** `IHF` y `PrrF`
   necesitan las clases `complejo` y `familia`, esbozadas en la capa manual pero
   no cerradas en el resto del flujo.
3. **Que `CpxR` y `PirR` tengan una decisión escrita.** Para `CpxR` hay que
   resolver quién gana entre la asignación habitual y RefSeq. Para `PirR` no se
   encontró corroboración pública de ningún tipo.

Una nota de método, porque la cifra se midió mal una vez antes de quedar así. La
forma correcta de preguntar «cuánto cubren las fuentes públicas» no es tachar
filas del archivo publicado, sino **volver a construir el diccionario con la capa
manual vacía** y medir sobre eso. Tacharlas a mano se equivoca en las dos
direcciones: borrar la fila entera de un gen que la capa manual solo enriqueció
quita un gen que las fuentes públicas sí tienen, y borrar solo sus alias deja en
pie símbolos que **también** puso la capa manual. La reconstrucción no tiene ese
problema, y además se comprobó que con la capa manual reproduce
`etapa2/genes_pao1.tsv` **byte por byte**, así que lo único que separa los dos
escenarios es la capa manual.

### El patrón de oro: 190 relaciones que el corpus sí contiene

La lámina 8 decía que el obstáculo era la evaluación: el modelo propone
relaciones para *P. aeruginosa* y no había contra qué compararlas. Esto lo
ataca.

**Cómo se construyó**, que es lo que no estaba escrito en ninguna parte:

1. Se eligieron seis subsistemas regulatorios de *P. aeruginosa* bien estudiados:
   captación de hierro y sideróforos, factores sigma, sistemas de dos componentes
   y secreción tipo III, quorum sensing, bombas de expulsión RND, y formación de
   biopelícula por c-di-GMP.
2. Para cada uno se listaron las relaciones que la literatura da por
   establecidas, con su signo y su nivel de certeza.
3. Cada relación se buscó en el corpus completo: los 918 textos completos y los
   2 354 resúmenes.
4. De cada una que apareciera se guardó la **oración literal** que la afirma y
   los artículos donde está.
5. Se verificó que cada oración guardada existiera de verdad donde la fila decía.

**Resultados.** 190 relaciones entre 55 factores y 110 genes blanco, repartidas
en hierro 41, sigma 37, dos componentes y secreción 36, quorum sensing 30, bombas
RND 29 y biopelícula 17. Por signo: 117 activan, 67 reprimen, 6 regulan sin
signo. Por certeza: 139 establecidas y 51 probables.

**181 de las 190 se encontraron en el corpus.** De esas 181, se comprobó que 180
tienen su oración literalmente en el texto: 161 exactas y 19 por fragmento
contiguo. **Ninguna oración inventada.**

De ahí sale el resultado que de verdad importa:

> Solo 9 relaciones canónicas faltan por completo del corpus, y casi todas son de
> autorregulación. Eso significa que **si el modelo no recupera una relación
> conocida, el fallo es del modelo y no del corpus.** Antes de esto no se podía
> distinguir una cosa de la otra.

**El denominador honesto son ~169, no 190.** Hay que restar las 9 que el corpus
no contiene, 6 cuyo signo la propia literatura deja sin resolver, y 5 en disputa
entre artículos. Un ejemplo de estas últimas: para `RhlR → rpoS`, dos artículos
la afirman, uno dice explícitamente lo contrario y un cuarto invierte la
dirección de la flecha.

**Dos sesgos que hay que declarar.** El corpus tira hacia virulencia y
biopelícula, porque es lo más publicado; y la granularidad no siempre es el gen,
sino el operón, así que `algD` funciona como representante de un bloque de doce
genes.

### 93 oraciones con la respuesta puesta de antemano

Hay una forma barata de encontrar errores del clasificador sin anotar nada
nuevo: buscar relaciones cuyo signo se conoce con certeza y ver qué contesta.

Se tomaron seis represores de bombas de expulsión —MexR, NalC, NalD, NfxB, MexZ
y MexL— cuya función represora está establecida, y se extrajeron del corpus
**198 oraciones** de 29 artículos donde aparecen junto a su bomba blanco. De
esas, **93 afirman la relación** y por tanto tienen respuesta conocida
(«reprime»): 69 con redacción directa y **24 escritas desde el fenotipo del
mutante**, que son la trampa:

> *«mutations in nfxB lead to overexpression of MexCD-OprJ»*

Un extractor descuidado lee «mutación» y «sobreexpresión» y contesta «activa»,
cuando la relación es exactamente la contraria. Es el mismo fallo que ya se había
observado con la línea base por reglas y que se reportó en el seminario.

Las otras 105 oraciones son co-menciones sin relación afirmada: negativas
realistas del mismo dominio, que es justo el tipo de ejemplo negativo que le
falta al entrenamiento.

Estado: **pendiente** de correrse contra el modelo.

### Un problema que la repartición no arregla

Rehacer la partición corrige la medición, no el diseño del conjunto de datos. Y
hay un problema de diseño que conviene decir en voz alta.

**La clase «sin relación» no es una clase semántica.** De sus 493 ejemplos,
**485 (98.4 %) comparten fragmento de texto y par (factor, gen) con otra fila
etiquetada como positiva.** Lo único que las distingue es cuál de las dos
menciones lleva el marcador. Así que lo que el modelo aprende bajo esa etiqueta
no es «aquí no hay relación», sino «la mención marcada no es la que está pegada
al verbo».

Eso pone un techo duro: por textos que se contradicen entre sí, ninguna
configuración puede pasar de 0.9962 de exactitud. Y crea un desajuste con el uso
real: cuando el modelo se aplique al corpus de *P. aeruginosa*, las negativas no
serán «par correcto, mención equivocada», sino pares que aparecen juntos sin
ninguna relación entre ellos. Son dos problemas distintos.

Arreglarlo pide anotación, no código.

---

### El programa ya corre entero, y todavía no certifica una cifra

Ya existe el camino completo: del corpus salen pares de genes que aparecen en la
misma oración, el clasificador les pone signo, se arma la red y se compara contra
el patrón de oro. Y como el objetivo de todo este trabajo es no volver a publicar
un número que se mide a sí mismo, antes de correrlo en serio se hizo lo contrario
de lo habitual: **se intentó engañarlo a propósito.**

El ataque más simple fue el más revelador. Se sustituyó el clasificador por uno
que no lee nada y contesta siempre lo mismo, `activates`. El programa lo
certificaba con código 0: «se distingue del azar». Y tenía razón en lo que medía
—el problema era el rival. Como el patrón de oro trae 97 activaciones y 42
represiones, **contestar siempre `activates` acierta el 69.8 % sin leer una sola
palabra**, y ganarle a una moneda al aire no dice nada. Ahora la comparación es
contra esa clase mayoritaria además de contra el azar, y el clasificador constante
sale con ventaja de +0.0 puntos, `p = 0.542`, rechazado. Un clasificador de
palabras clave de verdad, en cambio, sí pasa: 84.9 % contra 68.1 %.

Se cerraron cuatro huecos de esa misma familia —**todos eran comprobar la etiqueta
de un archivo en vez de su contenido**— y la batería de pruebas de la etapa 2
pasó de 453 a 482. Pero dos rondas de ataque posteriores encontraron cinco cosas
que siguen pasando, y conviene decirlas antes de que alguien cite un número:

- Contaminar el diccionario **a medias** —copiarle un 12 % de filas del patrón de
  oro— no dispara ningún aviso, sube todas las cifras publicadas y de hecho
  **baja** el indicador que debería detectarlo.
- La evaluación recibe cuatro archivos y no comprueba que vengan de la misma
  corrida. Con la misma red y una lista de candidatos recortada, la exhaustividad
  pasa de 80.6 % a 100.0 % sin una queja.
- Hay una bandera para excluir relaciones en disputa cuyo único control es que la
  justificación no esté vacía: excluyendo justo las que el programa erró, el
  acierto sube a 100.0 %.
- El umbral con que se arma la red no queda registrado, y mueve la exhaustividad
  entre 9.7 % y 93.8 % sobre las mismas predicciones.

Ninguna de esas cinco es un accidente que ocurra solo; todas exigen que alguien
haga algo raro, y dos de ellas se podrían cometer por descuido. **La conclusión
honesta es que hoy el programa detecta al tramposo torpe y no al cuidadoso**, y
que una cifra suya solo vale acompañada del registro de su corrida. Están todas
documentadas con el ataque exacto que las demuestra en `docs/decisiones.md`.

Vale la pena decir por qué esto sale en un informe y no se guarda: **el proyecto
existe porque una métrica inflándose sin que nadie lo notara costó meses.**
Encontrar cinco maneras más de que eso pase, y escribirlas, es el trabajo; enseñar
solo el 0.92 sería repetir el error con mejor ortografía.

## Lo que todavía no está medido

| falta | qué lo produce | qué cambiaría si sale distinto |
|---|---|---|
| Repetir con varias semillas | `barrido.py --semillas 42,43,44` | Ya no es una suposición: reentrenar la misma configuración **con la misma semilla** la movió 0.0125 en prueba. Con varias semillas se podría reportar cada cifra con su dispersión en vez de como un punto |
| Un brazo de control con partición al azar | `particionar.py`, todavía no lo produce | Sin él, la diferencia contra 0.8721 mezcla tres causas: quitar la contaminación, un conjunto de prueba más difícil, y haber reelegido los ajustes |
| ~~Una línea base barata (clase mayoritaria)~~ | **hecho** — `evaluar_oro.py` la calcula sobre el mismo subconjunto que evalúa, con binomial exacta | Ya rechaza al clasificador constante (69.8 % contra 69.8 %, p = 0.542) |
| Correr el clasificador contra el patrón de oro y la auditoría de signo | Los dos archivos ya existen | Sería la primera cifra de desempeño sobre *P. aeruginosa*, no sobre *E. coli* |
| Reconocer los 55 factores del oro con fuentes públicas | Tomar los sinónimos de proteína de UniProt en vez de firmarlos a mano, admitir complejos y familias de ARN, y resolver `CpxR` y `PirR` con una decisión escrita | Haría reproducibles los diez que hoy dependen de una firma humana. Hoy se reporta 43 de 55, que es el número honesto |
| Que la evaluación exija que sus cuatro entradas sean de la misma corrida | `red.py` ya deja la procedencia en `red_informe.json`; `evaluar_oro.py` no lo abre | Hoy la misma red publica 80.6 % o 100.0 % de exhaustividad según qué archivo se le ponga al lado, con código 0 |
| Detectar la contaminación parcial del diccionario | Un indicador que suba, no que baje, al añadir nombres del patrón de oro | Un 12 % de filas copiadas hoy es invisible y mejora todas las cifras |
| Registrar los umbrales y las filas excluidas en el JSON de la evaluación | Copiarlos de `red_informe.json` y acotar `--disputadas` | Sin eso dos corridas con trece puntos de diferencia entregan un JSON idéntico |
| Un conjunto anotado a mano de PAO1 | Muestreo por incertidumbre sobre lo que el modelo ya infirió | Es el obstáculo de fondo; sin él no hay entrenamiento en la especie objetivo |
| Correr el modelo sobre los 1 006 textos completos (hoy son 130) | El programa de inferencia del servidor | Cierra la pregunta de cuánto aporta el texto completo frente al resumen |

---

## Conclusiones

1. **El corpus existe, es reutilizable y contiene la evidencia.** 2 361
   artículos, 1 006 con texto completo, con el estado registrado para que nadie
   vuelva a descargar lo mismo. Y contiene lo que hace falta: solo 9 de 190
   relaciones canónicas faltan por completo. **medido**
2. **La métrica que se tenía medía memorización, y ahora hay una partición que
   no lo permite.** El 73.9 % de contaminación en el conjunto de prueba pasó a
   0.0 %. Esto no invalida el modelo; invalida el número que lo describía.
   **medido**
3. **Sin contaminación el modelo no empeora: mejora.** La misma configuración
   que el servidor reportó como suya pasa de 0.8721 a **0.9335** en prueba, y 12
   de las 24 corridas superan el número heredado. Y la elección de
   hiperparámetros del servidor resultó correcta: lo que estaba mal era la
   medición. Lo que queda abierto es cuánto de la diferencia atribuir a haber
   quitado la contaminación, porque el conjunto de prueba también cambió.
   **medido (24 de 24)**
4. **El obstáculo que señalaba el seminario dejó de ser total.** Ya hay contra
   qué comparar: 190 relaciones canónicas y 93 oraciones con signo conocido. No
   sustituyen un conjunto anotado a mano de *P. aeruginosa*, pero permiten
   detectar errores hoy. **medido / pendiente**
5. **Lo que no se resolvió.** La clase «sin relación» es un artefacto del
   marcado, no una categoría semántica, y el entrenamiento no se parece al uso
   real. Rehacer la partición no lo toca. **declarado**

---

## Siguientes pasos

1. **Correr el clasificador contra el patrón de oro y la auditoría de signo.**
   No requiere entrenar nada, no depende de tener GPU, y da la primera cifra de
   desempeño sobre *P. aeruginosa* en vez de sobre *E. coli*. Es lo más barato y
   lo que más aporta.
2. **Añadir el brazo de control**, que es lo que permitiría atribuir la
   diferencia contra el 0.8721 a una causa y no a tres. Depende de programarlo
   en `particionar.py`, no de conseguir GPU.
3. **Repetir con varias semillas** (`--semillas 42,43,44`), para reportar cada
   cifra con su dispersión en vez de como un punto. Es lo que falta para que el
   orden de la tabla signifique algo.
4. **Anotar un conjunto de PAO1**, muestreando por incertidumbre sobre lo que el
   modelo ya infirió. Es el trabajo de fondo y no depende de los anteriores.

---

## Por dónde seguir leyendo

| si quieres saber | lee |
|---|---|
| El panorama y el estado del proyecto | este informe |
| Cómo se opera la herramienta que construye el corpus | [`../README.md`](../README.md) |
| Qué formato tienen los datos que la etapa 1 entrega a la etapa 2 | [`traspaso-etapa-2.md`](traspaso-etapa-2.md) |
| Todo sobre el modelo heredado, incluidas sus piezas rotas | [`ficha-modelo-bert.md`](ficha-modelo-bert.md) |
| El detalle de la contaminación, la partición, Colab y el patrón de oro | [`../etapa2/README.md`](../etapa2/README.md) |
| Por qué cada decisión de diseño se tomó así y no de la forma obvia | [`decisiones.md`](decisiones.md) |
| Las diapositivas del seminario (láminas 7 a 9 desfasadas) | `../salidas/Seminario_GRN_IIMAS_final.pptx` |

Lo que **no** está en el repositorio y viene del servidor del asesor:
`ecoli_curated.tsv`, los tres `entity_marked_*.jsonl` y
`bio_bert_re_finetune.py`. Están en `.gitignore` a propósito: no son datos
propios y no se versionan aquí.

---

## Anexo — qué contiene cada archivo de datos

### `etapa2/oro_pseudomonas.tsv` — 190 filas

| columna | contenido |
|---|---|
| `tf` | factor de transcripción, 55 distintos |
| `blanco` | gen u operón regulado, 110 distintos |
| `signo` | `activates` 117, `represses` 67, `regulates` 6 |
| `certeza_dominio` | `establecida` 139, `probable` 51 |
| `subsistema` | los seis: hierro 41, sigma 37, dos componentes y T3SS 36, quorum sensing 30, bombas RND 29, biopelícula 17 |
| `alias` | otros nombres del factor o del blanco |
| `atestiguado` | `true` 181, `false` 9 |
| `n_articulos` | en cuántos artículos del corpus aparece |
| `pmids` | la lista, separada por comas |
| `oracion` | la evidencia literal; vacía en las no atestiguadas |

### `etapa2/auditoria_signo.tsv` — 198 filas

| columna | contenido |
|---|---|
| `pmid` | artículo, 29 distintos |
| `fuente` | `fulltext` 178, `abstract` 20 |
| `tf`, `blanco` | el represor y su bomba |
| `signo_correcto` | `represses` en las 93 evaluables, vacío en las 105 restantes |
| `evaluable` | `true` 93, `false` 105 |
| `redaccion` | `otra` 85, `directa` 69, `fenotipo_mutante` 24, `contraria_aparente` 20 |
| `mencion_tf`, `mencion_blanco` | el texto exacto de cada mención |
| `oracion` | la oración completa |

La aritmética que no es obvia: las 93 evaluables son `directa` más
`fenotipo_mutante`; las 105 restantes son `otra` más `contraria_aparente`.

### `etapa2/barrido_resumen.csv` del barrido

`nombre, i, lr, epochs, batch, warmup, semilla, max_length, dev_macro_f1,
dev_accuracy, test_macro_f1, test_accuracy, segundos, datos, huella`

La columna `huella` es una firma del contenido de la partición con la que se
produjo el resultado. Sirve para que reusar la misma carpeta de resultados con
otra partición se rechace, en vez de saltarse las corridas y reportar números
viejos como si fueran nuevos.

### `entity_marked_*.jsonl` — el formato de entrada del modelo

Cinco campos: `text, label, pmid, tf, target`. El texto lleva las dos menciones
marcadas con etiquetas, así el modelo sabe de qué par se le está preguntando.

**Un aviso que cuesta caro ignorar:** el orden de etiquetas por omisión que trae
`bio_bert_re_finetune.py` **intercambia `represses` con `no_relation`** respecto
al orden real del modelo entrenado del servidor. Entrenar sin pasarle explícitamente
`--labels_json` y luego leer el resultado con el orden del servidor reporta como
«sin relación» lo que el modelo llamó «reprime». Por eso `particionar.py` escribe
un `label_mapping.json` en cada carpeta que produce, y `barrido.py` se niega a
correr si falta. El detalle está en [`ficha-modelo-bert.md`](ficha-modelo-bert.md).
