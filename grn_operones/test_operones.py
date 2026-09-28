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
from unittest import mock

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


# Filas reales de la tabla de operones de PGD (datos públicos, BSD-3), en su
# formato: entrecomillado salvo los números. Cubren los casos que el archivo
# real trae:
# - operon-2, en la hebra menos;
# - operon-6, cuyas filas no van juntas;
# - rsmY, con locus tag `PA####.N`;
# - operon-714, el de la captura de la página;
# - carA-PA4757-carB, de PseudoCAP, que repite cada gen una vez por artículo.
PGD_CSV = u"""\
"operon-id","operon_name","locus_tag","start","end","strand","gene_name","source_database","pmid"
"operon-2","PA0006-lptA","PA0005",7018,7791,-1,"lptA","DOOR",18988623
"operon-2","PA0006-lptA","PA0006",7803,8339,-1,"","DOOR",18988623
"operon-6","hemF-aroE","PA0024",25736,26653,1,"hemF","DOOR",18988623
"operon-41798","rsmY","PA0527.1",586867,586990,1,"rsmY","PseudoCAP",19602144
"operon-6","hemF-aroE","PA0025",26711,27535,1,"aroE","DOOR",18988623
"operon-714","metG-PA3483","PA3482",3895324,3897357,1,"metG","DOOR",18988623
"operon-714","metG-PA3483","PA3483",3897391,3898191,1,"","DOOR",18988623
"operon-41779","carA-PA4757-carB operon","PA4756",5339864,5343085,-1,"carB","PseudoCAP",9286981
"operon-41779","carA-PA4757-carB operon","PA4756",5339864,5343085,-1,"carB","PseudoCAP",8169201
"operon-41779","carA-PA4757-carB operon","PA4757",5343105,5343755,-1,"","PseudoCAP",9286981
"operon-41779","carA-PA4757-carB operon","PA4757",5343105,5343755,-1,"","PseudoCAP",8169201
"operon-41779","carA-PA4757-carB operon","PA4758",5343767,5344903,-1,"carA","PseudoCAP",9286981
"operon-41779","carA-PA4757-carB operon","PA4758",5343767,5344903,-1,"carA","PseudoCAP",8169201
"""


class PruebasParserPgd(unittest.TestCase):
    """La tabla de operones de PGD: una fila por gen, un operón por id."""

    def _por_id(self, texto=None):
        filas = F.parsear_pgd((texto or PGD_CSV).encode("utf-8"))
        return dict((f["id_fuente"], f) for f in filas)

    def test_un_operon_por_id_aunque_sus_filas_no_vayan_juntas(self):
        """103 de 1 290 operones reales tienen las filas separadas."""
        por_id = self._por_id()

        self.assertEqual(sorted(por_id), ["operon-2", "operon-41779",
                                          "operon-41798", "operon-6",
                                          "operon-714"])
        self.assertEqual(por_id["operon-6"]["locus_tags"], "PA0024|PA0025")

    def test_en_la_hebra_menos_va_en_orden_de_transcripcion(self):
        """El archivo va ascendente por coordenada en las dos hebras; en la
        menos eso es al revés. El nombre lo delata: `PA0006-lptA`."""
        por_id = self._por_id()

        self.assertEqual(por_id["operon-2"]["locus_tags"], "PA0006|PA0005")
        self.assertEqual(por_id["operon-2"]["cadena"], "-")
        self.assertEqual(por_id["operon-714"]["locus_tags"], "PA3482|PA3483")
        self.assertEqual(por_id["operon-714"]["cadena"], "+")

    def test_un_gen_repetido_por_articulo_cuenta_una_vez(self):
        """Sin esto, `oprE` saldría `PA0291|PA0291`."""
        car = self._por_id()["operon-41779"]

        self.assertEqual(car["locus_tags"], "PA4758|PA4757|PA4756")
        self.assertEqual(len(car["registro_raw"]["genes"]), 3)

    def test_door_no_pone_la_cita_del_metodo_como_pmid(self):
        """18988623 es el artículo de DOOR, no una demostración del operón:
        en `pmid` la curación lo leería como literatura."""
        metg = self._por_id()["operon-714"]

        self.assertIsNone(metg["pmid"])
        self.assertEqual(metg["tipo_evidencia"], "DOOR")
        self.assertEqual(metg["registro_raw"]["referencia_metodo"], "18988623")

    def test_pseudocap_trae_sus_pmids_unidos_y_ordenados(self):
        car = self._por_id()["operon-41779"]

        self.assertEqual(car["tipo_evidencia"], "PseudoCAP")
        self.assertEqual(car["pmid"], "8169201;9286981")
        self.assertNotIn("referencia_metodo", car["registro_raw"])

    def test_un_locus_con_sufijo_punto_llega_entero(self):
        """`findall` lo habría recortado a `PA0527`, que es otro gen."""
        self.assertEqual(self._por_id()["operon-41798"]["locus_tags"],
                         "PA0527.1")

    def test_el_nombre_y_los_genes_de_la_pagina_quedan_en_el_crudo(self):
        crudo = self._por_id()["operon-714"]["registro_raw"]

        self.assertEqual(crudo["name"], "metG-PA3483")
        self.assertEqual(crudo["genes"][0], {
            "locus_tag": "PA3482", "gene_name": "metG", "start": 3895324,
            "end": 3897357, "hebra": "+"})

    def test_un_nombre_con_coma_no_corre_las_columnas(self):
        """Dos nombres reales llevan coma (`fabAB operon, long transcript`)."""
        texto = PGD_CSV.replace('"metG-PA3483"', '"metG operon, corto"')

        self.assertEqual(self._por_id(texto)["operon-714"]["registro_raw"]
                         ["name"], "metG operon, corto")

    def test_un_bom_al_frente_no_rompe_el_encabezado(self):
        """Un archivo guardado desde Excel trae BOM."""
        filas = F.parsear_pgd(b"\xef\xbb\xbf" + PGD_CSV.encode("utf-8"))

        self.assertEqual(len(filas), 5)

    def test_un_encabezado_distinto_falla(self):
        with self.assertRaises(F.FormatoDesconocido):
            F.parsear_pgd(PGD_CSV.replace('"pmid"', '"pubmed"')
                          .encode("utf-8"))

    def test_la_pagina_del_desafio_falla_diciendo_que_llego(self):
        """Lo que devuelve pseudomonas.com a cualquier cliente sin navegador."""
        html = (b"<!DOCTYPE html><html lang=\"en-US\"><head><title>Just a "
                b"moment...</title></head><body></body></html>")

        with self.assertRaises(F.FormatoDesconocido) as ctx:
            F.parsear_pgd(html)

        self.assertIn("html", str(ctx.exception))

    def test_un_cuerpo_vacio_falla(self):
        with self.assertRaises(F.FormatoDesconocido):
            F.parsear_pgd(b"")

    def test_un_cuerpo_que_no_es_csv_falla_con_el_error_del_contrato(self):
        """`csv.Error` no lo atrapa nadie: tiene que salir como
        FormatoDesconocido para que la descarga se conserve."""
        with self.assertRaises(F.FormatoDesconocido):
            F.parsear_pgd(b'"' + b"a" * 200000)

    def test_una_hebra_desconocida_falla_en_vez_de_adivinar(self):
        malo = PGD_CSV.replace("3897357,1,", "3897357,+,")

        with self.assertRaises(F.FormatoDesconocido) as ctx:
            F.parsear_pgd(malo.encode("utf-8"))

        self.assertIn("hebra", str(ctx.exception))

    def test_un_origen_desconocido_falla(self):
        """Un origen nuevo obliga a decidir si es predicción o literatura."""
        malo = PGD_CSV.replace('"metG","DOOR"', '"metG","OperonMapper"')

        with self.assertRaises(F.FormatoDesconocido):
            F.parsear_pgd(malo.encode("utf-8"))

    def test_un_locus_que_no_es_de_pao1_falla(self):
        malo = PGD_CSV.replace('"PA3482"', '"PA14_12345"')

        with self.assertRaises(F.FormatoDesconocido):
            F.parsear_pgd(malo.encode("utf-8"))


class PruebasExtraerPgd(unittest.TestCase):
    """`extraer --fuente pgd` sin red: la sesión se falsea."""

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        previo = os.environ.pop(F.VAR_PGD, None)
        if previo is not None:
            self.addCleanup(os.environ.__setitem__, F.VAR_PGD, previo)
        self.pedidas = []

    def _sesion(self, cuerpo=None):
        s = R.Sesion("alguien@unam.mx", pausa=0)

        def falso(url, datos=None, timeout=None):
            self.pedidas.append(url)
            return cuerpo if cuerpo is not None else PGD_CSV.encode("utf-8")
        s._abrir = falso
        return s

    def _extraer(self, url=None, cuerpo=None, archivo=None):
        return F.extraer(self.con, "pgd", self._sesion(cuerpo),
                         flag_datos=self.tmp.name, url=url, archivo=archivo)

    def test_sin_url_pide_la_tabla_fijada_y_la_parsea(self):
        informe = self._extraer()

        self.assertEqual(self.pedidas, [F.URL_PGD])
        self.assertEqual(informe["filas"], 5)
        self.assertTrue(informe["completa"])

    def test_una_segunda_corrida_no_vuelve_a_pedir(self):
        """La URL va fijada a un commit: sus bytes no pueden cambiar."""
        self._extraer()
        informe = self._extraer()

        self.assertEqual(self.pedidas, [F.URL_PGD])
        self.assertTrue(informe["ya_estaba"])
        self.assertEqual(len(D.extracciones_de(self.con, "pgd")), 1,
                         "una extracción abierta sin cerrar contaría como "
                         "corrida fallida")
        self.assertEqual(len(D.bronze_vigente(self.con)), 5)

    def test_otra_url_si_se_pide(self):
        """Una URL que no está fijada puede cambiar, y se vuelve a bajar."""
        self._extraer()
        self._extraer(url="https://otro.example/pao1_operones.csv")

        self.assertEqual(self.pedidas, [
            F.URL_PGD, "https://otro.example/pao1_operones.csv"])

    def test_pedir_la_tabla_fijada_a_proposito_si_la_baja(self):
        """`--url` explícito es una orden, no una sugerencia."""
        self._extraer()
        self._extraer(url=F.URL_PGD)

        self.assertEqual(self.pedidas, [F.URL_PGD, F.URL_PGD])

    def test_una_tabla_mas_nueva_no_se_revierte_a_la_fijada(self):
        """Con la tabla nueva vigente, bajar la de 2021 la reemplazaría y
        daría por retirados los operones que solo trae la nueva."""
        self._extraer()
        nueva = os.path.join(self.tmp.name, "pgd_nueva.csv")
        with io.open(nueva, "w", encoding="utf-8", newline="") as f:
            f.write(PGD_CSV + u'"operon-9","dnaA-dnaN","PA0001",483,2027,1,'
                              u'"dnaA","DOOR",18988623\n')
        self._extraer(archivo=nueva)

        informe = self._extraer()

        self.assertTrue(informe["ya_estaba"])
        self.assertEqual(self.pedidas, [F.URL_PGD])
        self.assertEqual(len(D.bronze_vigente(self.con)), 6)
        self.assertEqual(D.retirados(self.con), {})

    def test_una_foto_que_no_se_pudo_leer_se_rehace(self):
        """Un parseo fallido también cierra la extracción como completa. Si
        contara como «ya está», PGD se quedaría vacía para siempre."""
        self._extraer(cuerpo=b"<html><body>Blocked</body></html>")
        self.assertEqual(D.bronze_vigente(self.con), [])

        informe = self._extraer()

        self.assertEqual(self.pedidas, [F.URL_PGD, F.URL_PGD])
        self.assertEqual(informe["filas"], 5)

    def test_sin_el_crudo_en_disco_se_vuelve_a_bajar(self):
        """`reparsear` pide volver a extraer si falta el crudo; si `extraer`
        contestara «ya está», cada comando mandaría al otro."""
        self._extraer()
        os.remove(D.descargas_de(self.con, "pgd")[0]["ruta"])

        self._extraer()

        self.assertEqual(self.pedidas, [F.URL_PGD, F.URL_PGD])


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

    def test_dos_fuentes_que_listan_el_operon_al_reves_son_uno_solo(self):
        """El orden es del nombre, no de la identidad.

        Con la clave sensible al orden, `mexAB-oprM` salia DOS VECES: ODB lo
        escribe PA0425|PA0426|PA0427 y BioCyc PA0427|PA0426|PA0425, porque
        cada una lista los miembros en su propio sentido. El solapamiento
        entre fuentes salia artificialmente bajo y dos operones bien conocidos
        aparecian como "ausentes en BioCyc" cuando BioCyc los tiene.
        """
        _bronce(self.con, [
            _fila("odb", "op1", "PA0425|PA0426|PA0427"),
            _fila("biocyc", "TU-1", "PA0427|PA0426|PA0425")])

        self._curar()
        filas = D.silver_de(self.con)

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["n_fuentes"], 2)
        self.assertEqual(filas[0]["clave_genes"], "PA0425|PA0426|PA0427")

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

    def test_biocyc_y_pgd_cuentan_como_dos_fuentes(self):
        """PGD predice con DOOR y BioCyc con Pathway Tools: son motores
        distintos. Hasta el 27-sep-2026 contaban como una sola fuente por una
        premisa falsa, la de que PGD también usaba Pathway Tools."""
        _bronce(self.con, [
            _fila("biocyc", "TU-1", "PA0425|PA0426"),
            _fila("pgd", "op1", "PA0425|PA0426", tipo_evidencia="DOOR")])

        self._curar()

        self.assertEqual(D.silver_de(self.con)[0]["n_fuentes"], 2)

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


CDBPROM = (u"\n".join([
    "# CDBProm - Promoter prediction database",
    "# Instituto de Investigaciones en Matematicas Aplicadas y en Sistemas",
    "# Universidad Nacional Autonoma de Mexico",
    "# Organism: Pseudomonas aeruginosa PAO1",
    "# Genome: NC_002516.2",
    "# Model: XGBoost",
    "# Score threshold: 0.5",
    "# Strand: F = forward, R = reverse",
    "# Columns: NCBI ID, organism, locus tag, start, end, strand, score, "
    "label, sequence, annotation",
    "#",
    "\t".join(["NC_002516.2", "P. aeruginosa PAO1", "PA0425", "100", "179",
               "D", "0.91", "promoter", "A" * 60, "mexA"]),
    "\t".join(["NC_002516.2", "P. aeruginosa PAO1", "PA2493", "500", "579",
               "R", "0.72", "promoter", "C" * 60, "mexE"]),
]) + u"\n")


class PruebasArchivoLocal(unittest.TestCase):
    """Ingesta de un archivo que ya esta en disco, sin red."""

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.origen = os.path.join(self.tmp.name, "cdbprom_pao1.tsv")
        with io.open(self.origen, "w", encoding="utf-8", newline="") as f:
            f.write(CDBPROM)

    def test_el_archivo_se_copia_a_la_carpeta_de_crudos(self):
        """Un volcado que vive en la carpeta de descargas de alguien se mueve
        o se borra, y entonces `reparsear` deja de funcionar y la huella
        registrada apunta a nada."""
        carpeta = os.path.join(self.tmp.name, "crudo")
        os.makedirs(carpeta)

        bajadas = F.traer_archivo_local(self.origen, "cdbprom", carpeta)

        url, ruta, cuerpo = bajadas[0]
        self.assertTrue(os.path.exists(ruta))
        self.assertNotEqual(os.path.dirname(ruta),
                            os.path.dirname(self.origen))
        self.assertEqual(cuerpo, io.open(self.origen, "rb").read())

    def test_la_procedencia_dice_que_no_es_una_url(self):
        """Ponerle una URL inventada habria hecho creer que se puede volver a
        bajar."""
        carpeta = os.path.join(self.tmp.name, "crudo2")
        os.makedirs(carpeta)

        url, _r, _c = F.traer_archivo_local(self.origen, "cdbprom", carpeta)[0]

        self.assertTrue(url.startswith("archivo-local:"))

    def test_un_archivo_que_no_esta_falla_diciendolo(self):
        with self.assertRaises(F.FormatoDesconocido):
            F.traer_archivo_local(os.path.join(self.tmp.name, "no.tsv"),
                                  "cdbprom", self.tmp.name)


class PruebasParserCdbprom(unittest.TestCase):
    """El volcado de CDBProm: promotores, no operones."""

    def _cuerpo(self, texto=None):
        return (texto or CDBPROM).encode("utf-8")

    def test_salta_las_diez_lineas_de_encabezado(self):
        filas = F.parsear_cdbprom(self._cuerpo())

        self.assertEqual(len(filas), 2)
        self.assertEqual(sorted(f["id_fuente"] for f in filas),
                         ["PA0425", "PA2493"])

    def test_la_cadena_D_es_directa_aunque_el_encabezado_diga_F(self):
        """Los datos usan D/R y el encabezado dice F/R. Se acepta D."""
        por_locus = dict((f["id_fuente"], f)
                         for f in F.parsear_cdbprom(self._cuerpo()))

        self.assertEqual(por_locus["PA0425"]["cadena"], "+")
        self.assertEqual(por_locus["PA2493"]["cadena"], "-")

    def test_una_cadena_desconocida_falla_en_vez_de_adivinar(self):
        """Una cadena mal leida invierte el sentido del promotor, y un
        promotor aguas arriba del gen equivocado es peor que ninguno."""
        malo = CDBPROM.replace("\tD\t", "\tX\t")

        with self.assertRaises(F.FormatoDesconocido) as ctx:
            F.parsear_cdbprom(self._cuerpo(malo))

        self.assertIn("cadena", str(ctx.exception).lower())

    def test_guarda_coordenadas_y_secuencia_tal_cual(self):
        """El rango abarca 80 pb y la secuencia mide 60 nt. La discrepancia es
        del volcado; resolverla a ojo seria inventar una convencion que la
        fuente no declara."""
        f = F.parsear_cdbprom(self._cuerpo())[0]
        crudo = f["registro_raw"]

        self.assertEqual(crudo["largo_rango"], 80)
        self.assertEqual(crudo["largo_secuencia"], 60)
        self.assertEqual(crudo["cadena_original"], "D")

    def test_guarda_el_score_como_atributo(self):
        por_locus = dict((f["id_fuente"], f)
                         for f in F.parsear_cdbprom(self._cuerpo()))

        self.assertEqual(por_locus["PA0425"]["registro_raw"]["score"], "0.91")

    def test_un_locus_repetido_conserva_el_de_mayor_score(self):
        """El perfil dice un promotor maximo por locus tag. Elegir en silencio
        dejaria al operon marcado por un promotor que no es el mejor."""
        doble = CDBPROM + "\t".join(
            ["NC_002516.2", "P. aeruginosa PAO1", "PA0425", "900", "979",
             "D", "0.99", "promoter", "G" * 60, "mexA"]) + "\n"

        por_locus = dict((f["id_fuente"], f)
                         for f in F.parsear_cdbprom(doble.encode("utf-8")))

        self.assertEqual(len(por_locus), 2)
        self.assertEqual(por_locus["PA0425"]["registro_raw"]["score"], "0.99")

    def test_un_volcado_con_menos_columnas_falla(self):
        corto = CDBPROM.rsplit("\n", 2)[0] + "\nNC_002516.2\tsolo\tdos\n"

        with self.assertRaises(F.FormatoDesconocido):
            F.parsear_cdbprom(corto.encode("utf-8"))


class PruebasPromotorEnLaCuracion(unittest.TestCase):
    """Regla 5: CDBProm marca operones, no los crea."""

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ruta = os.path.join(self.tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        self.dicc = C.cargar_diccionario(ruta)
        _bronce(self.con, [
            _fila("odb", "op1", "PA0425|PA0426|PA0427"),
            _fila("odb", "op2", "PA2493|PA2494"),
            # Promotor sobre el PRIMER gen de op1 y sobre el SEGUNDO de op2.
            _fila("cdbprom", "PA0425", "PA0425"),
            _fila("cdbprom", "PA2494", "PA2494")])
        self.resumen = C.curar(self.con, diccionario=self.dicc, hebras={})

    def test_cdbprom_no_crea_operones(self):
        """1 972 promotores habrian fabricado 1 972 unidades monocistronicas
        que nadie ha observado transcribirse."""
        claves = set(f["clave_genes"] for f in D.silver_de(self.con))

        self.assertEqual(claves,
                         {"PA0425|PA0426|PA0427", "PA2493|PA2494"})
        self.assertEqual(self.resumen["promotores_cdbprom"], 2)

    def test_marca_el_operon_cuyo_primer_gen_tiene_promotor(self):
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(self.con))

        self.assertTrue(por_clave["PA0425|PA0426|PA0427"]["promotor_cdbprom"])

    def test_un_promotor_interno_no_marca_el_operon(self):
        """Un promotor sobre el segundo gen no inicia la unidad."""
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(self.con))

        self.assertFalse(por_clave["PA2493|PA2494"]["promotor_cdbprom"])


class PruebasPrimerGen(unittest.TestCase):
    """El primer gen transcrito lo decide la hebra, no el orden de la fuente.

    Cada fuente lista los miembros en su propio sentido: BioCyc en orden
    descendente en las dos hebras y ODB en orden ascendente. Tomar el primero
    de la lista ponía el gen equivocado en 515 de 1 082 operones multigénicos
    del silver del 25-sep-2026.
    """

    def test_en_mas_es_el_de_numero_menor(self):
        self.assertEqual(
            C.primer_gen(["PA0427", "PA0426", "PA0425"], "+"), "PA0425")

    def test_en_menos_es_el_de_numero_mayor(self):
        self.assertEqual(C.primer_gen(["PA2493", "PA2494"], "-"), "PA2494")

    def test_el_sufijo_punto_cuenta_en_el_orden(self):
        """`PA0668.1` va después de `PA0668` en el genoma."""
        self.assertEqual(C.primer_gen(["PA0668.1", "PA0668"], "+"), "PA0668")
        self.assertEqual(C.primer_gen(["PA0668", "PA0668.1"], "-"), "PA0668.1")

    def test_sin_hebra_se_queda_con_el_primero_de_la_lista(self):
        self.assertEqual(C.primer_gen(["PA2493", "PA2494"], None), "PA2493")

    def test_el_orden_de_transcripcion_es_la_misma_regla(self):
        """`primer_gen` y el catálogo salen de `orden_transcripcion`, para
        que el primer gen que muestra el catálogo sea el del promotor."""
        self.assertEqual(C.orden_transcripcion([], "+"), [])
        self.assertEqual(
            C.orden_transcripcion(["PA0668.1", "PA0668", "PA0668.2"], "-"),
            ["PA0668.2", "PA0668.1", "PA0668"])
        self.assertEqual(
            C.orden_transcripcion(["PA2494", "PA2493"], None),
            ["PA2494", "PA2493"], "sin hebra no se reordena")

    def test_la_curacion_marca_por_hebra_y_no_por_posicion(self):
        """ODB escribe ascendente un operón de la hebra menos, y BioCyc
        descendente uno de la hebra más: en los dos, el promotor del primer
        gen transcrito está en el ÚLTIMO de la lista."""
        con = _con()
        self.addCleanup(con.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ruta = os.path.join(tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        _bronce(con, [
            _fila("odb", "menos", "PA2493|PA2494"),
            _fila("biocyc", "mas", "PA0427|PA0426|PA0425"),
            _fila("cdbprom", "PA2494", "PA2494"),
            _fila("cdbprom", "PA0425", "PA0425")])

        C.curar(con, diccionario=C.cargar_diccionario(ruta),
                hebras={"PA2493": "-", "PA2494": "-", "PA0425": "+",
                        "PA0426": "+", "PA0427": "+"})
        por_clave = dict((f["clave_genes"], f) for f in D.silver_de(con))

        self.assertTrue(por_clave["PA2493|PA2494"]["promotor_cdbprom"])
        self.assertTrue(por_clave["PA0425|PA0426|PA0427"]["promotor_cdbprom"])

    def test_un_promotor_sobre_el_ultimo_transcrito_no_marca(self):
        con = _con()
        self.addCleanup(con.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ruta = os.path.join(tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        # En la hebra menos, PA2493 es el ÚLTIMO en transcribirse.
        _bronce(con, [_fila("odb", "menos", "PA2493|PA2494"),
                      _fila("cdbprom", "PA2493", "PA2493")])

        C.curar(con, diccionario=C.cargar_diccionario(ruta),
                hebras={"PA2493": "-", "PA2494": "-"})

        self.assertFalse(D.silver_de(con)[0]["promotor_cdbprom"])


class PruebasNivelDeEvidencia(unittest.TestCase):
    """La regla 4, por unidad y no por fuente.

    BioCyc mezcla en la misma consulta 39 unidades con respaldo experimental y
    3 705 predichas por Pathway Tools: darle a toda la fuente el nivel de su
    mejor fila, o el de la peor, seria falso en las dos direcciones.
    """

    def _fila(self, codigos, pmid=None):
        return {"tipo_evidencia": codigos, "pmid": pmid}

    def test_ev_exp_con_pmid_es_conocido(self):
        nivel, marcas = C.nivel_de_fila(
            self._fila("EV-EXP-IDA", "12345"), "biocyc")

        self.assertEqual((nivel, marcas), ("conocido", []))

    def test_ev_exp_sin_pmid_es_curado(self):
        nivel, marcas = C.nivel_de_fila(self._fila("EV-EXP-IEP"), "biocyc")

        self.assertEqual((nivel, marcas), ("curado", []))

    def test_solo_ev_comp_es_predicho(self):
        nivel, marcas = C.nivel_de_fila(self._fila("EV-COMP-AINF"), "biocyc")

        self.assertEqual((nivel, marcas), ("predicho", []))

    def test_ev_comp_con_cita_sigue_predicho_y_se_marca(self):
        """La cita de una prediccion suele ser la del metodo, no la de una
        demostracion del operon. Dejar que el PMID mande habria subido 16
        predicciones a conocido por la puerta de atras."""
        nivel, marcas = C.nivel_de_fila(
            self._fila("EV-COMP-AINF", "19683048"), "biocyc")

        self.assertEqual(nivel, "predicho")
        self.assertEqual(marcas, ["comp_con_cita"])

    def test_sin_codigo_ni_cita_es_predicho_con_marca(self):
        """Sin codigo no es lo mismo que predicho, aunque acabe en el mismo
        nivel: son unidades que no declaran metodo, y sin la marca se
        confunden con las 3 705 que si."""
        nivel, marcas = C.nivel_de_fila(self._fila(None), "biocyc")

        self.assertEqual((nivel, marcas), ("predicho", ["sin_evidencia"]))

    def test_sin_codigo_pero_con_cita_queda_pendiente_de_revision(self):
        """El unico caso ambiguo de la fuente: no declara metodo y trae un
        articulo. `EV-COMP*` con cita no es ambiguo --en la ontologia de
        BioCyc lo computacional lo decide el codigo-- pero aqui no hay codigo
        que lo decida. Son 16 unidades y 20 PMIDs distintos."""
        nivel, marcas = C.nivel_de_fila(self._fila(None, "14617143"), "biocyc")

        self.assertEqual((nivel, marcas), ("predicho", ["pendiente_revision"]))

    def test_entre_varios_codigos_manda_ev_exp(self):
        """Una unidad respaldada por experimento no deja de estarlo porque
        ademas la haya predicho un programa."""
        nivel, _m = C.nivel_de_fila(
            self._fila("EV-COMP-AINF;EV-EXP-IDA;EV-COMP", "999"), "biocyc")

        self.assertEqual(nivel, "conocido")

    def test_odb_con_pmid_es_conocido(self):
        nivel, _m = C.nivel_de_fila(
            self._fila("literatura", "12345"), "odb")

        self.assertEqual(nivel, "conocido")

    def test_pgd_pseudocap_con_pmid_es_conocido(self):
        """PseudoCAP es literatura curada; sus PMIDs, aunque sean varios, lo
        hacen conocido."""
        nivel, marcas = C.nivel_de_fila(
            self._fila("PseudoCAP", "8169201;9286981"), "pgd")

        self.assertEqual((nivel, marcas), ("conocido", []))

    def test_pgd_door_es_predicho_sin_marca(self):
        """El parser deja la cita del método fuera de `pmid`, así que DOOR no
        llega aquí con PMID y no hay `comp_con_cita` que marcar."""
        nivel, marcas = C.nivel_de_fila(self._fila("DOOR"), "pgd")

        self.assertEqual((nivel, marcas), ("predicho", []))

    def test_el_grupo_se_queda_con_el_mejor_nivel(self):
        """Si ODB lo documenta y BioCyc lo predice, el operon esta
        documentado; y la marca de la prediccion se conserva."""
        filas = [
            {"fuente": "odb", "tipo_evidencia": "literatura", "pmid": "111"},
            {"fuente": "biocyc", "tipo_evidencia": "EV-COMP-AINF",
             "pmid": "222"},
        ]

        nivel, marcas, codigos = C.nivel_de(filas, lambda f: f["fuente"])

        self.assertEqual(nivel, "conocido")
        self.assertIn("comp_con_cita", marcas)
        self.assertIn("biocyc:EV-COMP-AINF", codigos)

    def test_los_codigos_originales_se_conservan(self):
        """El nivel es una lectura nuestra; el codigo es el dato del que
        salio, y sin el no hay forma de revisar la lectura."""
        filas = [{"fuente": "biocyc",
                  "tipo_evidencia": "EV-EXP-IDA;EV-COMP-AINF", "pmid": "1"}]

        _n, _m, codigos = C.nivel_de(filas, lambda f: f["fuente"])

        self.assertEqual(codigos,
                         ["biocyc:EV-EXP-IDA", "biocyc:EV-COMP-AINF"])


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


class PruebasVistaPgd(unittest.TestCase):
    """El CSV con las columnas de la página de operones de pseudomonas.com."""

    ANOTACION = (u"locus_tag\tsimbolo\talias\ttipo\tproducto\tes_tf\t"
                 u"fuente_tf\tfuente\tsensible_mayusculas\n"
                 u"PA3482\tmetG\tPA3482\tprotein_coding\t"
                 u"methionine--tRNA ligase\tfalse\t\trefseq\tfalse\n")

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _bronce(self.con, F.parsear_pgd(PGD_CSV.encode("utf-8")))
        ruta = os.path.join(self.tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(self.ANOTACION)
        self.filas = E.filas_pgd(self.con, D, E.cargar_anotacion(ruta))

    def test_una_fila_por_gen_sin_repetidos(self):
        """13 renglones en el archivo, 10 genes distintos por operón."""
        self.assertEqual(len(self.filas), 10)

    def test_los_operones_van_en_orden_numerico(self):
        """`operon-10` después de `operon-2`: el orden textual los invierte."""
        ids = []
        for f in self.filas:
            if f["operon_id"] not in ids:
                ids.append(f["operon_id"])

        self.assertEqual(ids, ["operon-2", "operon-6", "operon-714",
                               "operon-41779", "operon-41798"])

    def test_la_fila_de_metg_es_la_de_la_pagina(self):
        """La captura de `feature/show/?id=109783&view=operons`."""
        metg = [f for f in self.filas if f["locus_tag"] == "PA3482"][0]

        self.assertEqual(metg["operon"], "metG-PA3483")
        self.assertEqual(metg["gen"], "metG")
        self.assertEqual((metg["inicio"], metg["fin"], metg["hebra"]),
                         (3895324, 3897357, "+"))
        self.assertEqual(metg["evidencia"], "Computationally-predicted (DOOR)")
        self.assertEqual(metg["pmid"], "18988623",
                         "la página muestra la cita del método")
        self.assertEqual(metg["descripcion"], "methionine--tRNA ligase")

    def test_un_locus_sin_anotacion_queda_en_blanco(self):
        pa3483 = [f for f in self.filas if f["locus_tag"] == "PA3483"][0]

        self.assertEqual((pa3483["descripcion"], pa3483["tipo"]), ("", ""))

    def test_el_encabezado_es_para_humanos_y_las_claves_no(self):
        ruta = os.path.join(self.tmp.name, "pgd.csv")

        E.escribir_csv(ruta, E.COLUMNAS_PGD, self.filas,
                       encabezados=E.ENCABEZADOS_PGD)

        with io.open(ruta, encoding="utf-8") as f:
            primera = f.readline().strip()
        self.assertTrue(primera.startswith(u"ID del operón,Operón,Locus tag"))


class PruebasCatalogo(unittest.TestCase):
    """El catálogo maestro: una fila por operón, trazable a cada fuente.

    El caso de `mexAB-oprM` es el real: lo tienen ODB, BioCyc y PGD, y PGD
    dos veces, como predicción de DOOR con nombre sintético y como
    literatura de PseudoCAP con un ID por artículo.
    """

    PASO1 = (u"operon\tmiembros\tlocus_tags\tfuente\n"
             u"mexAB-oprM\tmexA|mexB|oprM\tPA0425|PA0426|PA0427\t"
             u"refseq_adyacencia\n")

    def setUp(self):
        self.con = _con()
        self.addCleanup(self.con.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ruta = os.path.join(self.tmp.name, "genes.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(GENES_TSV)
        self.dicc = C.cargar_diccionario(ruta)
        self.anotacion = E.cargar_anotacion(ruta)
        self.hebras = {"PA0425": "+", "PA0426": "+", "PA0427": "+",
                       "PA2493": "-", "PA2494": "-"}
        _bronce(self.con, [
            _fila("odb", "op1", "PA0425|PA0426|PA0427", pmid="123",
                  tipo_evidencia="literatura",
                  registro_raw={"name": "mexAB-oprM"}),
            _fila("biocyc", "TU-1", "PA0427|PA0426|PA0425",
                  tipo_evidencia="EV-EXP-IDA"),
            _fila("biocyc", "TU-2", "PA2493|PA2494"),
            _fila("pgd", "operon-89", "PA0425|PA0426|PA0427",
                  tipo_evidencia="DOOR",
                  registro_raw={"name": "mexA-mexB-oprM",
                                "source_database": "DOOR"}),
            # Dos IDs de PseudoCAP con el mismo nombre: uno por artículo. El
            # orden textual pondría 41728 antes que 5000.
            _fila("pgd", "operon-41728", "PA0425|PA0426|PA0427",
                  tipo_evidencia="PseudoCAP", pmid="10648542",
                  registro_raw={"name": "mexAB-oprM",
                                "source_database": "PseudoCAP"}),
            _fila("pgd", "operon-5000", "PA0425|PA0426|PA0427",
                  tipo_evidencia="PseudoCAP", pmid="11053384",
                  registro_raw={"name": "mexAB-oprM",
                                "source_database": "PseudoCAP"}),
            _fila("cdbprom", "PA0425", "PA0425",
                  registro_raw={"score": "0.91"}),
            _fila("cdbprom", "PA2494", "PA2494",
                  registro_raw={"score": "0.87"}),
        ])
        self.paso1 = {"PA0425|PA0426|PA0427": "mexAB-oprM"}

    def _catalogo(self, hebras=None, paso1="omision"):
        C.curar(self.con, diccionario=self.dicc,
                hebras=self.hebras if hebras is None else hebras)
        filas = E.filas_catalogo(self.con, D, self.anotacion,
                                 self.paso1 if paso1 == "omision" else paso1)
        return dict((f["clave_genes"], f) for f in filas)

    def test_una_fila_por_operon_curado(self):
        self.assertEqual(sorted(self._catalogo()),
                         ["PA0425|PA0426|PA0427", "PA2493|PA2494"])

    def test_cada_fuente_con_su_id_y_su_nombre(self):
        mex = self._catalogo()["PA0425|PA0426|PA0427"]

        self.assertEqual(mex["id_odb"], "op1")
        self.assertEqual(mex["nombre_odb"], "mexAB-oprM")
        self.assertEqual(mex["id_biocyc"], "TU-1")
        self.assertEqual(mex["id_door"], "operon-89")
        self.assertEqual(mex["nombre_door"], "mexA-mexB-oprM")

    def test_pseudocap_separado_de_door_en_orden_numerico_y_sin_repetir(self):
        mex = self._catalogo()["PA0425|PA0426|PA0427"]

        self.assertEqual(mex["id_pseudocap"], "operon-5000;operon-41728")
        self.assertEqual(mex["nombre_pseudocap"], "mexAB-oprM")

    def test_cdbprom_tiene_columnas_propias_y_no_cuenta_como_fuente(self):
        """Decidido el 27-sep: CDBProm marca operones, no los crea ni los
        confirma. Contarlo inflaría «con dos o más fuentes»."""
        mex = self._catalogo()["PA0425|PA0426|PA0427"]

        self.assertEqual(mex["fuentes"], "biocyc;odb;pgd")
        self.assertEqual(mex["n_fuentes"], 3)
        self.assertEqual((mex["promotor_cdbprom"], mex["gen_con_promotor"],
                          mex["score_cdbprom"]), ("sí", "PA0425", "0.91"))

    def test_en_la_hebra_menos_el_orden_y_el_promotor_se_invierten(self):
        mexef = self._catalogo()["PA2493|PA2494"]

        self.assertEqual(mexef["locus_tags"], "PA2494|PA2493")
        self.assertEqual(mexef["genes"], "mexF mexE")
        self.assertEqual(mexef["orden_verificado"], "sí")
        self.assertEqual((mexef["gen_con_promotor"], mexef["score_cdbprom"]),
                         ("PA2494", "0.87"))

    def test_sin_hebra_el_orden_es_el_de_la_fuente_y_se_dice(self):
        mexef = self._catalogo(hebras={})["PA2493|PA2494"]

        self.assertEqual(mexef["orden_verificado"], "no")
        self.assertEqual(mexef["locus_tags"], "PA2493|PA2494")

    def test_el_catalogo_del_paso_1_en_sus_tres_casos(self):
        filas = self._catalogo()
        self.assertEqual(filas["PA0425|PA0426|PA0427"]["en_catalogo_paso1"],
                         "sí")
        self.assertEqual(
            filas["PA0425|PA0426|PA0427"]["nombre_catalogo_paso1"],
            "mexAB-oprM")
        self.assertEqual(filas["PA2493|PA2494"]["en_catalogo_paso1"], "no")

        sin_tsv = self._catalogo(paso1=None)["PA2493|PA2494"]

        self.assertEqual(sin_tsv["en_catalogo_paso1"], "",
                         "sin el TSV no se comprobó: un «no» mentiría")

    def test_claves_paso1_usa_la_expansion_del_paso_1(self):
        from grn_bronce import operones as P
        ruta = os.path.join(self.tmp.name, "operones.tsv")
        with io.open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(self.PASO1)

        claves = E.claves_paso1(P.leer(ruta),
                                P.Catalogo.cargar(ruta).locus_tags)

        self.assertEqual(claves, self.paso1)

    def test_la_hoja_de_fuentes_no_publica_rutas_locales(self):
        self._catalogo()
        filas = E.filas_fuentes_catalogo(self.con, D, F.FUENTES, F.URL_PGD)

        self.assertTrue(all("ruta" not in f for f in filas))
        self.assertNotIn("r", [f.get("origen") for f in filas],
                         "`r` es la ruta del fixture; el origen es `u`")
        cdb = [f for f in filas if f["fuente"] == "cdbprom"][0]
        self.assertEqual(cdb["aporta"], "marca promotores")
        self.assertEqual(cdb["unidades"], 2)

    def test_el_leame_trae_las_cifras_de_la_corrida(self):
        catalogo = list(self._catalogo().values())
        fuentes = E.filas_fuentes_catalogo(self.con, D, F.FUENTES, F.URL_PGD)

        texto = "\n".join(E.lineas_leame(catalogo, fuentes, self.paso1))

        self.assertIn("2 unidades", texto)
        self.assertIn("marca 2 operones", texto)
        self.assertIn("1 unidades coinciden", texto)

    def test_encabezados_y_columnas_van_parejos(self):
        self.assertEqual(len(E.COLUMNAS_CATALOGO),
                         len(E.ENCABEZADOS_CATALOGO))
        self.assertEqual(len(E.COLUMNAS_FUENTES_CATALOGO),
                         len(E.ENCABEZADOS_FUENTES_CATALOGO))

    def test_sin_openpyxl_se_dice_y_se_sigue(self):
        with mock.patch.dict(sys.modules, {"openpyxl": None}):
            ok = E.escribir_xlsx_catalogo(
                os.path.join(self.tmp.name, "c.xlsx"), [], [], ["x"])

        self.assertFalse(ok)

    def test_el_xlsx_tiene_tres_hojas_y_no_ejecuta_formulas(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl no está instalado")
        catalogo = list(self._catalogo().values())
        catalogo[0]["nombre"] = "=HYPERLINK(\"x\")"
        catalogo[0]["motivo"] = "con\x01control"
        fuentes = E.filas_fuentes_catalogo(self.con, D, F.FUENTES, F.URL_PGD)
        ruta = os.path.join(self.tmp.name, "c.xlsx")

        self.assertTrue(E.escribir_xlsx_catalogo(ruta, catalogo, fuentes,
                                                 ["uno", "dos"]))

        libro = openpyxl.load_workbook(ruta)
        self.assertEqual(libro.sheetnames, [u"Catálogo", "Fuentes", u"Léame"])
        hoja = libro[u"Catálogo"]
        self.assertEqual(hoja.max_row, 3)
        col = E.COLUMNAS_CATALOGO.index("nombre") + 1
        self.assertEqual(hoja.cell(row=2, column=col).data_type, "s")
        self.assertIsInstance(
            hoja.cell(row=2, column=E.COLUMNAS_CATALOGO.index(
                "score_cdbprom") + 1).value, float)


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
