# -*- coding: utf-8 -*-
"""Orquestacion del ETL.

Dos operaciones, ambas idempotentes y ambas por lotes:

    ingestar(...)          consulta -> abstracts en la base
    descargar_fulltext(..) documentos en la base -> XML / PDF en disco

Ninguna de las dos habla con la terminal: reportan por callback. Por eso
el mismo codigo sirve para el CLI de hoy y para un endpoint HTTP manana.
"""

from pathlib import Path

from . import db, pubmed


def _nada(*_a, **_k):
    pass


# ------------------------------------------------------------- abstracts

def ingestar(con, cliente, nombre_consulta, orden="relevance", limite=None,
             mindate=None, maxdate=None, tam_lote=200, log=_nada):
    """Corre una consulta y guarda los abstracts que falten.

    El flujo es: pedir a PubMed la lista completa de PMIDs, restarle lo
    que ya esta en la base, y descargar solo la diferencia. Correr esto
    dos veces seguidas no genera trafico de descarga la segunda vez.
    """
    consulta = db.obtener_consulta(con, nombre_consulta)
    if not consulta:
        raise ValueError(f"No existe la consulta '{nombre_consulta}'")

    ejecucion_id = db.abrir_ejecucion(con, consulta["id"])

    try:
        avisos = []
        log(f"Buscando en PubMed (orden: {orden})...")
        total, pmids = pubmed.buscar_pmids(
            cliente, consulta["texto"], mindate, maxdate, orden, limite, avisos
        )
        for a in avisos:
            log(f"  aviso de NCBI: {a}")
        log(f"PubMed reporta {total} articulos; se consideran {len(pmids)}.")

        conocidos = db.pmids_conocidos(con, pmids)
        faltantes = [p for p in pmids if p not in conocidos]
        log(f"Ya en la base: {len(conocidos)}   por descargar: {len(faltantes)}")

        descargados = 0
        if faltantes:
            def avance(hechos, total_f, n):
                log(f"  efetch {hechos}/{total_f} (+{n} registros)")

            registros = pubmed.traer_articulos(
                cliente, faltantes, tam_lote, al_avanzar=avance
            )
            descargados = db.guardar_documentos(con, registros)

            recuperados = {r["pmid"] for r in registros}
            perdidos = set(faltantes) - recuperados
            if perdidos:
                log(f"  {len(perdidos)} PMIDs no devolvieron registro "
                    f"(retirados o de tipo Book)")

        # Se vinculan TODOS los pmids, no solo los nuevos: un articulo ya
        # descargado por otra consulta tambien pertenece a esta. Los que
        # efetch no devolvio los descarta db.vincular(), que no liga lo que
        # no esta en 'documentos'.
        db.vincular(con, consulta["id"], pmids, ejecucion_id)

        db.cerrar_ejecucion(
            con, ejecucion_id, "ok",
            total_pubmed=total, pmids_nuevos=len(faltantes),
            pmids_previos=len(conocidos), descargados=descargados,
        )
        return {
            "ejecucion_id": ejecucion_id, "total_pubmed": total,
            "considerados": len(pmids), "previos": len(conocidos),
            "nuevos": len(faltantes), "descargados": descargados,
        }

    except Exception as e:
        db.cerrar_ejecucion(con, ejecucion_id, "error", error=str(e)[:500])
        raise


# -------------------------------------------------------------- full text

def descargar_fulltext(con, cliente, tipo="xml", nombre_consulta=None,
                       limite=None, reintentar=False, salida="datos/fulltext",
                       usar_unpaywall=True, log=_nada):
    """Baja XML de PMC o PDF de acceso abierto para lo que falte.

    Corre DESPUES de la ingesta de abstracts, sobre lo que ya esta en la
    base. Cada resultado se registra en 'descargas', asi que reanudar una
    corrida interrumpida solo continua con lo pendiente.

    Sobre el orden: conviene correr tipo='xml' primero. El JATS de PMC ya
    viene con secciones separadas y sin ligaduras rotas, asi que para el
    clasificador de relaciones es mejor insumo que un PDF re-parseado.
    """
    if tipo not in ("xml", "pdf"):
        raise ValueError("tipo debe ser 'xml' o 'pdf'")

    base = Path(salida) / tipo
    base.mkdir(parents=True, exist_ok=True)

    filas = db.pendientes_descarga(con, tipo, nombre_consulta, limite, reintentar)
    if not filas:
        log("No hay nada pendiente.")
        return {"pendientes": 0, "ok": 0, "no_disponible": 0, "error": 0}

    log(f"Pendientes de {tipo}: {len(filas)}")

    # Resolver PMCID/DOI de los que aun no lo tienen
    sin_ids = [f["pmid"] for f in filas if not f["pmcid"]]
    mapa = {}
    if sin_ids:
        log(f"Resolviendo PMCID/DOI de {len(sin_ids)}...")
        mapa = pubmed.convertir_ids(cliente, sin_ids)
        for pmid, ids in mapa.items():
            db.actualizar_ids(con, pmid, ids.get("pmcid"), ids.get("doi"))

    cuenta = {"ok": 0, "no_disponible": 0, "error": 0}

    for n, fila in enumerate(filas, 1):
        pmid = fila["pmid"]
        pmcid = fila["pmcid"] or mapa.get(pmid, {}).get("pmcid", "")
        doi = fila["doi"] or mapa.get(pmid, {}).get("doi", "")
        prefijo = f"  [{n}/{len(filas)}] {pmid}"

        try:
            if tipo == "xml":
                estado = _bajar_xml(cliente, con, base, pmid, pmcid, log, prefijo)
            else:
                estado = _bajar_pdf(cliente, con, base, pmid, pmcid, doi,
                                    usar_unpaywall, log, prefijo)
        except Exception as e:
            db.registrar_descarga(con, pmid, tipo, "error", nota=str(e)[:300])
            log(f"{prefijo} error: {e}")
            estado = "error"

        cuenta[estado] = cuenta.get(estado, 0) + 1

    return {"pendientes": len(filas), **cuenta}


def _bajar_xml(cliente, con, base, pmid, pmcid, log, prefijo):
    if not pmcid:
        # Sin PMCID no hay a donde ir en PMC, pero la ficha de PubMed si
        # existe: queda como la liga para conseguirlo por otra via.
        db.registrar_descarga(con, pmid, "xml", "no_disponible",
                              nota="sin PMCID (no esta en PMC)",
                              url=pubmed.url_articulo_pubmed(pmid))
        log(f"{prefijo} sin PMCID")
        return "no_disponible"

    url = pubmed.url_articulo_pmc(pmcid)
    xml_bytes = pubmed.traer_xml_pmc(cliente, pmcid)
    texto, tiene_cuerpo = pubmed.jats_a_texto(xml_bytes)

    if not tiene_cuerpo:
        # PMC tiene el articulo pero no lo entrega por la API. La liga
        # importa mas aqui que en el caso feliz: es donde alguien va a
        # tener que ir a leerlo.
        db.registrar_descarga(con, pmid, "xml", "no_disponible", fuente="PMC",
                              nota="PMC solo entrego metadatos (no es OA)",
                              url=url)
        log(f"{prefijo} solo metadatos")
        return "no_disponible"

    (base / f"{pmid}_{pmcid}.xml").write_bytes(xml_bytes)
    ruta_txt = base / f"{pmid}_{pmcid}.txt"
    ruta_txt.write_text(texto, encoding="utf-8")
    db.registrar_descarga(con, pmid, "xml", "ok", fuente="PMC",
                          ruta=str(ruta_txt), tam=len(texto), url=url)
    log(f"{prefijo} texto completo, {len(texto):,} caracteres")
    return "ok"


def _bajar_pdf(cliente, con, base, pmid, pmcid, doi, usar_unpaywall, log, prefijo):
    url, fuente = None, ""
    if pmcid:
        url = pubmed.liga_pdf_pmc(cliente, pmcid)
        fuente = "PMC OA" if url else ""
    if not url and usar_unpaywall and doi:
        url, repo = pubmed.liga_pdf_unpaywall(cliente, doi, cliente.email)
        fuente = f"Unpaywall{' / ' + repo if repo else ''}" if url else ""

    if not url:
        db.registrar_descarga(con, pmid, "pdf", "no_disponible",
                              nota="sin PDF de acceso abierto",
                              url=(pubmed.url_articulo_pmc(pmcid)
                                   or pubmed.url_articulo_pubmed(pmid)))
        log(f"{prefijo} sin PDF abierto")
        return "no_disponible"

    datos = cliente.get(url)
    # Verificar la firma: muchos servidores responden HTML de error con 200
    if not datos or datos[:4] != b"%PDF":
        # Se guarda la liga que fallo, no una generica: sin ella no hay
        # forma de saber a que editor hay que ir ni que se intento.
        db.registrar_descarga(con, pmid, "pdf", "error", fuente=fuente,
                              nota="la liga no devolvio un PDF valido",
                              url=url)
        log(f"{prefijo} la liga no dio PDF")
        return "error"

    ruta = base / f"{pmid}.pdf"
    ruta.write_bytes(datos)
    db.registrar_descarga(con, pmid, "pdf", "ok", fuente=fuente,
                          ruta=str(ruta), tam=len(datos), url=url)
    log(f"{prefijo} PDF {len(datos) / 1024:.0f} KB ({fuente})")
    return "ok"
