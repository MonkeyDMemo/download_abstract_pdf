# Protocolo de evaluación: BioBERT sobre la base curada, versión 1

Este documento fija **antes de entrenar** qué se mide, cómo y con qué regla se
decide. Se commitea antes del tramo 2. `RESULTADOS.md` muestra el commit de
este archivo y si es anterior al inicio de la corrida. Lo que la corrida haga
distinto de aquí aparece en el informe como desviación. Lo que se cambie
después de commitearlo va en la sección 12, con fecha y motivo.

La razón es la norma del proyecto: «la regla queda escrita antes de mirar la
tabla». Con 96 artículos, cualquier decisión tomada después de ver una cifra
(otra semilla, otra métrica, otro corte) puede mover el resultado más que el
modelo (Nosek et al. 2018).

## 1. Qué se estima

Si la receta del run 22, entrenada con la base curada, **clasifica la relación
regulador → blanco en artículos que no vio** mejor que recordar la etiqueta
del par.

La pregunta es contra recordar, y no contra el azar, por cómo se construyen
los datos. Por supervisión distante, un par registrado en la base nunca sale
como `no_relation` y uno que no lo está nunca sale como relación. Un modelo
que solo memorizara pares tendría un F1 alto en los artículos que comparten
pares con el entrenamiento. La pregunta útil para la red es si lee la oración.

## 2. Datos

- **Origen:** la base curada v2 del laboratorio, que se lee en el servidor
  del asesor y nunca sale de ahí. Los ejemplos salen por supervisión distante
  (`grn_verificacion/entrenamiento.py`), con la conciliación de PLAN.md 2.4:
  309 PMIDs y 1 DOI.
- **Reservas:** las 50 candidatas de la muestra de juicios (46 PMIDs, 232
  oraciones) quedan fuera del entrenamiento y de la evaluación. Son las de la
  evaluación externa de la sección 10.
- **Clases de esta versión:** `activates`, `no_relation` y `represses`.
  `regulates` queda fuera: tiene 6 ejemplos de 2 artículos, y ninguno cae en
  dev ni en test de la partición única. Una clase así no se puede aprender ni
  medir. Se quita antes de particionar (`--excluir-etiqueta`, por omisión
  `regulates`). El modelo conserva las cuatro salidas de `label_mapping.json`,
  así que el flujo no cambia, pero no aprende `regulates`.
  - El script pondera la pérdida por la inversa de la frecuencia. A una clase
    sin ejemplos le da el peso mayor, pero `CrossEntropyLoss` pondera por la
    clase verdadera de cada ejemplo: ese peso nunca entra en la pérdida, y la
    proporción entre las otras tres no cambia.

**Conteos del tramo 1 bis**, del `RESULTADOS.md` de la corrida del 16-oct-2026
con el commit `6f924e3318`. La base coincide con PLAN.md 2.4 en los 14
conteos, sin `--aceptar-base-distinta`.

| clase | ejemplos | artículos con la clase |
|---|---:|---:|
| activates | 322 | 66 |
| no_relation | 467 | 60 |
| represses | 139 | 40 |
| **total** | **928** | **96** |

Fuera quedaron los 6 ejemplos de `regulates`, de 2 artículos.

Pliegues (`particionar.py --folds 5 --por pmid --semilla 20260819`), con
la línea base de memorización de cada uno (sección 6):

| pliegue (test) | artículos | ejemplos | activates | no_relation | represses | par ya visto en train | macro-F1 línea base |
|---|---:|---:|---:|---:|---:|---:|---:|
| fold_0 | 17 | 185 | 64 | 94 | 27 | 7.6 % | 0.3231 |
| fold_1 | 20 | 185 | 64 | 93 | 28 | 13.5 % | 0.4493 |
| fold_2 | 20 | 186 | 65 | 93 | 28 | 8.6 % | 0.3194 |
| fold_3 | 19 | 185 | 64 | 93 | 28 | 4.3 % | 0.2341 |
| fold_4 | 20 | 187 | 65 | 94 | 28 | 18.2 % | 0.5359 |
| **todos** | 96 | 928 | 322 | 467 | 139 | 10.5 % | **0.3817** |

La partición es determinista con su semilla: el tramo 2 la rehace igual. Si
cambiara, la evaluación no daría la línea base de la última fila y se
detendría.

## 3. Receta (fija)

El run 22 del barrido del asesor, sin tocar su script
(`bio_bert_re_finetune.py`, por `etapa2/barrido.py --solo 22`):

| parámetro | valor |
|---|---|
| modelo base | `dmis-lab/biobert-base-cased-v1.1` |
| tasa de aprendizaje | 3e-5 |
| épocas | 8, con paro temprano (paciencia 2) |
| lote | 16 |
| calentamiento | 0.1 |
| weight decay | 0.01 |
| max_length | 512 |
| pesos de clase | inversa de la frecuencia en train |
| mejor checkpoint | el de mayor macro-F1 en dev (regla del script) |

No se ajusta ningún hiperparámetro con estos datos. La receta es la del barrido
de *E. coli*.

## 4. Modelos

- **Validación cruzada, la que se evalúa.** 5 pliegues por artículo. En el
  pliegue *i*, test es `fold_i`, dev es `fold_(i+1)` (solo para el paro
  temprano y el mejor checkpoint) y train son los otros tres, el 60 % de los
  artículos. Cada pliegue se entrena con las semillas 42, 43 y 44: son 15
  modelos. Cada uno predice su test y se borra.
- **El modelo desplegable.** Partición única por PMID 80/10/10, semilla 42,
  fijada de antemano: no se elige la mejor semilla. Es el que usará el flujo.
  Su test tiene unos pocos artículos y es descriptivo (sección 8).

Las predicciones salen de `etapa2/clasificar.py`, en CPU, la misma vía de
inferencia que usa el flujo. Cada predicción es el argmax de las cuatro
probabilidades, sin umbrales.

## 5. Métrica primaria

**Macro-F1 sobre el conjunto fijo {activates, no_relation, represses}**:

1. Para cada semilla, se juntan las predicciones de test de los 5 pliegues.
   Cada ejemplo aparece una vez, predicho por el modelo que no vio su artículo.
2. Sobre esa matriz de confusión se calcula el F1 de cada una de las tres
   clases y se promedia sin ponderar. Una clase sin predichos ni soporte vale
   0 (`zero_division=0`). Una predicción de `regulates` cuenta como error de
   la clase verdadera.
3. La cifra es la media de las tres semillas, con su desviación estándar.

**Intervalo al 95 %:** bootstrap percentil por conglomerados. Se remuestrean
artículos con reemplazo, tantos como hay, y en cada réplica se recalcula el
paso 2 por semilla y su media. Son B = 2000 réplicas con semilla 20261016 y
los modelos fijos. Los ejemplos de un artículo no son independientes:
remuestrearlos sueltos daría un intervalo demasiado angosto (Field y Welsh
2007).

Por qué el conjunto fijo y no la regla del script: el `compute_metrics` del
script promedia sobre las clases presentes en la verdad o en la predicción.
Ese conjunto cambia de un pliegue a otro, y dos cifras dejan de promediar lo
mismo. Un ejemplo: con verdad (a, a, n) y predicción (a, n, n), el script da
0.667 y el conjunto fijo {a, n, r} da 0.444.

## 6. Comparación primaria y regla de decisión

**Línea base de memorización.** Para cada ejemplo de test se toma la etiqueta
más frecuente de su par en el train de su pliegue. El par se compara por locus
(PA####): así un operón y su gen cuentan como el mismo par. Si el par no
estaba en ese train, se toma la clase mayoritaria del train. No lee la
oración.

La línea base no depende del modelo, así que ya se conoce: **macro-F1
0.3817** sobre las predicciones fuera de pliegue (sección 2). El
orquestador la recalcula en la evaluación y se detiene si no da lo mismo.

**Diferencia pareada:** macro-F1 del modelo (media de semillas) menos
macro-F1 de la línea base. Se calcula en las mismas réplicas del bootstrap
(Berg-Kirkpatrick et al. 2012).

**Regla:** el modelo **supera a la línea base** si el límite inferior del
IC95 de la diferencia es mayor que 0. Si no, el informe dice «no se demostró
ventaja sobre recordar el par». Esa es la frase que va a la ficha y al asesor,
sin matices añadidos después.

## 7. Métricas secundarias

Se reportan todas, y ninguna sirve para declarar que el modelo supera a la
línea base:

- Precisión, exhaustividad y F1 por clase, con su soporte en ejemplos y en
  artículos. Una clase con menos de 5 artículos se marca: su F1 es ruido.
- La matriz de confusión de cada semilla.
- Los estratos «par ya visto en train» y «par nuevo», con el macro-F1 del
  modelo y de la línea base en cada uno. En los pares nuevos la línea base no
  puede recordar nada.
- La línea base de clase mayoritaria.
- Por semilla, el mínimo y el máximo además de la media y la desviación
  (Reimers y Gurevych 2017; Dodge et al. 2020).
- Por pliegue y semilla, las métricas del script con su regla, para poder
  compararlas con el barrido del asesor.
- Los modelos que predicen una sola clase, marcados. Entran como están.

## 8. Lo que no es una estimación

- **El test de la partición única.** Son unos pocos artículos. Se usa para
  comprobar el modelo desplegable tal como lo usará el flujo, y para el
  cotejo entre `clasificar.py` y el script.
- **Las cifras de dev.** Con ellas se eligió el checkpoint.
- **El macro-F1 con la regla del script.**
- **Cualquier cifra de `regulates`.**
- **La comparación con el 0.87 de *E. coli*** (otro organismo, otro test, y
  aquel con fuga) **o con el 44 %** (otra métrica, sección 10).

## 9. Reglas de ejecución

1. **Una corrida:**
   `reentrenar correr --folds 5 --semillas 42,43,44 --desprender`, con la
   exclusión por omisión y el código commiteado.
2. **No se relanza por un mal resultado.** Después de ver una cifra no se
   cambia nada de lo de este documento: semillas, pliegues, receta, métrica o
   regla. Todo cambio va como enmienda (sección 12) y la corrida que lo use
   se reporta aparte.
3. **Un fallo técnico se relanza con el mismo comando.** Por ejemplo memoria
   de la GPU, un corte del servidor, el tope de 4 h o la GPU ocupada. El
   orquestador retoma sin rehacer lo terminado, con las mismas semillas. Se
   anota en la bitácora.
4. Si un pliegue no puede terminar por razones técnicas, no hay cifra
   primaria. No se calcula una con los pliegues que sí terminaron.
5. **Si el cotejo falla en el modelo desplegable, la corrida se detiene.** El
   cotejo compara la accuracy de `clasificar.py` con la del script, con
   tolerancia de 2 ejemplos. Si falla, la unión entre predicciones y
   ejemplos, o el orden de las etiquetas, está mal. Se corrige como enmienda
   antes de leer ninguna cifra. En un pliegue es un aviso del informe.
6. Mientras corre, solo se mira el avance (`reentrenar estado`), no las
   métricas.

## 10. Evaluación externa (pendiente del asesor)

Las métricas de las secciones 5 a 7 se miden contra etiquetas de supervisión
distante, que traen ruido. No equivalen a la exactitud del modelo (Mintz et
al. 2009; Riedel et al. 2010). La medición contra juicio humano es el 44 %:
la precisión del bronce juzgada a mano sobre 50 candidatas, que están
reservadas desde el 8-oct. Recalcularla con este modelo (`flujo.py --modelo`)
da una precisión con n = 50 y su intervalo de Wilson. Eso requiere el visto
bueno del asesor: las salidas del modelo sobre el corpus público no salen del
servidor sin él.

## 11. Limitaciones

- **Supervisión distante.** Un positivo es «este par, en una oración de un
  artículo que la base cita para esa relación», y la oración no tiene por qué
  afirmarla. Un negativo es «un par que la base no registra», no «un par sin
  relación».
- **La proporción de clases no es la del flujo.** Aquí hay una `no_relation`
  por positivo. En el flujo hay muchos más pares sin relación: con la misma
  tasa de falsos positivos, la precisión será menor.
- **Pocos artículos.** El intervalo será ancho, y eso es parte del resultado
  (Varoquaux 2018).
- **El intervalo es con los modelos fijos.** Dice cuánto cambiaría la cifra
  con otros artículos. La variación por entrenamiento solo la recogen, en
  parte, las tres semillas.
- **Los pliegues entrenan con el 60 %** de los artículos y el modelo
  desplegable con el 80 %. La cifra es algo conservadora para el desplegable.
- **Sin `regulates`.** Las aristas con signo «?» de la red no vendrán de este
  modelo.

## 12. Enmiendas

Ninguna. Cada enmienda lleva fecha, qué cambia, por qué y si es anterior o
posterior a ver alguna cifra del tramo 2.

## 13. Referencias

- ACL Rolling Review. *Responsible NLP Research Checklist*.
- Berg-Kirkpatrick, T., Burkett, D. y Klein, D. (2012). An empirical
  investigation of statistical significance in NLP. *EMNLP-CoNLL 2012*.
- Dodge, J. et al. (2020). Fine-tuning pretrained language models: weight
  initializations, data orders, and early stopping. arXiv:2002.06305.
- Field, C. A. y Welsh, A. H. (2007). Bootstrapping clustered data. *Journal
  of the Royal Statistical Society B*, 69(3), 369–390.
- Gebru, T. et al. (2021). Datasheets for datasets. *Communications of the
  ACM*, 64(12), 86–92.
- Mintz, M., Bills, S., Snow, R. y Jurafsky, D. (2009). Distant supervision
  for relation extraction without labeled data. *ACL-IJCNLP 2009*.
- Mitchell, M. et al. (2019). Model cards for model reporting. *FAT\* 2019*.
- Mosbach, M., Andriushchenko, M. y Klakow, D. (2021). On the stability of
  fine-tuning BERT: misconceptions, explanations, and strong baselines.
  *ICLR 2021*.
- Nosek, B. A. et al. (2018). The preregistration revolution. *PNAS*,
  115(11), 2600–2606.
- Reimers, N. y Gurevych, I. (2017). Reporting score distributions makes a
  difference: performance study of LSTM-networks for sequence tagging.
  *EMNLP 2017*.
- Riedel, S., Yao, L. y McCallum, A. (2010). Modeling relations and their
  mentions without labeled text. *ECML PKDD 2010*.
- Roberts, D. R. et al. (2017). Cross-validation strategies for data with
  temporal, spatial, hierarchical, or phylogenetic structure. *Ecography*,
  40(8), 913–929.
- Varoquaux, G. (2018). Cross-validation failure: small sample sizes lead to
  large error bars. *NeuroImage*, 180, 68–77.
- Wilson, E. B. (1927). Probable inference, the law of succession, and
  statistical inference. *JASA*, 22(158), 209–212.
