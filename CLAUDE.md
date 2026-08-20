# CLAUDE.md

Contexto del proyecto. Se carga en cada sesion de Claude Code.

## Objetivo

ETL de literatura biomedica desde PubMed. Recibe consultas booleanas,
descarga abstracts por lotes y mantiene el estado en SQLite. En un segundo
lote opcional descarga texto completo (XML de PMC, PDF de acceso abierto).

Es la primera etapa de un pipeline cuyo fin es inferir relaciones regulatorias
entre factores de transcripcion y genes en *Pseudomonas aeruginosa*, para
construir una red de regulacion genica.

**El valor central es no volver a descargar lo que ya se tiene, y saber en
todo momento que se tiene.** Sin eso, cada estudiante del laboratorio corre su
propio script y baja los mismos articulos otra vez.

Lo usan varios miembros del laboratorio, no un solo desarrollador. Se opera
por CLI y por un tablero HTTP local (`servidor.py`), que son dos frentes
sobre las mismas capas.

**El proyecto no termina en el ETL.** `etapa2/` prepara los datos del
clasificador de relaciones y lanza su barrido: no entrena aqui, y el modelo
—BioBERT afinado en cuatro clases— es del servidor del asesor, no de este
repositorio. Vale la pena saber tres cosas antes de tocar nada de ahi: se
entreno con *E. coli* y se aplica a *P. aeruginosa*; su metrica reportada
estaba contaminada porque el 73.9% del conjunto de prueba ya se habia visto en
entrenamiento; y `etapa2/particionar.py` se niega a escribir una particion en
la que detecte esa contaminacion. El panorama esta en
`docs/informe-seminario-1.md` y el detalle en `etapa2/README.md` y
`docs/ficha-modelo-bert.md`.

## Restricciones duras

**Solo libreria estandar de Python 3.8+.** No agregar dependencias. El codigo
corre en maquinas de laboratorio (Linux y Windows) sin permisos de
administrador y a veces sin salida a PyPI. Si una tarea parece necesitar
`requests`, `pandas` o `lxml`, resolverla con `urllib.request`, `sqlite3` y
`xml.etree.ElementTree`, y explicar la alternativa en un comentario.

**Acentos: segun quien lo lea.** La regla depende de si el texto es para un
humano o es un identificador.

- **Texto que lee un humano lleva acentos correctos.** Etiquetas y mensajes
  del tablero, salida de terminal del CLI, encabezados de CSV, titulos,
  documentacion. Se escribe "Año", "Título", "búsqueda", "año mínimo": la
  palabra correcta del espanol en cada caso, no una lista cerrada de
  excepciones.
- **Los identificadores van siempre en ASCII sin acentos.** Nombres de
  variables, funciones, clases, columnas de SQL, claves del JSON de la API,
  atributos `data-*` y valores de `id=` del HTML. `anio` sigue siendo `anio`
  como columna, como clave de JSON y como id de elemento. Cambiarlo rompe la
  base de 2263 documentos y el contrato de la API.

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

1. **Solo `db.py` escribe SQL.** Si otra capa necesita una consulta nueva, se
   agrega una funcion en `db.py`. Nunca un `con.execute()` en `etl.py`,
   `servidor.py`, `cli.py` ni `trabajos.py`. Ya no queda ninguna excepcion.
2. **`pubmed.py` no conoce la base.** Recibe parametros, devuelve
   diccionarios. No importa `db`. Eso la hace probable sin red.
3. **`etl.py` no imprime.** Recibe un callable `log`. Default: funcion vacia.
   El CLI le pasa `print`; el gestor de trabajos le pasa su acumulador de
   lineas, que es lo que el tablero sondea.
4. **`cli.py` no tiene logica de negocio.** Parsea, llama a `etl`, formatea.
5. **`servidor.py` tampoco.** Valida lo que llega, llama a `db`, `etl` o
   `trabajos`, y formatea JSON. La pieza que importa es `manejar(metodo, ruta,
   params, cuerpo, ctx) -> (codigo, objeto)`: una funcion normal que no abre
   sockets ni lee del disco, y por eso las pruebas cubren el API completo sin
   levantar un puerto.
6. **`trabajos.py` no importa `etl`.** Recibe el callable a correr, asi que
   sirve igual para `ingestar()` que para `descargar_fulltext()` y las pruebas
   de concurrencia no arrastran el ETL.

Esta separacion es lo que permitio montar el tablero sin tocar la logica, y lo
que permitiria montar FastAPI manana. Si una propuesta obliga a cruzar estas
fronteras, casi siempre hay una alternativa que no lo hace.

## Modelo de datos

| tabla | rol |
|---|---|
| `consultas` | la query booleana con nombre |
| `ejecuciones` | bitacora de cada corrida |
| `documentos` | un articulo, unico por PMID |
| `consulta_documento` | que consulta trajo que documento (N a N) |
| `descargas` | estado de full text por PMID y tipo (`xml` / `pdf`) |

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
python3 -m unittest discover        # desde la raiz del proyecto
```

349 pruebas con `unittest` de la estandar, en `pruebas/`. No tocan la red: se inyecta
`pruebas.falsos.ClienteFalso`, que devuelve XML o JSON fijo y registra cada
llamada. Ademas `PruebaSinRed` deja `urlopen` inutilizable, asi que una
prueba que arme un `Cliente` de verdad falla en vez de salir a NCBI.

La prueba que no puede faltar: correr la misma ingesta dos veces y verificar
que la segunda no llama a `efetch`
(`pruebas/test_idempotencia.py::PruebasSegundaCorrida`).

## APIs externas

| Servicio | Uso | Limite |
|---|---|---|
| NCBI E-utilities | `esearch`, `efetch` de PubMed y PMC | 3 req/s sin key, 10 con |
| PMC ID Converter | PMID a PMCID/DOI | 200 IDs por peticion |
| PMC OA Service | localizar PDF del subset abierto | sin limite documentado |
| Europe PMC | localizar PDF de articulos de PMC fuera del subset abierto | sin limite documentado |
| Unpaywall | localizar PDF abierto por DOI | 100k/dia, exige correo |

Las queries booleanas van por **POST**, nunca GET: rebasan los 700 caracteres.

Errores: HTTP 400 de NCBI es query mal formada, fallar de inmediato sin
reintentar. HTTP 404 de Unpaywall es DOI no registrado, devolver `None`. Los
fallos de un articulo no abortan el lote; se registran en `descargas` con
estatus `error`.

Solo se descarga lo que PMC, Europe PMC y Unpaywall exponen legalmente, y en
el caso de Europe PMC se respeta su campo `availabilityCode`: no se adivina.
No implementar nada que evada muros de pago ni controles de acceso, y eso
incluye un navegador headless para pasar los desafios de las editoriales: es
dependencia y es evasion. La via formal para contenido con suscripcion es el
acceso institucional de la UNAM y, para Elsevier, su API de TDM con clave
institucional. Lo que no es abierto se exporta como lista de pendientes con su
liga, para pedirlo por biblioteca.

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
   parte: lo que se obtiene son PDFs para lectura humana. Re-parsearlos no es
   opcion (pediria una dependencia, y el propio JATS existe justamente porque
   un PDF re-parseado pierde subindices de genes y entrelaza columnas). O sea
   que el corpus del clasificador solo crece con `fulltext --tipo xml`.

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