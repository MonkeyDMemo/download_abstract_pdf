"""Pruebas de `verificar-contaminacion`, sobre datos SINTÉTICOS.

La base del paso 0 es temporal y se arma con `grn_etl.db`; las reservas, la
llave de una muestra, las juzgadas y la partición son archivos inventados con
el formato real, y la base curada se arma con `construir_xlsx`. Los PMIDs
están por encima de los que existen (9xxxxxxx) y los DOIs son del prefijo
10.9999, que nadie tiene: nada de aquí viene de los datos del laboratorio.

GRN_DATOS y BASE_CURADA se quitan del entorno en cada prueba, y toda corrida
lleva --db o --datos: una prueba que se olvidara de darlos no puede abrir la
base de nadie.
"""

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from grn_comun import procedencia
from grn_etl import db as db0
from grn_etl import exportar
from grn_verificacion import cli
from grn_verificacion import contaminacion_nuevos as CN
from grn_verificacion import muestra, reentrenar
from grn_verificacion.test_validacion import ENCABEZADOS, construir_xlsx

CORPUS = ["91000001", "91000002", "91000003"]
NUEVOS = ["93000001", "93000002", "93000003"]
# Fuera del corpus, pero con el DOI de CORPUS[1] escrito con otras mayúsculas.
MISMO_DOI = "93000009"
# El de la lista y el reservado comparten DOI en `documentos`; el archivo de
# reservas solo trae el PMID.
CON_DOI_RESERVADO = "93000008"
RESERVADO, RESERVADO_CON_DOI = "94000001", "94000002"
EN_MUESTRA = "95000001"
JUZGADO = "96000001"
TRAIN, DEV, TEST = "97000001", "97000002", "97000003"
EN_BASE, EN_BASE_LOCUS_ROTO = "98000001", "98000002"

DOI_CORPUS = "10.9999/Sint.Corpus.2"
DOI_RESERVADO = "10.9999/sint.reservado.2"
DOI_BASE = "10.9999/sint.base.1"

TODOS_LOS_PMIDS = (CORPUS + NUEVOS + [MISMO_DOI, CON_DOI_RESERVADO, RESERVADO,
                   RESERVADO_CON_DOI, EN_MUESTRA, JUZGADO, TRAIN, DEV, TEST,
                   EN_BASE, EN_BASE_LOCUS_ROTO])
DOIS = (DOI_CORPUS, DOI_RESERVADO, DOI_BASE)

FILAS_BASE = [
    ENCABEZADOS,
    ["qzaR", "wvaA", "+", ("num", EN_BASE), "PA9001", "PA9002",
     u"Histórica", "x"],
    # Locus ilegible: `leer_base` la tira, pero el artículo está en la base.
    ["qzbR", "wvbA", "-", EN_BASE_LOCUS_ROTO + " homology", "PA90X",
     "PA9004", u"Histórica", "x"],
    ["qzcR", "wvcA", "+", "doi:" + DOI_BASE, "PA9005", "PA9006",
     u"Histórica", "x"],
]


def escribir(ruta, texto, bom=False):
    carpeta = os.path.dirname(ruta)
    if carpeta and not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    with io.open(ruta, "w", encoding="utf-8-sig" if bom else "utf-8",
                 newline="") as f:
        f.write(texto)
    return ruta


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contaminacion_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        entorno = mock.patch.dict(os.environ)
        entorno.start()
        self.addCleanup(entorno.stop)
        os.environ.pop("GRN_DATOS", None)
        os.environ.pop("BASE_CURADA", None)

        self.db = os.path.join(self.tmp, "datos", "grn.db")
        con = db0.conectar(self.db)
        try:
            docs = [{"pmid": p, "doi": "10.9999/sint.%s" % p}
                    for p in CORPUS + NUEVOS]
            docs[1]["doi"] = DOI_CORPUS
            docs += [{"pmid": MISMO_DOI, "doi": DOI_CORPUS.lower()},
                     {"pmid": CON_DOI_RESERVADO, "doi": DOI_RESERVADO},
                     {"pmid": RESERVADO_CON_DOI,
                      "doi": "https://doi.org/" + DOI_RESERVADO}]
            db0.guardar_documentos(con, docs)
            vieja, _ = db0.alta_consulta(con, "vieja", "query vieja")
            db0.vincular(con, vieja, CORPUS)
            db0.crear_corpus(con, CN.CORPUS_POR_OMISION, consulta_id=vieja)
            nuevos, _ = db0.alta_consulta(con, "nuevos", "query nueva")
            db0.vincular(con, nuevos, NUEVOS)
            mezcla, _ = db0.alta_consulta(con, "nuevos_y_uno_viejo", "otra")
            db0.vincular(con, mezcla, NUEVOS + CORPUS[:1])
        finally:
            con.close()

        self.reservas = escribir(
            os.path.join(self.tmp, "reservas.tsv"),
            "# Reservas inventadas\npmid\t%s\npmid\t%s\n"
            "oracion\tQzaR activa a wvaA en una oración inventada.\n"
            % (RESERVADO, RESERVADO_CON_DOI))
        self.muestra = os.path.join(self.tmp, "sorteo")
        fila = dict((c, "") for c in muestra.COLUMNAS_LLAVE)
        fila.update({"id_item": "m-1000", "pmid": EN_MUESTRA,
                     "fuente_texto": "abstract", "num_oracion": "1"})
        llave = io.StringIO()
        w = csv.DictWriter(llave, fieldnames=muestra.COLUMNAS_LLAVE,
                           lineterminator="\n")
        w.writeheader()
        w.writerow(fila)
        escribir(os.path.join(self.muestra, muestra.LLAVE), llave.getvalue(),
                 bom=True)
        self.juzgadas = escribir(
            os.path.join(self.tmp, "juzgadas.csv"),
            "pmid,oracion,juicio\n%s,Una oración inventada.,si\n" % JUZGADO)
        self.particion = os.path.join(self.tmp, "particion_x")
        for parte, pmid in zip(CN.PARTES, (TRAIN, DEV, TEST)):
            ejemplo = {"text": "<e1>QzaR</e1> activa a <e2>wvaA</e2>.",
                       "label": "activates", "pmid": int(pmid)}
            escribir(os.path.join(self.particion, CN.ARCHIVO_PARTE % parte),
                     json.dumps(ejemplo) + "\n")
        self.base = os.path.join(self.tmp, "base.xlsx")
        construir_xlsx(self.base, [("Hoja1", FILAS_BASE)])

    def lista(self, pmids, nombre="lista.txt"):
        return escribir(os.path.join(self.tmp, nombre),
                        "".join("%s\n" % p for p in pmids))

    def todas(self, lista):
        """Los argumentos con todas las fuentes y la base del paso 0."""
        return ["verificar-contaminacion", "--lista", lista,
                "--db", self.db, "--reservas", self.reservas,
                "--muestra", self.muestra, "--juzgadas", self.juzgadas,
                "--particion", self.particion, "--base", self.base]

    def correr(self, argv):
        lineas = []
        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main(argv)
        return codigo, lineas

    def correr_json(self, argv):
        ruta = os.path.join(self.tmp, "resultado.json")
        if os.path.exists(ruta):
            os.remove(ruta)
        codigo, lineas = self.correr(argv + ["--json", ruta])
        with io.open(ruta, encoding="utf-8") as f:
            texto = f.read()
        return codigo, lineas, texto, json.loads(texto)

    def assertSinContenido(self, texto):
        """Ni PMIDs, ni DOIs, ni rutas: solo conteos, nombres y huellas."""
        for pmid in TODOS_LOS_PMIDS:
            self.assertNotIn(pmid, texto)
        for doi in DOIS:
            self.assertNotIn(doi.lower(), texto.lower())
        self.assertNotIn(self.tmp, texto)
        self.assertNotIn(os.path.basename(self.tmp), texto)
        reentrenar.verificar_publicable(texto)


def por_fuente(resultado, llave="cruces_pmid"):
    return dict((f["fuente"], f.get(llave)) for f in resultado["fuentes"])


class PruebasCruces(Base):

    def test_sin_cruces_sale_0_y_solo_dice_conteos(self):
        codigo, lineas, texto, r = self.correr_json(
            self.todas(self.lista(NUEVOS)))

        self.assertEqual(codigo, 0)
        self.assertEqual(r["codigo"], 0)
        self.assertEqual(r["fuentes_con_cruces"], [])
        self.assertTrue(all(f["revisada"] for f in r["fuentes"]))
        self.assertEqual(por_fuente(r), dict.fromkeys(CN.FUENTES, 0))
        self.assertEqual(por_fuente(r, "cruces_doi"),
                         dict.fromkeys(CN.FUENTES, 0))
        self.assertEqual(por_fuente(r, "pmids"), {
            "corpus": 3, "reservas": 2, "muestra": 1, "juzgadas": 1,
            "particion": 3, "base": 2})
        self.assertEqual(r["lista"]["pmids"], 3)
        self.assertEqual(r["lista"]["con_doi"], 3)
        dicho = "\n".join(lineas)
        self.assertIn("Ningún cruce en 6 fuentes revisadas.", dicho)
        self.assertIn("corpus v0-agosto: 3 PMIDs y 3 DOIs", dicho)
        self.assertSinContenido(dicho)
        self.assertSinContenido(texto)

    def test_un_cruce_en_cada_fuente_sale_1(self):
        casos = [("corpus", CORPUS[0]), ("reservas", RESERVADO),
                 ("muestra", EN_MUESTRA), ("juzgadas", JUZGADO),
                 ("particion", TRAIN), ("particion", DEV),
                 ("particion", TEST), ("base", EN_BASE),
                 ("base", EN_BASE_LOCUS_ROTO)]
        for fuente, pmid in casos:
            with self.subTest(fuente=fuente, pmid=pmid):
                ruta = self.lista(NUEVOS + [pmid], "lista_%s.txt" % pmid)
                codigo, lineas, texto, r = self.correr_json(self.todas(ruta))

                self.assertEqual(codigo, 1)
                self.assertEqual(r["fuentes_con_cruces"], [fuente])
                esperado = dict.fromkeys(CN.FUENTES, 0)
                esperado[fuente] = 1
                self.assertEqual(por_fuente(r), esperado)
                dicho = "\n".join(lineas)
                self.assertIn("Con cruces en 1 de 6 fuentes revisadas", dicho)
                self.assertSinContenido(dicho)
                self.assertSinContenido(texto)

    def test_el_doi_cruza_aunque_el_pmid_no(self):
        """El mismo DOI, con otras mayúsculas, bajo otro PMID: por PMID da
        cero, y sin el cruce por DOI la lista pasaría por nueva."""
        codigo, lineas, texto, r = self.correr_json(
            self.todas(self.lista(NUEVOS + [MISMO_DOI])))

        self.assertEqual(codigo, 1)
        corpus = r["fuentes"][CN.FUENTES.index("corpus")]
        self.assertEqual((corpus["cruces_pmid"], corpus["cruces_doi"],
                          corpus["solo_doi"]), (0, 1, 1))
        self.assertIn("0 por PMID, 1 por DOI (1 solo por DOI)",
                      "\n".join(lineas))
        self.assertSinContenido(texto)

    def test_el_doi_de_documentos_cruza_una_fuente_que_solo_trae_pmids(self):
        """Las reservas solo traen el PMID; su DOI sale de `documentos`, como
        el de la lista."""
        codigo, _, _, r = self.correr_json(
            self.todas(self.lista(NUEVOS + [CON_DOI_RESERVADO])))

        self.assertEqual(codigo, 1)
        reservas = r["fuentes"][CN.FUENTES.index("reservas")]
        self.assertEqual((reservas["cruces_pmid"], reservas["cruces_doi"],
                          reservas["solo_doi"]), (0, 1, 1))

    def test_sin_base_del_paso_0_cruzan_los_dois_que_traen_las_fuentes(self):
        """En el servidor no está la base del paso 0: la columna doi de la
        lista y el DOI escrito en la base curada bastan para cruzar."""
        vacia = os.path.join(self.tmp, "sin_datos")
        os.makedirs(vacia)
        ruta = escribir(os.path.join(self.tmp, "lista.csv"),
                        "pmid,doi\n%s,https://doi.org/%s.\n%s,\n"
                        % (NUEVOS[0], DOI_BASE.upper(), NUEVOS[1]))

        codigo, lineas, texto, r = self.correr_json([
            "verificar-contaminacion", "--lista", ruta, "--sin-corpus",
            "--datos", vacia, "--juzgadas", self.juzgadas,
            "--base", self.base])

        self.assertEqual(codigo, 1)
        self.assertFalse(r["base_paso0"]["abierta"])
        self.assertEqual(r["lista"]["con_doi"], 1)
        base = r["fuentes"][CN.FUENTES.index("base")]
        self.assertEqual((base["cruces_pmid"], base["cruces_doi"]), (0, 1))
        dicho = "\n".join(lineas)
        self.assertIn("Base del paso 0: no está (por --datos)", dicho)
        self.assertIn("corpus: no se pidió (--sin-corpus).", dicho)
        self.assertSinContenido(dicho)
        self.assertSinContenido(texto)

    def test_la_consulta_toma_la_lista_de_la_base_del_paso_0(self):
        argumentos = ["verificar-contaminacion", "--db", self.db,
                      "--juzgadas", self.juzgadas]

        codigo, lineas, _, r = self.correr_json(
            argumentos + ["--consulta", "nuevos"])
        self.assertEqual(codigo, 0)
        self.assertEqual(r["lista"]["origen"], "consulta")
        self.assertEqual(r["lista"]["pmids"], 3)
        self.assertEqual(r["lista"]["huella"], db0.huella_pmids(NUEVOS))
        self.assertIsNone(r["lista"]["huella_archivo"])
        self.assertIn("de la consulta «nuevos»", lineas[0])

        codigo, _, _, r = self.correr_json(
            argumentos + ["--consulta", "nuevos_y_uno_viejo"])
        self.assertEqual(codigo, 1)
        self.assertEqual(r["fuentes_con_cruces"], ["corpus"])

    def test_la_huella_de_una_lista_igual_al_corpus_es_la_del_corpus(self):
        ruta = self.lista([CORPUS[2], CORPUS[0], CORPUS[1], CORPUS[0]])

        codigo, lineas, _, r = self.correr_json(self.todas(ruta))

        self.assertEqual(codigo, 1)
        con = db0.conectar(self.db)
        try:
            huella = db0.obtener_corpus(con, CN.CORPUS_POR_OMISION)[
                "hash_pmids"]
        finally:
            con.close()
        self.assertEqual(r["lista"]["huella"], huella)
        self.assertEqual(r["lista"]["huella_archivo"],
                         procedencia.huella(ruta))
        self.assertIn(huella, lineas[0])
        self.assertIn(procedencia.huella(ruta), lineas[0])

    def test_lo_que_no_se_pidio_y_la_calibracion_se_dicen(self):
        codigo, lineas, _, r = self.correr_json([
            "verificar-contaminacion", "--lista", self.lista(NUEVOS),
            "--db", self.db, "--juzgadas", self.juzgadas])

        self.assertEqual(codigo, 0)
        dicho = "\n".join(lineas)
        for clave in ("reservas", "muestra", "particion"):
            self.assertIn("no se pidió (--%s)" % clave, dicho)
        self.assertIn("base curada: no se pidió (--base", dicho)
        self.assertIn("calibración: no aplica", dicho)
        self.assertIn("no tienen PMIDs", r["calibracion"])
        self.assertIn("Ningún cruce en 2 fuentes revisadas.", dicho)
        revisadas = [f["fuente"] for f in r["fuentes"] if f["revisada"]]
        self.assertEqual(revisadas, ["corpus", "juzgadas"])

    def test_la_base_del_paso_0_se_abre_en_solo_lectura(self):
        antes = procedencia.huella(self.db)
        codigo, _ = self.correr(self.todas(self.lista(NUEVOS)))
        self.assertEqual(codigo, 0)
        self.assertEqual(procedencia.huella(self.db), antes)

        falta = os.path.join(self.tmp, "otra", "grn.db")
        codigo, lineas = self.correr([
            "verificar-contaminacion", "--lista", self.lista(NUEVOS),
            "--db", falta, "--juzgadas", self.juzgadas])
        self.assertEqual(codigo, 2)
        self.assertFalse(os.path.exists(falta), "se creó una base vacía")
        self.assertFalse(os.path.exists(os.path.dirname(falta)))

    def test_ejecutar_devuelve_lo_mismo_que_reporta(self):
        lineas = []
        r = CN.ejecutar(lista=self.lista(NUEVOS + [JUZGADO]),
                        ruta_db=self.db, juzgadas=self.juzgadas,
                        reservas=self.reservas, log=lineas.append)

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(r["fuentes_con_cruces"], ["juzgadas"])
        self.assertEqual(lineas, CN.resumen(r))


class PruebasErrores(Base):
    """Lo que impide verificar sale con 2, con un mensaje sin rutas, y sin
    escribir ni un conteo: un resultado a medias se leería como completo."""

    def assertNoVerificable(self, argv, *fragmentos):
        json_ = os.path.join(self.tmp, "no_debe.json")
        codigo, lineas = self.correr(argv + ["--json", json_])
        self.assertEqual(codigo, 2)
        self.assertEqual(len(lineas), 1, lineas)
        self.assertTrue(lineas[0].startswith("ERROR: "))
        for fragmento in fragmentos:
            self.assertIn(fragmento, lineas[0])
        self.assertNotIn(self.tmp, lineas[0])
        self.assertFalse(os.path.exists(json_))
        return lineas[0]

    def test_sin_el_archivo_de_la_lista(self):
        self.assertNoVerificable(
            self.todas(os.path.join(self.tmp, "no_esta.txt")), "--lista")

    def test_un_pmid_mal_escrito_dice_la_linea_y_no_el_valor(self):
        ruta = escribir(os.path.join(self.tmp, "mala.txt"),
                        "%s\nPMC7654321\n" % NUEVOS[0])
        mensaje = self.assertNoVerificable(self.todas(ruta), "línea 2")
        self.assertNotIn("PMC7654321", mensaje)

    def test_una_lista_vacia(self):
        ruta = escribir(os.path.join(self.tmp, "vacia.txt"), "# nada\n\n")
        self.assertNoVerificable(self.todas(ruta), "ningún PMID")

    def test_un_corpus_o_una_consulta_que_no_existen(self):
        self.assertNoVerificable(
            self.todas(self.lista(NUEVOS)) + ["--corpus", "no-hay"],
            "corpus «no-hay»")
        self.assertNoVerificable(
            ["verificar-contaminacion", "--consulta", "no_hay", "--db",
             self.db, "--juzgadas", self.juzgadas], "consulta «no_hay»")

    def test_sin_base_del_paso_0_hace_falta_sin_corpus(self):
        vacia = os.path.join(self.tmp, "sin_datos")
        os.makedirs(vacia)
        self.assertNoVerificable(
            ["verificar-contaminacion", "--lista", self.lista(NUEVOS),
             "--datos", vacia, "--juzgadas", self.juzgadas],
            "--sin-corpus")

    def test_una_particion_sin_una_de_sus_partes(self):
        os.remove(os.path.join(self.particion, CN.ARCHIVO_PARTE % "dev"))
        self.assertNoVerificable(self.todas(self.lista(NUEVOS)),
                                 "entity_marked_dev.jsonl", "«particion_x»")

    def test_una_muestra_sin_llave(self):
        os.remove(os.path.join(self.muestra, muestra.LLAVE))
        self.assertNoVerificable(self.todas(self.lista(NUEVOS)),
                                 "llave.csv", "«sorteo»")

    def test_unas_reservas_mal_escritas(self):
        escribir(self.reservas, "pmid %s\n" % RESERVADO)
        self.assertNoVerificable(self.todas(self.lista(NUEVOS)),
                                 "--reservas", "línea 1")

    def test_una_base_curada_que_no_esta(self):
        argv = self.todas(self.lista(NUEVOS))
        argv[argv.index("--base") + 1] = os.path.join(self.tmp, "no.xlsx")
        self.assertNoVerificable(argv, "--base")

    def test_lo_que_no_pasa_el_filtro_no_se_imprime(self):
        """Un nombre de consulta con forma de PMID: lo demás son conteos."""
        con = db0.conectar(self.db)
        try:
            q, _ = db0.alta_consulta(con, "lote 12345678", "query")
            db0.vincular(con, q, NUEVOS)
        finally:
            con.close()
        self.assertNoVerificable(
            ["verificar-contaminacion", "--consulta", "lote 12345678",
             "--db", self.db, "--juzgadas", self.juzgadas],
            "filtro de publicación")

    def test_lista_y_consulta_a_la_vez_no(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            cli.main(["verificar-contaminacion", "--lista", "x",
                      "--consulta", "y"])
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            cli.main(["verificar-contaminacion", "--lista", "x",
                      "--corpus", "v1", "--sin-corpus"])


class PruebasLista(Base):

    def test_un_pmid_por_linea_con_comentarios_y_bom(self):
        ruta = escribir(os.path.join(self.tmp, "l.txt"),
                        "# nuevos\r\n\r\n%s\r\n 0%s \r\n%s\r\n"
                        % (NUEVOS[0], NUEVOS[1], NUEVOS[0]), bom=True)
        self.assertEqual(CN.leer_lista(ruta), (set(NUEVOS[:2]), {}))

    def test_csv_tsv_y_punto_y_coma_con_encabezado(self):
        casos = {"c.csv": "# nota\nPMID,DOI\n%s,10.9999/A\n%s,\n",
                 "t.tsv": "pmid\tdoi\n%s\t10.9999/A\n%s\t\n",
                 "p.csv": "pmid;doi\n%s;10.9999/A\n%s;\n"}
        for nombre, plantilla in sorted(casos.items()):
            with self.subTest(nombre):
                ruta = escribir(os.path.join(self.tmp, nombre),
                                plantilla % (NUEVOS[0], NUEVOS[1]))
                self.assertEqual(CN.leer_lista(ruta), (
                    set(NUEVOS[:2]), {NUEVOS[0]: {"10.9999/a"}}))

    def test_la_exportacion_de_una_consulta_sirve_tal_cual(self):
        con = db0.conectar(self.db)
        try:
            docs = list(exportar.documentos(con, "nuevos"))
        finally:
            con.close()
        ruta = os.path.join(self.tmp, "nuevos.csv")
        exportar.escribir_csv(docs, ruta, bom=True)

        pmids, dois = CN.leer_lista(ruta)

        self.assertEqual(pmids, set(NUEVOS))
        self.assertEqual(dois[NUEVOS[2]], {"10.9999/sint.%s" % NUEVOS[2]})

    def test_un_pmid_mal_escrito_en_el_csv_dice_su_linea(self):
        ruta = escribir(os.path.join(self.tmp, "m.csv"),
                        "pmid,doi\n%s,\nx12,\n" % NUEVOS[0])
        with self.assertRaises(ValueError) as e:
            CN.leer_lista(ruta)
        self.assertIn("línea 3", str(e.exception))
        self.assertNotIn("x12", str(e.exception))

    def test_normalizar_doi(self):
        self.assertEqual(CN.normalizar_doi(" https://doi.org/10.9999/AbC. "),
                         "10.9999/abc")
        self.assertEqual(CN.normalizar_doi("doi: 10.9999/x"), "10.9999/x")
        self.assertEqual(CN.normalizar_doi("http://dx.doi.org/10.9999/y"),
                         "10.9999/y")
        for malo in ("", None, "PMC12345", "10.99/x", "10.9999"):
            self.assertIsNone(CN.normalizar_doi(malo))


class PruebasJuzgadasPorOmision(unittest.TestCase):

    def test_existe_y_trae_la_columna_pmid(self):
        # Solo el encabezado: ni un PMID pasa por la prueba.
        with io.open(CN.JUZGADAS_POR_OMISION, encoding="utf-8-sig",
                     newline="") as f:
            encabezado = next(csv.reader(f))
        self.assertIn("pmid", encabezado)


if __name__ == "__main__":
    unittest.main()
