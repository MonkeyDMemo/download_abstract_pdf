# Bitácora y plan

Qué se hizo antes, qué se hizo hoy, y qué sigue. Escrito el 27 de agosto de
2026, después del comité.

Para el detalle técnico de cada punto está
[`informe-seminario-1.md`](informe-seminario-1.md); esto es el mapa.

---

## Lo que se hizo antes

### Fase 0 — el ETL (17 y 18 de agosto)

Descarga de literatura de PubMed con estado persistente. Lo central del diseño
es que **no vuelve a descargar lo que ya tiene**: los documentos se guardan una
vez y se ligan a cada consulta que los trajo. Sobre seis consultas, la suma
ingenua habría sido 5 331 descargas; se hicieron 2 361.

| | |
|---|---|
| Artículos | 2 361 |
| Con resumen | 2 354 |
| Con texto completo (JATS de PMC) | 918 |
| Pruebas | 349, ninguna toca la red |

Se opera por CLI o por un tablero local. Solo biblioteca estándar de Python.

### Etapa 2 — el modelo, y el defecto que tenía (19 y 20 de agosto)

El asesor tenía un BioBERT ajustado para clasificar relaciones, entrenado en
*E. coli* y con macro-F1 reportado de 0.8721.

**Ese número medía memorización.** El corpus de entrenamiento tiene 1 562
ejemplos pero solo **694 ventanas de texto distintas**: cada ventana genera un
ejemplo por cada par de genes que contiene. Al partir a nivel de ejemplo, la
misma ventana quedaba en entrenamiento y en prueba. El 73.9 % de la prueba ya se
había visto.

Lo que se construyó:

- **`particionar.py`** — reparte agrupando por artículo más ventana, y marca la
  partición como rechazada si queda fuga. Sale en 1242/163/157, casi igual que
  la original, así que la comparación es directa.
- **El barrido rehecho**, 24 de 24 corridas en Colab. La misma configuración del
  servidor pasa de **0.8721 a 0.9335** sin contaminación. *Sube, no baja*: los
  hiperparámetros estaban bien; lo que estaba mal era la medición.
- **El patrón de oro** — 190 relaciones canónicas de *P. aeruginosa*, buscadas
  en nuestro corpus. 181 atestiguadas con oración textual, y 180 de esas
  verificadas una por una: existen literalmente.
- **La auditoría de signo** — 198 oraciones sobre los seis represores de bombas
  RND, de las cuales **93 tienen la respuesta conocida de antemano**.
- **El diccionario de PAO1** — 5 642 genes desde RefSeq, KEGG y UniProt, 572
  marcados como factor de transcripción. Cubre 43 de los 55 factores del patrón
  con fuentes públicas.
- **El programa local de inferencia** — del corpus salen pares, el clasificador
  les pone signo, se arma la red y se compara. Sin depender del servidor.

También quedó documentado, con el ataque que lo demuestra, que **el programa
detectaba al tramposo torpe y no al cuidadoso**: cinco formas de inflar una
cifra que seguían pasando.

---

## Lo que se hizo hoy (27 de agosto)

### El programa corrió con el modelo real, por primera vez

Lo que faltaba no era código: era `torch`, que no estaba instalado. Se resolvió
con un entorno virtual —el Python de la Microsoft Store deja la ruta en 138
caracteres y la instalación de torch muere con `WinError 206`— y **no hizo falta
máquina más grande**: 65 223 pares en **69.7 minutos** de CPU en la laptop.

```
2 361 documentos
  -> 65 223 pares candidatos
  -> 43 751 pasan umbrales
  ->  8 653 aristas · 376 TF · 1 744 blancos · 1 379 artículos
```

Para comparar: el servidor había inferido 789 aristas sobre 130 PDFs.

### Los dos números de signo, y por qué no se contradicen

| medida | valor | su línea base |
|---|---|---|
| Exhaustividad (patrón de oro) | 95.1 % | azar **99.4 %** — la cifra no mide el modelo |
| Acierto de signo agregado | 86.5 % | clase mayoritaria 76.9 % (**+9.6 pp**) |
| **Acierto de signo por oración** | **36.6 %** | sin información 17.1 % |
| ...solo fenotipo del mutante | **8.3 % (2 de 24)** | 14 errores son inversión de signo |

El modelo se inclina hacia `activates`. El patrón de oro es 80 activaciones de
104, así que ahí el sesgo se parece a acertar; la auditoría es toda represiones
y no se lo permite. **La auditoría se construyó para que el 86.5 % no se pudiera
citar solo, y funcionó.**

### El reparto de clases cambia al cambiar de especie

`regulates` pasa del 13.3 % en entrenamiento al **43.1 %** en inferencia: el
modelo se refugia en la clase sin signo. Y `no_relation` cae del 31.6 % al
14.7 %. Las dos cosas son medibles **sin una sola etiqueta**, y son la
dificultad de la transferencia entre especies hecha número.

### Dos guardianes, puestos antes de la cifra que protegen

De las cinco formas de inflar una cifra, las dos que se podían cometer por
descuido quedaron cerradas:

- **La cadena** (`procedencia.py`): `red.py` sella el sha256 de sus entradas y
  su salida, y las evaluaciones se niegan si no coincide. Antes, la misma red
  publicaba 80.6 % o 100.0 % según qué archivo se le pusiera al lado.
- **La cobertura del oro**: el indicador anterior *bajaba* al contaminar,
  porque era un cociente cuyo denominador crecía. El nuevo mide contra un
  conjunto fijo: honesto 0.619, contaminado 1.000.

**El primero se estrenó atrapando un error mío** —`red.py` sellaba un archivo
que aún no estaba en su sitio— y no distinguió de quién era la culpa, que es lo
que se le pedía.

---

## Lo que pidió el comité

| lo que pidieron | qué significa en concreto |
|---|---|
| Comparar contra lo que se tiene | Referencias externas y líneas base |
| Qué tan bueno es el score y si sirve | Metodología de evaluación |
| Cuántos errores comete y cuántos no | **Precisión y exhaustividad** |
| Buscar en PubMed Central, que hay PDFs | Ampliar el corpus |
| Generar la red para tomar decisiones | El entregable para el laboratorio |

### Dos cosas que se descubrieron al preparar la respuesta

**1. Contra una referencia externa, la exhaustividad es otra.** Medida contra
`collectf_pao1.tsv` —333 pares con sitio de unión medido experimentalmente,
curados por CollecTF y que no construimos nosotros— la recuperación es del
**37.8 %**, frente al 95.1 % contra nuestro propio patrón.

Se corrió el 27 de agosto con `evaluar_collectf()`, que ya existía en el
repositorio y nunca se había usado. **Y el resultado explica la diferencia**:
está desarrollado en la sección de más abajo, porque no es un número sino un
mecanismo.

**2. La precisión no se puede sacar del patrón de oro, y está bien que así
sea.** `evaluar_oro.py` prohíbe calcularla, con esta razón escrita en el código:

> El patrón de oro cubre 6 subsistemas con 190 relaciones. Una arista fuera de
> esos subsistemas no está mal: simplemente no está en la lista. Calcular
> precisión contra el oro contaría como falso positivo cada arista correcta que
> el oro no cubre, y el número sería una calumnia contra el pipeline, no una
> medición.

**La forma válida es muestrear la salida y juzgarla a mano.** Es lo estándar en
extracción de información cuando la referencia no es exhaustiva.

---

## La referencia externa: CollecTF, y por qué la exhaustividad depende del tipo de experimento

Es la respuesta a lo que el comité pidió con «comparar contra lo que se tiene».

`etapa2/collectf_pao1.tsv` son **333 pares con sitio de unión medido
experimentalmente**, curados por CollecTF a partir de artículos de unión
proteína-DNA. **No los construimos nosotros y no pasaron por nuestro corpus**,
que es justo lo que les da valor: el patrón de oro propio se armó quedándose con
las relaciones que el corpus atestigua, así que por diseño contiene lo que el
pipeline puede encontrar.

### El primer número, y por qué no es el que hay que citar

| referencia | exhaustividad |
|---|---|
| Patrón de oro propio (190 relaciones) | 95.1 % |
| **CollecTF (333 pares, externo)** | **37.8 %** (126 de 333) |

La caída era esperable por el sesgo de construcción. Lo que **no** era esperable
es lo siguiente.

### El pipeline no está repitiendo lo que se le enseñó

CollecTF se evalúa partido en dos: los factores que nuestro patrón de oro
menciona, y los que no.

| grupo | pares | exhaustividad |
|---|---|---|
| TFs que el patrón de oro cubre | 271 | 37.6 % |
| **TFs que el patrón de oro nunca menciona** | 62 | **37.1 %** |

**Son indistinguibles.** Si el pipeline solo encontrara aquello a lo que se le
apuntó, el segundo número se desplomaría. No lo hace: recupera relaciones de 12
factores que nadie le enseñó, al mismo ritmo que las de los 18 conocidos.

Ese corte estaba puesto en `evaluar_collectf()` desde antes, precisamente para
detectar circularidad. Detectó lo contrario, que es la buena noticia.

### Dónde se pierden las que no recupera

| qué pasó | pares | |
|---|---|---|
| Recuperada en la red | 126 | 38 % |
| Fue candidato pero no llegó a arista | 19 | 6 % |
| **El artículo está, pero el par nunca fue candidato** | **182** | **55 %** |
| El artículo no está en el corpus | 6 | 2 % |

**El 55 % de las pérdidas no son del modelo: son de la extracción de
candidatos.** El par nunca llegó a proponerse, así que el clasificador jamás lo
vio. Y afinando un nivel más sobre esos 182:

| | pares | |
|---|---|---|
| **El gen blanco no se nombra en el artículo** | **162** | 89 % |
| Los dos se nombran, pero nunca en la misma oración | 19 | 10 % |
| Ninguno aparece | 1 | 1 % |

### La explicación, y es limpia

El tipo de experimento lo dice todo:

| grupo | técnicas dominantes |
|---|---|
| Recuperadas | EMSA 21 %, reportero β-gal 14 %, mutagénesis dirigida 11 %, huella de DNAsa 8 % |
| Nunca candidatas | **ChIP-Seq 26 % + RNA-Seq 26 %** |

Las relaciones que el pipeline recupera vienen de **experimentos dirigidos a un
gen**: un artículo, uno o pocos blancos, discutidos en prosa. Las que pierde
vienen de **experimentos de genoma completo**, cuyos cientos de blancos se
publican en tablas suplementarias que nuestro corpus no contiene.

**Eso no es un fallo del modelo: es una propiedad de la minería de texto.**
Ningún clasificador recupera un gen que el artículo no nombra.

### El número que sí hay que citar

Descontando lo que no está en el texto —162 blancos no nombrados y 6 artículos
ausentes—, quedan **164 pares recuperables de prosa**, de los que el pipeline
recupera **126: el 76.8 %**.

| medida | valor | qué dice |
|---|---|---|
| Exhaustividad bruta contra CollecTF | 37.8 % | mezcla dos cosas distintas |
| **Sobre lo que el texto sí afirma** | **76.8 %** | lo que el sistema puede hacer |
| Sobre TFs nunca vistos en el oro | 37.1 % | no hay circularidad |

Las dos cifras hay que darlas juntas. La primera sola subestima al sistema; la
segunda sola esconde que **la mitad de la regulación conocida de PAO1 no está en
prosa y no se puede minar de texto**, que es un límite del enfoque y conviene
decirlo antes de que lo pregunten.

---

## La corrección del diccionario no movió ninguna métrica, y eso es el hallazgo

Al quitar `folD`, `hemE`, `pilI` y `minD` —los cuatro genes que emparejaban con
palabras inglesas— la cadena se volvió a correr entera.

| | antes | después |
|---|---|---|
| pares candidatos | 65 223 | 63 791 |
| aristas | 8 653 | **8 488** |
| entregable (estrato A) | 945 | **897** |
| exhaustividad contra el oro | 95.1 % | 95.1 % |
| acierto de signo agregado | 86.5 % | 86.5 % |
| acierto de signo por oración | 36.6 % | 36.6 % |

**189 aristas desaparecieron y el 100 % de ellas llevaba una de las cuatro
palabras.** Cero daño colateral: ninguna arista legítima se perdió.

**Y ninguna métrica se movió ni una décima.** No es una decepción: es la
demostración de por qué hacía falta medir precisión por muestreo.

El patrón de oro cubre 190 relaciones de 6 subsistemas. La auditoría de signo,
93 oraciones de 6 represores. **Ninguna de las dos contiene una sola arista de
`folD`, `hemE` o `pilI`**, así que 189 falsos positivos podían entrar y salir de
la red sin que ninguna cifra lo notara.

Esa es la respuesta concreta a la pregunta del comité sobre cuántos errores
comete el sistema: **las referencias miden lo que cubren, y no ven los errores
que caen fuera.** Solo el muestreo de la salida los ve, porque no parte de una
lista de lo que debería haber sino de lo que hay.

## Línea base: un LLM sin ajuste fino contra el BioBERT ajustado

Sobre las mismas 93 oraciones de la auditoría, con las 105 no evaluables
mezcladas como distractores y sin acceso a las respuestas:

| | BioBERT ajustado | LLM sin ajuste |
|---|---|---|
| las 93 evaluables | 36.6 % | **91.4 %** |
| redacción directa | 46.4 % | 91.3 % |
| **fenotipo del mutante** | **8.3 %** (2/24) | **91.7 %** (22/24) |

Contra la línea base sin información, p = 1.5 × 10⁻⁵⁵.

**El control que impide leerlo mal:** en las 105 co-menciones sin relación
afirmada el LLM reparte `regulates` 45, `no_relation` 42, `represses` 18. No
está contestando una sola clase.

**Y una objeción propia, medida y descartada.** El primer prompt le decía
explícitamente que el fenotipo del mutante invierte el signo —o sea, le
enseñaba el truco que BioBERT falla—. Se repitió con un prompt neutro, sin esa
regla ni la de la voz pasiva: **da exactamente lo mismo, y los dos difieren en 0
de las 93.** La ventaja no venía de la pista.

### Lo que esto cambia, y lo que no

No dice que el ajuste fino sea inútil: dice que **para resolver el signo en una
especie distinta de aquella en que se entrenó, un modelo general sin ajustar lo
hace mejor**. Encaja con todo lo demás medido: el `no_relation` aprendido es un
artefacto de marcado, y el reparto de clases se deforma al cambiar de especie.

Tres límites que van con el número. Son 93 oraciones de **un solo subsistema** y
todas de la misma clase: es un conjunto difícil a propósito, no representativo.
El costo a escala es otro orden de magnitud —63 791 pares que BioBERT hace en 72
minutos de CPU local—. Y el LLM evaluado es de la misma familia que el sistema
que preparó el conjunto, aunque los agentes clasificaron a ciegas.

**Esto convierte la cascada de decisión de idea en respuesta**, pero al revés de
como se dibujó: no es «el LLM como último recurso caro», sino «lo barato resuelve
el volumen y el LLM entra donde lo barato no es de fiar». Ahora hay con qué
decidir dónde poner esa frontera en vez de suponerla.

---

## La primera pasada de juicio, y lo que insinúa

Las 250 aristas de la muestra se juzgaron primero de forma automática, para que
la persona empiece por donde hay dudas en vez de por la fila 001. **No es la
medición** —esa la da la columna que llene la persona— pero lo que insinúa es lo
bastante fuerte para dejarlo escrito.

| estrato | juzgadas | «correctas» según la primera pasada |
|---|---|---|
| **A — el entregable** | 120 | **31 %** |
| B | 65 | 12 % |
| C | 65 | 18 % |

**160 de los 250 veredictos son `no`**: la evidencia mostrada no afirma ninguna
relación regulatoria.

### El modo de fallo es uno solo, y es mecánico

Las notas lo repiten con distintas palabras: *«co-blancos de un tercero»*,
*«vecindad genómica no es regulación»*, *«co-expresión, no regulación
afirmada»*, *«se listan como reguladores del mismo operón»*.

Es exactamente lo que cabe esperar de cómo funciona la extracción —dos genes en
la misma oración— en una literatura donde los genes de una misma vía se nombran
juntos constantemente. `RpoS → algU`, con 30 evidencias, se sostiene en frases
como *«The role of two sigma factors, AlgT and RpoS, in mediating...»*: los dos
nombrados como factores sigma, sin relación entre ellos.

### Se descartó la explicación cómoda

La sospecha inmediata era que la culpa fuera de la herramienta: las tres
oraciones que se muestran son las primeras del archivo, no las que mejor
respaldan la relación, así que un juez podría estar viendo evidencia floja de
aristas que la tienen fuerte.

Se midió: **de las 60 aristas del estrato A juzgadas `no`, solo en 3 (5 %) la
evidencia de mayor probabilidad no se había mostrado.** La selección no explica
el resultado.

### Lo que implicaría si la persona lo confirma

**El filtro del entregable no filtra lo que se creía.** El estrato A exige tres
o más artículos independientes y sin conflicto, y aun así sale en 31 %. Que
varios artículos mencionen dos genes juntos no es raro: es lo normal cuando
están en la misma vía. **Contar artículos no distingue una relación afirmada de
una coocurrencia frecuente.**

Eso apunta a filtrar por **calidad de la evidencia** —el tipo de redacción, la
probabilidad del modelo— y no por número de artículos.

Y sería el hallazgo más importante del proyecto, por encima del acierto de
signo: diría que la red tal como está es en su mayoría ruido, y que las tres
cifras que ya teníamos —exhaustividad, signo agregado, signo por oración— son
todas condicionales a que la arista exista, cosa que en dos de cada tres casos
no se cumple.

### Cómo queda la revisión

| | filas |
|---|---|
| dudosas (confianza baja o media) | 82 |
| control al azar de las que la pasada dio por seguras | 30 |
| **total a revisar** | **112 de 250** (~2.8 h) |

El control de 30 no es opcional: sin él, «el juez automático estaba seguro»
queda como supuesto sin comprobar. Con él se mide si esa confianza está
calibrada y el error se propaga al intervalo final.

`datos_etapa2/muestra_precision.tsv` trae `veredicto_auto`, `confianza_auto` y
`nota_auto` en columnas propias. **La columna `veredicto` está vacía en las 250
y es la única que cuenta** para lo que se publique.

## El plan

> **Al día del 27 de agosto por la noche.** De los cuatro pasos del bloque 1,
> tres están hechos y el cuarto queda preparado. Lo tachado no se borra: sirve
> para saber qué ya se contestó y con qué.

### Bloque 1 — medir, que es lo que preguntó el comité

| # | paso | estado | qué salió |
|---|---|---|---|
| 1 | `evaluar_oro.py --collectf` | **hecho** | 38.8 % contra la referencia externa, y **sin circularidad**: 37.1 % en los factores que el oro nunca menciona |
| 2 | Muestrear aristas y juzgarlas a mano | **preparado** | 250 aristas en `datos_etapa2/muestra_precision.tsv`, listas para llenar. **7 h de una persona** |
| 3 | Línea base de coocurrencia | pendiente | si el modelo supera a «aparecen juntos» |
| 4 | Línea base de LLM a ciegas | **hecho** | **91.4 % contra el 36.6 % del BioBERT**, y 91.7 % contra 8.3 % en la trampa |

**El paso 2 es lo único que bloquea la respuesta principal del comité**, y ya no
depende de programar nada: depende de que alguien lea 250 oraciones.

### Bloque 2 — subir el número

| # | paso | cuesta | qué mueve |
|---|---|---|---|
| 5 | La regla de inversión de fenotipo | 1 día | **36.6 % → ~51.6 %**, ya medido |
| 6 | **Añadir `Fur`, `Anr` y `Vfr` en su forma capitalizada** | 1 día | **1 536 menciones que hoy el pipeline no ve**, de tres reguladores centrales |
| 7 | Reentrenar con `<e1>/<e2>` como tokens y sin *lowercase* | 1 tarde de Colab | dos defectos conocidos del checkpoint |
| 8 | Calibrar umbrales sobre la auditoría | 1 día | 13 puntos de exhaustividad en juego |

El paso 5 es la capa 1 de la cascada propuesta, y es lo más rentable: de las 24
oraciones de la trampa, 14 son inversión pura.

#### Sobre el paso 6, que salió del trabajo de hoy

El informe tenía anotado *«tomar los sinónimos de proteína de UniProt en vez de
firmarlos a mano»* para cerrar los 12 factores que las fuentes públicas no
reconocen. **Se midió contra los 8 273 registros del caché y no funciona:**
`Anr`, `Fur` y `Vfr` aparecen, pero **en minúscula incluso en el campo de nombre
de proteína** («Transcriptional activator protein anr»). Los otros nueve no
están. Esa línea queda cerrada con datos, para que nadie la reintente.

Lo que sí funciona es otra cosa que el informe había descartado. Decía que
inventar la forma capitalizada *reintroduciría el falso positivo que la marca de
sensibilidad existe para matar*, y **ese razonamiento vale para emparejamiento
insensible a mayúsculas, no para una fila que ya es sensible**: ahí `Fur` no
puede casar con `fur`. Medido sobre los 918 textos:

| | ocurrencias exactas | qué resultaron ser |
|---|---|---|
| `Fur` | 481 | todas la proteína |
| `Anr` | 500 | todas la proteína |
| `Vfr` | 555 | todas la proteína |

Incluso las que empiezan oración. Son **1 536 menciones invisibles** para el
pipeline, de los reguladores maestros de hierro, anaerobiosis y virulencia.

**Cuidado con generalizarlo.** Se intentó como regla automática —*para toda fila
sensible con símbolo en minúscula, añadir la capitalizada*— y **excluye justo
estos tres**, porque `fur`, `anr` y `vfr` están en `palabras_comunes.txt`. La
exclusión mira la minúscula cuando lo que decide es si la **mayúscula** es
ambigua. Y aflojarla sin más daría `cat`→`Cat`, `era`→`Era`, `set`→`Set`, que sí
aparecen capitalizadas al inicio de oración.

**Por eso la propuesta no es una regla a priori sino una medición por
candidato**: contar las ocurrencias exactas de cada forma capitalizada en el
corpus y muestrearlas. Si son inequívocas, entra; si no, se queda fuera. Es
reproducible —cualquiera con el corpus lo rehace— y no depende de una firma.

Subiría la cobertura reproducible de **43/55 a 46/55** y quitaría tres filas de
la capa manual.

### Bloque 3 — el entregable del laboratorio

La red filtrada a lo que se puede defender, ya sobre la red corregida:

| subconjunto | aristas |
|---|---|
| todas | 8 488 |
| con signo resuelto | 4 025 |
| con signo, 3+ artículos independientes, sin conflicto | **897** |

Esas 897 son la «red para la toma de decisiones» que pidió el comité. **Lo único
que les falta es su precisión**, que sale del paso 2.

### Bloque 4 — lo de fondo, en paralelo

La **guía de anotación** antes de anotar nada, y luego anotar PAO1 con
asistencia de LLM y verificación humana.

---

## Sobre la cascada de decisión propuesta

**Lo que está bien:** ataca el fallo medido, escala por costo, y deja al LLM de
último recurso. Y el aviso de que los regex y la base de conocimiento se
escriben desde la literatura y nunca desde el patrón de oro es la disciplina
anticircularidad que a este proyecto le costó dos guardianes.

**Tres correcciones:**

1. **La capa 2 tiene un sesgo de selección.** «Si BioBERT coincide con el regex
   y tiene alta certeza, se acepta» quiere decir que solo se aceptan los casos
   donde dos métodos concuerdan, y esos subconjuntos siempre parecen exactos. Es
   el error del 86.5 % otra vez. Hay que reportar **siempre cobertura junto a
   exactitud**: «resolvió el X %, y en esos acertó el Y %».
2. **La cascada dificulta contestar al comité.** Si BioBERT solo decide cuando
   coincide con el regex, se mide un conjunto, no el modelo. Hace falta
   **ablación por capa** para saber qué aporta cada una.
3. **El 78 / 19 / 3 no está medido.** Son cifras de maqueta, y se pueden medir
   hoy con las 198 oraciones y los 65 223 pares.

**Una cosa que sí está resuelta y el diagrama daba por pendiente:** la capa 0 ya
funciona. Se comprobó que **las 8 653 aristas tienen un factor de transcripción
conocido como regulador, sin una sola excepción** — `extraer_pares.py` solo
propone pares cuyo regulador está marcado `es_tf` en el diccionario.

---

## Lo que no vamos a hacer, y por qué

**Automatizar el pipeline con Strands o con varios LLMs.** El pipeline es
determinista a propósito: el mismo corpus tiene que dar los mismos pares
siempre, o la medición no significa nada. Además `pip install` choca con la
restricción de biblioteca estándar. Donde los LLM sí valen es como línea base y
como asistentes de anotación, y así están en el plan.

**Ampliar el corpus con los PDFs de PMC, todavía.** Son 607 artículos y la vía
existe —el servidor procesó 130 con GROBID—, pero no tiene sentido ampliar el
corpus antes de saber si lo que ya se extrae es correcto. Va después del
bloque 1.

**Calcular precisión contra el patrón de oro.** No es una omisión: sería un
número falso, por las razones de arriba. Si alguien lo intenta, el programa se
niega y explica por qué.
