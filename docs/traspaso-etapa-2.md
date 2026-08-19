# Traspaso a la etapa 2

Documento para llevar al servidor donde vive el modelo BERT. Describe qué
produjo la etapa 1, en qué formato exacto, y qué hace falta averiguar del
lado del modelo para poder conectarlos.

Corte de datos: 19 de agosto de 2026.

> **Contestado.** La sección 4 de este documento ya tiene respuesta: ver
> [`ficha-modelo-bert.md`](ficha-modelo-bert.md), levantada del servidor el
> 19 de agosto. Lo que sigue se conserva porque describe el lado del corpus,
> que no cambia. Tres cosas de la ficha corrigen supuestos de aquí:
>
> - **El modelo se entrenó en *E. coli*, no en *Pseudomonas*.** Es
>   transferencia entre especies, y esa es la premisa central del trabajo.
> - **La unidad de entrada ya estaba decidida**: ventana de ±300 caracteres
>   alrededor del par, no el artículo. La duda sobre segmentación de la
>   sección 4 queda resuelta.
> - **Hay fuga de datos entre particiones** que infla las métricas
>   reportadas. Es el trabajo pendiente número uno.

---

## 1. Qué hay disponible

El corpus vive en una base SQLite (`datos/grn.db`) más archivos de texto en
disco. Números al corte:

| | |
|---|---|
| Artículos únicos | 2 361 |
| Con resumen | 2 354 |
| **Con texto completo** | **1 006** |
| Solo resumen, sin texto completo | 1 348 |
| Sin ninguno de los dos | 7 |
| Volumen de texto completo | ~51 millones de caracteres |

Los 1 006 con texto completo son el insumo real para extracción de
relaciones. Los otros 1 348 tienen resumen, que sirve para clasificación
gruesa pero no contiene el detalle experimental donde se afirma que un
factor regula a un gen.

**Por qué no hay más:** 738 artículos no están en PubMed Central y 607 están
pero fuera del subconjunto de acceso abierto. De esos 607 se verificó contra
cuatro fuentes distintas que no existe texto legible por máquina en ninguna
parte. No es una limitación de la herramienta.

---

## 2. Cómo sacar los datos

### Metadatos y resúmenes — JSONL

```bash
python cli.py export <nombre_consulta> --formato jsonl
# -> salidas/<nombre_consulta>.jsonl
```

Un objeto JSON por línea, codificación UTF-8. Esquema de cada renglón:

| campo | tipo | ejemplo |
|---|---|---|
| `pmid` | str | `"40348909"` |
| `doi` | str | `"10.1007/s00203-025-04346-8"` |
| `pmcid` | str | `"PMC10418997"` o `""` |
| `titulo` | str | |
| `abstract` | str | texto corrido; las secciones estructuradas vienen como `BACKGROUND: … RESULTS: …` |
| `revista` | str | `"Arch Microbiol"` |
| `anio` | str | `"2025"` — es texto, no entero: PubMed a veces trae rangos |
| `autores` | list[str] | `["Ramesh R", "Rekha ND"]` |
| `mesh_terms` | list[str] | |
| `keywords` | list[str] | |
| `tipos_publicacion` | list[str] | `["Journal Article", "Review"]` |
| `tiene_abstract` | int | 0 o 1 |
| `extraido_en` | str | ISO 8601 UTC |

**Todas las claves están en ASCII sin acentos**, a propósito: es el contrato
con el resto del pipeline y no debe cambiarse.

### Texto completo — archivos de texto

```
datos/fulltext/xml/{pmid}_{pmcid}.txt    texto extraído por secciones
datos/fulltext/xml/{pmid}_{pmcid}.xml    el JATS original, por si hace falta
```

El `.txt` trae jerarquía tipo Markdown, derivada de la estructura del JATS:

```
# Título del artículo

## ABSTRACT

Párrafo…

## BACKGROUND

Párrafo…

### Subsección

## PIES DE FIGURA Y TABLA

Figura 1. Unión de LasR al promotor de rhlR…
```

Niveles: `#` es el título (uno por archivo), `##` sección, `###` a `#####`
subsecciones. Los párrafos van separados por línea en blanco.

**La sección `PIES DE FIGURA Y TABLA` merece atención especial:** ahí se
concentran las afirmaciones de relación factor-gen, a menudo con el signo
explícito. Aparece en 916 de los 918 archivos derivados de PMC.

### La base directamente

Si conviene consultar en vez de exportar, el esquema está documentado en
`structure.md`. Cinco tablas; las relevantes son `documentos` (una fila por
PMID) y `descargas` (qué texto se obtuvo de cada uno y por qué no, cuando no).

---

## 3. Lo que el dominio impone

Estas no son preferencias, son propiedades del material:

- **Gen y proteína se distinguen solo por capitalización.** `lasR` es el gen,
  `LasR` la proteína, y son la misma entidad para efectos de la red. Cualquier
  normalización tiene que unirlas.
- **Operones** aparecen como `mexEF-oprN`, con guion y varios genes.
- **Etiquetas de locus** de la cepa PAO1 como `PA0762` conviven con los
  nombres comunes y se refieren a lo mismo.
- **Los factores sigma** (`RpoS`, `AlgU`) suelen ser concentradores de la red:
  muchas aristas salen de pocos nodos.
- **Tres clases de relación**: `activator`, `repressor` y `regulator`, este
  último para cuando el artículo establece la relación sin resolver el signo.
  La tercera clase no es un descarte: es información.
- **El reconocimiento de genes por patrón produce falsos positivos** y no
  sustituye al reconocimiento de entidades. Sirve como línea base a superar,
  no como solución.

---

## 4. Qué averiguar en `04_modeling`

Lo que hay que responder del lado del modelo para poder conectarlo con este
corpus. En orden de importancia:

### Sobre el modelo

- [ ] **¿Qué variante es?** BioBERT, PubMedBERT, SciBERT, BERT multilingüe,
      alguno en español. Determina si el vocabulario ya conoce nomenclatura
      biomédica o hay que lidiar con la segmentación de `mexEF-oprN`.
- [ ] **¿Para qué tarea está ajustado?** Reconocimiento de entidades,
      clasificación de relaciones, clasificación de documentos, o solo
      preentrenamiento de dominio. Cambia por completo cómo se usa.
- [ ] **¿Qué etiquetas produce?** El conjunto exacto. Si es de entidades, qué
      tipos; si es de relaciones, qué clases y si coinciden con las tres de
      arriba.
- [ ] **¿Qué formato de entrada espera?** Longitud máxima de secuencia,
      tokenizador, si espera oraciones sueltas o párrafos. Con texto de
      mediana 50 000 caracteres, la segmentación es una decisión real.
- [ ] **¿En qué se entrenó?** Corpus, tamaño, si fue en inglés. Y sobre todo:
      **¿quedaron los datos de entrenamiento?** Eso decide si se puede evaluar
      sin anotar desde cero.

### Sobre la evaluación

- [ ] **¿Hay un conjunto de prueba anotado?** Es lo más caro de conseguir y lo
      que determina si se puede comparar modelos o solo describirlos.
- [ ] **¿Hay resultados reportados?** Precisión, exhaustividad, F1 y sobre qué
      conjunto. Sirven de línea base sin volver a correr nada.
- [ ] **¿Existe una red de regulación curada de *P. aeruginosa*** que sirva de
      referencia, o hay que construirla?

### Sobre lo práctico

- [ ] Formato de los pesos y con qué versión de qué biblioteca se cargan.
- [ ] Si hay GPU disponible en ese servidor, y de cuánta memoria.
- [ ] Si el modelo se puede copiar o tiene que quedarse ahí.

---

## 5. Una pregunta que este corpus permite responder

El corpus quedó dividido de forma natural: **1 006 artículos con texto
completo y 1 348 con solo el resumen**, sobre el mismo dominio y la misma
consulta.

Eso permite medir directamente cuánto aporta el texto completo frente al
resumen en esta tarea. Es una pregunta con valor propio para la tesis, y su
respuesta decide algo práctico: si vale la pena perseguir los 1 355 textos que
faltan, o si el resumen basta.

**Ya hay una respuesta parcial**, del lado del servidor: sobre 130 PDFs y 388
resúmenes, la *tasa* de relaciones por par candidato resultó casi idéntica
—10.5 % contra 10.0 %—, pero el texto completo produjo unos 103 candidatos por
artículo contra 3.7 del resumen. O sea que el texto completo no encuentra
relaciones más densas: encuentra **muchas más**.

Correr lo mismo sobre los 1 006 textos de la etapa 1 —contra los 130 PDFs de
ahora— cierra la pregunta, y es una extensión directa, no un experimento nuevo.
Lo que falta para que la respuesta sea concluyente es saber si esas relaciones
adicionales son **correctas**, y eso exige el conjunto de referencia anotado.

---

## 6. Lo que sigue sin estar decidido

Ninguna de estas está resuelta, y conviene no dar ninguna por supuesta al
llegar al servidor:

- El conjunto de referencia para evaluar — el obstáculo real de la etapa 2.
- Qué modelos entran en la comparación, incluidas las líneas base baratas
  (coocurrencia en la misma oración es la más obvia).
- La unidad de evaluación: oración, artículo o arista de la red. Cambia por
  completo lo que significan las métricas.
- El criterio de éxito: qué valor haría el resultado útil para el laboratorio.

---

## 7. Contexto de la herramienta, por si hay que volver a ella

- Corre con **solo biblioteca estándar de Python 3.8+**, sin dependencias.
- Se opera por línea de comandos (`cli.py`) o por un tablero local
  (`python servidor.py --abrir`, solo en 127.0.0.1).
- **No vuelve a descargar lo que ya tiene.** Sobre las seis consultas
  registradas, la suma ingenua daría 5 331 descargas; se hicieron 2 361.
- Las credenciales de NCBI salen de `NCBI_API_KEY`/`.key` y
  `NCBI_EMAIL`/`.correo`. **Ninguno de los dos archivos va al repositorio.**
- 349 pruebas, ninguna toca la red.
- Las decisiones de diseño y su porqué están en `docs/decisiones.md`.

**Cuidado al correrlo en un servidor compartido:** NCBI limita por dirección
IP, no por usuario. Un bloqueo deja sin servicio a todos los que salen por esa
red. Conviene avisar a quien administra la máquina antes de lanzar corridas
largas.
