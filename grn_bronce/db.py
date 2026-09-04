# -*- coding: utf-8 -*-
"""El unico modulo del bronce que escribe SQL.

Hoy administra una sola tabla, `corridas`, que es la que hace falta para que
una cifra pueda decir de donde salio: que metodo la produjo, con que version,
con que parametros y sobre que corpus.

Las otras tres tablas del paso 1 --`texto_unidades`, `menciones` y
`oraciones_candidatas`-- estan disenadas y **no se crean todavia**: `CLAUDE.md`
exige proponer el DDL y esperar confirmacion antes de aplicarlo, y el
entregable de hoy es la exportacion tabular, no la persistencia. El contenido
de las tres sale igualmente, en CSV y en Excel.

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
