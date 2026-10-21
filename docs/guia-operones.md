# Guía de los operones: cómo funcionan, cómo se mantienen y cómo se regeneran

Para quien mantenga los operones del proyecto. Sirve para:
- regenerar `operones_base.tsv` en otra máquina;
- meter una fuente o una foto nueva;
- entender por qué se movió una cifra.

Estado al 20 de octubre de 2026. Otros tres documentos completan este:
- [`catalogo-operones.md`](catalogo-operones.md) tiene el detalle de cada
  fuente y el diccionario de datos, y aquí no se repite;
- [`fuentes-operones.md`](fuentes-operones.md) tiene la liga exacta de cada
  fuente y la cadena de evidencia de Pseudomonas Genome DB;
- [`operones-asesor.md`](operones-asesor.md) da el estado y las decisiones
  abiertas, en corto.

Cada afirmación cita el archivo o la función de donde sale, y no el número de
línea, que se mueve.

---

## 0. La historia en fechas

| fecha | qué pasó | dónde está |
|---|---|---|
| 11-sep | Acuerdo con el asesor: una relación sobre un operón alcanza a todos sus genes, y el bronce gana una columna de operón | `PLAN.md` §1.1 |
| 17-sep | El bronce guarda la mención del operón y su expansión (corrida 2). `grn_bronce/operones.py` queda como la única expansión del proyecto. 7 136 menciones, 363 operones y 103 fuera del catálogo | bitácora del 17-sep |
| 18-sep | Nace `grn_operones`, en siete commits. Se bajan ODB y BioCyc, y a mano el archivo de CDBProm | abajo |
| 24-sep | Ingesta por archivo local y parser de CDBProm. Guion de la reunión | `e6e0e94`, `3ee2c93` |
| 25-sep | Entra el volcado real de CDBProm. Reunión con el asesor, que deja siete decisiones pedidas | bitácora del 25-sep; [`reunion-asesor-25sep.md`](reunion-asesor-25sep.md) |
| 27-sep | Ver el desglose abajo | las tres entradas de la bitácora del 27-sep |
| 28-sep | `operones_base.tsv` queda fuera de git. La guarda de contaminación vigila `grn_operones`, y `pyproject.toml` gana el extra `[operones]` | bitácora del 28-sep; `6b5e173`, `577c627`, `8ae974b` |
| 5 al 9-oct | Respuesta verbal del asesor sobre la decisión 3 | §11 |
| 8-oct | `flujo.py` gana el paso `operones`, y la capa dice a qué operones pertenece el blanco | bitácora del 8-oct |
| 16-oct | Esta guía y el documento para el asesor | bitácora del 16-oct |
| 18-oct | `fuentes-operones.md`: la liga de cada fuente y la evidencia de PGD | bitácora del 18-oct |
| 20-oct | Se cierra todo lo de operones que no depende del asesor (§12), y la base pasa a la huella `66b594bba16236d9` | bitácora del 20-oct |

El 27-sep pasaron cinco cosas:
- entra Pseudomonas Genome DB por la exportación de su curador;
- dos correcciones: el primer gen transcrito, y PGD no es Pathway Tools;
- el catálogo maestro;
- la medición de «anota, no detecta»;
- `catalogo --paso1` y la corrida 4 reexportada con operones.

### Del 18 al 24 de septiembre, reconstruido de los commits

La bitácora no tiene entradas de esos días. Esto sale del cuerpo de cada
commit (`git log --reverse 77008be^..e6e0e94 -- grn_operones/`):

1. **`77008be`.** Paquete nuevo, solo biblioteca estándar. El prototipo
   `operones_extraccion.py`, que nunca entró a git, queda portado y borrado.
   - Separa bronce y silver.
   - Credenciales solo por entorno: se retira `--email`.
   - `inspeccionar()` describe lo que llegó antes de escribir un parser.
   - El DDL queda propuesto, sin aplicar. 40 pruebas.
2. **`1b011b6`.** El DDL se aplica a la base: cuatro tablas, vacías.
   - La foto vigente pasa a ser la última extracción **completa** de cada
     fuente, y lo que desaparece entre fotos se lista como retirado.
   - Los parálogos (`phzA`) ya no se resuelven solos: van a conflictos.
   - 46 pruebas.
3. **`bc273db`.** Quinta tabla, `operones_extracciones`. La fuente deja de
   estar en el bronce y se deriva de la extracción, así que una fila no puede
   colgar de la descarga de otra fuente. 48 pruebas.
4. **`004e0e0`.**
   - La clave de las descargas pasa a `(extraccion_id, url)`.
   - `edad_de_la_foto()` avisa si se cura una foto vieja.
   - ODB v4 resulta ser una aplicación de JavaScript, y se usa su volcado de
     texto.
   - 52 pruebas.
5. **`0ad3cd2`.** Las unidades de un gen se conservan marcadas
   (`monocistronico`), y filtrarlas pasa a `exportar --sin-monocistronicos`.
   - Las dos consultas de BioCyc se registran con sus parámetros: con el
     endpoint pelado, `genes.xml` quedaba sin procedencia.
   - 58 pruebas.
6. **`6bd1fab`.**
   - Los PMIDs de BioCyc salen de toda la unidad, promotor incluido. El
     cuerpo del commit dice «de su cita», pero el código ya recorría todo el
     subárbol, y así sigue (`fuentes.parsear_biocyc`). La D2 depende de esto.
   - El nivel de evidencia se decide por unidad y no por fuente.
   - Nace `reparsear`, que vuelve a leer el crudo sin red.
   - 67 pruebas.
7. **`3a25480`.** La clave del operón son sus genes ordenados, y ya no el
   orden de la fuente. Lo destapó la revisión a mano de `mexAB-oprM`.
   - Las unidades pasan de 3 755 a 3 742, y las de dos o más fuentes, de 4 a
     17.
   - Nacen las marcas `pendiente_revision` y `locus_sufijo_excluido`.
   - 69 pruebas.
8. **`e6e0e94` (24-sep).** `extraer --archivo` y el parser de CDBProm.
   - Se probaron con un volcado sintético que después se borró de la base y
     del disco.
   - CDBProm marca y no crea operones.
   - 82 pruebas.

El 24-sep salió además la lista de revisión para el asesor
(`salidas/operones_pendiente_revision_20260924.csv`): 16 unidades con 21
PMIDs, con título, año, revista y tipo de artículo. La produjo un script de
sesión que no quedó versionado. Desde el 20-oct-2026 la reproduce
`exportar --pendientes`.

## 1. Los dos catálogos

| | catálogo del paso 1 | base de operones |
|---|---|---|
| archivo | `grn_bronce/recursos/operones_pao1.tsv`, copia de `etapa2/operones_pao1.tsv`: el mismo archivo en git, y `test_recursos.py` vigila que no diverjan | `grn_bronce/recursos/operones_base.tsv` |
| filas | 3 030 operones, todos de dos o más genes | 4 250 unidades (1 576 de más de un gen) |
| origen | adyacencia en el GFF de RefSeq (`etapa2/construir_diccionario.py::derivar_operones`) | ODB, BioCyc y PGD, curados por `grn_operones` |
| lo escribe | `etapa2/construir_diccionario.py` escribe la copia de `etapa2/`, y de ahí se copia a `recursos/` | `python -m grn_operones.cli catalogo --paso1` |
| lo lee | `grn_bronce/operones.py::Catalogo` y `etapa2/lexico.py` | `grn_bronce/operones.py::BaseOperones` |
| en git | sí | no (`.gitignore`) |
| huella (`procedencia.huella_texto`) | `1ebba969e400ddb4` | `66b594bba16236d9` desde el 20-oct-2026 (era `f399bd89da7d558d`) |

El contrato de `operones_base.tsv` (ruta y encabezado) vive en el paquete que
lo lee: `grn_bronce/operones.py` (`RUTA_BASE`, `COLUMNAS_BASE`). `grn_operones`
lo importa para escribirlo. `grn_bronce` nunca importa `grn_operones`: lo
consume por archivo.

**La regla: el catálogo del paso 1 detecta y expande; la base solo anota.** Se
midió el 27-sep simulando cada variante contra las 7 136 menciones de la
corrida 4 (`decisiones.md`, «La base de operones anota el bronce, no lo
detecta»):

| variante | faltantes resueltos (de 103) | efecto |
|---|---|---|
| sumar los 71 operones con nombre de literatura | 1 | +208 menciones, casi todas falsas (`psl` 155, `amidase` 22) |
| sumar las 1 200 unidades con nombre | 2 | +356 menciones que se comen 343 de genes y proteínas |
| reemplazar `operones_pao1.tsv` | 1 o 2 | se pierden entre 3 251 y 4 554 de las 6 689 menciones resueltas |

**Qué unidades de la base cuentan para anotar** (`BaseOperones._cuenta`):
- cuentan las de más de un gen que no son alternativas;
- cuentan también las alternativas de más de un gen cuyo nivel no es solo
  `predicho`. Hay 56 alternativas con evidencia, pero 24 son de un solo gen y
  no cuentan;
- una alternativa es un subconjunto estricto de otra unidad
  (`curar.py`, paso 3);
- son 1 219 de 4 250, y 32 de ellas son alternativas con evidencia.

## 2. `grn_operones` por dentro

| módulo | qué hace |
|---|---|
| `cli.py` | el único que imprime: parsea, llama y formatea |
| `fuentes.py` | trae cada fuente, guarda el crudo y lo parsea; `extraer`, `reparsear`, `foto_sana`, las URLs y los contratos de formato |
| `red.py` | la sesión HTTP: 2 s entre peticiones, reintentos con retroceso, User-Agent con correo de contacto, sin navegador |
| `db.py` | el único que escribe SQL; administra las cinco tablas `operones_*` |
| `curar.py` | de bronce a silver: normaliza a locus tag, valida adyacencia y hebra, deduplica, decide el nivel de evidencia y marca el promotor |
| `exportar.py` | silver, conflictos, la vista de PGD, el catálogo maestro (CSV, léame y `.xlsx`) y el recurso del paso 1 |
| `test_operones.py` | las pruebas del paquete, sin red |

Dependencias:
- solo biblioteca estándar;
- openpyxl, opcional y solo para el `.xlsx`, va en el extra `[operones]`.

Importa:
- de `grn_comun`: `rutas` (desde el 20-oct-2026; antes de `grn_bronce`) y
  `procedencia`;
- de lado, de `grn_bronce`: el lector del catálogo del paso 1 y el contrato de
  `operones_base.tsv`;
- de `grn_etl`: `credenciales`, `db` y, solo para `exportar --pendientes`,
  `pubmed`.

## 3. Comandos

`python -m grn_operones.cli [--datos D] <subcomando>`. **`--datos` va antes del
subcomando** en este CLI; en `grn_bronce.cli` va después.

| comando | red | credenciales | lee | escribe |
|---|---|---|---|---|
| `extraer [--fuente X] [--url U] [--archivo A] [--pausa S]` | sí, salvo con `--archivo` | el correo de contacto (`NCBI_EMAIL` o `.correo`), salvo con `--archivo`; para BioCyc, además `BIOCYC_EMAIL` y `BIOCYC_PASSWORD` | la fuente | el crudo en `<datos>/operones_crudo/<fuente>/<fecha>/` y filas en `operones_extracciones`, `operones_descargas` y `operones_bronze` |
| `reparsear [--fuente X]` | no | no | el crudo de la foto vigente y, si la hay, el de la completa y vacía más nueva, buscados bajo la raíz de datos de hoy y con su huella comprobada | rehace el bronce de esas extracciones |
| `curar` | no | no | el bronce de la foto vigente, `genes_pao1.tsv` y el GFF de RefSeq | rehace `operones_silver` y `operones_silver_fuente` |
| `exportar [--sin-monocistronicos] [--pendientes]` | solo con `--pendientes`: una petición a PubMed por cada 200 PMIDs (hoy, una) | con `--pendientes`, el correo | silver, el bronce de PGD y `genes_pao1.tsv` | `salidas/operones_<día>_{silver,conflictos,pgd}.csv`; con `--pendientes`, además `_pendiente_revision.csv` |
| `catalogo [--paso1]` | no | no | silver, el bronce vigente, el registro de descargas (para la hoja de fuentes), `genes_pao1.tsv` y `operones_pao1.tsv` | `salidas/operones_<día>_catalogo.csv`, `_catalogo_fuentes.csv`, `_catalogo_leame.txt` y `.xlsx`; con `--paso1`, además `grn_bronce/recursos/operones_base.tsv` |
| `estado` | no | no | las tablas | nada |

Detalles que muerden:
- **`--fuente`.**
  - Vale `todo` por omisión.
  - `--archivo` y `--url` exigen una sola fuente.
- **`exportar` y `catalogo` escriben en `salidas/` relativo a la carpeta
  actual.** Hay que correrlos desde la raíz del repositorio.
- **Todos los comandos abren la base con `grn_etl.db.conectar`, que la crea
  vacía si no existe.** Un `--datos` equivocado no da error: da una base
  vacía, y `estado` dice «Sin datos todavía».
- **El código de salida dice si entró todo lo pedido** (desde el
  20-oct-2026; antes era 0 siempre).
  - `extraer` sale con 1 si una fuente pedida no entró: credenciales, red, un
    `--archivo` que no existe o un formato que no se reconoce. Lo resume en el
    bloque «LO QUE DEVOLVIO CADA FUENTE».
  - Lo omitido por diseño no cuenta: CDBProm sin URL dentro de
    `--fuente todo`. Pedida por nombre, sí cuenta.
  - `reparsear` sale con 1 si no puede volver a leer la foto vigente: falta
    un crudo, no coincide su huella o el formato no se reconoce. No son falla
    una fuente sin ninguna extracción, ni una completa y vacía más nueva que
    sigue sin leerse: esa se avisa.
  - Un cuerpo que no es XML, o un XML con una codificación que no se conoce,
    ya no termina con traza: sale como formato desconocido y las demás
    fuentes siguen.
- **Lo que se sabe sin pedir nada se revisa antes de abrir la extracción.**
  Sin credenciales de BioCyc, sin URL de CDBProm o con un `--archivo` que no
  existe no queda ninguna extracción registrada. Lo que falla después de
  abrirla, a media descarga o al guardar el bronce, la cierra incompleta, con
  su fin.
- **BioCyc no entra por `--archivo`**: su foto son dos consultas.

Del lado del bronce:
- `python -m grn_bronce.cli exportar --corrida N` vuelve a volcar una corrida
  con `hay_operon` y `operones_en_oracion`, sin identificar de nuevo.
- `python -m grn_bronce.cli operones [--corrida N] [--solo-faltantes]` lista
  los operones que nombra el corpus y los que faltan en el catálogo del paso 1.

## 4. Tablas y archivos

**Las cinco tablas**, con su clave natural (detalle de columnas en
`catalogo-operones.md` §6.1):

| tabla | una fila es | clave natural |
|---|---|---|
| `operones_extracciones` | una foto de una fuente | `id`; `completa` = 1 si la descarga terminó, aunque el parseo falle (entonces con 0 filas) |
| `operones_descargas` | un archivo de una foto | `(extraccion_id, url)`. Desde el 20-oct-2026 la ruta se guarda relativa a la raíz de datos y con `/` |
| `operones_bronze` | lo que dijo la fuente, partido en campos | `(id_fuente, descarga_id)` |
| `operones_silver` | un operón curado | `clave_genes` |
| `operones_silver_fuente` | qué registro de cada fuente respalda cada operón | `(silver_id, fuente, id_fuente)` |

**La foto vigente** de cada fuente, que es la que se cura, es su última
extracción completa **que dejó filas** (`db.foto_vigente`). Una completa y
vacía, de un formato que no se supo leer, no desplaza a la anterior:
- `curar` la nombra;
- cuenta como fallida en la edad de la foto;
- la hoja de fuentes del catálogo la dice.

La misma foto es la que mira `fuentes.foto_sana` para decidir si PGD «ya
está». `reparsear` vuelve a leer la foto vigente y después la completa y
vacía más nueva: si un parser corregido ya la lee, pasa a ser la vigente.
Hasta la revisión del 20-oct-2026, `foto_sana` y `reparsear` miraban la
última completa. Una vacía encima hacía que `extraer --fuente pgd` volviera
a la tabla de 2021, y que `reparsear` saliera con 1 para siempre.

**El crudo**, en `<GRN_DATOS>/operones_crudo/<fuente>/<AAAA-MM-DD>/`. En la
laptop pesa 13 MB:
- `biocyc/2026-09-18/`: `tus.xml` y `genes.xml`;
- `odb/2026-09-18/`: `known_operon.download.txt`;
- `cdbprom/2026-09-25/`: el archivo del IIMAS;
- `pgd/2026-09-27/`: `PAO1-operons-2021-07-19.csv`.

**Las salidas** van a `salidas/`. Las del 27-sep son
`operones_20260927_{catalogo.csv, catalogo.xlsx, catalogo_fuentes.csv,
catalogo_leame.txt, conflictos.csv, pgd.csv, silver.csv}`. Las vigentes son
las del 20-oct, con los mismos nombres y `operones_20261020_`, más
`operones_20261020_pendiente_revision.csv`.

**`operones_base.tsv`.** Columnas: `clave_genes`, `nombre`, `locus_tags`,
`genes`, `nivel_evidencia`, `es_alternativa` y `monocistronico`.
- Sale ordenado por clave y sin fechas: la huella solo cambia si cambian los
  operones o sus nombres.
- **No lleva el promotor**, así que CDBProm no lo afecta.
- El detalle está en `catalogo-operones.md` §6.4.

## 5. De punta a punta

```
ODB · BioCyc · PGD · CDBProm
        │  extraer (red)  o  extraer --archivo
        ▼
<datos>/operones_crudo/  +  operones_extracciones / _descargas / _bronze
        │  curar (sin red; foto vigente de cada fuente)
        ▼
operones_silver  +  operones_silver_fuente
        │  catalogo --paso1
        ├──► salidas/operones_<día>_catalogo.*        para leer
        └──► grn_bronce/recursos/operones_base.tsv
                 ├──► bronce: hay_operon, operones_en_oracion
                 └──► capa:   operones_del_blanco
```

Quién lee qué catálogo:

| consumidor | catálogo del paso 1 | base de operones |
|---|---|---|
| detección del bronce (`grn_bronce/identificar.py` → `etapa2/lexico.py`) | sí | no |
| exportación del bronce (`grn_bronce/exportar.py`) | `operones`, `genes_expandidos` | `hay_operon`, `operones_en_oracion` |
| pares del paso 2 (`grn_verificacion/puente.py::locus_de`) | sí: los locus de un blanco que es operón | no |
| capa (`grn_verificacion/capa.py`) | por los pares | `operones_del_blanco` |
| entrenamiento con la base curada (`grn_verificacion/entrenamiento.py`) | por los locus que dejó el puente | no |
| evaluación (`etapa2/evaluar_oro.py`, `evaluar_signo.py`, `evaluar_cobertura_bronce.py`) | sí. El nombre que escribió la referencia se expande además por deducción, a propósito (`evaluar_oro.claves_extremo`); el que produjo el pipeline, solo por tabla | no |
| autorregulación (`etapa2/extraer_pares.py`) | sí, más los operones sintéticos del léxico (medido; ver §12, 4.17) | no |

## 6. El paso `operones` de `flujo.py`

`flujo.py::_plan`, rama `operones`:

- **Sin `--rehacer-operones` no corre nada.** Solo registra la huella de
  `operones_base.tsv` como salida. Si la huella cambia, el bronce y la capa,
  que lo declaran como entrada, se rehacen.
- **Si el archivo falta, el paso sale omitido** con el motivo. El bronce y la
  capa corren sin la base, solo con los operones que nombra la oración: es
  `OPCIONALES` en `flujo.py`.
- **Con `--rehacer-operones` corre tres comandos, y siempre:**
  `reparsear --fuente todo`, `curar` y `catalogo --paso1`, con `--datos` si se
  pasó.
  - Corre aunque nada haya cambiado. La base y los crudos que lee no se pueden
    huellear desde el flujo, y pedir rehacer es pedir rehacer. Hasta el
    20-oct-2026 la segunda vez salía «ya hecho» y hacía falta `--forzar
    operones`.
  - Nunca corre `extraer`, porque sale a la red y pide credenciales.
  - Si `reparsear` no puede volver a leer la foto vigente de una fuente (un
    crudo que no encuentra, §8), sale con 1 y el paso falla con el mensaje.
    Antes seguía callado con el bronce viejo. Una completa y vacía más nueva
    que sigue sin leerse solo se avisa, porque no es la que se cura.
  - La bandera con un `--pasos` que no incluye `operones` es error de uso.
- **Las entradas declaradas** son lo que decide `operones_base.tsv` y sí se
  puede huellear:
  - `genes_pao1.tsv` y `operones_pao1.tsv`;
  - las dos copias del GFF;
  - `grn_bronce/operones.py`, donde vive el contrato del recurso;
  - todo `grn_operones/*.py` menos las pruebas.

  Sin la bandera, si alguna cambió desde la última regeneración, el paso
  avisa que la base no se regeneró: en el log y en la nota del paso, que el
  tablero muestra. **El aviso se repite en cada corrida** hasta que se corre
  con `--rehacer-operones`. Hasta la revisión del 20-oct-2026 salía una sola
  vez, y la corrida siguiente daba el paso por hecho con la base vieja.

```bash
python flujo.py --pasos operones --rehacer-operones
```

Las pruebas del paso están en `pruebas/test_flujo.py`: los tres comandos, el
omitido, las entradas, que la bandera rehace también la segunda vez y que el
aviso se repite hasta regenerar.

## 7. Red y credenciales

| fuente | qué pide `extraer` | qué se rehace sin red |
|---|---|---|
| ODB | red y correo de contacto; una petición al volcado | `reparsear --fuente odb` |
| BioCyc | red, correo, `BIOCYC_EMAIL` y `BIOCYC_PASSWORD`; dos consultas a la API | `reparsear --fuente biocyc` |
| PGD | red y correo; una petición a GitHub. No vuelve a bajar mientras la foto vigente sirva (`fuentes.foto_sana`) | `reparsear --fuente pgd`, o una tabla nueva con `--archivo` |
| CDBProm | no tiene URL pública: entra con `--archivo` y el archivo bajado a mano del sitio del IIMAS. Con `--archivo` no pide correo | `reparsear --fuente cdbprom` |

`reparsear`, `curar`, `catalogo` y `estado` no salen a la red ni piden
credenciales. `exportar` tampoco, salvo con `--pendientes`, que hace una
petición a PubMed por cada 200 PMIDs (hoy, una) con el correo de contacto.

**Las credenciales de BioCyc van solo en el entorno de la sesión.** No se
escriben en ningún archivo del repositorio, ni en un perfil de shell
compartido, ni en la línea de comandos, donde quedarían en el historial. El
código no las imprime. En Linux, por ejemplo:

```bash
read -r BIOCYC_EMAIL; read -rs BIOCYC_PASSWORD; export BIOCYC_EMAIL BIOCYC_PASSWORD
```

Sin ellas, `extraer --fuente todo` no abre la extracción de BioCyc, anota el
error, sigue con las demás y sale con 1.

## 8. Regenerar `operones_base.tsv` en una máquina nueva

El archivo no viaja por git. En una máquina sin él, el bronce dice «recurso
ausente» y el flujo omite el paso `operones`. Hay tres vías.

### A. Recomendada: con la base copiada

`grn.db` ya trae las cinco tablas, con el bronce y silver. Viaja como
snapshot, igual que para el resto del proyecto. Desde la raíz del clon:

```bash
python -m grn_operones.cli --datos <D> estado            # las cuatro fuentes con filas en bronce
python -m grn_operones.cli --datos <D> catalogo --paso1
python -c "from grn_comun import procedencia; print(procedencia.huella_texto('grn_bronce/recursos/operones_base.tsv'))"
# → 66b594bba16236d9 (desde el 20-oct-2026)
```

- Sin red y sin credenciales.
- `curar` no hace falta: silver ya está en la base. Si se corre, rehace silver
  igual, porque la hebra sale primero de la copia versionada del GFF, la misma
  en todo clon, y `curar` dice de qué archivo salió y con qué huella.
- **Si la huella no coincide, no se usa el archivo.** Hay que ver qué cambió:
  `genes_pao1.tsv`, el GFF o la base copiada.
- **Con una base copiada antes del 20-oct-2026 sale `f399bd89da7d558d`,** la
  versión anterior. Los nombres de BioCyc entran con `reparsear` y el
  desempate de nombres con `curar`, así que hacen falta los crudos y
  `python flujo.py --pasos operones --rehacer-operones`, que corre los tres
  comandos.

**Los crudos, solo si después hará falta `reparsear`,** por ejemplo tras
corregir un parser. En ese caso se copia también `<datos>/operones_crudo/`, que
son 13 MB, dentro de la raíz de datos de la máquina nueva.

`reparsear` busca cada crudo en tres lugares:
1. la ruta guardada en `operones_descargas.ruta`, que es la de la máquina que
   lo bajó;
2. esa misma ruta, bajo la raíz de datos de hoy;
3. lo que sigue a `operones_crudo` en esa ruta, bajo la raíz de datos de hoy.

Se queda con el primero que tiene la huella registrada. Así una base copiada de
Windows a Linux encuentra sus crudos, aunque la ruta se haya escrito con `\`.
Si no lo encuentra, sale con 1 y dice dónde buscó. Desde el 20-oct-2026 lo
nuevo se registra relativo a la raíz de datos.

### B. Volver a extraer

Pide red, el correo de contacto y la cuenta de BioCyc. Una fuente a la vez,
leyendo el informe de cada una:

```bash
python -m grn_operones.cli extraer --fuente odb
python -m grn_operones.cli extraer --fuente biocyc       # con BIOCYC_EMAIL y BIOCYC_PASSWORD
python -m grn_operones.cli extraer --fuente pgd          # la tabla fijada a un commit
python -m grn_operones.cli extraer --fuente cdbprom --archivo <archivo_del_IIMAS>
python -m grn_operones.cli curar
python -m grn_operones.cli catalogo --paso1
```

- **Es una foto nueva, no la misma.**
  - ODB y BioCyc están vivas, así que la huella puede cambiar, y eso es lo
    esperado.
  - Hay que comparar las cifras de `curar` con las de §10 y anotar la
    diferencia en la bitácora.
- **CDBProm no afecta a `operones_base.tsv`:** solo al catálogo. Si el archivo
  del IIMAS no está a mano, se puede dejar para después.
- **Las reglas de acceso de cada fuente** están en `catalogo-operones.md` §2:
  2 s entre peticiones, la API oficial de BioCyc y nada de navegador.

### C. Copiar el TSV de otra máquina

El camino más corto: copiar el archivo a `grn_bronce/recursos/` y comprobar la
huella con el mismo comando de la vía A.
- No necesita la base ni los crudos.
- Nunca va a git: ya está en `.gitignore`.
- Si el archivo cambia, el flujo lo nota solo: el bronce guarda su huella en
  el resumen, y el bronce y la capa la declaran como entrada.

### Qué cambió → qué rehacer

| cambió | qué rehacer |
|---|---|
| un parser de `fuentes.py` | `reparsear --fuente X`, `curar` y `catalogo --paso1`; después, lo de la última fila |
| `curar.py` o `genes_pao1.tsv` | `curar` y `catalogo --paso1`; después, lo de la última fila |
| `exportar.py`, en el catálogo o el recurso | `catalogo --paso1` |
| una foto nueva de una fuente | `extraer --fuente X` (o `--archivo`), `curar` y `catalogo --paso1` |
| `operones_pao1.tsv` | una corrida nueva del bronce, porque cambia la detección, y todo lo de abajo; también `catalogo`, por la columna «En el catálogo del paso 1» |
| `operones_base.tsv` | el bronce (`grn_bronce.cli exportar --corrida N`, sin identificar de nuevo) y la capa. `flujo.py` lo hace solo |

## 9. Pruebas que cubren los operones

| archivo | pruebas en el archivo | qué cubre de los operones |
|---|---|---|
| `grn_operones/test_operones.py` | 186 | los parsers de las cuatro fuentes (PGD con filas reales; BioCyc, CDBProm y ODB con fixtures sintéticos); la página de desafío de Cloudflare y las codificaciones que no se conocen; las extracciones que no abren o que se cierran incompletas; los códigos de salida; la foto vigente, también en `foto_sana` y en `reparsear` con una vacía encima; `reparsear` con la base de otra máquina; la curación, la adyacencia con `.N`, el GFF usado; el catálogo, la hoja de fuentes, la lista de revisión y el recurso del paso 1 |
| `grn_bronce/test_operones.py` | 57 | la expansión por tabla, las dos vistas, `BaseOperones` y las columnas del bronce |
| `grn_bronce/test_recursos.py` | 25 | que las copias de `grn_bronce/recursos/` y `etapa2/` no diverjan, `operones_pao1.tsv` incluido |
| `grn_verificacion/test_capa_evaluar.py` | 27 | los operones del blanco en la capa, con base y sin ella; que la capa no mezcle dos versiones de la base; que IHF, PrrF y PrrH no cuenten como operón |
| `grn_verificacion/test_puente.py` | 23 | los locus de un blanco que es operón y la huella del catálogo en el informe de pares |
| `pruebas/test_flujo.py` | 37 | el paso `operones`: sus comandos, el omitido, sus entradas, que `--rehacer-operones` rehace siempre y que el aviso se repite hasta regenerar |
| `etapa2/test_evaluar.py` | 126 | la equivalencia por operón del evaluador |
| `etapa2/test_contaminacion.py` | 8 | que ningún paquete vigilado, `grn_operones` incluido, nombre las referencias de evaluación |

```bash
python -m unittest grn_operones.test_operones grn_bronce.test_operones grn_bronce.test_recursos \
    grn_verificacion.test_capa_evaluar grn_verificacion.test_puente pruebas.test_flujo
python -m unittest discover etapa2 -p "test_evaluar.py"
python -m unittest discover etapa2 -p "test_contaminacion.py"
```

Lo que no tiene prueba es la extracción real contra cada fuente: las pruebas
usan sesiones falsas y no salen a la red, a propósito.

## 10. Cifras vigentes y de dónde salen

Al 20-oct-2026, después de regenerar la base y correr el flujo de la corrida 4:

| cifra | valor | de dónde sale |
|---|---|---|
| unidades de la base | 4 250; 1 576 de más de un gen | `operones_base.tsv` (`monocistronico`) |
| conocidas / curadas / predichas | 145 / 3 / 4 102 (96.5 %) | `operones_base.tsv` (`nivel_evidencia`) |
| alternativas | 1 072 | `operones_base.tsv` (`es_alternativa`) |
| unidades que anotan | 1 219 | `BaseOperones._cuenta` sobre el TSV |
| sin nombre | 2 953, todas solo de BioCyc (eran 2 992); BioCyc nombra 93 | `salidas/operones_20261020_catalogo.csv` y su léame |
| con dos o más fuentes | 738 (717 BioCyc + PGD) | el mismo catálogo |
| con promotor CDBProm | 1 574 | el mismo catálogo |
| no adyacentes | 17 (eran 55, con el sufijo `.N` ignorado) | el mismo catálogo |
| para revisar | 81 (eran 117) | `salidas/operones_20261020_conflictos.csv` |
| iguales al catálogo del paso 1 | 325 de 3 030 | el léame del catálogo |
| lista de revisión (D2) | 16 unidades, 21 PMIDs, 22 filas | `salidas/operones_20261020_pendiente_revision.csv` |
| filas de bronce por fuente | ODB 33, BioCyc 3 774, PGD 1 290, CDBProm 1 950 | `salidas/operones_20261020_catalogo_fuentes.csv` |
| menciones de operón en la corrida 4 | 7 136, de 363 operones | `salidas/flujo/corrida4_run22/bronce_identificacion_corrida4_20261020_operones.csv` |
| operones fuera del catálogo del paso 1 | 103, con 447 menciones | el mismo CSV (`en_catalogo = no`) |
| candidatas con operón | 23 445 de 29 659 | `bronce_identificacion_corrida4_20261020_resumen.csv`, en esa carpeta |
| oraciones de la capa con operón | 17 326 | `capa_resumen.json` |
| pares con el blanco en un operón de la base | 38 307 | `capa_resumen.json` |
| pares cuyo blanco es un operón | 3 422 (eran 3 605: contaba a IHF, PrrF y PrrH) | `capa_resumen.json` |
| relaciones del oro unidas por operón | 4 de 190 | `evaluacion_oro.json` (`coincidencias`) |
| oraciones de la auditoría de signo unidas por operón | 8 de 93 | `evaluacion_signo.json` (`union`) |
| huella de `operones_base.tsv` | `66b594bba16236d9` | `procedencia.huella_texto`; también en `bronce_identificacion_corrida4_20261020_resumen.csv` y en `capa_resumen.json`. El resumen del bronce del 8-oct, en la misma carpeta, guarda la anterior |

## 11. Decisiones

Las de la reunión del 25-sep llevan tres numeraciones. Esta es la
equivalencia:

| asesor (D) | `pendientes.md` | tema |
|---|---|---|
| D1 | 1.2 | patrón de locus tag |
| D2 | 1.3 | las 16 unidades `pendiente_revision` y los PMIDs del promotor |
| D3 | 1.1 | ¿GRN_experimental se amplió por pertenencia a operón? |
| D4 | 1.4 | CDBProm y la clave de silver |
| D5 | — | superada: PGD entró por la exportación de su curador |
| D6 | 1.5 | las tres decisiones propias |
| D7 | 1.6 y fila 34 del PLAN | los 103 operones fuera del catálogo |
| D8 | 1.7 | contar la literatura por PMID único |
| D9 | 7.12 | operones en la red: expansión o anotación |

Las recomendaciones de cada una están en `operones-asesor.md` §7.

**Decisión 3 (abierta): respuesta verbal, probable (semana del 5 al 9 de
octubre de 2026). GRN_experimental es la red regulatoria y no una fuente de
operones. Falta confirmar por escrito si alguna relación se amplió por
pertenencia a operón; hasta entonces la pertenencia solo anota.** La pregunta
escrita está en `operones-asesor.md` §8.

Cuando llegue la respuesta escrita, hay que tocar lo mismo en cualquier caso:
- la bitácora y `PLAN.md` §1.4;
- `pendientes.md` 1.1 y, si se cierra, 3.13;
- la frase de estado, en `catalogo-operones.md` §8, `decisiones.md`
  («La base de operones anota el bronce, no lo detecta»),
  `grn_bronce/recursos/PROCEDENCIA.md`, `operones-asesor.md` §8 y esta
  sección;
- la nota «NOTA operones_en_oracion» del resumen del bronce
  (`grn_bronce/cli.py`) y el léame y el docstring de
  `grn_verificacion/capa.py`.

Cambiar `grn_bronce/cli.py` rehace el bronce en el flujo, porque es una de sus
entradas.

Lo que cambia con cada respuesta:

- **«No».** La pertenencia puede ser rasgo del paso 2, y la guarda por
  procedencia (3.13) deja de hacer falta.
- **«Sí».**
  - La pertenencia sigue como anotación.
  - Las filas ampliadas se apartan al evaluar y al entrenar.
  - Se monta la guarda: `operones_silver_fuente` dice qué fuente respalda
    cada unidad, y con eso se puede vetar la fuente que nombre el asesor.
- **«No lo sé».** Todo sigue como hoy.

## 12. Huecos conocidos

**Lo que queda, todo lo que no depende del asesor:**
- **4.3, la tabla del release 22.1 de PGD.** La que entró es de 2021. Se pide
  por correo al curador (pseudocap-mail@sfu.ca), con permiso escrito, y entra
  con `extraer --fuente pgd --archivo`. El borrador del correo está listo;
  lo manda el usuario.
- **Los importadores de `grn_bronce.rutas`** se mudan a `grn_comun` al tocar
  cada archivo:
  - `cli.py` y `servidor.py`;
  - `grn_verificacion/cli.py` y `grn_bronce/cli.py`;
  - dos scripts de `etapa2`.

  Cuando no quede ninguno, se borra el puente.
- **Dos detalles menores que vio la revisión del 20-oct, sin arreglar:**
  - `extraer --fuente cdbprom` sin `--archivo` ni URL pide el correo antes de
    decir que la omite, aunque no vaya a pedir nada;
  - si NCBI contesta su mensaje de límite rebasado con un 200,
    `exportar --pendientes` termina con traza. Es el punto 5 de la auditoría
    de `pubmed.py`, en CLAUDE.md, y se arregla en `grn_etl`.

**Cerrados el 20-oct-2026**; los que cambian código llevan sus pruebas (la
bitácora tiene el detalle):
- 3.14 y 4.10: el paso `operones` del flujo, con sus entradas reales, y
  `--rehacer-operones` rehace siempre (§6);
- 4.1: el `common-name` de BioCyc, con su columna en el catálogo;
- 4.2: la adyacencia con sufijo `.N`;
- 4.4: una foto que no deja filas ya no saca a la fuente de la curación (§4);
- 4.5: `exportar --pendientes`;
- 4.6: las pruebas de `parsear_odb`;
- 4.7: la hebra sale primero de la copia versionada, y `curar` dice cuál;
- 4.8: `rutas` vive en `grn_comun`, con un puente en `grn_bronce`;
- 4.11, 4.12 y 4.13: las extracciones y los códigos de salida (§3);
- 4.14: el nombre en el CSV de conflictos;
- 4.15: el código muerto;
- 4.16: `reparsear` encuentra el crudo en cualquier máquina (§8);
- 4.18: la huella de `operones_pao1.tsv` en `pares_informe.json`;
- 4.19: la capa se niega a mezclar dos versiones de la base;
- además, la capa contaba como operón a IHF, PrrF y PrrH, que no tienen locus
  en el diccionario: IHF es un complejo, y PrrF y PrrH son ARN pequeños;
- y lo que encontró la revisión independiente de la rama: `foto_sana` y
  `reparsear` miran la foto vigente (§4); el aviso del paso se repite hasta
  regenerar (§6); y lo ilegible o lo que falla al guardar ya no deja la
  extracción abierta (§3).

**4.17, medido y sin cambio de código.** La autorregulación por operón usa
`lexico.miembros_operon`, que incluye los operones sintéticos del texto. Sobre
la corrida 4:
- hay 8 000 pares marcados;
- 7 384 son la misma entidad y 616 son por operón;
- de los 616, 604 son operones de la tabla y solo 12 son sintéticos.

En la mayoría de esos 12 el regulador sí está entre los genes nombrados. ExsA
está en exsCBA, y AlgU es AlgT. Contarlos solo por tabla convertía en aristas
dos autorregulaciones reales y metía una falsa (MvfR → pqsBR, de «pqsBR
mutants»). Solo LasR → lasRI es discutible, y BioBERT lo da como
`no_relation`.

Se queda como está: `etapa2` está congelada, y el cambio movería el
`pares.jsonl` del entrenamiento en curso.
