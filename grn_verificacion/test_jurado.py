"""El jurado: la regla de votos, la anotación que escribe y el barrido del
umbral con sus dos métricas. Todo con una hoja, unos jurados, un experto y
una llave inventados: las cifras esperadas salen a mano en los comentarios.

    python -m unittest grn_verificacion.test_jurado
"""

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import unittest

from grn_verificacion import cli, jurado, precision_ciega
from grn_verificacion.muestra import COLUMNAS_HOJA

ORACIONES = {
    "m-4001": ("GenA activates genB in this made-up line.", "GenA", "genB"),
    "m-4002": ("genD is activated by GenC, we invent.", "GenC", "genD"),
    "m-4003": ("GenE and genF appear in a made-up list.", "GenE", "genF"),
    "m-4004": ("GenG may control genH, we suppose.", "GenG", "genH"),
    "m-4005": ("GenI turns on genJ in a fake strain.", "GenI", "genJ"),
    "m-4006": ("GenK sits next to genL, made up.", "GenK", "genL"),
}
BRONCE = {"m-4001": "1>2", "m-4002": "1>2", "m-4003": "2>1",
          "m-4004": "1>2", "m-4005": "1>2", "m-4006": "1>2"}


def si(direccion, signo="+", tipo="no_se", especulativa="no"):
    return {"relacion": "si", "direccion": direccion, "signo": signo,
            "tipo": tipo, "negada": "no", "especulativa": especulativa}


def no(negada="no"):
    return {"relacion": "no", "direccion": "ninguna", "signo": "",
            "tipo": "", "negada": negada, "especulativa": "no"}


def dudoso(direccion="1>2"):
    return {"relacion": "dudoso", "direccion": direccion, "signo": "?",
            "tipo": "no_se", "negada": "no", "especulativa": "si",
            "comentario": "F8"}


ABST = {}

# Tres jurados; ver el docstring de `PruebasBarrido` para las cuentas.
JURADOS = [
    {"m-4001": si("1>2"), "m-4002": si("2>1"), "m-4003": si("2>1"),
     "m-4004": dudoso(), "m-4005": si("1>2"), "m-4006": ABST},
    {"m-4001": si("1>2", "-"), "m-4002": si("2>1"), "m-4003": no(),
     "m-4004": dudoso(), "m-4005": si("2>1"), "m-4006": ABST},
    {"m-4001": no(), "m-4002": si("1>2"), "m-4003": no(),
     "m-4004": no(), "m-4005": ABST, "m-4006": ABST},
]
EXPERTO = {"m-4001": si("1>2"), "m-4002": si("2>1"), "m-4003": no(),
           "m-4004": dudoso(), "m-4005": si("1>2"), "m-4006": ABST}


def escribir(ruta, valores):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_HOJA)
        w.writeheader()
        for id_item, (oracion, e1, e2) in ORACIONES.items():
            fila = dict.fromkeys(COLUMNAS_HOJA, "")
            fila.update(id_item=id_item, oracion=oracion, entidad_1=e1,
                        entidad_2=e2)
            fila.update(valores.get(id_item, {}))
            w.writerow(fila)


def escribir_llave(ruta):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id_item", "direccion_bronce",
                                          "id_par"])
        w.writeheader()
        for id_item, d in BRONCE.items():
            w.writerow({"id_item": id_item, "direccion_bronce": d,
                        "id_par": "par-secreto"})


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.rutas = []
        for i, valores in enumerate(JURADOS, 1):
            carpeta = os.path.join(self.tmp, "salidas", "ouroboros",
                                   "j%d" % i)
            os.makedirs(carpeta)
            ruta = os.path.join(carpeta, "anotaciones.csv")
            escribir(ruta, valores)
            self.rutas.append(ruta)
        self.experto = os.path.join(self.tmp, "experto.csv")
        escribir(self.experto, EXPERTO)
        self.llave = os.path.join(self.tmp, "llave.csv")
        escribir_llave(self.llave)
        self.salida = os.path.join(self.tmp, "salidas", "ouroboros", "jur")

    def sin_contenido(self, texto):
        for id_item, (oracion, _e1, _e2) in ORACIONES.items():
            self.assertNotIn(oracion, texto)
            self.assertNotIn(id_item, texto)
        self.assertNotIn("par-secreto", texto)


class PruebasVotos(unittest.TestCase):

    def votos(self, *filas):
        return [jurado._valores(f) for f in filas]

    def test_si_con_el_umbral_y_la_direccion_de_la_mayoria(self):
        votos = self.votos(si("2>1", "-"), si("2>1", "-"), si("1>2"))
        fila, cuenta = jurado.votar(votos, 2)
        self.assertEqual((fila["relacion"], fila["direccion"], fila["signo"],
                          fila["negada"]), ("si", "2>1", "-", "no"))
        self.assertEqual(cuenta["si"], 3)
        self.assertIn("jurado 2 de 3: si 3", fila["comentario"])

    def test_empate_en_la_direccion_es_dudoso(self):
        fila, _ = jurado.votar(self.votos(si("1>2"), si("2>1"), no()), 2)
        self.assertEqual((fila["relacion"], fila["direccion"]),
                         ("dudoso", "1>2"))
        self.assertIn("empate en la dirección", fila["comentario"])

    def test_bajo_el_umbral(self):
        fila, _ = jurado.votar(self.votos(si("1>2"), si("1>2"), no()), 3)
        self.assertEqual((fila["relacion"], fila["direccion"], fila["signo"],
                          fila["tipo"]), ("no", "ninguna", "", ""))
        fila, _ = jurado.votar(self.votos(si("1>2"), dudoso("2>1"),
                                          dudoso("2>1")), 2)
        self.assertEqual((fila["relacion"], fila["direccion"],
                          fila["especulativa"]), ("dudoso", "2>1", "si"))

    def test_la_abstencion_no_vota(self):
        fila, cuenta = jurado.votar(self.votos(ABST, ABST, si("1>2")), 1)
        self.assertEqual(fila["relacion"], "si")
        self.assertEqual(cuenta["abstencion"], 2)
        fila, _ = jurado.votar(self.votos(ABST, ABST, ABST), 1)
        self.assertEqual(set(fila.values()), {""})

    def test_empate_en_un_campo_da_el_neutro(self):
        fila, _ = jurado.votar(self.votos(si("1>2", "+", "directa"),
                                          si("1>2", "-", "indirecta")), 2)
        self.assertEqual((fila["signo"], fila["tipo"]), ("?", "no_se"))

    def test_el_umbral_va_de_1_a_n(self):
        for malo in (0, 4, True, "2"):
            with self.assertRaises(jurado.ErrorJurado, msg=repr(malo)):
                jurado.agregar([{}, {}, {}], [], malo)


class PruebasAnotacion(Base):

    def test_escribe_la_hoja_y_el_informe(self):
        informe = jurado.ejecutar(self.rutas, 2, self.salida)
        self.assertEqual(informe["conteos"], {"items": 6, "si": 2, "no": 1,
                                              "dudoso": 2, "abstencion": 1})
        ruta = os.path.join(self.salida, jurado.ANOTACIONES)
        anotacion = precision_ciega.leer_anotacion(ruta)
        self.assertEqual(anotacion["m-4002"]["direccion"], "2>1")
        # Ninguna combinación que la rúbrica no admita.
        self.assertEqual(sum(precision_ciega.avisos_de_rubrica(
            anotacion).values()), 0)
        with io.open(os.path.join(self.salida, jurado.INFORME),
                     encoding="utf-8") as f:
            texto = f.read()
        self.sin_contenido(texto)
        self.assertEqual(json.loads(texto)["jurados"][0]["archivo"],
                         "j1/anotaciones.csv")
        with io.open(ruta, "rb") as f:
            self.assertTrue(f.read().startswith(b"\xef\xbb\xbf"))

    def test_otra_hoja_no_pasa(self):
        otra = dict(JURADOS[1])
        otra.pop("m-4006")
        ruta = os.path.join(self.tmp, "otra.csv")
        with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS_HOJA)
            w.writeheader()
            for id_item, (oracion, e1, e2) in ORACIONES.items():
                if id_item == "m-4006":
                    continue
                if id_item == "m-4001":
                    oracion = "Una oración distinta."
                fila = dict.fromkeys(COLUMNAS_HOJA, "")
                fila.update(id_item=id_item, oracion=oracion, entidad_1=e1,
                            entidad_2=e2)
                fila.update(otra.get(id_item, {}))
                w.writerow(fila)
        with self.assertRaises(jurado.ErrorJurado) as caja:
            jurado.leer_jurados([self.rutas[0], ruta])
        mensaje = str(caja.exception)
        self.assertIn("1 ítems de menos, 0 de más y 1 con otra oración",
                      mensaje)
        self.assertNotIn("distinta", mensaje)

    def test_uno_solo_no_es_jurado(self):
        with self.assertRaises(jurado.ErrorJurado):
            jurado.leer_jurados(self.rutas[:1])

    def test_nunca_en_la_carpeta_del_experto(self):
        for mala in (os.path.join(self.tmp, "salidas", "revision", "x"),
                     os.path.join(self.tmp, "Salidas", "Revision", "x")
                     if os.name == "nt" else
                     os.path.join(self.tmp, "salidas", "revision", "y")):
            with self.assertRaises(jurado.ErrorJurado):
                jurado.ejecutar(self.rutas, 2, mala)
            self.assertFalse(os.path.exists(mala))


class PruebasBarrido(Base):
    """Las cuentas, sobre los cinco ítems que anotó el experto:

    - umbral 1: el jurado dice si en m-4001 (1>2), m-4002 (2>1, al revés
      del bronce) y m-4003 (2>1). Con la dirección del bronce acepta m-4001
      y m-4003, y acierta m-4001: 1/2; retiene 1 de los 2 verdaderos
      (m-4001 y m-4005). Con reorientación acepta los tres y acierta m-4001
      y m-4002: 2/3; retiene 2 de los 3 si del experto.
    - umbral 2: si en m-4001 y m-4002 (m-4005 empata la dirección y queda
      dudoso): bronce 1/1, retiene 1/2; reorientado 2/2, retiene 2/3.
    - umbral 3: si solo en m-4002: bronce 0/0, retiene 0/2; reorientado
      1/1, retiene 1/3.
    """

    def test_las_dos_metricas_por_umbral(self):
        r = jurado.barrer(self.rutas, self.experto, self.llave,
                          retencion_minima=0.5)
        cifras = dict(
            (m["umbral"], (
                (m["filtro_bronce"]["precision"]["k"],
                 m["filtro_bronce"]["precision"]["n"]),
                (m["filtro_bronce"]["retencion"]["k"],
                 m["filtro_bronce"]["retencion"]["n"]),
                (m["filtro_reorientado"]["precision"]["k"],
                 m["filtro_reorientado"]["precision"]["n"]),
                (m["filtro_reorientado"]["retencion_de_los_si_del_experto"]
                 ["k"],
                 m["filtro_reorientado"]["retencion_de_los_si_del_experto"]
                 ["n"])))
            for m in r["por_umbral"])
        self.assertEqual(cifras, {
            1: ((1, 2), (1, 2), (2, 3), (2, 3)),
            2: ((1, 1), (1, 2), (2, 2), (2, 3)),
            3: ((0, 0), (0, 2), (1, 1), (1, 3)),
        })
        self.assertEqual(r["por_umbral"][0]["reorientacion"],
                         {"aceptadas_al_reves_del_bronce": 1,
                          "de_ellas_correctas": 1})
        self.assertEqual(r["elegido"], {"filtro_bronce": 2,
                                        "filtro_reorientado": 2})
        self.assertEqual(len(r["individuales"]), 3)
        # El jurado 1 solo: si en m-4001, m-4002, m-4003 y m-4005.
        uno = r["individuales"][0]["filtro_reorientado"]
        self.assertEqual((uno["precision"]["k"], uno["precision"]["n"]),
                         (3, 4))

    def test_la_metrica_del_bronce_es_la_de_concordancia(self):
        r = jurado.barrer(self.rutas, self.experto, self.llave)
        from grn_verificacion import concordancia
        directo = concordancia.calcular(self.experto, self.rutas[0],
                                        self.llave)["filtro"]
        self.assertEqual(r["individuales"][0]["filtro_bronce"]["precision"],
                         directo["filtro_precision_con_direccion"])

    def test_sin_quien_retenga_lo_pedido(self):
        r = jurado.barrer(self.rutas, self.experto, self.llave,
                          retencion_minima=0.9)
        self.assertEqual(r["elegido"], {"filtro_bronce": None,
                                        "filtro_reorientado": None})


class PruebasCli(Base):

    def correr(self, *argv):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cli.main(list(argv))
        return codigo, salida.getvalue()

    def modelos(self):
        argumentos = []
        for ruta in self.rutas:
            argumentos += ["--modelo", ruta]
        return argumentos

    def test_jurado(self):
        codigo, texto = self.correr("jurado", *self.modelos(), "--umbral",
                                    "2", "--salida", self.salida)
        self.assertEqual(codigo, 0, texto)
        self.assertIn("Jurado de 3 con umbral 2: 6 ítems, si 2", texto)
        self.sin_contenido(texto)

    def test_jurado_con_un_umbral_imposible(self):
        codigo, texto = self.correr("jurado", *self.modelos(), "--umbral",
                                    "4", "--salida", self.salida)
        self.assertEqual(codigo, 1)
        self.assertIn("El umbral va de 1 a 3", texto)

    def test_barrido_solo_da_conteos(self):
        ruta_json = os.path.join(self.tmp, "barrido.json")
        codigo, texto = self.correr("jurado-barrido", *self.modelos(),
                                    "--experto", self.experto, "--llave",
                                    self.llave, "--retencion-minima", "0.5",
                                    "--json", ruta_json)
        self.assertEqual(codigo, 0, texto)
        self.assertIn("umbral 2 de 3", texto)
        self.assertIn("con reorientación:           precisión 2/2", texto)
        self.assertIn("reteniendo al menos 50 %, con reorientación: umbral 2",
                      texto)
        self.sin_contenido(texto)
        with io.open(ruta_json, encoding="utf-8") as f:
            self.sin_contenido(f.read())


if __name__ == "__main__":
    unittest.main()
