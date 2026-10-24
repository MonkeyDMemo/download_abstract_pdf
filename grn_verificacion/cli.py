"""CLI del paso 2. Parsea, llama y formatea; la lógica vive en los módulos.

    python -m grn_verificacion.cli pares --bronce CSV --carpeta DIR [--limite N]
    python -m grn_verificacion.cli biobert --carpeta DIR --modelo DIR [--reusar-de DIR]
    python -m grn_verificacion.cli capa --carpeta DIR --bronce CSV [--sintaxis JSONL]
    python -m grn_verificacion.cli evaluar --carpeta DIR --bronce CSV [--particion DIR]
    python -m grn_verificacion.cli verificar --carpeta DIR [--datos D] [--particion P] [--contra J] [--json J] [--html H]
    python -m grn_verificacion.cli datos-entrenamiento --pares JSONL --base XLSX ...
    python -m grn_verificacion.cli reentrenar correr|estado|detener --raiz DIR ...
    python -m grn_verificacion.cli contraste --base XLSX --carpeta DIR --informe MD --confidencial DIR ...
    python -m grn_verificacion.cli tablas --base XLSX --carpeta DIR --xml DIR --informe MD --confidencial DIR [--cuantos N] ...
    python -m grn_verificacion.cli muestra --carpeta DIR --reservas TSV --n N --salida DIR [--semilla S] [--fraccion-doble F] [--tandas 1|2] [--excluir-muestra DIR ...]
    python -m grn_verificacion.cli precision-ciega --anotacion CSV --llave CSV --carpeta DIR [--json J]

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
    evaluar.evaluar_carpeta(args.carpeta, args.bronce, log=log,
                            particion=args.particion)
    return 0


def cmd_verificar(args):
    """El código de salida es el de la verificación: 0 cumple, 1 falla un
    invariante, 2 no se pudo verificar. Así un script que lo llame no tiene
    que leer el JSON para saber si puede citar las cifras."""
    from grn_verificacion import verificar
    resultado = verificar.ejecutar(
        args.carpeta, datos=args.datos, particion=args.particion,
        contra=args.contra, salida_json=args.json, salida_html=args.html,
        log=log)
    return resultado["codigo"]


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
    # Sin esto, la corrida en segundo plano usaría los valores por omisión
    # sin decirlo.
    argv += ["--semillas", args.semillas]
    for etiqueta in args.excluir_etiqueta or ():
        argv += ["--excluir-etiqueta", etiqueta]
    if args.sin_pesos_de_clase:
        argv.append("--sin-pesos-de-clase")
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
                           args.script, args.ciego, args.folds, args.hasta,
                           R.semillas_de(args.semillas),
                           R.excluir_de(args.excluir_etiqueta))
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
    try:
        semillas = R.semillas_de(args.semillas)
        excluir = R.excluir_de(args.excluir_etiqueta)
    except ValueError as e:
        error("ERROR: %s" % e)
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
            log=_nada if desprendido else log, detener=detener,
            semillas=semillas, excluir=excluir,
            pesos_clase=not args.sin_pesos_de_clase)
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
    co.add_argument("--semillas", default=R.SEMILLA_MODELO,
                    help="Semillas de la validación cruzada, separadas por "
                         "coma (el protocolo usa 42,43,44). El modelo "
                         "desplegable usa siempre la %s." % R.SEMILLA_MODELO)
    co.add_argument("--excluir-etiqueta", dest="excluir_etiqueta",
                    action="append", default=None,
                    choices=list(R.EXCLUIBLES) + ["ninguna"],
                    help="Clase que esta versión deja fuera; se puede "
                         "repetir. Por omisión %s; «ninguna» para entrenar "
                         "con todas." % ", ".join(R.EXCLUIR_POR_OMISION))
    co.add_argument("--sin-pesos-de-clase", dest="sin_pesos_de_clase",
                    action="store_true",
                    help="Entrena sin --use_class_weights (enmienda 1 del "
                         "protocolo). Usa otro --nombre: un resultado con "
                         "otros pesos no se reusa.")
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


def cmd_contraste(args):
    """Ningún error sale como traceback: uno de `zipfile` o de `open`
    traería la ruta de la base o la de la carpeta confidencial. Se dice el
    mensaje, filtrado, o solo el tipo."""
    from grn_verificacion import contraste
    if not args.base:
        log("ERROR: falta --base (o BASE_CURADA en el entorno).")
        return 2
    try:
        contraste.ejecutar(
            args.base, args.carpeta, args.confidencial, informe=args.informe,
            hoja=args.hoja, excluir=args.excluir_pmids, solo=args.solo_pmids,
            sin_red=args.sin_red, red=args.red,
            aceptar_base_distinta=args.aceptar_base_distinta, log=log)
    except KeyboardInterrupt:
        log("Interrumpido.")
        return 3
    except Exception as e:
        log("ERROR: %s" % contraste.mensaje_publicable(
            e, (args.base, args.confidencial)))
        return 1
    return 0


def _sub_contraste(sub):
    co = sub.add_parser(
        "contraste",
        help="Cobertura del bronce y recall de la red contra la base curada "
             "(PLAN.md 2.4); publica solo un informe con conteos.")
    co.add_argument("--base", default=os.environ.get("BASE_CURADA"),
                    help="Ruta del .xlsx de la base curada; por omisión "
                         "$BASE_CURADA. Nunca se imprime.")
    co.add_argument("--carpeta", required=True,
                    help="Carpeta del flujo: los CSV del bronce y, salvo con "
                         "--sin-red, red.tsv, red_evidencias.tsv y "
                         "pares.jsonl.")
    co.add_argument("--excluir-pmids", dest="excluir_pmids", action="append",
                    default=[], metavar="ARCHIVO",
                    help="PMIDs fuera del denominador, con el formato de "
                         "reservas.tsv (pmid<TAB>número), fuera del "
                         "repositorio. Se puede repetir.")
    co.add_argument("--solo-pmids", dest="solo_pmids", action="append",
                    default=[], metavar="ARCHIVO",
                    help="Para una red hecha con un modelo entrenado con la "
                         "base: el recall solo sobre estos PMIDs (los de "
                         "test). Mismo formato; se puede repetir.")
    co.add_argument("--sin-red", dest="sin_red", action="store_true",
                    help="Solo la cobertura del bronce, sin la red.")
    co.add_argument("--red", default=None, metavar="NOMBRE",
                    help="Contrasta red_NOMBRE.tsv, con sus evidencias y su "
                         "informe, en vez de red.tsv: una red con otras "
                         "reglas de grn_red.cli consolidar (recomendada es la "
                         "del paso red_recomendada del flujo). No va con "
                         "--sin-red.")
    co.add_argument("--hoja", default=None,
                    help="Nombre de la hoja de la base; por omisión, la "
                         "primera del libro.")
    co.add_argument("--aceptar-base-distinta", dest="aceptar_base_distinta",
                    action="store_true",
                    help="Seguir aunque la base no coincida con PLAN.md 2.4.")
    co.add_argument("--informe", required=True,
                    help="Dónde escribir el informe en Markdown: lo único "
                         "publicable.")
    co.add_argument("--confidencial", required=True,
                    help="Carpeta fuera de todo repositorio para lo que "
                         "deriva de la base (cobertura_por_fila.tsv, "
                         "candidatas_nuevas.tsv, contraste.json). Nunca se "
                         "imprime.")
    co.set_defaults(func=cmd_contraste)


def cmd_tablas(args):
    """Como `contraste`: ningún error sale como traceback, que traería la ruta
    de la base, la de la carpeta confidencial o el nombre de un XML, que lleva
    el PMID de uno de los artículos mayores."""
    from grn_verificacion import contraste, tablas
    if not args.base:
        log("ERROR: falta --base (o BASE_CURADA en el entorno).")
        return 2
    cuantos = tablas.CUANTOS if args.cuantos is None else args.cuantos
    try:
        tablas.ejecutar(
            args.base, args.carpeta, args.xml, args.confidencial,
            informe=args.informe, excluir=args.excluir_pmids, hoja=args.hoja,
            aceptar_base_distinta=args.aceptar_base_distinta,
            cuantos=cuantos, log=log)
    except KeyboardInterrupt:
        log("Interrumpido.")
        return 3
    except Exception as e:
        log("ERROR: %s" % contraste.mensaje_publicable(
            e, [args.base, args.confidencial, args.xml, args.carpeta,
                args.informe] + list(args.excluir_pmids)))
        return 1
    return 0


def _sub_tablas(sub):
    # Sin importar `tablas` aquí: trae el puente y `etapa2/`, y el parser se
    # arma en cada comando, también en el `reentrenar` del servidor.
    ta = sub.add_parser(
        "tablas",
        help="De las filas de la base que citan los artículos con más filas, "
             "cuántas tienen sus dos locus en una tabla del XML y cuántas en "
             "el texto (PLAN.md 3.4, punto 27); publica solo conteos.")
    ta.add_argument("--base", default=os.environ.get("BASE_CURADA"),
                    help="Ruta del .xlsx de la base curada; por omisión "
                         "$BASE_CURADA. Nunca se imprime.")
    ta.add_argument("--carpeta", required=True,
                    help="Carpeta del flujo: los dos CSV del bronce "
                         "(candidatas y menciones).")
    ta.add_argument("--xml", required=True,
                    help="Carpeta con los XML de PMC, <pmid>_<pmcid>.xml: "
                         "la subcarpeta xml de la salida de `cli.py fulltext "
                         "--tipo xml`, o una copia suya.")
    ta.add_argument("--excluir-pmids", dest="excluir_pmids", action="append",
                    default=[], metavar="ARCHIVO",
                    help="PMIDs fuera del denominador, como en contraste "
                         "(pmid<TAB>número), fuera del repositorio. Se puede "
                         "repetir.")
    ta.add_argument("--cuantos", type=int, default=None,
                    help="Cuántos artículos, de más filas exigibles a menos. "
                         "Por omisión, los de la concentración del contraste.")
    ta.add_argument("--hoja", default=None,
                    help="Nombre de la hoja de la base; por omisión, la "
                         "primera del libro.")
    ta.add_argument("--aceptar-base-distinta", dest="aceptar_base_distinta",
                    action="store_true",
                    help="Seguir aunque la base no coincida con PLAN.md 2.4.")
    ta.add_argument("--informe", required=True,
                    help="Dónde escribir el informe en Markdown (TABLAS.md): "
                         "lo único publicable.")
    ta.add_argument("--confidencial", required=True,
                    help="Carpeta fuera de todo repositorio para tablas.json. "
                         "Nunca se imprime.")
    ta.set_defaults(func=cmd_tablas)


def cmd_muestra(args):
    """Solo conteos: el módulo nunca le pasa una oración a `log`."""
    from grn_verificacion import muestra
    try:
        muestra.ejecutar(args.carpeta, args.reservas, args.n, args.salida,
                         semilla=args.semilla,
                         fraccion_doble=args.fraccion_doble,
                         tandas=args.tandas,
                         excluir_muestras=args.excluir_muestra, log=log)
    except (ValueError, OSError) as e:
        log("ERROR: %s" % e)
        return 1
    return 0


def _sub_muestra(sub):
    from grn_verificacion import muestra
    mu = sub.add_parser(
        "muestra",
        help="Sortea la muestra ciega de anotación con ayudantes "
             "(docs/rubrica-anotacion.md, §6 a §8): las dos hojas, la llave "
             "y el resumen.")
    mu.add_argument("--carpeta", required=True,
                    help="Carpeta del flujo con capa_pares.csv.")
    mu.add_argument("--reservas", required=True,
                    help="reservas.tsv: la muestra de 50 y el conjunto "
                         "ciego, que no entran.")
    mu.add_argument("--n", type=int, required=True,
                    help="Cuántos ítems se sortean.")
    mu.add_argument("--salida", required=True,
                    help="Carpeta para hoja_tanda1.csv, "
                         "hoja_tanda2_ciega.csv, llave.csv y resumen.json.")
    mu.add_argument("--semilla", type=int, default=muestra.SEMILLA,
                    help="Por omisión, %(default)s.")
    mu.add_argument("--fraccion-doble", dest="fraccion_doble", type=float,
                    default=muestra.FRACCION_DOBLE,
                    help="Fracción de cada tanda que anotan dos personas; "
                         "por omisión, %(default)s.")
    mu.add_argument("--tandas", type=int, choices=(1, 2),
                    default=muestra.TANDAS,
                    help="En cuántas hojas se reparte la muestra: 1, toda en "
                         "hoja_tanda1.csv; 2, la mitad en hoja_tanda1.csv y "
                         "la otra en hoja_tanda2_ciega.csv. Solo reparte: "
                         "con 1 o con 2 salen los mismos ítems. Por "
                         "omisión, %(default)s.")
    mu.add_argument("--excluir-muestra", dest="excluir_muestra",
                    action="append", default=None, metavar="DIR",
                    help="Carpeta de un sorteo anterior sobre la misma "
                         "capa, con su llave.csv: ni sus artículos (por "
                         "PMID), ni sus oraciones copiadas en otros, ni sus "
                         "id_item salen en este, como pide una tanda de "
                         "prueba. Se puede repetir.")
    mu.set_defaults(func=cmd_muestra)


def cmd_precision_ciega(args):
    """Solo cifras: ni oraciones ni PMIDs pasan por `log`."""
    from grn_verificacion import precision_ciega
    try:
        precision_ciega.ejecutar(args.anotacion, args.llave, args.carpeta,
                                 args.json, log=log, red=args.red,
                                 excluir=args.excluir_pmids,
                                 particion=args.particion, capa=args.capa,
                                 etiqueta=args.etiqueta)
    except (ValueError, OSError, KeyError) as e:
        log("ERROR: %s" % e)
        return 1
    return 0


def _sub_precision_ciega(sub):
    pc = sub.add_parser(
        "precision-ciega",
        help="Precisión pareada del bronce y de la red final sobre la "
             "muestra ciega anotada, con la retención de la red.")
    pc.add_argument("--anotacion", required=True,
                    help="La hoja anotada, o el CSV que exporta la página de "
                         "revisión.")
    pc.add_argument("--llave", required=True,
                    help="llave.csv del sorteo: une cada id_item con su par.")
    pc.add_argument("--carpeta", required=True,
                    help="Carpeta del flujo: capa_pares.csv, red.tsv y "
                         "red_evidencias.tsv.")
    pc.add_argument("--json", help="Escribe ahí el resultado completo.")
    pc.add_argument("--red", default=None, metavar="NOMBRE",
                    help="Mide la red con otras reglas red_NOMBRE.tsv "
                         "(grn_red consolidar) en vez de red.tsv; sus "
                         "aristas expandidas no se leen.")
    pc.add_argument("--capa", default=None, metavar="RUTA",
                    help="El capa_pares.csv de la llave; por omisión, el de "
                         "--carpeta. Para medir la carpeta de otro modelo con "
                         "la capa del sorteo.")
    pc.add_argument("--excluir-pmids", dest="excluir_pmids", action="append",
                    default=[], metavar="ARCHIVO",
                    help="PMIDs con el formato de reservas.tsv "
                         "(pmid<TAB>número): sus ítems salen de todo, bronce "
                         "y red. Se puede repetir.")
    pc.add_argument("--particion", default=None, metavar="DIR",
                    help="Carpeta con los entity_marked_*.jsonl del modelo: "
                         "los ítems de artículos de train o dev salen de "
                         "todo, y se cuenta cuántos de los demás tienen su "
                         "oración en train. Solo conteos.")
    pc.add_argument("--etiqueta", default=None, metavar="TEXTO",
                    help="Texto libre que solo se guarda en el JSON (por "
                         "ejemplo, tanda2).")
    pc.set_defaults(func=cmd_precision_ciega)


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
    ev.add_argument("--particion", default=None, metavar="DIR",
                    help="Carpeta con los entity_marked_{train,dev}.jsonl del "
                         "modelo: separa el P1 de las 50 en par visto y par "
                         "no visto al entrenar. Solo conteos.")
    ev.set_defaults(func=cmd_evaluar)

    vf = sub.add_parser(
        "verificar",
        help="Verifica una carpeta del flujo contra la base, en solo lectura: "
             "cinco invariantes, el embudo y las métricas, en un JSON y un "
             "HTML que se pueden publicar.")
    vf.add_argument("--carpeta", required=True,
                    help="La carpeta del flujo (salidas/flujo/corridaN_...).")
    vf.add_argument("--datos", default=None,
                    help="Raíz de datos; gana sobre GRN_DATOS.")
    vf.add_argument("--particion", default=None,
                    help="Carpeta con los entity_marked_{train,dev,test}.jsonl "
                         "con que se entrenó el checkpoint: comprueba que no "
                         "haya fuga hacia train (I3).")
    vf.add_argument("--contra", default=None,
                    help="Otro verificacion.json, para decir qué cambió.")
    vf.add_argument("--json", default=None,
                    help="Dónde escribir el JSON; por omisión, "
                         "verificacion.json en la carpeta.")
    vf.add_argument("--html", default=None,
                    help="Dónde escribir el informe HTML autocontenido.")
    vf.set_defaults(func=cmd_verificar)

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
    _sub_contraste(sub)
    _sub_tablas(sub)
    _sub_muestra(sub)
    _sub_precision_ciega(sub)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
