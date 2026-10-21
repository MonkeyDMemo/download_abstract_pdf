# -*- coding: utf-8 -*-
"""Pruebas de `verificar`: una base y una carpeta del flujo, sintéticas.

Las que no pueden faltar: una carpeta coherente pasa con 0, y cada eslabón
roto da 1. Un verificador que diera 0 con la cadena rota certificaría lo que
no mira, que es peor que no tenerlo.

Todo es inventado: loci PA9xxx que PAO1 no tiene, PMIDs de cuatro cifras y
oraciones escritas para la prueba. Nada sale a la red.

    python -m unittest grn_verificacion.test_verificar
"""

import csv
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from grn_bronce import db as bdb                 # noqa: E402
from grn_bronce import exportar, identificar     # noqa: E402
from grn_comun import procedencia                # noqa: E402
from grn_etl import db as db0                    # noqa: E402
from grn_verificacion import capa, cli, evaluar, reentrenar  # noqa: E402
from grn_verificacion import verificar as V      # noqa: E402

CARPETA = "corrida1_run22"
CANDIDATAS = "bronce_identificacion_corrida1_20991231_oraciones_candidatas.csv"
RESUMEN = "bronce_identificacion_corrida1_20991231_resumen.csv"
PMIDS = ("1001", "1002", "1003", "1004")
# (oración, regulador, blanco, locus del regulador, locus del blanco)
ORACIONES = (
    ("LasR activates lasB in the wild type.", "lasR", "lasB", "PA9001",
     "PA9002"),
    ("RhlR represses rhlA when iron is low.", "rhlR", "rhlA", "PA9003",
     "PA9004"),
)
OTRA = "Cells were grown overnight in rich medium."
ESCRIPT = "<script>alert(1)</script>"
# Una predicción por par, en el orden de pares.jsonl. El segundo par es la
# autorregulación estricta (lasR consigo mismo): pasa el umbral, pero la red
# la descarta.
PREDICCIONES = (("activates", 0.9), ("activates", 0.9), ("represses", 0.8),
                ("activates", 0.9), ("represses", 0.75), ("no_relation", 0.9),
                ("represses", 0.6), ("regulates", 0.65), ("activates", 0.7))
ETIQUETAS = ("activates", "no_relation", "regulates", "represses")


def _escribir_json(ruta, objeto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)


def _leer_json(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _cadenas(objeto):
    """Todas las cadenas de un JSON leído, llaves incluidas."""
    if isinstance(objeto, dict):
        return [c for k, v in objeto.items() for c in [k] + _cadenas(v)]
    if isinstance(objeto, list):
        return [c for v in objeto for c in _cadenas(v)]
    return [objeto] if isinstance(objeto, str) else []


def _escribir_jsonl(ruta, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def _escribir_csv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(columnas)
        for fila in filas:
            w.writerow([fila.get(c, "") for c in columnas])


def armar_base(ruta, sellar_recursos=True):
    """4 documentos, un corpus y la corrida 1 del bronce: 12 oraciones, 8
    candidatas y 16 menciones de gen, todas con locus."""
    con = bdb.conectar(ruta)
    db0.guardar_documentos(con, [
        {"pmid": p, "titulo": "Un artículo inventado", "abstract": "x",
         "anio": "2020"} for p in PMIDS])
    corpus_id, _ = db0.crear_corpus(con, "prueba-v1", pmids=list(PMIDS))
    parametros = {"corpus": "prueba-v1"}
    if sellar_recursos:
        parametros["recursos"] = identificar.huellas_de_recursos()
    corrida = bdb.abrir_corrida(con, "1", identificar.METODO,
                                identificar.VERSION, parametros, corpus_id)
    for pmid in PMIDS:
        for num, (texto, tf, blanco, l1, l2) in enumerate(ORACIONES):
            unidad = _unidad(con, corrida, pmid, num, texto)
            ids = bdb.guardar_menciones(con, corrida, "lexico", unidad, [
                {"tipo": "gen", "texto": tf, "id_normalizado": l1,
                 "offset_ini": 0, "offset_fin": 4},
                {"tipo": "gen", "texto": blanco, "id_normalizado": l2,
                 "offset_ini": 14, "offset_fin": 18},
                {"tipo": "disparador", "texto": "activates",
                 "id_normalizado": "", "offset_ini": 5, "offset_fin": 13}])
            bdb.guardar_candidata(con, corrida, "lexico", unidad, {
                "disparador": "activates", "signo_sugerido": "+",
                "regulador_candidato": tf, "blanco_candidato": blanco,
                "score": 1.0}, ids)
        _unidad(con, corrida, pmid, 2, OTRA)
    bdb.cerrar_corrida(con, corrida, "ok", None, len(PMIDS), 8)
    con.close()
    return corrida


def _unidad(con, corrida, pmid, num, texto):
    return bdb.guardar_unidad(con, corrida, {
        "pmid": pmid, "fuente_texto": "abstract", "seccion": "abstract",
        "num_oracion": num, "texto": texto, "offset_ini": 0,
        "offset_fin": len(texto), "contiguo": True})


def _pares():
    """Un par por candidata, más la autorregulación de la primera."""
    pares = []
    for pmid in PMIDS:
        for num, (texto, tf, blanco, _l1, _l2) in enumerate(ORACIONES):
            if pmid == PMIDS[0] and num == 0:
                texto = texto + " " + ESCRIPT
            pares.append((pmid, num, texto, tf, blanco))
            if pmid == PMIDS[0] and num == 0:
                pares.append((pmid, num, texto, tf, tf))
    salida = []
    for i, ((pmid, num, texto, tf, blanco), (clase, p)) in enumerate(
            zip(pares, PREDICCIONES), 1):
        salida.append({"id_par": "p%d" % i, "pmid": pmid, "num": num,
                       "texto": texto, "tf": tf, "blanco": blanco,
                       "clase": clase, "p": p, "auto": tf == blanco})
    return salida


class Carpeta(object):
    """Una carpeta del flujo coherente con `armar_base`.

    `escribir(**cambios)` la escribe entera; cada cambio es una función que
    recibe el objeto de ese archivo antes de escribirlo y lo modifica. Las
    huellas se calculan después, así que lo que no se cambió sigue
    cuadrando: solo se rompe el eslabón que la prueba quiere romper.
    """

    def __init__(self, raiz):
        self.raiz = raiz
        self.ruta = os.path.join(raiz, "salidas", "flujo", CARPETA)
        os.makedirs(self.ruta)

    def de(self, nombre):
        return os.path.join(self.ruta, nombre)

    def escribir(self, **cambios):
        def cambiar(clave, objeto):
            if clave in cambios:
                cambios[clave](objeto)
            return objeto

        pares = _pares()
        candidatas = []
        for pmid in PMIDS:
            for num, (texto, tf, blanco, _l1, _l2) in enumerate(ORACIONES):
                if pmid == PMIDS[0] and num == 0:
                    texto = texto + " " + ESCRIPT
                candidatas.append({
                    "pmid": pmid, "fuente_texto": "abstract",
                    "seccion": "abstract", "num_oracion": num,
                    "oracion": texto, "regulador_candidato": tf,
                    "blanco_candidato": blanco, "corrida_id": 1,
                    "metodo": identificar.METODO,
                    "version": identificar.VERSION})
        _escribir_csv(self.de(CANDIDATAS), exportar.COLUMNAS_CANDIDATAS,
                      cambiar("candidatas", candidatas))
        resumen = [["concepto", "valor"], ["Corpus", "prueba-v1"],
                   ["Documentos procesados", 4],
                   ["Oraciones totales (todas, se guardan aunque no sean "
                    "candidatas)", 12],
                   ["Oraciones candidatas", 8], ["Menciones totales", 24]]
        with io.open(self.de(RESUMEN), "w", encoding="utf-8-sig",
                     newline="") as f:
            csv.writer(f).writerows(cambiar("resumen", resumen))

        _escribir_jsonl(self.de(V.PARES), cambiar("pares", [
            {"id_par": p["id_par"], "pmid": p["pmid"],
             "text": "<e1>%s</e1> y <e2>%s</e2>" % (p["tf"], p["blanco"]),
             "tf": p["tf"], "target": p["blanco"], "tf_id": p["tf"],
             "target_id": p["blanco"], "corrida_bronce": 1,
             "autorregulacion": p["auto"], "oracion_cruda": p["texto"],
             "fuente_texto": "abstract", "num_oracion": p["num"],
             "seccion": "abstract", "tf_locus": ["PA9001"],
             "target_locus": ["PA9002"]} for p in pares]))
        _escribir_jsonl(self.de(V.SINTAXIS), cambiar("sintaxis", [
            {"pmid": p["pmid"], "fuente_texto": "abstract",
             "num_oracion": p["num"], "a": p["tf"], "b": p["blanco"],
             "regulador_sintactico": p["tf"]} for p in pares
            if not p["auto"]]))
        predicciones = []
        for p in pares:
            fila = {"id_par": p["id_par"], "pmid": int(p["pmid"]),
                    "prediccion": p["clase"], "seccion": "abstract",
                    "autorregulacion": p["auto"]}
            for e in ETIQUETAS:
                fila["p_" + e] = p["p"] if e == p["clase"] else \
                    round((1 - p["p"]) / 3, 6)
            predicciones.append(fila)
        _escribir_jsonl(self.de(V.PREDICCIONES),
                        cambiar("predicciones", predicciones))
        h = procedencia.huella
        _escribir_json(self.de(V.PARES_INFORME), cambiar("pares_informe", {
            "oraciones_leidas": 8, "oraciones_con_par": 8, "pares": 9,
            "autorregulacion": 1,
            "descartes_de_extraer_pares": {
                "pares_autorregulacion_antes_del_tope": 1},
            "huellas": {"candidatas": h(self.de(CANDIDATAS)),
                        "pares": h(self.de(V.PARES))},
            "limite": None}))
        # Con rutas absolutas, como las escriben puente.py y red.py: el
        # informe no puede repetirlas.
        _escribir_json(self.de(V.PREDICCIONES_META), cambiar("meta", {
            "modelo": os.path.join(self.raiz, "modelo_limpio_run22"),
            "n_entrada": 9, "n_salida": 9,
            "huella_pares": h(self.de(V.PARES)),
            "huella_predicciones": h(self.de(V.PREDICCIONES))}))
        with io.open(self.de(V.RED), "w", encoding="utf-8",
                     newline="\n") as f:
            f.write("tf\tblanco\tsigno\nlasR\tlasB\tactivates\n")
        sello = procedencia.sellar({"pares": self.de(V.PARES),
                                    "predicciones": self.de(V.PREDICCIONES)})
        sello["red"] = procedencia.sellar_como(self.de(V.RED), self.de(V.RED))
        _escribir_json(self.de(V.RED_INFORME), cambiar("red_informe", {
            "predicciones": self.de(V.PREDICCIONES),
            "pares": self.de(V.PARES),
            "umbrales": dict(capa.UMBRALES), "sin_pies": "false",
            "sin_introduccion": "false",
            "incluir_autorregulacion": "false", "n_predicciones": 9,
            "n_supervivientes": 6, "n_aristas": 4, "huellas": sello}))
        filas_capa = []
        for p in pares:
            pasa = p["clase"] != "no_relation" and \
                p["p"] >= capa.UMBRALES[p["clase"]]
            filas_capa.append({
                "corrida_bronce": 1, "pmid": p["pmid"],
                "fuente_texto": "abstract", "seccion": "abstract",
                "num_oracion": p["num"], "id_par": p["id_par"],
                "oracion": p["texto"], "tf_id": p["tf"],
                "target_id": p["blanco"],
                "autorregulacion": "si" if p["auto"] else "no",
                "prediccion": p["clase"],
                "pasa_umbral": "si" if pasa else "no",
                "direccion_sintaxis": "sin_dato" if p["auto"]
                else "concuerda"})
        _escribir_csv(self.de(V.CAPA), capa.COLUMNAS_CAPA,
                      cambiar("capa", filas_capa))
        _escribir_json(self.de(V.CAPA_RESUMEN), cambiar("capa_resumen", {
            "filas": 9, "oraciones": 8, "articulos": 4, "pasan_umbral": 7,
            "umbrales": dict(capa.UMBRALES),
            "sintaxis": {"presente": True,
                         "direccion": {"concuerda": 8, "sin_dato": 1},
                         "huella_sintaxis": h(self.de(V.SINTAXIS))}}))
        _escribir_json(self.de(V.EVALUACION), cambiar("evaluacion", {
            "muestra": {"n": 50, "si": 22, "no": 24, "dudoso": 4,
                        "unidas": 50},
            "P0_bronce": evaluar.proporcion(22, 50),
            "P1_bronce_y_biobert_con_umbral": evaluar.proporcion(16, 37),
            "S1_signo": {"biobert": {"acierto": evaluar.proporcion(11, 11),
                                     "cubiertas": 11}},
            "notas": ["Una nota con %s dentro." % ESCRIPT]}))
        self._escribir_estado(cambiar)

    def _escribir_estado(self, cambiar):
        def rel(nombre):
            return "salidas/flujo/%s/%s" % (CARPETA, nombre)

        def sellos(*nombres):
            return dict((rel(n), procedencia.huella(self.de(n)))
                        for n in nombres)
        # Una entrada de fuera de la carpeta, medida como la mide el flujo:
        # un recurso de texto del repositorio, sin CRLF.
        codigo = {"grn_verificacion/capa.py": procedencia.huella_texto(
            os.path.join(_RAIZ, "grn_verificacion", "capa.py"))}
        hecho = {"estatus": "ok", "nombre": "x"}
        pasos = {
            "operones": {"estatus": "omitido", "nombre": "Operones",
                         "nota": "falta operones_base.tsv %s" % ESCRIPT},
            "bronce": dict(hecho, entradas=dict(codigo),
                           salidas=sellos(CANDIDATAS)),
            "pares": dict(hecho, entradas=sellos(CANDIDATAS),
                          salidas=sellos(V.PARES, V.PARES_INFORME)),
            "biobert": dict(hecho, estatus="saltado",
                            entradas=sellos(V.PARES),
                            salidas=sellos(V.PREDICCIONES,
                                           V.PREDICCIONES_META)),
            "red": dict(hecho, entradas=sellos(V.PREDICCIONES,
                                               V.PREDICCIONES_META, V.PARES),
                        salidas=sellos(V.RED, V.RED_INFORME)),
            "sintaxis": dict(hecho, entradas=sellos(CANDIDATAS),
                             salidas=sellos(V.SINTAXIS)),
            "capa": dict(hecho, entradas=sellos(CANDIDATAS, V.PARES,
                                                V.PREDICCIONES, V.SINTAXIS),
                         salidas=sellos(V.CAPA, V.CAPA_RESUMEN)),
            "evaluar": dict(hecho, entradas=sellos(V.CAPA, V.RED,
                                                   V.RED_INFORME),
                            salidas=sellos(V.EVALUACION)),
        }
        _escribir_json(self.de("estado.json"), cambiar("estado", {
            "version": 1, "carpeta": CARPETA, "corrida_bronce": 1,
            "modelo": "modelo_limpio_run22", "limite": None,
            "archivos": {"candidatas": CANDIDATAS}, "pasos": pasos}))


def armar_particion(ruta, fuga_pmid=False, fuga_texto=False, vacia=None):
    """Una partición de juguete: 3 ejemplos por parte, con PMIDs propios."""
    os.makedirs(ruta)
    partes = {}
    for base, nombre in ((2000, "train"), (3000, "dev"), (4000, "test")):
        partes[nombre] = [
            {"text": "<e1>AraC</e1> activa <e2>araB</e2> en %s %d."
                     % (nombre, i),
             "label": "activates", "pmid": base + i, "tf": "AraC",
             "target": "araB"} for i in range(3)]
    if fuga_pmid:
        partes["test"][0]["pmid"] = 2001
    if fuga_texto:
        # Otra puntuación y otras mayúsculas: el texto canónico es el mismo.
        partes["dev"][0]["text"] = "<e1>arac</e1> ACTIVA <e2>arab</e2>, en " \
                                   "train 0"
    if vacia:
        partes[vacia] = []
    for nombre, filas in partes.items():
        _escribir_jsonl(os.path.join(ruta, "entity_marked_%s.jsonl" % nombre),
                        filas)
    return ruta


class _Base(unittest.TestCase):

    def setUp(self):
        prohibido = mock.patch.object(
            urllib.request, "urlopen",
            side_effect=AssertionError("una prueba intentó abrir la red"))
        prohibido.start()
        self.addCleanup(prohibido.stop)
        self.tmp = tempfile.mkdtemp(prefix="grn_verificar_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.datos = os.path.join(self.tmp, "datos")
        os.makedirs(self.datos)
        self.db = os.path.join(self.datos, "grn.db")
        self.carpeta = Carpeta(self.tmp)
        # El barrido_resumen.csv del repositorio trae la huella de la
        # partición real; las de juguete no la tienen. Cada prueba que lo
        # necesite escribe el suyo.
        self.barrido = os.path.join(self.tmp, "barrido_resumen.csv")
        barrido = mock.patch.object(V, "BARRIDO_RESUMEN", self.barrido)
        barrido.start()
        self.addCleanup(barrido.stop)

    def escribir_barrido(self, huella, i=22):
        with io.open(self.barrido, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["nombre", "i", "datos", "huella"])
            w.writerow(["run_%d_x" % i, i, "/content/trabajo/por_pmid",
                        huella])

    def verificar(self, **kwargs):
        kwargs.setdefault("datos", self.datos)
        return V.ejecutar(self.carpeta.ruta, **kwargs)

    def comprobacion(self, resultado, ident, clave):
        inv = self.invariante(resultado, ident)
        return [c for c in inv["comprobaciones"] if c["clave"] == clave][0]

    def invariante(self, resultado, ident):
        return [i for i in resultado["invariantes"] if i["id"] == ident][0]

    def estatus(self, resultado):
        return dict((i["id"], i["estatus"]) for i in resultado["invariantes"])


class PruebasCarpetaCoherente(_Base):

    def setUp(self):
        super().setUp()
        armar_base(self.db)
        self.carpeta.escribir()

    def test_pasa_con_cero(self):
        html_ruta = os.path.join(self.tmp, "informe", "verificacion.html")
        r = self.verificar(salida_html=html_ruta)

        self.assertEqual(r["codigo"], 0, V.lineas(r))
        self.assertEqual(self.estatus(r), {
            "I1": "cumple", "I2": "cumple", "I3": "no_aplica",
            "I4": "cumple", "I5": "cumple"})
        self.assertEqual(self.invariante(r, "I1")["valor"], 1.0)
        for clave in ("supervivientes", "sin_dato_sintaxis", "resumen_bronce",
                      "entradas", "salidas", "huellas_red", "huellas_puente",
                      "huellas_predicciones", "huella_sintaxis"):
            self.assertEqual(self.comprobacion(r, "I4", clave)["estatus"],
                             "cumple", clave)
        self.assertEqual([e["n"] for e in r["embudo"]],
                         [4, 12, 8, 8, 9, 6, 4])
        self.assertTrue(os.path.isfile(self.carpeta.de(V.ARCHIVO_JSON)))
        self.assertTrue(os.path.isfile(html_ruta))

    def test_el_json_y_el_html_son_publicables(self):
        """Ni la carpeta temporal (con la cuenta del usuario) ni las rutas
        absolutas que traen predicciones_meta y red_informe, ni nada de las
        oraciones."""
        html_ruta = os.path.join(self.tmp, "v.html")
        r = self.verificar(salida_html=html_ruta)
        self.assertTrue(r["publicable"])
        with io.open(self.carpeta.de(V.ARCHIVO_JSON), encoding="utf-8") as f:
            texto_json = f.read()
        with io.open(html_ruta, encoding="utf-8") as f:
            texto_html = f.read()
        # El JSON escribe `\` como `\\`: se busca en las cadenas ya leídas.
        cadenas = _cadenas(json.loads(texto_json)) + [texto_html]
        for texto in (texto_json, texto_html):
            reentrenar.verificar_publicable(texto)
        for texto in cadenas:
            self.assertNotIn(self.tmp, texto)
            self.assertNotIn(self.tmp.replace("\\", "/"), texto)
            self.assertNotIn("PA900", texto)
            self.assertNotIn("<e1>", texto)
            self.assertNotIn("LasR activates", texto)
            self.assertIsNone(re.search(r"(?<![0-9A-Za-z])1001(?![0-9A-Za-z])",
                                        texto))

    def test_el_html_escapa_y_no_carga_nada_de_fuera(self):
        html_ruta = os.path.join(self.tmp, "v.html")
        self.verificar(salida_html=html_ruta)
        with io.open(html_ruta, encoding="utf-8") as f:
            texto = f.read()
        # La nota del paso y la de la evaluación traen un <script>: sale
        # escapado, y la página no trae ningún script propio.
        self.assertIn("&lt;script&gt;", texto)
        self.assertNotIn("<script", texto.lower())
        self.assertIsNone(re.search(r"\b(src|href)\s*=", texto, re.I))
        for externo in ("@import", "url(", "<link", "http:", "https:",
                        "@font-face"):
            self.assertNotIn(externo, texto.lower())

    def test_avisa_del_paso_omitido_sin_fallar(self):
        r = self.verificar()
        self.assertEqual(r["codigo"], 0)
        self.assertTrue(any("operones" in a and "omitido" in a
                            for a in r["avisos"]), r["avisos"])

    def test_la_cli_devuelve_el_codigo(self):
        dichas = []
        with mock.patch.object(cli, "log", dichas.append):
            codigo = cli.main(["verificar", "--carpeta", self.carpeta.ruta,
                               "--datos", self.datos,
                               "--json", os.path.join(self.tmp, "v.json"),
                               "--html", os.path.join(self.tmp, "v.html")])
        self.assertEqual(codigo, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "v.json")))
        self.assertFalse(os.path.exists(self.carpeta.de(V.ARCHIVO_JSON)))
        self.assertTrue(any("código 0" in l for l in dichas), dichas)
        self.assertFalse(any(self.tmp in l for l in dichas), dichas)


class PruebasEslabonesRotos(_Base):

    def test_normalizacion_baja_da_uno(self):
        corrida = armar_base(self.db)
        con = bdb.conectar(self.db)
        unidad = con.execute("SELECT MIN(id) FROM texto_unidades").fetchone()[0]
        bdb.guardar_menciones(con, corrida, "lexico", unidad, [
            {"tipo": "gen", "texto": "xyzA", "id_normalizado": "",
             "offset_ini": 0, "offset_fin": 4}] * 20)
        con.commit()
        con.close()
        # El resumen del bronce se exportaría con las 44 menciones: así solo
        # falla la normalización.
        self.carpeta.escribir(
            resumen=lambda filas: filas[-1].__setitem__(1, 44))

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.estatus(r)["I1"], "falla")
        self.assertEqual(self.estatus(r)["I4"], "cumple")
        self.assertEqual(self.invariante(r, "I1")["valor"], 0.4444)

    def test_una_mencion_de_otra_corrida_da_uno(self):
        armar_base(self.db)
        con = bdb.conectar(self.db)
        otra = bdb.abrir_corrida(con, "1", "otro-metodo", "1", {}, None)
        unidad = con.execute(
            "SELECT MIN(id) FROM texto_unidades WHERE corrida_id = 1"
        ).fetchone()[0]
        bdb.guardar_menciones(con, otra, "lexico", unidad, [
            {"tipo": "gen", "texto": "lasR", "id_normalizado": "PA9001",
             "offset_ini": 0, "offset_fin": 4}])
        bdb.cerrar_corrida(con, otra, "ok")
        con.close()
        self.carpeta.escribir()

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.estatus(r)["I2"], "falla")
        valores = dict(self.comprobacion(r, "I2", "integridad")["valores"])
        self.assertEqual(valores["menciones_de_otra_corrida"], 1)
        # La mención ajena no entra en los conteos de la corrida 1.
        self.assertEqual(self.estatus(r)["I1"], "cumple")

    def test_un_corpus_alterado_da_uno(self):
        armar_base(self.db)
        con = bdb.conectar(self.db)
        with con:
            con.execute("DELETE FROM corpus_documento WHERE pmid = ?",
                        (PMIDS[-1],))
        con.close()
        self.carpeta.escribir()

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.estatus(r)["I5"], "falla")
        self.assertEqual(self.comprobacion(r, "I5", "huella")["estatus"],
                         "falla")

    def test_un_conteo_roto_da_uno(self):
        armar_base(self.db)
        self.carpeta.escribir(capa_resumen=lambda d: d.update(filas=10))

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        fallan = [c["clave"] for c in self.invariante(r, "I4")["comprobaciones"]
                  if c["estatus"] == "falla"]
        self.assertEqual(fallan, ["pares"])

    def test_un_paso_en_error_da_uno(self):
        armar_base(self.db)
        self.carpeta.escribir(
            estado=lambda d: d["pasos"]["red"].update(estatus="error"))

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.comprobacion(r, "I4", "pasos")["estatus"],
                         "falla")

    def test_un_paso_desconocido_no_rompe(self):
        """Otra rama agrega un paso «paquete» al final del flujo: la
        verificación no recorre la lista del flujo, solo lo que trae
        estado.json."""
        armar_base(self.db)

        def con_paquete(d):
            d["pasos"]["paquete"] = {
                "estatus": "ok", "nombre": "Paquete",
                "entradas": {"salidas/flujo/%s/%s" % (CARPETA, V.RED):
                             procedencia.huella(self.carpeta.de(V.RED))},
                "salidas": {"salidas/flujo/paquete.zip": "0123456789abcdef"}}
        self.carpeta.escribir(estado=con_paquete)

        r = self.verificar()

        self.assertEqual(r["codigo"], 0, V.lineas(r))
        valores = dict(self.comprobacion(r, "I4", "pasos")["valores"])
        self.assertEqual(valores["paquete"], "ok")

    def test_falta_un_paso_exigido_da_uno(self):
        armar_base(self.db)
        self.carpeta.escribir(estado=lambda d: d["pasos"].pop("evaluar"))

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        comprobacion = self.comprobacion(r, "I4", "pasos")
        self.assertEqual(comprobacion["estatus"], "falla")
        self.assertIn("evaluar", comprobacion["nota"])

    def test_una_salida_cambiada_despues_da_uno(self):
        armar_base(self.db)
        self.carpeta.escribir()
        with io.open(self.carpeta.de(V.RED), "a", encoding="utf-8") as f:
            f.write("rhlR\trhlA\trepresses\n")

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        fallan = [c["clave"] for c in self.invariante(r, "I4")["comprobaciones"]
                  if c["estatus"] == "falla"]
        self.assertIn("salidas", fallan)
        self.assertIn("huellas_red", fallan)

    def test_unos_pares_rehechos_sin_rehacer_la_capa_dan_uno(self):
        """`--pasos pares` rehace pares.jsonl y deja la capa como estaba: las
        cifras no cambian y la capa ya no es de estos pares."""
        armar_base(self.db)
        self.carpeta.escribir()
        estado = _leer_json(self.carpeta.de("estado.json"))
        with io.open(self.carpeta.de(V.PARES), "a", encoding="utf-8") as f:
            f.write("\n")
        nueva = procedencia.huella(self.carpeta.de(V.PARES))
        clave = "salidas/flujo/%s/%s" % (CARPETA, V.PARES)
        estado["pasos"]["pares"]["salidas"][clave] = nueva
        _escribir_json(self.carpeta.de("estado.json"), estado)

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.comprobacion(r, "I4", "entradas")["estatus"],
                         "falla")
        self.assertEqual(self.comprobacion(r, "I4", "salidas")["estatus"],
                         "cumple")

    def test_otra_corrida_en_el_csv_da_uno(self):
        armar_base(self.db)

        def otra(filas):
            filas[0]["corrida_id"] = 7
        self.carpeta.escribir(candidatas=otra)

        r = self.verificar()

        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.comprobacion(r, "I4", "corrida")["estatus"],
                         "falla")


class PruebasParticion(_Base):

    def setUp(self):
        super().setUp()
        armar_base(self.db)
        self.carpeta.escribir()

    def test_una_particion_limpia_cumple_y_avisa_del_vinculo(self):
        r = self.verificar(particion=armar_particion(
            os.path.join(self.tmp, "por_pmid")))
        self.assertEqual(r["codigo"], 0, V.lineas(r))
        self.assertEqual(self.estatus(r)["I3"], "cumple")
        self.assertIn(V.VINCULO_PARTICION, r["avisos"])

    def test_la_huella_del_barrido_que_coincide_cumple_sin_aviso(self):
        ruta = armar_particion(os.path.join(self.tmp, "por_pmid"))
        self.escribir_barrido(V._huella_particion(ruta))

        r = self.verificar(particion=ruta)

        self.assertEqual(r["codigo"], 0, V.lineas(r))
        self.assertEqual(self.comprobacion(r, "I3", "vinculo")["estatus"],
                         "cumple")
        self.assertNotIn(V.VINCULO_PARTICION, r["avisos"])

    def test_otra_particion_que_la_del_barrido_da_uno(self):
        self.escribir_barrido("3d2cb9d4a0378177")
        r = self.verificar(particion=armar_particion(
            os.path.join(self.tmp, "por_pmid")))
        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.comprobacion(r, "I3", "vinculo")["estatus"],
                         "falla")

    def test_sin_fila_del_run_solo_avisa(self):
        self.escribir_barrido("3d2cb9d4a0378177", i=21)
        r = self.verificar(particion=armar_particion(
            os.path.join(self.tmp, "por_pmid")))
        self.assertEqual(r["codigo"], 0, V.lineas(r))
        self.assertEqual(self.comprobacion(r, "I3", "vinculo")["estatus"],
                         "no_aplica")
        self.assertIn(V.VINCULO_PARTICION, r["avisos"])

    def test_un_pmid_de_test_en_train_da_uno(self):
        r = self.verificar(particion=armar_particion(
            os.path.join(self.tmp, "por_pmid"), fuga_pmid=True))
        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.comprobacion(r, "I3", "pmids")["estatus"],
                         "falla")

    def test_un_texto_canonico_de_dev_en_train_da_uno(self):
        r = self.verificar(particion=armar_particion(
            os.path.join(self.tmp, "por_pmid"), fuga_texto=True))
        self.assertEqual(r["codigo"], 1)
        valores = dict(self.comprobacion(r, "I3", "textos")["valores"])
        self.assertEqual(valores["ejemplos de dev con su texto en train"], 1)

    def test_una_parte_vacia_no_pasa_por_limpia(self):
        r = self.verificar(particion=armar_particion(
            os.path.join(self.tmp, "por_pmid"), vacia="test"))
        self.assertEqual(r["codigo"], 1)
        self.assertEqual(self.comprobacion(r, "I3", "partes")["estatus"],
                         "falla")

    def test_una_particion_que_no_esta_no_se_puede_verificar(self):
        r = self.verificar(particion=os.path.join(self.tmp, "no_esta"))
        self.assertEqual(r["codigo"], 2)
        self.assertEqual(self.estatus(r)["I3"], "no_verificable")


class PruebasNoVerificable(_Base):

    def test_un_candado_da_dos_y_no_escribe(self):
        armar_base(self.db)
        self.carpeta.escribir()
        with io.open(self.carpeta.de(V.CANDADO), "w") as f:
            f.write("1234")

        r = self.verificar(salida_html=os.path.join(self.tmp, "v.html"))

        self.assertEqual(r["codigo"], 2)
        self.assertIn(".flujo.lock", r["motivo"])
        self.assertFalse(os.path.exists(self.carpeta.de(V.ARCHIVO_JSON)))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "v.html")))

    def test_sin_carpeta_o_sin_estado_da_dos(self):
        r = V.ejecutar(os.path.join(self.tmp, "no_esta"), datos=self.datos)
        self.assertEqual(r["codigo"], 2)
        r = V.ejecutar(self.carpeta.ruta, datos=self.datos)
        self.assertEqual(r["codigo"], 2)
        self.assertIn("estado.json", r["motivo"])

    def test_sin_base_da_dos_y_no_la_crea(self):
        self.carpeta.escribir()
        vacia = os.path.join(self.tmp, "otros_datos")

        r = self.verificar(datos=vacia)

        self.assertEqual(r["codigo"], 2)
        for ident in ("I1", "I2", "I5"):
            self.assertEqual(self.estatus(r)[ident], "no_verificable")
        self.assertEqual(self.estatus(r)["I4"], "cumple")
        self.assertFalse(os.path.exists(vacia))


class PruebasAvisos(_Base):

    def test_zombis_paso_2_suelto_y_recursos_sin_sellar_no_fallan(self):
        armar_base(self.db, sellar_recursos=False)
        con = bdb.conectar(self.db)
        zombi = bdb.abrir_corrida(con, "1", "m", "9", {}, None)
        with con:
            con.execute("UPDATE corridas SET iniciada_en = ? WHERE id = ?",
                        ("2020-01-01T00:00:00+00:00", zombi))
        suelta = bdb.abrir_corrida(con, "2", "biobert-run22", "1",
                                   {"corrida_bronce": 99}, None)
        bdb.cerrar_corrida(con, suelta, "ok")
        con.close()
        self.carpeta.escribir()

        r = self.verificar()

        self.assertEqual(r["codigo"], 0, V.lineas(r))
        avisos = " | ".join(r["avisos"])
        self.assertIn("anterior al sellado", avisos)
        self.assertIn("«corriendo»", avisos)
        self.assertIn("%d (bronce 99)" % suelta, avisos)

    def test_una_metrica_con_el_ic_mal_avisa(self):
        armar_base(self.db)

        def mal(d):
            d["P0_bronce"]["ic95"] = [0.1, 0.9]
        self.carpeta.escribir(evaluacion=mal)

        r = self.verificar()

        self.assertEqual(r["codigo"], 0)
        self.assertTrue(any("Wilson" in a and "P0_bronce" in a
                            for a in r["avisos"]), r["avisos"])


class PruebasContra(_Base):

    def test_dice_que_cambio_contra_otra_verificacion(self):
        armar_base(self.db)
        self.carpeta.escribir()
        antes = os.path.join(self.tmp, "antes.json")
        self.verificar(salida_json=antes)
        self.carpeta.escribir(capa_resumen=lambda d: d.update(filas=10))
        html_ruta = os.path.join(self.tmp, "v.html")

        r = self.verificar(contra=antes, salida_html=html_ruta)

        contra = r["contra"]
        self.assertEqual(contra["codigo_antes"], 0)
        self.assertEqual(contra["codigo_ahora"], 1)
        cambios = dict((i["id"], (i["antes"], i["ahora"]))
                       for i in contra["invariantes"] if i["cambia"])
        self.assertEqual(cambios, {"I4": ("cumple", "falla")})
        with io.open(html_ruta, encoding="utf-8") as f:
            self.assertIn("Comparación con antes.json", f.read())

    def test_un_contra_ilegible_avisa_y_no_compara(self):
        armar_base(self.db)
        self.carpeta.escribir()
        malo = os.path.join(self.tmp, "malo.json")
        with io.open(malo, "w", encoding="utf-8") as f:
            f.write("[1, 2")

        r = self.verificar(contra=malo)

        self.assertIsNone(r["contra"])
        self.assertTrue(any("--contra" in a for a in r["avisos"]))


class PruebasPublicableDeFormaReal(_Base):
    """Con la forma de la corrida real: el CSV del bronce con su fecha en el
    nombre, y conteos de ocho cifras. Los dos tienen forma de PMID."""

    def test_csv_fechado_y_conteo_grande_pasan_el_filtro(self):
        armar_base(self.db)
        self.carpeta.escribir(
            capa_resumen=lambda d: d.update(filas=12345678))
        # El CSV cambia después de registrarse: su nombre tendría que salir
        # en la comprobación de las salidas.
        with io.open(self.carpeta.de(CANDIDATAS), "a", encoding="utf-8") as f:
            f.write("\n")
        antes = os.path.join(self.tmp, "antes.json")
        self.verificar(salida_json=antes)
        html_ruta = os.path.join(self.tmp, "v.html")

        r = self.verificar(contra=antes, salida_html=html_ruta)

        self.assertEqual(r["codigo"], 1)
        self.assertTrue(r["publicable"], r["avisos"])
        with io.open(self.carpeta.de(V.ARCHIVO_JSON), encoding="utf-8") as f:
            texto_json = f.read()
        with io.open(html_ruta, encoding="utf-8") as f:
            texto_html = f.read()
        for texto in (texto_json, texto_html):
            reentrenar.verificar_publicable(texto)
            self.assertIn("12 345 678", texto)
            self.assertIn("CSV de candidatas", texto)
            self.assertNotIn("20991231", texto)
            self.assertNotIn("2099-12-31", texto)
            self.assertNotIn("bytes", texto)
        salidas = self.comprobacion(r, "I4", "salidas")
        self.assertEqual(salidas["estatus"], "falla")
        self.assertEqual(salidas["valores"][0][0], "bronce: CSV de candidatas")
        # La comparación lee los miles con espacio del otro informe.
        pares = [e for e in r["contra"]["embudo"] if e["clave"] == "pares"][0]
        self.assertEqual(pares["diferencia"], 0)


class PruebasPublicable(unittest.TestCase):

    def test_las_rutas_quedan_relativas_o_en_su_ultimo_tramo(self):
        raiz = os.path.join(tempfile.gettempdir(), "repo_de_prueba")
        texto = V.publicable(
            "%s y C:\\Users\\cuenta\\x\\pares.jsonl y /home/cuenta/a/b.txt"
            % os.path.join(raiz, "grn_bronce", "recursos", "genes.tsv"),
            [raiz])
        self.assertNotIn("cuenta", texto)
        self.assertIn("genes.tsv", texto)
        self.assertIn(u"…/pares.jsonl", texto)
        self.assertIn(u"…/b.txt", texto)
        reentrenar.verificar_publicable(texto)

    def test_una_fecha_compacta_no_pasa_por_pmid(self):
        self.assertEqual(V.publicable(CANDIDATAS),
                         "bronce_identificacion_corrida1_2099-12-31_"
                         "oraciones_candidatas.csv")

    def test_lo_que_trae_locus_marcador_o_pmid_se_omite_entero(self):
        for malo in ("gen PA9001 aquí", "<e1>LasR</e1>", "pmid 12345678"):
            self.assertEqual(V.publicable(malo), V.OMITIDO)


class PruebasConexionDeLectura(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grn_lectura_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = os.path.join(self.tmp, "grn.db")
        con = bdb.conectar(self.ruta)
        db0.guardar_documentos(con, [{"pmid": "1001", "titulo": "t"}])
        modo = con.execute("PRAGMA journal_mode").fetchone()[0]
        con.close()
        self.assertEqual(modo.lower(), "wal")

    def test_rechaza_un_insert(self):
        con = bdb.conectar_lectura(self.ruta)
        self.addCleanup(con.close)
        with self.assertRaises(sqlite3.Error):
            con.execute("INSERT INTO documentos (pmid, extraido_en) "
                        "VALUES ('1002', 'x')")
        with self.assertRaises(sqlite3.Error):
            con.execute("CREATE TABLE otra (a)")
        self.assertEqual(con.execute(
            "SELECT COUNT(*) FROM documentos").fetchone()[0], 1)

    def test_no_crea_la_base_si_falta(self):
        falta = os.path.join(self.tmp, "no_esta", "grn.db")
        with self.assertRaises(bdb.ErrorBase):
            bdb.conectar_lectura(falta)
        self.assertFalse(os.path.exists(os.path.dirname(falta)))

    def test_un_archivo_que_no_es_base_lanza_al_abrir(self):
        basura = os.path.join(self.tmp, "basura.db")
        with io.open(basura, "w", encoding="utf-8") as f:
            f.write("esto no es una base de datos " * 40)
        with self.assertRaises(bdb.ErrorBase):
            bdb.conectar_lectura(basura)

    def test_abre_una_base_wal_sin_sus_wal_y_shm(self):
        # Al cerrar la última conexión, SQLite borra los dos: es el estado de
        # una base que nadie tiene abierta. Si siguieran ahí, la prueba no
        # probaría nada.
        for sufijo in ("-wal", "-shm"):
            self.assertFalse(os.path.exists(self.ruta + sufijo), sufijo)
        con = bdb.conectar_lectura(self.ruta)
        try:
            self.assertEqual(con.execute(
                "SELECT pmid FROM documentos").fetchone()["pmid"], "1001")
        finally:
            con.close()


class PruebasIntegridad(unittest.TestCase):

    def test_una_corrida_sana_da_cero_en_todo(self):
        tmp = tempfile.mkdtemp(prefix="grn_integridad_")
        self.addCleanup(shutil.rmtree, tmp, True)
        ruta = os.path.join(tmp, "grn.db")
        corrida = armar_base(ruta)
        con = bdb.conectar_lectura(ruta)
        self.addCleanup(con.close)
        integridad = bdb.integridad_de_corrida(con, corrida)
        self.assertEqual(set(integridad.values()), {0})
        por_estatus = bdb.corridas_por_estatus(con)
        self.assertEqual([f["id"] for f in por_estatus["ok"]], [corrida])


if __name__ == "__main__":
    unittest.main()
