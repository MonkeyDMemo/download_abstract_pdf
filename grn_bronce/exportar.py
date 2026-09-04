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

COLUMNAS_CANDIDATAS = [
    "pmid", "doi", "titulo", "anio", "revista", "fecha_ingesta",
    "fuente_texto", "seccion", "num_oracion", "oracion",
    "genes", "genes_locus_tag", "proteinas",
    "regulador_candidato", "blanco_candidato",
    "disparador", "signo_sugerido",
    "funciones_biologicas", "evidencia_experimental", "organismo",
    "score", "metodo", "version", "corrida_id", "fecha_corrida",
]

COLUMNAS_MENCIONES = [
    "pmid", "fuente_texto", "seccion", "num_oracion", "tipo", "texto",
    "id_normalizado", "offset_ini", "offset_fin",
    "metodo", "version", "corrida_id",
]

# Las dos columnas que no afirman lo que su nombre sugiere, y hay que decirlo
# donde se leen y no en una nota al pie que nadie abre.
AVISOS = {
    "signo_sugerido": "signo_sugerido (NO VERIFICADO)",
    "score": "score: ordena, no es umbral; sin calibrar",
}


def _encabezado_visible(columna):
    """Lo que ve una persona. El nombre de la columna en los CSV no cambia:
    es parte del contrato tabular y otra cosa lo consume."""
    return AVISOS.get(columna, columna)


def filas_candidatas(con, db, corrida_id):
    """La hoja 1, armada desde las tablas.

    Las columnas agregadas --`genes`, `proteinas`, `funciones_biologicas`...--
    se derivan de `menciones`, que es donde viven de verdad. Repetirlas en
    `oraciones_candidatas` habria sido guardar dos veces lo mismo y abrir la
    puerta a que las dos copias dejen de coincidir.
    """
    por_unidad = db.menciones_por_unidad_candidata(con, corrida_id)
    filas = []
    for c in db.candidatas_de(con, corrida_id):
        mens = por_unidad.get(c["unidad_id"], [])

        def juntar(*tipos, **kw):
            campo = 2 if kw.get("normalizado") else 1
            return ";".join(sorted(set(
                m[campo] for m in mens if m[0] in tipos and m[campo])))

        genes = sorted(set(m[1] for m in mens if m[0] in ("gen", "proteina")))
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
                if m[0] in ("gen", "proteina")
                and str(m[2] or "").startswith("PA")))),
            "proteinas": ";".join(sorted(set(
                m[1] for m in mens if m[0] == "proteina"))),
            "regulador_candidato": c["regulador_candidato"] or "",
            "blanco_candidato": c["blanco_candidato"] or "",
            "disparador": c["disparador"] or "",
            "signo_sugerido": c["signo_sugerido"] or "",
            "funciones_biologicas": juntar("funcion"),
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


def escribir_xlsx(ruta, candidatas, menciones, resumen, log=lambda m: None):
    """Las tres hojas en un libro. Devuelve True si se escribio.

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

    for hoja in (h1, h2, h3):
        for celda in hoja[1]:
            celda.font = Font(bold=True)
        hoja.freeze_panes = "A2"

    # Anchos a ojo, no calculados: recorrer 300 000 celdas para medir la mas
    # larga cuesta mas que el valor de tener la columna justa.
    for hoja, anchos in ((h1, {"A": 11, "C": 46, "J": 90, "K": 26, "L": 22}),
                         (h2, {"A": 11, "F": 22, "G": 18}),
                         (h3, {"A": 46, "B": 30})):
        for letra, ancho in anchos.items():
            hoja.column_dimensions[letra].width = ancho
    for i in range(1, len(COLUMNAS_CANDIDATAS) + 1):
        letra = get_column_letter(i)
        if letra not in ("A", "C", "J", "K", "L"):
            h1.column_dimensions[letra].width = 16

    tmp = ruta + ".tmp"
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    libro.save(tmp)
    os.replace(tmp, ruta)
    log("  %s" % ruta)
    return True
