# Procedencia de los recursos del bronce

De donde sale cada archivo de esta carpeta, con que se construyo y que sabe
hacer. Sin esto, el diccionario es una tabla que aparecio de la nada y nadie
puede decir si cubre lo que dice cubrir.

## `genes_pao1.tsv` — el diccionario de registro

**5 642 filas**, una por gen de *Pseudomonas aeruginosa* PAO1.

| columna | que es |
|---|---|
| `locus_tag` | `PA####`, el identificador canonico |
| `simbolo` | el nombre corto (`mexT`), vacio si no tiene |
| `alias` | sinonimos separados por `\|` |
| `tipo` | `protein_coding` (5 515), `tRNA` (63), `ncRNA` (29), `pseudogene` (19), `rRNA` (13), y 3 entradas manuales de tipo `complejo` o `familia` |
| `producto` | la descripcion funcional de RefSeq |
| `es_tf` | `true` en **572 filas**: los factores de transcripcion y sigma |
| `fuente_tf` | por que se marco como TF |
| `fuente` | que fuentes respaldan la fila |
| `sensible_mayusculas` | `true` en **185 filas**. Ver abajo |

### Las cuatro fuentes

| fuente | que aporta | filas |
|---|---|---|
| **RefSeq**, GFF de `GCF_000006765.1_ASM676v1` | el esqueleto: locus tag, simbolo, tipo y producto | todas |
| **KEGG**, `rest.kegg.jp/list/pae` | sinonimos y confirmacion de simbolo | todas |
| **UniProt**, `rest.uniprot.org/uniprotkb/search` (dos consultas: proteoma y especie) | mas sinonimos y la marca de factor de transcripcion | 5 520 |
| **capa manual**, `manual_pao1.tsv` | 22 filas con justificacion en prosa obligatoria y tope duro de 40 | 22 |

Reparto real de la columna `fuente`: `refseq|kegg|uniprot` en 4 006 filas,
`refseq|kegg|uniprot|uniprot_especie` en 1 495, `refseq|kegg` en 119, y el
resto con capa manual encima.

### Por que no Pseudomonas Genome DB

Es la fuente que un lector esperaria, y **no se puede usar**: `pseudomonas.com`
devuelve **HTTP 403** a `urllib.request`, incluida la peticion con User-Agent
de navegador. Es proteccion de bot, no filtro de cabecera. Pasarla exigiria un
navegador headless, que es a la vez dependencia y evasion, y las dos cosas
estan prohibidas por `CLAUDE.md`. Comprobado el 20 de agosto y de nuevo el 3 de
septiembre de 2026. Ver `docs/hallazgos.md`.

### `sensible_mayusculas`: la defensa contra las colisiones con el ingles

Una fila marcada asi exige **coincidencia exacta de mayusculas** para todas sus
superficies. La regla que la calcula tiene dos clausulas: superficie de tres
caracteres o menos, **o** superficie presente en `palabras_comunes.txt`.

Son 185 filas: 181 por longitud y **4 por la lista**, que son las que costaron
caro. `folD` emparejaba con "fold" de "a 3-fold increase" y llego a ser el
segundo blanco mas citado de toda la tabla de evidencias. Con `hemE`/heme,
`pilI`/pili y `minD`/mind sostenian **193 de 8 653 aristas**.

**No es una lista negra, y la diferencia importa.** Una lista negra borraria la
entrada del diccionario y con ella las menciones correctas del mismo gen: se
habria llevado por delante `Anr->hemE` y las tres aristas de `pilI`, que tienen
evidencia coherente. Exigir mayusculas conserva el gen y descarta la palabra.

`fur` (PA4764) esta cubierto por la clausula de longitud. **`cap` no existe en
PAO1**: es el nombre de *E. coli*, y el homologo aqui se llama `vfr` (PA0652).

## `operones_pao1.tsv` — 3 030 operones

Columnas: `operon`, `miembros`, `locus_tags`, `fuente`. Sirven para que
`mexEF-oprN` se reconozca como una unidad y no como tres genes sueltos, y para
expandirlo despues a los genes que contiene.

### De donde salen

**Derivados del mismo GFF de RefSeq que el diccionario**
(`GCF_000006765.1_ASM676v1`), por adyacencia de locus tags. Las 3 030 filas
llevan `fuente = refseq_adyacencia`; no hay ninguna otra fuente en la tabla.
Los construye `etapa2/construir_diccionario.py::derivar_operones()`.

La regla, en cuatro pasos:

1. Se recorren los genes en el orden del GFF y se agrupan los que tienen locus
   tags consecutivos **y** un simbolo de la forma prefijo de tres minusculas
   mas una mayuscula (`mexA`, `oprM`). Un gen sin simbolo o con otra forma
   corta la corrida.
2. **Una corrida no cruza un cambio de hebra.** Dos genes contiguos en hebras
   opuestas son divergentes o convergentes: no comparten promotor y no forman
   operon.
3. Los miembros se escriben en **orden de transcripcion**, no de locus tag
   ascendente. Verificado en el GFF: `mexCD-oprJ` va en la hebra menos (PA4597
   `oprJ`, PA4598 `mexD`, PA4599 `mexC`), asi que por locus tag ascendente el
   nombre que sale es `oprJ-mexDC`, que no existe en ninguna parte.
   `mexAB-oprM` y `mexEF-oprN` salian bien solo porque van en la hebra mas.
4. De cada corrida maximal se emiten **todas las sub-corridas contiguas de dos
   o mas genes**. De ahi el reparto de tamanos: 873 filas de 2 genes, 536 de 3,
   373 de 4, y una cola hasta 31. Es lo que permite que el texto nombre
   `pqsABCDE` o solo `pqsAB` y las dos formas emparejen.

Un nombre de operon que choque con el simbolo de un gen se descarta: esa
superficie resolveria a dos entidades y `lexico` no emitiria ninguna mencion.
Se descarta el operon, que es el derivado.

### La cautela que hay que leer antes de usarla

**Es una prediccion por adyacencia, no una lista de operones verificados
experimentalmente.** Genes contiguos en la misma hebra suelen cotranscribirse,
pero no siempre, y la regla no mira promotores ni terminadores ni datos de
transcriptoma. Lo que la tabla afirma es "estos genes son vecinos en la misma
hebra y sus nombres componen esta cadena", no "estos genes forman un operon".
La distincion importa aguas abajo: expandir un operon mete aristas en el grafo,
y una expansion falsa mete aristas falsas.

### Con que criterio se expande

**Solo por tabla, nunca deducido del nombre.** `grn_bronce/operones.py` es la
unica expansion del proyecto; `etapa2/evaluar_oro.py` delega ahi en vez de
repetirla.

- Un nombre expande a lo que su fila diga, y a nada mas. La expansion mecanica
  --leer `pqsABCDE` y deducir pqsA..pqsE-- queda fuera, y no por gusto:
  `etapa2/lexico.py` acuna operones sinteticos leyendo el texto en cuanto todos
  los miembros existen en el diccionario (`lasRIAB`, `rsmZA`, `gacAS`,
  `exoSTY`), y con la expansion mecanica una sola arista inventada
  `LasR -> lasRIAB` se contaba como recuperacion de **tres** filas del oro a la
  vez. Un nodo fabricado por una concatenacion del texto subia la exhaustividad
  sin haber encontrado ninguna relacion.
- **Un operon que la tabla no conoce no expande a nada**, y eso es el
  comportamiento buscado: sale listado como hueco del catalogo en
  `python -m grn_bronce.cli operones --solo-faltantes`. Es el entregable, no un
  fallo.
- El nombre se compara **en minusculas**: `MexEF-OprN` y `mexEF-oprN` son el
  mismo operon, porque la mayuscula es convencion de nomenclatura --forma
  proteina contra forma gen-- y no identidad.
- Hay **dos vistas de las mismas filas**, no dos reglas. `miembros()` devuelve
  simbolos y locus tags juntos en minusculas, que es lo que el emparejamiento
  del evaluador necesita porque las referencias nombran los extremos de las dos
  formas. `locus_tags()` devuelve solo los `PA####` tal como estan escritos, y
  es lo que llena la columna `genes_expandidos`, porque el grafo se arma sobre
  locus tags y no sobre simbolos.

### Las dos capas, y por que se guardan las dos

El bronce guarda la **mencion del operon tal como aparece en el texto** y su
**expansion a los genes que contiene**, en columnas separadas. El texto dice
`mexEF-oprN`; el grafo necesita PA2493, PA2494 y PA2495. Ninguna sustituye a la
otra: aplanar el operon a sus genes al guardarlo perderia lo que el articulo
dijo de verdad --y con ello la unica senal de que al catalogo le falta esa
entrada-- y dejarlo sin expandir dejaria al paso 3 sin nodos.

Por eso una mencion de operon se guarda con `menciones.tipo = 'operon'` y su
nombre como `id_normalizado`, y **una oracion sobre un operon de cinco genes
sigue siendo una fila y no cinco**.

## `palabras_comunes.txt` — 41 entradas

Las superficies que colisionan con palabras inglesas comunes. Alimenta la
segunda clausula de `sensible_mayusculas`.

**Pendiente anotado, no corregido:** el archivo cita mal tres de los cuatro
locus tags de su propio hallazgo (`hemE` es PA5034 y no PA5259; `minD` es
PA3244 y no PA3400; `pilI` es PA0410 y no PA4551), y el numero 191 que aparece
en su cabecera no corresponde a ninguna cifra real: son 193 tocadas y 189
eliminadas. Son comentarios, asi que no afectan el emparejamiento.

## `disparadores.csv`, `funciones_semilla.csv`, `evidencia_experimental.csv`

Vocabularios semilla del paso 1, escritos **desde la literatura del dominio**,
nunca desde el patron de oro ni desde las oraciones auditadas. Esa regla no es
formalidad: si el vocabulario sale de la referencia con la que luego se evalua,
las metricas dejan de medir lo que el pipeline encuentra y pasan a medir lo que
le sopla la referencia, con la misma etiqueta y la misma pinta de correcto.

Cada termino se conto contra los 918 textos completos del corpus antes de
incluirse; lo que no aparece nunca se descarto.

**Ese filtro explica por que ningun termino del catalogo tiene cero menciones,
y por que ese cero no significa nada.** El catalogo se construyo exigiendo
presencia en el corpus, asi que medir "cuantos terminos no aparecen" solo
confirma el filtro. Para medir si un termino *sirve* hace falta otra cosa: por
ejemplo, si aparece solo en oraciones sin par de genes.

## `virulence`, partida en tres el 17 de septiembre de 2026

La categoria `virulence` juntaba cosas que se comportan distinto, y medirla
entera escondia esa diferencia. Sobre la corrida 3, de las 1 417 candidatas que
la activaban, el 53.5 % lo hacia solo por cuatro terminos y el 46.5 % por algo
concreto. Se parte en tres, que es donde estaba el corte de verdad:

| categoria | que es | terminos |
|---|---|---|
| `virulence_molecule` | moleculas medibles: se cuantifican en un ensayo | 9 |
| `virulence_phenotype` | fenotipos de ensayo: se observan, no se pesan | 8 |
| `virulence_general` | etiquetas de resumen del articulo | 4 |

**`virulence_general` no discrimina, y hay que decirlo donde se lee.** Sus
cuatro terminos --`pathogenicity`, `pathogenesis`, `virulence factor`,
`virulence gene`-- son como el articulo resume, no lo que mide: **222
candidatas se activan solo por ellos**, sin ninguna otra funcion que las
acompane. Sirve como **senal debil** --dice que la oracion habla de virulencia
en general-- y **no como atributo de nodo**: que una oracion diga
"pathogenicity" no dice nada del gen que nombra. Usarla como si fuera un
atributo pondria la misma etiqueta a todo gen que aparezca cerca de la palabra.

`acute infection` y `chronic infection` salieron de aqui: son el escenario
clinico, no el mecanismo. Viven ahora en `infection_type`.

## `infection_type` — 38 terminos

El eje agudo-cronico y los escenarios clinicos. Se midio antes de decidir si
merecia categoria propia: con solo `acute infection` y `chronic infection` eran
**68 candidatas de 29 659, el 0.23 %**, que no da para medir nada. Se amplio con
36 terminos de tipo y sitio de infeccion, todos contados contra el corpus antes
de entrar; tres candidatos se descartaron por no aparecer nunca (`eye
infection`, `catheter-associated infection`, `community-acquired infection`), y
se dejaron fuera `wound healing`, `gut colonization` e `intestinal
colonization`, que aparecen pero son procesos y no tipos de infeccion.

Incluye variantes de grafia que la normalizacion no cubre porque son palabras
distintas: `bacteremia`/`bacteraemia`, y las formas cortas del entorno de
fibrosis quistica que el corpus usa de verdad (`cf patients`, `cf lung`,
`cf airway`).

**Resultado de la ampliacion, y la decision que cierra: senal debil.** Con los
38 terminos, `infection_type` llega a **216 candidatas de 29 659, el 0.73 %**.
Amplio la cobertura por un factor de tres --eran 68 con solo `acute infection`
y `chronic infection`-- y aun asi **no llega al 1 %**, que era el umbral
acordado para darle mas trabajo. Se queda como esta y no se amplia mas.

La asimetria entre sus **4 668 menciones (el 9.1 % de las de funcion)** y sus
216 candidatas es la explicacion, y conviene entenderla antes de volver a
tocarla: `cystic fibrosis` y compania aparecen sobre todo en el resumen y la
introduccion, donde se describe el contexto clinico, y esas oraciones casi
nunca traen dos genes distintos, que es lo que exige una candidata. **El tipo
de infeccion se enuncia donde no hay relacion que extraer.** Por eso, si el
eje agudo-cronico llega a hacer falta, el sitio no es una categoria del bronce
sino una condicion a nivel de documento en el paso 2.

## `contexto_regulatorio.csv` — 26 terminos

**Salio de `funciones_semilla.csv` el 17 de septiembre de 2026**, con las
mismas dos columnas (`termino`, `categoria`) y el mismo criterio de
construccion. Era la categoria `regulation`, la mas grande del archivo con
14 342 menciones (el 23.9 % de 60 134), y la que menos informacion propia
aportaba. Las tres cifras que lo decidieron, medidas sobre la corrida 2:

- de las 3 172 candidatas que la activaban, **el 72 % no activaba ninguna otra
  funcion**: como funcion biologica no discriminaba nada;
- **el 87.8 %** de sus menciones caia en oraciones que ya traian un disparador,
  y el 48.6 % en oraciones que ya traian un factor de transcripcion;
- **siete de sus terminos estaban literalmente en `disparadores.csv`**
  (4 460 menciones, el 31.1 %): `regulon`, `transcriptional regulator`,
  `transcriptional activator`, `negative regulator`,
  `transcriptional repressor`, `positive regulator` y `autoregulation`.

No se borro porque la senal sirve, pero en otro eje. Un termino de aqui dice
que la oracion **habla de regulacion**, no de que proceso biologico habla, y
eso es insumo del `tipo_relacion` del paso 2, no de la anotacion funcional.
Por eso sus menciones se guardan con `menciones.tipo = 'contexto_regulatorio'`
y salen en su propia columna de la exportacion, separadas de
`funciones_biologicas`.

## Como se emparejan los terminos

Desde la version 3 del metodo, termino y superficie se comparan por una clave
normalizada: **minusculas, y guiones y espacios colapsados a un espacio**. El
patron hace el camino inverso, de modo que cada separador de un termino acepta
guion o espacio y una sola entrada cubre las dos formas.

Arregla dos defectos que eran silenciosos --la mencion salia igual, solo que
sin categoria, o directamente no salia-- y que por eso no aparecian en ningun
conteo:

1. **Mayusculas.** La categoria se resolvia probando primero la superficie en
   minusculas y despues la superficie cruda. Los 32 terminos del catalogo que
   llevan mayuscula (`exotoxin A`, `c-di-GMP`, `sRNA`, `type III secretion`,
   `lipid A`...) solo resolvian cuando el corpus usaba exactamente esa
   capitalizacion: `Exotoxin A` con E mayuscula salia con categoria vacia.
   Eran **329 menciones**, el 0.5 %.
2. **Guiones.** `two component system` no emparejaba con `two-component
   system`, que si estaba en el catalogo. El arreglo aporto **2 243 menciones
   nuevas**.

Consecuencia de limpieza: ocho filas de `evidencia_experimental.csv` eran
pares guion/espacio del mismo termino (`gel shift` y `gel-shift`, `rt-pcr` y
`rt pcr`...), escritas a mano justo porque el emparejamiento era literal. Ya
no hacen falta y se quitaron; sus dos variantes tenian la misma `tecnica`, asi
que no se pierde nada.

## Nota sobre la copia

`genes_pao1.tsv`, `operones_pao1.tsv`, `manual_pao1.tsv` y
`palabras_comunes.txt` son **copia byte a byte** de los de `etapa2/`, que sigue
usandolos y esta congelada. Hay una prueba que falla si las dos copias
divergen: dos diccionarios que se separan sin que nadie lo note es exactamente
el defecto que este proyecto no se puede permitir. Cuando `etapa2/` se migre,
la copia de `etapa2/` desaparece y esta queda como unica.
