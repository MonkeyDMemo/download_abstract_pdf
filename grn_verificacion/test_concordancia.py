"""El acuerdo de Ouroboros con el experto, con datos sintéticos: ni
oraciones del corpus, ni de las tandas, ni juicios del experto.

    python -m unittest grn_verificacion.test_concordancia
"""

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import unittest

from grn_verificacion import cli, concordancia as co

HOJA = ["id_item", "oracion", "entidad_1", "entidad_2", "relacion",
        "direccion", "signo", "tipo", "negada", "especulativa", "comentario"]
LLAVE = ["id_item", "tanda", "doble", "pmid", "fuente_texto", "num_oracion",
         "id_par", "regulador", "blanco", "direccion_bronce"]
NO = ("no", "ninguna", "", "", "no", "no")
VACIA = ("",) * 6

# (experto, modelo, dirección del bronce), con los seis campos cerrados en el
# orden de la hoja. El modelo se abstiene en m-3010; m-3011 el experto no lo
# anotó y no cuenta.
ITEMS = {
    "m-3001": (("si", "1>2", "+", "no_se", "no", "no"),
               ("si", "1>2", "+", "no_se", "no", "no"), "1>2"),
    "m-3002": (("si", "1>2", "-", "no_se", "no", "no"),
               ("si", "1>2", "-", "no_se", "no", "no"), "1>2"),
    "m-3003": (("si", "2>1", "+", "directa", "no", "no"),
               ("si", "2>1", "+", "no_se", "no", "no"), "1>2"),
    "m-3004": (("si", "1>2", "?", "no_se", "no", "no"),
               ("si", "2>1", "?", "no_se", "no", "no"), "1>2"),
    "m-3005": (("si", "1>2", "+", "no_se", "no", "no"), NO, "1>2"),
    "m-3006": (NO, NO, "1>2"),
    "m-3007": (NO, NO, "2>1"),
    "m-3008": (("no", "ninguna", "", "", "si", "no"),
               ("si", "1>2", "+", "no_se", "no", "no"), "1>2"),
    "m-3009": (("dudoso", "1>2", "?", "no_se", "no", "si"),
               ("dudoso", "1>2", "?", "no_se", "no", "si"), "1>2"),
    "m-3010": (("dudoso", "2>1", "?", "directa", "si", "no"), VACIA, "2>1"),
    "m-3011": (VACIA, ("si", "1>2", "+", "no_se", "no", "no"), "1>2"),
}

# La tabla de relación, filas el experto y columnas el modelo:
#
#              si   no   dudoso   abstención | total
#     si        4    1        0            0 |     5
#     no        1    2        0            0 |     3
#     dudoso    0    0        1            1 |     2
#     total     5    3        1            1 |    10
#
# acuerdo observado p_o = (4 + 2 + 1) / 10 = 0.7
# acuerdo esperado  p_e = 0.5 * 0.5 + 0.3 * 0.3 + 0.2 * 0.1 + 0 * 0.1 = 0.36
#                        (la abstención la usa solo el modelo: no suma)
# kappa = (0.7 - 0.36) / (1 - 0.36) = 0.34 / 0.64 = 0.53125
KAPPA_ITEMS = 0.53125


def _oracion(id_item):
    return "GenA%s activates genB%s in an invented sentence." % (
        id_item[-2:], id_item[-2:])


def _fila(id_item, valores, oracion=None):
    fila = dict(zip(HOJA[4:10], valores))
    fila.update(id_item=id_item, oracion=oracion or _oracion(id_item),
                entidad_1="GenA" + id_item[-2:],
                entidad_2="genB" + id_item[-2:], comentario="")
    return fila


def _escribir(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)


class PruebasKappa(unittest.TestCase):

    def test_el_ejemplo_de_dos_categorias(self):
        """50 propuestas leídas por dos personas: 20 sí-sí, 5 sí-no, 10
        no-sí y 15 no-no.

        p_o = (20 + 15) / 50 = 0.7
        p_e = (25/50)(30/50) + (25/50)(20/50) = 0.3 + 0.2 = 0.5
        kappa = (0.7 - 0.5) / (1 - 0.5) = 0.4
        """
        pares = ([("si", "si")] * 20 + [("si", "no")] * 5
                 + [("no", "si")] * 10 + [("no", "no")] * 15)
        self.assertAlmostEqual(co.kappa(pares), 0.4, places=4)

    def test_tres_categorias_y_la_abstencion(self):
        pares = [(e[0], m[0] if m[0] else co.ABSTENCION)
                 for e, m, _d in ITEMS.values() if e[0]]
        self.assertAlmostEqual(co.kappa(pares), KAPPA_ITEMS, places=3)

    def test_acuerdo_perfecto(self):
        self.assertEqual(co.kappa([("si", "si"), ("no", "no")]), 1.0)

    def test_no_definido(self):
        """Una sola categoría en los dos: p_e = 1."""
        self.assertIsNone(co.kappa([("si", "si")] * 3))
        self.assertIsNone(co.kappa([]))


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.experto = os.path.join(self.tmp, "experto.csv")
        self.modelo = os.path.join(self.tmp, "modelo.csv")
        self.llave = os.path.join(self.tmp, "llave.csv")
        self.escribir()

    def escribir(self, items=ITEMS, otra_oracion=None):
        _escribir(self.experto, HOJA,
                  [_fila(i, e) for i, (e, _m, _d) in items.items()])
        _escribir(self.modelo, HOJA,
                  [_fila(i, m, otra_oracion if i == "m-3001" else None)
                   for i, (_e, m, _d) in items.items()])
        _escribir(self.llave, LLAVE,
                  [{"id_item": i, "pmid": "999%s" % i[-2:],
                    "id_par": "par-%s" % i, "direccion_bronce": d}
                   for i, (_e, _m, d) in items.items()])


class PruebasAcuerdo(Base):

    def test_por_campo_sobre_lo_que_anoto_el_experto(self):
        r = co.calcular(self.experto, self.modelo)
        self.assertEqual(r["n_anotados_por_el_experto"], 10)
        self.assertEqual(r["n_sin_anotar_por_el_experto"], 1)
        k = dict((c, p["k"]) for c, p in r["acuerdo_por_campo"].items())
        self.assertEqual(k, {"relacion": 7, "direccion": 6, "signo": 7,
                             "tipo": 6, "negada": 8, "especulativa": 9})
        self.assertTrue(all(p["n"] == 10
                            for p in r["acuerdo_por_campo"].values()))
        self.assertAlmostEqual(r["kappa_relacion"], KAPPA_ITEMS, places=3)

    def test_las_matrices(self):
        r = co.calcular(self.experto, self.modelo)
        relacion = r["matrices"]["relacion"]
        self.assertEqual(list(relacion), ["si", "no", "dudoso"])
        self.assertEqual(dict(relacion["si"]), {"si": 4, "no": 1, "dudoso": 0,
                                                co.ABSTENCION: 0})
        self.assertEqual(relacion["dudoso"][co.ABSTENCION], 1)
        signo = r["matrices"]["signo"]
        self.assertEqual(list(signo), ["+", "-", "?", co.VACIO])
        self.assertEqual(signo["+"][co.VACIO], 1)          # m-3005
        self.assertEqual(signo[co.VACIO]["+"], 1)          # m-3008
        # Todas las celdas suman los ítems anotados, en cada campo.
        for campo, m in r["matrices"].items():
            self.assertEqual(sum(sum(f.values()) for f in m.values()), 10,
                             campo)

    def test_la_nota_del_tipo_en_la_tanda_1(self):
        lineas = []
        co.ejecutar(self.experto, self.modelo, log=lineas.append)
        self.assertTrue(any("tanda 1" in l and "directa" in l
                            for l in lineas))


class PruebasAbstencion(Base):
    """La abstención del modelo cuenta como error en todos los campos."""

    def test_un_no_con_abstencion(self):
        self.escribir({"m-3001": (NO, NO, "1>2"),
                       "m-3002": (NO, VACIA, "1>2")})
        r = co.calcular(self.experto, self.modelo)
        self.assertEqual(r["abstenciones_del_modelo"]["k"], 1)
        for campo, p in r["acuerdo_por_campo"].items():
            self.assertEqual((p["k"], p["n"]), (1, 2), campo)
        self.assertEqual(r["matrices"]["relacion"]["no"]["no"], 1)
        self.assertEqual(r["matrices"]["relacion"]["no"][co.ABSTENCION], 1)
        # Una sola categoría del experto, y la del modelo nunca coincide.
        self.assertEqual(r["kappa_relacion"], 0.0)

    def test_en_el_filtro_rechaza(self):
        self.escribir({"m-3001": (("si", "1>2", "+", "no_se", "no", "no"),
                                  VACIA, "1>2")})
        f = co.calcular(self.experto, self.modelo, self.llave)["filtro"]
        self.assertEqual(f["retencion_de_los_verdaderos"]["k"], 0)
        self.assertEqual(f["filtro_precision_con_direccion"]["n"], 0)

    def test_sin_relacion_pero_con_otros_valores_no_es_abstencion(self):
        self.escribir({"m-3001": (NO, ("", "", "", "", "no", "no"), "1>2")})
        with self.assertRaises(ValueError):
            co.calcular(self.experto, self.modelo)


class PruebasFiltro(Base):
    """acepta = relación si con la dirección del bronce.

    verdaderos (si con la dirección del bronce): m-3001, 3002, 3004, 3005
    aceptados: m-3001, 3002 y 3008 (el experto dice no)
    """

    def test_precision_retencion_y_diferencia(self):
        f = co.calcular(self.experto, self.modelo, self.llave)["filtro"]
        b = f["bronce_precision_con_direccion"]
        p = f["filtro_precision_con_direccion"]
        r = f["retencion_de_los_verdaderos"]
        self.assertEqual(((b["k"], b["n"]), (p["k"], p["n"]),
                          (r["k"], r["n"])), ((4, 10), (2, 3), (2, 4)))
        self.assertEqual(f["retencion_total"]["k"], 3)
        self.assertAlmostEqual(f["diferencia_filtro_menos_bronce"],
                               2 / 3.0 - 0.4, places=3)
        self.assertEqual(f["tabla"], {"falso|acepta": 1, "falso|rechaza": 5,
                                      "verdadero|acepta": 2,
                                      "verdadero|rechaza": 2})
        bajo, alto = f["diferencia_ic95"]
        self.assertLessEqual(bajo, alto)

    def test_el_bootstrap_es_reproducible(self):
        a = co.calcular(self.experto, self.modelo, self.llave)
        b = co.calcular(self.experto, self.modelo, self.llave)
        self.assertEqual(a["filtro"]["diferencia_ic95"],
                         b["filtro"]["diferencia_ic95"])

    def test_sin_llave_no_hay_filtro(self):
        self.assertIsNone(co.calcular(self.experto, self.modelo)["filtro"])

    def test_una_llave_de_otra_hoja(self):
        _escribir(self.llave, LLAVE, [{"id_item": "m-9999",
                                       "direccion_bronce": "1>2"}])
        with self.assertRaises(ValueError):
            co.calcular(self.experto, self.modelo, self.llave)


class PruebasMismaHoja(Base):

    def test_falta_un_item_del_experto(self):
        items = dict(ITEMS)
        _escribir(self.modelo, HOJA, [_fila(i, m) for i, (_e, m, _d)
                                      in items.items() if i != "m-3004"])
        with self.assertRaises(ValueError) as caja:
            co.calcular(self.experto, self.modelo)
        self.assertIn("1 ítems", str(caja.exception))

    def test_otra_oracion(self):
        self.escribir(otra_oracion="Una oración distinta, inventada.")
        with self.assertRaises(ValueError) as caja:
            co.calcular(self.experto, self.modelo)
        self.assertNotIn("distinta", str(caja.exception))

    def test_el_espaciado_no_cuenta(self):
        self.escribir(otra_oracion=_oracion("m-3001").replace(" ", "  "))
        self.assertEqual(
            co.calcular(self.experto, self.modelo)[
                "n_anotados_por_el_experto"], 10)


class PruebasSalida(Base):

    def test_solo_conteos_en_el_log_y_en_el_json(self):
        ruta_json = os.path.join(self.tmp, "concordancia.json")
        lineas = []
        co.ejecutar(self.experto, self.modelo, ruta_llave=self.llave,
                    ruta_json=ruta_json, log=lineas.append)
        with io.open(ruta_json, encoding="utf-8") as f:
            texto_json = f.read()
        json.loads(texto_json)
        for texto in (texto_json, "\n".join(lineas)):
            for id_item in ITEMS:
                self.assertNotIn(id_item, texto)
                self.assertNotIn(_oracion(id_item), texto)
                self.assertNotIn("999" + id_item[-2:], texto)   # el PMID
                self.assertNotIn("GenA" + id_item[-2:], texto)

    def test_el_subcomando(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cli.main(["concordancia", "--experto", self.experto,
                               "--modelo", self.modelo, "--llave",
                               self.llave])
        texto = salida.getvalue()
        self.assertEqual(codigo, 0)
        self.assertIn("kappa de Cohen en relación: 0.531", texto)
        self.assertIn("filtro, precisión con dirección:  2/3", texto)

    def test_el_subcomando_con_un_error(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cli.main(["concordancia", "--experto", self.experto,
                               "--modelo", os.path.join(self.tmp, "no.csv")])
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
