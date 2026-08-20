# Diccionario de genes de *Pseudomonas aeruginosa* PAO1

Construye un diccionario de genes para reconocer menciones en texto cientifico,
a partir de tres fuentes publicas de **anotacion de secuencia** (no de listas de
relaciones regulatorias): RefSeq (GFF), KEGG y UniProt. Solo biblioteca estandar
de Python 3.8+ (`urllib`, `gzip`, `re`, `os`, `time`). Sin `requests`, `pandas`,
`biopython` ni `lxml`.

## Como correrlo

    python3 construir_diccionario.py

Crea la carpeta `diccionario_independiente/` con:

- `cache/` — respuestas crudas de las tres fuentes (una segunda corrida NO
  vuelve a golpear la red).
- `genes.tsv` — un renglon por `locus_tag` PA####. Columnas, en este orden:
  `locus_tag, simbolo, alias, tipo, producto, es_tf, fuente_tf, fuente,
  sensible_mayusculas`.
- `operones.tsv` — operones derivados del propio diccionario (mismo simbolo
  base, locus consecutivos, misma hebra), nombrados en sentido de transcripcion.
  Columnas: `operon, miembros, locus_tags, hebra`.
- `sitios_union.tsv` — pares factor -> blanco tomados de los `protein_binding_site`
  del GFF (evidencia experimental de secuencia). Columnas: `tf, blanco,
  experimento, pmids`.

Al terminar imprime los conteos reales (genes, marcados `es_tf`, operones y
cuantos en hebra menos, pares y factores de sitios de union).

## Validar la logica que NO necesita red

    python3 test_logica.py

Prueba con datos sinteticos el nombrado de operones (incluido el caso de hebra
menos `mexCD-oprJ`), la regla `es_tf`, la sensibilidad de mayusculas, el parseo
de atributos del GFF y la construccion de sitios. Debe imprimir
`TODO OK`.

## Numeros de control (para detectar si una fuente cambio)

Del GFF de RefSeq (`GCF_000006765.1`), tras descomprimir:

- ~3,243,384 caracteres
- 11,599 apariciones de `locus_tag=`
- 532 features `protein_binding_site`

Ordenes de magnitud esperados en la salida:

- ~545 genes marcados `es_tf`
- ~33 factores y ~332 pares en `sitios_union.tsv`

Si el conteo de `es_tf` o los del GFF se salen mucho de esto, revisa que la
fuente no haya cambiado (el script avisa si el GFF no coincide).

## Que significa `es_tf` (leer)

La marca `es_tf` es la **union de 5 senales de UniProt**: los terminos GO
`GO:0003700` y `GO:0006355`, y las palabras clave `Transcription regulation`,
`Sigma factor` y `Two-component regulatory system`. El producto de RefSeq nunca
dispara la marca; solo se anexa como corroboracion (`producto_refseq`) cuando la
marca ya es verdadera por UniProt.

**Honestidad:** ninguna fuente dice con autoridad "esto es un factor de
transcripcion". Esas senales son inferencia curada (buena parte por similitud de
dominio). Por eso `es_tf` **sobre-incluye** la mitad sensora de los sistemas de
dos componentes (histidina-cinasas, que no se unen a ADN) y los factores
anti-sigma. Es el costo de usar anotacion de secuencia en vez de una lista de
relaciones; queda documentado, no se "corrige".

## No-contaminacion

El diccionario no se construye, ni parcial ni totalmente, a partir de ninguna
lista de relaciones regulatorias conocidas. La columna `fuente` solo admite
`refseq`, `kegg`, `uniprot`. Los `sitios_union` viven en su propio archivo y no
alimentan la marca `es_tf` ni el conjunto de genes: asi el diccionario sirve como
entrada limpia para una evaluacion posterior.

## Nota sobre pseudomonas.com

No se usa: responde 403 a `urllib` (proteccion de bot) y saltarlo exigiria un
navegador headless, fuera del alcance de este script de biblioteca estandar.