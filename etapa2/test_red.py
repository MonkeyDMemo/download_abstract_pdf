# -*- coding: utf-8 -*-
"""Pruebas de la etapa 4, la que arma la red.

Las cuatro que no pueden faltar, porque cubren lo que se rompio antes o lo que
al romperse no avisa:

- el umbral es POR CLASE. Uno solo para las tres borra la unica perilla que
  distingue "activa" de "reprime" a la hora de filtrar.
- la dedup va ANTES del tope. Al reves, una oracion citada por tres articulos
  gasta tres cupos y luego se colapsa a uno: el par acaba con menos oraciones
  distintas de las que cabian y las que se descartaron ya no vuelven.
- n_articulos cuenta PMIDs, no evidencias. Deduplicar sin guardar de cuantos
  articulos venia cada oracion tira la senal de confianza mas barata que hay.
- el par contradictorio se degrada a 'regulates', no se resuelve por mayoria
  simple ni se tira.
- la columna `confianza` va vacia cuando ninguna evidencia voto por la clase
  ganadora, en vez de rellenarse con la media sobre toda la evidencia
  contradictoria, que es otro numero bajo la misma etiqueta.

**Las pruebas de orden pasan por `main()`.** La que llevaba antes el nombre
`test_la_dedup_va_antes_del_tope` componia ella misma `topar(deduplicar(...))`
y verificaba una propiedad de su propia llamada: se podia invertir el orden
dentro de `main()` y la suite entera seguia en verde. Una prueba que no puede
fallar cuando el codigo se rompe no es una prueba.

    python -m unittest discover etapa2
"""

import itertools
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import red as R


_ids = itertools.count(1)

ORDEN_BUENO = {"0": "activates", "1": "no_relation",
               "2": "regulates", "3": "represses"}


def probabilidades(clase, prob):
    """El resto se reparte parejo entre las otras tres, asi suman 1."""
    resto = (1.0 - prob) / 3.0
    p = dict((e, resto) for e in R.ETIQUETAS)
    p[clase] = prob
    return p


def fila(tf="MexT", blanco="mexEF-oprN", prediccion="activates", prob=0.9,
         pmid=1, seccion="results", fuente="fulltext", auto=False,
         redaccion="directa", oracion=None, n_oracion=0, id_par=None):
    """Una prediccion ya unida con su candidato, como la ve el pipeline."""
    return {
        "id_par": id_par or ("id%04d" % next(_ids)),
        "pmid": pmid, "tf": tf, "blanco": blanco,
        "prediccion": prediccion, "p": probabilidades(prediccion, prob),
        "seccion": seccion, "fuente": fuente,
        "autorregulacion": auto, "redaccion": redaccion,
        "oracion": oracion or ("%s regula a %s en esta oracion." % (tf, blanco)),
        "n_oracion": n_oracion,
    }


UMBRALES = dict(R.UMBRALES_POR_OMISION)


class PruebasUmbral(unittest.TestCase):
    """Paso 2: fuera no_relation, y cada clase contra SU umbral."""

    def test_no_relation_se_descarta_por_alta_que_venga(self):
        vivas = R.filtrar([fila(prediccion="no_relation", prob=0.99)], UMBRALES)
        self.assertEqual(vivas, [])

    def test_cada_clase_se_mide_contra_su_propio_umbral(self):
        """Con 0.66: activates pasa (0.65), represses no (0.70), regulates si
        (0.60). Un umbral unico dejaria pasar o caeria a las tres juntas."""
        filas = [fila(prediccion="activates", prob=0.66, blanco="a"),
                 fila(prediccion="represses", prob=0.66, blanco="b"),
                 fila(prediccion="regulates", prob=0.66, blanco="c")]
        vivas = R.filtrar(filas, UMBRALES)
        self.assertEqual(sorted(v["blanco"] for v in vivas), ["a", "c"])

    def test_el_umbral_se_alcanza_con_la_igualdad(self):
        justo = R.filtrar([fila(prediccion="represses", prob=0.70)], UMBRALES)
        casi = R.filtrar([fila(prediccion="represses", prob=0.6999)], UMBRALES)
        self.assertEqual(len(justo), 1)
        self.assertEqual(casi, [])

    def test_los_motivos_del_descarte_quedan_contados(self):
        import collections
        cuenta = collections.Counter()
        R.filtrar([fila(prediccion="no_relation", prob=0.9),
                   fila(prediccion="activates", prob=0.10),
                   fila(prediccion="represses", prob=0.10),
                   fila(prediccion="activates", prob=0.99)],
                  UMBRALES, cuenta=cuenta)
        self.assertEqual(cuenta["no_relation"], 1)
        self.assertEqual(cuenta["bajo_umbral_activates"], 1)
        self.assertEqual(cuenta["bajo_umbral_represses"], 1)

    def test_sin_pies_descarta_solo_los_pies(self):
        filas = [fila(seccion="pie_de_figura", blanco="a"),
                 fila(seccion="results", blanco="b")]
        self.assertEqual([v["blanco"] for v in R.filtrar(filas, UMBRALES)],
                         ["a", "b"])
        vivas = R.filtrar(filas, UMBRALES, sin_pies=True)
        self.assertEqual([v["blanco"] for v in vivas], ["b"])

    def test_sin_introduccion_descarta_solo_la_introduccion(self):
        filas = [fila(seccion="introduction", blanco="a"),
                 fila(seccion="discussion", blanco="b")]
        vivas = R.filtrar(filas, UMBRALES, sin_introduccion=True)
        self.assertEqual([v["blanco"] for v in vivas], ["b"])

    def test_la_autorregulacion_se_descarta_por_omision(self):
        """En auditar_signo.py quedaba fuera por estructura de datos, no por un
        condicional. Al generalizar a pares arbitrarios hay que reponerla."""
        filas = [fila(tf="NalD", blanco="nalD", auto=True)]
        self.assertEqual(R.filtrar(filas, UMBRALES), [])
        self.assertEqual(len(R.filtrar(filas, UMBRALES,
                                       incluir_autorregulacion=True)), 1)


class PruebasDedup(unittest.TestCase):
    """Paso 3: la clave es (tf, blanco, oracion). El pmid NO entra."""

    def test_la_misma_oracion_en_tres_articulos_es_una_evidencia(self):
        o = "MexT is a transcriptional activator of mexEF-oprN in PAO1."
        filas = [fila(pmid=p, oracion=o) for p in (11, 22, 33)]
        ev = R.deduplicar(filas)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["pmids"], [11, 22, 33])
        self.assertEqual(ev[0]["n_copias"], 3)

    def test_dos_oraciones_distintas_no_se_colapsan(self):
        filas = [fila(oracion="Una oracion."), fila(oracion="Otra oracion.")]
        self.assertEqual(len(R.deduplicar(filas)), 2)

    def test_dos_pares_en_la_misma_oracion_no_se_colapsan(self):
        o = "MexT activates mexEF-oprN and mexS in PAO1."
        filas = [fila(blanco="mexEF-oprN", oracion=o),
                 fila(blanco="mexS", oracion=o)]
        self.assertEqual(len(R.deduplicar(filas)), 2)

    def test_el_representante_es_el_de_mayor_probabilidad(self):
        o = "MexT activates mexEF-oprN."
        filas = [fila(pmid=5, prob=0.71, oracion=o),
                 fila(pmid=9, prob=0.95, oracion=o)]
        ev = R.deduplicar(filas)
        self.assertEqual(ev[0]["pmid"], 9)
        # y no depende del orden de lectura
        ev2 = R.deduplicar(list(reversed(filas)))
        self.assertEqual(ev2[0]["pmid"], 9)


class PruebasTope(unittest.TestCase):

    def test_topar_cuenta_evidencias_ya_deduplicadas(self):
        """Unidad de `topar()`: recibe evidencias distintas y recorta a N.

        Esta prueba NO dice nada sobre el orden que usa el pipeline --compone
        ella misma `topar(deduplicar(...))`--, y por eso no basta. El orden
        real lo verifica `test_la_dedup_va_antes_del_tope_en_la_corrida`, que
        pasa por `main()`."""
        filas = []
        for i, o in enumerate(("Oracion A.", "Oracion B.", "Oracion C.")):
            filas.append(fila(pmid=2 * i + 1, oracion=o, n_oracion=i))
            filas.append(fila(pmid=2 * i + 2, oracion=o, n_oracion=i))
        topadas = R.topar(R.deduplicar(filas), 3)
        self.assertEqual(len(topadas), 3)
        self.assertEqual(sorted(e["oracion"] for e in topadas),
                         ["Oracion A.", "Oracion B.", "Oracion C."])

    def test_el_tope_es_por_par_y_no_global(self):
        filas = ([fila(blanco="a", oracion="A%d." % i, n_oracion=i)
                  for i in range(4)]
                 + [fila(blanco="b", oracion="B%d." % i, n_oracion=i)
                    for i in range(4)])
        topadas = R.topar(R.deduplicar(filas), 2)
        self.assertEqual(len(topadas), 4)
        self.assertEqual(sum(1 for e in topadas if e["blanco"] == "a"), 2)

    def test_el_recorte_es_determinista(self):
        filas = [fila(pmid=p, oracion="O%d." % p, n_oracion=p)
                 for p in (9, 3, 7, 1)]
        a = R.topar(R.deduplicar(filas), 2)
        b = R.topar(R.deduplicar(list(reversed(filas))), 2)
        self.assertEqual([e["pmid"] for e in a], [1, 3])
        self.assertEqual([e["pmid"] for e in a], [e["pmid"] for e in b])


class PruebasResolverSigno(unittest.TestCase):
    """Paso 5 y seccion 5.2: la regla de mayoria y el conflicto."""

    def test_unanime(self):
        self.assertEqual(R.resolver_signo(3, 0, 0.66), ("activates", False))
        self.assertEqual(R.resolver_signo(0, 3, 0.66), ("represses", False))

    def test_mayoria_suficiente(self):
        # 2 de 3 son 0.667, que alcanza el 0.66 por omision.
        self.assertEqual(R.resolver_signo(2, 1, 0.66), ("activates", False))
        self.assertEqual(R.resolver_signo(5, 1, 0.66), ("activates", False))

    def test_tres_contra_dos_es_conflicto(self):
        """0.6 no llega a 0.66: se degrada a 'regulates' en vez de fabricar un
        signo por mayoria simple."""
        self.assertEqual(R.resolver_signo(3, 2, 0.66), ("regulates", True))

    def test_empate_es_conflicto(self):
        self.assertEqual(R.resolver_signo(2, 2, 0.66), ("regulates", True))

    def test_empate_sigue_siendo_conflicto_con_la_mayoria_floja(self):
        """Aunque alguien baje --mayoria, un empate no tiene ganador."""
        self.assertEqual(R.resolver_signo(2, 2, 0.4), ("regulates", True))

    def test_sin_evidencia_firmada_no_hay_conflicto(self):
        """Solo 'regulates': la relacion esta establecida sin signo resuelto,
        que es una cosa distinta de que la literatura se contradiga."""
        self.assertEqual(R.resolver_signo(0, 0, 0.66), ("regulates", False))


class PruebasAgregacion(unittest.TestCase):

    def _aristas(self, filas, mayoria=0.66, **kw):
        return R.agregar(R.topar(R.deduplicar(filas), 200), mayoria, **kw)[0]

    def test_un_par_en_varios_articulos_es_una_sola_arista(self):
        filas = [fila(pmid=1, oracion="A.", seccion="results"),
                 fila(pmid=2, oracion="B.", seccion="introduction"),
                 fila(pmid=3, oracion="C.", seccion="results")]
        aristas = self._aristas(filas)
        self.assertEqual(len(aristas), 1)
        a = aristas[0]
        self.assertEqual((a["tf"], a["blanco"]), ("MexT", "mexEF-oprN"))
        self.assertEqual(a["n_evidencias"], 3)
        self.assertEqual(a["n_activates"], 3)
        self.assertEqual(a["n_articulos"], 3)
        self.assertEqual(a["pmids"], [1, 2, 3])
        self.assertEqual(a["secciones"], ["introduction", "results"])
        self.assertEqual(a["signo"], "activates")
        self.assertFalse(a["conflicto"])

    def test_los_conteos_cuadran_con_las_evidencias(self):
        filas = [fila(prediccion="activates", oracion="A."),
                 fila(prediccion="represses", oracion="B."),
                 fila(prediccion="regulates", oracion="C.")]
        a = self._aristas(filas)[0]
        self.assertEqual(a["n_evidencias"],
                         a["n_activates"] + a["n_represses"] + a["n_regulates"])
        self.assertEqual((a["n_activates"], a["n_represses"], a["n_regulates"]),
                         (1, 1, 1))

    def test_el_conflicto_se_degrada_a_regulates_y_queda_marcado(self):
        filas = [fila(prediccion="activates", oracion="A%d." % i)
                 for i in range(3)]
        filas += [fila(prediccion="represses", prob=0.9, oracion="R%d." % i)
                  for i in range(2)]
        a = self._aristas(filas)[0]
        self.assertEqual(a["signo"], "regulates")
        self.assertTrue(a["conflicto"])
        # Los tres conteos se conservan: la decision es auditable y un revisor
        # puede aplicar otra regla sin recorrer el pipeline.
        self.assertEqual((a["n_activates"], a["n_represses"]), (3, 2))

    def test_la_confianza_es_la_media_de_la_clase_ganadora(self):
        filas = [fila(prediccion="activates", prob=0.90, oracion="A."),
                 fila(prediccion="activates", prob=0.80, oracion="B."),
                 fila(prediccion="regulates", prob=0.99, oracion="C.")]
        a = self._aristas(filas)[0]
        self.assertEqual(a["signo"], "activates")
        self.assertAlmostEqual(a["confianza"], 0.85, places=4)

    def test_sin_votante_de_la_clase_ganadora_la_confianza_va_vacia(self):
        """Cuando el conflicto degrada la arista a 'regulates' y ninguna
        evidencia predijo 'regulates', no hay evidencia que promediar y la
        columna se deja VACIA.

        Antes se rellenaba con la media de p_regulates sobre toda la evidencia
        contradictoria: otro numero, publicado bajo la misma etiqueta y sin
        nada en el TSV que lo distinguiera. Medido en una corrida de prueba,
        las 74 aristas 'regulates' eran las 74 en conflicto, o sea el 100 % de
        esa columna calculado con la definicion alterna."""
        filas = [fila(prediccion="activates", prob=0.9, oracion="A%d." % i)
                 for i in range(3)]
        filas += [fila(prediccion="represses", prob=0.9, oracion="R%d." % i)
                  for i in range(2)]
        a = self._aristas(filas)[0]
        self.assertEqual(a["signo"], "regulates")
        self.assertTrue(a["conflicto"])
        self.assertEqual(a["n_regulates"], 0)
        self.assertIsNone(a["confianza"])
        # La media alterna --la masa que el modelo le dio a una clase que nadie
        # predijo-- ya no se publica bajo esta etiqueta.
        self.assertNotAlmostEqual(a["confianza"] or -1.0,
                                  round((1.0 - 0.9) / 3.0, 4), places=4)
        # La arista sigue siendo legible: los tres conteos y una oracion.
        self.assertTrue(a["oracion_representativa"])

    def test_el_conflicto_con_votos_de_regulates_si_tiene_confianza(self):
        """El contrapeso: si alguien voto 'regulates', la definicion normal
        aplica y la columna se llena. Sin esto, vaciarla siempre pasaria por
        arreglo."""
        filas = [fila(prediccion="activates", prob=0.9, oracion="A%d." % i)
                 for i in range(3)]
        filas += [fila(prediccion="represses", prob=0.9, oracion="R%d." % i)
                  for i in range(2)]
        filas += [fila(prediccion="regulates", prob=0.80, oracion="G1."),
                  fila(prediccion="regulates", prob=0.90, oracion="G2.")]
        a = self._aristas(filas)[0]
        self.assertEqual(a["signo"], "regulates")
        self.assertTrue(a["conflicto"])
        self.assertEqual(a["n_regulates"], 2)
        self.assertAlmostEqual(a["confianza"], 0.85, places=4)

    def test_la_oracion_representativa_es_la_mas_probable(self):
        filas = [fila(prob=0.71, oracion="La floja."),
                 fila(prob=0.97, oracion="La fuerte."),
                 fila(prediccion="regulates", prob=0.99, oracion="Otra clase.")]
        a = self._aristas(filas)[0]
        self.assertEqual(a["oracion_representativa"], "La fuerte.")

    def test_min_evidencias_descarta_la_arista_entera(self):
        filas = [fila(blanco="a", oracion="A."),
                 fila(blanco="b", oracion="B1."),
                 fila(blanco="b", oracion="B2.")]
        aristas, descartadas = R.agregar(R.topar(R.deduplicar(filas), 200),
                                         0.66, min_evidencias=2)
        self.assertEqual([x["blanco"] for x in aristas], ["b"])
        self.assertEqual(descartadas, 1)

    def test_min_articulos_mira_pmids_no_evidencias(self):
        """Dos oraciones del mismo articulo son dos evidencias y UN articulo."""
        filas = [fila(pmid=7, oracion="A."), fila(pmid=7, oracion="B.")]
        aristas, descartadas = R.agregar(R.topar(R.deduplicar(filas), 200),
                                         0.66, min_articulos=2)
        self.assertEqual(aristas, [])
        self.assertEqual(descartadas, 1)

    def test_las_aristas_salen_ordenadas(self):
        filas = [fila(tf="NalD", blanco="mexAB-oprM", prediccion="represses",
                      oracion="N."),
                 fila(tf="MexT", blanco="mexS", oracion="M2."),
                 fila(tf="MexT", blanco="mexEF-oprN", oracion="M1.")]
        aristas = self._aristas(filas)
        self.assertEqual([(a["tf"], a["blanco"]) for a in aristas],
                         [("MexT", "mexEF-oprN"), ("MexT", "mexS"),
                          ("NalD", "mexAB-oprM")])


class PruebasCuentaDeArticulos(unittest.TestCase):
    """n_articulos es PMIDs distintos, no evidencias. auditar_signo.py lo
    perdia al deduplicar y era la senal de confianza mas barata que habia."""

    def test_la_dedup_no_se_lleva_los_articulos(self):
        o = "MexT activates mexEF-oprN."
        filas = [fila(pmid=p, oracion=o) for p in (100, 200, 300)]
        a = R.agregar(R.topar(R.deduplicar(filas), 200), 0.66)[0][0]
        self.assertEqual(a["n_evidencias"], 1)
        self.assertEqual(a["n_articulos"], 3)
        self.assertEqual(a["pmids"], [100, 200, 300])

    def test_los_pmids_de_las_evidencias_se_unen_sin_repetir(self):
        """Dos oraciones distintas que comparten un articulo: 2 evidencias y 3
        articulos, no 4."""
        filas = [fila(pmid=1, oracion="A."), fila(pmid=2, oracion="A."),
                 fila(pmid=2, oracion="B."), fila(pmid=3, oracion="B.")]
        a = R.agregar(R.topar(R.deduplicar(filas), 200), 0.66)[0][0]
        self.assertEqual(a["n_evidencias"], 2)
        self.assertEqual(a["n_articulos"], 3)
        self.assertEqual(a["pmids"], [1, 2, 3])

    def test_el_articulo_repetido_en_la_misma_arista_cuenta_una_vez(self):
        filas = [fila(pmid=5, oracion="A."), fila(pmid=5, oracion="B.")]
        a = R.agregar(R.topar(R.deduplicar(filas), 200), 0.66)[0][0]
        self.assertEqual((a["n_evidencias"], a["n_articulos"]), (2, 1))


class PruebasInvariantes(unittest.TestCase):

    def _arista(self, **kw):
        a = {"tf": "MexT", "blanco": "mexEF-oprN", "signo": "activates",
             "conflicto": False, "n_evidencias": 1, "n_activates": 1,
             "n_represses": 0, "n_regulates": 0, "n_articulos": 1,
             "confianza": 0.9, "autorregulacion": False,
             "secciones": ["results"], "pmids": [1],
             "oracion_representativa": "A.", "evidencias": []}
        a.update(kw)
        return a

    def test_cero_aristas_no_escribe_nada(self):
        with self.assertRaises(SystemExit):
            R.verificar([], False)

    def test_conteos_que_no_cuadran(self):
        with self.assertRaises(SystemExit):
            R.verificar([self._arista(n_evidencias=5)], False)

    def test_signo_fuera_del_enum(self):
        with self.assertRaises(SystemExit):
            R.verificar([self._arista(signo="activador")], False)

    def test_autorregulacion_colada(self):
        with self.assertRaises(SystemExit):
            R.verificar([self._arista(autorregulacion=True)], False)
        R.verificar([self._arista(autorregulacion=True)], True)


class PruebasMeta(unittest.TestCase):
    """Sin el meta no se sabe en que orden se leyeron los logits, y uno de los
    tres ordenes del arbol del asesor intercambia represion con no_relation."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="red_meta_")
        self.pred = os.path.join(self.dir, "predicciones.jsonl")
        open(self.pred, "w").close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _meta(self, obj, nombre="predicciones_meta.json"):
        with open(os.path.join(self.dir, nombre), "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def test_sin_meta_no_corre(self):
        with self.assertRaises(SystemExit):
            R.cargar_meta(self.pred)

    def test_el_orden_intercambiado_se_rechaza(self):
        self._meta({"id2label": {"0": "activates", "1": "represses",
                                 "2": "regulates", "3": "no_relation"}})
        with self.assertRaises(SystemExit):
            R.cargar_meta(self.pred)

    def test_el_orden_del_checkpoint_se_acepta(self):
        self._meta({"id2label": ORDEN_BUENO, "do_lower_case": True})
        meta, ruta = R.cargar_meta(self.pred)
        self.assertEqual(meta["do_lower_case"], True)
        self.assertTrue(ruta.endswith("predicciones_meta.json"))

    def test_el_meta_toma_el_nombre_del_archivo_de_predicciones(self):
        otro = os.path.join(self.dir, "corrida7.jsonl")
        open(otro, "w").close()
        self._meta({"id2label": ORDEN_BUENO}, "corrida7_meta.json")
        _, ruta = R.cargar_meta(otro)
        self.assertTrue(ruta.endswith("corrida7_meta.json"))


class PruebasEntrada(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="red_entrada_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _escribir(self, nombre, registros):
        ruta = os.path.join(self.dir, nombre)
        with open(ruta, "w", encoding="utf-8", newline="\n") as f:
            for r in registros:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return ruta

    def test_una_etiqueta_desconocida_para_la_corrida(self):
        ruta = self._escribir("p.jsonl", [{
            "id_par": "a", "pmid": 1, "tf": "MexT", "target": "mexS",
            "prediccion": "activador", "p_activates": 1.0, "p_no_relation": 0.0,
            "p_regulates": 0.0, "p_represses": 0.0, "seccion": "results",
            "fuente": "fulltext", "autorregulacion": False,
            "redaccion": "directa"}])
        with self.assertRaises(SystemExit):
            R.cargar_predicciones(ruta)

    def test_un_id_par_repetido_en_los_candidatos(self):
        ruta = self._escribir("pares.jsonl", [
            {"id_par": "a", "oracion_cruda": "A.", "n_oracion": 0},
            {"id_par": "a", "oracion_cruda": "B.", "n_oracion": 1}])
        with self.assertRaises(SystemExit):
            R.cargar_pares(ruta)

    def test_una_prediccion_sin_candidato_para_la_corrida(self):
        """Predicciones y candidatos de corridas distintas: la union por id_par
        no seria fiable y la red saldria con oraciones de otro archivo."""
        with self.assertRaises(SystemExit):
            R.unir_con_pares([{"id_par": "z"}], {"a": ("A.", 0)},
                             "pares.jsonl", lambda *a: None)


def registro_prediccion(id_par, tf, target, prediccion, prob, pmid,
                        seccion="results", auto=False, redaccion="directa"):
    p = probabilidades(prediccion, prob)
    d = {"id_par": id_par, "pmid": pmid, "tf": tf, "target": target,
         "prediccion": prediccion}
    for e in R.ETIQUETAS:
        d["p_" + e] = round(p[e], 6)
    d.update({"seccion": seccion, "fuente": "fulltext",
              "autorregulacion": auto, "redaccion": redaccion})
    return d


class PruebasExtremoAExtremo(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="red_e2e_")
        self.pred = os.path.join(self.dir, "predicciones.jsonl")
        self.pares = os.path.join(self.dir, "pares.jsonl")
        self.red = os.path.join(self.dir, "red.tsv")
        self.evid = os.path.join(self.dir, "red_evidencias.tsv")
        self.informe = os.path.join(self.dir, "red_informe.json")
        with open(os.path.join(self.dir, "predicciones_meta.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"id2label": ORDEN_BUENO, "do_lower_case": True,
                       "modelo": "run_22"}, f)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _escribir(self, predicciones, oraciones):
        with open(self.pred, "w", encoding="utf-8", newline="\n") as f:
            for r in predicciones:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(self.pares, "w", encoding="utf-8", newline="\n") as f:
            for i, (id_par, o) in enumerate(oraciones):
                f.write(json.dumps({"id_par": id_par, "oracion_cruda": o,
                                    "n_oracion": i}, ensure_ascii=False) + "\n")

    def _correr(self, extra=()):
        argv = ["--predicciones", self.pred, "--pares", self.pares,
                "--salida", self.red, "--evidencias", self.evid,
                "--informe", self.informe] + list(extra)
        return R.main(argv, log=lambda *a: None)

    def _caso(self):
        o1 = "MexT is a transcriptional activator of mexEF-oprN in PAO1."
        o2 = "Overexpression of mexEF-oprN requires MexT."
        o3 = "MexT reduced the expression of mexEF-oprN in the mutant."
        o4 = "NalD represses mexAB-oprM at the second promoter."
        preds = [
            # la misma oracion en dos articulos: una evidencia, dos articulos
            registro_prediccion("p1", "MexT", "mexEF-oprN", "activates", 0.92, 100),
            registro_prediccion("p2", "MexT", "mexEF-oprN", "activates", 0.92, 101),
            registro_prediccion("p3", "MexT", "mexEF-oprN", "activates", 0.80, 102,
                                seccion="introduction"),
            registro_prediccion("p4", "MexT", "mexEF-oprN", "represses", 0.75, 103),
            registro_prediccion("p5", "NalD", "mexAB-oprM", "represses", 0.85, 200),
            # las tres que no deben llegar a la red
            registro_prediccion("p6", "MexT", "mexS", "no_relation", 0.99, 104),
            registro_prediccion("p7", "MexT", "mexS", "activates", 0.30, 105),
            registro_prediccion("p8", "NalD", "nalD", "represses", 0.99, 201,
                                auto=True),
        ]
        pares = [("p1", o1), ("p2", o1), ("p3", o2), ("p4", o3), ("p5", o4),
                 ("p6", "MexT and mexS appear here."),
                 ("p7", "MexT and mexS appear there."),
                 ("p8", "NalD represses its own gene nalD.")]
        self._escribir(preds, pares)

    def _leer_tsv(self, ruta):
        with open(ruta, encoding="utf-8") as f:
            filas = [l.rstrip("\n").split("\t") for l in f if l.strip()]
        return filas[0], [dict(zip(filas[0], r)) for r in filas[1:]]

    def test_la_corrida_completa(self):
        self._caso()
        self.assertEqual(self._correr(), 0)

        cabecera, filas = self._leer_tsv(self.red)
        self.assertEqual(cabecera, R.COLUMNAS_RED)
        self.assertEqual([(f["tf"], f["blanco"]) for f in filas],
                         [("MexT", "mexEF-oprN"), ("NalD", "mexAB-oprM")])

        a = filas[0]
        # 4 predicciones, pero dos comparten oracion: 3 evidencias distintas.
        self.assertEqual(a["n_evidencias"], "3")
        self.assertEqual((a["n_activates"], a["n_represses"], a["n_regulates"]),
                         ("2", "1", "0"))
        # 2 de 3 firmadas son 0.667 y alcanzan el 0.66 por omision.
        self.assertEqual(a["signo"], "activates")
        self.assertEqual(a["conflicto"], "false")
        # los cuatro articulos, incluido el que la dedup colapso
        self.assertEqual(a["n_articulos"], "4")
        self.assertEqual(a["pmids"], "100|101|102|103")
        self.assertEqual(a["secciones"], "introduction|results")
        self.assertEqual(a["confianza"], "0.8600")
        self.assertEqual(a["autorregulacion"], "false")
        self.assertTrue(a["oracion_representativa"].startswith("MexT is a"))

        # la evidencia queda rastreable hasta el articulo
        cab_e, evid = self._leer_tsv(self.evid)
        self.assertEqual(cab_e, R.COLUMNAS_EVIDENCIAS)
        self.assertEqual(len(evid), 4)
        self.assertEqual(evid[0]["id_par"], "p1")
        self.assertEqual(evid[0]["probabilidad"], "0.920000")

    def test_la_dedup_va_antes_del_tope_en_la_corrida(self):
        """El orden del paso 3 y el paso 4 tal como los aplica `main()`, no
        una composicion que escriba la prueba.

        Tres oraciones distintas del mismo par, cada una citada por dos
        articulos, y --max-por-par 3. Bien hecho: la dedup deja tres
        evidencias, el tope de 3 las conserva todas y la arista sale con 3
        evidencias y 6 articulos. Al reves --topar y despues deduplicar, que es
        el defecto de `auditar_signo.py:232` que la seccion 5 paso 4 existe
        para impedir-- el tope se lleva las filas de pmid 101, 102 y 103, o sea
        dos copias de la oracion A y una de la B, y despues la dedup las
        colapsa a 2: el par acaba con menos oraciones distintas de las que
        cabian y las que se descartaron ya no vuelven.

        La prueba anterior con este nombre componia ella misma
        `topar(deduplicar(filas))` y verificaba una propiedad de su propia
        llamada: invertir el orden dentro de `main()` la dejaba en verde."""
        preds, pares = [], []
        for i, oracion in enumerate(("Primera oracion del par.",
                                     "Segunda oracion del par.",
                                     "Tercera oracion del par.")):
            for k in range(2):
                pmid = 101 + 2 * i + k
                id_par = "d%d" % pmid
                preds.append(registro_prediccion(
                    id_par, "MexT", "mexEF-oprN", "activates", 0.90, pmid))
                pares.append((id_par, oracion, i))
        with open(self.pred, "w", encoding="utf-8", newline="\n") as f:
            for r in preds:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(self.pares, "w", encoding="utf-8", newline="\n") as f:
            for id_par, oracion, n in pares:
                f.write(json.dumps({"id_par": id_par, "oracion_cruda": oracion,
                                    "n_oracion": n}, ensure_ascii=False) + "\n")

        self.assertEqual(self._correr(["--max-por-par", "3"]), 0)
        _, filas = self._leer_tsv(self.red)
        self.assertEqual(len(filas), 1)
        a = filas[0]
        self.assertEqual(a["n_evidencias"], "3")
        self.assertEqual(a["n_articulos"], "6")
        self.assertEqual(a["pmids"], "101|102|103|104|105|106")
        _, evid = self._leer_tsv(self.evid)
        self.assertEqual(sorted(e["oracion"] for e in evid),
                         ["Primera oracion del par.",
                          "Segunda oracion del par.",
                          "Tercera oracion del par."])
        with open(self.informe, encoding="utf-8") as f:
            informe = json.load(f)
        self.assertEqual(informe["n_evidencias_distintas"], 3)
        self.assertEqual(informe["n_evidencias_tras_tope"], 3)
        self.assertEqual(informe["n_evidencias_colapsadas"], 3)

    def test_la_confianza_vacia_llega_al_tsv(self):
        """La columna `confianza` de una arista degradada sin voto 'regulates'
        sale vacia en el archivo, no con la media alterna."""
        preds, pares = [], []
        # 3 contra 2: la mayoria de 0.66 no se alcanza, asi que el par se
        # degrada a 'regulates' sin que nadie haya votado 'regulates'.
        for i, (clase, oracion) in enumerate(
                [("activates", "Lo activa segun el primer articulo."),
                 ("activates", "Lo activa segun el segundo articulo."),
                 ("activates", "Lo activa segun el tercer articulo."),
                 ("represses", "Lo reprime segun el cuarto articulo."),
                 ("represses", "Lo reprime segun el quinto articulo.")]):
            id_par = "c%d" % i
            preds.append(registro_prediccion(id_par, "MexT", "mexEF-oprN",
                                             clase, 0.90, 300 + i))
            pares.append((id_par, oracion))
        self._escribir(preds, pares)
        self.assertEqual(self._correr(), 0)
        _, filas = self._leer_tsv(self.red)
        a = filas[0]
        self.assertEqual(a["signo"], "regulates")
        self.assertEqual(a["conflicto"], "true")
        self.assertEqual(a["n_regulates"], "0")
        self.assertEqual(a["confianza"], "")
        with open(self.informe, encoding="utf-8") as f:
            informe = json.load(f)
        self.assertEqual(informe["n_aristas_sin_confianza"], 1)

    def test_el_informe_trae_umbrales_y_barrido(self):
        self._caso()
        self._correr()
        with open(self.informe, encoding="utf-8") as f:
            inf = json.load(f)
        self.assertEqual(inf["umbrales"], R.UMBRALES_POR_OMISION)
        self.assertEqual(inf["fuente_umbrales"], "por omision")
        self.assertEqual(len(inf["barrido"]), 9)
        self.assertEqual(inf["barrido"][0]["umbral"], 0.5)
        self.assertEqual(inf["barrido"][-1]["umbral"], 0.9)
        self.assertEqual(inf["descartes"]["no_relation"], 1)
        self.assertEqual(inf["descartes"]["autorregulacion"], 1)
        self.assertEqual(inf["descartes"]["bajo_umbral_activates"], 1)
        self.assertEqual(inf["n_evidencias_colapsadas"], 1)
        self.assertEqual(inf["n_aristas"], 2)
        self.assertEqual(inf["meta_inferencia"]["do_lower_case"], True)

    def test_no_quedan_temporales(self):
        self._caso()
        self._correr()
        sobrantes = [n for n in os.listdir(self.dir) if n.endswith(".tmp")]
        self.assertEqual(sobrantes, [])

    def test_sin_aristas_no_escribe_el_archivo(self):
        """Un archivo vacio con el encabezado bueno parece una red que dio
        cero, y no lo es: es una corrida que no se puede defender."""
        self._caso()
        with self.assertRaises(SystemExit):
            self._correr(["--umbral-activates", "0.999",
                          "--umbral-represses", "0.999",
                          "--umbral-regulates", "0.999"])
        self.assertFalse(os.path.exists(self.red))

    def test_los_flags_de_seccion_recortan(self):
        self._caso()
        self._correr(["--sin-introduccion"])
        _, filas = self._leer_tsv(self.red)
        self.assertEqual(filas[0]["n_evidencias"], "2")
        self.assertEqual(filas[0]["pmids"], "100|101|103")

    def test_la_autorregulacion_entra_solo_con_su_flag(self):
        self._caso()
        self._correr(["--incluir-autorregulacion"])
        _, filas = self._leer_tsv(self.red)
        pares = [(f["tf"], f["blanco"], f["autorregulacion"]) for f in filas]
        self.assertIn(("NalD", "nalD", "true"), pares)

    def test_ningun_campo_lleva_tabulador(self):
        """La oracion viene de un texto con tabuladores y saltos: si se
        escribieran tal cual, la fila tendria mas columnas que el encabezado y
        el TSV dejaria de poder leerse."""
        self._caso()
        with open(self.pares, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"id_par": "p1", "n_oracion": 0,
                                "oracion_cruda": "MexT\tactiva a\n mexEF-oprN."})
                    + "\n")
        with open(self.pred, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(registro_prediccion(
                "p1", "MexT", "mexEF-oprN", "activates", 0.92, 100)) + "\n")
        self._correr()
        cabecera, filas = self._leer_tsv(self.red)
        with open(self.red, encoding="utf-8") as f:
            cuerpo = f.read().splitlines()[1]
        self.assertEqual(len(cuerpo.split("\t")), len(cabecera))
        self.assertEqual(filas[0]["oracion_representativa"],
                         "MexT activa a mexEF-oprN.")

    def test_la_mayoria_floja_se_rechaza(self):
        self._caso()
        with self.assertRaises(SystemExit):
            self._correr(["--mayoria", "0.4"])

    def test_los_umbrales_se_pueden_leer_de_un_archivo(self):
        self._caso()
        ruta = os.path.join(self.dir, "umbrales_sugeridos.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"umbrales": {"activates": 0.85, "represses": 0.5,
                                    "regulates": 0.5},
                       "calibrado_en": "dev sin fuga"}, f)
        self._correr(["--umbrales", ruta, "--umbral-activates", "0.1"])
        with open(self.informe, encoding="utf-8") as f:
            inf = json.load(f)
        # El archivo gana sobre el flag.
        self.assertEqual(inf["umbrales"]["activates"], 0.85)
        self.assertEqual(inf["calibrado_en"], "dev sin fuga")
        _, filas = self._leer_tsv(self.red)
        # Con esos umbrales cae la evidencia que activa con 0.80 y entra la que
        # reprime con 0.75: queda 1 contra 1, o sea empate y conflicto. Lo que
        # se comprueba es que la politica de umbrales cambia la red sin volver
        # a llamar al modelo, que es para lo que existe esta etapa.
        self.assertEqual(filas[0]["signo"], "regulates")
        self.assertEqual(filas[0]["conflicto"], "true")


class PruebasProbabilidades(unittest.TestCase):
    """Las cuatro probabilidades son una distribucion, y la etiqueta es su
    argmax. Unidad; el guardian de verdad es la corrida de PruebasSoftmax.

    La invariante ("suman 1.0 +/- 1e-3") estaba escrita solo en el script que
    produce el archivo, que es el unico que importa torch y por lo tanto el
    que no corre en las maquinas del laboratorio. Medido: 65216 filas con las
    cuatro clases a 0.99 --suman 3.96-- daban 9608 aristas con confianza
    0.9900 y codigo 0, y la etapa 5 publicaba exhaustividad 95.1 % sobre esa
    red.
    """

    def _fila(self, p, prediccion="activates"):
        f = fila(prediccion=prediccion)
        f["p"] = dict(zip(R.ETIQUETAS, p))
        return f

    def test_la_distribucion_normal_pasa(self):
        medicion = R.revisar_probabilidades(
            [self._fila([0.912844, 0.031207, 0.049116, 0.006833])], "p.jsonl")
        self.assertEqual(medicion["filas"], 1)
        self.assertLess(medicion["desviacion_maxima_de_la_suma"], 1e-3)

    def test_las_cuatro_a_099_no_pasan(self):
        """El exploit literal: suman 3.96 y la fila se aceptaba entera."""
        with self.assertRaises(SystemExit) as cm:
            R.revisar_probabilidades([self._fila([0.99, 0.99, 0.99, 0.99])],
                                     "p.jsonl")
        self.assertIn("no suman 1", str(cm.exception))

    def test_la_tolerancia_es_de_mil_diezmilesimas(self):
        """1e-3 lo pide el contrato: con seis decimales por clase el redondeo
        no llega ni a 1e-5, asi que la tolerancia solo cubre eso."""
        R.revisar_probabilidades([self._fila([0.2505, 0.25, 0.25, 0.25])],
                                 "p.jsonl")
        with self.assertRaises(SystemExit):
            R.revisar_probabilidades([self._fila([0.2515, 0.25, 0.25, 0.25])],
                                     "p.jsonl")

    def test_una_probabilidad_fuera_de_cero_uno(self):
        with self.assertRaises(SystemExit) as cm:
            R.revisar_probabilidades([self._fila([1.5, -0.5, 0.0, 0.0])],
                                     "p.jsonl")
        self.assertIn("[0, 1]", str(cm.exception))

    def test_un_nan_no_se_cuela_por_la_suma(self):
        """`json.loads` acepta `NaN`, y con un nan toda comparacion es falsa:
        `abs(nan - 1) > 1e-3` tambien. La comprobacion del rango es la que lo
        atrapa, y por eso va primero."""
        nan = float("nan")
        with self.assertRaises(SystemExit):
            R.revisar_probabilidades([self._fila([nan, 0.0, 0.0, 0.0])],
                                     "p.jsonl")
        with self.assertRaises(SystemExit):
            R.revisar_probabilidades(
                [self._fila([float("inf"), 0.0, 0.0, 0.0])], "p.jsonl")

    def test_la_etiqueta_tiene_que_ser_la_clase_mas_probable(self):
        """Sin esto, la comprobacion de la suma se esquiva con una
        distribucion legitima y una etiqueta falsa: p_represses = 0.9
        declarado 'activates' pasa el umbral de activacion con un numero que
        pertenece a la represion, y la arista sale con el signo cambiado."""
        with self.assertRaises(SystemExit) as cm:
            R.revisar_probabilidades(
                [self._fila([0.05, 0.03, 0.02, 0.90])], "p.jsonl")
        self.assertIn("la clase mas probable es 'represses'",
                      str(cm.exception))

    def test_el_empate_exacto_se_acepta_y_se_cuenta(self):
        """Cuatro clases a 0.25 SI son una distribucion. No hay argmax unico y
        ninguna eleccion es un error; lo que no puede pasar es que el empate
        se cuele sin quedar contado."""
        medicion = R.revisar_probabilidades(
            [self._fila([0.25, 0.25, 0.25, 0.25])], "p.jsonl")
        self.assertEqual(medicion["filas_con_la_clase_ganadora_empatada"], 1)

    def test_el_redondeo_a_seis_decimales_no_cuenta_como_empate_roto(self):
        """La clase declarada pierde por 5e-7, que es lo mas que puede meter
        el redondeo a seis decimales de la seccion 4. No es un error; medio
        micron por debajo del maximo no es una etiqueta mentida."""
        R.revisar_probabilidades(
            [self._fila([0.5, 0.5000005, 0.0, 0.0])], "p.jsonl")
        # Un orden de magnitud mas y si lo es.
        with self.assertRaises(SystemExit):
            R.revisar_probabilidades(
                [self._fila([0.5, 0.500005, 0.0, 0.0])], "p.jsonl")


class PruebasSoftmax(unittest.TestCase):
    """El mismo agujero, pero por `main()`: lo que decide es que el archivo no
    se escriba, no que exista una funcion que sepa detectarlo."""

    setUp = PruebasExtremoAExtremo.setUp
    tearDown = PruebasExtremoAExtremo.tearDown
    _escribir = PruebasExtremoAExtremo._escribir
    _correr = PruebasExtremoAExtremo._correr
    _caso = PruebasExtremoAExtremo._caso

    def _predicciones_rotas(self, **kw):
        r = registro_prediccion("p1", "MexT", "mexEF-oprN", "activates", 0.92,
                                100)
        r.update(kw)
        self._escribir([r], [("p1", "MexT activa a mexEF-oprN en PAO1.")])

    def test_la_corrida_con_las_cuatro_a_099_no_escribe_nada(self):
        self._predicciones_rotas(p_activates=0.99, p_no_relation=0.99,
                                 p_regulates=0.99, p_represses=0.99)
        with self.assertRaises(SystemExit) as cm:
            self._correr()
        self.assertIn("no suman 1", str(cm.exception))
        self.assertFalse(os.path.exists(self.red))
        self.assertFalse(os.path.exists(self.evid))
        self.assertFalse(os.path.exists(self.informe))

    def test_la_corrida_con_la_etiqueta_mentida_no_escribe_nada(self):
        self._predicciones_rotas(p_activates=0.05, p_no_relation=0.03,
                                 p_regulates=0.02, p_represses=0.90)
        with self.assertRaises(SystemExit):
            self._correr()
        self.assertFalse(os.path.exists(self.red))

    def test_la_corrida_buena_publica_la_medicion(self):
        """Una comprobacion que solo se nota cuando falla es indistinguible de
        una que no existe: quien lea la red tiene que poder ver que el
        predicciones.jsonl del que salio se miro, y con que numero."""
        self._caso()
        self.assertEqual(self._correr(), 0)
        with open(self.informe, encoding="utf-8") as f:
            inf = json.load(f)
        self.assertEqual(inf["probabilidades"]["filas"], 8)
        self.assertEqual(inf["probabilidades"]["tolerancia_suma"],
                         R.TOLERANCIA_SUMA)
        self.assertLess(inf["probabilidades"]["desviacion_maxima_de_la_suma"],
                        R.TOLERANCIA_SUMA)


class PruebasDeterminismo(unittest.TestCase):

    def test_la_misma_entrada_da_la_misma_red(self):
        filas = [fila(pmid=p, oracion="O%d." % (p % 3), n_oracion=p % 3,
                      prediccion=("activates" if p % 2 else "represses"),
                      prob=0.9)
                 for p in range(1, 10)]
        def corre(fs):
            aristas, _ = R.agregar(R.topar(R.deduplicar(
                R.filtrar(fs, UMBRALES)), 5), 0.66)
            return [R.fila_red(a) for a in aristas]
        self.assertEqual(corre(filas), corre(list(reversed(filas))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
