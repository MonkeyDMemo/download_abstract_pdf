# -*- coding: utf-8 -*-
"""Pruebas del generador de pares candidatos.

Las que no pueden faltar, y por que:

- **El marcado tiene que ser byte a byte el del entrenamiento.** Los
  marcadores no son tokens especiales --no hay `add_tokens` ni
  `resize_token_embeddings` en `bio_bert_re_finetune.py`--, asi que se parten
  en piezas de wordpiece. Con `>` pegado al nombre las piezas son otras y el
  modelo nunca vio eso: la inferencia se degrada en silencio, sin que nada
  falle. Por eso la prueba compara contra lineas literales de
  `entity_marked_train.jsonl` y no contra una cadena escrita a mano.
- **Una mencion corta no puede casar dentro de una larga.** `mexA` dentro de
  `mexAB-oprM` contaria dos veces la misma mencion y fabricaria el par
  `MexR -> mexA` donde el articulo hablaba de la bomba entera.
- **El par X -> x SI se emite, marcado.** La seccion 3.4 manda sobre la 3.2
  regla 5. Quien lo excluye es `red.py`. Descartarlo aqui hacia que las 10
  filas autorregulatorias del oro salieran con veredicto
  `no_recuperada_sin_candidato`, que afirma que los dos extremos nunca
  coocurrieron: falso, hay 1228 oraciones en 300 de los 918 textos donde un TF
  aparece dos o mas veces.
- **Dos menciones con el mismo tramo no forman par.**
- **Ninguna prueba puede pasar pase lo que pase.** Dos de las que habia lo
  hacian: la de METHODS solo assertaba constantes y nunca llamaba a la funcion
  que filtra, asi que neutralizar el filtro dejaba la suite en verde. Las de
  aqui corren `piezas_de_documento()` y `main()` sobre un documento que TIENE
  seccion de metodos.
- **Lo que generamos tiene que parecerse a lo que el modelo vio.** Por eso las
  1249 filas reales del entrenamiento se despojan de sus marcadores y se
  vuelven a pasar por `pretokenizar()`: cada diferencia es una forma que el
  modelo no vio nunca.

    python -m unittest discover etapa2
"""

import collections
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extraer_pares as E
import lexico as L
from grn_bronce import texto as T

AQUI = os.path.dirname(os.path.abspath(__file__))
ENTRENAMIENTO = os.path.join(AQUI, "para_colab", "entity_marked_train.jsonl")

COLUMNAS_GENES = "\t".join(L.COLUMNAS_GENES)
COLUMNAS_OPERONES = "\t".join(L.COLUMNAS_OPERONES)

# (locus_tag, simbolo, alias, tipo, producto, es_tf, fuente_tf, fuente,
#  sensible_mayusculas)
GENES = [
    ("PA0424", "mexR", "PA0424", "protein_coding", "repressor MexR",
     "true", "go_0003700", "refseq", "false"),
    ("PA0425", "mexA", "", "protein_coding", "RND membrane fusion protein",
     "false", "", "refseq", "false"),
    ("PA0426", "mexB", "", "protein_coding", "RND transporter",
     "false", "", "refseq", "false"),
    ("PA0427", "oprM", "", "protein_coding", "outer membrane protein",
     "false", "", "refseq", "false"),
    ("PA2492", "mexT", "PA2492", "protein_coding",
     "transcriptional regulator MexT", "true",
     "go_0003700|producto_refseq", "refseq|kegg", "false"),
    ("PA2493", "mexE", "", "protein_coding", "RND membrane fusion protein",
     "false", "", "refseq", "false"),
    ("PA2494", "mexF", "", "protein_coding", "RND transporter",
     "false", "", "refseq", "false"),
    ("PA2495", "oprN", "", "protein_coding", "outer membrane protein",
     "false", "", "refseq", "false"),
    ("PA3574", "nalD", "PA3574", "protein_coding", "TetR family repressor",
     "true", "go_0003700", "refseq", "false"),
    ("PA0996", "pqsA", "", "protein_coding", "anthranilate-CoA ligase",
     "false", "", "refseq", "false"),
    ("PA0997", "pqsB", "", "protein_coding", "PqsB", "false", "", "refseq",
     "false"),
    ("PA0998", "pqsC", "", "protein_coding", "PqsC", "false", "", "refseq",
     "false"),
    ("PA0999", "pqsD", "", "protein_coding", "PqsD", "false", "", "refseq",
     "false"),
    ("PA1000", "pqsE", "", "protein_coding", "PqsE", "false", "", "refseq",
     "false"),
    ("PA5360", "phoB", "PA5360", "protein_coding", "response regulator PhoB",
     "true", "kw_two_component", "refseq", "false"),
    ("PA5361", "phoR", "", "protein_coding", "sensor histidine kinase PhoR",
     "false", "", "refseq", "false"),
    ("PA4109", "cat", "", "protein_coding", "chloramphenicol acetyltransferase",
     "false", "", "refseq", "true"),
]

# (operon, miembros, locus_tags, fuente)
OPERONES = [
    ("mexAB", "mexA|mexB", "PA0425|PA0426", "refseq_adyacencia"),
    ("mexAB-oprM", "mexA|mexB|oprM", "PA0425|PA0426|PA0427",
     "refseq_adyacencia"),
    ("mexEF", "mexE|mexF", "PA2493|PA2494", "refseq_adyacencia"),
    ("mexEF-oprN", "mexE|mexF|oprN", "PA2493|PA2494|PA2495",
     "refseq_adyacencia"),
    ("pqsABCDE", "pqsA|pqsB|pqsC|pqsD|pqsE",
     "PA0996|PA0997|PA0998|PA0999|PA1000", "refseq_adyacencia"),
    ("phoBR", "phoB|phoR", "PA5360|PA5361", "refseq_adyacencia"),
]


def desmarcar(marcado):
    """Marcado -> (texto desnudo, span de e1, span de e2).

    Se procesan los marcadores de izquierda a derecha: al quitar un par, los
    tramos que ya se anotaron quedan a su izquierda y no se mueven.
    """
    salida, spans = marcado, {}
    while True:
        m = re.search(r"<e([12])> ", salida)
        if not m:
            break
        etiqueta, ini = m.group(1), m.start()
        salida = salida[:ini] + salida[m.end():]
        cierre = " </e%s>" % etiqueta
        fin = salida.index(cierre, ini)
        salida = salida[:fin] + salida[fin + len(cierre):]
        spans[etiqueta] = (ini, fin)
    return salida, spans["1"], spans["2"]


class Base(unittest.TestCase):
    """Diccionario de juguete en disco, con la forma exacta del contrato."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.ruta_genes = os.path.join(cls.dir, "genes.tsv")
        cls.ruta_operones = os.path.join(cls.dir, "operones.tsv")
        with io.open(cls.ruta_genes, "w", encoding="utf-8", newline="") as f:
            f.write(COLUMNAS_GENES + u"\n")
            for fila in GENES:
                f.write(u"\t".join(fila) + u"\n")
        with io.open(cls.ruta_operones, "w", encoding="utf-8",
                     newline="") as f:
            f.write(COLUMNAS_OPERONES + u"\n")
            for fila in OPERONES:
                f.write(u"\t".join(fila) + u"\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.lex = L.Lexico.cargar(self.ruta_genes, self.ruta_operones)
        self.cuenta = collections.Counter()

    def pares(self, oracion, seccion="results", fuente="fulltext",
              n_oracion=0, pmid="19846594", max_menciones=8):
        crudos = E.candidatos_de_oracion(
            pmid, seccion, fuente, n_oracion, T.normalizar_espacios(oracion),
            self.lex, max_menciones, self.cuenta)
        return [fila for fila, _ in crudos]


class PruebasMarcado(Base):
    """El formato del texto marcado, contra el dato y no contra la memoria."""

    def test_marcar_reproduce_lineas_literales_del_entrenamiento(self):
        """Se toman lineas reales, se les quitan los marcadores y se vuelven a
        poner. Si `marcar()` cambia un solo espacio, esto falla.

        `etapa2/README.md` lineas ~181-188 dibuja el ejemplo SIN espacios
        dentro de la etiqueta. Es incorrecto respecto al dato: el contenido
        entre `<e1>` y `</e1>` empieza y termina con exactamente un espacio en
        1563 de 1563 ocurrencias.
        """
        self.assertTrue(os.path.isfile(ENTRENAMIENTO), ENTRENAMIENTO)
        with io.open(ENTRENAMIENTO, encoding="utf-8") as f:
            filas = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(filas), 1249)
        for fila in filas:
            desnudo, e1, e2 = desmarcar(fila["text"])
            self.assertEqual(T.marcar(desnudo, e1, e2), fila["text"])

    def test_e1_es_un_rol_y_no_una_posicion(self):
        """El gen va antes que el TF en el 38.6 % de los casos y el marcado no
        se reordena. Si `marcar()` asignara e1/e2 por posicion, el par (A,B) y
        el par (B,A) dejarian de ser dos entradas distintas."""
        with io.open(ENTRENAMIENTO, encoding="utf-8") as f:
            filas = [json.loads(l) for l in f if l.strip()]
        invertidas = [d for d in filas
                      if d["text"].index("<e2>") < d["text"].index("<e1>")]
        self.assertGreater(len(invertidas), 400)
        for fila in invertidas[:50]:
            desnudo, e1, e2 = desmarcar(fila["text"])
            self.assertGreater(e1[0], e2[0])
            self.assertEqual(T.marcar(desnudo, e1, e2), fila["text"])

    def test_las_menciones_marcadas_son_las_que_dicen_los_campos(self):
        with io.open(ENTRENAMIENTO, encoding="utf-8") as f:
            filas = [json.loads(l) for l in f if l.strip()]
        for fila in filas:
            marcadas = dict(E.MARCADO.findall(fila["text"]))
            self.assertEqual(marcadas["1"], fila["tf"])
            self.assertEqual(marcadas["2"], fila["target"])

    def test_el_ejemplo_del_contrato_sale_igual(self):
        """La linea del PMID 19846594 de la seccion 3 del contrato, generada
        de punta a punta desde la oracion cruda."""
        cruda = ("The expression of mexEF-oprN is activated by a LysR-type "
                 "transcriptional regulator (LTTR) MexT, which is encoded by "
                 "a gene located just upstream of mexEF-oprN in the same "
                 "orientation in P. aeruginosa.")
        esperado = ("The expression of mexEF-oprN is activated by a LysR - "
                    "type transcriptional regulator ( LTTR ) <e1> MexT </e1> "
                    ", which is encoded by a gene located just upstream of "
                    "<e2> mexEF-oprN </e2> in the same orientation in P . "
                    "aeruginosa .")
        filas = self.pares(cruda, seccion="introduction", n_oracion=37)
        fila = [f for f in filas if f["target"] == "mexEF-oprN"]
        self.assertEqual(len(fila), 1)
        fila = fila[0]
        self.assertEqual(fila["text"], esperado)
        self.assertEqual(fila["tf"], "MexT")
        self.assertEqual(fila["pos_tf"], 90)
        self.assertEqual(fila["pos_target"], 148)
        self.assertEqual(fila["distancia"], 54)
        self.assertEqual(fila["seccion"], "introduction")
        self.assertEqual(fila["n_oracion"], 37)
        self.assertEqual(fila["label"], "")
        self.assertIsInstance(fila["pmid"], int)
        self.assertEqual(list(fila.keys()), E.CLAVES)

    def test_el_texto_marcado_casa_dos_veces_con_la_regex_del_contrato(self):
        oracion = ("MexR represses the expression of mexAB-oprM in "
                   "Pseudomonas aeruginosa PAO1 under standard conditions.")
        filas = self.pares(oracion)
        self.assertTrue(filas)
        for fila in filas:
            encontrados = E.MARCADO.findall(fila["text"])
            self.assertEqual(sorted(e[0] for e in encontrados), ["1", "2"])

    def test_la_superficie_literal_no_se_reescribe(self):
        """`tf` lleva la forma canonica, pero `text` marca la superficie tal
        como el articulo la escribio. Reescribir `mexT` a `MexT` dentro de la
        oracion fabricaria una frase que nadie publico."""
        oracion = ("Transcription of mexEF-oprN requires mexT, the gene "
                   "encoding the LysR-type activator of this operon.")
        fila = [f for f in self.pares(oracion)
                if f["target"] == "mexEF-oprN"][0]
        self.assertEqual(fila["tf"], "MexT")
        self.assertEqual(fila["mencion_tf"], "mexT")
        self.assertIn("<e1> mexT </e1>", fila["text"])
        self.assertNotIn("<e1> MexT </e1>", fila["text"])


class PruebasMenciones(Base):

    def test_una_mencion_corta_no_casa_dentro_de_una_larga(self):
        """`mexA` dentro de `mexAB-oprM`. El operon entero gana porque el
        token completo se consulta antes que sus segmentos."""
        oracion = ("MexR represses the expression of mexAB-oprM in "
                   "Pseudomonas aeruginosa under standard laboratory "
                   "conditions.")
        blancos = set(f["target"] for f in self.pares(oracion))
        self.assertEqual(blancos, set(["mexAB-oprM"]))
        self.assertNotIn("mexA", blancos)
        self.assertNotIn("mexB", blancos)
        self.assertNotIn("oprM", blancos)

    def test_el_segundo_elemento_del_compuesto_es_visible(self):
        """El lookbehind `(?<![A-Za-z0-9-])` de `auditar_signo.py:140` incluia
        el guion, asi que el segundo elemento de todo compuesto era invisible:
        medidas 262 ocurrencias en 60 documentos."""
        menciones = self.lex.menciones("The mexT-oprN fusion was assayed .")
        ids = [m[3] for m in menciones]
        self.assertIn("mexT", ids)
        self.assertIn("oprN", ids)

    def test_el_operon_concatenado_se_reconoce(self):
        oracion = ("MexT activates transcription of pqsABCDE and of the "
                   "downstream genes in Pseudomonas aeruginosa PAO1 cells.")
        blancos = set(f["target"] for f in self.pares(oracion))
        self.assertIn("pqsABCDE", blancos)

    def test_la_letra_griega_no_esconde_la_mencion(self):
        """Medido: 1039 `Delta` griegas contra 4 escritas como palabra en 60
        documentos."""
        menciones = self.lex.menciones(u"The ΔmexT mutant was tested .")
        self.assertEqual([m[3] for m in menciones], ["mexT"])
        menciones = self.lex.menciones("The DeltamexT mutant was tested .")
        self.assertEqual([m[3] for m in menciones], ["mexT"])

    def test_la_sensibilidad_a_mayusculas_es_por_fila(self):
        """`cat` es palabra inglesa antes que gen. Medido en 60 documentos,
        insensible contra sensible: `cat` 38 vs 2, `his` 47 vs 3, `fur` 32 vs
        13. La diferencia son falsos positivos puros.

        Sensible quiere decir que solo casa la superficie tal como la escribio
        el diccionario, o sea `cat` y no `Cat` ni `CAT`. La forma de proteina
        NO se sintetiza: registrarla devolveria `Cat` y `His` al conjunto de
        aciertos, que es justo lo que este campo existe para evitar."""
        self.assertEqual([m[3] for m in self.lex.menciones("the cat gene")],
                         ["cat"])
        self.assertEqual(self.lex.menciones("the CAT assay was linear"), [])
        self.assertEqual(self.lex.menciones("the Cat sat on the mat"), [])
        # mexT no es sensible: se reconoce como lo escriba el articulo.
        self.assertEqual([m[3] for m in self.lex.menciones("MEXT and MexT")],
                         ["mexT", "mexT"])


class PruebasVentana(Base):
    """La ventana respeta los limites medidos."""

    def test_los_limites_son_los_medidos(self):
        self.assertEqual(E.MIN_ORACION, 40)
        self.assertEqual(E.MAX_ORACION, 700)
        self.assertEqual(E.MAX_TEXTO, 900)

    def test_las_oraciones_fuera_de_rango_se_descartan(self):
        corta = "MexT activates mexEF-oprN."
        self.assertLess(len(corta), E.MIN_ORACION)
        larga = ("MexT activates mexEF-oprN and " + "abc def " * 90
                 + "finally mexAB-oprM.")
        self.assertGreater(len(larga), E.MAX_ORACION)
        media = ("MexT activates the expression of mexEF-oprN in "
                 "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        cuenta = collections.Counter()
        filas = E.candidatos_de_documento(
            "1",
            [("results", corta + "\n\n" + larga + "\n\n" + media, "fulltext")],
            self.lex, 8, cuenta)
        self.assertEqual(cuenta["oraciones_cortas"], 1)
        self.assertEqual(cuenta["oraciones_largas"], 1)
        self.assertEqual(cuenta["oraciones_examinadas"], 1)
        self.assertTrue(filas)
        # La unica oracion conservada es la primera del documento.
        for fila, _ in filas:
            self.assertEqual(fila["n_oracion"], 0)

    def test_ningun_texto_marcado_rebasa_la_ventana_segura(self):
        """Una oracion de 700 caracteres muy cargada de puntuacion crece hasta
        casi el doble al pretokenizar. Se descarta el par antes de escribirlo,
        no se aborta la corrida ni se emite una fila que la invariante del
        contrato rechazaria."""
        relleno = "(x)" * 220
        oracion = "MexT activates " + relleno + " mexEF-oprN."
        self.assertLessEqual(len(oracion), E.MAX_ORACION)
        filas = self.pares(oracion)
        self.assertEqual(filas, [])
        self.assertEqual(self.cuenta["pares_texto_largo"], 1)

    def test_las_oraciones_con_demasiadas_menciones_se_descartan(self):
        """Hay parrafos con 40 genes distintos (780 pares posibles). Una lista
        enumerativa no afirma nada."""
        oracion = ("Genes assayed here: mexT, mexA, mexB, oprM, mexE, mexF, "
                   "oprN, nalD, phoB, phoR, pqsA and cat were all measured.")
        self.assertEqual(self.pares(oracion, max_menciones=8), [])
        self.assertEqual(self.cuenta["oraciones_demasiadas_menciones"], 1)
        self.assertTrue(self.pares(oracion, max_menciones=40))


class PruebasPares(Base):

    def test_una_sola_entrada_por_oracion_y_par(self):
        """`no_relation` no significa "este TF no regula este gen", sino "esta
        ocurrencia concreta no es la que el anotador eligio": 485 de las 493
        filas negativas del entrenamiento comparten ventana Y par con una
        positiva. Marcar todas las combinaciones produciria masivamente
        entradas con la forma que el modelo aprendio a llamar `no_relation`."""
        oracion = ("MexT binds the mexEF-oprN promoter, and MexT then "
                   "activates mexEF-oprN transcription in PAO1 cells.")
        filas = self.pares(oracion)
        claves = [(f["tf"], f["target"]) for f in filas]
        self.assertEqual(len(claves), len(set(claves)))

    def test_se_eligen_las_ocurrencias_de_minima_distancia(self):
        oracion = ("The mexEF-oprN operon is well studied, and many groups "
                   "have shown that MexT activates mexEF-oprN strongly.")
        fila = [f for f in self.pares(oracion)
                if f["target"] == "mexEF-oprN"][0]
        segunda = oracion.rindex("mexEF-oprN")
        self.assertEqual(fila["pos_target"], segunda)
        self.assertEqual(
            fila["distancia"],
            segunda - (oracion.index("MexT") + len("MexT")))

    def test_los_empates_se_rompen_de_forma_determinista(self):
        ocs_tf = [(10, 14, "MexT", True), (30, 34, "MexT", True)]
        ocs_tg = [(20, 24, "mexE", False)]
        a, b, d = E.elegir_ocurrencias(ocs_tf, ocs_tg)
        self.assertEqual(d, 6)
        self.assertEqual(a[0], 10)   # empate en distancia -> menor pos_tf

    def test_el_par_se_emite_en_los_dos_sentidos_cuando_ambos_son_tf(self):
        """El par (A,B) y el par (B,A) son dos entradas distintas."""
        oracion = ("In this strain MexT represses nalD, whereas nalD has no "
                   "measurable effect on the level of MexT protein.")
        claves = set((f["tf"], f["target"]) for f in self.pares(oracion))
        self.assertIn(("MexT", "nalD"), claves)
        self.assertIn(("NalD", "mexT"), claves)

    def test_target_es_tf_se_propaga(self):
        oracion = ("In this strain MexT represses nalD, whereas nalD has no "
                   "measurable effect on the level of MexT protein.")
        fila = [f for f in self.pares(oracion) if f["target"] == "nalD"][0]
        self.assertTrue(fila["target_es_tf"])

    def test_el_id_par_es_determinista_y_depende_de_la_clave(self):
        oracion = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        a = self.pares(oracion, n_oracion=3)[0]
        b = self.pares(oracion, n_oracion=3)[0]
        c = self.pares(oracion, n_oracion=4)[0]
        self.assertEqual(a["id_par"], b["id_par"])
        self.assertNotEqual(a["id_par"], c["id_par"])
        self.assertEqual(len(a["id_par"]), 16)


class PruebasSpanCompartido(Base):
    """Dos menciones con el mismo tramo no forman par."""

    def test_elegir_ocurrencias_rechaza_el_tramo_compartido(self):
        misma = [(10, 14, "MexT", True)]
        self.assertIsNone(E.elegir_ocurrencias(misma, list(misma)))

    def test_elegir_ocurrencias_salta_la_combinacion_y_usa_otra(self):
        ocs_tf = [(10, 14, "MexT", True)]
        ocs_tg = [(10, 14, "MexT", True), (40, 44, "mexE", False)]
        a, b, d = E.elegir_ocurrencias(ocs_tf, ocs_tg)
        self.assertEqual(b[0], 40)

    def test_marcar_rechaza_el_mismo_tramo(self):
        self.assertRaises(ValueError, T.marcar, "MexT activates mexE .",
                          (0, 4), (0, 4))


class PruebasAutorregulacion(Base):

    def test_el_par_de_la_misma_entidad_se_emite_marcado(self):
        """La seccion 3.4 manda sobre la 3.2 regla 5: `X -> x` se EMITE con
        `autorregulacion: true` y quien lo excluye es `red.py`.

        Descartarlo aqui hacia que las 10 filas autorregulatorias del oro
        (MexR->mexR, MexZ->mexZ, NfxB->nfxB, AlgU->algU...) salieran con
        veredicto `no_recuperada_sin_candidato`, que declara que los dos
        extremos nunca coocurrieron en una oracion. Era falso: hay 1228
        oraciones en 300 de los 918 textos donde un TF aparece dos o mas
        veces."""
        oracion = (u"In the ΔnalD mutant, nalD expression was measured "
                   u"and found to be strongly increased over the wild type.")
        menciones = self.lex.menciones(T.normalizar_espacios(oracion))
        self.assertEqual([m[3] for m in menciones], ["nalD", "nalD"])
        self.assertNotEqual(menciones[0][:2], menciones[1][:2])

        filas = self.pares(oracion)
        self.assertEqual([(f["tf"], f["target"]) for f in filas],
                         [("NalD", "nalD")])
        self.assertTrue(filas[0]["autorregulacion"])
        self.assertTrue(filas[0]["target_es_tf"])
        # Las dos ocurrencias marcadas son tramos distintos de la oracion.
        self.assertNotEqual(filas[0]["pos_tf"], filas[0]["pos_target"])
        self.assertEqual(
            self.cuenta["pares_autorregulacion_antes_del_tope"], 1)
        self.assertEqual(self.cuenta["oraciones_sin_par"], 0)

    def test_una_sola_ocurrencia_del_tf_no_da_par_autorregulatorio(self):
        """La proteccion que queda en la extraccion es exigir DOS ocurrencias
        distintas: un TF nombrado una vez no se regula a si mismo por el hecho
        de aparecer."""
        oracion = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        filas = self.pares(oracion)
        self.assertNotIn(("MexT", "mexT"),
                         [(f["tf"], f["target"]) for f in filas])
        self.assertEqual(self.cuenta["autorregulacion_sin_segunda_ocurrencia"],
                         1)
        self.assertEqual(
            self.cuenta["pares_autorregulacion_antes_del_tope"], 0)

    def test_el_contador_de_autorregulacion_no_cuenta_combinaciones(self):
        """El contador anterior, `pares_misma_entidad`, subia una vez por cada
        (oracion, TF) porque el TF siempre se encuentra a si mismo, y el
        informe lo imprimia como si fueran candidatos autorregulatorios
        descartados: 18185 de ellos en una corrida real. Aqui hay dos TFs
        nombrados una vez cada uno, o sea CERO candidatos autorregulatorios y
        dos huecos por falta de segunda ocurrencia."""
        oracion = ("MexT and NalD both act on mexAB-oprM in Pseudomonas "
                   "aeruginosa PAO1 grown in rich medium.")
        filas = self.pares(oracion)
        self.assertTrue(filas)
        self.assertEqual(
            self.cuenta["pares_autorregulacion_antes_del_tope"], 0)
        self.assertEqual(self.cuenta["autorregulacion_sin_segunda_ocurrencia"],
                         2)
        self.assertNotIn("pares_misma_entidad", self.cuenta)

    def test_la_autorregulacion_convive_con_los_demas_pares(self):
        con_tercero = (u"In the ΔnalD mutant, nalD and mexAB-oprM expression "
                       u"were both strongly increased over the wild type.")
        filas = self.pares(con_tercero)
        self.assertEqual(set((f["tf"], f["target"]) for f in filas),
                         set([("NalD", "nalD"), ("NalD", "mexAB-oprM")]))
        auto = dict(((f["tf"], f["target"]), f["autorregulacion"])
                    for f in filas)
        self.assertTrue(auto[("NalD", "nalD")])
        self.assertFalse(auto[("NalD", "mexAB-oprM")])

    def test_el_operon_que_contiene_al_propio_gen_se_marca(self):
        """`PhoB -> phoBR`: se emite, marcado, y `red.py` lo excluye salvo
        --incluir-autorregulacion."""
        oracion = ("Under phosphate starvation PhoB activates the phoBR "
                   "operon in Pseudomonas aeruginosa PAO1 cells.")
        fila = [f for f in self.pares(oracion) if f["target"] == "phoBR"][0]
        self.assertTrue(fila["autorregulacion"])

    def test_un_par_normal_no_queda_marcado_como_autorregulacion(self):
        oracion = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        fila = [f for f in self.pares(oracion)
                if f["target"] == "mexEF-oprN"][0]
        self.assertFalse(fila["autorregulacion"])


class PruebasRedaccion(Base):

    def test_el_fenotipo_del_mutante_se_reconoce_con_la_letra_griega(self):
        """Sintoma real: `PERDIDA.search("DeltamexR strain")` con la letra
        griega devolvia False, asi que las oraciones de fenotipo --que son casi
        todas las que hay-- se clasificaban como `otra` y se perdia justo la
        particion que la etapa 6 existe para medir."""
        oracion = (u"In the ΔmexT strain, mexEF-oprN expression was "
                   u"increased more than tenfold over the parental PAO1.")
        fila = [f for f in self.pares(oracion)
                if f["target"] == "mexEF-oprN"][0]
        self.assertEqual(fila["redaccion"], "fenotipo_mutante")

    def test_la_redaccion_directa_se_reconoce(self):
        oracion = ("MexR is a repressor of mexAB-oprM in Pseudomonas "
                   "aeruginosa and binds its promoter region directly.")
        fila = self.pares(oracion)[0]
        self.assertEqual(fila["redaccion"], "directa")

    def test_una_comencion_sin_verbo_cae_en_otra(self):
        oracion = ("Strains used in this work carried the mexT allele and a "
                   "chromosomal copy of mexEF-oprN from PAO1 stocks.")
        fila = self.pares(oracion)[0]
        self.assertEqual(fila["redaccion"], "otra")


class PruebasSecciones(Base):

    def test_el_encabezado_no_se_pega_a_la_primera_oracion(self):
        """Medido: `"## INTRODUCTION In the United States, pneumonia is..."`
        de 845 caracteres. Con reconocimiento insensible a mayusculas, un
        `### MEXT REGULATES MEXEF-OPRN` producia menciones validas y la
        "oracion de evidencia" era un titulo de subseccion."""
        md = ("# Titulo\n\n## RESULTS\n\n### MEXT REGULATES MEXEF-OPRN\n\n"
              "MexT activates the expression of mexEF-oprN in PAO1 cells.\n")
        clases = T.cargar_clases()
        secciones = T.secciones(md, clases)
        cuerpos = [c for clase, c in secciones if clase == "results"]
        self.assertEqual(len(cuerpos), 1)
        self.assertNotIn("MEXT REGULATES", cuerpos[0])
        self.assertNotIn("#", cuerpos[0])
        for oracion in T.oraciones(cuerpos[0]):
            self.assertFalse(oracion.startswith("MEXT"))

    METODOS = ("The coding regions of MexT, NalD and MexR were amplified by "
               "PCR and cloned upstream of mexEF-oprN in pUCP20.")
    RESULTADOS = ("MexT activates the expression of mexEF-oprN in "
                  "Pseudomonas aeruginosa PAO1 grown in rich medium.")

    def _documento_con_metodos(self, nombre="metodos.txt"):
        md = ("## RESULTS\n\n%s\n\n## MATERIALS AND METHODS\n\n%s\n\n"
              "## EXPERIMENTAL PROCEDURES\n\n%s\n"
              % (self.RESULTADOS, self.METODOS, self.METODOS))
        ruta = os.path.join(self.dir, nombre)
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(md)
        return ruta

    def test_los_metodos_no_entran(self):
        """Es el 19.6 % del corpus: prosa densa en nombres de gen que describe
        construccion de plasmidos y cepas, donde tres genes coocurren y no hay
        ninguna relacion que extraer.

        Esta prueba corre `piezas_de_documento()` sobre un documento que TIENE
        seccion de metodos. La version anterior solo assertaba constantes --que
        secciones.tsv mapea 'materials and methods' a 'excluir' y que 'excluir'
        no esta en SECCIONES_QUE_ENTRAN-- y nunca llamaba a la funcion que
        filtra: neutralizar el filtro dejaba las 281 pruebas en verde."""
        clases = T.cargar_clases()
        piezas = E.piezas_de_documento(
            "1", "", self._documento_con_metodos(), clases, False,
            collections.Counter())
        self.assertEqual([c for c, _, _ in piezas], ["results"])
        cuerpo = piezas[0][1]
        self.assertIn("MexT activates", cuerpo)
        self.assertNotIn("amplified by PCR", cuerpo)

    def test_ningun_par_sale_de_una_seccion_de_metodos(self):
        """El mismo filtro visto desde el otro extremo: los tres genes de la
        oracion de metodos coocurren y darian pares si la seccion entrara."""
        clases = T.cargar_clases()
        piezas = E.piezas_de_documento(
            "1", "", self._documento_con_metodos("metodos2.txt"), clases,
            False, collections.Counter())
        cuenta = collections.Counter()
        filas = E.candidatos_de_documento("1", piezas, self.lex, 8, cuenta)
        self.assertTrue(filas)
        for f, _ in filas:
            self.assertEqual(f["seccion"], "results")
            self.assertNotIn("PCR", f["oracion_cruda"])
        # Y para que no quepa duda de que la oracion de metodos SI produciria
        # pares si se colara: se le pasa suelta al mismo extractor.
        self.assertTrue(self.pares(self.METODOS, seccion="excluir"))

    def test_los_pies_de_figura_si_entran(self):
        """11.4 % del corpus y presentes en el 100 % de los documentos. Se
        quedan marcados aparte para que `red.py --sin-pies` pueda medirlos."""
        clases = T.cargar_clases()
        self.assertEqual(clases["pies de figura y tabla"], "pie_de_figura")
        md = ("## PIES DE FIGURA Y TABLA\n\n%s\n" % self.RESULTADOS)
        ruta = os.path.join(self.dir, "pies.txt")
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(md)
        piezas = E.piezas_de_documento("1", "", ruta, clases, False,
                                       collections.Counter())
        self.assertEqual([c for c, _, _ in piezas], ["pie_de_figura"])

    def test_la_seccion_desconocida_queda_fuera_por_omision(self):
        md = "## PERSPECTIVE\n\nMexT activates mexEF-oprN in PAO1 cells now.\n"
        desconocidas = collections.Counter()
        ruta = os.path.join(self.dir, "doc.txt")
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(md)
        clases = T.cargar_clases()
        piezas = E.piezas_de_documento(
            "1", "", ruta, clases, False, desconocidas)
        self.assertEqual(piezas, [])
        self.assertIn("perspective", desconocidas)
        piezas = E.piezas_de_documento(
            "1", "", ruta, clases, True, desconocidas)
        self.assertEqual([(c, f) for c, _, f in piezas],
                         [("otra", "fulltext")])

    def test_el_resumen_no_se_lee_dos_veces(self):
        """Medido: los primeros 120 caracteres de `documentos.abstract`
        aparecen literales dentro del `.txt` en 777 de 918 casos. Procesar las
        dos piezas hacia que cada arista de resumen contara doble su
        evidencia."""
        md = ("## ABSTRACT\n\nMexT activates mexEF-oprN in PAO1 cells here.\n"
              "\n## RESULTS\n\nMexT also represses nalD in the same cells.\n")
        ruta = os.path.join(self.dir, "doc2.txt")
        with io.open(ruta, "w", encoding="utf-8") as f:
            f.write(md)
        clases = T.cargar_clases()
        piezas = E.piezas_de_documento(
            "1", "MexT activates mexEF-oprN in PAO1 cells here.", ruta,
            clases, False, collections.Counter())
        self.assertEqual([c for c, _, _ in piezas], ["abstract", "results"])
        self.assertEqual(sum(1 for c, _, _ in piezas if c == "abstract"), 1)
        # Todas las piezas de un documento con .txt vienen del .txt. Es lo que
        # la invariante de la seccion 3.3 vigila, y por eso `fuente` viaja por
        # pieza: en cuanto una diga 'resumen', `verificar()` lo detecta.
        self.assertEqual(set(f for _, _, f in piezas), set(["fulltext"]))

    def test_el_resumen_de_la_base_solo_se_usa_sin_texto_completo(self):
        clases = T.cargar_clases()
        piezas = E.piezas_de_documento(
            "1", "MexT activates mexEF-oprN in PAO1 cells.", None, clases,
            False, collections.Counter())
        self.assertEqual([(c, f) for c, _, f in piezas],
                         [("abstract", "resumen")])

    def test_el_abstract_repetido_no_se_pierde(self):
        """`## ABSTRACT` aparece 1203 veces en 914 documentos porque los
        resumenes estructurados convirtieron cada subtitulo en otro bloque."""
        md = ("## ABSTRACT\n\nBackground here.\n\n## ABSTRACT\n\nMethods "
              "here.\n")
        clases = T.cargar_clases()
        self.assertEqual([c for c, _ in T.secciones(md, clases)],
                         ["abstract", "abstract"])

    def test_n_oracion_corre_a_lo_largo_del_documento(self):
        piezas = [
            ("abstract",
             "MexT activates mexEF-oprN in Pseudomonas aeruginosa PAO1 now.",
             "fulltext"),
            ("results",
             "MexR represses mexAB-oprM in Pseudomonas aeruginosa PAO1 too.",
             "fulltext"),
        ]
        cuenta = collections.Counter()
        filas = E.candidatos_de_documento("1", piezas, self.lex, 8, cuenta)
        indices = dict((f["seccion"], f["n_oracion"]) for f, _ in filas)
        self.assertEqual(indices["abstract"], 0)
        self.assertEqual(indices["results"], 1)


class PruebasTopeYVerificacion(Base):

    def _fila(self, oracion, pmid, n_oracion):
        return E.candidatos_de_oracion(
            pmid, "results", "fulltext", n_oracion,
            T.normalizar_espacios(oracion), self.lex, 8, self.cuenta)

    def test_el_tope_cuenta_oraciones_distintas_no_filas(self):
        """Defecto real de `auditar_signo.py`: el contador se incrementaba
        antes de la dedup, asi que una oracion citada por tres articulos
        consumia tres de los 40 cupos y luego se colapsaba a una."""
        misma = ("MexT activates the expression of mexEF-oprN in "
                 "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        otra = ("MexT binds directly upstream of mexEF-oprN and turns the "
                "operon on in Pseudomonas aeruginosa PAO1 cells.")
        crudos = []
        for pmid in ("1", "2", "3"):
            crudos.extend(self._fila(misma, pmid, 0))
        crudos.extend(self._fila(otra, "4", 0))
        crudos = [c for c in crudos if c[0]["target"] == "mexEF-oprN"]
        self.assertEqual(len(crudos), 4)
        topados, descartadas = E.topar_por_par(crudos, 2)
        # Tres filas de la misma oracion consumen UN cupo, no tres, asi que la
        # cuarta oracion --que es nueva-- entra.
        self.assertEqual(len(topados), 4)
        self.assertEqual(descartadas, 0)
        topados, descartadas = E.topar_por_par(crudos, 1)
        self.assertEqual(len(topados), 3)
        self.assertEqual(descartadas, 1)

    def test_verificar_acepta_una_muestra_bien_formada(self):
        oracion = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        crudos = self._fila(oracion, "19846594", 0)
        self.assertTrue(crudos)
        self.assertIsNone(E.verificar(crudos))

    def test_verificar_detecta_el_marcado_roto(self):
        oracion = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        crudos = self._fila(oracion, "19846594", 0)
        crudos[0][0]["text"] = crudos[0][0]["text"].replace("<e1> ", "<e1>")
        self.assertIn("seccion 3.1", E.verificar(crudos))

    def test_verificar_detecta_el_id_par_repetido(self):
        oracion = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        crudos = self._fila(oracion, "19846594", 0)
        fila = crudos[0]
        gemela = (dict(fila[0]), fila[1])
        gemela[0]["seccion"] = "discussion"
        self.assertIn("id_par colisiona", E.verificar([fila, gemela]))

    def test_verificar_detecta_el_resumen_leido_dos_veces(self):
        """La regresion que la seccion 3.3 vigila --leer el resumen del .txt y
        otra vez de la base, que afecta a 799 de 918 articulos-- se simula
        pasando por el generador de candidatos las piezas que produciria esa
        doble lectura, no fabricando dos filas a mano.

        Mientras `piezas_de_documento()` devolvia UNA fuente por documento,
        esta invariante no podia dispararse en produccion: estaba viva en su
        prueba y muerta en la corrida. Con la fuente por pieza, la doble
        lectura es representable y el guardian la ve."""
        resumen = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        cuerpo = ("MexR represses mexAB-oprM in Pseudomonas aeruginosa PAO1 "
                  "cultures grown in rich medium.")
        piezas = [("abstract", resumen, "fulltext"),
                  ("results", cuerpo, "fulltext"),
                  ("abstract", resumen, "resumen")]
        cuenta = collections.Counter()
        candidatos = E.candidatos_de_documento("19846594", piezas, self.lex,
                                               8, cuenta)
        self.assertIn("seccion 3.3", E.verificar(candidatos))

    def test_verificar_acepta_el_documento_sin_doble_lectura(self):
        """El contrapeso del anterior: las mismas piezas, todas del .txt, no
        disparan nada. Sin esto la invariante podria estar saltando siempre."""
        resumen = ("MexT activates the expression of mexEF-oprN in "
                   "Pseudomonas aeruginosa PAO1 grown in rich medium.")
        cuerpo = ("MexR represses mexAB-oprM in Pseudomonas aeruginosa PAO1 "
                  "cultures grown in rich medium.")
        piezas = [("abstract", resumen, "fulltext"),
                  ("results", cuerpo, "fulltext")]
        candidatos = E.candidatos_de_documento("19846594", piezas, self.lex,
                                               8, collections.Counter())
        self.assertTrue(candidatos)
        self.assertIsNone(E.verificar(candidatos))


# Las unicas filas del corpus del asesor que `pretokenizar()` no reproduce, y
# por que ninguna regla puede ni debe reproducirlas: son averias del extractor
# de PDF con el que se armo ese corpus, no convenciones de pretokenizacion.
#
# Cada entrada es (subcadena que identifica la fila, cuantas filas la llevan,
# justificacion). Si una deja de aparecer, la prueba falla: una lista de
# excepciones que ya no corresponde a nada es una lista que nadie reviso.
ARTEFACTOS_DEL_EXTRACTOR = [
    ("melR promoter, while", 4,
     "El extractor dejo sin separar la coma y el punto de esa oracion. El "
     "propio contrato lo midio: la coma va pegada 21 veces contra 4309 "
     "separada. Imitar el 0.5 % rompe el 99.5 %."),
    ("?RS45", 2,
     "Mojibake de la lambda de los lisogenos (lambdaRS45). El caracter se "
     "perdio al extraer el PDF y quedo un signo de interrogacion pegado al "
     "nombre de la cepa. Nuestro corpus JATS trae el caracter correcto."),
    ("?JA450", 1,
     "El mismo mojibake, con lambdaJA450."),
    ("nitrophenyl -- D - galactopyranoside", 1,
     "Mojibake de la beta de o-nitrophenyl-beta-D-galactopyranoside: quedaron "
     "dos guiones seguidos donde iba la letra griega."),
]


class PruebasIdempotenciaContraElEntrenamiento(unittest.TestCase):
    """`pretokenizar()` contra el texto que el modelo vio de verdad.

    El corpus del asesor YA viene pretokenizado. Volver a pasarlo por nuestra
    funcion tiene que devolverlo intacto: cada diferencia es una forma que
    nosotros generamos y que el modelo no vio nunca, y como los marcadores no
    son tokens especiales, esas piezas de wordpiece se degradan en silencio,
    sin que nada falle.

    Sintoma que esta prueba caza, medido byte a byte: con la regla que separaba
    TODO punto y TODA coma, 96 de las 1249 filas de entrenamiento (7.7 %)
    dejaban de ser idempotentes, y todas por partir numeros (`46.5`, `1,000`,
    el DOI `10.1042`) o entidades HTML (`&amp;`). En el corpus real eso tocaba
    el 4.7 % de las oraciones candidatas, concentradas en RESULTS y en los pies
    de figura, que es donde estan los cambios de expresion: `P < 0 . 05` y
    `2 . 5 - fold`.
    """

    @classmethod
    def setUpClass(cls):
        cls.corpus = {}
        for nombre in ("train", "dev", "test"):
            ruta = os.path.join(AQUI, "para_colab",
                                "entity_marked_%s.jsonl" % nombre)
            with io.open(ruta, encoding="utf-8") as f:
                cls.corpus[nombre] = [json.loads(l) for l in f if l.strip()]

    def _desnudo(self, marcado):
        for etiqueta in ("<e1>", "</e1>", "<e2>", "</e2>"):
            marcado = marcado.replace(etiqueta, "")
        return T.normalizar_espacios(marcado)

    def _no_idempotentes(self, nombre):
        salida = []
        for i, d in enumerate(self.corpus[nombre], 1):
            crudo = self._desnudo(d["text"])
            vuelto, spans = T.pretokenizar(crudo, [])
            self.assertEqual(spans, [])
            if vuelto != crudo:
                salida.append((i, crudo, vuelto))
        return salida

    def test_las_1249_filas_de_entrenamiento_son_idempotentes(self):
        """La cifra que importa: de las 1249 filas reales, las unicas que no
        vuelven identicas son las 8 que llevan una averia del extractor del
        asesor, enumeradas una a una con su justificacion."""
        self.assertEqual(len(self.corpus["train"]), 1249)
        malas = self._no_idempotentes("train")
        con_artefacto, sin_explicacion = [], []
        for i, crudo, vuelto in malas:
            if any(marca in crudo for marca, _, _ in ARTEFACTOS_DEL_EXTRACTOR):
                con_artefacto.append(i)
            else:
                sin_explicacion.append((i, crudo, vuelto))
        self.assertEqual(
            sin_explicacion, [],
            "Hay filas que pretokenizar() no reproduce y que no son una "
            "averia conocida del extractor: cada una es una forma que el "
            "modelo no vio nunca.")
        self.assertEqual(len(con_artefacto), 8)
        self.assertEqual(
            len(self.corpus["train"]) - len(malas), 1241)

    def test_ni_un_solo_numero_ni_una_entidad_html_se_parten(self):
        """La familia entera, dicha como numero: cero filas rotas por un
        decimal, un separador de millares, un DOI o un `&amp;` --en los tres
        archivos, no solo en el de entrenamiento--."""
        rotas = []
        for nombre in ("train", "dev", "test"):
            for i, crudo, vuelto in self._no_idempotentes(nombre):
                if re.search(r"\d[.,]\d", crudo) and re.search(r"\d [.,] \d",
                                                              vuelto):
                    rotas.append((nombre, i, "numero"))
                elif "&" in crudo and re.search(r"&[A-Za-z#0-9]+ ;", vuelto):
                    rotas.append((nombre, i, "entidad_html"))
        self.assertEqual(rotas, [])

    def test_la_lista_de_artefactos_sigue_correspondiendo_al_dato(self):
        """Una lista de excepciones que ya no corresponde a nada es una lista
        que nadie reviso. Aqui se comprueba que cada artefacto sigue estando
        en el archivo, y en la cantidad anotada."""
        textos = [self._desnudo(d["text"]) for d in self.corpus["train"]]
        for marca, cuantas, justificacion in ARTEFACTOS_DEL_EXTRACTOR:
            self.assertTrue(justificacion.strip())
            self.assertEqual(
                sum(1 for t in textos if marca in t), cuantas,
                "el artefacto %r ya no aparece %d veces" % (marca, cuantas))

    def test_el_punto_final_tras_una_cifra_si_se_separa(self):
        """La proteccion es SOLO entre digitos. Si se extendiera a cualquier
        punto pegado a una cifra, el punto que cierra la oracion dejaria de
        separarse y ahi si nos apartariamos del entrenamiento, donde 1547 de
        1562 filas terminan en `" ."`."""
        texto, _ = T.pretokenizar("The strain grew for 5. Then it stopped.",
                                  [])
        self.assertEqual(texto, "The strain grew for 5 . Then it stopped .")

    def test_los_decimales_del_dominio_llegan_enteros(self):
        """Las formas concretas que el 4.7 % del corpus lleva."""
        casos = [
            ("Expression increased 2.5-fold in the mutant.",
             "Expression increased 2.5 - fold in the mutant ."),
            ("The difference was significant (P < 0.05).",
             "The difference was significant ( P < 0.05 ) ."),
            ("A total of 1,000 colonies were counted.",
             "A total of 1,000 colonies were counted ."),
        ]
        for cruda, esperada in casos:
            self.assertEqual(T.pretokenizar(cruda, [])[0], esperada)


class PruebasPretokenizacion(Base):

    def test_la_puntuacion_se_separa(self):
        texto, spans = T.pretokenizar("A LysR-type regulator (LTTR) acts.", [])
        self.assertEqual(texto, "A LysR - type regulator ( LTTR ) acts .")
        self.assertEqual(spans, [])

    def test_los_tramos_protegidos_no_se_parten(self):
        cruda = "The mexEF-oprN operon is induced."
        ini = cruda.index("mexEF-oprN")
        texto, spans = T.pretokenizar(cruda, [(ini, ini + 10)])
        self.assertIn("mexEF-oprN", texto)
        self.assertNotIn("mexEF - oprN", texto)
        self.assertEqual(texto[spans[0][0]:spans[0][1]], "mexEF-oprN")

    def test_no_se_parte_la_frontera_letra_digito(self):
        """El entrenamiento muestra `His 6 - ArgP`, pero partir ahi convertiria
        `PA0762` en `PA 0762` y destruiria la mitad del vocabulario del
        dominio."""
        texto, _ = T.pretokenizar("The PA0762 locus and mexAB were assayed.",
                                  [])
        self.assertIn("PA0762", texto)
        self.assertIn("mexAB", texto)


class PruebasOraciones(Base):

    def test_la_guarda_de_inicial_no_parte_el_nombre_de_la_especie(self):
        """Medido sobre 60 textos completos: dispara en el 15.9 % de los cortes
        crudos, y `P.` sola son 2110 de esas veces."""
        cuerpo = ("MexT acts in P. aeruginosa PAO1. The mexEF-oprN operon "
                  "follows. Growth in E. coli was normal.")
        salida = T.oraciones(cuerpo)
        self.assertEqual(len(salida), 3)
        self.assertTrue(salida[0].startswith("MexT acts in P. aeruginosa"))
        self.assertTrue(salida[2].startswith("Growth in E. coli"))

    def test_la_abreviatura_no_termina_oracion(self):
        cuerpo = "See Fig. 3 for details. The operon was induced."
        self.assertEqual(len(T.oraciones(cuerpo)), 2)


RESULTADOS = ("MexT activates the expression of mexEF-oprN in Pseudomonas "
              "aeruginosa PAO1 grown in rich medium.")
METODOS = ("The coding regions of MexT, NalD and MexR were amplified by PCR "
           "and cloned upstream of mexEF-oprN in the plasmid pUCP20.")
AUTO = (u"In the ΔnalD mutant, nalD expression was measured and found to be "
        u"strongly increased over the wild type.")
RESUMEN = ("MexR represses mexAB-oprM in Pseudomonas aeruginosa PAO1 under "
           "the conditions assayed here.")


class PruebasCorridaCompleta(unittest.TestCase):
    """`main()` de punta a punta, sobre un corpus de dos documentos.

    Las pruebas de unidad de arriba cubren cada pieza; esta cubre lo que el
    script HACE cuando se corre, que es donde se esconden los defectos de
    orquestacion: que el filtro de seccion se aplique de verdad, que la
    invariante de escala no tenga interruptor y que la autorregulacion llegue
    al archivo marcada.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pares_e2e_")
        self.genes = os.path.join(self.dir, "genes.tsv")
        self.operones = os.path.join(self.dir, "operones.tsv")
        self.db = os.path.join(self.dir, "grn.db")
        self.fulltext = os.path.join(self.dir, "fulltext")
        self.salida = os.path.join(self.dir, "salida", "pares.jsonl")
        self.informe = os.path.join(self.dir, "salida", "informe.json")

        # El diccionario de juguete mas el relleno que exige la invariante de
        # las 5000 filas. El relleno son locus tags que no aparecen en ningun
        # texto: esta prueba mide la orquestacion, no el reconocimiento.
        with io.open(self.genes, "w", encoding="utf-8", newline="") as f:
            f.write(COLUMNAS_GENES + u"\n")
            for fila in GENES:
                f.write(u"\t".join(fila) + u"\n")
            for i in range(6000 - len(GENES)):
                f.write(u"\t".join(["PA%04d" % (1000 + i), "", "",
                                    "protein_coding", "hypothetical protein",
                                    "false", "", "refseq", "false"]) + u"\n")
        with io.open(self.operones, "w", encoding="utf-8", newline="") as f:
            f.write(COLUMNAS_OPERONES + u"\n")
            for fila in OPERONES:
                f.write(u"\t".join(fila) + u"\n")

        os.makedirs(self.fulltext)
        md = ("## RESULTS\n\n%s\n\n%s\n\n## MATERIALS AND METHODS\n\n%s\n"
              % (RESULTADOS, AUTO, METODOS))
        with io.open(os.path.join(self.fulltext, "19846594_PMC2794183.txt"),
                     "w", encoding="utf-8") as f:
            f.write(md)

        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE documentos (pmid TEXT, abstract TEXT)")
        con.execute("INSERT INTO documentos VALUES (?, ?)",
                    ("19846594", RESULTADOS))
        con.execute("INSERT INTO documentos VALUES (?, ?)", ("100", RESUMEN))
        con.commit()
        con.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _argv(self, extra=()):
        return (["extraer_pares.py", "--db", self.db, "--fulltext",
                 self.fulltext, "--genes", self.genes, "--operones",
                 self.operones, "--salida", self.salida, "--informe",
                 self.informe] + list(extra))

    def _correr(self, extra=()):
        """Corre `main()` de verdad. Se silencian las dos salidas para que la
        suite no escupa el informe ni el uso de argparse."""
        viejos = (sys.argv, sys.stdout, sys.stderr)
        sys.argv = self._argv(extra)
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            return E.main()
        finally:
            sys.argv, sys.stdout, sys.stderr = viejos

    def _leer(self):
        with io.open(self.salida, encoding="utf-8") as f:
            filas = [json.loads(l) for l in f if l.strip()]
        with io.open(self.informe, encoding="utf-8") as f:
            return filas, json.load(f)

    def test_la_corrida_de_depuracion_escribe_y_se_marca(self):
        self.assertEqual(self._correr(["--limite-docs", "2"]), 0)
        filas, informe = self._leer()
        self.assertTrue(filas)
        self.assertFalse(informe["corrida_completa"])
        # El formato del marcado, sobre el archivo que se escribio de verdad.
        for fila in filas:
            encontrados = E.MARCADO.findall(fila["text"])
            self.assertEqual(sorted(e[0] for e in encontrados), ["1", "2"])
            marcadas = dict(encontrados)
            self.assertEqual(marcadas["1"], fila["mencion_tf"])
            self.assertEqual(marcadas["2"], fila["mencion_target"])
            self.assertNotIn("  ", fila["text"])

    def test_ninguna_fila_sale_de_la_seccion_de_metodos(self):
        """El filtro de seccion visto desde el archivo que se escribe. Es el
        19.6 % del corpus: prosa de construccion de plasmidos donde MexT, NalD
        y MexR coocurren con mexEF-oprN sin ninguna relacion que extraer."""
        self._correr(["--limite-docs", "2"])
        filas, _ = self._leer()
        for fila in filas:
            self.assertIn(fila["seccion"], E.SECCIONES_QUE_ENTRAN)
            self.assertNotIn("PCR", fila["oracion_cruda"])
            self.assertNotIn("pUCP20", fila["oracion_cruda"])
        # Y la oracion de metodos SI habria dado pares de haber entrado.
        self.assertNotEqual(
            [], E.candidatos_de_oracion("1", "results", "fulltext", 0,
                                        METODOS,
                                        L.Lexico.cargar(self.genes,
                                                        self.operones),
                                        8, collections.Counter()))

    def test_la_autorregulacion_llega_al_archivo_marcada(self):
        self._correr(["--limite-docs", "2"])
        filas, informe = self._leer()
        autos = [f for f in filas if f["autorregulacion"]]
        self.assertEqual([(f["tf"], f["target"]) for f in autos],
                         [("NalD", "nalD")])
        self.assertEqual(informe["autorregulacion_misma_entidad"], 1)
        self.assertEqual(informe["autorregulacion_por_operon"], 0)

    def test_el_resumen_de_la_base_entra_solo_donde_no_hay_txt(self):
        self._correr(["--limite-docs", "2"])
        filas, _ = self._leer()
        fuentes = dict((f["pmid"], set()) for f in filas)
        for f in filas:
            fuentes[f["pmid"]].add(f["fuente"])
        self.assertEqual(fuentes[19846594], set(["fulltext"]))
        self.assertEqual(fuentes[100], set(["resumen"]))

    def test_sin_limite_docs_la_invariante_de_escala_aborta(self):
        """El aviso barato de 'revisa el diccionario antes de gastar una hora
        de GPU'. Habia una bandera, `--sin-invariante-escala`, que lo apagaba
        sobre el corpus COMPLETO: con un diccionario del que solo 3 filas
        tenian simbolo, escribio pares.jsonl con 11 pares sin una queja, y ese
        archivo alimenta a la etapa 3 y sale una red entera construida sobre
        nada."""
        with self.assertRaises(SystemExit) as cm:
            self._correr()
        self.assertIn("pares candidatos", str(cm.exception))
        self.assertFalse(os.path.exists(self.salida))

    def test_la_bandera_que_apagaba_la_invariante_ya_no_existe(self):
        """No estaba en el contrato y nada la obligaba a ir con --limite-docs:
        su ayuda decia 'solo tiene sentido con --limite-docs' y ahi acababa la
        garantia. Ahora la unica forma de saltarse la invariante es recortar el
        corpus, que es lo que la hace inaplicable."""
        with self.assertRaises(SystemExit) as cm:
            self._correr(["--sin-invariante-escala"])
        self.assertEqual(cm.exception.code, 2)
        self.assertFalse(os.path.exists(self.salida))


class PruebasProcedencia(unittest.TestCase):
    """De donde salio el diccionario, comprobado en la ETAPA 2.

    El guardian vivia solo en la etapa 5, o sea despues de escribir
    pares.jsonl, predicciones.jsonl y red.tsv. Demostrado: un genes_pao1.tsv
    con fuente=oro en las 5700 filas producia 86217 pares y 3353 aristas con
    codigo 0 en las dos etapas. La red es el artefacto que se comparte y quien
    corriera solo hasta ahi no recibia ningun aviso.
    """

    def _filas(self, *fuentes):
        return [{"locus_tag": "PA%04d" % (i + 1), "fuente": f}
                for i, f in enumerate(fuentes)]

    def test_una_sola_fila_del_patron_lo_impide_todo(self):
        with self.assertRaises(SystemExit) as cm:
            E.revisar_procedencia(
                self._filas("refseq", "refseq|oro", "kegg"), "genes.tsv")
        mensaje = str(cm.exception)
        self.assertIn("PA0002 (fuente=oro)", mensaje)
        self.assertIn("No escribo", mensaje)

    def test_las_variantes_de_la_etiqueta_caen_igual(self):
        """Se compara en minusculas y por subcadena: quien escriba `ORO`,
        `patron_de_referencia` o el nombre del archivo de la auditoria de
        signo cae en el mismo sitio. Una lista de coincidencias exactas se
        esquiva con una mayuscula."""
        for valor in ("ORO", "patron", "auditoria", "Oro|refseq",
                      "tabla_de_auditoria"):
            with self.assertRaises(SystemExit):
                E.revisar_procedencia(self._filas(valor), "genes.tsv")

    def test_el_enum_del_contrato_pasa_y_se_cuenta(self):
        fuentes, desconocidas = E.revisar_procedencia(
            self._filas("refseq|kegg", "uniprot", "manual",
                        "uniprot_especie"), "genes.tsv")
        self.assertEqual(dict(fuentes), {"refseq": 1, "kegg": 1, "uniprot": 1,
                                         "manual": 1, "uniprot_especie": 1})
        self.assertEqual(dict(desconocidas), {})

    def test_una_fuente_desconocida_avisa_pero_no_aborta(self):
        """No es prueba de circularidad, solo de que el archivo no lo escribio
        construir_diccionario.py. Abortar ahi convertiria el guardian en un
        estorbo y acabaria desactivado."""
        viejo, sys.stdout = sys.stdout, io.StringIO()
        try:
            fuentes, desconocidas = E.revisar_procedencia(
                self._filas("pseudomonas_com", "refseq"), "genes.tsv")
            texto = sys.stdout.getvalue()
        finally:
            sys.stdout = viejo
        self.assertEqual(dict(desconocidas), {"pseudomonas_com": 1})
        self.assertIn("AVISO", texto)

    def test_la_lista_de_fuentes_no_puede_divergir_de_la_etapa_5(self):
        """Las dos etapas vigilan la misma columna con la misma lista. Dos
        copias que se separen dejan una puerta abierta en una de las dos, y
        justo eso --que el guardian estuviera en un solo archivo-- es el
        defecto que se esta cerrando aqui."""
        import evaluar_oro as O
        self.assertEqual(E.FUENTES_VALIDAS, O.FUENTES_VALIDAS)
        self.assertEqual(E.FUENTES_DEL_ORO, O.FUENTES_DEL_ORO)


class PruebasLoQueElDiccionarioEncuentra(unittest.TestCase):
    """La mitad que mide contenido: cuantas entidades aparecen de verdad.

    La procedencia es una etiqueta, y una etiqueta se escribe: quien copie una
    lista y ponga `refseq` pasa el guardian de arriba. Lo que no se puede
    falsificar es que el corpus mencione los genes por su nombre.
    """

    def test_el_patron_del_locus_tag_es_el_mismo_que_el_del_lexico(self):
        """Si los dos se separan, un locus tag empieza a contar como nombre en
        un lado y no en el otro, y la medicion deja de medir lo que dice."""
        self.assertEqual(E.LOCUS_TAG.pattern, L._LOCUS.pattern)

    def test_el_umbral_es_el_medido(self):
        """Fijador de un valor medido, no una constante de gusto. Sobre los
        918 textos completos, entidades reconocidas por un nombre y no por su
        locus tag: 1979 con el diccionario real de la etapa 1, 865 con uno de
        771 simbolos reales mas relleno inventado, 1112 con uno de 1100. El
        umbral queda 1.7 veces por encima del ataque mas fuerte y un 24 % por
        debajo del diccionario real."""
        self.assertEqual(E.MINIMO_ENTIDADES_VISTAS, 1500)

    def test_por_debajo_del_umbral_no_escribe(self):
        with self.assertRaises(SystemExit) as cm:
            E.revisar_lo_que_el_diccionario_encuentra(
                set("g%d" % i for i in range(E.MINIMO_ENTIDADES_VISTAS - 1)),
                5700, "genes.tsv")
        self.assertIn("No escribo", str(cm.exception))

    def test_en_el_umbral_pasa(self):
        E.revisar_lo_que_el_diccionario_encuentra(
            set("g%d" % i for i in range(E.MINIMO_ENTIDADES_VISTAS)),
            5700, "genes.tsv")


class PruebasEntidadesVistas(Base):
    """El locus tag NO cuenta como nombre, y esa es la mitad util.

    Medido: un diccionario con 1100 simbolos de verdad y 4542 filas de relleno
    inventado seguia reconociendo 2646 entidades del corpus, porque conservaba
    los 5642 locus tags y la literatura de PAO1 escribe muchos PAxxxx.
    Contando solo las reconocidas por un nombre cae a 1112. Un locus tag se
    genera con un bucle; un simbolo de gen, no.
    """

    def _vistas(self, oracion):
        vistas = {}
        E.candidatos_de_oracion("1", "results", "fulltext", 0,
                                T.normalizar_espacios(oracion), self.lex, 8,
                                self.cuenta, vistas)
        return vistas

    def test_la_mencion_por_locus_tag_se_ve_pero_no_cuenta_como_nombre(self):
        vistas = self._vistas("Expression of PA2492 was measured in PAO1.")
        self.assertEqual(vistas, {"mexT": False})

    def test_la_mencion_por_el_simbolo_si_cuenta(self):
        vistas = self._vistas("Expression of mexT was measured in PAO1.")
        self.assertEqual(vistas, {"mexT": True})

    def test_el_nombre_le_gana_al_locus_tag_llegue_como_llegue(self):
        """La misma entidad nombrada de las dos formas cuenta como nombre, sin
        que importe cual aparecio antes."""
        for oracion in ("PA2492 encodes mexT in this strain of PAO1.",
                        "mexT is the gene PA2492 in this strain of PAO1."):
            self.assertEqual(self._vistas(oracion), {"mexT": True})

    def test_sin_el_parametro_no_se_lleva_la_cuenta(self):
        """La firma vieja tiene que seguir sirviendo: `vistas` es opcional
        justamente para que las pruebas de unidad de arriba no la pasen."""
        self.assertNotEqual([], E.candidatos_de_oracion(
            "1", "results", "fulltext", 0,
            "MexT activates the mexEF-oprN operon of P. aeruginosa PAO1.",
            self.lex, 8, self.cuenta))


class PruebasProcedenciaEnLaCorrida(unittest.TestCase):
    """Lo mismo, pero por `main()`. Lo que importa no es que exista una
    funcion capaz de detectarlo, sino que el archivo no llegue a escribirse.

    Se reusa el montaje de PruebasCorridaCompleta --corpus de dos documentos,
    base SQLite y diccionario de 6000 filas-- sin heredar de ella, que
    repetiria sus seis pruebas."""

    setUp = PruebasCorridaCompleta.setUp
    tearDown = PruebasCorridaCompleta.tearDown
    _argv = PruebasCorridaCompleta._argv
    _correr = PruebasCorridaCompleta._correr
    _leer = PruebasCorridaCompleta._leer

    def _envenenar(self, fuente):
        with io.open(self.genes, encoding="utf-8") as f:
            lineas = f.read().split(u"\n")
        cabecera = lineas[0].split(u"\t")
        i = cabecera.index("fuente")
        salida = [lineas[0]]
        for linea in lineas[1:]:
            if not linea.strip():
                continue
            campos = linea.split(u"\t")
            campos[i] = fuente
            salida.append(u"\t".join(campos))
        with io.open(self.genes, "w", encoding="utf-8", newline="") as f:
            f.write(u"\n".join(salida) + u"\n")

    def test_el_diccionario_del_patron_aborta_sin_escribir_nada(self):
        self._envenenar("oro")
        with self.assertRaises(SystemExit) as cm:
            self._correr(["--limite-docs", "2"])
        self.assertIn("hace circular", str(cm.exception))
        self.assertFalse(os.path.exists(self.salida))
        self.assertFalse(os.path.exists(self.informe))

    def test_aborta_antes_de_leer_el_corpus(self):
        """Cuesta cero y no deja a medias ningun trabajo: la comprobacion va
        antes de listar el directorio de textos completos."""
        self._envenenar("oro")
        viejos = (sys.argv, sys.stdout, sys.stderr)
        sys.argv = self._argv(["--limite-docs", "2"])
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            with self.assertRaises(SystemExit):
                E.main()
            impreso = sys.stdout.getvalue()
        finally:
            sys.argv, sys.stdout, sys.stderr = viejos
        self.assertNotIn("Corpus:", impreso)

    def test_el_informe_publica_la_composicion_del_diccionario(self):
        """Los numeros que describen la ENTRADA. Sin ellos el informe cuenta
        lo que salio de una corrida cuya entrada nadie puede reconstruir."""
        self._correr(["--limite-docs", "2"])
        _, informe = self._leer()
        self.assertEqual(informe["diccionario"]["filas"], 6000)
        self.assertEqual(informe["diccionario"]["fuentes"]["refseq"], 6000)
        self.assertEqual(informe["diccionario"]["fuentes_desconocidas"], {})
        self.assertGreater(informe["entidades_vistas_en_el_corpus"], 0)
        self.assertLessEqual(informe["entidades_vistas_por_un_nombre"],
                             informe["entidades_vistas_en_el_corpus"])

    def test_la_corrida_completa_comprueba_lo_que_el_diccionario_encuentra(self):
        """El cableado, no la funcion. Con --limite-docs la comprobacion no
        corre --es una medicion contra el corpus completo-- y sobre el corpus
        de juguete la invariante de escala mata la corrida antes de llegar a
        ella, asi que sin aflojar la banda no habria forma de que esta prueba
        fallara cuando alguien borrase la llamada de `main()`. Se afloja el
        minimo de pares y se comprueba lo siguiente que tiene que pasar."""
        viejo = E.MIN_PARES
        E.MIN_PARES = 1
        try:
            with self.assertRaises(SystemExit) as cm:
                self._correr()
        finally:
            E.MIN_PARES = viejo
        self.assertIn("escritas con un nombre", str(cm.exception))
        self.assertFalse(os.path.exists(self.salida))
        self.assertFalse(os.path.exists(self.informe))

    def test_el_informe_cuenta_los_operones_que_aparecen(self):
        """Las sub-corridas de la tabla que ningun articulo escribe. Medido
        sobre los 918 textos completos: 244 de los 3030 aparecen alguna vez, y
        `mexB-oprM` --el ejemplo de siempre-- no es una de ellas. No se
        filtran (ver el docstring del modulo), pero el numero se publica para
        que la decision se pueda revisar con evidencia de la corrida."""
        self._correr(["--limite-docs", "2"])
        _, informe = self._leer()
        self.assertEqual(informe["operones_de_la_tabla"], len(OPERONES))
        self.assertIn("mexAB-oprM", informe["operones_vistos_top"])
        self.assertLess(informe["operones_vistos_en_el_corpus"],
                        informe["operones_de_la_tabla"])


if __name__ == "__main__":
    unittest.main()
