# Avance para el seminario 2

Qué se hizo desde el primer seminario, qué contestó cada cosa que pidió el
comité, y qué falta. Corte: 27 de agosto de 2026.

El detalle está en [`informe-seminario-1.md`](informe-seminario-1.md) y el
estado día a día en [`bitacora.md`](bitacora.md).

Todas las cifras salen de archivos que el repositorio produce y que llevan la
huella de sus entradas. Las de este documento son de **la corrida del 27 de
agosto**, posterior a la corrección del diccionario; donde el informe 1 publica
otra cifra para lo mismo, es porque venía de la corrida anterior y se dice.

---

## En una frase

**El programa corrió por primera vez con el modelo real y ya hay cifras sobre
*P. aeruginosa*. Todas vienen con la línea base que les quita el adorno, y dos
de las tres dicen algo incómodo.**

---

## Lo que pidió el comité, y qué se contestó

| lo que pidieron | estado | qué salió |
|---|---|---|
| Comparar contra lo que se tiene | **hecho** | CollecTF, referencia externa con evidencia experimental: **38.7 %** (129 de 333) |
| Cuántos errores comete | **en curso** | muestra de 250 aristas lista; falta el juicio humano |
| Cómo se evalúa el modelo | **hecho** | cada cifra sale con su línea base; sin ella no se cita |
| Buscar en PubMed Central (PDFs) | pospuesto | no tiene sentido ampliar el corpus antes de saber si lo que se extrae es correcto |
| Generar la red para decidir | **hecho** | 897 aristas con signo y respaldo de 3+ artículos |

---

## Lo que ya estaba: el número heredado, corregido

Es el resultado que el comité viene siguiendo desde el seminario 1 y sigue en
pie. El macro-F1 de 0.8721 del modelo del asesor medía memorización: el 73.9 %
de los ejemplos de prueba tenían su ventana de texto ya vista en entrenamiento.

Con la partición corregida —cero contaminación, verificada con una clave
distinta de la que se usó para agrupar— **la misma configuración pasa de 0.8721
a 0.9335 en prueba**. Sube, no baja: los hiperparámetros estaban bien; lo que
estaba mal era la medición.

Queda abierto cuánto de esa subida atribuir a quitar la contaminación, porque el
conjunto de prueba también cambió. Por eso falta el brazo de control.

---

## Las cifras nuevas

Sobre 2 361 documentos: **63 791 pares candidatos → 8 488 aristas**, con 375
factores de transcripción, 1 743 genes blanco y evidencia en 1 356 artículos.
Setenta y dos minutos de CPU en una laptop, sin GPU y sin servidor.

| medida | valor | su rival | veredicto |
|---|---|---|---|
| Exhaustividad contra el patrón propio | 95.1 % | azar **99.4 %** | **no mide el modelo** |
| Exhaustividad contra CollecTF | **38.7 %** | — | la honesta |
| Acierto de signo agregado | 86.5 % | clase mayoritaria 76.9 % | +9.6 pp, p = 0.010 |
| **Acierto de signo por oración** | **36.6 %** | sin información 16.9 % | despega, pero poco |
| ...solo fenotipo del mutante | **8.3 %** (2 de 24) | — | falla casi entero |

**Ninguna se puede citar sola.** El 95.1 % *pierde contra el azar*: mide el
diccionario y el extractor de pares, no el clasificador. Y el 86.5 % está a 9.6
puntos de contestar siempre `activates` sin leer nada.

### Por qué 86.5 % y 36.6 % no se contradicen

El modelo se inclina hacia `activates`. El patrón de oro es 80 activaciones de
104 filas comparables, así que ahí el sesgo **se parece a acertar**. La
auditoría de signo es toda represiones y no se lo permite. **Se construyó
justamente para que el 86.5 % no se pudiera citar solo, y funcionó.**

---

## Los tres resultados que valen para la tesis

### 1. La exhaustividad depende de dónde está escrita la relación

Contra CollecTF —333 pares con sitio de unión medido experimentalmente, curados
por terceros y que no pasaron por nuestro corpus— la recuperación bruta es del
**38.7 % (129 de 333)**, frente al 95.1 % contra el patrón propio.

**El pipeline no está repitiendo lo que se le enseñó**, y eso se midió:

| grupo | pares | exhaustividad |
|---|---|---|
| factores que nuestro patrón cubre | 271 | 38.8 % |
| **factores que nuestro patrón nunca menciona** | 62 | **37.1 %** |

Las dos tasas quedan a 1.7 puntos. **Con n = 62 el estudio no tiene potencia
para descartar diferencias menores de unos 20 puntos**, así que lo honesto es
decir que *no aparece señal de circularidad*, no que se haya demostrado su
ausencia. Recupera relaciones de **10 factores** que el patrón nunca menciona.

#### Dónde se pierden las otras 204

Producido por `etapa2/analizar_perdidas.py`, sobre los 333 pares:

| | n | de 333 |
|---|---|---|
| recuperada | 129 | 38.7 % |
| fue candidato pero no llegó a arista | 19 | 5.7 % |
| **el artículo está, pero el par nunca fue candidato** | **179** | **53.8 %** |
| el artículo no está en el corpus | 6 | 1.8 % |

De esos 179, en **159 (88.8 %) el gen blanco no se nombra en el artículo**.

Y el tipo de experimento lo explica:

| grupo | técnicas dominantes |
|---|---|
| recuperadas | EMSA 20.7 %, reportero β-gal 14.2 %, mutagénesis dirigida 10.5 % |
| nunca candidatas | **ChIP-Seq 26.2 % + RNA-Seq 26.2 %** |

Lo que recupera viene de experimentos **dirigidos a un gen**, discutidos en
prosa. Lo que pierde viene de experimentos de **genoma completo**, cuyos cientos
de blancos se publican en tablas suplementarias que el corpus no contiene.

#### La cifra corregida, y por qué había una versión inflada

Una versión anterior de este documento decía «76.8 % sobre lo que la prosa sí
afirma», excluyendo del denominador los 159 blancos no nombrados. **Estaba mal,
y el script lo demuestra: 101 de esos 159 son blancos que el diccionario solo
conoce por su locus tag.** Ahí el fallo es nuestro, no del corpus, y excluirlos
es excluir justo aquello de lo que el sistema es responsable.

Las tres cifras, con lo que excluye cada una:

| | exhaustividad | excluye |
|---|---|---|
| **bruta** | **38.7 %** (129/333) | nada |
| descontando solo lo que el corpus no puede dar | **48.1 %** (129/268) | 59 blancos genuinamente no nombrables + 6 sin artículo |
| descontando todo lo no nombrado | ~~77.2 %~~ | *además* 101 fallos del diccionario — **demasiado generosa** |

**La que hay que citar es la bruta, y junto a ella el 48.1 %** como techo de lo
alcanzable si el corpus fuera lo único que limitara. Los 101 fallos de
diccionario son trabajo pendiente, no una limitación del enfoque.

### 2. Un modelo general sin ajuste fino le gana al BioBERT ajustado

Sobre las mismas 93 oraciones de la auditoría, a ciegas y con las 105 no
evaluables mezcladas como distractores:

| | BioBERT ajustado | LLM sin ajuste |
|---|---|---|
| las 93 evaluables | 36.6 % | **91.4 %** |
| **fenotipo del mutante** | **8.3 %** | **91.7 %** |

**El control:** en las 105 co-menciones reparte `regulates` 45, `no_relation`
42, `represses` 18. No contesta una sola clase.

**Y una objeción propia, medida y descartada:** el primer prompt le decía que el
fenotipo del mutante invierte el signo —o sea, le enseñaba el truco que BioBERT
falla—. Repetido con prompt neutro **da exactamente lo mismo y los dos difieren
en 0 de las 93**.

**Tres límites que van con el número.** Son 93 oraciones de **un solo
subsistema** y todas de la misma clase: un conjunto difícil a propósito, no
representativo. El costo a escala es otro orden de magnitud —63 791 pares que
BioBERT hace en 72 minutos de CPU local—. Y el LLM evaluado es de la misma
familia que el sistema que preparó el conjunto, aunque los agentes clasificaron
a ciegas y sin ver las respuestas.

No dice que el ajuste fino sea inútil: dice que **para resolver el signo en una
especie distinta de aquella en que se entrenó, un modelo general lo hace
mejor**.

### 3. Una referencia es ciega a los errores que caen fuera de ella

Se encontraron cuatro genes de PAO1 que emparejaban con palabras inglesas
comunes: **`folD` con «fold»** («3-fold increase»), `hemE` con «heme», `pilI`
con «pili», `minD` con «mind». `folD` llegó a ser el segundo blanco más citado
de toda la tabla de evidencias.

Al corregirlo, **189 aristas desaparecieron y el 100 % llevaba una de las cuatro
palabras**. Cero daño colateral.

**Y las tres métricas de referencia no se movieron ni una décima**: 95.1 % de
exhaustividad, 86.5 % de signo agregado, 36.6 % por oración. El patrón de oro
cubre 190 relaciones de 6 subsistemas y la auditoría 93 oraciones de 6
represores; ninguna contiene una sola arista de `folD`, así que 189 falsos
positivos entraron y salieron sin que nada lo notara. *(La única que sí se movió
fue CollecTF, +0.9 pp, porque es la referencia que no se construyó desde este
corpus.)*

Es la respuesta concreta a *«cuántos errores comete»*: **una referencia mide lo
que cubre y es ciega a lo que cae fuera**. Solo muestrear la salida los ve.

---

## Lo que falta, y es lo que decide

**La precisión.** No se puede calcular contra el patrón de oro —contaría como
falso positivo cada arista correcta que el patrón no cubre— así que se mide
muestreando la salida y juzgándola: **250 aristas**, 120 del entregable y 65 de
cada uno de los otros dos estratos, con hasta tres evidencias de artículos
distintos cada una.

Una primera pasada automática, que **no es la medición**, insinúa **31 % en el
entregable** y 160 de 250 veredictos «la evidencia no afirma relación». El modo
de fallo es uno solo y es mecánico: *co-blancos de un tercero*, *vecindad
genómica*, *co-expresión*. Se descartó la explicación cómoda —que la herramienta
mostrara evidencia floja— midiendo que solo en el 5 % de los casos la mejor
evidencia no se había mostrado.

**Cómo se reparte el trabajo humano:** la persona revisa las 82 filas donde la
pasada automática dudó, más 30 tomadas al azar de las que dio por seguras —el
control sin el cual «el juez automático estaba seguro» quedaría como supuesto
sin comprobar—. Son **112 de las 250, unas 3 horas**; las 138 restantes se
aceptan solo si el control confirma que la confianza está calibrada.

Si el juicio humano confirma la primera pasada, sería el hallazgo más importante
del trabajo: **las tres cifras de arriba son condicionales a que la arista
exista**, y eso es lo que estaría fallando. Y apuntaría a algo concreto:
**contar artículos no filtra**, porque que varios artículos nombren dos genes
juntos es lo normal cuando están en la misma vía.

---

## Lo que sigue

| | qué | cuesta |
|---|---|---|
| 1 | **El juicio humano de la muestra** | ~3 h |
| 2 | Los 101 blancos que el diccionario solo conoce por locus tag | 1 día · sube el techo de 48.1 % |
| 3 | Regla de inversión del fenotipo del mutante | 1 día · **36.6 % → ~51.6 %** medido |
| 4 | Añadir `Fur`, `Anr`, `Vfr` capitalizados | 1 día · **1 536 menciones** invisibles hoy |
| 5 | Línea base de coocurrencia, y el brazo de control | 2 días |
| 6 | Reentrenar con `<e1>/<e2>` y sin *lowercase* | 1 tarde de GPU |
| 7 | Guía de anotación, y anotar PAO1 | el trabajo de fondo |

El punto 1 es lo único que bloquea la respuesta principal del comité, y ya no
depende de programar nada.

---

## Si solo hay tiempo para tres frases

1. **El número heredado sube al corregir la medición** —0.8721 a 0.9335— y ya
   hay cifras propias sobre *P. aeruginosa*, todas con su línea base: la
   exhaustividad de 95 % pierde contra el azar y no mide el modelo; la honesta,
   contra una referencia externa, es **38.7 %**.
2. **El acierto de signo es 36.6 % oración por oración**, y un modelo general
   sin ajuste fino saca 91.4 % sobre las mismas oraciones. El ajuste sobre
   *E. coli* no transfiere.
3. **Falta la precisión, que es lo que preguntó el comité**, y no se puede sacar
   de ninguna referencia existente: hay 250 aristas muestreadas esperando tres
   horas de juicio humano.

---

## Y una advertencia sobre cómo leer todo esto

Cuatro veces en este trabajo un número resultó estar midiendo algo distinto de
lo que decía: el 0.8721 heredado medía memorización; el 95 % de exhaustividad
mide el extractor; el 86.5 % de signo mide el reparto de clases; y el 77.2 % que
una versión anterior de este documento publicaba excluía del denominador 101
fallos propios.

**Las cuatro se detectaron construyendo el rival que el número tenía que ganar**,
no mirando el número. La última la encontró una revisión de este mismo
documento, tres días después de escribirlo.

Por eso ninguna cifra de aquí aparece sola, y por eso la que falta —la
precisión— se está midiendo con el método más caro y no con el más cómodo.
