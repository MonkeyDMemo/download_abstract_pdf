# -*- coding: utf-8 -*-
"""La prueba central del proyecto: no volver a descargar lo que ya se tiene.

Si algo de este archivo falla, el ETL perdio su razon de ser. No es una
regresion menor: significa que cada corrida vuelve a pedirle a NCBI lo
que ya esta en la base.
"""

from grn_etl import db, etl, pubmed

from .falsos import ClienteFalso, PruebaSinRed, articulo_xml


class BasePruebaIngesta(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.con = db.conectar(":memory:")
        self.addCleanup(self.con.close)
        self.mensajes = []

    def log(self, msg):
        self.mensajes.append(msg)

    def alta(self, nombre, texto=None):
        db.alta_consulta(self.con, nombre, texto or f"query de {nombre}")

    def cuenta(self, tabla):
        return self.con.execute(f"SELECT COUNT(*) c FROM {tabla}").fetchone()["c"]


# ------------------------------------------------- la segunda corrida

class PruebasSegundaCorrida(BasePruebaIngesta):

    def setUp(self):
        super().setUp()
        self.alta("pa", "Pseudomonas aeruginosa AND regulation")
        self.cliente = ClienteFalso(universo=["111", "222", "333"])

    def test_segunda_ingesta_no_llama_a_efetch(self):
        """El corazon del asunto: mismo universo dos veces, un solo efetch."""
        primera = etl.ingestar(self.con, self.cliente, "pa", log=self.log)
        self.assertEqual(primera["descargados"], 3)
        self.assertEqual(self.cliente.n_eutils("efetch.fcgi"), 1)

        self.cliente.reiniciar()
        segunda = etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertEqual(self.cliente.n_eutils("efetch.fcgi"), 0,
                         "la segunda corrida volvio a descargar contenido")
        self.assertEqual(segunda["previos"], 3)
        self.assertEqual(segunda["nuevos"], 0)
        self.assertEqual(segunda["descargados"], 0)

    def test_la_segunda_ingesta_si_vuelve_a_buscar(self):
        """esearch si se repite: hay que saber que trae la consulta hoy.

        Saltarse esearch para 'ahorrar' seria el arreglo falso: dejaria de
        detectar articulos nuevos y de vincular los que ya estaban por
        otra consulta.
        """
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)
        self.cliente.reiniciar()
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertGreaterEqual(self.cliente.n_eutils("esearch.fcgi"), 1)

    def test_la_segunda_ingesta_no_duplica_documentos_ni_vinculos(self):
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertEqual(self.cuenta("documentos"), 3)
        self.assertEqual(self.cuenta("consulta_documento"), 3)

    def test_solo_se_pide_la_diferencia_cuando_el_universo_crece(self):
        """El universo crece de 3 a 5: efetch pide exactamente los 2 nuevos.

        Distinta de la anterior a proposito. Un 'if ya_hay_algo: no bajar
        nada' pasaria aquella y fallaria esta.
        """
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)
        self.cliente.universo = ["111", "222", "333", "444", "555"]
        self.cliente.reiniciar()

        r = etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertEqual(self.cliente.pmids_pedidos(), ["444", "555"])
        self.assertEqual(r["nuevos"], 2)
        self.assertEqual(r["previos"], 3)
        self.assertEqual(self.cuenta("documentos"), 5)

    def test_los_lotes_de_efetch_cubren_todo_sin_repetir(self):
        """Con tam_lote chico se hacen varias llamadas; ningun PMID se
        pierde ni se pide dos veces."""
        self.cliente.universo = [str(i) for i in range(1, 6)]

        etl.ingestar(self.con, self.cliente, "pa", tam_lote=2, log=self.log)

        pedidos = self.cliente.pmids_pedidos()
        self.assertEqual(self.cliente.n_eutils("efetch.fcgi"), 3)
        self.assertEqual(sorted(pedidos), sorted(self.cliente.universo))
        self.assertEqual(len(pedidos), len(set(pedidos)))

    def test_el_limite_recorta_antes_de_descargar(self):
        self.cliente.universo = [str(i) for i in range(1, 11)]

        r = etl.ingestar(self.con, self.cliente, "pa", limite=4, log=self.log)

        self.assertEqual(len(self.cliente.pmids_pedidos()), 4)
        self.assertEqual(r["total_pubmed"], 10)
        self.assertEqual(r["considerados"], 4)


# ------------------------------------------- un articulo, varias consultas

class PruebasSolapamiento(BasePruebaIngesta):
    """La separacion documentos / consulta_documento es la decision de
    diseno central. Aqui se verifica que de verdad rinde."""

    def setUp(self):
        super().setUp()
        self.alta("lasR", "lasR")
        self.alta("mexT", "mexT")
        self.cliente = ClienteFalso(universos={
            "lasR": ["111", "222", "333"],
            "mexT": ["333", "444"],          # el 333 aparece en las dos
        })

    def test_el_articulo_compartido_se_guarda_una_vez_y_se_liga_dos(self):
        etl.ingestar(self.con, self.cliente, "lasR", log=self.log)
        etl.ingestar(self.con, self.cliente, "mexT", log=self.log)

        veces_guardado = self.con.execute(
            "SELECT COUNT(*) c FROM documentos WHERE pmid = '333'"
        ).fetchone()["c"]
        veces_ligado = self.con.execute(
            "SELECT COUNT(*) c FROM consulta_documento WHERE pmid = '333'"
        ).fetchone()["c"]

        self.assertEqual(veces_guardado, 1)
        self.assertEqual(veces_ligado, 2)
        self.assertEqual(self.cuenta("documentos"), 4)
        self.assertEqual(self.cuenta("consulta_documento"), 5)

    def test_la_segunda_consulta_solo_descarga_lo_que_no_tenia(self):
        """El ahorro que justifica el proyecto: el solapamiento no se
        vuelve a bajar."""
        etl.ingestar(self.con, self.cliente, "lasR", log=self.log)
        self.cliente.reiniciar()

        r = etl.ingestar(self.con, self.cliente, "mexT", log=self.log)

        self.assertEqual(self.cliente.pmids_pedidos(), ["444"])
        self.assertEqual(r["previos"], 1)
        self.assertEqual(r["nuevos"], 1)

    def test_un_pmid_ya_en_la_base_se_vincula_aunque_no_se_descargue(self):
        """Paso 4 del flujo: se vinculan TODOS los PMIDs, no solo los
        nuevos. Vincular solo los nuevos dejaria la consulta 'mexT' sin
        su articulo 333, que si le pertenece."""
        etl.ingestar(self.con, self.cliente, "lasR", log=self.log)
        etl.ingestar(self.con, self.cliente, "mexT", log=self.log)

        de_mexT = {f["pmid"] for f in db.documentos_de_consulta(self.con, "mexT")}
        self.assertEqual(de_mexT, {"333", "444"})

    def test_el_documento_compartido_conserva_su_contenido(self):
        """Volver a verlo desde otra consulta no lo pisa con una version
        mas pobre (ON CONFLICT DO NOTHING)."""
        etl.ingestar(self.con, self.cliente, "lasR", log=self.log)
        antes = self.con.execute(
            "SELECT titulo, abstract FROM documentos WHERE pmid = '333'"
        ).fetchone()

        etl.ingestar(self.con, self.cliente, "mexT", log=self.log)
        despues = self.con.execute(
            "SELECT titulo, abstract FROM documentos WHERE pmid = '333'"
        ).fetchone()

        self.assertEqual(tuple(antes), tuple(despues))


# ------------------------------------------------ PMIDs que efetch no da

class PruebasPmidsSinRegistro(BasePruebaIngesta):
    """esearch lista PMIDs que efetch no devuelve: registros retirados o
    de tipo Book. Un solo caso asi no puede tumbar la corrida entera."""

    def setUp(self):
        super().setUp()
        self.alta("pa")
        self.cliente = ClienteFalso(
            universo=["111", "222", "333"],
            articulos={"111": articulo_xml("111"), "333": articulo_xml("333")},
        )

    def test_un_pmid_retirado_no_aborta_la_corrida(self):
        r = etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertEqual(r["descargados"], 2)
        self.assertEqual(self.cuenta("documentos"), 2)
        fila = db.historial(self.con, "pa")[0]
        self.assertEqual(fila["estatus"], "ok")
        self.assertIsNone(fila["error"])

    def test_solo_se_vinculan_los_pmids_que_existen(self):
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        ligados = {f["pmid"] for f in self.con.execute(
            "SELECT pmid FROM consulta_documento")}
        self.assertEqual(ligados, {"111", "333"})

    def test_se_reporta_cuantos_no_devolvieron_registro(self):
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertTrue(
            any("no devolvieron registro" in m for m in self.mensajes),
            "la corrida no aviso de los PMIDs sin registro",
        )

    def test_el_retirado_se_reintenta_pero_el_resto_no(self):
        """Comportamiento aceptado: el PMID sin registro se vuelve a pedir
        en cada corrida (nunca entra a 'documentos'). Es una peticion por
        corrida; lo que importa es que los demas no se rebajen."""
        etl.ingestar(self.con, self.cliente, "pa", log=self.log)
        self.cliente.reiniciar()

        etl.ingestar(self.con, self.cliente, "pa", log=self.log)

        self.assertEqual(self.cliente.pmids_pedidos(), ["222"])


# --------------------------------------------------------- la bitacora

class PruebasBitacora(BasePruebaIngesta):
    """La tabla 'ejecuciones' es lo que hace saber en todo momento que se
    tiene. Cuando esto sea servicio, tambien sera el estado del trabajo."""

    def setUp(self):
        super().setUp()
        self.alta("pa")

    def test_cada_corrida_deja_su_renglon_con_los_contadores(self):
        cliente = ClienteFalso(universo=["111", "222"])
        etl.ingestar(self.con, cliente, "pa", log=self.log)
        etl.ingestar(self.con, cliente, "pa", log=self.log)

        filas = db.historial(self.con, "pa")
        self.assertEqual(len(filas), 2)
        reciente, primera = filas[0], filas[1]

        self.assertEqual(primera["pmids_nuevos"], 2)
        self.assertEqual(primera["pmids_previos"], 0)
        self.assertEqual(reciente["pmids_nuevos"], 0)
        self.assertEqual(reciente["pmids_previos"], 2)
        self.assertEqual(reciente["total_pubmed"], 2)
        self.assertTrue(all(f["estatus"] == "ok" for f in filas))
        self.assertTrue(all(f["terminada_en"] for f in filas))

    def test_un_fallo_de_red_deja_la_ejecucion_marcada_y_propaga(self):
        cliente = ClienteFalso(
            universo=["111"],
            fallas={"efetch.fcgi": pubmed.ErrorPubMed("efetch fallo tras 5 intentos")},
        )

        with self.assertRaises(pubmed.ErrorPubMed):
            etl.ingestar(self.con, cliente, "pa", log=self.log)

        fila = db.historial(self.con, "pa")[0]
        self.assertEqual(fila["estatus"], "error")
        self.assertIn("efetch", fila["error"])
        self.assertEqual(self.cuenta("documentos"), 0)

    def test_una_consulta_inexistente_falla_sin_abrir_ejecucion(self):
        cliente = ClienteFalso(universo=["111"])

        with self.assertRaises(ValueError):
            etl.ingestar(self.con, cliente, "no_existe", log=self.log)

        self.assertEqual(self.cuenta("ejecuciones"), 0)
        self.assertEqual(cliente.llamadas, [],
                         "se salio a la red por una consulta inexistente")

    def test_los_avisos_de_ncbi_llegan_al_log(self):
        cliente = ClienteFalso(universo=["111"])
        cliente.avisos_esearch = ["quorum sensin"]

        etl.ingestar(self.con, cliente, "pa", log=self.log)

        self.assertTrue(any("quorum sensin" in m for m in self.mensajes))


# --------------------------------------------------- esearch paginado

class PruebasBusqueda(PruebaSinRed):
    """buscar_pmids trae la lista completa ANTES de descargar nada; de ahi
    sale la resta contra la base."""

    def test_un_conjunto_grande_cabe_en_una_sola_peticion(self):
        """Hasta el tope se pide de un tiro, con retmax al maximo.

        Paginar con retstart no sirve en PubMed, asi que pedir de menos
        obligaria a una segunda pagina que la base no entrega completa.
        """
        universo = [str(i) for i in range(100000, 109500)]   # 9500, casi el tope
        cliente = ClienteFalso(universo=universo)

        total, pmids = pubmed.buscar_pmids(cliente, "query larga")

        self.assertEqual(total, 9500)
        self.assertEqual(pmids, universo)
        self.assertEqual(cliente.n_eutils("esearch.fcgi"), 1)
        _, _, params = cliente.llamadas[0]
        self.assertEqual(params["retmax"], str(pubmed.TOPE_ESEARCH))

    def test_pasar_del_tope_falla_en_vez_de_truncar_en_silencio(self):
        """NBK25499: PubMed solo entrega los primeros 10,000 de un conjunto.

        Devolver los que quepan seria lo peor posible: la ejecucion se
        cerraria con estatus 'ok' y la bitacora diria que el corpus esta
        completo cuando le faltan dos tercios. Mejor no arrancar.
        """
        cliente = ClienteFalso(universo=[str(i) for i in range(500000, 510000)])
        cliente.total_declarado = 25000      # PubMed reporta mas de los que da

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.buscar_pmids(cliente, "query enorme")

        mensaje = str(ctx.exception)
        self.assertIn("25000", mensaje)
        self.assertIn("--desde", mensaje, "no dice como partir la consulta")

    def test_con_limite_explicito_un_conjunto_enorme_no_falla(self):
        """Con --limite el usuario ya dijo que no quiere todo; recortar ahi
        no es mentir, es lo que pidio."""
        cliente = ClienteFalso(universo=[str(i) for i in range(500000, 510000)])
        cliente.total_declarado = 25000

        total, pmids = pubmed.buscar_pmids(cliente, "query enorme", limite=5)

        self.assertEqual(total, 25000)
        self.assertEqual(len(pmids), 5)

    def test_un_error_de_esearch_se_convierte_en_ErrorPubMed(self):
        cliente = ClienteFalso(universo=[])
        cliente._esearch = lambda params: (
            b"<eSearchResult><ERROR>Query syntax error</ERROR></eSearchResult>"
        )

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.buscar_pmids(cliente, "AND AND")

        self.assertIn("Query syntax error", str(ctx.exception))

    def test_la_query_viaja_completa_en_el_parametro_term(self):
        cliente = ClienteFalso(universo=["111"])
        query = "(Pseudomonas aeruginosa[MeSH]) AND (lasR OR rhlR OR mexT)"

        pubmed.buscar_pmids(cliente, query)

        _, _, params = cliente.llamadas[0]
        self.assertEqual(params["term"], query)
        self.assertEqual(params["db"], "pubmed")
