#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Une el juicio humano con la muestra y reporta las dos cifras.

    python3 etapa2/unir_juicios.py

Lee `salidas/muestra_precision_50.csv` --lo que el bronce afirma, incluido el
`signo_sugerido`-- y `salidas/juicio_consolidado.csv` --lo que la persona
juzgo, sin haber visto ese signo-- y reporta:

- **Precision de relacion**: los `si` sobre el total juzgado, con intervalo de
  Wilson al 95 %.
- **Acierto de signo**: `signo_correcto` contra `signo_sugerido`, y solo sobre
  las filas con `relacion = si` y signo resuelto en los dos lados.

CUATRO REGLAS QUE ESTE SCRIPT NO ROMPE
======================================
1. **No inventa juicios.** Una fila sin juzgar sale del denominador y se cuenta
   aparte, en su propia linea. Rellenar un hueco con el valor mas probable es
   como se infla una metrica sin que nadie lo note.
2. **Los dudosos nunca cuentan como `si`.** Estan en el denominador porque el
   juez los miro, y fuera del numerador porque no los resolvio. Repartirlos es
   decidir en su lugar.
3. **La union lleva la oracion en la llave.** `pmid+regulador+blanco` no basta:
   en esta muestra hay un par (`hfq -> crc`, pmid 29244160) que aparece en tres
   oraciones distintas del mismo articulo, y unir sin la oracion colapsaria tres
   juicios en uno.
4. **Por debajo de 10 filas no se publica intervalo.** Se da el conteo y nada
   mas. Un intervalo de Wilson sobre seis casos es tan ancho que no distingue
   ninguna hipotesis de ninguna otra, y publicarlo aparenta una precision que
   no existe.

El archivo de juicio NO trae `signo_sugerido`, y es a proposito: ver lo que el
sistema propuso antes de decidir el signo correcto es la forma mas facil de
convertir una evaluacion en una confirmacion.

Solo biblioteca estandar.
"""

import argparse
import collections
import csv
import io
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

from muestrear_precision import wilson                      # noqa: E402

VALIDOS_RELACION = ("si", "no", "dudoso")
MINIMO_PARA_INTERVALO = 10

# El signo se escribe `+` o `-`. Se aceptan las palabras porque quien llena un
# CSV a mano a las once de la noche escribe lo que le sale.
EQUIVALE = {"+": "+", "activa": "+", "activacion": "+", "activates": "+",
            "positivo": "+",
            "-": "-", "reprime": "-", "represion": "-", "represses": "-",
            "negativo": "-",
            "?": "?", "sin signo": "?", "no resuelto": "?", "regulates": "?"}


def leer(ruta):
    if not os.path.exists(ruta):
        sys.exit("Falta %s." % ruta)
    with io.open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def llave(fila):
    """pmid + regulador + blanco + oracion. Ver la regla 3 del docstring."""
    return (fila["pmid"].strip(), fila["regulador"].strip(),
            fila["blanco"].strip(), " ".join(fila["oracion"].split()))


def normalizar_signo(valor):
    v = (valor or "").strip().lower()
    return EQUIVALE.get(v, v) if v else ""


def resuelto(signo):
    """Un signo unico y con direccion. `?`, vacio y `+;?` no lo son.

    El `signo_sugerido` del bronce agrega TODOS los disparadores de la oracion,
    asi que llega a menudo como `+;?` o incluso `+;-`. Comparar eso contra un
    juicio humano no significa nada: no se sabria cual de los dos se evalua.
    """
    return signo in ("+", "-")


def unir(muestra, juicios):
    por_llave = dict((llave(f), f) for f in juicios)
    filas, sin_pareja = [], 0
    for m in muestra:
        j = por_llave.get(llave(m))
        if j is None:
            sin_pareja += 1
        filas.append({
            "pmid": m["pmid"], "regulador": m["regulador"],
            "blanco": m["blanco"],
            "signo_sugerido": normalizar_signo(m.get("signo_sugerido")),
            "relacion": (j or {}).get("relacion", "").strip().lower(),
            "signo_correcto": normalizar_signo((j or {}).get("signo_correcto")),
        })
    return filas, sin_pareja


def informar_relacion(filas, sin_pareja, log):
    cuenta = collections.Counter(f["relacion"] or "(sin juzgar)"
                                 for f in filas)
    raros = sorted(set(f["relacion"] for f in filas
                       if f["relacion"]
                       and f["relacion"] not in VALIDOS_RELACION))

    log("=" * 70)
    log("PRECISION DE RELACION, POR JUICIO HUMANO")
    log("=" * 70)
    log("")
    log("  filas de la muestra              %3d" % len(filas))
    for v in VALIDOS_RELACION:
        log("    relacion = %-10s          %3d" % (v, cuenta.get(v, 0)))
    log("    sin juzgar                     %3d"
        % cuenta.get("(sin juzgar)", 0))
    if raros:
        log("    valores no reconocidos: %s" % ", ".join(raros))
    if sin_pareja:
        log("    filas que el archivo de juicio no cubre: %d" % sin_pareja)
    log("")

    juzgadas = sum(cuenta.get(v, 0) for v in VALIDOS_RELACION)
    if not juzgadas:
        log("  Todavia no hay ninguna fila juzgada: no hay cifra que dar.")
        log("")
        return False

    si, dud = cuenta.get("si", 0), cuenta.get("dudoso", 0)
    log("  Denominador: las %d juzgadas. Las %d sin juzgar quedan fuera y no"
        % (juzgadas, cuenta.get("(sin juzgar)", 0)))
    log("  se rellenan con nada.")
    log("")
    if juzgadas >= MINIMO_PARA_INTERVALO:
        baja, alta = wilson(si, juzgadas)
        log("  PRECISION  %d de %d  =  %.1f %%   IC 95 %% Wilson [%.1f, %.1f]"
            % (si, juzgadas, 100.0 * si / juzgadas,
               100.0 * baja, 100.0 * alta))
    else:
        log("  PRECISION  %d de %d  =  %.1f %%   (sin intervalo: menos de %d)"
            % (si, juzgadas, 100.0 * si / juzgadas, MINIMO_PARA_INTERVALO))
    log("")
    if dud:
        log("  Los %d dudosos estan en el denominador pero NUNCA en el" % dud)
        log("  numerador: un dudoso no es medio acierto, es una fila que el")
        log("  juez no pudo resolver, y repartirla es decidir por el.")
        log("")
    return True


def informar_signo(filas, log):
    log("=" * 70)
    log("ACIERTO DE SIGNO")
    log("=" * 70)
    log("")
    con_relacion = [f for f in filas if f["relacion"] == "si"]
    evaluables = [f for f in con_relacion
                  if resuelto(f["signo_correcto"])
                  and resuelto(f["signo_sugerido"])]

    sin_juicio = sum(1 for f in con_relacion if not f["signo_correcto"])
    juicio_flojo = sum(1 for f in con_relacion
                       if f["signo_correcto"]
                       and not resuelto(f["signo_correcto"]))
    sugerido_flojo = sum(1 for f in con_relacion
                         if resuelto(f["signo_correcto"])
                         and not resuelto(f["signo_sugerido"]))

    log("  filas con relacion = si            %3d" % len(con_relacion))
    log("    sin signo_correcto               %3d" % sin_juicio)
    log("    con signo_correcto sin resolver  %3d" % juicio_flojo)
    log("    con signo_sugerido sin resolver  %3d" % sugerido_flojo)
    log("    evaluables                       %3d" % len(evaluables))
    log("")

    if not evaluables:
        log("  Ninguna fila tiene signo resuelto en los dos lados: no hay")
        log("  acierto de signo que reportar.")
        log("")
        return

    aciertos = sum(1 for f in evaluables
                   if f["signo_correcto"] == f["signo_sugerido"])
    if len(evaluables) < MINIMO_PARA_INTERVALO:
        log("  ACIERTO  %d de %d.  Sin intervalo: menos de %d filas."
            % (aciertos, len(evaluables), MINIMO_PARA_INTERVALO))
        log("")
        log("  Un intervalo de Wilson sobre %d casos es tan ancho que no"
            % len(evaluables))
        log("  distingue ninguna hipotesis de ninguna otra. El conteo es un")
        log("  dato; la proporcion todavia no es una cifra.")
    else:
        b, a = wilson(aciertos, len(evaluables))
        log("  ACIERTO  %d de %d  =  %.1f %%   IC 95 %% Wilson [%.1f, %.1f]"
            % (aciertos, len(evaluables),
               100.0 * aciertos / len(evaluables), 100.0 * b, 100.0 * a))
        mayoria = collections.Counter(f["signo_correcto"] for f in evaluables)
        clase, n = mayoria.most_common(1)[0]
        log("")
        log("  Linea base: contestar siempre '%s' acertaria %d de %d = %.1f %%."
            % (clase, n, len(evaluables), 100.0 * n / len(evaluables)))
        log("  Sin ese rival al lado la cifra de arriba no significa nada.")
    log("")
    if sugerido_flojo:
        log("  Las %d filas que se caen por `signo_sugerido` sin resolver no"
            % sugerido_flojo)
        log("  son culpa del juez: el bronce agrega todos los disparadores de")
        log("  la oracion y basta uno generico para arrastrar un '?'. Se")
        log("  desbloquea con el disparador dominante; ver docs/bitacora.md.")
        log("")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--muestra", default="salidas/muestra_precision_50.csv")
    ap.add_argument("--juicios", default="salidas/juicio_consolidado.csv")
    args = ap.parse_args(argv)

    filas, sin_pareja = unir(leer(args.muestra), leer(args.juicios))

    def log(m):
        print(m, flush=True)

    if informar_relacion(filas, sin_pareja, log):
        informar_signo(filas, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
