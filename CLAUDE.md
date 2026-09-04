# CLAUDE.md

Contexto del proyecto. Se carga en cada sesion de Claude Code. Es la misma
fuente de verdad que lee Kiro desde `.kiro/steering/`: si las reglas divergen,
manda este archivo y hay que alinear el steering.

## Objetivo

Construir una red de regulacion genica (GRN) de *Pseudomonas aeruginosa* desde
la literatura. La red es un grafo dirigido: los nodos son genes y sus productos
reguladores; las aristas son relacion regulador -> gen blanco, con signo y,
cuando el texto lo dice, condicion.

El pipeline tiene cuatro pasos y tres capas. `PLAN.md` los define en detalle.

| Paso | Nombre | Capa | Paquete | Estado |
|---|---|---|---|---|
| 0 | Extraccion | — | `grn_etl/` | cerrado |
| 1 | Identificacion de elementos | bronce | `grn_bronce/` | foco actual |
| 2 | Verificacion | silver | `grn_verificacion/` | futuro |
| 3 | Consolidacion | gold | `grn_red/` | futuro |

**Regla de capas: el bronce se construye solo desde el texto.** La data de
validacion entra en el paso 2 (evaluacion y, con particion por PMID,
entrenamiento) y en el paso 3 (diff). Queda fuera de la logica de extraccion.

**El paso 1 entrega el *donde*, no el *si*.** Localiza menciones y oraciones
donde puede haber una relacion. Decidir si la relacion existe y cual es su
signo pertenece al paso 2. Una columna como `signo_sugerido` es una propuesta
lexica, no una afirmacion, y va etiquetada como tal.

### El paso 0, que ya esta cerrado

ETL de literatura biomedica desde PubMed. Recibe consultas booleanas,
descarga abstracts por lotes y mantiene el estado en SQLite. En un segundo
lote opcional descarga texto completo (XML de PMC, PDF de acceso abierto).

**El valor central es no volver a descargar lo que ya se tiene, y saber en
todo momento que se tiene.** Sin eso, cada estudiante del laboratorio corre su
propio script y baja los mismos articulos otra vez.

Lo usan varios miembros del laboratorio, no un solo desarrollador. Se opera
por CLI y por un tablero HTTP local (`servidor.py`), que son dos frentes
sobre las mismas capas. Eso manda sobre cuatro decisiones de diseno: **la base
es la fuente de verdad compartida**, no archivos locales; las consultas se
registran con nombre para que otros las reutilicen; las corridas quedan en
bitacora; y nada depende de que un humano este mirando la terminal.

Cinco principios de producto, en orden:

1. **Idempotencia sobre todo.** Correr una consulta dos veces no debe generar
   trafico la segunda. Romperlo es un defecto grave, no una regresion menor.
2. **Reanudable.** Una corrida interrumpida a la mitad se retoma sin perder lo
   hecho: **el estado se escribe despues de cada lote, no al final.**
3. **Simple antes que completo.** Una funcion clara que hace una cosa le gana a
   una abstraccion generica. No se agregan capas por si acaso.
4. **Solo acceso abierto.** Lo que no lo es se exporta como lista de pendientes
   para pedirlo por biblioteca.
5. **Ciudadano respetuoso de las APIs.** NCBI bloquea por IP, no por usuario:
   rebasar el limite deja sin servicio a todo el laboratorio.

Sigue fuera de alcance traer fuentes distintas a PubMed y PMC (Scopus, Web of
Science), y exponer una interfaz publica o multiusuario con autenticacion. El
tablero local si esta dentro: es la logica del CLI vista por el navegador.

**El proyecto no termina en el ETL.** `etapa2/` prepara los datos del
clasificador de relaciones y lanza su barrido: no entrena aqui, y el modelo
—BioBERT afinado en cuatro clases— es del servidor del asesor, no de este
repositorio. Vale la pena saber tres cosas antes de tocar nada de ahi: se
entreno con *E. coli* y se aplica a *P. aeruginosa*; su metrica reportada
estaba contaminada porque el 73.9% del conjunto de prueba ya se habia visto en
entrenamiento; y `etapa2/particionar.py` marca como RECHAZADA y sale con codigo 1
cualquier particion en la que detecte esa contaminacion. El panorama esta en
`docs/informe-seminario-1.md` y el detalle en `etapa2/README.md` y
`docs/ficha-modelo-bert.md`.

## Restricciones duras

**Libreria estandar de Python 3.8+, con una excepcion acotada.**

- **Solo estandar, sin excepciones:** `grn_etl/`, `servidor.py`, `trabajos.py`
  y `etapa2/`. El codigo corre en maquinas de laboratorio (Linux y Windows) sin
  permisos de administrador y a veces sin salida a PyPI. Si una tarea parece
  necesitar `requests`, `pandas` o `lxml`, resolverla con `urllib.request`,
  `sqlite3` y `xml.etree.ElementTree`, y explicar la alternativa en un
  comentario.
- **`grn_bronce/` puede usar terceros** declarados en `pyproject.toml` como
  extra `[bronce]`, e instalados solo dentro del venv del proyecto. Aprobados
  hoy: **openpyxl** y **PyMuPDF**. Cualquier otro se aprueba antes de usarse.

La excepcion no es una puerta abierta: lo que se apoya en un tercero deja de
correr donde no se puede instalar. Los CSV son el producto canonico de toda
exportacion y se generan siempre con estandar; el `.xlsx` es comodidad encima.

`etapa2/clasificar.py` es la unica pieza que importa `torch` y `transformers`,
y por eso los demas scripts la invocan por subprocess.

**Acentos: segun quien lo lea.** La regla depende de si el texto es para un
humano o es un identificador.

- **Texto que lee un humano lleva acentos correctos.** Etiquetas y mensajes
  del tablero, salida de terminal del CLI, encabezados de CSV, titulos,
  comentarios, docstrings, documentacion. Se escribe "Año", "Título",
  "búsqueda", "año mínimo": la palabra correcta del espanol en cada caso, no
  una lista cerrada de excepciones.
- **Los identificadores van siempre en ASCII sin acentos.** Nombres de
  variables, funciones, clases, tablas, columnas de SQL, claves del JSON de la
  API, atributos `data-*` y valores de `id=` del HTML. `anio` sigue siendo
  `anio` como columna, como clave de JSON y como id de elemento. Cambiarlo
  rompe la base de 2263 documentos y el contrato de la API.

La razon del corte: la ene con virgulilla y las vocales acentuadas existen en
cp1252, asi que imprimen bien en la consola de Windows. Lo que si truena ahi
es lo que cae fuera de Latin-1 (una sigma griega, por ejemplo), y por eso los
archivos de datos se escriben siempre con `encoding="utf-8"` explicito.

Nombres de funciones y tablas en espanol. Los identificadores de dominio
externo se quedan como estan: `pmid`, `pmcid`, `doi`, `abstract`,
`mesh_terms`. Sin emojis en ningun lado.

**Nunca escribir credenciales en el codigo.** La API key sale de
`NCBI_API_KEY` o del archivo `.key`; el correo, de `NCBI_EMAIL`, del flag
`--email` o del archivo `.correo`. El entorno gana sobre el archivo. Lo
resuelve `grn_etl/credenciales.py`, que usan igual el CLI y el tablero, y los
dos archivos los cubre el `.gitignore`.

Desde el tablero se configuran en «Credenciales de NCBI». La regla ahi es que
**la llave se puede escribir pero nunca leer**: `GET /api/config` dice si hay
llave y de donde salio, jamas su valor, y hay una prueba que falla si la llave
real aparece en alguna respuesta.

**Rutas de datos: `GRN_DATOS`**, con esta precedencia y no otra:

1. flag explicito (`--db`, `--fulltext`, ...)
2. variable de entorno `GRN_DATOS`
3. `./datos` por omision

En la maquina del laboratorio `GRN_DATOS` apunta fuera del repositorio. Las
rutas literales que quedan se reemplazan **al tocar cada archivo**, no en un
barrido masivo: un barrido sobre codigo que nadie esta leyendo es la forma mas
barata de romper algo sin enterarse.

## Confidencialidad

- **No leer, listar ni citar el contenido de `datos/validacion/`, de
  archivos `*.db` ni de `.env`.** Ahi es donde viven los datos del
  laboratorio cuando lleguen. El resto de `GRN_DATOS` --el corpus de
  PubMed, que es publico-- es el insumo del paso 1 y se lee con normalidad:
  una regla mas ancha que lo que protege bloquea el trabajo sin ganar
  confidencialidad.
- **Los datos del laboratorio son confidenciales**: la base curada v2 y los
  parrafos etiquetados. Nunca se copian a fixtures, pruebas, documentacion,
  prompts ni mensajes. Se consultan solo por sus tablas
  (`validacion_interacciones`, `particion`) y solo en los pasos 2 y 3. **Lo
  permitido es esquema y conteos; volcar filas esta prohibido.**
- Los archivos que vienen del servidor del asesor
  (`entity_marked_*.jsonl`, `ecoli_curated.tsv`, `bio_bert_re_finetune.py`,
  `run_sweep_biobert.sh`, `summarize_sweep.py`) estan en `.gitignore` a
  proposito: son trabajo de otra persona y este repositorio tiene remoto
  publico.
- `salidas/` tambien esta ignorado.

## Estructura

```
CLAUDE.md              las reglas; esto
PLAN.md                los cuatro pasos, sus tablas y sus contratos
cli.py                 el CLI del paso 0
servidor.py            tablero HTTP local (127.0.0.1); hermano de cli.py
web/index.html         el tablero entero en un archivo, sin CDN ni dependencias
grn_etl/               paso 0, cerrado
  db.py                  esquema SQLite y todo el SQL del paso 0
  pubmed.py              clientes de E-utilities, PMC, Europe PMC, Unpaywall
  etl.py                 orquestacion
  trabajos.py            gestor de trabajos en segundo plano, uno a la vez
  credenciales.py        entorno primero, archivo despues
grn_bronce/            paso 1, en construccion
  texto.py               segmentacion en oraciones y offsets absolutos
  secciones.tsv          etiqueta h2 -> clase de seccion
grn_comun/             lo que usan los tres pasos
  procedencia.py         huella por contenido de cada eslabon de la cadena
pruebas/               las del paso 0; falsos.py deja urlopen inutilizable
etapa2/                congelada; migra a grn_verificacion/ cuando el paso 1
                       reporte metricas. Ver etapa2/README.md
docs/
  bitacora.md            que se hizo, cuando y que decision quedo abierta
  hallazgos.md           los hechos medidos, con su medicion
  decisiones.md          las decisiones de diseno y por que se tomaron asi
.kiro/steering/        lo que lee Kiro; apunta a CLAUDE.md y PLAN.md
datos/                 ignorado: la base y el full text. Ruta por GRN_DATOS
salidas/               ignorado: exportaciones
```

## Arquitectura

Dos frentes de entrada sobre las mismas capas. `trabajos.py` es la capa de
servicio: existe solo para que el HTTP no tenga que esperar a una corrida de
varios minutos.

```
cli.py       -------------------------\
                                       >-- etl.py --> db.py
servidor.py --> trabajos.py ----------/           --> pubmed.py
                     |
                     +--> db.py   (solo para abrir conexion y la hora)

web/index.html --HTTP--> servidor.py
```

Seis reglas que no se rompen:

1. **Solo `db.py` escribe SQL.** Cada paquete tiene el suyo y administra
   unicamente sus tablas. Si otra capa necesita una consulta nueva, se agrega
   una funcion en `db.py`. Nunca un `con.execute()` en `etl.py`,
   `servidor.py`, `cli.py` ni `trabajos.py`.
2. **`pubmed.py` no conoce la base.** Recibe parametros, devuelve
   diccionarios. No importa `db`. Eso la hace probable sin red.
3. **`print()` solo en puntos de entrada.** Son puntos de entrada el `cli.py`
   de cada paquete y los scripts autonomos de `etapa2/`, que se invocan
   directamente. Los modulos de orquestacion, de base de datos y los clientes
   reportan por callback o por logging: `etl.py` recibe un callable `log` con
   default vacio, el CLI le pasa `print` y el gestor de trabajos le pasa su
   acumulador de lineas, que es lo que el tablero sondea.
4. **`cli.py` no tiene logica de negocio.** Parsea, llama a la orquestacion,
   formatea.
5. **`servidor.py` tampoco.** Valida lo que llega, llama a `db`, `etl` o
   `trabajos`, y formatea JSON. La pieza que importa es `manejar(metodo, ruta,
   params, cuerpo, ctx) -> (codigo, objeto)`: una funcion normal que no abre
   sockets ni lee del disco, y por eso las pruebas cubren el API completo sin
   levantar un puerto.
6. **`trabajos.py` no importa `etl`.** Recibe el callable a correr, asi que
   sirve igual para `ingestar()` que para `descargar_fulltext()` y las pruebas
   de concurrencia no arrastran el ETL.

Dependencia en una sola direccion: `cli -> orquestacion -> db / clientes`.
Ningun modulo salta capas. `grn_comun/` es la excepcion prevista: lo que usan
los tres pasos por igual (hoy `procedencia.py`) vive ahi para que ninguno
tenga que importar de lado.

Esta separacion es lo que permitio montar el tablero sin tocar la logica, y lo
que permitiria montar FastAPI manana. Si una propuesta obliga a cruzar estas
fronteras, casi siempre hay una alternativa que no lo hace.

**Estilo.** Tono directo. Los comentarios explican **por que**, no **que**: uno
que parafrasea la linea siguiente sobra, y uno que cuenta el defecto que la
motivo vale por tres. Preferir lo simple: una funcion de 30 lineas legible le
gana a tres clases con herencia. Type hints opcionales; si se usan, que sean
consistentes dentro del modulo.

## Modelo de datos

Un solo archivo SQLite compartido por todos los pasos. Cada paquete crea y
administra unicamente sus tablas.

**Paso 0 — `grn_etl/db.py`:**

| tabla | rol |
|---|---|
| `consultas` | la query booleana con nombre |
| `ejecuciones` | bitacora de cada corrida del ETL |
| `documentos` | un articulo, unico por PMID |
| `consulta_documento` | que consulta trajo que documento (N a N) |
| `descargas` | estado de full text por PMID y tipo (`xml` / `pdf`) |
| `corpus` | un conjunto de documentos congelado con nombre |
| `corpus_documento` | que documentos entraron en ese corpus (N a N) |

**Paso 1 — `grn_bronce/db.py`:** `corridas`, `texto_unidades`, `menciones`,
`oraciones_candidatas`.

Ojo con los nombres reales: la columna de estado de `descargas` se llama
**`estatus`**, no `estado`.

**La separacion entre `documentos` y `consulta_documento` es la decision de
diseno central.** Un articulo que aparece en cinco consultas se almacena una
vez y se liga cinco veces. Sin esa separacion, cada consulta nueva volveria a
descargar todo el solapamiento, que en este dominio es enorme.

De ahi sale la idempotencia. El flujo de `ingestar()`:

1. `esearch` trae la lista completa de PMIDs, sin descargar contenido.
2. Se resta contra `documentos` via `db.pmids_conocidos()`.
3. `efetch` solo de la diferencia.
4. Se vinculan **todos** los PMIDs a la consulta, no solo los nuevos.

El paso 4 importa: un articulo que ya estaba por otra consulta igual
pertenece a esta.

Romper la idempotencia es un defecto grave, no una regresion menor.

### Donde vive la idempotencia

| operacion | mecanismo |
|---|---|
| alta de consulta | `SELECT` por nombre; si existe, actualiza |
| insercion de documento | `ON CONFLICT(pmid) DO NOTHING` |
| vinculo consulta-documento | `ON CONFLICT(consulta_id, pmid) DO NOTHING` |
| creacion de corpus | `ON CONFLICT(corpus_id, pmid) DO NOTHING`, y `ValueError` si el nombre ya existe con otro conjunto |
| descarga de full text | `UNIQUE(pmid, tipo)` mas el filtro de `pendientes_descarga()` |

El dialecto es `ON CONFLICT ... DO NOTHING / DO UPDATE`; en este proyecto no se
usa `INSERT OR IGNORE`. Toda tabla nueva necesita su clave natural declarada
(PK compuesta o `UNIQUE`) **antes** de poder ser idempotente: sin indice donde
apoyarse, el `ON CONFLICT` falla.

`pendientes_descarga()` excluye por omision los marcados `no_disponible`: no
tienen acceso abierto y reintentarlos solo gasta peticiones. Los que quedaron
en `error` si se reintentan, pero unicamente con `--reintentar` explicito. Son
tres estatus y no dos, y la distincion es la misma de siempre: **"no hay"
contra "no pude preguntar"**.

### Convenciones de nombres y formatos

- Tablas y columnas en espanol, minusculas, plural para tablas.
- **Timestamps en ISO 8601 UTC como TEXT** (`db.ahora()`). SQLite no tiene tipo
  fecha; guardar ISO permite ordenar y comparar como cadena.
- **Las listas se guardan como JSON en una columna TEXT** (autores, MeSH,
  keywords) y se deserializan con `db.a_dict()`, que tolera JSON corrupto
  devolviendo lista vacia.
- **Los booleanos son INTEGER** con `NOT NULL DEFAULT`.
- `pmid` es **TEXT**, no INTEGER: cualquier llave foranea hacia `documentos`
  tiene que serlo tambien.
- Los archivos de full text se nombran `{pmid}_{pmcid}.xml` y `{pmid}.pdf`,
  para poder rastrear el origen desde el nombre.

### Corpus y trazabilidad de corridas

**El paso 1 recibe la lista de documentos por `corpus_id`, y por ninguna otra
via.** Esa es la lista completa de PMIDs. Sin eso, cada script decide por su
cuenta que mirar y dos metricas dejan de ser comparables sin que nada avise.
Un corpus congelado no cambia: `crear_corpus()` lanza `ValueError` si el mismo
nombre apunta a otro conjunto.

**Toda corrida de procesamiento registra una fila en `corridas`** (`paso`,
`metodo`, `version`, `parametros`, `fecha`, `corpus_id`) **antes** de procesar,
y **procesa solo las unidades sin resultado para su par `(metodo, version)`**.
Re-ejecutar es seguro.

Dos detalles que ya costaron caro una vez cada uno:

- El filtro `(metodo, version)` va en el `ON` del `LEFT JOIN`, **nunca en el
  `WHERE`**: al `WHERE`, las filas caen fuera del join y vuelven a quedar
  pendientes en cada corrida.
- La resta se hace contra **las filas de resultado**, jamas contra
  `corridas.estatus`. Una corrida cortada con Ctrl-C queda marcada
  `'corriendo'` para siempre y nadie la limpia; si la resta la mirara, una
  corrida zombi la engañaria.

Toda fila del bronce apunta a su `corrida_id` y, por la unidad de texto, a su
PMID y su fuente. Los offsets son absolutos sobre el texto original de la
unidad. Todo es exportable a CSV.

## Comandos

```bash
python3 cli.py query add <nombre> --archivo queries/<x>.txt
python3 cli.py run <nombre> [--limite N] [--orden pub_date]
python3 cli.py fulltext --tipo xml      # primero XML
python3 cli.py fulltext --tipo pdf      # luego PDF
python3 cli.py estado
python3 cli.py log
python3 cli.py export <nombre> --formato jsonl
python3 cli.py export --pendientes      # los que faltan, para la biblioteca

python3 cli.py corpus crear --nombre v1 --consulta <nombre>
python3 cli.py corpus list | cobertura | verificar --nombre v1

python3 servidor.py --abrir             # tablero en http://127.0.0.1:8765
```

El tablero hace lo mismo que el CLI desde el navegador y ademas deja corregir
a mano un titulo o un anio que llego mal. Escucha solo en 127.0.0.1 y corre un
trabajo a la vez. `web/index.html` abierto con doble clic no sirve: la pagina
pide sus datos a `/api/...`, que lo sirve `servidor.py`.

**El tablero no carga nada de internet, y eso no es negociable.** Todo el CSS
y el JavaScript viven dentro de `web/index.html`. Una tipografia, un paquete
de iconos o una biblioteca de graficos traidos de un CDN dejan la pagina rota
justo en la maquina sin salida a internet, que es la que este proyecto tiene
que atender. Si hace falta algo asi, se vendora y se sirve desde la lista
blanca de `servidor.py`, a sabiendas de que el tablero deja de ser un archivo
autocontenido. Hay una prueba que falla si aparece un `src` o `href` externo.

Fuera de `/api/`, `servidor.py` sirve **dos** archivos y nada mas: `/` (la
pagina) y `/logo.png` (el escudo). La comparacion es por igualdad exacta
contra rutas fijas que salen de `__file__`, no por prefijo: en la raiz viven
`.key`, la base y el codigo, y apuntar un manejador de archivos estatico ahi
los expondria.

Bajo `/api/` hay dos rutas que si entregan archivos del corpus:
`/api/documentos/<pmid>/texto` y `/api/documentos/<pmid>/pdf`. La ruta de
disco **se arma con el PMID y el PMCID validados** (`^\d{1,12}$` y
`^PMC\d{1,12}$`) mas la convencion de nombres, nunca leyendo
`descargas.ruta`, y se comprueba que quede dentro de la carpeta de salida.
Ojo con el PMCID: esta en `db.COLUMNAS_EDITABLES`, o sea que se puede
escribir desde el tablero, asi que venir de la base no lo hace de fiar. Ver
`docs/decisiones.md`.

El aspecto es el sistema Nocturne, cuya referencia esta en
`web/UI mockups request/` (no se sirve ni se ejecuta: es un lienzo de diseno y
carga React desde CDN). Los tokens estan copiados al `:root` de `index.html`.
Es oscuro por decision, sin bloque de `prefers-color-scheme`: mantener los dos
temas era mantener dos tableros. Los botones van delineados, nunca rellenos.
Ver `docs/decisiones.md`.

`run` siempre antes que `fulltext`. Dentro de `fulltext`, `xml` antes que
`pdf`: el JATS de PMC llega con secciones separadas y pies de figura
identificados; un PDF re-parseado pierde subindices de genes y entrelaza
columnas. El XML alimenta al clasificador; el PDF es para lectura humana.

## Pruebas

```bash
python3 -m unittest discover           # raiz: paso 0, grn_bronce y grn_comun
python3 -m unittest discover etapa2    # etapa2 no tiene __init__.py
```

Son dos comandos, no uno: `etapa2/` no es un paquete, asi que el `discover` de
la raiz no lo recoge. Los paquetes nuevos si lo son y por eso caen en el
primero.

Ninguna prueba toca la red: se inyecta `pruebas.falsos.ClienteFalso`, que
devuelve XML o JSON fijo y registra cada llamada. Ademas `PruebaSinRed` deja
`urlopen` inutilizable, asi que una prueba que arme un `Cliente` de verdad
falla en vez de salir a NCBI.

Las pruebas que no pueden faltar:

- **Idempotencia del ETL**: correr la misma ingesta dos veces y verificar que
  la segunda no llama a `efetch`
  (`pruebas/test_idempotencia.py::PruebasSegundaCorrida`).
- **El corte de oracion no se mueve**
  (`grn_bronce/test_texto.py::PruebasGolden`). La union de `evaluar_signo.py`
  con las oraciones auditadas es por igualdad de texto, sin identificador
  estable, y su guardian solo salta por debajo de 80 de 93 uniones.
- **La frontera de la contaminacion**
  (`etapa2/test_contaminacion.py`). Vigila los tres paquetes: si el patron de
  oro entra al diccionario, al generador de pares o a la calibracion de
  umbrales, las metricas dejan de medir lo que el pipeline encuentra y pasan a
  medir lo que le sopla el oro, con la misma etiqueta y la misma pinta de
  correcto.

## Flujo de trabajo

- Rama **`bronce`**. Commits pequenos, con mensaje en espanol que nombre el
  modulo tocado.
- Antes de crear un modulo nuevo, revisar que no exista ya en `PLAN.md` con
  otro nombre.
- **Cambios de esquema: proponer el DDL y esperar confirmacion** antes de
  aplicarlo. Las migraciones son aditivas.
- Al cerrar una sesion de trabajo, agregar una entrada fechada en
  **`docs/bitacora.md`**: que se corrio, con que version, resultado y decision
  pendiente. Cada experimento queda ademas como fila en `corridas`, asi que la
  bitacora registra decisiones y la base registra hechos.
- Los tags fijan lo que ya no se mueve: `v0-extraccion` (paso 0 cerrado) y
  `v1-corrida-27ago` (la primera corrida completa sobre *P. aeruginosa*).

## Maquina del laboratorio

- La GPU es compartida: correr `nvidia-smi` antes de lanzar nada y terminar
  los procesos propios al acabar.
- Usuario, carpeta y venv propios. El repositorio se clona por git, sin copias
  sueltas. `GRN_DATOS` vive fuera del repositorio y con respaldo.
- SQLite es de un solo escritor: el archivo de la base se mueve entre entornos
  como snapshot, nunca se edita en dos lugares a la vez.
- Si un experimento supera 4 horas o el modelo no cabe en VRAM con lote de 8 y
  512 tokens, detenerlo y anotarlo en la bitacora. La decision de moverlo a la
  nube la toma el responsable, segun `PLAN.md` seccion 7.
- **Claude Code en esa maquina**: aviso por escrito al asesor de que se usa y
  de que el codigo y los fragmentos abiertos en sesion se envian a Anthropic.
  Trabajo restringido a la carpeta propia y al repositorio; la base curada v2 y
  los parrafos etiquetados quedan fuera de toda sesion. Sesion con la cuenta
  personal, sin credenciales en perfiles de shell compartidos.

## Fuera de alcance

- Modificar archivos fuera del repositorio o del venv del proyecto.
- Usar `sudo`, cambiar configuracion del sistema o instalar paquetes globales.
- Ejecutar Playwright u otros navegadores. Desactivado por omision.
- **Crear `grn_verificacion/` o `grn_red/` antes de que el paso 1 reporte sus
  metricas.** Los pasos 2 y 3 estan descritos como panorama en `PLAN.md`,
  no como trabajo abierto.
- **`etapa2/` se conserva congelada**: sin cambios funcionales, solo lo que
  exija una mudanza de modulos o una correccion de error. Se migra a
  `grn_verificacion/` cuando el paso 1 tenga metricas. Que ya exista codigo de
  clasificacion ahi no reabre el paso 2.

## APIs externas

| Servicio | Uso | Limite |
|---|---|---|
| NCBI E-utilities | `esearch`, `efetch` de PubMed y PMC | 3 req/s sin key, 10 con |
| PMC ID Converter | PMID a PMCID/DOI | 200 IDs por peticion |
| PMC OA Service | localizar PDF del subset abierto | sin limite documentado |
| Europe PMC | localizar PDF de articulos de PMC fuera del subset abierto | sin limite documentado |
| Unpaywall | localizar PDF abierto por DOI | 100k/dia, exige correo |

Las queries booleanas van por **POST**, nunca GET: rebasan los 700 caracteres.

**Manejo de errores.** Toda peticion de red lleva reintentos con retroceso
exponencial y tope. HTTP 400 de NCBI es query mal formada: fallar de inmediato
con el cuerpo de la respuesta, sin reintentar. HTTP 404 de Unpaywall es DOI no
registrado: es un resultado valido, devolver `None`, no lanzar. Los fallos de
un articulo no abortan el lote; se registran en `descargas` con estatus
`error` y el lote sigue. Las excepciones de una ejecucion completa se guardan
en `ejecuciones.error` **antes** de propagarse.

Solo se descarga lo que PMC, Europe PMC y Unpaywall exponen legalmente, y en
el caso de Europe PMC se respeta su campo `availabilityCode`: no se adivina.
No implementar nada que evada muros de pago ni controles de acceso, y eso
incluye un navegador headless para pasar los desafios de las editoriales: es
dependencia y es evasion. La via formal para contenido con suscripcion es el
acceso institucional de la UNAM y, para Elsevier, su API de TDM con clave
institucional. Lo que no es abierto se exporta como lista de pendientes con su
liga, para pedirlo por biblioteca.

**Pseudomonas Genome DB es una via cerrada.** El diccionario PAO1 se construye
desde RefSeq, KEGG y UniProt; su procedencia esta en
`grn_bronce/recursos/PROCEDENCIA.md`. Ver `docs/hallazgos.md`.

## Dominio

Los nodos de la red son genes; las aristas son relaciones de regulacion.
Tres clases: `activator`, `repressor`, `regulator` (este ultimo cubre los
casos donde el articulo establece la relacion sin resolver el signo).

Nomenclatura bacteriana: gen en minusculas mas mayuscula (`lasR`, `mexT`),
proteina capitalizada (`LasR`, `MexT`): misma entidad, hay que normalizarlas
juntas. Operones como `mexEF-oprN`. Locus tags de PAO1 como `PA0762`.
Factores sigma (`RpoS`, `AlgU`) suelen ser hubs de la red.

Cualquier reconocimiento de genes por patron produce falsos positivos y no
sustituye al reconocimiento de entidades. Dejarlo explicito en el docstring
donde se use.

**Sospechar del vocabulario de *E. coli*.** El clasificador heredado se entreno
con ese organismo, y sus nombres se cuelan. Todo simbolo que llegue de ese lado
se comprueba contra `genes_pao1.tsv` antes de darlo por bueno.

**Contra las colisiones con el ingles, `sensible_mayusculas` y no una lista
negra.** Un simbolo de gen puede ser palabra comun en minusculas; la defensa es
exigir coincidencia exacta de mayusculas en esa fila, no borrar la entrada.
Borrarla se lleva por delante las menciones correctas del mismo gen.

Las mediciones de las dos reglas anteriores estan en `docs/hallazgos.md`.

## Deuda conocida, en orden de riesgo

1. **Limitador de tasa por instancia.** Vive en `pubmed.Cliente._ultima`. Con
   varios workers cada uno cree que respeta el limite mientras el conjunto lo
   rebasa. NCBI bloquea por IP, no por usuario: un worker mal portado deja sin
   servicio a todo el laboratorio. Solucion: token bucket en Redis, cambiando
   solo el cuerpo de `_esperar()`.
2. **SQLite serializa escrituras.** Dos ingestas simultaneas dan `database is
   locked`. WAL y `busy_timeout` cubren el caso comun (el tablero leyendo
   mientras el ETL escribe), no dos escritores de verdad. La migracion a
   Postgres toca solo `db.py`. No migrar antes de tiempo: con un solo escritor
   SQLite basta.
3. **El PDF no alimenta al clasificador.** De los articulos que estan en PMC
   fuera del subset abierto no existe texto legible por maquina en ninguna
   parte: lo que se obtiene son PDFs para lectura humana. Un PDF re-parseado
   pierde subindices de genes y entrelaza columnas, que es justamente por lo
   que existe el JATS. Con PyMuPDF aprobado el camino queda abierto para el
   bronce, pero hay que **medir cuanto texto util sale** antes de confiar en
   el: hoy el corpus del clasificador solo crece con `fulltext --tipo xml`.

## Pendientes de la auditoria contra la documentacion de NCBI

Se audito `pubmed.py` contra NBK25497 y NBK25499. Veinte puntos salieron
conformes (host correcto, `tool` y `email` en toda peticion, POST para las
queries largas, `retmax` y `retmode` validos, lotes en vez de una peticion por
articulo, 180 IDs por llamada al ID Converter). Lo que quedo abierto:

1. **El OA Service de PMC esta anunciado para retiro.** El aviso del 30 de
   julio de 2026 dice que a partir del 24 de agosto dejan de estar los
   archivos heredados, incluida la API del OA Web Service que usa
   `liga_pdf_pmc()`. Ya se blindo el sintoma: si el servicio no contesta se
   lanza `ErrorPubMed` y la fila queda como `error` (reintentable) en vez de
   `no_disponible` (permanente). Falta lo de fondo: mover la localizacion del
   PDF al PMC Cloud Service en AWS. Toca solo `liga_pdf_pmc()`.
2. **El correo que se manda a NCBI es el del estudiante que corre, no el del
   mantenedor.** NBK25497 pide "the software developer and not that of a
   third-party end user", y pide registrar `tool` y `email` escribiendo a
   eutilities@ncbi.nlm.nih.gov. Sin registro, si NCBI bloquea la IP no tiene a
   quien avisar y el servicio no se restablece hasta registrarlo. Arreglo:
   separar el correo de mantenedor (fijo, del laboratorio) del correo de quien
   corre.
3. **Nada sabe que hora es.** NBK25497 pide limitar los trabajos grandes a
   fines de semana o entre las 21:00 y las 5:00 hora del Este, con la misma
   sancion de bloqueo por IP que la tasa de peticiones. Un `fulltext` sobre
   mil documentos a media manana cae justo en la ventana que pide evitar.
   Arreglo: que `cli.py` estime las peticiones antes de lanzar y avise.
4. **No usamos EPost ni el History server.** Pasamos listas explicitas de
   PMIDs en lotes de 200. Es una via documentada y va por POST, asi que no
   incumple nada, pero el 200 se eligio como si fuera un tope y no lo es: la
   documentacion ejemplifica con 500. Subirlo es una linea; usar EPost es lo
   alineado con "Minimizing the Number of Requests".
5. **No detectamos el mensaje de limite rebasado.** NBK25497 documenta que
   NCBI responde `{"error":"API rate limit exceeded"}`. `Cliente` solo mira el
   estatus HTTP, asi que si ese cuerpo llega con 200 se toma por bueno y
   revienta despues en el parseo de XML, con un mensaje que no dice lo que
   pasa.
6. **Falta el aviso de exencion de responsabilidad.** NBK25497 usa "must":
   quien use E-utilities dentro de software tiene que mostrar a sus usuarios
   la liga a https://www.ncbi.nlm.nih.gov/About/disclaimer.html . Son tres
   lineas: pie del tablero, epilogo del CLI y parrafo del README.
7. **Umbral para dejar E-utilities.** Si el corpus objetivo llega de forma
   sostenida a decenas de miles de articulos, la via que NCBI senala no es mas
   paginacion sino la descarga local de MEDLINE/PubMed.

## Deuda resuelta

**El 403 de los editores costaba cuatro peticiones y 14 segundos por
articulo.** `Cliente.get()` ahora trata 401, 403, 404, 422 y 451 como
definitivos: una peticion y cero espera. Y como parte del mismo cambio, `get()`
lanza `ErrorPubMed` al agotar los intentos en vez de devolver `None`, para que
el contrato sea el mismo en todas las capas: **`None` = el servidor contesto y
la respuesta es no; excepcion = no pude preguntar.** Sin eso, tratar el 403
como `no_disponible` habria hecho que un corte de red marcara un lote entero
como permanentemente inaccesible.

**`cli.py::cmd_export` ya no tiene SQL crudo.** La consulta de `--pendientes`
paso a `db.pendientes_biblioteca()`, que ademas corrige el filtro (antes solo
miraba el XML, asi que un articulo con PDF ya bajado seguia saliendo en la
lista) y agrega la nota y la liga del ultimo intento. Ya no queda SQL fuera de
`db.py`.

**Corridas largas no caben en una peticion HTTP.** Lo resolvio
`trabajos.Gestor`: `POST /api/trabajo` lanza la funcion en un hilo daemon,
contesta 202 de inmediato y el tablero sondea `GET /api/trabajo` para ver las
lineas de bitacora en vivo.

Queda un limite y es deliberado: **un trabajo a la vez, por proceso.** El
segundo recibe 409. Es lo que mantiene una sola instancia de `pubmed.Cliente`
respetando el limite de NCBI y un solo escritor sobre SQLite. Como el candado
es por proceso, dos servidores serian dos gestores creyendo cada uno que es el
unico; por eso `allow_reuse_address` se desactiva en Windows (ver
`docs/decisiones.md`). El tope solo se podra subir cuando existan el limitador
compartido del punto 1 y Postgres del punto 2.

**El corte de oracion ya no depende de un guardian de tiempo de corrida.**
`texto.oraciones()` es un envoltorio de `oraciones_con_offset()`, asi que hay
una sola implementacion, y `grn_bronce/test_texto.py` fija las 93 oraciones
auditadas como golden. Antes, mover un corte solo se descubria corriendo
`evaluar_signo.py` y solo si el dano pasaba de trece filas.
