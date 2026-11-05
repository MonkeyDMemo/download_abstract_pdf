# -*- coding: utf-8 -*-
"""El agente integrado al flujo: la hoja que juzga y la unión con la red."""

import csv
import io
import os
import tempfile
import unittest

from grn_verificacion import juez, muestra

ORACION_1 = "LasR directly activates lasB transcription."
ORACION_2 = "The lasB promoter is bound by LasR in vitro."
ORACION_3 = "RhlR represses phzA1 expression."


def _tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        e = csv.DictWriter(f, fieldnames=columnas, delimiter="\t",
                           lineterminator="\n")
        e.writeheader()
        e.writerows(filas)


def _csv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        e = csv.DictWriter(f, fieldnames=columnas, lineterminator="\n")
        e.writeheader()
        e.writerows(filas)


def _bytes(ruta):
    with open(ruta, "rb") as f:
        return f.read()


def _leer(ruta, delim=","):
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=delim))


class PruebasJuez(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.c = tmp.name
        _tsv(os.path.join(self.c, "red.tsv"),
             ["tf", "blanco", "signo", "n_articulos"],
             [{"tf": "LasR", "blanco": "lasB", "signo": "activates",
               "n_articulos": "2"},
              {"tf": "RhlR", "blanco": "phzA1", "signo": "represses",
               "n_articulos": "1"}])
        _tsv(os.path.join(self.c, "red_evidencias.tsv"),
             ["tf", "blanco", "id_par", "pmid", "fuente", "oracion"],
             [{"tf": "LasR", "blanco": "lasB", "id_par": "p1", "pmid": "1",
               "fuente": "abstract", "oracion": ORACION_1},
              {"tf": "LasR", "blanco": "lasB", "id_par": "p2", "pmid": "2",
               "fuente": "abstract", "oracion": ORACION_2},
              {"tf": "RhlR", "blanco": "phzA1", "id_par": "p3", "pmid": "3",
               "fuente": "abstract", "oracion": ORACION_3}])
        _csv(os.path.join(self.c, "capa_pares.csv"),
             ["id_par", "tf", "target", "mencion_tf", "mencion_target"],
             [{"id_par": "p1", "tf": "LasR", "target": "lasB",
               "mencion_tf": "LasR", "mencion_target": "lasB"},
              # La capa puede traer el par al revés: la mención sigue al gen.
              {"id_par": "p2", "tf": "lasB", "target": "LasR",
               "mencion_tf": "lasB", "mencion_target": "LasR"},
              {"id_par": "p3", "tf": "RhlR", "target": "phzA1",
               "mencion_tf": "RhlR", "mencion_target": "phzA1"}])
        self.red_antes = _bytes(os.path.join(self.c, "red.tsv"))

    def _anotar(self, valores):
        """Simula a Ouroboros: la hoja con los juicios, por id_item."""
        hoja = _leer(os.path.join(self.c, "juez", "hoja.csv"))
        for fila in hoja:
            fila.update(valores.get(fila["id_item"], {}))
        destino = os.path.join(self.c, "juez", "ouroboros")
        os.makedirs(destino)
        _csv(os.path.join(destino, "anotaciones.csv"), muestra.COLUMNAS_HOJA,
             hoja)

    def test_la_hoja_es_la_de_la_rubrica_y_en_blanco(self):
        self.assertEqual(juez.armar_hoja(self.c), 3)
        hoja = _leer(os.path.join(self.c, "juez", "hoja.csv"))
        self.assertEqual(list(hoja[0].keys()), muestra.COLUMNAS_HOJA)
        for fila in hoja:
            self.assertTrue(all(not fila[c] for c in muestra.COLUMNAS_HOJA[4:]))

    def test_la_entidad_1_es_la_que_aparece_primero(self):
        juez.armar_hoja(self.c)
        hoja = {f["oracion"]: f for f in
                _leer(os.path.join(self.c, "juez", "hoja.csv"))}
        llave = {f["id_item"]: f for f in
                 _leer(os.path.join(self.c, "juez", "llave.csv"))}
        h1, h2 = hoja[ORACION_1], hoja[ORACION_2]
        self.assertEqual((h1["entidad_1"], h1["entidad_2"]), ("LasR", "lasB"))
        self.assertEqual(llave[h1["id_item"]]["direccion_red"], "1>2")
        # En la segunda, lasB va primero: la red (LasR → lasB) es 2>1.
        self.assertEqual((h2["entidad_1"], h2["entidad_2"]), ("lasB", "LasR"))
        self.assertEqual(llave[h2["id_item"]]["direccion_red"], "2>1")

    def test_veredictos_por_oracion(self):
        v = juez.veredicto_oracion
        self.assertEqual(v({"relacion": "si", "direccion": "1>2"}, "1>2"),
                         "confirma")
        self.assertEqual(v({"relacion": "si", "direccion": "2>1"}, "1>2"),
                         "invierte")
        self.assertEqual(v({"relacion": "no"}, "1>2"), "rechaza")
        self.assertEqual(v({"relacion": "dudoso"}, "1>2"), "dudosa")
        self.assertEqual(v({"relacion": "si", "direccion": "ninguna"}, "1>2"),
                         "dudosa")
        self.assertEqual(v({}, "1>2"), "abstiene")

    def test_unir_marca_sin_tocar_la_red(self):
        juez.armar_hoja(self.c)
        llave = {(f["tf"], f["blanco"], f["id_par"]): f for f in
                 _leer(os.path.join(self.c, "juez", "llave.csv"))}
        i1 = llave[("LasR", "lasB", "p1")]["id_item"]
        i2 = llave[("LasR", "lasB", "p2")]["id_item"]
        i3 = llave[("RhlR", "phzA1", "p3")]["id_item"]
        self._anotar({
            i1: {"relacion": "no", "direccion": "ninguna"},
            # 2>1 es la dirección de la red en esta oración: confirma.
            i2: {"relacion": "si", "direccion": "2>1", "signo": "+"},
            i3: {"relacion": "si", "direccion": "2>1", "signo": "-"},
        })
        resumen = juez.unir(self.c)
        aristas = {(f["tf"], f["blanco"]): f for f in
                   _leer(os.path.join(self.c, "red_juez.tsv"), "\t")}
        lasb = aristas[("LasR", "lasB")]
        self.assertEqual(lasb["veredicto_agente"], "confirmada")
        self.assertEqual((lasb["n_confirma"], lasb["n_rechaza"]), ("1", "1"))
        self.assertEqual(lasb["signo_agente"], "+")
        self.assertEqual(aristas[("RhlR", "phzA1")]["veredicto_agente"],
                         "invertida")
        self.assertEqual(resumen["aristas_por_veredicto"]["confirmada"], 1)
        self.assertEqual(_bytes(os.path.join(self.c, "red.tsv")),
                         self.red_antes)

    def test_una_anotacion_de_otra_hoja_no_se_une(self):
        juez.armar_hoja(self.c)
        self._anotar({})
        ruta = os.path.join(self.c, "juez", "ouroboros", "anotaciones.csv")
        filas = _leer(ruta)
        filas[0]["oracion"] = "Otra oración."
        _csv(ruta, muestra.COLUMNAS_HOJA, filas)
        with self.assertRaises(juez.ErrorJuez):
            juez.unir(self.c)

    def test_sin_juicio_el_paso_solo_arma_la_hoja(self):
        mensajes = []
        self.assertIsNone(juez.ejecutar(self.c, log=mensajes.append))
        self.assertFalse(os.path.exists(os.path.join(self.c, "red_juez.tsv")))
        self.assertTrue(any("Falta el juicio" in m for m in mensajes))


class PruebasTope(unittest.TestCase):
    """El tope por arista: las N de mayor probabilidad, guardado en la
    carpeta para que la segunda pasada arme la misma hoja."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.c = tmp.name
        _tsv(os.path.join(self.c, "red.tsv"), ["tf", "blanco", "signo"],
             [{"tf": "LasR", "blanco": "lasB", "signo": "activates"},
              {"tf": "RhlR", "blanco": "phzA1", "signo": "represses"}])
        filas = [{"tf": "LasR", "blanco": "lasB", "id_par": "p%d" % i,
                  "pmid": str(i), "fuente": "abstract",
                  "probabilidad": str(p),
                  "oracion": "LasR activates lasB (%d)." % i}
                 for i, p in enumerate([0.70, 0.95, 0.80, 0.95, 0.60], 1)]
        filas.append({"tf": "RhlR", "blanco": "phzA1", "id_par": "q1",
                      "pmid": "9", "fuente": "abstract", "probabilidad": "",
                      "oracion": ORACION_3})
        _tsv(os.path.join(self.c, "red_evidencias.tsv"),
             ["tf", "blanco", "id_par", "pmid", "fuente", "probabilidad",
              "oracion"], filas)

    def _llave(self):
        return _leer(os.path.join(self.c, "juez", "llave.csv"))

    def test_toma_las_de_mayor_probabilidad_con_desempate_estable(self):
        juez.ejecutar(self.c, log=lambda m: None, max_por_arista=2)
        llave = self._llave()
        self.assertEqual(sorted(f["id_par"] for f in llave
                                if f["tf"] == "LasR"), ["p2", "p4"])
        # Una arista con menos oraciones que el tope (y sin probabilidad)
        # entra completa.
        self.assertEqual([f["id_par"] for f in llave if f["tf"] == "RhlR"],
                         ["q1"])

    def test_el_tope_se_guarda_y_vale_en_la_segunda_pasada(self):
        juez.ejecutar(self.c, log=lambda m: None, max_por_arista=1)
        hoja = _bytes(os.path.join(self.c, "juez", "hoja.csv"))
        juez.ejecutar(self.c, log=lambda m: None)
        self.assertEqual(_bytes(os.path.join(self.c, "juez", "hoja.csv")),
                         hoja)
        self.assertEqual(juez.leer_tope(self.c), 1)
        self.assertEqual(len(self._llave()), 2)

    def test_sin_tope_van_todas(self):
        juez.ejecutar(self.c, log=lambda m: None)
        self.assertEqual(len(self._llave()), 6)
        self.assertIsNone(juez.leer_tope(self.c))

    def test_las_que_quedan_fuera_no_llevan_veredicto(self):
        juez.ejecutar(self.c, log=lambda m: None, max_por_arista=1)
        hoja = _leer(os.path.join(self.c, "juez", "hoja.csv"))
        anot = []
        for f in hoja:
            f = dict(f)
            f.update({"relacion": "si", "direccion": "1>2", "signo": "+"})
            anot.append(f)
        carpeta = os.path.join(self.c, "juez", "ouroboros")
        os.makedirs(carpeta)
        _csv(os.path.join(carpeta, "anotaciones.csv"), list(anot[0]), anot)
        resumen = juez.ejecutar(self.c, log=lambda m: None)
        self.assertEqual(resumen["max_por_arista"], 1)
        self.assertEqual(resumen["oraciones"], 2)
        self.assertEqual(resumen["oraciones_en_la_red"], 6)
        ev = _leer(os.path.join(self.c, "red_evidencias_juez.tsv"), "\t")
        juzgadas = [e["id_par"] for e in ev if e["veredicto_agente"]]
        self.assertEqual(sorted(juzgadas), ["p2", "q1"])
        red = _leer(os.path.join(self.c, "red_juez.tsv"), "\t")
        self.assertEqual([a["n_juzgadas"] for a in red], ["1", "1"])

    def test_un_tope_invalido_no_se_acepta(self):
        with self.assertRaises(juez.ErrorJuez):
            juez.ejecutar(self.c, log=lambda m: None, max_por_arista=0)


class PruebasNivel(unittest.TestCase):
    """El nivel de confianza sale de los votos del jurado."""

    def test_votos_del_comentario(self):
        self.assertEqual(juez.votos_de(
            {"comentario": "jurado 1 de 3: si 2, no 1, dudoso 0, "
                           "abstenciones 0"}), (3, 2))
        self.assertEqual(juez.votos_de({"comentario": ""}), (None, None))
        self.assertEqual(juez.votos_de({}), (None, None))

    def test_nivel(self):
        self.assertEqual(juez.nivel("confirmada", 3, 3), "alta")
        self.assertEqual(juez.nivel("invertida", 3, 3), "alta")
        self.assertEqual(juez.nivel("confirmada", 2, 3), "media")
        self.assertEqual(juez.nivel("rechazada", 0, 3), "sin_respaldo")
        self.assertEqual(juez.nivel("dudosa", 1, 3), "sin_respaldo")
        # Un solo agente no es un jurado: sin nivel.
        self.assertEqual(juez.nivel("confirmada", None, None), "")
        self.assertEqual(juez.nivel("confirmada", 1, 1), "media")

    def test_la_arista_toma_el_maximo_de_sus_oraciones_que_la_respaldan(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = tmp.name
        _tsv(os.path.join(c, "red.tsv"), ["tf", "blanco", "signo"],
             [{"tf": "LasR", "blanco": "lasB", "signo": "activates"},
              {"tf": "RhlR", "blanco": "phzA1", "signo": "represses"}])
        _tsv(os.path.join(c, "red_evidencias.tsv"),
             ["tf", "blanco", "id_par", "pmid", "fuente", "oracion"],
             [{"tf": "LasR", "blanco": "lasB", "id_par": "p1", "pmid": "1",
               "fuente": "abstract", "oracion": ORACION_1},
              {"tf": "LasR", "blanco": "lasB", "id_par": "p2", "pmid": "2",
               "fuente": "abstract", "oracion": ORACION_2},
              {"tf": "RhlR", "blanco": "phzA1", "id_par": "p3", "pmid": "3",
               "fuente": "abstract", "oracion": ORACION_3}])
        juez.ejecutar(c, log=lambda m: None)
        hoja = _leer(os.path.join(c, "juez", "hoja.csv"))
        llave = {f["id_item"]: f for f in _leer(os.path.join(c, "juez",
                                                             "llave.csv"))}
        votos = {"p1": 1, "p2": 3, "p3": 0}
        anot = []
        for f in hoja:
            f = dict(f)
            l = llave[f["id_item"]]
            n = votos[l["id_par"]]
            f.update({"relacion": "si" if n else "no",
                      "direccion": l["direccion_red"] if n else "",
                      "signo": "+" if n else "",
                      "comentario": "jurado 1 de 3: si %d, no %d, dudoso 0, "
                                    "abstenciones 0" % (n, 3 - n)})
            anot.append(f)
        os.makedirs(os.path.join(c, "juez", "ouroboros"))
        _csv(os.path.join(c, "juez", "ouroboros", "anotaciones.csv"),
             list(anot[0]), anot)
        resumen = juez.ejecutar(c, log=lambda m: None)
        red = {a["tf"]: a for a in _leer(os.path.join(c, "red_juez.tsv"),
                                         "\t")}
        self.assertEqual((red["LasR"]["votos_si"], red["LasR"]["nivel"]),
                         ("3", "alta"))
        self.assertEqual(red["RhlR"]["nivel"], "sin_respaldo")
        self.assertEqual(resumen["aristas_por_nivel"],
                         {"alta": 1, "media": 0, "sin_respaldo": 1})


if __name__ == "__main__":
    unittest.main()
