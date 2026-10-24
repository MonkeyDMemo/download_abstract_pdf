"""¿Tablas o redacción? Las filas de la base que el bronce no cubre, en los
artículos que más filas sostienen (PLAN.md 3.4, punto 27).

El segundo artículo con más filas del denominador tenía XML y apenas un cuarto
de cobertura, y quedaron dos explicaciones: «o reporta en tablas, o hay un
patrón de redacción que el bronce no capta». El bronce lee oraciones, y una
tabla no las tiene. Aquí se mide cuánto pesa cada una, en la máquina donde
vive la base y solo con conteos.

Las categorías
--------------
Cada fila exigible que cita alguno de los `cuantos` artículos con más filas
(los de `contraste._concentracion`) cae en la primera que le aplica:

1. `autorregulacion`: regulador y blanco son el mismo locus. Va aparte, como
   en el contraste: el bronce la excluye por construcción.
2. `regla_b`: ya la cubre la regla b con expansión (`contraste.cubierta`).
3. `sin_xml`: ninguno de los artículos mayores que cita tiene su
   `<pmid>_*.xml` legible en la carpeta de `--xml`.
4. `misma_fila`: sus dos locus en un mismo `tr` de una tabla; una celda
   que abarca varias filas (`rowspan`) cuenta en cada una.
5. `misma_tabla`: en un mismo `table-wrap`, contando título (también el de
   su `table-wrap-group`), celdas y pie.
6. `tabla_y_texto`: uno en una tabla y el otro en el texto.
7. `solo_texto`: los dos en el texto, sin coocurrir en una oración candidata
   (si coocurrieran ahí, la regla b ya la habría cubierto).
8. `ninguno`: lo demás.

El orden es parte de la medición: una fila con los dos locus en el texto y
uno de ellos también en una tabla es `tabla_y_texto`. Para que eso no se lea
como «solo en tablas», las tres últimas traen su desglose (`DETALLES`).

Qué es «el texto»
-----------------
Lo que el bronce lee del XML: `grn_etl.pubmed.jats_a_texto`, partido en
bloques y oraciones por `grn_bronce.texto` como en la identificación, pero con
las tablas quitadas del árbol antes. Sin quitarlas, una tabla metida en un
`<p>` sale aplanada en el texto de ese párrafo y su título sale entre los
pies de figura, y «en una tabla» y «en el texto» dejarían de distinguirse.
Un locus es una mención del diccionario del bronce (`etapa2/lexico.py`),
llevada a locus como en el puente (`puente.locus_de`), con los operones
expandidos por el catálogo del paso 1.

Las celdas se leen con otra regla que la prosa (`_FORMATO`): el bronce no las
lee, y una lectura que pegara un `<break/>` o la marca de una nota al gen
vecino perdería el gen.

Confidencialidad
----------------
Como en el contraste: la base llega solo por argumento y su ruta no se
imprime. Lo publicable, el informe, pasa por `reentrenar.verificar_publicable`:
conteos y porcentajes, sin locus, PMIDs ni rutas. Los artículos van numerados
por filas («artículo 1» es el de más) y nunca por PMID; el nombre de cada XML
lo lleva, así que ningún mensaje lo repite. A la carpeta confidencial va
`tablas.json`, con los parámetros, las huellas y los mismos conteos. Ningún
archivo sale fila por fila: nada se ajusta mirando filas.

Reconocer genes por diccionario produce falsos positivos y no sustituye al
reconocimiento de entidades: dos locus en una fila de tabla son un candidato,
no una relación.

Biblioteca estándar y Python 3.8: corre con el intérprete del entorno del
asesor sin instalar nada.
"""

import collections
import glob
import json
import os
import re
import xml.etree.ElementTree as ET

from grn_bronce import texto as _texto
from grn_comun import procedencia
from grn_etl import pubmed
from grn_verificacion import contraste, puente, reentrenar, validacion

CUANTOS = 5
ARCHIVO_REGISTRO = "tablas.json"

CATEGORIAS = ("autorregulacion", "regla_b", "sin_xml", "misma_fila",
              "misma_tabla", "tabla_y_texto", "solo_texto", "ninguno")
# Las que el XML puede explicar: tienen XML, no son autorregulación y la regla
# b no las cubre. Son el denominador de la segunda columna del informe.
POR_EXPLICAR = CATEGORIAS[3:]
DETALLES = collections.OrderedDict([
    ("tabla_y_texto", ("los_dos_en_el_texto", "uno_solo_en_el_texto")),
    ("solo_texto", ("misma_oracion", "oraciones_distintas")),
    ("ninguno", ("ninguno_aparece", "uno_solo", "tablas_distintas")),
])

NOMBRE_CATEGORIA = {
    "autorregulacion": "autorregulación",
    "regla_b": "regla b (ya cubierta)",
    "sin_xml": "sin XML",
    "misma_fila": "misma fila de una tabla",
    "misma_tabla": "misma tabla",
    "tabla_y_texto": "tabla y texto",
    "solo_texto": "solo texto",
    "ninguno": "ninguno",
}
NOMBRE_DETALLE = {
    "los_dos_en_el_texto": "con los dos locus también en el texto",
    "uno_solo_en_el_texto": "con uno de ellos solo en tablas",
    "misma_oracion": "en una misma oración que el bronce no tomó como "
                     "candidata",
    "oraciones_distintas": "en oraciones distintas",
    "ninguno_aparece": "sin ninguno de los dos locus en el XML",
    "uno_solo": "con uno solo",
    "tablas_distintas": "con los dos en tablas distintas",
}
NOMBRE_XML = {"si": "sí", "no": "no", "ilegible": "ilegible"}
NOMBRE_BRONCE = {"xml": "con XML", "abstract": "solo abstract",
                 None: "fuera del corpus"}

# `row` y `entry` son las de una tabla OASIS (CALS), que JATS admite en su
# propio espacio de nombres; por nombre local se leen igual que `tr` y `td`.
_FILAS = ("tr", "row")
_CELDAS = ("th", "td", "entry")
# Lo que se quita del texto: un `table-wrap-group` lleva su propio título,
# que dentro de un `<p>` saldría pegado a la prosa como el de una tabla.
_ENVOLTURAS = ("table-wrap", "table-wrap-group")
_ENTERO = re.compile(r"^[0-9]+$")
# `rowspan="0"` es «hasta el final del grupo de filas»; el arrastre se corta
# ahí de todos modos, así que basta con un número que no se acabe antes.
_HASTA_EL_FINAL = 10 ** 9
# Las marcas de formato se pegan a lo que las rodea porque parten nombres de
# gen: `<italic>mexEF</italic>-<italic>oprN</italic>` es un solo operón. Todo
# otro elemento separa: con `itertext` a secas, un `<break/>` entre dos genes
# de una celda o la marca de una nota pegada al gen (`lasR<sup>a</sup>`)
# dejaban una sola palabra que el diccionario ya no reconoce.
_FORMATO = frozenset([
    "italic", "bold", "underline", "sc", "monospace", "roman", "sans-serif",
    "styled-content", "named-content", "strike", "overline"])


def _nada(_):
    pass


_n = contraste._n


def _pct(k, n):
    return "%.1f %%" % (100.0 * k / n) if n else "—"


# ----------------------------------------------------------------- el XML

def _nombre(elemento):
    """El nombre local de la etiqueta: `{...}table-wrap` -> `table-wrap`.

    Por nombre local, como `validacion._local`, para que un JATS con espacio
    de nombres (o una tabla OASIS) no se lea como si no tuviera tablas.
    """
    etiqueta = elemento.tag
    return etiqueta.rsplit("}", 1)[-1] if isinstance(etiqueta, str) else ""


def _leer_xml(ruta):
    """La raíz del XML, o ValueError sin la ruta: su nombre lleva el PMID."""
    try:
        return ET.parse(ruta).getroot()
    except (ET.ParseError, LookupError, ValueError):
        # LookupError es una codificación declarada que Python no conoce, y
        # ValueError una multibyte que expat no lee: la primera tumbaba la
        # corrida entera en vez de dejar ilegible un artículo.
        raise ValueError("Un XML de --xml no es XML válido.") from None


def _juntar(elemento, partes):
    separa = _nombre(elemento) not in _FORMATO
    if separa:
        partes.append(" ")
    partes.append(elemento.text or "")
    for hijo in elemento:
        _juntar(hijo, partes)
        partes.append(hijo.tail or "")
    if separa:
        partes.append(" ")


def _texto_de(elemento):
    """El texto de un elemento y lo que lleva dentro, con los blancos
    colapsados. Ver `_FORMATO`."""
    partes = []
    _juntar(elemento, partes)
    return " ".join("".join(partes).split())


def _titulo(envoltura):
    return " ".join(_texto_de(h) for h in envoltura
                    if _nombre(h) in ("label", "caption"))


def _filas_de_mas(celda):
    """Cuántas filas debajo de la suya ocupa una celda: `rowspan` menos uno
    en una tabla XHTML, `morerows` en una OASIS. Lo que no es un entero no
    abarca nada."""
    valor = (celda.get("rowspan") or "").strip()
    if _ENTERO.match(valor):
        n = int(valor)
        return _HASTA_EL_FINAL if n == 0 else n - 1
    valor = (celda.get("morerows") or "").strip()
    return int(valor) if _ENTERO.match(valor) else 0


def _filas(envoltura):
    """Una lista por `tr` (o `row`), en el orden del documento, con el texto
    de cada celda.

    Una celda que abarca varias filas cuenta en cada una, al principio de las
    de abajo. Es la forma de una tabla de regulador y blancos: el regulador en
    una celda con `rowspan` y un blanco por fila. Leída `tr` por `tr`, solo el
    primer blanco compartía fila con él y los demás bajaban a «misma tabla».
    El arrastre es por grupo de filas (el `thead`, el `tbody` o la tabla
    misma): no pasa del encabezado al cuerpo ni entra a una tabla anidada.
    """
    grupo_de = dict((hijo, padre) for padre in envoltura.iter()
                    for hijo in padre)
    arrastre = {}
    filas = []
    for fila in envoltura.iter():
        if _nombre(fila) not in _FILAS:
            continue
        grupo = grupo_de.get(fila)
        vienen = arrastre.get(grupo, [])
        celdas = [texto for texto, _ in vienen]
        siguen = [(texto, n - 1) for texto, n in vienen if n > 1]
        for celda in fila:
            if _nombre(celda) not in _CELDAS:
                continue
            texto = _texto_de(celda)
            celdas.append(texto)
            de_mas = _filas_de_mas(celda)
            if de_mas > 0:
                siguen.append((texto, de_mas))
        arrastre[grupo] = siguen
        filas.append(celdas)
    return filas


def _tabla(envoltura, titulo_del_grupo=""):
    titulo = " ".join(t for t in (titulo_del_grupo, _titulo(envoltura)) if t)
    pie = " ".join(_texto_de(h) for h in envoltura
                   if _nombre(h) == "table-wrap-foot")
    return {"titulo": titulo, "filas": _filas(envoltura), "pie": pie}


def tablas_de_jats(ruta):
    """Las tablas de un XML JATS: [{"titulo", "filas", "pie"}] en el orden
    del documento.

    Una por `table-wrap`. `titulo` es el texto de su `label` y su `caption`,
    precedido del de su `table-wrap-group` si va en uno: el título del grupo
    es el de todas sus tablas. `filas`, una lista por `tr` con el texto de
    cada `th` o `td`, más el de las celdas de arriba que la abarcan
    (`rowspan`; ver `_filas`); `pie`, el texto de su `table-wrap-foot`.

    Una tabla anidada no se pierde: un `<table>` dentro de una celda deja su
    texto en esa celda y sus `tr` como filas de la tabla que lo contiene, y un
    `table-wrap` dentro de otro sale además como tabla propia, con su título y
    su pie. Las etiquetas se comparan por nombre local. ValueError si el
    archivo no es XML.
    """
    raiz = _leer_xml(ruta)
    del_grupo = {}
    for grupo in raiz.iter():
        if _nombre(grupo) == "table-wrap-group":
            titulo = _titulo(grupo)
            for hija in grupo:
                if _nombre(hija) == "table-wrap":
                    del_grupo[hija] = titulo
    return [_tabla(e, del_grupo.get(e, "")) for e in raiz.iter()
            if _nombre(e) == "table-wrap"]


def _quitar_tablas(raiz):
    """Saca del árbol los `table-wrap` y los `table-wrap-group`, con el texto
    que les sigue a salvo.

    En ElementTree el texto que va después de un elemento es su `tail`, y se
    iría con él: «As shown in <table-wrap/> the genes vary» perdía «the genes
    vary», que es prosa del párrafo.
    """
    for padre in list(raiz.iter()):
        anterior = None
        for hijo in list(padre):
            if _nombre(hijo) not in _ENVOLTURAS:
                anterior = hijo
                continue
            if hijo.tail:
                if anterior is None:
                    padre.text = (padre.text or "") + " " + hijo.tail
                else:
                    anterior.tail = (anterior.tail or "") + " " + hijo.tail
            padre.remove(hijo)


def oraciones_de_jats(ruta):
    """Las oraciones que el bronce lee de un XML JATS, sin las tablas.

    `jats_a_texto` es el mismo que escribió el `.txt` que leyó el bronce, y
    los bloques y las oraciones salen de `grn_bronce.texto` como en
    `identificar`: los encabezados (también el título del artículo) no son
    oraciones. Las etiquetas se pasan a su nombre local antes, porque
    `jats_a_texto` las busca sin espacio de nombres. ValueError si el archivo
    no es XML.
    """
    raiz = _leer_xml(ruta)
    _quitar_tablas(raiz)
    for elemento in raiz.iter():
        nombre = _nombre(elemento)
        if nombre:
            elemento.tag = nombre
    md, _ = pubmed.jats_a_texto(ET.tostring(raiz, encoding="utf-8"))
    return [oracion for _, cuerpo in _texto.bloques(md)
            for oracion in _texto.oraciones(cuerpo)]


def xml_de(carpeta, pmid):
    """Los `<pmid>_*.xml` de la carpeta, ordenados.

    Es el nombre que deja `cli.py fulltext --tipo xml` (`{pmid}_{pmcid}.xml`);
    con dos PMCIDs para el mismo artículo habría dos, y se leen los dos.
    """
    return sorted(glob.glob(os.path.join(glob.escape(carpeta),
                                         "%s_*.xml" % pmid)))


# ------------------------------------------------------------- los locus

def cargar_recursos():
    """(léxico, {id canónico: locus}, catálogo de operones): los del bronce,
    cargados como en `puente.construir_pares`."""
    from grn_bronce import identificar, operones
    return (identificar.cargar_lexico(), identificar.cargar_locus_tags(),
            operones.Catalogo.cargar(operones.RUTA_POR_OMISION))


def huellas_de_recursos():
    """Las huellas del diccionario y del catálogo con que se llevó a locus."""
    from grn_bronce import identificar
    rutas = identificar.recursos_de_la_identificacion()
    return collections.OrderedDict(
        (n, procedencia.huella_texto(rutas[n]))
        for n in ("genes_pao1.tsv", "operones_pao1.tsv"))


def locus_de_texto(texto, lex, locus, catalogo):
    """Los locus de PAO1 que nombra `texto`, como conjunto.

    Las menciones son las de `lex.menciones`, el mismo reconocimiento del
    bronce, y cada una se lleva a locus con `puente.locus_de`: un gen da el
    suyo y un operón del catálogo, sus genes (uno que el texto abrevia y la
    tabla no conoce no da ninguno, por la regla de `grn_bronce.operones`). Lo
    que no tiene forma de locus de PAO1 se ignora, como en el contraste: no se
    puede comparar con la base.

    Es reconocimiento por diccionario: produce falsos positivos y no
    sustituye al reconocimiento de entidades.
    """
    salida = set()
    for mencion in lex.menciones(texto or ""):
        # (ini, fin, superficie, id canónico, es_tf): basta el id.
        for lt in puente.locus_de(mencion[3], locus, catalogo):
            lt = lt.strip().upper()
            if validacion.LOCUS.match(lt):
                salida.add(lt)
    return salida


def indice_de_articulo(rutas, lex, locus, catalogo):
    """Las tablas y el texto de un artículo, ya en locus.

    {"tablas": [{"filas", "todo"}], "texto", "oraciones", "n_tablas",
    "n_filas"}: de cada tabla, las filas con dos locus o más y todo lo que
    nombra (título, celdas y pie); del texto, sus locus y los de cada oración
    con dos o más. Con varios XML del mismo artículo, se juntan. ValueError si
    alguno no es XML.
    """
    def a_locus(t):
        return locus_de_texto(t, lex, locus, catalogo)

    tablas, texto, oraciones, n_filas = [], set(), [], 0
    for ruta in rutas:
        for t in tablas_de_jats(ruta):
            filas = [set().union(*[a_locus(c) for c in fila])
                     for fila in t["filas"]]
            todo = a_locus(t["titulo"]) | a_locus(t["pie"])
            for f in filas:
                todo |= f
            tablas.append({"filas": [f for f in filas if len(f) > 1],
                           "todo": todo})
            n_filas += len(filas)
        for oracion in oraciones_de_jats(ruta):
            loci = a_locus(oracion)
            texto |= loci
            if len(loci) > 1:
                oraciones.append(loci)
    return {"tablas": tablas, "texto": texto, "oraciones": oraciones,
            "n_tablas": len(tablas), "n_filas": n_filas}


# ------------------------------------------------------- las categorías

def articulos_mayores(exigibles, cuantos=CUANTOS):
    """Los PMIDs de los `cuantos` artículos con más filas exigibles, de más a
    menos.

    El criterio y el desempate (por PMID, de menor a mayor) son los de
    `contraste._concentracion`, que da cuántas filas reúnen: una prueba exige
    que coincidan, porque si no, el informe hablaría de otros artículos que
    los de la concentración que reporta el contraste.
    """
    por_pmid = collections.Counter()
    for f in exigibles:
        for p in set(f["pmids"]):
            por_pmid[p] += 1
    orden = sorted(por_pmid.items(), key=lambda x: (-x[1], int(x[0])))
    return [p for p, _ in orden[:cuantos]]


def _en_articulo(a, b, indice):
    """(categoría, detalle) de un par en un artículo con XML."""
    tablas = indice["tablas"]
    if any(a in f and b in f for t in tablas for f in t["filas"]):
        return "misma_fila", None
    if any(a in t["todo"] and b in t["todo"] for t in tablas):
        return "misma_tabla", None
    en_tablas = set()
    for t in tablas:
        en_tablas |= t["todo"]
    texto = indice["texto"]
    if (a in en_tablas and b in texto) or (b in en_tablas and a in texto):
        return "tabla_y_texto", ("los_dos_en_el_texto"
                                 if a in texto and b in texto
                                 else "uno_solo_en_el_texto")
    if a in texto and b in texto:
        juntos = any(a in o and b in o for o in indice["oraciones"])
        return "solo_texto", ("misma_oracion" if juntos
                              else "oraciones_distintas")
    # Si uno está en el texto, el otro no aparece en ningún lado (si no, la
    # fila habría caído antes); si aparecen los dos, es en tablas distintas.
    vistos = sum(1 for x in (a, b) if x in en_tablas or x in texto)
    return "ninguno", DETALLES["ninguno"][vistos]


def categoria(fila, pares, indices, mayores):
    """(categoría, detalle) de una fila de la base: la primera que aplica.

    `pares`, los de `contraste.pares_del_bronce` con expansión. `indices`,
    {pmid: lo de `indice_de_articulo`, o None si no hay XML legible}.
    `mayores`, los artículos que se miran, en orden; de ellos cuentan los que
    la fila cita. Si cita dos con XML, gana la categoría que va antes,
    artículo por artículo: un locus de la tabla de uno y otro del texto del
    otro no son «tabla y texto». `detalle` es None salvo en las categorías
    de `DETALLES`.
    """
    a, b = fila["regulador"], fila["blanco"]
    if a == b:
        return "autorregulacion", None
    if contraste.cubierta(fila, pares, "b"):
        return "regla_b", None
    con_xml = [indices[p] for p in mayores
               if p in fila["pmids"] and indices.get(p) is not None]
    if not con_xml:
        return "sin_xml", None
    return min((_en_articulo(a, b, i) for i in con_xml),
               key=lambda c: CATEGORIAS.index(c[0]))


def _vacio():
    return collections.OrderedDict([
        ("filas", 0),
        ("categorias", collections.OrderedDict((c, 0) for c in CATEGORIAS)),
        ("detalles", collections.OrderedDict(
            (c, collections.OrderedDict((d, 0) for d in ds))
            for c, ds in DETALLES.items())),
    ])


def _sumar(conteo, hecho):
    cat, detalle = hecho
    conteo["filas"] += 1
    conteo["categorias"][cat] += 1
    if detalle:
        conteo["detalles"][cat][detalle] += 1


def medir(exigibles, pares, indices, mayores):
    """(juntos, por_articulo): los conteos por categoría de las filas que
    citan alguno de `mayores`, todos juntos y artículo por artículo.

    En `juntos` cada fila cuenta una vez; en `por_articulo`, en cada artículo
    que cita, con la categoría que le da ese artículo solo. La regla b no
    cambia: mira todos los artículos que la fila cita, porque una fila que el
    bronce cubre en otro no está por explicar en este.
    """
    juntos = _vacio()
    por_articulo = [_vacio() for _ in mayores]
    elegidos = set(mayores)
    for fila in exigibles:
        if not elegidos & set(fila["pmids"]):
            continue
        _sumar(juntos, categoria(fila, pares, indices, mayores))
        for i, pmid in enumerate(mayores):
            if pmid in fila["pmids"]:
                _sumar(por_articulo[i],
                       categoria(fila, pares, indices, [pmid]))
    return juntos, por_articulo


# ------------------------------------------------------------- el informe

def _linea_base(base):
    if base["diferencias"]:
        return ("Base: difiere de PLAN.md 2.4 en %s conteos; se siguió con "
                "--aceptar-base-distinta." % _n(base["diferencias"]))
    return ("Base: coincide con PLAN.md 2.4 en los %s conteos."
            % _n(len(base["cotejo"])))


def _mayuscula(texto):
    return texto[:1].upper() + texto[1:]


def _seccion_juntos(w, juntos):
    por_explicar = sum(juntos["categorias"][c] for c in POR_EXPLICAR)
    w("| categoría | filas | % de las filas | % de las por explicar |")
    w("|---|---:|---:|---:|")
    for c in CATEGORIAS:
        k = juntos["categorias"][c]
        w("| %s | %s | %s | %s |" % (
            NOMBRE_CATEGORIA[c], _n(k), _pct(k, juntos["filas"]),
            _pct(k, por_explicar) if c in POR_EXPLICAR else "—"))
    w("| **total** | **%s** | %s | %s |" % (
        _n(juntos["filas"]), _pct(juntos["filas"], juntos["filas"]),
        _pct(por_explicar, por_explicar)))
    w("")
    w("- Por explicar: %s de %s." % (_n(por_explicar), _n(juntos["filas"])))
    for c, detalles in DETALLES.items():
        w("- %s: %s." % (_mayuscula(NOMBRE_CATEGORIA[c]), "; ".join(
            "%s, %s" % (NOMBRE_DETALLE[d], _n(juntos["detalles"][c][d]))
            for d in detalles)))
    w("")


def _seccion_por_articulo(w, articulos):
    def fila(nombre, celdas):
        w("| %s | %s |" % (nombre, " | ".join(celdas)))

    w("| | %s |" % " | ".join("artículo %d" % a["articulo"]
                               for a in articulos))
    w("|---|%s" % ("---:|" * len(articulos)))
    fila("filas exigibles", [_n(a["filas"]) for a in articulos])
    fila("XML en `--xml`", [NOMBRE_XML[a["xml"]] for a in articulos])
    fila("el bronce lo leyó", [NOMBRE_BRONCE.get(a["bronce"], "—")
                               for a in articulos])
    fila("tablas (filas de tabla)", [
        "%s (%s)" % (_n(a["tablas"]), _n(a["filas_de_tabla"]))
        if a["tablas"] is not None else "—" for a in articulos])
    for c in CATEGORIAS:
        fila(NOMBRE_CATEGORIA[c], [
            "%s (%s)" % (_n(a["categorias"][c]),
                         _pct(a["categorias"][c], a["filas"]))
            for a in articulos])
    for c, detalles in DETALLES.items():
        for d in detalles:
            fila("— %s, %s" % (NOMBRE_CATEGORIA[c], NOMBRE_DETALLE[d]),
                 [_n(a["detalles"][c][d]) for a in articulos])
    w("")


def informe_markdown(resultado):
    """El informe publicable: solo conteos y porcentajes.

    Antes de devolverse pasa por `reentrenar.verificar_publicable`: si trae
    una ruta, un locus o algo con forma de PMID, lanza ValueError y no hay
    informe a medias.
    """
    s = []
    w = s.append
    d = resultado["denominador"]
    b = resultado["bronce"]
    x = resultado["xml"]
    articulos = resultado["por_articulo"]
    cuantos = len(articulos)

    w("# Tablas o redacción en los artículos con más filas")
    w("")
    w("- Generado el %s (UTC)." % resultado["generado_en"])
    w("- %s" % _linea_base(resultado["base"]))
    w("- Exigibles: %s (fuera por homología %s y por el archivo de "
      "exclusiones %s). Las que citan alguno de los %s artículos con más "
      "filas exigibles: %s." % (
          _n(d["exigibles"]), _n(d["homologia"]),
          _n(d["excluidas_por_archivo"]), _n(cuantos),
          _n(resultado["juntos"]["filas"])))
    w("- Bronce: corrida %s; %s oraciones candidatas."
      % (contraste._corrida(b["corrida"]), _n(b["oraciones"])))
    w("- XML en `--xml`: %s para estos artículos; legible en %s de los %s."
      % (contraste._cuantas(x["archivos"], "archivo", "archivos"),
         _n(x["articulos_con_xml"]), _n(cuantos)))
    w("")
    w("PLAN.md 3.4, punto 27: de las filas que estos artículos sostienen y "
      "el bronce no cubre, ¿cuántas reporta el artículo en tablas, que el "
      "bronce no lee, y cuántas en el texto, con una redacción que no capta? "
      "Cada fila cae en la primera categoría que le aplica, en este orden:")
    w("")
    w("1. **autorregulación**: el regulador y el blanco son el mismo locus; "
      "el bronce la excluye por construcción.")
    w("2. **regla b**: ya la cubre una oración candidata del artículo que "
      "cita, con expansión (la regla b del contraste).")
    w("3. **sin XML**: ninguno de estos artículos que cita tiene su XML "
      "legible en `--xml`.")
    w("4. **misma fila**: sus dos locus en una misma fila (`tr`) de una "
      "tabla; una celda que abarca varias filas (`rowspan`) cuenta en cada "
      "una.")
    w("5. **misma tabla**: en una misma tabla (`table-wrap`), contando "
      "título (también el de su grupo de tablas), celdas y pie.")
    w("6. **tabla y texto**: uno en una tabla y el otro en el texto.")
    w("7. **solo texto**: los dos en el texto, sin coocurrir en una oración "
      "candidata.")
    w("8. **ninguno**: lo demás.")
    w("")
    w("El texto es lo que el bronce lee del XML (resumen, párrafos y pies "
      "de figura, partidos en sus mismas oraciones), sin las tablas. Un locus "
      "sale de una mención del diccionario del bronce, con los operones "
      "expandidos por su catálogo. «Por explicar» son las filas con XML que "
      "no son autorregulación y que la regla b no cubre.")
    w("")
    if not articulos:
        w("No hay artículos que medir: ninguna fila exigible cita un PMID.")
        w("")
    else:
        w("## 1. Los %s juntos" % _n(cuantos))
        w("")
        _seccion_juntos(w, resultado["juntos"])
        w("## 2. Por artículo")
        w("")
        w("«Artículo 1» es el de más filas exigibles; los empates van por "
          "PMID, como en la concentración del contraste. Una fila que cita "
          "dos de estos artículos cuenta en las dos columnas, cada una con "
          "la categoría que le da ese artículo, y una sola vez en la "
          "sección 1; la regla b mira, como en el contraste, todos los "
          "artículos que la fila cita. Los porcentajes son sobre las filas "
          "de cada artículo.")
        w("")
        _seccion_por_articulo(w, articulos)
    w("## 3. Cautelas")
    w("")
    w("- El reconocimiento de genes es por diccionario: produce falsos "
      "positivos y no sustituye al reconocimiento de entidades. Dos locus en "
      "una fila de tabla son un candidato, no una relación.")
    w("- Una tabla de cepas, plásmidos u oligos también nombra genes, y aquí "
      "no se distingue de una de resultados: «misma fila» es la señal más "
      "fuerte de que el artículo reporta el par en una tabla; «misma tabla» "
      "y «tabla y texto», las más débiles.")
    w("- La expansión de operones sale del catálogo y no del texto: una "
      "celda u oración que nombra un operón pone juntos a todos sus genes, "
      "así que una fila entre dos genes del mismo operón cae en «misma "
      "fila» (o en una misma oración) sin que el artículo la diga, como en "
      "la regla b del contraste.")
    w("- Un regulador que va en el encabezado de una columna (la cepa "
      "mutante del experimento) comparte tabla con sus blancos pero no "
      "fila: cuenta como «misma tabla».")
    w("- Es un piso: un gen que el artículo nombra de una forma que el "
      "diccionario no conoce (un nombre de la cepa PA14, un sinónimo) no "
      "cuenta, ni en las tablas ni en el texto.")
    w("- El texto incluye las oraciones que el bronce no toma como "
      "candidatas (métodos, demasiado cortas o largas, con más de 8 genes): "
      "el desglose de «solo texto» dice cuántas filas coocurren en una de "
      "ellas.")
    w("- El orden importa: una fila con los dos locus en el texto y uno "
      "también en una tabla es «tabla y texto», y el desglose dice cuántas "
      "son así.")
    w("- Una tabla anidada cuenta dentro de la que la contiene. Una tabla "
      "que el XML trae como imagen no tiene filas, y una suplementaria (un "
      "archivo aparte) no viene en el XML: sus genes no cuentan, y sus "
      "filas caen en «ninguno».")
    w("- Las filas de un mismo artículo no son independientes: estas cifras "
      "describen a estos artículos y no se extienden al resto de la base.")
    if resultado.get("avisos"):
        w("")
        w("## Avisos")
        w("")
        for aviso in resultado["avisos"]:
            w("- %s" % aviso)
    texto = "\n".join(s) + "\n"
    try:
        reentrenar.verificar_publicable(texto)
    except ValueError as e:
        raise ValueError("El informe no se puede publicar (%s): no se "
                         "escribe." % e) from None
    return texto


def resumen(resultado):
    """Las líneas de la terminal: las cifras principales y los avisos."""
    d = resultado["denominador"]
    x = resultado["xml"]
    juntos = resultado["juntos"]
    articulos = resultado["por_articulo"]

    def reparto(conteo):
        return "; ".join("%s %s" % (NOMBRE_CATEGORIA[c],
                                    _n(conteo["categorias"][c]))
                         for c in CATEGORIAS)

    lineas = [_linea_base(resultado["base"])]
    lineas.append(
        "Exigibles: %s; de ellas, en los %s artículos con más filas: %s. "
        "XML legible en --xml: %s de %s (%s)."
        % (_n(d["exigibles"]), _n(len(articulos)), _n(juntos["filas"]),
           _n(x["articulos_con_xml"]), _n(len(articulos)),
           contraste._cuantas(x["archivos"], "archivo encontrado",
                              "archivos encontrados")))
    if articulos:
        lineas.append("Juntos: %s." % reparto(juntos))
        for a in articulos:
            lineas.append("  artículo %d, %s: %s." % (
                a["articulo"], contraste._cuantas(a["filas"], "fila",
                                                  "filas"), reparto(a)))
    for aviso in resultado.get("avisos") or ():
        lineas.append("AVISO: %s" % aviso)
    return lineas


# ---------------------------------------------------------------- ejecutar

def ejecutar(base, carpeta, xml, confidencial, informe=None, excluir=(),
             hoja=None, aceptar_base_distinta=False, cuantos=CUANTOS,
             log=_nada):
    """Mide tablas y texto de los `cuantos` artículos mayores y escribe.

    `base`: el .xlsx, por ruta. `carpeta`: la del flujo (los dos CSV del
    bronce). `xml`: la carpeta con los `<pmid>_<pmcid>.xml` de PMC (la
    subcarpeta `xml` del texto completo, o una copia suya), que son datos
    públicos. `excluir`: archivos con el formato de `reservas.tsv`,
    como en el contraste. `confidencial`: carpeta fuera de todo repositorio
    para `tablas.json`. `informe`: dónde va el Markdown publicable, o None.

    Las comprobaciones van antes de abrir la base, y la base se coteja con
    `reentrenar.BASE_ESPERADA` como en el contraste: si no cuadra, ValueError
    salvo `aceptar_base_distinta`. El informe y las líneas de `log` pasan por
    `verificar_publicable` antes de escribir nada. Devuelve el resultado: solo
    conteos.
    """
    confidencial = contraste._expandir(confidencial, "--confidencial")
    contraste.exigir_confidencial_fuera(confidencial)
    base = contraste._expandir(base, "--base")
    carpeta = contraste._expandir(carpeta, "--carpeta")
    xml = contraste._expandir(xml, "--xml")
    excluir = [contraste._expandir(r, "--excluir-pmids")
               for r in contraste._como_lista(excluir)]
    if informe:
        informe = contraste._expandir(informe, "--informe")
    if isinstance(cuantos, bool) or not isinstance(cuantos, int) \
            or cuantos < 1:
        raise ValueError("--cuantos tiene que ser un entero de 1 o más.")
    for flag, ruta in ([("--base", base)]
                       + [("--excluir-pmids", r) for r in excluir]):
        if not os.path.isfile(ruta):
            # Sin la ruta: la de --base dice dónde vive la base.
            raise ValueError("No encuentro el archivo de %s. Usa una ruta "
                             "absoluta; entre comillas simples, ~ y $HOME no "
                             "se expanden." % flag)
    if not os.path.isdir(xml):
        raise ValueError("No encuentro la carpeta de --xml.")
    if not glob.glob(os.path.join(glob.escape(xml), "*_*.xml")):
        # Antes de abrir la base: `cli.py fulltext` deja los XML en la
        # subcarpeta xml de su salida, y con la carpeta de arriba todo salía
        # «sin XML» después de haber leído la base para nada.
        raise ValueError("La carpeta de --xml no tiene ningún "
                         "<pmid>_<pmcid>.xml. Si es la del texto completo, "
                         "los XML están en su subcarpeta xml.")
    rutas = contraste.ubicar_archivos(carpeta, sin_red=True)
    # El lector del contraste (en `main`, alias de `entrenamiento.leer_pmids`):
    # un error dice la línea del archivo y no su ruta.
    pmids_excluir, c_excluir = contraste._leer_pmids(excluir,
                                                     "--excluir-pmids")

    interacciones, c_base = validacion.leer_base(base, hoja)
    # BASE_ESPERADA se lee aquí, como en el contraste: así una prueba la
    # puede sustituir.
    cotejo = reentrenar.filas_cotejo(c_base, reentrenar.BASE_ESPERADA)
    distintas = [f for f in cotejo if not f[3]]
    for clave, esperado, medido, _ in distintas:
        log("Base: %s esperado %s, medido %s." % (clave, _n(esperado),
                                                  _n(medido)))
    if distintas and not aceptar_base_distinta:
        raise ValueError(
            "La base no coincide con PLAN.md 2.4 en %d conteos (arriba). "
            "Puede ser otra versión de la base o el lector: no se mide hasta "
            "decidirlo; con --aceptar-base-distinta se sigue."
            % len(distintas))

    avisos = []
    citados = set()
    for fila in interacciones:
        citados.update(fila["pmids"])
    if not excluir:
        avisos.append("sin --excluir-pmids: el denominador conserva el "
                      "artículo de 731 filas que el bronce no puede leer "
                      "(PLAN.md 2.4), que entonces cuenta entre los mayores.")
    elif not pmids_excluir & citados:
        avisos.append("ninguno de los PMIDs de --excluir-pmids aparece en la "
                      "base; revisa que el archivo sea el que querías.")

    exigibles, c_den = contraste.denominador(interacciones, pmids_excluir)
    mayores = articulos_mayores(exigibles, cuantos)
    oraciones, corridas, trae_expandidos = contraste._leer_candidatas(
        rutas["candidatas"])
    if not trae_expandidos:
        avisos.append("el CSV de candidatas no trae genes_expandidos (un "
                      "bronce anterior a la expansión de operones): la regla "
                      "b se mide sin expansión.")
    if len(corridas) > 1:
        avisos.append("el CSV de candidatas mezcla %s corridas del bronce."
                      % _n(len(corridas)))
    pares = contraste._pares(oraciones, True)
    docs = contraste.documentos_del_bronce(rutas["menciones"])

    lex, locus, catalogo = cargar_recursos()
    indices, estados = {}, {}
    c_xml = collections.Counter()
    for pmid in mayores:
        archivos_xml = xml_de(xml, pmid)
        c_xml["archivos"] += len(archivos_xml)
        if len(archivos_xml) > 1:
            c_xml["con_varios"] += 1
        indices[pmid], estados[pmid] = None, "no"
        if not archivos_xml:
            continue
        try:
            indices[pmid] = indice_de_articulo(archivos_xml, lex, locus,
                                               catalogo)
            estados[pmid] = "si"
            c_xml["leidos"] += len(archivos_xml)
        except (ValueError, OSError):
            # Sin el mensaje: el nombre del archivo lleva el PMID. Lo que no
            # se puede leer no explica nada, y cuenta como sin XML.
            estados[pmid] = "ilegible"
    ilegibles = sum(1 for e in estados.values() if e == "ilegible")
    con_xml = sum(1 for e in estados.values() if e == "si")
    if ilegibles:
        avisos.append("%s de los artículos %s un XML que no se pudo leer: "
                      "cuenta como sin XML."
                      % (_n(ilegibles), "tiene" if ilegibles == 1
                         else "tienen"))
    if mayores and not con_xml:
        avisos.append("ninguno de los artículos tiene su XML en --xml: revisa "
                      "que la carpeta sea la de los XML del corpus de este "
                      "bronce.")
    if c_xml["con_varios"]:
        # Pasa cuando se corrigió el PMCID en el tablero y se volvió a bajar:
        # el XML viejo, que puede ser de otro artículo, sigue en la carpeta y
        # el bronce ya no lo lee.
        avisos.append("%s de los artículos %s más de un XML en --xml (con "
                      "otro PMCID) y se leyeron juntos: si uno es de otro "
                      "artículo, sus genes cuentan como de este."
                      % (_n(c_xml["con_varios"]),
                         "tiene" if c_xml["con_varios"] == 1 else "tienen"))

    juntos, por_articulo = medir(exigibles, pares, indices, mayores)
    articulos = []
    for i, pmid in enumerate(mayores):
        indice = indices[pmid]
        a = collections.OrderedDict([
            ("articulo", i + 1),
            ("xml", estados[pmid]),
            ("bronce", docs.get(pmid)),
            ("tablas", indice["n_tablas"] if indice else None),
            ("filas_de_tabla", indice["n_filas"] if indice else None),
        ])
        a.update(por_articulo[i])
        articulos.append(a)

    resultado = collections.OrderedDict([
        ("generado_en", contraste._ahora()),
        ("base", collections.OrderedDict([
            ("filas", c_base["filas"]), ("cotejo", cotejo),
            ("diferencias", len(distintas)),
            ("aceptada_distinta", bool(distintas))])),
        ("exclusiones", collections.OrderedDict([
            ("archivos", c_excluir["archivos"]),
            ("pmids", len(pmids_excluir)),
            ("pmids_citados", len(pmids_excluir & citados))])),
        ("denominador", collections.OrderedDict(
            (k, c_den[k]) for k in ("base", "homologia",
                                    "excluidas_por_archivo", "exigibles",
                                    "autorregulacion",
                                    "en_los_5_articulos_mayores"))),
        ("bronce", collections.OrderedDict([
            ("corrida", next(iter(corridas)) if len(corridas) == 1
             else None),
            ("oraciones", len(oraciones)),
            ("trae_expandidos", trae_expandidos)])),
        ("cuantos", cuantos),
        ("xml", collections.OrderedDict([
            ("articulos", len(mayores)), ("articulos_con_xml", con_xml),
            ("articulos_ilegibles", ilegibles),
            ("archivos", c_xml["archivos"]), ("leidos", c_xml["leidos"])])),
        ("juntos", juntos),
        ("por_articulo", articulos),
        ("avisos", avisos),
    ])
    texto = informe_markdown(resultado)
    lineas = resumen(resultado)
    try:
        reentrenar.verificar_publicable("\n".join(lineas))
    except ValueError as e:
        raise ValueError("El resumen de la terminal no pasó el filtro de "
                         "publicación (%s): no se escribe nada." % e)

    if not os.path.isdir(confidencial):
        # 0o700: en el servidor, otras cuentas no entran a la carpeta.
        os.makedirs(confidencial, 0o700)
    huellas = collections.OrderedDict([
        ("base", procedencia.huella(base)),
        ("candidatas", procedencia.huella(rutas["candidatas"])),
        ("menciones", procedencia.huella(rutas["menciones"])),
        ("excluir", [procedencia.huella(r) for r in excluir]),
    ])
    huellas.update(huellas_de_recursos())
    registro = collections.OrderedDict([
        ("parametros", collections.OrderedDict([
            ("hoja", hoja), ("cuantos", cuantos),
            ("aceptar_base_distinta", bool(aceptar_base_distinta)),
            ("archivos_excluir", len(excluir))])),
        ("huellas", huellas),
        ("resultado", resultado),
    ])
    contraste._escribir_texto(
        os.path.join(confidencial, ARCHIVO_REGISTRO),
        json.dumps(registro, ensure_ascii=False, indent=2) + "\n")
    if informe:
        contraste._escribir_texto(informe, texto)

    for linea in lineas:
        log(linea)
    log("Escrito en la carpeta de --confidencial: %s%s."
        % (ARCHIVO_REGISTRO,
           "; el informe, en la ruta de --informe" if informe else ""))
    return resultado
