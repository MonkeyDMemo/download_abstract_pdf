# -*- coding: utf-8 -*-
"""Pruebas de la etapa 1 (seccion 2 del contrato de datos).

Dos familias:

- Las que ejercitan el analisis de las respuestas de RefSeq, KEGG y UniProt
  contra los recortes literales de `etapa2/fixtures/`. Ninguna toca la red.
- Las dos comprobaciones de cobertura contra el patron de oro, que son
  **verificacion cruzada y no fuente**: el diccionario no puede leer el oro
  (lo impide `test_contaminacion.py`), pero si tiene que poder reconocer los
  nombres que el oro usa, porque si no la exhaustividad de la etapa 5 mediria
  el diccionario en vez de medir el pipeline.

Y una tercera cosa, que es la que motiva el archivo entero: las pruebas que
reconocen un diccionario FABRICADO. La verificacion adversarial demostro que
un `genes_pao1.tsv` con 785 filas copiadas del oro y 4915 filas de relleno
vacio pasaba todos los guardianes de entonces y publicaba exhaustividad
81.7 %. El guardian que existia contaba LINEAS, asi que el relleno lo
desactivaba. Aqui se cuentan filas utiles y se mide cuanto sabe el
diccionario que el oro no sabe.

La segunda vuelta de esa misma verificacion demostro que el ataque no hacia
falta hacerlo sobre el TSV: bastaba **editar el cache**. Con 165 nombres del
patron de oro inyectados en `refseq_gff.gz`, el script salia con codigo 0
publicando 5642 filas y una cobertura del oro del 95.8 %, y pasaba estas
mismas pruebas, porque todas miraban la salida y ninguna miraba de donde
venia. De ahi salen `PruebasCacheVerificado` (los bytes contra el sha256 del
manifiesto) y `PruebasCorroboracionCruzada` (el contenido contra el
contenido: si RefSeq, KEGG y UniProt coinciden en como se llama cada locus
tag). La regla que las ordena es la misma en las tres familias: **no
preguntes que dice ser, mide que es.**
"""

import contextlib
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import construir_diccionario as D    # noqa: E402
from lexico import Lexico            # noqa: E402

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(DIRECTORIO, "fixtures")
GENES = os.path.join(DIRECTORIO, "genes_pao1.tsv")
OPERONES = os.path.join(DIRECTORIO, "operones_pao1.tsv")
COLLECTF = os.path.join(DIRECTORIO, "collectf_pao1.tsv")
MANUAL = os.path.join(DIRECTORIO, "manual_pao1.tsv")
ORO = os.path.join(DIRECTORIO, "oro_pseudomonas.tsv")

LOCUS_EN_TEXTO = re.compile(r"\bPA\d{4}(?:\.\d)?\b")


def _fixture(nombre):
    with open(os.path.join(FIXTURES, nombre), encoding="utf-8") as f:
        return f.read()


def _fila(filas, locus):
    for fila in filas:
        if fila["locus_tag"] == locus:
            return fila
    return None


def _fila_valida(**campos):
    """Una fila de genes con todos los campos, para las pruebas de invariante."""
    fila = {c: "" for c in D.COLUMNAS_GENES}
    fila.update({"tipo": "protein_coding", "es_tf": "false",
                 "fuente": "refseq", "sensible_mayusculas": "false"})
    fila.update(campos)
    return fila


# --------------------------------------------------------- analisis crudo

class PruebasAnalisisGFF(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.genes, cls.sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))

    def test_lee_locus_simbolo_y_producto(self):
        self.assertEqual("mexT", self.genes["PA2492"]["simbolo"])
        self.assertIn("MexT", self.genes["PA2492"]["producto"])
        self.assertEqual("protein_coding", self.genes["PA2492"]["biotipo"])

    def test_el_simbolo_puede_venir_del_feature_hijo(self):
        """PA1003 lleva `gene=mvfR` en el feature `gene` y en el `CDS`.

        El parser tiene que tomar el primero que aparezca y no pisarlo: si
        pisara con el hijo, un gen cuyo CDS no repite `gene=` se quedaria sin
        simbolo.
        """
        self.assertEqual("mvfR", self.genes["PA1003"]["simbolo"])

    def test_lee_la_hebra(self):
        """Sin la hebra, `mexCD-oprJ` sale al reves. Ver derivar_operones."""
        self.assertEqual("+", self.genes["PA0425"]["hebra"])
        self.assertEqual("-", self.genes["PA4597"]["hebra"])

    def test_los_atributos_se_desescapan_despues_de_partir(self):
        atributos = D._atributos("a=uno%3Bdos;b=tres")
        self.assertEqual({"a": "uno;dos", "b": "tres"}, atributos)

    def test_los_sitios_de_collectf_no_entran_como_genes(self):
        self.assertTrue(self.sitios)
        for locus in self.genes:
            self.assertTrue(locus.startswith("PA"))


class PruebasCollecTF(unittest.TestCase):

    def test_partir_por_comas_respeta_los_corchetes(self):
        """`qPCR [quantitative real-time]` lleva corchetes propios y un
        `[PMID: ...]` detras; partir por comas a ciegas los mezcla."""
        self.assertEqual(
            ["ChIP-Seq [PMID: 1]", "qPCR [quantitative real-time] [PMID: 2,3]"],
            D._partir_por_comas(
                "ChIP-Seq [PMID: 1],qPCR [quantitative real-time] [PMID: 2,3]"))

    def test_pares_experimentos_y_pmids(self):
        sitios = [{
            "bound_moiety": "AmrZ",
            "experiment": "ChIP-Seq [PMID: 24603766],RNA-Seq [PMID: 24603766]",
            "Note": ("Transcription factor binding site for NP_252075."
                     "~Evidence of regulation for: PA0027, PA0038"),
        }]
        pares, moieties = D.analizar_sitios(sitios)
        self.assertEqual({("AmrZ", "PA0027"), ("AmrZ", "PA0038")}, set(pares))
        self.assertEqual({"ChIP-Seq", "RNA-Seq"},
                         pares[("AmrZ", "PA0027")]["experimentos"])
        self.assertEqual({24603766}, pares[("AmrZ", "PA0027")]["pmids"])
        self.assertEqual(1, moieties["AmrZ"])

    def test_un_sitio_sin_gen_regulado_no_produce_par_pero_si_TF(self):
        sitios = [{"bound_moiety": "TrpI", "experiment": "EMSA [PMID: 2107533]",
                   "Note": "Transcription factor binding site for NP_248727."}]
        pares, moieties = D.analizar_sitios(sitios)
        self.assertEqual({}, dict(pares))
        self.assertEqual(1, moieties["TrpI"])
        self.assertEqual({2107533}, D.pmids_de_los_sitios(sitios))


class PruebasKEGG(unittest.TestCase):

    def setUp(self):
        self.kegg = D.analizar_kegg(_fixture("kegg_recorte.txt"))

    def test_separa_simbolo_de_descripcion(self):
        self.assertEqual(("mexA", "multidrug resistance protein MexA"),
                         self.kegg["PA0425"])

    def test_sin_simbolo_la_cuarta_columna_es_descripcion(self):
        """PA3678 no tiene simbolo en KEGG: la descripcion no debe leerse
        como si lo fuera."""
        simbolo, descripcion = self.kegg["PA3678"]
        self.assertEqual("", simbolo)
        self.assertIn("regulator", descripcion)


class PruebasUniProt(unittest.TestCase):

    def setUp(self):
        self.filas = D.analizar_uniprot([_fixture("uniprot_recorte.tsv")])

    def test_indexa_por_locus_tag_de_pao1(self):
        indice, descartadas = D.indexar_uniprot(self.filas)
        self.assertIn("PA2492", indice)
        self.assertEqual(0, descartadas)

    def test_descarta_las_entradas_de_otra_cepa(self):
        """Una entrada reviewed de la especie con `PA14_51340` y sin locus de
        PAO1 no se puede colgar de ningun gen sin mezclar dos genomas."""
        indice, descartadas = D.indexar_uniprot(
            [{"Gene Names (ordered locus)": "PA14_51340"}])
        self.assertEqual({}, dict(indice))
        self.assertEqual(1, descartadas)

    def test_marcas_de_tf(self):
        self.assertEqual(
            {"go_0003700", "kw_transcription_regulation"},
            D.marcas_tf_uniprot({"Gene Ontology IDs": "GO:0003700; GO:0005515",
                                 "Keywords": "DNA-binding;Transcription "
                                             "regulation;Reference proteome"}))
        self.assertEqual(set(), D.marcas_tf_uniprot(
            {"Gene Ontology IDs": "GO:0016020", "Keywords": "Membrane"}))

    def test_los_locus_tags_no_entran_como_nombres_de_gen(self):
        primario, sinonimos = D._nombres_uniprot(
            {"Gene Names (primary)": "mexT", "Gene Names (synonym)": "",
             "Gene Names": "mexT PA2492"})
        self.assertEqual("mexT", primario)
        self.assertEqual([], sinonimos)


# ------------------------------------------------------------ construccion

class PruebasConstruccion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        gff, sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))
        kegg = D.analizar_kegg(_fixture("kegg_recorte.txt"))
        uni, _ = D.indexar_uniprot(
            D.analizar_uniprot([_fixture("uniprot_recorte.tsv")]))
        pares, moieties = D.analizar_sitios(sitios)
        cls.gff, cls.moieties, cls.uni = gff, moieties, uni
        cls.filas, cls.indices, cls.quitados = D.construir_genes(
            gff, kegg, uni, {}, [], {"fur"}, moieties)

    def test_la_fuente_se_declara_completa(self):
        fila = _fila(self.filas, "PA2492")
        self.assertEqual("refseq|kegg|uniprot", fila["fuente"])

    def test_la_procedencia_se_verifica_contra_las_cargas(self):
        self.assertEqual([], D.verificar_procedencia(
            self.filas, self.indices, self.gff, self.uni, {}, self.moieties, []))

    def test_una_fuente_inventada_se_caza(self):
        """Es el guardian que separa un diccionario derivado de uno copiado:
        declarar `kegg` sin estar en la carga de KEGG no cuela."""
        filas = [dict(f) for f in self.filas]
        _fila(filas, "PA2492")["fuente"] = "refseq|kegg|uniprot|uniprot_especie"
        problemas = D.verificar_procedencia(
            filas, self.indices, self.gff, self.uni, {}, self.moieties, [])
        self.assertTrue(any("uniprot_especie" in p for p in problemas),
                        problemas)

    def test_una_carga_que_si_la_trae_no_se_puede_callar(self):
        filas = [dict(f) for f in self.filas]
        _fila(filas, "PA2492")["fuente"] = "refseq"
        problemas = D.verificar_procedencia(
            filas, self.indices, self.gff, self.uni, {}, self.moieties, [])
        self.assertTrue(any("no la declara" in p for p in problemas), problemas)

    def test_collectf_como_evidencia_de_tf(self):
        """MexT es bound_moiety de un sitio del recorte, y CollecTF lo escribe
        en forma de proteina mientras el diccionario guarda `mexT`."""
        fila = _fila(self.filas, "PA2492")
        self.assertIn("collectf", fila["fuente_tf"].split("|"))
        self.assertEqual("true", fila["es_tf"])

    def test_es_tf_y_fuente_tf_no_se_contradicen(self):
        for fila in self.filas:
            self.assertEqual(fila["es_tf"] == "true",
                             bool(fila["fuente_tf"].strip()), fila)

    def test_sensible_por_longitud_y_por_palabra_comun(self):
        self.assertEqual("true", _fila(self.filas, "PA4764")["sensible_mayusculas"])
        self.assertEqual("false", _fila(self.filas, "PA2492")["sensible_mayusculas"])

    def test_el_simbolo_de_un_gen_le_gana_al_alias_de_otro(self):
        """UniProt registra `rsmA` como sinonimo de ksgA (PA0592), y `rsmA` es
        el simbolo de PA0905. Con las dos superficies vivas, `Lexico` marca la
        cadena como ambigua y no emite mencion para NINGUNA de las dos: se
        pierden los dos genes, no uno. Medido en el corpus: 2004 menciones de
        RsmA/rsmA en 102 documentos."""
        ksga = _fila(self.filas, "PA0592")
        self.assertNotIn("rsmA", ksga["alias"].split("|"))
        self.assertEqual("rsmA", _fila(self.filas, "PA0905")["simbolo"])
        self.assertEqual(1, self.quitados["choca_con_un_simbolo"])

    def test_un_alias_que_no_parece_nombre_se_tira(self):
        filas = [_fila_valida(locus_tag="PA0001", simbolo="dnaA",
                              alias=";|PA0001")]
        D.depurar_alias(filas)
        self.assertEqual("PA0001", filas[0]["alias"])


class PruebasOperones(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        gff, sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))
        kegg = D.analizar_kegg(_fixture("kegg_recorte.txt"))
        uni, _ = D.indexar_uniprot(
            D.analizar_uniprot([_fixture("uniprot_recorte.tsv")]))
        filas, _, _ = D.construir_genes(gff, kegg, uni, {}, [], set(),
                                        D.analizar_sitios(sitios)[1])
        cls.operones = {o["operon"]: o for o in D.derivar_operones(filas, gff)}

    def test_hebra_mas(self):
        self.assertIn("mexAB-oprM", self.operones)
        self.assertEqual("mexA|mexB|oprM",
                         self.operones["mexAB-oprM"]["miembros"])
        self.assertEqual("PA0425|PA0426|PA0427",
                         self.operones["mexAB-oprM"]["locus_tags"])

    def test_hebra_menos(self):
        """PA4597 es oprJ, PA4598 mexD y PA4599 mexC, los tres en la hebra
        menos. Por locus tag ascendente el nombre saldria `oprJ-mexDC`, que no
        existe en la literatura; el operon se llama `mexCD-oprJ` y es blanco de
        dos filas del patron de oro."""
        self.assertIn("mexCD-oprJ", self.operones)
        self.assertEqual("mexC|mexD|oprJ",
                         self.operones["mexCD-oprJ"]["miembros"])
        self.assertEqual("PA4599|PA4598|PA4597",
                         self.operones["mexCD-oprJ"]["locus_tags"])
        self.assertNotIn("oprJ-mexDC", self.operones)

    def test_se_emiten_las_subcorridas(self):
        self.assertIn("mexAB", self.operones)
        self.assertIn("mexB-oprM", self.operones)

    def test_todos_declaran_su_procedencia(self):
        for operon in self.operones.values():
            self.assertEqual("refseq_adyacencia", operon["fuente"])

    def test_el_nombre_se_arma_por_prefijos(self):
        self.assertEqual("mexAB-oprM",
                         D.nombre_de_operon(["mexA", "mexB", "oprM"]))
        self.assertEqual("pqsABCDE", D.nombre_de_operon(
            ["pqsA", "pqsB", "pqsC", "pqsD", "pqsE"]))
        self.assertEqual("", D.nombre_de_operon(["mexA", "narK1"]))


class PruebasCapaManual(unittest.TestCase):

    def _manual(self, *filas):
        ruta = os.path.join(self.tmp, "manual.tsv")
        with open(ruta, "w", encoding="utf-8", newline="\n") as f:
            f.write("\t".join(D.COLUMNAS_MANUAL) + "\n")
            for fila in filas:
                f.write("\t".join(fila) + "\n")
        return ruta

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_la_justificacion_es_obligatoria(self):
        ruta = self._manual(["fur", "alias", "Fur|PA4764", "", ""])
        with self.assertRaises(SystemExit) as caja:
            D.leer_manual(ruta)
        self.assertIn("justificacion", str(caja.exception))

    def test_un_complejo_declara_sus_miembros(self):
        ruta = self._manual(["IHF", "complejo", "IHF|ihf", "", "TF: prueba"])
        with self.assertRaises(SystemExit) as caja:
            D.leer_manual(ruta)
        self.assertIn("miembros", str(caja.exception))

    def test_el_archivo_versionado_esta_dentro_del_tope(self):
        filas = D.leer_manual(MANUAL)
        self.assertLessEqual(len(filas), 40,
                             "El tope de la capa manual son 40 filas. Si crece "
                             "hasta parecerse a la lista del oro, algo se hizo "
                             "mal.")
        for fila in filas:
            self.assertTrue(fila["justificacion"].strip())

    def test_la_capa_manual_no_renombra_un_gen_publico(self):
        """`mexT` ya es PA2492 en RefSeq: una fila manual no puede llamarlo
        de otra forma. Solo puede agregar superficies."""
        gff, sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))
        manual = [{"id_canonico": "otroNombre", "clase": "alias",
                   "superficies": "PA2492", "miembros": "",
                   "justificacion": "prueba"}]
        with self.assertRaises(SystemExit) as caja:
            D.construir_genes(gff, {}, {}, {}, manual, set(),
                              D.analizar_sitios(sitios)[1])
        self.assertIn("renombra", str(caja.exception))

    def test_la_capa_manual_bautiza_un_gen_sin_simbolo(self):
        """PA3678 no tiene simbolo en ninguna fuente publica. Sin bautizarlo,
        la entidad canonica seria `PA3678` y la tabla de operones no podria
        formar `mexJK`, que es blanco de una fila del patron de oro."""
        gff, sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))
        manual = [{"id_canonico": "mexL", "clase": "alias",
                   "superficies": "MexL|PA3678", "miembros": "",
                   "justificacion": "prueba"}]
        filas, indices, _ = D.construir_genes(gff, {}, {}, {}, manual, set(),
                                              D.analizar_sitios(sitios)[1])
        fila = _fila(filas, "PA3678")
        self.assertEqual("mexL", fila["simbolo"])
        self.assertIn("manual", fila["fuente"].split("|"))

    def test_un_alias_sin_ancla_no_pasa(self):
        gff, sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))
        manual = [{"id_canonico": "Inventado", "clase": "alias",
                   "superficies": "Inventado", "miembros": "",
                   "justificacion": "prueba"}]
        with self.assertRaises(SystemExit) as caja:
            D.construir_genes(gff, {}, {}, {}, manual, set(),
                              D.analizar_sitios(sitios)[1])
        self.assertIn("no se ancla", str(caja.exception))


# ------------------------------------------------------------- invariantes

class PruebasInvariantes(unittest.TestCase):

    def _minimo(self, n=5600, **campos):
        filas = []
        for i in range(n):
            filas.append(_fila_valida(locus_tag="PA%04d" % i))
        for fila in filas[:400]:
            fila.update(es_tf="true", fuente_tf="go_0003700")
        if campos:
            filas[0].update(campos)
        return filas

    def test_una_fila_con_procedencia_de_oro_lo_impide_todo(self):
        filas = self._minimo(fuente="refseq|oro")
        self.assertEqual(D.MSG_ORO, D.invariantes(filas, [], set()))

    def test_la_escala(self):
        self.assertIn("5700", D.invariantes(self._minimo(120), [], set()))
        self.assertIn("5700", D.invariantes(self._minimo(7100), [], set()))
        self.assertIsNone(D.invariantes(self._minimo(), [], set()))

    def test_el_numero_de_tf(self):
        filas = self._minimo()
        for fila in filas:
            fila.update(es_tf="true", fuente_tf="go_0003700")
        self.assertIn("536", D.invariantes(filas, [], set()))

    def test_locus_duplicado(self):
        filas = self._minimo()
        filas[1]["locus_tag"] = filas[0]["locus_tag"]
        self.assertIn("duplicado", D.invariantes(filas, [], set()))

    def test_es_tf_sin_fuente_tf(self):
        filas = self._minimo(es_tf="true", fuente_tf="")
        self.assertIn("se contradicen", D.invariantes(filas, [], set()))

    def test_tope_de_la_capa_manual(self):
        manual = [{"id_canonico": "x"}] * 41
        self.assertIn("tope es 40",
                      D.invariantes(self._minimo(), manual, set()))

    def test_demasiadas_superficies_ambiguas(self):
        self.assertIn("dos entidades",
                      D.invariantes(self._minimo(), [],
                                    {"s%d" % i for i in range(51)}))

    def test_contar_ambiguas_usa_la_regla_de_lexico(self):
        filas = [_fila_valida(locus_tag="PA0001", simbolo="fur",
                              sensible_mayusculas="true"),
                 _fila_valida(locus_tag="PA0002", simbolo="Fur",
                              sensible_mayusculas="true")]
        # Sensibles: `fur` y `Fur` son claves distintas, no chocan.
        self.assertEqual(set(), D.contar_ambiguas(filas))
        for fila in filas:
            fila["sensible_mayusculas"] = "false"
        self.assertEqual({"fur"}, D.contar_ambiguas(filas))


class PruebasSinRed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(self.cache)
        self.manifiesto = {}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _escribir(self, nombre, cuerpo, url="https://ejemplo/%s"):
        """Un archivo del cache y su entrada de manifiesto, como los escribe
        una descarga de verdad. Sin la entrada no se puede leer, y esa es la
        mitad del arreglo."""
        with open(os.path.join(self.cache, nombre), "wb") as f:
            f.write(cuerpo)
        self.manifiesto[nombre] = {
            "url": url % nombre if "%s" in url else url,
            "bytes": len(cuerpo),
            "sha256": hashlib.sha256(cuerpo).hexdigest(),
            "enlace_siguiente": "",
            "fecha": "2026-08-20T00:00:00",
        }
        with io.open(os.path.join(self.cache, "manifiesto.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            json.dump(self.manifiesto, f)

    def _poblar(self):
        self._escribir("refseq_gff.gz",
                       gzip.compress(_fixture("refseq_recorte.gff").encode("utf-8")),
                       D.URL_GFF)
        self._escribir("kegg_pae.txt",
                       _fixture("kegg_recorte.txt").encode("utf-8"), D.URL_KEGG)
        for prefijo, consulta in (("uniprot_proteoma", D.CONSULTA_PROTEOMA),
                                  ("uniprot_especie", D.CONSULTA_ESPECIE)):
            self._escribir("%s_01.tsv" % prefijo,
                           _fixture("uniprot_recorte.tsv").encode("utf-8"),
                           D.url_uniprot(consulta))

    def test_sin_cache_no_inventa_nada(self):
        cache = D.Cache(self.cache, sin_red=True)
        with self.assertRaises(SystemExit) as caja:
            cache.obtener("refseq_gff.gz", D.URL_GFF, None)
        self.assertEqual(D.MSG_SIN_FUENTE, str(caja.exception))

    def test_las_paginas_se_recorren_por_indice(self):
        self._poblar()
        cache = D.Cache(self.cache, sin_red=True)
        paginas = list(cache.paginas("uniprot_proteoma", None, None))
        self.assertEqual(1, len(paginas))
        self.assertIn("PA2492", paginas[0])

    def test_una_corrida_de_juguete_no_escribe_un_diccionario_de_juguete(self):
        """El pipeline entero sobre el recorte: 14 genes. La invariante de
        escala tiene que impedir que eso llegue al disco, porque un
        `genes_pao1.tsv` de 14 filas alimentaria a `extraer_pares.py` y la
        cobertura del oro saldria por los suelos sin que nada dijera por que.
        """
        self._poblar()
        salida = os.path.join(self.tmp, "genes.tsv")
        with open(os.devnull, "w") as mudo, contextlib.redirect_stdout(mudo):
            mensaje = D.main(["--sin-red", "--cache", self.cache,
                              "--salida", salida,
                              "--operones", os.path.join(self.tmp, "op.tsv"),
                              "--collectf", os.path.join(self.tmp, "co.tsv"),
                              "--manual", os.path.join(self.tmp, "no.tsv"),
                              "--db", os.path.join(self.tmp, "no.db")])
        self.assertIn("5700", mensaje)
        self.assertFalse(os.path.exists(salida))
        self.assertFalse(os.path.exists(salida + ".tmp"))


class _ClienteQueNoContesta(object):
    """Un cliente que falla si alguien lo usa. Sirve para MEDIR que el cache
    evito la peticion, en vez de creerle a un contador."""

    def __init__(self):
        self.peticiones = []

    def get(self, url):
        self.peticiones.append(url)
        raise AssertionError("salio a la red pudiendo usar el cache: %s" % url)

    def enlace_siguiente(self):
        return None


class _ClienteCaido(object):
    """La red caida: `Cliente.get()` agota los reintentos y lanza.

    Es el caso mas frecuente en la maquina de laboratorio sin salida a
    internet, y es el contrario del `None`, que significa que el servidor si
    contesto.
    """

    def get(self, url):
        raise D.pubmed.ErrorPubMed(
            "ftp.ncbi.nlm.nih.gov fallo tras 4 intentos: "
            "<urlopen error [Errno 11001] getaddrinfo failed>")

    def enlace_siguiente(self):
        return None


class PruebasCacheVerificado(PruebasSinRed):
    """El sha256 del manifiesto contra los bytes que de verdad se usan.

    El ataque que motiva la clase entera esta medido: se copio el cache real,
    se descomprimio `refseq_gff.gz`, se le inyectaron 165 nombres del patron de
    oro y se volvio a comprimir. El script salia con CODIGO 0, publicaba 5642
    filas y una cobertura del oro del 95.8 %, y el manifiesto seguia mostrando
    el sha256 de la descarga honesta porque nadie lo leia.
    """

    def _corrida(self, *extra):
        salida = os.path.join(self.tmp, "genes.tsv")
        with open(os.devnull, "w") as mudo, contextlib.redirect_stdout(mudo):
            try:
                mensaje = D.main(["--sin-red", "--cache", self.cache,
                                  "--salida", salida,
                                  "--operones", os.path.join(self.tmp, "op.tsv"),
                                  "--collectf", os.path.join(self.tmp, "co.tsv"),
                                  "--manual", os.path.join(self.tmp, "no.tsv"),
                                  "--db", os.path.join(self.tmp, "no.db")]
                                 + list(extra))
            except SystemExit as e:
                mensaje = str(e)
        return mensaje, salida

    def test_un_byte_distinto_en_el_cache_lo_para_todo(self):
        """El ataque, en miniatura: el GFF cambia y el manifiesto no."""
        self._poblar()
        ruta = os.path.join(self.cache, "refseq_gff.gz")
        crudo = _fixture("refseq_recorte.gff").replace(
            "gene_biotype=protein_coding", "gene_biotype=protein_coding;gene=exoU", 1)
        with open(ruta, "wb") as f:
            f.write(gzip.compress(crudo.encode("utf-8")))
        mensaje, salida = self._corrida()
        self.assertIn("no coincide con su manifiesto", mensaje)
        self.assertIn("refseq_gff.gz", mensaje)
        self.assertFalse(os.path.exists(salida))
        self.assertFalse(os.path.exists(salida + ".tmp"))

    def test_lo_que_el_manifiesto_no_describe_no_se_usa(self):
        self._poblar()
        del self.manifiesto["kegg_pae.txt"]
        with io.open(os.path.join(self.cache, "manifiesto.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            json.dump(self.manifiesto, f)
        mensaje, salida = self._corrida()
        self.assertIn("manifiesto.json no lo describe", mensaje)
        self.assertFalse(os.path.exists(salida))

    def test_el_manifiesto_tiene_que_declarar_la_url_que_se_pide(self):
        """Un cache correcto de OTRA consulta no es un cache de esta."""
        self._poblar()
        self.manifiesto["refseq_gff.gz"]["url"] = "https://otra.parte/x.gff.gz"
        with io.open(os.path.join(self.cache, "manifiesto.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            json.dump(self.manifiesto, f)
        mensaje, _ = self._corrida()
        self.assertIn("Es otra fuente", mensaje)

    def test_el_tamano_solo_no_basta(self):
        """Un cambio que conserva el tamano tambien tiene que morir: si la
        comprobacion fuera por bytes, cambiar `mexT` por `oprN` pasaria."""
        self._poblar()
        crudo = _fixture("refseq_recorte.gff").replace("gene=mexT", "gene=oprN")
        cuerpo = gzip.compress(crudo.encode("utf-8"))
        anotado = self.manifiesto["refseq_gff.gz"]
        with open(os.path.join(self.cache, "refseq_gff.gz"), "wb") as f:
            f.write(cuerpo)
        anotado["bytes"] = len(cuerpo)     # solo el sha delata el cambio
        with io.open(os.path.join(self.cache, "manifiesto.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            json.dump(self.manifiesto, f)
        mensaje, _ = self._corrida()
        self.assertIn("no coincide con su manifiesto", mensaje)

    def test_el_cache_intacto_se_lee_sin_una_queja(self):
        """El contrapeso: un guardian que salta siempre no sirve de nada."""
        self._poblar()
        mensaje, _ = self._corrida()
        # Muere por la invariante de escala (14 genes), que es la siguiente.
        self.assertIn("5700", mensaje)

    # -------------------------------------------- reutilizar, no solo guardar

    def test_con_el_cache_lleno_no_se_sale_a_la_red(self):
        """El contrato define --cache como 'guarda y REUTILIZA'. Medido con un
        cliente que aborta si lo llaman: peticiones evitadas, todas."""
        self._poblar()
        cache = D.Cache(self.cache)
        cliente = _ClienteQueNoContesta()
        cuerpo = cache.obtener("refseq_gff.gz", D.URL_GFF, cliente)
        paginas = list(cache.paginas("uniprot_proteoma",
                                     D.url_uniprot(D.CONSULTA_PROTEOMA), cliente))
        self.assertIn(b"PA2492", gzip.decompress(cuerpo))
        self.assertEqual(1, len(paginas))
        self.assertEqual([], cliente.peticiones)
        self.assertEqual(2, cache.aciertos)
        self.assertEqual(0, cache.descargas)

    def test_refrescar_cache_vuelve_a_pedirlo_todo(self):
        self._poblar()
        cache = D.Cache(self.cache, refrescar=True)
        cliente = _ClienteQueNoContesta()
        with self.assertRaises(AssertionError):
            cache.obtener("refseq_gff.gz", D.URL_GFF, cliente)
        self.assertEqual(1, len(cliente.peticiones))

    def test_un_cache_dudoso_no_se_reutiliza_ni_se_calla(self):
        """Con red, un archivo que no casa con el manifiesto se vuelve a
        pedir. Ni se usa a escondidas ni aborta la corrida."""
        self._poblar()
        with open(os.path.join(self.cache, "refseq_gff.gz"), "ab") as f:
            f.write(b"basura")
        cache = D.Cache(self.cache)
        cliente = _ClienteQueNoContesta()
        with open(os.devnull, "w") as mudo, contextlib.redirect_stdout(mudo):
            with self.assertRaises(AssertionError):
                cache.obtener("refseq_gff.gz", D.URL_GFF, cliente)
        self.assertEqual(1, len(cliente.peticiones))

    def test_la_red_caida_sale_con_el_mensaje_del_contrato(self):
        """ErrorPubMed = no pude preguntar. Antes salia un traceback crudo de
        ocho lineas en vez de la linea que dice que hacer."""
        cache = D.Cache(self.cache)
        with self.assertRaises(SystemExit) as caja:
            cache.obtener("refseq_gff.gz", D.URL_GFF, _ClienteCaido())
        self.assertIn(D.MSG_SIN_FUENTE, str(caja.exception))
        self.assertIn("getaddrinfo", str(caja.exception))

    def test_misma_url_no_depende_del_orden_de_los_parametros(self):
        self.assertTrue(D.misma_url("https://x/y?a=1&b=2", "https://x/y?b=2&a=1"))
        self.assertFalse(D.misma_url("https://x/y?a=1", "https://x/z?a=1"))
        self.assertFalse(D.misma_url("https://x/y?a=1", "https://x/y?a=2"))


class PruebasCorroboracionCruzada(unittest.TestCase):
    """Que las tres bases coincidan es una MEDICION; que la etiqueta diga
    `refseq` no lo es.

    Es el unico guardian que sigue en pie si quien altera el cache altera
    tambien el manifiesto, que es un JSON de texto sin firma.
    """

    def _cargas(self, gff_texto):
        gff, _ = D.analizar_gff(gff_texto)
        kegg = D.analizar_kegg(_fixture("kegg_recorte.txt"))
        uni, _x = D.indexar_uniprot(
            D.analizar_uniprot([_fixture("uniprot_recorte.tsv")]))
        return gff, kegg, uni

    def test_el_recorte_honesto_no_tiene_ni_uno(self):
        gff, kegg, uni = self._cargas(_fixture("refseq_recorte.gff"))
        self.assertEqual([], D.corroborar_simbolos(gff, kegg, uni, {}))

    def test_un_nombre_inyectado_en_el_gff_sale_solo(self):
        """La forma exacta del ataque: `gene=` sobre un locus que RefSeq deja
        sin simbolo. PA3678 no tiene simbolo en ninguna de las tres fuentes,
        asi que un `exoU` puesto ahi no lo respalda nadie."""
        texto = _fixture("refseq_recorte.gff").replace(
            "locus_tag=PA3678", "gene=exoU;locus_tag=PA3678")
        gff, kegg, uni = self._cargas(texto)
        self.assertEqual([("PA3678", "exoU")],
                         D.corroborar_simbolos(gff, kegg, uni, {}))

    def test_el_script_no_escribe_cuando_se_pasa_del_limite(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cache = os.path.join(tmp, "cache")
        os.makedirs(cache)
        prueba = PruebasCacheVerificado("test_misma_url_no_depende_del_orden_de_los_parametros")
        prueba.tmp, prueba.cache, prueba.manifiesto = tmp, cache, {}
        prueba._poblar()
        texto = _fixture("refseq_recorte.gff").replace(
            "locus_tag=PA3678", "gene=exoU;locus_tag=PA3678")
        prueba._escribir("refseq_gff.gz",
                         gzip.compress(texto.encode("utf-8")), D.URL_GFF)
        salida = os.path.join(tmp, "genes.tsv")
        viejo = D.LIMITE_SIN_CORROBORAR
        D.LIMITE_SIN_CORROBORAR = 0
        try:
            with open(os.devnull, "w") as mudo, contextlib.redirect_stdout(mudo):
                mensaje = D.main(["--sin-red", "--cache", cache,
                                  "--salida", salida,
                                  "--operones", os.path.join(tmp, "op.tsv"),
                                  "--collectf", os.path.join(tmp, "co.tsv"),
                                  "--manual", os.path.join(tmp, "no.tsv"),
                                  "--db", os.path.join(tmp, "no.db")])
        finally:
            D.LIMITE_SIN_CORROBORAR = viejo
        self.assertIn("PA3678 = exoU", mensaje)
        self.assertIn("no aparecen ni en KEGG ni en UniProt", mensaje)
        self.assertFalse(os.path.exists(salida))
        self.assertFalse(os.path.exists(salida + ".tmp"))


class PruebasEntidadesManuales(unittest.TestCase):
    """`complejo` y `familia` contra el GFF.

    Las filas de clase `alias` llevaban dos candados desde el principio y
    estas dos clases ninguno; el mensaje del primer candado hasta senalaba la
    puerta abierta ('si es una entidad nueva, declarala como complejo o
    familia'). Medido: 14 entidades fabricadas con miembros PA9999|NOEXISTE y
    ZZZZ entraban con `fuente=manual` y codigo 0, y los blancos del oro que
    resolvian subian de 94/110 a 105/110 sin un solo gen nuevo.
    """

    @classmethod
    def setUpClass(cls):
        gff, sitios = D.analizar_gff(_fixture("refseq_recorte.gff"))
        cls.gff = gff
        cls.kegg = D.analizar_kegg(_fixture("kegg_recorte.txt"))
        cls.uni, _ = D.indexar_uniprot(
            D.analizar_uniprot([_fixture("uniprot_recorte.tsv")]))
        cls.pares, cls.moieties = D.analizar_sitios(sitios)

    def _construir(self, *manual):
        filas = [dict(zip(D.COLUMNAS_MANUAL, f)) for f in manual]
        return D.construir_genes(self.gff, self.kegg, self.uni, {}, filas,
                                 set(), self.moieties)

    def _muere(self, fila, trozo):
        with self.assertRaises(SystemExit) as caja:
            self._construir(fila)
        self.assertIn(trozo, str(caja.exception))

    def test_un_miembro_que_no_esta_en_el_gff(self):
        self._muere(["exoU", "complejo", "exoU|ExoU", "PA9999|NOEXISTE",
                     "Inventado a proposito."],
                    "no es un locus tag de PAO1 presente en el GFF")

    def test_un_miembro_que_ni_siquiera_parece_locus_tag(self):
        self._muere(["PirR", "familia", "PirR|pirr", "ZZZZ", "TF: inventado."],
                    "no es un locus tag de PAO1 presente en el GFF")

    def test_un_solo_miembro_es_un_alias(self):
        self._muere(["Algo", "complejo", "Algo", "PA0425", "Un solo miembro."],
                    "usa la clase alias")

    def test_no_puede_hacerse_pasar_por_un_gen(self):
        self._muere(["PA0425", "complejo", "PA0425x", "PA0425|PA0426",
                     "Se hace pasar por gen."],
                    "tiene forma de locus tag")

    def test_no_puede_pisar_el_simbolo_de_un_gen_publico(self):
        self._muere(["mexT", "complejo", "mexT|MexTc", "PA0425|PA0426",
                     "Choca con un simbolo publico."],
                    "choca con el simbolo")

    def test_dos_filas_no_pueden_producir_la_misma_entidad(self):
        with self.assertRaises(SystemExit) as caja:
            self._construir(
                ["Cosa", "complejo", "Cosa", "PA0425|PA0426", "Una."],
                ["Cosa", "familia", "Cosa2", "PA0426|PA0427", "Otra."])
        self.assertIn("ya la declaro otra fila", str(caja.exception))

    def test_tampoco_puede_pisar_un_simbolo_que_puso_la_propia_capa_manual(self):
        """PA3678 no tiene simbolo en ninguna fuente publica, asi que el
        primer filtro (contra el GFF) no ve el choque: la fila de clase alias
        lo bautiza `mexL` en la misma corrida."""
        with self.assertRaises(SystemExit) as caja:
            self._construir(
                ["mexL", "alias", "MexL|PA3678", "", "Bautiza a PA3678."],
                ["mexL", "complejo", "mexLc", "PA0425|PA0426", "Lo pisa."])
        self.assertIn("choca con el simbolo de un gen del diccionario",
                      str(caja.exception))

    def test_la_marca_de_tf_no_se_concede_por_escribir_dos_letras(self):
        """`es_tf=true` se daba porque la justificacion empezara con 'TF:'.
        Ahora la tiene que sostener algun miembro con evidencia publica."""
        self._muere(["Bomba", "complejo", "Bomba", "PA0425|PA0426",
                     "TF: me lo invento."],
                    "ninguno de sus miembros")

    def test_un_complejo_legitimo_si_entra(self):
        """Contrapeso: MexT (PA2492) lleva marca de TF por GO en el recorte,
        asi que un complejo que lo incluya puede declararse TF."""
        filas, indices, _ = self._construir(
            ["Cosa", "complejo", "Cosa|cosa", "PA2492|PA0425", "TF: legitimo."])
        fila = [f for f in filas if f["simbolo"] == "Cosa"][0]
        self.assertEqual("", fila["locus_tag"])
        self.assertEqual("complejo", fila["tipo"])
        self.assertEqual("true", fila["es_tf"])
        self.assertEqual("manual", fila["fuente"])
        self.assertIn("Cosa", indices["manual"])


class PruebasLoQueElInformeTieneQueDecir(unittest.TestCase):
    """Los tres conteos que existen para que nadie tenga que deducir a mano si
    una defensa esta haciendo algo."""

    def test_palabras_comunes_hoy_no_cambia_ni_una_fila(self):
        """`palabras_comunes.txt` es inerte y el script lo publica. Un revisor
        que lee 41 entradas comentadas una por una concluye que ahi hay una
        defensa activa; medido, las filas sensibles SOLO por la lista son 0,
        porque las 41 tienen tres caracteres o menos y la clausula de longitud
        ya las cubre. Y no faltan palabras largas: ninguna de las 1931
        superficies alfabeticas de cuatro caracteres o mas del diccionario es
        una palabra inglesa."""
        filas = D.leer_tsv(GENES, D.COLUMNAS_GENES)
        palabras = D.leer_palabras_comunes(D.RUTA_PALABRAS)
        por_longitud, solo_lista = D.sensibles_por_motivo(filas, palabras)
        sensibles = sum(1 for f in filas if f["sensible_mayusculas"] == "true")
        self.assertEqual(0, solo_lista)
        self.assertEqual(sensibles, por_longitud)
        largas = {x for f in filas for x in D.superficies_de(f)
                  if len(x) >= 4 and x.isalpha()}
        self.assertEqual(set(), {x.lower() for x in largas} & palabras)

    def test_pero_el_mecanismo_de_la_lista_sigue_vivo(self):
        """Contrapeso del anterior: si un dia entra una superficie larga que
        es palabra inglesa, la lista tiene que actuar. Un guardian inerte y un
        guardian roto se ven igual desde fuera si nadie prueba el mecanismo."""
        fila = _fila_valida(locus_tag="PA0001", simbolo="operon",
                            sensible_mayusculas="true")
        self.assertTrue(D.es_sensible(fila, {"operon"}))
        self.assertFalse(D.es_sensible(fila, set()))
        self.assertEqual((0, 1), D.sensibles_por_motivo([fila], {"operon"}))

    def test_los_tf_sensibles_sin_forma_de_proteina_son_los_tres_medidos(self):
        """Un TF de tres letras es sensible, y `Lexico` no sintetiza la forma
        de proteina de una fila sensible, asi que cada vez que el articulo
        escribe `Rho` no hay mencion y no hay candidato. Hoy son cuatro genes;
        `ada` tiene fila en la capa manual y los otros tres NO, a proposito.

        La medicion que lo decide, sobre los 918 textos completos con la regex
        (?<![A-Za-z0-9-])X(?![A-Za-z0-9-]) sensible a mayusculas:

        - `Ada`: 6 menciones en 2 documentos, las 6 el regulador ('Ada
          negatively regulates its own transcription'). Lleva fila.
        - `Rho`: 21 menciones en 9 documentos, y **la mitad no son PA5239**
          sino la GTPasa eucariota que ExoS, ExoT y ExoU atacan ('Rho
          GTPases', 'Rho GAP activity of ExoS'). Anadir la superficie
          fabricaria pares falsos `Rho -> exoS` en el mismo corpus que se
          quiere medir.
        - `Arr`: 5 menciones en 2 documentos y las 5 lo describen como
          fosfodiesterasa de c-di-GMP, o sea que confirman que su marca de TF
          --que se sostiene solo en `producto_refseq`-- es un falso positivo.
        - `Mfd`: 0 menciones. No hay nada que recuperar.

        Si alguien les pone fila, esta prueba falla y hay que volver a decidir
        con la medicion delante."""
        filas = D.leer_tsv(GENES, D.COLUMNAS_GENES)
        sueltos = D.tf_sin_forma_proteina(filas)
        self.assertEqual([("PA2818", "arr", "Arr"), ("PA3002", "mfd", "Mfd"),
                          ("PA5239", "rho", "Rho")], sueltos)
        ada = _fila(filas, "PA2118")
        self.assertIn("Ada", D.superficies_de(ada))
        self.assertIn("manual", ada["fuente"])

    def test_simbolos_repetidos_ve_lo_que_contar_ambiguas_no_puede(self):
        """`contar_ambiguas()` mide con la misma expresion que colisiona
        (`simbolo or locus_tag`), asi que dos genes con el mismo simbolo dan la
        misma clave y `previo != idc` nunca es cierto: son invisibles para
        ella. Es el mismo defecto que ordena todo este trabajo."""
        filas = [_fila_valida(locus_tag="PA0326", simbolo="potA"),
                 _fila_valida(locus_tag="PA0603", simbolo="potA")]
        self.assertEqual(set(), D.contar_ambiguas(filas))
        self.assertEqual({"potA": ["PA0326", "PA0603"]},
                         D.simbolos_repetidos(filas))

    def test_el_diccionario_versionado_publica_sus_colisiones(self):
        filas = D.leer_tsv(GENES, D.COLUMNAS_GENES)
        repetidos = D.simbolos_repetidos(filas)
        self.assertIn("potA", repetidos)
        self.assertEqual(3, len(repetidos["potA"]))
        self.assertLess(len(repetidos), 30)


# --------------------------------------- el diccionario versionado, de verdad

class PruebasDelDiccionarioVersionado(unittest.TestCase):
    """Sobre `etapa2/genes_pao1.tsv` tal como esta en el repositorio."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(GENES):
            # No se salta: `genes_pao1.tsv` es un dato VERSIONADO (§0.1), asi
            # que si falta es que alguien lo borro o lo movio, y las dos
            # coberturas del oro son justo lo que no puede dejar de medirse
            # en silencio. Una prueba saltada se lee como una prueba que pasa.
            raise AssertionError(
                "Falta etapa2/genes_pao1.tsv, que va versionado. Corre "
                "python etapa2/construir_diccionario.py --sin-red")
        cls.filas = D.leer_tsv(GENES, D.COLUMNAS_GENES)
        cls.lex = Lexico.cargar(GENES, OPERONES)
        with open(ORO, encoding="utf-8") as f:
            cls.oro = list(csv.DictReader(f, delimiter="\t"))

    @classmethod
    def resolver(cls, nombre):
        """El id canonico al que `Lexico` manda ese nombre, o None.

        Se pasa por `menciones()` y no por `superficies()` a proposito: lo que
        importa no es que la cadena este en algun diccionario interno, sino que
        el reconocedor que usa la etapa 2 la encuentre.
        """
        for _, _, superficie, idc, _ in cls.lex.menciones(nombre):
            if superficie == nombre:
                return idc
        return None

    # --- los dos umbrales duros del contrato ---

    def test_cobertura_de_los_tfs_del_oro(self):
        """>= 90 % de los 55 TFs del oro resuelven a una entidad canonica.

        Es verificacion cruzada, no fuente: si baja, la exhaustividad de la
        etapa 5 medira que el diccionario no conoce los nombres, y se leera
        como que el pipeline no encuentra las relaciones.
        """
        tfs = sorted({fila["tf"] for fila in self.oro})
        self.assertEqual(55, len(tfs))
        faltan = [t for t in tfs if self.resolver(t) is None]
        cobertura = (len(tfs) - len(faltan)) / float(len(tfs))
        self.assertGreaterEqual(
            cobertura, 0.90,
            "Solo %d de %d TFs del oro resuelven (%.1f %%). No resuelven: %s"
            % (len(tfs) - len(faltan), len(tfs), 100 * cobertura, faltan))

    def test_cobertura_de_los_locus_tags_que_cita_el_oro(self):
        """>= 95 % de los locus tags PA que cita la columna `alias` del oro
        existen en el diccionario y no contradicen su simbolo.

        Un locus tag pasa si (a) resuelve, y (b) ningun nombre que el oro
        empareje con el por `nombre = PAxxxx` resuelve a OTRA entidad. Los
        nombres de operon quedan fuera de (b): ahi el oro empareja el operon
        con su primer gen (`mexAB-oprM = PA0425`), que es otra cosa y no una
        contradiccion.

        Falla conocida hoy, y es del dominio y no del parseo: el oro dice
        `poxB = PA5514` (la beta-lactamasa) y RefSeq le da el simbolo `poxB` a
        PA5297 (la piruvato deshidrogenasa). Son dos literaturas usando el
        mismo nombre.
        """
        emparejados = {}
        locus_citados = set()
        for fila in self.oro:
            locus_citados.update(LOCUS_EN_TEXTO.findall(fila["alias"]))
            for nombre in (fila["tf"], fila["blanco"]):
                for m in re.finditer(
                        r"\b%s\s*=\s*(PA\d{4}(?:\.\d)?)" % re.escape(nombre),
                        fila["alias"]):
                    emparejados.setdefault(m.group(1), set()).add(nombre)
        self.assertEqual(104, len(locus_citados))
        malos = []
        for locus in sorted(locus_citados):
            destino = self.resolver(locus)
            if destino is None:
                malos.append("%s no existe" % locus)
                continue
            for nombre in emparejados.get(locus, ()):
                otro = self.resolver(nombre)
                if otro is not None and not self.lex.es_operon(otro) \
                        and otro != destino:
                    malos.append("%s -> %s pero %s -> %s"
                                 % (locus, destino, nombre, otro))
        cobertura = (len(locus_citados) - len(malos)) / float(len(locus_citados))
        self.assertGreaterEqual(
            cobertura, 0.95,
            "Solo %.1f %% de los locus tags del oro cuadran: %s"
            % (100 * cobertura, malos))

    # --- las que reconocen un diccionario fabricado ---

    def test_ninguna_fila_declara_procedencia_de_oro(self):
        for fila in self.filas:
            self.assertNotIn("oro", fila["fuente"].split("|"),
                             "Fila %s declara procedencia del patron de oro."
                             % fila["locus_tag"])

    def test_toda_fila_declara_una_procedencia_del_enum(self):
        for fila in self.filas:
            tokens = [t for t in fila["fuente"].split("|") if t]
            self.assertTrue(tokens, "Fila %s sin procedencia." % fila)
            for token in tokens:
                self.assertIn(token, D.FUENTES_VALIDAS)
            for token in [t for t in fila["fuente_tf"].split("|") if t]:
                self.assertIn(token, D.FUENTES_TF_VALIDAS)

    def test_las_filas_son_utiles_y_no_relleno(self):
        """El ataque demostrado fue rellenar el archivo con filas vacias hasta
        5700 para desactivar un guardian que contaba LINEAS. Aqui se cuentan
        filas con contenido de verdad."""
        self.assertGreaterEqual(len(self.filas), 5000)
        con_producto = sum(1 for f in self.filas if f["producto"].strip())
        self.assertGreaterEqual(
            con_producto, 5000,
            "Solo %d de %d filas traen producto. Un archivo con miles de filas "
            "vacias tiene el tamano de un diccionario y el contenido de una "
            "lista corta." % (con_producto, len(self.filas)))

    def test_el_diccionario_sabe_mucho_mas_que_el_oro(self):
        """El vocabulario del oro son 165 nombres; el diccionario tiene del
        orden de 5700 entidades. Un diccionario hecho copiando el oro tiene
        165 y se delata aqui a gritos."""
        vocabulario = {fila["tf"] for fila in self.oro}
        vocabulario |= {fila["blanco"] for fila in self.oro}
        self.assertEqual(165, len(vocabulario),
                         "El oro nombra 55 TFs y 110 blancos; si eso cambia, "
                         "los umbrales de esta prueba se recalculan.")
        # A partir de aqui se compara en minusculas: el oro escribe el TF en
        # forma de proteina (`MexT`) y el blanco en forma de gen (`mexT`), asi
        # que `MexR` y `mexR` son la misma entidad contada dos veces.
        bajo = {v.lower() for v in vocabulario}
        # Solo cuentan las filas con contenido: un archivo relleno de filas
        # vacias con locus tags correlativos aportaria miles de "entidades"
        # que no son nada, y ese fue justo el ataque demostrado.
        propias = {(f["simbolo"] or f["locus_tag"]).lower() for f in self.filas
                   if f["producto"].strip()}
        fuera = propias - bajo
        self.assertGreaterEqual(
            len(fuera), 4000,
            "El diccionario solo aporta %d entidades que el oro no nombra. Eso "
            "no es un diccionario del genoma, es una copia del patron de oro."
            % len(fuera))

    # --- defectos concretos que no pueden volver ---

    def test_pa2390_es_pvdt_y_no_mexl(self):
        """`auditar_signo.py:80` afirmaba `"MexL": {"alias": ["mexL",
        "PA2390"]}`. mexL es PA3678, contiguo y divergente de PA3677 (mexJ) y
        PA3676 (mexK); PA2390 es biosintesis de pioverdina, otro subsistema
        entero."""
        self.assertEqual("pvdT", self.resolver("PA2390"))
        self.assertEqual("mexL", self.resolver("PA3678"))
        self.assertEqual("mexL", self.resolver("mexL"))

    def test_el_operon_de_la_hebra_menos_existe(self):
        self.assertEqual("mexCD-oprJ", self.resolver("mexCD-oprJ"))
        self.assertEqual("mexJK", self.resolver("mexJK"))

    def test_los_tres_que_el_oro_llama_tf_y_no_lo_son(self):
        """ExsD es antiactivador, FpvR es anti-sigma y RsmA une ARN. En los
        tres casos la marca tiene razon y el oro no, y eso se documenta, no se
        arregla: si alguien los marca a mano para que la evaluacion salga
        mejor, esta prueba lo dice."""
        for nombre in ("exsD", "fpvR", "rsmA"):
            idc = self.resolver(nombre)
            self.assertIsNotNone(idc, nombre)
            self.assertFalse(
                self.lex.es_tf(idc),
                "%s quedo marcado como TF. No une ADN; el patron de oro lo "
                "trata como TF y se equivoca. Ver el docstring de "
                "construir_diccionario.py." % nombre)

    def test_collectf_trae_pares_con_pmids(self):
        filas = D.leer_tsv(COLLECTF, D.COLUMNAS_COLLECTF)
        self.assertGreater(len(filas), 200)
        self.assertGreaterEqual(len({f["tf"] for f in filas}), 30)
        for fila in filas:
            self.assertTrue(D.LOCUS_LAXO.match(fila["blanco"]), fila)
            self.assertIn(fila["en_corpus"], ("true", "false"))

    def test_los_operones_declaran_procedencia_mecanica(self):
        for fila in D.leer_tsv(OPERONES, D.COLUMNAS_OPERONES):
            self.assertIn(fila["fuente"], ("refseq_adyacencia", "manual"))
            self.assertGreaterEqual(len(fila["miembros"].split("|")), 2)
            self.assertEqual(len(fila["miembros"].split("|")),
                             len(fila["locus_tags"].split("|")))


if __name__ == "__main__":
    unittest.main()
