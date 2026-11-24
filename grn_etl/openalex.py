# -*- coding: utf-8 -*-
"""Las copias en PDF que guarda OpenAlex de los artículos sin texto completo.

    python -m grn_etl.openalex bajar [--corpus NOMBRE ...] [--max N]
    .venv-pdf/Scripts/python -m grn_pdf.cli convertir \\
        --entrada <datos>/fulltext/pdf_openalex/<corpus> \\
        --salida <datos>/fulltext/pdf_openalex_txt/<corpus>
    python -m grn_etl.openalex registrar --corpus NOMBRE

Son tres pasos porque el de en medio necesita PyMuPDF, que no es del núcleo.

- `bajar` no escribe en la base: deja los PDF en una carpeta de espera
  (`<datos>/fulltext/pdf_openalex/<corpus>/<pmid>.pdf`) con su
  `registro.jsonl`. Se puede volver a correr: salta lo ya bajado y se detiene
  sola cuando se acaba el presupuesto del día (US$0.01 por PDF; con la llave
  gratuita, US$1 al día, que se renueva a las 0:00 UTC).
- `registrar` pasa a `<datos>/fulltext/pdf` y anota en `descargas` solo los
  PDF cuyo texto convertido es el artículo (`es_el_articulo`). Respalda la
  base antes de usarlo.
- La llave sale de grn_etl.credenciales (entorno u `openalex.key`) y viaja
  solo en la cabecera Authorization, nunca en una URL ni en el registro. Si el
  servidor redirige a otro sitio, a ese sitio no se le manda.
- Imprime solo conteos.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

from grn_etl import credenciales, db

API = "https://api.openalex.org"
CONTENIDO = "https://content.openalex.org/works/%s.pdf"
CAMPOS = "id,ids,has_content,open_access,best_oa_location"
LOTE = 50
AGENTE = "grn-etl/0.1"
COSTO_PDF = 0.01
ESPERA_MAXIMA = 330
# Cuándo un PDF convertido es el artículo que dice su PMID (enmienda 3 de
# docs/protocolo-prueba-nuevos.md). OpenAlex a veces guarda otra cosa: una
# carátula, un resumen de congreso o el archivo de otro trabajo.
MIN_CARACTERES = 5000
CABECERA = 6000
MIN_EN_CABECERA = 0.6
MIN_EN_TODO = 0.8


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k):
        return None


ABRIDOR = urllib.request.build_opener(_SinRedireccion)


def pedir(url, llave, espera=60):
    """(estado, cabeceras, cuerpo). La llave no sigue una redirección."""
    cabeceras = {"User-Agent": AGENTE}
    if llave:
        cabeceras["Authorization"] = "Bearer " + llave
    try:
        r = ABRIDOR.open(urllib.request.Request(url, headers=cabeceras),
                         timeout=espera)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        destino = e.headers.get("Location")
        if e.code in (301, 302, 303, 307, 308) and destino:
            return pedir(urllib.parse.urljoin(url, destino), None, espera)
        return e.code, e.headers, e.read()


def _normal(texto):
    return re.sub(r"[^a-z0-9 ]+", " ", (texto or "").lower())


def es_el_articulo(titulo, texto):
    """El texto convertido trae el título del registro y es un artículo."""
    if len(texto or "") < MIN_CARACTERES:
        return False
    palabras = [p for p in _normal(titulo).split() if len(p) > 3]
    if not palabras:
        return False
    cabecera, todo = _normal(texto[:CABECERA]), _normal(texto)
    en_cabecera = sum(1 for p in palabras if p in cabecera) / float(len(palabras))
    en_todo = sum(1 for p in palabras if p in todo) / float(len(palabras))
    return en_cabecera >= MIN_EN_CABECERA or en_todo >= MIN_EN_TODO


def registrar_corpus(con, nombre, espera, espera_txt, carpeta_pdf):
    """Pasa a la carpeta de PDF y registra los que son el artículo."""
    cuenta = collections.Counter()  # type: dict
    origen = os.path.join(espera, nombre)
    os.makedirs(carpeta_pdf, exist_ok=True)
    with open(os.path.join(origen, "registro.jsonl"), encoding="utf-8") as f:
        filas = [json.loads(linea) for linea in f if linea.strip()]
    for fila in filas:
        if fila.get("estado") != "ok":
            continue
        pmid = fila["pmid"]
        if any(d["tipo"] == "pdf" and d["estatus"] == "ok"
               for d in db.descargas_de(con, pmid)):
            cuenta["ya_registrados"] += 1
            continue
        ruta_txt = os.path.join(espera_txt, nombre, pmid + ".txt")
        if not os.path.isfile(ruta_txt):
            cuenta["sin_convertir"] += 1
            continue
        with open(ruta_txt, encoding="utf-8", errors="replace") as f:
            texto = f.read()
        documento = db.obtener_documento(con, pmid)
        if not es_el_articulo(documento["titulo"], texto):
            cuenta["descartados"] += 1
            continue
        ruta = os.path.join(carpeta_pdf, pmid + ".pdf")
        shutil.copyfile(os.path.join(origen, pmid + ".pdf"), ruta)
        db.registrar_descarga(
            con, pmid, "pdf", "ok", fuente="OpenAlex", ruta=ruta,
            tam=fila.get("bytes"),
            nota="version=%s; acceso=%s; licencia=%s" % (
                fila.get("version"), fila.get("acceso"), fila.get("licencia")),
            url=CONTENIDO % fila["obra"])
        cuenta["registrados"] += 1
    return dict(cuenta)


def sin_texto_completo(con, nombre):
    corpus = db.obtener_corpus(con, nombre)
    if corpus is None:
        raise SystemExit("No existe el corpus %s." % nombre)
    return [pmid for pmid, _doi in db.pmids_y_dois_del_corpus(con, corpus["id"])
            if not any(d["estatus"] == "ok" for d in db.descargas_de(con, pmid))]


def obras_con_pdf(pmids, llave):
    """{pmid: obra} de las que OpenAlex guarda copia en PDF."""
    obras = {}
    for i in range(0, len(pmids), LOTE):
        url = API + "/works?" + urllib.parse.urlencode({
            "filter": "pmid:" + "|".join(pmids[i:i + LOTE]),
            "per_page": "100", "select": CAMPOS}, safe=":|,")
        estado, _cab, cuerpo = pedir(url, llave)
        if estado != 200:
            raise SystemExit("OpenAlex contestó %d a la consulta." % estado)
        for obra in json.loads(cuerpo).get("results", []):
            pmid = (obra.get("ids", {}).get("pmid") or "").rstrip("/")
            pmid = pmid.rsplit("/", 1)[-1]
            if pmid and (obra.get("has_content") or {}).get("pdf"):
                obras.setdefault(pmid, obra)
        time.sleep(0.1)
    return obras


def leer_registro(ruta):
    vistos = {}
    if os.path.isfile(ruta):
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                try:
                    fila = json.loads(linea)
                except ValueError:
                    continue
                vistos[fila["pmid"]] = fila["estado"]
    return vistos


def bajar_corpus(con, nombre, destino, llave, tope, limite_s, inicio, log):
    carpeta = os.path.join(destino, nombre)
    os.makedirs(carpeta, exist_ok=True)
    ruta_registro = os.path.join(carpeta, "registro.jsonl")
    vistos = leer_registro(ruta_registro)
    pendientes = sin_texto_completo(con, nombre)
    obras = obras_con_pdf(pendientes, llave)
    cuenta = collections.Counter()  # type: dict
    cuenta["sin_texto_completo"] = len(pendientes)
    cuenta["con_copia_en_openalex"] = len(obras)
    restante, motivo = None, ""
    with open(ruta_registro, "a", encoding="utf-8") as registro:
        for pmid in sorted(obras, key=lambda p: -int(p)):
            ruta = os.path.join(carpeta, pmid + ".pdf")
            if vistos.get(pmid) == "ok" and os.path.isfile(ruta):
                cuenta["ya_bajados"] += 1
                continue
            if vistos.get(pmid) == "sin_contenido":
                cuenta["sin_contenido"] += 1
                continue
            if tope is not None and cuenta["bajados_ahora"] >= tope:
                motivo = "tope de esta corrida"
                break
            if time.time() - inicio > limite_s:
                motivo = "tiempo de esta corrida"
                break
            if restante is not None and restante < COSTO_PDF:
                motivo = "presupuesto del día agotado"
                break
            obra = obras[pmid]
            id_obra = obra["id"].rsplit("/", 1)[-1]
            estado, cab, cuerpo = None, {}, b""
            for intento in range(4):
                estado, cab, cuerpo = pedir(CONTENIDO % id_obra, llave)
                if estado != 429:
                    break
                # Una cuenta nueva gasta su primer dólar a US$0.10 cada 5
                # minutos: el 429 trae cuánto esperar, y esperar no cuesta.
                espera = int(cab.get("Retry-After") or 0)
                if not 0 < espera <= ESPERA_MAXIMA:
                    break
                time.sleep(espera + 1)
            if cab.get("X-RateLimit-Remaining-USD") is not None:
                restante = float(cab["X-RateLimit-Remaining-USD"])
            fila = {"pmid": pmid, "obra": id_obra,
                    "fecha": datetime.datetime.now(
                        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            if estado == 200 and cuerpo[:4] == b"%PDF":
                with open(ruta, "wb") as f:
                    f.write(cuerpo)
                lugar = obra.get("best_oa_location") or {}
                fila.update({
                    "estado": "ok", "bytes": len(cuerpo),
                    "sha256": hashlib.sha256(cuerpo).hexdigest(),
                    "acceso": (obra.get("open_access") or {}).get("oa_status"),
                    "version": lugar.get("version"),
                    "licencia": lugar.get("license")})
                cuenta["bajados_ahora"] += 1
            elif estado == 429:
                try:
                    razon = json.loads(cuerpo).get("reason") or ""
                except ValueError:
                    razon = ""
                motivo = "presupuesto: 429 %s, reintentar en %s s" % (
                    razon, cab.get("Retry-After") or "?")
                break
            elif estado == 404:
                fila["estado"] = "sin_contenido"
                cuenta["sin_contenido"] += 1
            else:
                fila["estado"] = "error_%s" % estado
                cuenta["errores"] += 1
            registro.write(json.dumps(fila, ensure_ascii=False) + "\n")
            registro.flush()
            if cuenta["bajados_ahora"] and cuenta["bajados_ahora"] % 20 == 0 \
                    and fila.get("estado") == "ok":
                log("  %s: %d bajados" % (nombre, cuenta["bajados_ahora"]))
            time.sleep(0.15)
    cuenta["en_la_carpeta"] = sum(1 for a in os.listdir(carpeta)
                                  if a.endswith(".pdf"))
    cuenta["faltan"] = max(0, len(obras) - cuenta["en_la_carpeta"]
                           - cuenta["sin_contenido"])
    resumen = dict(cuenta)
    resumen["corpus"] = nombre
    resumen["se_detuvo_por"] = motivo or "terminó"
    ok = [json.loads(l) for l in open(ruta_registro, encoding="utf-8")]
    ok = [f for f in ok if f.get("estado") == "ok"]
    resumen["por_acceso"] = dict(collections.Counter(
        f.get("acceso") or "?" for f in ok))
    resumen["por_version"] = dict(collections.Counter(
        f.get("version") or "?" for f in ok))
    return resumen, restante, bool(motivo.startswith("presupuesto"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="orden", required=True)
    ba = sub.add_parser("bajar", help="Bajar las copias a la carpeta de espera.")
    ba.add_argument("--corpus", nargs="+",
                    default=["nuevos-20261104", "v0-agosto"])
    ba.add_argument("--max", type=int, default=None)
    ba.add_argument("--segundos", type=int, default=480)
    re_ = sub.add_parser("registrar", help="Registrar en la base los PDF "
                                           "que son el artículo.")
    re_.add_argument("--corpus", required=True)
    for p in (ba, re_):
        p.add_argument("--datos", default=None,
                       help="Raíz de datos; gana sobre GRN_DATOS.")
    args = ap.parse_args(argv)
    datos = args.datos or os.environ.get("GRN_DATOS", "datos")
    destino = os.path.join(datos, "fulltext", "pdf_openalex")
    con = db.conectar(os.path.join(datos, "grn.db"))
    if args.orden == "registrar":
        print(json.dumps(registrar_corpus(
            con, args.corpus, destino, destino + "_txt",
            os.path.join(datos, "fulltext", "pdf")), ensure_ascii=False))
        return 0
    llave = credenciales.llave_openalex()
    if not llave:
        raise SystemExit("Falta la llave de OpenAlex (OPENALEX_API_KEY u "
                         "openalex.key).")
    inicio = time.time()
    tope = args.max
    todo = []
    for nombre in args.corpus:
        resumen, _restante, agotado = bajar_corpus(
            con, nombre, destino, llave, tope, args.segundos, inicio,
            lambda m: print(m, flush=True))
        todo.append(resumen)
        print(json.dumps(resumen, ensure_ascii=False), flush=True)
        if tope is not None:
            tope = max(0, tope - resumen.get("bajados_ahora", 0))
        if agotado or time.time() - inicio > args.segundos:
            break
    _e, _c, cuerpo = pedir(API + "/rate-limit", llave)
    limite = json.loads(cuerpo).get("rate_limit", {})
    print("presupuesto: usado hoy US$%s, queda US$%s, se renueva en %.1f h" % (
        limite.get("daily_used_usd"), limite.get("daily_remaining_usd"),
        (limite.get("resets_in_seconds") or 0) / 3600.0))
    with open(os.path.join(destino, "resumen.json"), "w",
              encoding="utf-8") as f:
        json.dump(todo, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
