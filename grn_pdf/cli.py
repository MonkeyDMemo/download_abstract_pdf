# -*- coding: utf-8 -*-
"""grn-pdf: la línea de comandos de la conversión de PDF a texto.

    .venv-pdf/Scripts/python -m grn_pdf.cli convertir [--entrada D] [--salida D]
                                                      [--forzar] [--pmid P ...]
    python -m grn_pdf.cli validar [--xml D] [--pdf-txt D] [--json R]

`convertir` necesita PyMuPDF y corre con el intérprete de `.venv-pdf`;
`validar` es biblioteca estándar y corre con cualquiera. Las carpetas salen de
la raíz de datos con la precedencia de siempre (`--datos`, `GRN_DATOS`,
`./datos`), y un flag explícito gana sobre ella.

Parsea, llama y formatea: la lógica vive en `convertir.py` y `validar.py`. Es
el único módulo del paquete que imprime.
"""

import argparse
import io
import json
import os
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from grn_comun import rutas                       # noqa: E402

AYUDA_ENTORNO = (
    "PyMuPDF no está en este intérprete. La conversión corre en .venv-pdf:\n"
    "  uv venv .venv-pdf --python 3.12\n"
    "  uv pip install --python .venv-pdf/Scripts/python.exe "
    "-r grn_pdf/requisitos.txt\n"
    "  .venv-pdf/Scripts/python -m grn_pdf.cli convertir")


def log(msg):
    print(msg, flush=True)


def _carpeta(flag, datos, *partes):
    return flag or os.path.join(rutas.raiz_datos(datos), *partes)


def cmd_convertir(args):
    from grn_pdf import convertir, extraer, maquetar
    if not extraer.hay_pymupdf():
        sys.exit(AYUDA_ENTORNO)
    entrada = _carpeta(args.entrada, args.datos, "fulltext", "pdf")
    salida = _carpeta(args.salida, args.datos, "fulltext", "pdf_txt")
    log("PDF en %s" % entrada)
    log("Texto a %s" % salida)
    log("Maquetado v%s, PyMuPDF %s" % (maquetar.VERSION,
                                       extraer.version_pymupdf()))
    t0 = time.time()
    cuenta = convertir.convertir_carpeta(entrada, salida, args.forzar,
                                         args.pmid, args.limite, log)
    log("")
    log("  PDF en la carpeta : %d" % cuenta["pdf"])
    log("  ya al día         : %d" % cuenta["al_dia"])
    log("  convertidos       : %d" % cuenta["convertidos"])
    log("  sin texto         : %d" % cuenta["sin_texto"])
    log("  con error         : %d" % cuenta["errores"])
    log("  registro          : %s" % os.path.join(
        salida, convertir.NOMBRE_REGISTRO))
    log("  duración          : %.0f s" % (time.time() - t0))
    return 1 if cuenta["errores"] else 0


def cmd_validar(args):
    from grn_pdf import validar
    xml = _carpeta(args.xml, args.datos, "fulltext", "xml")
    pdf_txt = _carpeta(args.pdf_txt, args.datos, "fulltext", "pdf_txt")
    log("XML en %s" % xml)
    log("Texto de PDF en %s" % pdf_txt)
    log("Cargando el diccionario...")
    t0 = time.time()
    informe = validar.validar(xml, pdf_txt, args.pmid, log=log)
    informe["carpetas"] = {"xml": xml, "pdf_txt": pdf_txt}
    os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
    tmp = args.json + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, args.json)

    log("")
    log("Artículos con XML y PDF: %d" % informe["articulos"])
    for clave, nombre in (
            ("frac_candidatas_recuperadas", "candidatas del XML recuperadas"),
            ("frac_candidatas_ruido", "candidatas del PDF que no están en el XML"),
            ("frac_recuperadas", "examinables del XML recuperadas"),
            ("frac_ruido", "examinables del PDF que no están en el XML")):
        r = informe["por_articulo"][clave]
        log("  %-44s mediana %s  (q1 %s, q3 %s; n %d)"
            % (nombre, _pct(r["mediana"]), _pct(r["q1"]), _pct(r["q3"]),
               r["n"]))
    t = informe["totales"]
    log("  en total: %s de %d candidatas recuperadas; %s de %d del PDF son "
        "ruido" % (_pct(t["frac_candidatas_recuperadas"], 1),
                   t["candidatas_xml"], _pct(t["frac_candidatas_ruido"], 1),
                   t["candidatas_pdf"]))
    log("  peores por candidatas recuperadas: %s" % ", ".join(
        "%s (%s)" % (f["pmid"], _pct(f["frac_candidatas_recuperadas"]))
        for f in informe["peores_por_candidatas_recuperadas"][:6]))
    log("Informe en %s (%.0f s)" % (args.json, time.time() - t0))
    return 0


def _pct(x, dec=0):
    return "n/d" if x is None else ("%." + str(dec) + "f %%") % (100.0 * x)


def main():
    for flujo_salida in (sys.stdout, sys.stderr):
        if hasattr(flujo_salida, "reconfigure"):
            flujo_salida.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        prog="grn-pdf",
        description="Texto de los PDF de acceso abierto, en el formato de "
                    "los .txt del XML de PMC.")
    sub = ap.add_subparsers(dest="sub", required=True)

    co = sub.add_parser("convertir", help="PDF -> <pmid>.txt (con .venv-pdf).")
    co.add_argument("--datos", help="Raíz de datos; gana sobre GRN_DATOS.")
    co.add_argument("--entrada", help="Carpeta de los PDF (por omisión, "
                                      "<datos>/fulltext/pdf).")
    co.add_argument("--salida", help="Carpeta de los .txt (por omisión, "
                                     "<datos>/fulltext/pdf_txt).")
    co.add_argument("--forzar", action="store_true",
                    help="Reconvertir aunque el .txt esté al día.")
    co.add_argument("--pmid", action="append", default=None,
                    help="Solo ese PMID (se puede repetir).")
    co.add_argument("--limite", type=int, default=None,
                    help="Convertir a lo más N pendientes.")
    co.set_defaults(func=cmd_convertir)

    va = sub.add_parser("validar",
                        help="Comparar con el XML los que tienen los dos.")
    va.add_argument("--datos", help="Raíz de datos; gana sobre GRN_DATOS.")
    va.add_argument("--xml", help="Carpeta de los .txt del XML (por omisión, "
                                  "<datos>/fulltext/xml).")
    va.add_argument("--pdf-txt", dest="pdf_txt",
                    help="Carpeta de los .txt del PDF (por omisión, "
                         "<datos>/fulltext/pdf_txt).")
    va.add_argument("--json", default=os.path.join("salidas",
                                                   "pdf_validacion.json"),
                    help="Informe (por omisión, salidas/pdf_validacion.json).")
    va.add_argument("--pmid", action="append", default=None,
                    help="Solo ese PMID (se puede repetir).")
    va.set_defaults(func=cmd_validar)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
