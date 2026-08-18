# -*- coding: utf-8 -*-
"""Lo que el tablero le pide a la base: listados, filtros y CRUD.

Estas funciones son las unicas por las que un usuario puede EDITAR o
BORRAR lo que el ETL junto, asi que aqui se prueba sobre todo que no
dejen la base en un estado que ya no se pueda creer: nada de huerfanos,
nada de conteos que mienten, y ningun filtro que devuelva de mas.

La busqueda por texto tiene prueba de inyeccion propia. El tablero corre
en 127.0.0.1, pero el texto llega de una query string y basta con que
alguien pegue una URL ajena; ademas un LIKE armado a mano es de los
errores mas faciles de cometer al agregar un filtro nuevo.
"""

import tempfile
from pathlib import Path

import os

from grn_etl import credenciales, db

from .falsos import PruebaSinRed


class BasePruebaTablero(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.con = db.conectar(":memory:")
        self.addCleanup(self.con.close)

    def cuenta(self, sql, params=()):
        return self.con.execute(sql, params).fetchone()[0]

    def sin_huerfanos(self):
        """PRAGMA foreign_key_check lista toda fila que apunte a la nada."""
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])


# --------------------------------------------------------------- conexion

class PruebasWal(PruebaSinRed):

    def test_wal_no_truena_con_una_base_en_memoria(self):
        """':memory:' no puede usar WAL y responde 'memory'. Las 101
        pruebas que ya existen abren asi la base: si conectar() se pusiera
        exigente con el PRAGMA, se caeria la suite entera."""
        con = db.conectar(":memory:")
        self.addCleanup(con.close)

        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "memory")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0], 0)

    def test_wal_queda_activo_en_una_base_de_archivo(self):
        """Sin WAL el tablero leyendo bloquea al ETL escribiendo y sale
        'database is locked' a media corrida."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        con = db.conectar(str(Path(tmp.name) / "grn.db"))
        self.addCleanup(con.close)

        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_hay_espera_antes_de_declarar_la_base_bloqueada(self):
        """WAL no cubre dos escritores. Un borrado desde el tablero
        durante una ingesta debe esperar, no fallar al instante."""
        con = db.conectar(":memory:")
        self.addCleanup(con.close)

        self.assertGreater(con.execute("PRAGMA busy_timeout").fetchone()[0], 0)


# ------------------------------------------------------ listar documentos

class PruebasListarDocumentos(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        db.guardar_documentos(self.con, [
            {"pmid": "1001", "titulo": "Regulacion de lasR en biofilm",
             "abstract": "LasR activa a rhlR.", "anio": "2021"},
            {"pmid": "1002", "titulo": "Represion por MexT",
             "abstract": "MexT reprime a mexEF-oprN.", "anio": "2020"},
            {"pmid": "1003", "titulo": "Factor sigma RpoS",
             "abstract": "", "anio": "2020"},
            {"pmid": "1004", "titulo": "Quorum sensing",
             "abstract": "Sin genes citados.", "anio": "2019"},
            {"pmid": "1005", "titulo": "Sin anio", "abstract": "x", "anio": ""},
        ])
        self.pa, _ = db.alta_consulta(self.con, "pa", "q1")
        self.otra, _ = db.alta_consulta(self.con, "otra", "q2")
        db.vincular(self.con, self.pa, ["1001", "1002", "1003"])
        db.vincular(self.con, self.otra, ["1001"])

    def pmids(self, **kw):
        _, filas = db.listar_documentos(self.con, **kw)
        return [f["pmid"] for f in filas]

    def test_el_total_es_de_todo_el_filtro_y_las_filas_solo_de_la_pagina(self):
        """Si 'total' contara solo la pagina, el tablero no podria dibujar
        el paginador."""
        total, filas = db.listar_documentos(self.con, pagina=1, por_pagina=2)

        self.assertEqual(total, 5)
        self.assertEqual(len(filas), 2)

    def test_las_paginas_no_se_enciman_ni_dejan_huecos(self):
        paginas = [self.pmids(pagina=n, por_pagina=2) for n in (1, 2, 3)]
        vistos = [p for pagina in paginas for p in pagina]

        self.assertEqual([len(p) for p in paginas], [2, 2, 1])
        self.assertEqual(sorted(vistos), ["1001", "1002", "1003", "1004", "1005"])

    def test_una_pagina_pasada_del_final_no_pierde_el_total(self):
        total, filas = db.listar_documentos(self.con, pagina=9, por_pagina=2)

        self.assertEqual(total, 5)
        self.assertEqual(filas, [])

    def test_paginacion_absurda_se_normaliza_en_vez_de_tronar(self):
        """Los valores llegan de una URL. Un pagina=0 o negativo cae en la
        primera pagina, y un por_pagina vacio en el tamano por omision;
        ninguno de los dos puede reventar la peticion."""
        self.assertEqual(self.pmids(pagina=0, por_pagina=2),
                         self.pmids(pagina=1, por_pagina=2))
        self.assertEqual(self.pmids(pagina=-3, por_pagina=2),
                         self.pmids(pagina=1, por_pagina=2))
        self.assertEqual(len(self.pmids(por_pagina=0)), 1)
        self.assertEqual(len(self.pmids(por_pagina="0")), 1)
        self.assertEqual(len(self.pmids(por_pagina="")), 5)

    def test_la_paginacion_acepta_los_numeros_como_cadena(self):
        """La query string entrega cadenas; que db no las convierta
        obligaria a la capa HTTP a saber que aqui son enteros."""
        total, filas = db.listar_documentos(self.con, pagina="2", por_pagina="2")

        self.assertEqual(total, 5)
        self.assertEqual([f["pmid"] for f in filas], ["1003", "1004"])

    def test_por_pagina_tiene_tope(self):
        """Un por_pagina de seis cifras en la URL traeria la tabla entera a
        memoria en cada refresco."""
        db.guardar_documentos(
            self.con, [{"pmid": str(9000 + i)} for i in range(600)])

        total, filas = db.listar_documentos(self.con, por_pagina=999999)

        self.assertEqual(total, 605)
        self.assertEqual(len(filas), 500)

    def test_ordena_por_anio_descendente_y_luego_por_pmid(self):
        self.assertEqual(self.pmids(),
                         ["1001", "1002", "1003", "1004", "1005"])

    def test_la_busqueda_mira_titulo_abstract_y_pmid(self):
        self.assertEqual(self.pmids(texto="biofilm"), ["1001"])       # titulo
        self.assertEqual(self.pmids(texto="mexEF"), ["1002"])         # abstract
        self.assertEqual(self.pmids(texto="1004"), ["1004"])          # pmid

    def test_la_busqueda_por_texto_no_es_vulnerable_a_inyeccion(self):
        """El clasico. Si el termino se concatenara al SQL, el OR '1'='1'
        haria verdadera la condicion y devolveria la tabla completa."""
        total, filas = db.listar_documentos(self.con, texto="%' OR '1'='1")

        self.assertEqual(total, 0)
        self.assertEqual(filas, [])

    def test_un_termino_con_drop_table_no_borra_nada(self):
        db.listar_documentos(self.con, texto="'; DROP TABLE documentos; --")

        self.assertEqual(self.cuenta("SELECT COUNT(*) FROM documentos"), 5)

    def test_los_comodines_del_usuario_se_buscan_literales(self):
        """Un '%' o un '_' tecleados son parte de lo que se busca. Sin
        escaparlos, buscar '%' traeria los cinco documentos."""
        db.guardar_documentos(self.con, [
            {"pmid": "2001", "titulo": "100% de identidad", "anio": "2022"},
            {"pmid": "2002", "titulo": "Locus PA_0762", "anio": "2022"},
        ])

        self.assertEqual(self.pmids(texto="%"), ["2001"])
        self.assertEqual(self.pmids(texto="_"), ["2002"])

    def test_filtra_por_consulta_sin_duplicar_documentos_compartidos(self):
        """1001 esta en dos consultas. El join no puede hacerlo aparecer
        dos veces: seria contar de mas justo el caso que este diseno
        existe para permitir."""
        total, filas = db.listar_documentos(self.con, consulta="pa")

        self.assertEqual(total, 3)
        self.assertEqual([f["pmid"] for f in filas], ["1001", "1002", "1003"])
        self.assertEqual(self.pmids(consulta="otra"), ["1001"])

    def test_una_consulta_sin_documentos_no_devuelve_nada(self):
        db.alta_consulta(self.con, "vacia", "q3")

        self.assertEqual(db.listar_documentos(self.con, consulta="vacia"), (0, []))

    def test_filtra_por_anio(self):
        self.assertEqual(self.pmids(anio="2020"), ["1002", "1003"])

    def test_filtra_por_tener_o_no_abstract(self):
        self.assertEqual(self.pmids(con_abstract=True),
                         ["1001", "1002", "1004", "1005"])
        self.assertEqual(self.pmids(con_abstract=False), ["1003"])

    def test_los_filtros_se_combinan(self):
        self.assertEqual(
            self.pmids(consulta="pa", anio="2020", con_abstract=True), ["1002"])


# ----------------------------------------------------- obtener y actualizar

class PruebasDocumentoIndividual(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        db.guardar_documentos(self.con, [{
            "pmid": "1001", "titulo": "Titulo viejo", "abstract": "Hay texto.",
            "anio": "2020", "doi": "10.1/a", "revista": "J Bacteriol",
            "autores": ["Ramos JL"],
        }])

    def campo(self, columna, pmid="1001"):
        return self.con.execute(
            "SELECT " + columna + " FROM documentos WHERE pmid = ?", (pmid,)
        ).fetchone()[0]

    def test_obtener_un_documento_que_no_existe_es_none(self):
        self.assertIsNone(db.obtener_documento(self.con, "9999"))

    def test_obtener_devuelve_las_listas_todavia_como_json(self):
        """a_dict() es quien deserializa; obtener_documento entrega la
        fila cruda para no duplicar esa logica."""
        fila = db.obtener_documento(self.con, "1001")

        self.assertEqual(db.a_dict(fila)["autores"], ["Ramos JL"])

    def test_actualiza_las_columnas_de_la_lista_blanca(self):
        cambio = db.actualizar_documento(self.con, "1001", {
            "titulo": "Titulo corregido", "revista": "Mol Microbiol"})

        self.assertTrue(cambio)
        self.assertEqual(self.campo("titulo"), "Titulo corregido")
        self.assertEqual(self.campo("revista"), "Mol Microbiol")

    def test_las_columnas_fuera_de_la_lista_blanca_se_ignoran(self):
        """El tablero devuelve el formulario completo. Que traiga pmid o
        extraido_en no debe permitirle reescribir la identidad ni la
        bitacora del documento."""
        extraido = self.campo("extraido_en")

        db.actualizar_documento(self.con, "1001", {
            "titulo": "Titulo corregido", "pmid": "9999",
            "extraido_en": "1999-01-01T00:00:00+00:00", "tiene_abstract": 0,
            "columna_inventada": "x",
        })

        self.assertEqual(self.campo("titulo"), "Titulo corregido")
        self.assertIsNotNone(db.obtener_documento(self.con, "1001"))
        self.assertIsNone(db.obtener_documento(self.con, "9999"))
        self.assertEqual(self.campo("extraido_en"), extraido)
        self.assertEqual(self.campo("tiene_abstract"), 1)

    def test_vaciar_el_abstract_recalcula_tiene_abstract(self):
        """Si no se recalcula, el resumen del tablero sigue contando el
        documento como que tiene abstract y el conteo miente."""
        db.actualizar_documento(self.con, "1001", {"abstract": ""})

        self.assertEqual(self.campo("tiene_abstract"), 0)
        self.assertEqual(db.resumen(self.con)["con_abstract"], 0)

    def test_escribir_un_abstract_tambien_recalcula(self):
        db.guardar_documentos(self.con, [{"pmid": "1002", "abstract": ""}])

        db.actualizar_documento(self.con, "1002", {"abstract": "Ya hay texto."})

        self.assertEqual(self.campo("tiene_abstract", "1002"), 1)
        self.assertEqual(db.resumen(self.con)["con_abstract"], 2)

    def test_sin_ninguna_columna_valida_no_toca_la_fila(self):
        cambio = db.actualizar_documento(self.con, "1001", {"pmid": "9999"})

        self.assertFalse(cambio)
        self.assertEqual(self.campo("titulo"), "Titulo viejo")

    def test_actualizar_un_pmid_inexistente_devuelve_false(self):
        """Asi la capa HTTP puede contestar 404 sin consultar antes."""
        self.assertFalse(
            db.actualizar_documento(self.con, "9999", {"titulo": "x"}))


# ------------------------------------------------------- borrar documentos

class PruebasBorrarDocumento(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        self.pa, _ = db.alta_consulta(self.con, "pa", "q1")
        self.otra, _ = db.alta_consulta(self.con, "otra", "q2")
        db.guardar_documentos(self.con,
                              [{"pmid": "1001"}, {"pmid": "1002"}])
        db.vincular(self.con, self.pa, ["1001", "1002"])
        db.vincular(self.con, self.otra, ["1001"])
        db.registrar_descarga(self.con, "1001", "xml", "ok", ruta="/x.xml")
        db.registrar_descarga(self.con, "1001", "pdf", "no_disponible")
        db.registrar_descarga(self.con, "1002", "xml", "ok")

    def test_devuelve_cuanto_se_llevo_por_delante(self):
        """Borrar un documento rompe trazabilidad. Lo minimo es decir de
        cuantas consultas y cuantas descargas se lo llevo."""
        borrados = db.borrar_documento(self.con, "1001")

        self.assertEqual(borrados, {"vinculos": 2, "descargas": 2})

    def test_no_deja_huerfanos(self):
        db.borrar_documento(self.con, "1001")

        self.sin_huerfanos()
        self.assertEqual(
            self.cuenta("SELECT COUNT(*) FROM consulta_documento WHERE pmid='1001'"), 0)
        self.assertEqual(
            self.cuenta("SELECT COUNT(*) FROM descargas WHERE pmid='1001'"), 0)
        self.assertIsNone(db.obtener_documento(self.con, "1001"))

    def test_no_toca_a_los_demas_documentos(self):
        db.borrar_documento(self.con, "1001")

        self.assertIsNotNone(db.obtener_documento(self.con, "1002"))
        self.assertEqual(
            self.cuenta("SELECT COUNT(*) FROM consulta_documento WHERE pmid='1002'"), 1)
        self.assertEqual(
            self.cuenta("SELECT COUNT(*) FROM descargas WHERE pmid='1002'"), 1)

    def test_las_consultas_siguen_existiendo(self):
        """Se borra un articulo, no la consulta que lo trajo."""
        db.borrar_documento(self.con, "1001")

        self.assertEqual(len(db.listar_consultas(self.con)), 2)

    def test_borrar_uno_que_no_existe_no_truena(self):
        self.assertEqual(db.borrar_documento(self.con, "9999"),
                         {"vinculos": 0, "descargas": 0})


# -------------------------------------------------------- borrar consultas

class PruebasBorrarConsulta(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        self.pa, _ = db.alta_consulta(self.con, "pa", "q1")
        self.otra, _ = db.alta_consulta(self.con, "otra", "q2")
        db.guardar_documentos(self.con, [
            {"pmid": "1001"}, {"pmid": "1002"}, {"pmid": "1003"}])
        e1 = db.abrir_ejecucion(self.con, self.pa)
        db.cerrar_ejecucion(self.con, e1, "ok")
        e2 = db.abrir_ejecucion(self.con, self.pa)
        db.cerrar_ejecucion(self.con, e2, "ok")
        e3 = db.abrir_ejecucion(self.con, self.otra)
        db.cerrar_ejecucion(self.con, e3, "ok")
        # 1001 lo comparten las dos consultas; 1003 solo lo trajo 'pa'.
        db.vincular(self.con, self.pa, ["1001", "1003"], e2)
        db.vincular(self.con, self.otra, ["1001", "1002"], e3)

    def test_devuelve_vinculos_y_ejecuciones_borrados(self):
        self.assertEqual(db.borrar_consulta(self.con, self.pa),
                         {"vinculos": 2, "ejecuciones": 2})

    def test_no_borra_un_documento_que_otra_consulta_usa(self):
        """1001 tambien lo trajo 'otra'. Borrarlo obligaria a bajarlo de
        nuevo, que es justo lo que este proyecto existe para evitar."""
        db.borrar_consulta(self.con, self.pa)

        self.assertIsNotNone(db.obtener_documento(self.con, "1001"))
        self.assertEqual(
            [f["pmid"] for f in db.documentos_de_consulta(self.con, "otra")],
            ["1001", "1002"])

    def test_tampoco_borra_el_documento_que_se_queda_sin_consulta(self):
        """1003 queda sin vinculo. Sigue siendo trabajo ya descargado y se
        sigue viendo en el listado; volver a bajarlo costaria trafico."""
        db.borrar_consulta(self.con, self.pa)

        self.assertIsNotNone(db.obtener_documento(self.con, "1003"))
        self.assertEqual(db.resumen(self.con)["documentos"], 3)
        self.assertIn("1003",
                      [f["pmid"] for f in db.listar_documentos(self.con)[1]])

    def test_la_base_queda_consistente(self):
        db.borrar_consulta(self.con, self.pa)

        self.sin_huerfanos()
        self.assertEqual([c["nombre"] for c in db.listar_consultas(self.con)],
                         ["otra"])
        self.assertEqual(len(db.historial(self.con)), 1)

    def test_borrar_una_consulta_inexistente_no_truena(self):
        self.assertEqual(db.borrar_consulta(self.con, 999),
                         {"vinculos": 0, "ejecuciones": 0})
        self.assertEqual(len(db.listar_consultas(self.con)), 2)


# ------------------------------------------------- una consulta por su id

class PruebasConsultaPorId(BasePruebaTablero):
    """El tablero se refiere a una consulta por id en /api/consultas/<id>.

    Antes esa resolucion se hacia recorriendo listar_consultas() en Python,
    que calcula dos subconsultas correlacionadas POR CONSULTA registrada:
    con cuarenta dadas de alta eran ochenta para quedarse con una fila.
    """

    def setUp(self):
        super().setUp()
        self.pa, _ = db.alta_consulta(self.con, "pa", "lasR", "quorum sensing")
        self.otra, _ = db.alta_consulta(self.con, "otra", "mexT")

    def test_trae_la_consulta_del_id_pedido_y_no_otra(self):
        fila = db.obtener_consulta_por_id(self.con, self.pa)

        self.assertEqual(fila["nombre"], "pa")
        self.assertEqual(fila["texto"], "lasR")
        self.assertEqual(fila["descripcion"], "quorum sensing")
        self.assertEqual(
            db.obtener_consulta_por_id(self.con, self.otra)["nombre"], "otra")

    def test_un_id_que_no_existe_es_none(self):
        """Asi la capa HTTP contesta 404 sin recorrer nada."""
        self.assertIsNone(db.obtener_consulta_por_id(self.con, 9999))

    def test_devuelve_la_misma_fila_que_buscar_por_nombre(self):
        """Dos caminos a la misma consulta no pueden dar cosas distintas."""
        por_id = db.obtener_consulta_por_id(self.con, self.pa)
        por_nombre = db.obtener_consulta(self.con, "pa")

        self.assertEqual(dict(por_id), dict(por_nombre))

    def test_el_id_borrado_deja_de_encontrarse(self):
        db.borrar_consulta(self.con, self.pa)

        self.assertIsNone(db.obtener_consulta_por_id(self.con, self.pa))


# ----------------------------------------------- conteos antes de borrar

class PruebasConteosConsulta(BasePruebaTablero):
    """Lo que cuelga de una consulta, para advertirlo antes del borrado."""

    def setUp(self):
        super().setUp()
        self.pa, _ = db.alta_consulta(self.con, "pa", "q1")
        self.otra, _ = db.alta_consulta(self.con, "otra", "q2")
        db.guardar_documentos(self.con, [
            {"pmid": "1001"}, {"pmid": "1002"}, {"pmid": "1003"}])
        db.vincular(self.con, self.pa, ["1001", "1002", "1003"])
        db.vincular(self.con, self.otra, ["1001"])
        for _ in range(3):
            db.cerrar_ejecucion(
                self.con, db.abrir_ejecucion(self.con, self.pa), "ok")
        db.cerrar_ejecucion(
            self.con, db.abrir_ejecucion(self.con, self.otra), "error")

    def test_cuenta_vinculos_y_ejecuciones_de_esa_consulta(self):
        self.assertEqual(db.conteos_consulta(self.con, self.pa),
                         {"vinculos": 3, "ejecuciones": 3})

    def test_no_cuenta_lo_de_las_demas_consultas(self):
        """1001 esta en las dos. Contarlo aqui inflaria la advertencia y
        haria creer que se borra el doble."""
        self.assertEqual(db.conteos_consulta(self.con, self.otra),
                         {"vinculos": 1, "ejecuciones": 1})

    def test_una_consulta_recien_creada_cuenta_cero(self):
        vacia, _ = db.alta_consulta(self.con, "vacia", "q3")

        self.assertEqual(db.conteos_consulta(self.con, vacia),
                         {"vinculos": 0, "ejecuciones": 0})

    def test_un_id_inexistente_cuenta_cero_en_vez_de_tronar(self):
        self.assertEqual(db.conteos_consulta(self.con, 9999),
                         {"vinculos": 0, "ejecuciones": 0})

    def test_lo_que_anuncia_es_exactamente_lo_que_el_borrado_se_lleva(self):
        """Es la razon de ser de la funcion: mismas llaves y mismas tablas
        que borrar_consulta(). Si los dos numeros no coinciden, la
        confirmacion que el usuario acepto no era cierta."""
        anunciado = db.conteos_consulta(self.con, self.pa)

        self.assertEqual(db.borrar_consulta(self.con, self.pa), anunciado)

    def test_cuenta_mas_alla_de_cualquier_pagina_de_la_bitacora(self):
        """El defecto que dio origen a esta funcion: el tablero contaba las
        ejecuciones pidiendo hasta 1000 renglones y midiendo el largo del
        arreglo. Con 1200 registradas el dialogo decia 1000 y el borrado se
        llevaba 1200. Un COUNT no tiene ese techo."""
        self.con.executemany(
            "INSERT INTO ejecuciones (consulta_id, iniciada_en, estatus) "
            "VALUES (?, ?, 'ok')",
            [(self.pa, db.ahora()) for _ in range(1200)])
        self.con.commit()

        conteos = db.conteos_consulta(self.con, self.pa)

        self.assertEqual(conteos["ejecuciones"], 1203)
        self.assertEqual(db.borrar_consulta(self.con, self.pa), conteos)


# ------------------------------------------------- el error de la base

class PruebasErrorBase(BasePruebaTablero):
    """db.ErrorBase existe para que nadie mas importe el motor.

    servidor.py atrapa esta excepcion sin saber que hay sqlite3 debajo. El
    dia de Postgres se reapunta el alias en db.py y ninguna otra capa se
    entera, que es lo que promete migracion-servicio.md.
    """

    def test_una_operacion_que_falla_lanza_errorbase(self):
        with self.assertRaises(db.ErrorBase):
            self.con.execute("SELECT * FROM tabla_que_no_existe")

    def test_cubre_las_violaciones_de_llave_foranea(self):
        """El caso realista del tablero: vincular a una consulta que no
        existe. La capa HTTP lo traduce a 500 sin mirar el motor."""
        db.guardar_documentos(self.con, [{"pmid": "1001"}])

        with self.assertRaises(db.ErrorBase):
            self.con.execute(
                "INSERT INTO consulta_documento "
                "(consulta_id, pmid, vinculado_en) VALUES (?, ?, ?)",
                (9999, "1001", db.ahora()))


# --------------------------------------------------- actualizar consultas

class PruebasActualizarConsulta(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        self.cid, _ = db.alta_consulta(self.con, "pa", "lasR", "descripcion vieja")

    def fila(self):
        return self.con.execute(
            "SELECT * FROM consultas WHERE id = ?", (self.cid,)).fetchone()

    def test_none_significa_no_tocar_ese_campo(self):
        """El tablero manda solo lo que el usuario edito; un campo ausente
        no puede vaciar la query booleana."""
        self.assertTrue(
            db.actualizar_consulta(self.con, self.cid, descripcion="nueva"))

        self.assertEqual(self.fila()["texto"], "lasR")
        self.assertEqual(self.fila()["descripcion"], "nueva")

    def test_la_cadena_vacia_si_limpia_la_descripcion(self):
        db.actualizar_consulta(self.con, self.cid, descripcion="")

        self.assertEqual(self.fila()["descripcion"], "")

    def test_activa_se_guarda_como_entero(self):
        db.actualizar_consulta(self.con, self.cid, activa=False)
        self.assertEqual(self.fila()["activa"], 0)

        db.actualizar_consulta(self.con, self.cid, activa=True)
        self.assertEqual(self.fila()["activa"], 1)

    def test_cambiar_el_texto_no_tira_los_documentos_ya_vinculados(self):
        """Afinar una query desde el tablero no puede tirar el trabajo
        hecho, igual que no lo tira alta_consulta()."""
        db.guardar_documentos(self.con, [{"pmid": "1001"}])
        db.vincular(self.con, self.cid, ["1001"])

        db.actualizar_consulta(self.con, self.cid, texto="lasR OR rhlR")

        self.assertEqual(self.fila()["texto"], "lasR OR rhlR")
        self.assertEqual(len(db.documentos_de_consulta(self.con, "pa")), 1)

    def test_el_nombre_no_se_puede_cambiar_por_aqui(self):
        db.actualizar_consulta(self.con, self.cid, texto="otra cosa")

        self.assertEqual(self.fila()["nombre"], "pa")

    def test_sin_campos_o_con_id_inexistente_devuelve_false(self):
        self.assertFalse(db.actualizar_consulta(self.con, self.cid))
        self.assertFalse(db.actualizar_consulta(self.con, 999, texto="x"))


# -------------------------------------------------------------- descargas

class PruebasListarDescargas(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        db.guardar_documentos(self.con, [
            {"pmid": "1001", "titulo": "Regulacion de lasR", "anio": "2021"},
            {"pmid": "1002", "titulo": "Represion por MexT", "anio": "2020"},
            {"pmid": "1003", "titulo": "Factor sigma RpoS", "anio": "2019"},
        ])
        db.registrar_descarga(self.con, "1001", "xml", "ok", ruta="/1001.xml")
        db.registrar_descarga(self.con, "1002", "xml", "error", nota="timeout")
        db.registrar_descarga(self.con, "1003", "xml", "no_disponible")
        db.registrar_descarga(self.con, "1001", "pdf", "ok", ruta="/1001.pdf")

    def test_trae_el_titulo_del_documento(self):
        """El tablero no puede pedir cada documento por separado en cada
        refresco de la lista."""
        _, filas = db.listar_descargas(self.con, tipo="pdf")

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["titulo"], "Regulacion de lasR")
        self.assertEqual(filas[0]["ruta"], "/1001.pdf")

    def test_filtra_por_tipo(self):
        total, filas = db.listar_descargas(self.con, tipo="xml")

        self.assertEqual(total, 3)
        self.assertEqual({f["pmid"] for f in filas}, {"1001", "1002", "1003"})

    def test_filtra_por_estatus(self):
        total, filas = db.listar_descargas(self.con, estatus="ok")

        self.assertEqual(total, 2)
        self.assertEqual({f["tipo"] for f in filas}, {"xml", "pdf"})

    def test_combina_tipo_y_estatus(self):
        total, filas = db.listar_descargas(self.con, tipo="xml", estatus="error")

        self.assertEqual(total, 1)
        self.assertEqual(filas[0]["pmid"], "1002")

    def test_el_total_es_del_filtro_completo_no_de_la_pagina(self):
        total, filas = db.listar_descargas(self.con, por_pagina=2)

        self.assertEqual(total, 4)
        self.assertEqual(len(filas), 2)

    def test_sin_descargas_devuelve_cero_y_lista_vacia(self):
        self.assertEqual(db.listar_descargas(self.con, tipo="epub"), (0, []))


class PruebasBorrarDescarga(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        cid, _ = db.alta_consulta(self.con, "pa", "q1")
        db.guardar_documentos(self.con, [{"pmid": "1001", "pmcid": "PMC1"}])
        db.vincular(self.con, cid, ["1001"])
        db.registrar_descarga(self.con, "1001", "xml", "no_disponible")
        db.registrar_descarga(self.con, "1001", "pdf", "ok", ruta="/1001.pdf")

    def test_borrar_el_registro_devuelve_el_pmid_a_pendientes(self):
        """Es para lo que sirve: un 'no_disponible' no se reintenta nunca,
        y a veces el articulo si aparecio en PMC despues. Borrar la fila
        lo vuelve a poner en la cola sin correr todo con --reintentar."""
        self.assertEqual(db.pendientes_descarga(self.con, "xml"), [])

        self.assertTrue(db.borrar_descarga(self.con, "1001", "xml"))

        pendientes = db.pendientes_descarga(self.con, "xml")
        self.assertEqual([f["pmid"] for f in pendientes], ["1001"])

    def test_solo_borra_el_tipo_pedido(self):
        db.borrar_descarga(self.con, "1001", "xml")

        _, filas = db.listar_descargas(self.con)
        self.assertEqual([f["tipo"] for f in filas], ["pdf"])

    def test_borrar_una_que_no_existe_devuelve_false(self):
        """Asi la capa HTTP contesta 404 sin consultar antes."""
        self.assertFalse(db.borrar_descarga(self.con, "1001", "epub"))
        self.assertFalse(db.borrar_descarga(self.con, "9999", "xml"))


# ------------------------------------------------------ ejecuciones y anios

class PruebasEjecucionYAnios(BasePruebaTablero):

    def test_obtener_ejecucion_trae_el_nombre_de_la_consulta(self):
        """El tablero sondea por id y muestra a que consulta pertenece,
        sin tener que pedir la consulta aparte."""
        cid, _ = db.alta_consulta(self.con, "pa", "q1")
        eid = db.abrir_ejecucion(self.con, cid)
        db.cerrar_ejecucion(self.con, eid, "ok", total_pubmed=42, pmids_nuevos=7)

        fila = db.obtener_ejecucion(self.con, eid)

        self.assertEqual(fila["consulta"], "pa")
        self.assertEqual(fila["estatus"], "ok")
        self.assertEqual(fila["total_pubmed"], 42)
        self.assertEqual(fila["pmids_nuevos"], 7)
        self.assertIsNotNone(fila["terminada_en"])

    def test_una_ejecucion_que_no_existe_es_none(self):
        self.assertIsNone(db.obtener_ejecucion(self.con, 999))

    def test_anios_sin_repetir_del_mas_nuevo_al_mas_viejo(self):
        db.guardar_documentos(self.con, [
            {"pmid": "1001", "anio": "2020"}, {"pmid": "1002", "anio": "2023"},
            {"pmid": "1003", "anio": "2020"}, {"pmid": "1004", "anio": "2019"},
        ])

        self.assertEqual(db.anios_disponibles(self.con), ["2023", "2020", "2019"])

    def test_los_documentos_sin_anio_no_ensucian_el_filtro(self):
        """PubMed no siempre trae anio. Un '' en el desplegable del
        tablero no filtra nada y confunde."""
        db.guardar_documentos(self.con, [
            {"pmid": "1001", "anio": ""}, {"pmid": "1002", "anio": "2021"}])
        self.con.execute("UPDATE documentos SET anio = NULL WHERE pmid = '1001'")

        self.assertEqual(db.anios_disponibles(self.con), ["2021"])

    def test_una_base_vacia_devuelve_lista_vacia(self):
        self.assertEqual(db.anios_disponibles(self.con), [])


class PruebasPendientesBiblioteca(BasePruebaTablero):
    """La lista que alguien lleva a la biblioteca.

    No es la misma que la del clasificador: un articulo con PDF ya esta
    resuelto para un humano aunque siga sin servir de insumo al pipeline.
    """

    def setUp(self):
        super().setUp()
        self.cid, _ = db.alta_consulta(self.con, "pa", "q")
        db.guardar_documentos(self.con, [
            {"pmid": "111", "anio": "2020", "titulo": "Con XML"},
            {"pmid": "222", "anio": "2019", "titulo": "Solo PDF"},
            {"pmid": "333", "anio": "2018", "titulo": "Con nada"},
        ])
        db.vincular(self.con, self.cid, ["111", "222", "333"])
        db.registrar_descarga(self.con, "111", "xml", "ok", ruta="/x.txt")
        db.registrar_descarga(self.con, "222", "pdf", "ok", ruta="/x.pdf")
        db.registrar_descarga(self.con, "333", "pdf", "no_disponible",
                              nota="el editor nego el acceso",
                              url="https://editor.com/333")

    def pmids(self, **kw):
        return [f["pmid"] for f in db.pendientes_biblioteca(self.con, **kw)]

    def test_un_documento_con_xml_no_es_pendiente(self):
        self.assertNotIn("111", self.pmids())

    def test_un_documento_con_pdf_tampoco_es_pendiente(self):
        """Antes el filtro miraba solo el XML, asi que un articulo con PDF
        ya bajado seguia saliendo en la lista de la biblioteca."""
        self.assertNotIn("222", self.pmids())

    def test_el_que_no_tiene_nada_si_es_pendiente(self):
        self.assertEqual(self.pmids(), ["333"])

    def test_viaja_la_razon_y_la_liga_del_ultimo_intento(self):
        """Sin la nota, quien lleva el CSV no sabe si el articulo no existe
        abierto o si el editor lo bloqueo, que se piden distinto."""
        fila = db.pendientes_biblioteca(self.con)[0]

        self.assertEqual(fila["nota"], "el editor nego el acceso")
        self.assertEqual(fila["url_intentada"], "https://editor.com/333")

    def test_se_puede_acotar_a_una_consulta(self):
        otra, _ = db.alta_consulta(self.con, "otra", "q2")
        db.guardar_documentos(self.con, [{"pmid": "444", "anio": "2017"}])
        db.vincular(self.con, otra, ["444"])

        self.assertEqual(self.pmids(nombre="otra"), ["444"])
        self.assertNotIn("444", self.pmids(nombre="pa"))

    def test_un_documento_en_dos_consultas_no_se_duplica(self):
        otra, _ = db.alta_consulta(self.con, "otra", "q2")
        db.vincular(self.con, otra, ["333"])

        self.assertEqual(self.pmids().count("333"), 1)


class PruebasCoberturaTexto(BasePruebaTablero):
    """"Cuantos documentos hay" y "cuanto sirve para el clasificador" son
    preguntas distintas, y confundirlas es el error que esta funcion existe
    para evitar."""

    def setUp(self):
        super().setUp()
        self.cid, _ = db.alta_consulta(self.con, "pa", "q")

    def sembrar(self, *docs):
        db.guardar_documentos(self.con, list(docs))
        db.vincular(self.con, self.cid, [d["pmid"] for d in docs])

    def test_las_tres_categorias_suman_el_total(self):
        """Cada documento cae en exactamente una: si no suman, alguna
        condicion se solapa o deja un hueco."""
        self.sembrar({"pmid": "111", "abstract": "hay"},
                     {"pmid": "222", "abstract": "hay"},
                     {"pmid": "333", "abstract": ""},
                     {"pmid": "444", "abstract": "hay"})
        db.registrar_descarga(self.con, "111", "xml", "ok", ruta="/a.txt")

        c = db.cobertura_texto(self.con)

        self.assertEqual(c["completo"] + c["solo_abstract"] + c["sin_texto"],
                         c["total"])
        self.assertEqual(c, {"total": 4, "completo": 1,
                             "solo_abstract": 2, "sin_texto": 1})

    def test_un_documento_con_los_dos_formatos_se_cuenta_una_vez(self):
        self.sembrar({"pmid": "111", "abstract": "hay"})
        db.registrar_descarga(self.con, "111", "xml", "ok", ruta="/a.txt")
        db.registrar_descarga(self.con, "111", "pdf", "ok", ruta="/a.pdf")

        c = db.cobertura_texto(self.con)

        self.assertEqual(c["completo"], 1)
        self.assertEqual(c["total"], 1)

    def test_un_pdf_sin_xml_tambien_cuenta_como_texto_completo(self):
        """Hoy no pasa, pero la condicion se escribe sobre el estatus y no
        sobre el tipo justamente para que el dia que pase, cuente."""
        self.sembrar({"pmid": "111", "abstract": "hay"})
        db.registrar_descarga(self.con, "111", "pdf", "ok", ruta="/a.pdf")

        self.assertEqual(db.cobertura_texto(self.con)["completo"], 1)

    def test_una_descarga_fallida_no_cuenta_como_texto(self):
        self.sembrar({"pmid": "111", "abstract": "hay"})
        db.registrar_descarga(self.con, "111", "xml", "no_disponible")

        c = db.cobertura_texto(self.con)

        self.assertEqual(c["completo"], 0)
        self.assertEqual(c["solo_abstract"], 1)

    def test_una_base_vacia_no_truena(self):
        self.assertEqual(db.cobertura_texto(self.con),
                         {"total": 0, "completo": 0,
                          "solo_abstract": 0, "sin_texto": 0})


class PruebasDescargasDe(BasePruebaTablero):

    def setUp(self):
        super().setUp()
        cid, _ = db.alta_consulta(self.con, "pa", "q")
        db.guardar_documentos(self.con, [{"pmid": "111"}])
        db.vincular(self.con, cid, ["111"])

    def test_devuelve_lo_que_hace_falta_para_saber_que_se_puede_abrir(self):
        db.registrar_descarga(self.con, "111", "xml", "ok", fuente="PMC",
                              ruta="/a.txt", tam=1234)

        filas = db.descargas_de(self.con, "111")

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["tipo"], "xml")
        self.assertEqual(filas[0]["estatus"], "ok")
        self.assertEqual(filas[0]["bytes"], 1234)

    def test_no_devuelve_la_ruta_del_disco(self):
        """Quien sirve un archivo arma su ruta desde el pmid validado y la
        convencion de nombres, nunca desde una cadena guardada. Mandarla al
        navegador solo invita a que alguien la use para eso."""
        db.registrar_descarga(self.con, "111", "pdf", "ok", ruta="/secreto/a.pdf")

        self.assertNotIn("ruta", db.descargas_de(self.con, "111")[0])

    def test_trae_la_nota_que_explica_por_que_no_hay_nada(self):
        db.registrar_descarga(self.con, "111", "pdf", "no_disponible",
                              nota="el editor nego el acceso",
                              url="https://editor/111")

        fila = db.descargas_de(self.con, "111")[0]

        self.assertEqual(fila["nota"], "el editor nego el acceso")
        self.assertEqual(fila["url"], "https://editor/111")

    def test_un_documento_sin_descargas_devuelve_lista_vacia(self):
        self.assertEqual(db.descargas_de(self.con, "111"), [])

    def test_un_pmid_que_no_existe_devuelve_lista_vacia(self):
        self.assertEqual(db.descargas_de(self.con, "999"), [])


class PruebasCredenciales(PruebaSinRed):
    """De donde salen el correo y la llave, y que se rechaza al guardar."""

    def setUp(self):
        super().setUp()
        import tempfile, unittest.mock
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        for nombre, valor in (("ARCHIVO_LLAVE", raiz / ".key"),
                              ("ARCHIVO_CORREO", raiz / ".correo")):
            parche = unittest.mock.patch.object(credenciales, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        parche = unittest.mock.patch.dict(os.environ, {}, clear=False)
        parche.start()
        self.addCleanup(parche.stop)
        os.environ.pop("NCBI_API_KEY", None)
        os.environ.pop("NCBI_EMAIL", None)

    def test_el_entorno_le_gana_al_archivo(self):
        """Permite correr una vez con otra cuenta sin tocar los archivos."""
        credenciales.guardar_correo("archivo@unam.mx")
        os.environ["NCBI_EMAIL"] = "entorno@unam.mx"

        self.assertEqual(credenciales.correo(), "entorno@unam.mx")
        self.assertEqual(credenciales.origen_correo(), "entorno")

    def test_sin_entorno_se_lee_el_archivo(self):
        """Es el arreglo de fondo: la llave ya estaba en el disco y habia
        que exportarla a mano en cada sesion."""
        credenciales.guardar_llave("b" * 36)

        self.assertEqual(credenciales.llave(), "b" * 36)
        self.assertEqual(credenciales.origen_llave(), "archivo")

    def test_sin_nada_no_hay_credenciales(self):
        self.assertIsNone(credenciales.correo())
        self.assertIsNone(credenciales.llave())
        self.assertEqual(credenciales.origen_llave(), "ninguno")

    def test_un_correo_con_dedazo_no_se_guarda(self):
        for malo in ("sin-arroba", "@sindominio", "yo@", "yo@sinpunto",
                     "", "  ", "dos@arrobas@x.com"):
            with self.assertRaises(ValueError, msg=malo):
                credenciales.guardar_correo(malo)

    def test_una_llave_de_largo_equivocado_no_se_guarda(self):
        for mala in ("", "abc", "a" * 35, "a" * 37, "-" * 36, "a b" + "c" * 33):
            with self.assertRaises(ValueError, msg=mala):
                credenciales.guardar_llave(mala)

    def test_una_llave_valida_se_guarda_y_se_relee(self):
        credenciales.guardar_llave("A1b2" * 9)

        self.assertEqual(credenciales.llave(), "A1b2" * 9)

    def test_borrar_la_llave_la_quita(self):
        credenciales.guardar_llave("c" * 36)

        credenciales.borrar_llave()

        self.assertIsNone(credenciales.llave())
