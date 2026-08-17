# -*- coding: utf-8 -*-
"""Cliente de las APIs externas: E-utilities, PMC e Unpaywall.

Esta capa no sabe nada de la base de datos. Recibe parametros, devuelve
diccionarios. Eso la hace probable sin red y reutilizable desde un
servicio web sin cambios.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# Ruta documentada del ID Converter. La anterior
# (www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/) sigue respondiendo, pero ya
# no aparece en la documentacion de la API y vive en el dominio que PMC
# esta desmontando. Se verifico que las dos devuelven la misma estructura.
IDCONV = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
OA_SERVICE = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
UNPAYWALL = "https://api.unpaywall.org/v2"
TOOL = "grn-etl"


class ErrorPubMed(RuntimeError):
    pass


class Cliente:
    """Cliente con control de tasa y reintentos.

    NCBI permite 3 peticiones/segundo sin API key y 10 con ella.
    El control es por instancia, asi que un servicio con varios workers
    necesitaria un limitador compartido (Redis) en vez de este.
    """

    def __init__(self, email, api_key=None, tool=TOOL):
        if not email:
            raise ValueError("NCBI exige un correo de contacto")
        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.pausa = 0.11 if api_key else 0.36
        self._ultima = 0.0

    def _esperar(self, pausa=None):
        p = self.pausa if pausa is None else pausa
        d = time.time() - self._ultima
        if d < p:
            time.sleep(p - d)
        self._ultima = time.time()

    def _abrir(self, url, datos=None, timeout=120):
        req = urllib.request.Request(
            url, data=datos,
            headers={"User-Agent": f"{self.tool} ({self.email})"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def eutils(self, endpoint, params, intentos=5):
        """POST a E-utilities. POST y no GET porque las queries booleanas
        largas rebasan el limite de longitud de URL."""
        params = {**params, "tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        datos = urllib.parse.urlencode(params).encode()
        url = f"{EUTILS}/{endpoint}"

        for i in range(1, intentos + 1):
            self._esperar()
            try:
                return self._abrir(url, datos)
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    raise ErrorPubMed(
                        f"NCBI rechazo la peticion (400). Revisa la query.\n"
                        f"{e.read().decode('utf-8', 'replace')[:400]}"
                    ) from e
                if i == intentos:
                    raise ErrorPubMed(f"{endpoint} fallo tras {intentos} intentos: {e}")
                time.sleep(min(2 ** i, 30))
            except Exception as e:
                if i == intentos:
                    raise ErrorPubMed(f"{endpoint} fallo tras {intentos} intentos: {e}")
                time.sleep(min(2 ** i, 30))

    def get(self, url, params=None, intentos=4, pausa=None, tolerar_404=True):
        """GET generico. Devuelve bytes o None si no se pudo."""
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        for i in range(1, intentos + 1):
            self._esperar(pausa)
            try:
                return self._abrir(url)
            except urllib.error.HTTPError as e:
                if e.code in (404, 422) and tolerar_404:
                    return None
                if i == intentos:
                    return None
                time.sleep(min(2 ** i, 20))
            except Exception:
                if i == intentos:
                    return None
                time.sleep(min(2 ** i, 20))
        return None


# ------------------------------------------------------------------ buscar

# Tope duro de esearch para PubMed y PMC. No es el tope de retmax: es
# cuantos registros existe forma de recuperar de un mismo conjunto de
# resultados. La documentacion (NBK25499) lo dice sin rodeos: "For PubMed
# and PMC, ESearch can only retrieve the first 10,000 records matching the
# query", y la receta de ir subiendo retstart la limita explicitamente a
# "databases other than PubMed or PMC". Para pasar de ahi manda partir la
# consulta en tramos de fecha.
TOPE_ESEARCH = 10000


def buscar_pmids(cliente, query, mindate=None, maxdate=None, orden="relevance",
                 limite=None, avisos=None):
    """esearch de una consulta. Devuelve (total_reportado, lista_de_pmids).

    Se traen los PMIDs completos ANTES de descargar nada. Asi se puede
    comparar contra la base y bajar solo lo que falta.

    Una sola peticion con retmax en el tope: para PubMed no hay segunda
    pagina que valga. Si la consulta trae mas de TOPE_ESEARCH resultados
    se falla de inmediato en vez de devolver lo que quepa, porque el
    llamador no tiene como distinguir una lista completa de una truncada:
    guardaria 10,000 de 25,000 y cerraria la ejecucion con estatus 'ok'.
    Un corpus incompleto que la bitacora presenta como completo es peor
    que una corrida que no arranca.
    """
    base = {"db": "pubmed", "term": query, "sort": orden, "retmode": "xml"}
    if mindate or maxdate:
        base["datetype"] = "pdat"
        base["mindate"] = mindate or "1800"
        base["maxdate"] = maxdate or "3000"

    raiz = ET.fromstring(cliente.eutils(
        "esearch.fcgi", {**base, "retstart": "0", "retmax": str(TOPE_ESEARCH)}
    ))
    err = raiz.findtext(".//ERROR")
    if err:
        raise ErrorPubMed(f"esearch: {err}")

    total = int(raiz.findtext("Count", "0"))
    if avisos is not None:
        for w in raiz.findall(".//WarningList/*"):
            avisos.append(f"[{w.tag}] {(w.text or '').strip()}")

    pmids = [e.text for e in raiz.findall(".//IdList/Id") if e.text]

    # Con --limite el usuario ya dijo que no quiere todo, asi que un total
    # enorme no lo sorprende: se recorta y ya. Sin limite, callarse el
    # recorte seria mentir sobre lo que se trajo.
    if total > TOPE_ESEARCH and not limite:
        raise ErrorPubMed(
            f"La consulta trae {total} resultados y PubMed solo permite "
            f"recuperar los primeros {TOPE_ESEARCH} de un mismo conjunto.\n"
            f"Partela por fechas y corre cada tramo: "
            f"--desde 1990 --hasta 2009, luego --desde 2010, etc. "
            f"Los tramos se acumulan en la misma consulta sin duplicar nada.\n"
            f"Para explorar sin bajar todo, usa --limite N."
        )

    if limite:
        pmids = pmids[:limite]
    return total, pmids


# ------------------------------------------------------------------ fetch

def _txt(nodo):
    return "".join(nodo.itertext()).strip() if nodo is not None else ""


def _limpio(s):
    return " ".join(s.split())


def _abstract(article):
    """Reconstruye el abstract conservando las etiquetas de seccion."""
    partes = []
    for at in article.findall(".//Abstract/AbstractText"):
        t = _limpio(_txt(at))
        if not t:
            continue
        etiqueta = at.get("Label") or at.get("NlmCategory")
        partes.append(f"{etiqueta.strip()}: {t}"
                      if etiqueta and etiqueta.upper() != "UNLABELLED" else t)
    return " ".join(partes)


def _anio(article):
    y = article.findtext(".//Journal/JournalIssue/PubDate/Year")
    if y:
        return y.strip()
    md = article.findtext(".//Journal/JournalIssue/PubDate/MedlineDate", "")
    for tok in md.replace("-", " ").split():
        if tok.isdigit() and len(tok) == 4:
            return tok
    return ""


def _doi(pa):
    for el in pa.findall(".//Article/ELocationID"):
        if el.get("EIdType") == "doi" and el.text:
            return el.text.strip()
    for aid in pa.findall(".//PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi" and aid.text:
            return aid.text.strip()
    return ""


def parsear_articulos(xml_bytes):
    raiz = ET.fromstring(xml_bytes)
    salida = []
    for pa in raiz.findall(".//PubmedArticle"):
        art = pa.find(".//Article")
        if art is None:
            continue
        pmid = (pa.findtext(".//MedlineCitation/PMID") or "").strip()
        autores = []
        for au in art.findall(".//AuthorList/Author"):
            ap = (au.findtext("LastName") or "").strip()
            ini = (au.findtext("Initials") or "").strip()
            col = (au.findtext("CollectiveName") or "").strip()
            if ap:
                autores.append(f"{ap} {ini}".strip())
            elif col:
                autores.append(col)
        salida.append({
            "pmid": pmid,
            "doi": _doi(pa),
            "pmcid": "",
            "titulo": _limpio(_txt(art.find("ArticleTitle"))),
            "abstract": _abstract(art),
            "revista": _limpio(art.findtext(".//Journal/ISOAbbreviation", "")
                               or art.findtext(".//Journal/Title", "")),
            "anio": _anio(art),
            "autores": autores,
            "mesh_terms": [_limpio(_txt(d)) for d in pa.findall(
                ".//MeshHeadingList/MeshHeading/DescriptorName")],
            "keywords": [k for k in (_limpio(_txt(x)) for x in
                                     pa.findall(".//KeywordList/Keyword")) if k],
            "tipos_publicacion": [_limpio(_txt(t)) for t in art.findall(
                ".//PublicationTypeList/PublicationType")],
        })
    return salida


def traer_articulos(cliente, pmids, tam_lote=200, al_avanzar=None):
    """efetch por lista explicita de PMIDs (no por historial).

    Con lista explicita se controla exactamente que se pide, que es lo
    que permite pedir solo la diferencia contra la base.
    """
    todos = []
    for i in range(0, len(pmids), tam_lote):
        lote = pmids[i:i + tam_lote]
        xml_bytes = cliente.eutils("efetch.fcgi", {
            "db": "pubmed", "id": ",".join(lote), "retmode": "xml",
        })
        regs = parsear_articulos(xml_bytes)
        todos.extend(regs)
        if al_avanzar:
            al_avanzar(min(i + tam_lote, len(pmids)), len(pmids), len(regs))
    return todos


# -------------------------------------------------------------- full text

def convertir_ids(cliente, pmids, tam_lote=180):
    """PMID -> PMCID / DOI via el ID Converter de PMC.

    Si el servicio no contesta, se falla en vez de devolver un mapa a
    medias. Antes se seguia de largo, y el efecto era destructivo y mudo:
    los PMIDs de ese lote quedaban sin PMCID, y quien llama no distingue
    "este articulo no esta en PMC" de "no pude preguntar". El ETL los
    escribe como 'no_disponible', que por diseno no se reintenta nunca,
    asi que una caida de unos minutos condenaba hasta 180 articulos de
    acceso abierto de forma permanente.
    """
    mapa = {}
    for i in range(0, len(pmids), tam_lote):
        lote = pmids[i:i + tam_lote]
        datos = cliente.get(IDCONV, {
            "ids": ",".join(lote), "format": "json",
            "tool": cliente.tool, "email": cliente.email,
        })
        if not datos:
            raise ErrorPubMed(
                f"El ID Converter de PMC no respondio (lote de {len(lote)} "
                f"PMIDs desde {lote[0]}). No se marca nada como no disponible: "
                f"vuelve a correr cuando el servicio responda."
            )
        try:
            j = json.loads(datos)
        except json.JSONDecodeError:
            raise ErrorPubMed(
                "El ID Converter de PMC respondio algo que no es JSON. "
                "Puede que la ruta del servicio haya cambiado."
            )
        for rec in j.get("records", []):
            if rec.get("pmid"):
                # El ID Converter manda el PMID como NUMERO de JSON
                # ("pmid":37569271), no como cadena. En el resto del
                # sistema los PMIDs son texto, incluida la columna
                # documentos.pmid. Sin este str() la llave del mapa es un
                # entero, ningun mapa.get(pmid) acierta, y un articulo de
                # acceso abierto termina marcado 'no_disponible' para
                # siempre.
                mapa[str(rec["pmid"])] = {
                    "pmcid": rec.get("pmcid") or "",
                    "doi": rec.get("doi") or "",
                }
    return mapa


def url_articulo_pmc(pmcid):
    """URL humana del articulo en PMC.

    No se usa para descargar (para eso esta efetch, que devuelve JATS
    estructurado y es la via que NCBI habilita para acceso programatico).
    Se guarda en 'descargas' para poder volver a la fuente desde la base
    sin rearmar la liga a mano, y para que la lista de pendientes le diga
    a quien la lea exactamente donde esta el articulo.
    """
    return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else ""


def url_articulo_pubmed(pmid):
    """URL del registro en PubMed. Es el pointer que queda cuando no hay
    PMCID: el articulo no esta en PMC, pero su ficha si."""
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def traer_xml_pmc(cliente, pmcid):
    return cliente.eutils("efetch.fcgi", {
        "db": "pmc", "id": pmcid.replace("PMC", ""), "retmode": "xml",
    })


def jats_a_texto(xml_bytes):
    """JATS -> texto plano por secciones. Devuelve (texto, tiene_cuerpo).

    tiene_cuerpo=False significa que PMC solo entrego metadatos, o sea
    que el articulo no esta en el subset de acceso abierto.
    """
    try:
        raiz = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return "", False

    partes = []
    tit = raiz.find(".//article-meta//article-title")
    if tit is not None:
        partes.append("# " + _limpio(_txt(tit)))

    for ab in raiz.findall(".//article-meta/abstract"):
        partes.append("\n## ABSTRACT")
        partes.extend(t for t in (_limpio(_txt(p)) for p in ab.findall(".//p")) if t)

    body = raiz.find(".//body")
    tiene_cuerpo = body is not None and len(list(body)) > 0
    if not tiene_cuerpo:
        return "\n\n".join(partes), False

    def recorrer(nodo, nivel=2):
        for sec in nodo.findall("sec"):
            st = _limpio(_txt(sec.find("title")))
            if st:
                partes.append(f"\n{'#' * nivel} {st.upper()}")
            partes.extend(t for t in (_limpio(_txt(p)) for p in sec.findall("p")) if t)
            recorrer(sec, min(nivel + 1, 5))

    partes.extend(t for t in (_limpio(_txt(p)) for p in body.findall("p")) if t)
    recorrer(body)

    # Los pies de figura y tabla suelen concentrar relaciones TF-gen
    pies = [t for t in (_limpio(_txt(c)) for c in
                        raiz.findall(".//fig/caption") +
                        raiz.findall(".//table-wrap/caption")) if t]
    if pies:
        partes.append("\n## PIES DE FIGURA Y TABLA")
        partes.extend(pies)

    return "\n\n".join(partes), True


def liga_pdf_pmc(cliente, pmcid):
    """OA Service de PMC. Devuelve la URL del PDF, o None si no hay.

    None significa una sola cosa: el servicio contesto y ese articulo no
    tiene PDF abierto. Si el servicio NO contesta se lanza ErrorPubMed,
    porque las dos situaciones terminan en lugares opuestos: 'no hay PDF'
    se registra como 'no_disponible', que nunca se reintenta, y 'no pude
    preguntar' tiene que quedar como 'error', que si se reintenta con
    --reintentar. Confundirlas escribe una mentira permanente en la base.

    Importa mas de lo que parece: NCBI anuncio el retiro de este servicio
    (el aviso del 30 de julio de 2026 habla del 24 de agosto en adelante).
    Cuando deje de responder, sin esta distincion el ETL marcaria como
    'sin PDF de acceso abierto' a articulos que si lo tienen, y no habria
    forma de recuperarlos sin borrar filas a mano.
    """
    datos = cliente.get(OA_SERVICE, {"id": pmcid})
    if not datos:
        raise ErrorPubMed(
            f"El OA Service de PMC no respondio por {pmcid}. No se marca "
            f"como sin PDF: puede ser una caida, o el retiro anunciado del "
            f"servicio."
        )
    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError:
        raise ErrorPubMed(
            f"El OA Service de PMC respondio algo que no es XML por {pmcid}."
        )
    if raiz.find(".//error") is not None:
        return None
    for link in raiz.findall(".//record/link"):
        if link.get("format") == "pdf":
            # El servicio responde ftp://; https pasa mejor tras un firewall
            return link.get("href", "").replace(
                "ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov")
    return None


def liga_pdf_unpaywall(cliente, doi, email):
    """Unpaywall indexa copias legales de acceso abierto (repositorios,
    preprints, versiones de autor). Devuelve (url, fuente) o (None, None)."""
    if not doi:
        return None, None
    datos = cliente.get(f"{UNPAYWALL}/{urllib.parse.quote(doi)}",
                        {"email": email}, pausa=0.15)
    if not datos:
        return None, None
    try:
        j = json.loads(datos)
    except json.JSONDecodeError:
        return None, None
    mejor = j.get("best_oa_location")
    if not mejor:
        return None, None
    url = mejor.get("url_for_pdf") or mejor.get("url")
    repo = mejor.get("repository_institution") or mejor.get("host_type") or ""
    return url, repo
