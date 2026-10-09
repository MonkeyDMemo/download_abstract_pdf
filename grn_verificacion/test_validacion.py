"""Pruebas del lector de la base curada, sobre un .xlsx SINTÉTICO.

El .xlsx de estas pruebas se arma aquí mismo con `zipfile`: nombres de gen
inventados, locus y PMIDs de juguete. Nada de la base del laboratorio entra a
este archivo, ni como dato ni como forma: lo que se reproduce son las rarezas
que PLAN.md 2.4 describe en conteos (flotantes con `.0`, listas, un DOI, la
etiqueta de homología, un locus corrido en `Interaction`).
"""

import ast
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

from grn_verificacion import validacion as V

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_TIPO = _R + "/"


def _letra(columna):
    """0 -> A, 25 -> Z, 26 -> AA."""
    letras = ""
    columna += 1
    while columna:
        columna, resto = divmod(columna - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def construir_xlsx(ruta, hojas):
    """Escribe un .xlsx mínimo pero legítimo con `zipfile`.

    `hojas` es una lista de (nombre, filas). `filas` es una lista (fila 1, 2,
    ...) o un dict {número de fila: celdas}, para dejar huecos. Cada celda:

        None              no se escribe (hueco en la fila)
        "texto"           cadena compartida
        ("rico", [...])   cadena compartida en corridas, con guía fonética
        ("en_linea", t)   cadena en línea
        ("num", "1.5E7")  número con ese texto crudo
        True / False      booleano
        7, 7.5            número

    Las hojas se guardan en orden INVERSO de archivo (la primera del libro en
    el `sheetN.xml` de número más alto) y con destinos relativos y absolutos
    alternados: el lector tiene que resolverlas por `workbook.xml` y sus
    relaciones, no por el nombre del archivo.
    """
    compartidas, indices = [], {}

    def compartida(clave, fragmento):
        if clave not in indices:
            indices[clave] = len(compartidas)
            compartidas.append(fragmento)
        return indices[clave]

    def celda_xml(ref, celda):
        if isinstance(celda, bool):
            return '<c r="%s" t="b"><v>%d</v></c>' % (ref, int(celda))
        if isinstance(celda, (int, float)):
            return '<c r="%s"><v>%r</v></c>' % (ref, celda)
        if isinstance(celda, tuple) and celda[0] == "num":
            return '<c r="%s"><v>%s</v></c>' % (ref, escape(celda[1]))
        if isinstance(celda, tuple) and celda[0] == "en_linea":
            return ('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                    % (ref, escape(celda[1])))
        if isinstance(celda, tuple) and celda[0] == "rico":
            corridas = "".join(
                '<r><rPr><b/></rPr><t xml:space="preserve">%s</t></r>'
                % escape(p) for p in celda[1])
            i = compartida(("rico",) + tuple(celda[1]),
                           '<si>%s<rPh sb="0" eb="1"><t>ZZ</t></rPh></si>'
                           % corridas)
            return '<c r="%s" t="s"><v>%d</v></c>' % (ref, i)
        i = compartida(("t", celda),
                       '<si><t xml:space="preserve">%s</t></si>'
                       % escape(celda))
        return '<c r="%s" t="s"><v>%d</v></c>' % (ref, i)

    total = len(hojas)
    hojas_xml, rels, entradas = [], [], []
    for posicion, (nombre, filas) in enumerate(hojas):
        if isinstance(filas, dict):
            items = sorted(filas.items())
        else:
            items = list(enumerate(filas, 1))
        filas_xml = []
        for numero, celdas in items:
            partes = [celda_xml("%s%d" % (_letra(col), numero), celda)
                      for col, celda in enumerate(celdas) if celda is not None]
            filas_xml.append('<row r="%d">%s</row>' % (numero, "".join(partes)))
        archivo = "sheet%d.xml" % (total - posicion)
        destino = ("worksheets/" + archivo if posicion % 2 == 0
                   else "/xl/worksheets/" + archivo)
        rid = "rId%d" % (posicion + 1)
        entradas.append('<sheet name="%s" sheetId="%d" r:id="%s"/>'
                        % (escape(nombre), posicion + 1, rid))
        rels.append('<Relationship Id="%s" Type="%sworksheet" Target="%s"/>'
                    % (rid, _TIPO, destino))
        hojas_xml.append((
            "xl/worksheets/" + archivo,
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="%s" xmlns:r="%s"><sheetData>%s</sheetData>'
            '</worksheet>' % (_MAIN, _R, "".join(filas_xml))))
    rels.append('<Relationship Id="rId99" Type="%ssharedStrings" '
                'Target="sharedStrings.xml"/>' % _TIPO)

    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" '
            'ContentType="application/xml"/></Types>')
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s"><Relationship Id="rId1" '
            'Type="%sofficeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>' % (_PKG, _TIPO))
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
            % (_MAIN, _R, "".join(entradas)))
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="%s">%s</Relationships>'
            % (_PKG, "".join(rels)))
        z.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="%s" count="%d" uniqueCount="%d">%s</sst>'
            % (_MAIN, len(compartidas), len(compartidas),
               "".join(compartidas)))
        for nombre, contenido in hojas_xml:
            z.writestr(nombre, contenido)
    return ruta


ENCABEZADOS = ["Source", "Target", "Interaction", "Reference",
               "Source_Locus_id", "Target_Locus_id", "Origen",
               "Contributions"]

# Una base de juguete con una fila por rareza. Genes y locus inventados.
BASE = {
    1: ENCABEZADOS,
    2: ["qzxR", "wvuA", "+", ("num", "31415926"), "PA9001", "PA9002",
        u"Histórica", "x"],
    3: ["qzxR", "wvuB", "-", "27182818.0", "PA9001", "PA9003", u"Histórica"],
    4: ["qzxR", "wvuC", "Unknown", "16180339, 14142135", "PA9001", "PA9004",
        "Ambos"],
    # `Interaction` vacía, PMID en notación científica.
    5: ["qzxR", "wvuD", None, ("num", "1.7320508E7"), "PA9001", "PA9005",
        "BioBERT"],
    # PMID de 7 dígitos con la etiqueta pegada.
    6: ["qzxR", "wvuE", "d", "2236067PMID", "PA9001", "PA9006", u"Histórica"],
    # Solo un DOI: la fila se queda sin PMID. Origen en corridas de formato.
    7: ["qzxR", "wvuF", "+, +", "doi:10.1128/JB.00001-99", "PA9001", "PA9007",
        ("rico", ["Hist", u"órica"])],
    8: ["qzxR", "wvuG", "-", "homology PA14", "PA9001", "PA9008",
        u"Histórica"],
    # Signo en cadena en línea; un booleano en `Contributions`.
    9: ["qzxR", "wvuH", ("en_linea", "+"), "31415926 Homologous", "PA9001",
        "PA9009", u"Histórica", True],
    # Locus corrido a `Interaction`.
    10: ["qzxR", "wvuI", "PA9010", "31415926", "PA9001", "PA9010",
         u"Histórica"],
    11: ["qzxR", "wvuJ", "+", "31415926", "PA12", "PA9011", u"Histórica"],
    # La fila 12 no existe; la 13 viene vacía.
    13: [None, None, ""],
    14: ["qzxR", "wvuK", "-", "12345, 98765432", "pa9001", "PA9012",
         "Validada"],
}

PMIDS_DE_JUGUETE = ("31415926", "27182818", "16180339", "14142135",
                    "17320508", "2236067", "98765432")


class _ConCarpeta(unittest.TestCase):

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix="grn_val_")
        self.addCleanup(shutil.rmtree, self.carpeta, True)

    def ruta(self, nombre):
        return os.path.join(self.carpeta, nombre)


class PruebasLeerXlsx(_ConCarpeta):

    def test_tipos_de_celda_y_huecos(self):
        ruta = construir_xlsx(self.ruta("tipos.xlsx"), [("Datos", {
            1: ["Uno", "Dos", None, "Cuatro"],
            2: ["texto", ("num", "12345678"), True, ("en_linea", "linea")],
            4: [("rico", ["Hist", u"órica"]), ("num", "1.2345678E7"), False,
                "a_x000D_b"],
            5: [None, None, None, 7.5],
        })])
        encabezados, filas = V.leer_xlsx(ruta)
        self.assertEqual(["Uno", "Dos", "", "Cuatro"], encabezados)
        self.assertEqual([
            (2, ["texto", "12345678", "TRUE", "linea"]),
            (4, [u"Histórica", "1.2345678E7", "FALSE", "a\rb"]),
            (5, ["", "", "", "7.5"]),
        ], filas)

    def test_la_primera_hoja_es_la_del_libro_no_la_del_archivo(self):
        ruta = construir_xlsx(self.ruta("hojas.xlsx"), [
            ("Primera", [["A"], ["uno"]]),
            ("Segunda", [["B"], ["dos"]]),
        ])
        # Primera vive en sheet2.xml: un lector que tomara sheet1.xml
        # devolvería la segunda hoja.
        with zipfile.ZipFile(ruta) as z:
            self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
        self.assertEqual((["A"], [(2, ["uno"])]), V.leer_xlsx(ruta))
        self.assertEqual((["B"], [(2, ["dos"])]), V.leer_xlsx(ruta, "Segunda"))
        self.assertEqual((["B"], [(2, ["dos"])]), V.leer_xlsx(ruta, 1))
        with self.assertRaises(ValueError):
            V.leer_xlsx(ruta, "Tercera")
        with self.assertRaises(ValueError):
            V.leer_xlsx(ruta, 5)

    def test_el_encabezado_es_la_primera_fila_con_valores(self):
        ruta = construir_xlsx(self.ruta("abajo.xlsx"), [("Datos", {
            1: [None, ""],
            3: ["Uno", "Dos"],
            4: ["a", "b"],
        })])
        self.assertEqual((["Uno", "Dos"], [(4, ["a", "b"])]),
                         V.leer_xlsx(ruta))

    def test_un_archivo_que_no_es_xlsx_da_valueerror(self):
        ruta = self.ruta("falso.xlsx")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("no soy un zip")
        with self.assertRaises(ValueError):
            V.leer_xlsx(ruta)


class PruebasNormalizar(_ConCarpeta):

    def setUp(self):
        super(PruebasNormalizar, self).setUp()
        self.interacciones, self.conteos = V.leer_base(
            construir_xlsx(self.ruta("base.xlsx"), [("Hoja1", BASE)]))
        self.por_fila = dict((i["fila_origen"], i) for i in self.interacciones)

    def test_conteos(self):
        c = self.conteos
        self.assertEqual(11, c["filas"])
        self.assertEqual(1, c["filas_vacias"])
        self.assertEqual(1, c["locus_invalido"])
        self.assertEqual(10, c["interacciones"])
        self.assertEqual({"+": 4, "-": 3, "?": 2, "d": 1, "ilegible": 1},
                         c["signo"])
        self.assertEqual(1, c["signo_locus_corrido"])
        self.assertEqual({"historica": 8, "biobert": 1, "ambos": 1, "otro": 1},
                         c["origen"])
        self.assertEqual(2, c["homologia"])
        self.assertEqual(10, c["menciones_pmid"])
        self.assertEqual(7, c["pmids_distintos"])
        self.assertEqual(2, c["filas_sin_pmid"])
        self.assertEqual(1, c["dois_descartados"])
        self.assertEqual(1, c["numeros_descartados"])

    def test_interacciones(self):
        f = self.por_fila
        self.assertEqual(sorted([2, 3, 4, 5, 6, 7, 8, 9, 10, 14]), sorted(f))
        self.assertEqual({"fila_origen": 2, "regulador": "PA9001",
                          "blanco": "PA9002", "signo": "+",
                          "pmids": ["31415926"], "origen": "historica",
                          "homologia": False}, f[2])
        self.assertEqual(["27182818"], f[3]["pmids"])
        self.assertEqual(["16180339", "14142135"], f[4]["pmids"])
        self.assertEqual(("?", "ambos"), (f[4]["signo"], f[4]["origen"]))
        self.assertEqual(("?", "biobert", ["17320508"]),
                         (f[5]["signo"], f[5]["origen"], f[5]["pmids"]))
        self.assertEqual(("d", ["2236067"]), (f[6]["signo"], f[6]["pmids"]))
        self.assertEqual(("+", [], "historica"),
                         (f[7]["signo"], f[7]["pmids"], f[7]["origen"]))
        self.assertTrue(f[8]["homologia"])
        self.assertTrue(f[9]["homologia"])
        self.assertEqual(["31415926"], f[9]["pmids"])
        # El locus corrido deja la fila sin signo, pero el par sigue ahí
        # para vetar negativos.
        self.assertIsNone(f[10]["signo"])
        self.assertEqual("PA9001", f[14]["regulador"])
        self.assertEqual("otro", f[14]["origen"])
        self.assertEqual(["98765432"], f[14]["pmids"])

    def test_los_conteos_no_llevan_contenido(self):
        texto = json.dumps(self.conteos, ensure_ascii=False)
        for pmid in PMIDS_DE_JUGUETE:
            self.assertNotIn(pmid, texto)
        self.assertIsNone(re.search(r"PA[0-9]{2}", texto))
        self.assertNotIn("qzx", texto.lower())
        self.assertNotIn("wvu", texto.lower())

    def test_faltan_columnas(self):
        ruta = construir_xlsx(self.ruta("corta.xlsx"), [("Hoja1", [
            ["Source", "Target", "Interaction", "Reference",
             "Source_Locus_id", "Target_Locus_id"],
            ["a", "b", "+", "31415926", "PA9001", "PA9002"],
        ])])
        with self.assertRaises(ValueError) as ctx:
            V.leer_base(ruta)
        self.assertIn("Origen", str(ctx.exception))
        self.assertNotIn("31415926", str(ctx.exception))

    def test_encabezados_sin_distinguir_mayusculas_ni_espacios(self):
        encabezados = [" interaction", "REFERENCE ", "source_locus_id",
                       "Target_Locus_Id", "origen"]
        interacciones, _ = V.normalizar(
            encabezados, [(2, ["-", "31415926", "PA9001", "PA9002", "Ambos"])])
        self.assertEqual("-", interacciones[0]["signo"])


class PruebasPiezas(unittest.TestCase):

    def test_pmids_de(self):
        casos = [
            ("12345678", (["12345678"], 0, 0)),
            ("12345678.0", (["12345678"], 0, 0)),
            ("1.2345678E7", (["12345678"], 0, 0)),
            ("12345678, 23456789;34567890 45678901",
             (["12345678", "23456789", "34567890", "45678901"], 0, 0)),
            ("PMID:1234567", (["1234567"], 0, 0)),
            ("12345678homology", (["12345678"], 0, 0)),
            ("homology PA14", ([], 0, 0)),
            ("https://doi.org/10.1093/nar/gkx1234", ([], 1, 0)),
            ("12345678 doi:10.1128/JB.00001-99", (["12345678"], 1, 0)),
            ("123456, 1234567890", ([], 0, 2)),
            ("12345678, 12345678.0", (["12345678"], 0, 0)),
            ("12345678_x000D_", (["12345678"], 0, 0)),
            ("", ([], 0, 0)),
        ]
        for referencia, esperado in casos:
            self.assertEqual(esperado, V.pmids_de(V._desescapar(referencia)),
                             referencia)

    def test_signo_de(self):
        casos = [("+", "+"), (" + ", "+"), ("+, +", "+"), ("-", "-"),
                 (u"−", "-"), ("Unknown", "?"), ("unknown", "?"),
                 ("", "?"), ("d", "d"), ("D", "d")]
        for celda, esperado in casos:
            self.assertEqual((esperado, None), V.signo_de(celda), celda)
        self.assertEqual((None, "locus_corrido"), V.signo_de("PA0001"))
        self.assertEqual((None, "no_reconocido"), V.signo_de("+, -"))
        self.assertEqual((None, "no_reconocido"), V.signo_de("activa"))

    def test_origen_de(self):
        self.assertEqual("historica", V.origen_de(u" Histórica "))
        self.assertEqual("historica", V.origen_de("HISTORICA"))
        self.assertEqual("biobert", V.origen_de("BioBERT"))
        self.assertEqual("ambos", V.origen_de("Ambos"))
        self.assertEqual("otro", V.origen_de(""))
        self.assertEqual("otro", V.origen_de("Validada"))


class PruebasCompatibilidad(unittest.TestCase):

    def test_sintaxis_de_python_3_8(self):
        """El servidor corre Python 3.10 y el proyecto promete 3.8."""
        ruta = V.__file__
        if ruta.endswith(".pyc"):
            ruta = ruta[:-1]
        with open(ruta, encoding="utf-8") as f:
            ast.parse(f.read(), filename=ruta, feature_version=(3, 8))


class PruebasMensajesSinRuta(unittest.TestCase):

    def test_un_archivo_que_no_es_xlsx_no_dice_donde_esta(self):
        carpeta = tempfile.mkdtemp(prefix="grn_val_")
        self.addCleanup(shutil.rmtree, carpeta, True)
        ruta = os.path.join(carpeta, "secreto_base.xlsx")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("no es un zip")
        with self.assertRaises(ValueError) as ctx:
            V.leer_xlsx(ruta)
        self.assertNotIn("secreto", str(ctx.exception))
        self.assertIn("--base", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
