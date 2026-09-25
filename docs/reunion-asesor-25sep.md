# Reunión con el asesor — 25 de septiembre de 2026

Guión de estado. Cada cifra dice de dónde sale: un archivo versionado, un
cuerpo de commit, un comando corrido la noche del 24 o una medición de esa
misma sesión. Ninguna es de memoria.

Verificado el 24 de septiembre por la noche: `git status` limpio en
`base-operones` (e6e0e94, publicada y al día con `origin`); suites
`python -m unittest discover` → 541 OK (1 omitida) y
`python -m unittest discover etapa2` → 524 OK (3 omitidas).

---

## 1. El estado en una frase

El bronce v1 con operones está cerrado en `main` desde el 17 de septiembre;
la base de operones está construida, probada y curada con dos de las cuatro
fuentes (ODB y BioCyc), y lo que sigue depende de siete decisiones del asesor
y de dos archivos que sólo una persona puede conseguir.

---

## 2. Lo que se entrega hoy

### A. Bronce v1 con operones — `main`, cerrado el 17-sep

- **Punto 31 del PLAN, hecho** (corrida 2): 7 136 menciones de operón, 363
  operones distintos, 3 603 oraciones candidatas afectadas (12,1 %), 393 con
  operón como blanco. La expansión operón → genes vive en un solo sitio,
  `grn_bronce/operones.py`. Cobertura contra el patrón de oro sin moverse:
  149/176 = 84,7 %. *(bitácora 17-sep)*
- **Punto 32, limpieza y corte hechos**: corrida 3 recuperó 329 menciones por
  mayúsculas y 2 243 por guiones, y `regulation` salió de funciones a
  `contexto_regulatorio.csv`; corrida 4 partió `virulence` en `_molecule` /
  `_phenotype` / `_general` y amplió `infection_type` a 38 términos.
  Decisión cerrada con el asesor: las bombas de expulsión no entran como
  función. *(bitácora 17-sep, PROCEDENCIA.md)*
- Identificador en versión 4. Exportaciones de la corrida 4:
  `salidas/bronce_identificacion_20260917_*.csv` (495 382 menciones, 29 659
  candidatas) y el `.xlsx` de la corrida 4.

### B. Base de operones — paquete `grn_operones/`, rama `base-operones`

**Qué es.** Un paquete nuevo, aparte de `grn_bronce/operones.py`, con dos
capas: *bronze* (lo que cada fuente dijo, byte a byte, con sha256) y *silver*
(una fila por conjunto de genes, normalizada a locus tag, con nivel de
evidencia). Cinco tablas en la misma base SQLite, con clave natural y
`ON CONFLICT`. CLI: `python -m grn_operones.cli extraer | reparsear | curar |
exportar | estado`.

**Qué hay dentro** (`estado`, 24-sep 22:40):

```
descargas crudas registradas   5      biocyc 2, odb 3
filas en bronce                3 873  biocyc 3 774, odb 99
operones curados               3 742
para revisar                   89
Sin datos todavía: pgd, cdbprom
```

**La cifra de cabecera** (`salidas/operones_20260924_silver.csv`, 3 742 filas):

| | |
|---|---|
| unidades de transcripción | **3 742** |
| policistrónicas (≥ 2 genes) | **1 082** |
| monocistrónicas | 2 660 |
| nivel `conocido` / `curado` / `predicho` | **63 / 5 / 3 674** |
| con dos o más fuentes | 17 |
| con PMID | 90 |

Y los 89 para revisar (`operones_20260924_conflictos.csv`): 39 con genes no
consecutivos en el genoma, 16 `pendiente_revision`, 16 `comp_con_cita`,
14 sin evidencia, 10 con un nombre que no llegó a locus tag, 9
`locus_sufijo_excluido`, 6 con gen huérfano.

**Compatibilidad con el catálogo del bronce**: de los 33 operones de ODB,
31 son compatibles con `operones_pao1.tsv` (17 idénticos) y 2 están
ausentes: **94 %**. *(commit 3a25480; antes de arreglar la clave por orden
salían 4 idénticos y 12 ausentes)*

**Cómo se hizo cada fuente.**

- *ODB v4*: el sitio es una aplicación JavaScript (`GET /known` devuelve 689
  bytes sin datos); se usa su volcado de texto plano. 33 operones.
- *BioCyc / PseudoCyc*: por la API oficial (`websvc.biocyc.org/xmlquery`,
  BioVelo), con las credenciales del usuario en su propia terminal; el
  código nunca las ve. 3 774 TUs, con sus `<pubmed-id>` y códigos de
  evidencia. Dos extracciones anteriores quedaron incompletas y `curar` las
  ignora por diseño.
- *Nivel de evidencia por TU*: `conocido` si trae código experimental,
  `curado` si trae cita curada, `predicho` para EV-COMP*. La ausencia de
  repetición de un PMID no es evidencia de lo contrario: los EV-COMP* son
  predichos por ontología, no por conteo de citas.
- *Reglas C1–C6 y restricciones R1–R5 del encargo*: implementadas en
  `curar.py` y `red.py` (pausa de 2 s, un User-Agent con correo de contacto,
  sin reintentar 403, sin navegador, sin `--email` por línea de comandos).
- **82 pruebas propias**, sin red, con fixtures locales.

**Lista para el asesor**: `salidas/operones_pendiente_revision_20260924.csv`,
22 filas = 16 operones con 21 PMIDs distintos, enriquecida con título, año,
revista y tipo de artículo desde PubMed (5 peticiones: 16 de los 21 ya
estaban en el corpus).

**Parser de CDBProm e ingesta por archivo local**: listos (`extraer --archivo`),
verificados con un volcado sintético que luego se borró. CDBProm no crea
operones: marca `promotor_cdbprom` en el operón cuyo primer gen tiene promotor.

### C. La regex de locus tag — medida, planificada, esperando decisión

- La clave primaria del pipeline es `^PA\d{4}(\.\d)?$` y deja fuera **58 de
  los 5 697** locus tags del GFF de RefSeq. *(medido el 24-sep sobre el GFF
  versionado)*
- De los 58, 57 son `protein_coding` sin símbolo. **Uno tiene símbolo:
  `crcZ` (PA4726.11)**, el sRNA que secuestra a Crc, con 399 menciones en 35
  documentos del corpus. *(construir_diccionario.py:150)*
- La regex que se había anotado (`^PA\d{4}[a-z]?(\.\d)?$`) recupera 57 y
  **deja fuera justo a `crcZ`**, porque su exclusión no es la letra sino los
  dos dígitos tras el punto. Con `\d+` se recuperan los 58:
  `^PA\d{4}[a-z]?(\.\d+)?$` → 5 697 / 5 697.
- Defecto vigente que el cambio corrige de paso: la variante «en texto» sobre
  `PA4726.11` extrae `PA4726`, que es **`cbrB`**, el regulador de `crcZ`. Hoy
  un texto que nombra a `crcZ` por locus tag devuelve a su regulador.
- Paso 0 verificado el 24-sep: `construir_diccionario.py --sin-red` reproduce
  el diccionario versionado byte a byte. Cuando se apruebe, un diff de 58
  líneas significará 58 genes y no ruido.

---

## 3. Lo que falta y por qué

- **Pseudomonas Genome DB**: 0 extracciones. `pseudomonas.com` responde 403 a
  peticiones automáticas y nadie ha localizado la liga del archivo bulk. La
  vía está lista (`PGD_OPERONES_URL` o `extraer --fuente pgd --archivo`);
  falta el archivo. No se raspa ni se evade el 403: es dependencia y es evasión.
- **CDBProm**: 0 extracciones; el volcado real lo tiene el asesor. Sin él la
  regla C5 (promotor aguas arriba) no se ha ejercitado con datos reales.
- **Documentación**: la bitácora no tiene entrada del 18 al 24; PLAN.md,
  CLAUDE.md y README no mencionan `grn_operones`; la sección «Estado actual»
  de `CONTEXTO_OPERONES.md` describe un prototipo que ya no existe. El trabajo
  vive en los cuerpos de commit.
- **La lista de revisión no es reproducible**: la produjo un script de sesión,
  no código versionado. Conviene volverla `exportar --pendientes`.
- **Desviación de la tarea 4 del encargo**: pedía `grn_etl/operones/` con
  subcomando en el `cli.py` de la raíz; se hizo paquete aparte con CLI propio.
  La razón: un directorio `grn_bronce/operones/` taparía el módulo
  `operones.py`, y `grn_etl/` está cerrado. No hay acuerdo registrado.
- **Tarea 6 parcial**: no hay fixture ni prueba de `parsear_odb`; el parser de
  ODB sólo se ha probado contra el volcado real.
- **Guarda de contaminación**: vigila `etapa2`, `grn_bronce` y `grn_comun`;
  no vigila `grn_operones`. La restricción R5 se cumple hoy, pero sin prueba.
- **Sinónimos**: el diccionario trae 224 sinónimos en 5 642 filas; nombres
  históricos como `nalB` (por `mexR`) no mapean. La capa desde NCBI Gene
  está diseñada (tres condiciones acordadas) y no empezada.
- **Puntos 33, 34 y 35 del PLAN** sin avance desde el 17-sep: conectar el
  bronce con silver vía BioBERT; los 103 operones del corpus fuera del
  catálogo; el mapeo PA14 → PAO1.
- **Fusión a `main`**: la rama está lista (sería fast-forward) y sin fusionar.

---

## 4. Las siete decisiones que se piden

1. **Regex de locus tag.** ¿Se aprueba `^PA\d{4}[a-z]?(\.\d+)?$`, con la
   excepción acotada a la congelación de `etapa2/` (cuatro líneas de regex y
   un mensaje de error)? Coste: regenerar el diccionario (5 642 → 5 700
   filas), corrida nueva del paso 1 y recalcular 95,1 % / 84,7 % / 44,0 %.
   Va en commit propio con el antes y el después.
2. **Las 16 TUs de BioCyc con cita pero sin código de evidencia**
   (`pendiente_revision`, 21 PMIDs). ¿`conocido` o `predicho`? El CSV trae
   título y tipo de artículo de cada PMID para decidir sin abrir BioCyc.
3. **Qué fuentes de operones incorpora la base curada del laboratorio.** Si
   `GRN_experimental` ya usó ODB o BioCyc, hay fuga hacia la validación. Con
   la respuesta se monta la lista de fuentes vetadas y su guarda.
4. **El volcado de CDBProm.** El formato ya está soportado (10 líneas de
   encabezado, 10 columnas, cadena D/R, score ≥ 0,5). Dos discrepancias del
   perfil quedan anotadas: el encabezado dice F/R y el volcado escribe D/R;
   las coordenadas abarcan 80 pb y la secuencia mide 60 nt.
5. **Pseudomonas Genome DB.** ¿Conoce la liga del bulk? Si no, ¿vale bajarlo a
   mano en el navegador e ingestarlo con `--archivo`?
6. **Validar tres decisiones tomadas por cuenta propia**: el modelo
   bronze/silver con cinco tablas; el paquete `grn_operones/` en vez de
   `grn_etl/operones/`; normalizar con `genes_pao1.tsv` en vez de la
   anotación de pseudomonas.com (que no se puede descargar).
7. **Punto 34.** Criterio para los 103 operones del corpus ausentes del
   catálogo (`cyaAB`, `exoSTY`, `rsmZY`, `phzMS`, `lasRI`, `sodAB`…), listados
   en `salidas/operones_corrida2_20260917.csv`.

---

## 5. Qué decir y qué no

- No «las cuatro fuentes están integradas». Sí: «dos de cuatro con datos
  reales; las otras dos tienen la vía lista y esperan un archivo».
- No «3 742 operones curados» a secas. Sí: «3 742 unidades de transcripción,
  1 082 policistrónicas, 68 con evidencia experimental o de literatura; el
  98 % es predicción de BioCyc».
- No «17 confirmados por dos fuentes independientes» sin matizar: ODB y
  BioCyc sí lo son; PGD y BioCyc comparten el motor de Pathway Tools.
- No «re-correr no vuelve a descargar»: cada `extraer` es una foto nueva por
  fecha, por diseño. Lo idempotente es silver (`ON CONFLICT(clave_genes)`) y
  `reparsear`, que no sale a la red.
- No «el parser de CDBProm está probado»: sólo con datos sintéticos.
- No «pseudomonas.com no tiene descarga». Sí: «responde 403 a peticiones
  automáticas y no hemos localizado la liga del bulk».
- La verificación de hebra usa un GFF en cache no versionado: aquí se hizo;
  en un clon limpio la fila queda `hebra_no_verificada`. No presentarla como
  propiedad del pipeline.
- La base **convive** con `operones_pao1.tsv`; no lo sustituye todavía.
- Si sale el clasificador: 86,5 % agregado pero **36,6 % por oración**; se
  cita el segundo, siempre con su línea base. Precisión del paso 1: 44,0 %
  (22/50, IC 95 % [31,2, 57,7]), aceptada como línea base el 11-sep.
- Si preguntan por las pruebas omitidas: 1 en la raíz
  (`grn_comun.test_procedencia…test_el_diccionario_honesto_pasa`, necesita
  archivos reales que no están en el clon) y 3 en `etapa2/test_clasificar`
  (`torch` y `transformers` no instalados aquí, por diseño).

---

## 6. Siguientes pasos propuestos, en orden

1. Regex de locus tag, en cuanto haya visto bueno (plan escrito, paso 0 hecho).
2. Capa de sinónimos desde NCBI Gene `gene_info`, con `sinonimos_manual.tsv`
   para lo curado a mano (autor, fecha, PMID).
3. Guarda de contaminación por procedencia, con la lista de fuentes vetadas
   que salga de la decisión 3.
4. PGD y CDBProm en cuanto lleguen los archivos: `extraer --archivo`, `curar`,
   y volver a medir la compatibilidad.
5. Documentación (bitácora, PLAN, CLAUDE, CONTEXTO) y fusión de
   `base-operones` a `main`.
