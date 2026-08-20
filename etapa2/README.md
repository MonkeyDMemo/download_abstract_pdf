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
| `oro_pseudomonas.tsv` | **190 relaciones canónicas de *P. aeruginosa*** con su oración |
| `auditar_signo.py` | extrae las oraciones de los seis represores RND |
| `auditoria_signo.tsv` | 198 oraciones, 93 con signo conocido de antemano |

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
- **Fijar también `numpy<2` y `pandas==2.2.3`.** `datasets 2.20` usa
  `np.float_`, que numpy 2 eliminó, y el pandas 3 de la imagen de Colab exige
  numpy 2: fijar solo numpy deja dos paquetes que se contradicen e `import
  datasets` truena a media corrida. El muro de conflictos que escupe `pip` al
  bajar numpy (jax, cupy, opencv, rasterio) es ruido: son paquetes que el
  cuaderno nunca importa, y pip revisa el entorno entero, no lo que se instaló.
- **Las comprobaciones del cuaderno corren en un subproceso.** Leen lo que quedó
  en disco y no lo que quedó en memoria, así que no hay que reiniciar el entorno
  después del `pip`. Y ninguna construye un `TrainingArguments`: instanciarlo
  dispara la búsqueda de integraciones (wandb, mlflow, comet, neptune) y el
  arranque de CUDA, que en un entorno recién reinstalado se va varios minutos
  haciendo `stat()` sobre `sys.path` y parece colgado. `inspect.signature`
  responde la misma pregunta al instante.
- **Una prueba de humo antes del barrido**: el script de verdad sobre 40
  ejemplos, una época y ventanas de 128, dos minutos. Ejerce lo que la
  comprobación de versiones no alcanza a ver —una incompatibilidad de `torch`
  con `accelerate`, por ejemplo— y de paso deja BioBERT en la caché.
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

---

# El patrón de oro de *P. aeruginosa*

El problema A —la fuga— es sobre *E. coli*. Esta segunda parte ataca el otro,
que es el de la tesis: **el modelo infirió 789 aristas de *P. aeruginosa* y no
existía nada contra qué compararlas.**

## `oro_pseudomonas.tsv` — 190 relaciones canónicas

Seis lenguajes de dominio distintos —quorum sensing, bombas de expulsión,
factores sigma, biopelícula, hierro, dos componentes— produjeron las relaciones
que la literatura da por establecidas, y **se buscaron en los 918 textos
completos y los 2 354 resúmenes** de la etapa 1.

| subsistema | total | atestiguadas |
|---|---|---|
| Hierro y sideróforos | 41 | 39 |
| Factores sigma | 37 | 35 |
| Dos componentes y T3SS | 36 | 34 |
| Quorum sensing | 30 | 30 |
| Bombas RND | 29 | 27 |
| Biopelícula y c-di-GMP | 17 | 16 |
| | **190** | **181** |

**Verificación: 180 de las 181 oraciones existen literalmente** en un artículo
que la propia fila declara — 161 exactas y 19 por fragmento contiguo largo,
donde el desfase era tipográfico (guiones U+2010, sigmas griegas). **Cero
inventadas.** La única con problema, `PrrF→bfrB`, era un error de atribución:
la oración existe pero en el PMID 36036571, ya corregido.

### Lo que esto permite decir, y antes no

**El corpus sí contiene la evidencia.** Solo 9 relaciones canónicas faltan por
completo, y son casi todas autorregulación (`MexT→mexT`, `NalD→nalD`,
`AlgR→algR`). O sea: **casi cualquier arista canónica que el modelo no
recupere es fallo del modelo, no del corpus.**

### El denominador honesto son ~169, no 190

Hay que sacar del cómputo:

- Las **9 no atestiguadas** — el corpus no las contiene.
- Las **6 con `signo='regulates'`** — el corpus no resuelve el signo.
- Las **5 en disputa**, donde el corpus se contradice a sí mismo. La peor es
  `RhlR→rpoS`: dos artículos la afirman, uno dice explícitamente *«rpoS
  expression is not regulated by RhlR»*, y un cuarto invierte la flecha. Es de
  Latifi 1996 y la literatura posterior no la confirmó — y es justo el tipo de
  arista que un modelo entrenado en literatura vieja tiene alta probabilidad
  de emitir.

### Dos sesgos que hay que declarar

**El corpus tira a virulencia y biopelícula.** `RpoN→glnA`, la arista de
sigma-54 más canónica que existe, se sostiene en un solo artículo. No conviene
medir regulones metabólicos con esto.

**La granularidad limita.** El corpus usa `algD` como proxy del operón de doce
genes y casi nunca nombra `alg8`, `alg44` o `algK`. Aristas hacia esos genes no
son recuperables aunque sean ciertas.

### El universo de evaluación: texto completo **y** resúmenes

De los 312 artículos citados, 243 tienen texto completo. Pero **24 relaciones
tienen su oración de evidencia solo en un resumen, y 12 de esas 24 son de
hierro**: la cascada clásica de pioverdina, cuya evidencia primaria es de
1996-2003. Los XML de PMC son sesgadamente recientes y dan por sabida esa
cascada sin repetir el experimento.

Midiendo solo sobre texto completo, el subsistema de hierro saldría
artificialmente mal y las bombas perderían sus autorregulaciones. Por eso el
universo son las dos cosas.

## `auditar_signo.py` — donde va a fallar, medido de antemano

```bash
python etapa2/auditar_signo.py     # -> etapa2/auditoria_signo.tsv
```

MexR, NalC, NalD, NfxB, MexZ y MexL reprimen su bomba: la literatura no lo
discute. Pero casi toda la evidencia está escrita desde el fenotipo del
mutante, y ahí está la trampa:

> *«mutations in nfxB lead to overexpression of MexCD-OprJ»*
> *«nalC mutants showing elevated PA3720-armR expression»*

Un extractor lee eso y saca **activates** cuando la relación es **represses**.

El script extrae del corpus las oraciones de esos seis pares y las clasifica
por redacción. Resultado: **198 oraciones, de las cuales 93 son evaluables**
—afirman la relación— con signo conocido `represses`, y **24 de esas 93 están
escritas desde el fenotipo del mutante**.

Es un conjunto de prueba con la respuesta puesta de antemano, sobre el
subconjunto donde el modelo tiene más probabilidad de equivocarse. **Una
oración evaluable que el clasificador etiquete `activates` es un error
confirmado**, sin anotar nada.

Las otras 105 no son basura: son co-menciones sin relación afirmada, o sea
**negativas realistas del mismo dominio**. Es justo el tipo de negativa que le
falta al entrenamiento, donde el 98 % de los `no_relation` son «marcaste la
mención equivocada».

### Tres cosas que se aprendieron leyendo lo que salía

**La autorregulación quedó fuera.** Una oración que nombra `nalD` dos veces
—una como `ΔnalD`— no afirma que NalD se regule a sí mismo. Sin ese corte,
`NalD→nalD` salía con 40 oraciones para un par que el patrón de oro da por no
atestiguado, y tenía razón el patrón.

**Solo las que afirman la relación son evaluables.** En una co-mención el
modelo no se equivoca al no ver represión, porque no hay ninguna escrita. La
etiqueta correcta ahí es `no_relation`.

**MexL no es solo represor.** Reprime `mexJK` pero **activa** los genes de
fenazina, y el corpus lo dice con todas sus letras. El signo conocido vale para
la bomba, no para el regulador entero.
