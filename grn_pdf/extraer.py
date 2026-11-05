# -*- coding: utf-8 -*-
"""Del PDF a páginas de líneas con su tipografía. La única pieza con PyMuPDF.

Devuelve estructuras de Python simples (listas y diccionarios), no objetos de
PyMuPDF. Así todo lo que decide --orden de lectura, encabezados, pies de
figura, tablas-- vive en `maquetar.py`, que es biblioteca estándar y se prueba
con páginas sintéticas sin tener PyMuPDF instalado.

    página = {"numero", "ancho", "alto", "bloques": [bloque]}
    bloque = {"bbox": (x0, y0, x1, y1), "lineas": [línea]}
    línea  = {"bbox": (...), "spans": [span]}
    span   = {"texto", "tam", "negrita", "cursiva", "fuente", "x0", "x1",
              "base", "sup"}

PyMuPDF se importa dentro de las funciones: el paquete se importa (y sus
pruebas de lógica corren) en un entorno sin él.
"""

import re

# Lo que delata una negrita en el nombre de la fuente. El bit de negrita de
# MuPDF solo se enciende si la fuente lo declara, y muchas revistas usan una
# «Times-Bold» que no lo declara.
_NEGRITA = re.compile(r"bold|black|heavy|semibold|demi|,b\b|-b\b|\.b\b",
                      re.IGNORECASE)


class ErrorPDF(Exception):
    """El archivo no se pudo leer como PDF (cifrado, cortado, no es PDF)."""


def version_pymupdf():
    """La versión de PyMuPDF instalada, o None si no está."""
    try:
        import pymupdf
    except ImportError:
        return None
    return getattr(pymupdf, "VersionBind", None) or getattr(
        pymupdf, "__version__", "desconocida")


def hay_pymupdf():
    return version_pymupdf() is not None


def leer_paginas(ruta):
    """(páginas, número de páginas) del PDF en `ruta`. Lanza `ErrorPDF`.

    Sin `TEXT_PRESERVE_LIGATURES`: MuPDF expande las ligaduras que conoce
    (`ﬁ` -> `fi`). Las que se le escapan, con código privado o de
    compatibilidad, las normaliza `maquetar.normalizar` igual.
    """
    import pymupdf
    try:
        doc = pymupdf.open(ruta)
    except Exception as e:                          # noqa: BLE001
        raise ErrorPDF("no se pudo abrir: %s" % e)
    try:
        if doc.needs_pass:
            raise ErrorPDF("el PDF está cifrado")
        # El código del glifo cuando la fuente no da Unicode, y no U+FFFD:
        # las fuentes de símbolos de la ASM dan así `D` por Δ y `s` por σ,
        # que `maquetar` traduce; con U+FFFD ya no habría qué traducir.
        banderas = (pymupdf.TEXT_PRESERVE_WHITESPACE
                    | pymupdf.TEXT_MEDIABOX_CLIP
                    | pymupdf.TEXT_CID_FOR_UNKNOWN_UNICODE)
        paginas = []
        for i, pagina in enumerate(doc):
            try:
                d = pagina.get_text("dict", flags=banderas)
            except Exception as e:                  # noqa: BLE001
                raise ErrorPDF("página %d ilegible: %s" % (i + 1, e))
            paginas.append(_pagina(d, i, pagina.rect))
        return paginas, doc.page_count
    finally:
        doc.close()


def _pagina(d, numero, rect):
    bloques = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        lineas = []
        for l in b.get("lines", []):
            dx, dy = l.get("dir", (1.0, 0.0))
            # Texto girado: la marca «Downloaded from ... by guest» de las
            # revistas de la ASM, el «Author Manuscript» de los manuscritos
            # de PMC. Nunca es cuerpo del artículo.
            if dx < 0.95 or abs(dy) > 0.05:
                continue
            spans = []
            for s in l.get("spans", []):
                t = s.get("text") or ""
                if not t:
                    continue
                fuente = s.get("font") or ""
                banderas = s.get("flags", 0)
                spans.append({
                    "texto": t, "tam": float(s.get("size", 0.0)),
                    "negrita": bool(banderas & 16) or bool(_NEGRITA.search(fuente)),
                    "cursiva": bool(banderas & 2),
                    "sup": bool(banderas & 1),
                    "fuente": fuente,
                    "x0": float(s["bbox"][0]), "x1": float(s["bbox"][2]),
                    "base": float(s.get("origin", (0, s["bbox"][3]))[1]),
                })
            if spans:
                lineas.append({"bbox": tuple(float(x) for x in l["bbox"]),
                               "spans": spans})
        if lineas:
            bloques.append({"bbox": tuple(float(x) for x in b["bbox"]),
                            "lineas": lineas})
    return {"numero": numero, "ancho": float(rect.width),
            "alto": float(rect.height), "x0": float(rect.x0),
            "y0": float(rect.y0), "bloques": bloques}
