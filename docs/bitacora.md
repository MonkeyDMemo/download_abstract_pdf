# Bitácora y plan

Qué se hizo antes, qué se hizo hoy, y qué sigue. Escrito el 27 de agosto de
2026, después del comité.

Para el detalle técnico de cada punto está
[`informe-seminario-1.md`](informe-seminario-1.md); esto es el mapa.

---

## 17 de septiembre de 2026 (noche) — `virulence` se parte en tres, corrida 4

`virulence` juntaba cosas que se comportan distinto y medirla entera escondía
la diferencia. De las 1 417 candidatas que la activaban, el 53.5 % lo hacía
sólo por cuatro términos y el 46.5 % por algo concreto. Queda partida en tres,
que es donde estaba el corte:

| categoría | menciones | candidatas | sólo esa categoría |
|---|---|---|---|
| `virulence_molecule` | 5 453 | 1 005 | 698 |
| `virulence_general` | 2 547 | 291 | 174 |
| `virulence_phenotype` | 1 289 | 113 | 69 |

`acute infection` y `chronic infection` salieron a `infection_type`: son
escenario clínico, no mecanismo. Las tres juntas dan 1 352 candidatas, contra
las 1 417 de antes; los 65 que faltan son justo ésos.

**`virulence_general` queda marcada como señal débil en `PROCEDENCIA.md`.** Sus
cuatro términos son cómo el artículo resume, no lo que mide, y 174 candidatas
se activan sólo por ellos. Sirve para decir que la oración habla de virulencia;
no sirve como atributo de nodo, porque que una oración diga "pathogenicity" no
dice nada del gen que nombra.

### `infection_type`: se amplió, se midió, y se para ahí

Se añadieron 36 términos de tipo y sitio de infección, todos contados contra el
corpus antes de entrar. Tres candidatos se descartaron por no aparecer nunca
(`eye infection`, `catheter-associated infection`,
`community-acquired infection`), y se dejaron fuera `wound healing`,
`gut colonization` e `intestinal colonization`, que aparecen pero son procesos
y no tipos de infección.

**Resultado: 216 candidatas de 29 659, el 0.73 %.** Triplica la cobertura —eran
68— y aun así no llega al 1 % acordado, así que queda documentado como señal
débil y no se le da más trabajo.

Lo que explica la cifra, y es lo aprovechable: la categoría tiene **4 668
menciones (el 9.1 % de las de función) y sólo 216 candidatas**. `cystic
fibrosis` y compañía viven en el resumen y la introducción, donde se describe
el contexto clínico, y esas oraciones casi nunca traen dos genes distintos.
**El tipo de infección se enuncia donde no hay relación que extraer.** Si el
eje agudo-crónico hace falta, el sitio es una condición a nivel de documento en
el paso 2, no una categoría del bronce.

### Corrida 4

Menciones de función 47 123 → 51 160, ninguna sin categoría. Candidatas con
alguna función 6 554 → **6 665 (22.5 %)**; el alza son los términos de
infección nuevos. Las categorías no son comparables con la corrida 3 por
nombre: la misma mención cambia de etiqueta sin que cambie el texto, y por eso
la versión del método sube a 4.

### Decisión de cierre: las bombas de expulsión no entran como función

`MexAB-OprM` y las demás familias **se quedan como operón y como genes**, y no
se les da categoría de función. `efflux` —6 términos, 1 126 menciones— ya cubre
el concepto.

La razón es la misma que sacó a `regulation`: `mexAB-oprM` ya existe hoy en dos
capas, como operón del catálogo (PA0425-PA0427, 550 menciones) y como genes
sueltos. Añadirlo como función haría que **la misma mención produjera tres
filas en tres ejes distintos**, que es exactamente el solapamiento que se acaba
de deshacer. Un vocabulario que repite lo que otro ya dice no aporta señal: la
infla.

Quedan por medir **anaerobiosis y respiración microaerobia** y **metabolismo de
fosfato**. Antes de añadirlos se les aplica la regla de `PROCEDENCIA.md`:
menciones, candidatas y reparto por sección. Si se comportan como
`infection_type`, no entran.

### Deuda que sigue abierta al cerrar la semana

- Los acentos de `cli.py`, `exportar.py` y `PROCEDENCIA.md`, que hay que
  normalizar de una pasada y no a medias.
- El mapeo PA14 → PAO1 y, sólo después, el tokenizador (punto 35).
- Los 103 operones que le faltan al catálogo (punto 34).

---

## 17 de septiembre de 2026 (tarde) — `regulation` sale de las funciones, corrida 3

`regulation` era la categoría más grande de `funciones_semilla.csv` y la que
menos información propia aportaba. Los datos de la corrida 2 la cerraron: de
las 3 172 candidatas que la activaban **el 72 % no activaba ninguna otra
función**, el 87.8 % de sus menciones caía en oraciones que ya traían un
disparador, y **siete de sus términos estaban literalmente en
`disparadores.csv`** (4 460 menciones, el 31.1 %).

No se borró: se movió a `grn_bronce/recursos/contexto_regulatorio.csv`, con las
mismas dos columnas. La señal sirve, pero en otro eje — dice que la oración
**habla de regulación**, no de qué proceso biológico habla — y ese eje es
insumo del `tipo_relacion` del paso 2. Sus menciones se guardan con
`menciones.tipo = 'contexto_regulatorio'` y salen en su propia columna,
separadas de `funciones_biologicas`.

### Dos defectos silenciosos del emparejamiento, arreglados

Silenciosos porque la mención salía igual, sólo que sin categoría, o
directamente no salía: ninguno aparecía en los conteos.

**Mayúsculas.** La categoría se resolvía probando la superficie en minúsculas
y, si fallaba, la superficie cruda. Los 32 términos del catálogo que llevan
mayúscula (`exotoxin A`, `c-di-GMP`, `sRNA`, `type III secretion`, `lipid A`…)
sólo resolvían cuando el corpus usaba exactamente su capitalización:
`Exotoxin A` con E mayúscula salía con categoría vacía. **Recupera las 329
menciones**, 322 de función y 7 de contexto, y no queda ninguna sin categoría.

**Guiones.** `two component system` no emparejaba con `two-component system`.
**Aporta 2 243 menciones nuevas**: 1 339 de función y 904 de contexto.

Los dos se arreglan con la misma clave: minúsculas y `[-\s]+` colapsado a un
espacio, aplicada **a los dos lados**. Normalizar uno solo era el defecto.

De limpieza: ocho filas de `evidencia_experimental.csv` eran pares
guion/espacio del mismo término (`gel shift` y `gel-shift`, `rt-pcr` y
`rt pcr`…), escritas a mano justo porque el emparejamiento era literal. Se
quitaron; sus dos variantes tenían la misma `tecnica`.

### El punto 3 salió distinto de lo previsto, y es la corrección que importa

La lista de n-gramas del análisis anterior **sobreestimó los huecos**. El
filtro excluía un n-grama si era subcadena de un término más largo del
catálogo, pero no si lo *contenía*. Medido contra el corpus, de los términos
que se iban a trasladar:

| término | oraciones | ya detectadas |
|---|---|---|
| `mobility shift assay` | 55 | **55** (por `mobility shift`) |
| `mobility shift assays` | 51 | **51** |
| `shift assay` | 63 | 62 |
| `lacz transcriptional fusion` | 23 | **23** (por `lacz fusion`) |
| `directly binds` | 64 | **64** (por `binds`) |
| `western blot` | 119 | 50 |

Sólo **`western blot` era un hueco real** — `northern blot` estaba en el
catálogo y `western blot` no —, y añadirlo da evidencia a 69 oraciones que no
la tenían. Los demás se habrían duplicado, que es justo lo que el encargo
prohibía. `directly binds` sí se añadió pese a estar cubierto por `binds`: no
es la misma cadena sino una más específica, y la regla de coincidencia más
larga hace que 64 menciones registren el adverbio, que es la señal de unión
directa que pide el punto 6 del plan.

### Resultado, corrida 3

| | corrida 2 | corrida 3 |
|---|---|---|
| menciones de función | 60 134 | **47 123** |
| … sin categoría | 329 | **0** |
| contexto regulatorio | — | **15 268** |
| candidatas con alguna función | 8 652 (29.2 %) | **6 554 (22.1 %)** |
| candidatas con contexto regulatorio | — | 3 291 (11.1 %) |
| menciones de evidencia | 45 274 | 46 107 |

La caída de candidatas con función es la salida de `regulation`, no una
pérdida: **8 895 candidatas activan función o contexto**, contra 8 652 antes.
950 activan las dos. El neto es +243 por el arreglo de guiones.

### `pa14 pa14 pa14` no era un artefacto de tabla

Era un artefacto de **tokenización**, y tapaba un hallazgo mejor. Las 20
apariciones salen de locus tags de la cepa **PA14** (`PA14_23420`,
`PA14_59010`): el tokenizador parte por el guion bajo, se queda con `pa14` y
tira el número, así que tres locus tags seguidos en una enumeración se leen
como el mismo token tres veces. Siete oraciones candidatas en cinco documentos
(18927620, 24386415, 32459613, 33106346, 33995291).

**El defecto sigue ocurriendo, y hay que decir exactamente dónde.** El
tokenizador del análisis de n-gramas era de un script de un solo uso y no está
versionado, pero el del pipeline hace lo mismo: `etapa2/lexico.py::_TOKEN` es
`[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*`, que **no incluye el guion bajo**, así
que `PA14_23420` se parte igual en `PA14` y un `23420` que ya no empieza por
letra y no llega a token.

Lo que cambia es la consecuencia, y por eso no es urgente: **`PA14` no resuelve
a ninguna entrada del diccionario**, así que el pipeline no emite ninguna
mención. Comprobado: cero menciones con `texto = 'PA14'` en las corridas 2 y 3.
No fabrica falsos positivos; pierde en silencio. Las 195 menciones cuyo texto
empieza por `PA14` son locus tags PAO1 legítimos del rango `PA14xx`, otra cosa.

Lo que hay debajo sí importa: **377 locus tags `PA14_#####` distintos, 837
menciones en 83 documentos, y `genes_pao1.tsv` no reconoce ninguno.** El
diccionario es de PAO1 y esa es otra nomenclatura. Arreglar el tokenizador sin
añadir antes el mapeo PA14 → PAO1 no serviría de nada: produciría tokens
`PA14_23420` que el diccionario tampoco sabría resolver. Queda como punto 35
del plan, ligado al 17.

### Pendiente

No se añadió ningún término nuevo al vocabulario más allá de `western blot` y
`directly binds`: primero limpiar, luego ampliar. Los candidatos del análisis
de n-gramas siguen sin entrar.

---

## 17 de septiembre de 2026 — soporte de operones en el bronce, corrida 2

El bronce guarda ahora **las dos capas del operón**: la mención tal como el
artículo la escribió, y su expansión a los locus tag que contiene. El texto
dice `mexEF-oprN` y el grafo necesita PA2493, PA2494 y PA2495; ninguna de las
dos sustituye a la otra, así que van en columnas separadas y no mezcladas.

### Qué se corrió

`python -m grn_bronce.cli exportar --corpus v0-agosto`, que abrió la **corrida
2** (`baseline-deterministico` v2). La versión sube de 1 a 2 porque una fila
del bronce v1 y una de la v2 dicen cosas distintas del mismo texto. **La
corrida 1 se conserva intacta**: no se usó `--rehacer`, así que las dos están
en la base y se pueden comparar, y la muestra de 50 de
`etapa2/evaluacion/muestrear_candidatas.py` sigue anclada a la corrida 1.

Duración: 1 min 32 s sobre 2 361 documentos.

### Resultado

| cifra | valor |
|---|---|
| menciones de operón | **7 136** |
| operones distintos en el corpus | **363** |
| de ellos, en `operones_pao1.tsv` | 260 (6 689 menciones) |
| **fuera del catálogo** | **103** (447 menciones, 6.3 %) |
| oraciones candidatas con al menos un operón | **3 603** de 29 659 (12.1 %) |
| de ellas, con expansión no vacía | 3 390 (las otras 213 nombran un operón que el catálogo no conoce) |
| candidatas cuyo blanco es un operón | 393, sobre 74 operones distintos |

Los 103 que faltan son el entregable para el asesor y salen ordenados por
menciones con `python -m grn_bronce.cli operones --solo-faltantes`. Los de
arriba: `cyaAB` (53), `exoSTY` (53), `rsmZY` (45), `phzMS` (42), `lasRI` (20),
`sodAB` (18), `phzMSH` (16), `rhlABC` (14). Son concatenaciones que
`etapa2/lexico.py` acuña leyendo el texto cuando todos los miembros existen en
el diccionario, y que la tabla derivada por adyacencia no trae. **No expanden a
ningún gen**, y eso es deliberado: la expansión es solo por tabla.

### La corrida 2 es la 1 con otra etiqueta, y está comprobado

Mismas 273 062 unidades, mismas 488 221 menciones, mismas 29 659 candidatas,
mismas 5 833 con blanco. Los tipos se reparten distinto y suman igual: gen
67 591 + proteína 91 812 + operón 7 136 = **166 539**, exactamente el gen
71 865 + proteína 94 674 de la corrida 1.

La cobertura contra el oro **no se movió**: 149/176 = 84.7 % con denominador
honesto y 154/190 = 81.1 % sobre el total, con el mismo reparto de pérdidas
(12 / 8 / 7). Para que siguiera siendo comparable hubo que añadir `'operon'` a
los tres filtros `tipo IN ('gen','proteina')` de
`etapa2/evaluar_cobertura_bronce.py`, ahora en la constante `TIPOS_DE_GEN`.
Sin eso el evaluador habría dejado de ver 7 136 menciones y la cifra habría
bajado sin que el pipeline encontrara una relación menos. Es el modo de fallo
de siempre: el número sale igual de bien presentado y mide otra cosa.

**Diff de los dos CSV, columna por columna:** `genes`, `genes_locus_tag`,
`regulador_candidato`, `blanco_candidato`, `disparador`, `signo_sugerido`,
`score` y `oracion` cambian en **0** de las 29 659 filas.

### La única columna vieja que sí cambió: `proteinas`

Cambia en **1 468 filas** (4.9 %). Un operón capitalizado --`MexAB-OprM`--
empezaba por mayúscula, así que `_es_proteina()` lo mandaba a tipo `proteina` y
aparecía en esa columna; son 2 862 menciones, el 3.0 % de las 94 674 que tenía
la corrida 1. Un operón no es una proteína, así que sale.

**La superficie no se pierde**: sigue en `genes`, está en la nueva columna
`operones` y en la hoja de menciones con `tipo='operon'`. Queda fijado por
`grn_bronce/test_operones.py::test_un_operon_capitalizado_ya_no_cuenta_como_proteina`
para que no vuelva a ser un cambio silencioso.

### Dónde quedó la expansión

**`grn_bronce/operones.py`**, y es la única del proyecto.
`etapa2/evaluar_oro.py::cargar_operones()` y `miembros_de_tabla()` delegan ahí
en vez de repetirla; comprobado que el mapa de 3 030 filas sale idéntico al que
construía antes. Dos expansiones que se separan sin que nadie lo note dejarían
al evaluador y al bronce emparejando distinto.

Expone dos vistas de las mismas filas, no dos reglas: `miembros()` da símbolos
y locus tags juntos en minúsculas, que es lo que el emparejamiento del
evaluador necesita, y `locus_tags()` da solo los `PA####`, que es lo que llena
`genes_expandidos` porque el grafo se arma sobre locus tags.

### Salida

Dos columnas nuevas en `oraciones_candidatas`, **después de `proteinas`** para
no correr de sitio ninguna de las que ya existían: `operones` (la forma del
texto) y `genes_expandidos` (los locus tag del catálogo). Un CSV nuevo
`_operones.csv` y una cuarta hoja `operones` en el `.xlsx`, las dos desde
`db.operones_del_corpus()`. **Una oración sobre un operón de cinco genes sigue
siendo una fila y no cinco.**

De paso, los anchos de columna del `.xlsx` pasaron de letras fijas
(`"A"`, `"C"`, `"J"`...) a nombres de columna. Estaban atados a posiciones de
`COLUMNAS_CANDIDATAS`, así que insertar una columna los habría dejado
adornando la columna equivocada, en silencio.

### Dos defectos que salieron en la revisión y ya están arreglados

**`LIKE 'PA%'` no distinguía mayúsculas.** En SQLite `LIKE` es insensible para
ASCII y nadie activa `PRAGMA case_sensitive_like`, así que el numerador de la
tasa de normalización casaba también con los nombres de operón que empiezan por
`pa` minúscula: `parRS`, `panBC`, `panBCD`, `panCD`, `pabC-mltG`. En el corpus
son **78 menciones de `parRS`** contadas como locus tag sin serlo. Con
`GLOB 'PA*'`, que sí distingue, la tasa pasa de 95.12 % a 95.07 %: **el 95.1 %
publicado no se mueve**. Lo que sí se arregla es una incoherencia interna, que
era el síntoma preocupante: el mismo `id_normalizado='parRS'` era locus tag para
la métrica de la base y no lo era para la columna `genes_locus_tag` del CSV, que
filtra con el `startswith("PA")` de Python. El defecto es anterior a este
cambio.

**Un catálogo vacío pasado a propósito se descartaba en silencio.** `Catalogo`
define `__len__`, así que uno sin filas es *falsy*, y el
`catalogo = catalogo or Catalogo.cargar(...)` del exportador lo sustituía por el
real de 3 030 filas. Quien pidiera exportar sin expansión veía `en_catalogo=si`
y tres locus tag donde pidió nada. Ahora es `is None`.

Las dos correcciones están fijadas con pruebas que se comprobó que fallan contra
el código defectuoso; una prueba de regresión que no atrapa su regresión no
sirve de nada.

### Decisiones pendientes

- **`operones_pao1.tsv` es una predicción por adyacencia, no una lista de
  operones verificados.** Genes contiguos en la misma hebra suelen
  cotranscribirse, pero la regla no mira promotores ni terminadores ni
  transcriptoma. Expandir mete aristas en el grafo, y una expansión falsa mete
  aristas falsas. Anotado en `recursos/PROCEDENCIA.md`; decidir en el paso 3 si
  la expansión entra en la red o se queda como anotación.
- **Los 103 huecos del catálogo esperan criterio del asesor**: añadirlos a la
  tabla a mano, o aceptar que un operón sin expansión es un nodo sin resolver.
  Quedan como punto 34 de `PLAN.md`, con el listado completo en
  `salidas/operones_corrida2_20260917.csv`.
- **`PLAN.md` no traía el punto de operones.** La numeración llegaba a 30 y la
  sección 3.2 listaba los puntos 6 a 9. Resuelto el mismo día: la edición vivía
  fuera del repositorio y no se había aplicado. Ahora están los puntos 31 a 34 y
  la subsección 1.1 con la reunión del 11-sep; las dos subsecciones siguientes
  de la sección 1 se renumeraron a 1.2 y 1.3.

### Deuda: los acentos, y hay que arreglarlos de una vez

`grn_bronce/cli.py`, `grn_bronce/exportar.py` y
`grn_bronce/recursos/PROCEDENCIA.md` **no tienen un solo acento en todo el
archivo**, y eso incumple la regla de `CLAUDE.md`: el texto que lee una persona
--salida de terminal del CLI, encabezados, títulos y documentación-- lleva los
acentos correctos del español, y solo los identificadores van en ASCII.

Al añadir el soporte de operones se escribió sin acentos para no dejar los
archivos a medias, así que la deuda no creció en proporción pero sí en tamaño
absoluto. **La corrección es normalizar cada archivo entero de una pasada, no
acentuar las líneas nuevas**: un archivo con "operón" en una línea y "operon" en
la siguiente es peor que uno consistente, porque quien lo edite después no sabrá
cuál de los dos criterios seguir, y el diff de la normalización real quedará
enterrado entre las líneas ya tocadas.

Lo que hay que respetar al hacerlo: los identificadores **no** se tocan. Las
columnas `operones` y `genes_expandidos`, las claves del JSON, los nombres de
tabla y los `id=` del HTML siguen en ASCII sin acentos, como manda `CLAUDE.md`,
porque cambiarlos rompe el contrato tabular y la base. Lo que cambia es solo el
texto entre comillas que termina en pantalla o en un `.md`.

---

## 11 de septiembre de 2026 — precisión 44.0 %, evaluación versionada y guarda ampliada

Tres cosas en el día: los 50 juicios y la precisión del paso 1, la evaluación
versionada en `etapa2/evaluacion/`, y la guarda de contaminación ampliada, con
un hallazgo de CRLF que habría roto la reproducibilidad del muestreo.

### Los 50 juicios y la precisión del paso 1

**Qué se corrió.** `python etapa2/unir_juicios.py` sobre
`muestra_precision_50.csv` (50 candidatas de la corrida 1,
`baseline-deterministico` v1, semilla 20260904) y `juicio_consolidado.csv`,
llenado a mano el 11-sep sin ver el `signo_sugerido`. Los criterios del juez
están en `etapa2/evaluacion/criterios_juicio.md` (sus números de fila son
líneas del CSV, con el encabezado como línea 1).

**Resultado.** Las 50 filas juzgadas: `si` 22, `no` 24, `dudoso` 4.

| cifra | valor |
|---|---|
| **precisión de relación** | **22 de 50 = 44.0 %**, IC 95 % Wilson [31.2, 57.7] |
| acierto de signo | 1 de 1; sin intervalo, por debajo de 10 |

Los 4 dudosos están en el denominador y fuera del numerador, como manda el
script.

**Cómo se reparten los 24 `no`.** Seis son inversión de dirección: la oración
dice la relación al revés de como el bronce asignó regulador y blanco (líneas
8, 11, 20, 41, 44 y 50 del CSV). En esas seis el par es correcto y solo falla
la orientación. Contando el par sin dirección, la precisión subiría a 28 de 50
= 56.0 %. Es una lectura, no la cifra: el bronce emite pares dirigidos y así se
evalúa. El resto de los `no` son interacción proteína-proteína o co-regulación
sin vínculo, efectos negados en la oración, y casos sin relación.

**Por qué el signo casi no se evalúa.** De las 22 filas con relación, 7 llevan
`?` del juez (la oración no fija el sentido: «MexT-regulated», «under the
control of», pertenencia al regulón) y 14 llevan `signo_sugerido` sin resolver
(`?`, `+;?` o `-;?`). Queda una fila evaluable, y acertó. Cruzando lo sugerido
con lo juzgado en las 22: `+;?`→`+` 4, `-;?`→`-` 2, `+;?`→`-` 1, `+`→`+` 1,
`?`→`+` 6, `?`→`-` 1, `?`→`?` 7. Si el disparador dominante resolviera `+;?`
como `+` y `-;?` como `-`, habría 8 evaluables con 7 aciertos: todavía por
debajo del umbral de 10, y es un supuesto sobre cómo resolvería, no una
medición.

**Cómo leer el 44 %.** Es precisión de la candidata como relación dirigida,
leída solo desde su oración. El paso 1 entrega el *dónde*: una candidata «no»
sigue siendo una oración con dos genes y un disparador, que el paso 2 tiene
que descartar. La cifra dice cuánto ruido le llega al paso 2, no cuánto acierta
el pipeline. Va siempre junto al techo de cobertura (84.7 % contra el oro,
30.2 % contra la base curada con XML).

**Nota del juez.** Dos lecturas discutibles, líneas 14 (`mvfR → pqsA`, `si/+`)
y 27 (`rpoS → dinB` vía inducción del regulón en *E. coli*, `si/+`). Si se
cambiaran a `no`, la precisión sería 20 de 50 = 40.0 %.

### La evaluación, versionada

La muestra, el juicio, los criterios y el script del sorteo se versionaron en
`etapa2/evaluacion/`: antes vivían en `salidas/` (ignorado) y en la raíz (sin
rastrear), y el único número de precisión del paso 1 no estaba en el
repositorio. `muestrear_candidatas.py` es el script del 4 de septiembre,
recuperado de la sesión: población ordenada por id de candidata, sorteo con la
semilla 20260904 y barajado aparte con 20260905. `unir_juicios.py` apunta ahí
por omisión y da la misma cifra. En `PLAN.md`: 2.3 lleva la cifra, los puntos
15 y 29 quedan hechos, el 18 anota que el disparador dominante también
desbloquea la medición de signo, y entra el 30 (inversión de dirección).

**El hallazgo de CRLF.** La primera versión del script reproducía byte a byte
el archivo de `salidas/`, y con eso se dio por buena. Pero `csv` escribe CRLF
por omisión y `.gitattributes` guarda los CSV en LF, así que tras un checkout
limpio el archivo versionado y el regenerado habrían diferido en un byte por
línea: reproducible en esta máquina y en ninguna otra. Ahora escribe LF y
coincide byte a byte con el blob del commit. Es la misma trampa que el 3-sep
hizo fallar la prueba de divergencia del diccionario; la lección es que
«reproduce el archivo» hay que comprobarlo contra lo que git guarda, no contra
la copia local.

### La guarda de contaminación, ampliada

Es el punto 1 de la sección 3.1 del `PLAN.md`, la mitigación del incidente del
10-sep, en dos capas. La regla de usar la herramienta `Grep` y no un comando
quedó en `CLAUDE.md` (Confidencialidad), que es lo que se carga en cada
sesión. Y `test_contaminacion.py` protege también `GRN_experimental` y
`datos/validacion`, ya sin distinguir mayúsculas (`ORO_PSEUDOMONAS` no la
disparaba, aunque su comentario decía que sí) y entrando en subcarpetas
(`etapa2/para_colab/` y `etapa2/evaluacion/` quedaban fuera). La lista blanca
solo vale en el primer nivel del paquete. Dos pruebas nuevas fijan las
variantes que atrapa y el recorrido de subcarpetas.

Se comprobó con tres archivos sonda que nombraban `Datos/Validacion`,
`ORO_PSEUDOMONAS` y `grn_EXPERIMENTAL` desde subcarpetas: la guarda falló con
los tres, y se borraron. Lo que no atrapa (nombre concatenado, ruta por
variable de entorno, `glob`, `pathlib` por partes, archivos que no son `.py`)
está escrito en su docstring: protege contra el descuido, no contra la
evasión, y convertirla en análisis de flujo no vale lo que cuesta.
`settings.json` no se tocó. Suites: `etapa2` 524 pruebas con los 2 errores de
siempre de `test_clasificar`; raíz 412, OK.

---

## 10 de septiembre de 2026 — un `grep` recorrió `datos/validacion/`

**Qué pasó.** Al verificar las secciones 2.1 a 2.3 del `PLAN.md` nuevo con
agentes de solo lectura, uno de ellos buscó el script que sorteó la muestra de
50 con `grep -rn` sobre la raíz del repositorio. El recorrido entró en
`datos/`, incluida `datos/validacion/`. Según su propio reporte, filtró la
salida con `grep -v` y no se mostró nada de esa carpeta. Lo detectó el mismo
agente y lo avisó en su informe.

**El riesgo fue de recorrido, no de lectura de contenido.** El `--include`
limitaba la búsqueda a `.py`, `.md`, `.ipynb`, `.sh` y `.ps1`, así que el
`.xlsx` quedaba fuera del alcance de grep por construcción. Queda escrito para
que más adelante no se lea como una fuga.

**Por qué la regla no lo impidió.** Ninguna de las cuatro defensas cubre una
recursión desde la raíz:

- `CLAUDE.md` es una instrucción, no un bloqueo.
- `.claude/settings.json` niega `Read(./datos/validacion/**)` y
  `Bash(cat ./datos/validacion/*)`: frena la herramienta de lectura y un `cat`
  que nombre la ruta, pero no un `grep -r` lanzado desde la raíz, que llega a
  la carpeta sin nombrarla.
- La herramienta `Grep` respeta `.gitignore` y no entra en `datos/`; el `grep`
  de la shell sí.
- `test_contaminacion.py` vigila nombres dentro del código de los paquetes, no
  comandos.

**Mitigación: el punto 1 de la sección 3.1 del `PLAN.md`.** La preferente es
usar la herramienta `Grep` en vez del comando, porque negar comandos es frágil:
`rg`, `findstr`, `Select-String` o un script de Python esquivan la regla sin
querer. Como refuerzo, el mismo punto registra negar `Bash(grep *)` sobre rutas
de datos o exigir `--exclude-dir=datos`.

**Aplicado el 11 de septiembre**; el detalle está en la entrada de ese día.

---

## 3 y 4 de septiembre de 2026 — el paso 1 corre de punta a punta

**Qué se corrió.** `python -m grn_bronce.cli exportar --corpus v0-agosto`,
método `baseline-deterministico` versión `1`, corrida 1. **1 min 20 s** sobre
2 361 documentos.

**Resultado.** 273 062 oraciones persistidas, 488 221 menciones, **29 659
oraciones candidatas**, 95.1 % de normalización a locus tag. Salidas en
`salidas/bronce_identificacion_20260903.*` — tres CSV y un `.xlsx`, generados
por consulta a las tablas y no desde memoria.

**Antes de eso**, en la misma sesión: se fusionaron los dos `CLAUDE.md` y se
reestructuró el steering de Kiro, que vivía en cinco `.md` sueltos en la raíz
que Kiro nunca leyó. Se congelaron `CLAUDE.md`, `PLAN.md`, `.kiro/`, `docs/`
salvo esta bitácora, `servidor.py` y `trabajos.py`.

### Hallazgo: una colisión que `sensible_mayusculas` no puede arreglar

`tag` es **PA0010**, un gen real (DNA-3-metiladenina glicosidasa I). Sus **568
menciones** en el corpus son todas jerga de laboratorio: «epitope tag», «FLAG
tag», «Myc tag». Es la segunda superficie de gen más frecuente después de `fur`.

Lo que lo hace distinto de `folD`/fold: **la defensa existente no sirve**. El
símbolo del gen es minúscula `tag` y la palabra inglesa también, así que exigir
coincidencia exacta de mayúsculas no distingue nada. La fila ya está marcada
`sensible_mayusculas=true` por la cláusula de longitud y aun así entra.

Las salidas son: quitar `tag` del diccionario y aceptar perder el gen, o exigir
contexto (que no vaya precedido de «epitope», «FLAG», «His», «Myc», o de un
guion). Sin decidir. **Es una clase nueva y conviene buscar más antes de
elegir.**

### Cobertura del bronce sobre el oro, y la autorregulación

`etapa2/evaluar_cobertura_bronce.py`, nuevo. Mide **el techo del paso 1**: de las
relaciones canónicas, cuántas llegan a tener sus dos extremos juntos en alguna
oración candidata. Lo que no está ahí, el paso 2 no lo puede verificar porque no
lo va a ver.

Vive en `etapa2/` y no en `grn_bronce/` porque abre el patrón de oro, y el
paquete bronce no puede. Está registrado en la lista blanca de
`test_contaminacion.py` **como evaluador**, con la misma condición que
`evaluar_oro.py` y `verificar_oro.py`: nadie lo importa, no produce nada que el
pipeline consuma, y su salida es un informe.

| denominador | cubiertas | recall |
|---|---|---|
| honesto (atestiguada + signo resuelto + sin disputa) | 149 de **176** | **84.7 %** |
| sobre las 190, para comparar | 154 de 190 | 81.1 % |

**El denominador honesto sale 176, no ~169.** No es discrepancia de criterio: de
las 5 relaciones en disputa que documenta el README, **solo 1 se puede detectar**
(`RhlR→rpoS`, por la marca en la columna `alias`). Las otras 4 no están nombradas
en ninguna parte, así que no se pueden sacar del cómputo. El script avisa de eso
en cada corrida en vez de quedarse callado. Nombrarlas —hay un flag
`--disputadas` que las acepta— dejaría el denominador en 172.

**La autorregulación queda fuera de la coocurrencia actual y necesita regla
propia.** `grn_bronce/identificar.py` exige dos genes **distintos** por oración,
así que `MexT → mexT` no puede salir jamás: no es que no se encuentre, es que la
regla lo excluye por construcción. Son **11 filas del oro** (`AlgR→algR`,
`MexL→mexL`, `MexR→mexR`, `MexT→mexT`, `MexZ→mexZ`, `NalD→nalD`, `NfxB→nfxB`,
`AlgU→algU`, `AmrZ→amrZ`, `PchR→pchR` y `ExsA→exsCEBA`, donde ExsA es miembro de
su propio operón), 8 de ellas dentro del denominador honesto.

Es una **regresión respecto de `etapa2/extraer_pares.py`**, que sí las emitía con
`autorregulacion: true` precisamente «para que las 10 filas autorregulatorias del
patrón de oro no salieran de la evaluación». Sin decidir cómo se recupera.

#### Dos defectos propios, encontrados al medir

**El evaluador contaba la autorregulación como cubierta.** La primera versión
miraba la cobertura antes de detectar el caso, y como los dos extremos de
`MexT → mexT` resuelven al mismo conjunto de claves, **una sola mención de MexT
satisfacía los dos lados**. Daba 89.2 % en vez de 84.7 %: 4.5 puntos de más, el
5.7 % del denominador, en relaciones que el bronce no puede emitir. Corregido
decidiendo la autorregulación antes de mirar la cobertura.

**La prueba de divergencia del diccionario comparaba bytes crudos.** Falló
avisando de una divergencia que no existía: git en Windows convierte los finales
de línea al hacer checkout, y las dos copias diferían en 5 643 bytes sobre 5 643
líneas — exactamente un byte por línea. El contenido era idéntico. Ahora normaliza
los saltos antes de calcular la huella, y se comprobó que sigue atrapando
divergencia real añadiendo una fila falsa a una de las copias.

### Las 27 pérdidas, clasificadas por causa

`evaluar_cobertura_bronce.py --detalle`. De cada causa sale un ejemplo del
corpus, con su PMID; no se vuelca la referencia.

| causa | n |
|---|---|
| alias o símbolo del **blanco** ausente del diccionario | 11 |
| **autorregulación** | 8 |
| extremos en oraciones distintas | 7 |
| alias o símbolo del **TF** ausente del diccionario | 1 |

**Cuatro causas salieron en cero, y eso informa tanto como las que no:** oración
en sección excluida, oración fuera del rango de largo, evidencia solo en PDF no
parseado, y «otra». Es decir: **ni el filtro de METHODS ni el de longitud pierden
una sola relación canónica**, y ninguna pérdida se explica por el PDF sin
parsear. Los dos filtros que más sospecha levantaban resultaron inocentes.

Lo que queda es un reparto limpio: **12 de 27 son del diccionario** (no sabe
nombrar un extremo), 8 son la regla de autorregulación que no existe, y solo 7
son fallo genuino de la coocurrencia — los dos extremos están en el corpus pero
nunca en la misma oración. Ese último grupo es el único que arreglaría una
ventana de contexto.

### `pares_candidatos`: lo que el paso 2 recibiría

`grn-bronce pares`, nuevo subcomando, sobre la corrida 1:

| | |
|---|---|
| pares dirigidos distintos (TF → blanco, orientados) | **1 188** |
| con **2 o más documentos** | **307** (25.8 %) |
| oraciones que los sostienen | 5 833 |

Sin orientar —todo par de genes distintos que coocurre en una candidata— son
**17 191 pares**, de los cuales 3 948 (23.0 %) tienen dos o más documentos. La
diferencia entre 1 188 y 17 191 es lo que cuesta exigir disparador y un solo TF.

Ninguna de esas filas afirma que la relación exista. El conteo de documentos
distintos es la columna que importa: seis oraciones del mismo artículo siguen
siendo un artículo.

### `.gitattributes`, contra la causa y no el síntoma

`* text=auto eol=lf`, más `*.tsv` y `*.csv` explícitos. Ayer la prueba de
divergencia del diccionario falló por la conversión CRLF de git sobre contenido
idéntico; se arregló la prueba, pero la causa seguía ahí y habría vuelto a morder
en cualquier archivo con huella por contenido.

### Para la próxima semana, sin implementar

1. **Regla de autorregulación en `identificar.py`, con bandera propia.**
   `MexT → mexT` no puede salir hoy porque se exigen dos genes distintos por
   oración. Emitirlo marcado, como hacía `extraer_pares.py` con
   `autorregulacion: true`, **recupera 8 relaciones del denominador honesto** —
   de 149 a 157 sobre 176, o sea de 84.7 % a 89.2 %. Es la mejora más barata que
   hay sobre la mesa y su tamaño está medido.
2. **Columna `disputa` en `oro_pseudomonas.tsv`, alimentada por
   `verificar_oro.py`.** Hoy la documentación habla de 5 relaciones en disputa y
   solo 1 se puede detectar, por una marca en la columna `alias`; las otras 4 no
   están nombradas en ninguna parte, así que el denominador honesto sale 176 en
   vez de los ~169 que dice el README. Con la columna, el número dejaría de
   depender de una convención escrita a mano.
3. **Lista `requiere_contexto`, si hoy no alcanza.** Serían las 7 pérdidas cuyos
   dos extremos están en el corpus pero nunca en la misma oración: el único grupo
   que una ventana de ±1 podría recuperar. Conviene mirarlas una por una antes de
   decidir si la ventana vale lo que cuesta, porque ya está medido que ampliar la
   coocurrencia sin aserción es el mecanismo que produce el 16.8 % de precisión.

### El signo no se puede medir todavía, y por qué

La muestra de 50 para juicio humano se generó y se partió en dos vistas sin
anclaje: `juicio_relacion.csv` (sin ninguna columna de signo) y
`juicio_signo.csv` (sin disparador ni `signo_sugerido`). `etapa2/unir_juicios.py`
las une con la muestra y reporta la precisión de relación.

**El signo no se reporta.** De las 50 filas, solo **6** traen un signo único
resuelto. Y no es cosa de la muestra: sobre los **1 188 pares dirigidos** de la
corrida completa el reparto es el mismo problema a escala.

| `signo_sugerido` del par | pares | |
|---|---|---|
| solo `?` | 513 | 43.2 % |
| mezcla con `?` (`+;?`, `-;?`) | 366 | 30.8 % |
| **contradictorio** (`+` y `-` a la vez) | 195 | 16.4 % |
| único resuelto | **114** | **9.6 %** |

**Nueve de cada diez pares no tienen un signo utilizable.** La causa es la regla
de agregación: el bronce junta **todos** los disparadores de la oración en una
sola columna, y basta un genérico —`regulatory`, `binding`, `regulator`— para
que el par arrastre un `?` que se lo come todo. Peor: 195 pares salen
contradictorios porque una oración menciona una activación y una represión que
no van dirigidas al mismo par.

Publicar acierto de signo sobre un denominador de 6 daría un intervalo de Wilson
que no distingue nada. Queda registrado en la salida del script como
«denominador insuficiente», no como un cero ni como un hueco.

### Para mañana, anotado sin implementar

**Disparador dominante en `identificar.py`.** Una relación adopta el signo del
disparador **más específico de su oración**, no la unión de todos. «Más
específico» está por definir y es la decisión de fondo: probablemente el más
cercano al par regulador-blanco, con desempate por especificidad léxica
(`represses` gana a `regulatory`; un sintagma de dos palabras gana a una suelta).

Qué desbloquea, con las cifras ya medidas:

- **La cifra de acierto de signo**, hoy imposible: pasaría de 114 pares
  utilizables a un techo de 675, que son los que tienen algun disparador con
  signo (`solo ?` fuera).
- **Limpia `signo_sugerido` de los 1 188 pares dirigidos**, en particular los
  195 contradictorios, que hoy son ruido puro en la columna.

Lo que **no** desbloquea, y conviene no confundirlo: la inversión de signo de la
redacción desde el fenotipo del mutante sigue siendo del paso 2. Elegir bien el
disparador no arregla que «expression was increased in the mexT mutant» significa
represión.

### Pendientes anotados, no corregidos

Los seis primeros tocan archivos congelados; los demás son deuda del paso 1.

1. **`PLAN.md` sección 4** nombra los módulos del bronce como `menciones.py`,
   `candidatos.py`, `disparadores.py`, `indice.py`, `llm_local.py`. Los reales
   son `rutas.py`, `db.py`, `vocabulario.py`, `identificar.py`, `exportar.py` y
   `texto.py`. Actualizar al descongelar.
2. **`PLAN.md` describe mal `grn_etl/`**: lista `resolvers.py` y `downloader.py`,
   que no existen, y omite `trabajos.py` y `credenciales.py`. No menciona
   `servidor.py` ni `web/`.
3. **`grn_comun/` no está en `PLAN.md`.** Hizo falta para `procedencia.py`, que
   usan los tres pasos.
4. **El DDL aplicado se desvía del plan en cuatro puntos**, todos por motivo
   medido: `corridas` recupera `estatus`, `error`, `terminada_en` y contadores,
   que `ejecuciones` ya tenía y el plan perdía; `version` es TEXT para que
   `"3e-5"` no se vuelva `"3e-05"`; `texto_unidades` gana `contiguo`, por las
   594 oraciones que cruzan un encabezado borrado; y `oraciones_candidatas`
   gana `signo_sugerido`, `regulador_candidato` y `blanco_candidato`, que la
   hoja 1 necesita. Las columnas agregadas (`genes`, `funciones_biologicas`...)
   **no** se guardan: se derivan de `menciones` al exportar, para no tener dos
   copias que puedan dejar de coincidir.
5. **`palabras_comunes.txt` cita mal tres de sus cuatro locus tags** (`hemE` es
   PA5034, `minD` es PA3244, `pilI` es PA0410) y el número 191 de su cabecera
   no corresponde a nada: son 193 tocadas y 189 eliminadas.
6. **La corrección del diccionario del 27 de agosto añadió 24 aristas** además
   de quitar 189, y ningún documento lo explica.
7. **`lexico.py` sigue en `etapa2/`** y `grn_bronce` lo importa. Se copió el
   diccionario a `recursos/` con una prueba que falla si las dos copias
   divergen, pero el módulo no se movió: `etapa2/` está congelada.
8. **`transcriptional regulator` está en `disparadores.csv` y en
   `funciones_semilla.csv`**, así que produce dos menciones de la misma
   superficie. No es incorrecto —es las dos cosas— pero conviene decidirlo.
9. **El score no está calibrado.** Ordena; no debe usarse como umbral hasta
   medir si mejora la precisión.
10. **PDF sin procesar.** Los documentos con `pdf` estatus ok quedaron fuera;
    van después, con PyMuPDF.

### Una decisión que quedó sin poder cumplirse como se pidió

Se pidió poner en la hoja resumen **precisión y recall contra el oro que se usó
para el 31.7 %**. No se pudo, por tres razones que conviene dejar escritas:

- **El 31.7 % no salió de un patrón de oro.** Es precisión del estrato A de la
  red del paso 2, medida por muestreo estratificado con juicio.
  `evaluar_oro.py` prohíbe calcular precisión contra el oro, y con razón: cubre
  6 subsistemas, y una arista fuera de esa lista no está mal, solo no está
  listada.
- **Es de otro nivel.** La referencia lista pares regulador-blanco; esta capa
  produce oraciones. No hay denominador común.
- **El bronce no puede leer la referencia.** `test_contaminacion.py` prohíbe
  esa cadena en los tres paquetes, y partirla para colarla sería evadir la
  propia guarda.

La hoja lleva el tamaño de la referencia (190 pares, 6 subsistemas, 312
documentos citados) y dice explícitamente que las dos métricas no se calculan
ahí y por qué.

### Pendiente de confidencialidad, ya resuelto

La regla `deny: Read(./datos/**)` bloqueaba el corpus de PubMed, que es público
y es el insumo del paso 1. Se acotó a `datos/validacion/`, que es donde irán la
base curada v2 y los párrafos etiquetados cuando lleguen.

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
