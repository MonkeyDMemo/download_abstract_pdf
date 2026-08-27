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

**1. Contra una referencia externa, la exhaustividad se desploma.** Medida
contra `collectf_pao1.tsv` —333 pares con sitio de unión medido
experimentalmente, curados por CollecTF, que no construimos nosotros— la
recuperación cae a **~7 %**, frente al 95.1 % contra nuestro patrón.

Probablemente es **sesgo de construcción**: nuestro patrón se armó quedándonos
con las relaciones que el corpus atestigua, así que por diseño contiene lo que
el pipeline puede encontrar. CollecTF no pasó por ese filtro.

*La medición fue cruda* —sin expandir operones ni mapear locus tags— y
`evaluar_collectf()` ya existe en el repositorio y **nunca se ha corrido**. El
número real está entre ese 7 % y algo más alto. Averiguarlo es el paso uno.

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

## El plan

### Bloque 1 — medir, que es lo que preguntó el comité

| # | paso | cuesta | contesta |
|---|---|---|---|
| 1 | Correr `evaluar_oro.py --collectf` con la función que ya existe | 1 hora | «comparar contra lo que se tiene»; aclara si el 7 % es real |
| 2 | Muestrear 150 aristas y juzgarlas a mano | 1 día de código + **4 h de una persona** | **la precisión: cuántos errores comete** |
| 3 | Línea base de coocurrencia en la misma oración | 1 día | si el modelo supera a «aparecen juntos» |
| 4 | Línea base de LLM **a ciegas** sobre las 198 | 1 día | si el ajuste fino se justifica |

El paso 4 tiene que correrlo un modelo que **no haya visto** que las 93 son
todas `represses`, y sobre las 198 completas —las otras 105 hacen de
distractores—. Sin eso la línea base tendría el mismo defecto que le criticamos
al 86.5 %.

### Bloque 2 — subir el número

| # | paso | cuesta | qué mueve |
|---|---|---|---|
| 5 | La regla de inversión de fenotipo | 1 día | **36.6 % → ~51.6 %**, ya medido |
| 6 | Reentrenar con `<e1>/<e2>` como tokens y sin *lowercase* | 1 tarde de Colab | dos defectos conocidos del checkpoint |
| 7 | Calibrar umbrales sobre la auditoría | 1 día | 13 puntos de exhaustividad en juego |

El paso 5 es la capa 1 de la cascada propuesta, y es lo más rentable: de las 24
oraciones de la trampa, 14 son inversión pura.

Sobre el paso 6, los dos defectos vienen de la ficha del modelo y no se han
tocado: `<e1>` se parte en cuatro piezas, y el tokenizador trae
`do_lower_case=true` siendo un checkpoint *cased*, así que **`lasR` y `LasR` se
colapsan** y la mayúscula que distingue gen de proteína es invisible.

### Bloque 3 — el entregable del laboratorio

La red filtrada a lo que se puede defender:

| subconjunto | aristas |
|---|---|
| todas | 8 653 |
| con signo resuelto | 4 133 |
| con signo, 3+ artículos independientes, sin conflicto | **945** |

Esas 945 son la «red para la toma de decisiones» que pidió el comité. **Lo único
que les falta es su precisión**, que sale del paso 2.

### Bloque 4 — lo de fondo, en paralelo

La **guía de anotación** antes de anotar nada, y luego anotar PAO1 con
asistencia de LLM y verificación humana.

Sin guía se reproduce el defecto ya documentado: el 98.4 % de los `no_relation`
de *E. coli* son «marcaste la mención equivocada», no «estos genes no se
regulan». Anotar con ese criterio gasta el trabajo humano en enseñarle al modelo
algo que no le sirve para inferir.

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
