# -*- coding: utf-8 -*-
"""Capa de base de datos (SQLite).

Todo el estado del ETL vive aqui. Ninguna otra capa hace SQL.
Cuando esto pase a ser servicio, se cambia SQLite por Postgres tocando
solo este archivo: las firmas de las funciones no cambian.

Modelo:

    consultas            una query de PubMed con nombre
    ejecuciones          cada vez que se corre una consulta
    documentos           un articulo, unico por PMID (nunca se duplica)
    consulta_documento   que consulta trajo que documento (N a N)
    descargas            estado de full text por PMID y tipo (xml / pdf)

La clave del diseno es que 'documentos' esta separado de
'consulta_documento'. Un articulo que aparece en tres consultas se
almacena una sola vez y se liga tres veces. Eso hace el ETL idempotente:
volver a correr una consulta no re-descarga nada que ya se tenga.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Lo que puede salir mal al hablar con la base, con nombre propio de esta
# capa. Existe para que ninguna otra importe sqlite3: servidor.py atrapa
# db.ErrorBase y no se entera de que motor hay debajo. Es la promesa de
# migracion-servicio.md llevada al codigo, porque un 'except sqlite3.Error'
# en la capa HTTP haria que migrar a Postgres tocara mas de un archivo.
ErrorBase = sqlite3.Error

ESQUEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS consultas (
    id          INTEGER PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE,
    texto       TEXT NOT NULL,
    descripcion TEXT,
    activa      INTEGER NOT NULL DEFAULT 1,
    creada_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ejecuciones (
    id            INTEGER PRIMARY KEY,
    consulta_id   INTEGER NOT NULL REFERENCES consultas(id),
    iniciada_en   TEXT NOT NULL,
    terminada_en  TEXT,
    estatus       TEXT NOT NULL,
    total_pubmed  INTEGER,
    pmids_nuevos  INTEGER,
    pmids_previos INTEGER,
    descargados   INTEGER,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS documentos (
    pmid              TEXT PRIMARY KEY,
    doi               TEXT,
    pmcid             TEXT,
    titulo            TEXT,
    abstract          TEXT,
    revista           TEXT,
    anio              TEXT,
    autores           TEXT,
    mesh_terms        TEXT,
    keywords          TEXT,
    tipos_publicacion TEXT,
    tiene_abstract    INTEGER NOT NULL DEFAULT 0,
    extraido_en       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consulta_documento (
    consulta_id  INTEGER NOT NULL REFERENCES consultas(id),
    pmid         TEXT    NOT NULL REFERENCES documentos(pmid),
    ejecucion_id INTEGER REFERENCES ejecuciones(id),
    vinculado_en TEXT NOT NULL,
    PRIMARY KEY (consulta_id, pmid)
);

CREATE TABLE IF NOT EXISTS descargas (
    id            INTEGER PRIMARY KEY,
    pmid          TEXT NOT NULL REFERENCES documentos(pmid),
    tipo          TEXT NOT NULL,
    estatus       TEXT NOT NULL,
    fuente        TEXT,
    ruta          TEXT,
    bytes         INTEGER,
    nota          TEXT,
    url           TEXT,
    intentos      INTEGER NOT NULL DEFAULT 1,
    actualizado_en TEXT NOT NULL,
    UNIQUE (pmid, tipo)
);

CREATE INDEX IF NOT EXISTS ix_doc_anio    ON documentos(anio);
CREATE INDEX IF NOT EXISTS ix_cd_pmid     ON consulta_documento(pmid);
CREATE INDEX IF NOT EXISTS ix_desc_estado ON descargas(tipo, estatus);

CREATE VIEW IF NOT EXISTS v_documentos_consulta AS
SELECT c.nombre AS consulta, d.*
FROM documentos d
JOIN consulta_documento cd ON cd.pmid = d.pmid
JOIN consultas c           ON c.id = cd.consulta_id;
"""

CAMPOS_LISTA = ("autores", "mesh_terms", "keywords", "tipos_publicacion")

# Lo unico que se puede editar a mano desde el tablero. El resto de las
# columnas (pmid, tiene_abstract, extraido_en) las mantiene el ETL: si un
# formulario las pisa, la base deja de decir lo que de verdad se descargo.
COLUMNAS_EDITABLES = ("titulo", "abstract", "anio", "doi", "pmcid", "revista")


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar(ruta="grn.db"):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    # WAL porque el tablero lee mientras el ETL escribe. Con el journal
    # clasico el lector bloquea al escritor y sale 'database is locked' a
    # media corrida. En WAL conviven: el lector ve la ultima version
    # consolidada y no espera.
    # Hay dos casos donde no se puede: ':memory:' (responde 'memory') y los
    # sistemas de archivos de red, que no soportan la memoria compartida del
    # WAL y devuelven error. En ninguno de los dos vale tumbar la conexion:
    # sin WAL la base sigue siendo correcta, nada mas menos concurrente.
    try:
        con.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass

    # WAL no arregla dos ESCRITORES simultaneos (borrar desde el tablero
    # mientras corre una ingesta). Esperar en vez de fallar al instante
    # cubre el caso comun, que es un choque de milisegundos. El arreglo de
    # fondo sigue siendo Postgres.
    con.execute("PRAGMA busy_timeout = 5000")

    con.executescript(ESQUEMA)
    _migrar(con)
    return con


def _migrar(con):
    """Agrega columnas que no existian en versiones previas del esquema.

    'CREATE TABLE IF NOT EXISTS' no toca una tabla que ya existe, asi que
    una base creada antes se quedaria sin la columna nueva. Migrarla aqui
    evita tener que pedirle a alguien que borre su base y vuelva a
    descargar todo, que es justo lo que este proyecto existe para evitar.
    """
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(descargas)")}
    if "url" not in columnas:
        con.execute("ALTER TABLE descargas ADD COLUMN url TEXT")
        con.commit()


# ------------------------------------------------------------- auxiliares

def _patron(texto):
    """Arma el patron de LIKE para una busqueda parcial.

    El valor viaja siempre como parametro (?), nunca concatenado, asi que
    la inyeccion ya esta descartada por ahi. Lo que se escapa aqui son los
    comodines '%' y '_': quien busca "100%" o "PA_0762" espera esos
    caracteres literales, y sin escaparlos la busqueda devolveria media
    tabla como si no filtrara nada.
    """
    limpio = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + limpio + "%"


def paginado(pagina, por_pagina):
    """Normaliza la paginacion. Devuelve (pagina, por_pagina, desplazamiento).

    Publica y no privada porque la capa HTTP tiene que devolver en la
    respuesta los valores YA acotados: si el tablero pide la pagina 0 y
    recibe las filas de la 1 sin enterarse, pinta una paginacion que no
    corresponde a lo que muestra. Duplicar los limites alla seria tener
    dos verdades sobre lo mismo.

    Los valores llegan de una query string: como cadenas y escritos por
    quien sea. Convertirlos y acotarlos aqui, y no en cada listado, es lo
    que evita que un filtro nuevo se olvide de hacerlo. Ausente ('' o
    None) cae en el valor por omision; fuera de rango se recorta.

    El tope de 500 no es capricho: sin el, un por_pagina de seis cifras en
    la URL traeria la tabla entera a memoria en cada refresco del tablero.
    """
    pagina = 1 if pagina in (None, "") else max(1, int(pagina))
    if por_pagina in (None, ""):
        por_pagina = 50
    else:
        por_pagina = min(max(1, int(por_pagina)), 500)
    return pagina, por_pagina, (pagina - 1) * por_pagina


# --------------------------------------------------------------- consultas

def alta_consulta(con, nombre, texto, descripcion=None):
    """Registra una consulta. Si el nombre ya existe, actualiza el texto."""
    fila = con.execute(
        "SELECT id, texto FROM consultas WHERE nombre = ?", (nombre,)
    ).fetchone()
    if fila:
        if fila["texto"] != texto:
            con.execute(
                "UPDATE consultas SET texto = ?, descripcion = ? WHERE id = ?",
                (texto, descripcion, fila["id"]),
            )
            con.commit()
            return fila["id"], "actualizada"
        return fila["id"], "sin_cambios"

    cur = con.execute(
        "INSERT INTO consultas (nombre, texto, descripcion, creada_en) "
        "VALUES (?, ?, ?, ?)",
        (nombre, texto, descripcion, ahora()),
    )
    con.commit()
    return cur.lastrowid, "creada"


def obtener_consulta(con, nombre):
    return con.execute("SELECT * FROM consultas WHERE nombre = ?", (nombre,)).fetchone()


def obtener_consulta_por_id(con, consulta_id):
    """La fila de una consulta por su id, o None.

    El id es como el tablero se refiere a una consulta en las rutas
    (/api/consultas/<id>), asi que hace falta buscarla por ahi y no solo
    por nombre. Un SELECT por llave primaria y no un recorrido de
    listar_consultas(): ese listado calcula dos subconsultas
    correlacionadas por cada consulta registrada, y descartar las demas en
    Python las paga todas para quedarse con una.
    """
    return con.execute(
        "SELECT * FROM consultas WHERE id = ?", (consulta_id,)
    ).fetchone()


def listar_consultas(con):
    return con.execute(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM consulta_documento cd
                    WHERE cd.consulta_id = c.id) AS n_documentos,
                  (SELECT MAX(terminada_en) FROM ejecuciones e
                    WHERE e.consulta_id = c.id AND e.estatus = 'ok') AS ultima_corrida
             FROM consultas c ORDER BY c.nombre"""
    ).fetchall()


def actualizar_consulta(con, consulta_id, texto=None, descripcion=None,
                        activa=None):
    """Edita una consulta existente. Devuelve True si cambio alguna fila.

    None significa "no toques ese campo", no "ponlo en NULL": el tablero
    manda solo lo que el usuario edito. Para vaciar la descripcion se
    manda cadena vacia.

    El nombre no se toca a proposito. Es la llave con la que el CLI, las
    ejecuciones y los exportes se refieren a la consulta; renombrarla
    desde un formulario dejaria scripts del laboratorio apuntando a algo
    que ya no existe. Para eso esta alta_consulta().
    """
    asignaciones, valores = [], []
    if texto is not None:
        asignaciones.append("texto = ?")
        valores.append(texto)
    if descripcion is not None:
        asignaciones.append("descripcion = ?")
        valores.append(descripcion)
    if activa is not None:
        asignaciones.append("activa = ?")
        valores.append(1 if activa else 0)

    if not asignaciones:
        return False

    valores.append(consulta_id)
    # Los nombres de columna salen de este mismo codigo, no del cuerpo
    # recibido; los valores van todos como ?.
    cur = con.execute(
        "UPDATE consultas SET " + ", ".join(asignaciones) + " WHERE id = ?",
        valores,
    )
    con.commit()
    return cur.rowcount > 0


def borrar_consulta(con, consulta_id):
    """Borra una consulta, sus vinculos y su bitacora.

    Devuelve {"vinculos": n, "ejecuciones": n}: quien borra tiene derecho
    a saber cuanta trazabilidad se llevo por delante.

    Los documentos NO se borran. Pueden pertenecer a otras consultas, y
    aunque no pertenezcan a ninguna siguen siendo trabajo ya descargado;
    tirarlos obligaria a bajarlos de nuevo, que es justo lo que este
    proyecto existe para evitar. Quedan sin vinculo y se siguen viendo en
    listar_documentos().

    El orden lo imponen las llaves foraneas: consulta_documento apunta a
    consultas y a ejecuciones, y ejecuciones apunta a consultas. Todo en
    una transaccion, porque quedarse a la mitad deja una consulta sin
    bitacora o una bitacora sin consulta.
    """
    with con:
        vinculos = con.execute(
            "DELETE FROM consulta_documento WHERE consulta_id = ?",
            (consulta_id,),
        ).rowcount
        ejecuciones = con.execute(
            "DELETE FROM ejecuciones WHERE consulta_id = ?", (consulta_id,)
        ).rowcount
        con.execute("DELETE FROM consultas WHERE id = ?", (consulta_id,))
    return {"vinculos": vinculos, "ejecuciones": ejecuciones}


def conteos_consulta(con, consulta_id):
    """Que cuelga de una consulta: {"vinculos": n, "ejecuciones": n}.

    Mismas llaves y mismas tablas que borrar_consulta(), a proposito: lo
    que la confirmacion promete y lo que el borrado devuelve tienen que
    ser el mismo numero.

    Se cuenta con COUNT y no midiendo el largo de una pagina de
    resultados. Contar filas traidas con un LIMIT da el limite en cuanto
    se rebasa: el dialogo diria que se van mil ejecuciones y se irian mil
    doscientas. Una confirmacion que se queda corta sobre el alcance de un
    borrado es peor que no dar el numero.
    """
    return {
        "vinculos": con.execute(
            "SELECT COUNT(*) c FROM consulta_documento WHERE consulta_id = ?",
            (consulta_id,),
        ).fetchone()["c"],
        "ejecuciones": con.execute(
            "SELECT COUNT(*) c FROM ejecuciones WHERE consulta_id = ?",
            (consulta_id,),
        ).fetchone()["c"],
    }


# ------------------------------------------------------------- ejecuciones

def abrir_ejecucion(con, consulta_id):
    cur = con.execute(
        "INSERT INTO ejecuciones (consulta_id, iniciada_en, estatus) "
        "VALUES (?, ?, 'corriendo')",
        (consulta_id, ahora()),
    )
    con.commit()
    return cur.lastrowid


def cerrar_ejecucion(con, ejecucion_id, estatus, **contadores):
    con.execute(
        """UPDATE ejecuciones SET terminada_en = ?, estatus = ?,
                  total_pubmed = ?, pmids_nuevos = ?, pmids_previos = ?,
                  descargados = ?, error = ?
             WHERE id = ?""",
        (
            ahora(), estatus,
            contadores.get("total_pubmed"), contadores.get("pmids_nuevos"),
            contadores.get("pmids_previos"), contadores.get("descargados"),
            contadores.get("error"), ejecucion_id,
        ),
    )
    con.commit()


def historial(con, nombre=None, limite=20):
    sql = """SELECT e.*, c.nombre AS consulta FROM ejecuciones e
             JOIN consultas c ON c.id = e.consulta_id"""
    params = []
    if nombre:
        sql += " WHERE c.nombre = ?"
        params.append(nombre)
    sql += " ORDER BY e.id DESC LIMIT ?"
    params.append(limite)
    return con.execute(sql, params).fetchall()


def obtener_ejecucion(con, ejecucion_id):
    """Una ejecucion con el nombre de su consulta, o None.

    Es el sondeo de una corrida lanzada desde el tablero: 'ejecuciones' ya
    guarda estatus, inicio, fin y error, asi que no hace falta una tabla
    de trabajos aparte.
    """
    return con.execute(
        """SELECT e.*, c.nombre AS consulta FROM ejecuciones e
             JOIN consultas c ON c.id = e.consulta_id
            WHERE e.id = ?""",
        (ejecucion_id,),
    ).fetchone()


# -------------------------------------------------------------- documentos

def pmids_conocidos(con, pmids):
    """De una lista de PMIDs, cuales ya estan en la base.

    Es el corazon de la idempotencia: solo se descarga la diferencia.
    Se consulta por lotes porque SQLite limita el numero de parametros.
    """
    conocidos = set()
    lista = list(pmids)
    for i in range(0, len(lista), 800):
        lote = lista[i:i + 800]
        marcas = ",".join("?" * len(lote))
        filas = con.execute(
            f"SELECT pmid FROM documentos WHERE pmid IN ({marcas})", lote
        ).fetchall()
        conocidos.update(f["pmid"] for f in filas)
    return conocidos


def guardar_documentos(con, registros):
    """Inserta documentos nuevos. Si el PMID ya existe, no lo pisa."""
    filas = []
    for r in registros:
        filas.append((
            r["pmid"], r.get("doi", ""), r.get("pmcid", ""),
            r.get("titulo", ""), r.get("abstract", ""),
            r.get("revista", ""), r.get("anio", ""),
            *[json.dumps(r.get(c, []), ensure_ascii=False) for c in CAMPOS_LISTA],
            1 if r.get("abstract") else 0,
            ahora(),
        ))
    con.executemany(
        """INSERT INTO documentos
           (pmid, doi, pmcid, titulo, abstract, revista, anio,
            autores, mesh_terms, keywords, tipos_publicacion,
            tiene_abstract, extraido_en)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(pmid) DO NOTHING""",
        filas,
    )
    con.commit()
    return len(filas)


def vincular(con, consulta_id, pmids, ejecucion_id=None):
    """Liga PMIDs a una consulta. Repetir la ejecucion no duplica.

    Solo se ligan los PMIDs que existen en 'documentos'. esearch devuelve
    PMIDs que efetch luego no entrega (registros retirados, tipo Book), y
    ligarlos violaria la llave foranea y abortaria la corrida completa por
    un solo articulo. Se ignoran en silencio; quien llama ya sabe cuales
    faltaron y lo reporta.

    El INSERT ... SELECT hace el filtro en una sola pasada: si el PMID no
    esta en 'documentos' el SELECT no devuelve filas y no se inserta nada.
    """
    t = ahora()
    con.executemany(
        """INSERT INTO consulta_documento
             (consulta_id, pmid, ejecucion_id, vinculado_en)
           SELECT ?, d.pmid, ?, ? FROM documentos d WHERE d.pmid = ?
           ON CONFLICT(consulta_id, pmid) DO NOTHING""",
        [(consulta_id, ejecucion_id, t, p) for p in pmids],
    )
    con.commit()


def a_dict(fila):
    """Convierte una fila de documentos a dict, deserializando las listas."""
    d = dict(fila)
    for c in CAMPOS_LISTA:
        if c in d and d[c]:
            try:
                d[c] = json.loads(d[c])
            except (json.JSONDecodeError, TypeError):
                d[c] = []
    return d


def documentos_de_consulta(con, nombre, solo_con_abstract=False, limite=None):
    sql = """SELECT d.* FROM documentos d
             JOIN consulta_documento cd ON cd.pmid = d.pmid
             JOIN consultas c ON c.id = cd.consulta_id
             WHERE c.nombre = ?"""
    if solo_con_abstract:
        sql += " AND d.tiene_abstract = 1"
    sql += " ORDER BY d.anio DESC, d.pmid"
    params = [nombre]
    if limite:
        sql += " LIMIT ?"
        params.append(limite)
    return con.execute(sql, params).fetchall()


def listar_documentos(con, texto=None, consulta=None, anio=None,
                      con_abstract=None, pagina=1, por_pagina=50):
    """Documentos filtrados y paginados. Devuelve (total, filas).

    'total' es el conteo con los mismos filtros pero sin paginar: el
    tablero necesita saber cuantas paginas hay, no solo cuantas filas trae
    esta. 'consulta' es el NOMBRE, igual que en documentos_de_consulta().
    'texto' busca en titulo, abstract y pmid.

    El SQL se arma por pedazos, pero los pedazos son literales escritos
    aqui; todo valor que venga de afuera entra como ?.
    """
    pagina, por_pagina, desplazamiento = paginado(pagina, por_pagina)

    origen = "FROM documentos d"
    donde, params = [], []

    if consulta:
        # La PK (consulta_id, pmid) garantiza a lo mas una fila por
        # documento, asi que el join no duplica y no hace falta DISTINCT.
        origen += (" JOIN consulta_documento cd ON cd.pmid = d.pmid"
                   " JOIN consultas c ON c.id = cd.consulta_id")
        donde.append("c.nombre = ?")
        params.append(consulta)

    if texto:
        donde.append("(d.titulo LIKE ? ESCAPE '\\'"
                     " OR d.abstract LIKE ? ESCAPE '\\'"
                     " OR d.pmid LIKE ? ESCAPE '\\')")
        params.extend([_patron(texto)] * 3)

    if anio:
        donde.append("d.anio = ?")
        params.append(str(anio))

    if con_abstract is not None:
        donde.append("d.tiene_abstract = ?")
        params.append(1 if con_abstract else 0)

    filtro = (" WHERE " + " AND ".join(donde)) if donde else ""

    total = con.execute(
        "SELECT COUNT(*) c " + origen + filtro, params
    ).fetchone()["c"]
    filas = con.execute(
        "SELECT d.* " + origen + filtro
        + " ORDER BY d.anio DESC, d.pmid LIMIT ? OFFSET ?",
        params + [por_pagina, desplazamiento],
    ).fetchall()
    return total, filas


def obtener_documento(con, pmid):
    return con.execute(
        "SELECT * FROM documentos WHERE pmid = ?", (pmid,)
    ).fetchone()


def actualizar_documento(con, pmid, campos):
    """Corrige a mano un documento. Devuelve True si cambio alguna fila.

    Solo se aceptan las columnas de COLUMNAS_EDITABLES; cualquier otra
    clave se ignora en silencio. La decision es a proposito: el tablero
    devuelve el formulario completo, con pmid y extraido_en incluidos, y
    fallar por eso obligaria a la capa HTTP a recortar el cuerpo antes de
    llamar, o sea a saber de columnas. Lo que no puede pasar es que una
    clave arbitraria llegue al SQL, y no llega: los nombres de columna del
    UPDATE salen de la constante, no del cuerpo recibido.
    """
    asignaciones, valores = [], []
    for columna in COLUMNAS_EDITABLES:
        if columna in campos:
            asignaciones.append(columna + " = ?")
            valores.append(campos[columna])

    if not asignaciones:
        return False

    # Sin esto el resumen miente: se vacia el abstract desde el tablero y
    # 'con_abstract' sigue contando el documento como que lo tiene.
    if "abstract" in campos:
        asignaciones.append("tiene_abstract = ?")
        valores.append(1 if campos["abstract"] else 0)

    valores.append(pmid)
    cur = con.execute(
        "UPDATE documentos SET " + ", ".join(asignaciones) + " WHERE pmid = ?",
        valores,
    )
    con.commit()
    return cur.rowcount > 0


def borrar_documento(con, pmid):
    """Borra un documento y todo lo que cuelga de el.

    Devuelve {"vinculos": n, "descargas": n}. Las cuentas no son adorno:
    un articulo puede estar ligado a cinco consultas y tener full text ya
    bajado, y quien borra necesita ver que se llevo.

    El orden lo imponen las llaves foraneas (consulta_documento y
    descargas apuntan a documentos) y va en una sola transaccion: a medio
    camino quedarian vinculos apuntando a un documento inexistente, que es
    exactamente lo que las FK estan ahi para impedir.

    El archivo de full text en disco no se toca; el registro de la
    descarga si desaparece.
    """
    with con:
        vinculos = con.execute(
            "DELETE FROM consulta_documento WHERE pmid = ?", (pmid,)
        ).rowcount
        descargas = con.execute(
            "DELETE FROM descargas WHERE pmid = ?", (pmid,)
        ).rowcount
        con.execute("DELETE FROM documentos WHERE pmid = ?", (pmid,))
    return {"vinculos": vinculos, "descargas": descargas}


def conteos_documento(con, pmid):
    """Que cuelga de un documento: {"vinculos": n, "descargas": n}.

    Mismas llaves y mismas tablas que borrar_documento(), a proposito: es
    lo que permite decirle a quien va a borrar cuanto se va a llevar
    ANTES de que confirme, y no despues. Una advertencia con el numero
    exacto es la diferencia entre borrar a ciegas y borrar sabiendo.
    """
    return {
        "vinculos": con.execute(
            "SELECT COUNT(*) c FROM consulta_documento WHERE pmid = ?", (pmid,)
        ).fetchone()["c"],
        "descargas": con.execute(
            "SELECT COUNT(*) c FROM descargas WHERE pmid = ?", (pmid,)
        ).fetchone()["c"],
    }


def anios_disponibles(con):
    """Anios distintos que hay en documentos, del mas reciente al mas viejo.

    Alimenta el filtro del tablero con lo que de verdad esta en la base en
    vez de un rango inventado. 'anio' es TEXT porque PubMed a veces trae
    cosas como '2019-2020'; el orden es lexicografico, que con cuatro
    digitos coincide con el cronologico.
    """
    filas = con.execute(
        "SELECT DISTINCT anio FROM documentos "
        "WHERE anio IS NOT NULL AND anio <> '' ORDER BY anio DESC"
    ).fetchall()
    return [f["anio"] for f in filas]


# --------------------------------------------------------------- descargas

def pendientes_descarga(con, tipo, nombre=None, limite=None, reintentar=False):
    """PMIDs sin descarga exitosa de ese tipo.

    Por defecto NO reintenta los marcados 'no_disponible' (no tienen
    acceso abierto; reintentar solo gasta peticiones). Con reintentar=True
    se vuelven a considerar los que fallaron por error tecnico.
    """
    condicion = "dz.pmid IS NULL"
    if reintentar:
        condicion = "(dz.pmid IS NULL OR dz.estatus = 'error')"

    # El LEFT JOIN trae la fila de 'descargas' sea cual sea su estatus; es
    # la condicion de arriba la que decide. Filtrar aqui por estatus dejaria
    # los 'error' fuera del join, o sea pendientes en cada corrida, y haria
    # imposible que se cumpla la condicion de reintentar.
    sql = f"""SELECT DISTINCT d.pmid, d.doi, d.pmcid, d.titulo,
                     (otro.pmid IS NOT NULL) AS ya_hay_texto
                FROM documentos d
                JOIN consulta_documento cd ON cd.pmid = d.pmid
                JOIN consultas c ON c.id = cd.consulta_id
                LEFT JOIN descargas dz
                       ON dz.pmid = d.pmid AND dz.tipo = ?
                LEFT JOIN descargas otro
                       ON otro.pmid = d.pmid AND otro.tipo <> ?
                      AND otro.estatus = 'ok'
               WHERE {condicion}"""
    params = [tipo, tipo]
    if nombre:
        sql += " AND c.nombre = ?"
        params.append(nombre)
    # Primero lo que no tiene texto de ninguna forma. Sin esto la etapa de
    # PDF gasta sus primeras horas en articulos que ya estan en XML, que es
    # el formato mejor: el orden por anio los pone adelante porque lo
    # reciente es lo que mas cubre el subset abierto de PMC. Nada se
    # excluye, solo se atiende primero lo que de verdad falta.
    sql += " ORDER BY ya_hay_texto, d.anio DESC, d.pmid"
    if limite:
        sql += " LIMIT ?"
        params.append(limite)
    return con.execute(sql, params).fetchall()


def pendientes_biblioteca(con, nombre=None):
    """Documentos sin full text de NINGUN tipo, con lo que se intento.

    Es la lista que alguien lleva a la biblioteca. Se exige que falten
    los dos formatos: un articulo con PDF ya esta resuelto para un
    humano, aunque siga sin servir de insumo al clasificador. Son dos
    listas distintas y conviene no confundirlas; la del clasificador es
    'descargas WHERE tipo = xml AND estatus = ok'.

    La 'nota' y la 'url' del ultimo intento viajan con cada fila: son la
    diferencia entre "no existe copia abierta" y "el editor nos nego el
    acceso", y entre las dos cambia lo que hay que pedir.
    """
    sql = """SELECT d.pmid, d.doi, d.anio, d.revista, d.titulo, d.pmcid,
                    dz.nota AS nota, dz.url AS url_intentada
               FROM documentos d
               JOIN consulta_documento cd ON cd.pmid = d.pmid
               JOIN consultas c ON c.id = cd.consulta_id
               LEFT JOIN descargas ok ON ok.pmid = d.pmid
                    AND ok.estatus = 'ok'
               LEFT JOIN descargas dz ON dz.pmid = d.pmid AND dz.tipo = 'pdf'
              WHERE ok.pmid IS NULL"""
    params = []
    if nombre:
        sql += " AND c.nombre = ?"
        params.append(nombre)
    sql += " GROUP BY d.pmid ORDER BY d.anio DESC, d.pmid"
    return con.execute(sql, params).fetchall()


def registrar_descarga(con, pmid, tipo, estatus, fuente=None, ruta=None,
                       tam=None, nota=None, url=None):
    """Registra el resultado de una descarga.

    'url' es de donde salio o de donde saldria el documento. Se guarda
    tambien cuando el resultado es 'no_disponible' o 'error': ahi es
    justamente donde sirve, porque es la liga que alguien va a tener que
    abrir a mano para conseguir el articulo por la biblioteca.
    """
    con.execute(
        """INSERT INTO descargas
             (pmid, tipo, estatus, fuente, ruta, bytes, nota, url, actualizado_en)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(pmid, tipo) DO UPDATE SET
             estatus = excluded.estatus, fuente = excluded.fuente,
             ruta = excluded.ruta, bytes = excluded.bytes,
             nota = excluded.nota, url = excluded.url,
             intentos = descargas.intentos + 1,
             actualizado_en = excluded.actualizado_en""",
        (pmid, tipo, estatus, fuente, ruta, tam, nota, url, ahora()),
    )
    con.commit()


def actualizar_ids(con, pmid, pmcid=None, doi=None):
    """Guarda el PMCID/DOI que resolvio el ID Converter."""
    if pmcid:
        con.execute("UPDATE documentos SET pmcid = ? WHERE pmid = ?", (pmcid, pmid))
    if doi:
        con.execute(
            "UPDATE documentos SET doi = ? WHERE pmid = ? AND (doi IS NULL OR doi = '')",
            (doi, pmid),
        )
    con.commit()


def listar_descargas(con, tipo=None, estatus=None, pagina=1, por_pagina=50):
    """Descargas filtradas y paginadas, con el titulo del documento.

    Devuelve (total, filas). El titulo viene en el JOIN y no en una
    consulta por fila: la lista de descargas es lo que mas se refresca en
    el tablero y pedir cada documento aparte serian cientos de viajes.

    El JOIN no pierde filas ni descuadra el total contra el COUNT: la FK
    descargas.pmid -> documentos.pmid garantiza que el documento existe.
    """
    pagina, por_pagina, desplazamiento = paginado(pagina, por_pagina)

    donde, params = [], []
    if tipo:
        donde.append("dz.tipo = ?")
        params.append(tipo)
    if estatus:
        donde.append("dz.estatus = ?")
        params.append(estatus)
    filtro = (" WHERE " + " AND ".join(donde)) if donde else ""

    total = con.execute(
        "SELECT COUNT(*) c FROM descargas dz" + filtro, params
    ).fetchone()["c"]
    filas = con.execute(
        "SELECT dz.*, d.titulo, d.anio FROM descargas dz"
        " JOIN documentos d ON d.pmid = dz.pmid" + filtro
        + " ORDER BY dz.actualizado_en DESC, dz.pmid LIMIT ? OFFSET ?",
        params + [por_pagina, desplazamiento],
    ).fetchall()
    return total, filas


def borrar_descarga(con, pmid, tipo):
    """Olvida el registro de una descarga. Devuelve True si existia.

    Borra el renglon, no el archivo en disco. Sirve para que un PMID
    marcado 'no_disponible' o 'error' vuelva a salir en
    pendientes_descarga() y se reintente solo, sin tener que correr todo
    el lote con --reintentar.
    """
    cur = con.execute(
        "DELETE FROM descargas WHERE pmid = ? AND tipo = ?", (pmid, tipo)
    )
    con.commit()
    return cur.rowcount > 0


# ----------------------------------------------------------------- resumen

def resumen(con):
    r = {
        "consultas": con.execute("SELECT COUNT(*) c FROM consultas").fetchone()["c"],
        "documentos": con.execute("SELECT COUNT(*) c FROM documentos").fetchone()["c"],
        "con_abstract": con.execute(
            "SELECT COUNT(*) c FROM documentos WHERE tiene_abstract = 1"
        ).fetchone()["c"],
        "vinculos": con.execute(
            "SELECT COUNT(*) c FROM consulta_documento"
        ).fetchone()["c"],
    }
    r["descargas"] = con.execute(
        "SELECT tipo, estatus, COUNT(*) n FROM descargas "
        "GROUP BY tipo, estatus ORDER BY tipo, estatus"
    ).fetchall()
    return r
