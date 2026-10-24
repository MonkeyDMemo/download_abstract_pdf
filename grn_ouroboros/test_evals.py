"""Strands Evals con los evaluadores propios, y la guarda de que el juez
nunca sea Claude.

Las reglas de los jueces y la guarda de que ninguno traiga modelo corren sin
Strands Evals: miran las clases de biblioteca estándar que el experimento
envuelve. Lo que arma el experimento de verdad se salta donde no está. La
guarda de Bedrock parcha `BedrockModel.__init__` para que construir uno falle:
si el anotador o el experimento cayeran en Bedrock, la prueba lo dice.

    python -m unittest grn_ouroboros.test_evals
"""

import importlib.util
import inspect
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from grn_ouroboros import evals, rubrica

TIENE_EVALS = importlib.util.find_spec("strands_evals") is not None
TIENE_STRANDS = importlib.util.find_spec("strands") is not None
MOTIVO = "strands_evals no está instalado: es del .venv-ouroboros"

ITEMS = [
    {"id_item": "c01", "oracion": "GenX activates genY.", "entidad_1": "GenX",
     "entidad_2": "genY"},
    {"id_item": "c02", "oracion": "GenQ and genR are listed.",
     "entidad_1": "GenQ", "entidad_2": "genR"},
    {"id_item": "c03", "oracion": "GenS represses genT.", "entidad_1": "GenS",
     "entidad_2": "genT"},
    {"id_item": "c04", "oracion": "GenU binds the genV promoter.",
     "entidad_1": "GenU", "entidad_2": "genV"},
]
SI = {"relacion": "si", "direccion": "1>2", "signo": "+", "tipo": "no_se",
      "negada": "no", "especulativa": "no"}
NO = {"relacion": "no", "direccion": "ninguna", "signo": "", "tipo": "",
      "negada": "no", "especulativa": "no"}


def _valido(valores, evidencia="no"):
    return {"abstencion": False, "motivo_abstencion": "",
            "valores": dict(valores, comentario=""),
            "evidencia_invalida": evidencia, "texto": "{}", "trayectoria": []}


RESULTADOS = {
    "c01": _valido(SI),                                    # todo bien
    "c02": _valido(SI),                                    # la llave dice no
    "c03": {"abstencion": True, "motivo_abstencion": "truncado",
            "valores": None, "evidencia_invalida": "", "texto": ""},
    "c04": _valido(dict(SI, signo="?"), evidencia="si"),   # fragmento malo
}
REFERENCIA = {"c01": SI, "c02": NO, "c03": dict(SI, signo="-"),
              "c04": dict(SI, signo="?", tipo="directa")}
NOMBRES = set(["campo_%s" % c for c in rubrica.CAMPOS_CERRADOS]
              + ["validez_rubrica", "fragmento_valido"])


def _jueces():
    return [juez(**argumentos)
            for juez, argumentos in evals.especificaciones()]


class PruebasJueces(unittest.TestCase):
    """Las reglas, sobre las clases de biblioteca estándar."""

    def juzgar(self, juez, id_item, referencia=REFERENCIA):
        return juez.juzgar(referencia.get(id_item),
                           evals.salida_de(RESULTADOS[id_item]))

    def test_campo_exacto(self):
        signo = evals.CampoExacto("signo")
        self.assertEqual(self.juzgar(signo, "c01")[:2], (1.0, True))
        self.assertEqual(self.juzgar(signo, "c04")[3], "acuerdo")
        relacion = evals.CampoExacto("relacion")
        self.assertEqual(self.juzgar(relacion, "c02")[:2], (0.0, False))

    def test_la_abstencion_es_error(self):
        for juez in _jueces():
            puntaje, paso, _razon, _etiqueta = self.juzgar(juez, "c03")
            self.assertEqual((puntaje, paso), (0.0, False), juez.name)
        self.assertEqual(self.juzgar(evals.ValidezRubrica(), "c03")[3],
                         "truncado")
        self.assertEqual(self.juzgar(evals.FragmentoValido(), "c03")[3],
                         "abstencion")

    def test_la_abstencion_es_error_aunque_la_llave_diga_no(self):
        """Con relación «no» la llave deja signo y tipo vacíos, y una
        abstención no trae valores: sin la regla explícita, el vacío contra
        el vacío contaría como acuerdo."""
        for motivo in ("truncado", "json_invalido"):
            abstencion = {"abstencion": True, "motivo_abstencion": motivo,
                          "valores": None, "evidencia_invalida": ""}
            for juez in _jueces():
                puntaje, paso, _razon, _etiqueta = juez.juzgar(
                    NO, evals.salida_de(abstencion))
                self.assertEqual((puntaje, paso), (0.0, False),
                                 "%s, %s" % (juez.name, motivo))

    def test_sin_referencia_no_aplica(self):
        r = self.juzgar(evals.CampoExacto("tipo"), "c01", referencia={})
        self.assertEqual(r[3], evals.NO_APLICA)
        self.assertTrue(r[1])
        # La validez y el fragmento no necesitan referencia.
        self.assertEqual(
            self.juzgar(evals.ValidezRubrica(), "c01", referencia={})[3],
            "valida")

    def test_el_fragmento(self):
        self.assertEqual(self.juzgar(evals.FragmentoValido(), "c01")[3],
                         "literal")
        self.assertEqual(self.juzgar(evals.FragmentoValido(), "c04")[3],
                         "fragmento_invalido")

    def test_un_campo_que_la_hoja_no_tiene(self):
        with self.assertRaises(ValueError):
            evals.CampoExacto("comentario")


class PruebasNingunJuezTraeModelo(unittest.TestCase):
    """Un evaluador con `model` es uno con LLM, y sin modelo explícito
    Strands Evals juzga con Bedrock (Claude). Se mira en las clases del
    módulo, que son las que el experimento envuelve."""

    def test_ni_en_la_firma_ni_en_los_atributos(self):
        for juez in evals.JUECES:
            parametros = inspect.signature(juez.__init__).parameters
            self.assertNotIn("model", parametros, juez.__name__)
            self.assertNotIn("model_id", parametros, juez.__name__)
            self.assertFalse(hasattr(juez, "model"), juez.__name__)
        for juez in _jueces():
            self.assertFalse(set(vars(juez)) & {"model", "model_id"},
                             juez.name)

    def test_los_atributos_se_llaman_como_los_parametros(self):
        """Lo que `to_dict` escribe y `from_file` vuelve a armar."""
        for juez in _jueces():
            parametros = set(inspect.signature(type(juez).__init__)
                             .parameters) - {"self"}
            self.assertEqual(set(vars(juez)), parametros, juez.name)

    def test_los_nombres_son_unicos(self):
        self.assertEqual(set(j.name for j in _jueces()), NOMBRES)
        self.assertEqual(len(_jueces()), len(NOMBRES))

    def test_solo_los_jueces_propios(self):
        """Ningún evaluador de Strands Evals entra por nombre al módulo."""
        with open(evals.__file__, encoding="utf-8") as f:
            texto = f.read()
        codigo = texto.split('"""', 2)[2]   # sin el docstring, que los nombra
        for prohibido in ("OutputEvaluator", "BedrockModel", "model_id",
                          "model="):
            self.assertNotIn(prohibido, codigo)


class PruebasSinStrandsEvals(unittest.TestCase):

    def setUp(self):
        # Una carpeta propia y no la temporal del sistema: ahí otro proceso
        # puede tener un `salidas/revision` a medias, y la prueba fallaría
        # sin que el módulo hubiera creado nada.
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_disponible_no_revienta(self):
        self.assertIsInstance(evals.disponible(), bool)

    def test_salida_de_un_veredicto(self):
        s = evals.salida_de(RESULTADOS["c03"])
        self.assertEqual(s, {"abstencion": True,
                             "motivo_abstencion": "truncado", "valores": {},
                             "evidencia_invalida": ""})
        self.assertNotIn("texto", evals.salida_de(RESULTADOS["c01"]))

    def test_no_corre_si_mandaria_a_cloudwatch(self):
        with mock.patch.dict(os.environ, {"AGENT_OBSERVABILITY_ENABLED": "1"}):
            with self.assertRaises(RuntimeError):
                evals.ejecutar(self.tmp, ITEMS, RESULTADOS)
        # Se detiene antes de armar el experimento: no escribe nada.
        self.assertEqual(os.listdir(self.tmp), [])

    def test_nunca_en_la_carpeta_del_experto(self):
        carpeta = os.path.join(self.tmp, "salidas", "revision", "t1")
        with self.assertRaises(ValueError):
            evals.ejecutar(carpeta, ITEMS, RESULTADOS)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "salidas")))

    def test_faltan_veredictos(self):
        incompletos = dict(RESULTADOS)
        del incompletos["c04"]
        with self.assertRaises(ValueError):
            evals.ejecutar(self.tmp, ITEMS, incompletos)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_los_nombres_de_los_archivos_no_llevan_puntos(self):
        self.assertNotIn(".", evals.NOMBRE_EXPERIMENTO)
        self.assertNotIn(".", evals.NOMBRE_INFORME)

    def test_resumir_cuenta_y_detiene_si_un_evaluador_fallo(self):
        """Con un informe falso que tiene las cuatro listas del de Strands
        Evals, una fila por (caso, evaluador)."""
        def fila(nombre, paso, aplica=True, razon="r", detalle=True):
            d = [types.SimpleNamespace(not_applicable=not aplica)]
            return {"evaluator": nombre}, paso, razon, d if detalle else []

        def informe(filas):
            casos, pasos, razones, detalles = zip(*filas)
            return types.SimpleNamespace(
                cases=list(casos), test_passes=list(pasos),
                reasons=list(razones), detailed_results=list(detalles))

        filas = [fila("a", True), fila("a", False), fila("a", True, False),
                 fila("b", True)]
        self.assertEqual(evals.resumir(informe(filas)),
                         {"a": {"k": 1, "n": 2, "no_aplica": 1},
                          "b": {"k": 1, "n": 1, "no_aplica": 0}})
        filas.append(fila("b", False, razon="Evaluator error: x",
                          detalle=False))
        with self.assertRaises(RuntimeError):
            evals.resumir(informe(filas))


@unittest.skipUnless(TIENE_EVALS, MOTIVO)
class PruebasEvaluadores(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_ninguno_trae_modelo(self):
        for e in evals.evaluadores():
            self.assertFalse(hasattr(e, "model"), e.get_name())
            serializado = e.to_dict()
            self.assertNotIn("model", serializado)
            self.assertNotIn("model_id", serializado)

    def test_son_los_jueces_envueltos(self):
        from strands_evals.evaluators import Evaluator
        for e in evals.evaluadores():
            self.assertIsInstance(e, Evaluator)
            self.assertIn(type(e).__name__,
                          [j.__name__ for j in evals.JUECES])
        self.assertEqual(set(e.get_name() for e in evals.evaluadores()),
                         NOMBRES)

    def test_no_aplica_es_la_etiqueta_de_strands(self):
        from strands_evals.types import NOT_APPLICABLE
        self.assertEqual(evals.NO_APLICA, NOT_APPLICABLE)

    def test_con_la_referencia_de_la_calibracion(self):
        r = evals.ejecutar(self.tmp, ITEMS, RESULTADOS, REFERENCIA)
        self.assertEqual(r["campo_relacion"], {"k": 2, "n": 4,
                                               "no_aplica": 0})
        # c03 es abstención: error también en el signo.
        self.assertEqual(r["campo_signo"]["k"], 3 - 1)
        self.assertEqual(r["campo_tipo"]["k"], 1)
        self.assertEqual(r["validez_rubrica"], {"k": 3, "n": 4,
                                                "no_aplica": 0})
        self.assertEqual(r["fragmento_valido"], {"k": 2, "n": 4,
                                                 "no_aplica": 0})
        for nombre in (evals.NOMBRE_EXPERIMENTO, evals.NOMBRE_INFORME):
            ruta = os.path.join(self.tmp, nombre + ".json")
            self.assertTrue(os.path.isfile(ruta), nombre)
            with open(ruta, encoding="utf-8") as f:
                json.load(f)

    def test_sin_referencia_los_campos_no_aplican(self):
        r = evals.ejecutar(self.tmp, ITEMS, RESULTADOS)
        self.assertEqual(r["campo_relacion"], {"k": 0, "n": 0,
                                               "no_aplica": 4})
        self.assertEqual(r["validez_rubrica"]["k"], 3)

    def test_un_caso_por_item_con_su_id_de_sesion(self):
        casos = evals.casos(ITEMS, REFERENCIA)
        self.assertEqual([(c.name, c.session_id) for c in casos],
                         [(it["id_item"], it["id_item"]) for it in ITEMS])
        self.assertEqual(casos[1].expected_output, NO)

    def test_el_experimento_se_vuelve_a_armar_desde_el_archivo(self):
        """Los atributos se llaman como los parámetros de `__init__`."""
        from strands_evals import Experiment
        evals.ejecutar(self.tmp, ITEMS, RESULTADOS, REFERENCIA)
        de_nuevo = Experiment.from_file(
            os.path.join(self.tmp, evals.NOMBRE_EXPERIMENTO + ".json"),
            custom_evaluators=list(evals.clases().values()))
        self.assertEqual(sorted(e.get_name() for e in de_nuevo.evaluators),
                         sorted(NOMBRES))
        self.assertEqual([c.session_id for c in de_nuevo.cases],
                         [it["id_item"] for it in ITEMS])


@unittest.skipUnless(TIENE_EVALS and TIENE_STRANDS, MOTIVO)
class PruebasNuncaBedrock(unittest.TestCase):
    """Si algo construye un `BedrockModel`, el juez sería Claude."""

    def setUp(self):
        from strands.models import bedrock

        def prohibido(*_a, **_k):
            raise AssertionError("se construyó un BedrockModel")

        parche = mock.patch.object(bedrock.BedrockModel, "__init__",
                                   prohibido)
        parche.start()
        self.addCleanup(parche.stop)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_la_guarda_funciona(self):
        from strands import Agent
        with self.assertRaises(AssertionError):
            Agent(callback_handler=None)

    def test_el_anotador_no_construye_bedrock(self):
        """Llamándolo, no solo creándolo: el `Agent` se arma dentro del
        anotador, uno por ítem, y `crear_anotador` solo arma el
        `OllamaModel`. El cliente de `ollama` es el falso de `test_agente`:
        ninguna petición sale a la red."""
        import ollama
        from grn_ouroboros import agente, test_agente
        falso = test_agente._ClienteFalso
        with mock.patch.object(ollama, "AsyncClient", falso), \
                mock.patch.multiple(falso, peticiones=[], construido_con=[],
                                    guion=None, texto="{}", razon="stop"):
            for herramientas in ("ninguna", "buscar_locus"):
                anotador = agente.crear_anotador(
                    agente.PRINCIPAL, "Sistema.", herramientas=herramientas)
                r = anotador(test_agente.ITEM)
                self.assertEqual(r["done_reason"], "stop", herramientas)
            self.assertEqual(len(falso.peticiones), 2)

    def test_el_experimento_no_construye_bedrock(self):
        r = evals.ejecutar(self.tmp, ITEMS, RESULTADOS, REFERENCIA)
        self.assertEqual(set(r), NOMBRES)


if __name__ == "__main__":
    unittest.main()
