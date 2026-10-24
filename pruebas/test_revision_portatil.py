# -*- coding: utf-8 -*-
"""La página portátil de revisión: lo que no lleva y lo que mide igual.

Dos cosas tienen que ser ciertas para que la tanda 2 se pueda anotar con ella:

- **La página no lleva nada de la llave.** La carpeta de prueba tiene, al lado
  de la hoja, una llave, unos dobles y un resumen con el mismo señuelo que
  vigila `test_revision`.
- **Mide y exporta lo mismo que `revision.py`.** La lógica de la página corre
  en node, si está, contra `revision.validar`, `anotaciones_de_eventos` y
  `escribir_csv`: el mismo veredicto, el mismo tiempo y el mismo CSV byte a
  byte. Sin node esas pruebas se saltan, y la conversión del respaldo, que es
  Python, se prueba igual.
"""

import contextlib
import csv
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import revision
import revision_portatil as RP
from grn_verificacion import precision_ciega

from .test_revision import ITEMS, SENUELO, VALIDOS, escribir_hoja

NODE = shutil.which("node")

# Una oración que intenta cerrar el bloque de datos y abrir un comentario.
MALICIOSA = ("m-4567", 'PqsR binds </script><script>alert(1)</script><!-- '
             'the "pqsA" promoter, and pqsA rises.', "PqsR", "pqsA")


def _datos_de_la_pagina(texto):
    m = re.search(r'<script id="datos" type="application/json">(.*?)</script>',
                  texto, re.S)
    return json.loads(m.group(1))


def _callado(funcion, *args):
    """La CLI imprime una línea; en la suite no hace falta verla."""
    with contextlib.redirect_stdout(io.StringIO()),             contextlib.redirect_stderr(io.StringIO()):
        return funcion(*args)


class Base(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.carpeta = os.path.join(self.tmp, "muestra")
        os.makedirs(self.carpeta)
        escribir_hoja(self.carpeta, ITEMS + [MALICIOSA])
        # Lo que vive al lado de la hoja y la página no puede tener.
        with io.open(os.path.join(self.carpeta, "llave.csv"), "w",
                     encoding="utf-8") as f:
            f.write("id_item,pmid,direccion_bronce,capa\n"
                    "m-1234,12345678,1>2,%s\n" % SENUELO)
        for nombre in ("dobles.csv", "resumen.json"):
            with io.open(os.path.join(self.carpeta, nombre), "w",
                         encoding="utf-8") as f:
                f.write(SENUELO)
        self.hoja = revision.ruta_hoja(self.carpeta)

    def html(self):
        salida = os.path.join(self.tmp, "pagina.html")
        RP.exportar_html(self.hoja, salida)
        with io.open(salida, encoding="utf-8") as f:
            return f.read()


class PruebasPagina(Base):

    def test_no_lleva_nada_de_la_llave(self):
        texto = self.html()
        for prohibido in (SENUELO, "12345678", "direccion_bronce", "capa"):
            self.assertNotIn(prohibido, texto)
        datos = _datos_de_la_pagina(texto)
        self.assertEqual([it["id_item"] for it in datos["items"]],
                         [i[0] for i in ITEMS + [MALICIOSA]])
        for it in datos["items"]:
            self.assertEqual(sorted(it), sorted(revision.COLUMNAS_ITEM))

    def test_una_oracion_no_cierra_el_bloque_de_datos(self):
        texto = self.html()
        self.assertNotIn("<script>alert(1)", texto)
        self.assertNotIn("<!-- the", texto)
        # Y llega intacta a la página.
        oracion = _datos_de_la_pagina(texto)["items"][-1]["oracion"]
        self.assertEqual(oracion, MALICIOSA[1])

    def test_sin_recursos_de_fuera(self):
        """Se abre con doble clic, a veces sin red: nada de un CDN."""
        texto = self.html()
        self.assertIsNone(re.search(r'(src|href)\s*=\s*["\']?(https?:)?//',
                                    texto))

    def test_lo_que_mide_sale_de_revision(self):
        datos = _datos_de_la_pagina(self.html())
        self.assertEqual(datos["opciones"],
                         dict((c, list(v))
                              for c, v in revision.OPCIONES.items()))
        self.assertEqual(datos["columnas_exportadas"],
                         revision.COLUMNAS_EXPORTADAS)
        self.assertEqual(datos["tope_tramo_s"], 15 * 60)
        self.assertEqual(datos["huella"], RP.huella_hoja(self.hoja))

    def test_la_guia_va_escapada(self):
        guia = os.path.join(self.tmp, "guia.md")
        with io.open(guia, "w", encoding="utf-8") as f:
            f.write("# Guía\n\n- **si**: <b>no</b> pasa como HTML\n")
        texto, _ = RP.pagina(self.hoja, guia)
        self.assertIn("&lt;b&gt;no&lt;/b&gt;", texto)
        self.assertIn("<strong>si</strong>", texto)

    def test_la_guia_del_repositorio_existe(self):
        self.assertTrue(os.path.isfile(RP.GUIA))

    def test_la_cli(self):
        salida = os.path.join(self.tmp, "p.html")
        self.assertEqual(_callado(RP.main, ["exportar-html", "--carpeta",
                                            self.carpeta, "--salida", salida]),
                         0)
        self.assertTrue(os.path.isfile(salida))
        mala = os.path.join(self.tmp, "mala.csv")
        with io.open(mala, "w", encoding="utf-8") as f:
            f.write("id_item,oracion\nm-1,x\n")
        self.assertEqual(_callado(RP.main, ["exportar-html", "--hoja", mala,
                                            "--salida", salida]), 1)


def _eventos_de_prueba():
    """Tres ítems: uno con dos tramos, uno con un tramo de más de 15
    minutos, y uno corregido sin reabrir. Las horas como las de
    `toISOString`, con milisegundos y «Z»."""
    return [
        {"evento": "inicio", "id_item": "m-1234", "hora": "2026-10-24T10:00:00.250Z"},
        {"evento": "guardado", "id_item": "m-1234", "hora": "2026-10-24T10:01:00.100Z",
         "valores": dict(VALIDOS)},
        {"evento": "inicio", "id_item": "m-1234", "hora": "2026-10-24T11:00:00.000Z"},
        # El guardado que queda: lo difícil del CSV tiene que llegar a él.
        {"evento": "guardado", "id_item": "m-1234", "hora": "2026-10-24T11:00:45.000Z",
         "valores": dict(VALIDOS, signo="-",
                         comentario='coma, "comillas"\ny salto')},
        {"evento": "inicio", "id_item": "m-2345", "hora": "2026-10-24T12:00:00.000Z"},
        {"evento": "guardado", "id_item": "m-2345", "hora": "2026-10-24T12:16:00.000Z",
         "valores": {"relacion": "no", "direccion": "ninguna", "signo": "",
                     "tipo": "", "negada": "si", "especulativa": "no",
                     "comentario": "F6; β"}},
        # Un salto de línea solo, sin coma ni comillas que ya pidan comillas.
        {"evento": "guardado", "id_item": "m-4567", "hora": "2026-10-24T13:00:00.000Z",
         "valores": dict(VALIDOS, comentario="una línea\notra")},
        # Lo que no se entiende se salta, en las dos.
        {"evento": "guardado", "id_item": "m-12", "hora": "x", "valores": {}},
        {"evento": "otro", "id_item": "m-3456", "hora": "2026-10-24T13:00:00Z"},
    ]


class PruebasRespaldo(Base):

    def respaldo(self, eventos, huella=None):
        ruta = os.path.join(self.tmp, "respaldo.json")
        with io.open(ruta, "w", encoding="utf-8") as f:
            json.dump({"huella": huella or RP.huella_hoja(self.hoja),
                       "eventos": eventos}, f, ensure_ascii=False)
        return ruta

    def test_da_el_mismo_csv_que_el_tablero_y_lo_lee_precision_ciega(self):
        eventos = _eventos_de_prueba()
        desde = os.path.join(self.tmp, "desde_respaldo.csv")
        self.assertEqual(RP.desde_respaldo(self.respaldo(eventos), self.hoja,
                                           desde), 3)
        # Los mismos eventos en el JSONL del tablero.
        with io.open(revision.ruta_anotaciones(self.carpeta), "w",
                     encoding="utf-8") as f:
            for ev in eventos:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        tablero = revision.exportar_csv(self.carpeta)
        with open(desde, "rb") as a, open(tablero, "rb") as b:
            self.assertEqual(a.read(), b.read())

        anotacion = precision_ciega.leer_anotacion(desde)
        self.assertEqual(anotacion["m-2345"]["negada"], "si")
        with io.open(desde, encoding="utf-8-sig", newline="") as f:
            filas = dict((r["id_item"], r) for r in csv.DictReader(f))
        # 60 s y 45 s; la hora entre los dos tramos no cuenta.
        self.assertEqual(filas["m-1234"]["segundos"], "104")
        self.assertEqual(filas["m-1234"]["tramos_largos"], "0")
        # Un tramo de 16 minutos no se suma: se cuenta.
        self.assertEqual(filas["m-2345"]["segundos"], "")
        self.assertEqual(filas["m-2345"]["tramos_largos"], "1")
        # Sin inicio: sin tiempo, pero anotado.
        self.assertEqual(filas["m-4567"]["segundos"], "")
        self.assertEqual(filas["m-3456"]["relacion"], "")

    def test_un_respaldo_de_otra_hoja_no_se_convierte(self):
        with self.assertRaises(ValueError):
            RP.desde_respaldo(self.respaldo([], huella="0" * 64), self.hoja,
                              os.path.join(self.tmp, "x.csv"))

    def test_la_cli(self):
        salida = os.path.join(self.tmp, "x.csv")
        self.assertEqual(_callado(RP.main, [
            "desde-respaldo", "--respaldo", self.respaldo(_eventos_de_prueba()),
            "--carpeta", self.carpeta, "--salida", salida]), 0)


@unittest.skipUnless(NODE, "node no está: la lógica de la página no se puede "
                           "correr aquí")
class PruebasLaPaginaMideIgual(Base):
    """La lógica de la página contra la de revision.py, en node."""

    def correr(self, entrada):
        js = os.path.join(self.tmp, "arnes.js")
        with io.open(js, "w", encoding="utf-8") as f:
            f.write('const fs = require("fs");\n' + RP.LOGICA + r"""
const e = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = {
  validar: e.valores.map(v => { const r = Revision.validar(v, e.cfg);
                                return [r.errores.length > 0, r.avisos.length]; }),
  vigentes: e.secuencias.map(s => Revision.vigentes(s, e.cfg)),
  csv: Revision.exportarCSV(e.items, Revision.vigentes(e.eventos, e.cfg), e.cfg)
};
fs.writeFileSync(process.argv[3], JSON.stringify(out), "utf8");
""")
        ruta_e = os.path.join(self.tmp, "entrada.json")
        ruta_s = os.path.join(self.tmp, "salida.json")
        with io.open(ruta_e, "w", encoding="utf-8") as f:
            json.dump(entrada, f, ensure_ascii=False)
        subprocess.run([NODE, js, ruta_e, ruta_s], check=True,
                       capture_output=True, timeout=120)
        with io.open(ruta_s, encoding="utf-8") as f:
            return json.load(f)

    def test_valida_igual_que_revision(self):
        valores = [dict(zip(revision.COLUMNAS_VALORES, combo))
                   for combo in itertools.product(
                       ("si", "no", "dudoso", ""), ("1>2", "2>1", "ninguna", ""),
                       ("+", "-", "?", ""), ("directa", "no_se", ""),
                       ("si", "no", ""), ("si", "no"), ("", "una nota"))]
        cfg = RP.datos_de(self.hoja)
        js = self.correr({"cfg": cfg, "valores": valores, "secuencias": [],
                          "items": [], "eventos": []})["validar"]
        py = []
        for v in valores:
            _limpios, errores, avisos = revision.validar(v)
            py.append([bool(errores), len(avisos)])
        self.assertEqual(len(js), len(py))
        distintos = [v for v, a, b in zip(valores, js, py) if a != b]
        self.assertEqual(distintos, [])

    def test_mide_y_exporta_igual_que_revision(self):
        cfg = RP.datos_de(self.hoja)
        eventos = _eventos_de_prueba()
        # Y el borde: exactamente 15 minutos todavía se suma.
        borde = [{"evento": "inicio", "id_item": "m-3456",
                  "hora": "2026-10-24T14:00:00.000Z"},
                 {"evento": "guardado", "id_item": "m-3456",
                  "hora": "2026-10-24T14:15:00.000Z", "valores": dict(VALIDOS)}]
        secuencias = [eventos, eventos[:3], [eventos[4], eventos[5]], borde]
        salida = self.correr({"cfg": cfg, "valores": [], "secuencias": secuencias,
                              "items": cfg["items"], "eventos": eventos})
        for js, seq in zip(salida["vigentes"], secuencias):
            py = revision.anotaciones_de_eventos(revision.eventos_validos(seq))
            self.assertEqual(js, py)
        ruta = os.path.join(self.tmp, "py.csv")
        revision.escribir_csv(revision.leer_items(self.hoja),
                              revision.anotaciones_de_eventos(
                                  revision.eventos_validos(eventos)), ruta)
        with io.open(ruta, encoding="utf-8", newline="") as f:
            self.assertEqual(salida["csv"], f.read())


if __name__ == "__main__":
    unittest.main()
