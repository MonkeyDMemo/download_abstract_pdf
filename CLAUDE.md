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

**Nunca escribir credenciales en el codigo.** API key en `NCBI_API_KEY`,
correo en `NCBI_EMAIL` o flag `--email`.

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
   `servidor.py` ni `trabajos.py`. (Queda una violacion viva en `cli.py`,
   anotada en la deuda.)
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

`run` siempre antes que `fulltext`. Dentro de `fulltext`, `xml` antes que
`pdf`: el JATS de PMC llega con secciones separadas y pies de figura
identificados; un PDF re-parseado pierde subindices de genes y entrelaza
columnas. El XML alimenta al clasificador; el PDF es para lectura humana.

## Pruebas

```bash
python3 -m unittest discover        # desde la raiz del proyecto
```

263 pruebas con `unittest` de la estandar, en `pruebas/`. No tocan la red: se inyecta
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
| Unpaywall | localizar PDF abierto por DOI | 100k/dia, exige correo |

Las queries booleanas van por **POST**, nunca GET: rebasan los 700 caracteres.

Errores: HTTP 400 de NCBI es query mal formada, fallar de inmediato sin
reintentar. HTTP 404 de Unpaywall es DOI no registrado, devolver `None`. Los
fallos de un articulo no abortan el lote; se registran en `descargas` con
estatus `error`.

Solo se descarga lo que PMC y Unpaywall exponen legalmente. No implementar
nada que evada muros de pago. Lo que no es abierto se exporta como lista de
pendientes.

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
3. **El 403 de los editores se reintenta cuatro veces por articulo.**
   `Cliente.get()` solo trata 404 y 422 como definitivos; todo lo demas entra
   al retroceso exponencial. Un editor que responde 403 a los robots lo va a
   responder igual las cuatro veces, asi que cada articulo cerrado cuesta
   cuatro peticiones y hasta 14 segundos de espera. En la etapa de PDF, que es
   donde se sale a los sitios de las editoriales, eso es la mayor parte del
   tiempo de corrida. Arreglo: sumar 401, 403 y 451 a los codigos definitivos.
4. **`cli.py::cmd_export` tiene un `con.execute()` crudo.** Es el unico SQL
   que quedo fuera de `db.py`: la consulta de `--pendientes`, que hace su
   propio `LEFT JOIN` contra `descargas`. Debe pasar a una funcion de `db.py`
   (el tablero va a necesitar la misma lista) y, mientras siga ahi, la
   migracion a Postgres no toca solo `db.py` como dice el punto 2.

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