# -*- coding: utf-8 -*-
"""El unico modulo del paquete que escribe SQL. Administra sus cuatro tablas.

Las cuatro llevan prefijo `operones_` porque comparten archivo SQLite con el
paso 0 y el paso 1. Cada paquete crea y administra unicamente las suyas.

LAS DOS CAPAS, Y POR QUE LA CRUDA SE GUARDA ENTERA
==================================================
`operones_bronze` es lo que la fuente dijo, ya partido en campos pero sin
interpretar: sin normalizar nombres, sin validar contra el genoma y sin
deduplicar. `operones_silver` es el resultado de esas tres cosas.

Separarlas permite rehacer la curacion sin volver a descargar --que es lo caro
y lo que molesta a las fuentes-- y permite comparar dos curaciones sobre
exactamente los mismos bytes. `registro_raw` conserva ademas la fila original
tal cual, para poder volver a parsear cuando se descubra que el parser perdia
un campo.

DONDE VIVE LA IDEMPOTENCIA
==========================
El encargo la exige: re-correr no debe duplicar registros. Cada tabla declara
su clave natural **antes** de poder ser idempotente, porque sin indice donde
apoyarse el `ON CONFLICT` falla.

| tabla | clave natural | al repetir |
|---|---|---|
| `operones_descargas` | `(fuente, sha256)` | no hace nada: son los mismos bytes |
| `operones_bronze` | `(fuente, id_fuente, descarga_id)` | no hace nada: el bronce no se reescribe |
| `operones_silver` | `clave_genes` | actualiza la evidencia agregada |
| `operones_silver_fuente` | `(silver_id, fuente, id_fuente)` | no hace nada |

**El bronce solo inserta, nunca actualiza.** Una descarga con la misma huella
es literalmente la misma respuesta, asi que re-correr no crea nada; y si la
fuente corrigio un operon, sus nuevos bytes son otra descarga y la fila nueva
convive con la anterior. Reescribir habria perdido que la fuente cambio de
opinion y cuando, que es de lo poco que una capa cruda puede aportar y nadie
mas guarda.

Quedarse con la version vigente es trabajo de la capa curada: `bronze_vigente()`
devuelve, de cada `(fuente, id_fuente)`, la fila de la descarga mas reciente.

Solo biblioteca estandar.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from grn_etl import db as _paso0

ErrorBase = sqlite3.Error

ESQUEMA_OPERONES = """
-- Procedencia de cada descarga cruda. Es el manifiesto del constructor del
-- diccionario llevado a la base: sin url, bytes y huella, un archivo en disco
-- es un archivo que alguien dejo ahi.
CREATE TABLE IF NOT EXISTS operones_descargas (
    id            INTEGER PRIMARY KEY,
    fuente        TEXT NOT NULL,
    url           TEXT NOT NULL,
    ruta          TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    descargado_en TEXT NOT NULL,
    nota          TEXT,
    UNIQUE (fuente, sha256)
);

-- Lo que la fuente dijo en cada descarga, partido en campos y sin interpretar.
--
-- La clave incluye `descarga_id` y la insercion es DO NOTHING, no DO UPDATE:
-- el bronce conserva lo que cada fuente dijo EN CADA FECHA. Con la clave sin
-- la descarga, una fuente que corrigiera un operon entre dos bajadas
-- sobrescribia lo anterior y no quedaba forma de saber que habia cambiado ni
-- cuando. Quedarse con la version vigente es trabajo de la capa curada, que
-- para eso mira `bronze_vigente()`.
--
-- `descarga_id` es NOT NULL y eso no es decoracion: en SQLite los NULL son
-- distintos entre si dentro de un UNIQUE, asi que una sola fila sin descarga
-- abriria la puerta a duplicados ilimitados de esa misma fila. Ademas, una
-- fila de bronce sin la descarga de la que salio no tiene procedencia, que es
-- justo lo que esta capa existe para guardar.
CREATE TABLE IF NOT EXISTS operones_bronze (
    id             INTEGER PRIMARY KEY,
    fuente         TEXT NOT NULL,
    id_fuente      TEXT NOT NULL,
    genes_raw      TEXT,
    locus_tags     TEXT,
    cadena         TEXT,
    tipo_evidencia TEXT,
    pmid           TEXT,
    descarga_id    INTEGER NOT NULL REFERENCES operones_descargas(id),
    fecha_descarga TEXT NOT NULL,
    registro_raw   TEXT,
    UNIQUE (fuente, id_fuente, descarga_id)
);

-- El operon curado. `clave_genes` es el conjunto ORDENADO de locus tags
-- separados por '|': dos fuentes que nombran los mismos genes en el mismo
-- orden describen el mismo operon, se llamen como se llamen.
CREATE TABLE IF NOT EXISTS operones_silver (
    id            INTEGER PRIMARY KEY,
    clave_genes   TEXT NOT NULL,
    nombre        TEXT,
    locus_tags    TEXT NOT NULL,
    n_genes       INTEGER NOT NULL,
    cadena        TEXT,
    nivel_evidencia TEXT NOT NULL,
    n_fuentes     INTEGER NOT NULL DEFAULT 0,
    pmids         TEXT,
    adyacente     INTEGER NOT NULL DEFAULT 0,
    es_alternativa INTEGER NOT NULL DEFAULT 0,
    promotor_cdbprom INTEGER NOT NULL DEFAULT 0,
    revisar       TEXT,
    curado_en     TEXT NOT NULL,
    UNIQUE (clave_genes)
);

-- Que fuentes respaldan cada operon curado. N a N, y es lo que permite decir
-- "tres fuentes independientes" sin recontar la misma prediccion dos veces.
CREATE TABLE IF NOT EXISTS operones_silver_fuente (
    silver_id  INTEGER NOT NULL REFERENCES operones_silver(id),
    fuente     TEXT NOT NULL,
    id_fuente  TEXT NOT NULL,
    PRIMARY KEY (silver_id, fuente, id_fuente)
);

CREATE INDEX IF NOT EXISTS ix_opbronze_fuente ON operones_bronze(fuente);
CREATE INDEX IF NOT EXISTS ix_opsilver_nivel  ON operones_silver(nivel_evidencia);
"""


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def huella(cuerpo):
    return hashlib.sha256(cuerpo).hexdigest()


def conectar(ruta="datos/grn.db"):
    """Abre la base con el esquema del paso 0 y el de operones encima.

    Se apoya en `grn_etl.db.conectar()` en vez de repetir sus PRAGMAs, igual
    que hace el bronce. La dependencia va en el sentido correcto.
    """
    con = _paso0.conectar(ruta)
    con.executescript(ESQUEMA_OPERONES)
    return con


# ------------------------------------------------------------------ descargas

def registrar_descarga(con, fuente, url, ruta, cuerpo, nota=None):
    """Anota una descarga cruda y devuelve su id.

    Idempotente por `(fuente, sha256)`: volver a bajar los mismos bytes no
    crea una fila nueva ni pisa la fecha en que se vieron por primera vez.
    Devuelve el id de la fila existente en ese caso.
    """
    sha = huella(cuerpo)
    con.execute(
        """INSERT INTO operones_descargas
             (fuente, url, ruta, bytes, sha256, descargado_en, nota)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(fuente, sha256) DO NOTHING""",
        (fuente, url, ruta, len(cuerpo), sha, ahora(), nota))
    con.commit()
    fila = con.execute(
        "SELECT id FROM operones_descargas WHERE fuente=? AND sha256=?",
        (fuente, sha)).fetchone()
    return fila["id"] if fila else None


def descargas_de(con, fuente=None):
    if fuente is None:
        return con.execute(
            "SELECT * FROM operones_descargas ORDER BY descargado_en DESC"
        ).fetchall()
    return con.execute(
        """SELECT * FROM operones_descargas WHERE fuente = ?
            ORDER BY descargado_en DESC""", (fuente,)).fetchall()


# --------------------------------------------------------------------- bronze

def guardar_bronze(con, filas):
    """Inserta filas de bronce. Devuelve (insertadas, ya_estaban).

    Solo inserta. Repetir la misma descarga no crea nada; una descarga nueva
    con datos corregidos crea filas nuevas que conviven con las anteriores.
    Lo que se conserva es la historia: que dijo cada fuente en cada fecha.

    Exige `descarga_id`: una fila de bronce sin la descarga de la que salio no
    tiene procedencia, y ademas rompe la unicidad, porque en SQLite los NULL
    son distintos entre si dentro de un UNIQUE.
    """
    insertadas = ya_estaban = 0
    for f in filas:
        if f.get("descarga_id") is None:
            raise ValueError(
                "fila de bronce sin descarga_id (%s/%s): una fila cruda sin "
                "su descarga no tiene procedencia"
                % (f.get("fuente"), f.get("id_fuente")))
        antes = con.total_changes
        con.execute(
            """INSERT INTO operones_bronze
                 (fuente, id_fuente, genes_raw, locus_tags, cadena,
                  tipo_evidencia, pmid, descarga_id, fecha_descarga,
                  registro_raw)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(fuente, id_fuente, descarga_id) DO NOTHING""",
            (f["fuente"], f["id_fuente"], f.get("genes_raw"),
             f.get("locus_tags"), f.get("cadena"), f.get("tipo_evidencia"),
             f.get("pmid"), f["descarga_id"],
             f.get("fecha_descarga") or ahora(),
             json.dumps(f.get("registro_raw"), ensure_ascii=False,
                        sort_keys=True) if f.get("registro_raw") else None))
        # Con DO NOTHING la cuenta si es fiable: o inserto una fila o ninguna.
        if con.total_changes > antes:
            insertadas += 1
        else:
            ya_estaban += 1
    con.commit()
    return insertadas, ya_estaban


def bronze_de(con, fuente=None):
    if fuente is None:
        return con.execute(
            "SELECT * FROM operones_bronze ORDER BY fuente, id_fuente"
        ).fetchall()
    return con.execute(
        "SELECT * FROM operones_bronze WHERE fuente=? ORDER BY id_fuente",
        (fuente,)).fetchall()


SQL_BRONZE_VIGENTE = """
SELECT b.* FROM operones_bronze b
  JOIN (SELECT fuente, id_fuente, MAX(descarga_id) AS ultima
          FROM operones_bronze GROUP BY fuente, id_fuente) u
    ON u.fuente = b.fuente AND u.id_fuente = b.id_fuente
   AND u.ultima = b.descarga_id
 ORDER BY b.fuente, b.id_fuente
"""


def bronze_vigente(con):
    """De cada `(fuente, id_fuente)`, la fila de la descarga mas reciente.

    Es la resta que el bronce ya no hace: como ahora conserva una fila por
    descarga, curar sobre la tabla entera metiria en la capa curada versiones
    viejas de un operon junto a la corregida, las dos con la misma pinta de
    buenas. `MAX(descarga_id)` y no la fecha porque el id es monotono y la
    fecha de dos descargas del mismo dia puede empatar.

    Sin ventana (`ROW_NUMBER`) a proposito: no todas las builds de SQLite que
    trae Python la tienen, y este subselect agrupado funciona en todas.
    """
    return con.execute(SQL_BRONZE_VIGENTE).fetchall()


def versiones_de(con, fuente, id_fuente):
    """Todas las versiones de un registro, de la mas nueva a la mas vieja.

    Es lo que el DO UPDATE hacia imposible: ver que cambio una fuente y
    cuando.
    """
    return con.execute(
        """SELECT * FROM operones_bronze
            WHERE fuente = ? AND id_fuente = ?
            ORDER BY descarga_id DESC""", (fuente, id_fuente)).fetchall()


def conteos_bronze(con):
    """{fuente: n}, para decir que trajo cada fuente sin volcar filas."""
    return dict((f["fuente"], f["n"]) for f in con.execute(
        "SELECT fuente, COUNT(*) n FROM operones_bronze GROUP BY fuente"))


# --------------------------------------------------------------------- silver

def guardar_silver(con, fila, respaldos):
    """Inserta o actualiza un operon curado con sus fuentes. Devuelve su id."""
    con.execute(
        """INSERT INTO operones_silver
             (clave_genes, nombre, locus_tags, n_genes, cadena,
              nivel_evidencia, n_fuentes, pmids, adyacente, es_alternativa,
              promotor_cdbprom, revisar, curado_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(clave_genes) DO UPDATE SET
             nombre=excluded.nombre,
             nivel_evidencia=excluded.nivel_evidencia,
             n_fuentes=excluded.n_fuentes,
             pmids=excluded.pmids,
             adyacente=excluded.adyacente,
             es_alternativa=excluded.es_alternativa,
             promotor_cdbprom=excluded.promotor_cdbprom,
             revisar=excluded.revisar,
             curado_en=excluded.curado_en""",
        (fila["clave_genes"], fila.get("nombre"), fila["locus_tags"],
         fila["n_genes"], fila.get("cadena"), fila["nivel_evidencia"],
         fila.get("n_fuentes", 0), fila.get("pmids"),
         1 if fila.get("adyacente") else 0,
         1 if fila.get("es_alternativa") else 0,
         1 if fila.get("promotor_cdbprom") else 0,
         fila.get("revisar"), ahora()))
    sid = con.execute("SELECT id FROM operones_silver WHERE clave_genes=?",
                      (fila["clave_genes"],)).fetchone()["id"]
    for fuente, id_fuente in respaldos:
        con.execute(
            """INSERT INTO operones_silver_fuente (silver_id, fuente, id_fuente)
               VALUES (?,?,?)
               ON CONFLICT(silver_id, fuente, id_fuente) DO NOTHING""",
            (sid, fuente, id_fuente))
    con.commit()
    return sid


def vaciar_silver(con):
    """Borra la capa curada para rehacerla. No toca bronce ni descargas.

    Curar es determinista sobre el bronce, asi que rehacer desde cero es mas
    barato y mas honesto que intentar un diff: una regla de curacion que cambia
    puede fusionar dos operones que antes estaban separados, y eso no se
    expresa como actualizacion fila a fila.
    """
    with con:
        con.execute("DELETE FROM operones_silver_fuente")
        con.execute("DELETE FROM operones_silver")


def silver_de(con, nivel=None):
    if nivel is None:
        return con.execute(
            "SELECT * FROM operones_silver ORDER BY n_fuentes DESC, clave_genes"
        ).fetchall()
    return con.execute(
        """SELECT * FROM operones_silver WHERE nivel_evidencia=?
            ORDER BY n_fuentes DESC, clave_genes""", (nivel,)).fetchall()


def fuentes_de_silver(con):
    """{silver_id: [(fuente, id_fuente)]}, en una consulta."""
    salida = {}
    for f in con.execute(
            "SELECT silver_id, fuente, id_fuente FROM operones_silver_fuente"):
        salida.setdefault(f["silver_id"], []).append(
            (f["fuente"], f["id_fuente"]))
    return salida


def resumen_silver(con):
    """Los conteos de la capa curada, contados en la base y no en memoria."""
    def uno(sql, params=()):
        return con.execute(sql, params).fetchone()[0]
    return {
        "operones": uno("SELECT COUNT(*) FROM operones_silver"),
        "por_nivel": dict((f["nivel_evidencia"], f["n"]) for f in con.execute(
            """SELECT nivel_evidencia, COUNT(*) n FROM operones_silver
                GROUP BY nivel_evidencia""")),
        "con_dos_o_mas_fuentes": uno(
            "SELECT COUNT(*) FROM operones_silver WHERE n_fuentes >= 2"),
        "no_adyacentes": uno(
            "SELECT COUNT(*) FROM operones_silver WHERE adyacente = 0"),
        "alternativas": uno(
            "SELECT COUNT(*) FROM operones_silver WHERE es_alternativa = 1"),
        "para_revisar": uno(
            """SELECT COUNT(*) FROM operones_silver
                WHERE revisar IS NOT NULL AND revisar <> ''"""),
        "con_promotor": uno(
            "SELECT COUNT(*) FROM operones_silver WHERE promotor_cdbprom = 1"),
    }
