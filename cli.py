#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ETL de PubMed para redes de regulacion genica.

Comandos:
    query add     registrar una consulta
    query list    ver consultas y cuantos documentos trajo cada una
    run           correr una consulta y guardar los abstracts que falten
    fulltext      bajar XML de PMC o PDF abierto (despues del run)
    estado        resumen de la base
    log           historial de ejecuciones
    export        volcar a CSV o JSONL

Ejemplo completo:
    python3 cli.py query add pa_regulacion --archivo queries/pa.txt
    python3 cli.py run pa_regulacion --email tu@correo.unam.mx
    python3 cli.py fulltext --tipo xml --email tu@correo.unam.mx
    python3 cli.py fulltext --tipo pdf --email tu@correo.unam.mx
    python3 cli.py export pa_regulacion --formato jsonl
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from grn_etl import credenciales, db, etl, pubmed


def log(msg):
    print(msg, flush=True)


def cliente_de(args):
    # Entorno primero, archivos de la raiz despues. Asi no hay que
    # exportar en cada sesion una llave que ya esta en el disco.
    email = credenciales.correo(args.email)
    if not email:
        sys.exit("Falta el correo de contacto de NCBI. Dalo con --email, con "
                 "la variable NCBI_EMAIL, o guárdalo una vez desde el tablero "
                 "(python servidor.py --abrir), que lo deja en .correo.")
    api_key = credenciales.llave()
    if not api_key:
        log("Sin NCBI_API_KEY: el límite será de 3 peticiones/segundo.")
    return pubmed.Cliente(email, api_key)


# ------------------------------------------------------------------ query

def cmd_query_add(con, args):
    if args.archivo:
        texto = Path(args.archivo).read_text(encoding="utf-8").strip()
    elif args.texto:
        texto = args.texto.strip()
    else:
        sys.exit("Da --archivo o --texto con la query.")

    _, estado = db.alta_consulta(con, args.nombre, texto, args.descripcion)
    log(f"Consulta '{args.nombre}': {estado}  ({len(texto)} caracteres)")
    if estado == "actualizada":
        log("  El texto cambió. Los documentos ya vinculados se conservan;")
        log("  el próximo 'run' agregará lo que traiga la nueva versión.")


def cmd_query_list(con, args):
    filas = db.listar_consultas(con)
    if not filas:
        log("No hay consultas registradas.")
        return
    log(f"{'nombre':<24} {'docs':>7}  {'última corrida':<22} descripción")
    log("-" * 88)
    for f in filas:
        log(f"{f['nombre']:<24} {f['n_documentos']:>7}  "
            f"{(f['ultima_corrida'] or 'nunca'):<22} {f['descripcion'] or ''}")


# -------------------------------------------------------------------- run

def cmd_run(con, args):
    cliente = cliente_de(args)
    r = etl.ingestar(
        con, cliente, args.nombre, orden=args.orden, limite=args.limite,
        mindate=args.desde, maxdate=args.hasta, tam_lote=args.lote, log=log,
    )
    log("\n--- Resultado ---")
    log(f"PubMed reporta      : {r['total_pubmed']}")
    log(f"Considerados        : {r['considerados']}")
    log(f"Ya estaban          : {r['previos']}")
    log(f"Nuevos descargados  : {r['descargados']}")


# --------------------------------------------------------------- fulltext

def cmd_fulltext(con, args):
    cliente = cliente_de(args)
    r = etl.descargar_fulltext(
        con, cliente, tipo=args.tipo, nombre_consulta=args.nombre,
        limite=args.limite, reintentar=args.reintentar, salida=args.salida,
        usar_unpaywall=not args.sin_unpaywall, log=log,
    )
    if r["pendientes"]:
        log("\n--- Resultado ---")
        log(f"Procesados      : {r['pendientes']}")
        log(f"Descargados     : {r['ok']}")
        log(f"Sin acceso libre: {r['no_disponible']}")
        log(f"Con error       : {r['error']}")
        if r["error"]:
            log("\nLos de error se reintentan con --reintentar.")
            log("Los 'sin acceso libre' no: hay que conseguirlos por la")
            log("biblioteca digital (usa 'export --pendientes').")


# ----------------------------------------------------------------- estado

def cmd_estado(con, args):
    r = db.resumen(con)
    log(f"Consultas          : {r['consultas']}")
    log(f"Documentos únicos  : {r['documentos']}")
    log(f"  con abstract     : {r['con_abstract']}")
    log(f"Vínculos consulta-doc: {r['vinculos']}")
    if r["descargas"]:
        log("\nDescargas de full text:")
        for d in r["descargas"]:
            log(f"  {d['tipo']:<5} {d['estatus']:<16} {d['n']:>6}")
    else:
        log("\nSin descargas de full text todavía.")


def cmd_log(con, args):
    filas = db.historial(con, args.nombre, args.n)
    if not filas:
        log("Sin ejecuciones registradas.")
        return
    log(f"{'id':>4} {'consulta':<22} {'estatus':<10} {'total':>7} "
        f"{'nuevos':>7} {'bajados':>8}  iniciada")
    log("-" * 92)
    for f in filas:
        log(f"{f['id']:>4} {f['consulta']:<22} {f['estatus']:<10} "
            f"{f['total_pubmed'] or 0:>7} {f['pmids_nuevos'] or 0:>7} "
            f"{f['descargados'] or 0:>8}  {f['iniciada_en']}")
        if f["error"]:
            log(f"     error: {f['error'][:80]}")


# ----------------------------------------------------------------- export

CAMPOS = ["pmid", "doi", "pmcid", "titulo", "abstract", "revista", "anio",
          "autores", "mesh_terms", "keywords", "tipos_publicacion"]

# Encabezado que lee una persona, columna por columna. Va aparte de CAMPOS
# porque CAMPOS son las columnas de la base y las llaves del diccionario que
# se escribe: en ASCII, que es el contrato con el resto del pipeline. Lo que
# se abre en Excel si lleva el acento. Toda columna de CAMPOS tiene que
# aparecer aqui, y de eso se encarga la lectura de abajo.
ENCABEZADOS = {
    "pmid": "pmid", "doi": "doi", "pmcid": "pmcid", "titulo": "título",
    "abstract": "abstract", "revista": "revista", "anio": "año",
    "autores": "autores", "mesh_terms": "mesh_terms", "keywords": "keywords",
    "tipos_publicacion": "tipos_publicación",
}


def cmd_export(con, args):
    if args.pendientes:
        filas = db.pendientes_biblioteca(con, args.nombre)
        ruta = Path(args.salida or "salidas/pendientes_biblioteca.csv")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            # url_pmc va primero de las tres ligas: cuando existe, es la que
            # lleva al texto completo legible. Las otras dos llevan a la
            # ficha o al editor, que es donde hay que pedirlo o pagarlo.
            # 'nota' dice por que no se pudo, que es lo que decide si hay
            # que pedirlo por prestamo interbibliotecario o solo abrirlo.
            w.writerow(["pmid", "doi", "año", "revista", "título",
                        "url_pmc", "url_pubmed", "url_doi",
                        "por_qué_no_se_pudo", "última_liga_intentada"])
            for r in filas:
                w.writerow([r["pmid"], r["doi"], r["anio"], r["revista"],
                            r["titulo"],
                            pubmed.url_articulo_pmc(r["pmcid"]),
                            pubmed.url_articulo_pubmed(r["pmid"]),
                            f"https://doi.org/{r['doi']}" if r["doi"] else "",
                            r["nota"] or "", r["url_intentada"] or ""])
        log(f"{len(filas)} sin full text -> {ruta}")
        return

    if not args.nombre:
        sys.exit("Da el nombre de la consulta a exportar.")

    filas = db.documentos_de_consulta(con, args.nombre, args.solo_con_abstract)
    if not filas:
        log("No hay documentos para esa consulta.")
        return

    ext = "jsonl" if args.formato == "jsonl" else "csv"
    ruta = Path(args.salida or f"salidas/{args.nombre}.{ext}")
    ruta.parent.mkdir(parents=True, exist_ok=True)

    if args.formato == "jsonl":
        with open(ruta, "w", encoding="utf-8") as f:
            for fila in filas:
                f.write(json.dumps(db.a_dict(fila), ensure_ascii=False) + "\n")
    else:
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
            # No se usa writeheader(): escribiria las llaves del diccionario,
            # que son las columnas de la base y van sin acento. El encabezado
            # es para leerse, asi que sale de ENCABEZADOS.
            csv.writer(f).writerow([ENCABEZADOS[c] for c in CAMPOS])
            for fila in filas:
                d = db.a_dict(fila)
                w.writerow({k: (" | ".join(v) if isinstance(v, list) else v)
                            for k, v in d.items()})

    log(f"{len(filas)} documentos -> {ruta}")


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="ETL de PubMed para GRN.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", default="datos/grn.db", help="Ruta de la base SQLite.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query", help="Administrar consultas.").add_subparsers(
        dest="subcmd", required=True)

    qa = q.add_parser("add", help="Registrar o actualizar una consulta.")
    qa.add_argument("nombre")
    qa.add_argument("--archivo", help="Archivo de texto con la query.")
    qa.add_argument("--texto", help="Query en línea (usa comillas simples).")
    qa.add_argument("--descripcion")
    qa.set_defaults(func=cmd_query_add)

    ql = q.add_parser("list", help="Listar consultas.")
    ql.set_defaults(func=cmd_query_list)

    r = sub.add_parser("run", help="Correr una consulta y bajar abstracts.")
    r.add_argument("nombre")
    r.add_argument("--email")
    r.add_argument("--orden", default="relevance", choices=["relevance", "pub_date"])
    r.add_argument("--limite", type=int, help="Tope de artículos a considerar.")
    r.add_argument("--desde", help="Año mínimo, ej. 2000.")
    r.add_argument("--hasta", help="Año máximo.")
    r.add_argument("--lote", type=int, default=200)
    r.set_defaults(func=cmd_run)

    ft = sub.add_parser("fulltext", help="Bajar XML de PMC o PDF abierto.")
    ft.add_argument("--tipo", default="xml", choices=["xml", "pdf"])
    ft.add_argument("--nombre", help="Limitar a una consulta.")
    ft.add_argument("--email")
    ft.add_argument("--limite", type=int, help="Procesar solo N (para probar).")
    ft.add_argument("--reintentar", action="store_true",
                    help="Reintentar los que quedaron en error.")
    ft.add_argument("--salida", default="datos/fulltext")
    ft.add_argument("--sin-unpaywall", action="store_true")
    ft.set_defaults(func=cmd_fulltext)

    e = sub.add_parser("estado", help="Resumen de la base.")
    e.set_defaults(func=cmd_estado)

    lg = sub.add_parser("log", help="Historial de ejecuciones.")
    lg.add_argument("--nombre")
    lg.add_argument("-n", type=int, default=20)
    lg.set_defaults(func=cmd_log)

    ex = sub.add_parser("export", help="Volcar a CSV o JSONL.")
    ex.add_argument("nombre", nargs="?")
    ex.add_argument("--formato", default="csv", choices=["csv", "jsonl"])
    ex.add_argument("--salida")
    ex.add_argument("--solo-con-abstract", action="store_true")
    ex.add_argument("--pendientes", action="store_true",
                    help="Exportar los que NO tienen full text, para pedirlos "
                         "a la biblioteca.")
    ex.set_defaults(func=cmd_export)

    args = ap.parse_args()
    con = db.conectar(args.db)
    try:
        args.func(con, args)
    finally:
        con.close()


if __name__ == "__main__":
    main()
