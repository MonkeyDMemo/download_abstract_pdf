# -*- coding: utf-8 -*-
"""El unico modulo del bronce que escribe SQL.

Administra las cuatro tablas del paso 1: `corridas`, que es la que hace falta
para que una cifra pueda decir de donde salio --que metodo la produjo, con que
version, con que parametros y sobre que corpus-- y las tres del contenido,
`texto_unidades`, `menciones` y `oraciones_candidatas`.

**La exportacion sale de consultar estas tablas, no de lo que quedo en memoria
durante la corrida.** Si tuviera su propio camino, un dia el archivo y la base
dirian cosas distintas y no habria forma de saber cual miente. Por eso las
consultas de exportacion viven aqui abajo y no en `exportar.py`.

`conectar()` se apoya en `grn_etl.db.conectar()` en vez de repetir sus PRAGMAs.
La dependencia va en el sentido correcto --el bronce depende de la extraccion,
no al reves-- y garantiza que las tablas del paso 0 existan, que es lo que las
llaves foraneas del bronce necesitan.

Solo biblioteca estandar.
"""

import json
import sqlite3
from datetime import datetime, timezone

from grn_etl import db as _paso0

ErrorBase = sqlite3.Error

ESQUEMA_BRONCE = """
CREATE TABLE IF NOT EXISTS corridas (
    id              INTEGER PRIMARY KEY,
    paso            TEXT NOT NULL,
    metodo          TEXT NOT NULL,
    version         TEXT NOT NULL,
    parametros      TEXT,
    corpus_id       INTEGER REFERENCES corpus(id),
    iniciada_en     TEXT NOT NULL,
    terminada_en    TEXT,
    estatus         TEXT NOT NULL,
    error           TEXT,
    n_entrada       INTEGER,
    n_salida        INTEGER
);

CREATE INDEX IF NOT EXISTS ix_corridas_metodo ON corridas(metodo, version);

CREATE TABLE IF NOT EXISTS texto_unidades (
    id           INTEGER PRIMARY KEY,
    pmid         TEXT NOT NULL REFERENCES documentos(pmid),
    fuente_texto TEXT NOT NULL,
    seccion      TEXT,
    num_oracion  INTEGER NOT NULL,
    texto        TEXT NOT NULL,
    offset_ini   INTEGER NOT NULL,
    offset_fin   INTEGER NOT NULL,
    contiguo     INTEGER NOT NULL DEFAULT 1,
    corrida_id   INTEGER NOT NULL REFERENCES corridas(id),
    UNIQUE (corrida_id, pmid, fuente_texto, num_oracion)
);

CREATE TABLE IF NOT EXISTS menciones (
    id             INTEGER PRIMARY KEY,
    unidad_id      INTEGER NOT NULL REFERENCES texto_unidades(id),
    tipo           TEXT NOT NULL,
    texto          TEXT NOT NULL,
    id_normalizado TEXT,
    offset_ini     INTEGER NOT NULL,
    offset_fin     INTEGER NOT NULL,
    metodo         TEXT NOT NULL,
    corrida_id     INTEGER NOT NULL REFERENCES corridas(id)
);

CREATE TABLE IF NOT EXISTS oraciones_candidatas (
    id                  INTEGER PRIMARY KEY,
    unidad_id           INTEGER NOT NULL REFERENCES texto_unidades(id),
    entidades           TEXT NOT NULL,
    disparador          TEXT,
    signo_sugerido      TEXT,
    regulador_candidato TEXT,
    blanco_candidato    TEXT,
    score               REAL,
    metodo              TEXT NOT NULL,
    corrida_id          INTEGER NOT NULL REFERENCES corridas(id)
);

CREATE INDEX IF NOT EXISTS ix_tu_corrida   ON texto_unidades(corrida_id, pmid);
CREATE INDEX IF NOT EXISTS ix_men_unidad   ON menciones(unidad_id);
CREATE INDEX IF NOT EXISTS ix_men_corrida  ON menciones(corrida_id, tipo);
CREATE INDEX IF NOT EXISTS ix_cand_unidad  ON oraciones_candidatas(unidad_id);
CREATE INDEX IF NOT EXISTS ix_cand_corrida ON oraciones_candidatas(corrida_id);
"""


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar(ruta="datos/grn.db"):
    """Abre la base con el esquema del paso 0 y el del bronce encima."""
    con = _paso0.conectar(ruta)
    con.executescript(ESQUEMA_BRONCE)
    return con


def abrir_corrida(con, paso, metodo, version, parametros=None, corpus_id=None):
    """Registra la corrida ANTES de procesar y devuelve su id.

    Antes y no despues: si el proceso muere a la mitad, tiene que quedar
    constancia de que se intento. Una corrida que solo se registra al terminar
    convierte cada interrupcion en un hueco silencioso en la bitacora.
    """
    cur = con.execute(
        """INSERT INTO corridas
             (paso, metodo, version, parametros, corpus_id,
              iniciada_en, estatus)
           VALUES (?,?,?,?,?,?,'corriendo')""",
        (paso, metodo, version,
         json.dumps(parametros or {}, ensure_ascii=False, sort_keys=True),
         corpus_id, ahora()))
    con.commit()
    return cur.lastrowid


def cerrar_corrida(con, corrida_id, estatus, error=None,
                   n_entrada=None, n_salida=None):
    con.execute(
        """UPDATE corridas
              SET terminada_en = ?, estatus = ?, error = ?,
                  n_entrada = ?, n_salida = ?
            WHERE id = ?""",
        (ahora(), estatus, (error or "")[:500] or None,
         n_entrada, n_salida, corrida_id))
    con.commit()


def corrida_previa(con, metodo, version, corpus_id=None):
    """La ultima corrida terminada bien con ese par, o None.

    Es la base de la idempotencia por `(metodo, version)`: si ya existe, no
    hay nada nuevo que calcular salvo que se pida rehacer.

    **Solo mira corridas con estatus 'ok'.** Una cortada con Ctrl-C queda en
    'corriendo' para siempre y nadie la limpia; contarla como hecha convertiria
    una corrida zombi en un resultado.
    """
    sql = ("""SELECT * FROM corridas
               WHERE metodo = ? AND version = ? AND estatus = 'ok'""")
    params = [metodo, version]
    if corpus_id is not None:
        sql += " AND corpus_id = ?"
        params.append(corpus_id)
    return con.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()


def listar_corridas(con, limite=20):
    return con.execute(
        "SELECT * FROM corridas ORDER BY id DESC LIMIT ?", (limite,)).fetchall()


def documentos_del_corpus(con, corpus_id=None):
    """Los documentos a procesar, con lo que la hoja 1 necesita de cada uno.

    Si `corpus_id` es None se toman todos los de la base. El encargo lo permite
    para el caso en que no haya corpus congelado; con corpus la corrida es
    reproducible y sin el no, asi que conviene decirlo en el informe.
    """
    campos = ("pmid, doi, titulo, anio, revista, extraido_en, abstract, "
              "tiene_abstract")
    if corpus_id is None:
        return con.execute(
            "SELECT %s FROM documentos ORDER BY pmid" % campos).fetchall()
    return con.execute(
        """SELECT %s FROM documentos d
             JOIN corpus_documento cd ON cd.pmid = d.pmid
            WHERE cd.corpus_id = ?
            ORDER BY d.pmid""" % campos.replace("pmid,", "d.pmid,"),
        (corpus_id,)).fetchall()


# ------------------------------------------------------- escritura del bronce

def guardar_unidad(con, corrida_id, u):
    """Inserta una oracion y devuelve su id."""
    cur = con.execute(
        """INSERT INTO texto_unidades
             (pmid, fuente_texto, seccion, num_oracion, texto,
              offset_ini, offset_fin, contiguo, corrida_id)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(corrida_id, pmid, fuente_texto, num_oracion)
           DO NOTHING""",
        (u["pmid"], u["fuente_texto"], u["seccion"], u["num_oracion"],
         u["texto"], u["offset_ini"], u["offset_fin"],
         1 if u.get("contiguo", True) else 0, corrida_id))
    if cur.lastrowid:
        return cur.lastrowid
    fila = con.execute(
        """SELECT id FROM texto_unidades
            WHERE corrida_id=? AND pmid=? AND fuente_texto=? AND num_oracion=?""",
        (corrida_id, u["pmid"], u["fuente_texto"], u["num_oracion"])).fetchone()
    return fila["id"] if fila else None


def guardar_menciones(con, corrida_id, metodo, unidad_id, filas):
    """Inserta las menciones de una unidad y devuelve sus ids, en orden."""
    ids = []
    for m in filas:
        cur = con.execute(
            """INSERT INTO menciones
                 (unidad_id, tipo, texto, id_normalizado,
                  offset_ini, offset_fin, metodo, corrida_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (unidad_id, m["tipo"], m["texto"], m["id_normalizado"],
             m["offset_ini"], m["offset_fin"], metodo, corrida_id))
        ids.append(cur.lastrowid)
    return ids


def guardar_candidata(con, corrida_id, metodo, unidad_id, c, ids_menciones):
    con.execute(
        """INSERT INTO oraciones_candidatas
             (unidad_id, entidades, disparador, signo_sugerido,
              regulador_candidato, blanco_candidato, score, metodo, corrida_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (unidad_id, json.dumps(ids_menciones), c["disparador"],
         c["signo_sugerido"], c["regulador_candidato"], c["blanco_candidato"],
         c["score"], metodo, corrida_id))


def borrar_corrida(con, corrida_id):
    """Borra las filas del bronce de una corrida, para poder rehacerla.

    En orden inverso a las llaves foraneas, y en una transaccion: quedarse a
    la mitad dejaria menciones apuntando a unidades que ya no estan.
    """
    with con:
        con.execute("DELETE FROM oraciones_candidatas WHERE corrida_id = ?",
                    (corrida_id,))
        con.execute("DELETE FROM menciones WHERE corrida_id = ?", (corrida_id,))
        con.execute("DELETE FROM texto_unidades WHERE corrida_id = ?",
                    (corrida_id,))


# --------------------------------------------------- consultas de exportacion
#
# El Excel y los CSV salen de AQUI, no de lo que quedo en memoria durante la
# corrida. Si la exportacion tuviera su propio camino, un dia el archivo y la
# base dirian cosas distintas y no habria forma de saber cual miente.

SQL_CANDIDATAS = """
SELECT u.id AS unidad_id,
       d.pmid, d.doi, d.titulo, d.anio, d.revista,
       d.extraido_en                              AS fecha_ingesta,
       u.fuente_texto, u.seccion, u.num_oracion,
       u.texto                                    AS oracion,
       c.regulador_candidato, c.blanco_candidato,
       c.disparador, c.signo_sugerido, c.score,
       c.metodo, r.version, c.corrida_id, r.iniciada_en AS fecha_corrida,
       c.entidades
  FROM oraciones_candidatas c
  JOIN texto_unidades u ON u.id = c.unidad_id
  JOIN documentos     d ON d.pmid = u.pmid
  JOIN corridas       r ON r.id = c.corrida_id
 WHERE c.corrida_id = ?
 ORDER BY d.pmid, u.fuente_texto, u.num_oracion
"""

SQL_MENCIONES_DE_UNIDAD = """
SELECT tipo, texto, id_normalizado
  FROM menciones WHERE unidad_id = ? ORDER BY offset_ini
"""

SQL_MENCIONES = """
SELECT u.pmid, u.fuente_texto, u.seccion, u.num_oracion,
       m.tipo, m.texto, m.id_normalizado, m.offset_ini, m.offset_fin,
       m.metodo, r.version, m.corrida_id
  FROM menciones m
  JOIN texto_unidades u ON u.id = m.unidad_id
  JOIN corridas       r ON r.id = m.corrida_id
 WHERE m.corrida_id = ?
 ORDER BY u.pmid, u.fuente_texto, u.num_oracion, m.offset_ini
"""


SQL_MENCIONES_POR_UNIDAD = """
SELECT m.unidad_id, m.tipo, m.texto, m.id_normalizado
  FROM menciones m
  JOIN oraciones_candidatas c ON c.unidad_id = m.unidad_id
 WHERE m.corrida_id = ?
 ORDER BY m.unidad_id, m.offset_ini
"""


def menciones_por_unidad_candidata(con, corrida_id):
    """{unidad_id: [(tipo, texto, id_normalizado)]} de las que son candidatas.

    Una sola consulta en vez de una por candidata. Con quince mil candidatas
    la diferencia entre una y quince mil no es un detalle.
    """
    salida = {}
    for f in con.execute(SQL_MENCIONES_POR_UNIDAD, (corrida_id,)):
        salida.setdefault(f["unidad_id"], []).append(
            (f["tipo"], f["texto"], f["id_normalizado"]))
    return salida


def candidatas_de(con, corrida_id):
    return con.execute(SQL_CANDIDATAS, (corrida_id,)).fetchall()


def menciones_de(con, corrida_id):
    return con.execute(SQL_MENCIONES, (corrida_id,)).fetchall()


def menciones_de_unidad(con, unidad_id):
    return con.execute(SQL_MENCIONES_DE_UNIDAD, (unidad_id,)).fetchall()


def conteos_de(con, corrida_id):
    """Los numeros de la hoja resumen, contados en la base y no en memoria."""
    def uno(sql, params=()):
        return con.execute(sql, params).fetchone()[0]

    por_tipo = dict(
        (f["tipo"], f["n"]) for f in con.execute(
            """SELECT tipo, COUNT(*) n FROM menciones
                WHERE corrida_id = ? GROUP BY tipo""", (corrida_id,)))
    return {
        "unidades": uno("SELECT COUNT(*) FROM texto_unidades WHERE corrida_id=?",
                        (corrida_id,)),
        "unidades_no_contiguas": uno(
            "SELECT COUNT(*) FROM texto_unidades WHERE corrida_id=? AND contiguo=0",
            (corrida_id,)),
        "documentos": uno(
            "SELECT COUNT(DISTINCT pmid) FROM texto_unidades WHERE corrida_id=?",
            (corrida_id,)),
        "documentos_con_fulltext": uno(
            """SELECT COUNT(DISTINCT pmid) FROM texto_unidades
                WHERE corrida_id=? AND fuente_texto='xml'""", (corrida_id,)),
        "candidatas": uno(
            "SELECT COUNT(*) FROM oraciones_candidatas WHERE corrida_id=?",
            (corrida_id,)),
        "menciones": uno("SELECT COUNT(*) FROM menciones WHERE corrida_id=?",
                         (corrida_id,)),
        "por_tipo": por_tipo,
        "genes_distintos": uno(
            """SELECT COUNT(DISTINCT texto) FROM menciones
                WHERE corrida_id=? AND tipo IN ('gen','proteina')""",
            (corrida_id,)),
        "genes_normalizados": uno(
            """SELECT COUNT(*) FROM menciones
                WHERE corrida_id=? AND tipo IN ('gen','proteina')
                  AND id_normalizado LIKE 'PA%'""", (corrida_id,)),
        "genes_totales": uno(
            """SELECT COUNT(*) FROM menciones
                WHERE corrida_id=? AND tipo IN ('gen','proteina')""",
            (corrida_id,)),
        "con_regulador": uno(
            """SELECT COUNT(*) FROM oraciones_candidatas
                WHERE corrida_id=? AND regulador_candidato <> ''""",
            (corrida_id,)),
        "con_disparador": uno(
            """SELECT COUNT(*) FROM oraciones_candidatas
                WHERE corrida_id=? AND disparador <> ''""", (corrida_id,)),
    }


def fulltext_disponible(con, tipo="xml"):
    """{pmid: ruta} de las descargas con estatus 'ok' de ese tipo.

    Se consulta `descargas`, que es la tabla que sabe que se bajo de verdad, en
    vez de listar el directorio. Un archivo suelto en disco puede ser de una
    descarga fallida a medias; la fila con estatus 'ok' no.
    """
    return dict(
        (f["pmid"], f["ruta"]) for f in con.execute(
            """SELECT pmid, ruta FROM descargas
                WHERE tipo = ? AND estatus = 'ok' AND ruta IS NOT NULL""",
            (tipo,)))
