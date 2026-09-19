# -*- coding: utf-8 -*-
"""La base de operones: idempotencia, curacion y el contrato de errores.

Ninguna prueba toca la red. `red.Sesion` no se instancia con una URL de
verdad en ningun punto: lo que se prueba de ella es el contrato --`None` es
"contesto que no", excepcion es "no pude preguntar"-- con un opener falso.

Fixtures locales y minimos: ningun recurso real, ninguna base real.

    python -m unittest discover .
"""

import io
import os
import sys
import tempfile
import unittest
import urllib.error

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_operones import curar as C                  # noqa: E402
from grn_operones import db as D                     # noqa: E402
from grn_operones import exportar as E               # noqa: E402
from grn_operones import fuentes as F                # noqa: E402
from grn_operones import red as R                    # noqa: E402

# Dos TUs de BioCyc: una de tres genes con evidencia experimental y otra de
# dos. `PA9999` no esta en el mapa de genes, para probar el sin_mapear.
XML_GENES = u"""<?xml version="1.0"?>
<ptools-xml>
  <Gene frameid="G-1"><accession-1>PA0425</accession-1></Gene>
  <Gene frameid="G-2"><accession-1>PA0426</accession-1></Gene>
  <Gene frameid="G-3"><accession-1>PA0427</accession-1></Gene>
  <Gene frameid="G-4"><accession-1>PA2493</accession-1></Gene>
  <Gene frameid="G-5"><accession-1>PA2494</accession-1></Gene>
</ptools-xml>"""

XML_TUS = u"""<?xml version="1.0"?>
<ptools-xml>
  <Transcription-Unit frameid="TU-1">
    <Evidence-Code frameid="EV-EXP-IDA"/>
    <component><Gene frameid="G-1"/></component>
    <component><Gene frameid="G-2"/></component>
    <component><Gene frameid="G-3"/></component>
  </Transcription-Unit>
  <Transcription-Unit frameid="TU-2">
    <component><Gene frameid="G-4"/></component>
    <component><Gene frameid="G-5"/></component>
    <component><Gene frameid="G-99"/></component>
  </Transcription-Unit>
</ptools-xml>"""

GENES_TSV = u"""locus_tag\tsimbolo\talias\ttipo\tproducto\tes_tf\tfuente_tf\tfuente\tsensible_mayusculas
PA0425\tmexA\t\tcds\tefflux\tfalse\t\trefseq\tfalse
PA0426\tmexB\t\tcds\tefflux\tfalse\t\trefseq\tfalse
PA0427\toprM\toprK\tcds\tporin\tfalse\t\trefseq\tfalse
PA2493\tmexE\t\tcds\tefflux\tfalse\t\trefseq\tfalse
PA2494\tmexF\t\tcds\tefflux\tfalse\t\trefseq\tfalse
PA2495\toprN\t\tcds\tporin\tfalse\t\trefseq\tfalse
"""


def _con():
    return D.conectar(":memory:")


def _fila(fuente, idf, locus, descarga_id=None, **kw):
    """Una fila de bronce. `descarga_id` es obligatorio en el esquema:
    una fila cruda sin la descarga de la que salio no tiene procedencia."""
    f = {"fuente": fuente, "id_fuente": idf, "locus_tags": locus}
    if descarga_id is not None:
        f["descarga_id"] = descarga_id
    f.update(kw)
    return f


def _descarga(con, fuente="odb", cuerpo=b"X", extraccion_id=None,
              completa=True):
    """Abre una extraccion si no se pasa una, registra el archivo y cierra.

    Cierra completa por omision: `bronze_vigente()` solo mira las completas,
    asi que una prueba que no la cerrara no veria su bronce. Con
    `completa=False` se simula una corrida interrumpida.
    """
    propia = extraccion_id is None
    if propia:
        extraccion_id = D.abrir_extraccion(con, fuente)
    did = D.registrar_descarga(con, extraccion_id, "u", "r", cuerpo)
    if propia:
        D.cerrar_extraccion(con, extraccion_id, completa=completa)
    return did


def _bronce(con, filas, completa=True):
    """Guarda filas de bronce abriendo, por cada fuente, SU extraccion.

    La fuente ya no es una columna del bronce: se deriva de la extraccion de
    su descarga, y por eso no puede discrepar de ella. El helper monta esa
    cadena para que las pruebas hablen de curacion y no de plomeria.
    """
    por_fuente = {}
    for f in filas:
        fu = f["fuente"]
        if fu not in por_fuente:
            eid = D.abrir_extraccion(con, fu)
            por_fuente[fu] = (eid, D.registrar_descarga(
                con, eid, "u", "r", ("cuerpo-%s-%d" % (fu, eid)).encode()))
        f["descarga_id"] = por_fuente[fu][1]
    salida = D.guardar_bronze(con, filas)
    for eid, _did in por_fuente.values():
        D.cerrar_extraccion(con, eid, completa=completa)
    return salida


class PruebasContratoDeRed(unittest.TestCase):
    """`None` = contesto que no. Excepcion = no pude preguntar.

    Es el mismo contrato que `grn_etl/pubmed.py`, y no por simetria: quien
    llama traduce `None` a "esta fuente no tiene esto" y lo da por definitivo.
    Si un corte de red se colara como `None`, una fuente entera quedaria
    marcada como vacia cuando lo que paso es que no se pudo preguntar.
    """

    def _sesion(self, efecto):
        s = R.Sesion("alguien@unam.mx", pausa=0)

        def falso(url, datos=None, timeout=None):
            return efecto()
        s._abrir = falso
        return s

    def test_un_403_es_que_no_y_no_se_reintenta(self):
        intentos = []

        def efecto():
            intentos.append(1)
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

        salida = self._sesion(efecto).pedir("https://x/y")

        self.assertIsNone(salida)
        self.assertEqual(len(intentos), 1, "un definitivo no se reintenta")

    def test_un_500_agota_intentos_y_lanza(self):
        def efecto():
            raise urllib.error.HTTPError("u", 500, "boom", {}, None)

        with self.assertRaises(R.ErrorFuente):
            self._sesion(efecto).pedir("https://x/y", intentos=2)

    def test_el_transporte_caido_lanza_no_devuelve_vacio(self):
        def efecto():
            raise OSError("sin ruta al host")

        with self.assertRaises(R.ErrorFuente):
            self._sesion(efecto).pedir("https://x/y", intentos=2)

    def test_el_mensaje_de_error_no_lleva_la_cadena_de_consulta(self):
        """Los errores acaban en logs y en la bitacora, y una URL con
        parametros puede llevar un token de sesion."""
        def efecto():
            raise OSError("boom")

        try:
            self._sesion(efecto).pedir("https://x/y", params={"token": "SECRETO"},
                                       intentos=1)
        except R.ErrorFuente as e:
            self.assertNotIn("SECRETO", str(e))
        else:
            self.fail("deberia haber lanzado")

    def test_sin_correo_no_hay_sesion(self):
        """El User-Agent tiene que identificar a alguien: es lo que permite a
        un administrador escribir en vez de bloquear."""
        with self.assertRaises(ValueError):
            R.Sesion("")


class PruebasInspeccionar(unittest.TestCase):
    """La tarea 1 del encargo: decir que devolvio cada fuente."""

    def test_reconoce_json_xml_y_html(self):
        self.assertEqual(F.inspeccionar(b'{"a": 1}')["tipo"], "json")
        self.assertEqual(F.inspeccionar(b'<?xml version="1.0"?><a/>')["tipo"],
                         "xml")
        self.assertEqual(F.inspeccionar(b"<html><body>x</body></html>")["tipo"],
                         "html")

    def test_delata_el_esqueleto_de_una_aplicacion_javascript(self):
        """El caso REAL de ODB v4, comprobado el 18-sep-2026: 689 bytes con un
        div vacio y un script, sin NINGUNA tabla.

        La primera version de la heuristica exigia `tablas > 0` y se le
        escapaba justo esto, que es el caso que vino a detectar: suponia que
        el sitio al menos intenta renderizar algo en el servidor.
        """
        shell = (b"<!DOCTYPE html><html><head><title>Operon database v4"
                 b"</title></head><body><div id=\"app\"></div>"
                 b"<script src=\"/assets/js/index.js\"></script></body></html>")

        d = F.inspeccionar(shell)

        self.assertTrue(d["parece_render_js"])
        self.assertTrue(d["sin_datos"])
        self.assertEqual(d["tablas"], 0)

    def test_una_tabla_con_encabezado_y_sin_filas_es_sin_datos(self):
        """No es necesariamente render por JavaScript --puede ser una busqueda
        sin resultados-- pero tampoco trae nada que parsear."""
        html = b"<html><table><tr><th>Operon</th></tr></table></html>"

        d = F.inspeccionar(html)

        self.assertTrue(d["sin_datos"])
        self.assertEqual(d["locus_tags_visibles"], 0)

    def test_una_tabla_con_datos_no_se_confunde_con_un_esqueleto(self):
        html = (b"<html><table><tr><th>Operon</th></tr>"
                b"<tr><td>PA0425</td></tr><tr><td>PA0426</td></tr>"
                b"</table></html>")

        d = F.inspeccionar(html)

        self.assertFalse(d["parece_render_js"])
        self.assertEqual(d["locus_tags_visibles"], 2)

    def test_cuenta_locus_tags_en_texto_tabular(self):
        d = F.inspeccionar(b"operon\tgenes\nop1\tPA0425|PA0426\n")

        self.assertEqual(d["tipo"], "texto")
        self.assertEqual(d["separador"], "tabulador")
        self.assertEqual(d["locus_tags_visibles"], 2)


class PruebasParserBioCyc(unittest.TestCase):

    def test_mapea_frameid_a_locus_tag(self):
        filas = F.parsear_biocyc(XML_TUS.encode("utf-8"),
                                 XML_GENES.encode("utf-8"))
        por_id = dict((f["id_fuente"], f) for f in filas)

        self.assertEqual(por_id["TU-1"]["locus_tags"], "PA0425|PA0426|PA0427")
        self.assertEqual(por_id["TU-1"]["tipo_evidencia"], "EV-EXP-IDA")

    def test_un_gen_sin_locus_tag_se_anota_en_vez_de_perderse(self):
        """`G-99` no esta en el XML de genes. La TU se conserva con los dos
        que si mapearon, y el que falto queda escrito: es lo que permite
        saber despues si el hueco importa."""
        filas = F.parsear_biocyc(XML_TUS.encode("utf-8"),
                                 XML_GENES.encode("utf-8"))
        tu2 = [f for f in filas if f["id_fuente"] == "TU-2"][0]

        self.assertEqual(tu2["locus_tags"], "PA2493|PA2494")
        self.assertEqual(tu2["registro_raw"]["sin_mapear"], ["G-99"])
        self.assertIsNone(tu2["genes_raw"],
                          "los frameid no son nombres de gen")

    def test_los_parsers_que_faltan_fallan_diciendo_que_llego(self):
        """Un parser a ciegas devolveria cero filas y pareceria correcto.

        PGD y CDBProm siguen sin formato conocido; ODB ya no, porque su
        volcado real se vio el 18-sep-2026."""
        with self.assertRaises(F.FormatoDesconocido) as ctx:
            F.parsear_tabular(b"no hay locus tags aqui", "pgd")

        self.assertIn("pgd", str(ctx.exception).lower())


class PruebasIdempotencia(unittest.TestCase):
    """El encargo la exige: re-correr no debe duplicar registros."""

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)

    def _corrida(self, fuente, cuerpo, completa=True):
        """(extraccion_id, descarga_id) de una corrida ya cerrada."""
        eid = D.abrir_extraccion(self.con, fuente)
        did = D.registrar_descarga(self.con, eid, "u", "r", cuerpo)
        D.cerrar_extraccion(self.con, eid, completa=completa)
        return eid, did

    def test_el_mismo_archivo_no_se_registra_dos_veces_en_una_corrida(self):
        eid = D.abrir_extraccion(self.con, "odb")
        a = D.registrar_descarga(self.con, eid, "u", "r", b"XYZ")
        b = D.registrar_descarga(self.con, eid, "u", "r", b"XYZ")

        self.assertEqual(a, b)
        self.assertEqual(len(D.descargas_de(self.con, "odb")), 1)

    def test_dos_urls_con_el_mismo_contenido_se_registran_las_dos(self):
        """Identificar por contenido se tragaba URLs. En ODB pasa: una pagina
        fuera de rango devuelve la plantilla vacia, o el servidor repite la
        ultima valida, y no quedaba rastro de que se habia pedido."""
        eid = D.abrir_extraccion(self.con, "odb")
        D.registrar_descarga(self.con, eid, "p=1", "r1", b"IGUAL")
        D.registrar_descarga(self.con, eid, "p=2", "r2", b"IGUAL")

        descargas = D.descargas_de(self.con, "odb")

        self.assertEqual(len(descargas), 2)
        self.assertEqual(sorted(d["url"] for d in descargas), ["p=1", "p=2"])

    def test_los_contenidos_repetidos_se_pueden_consultar(self):
        """Visibles en vez de absorbidos: es lo que permite reconocer la
        plantilla vacia del final de la paginacion."""
        eid = D.abrir_extraccion(self.con, "odb")
        D.registrar_descarga(self.con, eid, "p=1", "r1", b"DATOS")
        D.registrar_descarga(self.con, eid, "p=2", "r2", b"VACIA")
        D.registrar_descarga(self.con, eid, "p=3", "r3", b"VACIA")

        repetidos = D.contenidos_repetidos(self.con, eid)

        self.assertEqual(len(repetidos), 1)
        _sha, urls = repetidos[0]
        self.assertEqual(sorted(urls), ["p=2", "p=3"])

    def test_el_mismo_archivo_en_otra_corrida_se_registra_aparte(self):
        """Cada extraccion es una foto, y lo que importa de un archivo es en
        que foto salio."""
        self._corrida("odb", b"IGUAL")
        self._corrida("odb", b"IGUAL")

        self.assertEqual(len(D.descargas_de(self.con, "odb")), 2)

    def test_la_misma_descarga_no_inserta_bronce_dos_veces(self):
        _eid, did = self._corrida("biocyc", b"A")
        D.guardar_bronze(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426", descarga_id=did)])
        n, ya = D.guardar_bronze(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426", descarga_id=did)])

        self.assertEqual(len(D.bronze_de(self.con, "biocyc")), 1)
        self.assertEqual((n, ya), (0, 1))

    def test_el_bronce_conserva_lo_que_dijo_la_fuente_en_cada_corrida(self):
        """Si la fuente corrige un operon, la version vieja NO se pisa.

        Con DO UPDATE se perdia que la fuente cambio de opinion y cuando, que
        es de lo poco que una capa cruda aporta y nadie mas guarda.
        """
        _e1, d1 = self._corrida("biocyc", b"PRIMERA")
        _e2, d2 = self._corrida("biocyc", b"SEGUNDA")
        D.guardar_bronze(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426", descarga_id=d1)])
        D.guardar_bronze(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426|PA0427", descarga_id=d2)])

        versiones = D.versiones_de(self.con, "biocyc", "TU-1")

        self.assertEqual(len(versiones), 2)
        self.assertEqual(versiones[0]["locus_tags"], "PA0425|PA0426|PA0427")
        self.assertEqual(versiones[1]["locus_tags"], "PA0425|PA0426")

    def test_vigente_es_la_ultima_corrida_completa(self):
        _e1, d1 = self._corrida("biocyc", b"PRIMERA")
        _e2, d2 = self._corrida("biocyc", b"SEGUNDA")
        D.guardar_bronze(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426", descarga_id=d1)])
        D.guardar_bronze(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426|PA0427", descarga_id=d2)])

        vigente = D.bronze_vigente(self.con)

        self.assertEqual(len(vigente), 1)
        self.assertEqual(vigente[0]["locus_tags"], "PA0425|PA0426|PA0427")
        self.assertEqual(vigente[0]["fuente"], "biocyc")

    def test_una_corrida_incompleta_no_desplaza_a_la_completa_anterior(self):
        """Media foto nueva no invalida la ultima foto buena: si la
        paginacion se corta, se sigue curando la anterior."""
        _e1, d1 = self._corrida("odb", b"BUENA")
        _e2, d2 = self._corrida("odb", b"CORTADA", completa=False)
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=d1)])
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA9999", descarga_id=d2)])

        vigente = D.bronze_vigente(self.con)

        self.assertEqual(len(vigente), 1)
        self.assertEqual(vigente[0]["locus_tags"], "PA0425|PA0426")

    def test_una_fuente_sin_ninguna_corrida_completa_queda_fuera(self):
        """Con media foto no se puede decir que se retiro ni que sigue, asi
        que la fuente entera sale de la curacion. Y hay que nombrarla: que
        desaparezca por una descarga cortada es indistinguible de que no
        trajera nada, y son dos problemas distintos.
        """
        _eid, did = self._corrida("odb", b"CORTADA", completa=False)
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=did)])

        self.assertEqual(D.bronze_vigente(self.con), [])
        self.assertEqual(D.fuentes_sin_foto(self.con), ["odb"])
        self.assertEqual(D.retirados(self.con), {},
                         "no se retiro nada: no hay con que comparar")
        self.assertEqual(len(D.bronze_de(self.con, "odb")), 1,
                         "el crudo si se conserva; lo que no se cura")

    def test_la_edad_de_la_foto_cuenta_las_corridas_fallidas_despues(self):
        """El modo de fallo lento: si las extracciones fallan varias veces
        seguidas se cura una foto vieja indefinidamente y sin ruido, porque
        todo sigue funcionando. El contador es lo que lo delata."""
        _e1, d1 = self._corrida("odb", b"BUENA")
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=d1)])
        self._corrida("odb", b"FALLO1", completa=False)
        self._corrida("odb", b"FALLO2", completa=False)

        edad = D.edad_de_la_foto(self.con)

        self.assertEqual(edad["odb"]["extraccion_id"], _e1)
        self.assertEqual(edad["odb"]["incompletas_despues"], 2)
        self.assertTrue(edad["odb"]["fecha"])

    def test_sin_corridas_fallidas_el_contador_es_cero(self):
        _e1, d1 = self._corrida("odb", b"BUENA")
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=d1)])

        self.assertEqual(
            D.edad_de_la_foto(self.con)["odb"]["incompletas_despues"], 0)

    def test_una_fuente_con_foto_no_aparece_como_sin_foto(self):
        _eid, did = self._corrida("odb", b"BUENA")
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=did)])

        self.assertEqual(D.fuentes_sin_foto(self.con), [])

    def test_un_operon_que_la_fuente_retira_deja_de_estar_vigente(self):
        """Con el criterio viejo --la fila mas reciente de cada clave-- un
        operon eliminado seguia vigente para siempre."""
        _e1, d1 = self._corrida("odb", b"PRIMERA")
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=d1),
            _fila("odb", "b", "PA2493|PA2494", descarga_id=d1)])
        _e2, d2 = self._corrida("odb", b"SEGUNDA")
        D.guardar_bronze(self.con, [
            _fila("odb", "a", "PA0425|PA0426", descarga_id=d2)])

        vigentes = set(f["id_fuente"] for f in D.bronze_vigente(self.con))

        self.assertEqual(vigentes, {"a"})
        self.assertEqual(D.retirados(self.con), {"odb": ["b"]})

    def test_una_fila_sin_descarga_no_entra(self):
        """Sin la descarga de la que salio no tiene procedencia, y ademas el
        NULL rompe la unicidad: en SQLite los NULL son distintos entre si."""
        with self.assertRaises(ValueError):
            D.guardar_bronze(self.con, [
                {"id_fuente": "x", "locus_tags": "PA0425"}])

    def test_una_fila_que_dice_ser_de_otra_fuente_se_rechaza(self):
        """La fuente ya no se guarda en el bronce --se deriva de la
        extraccion-- asi que no puede discrepar. Lo que si se comprueba es que
        quien llama no se haya equivocado de descarga."""
        _eid, did = self._corrida("odb", b"AJENA")

        with self.assertRaises(ValueError):
            D.guardar_bronze(self.con, [
                _fila("biocyc", "TU-1", "PA0425", descarga_id=did)])

    def test_dos_fuentes_pueden_usar_el_mismo_id(self):
        """Que ODB y BioCyc llamen `op1` a cosas distintas no puede hacer que
        una pise a la otra: cada una cuelga de su propia descarga."""
        _bronce(self.con, [_fila("odb", "op1", "PA0425|PA0426"),
                           _fila("biocyc", "op1", "PA2493|PA2494")])

        self.assertEqual(len(D.bronze_de(self.con)), 2)
        self.assertEqual(
            sorted(f["fuente"] for f in D.bronze_vigente(self.con)),
            ["biocyc", "odb"])


class PruebasCuracion(unittest.TestCase):

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ruta = os.path.join(self.tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        self.dicc = C.cargar_diccionario(ruta)
        self.hebras = {"PA0425": "+", "PA0426": "+", "PA0427": "+",
                       "PA2493": "+", "PA2494": "+", "PA2495": "-"}

    def _curar(self, hebras=None):
        return C.curar(self.con, diccionario=self.dicc,
                       hebras=self.hebras if hebras is None else hebras)

    def test_normaliza_simbolos_y_alias_a_locus_tag(self):
        locus, fuera, _amb = C.normalizar(["mexA", "mexB", "oprK"], self.dicc)

        self.assertEqual(locus, ["PA0425", "PA0426", "PA0427"])
        self.assertEqual(fuera, [])

    def test_conserva_el_orden_de_transcripcion(self):
        """El orden distingue `mexCD-oprJ` de `oprJ-mexDC`, que es el mismo
        operon leido al reves y un nombre que no existe."""
        locus, _f, _a = C.normalizar(["oprM", "mexB", "mexA"], self.dicc)

        self.assertEqual(locus, ["PA0427", "PA0426", "PA0425"])

    def test_un_nombre_que_no_esta_se_reporta_no_se_inventa(self):
        locus, fuera, _amb = C.normalizar(["mexA", "noexiste"], self.dicc)

        self.assertEqual(locus, ["PA0425"])
        self.assertEqual(fuera, ["noexiste"])

    def test_la_adyacencia_vale_en_los_dos_sentidos(self):
        self.assertTrue(C.es_adyacente(["PA0425", "PA0426", "PA0427"]))
        self.assertTrue(C.es_adyacente(["PA0427", "PA0426", "PA0425"]))
        self.assertFalse(C.es_adyacente(["PA0425", "PA0430"]))

    def test_dos_fuentes_con_los_mismos_genes_dan_un_solo_operon(self):
        _bronce(self.con, [
            _fila("odb", "op1", "PA0425|PA0426|PA0427", pmid="123"),
            _fila("biocyc", "TU-1", "PA0425|PA0426|PA0427")])

        self._curar()
        filas = D.silver_de(self.con)

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["n_fuentes"], 2)

    def test_un_subconjunto_se_marca_alternativo_y_no_se_fusiona(self):
        """Un operon puede transcribirse entero o en parte, y las dos cosas
        estan documentadas. Fusionarlas perderia una."""
        _bronce(self.con, [
            _fila("odb", "largo", "PA0425|PA0426|PA0427"),
            _fila("odb", "corto", "PA0425|PA0426")])

        self._curar()
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(self.con))

        self.assertEqual(len(por_clave), 2)
        self.assertTrue(por_clave["PA0425|PA0426"]["es_alternativa"])
        self.assertFalse(por_clave["PA0425|PA0426|PA0427"]["es_alternativa"])

    def test_el_nivel_de_evidencia_ordena_conocido_curado_predicho(self):
        _bronce(self.con, [
            _fila("odb", "a", "PA0425|PA0426", pmid="123"),
            _fila("biocyc", "b", "PA2493|PA2494",
                  tipo_evidencia="EV-EXP-IDA"),
            _fila("pgd", "c", "PA0426|PA0427")])

        self._curar()
        niveles = dict((f["clave_genes"], f["nivel_evidencia"])
                       for f in D.silver_de(self.con))

        self.assertEqual(niveles["PA0425|PA0426"], "conocido")
        self.assertEqual(niveles["PA2493|PA2494"], "curado")
        self.assertEqual(niveles["PA0426|PA0427"], "predicho")

    def test_biocyc_y_pgd_juntas_cuentan_como_una_fuente(self):
        """Comparten el motor de prediccion de Pathway Tools: coincidir no es
        confirmacion independiente."""
        _bronce(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426"),
            _fila("pgd", "op1", "PA0425|PA0426")])

        self._curar()

        self.assertEqual(D.silver_de(self.con)[0]["n_fuentes"], 1)

    def test_un_operon_no_adyacente_queda_marcado_para_revisar(self):
        _bronce(self.con, [_fila("odb", "raro", "PA0425|PA2494")])

        self._curar()
        fila = D.silver_de(self.con)[0]

        self.assertFalse(fila["adyacente"])
        self.assertIn("no_adyacente", fila["revisar"])

    def test_hebras_distintas_se_marcan(self):
        _bronce(self.con, [_fila("odb", "x", "PA2494|PA2495")])

        self._curar()

        self.assertIn("hebras_distintas", D.silver_de(self.con)[0]["revisar"])

    def test_sin_gff_la_hebra_no_se_da_por_buena(self):
        """Callar es peor que decir que no se comprobo: una fila sin marca se
        lee como validada."""
        _bronce(self.con, [_fila("odb", "x", "PA0425|PA0426")])

        C.curar(self.con, diccionario=self.dicc, hebras={})

        self.assertIn("hebra_no_verificada",
                      D.silver_de(self.con)[0]["revisar"])

    def test_curar_dos_veces_no_duplica(self):
        _bronce(self.con, [_fila("odb", "a", "PA0425|PA0426")])

        self._curar()
        self._curar()

        self.assertEqual(len(D.silver_de(self.con)), 1)
        self.assertEqual(len(D.fuentes_de_silver(self.con)), 1)


class PruebasMonocistronicos(unittest.TestCase):
    """Una unidad de transcripcion de un solo gen se conserva, marcada.

    BioCyc registra 3 774 TUs para unos 5 600 genes, asi que muchas son
    monocistronicas: descartarlas tiraba la mayor parte de esa fuente. Filtrar
    es decision de quien lee el archivo, no de quien lo construye, y por eso
    vive en la exportacion.
    """

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ruta = os.path.join(self.tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        self.dicc = C.cargar_diccionario(ruta)
        self.hebras = {"PA0425": "+", "PA0426": "+", "PA0427": "+",
                       "PA2493": "+"}
        _bronce(self.con, [
            _fila("biocyc", "TU-solo", "PA2493"),
            _fila("biocyc", "TU-tres", "PA0425|PA0426|PA0427")])
        C.curar(self.con, diccionario=self.dicc, hebras=self.hebras)

    def test_una_unidad_de_un_gen_llega_a_silver_marcada(self):
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(self.con))

        self.assertIn("PA2493", por_clave)
        self.assertTrue(por_clave["PA2493"]["monocistronico"])
        self.assertEqual(por_clave["PA2493"]["n_genes"], 1)

    def test_un_operon_de_varios_genes_no_se_marca(self):
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(self.con))

        self.assertFalse(por_clave["PA0425|PA0426|PA0427"]["monocistronico"])

    def test_un_monocistronico_no_se_marca_como_no_adyacente(self):
        """Con un solo gen la adyacencia es vacuamente cierta: no hay pares que
        comparar. Marcarlos inundaria el archivo de conflictos con lo que no es
        un conflicto."""
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(self.con))

        self.assertTrue(por_clave["PA2493"]["adyacente"])
        self.assertNotIn("no_adyacente", por_clave["PA2493"]["revisar"] or "")

    def test_el_resumen_los_cuenta(self):
        self.assertEqual(D.resumen_silver(self.con)["monocistronicos"], 1)

    def test_exportar_los_incluye_por_omision(self):
        filas = E.filas_silver(self.con, D)

        self.assertEqual(len(filas), 2)
        self.assertIn("si", [f["monocistronico"] for f in filas])

    def test_exportar_los_deja_fuera_con_la_opcion(self):
        filas = E.filas_silver(self.con, D, sin_monocistronicos=True)

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["clave_genes"], "PA0425|PA0426|PA0427")

    def test_una_fila_sin_ningun_gen_resuelto_si_se_descarta(self):
        """Distinto de una unidad de un gen: aqui no hay nada que curar."""
        _bronce(self.con, [_fila("odb", "vacio", "NOEXISTE")])

        resumen = C.curar(self.con, diccionario=self.dicc, hebras=self.hebras)

        self.assertEqual(resumen["sin_ningun_gen"], 1)


class PruebasExportacion(unittest.TestCase):

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ruta = os.path.join(self.tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        _bronce(self.con, [
            _fila("odb", "bueno", "PA0425|PA0426", pmid="123"),
            _fila("odb", "raro", "PA0425|PA2494")])
        C.curar(self.con, diccionario=C.cargar_diccionario(ruta),
                hebras={"PA0425": "+", "PA0426": "+", "PA2494": "+"})

    def test_los_conflictos_traen_solo_lo_que_hay_que_mirar(self):
        conflictos = E.filas_conflictos(self.con, D)

        self.assertEqual(len(conflictos), 1)
        self.assertEqual(conflictos[0]["clave_genes"], "PA0425|PA2494")
        self.assertIn("consecutivos", conflictos[0]["motivo"])

    def test_el_csv_lleva_las_fuentes_que_respaldan_cada_operon(self):
        filas = E.filas_silver(self.con, D)

        self.assertTrue(all(f["fuentes"] == "odb" for f in filas))

    def test_el_csv_se_escribe_entero_o_no_se_escribe(self):
        ruta = os.path.join(self.tmp.name, "sub", "silver.csv")

        E.escribir_csv(ruta, E.COLUMNAS_SILVER,
                       E.filas_silver(self.con, D))

        self.assertTrue(os.path.exists(ruta))
        self.assertFalse(os.path.exists(ruta + ".tmp"))


class PruebasCoberturaDeMapeo(unittest.TestCase):
    """Cuanto del vocabulario real de ODB sabe resolver el diccionario.

    Esta clase mide, no exige. Falla solo si la cobertura cae por debajo de un
    piso muy bajo, porque **el numero util no es el veredicto sino la cifra**:
    la normalizacion falla en silencio --un nombre desconocido da un operon con
    un gen menos, indistinguible de uno que de verdad lo tiene-- y lo unico que
    delata eso es medirlo.

    Sobre el diccionario real: de sus 5 642 filas, solo 224 traen un sinonimo
    distinto del simbolo y del locus tag. Los nombres historicos que usa la
    literatura de operones no estan cubiertos, y `nalB` --el nombre con el que
    los articulos de los noventa llaman a `mexR`-- es el caso de manual.
    """

    @classmethod
    def setUpClass(cls):
        cls.dicc = C.cargar_diccionario()

    # Simbolos vigentes que cualquier fuente de operones de PAO1 va a nombrar.
    VIGENTES = ["mexA", "mexB", "oprM", "mexE", "mexF", "oprN", "lasR", "lasI",
                "rhlR", "rhlI", "pqsA", "algD", "mexR", "nfxB", "ampC",
                "pilA", "fliC", "rpoS", "rpoN", "vfr", "anr", "fur", "toxA",
                "exoS", "pchA", "pvdA", "katA", "sodB", "oprF", "oprD",
                "gacA", "gacS", "rsmA", "crc", "cbrA", "nirS", "norB", "nosZ"]

    # Nombres historicos y formas que la literatura usa y el catalogo no.
    # No son un fallo del diccionario: son la medida de su alcance.
    HISTORICOS = ["nalB", "phzA"]

    def test_los_simbolos_vigentes_se_resuelven_casi_todos(self):
        c = C.cobertura_mapeo(self.VIGENTES, self.dicc)

        self.assertGreaterEqual(
            c["tasa"], 0.95,
            "la cobertura de simbolos vigentes cayo a %.1f %%; sin mapeo, "
            "esos genes desaparecen de sus operones en silencio. Sin "
            "resolver: %s" % (100.0 * c["tasa"], c["huerfanos"]))

    def test_los_dos_modos_de_fallo_se_reportan_por_separado(self):
        """`nalB` falta del diccionario; `phzA` sobra de candidatos. Son dos
        problemas con dos arreglos distintos --anadir una entrada contra
        desambiguar a mano-- y una sola cifra no diria cual toca."""
        c = C.cobertura_mapeo(self.HISTORICOS, self.dicc)

        self.assertEqual(c["huerfanos"], ["nalB"])
        self.assertEqual(c["ambiguos"], ["phzA"])
        self.assertEqual(c["mapeados"], 0)

    def test_el_conteo_de_sinonimos_se_reporta_no_se_acota(self):
        """No hay umbral, a proposito.

        Una prueba que fallara al crecer el diccionario castigaria la mejora y
        rompería CI por una buena noticia. El tamano del catalogo es un hecho
        de la corrida y va al informe de `curar`; lo que las pruebas fijan es
        comportamiento. Aqui solo se comprueba que el contador existe y cuenta.
        """
        filas, con_sinonimo = C.contar_sinonimos()

        self.assertGreater(filas, 5000)
        self.assertGreaterEqual(con_sinonimo, 0)
        self.assertLessEqual(con_sinonimo, filas)

    def test_un_paralogo_no_se_resuelve_a_uno_de_sus_candidatos(self):
        """`phzA` puede ser `phzA1` (PA4210) o `phzA2` (PA1899). Elegir uno
        meteria un gen equivocado en un operon sin dejar rastro de que hubo
        una eleccion."""
        locus, fuera, ambiguos = C.normalizar(["phzA"], self.dicc)

        self.assertEqual(locus, [])
        self.assertEqual(fuera, [])
        self.assertEqual(len(ambiguos), 1)
        nombre, candidatos = ambiguos[0]
        self.assertEqual(nombre, "phzA")
        self.assertIn("PA4210", candidatos)
        self.assertIn("PA1899", candidatos)

    def test_un_nombre_sin_parientes_es_huerfano_no_ambiguo(self):
        """`nalB` no tiene familia numerada: no es ambiguo, es desconocido.
        Son dos problemas distintos y se reportan por separado."""
        locus, fuera, ambiguos = C.normalizar(["nalB"], self.dicc)

        self.assertEqual(fuera, ["nalB"])
        self.assertEqual(ambiguos, [])

    def test_la_cobertura_se_mide_sobre_los_nombres_crudos_de_la_fuente(self):
        """Si se midiera sobre `locus_tags` --que ya vienen resueltos cuando
        la fuente los da-- la tasa saldria siempre alta y no diria nada."""
        con = _con()
        self.addCleanup(con.close)
        did = _descarga(con, "odb", b"X")
        D.guardar_bronze(con, [_fila("odb", "op1", "PA0425|PA0426",
                                     descarga_id=did,
                                     genes_raw="mexA|nalB")])

        c = C.cobertura_de_fuente(con, "odb", self.dicc)

        self.assertEqual(c["nombres"], 2)
        self.assertEqual(c["huerfanos"], ["nalB"])


class PruebasCredenciales(unittest.TestCase):

    def test_sin_variables_de_entorno_falla_con_un_mensaje_util(self):
        previo = dict((k, os.environ.pop(k, None))
                      for k in ("BIOCYC_EMAIL", "BIOCYC_PASSWORD"))
        self.addCleanup(lambda: os.environ.update(
            (k, v) for k, v in previo.items() if v is not None))

        with self.assertRaises(F.ErrorCredenciales) as ctx:
            F.credenciales_biocyc()

        self.assertIn("BIOCYC_EMAIL", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
