# -*- coding: utf-8 -*-
"""Pruebas de las dos evaluaciones, la del oro y la del signo.

Las tres que no pueden faltar, porque cubren los tres errores que harían que
los números salieran bien y no midieran nada:

1. **El emparejamiento por alias.** El mismo gen aparece con varios nombres
   (`MexR = NalB = PA0424`). Si el evaluador solo compara el nombre de la
   columna, cuenta como "no recuperada" una arista que sí está, y la
   exhaustividad sale baja por un problema de nomenclatura.
2. **Los dos denominadores.** El crudo son 190; el honesto quita lo que el
   corpus no puede sostener. Las categorías se solapan, así que restar 9 + 6 + 5
   a mano da un número equivocado. La prueba fija la aritmética.
3. **El desglose de las 24 escritas desde el fenotipo del mutante.** Un modelo
   que acierte las 69 directas y falle las 24 saca 74 % global. Ese 74 % oculta
   que el fallo está entero en un solo tipo de redacción, que es justo el que
   tiene arreglo distinto.
4. **La línea base aleatoria.** Con predicciones al azar `evaluar_oro.py`
   publicaba 95.5 % de exhaustividad. Las pruebas de `PruebasLineaBase` fijan
   que la línea base se publique siempre, que sea determinista con la semilla y
   que el código de salida cambie cuando el acierto de signo no despega.
5. **La procedencia del diccionario.** `PruebasCircularidad` reproduce el
   exploit medido: un `genes_pao1.tsv` copiado del oro y rellenado hasta 5700
   líneas. Antes pasaba y publicaba 81.7 % de exhaustividad.

    python -m unittest discover etapa2
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import evaluar_oro as O
import evaluar_signo as S

AQUI = os.path.dirname(os.path.abspath(__file__))
ORO_REAL = os.path.join(AQUI, "oro_pseudomonas.tsv")
AUDITORIA_REAL = os.path.join(AQUI, "auditoria_signo.tsv")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def escribir_tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(str(fila.get(c, "")) for c in columnas) + "\n")


def escribir_jsonl(ruta, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        for fila in filas:
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def fila_oro(tf, blanco, signo="activates", certeza="establecida",
             subsistema="Bombas RND", alias="", atestiguado="true"):
    return {"tf": tf, "blanco": blanco, "signo": signo,
            "certeza_dominio": certeza, "subsistema": subsistema,
            "alias": alias, "atestiguado": atestiguado, "n_articulos": "1",
            "pmids": "1", "oracion": "Oracion de evidencia."}


def escribir_oro(ruta, filas):
    """Completa hasta las 190 filas que exige el invariante de §6.

    El relleno va con atestiguado=false a propósito: así queda fuera del
    denominador honesto y las cuentas de la prueba se leen sobre las filas que
    la prueba puso.
    """
    relleno = [fila_oro("Zzr%03d" % i, "zzt%03d" % i, atestiguado="false")
               for i in range(O.FILAS_ORO - len(filas))]
    escribir_tsv(ruta, O.COLUMNAS_ORO, list(filas) + relleno)


def fila_red(tf, blanco, signo, n_evidencias=3, conflicto="false"):
    return {"tf": tf, "blanco": blanco, "signo": signo, "conflicto": conflicto,
            "n_evidencias": str(n_evidencias),
            "n_activates": str(n_evidencias if signo == "activates" else 0),
            "n_represses": str(n_evidencias if signo == "represses" else 0),
            "n_regulates": str(n_evidencias if signo == "regulates" else 0),
            "n_articulos": "2", "confianza": "0.8000",
            "autorregulacion": "false", "secciones": "results",
            "pmids": "1|2", "oracion_representativa": "Evidencia."}


GENES = [
    ("PA2492", "mexT"), ("PA2493", "mexE"), ("PA2494", "mexF"),
    ("PA2495", "oprN"), ("PA0424", "mexR"), ("PA0425", "mexA"),
    ("PA0426", "mexB"), ("PA0427", "oprM"), ("PA3477", "rhlR"),
    ("PA3622", "rpoS"), ("PA1430", "lasR"), ("PA3724", "lasB"),
    ("PA5261", "algR"), ("PA3702", "wspR"), ("PA3064", "pelA"),
    ("PA0762", "algU"), ("PA4599", "mexC"), ("PA4598", "mexD"),
    ("PA4597", "oprJ"), ("PA3540", "algD"), ("PA2426", "pvdS"),
    ("PA2386", "pvdA"), ("PA3721", "nalC"), ("PA3719", "armR"),
]


# Los operones que la tabla derivada del diccionario traería para estos genes.
# Se escriben solo donde la prueba los necesita: la equivalencia operón-gen del
# lado del PIPELINE solo vale por tabla, y comprobar que sin tabla no empareja
# es la mitad del arreglo.
OPERONES = [
    {"operon": "mexEF-oprN", "miembros": "mexE|mexF|oprN",
     "locus_tags": "PA2493|PA2494|PA2495", "fuente": "refseq_adyacencia"},
    {"operon": "mexAB-oprM", "miembros": "mexA|mexB|oprM",
     "locus_tags": "PA0425|PA0426|PA0427", "fuente": "refseq_adyacencia"},
]


def meta_de_juguete(ruta, id2label=None):
    """El predicciones_meta.json que evaluar_signo.py exige antes de medir."""
    if id2label is None:
        id2label = dict((str(i), e) for i, e in enumerate(S.ETIQUETAS))
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"modelo": "checkpoint_de_juguete", "id2label": id2label,
                   "do_lower_case": False}, f, ensure_ascii=False)


# Genes que el patrón de oro no nombra. Un diccionario de PAO1 tiene 5642 y el
# oro nombra 110 blancos: el caso normal es que la mayor parte de lo que el
# pipeline reconoce en la prosa caiga fuera del oro. Las fixtures anteriores
# no tenían ni uno, así que describían justo el diccionario que el guardián de
# sustancia existe para rechazar --uno que solo sabe lo que el oro le dijo-- y
# con ellas ese guardián no se podía probar.
# Son 60 contra los 20 pares del oro del escenario más grande: la proporción
# medida sobre el corpus real es 2528 de 9876 pares dentro del vocabulario del
# oro, o sea 25.6 %, y con 60 de fondo el escenario cae en ese mismo orden.
FONDO = [("PA9%03d" % i, "bkg%03d" % i) for i in range(60)]
PARES_DE_FONDO = [("Bkg%03d" % i, "bkg%03d" % i) for i in range(60)]


def escribir_genes(ruta, extra=()):
    filas = []
    for locus, simbolo in list(GENES) + list(FONDO) + list(extra):
        filas.append({"locus_tag": locus, "simbolo": simbolo, "alias": "",
                      "tipo": "protein_coding", "producto": "proteina",
                      "es_tf": "false", "fuente_tf": "", "fuente": "refseq",
                      "sensible_mayusculas": "false"})
    escribir_tsv(ruta, O.COLUMNAS_GENES, filas)


def escribir_pares(ruta, pares, n_fondo=60):
    """Los pares que pide la prueba, más un fondo que el oro no nombra.

    El fondo no toca ninguna métrica --todas se calculan sobre las filas del
    oro-- pero sí la medida de sustancia de `evaluar_oro.medir_sustancia()`,
    que pregunta qué fracción de los pares propuestos cae entera dentro del
    vocabulario del oro. Sin fondo, cualquier escenario de prueba da 100 % y
    es indistinguible del diccionario copiado del patrón.
    """
    todos = list(pares) + list(PARES_DE_FONDO[:n_fondo])
    escribir_jsonl(ruta, [{"text": "x", "label": "", "pmid": 1, "tf": tf,
                           "target": target} for tf, target in todos])


class Escenario(object):
    """Un directorio con las cinco entradas de evaluar_oro.py."""

    def __init__(self, filas_oro, aristas, pares, collectf=None,
                 operones=None, n_fondo=60):
        self.dir = tempfile.mkdtemp()
        self.oro = os.path.join(self.dir, "oro.tsv")
        self.red = os.path.join(self.dir, "red.tsv")
        self.pares = os.path.join(self.dir, "pares.jsonl")
        self.genes = os.path.join(self.dir, "genes.tsv")
        self.operones = os.path.join(self.dir, "operones.tsv")
        self.salida = os.path.join(self.dir, "evaluacion.tsv")
        self.resumen = os.path.join(self.dir, "evaluacion.json")
        self.collectf = os.path.join(self.dir, "collectf.tsv")
        self.predicciones = os.path.join(self.dir, "predicciones.jsonl")
        escribir_oro(self.oro, filas_oro)
        escribir_tsv(self.red, O.COLUMNAS_RED, aristas)
        escribir_pares(self.pares, pares, n_fondo)
        escribir_genes(self.genes)
        if collectf is not None:
            escribir_tsv(self.collectf, O.COLUMNAS_COLLECTF, collectf)
        if operones is not None:
            escribir_tsv(self.operones, O.COLUMNAS_OPERONES, operones)

    def correr(self, extra=()):
        """Corre y admite el código 2 además del 0.

        El 2 quiere decir "el acierto de signo no se distingue del azar", y en
        un escenario de juguete de tres filas comparables eso pasa casi
        siempre: con tan pocas filas no se puede distinguir nada. Lo que sí
        exige esta prueba es que en los dos casos los archivos estén escritos,
        que es la razón por la que el código 2 existe en vez de un sys.exit.
        """
        argv = ["--oro", self.oro, "--red", self.red, "--pares", self.pares,
                "--genes", self.genes, "--operones", self.operones,
                "--salida", self.salida, "--resumen", self.resumen,
                "--predicciones", self.predicciones]
        argv += list(extra)
        with contextlib.redirect_stdout(io.StringIO()) as salida:
            self.codigo = O.main(argv)
        self.impreso = salida.getvalue()
        assert self.codigo in (0, 2), self.codigo
        with io.open(self.resumen, encoding="utf-8") as f:
            self.json = json.load(f)
        self.filas = O.leer_tsv(self.salida, O.COLUMNAS_SALIDA, "salida")
        return self

    def fila(self, tf, blanco):
        for f in self.filas:
            if f["tf"] == tf and f["blanco"] == blanco:
                return f
        raise AssertionError("no está la fila %s->%s" % (tf, blanco))

    def limpiar(self):
        shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Emparejamiento por nombre
# ---------------------------------------------------------------------------

class PruebasAlias(unittest.TestCase):
    """La columna `alias` del oro es prosa, no una lista. Hay que leerla bien."""

    def test_cadena_anclada_a_cada_extremo(self):
        campo = ("MexR = NalB = PA0424, familia MarR; "
                 "mexAB-oprM = PA0425-PA0427")
        tf, bl, amb = O.alias_anclados(campo, "MexR", "mexAB-oprM")
        self.assertEqual(tf, set(["nalb", "pa0424"]))
        self.assertEqual(bl, set(["pa0425", "pa0426", "pa0427"]))
        self.assertEqual(amb, 0)

    def test_el_rango_se_expande_y_no_se_guarda_crudo(self):
        _, bl, _ = O.alias_anclados("mexXY = amrAB = PA2019-PA2018",
                                    "MexZ", "mexXY")
        # Ninguna arista se llama "PA2019-PA2018"; guardarlo sería basura.
        self.assertNotIn("pa2019-pa2018", bl)
        self.assertEqual(bl, set(["amrab", "pa2018", "pa2019"]))

    def test_cadena_que_toca_los_dos_extremos_se_descarta(self):
        # "adcA = PA4843 = AmrZ dependent cyclase A": el AmrZ final es prosa.
        # Anclarla al TF convertiría al blanco en alias del propio TF.
        tf, bl, amb = O.alias_anclados(
            "adcA = PA4843 = AmrZ dependent cyclase A", "AmrZ", "adcA")
        self.assertEqual(tf, set())
        self.assertEqual(bl, set())
        self.assertEqual(amb, 1)

    def test_la_prosa_no_se_toma_por_alias(self):
        tf, _, _ = O.alias_anclados("AlgP = proteina tipo histona / nucleoide",
                                    "AlgP", "algD")
        self.assertEqual(tf, set())

    def test_lista_por_comas_anclada(self):
        tf, _, _ = O.alias_anclados("PhoB, phoB, PA5360", "PhoB", "pstS")
        self.assertEqual(tf, set(["pa5360"]))

    def test_lista_no_anclada_se_ignora(self):
        # "rhlA, rhlB, rhlABC" no nombra a rhlAB: sin ancla no hay alias.
        tf, bl, _ = O.alias_anclados("rhlA, rhlB, rhlABC; ramnolipidos",
                                     "AlgR", "rhlAB")
        self.assertEqual(tf, set())
        self.assertEqual(bl, set())

    def test_sobre_el_oro_real_ninguna_cadena_revienta(self):
        oro = O.cargar_oro(ORO_REAL)
        con_alias = 0
        for fila in oro:
            tf, bl, _ = O.alias_anclados(fila["alias"], fila["tf"],
                                         fila["blanco"])
            con_alias += 1 if (tf or bl) else 0
            self.assertNotIn(O.clave(fila["tf"]), bl)
            self.assertNotIn(O.clave(fila["blanco"]), tf)
        self.assertGreater(con_alias, 50)


class PruebasOperon(unittest.TestCase):
    """Equivalencia operón-gen: normalización de evaluación, no de construcción."""

    def test_compuesto_con_guion(self):
        self.assertEqual(O.miembros_operon("mexAB-oprM"),
                         ["mexA", "mexB", "oprM"])

    def test_concatenado(self):
        self.assertEqual(O.miembros_operon("pqsABCDE"),
                         ["pqsA", "pqsB", "pqsC", "pqsD", "pqsE"])

    def test_rango_alfabetico(self):
        self.assertEqual(O.miembros_operon("phzA-G"),
                         ["phzA", "phzB", "phzC", "phzD", "phzE", "phzF",
                          "phzG"])

    def test_grupos_con_digito(self):
        self.assertEqual(O.miembros_operon("narK1K2GHJI"),
                         ["narK1", "narK2", "narG", "narH", "narJ", "narI"])

    def test_un_gen_no_es_operon(self):
        self.assertEqual(O.miembros_operon("algD"), [])
        self.assertEqual(O.miembros_operon("pel"), [])

    def test_locus_tag_no_se_parte(self):
        # PA0762 no es "PA" + grupos: partirlo destruiría el vocabulario.
        self.assertEqual(O.miembros_operon("PA0762"), [])


# ---------------------------------------------------------------------------
# Los dos denominadores y los veredictos
# ---------------------------------------------------------------------------

FILAS = [
    # recuperada por nombre exacto, signo correcto
    fila_oro("MexT", "mexEF-oprN", "activates",
             alias="MexT = PA2492; mexEF-oprN = PA2493-PA2495"),
    # recuperada por alias en los dos extremos (NalB -> PA0425)
    fila_oro("MexR", "mexAB-oprM", "represses",
             alias="MexR = NalB = PA0424, familia MarR; "
                   "mexAB-oprM = PA0425-PA0427"),
    # excluida: no atestiguada Y de signo no resuelto (el solape)
    fila_oro("MexT", "mexT", "regulates", atestiguado="false",
             alias="autorregulacion tipica de LysR"),
    # excluida: no atestiguada
    fila_oro("AlgR", "algR", "activates", atestiguado="false"),
    # excluida: signo no resuelto
    fila_oro("WspR", "pel", "regulates"),
    # excluida: signo no resuelto Y en disputa (el otro solape)
    fila_oro("RhlR", "rpoS", "regulates",
             alias="relacion en disputa: el corpus la afirma y la niega"),
    # excluida: en disputa
    fila_oro("LasR", "lasB", "activates",
             alias="relacion en disputa entre articulos"),
    # dentro del honesto, pero fuera del diccionario (exoU no está en PAO1)
    fila_oro("ExsA", "exoU", "activates", certeza="probable",
             subsistema="Dos componentes T3SS"),
    # recuperada por operón, con el signo al revés
    fila_oro("AlgU", "mexCD-oprJ", "activates"),
    # había candidato y la red no la sacó
    fila_oro("LasR", "rhlR", "activates", subsistema="Quorum sensing"),
    # nunca hubo candidato
    fila_oro("RpoS", "algD", "activates", certeza="probable",
             subsistema="Factores sigma"),
    # recuperada sin signo: la red dijo regulates
    fila_oro("PvdS", "pvdA", "activates", subsistema="Hierro sideroforos"),
]

ARISTAS = [
    fila_red("MexT", "mexEF-oprN", "activates", 9),
    fila_red("NalB", "PA0425", "represses", 4),
    fila_red("AlgU", "mexC", "represses", 2),
    fila_red("PvdS", "pvdA", "regulates", 5),
]

PARES = [("MexT", "mexEF-oprN"), ("MexR", "mexA"), ("AlgU", "mexC"),
         ("LasR", "rhlR"), ("PvdS", "pvdA")]


class PruebasDenominadores(unittest.TestCase):

    def setUp(self):
        self.esc = Escenario(FILAS, ARISTAS, PARES).correr()

    def tearDown(self):
        self.esc.limpiar()

    def test_el_crudo_son_las_190(self):
        self.assertEqual(self.esc.json["denominadores"]["crudo"], 190)
        self.assertEqual(len(self.esc.filas), 190)

    def test_el_honesto_quita_las_tres_categorias(self):
        d = self.esc.json["denominadores"]
        # 12 filas puestas + 178 de relleno no atestiguado.
        self.assertEqual(d["exclusiones"]["no_atestiguada"], 2 + 178)
        self.assertEqual(d["exclusiones"]["signo_no_resuelto"], 2)
        self.assertEqual(d["exclusiones"]["en_disputa"], 1)
        self.assertEqual(d["exclusiones"]["total"], 183)
        self.assertEqual(d["honesto"], 190 - 183)
        self.assertEqual(d["honesto"], self.esc.json["honesto"]["filas"])

    def test_las_categorias_se_solapan_y_se_cuentan_una_vez(self):
        """La resta 9 + 6 + 5 de la documentación supone que no se solapan.

        MexT -> mexT es no atestiguada Y de signo no resuelto; RhlR -> rpoS es
        de signo no resuelto Y en disputa. Contarlas dos veces daría un
        denominador más chico que el real, o sea una exhaustividad inflada.
        """
        self.assertEqual(self.esc.fila("MexT", "mexT")["motivo_exclusion"],
                         "no_atestiguada")
        self.assertEqual(self.esc.fila("RhlR", "rpoS")["motivo_exclusion"],
                         "signo_no_resuelto")
        self.assertEqual(self.esc.fila("LasR", "lasB")["motivo_exclusion"],
                         "en_disputa")
        honestas = [f for f in self.esc.filas
                    if f["en_denominador_honesto"] == "true"]
        self.assertEqual(len(honestas), self.esc.json["denominadores"]["honesto"])

    def test_las_categorias_se_publican_tambien_con_solape(self):
        """Sin el conteo crudo, un "0 en disputa" parece decir que la marca no
        se encontró, cuando lo que pasa es que esa fila ya salía por otra vía.
        """
        d = self.esc.json["denominadores"]
        con_solape = d["categorias_con_solape"]
        self.assertEqual(con_solape["no_atestiguada"], 2 + 178)
        self.assertEqual(con_solape["signo_no_resuelto"], 3)
        self.assertEqual(con_solape["en_disputa"], 2)
        # Con solape suman más que el total de filas excluidas.
        self.assertGreater(sum(con_solape.values()), d["exclusiones"]["total"])

    def test_los_dos_numeros_van_etiquetados_en_la_terminal(self):
        self.assertIn("crudo", self.esc.impreso)
        self.assertIn("honesto", self.esc.impreso)
        self.assertIn("190 filas", self.esc.impreso)

    def test_el_tsv_permite_reconstruir_el_denominador(self):
        marcadas = sum(1 for f in self.esc.filas
                       if f["en_denominador_honesto"] == "true")
        self.assertEqual(marcadas, 7)

    def test_incluir_no_atestiguadas_las_devuelve_al_universo(self):
        esc = Escenario(FILAS, ARISTAS, PARES).correr(
            ["--incluir-no-atestiguadas"])
        try:
            # Vuelven las no atestiguadas; las de signo sin resolver y las
            # disputadas siguen fuera porque no son medibles.
            self.assertEqual(esc.json["denominadores"]["honesto"], 190 - 3)
        finally:
            esc.limpiar()

    def test_el_honesto_documentado_viaja_pero_no_manda(self):
        d = self.esc.json["denominadores"]
        self.assertEqual(d["honesto_documentado"], 169)
        self.assertNotEqual(d["honesto"], d["honesto_documentado"])
        self.assertTrue(any("no es el documentado" in a
                            for a in self.esc.json["avisos"]))


class PruebasVeredictos(unittest.TestCase):

    def setUp(self):
        self.esc = Escenario(FILAS, ARISTAS, PARES).correr()

    def tearDown(self):
        self.esc.limpiar()

    def test_coincidencia_exacta(self):
        f = self.esc.fila("MexT", "mexEF-oprN")
        self.assertEqual(f["coincidencia"], "exacta")
        self.assertEqual(f["veredicto"], "recuperada_signo_ok")

    def test_coincidencia_por_alias(self):
        # La arista de la red se llama NalB -> PA0425; el oro, MexR -> mexAB-oprM.
        f = self.esc.fila("MexR", "mexAB-oprM")
        self.assertEqual(f["coincidencia"], "por_alias")
        self.assertEqual(f["signo_red"], "represses")
        self.assertEqual(f["veredicto"], "recuperada_signo_ok")

    def test_coincidencia_por_operon(self):
        f = self.esc.fila("AlgU", "mexCD-oprJ")
        self.assertEqual(f["coincidencia"], "por_operon")
        self.assertEqual(f["veredicto"], "recuperada_signo_mal")

    def test_sin_signo_comparable(self):
        f = self.esc.fila("PvdS", "pvdA")
        self.assertEqual(f["veredicto"], "recuperada_sin_signo")

    def test_habia_candidato_y_no_hay_arista(self):
        f = self.esc.fila("LasR", "rhlR")
        self.assertEqual(f["hubo_candidato"], "true")
        self.assertEqual(f["veredicto"], "no_recuperada_filtrada")

    def test_nunca_hubo_candidato(self):
        f = self.esc.fila("RpoS", "algD")
        self.assertEqual(f["hubo_candidato"], "false")
        self.assertEqual(f["veredicto"], "no_recuperada_sin_candidato")

    def test_fuera_de_diccionario(self):
        f = self.esc.fila("ExsA", "exoU")
        self.assertEqual(f["veredicto"], "fuera_de_diccionario")
        self.assertIn("ExsA->exoU", self.esc.json["fuera_de_diccionario"])

    def test_las_cuatro_coberturas_van_separadas(self):
        """§6.2: reportar solo exhaustividad escondería de dónde sale."""
        h = self.esc.json["honesto"]
        self.assertEqual((h["cobertura_diccionario"]["n"],
                          h["cobertura_diccionario"]["d"]), (6, 7))
        self.assertEqual((h["cobertura_candidatos"]["n"],
                          h["cobertura_candidatos"]["d"]), (5, 6))
        self.assertEqual((h["exhaustividad"]["n"],
                          h["exhaustividad"]["d"]), (4, 5))
        self.assertEqual((h["acierto_signo"]["n"],
                          h["acierto_signo"]["d"]), (2, 3))

    def test_la_equivalencia_operon_se_reporta(self):
        b = self.esc.json["equivalencia_operon"]
        # mexEF-oprN, mexAB-oprM y mexCD-oprJ se expanden mecánicamente.
        self.assertGreaterEqual(b["blancos_con_expansion_mecanica"], 3)
        self.assertEqual(b["blancos_en_la_tabla_de_operones"], 0)
        # Solo AlgU -> mexCD-oprJ necesita bajar a los miembros: los otros dos
        # operones traen su locus tag en la columna alias y resuelven por ahí.
        self.assertEqual(b["filas_resueltas_por_operon"], 1)
        self.assertIn("circular", b["aviso"])

    def test_desglose_por_subsistema_y_certeza(self):
        self.assertIn("Bombas RND", self.esc.json["por_subsistema"])
        self.assertIn("Quorum sensing", self.esc.json["por_subsistema"])
        self.assertEqual(sorted(self.esc.json["por_certeza"]),
                         ["establecida", "probable"])


class PruebasNoHayPrecision(unittest.TestCase):
    """§6.1: el oro no da precisión, y el script no deja fingir que sí."""

    def setUp(self):
        self.esc = Escenario(FILAS, ARISTAS, PARES)

    def tearDown(self):
        self.esc.limpiar()

    def test_la_bandera_se_rechaza_con_la_explicacion(self):
        with contextlib.redirect_stdout(io.StringIO()) as salida:
            with self.assertRaises(SystemExit):
                O.main(["--oro", self.esc.oro, "--red", self.esc.red,
                        "--pares", self.esc.pares, "--genes", self.esc.genes,
                        "--precision"])
        self.assertIn("NO da precisión", salida.getvalue())

    def test_ningun_campo_del_resumen_se_llama_precision(self):
        esc = self.esc.correr()
        crudo = json.dumps(esc.json, ensure_ascii=False)
        for palabra in ('"precision"', '"f1"', '"vp"', '"fp"',
                        '"falsos_positivos"'):
            self.assertNotIn(palabra, crudo)
        self.assertIn("NO da precisión", esc.json["aviso"])

    def test_el_aviso_encabeza_el_tsv(self):
        esc = self.esc.correr()
        with io.open(esc.salida, encoding="utf-8") as fh:
            lineas = fh.read().split("\n")
        comentario = " ".join(ln for ln in lineas if ln.startswith("#"))
        self.assertTrue(lineas[0].startswith("# "))
        self.assertIn("NO da precisión", comentario)
        self.assertIn("denominador crudo", comentario)
        # Y la primera línea que no es comentario sigue siendo el encabezado.
        datos = [ln for ln in lineas if ln and not ln.startswith("#")]
        self.assertEqual(datos[0].split("\t"), O.COLUMNAS_SALIDA)


class PruebasCollecTF(unittest.TestCase):
    """Los TFs que el oro no menciona son la prueba de que no hay circularidad."""

    def test_se_parte_en_los_que_el_oro_cubre_y_los_que_no(self):
        collectf = [
            {"tf": "MexT", "blanco": "PA2493", "experimento": "ChIP-Seq",
             "pmids": "1", "en_corpus": "true"},
            {"tf": "LexA", "blanco": "PA3617", "experimento": "EMSA",
             "pmids": "2", "en_corpus": "true"},
        ]
        # Con la tabla: es el único camino por el que se expande un nombre
        # que produjo el pipeline (mexEF-oprN -> mexE, y CollecTF nombra
        # PA2493, que es mexE). Sin ella no empareja, y eso lo fija la prueba
        # de al lado.
        esc = Escenario(FILAS, ARISTAS, PARES, collectf=collectf,
                        operones=OPERONES)
        try:
            esc.correr(["--collectf", esc.collectf])
            bloque = esc.json["collectf"]
            self.assertEqual(bloque["en_el_oro"]["pares"], 1)
            self.assertEqual(bloque["fuera_del_oro"]["pares"], 1)
            # MexT -> PA2493 es mexE, miembro de mexEF-oprN: la red lo tiene.
            self.assertEqual(bloque["en_el_oro"]["exhaustividad"]["n"], 1)
            self.assertEqual(bloque["fuera_del_oro"]["exhaustividad"]["n"], 0)
            self.assertIn("NO trae signo", bloque["aviso"])
        finally:
            esc.limpiar()


class PruebasGuardianesOro(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_un_oro_de_otra_forma_se_rechaza(self):
        ruta = os.path.join(self.dir, "oro.tsv")
        escribir_tsv(ruta, O.COLUMNAS_ORO, [fila_oro("A", "b")])
        with self.assertRaises(SystemExit) as cm:
            O.cargar_oro(ruta)
        self.assertIn("no tiene la forma esperada", str(cm.exception))

    def test_falta_pares(self):
        with self.assertRaises(SystemExit) as cm:
            O.cargar_pares(os.path.join(self.dir, "no_existe.jsonl"), {})
        self.assertIn("extraer_pares.py", str(cm.exception))

    def test_diccionario_hecho_desde_el_oro(self):
        """Invariante de §6: cobertura del 100 % con un diccionario diminuto."""
        filas = [fila_oro("MexT", "mexT")] * 1
        esc = Escenario(filas, [], [])
        try:
            # Un diccionario que solo tiene lo que el oro nombra.
            escribir_tsv(esc.genes, O.COLUMNAS_GENES, [
                {"locus_tag": "PA2492", "simbolo": "mexT", "alias": "",
                 "tipo": "protein_coding", "producto": "x", "es_tf": "true",
                 "fuente_tf": "manual", "fuente": "refseq",
                 "sensible_mayusculas": "false"}])
            # Todas las filas de relleno resolverían a nada, así que para que
            # la cobertura dé 1.0 el oro tiene que ser solo lo que el
            # diccionario cubre: se rellena con la misma fila.
            escribir_tsv(esc.oro, O.COLUMNAS_ORO,
                         [fila_oro("MexT", "mexT")] * O.FILAS_ORO)
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    O.main(["--oro", esc.oro, "--red", esc.red, "--pares",
                            esc.pares, "--genes", esc.genes, "--operones",
                            esc.operones, "--salida", esc.salida, "--resumen",
                            esc.resumen])
            self.assertIn("hecho desde el oro", str(cm.exception))
        finally:
            esc.limpiar()


class PruebasOroReal(unittest.TestCase):
    """Los números que la documentación cita, medidos sobre la tabla."""

    def test_la_forma(self):
        oro = O.cargar_oro(ORO_REAL)
        self.assertEqual(len(oro), 190)

    def test_las_tres_categorias_del_denominador_honesto(self):
        oro = O.cargar_oro(ORO_REAL)
        no_atestiguadas = [f for f in oro if f["atestiguado"] != "true"]
        sin_signo = [f for f in oro if f["signo"] == "regulates"]
        disputadas, origen = O.cargar_disputadas(None, oro)
        self.assertEqual(len(no_atestiguadas), 9)
        self.assertEqual(len(sin_signo), 6)
        self.assertIn("alias", origen)
        # La documentación habla de 5 en disputa y la tabla solo marca una.
        # Mientras las otras cuatro no estén en ningún dato, no se restan.
        self.assertEqual(len(disputadas), 1)

    def test_el_solape_es_real(self):
        oro = O.cargar_oro(ORO_REAL)
        excluidas = set()
        for f in oro:
            if (f["atestiguado"] != "true" or f["signo"] == "regulates"
                    or "disputa" in f["alias"].lower()):
                excluidas.add((f["tf"], f["blanco"]))
        # 9 + 6 + 1 = 16 si no se solaparan; se solapan en dos filas.
        self.assertEqual(len(excluidas), 14)
        self.assertIn(("MexT", "mexT"), excluidas)
        self.assertIn(("RhlR", "rpoS"), excluidas)


# ---------------------------------------------------------------------------
# Acierto de signo: las 93, y las 24 de la trampa aparte
# ---------------------------------------------------------------------------

PARES_AUDITORIA = [("MexZ", "mexXY"), ("MexR", "mexAB-oprM"),
                   ("NfxB", "mexCD-oprJ"), ("NalD", "mexAB-oprM"),
                   ("MexL", "mexJK"), ("NalC", "armR")]


def fila_auditoria(pmid, tf, blanco, oracion, evaluable, redaccion):
    return {"pmid": str(pmid), "fuente": "fulltext", "tf": tf,
            "blanco": blanco,
            "signo_correcto": "represses" if evaluable else "",
            "evaluable": "true" if evaluable else "false",
            "redaccion": redaccion, "mencion_tf": tf, "mencion_blanco": blanco,
            "oracion": oracion}


def corpus_auditoria(n_directas=69, n_fenotipo=24, n_no_evaluables=105):
    """198 filas con el mismo reparto que la tabla real.

    Las oraciones pasan de 120 caracteres a propósito: la unión por prefijo del
    contrato compara los primeros 120 de cada lado, así que con oraciones más
    cortas esa rama nunca se ejercitaría.
    """
    cola = ("Este detalle se anade para que la oracion pase de ciento veinte "
            "caracteres y la union por prefijo tenga sobre que trabajar.")
    filas, pmid = [], 30000
    for i in range(n_directas):
        tf, blanco = PARES_AUDITORIA[i % len(PARES_AUDITORIA)]
        filas.append(fila_auditoria(
            pmid + i, tf, blanco,
            "The expression of %s was repressed by the regulator %s in strain "
            "PAO1, caso directo numero %d. %s" % (blanco, tf, i, cola),
            True, "directa"))
    pmid += 1000
    for i in range(n_fenotipo):
        tf, blanco = PARES_AUDITORIA[i % len(PARES_AUDITORIA)]
        filas.append(fila_auditoria(
            pmid + i, tf, blanco,
            "Mutations in %s lead to overexpression of %s in clinical "
            "isolates, caso de fenotipo numero %d. %s" % (tf, blanco, i, cola),
            True, "fenotipo_mutante"))
    pmid += 1000
    for i in range(n_no_evaluables):
        tf, blanco = PARES_AUDITORIA[i % len(PARES_AUDITORIA)]
        filas.append(fila_auditoria(
            pmid + i, tf, blanco,
            "Both %s and %s were measured in this survey, co-mencion numero "
            "%d. %s" % (tf, blanco, i, cola),
            False, "otra"))
    return filas


class EscenarioSigno(object):

    def __init__(self, auditoria, respuestas, probabilidad=0.95,
                 id2label=None, operones=None, mapa_blancos=None,
                 blancos_por_llave=None):
        """respuestas: (pmid, tf, blanco) -> (prediccion, oracion o None).

        `mapa_blancos` renombra el blanco del lado del PIPELINE: es como se
        reproduce el caso real, donde la auditoría escribe `mexAB-oprM` y
        extraer_pares.py emitió `mexA` porque la oración nombra el gen suelto.
        """
        self.mapa_blancos = mapa_blancos or {}
        # Por llave completa, para poder romper cinco filas y no las quince de
        # un blanco entero: el guardián de 80/93 es de verdad y abortaría.
        self.blancos_por_llave = blancos_por_llave or {}
        self.dir = tempfile.mkdtemp()
        self.auditoria = os.path.join(self.dir, "auditoria.tsv")
        self.predicciones = os.path.join(self.dir, "predicciones.jsonl")
        self.meta = os.path.join(self.dir, "predicciones_meta.json")
        self.pares = os.path.join(self.dir, "pares.jsonl")
        self.operones = os.path.join(self.dir, "operones.tsv")
        self.salida = os.path.join(self.dir, "evaluacion.tsv")
        self.resumen = os.path.join(self.dir, "evaluacion.json")
        escribir_tsv(self.auditoria, S.COLUMNAS_AUDITORIA, auditoria)
        meta_de_juguete(self.meta, id2label)
        if operones is not None:
            escribir_tsv(self.operones, O.COLUMNAS_OPERONES, operones)

        pares, predicciones = [], []
        for i, fila in enumerate(auditoria):
            llave = (fila["pmid"], fila["tf"], fila["blanco"])
            if llave not in respuestas:
                continue
            prediccion, oracion = respuestas[llave]
            id_par = "id%04d" % i
            blanco = self.blancos_por_llave.get(
                llave, self.mapa_blancos.get(fila["blanco"], fila["blanco"]))
            pares.append({"text": "x", "label": "", "pmid": int(fila["pmid"]),
                          "tf": fila["tf"], "target": blanco,
                          "id_par": id_par, "seccion": "results",
                          "fuente": "fulltext", "n_oracion": 1,
                          "oracion_cruda": (fila["oracion"] if oracion is None
                                            else oracion)})
            probs = dict((("p_%s" % e), 0.0) for e in S.ETIQUETAS)
            probs["p_%s" % prediccion] = probabilidad
            resto = (1.0 - probabilidad) / 3.0
            for e in S.ETIQUETAS:
                if e != prediccion:
                    probs["p_%s" % e] = resto
            fila_pred = {"id_par": id_par, "pmid": int(fila["pmid"]),
                         "tf": fila["tf"], "target": blanco,
                         "prediccion": prediccion}
            fila_pred.update(probs)
            fila_pred.update({"seccion": "results", "fuente": "fulltext",
                              "autorregulacion": False, "redaccion":
                              fila["redaccion"]})
            predicciones.append(fila_pred)
        escribir_jsonl(self.pares, pares)
        escribir_jsonl(self.predicciones, predicciones)

    def correr(self, extra=()):
        argv = ["--auditoria", self.auditoria, "--predicciones",
                self.predicciones, "--pares", self.pares, "--salida",
                self.salida, "--resumen", self.resumen, "--red-informe",
                os.path.join(self.dir, "no_existe.json"),
                "--operones", self.operones]
        argv += list(extra)
        with contextlib.redirect_stdout(io.StringIO()) as salida:
            codigo = S.main(argv)
        self.impreso = salida.getvalue()
        self.codigo = codigo
        # Igual que el escenario del oro: el 2 quiere decir "la exactitud no
        # despega de la linea base sin informacion", y en un escenario de
        # juguete eso pasa a menudo. Lo que se exige en los dos casos es que
        # los archivos esten escritos, que es la razon de que el 2 exista en
        # vez de un sys.exit.
        assert codigo in (0, 2), codigo
        with io.open(self.resumen, encoding="utf-8") as f:
            self.json = json.load(f)
        self.filas = S.leer_tsv(self.salida, S.COLUMNAS_SALIDA, "salida")
        return self

    def limpiar(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def respuestas_por_redaccion(auditoria, mapa, no_evaluables="no_relation"):
    """Respuestas del modelo, incluidas las co-menciones sin respuesta conocida.

    Las 105 co-menciones llevan predicción a propósito: en una corrida real
    `predicciones.jsonl` las trae, y son lo único con lo que se puede estimar
    con qué frecuencia contesta el modelo una clase cuando la oración no
    afirma nada. De esa tasa cuelga el código de salida de `evaluar_signo.py`
    (`linea_base_sin_informacion`). Con `no_evaluables=None` se reproduce el
    archivo que no las trae, que es el caso en el que la tasa no se puede
    estimar.
    """
    salida = {}
    for fila in auditoria:
        llave = (fila["pmid"], fila["tf"], fila["blanco"])
        if fila["evaluable"] != "true":
            if no_evaluables is not None:
                salida[llave] = (no_evaluables, None)
            continue
        prediccion = mapa.get(fila["redaccion"])
        if prediccion is not None:
            salida[llave] = (prediccion, None)
    return salida


class PruebasLasVeinticuatro(unittest.TestCase):
    """El desglose por redacción es el resultado que este script produce."""

    def setUp(self):
        self.auditoria = corpus_auditoria()
        respuestas = respuestas_por_redaccion(
            self.auditoria,
            # El caso que el proyecto teme: acierta las directas y voltea el
            # signo en todas las escritas desde el fenotipo del mutante.
            {"directa": "represses", "fenotipo_mutante": "activates"})
        self.esc = EscenarioSigno(self.auditoria, respuestas).correr()

    def tearDown(self):
        self.esc.limpiar()

    def test_el_global_solo_no_bastaria(self):
        g = self.esc.json["global"]
        self.assertEqual(g["n"], 93)
        self.assertEqual((g["exactitud"]["n"], g["exactitud"]["d"]), (69, 93))

    def test_las_24_van_aparte(self):
        trampa = self.esc.json["la_trampa"]["fenotipo_mutante"]
        self.assertEqual(trampa["n"], 24)
        self.assertEqual(trampa["exactitud"]["n"], 0)
        self.assertEqual(trampa["tipo_error"].get("signo_invertido"), 24)

    def test_las_69_directas_van_aparte(self):
        directa = self.esc.json["la_trampa"]["directa"]
        self.assertEqual(directa["n"], 69)
        self.assertEqual(directa["exactitud"]["tasa"], 1.0)

    def test_el_desglose_tambien_esta_por_redaccion(self):
        self.assertEqual(sorted(self.esc.json["por_redaccion"]),
                         ["directa", "fenotipo_mutante"])

    def test_se_imprime_cual_es_la_trampa(self):
        self.assertIn("fenotipo_mutante", self.esc.impreso)
        self.assertIn("la trampa", self.esc.impreso)

    def test_las_105_co_menciones_no_entran_en_la_exactitud(self):
        self.assertEqual(self.esc.json["no_evaluables"]["n"], 105)
        self.assertEqual(len(self.esc.filas), 93)

    def test_un_fallo_repartido_no_se_confunde_con_la_trampa(self):
        """Mismo 74 % global, problema distinto: aquí falla en las dos clases."""
        respuestas = {}
        directas = [f for f in self.auditoria
                    if f["evaluable"] == "true" and f["redaccion"] == "directa"]
        fenotipo = [f for f in self.auditoria
                    if f["evaluable"] == "true"
                    and f["redaccion"] == "fenotipo_mutante"]
        for i, fila in enumerate(directas):
            respuestas[(fila["pmid"], fila["tf"], fila["blanco"])] = (
                ("activates" if i < 18 else "represses"), None)
        for i, fila in enumerate(fenotipo):
            respuestas[(fila["pmid"], fila["tf"], fila["blanco"])] = (
                ("activates" if i < 6 else "represses"), None)
        esc = EscenarioSigno(self.auditoria, respuestas).correr()
        try:
            self.assertEqual(esc.json["global"]["exactitud"]["n"], 69)
            self.assertEqual(
                esc.json["la_trampa"]["fenotipo_mutante"]["exactitud"]["n"], 18)
            self.assertEqual(
                esc.json["la_trampa"]["directa"]["exactitud"]["n"], 51)
        finally:
            esc.limpiar()


class PruebasUnionSigno(unittest.TestCase):

    def setUp(self):
        self.auditoria = corpus_auditoria()

    def test_union_exacta(self):
        respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})
        esc = EscenarioSigno(self.auditoria, respuestas).correr()
        try:
            self.assertEqual(esc.json["union"]["metodo"].get("exacta"), 93)
        finally:
            esc.limpiar()

    def test_union_por_prefijo(self):
        """La oración de la predicción diverge después del carácter 120."""
        respuestas = {}
        for fila in self.auditoria:
            if fila["evaluable"] != "true":
                continue
            recortada = fila["oracion"][:S.PREFIJO_UNION] + " y sigue de otro modo."
            respuestas[(fila["pmid"], fila["tf"], fila["blanco"])] = (
                "represses", recortada)
        esc = EscenarioSigno(self.auditoria, respuestas).correr()
        try:
            self.assertEqual(esc.json["union"]["metodo"].get("prefijo"), 93)
            self.assertEqual(esc.json["global"]["exactitud"]["n"], 93)
        finally:
            esc.limpiar()

    def test_encabezado_markdown_pegado(self):
        """9 de las 93 reales traen el encabezado pegado; sin recortarlo se pierden."""
        auditoria = list(self.auditoria)
        evaluables = [f for f in auditoria if f["evaluable"] == "true"]
        limpias = {}
        for fila in evaluables[:9]:
            limpia = fila["oracion"]
            fila["oracion"] = ("## RESULTS ### THE PUMP REPRESSOR ACTIVATES "
                               "PHENAZINES " + limpia)
            limpias[(fila["pmid"], fila["tf"], fila["blanco"])] = limpia
        respuestas = {}
        for fila in evaluables:
            llave = (fila["pmid"], fila["tf"], fila["blanco"])
            respuestas[llave] = ("represses", limpias.get(llave))
        esc = EscenarioSigno(auditoria, respuestas).correr()
        try:
            self.assertEqual(esc.json["union"]["tras_quitar_encabezado"], 9)
            self.assertEqual(esc.json["global"]["unidas"]["n"], 93)
        finally:
            esc.limpiar()

    def test_quitar_encabezado_no_toca_una_oracion_normal(self):
        oracion = "The expression of mexJK was repressed by MexL in PAO1."
        self.assertEqual(S.quitar_encabezado(oracion), oracion)

    def test_quitar_encabezado_no_deja_un_fragmento(self):
        # Si al recortar quedara casi nada, es mejor no unir que unir mal.
        corta = "### SOME UPPERCASE HEADING The end."
        self.assertEqual(S.quitar_encabezado(corta), corta)


class PruebasGuardianSigno(unittest.TestCase):
    """El guardián más barato del contrato: 80 de 93."""

    def setUp(self):
        self.auditoria = corpus_auditoria()

    def test_sale_con_1_si_no_se_unen_80(self):
        respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})
        # Se dejan 79: una menos del mínimo.
        for llave in list(respuestas)[79:]:
            del respuestas[llave]
        esc = EscenarioSigno(self.auditoria, respuestas)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    S.main(["--auditoria", esc.auditoria, "--predicciones",
                            esc.predicciones, "--pares", esc.pares,
                            "--salida", esc.salida, "--resumen", esc.resumen,
                            "--operones", esc.operones,
                            "--red-informe", os.path.join(esc.dir, "no.json")])
            self.assertIn("Solo 79 de 93", str(cm.exception))
            self.assertIn("texto.oraciones()", str(cm.exception))
            # No escribió nada: una métrica sobre 79 filas mediría otra cosa.
            self.assertFalse(os.path.exists(esc.salida))
        finally:
            esc.limpiar()

    def test_con_80_pasa_y_las_13_no_unidas_dicen_su_causa(self):
        """Las 13 no se unen porque su artículo no tiene ni una predicción.

        Antes las 13 salían como `sin_candidato`, cuyo significado declarado en
        §7 es "extraer_pares nunca generó esa oración". Aquí eso es falso: no
        hay nada del artículo entero. Quien lea el TSV se pondría a arreglar el
        segmentador.
        """
        respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})
        for llave in list(respuestas)[80:]:
            del respuestas[llave]
        esc = EscenarioSigno(self.auditoria, respuestas).correr()
        try:
            self.assertEqual(esc.json["global"]["unidas"]["n"], 80)
            self.assertEqual(esc.json["no_unidas"]["n"], 13)
            self.assertEqual(esc.json["no_unidas"]["por_causa"],
                             {"articulo_sin_predicciones": 13})
            self.assertEqual(
                esc.json["global"]["tipo_error"]["articulo_sin_predicciones"],
                13)
        finally:
            esc.limpiar()

    def test_sin_pares_dice_que_faltan_las_oraciones(self):
        """Sin texto no hay unión, y el guardián culparía al segmentador."""
        respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})
        esc = EscenarioSigno(self.auditoria, respuestas)
        try:
            # El informe de la red no existe a propósito, y desde que hay
            # guardián de procedencia eso imprime un aviso: se captura para que
            # no ensucie la salida de la batería.
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    S.main(["--auditoria", esc.auditoria, "--predicciones",
                            esc.predicciones, "--pares",
                            os.path.join(esc.dir, "no_existe.jsonl"),
                            "--salida", esc.salida, "--resumen", esc.resumen,
                            "--operones", esc.operones,
                            "--red-informe", os.path.join(esc.dir, "no.json")])
            self.assertIn("--pares", str(cm.exception))
        finally:
            esc.limpiar()

    def test_una_auditoria_de_otra_forma_se_rechaza(self):
        dirt = tempfile.mkdtemp()
        try:
            ruta = os.path.join(dirt, "auditoria.tsv")
            escribir_tsv(ruta, S.COLUMNAS_AUDITORIA,
                         corpus_auditoria(n_directas=1, n_fenotipo=1,
                                          n_no_evaluables=1))
            with self.assertRaises(SystemExit) as cm:
                S.cargar_auditoria(ruta)
            self.assertIn("no tiene la forma esperada", str(cm.exception))
        finally:
            shutil.rmtree(dirt, ignore_errors=True)


class PruebasTiposDeError(unittest.TestCase):

    def setUp(self):
        self.auditoria = corpus_auditoria()

    def correr_con(self, prediccion, extra=()):
        respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": prediccion,
                             "fenotipo_mutante": prediccion})
        return EscenarioSigno(self.auditoria, respuestas).correr(extra)

    def test_perdida_a_no_relation(self):
        esc = self.correr_con("no_relation")
        try:
            self.assertEqual(
                esc.json["global"]["tipo_error"]["perdida_a_no_relation"], 93)
        finally:
            esc.limpiar()

    def test_perdida_a_regulates(self):
        esc = self.correr_con("regulates")
        try:
            self.assertEqual(
                esc.json["global"]["tipo_error"]["perdida_a_regulates"], 93)
        finally:
            esc.limpiar()

    def test_bajo_umbral(self):
        """Acertó la clase pero no llega al umbral: no es lo mismo que fallar."""
        esc = self.correr_con("represses", ["--umbral-represses", "0.99"])
        try:
            g = esc.json["global"]
            self.assertEqual(g["exactitud"]["n"], 93)
            self.assertEqual(g["exactitud_con_umbral"]["n"], 0)
            self.assertEqual(g["tipo_error"]["bajo_umbral"], 93)
        finally:
            esc.limpiar()


class PruebasConsolaDeWindows(unittest.TestCase):
    """Lo que se imprime tiene que caber en la consola del laboratorio.

    En Windows la salida se codifica con la página de códigos de la consola, no
    con UTF-8. cp1252 y cp850 traen todas las acentuadas, pero cp437 --la de
    una instalación en inglés, que es lo que hay en varias máquinas del
    laboratorio-- no tiene las mayúsculas acentuadas ni el signo de sección.
    Un título como "EVALUACIÓN..." revienta ahí con UnicodeEncodeError después
    de haber corrido todo el análisis. Se comprueba sobre la salida real de los
    dos scripts, no sobre una lista de cadenas.
    """

    def codificable(self, texto):
        for cp in ("cp1252", "cp850", "cp437"):
            try:
                texto.encode(cp)
            except UnicodeEncodeError as e:
                self.fail("La salida no se puede imprimir en %s: %s" % (cp, e))

    def test_la_salida_de_evaluar_oro(self):
        # Con CollecTF, para que se imprima también ese bloque.
        esc = Escenario(FILAS, ARISTAS, PARES, collectf=[
            {"tf": "LexA", "blanco": "PA3617", "experimento": "EMSA",
             "pmids": "2", "en_corpus": "true"}])
        esc.correr(["--collectf", esc.collectf])
        try:
            self.codificable(esc.impreso)
        finally:
            esc.limpiar()

    def test_la_salida_de_evaluar_signo(self):
        auditoria = corpus_auditoria()
        respuestas = respuestas_por_redaccion(
            auditoria, {"directa": "represses",
                        "fenotipo_mutante": "activates"})
        esc = EscenarioSigno(auditoria, respuestas).correr()
        try:
            self.codificable(esc.impreso)
        finally:
            esc.limpiar()

    def test_los_mensajes_de_los_guardianes(self):
        """También los sys.exit: Python los escribe a stderr con la misma
        codificación, así que un guardián que no se puede imprimir se convierte
        en un rastro ilegible justo cuando hay que leerlo."""
        esc = Escenario(FILAS, ARISTAS, PARES)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as salida:
                with self.assertRaises(SystemExit) as cm:
                    O.main(["--oro", esc.oro, "--red", esc.red, "--pares",
                            esc.pares, "--genes", esc.genes, "--precision"])
            self.codificable(salida.getvalue())
            self.codificable(str(cm.exception))
        finally:
            esc.limpiar()
        with self.assertRaises(SystemExit) as cm:
            O.cargar_pares("no_existe.jsonl", {})
        self.codificable(str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            S.cargar_auditoria("no_existe.tsv")
        self.codificable(str(cm.exception))
        # Los guardianes nuevos: la circularidad por procedencia y el orden de
        # las etiquetas. Los dos son los que hay que poder leer.
        info = {"ruta": "genes.tsv", "filas": 5700,
                "filas_con_procedencia_del_oro": ["PA2492 (fuente=oro)"]}
        with self.assertRaises(SystemExit) as cm:
            O.revisar_procedencia(info)
        self.codificable(str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            S.cargar_meta(os.path.join(tempfile.mkdtemp(), "p.jsonl"))
        self.codificable(str(cm.exception))
        # Los dos guardianes nuevos: la sustancia del diccionario y la suma de
        # las probabilidades. El signo de seccion no existe en cp437, y los dos
        # mensajes hablan de secciones del contrato.
        sustancia = O.medir_sustancia(set([("mext", "mexe")]),
                                      {"mext": 1, "mexe": 1},
                                      set(["mext", "mexe"]))
        with self.assertRaises(SystemExit) as cm:
            O.revisar_sustancia(sustancia, "genes.tsv", "pares.jsonl")
        self.codificable(str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            O.revisar_probabilidades_de_fila(
                dict((("p_%s" % e), 0.99) for e in S.ETIQUETAS),
                "predicciones.jsonl", 1)
        self.codificable(str(cm.exception))
        esc = escenario_que_despega()
        try:
            self.codificable(esc.impreso)
        finally:
            esc.limpiar()


class PruebasAuditoriaReal(unittest.TestCase):
    """Los números que la documentación cita, medidos sobre la tabla."""

    def test_la_forma_y_el_reparto(self):
        filas = S.cargar_auditoria(AUDITORIA_REAL)
        self.assertEqual(len(filas), 198)
        evaluables = [f for f in filas
                      if f["evaluable"] == "true" and f["signo_correcto"]]
        self.assertEqual(len(evaluables), S.EVALUABLES)
        reparto = {}
        for fila in evaluables:
            reparto[fila["redaccion"]] = reparto.get(fila["redaccion"], 0) + 1
        self.assertEqual(reparto, S.POR_REDACCION)
        # Todas las evaluables tienen la misma respuesta conocida.
        self.assertEqual(set(f["signo_correcto"] for f in evaluables),
                         set(["represses"]))

    def test_nueve_traen_el_encabezado_pegado(self):
        filas = S.cargar_auditoria(AUDITORIA_REAL)
        evaluables = [f for f in filas
                      if f["evaluable"] == "true" and f["signo_correcto"]]
        pegadas = [f for f in evaluables if f["oracion"].lstrip().startswith("#")]
        self.assertEqual(len(pegadas), 9)
        for fila in pegadas:
            recortada = S.quitar_encabezado(fila["oracion"])
            self.assertNotEqual(recortada, fila["oracion"])
            self.assertFalse(recortada.startswith("#"))


# ---------------------------------------------------------------------------
# La circularidad, por procedencia y no por conteo
# ---------------------------------------------------------------------------

def escribir_genes_crudos(ruta, filas):
    escribir_tsv(ruta, O.COLUMNAS_GENES, filas)


def fila_gen(locus, simbolo="", alias="", fuente="refseq"):
    return {"locus_tag": locus, "simbolo": simbolo, "alias": alias,
            "tipo": "protein_coding", "producto": "proteina", "es_tf": "false",
            "fuente_tf": "", "fuente": fuente, "sensible_mayusculas": "false"}


class PruebasCircularidad(unittest.TestCase):
    """El exploit medido, reproducido: un diccionario copiado del patrón.

    El guardián anterior exigía cobertura del 100 % **y** menos de 1000 líneas
    en el TSV, y `n_genes` contaba líneas. Rellenar el archivo con filas de
    símbolo vacío hasta 5700 lo desactivaba sin tocar nada de lo que decía
    vigilar, y el script publicaba exhaustividad 81.7 % con código 0. Es el
    mismo patrón del verificador de fuga que medía con la clave del
    agrupamiento: la condición elegida no podía dispararse en el caso que
    quería atrapar.
    """

    def setUp(self):
        self.esc = Escenario([fila_oro("MexT", "mexT")], [], [])
        escribir_tsv(self.esc.oro, O.COLUMNAS_ORO,
                     [fila_oro("MexT", "mexT")] * O.FILAS_ORO)

    def tearDown(self):
        self.esc.limpiar()

    def correr(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                O.main(["--oro", self.esc.oro, "--red", self.esc.red,
                        "--pares", self.esc.pares, "--genes", self.esc.genes,
                        "--operones", self.esc.operones, "--salida",
                        self.esc.salida, "--resumen", self.esc.resumen])
        return str(cm.exception)

    def test_una_sola_fila_con_procedencia_del_oro_aborta(self):
        escribir_genes_crudos(self.esc.genes, [
            fila_gen("PA2492", "mexT", fuente="oro"),
            fila_gen("PA0424", "mexR"),
        ])
        mensaje = self.correr()
        self.assertIn("procedencia es el patrón de oro", mensaje)
        self.assertIn("circular", mensaje)
        self.assertFalse(os.path.exists(self.esc.salida))

    def test_la_procedencia_manda_aunque_el_archivo_sea_enorme(self):
        """Con 5700 filas y cobertura baja, el guardián de tamaño no salta."""
        filas = [fila_gen("PA%04d" % i, "gen%04d" % i, fuente="refseq")
                 for i in range(5700)]
        filas[0] = fila_gen("PA0000", "mexT", fuente="refseq|oro")
        escribir_genes_crudos(self.esc.genes, filas)
        mensaje = self.correr()
        self.assertIn("procedencia es el patrón de oro", mensaje)

    def test_el_relleno_ya_no_desactiva_el_guardian_de_tamano(self):
        """El exploit exacto: 5700 líneas, una sola entidad útil.

        La procedencia declarada es `refseq` en las 5700, o sea que quien lo
        fabricó también mintió en esa columna. Aun así no pasa: el guardián de
        tamaño cuenta entidades útiles, no líneas.
        """
        filas = [fila_gen("PA2492", "mexT")]
        filas += [fila_gen("PA%04d" % i) for i in range(1, 5700)]
        escribir_genes_crudos(self.esc.genes, filas)
        mensaje = self.correr()
        self.assertIn("hecho desde el oro", mensaje)
        self.assertIn("entidades útiles", mensaje)
        self.assertIn("5700", mensaje)

    def test_la_contaminacion_A_MEDIAS_tambien_aborta(self):
        """El hueco que §6 dejaba abierto, y por el que se escribió el guardián
        de cobertura.

        §6 es una conjunción: cobertura del 100 % **y** menos de 1000 entidades
        útiles. Un diccionario grande y legítimo al que le copian los nombres
        del oro cumple la primera y no la segunda, así que pasaba. Medido en el
        informe: un 12 % de filas copiadas no disparaba ningún aviso, subía
        todas las cifras, y de hecho BAJABA `fraccion_explicada_por_el_oro`,
        porque los nombres copiados engordan su denominador.

        La cobertura del oro no se puede diluir: su denominador es el
        vocabulario del oro, que es fijo.
        """
        # 1500 entidades útiles: muy por encima del mínimo de §6, así que ese
        # guardián no se dispara y el que responde tiene que ser el otro.
        filas = [fila_gen("PA%04d" % i, "gen%04d" % i) for i in range(1500)]
        # Y encima, los nombres que el oro escribe.
        filas.append(fila_gen("PA2492", "mexT"))
        escribir_genes_crudos(self.esc.genes, filas)
        mensaje = self.correr()
        self.assertIn("vocabulario que escribe el patrón de oro", mensaje)
        self.assertNotIn("entidades útiles", mensaje,
                         "ese es el mensaje de §6; aquí no debería aplicar")

    def test_un_diccionario_de_verdad_pasa(self):
        """El guardián no puede dispararse con el diccionario que se espera."""
        filas = [fila_gen("PA%04d" % i, "gen%04d" % i) for i in range(5700)]
        escribir_genes_crudos(self.esc.genes, filas)
        mapa, info = O.cargar_diccionario(self.esc.genes)
        self.assertEqual(info["entidades_utiles"], 5700)
        self.assertEqual(info["filas_con_procedencia_del_oro"], [])
        O.revisar_procedencia(info)      # no levanta

    def test_las_fuentes_desconocidas_se_avisan_pero_no_abortan(self):
        esc = Escenario(FILAS, ARISTAS, PARES)
        try:
            filas = [fila_gen(locus, simbolo, fuente="inventada")
                     for locus, simbolo in GENES]
            escribir_genes_crudos(esc.genes, filas)
            esc.correr()
            avisos = " ".join(esc.json["avisos"])
            self.assertIn("inventada", avisos)
            self.assertIn("construir_diccionario.py", avisos)
            self.assertEqual(esc.json["entradas"]["diccionario"]
                             ["fuentes_desconocidas"], {"inventada": 24})
        finally:
            esc.limpiar()


# ---------------------------------------------------------------------------
# La equivalencia operón-gen es asimétrica
# ---------------------------------------------------------------------------

class PruebasEquivalenciaAsimetrica(unittest.TestCase):
    """El nombre de la referencia se expande; el del pipeline, solo por tabla.

    `lexico` acuña entidades sintéticas desde el texto en cuanto todos los
    miembros existen en el diccionario (`lasRIAB`, `rsmZA`, `gacAS`). Con la
    expansión mecánica del lado del pipeline, una sola arista inventada
    `LasR -> lasRIAB` se contaba como recuperación de TRES filas del oro a la
    vez, las tres con coincidencia `por_operon`.
    """

    GENES_LAS = [("PA1430", "lasR"), ("PA1431", "lasI"), ("PA3724", "lasB"),
                 ("PA1871", "lasA")]

    def escenario(self, operones=None):
        filas = [fila_oro("LasR", "lasA", "activates"),
                 fila_oro("LasR", "lasB", "activates"),
                 fila_oro("LasR", "lasI", "activates")]
        esc = Escenario(filas, [fila_red("LasR", "lasRIAB", "activates")],
                        [("LasR", "lasRIAB")], operones=operones)
        escribir_genes(esc.genes, self.GENES_LAS)
        return esc.correr()

    def test_una_arista_inventada_no_recupera_tres_filas(self):
        esc = self.escenario()
        try:
            for blanco in ("lasA", "lasB", "lasI"):
                fila = esc.fila("LasR", blanco)
                self.assertEqual(fila["coincidencia"], "ninguna")
                self.assertEqual(fila["signo_red"], "")
                self.assertTrue(fila["veredicto"].startswith("no_recuperada"),
                                fila["veredicto"])
            self.assertEqual(esc.json["honesto"]["exhaustividad"]["n"], 0)
        finally:
            esc.limpiar()

    def test_pero_se_dice_cuantas_habrian_contado(self):
        """Cambiar de criterio en silencio se leería como una caída."""
        esc = self.escenario()
        try:
            b = esc.json["equivalencia_operon"]
            self.assertEqual(
                b["solo_con_expansion_mecanica_del_pipeline"],
                ["LasR->lasA", "LasR->lasB", "LasR->lasI"])
            self.assertIn("lasRIAB", " ".join(esc.json["avisos"]))
        finally:
            esc.limpiar()

    def test_un_operon_de_la_tabla_si_empareja(self):
        """El camino que §6.3 sí autoriza: la tabla derivada del diccionario."""
        filas = [fila_oro("MexT", "mexE", "activates")]
        esc = Escenario(filas, [fila_red("MexT", "mexEF-oprN", "activates")],
                        [("MexT", "mexEF-oprN")], operones=OPERONES)
        try:
            esc.correr()
            fila = esc.fila("MexT", "mexE")
            self.assertEqual(fila["coincidencia"], "por_operon")
            self.assertEqual(fila["veredicto"], "recuperada_signo_ok")
        finally:
            esc.limpiar()

    def test_sin_tabla_ese_mismo_operon_no_empareja(self):
        filas = [fila_oro("MexT", "mexE", "activates")]
        esc = Escenario(filas, [fila_red("MexT", "mexEF-oprN", "activates")],
                        [("MexT", "mexEF-oprN")])
        try:
            esc.correr()
            self.assertEqual(esc.fila("MexT", "mexE")["coincidencia"],
                             "ninguna")
            self.assertIn("No hay tabla de operones",
                          " ".join(esc.json["avisos"]))
        finally:
            esc.limpiar()

    def test_el_nombre_del_oro_si_se_expande(self):
        """Es una tabla versionada de 190 filas: el pipeline no la escribe."""
        self.assertEqual(O.miembros_de_tabla("mexAB-oprM", {}), frozenset())
        self.assertEqual(sorted(O.miembros_operon("mexAB-oprM")),
                         ["mexA", "mexB", "oprM"])


# ---------------------------------------------------------------------------
# La línea base aleatoria
# ---------------------------------------------------------------------------

def escenario_que_despega(extra=(), n_fondo=60, signos=None):
    """20 filas del oro recuperadas todas con el signo correcto.

    Es el único escenario de juguete en el que el acierto de signo se puede
    distinguir del azar: con 20 filas comparables acertadas, la probabilidad
    de que el azar llegue tan lejos es 0.75^20, del orden de 0.003. Con tres o
    cuatro filas no se distingue nada, y por eso los demás escenarios de este
    archivo salen con código 2.
    """
    simbolos = [s for _, s in GENES]
    filas, aristas, pares = [], [], []
    for i in range(20):
        blanco = simbolos[i]
        gen_tf = simbolos[(i + 1) % len(simbolos)]
        tf = gen_tf[0].upper() + gen_tf[1:]
        signo = "activates" if i % 2 == 0 else "represses"
        filas.append(fila_oro(tf, blanco, signo))
        aristas.append(fila_red(tf, blanco, signos[i] if signos else signo))
        pares.append((tf, blanco))
    return Escenario(filas, aristas, pares, n_fondo=n_fondo).correr(extra)


class PruebasLineaBase(unittest.TestCase):
    """El contrapeso de la exhaustividad.

    Con predicciones COMPLETAMENTE aleatorias sobre el corpus entero,
    `evaluar_oro.py` publicaba EXHAUSTIVIDAD 95.5 % (105 de 110) y código de
    salida 0. La métrica se satura porque un par del oro suele tener muchas
    oraciones candidatas y basta que una salga bien. Un clasificador roto se
    leía como éxito y nada en la salida lo delataba.
    """

    def setUp(self):
        self.esc = Escenario(FILAS, ARISTAS, PARES).correr()

    def tearDown(self):
        self.esc.limpiar()

    def test_se_publica_junto_a_la_cifra_real(self):
        b = self.esc.json["linea_base_aleatoria"]
        self.assertEqual(b["exhaustividad"]["real"],
                         self.esc.json["honesto"]["exhaustividad"]["tasa"])
        self.assertEqual(b["acierto_signo"]["real"],
                         self.esc.json["honesto"]["acierto_signo"]["tasa"])
        self.assertIsNotNone(b["exhaustividad"]["azar_media"])
        self.assertIsNotNone(b["acierto_signo"]["azar_media"])

    def test_se_imprime_en_la_terminal(self):
        self.assertIn("linea base aleatoria", self.esc.impreso)
        self.assertIn("ACIERTO DE SIGNO", self.esc.impreso)

    def test_sortea_sobre_los_mismos_candidatos(self):
        """"Los mismos" es literal: las mismas filas y las mismas oraciones."""
        b = self.esc.json["linea_base_aleatoria"]
        honestas = [f for f in self.esc.filas
                    if f["en_denominador_honesto"] == "true"]
        con_candidato = [f for f in honestas if f["hubo_candidato"] == "true"
                         and f["resuelto_tf"] and f["resuelto_blanco"]]
        self.assertEqual(b["filas_con_candidato"], len(con_candidato))
        self.assertEqual(b["oraciones_candidatas"],
                         sum(int(f["n_candidatos"]) for f in con_candidato))
        self.assertEqual(b["exhaustividad"]["real"],
                         self.esc.json["honesto"]["exhaustividad"]["tasa"])

    def test_es_determinista_con_la_semilla(self):
        otra = Escenario(FILAS, ARISTAS, PARES).correr(["--semilla", "99"])
        tercera = Escenario(FILAS, ARISTAS, PARES).correr(["--semilla", "99"])
        try:
            self.assertEqual(otra.json["linea_base_aleatoria"],
                             tercera.json["linea_base_aleatoria"])
        finally:
            otra.limpiar()
            tercera.limpiar()

    def test_la_semilla_y_las_repeticiones_viajan_en_el_json(self):
        esc = Escenario(FILAS, ARISTAS, PARES).correr(
            ["--semilla", "7", "--repeticiones-linea-base", "25"])
        try:
            b = esc.json["linea_base_aleatoria"]
            self.assertEqual(b["semilla"], 7)
            self.assertEqual(b["repeticiones"], 25)
            self.assertEqual(b["exhaustividad"]["sorteos_con_dato"], 25)
        finally:
            esc.limpiar()

    def test_el_azar_recupera_casi_todo_lo_que_tiene_candidato(self):
        """La razón de que la exhaustividad no decida el código de salida.

        Con 8 oraciones candidatas por par, el azar recupera el par con
        probabilidad 1 - (1/4)^8, o sea prácticamente siempre. Esa es la forma
        exacta en la que 105 de 110 salían "recuperadas" con predicciones al
        azar.
        """
        pares = [(tf, blanco) for tf, blanco in PARES for _ in range(8)]
        esc = Escenario(FILAS, ARISTAS, pares).correr()
        try:
            b = esc.json["linea_base_aleatoria"]["exhaustividad"]
            self.assertGreater(b["azar_media"], 0.95)
            self.assertLess(b["ventaja_puntos"], 0)
        finally:
            esc.limpiar()

    def test_el_codigo_2_cuando_el_signo_no_despega(self):
        self.assertEqual(self.esc.codigo, 2)
        self.assertIn("NO HAY RESULTADO", self.esc.impreso)
        # Y aun así los dos archivos están escritos: sin el detalle fila por
        # fila no hay forma de diagnosticar por qué no despega.
        self.assertTrue(os.path.exists(self.esc.salida))
        self.assertTrue(os.path.exists(self.esc.resumen))
        v = self.esc.json["veredicto_del_signo"]
        self.assertEqual(v["despega_de_las_dos_lineas_base"], False)
        self.assertEqual(v["codigo_de_salida"], 2)

    def test_el_codigo_0_cuando_despega(self):
        esc = escenario_que_despega()
        try:
            self.assertEqual(esc.codigo, 0)
            b = esc.json["linea_base_aleatoria"]
            v = esc.json["veredicto_del_signo"]
            self.assertTrue(v["despega_de_las_dos_lineas_base"])
            self.assertLessEqual(b["acierto_signo"]["p_valor"], O.ALFA)
            self.assertLessEqual(v["p_contra_la_clase_mayoritaria"], O.ALFA)
            self.assertEqual(b["acierto_signo"]["real"], 1.0)
            self.assertLess(b["acierto_signo"]["azar_media"], 0.7)
            self.assertIn("despega de las dos lineas base", esc.impreso)
        finally:
            esc.limpiar()

    def test_sin_ninguna_fila_comparable_tampoco_hay_resultado(self):
        esc = Escenario([fila_oro("MexT", "mexEF-oprN", "activates")], [],
                        [("MexT", "mexEF-oprN")]).correr()
        try:
            self.assertEqual(esc.codigo, 2)
            self.assertIsNone(
                esc.json["linea_base_aleatoria"]["acierto_signo"]["p_valor"])
            self.assertIn("NO HAY RESULTADO", esc.impreso)
        finally:
            esc.limpiar()

    def test_el_json_explica_que_significa_cada_codigo(self):
        b = self.esc.json["veredicto_del_signo"]
        texto = b["que_significa_el_codigo_de_salida"]
        self.assertIn("0 =", texto)
        self.assertIn("2 =", texto)
        self.assertIn("no decide el código de salida", texto)

    def test_el_sorteo_reproduce_la_regla_de_mayoria(self):
        """Sin candidatos no hay arista; con uno solo, nunca hay conflicto."""
        rng = __import__("random").Random(0)
        self.assertEqual(O.sortear_arista(rng, 0, 0.66), (False, ""))
        vistos = set()
        for _ in range(400):
            vistos.add(O.sortear_arista(rng, 1, 0.66))
        self.assertEqual(vistos, set([(False, ""), (True, "activates"),
                                      (True, "represses"),
                                      (True, "regulates")]))


# ---------------------------------------------------------------------------
# El orden de las etiquetas, en la rama que colgaba de clasificar.py
# ---------------------------------------------------------------------------

class PruebasMetaDelSigno(unittest.TestCase):
    """§8 cuelga evaluar_signo.py de clasificar.py sin pasar por red.py.

    red.py rechaza un meta con el orden de LABELS_DEFAULT; evaluar_signo.py no
    lo miraba siquiera. Con `represses` y `no_relation` intercambiados,
    publicaría 93 de 93 `perdida_a_no_relation`, que se lee como un fallo del
    modelo cuando es un fallo de carga, y es la única medición de signo a nivel
    de oración del proyecto.
    """

    def setUp(self):
        self.auditoria = corpus_auditoria()
        self.respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})

    def correr(self, esc):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                S.main(["--auditoria", esc.auditoria, "--predicciones",
                        esc.predicciones, "--pares", esc.pares, "--salida",
                        esc.salida, "--resumen", esc.resumen, "--operones",
                        esc.operones, "--red-informe",
                        os.path.join(esc.dir, "no.json")])
        return str(cm.exception)

    def test_sin_meta_no_hay_medicion(self):
        esc = EscenarioSigno(self.auditoria, self.respuestas)
        try:
            os.remove(esc.meta)
            mensaje = self.correr(esc)
            self.assertIn("No encuentro el meta", mensaje)
            self.assertFalse(os.path.exists(esc.salida))
        finally:
            esc.limpiar()

    def test_el_orden_de_labels_default_se_rechaza(self):
        # LABELS_DEFAULT de bio_bert_re_finetune.py: intercambia represses con
        # no_relation respecto del checkpoint.
        malo = dict(enumerate(["activates", "represses", "regulates",
                               "no_relation"]))
        esc = EscenarioSigno(self.auditoria, self.respuestas,
                             id2label=dict((str(k), v)
                                           for k, v in malo.items()))
        try:
            mensaje = self.correr(esc)
            self.assertIn("no son de fiar", mensaje)
            self.assertFalse(os.path.exists(esc.salida))
        finally:
            esc.limpiar()

    def test_el_meta_bueno_viaja_al_resumen(self):
        esc = EscenarioSigno(self.auditoria, self.respuestas).correr()
        try:
            self.assertEqual(esc.json["entradas"]["id2label"]["3"],
                             "represses")
            self.assertEqual(esc.json["entradas"]["do_lower_case"], False)
        finally:
            esc.limpiar()

    def test_las_dos_ramas_esperan_el_mismo_orden(self):
        """Está escrito dos veces; que no puedan divergir es una prueba."""
        import red as R
        self.assertEqual(list(S.ETIQUETAS), list(R.ETIQUETAS))


# ---------------------------------------------------------------------------
# La unión de §7 y la granularidad de operón
# ---------------------------------------------------------------------------

MAPA_A_GEN = {"mexAB-oprM": "mexA", "mexCD-oprJ": "mexC", "mexXY": "mexX",
              "mexJK": "mexJ"}


class PruebasEquivalenciaOperonSigno(unittest.TestCase):
    """4 de los 6 represores tienen el blanco escrito como operón.

    Medido sobre el corpus completo: uniendo por (pmid, tf, blanco) literal se
    unían 76 de 93, el guardián de 80/93 saltaba y evaluar_signo.py salía con
    código 1 sin escribir nada, o sea que la única medición de signo del
    proyecto no se podía calcular. Con equivalencia de operón, 84 de 93.
    """

    def setUp(self):
        self.auditoria = corpus_auditoria()
        self.respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})

    def test_el_pipeline_nombro_el_gen_y_la_auditoria_el_operon(self):
        esc = EscenarioSigno(self.auditoria, self.respuestas,
                             mapa_blancos=MAPA_A_GEN).correr()
        try:
            evaluables = [f for f in self.auditoria
                          if f["evaluable"] == "true"]
            de_operon = sum(1 for f in evaluables
                            if f["blanco"] in MAPA_A_GEN)
            union = esc.json["union"]["equivalencia_del_blanco"]
            self.assertEqual(esc.json["global"]["unidas"]["n"], 93)
            self.assertEqual(union["por_operon"], de_operon)
            self.assertEqual(union["exacta"], 93 - de_operon)
            # Y la columna lo dice fila por fila.
            filas = [f for f in esc.filas if f["blanco"] == "mexJK"]
            self.assertTrue(filas)
            for fila in filas:
                self.assertEqual(fila["equivalencia_blanco"], "por_operon")
        finally:
            esc.limpiar()

    def test_sin_equivalencia_el_guardian_habria_saltado(self):
        """La aritmética que dejaba sin medición de signo al proyecto.

        Las que se unen por nombre exacto son las de los dos represores cuyo
        blanco es un gen suelto. Solas no llegan al mínimo de 80, así que sin
        equivalencia de operón el guardián aborta y no se escribe nada. Es
        exactamente lo que pasó al correr sobre el corpus completo: 76 de 93.
        """
        esc = EscenarioSigno(self.auditoria, self.respuestas,
                             mapa_blancos=MAPA_A_GEN).correr()
        try:
            union = esc.json["union"]["equivalencia_del_blanco"]
            self.assertLess(union["exacta"], S.MINIMO_UNIDAS)
            self.assertEqual(union["exacta"] + union["por_operon"],
                             esc.json["global"]["unidas"]["n"])
        finally:
            esc.limpiar()

    def test_se_expande_el_nombre_de_la_auditoria(self):
        exactas, equivalentes = S.claves_blanco("mexAB-oprM", {})
        self.assertEqual(exactas, set(["mexab-oprm"]))
        self.assertEqual(equivalentes, set(["mexa", "mexb", "oprm"]))

    def test_no_se_inventa_nada_para_un_gen_suelto(self):
        exactas, equivalentes = S.claves_blanco("armR", {})
        self.assertEqual(exactas, set(["armr"]))
        self.assertEqual(equivalentes, set())

    def test_el_camino_inverso_solo_sale_de_la_tabla(self):
        """La auditoría nombra el gen y el pipeline el operón."""
        operones = {"mexab-oprm": ["mexa", "mexb", "oprm"]}
        _, equivalentes = S.claves_blanco("mexA", operones)
        self.assertIn("mexab-oprm", equivalentes)
        _, sin_tabla = S.claves_blanco("mexA", {})
        self.assertEqual(sin_tabla, set())


class PruebasCausasDeNoUnion(unittest.TestCase):
    """`sin_candidato` no es la única causa, y decir que sí manda a arreglar
    el segmentador cuando el defecto está en el diccionario."""

    def setUp(self):
        self.auditoria = corpus_auditoria()
        self.respuestas = respuestas_por_redaccion(
            self.auditoria, {"directa": "represses",
                             "fenotipo_mutante": "represses"})

    def llaves(self, n=5):
        return [(f["pmid"], f["tf"], f["blanco"]) for f in self.auditoria
                if f["evaluable"] == "true"][:n]

    def escenario_par_distinto(self):
        """Cinco filas cuyo pipeline llamó al blanco de otra manera.

        `pvdA` no es equivalente de ninguno de esos blancos, así que el par no
        se genera nunca con ese nombre: el artículo sí trae predicciones, pero
        de otro par. Esa es la causa `par_distinto`, y el arreglo está en el
        diccionario, no en el segmentador.
        """
        llaves = self.llaves()
        esc = EscenarioSigno(
            self.auditoria, self.respuestas,
            blancos_por_llave=dict((k, "pvdA") for k in llaves)).correr()
        return esc, set(k[0] for k in llaves)

    def test_par_distinto_no_se_llama_sin_candidato(self):
        esc, pmids = self.escenario_par_distinto()
        try:
            afectadas = [f for f in esc.filas if f["pmid"] in pmids]
            self.assertEqual(len(afectadas), 5)
            for fila in afectadas:
                self.assertEqual(fila["tipo_error"], "par_distinto")
            self.assertEqual(esc.json["no_unidas"]["por_causa"],
                             {"par_distinto": 5})
        finally:
            esc.limpiar()

    def test_sin_candidato_es_el_par_que_si_existe(self):
        """Mismo par, otra oración: eso sí es un fallo del segmentador."""
        respuestas = dict(self.respuestas)
        for llave in self.llaves():
            respuestas[llave] = ("represses",
                                 "Una oracion completamente distinta que no "
                                 "casa ni por prefijo con la de la auditoria, "
                                 "ni de lejos, ni por casualidad.")
        esc = EscenarioSigno(self.auditoria, respuestas).correr()
        try:
            self.assertEqual(esc.json["no_unidas"]["por_causa"],
                             {"sin_candidato": 5})
        finally:
            esc.limpiar()

    def test_el_tsv_lleva_la_causa_fila_por_fila(self):
        esc, _ = self.escenario_par_distinto()
        try:
            causas = set(f["tipo_error"] for f in esc.filas
                         if f["prediccion"] == "")
            self.assertEqual(causas, set(["par_distinto"]))
            self.assertIn("par_distinto", esc.impreso)
        finally:
            esc.limpiar()


# ---------------------------------------------------------------------------
# La segunda linea base: la clase mayoritaria, que no es el 50 %
# ---------------------------------------------------------------------------

def escenario_constante(n_activates=16, n_represses=4, n_fondo=60):
    """Un clasificador que contesta siempre `activates`, y nada más.

    Es el exploit medido, en pequeño: sobre las 139 filas comparables de una
    corrida real, decir siempre `activates` publicaba ACIERTO DE SIGNO 69.8 %
    (97 de 139) --clavado en la proporción de `activates` de esas mismas
    filas-- y `evaluar_oro.py` cerraba con "El acierto de signo se distingue
    del azar (p = 0.005). Codigo 0".
    """
    simbolos = [s for _, s in GENES]
    filas, aristas, pares = [], [], []
    for i in range(n_activates + n_represses):
        blanco = simbolos[i]
        gen_tf = simbolos[(i + 1) % len(simbolos)]
        tf = gen_tf[0].upper() + gen_tf[1:]
        filas.append(fila_oro(tf, blanco,
                              "activates" if i < n_activates else "represses"))
        aristas.append(fila_red(tf, blanco, "activates"))
        pares.append((tf, blanco))
    return Escenario(filas, aristas, pares, n_fondo=n_fondo).correr()


class PruebasLineaBaseMayoritaria(unittest.TestCase):
    """La línea base del acierto de signo no es 50 %.

    El comentario POR_QUE_SE_SATURA lo afirmaba como hecho ("su línea base es
    50 % venga de donde venga") y de esa comparación colgaba el código de
    salida. Es falso: sobre dos clases, la línea base es la proporción de la
    clase mayoritaria del subconjunto que se evalúa, porque un clasificador
    constante la acierta entera sin leer una palabra.
    """

    def setUp(self):
        self.esc = escenario_constante()

    def tearDown(self):
        self.esc.limpiar()

    def test_el_clasificador_constante_no_despega(self):
        self.assertEqual(self.esc.codigo, 2)
        self.assertIn("NO HAY RESULTADO", self.esc.impreso)
        # El envolvedor puede partir la frase, asi que se buscan las piezas.
        self.assertIn("no se distingue de contestar", self.esc.impreso)
        self.assertIn("clase mayoritaria de esas 20 filas", self.esc.impreso)
        # Y los archivos están escritos: el 2 no es un sys.exit.
        self.assertTrue(os.path.exists(self.esc.salida))

    def test_la_linea_base_aleatoria_sola_lo_habria_certificado(self):
        """Este es el defecto entero, en dos asserts.

        Con la semilla fija, el sorteo uniforme da p = 0.035 --por debajo de
        alfa-- para un clasificador que no hace nada, porque reparte las dos
        clases a partes iguales y da ~50 % pase lo que pase. La clase
        mayoritaria lo caza: acierta exactamente lo mismo que el pipeline.
        """
        v = self.esc.json["veredicto_del_signo"]
        self.assertLessEqual(v["p_contra_el_azar"], O.ALFA)
        self.assertGreater(v["p_contra_la_clase_mayoritaria"], O.ALFA)
        self.assertFalse(v["despega_de_las_dos_lineas_base"])
        self.assertEqual(v["codigo_de_salida"], 2)

    def test_la_tasa_base_es_la_clase_mayoritaria_y_no_el_50(self):
        m = self.esc.json["linea_base_mayoritaria"]
        self.assertEqual(m["clase_mayoritaria"], "activates")
        self.assertEqual(m["reparto_del_oro"],
                         {"activates": 16, "represses": 4})
        self.assertEqual(m["tasa_base"], 0.8)
        self.assertNotEqual(m["tasa_base"], 0.5)
        # El pipeline acierta exactamente eso: ni un punto más.
        self.assertEqual(m["real"], m["tasa_base"])
        self.assertEqual(m["ventaja_puntos"], 0.0)

    def test_se_imprime_al_lado_de_la_cifra(self):
        self.assertIn("Contra la clase mayoritaria", self.esc.impreso)
        self.assertIn("activates", self.esc.impreso)

    def test_un_pipeline_que_acierta_de_verdad_si_despega(self):
        esc = escenario_que_despega()
        try:
            m = esc.json["linea_base_mayoritaria"]
            self.assertEqual(m["real"], 1.0)
            self.assertLessEqual(m["p_valor"], O.ALFA)
            self.assertEqual(esc.codigo, 0)
        finally:
            esc.limpiar()

    def test_la_binomial_es_exacta(self):
        """Sin aproximación normal: en las colas es donde se decide."""
        self.assertAlmostEqual(O.binomial_cola_superior(0, 10, 0.5), 1.0)
        self.assertAlmostEqual(O.binomial_cola_superior(10, 10, 0.5),
                               0.5 ** 10)
        self.assertAlmostEqual(O.binomial_cola_superior(2, 2, 0.5), 0.25)
        self.assertAlmostEqual(O.binomial_cola_superior(1, 2, 0.5), 0.75)
        # Casos degenerados: el constante perfecto y el imposible.
        self.assertEqual(O.binomial_cola_superior(5, 5, 1.0), 1.0)
        self.assertEqual(O.binomial_cola_superior(1, 5, 0.0), 0.0)
        self.assertIsNone(O.binomial_cola_superior(0, 0, 0.5))

    def test_el_texto_ya_no_afirma_que_la_linea_base_sea_50(self):
        """Un comentario que afirma algo falso es peor que no tenerlo."""
        self.assertNotIn("su línea base es 50 %", O.POR_QUE_SE_SATURA)
        self.assertIn("clase mayoritaria", O.POR_QUE_SE_SATURA)
        self.assertIn("69.8", O.POR_QUE_SE_SATURA)
        # Y ES_GENEROSA ya no dice que el sesgo sea siempre contra el pipeline.
        self.assertIn("al revés", O.ES_GENEROSA)

    def test_sin_filas_comparables_no_hay_linea_base(self):
        m = O.linea_base_mayoritaria([])
        self.assertEqual(m["filas_comparables"], 0)
        self.assertIsNone(m["p_valor"])


# ---------------------------------------------------------------------------
# La sustancia del diccionario: contenido, no procedencia declarada
# ---------------------------------------------------------------------------

class PruebasSustancia(unittest.TestCase):
    """El guardián de circularidad que mide, en vez de preguntar.

    Los otros dos miran la columna `fuente` (texto que se escribe) y un conteo
    de filas con símbolo (relleno que se fabrica). El exploit medido pasaba los
    dos: un genes_pao1.tsv cuyas filas con contenido eran copia literal del
    oro, declarando `fuente=refseq`, con las de relleno llevando un símbolo
    inventado (zzz0001...), publicaba cobertura 100.0 %, EXHAUSTIVIDAD 95.3 %
    y ACIERTO DE SIGNO 98.8 % con código 0.
    """

    def escenario_copiado(self, n_fondo=0):
        """Diccionario del oro con relleno inventado y `fuente=refseq`."""
        esc = Escenario(FILAS, ARISTAS, PARES, n_fondo=n_fondo)
        filas = [fila_gen(locus, simbolo) for locus, simbolo in GENES]
        filas += [fila_gen("PA%04d" % (3000 + i), "zzz%04d" % i)
                  for i in range(5700 - len(filas))]
        escribir_genes_crudos(esc.genes, filas)
        return esc

    def test_los_otros_dos_guardianes_lo_dejan_pasar(self):
        """Primero se comprueba que el exploit es el exploit."""
        esc = self.escenario_copiado()
        try:
            mapa, info = O.cargar_diccionario(esc.genes)
            O.revisar_procedencia(info)        # no levanta: dice refseq
            self.assertGreaterEqual(info["entidades_utiles"],
                                    O.MINIMO_ENTIDADES_UTILES)
        finally:
            esc.limpiar()

    def test_y_el_de_sustancia_lo_mata_sin_escribir_nada(self):
        esc = self.escenario_copiado()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    O.main(["--oro", esc.oro, "--red", esc.red, "--pares",
                            esc.pares, "--genes", esc.genes, "--operones",
                            esc.operones, "--salida", esc.salida, "--resumen",
                            esc.resumen, "--predicciones", esc.predicciones])
            mensaje = str(cm.exception)
            self.assertIn("vocabulario", mensaje)
            self.assertIn("No escribo", mensaje)
            self.assertFalse(os.path.exists(esc.salida))
            self.assertFalse(os.path.exists(esc.resumen))
        finally:
            esc.limpiar()

    def test_la_fraccion_se_publica_siempre_aunque_no_dispare(self):
        """Es graduada: el número está aunque nadie salte."""
        esc = Escenario(FILAS, ARISTAS, PARES).correr()
        try:
            s = esc.json["sustancia_del_diccionario"]
            self.assertLess(s["fraccion_explicada_por_el_oro"],
                            O.UMBRAL_AVISO_CIRCULARIDAD)
            self.assertEqual(s["pares_distintos"], len(PARES) + 60)
            self.assertGreater(s["pares_fuera_del_vocabulario_del_oro"], 0)
            self.assertIn("Sustancia del diccionario", esc.impreso)
        finally:
            esc.limpiar()

    def test_la_contaminacion_parcial_avisa_y_baja_el_codigo(self):
        """Un diccionario medio copiado tampoco vale, y no es todo o nada.

        El acierto de signo despega de las dos líneas base --las 20 filas
        salen con el signo correcto-- y aun así el informe sale con 2, porque
        la mitad de los pares que el pipeline propuso están dentro del
        vocabulario del propio patrón.
        """
        esc = escenario_que_despega(n_fondo=20)
        try:
            s = esc.json["sustancia_del_diccionario"]
            self.assertGreaterEqual(s["fraccion_explicada_por_el_oro"],
                                    O.UMBRAL_AVISO_CIRCULARIDAD)
            self.assertLess(s["fraccion_explicada_por_el_oro"],
                            O.UMBRAL_CIRCULARIDAD)
            v = esc.json["veredicto_del_signo"]
            self.assertTrue(v["despega_de_las_dos_lineas_base"])
            self.assertTrue(v["vocabulario_contaminado"])
            self.assertEqual(esc.codigo, 2)
            self.assertIn("vocabulario del propio patron",
                          esc.impreso.replace("ó", "o"))
            self.assertTrue(any("dos extremos dentro del vocabulario" in a
                                for a in esc.json["avisos"]))
        finally:
            esc.limpiar()

    def test_el_vocabulario_recoge_alias_operones_y_rangos(self):
        oro = [fila_oro("MexR", "mexAB-oprM",
                        alias="MexR = NalB = PA0424; "
                              "mexAB-oprM = PA0425-PA0427")]
        vocab = O.vocabulario_del_oro(oro)
        for nombre in ("mexr", "nalb", "pa0424", "mexab-oprm", "mexa", "mexb",
                       "oprm", "pa0425", "pa0426", "pa0427"):
            self.assertIn(nombre, vocab)

    def test_el_guardian_no_salta_con_el_escenario_normal(self):
        """Un guardián que salta siempre es tan inútil como uno que no salta."""
        esc = escenario_que_despega()
        try:
            self.assertEqual(esc.codigo, 0)
            self.assertFalse(
                esc.json["veredicto_del_signo"]["vocabulario_contaminado"])
        finally:
            esc.limpiar()


# ---------------------------------------------------------------------------
# Las cuatro probabilidades tienen que sumar 1
# ---------------------------------------------------------------------------

def fila_prediccion(id_par, pmid, tf, target, prediccion, probs=None):
    fila = {"id_par": id_par, "pmid": pmid, "tf": tf, "target": target,
            "prediccion": prediccion, "seccion": "results",
            "fuente": "fulltext", "autorregulacion": False,
            "redaccion": "directa"}
    if probs is None:
        probs = dict((e, 0.01) for e in S.ETIQUETAS)
        probs[prediccion] = 0.97
    for e in S.ETIQUETAS:
        fila["p_%s" % e] = probs[e]
    return fila


class PruebasProbabilidades(unittest.TestCase):
    """La invariante de la seccion 4, fuera de clasificar.py.

    Vivía solo ahí, que es el único archivo que necesita torch y por tanto el
    que menos gente corre. Medido: 65216 filas con las cuatro clases a 0.99
    (suman 3.96) producían 9608 aristas con confianza 0.9900 y EXHAUSTIVIDAD
    95.1 % con código 0, sin que nada mirara los números.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ruta = os.path.join(self.dir, "predicciones.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def escribir(self, filas):
        escribir_jsonl(self.ruta, filas)
        return self.ruta

    def test_las_cuatro_a_099_no_pasan(self):
        ruta = self.escribir([fila_prediccion(
            "id1", 1, "MexT", "mexE", "activates",
            dict((e, 0.99) for e in S.ETIQUETAS))])
        with self.assertRaises(SystemExit) as cm:
            O.revisar_probabilidades(ruta)
        self.assertIn("no suman 1", str(cm.exception))
        self.assertIn("3.96", str(cm.exception))

    def test_la_etiqueta_tiene_que_ser_la_de_mayor_probabilidad(self):
        probs = {"activates": 0.1, "no_relation": 0.6, "regulates": 0.15,
                 "represses": 0.15}
        ruta = self.escribir([fila_prediccion("id1", 1, "MexT", "mexE",
                                              "activates", probs)])
        with self.assertRaises(SystemExit) as cm:
            O.revisar_probabilidades(ruta)
        self.assertIn("mayor probabilidad", str(cm.exception))

    def test_un_archivo_bueno_pasa_y_deja_su_medida(self):
        ruta = self.escribir([fila_prediccion("id1", 1, "MexT", "mexE",
                                              "activates")])
        info = O.revisar_probabilidades(ruta)
        self.assertEqual(info["filas"], 1)
        self.assertLess(info["desviacion_maxima_de_la_suma"],
                        O.TOLERANCIA_SOFTMAX)

    def test_evaluar_oro_lo_comprueba_y_no_escribe(self):
        esc = Escenario(FILAS, ARISTAS, PARES)
        try:
            escribir_jsonl(esc.predicciones, [fila_prediccion(
                "id1", 1, "MexT", "mexE", "activates",
                dict((e, 0.99) for e in S.ETIQUETAS))])
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    O.main(["--oro", esc.oro, "--red", esc.red, "--pares",
                            esc.pares, "--genes", esc.genes, "--operones",
                            esc.operones, "--salida", esc.salida, "--resumen",
                            esc.resumen, "--predicciones", esc.predicciones])
            self.assertIn("no suman 1", str(cm.exception))
            self.assertFalse(os.path.exists(esc.salida))
        finally:
            esc.limpiar()

    def test_evaluar_oro_avisa_cuando_no_pudo_comprobarlo(self):
        """Callarse que la comprobación no se hizo es lo mismo que no hacerla."""
        esc = Escenario(FILAS, ARISTAS, PARES).correr()
        try:
            avisos = " ".join(esc.json["avisos"])
            self.assertIn("NO comprobe", avisos.replace("é", "e"))
            self.assertIn("no se hizo",
                          esc.json["entradas"]["comprobacion_de_probabilidades"])
        finally:
            esc.limpiar()

    def test_evaluar_signo_lo_comprueba_igual(self):
        auditoria = corpus_auditoria()
        respuestas = respuestas_por_redaccion(
            auditoria, {"directa": "represses",
                        "fenotipo_mutante": "represses"})
        esc = EscenarioSigno(auditoria, respuestas)
        try:
            # Se rompe el archivo que el escenario ya escribió: las cuatro
            # clases a 0.99 en la primera fila.
            with io.open(esc.predicciones, encoding="utf-8") as f:
                lineas = f.read().split("\n")
            primera = json.loads(lineas[0])
            for e in S.ETIQUETAS:
                primera["p_%s" % e] = 0.99
            lineas[0] = json.dumps(primera, ensure_ascii=False)
            with io.open(esc.predicciones, "w", encoding="utf-8",
                         newline="\n") as f:
                f.write("\n".join(lineas))
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    S.main(["--auditoria", esc.auditoria, "--predicciones",
                            esc.predicciones, "--pares", esc.pares,
                            "--salida", esc.salida, "--resumen", esc.resumen,
                            "--red-informe", os.path.join(esc.dir, "no.json"),
                            "--operones", esc.operones])
            self.assertIn("no suman 1", str(cm.exception))
            self.assertFalse(os.path.exists(esc.salida))
        finally:
            esc.limpiar()

    def test_la_invariante_esta_escrita_una_sola_vez(self):
        """Dos copias de la misma invariante divergen; ya pasó en este repo."""
        self.assertIs(S.revisar_probabilidades_de_fila,
                      O.revisar_probabilidades_de_fila)


# ---------------------------------------------------------------------------
# El codigo de salida de evaluar_signo.py
# ---------------------------------------------------------------------------

class PruebasVeredictoDelSigno(unittest.TestCase):
    """Los dos scripts no pueden salir con 0 diciendo cosas incompatibles.

    Este archivo era el único que cazaba al clasificador constante --publicaba
    EXACTITUD 0.0 % de 93-- y aun así salía con código 0, mientras
    `evaluar_oro.py` decía 69.8 % y "se distingue del azar" sobre las mismas
    predicciones.
    """

    def correr(self, evaluables, no_evaluables):
        auditoria = corpus_auditoria()
        respuestas = respuestas_por_redaccion(
            auditoria, {"directa": evaluables,
                        "fenotipo_mutante": evaluables},
            no_evaluables=no_evaluables)
        return EscenarioSigno(auditoria, respuestas).correr()

    def test_el_constante_que_falla_todo_no_sale_con_cero(self):
        esc = self.correr("activates", "activates")
        try:
            self.assertEqual(esc.json["global"]["exactitud"]["n"], 0)
            self.assertEqual(esc.codigo, 2)
            self.assertIn("NO HAY RESULTADO", esc.impreso)
        finally:
            esc.limpiar()

    def test_el_constante_que_acierta_todo_tampoco(self):
        """100 % de exactitud y aun así no es un resultado.

        Las 93 son todas `represses`: contestar siempre `represses` las
        acierta enteras sin leer nada. Lo que lo delata es que el modelo
        contesta esa misma clase en las 105 co-menciones, donde la auditoría
        no ve ninguna relación afirmada.
        """
        esc = self.correr("represses", "represses")
        try:
            self.assertEqual(esc.json["global"]["exactitud"]["tasa"], 1.0)
            self.assertEqual(esc.json["veredicto"]["tasa_base"], 1.0)
            self.assertEqual(esc.codigo, 2)
        finally:
            esc.limpiar()

    def test_un_modelo_que_distingue_si_despega(self):
        esc = self.correr("represses", "no_relation")
        try:
            self.assertEqual(esc.json["global"]["exactitud"]["tasa"], 1.0)
            self.assertEqual(esc.json["veredicto"]["tasa_base"], 0.0)
            self.assertLessEqual(esc.json["veredicto"]["p_valor"], S.ALFA)
            self.assertEqual(esc.codigo, 0)
            self.assertIn("despega de la linea base", esc.impreso)
        finally:
            esc.limpiar()

    def test_sin_predicciones_fuera_no_se_puede_estimar_la_tasa(self):
        esc = self.correr("represses", None)
        try:
            self.assertIsNone(esc.json["veredicto"]["p_valor"])
            self.assertEqual(esc.codigo, 2)
            self.assertIn("no hay ninguna prediccion fuera", esc.impreso)
        finally:
            esc.limpiar()

    def test_la_linea_base_se_imprime_y_viaja_en_el_json(self):
        esc = self.correr("represses", "no_relation")
        try:
            b = esc.json["linea_base_sin_informacion"]
            self.assertEqual(b["filas_unidas"], 93)
            self.assertEqual(b["predicciones_fuera_de_la_auditoria"], 105)
            self.assertEqual(b["reparto_fuera_de_la_auditoria"],
                             {"no_relation": 105})
            self.assertIn("linea base sin informacion", esc.impreso)
            texto = esc.json["veredicto"]["que_significa_el_codigo_de_salida"]
            self.assertIn("0 =", texto)
            self.assertIn("2 =", texto)
        finally:
            esc.limpiar()

    def test_las_filas_evaluadas_no_entran_en_su_propia_tasa_base(self):
        """Si entraran, el constante se estaría comparando consigo mismo."""
        esc = self.correr("represses", "no_relation")
        try:
            b = esc.json["linea_base_sin_informacion"]
            self.assertNotIn("represses", b["reparto_fuera_de_la_auditoria"])
        finally:
            esc.limpiar()


if __name__ == "__main__":
    unittest.main()
