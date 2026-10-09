# -*- coding: utf-8 -*-
"""Pruebas del puente bronce → BioBERT.

Las que no pueden faltar:

- **la segunda corrida no llama al modelo**: con las mismas entradas, todo sale
  de la caché;
- **la caché es por texto, no por `id_par`**: si un diccionario nuevo cambia
  el marcado de un mismo `id_par`, la predicción vieja no se le pega al texto
  nuevo;
- **una caché de otro modelo no se usa**: otros pesos son otro modelo aunque
  el `config.json` sea idéntico byte a byte, que es lo que pasa con dos
  reentrenamientos de la misma receta;
- **lo que otro modelo dejó a medias no se adopta**: `clasificar.py
  --reanudar` toma lo que encuentre, así que el puente lo borra si no es de
  este modelo.

Oraciones sintéticas y el diccionario versionado; nada del laboratorio.

    python -m unittest discover .
"""

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_verificacion import puente   # noqa: E402

ETIQUETAS = ["activates", "no_relation", "regulates", "represses"]


def _modelo(carpeta, config='{"a": 1}', pesos=b"pesos A"):
    os.makedirs(carpeta, exist_ok=True)
    with io.open(os.path.join(carpeta, "config.json"), "w",
                 encoding="utf-8") as f:
        f.write(config)
    with io.open(os.path.join(carpeta, "pytorch_model.bin"), "wb") as f:
        f.write(pesos)
    with io.open(os.path.join(carpeta, "label_mapping.json"), "w",
                 encoding="utf-8") as f:
        json.dump(ETIQUETAS, f)
    return carpeta


def _par(id_par, texto, pmid=1):
    return {"text": texto, "label": "", "pmid": pmid, "tf": "MexT",
            "target": "mexE", "id_par": id_par, "seccion": "results",
            "fuente": "fulltext", "autorregulacion": False,
            "redaccion": "directa"}


def _pred(id_par, clase="activates", pmid=1):
    p = dict(("p_" + e, 0.1) for e in ETIQUETAS)
    p["p_" + clase] = 0.7
    d = {"id_par": id_par, "pmid": pmid, "tf": "MexT", "target": "mexE",
         "prediccion": clase}
    d.update(p)
    d.update(seccion="results", fuente="fulltext", autorregulacion=False,
             redaccion="directa")
    return d


def _escribir_jsonl(ruta, filas):
    with io.open(ruta, "w", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps(fila) + "\n")


class PruebasParesDesdeElBronce(unittest.TestCase):
    """Con el diccionario real: el marcado es el del contrato."""

    @classmethod
    def setUpClass(cls):
        from grn_bronce import identificar, operones
        cls.lex = identificar.cargar_lexico()
        cls.locus = identificar.cargar_locus_tags()
        cls.catalogo = operones.Catalogo.cargar(operones.RUTA_POR_OMISION)

    def _candidata(self, oracion, num=0, regulador="", blanco=""):
        return {"pmid": "123", "seccion": "results", "fuente_texto": "xml",
                "num_oracion": str(num), "oracion": oracion,
                "corrida_id": "4", "regulador_candidato": regulador,
                "blanco_candidato": blanco}

    def test_una_oracion_con_tf_da_pares_marcados_y_verificados(self):
        c = self._candidata("MexT activates the expression of mexE in this "
                            "strain under these conditions.",
                            regulador="mexT", blanco="mexE")
        candidatos, informe = puente.pares_de_candidatas(
            [c], self.lex, self.locus, self.catalogo)
        self.assertTrue(candidatos)
        filas = [f for f, _ in candidatos]
        par = [f for f in filas if f["tf_id"] == "mexT"
               and f["target_id"] == "mexE"]
        self.assertEqual(len(par), 1)
        self.assertIn("<e1> MexT </e1>", par[0]["text"])
        self.assertEqual(par[0]["par_del_bronce"], "directo")
        self.assertTrue(par[0]["tf_locus"][0].startswith("PA"))
        self.assertEqual(par[0]["fuente"], "fulltext")
        self.assertEqual(par[0]["fuente_texto"], "xml")
        self.assertEqual(par[0]["corrida_bronce"], 4)
        self.assertEqual(informe["pares"], len(candidatos))

    def test_una_oracion_sin_tf_no_da_pares(self):
        c = self._candidata("The mexE and oprN genes are adjacent in the "
                            "chromosome of this bacterium.")
        candidatos, informe = puente.pares_de_candidatas(
            [c], self.lex, self.locus, self.catalogo)
        self.assertEqual(candidatos, [])
        self.assertEqual(informe["oraciones_con_par"], 0)

    def test_el_limite_corta_las_oraciones_leidas(self):
        cs = [self._candidata("MexT activates mexE expression in the "
                              "wild-type strain.", num=i) for i in range(5)]
        _, informe = puente.pares_de_candidatas(cs, self.lex, self.locus,
                                                self.catalogo, limite=2)
        self.assertEqual(informe["oraciones_leidas"], 2)

    def test_locus_de_resuelve_genes_y_no_inventa(self):
        self.assertEqual(puente.locus_de("PA0425", self.locus, None),
                         ["PA0425"])
        self.assertTrue(puente.locus_de("mexT", self.locus, self.catalogo))
        self.assertEqual(puente.locus_de("noExisteXyz", self.locus,
                                         self.catalogo), [])
        self.assertEqual(puente.locus_de("", self.locus, self.catalogo), [])

    def test_par_del_bronce(self):
        self.assertEqual(puente.par_del_bronce("a", "b", "a", "b"), "directo")
        self.assertEqual(puente.par_del_bronce("a", "b", "b", "a"), "inverso")
        self.assertEqual(puente.par_del_bronce("a", "c", "a", "b"), "otro")
        self.assertEqual(puente.par_del_bronce("a", "b", "", ""), "sin_par")


class PruebasCacheYClasificacion(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.modelo = _modelo(os.path.join(self.tmp.name, "modelo"))
        self.carpeta = os.path.join(self.tmp.name, "corrida")
        os.makedirs(self.carpeta)

    def _vieja(self, nombre, pares, preds, modelo=None):
        """Una carpeta de una corrida anterior, con su meta."""
        d = os.path.join(self.tmp.name, nombre)
        os.makedirs(d)
        _escribir_jsonl(os.path.join(d, "pares.jsonl"), pares)
        _escribir_jsonl(os.path.join(d, "predicciones.jsonl"), preds)
        firma = puente.firma_del_modelo(modelo or self.modelo)
        with io.open(os.path.join(d, "predicciones_meta.json"), "w",
                     encoding="utf-8") as f:
            json.dump(dict(firma, do_lower_case=True, n_entrada=len(pares)),
                      f)
        return d

    def _falso_clasificar(self, clase="represses"):
        """Hace de clasificar.py: escribe predicciones de lo pendiente y,
        como `--reanudar`, adopta una salida completa que ya exista. Su meta
        trae lo que trae el de verdad: sin huellas de pesos."""

        def correr(argv, **kw):
            modelo = argv[argv.index("--modelo") + 1]
            entrada = argv[argv.index("--entrada") + 1]
            salida = argv[argv.index("--salida") + 1]
            meta = argv[argv.index("--meta") + 1]
            pares = puente.leer_jsonl(entrada)
            if not os.path.exists(salida):
                _escribir_jsonl(salida, [_pred(p["id_par"], clase)
                                         for p in pares])
            firma = puente.firma_del_modelo(modelo)
            with io.open(meta, "w", encoding="utf-8") as f:
                json.dump({"sha1_config": firma["sha1_config"],
                           "id2label": firma["id2label"],
                           "max_length": firma["max_length"],
                           "modelo": os.path.abspath(modelo),
                           "do_lower_case": True}, f)
            return {"codigo": 0, "segundos": 0.0}
        return correr

    def test_lo_reutilizable_no_llama_al_modelo(self):
        pares = [_par("a", "texto <e1> A </e1> y <e2> b </e2> uno"),
                 _par("b", "texto <e1> A </e1> y <e2> c </e2> dos")]
        vieja = self._vieja("vieja", pares, [_pred("a"), _pred("b")])
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=AssertionError("no debía clasificar")):
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        reusar_de=[vieja])
        self.assertEqual((r["reutilizadas"], r["nuevas"]), (2, 0))
        preds = puente.leer_jsonl(os.path.join(self.carpeta,
                                               "predicciones.jsonl"))
        self.assertEqual(list(preds[0].keys()),
                         puente.COLUMNAS_PREDICCION)

    def test_la_segunda_corrida_no_hace_nada(self):
        pares = [_par("a", "uno <e1> A </e1> <e2> b </e2>")]
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            puente.clasificar_pares(self.carpeta, self.modelo)
            self.assertEqual(m.call_count, 1)
            # clasificar.py nace en el grupo de este proceso: en Linux, con
            # sesión propia, el killpg con que el flujo cancela no lo alcanza.
            self.assertIs(m.call_args[1].get("nueva_sesion"), False)
            self.assertEqual(m.call_args[1].get("cwd"), puente._RAIZ)
            r = puente.clasificar_pares(self.carpeta, self.modelo)
            self.assertEqual(m.call_count, 1)
        self.assertFalse(r["hecho"])

    def test_la_cache_es_por_texto_y_no_por_id_par(self):
        """Mismo `id_par`, texto distinto: la predicción vieja no sirve."""
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"),
                        [_par("a", "viejo <e1> A </e1> <e2> b </e2>")])
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar("activates")):
            puente.clasificar_pares(self.carpeta, self.modelo)
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"),
                        [_par("a", "nuevo <e1> A </e1> <e2> b </e2>")])
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar("represses")) as m:
            r = puente.clasificar_pares(self.carpeta, self.modelo)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(r["nuevas"], 1)
        pred = puente.leer_jsonl(os.path.join(self.carpeta,
                                              "predicciones.jsonl"))[0]
        self.assertEqual(pred["prediccion"], "represses")

    def test_una_carpeta_de_otro_modelo_no_se_reutiliza(self):
        otro = _modelo(os.path.join(self.tmp.name, "otro"), '{"b": 2}')
        pares = [_par("a", "texto <e1> A </e1> <e2> b </e2>")]
        vieja = self._vieja("vieja", pares, [_pred("a")], modelo=otro)
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        reusar_de=[vieja])
        self.assertEqual(m.call_count, 1)
        self.assertEqual(r["reutilizadas"], 0)

    def test_mismo_config_otros_pesos_es_otro_modelo(self):
        """Dos reentrenamientos de la receta del run 22 escriben el mismo
        config.json: con solo él, la caché le pegaba al modelo nuevo las
        predicciones del viejo."""
        otro = _modelo(os.path.join(self.tmp.name, "otro"), pesos=b"pesos B")
        pares = [_par("a", "texto <e1> A </e1> <e2> b </e2>")]
        vieja = self._vieja("vieja", pares, [_pred("a")], modelo=otro)
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        reusar_de=[vieja])
            self.assertEqual((m.call_count, r["reutilizadas"]), (1, 0))
            # Y en la misma carpeta, el otro modelo no sale por «ya hecho».
            r = puente.clasificar_pares(self.carpeta, otro)
            self.assertEqual((m.call_count, r["nuevas"]), (2, 1))

    def test_un_meta_sin_huella_de_pesos_no_se_reutiliza(self):
        pares = [_par("a", "texto <e1> A </e1> <e2> b </e2>")]
        vieja = self._vieja("vieja", pares, [_pred("a")])
        ruta = os.path.join(vieja, "predicciones_meta.json")
        with io.open(ruta, encoding="utf-8") as f:
            meta = json.load(f)
        del meta["huellas_modelo"]
        with io.open(ruta, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        reusar_de=[vieja])
        self.assertEqual((m.call_count, r["reutilizadas"]), (1, 0))

    def test_lo_que_dejo_a_medias_otro_modelo_no_se_adopta(self):
        """Con la misma lista de pendientes, `--reanudar` adoptaba completo
        el archivo del modelo anterior y el nuevo «clasificaba» 0 pares."""
        pares = [_par("a", "uno <e1> A </e1> <e2> b </e2>")]
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        # El modelo A clasificó y se cortó antes de unir.
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar("activates")), \
                mock.patch.object(puente, "verificar_predicciones",
                                  side_effect=RuntimeError("corte")):
            with self.assertRaises(RuntimeError):
                puente.clasificar_pares(self.carpeta, self.modelo)
        self.assertTrue(os.path.exists(os.path.join(self.carpeta,
                                                    puente.NUEVAS)))
        otro = _modelo(os.path.join(self.tmp.name, "otro"), pesos=b"pesos B")
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar("represses")):
            puente.clasificar_pares(self.carpeta, otro)
        pred = puente.leer_jsonl(os.path.join(self.carpeta,
                                              "predicciones.jsonl"))[0]
        self.assertEqual(pred["prediccion"], "represses")
        # Al unir no queda nada a medias para la siguiente corrida.
        for nombre in (puente.PENDIENTES, puente.PENDIENTES_FIRMA,
                       puente.NUEVAS, puente.NUEVAS_META):
            self.assertFalse(os.path.exists(os.path.join(self.carpeta,
                                                         nombre)), nombre)

    def test_sin_cache_se_clasifica_todo_de_nuevo(self):
        pares = [_par("a", "uno <e1> A </e1> <e2> b </e2>")]
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            puente.clasificar_pares(self.carpeta, self.modelo)
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        usar_cache=False)
        self.assertEqual((m.call_count, r["nuevas"], r["reutilizadas"]),
                         (2, 1, 0))

    def test_una_carpeta_con_pares_rehechos_no_se_reutiliza(self):
        """La unión con otra carpeta es por `id_par`: si su pares.jsonl se
        rehízo después de clasificar, sus predicciones son de otro texto."""
        pares = [_par("a", "texto <e1> A </e1> <e2> b </e2>")]
        vieja = self._vieja("vieja", pares, [_pred("a")])
        ruta = os.path.join(vieja, "predicciones_meta.json")
        with io.open(ruta, encoding="utf-8") as f:
            meta = json.load(f)
        meta["huella_pares"] = "0" * 16
        with io.open(ruta, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        reusar_de=[vieja])
        self.assertEqual((m.call_count, r["reutilizadas"]), (1, 0))

    def test_sin_huella_de_pares_se_exige_el_mismo_conteo(self):
        pares = [_par("a", "texto <e1> A </e1> <e2> b </e2>")]
        vieja = self._vieja("vieja", pares, [_pred("a")])
        _escribir_jsonl(os.path.join(vieja, "pares.jsonl"),
                        pares + [_par("b", "otro <e1> A </e1> <e2> c </e2>")])
        _escribir_jsonl(os.path.join(self.carpeta, "pares.jsonl"), pares)
        with mock.patch("grn_comun.proceso.correr",
                        side_effect=self._falso_clasificar()) as m:
            r = puente.clasificar_pares(self.carpeta, self.modelo,
                                        reusar_de=[vieja])
        self.assertEqual((m.call_count, r["reutilizadas"]), (1, 0))

    def test_rel_del_cli_aguanta_otra_unidad(self):
        """`os.path.relpath` lanza ValueError entre unidades de Windows y
        tumbaba el paso biobert antes de clasificar."""
        from grn_verificacion import cli
        with mock.patch("os.path.relpath", side_effect=ValueError("otra")):
            r = cli._rel(os.path.join(self.tmp.name, "modelo"))
        self.assertEqual(r, os.path.abspath(os.path.join(
            self.tmp.name, "modelo")).replace(os.sep, "/"))
        self.assertNotIn("\\", r)

    def test_un_checkpoint_sin_pesos_no_tiene_firma(self):
        os.remove(os.path.join(self.modelo, "pytorch_model.bin"))
        with self.assertRaises(puente.ErrorPuente):
            puente.firma_del_modelo(self.modelo)

    def test_la_guarda_rechaza_probabilidades_que_no_suman_uno(self):
        pares = [_par("a", "x")]
        mala = _pred("a")
        mala["p_activates"] = 0.99
        self.assertIsNotNone(puente.verificar_predicciones(pares, [mala]))
        self.assertIsNone(puente.verificar_predicciones(pares, [_pred("a")]))

    def test_label_mapping_con_otras_etiquetas_se_rechaza(self):
        with io.open(os.path.join(self.modelo, "label_mapping.json"), "w",
                     encoding="utf-8") as f:
            json.dump(["a", "b", "c", "d"], f)
        with self.assertRaises(puente.ErrorPuente):
            puente.firma_del_modelo(self.modelo)


class PruebasCompatibilidad(unittest.TestCase):

    def test_el_nucleo_se_lee_con_python_3_8(self):
        carpeta = os.path.dirname(os.path.abspath(__file__))
        for nombre in sorted(os.listdir(carpeta)):
            if nombre.endswith(".py"):
                with io.open(os.path.join(carpeta, nombre),
                             encoding="utf-8") as f:
                    ast.parse(f.read(), feature_version=(3, 8))
        for ruta in (os.path.join(_RAIZ, "flujo.py"),
                     os.path.join(_RAIZ, "grn_comun", "proceso.py")):
            with io.open(ruta, encoding="utf-8") as f:
                ast.parse(f.read(), feature_version=(3, 8))

    def test_importar_el_nucleo_no_trae_torch(self):
        bloqueo = dict((m, None) for m in ("torch", "transformers",
                                           "strands", "spacy"))
        with mock.patch.dict(sys.modules, bloqueo):
            for m in ("grn_verificacion.puente", "grn_verificacion.capa",
                      "grn_verificacion.evaluar"):
                sys.modules.pop(m, None)
                __import__(m)


if __name__ == "__main__":
    unittest.main()
