# ETL de PubMed para redes de regulación génica

Descarga literatura de PubMed a partir de consultas booleanas con nombre,
guarda los abstracts en SQLite y, en un segundo paso, baja el texto completo
que esté en acceso abierto (XML de PMC, PDF de PMC OA o Unpaywall).

Es la primera etapa de un pipeline cuyo fin es inferir relaciones regulatorias
entre factores de transcripción y genes en *Pseudomonas aeruginosa*, para
construir una red de regulación génica. Este repositorio no analiza el texto:
lo consigue, lo mantiene ordenado y lo entrega. La extracción de relaciones
vive en etapas posteriores que consumen esta salida.

## Por qué existe

Sin esto, cada estudiante corre su propio script, vuelve a bajar los mismos
artículos y nadie sabe qué hay ya descargado. Las consultas de *P. aeruginosa*
se solapan muchísimo entre sí, así que el desperdicio no es marginal: es la
mayor parte del trabajo.

Las dos cosas que el sistema garantiza son **no volver a descargar lo que ya se
tiene** y **saber en todo momento qué se tiene**. Correr la misma consulta dos
veces no genera tráfico de descarga la segunda vez, y una corrida interrumpida
se retoma sin perder lo hecho.

Eso también protege al laboratorio entero: NCBI limita por IP, no por usuario.
Un script que baja de más deja sin servicio a todos los que comparten la salida
a internet, incluso a quienes no estaban usando nada.

## Requisitos

- Python 3.8 o superior. Nada más.
- **Cero dependencias.** No hay `pip install`, no hay entorno virtual
  obligatorio, no hay `requirements.txt`. Todo sale de la biblioteca estándar
  (`urllib.request`, `sqlite3`, `xml.etree.ElementTree`, `http.server`). Es a
  propósito: el código corre en máquinas del laboratorio con Windows y Linux,
  sin permisos de administrador y a veces sin salida a PyPI.
- Conexión a internet para `run` y `fulltext`. Los comandos de consulta
  (`estado`, `log`, `export`) y el tablero funcionan sin red.

En los ejemplos se escribe `python3`, que es lo normal en Linux. En Windows
casi siempre es `python`.

## Credenciales de NCBI

NCBI pide un correo de contacto para identificar el tráfico, y da un límite más
alto a quien use una API key: **3 peticiones por segundo sin llave, 10 con
llave**. El correo es obligatorio; la llave es opcional pero triplica la
velocidad de las corridas largas.

Para conseguir la llave: crear una cuenta en
<https://account.ncbi.nlm.nih.gov>, entrar a *Account settings* y en *API Key
Management* pulsar *Create an API Key*. La llave aparece una sola vez en esa
pantalla; se copia de ahí.

Ambas cosas se pasan por variables de entorno. **Nunca se escriben en el código
ni en ningún archivo del repositorio.**

```bash
# Linux o macOS, en la sesión actual
export NCBI_EMAIL="tu.correo@institucion.mx"
export NCBI_API_KEY="la_llave_que_te_dio_ncbi"
```

```powershell
# Windows PowerShell, en la sesión actual
$env:NCBI_EMAIL = "tu.correo@institucion.mx"
$env:NCBI_API_KEY = "la_llave_que_te_dio_ncbi"

# Windows, permanente (abre una terminal nueva para que tome efecto)
setx NCBI_EMAIL "tu.correo@institucion.mx"
setx NCBI_API_KEY "la_llave_que_te_dio_ncbi"
```

El correo también se puede dar en la línea de comandos con `--email`, útil
cuando varias personas comparten la misma máquina. La llave no: solo se lee de
`NCBI_API_KEY`, para que no quede en el historial de la terminal.

El `.gitignore` ya cubre `.env`, `*.key`, `datos/` y `salidas/`. Si aparece una
llave o un correo personal dentro de un archivo versionado, es un error, no una
comodidad.

## Flujo completo

Los comandos van en este orden. Cada uno depende de lo que dejó el anterior.

### 1. Registrar la consulta

```bash
python3 cli.py query add pa_regulacion --archivo pa_regulacion.txt \
    --descripcion "Regulación transcripcional en P. aeruginosa"
```

La consulta booleana vive en un archivo `.txt` para poder revisarla, comentarla
y versionarla; las del proyecto pasan de los 700 caracteres. Registrarla le da
un nombre estable: a partir de aquí todos los demás comandos hablan de
`pa_regulacion`, no de la query cruda.

Volver a correr `query add` con el mismo nombre actualiza el texto y conserva
los documentos ya vinculados. `python3 cli.py query list` muestra las
registradas, cuántos documentos trajo cada una y cuándo corrió por última vez.

### 2. Bajar los abstracts

```bash
python3 cli.py run pa_regulacion
```

Este es el paso que hace el trabajo interesante:

1. `esearch` trae la lista completa de PMIDs, sin descargar contenido.
2. Se resta contra lo que ya está en la tabla `documentos`.
3. `efetch` baja solo la diferencia, por lotes de 200.
4. Se vinculan **todos** los PMIDs a la consulta, no solo los nuevos.

El paso 4 es el que hace que valga la pena: un artículo que ya estaba en la
base porque lo trajo otra consulta igual pertenece a esta, y se liga sin
volver a descargarlo.

Opciones útiles: `--limite N` para probar con pocos, `--orden pub_date` para
traer primero lo reciente, `--desde 2010 --hasta 2024` para acotar por año.

### 3. Texto completo, primero XML

```bash
python3 cli.py fulltext --tipo xml
```

### 4. Texto completo, luego PDF

```bash
python3 cli.py fulltext --tipo pdf
```

**Por qué `run` va antes que `fulltext`:** `fulltext` no busca nada en PubMed.
Opera sobre lo que ya está en `documentos`, resolviendo el PMCID y el DOI de
cada artículo para ir a buscarlo. Sin `run` previo la lista de pendientes está
vacía y el comando no hace nada.

**Por qué `xml` va antes que `pdf`:** el JATS que entrega PMC llega con las
secciones separadas, las referencias aparte y los pies de figura
identificados. Un PDF reparseado pierde los subíndices de los nombres de genes
y entrelaza las columnas, que es justo lo que rompe el reconocimiento de
entidades después. El XML es el que alimenta al clasificador; el PDF es para
lectura humana. Además, la etapa de PDF es la lenta y la que más falla: sale a
los sitios de las editoriales, que responden 403 con frecuencia.

Ninguna de las dos etapas aborta por un artículo. Cada resultado queda
registrado en la tabla `descargas` como `ok`, `no_disponible` o `error`, así
que volver a lanzar el comando continúa con lo que falte. Los `error` se
reintentan con `--reintentar`; los `no_disponible` no, porque no tienen acceso
abierto y reintentarlos solo gasta peticiones.

### 5. Ver qué hay

```bash
python3 cli.py estado    # resumen: documentos, abstracts, descargas por estado
python3 cli.py log       # historial de corridas, con errores si los hubo
```

### 6. Exportar

```bash
python3 cli.py export pa_regulacion --formato jsonl   # -> salidas/pa_regulacion.jsonl
python3 cli.py export pa_regulacion --formato csv
python3 cli.py export --pendientes                    # -> salidas/pendientes_biblioteca.csv
```

`export --pendientes` es la lista de lo que **no** se pudo bajar, con el DOI y
las ligas a PMC, a PubMed y al editor, para pedirlo por la biblioteca
institucional.

## El tablero

Lo mismo que hace el CLI, pero en el navegador: ver las consultas, buscar entre
los documentos, corregir a mano un título o un año que llegó mal, revisar las
descargas y lanzar un `run` o un `fulltext` viendo la bitácora avanzar en vivo.

Al entrar explica qué es la herramienta y los cuatro pasos para usarla, así que
alguien que llega nuevo al laboratorio puede abrirlo sin haber leído esto.

```bash
python3 servidor.py --abrir
```

Arranca en <http://127.0.0.1:8765> y abre el navegador. Con `--puerto` se
cambia el puerto y con `--email` se da el correo si no está en el entorno; sin
correo el tablero arranca igual y deja ver y editar, pero no lanzar trabajos.

Dos cosas que conviene saber antes de usarlo:

- **Abrir `web/index.html` con doble clic no funciona.** La página no trae
  datos adentro: los pide por HTTP a `/api/...`, y ese API lo sirve
  `servidor.py`. Abierta como archivo no hay nadie del otro lado y la pantalla
  se queda vacía. Siempre por `python3 servidor.py`.
- **No carga nada de internet.** Todo el CSS y el JavaScript viven dentro de
  `web/index.html`, y el escudo institucional lo sirve el propio
  `servidor.py`. Es la misma razón por la que el Python es solo biblioteca
  estándar: en una máquina sin salida a internet el tablero se ve igual. Si
  algo va a agregarse ahí —una tipografía, un paquete de iconos, una
  biblioteca de gráficos— tiene que venir vendorado, nunca desde un CDN.
- **Escucha solo en 127.0.0.1**, es decir, únicamente desde la misma máquina.
  No tiene autenticación de ninguna clase y puede borrar documentos y gastar el
  límite de NCBI de todo el laboratorio, así que exponerlo a la red sería
  regalarle eso a cualquiera. Si algún día hace falta acceso remoto, va detrás
  de un túnel SSH, nunca cambiando el bind.

El servidor corre **un trabajo a la vez**. Si alguien ya lanzó una corrida, la
siguiente recibe un 409 hasta que la primera termine: es lo que mantiene una
sola instancia del cliente de NCBI respetando el límite de peticiones.

## Modelo de datos

Una sola base SQLite, `datos/grn.db`, con cinco tablas:

| tabla | qué guarda |
|---|---|
| `consultas` | la query booleana con su nombre y descripción |
| `ejecuciones` | bitácora de cada corrida: totales, nuevos, estado, error |
| `documentos` | un artículo, único por PMID |
| `consulta_documento` | qué consulta trajo qué documento (N a N) |
| `descargas` | estado del texto completo por PMID y tipo (`xml` / `pdf`) |

**La separación entre `documentos` y `consulta_documento` es la decisión de
diseño central.** Un artículo que aparece en cinco consultas se almacena una
vez y se liga cinco veces. Si el documento colgara de la consulta, cada
consulta nueva volvería a descargar todo el solapamiento, que en este dominio
es enorme; y no habría forma de responder "¿ya tenemos este PMID?" sin recorrer
consulta por consulta.

De ahí sale la idempotencia, y de ahí que `descargas` cuelgue del PMID y no de
la consulta: el texto completo de un artículo se baja una vez, sirva a la
consulta que sirva.

Los nombres de tablas y columnas están en español y sin acentos, y así se
quedan: son identificadores, no texto para leer.

## Qué se descarga y qué no

Solo se baja lo que PMC y Unpaywall exponen legalmente. No hay nada en este
código que evada un muro de pago ni que raspe páginas web, y no debe agregarse:
NCBI dirige el acceso programático a las E-utilities y bloquea por IP, o sea a
todo el laboratorio de una vez.

Lo que no es de acceso abierto no se descarga. Se exporta con
`export --pendientes` junto con su liga, para conseguirlo por la biblioteca.

## Resultados de una corrida real

Corte del 17 de agosto de 2026, con la consulta `pa_regulacion` sola. Después se
registraron más consultas y hoy la base tiene 2361 documentos; la diferencia está
explicada en `docs/informe-seminario-1.md`.

| medida | valor |
|---|---|
| documentos únicos | 2263 |
| con abstract | 2256 |
| texto completo en XML de PMC | 918 (183 MB en `datos/fulltext/xml`) |
| sin PMCID: no están en PMC | 738 |
| en PMC pero fuera del subset de acceso abierto | 607 |

Los tres últimos renglones suman 2263. Los 607 son el caso que más confunde:
PMC tiene el artículo y su página se lee en el navegador, pero la API solo
entrega los metadatos porque el editor no lo puso en el subset abierto. Esos y
los 738 salen en `export --pendientes`.

De los 2263, siete no traen abstract: son registros donde PubMed no lo publica
(erratas, comentarios editoriales).

## Pruebas

```bash
python3 -m unittest discover     # desde la raíz del proyecto
```

349 pruebas con `unittest` de la biblioteca estándar, en `pruebas/`. **Ninguna
toca la red.** Se inyecta `pruebas.falsos.ClienteFalso`, que devuelve XML o
JSON fijo y registra cada llamada; además, la clase base deja `urlopen`
inutilizable, así que una prueba que arme un cliente de verdad falla en vez de
salir a NCBI.

La prueba que no puede faltar está en `pruebas/test_idempotencia.py`: corre la
misma ingesta dos veces y verifica que la segunda no llama a `efetch`.

## Estructura

```
cli.py                 el CLI; el único que imprime
servidor.py            el tablero HTTP local, hermano de cli.py
web/index.html         el tablero entero en un archivo, sin dependencias
grn_etl/
  db.py                el esquema y TODO el SQL
  etl.py               orquestación; no imprime, reporta por callback
  pubmed.py            clientes de E-utilities, PMC y Unpaywall
  trabajos.py          corre un trabajo en segundo plano, uno a la vez
pruebas/               349 pruebas; ninguna toca la red
datos/grn.db           la base (fuera del repositorio)
datos/fulltext/        XML, texto derivado y PDF (fuera del repositorio)
salidas/               exportaciones CSV y JSONL (fuera del repositorio)
```

## Más documentación

| archivo | de qué trata |
|---|---|
| `docs/informe-seminario-1.md` | **el panorama del proyecto y su estado; empieza aquí** |
| `CLAUDE.md` | contexto completo del proyecto y reglas que no se rompen |
| `PLAN.md` | los cuatro pasos, sus capas y el contrato de cada uno |
| `docs/hallazgos.md` | los hechos medidos, con su medición y la fecha |
| `docs/decisiones.md` | las decisiones de diseño y por qué se tomaron así |
| `docs/traspaso-maquina-nueva.md` | **cómo levantar el proyecto en otra computadora**: qué copiar, qué instalar y cómo comprobarlo |
| `docs/traspaso-etapa-2.md` | qué formato tienen los datos que esta etapa entrega |
| `docs/ficha-modelo-bert.md` | el modelo de clasificación heredado, auditado |
| `etapa2/README.md` | la etapa 2: partición sin contaminación y patrón de oro |
| `.kiro/steering/dominio-grn.md` | nomenclatura de genes y qué se busca extraer |
| `.kiro/steering/migracion-servicio.md` | qué falta para operarlo como servicio compartido |
