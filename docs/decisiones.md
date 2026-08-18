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

## Las fuentes de PDF que se midieron y no se construyeron

Esta es la entrada más útil de este archivo: sin ella, dentro de seis meses
alguien vuelve a proponer Crossref y hay que volver a medir.

Se propuso una cascada de cinco niveles (PMC OA, Unpaywall, Crossref, OpenAlex,
Europe PMC, después el HTML de la landing page, después un navegador headless).
Antes de escribir nada se midió cada fuente contra muestras del corpus real, y
la medición que importa **no es cuántas URLs encuentra sino cuántos PDFs baja**:

| fuente | encuentra URL | **baja un PDF** |
|---|---|---|
| Europe PMC, grupo "en PMC pero solo metadatos" | 18/18 | **15/20** |
| Europe PMC, grupo "fuera de PMC" | 0/18 | 0/18 |
| Crossref | 7/15 | **0** |
| OpenAlex | 4/15 | **0** |
| `citation_pdf_url` de la landing page | 0/12 | **0** |
| Europe PMC `fullTextXML` | — | 404 en 18/18 |

Crossref y OpenAlex sí encuentran ligas, pero apuntan al sitio del editor:
`journals.asm.org` 403, `academic.oup.com` 403, `onlinelibrary.wiley.com` 403,
`link.springer.com` devuelve HTML. Los PDFs que sí bajaron vinieron **todos** de
`europepmc.org`, y la razón es sencilla: Europe PMC hospeda el archivo él mismo
en lugar de mandarte a la página del editor.

El nivel de la landing page rinde cero por partida doble: siete de doce
editoriales ni siquiera dejan cargar la página, y ninguna de las cinco que sí
carga publica `citation_pdf_url`.

El navegador headless se descartó por dos razones independientes, cualquiera de
las cuales basta: es una dependencia, y el proyecto no tiene ninguna; y usarlo
para pasar los controles de las editoriales es evadir un control de acceso, que
es justo lo que este proyecto no hace. La vía formal para contenido con
suscripción es el acceso institucional de la UNAM y, para Elsevier, su API de
TDM con clave institucional.

Y un dato que conviene tener presente al decidir cuánto esfuerzo merece esta
etapa: de los artículos que están en PMC fuera del subset abierto **no existe
texto legible por máquina en ninguna parte**. Lo que se obtiene son PDFs para
lectura humana; el corpus que alimenta al clasificador no crece con esto.

## La cascada baja en cada nivel, no resuelve una vez

`_bajar_pdf` tomaba la primera liga que apareciera y, si esa liga fallaba, el
artículo moría ahí. Con más de una fuente eso pierde PDFs que sí existen: para
un artículo de PMC fuera del subset abierto, Unpaywall suele devolver la liga
del editor, que contesta 403; si esa URL ganaba la carrera, Europe PMC no se
consultaba nunca.

Ahora `_fuentes_pdf` es un generador y el bucle intenta bajar en cada nivel. Es
generador a propósito: cuando PMC OA entrega el PDF, Europe PMC y Unpaywall no
se consultan, y eso son cientos de peticiones por corrida.

El beneficio secundario resultó ser el mayor: el OA Service de PMC tiene retiro
anunciado. Con la cadena vieja, el día que empiece a fallar la etapa entera
rinde cero. Con la cascada, Europe PMC toma el relevo solo.

En la primera corrida real de 60 artículos, la bitácora muestra el mecanismo
funcionando: `PMC OA no dio PDF, sigo` seguido de `PDF 1753 KB (Europe PMC)`.
Cuarenta y tres de esos sesenta se bajaron, todos por Europe PMC, y con el
código anterior los cuarenta y tres se habrían perdido.

## `None` contra excepción, ahora también en `Cliente.get`

`Cliente.get` devolvía `None` por dos motivos incompatibles: "el servidor
contestó 404" y "no pude preguntar tras cuatro intentos". Mientras nadie
tradujera `None` a un estatus permanente, la ambigüedad era tolerable.

Dejó de serlo al decidir que un 403 del editor se registra como
`no_disponible`, que por diseño no se reintenta nunca. Con el contrato viejo,
un corte de red de dos minutos habría marcado un lote entero como "sin acceso
abierto", de forma permanente y sin manera de recuperarlo con `--reintentar`.

El contrato quedó igual en las cuatro capas, y cabe en una línea:

> `None` = el servidor contestó y la respuesta es no. Excepción = no pude preguntar.

De paso cerró un defecto que ya estaba vivo: Unpaywall responde **422 a un
correo inválido** (verificado contra su API). Como 422 estaba en los códigos
definitivos genéricos, correr la etapa con un typo en `--email` marcaba como
permanentemente inaccesible todo lo que está fuera de PMC. Ahora
`liga_pdf_unpaywall` solo tolera el 404, que es el único "no" legítimo que ese
servicio emite.

## El 403 del editor es `no_disponible`, no `error`

MDPI, ScienceDirect, OUP, Wiley y ACS contestan 403 a un cliente que no es un
navegador. No es un muro de pago en todos los casos —el artículo de MDPI que se
probó es CC BY— pero sí es una decisión del editor sobre quién puede descargar.

Se registran como `no_disponible` y no como `error` por dos razones. La
primera: `error` significa "el sistema falló, vuelve a intentar", y aquí no
falló nada, el servidor contestó. La segunda es de costo: con `error`, cada
corrida con `--reintentar` vuelve a gastar peticiones contra servidores que ya
dijeron que no.

Además, los códigos 401, 403 y 451 pasaron a la lista de definitivos de
`Cliente.get`. Antes cada artículo bloqueado costaba cuatro peticiones y hasta
catorce segundos de retroceso exponencial; ahora cuesta una petición y cero
espera.

Lo que **no** se hizo, y no se debe hacer, es disfrazar el cliente de navegador
para pasar el bloqueo. Esos artículos salen en `export --pendientes` con su
liga, que abierta en un navegador funciona sin problema, porque el bloqueo es
contra el programa y no contra la persona.

## La etapa de PDF atiende primero lo que no tiene texto de ninguna forma

`pendientes_descarga` ordenaba por año descendente, y lo reciente es justo lo
que mejor cubre el subset abierto de PMC. El efecto era que una corrida de PDF
gastaba sus primeras horas bajando artículos que ya estaban en XML, que para el
clasificador es el formato mejor. Se comprobó en la primera corrida real: los
43 PDFs que bajó fueron los 43 a artículos que ya tenían XML, y ninguno al
grupo que esta etapa existe para atender.

Ahora el orden pone primero los que no tienen texto de ningún tipo. No se
excluye nada: el resto sigue en la cola, detrás.

Conviene no confundir dos listas que se parecen. "Sin full text" para la
biblioteca incluye a quien no tiene ni XML ni PDF. "Sin insumo para el
clasificador" es `descargas WHERE tipo = 'xml' AND estatus = 'ok'`, y un
artículo con PDF sigue faltando ahí.

## El tablero es oscuro por decisión, no por preferencia del sistema

El tablero nació con tema claro y un bloque de `prefers-color-scheme: dark`
que lo repintaba si el sistema operativo lo pedía. Al adoptar el sistema
visual del laboratorio —Nocturne, en `web/UI mockups request/`— se quitó ese
bloque.

Mantener los dos era mantener dos tableros: cada color nuevo hay que elegirlo
dos veces y verificarlo dos veces, y el que casi nadie mira se degrada sin que
nadie se entere. El diseño acordado es oscuro; el tablero es oscuro.

El cambio fue de tokens, no de estructura. El CSS ya estaba escrito contra
variables —noventa usos de `var(--…)` contra veintitrés colores incrustados—,
así que bastó sustituir el bloque `:root` y ajustar cinco reglas que asumían
fondo claro. Ninguna de las setenta y dos clases cambió de nombre y ningún
`id` se tocó, así que el JavaScript no se enteró.

Dos cosas de la hoja de referencia **no** se copiaron, y las dos por la misma
razón: la tipografía Inter y los iconos Phosphor vienen de un CDN. El token de
la fuente ya declara el respaldo del sistema, y eso es lo que se usa.

Del sistema sí se tomó una regla que cambia cómo se ve el tablero más que la
paleta: **los botones van delineados, nunca rellenos**. El acento se usa como
línea, no como superficie.

## El escudo institucional va sobre una placa clara

Sobre el fondo oscuro el escudo casi no se veía. En vez de ajustarlo a ojo se
decodificó el PNG y se contaron sus píxeles: **el 87% de los opacos son muy
oscuros** —el 60% es casi negro (`#1d1d1b`) y el 21% azul institucional
(`#253371`)—, lo que sobre `#161826` da 2.6:1.

Las salidas eran tres. Invertirlo o recolorearlo se descartó de entrada: es un
escudo institucional y sus colores no son nuestros para cambiarlos. Aclarar el
fondo de toda la página contradecía el diseño acordado. Queda la tercera, que
además es el tratamiento habitual: una placa clara detrás del escudo, que sube
el contraste a 5.9:1 y deja los colores intactos.

La placa usa `neutral-100` y no blanco puro porque el sistema no admite blanco
puro; la diferencia no se nota y la regla se respeta.

## La red animada se dibuja en Canvas 2D, no con una biblioteca de 3D

Se pidió `three.js` para los nodos del panel de entrada. Se resolvió con
Canvas 2D de a pie, y conviene dejar escrito por qué para no volver a
discutirlo.

La restricción que gobierna el proyecto entero es cero dependencias, y su
razón es de despliegue: las máquinas del laboratorio a veces no tienen salida
a internet. Una biblioteca por CDN no degrada con elegancia en ese caso —deja
el panel de entrada vacío justo en la máquina donde más cuesta diagnosticarlo—
y vendorearla serían cientos de kilobytes dentro de un archivo que hoy pesa
setenta y ocho, para un elemento decorativo.

Canvas 2D da el mismo efecto en una pantalla de código: nodos que flotan,
aristas que aparecen cuando dos se acercan y se desvanecen con la distancia, y
unos pocos nodos mayores que hacen de concentradores, como los factores sigma
en una red de regulación real. La figura no es un adorno cualquiera: es el
objeto del que trata el corpus.

Dos cuidados que no se ven pero importan en una laptop. La animación se
detiene cuando el Panel no está a la vista o la pestaña del navegador está
oculta, porque repintar sesenta veces por segundo detrás de algo que nadie
mira solo gasta batería. Y con `prefers-reduced-motion` se pinta un cuadro
fijo en lugar de animar: la red se sigue viendo, quieta.

Si algún día hace falta 3D de verdad, la vía es vendorear el archivo y
servirlo desde la lista blanca de `servidor.py`, la misma del escudo. Pero
entonces el tablero deja de ser un archivo autocontenido, y eso se decide a
sabiendas, no de pasada.

## La lista blanca de archivos servidos, y por qué es por igualdad exacta

`servidor.py` sirve dos archivos y nada más: la página y el escudo. No sirve
un directorio, y la diferencia no es de estilo. En la raíz del proyecto viven
`.key` con la llave de NCBI, la base con el corpus entero y todo el código;
apuntar un manejador de archivos estático a esa carpeta los expone a quien
abra el navegador.

Cada ruta se compara **por igualdad exacta** contra su propia ruta fija, que
sale de `__file__` y no se compone con nada de la petición. Por eso no existe
un `..` que sirva de nada, y por eso `/logo.PNG` también da 404: la lista es
de dos cadenas, no de un patrón. Hay pruebas que lo fijan, incluidas las
variantes codificadas.
