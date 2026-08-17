# Suite de pruebas del ETL de PubMed

## Contexto

El proyecto tiene tres capas (`pubmed.py`, `db.py`, `etl.py`) que ya funcionan
y estan documentadas en los archivos de steering. Falta la suite de pruebas
automatizadas. Este documento define los requisitos que debe cumplir.

## Objetivo

Verificar la logica de negocio del ETL sin depender de red ni de servicios
externos. Las pruebas corren en CI y en maquinas de laboratorio sin
conectividad a NCBI.

---

## Requisitos funcionales

### REQ-1: Sin acceso a red

Las pruebas no realizan ninguna peticion HTTP. Se inyecta un cliente falso
(mock/stub) en lugar de `pubmed.Cliente`. El cliente falso devuelve respuestas
XML y JSON fijas, aprovechando que `pubmed.py` no importa ni conoce `db.py`.

**Criterio de aceptacion:** la suite completa pasa con la interfaz de red del
sistema operativo deshabilitada.

---

### REQ-2: Verificacion de idempotencia (prueba central)

Correr `etl.ingestar()` dos veces consecutivas con el mismo universo de PMIDs
y afirmar que la segunda ejecucion:

- No hace **ninguna** llamada a `efetch`.
- No inserta documentos nuevos en la tabla `documentos`.
- Si vincula los PMIDs a la consulta (el vinculo ya existe, `ON CONFLICT DO
  NOTHING` lo absorbe sin error).
- Devuelve `nuevos == 0` y `descargados == 0`.

**Criterio de aceptacion:** un contador o registro en el cliente falso muestra
cero invocaciones a `efetch.fcgi` durante la segunda corrida.

---

### REQ-3: Relacion N a N entre consultas y documentos

Un articulo que aparece en los resultados de dos consultas distintas:

- Se almacena una sola vez en `documentos` (un unico PMID).
- Se vincula a ambas consultas en `consulta_documento` (dos filas).
- La segunda ingesta no vuelve a llamar a `efetch` para ese PMID.

**Criterio de aceptacion:** despues de ingestar la segunda consulta, la tabla
`documentos` sigue con una fila para el PMID compartido, y
`consulta_documento` tiene dos filas (una por consulta) para ese PMID.

---

### REQ-4: Parseo de abstracts estructurados con Label

Dado un XML de `efetch` que contiene un `<AbstractText>` con atributo
`Label` (por ejemplo "BACKGROUND", "METHODS", "RESULTS", "CONCLUSIONS"),
`pubmed.parsear_articulos()` reconstruye el abstract concatenando las
secciones con el formato `LABEL: texto`.

Tambien verificar que si `Label="UNLABELLED"`, la etiqueta se omite y solo
queda el texto.

**Criterio de aceptacion:** el campo `abstract` del dict resultante contiene
cada seccion con su etiqueta separada por `: ` y las secciones unidas por
espacio.

---

### REQ-5: MedlineDate sin campo Year

Dado un XML de `efetch` donde `<PubDate>` no tiene `<Year>` pero si
`<MedlineDate>` (por ejemplo `"2019 Jan-Feb"` o `"2020-2021"`),
`pubmed.parsear_articulos()` extrae correctamente el primer token de cuatro
digitos como anio.

**Criterio de aceptacion:** el campo `anio` del dict resultante contiene el
string del anio correcto (e.g. `"2019"`, `"2020"`).

---

### REQ-6: `jats_a_texto` cuando PMC solo devuelve metadatos

Dado un XML de PMC que contiene `<article-meta>` con titulo y abstract pero
**sin** elemento `<body>` (articulo que no esta en el subset de acceso
abierto), `pubmed.jats_a_texto()` devuelve:

- Un texto no vacio (contiene al menos el titulo).
- `tiene_cuerpo = False`.

Esto es lo que `etl._bajar_xml()` usa para clasificar como `no_disponible`.

**Criterio de aceptacion:** la tupla devuelta es `(texto, False)` donde
`texto` incluye el titulo del articulo y la seccion de abstract si la hay.

---

## Requisitos no funcionales

### REQ-NF-1: Framework

Usar `unittest` de la libreria estandar. No agregar `pytest` ni ninguna
dependencia externa para pruebas.

### REQ-NF-2: Base de datos en memoria

Las pruebas usan SQLite `:memory:` para evitar efectos secundarios entre
corridas y no dejar archivos residuales.

### REQ-NF-3: Fixtures reutilizables

Los XML y JSON de respuesta fija se definen como constantes o funciones
helper dentro del modulo de pruebas (o en un modulo auxiliar `fixtures.py`).
No se descargan de la red en ningun momento.

### REQ-NF-4: Independencia entre pruebas

Cada `TestCase` crea su propia conexion a la base en memoria y su propio
cliente falso. El orden de ejecucion no importa.

### REQ-NF-5: Ejecucion rapida

La suite completa debe correr en menos de 2 segundos en hardware tipico de
laboratorio. No hay E/S de red ni de disco (salvo la base en memoria).

### REQ-NF-6: Compatibilidad con la estructura del proyecto

Las pruebas se colocan en un modulo que respete la estructura de paquete
existente. El modulo de pruebas importa `db`, `pubmed` y `etl` de la misma
forma que el codigo de produccion.

---

## Fuera de alcance

- Pruebas de integracion contra NCBI real.
- Pruebas del CLI (`cli.py` es solo parseo de argumentos y formateo).
- Pruebas de `descargar_fulltext` con escritura a disco (se pueden agregar
  despues con `tempfile`).
- Cobertura de codigo o badges de CI.
