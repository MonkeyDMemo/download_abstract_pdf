# -*- coding: utf-8 -*-
"""Reconocimiento de nombres de gen y de operon. Modulo compartido, seccion
1.2 del contrato de datos.

**El reconocimiento se hace tokenizando la oracion una vez y consultando un
`dict`, no recorriendo 5700 expresiones regulares.** Es una obligacion, no una
sugerencia de rendimiento. `auditar_signo.py` compila un par de regex por par
(TF, blanco); con 536 TFs y 5700 genes el espacio de pares es de 3.05
millones. Medido sobre 20 documentos: una alternancia de 5700 ramas cuesta
7.22 s (proyeccion 331 s al corpus); tokenizar y consultar un `dict` cuesta
0.06 s (proyeccion 2.6 s). Con el bucle por pares, no termina.

Ningun reconocimiento de genes por patron sustituye al reconocimiento de
entidades: `cat`, `his` o `map` son palabras inglesas antes que genes, y por
eso la sensibilidad a mayusculas es un campo por fila del diccionario y no una
bandera global. Aun asi, esto produce falsos positivos.

Solo biblioteca estandar.
"""

import collections
import re

# Un solo barrido por oracion. La clase no admite la letra griega ni el guion
# bajo a proposito: `DeltamexR` se escribe casi siempre con `Δ`, que queda
# fuera del token y deja `mexR` limpio.
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")

# Prefijos de perdida de funcion que hay que recortar antes de consultar.
#
# Medido en 60 documentos: 1039 `Δ` contra 4 `Delta`. El
# `PERDIDA = re.compile(r"...Delta\s*...")` de `auditar_signo.py:90-93`
# buscaba la palabra cuando el corpus escribe la letra, asi que
# `PERDIDA.search("ΔmexR strain")` devolvia False.
PREFIJOS_PERDIDA = (u"Δ", u"∆", "Delta", "delta")

# Operon escrito concatenado: prefijo de tres minusculas y dos o mas
# mayusculas seguidas. `pqsABCDE`, `mexEF`, `rhlAB`.
_CONCATENADO = re.compile(r"^([a-z]{3})([A-Z]{2,})$")

_LOCUS = re.compile(r"^PA\d{4}(\.\d)?$")

COLUMNAS_GENES = ["locus_tag", "simbolo", "alias", "tipo", "producto",
                  "es_tf", "fuente_tf", "fuente", "sensible_mayusculas"]
COLUMNAS_OPERONES = ["operon", "miembros", "locus_tags", "fuente"]


def _leer_tsv(ruta, columnas):
    """Lee un TSV con encabezado exacto. Falla si no lo es."""
    filas = []
    with open(ruta, encoding="utf-8") as f:
        cabecera = f.readline().rstrip("\n").rstrip("\r").split("\t")
        if cabecera != columnas:
            raise ValueError(
                "%s: encabezado %r; el contrato pide %r." % (ruta, cabecera,
                                                             columnas))
        for linea in f:
            linea = linea.rstrip("\n").rstrip("\r")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            # Rellenar por si el escritor recorto campos vacios finales.
            partes += [""] * (len(columnas) - len(partes))
            filas.append(dict(zip(columnas, partes)))
    return filas


def _lista(campo):
    return [x for x in campo.split("|") if x] if campo else []


class Lexico(object):
    """Diccionario de superficies -> entidad canonica.

    La entidad canonica de un gen es su simbolo (`mexT`) si lo tiene, y su
    locus tag (`PA0762`) si no. La de un operon es su nombre (`mexEF-oprN`).
    """

    def __init__(self):
        self._exactas = {}        # superficie tal cual -> id canonico
        self._insensibles = {}    # superficie en minusculas -> id canonico
        self._ambiguas_exactas = set()
        self._ambiguas_insensibles = set()
        self._es_tf = {}          # id canonico -> bool
        self._miembros = {}       # id de operon -> [id de gen, ...]
        self._por_miembros = {}   # frozenset de miembros -> id de operon
        self._sensible = {}       # superficie -> bool
        # Superficies que se descartaron por resolver a dos entidades. Va al
        # informe de la etapa 2; no es parte del contrato de `menciones()`,
        # pero sin ella el informe no puede reportar `ambiguas`.
        self.ambiguas = collections.Counter()
        self.sinteticos = collections.Counter()

    # ---------------------------------------------------------------- carga

    @classmethod
    def cargar(cls, ruta_genes, ruta_operones):
        lex = cls()
        for fila in _leer_tsv(ruta_genes, COLUMNAS_GENES):
            locus = fila["locus_tag"].strip()
            simbolo = fila["simbolo"].strip()
            idc = simbolo or locus
            if not idc:
                continue
            lex._es_tf[idc] = (fila["es_tf"].strip().lower() == "true")
            sensible = (fila["sensible_mayusculas"].strip().lower() == "true")
            superficies = set()
            if locus:
                superficies.add(locus)
            if simbolo:
                # Solo el simbolo tal como viene, NO su forma de proteina
                # sintetizada. Para una fila insensible a mayusculas `Fur` ya
                # casa con `fur`, asi que anadirla no aporta; para una fila
                # sensible --que son justo las de tres letras y las palabras
                # inglesas comunes-- registrar `Cat` o `His` reintroduce el
                # falso positivo que `sensible_mayusculas` existe para matar.
                # Si un gen sensible necesita que se reconozca su proteina, va
                # como `alias` del diccionario, donde alguien lo firma.
                superficies.add(simbolo)
            for a in _lista(fila["alias"]):
                superficies.add(a.strip())
            for s in superficies:
                lex._registrar(s, idc, sensible)

        for fila in _leer_tsv(ruta_operones, COLUMNAS_OPERONES):
            operon = fila["operon"].strip()
            if not operon:
                continue
            miembros = [m.strip() for m in _lista(fila["miembros"])]
            lex._es_tf.setdefault(operon, False)
            lex._miembros[operon] = miembros
            if miembros:
                lex._por_miembros.setdefault(frozenset(miembros), operon)
            # Un nombre de operon tiene cuatro caracteres o mas por
            # construccion, asi que nunca choca con la lista de palabras
            # inglesas comunes: se busca sin distinguir mayusculas.
            lex._registrar(operon, operon, False)
        return lex

    def _registrar(self, superficie, idc, sensible):
        if not superficie:
            return
        destino = self._exactas if sensible else self._insensibles
        ambiguas = (self._ambiguas_exactas if sensible
                    else self._ambiguas_insensibles)
        clave = superficie if sensible else superficie.lower()
        previo = destino.get(clave)
        if previo is not None and previo != idc:
            # Dos entidades distintas reclaman la misma superficie. No se
            # elige: se marca y no se emite ninguna mencion.
            ambiguas.add(clave)
        else:
            destino[clave] = idc
        self._sensible[superficie] = sensible

    # ------------------------------------------------------------ consultas

    def _resolver(self, cadena):
        """Superficie -> id canonico, o None. `False` si es ambigua."""
        if cadena in self._ambiguas_exactas:
            return False
        idc = self._exactas.get(cadena)
        if idc is not None:
            return idc
        bajo = cadena.lower()
        if bajo in self._ambiguas_insensibles:
            return False
        return self._insensibles.get(bajo)

    def menciones(self, oracion):
        """[(ini, fin, superficie, id_canonico, es_tf)] ordenado por ini.

        Sin solapes: cada token produce a lo mas una mencion completa, y si no
        casa entero se intentan sus segmentos, que son disjuntos entre si.
        """
        salida = []
        for m in _TOKEN.finditer(oracion):
            ini, fin = m.span()
            token = m.group(0)

            # (a) el token completo, tal cual.
            idc = self._resolver(token)
            if idc is False:
                self.ambiguas[token] += 1
                continue
            if idc is not None:
                salida.append((ini, fin, token, idc, self._es_tf.get(idc, False)))
                continue

            # (b) el token tras recortar un prefijo de perdida.
            recortado, desplazamiento = self._sin_prefijo(token)
            if recortado is not None:
                idc = self._resolver(recortado)
                if idc is False:
                    self.ambiguas[recortado] += 1
                    continue
                if idc is not None:
                    salida.append((ini + desplazamiento, fin, recortado, idc,
                                   self._es_tf.get(idc, False)))
                    continue

            # (d) operon escrito concatenado. Se intenta antes que los
            # segmentos porque `mexEF-oprN` ya se resolvio en (a) si estaba en
            # la tabla, y lo que queda aqui son concatenaciones sueltas.
            trozo = self._operon_concatenado(token)
            if trozo is not None:
                salida.append((ini, fin, token, trozo,
                               self._es_tf.get(trozo, False)))
                continue

            # (c) cada segmento entre guiones, por separado.
            #
            # El lookbehind `(?<![A-Za-z0-9-])` de `auditar_signo.py:140`
            # incluia el guion, asi que el segundo elemento de todo compuesto
            # era invisible: medidas 262 ocurrencias en 60 documentos
            # (`oprN`=39, `pqsA`=22, `oprM`=9, `brlR`=12).
            if "-" in token:
                salida.extend(self._por_segmentos(token, ini))
        salida.sort(key=lambda t: t[0])
        return salida

    def _sin_prefijo(self, token):
        for p in PREFIJOS_PERDIDA:
            if len(token) > len(p) and token.startswith(p):
                return token[len(p):], len(p)
        return None, 0

    def _por_segmentos(self, token, base):
        salida = []
        desplazamiento = 0
        for seg in token.split("-"):
            ini = base + desplazamiento
            desplazamiento += len(seg) + 1
            if not seg:
                continue
            idc = self._resolver(seg)
            if idc is False:
                self.ambiguas[seg] += 1
                continue
            if idc is None:
                idc = self._operon_concatenado(seg)
            if idc is None:
                continue
            salida.append((ini, ini + len(seg), seg, idc,
                           self._es_tf.get(idc, False)))
        return salida

    def _operon_concatenado(self, token):
        """`pqsABCDE` -> el operon que reune pqsA..pqsE, o None.

        El contrato pide expandir el concatenado, pero un tramo que resolviera
        a cinco entidades distintas seria ambiguo por la regla 4 y no se
        emitiria ninguna mencion, que es justo lo contrario de lo que se
        busca: medidas 61 ocurrencias de `pqsABCDE`, 44 de `mexEF` y 14 de
        `rhlAB` que el lookahead ocultaba. Asi que la expansion resuelve a UNA
        entidad, el operon, y no a sus miembros.

        Si `operones_pao1.tsv` no trae esa combinacion --puede pasar, la tabla
        se deriva por adyacencia de locus tags-- se registra un operon
        sintetico con el nombre tal como el articulo lo escribio. Se exige que
        TODOS los miembros expandidos existan en el diccionario, asi que una
        palabra cualquiera en camello no fabrica entidades.
        """
        m = _CONCATENADO.match(token)
        if not m:
            return None
        prefijo, letras = m.group(1), m.group(2)
        miembros = []
        for letra in letras:
            idc = self._resolver(prefijo + letra)
            if not idc:
                return None
            miembros.append(idc)
        if len(set(miembros)) < 2:
            return None
        conjunto = frozenset(miembros)
        idc = self._por_miembros.get(conjunto)
        if idc is not None:
            return idc
        self._miembros[token] = miembros
        self._por_miembros[conjunto] = token
        self._es_tf.setdefault(token, False)
        self.sinteticos[token] += 1
        return token

    # ------------------------------------------------------------- utiles

    def es_tf(self, id_canonico):
        return bool(self._es_tf.get(id_canonico, False))

    def es_operon(self, id_canonico):
        return id_canonico in self._miembros

    def miembros_operon(self, id_canonico):
        return list(self._miembros.get(id_canonico, []))

    def forma_proteina(self, id_canonico):
        """'mexT' -> 'MexT'. Un locus tag se queda como esta."""
        if _LOCUS.match(id_canonico):
            return id_canonico
        return id_canonico[:1].upper() + id_canonico[1:]

    def forma_gen(self, id_canonico):
        """'MexT' -> 'mexT'. Un locus tag se queda como esta."""
        if _LOCUS.match(id_canonico):
            return id_canonico
        return id_canonico[:1].lower() + id_canonico[1:]

    def superficies(self):
        """{superficie: (id_canonico, sensible)}."""
        salida = {}
        for s, sensible in self._sensible.items():
            clave = s if sensible else s.lower()
            destino = self._exactas if sensible else self._insensibles
            idc = destino.get(clave)
            if idc is not None:
                salida[s] = (idc, sensible)
        return salida

    def __len__(self):
        return len(self._es_tf)
