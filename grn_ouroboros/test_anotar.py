"""La corrida con un anotador falso: la caché, la abstención, el fragmento y
las salidas. Ni Strands ni Ollama: el falso devuelve texto fijo y cuenta sus
llamadas. Las oraciones son inventadas.

    python -m unittest grn_ouroboros.test_anotar
"""

import collections
import csv
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from grn_ouroboros import agente, anotar, herramientas, rubrica

ORACIONES = {
    "m-1001": ("GenX activates genY in this invented sentence.", "GenX",
               "genY"),
    "m-1002": ("No effect of GenQ on genR was seen here.", "GenQ", "genR"),
    "m-1003": ("GenS represses genT, we say on purpose.", "GenS", "genT"),
}

DESCRIPCION = {"modelo": "qwen3:8b", "digest": "500a1f067a9f" + "0" * 52,
               "cuantizacion": "Q4_K_M", "huella_template": "t" * 64,
               "ollama": "0.12.6"}
DECODIFICACION = {"think": False, "temperature": 0.0, "top_p": None,
                  "top_k": None, "seed": 42, "num_ctx": 4096,
                  "num_predict": 512, "format": "esquema"}


def _json(fragmento, **cambios):
    r = {"fragmento": fragmento, "motivo": "Lo dice la oración.",
         "relacion": "si", "direccion": "1>2", "signo": "+", "tipo": "no_se",
         "negada": "no", "especulativa": "no", "comentario": ""}
    r.update(cambios)
    return json.dumps(r)


def _entradas(**cambios):
    e = anotar.armar_entradas(DESCRIPCION, dict(DECODIFICACION), "p" * 64,
                              "ninguna", {})
    e.update(cambios)
    return e


class AnotadorFalso(object):
    """Contesta por `id_item` y anota con qué la llamaron."""

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.llamadas = []

    def __call__(self, item):
        self.llamadas.append(dict(item))
        r = self.respuestas[item["id_item"]]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, str):
            return {"texto": r, "done_reason": "stop", "truncado": False}
        return r


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hoja = os.path.join(self.tmp, "hoja.csv")
        with io.open(self.hoja, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rubrica.COLUMNAS_HOJA)
            w.writeheader()
            for id_item, (oracion, e1, e2) in ORACIONES.items():
                w.writerow({"id_item": id_item, "oracion": oracion,
                            "entidad_1": e1, "entidad_2": e2})
        self.salida = os.path.join(self.tmp, "salida")
        self.respuestas = {
            "m-1001": _json("GenX activates genY"),
            "m-1002": _json("No effect of GenQ on genR", relacion="no",
                            direccion="ninguna", signo="", tipo="",
                            negada="si"),
            "m-1003": _json("GenS represses genT", signo="-"),
        }

    def correr(self, respuestas=None, entradas=None, salida=None):
        falso = AnotadorFalso(respuestas or self.respuestas)
        reloj = iter(float(i) for i in range(1000))
        r = anotar.ejecutar(self.hoja, salida or self.salida, falso,
                            entradas or _entradas(),
                            configuracion={"nombre": "principal"},
                            descripcion=DESCRIPCION,
                            reloj=lambda: next(reloj))
        return r, falso

    def leer(self, nombre):
        with io.open(os.path.join(self.salida, nombre), "rb") as f:
            return f.read()


class PruebasCache(Base):

    def test_la_segunda_corrida_no_vuelve_a_llamar(self):
        _r, primero = self.correr()
        self.assertEqual(len(primero.llamadas), 3)
        r, segundo = self.correr()
        self.assertEqual(segundo.llamadas, [])
        self.assertEqual(r["resumen"]["reutilizadas"], 3)
        self.assertEqual(r["resumen"]["nuevas"], 0)
        self.assertEqual(r["resultados"]["m-1001"]["valores"]["relacion"],
                         "si")

    def test_veredictos_es_de_solo_anexar(self):
        self.correr()
        lineas = self.leer(anotar.VEREDICTOS).splitlines()
        self.correr()
        self.assertEqual(self.leer(anotar.VEREDICTOS).splitlines(), lineas)
        self.assertEqual(len(lineas), 3)

    def test_una_corrida_cortada_retoma_lo_que_falta(self):
        cortada = dict(self.respuestas, **{"m-1003": RuntimeError("caído")})
        with self.assertRaises(RuntimeError):
            self.correr(cortada)
        corrida = json.loads(self.leer(anotar.CORRIDA).decode("utf-8"))
        self.assertEqual(corrida["estatus"], "error")
        self.assertEqual(corrida["error"], "RuntimeError")
        _r, falso = self.correr()
        self.assertEqual([it["id_item"] for it in falso.llamadas], ["m-1003"])

    def test_una_linea_cortada_se_salta(self):
        self.correr()
        with open(os.path.join(self.salida, anotar.VEREDICTOS), "ab") as f:
            f.write(b'{"llave": "abc", "val')
        _r, falso = self.correr()
        self.assertEqual(falso.llamadas, [])
        anotar.anexar(os.path.join(self.salida, anotar.VEREDICTOS),
                      {"llave": "x", "valor": {}})
        self.assertIn("x", anotar.leer_veredictos(
            os.path.join(self.salida, anotar.VEREDICTOS)))

    def test_otra_configuracion_no_reusa_la_carpeta(self):
        self.correr()
        otra = _entradas(decodificacion=dict(DECODIFICACION, seed=43))
        with self.assertRaises(ValueError):
            self.correr(entradas=otra)

    def test_otra_carpeta_con_otra_semilla_vuelve_a_llamar(self):
        self.correr()
        otra = _entradas(decodificacion=dict(DECODIFICACION, seed=43))
        _r, falso = self.correr(entradas=otra,
                                salida=os.path.join(self.tmp, "otra"))
        self.assertEqual(len(falso.llamadas), 3)


class PruebasLlave(unittest.TestCase):

    item = {"id_item": "m-1", "oracion": "GenX activates genY.",
            "entidad_1": "GenX", "entidad_2": "genY"}

    def test_cambia_con_cada_entrada(self):
        base = anotar.llave_cache(self.item, _entradas())
        cambios = [
            {"prompt": "q" * 64},
            {"modelo": dict(_entradas()["modelo"], digest="1" * 64)},
            {"modelo": dict(_entradas()["modelo"], cuantizacion="Q8_0")},
            {"ollama": "0.12.7"},
            {"decodificacion": dict(DECODIFICACION, num_predict=513)},
            {"esquema": {"version": 2, "huella": "e"}},
            {"herramientas": "buscar_locus"},
            {"recursos": {"genes_pao1.tsv": "abc"}},
        ]
        llaves = [anotar.llave_cache(self.item, _entradas(**c))
                  for c in cambios]
        self.assertNotIn(base, llaves)
        self.assertEqual(len(set(llaves)), len(llaves))
        self.assertNotEqual(
            anotar.llave_cache(dict(self.item, entidad_2="GenX"),
                               _entradas()), base)

    def test_el_id_solo_entra_con_contexto(self):
        otro = dict(self.item, id_item="m-2")
        self.assertEqual(anotar.llave_cache(self.item, _entradas()),
                         anotar.llave_cache(otro, _entradas()))
        todas = _entradas(herramientas="todas")
        self.assertNotEqual(anotar.llave_cache(self.item, todas),
                            anotar.llave_cache(otro, todas))

    def test_faltan_entradas(self):
        incompletas = _entradas()
        del incompletas["ollama"]
        with self.assertRaises(ValueError):
            anotar.llave_cache(self.item, incompletas)


class PruebasOtraConfiguracionNoReusa(Base):
    """Las entradas armadas como las arma el CLI, con `agente` y
    `herramientas` de verdad. Las de `PruebasLlave` se cambian a mano después
    de armarlas, y así no ven si `decodificacion`, `huella_prompt` o
    `armar_entradas` dejan algo fuera: un prompt reescrito o un digest con el
    mismo prefijo reusarían los veredictos viejos sin que nada fallara."""

    PROMPT = "Prompt inventado para la prueba: responde con el JSON."

    def entradas(self, config=None, prompt=PROMPT, herr="ninguna",
                 descripcion=DESCRIPCION):
        config = config or agente.configuracion("principal")
        return anotar.armar_entradas(
            descripcion, agente.decodificacion(config, herr),
            agente.huella_prompt(prompt, herr), herr,
            herramientas.Recursos().huellas(herr))

    def variantes(self):
        """Un cambio a la vez, también los que el CLI no ofrece (think o la
        temperatura solos): cada uno decide lo que genera el modelo."""
        principal = agente.configuracion("principal")
        return {
            "semilla": self.entradas(
                agente.configuracion("principal", semilla=43)),
            "think": self.entradas(dict(principal, think=True)),
            "temperatura": self.entradas(dict(principal, temperature=0.1)),
            "num_ctx": self.entradas(
                agente.configuracion("principal", num_ctx=8192)),
            "cache_kv": self.entradas(
                agente.configuracion("principal", kv_cache="q8_0")),
            "con_think": self.entradas(agente.configuracion("con_think")),
            "prompt": self.entradas(prompt=self.PROMPT + " Sin más."),
            "herramientas": self.entradas(herr="buscar_locus"),
            "digest": self.entradas(descripcion=dict(
                DESCRIPCION, digest="500a1f067a9f" + "1" * 52)),
        }

    def test_cada_cambio_da_otra_llave(self):
        item = PruebasLlave.item
        base = anotar.llave_cache(item, self.entradas())
        llaves = dict((nombre, anotar.llave_cache(item, e))
                      for nombre, e in self.variantes().items())
        for nombre, llave in llaves.items():
            self.assertNotEqual(llave, base, nombre)
        self.assertEqual(len(set(llaves.values())), len(llaves))

    def test_la_decodificacion_lleva_toda_la_configuracion(self):
        for nombre in agente.CONFIGURACIONES:
            config = agente.configuracion(nombre)
            for herr in herramientas.OPCIONES:
                d = agente.decodificacion(config, herr)
                self.assertEqual(dict((c, d[c]) for c in config), config)

    def test_en_la_misma_carpeta_vuelve_a_llamar(self):
        """Sin corrida.json, la guarda de la carpeta no tapa a la llave: lo
        que se mide aquí es la caché."""
        corrida = os.path.join(self.salida, anotar.CORRIDA)
        _r, falso = self.correr(entradas=self.entradas())
        self.assertEqual(len(falso.llamadas), 3)
        for nombre, entradas in self.variantes().items():
            os.remove(corrida)
            _r, falso = self.correr(entradas=entradas)
            self.assertEqual(len(falso.llamadas), 3, nombre)
        # Con las entradas de la primera, la caché sí sirve.
        os.remove(corrida)
        _r, falso = self.correr(entradas=self.entradas())
        self.assertEqual(falso.llamadas, [])


class PruebasAbstencion(Base):

    def un_item(self, respuesta, salida=None):
        r, _ = self.correr(dict(self.respuestas, **{"m-1001": respuesta}),
                           salida=salida)
        return r["resultados"]["m-1001"], r

    def test_json_invalido(self):
        valor, r = self.un_item("La relación es sí, sin duda.")
        self.assertTrue(valor["abstencion"])
        self.assertEqual(valor["motivo_abstencion"], "json_invalido")
        self.assertEqual(r["resumen"]["conteos"]["abstenciones"], 1)

    def test_truncado_aunque_parezca_completo(self):
        valor, r = self.un_item({"texto": _json("GenX activates genY"),
                                 "done_reason": "length", "truncado": True})
        self.assertEqual(valor["motivo_abstencion"], "truncado")
        self.assertEqual(valor["done_reason"], "length")
        self.assertEqual(
            r["resumen"]["conteos"]["abstenciones_por_motivo"],
            {"truncado": 1})

    def test_un_campo_que_falta(self):
        incompleto = json.loads(_json("GenX activates genY"))
        del incompleto["tipo"]
        valor, _ = self.un_item(json.dumps(incompleto))
        self.assertEqual(valor["motivo_abstencion"], "esquema")

    def test_la_rubrica_rechaza_si_con_negada(self):
        valor, _ = self.un_item(_json("GenX activates genY", negada="si"))
        self.assertEqual(valor["motivo_abstencion"], "rubrica")
        self.assertTrue(valor["errores"])

    def test_un_motivo_del_anotador(self):
        valor, _ = self.un_item({"texto": "", "done_reason": None,
                                 "truncado": False,
                                 "motivo_abstencion": "limite_turnos"})
        self.assertEqual(valor["motivo_abstencion"], "limite_turnos")

    def test_el_razonamiento_se_quita_antes_de_leer(self):
        valor, _ = self.un_item(
            "<think>Pienso que {sí}.</think>\n" + _json("GenX activates genY"))
        self.assertFalse(valor["abstencion"])
        # En otra carpeta: en la misma, la caché devolvería el de arriba.
        valor, _ = self.un_item("<think>Me quedé sin cerrar "
                                + _json("GenX activates genY"),
                                salida=os.path.join(self.tmp, "otra"))
        self.assertEqual(valor["motivo_abstencion"], "json_invalido")

    def test_la_abstencion_sale_vacia_en_la_hoja(self):
        self.un_item("nada")
        with io.open(os.path.join(self.salida, anotar.ANOTACIONES),
                     encoding="utf-8-sig", newline="") as f:
            filas = dict((fila["id_item"], fila) for fila in csv.DictReader(f))
        self.assertEqual([filas["m-1001"][c] for c in
                          rubrica.COLUMNAS_VALORES], [""] * 7)
        self.assertEqual(filas["m-1001"]["oracion"], ORACIONES["m-1001"][0])
        self.assertEqual(filas["m-1003"]["signo"], "-")


class PruebasFragmento(Base):

    def test_literal_con_sus_offsets(self):
        r, _ = self.correr()
        valor = r["resultados"]["m-1001"]
        self.assertEqual(valor["evidencia_invalida"], "no")
        ini, fin = valor["fragmento_offsets"]
        self.assertEqual(ORACIONES["m-1001"][0][ini:fin],
                         "GenX activates genY")

    def test_uno_que_no_esta_se_marca_y_no_se_borra(self):
        r, _ = self.correr(dict(self.respuestas, **{
            "m-1001": _json("GenX ACTIVATES genY")}))
        valor = r["resultados"]["m-1001"]
        self.assertFalse(valor["abstencion"])
        self.assertEqual(valor["evidencia_invalida"], "si")
        self.assertIsNone(valor["fragmento_offsets"])
        self.assertEqual(valor["valores"]["relacion"], "si")
        self.assertEqual(r["resumen"]["conteos"]["fragmentos_invalidos"], 1)

    def test_vacio_es_invalido(self):
        self.assertIsNone(anotar.ubicar_fragmento("abc", "  "))
        self.assertEqual(anotar.ubicar_fragmento("a bc", " bc "), [2, 4])


class PruebasSalidas(Base):

    def test_la_hoja_tiene_exactamente_las_columnas_y_bom(self):
        self.correr()
        crudo = self.leer(anotar.ANOTACIONES)
        self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))
        primera = crudo[3:].split(b"\r\n", 1)[0].decode("utf-8")
        self.assertEqual(primera.split(","), rubrica.COLUMNAS_HOJA)

    def test_la_lee_el_lector_de_la_precision_ciega(self):
        from grn_verificacion import precision_ciega
        self.correr()
        filas = precision_ciega.leer_anotacion(
            os.path.join(self.salida, anotar.ANOTACIONES))
        self.assertEqual(sorted(filas), sorted(ORACIONES))
        self.assertEqual(filas["m-1002"]["negada"], "si")

    def test_el_truncado_y_el_json_invalido_son_error_en_concordancia(self):
        """De punta a punta, contra un experto que anota justo lo que el
        modelo diría sin abstenerse: las dos abstenciones salen vacías en la
        hoja y `concordancia` las cuenta como error en todos los campos.

        kappa en relación, a mano: experto (si, no, si), modelo (abstención,
        abstención, si). p_o = 1/3; p_e = (2/3)(1/3) + (1/3)(0) = 2/9;
        kappa = (1/3 - 2/9) / (1 - 2/9) = 1/7.
        """
        from grn_verificacion import concordancia
        truncada = {"texto": self.respuestas["m-1001"],
                    "done_reason": "length", "truncado": True}
        self.correr(dict(self.respuestas, **{
            "m-1001": truncada, "m-1002": "La relación es no."}))
        experto = os.path.join(self.tmp, "experto.csv")
        with io.open(experto, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rubrica.COLUMNAS_HOJA)
            w.writeheader()
            for id_item, (oracion, e1, e2) in ORACIONES.items():
                juicio = json.loads(self.respuestas[id_item])
                fila = dict((c, juicio[c]) for c in rubrica.COLUMNAS_VALORES)
                fila.update(id_item=id_item, oracion=oracion, entidad_1=e1,
                            entidad_2=e2)
                w.writerow(fila)
        r = concordancia.calcular(
            experto, os.path.join(self.salida, anotar.ANOTACIONES))
        self.assertEqual(r["abstenciones_del_modelo"]["k"], 2)
        for campo, p in r["acuerdo_por_campo"].items():
            self.assertEqual((p["k"], p["n"]), (1, 3), campo)
        self.assertAlmostEqual(r["kappa_relacion"], 1 / 7.0, places=3)
        relacion = r["matrices"]["relacion"]
        self.assertEqual((relacion["si"][concordancia.ABSTENCION],
                          relacion["no"][concordancia.ABSTENCION]), (1, 1))

    def test_corrida_json_trae_conteos_y_ninguna_oracion(self):
        self.correr()
        texto = self.leer(anotar.CORRIDA).decode("utf-8")
        corrida = json.loads(texto)
        self.assertEqual(corrida["estatus"], "ok")
        self.assertEqual(corrida["conteos"]["validas"], 3)
        self.assertEqual(corrida["conteos"]["segundos_totales"], 3.0)
        self.assertIn("python", corrida["versiones"])
        self.assertIn("strands-agents", corrida["versiones"])
        self.assertEqual(corrida["identidad"]["entradas"]["modelo"][
            "cuantizacion"], "Q4_K_M")
        for oracion, _e1, _e2 in ORACIONES.values():
            self.assertNotIn(oracion, texto)

    def test_el_anotador_solo_recibe_el_item(self):
        _r, falso = self.correr()
        self.assertEqual(sorted(falso.llamadas[0]),
                         ["entidad_1", "entidad_2", "id_item", "oracion"])


def _enlazar(destino, enlace):
    """Un enlace de carpeta: simbólico donde se puede y, en un Windows sin
    permiso para eso, una unión (junction), que `realpath` también resuelve.
    False si no se pudo ninguno."""
    try:
        os.symlink(destino, enlace, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(destino, enlace)
            return True
        except (ImportError, AttributeError, OSError):
            pass
    return False


class PruebasCarpetaDelExperto(Base):
    """Las salidas nunca caen en salidas/revision, y nada se crea antes de
    rechazarla."""

    def test_ni_por_un_enlace(self):
        """`salidas` como enlace a una carpeta con otro nombre (la ruta
        resuelta ya no dice salidas/revision) y un atajo a la carpeta del
        experto (la ruta escrita no lo dice)."""
        almacen = os.path.join(self.tmp, "almacen")
        os.makedirs(os.path.join(almacen, "revision"))
        proyecto = os.path.join(self.tmp, "proyecto")
        del_experto = os.path.join(proyecto, "otra", "salidas", "revision")
        os.makedirs(del_experto)
        for destino, enlace in ((almacen, os.path.join(proyecto, "salidas")),
                                (del_experto,
                                 os.path.join(proyecto, "atajo"))):
            if not _enlazar(destino, enlace):
                self.skipTest("este sistema no deja crear enlaces de "
                              "carpeta")
            # Se quita el enlace y no lo que apunta: rmdir en Windows (unión
            # o enlace simbólico de carpeta), unlink en los demás.
            self.addCleanup(os.rmdir if os.name == "nt" else os.unlink,
                            enlace)
        for partes in (("salidas", "revision", "t1"), ("atajo", "t1")):
            with self.assertRaises(ValueError, msg="/".join(partes)):
                anotar.validar_salida(os.path.join(proyecto, *partes))

    def test_rechaza_la_carpeta_y_lo_que_cuelga_de_ella(self):
        for partes in (("salidas", "revision"),
                       ("salidas", "revision", "muestra200", "ouro"),
                       ("salidas", "ouroboros", "..", "revision", "t1")):
            ruta = os.path.join(self.tmp, *partes)
            with self.assertRaises(ValueError) as caja:
                anotar.validar_salida(ruta)
            self.assertIn("salidas/ouroboros/", str(caja.exception))

    def test_la_del_repositorio_tambien(self):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(
            anotar.__file__)))
        with self.assertRaises(ValueError):
            anotar.validar_salida(os.path.join(raiz, "salidas", "revision",
                                               "muestra200", "x"))

    @unittest.skipUnless(os.name == "nt", "solo Windows no distingue "
                                          "mayúsculas en las rutas")
    def test_sin_distinguir_mayusculas_en_windows(self):
        with self.assertRaises(ValueError):
            anotar.validar_salida(os.path.join(self.tmp, "SALIDAS",
                                               "Revision", "x"))

    def test_lo_demas_pasa(self):
        for partes in (("salidas", "ouroboros", "t1"),
                       ("salidas", "revision2"), ("revision", "salidas")):
            ruta = os.path.join(self.tmp, *partes)
            self.assertEqual(anotar.validar_salida(ruta),
                             os.path.realpath(ruta))

    def test_ejecutar_no_escribe_ahi(self):
        prohibida = os.path.join(self.tmp, "salidas", "revision", "t1")
        with self.assertRaises(ValueError):
            self.correr(salida=prohibida)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "salidas")))


class PruebasLeerCorrida(Base):

    def test_los_mismos_items_y_veredictos_sin_llamar(self):
        r, _ = self.correr()
        leida = anotar.leer_corrida(self.salida)
        self.assertEqual(leida["items"], r["items"])
        self.assertEqual(leida["resultados"], r["resultados"])
        self.assertEqual(leida["resumen"]["estatus"], "ok")

    def test_dos_items_que_comparten_llave(self):
        """El segundo sale de la caché y no tiene línea propia en el
        JSONL: se busca por la llave, no por el id_item."""
        with io.open(self.hoja, "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(["m-1004", ORACIONES["m-1001"][0],
                                    "GenX", "genY"] + [""] * 7)
        self.correr(dict(self.respuestas, **{"m-1004": "no se usa"}))
        leida = anotar.leer_corrida(self.salida)
        self.assertEqual(leida["resultados"]["m-1004"],
                         leida["resultados"]["m-1001"])

    def test_una_corrida_que_no_termino(self):
        cortada = dict(self.respuestas, **{"m-1003": RuntimeError("caído")})
        with self.assertRaises(RuntimeError):
            self.correr(cortada)
        with self.assertRaises(ValueError):
            anotar.leer_corrida(self.salida)

    def test_una_anotacion_tocada_despues(self):
        self.correr()
        with io.open(os.path.join(self.salida, anotar.ANOTACIONES), "a",
                     encoding="utf-8") as f:
            f.write("\n")
        with self.assertRaises(ValueError) as caja:
            anotar.leer_corrida(self.salida)
        self.assertIn(anotar.ANOTACIONES, str(caja.exception))

    def test_sin_corrida(self):
        with self.assertRaises(ValueError):
            anotar.leer_corrida(self.tmp)


# ------------------------------------------------- Ollama no se movió

# Lo que daba el código de antes de Bedrock y de `paralelo` (e828c8e), con la
# descripción falsa de arriba. Las corridas registradas en los protocolos
# (`identidad.entradas.prompt` 2f80f09a… y c90cf9f2…) se reusan y se comparan
# por estas llaves: si una cambia, sus veredictos dejan de encontrarse.
HUELLA_PRINCIPAL = ("2f80f09a5850fbf7860d8cb305dbf5fd47703b3aa97df86ab9cc72ace"
                    "9d7ddcc")
HUELLA_BUSCAR_LOCUS = ("c90cf9f2317ad4ea0a254a931c7ca60b455f9adcf5412a8cf1a57d"
                       "06b412647c")
ENTRADAS_PRINCIPAL = {
    "decodificacion": {"format": "esquema", "kv_cache": "f16",
                       "max_turnos": None, "nombre": "principal",
                       "num_ctx": 4096, "num_predict": 512, "seed": 42,
                       "temperature": 0.0, "think": False, "top_k": None,
                       "top_p": None},
    "esquema": {"huella": "c0fd5626f9bee00bfcc7d10b38b31560c8ebbce55e9b8ace19"
                          "09deefb516e88c",
                "version": 1},
    "herramientas": "ninguna",
    "modelo": {"cuantizacion": "Q4_K_M",
               "digest": "500a1f067a9f" + "0" * 52,
               "huella_template": "t" * 64, "nombre": "qwen3:8b"},
    "ollama": "0.12.6",
    "prompt": HUELLA_PRINCIPAL,
    "recursos": {},
}
LLAVE_PRINCIPAL = ("a59e1998ccc469853050b5e090edb570b0ae266245f991d13407ca539"
                   "0a2d667")
LLAVE_CON_THINK = ("34989a5a616519e00e9fc3aa75aeaf6d8793541f362fef817a85ca242"
                   "b1e378b")


class PruebasOllamaNoSeMovio(Base):
    """Con proveedor ollama todo da lo mismo que antes: la decodificación,
    las entradas, la llave y lo que `corrida.json` lleva."""

    def entradas(self, nombre="principal", herr="ninguna", **k):
        config = agente.configuracion(nombre)
        return anotar.armar_entradas(
            DESCRIPCION, agente.decodificacion(config, herr, **k),
            agente.huella_prompt(agente.leer_prompt(), herr), herr,
            herramientas.Recursos().huellas(herr))

    def test_las_huellas_registradas(self):
        prompt = agente.leer_prompt()
        self.assertEqual(agente.huella_prompt(prompt), HUELLA_PRINCIPAL)
        self.assertEqual(agente.huella_prompt(prompt, "buscar_locus"),
                         HUELLA_BUSCAR_LOCUS)

    def test_las_entradas_y_la_llave_de_la_principal(self):
        for e in (self.entradas(), self.entradas(proveedor="ollama")):
            self.assertEqual(e, ENTRADAS_PRINCIPAL)
            # Y en el mismo orden, sin una clave más.
            self.assertEqual(list(e), list(anotar.CLAVES_ENTRADAS))
            self.assertEqual(anotar.llave_cache(PruebasLlave.item, e),
                             LLAVE_PRINCIPAL)
        self.assertEqual(anotar.llave_cache(PruebasLlave.item,
                                            self.entradas("con_think")),
                         LLAVE_CON_THINK)

    def test_la_decodificacion_con_buscar_locus(self):
        d = agente.decodificacion(agente.configuracion("principal"),
                                  "buscar_locus")
        self.assertEqual(d, dict(ENTRADAS_PRINCIPAL["decodificacion"],
                                 format="en_el_prompt", max_turnos=10))

    def test_corrida_json_no_gana_campos(self):
        r, _ = self.correr(entradas=self.entradas())
        corrida = json.loads(self.leer(anotar.CORRIDA).decode("utf-8"))
        self.assertEqual(corrida["identidad"]["entradas"], ENTRADAS_PRINCIPAL)
        self.assertEqual(set(corrida), {
            "metodo", "version", "estatus", "iniciada_en", "identidad",
            "configuracion", "modelo", "versiones", "n_items", "terminada_en",
            "conteos", "reutilizadas", "nuevas", "segundos_esta_corrida",
            "salidas"})
        self.assertEqual(set(corrida["versiones"]),
                         {"python"} | set(anotar.PAQUETES))
        self.assertEqual(r["resumen"]["identidad"]["entradas"],
                         ENTRADAS_PRINCIPAL)


class PruebasLlaveBedrock(unittest.TestCase):
    """Con Bedrock la llave lleva el proveedor, el id y la región, y nunca
    coincide con la de Ollama aunque el prompt sea el mismo."""

    def entradas(self, modelo=agente.MODELO_BEDROCK,
                 region=agente.REGION_BEDROCK):
        config = agente.configuracion("principal")
        return anotar.armar_entradas(
            agente.describir_bedrock(modelo, region),
            agente.decodificacion(config, "ninguna", "bedrock"),
            agente.huella_prompt(agente.leer_prompt()), "ninguna", {})

    def test_lleva_proveedor_modelo_y_region(self):
        e = self.entradas()
        self.assertEqual(e["proveedor"], "bedrock")
        self.assertEqual(e["modelo"], {"model_id": agente.MODELO_BEDROCK,
                                       "region": "us-east-1"})
        self.assertIsNone(e["ollama"])
        self.assertEqual(e["decodificacion"]["format"], "en_el_prompt")
        self.assertEqual(e["prompt"], HUELLA_PRINCIPAL)
        for clave in anotar.CLAVES_ENTRADAS:
            self.assertIn(clave, e)

    def test_otra_llave_que_ollama_y_entre_ellas(self):
        item = PruebasLlave.item
        llaves = [anotar.llave_cache(item, e) for e in (
            self.entradas(),
            self.entradas(modelo="us.qwen.qwen3-32b-v1:0"),
            self.entradas(region="us-west-2"))]
        self.assertNotIn(LLAVE_PRINCIPAL, llaves)
        self.assertEqual(len(set(llaves)), 3)

    def test_la_identidad_de_la_corrida_difiere(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        hoja = os.path.join(tmp, "hoja.csv")
        _escribir_hoja(hoja, ORACIONES)
        falso = AnotadorFalso(dict((i, _json("x")) for i in ORACIONES))
        salida = os.path.join(tmp, "salida")
        r = anotar.ejecutar(hoja, salida, falso, self.entradas())
        entradas = r["resumen"]["identidad"]["entradas"]
        self.assertEqual((entradas["proveedor"],
                          entradas["modelo"]["model_id"],
                          entradas["modelo"]["region"]),
                         ("bedrock", agente.MODELO_BEDROCK, "us-east-1"))
        # La misma carpeta no la reusa una corrida de Ollama.
        with self.assertRaises(anotar.CarpetaOcupada):
            anotar.ejecutar(hoja, salida, falso, ENTRADAS_PRINCIPAL)


# --------------------------------------------------------------- paralelo

def _escribir_hoja(ruta, oraciones):
    with io.open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rubrica.COLUMNAS_HOJA)
        w.writeheader()
        for id_item, (oracion, e1, e2) in oraciones.items():
            w.writerow({"id_item": id_item, "oracion": oracion,
                        "entidad_1": e1, "entidad_2": e2})


class AnotadorLento(AnotadorFalso):
    """El falso, con una espera distinta por ítem y la cuenta de cuántos van
    a la vez. Sus respuestas pueden ser también un BaseException."""

    def __init__(self, respuestas, esperas):
        AnotadorFalso.__init__(self, respuestas)
        self.esperas = esperas
        self.avance = []
        self._candado = threading.Lock()
        self.en_vuelo = self.max_en_vuelo = 0

    def __call__(self, item):
        with self._candado:
            self.en_vuelo += 1
            self.max_en_vuelo = max(self.max_en_vuelo, self.en_vuelo)
        try:
            time.sleep(self.esperas.get(item["id_item"], 0))
            r = self.respuestas[item["id_item"]]
            if isinstance(r, BaseException) and not isinstance(r, Exception):
                self.llamadas.append(dict(item))
                raise r
            return AnotadorFalso.__call__(self, item)
        finally:
            with self._candado:
                self.en_vuelo -= 1


class PruebasParalelo(unittest.TestCase):
    """Con N hilos, las salidas son las de la corrida en serie, byte por
    byte: el mismo orden, el mismo contenido y el mismo avance. El falso
    tarda más en los primeros ítems, así que en paralelo terminan al revés
    de como se pidieron."""

    N = 12

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.oraciones = collections.OrderedDict()
        for i in range(1, self.N + 1):
            self.oraciones["m-%d" % (1100 + i)] = (
                "Gen%d activates gen%d in an invented sentence." % (i, i + 50),
                "Gen%d" % i, "gen%d" % (i + 50))
        # El último repite la oración y las entidades del tercero: la misma
        # llave, que se pide una sola vez.
        self.oraciones["m-%d" % (1100 + self.N)] = self.oraciones["m-1103"]
        self.hoja = os.path.join(self.tmp, "hoja.csv")
        _escribir_hoja(self.hoja, self.oraciones)
        self.respuestas = {}
        for i, (id_item, (oracion, e1, e2)) in enumerate(
                self.oraciones.items(), 1):
            self.respuestas[id_item] = _json(oracion.split(" in ")[0],
                                             signo="-" if i % 2 else "+")
        self.respuestas["m-1104"] = "Sin JSON."
        self.respuestas["m-1105"] = {"texto": _json("x"),
                                     "done_reason": "length",
                                     "truncado": True}
        self.respuestas["m-1107"] = _json("NO ESTA LITERAL")
        self.esperas = dict((id_item, 0.01 * (self.N - i))
                            for i, id_item in enumerate(self.oraciones))
        # La hora y el reloj fijos: lo único que cambiaría entre dos
        # corridas iguales.
        parche = mock.patch.object(anotar, "ahora",
                                   lambda: "2026-11-04T00:00:00+00:00")
        parche.start()
        self.addCleanup(parche.stop)

    def correr(self, nombre, paralelo, respuestas=None):
        falso = AnotadorLento(respuestas or self.respuestas, self.esperas)
        avance = []
        salida = os.path.join(self.tmp, nombre)
        try:
            anotar.ejecutar(self.hoja, salida, falso, _entradas(),
                            configuracion={"nombre": "principal"},
                            descripcion=DESCRIPCION, log=avance.append,
                            reloj=lambda: 0.0, paralelo=paralelo)
        finally:
            falso.avance = avance
        return falso

    def bytes_de(self, nombre):
        salida = {}
        for archivo in (anotar.ANOTACIONES, anotar.VEREDICTOS, anotar.CORRIDA):
            ruta = os.path.join(self.tmp, nombre, archivo)
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    salida[archivo] = f.read()
        return salida

    def test_las_salidas_no_dependen_de_n(self):
        serie = self.correr("serie", 1)
        paralelo = self.correr("paralelo", 4)
        self.assertGreater(paralelo.max_en_vuelo, 1)
        self.assertEqual(serie.max_en_vuelo, 1)
        self.assertEqual(self.bytes_de("serie"), self.bytes_de("paralelo"))
        self.assertEqual(len(self.bytes_de("serie")), 3)
        self.assertEqual(paralelo.avance, serie.avance)
        # El repetido se pidió una sola vez en las dos.
        for falso in (serie, paralelo):
            ids = sorted(it["id_item"] for it in falso.llamadas)
            self.assertEqual(ids, sorted(list(self.oraciones)[:-1]))
        corrida = json.loads(self.bytes_de("paralelo")[anotar.CORRIDA]
                             .decode("utf-8"))
        self.assertEqual((corrida["nuevas"], corrida["reutilizadas"]),
                         (self.N - 1, 1))
        self.assertEqual(corrida["conteos"]["abstenciones_por_motivo"],
                         {"json_invalido": 1, "truncado": 1})

    def test_y_tampoco_con_otro_n(self):
        self.correr("dos", 2)
        self.correr("ocho", 8)
        self.assertEqual(self.bytes_de("dos"), self.bytes_de("ocho"))

    def test_un_error_deja_lo_mismo_que_en_serie(self):
        """Se guarda lo anterior al ítem que falló, y nada después, aunque ya
        hubiera terminado; volver a correr retoma igual."""
        cortada = dict(self.respuestas, **{"m-1106": RuntimeError("caído")})
        self.esperas["m-1106"] = 0
        for nombre, n in (("serie", 1), ("paralelo", 4)):
            with self.assertRaises(RuntimeError):
                self.correr(nombre, n, cortada)
        self.assertEqual(self.bytes_de("serie"), self.bytes_de("paralelo"))
        lineas = self.bytes_de("paralelo")[anotar.VEREDICTOS].splitlines()
        self.assertEqual([json.loads(l)["id_item"] for l in lineas],
                         ["m-1101", "m-1102", "m-1103", "m-1104", "m-1105"])
        corrida = json.loads(self.bytes_de("paralelo")[anotar.CORRIDA]
                             .decode("utf-8"))
        self.assertEqual((corrida["estatus"], corrida["error"]),
                         ("error", "RuntimeError"))
        retomadas = [self.correr(nombre, n)
                     for nombre, n in (("serie", 1), ("paralelo", 4))]
        self.assertEqual(self.bytes_de("serie"), self.bytes_de("paralelo"))
        for falso in retomadas:
            self.assertEqual(sorted(it["id_item"] for it in falso.llamadas),
                             ["m-%d" % i for i in range(1106, 1100 + self.N)])
        # Y los veredictos quedan como los de una corrida sin cortes.
        self.correr("limpia", 1)
        self.assertEqual(self.bytes_de("limpia")[anotar.VEREDICTOS],
                         self.bytes_de("paralelo")[anotar.VEREDICTOS])

    def test_lo_que_no_habia_empezado_se_cancela(self):
        cortada = dict(self.respuestas, **{"m-1102": RuntimeError("caído")})
        self.esperas = dict((id_item, 0.05) for id_item in self.oraciones)
        self.esperas["m-1102"] = 0
        falso = AnotadorLento(cortada, self.esperas)
        with self.assertRaises(RuntimeError):
            anotar.ejecutar(self.hoja, os.path.join(self.tmp, "x"), falso,
                            _entradas(), reloj=lambda: 0.0, paralelo=2)
        self.assertLess(len(falso.llamadas), self.N - 1)
        # Al volver, ninguno sigue en vuelo.
        self.assertEqual(falso.en_vuelo, 0)

    def test_interrumpida_en_paralelo(self):
        interrumpe = dict(self.respuestas, **{"m-1104": KeyboardInterrupt()})
        with self.assertRaises(KeyboardInterrupt):
            self.correr("paralelo", 3, interrumpe)
        corrida = json.loads(self.bytes_de("paralelo")[anotar.CORRIDA]
                             .decode("utf-8"))
        self.assertEqual(corrida["error"], "KeyboardInterrupt")
        self.assertEqual(corrida["nuevas"], 3)

    def test_paralelo_invalido_no_escribe_nada(self):
        for malo in (0, -2, True, "4", 1.5):
            with self.assertRaises(ValueError, msg=repr(malo)):
                anotar.ejecutar(self.hoja, os.path.join(self.tmp, "y"),
                                AnotadorFalso({}), _entradas(),
                                paralelo=malo)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "y")))


if __name__ == "__main__":
    unittest.main()
