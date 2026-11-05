# -*- coding: utf-8 -*-
"""Convertir una carpeta de PDF a `.txt`, sin rehacer lo que ya está al día.

Idempotente por huella: el registro (`registro.json`, en la carpeta de salida)
guarda de cada PMID la huella del PDF que se convirtió, la versión del
maquetado y de PyMuPDF, y la huella del `.txt` que salió. Un PDF se vuelve a
convertir solo si cambió el PDF, cambió alguna de las dos versiones, o el
`.txt` falta o no es el que se escribió. Correr dos veces seguidas no
convierte nada la segunda.

Reanudable: el registro se reescribe después de cada documento, no al final,
y siempre con escritura atómica. Una corrida cortada conserva lo convertido.

Un PDF que no se puede leer (cortado a media descarga, cifrado) queda en el
registro con `estatus` `error` y se reintenta en la siguiente corrida: es «no
pude leerlo», no «no tiene texto».

Biblioteca estándar; PyMuPDF solo entra por `extraer.leer_paginas`.
"""

import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from grn_comun.archivos import reemplazar     # noqa: E402
from grn_pdf import extraer, maquetar          # noqa: E402

NOMBRE_REGISTRO = "registro.json"

# Solo `<pmid>.pdf`: es la convención de `grn_etl/etl.py`, y el PMID es lo que
# une el texto con su documento en la base.
_NOMBRE_PDF = re.compile(r"^(\d{1,12})\.pdf$", re.IGNORECASE)


def _nada(_m):
    pass


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def huella_bytes(ruta):
    """sha256 del archivo, completo. Es la identidad del PDF convertido."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def huella_texto(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def pdfs_de(carpeta):
    """{pmid: ruta} de los `<pmid>.pdf` de la carpeta, ordenado por PMID."""
    salida = {}
    if not os.path.isdir(carpeta):
        return salida
    for nombre in sorted(os.listdir(carpeta)):
        m = _NOMBRE_PDF.match(nombre)
        if m:
            salida[m.group(1)] = os.path.join(carpeta, nombre)
    return salida


def leer_registro(carpeta_salida):
    ruta = os.path.join(carpeta_salida, NOMBRE_REGISTRO)
    if not os.path.isfile(ruta):
        return {"documentos": {}}
    with io.open(ruta, encoding="utf-8") as f:
        try:
            reg = json.load(f)
        except ValueError:
            # Un registro ilegible no se toma por vacío en silencio: se
            # aparta y se reconvierte todo, que es lo seguro.
            reg = None
    if not isinstance(reg, dict) or not isinstance(reg.get("documentos"),
                                                   dict):
        os.replace(ruta, ruta + ".ilegible")
        return {"documentos": {}}
    return reg


def escribir_registro(carpeta_salida, registro):
    ruta = os.path.join(carpeta_salida, NOMBRE_REGISTRO)
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(registro, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    reemplazar(tmp, ruta)


def escribir_texto(ruta, texto):
    """UTF-8 y saltos `\\n` en todas las plataformas: la huella del `.txt`
    sale igual en Windows y en Linux. El bronce lo lee igual que los del
    XML, que se escribieron con CRLF en Windows."""
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    reemplazar(tmp, ruta)


def al_dia(entrada, ruta_pdf, ruta_txt, version_pymupdf, huella=None):
    """El `.txt` de este PDF ya está hecho con lo de hoy."""
    if not entrada or entrada.get("estatus") != "ok":
        return False
    if entrada.get("version_maquetado") != maquetar.VERSION:
        return False
    if entrada.get("pymupdf") != version_pymupdf:
        return False
    if not os.path.isfile(ruta_txt):
        return False
    with io.open(ruta_txt, encoding="utf-8", newline="") as f:
        if huella_texto(f.read()) != entrada.get("huella_txt"):
            return False
    if huella is None:
        huella = huella_bytes(ruta_pdf)
    return entrada.get("huella_pdf") == huella


def convertir_uno(ruta_pdf):
    """(texto, ficha) de un PDF. Lanza `extraer.ErrorPDF` si no se lee."""
    paginas, n_paginas = extraer.leer_paginas(ruta_pdf)
    resultado = maquetar.maquetar(paginas)
    texto = maquetar.a_texto(resultado)
    ficha = {
        "paginas": n_paginas,
        "caracteres": len(texto),
        "secciones": maquetar.secciones_halladas(resultado),
        "pies": len(resultado["pies"]),
        "descartes": dict(sorted(resultado["cuenta"].items())),
    }
    return texto, ficha


def convertir_carpeta(entrada, salida, forzar=False, pmids=None, limite=None,
                      log=_nada):
    """Convierte lo que falte de `entrada` a `salida/<pmid>.txt`.

    Devuelve los contadores: `convertidos`, `al_dia`, `errores`,
    `sin_texto` (PDF que abre pero no da ni un carácter: escaneado).
    """
    version_pymupdf = extraer.version_pymupdf()
    if version_pymupdf is None:
        raise RuntimeError("PyMuPDF no está instalado en este intérprete.")
    os.makedirs(salida, exist_ok=True)
    registro = leer_registro(salida)
    docs = registro.setdefault("documentos", {})
    pdfs = pdfs_de(entrada)
    if pmids:
        pdfs = dict((p, r) for p, r in pdfs.items() if p in set(pmids))
    cuenta = {"pdf": len(pdfs), "convertidos": 0, "al_dia": 0, "errores": 0,
              "sin_texto": 0}
    hechos = 0
    for i, (pmid, ruta_pdf) in enumerate(sorted(pdfs.items()), 1):
        ruta_txt = os.path.join(salida, pmid + ".txt")
        entrada_reg = docs.get(pmid)
        huella = huella_bytes(ruta_pdf)
        if not forzar and al_dia(entrada_reg, ruta_pdf, ruta_txt,
                                 version_pymupdf, huella):
            cuenta["al_dia"] += 1
            continue
        if limite is not None and hechos >= limite:
            break
        hechos += 1
        ficha = {"huella_pdf": huella, "bytes_pdf": os.path.getsize(ruta_pdf),
                 "version_maquetado": maquetar.VERSION,
                 "pymupdf": version_pymupdf, "convertido_en": ahora()}
        try:
            texto, datos = convertir_uno(ruta_pdf)
        except extraer.ErrorPDF as e:
            ficha.update(estatus="error", error=str(e)[:300])
            cuenta["errores"] += 1
            log("  [%d/%d] %s error: %s" % (i, len(pdfs), pmid, e))
        else:
            ficha.update(datos)
            if datos["caracteres"] == 0 or not datos["secciones"]:
                cuenta["sin_texto"] += 1
            escribir_texto(ruta_txt, texto)
            ficha.update(estatus="ok", huella_txt=huella_texto(texto))
            cuenta["convertidos"] += 1
            log("  [%d/%d] %s %d págs, %d caracteres, %s"
                % (i, len(pdfs), pmid, datos["paginas"], datos["caracteres"],
                   ", ".join(datos["secciones"]) or "sin secciones"))
        docs[pmid] = ficha
        registro.update(version_maquetado=maquetar.VERSION,
                        pymupdf=version_pymupdf, actualizado_en=ahora())
        escribir_registro(salida, registro)
    return cuenta
