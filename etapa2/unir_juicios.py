#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Une los dos juicios humanos con la muestra y reporta las dos cifras.

    python3 etapa2/unir_juicios.py

Lee `salidas/muestra_precision_50.csv` (lo que el bronce afirma),
`salidas/juicio_relacion.csv` y `salidas/juicio_signo.csv` (lo que la persona
juzgo, cada uno sin ver lo que anclaria al otro), y reporta:

- **Precision de relacion**: los `si` sobre el total juzgado, con intervalo de
  Wilson al 95 %. Los dudosos entran en el denominador y NUNCA en el numerador;
  los no juzgados quedan fuera de los dos.
- **Signo**: hoy no se calcula. De las 50 filas de la muestra solo 6 traen un
  signo unico resuelto, porque el bronce agrega todos los disparadores de la
  oracion y casi siempre hay uno generico que aporta `?`. Un denominador de 6
  da un intervalo que no distingue nada, y publicar esa cifra seria peor que no
  tenerla. Se desbloquea con el disparador dominante; ver `docs/bitacora.md`.

TRES REGLAS QUE ESTE SCRIPT NO ROMPE
====================================
1. **No inventa juicios.** Una fila sin juzgar se cuenta como no juzgada y sale
   del denominador, en su propia linea del informe. Rellenar un hueco con el
   valor mas probable es como se infla una metrica sin que nadie lo note.
2. **Los dudosos nunca cuentan como `si`.** Estan en el denominador porque el
   juez los miro, y fuera del numerador porque no los resolvio. Repartirlos es
   decidir en su lugar.
3. **La union lleva la oracion en la llave.** `pmid+regulador+blanco` no basta:
   en esta muestra hay un par (`hfq -> crc`, pmid 29244160) que aparece en tres
   oraciones distintas del mismo articulo, y unir sin la oracion colapsaria tres
   juicios en uno.

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
# El signo se escribe como en la muestra: `+`, `-` o `?`. Se acepta tambien la
# palabra, porque quien llena un CSV a mano a las once de la noche escribe lo
# que le sale.
EQUIVALE = {"+": "+", "activa": "+", "activacion": "+", "activates": "+",
            "-": "-", "reprime": "-", "represion": "-", "represses": "-",
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


def unir(muestra, relacion, signo):
    por_relacion = dict((llave(f), f) for f in relacion)
    por_signo = dict((llave(f), f) for f in signo)
    huerfanas = 0
    filas = []
    for m in muestra:
        k = llave(m)
        r = por_relacion.get(k)
        s = por_signo.get(k)
        if r is None and s is None:
            huerfanas += 1
        filas.append({
            "pmid": m["pmid"], "regulador": m["regulador"],
            "blanco": m["blanco"],
            "signo_sugerido": normalizar_signo(m.get("signo_sugerido")),
            "juicio": (r or {}).get("juicio", "").strip().lower(),
            "signo_correcto": normalizar_signo((s or {}).get("signo_correcto")),
        })
    return filas, huerfanas


def informar(filas, huerfanas, log):
    total = len(filas)
    cuenta = collections.Counter(f["juicio"] or "(sin juzgar)" for f in filas)
    raros = sorted(set(f["juicio"] for f in filas
                       if f["juicio"] and f["juicio"] not in VALIDOS_RELACION))

    log("=" * 70)
    log("PRECISION DEL BRONCE, POR JUICIO HUMANO")
    log("=" * 70)
    log("")
    log("  filas de la muestra              %3d" % total)
    for v in VALIDOS_RELACION:
        log("    relacion = %-10s          %3d" % (v, cuenta.get(v, 0)))
    log("    sin juzgar                     %3d" % cuenta.get("(sin juzgar)", 0))
    if raros:
        log("    valores no reconocidos: %s" % ", ".join(raros))
    if huerfanas:
        log("    filas de la muestra sin juicio que las empareje: %d" % huerfanas)
    log("")

    juzgadas = cuenta.get("si", 0) + cuenta.get("no", 0) + cuenta.get("dudoso", 0)
    if not juzgadas:
        log("  Todavia no hay ninguna fila juzgada: no hay cifra que dar.")
        log("")
        return

    si, dud = cuenta.get("si", 0), cuenta.get("dudoso", 0)
    log("  Denominador: las %d juzgadas. Las %d sin juzgar quedan fuera; no se"
        % (juzgadas, cuenta.get("(sin juzgar)", 0)))
    log("  rellenan con nada.")
    log("")
    baja, alta = wilson(si, juzgadas)
    log("  PRECISION  %d de %d  =  %.1f %%   IC 95 %% Wilson [%.1f, %.1f]"
        % (si, juzgadas, 100.0 * si / juzgadas, 100.0 * baja, 100.0 * alta))
    log("")
    if dud:
        log("  Los %d dudosos estan en el denominador pero NUNCA en el" % dud)
        log("  numerador: un dudoso no es un acierto a medias, es una fila")
        log("  que el juez no pudo resolver, y repartirla es decidir por el.")
        log("")

    # --- signo, solo sobre relacion=si y signo resuelto en los dos lados
    log("=" * 70)
    log("SIGNO")
    log("=" * 70)
    log("")
    unicos = sum(1 for f in filas if f["signo_sugerido"] in ("+", "-"))
    log("  signo: denominador insuficiente, %d filas con signo unico resuelto; "
        "pendiente de disparador dominante" % unicos)
    log("")
    log("  El bronce agrega HOY todos los disparadores de la oracion, asi que")
    log("  la mayoria de las filas traen un generico que aporta '?' y el signo")
    log("  queda sin resolver. No es un defecto de la muestra.")
    log("")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--muestra", default="salidas/muestra_precision_50.csv")
    ap.add_argument("--relacion", default="salidas/juicio_relacion.csv")
    ap.add_argument("--signo", default="salidas/juicio_signo.csv")
    args = ap.parse_args(argv)

    filas, huerfanas = unir(leer(args.muestra), leer(args.relacion),
                            leer(args.signo))
    informar(filas, huerfanas, lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
