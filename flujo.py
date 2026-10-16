"""El flujo de punta a punta, con lo que ya existe.

    operones → bronce → pares → biobert → red → sintaxis → capa → evaluar

Cada paso es el CLI que ya tiene su paquete, corrido como proceso aparte
(`grn_comun.proceso`), y deja sus archivos en una carpeta por corrida del
bronce y modelo: `salidas/flujo/corrida4_run22/`. Es la respuesta a «correr el
flujo con lo que tenemos» (asesor, 2-oct-2026): ningún paso reimplementa lo que
ya hace otro.

**Idempotente por huella.** Cada paso declara sus entradas (archivos, su propio
código y sus parámetros) y sus salidas; si las huellas de las entradas son las
mismas que la última vez y las salidas siguen ahí con su huella, se salta.
Correr el flujo dos veces seguidas no repite nada. Cambiar un recurso rehace
ese paso y, por cadena de huellas, los de abajo.

**Reanudable.** `estado.json` se escribe después de cada paso, no al final: una
corrida cortada se retoma en el paso donde se quedó.

Uso:
    python flujo.py [--corrida N] [--pasos operones,bronce,...] [--forzar PASO,..]
                    [--limite N] [--datos D] [--modelo DIR] [--reusar-de DIR ...]

Biblioteca estándar y Python 3.8: el tablero lo importa.
"""

import argparse
import datetime
import glob
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from grn_comun import procedencia, proceso   # noqa: E402
from grn_comun.archivos import borrar, reemplazar     # noqa: E402

PASOS = ("operones", "bronce", "pares", "biobert", "red", "sintaxis", "capa",
         "evaluar")

NOMBRES = {
    "operones": "Operones (base de pertenencia)",
    "bronce": "Bronce: oraciones candidatas",
    "pares": "Pares para BioBERT",
    "biobert": "Clasificación con BioBERT",
    "red": "Red preliminar",
    "sintaxis": "Sintaxis con spaCy",
    "capa": "Capa: oración, funciones, operones y BioBERT",
    "evaluar": "Evaluación (44 % recalculado, oro)",
}

RAIZ_FLUJO = os.path.join(RAIZ, "salidas", "flujo")
MODELO_POR_OMISION = os.path.join(RAIZ, "modelo_limpio_run22")
REUSO_POR_OMISION = os.path.join(RAIZ, "datos_etapa2")
OPERONES_BASE = os.path.join(RAIZ, "grn_bronce", "recursos", "operones_base.tsv")
OPERONES_CATALOGO = os.path.join(RAIZ, "grn_bronce", "recursos",
                                 "operones_pao1.tsv")
GENES = os.path.join(RAIZ, "grn_bronce", "recursos", "genes_pao1.tsv")
DISPARADORES = os.path.join(RAIZ, "grn_bronce", "recursos", "disparadores.csv")
JUICIOS = [os.path.join(RAIZ, "etapa2", "evaluacion", "juicio_consolidado.csv"),
           os.path.join(RAIZ, "etapa2", "evaluacion",
                        "muestra_precision_50.csv")]

# Lo que el tablero puede listar y entregar de una carpeta del flujo. Igualdad
# contra un patrón cerrado, sin subcarpetas: el nombre llega por HTTP.
CARPETA_VALIDA = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
ARCHIVO_VALIDO = re.compile(
    r"^[A-Za-z0-9_.-]{1,160}\.(csv|tsv|json|jsonl|log|txt|xlsx)$")

ESTATUS_HECHO = ("ok", "saltado")


class ErrorFlujo(RuntimeError):
    """Un paso falló; el flujo se detiene ahí porque lo de abajo depende."""


def _nada(_m):
    pass


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _rel(ruta):
    """La ruta relativa a la raíz, con `/`: es lo que se guarda y se publica.

    Lo que vive fuera del repositorio (`GRN_DATOS` en la máquina del
    laboratorio) va absoluto: un `../../../datos` no le dice a nadie dónde
    está."""
    try:
        relativa = os.path.relpath(ruta, RAIZ)
    except ValueError:          # otra unidad en Windows
        return ruta.replace(os.sep, "/")
    if relativa == os.pardir or relativa.startswith(os.pardir + os.sep):
        return os.path.abspath(ruta).replace(os.sep, "/")
    return relativa.replace(os.sep, "/")


_TEXTO = (".tsv", ".csv", ".py", ".md", ".txt")
_SALIDAS = os.path.join(RAIZ, "salidas") + os.sep

# Entradas que pueden faltar sin que el paso falle: sin la base de operones el
# bronce y la capa salen igual, solo con los operones que la oración nombra.
OPCIONALES = (OPERONES_BASE,)


def _huella(ruta):
    """Huella por contenido, o None si el archivo no está.

    Los recursos de texto del repositorio se miden sin CRLF (`huella_texto`)
    para que un checkout de Windows no parezca otra versión; lo generado por el
    flujo y lo binario, por bytes.
    """
    if not ruta or not os.path.isfile(ruta):
        return None
    absoluta = os.path.abspath(ruta)
    if (absoluta.endswith(_TEXTO) and absoluta.startswith(RAIZ + os.sep)
            and not absoluta.startswith(_SALIDAS)):
        return procedencia.huella_texto(absoluta)
    return procedencia.huella(absoluta)


def _python_nlp(pedido=None):
    """El intérprete del entorno de spaCy, o None si no existe."""
    for candidato in (pedido, os.environ.get("GRN_PYTHON_NLP"),
                      os.path.join(RAIZ, ".venv-nlp", "Scripts", "python.exe"),
                      os.path.join(RAIZ, ".venv-nlp", "bin", "python")):
        if candidato and os.path.isfile(candidato):
            return candidato
    return None


def etiqueta_modelo(modelo):
    """`modelo_limpio_run22` → `run22`; otro checkpoint, su nombre saneado.

    Solo el modelo por omisión se abrevia. Antes cualquier nombre con
    `run_22` daba `run22`, y el run 22 del asesor, el reentrenado con la base
    curada y el limpio caían en la misma carpeta, con su caché y sus
    predicciones (ver la guarda de `correr`).
    """
    ruta = os.path.abspath(modelo or MODELO_POR_OMISION)
    nombre = os.path.basename(os.path.normpath(ruta))
    if os.path.normcase(ruta) == os.path.normcase(MODELO_POR_OMISION):
        m = re.search(r"run_?(\d+)", nombre)
        if m:
            return "run%s" % m.group(1)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", nombre)[:40] or "modelo"


def nombre_carpeta(corrida, modelo=None, limite=None):
    nombre = "corrida%d_%s" % (corrida, etiqueta_modelo(modelo))
    if limite:
        nombre += "_limite%d" % limite
    return nombre


# ------------------------------------------------------------ estado.json

def _leer_estado(carpeta):
    ruta = os.path.join(carpeta, "estado.json")
    if not os.path.isfile(ruta):
        return {"version": 1, "pasos": {}, "archivos": {}}
    with io.open(ruta, encoding="utf-8") as f:
        try:
            datos = json.load(f)
        except ValueError:
            datos = None
    # Un estado.json roto no puede tumbar la corrida ni el tablero, que lo
    # sirve: se rehace todo, que es lo seguro, y se deja dicho. JSON válido
    # que no es un objeto (una lista, un número) cuenta como roto.
    if (not isinstance(datos, dict)
            or not isinstance(datos.setdefault("pasos", {}), dict)
            or not isinstance(datos.setdefault("archivos", {}), dict)):
        return {"version": 1, "pasos": {}, "archivos": {},
                "nota": "estado.json ilegible; se rehízo"}
    return datos


def _escribir_estado(carpeta, estado):
    estado["actualizado"] = _ahora()
    ruta = os.path.join(carpeta, "estado.json")
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    reemplazar(tmp, ruta)


# ------------------------------------------------------------ los pasos

class _Contexto(object):
    """Lo que todos los pasos necesitan saber de esta corrida del flujo."""

    def __init__(self, carpeta, corrida, datos, modelo, python_bert,
                 python_nlp, reusar_de, limite, rehacer_operones, estado,
                 forzar=()):
        self.carpeta = carpeta
        self.corrida = corrida
        self.datos = datos
        self.modelo = modelo
        self.python_bert = python_bert
        self.python_nlp = python_nlp
        self.reusar_de = reusar_de
        self.limite = limite
        self.rehacer_operones = rehacer_operones
        self.estado = estado
        self.forzar = set(forzar or ())

    def ruta(self, nombre):
        return os.path.join(self.carpeta, nombre)

    def candidatas(self):
        nombre = self.estado["archivos"].get("candidatas")
        return self.ruta(nombre) if nombre else None

    def con_datos(self, argv):
        return argv + (["--datos", self.datos] if self.datos else [])


def _codigo(*relativas):
    return [os.path.join(RAIZ, r) for r in relativas]


def _archivos_del_modelo(modelo):
    """Todo archivo del checkpoint, sin subcarpetas: config, etiquetas, pesos y
    tokenizador. El `config.json` solo no distingue dos reentrenamientos de la
    misma receta (lo escriben idéntico byte a byte); los pesos sí."""
    if not os.path.isdir(modelo):
        return [os.path.join(modelo, "config.json")]
    return [os.path.join(modelo, n) for n in sorted(os.listdir(modelo))
            if os.path.isfile(os.path.join(modelo, n))]


def _vocabularios():
    from grn_bronce import vocabulario
    return [os.path.join(vocabulario.RECURSOS, nombre)
            for nombre, _ in vocabulario.VOCABULARIOS]


def _plan(ctx, paso):
    """Lo que corre cada paso: argv(s), entradas, parámetros y salidas.

    Devuelve un dict con `comandos` (lista de (argv, codigos_ok, opcional)),
    `entradas` (rutas cuya huella decide si se rehace), `parametros` y
    `salidas`. `omitir` con un motivo cuando el paso no aplica.
    """
    py = sys.executable
    if paso == "operones":
        comandos = []
        if ctx.rehacer_operones:
            base = [py, "-m", "grn_operones.cli"] + (
                ["--datos", ctx.datos] if ctx.datos else [])
            # Nunca `extraer`: sale a la red, pide credenciales de BioCyc y
            # sale con código 0 aunque una fuente falle. Desde los crudos ya
            # bajados todo es local y determinista.
            comandos = [(base + ["reparsear", "--fuente", "todo"], (0,), False),
                        (base + ["curar"], (0,), False),
                        (base + ["catalogo", "--paso1"], (0,), False)]
        elif not os.path.isfile(OPERONES_BASE):
            return {"omitir": "falta grn_bronce/recursos/operones_base.tsv; "
                              "se genera con `python -m grn_operones.cli "
                              "catalogo --paso1`. Sin él, la capa solo trae "
                              "los operones que la oración nombra."}
        return {"comandos": comandos,
                "entradas": [OPERONES_CATALOGO] + _codigo(
                    "grn_operones/curar.py", "grn_operones/exportar.py"),
                "parametros": {"rehacer": bool(ctx.rehacer_operones)},
                "salidas": [OPERONES_BASE]}

    if paso == "bronce":
        argv = ctx.con_datos([py, "-m", "grn_bronce.cli", "exportar",
                              "--corrida", str(ctx.corrida),
                              "--salida", ctx.carpeta])
        return {"comandos": [(argv, (0,), False)],
                "entradas": [OPERONES_BASE, OPERONES_CATALOGO] + _codigo(
                    "grn_bronce/cli.py", "grn_bronce/exportar.py",
                    "grn_bronce/operones.py", "grn_bronce/db.py"),
                "parametros": {"corrida": ctx.corrida},
                "salidas": "candidatas"}

    candidatas = ctx.candidatas()
    if paso == "pares":
        argv = [py, "-m", "grn_verificacion.cli", "pares",
                "--bronce", candidatas, "--carpeta", ctx.carpeta]
        if ctx.limite:
            argv += ["--limite", str(ctx.limite)]
        return {"comandos": [(argv, (0,), False)],
                "entradas": [candidatas, GENES, OPERONES_CATALOGO] + _codigo(
                    "grn_verificacion/puente.py", "grn_verificacion/cli.py",
                    "grn_bronce/identificar.py", "grn_bronce/texto.py",
                    "grn_bronce/operones.py", "etapa2/extraer_pares.py",
                    "etapa2/lexico.py"),
                "parametros": {"limite": ctx.limite},
                "salidas": [ctx.ruta("pares.jsonl"),
                            ctx.ruta("pares_informe.json")]}

    if paso == "biobert":
        argv = ctx.con_datos([py, "-m", "grn_verificacion.cli", "biobert",
                              "--carpeta", ctx.carpeta,
                              "--modelo", ctx.modelo,
                              "--python", ctx.python_bert])
        for d in ctx.reusar_de:
            argv += ["--reusar-de", d]
        if ctx.limite:
            argv += ["--sin-registrar"]
        if "biobert" in ctx.forzar:
            # Rehacer el paso es reclasificar. Sin esto, «forzar» volvía a
            # salir por «ya están hechas» o por la caché de la carpeta.
            argv += ["--sin-cache"]
        return {"comandos": [(argv, (0,), False)],
                "entradas": [ctx.ruta("pares.jsonl")]
                + _archivos_del_modelo(ctx.modelo)
                + _codigo("grn_verificacion/puente.py",
                          "grn_verificacion/cli.py", "etapa2/clasificar.py"),
                "parametros": {"modelo": _rel(ctx.modelo)},
                "salidas": [ctx.ruta("predicciones.jsonl"),
                            ctx.ruta("predicciones_meta.json")]}

    if paso == "red":
        argv = [py, os.path.join(RAIZ, "etapa2", "red.py"),
                "--predicciones", ctx.ruta("predicciones.jsonl"),
                "--pares", ctx.ruta("pares.jsonl"),
                "--salida", ctx.ruta("red.tsv"),
                "--evidencias", ctx.ruta("red_evidencias.tsv"),
                "--informe", ctx.ruta("red_informe.json")]
        return {"comandos": [(argv, (0,), False)],
                "entradas": [ctx.ruta("predicciones.jsonl"),
                             ctx.ruta("predicciones_meta.json"),
                             ctx.ruta("pares.jsonl")]
                + _codigo("etapa2/red.py", "grn_bronce/texto.py"),
                "parametros": {},
                "salidas": [ctx.ruta("red.tsv"), ctx.ruta("red_evidencias.tsv"),
                            ctx.ruta("red_informe.json")]}

    if paso == "sintaxis":
        if not ctx.python_nlp:
            return {"omitir": "no hay entorno de spaCy (.venv-nlp); se crea "
                              "con las instrucciones de "
                              "docs/plan-sintaxis-bronce.md"}
        argv = [ctx.python_nlp, "-m", "grn_bronce.cli", "sintaxis",
                "--entrada", candidatas,
                "--salida", ctx.ruta("sintaxis.jsonl")]
        if ctx.limite:
            argv += ["--limite", str(ctx.limite)]
        return {"comandos": [(argv, (0,), False)],
                "entradas": [candidatas, GENES, OPERONES_CATALOGO,
                             DISPARADORES]
                + _codigo("grn_bronce/sintaxis.py", "grn_bronce/cli.py",
                          "grn_bronce/identificar.py",
                          "grn_bronce/vocabulario.py", "grn_bronce/texto.py",
                          "etapa2/extraer_pares.py", "etapa2/lexico.py"),
                "parametros": {"limite": ctx.limite},
                "salidas": [ctx.ruta("sintaxis.jsonl")]}

    if paso == "capa":
        argv = [py, "-m", "grn_verificacion.cli", "capa",
                "--carpeta", ctx.carpeta, "--bronce", candidatas]
        sintaxis = ctx.ruta("sintaxis.jsonl")
        entradas = [candidatas, ctx.ruta("pares.jsonl"),
                    ctx.ruta("predicciones.jsonl"), OPERONES_BASE,
                    OPERONES_CATALOGO, GENES] + _codigo(
                        "grn_verificacion/capa.py", "grn_verificacion/puente.py",
                        "grn_verificacion/cli.py", "grn_bronce/operones.py",
                        "grn_bronce/identificar.py")
        if os.path.isfile(sintaxis):
            argv += ["--sintaxis", sintaxis]
            entradas.append(sintaxis)
        return {"comandos": [(argv, (0,), False)],
                "entradas": entradas, "parametros": {},
                # Si la capa falla, que no queden a la vista (ni en las cifras
                # del tablero) las filas de la corrida anterior.
                "borrar_antes": [ctx.ruta("capa_pares.csv"),
                                 ctx.ruta("capa_resumen.json")],
                "salidas": [ctx.ruta("capa_pares.csv"),
                            ctx.ruta("capa_resumen.json")]}

    if paso == "evaluar":
        if ctx.limite:
            return {"omitir": "con --limite no está la muestra completa: la "
                              "evaluación solo tiene sentido sobre la corrida "
                              "entera"}
        propia = [py, "-m", "grn_verificacion.cli", "evaluar",
                  "--carpeta", ctx.carpeta, "--bronce", candidatas]
        oro = [py, os.path.join(RAIZ, "etapa2", "evaluar_oro.py"),
               "--red", ctx.ruta("red.tsv"),
               "--pares", ctx.ruta("pares.jsonl"),
               "--predicciones", ctx.ruta("predicciones.jsonl"),
               "--red-informe", ctx.ruta("red_informe.json"),
               "--salida", ctx.ruta("evaluacion_oro.tsv"),
               "--resumen", ctx.ruta("evaluacion_oro.json")]
        signo = [py, os.path.join(RAIZ, "etapa2", "evaluar_signo.py"),
                 "--predicciones", ctx.ruta("predicciones.jsonl"),
                 "--pares", ctx.ruta("pares.jsonl"),
                 "--red-informe", ctx.ruta("red_informe.json"),
                 "--salida", ctx.ruta("evaluacion_signo.tsv"),
                 "--resumen", ctx.ruta("evaluacion_signo.json")]
        entradas = [ctx.ruta("capa_pares.csv"), ctx.ruta("red.tsv"),
                    ctx.ruta("red_informe.json"),
                    ctx.ruta("predicciones.jsonl"), ctx.ruta("pares.jsonl")]
        # Las referencias que leen los evaluadores de etapa2 con sus valores
        # por omisión (el diccionario, los operones y las dos referencias de
        # evaluación), por patrón y sin nombrarlas: corregir una tiene que
        # rehacer la evaluación, y antes respondía «ya hecho» con las cifras
        # viejas. Lo mismo los vocabularios que lee el control léxico.
        entradas += sorted(glob.glob(os.path.join(RAIZ, "etapa2", "*.tsv")))
        entradas += _vocabularios()
        entradas += JUICIOS + _codigo("grn_verificacion/evaluar.py",
                                      "grn_verificacion/capa.py",
                                      "grn_verificacion/puente.py",
                                      "grn_verificacion/cli.py",
                                      "grn_bronce/vocabulario.py",
                                      "grn_bronce/operones.py",
                                      "grn_bronce/texto.py",
                                      "etapa2/muestrear_precision.py",
                                      "etapa2/evaluar_oro.py",
                                      "etapa2/evaluar_signo.py")
        if os.path.isfile(ctx.ruta("sintaxis.jsonl")):
            entradas.append(ctx.ruta("sintaxis.jsonl"))
        # Los evaluadores de etapa2 salen con 2 cuando la cifra no le gana a
        # su línea base: es un resultado, no una falla. Si fallan de verdad,
        # queda como aviso y el flujo sigue: la evaluación propia es la que
        # recalcula el 44 %. Sus salidas viejas se borran antes de correr,
        # para que un fallo no deje a la vista las cifras de otra corrida.
        return {"comandos": [(propia, (0,), False),
                             (oro, (0, 2), True),
                             (signo, (0, 2), True)],
                "entradas": entradas, "parametros": {},
                "borrar_antes": [ctx.ruta(n) for n in (
                    "evaluacion.json",
                    "evaluacion_oro.tsv", "evaluacion_oro.json",
                    "evaluacion_signo.tsv", "evaluacion_signo.json")],
                "salidas": [ctx.ruta("evaluacion.json")]}

    raise ValueError("paso desconocido: %s" % paso)


def _huellas(rutas):
    return dict((_rel(r), _huella(r)) for r in rutas if r)


def _salidas_de(ctx, plan):
    if plan["salidas"] == "candidatas":
        r = ctx.candidatas()
        return [r] if r else []
    return plan["salidas"]


def _puede_saltarse(ctx, previo, entradas, parametros, plan):
    if not previo or previo.get("estatus") not in ESTATUS_HECHO:
        return False
    if previo.get("avisos"):
        # Un comando opcional falló la vez anterior: se reintenta en vez de
        # dar el paso por hecho para siempre.
        return False
    if previo.get("entradas") != entradas:
        return False
    if previo.get("parametros") != parametros:
        return False
    salidas = _salidas_de(ctx, plan)
    if not salidas:
        return False
    actuales = _huellas(salidas)
    if any(h is None for h in actuales.values()):
        return False
    return previo.get("salidas") == actuales


def _ubicar_candidatas(ctx):
    """El CSV que acaba de volcar el bronce: el nombre lleva la fecha."""
    patron = ctx.ruta("bronce_identificacion_corrida%d_*_oraciones_candidatas"
                      ".csv" % ctx.corrida)
    hallados = sorted(glob.glob(patron), key=os.path.getmtime)
    if not hallados:
        raise ErrorFlujo("El bronce no dejó el CSV de candidatas en %s"
                         % _rel(ctx.carpeta))
    ctx.estado["archivos"]["candidatas"] = os.path.basename(hallados[-1])


# Los pasos que unen pares.jsonl con predicciones.jsonl por `id_par`, que no
# depende del texto marcado.
LEEN_PREDICCIONES = ("red", "capa", "evaluar")


def _exigir_predicciones_al_dia(ctx, paso):
    """Con `--pasos` (o el tablero) se puede rehacer los pares y saltarse
    biobert: la red y los evaluadores de etapa2 unían entonces un texto nuevo
    con la predicción del viejo, sin avisar. El meta de las predicciones dice
    de qué `pares.jsonl` salieron."""
    meta_ruta = ctx.ruta("predicciones_meta.json")
    pares_ruta = ctx.ruta("pares.jsonl")
    if not (os.path.isfile(meta_ruta) and os.path.isfile(pares_ruta)):
        return
    with io.open(meta_ruta, encoding="utf-8") as f:
        try:
            meta = json.load(f)
        except ValueError:
            meta = {}
    if meta.get("huella_pares") != procedencia.huella(pares_ruta):
        raise ErrorFlujo("El paso «%s» une pares y predicciones, y "
                         "predicciones.jsonl no se hizo con este pares.jsonl: "
                         "corre antes el paso biobert." % paso)


def _correr_paso(ctx, paso, forzar, log, detener):
    previo = ctx.estado["pasos"].get(paso)
    if paso != "bronce" and paso != "operones" and not ctx.candidatas():
        raise ErrorFlujo("El paso «%s» necesita el CSV de candidatas: corre "
                         "antes el paso bronce." % paso)
    plan = _plan(ctx, paso)
    registro = {"inicio": _ahora(), "nombre": NOMBRES[paso]}
    if "omitir" in plan:
        registro.update(estatus="omitido", nota=plan["omitir"], fin=_ahora())
        log("· %s: omitido. %s" % (NOMBRES[paso], plan["omitir"]))
        ctx.estado["pasos"][paso] = registro
        return "omitido"

    if paso in LEEN_PREDICCIONES:
        _exigir_predicciones_al_dia(ctx, paso)

    entradas = _huellas(plan["entradas"])
    opcionales = set(_rel(r) for r in OPCIONALES)
    faltan = [r for r, h in entradas.items() if h is None
              and r not in opcionales and not r.endswith("sintaxis.jsonl")]
    if faltan and paso not in ("operones",):
        raise ErrorFlujo("Al paso «%s» le faltan entradas: %s"
                         % (paso, ", ".join(faltan)))

    if paso not in forzar and _puede_saltarse(ctx, previo, entradas,
                                              plan["parametros"], plan):
        log("· %s: ya hecho (mismas entradas y salidas)." % NOMBRES[paso])
        previo["estatus"] = "saltado"
        previo["revisado"] = _ahora()
        return "saltado"

    log("")
    log("▶ %s" % NOMBRES[paso])
    inicio = time.monotonic()
    avisos = []
    codigos = []
    argvs = []
    for ruta in plan.get("borrar_antes", ()):
        borrar(ruta)
    for argv, codigos_ok, opcional in plan["comandos"]:
        argvs.append([_rel(a) if os.path.isabs(str(a)) else a for a in argv])
        try:
            r = proceso.correr(argv, log=log, detener=detener, cwd=RAIZ,
                               codigos_ok=codigos_ok)
            codigos.append(r["codigo"])
        except proceso.ErrorProceso as e:
            if not opcional:
                registro.update(estatus="error", fin=_ahora(), argv=argvs,
                                segundos=round(time.monotonic() - inicio, 1),
                                nota=str(e), entradas=entradas,
                                parametros=plan["parametros"])
                ctx.estado["pasos"][paso] = registro
                raise ErrorFlujo("Falló el paso «%s»: %s" % (paso, e))
            avisos.append(str(e).splitlines()[0])
            codigos.append(e.codigo)
    if paso == "bronce":
        _ubicar_candidatas(ctx)
    registro.update(
        estatus="ok", fin=_ahora(), argv=argvs, codigos=codigos,
        segundos=round(time.monotonic() - inicio, 1), entradas=entradas,
        parametros=plan["parametros"],
        salidas=_huellas(_salidas_de(ctx, plan)))
    if avisos:
        registro["nota"] = "Avisos: " + " | ".join(avisos)
        registro["avisos"] = avisos
    ctx.estado["pasos"][paso] = registro
    log("✓ %s (%.1f s)" % (NOMBRES[paso], registro["segundos"]))
    return "ok"


def _conexion(datos):
    """La base que van a abrir los pasos. Ellos corren con el directorio de
    trabajo en la raíz del repositorio, así que una raíz de datos relativa se
    resuelve contra esa raíz y no contra el directorio de quien llamó: si no,
    el flujo creaba una base vacía en otro lado y decía que no había
    corridas."""
    from grn_bronce import db as bdb, rutas
    raiz = rutas.raiz_datos(datos)
    if not os.path.isabs(raiz):
        raiz = os.path.join(RAIZ, raiz)
    return bdb.conectar(os.path.join(raiz, "grn.db"))


def _python_nlp_pedido(pedido=None):
    """El intérprete de spaCy que se pidió (flag o `GRN_PYTHON_NLP`), ya
    resuelto, o None si no se pidió ninguno. Lo pedido y no encontrado es
    error: antes se cambiaba en silencio por `.venv-nlp`, o el paso quedaba
    «omitido» sin decir que se ignoró la petición."""
    pedido = pedido or os.environ.get("GRN_PYTHON_NLP")
    if not pedido:
        return None
    ruta = _interprete(pedido)
    if not (os.sep in ruta or (os.altsep and os.altsep in ruta)):
        ruta = shutil.which(ruta) or ruta
    if not os.path.isfile(ruta):
        raise ErrorFlujo("No encuentro el intérprete de spaCy pedido: %s"
                         % pedido)
    return ruta


def _interprete(ruta):
    """Un intérprete dado como ruta (con separador) pasa a absoluto, porque
    los pasos corren desde la raíz; un nombre suelto, como `python3`, se deja
    para que lo busque el PATH."""
    if ruta and (os.sep in ruta or (os.altsep and os.altsep in ruta)):
        return os.path.abspath(ruta)
    return ruta


def ultima_corrida_bronce(con):
    from grn_bronce import db as bdb
    return bdb.ultima_corrida(con, "1")


def correr(corrida=None, pasos=None, forzar=(), datos=None, salida=None,
           modelo=None, python_bert=None, python_nlp=None, reusar_de=None,
           sin_reusar=False, limite=None, rehacer_operones=False, log=_nada,
           detener=None, con=None, **_ignorado):
    """Corre los pasos pedidos (todos por omisión) y devuelve el resumen.

    Lanza `ErrorFlujo` si un paso falla y `proceso.Cancelado` si se pidió
    detener; en los dos casos `estado.json` queda escrito con lo hecho hasta
    ahí. `con` lo inyecta el gestor del tablero y no se usa: cada paso abre su
    propia conexión en su propio proceso.
    """
    # None es «todos»; una lista vacía no: quien desmarcó todo no pidió eso.
    pasos = list(PASOS) if pasos is None else list(pasos)
    if not pasos:
        raise ValueError("no se pidió ningún paso")
    desconocidos = [p for p in pasos if p not in PASOS]
    if desconocidos:
        raise ValueError("pasos desconocidos: %s" % ", ".join(desconocidos))
    forzar = set(forzar or ())
    modelo = os.path.abspath(modelo or MODELO_POR_OMISION)
    # Absolutas desde aquí: los pasos corren con el directorio de trabajo en
    # la raíz del repositorio, y una ruta relativa al de quien llamó apuntaba
    # a otro lado en el padre y en los hijos.
    datos = os.path.abspath(datos) if datos else None
    python_bert = _interprete(python_bert or os.environ.get("GRN_PYTHON_BERT")
                              or sys.executable)
    python_nlp = _python_nlp_pedido(python_nlp)
    if sin_reusar:
        reusar = []
    elif reusar_de:
        reusar = [os.path.abspath(d) for d in reusar_de]
    else:
        reusar = [REUSO_POR_OMISION] if os.path.isdir(REUSO_POR_OMISION) \
            else []

    if corrida is None:
        cn = _conexion(datos)
        try:
            corrida = ultima_corrida_bronce(cn)
        finally:
            cn.close()
        if corrida is None:
            raise ErrorFlujo("No hay ninguna corrida del bronce terminada: "
                             "corre `python -m grn_bronce.cli exportar`.")

    raiz = os.path.abspath(salida or RAIZ_FLUJO)
    carpeta = os.path.join(raiz, nombre_carpeta(corrida, modelo, limite))
    os.makedirs(carpeta, exist_ok=True)
    candado = os.path.join(carpeta, ".flujo.lock")
    try:
        fd = os.open(candado, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ErrorFlujo("Otra corrida del flujo usa %s. Si no hay ninguna "
                         "viva (se cortó de golpe), borra %s."
                         % (_rel(carpeta), _rel(candado)))
    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)

    archivo = None
    resumen = {}
    try:
        estado = _leer_estado(carpeta)
        anterior = estado.get("modelo")
        if anterior and anterior != _rel(modelo):
            # Su caché, sus predicciones y su evaluación son de otro modelo:
            # seguir aquí las mezclaría, o pisaría las cifras del anterior.
            raise ErrorFlujo(
                "La carpeta %s es del modelo %s y pediste %s. Usa --salida con "
                "otra raíz, o renombra la carpeta del checkpoint."
                % (_rel(carpeta), anterior, _rel(modelo)))
        estado.update(corrida_bronce=corrida, modelo=_rel(modelo),
                      limite=limite, carpeta=os.path.basename(carpeta))
        ctx = _Contexto(carpeta, corrida, datos, modelo, python_bert,
                        _python_nlp(python_nlp), reusar, limite,
                        rehacer_operones, estado, forzar)
        archivo = open(os.path.join(carpeta, "flujo.log"), "a",
                       encoding="utf-8", buffering=1)
        archivo.write("\n=== %s\n" % _ahora())

        def registrar(m):
            # Las líneas del orquestador y las de los pasos pasan todas por
            # aquí. Antes el archivo solo recibía la salida de los hijos, y un
            # «ya hecho» o un «omitido» no dejaban rastro en él.
            archivo.write(m + "\n")
            log(m)

        registrar("Flujo sobre la corrida %d del bronce, modelo %s, en %s"
                  % (corrida, etiqueta_modelo(modelo), _rel(carpeta)))
        for paso in PASOS:
            if paso not in pasos:
                continue
            if detener is not None and detener.is_set():
                raise proceso.Cancelado("Cancelado antes de «%s»" % paso)
            try:
                resumen[paso] = _correr_paso(ctx, paso, forzar, registrar,
                                             detener)
            except proceso.Cancelado:
                estado["pasos"][paso] = {"estatus": "cancelado",
                                         "nombre": NOMBRES[paso],
                                         "fin": _ahora()}
                resumen[paso] = "cancelado"
                raise
            finally:
                _escribir_estado(carpeta, estado)
        registrar("")
        registrar("Listo: %s" % ", ".join("%s %s" % (p, e)
                                          for p, e in resumen.items()))
    except (ErrorFlujo, proceso.Cancelado) as e:
        # Quien llamó reporta el error (main lo imprime, el gestor lo guarda);
        # aquí solo se anota en el archivo, para no repetirlo en pantalla.
        if archivo is not None:
            archivo.write("%s\n" % e)
        raise
    finally:
        if archivo is not None:
            archivo.close()
        try:
            os.remove(candado)
        except OSError:
            pass
    return {"carpeta": os.path.basename(carpeta), "corrida": corrida,
            "pasos": resumen}


# ------------------------------------------------------------ para el tablero

def _lista_archivos(carpeta):
    archivos = []
    for nombre in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, nombre)
        if os.path.isfile(ruta) and ARCHIVO_VALIDO.match(nombre):
            st = os.stat(ruta)
            archivos.append({"nombre": nombre, "bytes": st.st_size,
                             "modificado": datetime.datetime.fromtimestamp(
                                 st.st_mtime, datetime.timezone.utc).strftime(
                                     "%Y-%m-%dT%H:%M:%SZ")})
    return archivos


def _carpeta_hija(raiz, nombre):
    """La ruta de `nombre` si es hija directa de `raiz`, o None.

    El nombre llega por HTTP: se valida con un patrón cerrado y además se
    comprueba que la ruta resuelta quede exactamente un nivel bajo la raíz.
    """
    if not nombre or not CARPETA_VALIDA.match(nombre) or nombre in (".", ".."):
        return None
    raiz = os.path.realpath(raiz)
    ruta = os.path.realpath(os.path.join(raiz, nombre))
    if os.path.dirname(ruta) != raiz or not os.path.isdir(ruta):
        return None
    return ruta


def leer_carpeta(raiz, nombre):
    """Estado y archivos de una carpeta del flujo, o None si no es válida."""
    carpeta = _carpeta_hija(raiz or RAIZ_FLUJO, nombre)
    if carpeta is None:
        return None
    return {"nombre": nombre, "estado": _leer_estado(carpeta),
            "archivos": _lista_archivos(carpeta)}


def ruta_archivo(raiz, carpeta, nombre):
    """La ruta en disco de un archivo listable de una carpeta, o None."""
    ruta_carpeta = _carpeta_hija(raiz or RAIZ_FLUJO, carpeta)
    if ruta_carpeta is None or not nombre or not ARCHIVO_VALIDO.match(nombre):
        return None
    if nombre not in [a["nombre"] for a in _lista_archivos(ruta_carpeta)]:
        return None
    ruta = os.path.realpath(os.path.join(ruta_carpeta, nombre))
    if os.path.dirname(ruta) != ruta_carpeta:
        return None
    return ruta


def estado_general(con=None, raiz=None):
    """Lo que el tablero pinta: corridas del bronce, carpetas y entornos."""
    raiz = raiz or RAIZ_FLUJO
    corridas = []
    if con is not None:
        from grn_bronce import db as bdb
        try:
            filas = bdb.listar_corridas(con, 50, paso="1")
        except sqlite3.OperationalError:
            # Una base donde el bronce nunca corrió no tiene la tabla. Otro
            # error de la base sí se deja subir: no es «no hay corridas».
            filas = []
        for f in filas:
            if f["estatus"] == "ok":
                corridas.append({"id": f["id"], "metodo": f["metodo"],
                                 "version": f["version"],
                                 "iniciada_en": f["iniciada_en"],
                                 "n_salida": f["n_salida"]})
    carpetas = []
    if os.path.isdir(raiz):
        for nombre in sorted(os.listdir(raiz)):
            if _carpeta_hija(raiz, nombre) is None:
                continue
            estado = _leer_estado(os.path.join(raiz, nombre))
            pasos = {}
            for p in PASOS:
                registro = estado["pasos"].get(p)
                pasos[p] = (registro.get("estatus", "pendiente")
                            if isinstance(registro, dict) else "pendiente")
            carpetas.append({
                "nombre": nombre,
                "corrida_bronce": estado.get("corrida_bronce"),
                "modelo": estado.get("modelo"),
                "limite": estado.get("limite"),
                "actualizado": estado.get("actualizado"),
                "pasos": pasos})
    return {"raiz": _rel(raiz), "pasos": list(PASOS), "nombres": NOMBRES,
            "corridas_bronce": corridas, "carpetas": carpetas,
            "entornos": {"modelo": os.path.isdir(MODELO_POR_OMISION),
                         "nlp": _python_nlp() is not None,
                         "reuso": os.path.isdir(REUSO_POR_OMISION),
                         "operones_base": os.path.isfile(OPERONES_BASE)}}


# ------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Corre el flujo: operones, bronce, BioBERT, red, sintaxis, "
                    "capa y evaluación.")
    ap.add_argument("--corrida", type=int, default=None,
                    help="Corrida del bronce (por omisión, la última terminada).")
    ap.add_argument("--pasos", default=None,
                    help="Pasos separados por coma (por omisión, todos): %s"
                         % ",".join(PASOS))
    ap.add_argument("--forzar", default="",
                    help="Pasos que se rehacen aunque nada haya cambiado.")
    ap.add_argument("--datos", default=None,
                    help="Raíz de datos; gana sobre GRN_DATOS.")
    ap.add_argument("--salida", default=None,
                    help="Raíz de las carpetas del flujo (salidas/flujo).")
    ap.add_argument("--modelo", default=None,
                    help="Checkpoint del clasificador (modelo_limpio_run22).")
    ap.add_argument("--python-bert", dest="python_bert", default=None,
                    help="Intérprete con torch y transformers.")
    ap.add_argument("--python-nlp", dest="python_nlp", default=None,
                    help="Intérprete con spaCy (por omisión, .venv-nlp).")
    ap.add_argument("--reusar-de", dest="reusar_de", action="append",
                    help="Carpeta con predicciones previas del mismo modelo.")
    ap.add_argument("--sin-reusar", dest="sin_reusar", action="store_true",
                    help="No reutilizar predicciones de otras carpetas "
                         "(datos_etapa2); la caché de esta carpeta se sigue "
                         "usando. Para reclasificar todo: --forzar biobert.")
    ap.add_argument("--limite", type=int, default=None,
                    help="Solo las primeras N oraciones (prueba rápida).")
    ap.add_argument("--rehacer-operones", dest="rehacer_operones",
                    action="store_true",
                    help="Regenerar operones_base.tsv desde los crudos.")
    args = ap.parse_args(argv)
    # La consola de Windows es cp1252: una barra de progreso («█») o una sigma
    # en la salida de un paso tumbaba el `print`. Se reemplaza lo que no cabe.
    for flujo_salida in (sys.stdout, sys.stderr):
        if hasattr(flujo_salida, "reconfigure"):
            flujo_salida.reconfigure(errors="replace")
    pasos = [p.strip() for p in args.pasos.split(",")] if args.pasos else None
    forzar = [p.strip() for p in args.forzar.split(",") if p.strip()]
    try:
        r = correr(corrida=args.corrida, pasos=pasos, forzar=forzar,
                   datos=args.datos, salida=args.salida, modelo=args.modelo,
                   python_bert=args.python_bert, python_nlp=args.python_nlp,
                   reusar_de=args.reusar_de, sin_reusar=args.sin_reusar,
                   limite=args.limite, rehacer_operones=args.rehacer_operones,
                   log=print)
    except ValueError as e:
        print("Uso incorrecto: %s" % e)
        return 2
    except proceso.Cancelado as e:
        print(str(e))
        return 3
    except ErrorFlujo as e:
        print("")
        print(str(e))
        return 1
    return 0 if all(e in ("ok", "saltado", "omitido")
                    for e in r["pasos"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
