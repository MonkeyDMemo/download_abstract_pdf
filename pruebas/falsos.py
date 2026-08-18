# -*- coding: utf-8 -*-
"""Dobles de prueba: un cliente falso y fabricas de XML/JSON fijos.

El cliente falso reemplaza a pubmed.Cliente con la misma superficie
(eutils, get, email, tool) pero sin red y sin pausas. Ademas registra
cada llamada, que es lo que permite afirmar cosas como "la segunda
ingesta no llamo a efetch".

Nada aqui usa librerias externas: solo unittest, json y sqlite3 de la
estandar, igual que el codigo que prueba.
"""

import json
import unittest
import unittest.mock
import urllib.parse
import urllib.request

from grn_etl import pubmed


# ------------------------------------------------------- guardia de red

class PruebaSinRed(unittest.TestCase):
    """Base de todas las pruebas: deja urlopen inutilizable.

    No basta con inyectar un cliente falso. Si alguna prueba futura arma
    un pubmed.Cliente de verdad por descuido, esto la hace fallar en el
    acto en vez de salir a NCBI desde la maquina de quien corre la suite.
    """

    def setUp(self):
        super().setUp()

        def prohibido(*_a, **_k):
            raise AssertionError(
                "una prueba intento abrir la red; usa ClienteFalso"
            )

        parche = unittest.mock.patch.object(
            urllib.request, "urlopen", side_effect=prohibido
        )
        parche.start()
        self.addCleanup(parche.stop)


# ------------------------------------------------------- fabricas de XML

def articulo_xml(pmid, titulo=None, abstract="Texto del abstract.",
                 anio="2020", doi=None, revista="J Bacteriol",
                 autores=(("Perez", "AB"),), mesh=("Pseudomonas aeruginosa",),
                 keywords=("quorum sensing",), tipos=("Journal Article",)):
    """Un <PubmedArticle> completo con valores por omision razonables."""
    titulo = titulo if titulo is not None else f"Articulo {pmid}"
    doi = doi if doi is not None else f"10.1000/prueba.{pmid}"
    aut = "".join(
        f"<Author><LastName>{ap}</LastName><Initials>{ini}</Initials></Author>"
        for ap, ini in autores
    )
    ms = "".join(
        f"<MeshHeading><DescriptorName>{m}</DescriptorName></MeshHeading>"
        for m in mesh
    )
    kw = "".join(f"<Keyword>{k}</Keyword>" for k in keywords)
    tp = "".join(f"<PublicationType>{t}</PublicationType>" for t in tipos)
    ab = f"<Abstract><AbstractText>{abstract}</AbstractText></Abstract>" if abstract else ""
    return f"""
  <PubmedArticle>
    <MedlineCitation>
      <PMID>{pmid}</PMID>
      <Article>
        <Journal>
          <JournalIssue><PubDate><Year>{anio}</Year></PubDate></JournalIssue>
          <ISOAbbreviation>{revista}</ISOAbbreviation>
        </Journal>
        <ArticleTitle>{titulo}</ArticleTitle>
        {ab}
        <AuthorList>{aut}</AuthorList>
        <ELocationID EIdType="doi">{doi}</ELocationID>
        <PublicationTypeList>{tp}</PublicationTypeList>
      </Article>
      <MeshHeadingList>{ms}</MeshHeadingList>
      <KeywordList>{kw}</KeywordList>
    </MedlineCitation>
  </PubmedArticle>"""


def conjunto_xml(fragmentos):
    return ("<?xml version='1.0'?><PubmedArticleSet>"
            + "".join(fragmentos) + "</PubmedArticleSet>").encode()


def esearch_xml(total, pmids, avisos=()):
    ids = "".join(f"<Id>{p}</Id>" for p in pmids)
    wl = ""
    if avisos:
        wl = "<WarningList>" + "".join(
            f"<QuotedPhraseNotFound>{a}</QuotedPhraseNotFound>" for a in avisos
        ) + "</WarningList>"
    return (f"<?xml version='1.0'?><eSearchResult><Count>{total}</Count>"
            f"<IdList>{ids}</IdList>{wl}</eSearchResult>").encode()


def jats_xml(titulo="Regulacion por LasR", abstract="Resumen del articulo.",
             cuerpo=True):
    """JATS de PMC. Con cuerpo=False simula un articulo que no es OA:
    PMC responde con los metadatos y sin <body>."""
    body = ""
    if cuerpo:
        body = """
  <body>
    <sec>
      <title>Results</title>
      <p>El regulador <italic>lasR</italic> activa a <italic>rhlR</italic>.</p>
      <sec>
        <title>Efecto en mexT</title>
        <p>La represion de <italic>mexT</italic> es indirecta.</p>
      </sec>
    </sec>
  </body>
  <floats-group>
    <fig><caption><p>Figura 1. Union de LasR al promotor de rhlR.</p></caption></fig>
    <table-wrap><caption><p>Tabla 1. Cepas usadas.</p></caption></table-wrap>
  </floats-group>"""
    return f"""<?xml version='1.0'?>
<article>
  <front>
    <article-meta>
      <article-title>{titulo}</article-title>
      <abstract><p>{abstract}</p></abstract>
    </article-meta>
  </front>{body}
</article>""".encode()


def oa_xml(pmcid, url="ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/x.pdf"):
    return (f"<?xml version='1.0'?><OA><records><record id='{pmcid}'>"
            f"<link format='pdf' href='{url}'/>"
            f"</record></records></OA>").encode()


def oa_error_xml():
    return (b"<?xml version='1.0'?><OA><error code='idIsNotOpenAccess'>"
            b"no esta en el subset abierto</error></OA>")


def epmc_json(pmcid, url=None, estilo="pdf", codigo="OA", sitio="Europe_PMC"):
    """Respuesta de busqueda de Europe PMC con una liga de texto completo.

    Los valores por omision son los de un articulo abierto alojado en
    Europe PMC, que es el unico caso que liga_pdf_europepmc acepta.
    Cambiando 'sitio' o 'codigo' se prueban los que debe descartar.
    """
    url = url or f"https://europepmc.org/articles/{pmcid}?pdf=render"
    return {"resultList": {"result": [{
        "pmcid": pmcid,
        "fullTextUrlList": {"fullTextUrl": [
            {"documentStyle": estilo, "site": sitio,
             "availabilityCode": codigo, "url": url},
        ]},
    }]}}


def epmc_vacio():
    """Lo que contesta Europe PMC cuando no tiene el articulo: 200 con la
    lista vacia. NO es lo mismo que no contestar."""
    return {"resultList": {"result": []}}


PDF_VALIDO = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n%%EOF\n"


# ------------------------------------------------------- cliente falso

class ClienteFalso:
    """Sustituto de pubmed.Cliente. Sin red, sin pausas, con bitacora.

    universo:   PMIDs que devuelve esearch para cualquier consulta.
    universos:  {texto_de_la_query: [pmids]} cuando hay varias consultas.
    articulos:  {pmid: fragmento_xml}. Un PMID del universo que no este
                aqui simula un registro retirado o de tipo Book: esearch
                lo lista pero efetch no lo devuelve.
    """

    def __init__(self, universo=None, universos=None, articulos=None,
                 xml_pmc=None, mapa_ids=None, oa=None, unpaywall=None,
                 cuerpos=None, fallas=None, europepmc=None,
                 email="prueba@unam.mx",
                 tool="grn-etl-prueba"):
        self.universo = list(universo) if universo else None
        self.universos = universos or {}
        self.articulos = dict(articulos) if articulos is not None else None
        self.xml_pmc = xml_pmc or {}
        self.mapa_ids = mapa_ids or {}
        self.oa = oa or {}
        self.unpaywall = unpaywall or {}
        self.cuerpos = cuerpos or {}
        self.europepmc = europepmc or {}
        self.fallas = fallas or {}
        self.email = email
        self.tool = tool
        self.avisos_esearch = []
        # PubMed reporta en <Count> el total real aunque solo entregue los
        # primeros 10,000. Poder declarar un total distinto del universo es
        # lo que permite probar ese caso sin fabricar 25,000 ids.
        self.total_declarado = None
        self.llamadas = []

    # --- bitacora -------------------------------------------------------

    def reiniciar(self):
        """Borra la bitacora. Se usa entre la primera y la segunda ingesta."""
        self.llamadas = []

    def n_eutils(self, endpoint, db=None):
        return len([c for c in self.llamadas
                    if c[0] == "eutils" and c[1] == endpoint
                    and (db is None or c[2].get("db") == db)])

    def pmids_pedidos(self):
        """Todos los PMIDs que se le pidieron a efetch de PubMed, en orden."""
        salida = []
        for c in self.llamadas:
            if c[0] == "eutils" and c[1] == "efetch.fcgi" and c[2].get("db") == "pubmed":
                salida.extend(c[2]["id"].split(","))
        return salida

    def urls_pedidas(self):
        return [c[1] for c in self.llamadas if c[0] == "get"]

    # --- superficie de pubmed.Cliente -----------------------------------

    def eutils(self, endpoint, params, intentos=5):
        self.llamadas.append(("eutils", endpoint, dict(params)))
        falla = self.fallas.get(endpoint)
        if falla:
            raise falla

        if endpoint == "esearch.fcgi":
            return self._esearch(params)
        if endpoint == "efetch.fcgi" and params.get("db") == "pmc":
            return self._efetch_pmc(params)
        if endpoint == "efetch.fcgi":
            return self._efetch_pubmed(params)
        raise AssertionError(f"endpoint no previsto en la prueba: {endpoint}")

    def get(self, url, params=None, intentos=4, pausa=None,
            definitivos=pubmed.HTTP_DEFINITIVOS):
        self.llamadas.append(("get", url, dict(params or {})))

        # 'fallas' por URL simula el servicio que no contesta. Hace falta
        # ahora que None significa "contesto que no": sin esto no habria
        # forma declarativa de probar la otra mitad del contrato.
        falla = self.fallas.get(url)
        if falla:
            raise falla

        if url == pubmed.IDCONV:
            pedidos = (params or {}).get("ids", "").split(",")
            # El ID Converter manda el PMID como NUMERO de JSON, no como
            # cadena, al reves que esearch y efetch. La fabrica lo imita a
            # proposito: cuando devolvia cadena, tapaba un defecto real.
            recs = [{"pmid": int(p), **self.mapa_ids[p]}
                    for p in pedidos if p in self.mapa_ids]
            return json.dumps({"records": recs}).encode()

        if url == pubmed.OA_SERVICE:
            return self.oa.get((params or {}).get("id"))

        if url == pubmed.EPMC:
            # Por omision contesta "no lo tengo" con una lista vacia, no
            # None: un PMCID desconocido es una respuesta valida, y asi
            # las pruebas de PDF que ya existian siguen significando lo
            # mismo sin tener que declarar este canal.
            pmcid = (params or {}).get("query", "").replace("PMCID:", "")
            return json.dumps(
                self.europepmc.get(pmcid) or epmc_vacio()).encode()

        if url.startswith(pubmed.UNPAYWALL):
            # El DOI trae diagonales, que quote() no escapa: se corta por
            # prefijo y no por la ultima diagonal.
            doi = urllib.parse.unquote(url[len(pubmed.UNPAYWALL) + 1:])
            cuerpo = self.unpaywall.get(doi)
            return json.dumps(cuerpo).encode() if cuerpo is not None else None

        return self.cuerpos.get(url)

    # --- respuestas -----------------------------------------------------

    def _pmids_de(self, term):
        if self.universo is not None:
            return self.universo
        return self.universos.get(term, [])

    def _esearch(self, params):
        pmids = self._pmids_de(params.get("term"))
        inicio = int(params.get("retstart", 0))
        tam = int(params.get("retmax", 9000))
        total = len(pmids) if self.total_declarado is None else self.total_declarado
        return esearch_xml(total, pmids[inicio:inicio + tam],
                           self.avisos_esearch)

    def _efetch_pubmed(self, params):
        pedidos = params["id"].split(",")
        if self.articulos is None:
            frags = [articulo_xml(p) for p in pedidos]
        else:
            frags = [self.articulos[p] for p in pedidos if p in self.articulos]
        return conjunto_xml(frags)

    def _efetch_pmc(self, params):
        pmcid = "PMC" + params["id"]
        falla = self.fallas.get(pmcid)
        if falla:
            raise falla
        return self.xml_pmc.get(pmcid, jats_xml(cuerpo=False))
