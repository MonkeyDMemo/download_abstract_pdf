# Decisiones de diseño

Por qué el sistema está hecho así y no de la forma obvia. Varias de estas
salieron de un error concreto en producción; queda anotado cuál, porque el
síntoma es lo que hace entender la decisión.

## Un documento no cuelga de la consulta que lo trajo

`documentos` guarda el artículo, único por PMID. `consulta_documento` guarda
qué consulta lo trajo. Son dos tablas y no una porque el solapamiento entre
consultas de *P. aeruginosa* es enorme: la misma revisión de quorum sensing cae
en la consulta de regulación, en la de biopelículas y en la de resistencia.

Con el documento colgando de la consulta, cada consulta nueva volvería a
descargar todo lo que ya se tenía, y la pregunta "¿ya tenemos este PMID?" no se
podría contestar sin recorrer consulta por consulta. Con las dos tablas, el
artículo se almacena una vez y se liga las veces que haga falta, y `ingestar()`
puede restar la lista de PMIDs que devolvió `esearch` contra lo que ya está en
la base y pedir por `efetch` solo la diferencia.

La misma razón vale para `descargas`, que cuelga del PMID y no de la consulta:
el texto completo de un artículo se baja una vez, sirva a la consulta que
sirva.

Romper esto no es una regresión menor. Es el sistema entero.

## Solo se vinculan los PMIDs que de verdad existen

`ingestar()` vincula a la consulta **todos** los PMIDs que devolvió `esearch`,
no solo los recién descargados, porque un artículo que ya estaba en la base por
otra consulta igual pertenece a esta.

El problema es que `esearch` devuelve PMIDs que `efetch` después no entrega:
registros retirados y entradas de tipo Book, entre otros. Vincularlos violaba
la llave foránea de `consulta_documento` hacia `documentos` y **abortaba la
corrida completa por un solo artículo**, después de haber descargado cientos.

`db.vincular()` filtra con un `INSERT ... SELECT` contra `documentos`: si el
PMID no está, el SELECT no devuelve filas y no se inserta nada. El filtro va en
la misma pasada, sin una consulta extra. Los faltantes se ignoran en silencio
en la capa de SQL, pero `etl.ingestar()` ya sabe cuáles son y los reporta en la
bitácora, que es donde alguien puede verlos.

## El PMID del ID Converter llega como número, no como cadena

El ID Converter de PMC devuelve `"pmid": 37569271` en su JSON: un número, no
una cadena. En todo el resto del sistema los PMIDs son texto, empezando por la
columna `documentos.pmid`.

Sin convertirlo con `str()` al armar el mapa, las llaves quedaban enteras y
ningún `mapa.get(pmid)` acertaba nunca. El efecto no era un error visible sino
algo peor: artículos que sí están en PMC en acceso abierto quedaban sin PMCID
resuelto, se registraban como `no_disponible` y, como `pendientes_descarga()`
no reintenta los `no_disponible` a propósito, quedaban descartados **para
siempre** aunque se volviera a correr el comando.

Un bug que ensucia la base de forma permanente vale más que un `str()`; por eso
la conversión lleva comentario en `pubmed.convertir_ids()`.

## El filtro por estatus va en el WHERE, no en el LEFT JOIN

`pendientes_descarga()` busca los documentos sin descarga exitosa de un tipo.
La versión original filtraba dentro del `LEFT JOIN`:

```sql
LEFT JOIN descargas dz ON dz.pmid = d.pmid
      AND dz.tipo = ? AND dz.estatus = 'ok'
WHERE dz.pmid IS NULL
```

Se lee bien y está mal. Las filas con estatus `error` no cumplen la condición
del join, así que el join no las trae, así que `dz.pmid IS NULL` es verdadero y
salen como pendientes **en cada corrida**, se pidan o no. Peor todavía: con esa
forma la condición de `--reintentar` (`dz.estatus = 'error'`) nunca se puede
cumplir, porque la fila de error jamás llega al `WHERE`. La bandera existía y
no hacía nada.

Ahora el join trae la fila de `descargas` sea cual sea su estatus y el `WHERE`
decide: `dz.pmid IS NULL` por omisión, `dz.pmid IS NULL OR dz.estatus = 'error'`
con `--reintentar`. Los `no_disponible` quedan fuera en ambos casos, que es lo
que se quería desde el principio: no tienen acceso abierto y reintentarlos solo
gasta peticiones contra el límite de NCBI.

## Un trabajo a la vez, y por eso el servidor se ata a 127.0.0.1

`trabajos.Gestor` corre un solo trabajo en segundo plano y le niega la entrada
al segundo con un 409. No es una limitación por implementar de más:

- El control de tasa vive en la instancia de `pubmed.Cliente` (atributo
  `_ultima`). Con dos trabajos en paralelo cada uno cree que respeta el límite
  mientras el conjunto lo rebasa. NCBI bloquea por IP, no por usuario: quien
  paga el bloqueo es todo el laboratorio, incluidos los que no estaban usando
  el sistema.
- SQLite serializa las escrituras. Dos ingestas simultáneas dan
  `database is locked` y una de las dos muere a media corrida.

Ese candado es **por proceso**, y de ahí salen las otras dos decisiones del
servidor.

La primera: escucha solo en `127.0.0.1`. No hay autenticación de ninguna clase
y el tablero puede borrar documentos y lanzar descargas; atarlo a `0.0.0.0`
sería regalarle a cualquiera de la red la capacidad de dejar sin servicio a los
demás. Acceso remoto, si algún día hace falta, va detrás de un túnel SSH o de
un proxy que autentique, nunca cambiando el bind.

La segunda: `allow_reuse_address` queda desactivado en Windows. En Linux
`SO_REUSEADDR` sirve para no esperar el `TIME_WAIT` al reiniciar y no permite
apoderarse de un socket que ya escucha, así que ahí se deja puesto. En Windows
la semántica es otra: un segundo proceso **sí** puede quedarse con un puerto
que ya está escuchando, y `bind()` lo acepta sin quejarse. Serían dos
servidores vivos, cada uno con su propio gestor creyendo que es el único: dos
trabajos a la vez, el límite de NCBI al doble y dos escritores sobre SQLite.
Como el candado es por proceso, la única forma de sostenerlo es impedir que
exista el segundo proceso, y eso es exactamente lo que hace fallar el `bind()`.

## No se raspa el sitio web de PMC

De los 2263 documentos, 607 están en PMC pero fuera del subset de acceso
abierto: su página se lee perfectamente en el navegador y la API solo entrega
los metadatos. La tentación de bajar el HTML es evidente y la respuesta es no.

NCBI dirige el acceso programático a las E-utilities precisamente para no
recibir ese tráfico en el sitio web, y hace cumplir la regla bloqueando por IP.
Una IP del laboratorio bloqueada deja sin PubMed a todos los que salen por ella
(incluidos quienes no tenían nada que ver) y no es algo que se destrabe
mandando un correo el mismo día. El riesgo no es proporcional al beneficio de
607 artículos.

Lo que sí está en el subset abierto se baja por la vía habilitada. Lo demás se
exporta con `export --pendientes`, con la liga a PMC o a PubMed incluida, para
pedirlo por la biblioteca institucional. Es más lento y es el camino correcto.

## WAL en SQLite

`db.conectar()` pone `PRAGMA journal_mode = WAL`. Con el journal clásico un
lector bloquea al escritor, así que el tablero sondeando el estado cada segundo
y medio le sacaba `database is locked` al ETL a media corrida. En WAL conviven:
el lector ve la última versión consolidada y no espera a nadie.

Hay dos casos donde el pragma no se puede aplicar: las bases `:memory:` de las
pruebas y los sistemas de archivos de red, que no soportan la memoria
compartida que usa el WAL. En ninguno de los dos vale tumbar la conexión (sin
WAL la base sigue siendo correcta, nada más menos concurrente), así que el
error se ignora a propósito.

Lo que WAL no arregla es dos escritores simultáneos, por ejemplo borrar desde
el tablero mientras corre una ingesta. Para eso está `PRAGMA busy_timeout =
5000`, que cubre el choque de milisegundos que es el caso realista. El arreglo
de fondo sigue siendo Postgres, y toca solo `db.py`.

## El tope de 10,000 de esearch: fallar en vez de truncar

`buscar_pmids()` pedía páginas sucesivas subiendo `retstart`. Para PubMed y
PMC eso no funciona: NBK25499 dice que sólo se pueden recuperar los primeros
10,000 registros de un mismo conjunto, y acota la receta de `retstart` a
"databases other than PubMed or PMC".

Con la consulta actual (2263 resultados) no se notaba. Con una consulta más
amplia había dos desenlaces, y el malo no era el que parece. Si NCBI devuelve
un nodo `<ERROR>`, la corrida muere y alguien se entera. Si en cambio trunca
en silencio, se guardan 10,000 de 25,000, se vinculan esos y la ejecución
cierra con estatus `ok`: la bitácora afirma que el corpus está completo cuando
le faltan dos tercios. Eso ataca directamente la razón de ser del proyecto,
que es saber en todo momento qué se tiene.

Ahora se pide una sola vez con `retmax` en 10,000 y, si el total lo rebasa sin
que haya `--limite`, se lanza `ErrorPubMed` explicando cómo partir la consulta
por fechas. Se eligió fallar en vez de segmentar automáticamente porque la
segmentación necesita partir recursivamente cualquier tramo que siga pasándose
del tope, y eso pide sus propias pruebas. Un error claro hoy vale más que una
segmentación a medio probar.

## "No hay" contra "no pude preguntar"

`convertir_ids()` hacía `continue` cuando el ID Converter no respondía, y
`liga_pdf_pmc()` devolvía `None` tanto si el servicio decía que no hay PDF
como si no contestaba.

Las dos situaciones terminan en lugares opuestos de la base. "No hay" se
registra como `no_disponible`, que por diseño no se reintenta nunca. "No pude
preguntar" tiene que quedar como `error`, que sí vuelve con `--reintentar`.
Confundirlas convierte una caída de unos minutos en una mentira permanente:
hasta 180 artículos de acceso abierto por lote marcados como inaccesibles,
recuperables sólo borrando filas a mano.

Ahora ambas funciones lanzan `ErrorPubMed` cuando no hay respuesta. Importa
más de lo que parecía cuando se decidió: NCBI anunció el retiro del OA Web
Service, así que el caso "el servicio no contesta" va a dejar de ser hipotético.
