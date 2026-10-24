"""Strands Evals sobre los veredictos de una corrida, con evaluadores propios
y deterministas.

Un `Case` por ítem (`name` y `session_id` son el `id_item`), y la tarea del
experimento no llama al modelo: devuelve el veredicto que `anotar.ejecutar`
ya guardó. Así el informe de Strands Evals describe exactamente lo que está en
`anotaciones.csv`, y correrlo dos veces no gasta GPU.

Los evaluadores (`docs/decisiones.md`, «Ouroboros v0»):

- `CampoExacto(campo)`, uno por cada campo cerrado de la hoja: acuerdo exacto
  con la referencia. La abstención cuenta como error.
- `ValidezRubrica`: si la respuesta fue un JSON con la forma pedida que pasa
  `revision.validar`. Lo que no, fue abstención, y la etiqueta dice por qué.
- `FragmentoValido`: si el fragmento citado está literal en la oración.

La única referencia es la llave de la calibración, que es sintética y
pública (`calibracion.referencia_si_es_calibracion`). Con una tanda no hay
referencia: los evaluadores por campo dan «no aplica», y el acuerdo con el
experto se mide fuera de este paquete, con `grn_verificacion.cli
concordancia`.

Los jueces y su envoltura
=========================
La regla de cada evaluador vive en una clase de biblioteca estándar (`JUECES`)
con un método `juzgar(esperado, obtenido)`. `clases()` las envuelve al vuelo
como subclases de `strands_evals.evaluators.Evaluator`, con el mismo nombre de
clase. Así la regla se prueba sin Strands Evals, y la guarda de que ningún
juez traiga modelo mira las mismas clases que usa el experimento.

Los atributos de cada juez se llaman como los parámetros de su `__init__`:
con eso `Evaluator.to_dict` los escribe en el experimento y
`Experiment.from_file` los vuelve a armar.

Lo que no se usa, a propósito: `OutputEvaluator` y los demás evaluadores con
LLM, que sin modelo explícito juzgan con Bedrock (Claude). Los de aquí no
tienen campo `model`, y una prueba falla si lo ganan o si algo construye un
`BedrockModel`. Tampoco se corre con `AGENT_OBSERVABILITY_ENABLED` en el
entorno: con ella, Strands Evals manda cada resultado a CloudWatch, y los
casos llevan las oraciones de la hoja.

`to_file` agrega `.json` a un nombre sin extensión y rechaza cualquier otra:
`experimento` e `informe_evals` van sin puntos.

Strands Evals se importa dentro de las funciones: este módulo se importa sin
él, en el Python 3.8 del servidor o en la laptop.
"""

import functools
import importlib.util
import os

from grn_ouroboros import anotar, rubrica

NOMBRE_EXPERIMENTO = "experimento"
NOMBRE_INFORME = "informe_evals"

# Con cualquiera de estas en el entorno, los resultados saldrían del
# servidor: la primera la lee Strands Evals para mandar a CloudWatch.
VARIABLES_DE_ENVIO = ("AGENT_OBSERVABILITY_ENABLED",)

# La etiqueta de «nada que juzgar»: es `strands_evals.types.NOT_APPLICABLE`,
# copiada para que los jueces no necesiten Strands Evals. Una prueba vigila que
# sigan iguales; si difieren, el informe contaría el «no aplica» como fallo.
NO_APLICA = "not_applicable"


def _nada(_mensaje):
    pass


def disponible():
    return importlib.util.find_spec("strands_evals") is not None


# ------------------------------------------------------------------ jueces

class CampoExacto(object):
    """Acuerdo exacto con la referencia en un campo cerrado de la hoja. La
    abstención cuenta como error."""

    def __init__(self, campo, name=None):
        if campo not in rubrica.CAMPOS_CERRADOS:
            raise ValueError("Campo que la hoja no tiene.")
        self.campo = campo
        self.name = name or "campo_%s" % campo

    def juzgar(self, esperado, obtenido):
        if not esperado:
            return 0.0, True, "Sin referencia para este ítem.", NO_APLICA
        if obtenido.get("abstencion", True):
            return 0.0, False, "Abstención: cuenta como error.", "abstencion"
        bien = ((obtenido.get("valores") or {}).get(self.campo, "")
                == esperado.get(self.campo, ""))
        return (1.0 if bien else 0.0, bien,
                "Coincide." if bien else "No coincide.",
                "acuerdo" if bien else "desacuerdo")


class ValidezRubrica(object):
    """Si la respuesta tuvo la forma pedida y pasó la rúbrica. La etiqueta de
    una abstención es su motivo (`truncado`, `json_invalido`...)."""

    def __init__(self, name=None):
        self.name = name or "validez_rubrica"

    def juzgar(self, esperado, obtenido):
        if obtenido.get("abstencion", True):
            motivo = obtenido.get("motivo_abstencion") or "sin_respuesta"
            return 0.0, False, "Abstención: %s." % motivo, motivo
        return 1.0, True, "Pasa la rúbrica.", "valida"


class FragmentoValido(object):
    """Si el fragmento que sostiene el juicio está literal en la oración."""

    def __init__(self, name=None):
        self.name = name or "fragmento_valido"

    def juzgar(self, esperado, obtenido):
        if obtenido.get("abstencion", True):
            return 0.0, False, "Abstención: no hay fragmento.", "abstencion"
        if obtenido.get("evidencia_invalida") == "no":
            return 1.0, True, "Literal en la oración.", "literal"
        return (0.0, False, "No está literal en la oración.",
                "fragmento_invalido")


JUECES = (CampoExacto, ValidezRubrica, FragmentoValido)


def especificaciones():
    """[(juez, argumentos)] del experimento: uno por campo cerrado, más la
    validez y el fragmento."""
    return ([(CampoExacto, {"campo": c}) for c in rubrica.CAMPOS_CERRADOS]
            + [(ValidezRubrica, {}), (FragmentoValido, {})])


# ------------------------------------------------------- Strands Evals

_CLASES = {}


def _envolver(juez, Evaluator, EvaluationOutput):
    """El juez como subclase de `Evaluator`, con el mismo nombre de clase:
    `get_type_name()` es el nombre de la clase, y es lo que `from_file`
    busca entre los `custom_evaluators`."""

    @functools.wraps(juez.__init__)
    def __init__(self, *args, **kwargs):
        # Primero el de Strands, que pone el agregador y name=None; después el
        # del juez, que pone sus atributos y su nombre. `wraps` deja la firma
        # del juez, que es la que `to_dict` lee para omitir los valores por
        # omisión.
        Evaluator.__init__(self)
        juez.__init__(self, *args, **kwargs)

    def evaluate(self, evaluation_case):
        puntaje, paso, razon, etiqueta = self.juzgar(
            evaluation_case.expected_output,
            evaluation_case.actual_output or {})
        return [EvaluationOutput(score=float(puntaje), test_pass=bool(paso),
                                 reason=razon, label=etiqueta)]

    return type(juez.__name__, (juez, Evaluator),
                {"__init__": __init__, "evaluate": evaluate,
                 "__doc__": juez.__doc__, "__module__": __name__})


def clases():
    """{nombre: clase} de los evaluadores de Strands Evals, armadas al primer
    uso."""
    if _CLASES:
        return _CLASES
    from strands_evals.evaluators import Evaluator
    from strands_evals.types import EvaluationOutput
    for juez in JUECES:
        _CLASES[juez.__name__] = _envolver(juez, Evaluator, EvaluationOutput)
    return _CLASES


def evaluadores():
    """Las instancias de Strands Evals, en el orden de `especificaciones`."""
    c = clases()
    return [c[juez.__name__](**argumentos)
            for juez, argumentos in especificaciones()]


def salida_de(valor):
    """Lo que la tarea devuelve de un veredicto guardado: lo que miran los
    evaluadores, sin el texto crudo ni la trayectoria."""
    return {"abstencion": bool(valor["abstencion"]),
            "motivo_abstencion": valor.get("motivo_abstencion") or "",
            "valores": valor.get("valores") or {},
            "evidencia_invalida": valor.get("evidencia_invalida") or ""}


def casos(items, referencia=None):
    from strands_evals import Case
    referencia = referencia or {}
    return [Case(name=it["id_item"], session_id=it["id_item"],
                 input={"oracion": it["oracion"],
                        "entidad_1": it["entidad_1"],
                        "entidad_2": it["entidad_2"]},
                 expected_output=referencia.get(it["id_item"]),
                 metadata={"con_referencia": it["id_item"] in referencia})
            for it in items]


def _exigir_sin_envio():
    puestas = [v for v in VARIABLES_DE_ENVIO if os.environ.get(v)]
    if puestas:
        raise RuntimeError(
            "%s está en el entorno: Strands Evals mandaría los casos, con sus "
            "oraciones, fuera del servidor. Quítala y vuelve a correr."
            % ", ".join(puestas))


def resumir(informe):
    """{evaluador: {"k", "n", "no_aplica"}} del informe: pasan k de los n
    casos con veredicto. Un evaluador que falló detiene todo: Strands Evals
    lo registra como un caso más que no pasó, y la cifra lo escondería."""
    resumen = {}
    errores = 0
    for caso, paso, razon, detalle in zip(informe.cases, informe.test_passes,
                                          informe.reasons,
                                          informe.detailed_results):
        nombre = caso.get("evaluator")
        fila = resumen.setdefault(nombre, {"k": 0, "n": 0, "no_aplica": 0})
        if not detalle:
            if str(razon).startswith(("Evaluator error", "An error occurred")):
                errores += 1
            fila["n"] += 1
            continue
        if all(d.not_applicable for d in detalle):
            fila["no_aplica"] += 1
            continue
        fila["n"] += 1
        fila["k"] += 1 if paso else 0
    if errores:
        raise RuntimeError("Un evaluador falló en %d casos." % errores)
    return resumen


def ejecutar(carpeta, items, resultados, referencia=None, log=_nada):
    """Escribe `experimento.json` e `informe_evals.json` en `carpeta` y
    devuelve el resumen por evaluador. `resultados` es {id_item: veredicto},
    el de `anotar.ejecutar`; `referencia`, {id_item: valores} o None."""
    # Antes de importar nada: lo que cae en la carpeta del experto o saldría
    # del servidor se rechaza aunque Strands Evals no esté.
    anotar.validar_salida(carpeta)
    _exigir_sin_envio()
    faltan = [it["id_item"] for it in items if it["id_item"] not in resultados]
    if faltan:
        raise ValueError("Faltan los veredictos de %d ítems de la hoja."
                         % len(faltan))
    from strands_evals import Experiment
    experimento = Experiment(cases=casos(items, referencia),
                             evaluators=evaluadores())
    experimento.to_file(os.path.join(carpeta, NOMBRE_EXPERIMENTO))
    por_id = dict((id_item, salida_de(valor))
                  for id_item, valor in resultados.items())

    def tarea(caso):
        return {"output": por_id[caso.name]}

    informe = experimento.run_evaluations(tarea)
    informe.to_file(os.path.join(carpeta, NOMBRE_INFORME))
    resumen = resumir(informe)
    for nombre, fila in resumen.items():
        if fila["n"]:
            log("%s: %d de %d" % (nombre, fila["k"], fila["n"]))
        else:
            log("%s: no aplica (sin referencia)" % nombre)
    return resumen
