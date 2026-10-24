"""CLI de Ouroboros v0, el único módulo del paquete que imprime.

    python -m grn_ouroboros.cli humo [--host URL]
    python -m grn_ouroboros.cli anotar --hoja H --salida D
        --config {principal,con_think} [--semilla S] [--num-ctx N]
        [--kv-cache {f16,q8_0,q4_0}]
        [--herramientas {ninguna,buscar_locus,todas}]
        [--llave L --corrida-bronce N [--db DB]] [--prompt RUTA] [--host URL]
    python -m grn_ouroboros.cli calibracion --anotacion A
    python -m grn_ouroboros.cli evals --salida D

Corre en el servidor, con el Python de `.venv-ouroboros`; los pasos, en el
orden en que se corren, están en `docs/ouroboros-v0.md`. Parsea, llama y
formatea: la lógica vive en los módulos.

- `humo`: la versión de Ollama, el digest y la cuantización del modelo, si es
  el pre-registrado y si con think = false la respuesta llega sin
  razonamiento.
- `anotar`: anota una hoja de la rúbrica. Antes llama a `motor.exigir`: un
  digest o una cuantización distintos detienen la corrida con código 1, sin
  anotar nada.
- `calibracion`: el acuerdo de una anotación con la llave de la calibración,
  por campo y por ítem.
- `evals`: Strands Evals sobre una corrida ya hecha, sin volver a llamar al
  modelo.

Lo que imprime son conteos, versiones y huellas, nunca una oración ni el
veredicto de un ítem: la tanda 2 es ciega para toda sesión de Claude hasta
evaluarla, y la terminal es lo que esas sesiones ven. La excepción es
`calibracion`, que da los desacuerdos por ítem, porque sus ítems son
sintéticos y públicos.

`--salida` nunca cae dentro de salidas/revision, la carpeta del experto: las
salidas de Ouroboros van a salidas/ouroboros/ (`anotar.validar_salida`).

Códigos de salida: 0 bien; 1 el modelo no es el pre-registrado, Ollama no
contesta o la corrida se detuvo; 2 argumentos o entradas que no sirven; 3
interrumpida (lo hecho queda en la caché, y volver a correr lo retoma).
"""

import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from grn_bronce import db as bdb  # noqa: E402
from grn_comun import rutas  # noqa: E402
from grn_ouroboros import (agente, anotar, calibracion, evals,  # noqa: E402
                           herramientas, motor, rubrica)

BIEN, FALLA, ENTRADA, INTERRUMPIDA = 0, 1, 2, 3

# Se declara con --kv-cache; si no, vale la del entorno, que es la que lee
# Ollama al arrancar cuando se lanza desde la misma terminal.
VARIABLE_KV = "OLLAMA_KV_CACHE_TYPE"

SIN_STRANDS = ("Strands no está instalado: corre con el Python de "
               ".venv-ouroboros (docs/ouroboros-v0.md).")


def log(mensaje):
    # Con flush: en el servidor la corrida va con nohup a un archivo, y sin él
    # el avance llegaría en bloques, al final.
    print(mensaje, flush=True)


def consola_tolerante():
    """La consola de Windows imprime cp1252: lo que no cabe se reemplaza en
    vez de tumbar la corrida."""
    for flujo_salida in (sys.stdout, sys.stderr):
        if hasattr(flujo_salida, "reconfigure"):
            flujo_salida.reconfigure(errors="replace")


def _porcentaje(k, n):
    return "%d/%d (%.0f %%)" % (k, n, 100.0 * k / n) if n else "%d/%d" % (k, n)


def _mostrar_modelo(d):
    log("Ollama %s en %s" % (d["ollama"], d["host"]))
    log("modelo %s: digest %s, cuantización %s, %s %s"
        % (d["modelo"], d["digest"][:12], d["cuantizacion"] or "(ninguna)",
           d["familia"], d["parametros"]))
    log("capacidades: %s" % (", ".join(d["capacidades"]) or "(ninguna)"))


# ---------------------------------------------------------------- humo

def cmd_humo(args):
    try:
        r = motor.humo(args.host)
    except motor.ErrorMotor as e:
        log("ERROR: %s" % e)
        return FALLA
    _mostrar_modelo(r["descripcion"])
    for problema in r["problemas"]:
        log("NO ES EL PRE-REGISTRADO: %s" % problema)
    if not r["problemas"]:
        log("Es el pre-registrado (digest %s, %s)."
            % (motor.DIGEST_PREFIJO, motor.CUANTIZACION))
    estado = ("sin razonamiento" if r["sin_razonamiento"] else
              "TRAE RAZONAMIENTO (%d caracteres)"
              % r["caracteres_de_razonamiento"])
    log("think = false: %s (done_reason %s, %s tokens, %.1f s)"
        % (estado, r["done_reason"], r["tokens"], r["segundos"]))
    return BIEN if not r["problemas"] and r["sin_razonamiento"] else FALLA


# -------------------------------------------------------------- anotar

def _recursos(args, items):
    """Los recursos de las herramientas pedidas, o None. Con `todas`,
    `contexto` necesita la llave del sorteo, la base y la corrida del bronce,
    y se comprueba antes de correr que sean los de esta hoja."""
    if args.herramientas == "ninguna":
        return None
    if args.herramientas == "buscar_locus":
        return herramientas.Recursos()
    faltan = [nombre for nombre, valor in (("--llave", args.llave),
                                           ("--corrida-bronce",
                                            args.corrida_bronce))
              if valor is None]
    if faltan:
        raise ValueError("Con --herramientas todas, contexto necesita %s."
                         % " y ".join(faltan))
    recursos = herramientas.Recursos(
        ruta_llave=args.llave, ruta_db=args.db or rutas.ruta("grn.db"),
        corrida_bronce=args.corrida_bronce)
    recursos.verificar_contexto(items)
    return recursos


def _mostrar_conteos(resumen):
    c = resumen["conteos"]
    motivos = ", ".join("%s %d" % par
                        for par in c["abstenciones_por_motivo"].items())
    log("Listo: %d ítems, %d válidos y %d abstenciones%s."
        % (c["items"], c["validas"], c["abstenciones"],
           " (%s)" % motivos if motivos else ""))
    log("fragmentos que no están literales: %d; con avisos de la rúbrica: %d"
        % (c["fragmentos_invalidos"], c["con_avisos"]))
    if c["llamadas_a_herramientas"]:
        log("llamadas a herramientas: %d" % c["llamadas_a_herramientas"])
    log("nuevos: %d, de la caché: %d; %.1f s del modelo en total, %.1f s en "
        "esta corrida" % (resumen["nuevas"], resumen["reutilizadas"],
                          c["segundos_totales"],
                          resumen["segundos_esta_corrida"]))


def cmd_anotar(args):
    herr = args.herramientas
    try:
        anotar.validar_salida(args.salida)
        motor.validar_host(args.host)
        items = calibracion.leer_hoja(args.hoja)
        config = agente.configuracion(args.config, semilla=args.semilla,
                                      num_ctx=args.num_ctx,
                                      kv_cache=args.kv_cache)
        prompt = agente.leer_prompt(args.prompt)
        recursos = _recursos(args, items)
    except (ValueError, OSError, bdb.ErrorBase, motor.ErrorMotor) as e:
        log("ERROR: %s" % e)
        return ENTRADA
    try:
        descripcion = motor.exigir(motor.describir(args.host))
    except motor.ErrorMotor as e:
        log("ERROR: %s" % e)
        return FALLA
    _mostrar_modelo(descripcion)
    try:
        anotador = agente.crear_anotador(config, prompt, host=args.host,
                                         herramientas=herr, recursos=recursos)
    except ImportError:
        log("ERROR: %s" % SIN_STRANDS)
        return ENTRADA
    entradas = anotar.armar_entradas(
        descripcion, agente.decodificacion(config, herr),
        agente.huella_prompt(prompt, herr), herr,
        recursos.huellas(herr) if recursos else {})
    log("Anotando %d ítems: %s (%s, T %s, semilla %d, num_ctx %d, num_predict "
        "%d, caché KV %s), herramientas: %s."
        % (len(items), config["nombre"],
           "con think" if config["think"] else "sin think",
           config["temperature"], config["seed"], config["num_ctx"],
           config["num_predict"], config["kv_cache"], herr))
    try:
        r = anotar.ejecutar(
            args.hoja, args.salida, anotador, entradas,
            configuracion=dict(config, herramientas=herr,
                               prompt=os.path.basename(args.prompt)),
            descripcion=descripcion, log=log)
    except anotar.CarpetaOcupada as e:
        log("ERROR: %s" % e)
        return ENTRADA
    except KeyboardInterrupt:
        log("Interrumpida. Lo hecho queda en %s, y volver a correr lo retoma."
            % anotar.VEREDICTOS)
        return INTERRUMPIDA
    except Exception as e:
        # Solo el tipo: el mensaje de una excepción del cliente o de Strands
        # puede traer el texto de la petición, que lleva la oración.
        log("ERROR: la corrida se detuvo (%s). Lo hecho queda en %s, y volver "
            "a correr lo retoma." % (type(e).__name__, anotar.VEREDICTOS))
        return FALLA
    _mostrar_conteos(r["resumen"])
    return BIEN


# --------------------------------------------------------- calibracion

def cmd_calibracion(args):
    try:
        anotaciones = calibracion.leer_anotaciones(args.anotacion)
        r = calibracion.comparar(anotaciones, calibracion.leer_llave())
    except (ValueError, OSError) as e:
        log("ERROR: %s" % e)
        return ENTRADA
    log("ítems: %d; idénticos a la llave: %d; abstenciones: %d"
        % (r["n"], r["identicos"], r["abstenciones"]))
    log("acuerdo por campo (la abstención cuenta como error):")
    for campo in rubrica.CAMPOS_CERRADOS:
        p = r["por_campo"][campo]
        log("  %-13s %s" % (campo, _porcentaje(p["k"], p["n"])))
    log("por ítem:")
    for id_item in sorted(r["por_item"]):
        fila = r["por_item"][id_item]
        if fila["abstencion"]:
            estado = "abstención"
        elif fila["difiere"]:
            estado = "difiere en %s" % ", ".join(fila["difiere"])
        else:
            estado = "igual"
        log("  %s: %s" % (id_item, estado))
    return BIEN


# --------------------------------------------------------------- evals

def cmd_evals(args):
    try:
        anotar.validar_salida(args.salida)
        corrida = anotar.leer_corrida(args.salida)
    except (ValueError, OSError) as e:
        log("ERROR: %s" % e)
        return ENTRADA
    if not evals.disponible():
        log("ERROR: %s" % SIN_STRANDS.replace("Strands", "Strands Evals"))
        return ENTRADA
    items = corrida["items"]
    referencia = calibracion.referencia_si_es_calibracion(items)
    log("%d ítems; referencia: %s" % (
        len(items), "la llave de la calibración" if referencia
        else "ninguna, así que los campos no aplican"))
    try:
        evals.ejecutar(args.salida, items, corrida["resultados"], referencia,
                       log=log)
    except RuntimeError as e:
        log("ERROR: %s" % e)
        return FALLA
    log("Escritos %s.json y %s.json en la carpeta de la corrida."
        % (evals.NOMBRE_EXPERIMENTO, evals.NOMBRE_INFORME))
    return BIEN


# ---------------------------------------------------------------- main

def _kv_del_entorno():
    valor = os.environ.get(VARIABLE_KV)
    return valor if valor in agente.TIPOS_KV else None


def main(argv=None):
    consola_tolerante()
    ap = argparse.ArgumentParser(
        prog="grn_ouroboros.cli",
        description="Ouroboros v0: el juez LLM local, exploratorio y fuera "
                    "del pipeline (docs/ouroboros-v0.md).")
    sub = ap.add_subparsers(dest="sub", required=True)

    hu = sub.add_parser("humo", help="Versión, digest y cuantización, y una "
                                     "respuesta con think = false.")
    hu.add_argument("--host", default=motor.HOST,
                    help="Ollama local; por omisión %(default)s.")
    hu.set_defaults(func=cmd_humo)

    an = sub.add_parser("anotar", help="Anota una hoja de la rúbrica.")
    an.add_argument("--hoja", required=True,
                    help="La hoja sin anotar: la de la calibración o la de "
                         "una tanda.")
    an.add_argument("--salida", required=True,
                    help="Carpeta de la corrida, bajo salidas/ouroboros/; "
                         "nunca dentro de salidas/revision.")
    an.add_argument("--config", required=True,
                    choices=sorted(agente.CONFIGURACIONES),
                    help="Una de las pre-registradas.")
    an.add_argument("--semilla", type=int, default=None,
                    help="Otra semilla; por omisión la de la configuración.")
    an.add_argument("--num-ctx", dest="num_ctx", type=int, default=None,
                    help="Otro num_ctx; solo si el de la configuración no "
                         "cabe en la GPU ni con la caché KV comprimida.")
    an.add_argument("--kv-cache", dest="kv_cache", choices=agente.TIPOS_KV,
                    default=_kv_del_entorno(),
                    help="La caché KV con que arrancó Ollama (%s). No se "
                         "puede leer por la API: se declara. Por omisión la "
                         "del entorno, o f16." % VARIABLE_KV)
    an.add_argument("--herramientas", choices=herramientas.OPCIONES,
                    default="ninguna",
                    help="Por omisión, ninguna: el experto juzga solo la "
                         "oración.")
    an.add_argument("--llave", default=None,
                    help="Con todas: la llave.csv del sorteo, de la que "
                         "contexto lee solo la posición de cada ítem.")
    an.add_argument("--corrida-bronce", dest="corrida_bronce", type=int,
                    default=None,
                    help="Con todas: la corrida del bronce de la que salió "
                         "la muestra.")
    an.add_argument("--db", default=None,
                    help="Con todas: la base; por omisión <datos>/grn.db, "
                         "con datos de GRN_DATOS o ./datos.")
    an.add_argument("--prompt", default=agente.RUTA_PROMPT,
                    help="El prompt del sistema; por omisión el v0.")
    an.add_argument("--host", default=motor.HOST,
                    help="Ollama local; por omisión %(default)s.")
    an.set_defaults(func=cmd_anotar)

    ca = sub.add_parser("calibracion",
                        help="El acuerdo con la llave de la calibración, por "
                             "campo y por ítem.")
    ca.add_argument("--anotacion", required=True,
                    help="anotaciones.csv de una corrida sobre la hoja de "
                         "la calibración.")
    ca.set_defaults(func=cmd_calibracion)

    ev = sub.add_parser("evals", help="Strands Evals sobre una corrida ya "
                                      "hecha.")
    ev.add_argument("--salida", required=True,
                    help="La carpeta de la corrida; ahí quedan "
                         "experimento.json e informe_evals.json.")
    ev.set_defaults(func=cmd_evals)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
