# -*- coding: utf-8 -*-
"""La revisión ciega: revision.py y su familia de rutas en el tablero.

Lo que más importa vigilar aquí no es que se guarde, sino lo que nunca debe
llegar a la anotadora. La carpeta de la muestra tiene, al lado de la hoja,
la llave que dice qué capa propuso cada par y en qué dirección; una
anotadora que la ve juzga al pipeline y no a la oración. Por eso la carpeta
de prueba lleva una llave, unos dobles y un resumen con una cadena señuelo,
y cada respuesta de la suite se revisa contra ese señuelo y contra las
claves que delatarían a un sistema.
"""

import csv
import io
import json
import os
import tempfile
import unittest

import revision
import servidor

from .test_servidor import BasePruebaServidor

SENUELO = "SENUELO-LLAVE-7f3a"

# Ninguna respuesta las puede traer, ni anidadas: son las de la llave y las
# de un veredicto de modelo.
CLAVES_PROHIBIDAS = {"prediccion", "probabilidad", "modelo", "sistema",
                     "direccion_bronce", "pmid", "id_par", "tanda", "doble",
                     "regulador", "blanco", "score", "signo_sugerido"}

ITEMS = [
    ("m-1234", "LasR activates rhlR transcription in PAO1.", "LasR", "rhlR"),
    # oprN cae primero dentro de mexEF-oprN (el guion no es letra): la
    # marca tiene que ir a la segunda aparición.
    ("m-2345", "The mexEF-oprN operon is repressed by MexS, and oprN drops.",
     "mexEF-oprN", "oprN"),
    # «fur» no está como palabra entera: va sin posición.
    ("m-3456", "Expression of ampC β-lactamase rose in the furA mutant.",
     "ampC", "fur"),
]

VALIDOS = {"relacion": "si", "direccion": "1>2", "signo": "+",
           "tipo": "directa", "negada": "no", "especulativa": "no",
           "comentario": ""}


def escribir_hoja(carpeta, items=ITEMS):
    with io.open(os.path.join(carpeta, revision.HOJA), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=revision.COLUMNAS_HOJA)
        w.writeheader()
        for id_item, oracion, e1, e2 in items:
            fila = dict.fromkeys(revision.COLUMNAS_HOJA, "")
            fila.update({"id_item": id_item, "oracion": oracion,
                         "entidad_1": e1, "entidad_2": e2})
            w.writerow(fila)


def claves(objeto):
    if isinstance(objeto, dict):
        for k, v in objeto.items():
            yield k
            for kk in claves(v):
                yield kk
    elif isinstance(objeto, list):
        for v in objeto:
            for kk in claves(v):
                yield kk


class BasePruebaRevision(BasePruebaServidor):

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.carpeta = tmp.name
        escribir_hoja(self.carpeta)
        # Lo que vive al lado de la hoja y la página jamás debe leer.
        with io.open(os.path.join(self.carpeta, "llave.csv"), "w",
                     encoding="utf-8-sig", newline="") as f:
            f.write("id_item,pmid,direccion_bronce\n")
            for id_item, _, _, _ in ITEMS:
                f.write("%s,%s,1>2\n" % (id_item, SENUELO))
        with io.open(os.path.join(self.carpeta, "dobles.csv"), "w",
                     encoding="utf-8") as f:
            f.write("id_item,tanda\nm-1234,%s\n" % SENUELO)
        with io.open(os.path.join(self.carpeta, "resumen.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"semilla": SENUELO}, f)
        self.ctx.revision = self.carpeta

    def pedir(self, metodo, ruta, params=None, cuerpo=None, ctx=None):
        codigo, objeto = super().pedir(metodo, ruta, params, cuerpo, ctx)
        if isinstance(objeto, servidor.Archivo):
            contenido = objeto.ruta.read_text(encoding="utf-8-sig")
            self.assertNotIn(SENUELO, contenido, ruta)
        else:
            self.assertNotIn(SENUELO, json.dumps(objeto, ensure_ascii=False),
                             ruta)
            self.assertEqual(set(claves(objeto)) & CLAVES_PROHIBIDAS, set(),
                             ruta)
        return codigo, objeto

    def guardar(self, id_item, **cambios):
        valores = dict(VALIDOS)
        valores.update(cambios)
        return self.pedir("POST", "/api/revision/item/" + id_item,
                          cuerpo=valores)

    def eventos(self):
        ruta = revision.ruta_anotaciones(self.carpeta)
        if not os.path.exists(ruta):
            return []
        with io.open(ruta, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]


class PruebasCola(BasePruebaRevision):

    def test_la_cola_trae_la_hoja_en_su_orden_y_nada_mas(self):
        r = self.ok("GET", "/api/revision/cola")
        self.assertEqual([i["id_item"] for i in r["items"]],
                         ["m-1234", "m-2345", "m-3456"])
        for item in r["items"]:
            self.assertEqual(set(item), {"id_item", "oracion", "entidad_1",
                                         "entidad_2", "posiciones",
                                         "anotado"})
            self.assertFalse(item["anotado"])
        self.assertEqual(r["avance"], {"hechos": 0, "total": 3})
        self.assertIn("β-lactamase", r["items"][2]["oracion"])

    def test_posiciones_de_palabra_entera_sin_pisarse(self):
        items = self.ok("GET", "/api/revision/cola")["items"]
        oracion = items[0]["oracion"]
        p1, p2 = items[0]["posiciones"]
        self.assertEqual(oracion[p1[0]:p1[1]], "LasR")
        self.assertEqual(oracion[p2[0]:p2[1]], "rhlR")
        oracion = items[1]["oracion"]
        p1, p2 = items[1]["posiciones"]
        self.assertEqual(oracion[p1[0]:p1[1]], "mexEF-oprN")
        self.assertEqual(oracion[p2[0]:p2[1]], "oprN")
        self.assertGreaterEqual(p2[0], p1[1], "las marcas se pisan")
        self.assertEqual(items[2]["posiciones"][1], None)

    def test_la_posicion_distingue_mayusculas(self):
        self.assertIsNone(revision.posicion("lasR is here", "LasR"))
        self.assertEqual(revision.posicion("lasRI and lasR", "lasR"),
                         [10, 14])

    def test_el_item_trae_sus_valores_guardados(self):
        r = self.ok("GET", "/api/revision/item/m-1234")
        self.assertEqual(r["item"]["entidad_1"], "LasR")
        self.assertIsNone(r["valores"])
        self.guardar("m-1234", comentario="F1")
        r = self.ok("GET", "/api/revision/item/m-1234")
        self.assertEqual(r["valores"]["comentario"], "F1")
        self.assertTrue(r["item"]["anotado"])

    def test_sin_revision_dice_como_activarla(self):
        self.ctx.revision = None
        for ruta in ("/api/revision/cola", "/api/revision/exportar",
                     "/api/revision/item/m-1234"):
            r = self.falla("GET", ruta, 404)
            self.assertIn("--revision", r["error"])

    def test_sin_hoja_es_404_con_mensaje(self):
        os.remove(revision.ruta_hoja(self.carpeta))
        r = self.falla("GET", "/api/revision/cola", 404)
        self.assertIn(revision.HOJA, r["error"])

    def test_ids_mal_formados_o_con_ruta(self):
        for id_ in ("m-12", "x-1234", "..%2F..%2Fllave.csv", "llave.csv",
                    "m-1234%00", "m-1234%0A", "m-12345678"):
            self.falla("GET", "/api/revision/item/" + id_, 400)
            self.falla("POST", "/api/revision/item/" + id_ + "/inicio", 400,
                       cuerpo={})
        self.falla("GET", "/api/revision/item/m-9999", 404)
        self.falla("GET", "/api/revision/item/../llave.csv", 404)
        self.falla("GET", "/api/revision/llave.csv", 404)
        self.assertEqual(self.eventos(), [])

    def test_errores_caben_en_cp1252(self):
        casos = [("GET", "/api/revision/item/m-12", None),
                 ("GET", "/api/revision/item/m-9999", None),
                 ("POST", "/api/revision/item/m-1234",
                  dict(VALIDOS, relacion="no")),
                 ("POST", "/api/revision/item/m-1234/inicio", None)]
        for metodo, ruta, cuerpo in casos:
            _, objeto = self.pedir(metodo, ruta, cuerpo=cuerpo)
            objeto["error"].encode("cp1252")
        self.ctx.revision = None
        _, objeto = self.pedir("GET", "/api/revision/cola")
        objeto["error"].encode("cp1252")


class PruebasAnotar(BasePruebaRevision):

    def test_inicio_exige_cuerpo_json(self):
        """Sin cuerpo, cualquier página del navegador lo manda sin
        preflight y ensucia los tiempos."""
        self.falla("POST", "/api/revision/item/m-1234/inicio", 400)
        self.assertEqual(self.eventos(), [])
        r = self.ok("POST", "/api/revision/item/m-1234/inicio", cuerpo={})
        self.assertTrue(r["inicio"])
        ev = self.eventos()
        self.assertEqual([(e["evento"], e["id_item"]) for e in ev],
                         [("inicio", "m-1234")])

    def test_guardar_valido(self):
        codigo, r = self.guardar("m-2345", relacion="dudoso",
                                 comentario="otro organismo: E. coli")
        self.assertEqual(codigo, 200, r)
        self.assertEqual(r["avisos"], [])
        self.assertEqual(r["avance"], {"hechos": 1, "total": 3})
        cola = self.ok("GET", "/api/revision/cola")
        self.assertEqual([i["anotado"] for i in cola["items"]],
                         [False, True, False])

    def test_relacion_no_lleva_ninguna_y_va_sin_signo_ni_tipo(self):
        codigo, r = self.guardar("m-1234", relacion="no", direccion="ninguna",
                                 signo="", tipo="", negada="si")
        self.assertEqual(codigo, 200, r)

    def test_valores_invalidos_no_se_guardan(self):
        malos = [
            {"relacion": "no", "direccion": "ninguna", "signo": "+",
             "tipo": ""},
            {"relacion": "no", "direccion": "1>2", "signo": "", "tipo": ""},
            {"direccion": "1->2"},
            {"direccion": "ninguna"},
            {"relacion": "quizas"},
            {"signo": "−"},
            {"tipo": "no se"},
            {"negada": ""},
            {"especulativa": "tal vez"},
            {"comentario": "x" * (revision.MAX_COMENTARIO + 1)},
            {"comentario": 5},
            {"prediccion": "si"},
        ]
        for cambio in malos:
            codigo, r = self.guardar("m-1234", **cambio)
            self.assertEqual(codigo, 400, cambio)
            self.assertTrue(r["errores"], cambio)
            r["error"].encode("cp1252")
        self.falla("POST", "/api/revision/item/m-1234", 400, cuerpo=[1])
        self.assertEqual(self.eventos(), [])

    def test_dudoso_sin_comentario_es_aviso_no_error(self):
        codigo, r = self.guardar("m-1234", relacion="dudoso")
        self.assertEqual(codigo, 200, r)
        self.assertEqual(len(r["avisos"]), 1)
        self.assertIn("dudoso", r["avisos"][0])

    def test_retomar_gana_el_ultimo_guardado_y_sobrevive_al_contexto(self):
        self.guardar("m-1234", signo="+")
        self.guardar("m-1234", signo="-", comentario="F1")
        nuevo = servidor.Contexto(self.con, self.gestor, self.cliente,
                                  self.salida, flujo_raiz=self.flujo_raiz,
                                  exportaciones=self.exportaciones,
                                  revision=self.carpeta)
        codigo, r = self.pedir("GET", "/api/revision/item/m-1234", ctx=nuevo)
        self.assertEqual(codigo, 200)
        self.assertEqual(r["valores"]["signo"], "-")
        self.assertEqual(r["valores"]["comentario"], "F1")
        codigo, cola = self.pedir("GET", "/api/revision/cola", ctx=nuevo)
        self.assertEqual(cola["avance"], {"hechos": 1, "total": 3})
        # Solo anexar: los dos guardados siguen en el archivo.
        self.assertEqual(len(self.eventos()), 2)

    def test_una_linea_cortada_no_se_come_la_siguiente(self):
        with open(revision.ruta_anotaciones(self.carpeta), "wb") as f:
            f.write(b'{"evento": "guardado", "id_item": "m-12')
        self.guardar("m-3456")
        self.assertIn("m-3456", revision.anotaciones(self.carpeta))


class PruebasTiempos(BasePruebaRevision):

    def test_inicio_es_el_primero_despues_del_guardado_anterior(self):
        c = self.carpeta
        revision.registrar_inicio(c, "m-1234", "2026-10-22T10:00:00+00:00")
        revision.registrar_inicio(c, "m-1234", "2026-10-22T10:00:30+00:00")
        revision.guardar(c, "m-1234", dict(VALIDOS),
                         "2026-10-22T10:01:00+00:00")
        revision.registrar_inicio(c, "m-1234", "2026-10-22T11:00:00+00:00")
        revision.guardar(c, "m-1234", dict(VALIDOS, signo="-"),
                         "2026-10-22T11:00:45+00:00")
        # Sin inicio: queda sin tiempos.
        revision.guardar(c, "m-2345", dict(VALIDOS),
                         "2026-10-22T12:00:00+00:00")
        v = revision.anotaciones(c)
        self.assertEqual(v["m-1234"]["inicio"], "2026-10-22T11:00:00+00:00")
        self.assertEqual(v["m-1234"]["fin"], "2026-10-22T11:00:45+00:00")
        self.assertEqual(v["m-1234"]["valores"]["signo"], "-")
        self.assertIsNone(v["m-2345"]["inicio"])

        ruta = revision.exportar_csv(c)
        with io.open(ruta, encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
        self.assertEqual(filas[0]["segundos"], "45")
        self.assertEqual(filas[1]["inicio"], "")
        self.assertEqual(filas[1]["segundos"], "")


class PruebasExportar(BasePruebaRevision):

    def test_csv_con_bom_columnas_de_la_hoja_y_tiempos(self):
        self.ok("POST", "/api/revision/item/m-2345/inicio", cuerpo={})
        self.guardar("m-2345", relacion="no", direccion="ninguna", signo="",
                     tipo="", negada="si", comentario="F6; «cepa PA14»")
        codigo, archivo = self.pedir("GET", "/api/revision/exportar")
        self.assertEqual(codigo, 200)
        self.assertIsInstance(archivo, servidor.Archivo)
        self.assertEqual(archivo.descarga_como, revision.EXPORTADA)
        self.assertTrue(archivo.tipo_mime.startswith("text/csv"))
        crudo = archivo.ruta.read_bytes()
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"), "sin BOM")
        lector = csv.DictReader(io.StringIO(crudo.decode("utf-8-sig")))
        self.assertEqual(lector.fieldnames, revision.COLUMNAS_HOJA
                         + ["inicio", "fin", "segundos"])
        filas = list(lector)
        self.assertEqual([f["id_item"] for f in filas],
                         ["m-1234", "m-2345", "m-3456"])
        hecha = filas[1]
        self.assertEqual((hecha["relacion"], hecha["direccion"],
                          hecha["signo"], hecha["negada"],
                          hecha["comentario"]),
                         ("no", "ninguna", "", "si", "F6; «cepa PA14»"))
        self.assertTrue(hecha["inicio"] and hecha["fin"])
        self.assertTrue(hecha["segundos"].isdigit())
        for c in revision.COLUMNAS_VALORES + ["inicio", "fin", "segundos"]:
            self.assertEqual(filas[0][c], "", c)
        self.assertIn("β-lactamase", filas[2]["oracion"])

    def test_lo_exportado_lo_lee_el_calculo_de_precision(self):
        """La página y la hoja CSV tienen que dar la misma entrada a
        `precision_ciega`: si el anotador cambia de una a otra a medio
        camino, las cifras no pueden depender de por dónde anotó."""
        from grn_verificacion import precision_ciega
        self.ok("POST", "/api/revision/item/m-1234/inicio", cuerpo={})
        self.guardar("m-1234")
        self.guardar("m-2345", relacion="no", direccion="ninguna", signo="",
                     tipo="", negada="si")
        _, archivo = self.pedir("GET", "/api/revision/exportar")

        leidas = precision_ciega.leer_anotacion(str(archivo.ruta))

        self.assertEqual(sorted(leidas), ["m-1234", "m-2345", "m-3456"])
        self.assertEqual(leidas["m-1234"]["relacion"], VALIDOS["relacion"])
        self.assertEqual(leidas["m-2345"]["relacion"], "no")
        self.assertEqual(leidas["m-3456"]["relacion"], "")


class PruebasContratos(unittest.TestCase):

    def test_columnas_iguales_a_las_de_muestra(self):
        """revision.py las copia para que servidor.py no arrastre
        grn_verificacion; si muestra.py cambia, esto lo dice."""
        from grn_verificacion import muestra
        self.assertEqual(revision.COLUMNAS_HOJA, muestra.COLUMNAS_HOJA)
        self.assertEqual(revision.HOJA, muestra.HOJA_TANDA1)

    def test_revision_no_nombra_lo_que_no_debe_leer(self):
        with io.open(revision.__file__, encoding="utf-8") as f:
            fuente = f.read()
        codigo = [l for l in fuente.splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        for nombre in ('"llave.csv"', '"dobles.csv"', '"resumen.json"',
                       "import grn_verificacion", "from grn_verificacion"):
            self.assertFalse(any(nombre in l for l in codigo), nombre)

    def test_la_pagina_tiene_la_pestana_revision(self):
        pagina = servidor.RUTA_PAGINA.read_text(encoding="utf-8")
        self.assertIn('data-seccion="revision"', pagina)
        self.assertIn('id="sec-revision"', pagina)
        self.assertIn('"/api/revision/cola"', pagina)
        self.assertIn("no consultes bases curadas mientras anotas", pagina)
        self.assertIn("Guardar y siguiente", pagina)


if __name__ == "__main__":
    unittest.main()
