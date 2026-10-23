"""Pruebas de `grn_verificacion/muestra.py`, el sorteo de la muestra ciega.

Todo es sintético: oraciones inventadas, PMIDs 900xx y locus PA9xxx. La única
lectura de un archivo real es la cabecera de `capa_pares.csv`, en la prueba de
humo, y se salta si el archivo no está.
"""

import codecs
import csv
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from grn_comun import procedencia
from grn_verificacion import cli, entrenamiento, muestra

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COLUMNAS_CAPA = [
    "corrida_bronce", "pmid", "fuente_texto", "seccion", "num_oracion",
    "id_par", "oracion", "disparador", "signo_sugerido",
    "regulador_candidato", "blanco_candidato", "score", "tf", "target",
    "tf_id", "target_id", "tf_locus", "target_locus", "mencion_tf",
    "mencion_target", "par_del_bronce", "prediccion", "p_activates",
    "p_no_relation", "p_regulates", "p_represses", "pasa_umbral",
    "signo_biobert", "regulador_sintactico", "voz", "direccion_sintaxis"]

# Lo que la hoja no puede llevar: si alguno aparece en ella, se coló.
CENTINELAS = {
    "seccion": "seccion_centinela",
    "disparador": "disparador_centinela",
    "signo_sugerido": "signo_centinela",
    "score": "0.123456",
    "prediccion": "prediccion_centinela",
    "p_activates": "0.987654",
    "p_no_relation": "0.011111",
    "p_regulates": "0.022222",
    "p_represses": "0.033333",
    "pasa_umbral": "umbral_centinela",
    "signo_biobert": "biobert_centinela",
    "regulador_sintactico": "sintactico_centinela",
    "voz": "voz_centinela",
    "direccion_sintaxis": "concuerda_centinela",
}

RESERVADA_IGUAL = ("The sigma factor sgmX controls the entire flagellar "
                   "regulon of this strain.")
RESERVADA_CONTENIDA = ("The response regulator rspR binds directly to the "
                       "promoter of rspT")
FRAGMENTO = ("the two-component system tcsR represses tcsT under iron "
             "limitation")
RESERVADA_CORTA = "short srtR binds srtT"


def _fila(pmid, num, oracion, regulador, blanco, mencion_r=None,
          mencion_b=None, par="directo", fuente="xml", id_par=None,
          locus=9000):
    fila = dict(CENTINELAS)
    fila.update({
        "corrida_bronce": "4", "pmid": str(pmid), "fuente_texto": fuente,
        "num_oracion": str(num),
        "id_par": id_par or "%s%s%04d%s" % (pmid, fuente[0], num, par[0]),
        "oracion": oracion,
        "regulador_candidato": regulador, "blanco_candidato": blanco,
        "tf": mencion_r or regulador, "target": mencion_b or blanco,
        "tf_id": regulador, "target_id": blanco,
        "tf_locus": "PA%04d" % locus, "target_locus": "PA%04d" % (locus + 1),
        "mencion_tf": mencion_r or regulador,
        "mencion_target": mencion_b or blanco, "par_del_bronce": par,
    })
    return fila


def filas_sinteticas():
    """58 oraciones con el par del bronce; 50 quedan tras las exclusiones."""
    filas = []
    # 48 genéricas, 4 por artículo. Las pares nombran primero al regulador y
    # las nones al blanco; el regulador se escribe como proteína en la
    # oración (Reg7R) y como gen en el id del bronce (reg7R).
    for i in range(48):
        pmid, num = 90002 + i // 4, 1 + i % 4
        reg, bla = "reg%dR" % i, "tgt%dZ" % i
        mencion = "Reg%dR" % i
        if i % 2 == 0:
            oracion = ("The regulator %s directly activates transcription "
                       "of %s in sample %d cells." % (mencion, bla, i))
        else:
            oracion = ("Expression of %s dropped sharply after deletion of "
                       "%s in sample %d cells." % (bla, mencion, i))
        filas.append(_fila(pmid, num, oracion, reg, bla, mencion_r=mencion,
                           locus=9000 + 2 * i))
        # Otro par de la misma oración: no puede volverla dos ítems.
        filas.append(_fila(pmid, num, oracion, reg, bla, mencion_r=mencion,
                           par="otro", locus=9500 + i))
    # Reservadas por PMID.
    for num in (1, 2, 3):
        filas.append(_fila(90001, num, "Gene res%dR activates res%dT in the "
                           "reserved article." % (num, num),
                           "res%dR" % num, "res%dT" % num))
    # Igual a una reservada, con otro corte de espacios.
    filas.append(_fila(90020, 1, RESERVADA_IGUAL.replace(" entire ",
                                                         " entire\n"),
                       "sgmX", "flgA"))
    # Contiene una reservada de 40 caracteres o más.
    filas.append(_fila(90020, 2, "In addition, %s under iron limitation."
                       % RESERVADA_CONTENIDA, "rspR", "rspT"))
    # Es un pedazo de 40 caracteres o más de una reservada.
    filas.append(_fila(90020, 3, FRAGMENTO, "tcsR", "tcsT"))
    # Contiene una reservada de menos de 40: se queda.
    filas.append(_fila(90021, 1, "We observed that %s under every condition "
                       "tested here." % RESERVADA_CORTA, "srtR", "srtT"))
    # El bronce la orientó pero su par no llegó al clasificador.
    filas.append(_fila(90022, 1, "Gene opR activates the opAB operon in "
                       "sample cells.", "opR", "opBA", par="otro"))
    # Repetida: el mismo texto canónico en el resumen y en el texto completo.
    filas.append(_fila(90023, 1, "Gene dupR activates dupT in sample cells.",
                       "dupR", "dupT", fuente="abstract"))
    filas.append(_fila(90023, 7, "gene dupR activates dupT in sample cells",
                       "dupR", "dupT", fuente="xml"))
    # Oraciones sin par del bronce: no son población.
    for num in (1, 2):
        filas.append(_fila(90024, num, "Genes nopA and nopB were both "
                           "detected in sample %d." % num, "", "",
                           par="sin_par"))
    return filas


def escribir_capa(carpeta, filas=None, columnas=None):
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "capa_pares.csv")
    columnas = columnas or COLUMNAS_CAPA
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas if filas is not None else filas_sinteticas():
            w.writerow(fila)
    return ruta


def escribir_reservas(ruta):
    lineas = [
        "# reservas sintéticas",
        "pmid\t90001",
        "oracion\t%s" % RESERVADA_IGUAL.replace(" sigma ", "  sigma "),
        "oracion\t%s" % RESERVADA_CONTENIDA,
        "oracion\tEarlier reports showed that %s and we confirmed it."
        % FRAGMENTO,
        "oracion\t%s" % RESERVADA_CORTA,
    ]
    with io.open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")
    return ruta


def leer_csv(ruta):
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        return lector.fieldnames, list(lector)


def columnas_de_la_rubrica():
    """Las columnas de la tabla del §6 de la rúbrica, en su orden."""
    ruta = os.path.join(RAIZ, "docs", "rubrica-anotacion.md")
    with io.open(ruta, encoding="utf-8") as f:
        texto = f.read()
    seccion = texto.split("## 6.", 1)[1].split("\n## 7.", 1)[0]
    tabla = seccion.split("| columna |", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^\| `([a-z_0-9]+)` \|", tabla, re.M)


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.carpeta = os.path.join(self.tmp, "corrida")
        self.ruta_capa = escribir_capa(self.carpeta)
        self.ruta_reservas = escribir_reservas(
            os.path.join(self.tmp, "reservas.tsv"))
        self.reservas, _ = entrenamiento.leer_reservas([self.ruta_reservas])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def poblacion(self):
        return muestra.poblacion(self.ruta_capa, self.reservas)

    def ejecutar(self, n=20, salida="muestra", **kw):
        salida = os.path.join(self.tmp, salida)
        resumen = muestra.ejecutar(self.carpeta, self.ruta_reservas, n,
                                   salida, **kw)
        return salida, resumen


class PruebasPoblacion(Base):

    def test_cuenta_cada_exclusion_en_su_motivo(self):
        items, conteos = self.poblacion()
        self.assertEqual(conteos["oraciones_con_par_del_bronce"], 58)
        self.assertEqual(conteos["exclusiones"], {
            "pmid_reservado": 3, "oracion_reservada_igual": 1,
            "oracion_reservada_contenida": 2, "sin_par_directo": 1,
            "repetida": 1})
        self.assertEqual(conteos["poblacion"], 50)
        self.assertEqual(len(items), 50)

    def test_excluye_por_pmid(self):
        items, _ = self.poblacion()
        self.assertNotIn("90001", {i["pmid"] for i in items})

    def test_excluye_por_igualdad_con_espacios_normalizados(self):
        items, _ = self.poblacion()
        self.assertNotIn(RESERVADA_IGUAL, {i["normalizada"] for i in items})

    def test_excluye_por_contencion_de_40_o_mas(self):
        items, _ = self.poblacion()
        textos = [i["normalizada"] for i in items]
        self.assertFalse([t for t in textos if RESERVADA_CONTENIDA in t])
        self.assertNotIn(FRAGMENTO, textos)
        self.assertGreaterEqual(len(FRAGMENTO),
                                entrenamiento.MINIMO_CONTENCION)

    def test_una_reservada_corta_contenida_no_excluye(self):
        self.assertLess(len(RESERVADA_CORTA), entrenamiento.MINIMO_CONTENCION)
        items, _ = self.poblacion()
        self.assertTrue([i for i in items
                         if RESERVADA_CORTA in i["normalizada"]])

    def test_una_oracion_es_un_item_con_su_par_directo(self):
        items, _ = self.poblacion()
        claves = [(i["pmid"], i["fuente_texto"], i["num_oracion"])
                  for i in items]
        self.assertEqual(len(claves), len(set(claves)))
        self.assertTrue(all(i["id_par"].endswith("d") for i in items))

    def test_la_repetida_que_queda_es_la_primera_del_orden_estable(self):
        items, _ = self.poblacion()
        dup = [i for i in items if i["regulador"] == "dupR"]
        self.assertEqual([(d["fuente_texto"], d["num_oracion"]) for d in dup],
                         [("abstract", "1")])

    def test_sin_columnas_del_contrato_es_error(self):
        sin = [c for c in COLUMNAS_CAPA if c != "mencion_target"]
        escribir_capa(self.carpeta, columnas=sin)
        with self.assertRaises(ValueError) as e:
            self.poblacion()
        self.assertIn("mencion_target", str(e.exception))


class PruebasSorteo(Base):

    def test_la_misma_semilla_da_el_mismo_sorteo(self):
        items, _ = self.poblacion()
        uno = muestra.sortear(items, 10, semilla=7)
        dos = muestra.sortear(items, 10, semilla=7)
        self.assertEqual(
            [(m["id_item"], m["id_par"], m["tanda"], m["doble"]) for m in uno],
            [(m["id_item"], m["id_par"], m["tanda"], m["doble"]) for m in dos])

    def test_otra_semilla_da_otro_sorteo(self):
        items, _ = self.poblacion()
        uno = muestra.sortear(items, 10, semilla=7)
        otro = muestra.sortear(items, 10, semilla=8)
        self.assertNotEqual({m["id_par"] for m in uno},
                            {m["id_par"] for m in otro})

    def test_el_orden_de_llegada_no_cambia_el_sorteo(self):
        items, _ = self.poblacion()
        filas = filas_sinteticas()
        escribir_capa(self.carpeta, list(reversed(filas)))
        al_reves, _ = self.poblacion()
        self.assertEqual(
            [m["id_par"] for m in muestra.sortear(items, 10, semilla=7)],
            [m["id_par"] for m in muestra.sortear(al_reves, 10, semilla=7)])

    def test_un_tamano_mayor_que_la_poblacion_es_error(self):
        items, _ = self.poblacion()
        with self.assertRaises(ValueError) as e:
            muestra.sortear(items, 51)
        self.assertIn("51", str(e.exception))
        self.assertIn("50", str(e.exception))

    def test_un_tamano_mayor_no_escribe_nada(self):
        salida = os.path.join(self.tmp, "nada")
        with self.assertRaises(ValueError):
            muestra.ejecutar(self.carpeta, self.ruta_reservas, 51, salida)
        self.assertFalse(os.path.exists(salida))

    def test_la_parte_doble_tiene_la_fraccion_pedida(self):
        items, _ = self.poblacion()
        for fraccion, por_tanda in ((0.25, 5), (0.1, 2), (0.0, 0), (1.0, 20)):
            sorteo = muestra.sortear(items, 40, fraccion_doble=fraccion)
            for tanda in (1, 2):
                de_la_tanda = [m for m in sorteo if m["tanda"] == tanda]
                self.assertEqual(len(de_la_tanda), 20)
                self.assertEqual(sum(m["doble"] for m in de_la_tanda),
                                 por_tanda, (fraccion, tanda))

    def test_cambiar_la_fraccion_no_cambia_las_oraciones(self):
        items, _ = self.poblacion()
        uno = muestra.sortear(items, 20, fraccion_doble=0.25)
        otro = muestra.sortear(items, 20, fraccion_doble=0.5)
        self.assertEqual([(m["id_item"], m["id_par"]) for m in uno],
                         [(m["id_item"], m["id_par"]) for m in otro])

    def test_una_fraccion_fuera_de_rango_es_error(self):
        items, _ = self.poblacion()
        with self.assertRaises(ValueError):
            muestra.sortear(items, 10, fraccion_doble=1.5)

    def test_los_codigos_son_opacos_y_unicos(self):
        items, _ = self.poblacion()
        sorteo = muestra.sortear(items, 40)
        codigos = [m["id_item"] for m in sorteo]
        self.assertEqual(len(set(codigos)), 40)
        self.assertTrue(all(re.match(r"^m-\d{4}$", c) for c in codigos))
        self.assertFalse([c for c in codigos if c[2:] in
                          {m["pmid"] for m in sorteo}])
        # Al azar, no consecutivos: un consecutivo diría el orden del sorteo.
        self.assertNotEqual(sorted(codigos),
                            ["m-%04d" % i for i in range(1000, 1040)])


class PruebasEntidades(Base):

    def item(self, regulador_primero):
        items, _ = self.poblacion()
        i = 0 if regulador_primero else 1
        return [m for m in items if m["regulador"] == "reg%dR" % i][0]

    def test_la_entidad_1_es_la_que_aparece_primero(self):
        e1, e2, direccion = muestra.entidades(self.item(True))
        self.assertEqual((e1, e2, direccion), ("Reg0R", "tgt0Z", "1>2"))

    def test_el_orden_no_es_el_del_bronce(self):
        # El regulador del bronce va segundo en la oración: la hoja no lo
        # pone primero, y la llave dice 2>1.
        e1, e2, direccion = muestra.entidades(self.item(False))
        self.assertEqual((e1, e2, direccion), ("tgt1Z", "Reg1R", "2>1"))

    def test_el_orden_no_es_el_alfabetico(self):
        # §6: la que aparece primero, aunque el alfabeto diga otra cosa.
        e1, e2, _ = muestra.entidades(self.item(False))
        self.assertGreater(e1.casefold(), e2.casefold())

    def test_se_escriben_como_en_la_oracion(self):
        item = self.item(True)
        e1, _, _ = muestra.entidades(item)
        self.assertEqual(item["regulador"], "reg0R")
        self.assertEqual(e1, "Reg0R")
        self.assertIn(e1, item["oracion"])

    def test_cuenta_la_palabra_entera_y_no_el_prefijo(self):
        item = {"oracion": "Both lasRI and rhlR, and then lasR, were tested.",
                "mencion_regulador": "lasR", "mencion_blanco": "rhlR"}
        self.assertEqual(muestra.entidades(item), ("rhlR", "lasR", "2>1"))


class PruebasSalidas(Base):

    def test_la_hoja_lleva_exactamente_las_columnas_de_la_rubrica(self):
        rubrica = columnas_de_la_rubrica()
        self.assertEqual(rubrica, [
            "id_item", "oracion", "entidad_1", "entidad_2", "relacion",
            "direccion", "signo", "tipo", "negada", "especulativa",
            "comentario"])
        self.assertEqual(muestra.COLUMNAS_HOJA, rubrica)
        salida, _ = self.ejecutar()
        for nombre in (muestra.HOJA_TANDA1, muestra.HOJA_TANDA2):
            columnas, filas = leer_csv(os.path.join(salida, nombre))
            self.assertEqual(columnas, rubrica)
            self.assertEqual(len(filas), 10)
            for fila in filas:
                for c in rubrica[4:]:
                    self.assertEqual(fila[c], "", (nombre, c))

    def test_la_hoja_no_lleva_predicciones_ni_nada_del_bronce(self):
        salida, _ = self.ejecutar(n=50)
        for nombre in (muestra.HOJA_TANDA1, muestra.HOJA_TANDA2):
            with io.open(os.path.join(salida, nombre),
                         encoding="utf-8-sig") as f:
                texto = f.read()
            for columna, valor in CENTINELAS.items():
                self.assertNotIn(valor, texto, (nombre, columna))
            for pmid in range(90001, 90025):
                self.assertNotIn(str(pmid), texto)
            for marca in ("1>2", "2>1", "PA9", "directo"):
                self.assertNotIn(marca, texto)

    def test_la_llave_une_cada_item(self):
        salida, _ = self.ejecutar()
        _, hoja1 = leer_csv(os.path.join(salida, muestra.HOJA_TANDA1))
        _, hoja2 = leer_csv(os.path.join(salida, muestra.HOJA_TANDA2))
        columnas, llave = leer_csv(os.path.join(salida, muestra.LLAVE))
        self.assertEqual(columnas, muestra.COLUMNAS_LLAVE)
        en_hoja = dict((f["id_item"], (1, f)) for f in hoja1)
        en_hoja.update((f["id_item"], (2, f)) for f in hoja2)
        self.assertEqual(len(en_hoja), len(hoja1) + len(hoja2))
        self.assertEqual(set(en_hoja), {f["id_item"] for f in llave})
        self.assertEqual(len(llave), 20)
        capa = dict((f["id_par"], f) for f in filas_sinteticas())
        for fila in llave:
            tanda, de_la_hoja = en_hoja[fila["id_item"]]
            self.assertEqual(int(fila["tanda"]), tanda)
            par = capa[fila["id_par"]]
            self.assertEqual(par["par_del_bronce"], "directo")
            self.assertEqual(
                (fila["pmid"], fila["fuente_texto"], fila["num_oracion"]),
                (par["pmid"], par["fuente_texto"], par["num_oracion"]))
            self.assertEqual(de_la_hoja["oracion"], par["oracion"])
            self.assertEqual((fila["regulador"], fila["blanco"]),
                             (par["regulador_candidato"],
                              par["blanco_candidato"]))
            primero = (par["mencion_tf"] if fila["direccion_bronce"] == "1>2"
                       else par["mencion_target"])
            self.assertEqual(de_la_hoja["entidad_1"], primero)
            self.assertIn(fila["doble"], ("si", "no"))

    def test_los_dobles_van_sin_la_orientacion_del_bronce(self):
        salida, _ = self.ejecutar()
        columnas, dobles = leer_csv(os.path.join(salida, muestra.DOBLES))
        self.assertEqual(columnas, ["id_item", "tanda"])
        _, llave = leer_csv(os.path.join(salida, muestra.LLAVE))
        self.assertEqual(
            sorted((f["id_item"], f["tanda"]) for f in dobles),
            sorted((f["id_item"], f["tanda"]) for f in llave
                   if f["doble"] == "si"))
        self.assertEqual(len(dobles), 6)
        with io.open(os.path.join(salida, muestra.DOBLES),
                     encoding="utf-8-sig") as f:
            texto = f.read()
        for marca in ("1>2", "2>1", "PA9", "9000"):
            self.assertNotIn(marca, texto)

    def test_los_csv_llevan_bom(self):
        salida, _ = self.ejecutar()
        for nombre in (muestra.HOJA_TANDA1, muestra.HOJA_TANDA2,
                       muestra.LLAVE, muestra.DOBLES):
            with open(os.path.join(salida, nombre), "rb") as f:
                self.assertEqual(f.read(3), codecs.BOM_UTF8, nombre)

    def test_el_resumen(self):
        salida, devuelto = self.ejecutar(semilla=99)
        with io.open(os.path.join(salida, muestra.RESUMEN),
                     encoding="utf-8") as f:
            resumen = json.load(f)
        self.assertEqual(resumen, devuelto)
        self.assertEqual(resumen["semilla"], 99)
        self.assertEqual(resumen["n"], 20)
        self.assertEqual(resumen["poblacion"], 50)
        self.assertEqual(resumen["oraciones_con_par_del_bronce"], 58)
        self.assertEqual(sum(resumen["exclusiones"].values()), 8)
        self.assertEqual(resumen["dobles"], 6)  # round(0.25 * 10) en cada una
        self.assertEqual(resumen["entradas"], {
            "capa_pares.csv": procedencia.huella(self.ruta_capa),
            "reservas": procedencia.huella(self.ruta_reservas)})
        self.assertTrue(all(re.match(r"^[0-9a-f]{16}$", h)
                            for h in resumen["entradas"].values()))
        texto = json.dumps(resumen)
        self.assertNotIn("90002", texto)
        self.assertNotIn("sample", texto)

    def test_la_misma_corrida_da_los_mismos_bytes(self):
        uno, _ = self.ejecutar(salida="uno")
        dos, _ = self.ejecutar(salida="dos")
        for nombre in (muestra.HOJA_TANDA1, muestra.HOJA_TANDA2,
                       muestra.LLAVE, muestra.DOBLES, muestra.RESUMEN):
            with open(os.path.join(uno, nombre), "rb") as a, \
                    open(os.path.join(dos, nombre), "rb") as b:
                self.assertEqual(a.read(), b.read(), nombre)

    def test_no_sobrescribe_otro_sorteo(self):
        salida, _ = self.ejecutar(semilla=1)
        ruta = os.path.join(salida, muestra.HOJA_TANDA1)
        with open(ruta, "rb") as f:
            antes = f.read()
        self.ejecutar(semilla=1)  # el mismo sorteo sí se repite
        with self.assertRaises(ValueError):
            self.ejecutar(semilla=2)
        with self.assertRaises(ValueError):
            self.ejecutar(n=10, semilla=1)
        with open(ruta, "rb") as f:
            self.assertEqual(f.read(), antes)


class PruebasUnaTanda(Base):
    """La muestra única del servicio social: un anotador, una hoja, sin
    parte doble y sin tanda que barajar con candidatas nuevas."""

    def test_todo_va_a_la_tanda_1_y_no_hay_segunda_hoja(self):
        salida, resumen = self.ejecutar(n=20, tandas=1, fraccion_doble=0)

        self.assertEqual(resumen["num_tandas"], 1)
        self.assertEqual(resumen["tandas"], {"1": {"items": 20, "dobles": 0}})
        self.assertFalse(os.path.exists(
            os.path.join(salida, muestra.HOJA_TANDA2)))
        self.assertNotIn(muestra.HOJA_TANDA2, resumen["salidas"])
        with io.open(os.path.join(salida, muestra.HOJA_TANDA1),
                     encoding="utf-8-sig", newline="") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 20)

    def test_sin_dobles_la_lista_de_dobles_va_vacia(self):
        salida, resumen = self.ejecutar(n=20, tandas=1, fraccion_doble=0)

        self.assertEqual(resumen["dobles"], 0)
        with io.open(os.path.join(salida, muestra.DOBLES),
                     encoding="utf-8-sig", newline="") as f:
            self.assertEqual(list(csv.DictReader(f)), [])

    def test_una_tanda_sortea_las_mismas_oraciones_que_dos(self):
        """Las tandas solo reparten: el sorteo es el mismo."""
        _, una = self.ejecutar(n=20, salida="una", tandas=1)
        _, dos = self.ejecutar(n=20, salida="dos")
        ids = lambda s: sorted(
            m["id_item"] for m in muestra.sortear(
                self.poblacion()[0], 20,
                tandas=1 if s == "una" else 2))
        self.assertEqual(ids("una"), ids("dos"))
        self.assertEqual(una["poblacion"], dos["poblacion"])

    def test_no_se_mezcla_con_un_sorteo_de_dos_tandas(self):
        self.ejecutar(n=20, salida="misma")
        with self.assertRaises(ValueError):
            self.ejecutar(n=20, salida="misma", tandas=1)

    def test_tandas_fuera_de_1_o_2_es_error(self):
        with self.assertRaises(ValueError):
            muestra.sortear(self.poblacion()[0], 20, tandas=3)


class PruebasCli(Base):

    def main(self, argv):
        lineas = []
        with mock.patch.object(cli, "log", lineas.append):
            codigo = cli.main(argv)
        return codigo, lineas

    def argumentos(self, n, salida="por_cli"):
        return ["muestra", "--carpeta", self.carpeta,
                "--reservas", self.ruta_reservas, "--n", str(n),
                "--salida", os.path.join(self.tmp, salida)]

    def test_sortea_y_solo_dice_conteos(self):
        codigo, lineas = self.main(self.argumentos(20) + ["--semilla", "5"])
        self.assertEqual(codigo, 0)
        dicho = "\n".join(lineas)
        self.assertIn("50", dicho)
        self.assertIn("semilla 5", dicho)
        for fila in filas_sinteticas():
            self.assertNotIn(fila["oracion"][:25], dicho)
        with io.open(os.path.join(self.tmp, "por_cli", muestra.RESUMEN),
                     encoding="utf-8") as f:
            self.assertEqual(json.load(f)["semilla"], 5)

    def test_la_fraccion_doble_llega(self):
        codigo, _ = self.main(self.argumentos(20)
                              + ["--fraccion-doble", "0.5"])
        self.assertEqual(codigo, 0)
        with io.open(os.path.join(self.tmp, "por_cli", muestra.RESUMEN),
                     encoding="utf-8") as f:
            self.assertEqual(json.load(f)["dobles"], 10)

    def test_un_tamano_mayor_sale_con_1(self):
        codigo, lineas = self.main(self.argumentos(51))
        self.assertEqual(codigo, 1)
        self.assertTrue(lineas[-1].startswith("ERROR"))
        self.assertIn("no se sortea", lineas[-1])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "por_cli")))

    def test_sin_capa_sale_con_1(self):
        os.remove(self.ruta_capa)
        codigo, lineas = self.main(self.argumentos(5))
        self.assertEqual(codigo, 1)
        self.assertIn("capa_pares.csv", lineas[-1])


def _capa_real():
    """La `capa_pares.csv` de la corrida 4, en el checkout o, desde un
    worktree de `.claude/worktrees/`, en el checkout que lo contiene:
    `salidas/` está ignorada y el worktree no la trae."""
    relativa = os.path.join("salidas", "flujo", "corrida4_run22",
                            "capa_pares.csv")
    raices = [RAIZ]
    if os.path.basename(os.path.dirname(RAIZ)) == "worktrees":
        raices.append(os.path.dirname(os.path.dirname(os.path.dirname(RAIZ))))
    for raiz in raices:
        ruta = os.path.join(raiz, relativa)
        if os.path.isfile(ruta):
            return ruta
    return None


CAPA_REAL = _capa_real()


@unittest.skipUnless(CAPA_REAL, "no está la capa_pares.csv de la corrida 4")
class PruebaDeHumo(unittest.TestCase):

    def test_la_capa_real_trae_las_columnas_que_se_leen(self):
        # Solo la cabecera: ni una oración del corpus pasa por la prueba.
        with io.open(CAPA_REAL, encoding="utf-8-sig", newline="") as f:
            cabecera = next(csv.reader(f))
        faltan = [c for c in muestra.COLUMNAS_CAPA if c not in cabecera]
        self.assertEqual(faltan, [])


if __name__ == "__main__":
    unittest.main()
