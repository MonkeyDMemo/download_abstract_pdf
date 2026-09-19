# -*- coding: utf-8 -*-
"""El unico modulo del paquete que escribe SQL. Administra sus cinco tablas.

Las cinco llevan prefijo `operones_` porque comparten archivo SQLite con el
paso 0 y el paso 1. Cada paquete crea y administra unicamente las suyas.

EL MODELO, DE ARRIBA ABAJO
==========================
    operones_extracciones   una corrida de extraccion de UNA fuente
      -> operones_descargas   un archivo traido en esa corrida
           -> operones_bronze   un registro leido de ese archivo

`fuente` y `completa` viven **solo** en la extraccion, y eso no es normalizar
por gusto. Con `fuente` repetida en las tres tablas, nada impedia que una fila
de bronce colgara de una descarga de otra fuente: quedaba fuera de su propia
foto vigente y desaparecia del catalogo sin que nada lo dijera. Habia un
guardian en `guardar_bronze()` comprobandolo en tiempo de corrida; ahora el
modelo lo hace imposible, que es mejor que comprobarlo. Con `completa`
repetida por archivo, marcar una corrida como terminada eran N escrituras que
habia que acertar todas; ahora es una.

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
| `operones_descargas` | `(extraccion_id, sha256)` | no hace nada: ya esta en esta corrida |
| `operones_bronze` | `(id_fuente, descarga_id)` | no hace nada: el bronce no se reescribe |
| `operones_silver` | `clave_genes` | actualiza la evidencia agregada |
| `operones_silver_fuente` | `(silver_id, fuente, id_fuente)` | no hace nada |

**El bronce solo inserta, nunca actualiza.** Si la fuente corrigio un operon,
sus nuevos bytes llegan en otra extraccion y la fila nueva convive con la
anterior. Reescribir habria perdido que la fuente cambio de opinion y cuando,
que es de lo poco que una capa cruda puede aportar y nadie mas guarda.

Quedarse con la version vigente es trabajo de la capa curada, y el criterio es
**la ultima extraccion COMPLETA de cada fuente**. Una fuente que nunca termino
una extraccion queda FUERA de la curacion entera: con media foto no se puede
decir que se retiro ni que sigue, y curar sobre ella mezclaria media descarga
nueva con media vieja. `fuentes_sin_foto()` las lista para que el informe lo
diga en vez de que desaparezcan sin ruido.

Solo biblioteca estandar.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from grn_etl import db as _paso0

ErrorBase = sqlite3.Error

ESQUEMA_OPERONES = """
-- Una corrida de extraccion de una fuente. Aqui viven `fuente` y `completa`,
-- y en ningun otro sitio: una corrida es lo que se completa o no, y una
-- descarga pertenece a la fuente de su corrida por construccion.
CREATE TABLE IF NOT EXISTS operones_extracciones (
    id        INTEGER PRIMARY KEY,
    fuente    TEXT NOT NULL,
    inicio    TEXT NOT NULL,
    fin       TEXT,
    completa  INTEGER NOT NULL DEFAULT 0
);

-- Un archivo traido en una corrida, con su procedencia. Sin url, bytes y
-- huella, un archivo en disco es un archivo que alguien dejo ahi.
--
-- La clave es `(extraccion_id, url)`: **cada URL se registra una vez por
-- corrida**, y el `sha256` es un atributo, no parte de la identidad.
--
-- Identificar por contenido se tragaba URLs. Si dos peticiones distintas de
-- la misma corrida devuelven bytes identicos --en ODB pasa: una pagina fuera
-- de rango devuelve la plantilla vacia, o el servidor repite la ultima
-- valida-- la segunda caia por `DO NOTHING` y su URL desaparecia del
-- registro, con lo que no habia forma de saber que se habia pedido. Con la
-- clave por URL, los contenidos repetidos quedan **visibles** en vez de
-- absorbidos, y detectarlos es una consulta: `GROUP BY sha256 HAVING
-- COUNT(*) > 1`.
--
-- Entre corridas distintas la misma URL se registra otra vez a proposito:
-- cada extraccion es una foto y lo que importa de un archivo es en que foto
-- salio.
CREATE TABLE IF NOT EXISTS operones_descargas (
    id            INTEGER PRIMARY KEY,
    extraccion_id INTEGER NOT NULL REFERENCES operones_extracciones(id),
    url           TEXT NOT NULL,
    ruta          TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    descargado_en TEXT NOT NULL,
    nota          TEXT,
    UNIQUE (extraccion_id, url)
);

-- Lo que la fuente dijo en esa descarga, partido en campos y sin interpretar.
--
-- **No lleva columna `fuente`.** La fuente se deriva de la extraccion de su
-- descarga, y por eso no puede discrepar de ella. Una columna que puede
-- discrepar acaba discrepando.
--
-- `descarga_id` es NOT NULL y eso no es decoracion: en SQLite los NULL son
-- distintos entre si dentro de un UNIQUE, asi que una sola fila sin descarga
-- abriria la puerta a duplicados ilimitados de esa misma fila. Ademas, una
-- fila de bronce sin la descarga de la que salio no tiene procedencia, que es
-- justo lo que esta capa existe para guardar.
--
-- La fecha tampoco se repite: vive en `operones_descargas.descargado_en`.
CREATE TABLE IF NOT EXISTS operones_bronze (
    id             INTEGER PRIMARY KEY,
    id_fuente      TEXT NOT NULL,
    genes_raw      TEXT,
    locus_tags     TEXT,
    cadena         TEXT,
    tipo_evidencia TEXT,
    pmid           TEXT,
    descarga_id    INTEGER NOT NULL REFERENCES operones_descargas(id),
    registro_raw   TEXT,
    UNIQUE (id_fuente, descarga_id)
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
    -- Un operon de UN gen. BioCyc registra 3 774 unidades de transcripcion
    -- para ~5 600 genes, asi que muchas son monocistronicas: descartarlas
    -- tiraba la mayor parte de esa fuente. Se conservan marcadas, y filtrar
    -- es cosa de la exportacion, no de la curacion.
    monocistronico INTEGER NOT NULL DEFAULT 0,
    promotor_cdbprom INTEGER NOT NULL DEFAULT 0,
    revisar       TEXT,
    curado_en     TEXT NOT NULL,
    UNIQUE (clave_genes)
);

-- Que fuentes respaldan cada operon curado. N a N, y es lo que permite decir
-- "tres fuentes independientes" sin recontar la misma prediccion dos veces.
-- Es ademas donde se apoyaria una guarda de contaminacion por procedencia.
CREATE TABLE IF NOT EXISTS operones_silver_fuente (
    silver_id  INTEGER NOT NULL REFERENCES operones_silver(id),
    fuente     TEXT NOT NULL,
    id_fuente  TEXT NOT NULL,
    PRIMARY KEY (silver_id, fuente, id_fuente)
);

CREATE INDEX IF NOT EXISTS ix_opextr_fuente  ON operones_extracciones(fuente, completa);
CREATE INDEX IF NOT EXISTS ix_opdesc_extr    ON operones_descargas(extraccion_id);
CREATE INDEX IF NOT EXISTS ix_opbronze_desc  ON operones_bronze(descarga_id);
CREATE INDEX IF NOT EXISTS ix_opsilver_nivel ON operones_silver(nivel_evidencia);
"""


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def huella(cuerpo):
    return hashlib.sha256(cuerpo).hexdigest()


def _migrar(con):
    """Sustituye las tablas de la forma anterior si estan vacias.

    `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya existe, asi que sin
    esto una base creada con el esquema viejo se quedaria con el. Se borran
    **solo si estan vacias**: con datos dentro, migrar es una decision con
    perdidas y la toma una persona, no un import.
    """
    tablas = dict(
        (f["name"], f["sql"] or "") for f in con.execute(
            """SELECT name, sql FROM sqlite_master
                WHERE type='table' AND name LIKE 'operones_%'"""))
    if "operones_descargas" not in tablas:
        return

    # Se comprueba la forma ESPERADA, no las formas viejas conocidas. Mirar
    # solo si falta `extraccion_id` dejaba pasar la version intermedia, cuya
    # clave era `(extraccion_id, sha256)`: el `CREATE TABLE IF NOT EXISTS` no
    # la tocaba y el `ON CONFLICT(extraccion_id, url)` reventaba en la primera
    # descarga real. Enumerar defectos conocidos siempre deja fuera el
    # siguiente; comprobar lo que se espera, no.
    esperado = "UNIQUE (extraccion_id, url)"
    if esperado in tablas["operones_descargas"]:
        return

    # Aditiva y aparte del rehacer: `operones_silver` puede tener datos y
    # anadir una columna no los pierde. Las migraciones de este proyecto son
    # aditivas por contrato.
    if "operones_silver" in tablas and "monocistronico" not in tablas["operones_silver"]:
        with con:
            con.execute("ALTER TABLE operones_silver "
                        "ADD COLUMN monocistronico INTEGER NOT NULL DEFAULT 0")

    afectadas = ("operones_bronze", "operones_descargas",
                 "operones_extracciones")
    for t in afectadas:
        if t not in tablas:
            continue
        n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        if n:
            raise ErrorBase(
                "%s tiene %d filas con un esquema anterior. La migracion no "
                "se hace sola con datos dentro: exporta lo que valga, vacia "
                "las tablas operones_* y vuelve a extraer." % (t, n))
    with con:
        # En orden inverso a las llaves foraneas.
        for t in afectadas:
            con.execute("DROP TABLE IF EXISTS %s" % t)


def conectar(ruta="datos/grn.db"):
    """Abre la base con el esquema del paso 0 y el de operones encima.

    Se apoya en `grn_etl.db.conectar()` en vez de repetir sus PRAGMAs, igual
    que hace el bronce. La dependencia va en el sentido correcto.
    """
    con = _paso0.conectar(ruta)
    _migrar(con)
    con.executescript(ESQUEMA_OPERONES)
    return con


# --------------------------------------------------------------- extracciones

def abrir_extraccion(con, fuente):
    """Registra la corrida ANTES de descargar y devuelve su id.

    Antes y no despues, por la misma razon que en el paso 0: si el proceso
    muere a la mitad tiene que quedar constancia de que se intento. Queda con
    `completa = 0`, que es lo que mantiene su descarga fuera de la curacion
    hasta que alguien la cierre bien.
    """
    cur = con.execute(
        "INSERT INTO operones_extracciones (fuente, inicio) VALUES (?,?)",
        (fuente, ahora()))
    con.commit()
    return cur.lastrowid


def cerrar_extraccion(con, extraccion_id, completa=True):
    """Marca el fin de la corrida. `completa=True` SOLO si termino sin error.

    Una sola escritura por corrida: con el flag repetido en cada descarga,
    cerrar eran N escrituras que habia que acertar todas, y acertar N cosas
    siempre sale peor que acertar una.
    """
    con.execute(
        "UPDATE operones_extracciones SET fin = ?, completa = ? WHERE id = ?",
        (ahora(), 1 if completa else 0, extraccion_id))
    con.commit()


def extracciones_de(con, fuente=None, limite=50):
    sql = """SELECT e.*, COUNT(d.id) AS n_archivos
               FROM operones_extracciones e
               LEFT JOIN operones_descargas d ON d.extraccion_id = e.id"""
    params = []
    if fuente:
        sql += " WHERE e.fuente = ?"
        params.append(fuente)
    sql += " GROUP BY e.id ORDER BY e.id DESC LIMIT ?"
    params.append(limite)
    return con.execute(sql, params).fetchall()


# ------------------------------------------------------------------ descargas

def registrar_descarga(con, extraccion_id, url, ruta, cuerpo, nota=None):
    """Anota un archivo de esta corrida y devuelve su id.

    Idempotente por `(extraccion_id, url)`: reintentar la misma peticion
    dentro de la misma corrida no duplica, y **dos URLs distintas con el mismo
    contenido se registran las dos**. La fuente no se pasa ni se guarda: es la
    de la extraccion.
    """
    con.execute(
        """INSERT INTO operones_descargas
             (extraccion_id, url, ruta, bytes, sha256, descargado_en, nota)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(extraccion_id, url) DO NOTHING""",
        (extraccion_id, url, ruta, len(cuerpo), huella(cuerpo), ahora(), nota))
    con.commit()
    fila = con.execute(
        """SELECT id FROM operones_descargas
            WHERE extraccion_id = ? AND url = ?""",
        (extraccion_id, url)).fetchone()
    return fila["id"] if fila else None


def contenidos_repetidos(con, extraccion_id):
    """[(sha256, [urls])] de los archivos que llegaron identicos en la corrida.

    Antes esto era invisible: la clave por contenido descartaba la segunda URL
    y no quedaba rastro de que se habia pedido. Sirve para reconocer la
    plantilla vacia con la que ODB contesta a una pagina fuera de rango.
    """
    salida = {}
    for f in con.execute(
            """SELECT sha256, url FROM operones_descargas
                WHERE extraccion_id = ? ORDER BY id""", (extraccion_id,)):
        salida.setdefault(f["sha256"], []).append(f["url"])
    return [(s, u) for s, u in salida.items() if len(u) > 1]


SQL_DESCARGAS = """
SELECT d.*, e.fuente, e.completa, e.inicio AS extraccion_inicio
  FROM operones_descargas d
  JOIN operones_extracciones e ON e.id = d.extraccion_id
"""


def descargas_de(con, fuente=None):
    if fuente is None:
        return con.execute(
            SQL_DESCARGAS + " ORDER BY d.descargado_en DESC").fetchall()
    return con.execute(
        SQL_DESCARGAS + " WHERE e.fuente = ? ORDER BY d.descargado_en DESC",
        (fuente,)).fetchall()


# --------------------------------------------------------------------- bronze

def guardar_bronze(con, filas):
    """Inserta filas de bronce. Devuelve (insertadas, ya_estaban).

    Solo inserta. Repetir la misma descarga no crea nada; una extraccion nueva
    con datos corregidos crea filas nuevas que conviven con las anteriores.

    `fuente` **no se guarda**: se deriva de la extraccion de la descarga. Si
    la fila la trae, se comprueba que coincida y se descarta el valor. Es una
    comprobacion de cordura sobre quien llama, no una invariante de los datos:
    esa ya la garantiza el modelo.
    """
    insertadas = ya_estaban = 0
    for f in filas:
        if f.get("descarga_id") is None:
            raise ValueError(
                "fila de bronce sin descarga_id (%s): una fila cruda sin su "
                "descarga no tiene procedencia" % f.get("id_fuente"))
        fila_fuente = con.execute(
            """SELECT e.fuente FROM operones_descargas d
                 JOIN operones_extracciones e ON e.id = d.extraccion_id
                WHERE d.id = ?""", (f["descarga_id"],)).fetchone()
        if fila_fuente is None:
            raise ValueError("descarga_id %r no existe" % f["descarga_id"])
        if f.get("fuente") and f["fuente"] != fila_fuente["fuente"]:
            raise ValueError(
                "la fila %s dice ser de %r y su descarga es de %r"
                % (f.get("id_fuente"), f["fuente"], fila_fuente["fuente"]))

        antes = con.total_changes
        con.execute(
            """INSERT INTO operones_bronze
                 (id_fuente, genes_raw, locus_tags, cadena, tipo_evidencia,
                  pmid, descarga_id, registro_raw)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id_fuente, descarga_id) DO NOTHING""",
            (f["id_fuente"], f.get("genes_raw"), f.get("locus_tags"),
             f.get("cadena"), f.get("tipo_evidencia"), f.get("pmid"),
             f["descarga_id"],
             json.dumps(f.get("registro_raw"), ensure_ascii=False,
                        sort_keys=True) if f.get("registro_raw") else None))
        # Con DO NOTHING la cuenta si es fiable: o inserto una fila o ninguna.
        if con.total_changes > antes:
            insertadas += 1
        else:
            ya_estaban += 1
    con.commit()
    return insertadas, ya_estaban


SQL_BRONZE = """
SELECT b.*, e.fuente, d.descargado_en AS fecha_descarga,
       d.extraccion_id, e.completa
  FROM operones_bronze b
  JOIN operones_descargas d    ON d.id = b.descarga_id
  JOIN operones_extracciones e ON e.id = d.extraccion_id
"""


def bronze_de(con, fuente=None):
    if fuente is None:
        return con.execute(
            SQL_BRONZE + " ORDER BY e.fuente, b.id_fuente").fetchall()
    return con.execute(
        SQL_BRONZE + " WHERE e.fuente = ? ORDER BY b.id_fuente",
        (fuente,)).fetchall()


def versiones_de(con, fuente, id_fuente):
    """Todas las versiones de un registro, de la mas nueva a la mas vieja.

    Es lo que un `DO UPDATE` en el bronce haria imposible: ver que cambio una
    fuente y cuando.
    """
    return con.execute(
        SQL_BRONZE + """ WHERE e.fuente = ? AND b.id_fuente = ?
                          ORDER BY d.extraccion_id DESC""",
        (fuente, id_fuente)).fetchall()


# La ultima extraccion COMPLETA de cada fuente. Una incompleta no cuenta: es
# media foto, y media foto no dice que se retiro ni que sigue.
SQL_ULTIMA_COMPLETA = """
SELECT fuente, MAX(id) AS extraccion_id
  FROM operones_extracciones WHERE completa = 1 GROUP BY fuente
"""

SQL_BRONZE_VIGENTE = SQL_BRONZE + """
  JOIN (%s) u ON u.fuente = e.fuente AND u.extraccion_id = e.id
 ORDER BY e.fuente, b.id_fuente
""" % SQL_ULTIMA_COMPLETA


def ultima_extraccion_completa(con):
    """{fuente: extraccion_id}. Sin entrada para una fuente sin foto buena."""
    return dict((f["fuente"], f["extraccion_id"])
                for f in con.execute(SQL_ULTIMA_COMPLETA))


def edad_de_la_foto(con):
    """{fuente: {extraccion_id, fecha, incompletas_despues}} de la foto curada.

    Que una corrida incompleta conserve la foto anterior es lo correcto, pero
    tiene un modo de fallo lento: si las extracciones fallan varias veces
    seguidas, se cura una foto vieja **indefinidamente y sin ruido**, porque
    todo sigue funcionando. `incompletas_despues` es lo que lo delata: un
    numero que sube corrida tras corrida mientras la fecha no se mueve.
    """
    salida = {}
    for f in con.execute(SQL_ULTIMA_COMPLETA):
        fila = con.execute(
            "SELECT fin, inicio FROM operones_extracciones WHERE id = ?",
            (f["extraccion_id"],)).fetchone()
        fallidas = con.execute(
            """SELECT COUNT(*) FROM operones_extracciones
                WHERE fuente = ? AND id > ? AND completa = 0""",
            (f["fuente"], f["extraccion_id"])).fetchone()[0]
        salida[f["fuente"]] = {
            "extraccion_id": f["extraccion_id"],
            "fecha": (fila["fin"] or fila["inicio"]) if fila else None,
            "incompletas_despues": fallidas,
        }
    return salida


def fuentes_sin_foto(con):
    """Fuentes con bronce pero sin ninguna extraccion completa.

    **Quedan fuera de la curacion entera**, y por eso hay que nombrarlas: una
    fuente que desaparece del catalogo porque su unica descarga se corto es
    indistinguible de una fuente que no trajo nada, y las dos piden acciones
    distintas. El informe de `curar` las lista.
    """
    con_foto = set(ultima_extraccion_completa(con))
    con_bronce = set(f["fuente"] for f in con.execute(
        """SELECT DISTINCT e.fuente FROM operones_bronze b
             JOIN operones_descargas d    ON d.id = b.descarga_id
             JOIN operones_extracciones e ON e.id = d.extraccion_id"""))
    return sorted(con_bronce - con_foto)


def bronze_vigente(con):
    """Las filas de la ULTIMA EXTRACCION COMPLETA de cada fuente.

    No es "la fila mas reciente de cada (fuente, id_fuente)", que tenia dos
    fallas que no se ven hasta que muerden:

    1. **Registros retirados.** Si ODB elimina un operon, su ultima fila
       seguia siendo la mas reciente de su clave y se daba por vigente para
       siempre, sin que nada lo delatara.
    2. **Descargas parciales.** Si la paginacion se corta en la pagina 30, los
       operones de las paginas siguientes conservaban su version anterior y la
       capa curada mezclaba media foto nueva con media vieja.

    Una fuente sin ninguna extraccion completa **no aporta ninguna fila**: con
    media foto no se puede decir que se retiro ni que sigue. `fuentes_sin_foto()`
    las nombra para que el informe lo diga.

    Sin funciones de ventana a proposito: no todas las builds de SQLite que
    trae Python las traen, y este subselect agrupado funciona en todas.
    """
    return con.execute(SQL_BRONZE_VIGENTE).fetchall()


def retirados(con):
    """{fuente: [id_fuente]} que estuvieron y ya no estan en la foto vigente.

    Es la otra mitad de la resta, y tiene que ser visible: un operon que
    desaparece de la fuente es informacion --alguien lo retiro por algo-- y
    dejarlo caer en silencio lo convierte en un hueco que nadie sabe explicar.

    Una fuente sin foto completa no aporta retirados: no se ha retirado nada,
    simplemente no hay con que comparar.
    """
    vigentes = set((f["fuente"], f["id_fuente"]) for f in bronze_vigente(con))
    ultima = ultima_extraccion_completa(con)
    salida = {}
    for f in con.execute(
            """SELECT DISTINCT e.fuente, b.id_fuente FROM operones_bronze b
                 JOIN operones_descargas d    ON d.id = b.descarga_id
                 JOIN operones_extracciones e ON e.id = d.extraccion_id"""):
        par = (f["fuente"], f["id_fuente"])
        if f["fuente"] in ultima and par not in vigentes:
            salida.setdefault(f["fuente"], []).append(f["id_fuente"])
    for v in salida.values():
        v.sort()
    return salida


def conteos_bronze(con):
    """{fuente: n}, para decir que trajo cada fuente sin volcar filas."""
    return dict((f["fuente"], f["n"]) for f in con.execute(
        """SELECT e.fuente, COUNT(*) n FROM operones_bronze b
             JOIN operones_descargas d    ON d.id = b.descarga_id
             JOIN operones_extracciones e ON e.id = d.extraccion_id
            GROUP BY e.fuente"""))
# --------------------------------------------------------------------- silver

def guardar_silver(con, fila, respaldos):
    """Inserta o actualiza un operon curado con sus fuentes. Devuelve su id."""
    con.execute(
        """INSERT INTO operones_silver
             (clave_genes, nombre, locus_tags, n_genes, cadena,
              nivel_evidencia, n_fuentes, pmids, adyacente, es_alternativa,
              monocistronico,
              promotor_cdbprom, revisar, curado_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(clave_genes) DO UPDATE SET
             nombre=excluded.nombre,
             nivel_evidencia=excluded.nivel_evidencia,
             n_fuentes=excluded.n_fuentes,
             pmids=excluded.pmids,
             adyacente=excluded.adyacente,
             es_alternativa=excluded.es_alternativa,
             monocistronico=excluded.monocistronico,
             promotor_cdbprom=excluded.promotor_cdbprom,
             revisar=excluded.revisar,
             curado_en=excluded.curado_en""",
        (fila["clave_genes"], fila.get("nombre"), fila["locus_tags"],
         fila["n_genes"], fila.get("cadena"), fila["nivel_evidencia"],
         fila.get("n_fuentes", 0), fila.get("pmids"),
         1 if fila.get("adyacente") else 0,
         1 if fila.get("es_alternativa") else 0,
         1 if fila.get("monocistronico") else 0,
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
        "monocistronicos": uno(
            "SELECT COUNT(*) FROM operones_silver WHERE monocistronico = 1"),
        "para_revisar": uno(
            """SELECT COUNT(*) FROM operones_silver
                WHERE revisar IS NOT NULL AND revisar <> ''"""),
        "con_promotor": uno(
            "SELECT COUNT(*) FROM operones_silver WHERE promotor_cdbprom = 1"),
    }
