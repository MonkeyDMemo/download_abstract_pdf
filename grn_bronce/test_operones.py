# -*- coding: utf-8 -*-
"""El catalogo de operones, su expansion y las dos capas en la salida.

Lo que estas pruebas vigilan es que las dos capas no se fundan en una. El
bronce guarda la mencion del operon tal como el articulo la escribio Y su
expansion a locus tags, en columnas separadas: el texto dice `mexEF-oprN` y el
grafo necesita PA2493, PA2494, PA2495, y ninguna de las dos sustituye a la
otra. Una sola linea que aplanara el operon a sus genes al guardarlo perderia
lo que el articulo dijo, y otra que lo dejara sin expandir dejaria al paso 3
sin nodos.

La segunda cosa que vigilan es que la expansion sea **solo por tabla**. Si un
dia alguien la deduce del nombre, `pqsABCDE` expandiria a cinco genes sin que
nadie lo haya escrito en ningun recurso, y un operon inventado desde el texto
--`lasRIAB`, que `etapa2/lexico.py` acuna solo-- se convertiria en tres genes
que el corpus nunca nombro.

Fixtures locales y minimas: ningun recurso real, ninguna base real.

    python -m unittest discover .
"""

import io
import os
import sys
import tempfile
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.join(_RAIZ, "etapa2"))

from grn_bronce import db as bdb                    # noqa: E402
from grn_bronce import exportar                     # noqa: E402
from grn_bronce import identificar                  # noqa: E402
from grn_bronce import operones as OP               # noqa: E402
from grn_bronce import vocabulario                  # noqa: E402

# Tres operones de verdad y uno sin locus tags, para que la expansion tenga
# algo que no expandir. Las columnas son las del contrato, en su orden.
FIXTURE_OPERONES = u"""operon\tmiembros\tlocus_tags\tfuente
mexEF-oprN\tmexE|mexF|oprN\tPA2493|PA2494|PA2495\trefseq_adyacencia
mexAB-oprM\tmexA|mexB|oprM\tPA0425|PA0426|PA0427\trefseq_adyacencia
pqsABCDE\tpqsA|pqsB|pqsC|pqsD|pqsE\tPA0996|PA0997|PA0998|PA0999|PA1000\trefseq
solosimbolos\tgenX|genY\t\tmanual
vacio\t\t\tmanual
"""

FIXTURE_GENES = u"""locus_tag\tsimbolo\talias\ttipo\tproducto\tes_tf\tfuente_tf\tfuente\tsensible_mayusculas
PA2492\tmexT\t\tcds\tregulator\ttrue\tmanual\trefseq\tfalse
PA2493\tmexE\t\tcds\tefflux\tfalse\t\trefseq\tfalse
PA2494\tmexF\t\tcds\tefflux\tfalse\t\trefseq\tfalse
PA2495\toprN\t\tcds\tporin\tfalse\t\trefseq\tfalse
PA0996\tpqsA\t\tcds\tqs\tfalse\t\trefseq\tfalse
PA0997\tpqsB\t\tcds\tqs\tfalse\t\trefseq\tfalse
PA0998\tpqsC\t\tcds\tqs\tfalse\t\trefseq\tfalse
PA0999\tpqsD\t\tcds\tqs\tfalse\t\trefseq\tfalse
PA1000\tpqsE\t\tcds\tqs\tfalse\t\trefseq\tfalse
"""


def _escribir(carpeta, nombre, contenido):
    ruta = os.path.join(carpeta, nombre)
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(contenido)
    return ruta


class PruebasCatalogo(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = _escribir(self.tmp.name, "operones.tsv", FIXTURE_OPERONES)
        self.cat = OP.Catalogo.cargar(self.ruta)

    def test_expande_a_locus_tags_y_solo_a_locus_tags(self):
        """La columna `genes_expandidos` alimenta el grafo, que se arma sobre
        locus tags. Si se colaran simbolos, el paso 3 tendria dos nodos para el
        mismo gen y no sabria que son el mismo."""
        self.assertEqual(self.cat.locus_tags("mexEF-oprN"),
                         ["PA2493", "PA2494", "PA2495"])

    def test_el_nombre_no_distingue_mayusculas(self):
        """`MexEF-OprN` es la forma proteina del mismo operon. Distinguirlas
        perderia la mitad de las menciones."""
        self.assertEqual(self.cat.locus_tags("MexEF-OprN"),
                         self.cat.locus_tags("mexEF-oprN"))
        self.assertTrue(self.cat.tiene("MEXEF-OPRN"))

    def test_un_operon_que_la_tabla_no_conoce_no_expande(self):
        """Es el caso que el informe tiene que delatar, no tapar. `lasRIAB` lo
        acuna `lexico` leyendo el texto; el catalogo no lo tiene."""
        self.assertFalse(self.cat.tiene("lasRIAB"))
        self.assertEqual(self.cat.locus_tags("lasRIAB"), [])
        self.assertEqual(self.cat.n_genes("lasRIAB"), 0)

    def test_la_expansion_no_se_deduce_del_nombre(self):
        """`pqsAE` se parece a un operon y sus dos miembros existen en el
        diccionario, pero la tabla no lo trae. Deducirlo seria fabricar dos
        genes que nadie escribio en ningun recurso."""
        self.assertEqual(self.cat.locus_tags("pqsAE"), [])

    def test_una_fila_sin_miembros_no_entra(self):
        """Un operon de cero genes no expande nada y solo ensucia el conteo."""
        self.assertFalse(self.cat.tiene("vacio"))

    def test_una_fila_sin_locus_tags_se_conoce_pero_no_expande(self):
        """Conocido y expandible son dos cosas distintas: la fila existe, asi
        que no es un hueco del catalogo, pero no aporta nodos al grafo."""
        self.assertTrue(self.cat.tiene("solosimbolos"))
        self.assertEqual(self.cat.locus_tags("solosimbolos"), [])

    def test_expandir_varios_une_sin_repetir_y_ordenado(self):
        salida = self.cat.expandir_varios(
            ["mexEF-oprN", "pqsABCDE", "mexEF-oprN", "noexiste"])

        self.assertEqual(salida, ["PA0996", "PA0997", "PA0998", "PA0999",
                                  "PA1000", "PA2493", "PA2494", "PA2495"])

    def test_sin_archivo_el_catalogo_queda_vacio_y_no_revienta(self):
        """Sin tabla, la columna `operones` sigue diciendo que nombro el texto
        --que es informacion del texto-- y solo se pierde la expansion."""
        cat = OP.Catalogo.cargar(os.path.join(self.tmp.name, "no_existe.tsv"))

        self.assertEqual(len(cat), 0)
        self.assertEqual(cat.locus_tags("mexEF-oprN"), [])

    def test_un_encabezado_distinto_falla_en_vez_de_leer_mal(self):
        ruta = _escribir(self.tmp.name, "malo.tsv",
                         u"operon\tgenes\tfuente\nx\ty\tz\n")

        with self.assertRaises(ValueError):
            OP.Catalogo.cargar(ruta)


class PruebasContratoConElEvaluador(unittest.TestCase):
    """`etapa2/evaluar_oro.py` delega aqui su expansion. Si estas cambian, sus
    cifras cambian sin que nadie haya tocado el evaluador."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = _escribir(self.tmp.name, "operones.tsv", FIXTURE_OPERONES)
        self.mapa, _ = OP.desde_filas(OP._leer_tsv(self.ruta))

    def test_el_mapa_mezcla_simbolos_y_locus_tags_en_minusculas(self):
        """Es lo que `cargar_operones()` construia y lo que el emparejamiento
        del evaluador espera: las referencias nombran los extremos de las dos
        formas."""
        self.assertEqual(sorted(self.mapa["mexef-oprn"]),
                         ["mexe", "mexf", "oprn",
                          "pa2493", "pa2494", "pa2495"])

    def test_miembros_de_tabla_descarta_el_propio_nombre(self):
        """Un operon no se empareja consigo mismo por la via de la expansion."""
        mapa = {"abc": ["abc", "gen1"]}

        self.assertEqual(OP.miembros_de_tabla("abc", mapa),
                         frozenset(["gen1"]))

    def test_sin_tabla_no_expande(self):
        self.assertEqual(OP.miembros_de_tabla("mexAB-oprM", {}), frozenset())

    def test_evaluar_oro_sigue_dando_lo_mismo_al_delegar(self):
        """La delegacion tiene que ser invisible: mismo mapa, misma expansion."""
        import evaluar_oro as O

        mapa, existe = O.cargar_operones(self.ruta)

        self.assertTrue(existe)
        self.assertEqual(mapa, self.mapa)
        self.assertEqual(O.miembros_de_tabla("mexEF-oprN", mapa),
                         OP.miembros_de_tabla("mexEF-oprN", mapa))


class PruebasTipoDeMencion(unittest.TestCase):
    """Una mencion de operon se guarda COMO operon, no como gen."""

    def setUp(self):
        from lexico import Lexico
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        g = _escribir(self.tmp.name, "genes.tsv", FIXTURE_GENES)
        o = _escribir(self.tmp.name, "operones.tsv", FIXTURE_OPERONES)
        self.lex = Lexico.cargar(g, o)
        self.vocab = vocabulario.Vocabulario.cargar()
        self.locus = {"mexT": "PA2492", "mexE": "PA2493", "PA2492": "PA2492"}

    def _menciones(self, oracion):
        filas, _, _, _ = identificar._menciones_de_oracion(
            oracion, self.lex, self.vocab, self.locus)
        return dict((f["texto"], (f["tipo"], f["id_normalizado"]))
                    for f in filas)

    def test_el_operon_no_se_guarda_como_gen(self):
        m = self._menciones("MexT regulates mexEF-oprN expression in PAO1.")

        self.assertEqual(m["mexEF-oprN"], ("operon", "mexEF-oprN"))

    def test_conserva_la_forma_textual_intacta(self):
        """La superficie es lo que escribio el autor, con sus mayusculas. Es la
        unica capa que dice que hubo de verdad en el articulo."""
        m = self._menciones("Expression of MexEF-OprN was increased.")

        self.assertIn("MexEF-OprN", m)
        self.assertEqual(m["MexEF-OprN"][0], "operon")

    def test_el_id_normalizado_del_operon_es_su_nombre_no_un_locus_tag(self):
        """Si fuera un locus tag habria que elegir cual de los tres, y la
        eleccion seria una invencion. El nombre no lo es."""
        m = self._menciones("The mexEF-oprN operon was induced.")

        self.assertEqual(m["mexEF-oprN"][1], "mexEF-oprN")
        self.assertFalse(m["mexEF-oprN"][1].startswith("PA"))

    def test_un_gen_normal_sigue_yendo_a_locus_tag(self):
        m = self._menciones("MexT binds the promoter and activates it.")

        self.assertEqual(m["MexT"], ("proteina", "PA2492"))

    def test_el_operon_sintetico_tambien_es_operon(self):
        """El caso que importa: un operon que la tabla NO trae.

        `pqsAE` no esta en `FIXTURE_OPERONES`; lo acuna `lexico` al ver que sus
        dos miembros existen en el diccionario. Tiene que salir como operon
        igualmente, porque es justo lo que lo hace aparecer despues en el
        informe de huecos del catalogo. Si se probara con `pqsABCDE`, que si
        esta en la tabla, la prueba pasaria por la via de la tabla y no
        comprobaria nada de la concatenacion.
        """
        self.assertNotIn("pqsAE\t", FIXTURE_OPERONES)

        m = self._menciones("The pqsAE genes control quinolone synthesis.")

        self.assertEqual(m["pqsAE"][0], "operon")
        self.assertEqual(m["pqsAE"][1], "pqsAE")

    def test_el_operon_de_la_tabla_tambien_sale_como_operon(self):
        """El otro camino: `pqsABCDE` si esta en la tabla y se resuelve por
        ella. Los dos caminos tienen que dar el mismo tipo."""
        m = self._menciones("The pqsABCDE operon controls quinolone synthesis.")

        self.assertEqual(m["pqsABCDE"][0], "operon")


class PruebasSalida(unittest.TestCase):
    """Las dos capas en la salida, sobre una base de memoria."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cat = OP.Catalogo.cargar(
            _escribir(self.tmp.name, "operones.tsv", FIXTURE_OPERONES))
        self.con = bdb.conectar(":memory:")
        self.addCleanup(self.con.close)
        self.con.execute(
            """INSERT INTO documentos (pmid, titulo, anio, extraido_en)
               VALUES ('1', 'Un titulo', '2020', ?)""", (bdb.ahora(),))
        self.corrida = bdb.abrir_corrida(self.con, "1", "m", "1")
        self.unidad = bdb.guardar_unidad(self.con, self.corrida, {
            "pmid": "1", "fuente_texto": "abstract", "seccion": "abstract",
            "num_oracion": 0,
            "texto": "MexT activates mexEF-oprN and pqsABCDE in PAO1.",
            "offset_ini": 0, "offset_fin": 46, "contiguo": True})
        ids = bdb.guardar_menciones(self.con, self.corrida, "m", self.unidad, [
            {"tipo": "proteina", "texto": "MexT", "id_normalizado": "PA2492",
             "offset_ini": 0, "offset_fin": 4},
            {"tipo": "operon", "texto": "mexEF-oprN",
             "id_normalizado": "mexEF-oprN", "offset_ini": 15,
             "offset_fin": 25},
            {"tipo": "operon", "texto": "pqsABCDE",
             "id_normalizado": "pqsABCDE", "offset_ini": 30, "offset_fin": 38},
        ])
        bdb.guardar_candidata(self.con, self.corrida, "m", self.unidad, {
            "disparador": "activates", "signo_sugerido": "+",
            "regulador_candidato": "mexT",
            "blanco_candidato": "mexEF-oprN", "score": 0.5}, ids)
        self.con.commit()

    def _fila(self):
        filas = exportar.filas_candidatas(self.con, bdb, self.corrida,
                                          self.cat)
        self.assertEqual(len(filas), 1)
        return filas[0]

    def test_la_columna_operones_trae_la_forma_del_texto(self):
        self.assertEqual(self._fila()["operones"], "mexEF-oprN;pqsABCDE")

    def test_la_columna_genes_expandidos_trae_los_locus_tag(self):
        self.assertEqual(
            self._fila()["genes_expandidos"],
            "PA0996;PA0997;PA0998;PA0999;PA1000;PA2493;PA2494;PA2495")

    def test_la_columna_genes_sigue_trayendo_lo_que_ya_traia(self):
        """Antes de que el operon tuviera tipo propio caia en 'gen' o
        'proteina' y esta columna lo traia. Sacarlo ahora cambiaria la salida
        sin que nada hubiera mejorado."""
        self.assertEqual(self._fila()["genes"], "MexT;mexEF-oprN;pqsABCDE")

    def test_la_expansion_no_se_mezcla_con_los_genes(self):
        """Son capas distintas: lo que dice el texto y lo que dice el catalogo.
        Si se mezclaran, nadie podria volver a separarlas."""
        fila = self._fila()

        for locus in ("PA2493", "PA0996"):
            self.assertNotIn(locus, fila["genes"])
        self.assertNotIn("mexEF-oprN", fila["genes_expandidos"])

    def test_no_se_multiplican_las_filas_por_gen_del_operon(self):
        """Una oracion sobre un operon de cinco genes es una fila, no cinco."""
        filas = exportar.filas_candidatas(self.con, bdb, self.corrida,
                                          self.cat)

        self.assertEqual(len(filas), 1)

    def test_el_blanco_operon_se_queda_como_operon(self):
        self.assertEqual(self._fila()["blanco_candidato"], "mexEF-oprN")

    def test_un_operon_capitalizado_ya_no_cuenta_como_proteina(self):
        """La unica columna vieja cuyo contenido cambia, y queda fijada aqui.

        `MexAB-OprM` empieza por mayuscula, asi que antes `_es_proteina()` lo
        mandaba a tipo 'proteina' y aparecia en esta columna. Un operon no es
        una proteina, asi que sale. Medido sobre el corpus: cambia 1 468 de las
        29 659 filas. La superficie no se pierde --sigue en `genes` y ahora
        tambien en `operones`--, pero el cambio tiene que ser explicito y no
        una sorpresa para quien diffee los dos CSV.
        """
        unidad = bdb.guardar_unidad(self.con, self.corrida, {
            "pmid": "1", "fuente_texto": "abstract", "seccion": "abstract",
            "num_oracion": 1, "texto": "MexAB-OprM was overexpressed in nalB.",
            "offset_ini": 0, "offset_fin": 37, "contiguo": True})
        ids = bdb.guardar_menciones(self.con, self.corrida, "m", unidad, [
            {"tipo": "operon", "texto": "MexAB-OprM",
             "id_normalizado": "mexAB-oprM", "offset_ini": 0,
             "offset_fin": 10},
            {"tipo": "proteina", "texto": "MexT", "id_normalizado": "PA2492",
             "offset_ini": 30, "offset_fin": 34}])
        bdb.guardar_candidata(self.con, self.corrida, "m", unidad, {
            "disparador": "", "signo_sugerido": "",
            "regulador_candidato": "", "blanco_candidato": "",
            "score": 0.0}, ids)
        self.con.commit()

        fila = [f for f in exportar.filas_candidatas(
            self.con, bdb, self.corrida, self.cat) if f["num_oracion"] == 1][0]

        self.assertEqual(fila["proteinas"], "MexT")
        self.assertIn("MexAB-OprM", fila["genes"])
        self.assertEqual(fila["operones"], "MexAB-OprM")
        self.assertEqual(fila["genes_expandidos"],
                         "PA0425;PA0426;PA0427")

    def test_el_informe_separa_lo_que_falta_del_catalogo(self):
        filas = exportar.filas_operones(self.con, bdb, self.corrida, self.cat)
        por_nombre = dict((f["operon"], f) for f in filas)

        self.assertEqual(por_nombre["mexEF-oprN"]["en_catalogo"], "si")
        self.assertEqual(por_nombre["mexEF-oprN"]["n_genes_catalogo"], 3)
        self.assertEqual(por_nombre["mexEF-oprN"]["n_menciones"], 1)
        self.assertEqual(por_nombre["mexEF-oprN"]["n_candidatas"], 1)

    def test_un_operon_fuera_del_catalogo_sale_marcado_y_sin_genes(self):
        cat_corto = OP.Catalogo.cargar(_escribir(
            self.tmp.name, "corto.tsv",
            u"operon\tmiembros\tlocus_tags\tfuente\n"
            u"mexEF-oprN\tmexE\tPA2493\trefseq\n"))

        filas = exportar.filas_operones(self.con, bdb, self.corrida, cat_corto)
        por_nombre = dict((f["operon"], f) for f in filas)

        self.assertEqual(por_nombre["pqsABCDE"]["en_catalogo"], "no")
        self.assertEqual(por_nombre["pqsABCDE"]["n_genes_catalogo"], 0)
        self.assertEqual(por_nombre["pqsABCDE"]["genes_expandidos"], "")

    def test_el_operon_no_entra_en_genes_locus_tag(self):
        """Esa columna trae locus tags, y el id de un operon es su nombre.
        Si entrara, el paso 3 tendria un nodo `mexEF-oprN` mezclado con los
        PA####. Los locus tag del operon tienen su propia columna."""
        fila = self._fila()

        self.assertEqual(fila["genes_locus_tag"], "PA2492")
        for op in ("mexEF-oprN", "pqsABCDE"):
            self.assertNotIn(op, fila["genes_locus_tag"])

    def test_un_catalogo_vacio_que_se_pasa_se_respeta(self):
        """`Catalogo` define `__len__`, asi que uno vacio es falsy. Con un `or`
        en vez de `is None`, el exportador lo habria cambiado en silencio por
        el catalogo real de recursos/ y habria expandido igual."""
        vacio = OP.Catalogo.cargar(os.path.join(self.tmp.name, "no_hay.tsv"))
        self.assertEqual(len(vacio), 0)

        filas = exportar.filas_operones(self.con, bdb, self.corrida, vacio)
        cand = exportar.filas_candidatas(self.con, bdb, self.corrida, vacio)

        self.assertEqual(sorted(set(f["en_catalogo"] for f in filas)), ["no"])
        self.assertEqual(cand[0]["genes_expandidos"], "")

    def test_cuenta_el_operon_de_una_oracion_que_no_llego_a_candidata(self):
        """`operones_del_corpus()` mide sobre `menciones`, no sobre candidatas.
        Un operon nombrado en una oracion descartada por corta o por seccion
        sigue siendo un operon que el corpus nombra, y sigue contando como
        hueco del catalogo si no esta. `n_candidatas` es la columna que
        distingue los dos casos."""
        unidad = bdb.guardar_unidad(self.con, self.corrida, {
            "pmid": "1", "fuente_texto": "xml", "seccion": "excluir",
            "num_oracion": 9, "texto": "mexXY.", "offset_ini": 0,
            "offset_fin": 6, "contiguo": True})
        bdb.guardar_menciones(self.con, self.corrida, "m", unidad, [
            {"tipo": "operon", "texto": "mexXY", "id_normalizado": "mexXY",
             "offset_ini": 0, "offset_fin": 5}])
        self.con.commit()

        por_nombre = dict((f["operon"], f) for f in exportar.filas_operones(
            self.con, bdb, self.corrida, self.cat))

        self.assertEqual(por_nombre["mexXY"]["n_menciones"], 1)
        self.assertEqual(por_nombre["mexXY"]["n_oraciones"], 1)
        self.assertEqual(por_nombre["mexXY"]["n_candidatas"], 0)

    def test_un_operon_que_empieza_por_pa_no_cuenta_como_locus_tag(self):
        """`parRS` empieza por `pa`, y en SQLite `LIKE 'PA%'` no distingue
        mayusculas: contaba el nombre del operon como si fuera un locus tag e
        inflaba la tasa de normalizacion. En el corpus son 78 menciones. Se
        arregla con `GLOB 'PA*'`, y esta prueba es la que lo sostiene."""
        unidad = bdb.guardar_unidad(self.con, self.corrida, {
            "pmid": "1", "fuente_texto": "abstract", "seccion": "abstract",
            "num_oracion": 7, "texto": "The parRS system responds to peptides.",
            "offset_ini": 0, "offset_fin": 38, "contiguo": True})
        bdb.guardar_menciones(self.con, self.corrida, "m", unidad, [
            {"tipo": "operon", "texto": "parRS", "id_normalizado": "parRS",
             "offset_ini": 4, "offset_fin": 9}])
        self.con.commit()

        c = bdb.conteos_de(self.con, self.corrida)

        # 4 menciones de gen/proteina/operon, y solo `MexT` -> PA2492 esta
        # normalizada a locus tag.
        self.assertEqual(c["genes_totales"], 4)
        self.assertEqual(c["genes_normalizados"], 1)

    def test_los_conteos_de_gen_siguen_incluyendo_al_operon(self):
        """Si el operon saliera de estos conteos, la tasa de normalizacion a
        locus tag bajaria sin que nada hubiera empeorado, y la cifra publicada
        dejaria de ser comparable con la de la corrida 1."""
        c = bdb.conteos_de(self.con, self.corrida)

        self.assertEqual(c["genes_totales"], 3)
        self.assertEqual(c["por_tipo"]["operon"], 2)
        self.assertEqual(c["operones_distintos"], 2)
        self.assertEqual(c["candidatas_con_operon"], 1)


class PruebasColumnas(unittest.TestCase):

    def test_las_dos_columnas_nuevas_estan_en_el_contrato(self):
        for col in ("operones", "genes_expandidos"):
            self.assertIn(col, exportar.COLUMNAS_CANDIDATAS)

    def test_las_columnas_viejas_no_se_movieron_de_sitio(self):
        """Las dos nuevas van DESPUES de `proteinas`. Otro sitio correria las
        columnas que ya existian y algun lector que indexe por posicion leeria
        una cosa por otra."""
        c = exportar.COLUMNAS_CANDIDATAS

        self.assertEqual(c[:13], [
            "pmid", "doi", "titulo", "anio", "revista", "fecha_ingesta",
            "fuente_texto", "seccion", "num_oracion", "oracion",
            "genes", "genes_locus_tag", "proteinas"])
        self.assertEqual(c[13:15], ["operones", "genes_expandidos"])


if __name__ == "__main__":
    unittest.main()
