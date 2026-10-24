"""La corrida con un anotador falso: la caché, la abstención, el fragmento y
las salidas. Ni Strands ni Ollama: el falso devuelve texto fijo y cuenta sus
llamadas. Las oraciones son inventadas.

    python -m unittest grn_ouroboros.test_anotar
"""

import csv
import io
import json
import os
import shutil
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
