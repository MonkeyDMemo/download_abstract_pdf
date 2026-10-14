# -*- coding: utf-8 -*-
"""La exportacion por consulta: CSV, JSONL y el paquete zip para terceros.

Lo que importa aqui es lo mismo que en las rutas del tablero que entregan
archivos: el zip trae lo que la base dice que hay, las rutas del texto
completo salen del pmid y el pmcid validados y jamas de descargas.ruta, y lo
que falta se anota en vez de tumbar el paquete.
"""

import csv
import datetime
import io
import json
import os
import sys
import tempfile
import unittest.mock
import zipfile
from pathlib import Path

import cli
from grn_etl import db, exportar

from .falsos import PruebaSinRed

SECRETO = b"SECRETO: una llave que no debe salir"


def sembrar(con, fulltext, señuelo):
    """Una consulta con tres documentos y descargas de distinta suerte.

    111: XML y PDF presentes.  222: XML registrado 'ok' pero sin archivo.
    333: pmcid con travesia y descargas.ruta apuntando al señuelo.
    444: de otra consulta, con XML presente; no debe entrar.
    """
    consulta_id, _ = db.alta_consulta(con, "pa", "lasR AND rhlR",
                                      "Regulación en P. aeruginosa")
    otra_id, _ = db.alta_consulta(con, "otra", "mexT")
    db.guardar_documentos(con, [
        {"pmid": "111", "pmcid": "PMC111", "titulo": "Uno", "abstract": "Resumen uno",
         "anio": "2020", "autores": ["Pérez A", "López B"],
         "mesh_terms": ["Pseudomonas aeruginosa"], "keywords": [],
         "tipos_publicacion": ["Journal Article"]},
        {"pmid": "222", "pmcid": "PMC222", "titulo": "Dos", "anio": "2019"},
        {"pmid": "333", "pmcid": "../../llave", "titulo": "Tres",
         "abstract": "Resumen tres", "anio": "2018"},
        {"pmid": "444", "pmcid": "PMC444", "titulo": "Ajeno", "anio": "2017"},
    ])
    db.vincular(con, consulta_id, ["111", "222", "333"])
    db.vincular(con, otra_id, ["444"])

    xml = Path(fulltext) / "xml"
    pdf = Path(fulltext) / "pdf"
    xml.mkdir(parents=True)
    pdf.mkdir(parents=True)
    (xml / "111_PMC111.xml").write_bytes(b"<article>uno</article>")
    (xml / "111_PMC111.txt").write_text("uno en texto", encoding="utf-8")
    (xml / "444_PMC444.xml").write_bytes(b"<article>ajeno</article>")
    (pdf / "111.pdf").write_bytes(b"%PDF-1.7 uno")
    Path(señuelo).write_bytes(SECRETO)

    db.registrar_descarga(con, "111", "xml", "ok", ruta=str(xml / "111_PMC111.txt"))
    db.registrar_descarga(con, "111", "pdf", "ok", ruta=str(pdf / "111.pdf"))
    db.registrar_descarga(con, "222", "xml", "ok", ruta=str(xml / "222_PMC222.txt"))
    db.registrar_descarga(con, "333", "xml", "ok", ruta=str(señuelo))
    db.registrar_descarga(con, "444", "xml", "ok", ruta=str(xml / "444_PMC444.txt"))
    db.registrar_descarga(con, "222", "pdf", "no_disponible")


class BasePruebaExportar(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.fulltext = self.tmp / "datos" / "fulltext"
        self.destino = self.tmp / "datos" / "exportaciones"
        self.señuelo = self.tmp / "llave.key"
        self.con = db.conectar(":memory:")
        self.addCleanup(self.con.close)
        sembrar(self.con, self.fulltext, self.señuelo)
        self.mensajes = []

    def log(self, msg):
        self.mensajes.append(msg)

    def empaquetar(self, **kw):
        ruta = str(self.destino / "pa_prueba.zip")
        r = exportar.empaquetar(self.con, "pa", str(self.fulltext), ruta,
                                log=self.log, **kw)
        return r, zipfile.ZipFile(ruta)


class PruebasPaquete(BasePruebaExportar):

    def test_el_zip_trae_csv_jsonl_leeme_y_el_texto_completo_de_la_consulta(self):
        r, z = self.empaquetar()

        self.assertEqual(set(z.namelist()),
                         {"documentos.csv", "documentos.jsonl", "LEEME.txt",
                          "xml/111_PMC111.xml", "texto/111_PMC111.txt"})
        self.assertEqual((r["documentos"], r["con_abstract"], r["xml"],
                          r["texto"], r["pdf"]), (3, 2, 1, 1, 0))
        self.assertEqual(r["faltantes"], ["xml 222", "xml 333"])
        self.assertEqual(r["archivo"], "pa_prueba.zip")
        self.assertGreater(r["bytes"], 0)

    def test_el_csv_lleva_bom_encabezados_con_acento_y_listas_con_barra(self):
        _, z = self.empaquetar()

        crudo = z.read("documentos.csv")
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"), "sin BOM Excel lee cp1252")
        filas = list(csv.reader(io.StringIO(crudo.decode("utf-8-sig"))))
        self.assertEqual(filas[0][:4], ["pmid", "doi", "pmcid", "título"])
        self.assertIn("año", filas[0])
        self.assertEqual(len(filas), 4)
        uno = dict(zip(filas[0], filas[1]))
        self.assertEqual(uno["autores"], "Pérez A | López B")
        self.assertEqual(uno["pmid"], "111")

    def test_el_jsonl_tiene_una_linea_por_documento_y_listas_como_listas(self):
        _, z = self.empaquetar()

        lineas = z.read("documentos.jsonl").decode("utf-8").splitlines()
        self.assertEqual(len(lineas), 3)
        docs = [json.loads(l) for l in lineas]
        self.assertEqual(docs[0]["autores"], ["Pérez A", "López B"])
        self.assertEqual([d["pmid"] for d in docs], ["111", "222", "333"])

    def test_el_pdf_solo_entra_si_se_pide(self):
        r, z = self.empaquetar(incluir_pdf=True)

        self.assertIn("pdf/111.pdf", z.namelist())
        self.assertEqual(r["pdf"], 1)
        self.assertIn("pdf/", z.read("LEEME.txt").decode("utf-8"))

    def test_las_rutas_salen_del_pmid_y_del_pmcid_nunca_de_descargas_ruta(self):
        """El 333 tiene pmcid con travesia y descargas.ruta apuntando a una
        llave fuera de la carpeta. Nada de eso debe salir en el zip."""
        _, z = self.empaquetar(incluir_pdf=True)

        for nombre in z.namelist():
            self.assertNotIn("..", nombre)
            self.assertNotIn("llave", nombre)
            self.assertNotIn(SECRETO, z.read(nombre))

    def test_lo_de_otra_consulta_no_entra(self):
        _, z = self.empaquetar()

        self.assertNotIn("xml/444_PMC444.xml", z.namelist())
        self.assertNotIn("444", z.read("documentos.csv").decode("utf-8-sig"))

    def test_un_ok_sin_archivo_se_anota_en_el_leeme_y_no_tumba_el_paquete(self):
        _, z = self.empaquetar()

        leeme = z.read("LEEME.txt").decode("utf-8")
        self.assertIn("xml 222", leeme)
        self.assertIn("lasR AND rhlR", leeme, "la query va en el LEEME")
        self.assertIn("Regulación en P. aeruginosa", leeme)
        self.assertIn(exportar.DISCLAIMER_NCBI, leeme)
        self.assertIn("3 artículos, 2 con abstract, 1 con texto completo", leeme)

    def test_la_escritura_es_atomica_y_no_deja_tmp(self):
        with unittest.mock.patch.object(zipfile.ZipFile, "writestr",
                                        side_effect=RuntimeError("disco lleno")):
            with self.assertRaises(RuntimeError):
                self.empaquetar()

        self.assertEqual(os.listdir(self.destino), [])

    def test_una_consulta_inexistente_es_ValueError_sin_tocar_el_disco(self):
        with self.assertRaises(ValueError):
            exportar.empaquetar(self.con, "no_existe", str(self.fulltext),
                                str(self.destino / "x.zip"))

        self.assertFalse(self.destino.exists())


class PruebasSueltos(BasePruebaExportar):

    def test_escribir_csv_y_jsonl_son_atomicos_y_devuelven_las_filas(self):
        ruta_csv = str(self.tmp / "pa.csv")
        ruta_jsonl = str(self.tmp / "pa.jsonl")

        n1 = exportar.escribir_csv(exportar.documentos(self.con, "pa"), ruta_csv)
        n2 = exportar.escribir_jsonl(exportar.documentos(self.con, "pa"), ruta_jsonl)

        self.assertEqual((n1, n2), (3, 3))
        self.assertFalse(Path(ruta_csv + ".tmp").exists())
        crudo = Path(ruta_csv).read_bytes()
        self.assertFalse(crudo.startswith(b"\xef\xbb\xbf"),
                         "el CSV suelto sigue sin BOM, como documenta el README")
        self.assertIn("título".encode("utf-8"), crudo)
        lineas = Path(ruta_jsonl).read_bytes()
        self.assertNotIn(b"\r\n", lineas)
        self.assertEqual(lineas.count(b"\n"), 3)

    def test_solo_con_abstract_filtra(self):
        docs = list(exportar.documentos(self.con, "pa", solo_con_abstract=True))

        self.assertEqual([d["pmid"] for d in docs], ["111", "333"])


class PruebasCarpeta(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.carpeta = Path(tempfile.mkdtemp()) / "exportaciones"
        self.carpeta.mkdir()
        for nombre in ("a.zip", "b.csv", "c.jsonl", "d.tmp", "e.txt",
                       "f.zip.tmp", "LLAVE.key"):
            (self.carpeta / nombre).write_bytes(b"x")
        (self.carpeta / "sub").mkdir()
        (self.carpeta / "sub" / "g.zip").write_bytes(b"x")
        (self.carpeta.parent / "fuera.zip").write_bytes(b"x")

    def test_nombre_paquete_limpia_el_nombre_y_pone_la_fecha_utc(self):
        cuando = datetime.datetime(2026, 10, 13, 22, 30, 0,
                                   tzinfo=datetime.timezone.utc)

        nombre = exportar.nombre_paquete("Dr. edgardo/solicitud v1", cuando)

        self.assertEqual(nombre, "Dr._edgardo_solicitud_v1_20261013-223000Z.zip")
        self.assertTrue(exportar.ARCHIVO_VALIDO.match(nombre))
        self.assertTrue(exportar.nombre_paquete("", cuando).startswith("consulta_"))

    def test_listar_solo_da_lo_que_cumple_el_patron_y_es_hijo_directo(self):
        nombres = [a["nombre"] for a in exportar.listar_exportaciones(str(self.carpeta))]

        self.assertEqual(sorted(nombres), ["a.zip", "b.csv", "c.jsonl"])
        for a in exportar.listar_exportaciones(str(self.carpeta)):
            self.assertEqual(a["bytes"], 1)
            self.assertIn("T", a["modificado"])

    def test_una_carpeta_inexistente_es_una_lista_vacia(self):
        self.assertEqual(exportar.listar_exportaciones(str(self.carpeta / "no")), [])

    def test_ruta_exportacion_rechaza_travesias_y_lo_no_listado(self):
        carpeta = str(self.carpeta)

        self.assertEqual(exportar.ruta_exportacion(carpeta, "a.zip"),
                         os.path.join(carpeta, "a.zip"))
        for malo in ("../fuera.zip", "..\\fuera.zip", "sub/g.zip", "d.tmp",
                     "f.zip.tmp", "LLAVE.key", "z.zip", "", None, "a.ZIP",
                     "..zip", "a.zip/"):
            self.assertIsNone(exportar.ruta_exportacion(carpeta, malo), malo)

    def test_tipo_mime_por_extension(self):
        self.assertEqual(exportar.tipo_mime("a.zip"), "application/zip")
        self.assertTrue(exportar.tipo_mime("b.csv").startswith("text/csv"))


class PruebasCli(PruebaSinRed):
    """`cli.py export` con base en una carpeta de datos temporal."""

    def setUp(self):
        super().setUp()
        self.datos = Path(tempfile.mkdtemp())
        con = db.conectar(str(self.datos / "grn.db"))
        sembrar(con, self.datos / "fulltext", self.datos.parent / "llave.key")
        con.close()

    def correr(self, argv):
        mensajes = []
        with unittest.mock.patch.object(sys, "argv", ["cli.py"] + argv), \
                unittest.mock.patch.object(cli, "log", mensajes.append):
            cli.main()
        return mensajes

    def test_export_zip_cae_en_datos_exportaciones(self):
        self.correr(["--datos", str(self.datos), "export", "pa", "--formato", "zip"])

        paquetes = os.listdir(self.datos / "exportaciones")
        self.assertEqual(len(paquetes), 1)
        self.assertTrue(paquetes[0].startswith("pa_") and paquetes[0].endswith("Z.zip"))
        with zipfile.ZipFile(self.datos / "exportaciones" / paquetes[0]) as z:
            self.assertIn("xml/111_PMC111.xml", z.namelist())
            self.assertNotIn("pdf/111.pdf", z.namelist())

    def test_export_zip_con_pdf_y_salida_explicita(self):
        ruta = self.datos / "paquete.zip"

        self.correr(["--datos", str(self.datos), "export", "pa", "--formato",
                     "zip", "--con-pdf", "--salida", str(ruta)])

        with zipfile.ZipFile(ruta) as z:
            self.assertIn("pdf/111.pdf", z.namelist())

    def test_export_csv_escribe_donde_se_le_dice_y_sin_bom(self):
        ruta = self.datos / "pa.csv"

        mensajes = self.correr(["--datos", str(self.datos), "export", "pa",
                                "--salida", str(ruta)])

        crudo = ruta.read_bytes()
        self.assertFalse(crudo.startswith(b"\xef\xbb\xbf"))
        self.assertIn("título".encode("utf-8"), crudo)
        self.assertTrue(any("3 documentos" in m for m in mensajes))

    def test_export_de_consulta_inexistente_sale_con_mensaje(self):
        with self.assertRaises(SystemExit) as ctx:
            self.correr(["--datos", str(self.datos), "export", "nadie",
                         "--formato", "zip"])

        self.assertIn("nadie", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
