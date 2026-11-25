# -*- coding: utf-8 -*-
"""Redes derivadas de una carpeta del flujo, para contrastarlas con la base.

    python -m grn_verificacion.derivar --carpeta C --salida D
        [--niveles alta,media,volteadas,al_reves,sin_respaldo]
        [--voltear] [--signo]

Lee de C `red_juez.tsv`, `red_evidencias.tsv` y `pares.jsonl`, y escribe en D
`red.tsv`, `red_evidencias.tsv`, `pares.jsonl` (solo los pares que la red
derivada usa, y de cada uno solo lo que el contraste lee: el `id_par`, los
nombres y los locus) y `derivada.json` (parámetros y conteos). Para contrastarla, a D
se le copian el `estado.json` y los CSV del bronce de C; no lleva
`red_informe.json`, así que el contraste avisa que no pudo comprobar la
huella de los pares, que aquí son otros a propósito.

Las reglas son las de docs/protocolo-mejoras-nov.md y no tienen variantes:

- `--voltear` (B1): una arista de nivel `al_reves` con `votos_si` >= 2 pasa a
  la clase `volteadas` y cambia de sentido. Sus evidencias llevan un `id_par`
  nuevo (el suyo más `~inv`) cuyo par tiene los locus intercambiados: el
  contraste lleva una arista a locus por sus evidencias. Si la arista
  volteada ya está en la red derivada, no se duplica.
- `--signo` (B2): si la red dice `regulates`, el jurado da `+` o `-` y la
  clase es alta, media o volteadas, el signo pasa a `activates` o `represses`.
- `--niveles`: las clases que se conservan. Por omisión, todas.

No abre la base curada. Imprime solo conteos.
"""
import argparse
import collections
import csv
import io
import json
import os

CLASES = ("alta", "media", "volteadas", "al_reves", "sin_respaldo")
MIN_VOTOS_VOLTEAR = 2
SUFIJO_INVERSO = "~inv"
SIGNO_DEL_JURADO = {"+": "activates", "-": "represses"}
CON_SIGNO_DEL_JURADO = ("alta", "media", "volteadas")
_MARCA = "\x00signo_del_jurado"


def clase_de(fila, voltear):
    """La clase de una arista: su nivel, o `volteadas` si aplica B1."""
    nivel = (fila.get("nivel") or "").strip()
    if voltear and nivel == "al_reves":
        try:
            votos = int((fila.get("votos_si") or "0").strip() or 0)
        except ValueError:
            votos = 0
        if votos >= MIN_VOTOS_VOLTEAR:
            return "volteadas"
    return nivel


def derivar(red, evidencias, niveles=CLASES, voltear=False, signo=False):
    """(red, evidencias, ids, conteos) de la red derivada.

    `ids` es {id_par de la red derivada: (id_par original, invertido)}.
    """
    niveles = set(niveles)
    cuenta = collections.Counter()
    directas, volteadas = [], []
    for fila in red:
        clase = clase_de(fila, voltear)
        cuenta["clase_" + (clase or "sin_nivel")] += 1
        if clase not in niveles:
            continue
        nueva = dict(fila)
        if (signo and nueva["signo"].strip() == "regulates"
                and clase in CON_SIGNO_DEL_JURADO
                and (nueva.get("signo_agente") or "").strip()
                in SIGNO_DEL_JURADO):
            nueva["signo"] = SIGNO_DEL_JURADO[nueva["signo_agente"].strip()]
            nueva[_MARCA] = True
        (volteadas if clase == "volteadas" else directas).append(nueva)
    claves = set((f["tf"], f["blanco"]) for f in directas)
    invertidas = set()
    salida = list(directas)
    for fila in volteadas:
        original = (fila["tf"], fila["blanco"])
        nueva_clave = (original[1], original[0])
        if nueva_clave in claves:
            cuenta["volteadas_ya_en_la_red"] += 1
            continue
        claves.add(nueva_clave)
        invertidas.add(original)
        fila["tf"], fila["blanco"] = nueva_clave
        salida.append(fila)
        cuenta["volteadas"] += 1
    conservadas = set((f["tf"], f["blanco"]) for f in directas)
    ids = {}
    evidencias_salida = []
    for fila in evidencias:
        clave = (fila["tf"], fila["blanco"])
        id_par = fila["id_par"].strip()
        if clave in invertidas:
            nueva = dict(fila)
            nueva["tf"], nueva["blanco"] = clave[1], clave[0]
            nueva["id_par"] = id_par + SUFIJO_INVERSO
            ids[nueva["id_par"]] = (id_par, True)
            evidencias_salida.append(nueva)
        elif clave in conservadas:
            ids[id_par] = (id_par, False)
            evidencias_salida.append(dict(fila))
    # Se cuenta al final: una volteada que no entró no cambió ningún signo.
    con_signo = sum(1 for f in salida if f.pop(_MARCA, False))
    if con_signo:
        cuenta["signo_del_jurado"] = con_signo
    cuenta["aristas"] = len(salida)
    cuenta["evidencias"] = len(evidencias_salida)
    return salida, evidencias_salida, ids, dict(cuenta)


def pares_derivados(lineas, ids):
    """Las líneas de `pares.jsonl` de la red derivada.

    Un par invertido es el original con los locus (y los nombres)
    intercambiados y el `id_par` nuevo.
    """
    por_original = collections.defaultdict(list)
    for nuevo, (original, invertido) in ids.items():
        por_original[original].append((nuevo, invertido))
    for linea in lineas:
        if not linea.strip():
            continue
        par = json.loads(linea)
        for nuevo, invertido in por_original.get(str(par.get("id_par")), ()):
            a, b = ("target", "tf") if invertido else ("tf", "target")
            otro = collections.OrderedDict([
                ("id_par", nuevo),
                ("tf", par.get(a)), ("target", par.get(b)),
                ("tf_locus", par.get(a + "_locus")),
                ("target_locus", par.get(b + "_locus"))])
            yield json.dumps(otro, ensure_ascii=False) + "\n"


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        return lector.fieldnames, list(lector)


def _escribir_tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, columnas, delimiter="\t",
                                  quoting=csv.QUOTE_NONE, quotechar=None,
                                  escapechar=None, lineterminator="\n",
                                  extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def ejecutar(carpeta, salida, niveles=CLASES, voltear=False, signo=False):
    columnas_red, red = _leer_tsv(os.path.join(carpeta, "red_juez.tsv"))
    columnas_ev, evidencias = _leer_tsv(
        os.path.join(carpeta, "red_evidencias.tsv"))
    red_d, evidencias_d, ids, cuenta = derivar(red, evidencias, niveles,
                                               voltear, signo)
    os.makedirs(salida, exist_ok=True)
    _escribir_tsv(os.path.join(salida, "red.tsv"), columnas_red, red_d)
    _escribir_tsv(os.path.join(salida, "red_evidencias.tsv"), columnas_ev,
                  evidencias_d)
    escritos = 0
    with io.open(os.path.join(carpeta, "pares.jsonl"), encoding="utf-8") as f, \
            io.open(os.path.join(salida, "pares.jsonl"), "w",
                    encoding="utf-8", newline="") as g:
        for linea in pares_derivados(f, ids):
            g.write(linea)
            escritos += 1
    if escritos != len(ids):
        raise ValueError("%d id_par de las evidencias no están en "
                         "pares.jsonl: la red y los pares no son de la misma "
                         "corrida." % (len(ids) - escritos))
    cuenta["pares"] = escritos
    resumen = collections.OrderedDict([
        ("carpeta", os.path.basename(os.path.normpath(carpeta))),
        ("niveles", [c for c in CLASES if c in set(niveles)]),
        ("voltear", bool(voltear)), ("signo", bool(signo)),
        ("min_votos_voltear", MIN_VOTOS_VOLTEAR),
        ("conteos", collections.OrderedDict(sorted(cuenta.items())))])
    with io.open(os.path.join(salida, "derivada.json"), "w",
                 encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1)
    return resumen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--carpeta", required=True, help="Carpeta del flujo, "
                    "con red_juez.tsv.")
    ap.add_argument("--salida", required=True, help="Carpeta que se escribe.")
    ap.add_argument("--niveles", default=",".join(CLASES),
                    help="Clases que se conservan, separadas por coma: %s."
                    % ", ".join(CLASES))
    ap.add_argument("--voltear", action="store_true",
                    help="B1: voltear las al_reves con 2 o más votos.")
    ap.add_argument("--signo", action="store_true",
                    help="B2: el signo del jurado donde la red dice "
                         "regulates.")
    args = ap.parse_args(argv)
    niveles = [n.strip() for n in args.niveles.split(",") if n.strip()]
    ajenos = [n for n in niveles if n not in CLASES]
    if ajenos:
        ap.error("--niveles: no conozco %s." % ", ".join(ajenos))
    if "volteadas" in niveles and not args.voltear and len(niveles) < len(CLASES):
        ap.error("--niveles pide volteadas sin --voltear.")
    resumen = ejecutar(args.carpeta, args.salida, niveles, args.voltear,
                       args.signo)
    print(json.dumps(resumen, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
