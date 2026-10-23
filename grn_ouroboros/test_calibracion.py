"""La rúbrica de Ouroboros, la hoja y la llave de la calibración.

La calibración es sintética y pública (`docs/calibracion-anotacion.md`), así
que estas pruebas la leen tal cual está versionada. Lo demás son hojas
inventadas aquí, sin oraciones del corpus.

    python -m unittest grn_ouroboros.test_calibracion
"""

import csv
import io
import os
import shutil
import tempfile
import unittest

from grn_ouroboros import calibracion, rubrica

COLUMNAS = rubrica.COLUMNAS_HOJA


def _escribir(ruta, filas, columnas=COLUMNAS):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)


def _respuesta(**cambios):
    """Una respuesta válida del modelo, para un «si» sencillo."""
    r = {"fragmento": "GenX activates genY", "motivo": "Lo dice la oración.",
         "relacion": "si", "direccion": "1>2", "signo": "+", "tipo": "no_se",
         "negada": "no", "especulativa": "no", "comentario": ""}
    r.update(cambios)
    return r


class PruebasRubrica(unittest.TestCase):

    def test_las_columnas_son_las_de_la_pagina_de_revision(self):
        self.assertEqual(rubrica.COLUMNAS_HOJA[:4],
                         ["id_item", "oracion", "entidad_1", "entidad_2"])
        self.assertEqual(rubrica.CAMPOS_CERRADOS,
                         ["relacion", "direccion", "signo", "tipo", "negada",
                          "especulativa"])

    def test_el_esquema_pide_todo_y_admite_vacio_solo_en_signo_y_tipo(self):
        esquema = rubrica.esquema()
        self.assertEqual(esquema["required"], rubrica.CAMPOS_RESPUESTA)
        self.assertFalse(esquema["additionalProperties"])
        props = esquema["properties"]
        self.assertEqual(list(props)[:2], ["fragmento", "motivo"])
        self.assertIn("", props["signo"]["enum"])
        self.assertIn("", props["tipo"]["enum"])
        self.assertNotIn("", props["relacion"]["enum"])
        self.assertEqual(props["direccion"]["enum"], ["1>2", "2>1", "ninguna"])
        self.assertEqual(props["signo"]["enum"], ["+", "-", "?", ""])

    def test_el_esquema_es_nuevo_en_cada_llamada(self):
        a = rubrica.esquema()
        a["properties"]["relacion"]["enum"].append("quizas")
        self.assertNotIn("quizas",
                         rubrica.esquema()["properties"]["relacion"]["enum"])

    def test_una_respuesta_valida(self):
        valores, extras, esq, rub, _avisos = rubrica.validar_respuesta(
            _respuesta())
        self.assertEqual((esq, rub), ([], []))
        self.assertEqual(valores["relacion"], "si")
        self.assertEqual(set(valores), set(rubrica.COLUMNAS_VALORES))
        self.assertEqual(extras["fragmento"], "GenX activates genY")

    def test_un_campo_que_falta_o_sobra_es_error_de_esquema(self):
        sin = _respuesta()
        del sin["motivo"]
        self.assertTrue(rubrica.validar_respuesta(sin)[2])
        self.assertTrue(rubrica.validar_respuesta(
            _respuesta(confianza="alta"))[2])

    def test_una_etiqueta_que_no_es_de_la_rubrica(self):
        for cambio in ({"relacion": "sí"}, {"signo": "0"},
                       {"direccion": ""}, {"negada": True}):
            self.assertTrue(rubrica.validar_respuesta(_respuesta(**cambio))[2],
                            cambio)

    def test_una_combinacion_prohibida_es_error_de_rubrica(self):
        """«si» con negada = sí y «no» con signo: la forma está bien, la
        rúbrica no lo admite (§3.6 y §4)."""
        for cambio in ({"negada": "si"},
                       {"relacion": "no", "direccion": "ninguna"}):
            _v, _e, esq, rub, _a = rubrica.validar_respuesta(
                _respuesta(**cambio))
            self.assertEqual(esq, [], cambio)
            self.assertTrue(rub, cambio)

    def test_no_es_un_objeto(self):
        self.assertTrue(rubrica.validar_respuesta(["si"])[2])


class PruebasLlave(unittest.TestCase):

    def setUp(self):
        self.hoja = calibracion.leer_hoja(calibracion.RUTA_HOJA)
        self.llave = calibracion.leer_llave()

    def test_son_27_items(self):
        self.assertEqual(len(self.hoja), 27)
        self.assertEqual(len(self.llave), 27)

    def test_los_ids_y_las_entidades_de_la_hoja_y_la_llave_coinciden(self):
        self.assertEqual([it["id_item"] for it in self.hoja],
                         sorted(self.llave))
        for it in self.hoja:
            fila = self.llave[it["id_item"]]
            self.assertEqual((it["entidad_1"], it["entidad_2"]),
                             (fila["entidad_1"], fila["entidad_2"]),
                             it["id_item"])

    def test_toda_la_llave_pasa_la_rubrica(self):
        for id_item, fila in self.llave.items():
            valores = calibracion.valores_de(fila)
            valores["comentario"] = ""
            _limpios, errores, _avisos = rubrica.validar_valores(valores)
            self.assertEqual(errores, [], id_item)

    def test_el_guion_largo_es_celda_vacia(self):
        self.assertEqual(calibracion.valores_de(self.llave["c05"]),
                         {"relacion": "no", "direccion": "ninguna",
                          "signo": "", "tipo": "", "negada": "no",
                          "especulativa": "no"})
        self.assertEqual(self.llave["c16"]["relacion"], "dudoso")
        self.assertEqual(self.llave["c16"]["negada"], "si")

    def test_el_reparto_es_el_que_dice_el_documento(self):
        """15 `si`, 4 `dudoso` y 8 `no` (§«Cómo están hechas»)."""
        reparto = {}
        for fila in self.llave.values():
            reparto[fila["relacion"]] = reparto.get(fila["relacion"], 0) + 1
        self.assertEqual(reparto, {"si": 15, "dudoso": 4, "no": 8})


class PruebasHoja(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = os.path.join(self.tmp, "hoja.csv")

    def item(self, id_item="m-1001", **cambios):
        fila = {"id_item": id_item, "oracion": "GenX activates genY.",
                "entidad_1": "GenX", "entidad_2": "genY"}
        fila.update(cambios)
        return fila

    def test_lee_ids_de_calibracion_y_de_tanda(self):
        _escribir(self.ruta, [self.item("c01"), self.item("m-1234")])
        ids = [it["id_item"] for it in calibracion.leer_hoja(self.ruta)]
        self.assertEqual(ids, ["c01", "m-1234"])

    def test_columnas_de_otra_forma(self):
        _escribir(self.ruta, [self.item()], columnas=COLUMNAS[:4])
        with self.assertRaises(calibracion.ErrorHoja):
            calibracion.leer_hoja(self.ruta)

    def test_una_hoja_ya_anotada_se_rechaza(self):
        _escribir(self.ruta, [self.item(relacion="si")])
        with self.assertRaises(calibracion.ErrorHoja) as caja:
            calibracion.leer_hoja(self.ruta)
        self.assertIn("sin anotar", str(caja.exception))

    def test_el_error_no_lleva_la_oracion(self):
        _escribir(self.ruta, [self.item(), self.item()])
        with self.assertRaises(calibracion.ErrorHoja) as caja:
            calibracion.leer_hoja(self.ruta)
        self.assertNotIn("activates", str(caja.exception))

    def test_falta_una_entidad(self):
        _escribir(self.ruta, [self.item(entidad_2=" ")])
        with self.assertRaises(calibracion.ErrorHoja):
            calibracion.leer_hoja(self.ruta)

    def test_id_con_espacios(self):
        _escribir(self.ruta, [self.item("m 1")])
        with self.assertRaises(calibracion.ErrorHoja):
            calibracion.leer_hoja(self.ruta)


class PruebasComparar(unittest.TestCase):

    def setUp(self):
        self.llave = calibracion.leer_llave()

    def anotaciones(self, cambios=None, ids=None):
        salida = {}
        for id_item in ids or sorted(self.llave):
            valores = calibracion.valores_de(self.llave[id_item])
            valores["comentario"] = ""
            salida[id_item] = valores
        for id_item, cambio in (cambios or {}).items():
            salida[id_item] = None if cambio is None else dict(
                salida[id_item], **cambio)
        return salida

    def test_la_llave_contra_si_misma(self):
        r = calibracion.comparar(self.anotaciones(), self.llave)
        self.assertEqual(r["n"], 27)
        self.assertEqual(r["identicos"], 27)
        self.assertTrue(all(v == {"k": 27, "n": 27}
                            for v in r["por_campo"].values()))

    def test_un_campo_distinto(self):
        r = calibracion.comparar(
            self.anotaciones({"c27": {"tipo": "directa"}}), self.llave)
        self.assertEqual(r["por_campo"]["tipo"]["k"], 26)
        self.assertEqual(r["por_campo"]["relacion"]["k"], 27)
        self.assertEqual(r["por_item"]["c27"]["difiere"], ["tipo"])

    def test_la_abstencion_cuenta_como_error_en_todo(self):
        r = calibracion.comparar(self.anotaciones({"c01": None}), self.llave)
        self.assertEqual(r["abstenciones"], 1)
        self.assertTrue(all(v["k"] == 26 for v in r["por_campo"].values()))
        self.assertTrue(r["por_item"]["c01"]["abstencion"])

    def test_un_subconjunto_como_la_calibracion_2(self):
        r = calibracion.comparar(
            self.anotaciones(ids=["c07", "c22", "c10"]), self.llave)
        self.assertEqual(r["n"], 3)

    def test_un_item_que_no_es_de_la_calibracion(self):
        with self.assertRaises(ValueError):
            calibracion.comparar({"m-1001": None}, self.llave)


class PruebasAnotaciones(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ruta = os.path.join(self.tmp, "anotaciones.csv")

    def fila(self, id_item, **valores):
        fila = {"id_item": id_item, "oracion": "x", "entidad_1": "a",
                "entidad_2": "b"}
        fila.update(valores)
        return fila

    def test_abstencion_y_valores(self):
        _escribir(self.ruta, [
            self.fila("c01"),
            self.fila("c02", relacion="no", direccion="ninguna", negada="si",
                      especulativa="no")])
        r = calibracion.leer_anotaciones(self.ruta)
        self.assertIsNone(r["c01"])
        self.assertEqual(r["c02"]["negada"], "si")

    def test_un_valor_fuera_de_la_rubrica_detiene(self):
        _escribir(self.ruta, [self.fila("c01", relacion="si", direccion="1>2",
                                        signo="0", tipo="no_se", negada="no",
                                        especulativa="no")])
        with self.assertRaises(calibracion.ErrorHoja):
            calibracion.leer_anotaciones(self.ruta)


class PruebasReferencia(unittest.TestCase):

    def test_la_hoja_de_calibracion_trae_su_llave(self):
        items = calibracion.leer_hoja(calibracion.RUTA_HOJA)
        ref = calibracion.referencia_si_es_calibracion(items)
        self.assertEqual(len(ref), 27)
        self.assertEqual(ref["c10"]["negada"], "si")

    def test_la_calibracion_2_es_un_subconjunto(self):
        ruta = os.path.join(os.path.dirname(calibracion.RUTA_HOJA),
                            "calibracion2-hoja.csv")
        ref = calibracion.referencia_si_es_calibracion(
            calibracion.leer_hoja(ruta))
        self.assertEqual(len(ref), 12)

    def test_otra_hoja_no_tiene_referencia(self):
        items = calibracion.leer_hoja(calibracion.RUTA_HOJA)
        items[0] = dict(items[0], oracion=items[0]["oracion"] + " Otra.")
        self.assertIsNone(calibracion.referencia_si_es_calibracion(items))
        self.assertIsNone(calibracion.referencia_si_es_calibracion(
            [{"id_item": "m-1001", "oracion": "x", "entidad_1": "a",
              "entidad_2": "b"}]))


if __name__ == "__main__":
    unittest.main()
