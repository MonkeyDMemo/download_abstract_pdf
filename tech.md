---
inclusion: always
---

# Stack tecnico y convenciones

## Restricciones duras

**Solo libreria estandar de Python 3.8+.** No agregar dependencias sin que se
pidan explicitamente. La razon es de despliegue: el codigo corre en maquinas
de laboratorio con Linux y Windows, sin permisos de administrador y a veces
sin salida a PyPI. `urllib.request`, `sqlite3`, `xml.etree.ElementTree`,
`csv`, `json` y `argparse` cubren todo lo que hace falta.

Si una tarea parece necesitar `requests`, `pandas`, `lxml` o `BeautifulSoup`,
resolverla con la libreria estandar y explicar la alternativa en un
comentario. No instalarla.

## Idioma y acentos

Todo el proyecto esta en espanol. Los acentos dependen de si el texto es para
un humano o es un identificador; no hay una lista cerrada de palabras.

**Texto que lee un humano: acentos correctos.** Etiquetas y mensajes del
tablero, salida de terminal del CLI, encabezados de CSV, titulos y esta
documentacion. Se escribe "Año", "Título", "búsqueda", "año mínimo",
"petición": la palabra bien escrita del espanol en cada caso.

**Identificadores: ASCII sin acentos, siempre.** Nombres de variables,
funciones, clases, columnas de SQL, claves del JSON de la API, atributos
`data-*` y valores de `id=` del HTML. `anio` sigue siendo `anio` como columna,
como clave de JSON y como id de elemento; lo que cambia es la etiqueta que se
pinta encima, que dice "Año". Cambiar el identificador rompe la base de 2263
documentos y el contrato de la API, que es exactamente lo que este proyecto
existe para no hacer.

La razon del corte: la ene con virgulilla y las vocales acentuadas existen en
cp1252, asi que imprimen bien en la consola de Windows. Lo que si truena ahi
es lo que cae fuera de Latin-1 (una sigma griega, por ejemplo), y por eso todo
archivo de datos se escribe con `encoding="utf-8"` explicito, nunca con la
codificacion por omision del sistema.

Lo demas:

- Nombres de variables, funciones y tablas en **espanol**: `consultas`,
  `documentos`, `descargar_fulltext`, `pmids_conocidos`.
- Los identificadores de dominio externo se quedan en su forma original:
  `pmid`, `pmcid`, `doi`, `abstract`, `mesh_terms`.
- Sin emojis en codigo, comentarios, salida de terminal ni tablero.

## Estilo

- Tono directo y concreto. Los comentarios explican **por que**, no **que**.
  Un comentario que parafrasea la linea siguiente sobra.
- Preferir lo simple. Una funcion de 30 lineas legible le gana a tres clases
  con herencia.
- Sin `print()` en las capas internas (`db.py`, `pubmed.py`, `etl.py`,
  `trabajos.py`): reportan por un callback `log` que reciben como parametro.
  Imprimen los puntos de entrada y nada mas: `cli.py`, y `servidor.py` para su
  banner de arranque y los tracebacks que no deben salir en la respuesta HTTP.
  Esto es lo que permitio montar el tablero encima sin tocar el ETL.
- Type hints opcionales; si se usan, que sean consistentes en el modulo.

## Manejo de errores

- Toda peticion de red lleva reintentos con retroceso exponencial y tope.
- Un HTTP 400 de NCBI significa query mal formada: fallar de inmediato con el
  cuerpo de la respuesta, no reintentar.
- Un 404 de Unpaywall significa DOI no registrado: es un resultado valido,
  devolver `None`, no lanzar excepcion.
- Los fallos de un articulo individual no abortan el lote. Se registran en la
  tabla `descargas` con estatus `error` y el lote sigue.
- Las excepciones de una ejecucion completa se guardan en `ejecuciones.error`
  antes de propagarse.

## Secretos

Los archivos de steering y el codigo son parte del repositorio. **Nunca**
escribir API keys, correos personales ni credenciales en ninguno de los dos.

- API key de NCBI: variable de entorno `NCBI_API_KEY`.
- Correo de contacto: variable de entorno `NCBI_EMAIL` o flag `--email`.
- El `.gitignore` debe cubrir `.env`, `datos/` y `*.db`.

## APIs externas

| Servicio | Uso | Limite |
|---|---|---|
| NCBI E-utilities | `esearch`, `efetch` de PubMed y PMC | 3 req/s sin key, 10 con key |
| PMC ID Converter | PMID a PMCID/DOI | hasta 200 IDs por peticion |
| PMC OA Service | localizar PDF del subset abierto | sin limite documentado |
| Unpaywall | localizar PDF abierto por DOI | 100k/dia, exige correo |

Las queries booleanas van por **POST**, nunca GET: las consultas del proyecto
rebasan los 700 caracteres y truenan el limite de longitud de URL.

## Pruebas

Las pruebas no tocan la red. Se inyecta un cliente falso que devuelve XML o
JSON fijo. La capa `pubmed.py` esta separada justamente para permitir esto.

La prueba que no puede faltar: correr la misma ingesta dos veces y verificar
que la segunda no hace ninguna llamada a `efetch`.
