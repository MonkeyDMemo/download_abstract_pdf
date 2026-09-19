# Contexto: Base de operones de P. aeruginosa PAO1

## Proyecto

Pipeline de inferencia de una red de regulacion genica (GRN) para
*Pseudomonas aeruginosa*, dentro del paquete `grn_etl/`. El grafo final
tiene genes y factores de transcripcion como nodos, y relaciones
regulatorias como aristas.

Este trabajo agrega un componente nuevo: una base de datos que contiene
solamente operones.

## Encargo del asesor (Acordado)

- Extraer los operones de PAO1 de cuatro fuentes indicadas por el
  Dr. Edgardo Galan-Vasquez.
- Curarlos para obtener una base de operones unicamente.
- Todo el proceso debe ser automatizado y ejecutable por consola/codigo.

Fuentes:

1. Pseudomonas Genome Database: https://www.pseudomonas.com/feature/show/?id=109783&view=operons
2. ODB v4: https://operondb.jp/known?species=208964&p=2
3. BioCyc / PseudoCyc: https://biocyc.org/tu?orgid=PAER208964&id=TU1FZ6-912
4. CDBProm (IIMAS): https://aw.iimas.unam.mx/cdbprom/search2.php

Identificadores del organismo: taxid `208964`, BioCyc orgid `PAER208964`,
genoma de referencia NC_002516.2, locus tags `PA0001`-`PA5570`.

## Caracteristicas de cada fuente

| Fuente | Contenido | Evidencia | Via automatizable |
|---|---|---|---|
| ODB v4 | Operones conocidos, paginados | Literatura, con referencia | Paginacion HTTP de `/known?species=208964&p=N`; el sitio tambien ofrece descarga masiva |
| BioCyc | Unidades transcripcionales (TU) | Curada + prediccion Pathway Tools, con evidence codes | API oficial (`websvc.biocyc.org`, consultas BioVelo), requiere cuenta |
| Pseudomonas.com | Operones por gen | Prediccion DOOR | Archivo bulk por cepa (`pseudomonas.com/strain/download`) |
| CDBProm | Promotores predichos (XGBoost) | Prediccion | Volcado solicitado al asesor |

Nota metodologica: Pseudomonas.com (historicamente) y BioCyc usan
predicciones de Pathway Tools; se tratan como evidencia no independiente.

## Restricciones

- Respetar robots.txt y terminos de uso. BioCyc y CDBProm prohiben acceso
  automatizado a sus paginas web; usar la API oficial de BioCyc y el
  volcado de CDBProm. Pseudomonas.com tiene deteccion de bots: descargar
  el archivo bulk, sin raspar paginas por gen ni evadir la deteccion.
- Credenciales solo por variables de entorno (`BIOCYC_EMAIL`,
  `BIOCYC_PASSWORD`). Nunca en codigo, logs ni commits.
- Pausa minima de 2 s entre peticiones; User-Agent identificado.
- Ejecuciones idempotentes: re-correr no debe duplicar registros.
- La base curada del asesor es solo para validacion (Paso 2/3). No se usa
  en la extraccion ni en la curacion de operones.
- Seguir el patron de capas existente en `grn_etl/` (`db.py`, `etl.py`,
  `cli.py`) y el esquema SQLite actual.

## Estado actual

Existe un prototipo standalone: `operones_extraccion.py`.

- `odb`: descarga paginas HTML crudas. Sin parser. Posible render por
  JavaScript: si el HTML llega sin datos, buscar el endpoint JSON.
- `biocyc`: login, dos consultas BioVelo (TUs y genes), parser a
  `tus.tsv` (tu_id, locus_tag, evidencias). Endpoint de login y nombres
  de clase sin verificar; el acceso a PAER208964 puede requerir
  suscripcion.
- `pgd`, `cdbprom`: descarga generica desde URL en variable de entorno
  (`PGD_OPERONES_URL`, `CDBPROM_URL`). Sin parser.

Salida cruda en `datos/bronze/operones/<fuente>/<fecha>/`.

## Tareas

1. Verificar cada fuente con una corrida real y reportar lo que devuelve
   (formato, volumen, errores de acceso).
2. Localizar la URL del archivo de operones de PAO1 en Pseudomonas.com.
3. Escribir los parsers de ODB y PGD a partir del formato real.
4. Integrar el prototipo como `grn_etl/operones/` con un loader por
   fuente y comandos en `cli.py`: `operones extraer|curar|exportar`.
5. Implementar la capa bronze y la capa silver (ver abajo).
6. Pruebas con fixtures pequenos de cada fuente.

## Propuesta de modelo y curacion (Nuestro, pendiente de validar con el asesor)

Tabla `operones_bronze`:

```
fuente, id_fuente, genes_raw, locus_tags, cadena,
tipo_evidencia, pmid, fecha_descarga, registro_raw
```

Reglas de curacion hacia `operones_silver`:

1. Normalizar todo a locus_tag PAO1, usando la anotacion de Pseudomonas.com
   como diccionario nombre-locus_tag.
2. Validar contra el GFF de NC_002516.2: genes adyacentes, misma cadena,
   orden consecutivo. Los que fallen van a lista de revision.
3. Deduplicar: mismo conjunto ordenado de genes = un operon. Subconjuntos
   y solapamientos se conservan como TUs alternativas, marcadas.
4. Nivel de evidencia: conocido con PMID > curado BioCyc > predicho.
   Registrar numero de fuentes que respaldan cada operon.
5. Marcar soporte de promotor CDBProm aguas arriba del primer gen.
6. Exportar CSV de conflictos para revision manual con el asesor.

## Preguntas abiertas

- Si la base curada del asesor ya incorpora operones de estas fuentes,
  hay riesgo de fuga de informacion hacia la validacion.
- Formato y alcance del volcado de CDBProm.
- Disponibilidad de acceso a PAER208964 en BioCyc con la cuenta actual.
