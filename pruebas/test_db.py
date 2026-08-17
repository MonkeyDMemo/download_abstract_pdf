# -*- coding: utf-8 -*-
"""Capa de base de datos.

Aqui viven los mecanismos de los que depende la idempotencia: el
ON CONFLICT de documentos, el de vinculos y la resta de PMIDs. Se prueban
por separado porque cuando esto migre a Postgres seran estas firmas las
que tengan que seguir comportandose igual.
"""

import json
import tempfile
from pathlib import Path

from grn_etl import db

from .falsos import PruebaSinRed


class BasePruebaDb(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.con = db.conectar(":memory:")
        self.addCleanup(self.con.close)


# ------------------------------------------------------------ documentos

class PruebasDocumentos(BasePruebaDb):

    def test_pmids_conocidos_cruza_el_tope_de_parametros_de_sqlite(self):
        """SQLite limita los parametros por consulta, por eso se pregunta
        de 800 en 800. Con un universo grande el corte no puede perder
        ninguno: cada PMID perdido se vuelve a descargar."""
        universo = [str(i) for i in range(1000, 2500)]      # 1500, mas de 800
        db.guardar_documentos(self.con, [{"pmid": p} for p in universo])

        conocidos = db.pmids_conocidos(self.con, universo + ["9999"])

        self.assertEqual(conocidos, set(universo))
        self.assertNotIn("9999", conocidos)

    def test_pmids_conocidos_con_lista_vacia(self):
        self.assertEqual(db.pmids_conocidos(self.con, []), set())

    def test_guardar_no_pisa_un_documento_que_ya_estaba(self):
        """ON CONFLICT DO NOTHING: si el mismo PMID vuelve por otra
        consulta, gana la version que ya estaba."""
        db.guardar_documentos(self.con, [
            {"pmid": "111", "titulo": "Version completa",
             "abstract": "Con abstract"}])

        db.guardar_documentos(self.con, [
            {"pmid": "111", "titulo": "Version pobre", "abstract": ""}])

        fila = self.con.execute(
            "SELECT titulo, abstract FROM documentos WHERE pmid='111'").fetchone()
        self.assertEqual(fila["titulo"], "Version completa")
        self.assertEqual(fila["abstract"], "Con abstract")

    def test_tiene_abstract_refleja_si_hay_texto(self):
        db.guardar_documentos(self.con, [
            {"pmid": "111", "abstract": "Hay texto."},
            {"pmid": "222", "abstract": ""},
            {"pmid": "333"},
        ])

        filas = dict(self.con.execute(
            "SELECT pmid, tiene_abstract FROM documentos").fetchall())
        self.assertEqual(filas, {"111": 1, "222": 0, "333": 0})

    def test_las_listas_se_guardan_como_json_y_a_dict_las_devuelve(self):
        db.guardar_documentos(self.con, [{
            "pmid": "111",
            "autores": ["Ramos JL", "Nikaido H"],
            "mesh_terms": ["Pseudomonas aeruginosa"],
            "keywords": [], "tipos_publicacion": ["Journal Article"],
        }])

        fila = self.con.execute("SELECT * FROM documentos").fetchone()
        d = db.a_dict(fila)

        self.assertEqual(d["autores"], ["Ramos JL", "Nikaido H"])
        self.assertEqual(d["mesh_terms"], ["Pseudomonas aeruginosa"])
        self.assertEqual(d["keywords"], [])
        self.assertEqual(json.loads(fila["autores"]), d["autores"])

    def test_a_dict_tolera_un_campo_corrupto(self):
        """Una base vieja o editada a mano no debe tumbar una exportacion."""
        db.guardar_documentos(self.con, [{"pmid": "111"}])
        self.con.execute("UPDATE documentos SET autores = 'no es json'")

        d = db.a_dict(self.con.execute("SELECT * FROM documentos").fetchone())

        self.assertEqual(d["autores"], [])


# --------------------------------------------------------------- vinculos

class PruebasVinculos(BasePruebaDb):

    def setUp(self):
        super().setUp()
        self.a, _ = db.alta_consulta(self.con, "a", "query a")
        self.b, _ = db.alta_consulta(self.con, "b", "query b")
        db.guardar_documentos(self.con, [{"pmid": "111"}, {"pmid": "222"}])

    def cuenta_vinculos(self):
        return self.con.execute(
            "SELECT COUNT(*) c FROM consulta_documento").fetchone()["c"]

    def test_vincular_dos_veces_no_duplica(self):
        db.vincular(self.con, self.a, ["111", "222"])
        db.vincular(self.con, self.a, ["111", "222"])

        self.assertEqual(self.cuenta_vinculos(), 2)

    def test_el_mismo_documento_se_liga_a_varias_consultas(self):
        db.vincular(self.con, self.a, ["111"])
        db.vincular(self.con, self.b, ["111"])

        self.assertEqual(self.cuenta_vinculos(), 2)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) c FROM documentos").fetchone()["c"], 2)

    def test_un_pmid_que_no_esta_en_documentos_se_ignora(self):
        """esearch devuelve PMIDs que efetch no entrega (retirados, Book).
        Ligarlos violaria la llave foranea y abortaria la corrida entera
        por un solo articulo."""
        db.vincular(self.con, self.a, ["111", "no_existe", "222"])

        ligados = {f["pmid"] for f in self.con.execute(
            "SELECT pmid FROM consulta_documento")}
        self.assertEqual(ligados, {"111", "222"})


# -------------------------------------------------------------- consultas

class PruebasConsultas(BasePruebaDb):

    def test_alta_repetida_con_el_mismo_texto_no_cambia_nada(self):
        primero, estado1 = db.alta_consulta(self.con, "pa", "lasR AND mexT")
        segundo, estado2 = db.alta_consulta(self.con, "pa", "lasR AND mexT")

        self.assertEqual(estado1, "creada")
        self.assertEqual(estado2, "sin_cambios")
        self.assertEqual(primero, segundo)

    def test_cambiar_el_texto_conserva_los_documentos_ya_vinculados(self):
        """Afinar una query no puede tirar el trabajo ya hecho."""
        cid, _ = db.alta_consulta(self.con, "pa", "lasR")
        db.guardar_documentos(self.con, [{"pmid": "111"}])
        db.vincular(self.con, cid, ["111"])

        mismo, estado = db.alta_consulta(self.con, "pa", "lasR OR rhlR")

        self.assertEqual(estado, "actualizada")
        self.assertEqual(mismo, cid)
        self.assertEqual(len(db.documentos_de_consulta(self.con, "pa")), 1)

    def test_listar_cuenta_los_documentos_de_cada_consulta(self):
        cid, _ = db.alta_consulta(self.con, "pa", "q")
        db.alta_consulta(self.con, "vacia", "q2")
        db.guardar_documentos(self.con, [{"pmid": "111"}, {"pmid": "222"}])
        db.vincular(self.con, cid, ["111", "222"])

        filas = {f["nombre"]: f["n_documentos"] for f in db.listar_consultas(self.con)}

        self.assertEqual(filas, {"pa": 2, "vacia": 0})
        self.assertIsNone(dict(db.listar_consultas(self.con)[0])["ultima_corrida"])

    def test_documentos_de_consulta_filtra_los_que_no_tienen_abstract(self):
        cid, _ = db.alta_consulta(self.con, "pa", "q")
        db.guardar_documentos(self.con, [
            {"pmid": "111", "abstract": "hay"}, {"pmid": "222", "abstract": ""}])
        db.vincular(self.con, cid, ["111", "222"])

        todos = db.documentos_de_consulta(self.con, "pa")
        con_abstract = db.documentos_de_consulta(self.con, "pa",
                                                 solo_con_abstract=True)

        self.assertEqual(len(todos), 2)
        self.assertEqual([f["pmid"] for f in con_abstract], ["111"])


# --------------------------------------------------------------- descargas

class PruebasDescargas(BasePruebaDb):

    def setUp(self):
        super().setUp()
        db.guardar_documentos(self.con, [{"pmid": "111"}])

    def test_registrar_dos_veces_actualiza_y_lleva_la_cuenta_de_intentos(self):
        db.registrar_descarga(self.con, "111", "pdf", "error", nota="timeout")
        db.registrar_descarga(self.con, "111", "pdf", "ok", ruta="/x.pdf", tam=99)

        filas = self.con.execute(
            "SELECT * FROM descargas WHERE pmid='111'").fetchall()

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["estatus"], "ok")
        self.assertEqual(filas[0]["intentos"], 2)
        self.assertEqual(filas[0]["bytes"], 99)

    def test_xml_y_pdf_se_llevan_por_separado(self):
        db.registrar_descarga(self.con, "111", "xml", "ok")
        db.registrar_descarga(self.con, "111", "pdf", "no_disponible")

        estados = dict(self.con.execute(
            "SELECT tipo, estatus FROM descargas WHERE pmid='111'").fetchall())
        self.assertEqual(estados, {"xml": "ok", "pdf": "no_disponible"})

    def test_actualizar_ids_no_pisa_un_doi_que_ya_estaba(self):
        db.guardar_documentos(self.con, [{"pmid": "222", "doi": "10.1/bueno"}])

        db.actualizar_ids(self.con, "222", pmcid="PMC2", doi="10.1/otro")

        fila = self.con.execute(
            "SELECT pmcid, doi FROM documentos WHERE pmid='222'").fetchone()
        self.assertEqual(fila["pmcid"], "PMC2")
        self.assertEqual(fila["doi"], "10.1/bueno")


# ----------------------------------------------------------------- resumen

class PruebasResumen(BasePruebaDb):

    def test_el_resumen_distingue_documentos_de_vinculos(self):
        """Es la diferencia que hay que poder ver: 3 articulos unicos
        ligados 4 veces significa que una consulta reaprovecho uno."""
        a, _ = db.alta_consulta(self.con, "a", "q")
        b, _ = db.alta_consulta(self.con, "b", "q2")
        db.guardar_documentos(self.con, [
            {"pmid": "111", "abstract": "x"}, {"pmid": "222", "abstract": "y"},
            {"pmid": "333"}])
        db.vincular(self.con, a, ["111", "222", "333"])
        db.vincular(self.con, b, ["333"])
        db.registrar_descarga(self.con, "111", "xml", "ok")

        r = db.resumen(self.con)

        self.assertEqual(r["consultas"], 2)
        self.assertEqual(r["documentos"], 3)
        self.assertEqual(r["con_abstract"], 2)
        self.assertEqual(r["vinculos"], 4)
        self.assertEqual([tuple(d) for d in r["descargas"]], [("xml", "ok", 1)])

    def test_el_resumen_de_una_base_recien_creada(self):
        r = db.resumen(self.con)

        self.assertEqual(r["documentos"], 0)
        self.assertEqual(r["descargas"], [])


# --------------------------------------------------------------- conexion

class PruebasConexion(PruebaSinRed):

    def setUp(self):
        super().setUp()
        # Se registra la limpieza del directorio ANTES que la de cualquier
        # conexion: addCleanup corre al reves, y en Windows no se puede
        # borrar el archivo de la base mientras siga abierto.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def abrir(self, ruta):
        con = db.conectar(str(ruta))
        self.addCleanup(con.close)
        return con

    def test_conectar_crea_el_directorio_y_el_esquema(self):
        ruta = self.tmp / "sub" / "grn.db"

        con = self.abrir(ruta)

        self.assertTrue(ruta.exists())
        tablas = {f[0] for f in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tablas, {"consultas", "ejecuciones", "documentos",
                                  "consulta_documento", "descargas"})

    def test_las_llaves_foraneas_quedan_activas(self):
        """Sin esto la base aceptaria vinculos a documentos inexistentes y
        el estado dejaria de ser confiable."""
        con = self.abrir(self.tmp / "grn.db")

        self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_reabrir_una_base_existente_conserva_los_datos(self):
        """El esquema se crea con IF NOT EXISTS: abrir de nuevo no borra."""
        ruta = self.tmp / "grn.db"
        con = db.conectar(str(ruta))
        db.guardar_documentos(con, [{"pmid": "111"}])
        con.close()

        con2 = self.abrir(ruta)

        self.assertEqual(db.pmids_conocidos(con2, ["111"]), {"111"})
