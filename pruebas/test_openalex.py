# -*- coding: utf-8 -*-
"""Las copias de OpenAlex: qué PDF es el artículo y a quién llega la llave."""
import email.message
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from grn_etl import db, openalex

TITULO = "LasR regulates rhlR expression in Pseudomonas aeruginosa biofilms"
RELLENO = "Quorum sensing controls virulence. " * 300


class PruebasEsElArticulo(unittest.TestCase):

    def test_con_el_titulo_en_la_primera_pagina(self):
        self.assertTrue(openalex.es_el_articulo(TITULO, TITULO + ". " + RELLENO))

    def test_un_texto_corto_no_es_un_articulo(self):
        self.assertFalse(openalex.es_el_articulo(TITULO, TITULO))

    def test_otro_trabajo_no_es_el_articulo(self):
        self.assertFalse(openalex.es_el_articulo(TITULO, RELLENO))

    def test_el_titulo_puede_estar_despues_de_la_caratula(self):
        caratula = "Accepted manuscript. " * 400
        self.assertGreater(len(caratula), openalex.CABECERA)
        self.assertTrue(openalex.es_el_articulo(
            TITULO, caratula + TITULO + ". " + RELLENO))

    def test_sin_titulo_no_se_acepta(self):
        self.assertFalse(openalex.es_el_articulo("", RELLENO))


class PruebasLlave(unittest.TestCase):

    def test_la_llave_no_viaja_a_donde_redirige_el_servidor(self):
        vistos = []

        class Respuesta:
            status = 200
            headers = {}

            def read(self):
                return b"%PDF-1.7"

        def abrir(peticion, timeout=None):
            vistos.append((peticion.full_url, peticion.get_header("Authorization")))
            if len(vistos) == 1:
                cabeceras = email.message.Message()
                cabeceras["Location"] = "https://otro.example/archivo.pdf"
                error = urllib.error.HTTPError(peticion.full_url, 302, "Found",
                                               cabeceras, None)
                self.addCleanup(error.close)
                raise error
            return Respuesta()

        with mock.patch.object(openalex.ABRIDOR, "open", abrir):
            estado, _cab, cuerpo = openalex.pedir(
                "https://content.openalex.org/works/W1.pdf", "secreta")
        self.assertEqual((estado, cuerpo[:4]), (200, b"%PDF"))
        self.assertEqual(vistos[0][1], "Bearer secreta")
        self.assertEqual(vistos[1], ("https://otro.example/archivo.pdf", None))


class PruebasRegistro(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_gana_el_ultimo_estado_y_se_salta_la_linea_rota(self):
        ruta = os.path.join(self.tmp.name, "registro.jsonl")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(json.dumps({"pmid": "1", "estado": "error_500"}) + "\n")
            f.write("{a medias\n")
            f.write(json.dumps({"pmid": "1", "estado": "ok"}) + "\n")
        self.assertEqual(openalex.leer_registro(ruta), {"1": "ok"})

    def test_registrar_deja_fuera_el_pdf_que_no_es_el_articulo(self):
        raiz = self.tmp.name
        con = db.conectar(os.path.join(raiz, "grn.db"))
        self.addCleanup(con.close)
        espera = os.path.join(raiz, "espera")
        os.makedirs(os.path.join(espera, "c"))
        os.makedirs(os.path.join(espera + "_txt", "c"))
        textos = {"1": TITULO + ". " + RELLENO, "2": RELLENO}
        with open(os.path.join(espera, "c", "registro.jsonl"), "w",
                  encoding="utf-8") as f:
            for pmid in textos:
                f.write(json.dumps({"pmid": pmid, "estado": "ok", "obra": "W" + pmid,
                                    "bytes": 8, "version": "publishedVersion"}) + "\n")
            f.write(json.dumps({"pmid": "3", "estado": "sin_contenido",
                                "obra": "W3"}) + "\n")
        for pmid, texto in textos.items():
            with open(os.path.join(espera, "c", pmid + ".pdf"), "wb") as f:
                f.write(b"%PDF-1.7")
            with open(os.path.join(espera + "_txt", "c", pmid + ".txt"), "w",
                      encoding="utf-8") as f:
                f.write(texto)
        guardados = []
        with mock.patch.object(db, "obtener_documento",
                               lambda _con, _pmid: {"titulo": TITULO}), \
                mock.patch.object(db, "descargas_de", lambda _con, _pmid: []), \
                mock.patch.object(db, "registrar_descarga",
                                  lambda _con, pmid, *a, **k: guardados.append(
                                      (pmid, a, k))):
            cuenta = openalex.registrar_corpus(con, "c", espera, espera + "_txt",
                                               os.path.join(raiz, "pdf"))
        self.assertEqual(cuenta, {"registrados": 1, "descartados": 1})
        self.assertEqual([g[0] for g in guardados], ["1"])
        self.assertEqual(guardados[0][2]["fuente"], "OpenAlex")
        self.assertNotIn("secreta", json.dumps(guardados[0][2]))
        self.assertEqual(os.listdir(os.path.join(raiz, "pdf")), ["1.pdf"])


if __name__ == "__main__":
    unittest.main()
