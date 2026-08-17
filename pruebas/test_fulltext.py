# -*- coding: utf-8 -*-
"""Segunda etapa: XML de PMC y PDF de acceso abierto.

Tiene su propia idempotencia, distinta de la de la ingesta: la lleva la
tabla 'descargas'. Una corrida interrumpida se reanuda sin repetir lo
hecho, y lo que no es de acceso abierto no se vuelve a pedir nunca.

Nada de aqui escribe en el repositorio: todo va a un directorio temporal.
"""

import json
import tempfile
from pathlib import Path

from grn_etl import db, etl, pubmed

from .falsos import (PDF_VALIDO, ClienteFalso, PruebaSinRed, jats_xml,
                     oa_error_xml, oa_xml)


class BasePruebaFulltext(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.con = db.conectar(":memory:")
        self.addCleanup(self.con.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.salida = tmp.name
        self.mensajes = []
        self.consulta_id, _ = db.alta_consulta(self.con, "pa", "query")

    def log(self, msg):
        self.mensajes.append(msg)

    def sembrar(self, *docs):
        """Mete documentos en la base y los liga a la consulta."""
        db.guardar_documentos(self.con, list(docs))
        db.vincular(self.con, self.consulta_id, [d["pmid"] for d in docs])

    def archivos(self, tipo):
        carpeta = Path(self.salida) / tipo
        return sorted(p.name for p in carpeta.iterdir()) if carpeta.exists() else []

    def descarga(self, pmid, tipo):
        return self.con.execute(
            "SELECT * FROM descargas WHERE pmid = ? AND tipo = ?", (pmid, tipo)
        ).fetchone()

    def correr(self, tipo="xml", cliente=None, **kw):
        return etl.descargar_fulltext(
            self.con, cliente or self.cliente, tipo=tipo, salida=self.salida,
            log=self.log, **kw
        )


# ------------------------------------------------------------- XML de PMC

class PruebasXml(BasePruebaFulltext):

    def test_solo_metadatos_se_marca_no_disponible_y_no_escribe_nada(self):
        """El caso que mas dano hace si pasa inadvertido: PMC contesta con
        el articulo pero sin cuerpo. Guardarlo como 'ok' meteria un
        abstract al corpus haciendose pasar por texto completo."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        self.cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=False)})

        r = self.correr("xml")

        self.assertEqual(r, {"pendientes": 1, "ok": 0,
                             "no_disponible": 1, "error": 0})
        self.assertEqual(self.archivos("xml"), [])
        fila = self.descarga("111", "xml")
        self.assertEqual(fila["estatus"], "no_disponible")
        self.assertIn("metadatos", fila["nota"])

    def test_un_articulo_abierto_deja_el_jats_y_el_texto_en_disco(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        self.cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=True)})

        r = self.correr("xml")

        self.assertEqual(r["ok"], 1)
        self.assertEqual(self.archivos("xml"), ["111_PMC1.txt", "111_PMC1.xml"])
        fila = self.descarga("111", "xml")
        self.assertEqual(fila["estatus"], "ok")
        self.assertEqual(fila["fuente"], "PMC")
        self.assertTrue(fila["ruta"].endswith("111_PMC1.txt"))
        self.assertGreater(fila["bytes"], 0)

    def test_el_nombre_del_archivo_permite_rastrear_el_origen(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        self.cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=True)})

        self.correr("xml")

        crudo = Path(self.salida) / "xml" / "111_PMC1.xml"
        self.assertEqual(crudo.read_bytes(), jats_xml(cuerpo=True))

    def test_sin_pmcid_no_se_le_pide_nada_a_pmc(self):
        self.sembrar({"pmid": "111"})
        self.cliente = ClienteFalso()          # el ID Converter no lo conoce

        r = self.correr("xml")

        self.assertEqual(r["no_disponible"], 1)
        self.assertEqual(self.cliente.n_eutils("efetch.fcgi", db="pmc"), 0)
        self.assertIn("sin PMCID", self.descarga("111", "xml")["nota"])

    def test_el_pmcid_resuelto_se_usa_en_la_misma_corrida(self):
        """No basta con guardar el PMCID en la base: hay que usarlo ya, en
        la corrida que lo resolvio.

        Si el mapa que devuelve convertir_ids no se puede consultar por el
        PMID que trae la fila, el articulo se marca 'no_disponible' aunque
        su PMCID haya quedado guardado en la misma pasada. Y
        'no_disponible' no se reintenta nunca, asi que un articulo de
        acceso abierto queda perdido para siempre.
        """
        self.sembrar({"pmid": "37569271"})
        self.cliente = ClienteFalso(
            mapa_ids={"37569271": {"pmcid": "PMC10418997",
                                   "doi": "10.3390/ijms241511895"}},
            xml_pmc={"PMC10418997": jats_xml(cuerpo=True)},
        )

        r = self.correr("xml")

        self.assertEqual(r["ok"], 1, "se resolvio el PMCID pero no se uso")
        self.assertEqual(r["no_disponible"], 0)
        self.assertEqual(self.archivos("xml"),
                         ["37569271_PMC10418997.txt", "37569271_PMC10418997.xml"])
        fila = self.con.execute(
            "SELECT pmcid, doi FROM documentos WHERE pmid = '37569271'").fetchone()
        self.assertEqual(fila["pmcid"], "PMC10418997")
        self.assertEqual(fila["doi"], "10.3390/ijms241511895")

    def test_un_fallo_no_aborta_el_lote(self):
        """Los fallos de un articulo se registran y la corrida sigue: de
        otro modo un solo articulo raro tumbaria un lote de miles."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1", "anio": "2020"},
                     {"pmid": "222", "pmcid": "PMC2", "anio": "2019"},
                     {"pmid": "333", "pmcid": "PMC3", "anio": "2018"})
        self.cliente = ClienteFalso(
            xml_pmc={"PMC1": jats_xml(cuerpo=True), "PMC3": jats_xml(cuerpo=True)},
            fallas={"PMC2": pubmed.ErrorPubMed("se corto la conexion")},
        )

        r = self.correr("xml")

        self.assertEqual(r["ok"], 2)
        self.assertEqual(r["error"], 1)
        fila = self.descarga("222", "xml")
        self.assertEqual(fila["estatus"], "error")
        self.assertIn("conexion", fila["nota"])

    def test_la_segunda_corrida_no_vuelve_a_bajar_lo_ya_descargado(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        self.cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=True)})
        self.correr("xml")
        self.cliente.reiniciar()

        r = self.correr("xml")

        self.assertEqual(r["pendientes"], 0)
        self.assertEqual(self.cliente.llamadas, [])

    def test_tipo_invalido(self):
        self.cliente = ClienteFalso()
        with self.assertRaises(ValueError):
            self.correr("epub")


# ------------------------------------------------ que se considera pendiente

class PruebasPendientes(BasePruebaFulltext):
    """pendientes_descarga es lo que evita gastar peticiones en articulos
    que ya se sabe que no estan abiertos."""

    def setUp(self):
        super().setUp()
        self.sembrar({"pmid": "111", "anio": "2020"},
                     {"pmid": "222", "anio": "2019"},
                     {"pmid": "333", "anio": "2018"})
        db.registrar_descarga(self.con, "111", "xml", "ok", ruta="/x.txt")
        db.registrar_descarga(self.con, "222", "xml", "no_disponible")
        db.registrar_descarga(self.con, "333", "xml", "error", nota="timeout")

    def pendientes(self, **kw):
        return [f["pmid"] for f in db.pendientes_descarga(self.con, "xml", **kw)]

    def test_por_omision_solo_queda_pendiente_lo_no_intentado(self):
        self.sembrar({"pmid": "444", "anio": "2017"})

        self.assertEqual(self.pendientes(), ["444"])

    def test_con_reintentar_vuelven_los_que_fallaron(self):
        self.assertEqual(self.pendientes(reintentar=True), ["333"])

    def test_lo_no_disponible_no_vuelve_ni_con_reintentar(self):
        """No tiene acceso abierto: reintentarlo solo gasta el limite de
        peticiones. Esos salen por 'export --pendientes'."""
        self.assertNotIn("222", self.pendientes(reintentar=True))

    def test_el_tipo_se_lleva_por_separado(self):
        """Tener el XML no significa tener el PDF."""
        self.assertEqual(sorted(
            f["pmid"] for f in db.pendientes_descarga(self.con, "pdf")),
            ["111", "222", "333"])

    def test_el_limite_permite_probar_con_pocos(self):
        self.sembrar({"pmid": "444", "anio": "2017"}, {"pmid": "555", "anio": "2016"})

        self.assertEqual(len(self.pendientes(limite=1)), 1)


# ----------------------------------------------------------------- PDF

class PruebasPdf(BasePruebaFulltext):

    def test_pdf_del_subset_abierto_de_pmc(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        url = "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/a/b/111.pdf"
        https = url.replace("ftp://ftp.ncbi.nlm.nih.gov",
                            "https://ftp.ncbi.nlm.nih.gov")
        self.cliente = ClienteFalso(oa={"PMC1": oa_xml("PMC1", url)},
                                    cuerpos={https: PDF_VALIDO})

        r = self.correr("pdf")

        self.assertEqual(r["ok"], 1)
        self.assertEqual(self.archivos("pdf"), ["111.pdf"])
        self.assertEqual(self.descarga("111", "pdf")["fuente"], "PMC OA")

    def test_la_liga_ftp_se_pide_por_https(self):
        """El OA Service contesta ftp://, que muchos firewalls de la UNAM
        no dejan salir."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        url = "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/a/b/111.pdf"
        self.cliente = ClienteFalso(oa={"PMC1": oa_xml("PMC1", url)})

        self.correr("pdf")

        self.assertTrue(any(u.startswith("https://ftp.ncbi.nlm.nih.gov")
                            for u in self.cliente.urls_pedidas()))

    def test_una_respuesta_que_no_es_pdf_se_registra_como_error(self):
        """Varios repositorios contestan HTML de error con codigo 200. Sin
        revisar la firma se guardarian paginas de error como articulos."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        url = "https://ftp.ncbi.nlm.nih.gov/x.pdf"
        self.cliente = ClienteFalso(
            oa={"PMC1": oa_xml("PMC1", url)},
            cuerpos={url: b"<html><body>Acceso denegado</body></html>"},
        )

        r = self.correr("pdf")

        self.assertEqual(r["error"], 1)
        self.assertEqual(self.archivos("pdf"), [])
        self.assertIn("no devolvio un PDF", self.descarga("111", "pdf")["nota"])

    def test_unpaywall_como_segunda_fuente(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1", "doi": "10.1128/JB.001-20"})
        url = "https://repositorio.unam.mx/111.pdf"
        self.cliente = ClienteFalso(
            oa={"PMC1": oa_error_xml()},          # no esta en el subset de PMC
            unpaywall={"10.1128/JB.001-20": {"best_oa_location": {
                "url_for_pdf": url, "repository_institution": "UNAM"}}},
            cuerpos={url: PDF_VALIDO},
        )

        r = self.correr("pdf")

        self.assertEqual(r["ok"], 1)
        self.assertIn("Unpaywall", self.descarga("111", "pdf")["fuente"])
        self.assertIn("UNAM", self.descarga("111", "pdf")["fuente"])

    def test_sin_unpaywall_no_se_consulta_unpaywall(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1", "doi": "10.1/x"})
        self.cliente = ClienteFalso(oa={"PMC1": oa_error_xml()})

        r = self.correr("pdf", usar_unpaywall=False)

        self.assertEqual(r["no_disponible"], 1)
        self.assertFalse(any(u.startswith(pubmed.UNPAYWALL)
                             for u in self.cliente.urls_pedidas()))

    def test_sin_ninguna_fuente_abierta_queda_como_pendiente_de_biblioteca(self):
        """Lo que no es abierto no se toca: se exporta para pedirlo a la
        biblioteca."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1", "doi": "10.1/x"})
        self.cliente = ClienteFalso(oa={"PMC1": oa_error_xml()}, unpaywall={})

        r = self.correr("pdf")

        self.assertEqual(r["no_disponible"], 1)
        self.assertEqual(self.archivos("pdf"), [])
        self.assertIn("sin PDF de acceso abierto",
                      self.descarga("111", "pdf")["nota"])


# ------------------------------------------- funciones sueltas de pubmed

class PruebasResolucionDeIds(PruebaSinRed):

    def test_convertir_ids_respeta_el_tope_de_la_api(self):
        """El ID Converter acepta 200 IDs por peticion; se piden de 180."""
        # PMIDs con forma realista: los de verdad no empiezan en cero.
        pmids = [str(30000000 + i) for i in range(400)]
        cliente = ClienteFalso(mapa_ids={
            p: {"pmcid": "PMC" + p, "doi": ""} for p in pmids})

        mapa = pubmed.convertir_ids(cliente, pmids)

        self.assertEqual(len(mapa), 400)
        self.assertEqual(len(cliente.urls_pedidas()), 3)
        for _, _, params in cliente.llamadas:
            self.assertLessEqual(len(params["ids"].split(",")), 180)

    def test_un_registro_sin_pmid_no_entra_al_mapa(self):
        cliente = ClienteFalso()
        cliente.get = lambda *a, **k: json.dumps(
            {"records": [{"pmcid": "PMC1"}, {"pmid": 222, "pmcid": "PMC2"}]}
        ).encode()

        mapa = pubmed.convertir_ids(cliente, ["111", "222"])

        self.assertEqual(mapa, {"222": {"pmcid": "PMC2", "doi": ""}})

    def test_el_pmid_numerico_de_la_api_se_normaliza_a_texto(self):
        """El ID Converter manda "pmid":37569271 como numero, mientras que
        esearch y efetch lo mandan como cadena. Si el mapa se queda con la
        llave entera, ningun mapa.get(pmid) acierta y el articulo termina
        marcado 'no_disponible', que no se reintenta nunca."""
        cliente = ClienteFalso()
        cliente.get = lambda *a, **k: json.dumps({"records": [
            {"pmid": 37569271, "pmcid": "PMC10418997",
             "doi": "10.3390/ijms241511895"}]}).encode()

        mapa = pubmed.convertir_ids(cliente, ["37569271"])

        self.assertEqual(list(mapa), ["37569271"])
        self.assertIsInstance(list(mapa)[0], str)
        self.assertEqual(mapa["37569271"]["pmcid"], "PMC10418997")

    def test_un_registro_de_error_del_converter_no_aporta_pmcid(self):
        """Para un PMID que no esta en PMC el converter contesta el
        registro con status 'error'; no trae pmcid y no debe inventarse."""
        cliente = ClienteFalso()
        cliente.get = lambda *a, **k: json.dumps({"records": [
            {"pmid": 29729420, "status": "error",
             "errmsg": "Identifier not found in PMC"}]}).encode()

        mapa = pubmed.convertir_ids(cliente, ["29729420"])

        self.assertEqual(mapa["29729420"]["pmcid"], "")

    def test_liga_pdf_pmc_devuelve_none_si_no_es_de_acceso_abierto(self):
        cliente = ClienteFalso(oa={"PMC1": oa_error_xml()})

        self.assertIsNone(pubmed.liga_pdf_pmc(cliente, "PMC1"))

    def test_liga_pdf_unpaywall_sin_doi_no_hace_peticion(self):
        cliente = ClienteFalso()

        url, fuente = pubmed.liga_pdf_unpaywall(cliente, "", "yo@unam.mx")

        self.assertEqual((url, fuente), (None, None))
        self.assertEqual(cliente.llamadas, [])

    def test_liga_pdf_unpaywall_sin_copia_abierta(self):
        cliente = ClienteFalso(unpaywall={"10.1/x": {"best_oa_location": None}})

        url, fuente = pubmed.liga_pdf_unpaywall(cliente, "10.1/x", "yo@unam.mx")

        self.assertEqual((url, fuente), (None, None))


# ------------------------------------------- de donde salio cada documento

class PruebasRegistroDeUrl(BasePruebaFulltext):
    """Cada fila de 'descargas' guarda la liga del articulo.

    Importa mas en los casos que NO se pudieron bajar que en los que si:
    esa liga es la que alguien va a abrir a mano para conseguir el
    articulo por la biblioteca. Sin ella hay que rearmarla desde el PMID
    cada vez.
    """

    def test_el_articulo_bajado_guarda_su_liga_de_pmc(self):
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        self.cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=True)})

        self.correr("xml")

        self.assertEqual(self.descarga("111", "xml")["url"],
                         "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/")

    def test_solo_metadatos_guarda_la_liga_de_pmc(self):
        """El articulo esta en PMC y se puede leer ahi, aunque la API solo
        entregue metadatos. La liga es justo lo que hace falta."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        self.cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=False)})

        self.correr("xml")

        fila = self.descarga("111", "xml")
        self.assertEqual(fila["estatus"], "no_disponible")
        self.assertEqual(fila["url"], "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/")

    def test_sin_pmcid_queda_la_liga_de_pubmed(self):
        self.sembrar({"pmid": "111"})
        self.cliente = ClienteFalso()

        self.correr("xml")

        self.assertEqual(self.descarga("111", "xml")["url"],
                         "https://pubmed.ncbi.nlm.nih.gov/111/")

    def test_el_pdf_fallido_guarda_la_liga_que_fallo(self):
        """Sin la liga concreta no hay forma de saber a que editor se fue
        ni que se intento."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1"})
        url = "https://ftp.ncbi.nlm.nih.gov/x.pdf"
        self.cliente = ClienteFalso(
            oa={"PMC1": oa_xml("PMC1", url)},
            cuerpos={url: b"<html>Acceso denegado</html>"},
        )

        self.correr("pdf")

        fila = self.descarga("111", "pdf")
        self.assertEqual(fila["estatus"], "error")
        self.assertEqual(fila["url"], url)

    def test_una_base_vieja_gana_la_columna_sin_perder_datos(self):
        """La migracion no puede obligar a nadie a borrar su base y volver
        a descargar todo: eso es exactamente lo que el proyecto evita."""
        import sqlite3
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ruta = str(Path(tmp.name) / "vieja.db")

        # Base con el esquema anterior, sin la columna 'url'
        vieja = sqlite3.connect(ruta)
        vieja.executescript("""
            CREATE TABLE documentos (pmid TEXT PRIMARY KEY, doi TEXT, pmcid TEXT,
                titulo TEXT, abstract TEXT, revista TEXT, anio TEXT, autores TEXT,
                mesh_terms TEXT, keywords TEXT, tipos_publicacion TEXT,
                tiene_abstract INTEGER NOT NULL DEFAULT 0, extraido_en TEXT NOT NULL);
            CREATE TABLE descargas (id INTEGER PRIMARY KEY, pmid TEXT NOT NULL,
                tipo TEXT NOT NULL, estatus TEXT NOT NULL, fuente TEXT, ruta TEXT,
                bytes INTEGER, nota TEXT, intentos INTEGER NOT NULL DEFAULT 1,
                actualizado_en TEXT NOT NULL, UNIQUE (pmid, tipo));
            INSERT INTO documentos VALUES ('111','','','T','','','2020','[]','[]','[]','[]',0,'x');
            INSERT INTO descargas (pmid,tipo,estatus,actualizado_en)
                VALUES ('111','xml','ok','x');
        """)
        vieja.commit()
        vieja.close()

        con = db.conectar(ruta)
        self.addCleanup(con.close)

        columnas = {f["name"] for f in con.execute("PRAGMA table_info(descargas)")}
        self.assertIn("url", columnas)
        fila = con.execute("SELECT * FROM descargas WHERE pmid='111'").fetchone()
        self.assertEqual(fila["estatus"], "ok")
        self.assertIsNone(fila["url"])


class PruebasServicioCaido(PruebaSinRed):
    """Un servicio que no contesta no es lo mismo que un articulo que no
    esta disponible, y confundirlos escribe una mentira permanente.

    'no_disponible' no se reintenta nunca, por diseno. Si una caida de
    unos minutos se registra asi, articulos de acceso abierto quedan
    condenados y solo se recuperan borrando filas a mano. Por eso ambos
    servicios fallan ruidosamente cuando no hay respuesta: el ETL lo
    registra como 'error', que si vuelve con --reintentar.
    """

    def test_el_id_converter_sin_respuesta_falla_en_vez_de_callar(self):
        cliente = ClienteFalso()
        cliente.get = lambda *a, **k: None          # el servicio no contesta

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.convertir_ids(cliente, ["111", "222"])

        self.assertIn("no respondio", str(ctx.exception))

    def test_el_id_converter_con_basura_falla_en_vez_de_callar(self):
        cliente = ClienteFalso()
        cliente.get = lambda *a, **k: b"<html>Not Found</html>"

        with self.assertRaises(pubmed.ErrorPubMed):
            pubmed.convertir_ids(cliente, ["111"])

    def test_el_oa_service_sin_respuesta_falla_en_vez_de_decir_que_no_hay(self):
        """NCBI anuncio el retiro de este servicio. Cuando deje de
        responder, sin esto marcariamos como 'sin PDF de acceso abierto'
        a articulos que si lo tienen."""
        cliente = ClienteFalso(oa={})               # nadie contesta por PMC1

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.liga_pdf_pmc(cliente, "PMC1")

        self.assertIn("PMC1", str(ctx.exception))

    def test_el_oa_service_que_si_contesta_y_no_tiene_pdf_devuelve_none(self):
        """El caso legitimo sigue siendo None: contesto y no hay PDF."""
        cliente = ClienteFalso(oa={"PMC1": oa_error_xml()})

        self.assertIsNone(pubmed.liga_pdf_pmc(cliente, "PMC1"))


class PruebasCaidaEnElLote(BasePruebaFulltext):

    def test_una_caida_del_oa_service_queda_como_error_reintentable(self):
        """Cierra el circuito: el fallo ruidoso de pubmed.py tiene que
        aterrizar en 'descargas' como 'error', no como 'no_disponible'."""
        self.sembrar({"pmid": "111", "pmcid": "PMC1", "doi": "10.1/x"})
        self.cliente = ClienteFalso(oa={})          # el servicio no contesta

        r = self.correr("pdf")

        self.assertEqual(r["error"], 1)
        self.assertEqual(r["no_disponible"], 0)
        fila = self.descarga("111", "pdf")
        self.assertEqual(fila["estatus"], "error")

        # y por ser 'error', vuelve con --reintentar
        pendientes = [f["pmid"] for f in
                      db.pendientes_descarga(self.con, "pdf", reintentar=True)]
        self.assertIn("111", pendientes)
