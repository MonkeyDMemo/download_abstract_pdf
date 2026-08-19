# Ficha del modelo BERT — respuestas a la sección 4 del traspaso

Levantada del servidor el 19 de agosto de 2026, en respuesta a las preguntas
de [`traspaso-etapa-2.md`](traspaso-etapa-2.md).

**Todas las rutas de este documento son relativas a `/home/user/pseudomonas-trn`
en el servidor**, no a este repositorio. La carpeta es `04_modelling` (con
doble L). No es repositorio git.

---

## 1. Respuestas directas

### El modelo

| | |
|---|---|
| Variante | `dmis-lab/biobert-base-cased-v1.1` |
| Arquitectura | `BertForSequenceClassification`, 12 capas, 12 cabezas, hidden 768 |
| Vocabulario | cased, 28 996 piezas, 512 posiciones |
| Tamaño | ~433 MB por checkpoint, float32 |
| Tarea | Clasificación de relaciones (RE), **no** NER |

**El reconocimiento de entidades no lo hace el modelo.** Lo hace antes un
diccionario por expresiones regulares (`02_ner/nerspan_rules.py` sobre
`00_data/raw/pseudomonas_genes.tsv`: 5 697 genes PAO1, 536 marcados como TF).
Es decir: lo que el traspaso identificaba como «línea base a superar» es lo que
está en producción para las entidades.

**Etiquetas** — el orden real, el de `config.json` y `label_mapping.json`:

| id | etiqueta | equivale a |
|---|---|---|
| 0 | `activates` | activator |
| 1 | `no_relation` | — |
| 2 | `regulates` | regulator (sin signo resuelto) |
| 3 | `represses` | repressor |

> **Aviso.** `config.yaml` y el respaldo de `04_modelling/infer_from_pairs.py:40`
> declaran **órdenes distintos y equivocados**. Hoy no hacen daño porque el
> código lee `id2label` del checkpoint, pero cualquier script nuevo que copie
> esas listas **invertirá activador y represor en silencio**.

**Formato de entrada** — texto con las dos entidades marcadas en línea:

```
... placing the NanR , <e1> IHF </e1> and NagC binding sites closer to the
<e2> fimB </e2> promoter enhances the ability ...
```

`<e1>` es el factor de transcripción, `<e2>` el gen blanco. Truncado a 512
tokens. **No es oración suelta: es una ventana de ±300 caracteres alrededor
del par**, recortada del párrafo, con distancia máxima de 600 caracteres entre
menciones. Longitud real: mediana 244 caracteres, máximo 687.

Eso resuelve la duda sobre segmentación del traspaso: **la unidad ya está
decidida y es la ventana intra-párrafo**, no el artículo. Los ~51 M de
caracteres de la etapa 1 se trocean solos.

Dos detalles del tokenizador:

- `<e1>`, `</e1>`, `<e2>`, `</e2>` **no son tokens especiales**: se parten en
  `<`, `e`, `##1`, `>`. Funciona, pero añadirlos al vocabulario es la mejora
  barata más obvia.
- El tokenizador tiene `lowercase: true` pese a ser un checkpoint *cased*
  —defecto conocido del `tokenizer_config.json` de dmis-lab—. Consecuencia:
  `lasR` y `LasR` se colapsan. Para la red eso es lo deseado, pero el modelo
  nunca aprovecha la mayúscula que distingue proteína de gen.

### Los datos de entrenamiento

**No se entrenó en *Pseudomonas*. Se entrenó en *E. coli*.**

Fuente: `00_data/raw/ecoli_curated.tsv`, 1 562 filas, 119 PMIDs, formato
RegulonDB. Distribución original: 593 activator, 493 no_relation,
269 repressor, 207 regulator.

| archivo | filas | activates | no_relation | represses | regulates |
|---|---|---|---|---|---|
| `entity_marked_train.jsonl` | 1 249 | 474 | 394 | 215 | 166 |
| `entity_marked_dev.jsonl` | 156 | 59 | 49 | 27 | 21 |
| `entity_marked_test.jsonl` | 157 | 60 | 50 | 27 | 20 |

Campos: `text`, `label`, `pmid`, `tf`, `target`.

Es **transferencia entre especies**: entrenado en *E. coli*, aplicado a
*P. aeruginosa* sin un solo ejemplo de PAO1 en el entrenamiento. Es razonable
dado que no había datos anotados de PAO1, pero es la premisa central del
trabajo y no estaba enunciada.

### La evaluación

**Conjunto de prueba anotado:** sí para *E. coli* (157 ejemplos), **ninguno
para *P. aeruginosa***. Cero ejemplos PAO1 anotados a mano en todo el árbol.

**Resultados** — barrido de 24 corridas (lr × epochs × batch × warmup), con
pesos de clase inversos a la frecuencia y paro temprano con paciencia 2.
Mejor: `run_22_lr3e-5_ep8_bs16_wu0.1`.

| | dev | test |
|---|---|---|
| macro-F1 | 0.9024 | 0.8721 |
| exactitud | 0.9103 | 0.8854 |
| precisión (macro) | 0.9076 | 0.8934 |
| exhaustividad (macro) | 0.8985 | 0.8621 |

Rango del barrido: 0.767 a 0.902. Tendencia limpia: lr alto y batch chico ganan.

> **Estos números están inflados.** Ver sección 2.

**Red curada de referencia de *P. aeruginosa*:** no existe en el repositorio.
Solo el diccionario de genes con la bandera `If_TFs`.

### Lo práctico

- Pesos en `pytorch_model.bin` (no safetensors), `transformers==4.44.2`.
- Entorno conda **`pseudoRE`**: Python 3.10, torch 2.6.0+cu124, datasets 2.20.0.
- **GPU: NVIDIA RTX 3070, 8 GB**, CUDA 12.4. Suficiente para BERT-base a 512
  tokens con batch 16.
- El script usa `evaluation_strategy=`, removido en transformers ≥ 4.46 (ahora
  `eval_strategy`). Solo importa si se reentrena en un entorno más nuevo.
- El árbol completo pesa **75 GB** por los `optimizer.pt` de cada corrida. Para
  llevarse el modelo bastan ~433 MB del `run_22` más su tokenizador.

---

## 2. Los dos hallazgos que cambian la lectura

### 2.1 Fuga de datos entre particiones

Los splits se hicieron **a nivel de ejemplo, no de documento ni de oración**.
Como la misma oración genera varios ejemplos, cae en train y en test a la vez.

| medida | valor |
|---|---|
| PMIDs compartidos train ∩ test | 61 de 119 |
| PMIDs compartidos train ∩ dev | 65 de 119 |
| **ejemplos de test cuya oración base ya está en train** | **73.9 %** |
| ejemplos de dev cuya oración base ya está en train | 68.6 % |
| **pares (TF, blanco) de test ya vistos en train** | **86.6 %** |

Con eso, 0.87–0.90 de macro-F1 mide sobre todo memorización. La cifra honesta
exige reparticionar y volver a correr el barrido: los datos y el script están,
cuesta una noche de GPU. Es probable que el número baje y que el orden de las
24 corridas cambie.

**No invalida el trabajo: invalida el número.**

### 2.2 Ya hay respuesta parcial sobre texto completo contra resumen

| entrada | documentos | pares candidatos | con relación |
|---|---|---|---|
| texto completo (PDF vía GROBID) | 130 | 13 368 | 1 406 (10.5 %) |
| resúmenes | 388 | 1 437 | 144 (10.0 %) |

La *tasa* es casi idéntica; lo que cambia es el **volumen**: ~103 candidatos
por artículo contra ~3.7, unas 28 veces más. Sin conjunto de referencia no se
sabe si son más relaciones *correctas*.

---

## 3. Estado del pipeline

```
PDFs (130) ──GROBID──> pdf_txt_grobid/ (130)
Resúmenes (388) ─────> abs_json/ (388)
                            ↓
                   02_ner/nerspan_rules.py      ← diccionario PAO1, regex
                            ↓
                  spans_ner/ (130) + spans_abs/ (388)
                            ↓
           03_candidates/build_entity_marked_from_spans.py
                            ↓
                pairs_entity_marked.tsv (34 MB)
                            ↓
              04_modelling/infer_from_pairs.py  ← BioBERT run_22
                            ↓
                  infer.tsv  (13 368 filas)
                            ↓
        06_evaluation/dedup_by_paragraph_v2.py → infer_dedup.tsv (3 735)
        06_evaluation/filter_by_conf.py        → infer_filtered.tsv (1 141)
                  umbrales: act ≥ 0.65, rep ≥ 0.70, reg ≥ 0.60
                            ↓
              infer_filtered_with_titles.tsv (1 152, con títulos)
```

**Red resultante:** 789 aristas únicas sobre 656 pares distintos, **104 TFs** y
**227 genes blanco**, con evidencia en 93 artículos. Composición: 373 represses,
366 regulates, 357 activates.

Los umbrales son valores fijos sin justificación documentada, y sin conjunto de
referencia no hay cómo calibrarlos. Es la segunda decisión no auditada del
pipeline, después del split.

### Piezas rotas o faltantes

- `00_data/processed/model_ckpt/` es el **checkpoint viejo** (dev 0.8595) y trae
  un `CHECKPOINT_DUMMY.txt`. El bueno es `sweep_biobert/run_22_.../`.
- `model_ckpt_best` es un **symlink roto**: ruta relativa mal formada.
- `04_modelling/infer_pseudo.py` es un **stub** que escribe
  `prediction='regulates'` y `conf=0.5` para todo. **Sigue citado en el README y
  en `make infer`.** Quien siga el README entrenará bien y luego inferirá basura.
- `06_evaluation/aggregate_edges.py` corrió tres veces pero
  `edges_aggregated.tsv` no existe.
- `05_active_learning/` está **vacío** — y es justo lo que produciría el
  conjunto de referencia de PAO1 que falta.
- El `Makefile` y el README describen un flujo distinto al que se ejecutó.

---

## 4. Trabajo pendiente

1. **Reparticionar y recorrer el barrido.** Corrección metodológica no
   negociable. Datos y script listos, ~24 corridas en la 3070.
2. **Anotar un conjunto de prueba de PAO1.** Sin él no hay número defendible
   sobre *Pseudomonas*. `infer_dedup.tsv` con su columna `conf` ya permite
   muestreo por incertidumbre: anotar las 200–300 más ambiguas rinde mucho más
   que anotar al azar.
3. **Línea base de coocurrencia** sobre el mismo conjunto.
4. **Correr el modelo sobre los 1 006 textos completos de la etapa 1** (hoy son
   130 PDFs) y cerrar la comparación texto completo contra resumen.
5. Arreglos baratos: el symlink, marcar `infer_pseudo.py`, corregir el orden de
   etiquetas en `config.yaml`, añadir `<e1>/<e2>` como tokens especiales, purgar
   los `optimizer.pt` (libera ~40 GB).

---

## 5. Rutas de referencia

| qué | dónde |
|---|---|
| **modelo bueno** | `00_data/processed/sweep_biobert/run_22_lr3e-5_ep8_bs16_wu0.1/` |
| entrenamiento | `04_modelling/bio_bert_re_finetune.py` |
| inferencia real | `04_modelling/infer_from_pairs.py` |
| inferencia falsa (stub) | `04_modelling/infer_pseudo.py` |
| barrido | `run_sweep_biobert.sh`, `summarize_sweep.py` |
| tabla del barrido | `00_data/processed/sweep_biobert/sweep_summary.csv` |
| datos de entrenamiento | `00_data/processed/entity_marked_{train,dev,test}.jsonl` |
| fuente original (E. coli) | `00_data/raw/ecoli_curated.tsv` |
| diccionario PAO1 | `00_data/raw/pseudomonas_genes.tsv` |
| red inferida | `00_data/processed/infer_filtered_with_titles.tsv` |
| entorno | conda `pseudoRE` |

---

## 6. Notas añadidas desde la etapa 1

Tres observaciones sobre el trabajo pendiente, desde el lado del corpus:

**Repartir por PMID no basta.** Aun separando documentos, el mismo par
`(LasR, rhlR)` puede aparecer en dos artículos y quedar en train y en test.
Conviene reportar **dos números**: partición por documento y partición por par.
El segundo es el honesto para la pregunta «¿generaliza a relaciones que no ha
visto?».

**Cuidado con el tamaño al repartir.** Son 1 562 ejemplos de 119 PMIDs, y
`regulates` tiene solo 207. Al partir por PMID es fácil que una clase quede con
una docena de ejemplos en test y su F1 se vuelva ruido. Revisar el balance
resultante y, si hace falta, usar validación cruzada por PMID en vez de una
sola partición.

**Verificación barata mientras no exista el conjunto anotado.** La red inferida
tiene 104 TFs. Las relaciones canónicas de *P. aeruginosa* son conocidas —LasR
sobre `rhlR`, la cascada del quorum sensing, AlgU sobre los genes de alginato—.
Revisar a mano si el modelo las encuentra cuesta una tarde y responde de forma
concreta si la transferencia entre especies funcionó. No sustituye a la
evaluación formal, pero es el tipo de evidencia que convence en una defensa.

---

## 7. Lo que apareció al medir los datos

Medido el 19 de agosto sobre los tres `entity_marked_*.jsonl`. La corrección
está en [`../etapa2/`](../etapa2/README.md).

### 7.1 La fuga se explica entera por una cifra

**1 562 ejemplos, pero solo 694 ventanas de texto distintas.** Cada ventana
produce un ejemplo por cada par que contiene, 2.3 en promedio. Los splits a
nivel de ejemplo separan copias del mismo fragmento, y de ahí sale el 73.9 %.

Los números de la sección 2.1 reproducen exactos desde este lado.

### 7.2 No se puede cortar por artículo y por par a la vez

Al unir en un grafo cada PMID con cada par que menciona, el corpus colapsa en
**una componente con el 89.1 % de los ejemplos**. No es una preferencia: es
imposible partirlo pidiendo las dos cosas. La partición usable agrupa por
**PMID + ventana** (108 grupos, el mayor de 105 ejemplos).

El corte por par pesa menos de lo que parecía: **176 de los 332 pares llevan
más de una etiqueta en el oro**, así que no hay un par→etiqueta que memorizar.

### 7.3 `no_relation` no es una clase semántica

**485 de los 493 ejemplos (98.4 %) comparten ventana y par con una fila
positiva.** Lo único que los separa es cuál mención lleva el marcador `<e2>`.
Con `activates` pasa en el 27.5 % de los casos, con `represses` en el 31.2 % y
con `regulates` en el 37.2 %.

El techo duro de exactitud es 0.9962 —solo 6 textos son literalmente
contradictorios—, así que el 0.8854 reportado no es imposible. Pero lo que el
modelo aprende a distinguir es «¿se marcó la mención pegada al verbo?», y en
inferencia sobre PAO1 las negativas son otras: pares que coocurren sin
relación. Es un desajuste entre entrenamiento y despliegue que **ninguna
repartición corrige**, y probablemente explica por qué los umbrales de
confianza hubo que fijarlos a mano.

### 7.4 Defectos menores del oro

- **6 textos con etiquetas contradictorias**, cinco dentro de train y uno
  repartido entre train y test (`Mlc`→`ptsG`, `no_relation` contra
  `represses`).
- **12 filas duplicadas exactas**. `MelR`→`melAB` aparece con texto idéntico
  bajo siete PMIDs distintos; cuatro de esas copias caían dos en train y dos
  en test.
- **Fuga que el PMID no puede evitar**: 12 ejemplos de test (7.6 %) tienen su
  ventana contenida en una de train, uno al 1.00 —un título citado en la
  bibliografía de otro artículo—.

### 7.5 El reparto reportado engaña sobre el tamaño

En la partición nueva, `regulates` en dev son 24 ejemplos **pero de solo 3
artículos**, y 12 salen del mismo. El test entero son 8 artículos. Contar
ejemplos sobreestima mucho la información disponible; lo que fija la
incertidumbre es el número de artículos independientes.

Por eso la cifra que se reporte debería venir de validación cruzada, no de una
sola partición.

### 7.6 Una trampa del script de entrenamiento

`bio_bert_re_finetune.py` trae
`LABELS_DEFAULT = ["activates","represses","regulates","no_relation"]`, que
comparado con el orden real del checkpoint deja `activates` en el id 0 pero
**intercambia `represses` con `no_relation`**. O sea que entrenar sin
`--labels_json` y luego leer el checkpoint con el orden del servidor reporta
como «sin relación» lo que el modelo llamó represión.

(La sección 1 avisaba del riesgo pero nombraba mal el par que se voltea: no es
activador contra represor.)
