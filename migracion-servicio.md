---
inclusion: auto
name: migracion-servicio
description: Guia para exponer el ETL como servicio HTTP, concurrencia, limitador de tasa compartido, migracion de SQLite a PostgreSQL y encolado de trabajos. Usar al trabajar en API, endpoints, workers, colas o cuando se discuta acceso concurrente de varios usuarios.
---

# Migracion a servicio

El ETL nacio como batch por CLI pero va a operarse como servicio compartido
del laboratorio. Las capas ya estan separadas para permitirlo. Un endpoint se
monta encima sin tocar la logica:

```python
@app.post("/consultas/{nombre}/ejecutar")
def ejecutar(nombre: str):
    con = db.conectar(RUTA_DB)
    return etl.ingestar(con, cliente, nombre, log=logger.info)
```

Tres cosas si necesitan cambio antes de exponerlo a varios usuarios. Estan en
orden de riesgo.

## 1. Limitador de tasa compartido

El control de tasa vive en la instancia de `pubmed.Cliente` (atributo
`_ultima`). Con varios workers concurrentes cada uno cree que respeta el
limite mientras el conjunto lo rebasa.

**NCBI bloquea por IP, no por usuario.** Un worker mal portado deja sin
servicio a todo el laboratorio, incluidos los que no estaban usando el
sistema. Por eso este es el primero de la lista pese a parecer el menos
urgente.

La solucion es un limitador con estado externo, tipicamente un token bucket en
Redis. Al implementarlo, mantener la interfaz de `Cliente` intacta: lo unico
que cambia es el cuerpo de `_esperar()`.

## 2. SQLite a PostgreSQL

SQLite tolera lecturas concurrentes pero serializa escrituras. Dos ingestas
simultaneas producen `database is locked`.

La migracion toca **solo `db.py`**. Las firmas de las funciones no cambian, y
ninguna otra capa hace SQL, asi que `etl.py` y `cli.py` no se enteran.

Puntos que si cambian en el SQL:

- `INSERT ... ON CONFLICT DO NOTHING` funciona igual en Postgres.
- `INTEGER PRIMARY KEY` autoincremental pasa a `SERIAL` o `IDENTITY`.
- Los timestamps ISO en TEXT pueden pasar a `TIMESTAMPTZ`.
- El limite de parametros por consulta cambia; revisar el troceado de 800 en
  `pmids_conocidos()`.

Mientras el uso sea de un solo escritor, SQLite basta. No migrar antes de
tiempo.

## 3. Encolado de trabajos

Una corrida sobre las consultas reales tarda varios minutos, mas de lo que
aguanta una peticion HTTP sincrona.

El endpoint debe encolar y devolver el `ejecucion_id` de inmediato. La tabla
`ejecuciones` ya funciona como estado del trabajo: tiene `estatus`
(`corriendo` / `ok` / `error`), `iniciada_en`, `terminada_en` y `error`. No
hace falta una tabla nueva de jobs.

Un endpoint `GET /ejecuciones/{id}` que lea esa fila cubre el sondeo del
cliente.

## Lo que no cambia

- La idempotencia sigue siendo responsabilidad de la base, no del servicio.
  Dos usuarios corriendo la misma consulta a la vez no duplican documentos
  porque las restricciones `ON CONFLICT` lo impiden.
- El correo de contacto de NCBI debe seguir siendo real e identificable. Si el
  servicio corre bajo una cuenta institucional, usar el correo del laboratorio,
  no el de un estudiante.
