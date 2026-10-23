"""Pruebas del contraste con la base curada, sobre datos SINTÉTICOS.

La base se arma con `construir_xlsx`; el bronce y la red son archivos
inventados con las columnas reales (`grn_bronce.exportar` y `etapa2/red.py`,
que se leen de su código para enterarse si cambian). Los locus son de un
rango que PAO1 no tiene (PA9001 y siguientes) y los PMIDs están por encima de
los que existen: nada de aquí viene de la base del laboratorio, ni como dato
ni como forma.

El escenario tiene una fila por caso, y las cifras esperadas se sacaron a
mano de la tabla de abajo (las de las pruebas más nuevas, en su docstring):

    fila  par              cita            origen     qué prueba
     2    9001 -> 9002     XML             Histórica  cubierta por a y b; red dirigida, acuerdo
     3    9003 -> 9004     ABS             Histórica  solo regla a (la oración es de OTRO); red al revés
     4    9005 -> 9006     XML             Ambos      solo con expansión; red con el signo contrario
     5    9007 -> 9007     XML             Histórica  autorregulación
     6    9008 -> 9009     XML homology    Histórica  homología: fuera
     7    9010 -> 9011     B               Histórica  el archivo de exclusiones: fuera
     8    9012 -> 9013     B, ABS          Histórica  se queda (no todos sus PMIDs); red mixta
     9    9014 -> 9015     FUERA           Histórica  fuera del corpus, cubierta por a
    10    9016 -> 9017     TEST            BioBERT    estrato aparte
    11    9018 -> 9019     TEST            Histórica  `?`: sin juicio de signo
    12    9020 -> 9021     TEST, XML       Histórica  con --solo-pmids, «mezcla»
    13    9024 -> 9025     TEST            Histórica  su arista solo tiene evidencia de XML
    14    9026 -> 9027     un DOI          Histórica  sin PMID
    15    9040 -> 9042     XML             Histórica  la red llega por un operón

`red_prueba.tsv` es una red con otras reglas, como las de
`grn_red.consolidar`: las aristas de `red.tsv`, una autorregulación de un solo
locus (9043) y una arista expandida del operón de la fila 15, sin evidencia
propia.
"""

import collections
import contextlib
import csv
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from grn_bronce.exportar import COLUMNAS_CANDIDATAS, COLUMNAS_MENCIONES
from grn_comun import procedencia, redes
from grn_verificacion import cli
from grn_verificacion import contraste as C
from grn_verificacion import entrenamiento as E
from grn_verificacion import reentrenar as R
from grn_verificacion import validacion as V
from grn_verificacion.test_validacion import ENCABEZADOS, construir_xlsx

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _red_de_etapa2():
    """`etapa2/red.py` por ruta: sus columnas son el contrato que se lee."""
    ruta = os.path.join(_RAIZ, "etapa2", "red.py")
    spec = importlib.util.spec_from_file_location("_red_de_etapa2", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


RED = _red_de_etapa2()

P_XML, P_ABS, P_B, P_FUERA, P_TEST, P_OTRO = (
    "91000001", "91000002", "91000003", "91000004", "91000005", "91000006")
PMIDS = (P_XML, P_ABS, P_B, P_FUERA, P_TEST, P_OTRO)
HIST = u"Histórica (versión anterior)"

FILAS_BASE = {
    1: ENCABEZADOS,
    2: ["qzaR", "wvaA", "+", ("num", P_XML), "PA9001", "PA9002", HIST, "x"],
    3: ["qzbR", "wvbA", "-", P_ABS + ".0", "PA9003", "PA9004", HIST, "x"],
    4: ["qzcR", "wvcA", "+", P_XML, "PA9005", "PA9006", "Ambos (las dos)",
        "x"],
    5: ["qzdR", "qzdR", "+", P_XML, "PA9007", "PA9007", HIST, "x"],
    6: ["qzeR", "wveA", "-", P_XML + " homology", "PA9008", "PA9009", HIST,
        "x"],
    7: ["qzfR", "wvfA", "+", P_B, "PA9010", "PA9011", HIST, "x"],
    8: ["qzgR", "wvgA", "+", P_B + ", " + P_ABS, "PA9012", "PA9013", HIST,
        "x"],
    9: ["qzhR", "wvhA", "+", P_FUERA, "PA9014", "PA9015", HIST, "x"],
    10: ["qziR", "wviA", "+", P_TEST, "PA9016", "PA9017", "BioBERT (modelo)",
         "x"],
    11: ["qzjR", "wvjA", "Unknown", P_TEST, "PA9018", "PA9019", HIST, "x"],
    12: ["qzkR", "wvkA", "+", P_TEST + "; " + P_XML, "PA9020", "PA9021",
         HIST, "x"],
    13: ["qzlR", "wvlA", "+", P_TEST, "PA9024", "PA9025", HIST, "x"],
    14: ["qzmR", "wvmA", "+", "doi:10.1128/JB.00001-99", "PA9026", "PA9027",
         HIST, "x"],
    15: ["qznR", "wvnA", "-", P_XML, "PA9040", "PA9042", HIST, "x"],
}

# (pmid, genes_locus_tag, genes_expandidos) de cada oración candidata.
ORACIONES = [
    (P_XML, "PA9001;PA9002", ""),
    (P_OTRO, "PA9003;PA9004", ""),
    (P_XML, "PA9005", "PA9006;PA9050"),
    (P_XML, "PA9001;PA9007", ""),
    (P_XML, "PA9008;PA9009", ""),
    (P_ABS, "PA9012;PA9013", ""),
    (P_OTRO, "PA9014;PA9015", ""),
    (P_TEST, "PA9016;PA9017;PA9018;PA9019", ""),
    (P_TEST, "PA9024;PA9025", ""),
    (P_XML, "PA9040", "PA9041;PA9042"),
]

# (pmid, fuente_texto) de las unidades con alguna mención.
UNIDADES = [(P_XML, "abstract"), (P_XML, "xml"), (P_ABS, "abstract"),
            (P_B, "abstract"), (P_TEST, "xml"), (P_OTRO, "abstract")]

# (tf, blanco, signo, pmids, [(id_par, pmid, tf_locus, target_locus)]).
ARISTAS = [
    ("QzaR", "wvaA", "activates", [P_XML],
     [("e01", P_XML, ["PA9001"], ["PA9002"])]),
    ("WvbA", "qzbR", "represses", [P_OTRO],
     [("e02", P_OTRO, ["PA9004"], ["PA9003"])]),
    ("QzcR", "wvcA", "represses", [P_XML],
     [("e03", P_XML, ["PA9005"], ["PA9006"])]),
    ("QziR", "wviA", "activates", [P_TEST],
     [("e04", P_TEST, ["PA9016"], ["PA9017"])]),
    ("QzjR", "wvjA", "regulates", [P_TEST],
     [("e05", P_TEST, ["PA9018"], ["PA9019"])]),
    ("QzlR", "wvlA", "activates", [P_XML],
     [("e06", P_XML, ["PA9024"], ["PA9025"])]),
    # Un operón: una arista, dos pares de locus.
    ("QznR", "wvnABC", "represses", [P_XML],
     [("e07", P_XML, ["PA9040"], ["PA9041", "PA9042"])]),
    # El par de la fila de homología: la base lo registra.
    ("QzeR", "wveA", "activates", [P_XML],
     [("e08", P_XML, ["PA9008"], ["PA9009"])]),
    ("QzxR", "wvxA", "activates", [P_OTRO],
     [("e09", P_OTRO, ["PA9030"], ["PA9031"])]),
    ("QzyR", "wvyA", "activates", [P_OTRO],
     [("e10", P_OTRO, [], ["PA9032"])]),
    # La proteína y el gen con signos distintos: el par queda mixto.
    ("QzgR", "wvgA", "activates", [P_ABS],
     [("e11", P_ABS, ["PA9012"], ["PA9013"])]),
    ("qzgR", "wvgA", "represses", [P_ABS],
     [("e12", P_ABS, ["PA9012"], ["PA9013"])]),
]

# Para una red con otras reglas (`grn_red.consolidar`): una autorregulación
# que el perfil recomendado marca en vez de descartar, con sus dos lados en
# el mismo locus, y una expansión del operón de la e07, que copia su fila y
# no tiene evidencia propia.
AUTORREGULADA = ("QzpR", "qzpR", "activates", [P_XML],
                 [("e13", P_XML, ["PA9043"], ["PA9043"])])
OPERON, GEN_EXPANDIDO = ARISTAS[6], "wvnB"

# Lo que no puede salir en nada publicable.
_LOCUS = re.compile(r"PA[0-9]{4}")
_SIETE_U_OCHO = re.compile(r"(?<![0-9])[0-9]{7,8}(?![0-9])")


def escribir_candidatas(ruta, oraciones, corrida=4):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_CANDIDATAS)
        w.writeheader()
        for i, (pmid, locus, expandidos) in enumerate(oraciones):
            # Comillas y coma dentro de la oración: el CSV del bronce las
            # entrecomilla y el lector tiene que respetarlo.
            w.writerow({"pmid": pmid, "fuente_texto": "xml",
                        "seccion": "results", "num_oracion": i,
                        "oracion": u'Qzx "regula", según esto, a wvu.',
                        "genes_locus_tag": locus,
                        "genes_expandidos": expandidos,
                        "corrida_id": corrida,
                        "metodo": "baseline-deterministico", "version": "4"})
    return ruta


def escribir_menciones(ruta, unidades):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_MENCIONES)
        w.writeheader()
        for i, (pmid, fuente) in enumerate(unidades):
            w.writerow({"pmid": pmid, "fuente_texto": fuente,
                        "seccion": "abstract", "num_oracion": i,
                        "tipo": "organismo", "texto": "P. aeruginosa",
                        "id_normalizado": "abreviada", "offset_ini": 0,
                        "offset_fin": 13, "metodo": "baseline-deterministico",
                        "version": "4", "corrida_id": 4})
    return ruta


def _oracion(tf, blanco):
    # Una oración que empieza con comillas: leída con el csv por omisión, se
    # comería las líneas siguientes.
    return u'"%s" controla a %s, dice el texto.' % (tf, blanco)


def _fila_red(tf, blanco, signo, pmids, evidencias, autorregulacion=False):
    """Una fila de red.tsv con las columnas de etapa2/red.py."""
    return {"tf": tf, "blanco": blanco, "signo": signo,
            "conflicto": "false", "n_evidencias": len(evidencias),
            "n_activates": int(signo == "activates"),
            "n_represses": int(signo == "represses"),
            "n_regulates": int(signo == "regulates"),
            "n_articulos": len(pmids), "confianza": "0.9000",
            "autorregulacion": "true" if autorregulacion else "false",
            "secciones": "results", "pmids": "|".join(pmids),
            "oracion_representativa": _oracion(tf, blanco)}


def _escribir_evidencias(fe, fp, tf, blanco, signo, evidencias,
                         autorregulacion=False):
    """Las filas de red_evidencias.tsv de una arista y, si `fp` no es None,
    sus pares en pares.jsonl."""
    for id_par, pmid, tf_locus, target_locus in evidencias:
        ev = {"tf": tf, "blanco": blanco, "id_par": id_par, "pmid": pmid,
              "seccion": "results", "fuente": "fulltext",
              "prediccion": signo, "probabilidad": "0.900000",
              "redaccion": "directa", "oracion": _oracion(tf, blanco)}
        fe.write("\t".join(str(ev[c]) for c in RED.COLUMNAS_EVIDENCIAS)
                 + "\n")
        if fp is not None:
            fp.write(json.dumps({
                "id_par": id_par, "pmid": int(pmid), "tf": tf,
                "target": blanco,
                "text": "<e1> %s </e1> controla a <e2> %s </e2> ."
                        % (tf, blanco),
                "tf_locus": tf_locus, "target_locus": target_locus,
                "autorregulacion": autorregulacion},
                ensure_ascii=False) + "\n")


def sellar_red(carpeta, informe=redes.INFORME):
    """El sello de `red.py` en su informe: la huella del pares.jsonl."""
    huella = procedencia.huella(os.path.join(carpeta, "pares.jsonl"))
    with io.open(os.path.join(carpeta, informe), "w", encoding="utf-8") as f:
        json.dump({"huellas": {"pares": {"huella": huella}}}, f)


def escribir_red(carpeta, aristas, sellar=True):
    """red.tsv y red_evidencias.tsv con las columnas de etapa2/red.py, el
    pares.jsonl del puente y el sello de red_informe.json."""
    with io.open(os.path.join(carpeta, "red.tsv"), "w", encoding="utf-8",
                 newline="\n") as fr, \
            io.open(os.path.join(carpeta, "red_evidencias.tsv"), "w",
                    encoding="utf-8", newline="\n") as fe, \
            io.open(os.path.join(carpeta, "pares.jsonl"), "w",
                    encoding="utf-8", newline="\n") as fp:
        fr.write("\t".join(RED.COLUMNAS_RED) + "\n")
        fe.write("\t".join(RED.COLUMNAS_EVIDENCIAS) + "\n")
        for tf, blanco, signo, pmids, evidencias in aristas:
            fila = _fila_red(tf, blanco, signo, pmids, evidencias)
            fr.write("\t".join(str(fila[c]) for c in RED.COLUMNAS_RED)
                     + "\n")
            _escribir_evidencias(fe, fp, tf, blanco, signo, evidencias)
    if sellar:
        sellar_red(carpeta)


def escribir_red_con_reglas(carpeta, nombre, aristas, autorreguladas=(),
                            expandidas=()):
    """red_<nombre>.tsv, sus evidencias y su informe, como los deja
    `grn_red.consolidar` con el perfil recomendado.

    Las columnas son las de etapa2/red.py más `nivel_soporte` y
    `expandida_de`. Las evidencias son las de red.py, de las aristas
    observadas: una expandida, dada como (arista del operón, gen), copia la
    fila del operón y no tiene ninguna. Los pares de las autorreguladas se
    agregan a pares.jsonl, y los dos informes se vuelven a sellar con la
    huella nueva. Va después de `escribir_red`, que escribe pares.jsonl.
    """
    archivo_red, archivo_evidencias, archivo_informe = \
        redes.archivos_de_red(nombre)
    filas = []
    with io.open(os.path.join(carpeta, archivo_evidencias), "w",
                 encoding="utf-8", newline="\n") as fe, \
            io.open(os.path.join(carpeta, "pares.jsonl"), "a",
                    encoding="utf-8", newline="\n") as fp:
        fe.write("\t".join(RED.COLUMNAS_EVIDENCIAS) + "\n")
        for tf, blanco, signo, pmids, evidencias in aristas:
            filas.append(_fila_red(tf, blanco, signo, pmids, evidencias))
            # Sus pares ya están: los escribió escribir_red.
            _escribir_evidencias(fe, None, tf, blanco, signo, evidencias)
        for tf, blanco, signo, pmids, evidencias in autorreguladas:
            filas.append(_fila_red(tf, blanco, signo, pmids, evidencias,
                                   autorregulacion=True))
            _escribir_evidencias(fe, fp, tf, blanco, signo, evidencias,
                                 autorregulacion=True)
    for (tf, blanco, signo, pmids, evidencias), gen in expandidas:
        fila = _fila_red(tf, gen, signo, pmids, evidencias)
        fila["oracion_representativa"] = _oracion(tf, blanco)
        fila["expandida_de"] = blanco
        filas.append(fila)
    columnas = list(RED.COLUMNAS_RED) + ["nivel_soporte", "expandida_de"]
    with io.open(os.path.join(carpeta, archivo_red), "w", encoding="utf-8",
                 newline="\n") as fr:
        fr.write("\t".join(columnas) + "\n")
        for fila in filas:
            fila.setdefault("expandida_de", "")
            fila["nivel_soporte"] = ("candidata" if fila["n_articulos"] == 1
                                     else "soporte_multiple")
            fr.write("\t".join(str(fila[c]) for c in columnas) + "\n")
    if os.path.isfile(os.path.join(carpeta, redes.INFORME)):
        sellar_red(carpeta)
    sellar_red(carpeta, archivo_informe)


def escribir_lista(ruta, pmids):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("# PMIDs sintéticos\n")
        for p in pmids:
            f.write("pmid\t%s\n" % p)
    return ruta


class _ConEscenario(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="grn_contraste_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = construir_xlsx(
            os.path.join(self.tmp, "base_sintetica.xlsx"),
            [("Hoja1", FILAS_BASE)])
        self.carpeta = os.path.join(self.tmp, "corrida4_prueba")
        os.makedirs(self.carpeta)
        self.prefijo = os.path.join(self.carpeta,
                                    "bronce_identificacion_corrida4_20990101")
        self.candidatas = escribir_candidatas(
            self.prefijo + "_oraciones_candidatas.csv", ORACIONES)
        self.menciones = escribir_menciones(
            self.prefijo + "_menciones.csv", UNIDADES)
        escribir_red(self.carpeta, ARISTAS)
        self.excluir = escribir_lista(os.path.join(self.tmp, "excluir.tsv"),
                                      [P_B])
        self.solo = escribir_lista(os.path.join(self.tmp, "solo.tsv"),
                                   [P_TEST])
        self.confidencial = os.path.join(self.tmp, "confidencial")
        self.informe = os.path.join(self.tmp, "publicable", "contraste.md")

    def interacciones(self):
        return V.leer_base(self.base)[0]

    def exigibles(self):
        return C.denominador(self.interacciones(), {P_B})[0]

    def por_fila(self, filas):
        return dict((f["fila_origen"], f) for f in filas)

    def pares(self):
        return collections.OrderedDict([
            ("con_expansion", C.pares_del_bronce(self.candidatas, True)),
            ("sin_expansion", C.pares_del_bronce(self.candidatas, False))])

    def docs(self):
        return C.documentos_del_bronce(self.menciones)

    def aristas(self, red=None):
        nombre_red, nombre_evidencias, _ = redes.archivos_de_red(red)
        return C.aristas_en_locus(
            os.path.join(self.carpeta, nombre_red),
            os.path.join(self.carpeta, nombre_evidencias),
            os.path.join(self.carpeta, "pares.jsonl"))

    def con_reglas(self):
        """Escribe `red_prueba.tsv` junto a `red.tsv`."""
        escribir_red_con_reglas(self.carpeta, "prueba", ARISTAS,
                                [AUTORREGULADA], [(OPERON, GEN_EXPANDIDO)])

    def correr(self, **kwargs):
        lineas = []
        kwargs.setdefault("informe", self.informe)
        kwargs.setdefault("excluir", [self.excluir])
        kwargs.setdefault("aceptar_base_distinta", True)
        resultado = C.ejecutar(self.base, self.carpeta, self.confidencial,
                               log=lineas.append, **kwargs)
        return resultado, lineas

    def assertSinContenido(self, texto):
        """Ni locus, ni PMIDs, ni nombres de gen, ni rutas."""
        self.assertIsNone(_LOCUS.search(texto))
        self.assertIsNone(_SIETE_U_OCHO.search(texto))
        for pmid in PMIDS:
            self.assertNotIn(pmid, texto)
        for nombre in ("qz", "wv"):
            self.assertNotIn(nombre, texto.lower())
        for ruta in (self.tmp, self.tmp.replace("\\", "/"),
                     os.path.basename(self.tmp), "base_sintetica"):
            self.assertNotIn(ruta, texto)
        R.verificar_publicable(texto)


class PruebasDenominador(_ConEscenario):

    def test_exclusiones_por_homologia_y_por_archivo(self):
        exigibles, c = C.denominador(self.interacciones(), {P_B})
        self.assertEqual([2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15],
                         sorted(f["fila_origen"] for f in exigibles))
        self.assertEqual((14, 1, 1, 12), (c["base"], c["homologia"],
                                          c["excluidas_por_archivo"],
                                          c["exigibles"]))
        # La fila 8 cita al excluido y a otro: se queda.
        self.assertIn(8, [f["fila_origen"] for f in exigibles])
        # La del DOI no tiene PMID y se queda: el archivo no dice nada de ella.
        self.assertEqual(1, c["sin_pmid"])
        self.assertEqual(1, c["autorregulacion"])
        self.assertEqual({"+": 9, "-": 2, "?": 1, "d": 0, "ilegible": 0},
                         dict(c["signo"]))
        self.assertEqual({"historica": 10, "ambos": 1, "biobert": 1,
                          "otro": 0}, dict(c["origen"]))

    def test_la_homologia_va_antes_que_el_archivo(self):
        filas = self.interacciones()
        # Excluyendo el artículo de la fila de homología, esa fila sigue
        # contando como homología (el orden de PLAN.md 2.4).
        _, c = C.denominador(filas, {P_XML})
        self.assertEqual(1, c["homologia"])
        self.assertEqual("homologia",
                         C.motivo_de(self.por_fila(filas)[6], {P_XML}))

    def test_sin_archivo_solo_sale_la_homologia(self):
        exigibles, c = C.denominador(self.interacciones())
        self.assertEqual((0, 13), (c["excluidas_por_archivo"],
                                   c["exigibles"]))
        self.assertEqual((0, 0), (c["citan_excluido_y_otro"],
                                  c["homologia_que_cita_excluido"]))

    def test_la_conciliacion_con_el_archivo_de_exclusiones(self):
        """Con P_B sale la fila 7 y se queda la 8, que cita además P_ABS:
        es la que separa «todos sus PMIDs» de «cita el artículo». Con P_XML
        salen las 2, 4, 5 y 15, se queda la 12 (cita también P_TEST) y la 6,
        que lo cita, ya había salido por homología: 14 - 1 - 4 = 9."""
        _, c = C.denominador(self.interacciones(), {P_B})
        self.assertEqual((1, 1, 0), (c["excluidas_por_archivo"],
                                     c["citan_excluido_y_otro"],
                                     c["homologia_que_cita_excluido"]))
        _, c = C.denominador(self.interacciones(), {P_XML})
        self.assertEqual((1, 4, 1, 1, 9),
                         (c["homologia"], c["excluidas_por_archivo"],
                          c["citan_excluido_y_otro"],
                          c["homologia_que_cita_excluido"], c["exigibles"]))


class PruebasBronce(_ConEscenario):

    def test_un_articulo_es_de_xml_si_alguna_unidad_lo_es(self):
        self.assertEqual({P_XML: "xml", P_ABS: "abstract", P_B: "abstract",
                          P_TEST: "xml", P_OTRO: "abstract"}, self.docs())

    def test_pares_con_y_sin_expansion(self):
        con, por_pmid_con = C.pares_del_bronce(self.candidatas, True)
        sin, por_pmid_sin = C.pares_del_bronce(self.candidatas, False)
        self.assertIn(("PA9005", "PA9006"), con)
        self.assertNotIn(("PA9005", "PA9006"), sin)
        self.assertIn(("PA9040", "PA9042"), por_pmid_con[P_XML])
        self.assertNotIn(("PA9040", "PA9042"), por_pmid_sin[P_XML])
        # El par no tiene dirección: siempre (menor, mayor).
        self.assertTrue(all(a < b for a, b in con))
        self.assertTrue(sin <= con)

    def test_regla_a_sin_regla_b(self):
        fila = self.por_fila(self.exigibles())[3]
        pares = self.pares()["con_expansion"]
        self.assertTrue(C.cubierta(fila, pares, "a"))
        self.assertFalse(C.cubierta(fila, pares, "b"))

    def test_cobertura_que_solo_da_la_expansion(self):
        filas = self.por_fila(self.exigibles())
        pares = self.pares()
        for numero in (4, 15):
            for regla in ("a", "b"):
                self.assertTrue(C.cubierta(filas[numero],
                                           pares["con_expansion"], regla))
                self.assertFalse(C.cubierta(filas[numero],
                                            pares["sin_expansion"], regla))
        cob = C.cobertura_bronce(self.exigibles(), self.docs(), pares)
        self.assertEqual({"todas": 2, "en_corpus": 2, "con_xml": 2,
                          "solo_abstract": 0},
                         dict(cob["solo_por_expansion"]["a"]))

    def test_la_autorregulacion_nunca_se_cubre(self):
        fila = self.por_fila(self.exigibles())[5]
        # Aun con el par de un locus consigo mismo en los dos conjuntos.
        trampa = ({("PA9007", "PA9007")}, {P_XML: {("PA9007", "PA9007")}})
        for regla in ("a", "b"):
            self.assertFalse(C.cubierta(fila, trampa, regla))
        cob = C.cobertura_bronce(self.exigibles(), self.docs(), self.pares())
        self.assertEqual(1, cob["autorregulacion"]["todas"])
        self.assertEqual(1, cob["autorregulacion"]["con_xml"])
        # Está en el denominador: 12 filas, no 11.
        self.assertEqual(12, cob["n"]["todas"])

    def test_los_grupos_xml_y_abstract(self):
        docs = self.docs()
        filas = self.por_fila(self.exigibles())
        self.assertEqual("con_xml", C.grupo_de(filas[12], docs))
        self.assertEqual("solo_abstract", C.grupo_de(filas[8], docs))
        self.assertEqual("solo_abstract", C.grupo_de(filas[3], docs))
        self.assertEqual("fuera", C.grupo_de(filas[9], docs))
        self.assertEqual("fuera", C.grupo_de(filas[14], docs))
        cob = C.cobertura_bronce(self.exigibles(), docs, self.pares())
        self.assertEqual({"todas": 12, "en_corpus": 10, "con_xml": 8,
                          "solo_abstract": 2}, dict(cob["n"]))

    def test_las_cifras_por_regla_grupo_y_variante(self):
        cob = C.cobertura_bronce(self.exigibles(), self.docs(), self.pares())
        esperado = {
            ("con_expansion", "a"): (9, 8, 6, 2),
            ("con_expansion", "b"): (7, 7, 6, 1),
            ("sin_expansion", "a"): (7, 6, 4, 2),
            ("sin_expansion", "b"): (5, 5, 4, 1),
        }
        for (v, regla), ks in esperado.items():
            self.assertEqual(ks, tuple(cob[v][regla][g]["k"]
                                       for g in C.GRUPOS), (v, regla))
        p = cob["con_expansion"]["a"]["todas"]
        self.assertEqual((9, 12, 0.75), (p["k"], p["n"], p["valor"]))
        self.assertLess(p["ic95"][0], 0.75)
        self.assertGreater(p["ic95"][1], 0.75)

    def test_ubicar_prefiere_el_csv_del_estado(self):
        otro = os.path.join(self.carpeta,
                            "bronce_identificacion_corrida4_20990202")
        escribir_candidatas(otro + "_oraciones_candidatas.csv", ORACIONES[:1])
        escribir_menciones(otro + "_menciones.csv", UNIDADES[:1])
        tiempo = os.path.getmtime(self.candidatas) + 60
        os.utime(otro + "_oraciones_candidatas.csv", (tiempo, tiempo))
        # Sin estado: el más reciente.
        self.assertEqual(otro + "_oraciones_candidatas.csv",
                         C.ubicar_archivos(self.carpeta)["candidatas"])
        with io.open(os.path.join(self.carpeta, "estado.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"archivos": {"candidatas": os.path.basename(
                self.candidatas)}}, f)
        rutas = C.ubicar_archivos(self.carpeta)
        self.assertEqual(self.candidatas, rutas["candidatas"])
        self.assertEqual(self.menciones, rutas["menciones"])


class PruebasRed(_ConEscenario):

    def test_las_aristas_se_llevan_a_locus_y_el_operon_se_expande(self):
        aristas, c = self.aristas()
        self.assertEqual((12, 11, 1, 1, 11),
                         (c["aristas"], c["con_locus"], c["sin_locus"],
                          c["expandidas"], c["pares_locus"]))
        self.assertIn(("PA9040", "PA9041"), aristas)
        self.assertIn(("PA9040", "PA9042"), aristas)
        self.assertEqual({"activates": 6, "represses": 4, "regulates": 1},
                         dict(c["por_signo"]))
        # La oración entre comillas no se comió ninguna línea.
        self.assertEqual(2, len(aristas[("PA9012", "PA9013")]))

    def test_un_id_par_que_no_esta_en_los_pares_detiene(self):
        ruta = os.path.join(self.carpeta, "pares.jsonl")
        with io.open(ruta, encoding="utf-8") as f:
            lineas = [l for l in f if '"e05"' not in l]
        with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lineas)
        with self.assertRaises(ValueError) as ctx:
            self.aristas()
        self.assertIn("misma corrida", str(ctx.exception))

    def test_red_dirigida_contra_inversa(self):
        aristas, _ = self.aristas()
        filas = self.por_fila(self.exigibles())
        self.assertEqual(("dirigido", "activates"),
                         C.en_red(filas[2], aristas))
        self.assertEqual(("inverso", None), C.en_red(filas[3], aristas))
        self.assertEqual(("no", None), C.en_red(filas[12], aristas))
        r = C.recall_red(self.exigibles(), aristas)["estratos"][C.PRINCIPAL]
        self.assertEqual((11, 6, 1, 7), (r["n"], r["dirigido"]["k"],
                                         r["inverso"]["k"],
                                         r["cualquiera"]["k"]))
        self.assertEqual(1, r["autorregulacion"])

    def test_el_signo(self):
        aristas, _ = self.aristas()
        filas = self.por_fila(self.exigibles())
        self.assertEqual("acuerdo", C.juicio_signo(
            "+", C.en_red(filas[2], aristas)[1]))
        self.assertEqual("acuerdo", C.juicio_signo(
            "-", C.en_red(filas[15], aristas)[1]))
        self.assertEqual("contrario", C.juicio_signo(
            "+", C.en_red(filas[4], aristas)[1]))
        self.assertEqual("mixto", C.en_red(filas[8], aristas)[1])
        self.assertEqual("regulates", C.juicio_signo("+", "regulates"))
        # Un `?` de la base no tiene signo que juzgar.
        self.assertIsNone(C.juicio_signo("?", "regulates"))
        s = C.recall_red(self.exigibles(),
                         aristas)["estratos"][C.PRINCIPAL]["signo"]
        self.assertEqual((5, 3, 1, 0, 1), (s["n"], s["acuerdo"]["k"],
                                           s["contrario"], s["regulates"],
                                           s["mixto"]))

    def test_solo_pmids(self):
        aristas, _ = self.aristas()
        filas = self.por_fila(self.exigibles())
        solo = {P_TEST}
        self.assertEqual("evaluada", C.en_test(filas[13], solo))
        self.assertEqual("mezcla", C.en_test(filas[12], solo))
        self.assertEqual("fuera", C.en_test(filas[14], solo))
        # La arista de la fila 13 solo tiene evidencia de un artículo que no
        # es de test: sin el filtro se encuentra, con él no.
        self.assertEqual("dirigido", C.en_red(filas[13], aristas)[0])
        self.assertEqual("no", C.en_red(filas[13], aristas, solo)[0])
        r = C.recall_red(self.exigibles(), aristas, solo)
        self.assertEqual({"pmids": 1, "evaluadas": 3, "mezcla": 1,
                          "fuera": 8}, dict(r["solo_pmids"]))
        principal = r["estratos"][C.PRINCIPAL]
        self.assertEqual((2, 1), (principal["n"], principal["dirigido"]["k"]))
        self.assertEqual(0, principal["signo"]["n"])
        # La 11 dirigida y nada al revés; sin signo que juzgar, la línea base
        # queda sin denominador.
        self.assertEqual((1, 1), (principal["orientacion"]["k"],
                                  principal["orientacion"]["n"]))
        self.assertIsNone(principal["signo"]["acuerdo_si_da_signo"]["valor"])

    def test_el_estrato_biobert_va_aparte(self):
        aristas, _ = self.aristas()
        e = C.recall_red(self.exigibles(), aristas)["estratos"]
        self.assertEqual((1, 1, 1), (e["biobert"]["n"],
                                     e["biobert"]["dirigido"]["k"],
                                     e["biobert"]["signo"]["acuerdo"]["k"]))
        self.assertEqual(10, e["historica"]["n"])
        self.assertEqual(1, e["ambos"]["n"])
        self.assertEqual(0, e["otro"]["n"])
        # La principal junta Histórica, Ambos y otro, y nada de BioBERT.
        self.assertEqual(e["historica"]["n"] + e["ambos"]["n"]
                         + e["otro"]["n"], e[C.PRINCIPAL]["n"])

    def test_el_estrato_de_una_fila(self):
        filas = self.por_fila(self.exigibles())
        self.assertEqual(("historica", "ambos", "biobert"),
                         (C.estrato_de(filas[2]), C.estrato_de(filas[4]),
                          C.estrato_de(filas[10])))
        # Un valor que no es de los medidos cuenta como «otro».
        self.assertEqual("otro", C.estrato_de(dict(filas[2], origen="nuevo")))

    def test_la_linea_base_y_la_orientacion_por_estrato(self):
        """Las dirigidas con signo sin BioBERT son la 2 (+, acuerdo), la 4
        (+, contrario), la 8 (+, mixto), la 13 (+, acuerdo) y la 15 (-,
        acuerdo). Resueltas, las de acuerdo o contrario: 2, 4, 13 y 15; con
        + en la base, 2, 4 y 13. Siempre activa acierta en 4 de las 5
        dirigidas con signo. La orientación: 6 dirigidas de las 7 que la red
        encuentra (la 3 va al revés).

        Por estrato, (orientación, resueltas, resueltas con +, dirigidas con
        signo y +, acuerdo cuando da signo, siempre activa en las resueltas,
        siempre activa con abstención), con cada proporción como (k, n)."""
        aristas, _ = self.aristas()
        e = C.recall_red(self.exigibles(), aristas)["estratos"]

        def kn(p):
            return (p["k"], p["n"])

        esperado = {
            C.PRINCIPAL: ((6, 7), 4, 3, 4, (3, 4), (3, 4), (4, 5)),
            "historica": ((5, 6), 3, 2, 3, (3, 3), (2, 3), (3, 4)),
            "ambos": ((1, 1), 1, 1, 1, (0, 1), (1, 1), (1, 1)),
            "otro": ((0, 0), 0, 0, 0, (0, 0), (0, 0), (0, 0)),
            "biobert": ((1, 1), 1, 1, 1, (1, 1), (1, 1), (1, 1)),
        }
        for nombre, valores in esperado.items():
            s = e[nombre]["signo"]
            self.assertEqual(valores, (
                kn(e[nombre]["orientacion"]), s["resueltas"],
                s["resueltas_mas"], s["con_signo_mas"],
                kn(s["acuerdo_si_da_signo"]), kn(s["linea_base_siempre_mas"]),
                kn(s["linea_base_siempre_mas_con_abstencion"])), nombre)
        p = e[C.PRINCIPAL]
        # Resueltas es acuerdo más contrario; con abstención, el mismo
        # denominador que el acuerdo de siempre; la orientación, dirigido
        # entre cualquier dirección (642/674 en la corrida 4).
        self.assertEqual(p["signo"]["acuerdo"]["k"] + p["signo"]["contrario"],
                         p["signo"]["resueltas"])
        self.assertEqual(p["signo"]["n"], p["signo"]
                         ["linea_base_siempre_mas_con_abstencion"]["n"])
        self.assertEqual((p["dirigido"]["k"], p["cualquiera"]["k"]),
                         kn(p["orientacion"]))
        self.assertIsNone(e["otro"]["orientacion"]["valor"])

    def test_regulates_no_cuenta_entre_las_resueltas(self):
        """En el escenario ninguna dirigida con signo en la base sale
        regulates (la 11 es `?`), así que nada distinguía «resueltas» de
        «acuerdo, contrario y regulates». Con la arista de la fila 2 en
        regulates, las dirigidas con signo sin BioBERT siguen siendo 5, y las
        resueltas son la 4 (+, contrario), la 13 (+, acuerdo) y la 15 (-,
        acuerdo): 3, con 2 de +. La 8 sigue mixta."""
        aristas, _ = self.aristas()
        aristas = dict(aristas)
        aristas[("PA9001", "PA9002")] = [
            dict(a, signo="regulates") for a in aristas[("PA9001", "PA9002")]]
        s = C.recall_red(self.exigibles(),
                         aristas)["estratos"][C.PRINCIPAL]["signo"]

        def kn(p):
            return (p["k"], p["n"])

        self.assertEqual((5, 2, 1, 1, 1), (s["n"], s["acuerdo"]["k"],
                                           s["contrario"], s["regulates"],
                                           s["mixto"]))
        self.assertEqual((3, 2, 4), (s["resueltas"], s["resueltas_mas"],
                                     s["con_signo_mas"]))
        self.assertEqual(((2, 3), (2, 3), (4, 5)), (
            kn(s["acuerdo_si_da_signo"]), kn(s["linea_base_siempre_mas"]),
            kn(s["linea_base_siempre_mas_con_abstencion"])))

    def test_el_techo_sin_biobert(self):
        """Sin BioBERT son 11 filas, todas menos la 10: 9 en el corpus (no la
        9 ni la 14), 7 con XML y 2 solo abstract (la 3 y la 8). La regla a)
        con expansión cubre la 2, 3, 4, 8, 9, 11, 13 y 15; sin expansión
        pierde la 4 y la 15. La b) con expansión, la 2, 4, 8, 11, 13 y 15;
        sin expansión, la 2, 8, 11 y 13. La red encuentra en alguna
        dirección la 2, 3, 4, 8, 11, 13 y 15, todas dentro de la a)."""
        aristas, _ = self.aristas()
        exigibles, docs, pares = self.exigibles(), self.docs(), self.pares()
        techo = C.techo_sin_biobert(exigibles, docs, pares, aristas)
        self.assertEqual(11, techo["n"])
        cob = techo["cobertura"]
        self.assertEqual({"todas": 11, "en_corpus": 9, "con_xml": 7,
                          "solo_abstract": 2}, dict(cob["n"]))
        esperado = {
            ("con_expansion", "a"): (8, 7, 5, 2),
            ("con_expansion", "b"): (6, 6, 5, 1),
            ("sin_expansion", "a"): (6, 5, 3, 2),
            ("sin_expansion", "b"): (4, 4, 3, 1),
        }
        for (v, regla), ks in esperado.items():
            self.assertEqual(ks, tuple(cob[v][regla][g]["k"]
                                       for g in C.GRUPOS), (v, regla))
        self.assertEqual(0, techo["red_cualquiera_fuera_de_a"])
        # Las mismas filas que la cifra principal de la red.
        principal = C.recall_red(exigibles, aristas)["estratos"][C.PRINCIPAL]
        self.assertEqual(principal["n"], techo["n"])

        # Una arista que la a) no cubre, al revés de la fila 12 (que no tiene
        # candidata): la red la encuentra y queda fuera. Es un dato.
        otra = dict(aristas)
        otra[("PA9021", "PA9020")] = [{"tf": "x", "blanco": "y",
                                       "signo": "activates",
                                       "pmids": frozenset()}]
        self.assertEqual(1, C.techo_sin_biobert(
            exigibles, docs, pares, otra)["red_cualquiera_fuera_de_a"])
        # La misma fila con Origen BioBERT no entra al techo.
        con_biobert = [dict(f, origen="biobert") if f["fila_origen"] == 12
                       else f for f in exigibles]
        techo = C.techo_sin_biobert(con_biobert, docs, pares, otra)
        self.assertEqual((10, 0), (techo["n"],
                                   techo["red_cualquiera_fuera_de_a"]))
        # Sin red no hay cruce.
        self.assertIsNone(C.techo_sin_biobert(
            exigibles, docs, pares)["red_cualquiera_fuera_de_a"])

    def test_una_red_con_otras_reglas(self):
        """red_prueba.tsv: las 12 aristas de red.tsv, la autorregulación de un
        solo locus y la expandida sin evidencia propia, 14 filas. No se
        detiene, y da los mismos pares de locus que red.tsv."""
        self.con_reglas()
        normal, c_normal = self.aristas()
        otra, c = self.aristas("prueba")
        self.assertEqual((14, 11, 1, 1, 1, 1, 11),
                         (c["aristas"], c["con_locus"], c["sin_locus"],
                          c["solo_autorregulacion"], c["expandidas_omitidas"],
                          c["expandidas"], c["pares_locus"]))
        self.assertEqual(normal, otra)
        self.assertEqual(c_normal["por_signo"], c["por_signo"])
        self.assertEqual((0, 0), (c_normal["solo_autorregulacion"],
                                  c_normal["expandidas_omitidas"]))
        # Lo que decide es la marca y no el locus: la misma arista sin marcar
        # cuenta como sin locus, como en red.tsv.
        escribir_red_con_reglas(self.carpeta, "sin_marca",
                                ARISTAS + [AUTORREGULADA])
        _, c = self.aristas("sin_marca")
        self.assertEqual((13, 2, 0), (c["aristas"], c["sin_locus"],
                                      c["solo_autorregulacion"]))

    def test_una_expandida_que_se_llama_como_una_observada_tambien_se_omite(
            self):
        """En red_recomendada.tsv de la corrida 4, 695 de las 1 533 expandidas
        se llaman como una arista observada y tienen evidencias bajo ese
        nombre. Se omiten igual: leída con las evidencias de la observada, la
        expandida, que copia el signo de su operón, le pondría al par un signo
        que no es el suyo. Aquí la observada es la de la fila 2 (activates) y
        la expandida, de un operón inventado, dice represses."""
        operon = ("QzaR", "wvaXYZ", "represses", [P_XML], [])
        escribir_red_con_reglas(self.carpeta, "prueba", ARISTAS,
                                expandidas=[(operon, "wvaA")])
        normal, _ = self.aristas()
        otra, c = self.aristas("prueba")
        self.assertEqual((13, 1, 11), (c["aristas"], c["expandidas_omitidas"],
                                       c["con_locus"]))
        self.assertEqual(normal, otra)
        self.assertEqual("activates", C.signo_par(otra[("PA9001", "PA9002")]))

    def test_sin_expandida_de_una_arista_sin_evidencias_detiene(self):
        """La expandida se omite por su columna, no por faltarle evidencia:
        vacía la marca y la misma fila detiene el contraste, con el mensaje
        en los archivos de esa red."""
        self.con_reglas()
        ruta = os.path.join(self.carpeta, "red_prueba.tsv")
        with io.open(ruta, encoding="utf-8") as f:
            lineas = f.readlines()
        marca = "\t" + OPERON[1] + "\n"
        lineas = [l[:-len(marca)] + "\t\n" if l.endswith(marca) else l
                  for l in lineas]
        with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lineas)
        with self.assertRaises(ValueError) as ctx:
            self.aristas("prueba")
        mensaje = str(ctx.exception)
        self.assertIn("red_prueba.tsv", mensaje)
        self.assertIn("red_prueba_evidencias.tsv", mensaje)
        self.assertNotIn(self.tmp, mensaje)

    def test_candidatas_nuevas(self):
        aristas, _ = self.aristas()
        nuevas = C.candidatas_nuevas(aristas,
                                     C.curados_de(self.interacciones()))
        self.assertEqual([("PA9030", "PA9031", "activates"),
                          ("PA9040", "PA9041", "represses")],
                         [(n["regulador"], n["blanco"], n["signo"])
                          for n in nuevas])
        # Ni la del revés de la fila 3 ni la de la fila de homología.
        pares = set((n["regulador"], n["blanco"]) for n in nuevas)
        self.assertNotIn(("PA9004", "PA9003"), pares)
        self.assertNotIn(("PA9008", "PA9009"), pares)


class PruebasEjecutar(_ConEscenario):

    def test_un_cotejo_que_no_cuadra_se_detiene(self):
        lineas = []
        with self.assertRaises(ValueError) as ctx:
            C.ejecutar(self.base, self.carpeta, self.confidencial,
                       informe=self.informe, excluir=[self.excluir],
                       log=lineas.append)
        self.assertIn("--aceptar-base-distinta", str(ctx.exception))
        self.assertFalse(os.path.exists(self.confidencial))
        self.assertFalse(os.path.exists(self.informe))
        self.assertIn("Base: filas esperado 5 584, medido 14.", lineas)
        self.assertSinContenido("\n".join(lineas + [str(ctx.exception)]))

    def test_con_la_base_esperada_no_hace_falta_aceptar(self):
        _, medidos = V.leer_base(self.base)
        esperada = collections.OrderedDict()
        for clave, valor in R.BASE_ESPERADA.items():
            if isinstance(valor, dict):
                esperada[clave] = collections.OrderedDict(
                    (k, medidos[clave][k]) for k in valor)
            else:
                esperada[clave] = medidos[clave]
        with mock.patch.object(R, "BASE_ESPERADA", esperada):
            resultado, _ = self.correr(aceptar_base_distinta=False)
        self.assertEqual(0, resultado["base"]["diferencias"])
        with io.open(self.informe, encoding="utf-8") as f:
            self.assertIn("Coincide en todo.", f.read())

    def test_de_punta_a_punta(self):
        resultado, lineas = self.correr(solo=[self.solo])
        d = resultado["denominador"]
        self.assertEqual((12, 1, 1, 1), (d["exigibles"], d["homologia"],
                                         d["excluidas_por_archivo"],
                                         d["autorregulacion"]))
        self.assertEqual(11, d["en_los_5_articulos_mayores"])
        b = resultado["bronce"]
        self.assertEqual((4, 5, 2, 3, 10), (b["corrida"], b["documentos"],
                                            b["con_xml"], b["solo_abstract"],
                                            b["oraciones"]))
        cob = resultado["cobertura"]
        self.assertEqual(9, cob["con_expansion"]["a"]["todas"]["k"])
        self.assertEqual(6, cob["con_expansion"]["b"]["con_xml"]["k"])
        self.assertEqual(1, resultado["homologia"]["con_expansion"]["b"]
                         ["todas"]["k"])
        red = resultado["red"]
        self.assertEqual(6, red["recall"]["estratos"][C.PRINCIPAL]
                         ["dirigido"]["k"])
        self.assertEqual(3, red["recall_test"]["solo_pmids"]["evaluadas"])
        self.assertEqual(2, red["candidatas_nuevas"]["pares"])
        self.assertEqual({"archivos": 1, "pmids": 1, "pmids_citados": 1,
                          "oraciones_ignoradas": 0},
                         dict(resultado["exclusiones"]))
        self.assertEqual((1, 0), (d["citan_excluido_y_otro"],
                                  d["homologia_que_cita_excluido"]))
        self.assertEqual((14, 14, 0), (resultado["base"]["filas"],
                                       resultado["base"]["interacciones"],
                                       resultado["base"]["locus_invalido"]))
        self.assertEqual("red.tsv", red["archivo"])
        self.assertEqual((0, 0), (red["conteos"]["expandidas_omitidas"],
                                  red["conteos"]["solo_autorregulacion"]))
        self.assertEqual((11, 0), (resultado["techo_sin_biobert"]["n"],
                                   resultado["techo_sin_biobert"]
                                   ["red_cualquiera_fuera_de_a"]))

        with io.open(os.path.join(self.confidencial, C.ARCHIVO_POR_FILA),
                     encoding="utf-8", newline="") as f:
            por_fila = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(14, len(por_fila))
        motivos = collections.Counter(f["motivo"] for f in por_fila)
        self.assertEqual({"exigible": 12, "homologia": 1,
                          "excluida_por_archivo": 1}, dict(motivos))
        fila4 = [f for f in por_fila if f["fila_origen"] == "4"][0]
        self.assertEqual(("si", "no", "dirigido", "contrario"),
                         (fila4["a_con_expansion"], fila4["a_sin_expansion"],
                          fila4["red"], fila4["juicio_signo"]))
        fila13 = [f for f in por_fila if f["fila_origen"] == "13"][0]
        self.assertEqual(("evaluada", "no"), (fila13["test"],
                                              fila13["red_test"]))
        with io.open(os.path.join(self.confidencial, C.ARCHIVO_NUEVAS),
                     encoding="utf-8", newline="") as f:
            nuevas = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(["PA9030", "PA9040"],
                         [n["regulador"] for n in nuevas])
        with io.open(os.path.join(self.confidencial, C.ARCHIVO_REGISTRO),
                     encoding="utf-8") as f:
            registro = json.load(f)
        self.assertEqual(procedencia.huella(self.base),
                         registro["huellas"]["base"])
        self.assertIsNone(registro["parametros"]["red"])
        self.assertTrue(lineas[-1].startswith("Escritos en la carpeta de "
                                              "--confidencial"))

    def test_el_informe_no_lleva_contenido_de_la_base(self):
        _, lineas = self.correr(solo=[self.solo])
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertSinContenido(texto)
        self.assertSinContenido("\n".join(lineas))
        # Y sí lleva lo que tiene que llevar.
        self.assertIn("9/12 (75.0 %)", texto)
        self.assertIn("BioBERT (circular, aparte)", texto)
        self.assertIn("Solo los artículos de test", texto)
        self.assertIn("**DIFIERE**", texto)
        # La corrida 4 no se compara con la 1.
        self.assertNotIn("Frente a PLAN.md 2.4", texto)

    def test_el_informe_lleva_la_conciliacion_del_denominador(self):
        """Las cifras de las pruebas del denominador, en la sección 2."""
        _, lineas = self.correr()
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("- 14 filas con valores, 14 con los dos locus: 0 con un "
                      "locus inválido.", texto)
        self.assertIn("- 1 cita el artículo excluido junto con otro y se "
                      "queda, porque la regla es «todos sus PMIDs». Las de "
                      "homología que lo citan (0) salen antes", texto)
        self.assertSinContenido(texto)
        # El aviso sin archivo de exclusiones conserva su 731, y entonces no
        # hay nada que conciliar.
        self.correr(excluir=[])
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertNotIn("citan el artículo excluido", texto)
        self.assertNotIn("cita el artículo excluido", texto)

    def test_el_informe_lleva_el_techo_sin_biobert(self):
        """Las cifras de test_el_techo_sin_biobert, junto al dirigido y a
        cualquier dirección de la cifra principal; en la terminal, una
        línea."""
        _, lineas = self.correr()
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("### El techo de la regla a), sin BioBERT", texto)
        self.assertIn("las mismas 11 filas de la cifra principal", texto)
        self.assertIn("| a) cualquier oración candidata | con expansión | "
                      "8/11 (72.7 %)", texto)
        self.assertIn("dirigido 6/11 (54.5 %)", texto)
        self.assertIn("cualquier dirección 7/11 (63.6 %)", texto)
        self.assertIn("no cubre: 0, como debe ser.", texto)
        self.assertSinContenido(texto)
        todo = "\n".join(lineas)
        self.assertIn("Techo sin BioBERT: la regla a con expansión cubre "
                      "72.7 %; la red encuentra 63.6 % en cualquier "
                      "dirección; fuera de la regla a: 0.", todo)
        self.assertSinContenido(todo)
        # Sin red, el techo sigue en el resultado y no en el informe.
        resultado, _ = self.correr(sin_red=True)
        self.assertEqual(11, resultado["techo_sin_biobert"]["n"])
        self.assertIsNone(resultado["techo_sin_biobert"]
                          ["red_cualquiera_fuera_de_a"])
        with io.open(self.informe, encoding="utf-8") as f:
            self.assertNotIn("El techo de la regla a)", f.read())

    def test_el_informe_lleva_la_linea_base_y_la_orientacion(self):
        """Las cifras de test_la_linea_base_y_la_orientacion_por_estrato, en
        las tablas de la red, en la línea de la abstención y en la terminal."""
        _, lineas = self.correr()
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("| cualquier dirección | orientación | acuerdo de "
                      "signo |", texto)
        self.assertIn("6/7 (85.7 %)", texto)
        self.assertIn("| sin BioBERT (la cifra principal) | 5 | 3 | 1 | 0 | "
                      "1 | 3/4 (75.0 %) [30.1, 95.4] | 3/4 (75.0 %) "
                      "[30.1, 95.4] |", texto)
        self.assertIn("la red acuerda en 3/5 (60.0 %)", texto)
        self.assertIn("acertaría en 4/5 (80.0 %)", texto)
        self.assertIn("Con 9 `+` y 2 `-` entre las exigibles", texto)
        self.assertSinContenido(texto)
        todo = "\n".join(lineas)
        self.assertIn("orientación 85.7 %; acuerdo cuando da signo 75.0 %, "
                      "siempre activa en esas filas 75.0 %; siempre activa en "
                      "las dirigidas con signo 80.0 %", todo)
        self.assertSinContenido(todo)

    def test_la_conciliacion_con_un_locus_invalido(self):
        """Una fila 16 con un regulador sin forma de locus: cuenta entre las
        filas con valores y no entre las de los dos locus, y el resto del
        denominador no cambia."""
        filas = dict(FILAS_BASE)
        filas[16] = ["qzoR", "wvoA", "+", P_XML, "PA12", "PA9043", HIST, "x"]
        self.base = construir_xlsx(os.path.join(self.tmp, "base_sintetica_16"
                                                ".xlsx"), [("Hoja1", filas)])
        resultado, _ = self.correr()
        self.assertEqual((15, 14, 1), (resultado["base"]["filas"],
                                       resultado["base"]["interacciones"],
                                       resultado["base"]["locus_invalido"]))
        self.assertEqual((14, 12), (resultado["denominador"]["base"],
                                    resultado["denominador"]["exigibles"]))
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("- 15 filas con valores, 14 con los dos locus: 1 con un "
                      "locus inválido.", texto)
        self.assertSinContenido(texto)

    def test_con_otra_red(self):
        """`red_prueba.tsv` da los mismos pares de locus que `red.tsv`: el
        mismo recall, también el de test, y el mismo techo. El informe y el
        registro dicen qué red se midió."""
        self.con_reglas()
        normal, _ = self.correr(solo=[self.solo])
        resultado, lineas = self.correr(solo=[self.solo], red="prueba")
        red = resultado["red"]
        self.assertEqual("red_prueba.tsv", red["archivo"])
        self.assertEqual((14, 1, 1), (red["conteos"]["aristas"],
                                      red["conteos"]["expandidas_omitidas"],
                                      red["conteos"]["solo_autorregulacion"]))
        self.assertEqual(normal["red"]["recall"], red["recall"])
        self.assertEqual(normal["red"]["recall_test"], red["recall_test"])
        self.assertEqual(normal["techo_sin_biobert"],
                         resultado["techo_sin_biobert"])
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("- Red: 14 aristas de `red_prueba.tsv`", texto)
        self.assertIn("- 14 aristas de `red_prueba.tsv`: 11 llevadas a locus",
                      texto)
        self.assertIn(", 1 sin locus de PAO1, 1 de autorregulación con un "
                      "solo locus y 1 expandida de un operón; en total, 11 "
                      "pares de locus dirigidos.", texto)
        self.assertIn("- La expandida se omite: no tiene evidencia propia",
                      texto)
        self.assertNotIn("`red.tsv`", texto)
        self.assertSinContenido(texto)
        self.assertSinContenido("\n".join(lineas))
        self.assertIn("Red: 14 aristas de red_prueba.tsv", "\n".join(lineas))
        with io.open(os.path.join(self.confidencial, C.ARCHIVO_REGISTRO),
                     encoding="utf-8") as f:
            registro = json.load(f)
        self.assertEqual("prueba", registro["parametros"]["red"])
        self.assertEqual(procedencia.huella(
            os.path.join(self.carpeta, "red_prueba.tsv")),
            registro["huellas"]["red"])

    def test_otra_red_de_otros_pares_se_detiene(self):
        """La procedencia se comprueba con el informe de esa red."""
        self.con_reglas()
        with io.open(os.path.join(self.carpeta, "red_prueba_informe.json"),
                     "w", encoding="utf-8") as f:
            json.dump({"huellas": {"pares": {"huella": "abcdefabcdefabcd"}}},
                      f)
        with self.assertRaises(ValueError) as ctx:
            self.correr(red="prueba")
        self.assertIn("otro pares.jsonl", str(ctx.exception))
        # La red por omisión sigue sellada con los pares de la carpeta.
        self.correr()

    def test_otra_red_sin_su_sello_lo_avisa_con_su_nombre(self):
        """El aviso va al informe publicado: tiene que nombrar el informe que
        falta, no `red_informe.json`, que sí está en la carpeta."""
        self.con_reglas()
        os.remove(os.path.join(self.carpeta, "red_prueba_informe.json"))
        resultado, _ = self.correr(red="prueba")
        avisos = [a for a in resultado["avisos"] if "huella" in a]
        self.assertEqual(1, len(avisos), resultado["avisos"])
        self.assertIn("red_prueba_informe.json", avisos[0])
        self.assertNotIn("red_informe.json", avisos[0])
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("red_prueba_informe.json", texto)
        self.assertSinContenido(texto)

    def test_un_nombre_de_red_con_forma_de_pmid_se_rechaza_antes(self):
        """`x_20990101` vale para `grn_red` (`consolidar --nombre`), pero el
        informe y la terminal nombran `red_x_20990101.tsv`, y ocho dígitos
        seguidos tienen forma de PMID: el filtro de publicación rechazaría el
        informe al final, con la base ya leída. Se dice antes de abrirla, y
        sin repetir el nombre."""
        escribir_red_con_reglas(self.carpeta, "x_20990101", ARISTAS)
        with mock.patch.object(V, "leer_base",
                               side_effect=AssertionError("abrió la base")):
            with self.assertRaises(ValueError) as ctx:
                self.correr(red="x_20990101")
        mensaje = str(ctx.exception)
        self.assertTrue(mensaje.startswith("--red: "), mensaje)
        self.assertNotIn("20990101", mensaje)
        self.assertSinContenido(mensaje)
        self.assertFalse(os.path.exists(self.confidencial))
        self.assertFalse(os.path.exists(self.informe))
        # Con letras pegadas no tiene forma de PMID, y corre.
        escribir_red_con_reglas(self.carpeta, "v20990101", ARISTAS)
        resultado, _ = self.correr(red="v20990101")
        self.assertEqual("red_v20990101.tsv", resultado["red"]["archivo"])

    def test_red_y_sin_red_se_excluyen(self):
        self.con_reglas()
        with mock.patch.object(V, "leer_base",
                               side_effect=AssertionError("abrió la base")):
            with self.assertRaises(ValueError) as ctx:
                self.correr(red="prueba", sin_red=True)
        mensaje = str(ctx.exception)
        self.assertIn("--red", mensaje)
        self.assertIn("--sin-red", mensaje)
        self.assertSinContenido(mensaje)
        self.assertFalse(os.path.exists(self.confidencial))
        self.assertFalse(os.path.exists(self.informe))

    def test_un_nombre_de_red_invalido_no_dice_cual(self):
        for nombre in (os.path.join(self.tmp, "secreta"), "evidencias",
                       "Prueba", "prueba\n", ""):
            with mock.patch.object(V, "leer_base",
                                   side_effect=AssertionError("abrió la "
                                                              "base")):
                with self.assertRaises(ValueError) as ctx:
                    self.correr(red=nombre)
            mensaje = str(ctx.exception)
            self.assertTrue(mensaje.startswith("--red: "), mensaje)
            self.assertNotIn("secreta", mensaje)
            self.assertNotIn("Prueba", mensaje)
            self.assertSinContenido(mensaje)
            self.assertFalse(os.path.exists(self.confidencial))

    def test_una_red_que_no_esta_dice_como_armarla(self):
        with self.assertRaises(ValueError) as ctx:
            self.correr(red="otra")
        mensaje = str(ctx.exception)
        self.assertIn("Falta red_otra.tsv", mensaje)
        self.assertIn("grn_red.cli consolidar", mensaje)
        self.assertSinContenido(mensaje)

    def test_el_informe_pasa_con_entradas_de_forma_real(self):
        """Los CSV llevan fecha en el nombre (el prefijo de `setUp`) y un
        conteo pasa de 10^7: ni el nombre ni el conteo salen como una corrida
        de siete u ocho dígitos que el filtro tome por PMID."""
        resultado, lineas = self.correr(solo=[self.solo])
        resultado["bronce"]["oraciones"] = 72969123
        resultado["red"]["conteos"]["aristas"] = 12345678
        resultado["denominador"]["exigibles"] = 1234567
        texto = C.informe_markdown(resultado)
        self.assertIn("72 969 123", texto)
        self.assertIn("12 345 678", texto)
        todo = os.linesep.join([texto] + C.resumen(resultado) + lineas)
        self.assertSinContenido(todo)
        for prohibido in ("20990101", "bronce_identificacion", ".csv",
                          "bytes"):
            self.assertNotIn(prohibido, todo)
        with io.open(self.informe, encoding="utf-8") as f:
            self.assertSinContenido(f.read())

    def test_una_carpeta_confidencial_dentro_del_repositorio_se_rechaza(self):
        dentro = os.path.join(E.RAIZ_REPO, "salidas",
                              "contraste_prueba_%d" % os.getpid())
        self.addCleanup(shutil.rmtree, dentro, True)
        with mock.patch.object(V, "leer_base",
                               side_effect=AssertionError("abrió la base")):
            with self.assertRaises(ValueError) as ctx:
                C.ejecutar(self.base, self.carpeta, dentro,
                           informe=self.informe, aceptar_base_distinta=True)
        mensaje = str(ctx.exception)
        self.assertIn("--confidencial", mensaje)
        self.assertNotIn(dentro, mensaje)
        self.assertNotIn(E.RAIZ_REPO, mensaje)
        self.assertFalse(os.path.exists(dentro))
        self.assertFalse(os.path.exists(self.informe))

    def test_sin_red(self):
        os.makedirs(self.confidencial)
        vieja = os.path.join(self.confidencial, C.ARCHIVO_NUEVAS)
        with io.open(vieja, "w", encoding="utf-8") as f:
            f.write("de una corrida anterior\n")
        os.remove(os.path.join(self.carpeta, "red.tsv"))
        resultado, lineas = self.correr(sin_red=True, solo=[self.solo])
        self.assertIsNone(resultado["red"])
        self.assertFalse(os.path.exists(vieja))
        self.assertTrue(any("--solo-pmids no tiene efecto" in a
                            for a in resultado["avisos"]))
        with io.open(self.informe, encoding="utf-8") as f:
            self.assertIn("No se contrastó", f.read())

    def test_sin_la_red_ni_sin_red_se_detiene(self):
        os.remove(os.path.join(self.carpeta, "red.tsv"))
        with self.assertRaises(ValueError) as ctx:
            self.correr()
        self.assertIn("--sin-red", str(ctx.exception))

    def test_la_corrida_1_se_compara_con_plan(self):
        escribir_candidatas(self.candidatas, ORACIONES, corrida=1)
        resultado, _ = self.correr()
        self.assertEqual(1, resultado["bronce"]["corrida"])
        with io.open(self.informe, encoding="utf-8") as f:
            texto = f.read()
        self.assertIn("Frente a PLAN.md 2.4, la misma corrida 1", texto)
        self.assertIn("239/791 (30.2 %)", texto)
        self.assertSinContenido(texto)

    def test_una_red_de_otros_pares_se_detiene(self):
        with io.open(os.path.join(self.carpeta, "red_informe.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"huellas": {"pares": {"huella": "abcdefabcdefabcd"}}},
                      f)
        with self.assertRaises(ValueError) as ctx:
            self.correr()
        self.assertIn("otro pares.jsonl", str(ctx.exception))
        self.assertFalse(os.path.exists(self.confidencial))

    def test_sin_sello_de_la_red_se_avisa(self):
        os.remove(os.path.join(self.carpeta, "red_informe.json"))
        resultado, _ = self.correr()
        self.assertTrue(any("red_informe.json" in a
                            for a in resultado["avisos"]))

    def test_sin_archivo_de_exclusiones_se_avisa(self):
        resultado, _ = self.correr(excluir=[])
        self.assertEqual(13, resultado["denominador"]["exigibles"])
        self.assertTrue(any("731" in a for a in resultado["avisos"]))

    def test_un_archivo_de_exclusiones_mal_escrito_no_dice_donde_esta(self):
        malo = os.path.join(self.tmp, "secreto_excluir.tsv")
        with io.open(malo, "w", encoding="utf-8") as f:
            f.write("pmid\tno-es-numero\n")
        with self.assertRaises(ValueError) as ctx:
            self.correr(excluir=[malo])
        self.assertIn("--excluir-pmids", str(ctx.exception))
        self.assertIn("línea 1", str(ctx.exception))
        self.assertNotIn("secreto", str(ctx.exception))

    def test_una_base_que_no_esta_no_dice_donde_la_buscaba(self):
        with self.assertRaises(ValueError) as ctx:
            C.ejecutar(os.path.join(self.tmp, "secreta.xlsx"), self.carpeta,
                       self.confidencial)
        self.assertIn("--base", str(ctx.exception))
        self.assertNotIn("secreta", str(ctx.exception))


class PruebasCli(_ConEscenario):

    def argv(self, *extra):
        return (["contraste", "--base", self.base, "--carpeta", self.carpeta,
                 "--excluir-pmids", self.excluir, "--informe", self.informe,
                 "--confidencial", self.confidencial] + list(extra))

    def main(self, argv):
        lineas = []
        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main(argv)
        return codigo, lineas

    def test_la_ayuda(self):
        for argv, buscados in ((["contraste", "--help"],
                                ("--base", "--carpeta", "--excluir-pmids",
                                 "--solo-pmids", "--sin-red", "--red",
                                 "--hoja", "--aceptar-base-distinta",
                                 "--informe", "--confidencial")),
                               (["--help"], ("contraste", "reentrenar"))):
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                with self.assertRaises(SystemExit) as ctx:
                    cli.main(argv)
            self.assertEqual(0, ctx.exception.code)
            for buscado in buscados:
                self.assertIn(buscado, salida.getvalue())

    def test_corre_y_no_imprime_rutas_ni_contenido(self):
        codigo, lineas = self.main(self.argv("--solo-pmids", self.solo,
                                             "--aceptar-base-distinta"))
        self.assertEqual(0, codigo, lineas)
        self.assertSinContenido("\n".join(lineas))
        self.assertTrue(os.path.isfile(self.informe))
        self.assertTrue(os.path.isfile(os.path.join(self.confidencial,
                                                    C.ARCHIVO_NUEVAS)))

    def test_otra_red(self):
        self.con_reglas()
        codigo, lineas = self.main(self.argv("--red", "prueba",
                                             "--aceptar-base-distinta"))
        self.assertEqual(0, codigo, lineas)
        self.assertSinContenido("\n".join(lineas))
        self.assertTrue(any("red_prueba.tsv" in l for l in lineas))
        with io.open(self.informe, encoding="utf-8") as f:
            self.assertIn("`red_prueba.tsv`", f.read())

    def test_red_con_sin_red_o_un_nombre_invalido_sale_sin_ruta(self):
        self.con_reglas()
        secreta = os.path.join(self.tmp, "secreta", "red_prueba.tsv")
        for extra in (("--red", "prueba", "--sin-red"), ("--red", secreta),
                      ("--red", "evidencias"), ("--red", "x_20990101")):
            codigo, lineas = self.main(self.argv(*(extra + (
                "--aceptar-base-distinta",))))
            self.assertEqual(1, codigo, extra)
            self.assertTrue(lineas[-1].startswith("ERROR: --red"), lineas)
            todo = "\n".join(lineas)
            self.assertSinContenido(todo)
            self.assertNotIn("secreta", todo)
            self.assertFalse(os.path.exists(self.informe))
            self.assertFalse(os.path.exists(self.confidencial))

    def test_un_cotejo_que_no_cuadra_sale_con_error_y_sin_rutas(self):
        codigo, lineas = self.main(self.argv())
        self.assertEqual(1, codigo)
        self.assertTrue(lineas[-1].startswith("ERROR: La base no coincide"))
        self.assertSinContenido("\n".join(lineas))
        self.assertFalse(os.path.exists(self.informe))

    def test_una_carpeta_confidencial_en_el_repositorio(self):
        dentro = os.path.join(E.RAIZ_REPO, "salidas",
                              "contraste_cli_%d" % os.getpid())
        self.addCleanup(shutil.rmtree, dentro, True)
        argv = self.argv("--aceptar-base-distinta")
        argv[argv.index("--confidencial") + 1] = dentro
        codigo, lineas = self.main(argv)
        self.assertEqual(1, codigo)
        self.assertNotIn(dentro, "\n".join(lineas))
        self.assertNotIn(E.RAIZ_REPO, "\n".join(lineas))
        self.assertFalse(os.path.exists(dentro))

    def test_sin_base(self):
        argv = self.argv()
        del argv[argv.index("--base"):argv.index("--base") + 2]
        with mock.patch.dict(os.environ):
            os.environ.pop("BASE_CURADA", None)
            codigo, lineas = self.main(argv)
        self.assertEqual(2, codigo)
        self.assertIn("falta --base", lineas[-1])

    def test_un_error_inesperado_sale_sin_la_ruta(self):
        ruta = os.path.join(self.tmp, "secreta", "base.xlsx")
        error = FileNotFoundError(2, "No such file or directory", ruta)
        with mock.patch.object(C, "ejecutar", side_effect=error):
            codigo, lineas = self.main(self.argv())
        self.assertEqual(1, codigo)
        self.assertEqual(["ERROR: FileNotFoundError: No such file or "
                          "directory"], lineas)

    def test_mensaje_publicable(self):
        ruta = os.path.join(self.tmp, "secreta", "base.xlsx")
        mensaje = C.mensaje_publicable(ValueError("No pude con %s." % ruta),
                                       (ruta,))
        self.assertEqual("No pude con <ruta>.", mensaje)
        # Algo con forma de contenido de la base deja solo el tipo.
        self.assertEqual("ValueError", C.mensaje_publicable(
            ValueError("el locus PA9001 no cuadra")))
        self.assertEqual("KeyError: 'pmid'",
                         C.mensaje_publicable(KeyError("pmid")))


if __name__ == "__main__":
    unittest.main()
