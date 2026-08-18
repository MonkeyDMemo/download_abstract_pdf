# -*- coding: utf-8 -*-
"""Parseo de XML de PubMed y de PMC, y contrato del cliente HTTP.

pubmed.py no conoce la base, asi que todo esto son funciones puras sobre
bytes fijos. Las unicas pruebas que tocan pubmed.Cliente le sustituyen
_abrir(), que es el unico punto donde el modulo abriria la red.
"""

import io
import unittest.mock
import urllib.error
import urllib.parse

from grn_etl import pubmed

from .falsos import PruebaSinRed, jats_xml


def _articulo(interior, pmid="111", citacion_extra="", datos_pubmed=""):
    """Envuelve un fragmento de <Article> y devuelve el dict parseado."""
    xml = (f"<?xml version='1.0'?><PubmedArticleSet><PubmedArticle>"
           f"<MedlineCitation><PMID>{pmid}</PMID>"
           f"<Article>{interior}</Article>{citacion_extra}</MedlineCitation>"
           f"{datos_pubmed}</PubmedArticle></PubmedArticleSet>")
    return pubmed.parsear_articulos(xml.encode())[0]


def _con_pubdate(pubdate):
    return (f"<Journal><JournalIssue><PubDate>{pubdate}</PubDate></JournalIssue>"
            f"<ISOAbbreviation>J Bacteriol</ISOAbbreviation></Journal>"
            f"<ArticleTitle>Titulo</ArticleTitle>")


# --------------------------------------------------------- abstracts

class PruebasAbstract(PruebaSinRed):
    """Los abstracts estructurados son la norma en literatura biomedica.
    Perder las etiquetas de seccion le quita contexto al clasificador:
    una relacion TF-gen afirmada en RESULTS no vale lo mismo que una
    mencionada en BACKGROUND."""

    def test_abstract_estructurado_conserva_las_etiquetas_y_el_orden(self):
        d = _articulo("""
          <ArticleTitle>Regulacion por LasR</ArticleTitle>
          <Abstract>
            <AbstractText Label="BACKGROUND" NlmCategory="BACKGROUND"
              >El quorum sensing controla la virulencia.</AbstractText>
            <AbstractText Label="RESULTS" NlmCategory="RESULTS"
              >LasR activa la transcripcion de rhlR.</AbstractText>
            <AbstractText Label="CONCLUSIONS" NlmCategory="CONCLUSIONS"
              >La jerarquia es secuencial.</AbstractText>
          </Abstract>""")

        self.assertEqual(
            d["abstract"],
            "BACKGROUND: El quorum sensing controla la virulencia. "
            "RESULTS: LasR activa la transcripcion de rhlR. "
            "CONCLUSIONS: La jerarquia es secuencial.",
        )

    def test_la_etiqueta_UNLABELLED_no_produce_prefijo(self):
        d = _articulo("""
          <ArticleTitle>T</ArticleTitle>
          <Abstract>
            <AbstractText Label="UNLABELLED" NlmCategory="UNASSIGNED"
              >Un abstract corrido.</AbstractText>
          </Abstract>""")

        self.assertEqual(d["abstract"], "Un abstract corrido.")

    def test_se_usa_NlmCategory_cuando_no_hay_Label(self):
        d = _articulo("""
          <ArticleTitle>T</ArticleTitle>
          <Abstract>
            <AbstractText NlmCategory="METHODS">Se uso PAO1.</AbstractText>
          </Abstract>""")

        self.assertEqual(d["abstract"], "METHODS: Se uso PAO1.")

    def test_las_secciones_vacias_se_omiten(self):
        d = _articulo("""
          <ArticleTitle>T</ArticleTitle>
          <Abstract>
            <AbstractText Label="BACKGROUND">Hay contexto.</AbstractText>
            <AbstractText Label="METHODS"></AbstractText>
            <AbstractText Label="RESULTS">   </AbstractText>
            <AbstractText Label="CONCLUSIONS">Hay conclusion.</AbstractText>
          </Abstract>""")

        self.assertEqual(d["abstract"],
                         "BACKGROUND: Hay contexto. CONCLUSIONS: Hay conclusion.")

    def test_el_marcado_interno_no_parte_los_nombres_de_gen(self):
        """PubMed marca los nombres de gen en cursivas y los subindices con
        etiquetas propias. Si el parseo se quedara con el .text del nodo,
        'lasR' desapareceria del abstract y con el la relacion."""
        d = _articulo("""
          <ArticleTitle>T</ArticleTitle>
          <Abstract>
            <AbstractText>El regulador <i>lasR</i> reprime a
              <i>mexT</i> en el operon <i>mexEF-oprN</i>, y el locus
              PA<sub>0762</sub> responde a AlgU.</AbstractText>
          </Abstract>""")

        self.assertIn("lasR", d["abstract"])
        self.assertIn("mexT", d["abstract"])
        self.assertIn("mexEF-oprN", d["abstract"])
        self.assertIn("PA0762", d["abstract"])

    def test_un_articulo_sin_abstract_queda_con_cadena_vacia(self):
        d = _articulo("<ArticleTitle>Solo titulo</ArticleTitle>")

        self.assertEqual(d["abstract"], "")
        self.assertEqual(d["titulo"], "Solo titulo")

    def test_los_saltos_de_linea_del_xml_se_colapsan(self):
        d = _articulo("""
          <ArticleTitle>T</ArticleTitle>
          <Abstract><AbstractText>Primera linea
              y segunda    linea.</AbstractText></Abstract>""")

        self.assertEqual(d["abstract"], "Primera linea y segunda linea.")


# ------------------------------------------------------------- anio

class PruebasAnio(PruebaSinRed):
    """Una parte de las revistas no manda <Year>: mandan <MedlineDate> con
    texto libre. Sin este rescate esos articulos quedan sin anio y se van
    al final de cualquier orden por fecha."""

    def test_year_normal(self):
        self.assertEqual(_articulo(_con_pubdate("<Year>2018</Year>"))["anio"],
                         "2018")

    def test_medline_date_con_rango_de_meses(self):
        d = _articulo(_con_pubdate("<MedlineDate>2019 Nov-Dec</MedlineDate>"))
        self.assertEqual(d["anio"], "2019")

    def test_medline_date_con_rango_de_anios_toma_el_primero(self):
        d = _articulo(_con_pubdate("<MedlineDate>1998-1999</MedlineDate>"))
        self.assertEqual(d["anio"], "1998")

    def test_medline_date_con_estacion_antes_del_anio(self):
        d = _articulo(_con_pubdate("<MedlineDate>Winter 2005</MedlineDate>"))
        self.assertEqual(d["anio"], "2005")

    def test_year_gana_sobre_medline_date(self):
        d = _articulo(_con_pubdate(
            "<Year>2011</Year><MedlineDate>2010 Spring</MedlineDate>"))
        self.assertEqual(d["anio"], "2011")

    def test_sin_fecha_el_anio_queda_vacio_y_el_articulo_se_conserva(self):
        """Un articulo sin fecha reconocible no puede tumbar la ingesta."""
        d = _articulo(_con_pubdate("<MedlineDate>sin fecha</MedlineDate>"))

        self.assertEqual(d["anio"], "")
        self.assertEqual(d["pmid"], "111")


# --------------------------------------------------- resto del registro

class PruebasRegistro(PruebaSinRed):

    def test_doi_desde_elocationid(self):
        d = _articulo("<ArticleTitle>T</ArticleTitle>"
                      "<ELocationID EIdType='pii'>S0021</ELocationID>"
                      "<ELocationID EIdType='doi'>10.1128/JB.00123-20</ELocationID>")
        self.assertEqual(d["doi"], "10.1128/JB.00123-20")

    def test_doi_desde_articleidlist_cuando_no_hay_elocationid(self):
        d = _articulo(
            "<ArticleTitle>T</ArticleTitle>",
            datos_pubmed="<PubmedData><ArticleIdList>"
                         "<ArticleId IdType='pubmed'>111</ArticleId>"
                         "<ArticleId IdType='doi'>10.1099/mic.0.001</ArticleId>"
                         "</ArticleIdList></PubmedData>",
        )
        self.assertEqual(d["doi"], "10.1099/mic.0.001")

    def test_sin_doi_queda_vacio(self):
        self.assertEqual(_articulo("<ArticleTitle>T</ArticleTitle>")["doi"], "")

    def test_autores_con_apellido_e_iniciales_y_autoria_colectiva(self):
        d = _articulo("""
          <ArticleTitle>T</ArticleTitle>
          <AuthorList>
            <Author><LastName>Ramos</LastName><Initials>JL</Initials></Author>
            <Author><LastName>Nikaido</LastName><Initials>H</Initials></Author>
            <Author><CollectiveName>Consorcio PA</CollectiveName></Author>
          </AuthorList>""")

        self.assertEqual(d["autores"], ["Ramos JL", "Nikaido H", "Consorcio PA"])

    def test_mesh_keywords_y_tipos_de_publicacion(self):
        d = _articulo(
            "<ArticleTitle>T</ArticleTitle>"
            "<PublicationTypeList>"
            "<PublicationType>Journal Article</PublicationType>"
            "<PublicationType>Review</PublicationType>"
            "</PublicationTypeList>",
            citacion_extra="<MeshHeadingList>"
                           "<MeshHeading><DescriptorName>Pseudomonas aeruginosa"
                           "</DescriptorName></MeshHeading>"
                           "<MeshHeading><DescriptorName>Gene Expression Regulation"
                           "</DescriptorName></MeshHeading>"
                           "</MeshHeadingList>"
                           "<KeywordList><Keyword>quorum sensing</Keyword>"
                           "<Keyword></Keyword><Keyword>biofilm</Keyword>"
                           "</KeywordList>",
        )

        self.assertEqual(d["mesh_terms"],
                         ["Pseudomonas aeruginosa", "Gene Expression Regulation"])
        self.assertEqual(d["keywords"], ["quorum sensing", "biofilm"])
        self.assertEqual(d["tipos_publicacion"], ["Journal Article", "Review"])

    def test_los_libros_no_producen_registro(self):
        """efetch mezcla <PubmedBookArticle> en la respuesta. No se parsean,
        y por eso hay PMIDs que se piden y no vuelven."""
        xml = (b"<?xml version='1.0'?><PubmedArticleSet>"
               b"<PubmedArticle><MedlineCitation><PMID>111</PMID>"
               b"<Article><ArticleTitle>Un articulo</ArticleTitle></Article>"
               b"</MedlineCitation></PubmedArticle>"
               b"<PubmedBookArticle><BookDocument><PMID>222</PMID>"
               b"<Book><BookTitle>Un libro</BookTitle></Book>"
               b"</BookDocument></PubmedBookArticle>"
               b"</PubmedArticleSet>")

        regs = pubmed.parsear_articulos(xml)

        self.assertEqual([r["pmid"] for r in regs], ["111"])

    def test_una_respuesta_vacia_devuelve_lista_vacia(self):
        vacio = b"<?xml version='1.0'?><PubmedArticleSet/>"
        self.assertEqual(pubmed.parsear_articulos(vacio), [])


# ------------------------------------------------------- JATS de PMC

class PruebasJats(PruebaSinRed):
    """jats_a_texto devuelve (texto, tiene_cuerpo). El segundo valor es el
    que decide si el articulo cuenta como full text o como pendiente."""

    def test_solo_metadatos_no_cuenta_como_cuerpo(self):
        """PMC responde igual para un articulo cerrado, pero sin <body>.
        Tomarlo por bueno llenaria el corpus de abstracts disfrazados de
        texto completo."""
        texto, tiene_cuerpo = pubmed.jats_a_texto(jats_xml(cuerpo=False))

        self.assertFalse(tiene_cuerpo)
        self.assertIn("Regulacion por LasR", texto)
        self.assertIn("## ABSTRACT", texto)

    def test_un_body_vacio_tampoco_cuenta(self):
        xml = (b"<article><front><article-meta>"
               b"<article-title>T</article-title></article-meta></front>"
               b"<body></body></article>")

        texto, tiene_cuerpo = pubmed.jats_a_texto(xml)

        self.assertFalse(tiene_cuerpo)

    def test_un_articulo_abierto_da_texto_con_secciones_jerarquicas(self):
        texto, tiene_cuerpo = pubmed.jats_a_texto(jats_xml(cuerpo=True))

        self.assertTrue(tiene_cuerpo)
        self.assertIn("## RESULTS", texto)
        self.assertIn("### EFECTO EN MEXT", texto)
        self.assertIn("lasR", texto)

    def test_los_pies_de_figura_y_tabla_se_conservan(self):
        """Los pies concentran relaciones TF-gen que no siempre estan en
        el cuerpo."""
        texto, _ = pubmed.jats_a_texto(jats_xml(cuerpo=True))

        self.assertIn("## PIES DE FIGURA Y TABLA", texto)
        self.assertIn("Union de LasR al promotor de rhlR", texto)
        self.assertIn("Tabla 1. Cepas usadas", texto)

    def test_los_parrafos_sueltos_del_body_no_se_pierden(self):
        xml = (b"<article><front><article-meta>"
               b"<article-title>T</article-title></article-meta></front>"
               b"<body><p>Parrafo sin seccion.</p>"
               b"<sec><title>Methods</title><p>Con seccion.</p></sec>"
               b"</body></article>")

        texto, tiene_cuerpo = pubmed.jats_a_texto(xml)

        self.assertTrue(tiene_cuerpo)
        self.assertIn("Parrafo sin seccion.", texto)
        self.assertIn("Con seccion.", texto)

    def test_un_xml_roto_no_lanza_excepcion(self):
        """Un XML truncado por una conexion cortada no puede tumbar el lote."""
        texto, tiene_cuerpo = pubmed.jats_a_texto(b"<article><body><sec>")

        self.assertEqual(texto, "")
        self.assertFalse(tiene_cuerpo)


# ----------------------------------------------- contrato del cliente

class PruebasCliente(PruebaSinRed):
    """Se prueba pubmed.Cliente sustituyendo _abrir(), su unico contacto
    con la red. Asi se verifican POST y manejo de errores sin salir."""

    def setUp(self):
        super().setUp()
        # El limitador de tasa y los reintentos duermen de verdad.
        parche = unittest.mock.patch.object(pubmed.time, "sleep")
        self.dormir = parche.start()
        self.addCleanup(parche.stop)

    @staticmethod
    def _http_error(codigo, cuerpo=b""):
        return urllib.error.HTTPError(
            "https://eutils", codigo, "err", {}, io.BytesIO(cuerpo)
        )

    def test_las_queries_booleanas_van_por_post_no_por_get(self):
        """Las queries del laboratorio rebasan los 700 caracteres; por GET
        las rechaza el servidor."""
        cliente = pubmed.Cliente("yo@unam.mx", api_key="abc123")
        query = "(Pseudomonas aeruginosa[MeSH]) AND " + " OR ".join(
            f"gen{i}[tiab]" for i in range(200))
        visto = {}

        def falso_abrir(url, datos=None, timeout=120):
            visto["url"], visto["datos"] = url, datos
            return b"<eSearchResult/>"

        cliente._abrir = falso_abrir
        cliente.eutils("esearch.fcgi", {"db": "pubmed", "term": query})

        self.assertGreater(len(query), 700)
        self.assertNotIn("?", visto["url"])
        self.assertIsNotNone(visto["datos"], "la query viajo por GET")
        cuerpo = urllib.parse.parse_qs(visto["datos"].decode())
        self.assertEqual(cuerpo["term"][0], query)
        self.assertEqual(cuerpo["email"][0], "yo@unam.mx")
        self.assertEqual(cuerpo["api_key"][0], "abc123")

    def test_un_400_de_ncbi_falla_de_inmediato_sin_reintentar(self):
        """400 es query mal formada. Reintentarla solo gasta el limite de
        peticiones de todo el laboratorio."""
        cliente = pubmed.Cliente("yo@unam.mx")
        intentos = []

        def falso_abrir(url, datos=None, timeout=120):
            intentos.append(url)
            raise self._http_error(400, b"error de sintaxis en la query")

        cliente._abrir = falso_abrir

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            cliente.eutils("esearch.fcgi", {"db": "pubmed", "term": "AND"})

        self.assertEqual(len(intentos), 1)
        self.assertIn("error de sintaxis", str(ctx.exception))

    def test_un_error_pasajero_si_se_reintenta(self):
        cliente = pubmed.Cliente("yo@unam.mx")
        intentos = []

        def falso_abrir(url, datos=None, timeout=120):
            intentos.append(url)
            if len(intentos) < 3:
                raise self._http_error(500)
            return b"<ok/>"

        cliente._abrir = falso_abrir
        salida = cliente.eutils("esearch.fcgi", {"db": "pubmed"}, intentos=5)

        self.assertEqual(salida, b"<ok/>")
        self.assertEqual(len(intentos), 3)

    def test_agotados_los_intentos_se_lanza_ErrorPubMed(self):
        cliente = pubmed.Cliente("yo@unam.mx")

        def falso_abrir(url, datos=None, timeout=120):
            raise self._http_error(500)

        cliente._abrir = falso_abrir

        with self.assertRaises(pubmed.ErrorPubMed):
            cliente.eutils("efetch.fcgi", {"db": "pubmed"}, intentos=2)

    def test_un_403_del_editor_no_se_reintenta(self):
        """El editor no atiende clientes automaticos, y lo va a contestar
        igual las cuatro veces. Reintentar cuesta 14 segundos y tres
        peticiones a un servidor que ya dijo que no."""
        cliente = pubmed.Cliente("yo@unam.mx")
        intentos = []

        def falso_abrir(url, datos=None, timeout=120):
            intentos.append(url)
            raise self._http_error(403)

        cliente._abrir = falso_abrir

        self.assertIsNone(cliente.get("https://journals.asm.org/x.pdf"))
        self.assertEqual(len(intentos), 1)

    def test_401_y_451_tambien_son_definitivos(self):
        cliente = pubmed.Cliente("yo@unam.mx")
        for codigo in (401, 451):
            intentos = []

            def falso_abrir(url, datos=None, timeout=120, _c=codigo):
                intentos.append(url)
                raise self._http_error(_c)

            cliente._abrir = falso_abrir
            self.assertIsNone(cliente.get("https://editor/x.pdf"), codigo)
            self.assertEqual(len(intentos), 1, codigo)

    def test_agotados_los_intentos_get_lanza_en_vez_de_devolver_none(self):
        """La mitad del contrato que sostiene todo lo demas.

        Quien llama traduce None a 'no_disponible', que no se reintenta
        nunca. Si una caida de red se colara como None, un corte de dos
        minutos marcaria un lote entero como sin acceso abierto, de forma
        permanente y sin manera de recuperarlo con --reintentar.
        """
        cliente = pubmed.Cliente("yo@unam.mx")

        def falso_abrir(url, datos=None, timeout=120):
            raise self._http_error(500)

        cliente._abrir = falso_abrir

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            cliente.get("https://ebi.ac.uk/x", intentos=2)

        self.assertIn("2 intentos", str(ctx.exception))

    def test_un_corte_de_transporte_en_get_lanza_ErrorPubMed(self):
        cliente = pubmed.Cliente("yo@unam.mx")

        def falso_abrir(url, datos=None, timeout=120):
            raise OSError("se corto la conexion")

        cliente._abrir = falso_abrir

        with self.assertRaises(pubmed.ErrorPubMed):
            cliente.get("https://ebi.ac.uk/x", intentos=2)

    def test_get_no_filtra_la_query_string_en_el_mensaje_de_error(self):
        """El correo viaja en la query string de Unpaywall; el mensaje de
        error puede acabar en la bitacora y en el tablero."""
        cliente = pubmed.Cliente("yo@unam.mx")

        def falso_abrir(url, datos=None, timeout=120):
            raise self._http_error(500)

        cliente._abrir = falso_abrir

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            cliente.get("https://api.unpaywall.org/v2/10.1/x",
                        {"email": "yo@unam.mx"}, intentos=1)

        self.assertNotIn("yo@unam.mx", str(ctx.exception))

    def test_un_404_devuelve_none_sin_reintentar(self):
        """404 de Unpaywall es un DOI no registrado, no una falla."""
        cliente = pubmed.Cliente("yo@unam.mx")
        intentos = []

        def falso_abrir(url, datos=None, timeout=120):
            intentos.append(url)
            raise self._http_error(404)

        cliente._abrir = falso_abrir
        salida = cliente.get("https://api.unpaywall.org/v2/10.1/x")

        self.assertIsNone(salida)
        self.assertEqual(len(intentos), 1)

    def test_el_cliente_exige_correo_de_contacto(self):
        """NCBI lo pide para poder avisar antes de bloquear la IP."""
        with self.assertRaises(ValueError):
            pubmed.Cliente("")

    def test_la_pausa_es_mas_corta_con_api_key(self):
        self.assertGreater(pubmed.Cliente("yo@unam.mx").pausa,
                           pubmed.Cliente("yo@unam.mx", api_key="k").pausa)
