# -*- coding: utf-8 -*-
"""Pruebas de la capa y de la evaluación del 44 %.

La de la evaluación que no puede faltar es la guarda: si el archivo de juicios
deja de reproducir 22 de 50, la comparación ya no es la del 11-sep y se aborta
en vez de reportar una cifra que parece comparable y no lo es.

Datos sintéticos; nada del laboratorio.

    python -m unittest discover .
"""

import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import operones   # noqa: E402
from grn_verificacion import capa, evaluar   # noqa: E402

ETIQUETAS = ["activates", "no_relation", "regulates", "represses"]


def _pred(id_par, clase, p=0.8):
    d = {"id_par": id_par, "prediccion": clase}
    resto = (1.0 - p) / 3
    for e in ETIQUETAS:
        d["p_" + e] = p if e == clase else resto
    return d


def _par(id_par, tf_id="mexT", target_id="mexE", target_locus=("PA2493",),
         pmid=1, num=0):
    return {"id_par": id_par, "pmid": pmid, "fuente_texto": "xml",
            "seccion": "results", "num_oracion": num,
            "oracion_cruda": "MexT activates mexE.", "tf": "MexT",
            "target": target_id, "tf_id": tf_id, "target_id": target_id,
            "tf_locus": ["PA2492"], "target_locus": list(target_locus),
            "mencion_tf": "MexT", "mencion_target": target_id,
            "target_es_tf": False, "autorregulacion": False,
            "redaccion": "directa", "distancia": 10,
            "par_del_bronce": "directo", "corrida_bronce": 4}


def _candidata(pmid=1, num=0):
    return {"pmid": str(pmid), "fuente_texto": "xml", "num_oracion": str(num),
            "doi": "", "anio": "2020", "revista": "J", "titulo": "T",
            "genes": "mexT;mexE", "funciones_biologicas": "efflux",
            "hay_operon": "si", "operones_en_oracion": "mexEF-oprN",
            "signo_sugerido": "+"}


class PruebasCapa(unittest.TestCase):

    def setUp(self):
        filas = [{"clave_genes": "PA2493|PA2494|PA2495", "nombre": "mexEF-oprN",
                  "locus_tags": "PA2493|PA2494|PA2495",
                  "genes": "mexE mexF oprN", "nivel_evidencia": "conocido",
                  "es_alternativa": "no", "monocistronico": "no"}]
        self.base = operones.BaseOperones(filas, presente=True)
        self.locus = {"mexT": "PA2492", "mexE": "PA2493", "PA2493": "PA2493"}

    def test_una_fila_por_par_con_oracion_operones_y_biobert(self):
        filas = capa.filas_capa([_candidata()], [_par("a")],
                                {"a": _pred("a", "activates")}, set(),
                                self.base, self.locus)
        self.assertEqual(len(filas), 1)
        f = filas[0]
        self.assertEqual(f["funciones_biologicas"], "efflux")
        self.assertEqual(f["operones_del_blanco"], "mexEF-oprN")
        self.assertEqual(f["blanco_es_operon"], "no")
        self.assertEqual(f["pasa_umbral"], "si")
        self.assertEqual(f["signo_biobert"], "+")
        self.assertEqual(f["origen_prediccion"], "reutilizada")
        self.assertEqual(f["direccion_sintaxis"], "")
        self.assertEqual(list(f.keys()), capa.COLUMNAS_CAPA)

    def test_el_umbral_es_por_clase(self):
        """represses pide 0.70: con 0.68 no pasa aunque activates pasaría."""
        filas = capa.filas_capa([_candidata()], [_par("a")],
                                {"a": _pred("a", "represses", 0.68)}, {"a"},
                                self.base, self.locus)
        self.assertEqual(filas[0]["pasa_umbral"], "no")
        self.assertEqual(filas[0]["origen_prediccion"], "nueva")

    def test_no_relation_nunca_pasa(self):
        filas = capa.filas_capa([_candidata()], [_par("a")],
                                {"a": _pred("a", "no_relation", 0.99)}, set(),
                                self.base, self.locus)
        self.assertEqual(filas[0]["pasa_umbral"], "no")
        self.assertEqual(filas[0]["signo_biobert"], "")

    def test_sin_base_de_operones_la_columna_va_vacia(self):
        filas = capa.filas_capa([_candidata()], [_par("a")],
                                {"a": _pred("a", "activates")}, set(),
                                operones.BaseOperones(), self.locus)
        self.assertEqual(filas[0]["operones_del_blanco"], "")

    def test_un_blanco_que_no_es_gen_del_diccionario_es_operon(self):
        self.assertTrue(capa.es_operon("exoSTY", self.locus))
        self.assertFalse(capa.es_operon("mexE", self.locus))
        self.assertFalse(capa.es_operon("PA9999", self.locus))

    def test_direccion_de_la_sintaxis(self):
        self.assertEqual(capa.direccion(None, "a", "b"), "sin_dato")
        self.assertEqual(capa.direccion({"regulador_sintactico": "a"},
                                        "a", "b"), "concuerda")
        self.assertEqual(capa.direccion({"regulador_sintactico": "b"},
                                        "a", "b"), "inversa")
        self.assertEqual(capa.direccion({"regulador_sintactico": ""},
                                        "a", "b"), "sin_orientar")

    def test_la_sintaxis_se_une_por_par_no_ordenado(self):
        sint = {("1", "xml", "0", frozenset(("mexT", "mexE"))):
                {"regulador_sintactico": "mexE", "voz": "pasiva",
                 "negada": False, "signo_dominante": "-"}}
        filas = capa.filas_capa([_candidata()], [_par("a")],
                                {"a": _pred("a", "activates")}, set(),
                                self.base, self.locus, sint)
        self.assertEqual(filas[0]["direccion_sintaxis"], "inversa")
        self.assertEqual(filas[0]["voz"], "pasiva")


def _juicios(si=22, no=24, dudoso=4):
    filas = []
    rel = ["si"] * si + ["no"] * no + ["dudoso"] * dudoso
    for i, r in enumerate(rel):
        filas.append({"_linea": i + 2, "pmid": str(100 + i),
                      "oracion": "Oración %d." % i, "regulador": "rA",
                      "blanco": "rB", "relacion": r,
                      "signo_correcto": "+" if r == "si" and i % 2 == 0
                      else ("-" if r == "si" else "")})
    return filas


def _unidas(juicios, pasa=lambda j: True, clase="activates", direccion=""):
    return dict((j["_linea"], {"pasa_umbral": "si" if pasa(j) else "no",
                               "prediccion": clase if pasa(j)
                               else "no_relation",
                               "signo_sugerido": "+",
                               "direccion_sintaxis": direccion})
                for j in juicios)


class PruebasControlLexico(unittest.TestCase):
    """Punto 18: el signo del disparador CON SIGNO más cercano."""

    class _Vocab(object):
        def __init__(self, disparadores):
            self.disparadores = disparadores

        def disparadores_en(self, oracion):
            return self.disparadores

    def test_un_interrogacion_cercano_no_le_gana_a_un_signo_lejano(self):
        """Así estaba la primera medición: un «regulates» junto al par le
        ganaba a un «represses» más lejos."""
        oracion = "QzaR regulates wvaA, which in turn represses the operon."
        fila = {"oracion": oracion, "mencion_tf": "QzaR",
                "mencion_target": "wvaA"}
        vocab = self._Vocab([(5, 14, "regulates", "?"),
                             (36, 45, "represses", "-")])
        self.assertEqual(evaluar._signo_cercano(fila, vocab), "-")

    def test_sin_disparadores_con_signo_no_hay_signo(self):
        fila = {"oracion": "QzaR regulates wvaA.", "mencion_tf": "QzaR",
                "mencion_target": "wvaA"}
        vocab = self._Vocab([(5, 14, "regulates", "?")])
        self.assertEqual(evaluar._signo_cercano(fila, vocab), "")

    def test_gana_el_mas_cercano_al_tramo(self):
        oracion = "Upon induction QzaR activates wvaA but represses wvbA."
        fila = {"oracion": oracion, "mencion_tf": "QzaR",
                "mencion_target": "wvaA"}
        vocab = self._Vocab([(20, 29, "activates", "+"),
                             (39, 48, "represses", "-")])
        self.assertEqual(evaluar._signo_cercano(fila, vocab), "+")


class PruebasCapaExigeLasPrediccionesDeEsosPares(unittest.TestCase):

    def test_predicciones_de_otro_pares_jsonl_se_rechazan(self):
        """La capa une por `id_par`, que no depende del texto marcado: con un
        `--pasos pares,capa` que se saltara biobert, un re-marcado se llevaba
        la predicción del texto viejo."""
        import json
        import tempfile
        from grn_comun import procedencia
        with tempfile.TemporaryDirectory() as carpeta:
            pares = os.path.join(carpeta, "pares.jsonl")
            with open(pares, "w", encoding="utf-8") as f:
                f.write('{"id_par": "a", "text": "nuevo"}\n')
            with open(os.path.join(carpeta, "predicciones.jsonl"), "w",
                      encoding="utf-8") as f:
                f.write('{"id_par": "a"}\n')
            meta = os.path.join(carpeta, "predicciones_meta.json")
            with open(meta, "w", encoding="utf-8") as f:
                json.dump({"huella_pares": "0" * 16}, f)
            with self.assertRaises(ValueError) as ctx:
                capa.escribir_capa(carpeta, os.path.join(carpeta, "no.csv"))
            self.assertIn("biobert", str(ctx.exception))
            # Con la huella correcta pasa la guarda (y falla después, por el
            # CSV del bronce que no existe: ya no es la guarda).
            with open(meta, "w", encoding="utf-8") as f:
                json.dump({"huella_pares": procedencia.huella(pares)}, f)
            with self.assertRaises(OSError):
                capa.escribir_capa(carpeta, os.path.join(carpeta, "no.csv"))


class PruebasEvaluacion(unittest.TestCase):

    def test_p0_reproduce_el_44(self):
        j = _juicios()
        r = evaluar.evaluar(j, _unidas(j))
        self.assertEqual((r["P0_bronce"]["k"], r["P0_bronce"]["n"]), (22, 50))
        self.assertAlmostEqual(r["P0_bronce"]["valor"], 0.44)

    def test_si_los_juicios_cambian_se_aborta(self):
        j = _juicios(si=21, no=25)
        with self.assertRaises(evaluar.ErrorEvaluacion):
            evaluar.evaluar(j, _unidas(j))

    def test_los_dudosos_cuentan_en_el_denominador(self):
        j = _juicios()
        # BioBERT retiene solo las `si` y las `dudoso`.
        r = evaluar.evaluar(j, _unidas(j, pasa=lambda x: x["relacion"]
                                       in ("si", "dudoso")))
        p1 = r["P1_bronce_y_biobert_con_umbral"]
        self.assertEqual((p1["k"], p1["n"]), (22, 26))
        self.assertEqual(r["R1_retencion_de_las_si"]["k"], 22)
        self.assertEqual(r["E1_no_descartadas"]["k"], 24)

    def test_la_sensibilidad_pasa_14_y_27_a_no(self):
        j = _juicios()
        r = evaluar.evaluar(j, _unidas(j))
        sens = r["sensibilidad_14_y_27_a_no"]["P0"]
        # Bajan tantas como `si` haya entre las líneas 14 y 27.
        cambian = sum(1 for x in j if x["_linea"] in (14, 27)
                      and x["relacion"] == "si")
        self.assertGreater(cambian, 0)
        self.assertEqual(sens["k"], 22 - cambian)

    def test_signo_con_cobertura_y_linea_base(self):
        j = _juicios()
        r = evaluar.evaluar(j, _unidas(j, clase="activates"))
        s1 = r["S1_signo"]
        self.assertEqual(s1["filas_con_signo_claro"], 22)
        self.assertEqual(s1["biobert"]["cubiertas"], 22)
        self.assertEqual(s1["biobert"]["acierto"]["k"], 11)

    def test_la_direccion_solo_aparece_si_hubo_sintaxis(self):
        j = _juicios()
        self.assertNotIn("D_direccion_sintaxis",
                         evaluar.evaluar(j, _unidas(j)))
        r = evaluar.evaluar(j, _unidas(j, direccion="concuerda"), True)
        d = r["D_direccion_sintaxis"]
        self.assertEqual(d["D2_si_que_se_romperian"]["k"], 0)
        self.assertEqual(d["D2_si_que_concuerdan"]["k"], 22)

    def test_categorias_del_disparador_dominante(self):
        self.assertEqual(evaluar._categoria(["+"]), "unico")
        self.assertEqual(evaluar._categoria(["+", "?"]), "mezcla")
        self.assertEqual(evaluar._categoria(["+", "-"]), "contradictorio")
        self.assertEqual(evaluar._categoria(["?"]), "solo_interrogacion")
        self.assertEqual(evaluar._categoria(["", ""]), "sin_disparador")

    def test_proporcion_con_n_cero(self):
        self.assertIsNone(evaluar.proporcion(0, 0)["valor"])


if __name__ == "__main__":
    unittest.main()
