# -*- coding: utf-8 -*-
"""Exportacion por consulta: CSV, JSONL y el paquete zip para terceros.

Dos frentes, el CLI y el tablero, entregan lo mismo, asi que la logica vive
aqui y no en ninguno de los dos. Antes el CSV se armaba dentro de cli.py y
el tablero no tenia como entregar nada.

El paquete (`empaquetar`) es un zip con el CSV, el JSONL, el texto completo
descargado para esa consulta y un LEEME que dice que hay, de donde salio y
con que licencia. Las rutas del texto completo se arman desde el pmid y el
pmcid validados y la convencion de nombres, nunca desde `descargas.ruta`:
es la misma regla que sigue el tablero al servir un PDF. Lo que esta
registrado como descargado pero no esta en disco se cuenta y se anota; no
tumba el paquete.

Solo biblioteca estandar y grn_comun.archivos. Python 3.8.
"""

import csv
import datetime
import io
import json
import os
import re
import zipfile

from grn_comun import archivos

from . import db

# Carpeta, dentro de la raiz de datos, donde caen los paquetes. La raiz la
# resuelven cli.py y servidor.py con la precedencia de GRN_DATOS; este
# modulo solo recibe rutas, para que grn_etl no dependa de grn_bronce.rutas.
CARPETA = "exportaciones"

CAMPOS = ["pmid", "doi", "pmcid", "titulo", "abstract", "revista", "anio",
          "autores", "mesh_terms", "keywords", "tipos_publicacion"]

# Encabezado que lee una persona, columna por columna. Va aparte de CAMPOS
# porque CAMPOS son las columnas de la base y las llaves del JSONL: en ASCII,
# que es el contrato con el resto del pipeline. Lo que se abre en Excel si
# lleva el acento.
ENCABEZADOS = {
    "pmid": "pmid", "doi": "doi", "pmcid": "pmcid", "titulo": "título",
    "abstract": "abstract", "revista": "revista", "anio": "año",
    "autores": "autores", "mesh_terms": "mesh_terms", "keywords": "keywords",
    "tipos_publicacion": "tipos_publicación",
}

# Lo que se puede listar y servir desde la carpeta de exportaciones. Un
# `.tmp` a medio escribir no empata, asi que no se lista ni se sirve.
ARCHIVO_VALIDO = re.compile(r"^[A-Za-z0-9_.-]{1,160}\.(zip|csv|jsonl)$")
TIPOS = {
    "zip": "application/zip",
    "csv": "text/csv; charset=utf-8",
    "jsonl": "application/x-ndjson; charset=utf-8",
}

# Los mismos patrones que usa el tablero para armar la ruta de un documento.
PMID_VALIDO = re.compile(r"^\d{1,12}$")
PMCID_VALIDO = re.compile(r"^PMC\d{1,12}$")

# NBK25497 pide que todo software que use E-utilities muestre esta liga.
DISCLAIMER_NCBI = "https://www.ncbi.nlm.nih.gov/About/disclaimer.html"


def _nada(*_a, **_k):
    pass


def _dentro_de(raiz, ruta):
    raiz = os.path.realpath(raiz)
    ruta = os.path.realpath(ruta)
    return ruta == raiz or ruta.startswith(raiz + os.sep)


# ------------------------------------------------------------- csv y jsonl

def documentos(con, nombre, solo_con_abstract=False):
    """Los documentos de la consulta, uno a uno y ya deserializados.

    Es un generador sobre el cursor: con 83 000 abstracts, un fetchall
    subiria cientos de MB a memoria para escribirlos a disco.
    """
    for fila in db.iterar_documentos_de_consulta(con, nombre, solo_con_abstract):
        yield db.a_dict(fila)


def fila_csv(doc):
    """Las listas van unidas con ' | '; lo demas tal cual."""
    return {k: (" | ".join(v) if isinstance(v, list) else v)
            for k, v in doc.items()}


def _volcar_csv(f, docs):
    w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
    # No se usa writeheader(): escribiria las llaves, que van sin acento.
    csv.writer(f).writerow([ENCABEZADOS[c] for c in CAMPOS])
    n = 0
    for d in docs:
        w.writerow(fila_csv(d))
        n += 1
    return n


def _volcar_jsonl(f, docs):
    n = 0
    for d in docs:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
        n += 1
    return n


def escribir_csv(docs, ruta, bom=False):
    """CSV atomico (.tmp y reemplazo). Con bom=True, Excel lo abre con
    doble clic sin confundir los acentos con cp1252. Devuelve las filas."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8",
                 newline="") as f:
        n = _volcar_csv(f, docs)
    archivos.reemplazar(tmp, ruta)
    return n


def escribir_jsonl(docs, ruta):
    """JSONL atomico, una linea por documento, con las listas como listas."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        n = _volcar_jsonl(f, docs)
    archivos.reemplazar(tmp, ruta)
    return n


# ---------------------------------------------------------------- paquete

def nombre_paquete(nombre, cuando=None):
    """`<nombre_limpio>_<YYYYMMDD-HHMMSS>Z.zip`, en UTC como todo el proyecto.

    El nombre de la consulta puede traer espacios, puntos o diagonales; se
    reduce a lo que ARCHIVO_VALIDO acepta para que el paquete se pueda
    listar y servir.
    """
    limpio = re.sub(r"[^A-Za-z0-9_.-]+", "_", nombre).strip("._-") or "consulta"
    cuando = cuando or datetime.datetime.now(datetime.timezone.utc)
    return f"{limpio[:80]}_{cuando.strftime('%Y%m%d-%H%M%S')}Z.zip"


def _ruta_fulltext(raiz, tipo, pmid, pmcid):
    """La ruta en disco de una descarga, o None si no se puede armar.

    Desde el pmid y el pmcid validados, nunca desde descargas.ruta: una
    cadena guardada en la base no es de fiar como ruta.
    """
    if not PMID_VALIDO.match(pmid or ""):
        return None
    if tipo == "pdf":
        ruta = os.path.join(raiz, "pdf", f"{pmid}.pdf")
    elif tipo == "xml":
        if not PMCID_VALIDO.match(pmcid or ""):
            return None
        ruta = os.path.join(raiz, "xml", f"{pmid}_{pmcid}.xml")
    else:
        return None
    return ruta if _dentro_de(raiz, ruta) else None


def _leeme(consulta, resumen, incluir_pdf, cuando):
    lineas = [
        f"Exportación de la consulta «{consulta['nombre']}»",
        f"Generado el {cuando.strftime('%Y-%m-%d %H:%M')} UTC por grn-etl "
        f"(paso 0 del pipeline GRN).",
        "",
        "Consulta de PubMed:",
        consulta["texto"],
    ]
    if consulta["descripcion"]:
        lineas += ["", f"Descripción: {consulta['descripcion']}"]
    lineas += [
        "",
        "Contenido",
        f"- documentos.csv    {resumen['documentos']} artículos, una fila por artículo. "
        f"UTF-8 con BOM: Excel lo abre con doble clic. Las listas (autores, "
        f"mesh_terms, keywords, tipos_publicación) van separadas por ' | '.",
        f"- documentos.jsonl  los mismos artículos con las listas como listas JSON, "
        f"una línea por artículo.",
        f"- xml/              {resumen['xml']} artículos con texto completo de PubMed "
        f"Central (JATS), nombrados <pmid>_<pmcid>.xml.",
        f"- texto/            {resumen['texto']} versiones en texto plano extraídas "
        f"del XML, <pmid>_<pmcid>.txt.",
    ]
    if incluir_pdf:
        lineas.append(f"- pdf/              {resumen['pdf']} PDF de acceso abierto, "
                      f"<pmid>.pdf.")
    lineas += [
        "",
        "Columnas: " + ", ".join(ENCABEZADOS[c] for c in CAMPOS),
        "",
        f"Cobertura: {resumen['documentos']} artículos, {resumen['con_abstract']} "
        f"con abstract, {resumen['xml']} con texto completo"
        + (f", {resumen['pdf']} con PDF." if incluir_pdf else "."),
    ]
    if resumen["faltantes"]:
        lineas += [
            "",
            f"Registrados como descargados pero ausentes del disco al exportar "
            f"({len(resumen['faltantes'])}): " + ", ".join(resumen["faltantes"]),
        ]
    lineas += [
        "",
        "Procedencia y licencias",
        "Los metadatos y los abstracts vienen de PubMed (NCBI) por E-utilities. "
        f"NCBI pide mostrar su aviso: {DISCLAIMER_NCBI}",
        "El texto completo viene de PubMed Central y de fuentes de acceso abierto "
        "(Europe PMC, Unpaywall). Cada artículo conserva la licencia de su editor; "
        "antes de redistribuir este paquete fuera del grupo, revísala.",
        "",
    ]
    return "\n".join(lineas)


def empaquetar(con, nombre, carpeta_fulltext, ruta_zip, incluir_pdf=False,
               log=_nada):
    """Arma el zip de una consulta. Devuelve el resumen de lo que lleva.

    Se escribe a `ruta_zip + ".tmp"` y se pone en su lugar al final: un corte
    a media escritura no deja un zip cortado que parezca bueno. El CSV y el
    JSONL se escriben directo al zip, en flujo, con dos pasadas sobre el
    cursor (el zip solo admite un miembro abierto a la vez); los archivos de
    texto completo entran uno por uno con `write`, sin cargarlos en memoria.
    """
    consulta = db.obtener_consulta(con, nombre)
    if not consulta:
        raise ValueError(f"No existe la consulta '{nombre}'")

    cuando = datetime.datetime.now(datetime.timezone.utc)
    resumen = {"archivo": os.path.basename(ruta_zip), "ruta": ruta_zip,
               "documentos": 0, "con_abstract": 0, "xml": 0, "texto": 0,
               "pdf": 0, "faltantes": [], "bytes": 0}
    os.makedirs(os.path.dirname(ruta_zip) or ".", exist_ok=True)
    tmp = ruta_zip + ".tmp"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            with z.open("documentos.csv", "w") as h, \
                    io.TextIOWrapper(h, encoding="utf-8-sig", newline="") as f:
                resumen["documentos"] = _volcar_csv(f, documentos(con, nombre))
            log(f"  documentos.csv: {resumen['documentos']} filas")

            with z.open("documentos.jsonl", "w") as h, \
                    io.TextIOWrapper(h, encoding="utf-8", newline="\n") as f:
                for d in documentos(con, nombre):
                    if d.get("abstract"):
                        resumen["con_abstract"] += 1
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
            log(f"  documentos.jsonl: {resumen['documentos']} lineas")

            for fila in db.descargas_de_consulta(con, nombre):
                tipo = fila["tipo"]
                if tipo == "pdf" and not incluir_pdf:
                    continue
                ruta = _ruta_fulltext(carpeta_fulltext, tipo, fila["pmid"],
                                      fila["pmcid"])
                if ruta is None or not os.path.isfile(ruta):
                    resumen["faltantes"].append(f"{tipo} {fila['pmid']}")
                    continue
                z.write(ruta, f"{tipo}/{os.path.basename(ruta)}")
                resumen[tipo] += 1
                if tipo == "xml":
                    texto = ruta[:-4] + ".txt"
                    if os.path.isfile(texto):
                        z.write(texto, f"texto/{os.path.basename(texto)}")
                        resumen["texto"] += 1
            log(f"  texto completo: {resumen['xml']} xml, {resumen['texto']} txt, "
                f"{resumen['pdf']} pdf; ausentes: {len(resumen['faltantes'])}")

            z.writestr("LEEME.txt", _leeme(consulta, resumen, incluir_pdf, cuando))
        archivos.reemplazar(tmp, ruta_zip)
    finally:
        archivos.borrar(tmp)

    resumen["bytes"] = os.path.getsize(ruta_zip)
    log(f"Paquete: {ruta_zip} ({resumen['bytes']} bytes)")
    return resumen


# ------------------------------------------------------------- la carpeta

def listar_exportaciones(carpeta):
    """[{nombre, bytes, modificado}] de lo que se puede servir, lo mas
    reciente primero. Una carpeta inexistente es una lista vacia."""
    if not os.path.isdir(carpeta):
        return []
    salida = []
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        if not ARCHIVO_VALIDO.match(nombre) or not os.path.isfile(ruta):
            continue
        st = os.stat(ruta)
        salida.append({
            "nombre": nombre, "bytes": st.st_size,
            "modificado": datetime.datetime.fromtimestamp(
                st.st_mtime, datetime.timezone.utc).isoformat(timespec="seconds"),
        })
    salida.sort(key=lambda a: (a["modificado"], a["nombre"]), reverse=True)
    return salida


def ruta_exportacion(carpeta, nombre):
    """La ruta de un paquete listado, o None.

    Tres cerrojos, como en las salidas del flujo: el nombre cumple el
    patron, esta en el listado (hijo directo, archivo de verdad) y la ruta
    resuelta queda dentro de la carpeta.
    """
    if not ARCHIVO_VALIDO.match(nombre or ""):
        return None
    if nombre not in {a["nombre"] for a in listar_exportaciones(carpeta)}:
        return None
    ruta = os.path.join(carpeta, nombre)
    return ruta if _dentro_de(carpeta, ruta) else None


def tipo_mime(nombre):
    return TIPOS[nombre.rsplit(".", 1)[-1]]
