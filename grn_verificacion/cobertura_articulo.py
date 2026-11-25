# -*- coding: utf-8 -*-
"""Cuánto de la base está en el artículo que cita, y dónde.

    python -m grn_verificacion.cobertura_articulo --base XLSX --carpeta DIR
        [--excluir-pmids TSV ...] [--hoja H] [--json J]

Es la opción E de docs/protocolo-mejoras-nov.md hecha como conteo: no saca de
la base la lista de artículos, mira los que ya están en el corpus. Sobre las
filas exigibles del estrato «sin BioBERT» (las de la cifra principal del
contraste), por grupo del artículo citado (con texto completo, solo resumen o
fuera del corpus):

- **misma oración**: los dos locus coocurren en una oración candidata del
  artículo citado (la regla b con expansión del contraste);
- **mismo artículo**: los dos locus aparecen en el artículo citado, en
  cualquier oración. Es el techo de un lector que junte oraciones;
- si no, cuál falta: solo está el regulador, solo el blanco, están en
  artículos citados distintos, o ninguno. Un locus que falta es un gen que el
  texto no nombra (tablas, material suplementario) o que el diccionario no
  reconoce.

Lee la base en el servidor y escribe solo conteos. Un artículo cuenta como
texto completo si el bronce leyó de él alguna unidad de XML o de PDF.
"""
import argparse
import collections
import io
import json
import os

from grn_verificacion import contraste

GRUPOS = ("completo", "resumen", "fuera")
NOMBRE_GRUPO = {"completo": "con texto completo", "resumen": "solo resumen",
                "fuera": "fuera del corpus"}
CASOS = ("misma_oracion", "mismo_articulo", "articulos_distintos",
         "solo_regulador", "solo_blanco", "ninguno")
CON_LOCUS = ("gen", "proteina")


def loci_por_articulo(ruta_menciones, oraciones):
    """({pmid: locus del artículo}, {pmid: 'completo' o 'resumen'}).

    Los locus salen de las menciones de genes y proteínas, y de las oraciones
    candidatas con su expansión de operones (`contraste._leer_candidatas`),
    para que «mismo artículo» contenga siempre a «misma oración».
    """
    loci = collections.defaultdict(set)
    fuentes = collections.defaultdict(set)
    _, filas = contraste._filas_csv(
        ruta_menciones, ("pmid", "fuente_texto", "tipo", "id_normalizado"),
        "el CSV de menciones")
    for numero, fila in enumerate(filas, 2):
        pmid = contraste._pmid(fila["pmid"])
        if pmid is None:
            raise ValueError("El CSV de menciones, línea %d: el pmid no es "
                             "un número." % numero)
        fuentes[pmid].add(fila["fuente_texto"].strip())
        if fila["tipo"].strip() in CON_LOCUS:
            loci[pmid] |= contraste._loci_de_celda(fila["id_normalizado"])
    for pmid, locus, expandidos in oraciones:
        loci[pmid] |= locus | expandidos
    tipo = dict((p, "completo" if f.intersection(("xml", "pdf")) else "resumen")
                for p, f in fuentes.items())
    return dict(loci), tipo


def caso_de(fila, loci, por_pmid):
    """En cuál de `CASOS` cae una fila cuyo artículo está en el corpus."""
    a, b = fila["regulador"], fila["blanco"]
    clave = contraste._par(a, b)
    citados = [p for p in fila["pmids"] if p in loci]
    if any(clave in por_pmid.get(p, ()) for p in citados):
        return "misma_oracion"
    con_a = [p for p in citados if a in loci[p]]
    con_b = [p for p in citados if b in loci[p]]
    if set(con_a).intersection(con_b):
        return "mismo_articulo"
    if con_a and con_b:
        return "articulos_distintos"
    if con_a:
        return "solo_regulador"
    if con_b:
        return "solo_blanco"
    return "ninguno"


def contar(exigibles, loci, tipo, por_pmid):
    """Los conteos por grupo. `por_pmid` es el de `contraste._pares`."""
    cuenta = collections.OrderedDict(
        (g, collections.Counter()) for g in GRUPOS)
    for fila in exigibles:
        if contraste.estrato_de(fila) == "biobert":
            continue
        en_corpus = [tipo[p] for p in fila["pmids"] if p in tipo]
        grupo = ("fuera" if not en_corpus
                 else "completo" if "completo" in en_corpus else "resumen")
        c = cuenta[grupo]
        c["filas"] += 1
        if fila["regulador"] == fila["blanco"]:
            c["autorregulacion"] += 1
        elif grupo != "fuera":
            c[caso_de(fila, loci, por_pmid)] += 1
    salida = collections.OrderedDict()
    for g in GRUPOS:
        c = cuenta[g]
        fila = collections.OrderedDict([("filas", c["filas"]),
                                        ("autorregulacion",
                                         c["autorregulacion"])])
        if g != "fuera":
            for caso in CASOS:
                fila[caso] = c[caso]
        salida[g] = fila
    return salida


def ejecutar(base, carpeta, excluir=(), hoja=None, aceptar_base_distinta=False):
    base = contraste._expandir(base, "--base")
    carpeta = contraste._expandir(carpeta, "--carpeta")
    excluir = [contraste._expandir(r, "--excluir-pmids")
               for r in contraste._como_lista(excluir)]
    for flag, ruta in [("--base", base)] + [("--excluir-pmids", r)
                                            for r in excluir]:
        if not os.path.isfile(ruta):
            raise ValueError("No encuentro el archivo de %s." % flag)
    rutas = contraste.ubicar_archivos(carpeta, sin_red=True)
    pmids_excluir, _ = contraste._leer_pmids(excluir, "--excluir-pmids")
    interacciones, c_base = contraste.validacion.leer_base(base, hoja)
    cotejo = contraste.reentrenar.filas_cotejo(
        c_base, contraste.reentrenar.BASE_ESPERADA)
    if [f for f in cotejo if not f[3]] and not aceptar_base_distinta:
        raise ValueError("La base no coincide con PLAN.md 2.4: no se cuenta "
                         "hasta decidirlo.")
    oraciones, _, _ = contraste._leer_candidatas(rutas["candidatas"])
    _, por_pmid = contraste._pares(oraciones, True)
    loci, tipo = loci_por_articulo(rutas["menciones"], oraciones)
    exigibles, _ = contraste.denominador(interacciones, pmids_excluir)
    return collections.OrderedDict([
        ("carpeta", os.path.basename(os.path.normpath(carpeta))),
        ("articulos_del_corpus", collections.OrderedDict(
            (g, sum(1 for t in tipo.values() if t == g))
            for g in ("completo", "resumen"))),
        ("por_grupo", contar(exigibles, loci, tipo, por_pmid))])


def lineas(resultado):
    yield "Carpeta: %s. Artículos del corpus: %d con texto completo y %d " \
          "solo con resumen." % (
              resultado["carpeta"],
              resultado["articulos_del_corpus"]["completo"],
              resultado["articulos_del_corpus"]["resumen"])
    for g, c in resultado["por_grupo"].items():
        if g == "fuera":
            yield "Artículo citado %s: %d filas." % (NOMBRE_GRUPO[g],
                                                     c["filas"])
            continue
        yield ("Artículo citado %s: %d filas (%d de autorregulación). "
               "Misma oración %d; mismo artículo, otra oración %d; en "
               "artículos citados distintos %d; solo el regulador %d; solo "
               "el blanco %d; ninguno %d." % (
                   NOMBRE_GRUPO[g], c["filas"], c["autorregulacion"],
                   c["misma_oracion"], c["mismo_articulo"],
                   c["articulos_distintos"], c["solo_regulador"],
                   c["solo_blanco"], c["ninguno"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default=os.environ.get("BASE_CURADA"))
    ap.add_argument("--carpeta", required=True)
    ap.add_argument("--excluir-pmids", dest="excluir", action="append",
                    default=[])
    ap.add_argument("--hoja", default=None)
    ap.add_argument("--aceptar-base-distinta", action="store_true")
    ap.add_argument("--json", default=None, help="Dónde guardar los conteos.")
    args = ap.parse_args(argv)
    if not args.base:
        print("ERROR: falta --base (o BASE_CURADA en el entorno).")
        return 2
    try:
        resultado = ejecutar(args.base, args.carpeta, args.excluir, args.hoja,
                             args.aceptar_base_distinta)
        texto = list(lineas(resultado))
        for linea in texto:
            contraste.reentrenar.verificar_publicable(linea)
    except ValueError as e:
        # El mensaje filtrado, nunca un traceback: traería la ruta de la base.
        print("ERROR: %s" % contraste.mensaje_publicable(e))
        return 1
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s." % type(e).__name__)
        return 1
    for linea in texto:
        print(linea)
    if args.json:
        with io.open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
