# -*- coding: utf-8 -*-
"""Las gráficas de «resumen contra texto completo».

No es parte del núcleo: necesita matplotlib, en el entorno del reporte.

    .venv-reporte/Scripts/python docs/reporte/graficas_fuentes.py \
        [--datos salidas/fuentes] [--salida salidas/fuentes/figuras]

Lee de `--datos` (todo conteos):
- `fuentes_corrida20.json`, `fuentes_corrida16.json` y
  `fuentes_corrida22.json` (los nuevos con PDF): `cli fuentes`;
- `precision_t1_por_origen.json` y `precision_t2_por_origen.json`:
  `cli precision-ciega`;
- `cobertura.json`: `db.cobertura_corpus` de cada corpus;
- `base_curada_por_origen.json`: conteos del servidor;
- `openalex_prueba.json`: la prueba de descarga con OpenAlex, sin llave;
- `openalex_con_llave.json`: la descarga de las copias de OpenAlex;
- `nuevos_resumen_vs_pdf.json`: los nuevos, solo resúmenes contra con PDF.
Las figuras que no tienen su archivo se saltan.
"""
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

MORADO, VERDE, AMBAR = "#7A6BD1", "#3E9B6A", "#C8962E"
GRIS, GRIS_CLARO, ROJO = "#5B5F74", "#C9CAD6", "#C0504D"
COLOR = {"resumen": MORADO, "cuerpo_xml": VERDE, "cuerpo_pdf": AMBAR}
NOMBRE = {"resumen": "Resumen", "cuerpo_xml": "Cuerpo (XML de PMC)",
          "cuerpo_pdf": "Cuerpo (PDF)"}
NIVEL = [("alta", "Confianza alta", "#2E7D4F"), ("media", "Media", "#9CCB86"),
         ("al_reves", "Flecha al revés", "#E3A857"),
         ("sin_respaldo", "Sin respaldo", GRIS_CLARO)]
plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titlesize": 11,
                     "axes.titleweight": "bold", "figure.dpi": 150})


def n(x):
    return "{:,}".format(x)


def leer(carpeta, nombre):
    ruta = os.path.join(carpeta, nombre)
    if not os.path.isfile(ruta):
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def barras_apiladas(ax, filas, titulo, total=True):
    """filas: [(etiqueta, [(valor, color, nombre)])], de arriba hacia abajo."""
    for i, (etiqueta, partes) in enumerate(reversed(filas)):
        izquierda = 0
        for valor, color, _nombre in partes:
            ax.barh(i, valor, left=izquierda, color=color, edgecolor="white")
            izquierda += valor
        if total:
            ax.text(izquierda, i, "  " + n(izquierda), va="center")
    ax.set_yticks(range(len(filas)))
    ax.set_yticklabels([e for e, _ in reversed(filas)])
    ax.set_title(titulo, loc="left")
    ax.xaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, _p: n(int(v))))
    ax.margins(x=0.16)


def leyenda(ax, partes, **kw):
    manos = [plt.Rectangle((0, 0), 1, 1, color=c) for _v, c, _n in partes]
    ax.legend(manos, [nm for _v, _c, nm in partes], frameon=False, **kw)


def embudo_articulos(datos, salida):
    cob, f20, f16 = (leer(datos, "cobertura.json"),
                     leer(datos, "fuentes_corrida20.json"),
                     leer(datos, "fuentes_corrida16.json"))
    if not (cob and f20):
        return
    # La barra de «con alguna candidata» sale de la corrida más reciente.
    f20 = leer(datos, "fuentes_corrida25.json") or f20
    oa = {r["corpus"]: r for r in leer(datos, "openalex_prueba.json") or []}
    fig, ejes = plt.subplots(1, 2, figsize=(12, 3.9),
                             gridspec_kw={"width_ratios": [1.25, 1]})
    c = cob["v0-agosto"]
    af = f20["embudo"]["articulos_por_fuente"]
    xml, pdf = c["xml_ok"], c["pdf_ok_sin_xml"]
    filas = [
        ("Descargados de PubMed", [(c["documentos"], GRIS, "")]),
        ("Con resumen", [(c["con_abstract"], "#8E8FA3", "")]),
        ("Con texto completo", [(xml, VERDE, "XML de PMC"),
                                (pdf, AMBAR, "PDF (sin XML)")]),
        ("Solo con resumen", [(c["sin_texto_completo"], MORADO, "")]),
        ("Con alguna oración\ncandidata", [
            (af.get("abstract", 0), MORADO, ""), (af.get("xml", 0), VERDE, ""),
            (af.get("pdf", 0), AMBAR, "")]),
    ]
    barras_apiladas(ejes[0], filas, "Corpus de agosto: artículos")
    leyenda(ejes[0], [(0, MORADO, "Solo resumen"), (0, VERDE, "XML de PMC"),
                      (0, AMBAR, "PDF (sin XML)")], loc="center right")
    c = cob["nuevos-20261104"]
    f22 = leer(datos, "fuentes_corrida22.json")
    filas = [
        ("Descargados de PubMed", [(c["documentos"], GRIS, "")]),
        ("Con resumen", [(c["con_abstract"], "#8E8FA3", "")]),
    ]
    if c.get("pdf_ok_sin_xml"):
        filas.append(("Con texto completo\n(PDF de OpenAlex)", [
            (c.get("pdf_version_publicada", c["pdf_ok_sin_xml"]), AMBAR,
             "PDF, versión publicada"),
            (c.get("pdf_version_enviada", 0), "#E6C98A",
             "PDF, versión enviada (preprint)")]))
        filas.append(("Solo con resumen",
                      [(c["sin_texto_completo"], MORADO, "")]))
    elif "nuevos-20261104" in oa:
        filas.append(("PDF abierto bajado en la\nprueba de OpenAlex", [
            (oa["nuevos-20261104"]["descargas"].get("ok", 0), AMBAR, "")]))
    if f22:
        af = f22["embudo"]["articulos_por_fuente"]
        filas.append(("Con alguna oración\ncandidata", [
            (af.get("abstract", 0), MORADO, ""), (af.get("pdf", 0), AMBAR, "")]))
    elif f16:
        filas.append(("Con alguna oración\ncandidata", [
            (f16["embudo"]["articulos_con_candidatas"], MORADO, "")]))
    barras_apiladas(ejes[1], filas, "Artículos nuevos (19-ago a 4-nov)",
                    total=False)
    for i, (etiqueta, partes) in enumerate(reversed(filas)):
        total = sum(v for v, _c, _n in partes)
        texto = n(total)
        if etiqueta.startswith("Con texto completo") and len(partes) == 2:
            texto += " (%d versión publicada,\n      %d preprint)" % (
                partes[0][0], partes[1][0])
        ejes[1].text(total, i, "  " + texto, va="center")
    ejes[1].margins(x=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig1_embudo_articulos.png"))
    plt.close(fig)


def embudo_evidencia(datos, salida):
    f20 = leer(datos, "fuentes_corrida20.json")
    if not f20:
        return
    po = f20["embudo"]["por_origen"]
    fig, ejes = plt.subplots(1, 2, figsize=(12, 3.4),
                             gridspec_kw={"width_ratios": [1.6, 1]})
    etapas = [("Oraciones candidatas", "oraciones_candidatas"),
              ("Pares que clasifica\nel BioBERT", "pares"),
              ("Pares sobre el umbral", "pares_sobre_umbral")]
    filas = [(et, [(po[o][k], COLOR[o], NOMBRE[o]) for o in COLOR if o in po])
             for et, k in etapas]
    barras_apiladas(ejes[0], filas, "Red con PDF: de dónde sale la evidencia")
    leyenda(ejes[0], filas[0][1], loc="upper right")
    por_articulo = [(NOMBRE[o], po[o]["oraciones_candidatas"] / po[o]["articulos"],
                     COLOR[o]) for o in COLOR if o in po]
    ax = ejes[1]
    for i, (nombre, valor, color) in enumerate(reversed(por_articulo)):
        ax.barh(i, valor, color=color)
        ax.text(valor, i, "  %.1f" % valor, va="center")
    ax.set_yticks(range(len(por_articulo)))
    ax.set_yticklabels([x[0] for x in reversed(por_articulo)])
    ax.set_title("Oraciones candidatas por artículo", loc="left")
    ax.margins(x=0.15)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig2_embudo_evidencia.png"))
    plt.close(fig)


def buenas_y_malas(datos, salida):
    f20 = leer(datos, "fuentes_corrida20.json")
    if not (f20 and f20.get("jurado")):
        return
    base = leer(datos, "base_curada_por_origen.json")
    fig, ejes = plt.subplots(1, 3 if base else 2,
                             figsize=(13.5 if base else 9.5, 3.8))
    # a) el jurado, por oración juzgada
    ax = ejes[0]
    partes = [("confirma", "Confirma", "#2E7D4F"),
              ("invierte", "Flecha al revés", "#E3A857"),
              ("dudosa", "Dudosa", "#8E8FA3"), ("rechaza", "Rechaza", GRIS_CLARO)]
    origenes = [o for o in COLOR if o in f20["jurado"]]
    for i, o in enumerate(reversed(origenes)):
        j = f20["jurado"][o]
        izquierda = 0.0
        for clave, _nm, color in partes:
            v = j[clave] + (j["abstiene"] if clave == "dudosa" else 0)
            pct = 100.0 * v / j["juzgadas"]
            ax.barh(i, pct, left=izquierda, color=color, edgecolor="white")
            if pct >= 10:
                ax.text(izquierda + pct / 2, i, "%.0f %%" % pct, va="center",
                        ha="center", color="white" if clave == "confirma"
                        else "black", fontsize=9)
            izquierda += pct
    ax.set_yticks(range(len(origenes)))
    ax.set_yticklabels(["%s\n(%s oraciones)" % (
        NOMBRE[o].replace(" (", "\n("), n(f20["jurado"][o]["juzgadas"]))
        for o in reversed(origenes)], fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% de las oraciones que juzgó el jurado")
    ax.set_title("a) Por oración: veredicto del jurado", loc="left")
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=c) for _k, _n, c in partes],
              [nm for _k, nm, _c in partes], frameon=False, ncol=2,
              loc="upper center", bbox_to_anchor=(0.5, -0.22), fontsize=9)
    # b) aristas por el origen de su evidencia
    clases = [("solo_resumen", "Solo en resúmenes"),
              ("resumen_y_cuerpo", "En resumen\ny en cuerpo"),
              ("solo_cuerpo", "Solo en el cuerpo")]
    pc = f20["aristas"]["por_clase"]
    filas = [(nm, [(pc[c]["nivel"][k], color, nombre)
                   for k, nombre, color in NIVEL]) for c, nm in clases]
    barras_apiladas(ejes[1], filas, "b) Por arista: nivel del jurado")
    ejes[1].legend(
        [plt.Rectangle((0, 0), 1, 1, color=c) for _k, _n, c in NIVEL],
        [nm for _k, nm, _c in NIVEL], frameon=False, ncol=2,
        loc="upper center", bbox_to_anchor=(0.5, -0.22), fontsize=9)
    ejes[1].set_xlabel("aristas")
    # c) en la base curada
    if base:
        ax = ejes[2]
        for i, (c, nm) in enumerate(reversed(clases)):
            total, en = base["por_clase"][c]
            ax.barh(i, en, color="#2E7D4F")
            ax.text(en, i, "  %s de %s (%.1f %%)" % (n(en), n(total),
                                                    100.0 * en / total),
                    va="center", fontsize=9)
        ax.set_yticks(range(len(clases)))
        ax.set_yticklabels([nm for _c, nm in reversed(clases)])
        ax.set_xlabel("aristas que están en la base curada")
        ax.set_title("c) Por arista: en la base curada", loc="left")
        ax.margins(x=0.45)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig3_buenas_y_malas.png"))
    plt.close(fig)


def experto(datos, salida):
    t1, t2 = (leer(datos, "precision_t1_por_origen.json"),
              leer(datos, "precision_t2_por_origen.json"))
    if not (t1 and t2 and t1.get("por_origen") and t2.get("por_origen")):
        return
    fig, ejes = plt.subplots(1, 2, figsize=(10.5, 3.6), sharey=True)
    for ax, (r, titulo) in zip(ejes, ((t1, "Tanda 1 (desarrollo, 198 oraciones)"),
                                      (t2, "Tanda 2 (prueba, 100 oraciones)"))):
        origenes = [o for o in ("resumen", "cuerpo_xml") if o in r["por_origen"]]
        for i, o in enumerate(origenes):
            g = r["por_origen"][o]
            for j, (clave, nombre, tono) in enumerate(
                    (("bronce", "Sin filtro", 0.45), ("red", "Red (BioBERT)", 1.0))):
                p = g[clave]
                if p["valor"] is None:
                    continue
                x = i + (j - 0.5) * 0.36
                v = 100 * p["valor"]
                ax.bar(x, v, width=0.32, color=COLOR[o], alpha=tono,
                       yerr=[[v - 100 * p["ic95"][0]], [100 * p["ic95"][1] - v]],
                       ecolor=GRIS, capsize=3)
                ax.text(x, 2, "%d/%d" % (p["k"], p["n"]), ha="center",
                        va="bottom", fontsize=8.5,
                        color="white" if tono == 1.0 else "black")
                ax.text(x, 100 * p["ic95"][1] + 2, "%.0f %%" % v, ha="center",
                        fontsize=9)
                ax.text(x, -9, nombre, ha="center", fontsize=8)
        ax.set_xticks(range(len(origenes)))
        ax.set_xticklabels(["%s\n(%d oraciones)" % (
            "Resumen" if o == "resumen" else "Cuerpo (XML)",
            r["por_origen"][o]["n"]) for o in origenes])
        ax.tick_params(axis="x", pad=16)
        ax.set_ylim(0, 100)
        ax.set_title(titulo, loc="left")
    ejes[0].set_ylabel("precisión con dirección (%)")
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig4_experto.png"))
    plt.close(fig)


def openalex_con_llave(datos, salida):
    """Las copias que guarda OpenAlex: bajadas, pendientes y descartadas."""
    d = leer(datos, "openalex_con_llave.json")
    if not d:
        return False
    previa = {r["corpus"]: r for r in leer(datos, "openalex_prueba.json") or []}
    filas_de = d["corpus"]
    fig, ejes = plt.subplots(1, len(filas_de), figsize=(6 * len(filas_de), 3.4))
    ejes = [ejes] if len(filas_de) == 1 else list(ejes)
    titulos = {"v0-agosto": "Corpus de agosto: artículos sin texto completo",
               "nuevos-20261104": "Artículos nuevos"}
    VERDE_OSCURO, CLARO = "#2E7D4F", "#F0DDB0"
    for ax, r in zip(ejes, filas_de):
        filas = [("Sin texto completo", [(r["sin_texto_completo"], GRIS, "")])]
        if r["corpus"] in previa:
            filas.append(("Bajados sin llave\n(ligas abiertas, 16-nov)", [
                (previa[r["corpus"]]["descargas"].get("ok", 0), VERDE, "")]))
        filas.append(("Con copia del PDF\nen OpenAlex", [
            (r["con_copia_en_openalex"], AMBAR, "")]))
        filas.append(("Bajados con la llave\n(24-nov)", [
            (r["son_el_articulo"], VERDE_OSCURO, "Bajado y es el artículo"),
            (r["no_son_el_articulo"] + r.get("sin_contenido", 0), ROJO,
             "Descartado"),
            (r["pendientes"], CLARO, "Pendiente (100 al día)")]))
        barras_apiladas(ax, filas, titulos.get(r["corpus"], r["corpus"]),
                        total=False)
        for i, (_e, partes) in enumerate(reversed(filas)):
            texto = " + ".join(n(v) for v, _c, _n in partes if v) or "0"
            ax.text(sum(v for v, _c, _n in partes), i, "  " + texto,
                    va="center")
        ax.tick_params(axis="y", labelsize=9)
    leyenda(ejes[0], [(0, VERDE_OSCURO, "Bajado y es el artículo"),
                      (0, ROJO, "Descartado"),
                      (0, CLARO, "Pendiente (100 al día)")],
            loc="lower right", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig5_openalex.png"))
    plt.close(fig)
    return True


def nuevos_con_pdf(datos, salida):
    """Los artículos nuevos: solo resúmenes contra con PDF."""
    d, f22 = (leer(datos, "nuevos_resumen_vs_pdf.json"),
              leer(datos, "fuentes_corrida22.json"))
    if not (d and f22):
        return
    fig, ejes = plt.subplots(1, 2, figsize=(12, 3.3),
                             gridspec_kw={"width_ratios": [1, 1.1]})

    def por_nivel(cuenta):
        return [(cuenta.get(k, 0), color, nombre) for k, nombre, color in NIVEL]

    def rotular(ax, filas):
        for i, (_e, partes) in enumerate(reversed(filas)):
            total = sum(v for v, _c, _n in partes)
            buenas = partes[0][0] + partes[1][0]
            ax.text(total, i, "  %s (confirma %d)" % (n(total), buenas),
                    va="center")

    filas = [("Solo resúmenes\n(40 artículos)",
              por_nivel(d["solo_resumenes_corrida16"]["nivel"])),
             ("Con los 27 PDF\n(mismos 40 artículos)",
              por_nivel(d["con_pdf_corrida22"]["nivel"]))]
    barras_apiladas(ejes[0], filas, "a) Relaciones de los artículos nuevos",
                    total=False)
    rotular(ejes[0], filas)
    ejes[0].margins(x=0.32)
    clases = f22["aristas"]["por_clase"]
    filas = [(nombre, por_nivel(clases[c]["nivel"])) for c, nombre in (
        ("solo_resumen", "Solo en resúmenes"),
        ("resumen_y_cuerpo", "En resumen\ny en cuerpo"),
        ("solo_cuerpo", "Solo en el cuerpo\n(PDF)"))]
    barras_apiladas(ejes[1], filas, "b) Con PDF: dónde está la evidencia",
                    total=False)
    rotular(ejes[1], filas)
    ejes[1].margins(x=0.32)
    leyenda(ejes[1], por_nivel({}), loc="upper right", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig6_nuevos_con_pdf.png"))
    plt.close(fig)


def openalex(datos, salida):
    if openalex_con_llave(datos, salida):
        return
    oa = leer(datos, "openalex_prueba.json")
    if not oa:
        return
    fig, ejes = plt.subplots(1, len(oa), figsize=(6 * len(oa), 3.3))
    ejes = [ejes] if len(oa) == 1 else list(ejes)
    titulos = {"v0-agosto": "Corpus de agosto: artículos sin texto completo",
               "nuevos-20261104": "Artículos nuevos"}
    for ax, r in zip(ejes, oa):
        filas = [
            ("Sin texto completo", r["sin_texto_completo"], GRIS),
            ("Acceso abierto\nsegún OpenAlex", r.get("es_acceso_abierto", 0), MORADO),
            ("Con liga de PDF abierto", r["con_liga_pdf_abierta"], VERDE),
            ("PDF bajado y verificado", r["descargas"].get("ok", 0), "#2E7D4F"),
            ("Con copia en OpenAlex\n(pide llave)", r.get("copia_pdf_en_openalex", 0),
             AMBAR),
        ]
        for i, (_e, v, color) in enumerate(reversed(filas)):
            ax.barh(i, v, color=color)
            ax.text(v, i, "  " + n(v), va="center")
        ax.set_yticks(range(len(filas)))
        ax.set_yticklabels([e for e, _v, _c in reversed(filas)], fontsize=9)
        ax.set_title(titulos.get(r["corpus"], r["corpus"]), loc="left")
        ax.margins(x=0.15)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "fig5_openalex.png"))
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default=os.path.join("salidas", "fuentes"))
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    salida = args.salida or os.path.join(args.datos, "figuras")
    os.makedirs(salida, exist_ok=True)
    for figura in (embudo_articulos, embudo_evidencia, buenas_y_malas,
                   experto, openalex, nuevos_con_pdf):
        figura(args.datos, salida)
    for nombre in sorted(os.listdir(salida)):
        print(os.path.join(salida, nombre))


if __name__ == "__main__":
    main()
