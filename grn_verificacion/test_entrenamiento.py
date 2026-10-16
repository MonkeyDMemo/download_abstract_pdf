"""Pruebas de la construcción de ejemplos, con pares y base SINTÉTICOS.

Genes, locus, PMIDs y oraciones son de juguete. La base curada no entra aquí
ni como dato ni como fixture: lo que se prueba son las reglas (qué fila da
positivos, qué par puede ser negativo, qué se reserva) y lo que la salida
promete (la acepta `etapa2/particionar.py`, y el log no lleva contenido).
"""

import argparse
import ast
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from grn_bronce import texto as _texto
from grn_verificacion import entrenamiento as E
from grn_verificacion.test_validacion import ENCABEZADOS, construir_xlsx


def par(pmid, tf, target, tf_locus, target_locus, id_par,
        resto="in the test strain", auto=False, texto=None, oracion=None):
    """Una línea de `pares.jsonl` con el esquema del puente."""
    if oracion is None:
        oracion = "%s controls %s %s." % (tf, target, resto)
    if texto is None:
        texto = "<e1> %s </e1> controls <e2> %s </e2> %s ." % (tf, target, resto)
    return {
        "text": texto, "label": "", "pmid": int(pmid), "tf": tf,
        "target": target, "id_par": id_par, "seccion": "abstract",
        "fuente": "abstract", "n_oracion": 0, "oracion_cruda": oracion,
        "mencion_tf": tf, "mencion_target": target, "pos_tf": 0,
        "pos_target": len(tf) + 10, "distancia": 10, "autorregulacion": auto,
        "redaccion": "otra", "n_menciones_oracion": 2, "target_es_tf": False,
        "corrida_bronce": 4, "fuente_texto": "abstract", "num_oracion": 0,
        "tf_id": tf, "target_id": target, "tf_locus": list(tf_locus),
        "target_locus": list(target_locus), "par_del_bronce": "directo",
        "regulador_candidato": tf, "blanco_candidato": target,
    }


def fila(regulador, blanco, signo, pmids, origen="historica",
         homologia=False):
    """Una interacción como la deja `validacion.normalizar`."""
    return {"fila_origen": 2, "regulador": regulador, "blanco": blanco,
            "signo": signo, "pmids": [str(p) for p in pmids],
            "origen": origen, "homologia": homologia}


def _ids(ejemplos, etiqueta=None):
    return set(e["id_par"] for e in ejemplos
               if etiqueta is None or e["label"] == etiqueta)


def _cargar_particionar():
    """`etapa2/particionar.py` como módulo: `etapa2` no es paquete."""
    ruta = os.path.join(E.RAIZ_REPO, "etapa2", "particionar.py")
    spec = importlib.util.spec_from_file_location("particionar_prueba", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class PruebasConstruir(unittest.TestCase):

    def test_positivos_con_su_etiqueta(self):
        filas = [fila("PA0001", "PA0002", "+", [11111111]),
                 fila("PA0001", "PA0003", "-", [11111111]),
                 fila("PA0004", "PA0005", "?", [22222222])]
        pares = [
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "p1"),
            par(11111111, "QzaR", "wvbA", ["PA0001"], ["PA0003"], "p2"),
            par(22222222, "QzbR", "wvcA", ["PA0004"], ["PA0005"], "p3"),
            # El par está curado, pero este artículo no es el que se cita.
            par(33333333, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "p4",
                resto="elsewhere"),
        ]
        ejemplos, c = E.construir(pares, filas, proporcion_negativos=0)
        self.assertEqual({"p1": "activates", "p2": "represses",
                          "p3": "regulates"},
                         dict((e["id_par"], e["label"]) for e in ejemplos))
        self.assertEqual(3, c["positivos"])
        self.assertEqual(3, c["filas_elegibles_con_oracion"])
        self.assertEqual({"activates": 1, "no_relation": 0, "regulates": 1,
                          "represses": 1}, c["por_etiqueta"])

    def test_el_operon_se_compara_por_sus_genes(self):
        filas = [fila("PA0001", "PA0007", "+", [11111111])]
        pares = [par(11111111, "QzaR", "wvoABC", ["PA0001"],
                     ["PA0006", "PA0007", "PA0008"], "op")]
        ejemplos, _ = E.construir(pares, filas, proporcion_negativos=0)
        self.assertEqual([("op", "activates")],
                         [(e["id_par"], e["label"]) for e in ejemplos])

    def test_filas_que_no_dan_positivos(self):
        filas = [
            fila("PA0001", "PA0002", "+", [11111111], homologia=True),
            fila("PA0001", "PA0003", "+", [11111111], origen="biobert"),
            fila("PA0001", "PA0004", "d", [11111111]),
            fila("PA0001", "PA0005", None, [11111111]),
            fila("PA0006", "PA0006", "-", [11111111]),
            fila("PA0001", "PA0009", "+", []),
            fila("PA0001", "PA0010", "-", [11111111], origen="ambos"),
        ]
        pares = [
            par(11111111, "QzaR", "wvhA", ["PA0001"], ["PA0002"], "h"),
            par(11111111, "QzaR", "wvbA", ["PA0001"], ["PA0003"], "b"),
            par(11111111, "QzaR", "wvdA", ["PA0001"], ["PA0004"], "d"),
            par(11111111, "QzaR", "wviA", ["PA0001"], ["PA0005"], "i"),
            par(11111111, "QzsR", "qzsR", ["PA0006"], ["PA0006"], "a",
                auto=True),
            par(11111111, "QzaR", "wvsA", ["PA0001"], ["PA0009"], "s"),
            par(11111111, "QzaR", "wvmA", ["PA0001"], ["PA0010"], "m"),
        ]
        ejemplos, c = E.construir(pares, filas, proporcion_negativos=0)
        self.assertEqual([("m", "represses")],
                         [(e["id_par"], e["label"]) for e in ejemplos])
        self.assertEqual({"homologia": 1, "biobert": 1, "signo_d": 1,
                          "signo_ilegible": 1, "autorregulacion": 1,
                          "sin_pmid": 1}, c["filas_excluidas"])
        self.assertEqual(1, c["filas_elegibles"])
        self.assertEqual(5, c["pares_solo_con_filas_excluidas"])
        self.assertEqual({"ambos": 1}, c["positivos_por_origen"])

    def test_etiquetas_en_conflicto_se_descartan(self):
        filas = [
            fila("PA0001", "PA0002", "+", [11111111]),
            fila("PA0001", "PA0002", "-", [11111111]),
            # Un operón cuyos genes tienen signos distintos.
            fila("PA0001", "PA0006", "+", [11111111]),
            fila("PA0001", "PA0007", "?", [11111111]),
            # Mismo signo desde dos orígenes: no es conflicto.
            fila("PA0003", "PA0004", "+", [11111111]),
            fila("PA0003", "PA0004", "+", [11111111], origen="ambos"),
        ]
        pares = [
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "c1"),
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "c2",
                resto="again"),
            par(11111111, "QzaR", "wvoAB", ["PA0001"], ["PA0006", "PA0007"],
                "c3"),
            par(11111111, "QzbR", "wvbA", ["PA0003"], ["PA0004"], "ok"),
        ]
        ejemplos, c = E.construir(pares, filas, proporcion_negativos=0)
        self.assertEqual([("ok", "activates")],
                         [(e["id_par"], e["label"]) for e in ejemplos])
        self.assertEqual(2, c["claves_en_conflicto"])
        self.assertEqual(3, c["pares_en_conflicto"])
        self.assertEqual({"ambos+historica": 1}, c["positivos_por_origen"])

    def test_tope_por_par_y_oraciones_duplicadas(self):
        filas = [fila("PA0001", "PA0002", "+", [11111111])]
        pares = [par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"],
                     "t%d" % i, resto="variant %s" % letra)
                 for i, letra in enumerate("abcdef")]
        # La misma oración que `t0`, con otros espacios: el mismo resumen
        # leído por la base y por el texto completo.
        pares.append(par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"],
                         "t9", resto="variant a",
                         oracion="QzaR  controls wvaA\nvariant a."))
        ejemplos, c = E.construir(pares, filas, max_por_par=3,
                                  proporcion_negativos=0)
        self.assertEqual(3, len(ejemplos))
        self.assertEqual(1, c["oraciones_duplicadas"])
        self.assertEqual(3, c["recortados_por_tope"])
        self.assertNotIn("t9", _ids(ejemplos))

    def test_negativos_solo_de_pares_sin_relacion_curada(self):
        filas = [
            fila("PA0001", "PA0002", "+", [11111111]),
            # En otro artículo y excluidas como positivas, pero el par está
            # curado: no puede ser negativo en ninguna dirección.
            fila("PA0008", "PA0001", "-", [99999999], homologia=True),
            fila("PA0001", "PA0009", "+", [99999999], origen="biobert"),
        ]
        pares = [
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "pos"),
            par(11111111, "WvaA", "QzaR", ["PA0002"], ["PA0001"], "inv",
                resto="reverse"),
            par(11111111, "QzaR", "wvhA", ["PA0001"], ["PA0008"], "hom",
                resto="hom"),
            par(11111111, "QzaR", "wviA", ["PA0001"], ["PA0009"], "bio",
                resto="bio"),
            par(11111111, "QzcR", "qzcR", ["PA0010"], ["PA0010"], "aut",
                resto="auto", auto=True),
            par(11111111, "QzdR", "wvdA", ["PA0011"], ["PA0012"], "n1",
                resto="clean one"),
            par(11111111, "QzeR", "wveA", ["PA0013"], ["PA0014"], "n2",
                resto="clean two"),
            # Un artículo sin positivos no da negativos: la base no lo leyó.
            par(44444444, "QzfR", "wvfA", ["PA0015"], ["PA0016"], "lejos",
                resto="far"),
        ]
        ejemplos, c = E.construir(pares, filas)
        negativos = _ids(ejemplos, "no_relation")
        self.assertEqual(1, len(negativos))
        self.assertTrue(negativos <= {"n1", "n2"})
        self.assertEqual(3, c["negativos_descartados_par_curado"])
        self.assertEqual(1, c["negativos_descartados_autorregulacion"])
        self.assertEqual(2, c["candidatos_negativos"])
        self.assertEqual(1, c["negativos_muestreados"])

        ejemplos, c = E.construir(pares, filas, proporcion_negativos=5)
        self.assertEqual({"n1", "n2"}, _ids(ejemplos, "no_relation"))
        self.assertEqual(0, c["negativos_en_oracion_con_positivo"])

    def test_un_negativo_puede_compartir_oracion_con_un_positivo(self):
        oracion = "QzaR controls wvaA but not wvdA."
        filas = [fila("PA0001", "PA0002", "+", [11111111])]
        pares = [
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "pos",
                oracion=oracion,
                texto="<e1> QzaR </e1> controls <e2> wvaA </e2> but not wvdA ."),
            par(11111111, "QzaR", "wvdA", ["PA0001"], ["PA0011"], "neg",
                oracion=oracion,
                texto="<e1> QzaR </e1> controls wvaA but not <e2> wvdA </e2> ."),
        ]
        ejemplos, c = E.construir(pares, filas)
        self.assertEqual({"neg"}, _ids(ejemplos, "no_relation"))
        self.assertEqual(1, c["negativos_en_oracion_con_positivo"])

    def test_reservas_por_pmid_y_por_oracion(self):
        filas = [fila("PA0001", "PA0002", "+", [11111111, 22222222, 33333333])]
        pares = [
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "r1"),
            par(11111111, "QzbR", "wvbA", ["PA0003"], ["PA0004"], "r1n"),
            par(22222222, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "r2",
                resto="second"),
            par(22222222, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "r2b",
                resto="third"),
            par(33333333, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "r3",
                resto="fourth"),
        ]
        carpeta = tempfile.mkdtemp(prefix="grn_res_")
        self.addCleanup(shutil.rmtree, carpeta, True)
        ruta = os.path.join(carpeta, "reservas.tsv")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("pmid\t11111111\noracion\tQzaR   controls wvaA second.\n")
        reservas, conteos_reservas = E.leer_reservas([ruta])
        self.assertEqual({"archivos": 1, "pmids": 1, "oraciones": 1},
                         conteos_reservas)

        ejemplos, c = E.construir(pares, filas, reservas,
                                  proporcion_negativos=5)
        self.assertEqual({"r2b", "r3"}, _ids(ejemplos))
        self.assertEqual(2, c["reservados_por_pmid"])
        self.assertEqual(1, c["reservados_por_oracion"])
        self.assertEqual(1, c["pmids_reservados_presentes"])

    def test_la_reserva_alcanza_a_la_oracion_cortada_de_otra_forma(self):
        """El bronce y el conjunto ciego no siempre cortan igual: una oración
        reservada puede llegar al corpus como un pedazo, o dentro de una más
        larga. Por igualdad se colaban; un pedazo corto no debe apartar
        nada."""
        filas = [fila("PA0001", "PA0002", "+", [11111111])]
        larga = ("QzaR controls wvaA in the test strain under low iron, and "
                 "the effect disappears in the qzaR deletion mutant.")
        pedazo = "QzaR controls wvaA in the test strain under low iron"
        pares = [
            # Pedazo de una reservada: se aparta.
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "pedazo",
                oracion=pedazo),
            # Contiene a la reservada: se aparta.
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "contiene",
                oracion="In short, " + larga + " Nothing else."),
            # Comparte menos de MINIMO_CONTENCION caracteres: se queda.
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "corta",
                oracion="QzaR controls wvaA."),
        ]
        reservas = {"pmids": set(), "oraciones": {larga}}
        ejemplos, c = E.construir(pares, filas, reservas,
                                  proporcion_negativos=0)
        self.assertGreaterEqual(len(pedazo), E.MINIMO_CONTENCION)
        self.assertEqual({"corta"}, _ids(ejemplos))
        self.assertEqual(2, c["reservados_por_oracion"])

    def test_determinista_y_dependiente_de_la_semilla(self):
        filas = [fila("PA0001", "PA0002", "+", [11111111])]
        pares = [par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"],
                     "s%02d" % i, resto="variant %d" % i) for i in range(10)]
        primera, _ = E.construir(pares, filas, semilla=7,
                                 proporcion_negativos=0)
        segunda, _ = E.construir(list(reversed(pares)), filas, semilla=7,
                                 proporcion_negativos=0)
        self.assertEqual(primera, segunda)
        elecciones = set()
        for semilla in range(1, 7):
            ejemplos, _ = E.construir(pares, filas, semilla=semilla,
                                      proporcion_negativos=0)
            self.assertEqual(3, len(ejemplos))
            elecciones.add(tuple(sorted(_ids(ejemplos))))
        self.assertGreater(len(elecciones), 1)

    def test_texto_repetido_entre_articulos_se_queda_en_uno(self):
        filas = [fila("PA0001", "PA0002", "+", [11111111, 22222222])]
        pares = [
            # Iguales para la verificación de particionar.py (sin
            # puntuación ni mayúsculas), distintos para su agrupamiento.
            par(22222222, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "x2",
                oracion="QzaR controls wvaA, here.",
                texto="<e1> QzaR </e1> controls <e2> wvaA </e2> , here ."),
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "x1",
                oracion="QzaR controls wvaA here.",
                texto="<e1> QzaR </e1> controls <e2> wvaA </e2> here ."),
        ]
        ejemplos, c = E.construir(pares, filas, proporcion_negativos=0)
        self.assertEqual({"x1"}, _ids(ejemplos))
        self.assertEqual(1, c["repetidos_entre_pmids"])

    def test_pares_inservibles(self):
        filas = [fila("PA0001", "PA0002", "+", [11111111])]
        pares = [
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "bueno"),
            par(11111111, "QzaR", "wvoX", ["PA0001"], [], "vacio",
                resto="empty"),
            par(11111111, "QzaR", "wvpA", ["PA0001"], ["PA14_12345"], "pa14",
                resto="other strain"),
            par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "roto",
                resto="broken", texto="QzaR controls <e2> wvaA </e2> ."),
        ]
        ejemplos, c = E.construir(pares, filas, proporcion_negativos=0)
        self.assertEqual({"bueno"}, _ids(ejemplos))
        self.assertEqual(1, c["sin_locus"])
        self.assertEqual(1, c["locus_no_pao1"])
        self.assertEqual(1, c["marcado_invalido"])

    def test_formato_de_salida(self):
        filas = [fila("PA0001", "PA0002", "-", [11111111])]
        pares = [par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "f1"),
                 par(11111111, "QzbR", "wvbA", ["PA0003"], ["PA0004"], "f2",
                     resto="no relation here")]
        ejemplos, _ = E.construir(pares, filas)
        self.assertEqual(2, len(ejemplos))
        for e in ejemplos:
            self.assertEqual(["text", "label", "pmid", "tf", "target",
                              "id_par"], list(e))
            self.assertIsInstance(e["pmid"], int)
            self.assertIn(e["label"], E.ETIQUETAS)
            self.assertIn("<e1>", e["text"])

    def test_parametros_invalidos(self):
        with self.assertRaises(ValueError):
            E.construir([], [], max_por_par=0)
        with self.assertRaises(ValueError):
            E.construir([], [], proporcion_negativos=-1)
        malo = par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "m")
        malo["pmid"] = "doce"
        with self.assertRaises(ValueError):
            E.construir([malo], [])


class PruebasComoParticionar(unittest.TestCase):
    """Lo que esta salida tiene que compartir con `etapa2/particionar.py`."""

    @classmethod
    def setUpClass(cls):
        cls.particionar = _cargar_particionar()

    def test_mismas_etiquetas_en_el_mismo_orden(self):
        self.assertEqual(list(self.particionar.ETIQUETAS), list(E.ETIQUETAS))

    def test_misma_forma_canonica(self):
        muestras = [
            "<e1> LasR </e1> activates <e2> rhlR </e2> .",
            "<e1>LasR</e1>-dependent  <e2>rhlR</e2>, (ΔlasR) é!",
            "  ",
        ]
        for m in muestras:
            self.assertEqual(self.particionar.canonico(m), E.canonico(m), m)


class PruebasReservas(unittest.TestCase):

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix="grn_res_")
        self.addCleanup(shutil.rmtree, self.carpeta, True)

    def ruta(self, nombre):
        return os.path.join(self.carpeta, nombre)

    def escribir(self, nombre, contenido, encoding="utf-8"):
        with open(self.ruta(nombre), "w", encoding=encoding) as f:
            f.write(contenido)
        return self.ruta(nombre)

    def test_ida_y_vuelta(self):
        conteos = E.escribir_reservas(
            self.ruta("r.tsv"), ["12345678", 2345678],
            [u"Una  oración\tcon tabulador", "otra", "  "])
        self.assertEqual({"pmids": 2, "oraciones": 2}, conteos)
        reservas, _ = E.leer_reservas([self.ruta("r.tsv")])
        self.assertEqual({"12345678", "2345678"}, reservas["pmids"])
        self.assertEqual({u"Una oración con tabulador", "otra"},
                         reservas["oraciones"])
        # Una ruta suelta, sin lista, es un archivo y no una lista de letras.
        self.assertEqual(reservas, E.leer_reservas(self.ruta("r.tsv"))[0])

    def test_comentarios_bom_y_tipos(self):
        ruta = self.escribir(
            "r.tsv", u"# comentario\n\nPMID\t 1234567 \noración\tUna frase."
                     u"\n", encoding="utf-8-sig")
        reservas, conteos = E.leer_reservas([ruta])
        self.assertEqual({"1234567"}, reservas["pmids"])
        self.assertEqual({"Una frase."}, reservas["oraciones"])
        self.assertEqual({"archivos": 1, "pmids": 1, "oraciones": 1}, conteos)

    def test_una_reserva_mal_escrita_detiene_la_lectura(self):
        for contenido in ("gen\tlasR\n", "pmid 12345678\n", "pmid\tdoce\n"):
            ruta = self.escribir("malo.tsv", contenido)
            with self.assertRaises(ValueError):
                E.leer_reservas([ruta])

    def test_desde_el_csv_de_juicios(self):
        csv_ruta = self.escribir(
            "juicios.csv",
            "pmid,oracion,regulador\n11111111,\"Una, con coma.\",x\n"
            "22222222,Otra.,y\n11111111,Tercera.,z\n")
        conteos = E.escribir_reservas_de_juicios(
            self.ruta("r.tsv"), ruta_csv=csv_ruta,
            oraciones_extra=["Extra   frase."])
        self.assertEqual({"pmids": 2, "oraciones": 1}, conteos)
        reservas, _ = E.leer_reservas([self.ruta("r.tsv")])
        self.assertEqual({"11111111", "22222222"}, reservas["pmids"])
        self.assertEqual({"Extra frase."}, reservas["oraciones"])
        pmids, oraciones = E.reservas_de_csv(csv_ruta, "pmid", "oracion")
        self.assertEqual(3, len(oraciones))
        with self.assertRaises(ValueError):
            E.reservas_de_csv(csv_ruta, "no_existe")

    def test_el_csv_versionado_de_juicios_da_pmids(self):
        if not os.path.exists(E.RUTA_JUICIOS):
            self.skipTest("No está el CSV de la muestra de 50 juicios.")
        pmids, _ = E.reservas_de_csv(E.RUTA_JUICIOS)
        self.assertTrue(pmids)
        self.assertTrue(all(p.isdigit() for p in pmids))


class PruebasLeerPares(unittest.TestCase):

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix="grn_par_")
        self.addCleanup(shutil.rmtree, self.carpeta, True)

    def test_faltan_campos_y_json_roto(self):
        ruta = os.path.join(self.carpeta, "pares.jsonl")
        incompleto = par(11111111, "QzaR", "wvaA", ["PA0001"], ["PA0002"], "a")
        del incompleto["tf_locus"]
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(json.dumps(incompleto) + "\n")
        with self.assertRaises(ValueError) as ctx:
            E.leer_pares(ruta)
        self.assertIn("tf_locus", str(ctx.exception))
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("{roto\n")
        with self.assertRaises(ValueError):
            E.leer_pares(ruta)

    def test_solo_conserva_lo_que_usa(self):
        ruta = os.path.join(self.carpeta, "pares.jsonl")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(json.dumps(par(11111111, "QzaR", "wvaA", ["PA0001"],
                                   ["PA0002"], "a")) + "\n\n")
        pares = E.leer_pares(ruta)
        self.assertEqual(1, len(pares))
        self.assertEqual(set(E.CAMPOS_PAR), set(pares[0]))


# Treinta artículos de juguete: en cada uno, una oración con el par curado y
# dos con pares sin relación. Son los que hacen falta para que el reparto
# 80/10/10 de particionar.py llene dev y test; con una docena, dejar dev
# vacío le sale más barato que llenarlo.
CODIGOS = ["%s%s" % (a, b) for a in "abcdefghij" for b in "abc"]
PMID_BASE = 30000001
PMID_AJENO = 99999901


def _corpus():
    """(filas del .xlsx, pares, nombres que no pueden salir en el log)."""
    filas = {1: ENCABEZADOS}
    pares, nombres = [], set()
    numero = 2
    for i, cod in enumerate(CODIGOS):
        pmid = PMID_BASE + i
        tf, tg, n1, n2 = ("Qz%sR" % cod, "wv%sA" % cod, "ny%sB" % cod,
                          "ny%sC" % cod)
        nombres.update([tf, tg, n1, n2])
        tf_l, tg_l = "PA1%03d" % i, "PA2%03d" % i
        n1_l, n2_l = "PA3%03d" % i, "PA4%03d" % i
        signo = ("+", "-", "Unknown")[i % 3]
        referencia = (("num", str(pmid)), "%d.0" % pmid,
                      "%d, %d" % (pmid, PMID_AJENO))[i % 3]
        origen = u"Histórica" if i % 4 else "Ambos"
        filas[numero] = [tf.lower(), tg, signo, referencia, tf_l, tg_l, origen,
                         "sintetica"]
        numero += 1
        pares.append(par(pmid, tf, tg, [tf_l], [tg_l], "pos%s" % cod,
                         resto="during florbination %s" % cod))
        pares.append(par(pmid, tf, n1, [tf_l], [n1_l], "neg1%s" % cod,
                         resto="near florbination %s" % cod))
        pares.append(par(pmid, tf, n2, [tf_l], [n2_l], "neg2%s" % cod,
                         resto="after florbination %s" % cod))
    # Homología en otro artículo: veta al primer negativo del artículo 0.
    filas[numero] = ["x", "y", "-", "homology PA14", "PA1000", "PA3000",
                     u"Histórica", ""]
    # BioBERT con otro signo sobre un par ya curado: no da positivo ni
    # conflicto.
    filas[numero + 1] = ["x", "y", "+", str(PMID_BASE + 1), "PA1001", "PA2001",
                         "BioBERT", ""]
    return filas, pares, nombres


class PruebasEjecutar(unittest.TestCase):

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix="grn_ent_")
        self.addCleanup(shutil.rmtree, self.carpeta, True)
        filas, pares, self.nombres = _corpus()
        self.base = construir_xlsx(os.path.join(self.carpeta, "base.xlsx"),
                                   [("Hoja1", filas)])
        self.pares = os.path.join(self.carpeta, "pares.jsonl")
        with open(self.pares, "w", encoding="utf-8") as f:
            for p in pares:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        self.reservas = os.path.join(self.carpeta, "reservas.tsv")
        E.escribir_reservas(
            self.reservas, [PMID_BASE + 29],
            ["QzjbR  controls nyjbC after florbination jb."])
        self.salida = os.path.join(self.carpeta, "salida", "curada")
        self.pmids = [str(PMID_BASE + i) for i in range(len(CODIGOS))]
        self.pmids.append(str(PMID_AJENO))

    def correr(self, **kwargs):
        lineas = []
        conteos = E.ejecutar(self.pares, self.base, [self.reservas],
                             self.salida, log=lineas.append, **kwargs)
        return conteos, lineas

    def test_escribe_y_particionar_la_acepta(self):
        conteos, _ = self.correr()
        e = conteos["entrenamiento"]
        self.assertEqual(29, e["positivos"])
        self.assertEqual(29, e["negativos"])
        self.assertEqual({"activates": 10, "no_relation": 29, "regulates": 9,
                          "represses": 10}, e["por_etiqueta"])
        self.assertEqual(3, e["reservados_por_pmid"])
        self.assertEqual(1, e["reservados_por_oracion"])
        self.assertEqual(56, e["candidatos_negativos"])
        self.assertEqual(1, e["negativos_descartados_par_curado"])
        self.assertEqual({"homologia": 1, "biobert": 1, "signo_d": 0,
                          "signo_ilegible": 0, "autorregulacion": 0,
                          "sin_pmid": 0}, e["filas_excluidas"])
        self.assertEqual(32, conteos["base"]["filas"])

        tamanos = dict((n, os.path.getsize(os.path.join(self.salida, n)))
                       for n in E.ARCHIVOS)
        self.assertEqual(0, tamanos["entity_marked_dev.jsonl"])
        self.assertEqual(0, tamanos["entity_marked_test.jsonl"])
        with open(os.path.join(self.salida, E.ARCHIVO_CONTEOS),
                  encoding="utf-8") as f:
            registro = json.load(f)
        self.assertEqual(json.loads(json.dumps(conteos)), registro["conteos"])
        self.assertEqual(E.SEMILLA, registro["parametros"]["semilla"])

        # Lo que importa: particionar.py la toma tal cual, parte por PMID y
        # no encuentra fuga.
        P = _cargar_particionar()
        filas = P.cargar(self.salida, list(E.ARCHIVOS))
        self.assertEqual(58, len(filas))
        grupos = P.agrupar(filas, "pmid")
        partes, _ = P.repartir(grupos, [0.8, 0.1, 0.1], 20260819, 20)
        self.assertTrue(P.verificar(partes, ["train", "dev", "test"], "pmid",
                                    filas, salida=lambda *a: None))

    def test_el_log_y_los_conteos_no_llevan_contenido(self):
        conteos, lineas = self.correr()
        self.assertTrue(lineas)
        log = "\n".join(lineas).replace(self.salida, "<salida>")
        devueltos = json.dumps(conteos, ensure_ascii=False)
        with open(os.path.join(self.salida, E.ARCHIVO_CONTEOS),
                  encoding="utf-8") as f:
            archivo = f.read()
        for nombre, texto in (("log", log), ("conteos", devueltos),
                              ("conteos.json", archivo)):
            for pmid in self.pmids:
                self.assertNotIn(pmid, texto, nombre)
            for gen in self.nombres:
                self.assertNotIn(gen.lower(), texto.lower(), nombre)
            self.assertNotIn("florbination", texto, nombre)
            self.assertIsNone(re.search(r"PA[0-9]{4}", texto), nombre)
        # Una huella hexadecimal puede traer siete dígitos seguidos; por eso
        # va solo en conteos.json y la búsqueda genérica no mira ahí.
        for nombre, texto in (("log", log), ("conteos", devueltos)):
            self.assertIsNone(re.search(r"[0-9]{7,}", texto), nombre)

    def test_se_niega_a_escribir_dentro_del_repositorio(self):
        dentro = os.path.join(E.RAIZ_REPO, "salidas", "no_debe_existir_grn")
        # Entradas que no existen: si la negativa no fuera lo primero, el
        # error sería otro.
        with self.assertRaises(ValueError) as ctx:
            E.ejecutar("no/existe.jsonl", "no/existe.xlsx", [], dentro)
        self.assertIn("repositorio", str(ctx.exception))
        self.assertFalse(os.path.exists(dentro))

    def test_se_niega_dentro_de_cualquier_copia_de_git(self):
        otra = os.path.join(self.carpeta, "otra_copia")
        os.makedirs(os.path.join(otra, ".git"))
        with self.assertRaises(ValueError) as ctx:
            self.salida = os.path.join(otra, "datos", "curada")
            self.correr()
        self.assertIn("git", str(ctx.exception))
        self.assertFalse(os.path.exists(self.salida))

    def test_una_entrada_que_no_existe_es_error_claro_y_sin_ruta(self):
        """`export BASE_CURADA='~/...'` deja la tilde sin expandir: antes
        salía un traceback de zipfile después de leer todos los pares."""
        for pares, base, reservas, flag in (
                ("no/existe.jsonl", self.base, [], "--pares"),
                (self.pares, "secreto/no_existe.xlsx", [], "--base"),
                (self.pares, self.base, ["no/existe.tsv"], "--reservar")):
            with self.assertRaises(ValueError) as ctx:
                E.ejecutar(pares, base, reservas, self.salida)
            self.assertIn(flag, str(ctx.exception))
            self.assertNotIn("secreto", str(ctx.exception))
        self.assertFalse(os.path.exists(self.salida))

    def test_la_tilde_se_expande(self):
        casa = os.path.dirname(self.base)
        with mock.patch.dict(os.environ, {"HOME": casa, "USERPROFILE": casa}):
            conteos = E.ejecutar(self.pares, os.path.join(
                "~", os.path.basename(self.base)), [self.reservas],
                self.salida)
        self.assertEqual(29, conteos["entrenamiento"]["positivos"])

    def test_la_tilde_de_la_salida_se_expande_antes_de_la_guarda(self):
        """Con `--salida=~/...` la guarda miraba la ruta literal y los
        ejemplos acababan en una carpeta llamada `~`."""
        casa = self.carpeta
        with mock.patch.dict(os.environ, {"HOME": casa, "USERPROFILE": casa}):
            E.ejecutar(self.pares, self.base, [self.reservas],
                       os.path.join("~", "salida_tilde"))
        self.assertTrue(os.path.isfile(os.path.join(
            casa, "salida_tilde", E.ARCHIVO_CONTEOS)))
        self.assertFalse(os.path.exists(os.path.join(os.getcwd(), "~")))

    def test_sin_ejemplos_no_escribe_nada(self):
        vacia = construir_xlsx(os.path.join(self.carpeta, "vacia.xlsx"),
                               [("Hoja1", [ENCABEZADOS])])
        with self.assertRaises(ValueError):
            E.ejecutar(self.pares, vacia, [], self.salida)
        self.assertFalse(os.path.exists(self.salida))

    def test_argumentos_del_cli(self):
        parser = E.agregar_argumentos(argparse.ArgumentParser())
        args = parser.parse_args([
            "--pares", self.pares, "--base", self.base,
            "--reservar", self.reservas, "--reservar", self.reservas,
            "--salida", self.salida, "--max-por-par", "2"])
        self.assertEqual([self.reservas, self.reservas], args.reservar)
        self.assertEqual(2, args.max_por_par)
        self.assertEqual(E.SEMILLA, args.semilla)
        self.assertEqual(E.PROPORCION_NEGATIVOS, args.proporcion_negativos)
        self.assertIsNone(args.hoja)
        conteos = E.desde_argumentos(args)
        self.assertEqual(1, conteos["reservas"]["pmids"])
        self.assertTrue(os.path.exists(os.path.join(self.salida,
                                                    E.ARCHIVOS[0])))


class PruebasCompatibilidad(unittest.TestCase):

    def test_sintaxis_de_python_3_8(self):
        """El servidor corre Python 3.10 y el proyecto promete 3.8."""
        ruta = E.__file__
        if ruta.endswith(".pyc"):
            ruta = ruta[:-1]
        with open(ruta, encoding="utf-8") as f:
            ast.parse(f.read(), filename=ruta, feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
