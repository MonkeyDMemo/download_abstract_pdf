# El catálogo de operones de PAO1: cómo se hizo

Para quien tenga que mantener, reproducir o explicar el catálogo de operones
de *Pseudomonas aeruginosa* PAO1 que arma `grn_operones/`. El documento cubre
cuatro cosas:
- de dónde sale cada fuente y por qué por esa vía;
- qué se tomó de cada una y qué no;
- cómo se construye el catálogo;
- qué significa cada columna.

Las cifras son las de la corrida del 27 de septiembre de 2026. El porqué de
las decisiones de diseño está en `docs/decisiones.md`, y los hechos medidos en
`docs/hallazgos.md`. Aquí se cita el código con `archivo:función` y no con
número de línea, porque las líneas se mueven.

---

## 1. Qué es y para qué

Son **cuatro fuentes con dos papeles distintos**:

| fuente | aporta | papel en el catálogo |
|---|---|---|
| ODB v4 (operondb.jp) | operones conocidos, de literatura | crea operones |
| BioCyc / PseudoCyc | unidades de transcripción, curadas y predichas | crea operones |
| Pseudomonas Genome DB | predicciones de DOOR y operones de literatura de PseudoCAP | crea operones |
| CDBProm (IIMAS, UNAM) | promotores predichos | **marca** operones, no los crea |

CDBProm da un promotor frente a un gen, no un operón. Si contara como fuente
de operones, fabricaría 1 950 «operones» de un gen que nadie ha visto
transcribirse, o haría que un operón con promotor pareciera confirmado por
dos fuentes. Por eso tiene columnas propias y no entra en «fuentes» ni en
`n_fuentes`.

Salen **tres productos**:
- **El catálogo maestro** (`python -m grn_operones.cli catalogo`): el archivo
  de referencia para leer. Tiene una fila por operón, con sus genes, su
  evidencia, el ID que le da cada fuente y el promotor.
- **La base técnica** (`exportar`): silver, conflictos y la vista de la página
  de PGD.
- **El recurso del paso 1** (`catalogo --paso1` →
  `grn_bronce/recursos/operones_base.tsv`): con él, cada oración candidata del
  bronce dice si tiene operones y cuáles. No cambia lo que el bronce detecta.

| cifra (27-sep) | valor |
|---|---|
| operones en el catálogo | 4 250 (1 576 de más de un gen) |
| conocidos / curados / predichos | 145 / 3 / 4 102 (96.5 % predicción) |
| con dos o más fuentes | 738 (717 de ellos BioCyc + PGD) |
| con promotor CDBProm | 1 574 |
| sin nombre | 2 992 (los de BioCyc: su parser no toma el nombre) |
| para revisar a mano | 117 |

**Casi todo el catálogo es predicción.** Hay que leer el nivel de evidencia
antes de citar un operón.

---

## 2. Reglas comunes a las cuatro fuentes

- **Organismo:** taxid `208964`, BioCyc orgid `PAER208964`, genoma
  `NC_002516.2`, locus tags `PA0001`–`PA5570`.
- **Acceso por red** (`grn_operones/red.py`):
  - pausa mínima de 2 s entre peticiones;
  - 4 intentos con retroceso exponencial (2, 4 y 8 s, con tope de 20 s);
  - tiempo de espera por petición de 120 s por omisión: 300 s para ODB y
    600 s para BioCyc, PGD y CDBProm;
  - User-Agent identificado con el correo de contacto (`NCBI_EMAIL` o
    `.correo`, nunca un flag);
  - un 401, 403, 404, 422 o 451 es «la fuente dijo que no»: no se reintenta;
  - nunca se rota el User-Agent, se ejecuta JavaScript ni se usa un
    navegador.
- **Términos de uso:** se respeta `robots.txt`. BioCyc y CDBProm prohíben el
  acceso automatizado a sus páginas, así que de BioCyc se usa su API oficial y
  de CDBProm su archivo de descarga. Las credenciales van solo por entorno
  (`BIOCYC_EMAIL`, `BIOCYC_PASSWORD`).
- **Crudo primero, parser después.** Cada archivo se guarda tal cual en
  `<GRN_DATOS>/operones_crudo/<fuente>/<fecha>/` con su sha256, antes de
  leerlo. Así, corregir un parser no cuesta una descarga
  (`reparsear --fuente X`).
- **Los parsers exigen su contrato** (encabezado, columnas, valores de hebra)
  y, si no se cumple, lanzan `FormatoDesconocido` en vez de leer columnas
  corridas. BioCyc todavía no lo hace del todo: un XML sin TUs da cero filas.

---

## 3. Las cuatro fuentes, una por una

### 3.1 ODB v4 — operones conocidos

**Qué es.** Operon DataBase v4 (operondb.jp) reúne operones conocidos de
muchos organismos, cada uno con el artículo que lo sostiene.

**Por qué esta vía.** El encargo apuntaba a la tabla paginada
`operondb.jp/known?species=208964&p=N`. No sirve: **ODB v4 es una aplicación de
JavaScript** y cualquier ruta del sitio, `robots.txt` incluido, devuelve el
mismo esqueleto de 689 bytes sin un solo dato. Un parser sobre ese HTML habría
devuelto cero filas para siempre. Se usa el volcado de texto que el propio
sitio ofrece: `https://operondb.jp/download/known_operon.download.txt`, en una
sola petición y sin cuenta.

**Qué se bajó.**
- Archivo: `known_operon.download.txt`, 538 404 bytes, descargado el
  18-sep-2026.
- Contenido: 9 480 líneas, que son el encabezado y 9 479 filas de todos los
  organismos. **33 son de PAO1.**

**Formato.** TSV con encabezado exacto `koid org name op definition source`
(`fuentes.py:parsear_odb`).

| campo de ODB | en el bronce | nota |
|---|---|---|
| `koid` | `id_fuente` | p. ej. `KO07643` |
| `org` | no se toma | solo filtra: se quedan las filas con `org = 208964` |
| `name` | `registro_raw.name` | es el nombre del **operón**, no de sus genes |
| `op` | `locus_tags` | de coma a `\|` |
| `definition` | `registro_raw.definition` | si no está vacío |
| `source` | `pmid` | de espacios a `;` |
| — | `tipo_evidencia = literatura` | constante: ODB es literatura por construcción |

**Resultado.** 33 filas por extracción; 33 unidades del catálogo con respaldo
de ODB. 23 de las 33 coinciden exactamente en genes con el catálogo del paso 1
(`operones_pao1.tsv`), y 17 de ellas también en el nombre.

### 3.2 BioCyc / PseudoCyc — unidades de transcripción

**Qué es.** La base de Pathway Tools para PAO1 (`PAER208964`). Trae unidades
de transcripción (TU), unas pocas con respaldo experimental y la gran mayoría
predichas por el algoritmo de Pathway Tools.

**Por qué esta vía.** BioCyc prohíbe el acceso automatizado a sus páginas, y
por eso la URL del encargo (`biocyc.org/tu?orgid=PAER208964&id=…`) no se usa.
Se usa la **API oficial**:
1. se entra con `POST https://websvc.biocyc.org/credentials/login/` y las
   credenciales del entorno;
2. se hacen dos consultas BioVelo a `https://websvc.biocyc.org/xmlquery` con
   `detail=full`:
   - `[x:x<-PAER208964^^Transcription-Units]` → `tus.xml`;
   - `[x:x<-PAER208964^^Genes]` → `genes.xml`.

La URL que se registra lleva los parámetros. Con el endpoint pelado, la
segunda consulta se confundía con la primera y su archivo quedaba sin
procedencia.

**Qué se bajó.**
- Fecha: 18-sep-2026. Pathway Tools versión 30.0.
- `tus.xml`: 2 475 121 bytes, 3 787 TUs.
- `genes.xml`: 9 079 922 bytes, 5 692 genes.

**Formato.** XML. Las TUs nombran sus genes con `frameid` internos (`G-1`),
que no significan nada fuera de BioCyc. **El puente es `genes.xml`**: cada
`Gene@frameid` trae su locus tag en `accession-1`.

| elemento de BioCyc | en el bronce | nota |
|---|---|---|
| `Transcription-Unit@frameid` | `id_fuente` | p. ej. `TU1FZ6-520` |
| `component/Gene@frameid` | `locus_tags` | vía `frameid → accession-1`, en el orden del XML |
| frameids sin locus tag | `registro_raw.sin_mapear` | se marcan `gen_huerfano` (6 TUs) |
| todos los frameids | `registro_raw.frameids` | |
| `Evidence-Code@frameid` | `tipo_evidencia` | conjunto ordenado, unido con `;`, de **todo** el subárbol de la TU, incluido su promotor |
| `pubmed-id` | `pmid` | de **todo** el subárbol de la TU, no de los `dblink`: 64 TUs con PMID (77 PMIDs). Solo 41 lo traen en su `citation`; 16 lo traen únicamente por su `component/Promoter` (ver §8) |
| `common-name` | **no se toma** | lo traen 94 TUs (`mexEF-oprN`, `carAB`, `fleSR`…). Pendiente |
| el promotor como entidad, dirección, comentarios, `dblink` | **no se toman** | aunque las citas y los códigos de evidencia del promotor sí entran, como se dice arriba |

**Resultado.**
- 3 787 TUs en el XML y 3 774 filas de bronce. Las 13 descartadas son todas
  de un solo gen sin locus tag resoluble, solo EV-COMP y sin PMID.
- 3 726 unidades del catálogo con respaldo de BioCyc.
- Reparto de la evidencia sobre las 3 774 del bronce
  (`curar.py:nivel_de_fila`): EV-EXP con PMID 32; EV-EXP sin PMID 7; EV-COMP
  con cita 16; solo EV-COMP 3 689; sin código 30.
- De las 30 sin código, 16 traen cita y quedan `pendiente_revision`, para que
  decida el asesor.

### 3.3 Pseudomonas Genome DB — lo que muestra la página, sin rasparla

**Qué se pedía.** Los operones de PAO1 tal como los muestra la vista de cada
gen en pseudomonas.com (`feature/show/?id=109783&view=operons`). La vista
trae:
- el nombre del operón;
- una tabla de sus genes: locus tag, nombre, descripción, inicio, fin, hebra y
  tipo;
- la evidencia;
- la referencia.

**Por qué no se sacó del sitio.** Se intentó tres veces, y las tres quedaron
medidas:

1. **20 de agosto y 3 de septiembre de 2026.** `urllib` recibe 403, incluso
   con un User-Agent de navegador. Es protección contra bots, no un filtro de
   cabecera.
2. **27 de septiembre, con más detalle.** Una petición por URL, 2 s entre
   cada una, sin nada que imite un navegador, a nueve rutas:
   - `robots.txt`;
   - `/strain/download`;
   - los archivos de `/downloads/` (CSV, GFF y ortólogos de PAO1, y
     `strain_summary.txt`);
   - el export CSV de `feature/list`;
   - la vista de operones;
   - `/downloads/`.

   **Las nueve contestaron igual:** 403, `Server: cloudflare`,
   `Cf-Mitigated: challenge` y una página «Just a moment...». Todo el host está
   detrás de un desafío administrado de Cloudflare, que solo pasa un
   navegador que ejecute JavaScript. Una ruta inventada contestó lo mismo,
   así que **el 403 no dice si una URL existe**. Lo que existe se supo por
   capturas del Internet Archive.
3. **La página de descargas no ofrece operones.** La captura de Wayback del
   11-feb-2025 (release 22.1, del 6-oct-2023) ofrece por cepa FASTA,
   anotación en CSV/GBK/GFF3/GTF y ortólogos; la palabra «operon» no aparece.
   El índice de Wayback no tiene ninguna ruta de `/downloads/` con «operon»,
   y el GFF de PAO1 archivado no trae rasgos de operón. **Los operones solo
   existen como la vista HTML de cada gen.**

Además, el **`robots.txt`** (captura de agosto de 2025) prohíbe la
recolección automatizada sin permiso escrito del operador.

Raspar 5 700 páginas exigiría pasar el desafío. Eso es evasión, y está fuera
de las reglas del proyecto (CLAUDE.md: «no implementar nada que evada muros
de pago ni controles de acceso»). No se hizo.

**Cómo se llegó a los mismos datos por otra vía:**
1. **Qué alimenta la vista.** Una captura de 2024 de la página de operones de
   `oprM` enseña dos orígenes:
   - predicciones de **DOOR** (Database of Prokaryotic Operons; Mao et al.
     2009, PMID 18988623), con evidencia «Computationally-predicted»;
   - operones de literatura de **PseudoCAP**, cada uno con su artículo.
2. **Quién recibió esos datos en bloque.** Lee et al. 2023 (*mSystems*,
   doi:10.1128/msystems.00342-22) dicen en sus Métodos: «the operon data were
   provided by Geoff Winsor [curador de PGD] and include computationally
   predicted annotations from DOOR as well as curated annotations from
   PseudoCAP».
3. **Dónde quedaron.** El laboratorio Greene publicó esa tabla, con licencia
   BSD-3, en `greenelab/core-accessory-interactome`,
   `data/metadata/PAO1-operons-2021-07-19.csv`.
4. **Fijada a un commit.** La URL que usa el código (`fuentes.URL_PGD`) va al
   commit `25539b82d51aa088c9e2f241a71ea1cc996fddae`. Una rama se mueve y un
   commit no: los bytes que se bajen en un año son los mismos que se
   revisaron.

**La comprobación de que es la misma información.** Se comparó contra la
captura de la página de `metG` que mandó el usuario. La tabla trae:
- `operon-714` y `metG-PA3483`;
- PA3482 (`metG`), 3895324–3897357, hebra +;
- PA3483, 3897391–3898191, hebra +;
- DOOR y PMID 18988623.

**Coincide campo por campo.** Lo único que la tabla no trae es la descripción
y el tipo de cada gen. Esos salen de RefSeq (`genes_pao1.tsv`), y el
encabezado lo dice, porque PGD redacta distinto («methionyl-tRNA synthetase»
frente a «methionine--tRNA ligase»).

**Por qué no se usó DOOR directo.** DOOR ya no está en línea: sus direcciones
de 2026 no contestan o dan 404. Sus predicciones para PAO1 sobreviven en esta
exportación.

**Qué se bajó.**
- Archivo: `PAO1-operons-2021-07-19.csv`, 332 301 bytes, descargado el
  27-sep-2026.
- Contenido: 3 816 filas (una por gen) en **1 290 operones**:
  - 1 165 de DOOR (3 517 filas);
  - 125 de PseudoCAP (299 filas, 75 PMIDs; 65 de ellos de un solo gen, contando
    `oprE`, que repite PA0291 una vez por artículo).

**Formato.** CSV entrecomillado con encabezado exacto `operon-id, operon_name,
locus_tag, start, end, strand, gene_name, source_database, pmid`. El parser
(`fuentes.py:parsear_pgd`) exige ese encabezado, hebra `1`/`-1`, origen
`DOOR` o `PseudoCAP` y coordenadas enteras, y acepta un BOM al frente.

| campo de PGD | en el bronce | nota |
|---|---|---|
| `operon-id` | `id_fuente` | se agrupa por id: en 103 operones las filas no van juntas |
| `locus_tag` | `locus_tags` | sin repetir (3 operones de PseudoCAP repiten cada gen por artículo); ordenados por `start` e invertidos en hebra −, o sea en orden de transcripción |
| `strand` | `cadena` | `+`/`-` |
| `source_database` | `tipo_evidencia` | `DOOR` o `PseudoCAP` |
| `pmid` de PseudoCAP | `pmid` | unidos con `;` |
| `pmid` de DOOR | `registro_raw.referencia_metodo` | siempre 18988623, el artículo del **método**. En `pmid` se leería como evidencia del operón |
| `operon_name` | `registro_raw.name` | |
| por gen: `locus_tag`, `gene_name`, `start`, `end` | `registro_raw.genes[]` | la vista de la página se reconstruye de aquí |

**Resultado.**
- 1 290 filas de bronce; 1 243 unidades con respaldo de PGD, 508 solo de PGD.
- Faltan 16 locus tags de PGD en `genes_pao1.tsv`; la cobertura de mapeo es
  del 99.6 %.
- `exportar` escribe además `operones_<día>_pgd.csv`: la vista de la página
  para los 1 290 operones, en 3 808 filas.

**Límite y cómo mejorarlo.** Es una foto del **19 de julio de 2021**; el
release vigente de PGD (22.1) es de 2023. La versión actual se pide por
correo a pseudocap-mail@sfu.ca o gwinsor@sfu.ca, que es como la consiguió el
laboratorio Greene, y entra con:

```bash
python -m grn_operones.cli extraer --fuente pgd --archivo <tabla_nueva.csv>
```

**Citar:** Winsor et al. 2016 (PGD, doi:10.1093/nar/gkv1227), Mao et al. 2009
(DOOR) y Lee et al. 2023.

### 3.4 CDBProm — promotores predichos

**Qué es.** Base de promotores predichos con XGBoost, del IIMAS (UNAM). Da
una predicción de promotor frente a cada gen.

**Por qué esta vía.** El sitio (`aw.iimas.unam.mx/cdbprom/search2.php`)
prohíbe el acceso automatizado a sus páginas, pero ofrece la **descarga del
archivo por organismo**. Una persona lo bajó el 18-sep-2026 y se ingirió el
25-sep:

```bash
python -m grn_operones.cli extraer --fuente cdbprom --archivo <archivo>
```

La procedencia queda como `archivo-local:<nombre>`, que dice que no es una
URL que se pueda volver a pedir.

**Qué se bajó.**
- Archivo: `Pseudomonas_aeruginosa_GCF_000006765.1_ASM676v1_upstream.txt`,
  689 857 bytes.
- Contenido: 10 líneas de encabezado en prosa, 2 en blanco y 1 972 filas de
  datos.

**Formato.** Las 10 líneas de encabezado se saltan por conteo; los datos
vienen en 10 columnas separadas por tabulador. Los nombres de columna son
nuestros, porque el encabezado es prosa.

| columna | en el bronce | nota |
|---|---|---|
| locus tag (3ª) | `id_fuente` y `locus_tags` | **se rechazan 22** con sufijo de letra (`PA0103a`…`PA5440a`); el diccionario no los tiene |
| cadena `D`/`R` | `cadena` `+`/`-` | el original, en `registro_raw.cadena_original` |
| inicio, fin, score, etiqueta, secuencia, anotación | `registro_raw.*` | tal cual, sin interpretar |
| — | `registro_raw.largo_rango`, `largo_secuencia` | calculados, para dejar constancia de la discrepancia |
| NCBI id, organismo | no se toman | son el mismo para todas las filas |
| — | `tipo_evidencia = promotor_predicho`, `pmid` vacío | |

**Discrepancias del archivo, anotadas y no «corregidas»:**
- El encabezado dice que la cadena es F/R y los datos traen D/R (982 D y
  990 R). Se acepta `D` como directa y **se rechaza cualquier otro valor**:
  una cadena mal leída pone el promotor frente al gen equivocado.
- `fin − inicio` da 80 en todas las filas, así que el rango inclusivo guardado
  en `largo_rango` es de 81 pb. La secuencia mide 60 nt, y el encabezado dice
  «(-60 to +1)». No se resuelve a ojo.
- Hay un promotor por locus como máximo. Si llegaran dos, se queda el de mayor
  score; en el archivo real no hay duplicados. El score mínimo es 0.5.

**Resultado.** 1 950 promotores en el bronce, todos de genes que están en
`genes_pao1.tsv`. **CDBProm no crea operones:** marca `promotor_cdbprom` en el
operón cuyo **primer gen transcrito** tiene promotor (1 574 operones).

---

## 4. Cómo se construye el catálogo

```bash
python -m grn_operones.cli extraer --fuente odb       # o biocyc, pgd;
                                                      # cdbprom con --archivo
python -m grn_operones.cli curar                      # bronce → silver
python -m grn_operones.cli catalogo [--paso1]         # el catálogo maestro
python -m grn_operones.cli exportar                   # silver, conflictos, vista PGD
python -m grn_operones.cli estado                     # qué hay
```

### 4.1 `extraer`: una foto por fuente
1. Se abre la extracción **antes** de bajar nada (`completa = 0`).
2. Se guarda cada archivo con url, ruta, bytes, sha256 y fecha.
3. Se parsea y se inserta en el bronce. El bronce **solo inserta**; una
   versión nueva convive con la anterior. La única excepción es `reparsear`:
   borra y vuelve a insertar las filas de la última extracción completa de esa
   fuente (mismos bytes, parser corregido). Las extracciones anteriores no se
   tocan.
4. Se cierra con `completa = 1`. Sin archivos, la extracción queda
   incompleta; un parseo fallido la cierra completa con 0 filas.

Detalles:
- `--archivo` y `--url` exigen `--fuente`, porque con `todo` el mismo archivo
  entraría como si fuera de cada fuente.
- PGD no se vuelve a bajar mientras la foto vigente sirva (`foto_sana`: tiene
  filas y su crudo sigue en disco con su huella). Así no se revierte una tabla
  más nueva que haya entrado por `--archivo`.

### 4.2 La foto vigente
El catálogo se cura sobre **la última extracción completa de cada fuente**
(`bronze_vigente`). Una fuente sin ninguna extracción completa queda fuera y
se nombra; los operones que una fuente retira entre fotos se reportan.

### 4.3 `curar`: de bronce a silver
Silver se rehace desde cero en cada corrida.

1. **Normalizar a locus tag** con `grn_bronce/recursos/genes_pao1.tsv` (5 642
   genes, con símbolos y alias), no con la anotación de pseudomonas.com, que
   está tras el mismo Cloudflare. Un nombre de parálogo sin número (`phzA`) se
   reporta como ambiguo y no se resuelve.
2. **Clave del operón:** sus locus tags ordenados, unidos con `|`. Dos fuentes
   que listan los mismos genes en distinto sentido son el mismo operón.
   **Límite:** dos unidades con los mismos genes y distinto inicio de
   transcripción colapsan en una.
3. **Alternativas:** una unidad cuyo conjunto de genes está contenido en el de
   otra se marca `es_alternativa`; no se fusiona.
4. **Adyacencia:** los números de locus tienen que ir de uno en uno.
   **Límite:** el sufijo `.N` se ignora, así que `PA0668.1|PA0668.2` cuenta
   como paso 0 y sale no adyacente. 38 de los 55 no adyacentes tienen algún
   locus `.N`; cuántos son falsos positivos no se ha revisado uno por uno.
5. **Hebra:** sale del GFF de RefSeq. Primero se busca el caché local
   (`datos_etapa2/cache_diccionario/`, ignorado por git) y, si falta, la
   copia versionada (`construir_diccionario/diccionario_independiente/cache/
   refseq.gff.gz`). Solo si faltan las dos la fila se marca
   `hebra_no_verificada`.
6. **Nivel de evidencia**, por fila y no por fuente:
   - BioCyc: EV-EXP con PMID → conocido; EV-EXP sin PMID → curado; el resto →
     predicho, con marca si trae cita (`comp_con_cita`) o no declara código
     (`sin_evidencia`, `pendiente_revision`);
   - ODB y PGD-PseudoCAP: conocido con PMID, curado sin él;
   - PGD-DOOR: predicho;
   - un operón toma el mejor nivel de sus fuentes.
7. **`n_fuentes`** cuenta fuentes distintas, **no confirmaciones
   independientes**. DOOR y Pathway Tools son motores distintos, pero ambos
   parten de la distancia intergénica. Además, ODB, BioCyc y PseudoCAP pueden
   citar el mismo artículo.
8. **Promotor:** el primer gen transcrito es el de número menor en hebra + y
   el mayor en −. Hay que calcularlo porque BioCyc lista al revés en las dos
   hebras, y usar el primero de la lista ponía el gen equivocado en 515 de
   1 082 operones.
9. **Nombre:** el más corto que dé alguna fuente.

### 4.4 Las marcas de «para revisar»

| marca | significado |
|---|---|
| `no_adyacente` | los genes no son consecutivos en el genoma |
| `hebras_distintas` | los genes no comparten hebra, así que no comparten promotor |
| `hebra_no_verificada` | sin GFF en caché, la hebra no se comprobó |
| `genes_sin_resolver` | algún nombre no se pudo llevar a locus tag |
| `locus_sufijo_excluido` | un locus con sufijo de letra no está en el diccionario |
| `nombre_ambiguo` | un nombre corresponde a varios parálogos |
| `gen_huerfano` | BioCyc cita un gen que su propia consulta no devolvió |
| `pendiente_revision` | BioCyc no declara método y trae un artículo |
| `comp_con_cita` | predicción con cita (suele ser la del método) |
| `sin_evidencia` | BioCyc no declara ningún código |

---

## 5. Modelo de datos

```
fuente externa (ODB, BioCyc, PGD, CDBProm)
   │  extraer
   ▼
operones_extracciones ──< operones_descargas ──< operones_bronze
 (una foto por fuente)     (un archivo, con        (lo que dijo la fuente,
                            su sha256)               partido en campos)
                                                        │  curar (foto vigente)
                                                        ▼
                               operones_silver ──< operones_silver_fuente
                               (un operón por          (qué registro de cada
                                conjunto de genes)       fuente lo respalda)
                                   │
            ┌──────────────────────┼─────────────────────────┐
            ▼                      ▼                         ▼
   catálogo maestro        exportar: silver,       operones_base.tsv
   (csv, xlsx, léame)      conflictos, vista PGD   (recurso del paso 1)
```

`──<` quiere decir «uno a muchos». La fuente vive **solo** en la extracción:
el bronce la hereda por su descarga y no puede contradecirla.

---

## 6. Diccionario de datos

### 6.1 Tablas (`grn_operones/db.py`)

**`operones_extracciones`**: una foto de una fuente.

| columna | tipo | significado |
|---|---|---|
| `id` | INTEGER PK | |
| `fuente` | TEXT NOT NULL | `odb`, `biocyc`, `pgd`, `cdbprom` |
| `inicio` | TEXT NOT NULL | ISO 8601 UTC |
| `fin` | TEXT | ISO 8601 UTC |
| `completa` | INTEGER NOT NULL DEFAULT 0 | 1 solo si terminó sin error |

**`operones_descargas`**: un archivo de una foto. Clave `(extraccion_id, url)`.

| columna | tipo | significado |
|---|---|---|
| `id` | INTEGER PK | |
| `extraccion_id` | INTEGER NOT NULL | → `operones_extracciones` |
| `url` | TEXT NOT NULL | o `archivo-local:<nombre>` |
| `ruta` | TEXT NOT NULL | ruta local; nunca se publica |
| `bytes` | INTEGER NOT NULL | |
| `sha256` | TEXT NOT NULL | huella del contenido |
| `descargado_en` | TEXT NOT NULL | ISO 8601 UTC |
| `nota` | TEXT | |

**`operones_bronze`**: lo que dijo la fuente. Clave `(id_fuente,
descarga_id)`; solo inserta, salvo `reparsear` (§4.1).

| columna | tipo | significado |
|---|---|---|
| `id` | INTEGER PK | |
| `id_fuente` | TEXT NOT NULL | el id de la fuente (`KO07643`, `TU1FZ6-520`, `operon-714`, `PA0425`) |
| `genes_raw` | TEXT | nombres de gen tal como los escribió la fuente; las cuatro lo dejan vacío porque dan locus tags |
| `locus_tags` | TEXT | separados por `\|` |
| `cadena` | TEXT | `+`/`-` si la fuente la da |
| `tipo_evidencia` | TEXT | códigos de la fuente, separados por `;` |
| `pmid` | TEXT | separados por `;` |
| `descarga_id` | INTEGER NOT NULL | → `operones_descargas` |
| `registro_raw` | TEXT | JSON con lo demás que dijo la fuente (ver §3) |

**`operones_silver`**: un operón curado. Clave `clave_genes`.

| columna | tipo | significado |
|---|---|---|
| `id` | INTEGER PK | |
| `clave_genes` | TEXT NOT NULL UNIQUE | locus tags ordenados, unidos con `\|` |
| `nombre` | TEXT | el más corto que dé una fuente |
| `locus_tags` | TEXT NOT NULL | en el orden de la primera fuente del grupo |
| `n_genes` | INTEGER NOT NULL | |
| `cadena` | TEXT | hebra según el GFF |
| `nivel_evidencia` | TEXT NOT NULL | `conocido`, `curado`, `predicho` |
| `evidencia_codigos` | TEXT | `fuente:código;…` |
| `n_fuentes` | INTEGER NOT NULL | fuentes de operones distintas |
| `pmids` | TEXT | |
| `adyacente` | INTEGER NOT NULL | 1/0 |
| `es_alternativa` | INTEGER NOT NULL | 1 si es subconjunto de otra unidad |
| `monocistronico` | INTEGER NOT NULL | 1 si tiene un solo gen |
| `promotor_cdbprom` | INTEGER NOT NULL | 1 si el primer gen transcrito tiene promotor |
| `revisar` | TEXT | marcas, separadas por `;` (§4.4) |
| `curado_en` | TEXT NOT NULL | ISO 8601 UTC |

**`operones_silver_fuente`**: qué registro de cada fuente respalda cada
operón. Clave `(silver_id, fuente, id_fuente)`. CDBProm nunca aparece aquí.

### 6.2 El catálogo maestro (`operones_<día>_catalogo.csv` y `.xlsx`)

Una fila por operón curado. Los valores sí/no se escriben «sí»/«no».

| columna | encabezado | significado |
|---|---|---|
| `clave_genes` | Clave (locus tags ordenados) | identidad del operón |
| `nombre` | Nombre | el más corto de sus fuentes |
| `genes` | Genes (símbolo de genes_pao1.tsv) | en orden de transcripción; el locus si no hay símbolo |
| `locus_tags` | Locus tags | en orden de transcripción |
| `orden_verificado` | Orden de transcripción verificado | «no» si falta la hebra |
| `n_genes` | Número de genes | |
| `hebra` | Hebra | |
| `nivel_evidencia` | Nivel de evidencia | |
| `evidencia` | Evidencia por fuente | p. ej. `biocyc:EV-EXP-IDA; pgd:PseudoCAP` |
| `pmids` | PMIDs | |
| `fuentes` | Fuentes de operones | solo odb, biocyc, pgd |
| `n_fuentes` | Número de fuentes | |
| `id_odb`, `nombre_odb` | ID / Nombre en ODB | |
| `id_biocyc` | ID en BioCyc | |
| `id_door`, `nombre_door` | ID / Nombre en PGD (DOOR) | |
| `id_pseudocap`, `nombre_pseudocap` | ID / Nombre en PGD (PseudoCAP) | un ID por artículo |
| `promotor_cdbprom` | Promotor CDBProm | |
| `gen_con_promotor` | Gen con promotor | el primer gen transcrito |
| `score_cdbprom` | Score CDBProm | |
| `monocistronico` | Un solo gen | |
| `adyacente` | Genes adyacentes | |
| `es_alternativa` | Unidad alternativa | |
| `en_catalogo_paso1` | En el catálogo del paso 1 | igualdad exacta de genes con `operones_pao1.tsv`; vacío si falta ese archivo |
| `nombre_catalogo_paso1` | Nombre en el catálogo del paso 1 | |
| `revisar`, `motivo` | Para revisar / Motivo | marcas y su prosa |

La **hoja de fuentes** (`_catalogo_fuentes.csv`) tiene una fila por archivo de
la foto vigente de cada fuente:
- qué aporta, qué es y su estado (vigente, más nueva que la curación, fuera
  de la curación);
- la fecha de los datos cuando se conoce, y la de descarga;
- origen, huella SHA-256 y bytes;
- las filas vigentes y las unidades que respalda (en CDBProm, las que marca).

El **léame** (`_catalogo_leame.txt` y hoja «Léame») calcula sus cifras al
correr.

### 6.3 La vista de la página de PGD (`operones_<día>_pgd.csv`)

Una fila por gen. Columnas: `ID del operón, Operón, Locus tag, Gen,
Descripción (RefSeq), Inicio, Fin, Hebra, Tipo (RefSeq), Evidencia, PMID`. Sale
del bronce vigente, antes de curar, en el orden del archivo. La evidencia se
escribe como en la página («Computationally-predicted (DOOR)» o «Literatura
(PseudoCAP)»), y en DOOR el PMID es el del método.

### 6.4 El recurso del paso 1 (`grn_bronce/recursos/operones_base.tsv`)

TSV, UTF-8 sin BOM, `\n`, ordenado por clave y sin fechas. Contrato en
`grn_bronce/operones.py` (`RUTA_BASE`, `COLUMNAS_BASE`). **No va a git:**
lleva unidades de BioCyc, cuya licencia restringe redistribuir los datos, y
el repositorio es público. Cada máquina lo genera con `catalogo --paso1`, y el
resumen del bronce guarda su huella.

| columna | significado |
|---|---|
| `clave_genes` | locus tags ordenados |
| `nombre` | nombre del operón, o vacío |
| `locus_tags` | en orden de transcripción |
| `genes` | símbolos separados por espacio |
| `nivel_evidencia` | solo decide qué alternativas cuentan |
| `es_alternativa`, `monocistronico` | `si`/`no` |

Con él, las oraciones candidatas del bronce ganan dos columnas:
- **`hay_operon`** (si/no);
- **`operones_en_oracion`**: los operones que la oración nombra más aquellos a
  los que pertenecen sus genes, sin repetir. Una unidad sin nombre sale con
  sus genes entre llaves (`{mexE mexF oprN}`).

Cuentan las unidades de más de un gen, principales, y las alternativas que no
son solo predicción. En la corrida 4, 23 445 de 29 659 candidatas tienen al
menos un operón.

---

## 7. Qué se tomó y qué no

| fuente | se tomó | no se tomó, y por qué |
|---|---|---|
| ODB | `koid`, operón (`op`), nombre, definición, PMIDs | los otros organismos (filtro por taxid) |
| BioCyc | TUs con sus genes (vía `accession-1`), códigos de evidencia, PMIDs de la cita | **`common-name` (94 TUs): pendiente**; promotores (25) y dirección; `dblink`, comentarios. Las TUs sin ningún gen resoluble se descartan |
| PGD | los 1 290 operones con sus genes, coordenadas, hebra, origen y PMIDs | la cita de DOOR como evidencia (va a `referencia_metodo`); la descripción de cada gen (no viene en la tabla); **el release 22.1** (el sitio no lo ofrece: está tras Cloudflare) |
| CDBProm | locus, cadena, coordenadas, score, secuencia y anotación, como marca de promotor | 22 locus con sufijo de letra; crear operones con él; la cadena del bronce en la curación |
| pseudomonas.com | nada del sitio | todo, por el desafío de Cloudflare y el `robots.txt`; sus operones entran por la exportación del curador |

---

## 8. Límites y pendientes

- **Casi todo es predicción:** el 96.5 %.
- **Decisión 3 (asesor):** si la base curada del laboratorio usó ODB o
  BioCyc, esas fuentes no pueden alimentar el paso 1 como rasgo evaluado
  contra ella. Por ahora el catálogo y la pertenencia solo anotan.
- **Contar la literatura por PMID único:** hoy dos fuentes que citan el mismo
  artículo cuentan como dos.
- **PGD es de 2021:** hay que pedir la tabla del release 22.1.
- **BioCyc:** tomar `common-name` (94 TUs), y decidir las 16 TUs
  `pendiente_revision`.
- **Adyacencia con sufijo `.N`:** 38 de los 55 «no adyacente» tienen algún
  locus `.N`, y hay que revisar cuántos son falsos.
- **BioCyc toma PMIDs y códigos de evidencia de todo el subárbol de la TU**,
  incluido su promotor. 16 TUs tienen PMID solo por su promotor, que es
  evidencia del promotor y no de la unidad. Restringirlo a la `citation` de la
  TU cambiaría el conjunto de «conocidos»; es una decisión pendiente.
- **Clave por genes:** dos unidades con distinto inicio de transcripción
  colapsan, y el promotor de CDBProm no dice a cuál pertenece.
- **La hebra sale de una foto fija del GFF de RefSeq** (la versionada con el
  diccionario): una anotación más nueva de RefSeq no entra sola.
- **Punto 34 del PLAN:** los mayores de los 103 operones del corpus que faltan
  en el catálogo del paso 1 (exoSTY, rsmZY, phzMS, lasRI, cyaAB) no son
  operones, sino genes que el texto abrevia juntos.
