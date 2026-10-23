"""Pruebas de la precisión pareada sobre la muestra ciega, con datos
sintéticos: ni oraciones del corpus ni nada del laboratorio."""

import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from grn_verificacion import cli, precision_ciega as pc

HOJA = ["id_item", "oracion", "entidad_1", "entidad_2", "relacion",
        "direccion", "signo", "tipo", "negada", "especulativa", "comentario"]
LLAVE = ["id_item", "tanda", "doble", "pmid", "fuente_texto", "num_oracion",
         "id_par", "regulador", "blanco", "direccion_bronce"]

# (id_item, id_par, tf, blanco, signo_sugerido, en la red con signo)
ITEMS = [
    ("m-1001", "p1", "PA0001", "PA0002", "+", "activates"),
    ("m-1002", "p2", "PA0003", "PA0004", "?", "represses"),
    ("m-1003", "p3", "PA0005", "PA0006", "-", None),
    ("m-1004", "p4", "PA0007", "PA0008", "+;-", None),
    ("m-1005", "p5", "PA0009", "PA0010", "+", None),
]
# relacion, direccion, signo anotados; m-1005 queda sin anotar.
ANOTADO = {
    "m-1001": ("si", "1>2", "+"),
    "m-1002": ("no", "ninguna", ""),
    "m-1003": ("si", "2>1", "-"),
    "m-1004": ("dudoso", "1>2", "?"),
    "m-1005": ("", "", ""),
}


def _escribir(ruta, columnas, filas, delim=",", bom=True):
    with io.open(ruta, "w", encoding="utf-8-sig" if bom else "utf-8",
                 newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, delimiter=delim,
                           extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.carpeta = os.path.join(self.tmp, "corrida")
        os.makedirs(self.carpeta)
        _escribir(os.path.join(self.carpeta, "capa_pares.csv"),
                  ["id_par", "tf_id", "target_id", "signo_sugerido",
                   "oracion"],
                  [{"id_par": p, "tf_id": a, "target_id": b,
                    "signo_sugerido": s, "oracion": "Oración %s." % p}
                   for _, p, a, b, s, _ in ITEMS])
        # La red usa formas de presentación distintas de los ids: la arista
        # se reconoce por su evidencia, no por su nombre.
        red = [(a.lower(), b.lower(), r, p) for _, p, a, b, _, r in ITEMS if r]
        _escribir(os.path.join(self.carpeta, "red.tsv"),
                  ["tf", "blanco", "signo"],
                  [{"tf": t, "blanco": b, "signo": r} for t, b, r, _ in red],
                  delim="\t", bom=False)
        # La oración de la evidencia trae otro espaciado: se compara
        # normalizada, como la deduplica red.py.
        evidencias = [{"tf": t, "blanco": b, "id_par": p,
                       "oracion": "Oración  %s." % p} for t, b, _, p in red]
        # p5 está en la red por OTRA oración: su par es arista, pero la
        # oración del ítem no la sostiene.
        evidencias.append({"tf": "pa0009", "blanco": "pa0010",
                           "id_par": "p5", "oracion": "Otra oración."})
        _escribir(os.path.join(self.carpeta, "red_evidencias.tsv"),
                  ["tf", "blanco", "id_par", "oracion"], evidencias,
                  delim="\t", bom=False)
        self.llave = os.path.join(self.tmp, "llave.csv")
        _escribir(self.llave, LLAVE,
                  [{"id_item": i, "tanda": 1, "doble": "no", "id_par": p,
                    "direccion_bronce": "1>2"} for i, p, *_ in ITEMS])

    def anotacion(self, extra=None, cambios=None, columnas=HOJA):
        filas = []
        for i, *_ in ITEMS:
            rel, dire, signo = (cambios or {}).get(i, ANOTADO[i])
            fila = {"id_item": i, "oracion": "x", "entidad_1": "a",
                    "entidad_2": "b", "relacion": rel, "direccion": dire,
                    "signo": signo}
            fila.update((extra or {}).get(i, {}))
            filas.append(fila)
        ruta = os.path.join(self.tmp, "anotacion.csv")
        _escribir(ruta, columnas, filas)
        return ruta

    def calcular(self, **kw):
        return pc.calcular(self.anotacion(**kw), self.llave, self.carpeta)


class PruebasCifras(Base):

    def test_el_bronce_cuenta_dudoso_en_el_denominador(self):
        r = self.calcular()

        self.assertEqual(r["n_anotados"], 4)
        self.assertEqual(r["n_sin_anotar"], 1)
        self.assertEqual(r["bronce"]["con_direccion"]["k"], 1)
        self.assertEqual(r["bronce"]["con_direccion"]["n"], 4)

    def test_la_direccion_contraria_cuenta_solo_sin_direccion(self):
        r = self.calcular()

        self.assertEqual(r["bronce"]["sin_direccion"]["k"], 2)

    def test_la_red_se_mide_sobre_lo_que_retiene(self):
        r = self.calcular()

        self.assertEqual((r["red"]["con_direccion"]["k"],
                          r["red"]["con_direccion"]["n"]), (1, 2))
        self.assertEqual((r["retencion_de_la_red"]["total"]["k"],
                          r["retencion_de_la_red"]["total"]["n"]), (2, 4))
        self.assertEqual(r["retencion_de_la_red"]["de_los_verdaderos"]["k"], 1)
        self.assertEqual(r["pareado"]["tabla"],
                         {"bien|en_la_red": 1, "mal|en_la_red": 1,
                          "mal|fuera": 2})

    def test_retiene_por_oracion_y_no_por_par(self):
        r = self.calcular(cambios={"m-1005": ("si", "1>2", "+")})

        self.assertEqual(r["retencion_de_la_red"]["total"]["k"], 2)
        self.assertEqual(
            r["retencion_de_la_red"]["par_en_la_red_por_cualquier_oracion"]
            ["k"], 3)

    def test_la_abstencion_de_signo_cuenta_como_error(self):
        # m-1001 es el único `si` bien orientado con signo; si el bronce
        # sugiere `+;-`, no da signo y falla.
        r = self.calcular()
        self.assertEqual(r["bronce"]["signo"]["abstencion_es_error"]["k"], 1)

        with open(os.path.join(self.carpeta, "capa_pares.csv"), "rb") as f:
            texto = f.read().replace(b"p1,PA0001,PA0002,+", b"p1,PA0001,PA0002,+;-")
        with open(os.path.join(self.carpeta, "capa_pares.csv"), "wb") as f:
            f.write(texto)
        r = self.calcular()
        signo = r["bronce"]["signo"]
        self.assertEqual((signo["abstencion_es_error"]["k"],
                          signo["abstencion_es_error"]["n"]), (0, 1))
        self.assertEqual(signo["solo_comunes"]["n"], 0)

    def test_la_diferencia_pareada_lleva_intervalo(self):
        ic = self.calcular()["pareado"]["diferencia_red_menos_bronce_ic95"]
        self.assertEqual(len(ic), 2)
        self.assertLessEqual(ic[0], ic[1])


class PruebasEntrada(Base):

    def test_las_columnas_de_tiempo_se_leen_y_las_demas_se_ignoran(self):
        extra = dict((i, {"inicio": "2026-10-23T10:0%d:00" % n, "fin": "",
                          "segundos": "60", "otra": "z"})
                     for n, (i, *_) in enumerate(ITEMS))
        r = self.calcular(extra=extra,
                          columnas=HOJA + ["inicio", "fin", "segundos",
                                           "otra"])

        self.assertEqual(r["bronce"]["con_direccion"]["k"], 1)
        self.assertEqual(r["tiempo"]["items_con_tiempo"], 4)
        self.assertEqual(r["tiempo"]["minutos_total"], 4.0)

    def test_sin_tiempos_no_inventa_cifra(self):
        self.assertIsNone(self.calcular()["tiempo"])

    def test_un_valor_fuera_de_la_rubrica_detiene(self):
        with self.assertRaises(ValueError):
            self.calcular(cambios={"m-1001": ("sí", "1>2", "+")})

    def test_un_item_sin_llave_detiene(self):
        with io.open(self.llave, encoding="utf-8-sig") as f:
            lineas = f.read().splitlines()
        with io.open(self.llave, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(lineas[:-1]) + "\n")
        with self.assertRaises(ValueError):
            self.calcular()


class PruebasCli(Base):

    def test_escribe_el_json_y_solo_dice_cifras(self):
        destino = os.path.join(self.tmp, "r.json")
        lineas = []
        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main(["precision-ciega",
                               "--anotacion", self.anotacion(),
                               "--llave", self.llave,
                               "--carpeta", self.carpeta,
                               "--json", destino])
        self.assertEqual(codigo, 0)
        with io.open(destino, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["n_anotados"], 4)
        self.assertNotIn("PA0001", "\n".join(lineas))

    def test_un_error_sale_con_1(self):
        lineas = []
        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main(["precision-ciega", "--anotacion", "no-hay.csv",
                               "--llave", self.llave,
                               "--carpeta", self.carpeta])
        self.assertEqual(codigo, 1)


if __name__ == "__main__":
    unittest.main()
