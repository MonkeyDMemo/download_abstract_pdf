# -*- coding: utf-8 -*-
"""La revisión ciega en un solo archivo HTML, sin servidor.

    python revision_portatil.py exportar-html (--carpeta C | --hoja H) --salida P.html
        [--guia docs/guia-anotacion.md] [--titulo T]
    python revision_portatil.py desde-respaldo --respaldo R.json (--carpeta C | --hoja H)
        --salida anotaciones_exportadas.csv

Para quien anota fuera del laboratorio, donde no corre `servidor.py`. Abre el
HTML con doble clic, anota y manda el CSV que exporta (o el respaldo, que
`desde-respaldo` convierte en el mismo CSV). La hizo Hermes el 23-oct-2026 y
entró al repositorio con estos cambios:

- **De la hoja solo entran `id_item`, `oracion`, `entidad_1` y `entidad_2`**,
  leídas con `revision.leer_items`, la misma validación que la pestaña
  «Revisión». La llave, los dobles y el resumen no se leen: la página no
  puede mostrar lo que no tiene.
- **Lo que la página tiene que medir igual que `revision.py` sale de ahí**: las
  opciones cerradas, las columnas del CSV, el tope de 15 minutos por tramo y
  el patrón del id. No se copian a mano.
- **La lógica pura** (los tramos, la validación y el CSV) va en su propio
  `<script id="logica">`, sin tocar el DOM. Así las pruebas la corren en node
  contra `revision.validar`, `revision.anotaciones_de_eventos` y
  `revision.escribir_csv`, y exigen el mismo CSV byte a byte.
- **Los datos van en un `<script type="application/json">`** con todo `<`
  escapado como `\\u003c`: una oración con `</script>` o `<!--` no puede
  cerrar ni alterar el bloque.

El tiempo sigue la regla de `revision.anotaciones`: tramos de `inicio` a
`guardado`, y un tramo de más de 15 minutos no se suma y se cuenta en
`tramos_largos`. Las horas son las del navegador de quien anota.

Biblioteca estándar y Python 3.8. `print` solo en `main`.
"""

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
from datetime import datetime, timezone

import revision

AQUI = os.path.dirname(os.path.abspath(__file__))
GUIA = os.path.join(AQUI, "docs", "guia-anotacion.md")
TITULO = "Revisión ciega"


def md_a_html(texto):
    """Markdown mínimo, el de la guía: #, ##, listas con '-' (y sublistas con
    sangría), **negrita** y *cursiva*. Todo se escapa antes."""
    salida, en_lista = [], False

    def en_linea(s):
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])",
                   r"<em>\1</em>", s)
        return s

    for cruda in texto.splitlines():
        linea = cruda.rstrip()
        m = re.match(r"^(\s*)- (.*)$", linea)
        if m:
            if not en_lista:
                salida.append("<ul>")
                en_lista = True
            clase = ' class="sub"' if len(m.group(1)) >= 2 else ""
            salida.append("<li%s>%s</li>" % (clase, en_linea(m.group(2))))
            continue
        if en_lista:
            salida.append("</ul>")
            en_lista = False
        if linea.startswith("## "):
            salida.append("<h3>%s</h3>" % en_linea(linea[3:]))
        elif linea.startswith("# "):
            salida.append("<h2>%s</h2>" % en_linea(linea[2:]))
        elif linea.strip():
            salida.append("<p>%s</p>" % en_linea(linea))
    if en_lista:
        salida.append("</ul>")
    return "\n".join(salida)


def huella_hoja(ruta):
    with open(ruta, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def datos_de(ruta_hoja):
    """Lo que la página lleva embebido. Los ítems solo con sus cuatro
    columnas: `leer_items` agrega las posiciones, que aquí no van (la página
    resalta por su cuenta)."""
    items = [dict((c, it[c]) for c in revision.COLUMNAS_ITEM)
             for it in revision.leer_items(ruta_hoja)]
    return {
        "items": items,
        "huella": huella_hoja(ruta_hoja),
        "tope_tramo_s": revision.TOPE_TRAMO,
        "opciones": dict((c, list(v)) for c, v in revision.OPCIONES.items()),
        "columnas_valores": list(revision.COLUMNAS_VALORES),
        "columnas_exportadas": list(revision.COLUMNAS_EXPORTADAS),
        "patron_id": revision.PATRON_ID.pattern,
        "max_comentario": revision.MAX_COMENTARIO,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _json_en_script(datos):
    # Todo `<` como <: sin él no hay `</script>` ni `<!--` que el
    # analizador de HTML vea dentro del bloque. JSON.parse lo devuelve igual.
    return json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")


def pagina(ruta_hoja, guia=None, titulo=TITULO):
    """El HTML entero, como texto."""
    datos = datos_de(ruta_hoja)
    if guia and os.path.isfile(guia):
        with io.open(guia, encoding="utf-8") as f:
            cuerpo_guia = md_a_html(f.read())
    else:
        cuerpo_guia = "<p>Sin guía.</p>"
    return (PLANTILLA.replace("__TITULO__", html.escape(titulo))
            .replace("__GUIA__", cuerpo_guia)
            .replace("__LOGICA__", LOGICA)
            .replace("__DATOS__", _json_en_script(datos))), datos


def exportar_html(ruta_hoja, salida, guia=GUIA, titulo=TITULO):
    """Escribe la página y devuelve (n_items, huella de la hoja)."""
    texto, datos = pagina(ruta_hoja, guia, titulo)
    with io.open(salida, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    return len(datos["items"]), datos["huella"]


def desde_respaldo(ruta_respaldo, ruta_hoja, salida):
    """El CSV que la página exportaría, desde su respaldo: por si quien anota
    manda el respaldo y no el CSV, o para comprobar uno contra el otro.
    Devuelve el número de ítems anotados.

    El respaldo tiene que ser de esta hoja (su huella): uno de otra hoja
    pondría valores en ítems que no son los suyos."""
    with io.open(ruta_respaldo, encoding="utf-8") as f:
        respaldo = json.load(f)
    if not isinstance(respaldo, dict) or not isinstance(
            respaldo.get("eventos"), list):
        raise ValueError("El archivo no es un respaldo de la página.")
    if respaldo.get("huella") != huella_hoja(ruta_hoja):
        raise ValueError("El respaldo es de otra hoja: su huella no es la de "
                         "%s." % os.path.basename(ruta_hoja))
    items = revision.leer_items(ruta_hoja)
    ids = set(it["id_item"] for it in items)
    eventos = [ev for ev in revision.eventos_validos(respaldo["eventos"])
               if ev["id_item"] in ids]
    vigentes = revision.anotaciones_de_eventos(eventos)
    revision.escribir_csv(items, vigentes, salida)
    return len(vigentes)


# La lógica que tiene que dar lo mismo que revision.py. Sin DOM: las pruebas
# la corren en node. Recibe la configuración de DATOS.
LOGICA = r"""
var Revision = (function () {
  "use strict";
  function segundosEntre(a, b) {
    const t = (Date.parse(b) - Date.parse(a)) / 1000;
    return isFinite(t) ? Math.max(0, Math.floor(t)) : null;
  }
  // revision.eventos_validos: lo que no se entiende se salta.
  function validos(eventos, cfg) {
    const patron = new RegExp(cfg.patron_id);
    return (Array.isArray(eventos) ? eventos : []).filter(ev =>
      ev && typeof ev === "object" && typeof ev.id_item === "string" &&
      patron.test(ev.id_item) && (ev.evento === "inicio" || ev.evento === "guardado") &&
      typeof ev.hora === "string" &&
      (ev.evento !== "guardado" || (ev.valores && typeof ev.valores === "object" && !Array.isArray(ev.valores))));
  }
  // revision.anotaciones_de_eventos, con el mismo tope por tramo.
  function vigentes(eventos, cfg) {
    const abierto = {}, salida = {};
    for (const ev of validos(eventos, cfg)) {
      if (ev.evento === "inicio") { if (!(ev.id_item in abierto)) abierto[ev.id_item] = ev.hora; continue; }
      const previo = salida[ev.id_item] || {};
      const ini = (ev.id_item in abierto) ? abierto[ev.id_item] : null;
      delete abierto[ev.id_item];
      const valores = {};
      // str(x or "") de Python: lo vacío o falso queda "".
      for (const c of cfg.columnas_valores) valores[c] = String(ev.valores[c] || "");
      let seg = ("segundos" in previo) ? previo.segundos : null;
      let largos = previo.tramos_largos || 0;
      const tramo = ini ? segundosEntre(ini, ev.hora) : null;
      if (tramo !== null) { if (tramo > cfg.tope_tramo_s) largos += 1; else seg = (seg || 0) + tramo; }
      salida[ev.id_item] = { valores: valores, inicio: previo.inicio || ini || null, fin: ev.hora,
                             segundos: seg, tramos_largos: largos };
    }
    return salida;
  }
  // revision.validar: errores que no dejan guardar y avisos que sí.
  function validar(v, cfg) {
    const O = cfg.opciones, errores = [], avisos = [];
    const en = (c, permitidos, cuando) => {
      if (!permitidos.includes(v[c])) errores.push("«" + c + "» tiene que ser " +
        permitidos.map(p => "«" + p + "»").join(" o ") + (cuando || "") + ".");
    };
    en("relacion", O.relacion);
    if (v.relacion === "no") {
      en("direccion", ["ninguna"], " cuando la relación es «no»");
      for (const c of ["signo", "tipo"]) if (v[c]) errores.push("«" + c + "» va vacío cuando la relación es «no».");
    } else if (v.relacion === "si" || v.relacion === "dudoso") {
      en("direccion", ["1>2", "2>1"], " cuando la relación es «" + v.relacion + "»");
      en("signo", O.signo); en("tipo", O.tipo);
    }
    en("negada", O.negada); en("especulativa", O.especulativa);
    if (v.relacion === "si" && v.negada === "si") errores.push("Con negada = sí, la relación no va «si». " +
      "Si la oración niega el efecto, la relación va «no», o «dudoso» si además afirma la unión al promotor; " +
      "si lo negado es otra cosa u otro par, negada va «no».");
    if ((v.comentario || "").length > cfg.max_comentario) errores.push("El comentario pasa de " + cfg.max_comentario + " caracteres.");
    if (!errores.length) {
      if (v.relacion === "dudoso" && !v.comentario) avisos.push("La guía pide comentario cuando el ítem es «dudoso».");
      if (v.relacion === "si" && v.especulativa === "si") avisos.push("Una relación planteada como posibilidad va «dudoso».");
    }
    return { errores: errores, avisos: avisos };
  }
  // El csv de Python con QUOTE_MINIMAL: entre comillas lo que lleva coma,
  // comillas o salto de línea; filas con \r\n y BOM al principio.
  function csvCampo(s) { s = s == null ? "" : String(s); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
  function exportarCSV(items, vig, cfg) {
    const cols = cfg.columnas_exportadas, lineas = [cols.map(csvCampo).join(",")];
    for (const it of items) {
      const h = vig[it.id_item], fila = {};
      for (const c of cols) fila[c] = "";
      for (const c of ["id_item", "oracion", "entidad_1", "entidad_2"]) fila[c] = it[c];
      if (h) {
        for (const c of cfg.columnas_valores) fila[c] = h.valores[c] || "";
        fila.inicio = h.inicio || ""; fila.fin = h.fin;
        fila.segundos = h.segundos === null ? "" : String(h.segundos);
        fila.tramos_largos = String(h.tramos_largos);
      }
      lineas.push(cols.map(c => csvCampo(fila[c])).join(","));
    }
    return "﻿" + lineas.join("\r\n") + "\r\n";
  }
  return { segundosEntre, validos, vigentes, validar, csvCampo, exportarCSV };
})();
"""


PLANTILLA = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>
:root { --borde:#d0d4da; --suave:#f5f6f8; --acento:#1f5fbf; --e1:#ffe08a; --e2:#a8e6c1; }
* { box-sizing: border-box; }
body { margin:0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color:#1d2330; background:#fff; }
header { display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; padding:.6rem 1rem; border-bottom:1px solid var(--borde); background:var(--suave); position:sticky; top:0; z-index:2; }
header h1 { font-size:1.05rem; margin:0 1rem 0 0; }
header .esp { flex:1; }
button, label.boton { font:inherit; padding:.35rem .7rem; border:1px solid var(--borde); border-radius:6px; background:#fff; cursor:pointer; }
button.primario { background:var(--acento); color:#fff; border-color:var(--acento); }
button:disabled { opacity:.5; cursor:default; }
main { display:grid; grid-template-columns: 220px 1fr; min-height: calc(100vh - 52px); }
nav { border-right:1px solid var(--borde); padding:.6rem; overflow:auto; max-height: calc(100vh - 52px); position:sticky; top:52px; }
nav .avance { font-size:.85rem; margin-bottom:.4rem; }
nav .barra { height:6px; background:#e7e9ee; border-radius:3px; overflow:hidden; margin-bottom:.6rem; }
nav .barra div { height:100%; background:var(--acento); width:0; }
nav ol { list-style:none; margin:0; padding:0; display:grid; grid-template-columns: repeat(5, 1fr); gap:3px; }
nav li button { width:100%; padding:.15rem 0; font-size:.8rem; }
nav li button.hecho { background:#e3f1e6; border-color:#9cc9a6; }
nav li button.actual { outline:2px solid var(--acento); }
section#item { padding:1rem 1.4rem; max-width: 980px; }
.oracion { font-size:1.12rem; line-height:1.7; background:var(--suave); border:1px solid var(--borde); border-radius:8px; padding:.9rem 1rem; margin:.4rem 0 1rem; }
mark.e1 { background:var(--e1); padding:0 .15em; border-radius:3px; }
mark.e2 { background:var(--e2); padding:0 .15em; border-radius:3px; }
.entidades { display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:.6rem; }
.entidades span { padding:.15rem .5rem; border-radius:4px; font-weight:600; }
.campo { display:grid; grid-template-columns: 130px 1fr; align-items:center; gap:.6rem; padding:.35rem 0; border-bottom:1px dashed #e5e7eb; }
.campo .nombre { font-weight:600; }
.opciones { display:flex; flex-wrap:wrap; gap:.4rem; }
.opciones label { border:1px solid var(--borde); border-radius:6px; padding:.2rem .6rem; cursor:pointer; user-select:none; }
.opciones input { margin-right:.3rem; }
.opciones label.off { opacity:.35; cursor:default; }
textarea { width:100%; min-height:3.2rem; font:inherit; padding:.4rem; border:1px solid var(--borde); border-radius:6px; }
.mensajes div { margin:.5rem 0; padding:.5rem .7rem; border-radius:6px; }
.error { background:#fde8e8; border:1px solid #f3b4b4; }
.aviso { background:#fff6db; border:1px solid #f0d58a; }
.ok { background:#e3f1e6; border:1px solid #9cc9a6; }
.acciones { display:flex; gap:.5rem; margin-top:.8rem; flex-wrap:wrap; }
.pista { color:#5b6475; font-size:.85rem; }
dialog { max-width: 860px; width: 92vw; border:1px solid var(--borde); border-radius:10px; padding:0; }
dialog .cuerpo { padding: .4rem 1.4rem 1rem; max-height: 75vh; overflow:auto; }
dialog .pie { padding:.6rem 1.4rem; border-top:1px solid var(--borde); text-align:right; }
dialog li.sub { margin-left: 1.2rem; list-style: circle; }
@media (max-width: 760px) { main { grid-template-columns: 1fr; } nav { position:static; max-height:none; } }
</style></head>
<body>
<header>
  <h1>__TITULO__</h1>
  <button id="b-guia">Guía</button>
  <span class="esp"></span>
  <button id="b-exportar" class="primario">Exportar CSV</button>
  <button id="b-respaldo">Descargar respaldo</button>
  <label class="boton" for="f-importar">Importar respaldo</label>
  <input id="f-importar" type="file" accept=".json,application/json" hidden>
</header>
<main>
  <nav>
    <div class="avance" id="avance"></div>
    <div class="barra"><div id="barra"></div></div>
    <ol id="lista"></ol>
    <p class="pista">Lo que guardas se queda en este navegador. Descarga un respaldo de vez en cuando; al terminar, exporta el CSV y mándalo.</p>
  </nav>
  <section id="item"></section>
</main>
<dialog id="d-guia"><div class="cuerpo">__GUIA__</div><div class="pie"><button id="b-cerrar-guia">Cerrar</button></div></dialog>
<script id="datos" type="application/json">__DATOS__</script>
<script id="logica">__LOGICA__</script>
<script>
"use strict";
const DATOS = JSON.parse(document.getElementById("datos").textContent);
const ITEMS = DATOS.items;
const CLAVE = "revision-ciega-" + DATOS.huella.slice(0, 16);
const OPCIONES = DATOS.opciones;
const VALORES = DATOS.columnas_valores;
const CAMPOS = ["relacion", "direccion", "signo", "tipo", "negada", "especulativa"];
const ETIQUETA = { relacion: "relación", direccion: "dirección", signo: "signo", tipo: "tipo", negada: "negada", especulativa: "especulativa" };
let eventos = cargar();
let actual = 0;
let sucio = false;

function cargar() {
  try { const e = JSON.parse(localStorage.getItem(CLAVE) || "[]"); return Array.isArray(e) ? e : []; }
  catch (_) { return []; }
}
function persistir() { localStorage.setItem(CLAVE, JSON.stringify(eventos)); }
function ahora() { return new Date().toISOString(); }
function registrar(ev) { eventos.push(ev); persistir(); }
function anotaciones() { return Revision.vigentes(eventos, DATOS); }

// Palabra entera y con sus mayúsculas, sin pisar la otra marca: solo para
// resaltar, como revision.posicion.
function posicion(texto, mencion, evitar) {
  if (!mencion) return null;
  const esc = mencion.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp("(?<![A-Za-z0-9])" + esc + "(?![A-Za-z0-9])", "g");
  let m;
  while ((m = re.exec(texto)) !== null) {
    const p = [m.index, m.index + mencion.length];
    if (!evitar || p[1] <= evitar[0] || p[0] >= evitar[1]) return p;
  }
  return null;
}
function pintarOracion(cont, it) {
  const t = it.oracion, p1 = posicion(t, it.entidad_1, null), p2 = posicion(t, it.entidad_2, p1);
  const marcas = [];
  if (p1) marcas.push([p1[0], p1[1], "e1"]);
  if (p2) marcas.push([p2[0], p2[1], "e2"]);
  marcas.sort((a, b) => a[0] - b[0]);
  let i = 0;
  for (const [a, b, cl] of marcas) {
    cont.appendChild(document.createTextNode(t.slice(i, a)));
    const mk = document.createElement("mark"); mk.className = cl; mk.textContent = t.slice(a, b);
    cont.appendChild(mk); i = b;
  }
  cont.appendChild(document.createTextNode(t.slice(i)));
}

function el(tag, attrs, hijos) {
  const e = document.createElement(tag);
  for (const k in (attrs || {})) { if (k === "texto") e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); }
  for (const h of (hijos || [])) e.appendChild(h);
  return e;
}

function leerFormulario() {
  const v = {};
  for (const c of VALORES) {
    if (c === "comentario") { v[c] = document.getElementById("comentario").value.trim(); continue; }
    const s = document.querySelector('input[name="' + c + '"]:checked');
    v[c] = s ? s.value : "";
  }
  return v;
}
function ajustarDependencias() {
  const rel = (document.querySelector('input[name="relacion"]:checked') || {}).value;
  const fijar = (campo, permitido) => {
    for (const inp of document.querySelectorAll('input[name="' + campo + '"]')) {
      const ok = permitido(inp.value);
      inp.disabled = !ok; inp.parentElement.classList.toggle("off", !ok);
      if (!ok && inp.checked) inp.checked = false;
    }
  };
  if (rel === "no") {
    fijar("direccion", x => x === "ninguna");
    const n = document.querySelector('input[name="direccion"][value="ninguna"]'); if (n) n.checked = true;
    fijar("signo", () => false); fijar("tipo", () => false);
  } else if (rel === "si" || rel === "dudoso") {
    fijar("direccion", x => x !== "ninguna"); fijar("signo", () => true); fijar("tipo", () => true);
  } else {
    fijar("direccion", () => true); fijar("signo", () => true); fijar("tipo", () => true);
  }
}

function mostrar(n, registrarInicio) {
  if (sucio && !confirm("Hay cambios sin guardar en este ítem. ¿Seguir sin guardarlos?")) return;
  actual = Math.max(0, Math.min(ITEMS.length - 1, n));
  sucio = false;
  const it = ITEMS[actual];
  if (registrarInicio !== false) registrar({ evento: "inicio", id_item: it.id_item, hora: ahora() });
  const hechos = anotaciones(), previo = hechos[it.id_item];
  const sec = document.getElementById("item"); sec.innerHTML = "";
  sec.appendChild(el("div", { class: "pista", texto: "Ítem " + (actual + 1) + " de " + ITEMS.length + " · " + it.id_item + (previo ? " · ya guardado (puedes corregirlo)" : "") }));
  const ora = el("div", { class: "oracion" }); pintarOracion(ora, it); sec.appendChild(ora);
  sec.appendChild(el("div", { class: "entidades" }, [
    el("span", { style: "background:var(--e1)", texto: "entidad_1: " + it.entidad_1 }),
    el("span", { style: "background:var(--e2)", texto: "entidad_2: " + it.entidad_2 })]));
  for (const c of CAMPOS) {
    const ops = el("div", { class: "opciones" });
    for (const o of OPCIONES[c]) {
      const inp = el("input", { type: "radio", name: c, value: o });
      if (previo && previo.valores[c] === o) inp.checked = true;
      inp.addEventListener("change", () => { sucio = true; ajustarDependencias(); });
      ops.appendChild(el("label", {}, [inp, document.createTextNode(o)]));
    }
    sec.appendChild(el("div", { class: "campo" }, [el("div", { class: "nombre", texto: ETIQUETA[c] }), ops]));
  }
  const ta = el("textarea", { id: "comentario", placeholder: "Obligatorio si es «dudoso», y para otro organismo, cepa, recíproca, condición o entidad mal reconocida." });
  ta.value = previo ? (previo.valores.comentario || "") : "";
  ta.addEventListener("input", () => { sucio = true; });
  sec.appendChild(el("div", { class: "campo" }, [el("div", { class: "nombre", texto: "comentario" }), ta]));
  sec.appendChild(el("div", { class: "mensajes", id: "mensajes" }));
  const bAnt = el("button", { texto: "← Anterior" }); bAnt.disabled = actual === 0; bAnt.onclick = () => mostrar(actual - 1);
  const bGuardar = el("button", { class: "primario", texto: "Guardar y seguir →" }); bGuardar.onclick = guardar;
  const bSig = el("button", { texto: "Saltar →" }); bSig.disabled = actual === ITEMS.length - 1; bSig.onclick = () => mostrar(actual + 1);
  sec.appendChild(el("div", { class: "acciones" }, [bAnt, bGuardar, bSig]));
  ajustarDependencias();
  pintarLista();
  window.scrollTo(0, 0);
}

function guardar() {
  const v = leerFormulario(), r = Revision.validar(v, DATOS), caja = document.getElementById("mensajes");
  caja.innerHTML = "";
  for (const e of r.errores) caja.appendChild(el("div", { class: "error", texto: e }));
  if (r.errores.length) return;
  const it = ITEMS[actual];
  registrar({ evento: "guardado", id_item: it.id_item, hora: ahora(), valores: v });
  sucio = false;
  if (r.avisos.length) {
    for (const a of r.avisos) caja.appendChild(el("div", { class: "aviso", texto: "Guardado, con un aviso: " + a }));
    pintarLista(); return;
  }
  const hechos = anotaciones();
  const sig = ITEMS.findIndex((x, i) => i > actual && !hechos[x.id_item]);
  const prox = sig >= 0 ? sig : ITEMS.findIndex(x => !hechos[x.id_item]);
  if (prox >= 0) mostrar(prox);
  else { pintarLista(); caja.appendChild(el("div", { class: "ok", texto: "¡Listo! Anotaste todos los ítems. Exporta el CSV y mándalo." })); }
}

function pintarLista() {
  const hechos = anotaciones(), ol = document.getElementById("lista"); ol.innerHTML = "";
  ITEMS.forEach((it, i) => {
    const b = el("button", { texto: String(i + 1), title: it.id_item });
    if (hechos[it.id_item]) b.classList.add("hecho");
    if (i === actual) b.classList.add("actual");
    b.onclick = () => mostrar(i);
    ol.appendChild(el("li", {}, [b]));
  });
  const n = ITEMS.filter(x => hechos[x.id_item]).length;
  document.getElementById("avance").textContent = n + " de " + ITEMS.length + " anotados";
  document.getElementById("barra").style.width = (100 * n / ITEMS.length) + "%";
}

function descargar(nombre, texto, tipo) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([texto], { type: tipo }));
  a.download = nombre; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
document.getElementById("b-exportar").onclick = () => descargar("anotaciones_exportadas.csv",
  Revision.exportarCSV(ITEMS, anotaciones(), DATOS), "text/csv;charset=utf-8");
document.getElementById("b-respaldo").onclick = () => descargar("respaldo_revision_" + DATOS.huella.slice(0, 8) + ".json",
  JSON.stringify({ huella: DATOS.huella, exportado: ahora(), eventos: eventos }), "application/json");
document.getElementById("f-importar").onchange = (ev) => {
  const f = ev.target.files[0]; if (!f) return;
  f.text().then(t => {
    let d; try { d = JSON.parse(t); } catch (_) { alert("El archivo no es un respaldo válido."); return; }
    if (!d || d.huella !== DATOS.huella || !Array.isArray(d.eventos)) { alert("Ese respaldo es de otra hoja."); return; }
    if (eventos.length && !confirm("Esto reemplaza lo guardado en este navegador por el respaldo. ¿Seguir?")) return;
    eventos = d.eventos; persistir(); sucio = false; mostrar(actual, false);
  });
  ev.target.value = "";
};
const dGuia = document.getElementById("d-guia");
document.getElementById("b-guia").onclick = () => dGuia.showModal();
document.getElementById("b-cerrar-guia").onclick = () => dGuia.close();
window.addEventListener("beforeunload", (e) => { if (sucio) { e.preventDefault(); e.returnValue = ""; } });

(function inicio() {
  const hechos = anotaciones();
  const primero = ITEMS.findIndex(x => !hechos[x.id_item]);
  if (!eventos.length) dGuia.showModal();
  mostrar(primero >= 0 ? primero : 0);
})();
</script>
</body></html>
"""


def _hoja_de(args):
    return args.hoja if args.hoja else revision.ruta_hoja(args.carpeta)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="revision_portatil",
        description="La revisión ciega en un solo HTML, sin servidor.")
    sub = ap.add_subparsers(dest="sub", required=True)
    for nombre, ayuda in (("exportar-html", "Escribe la página para quien "
                           "anota."),
                          ("desde-respaldo", "El CSV exportado, desde el "
                           "respaldo de la página.")):
        p = sub.add_parser(nombre, help=ayuda)
        hoja = p.add_mutually_exclusive_group(required=True)
        hoja.add_argument("--carpeta", help="Carpeta del sorteo: se lee solo "
                                            "su hoja_tanda1.csv.")
        hoja.add_argument("--hoja", help="Una hoja con las columnas de la "
                                         "rúbrica (§6), con cualquier nombre.")
        p.add_argument("--salida", required=True)
        if nombre == "exportar-html":
            p.add_argument("--guia", default=GUIA,
                           help="Markdown con la guía; por omisión, "
                                "docs/guia-anotacion.md.")
            p.add_argument("--titulo", default=TITULO)
        else:
            p.add_argument("--respaldo", required=True,
                           help="El JSON de «Descargar respaldo».")
    args = ap.parse_args(argv)
    try:
        if args.sub == "exportar-html":
            n, huella = exportar_html(_hoja_de(args), args.salida, args.guia,
                                      args.titulo)
            print("Escrito %s: %d ítems; huella de la hoja %s."
                  % (args.salida, n, huella[:16]))
        else:
            n = desde_respaldo(args.respaldo, _hoja_de(args), args.salida)
            print("Escrito %s: %d ítems anotados." % (args.salida, n))
    except (OSError, ValueError, LookupError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
