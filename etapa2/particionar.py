#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reparticiona el corpus de E. coli sin fuga entre train, dev y test.

Por que hace falta: los tres jsonl del servidor se partieron a nivel de
ejemplo. Como una misma ventana de texto genera un ejemplo por cada par
(TF, blanco) que contiene, la ventana cae en train y en test a la vez. Medido
sobre los archivos originales: el 73.9% de los ejemplos de test tiene su
ventana ya vista en train, y 61 de los 64 PMIDs de test estan tambien en
train. El macro-F1 de 0.87 mide sobre todo memorizacion.

Lo que hace este script: forma grupos que NO se pueden partir, los reparte
respetando la proporcion de clases, y despues VERIFICA que no quedo fuga. Si
queda, sale con codigo 1: mas vale no gastar GPU sobre una particion mala.

La verificacion mide con una canonizacion PROPIA, deliberadamente distinta de
la que se uso para agrupar. Una version anterior media con las mismas claves
del agrupamiento, asi que daba cero por construccion y el guardian era codigo
muerto: cualquier defecto en la clave se autoconfirmaba como particion limpia.
Ese es exactamente el genero de error que este script vino a corregir, asi que
no podia repetirlo.

Solo biblioteca estandar, como el resto del proyecto. Corre igual aqui que en
Colab sin instalar nada.

Uso:
    python etapa2/particionar.py --por pmid --salida datos_etapa2/por_pmid
    python etapa2/particionar.py --por par  --salida datos_etapa2/por_par --folds 5
"""

import argparse
import collections
import json
import os
import random
import re
import statistics
import sys

# El orden es el del checkpoint del servidor (config.json y label_mapping.json),
# que resulto ser alfabetico. Se fija aqui a proposito: la ficha encontro TRES
# ordenes distintos en el arbol. El del propio script de entrenamiento es
# LABELS_DEFAULT = ["activates","represses","regulates","no_relation"], que
# comparado con este deja 'activates' en el id 0 e intercambia 'represses' con
# 'no_relation'. O sea que entrenar sin --labels_json y luego leer el
# checkpoint con el orden del servidor reporta como "sin relacion" lo que el
# modelo llamo represion. Este archivo se escribe para pasarlo siempre.
ETIQUETAS = ["activates", "no_relation", "regulates", "represses"]

MARCADORES = re.compile(r"</?e[12]>")
NO_ALFANUM = re.compile(r"[^a-z0-9]+")


def ventana(texto):
    """El texto sin los marcadores, para AGRUPAR.

    Dos ejemplos con la misma ventana son el mismo fragmento del articulo con
    distinto par marcado. Separarlos entre particiones es la fuga principal.

    Los marcadores se quitan con cadena vacia, no con un espacio: el marcado
    solo inserta etiquetas, asi que quitarlas asi recupera el texto original.
    Sustituirlas por un espacio hacia que '<e1>CRP</e1>-dependent' y
    'CRP-dependent' dieran ventanas distintas cuando la etiqueta tocaba un
    caracter que no era espacio, y entonces el mismo fragmento caia en dos
    grupos. En el corpus de hoy no ocurre, pero la etapa 2 se regenera.
    """
    return " ".join(MARCADORES.sub("", texto).split())


def canonico(texto):
    """Forma canonica para VERIFICAR. No comparte codigo con ventana().

    Es a proposito mas agresiva: minusculas y sin puntuacion. Asi reconoce
    como el mismo fragmento dos textos que difieran en espaciado, en comas o
    en donde caia una etiqueta. Si verificar() usara ventana(), medirian lo
    mismo con lo mismo y el resultado seria cero pasara lo que pasara.
    """
    return " ".join(NO_ALFANUM.sub(" ", MARCADORES.sub("", texto).lower()).split())


def cargar(directorio, nombres):
    filas = []
    for n in nombres:
        ruta = os.path.join(directorio, n)
        if not os.path.exists(ruta):
            sys.exit("No encuentro %s" % ruta)
        with open(ruta, encoding="utf-8") as f:
            for i, linea in enumerate(f, 1):
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    r = json.loads(linea)
                except ValueError as e:
                    sys.exit("%s linea %d ilegible: %s" % (ruta, i, e))
                faltan = {"text", "label", "pmid", "tf", "target"} - set(r)
                if faltan:
                    sys.exit("%s linea %d sin los campos %s"
                             % (ruta, i, sorted(faltan)))
                if r["label"] not in ETIQUETAS:
                    sys.exit("%s linea %d: etiqueta desconocida %r"
                             % (ruta, i, r["label"]))
                filas.append(r)
    return filas


# ------------------------------------------------------------- agrupamiento

class Union:
    """Union-find. Los grupos son las componentes conexas del grafo que une
    cada ejemplo con las claves que no se deben separar."""

    def __init__(self):
        self.padre = {}

    def raiz(self, x):
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def unir(self, a, b):
        ra, rb = self.raiz(a), self.raiz(b)
        if ra != rb:
            self.padre[ra] = rb


def claves(fila, criterio):
    """Que cosas quedan atadas entre si para este criterio.

    La ventana entra SIEMPRE. Sin ella, agrupar por PMID todavia deja pasar
    las ventanas que RegulonDB atribuye a varios articulos: son pocas (6
    ventanas, 20 filas) pero caen justo en el par MelR->melAB, que aparece
    identico en cuatro PMIDs, dos de train y dos de test.
    """
    v = ("ventana", ventana(fila["text"]))
    if criterio == "pmid":
        return [("pmid", str(fila["pmid"])), v]
    if criterio == "par":
        return [("par", fila["tf"].lower(), fila["target"].lower()), v]
    raise ValueError(criterio)


def agrupar(filas, criterio):
    u = Union()
    for r in filas:
        ks = claves(r, criterio)
        for k in ks[1:]:
            u.unir(ks[0], k)
    grupos = collections.defaultdict(list)
    for r in filas:
        grupos[u.raiz(claves(r, criterio)[0])].append(r)
    return list(grupos.values())


# ------------------------------------------------------------- el reparto

def perfil(grupo):
    c = collections.Counter(r["label"] for r in grupo)
    return [c[e] for e in ETIQUETAS]


def desbalance(cuentas, objetivos):
    """Cuanto se aleja un reparto de lo que le tocaria por clase.

    Error relativo al cuadrado, no absoluto: lo que importa es que 'regulates'
    (207 ejemplos en total) no se quede con cuatro en test, y en cifras
    absolutas ese error se ve chico al lado del de 'activates'.
    """
    total = 0.0
    for c, o in zip(cuentas, objetivos):
        for x, y in zip(c, o):
            if y > 0:
                total += ((x - y) / y) ** 2
    return total


def _pulir(destino, perfiles, cuentas, objetivos, n_partes):
    """Mueve grupos de una particion a otra mientras eso mejore el balance.

    El voraz solo es myope al principio: coloca los grupos grandes cuando
    todas las particiones estan vacias y le dan igual, y despues ya no puede
    deshacerlo. Sin este pulido, un grupo de 105 ejemplos cae en dev y lo
    infla al 145% de su tamano. Con el, el reparto queda cerca del objetivo.
    """
    costo = desbalance(cuentas, objetivos)
    while True:
        mejor = None
        for i, p in enumerate(perfiles):
            origen = destino[i]
            cuentas[origen] = [a - b for a, b in zip(cuentas[origen], p)]
            for s in range(n_partes):
                if s == origen:
                    continue
                cuentas[s] = [a + b for a, b in zip(cuentas[s], p)]
                c = desbalance(cuentas, objetivos)
                if c < costo - 1e-12 and (mejor is None or c < mejor[0]):
                    mejor = (c, i, origen, s)
                cuentas[s] = [a - b for a, b in zip(cuentas[s], p)]
            cuentas[origen] = [a + b for a, b in zip(cuentas[origen], p)]
        if mejor is None:
            return costo
        costo, i, origen, s = mejor
        p = perfiles[i]
        cuentas[origen] = [a - b for a, b in zip(cuentas[origen], p)]
        cuentas[s] = [a + b for a, b in zip(cuentas[s], p)]
        destino[i] = s


def repartir(grupos, fracciones, semilla, intentos):
    """Reparte los grupos enteros minimizando el desbalance de clases.

    Voraz con reinicios, y cada reinicio se pule con busqueda local. Es un
    problema de particion de multiconjuntos; no se busca el optimo, se busca
    uno bueno y reproducible.
    """
    perfiles = [perfil(g) for g in grupos]
    totales = [sum(p[i] for p in perfiles) for i in range(len(ETIQUETAS))]
    objetivos = [[t * f for t in totales] for f in fracciones]
    n = len(fracciones)

    mejor, mejor_costo = None, float("inf")
    for intento in range(intentos):
        rnd = random.Random(semilla + intento)
        orden = sorted(range(len(grupos)),
                       key=lambda i: (-sum(perfiles[i]), rnd.random()))
        cuentas = [[0] * len(ETIQUETAS) for _ in fracciones]
        destino = [None] * len(grupos)
        for i in orden:
            p = perfiles[i]
            opciones = []
            for s in range(n):
                cuentas[s] = [a + b for a, b in zip(cuentas[s], p)]
                opciones.append((desbalance(cuentas, objetivos), rnd.random(), s))
                cuentas[s] = [a - b for a, b in zip(cuentas[s], p)]
            s = min(opciones)[2]
            cuentas[s] = [a + b for a, b in zip(cuentas[s], p)]
            destino[i] = s
        costo = _pulir(destino, perfiles, cuentas, objetivos, n)
        if costo < mejor_costo:
            mejor_costo, mejor = costo, list(destino)

    partes = [[] for _ in fracciones]
    for i, s in enumerate(mejor):
        partes[s].extend(grupos[i])
    return partes, mejor_costo


# ------------------------------------------------------------ verificacion

def _gramas(texto, n=10):
    p = texto.split()
    if len(p) <= n:
        return {tuple(p)} if p else set()
    return {tuple(p[i:i + n]) for i in range(len(p) - n + 1)}


def casi_duplicados(entrena, parte, umbral=0.8):
    """Ejemplos de 'parte' cuya ventana esta casi contenida en una de train.

    La igualdad exacta no basta. Un titulo de articulo citado en la
    bibliografia de otro produce dos ventanas distintas con el mismo texto
    dentro, y agrupar por PMID no lo puede atrapar porque son articulos
    distintos de verdad. Se mide contencion de 10-gramas, con indice invertido
    para no comparar todos contra todos.
    """
    indice = collections.defaultdict(set)
    gr_tr = []
    for j, r in enumerate(entrena):
        g = _gramas(canonico(r["text"]))
        gr_tr.append(len(g))
        for x in g:
            indice[x].add(j)

    peores = []
    for r in parte:
        g = _gramas(canonico(r["text"]))
        if not g:
            continue
        coincide = collections.Counter()
        for x in g:
            for j in indice.get(x, ()):
                coincide[j] += 1
        for j, c in coincide.items():
            base = min(len(g), gr_tr[j])
            if base and c / base >= umbral:
                peores.append((c / base, r, entrena[j]))
                break
    return peores


def verificar(partes, nombres, criterio, filas_todas, salida=print):
    """Comprueba que la particion sirve. Devuelve True o False.

    Mide con canonico(), que NO es la clave con la que se agrupo. Si midiera
    con ventana() daria cero por construccion, porque repartir() solo mueve
    grupos enteros, y entonces este guardian no podria detectar jamas un
    defecto en la propia clave de agrupamiento.
    """
    ok = True

    # 1. Nada vacio. Con --folds 2 el train salia vacio y, como todas las
    #    pertenencias contra un conjunto vacio son falsas, la particion se
    #    declaraba limpia.
    for parte, nombre in zip(partes, nombres):
        if not parte:
            salida("     FALLA: la particion '%s' quedo vacia." % nombre)
            ok = False
    if not ok:
        return False

    # 2. Que esten todas las filas y ninguna dos veces.
    vistas = [id(r) for p in partes for r in p]
    if len(vistas) != len(filas_todas) or len(set(vistas)) != len(vistas):
        salida("     FALLA: la union de las partes no reconstruye el corpus "
               "(%d repartidas, %d unicas, %d esperadas)."
               % (len(vistas), len(set(vistas)), len(filas_todas)))
        ok = False

    entrena = partes[0]
    c_tr = set(canonico(r["text"]) for r in entrena)
    p_tr = set(str(r["pmid"]) for r in entrena)
    pa_tr = set((r["tf"].lower(), r["target"].lower()) for r in entrena)

    salida("")
    salida("  %-14s %8s %6s %7s %9s" % ("fuga vs train", "texto", "PMID",
                                        "par", "casi-dup"))
    salida("  " + "-" * 50)
    for parte, nombre in zip(partes[1:], nombres[1:]):
        nc = sum(1 for r in parte if canonico(r["text"]) in c_tr)
        npm = len(set(str(r["pmid"]) for r in parte) & p_tr)
        npa = sum(1 for r in parte
                  if (r["tf"].lower(), r["target"].lower()) in pa_tr)
        cd = casi_duplicados(entrena, parte)
        n = len(parte)
        salida("  %-14s %7.1f%% %6d %6.1f%% %8.1f%%"
               % (nombre, 100.0 * nc / n, npm, 100.0 * npa / n,
                  100.0 * len(cd) / n))

        # El texto nunca puede repetirse: es la fuga que se vino a corregir.
        if nc:
            salida("     FALLA: %d ejemplos de %s repiten texto de train."
                   % (nc, nombre))
            ok = False
        # El PMID solo se exige cuando se pidio cortar por PMID. Con --por par
        # se comparte a proposito, y por eso se reporta pero no se exige.
        if criterio == "pmid" and npm:
            salida("     FALLA: %d PMIDs de %s tambien en train" % (npm, nombre))
            ok = False
        if criterio == "par" and npa:
            salida("     FALLA: %d ejemplos de %s con el par ya en train"
                   % (npa, nombre))
            ok = False
        # Los casi-duplicados no tumban la particion: un titulo citado en la
        # bibliografia de otro articulo es fuga real pero ningun criterio de
        # agrupamiento por PMID la puede evitar. Se reporta para que quien
        # escriba el numero sepa que existe.
        if cd:
            # Solo la razon de contencion: los otros dos campos son dicts y
            # max() sobre la tupla entera acaba comparandolos cuando empatan.
            peor = max(x[0] for x in cd)
            salida("     AVISO: %d ejemplos de %s tienen su ventana contenida "
                   "en una de train (peor %.2f)." % (len(cd), nombre, peor))
    return ok


def tabla_clases(partes, nombres, salida=print):
    salida("")
    salida("  %-9s %6s %5s  %s"
           % ("parte", "n", "arts", " ".join("%-11s" % e for e in ETIQUETAS)))
    salida("  " + "-" * 70)
    total = sum(len(p) for p in partes)
    for parte, nombre in zip(partes, nombres):
        if not parte:
            continue
        c = collections.Counter(r["label"] for r in parte)
        cel = " ".join("%4d %5.1f%%" % (c[e], 100.0 * c[e] / len(parte))
                       for e in ETIQUETAS)
        arts = len(set(str(r["pmid"]) for r in parte))
        salida("  %-9s %6d %5d  %s" % (nombre, len(parte), arts, cel))
    c = collections.Counter(r["label"] for p in partes for r in p)
    cel = " ".join("%4d %5.1f%%" % (c[e], 100.0 * c[e] / total)
                   for e in ETIQUETAS)
    arts = len(set(str(r["pmid"]) for p in partes for r in p))
    salida("  %-9s %6d %5d  %s" % ("TOTAL", total, arts, cel))

    # El numero de ejemplos enganaba: 21 'regulates' parecen suficientes hasta
    # que se ve que 15 salen del mismo articulo. Lo que da la incertidumbre
    # real es de cuantos articulos independientes vienen.
    salida("")
    problemas = []
    for parte, nombre in zip(partes[1:], nombres[1:]):
        if not parte:
            continue
        for e in ETIQUETAS:
            filas = [r for r in parte if r["label"] == e]
            if not filas:
                problemas.append((0, 0, e, nombre))
                continue
            arts = collections.Counter(str(r["pmid"]) for r in filas)
            mayor = max(arts.values())
            problemas.append((len(arts), len(filas), e, nombre, mayor))
    peor = min(problemas)
    if len(peor) == 5:
        n_arts, n_ej, e, nombre, mayor = peor
        salida("  La celda mas flaca: %s en %s son %d ejemplos, pero de solo "
               "%d articulos" % (e, nombre, n_ej, n_arts))
        salida("  (y %d de ellos salen de uno solo)." % mayor)
        if n_arts < 5:
            salida("  AVISO: con menos de 5 articulos independientes el F1 de "
                   "esa clase es ruido,")
            salida("  por bien que se vea el conteo de ejemplos. Reporta "
                   "validacion cruzada (--folds 5).")


def escribir(parte, ruta):
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        for r in parte:
            d = {k: r[k] for k in ("text", "label", "pmid", "tf", "target")}
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def escribir_etiquetas(directorio):
    os.makedirs(directorio, exist_ok=True)
    with open(os.path.join(directorio, "label_mapping.json"),
              "w", encoding="utf-8") as f:
        json.dump(ETIQUETAS, f, ensure_ascii=False, indent=2)


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Reparticiona sin fuga el corpus de relaciones.")
    ap.add_argument("--entrada", default=".",
                    help="Carpeta con los tres entity_marked_*.jsonl originales.")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--por", default="pmid", choices=["pmid", "par"],
                    help="pmid: ningun articulo se comparte. "
                         "par: ninguna relacion (TF,blanco) se comparte.")
    ap.add_argument("--dev", type=float, default=0.1)
    ap.add_argument("--test", type=float, default=0.1)
    ap.add_argument("--folds", type=int,
                    help="Validacion cruzada de K pliegues en vez de un corte.")
    ap.add_argument("--semilla", type=int, default=20260819)
    ap.add_argument("--intentos", type=int, default=400,
                    help="Reinicios del reparto voraz. Mas es mejor y cuesta segundos.")
    args = ap.parse_args()

    if args.folds is not None:
        # En modo pliegues el train es "todo menos test y dev", o sea (K-2)/K.
        # Con K=2 eso da cero, y un train vacio pasaba como particion limpia.
        if args.folds < 3:
            sys.exit("--folds tiene que ser 3 o mas: el train es (K-2)/K del "
                     "corpus, asi que con K=2 quedaria vacio.")
        if args.folds < 5:
            print("AVISO: con K=%d el train es solo el %.0f%% del corpus."
                  % (args.folds, 100.0 * (args.folds - 2) / args.folds))
    else:
        if not (0 < args.dev < 1) or not (0 < args.test < 1):
            sys.exit("--dev y --test tienen que estar entre 0 y 1.")
        if args.dev + args.test >= 1:
            sys.exit("--dev mas --test tiene que dejar algo para el train.")

    filas = cargar(args.entrada, ["entity_marked_train.jsonl",
                                  "entity_marked_dev.jsonl",
                                  "entity_marked_test.jsonl"])
    print("Cargados %d ejemplos de %d PMIDs, %d ventanas distintas."
          % (len(filas),
             len(set(str(r["pmid"]) for r in filas)),
             len(set(ventana(r["text"]) for r in filas))))

    grupos = agrupar(filas, args.por)
    tam = sorted((len(g) for g in grupos), reverse=True)
    print("Agrupando por %s + ventana: %d grupos indivisibles."
          % (args.por, len(grupos)))
    print("  tamanos: mayor=%d (%.1f%% del corpus)  mediana=%d  menor=%d"
          % (tam[0], 100.0 * tam[0] / len(filas), statistics.median(tam), tam[-1]))

    todo_ok = True
    if args.folds:
        tope = 1.0 / args.folds
        if tam[0] > tope * len(filas):
            print("  AVISO: el grupo mayor pasa del %.0f%% que le toca a un pliegue."
                  % (100 * tope))
        partes, costo = repartir(grupos, [1.0 / args.folds] * args.folds,
                                 args.semilla, args.intentos)
        nombres = ["fold_%d" % i for i in range(args.folds)]
        print("\nValidacion cruzada de %d pliegues (desbalance %.3f):"
              % (args.folds, costo))
        tabla_clases(partes, nombres)

        # Cada pliegue es test una vez; el siguiente hace de dev. Asi los tres
        # conjuntos siguen siendo grupos disjuntos entre si.
        for i in range(args.folds):
            j = (i + 1) % args.folds
            te, dv = partes[i], partes[j]
            tr = [r for k, p in enumerate(partes) if k not in (i, j) for r in p]
            print("\n--- pliegue %d: train=%d dev=%d test=%d"
                  % (i, len(tr), len(dv), len(te)))
            if not verificar([tr, dv, te], ["train", "dev", "test"],
                             args.por, filas):
                todo_ok = False
            d = os.path.join(args.salida, "fold_%d" % i)
            escribir(tr, os.path.join(d, "entity_marked_train.jsonl"))
            escribir(dv, os.path.join(d, "entity_marked_dev.jsonl"))
            escribir(te, os.path.join(d, "entity_marked_test.jsonl"))
            # Cada pliegue autocontenido: barrido.py exige el mapa de etiquetas
            # dentro de --datos, y apuntar --datos a fold_N no encontraba el de
            # la carpeta padre.
            escribir_etiquetas(d)
    else:
        fr = [1.0 - args.dev - args.test, args.dev, args.test]
        partes, costo = repartir(grupos, fr, args.semilla, args.intentos)
        nombres = ["train", "dev", "test"]
        print("\nReparto %.0f/%.0f/%.0f (desbalance %.3f):"
              % (fr[0] * 100, fr[1] * 100, fr[2] * 100, costo))
        tabla_clases(partes, nombres)
        todo_ok = verificar(partes, nombres, args.por, filas)
        for parte, nombre in zip(partes, nombres):
            escribir(parte, os.path.join(args.salida,
                                         "entity_marked_%s.jsonl" % nombre))

    escribir_etiquetas(args.salida)

    print("")
    if not todo_ok:
        print("PARTICION RECHAZADA: quedo fuga. No la uses.")
        return 1
    print("Particion limpia. Escrita en %s" % args.salida)
    print("Pasale --labels_json .../label_mapping.json al entrenamiento: el")
    print("LABELS_DEFAULT del script deja 'activates' en el id 0 pero")
    print("intercambia 'represses' con 'no_relation'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
