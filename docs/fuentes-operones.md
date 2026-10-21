# Las fuentes de los operones: de dónde salió cada archivo

Para el asesor y para quien tenga que citar o reproducir la base de operones de
*P. aeruginosa* PAO1. Estado al 18 de octubre de 2026.

Este documento dice, fuente por fuente, cuatro cosas:
- qué liga pidió el encargo;
- de qué liga se bajó de verdad cada archivo;
- por qué no siempre es la misma;
- qué archivo llegó.

El caso que más explicación necesita es Pseudomonas Genome DB. Sus operones no
salieron de pseudomonas.com, sino de una copia publicada en otro sitio (el
GitHub del laboratorio Greene) que es la misma información. La sección 3 lo
documenta paso por paso.

Qué se hizo después con cada archivo está en otros dos documentos:
- [`catalogo-operones.md`](catalogo-operones.md): qué se tomó de cada fuente y
  el diccionario de datos;
- [`guia-operones.md`](guia-operones.md): cómo se regenera la base.

---

## 1. En corto

| fuente | liga que pidió el encargo | liga de la que se bajó | archivo que llegó |
|---|---|---|---|
| ODB v4 | [operondb.jp/known?species=208964&p=2](https://operondb.jp/known?species=208964&p=2) | [operondb.jp/download/known_operon.download.txt](https://operondb.jp/download/known_operon.download.txt) | `known_operon.download.txt`, 538 404 bytes |
| BioCyc / PseudoCyc | [biocyc.org/tu?orgid=PAER208964&id=TU1FZ6-912](https://biocyc.org/tu?orgid=PAER208964&id=TU1FZ6-912) | la API oficial, `https://websvc.biocyc.org/xmlquery`, con cuenta | `tus.xml`, 2 475 121 bytes, y `genes.xml`, 9 079 922 bytes |
| Pseudomonas Genome DB | [pseudomonas.com/feature/show/?id=109783&view=operons](https://www.pseudomonas.com/feature/show/?id=109783&view=operons) | [la exportación del curador en GitHub](https://raw.githubusercontent.com/greenelab/core-accessory-interactome/25539b82d51aa088c9e2f241a71ea1cc996fddae/data/metadata/PAO1-operons-2021-07-19.csv) | `PAO1-operons-2021-07-19.csv`, 332 301 bytes |
| CDBProm (IIMAS, UNAM) | [aw.iimas.unam.mx/cdbprom/search2.php](https://aw.iimas.unam.mx/cdbprom/search2.php) | el archivo por organismo del mismo sitio, bajado a mano; la liga exacta no quedó registrada | `Pseudomonas_aeruginosa_GCF_000006765.1_ASM676v1_upstream.txt`, 689 857 bytes |

Fechas de descarga, en hora de México (UTC−6):

| fuente | bajado | entró a la base |
|---|---|---|
| ODB v4 | 18-sep-2026 | 18-sep-2026 |
| BioCyc / PseudoCyc | 18-sep-2026 | 18-sep-2026 |
| Pseudomonas Genome DB | 27-sep-2026 | 27-sep-2026 |
| CDBProm | 18-sep-2026, a mano | 25-sep-2026 |

**Por qué casi ninguna liga es la del encargo.** Las páginas que pidió el
encargo son las que una persona ve en el navegador. Para bajar los datos
completos de forma automática hubo que usar la vía que cada sitio ofrece o
permite para eso. En tres casos la página no servía:
- en ODB es una aplicación de JavaScript sin datos;
- en BioCyc el sitio prohíbe el acceso automatizado a sus páginas y ofrece una
  API;
- en Pseudomonas Genome DB todo el sitio está cerrado a programas.

---

## 2. Fuente por fuente

### 2.1 ODB v4 — operones conocidos

- **Qué es.** Operon DataBase v4, de operondb.jp. Reúne operones conocidos de
  muchos organismos, cada uno con el artículo que lo sostiene.
- **Qué pidió el encargo.** La tabla paginada de PAO1:
  [operondb.jp/known?species=208964&p=2](https://operondb.jp/known?species=208964&p=2).
- **Por qué no se usó esa liga.** ODB v4 es una aplicación de JavaScript. Pedida
  por un programa, cualquier ruta del sitio devuelve el mismo esqueleto de 689
  bytes, sin un solo dato; `robots.txt` incluido. Comprobado el 18-sep-2026.
- **De dónde se bajó.** Del volcado de texto que el propio sitio ofrece en la
  página de la tabla ([operondb.jp/known](https://operondb.jp/known)), con el
  botón «Download Known Operons (Plain text)»:
  [operondb.jp/download/known_operon.download.txt](https://operondb.jp/download/known_operon.download.txt).
  Es una sola petición, sin cuenta.
- **Qué llegó.**
  - `known_operon.download.txt`, de 538 404 bytes, con todos los organismos:
    9 479 filas de datos.
  - Se quedaron las 33 de PAO1 (taxid 208964).
  - En el código es `grn_operones/fuentes.py::URL_ODB`.

### 2.2 BioCyc / PseudoCyc — unidades de transcripción

- **Qué es.** La base de Pathway Tools para PAO1 (organismo `PAER208964`).
  Trae unidades de transcripción: unas pocas con respaldo experimental, y la
  gran mayoría predichas por el algoritmo de Pathway Tools.
- **Qué pidió el encargo.** La página de una unidad:
  [biocyc.org/tu?orgid=PAER208964&id=TU1FZ6-912](https://biocyc.org/tu?orgid=PAER208964&id=TU1FZ6-912).
- **Por qué no se usó esa liga.** BioCyc prohíbe el acceso automatizado a sus
  páginas. Para eso ofrece una API oficial, que pide cuenta.
- **De dónde se bajó.** De la API, en tres peticiones:
  1. Inicio de sesión: `POST https://websvc.biocyc.org/credentials/login/`, con
     la cuenta del usuario. Las credenciales van solo en el entorno de la
     sesión y nunca se escriben.
  2. Las unidades de transcripción: `https://websvc.biocyc.org/xmlquery` con
     `query=[x:x<-PAER208964^^Transcription-Units]` y `detail=full`. Da
     `tus.xml`.
  3. Los genes: la misma dirección con `query=[x:x<-PAER208964^^Genes]` y
     `detail=full`. Da `genes.xml`, que es el puente entre los identificadores
     internos de BioCyc y los locus tags.
- **Qué llegó.**
  - `tus.xml`, de 2 475 121 bytes, con 3 787 unidades.
  - `genes.xml`, de 9 079 922 bytes, con 5 692 genes.
  - Pathway Tools 30.0.
- **Un detalle del registro.** La dirección de `genes.xml` quedó guardada con
  sus parámetros. La de `tus.xml` quedó como `https://websvc.biocyc.org/xmlquery`,
  sin la consulta, porque se registró antes de que se corrigiera eso (commit
  `0ad3cd2`, 18-sep). La consulta está confirmada en el propio archivo: el
  `xml:base` de la respuesta repite `[x:x<-PAER208964^^Transcription-Units]`.
- **Licencia.** BioCyc restringe redistribuir sus datos. Por eso
  `operones_base.tsv`, que los lleva, no va al repositorio público.

### 2.3 Pseudomonas Genome DB — operones de DOOR y de PseudoCAP

- **Qué es.** La base de genomas de *Pseudomonas* (pseudomonas.com). Para cada
  gen tiene una vista de operones con:
  - el nombre del operón;
  - sus genes, con locus tag, nombre, descripción, inicio, fin, hebra y tipo;
  - la evidencia y la referencia.
- **Qué pidió el encargo.** Esa vista:
  [pseudomonas.com/feature/show/?id=109783&view=operons](https://www.pseudomonas.com/feature/show/?id=109783&view=operons).
- **Por qué no se usó esa liga.** El sitio entero está cerrado a programas y no
  ofrece un archivo de operones (sección 3).
- **De dónde se bajó.** De la tabla que el curador de la base le entregó al
  laboratorio Greene, publicada en GitHub y fijada a un commit:
  [raw.githubusercontent.com/greenelab/core-accessory-interactome/25539b82…/data/metadata/PAO1-operons-2021-07-19.csv](https://raw.githubusercontent.com/greenelab/core-accessory-interactome/25539b82d51aa088c9e2f241a71ea1cc996fddae/data/metadata/PAO1-operons-2021-07-19.csv).
  Es una sola petición, sin cuenta.
- **Qué llegó.**
  - `PAO1-operons-2021-07-19.csv`, de 332 301 bytes, con 3 816 filas (una por
    gen) en 1 290 operones.
  - 1 165 operones son predicciones de DOOR y 125 son de literatura, de
    PseudoCAP.
  - En el código es `grn_operones/fuentes.py::URL_PGD`.

### 2.4 CDBProm — promotores predichos

- **Qué es.** Una base de promotores bacterianos predichos con XGBoost, del
  IIMAS (UNAM). Da un promotor frente a cada gen.
- **Qué pidió el encargo.** El buscador del sitio:
  [aw.iimas.unam.mx/cdbprom/search2.php](https://aw.iimas.unam.mx/cdbprom/search2.php).
- **Por qué no se usó esa liga.** El sitio prohíbe el acceso automatizado a sus
  páginas, pero ofrece descargar el archivo completo de cada organismo.
- **De dónde se bajó.** De la descarga por organismo del mismo sitio, a mano y
  desde el navegador, el 18-sep-2026. **La liga exacta del archivo no quedó
  registrada.** Tampoco se puede volver a buscar con un programa, por la regla
  del sitio.
- **Cómo queda registrado.** La base lo anota como
  `archivo-local:Pseudomonas_aeruginosa_GCF_000006765.1_ASM676v1_upstream.txt`.
  Ese prefijo dice que no es una dirección que se pueda volver a pedir. Lo que
  identifica al archivo es su nombre, su tamaño y su huella.
- **Qué llegó.**
  - `Pseudomonas_aeruginosa_GCF_000006765.1_ASM676v1_upstream.txt`, de 689 857
    bytes, con 1 972 filas de datos.
  - Entraron 1 950 promotores. Se rechazaron 22 locus con sufijo de letra.
  - CDBProm no crea operones: marca los que tienen promotor frente a su primer
    gen transcrito.

---

## 3. Pseudomonas Genome DB: la fuente que llegó por otro sitio

El asesor pidió los operones tal como los muestra pseudomonas.com. Del sitio no
se pudo sacar nada, y se encontró la misma información publicada en otro lado.
Esta es la cadena de evidencia, con la liga de cada eslabón, para que cualquiera
la pueda revisar.

### 3.1 El sitio está cerrado a programas

- **El desafío de Cloudflare.** El 27-sep-2026 se pidieron nueve rutas, una por
  vez, con 2 s entre cada una y sin imitar un navegador:
  - `robots.txt`;
  - `/strain/download`;
  - los archivos de `/downloads/` de PAO1: el CSV, el GFF, los ortólogos y
    `strain_summary.txt`;
  - la exportación CSV de `feature/list`;
  - la vista de operones;
  - `/downloads/`.

  Las nueve contestaron igual: error 403, `Server: cloudflare`,
  `Cf-Mitigated: challenge` y una página «Just a moment...». Solo pasa un
  navegador que ejecute el desafío, y pasarlo con un programa sería evadir un
  control de acceso. No se hizo.
- **Su `robots.txt` lo prohíbe.** Prohíbe la recolección automatizada sin
  permiso escrito del operador. Como el sitio no deja leerlo, se leyó la copia
  del Internet Archive:
  [captura del 4-ago-2025](https://web.archive.org/web/20250804080414/https://pseudomonas.com/robots.txt).

### 3.2 No hay un archivo de operones que bajar

- **La página de descargas no ofrece operones.** Su captura del release 22.1
  (6-oct-2023) ofrece, por cepa, FASTA, anotación en CSV/GBK/GFF3/GTF y
  ortólogos. La palabra «operon» no aparece:
  [captura del 11-feb-2025](https://web.archive.org/web/20250211085929/https://pseudomonas.com/strain/download).
- **El GFF de PAO1 no trae operones.** Su copia archivada no tiene rasgos de
  operón:
  [GFF del release 16.1, captura del 2-abr-2017](https://web.archive.org/web/20170402055645/http://pseudomonas.com/downloads/pseudomonas/pgd_r_16_1/Pseudomonas_aeruginosa_PAO1_107/Pseudomonas_aeruginosa_PAO1_107.gff).

Los operones solo existen como la página HTML de cada gen. Bajarlos de ahí serían
unas 5 700 páginas, detrás del desafío.

### 3.3 Qué alimenta la vista de operones

La vista de un gen dice de dónde salen sus operones. Lo muestra la captura de la
página de operones de *oprM* (PA0427):
[página de *oprM*, captura del 25-nov-2017](https://web.archive.org/web/20171125060508/http://pseudomonas.com/feature/show/?id=103591&view=operons).
- Es la única captura que tiene el Internet Archive de esa página. Se comprobó
  en su índice el 18-oct-2026.
- Muestra «Operons (5)», con `mexAB-oprM` (PA0425–PA0427).
- De esos cinco, cuatro son operones de literatura de **PseudoCAP**, cada uno
  con su artículo, y uno es una predicción de **DOOR** (Database of
  Prokaryotic Operons).

Que los operones de la base vienen de DOOR lo dice también su artículo: Winsor
et al. 2011, [doi:10.1093/nar/gkq869](https://doi.org/10.1093/nar/gkq869),
«precise operon predictions based on the Database of Prokaryotic Operons
(DOOR)».

### 3.4 Quién recibió esos datos del curador

Lee et al. 2023, en *mSystems*
([doi:10.1128/msystems.00342-22](https://journals.asm.org/doi/10.1128/msystems.00342-22)),
dicen en sus Métodos:

> the operon data were provided by Geoff Winsor and include computationally
> predicted annotations from DOOR as well as curated annotations from PseudoCAP

Geoff Winsor es el curador de Pseudomonas Genome DB. Es decir, el laboratorio
Greene recibió del propio curador la misma tabla que alimenta la vista de
operones del sitio.

### 3.5 Dónde quedó publicada

- **Repositorio:**
  [github.com/greenelab/core-accessory-interactome](https://github.com/greenelab/core-accessory-interactome).
  Tiene licencia BSD-3, que permite usarla y redistribuirla conservando el
  aviso de derechos de autor.
- **Archivo:** `data/metadata/PAO1-operons-2021-07-19.csv`.
- **Commit al que se fija la descarga:**
  [25539b82d51aa088c9e2f241a71ea1cc996fddae](https://github.com/greenelab/core-accessory-interactome/commit/25539b82d51aa088c9e2f241a71ea1cc996fddae).
  Una rama se puede mover y un commit no. Por eso los bytes que se bajen dentro
  de un año son los mismos que se revisaron: 332 301 bytes, con la misma huella.

### 3.6 La comprobación de que es la misma información

No bastaba con que la tabla viniera del curador: tenía que ser lo que muestra la
página. Se comparó con la captura de la página de *metG* que mandó el usuario.
La tabla trae lo mismo:
- `operon-714`, con el nombre `metG-PA3483`;
- PA3482 (`metG`), de 3895324 a 3897357, en la hebra +;
- PA3483, de 3897391 a 3898191, en la hebra +;
- evidencia de DOOR, con el PMID 18988623.

**Coincide campo por campo.** Solo faltan en la tabla la descripción y el tipo
de cada gen, que se toman de RefSeq. Esa captura es de la página actual. La de
*oprM* (3.3) es de 2017, y las dos dicen lo mismo sobre el origen de los datos.

### 3.7 Por qué no se fue directo a DOOR

DOOR, el origen de las predicciones, ya no está en línea. El 27-sep-2026 se
probaron sus direcciones conocidas y ninguna sirve:
- `http://csbl.bmb.uga.edu/DOOR/`: no contesta;
- `http://bmbl.sdstate.edu/DOOR/`: no contesta;
- `https://bmbl.bmi.osumc.edu/DOOR/`: error 404;
- `http://intelligentoffloading.com/DOOR3/`: el dominio ya no resuelve.

Sus predicciones para PAO1 sobreviven en esta exportación. La referencia de DOOR
es Mao et al. 2009, PMID 18988623.

### 3.8 El límite, y cómo se mejora

La tabla es una foto del 19 de julio de 2021. El release vigente de la base es
el 22.1, del 6 de octubre de 2023. Una versión nueva se pide por correo al
curador (pseudocap-mail@sfu.ca o gwinsor@sfu.ca), que es como la consiguió el
laboratorio Greene. Entra como archivo local, sin tocar el código.

---

## 4. Fuentes de apoyo: no aportan operones, pero la curación las usa

| qué | liga | para qué |
|---|---|---|
| Genoma de PAO1 en RefSeq, GFF (`GCF_000006765.1_ASM676v1`) | [ftp.ncbi.nlm.nih.gov/…/GCF_000006765.1_ASM676v1_genomic.gff.gz](https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/006/765/GCF_000006765.1_ASM676v1/GCF_000006765.1_ASM676v1_genomic.gff.gz) | la hebra de cada gen, con la que se verifica el orden de transcripción y el primer gen de cada operón |
| KEGG, lista de genes de PAO1 | [rest.kegg.jp/list/pae](https://rest.kegg.jp/list/pae) | sinónimos del diccionario de genes |
| UniProt | [rest.uniprot.org/uniprotkb/search](https://rest.uniprot.org/uniprotkb/search), con el proteoma UP000002438 y la especie 287 (entradas revisadas) | sinónimos y la marca de factor de transcripción del diccionario |

Con esas tres fuentes se construye el diccionario de genes `genes_pao1.tsv`
(5 642 genes). Con él, cada nombre de gen de las cuatro fuentes se lleva a su
locus tag. No se usó la anotación de pseudomonas.com, porque está detrás del
mismo desafío. La procedencia completa del diccionario está en
[`grn_bronce/recursos/PROCEDENCIA.md`](../grn_bronce/recursos/PROCEDENCIA.md).

El GFF viaja en el repositorio, en
`construir_diccionario/diccionario_independiente/cache/refseq.gff.gz`, y es
idéntico a la copia local del constructor del diccionario.

---

## 5. Dónde queda registrado cada archivo

- **En la base de datos.** Por cada archivo bajado, `operones_descargas` guarda
  la dirección (o `archivo-local:`), los bytes, la huella SHA-256 y la fecha.
- **En disco.** El archivo se guarda tal como llegó, en
  `<GRN_DATOS>/operones_crudo/<fuente>/<fecha>/`.
- **En el catálogo maestro.** Su hoja de fuentes trae la dirección, los bytes y
  la huella completa de cada archivo, para que cualquiera compruebe que tiene el
  mismo. La del 27-sep es `salidas/operones_20260927_catalogo_fuentes.csv`.

El 18-oct-2026 se recalcularon los bytes y la huella de los cinco archivos en
disco. Coinciden con esa hoja.
