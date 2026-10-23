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

**Actualización del 13-oct-2026: ahora sí se segmenta, con sus pruebas.** Lo
que destrabó la decisión fue una consulta de 83 638 resultados que se corrió a
mano por año desde el tablero con «límite 1 000»: con límite el programa
recorta sin avisar, y diez corridas quedaron en la bitácora como `ok` con
≤1 000 de ~5 000 artículos cada una. Fallar protegía contra el truncado
silencioso del programa, no contra el del usuario. La segmentación
(`pubmed.tramos_por_fecha`) tomó cuatro decisiones:

- **Una petición de `esearch` por nodo, sin contar aparte.** Si el conteo del
  tramo cabe, el tramo es hoja y la misma respuesta ya trae sus ids; si no, se
  parte. Un `rettype=count` previo ahorraría ~100 KB de ids por nodo interno y
  a cambio abriría una carrera entre contar y pedir.
- **El punto medio se alinea al 31 de diciembre** cuando el rango cruza años,
  y solo baja a mitades de días dentro de un año que por sí solo rebase el
  tope. Los tramos salen legibles (`1990/01/01 - 2003/12/31`).
- **Mitades `[ini, medio]` y `[medio + 1 día, fin]`**, para que la suma de
  tramos sea comparable con el total. Desde 2014 `[dp]` empata la fecha
  impresa y la electrónica, así que un artículo puede caer en dos tramos: la
  unión lo cuenta una vez y una suma mayor que el total es aviso suave; una
  unión menor que el total es aviso fuerte, y la corrida sigue.
- **Un día que rebase el tope es error**, con el día y el conteo en el
  mensaje: ahí ya no hay forma de partir sin truncar.

Y la bitácora ganó `ejecuciones.parametros`, porque la causa de fondo no era
el tope sino que nada registraba que se había pedido con límite.

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

Por eso mismo la red va arriba de todo y **las métricas van encima de ella**:
los nodos son genes y aristas de regulación, o sea justo lo que cuentan las
cifras que se leen sobre ellos. Puestos juntos, la animación es contexto; en
una tarjeta aparte sería decoración. El lienzo va al 50% de opacidad con un
degradado, y las cifras llevan fondo propio: si los nodos se cuelan entre los
dígitos, el número deja de leerse de un golpe y la animación pasó de contexto
a estorbo.

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

## La ruta de un archivo se arma con identificadores, nunca con la base

El tablero sirve el texto y el PDF de un documento. Componer esa ruta es el
punto donde un tablero local se convierte en un lector de archivos arbitrarios,
y en la raíz del proyecto viven `.key` con la llave de NCBI, la base y el
código.

La salida obvia era leer `descargas.ruta`, que es donde el ETL apuntó lo que
escribió. Se descartó por dos razones. La primera es práctica: esa columna
guarda una ruta **relativa** al directorio desde donde corrió el ETL —y con
diagonales de Windows, `datos\fulltext\pdf\41212033.pdf`—, que no tiene por qué
ser el directorio del servidor. La segunda es de fondo: meter una cadena
guardada en una ruta de disco convierte cualquier escritura en la base en una
lectura de archivo, y la base se puede editar desde el propio tablero.

En vez de eso la ruta se arma con el PMID y el PMCID, validados contra
`^\d{1,12}$` y `^PMC\d{1,12}$`, más la convención de nombres de
`CLAUDE.md`. No es una suposición: se verificó contra los 2263 documentos
que **todos** los PMID son dígitos y **todos** los PMCID casan su patrón, y que
el 100% de los archivos se localizan así —300 de 300 de texto, 43 de 43 de PDF.

Encima va una comprobación de contención: la ruta resuelta tiene que quedar
dentro de la raíz de salida resuelta. Es redundante con la validación anterior
y se queda de todas formas, porque cuesta tres líneas y cubre el descuido de
mañana. Ojo con una trampa: `Path.is_relative_to` existe desde Python 3.9 y el
proyecto apunta a 3.8, así que la comparación se hace sobre `parents`.

Las rutas viven bajo `/api/` a propósito. La lista blanca de la raíz sigue
siendo de dos archivos comparados por igualdad exacta; esto no la toca.

## El lector no cabía en el modal

El detalle de un documento vive en un modal de `min(760px, 100%)` con
`max-height: 68vh`. El texto extraído de un artículo tiene una mediana de 56
mil caracteres y un máximo de 108 mil. Leer eso ahí es un castigo, así que el
lector es una vista propia.

No tiene pestaña. Se llega desde el botón «Leer» de la tabla y se sale con
«Volver», que regresa a donde estabas: no es un lugar al que se entre, sino al
que se va por un documento.

El texto se manda como JSON y no como archivo, para que el tablero lo pinte
con su helper y sin `innerHTML`: los artículos traen `<` y `>` de fórmulas y de
nombres de genes, y ahí es exactamente donde se cuela una inyección.

El índice de secciones sale gratis: `jats_a_texto` ya deja el texto con
jerarquía tipo markdown (`#` título, `##` sección, hasta `#####`). La sección
`PIES DE FIGURA Y TABLA` se marca aparte porque ahí se concentran las
relaciones factor-gen, que es lo que alguien viene a revisar.

El PDF va en un `<iframe>` con el visor nativo del navegador. Sin PDF.js ni
ninguna otra biblioteca, por la misma razón de siempre.

## La portada dice cuánto sirve, no cuántos hay

«Cuántos documentos tenemos» y «cuánto del corpus sirve para el clasificador»
son preguntas distintas, y se confundieron una y otra vez mientras se armaba
esto. Un artículo con abstract está en la base pero no alimenta la extracción
de relaciones: para eso hace falta el texto completo.

Por eso la cifra grande de la portada no es el total de documentos sino el
porcentaje que tiene texto completo —hoy 40.6%, 918 de 2263—, y la dona reparte
por cobertura de texto y no por estado de descargas.

La dona es SVG y no canvas: escala sin verse borrosa, se puede etiquetar para
lectores de pantalla y no hay que repintarla. Se dibuja con un círculo por
tramo y `stroke-dasharray`, sin rutas ni trigonometría. Un detalle de
implementación que cuesta encontrar: los elementos de SVG no se crean con
`createElement` sino con `createElementNS`, o el navegador los trata como
etiquetas desconocidas y no pinta nada.

Al lado va siempre la leyenda con las cifras y los porcentajes. La gráfica
nunca es la única forma de leer el dato, ni para quien usa lector de pantalla
ni para quien no distingue los colores.

## La idempotencia, comprobada contra PubMed

Se registró una segunda consulta que es la primera menos ocho términos, y se
corrió:

```
PubMed reporta      : 1434
Ya estaban          : 1433
Nuevos descargados  :    1
```

Después, la base: **2264 documentos y 3697 vínculos**, con 1433 artículos
ligados a las dos consultas. La suma ingenua de las dos consultas da
justamente 3697, que es el número de vínculos; los documentos son 2264 porque
lo compartido se almacena una vez.

O sea que registrar una consulta que se solapa costó **una** llamada a
`efetch`, por el único artículo publicado desde la corrida anterior. Es la
decisión de diseño central rindiendo en un caso real, y el número que hay que
volver a ver si algún día se toca `ingestar()`.

## Las credenciales se leen solas, y se escriben pero no se leen

Lanzar un trabajo fallaba con un 400 seguido. El motivo no era el tablero:
la API key vivía en `.key` desde siempre, pero el servidor solo la buscaba en
la variable de entorno, así que en cada sesión había que hacer

    $env:NCBI_API_KEY = (Get-Content .key -Raw).Trim()

y el día que se olvidaba —o la primera vez que alguien más clonaba el
proyecto— el lanzamiento moría sin explicar dónde estaba el problema.

El arreglo de fondo va en `grn_etl/credenciales.py`, que lo usan el CLI y el
tablero por igual: **entorno primero, archivo después**. El entorno gana
porque es lo que permite correr una vez con otra cuenta sin tocar nada. Los
archivos son `.key`, que ya existía con esa forma, y `.correo` para la
dirección de contacto; los dos los cubre el `.gitignore`. El correo no es un
secreto, pero es un dato personal que NCBI recibe en cada petición y no tiene
por qué acabar en un repositorio público.

Encima va el formulario del tablero, con una regla que no se negocia: **la
llave se puede escribir pero nunca leer**. `GET /api/config` dice si hay
llave y de dónde salió —entorno o archivo—, jamás su valor. Una llave que
entra por un formulario y puede volver a salir por un GET es una llave que
cualquier página abierta en el mismo navegador podría llevarse. Hay una
prueba que serializa las respuestas de las tres rutas del panel y falla si la
llave real aparece en alguna.

Se valida antes de guardar, y no por gusto: NCBI responde **422 a un correo
inválido**, y en la etapa de PDF ese 422 marcaba artículos como
permanentemente inaccesibles. Un dedazo en el formulario habría vuelto a
sembrar el mismo desastre, así que el correo tiene que tener forma de correo
y la llave sus 36 caracteres alfanuméricos. Descubrirlo al guardar es gratis;
descubrirlo a media corrida cuesta un lote.

Dos detalles de la interfaz que salieron del mismo razonamiento. El campo de
la llave se deja vacío al recargar aunque haya una guardada, porque su valor
no viaja de vuelta; para quitarla hay que escribir algo en blanco a
propósito, de forma que recargar y guardar no la borre sin querer. Y los
botones de lanzar quedan deshabilitados mientras no haya correo, con el
motivo en el `title`: vale más no dejar apretar que dejar apretar y contestar
un 400 que hay que ir a leer.

## Un código de salida no es un diagnóstico

Las 24 corridas del primer barrido en Colab murieron con **`-11`**, cuatro
minutos las 24, unos diez segundos cada una. `barrido.py` hizo lo correcto
—anotó cada fallo y siguió— y dejó 24 archivos `.json.error` con esto dentro:

```json
{"nombre": "run_1_lr1e-5_ep6_bs16_wu0.06", "codigo": -11, "huella": "3d2cb9d4a0378177"}
```

Un `-11` no es un código de salida: es una señal, SIGSEGV, y por eso no había
traceback. El número decía que el proceso murió, no dónde.

**Encontrarlo costó dos noches, y casi todo el costo fue de diagnóstico, no de
arreglo.** El arreglo cabe en una línea. Vale la pena dejar por escrito cómo se
llegó, porque el mismo error de método se puede repetir.

### Tres hipótesis falsas, y por qué parecían buenas

La última línea que se veía antes de morir era siempre el `FutureWarning` de
`evaluation_strategy`, que sale del `__post_init__` de `TrainingArguments`. De
ahí salieron, en orden:

1. **"Muere inicializando CUDA."** Es lo siguiente que hace ese `__post_init__`.
   La descartó una sonda que construyó un `TrainingArguments` y llegó a
   `cuda:0` sin problema.
2. **"Es la frontera `arrow`→`numpy`."** Al fijar `numpy<2` nadie tocó pyarrow,
   que en la imagen de Colab viene compilado contra numpy 2; una extensión en C
   en esa situación no lanza excepción, se cae. Encajaba con todo. Era falsa:
   pyarrow 25.0.1 convivió con numpy 1.26.4 sin una queja.
3. **"Es pandas 3, que exige numpy 2."** También falsa, y también verosímil.

Las tres se sostenían sobre la misma suposición: que el último renglón impreso
está cerca de donde murió. **No lo está.** Los warnings salen por stderr, que no
se almacena; los `print()` salen por stdout, que al ir por una tubería se
almacena en bloques de 8 KB, y una señal se lleva el bloque sin escribirlo.

### Lo que sí funcionó

Dos herramientas de la biblioteca estándar, y ninguna sonda hecha a mano:

- **`python -u`**, para que la última línea impresa sea de verdad la última.
- **`PYTHONFAULTHANDLER=1`**, que ante una señal imprime el traceback de Python
  de todos los hilos. Es exactamente lo que faltaba.

Con las dos puestas, el causante salió a la primera:

```
bio_bert_re_finetune.py:166  ->  trainer.train()
transformers/trainer.py:1099 ->  create_optimizer
torch/optim/adamw.py:36      ->  AdamW.__init__
torch/optim/optimizer.py:405 ->  Optimizer.__init__
torch/_compile.py:47         ->  import torch._dynamo
torch/_dynamo/utils.py:2874  ->  has_triton_package()
triton/knobs.py:15           ->  create_module  ->  SIGSEGV
```

**Era `triton`.** Construir el optimizador entra a `Optimizer.__init__`, que
pasa por `torch._compile`, que importa `torch._dynamo`, que al cargarse
pregunta si hay triton; ese import se cae con SIGSEGV en la imagen de Colab, al
cargar su extensión en C. Es la primera línea de `trainer.train()` que toca esa
ruta, y de ahí que las 24 murieran en el mismo punto, siempre a los diez
segundos, sin que la configuración tuviera nada que ver.

El arreglo es `pip uninstall -y triton`. Nada de este barrido lo necesita: solo
lo usa `torch.compile` y aquí se entrena en modo eager, así que sin el paquete
torch pregunta, recibe `ImportError` y sigue. La comprobación del cuaderno usa
`importlib.util.find_spec`, que busca sin importar; preguntarlo con un `import`
repetiría el mismo fallo que se vino a evitar.

### Las cuatro cosas que quedaron

No es la primera vez que este proyecto paga por un fallo silencioso, así que el
episodio dejó herramienta y no solo un arreglo:

1. **Todo proceso hijo se lanza con `-u` y `PYTHONFAULTHANDLER=1`**, en
   `barrido.py` y en las celdas del cuaderno. Una corrida que muera de una
   señal ya deja dicho en qué línea estaba.
2. **`etapa2/diagnostico.py`**: anota las versiones de todo —incluidas las que
   nadie fijó, que es donde estaba el problema— y corre el script de verdad
   sobre 40 ejemplos y una época. Dos minutos, y escribe su bitácora a un
   archivo en Drive, que sobrevive a la desconexión de la sesión. El cuaderno
   trae la misma prueba de humo antes del barrido: lo que la comprobación de
   versiones no alcanza a ver sale ahí y no en media hora de corridas fallidas.
3. **Ningún `!python` del cuaderno decide solo que puede seguir.** Un `!python`
   que muere no detiene la celda: la que baja el mejor modelo dejó correr sus
   `cp` sobre una carpeta vacía y el `ls` final imprimió `total 0` como si fuera
   un resultado. Las celdas que particionan y la que baja el modelo van por
   `subprocess.run` y miran el código de salida.
4. **La marca de fallo se borra al reintentar con éxito.** El `.error` de un
   intento viejo sobrevivía al `.json` bueno en la misma carpeta de Drive, así
   que una corrida rehecha seguía saliendo en `FALLARON` y el barrido no volvía
   a anunciar ganadora **nunca**. Lo cubre `etapa2/test_barrido.py`, que
   reproduce el escenario exacto: `run_13.json` bueno más su `.error` viejo.

La cuarta es la más grave de las cuatro y la que menos se ve: las otras tres
cuestan tiempo, esa cuesta una cifra que no mide lo que su etiqueta dice.

## La cobertura del oro se reporta sin la capa manual: 43 de 55

El diccionario de PAO1 sale de tres fuentes públicas —RefSeq, KEGG, UniProt— y
de una capa manual de 22 filas que alguien escribió y firmó. Sobre los 55
factores del patrón de oro reconoce **43 solo con las fuentes públicas y 53
añadiendo la capa manual**.

**Se reporta el 43.** El diccionario existe para evaluar, y una cobertura que
sube porque una persona escribió la fila que faltaba mide a la persona, no a las
fuentes. `construir_diccionario.py` ya se niega a aceptar `oro` como procedencia,
justamente para que la evaluación no acabe midiéndose contra sí misma; la capa
manual es el hueco que ese guardián no puede tapar, porque quien la escribe
también leyó el patrón de oro. Declarar las dos cifras por separado es lo que lo
tapa.

Las 22 filas se eligieron **por frecuencia en el corpus, no por el patrón de
oro** —`Fur` en 81 artículos, `PqsR` en 155— y cada una lleva su justificación.
Aun así van declaradas aparte: la intención de quien escribe no es verificable y
la procedencia sí.

### Cómo se mide: reconstruyendo, no tachando

**La forma correcta es volver a construir el diccionario con la capa manual
vacía** y medir sobre el resultado. No se toca el TSV publicado. La validación de
que el método es limpio: la misma reconstrucción **con** la capa manual reproduce
`etapa2/genes_pao1.tsv` y `etapa2/operones_pao1.tsv` **byte por byte**, así que lo
único que separa los dos escenarios es la capa manual y nada más.

Tachar filas a mano se equivoca, y se equivoca en las dos direcciones. Las dos
formas ingenuas se midieron:

- **Borrar toda fila cuya procedencia incluya `manual`** tira 22 filas y da 43.
  Da el número correcto por accidente: se lleva por delante a `dnr`, `ada`,
  `fis`, `lrp`, `crc` y `hfq`, que RefSeq, KEGG y UniProt **sí** nombran.
- **Borrar solo los alias que aportó la capa manual** da 47, y es el error que
  esta sección corrige. Parte de suponer que la capa manual solo añade alias, y
  no es cierto: cuando ninguna fuente pública nombra el locus, **la capa manual
  aporta el símbolo mismo** (`construir_diccionario.py:1015`). Mirando el TSV
  publicado, `PA3678` aparece con `simbolo = mexL` y procedencia
  `refseq|kegg|uniprot|manual`, y es fácil concluir que RefSeq trae el nombre. No
  lo trae: en el GFF, `PA3678` y `PA2523` son registros **sin campo `gene=`**, y
  su único nombre público es el locus tag.

### Los doce, y sus cinco causas

`Anr`, `CpxR`, `CzcR`, `Fur`, `HasI`, `HptB`, `IHF`, `MexL`, `PirR`, `PqsR`,
`PrrF`, `Vfr`. Ninguno es un gen desconocido:

1. **Cuatro locus sin nombre público** — `CzcR` (PA2523), `HasI` (PA3410),
   `HptB` (PA3345), `MexL` (PA3678). El símbolo se lo pone la capa manual.
2. **Tres con símbolo público en minúsculas y fila sensible a mayúsculas** —
   `Fur`, `Anr`, `Vfr`. Ver la subsección siguiente.
3. **Uno con otro nombre en las bases** — `PqsR` es `mvfR` en las tres.
4. **Dos que no son un gen** — `IHF` (RefSeq trae `ihfA` e `ihfB`, no el
   complejo), `PrrF` (trae `prrF1` y `prrF2`, no el colectivo).
5. **Dos que no resuelve ni la capa manual** — `CpxR` (PA3206) y `PirR`
   (PA0708): filas que existen y llevan `es_tf`, pero cuya única superficie es el
   locus tag.

Hay una lectura más laxa que da **46**: contar también cuando se reconoce la
forma de gen aunque no la de proteína, o sea aceptar que `fur` cubre a `Fur`. Se
reportó la estricta porque **el corpus escribe la forma de proteína**: `Fur`
aparece 573 veces, `Anr` 500 y `Vfr` 555. Un diccionario que solo conoce `fur` no
los encuentra en el texto, que es para lo que sirve el diccionario.

Efecto colateral que conviene tener presente: sin capa manual el diccionario baja
de 5 642 a 5 639 filas y de 572 a 570 marcas de factor, y la tabla de operones de
3 030 a 3 028 —desaparecen `mexJK` y `hptB-recQ`—. `mexJK` es blanco de una fila
del patrón de oro, o sea que la capa manual también mueve el lado de los blancos.

### Por qué no se automatiza la forma capitalizada

Parece que bastaría derivar `Fur` de `fur`, que es la convención bacteriana que
`CLAUDE.md` ya declara. No basta, y `lexico.py` lo dice donde registra las
superficies: para una fila insensible a mayúsculas añadirla no aporta, y para
una sensible —que son justo los símbolos de tres letras— sintetizar `Cat`, `His`
o `Fis` reintroduce el falso positivo que `sensible_mayusculas` existe para
matar. Un gen sensible que necesite su forma de proteína va como alias, **donde
alguien lo firma**.

Lo que queda pendiente entonces no es automatizar la capitalización sino
**cambiar la firma por una cita**: tomar esos nombres de los nombres de proteína
y sinónimos de gen de UniProt, que es fuente pública, en vez del criterio de
quien construye. Faltarían `IHF` y `PrrF`, que necesitan que el flujo admita
complejos y familias de ARN, y `CpxR` y `PirR`, que necesitan una decisión
escrita: la asignación habitual de `CpxR` contradice a RefSeq, que llama a ese
gen sensor de dos componentes, y de `PirR` no se halló corroboración pública de
ningún tipo.

## Cuatro guardianes que miden contenido, y lo que un codigo 0 todavia no garantiza

Los cuatro huecos que se cerraron en esta ronda eran el mismo error repetido:
**se comprobaba la etiqueta y no el contenido.** Un archivo que dice ser
predicciones se aceptaba por tener las columnas que promete, no por traer dentro
algo que pudiera ser una prediccion. La prueba de que era un error de verdad es
que un clasificador que contesta siempre `activates`, sin leer nada, salia
certificado con codigo 0.

### Lo que se cerro

1. **El acierto de signo se contrasta contra la clase mayoritaria, no solo
   contra el azar.** El azar es un rival debil cuando una clase domina: el oro de
   las 139 filas comparables trae 97 `activates` y 42 `represses`, asi que decir
   siempre `activates` acierta el 69.8 %. Antes eso bastaba para «se distingue
   del azar, codigo 0». Ahora hay que despegar de **las dos** lineas base, con
   una binomial exacta de una cola. Medido: el clasificador constante saca 69.8 %
   contra 69.8 %, ventaja +0.0 pp, p = 0.542, **codigo 2**. Y el guardian no es
   de los que saltan siempre: un clasificador de palabras clave de verdad saca
   84.9 % contra 68.1 %, p = 0.000, codigo 0.
2. **Las cuatro probabilidades se revisan al leerlas**, dentro de
   `cargar_predicciones()` y no en `main()`, para que ningun consumidor del
   modulo pueda saltarselo. Se comprueba que cada una este en `[0,1]` —que es lo
   que atrapa `nan`, con el que `abs(nan - 1) > 1e-3` es falso—, que sumen 1, y
   ademas que la columna `prediccion` sea de verdad la clase mas probable. Esa
   tercera hace falta: sin ella, una distribucion legitima con la etiqueta
   cambiada pasa, y `p_represses = 0.9` se publica como activacion.
3. **El diccionario declara su procedencia y ademas se mide contra el corpus.**
   Una fuente `oro` aborta antes de leer un solo documento. Pero la etiqueta sola
   no basta, asi que se cuenta cuantas entidades reconoce **por su nombre** en el
   corpus, sin contar los locus tag: la literatura de PAO1 escribe muchos
   `PA1234`, y un diccionario de relleno que conserve los 5 642 locus tags sigue
   reconociendo miles. Por nombre: 1 935 el diccionario real, 865 el falsificado.
   El minimo esta en 1 500.
4. **El cache se verifica byte a byte y, ademas, cruzando las tres fuentes.**
   Cada lectura compara el sha256 y el tamano contra el manifiesto. Y como el
   manifiesto tambien es texto, se comprueba que RefSeq, KEGG y UniProt coincidan
   en como se llama cada locus tag: en la descarga honesta, de 1 766 simbolos del
   GFF hay **uno solo** sin respaldo en ninguna de las otras dos. El tope esta en
   12.

Cada guardian tiene al menos una prueba que muere si se desactiva, comprobado
mutandolo y no suponiendolo. La suite de la etapa 2 pasa de 453 a **482 pruebas**.

### Lo que sigue abierto, y esta demostrado

Dos agentes adversarios volvieron a correr los ataques contra el codigo ya
reparado y contra codigo nuevo. Lo que sigue no son sospechas: cada uno se
ejecuto y produjo el numero que se cita.

- **La contaminacion parcial es invisible y ademas mejora todos los numeros.**
  El guardian de circularidad se anuncia como graduado y no lo es. Con el
  diccionario genuino mas 771 filas copiadas del patron de oro —el 12 % de las
  filas— la fraccion que deberia subir **baja**, de 25.6 % a 23.8 %, porque los
  nombres del oro emparejan con todo el genoma y engordan el denominador.
  Mientras tanto la cobertura publicada sube de 89.8 % a 96.0 % y la
  exhaustividad de 79.0 % a 86.4 %, todo con codigo 0 y sin un aviso. Solo
  dispara cuando el diccionario es casi puro oro, que es justo el umbral de todo
  o nada que dice no ser. **Y la contaminacion parcial es la unica que alguien
  cometeria por descuido.**
- **El manifiesto del cache lo escribe el propio script.** Quien pueda alterar
  el GFF puede alterar el manifiesto. Envenenando las tres fuentes de forma
  coherente —el mismo trabajo tres veces, unos veinte minutos— el diccionario
  sale con codigo 0 y con **190 de 190 relaciones del oro cubiertas**, contra
  170 de 190 del honesto, y recorre el pipeline entero hasta «el acierto de signo
  despega de las dos lineas base. Codigo 0». La senal que lo delataria ya se
  calcula y se imprime —los simbolos repetidos saltan de 13 a 111— pero no es
  invariante, o sea que nadie la mira.
- **`evaluar_oro.py` recibe cuatro archivos y no comprueba que sean de la misma
  corrida.** El numerador de la exhaustividad sale de `--red` y el denominador
  entero de `--pares`, y nada ata los dos. Con la **misma** `red.tsv` y un
  `pares.jsonl` podado, la exhaustividad pasa de 80.6 % a 100.0 % con codigo 0.
  Mezclar dos corridas genuinas —el accidente realista, porque las dos escriben
  en rutas por omision fijas— da 80.1 %, que no es la cifra de ninguna de las
  dos. Lo que falta ya esta escrito en el disco: `red.py` deja en
  `red_informe.json` que pares y que predicciones consumio, y `evaluar_oro.py` no
  abre ese archivo ni una vez, aunque `evaluar_signo.py` si lo abre para otra
  cosa.
- **`--disputadas` vacia el denominador y su unico control es que la
  justificacion no este vacia.** Pasando las 14 filas que el pipeline recupero
  con el signo al reves, el acierto de signo sube de 85.1 % a **100.0 %**,
  despega de las dos lineas base y sale con codigo 0. Con 7 filas elegidas a
  proposito el denominador cae exactamente en el 169 que anuncia la
  documentacion, lo que hace la corrida *mas* creible. Las dos lineas base se
  calculan sobre el conjunto ya recortado, asi que el mecanismo que existe para
  detectar seleccion es ciego justo a esta.
- **Los umbrales no quedan registrados.** Sobre las mismas predicciones: con
  umbral 0.50 la exhaustividad sale 93.8 %; por omision, 80.6 %. Trece puntos, y
  los dos `evaluacion_oro.json` son indistinguibles porque ninguno guarda el
  umbral. El agravante es que la corrida ajustada a mano es **mas silenciosa**
  que la honesta: el aviso de «umbrales por omision» solo se imprime cuando son
  los de omision.

### La consecuencia, dicha sin adornos

**Hoy, un codigo de salida 0 de este pipeline no certifica que la cifra se pueda
citar.** Para citarla hace falta ademas el `red_informe.json` de esa corrida, la
lista de filas disputadas y el umbral con que se corrio, y que quien la cite haya
regenerado el diccionario desde una descarga suya. Eso es peor de lo que la
palabra «guardian» sugiere, y por eso queda escrito aqui y no solo en el informe
de un agente: **la mitad del trabajo de la etapa 2 es que estas cinco cosas
dejen de ser ciertas.**

## Dos de las cinco cerradas: la cadena y la cobertura del oro

De las cinco maneras de inflar una cifra que quedaron documentadas arriba, dos
ya no funcionan. Se cerraron **antes** de la primera corrida del clasificador
con el modelo real, y ese orden no es casual: un guardián puesto después de la
cifra que protege llega tarde, porque la cifra ya se citó.

### La cadena: `etapa2/procedencia.py`

El ataque era mezclar pasos de corridas distintas. Los nombres de archivo son
siempre los mismos —`pares.jsonl`, `predicciones.jsonl`, `red.tsv`—, así que
basta rehacer un paso y no los otros, o copiar uno de una carpeta vieja. Cada
archivo por separado está bien formado, así que nada protestaba: **la misma red
publicaba 80.6 % o 100.0 % de exhaustividad según qué archivo se le pusiera al
lado, con código 0.**

Comparar rutas no sirve, porque la ruta es la misma y lo que cambia es el
contenido. Se comparan los bytes: `red.py` sella el sha256 de sus dos entradas
y de su propia salida en `red_informe.json`, y las dos evaluaciones exigen que
lo que van a leer coincida. Si no, salen con 1 y no escriben nada.

Se recorta el digest a 16 hexadecimales —64 bits— a propósito. Es de sobra para
descartar una confusión accidental, que es de lo que esto protege. **No protege
de un adversario y no pretende hacerlo**: quien pueda reescribir los archivos
puede reescribir el informe.

Un informe viejo, de antes de que esto existiera, **no bloquea**: avisa y deja
seguir. Bloquear ahí castigaría a quien no hizo nada malo; callarse dejaría
creer que se comprobó algo que no se comprobó.

### La cobertura del oro, y por qué el indicador anterior iba al revés

El otro ataque era contaminar el diccionario **a medias**: copiarle un 12 % de
filas del patrón de oro. No disparaba ningún aviso, subía todas las cifras, y
—lo peor— **bajaba el indicador que debía detectarlo.**

La razón está en el denominador. `fraccion_explicada_por_el_oro` es
*pares con los dos extremos en el oro* entre *pares que el pipeline sacó del
corpus*, y ese denominador **crece al contaminar**: los nombres copiados
reconocen menciones nuevas y generan pares nuevos, muchos con un solo extremo
en el oro. La contaminación se diluía a sí misma.

`cobertura_del_oro` mide contra el vocabulario del patrón, que es un conjunto
**fijo** de 625 nombres. Copiar filas solo puede meter nombres en la
intersección, nunca sacarlos: es monótona por construcción y no se puede
diluir. Medido: el diccionario honesto de las tres fuentes públicas cubre 387
de 625 (**0.619**); metiéndole los 238 que le faltan, sube a **1.000**.

Que suba no prueba trampa —un diccionario de verdad mejor también sube—, y por
eso el aviso a partir de 0.80 pide justificación en vez de acusar. Lo que sí es
implausible es acercarse a 1.0: hay 12 de los 55 factores del oro que RefSeq,
KEGG y UniProt no traen, así que cubrirlos todos significa que salieron de otro
lado. A partir de 0.95 aborta.

### El guardián nuevo va después del viejo, no antes

`revisar_cobertura_del_oro` se llama **después** del guardián de §6, aunque sea
más barato y lo natural fuera ponerlo antes. §6 es una conjunción —cobertura
total **y** diccionario diminuto— y cuando aplica da mejor diagnóstico, porque
nombra las entidades útiles y las líneas del archivo. El de cobertura recoge
justo lo que esa conjunción deja pasar: un diccionario grande y legítimo al que
le copiaron nombres.

Ponerlo antes le robaba el mensaje al otro sin ganar nada, y de hecho rompió
dos pruebas existentes al hacerlo. Se detectó por eso.

### Las pruebas que los mantienen vivos

`etapa2/test_procedencia.py`, 23 pruebas. La que importa es la de extremo a
extremo: le da a `evaluar_oro.main()` archivos de dos corridas distintas y
afirma que **devuelve 1 y no escribe resumen**. Las de unidad prueban el
módulo; esa prueba que está *conectado*, que es donde murió el guardián de
`particionar.py`: la función sabía fallar y nadie la llamaba con datos que la
hicieran fallar.

Para la cobertura hay dos que fijan la propiedad que la hace útil: meter
nombres del oro **siempre** la sube, y meter 500 genes ajenos al oro **no la
mueve**. Esa segunda es la que la anterior no habría pasado.

Y en `test_evaluar.py` queda la contaminación a medias con un diccionario de
1500 entidades útiles: §6 no se dispara —el diccionario no es diminuto— y el de
cobertura sí. Es el hueco exacto del informe, cerrado y con su prueba.

### Lo que sigue sin estar cerrado

Tres de las cinco: la bandera de disputadas cuyo único control es que la
justificación no esté vacía, los umbrales que no quedan registrados, y el
manifiesto del caché que escribe el mismo programa que descarga. Las tres
siguen documentadas arriba con el ataque que las demuestra.

## Los operones de PGD salen de la exportación de su curador, no de la página

El 27 de septiembre de 2026 el asesor pidió, sin alternativa, los operones de
PAO1 tal como los muestra Pseudomonas Genome DB en la vista de cada gen
(`feature/show/?id=109783&view=operons`). Esa vista muestra cuatro cosas:
- el nombre del operón;
- la tabla de genes (locus tag, nombre, descripción, inicio, fin, hebra, tipo);
- la evidencia;
- la referencia.

Esta sección cuenta cómo se consiguió, por qué por esa vía y qué se comprobó
en cada paso. Los números están en la bitácora del 27-sep, y la medición del
sitio en `hallazgos.md`.

### Por qué no se raspa la página

Es el mismo caso que PMC: se ve bien en el navegador, así que parece fácil
bajarla. Aquí hay tres razones en contra, y cualquiera basta:

- **El sitio entero está detrás de un desafío administrado de Cloudflare.**
  Se hizo una petición por URL con `urllib` y 2 s entre peticiones, sin
  cabeceras de navegador, a nueve rutas: `robots.txt`, la página de
  descargas, los archivos estáticos de `/downloads/`, el export CSV de
  `feature/list` y la vista de operones. Todas contestaron 403 con
  `Cf-Mitigated: challenge`. Pasar eso exige un navegador que resuelva el
  desafío, y CLAUDE.md lo prohíbe: es dependencia y es evasión.
- **El `robots.txt` prohíbe la recolección automatizada** sin permiso escrito
  del operador (copia de Wayback, agosto de 2025).
- **No hay archivo que bajar.** La página de descargas del release 22.1
  (Wayback, febrero de 2025) ofrece FASTA, anotación y ortólogos por cepa, y
  ningún archivo de operones. Los operones solo existen como HTML, un gen a la
  vez, y 5 700 páginas raspadas sería justo lo que el sitio pide no hacer.

Un detalle de método que evita una conclusión falsa: una ruta inventada bajo
`/downloads/` también contesta 403. Con el desafío delante, el 403 no dice si
una URL existe. Lo que existe se supo por las capturas de Wayback, no por
sondear el sitio.

### Cómo se encontró la vía que sí funciona

El sitio no daba los datos, así que se buscó quién los hubiera recibido del
curador. Tres pistas, cada una confirmada en su fuente primaria:

1. **Qué muestra la vista.** Una captura de Wayback de la página de operones
   de `oprM` enseña dos orígenes: predicciones de **DOOR** (Mao et al. 2009,
   PMID 18988623) y operones curados de **PseudoCAP**, con su artículo.
2. **Quién tiene esos datos en bloque.** Lee et al. 2023 (*mSystems*,
   doi:10.1128/msystems.00342-22) dice en Métodos que «the operon data were
   provided by Geoff Winsor», el curador de PGD, «and include computationally
   predicted annotations from DOOR as well as curated annotations from
   PseudoCAP».
3. **Dónde quedó.** El laboratorio Greene publicó esa tabla con licencia BSD-3
   en `greenelab/core-accessory-interactome`,
   `data/metadata/PAO1-operons-2021-07-19.csv`.

La URL se fija a un commit (`25539b82…`, en `fuentes.URL_PGD`). Una rama se
mueve y un commit no, así que los bytes que se bajen dentro de un año son los
mismos que se revisaron hoy.

### Cómo se comprobó que es la misma información

No bastaba con que la tabla viniera del curador: tenía que ser lo que muestra
la página. Se comparó contra la captura que mandó el usuario de la página de
`metG`. La tabla trae `operon-714`, `metG-PA3483`, PA3482 en 3895324–3897357
(+) y PA3483 en 3897391–3898191 (+), DOOR y PMID 18988623. Coincide campo por
campo.

Lo que la tabla no trae es la descripción ni el tipo de cada gen. Salen de
RefSeq (`genes_pao1.tsv`), y el encabezado del CSV lo dice, porque PGD redacta
distinto: «methionyl-tRNA synthetase» frente a «methionine--tRNA ligase».

El límite queda escrito donde se usa: es una foto del 19 de julio de 2021, y
el release vigente es del 6 de octubre de 2023. Una versión nueva se pide a
pseudocap-mail@sfu.ca, que es como la consiguió el laboratorio Greene.

### Lo que el parser hace porque el archivo lo obliga

`parsear_pgd` se escribió después de perfilar el archivo real completo
(3 816 filas), no a partir de la cabecera. Cada regla responde a algo medido:

- **Agrupa por `operon-id`, no por filas seguidas.** En 103 de los 1 290
  operones las filas no van juntas.
- **Quita los genes repetidos.** Tres operones de PseudoCAP repiten cada gen
  una vez por artículo; sin esto, `oprE` saldría `PA0291|PA0291`.
- **Entrega los genes en orden de transcripción.** El archivo va ascendente
  por coordenada en las dos hebras, y en la hebra menos eso es al revés. El
  nombre lo delata: `PA0006-lptA` son PA0006 y luego PA0005.
- **La cita de DOOR no va a `pmid`.** Las 3 517 filas de DOOR citan el
  artículo del método, no una demostración del operón. En `pmid`, ese
  artículo aparecería en la columna `pmids` de 1 165 operones como si fuera su
  evidencia, y cada uno quedaría marcado `comp_con_cita` para revisión a mano
  sin motivo. Va en `registro_raw["referencia_metodo"]`, y el CSV de la vista
  la muestra porque la página también.
- **Exige su contrato y falla fuerte.** Encabezado exacto, hebra 1/-1, origen
  DOOR o PseudoCAP, coordenadas enteras. Cualquier otra cosa lanza
  `FormatoDesconocido`, igual que ODB y CDBProm. El locus tag se valida con
  `LOCUS.fullmatch` y nunca se extrae con `findall`: `findall` convierte
  `PA4726.11` en `PA4726`, que es otro gen.

### No volver a bajar lo que no cambia, sin quedar atascado

Como la URL está fijada, bajarla dos veces solo repite 1 290 filas. Por eso
`extraer --fuente pgd` no la pide si ya hay una foto que sirve. La primera
versión de esa regla («si la última extracción trajo esta URL, ya está») tenía
dos fallas, y las dos se reprodujeron antes de corregirse:

- **Revertía tablas nuevas.** Si alguien metía una tabla más nueva con
  `--archivo`, el siguiente `extraer` sin argumentos bajaba la de 2021 encima
  y daba por «retirados por la fuente» los operones que solo traía la nueva.
- **Se atascaba.** Un parseo fallido también cierra la extracción como
  completa, con 0 filas. Si eso contaba como «ya está», PGD quedaba vacía
  para siempre. Y si faltaba el crudo, `reparsear` pedía volver a extraer
  mientras `extraer` contestaba «ya está, usa reparsear».

La regla que quedó (`fuentes.foto_sana`): sin URL explícita, no se baja nada
mientras la foto vigente tenga filas y su crudo siga en disco con la huella
registrada, venga de donde venga. `--url` explícito siempre baja, incluso con
la URL fijada, porque una orden no es una sugerencia.

### Lo que la integración destapó

Meter una cuarta fuente sacó a la luz dos errores que ya estaban en el código
y que se le habían presentado al asesor el 25-sep:

- **El promotor se buscaba sobre el gen equivocado.** `curar` tomaba como
  primer gen transcrito el primero de la lista, pero BioCyc lista los genes
  en orden descendente en las dos hebras y ODB en orden ascendente. En 515 de
  1 082 operones multigénicos con hebra conocida ese no era el primer gen.
  Ahora lo decide la hebra (`curar.primer_gen`). Los operones con promotor
  CDBProm pasan de 1 350 a 1 390 sin PGD: se ganan 139 y se pierden 99. Se
  corrigió antes de meter PGD, para que el efecto de cada cambio se pudiera
  medir por separado.
- **PGD y BioCyc se contaban como una sola fuente por una premisa falsa.** El
  repositorio decía que PGD también predecía con Pathway Tools, y no es así:
  predice con DOOR (Winsor et al. 2011, doi:10.1093/nar/gkq869). Se quitó
  `FUENTES_NO_INDEPENDIENTES`.
  - Lo que sí es dependiente es la literatura: ODB, BioCyc y PseudoCAP pueden
    citar el mismo artículo.
  - Contar por PMID único quedó como decisión del asesor, no del código.

### Cómo se revisó antes de darlo por bueno

El trabajo tuvo tres barreras, y cada una encontró algo que la anterior no vio:

1. **Revisión del plan contra el código, antes de escribir nada.** Encontró
   seis defectos del diseño:
   - el orden inverso en la hebra menos;
   - los genes repetidos;
   - una sexta regex de locus tag que no hacía falta;
   - la columna PMID de DOOR, que habría hecho fallar la comparación con la
     captura;
   - una prueba que escribía en la carpeta de datos real;
   - el error del primer gen.
2. **Pruebas que reproducen el archivo real.** El fixture son filas
   verdaderas de la tabla, que es pública: `metG`, un operón de la hebra menos,
   uno con filas separadas, `rsmY` con sufijo `.1` y el de PseudoCAP con genes
   repetidos. También cubren la página de desafío de Cloudflare como cuerpo
   que se tiene que rechazar.
3. **Revisión adversarial del código terminado.** Tres revisores
   independientes (parser y extracción; curación y exportación; reglas y
   documentación) y un escéptico por hallazgo, encargado de refutarlo.
   Confirmaron 14 hallazgos, que se reducen a 8 defectos distintos, y
   refutaron 2. Entre los confirmados:
   - las dos fallas de «ya está»;
   - un `csv.Error` que se escapaba del contrato;
   - dos cifras mal atribuidas en la bitácora.

   Cada defecto de código quedó con una prueba que reproduce su escenario.

Al cerrar pasaban 576 pruebas en la raíz (35 nuevas) y 524 en `etapa2`.

### Cómo reproducirlo

```bash
python -m grn_operones.cli extraer --fuente pgd    # una petición a GitHub
python -m grn_operones.cli curar
python -m grn_operones.cli exportar                # ..._pgd.csv: la vista de la página
```

Correr `extraer` otra vez dice «ya está» y no pide nada. `reparsear --fuente
pgd` vuelve a leer el crudo desde disco, sin red y comprobando la huella.

### Lo que queda abierto

- Contar la literatura por PMID único, para que dos fuentes que citan el mismo
  artículo no cuenten como dos respaldos.
- Pedir a PGD la tabla del release vigente, con permiso escrito. *El borrador
  del correo está listo desde el 20-oct-2026.*
- `es_adyacente` ignora el sufijo `.N`, así que `PA0668.1|PA0668.2` cuenta
  como paso 0 y sale no adyacente. 38 de los 55 operones marcados como no
  adyacentes tienen algún locus `.N`; cuántos son falsos positivos no se ha
  revisado uno por uno. *Cerrado el 20-oct-2026: el sufijo cuenta, y quedan
  17 no adyacentes.*
- Un `--archivo` con una página de desafío guardada deja a PGD sin operones
  hasta el siguiente `extraer --fuente pgd`, que la rehace. *Cerrado el
  20-oct-2026: una extracción sin filas ya no desplaza a la foto vigente.*

## La base de operones anota el bronce, no lo detecta

Con ODB, BioCyc y PGD dentro de `grn_operones`, lo natural parecía meterla
al paso 1 y volver a correr el bronce. Se midió antes de hacerlo (27-sep-2026),
simulando cada variante contra las 7 136 menciones de operón de la corrida 4,
con el `lexico` real cargado en memoria:

| variante | faltantes resueltos (de 103) | efecto en el corpus |
|---|---|---|
| sumar los 71 operones con nombre de literatura | 1 (`exsCBA`, 7 menciones) | +208 menciones nuevas, casi todas falsas: `psl` (el polisacárido Psl) 155, `amidase` (sustantivo común) 22, `ars` («ARs») 8 |
| sumar las 1 200 unidades con nombre | 2 | +356 menciones que **se comen 343 menciones de genes y proteínas**: «CbrA-CbrB» pasa a ser un operón y el paso 2 pierde regulador y blanco |
| reemplazar `operones_pao1.tsv` | 1-2 | se pierden entre 3 251 y 4 554 de las 6 689 menciones que hoy se resuelven (MexXY, CbrAB, AmgRS…) |

Hay dos razones de fondo:
- **Los faltantes casi no son operones.** Los mayores de los 103 (exoSTY,
  rsmZY, phzMS, lasRI, cyaAB) son genes separados en el genoma que el texto
  abrevia juntos. Solo 3 de los 103 tienen su conjunto exacto en la base.
- **Los nombres de la base no están en el texto.** O ya están en el catálogo
  del paso 1, o son uniones sintéticas de DOOR (`PA0006-lptA`) que nadie
  escribe.

Además el detector está atado por tres cosas:
- la regla §6.3 del contrato, que solo autoriza expandir con la tabla
  derivada del diccionario;
- la copia congelada de `etapa2/operones_pao1.tsv`;
- 41 nombres de la base iguales al nombre de un gen (`exoT`, `mexR`), que
  convertirían todas sus menciones en «operón».

**Lo que se hizo en su lugar: anotar al exportar, sin tocar la detección.**
Cada oración candidata dice si tiene operones y cuáles:
- **`hay_operon`** (si/no);
- **`operones_en_oracion`**: los que nombra más aquellos a los que pertenecen
  sus genes según la base (`grn_bronce/recursos/operones_base.tsv`), sin
  repetir. Si la oración nombra `mexAB-oprM` y además dice `mexA`, el operón
  sale una sola vez.

Cuentan las unidades de más de un gen, principales, más las alternativas que
no son solo predicción. Excluir todas las alternativas ocultaba 32 unidades
con evidencia (31 conocidas y 1 curada; 11 respaldadas por ODB, las demás por
BioCyc o PseudoCAP), 20 de ellas dentro de unidades solo predichas. Por
ejemplo, `rnc-era-recO` (ODB), `tolQR` (PseudoCAP) y `bphOP` (BioCyc y
PGD).

`python -m grn_bronce.cli exportar --corrida 4` volvió a volcar la corrida 4
**sin identificar de nuevo**:
- no creó corrida y la fila de la 4 quedó intacta;
- las 28 columnas originales de las 29 659 candidatas salieron idénticas a
  las del 17-sep, así que la detección no se movió;
- 23 445 candidatas tienen al menos un operón, nombrado o por pertenencia;
- `VERSION` no subió, porque ninguna fila de la base cambió. La huella del
  recurso queda en el resumen.

`grn_bronce` no importa `grn_operones`: lee un archivo generado cuyo
contrato vive en `grn_bronce/operones.py`. La dirección de las dependencias
no cambia.

**Pendiente de la decisión 3.** La pertenencia sale de ODB, BioCyc y PGD.
Decisión 3 (abierta): respuesta verbal, probable (semana del 5 al 9 de octubre
de 2026). GRN_experimental es la red regulatoria y no una fuente de operones.
Falta confirmar por escrito si alguna relación se amplió por pertenencia a
operón; hasta entonces la pertenencia solo anota. La pregunta escrita está en
`operones-asesor.md` §8.

## El flujo corre cada paso como proceso aparte y se salta lo hecho por huella

`flujo.py` (8-oct-2026) no importa los pasos: llama a los CLI que ya existían
por subproceso, con `grn_comun/proceso.py`. Hay tres razones:
- **Cada paso necesita un intérprete distinto.** El BioBERT pide torch, la
  sintaxis pide spaCy con numpy < 2, y el resto es estándar. En un solo
  proceso no caben.
- **`etapa2` está congelada.** Llamar a `clasificar.py` y `red.py` tal como
  están no obliga a tocarlos.
- **Cancelar.** Un hilo de Python no se puede matar; un árbol de procesos sí.
  `proceso.correr` lanza cada paso en su propio grupo, y un vigía mira el
  evento `detener` cada medio segundo. Mata también al nieto, porque el paso
  `biobert` lanza a su vez `clasificar.py`.

Saltar lo hecho se decide **por huella de contenido, no por fecha de
archivo**. Cada paso declara:
- sus entradas, **incluido su propio código** (el CLI y los módulos que
  lee);
- sus parámetros;
- sus salidas, que tienen que seguir existiendo con la huella que dejaron.

La fecha falla en las dos direcciones: un `git checkout` toca archivos sin
cambiarlos, y copiar una carpeta entre máquinas conserva fechas de archivos
que sí cambiaron. Meter el código en la huella es lo que hace que un arreglo
del bronce rehaga el bronce sin que nadie se acuerde de pedirlo.

La consecuencia buena se vio en la corrida del 8-oct. El bronce se rehízo, pero
`pares.jsonl` salió idéntico, y BioBERT y la red se saltaron solos: la cadena
se corta donde el contenido deja de cambiar, no donde cambió algo arriba.

El estado vive en `estado.json`, escrito de forma atómica después de cada paso.
Cada carpeta lleva un candado `.flujo.lock` con `O_EXCL`: dos flujos sobre la
misma carpeta se pisarían los archivos. Si el proceso muere de golpe, el
candado queda y el mensaje dice cuál borrar; no se adivina si el dueño sigue
vivo.

## El puente al BioBERT reutiliza el marcado del entrenamiento, y la caché es por texto

`grn_verificacion/puente.py` no escribe su propio marcado `<e1>`/`<e2>`: usa
`etapa2/extraer_pares.candidatos_de_oracion` y su `verificar()`. Es la función
que produjo los pares del 27-ago, y su marcado reproduce línea por línea el de
los datos de entrenamiento (lo vigila
`test_marcar_reproduce_lineas_literales_del_entrenamiento`). Un marcado
distinto en inferencia es la forma más barata de medir otro modelo sin
enterarse.

Las predicciones del 27-ago se reutilizan, pero solo bajo tres condiciones:
- el **texto marcado es idéntico**;
- el **checkpoint es el mismo**: misma huella de los pesos y del tokenizador,
  y mismo `config.json`, `id2label` y `max_length`;
- la caché es **por texto, nunca por `id_par`**.

La segunda condición se endureció el 8-oct, en la auditoría antes de
publicar. Al principio solo se comparaba el `config.json`, y el de un BERT
afinado no depende de los pesos: dos reentrenamientos con la receta del
run 22 lo escriben idéntico byte a byte. El modelo entrenado con la base
curada habría heredado sin aviso las predicciones del limpio. Los metas que ya
existían no traían la huella de los pesos; se sellaron a mano después de
reclasificar 48 de sus predicciones con el checkpoint actual (48 de 48 con la
misma clase, diferencia máxima 1e-6), y el sello dice cómo se hizo. Al del
27-ago, escrito por `clasificar.py`, también le faltaba la huella de su
`pares.jsonl`: se selló después de comprobar sus 63 791 pares uno por uno
(mismo `id_par`, en el mismo orden, con el mismo regulador y blanco).

La tercera no es un detalle. `id_par` sale del PMID, la sección, el número de
oración y las dos entidades, no del texto. Si el bronce cambia una oración y
conserva su número, unir por `id_par` le pega a la oración nueva la predicción
de la vieja, y nada falla. Hay una prueba que lo vigila. Donde la unión por
`id_par` es inevitable (con el `pares.jsonl` de otra carpeta, o en la capa),
se exige antes que las predicciones sean de ese mismo `pares.jsonl`, por su
huella.

Antes de confiar en la reutilización se reclasificaron 14 pares. Salieron
14 de 14 con la misma clase y una diferencia máxima de probabilidad de 1e-6.
Con eso, el 81.8 % de los 72 969 pares no volvió a pasar por el modelo. Las
13 293 nuevas tomaron 998 s de CPU; todas, a esa velocidad, cerca de hora y
media.

## La sintaxis vive en un `.venv-nlp` aparte

scispaCy exige numpy < 2 y el `.venv` tiene numpy 2.5.2, que usan torch y
`transformers`. Bajar numpy en el `.venv` arriesgaba el entorno que clasifica.

El `.venv-nlp` lleva spaCy 3.7.5 y el modelo `en_core_sci_md` 0.5.4,
**sin el paquete `scispacy`**. El modelo carga sin él, y el paquete era el
que no instalaba en Python 3.12. Las versiones van fijas en el extra
`[bronce-nlp]` de `pyproject.toml`, con `weasel`, `typer` y `click` acotados:
sin esos topes, pip resuelve versiones que rompen la CLI de spaCy.

Dos reglas mantienen la excepción acotada:
- `grn_bronce/sintaxis.py` es el **único** módulo que importa spaCy, y lo
  hace dentro de sus funciones.
- Sin `.venv-nlp`, el flujo marca el paso como `omitido`, no como error. La
  capa sale igual, con las columnas de sintaxis vacías.

## El entrenamiento con la base curada es supervisión distante, y corre donde vive la base

La base curada es confidencial. El entrenamiento se arma en el servidor del
asesor, que tiene la GPU. El `.xlsx` no estaba ahí: se sube una sola vez,
fuera del clon (`~/grn-guillermo/`), y de ahí no sale. Lo corre el usuario
o, desde el 9-oct-2026, una sesión de Claude abierta en el servidor con
`reentrenar` (ver la decisión siguiente). A una sesión de Claude solo
vuelven conteos y métricas.

`grn_verificacion/validacion.py` lee el `.xlsx` con `zipfile` y
`ElementTree`, sin openpyxl, para correr con el Python que ya haya. La ruta
llega por argumento: la guarda de contaminación sigue sin nombres en su lista
blanca.

Las reglas de `entrenamiento.py`, y la razón de cada una:
- **Positivo:** el par coincide por locus con una fila de la base y el PMID de
  la oración está en `Reference`. Es la regla b del PLAN 2.4: el locus solo no
  dice que esa oración afirme la relación.
- **Fuera la homología:** viene de otro organismo, no de la oración.
- **Fuera `Origen = BioBERT`:** sería entrenar al modelo con sus propias
  salidas.
- **Fuera el signo `d`.**
- **Negativos:** coocurrencias de los mismos PMIDs que no están en la base en
  ningún sentido. Son negativos ruidosos, y se reportan así.
- **Reservados:** los PMIDs y las oraciones de la muestra de 50, y las
  oraciones del conjunto ciego, no entran. Hasta el 9-oct solo se reservaban
  los PMIDs de la muestra. Eso apartaba el artículo, pero no una copia de la
  oración juzgada en otro artículo: `_sin_repetidos_entre_pmids` corre después
  de quitar lo reservado y ya no veía el original. En la corrida 4 no pasaba
  (los reservados por oración siguen en 516), pero no estaba garantizado.
  **Reservar oraciones no aparta pares.** Los 6 pares del conjunto ciego
  entran desde otras oraciones con la etiqueta de la base, así que para un
  modelo entrenado aquí la trampa del signo deja de ser una evaluación
  externa. El 9-oct se decidió dejarlo así y declararlo: `RESULTADOS.md`
  cuenta cuánto entró.
- La partición va por PMID (`particionar.py --por pmid`). La métrica de
  *E. coli* se contaminó justo por partir por oración. Aquí partir por PMID no
  basta para medir generalización: la etiqueta depende casi solo del par, y
  el mismo par cae en train y en test. Se decidió no entrenar dos veces
  (`--por par`) y reportar junto al F1 una línea base que solo recuerda el
  par: el modelo vale lo que le gana.

## La pista D es un orquestador desprendible, y lo que se publica es un informe filtrado

La guía del 8-oct eran tres comandos a mano dentro de tmux. La revisión del
9-oct encontró que, seguida al pie de la letra en el servidor, se rompía:

- **No hay tmux**, y pegado entero el bloque entrenaba en primer plano: un
  corte de SSH lo mataba.
- **No había cómo detenerlo.** Matar el PID de `conda run` dejaba vivos a
  `barrido.py` y al script del asesor con la GPU tomada, y en la cuenta
  compartida «tus procesos» no se distinguen por usuario.
- **`barrido.py` sale con 0 aunque el entrenamiento falle**, y está congelado.
- **Pegar la salida en la bitácora publicaba rutas del servidor**, con la
  cuenta si los datos caían bajo el home.

`grn_verificacion/reentrenar.py` lo resuelve en Python y no en un `.sh`. El
camino feliz cabe en veinte líneas de bash, pero lo difícil no: detectar el
fallo que `barrido.py` calla, cotejar la base, la línea base, el filtro, un
tope que alcance al nieto y saltar lo hecho por huella. Además, en bash no se
prueba con unittest. Cuatro piezas que no son obvias:

- **`fcntl.flock` y no un archivo creado con O_EXCL.** El núcleo suelta el
  candado cuando el proceso muere, también por SIGKILL, y no queda uno viejo
  que haya que borrar a mano: el defecto del `.flujo.lock`.
- **Los huérfanos se buscan en `/proc` por una marca en el entorno.** Si el
  orquestador muere por SIGKILL o por el OOM-killer, no alcanza a matar el
  árbol. Antes de volver a entrenar se buscan los procesos con
  `GRN_REENTRENAR=<runs>/<nombre>` en `/proc/PID/environ`, una variable que
  solo pone el orquestador y que heredan `barrido.py` y el script, y se matan
  sus grupos. La primera versión buscaba esa carpeta en la línea de comandos,
  y la revisión del 15-oct encontró por qué no sirve: `flujo.py --modelo` y
  `clasificar.py` nombran la misma carpeta al usar el modelo recién
  entrenado, y una corrida nueva los habría matado.
- **`matar_arbol` espera al grupo, no al hijo** (`grn_comun/proceso.py`,
  lo usa también el flujo). Antes solo mandaba SIGKILL si el hijo directo
  tardaba en morir. Si `barrido.py` moría con SIGTERM y el script del asesor
  no, el nieto seguía con la GPU y con la tubería abierta, y quien leía la
  salida se quedaba esperando: así se saltaba el tope de 4 horas. Ahora lo
  que quede del grupo a los 5 s muere con SIGKILL.
- **El candado no basta si alguien borra el archivo.** Antes de tocar nada,
  una corrida nueva busca si los procesos marcados tienen todavía a su
  orquestador vivo de padre (un huérfano de verdad lo perdió). Si es así, se
  detiene con `otra_corrida` en vez de matar el entrenamiento ajeno.
- **El paso de datos corre dentro del proceso**, no como subproceso. Así sus
  conteos llegan estructurados, y una excepción que no sea `ValueError` (que
  podría traer el valor de una celda en su mensaje) se registra solo por su
  tipo.
- **El informe es publicable por construcción.** Se arma desde datos
  estructurados y no desde el log. Antes de escribirse pasa por una
  verificación que rechaza rutas absolutas o bajo `~`, locus, marcadores de
  entidad y cualquier cosa con forma de PMID. Si no pasa, no se escribe. El
  error dice qué patrón y en qué línea, nunca el texto.
- **Lo que escribe `barrido.py` va con lo confidencial**, en `<runs>/barrido`:
  su JSON y su resumen llevan la ruta absoluta de la partición, y está
  congelado. A `<resultados>` llega una copia con solo números
  (`entrenamiento.json`), atada a la huella de la partición. Esa copia también
  es la que permite relanzar el tramo 1 después de entrenar sin perder las
  métricas del informe.
- **Del conjunto ciego, solo totales.** Contar por etiqueta los ejemplos de
  sus seis pares, que tienen nombre público, diría qué signo les da la base o
  si los registra. Eso ya no es «esquema y conteos».

## La curada v1 se evalúa con un protocolo escrito antes de entrenar

El tramo 1 real (15-oct) mostró tres cosas que el diseño de la pista D no
tenía resueltas. `regulates` tiene 6 ejemplos de 2 artículos y ninguno en dev
ni en test. El test de la partición única tiene 4 artículos. Y ningún código
daba métricas por clase, matrices ni un intervalo para el F1. El 16-oct el
usuario decidió excluir `regulates` en esta versión y aplicar el protocolo
completo (`docs/protocolo-curada-v1.md`).

- **Excluir, no fusionar.** `regulates` es una relación sin signo. Pasarla a
  `activates` o a `represses` le pondría un signo que la base no da, y pasarla
  a `no_relation` sería falso. Se quita antes de particionar y el mapa sigue
  con cuatro etiquetas, así que `clasificar.py` y el flujo no cambian. El
  script del asesor le daría el peso mayor (60 veces el de `no_relation`), y
  con *E. coli* el modelo ya se refugiaba en esa clase. Sin ejemplos, ese
  peso no entra en la pérdida: `CrossEntropyLoss` pondera por la clase
  verdadera.
- **El protocolo se commitea antes del tramo 2, y el informe lo comprueba.**
  Con 96 artículos, elegir después de ver una cifra (otra semilla, otra
  métrica, otro corte) mueve el resultado más que el modelo. `RESULTADOS.md`
  dice el commit del protocolo, si es anterior al inicio de la corrida, y
  lista cada parámetro que se aparta de él.
- **Validación cruzada por artículo con tres semillas, y las predicciones
  juntas.** Con unos 19 artículos por pliegue, el F1 de cada pliegue es ruido,
  y la regla del script cambia de clases de un pliegue a otro. Se juntan las
  predicciones fuera de pliegue de cada semilla y se calcula un macro-F1 sobre
  un conjunto fijo de clases. La media por pliegue con la regla del script
  sigue en el informe, para compararla con el barrido del asesor.
- **Bootstrap por artículo, con los modelos fijos.** Remuestrear ejemplos
  sueltos daría un intervalo demasiado angosto, porque los de un artículo no
  son independientes. Reentrenar en cada réplica costaría 2000 veces la
  corrida. Lo que el intervalo no recoge del entrenamiento lo muestran, en
  parte, las tres semillas.
- **La línea base se fija al particionar.** No depende del modelo, así que el
  tramo 1 ya la reporta (sección 5.1) y va al protocolo antes de entrenar. La
  evaluación la recalcula, y si no da lo mismo se detiene: querría decir que
  las predicciones no están unidas a los ejemplos de su pliegue.
- **Las predicciones por ejemplo salen de `etapa2/clasificar.py`, sin tocar
  nada congelado.** El script del asesor solo escribe métricas agregadas; es
  suyo y no se modifica, y `etapa2` está congelada. `clasificar.py` es además
  la vía de inferencia que usa el flujo, así que también se prueba el
  artefacto. Corre en CPU: son unos cientos de oraciones, y así no compite por
  la GPU compartida. La accuracy por argmax se coteja contra la del script:
  si no cuadra, la unión entre predicciones y ejemplos está mal y no se
  evalúa.
- **Los modelos de pliegue se borran después de predecir.** Son 15, de unos
  400 MB cada uno sin checkpoints. Lo que queda de ellos son sus predicciones
  y su resultado, y con eso basta para retomar sin reentrenar.
- **Un modelo que predice una sola clase es un resultado, no un error.**
  `clasificar.py` se niega a escribir en ese caso, desde 20 filas, porque a
  escala de corpus casi siempre es un modelo mal cargado. Aquí se acepta su
  `.parcial` si todo lo demás cuadra, y el informe lo marca. La marca sale de
  las predicciones, también con menos de 20 filas.

## La v2 sin pesos de clase va por un envoltorio, y la regla se escribió antes

En el flujo, la v1 salió sesgada a la represión, y la hipótesis fue que venía
de los pesos de clase por la inversa de la frecuencia (20-oct).

- **Un envoltorio y no un cambio en `barrido.py` ni en el script del
  asesor.** `barrido.py` está congelado y le pasa siempre
  `--use_class_weights`; el script es del asesor.
  `grn_verificacion/sin_pesos.py` quita ese flag y hace `execv` del script
  real, que llega en `GRN_SCRIPT_REAL`. Con `execv` el PID es el mismo, así
  que el tope de horas y `detener` lo alcanzan igual. `reentrenar
  --sin-pesos-de-clase` lo pone en lugar del script.
- **Los pesos son un parámetro de la corrida.** Quedan en `parametros` y en
  `PROTOCOLO_PARAMETROS`, así que el informe los lista como desviación. El
  lado `.tokens` de cada resultado anota con qué pesos se entrenó, y uno
  entrenado con otros no se reusa.
- **La regla para elegir versión se escribió antes de entrenar la v2**
  (enmienda 1). Para ir al flujo no basta con superar a la línea base: el
  signo en el patrón de oro tiene que despegar del azar y de «siempre
  activa». Con *E. coli* ya se había visto que un clasificador constante
  aprueba contra el azar.
- **Resultado: ninguna versión la cumple.**
  - la v1 da 46.3 % de signo, sesgada a la represión;
  - la v2 da 71.4 %, igual que «siempre activa»;
  - el modelo de *E. coli*, 87.6 %, sigue en el flujo.

  Las dos versiones le ganan a memorizar el par, así que el problema no es
  que el modelo no lea: el signo no se aprende de esta supervisión distante.

## El tablero corre el flujo: qué se toma de la petición y qué no

`POST /api/trabajo {tipo: "flujo"}` acepta **qué** correr: corrida, pasos,
forzar, límite y reusar. **Dónde y con qué** sale del arranque del servidor y
nunca del cuerpo: la carpeta de salida, la raíz de datos, el modelo y los
intérpretes. Un `python_bert` que llegara por HTTP sería ejecutar el programa
que diga quien mande la petición, y una `salida` sería permiso de escritura en
cualquier parte del disco. Es la misma regla que ya tenía `salida` para el
fulltext.

Tres detalles de HTTP que no son obvios, y el defecto que evita cada uno:
- **Cancelar pide un cuerpo JSON aunque sea `{}`.** Un POST sin cuerpo es
  una petición simple: cualquier página abierta en el mismo navegador la
  puede mandar a 127.0.0.1 sin preflight y cortar la corrida de otro. Con
  cuerpo, la verificación de `Content-Type` la detiene.
- **Las salidas se mandan por bloques y con el largo exacto.** El CSV de
  candidatas pesa decenas de MB, y leerlo entero en memoria por cada descarga
  podía tumbar el tablero. Además, `flujo.log` crece mientras el flujo corre: mandar «hasta el
  fin del archivo» después de anunciar un `Content-Length` deja bytes de más,
  que con HTTP/1.1 se leen como el principio de la siguiente respuesta.
- **El fin de un trabajo se detecta por su identidad (inicio y fin), no por
  la transición activo → inactivo.** Un flujo todo «ya hecho» termina antes
  del primer sondeo, y la página nunca veía la transición.
- **El `Host` tiene que nombrar a `127.0.0.1` o `localhost`, con cualquier
  puerto.** Escuchar solo en 127.0.0.1 no basta contra el DNS rebinding: una
  página hostil hace que su dominio resuelva a 127.0.0.1, queda en el mismo
  origen que el tablero y manda JSON sin preflight. Lo que la delata es que el
  navegador sigue poniendo su dominio en `Host`. El puerto no protege nada y
  la primera versión, que lo exigía, rompía el túnel SSH a otro puerto local
  (`ssh -L 8766:127.0.0.1:8765`).

## CollecTF es una referencia de evaluación: no entra a la base de conocimiento ni a `es_tf`

Decidido por el autor el 20-oct-2026 en el Documento de Tesis v1; se confirma
con el asesor el viernes 23-oct.

`etapa2/collectf_pao1.tsv` reúne sitios de unión de factores de transcripción
de *P. aeruginosa* validados experimentalmente: es una red regulatoria curada.
Si el agente de la plata la consultara como herramienta, confirmaría contra la
respuesta, y la plata y su evaluación saldrían sesgadas a la vez. Es el mismo
motivo por el que la base curada del laboratorio no entra al bronce ni a la
base de conocimiento.

- **Su uso es otro: la segunda referencia de evaluación**, independiente del
  laboratorio. El recall se reporta contra la base curada y contra CollecTF
  por separado. Ya se usó así: 126 de 333 pares (37.8 %, `bitacora.md:2094`;
  la línea 2326 dice 38.8 %, una errata).
- **Tampoco cuenta como evidencia de que un gen es TF.**
  `construir_diccionario.py:1021-1022` suma `collectf` a `fuente_tf`, y hoy
  lo hace en 29 de las 572 filas con `es_tf=true` de `genes_pao1.tsv`.
  Medido el 21-oct: las 29 traen además otra fuente, así que sacar CollecTF no
  cambia ninguna marca. Como `etapa2` está congelada, la guarda es una prueba
  del bronce que falla si una marca llega a depender solo de CollecTF.
- **Por qué no se protege el nombre en `test_contaminacion`:**
  `construir_diccionario.py` está en `DEL_PIPELINE`, donde la regla no admite
  lista blanca, y lo nombra para la marca de arriba. Cuando exista el paquete
  de la base de conocimiento, ese paquete sí entra a la guarda con CollecTF
  protegido.

## La base de conocimiento no usa base vectorial: los hechos se consultan por igualdad

Decidido por el autor el 20-oct-2026 en el Documento de Tesis v1. La base de
conocimiento del agente todavía no existe; esto fija cómo se construirá.

- **Los hechos (locus, TF, operón, GO) van en tablas `kb_*` de SQLite**, cada
  una con su fuente, fecha y huella, y se consultan por igualdad. Un hecho
  exige una respuesta exacta y determinista; una búsqueda vectorial devuelve
  lo «parecido» y puede contestar con el gen equivocado. Las tablas además son
  más rápidas, no cuestan y se reproducen por huella. Su DDL se propone y se
  confirma antes de aplicarse, como cualquier tabla nueva.
- **Los vectores sí sirven para proponer, nunca para decidir.** Un índice
  local (numpy o FAISS plano; unas 273 mil oraciones, menos de 1 GB) puede dar
  ejemplos parecidos para *few-shot* (solo de un conjunto de desarrollo, nunca
  de la muestra de 50, del conjunto ciego ni de PMIDs de test), vincular frases
  con términos GO, sugerir un locus para un nombre fuera del diccionario
  (marcado como propuesto, nunca como normalizado) o encontrar oraciones casi
  idénticas entre artículos.
- **S3 Vectors u OpenSearch** solo si la capa de agentes vive en la nube y
  hace falta búsqueda híbrida; es trabajo de la tesis, no del servicio social.

## El LLM sobre la oración es trabajo de tesis: el servicio social cierra con la capa determinista

Decidido el 22-oct-2026, tras una revisión externa de la arquitectura
multiagente del Documento de Tesis v1. Se presenta al asesor el viernes 23-oct
(`reunion-asesor-23oct.md`, decisión j).

**La contradicción que había.** La bitácora, en «Lo que no vamos a hacer, y por
qué» (entrada del bloque 1, sin fecha propia), descarta «automatizar el pipeline con Strands o con
varios LLMs», porque el pipeline es determinista a propósito. La tesis v1
propuso justo eso: un multiagente con Strands, AgentCore y un juez.

El cambio venía de un dato. En las 93 oraciones evaluables de la trampa del
signo, un LLM sin ajuste acierta el 91.4 % y el BioBERT de *E. coli* el 36.6 %;
en el fenotipo del mutante, 91.7 % contra 8.3 % (bitácora, «Línea base: un LLM
sin ajuste fino contra el BioBERT ajustado»). Pero
ese dato tiene tres límites, que la misma bitácora escribe:
- es un solo subsistema;
- es un conjunto difícil a propósito;
- el LLM es de la familia del sistema que preparó el conjunto.

Además, los modelos abiertos del plan no son ese LLM.

**Lo que se decidió:**
- **El servicio social cierra con la capa determinista:** el pipeline, la red
  versionada, el recall contra la base curada y la precisión en una muestra
  ciega de 200 con un anotador, registrando su tiempo por bloque. La regla de
  la bitácora sigue valiendo para él sin excepciones.
- **El LLM entra a la tesis, detrás de una puerta**
  (`plan-tesis-plata-llm.md`). Sobre la oración, y en otro proceso, como
  `etapa2/clasificar.py`. El bronce y las herramientas siguen deterministas.
- **La reproducibilidad del LLM es por caché, no por volver a llamarlo.**
  Cada veredicto se guarda con la huella de todo lo que lo decide (modelo,
  pesos, cuantización, motor, prompt y decodificación), como la caché del
  BioBERT en `puente.py`. Regenerar puede variar; reconstruir la red desde lo
  guardado, no.
- **La puerta no cabe en el servicio social, y está medido.**
  - De 200 oraciones al azar salen unos 35-65 ítems con signo, y contra
    «siempre activa» la potencia es de 0.24 a 0.54.
  - Hacen falta 150-250 ítems con signo para una ventaja de 10 puntos, así
    que la puerta pide un estrato aparte.
  - El cálculo está en `plan-tesis-plata-llm.md`.
- **Cada agente gana su lugar:** entra solo si quitarlo empeora una métrica
  medida. AgentCore y Gateway son despliegue: van a trabajo futuro.
- **El juez es local y de otra familia que el extractor y que Claude**, y esa
  regla manda sobre «el juez por omisión es Claude».

**Lo que queda opcional antes del 4-nov:** el LLM sobre las mismas 200, como
comparación exploratoria, sin puerta y declarado así en el informe.

## La tanda 1 es de desarrollo y la tanda 2 de prueba, sin artículos compartidos

Decidido el 23-oct-2026, después de ver las cifras de la tanda 1 (rúbrica,
enmienda 2).

- **La tanda 1 ya se vio.** Una regla nueva ajustada mirándola (el signo como
  parámetro, una regla de dirección, el prompt de Ouroboros) inflaría su cifra
  si se reportara con la misma tanda.
- **La tanda 2 sale de la misma población que la tanda 1 y que el 44 %:** las
  oraciones con regulador y blanco de la corrida 4, con las mismas reservas.
- **Se excluyen los PMIDs de la tanda 1, y no solo sus oraciones.** Si un
  artículo cae en las dos, la tanda 2 deja de ser una prueba independiente:
  su redacción y sus pares ya se vieron. Es la misma regla de partición por
  PMID del entrenamiento con la base curada.
- **También se excluyen sus códigos de `id_item`.** Con códigos de 4 dígitos,
  dos sorteos de 200 comparten unos 4 en promedio, y la probabilidad de que
  no compartan ninguno es de 1 %. Un mismo código en las dos tandas confunde
  cualquier análisis conjunto.
- **La semilla de la tanda 2, 20261023, se escribió en la bitácora antes de
  sortear.**
- **Los PMIDs del entrenamiento de las curadas v1 y v2 no se excluyen al
  sortear,** porque esa lista es confidencial y vive en el servidor. Salen en
  el análisis: `precision-ciega --particion`.

## Ouroboros v0: un CLI aparte, con las herramientas apagadas y sin think en la corrida principal

Decidido por el usuario el 23-oct-2026. Concilia «El LLM sobre la oración es
trabajo de tesis» (22-oct), que dejaba abierta una comparación exploratoria,
sin puerta y declarada así.

- **Fuera del flujo.** `grn_ouroboros` es un CLI que corre en el servidor, donde
  vive Ollama. Un paso del flujo en la laptop se saltaría siempre. Nada de la
  red ni de la entrega depende de él.
- **Su salida lleva exactamente las columnas de la hoja del experto.** Así el
  acuerdo se calcula con el mismo lector que valida la rúbrica
  (`precision_ciega.leer_anotacion`). Lo demás (fragmento, motivo, tiempos,
  huellas) va en archivos aparte.
- **Herramientas.**
  - Las cinco (`buscar_locus`, `es_tf`, `operon_de`, `funcion_anotada` y
    `contexto`) se implementan y se prueban, pero van apagadas por omisión.
  - El motivo: el experto juzga solo la oración (rúbrica §2). `es_tf` empuja
    justo a la heurística que el §3.4 prohíbe y que explica las inversiones.
    Un juez que sabe más que el experto deja de medir lo mismo.
  - La corrida con herramientas es secundaria y pre-registrada. Contesta si el
    conocimiento cambia el veredicto o reproduce los errores del bronce.
  - Con límite de tiempo: si hay atraso, solo `buscar_locus`, y las otras
    cuatro pasan a la tesis.
- **Decodificación.**
  - La principal va sin think, con T = 0 y semilla fija. La secundaria va con
    think, T = 0.6, top_p 0.95 y top_k 20, lo que recomienda Qwen: con T = 0 y
    think se degrada y entra en repeticiones.
  - La reproducibilidad no depende de T = 0. La da la caché con la huella de
    todas las entradas.
  - Las dos llevan un tope de tokens de salida (`num_predict`).
  - Una respuesta truncada o sin JSON válido es abstención, y la abstención
    cuenta como error. Se fija antes de correr.
  - El `num_ctx` de la corrida con think es 8 192. Si no cabe en los 8 GB
    compartidos, se comprime la caché con `OLLAMA_KV_CACHE_TYPE=q8_0` antes
    de recortarlo; lo mide Hermes en la calibración. Si sobra tiempo, la
    corrida con think se repite con tres semillas.
- **El juez nunca es Claude.**
  - Sin modelo explícito, Strands y Strands Evals caen en Bedrock con Claude
    sin avisar. Una prueba falla si se construye un `BedrockModel`.
  - No se usa `OutputEvaluator`. Los evaluadores son propios y deterministas.
- **Dependencias.** Strands (`strands-agents[ollama]==1.62.0`),
  `strands-agents-evals==1.7.0`, el cliente `ollama==0.6.3` y pydantic son una
  excepción explícita del usuario. Viven solo en `grn_ouroboros`, en
  `.venv-ouroboros` (Python ≥ 3.10) en el servidor. El núcleo no los importa,
  y las pruebas del repositorio pasan sin ellos.
- **El prompt** se ajusta solo con los ítems de calibración, que son
  sintéticos y escritos con Claude, y con la tanda 1 si hace falta. Se congela
  con un commit antes de correr sobre la tanda 2.

## El signo de la red como parámetro: dos alcances del voto léxico y el voto por artículo

Decidido por omisión el 23-oct-2026; se mide solo en la tanda 2.

- **Por omisión, apagado:** la red oficial sigue siendo la de `red.py`, byte a
  byte.
- **El voto léxico tiene dos alcances, y los dos son valor del parámetro:**
  - **Por evidencia, el principal.** Toda evidencia cuya predicción sea
    `regulates` vota con el signo del control léxico. Es la lectura literal
    de «cuando la predicción sea regulates».
  - **Por arista, el secundario.** Solo vota en las aristas que `red.py` dejó
    `regulates`, para no tocar las que ya tienen signo de BioBERT, que
    aciertan 42/48 en la tanda 1.
- **«Mixta» es una arista con votos + y −.** Es la que el voto por artículo
  decide: cada artículo vota con la mayoría de sus oraciones. El «mixto» del
  contraste es otra cosa: un par cuyas aristas, con distintas formas de
  nombre, no dicen lo mismo.
- **Cómo se reporta:** con abstención como error y frente a «siempre +» sobre
  la misma base. Cada regla también sola.
