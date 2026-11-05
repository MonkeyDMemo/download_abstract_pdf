"""El costo y el tope de gasto: precios, la reserva antes de cada llamada,
el tope que no se rehabilita, y una corrida que se detiene antes de pasarlo
y se retoma sin pagar lo hecho. Con un anotador falso que reporta tokens: ni
Strands ni red.

    python -m unittest grn_ouroboros.test_gasto
"""

import io
import json
import os
import shutil
import tempfile
import threading
import unittest

from grn_ouroboros import anotar, gasto
from grn_ouroboros.test_anotar import (DESCRIPCION, ORACIONES, AnotadorFalso,
                                       _entradas, _escribir_hoja, _json)

PRECIO = (0.15, 0.60)


def _con_uso(texto, entrada=1000, salida=500):
    return {"texto": texto, "done_reason": "stop", "truncado": False,
            "uso": {"entrada": entrada, "salida": salida}}


class PruebasPrecios(unittest.TestCase):

    def test_la_tabla_y_los_perfiles(self):
        self.assertEqual(gasto.precio("openai.gpt-oss-120b-1:0"), PRECIO)
        self.assertEqual(gasto.precio("us.openai.gpt-oss-20b-1:0"),
                         (0.07, 0.30))
        self.assertEqual(gasto.precio("qwen.qwen3-235b-a22b-2507-v1:0"),
                         (0.22, 0.88))
        self.assertIsNone(gasto.precio("qwen.qwen3-32b-v1:0"))
        self.assertIsNone(gasto.precio(None))

    def test_los_precios_dados_ganan(self):
        self.assertEqual(gasto.precio("qwen.qwen3-32b-v1:0", "0.15,0.6"),
                         (0.15, 0.6))
        for malo in ("1", "a,b", "-1,2", "1,2,3", ""):
            with self.assertRaises(ValueError, msg=malo):
                gasto.validar_precios(malo)

    def test_el_costo(self):
        self.assertAlmostEqual(
            gasto.costo({"entrada": 1000000, "salida": 1000000}, PRECIO),
            0.75)
        self.assertEqual(gasto.costo(None, PRECIO), 0.0)
        self.assertEqual(gasto.sumar_uso([{"uso": {"entrada": 3,
                                                   "salida": 4}},
                                          {"abstencion": True}]),
                         {"entrada": 3, "salida": 4, "con_uso": 1})

    def test_la_cota_es_holgada(self):
        """2 caracteres por token y la salida entera."""
        maximo = gasto.maximo_por_llamada(4000, 4096, PRECIO)
        self.assertAlmostEqual(maximo, (2001 * 0.15 + 4096 * 0.60) / 1e6)


class PruebasTope(unittest.TestCase):

    def test_reserva_y_libera(self):
        tope = gasto.Tope(0.01, PRECIO)
        tope.reservar(0.004)
        tope.reservar(0.004)
        with self.assertRaises(gasto.TopeAlcanzado):
            tope.reservar(0.004)
        tope.liberar(0.004, {"entrada": 1000, "salida": 1000})
        self.assertAlmostEqual(tope.gastado, 0.00075)
        # Agotado no se rehabilita aunque se libere una reserva.
        with self.assertRaises(gasto.TopeAlcanzado):
            tope.reservar(0.0001)

    def test_tope_invalido(self):
        for malo in (0, -1, None):
            with self.assertRaises(ValueError):
                gasto.Tope(malo, PRECIO)

    def test_con_tope_no_llama_si_no_cabe(self):
        llamadas = []

        def anotador(item):
            llamadas.append(item)
            return _con_uso("{}", 1000, 1000)

        # Cada reserva: (51 x 0.15 + 4096 x 0.60) / 1e6 = 0.00246 USD; la
        # primera cuesta 0.00075, y la segunda reserva ya no cabe en 0.003.
        tope = gasto.Tope(0.003, PRECIO)
        envuelto = gasto.con_tope(anotador, tope, lambda item: 100, 4096)
        envuelto({"id_item": "a"})
        with self.assertRaises(gasto.TopeAlcanzado):
            envuelto({"id_item": "b"})
        self.assertEqual(len(llamadas), 1)
        self.assertLessEqual(tope.gastado, tope.usd)

    def test_si_la_llamada_falla_no_se_cobra(self):
        def anotador(_item):
            raise RuntimeError("se cayó")

        tope = gasto.Tope(1.0, PRECIO)
        envuelto = gasto.con_tope(anotador, tope, lambda item: 100, 512)
        with self.assertRaises(RuntimeError):
            envuelto({"id_item": "a"})
        self.assertEqual((tope.gastado, tope.reservado), (0.0, 0.0))

    def test_entre_hilos_no_pasa_del_tope(self):
        def anotador(_item):
            return _con_uso("{}", 2000, 4096)

        tope = gasto.Tope(0.02, PRECIO)
        envuelto = gasto.con_tope(anotador, tope, lambda item: 4000, 4096)
        errores = []

        def correr():
            for _ in range(20):
                try:
                    envuelto({})
                except gasto.TopeAlcanzado:
                    errores.append(1)
                    return

        hilos = [threading.Thread(target=correr) for _ in range(8)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
        self.assertLessEqual(tope.gastado, tope.usd)
        self.assertTrue(errores)


class PruebasCorridaConTope(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hoja = os.path.join(self.tmp, "hoja.csv")
        _escribir_hoja(self.hoja, ORACIONES)
        self.salida = os.path.join(self.tmp, "salida")
        self.respuestas = dict((i, _con_uso(_json("x"))) for i in ORACIONES)

    def correr(self, usd, paralelo=1):
        falso = AnotadorFalso(dict(self.respuestas))
        tope = gasto.Tope(usd, PRECIO)
        envuelto = gasto.con_tope(falso, tope, lambda item: 2000, 512)
        r = anotar.ejecutar(self.hoja, self.salida, envuelto, _entradas(),
                            descripcion=DESCRIPCION, paralelo=paralelo,
                            precio=PRECIO)
        return r, falso, tope

    def corrida(self):
        with io.open(os.path.join(self.salida, anotar.CORRIDA),
                     encoding="utf-8") as f:
            return json.load(f)

    def test_alcanza_y_corrida_json_lleva_el_costo(self):
        r, falso, tope = self.correr(1.0)
        self.assertEqual(len(falso.llamadas), 3)
        costo = r["resumen"]["costo"]
        # 3 x (1000 x 0.15 + 500 x 0.60) / 1e6
        self.assertAlmostEqual(costo["usd_total"], 0.00135)
        self.assertAlmostEqual(costo["usd_esta_corrida"], 0.00135)
        self.assertEqual(costo["precio_usd_por_millon"], [0.15, 0.60])
        self.assertEqual((r["resumen"]["conteos"]["tokens_entrada"],
                          r["resumen"]["conteos"]["tokens_salida"]),
                         (3000, 1500))
        self.assertAlmostEqual(tope.gastado, 0.00135)

    def test_se_detiene_y_retoma_sin_pagar_lo_hecho(self):
        # Cada reserva: 1001 x 0.15 + 512 x 0.60 = 0.000457 USD; caben dos.
        # En paralelo, cuál de los tres se queda fuera depende de los hilos:
        # se guarda lo anterior a él, como siempre.
        for paralelo in (1, 3):
            shutil.rmtree(self.salida, True)
            with self.assertRaises(gasto.TopeAlcanzado):
                self.correr(0.001, paralelo=paralelo)
            corrida = self.corrida()
            self.assertEqual(corrida["estatus"], "error")
            self.assertEqual(corrida["error"], "TopeAlcanzado")
            hechas = corrida["conteos"]["validas"]
            if paralelo == 1:
                self.assertEqual(hechas, 2)
            self.assertLessEqual(hechas, 2)
            r, falso, _tope = self.correr(1.0)
            self.assertEqual(len(falso.llamadas), 3 - hechas)
            self.assertEqual((r["resumen"]["nuevas"],
                              r["resumen"]["reutilizadas"]),
                             (3 - hechas, hechas))
            self.assertAlmostEqual(r["resumen"]["costo"]["usd_esta_corrida"],
                                   0.00045 * (3 - hechas))
            self.assertAlmostEqual(r["resumen"]["costo"]["usd_total"],
                                   0.00135)

    def test_sin_precio_no_hay_costo(self):
        falso = AnotadorFalso(dict(self.respuestas))
        r = anotar.ejecutar(self.hoja, self.salida, falso, _entradas(),
                            descripcion=DESCRIPCION)
        self.assertNotIn("costo", r["resumen"])
        # Los tokens sí, porque los veredictos los traen.
        self.assertEqual(r["resumen"]["conteos"]["tokens_salida"], 1500)


if __name__ == "__main__":
    unittest.main()
