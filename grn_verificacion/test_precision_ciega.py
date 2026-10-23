"""Pruebas de la precisión pareada sobre la muestra ciega, con datos
sintéticos: ni oraciones del corpus ni nada del laboratorio."""

import collections
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
COLUMNAS_CAPA = ["id_par", "tf_id", "target_id", "signo_sugerido", "oracion"]
COLUMNAS_RED = ["tf", "blanco", "signo"]
COLUMNAS_EVIDENCIAS = ["tf", "blanco", "id_par", "oracion"]

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
# De ocho cifras: si uno se colara en el log o en el JSON, además de fallar la
# prueba lo atraparía `verificar_publicable`.
PMID = dict((i, "2000000%d" % n) for n, (i, *_) in enumerate(ITEMS, 1))


def _escribir(ruta, columnas, filas):
    """CSV con BOM, como la hoja, la llave y la capa."""
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)


def _escribir_tsv(ruta, columnas, filas):
    """Como `etapa2/red.py`: tabuladores y nada entrecomillado."""
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(str(fila.get(c, "")) for c in columnas) + "\n")


def _kn(p):
    return (p["k"], p["n"])


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.carpeta = os.path.join(self.tmp, "corrida")
        os.makedirs(self.carpeta)
        self.escribir_capa(ITEMS)
        # La red usa formas de presentación distintas de los ids: la arista
        # se reconoce por su evidencia, no por su nombre.
        red = [(a.lower(), b.lower(), r, p) for _, p, a, b, _, r in ITEMS if r]
        # La oración de la evidencia trae otro espaciado: se compara
        # normalizada, como la deduplica red.py.
        evidencias = [{"tf": t, "blanco": b, "id_par": p,
                       "oracion": "Oración  %s." % p} for t, b, _, p in red]
        # p5 está en la red por OTRA oración: su par es arista, pero la
        # oración del ítem no la sostiene.
        evidencias.append({"tf": "pa0009", "blanco": "pa0010",
                           "id_par": "p5", "oracion": "Otra oración."})
        self.escribir_red([{"tf": t, "blanco": b, "signo": r}
                           for t, b, r, _ in red], evidencias)
        self.llave = os.path.join(self.tmp, "llave.csv")
        self.escribir_llave(ITEMS)

    def escribir_capa(self, items, ruta=None, oraciones=None):
        _escribir(ruta or os.path.join(self.carpeta, "capa_pares.csv"),
                  COLUMNAS_CAPA,
                  [{"id_par": p, "tf_id": a, "target_id": b,
                    "signo_sugerido": s,
                    "oracion": (oraciones or {}).get(p, "Oración %s." % p)}
                   for _, p, a, b, s, _ in items])

    def escribir_red(self, aristas, evidencias, nombre=None,
                     columnas=COLUMNAS_RED):
        red, ev = (("red.tsv", "red_evidencias.tsv") if nombre is None else
                   ("red_%s.tsv" % nombre, "red_%s_evidencias.tsv" % nombre))
        _escribir_tsv(os.path.join(self.carpeta, red), columnas, aristas)
        _escribir_tsv(os.path.join(self.carpeta, ev), COLUMNAS_EVIDENCIAS,
                      evidencias)

    def escribir_llave(self, items, columnas=LLAVE):
        _escribir(self.llave, columnas,
                  [{"id_item": i, "tanda": 1, "doble": "no",
                    "pmid": PMID.get(i, ""), "id_par": p,
                    "direccion_bronce": "1>2"} for i, p, *_ in items])

    def anotacion(self, extra=None, cambios=None, columnas=HOJA, items=ITEMS):
        filas = []
        for i, *_ in items:
            rel, dire, signo = (cambios or {}).get(i, ANOTADO.get(
                i, ("", "", "")))
            fila = {"id_item": i, "oracion": "x", "entidad_1": "a",
                    "entidad_2": "b", "relacion": rel, "direccion": dire,
                    "signo": signo}
            fila.update((extra or {}).get(i, {}))
            filas.append(fila)
        ruta = os.path.join(self.tmp, "anotacion.csv")
        _escribir(ruta, columnas, filas)
        return ruta

    def calcular(self, extra=None, cambios=None, columnas=HOJA, items=ITEMS,
                 **kw):
        return pc.calcular(self.anotacion(extra, cambios, columnas, items),
                           self.llave, self.carpeta, **kw)

    def excluir(self, *pmids):
        """Un archivo de PMIDs con el formato de reservas.tsv."""
        self.archivos_excluir = getattr(self, "archivos_excluir", 0) + 1
        ruta = os.path.join(self.tmp, "excluir_%d.tsv" % self.archivos_excluir)
        with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
            f.write("# fuera del denominador\n")
            for p in pmids:
                f.write("pmid\t%s\n" % p)
        return ruta

    def particion(self, train, dev, test=()):
        """Una carpeta de partición: [(pmid, texto marcado)] por parte."""
        carpeta = tempfile.mkdtemp(dir=self.tmp)
        for nombre, filas in (("train", train), ("dev", dev), ("test", test)):
            with io.open(os.path.join(carpeta, "entity_marked_%s.jsonl"
                                      % nombre), "w", encoding="utf-8",
                         newline="\n") as f:
                for pmid, texto in filas:
                    f.write(json.dumps({"text": texto, "label": "activates",
                                        "pmid": int(pmid), "tf": "X",
                                        "target": "Y"},
                                       ensure_ascii=False) + "\n")
        return carpeta


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

    def test_las_inversiones_son_de_los_si(self):
        """m-1003 es un `si` anotado 2>1 contra el 1>2 del bronce: uno de los
        dos `si`. De los `si`, la red solo retiene m-1001."""
        r = self.calcular()

        self.assertEqual(_kn(r["bronce"]["inversiones"]), (1, 2))
        self.assertEqual(_kn(r["red"]["inversiones"]), (0, 1))

    def test_siempre_mas_va_sobre_la_misma_base(self):
        """Tres `si` bien orientados con signo; en m-1004 el bronce dice
        `+;-` y se abstiene. «Siempre +» tiene que tener el denominador de la
        cifra con la que se compara: 3 con la abstención, 2 en los comunes.
        Un `dudoso` con `+` (m-1002, que la red retiene) y un `si` invertido
        con `+` (m-1005) no entran a ninguna de las dos bases."""
        r = self.calcular(cambios={"m-1002": ("dudoso", "1>2", "+"),
                                   "m-1003": ("si", "1>2", "-"),
                                   "m-1004": ("si", "1>2", "+"),
                                   "m-1005": ("si", "2>1", "+")})
        s = r["bronce"]["signo"]

        self.assertEqual(_kn(s["abstencion_es_error"]), (2, 3))
        self.assertEqual(_kn(s["linea_base_siempre_mas"]), (2, 3))
        self.assertEqual(_kn(s["solo_comunes"]), (2, 2))
        self.assertEqual(_kn(s["linea_base_siempre_mas_comunes"]), (1, 2))
        self.assertEqual(_kn(r["red"]["signo"]["linea_base_siempre_mas"]),
                         (1, 1))

    def test_un_si_con_negada_baja_la_precision_en_la_sensibilidad(self):
        r = self.calcular(extra={"m-1001": {"negada": "si"},
                                 "m-1004": {"negada": "si"}})

        # La cifra principal no cambia: la sensibilidad va aparte.
        self.assertEqual(_kn(r["bronce"]["con_direccion"]), (1, 4))
        s = r["sensibilidad_negadas_como_no"]
        # m-1004 es `dudoso`: ya no estaba en el numerador.
        self.assertEqual(s["n_negadas"], 1)
        self.assertEqual(_kn(s["bronce"]), (0, 4))
        self.assertEqual(_kn(s["red"]), (0, 2))
        self.assertEqual(len(s["diferencia"]), 2)
        self.assertEqual(r["avisos_rubrica"]["si_con_negada"], 1)

    def test_sin_negadas_la_sensibilidad_no_cambia_nada(self):
        r = self.calcular()
        s = r["sensibilidad_negadas_como_no"]
        self.assertEqual(s["n_negadas"], 0)
        self.assertEqual(s["bronce"], r["bronce"]["con_direccion"])
        self.assertEqual(s["red"], r["red"]["con_direccion"])


class PruebasRed(Base):

    def test_la_red_con_nombre_no_lee_las_expandidas(self):
        """La fila expandida cae en el mismo (tf, blanco) que la observada y
        va después, como las ordena `consolidar`: leída, le pisaba el signo
        y m-1001 salía con el `-` del operón."""
        aristas = [
            {"tf": "pa0001", "blanco": "pa0002", "signo": "activates",
             "expandida_de": ""},
            {"tf": "pa0001", "blanco": "pa0002", "signo": "represses",
             "expandida_de": "pa0002-op"},
            {"tf": "pa0003", "blanco": "pa0004", "signo": "represses",
             "expandida_de": ""},
            {"tf": "pa0005", "blanco": "pa0006", "signo": "represses",
             "expandida_de": ""},
        ]
        evidencias = [{"tf": t, "blanco": b, "id_par": p,
                       "oracion": "Oración %s." % p}
                      for t, b, p in (("pa0001", "pa0002", "p1"),
                                      ("pa0003", "pa0004", "p2"),
                                      ("pa0005", "pa0006", "p3"))]
        self.escribir_red(aristas, evidencias, nombre="recomendada",
                          columnas=COLUMNAS_RED + ["expandida_de"])

        r = self.calcular(red="recomendada")

        self.assertEqual(r["entradas"]["red"], "red_recomendada.tsv")
        self.assertEqual(r["entradas"]["evidencias"],
                         "red_recomendada_evidencias.tsv")
        # Es la red con nombre y no red.tsv: p3 solo está en la recomendada.
        self.assertEqual(_kn(r["retencion_de_la_red"]["total"]), (3, 4))
        self.assertEqual(_kn(r["red"]["signo"]["abstencion_es_error"]), (1, 1))
        self.assertEqual(r["pares_con_signo_mixto"], 0)

    def test_un_nombre_de_red_invalido_detiene(self):
        with self.assertRaises(ValueError):
            self.calcular(red="Red-Mala")

    def test_cada_item_toma_el_signo_de_la_arista_de_su_oracion(self):
        """LasR → lasB y lasR → lasB son el mismo par canónico con signos
        distintos. Con un signo por par ganaba la última arista del archivo
        y m-1001 tomaba el `-` de la otra."""
        items = ITEMS + [("m-1006", "p6", "PA0001", "PA0002", "-", None)]
        self.escribir_capa(items)
        self.escribir_llave(items)
        self.escribir_red(
            [{"tf": "LasR", "blanco": "lasB", "signo": "activates"},
             {"tf": "lasR", "blanco": "lasB", "signo": "represses"}],
            [{"tf": "LasR", "blanco": "lasB", "id_par": "p1",
              "oracion": "Oración p1."},
             {"tf": "lasR", "blanco": "lasB", "id_par": "p6",
              "oracion": "Oración p6."}])

        r = self.calcular(items=items, cambios={"m-1006": ("si", "1>2", "-")})

        self.assertEqual(r["pares_con_signo_mixto"], 1)
        self.assertEqual(_kn(r["red"]["signo"]["abstencion_es_error"]), (2, 2))

    def test_una_oracion_que_empieza_con_comillas_sigue_retenida(self):
        """Unas comillas sin cerrar al principio: con el `csv` por omisión la
        evidencia de p1 se comía la línea de p2, y ninguna de las dos casaba
        con su ítem."""
        self.escribir_capa(ITEMS, oraciones={"p1": '"Oración p1.'})
        self.escribir_red(
            [{"tf": "pa0001", "blanco": "pa0002", "signo": "activates"},
             {"tf": "pa0003", "blanco": "pa0004", "signo": "represses"}],
            [{"tf": "pa0001", "blanco": "pa0002", "id_par": "p1",
              "oracion": '"Oración  p1.'},
             {"tf": "pa0003", "blanco": "pa0004", "id_par": "p2",
              "oracion": "Oración p2."}])

        r = self.calcular()

        self.assertEqual(_kn(r["retencion_de_la_red"]["total"]), (2, 4))
        self.assertEqual(_kn(r["red"]["con_direccion"]), (1, 2))
        self.assertEqual(r["red"]["signo"]["abstencion_es_error"]["k"], 1)

    def test_lee_la_red_con_bom_y_crlf(self):
        """Como queda un TSV guardado otra vez en Windows: con BOM la primera
        columna se llamaba «\\ufefftf» y no se encontraba `tf`."""
        for nombre in ("red.tsv", "red_evidencias.tsv"):
            ruta = os.path.join(self.carpeta, nombre)
            with io.open(ruta, encoding="utf-8", newline="") as f:
                texto = f.read()
            with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                f.write(texto.replace("\n", "\r\n"))

        r = self.calcular()

        self.assertEqual(_kn(r["retencion_de_la_red"]["total"]), (2, 4))
        self.assertEqual(r["red"]["signo"]["abstencion_es_error"]["k"], 1)

    def test_cuenta_las_evidencias_sin_par_en_la_capa(self):
        with io.open(os.path.join(self.carpeta, "red_evidencias.tsv"), "a",
                     encoding="utf-8", newline="\n") as f:
            f.write("pa0001\tpa0002\tp99\tOtra más.\n")

        r = self.calcular()

        self.assertEqual(r["evidencias_sin_par_en_capa"], 1)
        self.assertEqual(r["n_anotados"], 4)


class PruebasCapa(Base):

    def test_la_capa_de_otra_carpeta(self):
        """La red es de la carpeta (la de otro modelo) y la capa, la del
        sorteo: la que tiene los id_par de la llave."""
        antes = self.calcular()
        sorteo = os.path.join(self.tmp, "sorteo")
        os.makedirs(sorteo)
        capa = os.path.join(sorteo, "capa_pares.csv")
        shutil.move(os.path.join(self.carpeta, "capa_pares.csv"), capa)

        with self.assertRaises(OSError):
            self.calcular()
        r = self.calcular(capa=capa)

        self.assertTrue(antes["entradas"]["capa_de_la_carpeta"])
        self.assertFalse(r["entradas"]["capa_de_la_carpeta"])
        for clave in ("bronce", "red", "retencion_de_la_red", "pareado"):
            self.assertEqual(r[clave], antes[clave], clave)


class PruebasExclusion(Base):

    def test_por_archivo_saca_el_item_del_bronce_y_de_la_red(self):
        r = self.calcular(excluir=[self.excluir(PMID["m-1001"])])

        self.assertEqual(r["n_anotados"], 3)
        self.assertEqual(_kn(r["bronce"]["con_direccion"]), (0, 3))
        self.assertEqual(_kn(r["red"]["con_direccion"]), (0, 1))
        self.assertEqual(r["exclusion"],
                         {"archivos": 1, "pmids": 1, "items_excluidos": 1,
                          "items_con_texto_en_train": None})
        # Los avisos de la rúbrica tampoco cuentan al excluido: quedan los
        # tres anotados que siguen.
        self.assertEqual(r["avisos_rubrica"]["negada_o_especulativa_vacia"],
                         3)
        # Una ruta suelta, sin lista, no se recorre letra por letra.
        suelta = self.calcular(excluir=self.excluir(PMID["m-1001"]))
        self.assertEqual(suelta["exclusion"], r["exclusion"])

    def test_por_particion_saca_train_y_dev_pero_no_test(self):
        """m-1002 está en train y m-1005 en dev; m-1003 en test, que el
        modelo no vio. La oración de m-1004 está en train bajo otro PMID: no
        sale, pero se cuenta."""
        p = self.particion(
            train=[(PMID["m-1002"], "<e1>A</e1> y <e2>B</e2>."),
                   ("29999999", "<e1>Oración</e1> <e2>p4</e2>.")],
            dev=[(PMID["m-1005"], "<e1>C</e1> y <e2>D</e2>.")],
            test=[(PMID["m-1003"], "<e1>E</e1> y <e2>F</e2>.")])

        r = self.calcular(particion=p)

        self.assertEqual(r["exclusion"],
                         {"archivos": 0, "pmids": 3, "items_excluidos": 2,
                          "items_con_texto_en_train": 1})
        self.assertEqual((r["n_anotados"], r["n_sin_anotar"]), (3, 0))
        self.assertEqual(_kn(r["bronce"]["con_direccion"]), (1, 3))
        # m-1002 era el otro ítem que la red retenía.
        self.assertEqual(_kn(r["red"]["con_direccion"]), (1, 1))

    def test_archivos_y_particion_se_suman(self):
        p = self.particion(train=[(PMID["m-1002"], "<e1>A</e1> <e2>B</e2>")],
                           dev=[])
        r = self.calcular(excluir=[self.excluir(PMID["m-1001"]),
                                   self.excluir(PMID["m-1001"],
                                                PMID["m-1003"])],
                          particion=p)

        self.assertEqual(r["exclusion"],
                         {"archivos": 2, "pmids": 3, "items_excluidos": 3,
                          "items_con_texto_en_train": 0})
        self.assertEqual(r["n_anotados"], 1)

    def test_sin_columna_pmid_en_la_llave_no_se_puede_excluir(self):
        self.escribir_llave(ITEMS, columnas=[c for c in LLAVE if c != "pmid"])
        # Sin exclusión la llave no necesita el PMID.
        self.assertEqual(self.calcular()["n_anotados"], 4)

        with self.assertRaises(ValueError) as ctx:
            self.calcular(excluir=[self.excluir(PMID["m-1001"])])
        # Y por la columna que falta, no por los PMIDs vacíos que deja.
        self.assertIn("columna pmid", str(ctx.exception))

    def test_un_pmid_que_no_es_numero_detiene_sin_decir_cual(self):
        with io.open(self.llave, encoding="utf-8-sig") as f:
            texto = f.read().replace(PMID["m-1003"], "")
        with io.open(self.llave, "w", encoding="utf-8-sig") as f:
            f.write(texto)

        with self.assertRaises(ValueError) as ctx:
            self.calcular(excluir=[self.excluir(PMID["m-1001"])])
        self.assertIn("1 ítems", str(ctx.exception))
        self.assertNotIn("m-1003", str(ctx.exception))

    def test_sin_dev_en_la_particion_detiene_sin_la_ruta(self):
        p = self.particion(train=[], dev=[])
        os.remove(os.path.join(p, "entity_marked_dev.jsonl"))

        with self.assertRaises(ValueError) as ctx:
            self.calcular(particion=p)
        self.assertIn("entity_marked_dev.jsonl", str(ctx.exception))
        self.assertNotIn(p, str(ctx.exception))

    def test_ni_pmids_ni_ids_salen_por_el_log_ni_al_json(self):
        p = self.particion(train=[(PMID["m-1002"], "<e1>A</e1> <e2>B</e2>")],
                           dev=[(PMID["m-1003"], "<e1>C</e1> <e2>D</e2>")])
        destino = os.path.join(self.tmp, "r.json")
        lineas = []

        pc.ejecutar(self.anotacion(), self.llave, self.carpeta, destino,
                    log=lineas.append,
                    excluir=[self.excluir(PMID["m-1001"])], particion=p)

        with io.open(destino, encoding="utf-8") as f:
            texto = f.read()
        todo = texto + "\n" + "\n".join(lineas)
        for i, *_ in ITEMS:
            self.assertNotIn(i, todo)
            self.assertNotIn(PMID[i], todo)
        self.assertEqual(json.loads(texto)["exclusion"]["items_excluidos"], 3)
        self.assertTrue(any("exclusión" in l for l in lineas))

    def test_lo_que_no_se_puede_publicar_no_sale(self):
        """Una etiqueta con forma de PMID: ni una línea ni el JSON."""
        destino = os.path.join(self.tmp, "r.json")
        lineas = []
        with self.assertRaises(ValueError):
            pc.ejecutar(self.anotacion(), self.llave, self.carpeta, destino,
                        log=lineas.append, etiqueta="PMID 31415926")
        self.assertEqual(lineas, [])
        self.assertFalse(os.path.exists(destino))

    def test_una_linea_que_no_se_puede_publicar_no_sale(self):
        """Sin --json también se filtra: una red cuyo nombre tiene forma de
        PMID sale en la primera línea, y entonces no sale ninguna."""
        for sufijo in ("", "_evidencias"):
            shutil.copy(os.path.join(self.carpeta, "red%s.tsv" % sufijo),
                        os.path.join(self.carpeta,
                                     "red_31415926%s.tsv" % sufijo))
        lineas = []
        with self.assertRaises(ValueError) as ctx:
            pc.ejecutar(self.anotacion(), self.llave, self.carpeta,
                        log=lineas.append, red="31415926")
        self.assertEqual(lineas, [])
        self.assertNotIn("31415926", str(ctx.exception))


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
        self.assertEqual(r["tiempo"]["items_sin_tiempo"], 0)
        self.assertEqual(r["tiempo"]["minutos_total"], 4.0)

    def test_cuenta_los_anotados_sin_tiempo(self):
        """Un anotado sin `segundos` no se inventa ni se esconde: se cuenta,
        para que se vea cuánto de la cifra de esfuerzo falta."""
        extra = dict((i, {"inicio": "", "fin": "",
                          "segundos": "" if n == 0 else "60"})
                     for n, (i, *_) in enumerate(ITEMS))
        r = self.calcular(extra=extra,
                          columnas=HOJA + ["inicio", "fin", "segundos"])
        self.assertEqual(r["tiempo"]["items_con_tiempo"], 3)
        self.assertEqual(r["tiempo"]["items_sin_tiempo"], 1)
        self.assertEqual(r["tiempo"]["minutos_total"], 3.0)

    def test_sin_tiempos_no_inventa_cifra(self):
        self.assertIsNone(self.calcular()["tiempo"])

    def test_un_valor_fuera_de_la_rubrica_detiene(self):
        """El error dice la línea y la columna, no el valor: el valor es un
        juicio de una hoja ciega."""
        with self.assertRaises(ValueError) as ctx:
            self.calcular(cambios={"m-1001": ("sí", "1>2", "+")})
        self.assertIn("línea 2: relacion", str(ctx.exception))
        self.assertNotIn("sí", str(ctx.exception))

    def test_un_signo_0_detiene(self):
        """La tanda 1 traía 43 signos `0`; se normalizaron a `?` a mano. Un
        `0` que llegue ahora es un error y no un signo."""
        with self.assertRaises(ValueError) as ctx:
            self.calcular(cambios={"m-1001": ("si", "1>2", "0")})
        self.assertIn("línea 2: signo", str(ctx.exception))
        self.assertNotIn("'0'", str(ctx.exception))

    def test_tipo_negada_y_especulativa_fuera_de_la_rubrica_detienen(self):
        for columna, valor in (("tipo", "directo"), ("negada", "sí"),
                               ("especulativa", "quizá")):
            with self.assertRaises(ValueError, msg=columna) as ctx:
                self.calcular(extra={"m-1001": {columna: valor}})
            self.assertIn(columna, str(ctx.exception))
            self.assertNotIn(valor, str(ctx.exception))

    def test_negada_y_especulativa_vacias_son_aviso_y_no_error(self):
        # La hoja de las pruebas las deja vacías en los cuatro anotados.
        r = self.calcular()
        self.assertEqual(r["avisos_rubrica"]["negada_o_especulativa_vacia"],
                         4)

    def test_los_avisos_de_la_rubrica(self):
        def fila(rel, dire, signo="", tipo="", negada="no", espec="no"):
            return {"relacion": rel, "direccion": dire, "signo": signo,
                    "tipo": tipo, "negada": negada, "especulativa": espec}
        avisos = pc.avisos_de_rubrica({
            "a": fila("no", "1>2", signo="+"),
            "b": fila("si", "1>2", "+", "", negada="si"),
            "c": fila("dudoso", "1>2", "?", "no_se", espec=""),
            "d": fila("no", "ninguna"),
            "e": fila("si", "2>1", "-", "directa"),
            # Sin anotar: no cuenta para nada.
            "f": fila("", "", negada=""),
        })
        self.assertEqual(avisos, collections.Counter({
            "no_con_signo_o_tipo": 1, "no_sin_ninguna": 1,
            "si_o_dudoso_sin_signo_o_tipo": 1, "si_con_negada": 1,
            "negada_o_especulativa_vacia": 1}))

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

    def test_con_todas_las_banderas(self):
        for sufijo in ("", "_evidencias"):
            shutil.copy(os.path.join(self.carpeta, "red%s.tsv" % sufijo),
                        os.path.join(self.carpeta,
                                     "red_recomendada%s.tsv" % sufijo))
        sorteo = os.path.join(self.tmp, "sorteo")
        os.makedirs(sorteo)
        capa = os.path.join(sorteo, "capa_pares.csv")
        shutil.move(os.path.join(self.carpeta, "capa_pares.csv"), capa)
        p = self.particion(train=[(PMID["m-1002"], "<e1>A</e1> <e2>B</e2>")],
                           dev=[(PMID["m-1005"], "<e1>C</e1> <e2>D</e2>")])
        destino = os.path.join(self.tmp, "r.json")
        lineas = []

        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main([
                "precision-ciega", "--anotacion", self.anotacion(),
                "--llave", self.llave, "--carpeta", self.carpeta,
                "--json", destino, "--red", "recomendada", "--capa", capa,
                "--excluir-pmids", self.excluir(PMID["m-1001"]),
                "--excluir-pmids", self.excluir(PMID["m-1004"]),
                "--particion", p, "--etiqueta", "tanda2"])

        self.assertEqual(codigo, 0, lineas)
        with io.open(destino, encoding="utf-8") as f:
            r = json.load(f)
        self.assertEqual(r["etiqueta"], "tanda2")
        self.assertEqual(r["entradas"],
                         {"red": "red_recomendada.tsv",
                          "evidencias": "red_recomendada_evidencias.tsv",
                          "capa_de_la_carpeta": False})
        self.assertEqual(r["exclusion"],
                         {"archivos": 2, "pmids": 4, "items_excluidos": 4,
                          "items_con_texto_en_train": 0})
        # Queda m-1003 sola: un `si` invertido.
        self.assertEqual((r["n_anotados"], r["n_sin_anotar"]), (1, 0))
        self.assertEqual(_kn(r["bronce"]["inversiones"]), (1, 1))
        texto = "\n".join(lineas)
        self.assertNotIn("tanda2", texto)
        for i, *_ in ITEMS:
            self.assertNotIn(i, texto)
            self.assertNotIn(PMID[i], texto)


if __name__ == "__main__":
    unittest.main()
