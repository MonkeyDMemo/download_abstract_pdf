# -*- coding: utf-8 -*-
"""Visor de la red: un HTML autocontenido para explorar una carpeta del flujo.

    python visor_red.py --carpeta salidas/flujo/corrida4_run22 --salida visor.html

Se busca un gen (símbolo o locus) y se ven sus reguladores y sus blancos.
Cada arista trae su signo, cuántos artículos la sostienen y sus oraciones,
con el regulador y el blanco resaltados y el enlace a PubMed. Si el flujo ya
corrió el paso `juez`, cada arista y cada oración traen el veredicto del
agente (Ouroboros), que marca y no filtra.

Lee `red.tsv` o, si existe, `red_juez.tsv`, y sus evidencias. Todo va dentro
del archivo: no carga nada de internet y se abre con doble clic. Para que no
pese de más, cada arista lleva a lo más `--max-oraciones` oraciones (las de
mayor probabilidad del clasificador).

Solo biblioteca estándar.
"""

import argparse
import csv
import io
import json
import os
import sys

MAX_ORACIONES = 3
SIGNOS = {"activates": "+", "represses": "-", "regulates": "?"}


def _leer_tsv(ruta):
    with io.open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _entero(v, defecto=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return defecto


def _flotante(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def datos_de_carpeta(carpeta, max_oraciones=MAX_ORACIONES):
    juez = os.path.isfile(os.path.join(carpeta, "red_juez.tsv"))
    red = _leer_tsv(os.path.join(carpeta, "red_juez.tsv" if juez
                                 else "red.tsv"))
    evidencias = _leer_tsv(os.path.join(
        carpeta, "red_evidencias_juez.tsv" if juez else "red_evidencias.tsv"))
    por_arista = {}
    for ev in evidencias:
        por_arista.setdefault((ev["tf"], ev["blanco"]), []).append(ev)
    aristas = []
    pmids = set()
    for a in red:
        # El mismo orden que el tope del juez (grn_verificacion.juez.recortar):
        # así las oraciones que enseña el visor son las que juzgó el agente.
        evs = sorted(por_arista.get((a["tf"], a["blanco"]), []),
                     key=lambda e: (-_flotante(e.get("probabilidad")),
                                    e.get("pmid") or "", e.get("id_par") or ""))
        for e in evs:
            pmids.add(e.get("pmid", ""))
        aristas.append([
            a["tf"], a["blanco"], SIGNOS.get(a.get("signo") or "", "?"),
            _entero(a.get("n_articulos")), _entero(a.get("n_evidencias")),
            1 if a.get("conflicto") == "true" else 0,
            a.get("veredicto_agente", "") if juez else "",
            [[e.get("pmid", ""), e.get("seccion", ""), e.get("oracion", ""),
              round(_flotante(e.get("probabilidad")), 3),
              e.get("veredicto_agente", "") if juez else ""]
             for e in evs[:max_oraciones]],
            a.get("nivel", "") if juez else "",
            SIGNOS.get({"+": "activates", "-": "represses"}.get(
                a.get("signo_agente") or "", ""), "") if juez else "",
        ])
    aristas.sort(key=lambda x: (-x[3], -x[4], x[0], x[1]))
    nombre = os.path.basename(os.path.normpath(carpeta))
    return {"carpeta": nombre, "juez": juez, "aristas": aristas,
            "n_articulos": len(pmids - {""}),
            "max_oraciones": max_oraciones}


def _json_seguro(objeto):
    """JSON que no puede cerrar el <script> ni abrir un comentario."""
    texto = json.dumps(objeto, ensure_ascii=False, separators=(",", ":"))
    return (texto.replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


PLANTILLA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visor de la red · __TITULO__</title>
<style>
:root { --fondo:#16171f; --panel:#1f2130; --panel2:#262838; --borde:#33364a;
  --texto:#e8e8f0; --tenue:#9a9cb0; --acento:#9184d9; --ok:#7ddba4;
  --mal:#ef8a8a; --alerta:#e8c46a; --radio:10px; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto);
  font:14px/1.5 "Segoe UI", system-ui, sans-serif; }
header { padding:18px 24px; border-bottom:1px solid var(--borde); }
h1 { margin:0 0 4px; font-size:20px; }
.sub { color:var(--tenue); font-size:13px; }
main { padding:18px 24px 60px; max-width:1200px; margin:0 auto; }
.barra { display:flex; flex-wrap:wrap; gap:10px; align-items:center;
  margin-bottom:14px; }
input[type=search] { flex:1 1 260px; padding:10px 12px; border-radius:var(--radio);
  border:1px solid var(--borde); background:var(--panel); color:var(--texto);
  font-size:15px; }
select { padding:8px 10px; border-radius:var(--radio); border:1px solid var(--borde);
  background:var(--panel); color:var(--texto); }
.cifras { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
.cifra { background:var(--panel); border:1px solid var(--borde); border-radius:var(--radio);
  padding:8px 14px; }
.cifra b { font-size:18px; display:block; }
.cifra span { color:var(--tenue); font-size:12px; }
.top { margin-bottom:16px; }
.top button { margin:3px; padding:4px 10px; border-radius:999px; cursor:pointer;
  border:1px solid var(--borde); background:var(--panel2); color:var(--texto); font-size:12.5px; }
.top button:hover { border-color:var(--acento); }
.arista { background:var(--panel); border:1px solid var(--borde); border-radius:var(--radio);
  margin-bottom:8px; }
.cab { display:flex; gap:10px; align-items:center; padding:10px 14px; cursor:pointer;
  flex-wrap:wrap; }
.cab:hover { background:var(--panel2); border-radius:var(--radio); }
.par { font-weight:600; font-size:15px; min-width:220px; }
.flecha { color:var(--acento); margin:0 6px; }
.chip { font-size:11.5px; border-radius:999px; padding:1px 9px; border:1px solid var(--borde);
  color:var(--tenue); white-space:nowrap; }
.chip.mas { color:var(--ok); } .chip.menos { color:var(--mal); }
.chip.conf { color:var(--alerta); }
.ag-confirmada, .v-confirma { color:var(--ok); border-color:#3e6b52; }
.ag-rechazada, .v-rechaza { color:var(--mal); border-color:#7a3f3f; }
.ag-invertida, .v-invierte { color:var(--alerta); border-color:#7a6430; }
.ag-dudosa, .v-dudosa, .ag-sin_juicio, .v-abstiene { color:var(--tenue); }
.evs { display:none; padding:0 14px 12px; }
.arista.abierta .evs { display:block; }
.ev { border-top:1px solid var(--borde); padding:8px 0; font-size:13.5px; }
.ev .meta { color:var(--tenue); font-size:12px; margin-bottom:3px; display:flex; gap:8px;
  flex-wrap:wrap; align-items:center; }
.ev a { color:var(--acento); }
mark { background:rgba(145,132,217,.28); color:var(--texto); border-radius:3px; padding:0 2px; }
mark.b { background:rgba(125,219,164,.22); }
.nota { color:var(--tenue); font-size:12.5px; margin-top:18px; }
.mas-res { text-align:center; margin:14px 0; }
.mas-res button { padding:8px 16px; border-radius:var(--radio); border:1px solid var(--borde);
  background:var(--panel2); color:var(--texto); cursor:pointer; }
.chip.nivel-alta{background:#DDF3E6;color:#1E6B3A;font-weight:600}.chip.nivel-media{background:#FFF1CC;color:#7A5B00}.chip.nivel-sin_respaldo{background:#EEE;color:#666}
</style></head>
<body>
<header>
  <h1>Visor de la red · <span id="nombre"></span></h1>
  <div class="sub">Cada arista es una relación regulador → blanco propuesta a
  partir de la literatura, con las oraciones que la sostienen. Es una propuesta
  para revisar, no una relación confirmada.</div>
</header>
<main>
  <div class="cifras" id="cifras"></div>
  <div class="barra">
    <input type="search" id="q" placeholder="Busca un gen o locus: lasR, PA1430, algU…" autocomplete="off">
    <select id="f-soporte"><option value="0">Todo soporte</option>
      <option value="2">2 o más artículos</option><option value="5">5 o más artículos</option></select>
    <select id="f-signo"><option value="">Todo signo</option><option value="+">Activa (+)</option>
      <option value="-">Reprime (−)</option><option value="?">Sin signo</option></select>
    <select id="f-agente"><option value="">Todo veredicto del agente</option>
      <option value="confirmada">Confirmada</option><option value="invertida">Invertida</option>
      <option value="dudosa">Dudosa</option><option value="rechazada">Rechazada</option>
      <option value="sin_juicio">Sin juicio</option></select>
    <select id="f-nivel"><option value="">Toda confianza</option>
      <option value="alta">Alta (todo el jurado)</option><option value="media">Media</option>
      <option value="sin_respaldo">Sin respaldo</option></select>
  </div>
  <div class="top" id="top"></div>
  <div id="lista"></div>
  <div class="mas-res" id="mas"></div>
  <p class="nota" id="nota"></p>
</main>
<script id="datos" type="application/json">__DATOS__</script>
<script>
(function () {
"use strict";
const D = JSON.parse(document.getElementById("datos").textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const NOMBRE_SIGNO = {"+":"activa", "-":"reprime", "?":"sin signo"};
let PAGINA = 100, mostrar = PAGINA;

$("nombre").textContent = D.carpeta;
document.title = "Visor de la red · " + D.carpeta;
const hayNivel = D.aristas.some(a => a[8]);
if (!D.juez) { $("f-agente").style.display = "none"; }
if (!hayNivel) { $("f-nivel").style.display = "none"; }

const genes = new Set();
D.aristas.forEach(a => { genes.add(a[0]); genes.add(a[1]); });
const cifras = [[D.aristas.length.toLocaleString("es-MX"), "aristas"],
  [genes.size.toLocaleString("es-MX"), "genes"],
  [D.n_articulos.toLocaleString("es-MX"), "artículos con evidencia"],
  [D.aristas.filter(a => a[3] >= 2).length.toLocaleString("es-MX"), "aristas con 2 o más artículos"]];
if (D.juez) {
  cifras.push([D.aristas.filter(a => a[6] === "confirmada").length.toLocaleString("es-MX"),
               "confirmadas por el agente"]);
}
if (hayNivel) {
  cifras.push([D.aristas.filter(a => a[8] === "alta").length.toLocaleString("es-MX"),
               "de confianza alta (todo el jurado)"]);
}
$("cifras").innerHTML = cifras.map(c => `<div class="cifra"><b>${c[0]}</b><span>${c[1]}</span></div>`).join("");

const grado = {};
D.aristas.forEach(a => { grado[a[0]] = (grado[a[0]] || 0) + 1; });
const top = Object.entries(grado).sort((x, y) => y[1] - x[1]).slice(0, 24);
$("top").innerHTML = "<span class='sub'>Reguladores con más blancos: </span>" +
  top.map(t => `<button data-gen="${esc(t[0])}">${esc(t[0])} · ${t[1]}</button>`).join("");
$("top").addEventListener("click", (e) => {
  const g = e.target.getAttribute("data-gen");
  if (g) { $("q").value = g; mostrar = PAGINA; pintar(); }
});

function resaltar(oracion, tf, blanco) {
  let html = esc(oracion);
  const marca = (nombre, clase) => {
    if (!nombre) return;
    const re = new RegExp("(^|[^A-Za-z0-9])(" + esc(nombre).replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")(?![A-Za-z0-9])", "gi");
    html = html.replace(re, `$1<mark class="${clase}">$2</mark>`);
  };
  marca(tf, "r"); marca(blanco, "b");
  return html;
}

function coincide(a, q) {
  if (!q) return true;
  return a[0].toLowerCase() === q || a[1].toLowerCase() === q ||
         a[0].toLowerCase().startsWith(q) || a[1].toLowerCase().startsWith(q);
}

function pintar() {
  const q = $("q").value.trim().toLowerCase();
  const soporte = +$("f-soporte").value, signo = $("f-signo").value, agente = $("f-agente").value;
  const nv = $("f-nivel").value;
  const res = D.aristas.filter(a => coincide(a, q) && a[3] >= soporte &&
    (!signo || a[2] === signo) && (!agente || a[6] === agente) && (!nv || a[8] === nv));
  const vista = res.slice(0, mostrar);
  $("lista").innerHTML = vista.map((a, i) => {
    const sig = `<span class="chip ${a[2] === "+" ? "mas" : a[2] === "-" ? "menos" : ""}">${NOMBRE_SIGNO[a[2]]}</span>`;
    const conf = a[5] ? `<span class="chip conf">votos en conflicto</span>` : "";
    const ag = a[6] ? `<span class="chip ag-${a[6]}">agente: ${a[6].replace("_", " ")}</span>` : "";
    const NIVEL = {"alta": "confianza alta", "media": "confianza media", "sin_respaldo": "sin respaldo"};
    const niv = a[8] ? `<span class="chip nivel-${a[8]}">${NIVEL[a[8]]}</span>` : "";
    const sag = a[9] && a[9] !== a[2] && (a[6] === "confirmada" || a[6] === "invertida") ?
      `<span class="chip">jurado: ${NOMBRE_SIGNO[a[9]]}</span>` : "";
    const evs = a[7].map(e => `<div class="ev"><div class="meta">
        <a href="https://pubmed.ncbi.nlm.nih.gov/${esc(e[0])}/" target="_blank" rel="noopener">PMID ${esc(e[0])}</a>
        <span>${esc(e[1] || "")}</span><span>BioBERT ${e[3]}</span>
        ${e[4] ? `<span class="chip v-${e[4]}">agente: ${e[4]}</span>` : ""}</div>
        ${resaltar(e[2], a[0], a[1])}</div>`).join("");
    const resto = a[4] > a[7].length ? `<div class="ev meta">… y ${a[4] - a[7].length} oraciones más.</div>` : "";
    return `<div class="arista"><div class="cab" data-i="${i}">
      <span class="par">${esc(a[0])}<span class="flecha">→</span>${esc(a[1])}</span>
      ${sig}<span class="chip">${a[3]} artículo${a[3] === 1 ? "" : "s"}</span>${conf}${ag}${niv}${sag}</div>
      <div class="evs">${evs}${resto}</div></div>`;
  }).join("") || "<p class='sub'>Ninguna arista con esos filtros.</p>";
  $("mas").innerHTML = res.length > mostrar ?
    `<button id="btn-mas">Mostrar más (${(res.length - mostrar).toLocaleString("es-MX")} restantes)</button>` : "";
  $("nota").textContent = `${res.length.toLocaleString("es-MX")} aristas con estos filtros. ` +
    `Cada arista muestra hasta ${D.max_oraciones} oraciones, las de mayor probabilidad del clasificador.` +
    (D.juez ? " El veredicto del agente es exploratorio: marca, no filtra." : "");
}
$("lista").addEventListener("click", (e) => {
  const cab = e.target.closest(".cab");
  if (cab && !e.target.closest("a")) cab.parentElement.classList.toggle("abierta");
});
$("mas").addEventListener("click", (e) => {
  if (e.target.id === "btn-mas") { mostrar += PAGINA; pintar(); }
});
["q", "f-soporte", "f-signo", "f-agente", "f-nivel"].forEach(id =>
  $(id).addEventListener("input", () => { mostrar = PAGINA; pintar(); }));
pintar();
})();
</script>
</body></html>
"""


def escribir(carpeta, salida, max_oraciones=MAX_ORACIONES):
    datos = datos_de_carpeta(carpeta, max_oraciones)
    html = (PLANTILLA.replace("__TITULO__", datos["carpeta"])
            .replace("__DATOS__", _json_seguro(datos)))
    os.makedirs(os.path.dirname(os.path.abspath(salida)), exist_ok=True)
    with io.open(salida, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return datos


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--carpeta", required=True, help="Carpeta del flujo.")
    ap.add_argument("--salida", required=True, help="El HTML que se escribe.")
    ap.add_argument("--max-oraciones", type=int, default=MAX_ORACIONES,
                    dest="max_oraciones")
    args = ap.parse_args(argv)
    if not os.path.isfile(os.path.join(args.carpeta, "red.tsv")):
        print("ERROR: %s no tiene red.tsv." % args.carpeta, file=sys.stderr)
        return 1
    datos = escribir(args.carpeta, args.salida, args.max_oraciones)
    print("Escrito %s: %d aristas%s." % (
        args.salida, len(datos["aristas"]),
        ", con el veredicto del agente" if datos["juez"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
