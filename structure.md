---
inclusion: always
---

# Estructura del proyecto

```
cli.py                 el CLI; el unico que imprime
servidor.py            tablero HTTP local (127.0.0.1); hermano de cli.py
web/
  index.html           el tablero entero en un archivo: HTML, CSS y JS sin
                       dependencias ni CDN. Se sirve desde servidor.py
  cropped-cropped-LogoUNAM_IIMAS_Color.png
                       el escudo del encabezado; servidor.py lo sirve en
                       /logo.png. Es el segundo y ultimo archivo que sale
                       por HTTP: la lista blanca compara por igualdad
                       exacta, no por prefijo
  UI mockups request/  la referencia visual del tablero (sistema Nocturne).
                       NO se sirve ni se ejecuta: es un lienzo de diseno y
                       carga React e Inter desde CDN. Vive aqui porque la
                       herramienta de diseno espera esta disposicion de
                       carpetas; los tokens estan copiados a index.html
grn_etl/
  __init__.py
  db.py                esquema SQLite y todo el SQL
  pubmed.py            clientes de E-utilities, PMC, Unpaywall
  etl.py               orquestacion
  trabajos.py          gestor de trabajos en segundo plano, uno a la vez
pruebas/
  falsos.py            cliente falso y fabricas de XML/JSON fijos
  test_*.py            349 pruebas con unittest; ninguna toca la red
etapa2/                la etapa siguiente: el clasificador de relaciones. No
                       comparte codigo con el ETL ni depende de el; lo unico
                       que los liga es el corpus. Ver etapa2/README.md
  particionar.py       reparte el corpus de entrenamiento sin fuga entre
                       train, dev y test, y marca la particion como RECHAZADA
                       si queda alguna
  barrido.py           corre las 24 configuraciones del servidor, reanudable
  barrido_colab.ipynb  el cuaderno que lo corre en Colab
  barrido_resumen.csv  las 24 corridas ya cerradas; la 22 da el cara a cara
  el programa local de inferencia, en orden de ejecucion:
  construir_diccionario.py  arma el diccionario de PAO1 desde RefSeq, KEGG y
                       UniProt; se niega si detecta procedencia `oro`
  lexico.py            reconoce menciones de genes; respeta mayusculas
  texto.py             parte los documentos en oraciones
  extraer_pares.py     saca los pares candidatos (TF, blanco) del corpus
  clasificar.py        LA UNICA PIEZA QUE NECESITA torch. Corre el modelo
  procedencia.py       la huella de cada archivo, para que la evaluacion
                       se niegue si le mezclan pasos de dos corridas
  red.py               agrega las predicciones en aristas unicas
  evaluar_oro.py       contra las 190 relaciones canonicas
  evaluar_signo.py     contra las 93 oraciones de signo conocido
  genes_pao1.tsv       5 642 genes, 572 marcados como factor de transcripcion
  operones_pao1.tsv    3 030 operones derivados del genoma
  oro_pseudomonas.tsv  190 relaciones canonicas con su oracion del corpus
  auditoria_signo.tsv  198 oraciones de los represores de bombas RND
  test_*.py            494 pruebas; ninguna necesita torch ni red
docs/
  decisiones.md        las decisiones de diseno y por que se tomaron asi
  ficha-modelo-bert.md el modelo BERT del servidor del asesor: que es, en que
                       se entreno, y que se le encontro al medirlo
  traspaso-etapa-2.md  que produjo la etapa 1 y en que formato exacto
  bitacora-y-plan.md   que se hizo antes, que se hizo hoy y que sigue.
                       Empieza por aqui
  informe-seminario-1.md  el panorama: que se hizo, que se midio y que falta
  migracion-maquina.md que copiar y que correr para levantar esto en otra
                       maquina. Lo que destraba es clasificar.py, la unica
                       pieza que necesita torch
pa_regulacion.txt      la consulta booleana, en texto plano
datos/
  grn.db               la base
  fulltext/xml/        JATS crudo y texto plano derivado
  fulltext/pdf/        PDFs de acceso abierto
salidas/               exportaciones CSV y JSONL
```

`datos/` y `salidas/` no van al repositorio; el `.gitignore` los cubre junto
con `.env` y `*.key`.

## Regla de capas

Dos frentes de entrada sobre las mismas capas. La dependencia va en una sola
direccion, y `trabajos.py` es la capa de servicio entre el HTTP y el ETL:

```
cli.py       -------------------------\
                                       >-- etl.py --> db.py
servidor.py --> trabajos.py ----------/           --> pubmed.py
                     |
                     +--> db.py   (solo para abrir conexion y la hora)

web/index.html --HTTP--> servidor.py
```

Reglas que no se rompen:

- **Solo `db.py` escribe SQL.** Si otra capa necesita una consulta nueva, se
  agrega una funcion en `db.py`. Nunca un `con.execute()` en `etl.py`,
  `servidor.py`, `cli.py` ni `trabajos.py`. Ya no queda ninguna excepcion:
  la consulta de `--pendientes` vive en `db.pendientes_biblioteca()`.
- **`pubmed.py` no conoce la base.** Recibe parametros, devuelve
  diccionarios y bytes. No importa `db`. Esto la hace probable sin red.
- **`etl.py` no imprime.** Recibe un callable `log` y lo invoca. El default es
  una funcion vacia. El CLI le pasa `print`; el gestor le pasa su acumulador
  de lineas, que es lo que el tablero sondea.
- **`cli.py` no tiene logica de negocio.** Parsea argumentos, arma el cliente,
  llama a `etl` y formatea la salida.
- **`servidor.py` tampoco.** Valida lo que llega, llama a `db`, `etl` o
  `trabajos`, y formatea JSON. Toda la API pasa por `manejar(metodo, ruta,
  params, cuerpo, ctx) -> (codigo, objeto)`, que no abre sockets ni lee del
  disco: la clase de `http.server` solo la envuelve. Por eso las pruebas
  cubren la API completa sin levantar un puerto.
- **`trabajos.py` no importa `etl`.** Recibe el callable a correr, asi sirve
  igual para `ingestar()` que para `descargar_fulltext()`.

Esta separacion es lo que permitio montar el tablero sin tocar la logica del
ETL, y lo que permitiria montar FastAPI manana. Si una propuesta obliga a
cruzar estas fronteras, casi siempre hay una alternativa que no lo hace.

## Modelo de datos

Cinco tablas:

| tabla | rol |
|---|---|
| `consultas` | la query booleana con nombre |
| `ejecuciones` | bitacora de cada corrida: totales, nuevos, error |
| `documentos` | un articulo, unico por PMID |
| `consulta_documento` | que consulta trajo que documento (N a N) |
| `descargas` | estado de full text por PMID y tipo (`xml` / `pdf`) |

**La separacion entre `documentos` y `consulta_documento` es la decision de
diseno central.** Un articulo que aparece en cinco consultas se almacena una
vez y se liga cinco veces. Sin esa separacion, cada consulta nueva volveria a
descargar todo el solapamiento, que en este dominio es enorme: las queries de
*P. aeruginosa* comparten la mayor parte de sus resultados.

De ahi sale la idempotencia. El flujo de `ingestar()` es:

1. `esearch` trae la lista completa de PMIDs (sin descargar contenido).
2. Se resta contra `documentos` via `db.pmids_conocidos()`.
3. `efetch` solo de la diferencia.
4. Se vinculan **todos** los PMIDs a la consulta, no solo los nuevos.

El paso 4 importa: un articulo que ya estaba en la base por otra consulta
igual pertenece a esta. Se exceptuan los PMIDs que `efetch` no devolvio
(retirados o de tipo Book): no estan en `documentos`, y `db.vincular()` los
descarta para no violar la llave foranea.

## Convenciones de nombres

- Tablas y columnas en espanol, minusculas, plural para tablas.
- **Los identificadores no llevan acentos, nunca.** Columnas, claves del JSON
  de la API y valores de `id=` del HTML son ASCII: `anio`, no "año". El texto
  que lee un humano si los lleva, y correctos: la etiqueta del tablero dice
  "Año" sobre la columna `anio`, y el encabezado del CSV tambien. Cambiar un
  identificador rompe la base de 2263 documentos y el contrato de la API; ver
  la seccion de acentos en `tech.md`.
- Timestamps en ISO 8601 UTC como TEXT (`db.ahora()`). SQLite no tiene tipo
  fecha; guardar ISO permite ordenar y comparar como cadena.
- Las listas (autores, MeSH, keywords) se guardan como JSON en TEXT y se
  deserializan con `db.a_dict()`.
- Los archivos de full text se nombran `{pmid}_{pmcid}.xml` y `{pmid}.pdf`,
  para poder rastrear el origen desde el nombre.

## Idempotencia: donde vive

| operacion | mecanismo |
|---|---|
| alta de consulta | `SELECT` por nombre; si existe, actualiza |
| insercion de documento | `ON CONFLICT(pmid) DO NOTHING` |
| vinculo consulta-doc | `ON CONFLICT(consulta_id, pmid) DO NOTHING` |
| descarga de full text | `UNIQUE(pmid, tipo)` mas filtro en `pendientes_descarga()` |

`pendientes_descarga()` excluye por defecto los marcados `no_disponible`: no
tienen acceso abierto y reintentarlos solo gasta peticiones. Los que quedaron
en `error` si se reintentan, pero unicamente con `--reintentar` explicito.

## Orden de las operaciones

`run` (abstracts) siempre antes que `fulltext`. El full text opera sobre lo
que ya esta en `documentos`.

Dentro de `fulltext`, correr `--tipo xml` antes que `--tipo pdf`. El JATS de
PMC llega con secciones separadas, referencias aparte y pies de figura
identificados; un PDF re-parseado pierde subindices de genes y entrelaza
columnas. Para el clasificador posterior el XML es mejor insumo. El PDF es
para lectura humana, y su etapa es la lenta: sale a los sitios de las
editoriales, que responden 403 con frecuencia.

Desde el tablero el orden es el mismo; lo unico que cambia es quien lanza la
corrida. `trabajos.Gestor` admite **un trabajo a la vez por proceso**, asi que
un `run` y un `fulltext` no pueden solaparse ahi aunque dos personas los
pidan: el segundo recibe 409.
