# -*- coding: utf-8 -*-
"""Las tres hojas, a CSV y a Excel.

**Los CSV son el producto canonico** y se escriben siempre, con `csv` de la
biblioteca estandar. El `.xlsx` es comodidad encima: se genera con openpyxl si
esta disponible y su ausencia no rompe la corrida, solo se anota. Esa asimetria
es deliberada -- lo que se apoya en un tercero deja de correr donde no se puede
instalar, y el laboratorio tiene maquinas asi.

Las tres hojas se escriben con escritura atomica: primero a `.tmp` y despues
`os.replace`. Sin eso, una interrupcion a media escritura deja un CSV cortado
que parece completo, y de paso se lleva por delante el anterior, que si servia.

No imprime: recibe un callable `log`.
"""

import csv
import io
import os

from grn_bronce import operones as _operones

COLUMNAS_CANDIDATAS = [
    "pmid", "doi", "titulo", "anio", "revista", "fecha_ingesta",
    "fuente_texto", "seccion", "num_oracion", "oracion",
    "genes", "genes_locus_tag", "proteinas",
    "operones", "genes_expandidos",
    "regulador_candidato", "blanco_candidato",
    "disparador", "signo_sugerido",
    "funciones_biologicas", "contexto_regulatorio",
    "evidencia_experimental", "organismo",
    "score", "metodo", "version", "corrida_id", "fecha_corrida",
]

COLUMNAS_MENCIONES = [
    "pmid", "fuente_texto", "seccion", "num_oracion", "tipo", "texto",
    "id_normalizado", "offset_ini", "offset_fin",
    "metodo", "version", "corrida_id",
]

COLUMNAS_OPERONES = [
    "operon", "en_catalogo", "n_genes_catalogo", "genes_expandidos",
    "n_menciones", "n_documentos", "n_oraciones", "n_candidatas",
    "superficies",
]

# Las dos columnas que no afirman lo que su nombre sugiere, y hay que decirlo
# donde se leen y no en una nota al pie que nadie abre.
AVISOS = {
    "signo_sugerido": "signo_sugerido (NO VERIFICADO)",
    "score": "score: ordena, no es umbral; sin calibrar",
    "genes_expandidos": "genes_expandidos (expansion del catalogo, no del texto)",
}


def _encabezado_visible(columna):
    """Lo que ve una persona. El nombre de la columna en los CSV no cambia:
    es parte del contrato tabular y otra cosa lo consume."""
    return AVISOS.get(columna, columna)


# Las tres clases que el diccionario PAO1 reconoce sobre el texto. `operon`
# entra aqui porque antes de tener tipo propio las menciones de operon se
# guardaban como 'gen' o 'proteina' segun su mayuscula inicial: la columna
# `genes` las traia, y tiene que seguir trayendolas. Lo que NO se mezcla es la
# expansion, que va en `genes_expandidos`.
TIPOS_DE_GEN = ("gen", "proteina", "operon")


def _catalogo_o_el_de_recursos(catalogo):
    """El catalogo que pasaron, o el de `recursos/` si no pasaron ninguno.

    La comparacion es `is None` y no un `or`, y la diferencia no es de estilo:
    `Catalogo` define `__len__`, asi que **un catalogo vacio es falsy**. Con un
    `or`, quien pasara un catalogo vacio a proposito --para exportar sin
    expansion, o para aislar una prueba-- se lo habria encontrado sustituido en
    silencio por el real de 3 030 filas, y habria visto `en_catalogo = si` y
    tres locus tag donde pidio nada.
    """
    if catalogo is None:
        return _operones.Catalogo.cargar(_operones.RUTA_POR_OMISION)
    return catalogo


def filas_candidatas(con, db, corrida_id, catalogo=None):
    """La hoja 1, armada desde las tablas.

    Las columnas agregadas --`genes`, `proteinas`, `funciones_biologicas`...--
    se derivan de `menciones`, que es donde viven de verdad. Repetirlas en
    `oraciones_candidatas` habria sido guardar dos veces lo mismo y abrir la
    puerta a que las dos copias dejen de coincidir.

    Las dos capas del operon salen en columnas separadas y eso es el punto:
    `operones` trae lo que el articulo escribio y `genes_expandidos` trae los
    locus tag que el catalogo dice que hay detras. Una oracion sobre
    `mexEF-oprN` no se convierte en tres filas ni pierde el nombre que uso el
    autor. Si el catalogo no conoce el operon, `genes_expandidos` sale vacio:
    eso es el hueco del catalogo, visible, y no una expansion inventada.
    """
    catalogo = _catalogo_o_el_de_recursos(catalogo)
    por_unidad = db.menciones_por_unidad_candidata(con, corrida_id)
    filas = []
    for c in db.candidatas_de(con, corrida_id):
        mens = por_unidad.get(c["unidad_id"], [])

        def juntar(*tipos, **kw):
            campo = 2 if kw.get("normalizado") else 1
            return ";".join(sorted(set(
                m[campo] for m in mens if m[0] in tipos and m[campo])))

        genes = sorted(set(m[1] for m in mens if m[0] in TIPOS_DE_GEN))
        # Por nombre canonico, no por superficie: `mexAB-oprM` y `MexAB-OprM`
        # son el mismo operon y expanden a los mismos genes.
        ops = sorted(set(m[2] for m in mens if m[0] == "operon" and m[2]))
        filas.append({
            "pmid": c["pmid"], "doi": c["doi"] or "",
            "titulo": c["titulo"] or "", "anio": c["anio"] or "",
            "revista": c["revista"] or "",
            "fecha_ingesta": c["fecha_ingesta"] or "",
            "fuente_texto": c["fuente_texto"], "seccion": c["seccion"] or "",
            "num_oracion": c["num_oracion"], "oracion": c["oracion"],
            "genes": ";".join(genes),
            "genes_locus_tag": ";".join(sorted(set(
                m[2] for m in mens
                if m[0] in TIPOS_DE_GEN
                and str(m[2] or "").startswith("PA")))),
            "proteinas": ";".join(sorted(set(
                m[1] for m in mens if m[0] == "proteina"))),
            # La superficie tal como la escribio el articulo, no el nombre
            # canonico: es la capa del texto.
            "operones": ";".join(sorted(set(
                m[1] for m in mens if m[0] == "operon"))),
            "genes_expandidos": ";".join(catalogo.expandir_varios(ops)),
            "regulador_candidato": c["regulador_candidato"] or "",
            "blanco_candidato": c["blanco_candidato"] or "",
            "disparador": c["disparador"] or "",
            "signo_sugerido": c["signo_sugerido"] or "",
            "funciones_biologicas": juntar("funcion"),
            # Columna aparte y no mezclada con la anterior: es otro eje. Dice
            # que la oracion habla de regulacion, no de que proceso habla, y
            # alimenta el `tipo_relacion` del paso 2.
            "contexto_regulatorio": juntar("contexto_regulatorio"),
            "evidencia_experimental": juntar("evidencia", normalizado=True),
            "organismo": juntar("organismo"),
            "score": c["score"],
            "metodo": c["metodo"], "version": c["version"],
            "corrida_id": c["corrida_id"],
            "fecha_corrida": c["fecha_corrida"],
        })
    return filas


def filas_menciones(con, db, corrida_id):
    """La hoja 2, tal cual sale de la tabla."""
    return [dict(f) for f in db.menciones_de(con, corrida_id)]


def filas_operones(con, db, corrida_id, catalogo=None):
    """El distinto de operones del corpus: que se nombro y que no se conoce.

    Dos preguntas en la misma tabla, y la segunda es la que pidio el asesor:
    cuanto se menciona cada operon, y **cuales no estan en
    `operones_pao1.tsv`**. Los que salen con `en_catalogo` en `no` son los
    huecos del catalogo, y no expanden a ningun gen: hoy `etapa2/lexico.py`
    los acuna leyendo el texto --`pqsABCDE` resuelve a una entidad en cuanto
    sus cinco miembros existen en el diccionario-- asi que el bronce sabe que
    el articulo hablo de un operon pero no de que genes se compone.

    La base aporta los conteos y el catalogo aporta el contraste. Se ordena
    por menciones porque lo que falta y aparece cien veces urge mas que lo que
    falta y aparece una.
    """
    catalogo = _catalogo_o_el_de_recursos(catalogo)
    filas = []
    for f in db.operones_del_corpus(con, corrida_id):
        nombre = f["operon"]
        filas.append({
            "operon": nombre,
            "en_catalogo": "si" if catalogo.tiene(nombre) else "no",
            "n_genes_catalogo": catalogo.n_genes(nombre),
            "genes_expandidos": ";".join(catalogo.locus_tags(nombre)),
            "n_menciones": f["n_menciones"],
            "n_documentos": f["n_documentos"],
            "n_oraciones": f["n_oraciones"],
            "n_candidatas": f["n_candidatas"],
            "superficies": f["superficies"],
        })
    return filas


def escribir_csv(ruta, columnas, filas, log=lambda m: None):
    tmp = ruta + ".tmp"
    d = os.path.dirname(ruta)
    if d:
        os.makedirs(d, exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    os.replace(tmp, ruta)
    log("  %s  (%d filas)" % (ruta, len(filas)))


def escribir_resumen_csv(ruta, resumen, log=lambda m: None):
    tmp = ruta + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["concepto", "valor"])
        for concepto, valor in resumen:
            w.writerow([concepto, valor])
    os.replace(tmp, ruta)
    log("  %s  (%d filas)" % (ruta, len(resumen)))


def escribir_xlsx(ruta, candidatas, menciones, resumen, operones=None,
                  log=lambda m: None):
    """Las cuatro hojas en un libro. Devuelve True si se escribio.

    Si openpyxl no esta, se dice y se sigue: los CSV ya salieron y son el
    producto canonico.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        log("  openpyxl no esta instalado: se omite el .xlsx. "
            "Los CSV son el producto canonico y ya estan escritos.")
        return False

    libro = Workbook()

    h1 = libro.active
    h1.title = "oraciones_candidatas"
    h1.append([_encabezado_visible(c) for c in COLUMNAS_CANDIDATAS])
    for fila in candidatas:
        h1.append([fila.get(c, "") for c in COLUMNAS_CANDIDATAS])

    h2 = libro.create_sheet("menciones")
    h2.append(COLUMNAS_MENCIONES)
    for fila in menciones:
        h2.append([fila.get(c, "") for c in COLUMNAS_MENCIONES])

    h3 = libro.create_sheet("resumen")
    h3.append(["concepto", "valor"])
    for concepto, valor in resumen:
        h3.append([concepto, valor])

    h4 = libro.create_sheet("operones")
    h4.append(COLUMNAS_OPERONES)
    for fila in (operones or []):
        h4.append([fila.get(c, "") for c in COLUMNAS_OPERONES])

    for hoja in (h1, h2, h3, h4):
        for celda in hoja[1]:
            celda.font = Font(bold=True)
        hoja.freeze_panes = "A2"

    # Anchos a ojo, no calculados: recorrer 300 000 celdas para medir la mas
    # larga cuesta mas que el valor de tener la columna justa.
    #
    # Por NOMBRE de columna y no por letra. Antes eran letras fijas ("A", "C",
    # "J", "K", "L") atadas a posiciones de COLUMNAS_CANDIDATAS: insertar una
    # columna corria todas las siguientes y los anchos pasaban a adornar la
    # columna equivocada, en silencio y sin que ninguna prueba lo notara.
    ANCHOS = {
        "pmid": 11, "titulo": 46, "oracion": 90, "genes": 26,
        "genes_locus_tag": 22, "operones": 24, "genes_expandidos": 30,
        "texto": 22, "id_normalizado": 18, "superficies": 28, "operon": 18,
    }

    def anchos_por_nombre(hoja, columnas, por_omision=16):
        for i, nombre in enumerate(columnas, 1):
            hoja.column_dimensions[get_column_letter(i)].width = ANCHOS.get(
                nombre, por_omision)

    anchos_por_nombre(h1, COLUMNAS_CANDIDATAS)
    anchos_por_nombre(h2, COLUMNAS_MENCIONES)
    anchos_por_nombre(h4, COLUMNAS_OPERONES)
    h3.column_dimensions["A"].width = 46
    h3.column_dimensions["B"].width = 30

    tmp = ruta + ".tmp"
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    libro.save(tmp)
    os.replace(tmp, ruta)
    log("  %s" % ruta)
    return True
