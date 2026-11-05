"""CLI de Ouroboros v0, el único módulo del paquete que imprime.

    python -m grn_ouroboros.cli humo [--host URL]
    python -m grn_ouroboros.cli anotar --hoja H --salida D
        --config {principal,con_think} [--semilla S] [--num-ctx N]
        [--kv-cache {f16,q8_0,q4_0}]
        [--herramientas {ninguna,buscar_locus,todas}]
        [--llave L --corrida-bronce N [--db DB]] [--prompt RUTA] [--host URL]
    python -m grn_ouroboros.cli anotar --hoja H --salida D --config principal
        --proveedor bedrock [--modelo ID] [--region R] [--perfil-aws P]
        [--paralelo N] [--contexto C] [--tope-usd X] [--precios E,S]
    python -m grn_ouroboros.cli anotar --hoja H --salida D --config razonador
        --proveedor bedrock --modelo openai.gpt-oss-120b-1:0
        [--razonamiento {low,medium,high}] [...lo mismo]
    python -m grn_ouroboros.cli contexto --hoja H --llave L
        --corrida-bronce N [--db DB] --salida C.csv
    python -m grn_ouroboros.cli calibracion --anotacion A
    python -m grn_ouroboros.cli evals --salida D [--contexto C]

Corre en el servidor, con el Python de `.venv-ouroboros`; los pasos, en el
orden en que se corren, están en `docs/ouroboros-v0.md`. Parsea, llama y
formatea: la lógica vive en los módulos.

- `humo`: la versión de Ollama, el digest y la cuantización del modelo, si es
  el pre-registrado y si con think = false la respuesta llega sin
  razonamiento.
- `anotar`: anota una hoja de la rúbrica. Antes llama a `motor.exigir`: un
  digest o una cuantización distintos detienen la corrida con código 1, sin
  anotar nada. Con `--proveedor bedrock` no se toca Ollama: el juez es un
  Qwen o un gpt-oss de Bedrock que pasa el candado de
  `agente.validar_modelo_bedrock`, sin herramientas; un Qwen con la
  configuración principal y gpt-oss con `razonador`. `--paralelo N` anota N
  ítems a la vez con las mismas salidas que en serie, `--contexto` agrega a
  cada ítem sus dos oraciones vecinas (`contexto.py`) y `--tope-usd` detiene
  la corrida antes de pasar de ese gasto (`gasto.py`).
- `contexto`: escribe las vecinas de cada ítem de una hoja, desde la llave
  del sorteo y la base, para `anotar --contexto`.
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
contesta o la corrida se detuvo (con Bedrock, también un error que sobrevivió
a los reintentos o el tope de gasto); 2 argumentos o entradas que no sirven;
3 interrumpida (lo hecho queda en la caché, y volver a correr lo retoma).
"""

import argparse
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from grn_bronce import db as bdb  # noqa: E402
from grn_comun import procedencia, rutas  # noqa: E402
from grn_ouroboros import (agente, anotar, calibracion, contexto,  # noqa: E402
                           evals, gasto, herramientas, motor, rubrica)

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


def _mostrar_bedrock(d, perfil_aws):
    log("Bedrock en %s: modelo %s, perfil de AWS %s"
        % (d["region"], d["modelo"], perfil_aws or "(el del entorno)"))


def _opciones_del_proveedor(args):
    """(modelo, región) de Bedrock, o (None, None) con Ollama; ValueError
    con la opción que no va con el proveedor pedido."""
    if args.proveedor == "ollama":
        sobran = [nombre for nombre, valor in (("--modelo", args.modelo),
                                               ("--region", args.region),
                                               ("--perfil-aws",
                                                args.perfil_aws),
                                               ("--tope-usd", args.tope_usd),
                                               ("--precios", args.precios))
                  if valor is not None]
        if sobran:
            raise ValueError("%s son de --proveedor bedrock; con ollama el "
                             "modelo es el pre-registrado (%s)."
                             % (", ".join(sobran), motor.MODELO))
        motor.validar_host(args.host)
        return None, None
    sobran = [nombre for nombre, valor in (("--semilla", args.semilla),
                                           ("--num-ctx", args.num_ctx))
              if valor is not None]
    if sobran:
        raise ValueError("%s no van con bedrock: Converse no los recibe."
                         % ", ".join(sobran))
    modelo = agente.validar_modelo_bedrock(
        agente.MODELO_BEDROCK if args.modelo is None else args.modelo)
    region = agente.validar_region(
        agente.REGION_BEDROCK if args.region is None else args.region)
    return modelo, region


def _contexto(args, items):
    """{id_item: vecinas} de `--contexto`, o None. Con `--herramientas
    todas` no va: ahí el contexto lo pide el modelo con su herramienta."""
    if args.contexto is None:
        return None
    if args.herramientas == "todas":
        raise ValueError("--contexto no va con --herramientas todas, que ya "
                         "tiene la herramienta contexto.")
    return contexto.para_hoja(items, args.contexto)


def _gasto(args, modelo):
    """(precio, tope) de Bedrock: el precio por millón (de la tabla de
    `gasto.py` o de --precios) y el `gasto.Tope` de --tope-usd, o None."""
    if args.proveedor != "bedrock":
        return None, None
    precio = gasto.precio(modelo, args.precios)
    if args.tope_usd is None:
        return precio, None
    if precio is None:
        raise ValueError("No hay precio de lista para %s en gasto.py: para "
                         "el tope, dalo con --precios ENTRADA,SALIDA (USD "
                         "por millón de tokens)." % modelo)
    return precio, gasto.Tope(args.tope_usd, precio)


def _mostrar_costo(resumen, tope):
    costo = resumen.get("costo")
    if costo:
        log("costo: US$%.4f esta corrida, US$%.4f la hoja entera (US$%s y "
            "US$%s por millón de tokens de entrada y de salida)"
            % (costo["usd_esta_corrida"], costo["usd_total"],
               costo["precio_usd_por_millon"][0],
               costo["precio_usd_por_millon"][1]))
    if tope is not None:
        log("tope de gasto: US$%.4f de US$%.2f en %d llamadas"
            % (tope.gastado, tope.usd, tope.llamadas))


def cmd_anotar(args):
    herr = args.herramientas
    bedrock = args.proveedor == "bedrock"
    try:
        anotar.validar_salida(args.salida)
        # Con bedrock no se toca Ollama: ni el host ni el digest.
        modelo, region = _opciones_del_proveedor(args)
        agente.validar_paralelo(args.paralelo, args.proveedor)
        items = calibracion.leer_hoja(args.hoja)
        config = agente.configuracion(args.config, semilla=args.semilla,
                                      num_ctx=args.num_ctx,
                                      kv_cache=args.kv_cache,
                                      razonamiento=args.razonamiento)
        agente.validar_bedrock(config, herr, args.proveedor)
        if bedrock:
            agente.validar_modelo_y_config(modelo, config)
        prompt = agente.leer_prompt(args.prompt)
        recursos = _recursos(args, items)
        vecinas = _contexto(args, items)
        precio, tope = _gasto(args, modelo)
    except (ValueError, OSError, bdb.ErrorBase, motor.ErrorMotor) as e:
        log("ERROR: %s" % e)
        return ENTRADA
    if bedrock:
        descripcion = agente.describir_bedrock(modelo, region)
        _mostrar_bedrock(descripcion, args.perfil_aws)
    else:
        try:
            descripcion = motor.exigir(motor.describir(args.host))
        except motor.ErrorMotor as e:
            log("ERROR: %s" % e)
            return FALLA
        _mostrar_modelo(descripcion)
    try:
        if bedrock:
            anotador = agente.crear_anotador(
                config, prompt, herramientas=herr, recursos=recursos,
                modelo=modelo, proveedor="bedrock", region=region,
                perfil_aws=args.perfil_aws)
        else:
            anotador = agente.crear_anotador(config, prompt, host=args.host,
                                             herramientas=herr,
                                             recursos=recursos)
    except ImportError:
        log("ERROR: %s" % SIN_STRANDS)
        return ENTRADA
    except ValueError as e:
        # Un perfil de AWS que no existe o sin credenciales.
        log("ERROR: %s" % e)
        return ENTRADA
    con_contexto = vecinas is not None
    decodificacion = agente.decodificacion(config, herr, args.proveedor)
    entradas = anotar.armar_entradas(
        descripcion, decodificacion,
        agente.huella_prompt(prompt, herr, con_contexto), herr,
        recursos.huellas(herr) if recursos else {})
    configuracion = dict(config, herramientas=herr,
                         prompt=os.path.basename(args.prompt))
    if con_contexto:
        # Las vecinas de cada ítem entran a su llave; el archivo, a las
        # entradas, para que otra carpeta de contexto no se mezcle.
        entradas["contexto"] = {"plantilla": "vecinas",
                                "archivo": procedencia.huella(args.contexto)}
        configuracion["contexto"] = os.path.basename(args.contexto)
    paquetes = anotar.PAQUETES
    if bedrock:
        # Lo que se mandó, no lo que la configuración de Ollama decía: la
        # semilla, num_ctx y la caché KV no llegan a Converse.
        configuracion = dict(decodificacion, herramientas=herr,
                             prompt=os.path.basename(args.prompt),
                             proveedor="bedrock", model_id=modelo,
                             region=region, paralelo=args.paralelo)
        if con_contexto:
            configuracion["contexto"] = os.path.basename(args.contexto)
        if tope is not None:
            configuracion["tope_usd"] = tope.usd
        paquetes = anotar.PAQUETES + agente.PAQUETES_BEDROCK
        modo = ("razonamiento %s" % config["razonamiento"]
                if config.get("razonamiento") else "sin think")
        log("Anotando %d ítems con Bedrock: %s (%s, T %s, max_tokens %d, "
            "formato en el prompt), herramientas: %s, %d a la vez%s."
            % (len(items), config["nombre"], modo, config["temperature"],
               decodificacion["max_tokens"], herr, args.paralelo,
               ", con contexto" if con_contexto else ""))
        if precio is not None:
            texto_sistema = agente.sistema(prompt, herr)

            def medir(item):
                return len(texto_sistema) + len(agente.mensaje(item))

            medibles = [dict(it, contexto=vecinas[it["id_item"]])
                        if con_contexto else it for it in items]
            log("costo máximo si nada saliera de la caché: US$%.2f"
                % gasto.cota_de_la_corrida(medibles, medir,
                                           decodificacion["max_tokens"],
                                           precio))
            if tope is not None:
                anotador = gasto.con_tope(anotador, tope, medir,
                                          decodificacion["max_tokens"])
    else:
        log("Anotando %d ítems: %s (%s, T %s, semilla %d, num_ctx %d, "
            "num_predict %d, caché KV %s), herramientas: %s%s."
            % (len(items), config["nombre"],
               "con think" if config["think"] else "sin think",
               config["temperature"], config["seed"], config["num_ctx"],
               config["num_predict"], config["kv_cache"], herr,
               ", con contexto" if con_contexto else ""))
    try:
        r = anotar.ejecutar(
            args.hoja, args.salida, anotador, entradas,
            configuracion=configuracion, descripcion=descripcion, log=log,
            paralelo=args.paralelo, paquetes=paquetes, contexto=vecinas,
            precio=precio)
    except anotar.CarpetaOcupada as e:
        log("ERROR: %s" % e)
        return ENTRADA
    except KeyboardInterrupt:
        log("Interrumpida. Lo hecho queda en %s, y volver a correr lo retoma."
            % anotar.VEREDICTOS)
        return INTERRUMPIDA
    except gasto.TopeAlcanzado as e:
        log("ALTO: %s Lo hecho queda en %s, y volver a correr con un tope "
            "mayor lo retoma sin pagarlo otra vez." % (e, anotar.VEREDICTOS))
        _mostrar_costo({}, tope)
        return FALLA
    except Exception as e:
        # Solo el tipo: el mensaje de una excepción del cliente o de Strands
        # puede traer el texto de la petición, que lleva la oración.
        log("ERROR: la corrida se detuvo (%s). Lo hecho queda en %s, y volver "
            "a correr lo retoma." % (type(e).__name__, anotar.VEREDICTOS))
        return FALLA
    _mostrar_conteos(r["resumen"])
    _mostrar_costo(r["resumen"], tope)
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
        corrida = anotar.leer_corrida(args.salida,
                                      ruta_contexto=args.contexto)
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


# ------------------------------------------------------------ contexto

def cmd_contexto(args):
    """Las vecinas de cada ítem, desde la llave y la base. Imprime conteos y
    la huella del archivo, nunca una oración."""
    try:
        anotar.validar_salida(args.salida)
        items = calibracion.leer_hoja(args.hoja)
        recursos = herramientas.Recursos(
            ruta_llave=args.llave, ruta_db=args.db or rutas.ruta("grn.db"),
            corrida_bronce=args.corrida_bronce)
        carpeta = os.path.dirname(os.path.abspath(args.salida))
        os.makedirs(carpeta, exist_ok=True)
        contexto.ejecutar(items, recursos, args.salida, log=log)
    except (ValueError, OSError, bdb.ErrorBase) as e:
        log("ERROR: %s" % e)
        return ENTRADA
    log("Escrito %s (huella %s)." % (os.path.basename(args.salida),
                                     procedencia.huella(args.salida)))
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
                    help="El prompt del sistema; por omisión el v0, "
                         "congelado. El del jurado es "
                         "grn_ouroboros/prompts/anotador_v1.md.")
    an.add_argument("--host", default=motor.HOST,
                    help="Ollama local; por omisión %(default)s.")
    an.add_argument("--proveedor", choices=agente.PROVEEDORES,
                    default="ollama",
                    help="Dónde corre el juez: ollama, el local del servidor "
                         "(por omisión), o bedrock, un Qwen o un gpt-oss en "
                         "Amazon Bedrock con id explícito. Nunca Claude.")
    an.add_argument("--modelo", default=None,
                    help="Con bedrock, el id del modelo; por omisión %s. "
                         "Solo se aceptan los Qwen (qwen.…, us.qwen.… o "
                         "global.qwen.…) y gpt-oss (openai.gpt-oss-120b-1:0, "
                         "openai.gpt-oss-20b-1:0, con --config razonador). "
                         "Con ollama no va: el modelo es el pre-registrado."
                         % agente.MODELO_BEDROCK)
    an.add_argument("--region", default=None,
                    help="Con bedrock, la región de AWS; por omisión %s."
                         % agente.REGION_BEDROCK)
    an.add_argument("--perfil-aws", dest="perfil_aws", default=None,
                    help="Con bedrock, el perfil de la configuración de AWS "
                         "con las credenciales; por omisión, las del "
                         "entorno.")
    an.add_argument("--paralelo", type=int, default=1,
                    help="Cuántos ítems se anotan a la vez; por omisión 1. "
                         "Con ollama, solo 1: hay una sola GPU. Las salidas "
                         "no dependen de este número.")
    an.add_argument("--razonamiento", choices=agente.NIVELES_RAZONAMIENTO,
                    default=None,
                    help="Con --config razonador (gpt-oss), el nivel de "
                         "razonamiento; por omisión %s."
                         % agente.RAZONADOR["razonamiento"])
    an.add_argument("--contexto", default=None,
                    help="El CSV de `contexto` para esta hoja: cada ítem va "
                         "con su oración anterior y la siguiente.")
    an.add_argument("--tope-usd", dest="tope_usd", type=float, default=None,
                    help="Con bedrock, lo más que puede gastar esta "
                         "invocación, en USD; al llegar se detiene, y volver "
                         "a correr lo retoma.")
    an.add_argument("--precios", default=None,
                    help="Con bedrock, ENTRADA,SALIDA en USD por millón de "
                         "tokens, para un modelo sin precio en gasto.py.")
    an.set_defaults(func=cmd_anotar)

    cx = sub.add_parser("contexto",
                        help="Las oraciones vecinas de cada ítem de una "
                             "hoja, para anotar --contexto.")
    cx.add_argument("--hoja", required=True, help="La hoja sin anotar.")
    cx.add_argument("--llave", required=True,
                    help="La llave.csv del sorteo de esa hoja: de ella se "
                         "lee solo la posición de cada ítem.")
    cx.add_argument("--corrida-bronce", dest="corrida_bronce", type=int,
                    required=True,
                    help="La corrida del bronce de la que salió la muestra "
                         "(la 4 para las tandas de corrida4_run22).")
    cx.add_argument("--db", default=None,
                    help="La base; por omisión <datos>/grn.db, con datos de "
                         "GRN_DATOS o ./datos.")
    cx.add_argument("--salida", required=True,
                    help="El CSV que se escribe, bajo salidas/ouroboros/; "
                         "nunca dentro de salidas/revision.")
    cx.set_defaults(func=cmd_contexto)

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
    ev.add_argument("--contexto", default=None,
                    help="Si la corrida se hizo con --contexto, el mismo "
                         "archivo.")
    ev.set_defaults(func=cmd_evals)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
