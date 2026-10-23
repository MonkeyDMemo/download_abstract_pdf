"""Pruebas de la medición de tablas y texto, sobre datos SINTÉTICOS.

Como en `test_contraste.py`: la base se arma con `construir_xlsx`, los locus
son de un rango que PAO1 no tiene (PA9001 y siguientes), los PMIDs están por
encima de los que existen, y el diccionario es uno de juguete con los
encabezados del del bronce. Nada viene de la base del laboratorio.

El artículo 1 trae un XML con tres tablas: la 1 nombra al regulador en el
título; la 2 va metida en un párrafo, que es donde se colaría en el texto, y
separa dos genes con un `<break/>`; la 3 lleva una tabla anidada y un pie. El
artículo 2 no tiene XML y el del 3 no se puede leer. Una fila por caso:

    fila  par              cita        categoría
     2    9001 -> 9001     1           autorregulación
     3    9001 -> 9002     1           regla b (y además en la tabla 1)
     4    9001 -> 9003     1           misma fila
     5    9001 -> 9004     1           misma tabla: el título nombra al TF
     6    9018 -> 9015     1           misma tabla: el pie y la tabla anidada
     7    9010 -> 9005     1           tabla y texto, el blanco solo en tabla
     8    9010 -> 9006     1           tabla y texto, los dos en el texto
     9    9010 -> 9007     1           solo texto, en oraciones distintas
    10    9010 -> 9008     1           solo texto, en una oración de métodos
    11    9011 -> 9012     1           ninguno: no aparece ninguno
    12    9010 -> 9013     1           ninguno: aparece uno solo
    13    9014 -> 9015     1           ninguno: en tablas distintas
    14    9010 -> 9016     2 y 1       solo texto por el 1; en el 2, sin XML
    15    9001 -> 9020     2           sin XML
    16    9001 -> 9021     2           sin XML
    17    9001 -> 9022     3           sin XML: el suyo no se puede leer
    18    9001 -> 9023     1 homology  fuera del denominador
 19-22    9030 -> 9031...  B           fuera por el archivo de exclusiones
"""

import collections
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from grn_bronce import operones
from grn_comun import procedencia
from grn_verificacion import cli
from grn_verificacion import contraste as C
from grn_verificacion import entrenamiento as E
from grn_verificacion import reentrenar as R
from grn_verificacion import tablas as T
from grn_verificacion import validacion as V
from grn_verificacion.test_contraste import (escribir_candidatas,
                                             escribir_lista,
                                             escribir_menciones)
from grn_verificacion.test_validacion import ENCABEZADOS, construir_xlsx

# `tablas` importa el puente, que deja `etapa2/` en sys.path: de ahí sale el
# diccionario, como en el bronce.
import lexico  # noqa: E402

P1, P2, P3, P_B, P_OTRO = ("91000001", "91000002", "91000003", "91000004",
                           "91000005")
PMIDS = (P1, P2, P3, P_B, P_OTRO)
HIST = u"Histórica (versión anterior)"

# (locus, símbolo, es_tf) del diccionario de juguete.
GENES = [
    ("PA9001", "qzaR", "true"), ("PA9002", "wvaA", "false"),
    ("PA9003", "wvbA", "false"), ("PA9004", "wvcA", "false"),
    ("PA9005", "wvdA", "false"), ("PA9006", "wveA", "false"),
    ("PA9007", "wvfA", "false"), ("PA9008", "wvgA", "false"),
    ("PA9010", "qzbR", "true"), ("PA9011", "qzdR", "true"),
    ("PA9012", "wvhA", "false"), ("PA9013", "wviA", "false"),
    ("PA9014", "wvkA", "false"), ("PA9015", "wvmA", "false"),
    ("PA9016", "wvjA", "false"), ("PA9018", "qzcR", "true"),
    ("PA9041", "wvnA", "false"), ("PA9042", "wvnB", "false"),
    ("PA9043", "qzoN", "false"),
]
# Un operón del catálogo, como `mexEF-oprN`.
OPERONES = [("wvnAB-qzoN", "wvnA|wvnB|qzoN", "PA9041|PA9042|PA9043")]


def _fila(regulador, blanco, referencia):
    return ["qzxR", "wvxA", "+", referencia, regulador, blanco, HIST, "x"]


FILAS_BASE = {
    1: ENCABEZADOS,
    2: _fila("PA9001", "PA9001", P1),
    3: _fila("PA9001", "PA9002", P1),
    4: _fila("PA9001", "PA9003", P1),
    5: _fila("PA9001", "PA9004", P1),
    6: _fila("PA9018", "PA9015", P1),
    7: _fila("PA9010", "PA9005", P1),
    8: _fila("PA9010", "PA9006", P1),
    9: _fila("PA9010", "PA9007", P1),
    10: _fila("PA9010", "PA9008", P1),
    11: _fila("PA9011", "PA9012", P1),
    12: _fila("PA9010", "PA9013", P1),
    13: _fila("PA9014", "PA9015", P1),
    14: _fila("PA9010", "PA9016", P2 + ", " + P1),
    15: _fila("PA9001", "PA9020", P2),
    16: _fila("PA9001", "PA9021", P2),
    17: _fila("PA9001", "PA9022", P3),
    18: _fila("PA9001", "PA9023", P1 + " homology"),
    19: _fila("PA9030", "PA9031", P_B),
    20: _fila("PA9030", "PA9032", P_B),
    21: _fila("PA9030", "PA9033", P_B),
    22: _fila("PA9030", "PA9034", P_B),
}

ESPERADO = {
    2: ("autorregulacion", None), 3: ("regla_b", None),
    4: ("misma_fila", None), 5: ("misma_tabla", None),
    6: ("misma_tabla", None),
    7: ("tabla_y_texto", "uno_solo_en_el_texto"),
    8: ("tabla_y_texto", "los_dos_en_el_texto"),
    9: ("solo_texto", "oraciones_distintas"),
    10: ("solo_texto", "misma_oracion"),
    11: ("ninguno", "ninguno_aparece"), 12: ("ninguno", "uno_solo"),
    13: ("ninguno", "tablas_distintas"),
    14: ("solo_texto", "oraciones_distintas"),
    15: ("sin_xml", None), 16: ("sin_xml", None), 17: ("sin_xml", None),
}

# La oración del artículo 1 que la regla b encuentra, y una de otro artículo
# que solo la regla a vería: la fila 9 no es «regla b» por ella.
ORACIONES = [(P1, "PA9001;PA9002", ""), (P_OTRO, "PA9007;PA9010", "")]
UNIDADES = [(P1, "abstract"), (P1, "xml"), (P2, "abstract"),
            (P3, "abstract"), (P_OTRO, "abstract")]

JATS_1 = u"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC
  "-//NLM//DTD JATS (Z39.96) Journal Archiving DTD v1.2//EN"
  "JATS-archivearticle1.dtd">
<article xmlns:xlink="http://www.w3.org/1999/xlink"
         article-type="research-article">
<front><article-meta>
<title-group>
<article-title>The wvaA regulon of a made-up organism</article-title>
</title-group>
<abstract>
<p>The regulator QzbR controls many genes in this made-up organism.</p>
</abstract>
</article-meta></front>
<body>
<sec><title>Results</title>
<p>The qzbR mutant was built for this work. Expression of
<italic>wvfA</italic> was measured by qPCR in all strains.</p>
<p>The <italic>wveA</italic> transcript was abundant. The wvjA gene lies
downstream of the cluster.</p>
<fig id="F1"><label>Figure 1</label>
<caption><p>Growth of the qzoN mutant.</p></caption></fig>
<table-wrap id="T1" position="float"><label>Table 1</label>
<caption><title>Genes regulated by QzaR.</title></caption>
<table><thead><tr><th>Gene</th><th>Fold change</th></tr></thead>
<tbody><tr><td>wvcA<sup>b</sup></td><td>2.5</td></tr>
<tr><td><ext-link xlink:href="https://example.org/x">PA9002</ext-link></td>
<td>3.0</td></tr></tbody></table>
<table-wrap-foot>
<fn id="tf1"><p><sup>b</sup>Measured by qPCR.</p></fn>
</table-wrap-foot>
</table-wrap>
<p>As shown in Table 2 <table-wrap id="T2"><label>Table 2</label>
<caption><p>Expression in the mutant.</p></caption>
<table><thead><tr><th>Regulator and target</th><th>Fold</th></tr></thead>
<tbody><tr><td>QzaR<break/>wvbA</td><td>4.1</td></tr>
<tr><td>PA9005</td><td>1.2</td></tr>
<tr><td><italic>wveA</italic></td><td>0.8</td></tr>
<tr><td>PA9014</td><td>1.1</td></tr>
<tr><td><italic>wvnAB</italic>-<italic>qzoN</italic></td><td>5.0</td></tr>
</tbody></table></table-wrap> the targets vary between strains.</p>
</sec>
<sec><title>Methods</title>
<p>The qzbR and wvgA mutants were built by allelic exchange.</p>
</sec>
</body>
<floats-group>
<table-wrap id="T3"><label>Table 3</label>
<caption><p>Other targets.</p></caption>
<table><tbody><tr><td>Group 1</td>
<td><table><tbody><tr><td>PA9015</td></tr><tr><td>2.0</td></tr></tbody></table>
</td></tr></tbody></table>
<table-wrap-foot><p>Data from the qzcR study.</p></table-wrap-foot>
</table-wrap>
</floats-group>
</article>
"""

# Un JATS con espacio de nombres por omisión y una tabla OASIS: por nombre
# local se lee igual.
JATS_CON_ESPACIOS = u"""<?xml version="1.0" encoding="UTF-8"?>
<article xmlns="http://example.org/jats"
  xmlns:oasis="http://www.niso.org/standards/z39-96/ns/oasis-exchange/table">
<body><sec><title>Results</title>
<p>The qzbR gene is expressed in the stationary phase.</p>
<table-wrap><label>Table 1</label><caption><p>Targets of QzaR.</p></caption>
<oasis:table><oasis:tgroup cols="2"><oasis:tbody>
<oasis:row><oasis:entry>wvcA</oasis:entry>
<oasis:entry>PA9003</oasis:entry></oasis:row>
</oasis:tbody></oasis:tgroup></oasis:table>
</table-wrap>
</sec></body>
</article>
"""

# Una tabla de regulador y blancos con el regulador en una celda que abarca
# tres filas, y un grupo de tablas, metido en un párrafo, cuyo título nombra
# a otro regulador; su tabla es OASIS y abarca con `morerows`.
JATS_ABARCA = u"""<?xml version="1.0" encoding="UTF-8"?>
<article
  xmlns:oasis="http://www.niso.org/standards/z39-96/ns/oasis-exchange/table">
<body><sec><title>Results</title>
<table-wrap><label>Table 1</label><caption><p>Regulators and targets.</p>
</caption>
<table><thead><tr><th rowspan="2">Regulator</th><th>Target</th></tr></thead>
<tbody><tr><td rowspan="3">QzaR</td><td>wvaA</td></tr>
<tr><td>wvbA</td></tr>
<tr><td>wvcA</td></tr>
<tr><td rowspan="x">QzbR</td><td>wvdA</td></tr>
</tbody></table></table-wrap>
<p>See Table 2 <table-wrap-group><label>Table 2</label>
<caption><p>Targets of QzdR.</p></caption>
<table-wrap><label>Table 2a</label><caption><p>First part.</p></caption>
<oasis:table><oasis:tgroup cols="2"><oasis:tbody>
<oasis:row><oasis:entry morerows="1">QzcR</oasis:entry>
<oasis:entry>wveA</oasis:entry></oasis:row>
<oasis:row><oasis:entry>wvfA</oasis:entry></oasis:row>
<oasis:row><oasis:entry>wvgA</oasis:entry></oasis:row>
</oasis:tbody></oasis:tgroup></oasis:table>
</table-wrap></table-wrap-group> for the second set.</p>
</sec></body>
</article>
"""

# Lo que no puede salir en nada publicable.
_LOCUS = re.compile(r"PA[0-9]{4}")
_SIETE_U_OCHO = re.compile(r"(?<![0-9])[0-9]{7,8}(?![0-9])")


def recursos_de_juguete(carpeta):
    """(léxico, {id: locus}, catálogo) del diccionario de juguete, con los
    lectores del bronce."""
    genes = os.path.join(carpeta, "genes.tsv")
    with io.open(genes, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(lexico.COLUMNAS_GENES) + "\n")
        for locus, simbolo, es_tf in GENES:
            f.write("\t".join([locus, simbolo, "", "protein_coding",
                               u"proteína inventada", es_tf, "", "prueba",
                               "false"]) + "\n")
    ruta_operones = os.path.join(carpeta, "operones.tsv")
    with io.open(ruta_operones, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(lexico.COLUMNAS_OPERONES) + "\n")
        for nombre, miembros, locus in OPERONES:
            f.write("\t".join([nombre, miembros, locus, "prueba"]) + "\n")
    mapa = {}
    for locus, simbolo, _ in GENES:
        mapa[locus] = locus
        mapa[simbolo] = locus
    return (lexico.Lexico.cargar(genes, ruta_operones), mapa,
            operones.Catalogo.cargar(ruta_operones))


def escribir(ruta, texto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return ruta


class _ConEscenario(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grn_tablas_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.recursos = recursos_de_juguete(self.tmp)
        parche = mock.patch.object(T, "cargar_recursos",
                                   return_value=self.recursos)
        parche.start()
        self.addCleanup(parche.stop)
        self.base = construir_xlsx(
            os.path.join(self.tmp, "base_sintetica.xlsx"),
            [("Hoja1", FILAS_BASE)])
        self.carpeta = os.path.join(self.tmp, "corrida4_prueba")
        os.makedirs(self.carpeta)
        prefijo = os.path.join(self.carpeta,
                               "bronce_identificacion_corrida4_20990101")
        self.candidatas = escribir_candidatas(
            prefijo + "_oraciones_candidatas.csv", ORACIONES)
        self.menciones = escribir_menciones(prefijo + "_menciones.csv",
                                            UNIDADES)
        self.xml = os.path.join(self.tmp, "fulltext")
        os.makedirs(self.xml)
        self.xml_1 = escribir(os.path.join(self.xml,
                                           "%s_PMC9100001.xml" % P1), JATS_1)
        self.xml_3 = escribir(os.path.join(self.xml,
                                           "%s_PMC9100003.xml" % P3),
                              u"<article><body><p>cortado")
        self.excluir = escribir_lista(os.path.join(self.tmp, "excluir.tsv"),
                                      [P_B])
        self.confidencial = os.path.join(self.tmp, "confidencial")
        self.informe = os.path.join(self.tmp, "publicable", "TABLAS.md")

    def exigibles(self):
        return C.denominador(V.leer_base(self.base)[0], {P_B})[0]

    def por_fila(self):
        return dict((f["fila_origen"], f) for f in self.exigibles())

    def pares(self):
        return C.pares_del_bronce(self.candidatas, True)

    def indice_1(self):
        return T.indice_de_articulo([self.xml_1], *self.recursos)

    def indices(self):
        return {P1: self.indice_1(), P2: None, P3: None}

    def correr(self, **kwargs):
        lineas = []
        kwargs.setdefault("informe", self.informe)
        kwargs.setdefault("excluir", [self.excluir])
        kwargs.setdefault("aceptar_base_distinta", True)
        resultado = T.ejecutar(self.base, self.carpeta, self.xml,
                               self.confidencial, log=lineas.append, **kwargs)
        return resultado, lineas

    def assertSinContenido(self, texto):
        """Ni locus, ni PMIDs, ni nombres de gen, ni rutas."""
        self.assertIsNone(_LOCUS.search(texto))
        self.assertIsNone(_SIETE_U_OCHO.search(texto))
        for pmid in PMIDS:
            self.assertNotIn(pmid, texto)
        for nombre in ("qz", "wv"):
            self.assertNotIn(nombre, texto.lower())
        for ruta in (self.tmp, self.tmp.replace("\\", "/"),
                     os.path.basename(self.tmp), "base_sintetica",
                     "fulltext", "PMC9100001"):
            self.assertNotIn(ruta, texto)
        R.verificar_publicable(texto)


class PruebasJats(_ConEscenario):

    def test_tablas_con_titulo_filas_y_pie(self):
        t1, t2, t3 = T.tablas_de_jats(self.xml_1)
        self.assertEqual("Table 1 Genes regulated by QzaR.", t1["titulo"])
        # El superíndice de la nota se separa del gen, y el enlace también.
        self.assertEqual([["Gene", "Fold change"], ["wvcA b", "2.5"],
                          ["PA9002", "3.0"]], t1["filas"])
        self.assertEqual("b Measured by qPCR.", t1["pie"])
        self.assertEqual("Table 2 Expression in the mutant.", t2["titulo"])
        # El <break/> separa; la cursiva no parte el nombre del operón.
        self.assertEqual(["QzaR wvbA", "4.1"], t2["filas"][1])
        self.assertEqual(["wvnAB-qzoN", "5.0"], t2["filas"][5])
        self.assertEqual("", t2["pie"])

    def test_una_tabla_anidada_no_se_pierde(self):
        t3 = T.tablas_de_jats(self.xml_1)[2]
        # La celda que la contiene trae su texto, y sus filas cuentan como
        # filas de la tabla de afuera.
        self.assertEqual([["Group 1", "PA9015 2.0"], ["PA9015"], ["2.0"]],
                         t3["filas"])
        self.assertEqual("Data from the qzcR study.", t3["pie"])

    def test_tolera_espacios_de_nombres(self):
        ruta = escribir(os.path.join(self.tmp, "con_espacios.xml"),
                        JATS_CON_ESPACIOS)
        tablas = T.tablas_de_jats(ruta)
        self.assertEqual(1, len(tablas))
        self.assertEqual("Table 1 Targets of QzaR.", tablas[0]["titulo"])
        self.assertEqual([["wvcA", "PA9003"]], tablas[0]["filas"])
        self.assertEqual(["The qzbR gene is expressed in the stationary "
                          "phase."], T.oraciones_de_jats(ruta))

    def test_el_texto_es_el_del_bronce_sin_las_tablas(self):
        oraciones = T.oraciones_de_jats(self.xml_1)
        self.assertEqual([
            "The regulator QzbR controls many genes in this made-up "
            "organism.",
            "The qzbR mutant was built for this work.",
            "Expression of wvfA was measured by qPCR in all strains.",
            "The wveA transcript was abundant.",
            "The wvjA gene lies downstream of the cluster.",
            # La tabla 2 estaba dentro de este párrafo: se va ella y se
            # queda lo que la seguía.
            "As shown in Table 2 the targets vary between strains.",
            "The qzbR and wvgA mutants were built by allelic exchange.",
            # El pie de figura sí es texto; los títulos de las tablas, no.
            "Growth of the qzoN mutant.",
        ], oraciones)

    def test_una_celda_que_abarca_varias_filas_cuenta_en_cada_una(self):
        ruta = escribir(os.path.join(self.tmp, "abarca.xml"), JATS_ABARCA)
        t1, t2 = T.tablas_de_jats(ruta)
        # El `rowspan` del encabezado no pasa al cuerpo, y uno que no es
        # número no abarca nada.
        self.assertEqual([["Regulator", "Target"], ["QzaR", "wvaA"],
                          ["QzaR", "wvbA"], ["QzaR", "wvcA"],
                          ["QzbR", "wvdA"]], t1["filas"])
        # En OASIS, `morerows` dice cuántas filas más.
        self.assertEqual([["QzcR", "wveA"], ["QzcR", "wvfA"], ["wvgA"]],
                         t2["filas"])

    def test_el_titulo_del_grupo_es_el_de_sus_tablas(self):
        ruta = escribir(os.path.join(self.tmp, "abarca.xml"), JATS_ABARCA)
        t2 = T.tablas_de_jats(ruta)[1]
        self.assertEqual("Table 2 Targets of QzdR. Table 2a First part.",
                         t2["titulo"])
        # Y el grupo sale del texto con su título: dentro de un párrafo, se
        # habría pegado a la prosa.
        self.assertEqual(["See Table 2 for the second set."],
                         T.oraciones_de_jats(ruta))

    def test_un_xml_ilegible_no_dice_cual(self):
        for contenido in (u"<article><body><p>cortado",
                          # Una codificación que Python no conoce y una
                          # multibyte que expat no lee.
                          u'<?xml version="1.0" encoding="x-inventada"?><a/>',
                          u'<?xml version="1.0" encoding="Shift_JIS"?><a/>'):
            escribir(self.xml_3, contenido)
            for funcion in (T.tablas_de_jats, T.oraciones_de_jats):
                with self.subTest(contenido=contenido[:40],
                                  funcion=funcion.__name__):
                    with self.assertRaises(ValueError) as ctx:
                        funcion(self.xml_3)
                    self.assertNotIn(P3, str(ctx.exception))
                    self.assertIn("--xml", str(ctx.exception))

    def test_los_xml_de_un_pmid(self):
        self.assertEqual([self.xml_1], T.xml_de(self.xml, P1))
        self.assertEqual([], T.xml_de(self.xml, P2))
        # El prefijo es el PMID entero, no un pedazo.
        self.assertEqual([], T.xml_de(self.xml, P1[:-1]))


class PruebasLocus(_ConEscenario):

    def test_locus_de_texto(self):
        self.assertEqual(
            {"PA9001", "PA9004", "PA9041", "PA9042", "PA9043"},
            T.locus_de_texto("QzaR represses the wvnAB-qzoN operon, PA9004 "
                             "and noExisteXyz.", *self.recursos))
        self.assertEqual(set(), T.locus_de_texto("", *self.recursos))
        # Un operón que el texto abrevia y el catálogo no conoce no se
        # expande: es la regla de `grn_bronce.operones`.
        self.assertEqual({"PA9043"}, T.locus_de_texto("wvnAB qzoN",
                                                      *self.recursos))

    def test_el_indice_del_articulo(self):
        indice = self.indice_1()
        self.assertEqual((3, 12), (indice["n_tablas"], indice["n_filas"]))
        self.assertEqual({"PA9006", "PA9007", "PA9008", "PA9010", "PA9016",
                          "PA9043"}, indice["texto"])
        self.assertEqual([{"PA9008", "PA9010"}], indice["oraciones"])
        t1, t2, t3 = indice["tablas"]
        self.assertEqual({"PA9001", "PA9002", "PA9004"}, t1["todo"])
        self.assertEqual([{"PA9001", "PA9003"},
                          {"PA9041", "PA9042", "PA9043"}], t2["filas"])
        self.assertEqual({"PA9015", "PA9018"}, t3["todo"])


class PruebasCategorias(_ConEscenario):

    def probar(self, categoria):
        """Las filas del escenario que caen en `categoria`, con su detalle."""
        filas = self.por_fila()
        pares, indices = self.pares(), self.indices()
        mayores = T.articulos_mayores(list(filas.values()))
        numeros = sorted(n for n, (c, _) in ESPERADO.items() if c == categoria)
        self.assertTrue(numeros)
        for n in numeros:
            with self.subTest(fila=n):
                self.assertEqual(ESPERADO[n], T.categoria(
                    filas[n], pares, indices, mayores))

    def test_autorregulacion(self):
        self.probar("autorregulacion")

    def test_regla_b(self):
        self.probar("regla_b")

    def test_sin_xml(self):
        """El artículo 2 no tiene XML y el del 3 no se puede leer."""
        self.probar("sin_xml")

    def test_misma_fila(self):
        """Regulador y blanco en una celda, separados por un `<break/>`."""
        self.probar("misma_fila")

    def test_misma_tabla(self):
        """El regulador en el título (fila 5) o en el pie (fila 6), y el
        blanco en una celda; en la 6, la de la tabla anidada."""
        self.probar("misma_tabla")

    def test_tabla_y_texto(self):
        self.probar("tabla_y_texto")

    def test_solo_texto(self):
        """La 10 coocurre en una oración de métodos, que el bronce no toma
        como candidata; la 14 cita además un artículo sin XML."""
        self.probar("solo_texto")

    def test_ninguno(self):
        self.probar("ninguno")

    def test_el_escenario(self):
        """Los tres artículos en orden, todas las categorías con alguna fila
        y ninguna fila exigible de ellos sin caso."""
        exigibles = self.exigibles()
        self.assertEqual([P1, P2, P3], T.articulos_mayores(exigibles))
        self.assertEqual(set(T.CATEGORIAS),
                         set(c for c, _ in ESPERADO.values()))
        self.assertEqual(set(ESPERADO),
                         set(f["fila_origen"] for f in exigibles))

    def test_sin_xml_da_sin_xml(self):
        filas = self.por_fila()
        pares = self.pares()
        sin_nada = {P1: None, P2: None, P3: None}
        for n in (4, 9, 14):
            self.assertEqual(("sin_xml", None),
                             T.categoria(filas[n], pares, sin_nada,
                                         [P1, P2, P3]))
        # La fila 14 cita al 2, sin XML, y al 1, con XML: «sin XML» es solo
        # si ninguno de los que cita lo tiene.
        indices = self.indices()
        self.assertEqual(("sin_xml", None),
                         T.categoria(filas[14], pares, indices, [P2]))
        self.assertEqual("solo_texto",
                         T.categoria(filas[14], pares, indices, [P2, P1])[0])

    def test_la_regla_b_gana_sobre_la_tabla(self):
        fila = self.por_fila()[3]
        indices = self.indices()
        self.assertEqual(("regla_b", None),
                         T.categoria(fila, self.pares(), indices, [P1]))
        sin_bronce = (set(), {})
        self.assertEqual(("misma_tabla", None),
                         T.categoria(fila, sin_bronce, indices, [P1]))

    def test_la_celda_que_abarca_y_el_grupo_en_las_categorias(self):
        ruta = escribir(os.path.join(self.tmp, "abarca.xml"), JATS_ABARCA)
        indices = {P1: T.indice_de_articulo([ruta], *self.recursos)}
        sin_bronce = (set(), {})
        for regulador, blanco, esperada in (
                # El regulador abarca la fila del blanco (XHTML y OASIS).
                ("PA9001", "PA9004", "misma_fila"),
                ("PA9018", "PA9007", "misma_fila"),
                # Su celda acaba antes de la fila de este blanco.
                ("PA9001", "PA9005", "misma_tabla"),
                # Solo el título del grupo nombra al regulador.
                ("PA9011", "PA9008", "misma_tabla")):
            fila = {"regulador": regulador, "blanco": blanco, "pmids": [P1]}
            with self.subTest(par=(regulador, blanco)):
                self.assertEqual(esperada, T.categoria(
                    fila, sin_bronce, indices, [P1])[0])

    def test_la_regla_a_no_cuenta(self):
        """La fila 9 coocurre en una candidata de otro artículo: la regla a
        la cubriría, pero aquí se pregunta por el artículo que cita."""
        fila = self.por_fila()[9]
        self.assertTrue(C.cubierta(fila, self.pares(), "a"))
        self.assertEqual("solo_texto", T.categoria(
            fila, self.pares(), self.indices(), [P1])[0])

    def test_articulos_mayores_coincide_con_la_concentracion(self):
        def fila(*pmids):
            return {"pmids": list(pmids)}
        a, b, c = "91000011", "91000012", "91000013"
        casos = [
            # `a` con 3; `b` y `c` empatan con 2, y una fila de `b` cita
            # también a `a`: el desempate decide cuántas filas se reúnen.
            [fila(a), fila(a, b), fila(a), fila(b), fila(c), fila(c)],
            # Lo mismo, con el PMID menor del otro lado del empate.
            [fila(a), fila(a, c), fila(a), fila(c), fila(b), fila(b)],
            [fila(c, c, a), fila(b), fila()],
            [],
        ]
        for filas in casos:
            for cuantos in (1, 2, 3, 5):
                mayores = set(T.articulos_mayores(filas, cuantos))
                self.assertEqual(
                    C._concentracion(filas, cuantos),
                    sum(1 for f in filas if mayores & set(f["pmids"])),
                    (filas, cuantos))
        self.assertEqual([a, b, c], T.articulos_mayores(casos[0], 3))
        self.assertEqual([a, b], T.articulos_mayores(casos[1], 2))
        exigibles = self.exigibles()
        self.assertEqual(C._concentracion(exigibles), sum(
            1 for f in exigibles
            if set(T.articulos_mayores(exigibles)) & set(f["pmids"])))


class PruebasEjecutar(_ConEscenario):

    def test_de_punta_a_punta(self):
        resultado, lineas = self.correr()
        juntos = resultado["juntos"]
        self.assertEqual(16, juntos["filas"])
        self.assertEqual(collections.OrderedDict([
            ("autorregulacion", 1), ("regla_b", 1), ("sin_xml", 3),
            ("misma_fila", 1), ("misma_tabla", 2), ("tabla_y_texto", 2),
            ("solo_texto", 3), ("ninguno", 3)]), juntos["categorias"])
        self.assertEqual({"los_dos_en_el_texto": 1,
                          "uno_solo_en_el_texto": 1},
                         dict(juntos["detalles"]["tabla_y_texto"]))
        self.assertEqual({"misma_oracion": 1, "oraciones_distintas": 2},
                         dict(juntos["detalles"]["solo_texto"]))
        self.assertEqual({"ninguno_aparece": 1, "uno_solo": 1,
                          "tablas_distintas": 1},
                         dict(juntos["detalles"]["ninguno"]))
        a1, a2, a3 = resultado["por_articulo"]
        self.assertEqual((1, 13, "si", "xml", 3, 12),
                         (a1["articulo"], a1["filas"], a1["xml"],
                          a1["bronce"], a1["tablas"], a1["filas_de_tabla"]))
        self.assertEqual(0, a1["categorias"]["sin_xml"])
        self.assertEqual(3, a1["categorias"]["solo_texto"])
        # La fila 14 cuenta en el artículo 2 como sin XML.
        self.assertEqual((3, "no", "abstract", None),
                         (a2["filas"], a2["xml"], a2["bronce"],
                          a2["tablas"]))
        self.assertEqual(3, a2["categorias"]["sin_xml"])
        self.assertEqual((1, "ilegible", 1),
                         (a3["filas"], a3["xml"],
                          a3["categorias"]["sin_xml"]))
        self.assertEqual({"articulos": 3, "articulos_con_xml": 1,
                          "articulos_ilegibles": 1, "archivos": 2,
                          "leidos": 1}, dict(resultado["xml"]))
        self.assertEqual(16, resultado["denominador"]
                         ["en_los_5_articulos_mayores"])
        self.assertTrue(any("no se pudo leer" in a
                            for a in resultado["avisos"]))

        # A la carpeta confidencial va solo el registro: nada fila por fila.
        self.assertEqual([T.ARCHIVO_REGISTRO],
                         os.listdir(self.confidencial))
        with io.open(os.path.join(self.confidencial, T.ARCHIVO_REGISTRO),
                     encoding="utf-8") as f:
            registro = json.load(f)
        for llave, ruta in (("base", self.base),
                            ("candidatas", self.candidatas),
                            ("menciones", self.menciones)):
            self.assertEqual(procedencia.huella(ruta),
                             registro["huellas"][llave])
        self.assertIn("genes_pao1.tsv", registro["huellas"])
        self.assertEqual(5, registro["parametros"]["cuantos"])
        self.assertEqual(2, registro["resultado"]["xml"]["archivos"])
        self.assertTrue(os.path.isfile(self.informe))
        self.assertTrue(lineas[-1].startswith("Escrito en la carpeta de "
                                              "--confidencial"))

    def test_el_informe_no_lleva_locus_pmids_ni_rutas(self):
        _, lineas = self.correr()
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertSinContenido(texto)
        self.assertSinContenido("\n".join(lineas))
        with io.open(os.path.join(self.confidencial, T.ARCHIVO_REGISTRO),
                     encoding="utf-8") as f:
            registro = f.read()
        # El registro tampoco: lleva huellas, no PMIDs ni locus.
        self.assertIsNone(_LOCUS.search(registro))
        for pmid in PMIDS:
            self.assertNotIn(pmid, registro)
        # Y sí lleva lo que tiene que llevar.
        self.assertIn("| misma fila de una tabla | 1 | 6.2 % | 9.1 % |",
                      texto)
        self.assertIn("| **total** | **16** | 100.0 % | 100.0 % |", texto)
        self.assertIn("| | artículo 1 | artículo 2 | artículo 3 |", texto)
        self.assertIn("| XML en `--xml` | sí | no | ilegible |", texto)
        self.assertIn("| tablas (filas de tabla) | 3 (12) | — | — |", texto)
        self.assertIn("- Solo texto: en una misma oración que el bronce no "
                      "tomó como candidata, 1; en oraciones distintas, 2.",
                      texto)
        # Las cautelas que dicen dónde «misma fila» y «misma tabla» engañan.
        self.assertIn("una fila entre dos genes del mismo operón cae en "
                      "«misma fila»", texto)
        self.assertIn("encabezado de una columna", texto)

    def test_una_codificacion_desconocida_cuenta_como_ilegible(self):
        """Antes tumbaba la corrida: `ET.parse` lanza LookupError."""
        escribir(self.xml_3,
                 u'<?xml version="1.0" encoding="x-inventada"?><article/>')
        resultado, _ = self.correr()
        self.assertEqual((1, "ilegible", 1),
                         (resultado["por_articulo"][2]["filas"],
                          resultado["por_articulo"][2]["xml"],
                          resultado["por_articulo"][2]["categorias"]
                          ["sin_xml"]))

    def test_el_aviso_de_ilegibles_concuerda_en_numero(self):
        _, lineas = self.correr()
        self.assertIn("AVISO: 1 de los artículos tiene un XML que no se pudo "
                      "leer: cuenta como sin XML.", lineas)
        escribir(self.xml_1, u"<article><body>")
        _, lineas = self.correr()
        self.assertIn("AVISO: 2 de los artículos tienen un XML que no se "
                      "pudo leer: cuenta como sin XML.", lineas)

    def test_cuantos(self):
        resultado, _ = self.correr(cuantos=1)
        self.assertEqual(1, len(resultado["por_articulo"]))
        # Solo las filas que citan el artículo 1, la 14 incluida.
        self.assertEqual(13, resultado["juntos"]["filas"])
        self.assertEqual(0, resultado["juntos"]["categorias"]["sin_xml"])
        with self.assertRaises(ValueError) as ctx:
            self.correr(cuantos=0)
        self.assertIn("--cuantos", str(ctx.exception))

    def test_sin_exclusiones_el_articulo_excluido_entra(self):
        resultado, _ = self.correr(excluir=[])
        # Las 4 filas de B lo vuelven el artículo 2, sin XML.
        self.assertEqual(4, len(resultado["por_articulo"]))
        self.assertEqual((4, "no"), (resultado["por_articulo"][1]["filas"],
                                     resultado["por_articulo"][1]["xml"]))
        self.assertTrue(any("--excluir-pmids" in a
                            for a in resultado["avisos"]))

    def test_un_cotejo_que_no_cuadra_se_detiene(self):
        lineas = []
        with self.assertRaises(ValueError) as ctx:
            T.ejecutar(self.base, self.carpeta, self.xml, self.confidencial,
                       informe=self.informe, excluir=[self.excluir],
                       log=lineas.append)
        self.assertIn("--aceptar-base-distinta", str(ctx.exception))
        self.assertFalse(os.path.exists(self.confidencial))
        self.assertFalse(os.path.exists(self.informe))
        self.assertSinContenido("\n".join(lineas + [str(ctx.exception)]))

    def test_una_carpeta_confidencial_dentro_del_repositorio_se_rechaza(self):
        dentro = os.path.join(E.RAIZ_REPO, "salidas",
                              "tablas_prueba_%d" % os.getpid())
        self.addCleanup(shutil.rmtree, dentro, True)
        with mock.patch.object(V, "leer_base",
                               side_effect=AssertionError("abrió la base")):
            with self.assertRaises(ValueError) as ctx:
                T.ejecutar(self.base, self.carpeta, self.xml, dentro,
                           informe=self.informe, aceptar_base_distinta=True)
        mensaje = str(ctx.exception)
        self.assertIn("--confidencial", mensaje)
        self.assertNotIn(dentro, mensaje)
        self.assertNotIn(E.RAIZ_REPO, mensaje)
        self.assertFalse(os.path.exists(dentro))
        self.assertFalse(os.path.exists(self.informe))

    def test_sin_la_carpeta_de_xml_no_abre_la_base(self):
        falta = os.path.join(self.tmp, "secreta_fulltext")
        with mock.patch.object(V, "leer_base",
                               side_effect=AssertionError("abrió la base")):
            with self.assertRaises(ValueError) as ctx:
                T.ejecutar(self.base, self.carpeta, falta, self.confidencial,
                           aceptar_base_distinta=True)
        self.assertIn("--xml", str(ctx.exception))
        self.assertNotIn("secreta", str(ctx.exception))

    def test_sin_ningun_xml_se_avisa(self):
        os.remove(self.xml_1)
        os.remove(self.xml_3)
        # Queda el de un artículo que no está entre los mayores.
        escribir(os.path.join(self.xml, "%s_PMC9100005.xml" % P_OTRO),
                 u"<article/>")
        resultado, _ = self.correr()
        self.assertEqual(14, resultado["juntos"]["categorias"]["sin_xml"])
        self.assertTrue(any("ninguno de los artículos tiene su XML" in a
                            for a in resultado["avisos"]))

    def test_una_carpeta_de_xml_sin_xml_no_abre_la_base(self):
        """La carpeta de arriba del texto completo, con los XML en su
        subcarpeta xml: todo habría salido «sin XML»."""
        arriba = os.path.join(self.tmp, "texto_completo_secreto")
        os.makedirs(os.path.join(arriba, "xml"))
        os.makedirs(os.path.join(arriba, "pdf"))
        shutil.copy(self.xml_1, os.path.join(arriba, "xml"))
        with mock.patch.object(V, "leer_base",
                               side_effect=AssertionError("abrió la base")):
            with self.assertRaises(ValueError) as ctx:
                T.ejecutar(self.base, self.carpeta, arriba, self.confidencial,
                           excluir=[self.excluir], aceptar_base_distinta=True)
        mensaje = str(ctx.exception)
        self.assertIn("--xml", mensaje)
        self.assertIn("subcarpeta xml", mensaje)
        self.assertNotIn("secreto", mensaje)
        R.verificar_publicable(mensaje)
        self.assertFalse(os.path.exists(self.confidencial))


class PruebasImportar(unittest.TestCase):

    def test_importar_no_trae_torch_ni_spacy(self):
        """Corre con el intérprete del servidor, que no tiene por qué tener
        ninguno de los dos. En un proceso aparte: en este, todo lo que importa
        `tablas` ya está cargado y la prueba no vería nada."""
        codigo = ("import sys\n"
                  "for m in ('torch', 'transformers', 'spacy'):\n"
                  "    sys.modules[m] = None\n"
                  "import grn_verificacion.tablas\n")
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hecho = subprocess.run([sys.executable, "-c", codigo], cwd=raiz,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        self.assertEqual(0, hecho.returncode,
                         hecho.stderr.decode("utf-8", "replace"))


class PruebasCli(_ConEscenario):

    def argv(self, *extra):
        return (["tablas", "--base", self.base, "--carpeta", self.carpeta,
                 "--xml", self.xml, "--excluir-pmids", self.excluir,
                 "--informe", self.informe, "--confidencial",
                 self.confidencial] + list(extra))

    def main(self, argv):
        lineas = []
        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main(argv)
        return codigo, lineas

    def test_la_ayuda(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["tablas", "--help"])
        self.assertEqual(0, ctx.exception.code)
        for buscado in ("--base", "--carpeta", "--xml", "--excluir-pmids",
                        "--informe", "--confidencial", "--cuantos", "--hoja",
                        "--aceptar-base-distinta"):
            self.assertIn(buscado, salida.getvalue())

    def test_corre_y_no_imprime_rutas_ni_contenido(self):
        codigo, lineas = self.main(self.argv("--aceptar-base-distinta",
                                             "--cuantos", "2"))
        self.assertEqual(0, codigo, lineas)
        self.assertSinContenido("\n".join(lineas))
        self.assertTrue(os.path.isfile(self.informe))
        with io.open(os.path.join(self.confidencial, T.ARCHIVO_REGISTRO),
                     encoding="utf-8") as f:
            self.assertEqual(2, json.load(f)["parametros"]["cuantos"])

    def test_cuantos_por_omision(self):
        """El parser no importa `tablas` (traería el puente a cada comando):
        el valor por omisión lo pone `cmd_tablas`."""
        with mock.patch.object(T, "ejecutar") as ejecutar:
            codigo, _ = self.main(self.argv())
        self.assertEqual(0, codigo)
        self.assertEqual(T.CUANTOS, ejecutar.call_args[1]["cuantos"])

    def test_un_error_sale_con_1_y_el_mensaje_filtrado(self):
        codigo, lineas = self.main(self.argv())
        self.assertEqual(1, codigo)
        self.assertTrue(lineas[-1].startswith("ERROR: La base no coincide"))
        self.assertSinContenido("\n".join(lineas))
        self.assertFalse(os.path.exists(self.informe))

    def test_un_error_inesperado_sale_sin_la_ruta(self):
        ruta = os.path.join(self.xml, "%s_PMC9100001.xml" % P1)
        error = FileNotFoundError(2, "No such file or directory", ruta)
        with mock.patch.object(T, "ejecutar", side_effect=error):
            codigo, lineas = self.main(self.argv())
        self.assertEqual(1, codigo)
        self.assertEqual(["ERROR: FileNotFoundError: No such file or "
                          "directory"], lineas)
        # Un ValueError con la ruta de --xml la cambia por <ruta>.
        error = ValueError("No pude con %s." % self.xml)
        with mock.patch.object(T, "ejecutar", side_effect=error):
            codigo, lineas = self.main(self.argv())
        self.assertEqual((1, ["ERROR: No pude con <ruta>."]),
                         (codigo, lineas))

    def test_sin_base(self):
        argv = self.argv()
        del argv[argv.index("--base"):argv.index("--base") + 2]
        with mock.patch.dict(os.environ):
            os.environ.pop("BASE_CURADA", None)
            codigo, lineas = self.main(argv)
        self.assertEqual(2, codigo)
        self.assertIn("falta --base", lineas[-1])


if __name__ == "__main__":
    unittest.main()
