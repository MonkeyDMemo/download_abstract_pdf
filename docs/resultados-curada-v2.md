# Reentrenamiento del BioBERT con la base curada: curada-v2

- Estado: **ok**.
- Inicio 2026-10-21T04:12:25Z; fin 2026-10-21T05:00:57Z (UTC).
- Commit `56bf3b1114`.

`<datos>`, `<runs>` y `<resultados>` son carpetas del servidor. Los ejemplos y el modelo no salen de ahí; este archivo lleva solo conteos y métricas.

## 1. Receta

- Run 22 (`run_22_lr3e-5_ep8_bs16_wu0.1`): lr 3e-5, 8 épocas, lote 16, calentamiento 0.1, weight decay 0.01, max_length 512, semilla 42, **sin pesos de clase** (enmienda 1 del protocolo) y paro temprano con paciencia 2, sobre `dmis-lab/biobert-base-cased-v1.1`.
- Partición por PMID, 80/10/10; validación cruzada de 5 pliegues con las semillas 42, 43, 44.
- El modelo desplegable es el de la partición única con la semilla 42, fijada de antemano: no se elige la mejor semilla.
- Clases evaluadas: activates, no_relation, represses. **Fuera de esta versión: regulates**: sin soporte para aprenderla ni medirla (ver el protocolo y la sección 5). El modelo conserva las cuatro etiquetas de `label_mapping.json`, pero no aprende regulates y no la va a predecir.
- Tope por entrenamiento: 4.0 h. GPU libre mínima: 6500 MiB.
- Protocolo de evaluación (`docs/protocolo-curada-v1.md`): commit `56bf3b1114` del 2026-10-20T22:12:18-06:00 (el primero, `c48eeae054`, del 2026-10-16T09:17:56-06:00); anterior al primer entrenamiento (2026-10-21T04:12:47Z): las cifras de la sección 8 son pre-registradas.
- **Desviaciones del protocolo:** pesos_clase: el protocolo fija inversa y esta corrida usó ninguno.

## 2. Reservas

- 46 PMIDs y 232 oraciones reservados; de la muestra de 50 juicios faltan 0 PMIDs y 0 oraciones.

## 3. La base contra PLAN.md 2.4

| conteo | esperado | medido | |
|---|---:|---:|---|
| filas | 5584 | 5584 | coincide |
| signo + | 4060 | 4060 | coincide |
| signo - | 598 | 598 | coincide |
| signo ? | 909 | 909 | coincide |
| signo d | 14 | 14 | coincide |
| signo ilegible | 3 | 3 | coincide |
| origen historica | 4824 | 4824 | coincide |
| origen biobert | 544 | 544 | coincide |
| origen ambos | 216 | 216 | coincide |
| origen otro | 0 | 0 | coincide |
| homologia | 2850 | 2850 | coincide |
| pmids_distintos | 309 | 309 | coincide |
| filas_sin_pmid | 1 | 1 | coincide |
| dois_descartados | 1 | 1 | coincide |

Coincide en todo.

## 4. Ejemplos

```text
Base curada: 5584 filas con valores (0 vacías); 5578 con los dos locus válidos y 6 descartadas por locus.
  signo: + 4060; - 598; ? 909; d 14; ilegible 3 (3 con un locus corrido).
  origen: Histórica 4824; BioBERT 544; Ambos 216; otro 0.
  homología 2850; PMIDs distintos 309; filas sin PMID 1; DOIs descartados 1; números descartados 0.
Reservas: PMIDs 46; oraciones 232; archivos leídos 1.
Pares: leídos 72969; reservados por PMID 6839 (artículos reservados presentes: 46); reservados por oración 516; sin locus 411; con un locus fuera de PAO1 0; con el marcado roto 0.
Filas que pueden dar positivos: 2161 de 5578 (fuera: homología 2850, BioBERT 517, d 9, signo ilegible 0, autorregulación 40, sin PMID 1); 226 con alguna oración en los pares.
Positivos: 1187 pares coinciden con una fila elegible y 568 solo con filas excluidas; 0 claves en conflicto (0 pares); 2 oraciones duplicadas; 718 recortadas por el tope.
Negativos: 2643 candidatos (fuera: autorregulación 958, par curado 2286; duplicados 39; recortados por el tope 1445); muestreados 467, de ellos 82 en una oración con positivo.
Texto repetido entre artículos: 0 ejemplos fuera.
Ejemplos: 934 (activates 322; represses 139; regulates 6; no_relation 467).
  positivos por origen: Ambos 213; Histórica 254.
  PMIDs: 96 distintos, 96 con positivo; los 5 con más ejemplos reúnen 228.
```

## 5. Partición por PMID

```text
Cargados 928 ejemplos de 96 PMIDs, 594 ventanas distintas.
Agrupando por pmid + ventana: 96 grupos indivisibles.
  tamanos: mayor=57 (6.1% del corpus)  mediana=5  menor=1

Reparto 80/10/10 (desbalance 0.157):

  parte          n  arts  activates   no_relation regulates   represses
  ----------------------------------------------------------------------
  train        717    87   257  35.8%  350  48.8%    0   0.0%  110  15.3%
  dev          110     5    32  29.1%   63  57.3%    0   0.0%   15  13.6%
  test         101     4    33  32.7%   54  53.5%    0   0.0%   14  13.9%
  TOTAL        928    96   322  34.7%  467  50.3%    0   0.0%  139  15.0%

  AVISO: dev no tiene ningun ejemplo de regulates: el F1 de esa clase ahi no se mide.
  AVISO: test no tiene ningun ejemplo de regulates: el F1 de esa clase ahi no se mide.
  Reporta validacion cruzada (--folds 5).
  La celda mas flaca: represses en test son 14 ejemplos, pero de solo 3 articulos
  (y 10 de ellos salen de uno solo).
  AVISO: con menos de 5 articulos independientes el F1 de esa clase es ruido,
  por bien que se vea el conteo de ejemplos. Reporta validacion cruzada (--folds 5).

  fuga vs train     texto   PMID     par  casi-dup
  --------------------------------------------------
  dev                0.0%      0   21.8%      0.0%
  test               0.0%      0    4.0%      0.0%

Particion limpia. Escrita en <datos>/por_pmid
Pasale --labels_json .../label_mapping.json al entrenamiento: el
LABELS_DEFAULT del script deja 'activates' en el id 0 pero
intercambia 'represses' con 'no_relation'.
```

- Veredicto: limpia.
- regulates quedó fuera antes de particionar: 6 ejemplos de 2 artículos. Que falte en dev y test es por eso, no un aviso.
- La celda más flaca es represses en test: 14 ejemplos de 3 artículos. particionar.py nombra una sola celda para dev y test juntos (en un empate, dev): que diga «test» no quiere decir que la otra parte esté bien.
- **La cifra honesta es la de validación cruzada** (`--folds 5`, sección 8).

### 5.1 Pliegues de la validación cruzada

Cada pliegue es test una vez (con el siguiente de dev y el resto de train). La línea base de memorización no depende del modelo: es la misma antes y después de entrenar.

| pliegue | artículos | ejemplos | activates | no_relation | represses | par ya visto en train | macro-F1 línea base |
|---|---:|---:|---:|---:|---:|---:|---:|
| fold_0 | 17 | 185 | 64 | 94 | 27 | 7.6 % | 0.3231 |
| fold_1 | 20 | 185 | 64 | 93 | 28 | 13.5 % | 0.4493 |
| fold_2 | 20 | 186 | 65 | 93 | 28 | 8.6 % | 0.3194 |
| fold_3 | 19 | 185 | 64 | 93 | 28 | 4.3 % | 0.2341 |
| fold_4 | 20 | 187 | 65 | 94 | 28 | 18.2 % | 0.5359 |
| **todos** | 96 | 928 | 322 | 467 | 139 | 10.5 % | **0.3817** |

La última fila es la línea base del protocolo: el macro-F1 sobre activates, no_relation, represses de todas sus predicciones fuera de pliegue.
Artículos con al menos un ejemplo de cada clase: activates 66; no_relation 60; represses 40.

## 6. Fuga por par y línea base de memorización

Aquí la etiqueta depende casi solo del par: un par que la base registra nunca sale como `no_relation`, y uno que no registra nunca sale como relación. Partir por PMID no impide que el mismo par caiga en train y en test. La línea base predice, para cada ejemplo, la etiqueta más frecuente de su par en train (o la clase mayoritaria si el par no está): el modelo vale lo que le gana.

| | dev | test |
|---|---:|---:|
| ejemplos | 110 | 101 |
| par ya visto en train, por nombres | 21.8 % | 4.0 % |
| par ya visto en train, por locus | 21.8 % | 4.0 % |
| acierto de la etiqueta del par, en los ya vistos | 1.0000 | 1.0000 |
| línea base: accuracy | 0.7727 | 0.5347 |
| línea base: macro-F1 | 0.7129 | 0.2323 |
| clase mayoritaria: macro-F1 | 0.2428 | 0.2323 |

Conjunto ciego de la trampa del signo (6 pares). Reservar sus oraciones no aparta sus pares: entran desde otras oraciones con la etiqueta que les da la base. **Para este modelo la trampa no es una evaluación externa.** Van solo los totales: por etiqueta dirían qué registra la base de esos pares, que tienen nombre público.

| ejemplos | train | dev | test |
|---|---:|---:|---:|
| con uno de sus 6 reguladores | 7 | 0 | 0 |
| con uno de sus 6 pares | 1 | 0 | 0 |

## 7. Entrenamiento del run 22

- Entorno: NVIDIA GeForce RTX 3070, 6768 MiB libres de 8192; Python 3.10.19, torch 2.6.0+cu124, transformers 4.44.2; sin red.
- Longitud en tokens: mediana 79, p95 142, máximo 343; truncados 0.
- Duración 1.8 min; épocas recorridas 8.0.

| | dev | test |
|---|---:|---:|
| macro-F1 | 0.5915 | 0.4817 |
| accuracy | 0.6909 | 0.6337 |
| precisión macro | 0.5983 | 0.4876 |
| exhaustividad macro | 0.5893 | 0.4952 |
| pérdida | 0.9964 | 1.4886 |
| ejemplos por segundo | 286.5 | 170.4 |

- Estas son las métricas del script del asesor. Su macro-F1 promedia sobre las etiquetas que aparecen en el test o en las predicciones (sin `labels=`): el conjunto cambia de una partición a otra. La cifra del protocolo, con las etiquetas fijas, está en 7.1 y en 8.

| época | pérdida train | pérdida dev | macro-F1 dev |
|---:|---:|---:|---:|
| 1.0 | 1.1999 | 0.8813 | 0.2652 |
| 2.0 | 0.9195 | 0.7446 | 0.4422 |
| 3.0 | 0.6529 | 0.7149 | 0.4801 |
| 4.0 | 0.4598 | 0.8016 | 0.5397 |
| 5.0 | 0.2563 | 0.8691 | 0.5788 |
| 6.0 | 0.1430 | 1.0421 | 0.5899 |
| 7.0 | 0.1290 | 0.9964 | 0.5915 |
| 8.0 | 0.0892 | 1.0272 | 0.5766 |

- Mejor macro-F1 de dev 0.5915, en el paso 315 de 360.
- El modelo quedó en `<runs>/run_22_lr3e-5_ep8_bs16_wu0.1`, con `label_mapping.json` junto a los pesos y el orden de etiquetas verificado; 2 checkpoints borrados.

### 7.1 El modelo desplegable sobre su test (descriptivo)

101 ejemplos de **4 artículos**: con tan pocos artículos esto no es una estimación del desempeño; la cifra es la de la sección 8. Sirve para comprobar el modelo tal como lo usará el flujo (`clasificar.py`, en CPU, con su `label_mapping.json`).

| clase | soporte | artículos | precisión | exhaustividad | F1 |
|---|---:|---:|---:|---:|---:|
| activates | 33 | — | 0.4884 | 0.6364 | 0.5526 |
| no_relation | 54 | — | 0.8077 | 0.7778 | 0.7925 |
| represses | 14 | — | 0.1667 | 0.0714 | 0.1000 |

- Macro-F1 sobre activates, no_relation, represses (fijas): 0.4817; accuracy 0.6337.
- Modelo menos línea base de memorización, en este test: +0.2494.
- Cotejo con el script: accuracy 0.6337 con clasificar.py y 0.6337 con el script (0.0 ejemplos de diferencia; se toleran 2).

Matriz de confusión (conteos):

| verdad \ predicción | activates | no_relation | represses |
|---|---:|---:|---:|
| activates | 21 | 9 | 3 |
| no_relation | 10 | 42 | 2 |
| represses | 12 | 1 | 1 |

## 8. Validación cruzada: la cifra del protocolo

5 pliegues por artículo × 3 semillas (42, 43, 44). Cada ejemplo es test en un solo pliegue: las predicciones fuera de pliegue de cada semilla cubren los 928 ejemplos de 96 artículos. Cada pliegue entrena con el 60.0 % de los artículos.

### 8.1 Cifra principal (pre-registrada)

- **Macro-F1** sobre activates, no_relation, represses (etiquetas fijas): **0.4853** de media entre semillas (sd 0.0250; por semilla 42 0.4565, 43 0.4975, 44 0.5019), IC95 [0.4417, 0.5221].
- Línea base de memorización (la etiqueta del par en el train de su pliegue): 0.3817, IC95 [0.3003, 0.4642]. Clase mayoritaria: 0.2232.
- **Modelo menos línea base: +0.1036, IC95 [0.0218, 0.1819]**; réplicas con diferencia ≤ 0: 0.0080.
- **Regla del protocolo** (supera si el límite inferior del IC95 de la diferencia es mayor que 0): **supera a la línea base**.
- Intervalos: bootstrap percentil por artículos, B = 2000, semilla 20261016, con los modelos fijos.

### 8.2 Por clase

| clase | soporte | artículos | precisión | exhaustividad | F1 | F1 línea base |
|---|---:|---:|---:|---:|---:|---:|
| activates | 322 | 66 | 0.4990 | 0.6035 | 0.5461 | 0.3185 |
| no_relation | 467 | 60 | 0.7611 | 0.7088 | 0.7338 | 0.7049 |
| represses | 139 | 40 | 0.2092 | 0.1559 | 0.1760 | 0.1216 |

Media de las semillas. «(<5)»: con menos de 5 artículos, el F1 de esa clase es ruido.

### 8.3 Matrices de confusión

Semilla 42:

| verdad \ predicción | activates | no_relation | represses |
|---|---:|---:|---:|
| activates | 191 | 92 | 39 |
| no_relation | 120 | 326 | 21 |
| represses | 104 | 21 | 14 |

Semilla 43:

| verdad \ predicción | activates | no_relation | represses |
|---|---:|---:|---:|
| activates | 192 | 66 | 64 |
| no_relation | 100 | 323 | 44 |
| represses | 81 | 29 | 29 |

Semilla 44:

| verdad \ predicción | activates | no_relation | represses |
|---|---:|---:|---:|
| activates | 200 | 79 | 43 |
| no_relation | 91 | 344 | 32 |
| represses | 92 | 25 | 22 |

### 8.4 Pares ya vistos en train y pares nuevos

¿Generaliza a relaciones que no vio? En los pares nuevos la línea base no puede recordar nada: ahí se ve lo que el modelo lee de la oración.

| | ejemplos | artículos | macro-F1 modelo | macro-F1 línea base |
|---|---:|---:|---:|---:|
| par ya visto | 97 | 32 | 0.5289 | 1.0000 |
| par nuevo | 831 | 93 | 0.4707 | 0.2308 |

### 8.5 Por pliegue y semilla

Métricas del script (regla del asesor, comparables con su barrido) y el macro-F1 con las etiquetas fijas.

| corrida | dev macro-F1 | test macro-F1 | test accuracy | macro-F1 fijo | cotejo |
|---|---:|---:|---:|---:|---|
| s42/fold_0 | 0.5156 | 0.4705 | 0.5405 | 0.4705 | ok |
| s42/fold_1 | 0.4663 | 0.4766 | 0.6541 | 0.4766 | ok |
| s42/fold_2 | 0.4588 | 0.3808 | 0.5430 | 0.3808 | ok |
| s42/fold_3 | 0.5530 | 0.4745 | 0.5622 | 0.4745 | ok |
| s42/fold_4 | 0.4721 | 0.4030 | 0.5615 | 0.4030 | ok |
| s43/fold_0 | 0.5405 | 0.5393 | 0.6324 | 0.5393 | ok |
| s43/fold_1 | 0.4715 | 0.5479 | 0.6216 | 0.5479 | ok |
| s43/fold_2 | 0.5437 | 0.4430 | 0.5430 | 0.4430 | ok |
| s43/fold_3 | 0.4701 | 0.4088 | 0.5622 | 0.4088 | ok |
| s43/fold_4 | 0.4770 | 0.4958 | 0.5722 | 0.4958 | ok |
| s44/fold_0 | 0.5134 | 0.5184 | 0.6054 | 0.5184 | ok |
| s44/fold_1 | 0.4171 | 0.4753 | 0.6270 | 0.4753 | ok |
| s44/fold_2 | 0.4740 | 0.4304 | 0.5645 | 0.4304 | ok |
| s44/fold_3 | 0.5192 | 0.4615 | 0.6054 | 0.4615 | ok |
| s44/fold_4 | 0.4946 | 0.5799 | 0.6471 | 0.5799 | ok |
| **media ± sd** | 0.4925 ± 0.0375 | 0.4737 ± 0.0563 | 0.5895 ± 0.0398 | 0.4737 ± 0.0563 | |

## 9. Cómo leer estas cifras

- **Es supervisión distante.** Un positivo es «este par, en una oración de un artículo que la base cita para esa relación»; la oración no tiene por qué afirmarla. Un negativo es «un par que la base no registra», no «un par sin relación». Las dos clases traen ruido, y el F1 se mide contra etiquetas con el mismo ruido.
- **La proporción de clases no es la del flujo.** Hay una `no_relation` por positivo, tomada de los artículos que la base cita. En el flujo el modelo clasifica todos los pares de la corrida 4, la mayoría de artículos que la base no cita y con muchos más pares sin relación: con la misma tasa de falsos positivos, la precisión de las tres clases de relación será menor que aquí.
- **El intervalo es por artículos y con los modelos fijos.** Dice cuánto cambiaría la cifra con otros artículos, no con otro entrenamiento (para eso está la desviación entre semillas) ni con otra partición.
- **Cada pliegue entrena con el 60.0 % de los artículos** (con K pliegues, uno es test y otro dev): la cifra es algo conservadora para el modelo desplegable, que entrena con el 80 %.
- **regulates no está en esta versión.** El modelo no la predice: las aristas de la red con signo «?» no van a venir de él.
- **No es comparable con el 0.87 de E. coli** (otro organismo, otro test, y aquel con fuga) **ni con el 44 %**, que es la precisión del bronce juzgada a mano sobre 50 candidatas, reservadas para recalcularla con este modelo.

## 10. Avisos y decisiones pendientes

- La corrida se desvía del protocolo: pesos_clase: el protocolo fija inversa y esta corrida usó ninguno.
