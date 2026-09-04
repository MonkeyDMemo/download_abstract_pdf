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

Derivados del genoma. Columnas: `operon`, `miembros`, `locus_tags`, `fuente`.
Sirven para que `mexEF-oprN` se reconozca como una unidad y no como tres genes
sueltos.

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

## Nota sobre la copia

`genes_pao1.tsv`, `operones_pao1.tsv`, `manual_pao1.tsv` y
`palabras_comunes.txt` son **copia byte a byte** de los de `etapa2/`, que sigue
usandolos y esta congelada. Hay una prueba que falla si las dos copias
divergen: dos diccionarios que se separan sin que nadie lo note es exactamente
el defecto que este proyecto no se puede permitir. Cuando `etapa2/` se migre,
la copia de `etapa2/` desaparece y esta queda como unica.
