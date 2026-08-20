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
`structure.md`. No es una suposición: se verificó contra los 2263 documentos
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
