# -*- coding: utf-8 -*-
"""Pruebas del guardian de procedencia.

La que no puede faltar es la ultima: darle a la evaluacion archivos de dos
corridas distintas y afirmar que **sale con codigo distinto de 0**. Sin ella
este guardian puede quedarse en codigo muerto igual que le paso al de
particionar.py, y entonces no protege de nada mientras aparenta hacerlo.

    python -m unittest discover etapa2
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
# Las pruebas de extremo a extremo invocan evaluar_oro y
# muestrear_precision, que siguen viviendo en etapa2/ y se importan
# como modulos top-level. Sin esta segunda ruta no se cargan.
sys.path.insert(0, os.path.join(_RAIZ, 'etapa2'))

from grn_comun import procedencia as P


def escribir(ruta, texto):
    d = os.path.dirname(ruta)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return ruta


class PruebasHuella(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="proc_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def ruta(self, nombre):
        return os.path.join(self.d, nombre)

    def test_el_mismo_contenido_da_la_misma_huella(self):
        a = escribir(self.ruta("a.txt"), "las mismas lineas\n")
        b = escribir(self.ruta("b.txt"), "las mismas lineas\n")
        self.assertEqual(P.huella(a), P.huella(b))

    def test_un_byte_distinto_cambia_la_huella(self):
        """Es lo que separa esto de comparar rutas: el nombre del archivo es
        siempre el mismo y lo que cambia es el contenido."""
        a = escribir(self.ruta("a.txt"), "linea\n")
        b = escribir(self.ruta("b.txt"), "linea \n")
        self.assertNotEqual(P.huella(a), P.huella(b))

    def test_un_archivo_que_no_existe_no_tiene_huella(self):
        self.assertIsNone(P.huella(self.ruta("no_esta.txt")))
        self.assertIsNone(P.huella(""))
        self.assertIsNone(P.huella(None))

    def test_la_huella_no_depende_de_como_se_lea(self):
        """Se lee por bloques de 1 MB; un archivo mayor tiene que dar lo
        mismo que si se leyera de un golpe."""
        import hashlib
        grande = self.ruta("grande.bin")
        cuerpo = (b"x" * 1024 * 1024) + b"cola"
        with open(grande, "wb") as f:
            f.write(cuerpo)
        self.assertEqual(P.huella(grande),
                         hashlib.sha256(cuerpo).hexdigest()[:P.LARGO])


class PruebasSello(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="proc_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_sellar_guarda_ruta_huella_y_tamano(self):
        a = escribir(os.path.join(self.d, "pares.jsonl"), "una linea\n")
        s = P.sellar({"pares": a})
        self.assertEqual(s["pares"]["ruta"], a)
        self.assertEqual(s["pares"]["huella"], P.huella(a))
        self.assertEqual(s["pares"]["bytes"], 10)

    def test_sellar_ignora_las_rutas_vacias(self):
        self.assertEqual(P.sellar({"opcional": "", "otro": None}), {})

    def test_leer_sello_de_un_informe_sin_huellas_da_vacio(self):
        r = escribir(os.path.join(self.d, "i.json"), json.dumps({"fecha": "x"}))
        self.assertEqual(P.leer_sello(r), {})

    def test_leer_sello_de_un_json_roto_no_revienta(self):
        r = escribir(os.path.join(self.d, "i.json"), '{"huellas": {')
        self.assertEqual(P.leer_sello(r), {})

    def test_leer_sello_de_un_informe_que_no_existe_da_vacio(self):
        self.assertEqual(P.leer_sello(os.path.join(self.d, "no.json")), {})


class PruebasVerificar(unittest.TestCase):
    """El guardian tiene que poder decir que no."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="proc_")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.a = escribir(os.path.join(self.d, "pares.jsonl"), "corrida A\n")
        self.sello = P.sellar({"pares": self.a})

    def test_acepta_el_mismo_archivo(self):
        problemas, sin = P.verificar(self.sello, {"pares": self.a})
        self.assertEqual(problemas, [])
        self.assertEqual(sin, [])

    def test_rechaza_un_archivo_de_otra_corrida(self):
        escribir(self.a, "corrida B, otra cosa\n")   # misma ruta, otro contenido
        problemas, _ = P.verificar(self.sello, {"pares": self.a})
        self.assertEqual(len(problemas), 1)
        self.assertIn("corridas", problemas[0].lower())

    def test_rechaza_si_el_archivo_desaparecio(self):
        os.remove(self.a)
        problemas, _ = P.verificar(self.sello, {"pares": self.a})
        self.assertEqual(len(problemas), 1)
        self.assertIn("no existe", problemas[0])

    def test_lo_no_sellado_se_reporta_pero_no_es_problema(self):
        otro = escribir(os.path.join(self.d, "red.tsv"), "x\n")
        problemas, sin = P.verificar(self.sello, {"pares": self.a, "red": otro})
        self.assertEqual(problemas, [])
        self.assertEqual(sin, ["red"])


class PruebasExigir(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="proc_")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.dicho = []

    def decir(self, *a):
        self.dicho.append(" ".join(str(x) for x in a))

    def _informe(self, sello):
        return escribir(os.path.join(self.d, "red_informe.json"),
                        json.dumps({"huellas": sello}))

    def test_deja_seguir_cuando_todo_casa(self):
        a = escribir(os.path.join(self.d, "p.jsonl"), "A\n")
        inf = self._informe(P.sellar({"pares": a}))
        self.assertTrue(P.exigir(inf, {"pares": a}, self.decir))

    def test_detiene_cuando_no_casa(self):
        a = escribir(os.path.join(self.d, "p.jsonl"), "A\n")
        inf = self._informe(P.sellar({"pares": a}))
        escribir(a, "B\n")
        self.assertFalse(P.exigir(inf, {"pares": a}, self.decir))
        self.assertIn("CORRIDAS DISTINTAS", "\n".join(self.dicho))

    def test_un_informe_viejo_sin_huellas_avisa_pero_deja_seguir(self):
        """Un informe de antes de que esto existiera no debe bloquear; lo que
        no puede es callarse, porque entonces nadie sabe que no se comprobo."""
        a = escribir(os.path.join(self.d, "p.jsonl"), "A\n")
        inf = escribir(os.path.join(self.d, "viejo.json"),
                       json.dumps({"fecha": "2026-01-01"}))
        self.assertTrue(P.exigir(inf, {"pares": a}, self.decir))
        self.assertIn("AVISO", "\n".join(self.dicho))


class PruebasDeExtremoAExtremo(unittest.TestCase):
    """La que de verdad importa: que la EVALUACION se niegue.

    Las de arriba prueban el modulo. Esta prueba que esta conectado, que es
    donde murio el guardian de particionar.py: la funcion sabia fallar y nadie
    la llamaba con datos que la hicieran fallar.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="proc_e2e_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_evaluar_oro_sale_con_codigo_1_si_mezclan_corridas(self):
        import evaluar_oro

        pares = escribir(os.path.join(self.d, "pares.jsonl"),
                         '{"pmid":"1","tf":"LasR","blanco":"rhlR"}\n')
        preds = escribir(os.path.join(self.d, "predicciones.jsonl"),
                         '{"pmid":"1","signo":"activates"}\n')
        red = escribir(os.path.join(self.d, "red.tsv"),
                       "tf\tblanco\tsigno\nLasR\trhlR\tactivates\n")
        informe = escribir(
            os.path.join(self.d, "red_informe.json"),
            json.dumps({"huellas": P.sellar(
                {"pares": pares, "predicciones": preds, "red": red})}))

        # Alguien rehace la clasificacion y no vuelve a correr red.py.
        escribir(preds, '{"pmid":"1","signo":"represses"}\n')

        antes = sys.stdout
        sys.stdout = io.StringIO()
        try:
            codigo = evaluar_oro.main([
                "--red", red, "--pares", pares, "--predicciones", preds,
                "--red-informe", informe,
                "--salida", os.path.join(self.d, "e.tsv"),
                "--resumen", os.path.join(self.d, "e.json")])
            salida = sys.stdout.getvalue()
        finally:
            sys.stdout = antes

        self.assertEqual(codigo, 1, "la evaluacion tenia que negarse")
        self.assertIn("CORRIDAS DISTINTAS", salida)
        self.assertFalse(os.path.exists(os.path.join(self.d, "e.json")),
                         "no debe escribir resumen de una cadena rota")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PruebasCoberturaDelOro(unittest.TestCase):
    """El indicador que SUBE con la contaminacion.

    El que ya existia, `fraccion_explicada_por_el_oro`, es un cociente cuyo
    denominador crece al contaminar, asi que con un 12% de filas copiadas
    bajaba justo cuando debia subir. Estas pruebas fijan que el nuevo no puede
    hacer eso.
    """

    def setUp(self):
        import evaluar_oro
        self.O = evaluar_oro
        self.vocab = {"lasr", "rhlr", "mext", "mexef-oprn", "algu", "algd"}

    def test_cuenta_lo_que_esta(self):
        dicc = {"lasr": {}, "rhlr": {}, "mext": {}}
        c = self.O.medir_cobertura_del_oro(dicc, self.vocab)
        self.assertEqual(c["nombres_del_oro"], 6)
        self.assertEqual(c["nombres_del_oro_en_el_diccionario"], 3)
        self.assertAlmostEqual(c["cobertura_del_oro"], 0.5, places=3)

    def test_meter_nombres_del_oro_SIEMPRE_lo_sube(self):
        """La propiedad que lo hace util: es monotono."""
        dicc = {"lasr": {}, "rhlr": {}}
        antes = self.O.medir_cobertura_del_oro(dicc, self.vocab)["cobertura_del_oro"]
        for n in ("mext", "algu", "algd"):
            dicc[n] = {}
            ahora = self.O.medir_cobertura_del_oro(
                dicc, self.vocab)["cobertura_del_oro"]
            self.assertGreater(ahora, antes)
            antes = ahora

    def test_meter_nombres_AJENOS_al_oro_no_lo_mueve(self):
        """El denominador es fijo: engordar el diccionario con genes que el oro
        no menciona no diluye la medida, que es donde fallaba la anterior."""
        dicc = {"lasr": {}, "rhlr": {}}
        antes = self.O.medir_cobertura_del_oro(dicc, self.vocab)["cobertura_del_oro"]
        for i in range(500):
            dicc["pa%04d" % i] = {}
        ahora = self.O.medir_cobertura_del_oro(dicc, self.vocab)["cobertura_del_oro"]
        self.assertEqual(antes, ahora)

    def test_abandona_si_lo_cubre_todo(self):
        dicc = dict((n, {}) for n in self.vocab)
        with self.assertRaises(SystemExit) as e:
            self.O.revisar_cobertura_del_oro(
                self.O.medir_cobertura_del_oro(dicc, self.vocab), "g.tsv")
        self.assertIn("patrón de oro", str(e.exception))

    def test_avisa_sin_abandonar_en_la_franja_de_enmedio(self):
        dicc = dict((n, {}) for n in list(self.vocab)[:5])   # 5 de 6 = 0.833
        dicho = []
        aviso = self.O.revisar_cobertura_del_oro(
            self.O.medir_cobertura_del_oro(dicc, self.vocab), "g.tsv",
            lambda *a: dicho.append(" ".join(str(x) for x in a)))
        self.assertTrue(aviso)
        self.assertIn("AVISO", "\n".join(dicho))

    def test_el_diccionario_honesto_pasa(self):
        """Con el archivo real: 387 de 625, muy por debajo del umbral."""
        ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "genes_pao1.tsv")
        oro_ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "oro_pseudomonas.tsv")
        if not (os.path.exists(ruta) and os.path.exists(oro_ruta)):
            self.skipTest("faltan los archivos reales")
        dicc, _ = self.O.cargar_diccionario(ruta)
        vocab = self.O.vocabulario_del_oro(self.O.cargar_oro(oro_ruta))
        c = self.O.medir_cobertura_del_oro(dicc, vocab)
        self.assertLess(c["cobertura_del_oro"], self.O.UMBRAL_AVISO_COBERTURA_ORO)
        self.assertFalse(self.O.revisar_cobertura_del_oro(c, ruta, lambda *a: None))


class PruebasSellarComo(unittest.TestCase):
    """El sello de un archivo que todavia no esta en su sitio.

    Salio de un fallo real: red.py escribe a red.tsv.tmp y publicar() renombra
    al final, asi que al sellar el nombre final no existia. La huella salia
    None y la evaluacion rechazaba la cadena por una discrepancia inventada.
    El guardian atrapo el error en su primera corrida de verdad.
    """

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="proc_")
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_mide_el_temporal_y_anota_el_nombre_final(self):
        final = os.path.join(self.d, "red.tsv")
        tmp = escribir(final + ".tmp", "tf\tblanco\nLasR\trhlR\n")
        s = P.sellar_como(final, tmp)
        self.assertEqual(s["ruta"], final)
        self.assertEqual(s["huella"], P.huella(tmp))
        self.assertIsNotNone(s["huella"])

    def test_la_huella_sobrevive_al_renombrado(self):
        """Lo que hace que esto sirva: medir el .tmp y leer el final da igual,
        porque os.replace mueve los mismos bytes."""
        final = os.path.join(self.d, "red.tsv")
        tmp = escribir(final + ".tmp", "contenido definitivo\n")
        sello = {"red": P.sellar_como(final, tmp)}
        os.replace(tmp, final)                      # lo que hace publicar()
        problemas, sin = P.verificar(sello, {"red": final})
        self.assertEqual(problemas, [])
        self.assertEqual(sin, [])

    def test_sellar_directo_el_nombre_final_habria_fallado(self):
        """La prueba de que el arreglo hacia falta: sin sellar_como, la huella
        del archivo que aun no existe es None y la cadena se rompe sola."""
        final = os.path.join(self.d, "red.tsv")
        tmp = escribir(final + ".tmp", "contenido definitivo\n")
        sello_malo = P.sellar({"red": final})       # el final NO existe todavia
        self.assertIsNone(sello_malo["red"]["huella"])
        os.replace(tmp, final)
        problemas, _ = P.verificar(sello_malo, {"red": final})
        self.assertEqual(len(problemas), 1)
