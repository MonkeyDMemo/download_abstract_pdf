# -*- coding: utf-8 -*-
"""Pruebas de las reglas de consolidación como parámetros.

Las que no pueden faltar:

- **por omisión, la red es la de `etapa2/red.py` byte por byte**, con su
  sello: todo lo que lee `red.tsv` sigue leyendo lo mismo;
- **una configuración que no es la por omisión nunca toca `red.tsv`**;
- una prueba por regla: autorregulación, nivel de soporte, operones, mayoría y
  mínimo de artículos.

Todo es sintético: locus inventados (PA9001...), PMIDs inventados y un
catálogo de prueba; nada del laboratorio.

    python -m unittest grn_red.test_consolidar
"""

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import operones as _operones   # noqa: E402
from grn_comun import procedencia              # noqa: E402
from grn_red import cli, consolidar            # noqa: E402
from grn_red.consolidar import _red            # noqa: E402

ETIQUETAS = ["activates", "no_relation", "regulates", "represses"]


def _prediccion(id_par, tf, target, prediccion, prob, pmid, auto=False):
    resto = (1.0 - prob) / 3.0
    d = {"id_par": id_par, "pmid": pmid, "tf": tf, "target": target,
         "prediccion": prediccion}
    for e in ETIQUETAS:
        d["p_" + e] = round(prob if e == prediccion else resto, 6)
    d.update({"seccion": "results", "fuente": "fulltext",
              "autorregulacion": auto, "redaccion": "directa"})
    return d


PREDICCIONES = [
    # Dos artículos, dos oraciones: soporte múltiple. El blanco es operón.
    _prediccion("p01", "MexT", "mexEF", "activates", 0.92, 90000100),
    _prediccion("p02", "MexT", "mexEF", "activates", 0.88, 90000101),
    # Un artículo; el blanco es un operón que contiene el gen del regulador.
    _prediccion("p03", "AlgU", "algU-mucA", "activates", 0.90, 90000300),
    # Autorregulación marcada en el par.
    _prediccion("p04", "NalD", "nalD", "represses", 0.99, 90000201,
                auto=True),
    # 2 contra 1: 0.667 alcanza el 0.66 de red.py y no el 0.7.
    _prediccion("p05", "RhlR", "lasB", "activates", 0.90, 90000500),
    _prediccion("p06", "RhlR", "lasB", "activates", 0.90, 90000501),
    _prediccion("p07", "RhlR", "lasB", "represses", 0.90, 90000502),
    # Un artículo solo: cae con min_articulos=2.
    _prediccion("p08", "LasR", "rhlR", "activates", 0.95, 90000400),
    # No llega a la red.
    _prediccion("p09", "LasR", "lasB", "no_relation", 0.99, 90000401),
]

ORACIONES = {
    "p01": "MexT activates mexEF in a synthetic sentence one.",
    "p02": "MexT is needed for mexEF expression, synthetic two.",
    "p03": "AlgU activates algU-mucA, synthetic three.",
    "p04": "NalD represses its own gene nalD, synthetic four.",
    "p05": "RhlR activates lasB, synthetic five.",
    "p06": "RhlR induces lasB, synthetic six.",
    "p07": "RhlR represses lasB, synthetic seven.",
    "p08": "LasR activates rhlR, synthetic eight.",
    "p09": "LasR and lasB, synthetic nine.",
}

OPERONES = [
    ["mexEF", "mexE|mexF", "PA9003|PA9004", "prueba"],
    ["algU-mucA", "algU|mucA", "PA9010|PA9011", "prueba"],
    # Un operón que ninguna arista nombra.
    ["pqsAB", "pqsA|pqsB", "PA9020|PA9021", "prueba"],
]


def _carpeta(raiz, nombre="corrida4_prueba"):
    """Una carpeta como la que deja el flujo después del paso «biobert»."""
    carpeta = os.path.join(raiz, nombre)
    os.makedirs(carpeta)
    with io.open(os.path.join(carpeta, "predicciones.jsonl"), "w",
                 encoding="utf-8", newline="\n") as f:
        for r in PREDICCIONES:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with io.open(os.path.join(carpeta, "pares.jsonl"), "w", encoding="utf-8",
                 newline="\n") as f:
        for i, r in enumerate(PREDICCIONES):
            f.write(json.dumps({"id_par": r["id_par"],
                                "oracion_cruda": ORACIONES[r["id_par"]],
                                "n_oracion": i}, ensure_ascii=False) + "\n")
    with io.open(os.path.join(carpeta, "predicciones_meta.json"), "w",
                 encoding="utf-8") as f:
        json.dump({"id2label": {"0": "activates", "1": "no_relation",
                                "2": "regulates", "3": "represses"},
                   "modelo": "modelo_sintetico"}, f)
    return carpeta


def _catalogo(raiz):
    ruta = os.path.join(raiz, "operones_prueba.tsv")
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(_operones.COLUMNAS) + "\n")
        for fila in OPERONES:
            f.write("\t".join(fila) + "\n")
    return ruta


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    columnas = lineas[0].split("\t")
    return columnas, [dict(zip(columnas, l.split("\t"))) for l in lineas[1:]]


def _bytes(ruta):
    with io.open(ruta, "rb") as f:
        return f.read()


class BaseConsolidar(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = tmp.name
        self.carpeta = _carpeta(self.raiz)
        self.catalogo = _catalogo(self.raiz)

    def consolidar(self, cfg=None, nombre=None, carpeta=None):
        return consolidar.consolidar(carpeta or self.carpeta, cfg,
                                     nombre=nombre, catalogo=self.catalogo)

    def red(self, nombre=None):
        archivo = ("red.tsv" if nombre is None
                   else consolidar.nombres_de_salida(nombre)[0])
        return _leer_tsv(os.path.join(self.carpeta, archivo))

    def informe(self, nombre="recomendada"):
        archivo = consolidar.nombres_de_salida(nombre)[2]
        with io.open(os.path.join(self.carpeta, archivo),
                     encoding="utf-8") as f:
            return json.load(f)

    def aristas(self, filas):
        return dict(((f["tf"], f["blanco"], f.get("expandida_de", "")), f)
                    for f in filas)


class PruebasPorOmision(BaseConsolidar):

    def test_es_la_red_de_red_py_byte_por_byte(self):
        """Contra `red.py` corrido como lo corría el flujo, en otra carpeta
        con las mismas entradas."""
        self.consolidar()
        otra = _carpeta(self.raiz, "corrida4_directa")
        codigo = _red.main(
            ["--predicciones", os.path.join(otra, "predicciones.jsonl"),
             "--pares", os.path.join(otra, "pares.jsonl"),
             "--salida", os.path.join(otra, "red.tsv"),
             "--evidencias", os.path.join(otra, "red_evidencias.tsv"),
             "--informe", os.path.join(otra, "red_informe.json")],
            log=lambda m: None)
        self.assertEqual(codigo, 0)
        for nombre in ("red.tsv", "red_evidencias.tsv"):
            self.assertEqual(_bytes(os.path.join(self.carpeta, nombre)),
                             _bytes(os.path.join(otra, nombre)), nombre)
        with io.open(os.path.join(self.carpeta, "red_informe.json"),
                     encoding="utf-8") as f:
            mio = json.load(f)
        with io.open(os.path.join(otra, "red_informe.json"),
                     encoding="utf-8") as f:
            directo = json.load(f)
        # Lo único que cambia son la fecha y las rutas de la carpeta.
        for clave in ("fecha", "predicciones", "pares", "meta_inferencia",
                      "huellas"):
            mio.pop(clave)
            directo.pop(clave)
        self.assertEqual(mio, directo)

    def test_el_sello_de_red_informe_verifica(self):
        self.consolidar()
        with io.open(os.path.join(self.carpeta, "red_informe.json"),
                     encoding="utf-8") as f:
            sello = json.load(f)["huellas"]
        problemas, sin_sellar = procedencia.verificar(sello, {
            "pares": os.path.join(self.carpeta, "pares.jsonl"),
            "predicciones": os.path.join(self.carpeta, "predicciones.jsonl"),
            "red": os.path.join(self.carpeta, "red.tsv")})
        self.assertEqual((problemas, sin_sellar), ([], []))

    def test_los_argumentos_son_los_que_pasaba_el_flujo(self):
        cfg = consolidar.configuracion()
        self.assertTrue(consolidar.es_omision(cfg))
        argv = consolidar._argv_red("C", cfg, "S", "E", "I")
        self.assertEqual(argv, ["--predicciones", os.path.join("C",
                                                              "predicciones.jsonl"),
                                "--pares", os.path.join("C", "pares.jsonl"),
                                "--salida", "S", "--evidencias", "E",
                                "--informe", "I"])

    def test_lo_por_omision_dicho_a_mano_sigue_siendo_por_omision(self):
        cfg = consolidar.configuracion(mayoria=0.66, min_articulos=1,
                                       umbrales=dict(_red.UMBRALES_POR_OMISION),
                                       autorregulacion="excluir")
        self.assertTrue(consolidar.es_omision(cfg))
        self.assertFalse(consolidar.es_omision(
            consolidar.configuracion("recomendado")))

    def test_no_deja_la_red_de_otras_reglas(self):
        self.consolidar()
        nombres = sorted(os.listdir(self.carpeta))
        self.assertFalse([n for n in nombres if n.startswith("red_recomendada")
                          or n.endswith(".tmp") or n.startswith(".")], nombres)


class PruebasNuncaTocaRedTsv(BaseConsolidar):

    def test_sin_red_tsv_no_la_crea(self):
        self.consolidar({"nivel_soporte": True})
        nombres = os.listdir(self.carpeta)
        self.assertNotIn("red.tsv", nombres)
        self.assertNotIn("red_evidencias.tsv", nombres)
        self.assertNotIn("red_informe.json", nombres)
        for n in consolidar.nombres_de_salida("recomendada"):
            self.assertIn(n, nombres)
        # Ni temporales ni la carpeta de trabajo.
        self.assertFalse([n for n in nombres if n.endswith(".tmp")
                          or n.startswith(".")], nombres)

    def test_con_red_tsv_no_la_cambia(self):
        self.consolidar()
        antes = dict((n, _bytes(os.path.join(self.carpeta, n)))
                     for n in ("red.tsv", "red_evidencias.tsv",
                               "red_informe.json"))
        self.consolidar(consolidar.configuracion("recomendado"))
        self.consolidar({"mayoria": 0.9}, nombre="estricta")
        for n, contenido in antes.items():
            self.assertEqual(_bytes(os.path.join(self.carpeta, n)), contenido,
                             n)

    def test_con_nombre_va_a_su_archivo_aunque_las_reglas_sean_las_de_siempre(
            self):
        self.consolidar(nombre="copia")
        self.assertNotIn("red.tsv", os.listdir(self.carpeta))
        self.assertIn("red_copia.tsv", os.listdir(self.carpeta))

    def test_un_nombre_reservado_o_raro_es_error(self):
        for nombre in ("evidencias", "informe", "../fuera", "Mayus", ""):
            with self.assertRaises(consolidar.ErrorConsolidar, msg=nombre):
                self.consolidar({"nivel_soporte": True}, nombre=nombre)
        self.assertNotIn("red_evidencias.tsv", os.listdir(self.carpeta))


class PruebasReglas(BaseConsolidar):

    def test_autorregulacion_excluir_la_quita_y_marcar_la_deja_marcada(self):
        self.consolidar()
        _, filas = self.red()
        self.assertNotIn(("NalD", "nalD", ""), self.aristas(filas))

        self.consolidar({"autorregulacion": "marcar"})
        _, filas = self.red("recomendada")
        fila = self.aristas(filas)[("NalD", "nalD", "")]
        self.assertEqual(fila["autorregulacion"], "true")
        self.assertEqual(fila["signo"], "represses")
        self.assertEqual(self.informe()["conteos"]["n_autorregulaciones"], 1)

    def test_nivel_de_soporte_por_articulos(self):
        self.consolidar({"nivel_soporte": True})
        columnas, filas = self.red("recomendada")
        self.assertEqual(columnas, _red.COLUMNAS_RED + ["nivel_soporte"])
        aristas = self.aristas(filas)
        self.assertEqual(aristas[("MexT", "mexEF", "")]["nivel_soporte"],
                         "soporte_multiple")
        self.assertEqual(aristas[("LasR", "rhlR", "")]["nivel_soporte"],
                         "candidata")
        self.assertEqual(aristas[("RhlR", "lasB", "")]["nivel_soporte"],
                         "soporte_multiple")
        self.assertEqual(self.informe()["conteos"]["por_nivel"],
                         {"candidata": 2, "soporte_multiple": 2})

    def test_expandir_operones_agrega_los_genes_y_deja_el_operon(self):
        self.consolidar({"operones": "expandir"})
        columnas, filas = self.red("recomendada")
        self.assertEqual(columnas, _red.COLUMNAS_RED + ["expandida_de"])
        aristas = self.aristas(filas)
        original = aristas[("MexT", "mexEF", "")]
        for gen in ("mexE", "mexF"):
            expandida = aristas[("MexT", gen, "mexEF")]
            # Copia la fila del operón: es la misma evidencia.
            for c in _red.COLUMNAS_RED:
                if c != "blanco":
                    self.assertEqual(expandida[c], original[c], (gen, c))
        # AlgU -> algU es autorregulación, y por omisión se excluye; mucA sí.
        self.assertIn(("AlgU", "mucA", "algU-mucA"), aristas)
        self.assertNotIn(("AlgU", "algU", "algU-mucA"), aristas)
        self.assertIn(("AlgU", "algU-mucA", ""), aristas)
        # Lo que no es operón del catálogo no se expande.
        self.assertEqual(sum(1 for f in filas if f["expandida_de"]), 3)
        self.assertEqual(filas, sorted(filas, key=lambda f: (
            f["tf"], f["blanco"], f["expandida_de"])))
        conteos = self.informe()["conteos"]
        self.assertEqual(conteos["n_aristas_expandidas"], 3)
        self.assertEqual(conteos["n_operones_expandidos"], 2)
        self.assertEqual(conteos["n_aristas_de_operon_expandidas"], 2)
        self.assertEqual(conteos["n_expandidas_autorregulacion_excluidas"], 1)
        self.assertEqual(conteos["n_aristas_observadas"],
                         conteos["n_aristas"] - 3)

    def test_expandir_con_autorregulacion_marcada_la_deja(self):
        self.consolidar({"operones": "expandir", "autorregulacion": "marcar"})
        _, filas = self.red("recomendada")
        fila = self.aristas(filas)[("AlgU", "algU", "algU-mucA")]
        self.assertEqual(fila["autorregulacion"], "true")

    def test_las_evidencias_son_las_de_red_py(self):
        self.consolidar()
        self.consolidar(consolidar.configuracion("recomendado"))
        nombre = consolidar.nombres_de_salida("recomendada")[1]
        # Con la autorregulación marcada hay una evidencia más (NalD).
        _, mias = _leer_tsv(os.path.join(self.carpeta, nombre))
        _, base = _leer_tsv(os.path.join(self.carpeta, "red_evidencias.tsv"))
        self.assertEqual([e for e in mias if e["tf"] != "NalD"], base)

    def test_la_mayoria_cambia_el_desenlace_de_un_conflicto(self):
        self.consolidar()
        _, filas = self.red()
        fila = self.aristas(filas)[("RhlR", "lasB", "")]
        self.assertEqual((fila["signo"], fila["conflicto"]),
                         ("activates", "false"))
        self.consolidar({"mayoria": 0.7})
        _, filas = self.red("recomendada")
        fila = self.aristas(filas)[("RhlR", "lasB", "")]
        self.assertEqual((fila["signo"], fila["conflicto"]),
                         ("regulates", "true"))

    def test_min_articulos_quita_la_arista_de_un_solo_articulo(self):
        self.consolidar({"min_articulos": 2})
        _, filas = self.red("recomendada")
        aristas = self.aristas(filas)
        self.assertNotIn(("LasR", "rhlR", ""), aristas)
        self.assertIn(("MexT", "mexEF", ""), aristas)
        self.assertEqual(self.informe()["parametros"]["min_articulos"], 2)

    def test_perfil_recomendado(self):
        cfg = consolidar.configuracion("recomendado")
        self.assertEqual((cfg["autorregulacion"], cfg["nivel_soporte"],
                          cfg["operones"], cfg["mayoria"], cfg["umbrales"]),
                         ("marcar", True, "expandir", 0.66, None))
        self.consolidar(cfg)
        columnas, filas = self.red("recomendada")
        self.assertEqual(columnas, _red.COLUMNAS_RED + ["nivel_soporte",
                                                        "expandida_de"])
        aristas = self.aristas(filas)
        self.assertEqual(aristas[("MexT", "mexE", "mexEF")]["nivel_soporte"],
                         "soporte_multiple")
        self.assertIn(("NalD", "nalD", ""), aristas)

    def test_un_parametro_que_no_vale_es_error(self):
        for cambios in ({"autorregulacion": "borrar"}, {"operones": "x"},
                        {"min_articulos": 0}, {"mayoria": "mucha"},
                        {"umbrales": {"activates": 0.5}}, {"signo": "x"}):
            with self.assertRaises(consolidar.ErrorConsolidar, msg=cambios):
                consolidar.configuracion(**cambios)
        with self.assertRaises(consolidar.ErrorConsolidar):
            consolidar.configuracion("otro")

    def test_una_mayoria_que_red_py_rechaza_es_error_sin_salir(self):
        with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
            self.consolidar({"mayoria": 0.4})
        self.assertIn("--mayoria", str(ctx.exception))
        self.assertEqual([n for n in os.listdir(self.carpeta)
                          if n.startswith("red") or n.startswith(".")], [])


class PruebasInforme(BaseConsolidar):

    def setUp(self):
        super(PruebasInforme, self).setUp()
        self.consolidar(consolidar.configuracion("recomendado"))
        self.inf = self.informe()

    def test_lleva_parametros_conteos_y_el_informe_de_red_py(self):
        self.assertEqual(self.inf["nombre"], "recomendada")
        self.assertEqual(self.inf["parametros"]["operones"], "expandir")
        self.assertEqual(self.inf["archivos"]["red"], "red_recomendada.tsv")
        _, filas = self.red("recomendada")
        self.assertEqual(self.inf["conteos"]["n_aristas"], len(filas))
        self.assertIn("barrido", self.inf["red_py"])
        self.assertNotIn("huellas", self.inf["red_py"])
        self.assertEqual(self.inf["recursos"]["catalogo_operones"]["huella"],
                         procedencia.huella_texto(self.catalogo))

    def test_sus_huellas_verifican(self):
        nombres = consolidar.nombres_de_salida("recomendada")
        problemas, sin_sellar = procedencia.verificar(self.inf["huellas"], {
            "pares": os.path.join(self.carpeta, "pares.jsonl"),
            "predicciones": os.path.join(self.carpeta, "predicciones.jsonl"),
            "predicciones_meta": os.path.join(self.carpeta,
                                              "predicciones_meta.json"),
            "red": os.path.join(self.carpeta, nombres[0]),
            "evidencias": os.path.join(self.carpeta, nombres[1])})
        self.assertEqual((problemas, sin_sellar), ([], []))

    def test_dos_corridas_dan_la_misma_red(self):
        nombres = consolidar.nombres_de_salida("recomendada")
        antes = [_bytes(os.path.join(self.carpeta, n)) for n in nombres[:2]]
        self.consolidar(consolidar.configuracion("recomendado"))
        despues = [_bytes(os.path.join(self.carpeta, n)) for n in nombres[:2]]
        self.assertEqual(antes, despues)


class PruebasCLI(BaseConsolidar):

    def correr(self, argv):
        pantalla = io.StringIO()
        with contextlib.redirect_stdout(pantalla), \
                contextlib.redirect_stderr(pantalla):
            codigo = cli.main(argv)
        return codigo, pantalla.getvalue()

    def test_sin_entradas_sale_con_1_y_dice_que_falta(self):
        vacia = os.path.join(self.raiz, "vacia")
        os.makedirs(vacia)
        codigo, texto = self.correr(["consolidar", "--carpeta", vacia])
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR: Falta predicciones.jsonl", texto)
        self.assertIn("biobert", texto)
        self.assertNotIn("Traceback", texto)

    def test_por_omision_y_recomendado(self):
        codigo, texto = self.correr(["consolidar", "--carpeta", self.carpeta])
        self.assertEqual(codigo, 0, texto)
        self.assertTrue(os.path.isfile(os.path.join(self.carpeta, "red.tsv")))
        antes = _bytes(os.path.join(self.carpeta, "red.tsv"))
        # El CLI usa el catálogo versionado del paso 1: aquí solo se mira que
        # corra y que no toque red.tsv.
        codigo, texto = self.correr(["consolidar", "--carpeta", self.carpeta,
                                     "--perfil", "recomendado"])
        self.assertEqual(codigo, 0, texto)
        self.assertIn("red.tsv no se tocó", texto)
        self.assertEqual(_bytes(os.path.join(self.carpeta, "red.tsv")), antes)
        columnas, _ = self.red("recomendada")
        self.assertEqual(columnas[-2:], ["nivel_soporte", "expandida_de"])

    def test_un_flag_gana_sobre_el_perfil(self):
        codigo, texto = self.correr(["consolidar", "--carpeta", self.carpeta,
                                     "--perfil", "recomendado",
                                     "--operones", "nodo", "--nombre", "sin_op"])
        self.assertEqual(codigo, 0, texto)
        columnas, _ = self.red("sin_op")
        self.assertEqual(columnas, _red.COLUMNAS_RED + ["nivel_soporte"])


class PruebasCompatibilidad(unittest.TestCase):

    def test_consolidar_es_python_3_8_y_no_imprime(self):
        ruta = os.path.join(_RAIZ, "grn_red", "consolidar.py")
        with io.open(ruta, encoding="utf-8") as f:
            texto = f.read()
        arbol = ast.parse(texto, filename="consolidar.py",
                          feature_version=(3, 8))
        llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "print"]
        self.assertEqual(llamadas, [])


if __name__ == "__main__":
    unittest.main()
