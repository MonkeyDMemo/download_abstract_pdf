# -*- coding: utf-8 -*-
"""Pruebas del signo de la red como parámetro: el voto léxico y el voto por
artículo de `grn_red/signo.py`.

Las que no pueden faltar:

- **apagadas, nada cambia**: `es_omision` sigue diciendo que la configuración
  por omisión es la de `red.py` (la prueba byte a byte está en
  `test_consolidar`), y las reglas nunca escriben `red.tsv`;
- **prendidas, nunca sin nombre**: pisarían `red_recomendada.tsv`;
- **una arista que ninguna regla toca sale como la escribió `red.py`**;
- un caso por regla, con lo que dice la arista por oración y por artículo.

Todo es sintético: genes inventados (QzaR, wvaA...), locus inventados
(PA91xx), PMIDs inventados y un vocabulario de disparadores falso; nada del
laboratorio.

    python -m unittest grn_red.test_signo
"""

import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import operones as _operones     # noqa: E402
from grn_bronce import vocabulario               # noqa: E402
from grn_comun import procedencia                # noqa: E402
from grn_red import cli, consolidar, signo       # noqa: E402
from grn_red.consolidar import _red              # noqa: E402

ETIQUETAS = ["activates", "no_relation", "regulates", "represses"]

# (id_par, regulador, blanco, predicción, pmid, oración[, probabilidad]). Una
# arista por letra.
CASOS = [
    # a) Un regulates con un disparador «-».
    ("a1", "QzaR", "wvaA", "regulates", 91000001,
     "QzaR silences wvaA in a synthetic sentence."),
    # b) Un activates de BioBERT y dos regulates con disparador «-».
    ("b1", "QzbR", "wvbA", "activates", 91000010,
     "QzbR activates wvbA in strain one."),
    ("b2", "QzbR", "wvbA", "regulates", 91000011,
     "QzbR represses wvbA under iron limitation."),
    # Con 0.70 su p[represses] es mayor que la de b2, y aun así la
    # representativa es b2: solo votó el léxico, y eso va por orden.
    ("b3", "QzbR", "wvbA", "regulates", 91000012,
     "QzbR silences wvbA in biofilms.", 0.70),
    # c) Un conflicto 1:1 de BioBERT y un regulates con disparador «+».
    ("c1", "QzcR", "wvcA", "activates", 91000020,
     "QzcR activates wvcA in rich medium."),
    ("c2", "QzcR", "wvcA", "represses", 91000021,
     "QzcR represses wvcA in poor medium."),
    ("c3", "QzcR", "wvcA", "regulates", 91000022,
     "QzcR induces wvcA at high density."),
    # d) Tres «+» en el artículo A contra «-» en B y en C.
    ("d1", "QzdR", "wvdA", "activates", 91000030,
     "QzdR activates wvdA, synthetic sentence one."),
    ("d2", "QzdR", "wvdA", "activates", 91000030,
     "QzdR activates wvdA, synthetic sentence two."),
    ("d3", "QzdR", "wvdA", "activates", 91000030,
     "QzdR activates wvdA, synthetic sentence three."),
    ("d4", "QzdR", "wvdA", "represses", 91000031,
     "QzdR represses wvdA, synthetic sentence four."),
    ("d5", "QzdR", "wvdA", "represses", 91000032,
     "QzdR represses wvdA, synthetic sentence five."),
    # e) Dos «+» en A contra un «-» en B.
    ("e1", "QzeR", "wveA", "activates", 91000040,
     "QzeR activates wveA, synthetic sentence one."),
    ("e2", "QzeR", "wveA", "activates", 91000040,
     "QzeR activates wveA, synthetic sentence two."),
    ("e3", "QzeR", "wveA", "represses", 91000041,
     "QzeR represses wveA, synthetic sentence three."),
    # f) Dos «+» en A, y la misma oración «-» en B y en C.
    ("f1", "QzfR", "wvfA", "activates", 91000050,
     "QzfR activates wvfA, synthetic sentence one."),
    ("f2", "QzfR", "wvfA", "activates", 91000050,
     "QzfR activates wvfA, synthetic sentence two."),
    ("f3", "QzfR", "wvfA", "represses", 91000051,
     "QzfR represses wvfA in the same words."),
    ("f4", "QzfR", "wvfA", "represses", 91000052,
     "QzfR represses wvfA in the same words."),
    # g) El blanco es un operón del catálogo de prueba.
    ("g1", "QzgR", "wvgAB", "regulates", 91000060,
     "QzgR silences wvgAB under stress."),
    # h) Un regulates sin disparador con signo: no vota.
    ("h1", "QzhR", "wvhA", "regulates", 91000070,
     "QzhR and wvhA were studied together."),
    # i) Un «+» y un «-» en el mismo artículo: por artículo, nadie decide.
    ("i1", "QziR", "wviA", "activates", 91000080,
     "QziR activates wviA, synthetic sentence one."),
    ("i2", "QziR", "wviA", "represses", 91000080,
     "QziR represses wviA, synthetic sentence two."),
    # No llega a la red, aunque su oración tenga disparador.
    ("z1", "QzzR", "wvzA", "no_relation", 91000090,
     "QzzR silences wvzA, synthetic sentence."),
]

PROBABILIDAD = {"activates": 0.90, "represses": 0.90, "regulates": 0.80,
                "no_relation": 0.99}

# El «?» de studied no vota: la regla es el disparador CON signo.
DISPARADORES = (
    "# Vocabulario falso de las pruebas de grn_red/signo.py.\n"
    "palabra,signo_sugerido\n"
    "activates,+\n"
    "induces,+\n"
    "represses,-\n"
    "silences,-\n"
    "regulates,?\n"
    "studied,?\n")

OPERONES = [["wvgAB", "wvgA|wvgB", "PA9101|PA9102", "prueba"]]

COLUMNAS_SIGNO = ["signo_red_py", "n_lexico_activates", "n_lexico_represses",
                  "n_articulos_activates", "n_articulos_represses",
                  "n_articulos_sin_signo"]


def _prediccion(id_par, tf, target, prediccion, pmid, _oracion=None,
                prob=None):
    prob = prob or PROBABILIDAD[prediccion]
    resto = (1.0 - prob) / 3.0
    d = {"id_par": id_par, "pmid": pmid, "tf": tf, "target": target,
         "prediccion": prediccion}
    for e in ETIQUETAS:
        d["p_" + e] = round(prob if e == prediccion else resto, 6)
    d.update({"seccion": "results", "fuente": "fulltext",
              "autorregulacion": False, "redaccion": "directa"})
    return d


def _escribir(ruta, texto):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)


def _carpeta(raiz, nombre="corrida4_signo", casos=CASOS):
    """Una carpeta como la que deja el flujo después del paso «biobert», con
    las menciones en `pares.jsonl` como las escribe el paso «pares»."""
    carpeta = os.path.join(raiz, nombre)
    os.makedirs(carpeta)
    _escribir(os.path.join(carpeta, "predicciones.jsonl"), "".join(
        json.dumps(_prediccion(*c)) + "\n" for c in casos))
    _escribir(os.path.join(carpeta, "pares.jsonl"), "".join(
        json.dumps({"id_par": c[0], "oracion_cruda": c[5], "n_oracion": i,
                    "mencion_tf": c[1], "mencion_target": c[2]}) + "\n"
        for i, c in enumerate(casos)))
    _escribir(os.path.join(carpeta, "predicciones_meta.json"), json.dumps({
        "id2label": {"0": "activates", "1": "no_relation", "2": "regulates",
                     "3": "represses"}, "modelo": "modelo_sintetico"}))
    return carpeta


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    columnas = lineas[0].split("\t")
    return columnas, [dict(zip(columnas, l.split("\t"))) for l in lineas[1:]]


def _bytes(ruta):
    with io.open(ruta, "rb") as f:
        return f.read()


def _por_arista(filas):
    return dict(((f["tf"], f["blanco"], f.get("expandida_de", "")), f)
                for f in filas)


class _Vocab(object):
    """Un vocabulario falso como el de `test_capa_evaluar`, pero que busca
    las palabras en cada oración."""

    def __init__(self, signos):
        self.signos = signos
        self.disparadores = signos

    def disparadores_en(self, oracion):
        salida = []
        for palabra, s in self.signos.items():
            ini = oracion.find(palabra)
            while ini >= 0:
                salida.append((ini, ini + len(palabra), palabra, s))
                ini = oracion.find(palabra, ini + 1)
        return sorted(salida)


class BaseSigno(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = tmp.name
        self.carpeta = _carpeta(self.raiz)
        self.catalogo = os.path.join(self.raiz, "operones_prueba.tsv")
        _escribir(self.catalogo, "".join(
            "\t".join(f) + "\n" for f in [_operones.COLUMNAS] + OPERONES))
        # El vocabulario del bronce lee sus CSV de esta carpeta al cargarse:
        # aquí, la del vocabulario falso.
        self.recursos = os.path.join(self.raiz, "recursos")
        os.makedirs(self.recursos)
        self.disparadores = os.path.join(self.recursos, "disparadores.csv")
        _escribir(self.disparadores, DISPARADORES)
        parche = mock.patch.object(vocabulario, "RECURSOS", self.recursos)
        parche.start()
        self.addCleanup(parche.stop)

    def consolidar(self, cfg=None, nombre="signo"):
        return consolidar.consolidar(self.carpeta, cfg, nombre=nombre,
                                     catalogo=self.catalogo)

    def red(self, nombre="signo"):
        archivo = ("red.tsv" if nombre is None
                   else consolidar.nombres_de_salida(nombre)[0])
        columnas, filas = _leer_tsv(os.path.join(self.carpeta, archivo))
        return columnas, _por_arista(filas)

    def arista(self, tf, blanco, nombre="signo", expandida_de=""):
        return self.red(nombre)[1][(tf, blanco, expandida_de)]

    def informe(self, nombre="signo"):
        archivo = consolidar.nombres_de_salida(nombre)[2]
        with io.open(os.path.join(self.carpeta, archivo),
                     encoding="utf-8") as f:
            return json.load(f)


class PruebasVotoLexico(BaseSigno):

    def test_un_regulates_con_disparador_negativo_pasa_a_represses(self):
        self.consolidar({"signo_lexico": "evidencias"})
        a = self.arista("QzaR", "wvaA")
        # Sin confianza: BioBERT no predijo represses en ninguna evidencia.
        self.assertEqual((a["signo"], a["conflicto"], a["confianza"],
                          a["signo_red_py"]),
                         ("represses", "false", "", "regulates"))
        self.assertEqual((a["n_lexico_activates"], a["n_lexico_represses"]),
                         ("0", "1"))
        # Los conteos de red.py son de BioBERT y no cambian.
        self.assertEqual((a["n_activates"], a["n_represses"],
                          a["n_regulates"], a["n_evidencias"]),
                         ("0", "0", "1", "1"))

    def test_por_evidencias_vota_aunque_biobert_ya_diera_signo(self):
        """1 activates + 2 regulates con léxico «-»: 2/3 alcanza el 0.66. Con
        `aristas` la arista ya tenía signo de BioBERT y no se toca."""
        self.consolidar({"signo_lexico": "evidencias"}, "por_evidencia")
        self.consolidar({"signo_lexico": "aristas"}, "por_arista")
        b = self.arista("QzbR", "wvbA", "por_evidencia")
        self.assertEqual((b["signo"], b["conflicto"], b["confianza"],
                          b["signo_red_py"], b["n_lexico_represses"]),
                         ("represses", "false", "", "activates", "2"))
        # Solo votó el léxico por represses: la primera por orden_evidencia.
        self.assertEqual(b["oracion_representativa"],
                         "QzbR represses wvbA under iron limitation.")
        b = self.arista("QzbR", "wvbA", "por_arista")
        self.assertEqual((b["signo"], b["confianza"], b["signo_red_py"]),
                         ("activates", "0.9000", "activates"))
        self.assertEqual((b["n_lexico_activates"], b["n_lexico_represses"]),
                         ("", ""))
        # Donde BioBERT no dio signo, `aristas` sí vota.
        a = self.arista("QzaR", "wvaA", "por_arista")
        self.assertEqual((a["signo"], a["n_lexico_represses"]),
                         ("represses", "1"))

    def test_un_conflicto_y_un_regulates_positivo_dan_activates(self):
        self.consolidar({"signo_lexico": "evidencias"}, "por_evidencia")
        self.consolidar({"signo_lexico": "aristas"}, "por_arista")
        c = self.arista("QzcR", "wvcA", "por_evidencia")
        self.assertEqual((c["signo"], c["conflicto"], c["signo_red_py"],
                          c["n_lexico_activates"]),
                         ("activates", "false", "regulates", "1"))
        # La confianza es la del activates de BioBERT, y su oración gana a la
        # del voto léxico, cuya p[activates] no es la de su voto.
        self.assertEqual(c["confianza"], "0.9000")
        self.assertEqual(c["oracion_representativa"],
                         "QzcR activates wvcA in rich medium.")
        # El conflicto ya tenía votos con signo de BioBERT: `aristas` no lo
        # toca.
        c = self.arista("QzcR", "wvcA", "por_arista")
        self.assertEqual((c["signo"], c["conflicto"], c["confianza"]),
                         ("regulates", "true", "0.8000"))

    def test_sin_disparador_con_signo_no_vota(self):
        self.consolidar({"signo_lexico": "evidencias"})
        h = self.arista("QzhR", "wvhA")
        self.assertEqual((h["signo"], h["n_lexico_activates"],
                          h["n_lexico_represses"]), ("regulates", "0", "0"))
        self.assertEqual(
            self.informe()["conteos"]["signo"]["votos_lexicos"],
            {"activates": 1, "represses": 4, "sin_signo": 1})

    def test_la_mayoria_es_la_de_red_py(self):
        """Con 0.7, el 2/3 del caso b ya no alcanza: conflicto."""
        self.consolidar({"signo_lexico": "evidencias", "mayoria": 0.7})
        b = self.arista("QzbR", "wvbA")
        self.assertEqual((b["signo"], b["conflicto"]), ("regulates", "true"))
        self.assertEqual(self.informe()["red_py"]["mayoria"], 0.7)

    def test_los_umbrales_de_un_archivo_llegan_al_recalculo(self):
        """Los regulates de 0.80 caen con un umbral de 0.85: las aristas que
        solo tenían eso desaparecen de las dos redes, y el recálculo es el
        mismo que el de red.py."""
        ruta = os.path.join(self.raiz, "umbrales_sugeridos.json")
        _escribir(ruta, json.dumps({"umbrales": {
            "activates": 0.65, "represses": 0.70, "regulates": 0.85}}))
        self.consolidar({"signo_lexico": "evidencias", "umbrales": ruta})
        _, aristas = self.red()
        self.assertNotIn(("QzaR", "wvaA", ""), aristas)
        self.assertEqual(aristas[("QzbR", "wvbA", "")]["signo"], "activates")

    def test_con_un_vocabulario_de_objeto(self):
        """`votar` recibe cualquier objeto con `disparadores_en`, como el
        control léxico de la evaluación."""
        self.consolidar(nombre=None)
        filas = _leer_tsv(os.path.join(self.carpeta, "red.tsv"))[1]
        with io.open(os.path.join(self.carpeta, "red_informe.json"),
                     encoding="utf-8") as f:
            informe_red = json.load(f)
        nuevas, columnas, resumen = signo.votar(
            self.carpeta, filas, informe_red, "evidencias", False,
            vocab=_Vocab({"silences": "+"}))
        self.assertEqual(columnas, ["signo_red_py", "n_lexico_activates",
                                    "n_lexico_represses"])
        a = _por_arista(nuevas)[("QzaR", "wvaA", "")]
        self.assertEqual((a["signo"], a["n_lexico_activates"]),
                         ("activates", "1"))
        self.assertEqual(resumen["votos_lexicos"],
                         {"activates": 3, "represses": 0, "sin_signo": 3})


class PruebasVotoPorArticulo(BaseSigno):

    def setUp(self):
        super(PruebasVotoPorArticulo, self).setUp()
        self.consolidar(nombre=None)
        self.consolidar({"voto_articulo": True})

    def test_tres_a_favor_en_un_articulo_no_le_ganan_a_dos_articulos(self):
        d = self.arista("QzdR", "wvdA")
        # Por oración, 3 contra 2 es 0.6: conflicto.
        self.assertEqual(d["signo_red_py"], "regulates")
        self.assertEqual(self.arista("QzdR", "wvdA", None)["conflicto"],
                         "true")
        # Por artículo, 1 contra 2.
        self.assertEqual((d["signo"], d["conflicto"]), ("represses", "false"))
        self.assertEqual((d["n_articulos_activates"],
                          d["n_articulos_represses"],
                          d["n_articulos_sin_signo"]), ("1", "2", "0"))
        self.assertEqual(d["confianza"], "0.9000")
        self.assertEqual(d["oracion_representativa"],
                         "QzdR represses wvdA, synthetic sentence four.")

    def test_dos_oraciones_de_un_articulo_contra_una_de_otro_empatan(self):
        e = self.arista("QzeR", "wveA")
        self.assertEqual(e["signo_red_py"], "activates")
        self.assertEqual((e["signo"], e["conflicto"], e["confianza"]),
                         ("regulates", "true", ""))
        self.assertEqual((e["n_articulos_activates"],
                          e["n_articulos_represses"]), ("1", "1"))

    def test_la_misma_oracion_en_dos_articulos(self):
        """Una vez por oración (red.py la deduplica sin el PMID) y dos por
        artículo."""
        f = self.arista("QzfR", "wvfA")
        self.assertEqual((f["n_evidencias"], f["n_activates"],
                          f["n_represses"], f["n_articulos"]),
                         ("3", "2", "1", "3"))
        self.assertEqual(f["signo_red_py"], "activates")
        self.assertEqual((f["signo"], f["n_articulos_activates"],
                          f["n_articulos_represses"]),
                         ("represses", "1", "2"))

    def test_si_todos_los_articulos_se_abstienen_sigue_en_conflicto(self):
        """resolver_signo(0, 0) diría «sin conflicto»; la arista tiene un
        voto de cada signo en su único artículo y nadie la resolvió."""
        i = self.arista("QziR", "wviA")
        self.assertEqual((i["signo"], i["conflicto"], i["signo_red_py"]),
                         ("regulates", "true", "regulates"))
        self.assertEqual((i["n_articulos_activates"],
                          i["n_articulos_represses"],
                          i["n_articulos_sin_signo"]), ("0", "0", "1"))

    def test_solo_en_las_mixtas(self):
        a = self.arista("QzaR", "wvaA")
        self.assertEqual((a["signo"], a["n_articulos_activates"],
                          a["n_articulos_sin_signo"]), ("regulates", "", ""))
        # El conflicto 1:1 de c sí es mixto: el artículo del regulates se
        # abstiene y los otros dos empatan.
        c = self.arista("QzcR", "wvcA")
        self.assertEqual((c["signo"], c["conflicto"],
                          c["n_articulos_activates"],
                          c["n_articulos_represses"],
                          c["n_articulos_sin_signo"]),
                         ("regulates", "true", "1", "1", "1"))

    def test_el_informe(self):
        s = self.informe()["conteos"]["signo"]
        self.assertIsNone(s["votos_lexicos"])
        self.assertEqual((s["n_aristas_mixtas"], s["n_aristas_tocadas"],
                          s["n_aristas_con_otro_signo"],
                          s["n_conflictos_creados"],
                          s["n_conflictos_resueltos"],
                          s["n_aristas_sin_confianza"]), (5, 5, 3, 1, 1, 2))
        t = s["transiciones"]
        self.assertEqual((t["regulates"]["represses"],
                          t["activates"]["regulates"],
                          t["activates"]["represses"]), (1, 1, 1))
        self.assertNotIn("disparadores", self.informe()["recursos"])

    def test_despues_del_voto_lexico(self):
        """Con las dos reglas, la b es mixta después del léxico: su artículo
        con el activates contra los dos de los regulates «-»."""
        self.consolidar({"signo_lexico": "evidencias", "voto_articulo": True},
                        "las_dos")
        b = self.arista("QzbR", "wvbA", "las_dos")
        self.assertEqual((b["signo"], b["n_articulos_activates"],
                          b["n_articulos_represses"], b["confianza"]),
                         ("represses", "1", "2", ""))
        c = self.arista("QzcR", "wvcA", "las_dos")
        self.assertEqual((c["signo"], c["n_articulos_activates"],
                          c["n_articulos_represses"],
                          c["n_articulos_sin_signo"]),
                         ("activates", "2", "1", "0"))


class PruebasLoQueNoSeToca(BaseSigno):

    def test_las_aristas_que_ninguna_regla_toca_son_las_de_red_py(self):
        self.consolidar(nombre=None)
        _, base = self.red(None)
        self.consolidar({"signo_lexico": "evidencias"})
        _, mias = self.red()
        tocadas = set([("QzaR", "wvaA", ""), ("QzbR", "wvbA", ""),
                       ("QzcR", "wvcA", ""), ("QzgR", "wvgAB", "")])
        self.assertEqual(set(mias), set(base))
        for clave, fila in mias.items():
            if clave in tocadas:
                continue
            for c in _red.COLUMNAS_RED:
                self.assertEqual(fila[c], base[clave][c], (clave, c))
            self.assertEqual(fila["signo_red_py"], fila["signo"])
        self.assertEqual(
            self.informe()["conteos"]["signo"]["n_aristas_tocadas"],
            len(tocadas))

    def test_nunca_toca_red_tsv(self):
        self.consolidar(nombre=None)
        antes = dict((n, _bytes(os.path.join(self.carpeta, n)))
                     for n in ("red.tsv", "red_evidencias.tsv",
                               "red_informe.json"))
        self.consolidar({"signo_lexico": "evidencias", "voto_articulo": True})
        for n, contenido in antes.items():
            self.assertEqual(_bytes(os.path.join(self.carpeta, n)), contenido,
                             n)

    def test_las_evidencias_son_las_de_red_py(self):
        self.consolidar(nombre=None)
        self.consolidar({"signo_lexico": "evidencias"})
        self.assertEqual(
            _bytes(os.path.join(self.carpeta, "red_signo_evidencias.tsv")),
            _bytes(os.path.join(self.carpeta, "red_evidencias.tsv")))


class PruebasColumnasEInforme(BaseSigno):

    def test_las_expandidas_heredan_las_columnas_del_signo(self):
        self.consolidar({"signo_lexico": "evidencias",
                         "operones": "expandir"})
        _, aristas = self.red()
        operon = aristas[("QzgR", "wvgAB", "")]
        self.assertEqual((operon["signo"], operon["signo_red_py"]),
                         ("represses", "regulates"))
        for gen in ("wvgA", "wvgB"):
            fila = aristas[("QzgR", gen, "wvgAB")]
            for c in ("signo", "conflicto", "confianza", "signo_red_py",
                      "n_lexico_activates", "n_lexico_represses"):
                self.assertEqual(fila[c], operon[c], (gen, c))

    def test_el_orden_de_las_columnas(self):
        self.consolidar({"signo_lexico": "aristas", "voto_articulo": True,
                         "nivel_soporte": True, "operones": "expandir"},
                        "todas")
        columnas, _ = self.red("todas")
        self.assertEqual(columnas, _red.COLUMNAS_RED + COLUMNAS_SIGNO
                         + ["nivel_soporte", "expandida_de"])
        self.assertEqual(self.informe("todas")["columnas"], columnas)
        self.consolidar({"voto_articulo": True, "nivel_soporte": True},
                        "articulo")
        self.assertEqual(self.red("articulo")[0], _red.COLUMNAS_RED + [
            "signo_red_py", "n_articulos_activates", "n_articulos_represses",
            "n_articulos_sin_signo", "nivel_soporte"])
        self.consolidar({"signo_lexico": "evidencias"}, "lexico")
        self.assertEqual(self.red("lexico")[0], _red.COLUMNAS_RED + [
            "signo_red_py", "n_lexico_activates", "n_lexico_represses"])

    def test_el_informe_del_voto_lexico(self):
        self.consolidar({"signo_lexico": "evidencias"})
        inf = self.informe()
        self.assertEqual((inf["parametros"]["signo_lexico"],
                          inf["parametros"]["voto_articulo"]),
                         ("evidencias", False))
        s = inf["conteos"]["signo"]
        self.assertEqual((s["n_aristas_tocadas"], s["n_aristas_mixtas"],
                          s["n_aristas_con_otro_signo"],
                          s["n_conflictos_creados"],
                          s["n_conflictos_resueltos"],
                          s["n_aristas_sin_confianza"]), (4, 6, 4, 0, 1, 5))
        t = s["transiciones"]
        self.assertEqual((t["regulates"]["represses"],
                          t["activates"]["represses"],
                          t["regulates"]["activates"],
                          t["regulates"]["regulates"]), (2, 1, 1, 3))
        self.assertEqual(sum(sum(f.values()) for f in t.values()),
                         inf["conteos"]["n_aristas"])
        self.assertEqual(inf["recursos"]["disparadores"], {
            "archivo": "disparadores.csv",
            "huella": procedencia.huella_texto(self.disparadores)})
        # red_py conserva el reparto de red.py; conteos, el de esta red.
        self.assertEqual(inf["red_py"]["reparto_signos"],
                         {"activates": 3, "represses": 0, "regulates": 6})
        self.assertEqual(inf["conteos"]["reparto_signos"],
                         {"activates": 3, "represses": 3, "regulates": 3})
        self.assertEqual(inf["red_py"]["n_aristas_sin_confianza"], 2)

    def test_apagadas_el_informe_lo_dice(self):
        self.consolidar(consolidar.configuracion("recomendado"),
                        "recomendada")
        inf = self.informe("recomendada")
        self.assertIsNone(inf["conteos"]["signo"])
        self.assertNotIn("disparadores", inf["recursos"])
        self.assertEqual((inf["parametros"]["signo_lexico"],
                          inf["parametros"]["voto_articulo"]), (None, False))
        self.assertNotIn("signo_red_py", self.red("recomendada")[0])


class PruebasGuardas(BaseSigno):

    def test_sin_nombre_es_error_y_red_recomendada_no_se_toca(self):
        self.consolidar(consolidar.configuracion("recomendado"), None)
        nombres = consolidar.nombres_de_salida("recomendada")
        antes = [_bytes(os.path.join(self.carpeta, n)) for n in nombres]
        for cambios in ({"signo_lexico": "evidencias"},
                        {"voto_articulo": True},
                        dict(consolidar.configuracion("recomendado"),
                             signo_lexico="aristas")):
            with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
                self.consolidar(cambios, None)
            self.assertIn("nombre", str(ctx.exception))
        self.assertEqual([_bytes(os.path.join(self.carpeta, n))
                          for n in nombres], antes)
        self.assertFalse([n for n in os.listdir(self.carpeta)
                          if n.endswith(".tmp") or n.startswith(".")])

    def test_sin_disparadores_el_voto_lexico_es_error(self):
        os.remove(self.disparadores)
        with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
            self.consolidar({"signo_lexico": "evidencias"})
        self.assertIn("no existe", str(ctx.exception))
        # Un CSV con solo el encabezado también es un vocabulario vacío.
        _escribir(self.disparadores, "palabra,signo_sugerido\n")
        with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
            self.consolidar({"signo_lexico": "aristas"})
        self.assertIn("no trae ninguno", str(ctx.exception))
        self.assertFalse([n for n in os.listdir(self.carpeta)
                          if n.startswith("red")])
        # El voto por artículo no lo necesita.
        self.consolidar({"voto_articulo": True})

    def test_exigir_igual(self):
        self.consolidar(nombre=None)
        filas = _leer_tsv(os.path.join(self.carpeta, "red.tsv"))[1]
        with io.open(os.path.join(self.carpeta, "red_informe.json"),
                     encoding="utf-8") as f:
            parametros = signo.parametros_de(json.load(f))
        aristas = signo.recalcular(
            os.path.join(self.carpeta, "predicciones.jsonl"),
            os.path.join(self.carpeta, "pares.jsonl"), parametros)
        signo.exigir_igual(aristas, filas)
        # La tercera es QzcR -> wvcA, el conflicto 1:1.
        self.assertEqual((filas[2]["tf"], filas[2]["conflicto"]),
                         ("QzcR", "true"))
        for columna, valor in (("n_represses", "7"), ("signo", "activates"),
                               ("conflicto", "false"), ("blanco", "otro")):
            alterada = [dict(f) for f in filas]
            alterada[2][columna] = valor
            with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
                signo.exigir_igual(aristas, alterada)
            self.assertIn("arista 3", str(ctx.exception))
        with self.assertRaises(consolidar.ErrorConsolidar):
            signo.exigir_igual(aristas, filas[:-1])
        with self.assertRaises(consolidar.ErrorConsolidar):
            signo.exigir_igual(aristas[:-1], filas)

    def test_una_arista_sin_tocar_que_no_sale_igual_es_error(self):
        """Si la réplica de agregar() se separa de la de red.py, ni las
        tocadas son de fiar."""
        self.consolidar(nombre=None)
        filas = _leer_tsv(os.path.join(self.carpeta, "red.tsv"))[1]
        with io.open(os.path.join(self.carpeta, "red_informe.json"),
                     encoding="utf-8") as f:
            informe_red = json.load(f)
        filas = [dict(f) for f in filas]
        h = [f for f in filas if f["tf"] == "QzhR"][0]
        h["confianza"] = "0.7000"
        with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
            signo.votar(self.carpeta, filas, informe_red, "evidencias")
        self.assertIn("QzhR->wvhA", str(ctx.exception))

    def test_un_par_sin_menciones_es_error(self):
        ruta = os.path.join(self.raiz, "pares_sin_menciones.jsonl")
        _escribir(ruta, json.dumps({"id_par": "a1", "oracion_cruda": "x",
                                    "n_oracion": 0}) + "\n")
        with self.assertRaises(consolidar.ErrorConsolidar) as ctx:
            signo.menciones_de(ruta, ["a1"])
        self.assertIn("mencion_tf", str(ctx.exception))
        with self.assertRaises(consolidar.ErrorConsolidar):
            signo.menciones_de(os.path.join(self.carpeta, "pares.jsonl"),
                               ["a1", "no_esta"])
        self.assertEqual(
            signo.menciones_de(os.path.join(self.carpeta, "pares.jsonl"),
                               ["a1"]),
            {"a1": ("QzaR silences wvaA in a synthetic sentence.", "QzaR",
                    "wvaA")})

    def test_un_systemexit_de_red_py_es_error_consolidar(self):
        with self.assertRaises(consolidar.ErrorConsolidar):
            signo.recalcular(os.path.join(self.raiz, "no_esta.jsonl"),
                             os.path.join(self.carpeta, "pares.jsonl"),
                             signo.parametros_de({
                                 "umbrales": _red.UMBRALES_POR_OMISION,
                                 "mayoria": 0.66, "max_por_par": 200,
                                 "min_evidencias": 1, "min_articulos": 1,
                                 "sin_pies": "false",
                                 "sin_introduccion": "false",
                                 "incluir_autorregulacion": "false"}))
        with self.assertRaises(consolidar.ErrorConsolidar):
            signo.parametros_de({"mayoria": 0.66})


class PruebasConfiguracion(unittest.TestCase):

    def test_apagadas_por_omision_y_fuera_de_los_perfiles(self):
        cfg = consolidar.configuracion()
        self.assertTrue(consolidar.es_omision(cfg))
        self.assertEqual((cfg["signo_lexico"], cfg["voto_articulo"]),
                         (None, False))
        recomendado = consolidar.configuracion("recomendado")
        self.assertEqual((recomendado["signo_lexico"],
                          recomendado["voto_articulo"]), (None, False))
        # Los argumentos de red.py no cambian por ellas.
        self.assertEqual(consolidar._argv_red("C", cfg, "S", "E", "I"),
                         consolidar._argv_red("C", consolidar.configuracion(
                             signo_lexico="evidencias", voto_articulo=True),
                             "S", "E", "I"))

    def test_prendidas_ya_no_son_la_red_por_omision(self):
        for cambios in ({"signo_lexico": "evidencias"},
                        {"signo_lexico": "aristas"}, {"voto_articulo": True}):
            self.assertFalse(consolidar.es_omision(
                consolidar.configuracion(**cambios)), cambios)
        # None no cambia nada, como en el resto de los parámetros.
        self.assertTrue(consolidar.es_omision(consolidar.configuracion(
            signo_lexico=None, voto_articulo=None)))

    def test_un_valor_o_un_parametro_que_no_vale_es_error(self):
        for cambios in ({"signo_lexico": "oraciones"}, {"signo_lexico": ""},
                        {"signo_lexico": "Evidencias"}, {"signo": "x"},
                        {"voto_por_articulo": True}):
            with self.assertRaises(consolidar.ErrorConsolidar, msg=cambios):
                consolidar.configuracion(**cambios)


class PruebasCLI(BaseSigno):

    def correr(self, argv):
        pantalla = io.StringIO()
        with contextlib.redirect_stdout(pantalla), \
                contextlib.redirect_stderr(pantalla):
            codigo = cli.main(argv)
        return codigo, pantalla.getvalue()

    def test_las_dos_banderas(self):
        codigo, texto = self.correr([
            "consolidar", "--carpeta", self.carpeta, "--signo-lexico",
            "evidencias", "--voto-articulo", "--nombre", "signo"])
        self.assertEqual(codigo, 0, texto)
        self.assertIn("red.tsv no se tocó", texto)
        self.assertIn("votos léxicos: 1 +, 4 -, 1 sin signo", texto)
        columnas, _ = self.red()
        self.assertEqual(columnas, _red.COLUMNAS_RED + COLUMNAS_SIGNO)
        parametros = self.informe()["parametros"]
        self.assertEqual((parametros["signo_lexico"],
                          parametros["voto_articulo"]), ("evidencias", True))
        self.assertNotIn("red.tsv", os.listdir(self.carpeta))

    def test_sin_nombre_sale_con_1(self):
        codigo, texto = self.correr(["consolidar", "--carpeta", self.carpeta,
                                     "--voto-articulo"])
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR:", texto)
        self.assertIn("--nombre", texto)
        self.assertNotIn("Traceback", texto)

    def test_un_alcance_que_no_existe_lo_rechaza_argparse(self):
        with self.assertRaises(SystemExit):
            self.correr(["consolidar", "--carpeta", self.carpeta,
                         "--signo-lexico", "oraciones", "--nombre", "x"])


class PruebasCompatibilidad(unittest.TestCase):

    def test_python_3_8_y_sin_print_fuera_del_cli(self):
        rutas = [os.path.join(_RAIZ, "grn_red", n) for n in sorted(
            os.listdir(os.path.join(_RAIZ, "grn_red")))
            if n.endswith(".py") and not n.startswith("test_")]
        rutas.append(os.path.join(_RAIZ, "grn_comun", "signo_lexico.py"))
        self.assertIn(os.path.join(_RAIZ, "grn_red", "signo.py"), rutas)
        for ruta in rutas:
            with io.open(ruta, encoding="utf-8") as f:
                arbol = ast.parse(f.read(), filename=ruta,
                                  feature_version=(3, 8))
            if os.path.basename(ruta) == "cli.py":
                continue
            llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name)
                        and n.func.id == "print"]
            self.assertEqual(llamadas, [], ruta)

    def test_el_csv_de_los_disparadores_es_el_del_vocabulario(self):
        self.assertIn(signo.ARCHIVO_DISPARADORES,
                      [n for n, _ in vocabulario.VOCABULARIOS])


if __name__ == "__main__":
    unittest.main()
