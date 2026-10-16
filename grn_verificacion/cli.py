"""CLI del paso 2. Parsea, llama y formatea; la lógica vive en los módulos.

    python -m grn_verificacion.cli pares --bronce CSV --carpeta DIR [--limite N]
    python -m grn_verificacion.cli biobert --carpeta DIR --modelo DIR [--reusar-de DIR]
    python -m grn_verificacion.cli capa --carpeta DIR --bronce CSV [--sintaxis JSONL]
    python -m grn_verificacion.cli evaluar --carpeta DIR --bronce CSV
    python -m grn_verificacion.cli datos-entrenamiento --pares JSONL --base XLSX ...
    python -m grn_verificacion.cli reentrenar correr|estado|detener --raiz DIR ...

Lo normal es no llamarlo a mano: `python flujo.py` corre los pasos en orden y
se salta lo que ya está hecho.
"""

import argparse
import json
import os
import re
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

log = print


def _etiqueta_modelo(modelo):
    nombre = os.path.basename(os.path.normpath(modelo))
    m = re.search(r"run_?(\d+)", nombre)
    return "run%s" % m.group(1) if m else nombre


def _rel(ruta):
    """Relativa a la raíz, con `/`; absoluta si está en otra unidad de
    Windows, donde `os.path.relpath` lanza ValueError y tumbaba el paso."""
    absoluta = os.path.abspath(ruta)
    try:
        return os.path.relpath(absoluta, _RAIZ).replace(os.sep, "/")
    except ValueError:
        return absoluta.replace(os.sep, "/")


def cmd_pares(args):
    from grn_verificacion import puente
    puente.construir_pares(args.bronce, args.carpeta, limite=args.limite,
                           log=log)
    return 0


def _corrida_bronce_de(carpeta):
    with open(os.path.join(carpeta, "pares.jsonl"), encoding="utf-8") as f:
        for linea in f:
            if linea.strip():
                return json.loads(linea).get("corrida_bronce")
    return None


def cmd_biobert(args):
    from grn_bronce import db as bdb, rutas
    from grn_verificacion import puente

    modelo = os.path.abspath(args.modelo)
    reusar = args.reusar_de or []
    # Una sola vez: huellea los pesos (cientos de MB).
    firma = puente.firma_del_modelo(modelo)
    con = None
    corrida_id = None
    if not args.sin_registrar:
        # Toda corrida de procesamiento deja su fila ANTES de procesar
        # (CLAUDE.md). Es una fila del paso 2 en la misma tabla `corridas`:
        # `ultima_corrida()` filtra por paso, así que no confunde al bronce.
        corrida_bronce = _corrida_bronce_de(args.carpeta)
        con = bdb.conectar(os.path.join(rutas.raiz_datos(args.datos),
                                        "grn.db"))
        fila_bronce = bdb.corrida(con, corrida_bronce) \
            if corrida_bronce is not None else None
        # El método dice «run22» para cualquier checkpoint de esa receta; lo
        # que distingue a uno de otro es la firma, con la huella de los pesos.
        corrida_id = bdb.abrir_corrida(
            con, "2", "biobert-%s" % _etiqueta_modelo(modelo), "1",
            {"corrida_bronce": corrida_bronce,
             "modelo": _rel(modelo),
             "sha1_config": firma["sha1_config"],
             "huellas_modelo": firma["huellas_modelo"],
             "carpeta": _rel(args.carpeta),
             "umbrales": {"activates": 0.65, "represses": 0.70,
                          "regulates": 0.60},
             "reusar_de": [_rel(d) for d in reusar],
             "sin_cache": bool(args.sin_cache)},
            fila_bronce["corpus_id"] if fila_bronce is not None else None)
        log("Corrida %d del paso 2 registrada." % corrida_id)
    try:
        r = puente.clasificar_pares(args.carpeta, modelo, python=args.python,
                                    reusar_de=reusar, log=log,
                                    usar_cache=not args.sin_cache,
                                    firma=firma)
    except BaseException as e:
        if con is not None:
            bdb.cerrar_corrida(con, corrida_id, "error", str(e))
            con.close()
        raise
    if con is not None:
        n = r.get("reutilizadas", 0) + r.get("nuevas", 0)
        bdb.cerrar_corrida(con, corrida_id, "ok", None, n, n)
        con.close()
    log("Reutilizadas %d, clasificadas %d." % (r.get("reutilizadas", 0),
                                               r.get("nuevas", 0)))
    return 0


def cmd_capa(args):
    from grn_verificacion import capa
    capa.escribir_capa(args.carpeta, args.bronce, ruta_sintaxis=args.sintaxis,
                       log=log)
    return 0


def cmd_evaluar(args):
    from grn_verificacion import evaluar
    evaluar.evaluar_carpeta(args.carpeta, args.bronce, log=log)
    return 0


def cmd_datos_entrenamiento(args):
    from grn_verificacion import entrenamiento
    # `ejecutar` ya reporta por `log`, y solo conteos: la base curada y lo que
    # sale de ella no se imprimen nunca.
    try:
        entrenamiento.desde_argumentos(args, log=log)
    except ValueError as e:
        log("ERROR: %s" % e)
        return 1
    return 0


def cmd_reservas(args):
    """El archivo de lo que no entra al entrenamiento: los PMIDs y las
    oraciones de la muestra de 50 juicios (con ella se recalcula el 44 %) y,
    si se da, las oraciones del conjunto ciego de la trampa del signo."""
    import csv
    from grn_bronce.texto import normalizar_espacios
    from grn_verificacion import entrenamiento
    oraciones = []
    if args.ciego:
        # El conjunto ciego es un TSV con columna `oracion`; se reserva por
        # oración porque no trae PMID.
        with open(args.ciego, encoding="utf-8-sig", newline="") as f:
            for fila in csv.DictReader(f, delimiter="	"):
                texto = normalizar_espacios(fila.get("oracion") or "")
                if texto:
                    oraciones.append(texto)
    os.makedirs(os.path.dirname(os.path.abspath(args.salida)), exist_ok=True)
    # Se reporta lo que quedó escrito, no lo leído: la muestra de 50 juicios
    # trae 46 PMIDs distintos y 50 oraciones, y las 198 filas del conjunto
    # ciego son 182 oraciones distintas. Son las cifras que va a repetir
    # `datos-entrenamiento` (46 PMIDs; 232 oraciones).
    escritas = entrenamiento.escribir_reservas_de_juicios(
        args.salida, oraciones_extra=oraciones)
    log("Reservas escritas en %s: %d PMIDs y %d oraciones distintas (las de "
        "la muestra de juicios más %d distintas del conjunto ciego, de %d "
        "filas)." % (args.salida, escritas["pmids"], escritas["oraciones"],
                     len(set(oraciones)), len(oraciones)))
    return 0


def _ruta(valor):
    return os.path.abspath(os.path.expanduser(valor)) if valor else valor


def _argv_correr(args):
    """La misma corrida para relanzarla desprendida: rutas absolutas, porque
    el proceso nuevo arranca en la raíz del repositorio. Sin `--base` ni
    `--hoja`: viajan en el entorno (ver `reentrenar.desprender`)."""
    argv = ["reentrenar", "correr", "--raiz", _ruta(args.raiz),
            "--nombre", args.nombre,
            "--pares", _ruta(args.pares), "--script", _ruta(args.script),
            "--hasta", args.hasta, "--horas", repr(args.horas),
            "--gpu-min-mib", str(args.gpu_min_mib),
            "--max-length", str(args.max_length)]
    for ruta in args.reservar:
        argv += ["--reservar", _ruta(ruta)]
    if args.python:
        # Un nombre suelto se busca en el PATH; una ruta relativa se rompía al
        # arrancar el hijo en otra carpeta.
        argv += ["--python", _ruta(args.python) if os.sep in args.python
                 else args.python]
    if args.ciego:
        argv += ["--ciego", _ruta(args.ciego)]
    if args.folds is not None:
        argv += ["--folds", str(args.folds)]
    if args.aceptar_base_distinta:
        argv.append("--aceptar-base-distinta")
    if args.conservar_checkpoints:
        argv.append("--conservar-checkpoints")
    return argv


# Cuánto espera `--desprender` antes de devolver la terminal: si el proceso
# ya murió (un argumento malo, el candado tomado), se dice aquí y no hay que ir
# a buscarlo al estado.
ESPERA_DESPRENDER = 5


def _raiz_mostrable(raiz):
    """La raíz para imprimirla: con el home como `~`, o `<raiz>`. El shell ya
    expandió `~/grn-guillermo`, y la ruta absoluta lleva la cuenta."""
    raiz = os.path.abspath(os.path.expanduser(raiz))
    casa = os.path.expanduser("~")
    if raiz == casa or raiz.startswith(casa + os.sep):
        return os.path.join("~", os.path.relpath(raiz, casa))
    return "<raiz>"


def cmd_reentrenar(args):
    """Ningún error sale como traceback: traería rutas del servidor sin
    filtrar. Se dice el tipo y el mensaje filtrado."""
    from grn_verificacion import reentrenar as R
    try:
        return _cmd_reentrenar(args, R)
    except KeyboardInterrupt:
        log("Interrumpido.")
        return 3
    except Exception as e:
        try:
            mensaje = R.Saneador(R.rutas(args.raiz, args.nombre)).linea(str(e))
        except Exception:
            mensaje = None
        log("ERROR: %s%s" % (type(e).__name__,
                             ": %s" % mensaje if mensaje else ""))
        return 1


def _nada(_):
    pass


def _a_stderr(linea):
    print(linea, file=sys.stderr, flush=True)


def _desprender(args, R, subprocess):
    """Lanza la corrida en segundo plano y espera unos segundos.

    Lo que se puede comprobar antes se comprueba aquí: en segundo plano, un
    error se perdía y quien lanzó veía el estado de la corrida ANTERIOR.
    """
    try:
        R.validar_entradas(args.nombre, args.base, args.pares, args.reservar,
                           args.script, args.ciego, args.folds, args.hasta)
    except ValueError as e:
        log("ERROR: %s" % e)
        return 2
    r = R.rutas(args.raiz, args.nombre)
    pid = R.quien_corre(r["candado"])
    if pid:
        log("ERROR: ya corre una corrida %s (PID %s). Mírala con "
            "`reentrenar estado` o detenla con `reentrenar detener`."
            % (args.nombre, pid))
        return 4
    desde = os.path.getsize(r["err"]) if os.path.isfile(r["err"]) else 0
    proc = R.desprender(_argv_correr(args), args.raiz, args.nombre,
                        base=args.base, hoja=args.hoja)
    seguir = ("  python -m grn_verificacion.cli reentrenar %%s --raiz %s "
              "--nombre %s" % (_raiz_mostrable(args.raiz), args.nombre))
    try:
        codigo = proc.wait(timeout=ESPERA_DESPRENDER)
    except subprocess.TimeoutExpired:
        log("Lanzada la corrida %s en segundo plano (PID %d). Sobrevive "
            "a un corte de SSH. Sigue con:" % (args.nombre, proc.pid))
        log(seguir % "estado")
        return 0
    except KeyboardInterrupt:
        # Ctrl-C aquí no detiene nada: el proceso ya está en su propia sesión.
        log("La corrida %s sigue en segundo plano (PID %d). Para detenerla:"
            % (args.nombre, proc.pid))
        log(seguir % "detener")
        return 3
    if codigo == 0:
        for linea in R.resumen_estado(args.raiz, args.nombre):
            log(linea)
        return 0
    log("La corrida %s terminó al arrancar, con código %d. Lo que dijo:"
        % (args.nombre, codigo))
    san = R.Saneador(r)
    with open(r["err"], encoding="utf-8", errors="replace") as f:
        f.seek(desde)
        for linea in f.read().splitlines()[-20:]:
            limpia = san.linea(linea)
            if limpia:
                log("  " + limpia)
    return codigo


def _cmd_reentrenar(args, R):
    import signal
    import subprocess
    import threading

    if args.accion == "estado":
        for linea in R.resumen_estado(args.raiz, args.nombre, args.lineas):
            log(linea)
        return 0
    if args.accion == "detener":
        r = R.detener_corrida(args.raiz, args.nombre, esperar=args.esperar)
        if r["pid"]:
            log("Detenida la corrida %s (PID %s)%s." % (
                args.nombre, r["pid"], ", a la fuerza" if r["forzado"] else ""))
        else:
            log("No había ninguna corrida %s en marcha." % args.nombre)
        if r["huerfanos"]:
            log("Además se detuvieron %d procesos huérfanos." % r["huerfanos"])
        return 0

    # En segundo plano la salida estándar va a /dev/null y lo que cuenta ya
    # está en el log filtrado; los ERROR van a stderr, que es reentrenar.err.
    desprendido = os.environ.get(R.DESPRENDIDO) == "1"
    error = _a_stderr if desprendido else log

    faltan = [f for f, v in (("--base", args.base), ("--script", args.script))
              if not v]
    if faltan:
        error("ERROR: falta %s (o BASE_CURADA / SCRIPT_ASESOR en el entorno)."
              % " y ".join(faltan))
        return 2
    if args.desprender:
        return _desprender(args, R, subprocess)

    detener = threading.Event()
    senales = {"n": 0}

    def al_recibir(numero, marco):
        # Sin print aquí: un print dentro del manejador puede reventar con
        # «reentrant call». La primera señal pide detener con orden; la
        # segunda corta por las malas, y `proceso.correr` mata el árbol.
        senales["n"] += 1
        detener.set()
        if senales["n"] > 1:
            raise KeyboardInterrupt

    anteriores = {}
    for nombre in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, nombre):
            numero = getattr(signal, nombre)
            # Lo que llegó ignorado se queda ignorado: `nohup` ignora SIGHUP,
            # y capturarla anulaba el nohup y cancelaba la corrida al cortarse
            # el SSH.
            if signal.getsignal(numero) is signal.SIG_IGN:
                continue
            anteriores[numero] = signal.signal(numero, al_recibir)
    try:
        estado = R.ejecutar(
            args.raiz, args.nombre, args.base, args.pares, args.reservar,
            args.script, python=args.python, ciego=args.ciego,
            folds=args.folds, hasta=args.hasta,
            aceptar_base_distinta=args.aceptar_base_distinta,
            horas=args.horas, gpu_min_mib=args.gpu_min_mib,
            max_length=args.max_length,
            conservar_checkpoints=args.conservar_checkpoints, hoja=args.hoja,
            log=_nada if desprendido else log, detener=detener)
    except R.Ocupado as e:
        error("ERROR: ya corre una corrida %s (PID %s). Mírala con "
              "`reentrenar estado` o detenla con `reentrenar detener`."
              % (args.nombre, e.pid))
        return 4
    except R.ErrorReentreno as e:
        error("ERROR: %s" % e.detalle)
        return 1
    except ValueError as e:
        error("ERROR: %s" % e)
        return 2
    finally:
        for numero, anterior in anteriores.items():
            signal.signal(numero, anterior)
    motivo = estado.get("motivo")
    log("Corrida %s: %s%s. Informe: <resultados>/RESULTADOS.md" % (
        args.nombre, estado["estatus"], " (%s)" % motivo if motivo else ""))
    return {"ok": 0, "cancelado": 3}.get(estado["estatus"], 1)


def _sub_reentrenar(sub):
    from grn_verificacion import reentrenar as R
    re_ = sub.add_parser(
        "reentrenar",
        help="Pista D de punta a punta en el servidor: datos, partición por "
             "PMID y run 22, desprendible y con informe sin contenido.")
    acciones = re_.add_subparsers(dest="accion", required=True)

    def comunes(p):
        p.add_argument("--raiz", required=True,
                       help="Carpeta propia en el servidor (~/grn-guillermo); "
                            "ahí quedan datos/, runs/ y resultados/.")
        p.add_argument("--nombre", default="curada-v1",
                       help="Nombre de la corrida. Por omisión curada-v1.")

    co = acciones.add_parser("correr", help="Corre (o retoma) la corrida.")
    comunes(co)
    co.add_argument("--base", default=os.environ.get("BASE_CURADA"),
                    help="Ruta del .xlsx de la base curada; por omisión "
                         "$BASE_CURADA. Nunca se imprime.")
    co.add_argument("--pares", required=True,
                    help="pares.jsonl del puente (corpus público).")
    co.add_argument("--reservar", action="append", default=[],
                    metavar="ARCHIVO", required=True,
                    help="Archivo de reservas; se puede repetir.")
    co.add_argument("--script", default=os.environ.get("SCRIPT_ASESOR"),
                    help="bio_bert_re_finetune.py del asesor; por omisión "
                         "$SCRIPT_ASESOR.")
    co.add_argument("--python", default=None,
                    help="Intérprete con torch y transformers; por omisión "
                         "$GRN_PYTHON_BERT o el que corre esto.")
    co.add_argument("--ciego", default=None,
                    help="TSV del conjunto ciego (columnas tf y blanco): "
                         "cuenta cuánto de sus pares entró.")
    co.add_argument("--hoja", default=os.environ.get(
                        "GRN_REENTRENAR_HOJA"),
                    help="Nombre de la hoja de la base; por omisión la "
                         "primera.")
    co.add_argument("--folds", type=int, default=None,
                    help="Además, validación cruzada de K pliegues.")
    co.add_argument("--hasta", choices=R.HASTA, default="entrenamiento",
                    help="Último paso: datos, particion o entrenamiento.")
    co.add_argument("--aceptar-base-distinta", dest="aceptar_base_distinta",
                    action="store_true",
                    help="Seguir aunque la base no coincida con PLAN.md 2.4.")
    co.add_argument("--horas", type=float, default=R.HORAS,
                    help="Tope por entrenamiento. Por omisión %s." % R.HORAS)
    co.add_argument("--gpu-min-mib", dest="gpu_min_mib", type=int,
                    default=R.GPU_MIN_MIB,
                    help="Memoria libre mínima de la GPU para lanzar.")
    co.add_argument("--max-length", dest="max_length", default=R.MAX_LENGTH,
                    help="Techo de tokens del script. Por omisión %s."
                         % R.MAX_LENGTH)
    co.add_argument("--conservar-checkpoints", dest="conservar_checkpoints",
                    action="store_true",
                    help="No borrar los checkpoint-* al terminar.")
    co.add_argument("--desprender", action="store_true",
                    help="Correr en segundo plano, en su propia sesión: "
                         "sobrevive a un corte de SSH.")
    co.set_defaults(func=cmd_reentrenar)

    es = acciones.add_parser("estado", help="Cómo va la corrida.")
    comunes(es)
    es.add_argument("--lineas", type=int, default=15)
    es.set_defaults(func=cmd_reentrenar)

    de = acciones.add_parser("detener", help="Detiene la corrida.")
    comunes(de)
    de.add_argument("--esperar", type=float, default=60.0)
    de.set_defaults(func=cmd_reentrenar)


def consola_tolerante():
    """La consola de Windows imprime cp1252: los acentos caben, pero la barra
    de progreso de transformers («█») o una sigma no, y un `print` con ellos
    tumbaba la corrida entera desde el padre. Se reemplaza lo que no cabe en
    vez de reventar; los archivos de datos se escriben siempre en UTF-8."""
    for flujo_salida in (sys.stdout, sys.stderr):
        if hasattr(flujo_salida, "reconfigure"):
            flujo_salida.reconfigure(errors="replace")


def main(argv=None):
    consola_tolerante()
    ap = argparse.ArgumentParser(prog="grn_verificacion.cli",
                                 description="Paso 2: verificación.")
    sub = ap.add_subparsers(dest="sub", required=True)

    pa = sub.add_parser("pares", help="Pares marcados desde el bronce.")
    pa.add_argument("--bronce", required=True,
                    help="CSV de oraciones candidatas del bronce.")
    pa.add_argument("--carpeta", required=True)
    pa.add_argument("--limite", type=int, default=None)
    pa.set_defaults(func=cmd_pares)

    bb = sub.add_parser("biobert", help="Clasificar los pares con BioBERT.")
    bb.add_argument("--carpeta", required=True)
    bb.add_argument("--modelo", required=True)
    bb.add_argument("--python", default=None,
                    help="Intérprete con torch y transformers.")
    bb.add_argument("--reusar-de", dest="reusar_de", action="append",
                    help="Carpeta con predicciones del mismo modelo.")
    bb.add_argument("--datos", default=None,
                    help="Raíz de datos; gana sobre GRN_DATOS.")
    bb.add_argument("--sin-registrar", dest="sin_registrar",
                    action="store_true",
                    help="No dejar fila en `corridas` (pruebas rápidas).")
    bb.add_argument("--sin-cache", dest="sin_cache", action="store_true",
                    help="Clasificar todo de nuevo: ni las predicciones de "
                         "la carpeta, ni su caché, ni otras carpetas.")
    bb.set_defaults(func=cmd_biobert)

    ca = sub.add_parser("capa", help="La capa: oración, funciones, operones "
                                     "y BioBERT.")
    ca.add_argument("--carpeta", required=True)
    ca.add_argument("--bronce", required=True)
    ca.add_argument("--sintaxis", default=None)
    ca.set_defaults(func=cmd_capa)

    ev = sub.add_parser("evaluar", help="Recalcula el 44 %% con BioBERT.")
    ev.add_argument("--carpeta", required=True)
    ev.add_argument("--bronce", required=True)
    ev.set_defaults(func=cmd_evaluar)

    from grn_verificacion import entrenamiento
    de = sub.add_parser("datos-entrenamiento",
                        help="Datos de entrenamiento desde la base curada "
                             "(se corre en la máquina donde vive la base).")
    entrenamiento.agregar_argumentos(de)
    de.set_defaults(func=cmd_datos_entrenamiento)

    rs = sub.add_parser("reservas",
                        help="Lo que no entra al entrenamiento: la muestra "
                             "de 50 y el conjunto ciego.")
    rs.add_argument("--salida",
                    default=os.path.join("salidas", "flujo", "reservas.tsv"))
    rs.add_argument("--ciego", default=None,
                    help="TSV con columna `oracion`: el conjunto ciego de la "
                         "trampa del signo, versionado en etapa2/.")
    rs.set_defaults(func=cmd_reservas)

    _sub_reentrenar(sub)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
