# -*- coding: utf-8 -*-
"""Pruebas del paquete de la red.

Las que no pueden faltar:

- **«LasR» como regulador y «lasR» como blanco son un solo nodo**: es la razón
  de ser del paquete;
- **una fila que junta dos pares canónicos se detecta** y no entra al grafo;
- **el GraphML se vuelve a leer** y cuadra con nodos.tsv: todo extremo de
  arista es un nodo y ningún id se repite;
- **el manifiesto no lleva rutas absolutas**, aunque `red_informe.json` y
  `predicciones_meta.json` las traen, y sus sha256 son los de los archivos;
- **dos corridas dan los mismos bytes**.

Todo es sintético: locus inventados (PA9001...), PMIDs inventados y un
diccionario y un catálogo de prueba; nada del laboratorio.

    python -m unittest grn_red.test_paquete
"""

import ast
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
import xml.etree.ElementTree as ET

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_comun import procedencia   # noqa: E402
from grn_red import cli, paquete     # noqa: E402

NS = {"g": "http://graphml.graphdrawing.org/xmlns"}

GENES = [
    ["PA9001", "lasR", "PA9001", "protein_coding",
     "regulador sintético de quórum", "true", "prueba", "prueba", "false"],
    ["PA9002", "rhlR", "PA9002", "protein_coding", "otro regulador sintético",
     "true", "prueba", "prueba", "false"],
    ["PA9003", "mexE", "PA9003", "protein_coding", "proteína sintética",
     "false", "", "prueba", "false"],
    ["PA9004", "mexF", "PA9004", "protein_coding", "transportador sintético",
     "false", "", "prueba", "false"],
    ["PA9005", "", "PA9005", "protein_coding", "proteína hipotética",
     "false", "", "prueba", "false"],
    ["PA9006", "fur", "PA9006", "protein_coding", "regulador sintético",
     "true", "prueba", "prueba", "true"],
    ["", "IHF", "ihf", "complejo", "complejo sintético de dos subunidades",
     "true", "manual", "manual", "true"],
]

OPERONES = [
    ["mexEF", "mexE|mexF", "PA9003|PA9004", "prueba"],
    ["mexF-orfX", "mexF|PA9005", "PA9004|PA9005", "prueba"],
]


def _par(n, pmid, tf, target, tf_id, target_id, tf_locus, target_locus):
    return {"text": "<e1> %s </e1> y <e2> %s </e2> en una oración sintética "
                    "%d ." % (tf, target, n),
            "label": "", "pmid": pmid, "tf": tf, "target": target,
            "id_par": "a%015d" % n, "seccion": "results",
            "fuente": "fulltext", "n_oracion": n,
            "oracion_cruda": "Una oración sintética %d." % n,
            "autorregulacion": False, "redaccion": "directa",
            "corrida_bronce": 4, "tf_id": tf_id, "target_id": target_id,
            "tf_locus": tf_locus, "target_locus": target_locus}


PARES = [
    _par(1, 90000001, "LasR", "rhlR", "lasR", "rhlR", ["PA9001"], ["PA9002"]),
    _par(2, 90000002, "LasR", "rhlR", "lasR", "rhlR", ["PA9001"], ["PA9002"]),
    _par(3, 90000003, "RhlR", "lasR", "rhlR", "lasR", ["PA9002"], ["PA9001"]),
    _par(4, 90000001, "LasR", "mexEF", "lasR", "mexEF", ["PA9001"],
         ["PA9003", "PA9004"]),
    # La colisión: dos ids canónicos con la misma forma de proteína.
    _par(5, 90000004, "Fur", "rhlR", "fur", "rhlR", ["PA9006"], ["PA9002"]),
    _par(6, 90000005, "Fur", "rhlR", "Fur", "rhlR", [], ["PA9002"]),
    _par(7, 90000006, "IHF", "PA9005", "IHF", "PA9005", [], ["PA9005"]),
    # Un par que ninguna evidencia cita (no_relation, por ejemplo).
    _par(8, 90000006, "LasR", "mexE", "lasR", "mexE", ["PA9001"], ["PA9003"]),
    _par(9, 90000007, "RhlR", "lasR", "rhlR", "lasR", ["PA9002"], ["PA9001"]),
]


def _fila_red(tf, blanco, signo, conflicto, n, a, r, g, articulos, confianza,
              secciones, pmids):
    return [tf, blanco, signo, conflicto, str(n), str(a), str(r), str(g),
            str(articulos), confianza, "false", secciones, pmids,
            "La oración representativa de %s y %s." % (tf, blanco)]


RED = [
    _fila_red("Fur", "rhlR", "represses", "false", 2, 0, 2, 0, 2, "0.8000",
              "discussion", "90000004|90000005"),
    _fila_red("IHF", "PA9005", "activates", "false", 1, 1, 0, 0, 1, "0.9100",
              "results", "90000006"),
    _fila_red("LasR", "mexEF", "activates", "false", 1, 1, 0, 0, 1, "0.8800",
              "abstract", "90000001"),
    _fila_red("LasR", "rhlR", "activates", "false", 2, 2, 0, 0, 2, "0.9500",
              "abstract|results", "90000001|90000002"),
    # Un conflicto degradado a regulates sin un voto regulates: sin confianza.
    _fila_red("RhlR", "lasR", "regulates", "true", 2, 1, 1, 0, 2, "",
              "results", "90000003|90000007"),
]


def _evidencia(tf, blanco, n, pmid, prediccion, p):
    return [tf, blanco, "a%015d" % n, str(pmid), "results", "fulltext",
            prediccion, "%.6f" % p, "directa", "Una oración sintética %d." % n]


EVIDENCIAS = [
    _evidencia("Fur", "rhlR", 5, 90000004, "represses", 0.8),
    _evidencia("Fur", "rhlR", 6, 90000005, "represses", 0.8),
    _evidencia("IHF", "PA9005", 7, 90000006, "activates", 0.91),
    _evidencia("LasR", "mexEF", 4, 90000001, "activates", 0.88),
    _evidencia("LasR", "rhlR", 1, 90000001, "activates", 0.95),
    _evidencia("LasR", "rhlR", 2, 90000002, "activates", 0.95),
    _evidencia("RhlR", "lasR", 3, 90000003, "activates", 0.70),
    _evidencia("RhlR", "lasR", 9, 90000007, "represses", 0.75),
]

HUELLA_PREDICCIONES = "0123456789abcdef"


def _tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(fila) + "\n")


def _json(ruta, objeto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)


def _recursos(carpeta):
    """El diccionario y el catálogo de prueba, fuera de la carpeta del flujo."""
    os.makedirs(carpeta)
    genes = os.path.join(carpeta, "genes_prueba.tsv")
    catalogo = os.path.join(carpeta, "operones_prueba.tsv")
    _tsv(genes, paquete.COLUMNAS_GENES, GENES)
    from grn_bronce import operones
    _tsv(catalogo, operones.COLUMNAS, OPERONES)
    return genes, catalogo


def _carpeta(raiz, nombre="corrida4_prueba", red=None, evidencias=None,
             pares=None):
    """Una carpeta como la que deja el flujo después del paso «red».

    El informe y el meta llevan rutas absolutas, como los de verdad: el
    manifiesto no las puede repetir.
    """
    carpeta = os.path.join(raiz, nombre)
    os.makedirs(carpeta)
    ruta_pares = os.path.join(carpeta, "pares.jsonl")
    with io.open(ruta_pares, "w", encoding="utf-8", newline="\n") as f:
        for par in (PARES if pares is None else pares):
            f.write(json.dumps(par, ensure_ascii=False) + "\n")
    ruta_red = os.path.join(carpeta, "red.tsv")
    _tsv(ruta_red, paquete.COLUMNAS_RED, RED if red is None else red)
    _tsv(os.path.join(carpeta, "red_evidencias.tsv"),
         paquete.COLUMNAS_EVIDENCIAS,
         EVIDENCIAS if evidencias is None else evidencias)
    predicciones = os.path.join(os.path.abspath(carpeta), "predicciones.jsonl")
    huellas = procedencia.sellar({"pares": os.path.abspath(ruta_pares),
                                  "red": os.path.abspath(ruta_red)})
    huellas["predicciones"] = {"ruta": predicciones,
                               "huella": HUELLA_PREDICCIONES, "bytes": 100}
    _json(os.path.join(carpeta, "red_informe.json"), {
        "fecha": "2026-10-21T01:00:00",
        "predicciones": predicciones,
        "pares": os.path.abspath(ruta_pares),
        "umbrales": {"activates": 0.65, "represses": 0.7, "regulates": 0.6},
        "fuente_umbrales": "por omision", "calibrado_en": None,
        "mayoria": 0.66, "max_por_par": 200, "min_evidencias": 1,
        "min_articulos": 1, "sin_pies": "false", "sin_introduccion": "false",
        "incluir_autorregulacion": "false", "n_predicciones": 9,
        "n_aristas": 5, "n_tfs": 4, "n_blancos": 5,
        "reparto_signos": {"activates": 3, "represses": 1, "regulates": 1},
        "meta_inferencia": {"ruta": os.path.join(carpeta, "x.json"),
                            "modelo": "C:\\Users\\alguien\\modelo_sintetico"},
        "huellas": huellas})
    _json(os.path.join(carpeta, "predicciones_meta.json"), {
        "modelo": "C:\\Users\\alguien\\modelo_sintetico",
        "etiquetas_de": "C:\\Users\\alguien\\modelo_sintetico\\"
                        "label_mapping.json",
        "sha1_config": "f" * 40,
        "huellas_modelo": {"pytorch_model.bin": "1111111111111111"},
        "id2label": {"0": "activates", "1": "no_relation", "2": "regulates",
                     "3": "represses"},
        "max_length": 512,
        "huella_pares": procedencia.huella(ruta_pares),
        "huella_predicciones": HUELLA_PREDICCIONES,
        "reutilizadas": {"n": 3, "fuentes": [
            {"carpeta": "/home/alguien/datos_etapa2", "textos": 3}]}})
    _json(os.path.join(carpeta, "estado.json"),
          {"corrida_bronce": 4, "carpeta": nombre, "pasos": {}})
    return carpeta


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    columnas = lineas[0].split("\t")
    return [dict(zip(columnas, l.split("\t"))) for l in lineas[1:]]


def _cadenas(objeto):
    if isinstance(objeto, dict):
        for k, v in objeto.items():
            yield k
            for c in _cadenas(v):
                yield c
    elif isinstance(objeto, list):
        for v in objeto:
            for c in _cadenas(v):
                yield c
    elif isinstance(objeto, str):
        yield objeto


class BasePaquete(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = tmp.name
        self.genes, self.catalogo = _recursos(os.path.join(self.raiz, "rec"))

    def empaquetar(self, carpeta, log=paquete._nada):
        return paquete.empaquetar(carpeta, log=log, genes=self.genes,
                                  catalogo=self.catalogo)

    def nodos(self, carpeta):
        return dict((n["id"], n)
                    for n in _leer_tsv(os.path.join(carpeta, "nodos.tsv")))


class PruebasPaquete(BasePaquete):

    def setUp(self):
        super(PruebasPaquete, self).setUp()
        self.carpeta = _carpeta(self.raiz)
        self.manifiesto = self.empaquetar(self.carpeta)

    def test_lasR_regulador_y_lasR_blanco_son_un_solo_nodo(self):
        nodos = self.nodos(self.carpeta)
        self.assertIn("lasR", nodos)
        self.assertNotIn("LasR", nodos)
        lasr = nodos["lasR"]
        self.assertEqual(lasr["locus"], "PA9001")
        self.assertEqual(lasr["tipo"], "gen")
        self.assertEqual(lasr["es_tf"], "true")
        # Sale hacia rhlR y hacia mexEF, y le llega RhlR -> lasR.
        self.assertEqual((lasr["grado_salida"], lasr["grado_entrada"]),
                         ("2", "1"))
        self.assertEqual(sorted(nodos), ["IHF", "PA9005", "lasR", "mexEF",
                                         "rhlR"])

    def test_el_simbolo_y_el_locus_del_mismo_gen_son_un_solo_nodo(self):
        """El texto que nombra a lasR por su locus da un par con tf_id
        «PA9001»; sin unificar por locus, lasR saldría dos veces."""
        pares = PARES + [_par(10, 90000008, "PA9001", "rhlR", "PA9001",
                              "rhlR", ["PA9001"], ["PA9002"])]
        red = RED + [_fila_red("PA9001", "rhlR", "activates", "false", 1, 1,
                               0, 0, 1, "0.9000", "results", "90000008")]
        evidencias = EVIDENCIAS + [_evidencia("PA9001", "rhlR", 10, 90000008,
                                              "activates", 0.9)]
        carpeta = _carpeta(self.raiz, "con_locus", red=red,
                           evidencias=evidencias, pares=pares)
        manifiesto = self.empaquetar(carpeta)
        nodos = self.nodos(carpeta)
        self.assertNotIn("PA9001", nodos)
        self.assertEqual(nodos["lasR"]["grado_salida"], "3")
        self.assertEqual(manifiesto["unificados"],
                         [{"id": "lasR", "alias": ["PA9001"]}])
        # Las dos filas quedan como aristas paralelas: sumarlas sería
        # volver a agregar, que es trabajo de red.py.
        self.assertEqual(manifiesto["grafo"]["n_aristas"], 5)
        self.assertEqual(manifiesto["grafo"]["n_aristas_paralelas"], 2)
        raiz = ET.parse(os.path.join(carpeta, "red.graphml")).getroot()
        aristas = raiz.find("g:graph", NS).findall("g:edge", NS)
        self.assertEqual(sum(1 for a in aristas
                             if (a.get("source"), a.get("target"))
                             == ("lasR", "rhlR")), 2)
        self.assertEqual(len(set(a.get("id") for a in aristas)), len(aristas))

    def test_un_blanco_operon_lleva_sus_locus(self):
        mexef = self.nodos(self.carpeta)["mexEF"]
        self.assertEqual(mexef["tipo"], "operon")
        self.assertEqual(mexef["locus"], "PA9003|PA9004")
        self.assertEqual(mexef["simbolo"], "mexEF")
        self.assertEqual(mexef["es_tf"], "false")
        # Los operones del catálogo que tocan sus locus, él incluido.
        self.assertEqual(mexef["operones"], "mexEF|mexF-orfX")

    def test_lo_que_no_tiene_locus_o_simbolo_se_dice(self):
        nodos = self.nodos(self.carpeta)
        ihf = nodos["IHF"]
        self.assertEqual((ihf["tipo"], ihf["locus"], ihf["es_tf"]),
                         ("sin_locus", "", "true"))
        self.assertEqual(ihf["producto"], "complejo sintético de dos "
                                          "subunidades")
        gen = nodos["PA9005"]
        self.assertEqual((gen["tipo"], gen["simbolo"], gen["operones"]),
                         ("gen", "", "mexF-orfX"))

    def test_una_colision_se_detecta_y_queda_fuera_del_grafo(self):
        colisiones = self.manifiesto["colisiones"]
        self.assertEqual(len(colisiones), 1)
        self.assertEqual((colisiones[0]["tf"], colisiones[0]["blanco"]),
                         ("Fur", "rhlR"))
        self.assertEqual([(p["tf_id"], p["target_id"], p["n_evidencias"])
                          for p in colisiones[0]["pares"]],
                         [("Fur", "rhlR", 1), ("fur", "rhlR", 1)])
        nodos = self.nodos(self.carpeta)
        self.assertNotIn("fur", nodos)
        self.assertNotIn("Fur", nodos)
        grafo = self.manifiesto["grafo"]
        self.assertEqual((grafo["n_filas_red"], grafo["n_aristas"],
                          grafo["n_colisiones"]), (5, 4, 1))

    def test_el_graphml_se_vuelve_a_leer_y_cuadra(self):
        raiz = ET.parse(os.path.join(self.carpeta, "red.graphml")).getroot()
        self.assertEqual(raiz.tag, "{%s}graphml" % NS["g"])
        grafo = raiz.find("g:graph", NS)
        self.assertEqual(grafo.get("edgedefault"), "directed")
        nodos = grafo.findall("g:node", NS)
        aristas = grafo.findall("g:edge", NS)
        ids = [n.get("id") for n in nodos]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), sorted(self.nodos(self.carpeta)))
        self.assertEqual(len(aristas), self.manifiesto["grafo"]["n_aristas"])
        for a in aristas:
            self.assertIn(a.get("source"), ids)
            self.assertIn(a.get("target"), ids)
        self.assertEqual(sorted((a.get("source"), a.get("target"))
                                for a in aristas),
                         [("IHF", "PA9005"), ("lasR", "mexEF"),
                          ("lasR", "rhlR"), ("rhlR", "lasR")])

        claves = dict((k.get("id"), k) for k in raiz.findall("g:key", NS))
        self.assertTrue(set(k.get("attr.type") for k in claves.values())
                        <= set(["string", "int", "double", "boolean"]))
        de_arista = [k.get("attr.name") for k in claves.values()
                     if k.get("for") == "edge"]
        self.assertEqual(de_arista, [c for c in paquete.COLUMNAS_RED
                                     if c != "oracion_representativa"])

        def datos(elemento):
            return dict((claves[d.get("key")].get("attr.name"), d.text)
                        for d in elemento.findall("g:data", NS))

        por_par = dict(((a.get("source"), a.get("target")), datos(a))
                       for a in aristas)
        lasr_rhlr = por_par[("lasR", "rhlR")]
        self.assertEqual(lasr_rhlr["pmids"], "90000001;90000002")
        self.assertEqual(lasr_rhlr["secciones"], "abstract|results")
        self.assertEqual(lasr_rhlr["n_evidencias"], "2")
        self.assertEqual((lasr_rhlr["tf"], lasr_rhlr["blanco"]),
                         ("LasR", "rhlR"))
        # La confianza vacía de un conflicto no se escribe: 0 la inventaría.
        self.assertNotIn("confianza", por_par[("rhlR", "lasR")])
        self.assertEqual(por_par[("rhlR", "lasR")]["conflicto"], "true")
        mexef = [datos(n) for n in nodos if n.get("id") == "mexEF"][0]
        self.assertEqual(mexef["locus"], "PA9003|PA9004")
        self.assertEqual(mexef["tipo"], "operon")

    def test_el_manifiesto_cuadra_con_los_archivos_y_no_lleva_rutas(self):
        ruta = os.path.join(self.carpeta, "manifiesto.json")
        with io.open(ruta, encoding="utf-8") as f:
            texto = f.read()
        manifiesto = json.loads(texto)
        self.assertEqual(list(manifiesto["archivos"]),
                         ["red.tsv", "red_evidencias.tsv", "red_informe.json",
                          "nodos.tsv", "red.graphml"])
        for nombre, sello in manifiesto["archivos"].items():
            archivo = os.path.join(self.carpeta, nombre)
            self.assertEqual(sello["sha256"], paquete.sha256(archivo), nombre)
            self.assertEqual(sello["bytes"], os.path.getsize(archivo), nombre)
        for cadena in _cadenas(manifiesto):
            self.assertNotIn(":\\", cadena)
            self.assertFalse(cadena.startswith("/"), cadena)
            self.assertFalse(cadena.startswith("\\"), cadena)
            self.assertIsNone(re.match(r"^[A-Za-z]:", cadena), cadena)
        self.assertNotIn(os.path.basename(self.raiz), texto)

        self.assertEqual(manifiesto["corrida_bronce"], 4)
        self.assertEqual(manifiesto["carpeta"], "corrida4_prueba")
        self.assertEqual(manifiesto["modelo"]["nombre"], "modelo_sintetico")
        self.assertEqual(manifiesto["modelo"]["sha1_config"], "f" * 40)
        self.assertEqual(manifiesto["modelo"]["huella_predicciones"],
                         HUELLA_PREDICCIONES)
        self.assertEqual(manifiesto["red"]["umbrales"]["represses"], 0.7)
        self.assertEqual(manifiesto["red"]["mayoria"], 0.66)
        self.assertEqual(manifiesto["red"]["max_por_par"], 200)
        self.assertEqual(manifiesto["red"]["conteos"]["n_aristas"], 5)
        self.assertEqual(sorted(manifiesto["red"]["huellas"]),
                         ["pares", "predicciones", "red"])
        for sello in manifiesto["red"]["huellas"].values():
            self.assertEqual(sorted(sello), ["bytes", "huella"])
        self.assertEqual(manifiesto["recursos"]["diccionario"]["huella"],
                         procedencia.huella_texto(self.genes))
        self.assertEqual(
            manifiesto["recursos"]["catalogo_operones"]["archivo"],
            "operones_prueba.tsv")
        self.assertIsNone(manifiesto["kb"])
        self.assertEqual(manifiesto["go"], "pendiente")
        self.assertIn("kb", manifiesto["notas"])
        self.assertIn("UniProt", manifiesto["notas"]["go"])
        self.assertTrue(manifiesto["generado"].endswith("Z"))

    def test_dos_corridas_dan_los_mismos_bytes(self):
        def bytes_de(carpeta):
            salida = {}
            for nombre in ("nodos.tsv", "red.graphml"):
                with io.open(os.path.join(carpeta, nombre), "rb") as f:
                    salida[nombre] = f.read()
            return salida

        primera = bytes_de(self.carpeta)
        self.empaquetar(self.carpeta)
        self.assertEqual(bytes_de(self.carpeta), primera)
        # Ni el nombre ni la ruta de la carpeta entran a esos dos archivos.
        otra = _carpeta(os.path.join(self.raiz, "otra raiz"), "otro_nombre")
        self.empaquetar(otra)
        self.assertEqual(bytes_de(otra), primera)
        self.assertFalse(any(n.endswith(".tmp")
                             for n in os.listdir(self.carpeta)))


class PruebasEntradasQueNoCuadran(BasePaquete):
    """Lo que se rechaza, y que al rechazarlo no se escribe nada."""

    def falla(self, carpeta, *frases):
        with self.assertRaises(paquete.ErrorPaquete) as ctx:
            self.empaquetar(carpeta)
        for frase in frases:
            self.assertIn(frase, str(ctx.exception))
        for nombre in ("nodos.tsv", "red.graphml", "manifiesto.json"):
            self.assertFalse(os.path.exists(os.path.join(carpeta, nombre)),
                             nombre)
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(carpeta)))
        return ctx.exception

    def test_cada_entrada_que_falta_dice_que_paso_la_escribe(self):
        for nombre, paso in (("red.tsv", "«red»"),
                             ("red_evidencias.tsv", "«red»"),
                             ("red_informe.json", "«red»"),
                             ("pares.jsonl", "«pares»"),
                             ("predicciones_meta.json", "«biobert»")):
            carpeta = _carpeta(self.raiz, "sin_" + nombre.replace(".", "_"))
            os.remove(os.path.join(carpeta, nombre))
            self.falla(carpeta, nombre, paso)

    def test_un_pares_jsonl_de_otra_corrida_se_rechaza(self):
        carpeta = _carpeta(self.raiz)
        with io.open(os.path.join(carpeta, "pares.jsonl"), "a",
                     encoding="utf-8") as f:
            f.write(json.dumps(_par(10, 90000009, "LasR", "rhlR", "lasR",
                                    "rhlR", ["PA9001"], ["PA9002"])) + "\n")
        self.falla(carpeta, "misma corrida")

    def test_un_meta_de_otras_predicciones_se_rechaza(self):
        carpeta = _carpeta(self.raiz)
        ruta = os.path.join(carpeta, "predicciones_meta.json")
        with io.open(ruta, encoding="utf-8") as f:
            meta = json.load(f)
        meta["huella_predicciones"] = "fedcba9876543210"
        _json(ruta, meta)
        self.falla(carpeta, "otro modelo")

    def test_evidencias_que_no_suman_lo_que_dice_la_fila(self):
        carpeta = _carpeta(self.raiz, evidencias=EVIDENCIAS[:-1])
        self.falla(carpeta, "RhlR -> lasR", "declara 2")

    def test_un_par_con_otras_formas_que_su_evidencia(self):
        pares = [dict(p) for p in PARES]
        pares[0]["target"] = "rhlA"
        self.falla(_carpeta(self.raiz, pares=pares), "a000000000000001")

    def test_un_id_par_que_no_esta_en_los_pares(self):
        pares = [p for p in PARES if p["id_par"] != "a000000000000007"]
        self.falla(_carpeta(self.raiz, pares=pares), "a000000000000007")

    def test_un_pares_jsonl_sin_ids_canonicos(self):
        """El de etapa2/extraer_pares.py no los trae: sin ellos no hay con
        qué unificar."""
        pares = [dict((k, v) for k, v in p.items()
                      if k not in ("tf_id", "target_id")) for p in PARES]
        self.falla(_carpeta(self.raiz, pares=pares), "tf_id")

    def test_un_conteo_que_no_es_entero(self):
        red = [list(f) for f in RED]
        red[1][4] = "uno"
        self.falla(_carpeta(self.raiz, red=red), "n_evidencias")

    def test_una_fila_repetida_daria_dos_aristas_paralelas(self):
        self.falla(_carpeta(self.raiz, red=RED + [RED[1]]), "dos veces")


class PruebasPiezas(unittest.TestCase):

    def test_limpiar_xml_quita_lo_que_xml_no_admite(self):
        self.assertEqual(paquete.limpiar_xml("a\x0cb\x01c\x00d"), "abcd")
        self.assertEqual(paquete.limpiar_xml("x\ud800y\ufffez"), "xyz")
        # Lo que sí admite se queda, acentos y fuera del plano básico
        # incluidos.
        texto = "tab\tsalto\nretorno\r año σ \U00010000"
        self.assertEqual(paquete.limpiar_xml(texto), texto)

    def test_un_control_en_un_valor_no_rompe_el_graphml(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "red.graphml")
            nodo = dict((c, "") for c in paquete.COLUMNAS_NODOS)
            nodo.update(id="mexT", tipo="gen", es_tf=True, grado_salida=0,
                        grado_entrada=0, producto="antes\x0cdespués\x01fin")
            paquete.escribir_graphml(ruta, [nodo], [])
            raiz = ET.parse(ruta).getroot()
            textos = [d.text for d in raiz.iter("{%s}data" % NS["g"])]
        self.assertIn("antesdespuésfin", textos)
        self.assertFalse(any("\x0c" in t or "\x01" in t for t in textos))

    def test_un_extremo_que_no_es_nodo_no_se_escribe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            nodo = dict((c, "") for c in paquete.COLUMNAS_NODOS)
            nodo.update(id="mexT", es_tf=True, grado_salida=1,
                        grado_entrada=0)
            arista = {"fuente": "mexT", "destino": "mexE", "atributos": dict(
                (c, "") for c, _ in paquete.ATRIBUTOS_ARISTA)}
            with self.assertRaises(paquete.ErrorPaquete):
                paquete.escribir_graphml(os.path.join(carpeta, "r.graphml"),
                                         [nodo], [arista])

    def test_las_columnas_son_las_de_red_py_importadas(self):
        sys.path.insert(0, os.path.join(_RAIZ, "etapa2"))
        import red
        self.assertIs(paquete.COLUMNAS_RED, red.COLUMNAS_RED)
        self.assertIs(paquete.COLUMNAS_EVIDENCIAS, red.COLUMNAS_EVIDENCIAS)
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "red.tsv")
            _tsv(ruta, red.COLUMNAS_RED[:-1], [])
            with self.assertRaises(paquete.ErrorPaquete):
                paquete.leer_tsv(ruta, red.COLUMNAS_RED)

    def test_el_catalogo_es_el_versionado_y_no_la_base(self):
        """`operones_base.tsv` lleva datos de BioCyc que no se pueden
        redistribuir, y el paquete está hecho para salir de la máquina."""
        import flujo
        from grn_bronce import operones
        n = os.path.normcase
        self.assertEqual(n(paquete.RUTA_CATALOGO), n(operones.RUTA_POR_OMISION))
        self.assertEqual(n(paquete.RUTA_CATALOGO), n(flujo.OPERONES_CATALOGO))
        self.assertEqual(n(paquete.RUTA_GENES), n(flujo.GENES))
        self.assertNotEqual(n(paquete.RUTA_CATALOGO), n(operones.RUTA_BASE))

    def test_el_nombre_del_modelo_sale_de_rutas_de_las_dos_familias(self):
        for ruta in ("C:\\Users\\alguien\\modelo_limpio_run22",
                     "C:\\Users\\alguien\\modelo_limpio_run22\\",
                     "/home/alguien/modelo_limpio_run22",
                     "modelo_limpio_run22"):
            self.assertEqual(paquete._ultimo_componente(ruta),
                             "modelo_limpio_run22", ruta)

    def test_rutas_absolutas_las_ve_en_claves_y_listas(self):
        self.assertEqual(paquete.rutas_absolutas(
            {"a": ["bien", "/home/x"], "C:\\x": 1, "b": {"c": "D:/y"},
             "d": "etapa2/red.py", "e": "por omision"}),
            ["/home/x", "C:\\x", "D:/y"])

    def test_pares_por_id_trae_solo_lo_pedido(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "pares.jsonl")
            with io.open(ruta, "w", encoding="utf-8") as f:
                for par in PARES:
                    f.write(json.dumps(par) + "\n")
            por_id = paquete.pares_por_id(ruta, ["a000000000000004"])
        self.assertEqual(list(por_id), ["a000000000000004"])
        self.assertEqual(por_id["a000000000000004"]["target_locus"],
                         ["PA9003", "PA9004"])
        self.assertEqual(sorted(por_id["a000000000000004"]),
                         sorted(paquete.CLAVES_PAR))


class PruebasCli(BasePaquete):

    def test_sin_red_tsv_sale_con_1_y_dice_que_correr(self):
        carpeta = _carpeta(self.raiz)
        os.remove(os.path.join(carpeta, "red.tsv"))
        # Como lo lanza grn_comun/proceso.py: con la salida en UTF-8, que en
        # una tubería de Windows sería la página de códigos del sistema.
        r = subprocess.run(
            [sys.executable, "-m", "grn_red.cli", "paquete", "--carpeta",
             carpeta], cwd=_RAIZ, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        salida = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 1, salida)
        self.assertIn("red.tsv", salida)
        self.assertIn("«red»", salida)
        self.assertNotIn("Traceback", salida)

    def test_con_todo_sale_con_0(self):
        """Con el diccionario y el catálogo versionados: los locus de prueba
        no están ahí, y el paquete sale igual, sin producto."""
        carpeta = _carpeta(self.raiz)
        pantalla = io.StringIO()
        with contextlib.redirect_stdout(pantalla):
            codigo = cli.main(["paquete", "--carpeta", carpeta])
        self.assertEqual(codigo, 0, pantalla.getvalue())
        self.assertIn("Paquete listo", pantalla.getvalue())
        for nombre in ("nodos.tsv", "red.graphml", "manifiesto.json"):
            self.assertTrue(os.path.isfile(os.path.join(carpeta, nombre)))


class PruebasCompatibilidad(unittest.TestCase):

    def fuentes(self):
        carpeta = os.path.dirname(os.path.abspath(__file__))
        for nombre in sorted(os.listdir(carpeta)):
            if nombre.endswith(".py"):
                with io.open(os.path.join(carpeta, nombre),
                             encoding="utf-8") as f:
                    yield nombre, f.read()

    def test_se_lee_con_la_gramatica_de_python_3_8(self):
        nombres = []
        for nombre, texto in self.fuentes():
            ast.parse(texto, filename=nombre, feature_version=(3, 8))
            nombres.append(nombre)
        self.assertIn("paquete.py", nombres)

    def test_print_solo_en_el_cli(self):
        for nombre, texto in self.fuentes():
            if nombre in ("cli.py",) or nombre.startswith("test_"):
                continue
            llamadas = [n for n in ast.walk(ast.parse(texto))
                        if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name)
                        and n.func.id == "print"]
            self.assertEqual(llamadas, [], nombre)


if __name__ == "__main__":
    unittest.main()
