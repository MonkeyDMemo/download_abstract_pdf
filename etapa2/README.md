# Etapa 2 — reparticionar sin fuga y rehacer el barrido

Esta carpeta corrige un defecto metodológico del modelo de clasificación de
relaciones que vive en el servidor del asesor. No entrena aquí: prepara los
datos, verifica que la partición sirva, y lanza el barrido en Google Colab.

El contexto completo del modelo está en
[`../docs/ficha-modelo-bert.md`](../docs/ficha-modelo-bert.md).

## El problema

Los tres `entity_marked_*.jsonl` del servidor se partieron **a nivel de
ejemplo**. Como una misma ventana de texto genera un ejemplo por cada par
(factor, gen blanco) que contiene, la ventana cae en entrenamiento y en prueba
a la vez. Sobre el corpus hay **1 562 ejemplos pero solo 694 ventanas
distintas**: cada una se usa 2.3 veces en promedio.

Medido sobre los archivos originales:

| | dev | test |
|---|---|---|
| ejemplos cuya ventana ya está en train | 68.6 % | **73.9 %** |
| PMIDs compartidos con train | 65 de 68 | 61 de 64 |
| ejemplos cuyo par ya está en train | 89.7 % | 86.6 % |

Con eso, el macro-F1 reportado —0.9024 en dev, 0.8721 en test— mide sobre todo
memorización. **No invalida el trabajo: invalida el número.**

## Los archivos

| archivo | qué hace |
|---|---|
| `particionar.py` | reparte sin fuga y **se niega a escribir** si queda alguna |
| `barrido.py` | las 24 configuraciones del servidor, reanudable |
| `test_particionar.py` | 17 pruebas; la central verifica que el guardián puede fallar |
| `barrido_colab.ipynb` | el cuaderno |
| `para_colab/` | los seis archivos a subir a Drive (572 KB) |

```bash
python etapa2/particionar.py --por pmid --salida datos_etapa2/por_pmid
python -m unittest discover etapa2
```

## La decisión central: no se pueden pedir las dos cosas

Lo natural sería exigir que ni un artículo ni una relación se compartan entre
particiones. **Es imposible.** Al unir en un grafo cada artículo con cada par
que menciona, el corpus colapsa:

| agrupar por | grupos | grupo mayor | ¿sirve para 80/10/10? |
|---|---|---|---|
| solo PMID | 119 | 66 (4.2 %) | sí, pero deja colar ventanas repetidas |
| **PMID + ventana** | **108** | **105 (6.7 %)** | **sí — es la que se usa** |
| par + ventana | 141 | 241 (15.4 %) | solo con validación cruzada |
| PMID + par + ventana | 23 | 1391 (**89.1 %**) | no |

Hay que elegir, y las dos opciones responden preguntas distintas:

- **Por artículo** (`--por pmid`): ¿generaliza a artículos que no vio?
- **Por par** (`--por par --folds 5`): ¿generaliza a relaciones que no vio?

El corte por par importa menos de lo que parece: **176 de los 332 pares tienen
más de una etiqueta en el oro**, así que el modelo no puede memorizar
par→etiqueta ni queriendo. La fuga que envenena el número es la de la ventana.

## La partición que sale

```
parte          n  arts  activates   no_relation regulates   represses
train       1242   102   475  38.2%  390  31.4%  162  13.0%  215  17.3%
dev          163     9    59  36.2%   53  32.5%   24  14.7%   27  16.6%
test         157     8    59  37.6%   50  31.8%   21  13.4%   27  17.2%
TOTAL       1562   119   593  38.0%  493  31.6%  207  13.3%  269  17.2%
```

Queda en **1242 / 163 / 157** contra los 1249 / 156 / 157 originales, y con las
proporciones de clase a menos de un punto de las globales. La comparación es
manzana con manzana: mismo tamaño, mismo balance, lo único que cambia es la
fuga.

## Por qué el guardián mide con otra clave

Una versión anterior de `verificar()` medía la fuga con **las mismas funciones
que había usado para agrupar**. Como `repartir()` solo mueve grupos enteros,
eso daba cero por construcción: el `PARTICION RECHAZADA / exit 1` era código
muerto y cualquier defecto en la clave se autoconfirmaba como partición limpia.

Es exactamente el género de error que esta carpeta vino a corregir, así que no
podía repetirlo. Ahora hay dos canonizaciones distintas y deliberadamente
independientes:

- `ventana()` — quita los marcadores. **Agrupa.**
- `canonico()` — quita marcadores, puntuación y mayúsculas. **Verifica.**

Y `test_particionar.py` le pasa particiones deliberadamente sucias y afirma
que devuelve `False`, para que el guardián no vuelva a morirse en silencio.

Con la verificación independiente aparecieron dos cosas que la anterior no
podía ver:

- **12 ejemplos de test (7.6 %) tienen su ventana contenida en una de train**,
  uno con contención 1.00: el título de un artículo de prueba aparece en la
  bibliografía de uno de entrenamiento. Ningún criterio por PMID lo evita, y
  por eso se reporta como aviso y no como falla.
- **`regulates` en dev son 24 ejemplos pero de solo 3 artículos**, y 12 salen
  del mismo. El conteo de ejemplos engañaba; lo que da la incertidumbre real es
  de cuántos artículos independientes vienen.

## Lo que Colab impone

- **Fijar `transformers==4.44.2`.** El script del servidor usa
  `evaluation_strategy=`, removido en la 4.46, y la firma vieja de
  `compute_loss`. El cuaderno lo comprueba de verdad tras el `pip install`:
  sin eso, las 24 corridas fallan una por una y media hora después hay 24
  archivos `.error` y ni un resultado.
- **Los checkpoints van a `/content`, nunca a Drive.** Son ~433 MB por época.
  Se borran al terminar cada configuración, **falle o no**: doce fallos por
  falta de memoria llenaban el disco y tumbaban las que sí habrían cabido.
- **Cada resultado se escribe de forma atómica** (temporal más `os.replace`).
  El archivo de resultado es también la marca de «ya se hizo», así que uno
  truncado por una desconexión contaba como corrida buena.
- **Cada resultado lleva la huella de los datos.** Reusar `--resultados` con
  otra partición no salta las 24 corridas: se niega y lo dice.

`max_length` se queda en **512**, como el `.sh`. Bajarlo no acelera nada: el
script tokeniza sin relleno y el `DataCollatorWithPadding` rellena hasta el
más largo de cada lote, así que el costo ya es proporcional a la longitud
real. Lo único que hace `max_length` es marcar dónde se trunca.

## Un problema que la repartición no arregla

**`no_relation` no es una clase semántica: es un artefacto de qué mención se
marcó.** 485 de los 493 ejemplos (98.4 %) comparten ventana **y** par con otra
fila etiquetada como positiva. La única diferencia entre las dos es cuál de las
menciones lleva el marcador:

```
[no_relation]  ... placing the NanR , <e1>IHF</e1> and NagC binding sites
               closer to the <e2>fimB</e2> promoter enhances the ability of
               the regulators to activate fimB expression .

[activates]    ... placing the NanR , <e1>IHF</e1> and NagC binding sites
               closer to the fimB promoter enhances the ability of the
               regulators to activate <e2>fimB</e2> expression .
```

Misma frase, mismo par, mismo artículo. El modelo puede aprender la
diferencia —los marcadores están en la entrada, y el techo duro de exactitud
es 0.9962, muy por encima del 0.8854 reportado—, pero lo que aprende es **«¿se
marcó la mención pegada al verbo?»**, no «¿este texto afirma una relación?».

Y ahí está el problema real, que ninguna repartición corrige: **en producción
las negativas son otras.** Sobre *P. aeruginosa* se enumeran pares candidatos
con el diccionario de PAO1 y se pregunta si hay relación; las negativas de ahí
son pares que coocurren sin relación, no «par correcto, mención equivocada».
Es un desajuste entre entrenamiento y despliegue, y explicaría por qué los
umbrales de confianza (0.65 / 0.70 / 0.60) tuvieron que fijarse a mano.

Arreglarlo pide negativas construidas como las de inferencia: pares del mismo
párrafo sin relación anotada. Es trabajo de anotación, no de código.

## Lo que falta

1. **Correr el barrido.** Es lo inmediato y son un par de horas de T4.
2. **Varias semillas.** `--semillas 42,43,44` da la dispersión, que con 1242
   ejemplos es del orden de la señal que el barrido mide. El `.sh` usaba una.
3. **Un brazo de control**: correr la misma rejilla sobre una partición *a
   nivel de ejemplo* de las mismas 1 562 filas. Sin él, la diferencia contra
   0.8721 mezcla tres cosas —la fuga, que el test cambió de 64 artículos a 8,
   y que los hiperparámetros se reeligieron—. `particionar.py` todavía no lo
   produce.
4. **Una línea base barata** (mayoritaria, coocurrencia en la misma oración).
   Sin ella, un macro-F1 de 0.75 no se sabe si es bueno.
5. **El conjunto anotado de PAO1**, que sigue siendo el obstáculo de fondo.

## Los datos no están en el repositorio

`entity_marked_*.jsonl`, `ecoli_curated.tsv`, `bio_bert_re_finetune.py`,
`run_sweep_biobert.sh` y `summarize_sweep.py` vienen del servidor del asesor y
**no se versionan aquí**: son trabajo de otra persona y este repositorio tiene
remoto en GitHub. Están en el `.gitignore`.

Para reproducir, cópialos de `/home/user/pseudomonas-trn` según la tabla de
rutas de la ficha. `datos_etapa2/` tampoco se versiona: lo regenera
`particionar.py` de forma determinista con la semilla por omisión.
