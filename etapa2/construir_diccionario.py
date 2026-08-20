#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Etapa 1: construye el diccionario de genes de PAO1, la tabla de operones y
los pares de CollecTF. Seccion 2 del contrato de datos.

NINGUN CAMPO DE ESTE ARCHIVO DICE «ESTO ES UN TF» CON AUTORIDAD
================================================================

`es_tf` no es una medicion. GO y los keywords de UniProt son **inferencia
curada**, mucha de ella propagada por similitud de dominio desde otra especie,
y ninguna base publica contiene el enunciado «esta proteina une ADN y regula la
transcripcion en *P. aeruginosa*, medido». Lo que hay es una anotacion que
alguien acepto. Por eso existe la columna `fuente_tf`: la marca se publica
siempre junto a la razon por la que se puso, fila por fila, para que quien lea
un numero rio abajo pueda quitar la evidencia que no le convenza y recontar.

La marca **sobre-incluye**: mete la mitad sensora de los sistemas de dos
componentes (las cinasas de histidina no unen ADN; el que lo une es el
regulador de respuesta) y mete los anti-sigma, que regulan secuestrando a un
factor sigma y no uniendose al promotor. Medido en esta corrida: 95 genes
entran por el keyword `Two-component regulatory system`.

La marca tambien **sub-incluye** lo que el patron de oro trata como TF sin
serlo. Tres casos concretos, y en los tres **la marca tiene razon y el oro no**:

- `ExsD` (PA1713) es un **antiactivador**: secuestra a ExsA. No une ADN.
- `FpvR` (PA2388) es un **anti-sigma**: retiene a FpvI y a PvdS en la membrana.
- `RsmA` (PA0905) une **ARN**, no ADN: es un regulador postranscripcional.

Esa discrepancia **se documenta, no se arregla**. Meterlos a mano en el
diccionario para que el patron de oro salga mejor evaluado es exactamente la
circularidad que el contrato prohibe: la evaluacion dejaria de medir lo que el
pipeline encuentra y pasaria a medir lo que le sopla el oro.

De donde sale cada fila
=======================

Cuatro fuentes publicas y una capa manual versionada, en este orden:

1. **RefSeq GFF de GCF_000006765.1** (1 peticion). El esqueleto: `locus_tag`,
   `gene`, `gene_biotype`, `product`. De la misma respuesta salen los 532
   features `protein_binding_site` que CollecTF deposito en el genoma.
2. **KEGG `rest.kegg.jp/list/pae`** (1 peticion). Simbolos y descripciones.
3. **UniProt, proteoma `UP000002438`** (12 peticiones, `size=500` siguiendo el
   header `Link: rel="next"`). GO, keywords y sinonimos. No se usa `/stream`:
   rebasa los 120 s del `timeout` por omision de `Cliente._abrir()`.
4. **UniProt, `taxonomy_id:287 AND reviewed:true`** (6 peticiones). Capa de
   alias de literatura. **Cada alias se ancla a un locus tag de PAO1 o se
   descarta**: estas entradas traen locus tags de otras cepas (`PA14_51340`) y
   mezclarlos contaminaria el diccionario con otro genoma.
5. **`etapa2/manual_pao1.tsv`**, con tope duro de 40 filas y justificacion en
   prosa obligatoria por fila.

`pseudomonas.com` no se usa: devuelve 403 a `urllib` incluso con User-Agent de
navegador, o sea proteccion de bot y no filtro de UA. Pasarla exigiria un
navegador headless: dependencia y evasion, las dos prohibidas por CLAUDE.md.

La procedencia se verifica en tres planos, y ninguno basta solo
===============================================================

1. **Fila contra carga.** Antes de renombrar nada,
   `verificar_procedencia()` comprueba contra las respuestas crudas que
   **cada** token de `fuente` y de `fuente_tf` esta respaldado por la carga
   que dice respaldarlo, y que ninguna carga que si contiene esa fila quedo
   sin declarar. Si una fila dice `refseq|kegg`, ese locus tag esta en el GFF
   y en la lista de KEGG y no esta en UniProt. Esto caza una columna `fuente`
   inventada. **No caza un GFF alterado**: la fila declara `refseq`, el GFF la
   contiene, y todo cuadra. Es un verificador que mide con el mismo archivo
   que tiene que vigilar.

2. **Bytes contra manifiesto.** `Cache.leer()` compara el sha256 y el tamano
   de cada archivo del cache con lo que `manifiesto.json` declara, **en cada
   lectura**, y con la URL cuando quien lee sabe cual pidio. Guardar el sha256
   y no volver a mirarlo era lo que dejaba pasar el ataque medido: un cache
   con 165 nombres del patron de oro inyectados en el GFF producia un
   diccionario de 5642 filas con codigo 0 y cobertura del oro del 95.8 %,
   mientras el manifiesto seguia exhibiendo el sha256 de la descarga honesta.

3. **Contenido contra contenido.** `corroborar_simbolos()` mide si las tres
   bases coinciden: RefSeq, KEGG y UniProt se descargan por separado y cada
   una nombra los genes de PAO1 por su cuenta. En la descarga honesta, 1765 de
   los 1766 simbolos del GFF aparecen tambien en KEGG o en UniProt para el
   mismo locus tag. Un nombre que solo exista en el archivo que se puede
   editar no es un dato: es una edicion. Este es el unico plano que sigue en
   pie si quien altera el cache altera tambien el manifiesto, que es un JSON
   de texto y no lleva firma.

Con el manifiesto, ademas, un revisor puede regenerar el diccionario entero
con `--sin-red` y comparar byte a byte.

**`oro` no es un valor valido de `fuente`.** Este script no abre el patron de
oro ni la auditoria de signo -- lo comprueba `etapa2/test_contaminacion.py` --
y si una fila llegara con esa procedencia sale con codigo 1 sin escribir nada.

Solo biblioteca estandar.

Uso:
    python etapa2/construir_diccionario.py --email alguien@unam.mx
    python etapa2/construir_diccionario.py --sin-red
"""

import argparse
import collections
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grn_etl import credenciales                      # noqa: E402
from grn_etl import db as basededatos                 # noqa: E402
from grn_etl import pubmed                            # noqa: E402

# ------------------------------------------------------------------ fuentes

URL_GFF = ("https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/006/765/"
           "GCF_000006765.1_ASM676v1/GCF_000006765.1_ASM676v1_genomic.gff.gz")
URL_KEGG = "https://rest.kegg.jp/list/pae"
UNIPROT = "https://rest.uniprot.org/uniprotkb/search"
CAMPOS_UNIPROT = ("accession,protein_name,gene_names,gene_primary,gene_oln,"
                  "gene_synonym,go_id,keyword")
CONSULTA_PROTEOMA = "proteome:UP000002438"
CONSULTA_ESPECIE = "taxonomy_id:287 AND reviewed:true"

COLUMNAS_GENES = ["locus_tag", "simbolo", "alias", "tipo", "producto",
                  "es_tf", "fuente_tf", "fuente", "sensible_mayusculas"]
COLUMNAS_OPERONES = ["operon", "miembros", "locus_tags", "fuente"]
COLUMNAS_COLLECTF = ["tf", "blanco", "experimento", "pmids", "en_corpus"]
COLUMNAS_MANUAL = ["id_canonico", "clase", "superficies", "miembros",
                   "justificacion"]

FUENTES_VALIDAS = ("refseq", "kegg", "uniprot", "uniprot_especie", "manual")
FUENTES_TF_VALIDAS = ("go_0003700", "go_0006355", "kw_transcription_regulation",
                      "kw_sigma_factor", "kw_two_component", "producto_refseq",
                      "collectf", "manual")
TIPOS_VALIDOS = ("protein_coding", "ncRNA", "tRNA", "rRNA", "pseudogene",
                 "complejo", "familia")

# La clave primaria del contrato. Los 58 locus tags de PAO1 con sufijo de
# letra (`PA0032a`) o con dos digitos tras el punto (`PA4726.11`) quedan fuera
# por esta regex, que es la que el contrato fija: 5639 filas de las 5697 que
# trae el GFF.
#
# De los 58 excluidos, uno solo tiene simbolo en RefSeq y duele: `crcZ`
# (PA4726.11), el sRNA que secuestra a Crc, con 399 menciones en 35 documentos
# del corpus. No se repone por la capa manual porque no es un alias de nada ni
# un complejo ni una familia, que son las tres clases que el contrato admite
# ahi, y meterlo con una clase que no le toca seria mentir en la columna
# `tipo`. Queda como ausencia conocida: es un cambio de una linea en esta
# regex, pero la regex la fija el contrato y cambiarla toca la clave primaria
# de todo el pipeline.
LOCUS = re.compile(r"^PA\d{4}(\.\d)?$")

# Un alias tiene que parecer un nombre. Sin este filtro entraban cadenas como
# `;` desde el campo `Gene Names` de UniProt, y una superficie asi resuelve en
# cualquier oracion con punto y coma.
ALIAS_SANO = re.compile(r"^[A-Za-z][A-Za-z0-9_.'-]{0,29}$")

# Un locus tag tal como CollecTF lo escribe en el campo Note. Mas laxo que
# LOCUS a proposito: ahi aparecen los sufijos de letra, y un blanco de
# CollecTF no es clave primaria de nada.
LOCUS_LAXO = re.compile(r"^PA\d{4}(\.\d+)?[a-z]?$")

# `gene_biotype` de RefSeq que el enum `tipo` del contrato no contempla.
# `tmRNA` y `RNase_P_RNA` son ARN no codificantes; se doblan a `ncRNA` en vez
# de inventar valores de enum, que romperia a quien valide la columna.
BIOTIPO_A_TIPO = {
    "protein_coding": "protein_coding", "ncRNA": "ncRNA", "tRNA": "tRNA",
    "rRNA": "rRNA", "pseudogene": "pseudogene", "tmRNA": "ncRNA",
    "RNase_P_RNA": "ncRNA", "antisense_RNA": "ncRNA", "SRP_RNA": "ncRNA",
}

# Los tres keywords de UniProt que el contrato admite como evidencia de TF.
KEYWORDS_TF = {
    "Transcription regulation": "kw_transcription_regulation",
    "Sigma factor": "kw_sigma_factor",
    "Two-component regulatory system": "kw_two_component",
}

# Descripcion de RefSeq que se acepta como evidencia `producto_refseq`.
#
# Es reconocimiento por patron sobre prosa y produce falsos positivos: en esta
# corrida marca `arr` (PA2818, "aminoglycoside response regulator", que es una
# ADP-ribosiltransferasa) y las cinasas hibridas sensoras PA1243 y PA2177. Se
# conserva porque es la unica evidencia que tienen los anti-sigma `mucA` y
# `mucB`, que el oro trata como TF y que UniProt no marca con ningun keyword
# de regulacion transcripcional. Cada fila que entra solo por aqui lleva
# `producto_refseq` como unico token de `fuente_tf`, asi que quitarlas es un
# filtro de una linea sobre el TSV.
#
# La alternativa `DNA-binding` a secas se probo y se quito: metia `ssb`
# (proteina de union a ADN de cadena sencilla), `hupB` (proteina HU) y dos Dps
# de estres, ninguna de las cuales regula transcripcion en el sentido que este
# pipeline busca.
PRODUCTO_TF = re.compile(
    r"transcription(al)?\s+(regulator|activator|repressor|factor)"
    r"|sigma[- ]?(factor|70|54)"
    r"|anti-sigma"
    r"|response\s+regulator",
    re.I)

# Simbolo con forma de miembro de operon: tres minusculas y una mayuscula.
# `mexA`, `oprM`, `pqsE`. Es la forma que la regla de §2 Salida B necesita
# para poder concatenar (`mexA` + `mexB` -> `mexAB`).
MIEMBRO_OPERON = re.compile(r"^([a-z]{3})([A-Z])$")

RUTA_PALABRAS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "palabras_comunes.txt")

MSG_SIN_FUENTE = ("UniProt/KEGG/RefSeq no contesto. No escribo un diccionario "
                  "incompleto y lo llamo completo: corre otra vez o usa "
                  "--cache.")
MSG_ORO = ("Hay filas cuya procedencia es el patron de oro. Eso hace circular "
           "la evaluacion (ver seccion 7 del contrato). No escribo.")

MSG_CACHE_SIN_MANIFIESTO = (
    "El cache tiene %s y manifiesto.json no lo describe. Un archivo del que no "
    "consta de que URL salio ni cuanto media no es la respuesta de una fuente "
    "publica: es un archivo que alguien dejo ahi. No construyo el diccionario "
    "con el. Borralo y vuelve a correr sin --sin-red.")

MSG_CACHE_ALTERADO = (
    "El cache no coincide con su manifiesto. %s mide %d bytes y su sha256 "
    "empieza con %s; el manifiesto declara %d bytes y %s. Esos no son los "
    "bytes que se descargaron de %s, asi que el diccionario que saldria de "
    "ellos no tendria la procedencia que dice tener. Borra el archivo y "
    "vuelve a correr sin --sin-red.")

MSG_CACHE_OTRA_URL = (
    "El manifiesto dice que %s se descargo de %s y este script pide %s. Es "
    "otra fuente: no la uso como si fuera esta.")

# Cuantos simbolos del GFF pueden quedar sin respaldo de una segunda fuente
# antes de dejar de escribir. Medido en la descarga honesta del 2026-08-20:
# de los 1766 locus tags que RefSeq nombra, 1689 llevan el mismo simbolo en
# KEGG y en UniProt, 76 en una de las dos y **1 en ninguna** (`ercS` de
# PA1976, que UniProt escribe `ercS'`). El margen hasta 12 es para el desfase
# real entre releases de las tres bases, no para nombres nuevos: 12 simbolos
# que solo existan en el GFF ya son un patron, no un desfase.
LIMITE_SIN_CORROBORAR = 12

MSG_SIN_CORROBORAR = (
    "%d simbolos del GFF no aparecen ni en KEGG ni en UniProt para el mismo "
    "locus tag, y el maximo que tolero son %d (en la descarga honesta es 1). "
    "Tres bases que se descargan por separado no coinciden en inventar el "
    "mismo nombre para el mismo locus; lo que si produce este patron es un "
    "GFF al que alguien le anadio nombres. No escribo. Los primeros:\n  %s")


# --------------------------------------------------------------- utilidades

def normalizar(campo):
    """Un campo de TSV no puede llevar tabulador ni salto de linea (§0.2)."""
    return " ".join(str(campo or "").split())


def lista(valores):
    """Lista `|` ordenada y sin duplicados, como pide §0.2."""
    return "|".join(sorted({normalizar(v).replace("|", " ") for v in valores
                            if normalizar(v)}))


def url_uniprot(consulta):
    """La URL de la primera pagina de una consulta de UniProt.

    Vive a nivel de modulo, y no dentro de `main()`, para que la comprobacion
    de URL del cache y las pruebas la construyan con este mismo codigo: dos
    copias de la misma cadena divergen y el sintoma seria un cache legitimo
    rechazado.
    """
    return "%s?%s" % (UNIPROT, urllib.parse.urlencode(
        {"query": consulta, "format": "tsv", "size": "500",
         "fields": CAMPOS_UNIPROT}))


def misma_url(una, otra):
    """Si dos URLs piden lo mismo, aunque los parametros vayan en otro orden.

    Se compara asi y no por igualdad de cadena porque el orden en que
    `urlencode()` escribe la consulta depende del orden del `dict` que se le
    pase, y una reordenacion del codigo invalidaria un cache legitimo entero.
    Lo que importa es que sea la misma peticion, no que sea el mismo texto.
    """
    a, b = urllib.parse.urlsplit(una), urllib.parse.urlsplit(otra)
    return ((a.scheme, a.netloc, a.path) == (b.scheme, b.netloc, b.path)
            and sorted(urllib.parse.parse_qsl(a.query))
            == sorted(urllib.parse.parse_qsl(b.query)))


def escribir_tsv(ruta, columnas, filas):
    """Escribe a `<ruta>.tmp`. El renombrado lo hace quien llama, al final,
    para que las tres salidas aparezcan juntas o no aparezca ninguna."""
    with open(ruta + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(columnas) + "\n")
        for fila in filas:
            f.write("\t".join(normalizar(fila.get(c, "")) for c in columnas)
                    + "\n")


def escribir_json(ruta, objeto):
    with open(ruta + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(ruta + ".tmp", ruta)


def leer_tsv(ruta, columnas):
    """Lee un TSV con encabezado exacto. Falla si no lo es."""
    filas = []
    with open(ruta, encoding="utf-8") as f:
        cabecera = f.readline().rstrip("\n").rstrip("\r").split("\t")
        if cabecera != columnas:
            raise ValueError("%s: encabezado %r; el contrato pide %r."
                             % (ruta, cabecera, columnas))
        for linea in f:
            linea = linea.rstrip("\n").rstrip("\r")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            partes += [""] * (len(columnas) - len(partes))
            filas.append(dict(zip(columnas, partes)))
    return filas


# -------------------------------------------------------------------- cache

class ClienteConCabeceras(pubmed.Cliente):
    """`pubmed.Cliente` que ademas recuerda las cabeceras de la respuesta.

    Existe por una sola razon: la paginacion de UniProt vive en el header
    `Link: <...>; rel="next"` y `Cliente.get()` devuelve solo el cuerpo. Las
    dos alternativas eran peores. Modificar `grn_etl/pubmed.py` lo prohibe el
    contrato y ademas tocaria la capa que usa el ETL de la fase 0. Abrir la
    URL con `urllib` por nuestra cuenta perderia lo que hace falta de verdad:
    el limitador de tasa, los reintentos con backoff y el contrato de errores
    de `get()` (`None` = el servidor contesto que no; excepcion = no pude
    preguntar).

    Se sobrescribe `_abrir()` y no `get()` porque es el unico punto donde
    existe el objeto de respuesta; la logica de reintentos queda intacta.
    """

    def __init__(self, *args, **kwargs):
        super(ClienteConCabeceras, self).__init__(*args, **kwargs)
        self.cabeceras = {}

    def _abrir(self, url, datos=None, timeout=120):
        req = urllib.request.Request(
            url, data=datos,
            headers={"User-Agent": "%s (%s)" % (self.tool, self.email)},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            self.cabeceras = dict(r.headers.items())
            return r.read()

    def enlace_siguiente(self):
        for clave, valor in self.cabeceras.items():
            if clave.lower() != "link":
                continue
            m = re.search(r'<([^>]+)>;\s*rel="next"', valor)
            if m:
                return m.group(1)
        return None


class Cache(object):
    """Las respuestas crudas, en disco, y la comprobacion de que siguen siendo
    las que se descargaron.

    Sin esto, cada corrida y cada prueba golpean a NCBI, a KEGG y a UniProt, y
    sobre todo no habria forma de que un tercero comprobara que el diccionario
    salio de esas cargas y no de otra parte.

    El sha256 se compara con los bytes de verdad EN CADA LECTURA
    ===========================================================

    Guardar el sha256 en el manifiesto y no volver a mirarlo no protege de
    nada, y el sintoma esta medido: se copio este cache, se descomprimio
    `refseq_gff.gz`, se le inyectaron 165 nombres tomados del patron de oro
    como `gene=` y `product=transcriptional regulator ...` sobre genes que
    RefSeq deja sin simbolo, y se volvio a comprimir. Con ese cache,
    `--sin-red` salia con CODIGO 0 publicando 5642 filas, 691 marcas de TF y
    una cobertura del patron de oro del 95.8 %, pasaba las ocho invariantes de
    la seccion 2 y pasaba `verificar_procedencia()`, que valida las filas
    contra el mismo GFF envenenado y por eso es estructuralmente incapaz de
    ver el ataque. Mientras tanto el manifiesto seguia exhibiendo el sha256 de
    la descarga honesta, porque en `--sin-red` no se reescribe y nadie lo
    leia. La cifra que habria salido tres etapas despues se llamaria
    exhaustividad y estaria midiendo el solapamiento del diccionario consigo
    mismo.

    Por eso `leer()` compara los bytes del archivo con el sha256 y el tamano
    que el manifiesto declara, y con la URL cuando quien llama sabe cual pidio.
    Un archivo que el manifiesto no describe no se usa: no consta de donde
    salio.

    Lo que esto NO resuelve, dicho claro: quien altere el cache puede alterar
    tambien el manifiesto, que es un JSON de texto. Contra eso no hay firma
    posible sin una clave, y aqui no hay ninguna. Lo que queda entonces es
    medir el contenido en vez de creerle a la etiqueta, y de eso se encarga
    `corroborar_simbolos()`: tres bases que se descargan por separado tienen
    que coincidir en como se llama cada locus tag.
    """

    def __init__(self, directorio, sin_red=False, refrescar=False):
        self.directorio = directorio
        self.sin_red = sin_red
        self.refrescar = refrescar
        self.ruta_manifiesto = os.path.join(directorio, "manifiesto.json")
        self.manifiesto = {}
        self.aciertos = 0
        self.descargas = 0
        if os.path.exists(self.ruta_manifiesto):
            with open(self.ruta_manifiesto, encoding="utf-8") as f:
                self.manifiesto = json.load(f)
        if not sin_red:
            os.makedirs(directorio, exist_ok=True)

    def ruta(self, nombre):
        return os.path.join(self.directorio, nombre)

    def tiene(self, nombre):
        return os.path.exists(self.ruta(nombre))

    def problema(self, nombre, url=None):
        """El motivo por el que estos bytes no se pueden usar, o `None`.

        Devuelve una cadena en vez de lanzar para que el modo con red pueda
        decidir otra cosa --avisar y volver a descargar-- donde `--sin-red`
        solo puede rendirse.
        """
        anotado = self.manifiesto.get(nombre)
        if not anotado:
            return MSG_CACHE_SIN_MANIFIESTO % nombre
        with open(self.ruta(nombre), "rb") as f:
            cuerpo = f.read()
        sha = hashlib.sha256(cuerpo).hexdigest()
        if sha != anotado.get("sha256") or len(cuerpo) != anotado.get("bytes"):
            return MSG_CACHE_ALTERADO % (
                nombre, len(cuerpo), sha[:16],
                anotado.get("bytes", -1), str(anotado.get("sha256"))[:16],
                anotado.get("url", "(sin url)"))
        if url is not None and not misma_url(anotado.get("url", ""), url):
            return MSG_CACHE_OTRA_URL % (nombre, anotado.get("url", ""), url)
        return None

    def leer(self, nombre, url=None):
        """Los bytes del cache, ya comprobados contra el manifiesto."""
        fallo = self.problema(nombre, url)
        if fallo:
            sys.exit(fallo)
        with open(self.ruta(nombre), "rb") as f:
            return f.read()

    def guardar(self, nombre, url, cuerpo, enlace=None):
        with open(self.ruta(nombre), "wb") as f:
            f.write(cuerpo)
        self.manifiesto[nombre] = {
            "url": url,
            "bytes": len(cuerpo),
            "sha256": hashlib.sha256(cuerpo).hexdigest(),
            "enlace_siguiente": enlace or "",
            "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def cerrar(self):
        if not self.sin_red:
            escribir_json(self.ruta_manifiesto, self.manifiesto)

    def pedir(self, cliente, url):
        """`Cliente.get()` con el contrato de errores del proyecto traducido.

        `None` = el servidor contesto y la respuesta es no (un 404 del FTP de
        RefSeq, un 403 de UniProt). Excepcion = no pude preguntar: DNS caido,
        sin ruta, o 5xx tras agotar los cuatro intentos. Para una fuente
        obligatoria las dos son la misma condicion de la seccion 2 --la fuente
        no contesto-- y las dos tienen que salir con el mensaje que el
        contrato le asigna.

        Antes solo se trataba el `None`. La excepcion, que es el caso mas
        frecuente y justo el de la maquina de laboratorio sin salida a
        internet, se escapaba hasta arriba: ocho lineas de traceback
        terminadas en `ErrorPubMed: ftp.ncbi.nlm.nih.gov fallo tras 4
        intentos` en lugar de una linea que dijera que hacer.
        """
        try:
            cuerpo = cliente.get(url)
        except pubmed.ErrorPubMed as e:
            sys.exit("%s\n  Lo que contesto la red: %s" % (MSG_SIN_FUENTE, e))
        if cuerpo is None:
            sys.exit(MSG_SIN_FUENTE)
        return cuerpo

    def obtener(self, nombre, url, cliente):
        """El cuerpo crudo de una peticion. Del cache si esta, de la red si no.

        El contrato define `--cache` como "guarda y REUTILIZA las respuestas
        crudas", y la mitad de reutilizar faltaba: sin `--sin-red` se llamaba
        siempre a `cliente.get()` y despues se guardaba, asi que con el cache
        lleno y correcto las peticiones evitadas eran cero y cada repeticion
        costaba las 20 peticiones (12 de ellas a UniProt, unos 21 s) contra
        servicios que bloquean por IP. Ahora un cache que casa con su
        manifiesto se reutiliza, y `--refrescar-cache` es la forma de pedir
        que no.

        Si el cache no casa con el manifiesto y hay red, se avisa y se vuelve
        a descargar: el archivo dudoso no se usa ni se calla.

        `--sin-red` nunca sale a la red: si falta una carga, el diccionario
        seria incompleto, y este script no escribe uno incompleto y lo llama
        completo.
        """
        if self.sin_red:
            if not self.tiene(nombre):
                sys.exit(MSG_SIN_FUENTE)
            return self.leer(nombre, url)
        if self.tiene(nombre) and not self.refrescar:
            fallo = self.problema(nombre, url)
            if fallo is None:
                self.aciertos += 1
                return self.leer(nombre, url)
            print("  Aviso: no reutilizo %s del cache y lo vuelvo a pedir.\n"
                  "  %s" % (nombre, fallo))
        cuerpo = self.pedir(cliente, url)
        self.descargas += 1
        self.guardar(nombre, url, cuerpo, cliente.enlace_siguiente())
        return cuerpo

    def paginas(self, prefijo, url, cliente):
        """Las paginas de una consulta de UniProt, en orden.

        Con red se sigue el header `Link: rel="next"`. Sin red se recorren los
        archivos por indice hasta que falta uno, que es el mismo orden porque
        asi se guardaron.
        """
        i = 0
        while True:
            i += 1
            nombre = "%s_%02d.tsv" % (prefijo, i)
            if self.sin_red:
                if not self.tiene(nombre):
                    if i == 1:
                        sys.exit(MSG_SIN_FUENTE)
                    return
                # La URL solo se comprueba en la primera pagina: las demas son
                # cursores que UniProt devuelve en el header `Link` y que
                # cambian entre descargas, asi que compararlas contra la
                # consulta original seria comparar contra nada.
                yield self.leer(nombre, url if i == 1 else None).decode(
                    "utf-8", "replace")
                continue
            if self.tiene(nombre) and not self.refrescar:
                fallo = self.problema(nombre, url if i == 1 else None)
                if fallo is None:
                    self.aciertos += 1
                    yield self.leer(nombre).decode("utf-8", "replace")
                    # El cursor a la pagina siguiente lo guardo la corrida que
                    # descargo esta: sin el, reutilizar la pagina 1 obligaria
                    # a volver a pedir las otras once.
                    url = self.manifiesto[nombre].get("enlace_siguiente") or None
                    if url is None:
                        return
                    continue
                print("  Aviso: no reutilizo %s del cache y lo vuelvo a "
                      "pedir.\n  %s" % (nombre, fallo))
            if url is None:
                return
            cuerpo = self.pedir(cliente, url)
            self.descargas += 1
            enlace = cliente.enlace_siguiente()
            self.guardar(nombre, url, cuerpo, enlace)
            yield cuerpo.decode("utf-8", "replace")
            url = enlace


# ------------------------------------------------------------ analisis GFF

def _atributos(campo):
    """Los atributos de la novena columna del GFF, ya des-escapados.

    Se parte por `;` ANTES de des-escapar: un `%3B` dentro de un valor es un
    punto y coma literal y partir despues lo cortaria en dos.
    """
    salida = {}
    for kv in campo.split(";"):
        if "=" not in kv:
            continue
        clave, valor = kv.split("=", 1)
        salida[clave.strip()] = urllib.parse.unquote(valor).strip().strip("'\"")
    return salida


def analizar_gff(texto):
    """(genes, sitios) del GFF de RefSeq.

    `genes` va indexado por locus tag y en orden genomico; `sitios` son los
    features `protein_binding_site` que CollecTF deposito.
    """
    genes = collections.OrderedDict()
    sitios = []
    for linea in texto.splitlines():
        if not linea or linea.startswith("#"):
            continue
        campos = linea.split("\t")
        if len(campos) < 9:
            continue
        tipo, inicio, hebra = campos[2], campos[3], campos[6]
        attrs = _atributos(campos[8])
        if tipo == "protein_binding_site":
            sitios.append(attrs)
            continue
        locus = attrs.get("locus_tag")
        if not locus:
            continue
        if tipo in ("gene", "pseudogene"):
            genes[locus] = {
                "locus_tag": locus,
                "simbolo": attrs.get("gene", ""),
                "biotipo": attrs.get("gene_biotype", ""),
                "producto": "",
                "hebra": hebra,
                "inicio": int(inicio),
            }
        elif locus in genes:
            # El simbolo y el producto viven en el feature hijo (CDS, tRNA,
            # ncRNA) tanto como en el padre, pero no siempre en los dos: se
            # toma el primero que aparezca y no se pisa.
            if not genes[locus]["simbolo"] and attrs.get("gene"):
                genes[locus]["simbolo"] = attrs["gene"]
            if not genes[locus]["producto"] and attrs.get("product"):
                genes[locus]["producto"] = attrs["product"]
    return genes, sitios


def _partir_por_comas(texto):
    """Parte por comas de primer nivel: no parte dentro de `[...]`.

    Hace falta porque el campo `experiment` de CollecTF es
    `ChIP-Seq [PMID: 24603766],RNA-Seq [PMID: 24603766]` y hay nombres de
    ensayo que llevan corchetes propios (`qPCR [quantitative real-time]`).
    """
    partes, actual, hondo = [], [], 0
    for c in texto:
        if c == "[":
            hondo += 1
        elif c == "]":
            hondo = max(0, hondo - 1)
        if c == "," and hondo == 0:
            partes.append("".join(actual))
            actual = []
        else:
            actual.append(c)
    partes.append("".join(actual))
    return [p.strip() for p in partes if p.strip()]


def analizar_sitios(sitios):
    """Los pares (TF, blanco) de CollecTF, agregados sobre todos los sitios.

    Un sitio sin `Evidence of regulation for:` es un sitio de union sin gen
    regulado declarado: no produce par, pero su TF si cuenta como TF.
    """
    pares = collections.OrderedDict()
    moieties = collections.Counter()
    for attrs in sitios:
        tf = normalizar(attrs.get("bound_moiety", ""))
        if not tf:
            continue
        moieties[tf] += 1
        experimentos, pmids = set(), set()
        for parte in _partir_por_comas(attrs.get("experiment", "")):
            for m in re.finditer(r"\[PMID:\s*([0-9,\s]+)\]", parte):
                for p in re.split(r"[,\s]+", m.group(1)):
                    if p.isdigit():
                        pmids.add(int(p))
            nombre = normalizar(re.sub(r"\[PMID:[^\]]*\]", "", parte).strip("'\" "))
            if nombre:
                experimentos.add(nombre)
        nota = attrs.get("Note", "")
        if "Evidence of regulation for:" not in nota:
            continue
        cola = nota.split("Evidence of regulation for:", 1)[1]
        for bruto in re.split(r"[,;~]", cola):
            blanco = normalizar(bruto)
            if not LOCUS_LAXO.match(blanco):
                continue
            registro = pares.setdefault((tf, blanco),
                                        {"experimentos": set(), "pmids": set()})
            registro["experimentos"] |= experimentos
            registro["pmids"] |= pmids
    return pares, moieties


# ----------------------------------------------------------- analisis KEGG

def analizar_kegg(texto):
    """{locus_tag: (simbolo, descripcion)} de `rest.kegg.jp/list/pae`.

    Formato de cada linea: `pae:PA0001<tab>CDS<tab>483..2027<tab>dnaA;
    chromosome replication initiator DnaA`. El simbolo solo esta cuando hay
    `; ` y lo que va antes no lleva espacios; si no, la cuarta columna es la
    descripcion pelada.
    """
    salida = {}
    for linea in texto.splitlines():
        campos = linea.rstrip("\n").split("\t")
        if len(campos) < 4 or ":" not in campos[0]:
            continue
        locus = campos[0].split(":", 1)[1].strip()
        descripcion = campos[3].strip()
        simbolo = ""
        if "; " in descripcion:
            cabeza, resto = descripcion.split("; ", 1)
            if " " not in cabeza:
                # KEGG separa sinonimos con coma: `mexA, PA0425`.
                simbolo = cabeza.split(",")[0].strip()
                descripcion = resto
        salida[locus] = (simbolo, descripcion)
    return salida


# -------------------------------------------------------- analisis UniProt

def analizar_uniprot(paginas):
    """Las filas de un TSV paginado de UniProt, con encabezado por pagina."""
    filas = []
    for texto in paginas:
        lineas = texto.splitlines()
        if not lineas:
            continue
        cabecera = lineas[0].split("\t")
        for linea in lineas[1:]:
            campos = linea.split("\t")
            campos += [""] * (len(cabecera) - len(campos))
            filas.append(dict(zip(cabecera, campos)))
    return filas


def indexar_uniprot(filas):
    """({locus_tag PAO1: [entrada, ...]}, cuantas entradas se descartaron).

    El ancla es `Gene Names (ordered locus)`. Una entrada de la consulta por
    especie que trae `PA14_51340` y ningun `PA\\d{4}` es de otra cepa: sus
    alias no se pueden colgar de ningun gen de PAO1 sin mezclar dos genomas,
    asi que se descarta entera.
    """
    indice = collections.defaultdict(list)
    descartadas = 0
    for fila in filas:
        loci = [x for x in fila.get("Gene Names (ordered locus)", "").split()
                if LOCUS.match(x)]
        if not loci:
            descartadas += 1
            continue
        for locus in loci:
            indice[locus].append(fila)
    return indice, descartadas


def _nombres_uniprot(fila):
    """(primario, [sinonimos]) de una entrada de UniProt, sin locus tags."""
    primario = normalizar(fila.get("Gene Names (primary)", "")).split(" ")[0]
    if LOCUS_LAXO.match(primario):
        primario = ""
    sinonimos = []
    for campo in ("Gene Names (synonym)", "Gene Names"):
        for nombre in normalizar(fila.get(campo, "")).split(" "):
            if nombre and not LOCUS_LAXO.match(nombre) and nombre != primario:
                sinonimos.append(nombre)
    return primario, sinonimos


def marcas_tf_uniprot(fila):
    """Los tokens de `fuente_tf` que una entrada de UniProt respalda."""
    marcas = set()
    gos = {x.strip() for x in fila.get("Gene Ontology IDs", "").split(";")}
    if "GO:0003700" in gos:
        marcas.add("go_0003700")
    if "GO:0006355" in gos:
        marcas.add("go_0006355")
    for kw in fila.get("Keywords", "").split(";"):
        token = KEYWORDS_TF.get(kw.strip())
        if token:
            marcas.add(token)
    return marcas


# ------------------------------------------------------------- capa manual

def leer_manual(ruta):
    """Las filas de `manual_pao1.tsv`, validadas.

    La justificacion es obligatoria: una fila manual sin ella es una entidad
    que alguien metio a mano y nadie puede auditar, que es justo en lo que la
    capa manual no debe convertirse.
    """
    if not os.path.exists(ruta):
        return []
    filas = leer_tsv(ruta, COLUMNAS_MANUAL)
    for i, fila in enumerate(filas, 1):
        etiqueta = "manual_pao1.tsv fila %d (%s)" % (i, fila["id_canonico"])
        if fila["clase"] not in ("alias", "complejo", "familia"):
            sys.exit("%s: clase %r fuera del enum (alias, complejo, familia)."
                     % (etiqueta, fila["clase"]))
        if not fila["id_canonico"].strip():
            sys.exit("manual_pao1.tsv fila %d: id_canonico vacio." % i)
        if not fila["superficies"].strip():
            sys.exit("%s: sin superficies." % etiqueta)
        if not fila["justificacion"].strip():
            sys.exit("%s: la justificacion es obligatoria." % etiqueta)
        if fila["clase"] == "alias" and fila["miembros"].strip():
            sys.exit("%s: clase alias no lleva miembros." % etiqueta)
        if fila["clase"] != "alias" and not fila["miembros"].strip():
            sys.exit("%s: un %s tiene que declarar sus miembros."
                     % (etiqueta, fila["clase"]))
    return filas


def es_tf_manual(fila):
    """Una fila manual marca TF si su justificacion empieza con `TF:`.

    Se pide el prefijo explicito, y no una columna booleana, para que quien
    marque un TF a mano tenga que escribir en la misma celda por que lo hace.
    """
    return fila["justificacion"].strip().lower().startswith("tf:")


def leer_palabras_comunes(ruta):
    palabras = set()
    if not os.path.exists(ruta):
        return palabras
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.split("#", 1)[0].strip().lower()
            if linea:
                palabras.add(linea)
    return palabras


def validar_entidad_manual(fila, gff, por_simbolo, ya_vistas):
    """Las filas manuales de clase `complejo` y `familia`, contra el GFF.

    Las de clase `alias` llevaban desde el principio dos candados --anclarse a
    un locus tag que exista en el GFF, y no renombrar un gen que una fuente
    publica ya nombro-- y estas dos clases no llevaban ninguno. El mensaje del
    primer candado hasta senalaba la puerta abierta: "si es una entidad nueva,
    declarala como complejo o familia".

    Sintoma medido: 14 entidades fabricadas (exoU, pel, psl, cdrA, CpxR,
    PirR...) con `miembros` PA9999|NOEXISTE y ZZZZ entraron al diccionario con
    `fuente=manual` y codigo de salida 0, y los blancos del patron de oro que
    resolvian subieron de 94/110 a 105/110 sin que existiera un solo gen nuevo.
    `verificar_procedencia()` no podia verlo: construye `indices["manual"]` con
    los `id_canonico` de esas mismas filas, o sea que se confirmaba a si misma.
    `miembros` era la unica columna que nadie miraba, y es justamente la que
    dice de que genes reales se compone la entidad.

    Cuatro reglas, todas contra el GFF y no contra la propia fila:

    1. El `id_canonico` no puede tener forma de locus tag: un complejo no es
       un gen y no puede hacerse pasar por uno.
    2. El `id_canonico` no puede chocar con el simbolo publico de un gen. Si
       chocara, esa superficie resolveria a dos entidades y `Lexico` no
       emitiria mencion para ninguna de las dos (regla 4 de 1.2): se perderia
       tambien el gen real.
    3. Cada miembro tiene que ser un locus tag de PAO1 **que este en el GFF**,
       y tiene que haber al menos dos. Con uno solo la entidad es un alias de
       ese gen y le toca la clase `alias`, que si esta blindada.
    4. Dos filas manuales no pueden producir el mismo `id_canonico`.

    La marca de TF se comprueba aparte, ya con el diccionario armado: ver
    `construir_genes()`.
    """
    idc = fila["id_canonico"].strip()
    etiqueta = "manual_pao1.tsv: la fila %r (%s)" % (idc, fila["clase"])
    if LOCUS_LAXO.match(idc):
        sys.exit("%s tiene forma de locus tag. Un %s no es un gen: si lo que "
                 "quieres es agregarle superficies a ese gen, la clase es "
                 "alias." % (etiqueta, fila["clase"]))
    dueno = por_simbolo.get(idc.lower())
    if dueno is not None:
        sys.exit("%s choca con el simbolo que RefSeq le da a %s. Esa "
                 "superficie resolveria a dos entidades y Lexico no emitiria "
                 "mencion para ninguna, asi que se perderia tambien el gen "
                 "real." % (etiqueta, dueno))
    if idc in {f["id_canonico"].strip() for f in ya_vistas}:
        sys.exit("%s ya la declaro otra fila de la capa manual." % etiqueta)
    miembros = [m.strip() for m in fila["miembros"].split("|") if m.strip()]
    for miembro in miembros:
        if not LOCUS.match(miembro) or miembro not in gff:
            sys.exit("%s declara el miembro %r, que no es un locus tag de "
                     "PAO1 presente en el GFF de RefSeq. Los miembros son la "
                     "unica prueba de que la entidad se compone de genes que "
                     "existen." % (etiqueta, miembro))
    if len(miembros) < 2:
        sys.exit("%s declara %d miembro. Un %s de un solo gen es un alias de "
                 "ese gen: usa la clase alias, que se ancla al locus tag."
                 % (etiqueta, len(miembros), fila["clase"]))


# ----------------------------------------------------- construccion de filas

def construir_genes(gff, kegg, uni, esp, manual, palabras, moieties):
    """Las filas de `genes_pao1.tsv`, en orden genomico.

    Devuelve (filas, indices), donde `indices` son los conjuntos crudos con
    los que `verificar_procedencia()` vuelve a comprobar cada `fuente`.
    """
    por_simbolo = {}
    for locus, gen in gff.items():
        if LOCUS.match(locus) and gen["simbolo"]:
            por_simbolo.setdefault(gen["simbolo"].lower(), locus)

    # Donde se ancla cada fila manual de clase `alias`, y que simbolo bautiza.
    #
    # El ancla es siempre un locus tag: el de `id_canonico` si lo es, y si no,
    # el primero que aparezca entre las superficies. Anclar por locus tag y no
    # por nombre es lo que impide que la capa manual invente genes: la fila
    # tiene que apuntar a una fila que ya salio de RefSeq.
    #
    # Si el gen anclado no tiene simbolo en ninguna fuente publica --que es el
    # caso de PA3678, PA3677 y PA3676, o sea mexL, mexJ y mexK--, el
    # `id_canonico` de la fila manual pasa a ser su simbolo. Sin eso, la
    # entidad canonica seguiria siendo `PA3678` y la tabla de operones, que se
    # deriva de los simbolos, no podria formar `mexJK`: medido, el PMID
    # 40011517 son 86 KB dedicados a MexL, lo nombra 388 veces y sin simbolo
    # daba 2 pares.
    #
    # Si el gen anclado YA tiene simbolo, el `id_canonico` tiene que coincidir
    # con el. La capa manual agrega superficies; no renombra genes que una
    # fuente publica ya nombro.
    manual_por_locus = collections.defaultdict(list)
    simbolo_manual = {}
    manual_entidades = []
    for fila in manual:
        if fila["clase"] != "alias":
            validar_entidad_manual(fila, gff, por_simbolo, manual_entidades)
            manual_entidades.append(fila)
            continue
        idc = fila["id_canonico"].strip()
        superficies = [s.strip() for s in fila["superficies"].split("|")]
        candidatos = ([idc] if LOCUS.match(idc) else []) + [
            s for s in superficies if LOCUS.match(s)]
        locus = candidatos[0] if candidatos else por_simbolo.get(idc.lower())
        if locus is None or locus not in gff:
            sys.exit("manual_pao1.tsv: la fila %r no se ancla a ningun locus "
                     "tag de PAO1. Pon el locus tag en id_canonico o entre las "
                     "superficies; si es una entidad nueva, declarala como "
                     "complejo o familia." % idc)
        publico = gff[locus]["simbolo"]
        if publico and not LOCUS.match(idc) and idc != publico:
            sys.exit("manual_pao1.tsv: la fila %r quiere renombrar %s, que "
                     "RefSeq ya llama %r. La capa manual agrega superficies, "
                     "no renombra genes." % (idc, locus, publico))
        if not publico and not LOCUS.match(idc):
            simbolo_manual[locus] = idc
        manual_por_locus[locus].append(fila)

    filas = []
    for locus, gen in gff.items():
        if not LOCUS.match(locus):
            continue
        fuente = ["refseq"]
        fuente_tf = set()
        alias = {locus}
        simbolo = gen["simbolo"]
        producto = gen["producto"]

        if locus in kegg:
            fuente.append("kegg")
            simbolo_kegg, descripcion_kegg = kegg[locus]
            if simbolo_kegg:
                if not simbolo:
                    simbolo = simbolo_kegg
                elif simbolo_kegg != simbolo:
                    alias.add(simbolo_kegg)
            if not producto:
                producto = descripcion_kegg

        if locus in uni:
            fuente.append("uniprot")
            for entrada in uni[locus]:
                primario, sinonimos = _nombres_uniprot(entrada)
                if primario:
                    if not simbolo:
                        simbolo = primario
                    elif primario != simbolo:
                        alias.add(primario)
                alias.update(sinonimos)
                fuente_tf |= marcas_tf_uniprot(entrada)
                if not producto:
                    producto = entrada.get("Protein names", "")

        if locus in esp:
            fuente.append("uniprot_especie")
            for entrada in esp[locus]:
                primario, sinonimos = _nombres_uniprot(entrada)
                if primario and primario != simbolo:
                    alias.add(primario)
                alias.update(sinonimos)
                fuente_tf |= marcas_tf_uniprot(entrada)

        if PRODUCTO_TF.search(gen["producto"] or ""):
            fuente_tf.add("producto_refseq")

        for fila in manual_por_locus.get(locus, []):
            if "manual" not in fuente:
                fuente.append("manual")
            if locus in simbolo_manual and not simbolo:
                simbolo = simbolo_manual[locus]
            alias.update(s.strip() for s in fila["superficies"].split("|"))
            if es_tf_manual(fila):
                fuente_tf.add("manual")

        if _es_bound_moiety(locus, simbolo, moieties):
            fuente_tf.add("collectf")

        alias.discard(simbolo)
        alias.discard("")
        filas.append({
            "locus_tag": locus,
            "simbolo": simbolo,
            "alias": lista(alias),
            "tipo": BIOTIPO_A_TIPO.get(gen["biotipo"], "ncRNA"),
            "producto": normalizar(producto),
            "es_tf": "true" if fuente_tf else "false",
            "fuente_tf": lista(fuente_tf),
            "fuente": "|".join(sorted(set(fuente), key=FUENTES_VALIDAS.index)),
            "sensible_mayusculas": "",   # se calcula abajo, con la fila entera
        })

    # Entidades que ninguna base publica tiene: complejos y familias.
    #
    # Van con `locus_tag` vacio, y es la unica desviacion deliberada de las
    # columnas de §2. La razon es que el contrato se contradice consigo mismo:
    # declara `locus_tag` clave primaria unica y obligatoria, y a la vez admite
    # `tipo=complejo`, y su propio ejemplo es IHF, heterodimero de PA2738 y
    # PA3161. Un heterodimero no tiene UN locus tag. Ponerle el del primer
    # miembro duplicaria la clave y, peor, haria que la superficie `PA2738`
    # resolviera a dos entidades distintas, con lo que `Lexico` dejaria de
    # emitir mencion para ella (regla 4 de §1.2) y se perderia el gen real.
    # Dejarlo vacio no rompe nada aguas abajo: `Lexico` usa
    # `simbolo or locus_tag` como id canonico. Los miembros quedan registrados
    # en `manual_pao1.tsv`, que es el archivo auditable, y en prosa dentro de
    # `producto`.
    # La quinta regla de `validar_entidad_manual()`, que necesita el
    # diccionario ya armado: una entidad manual solo puede marcarse TF si
    # alguno de sus genes miembros lleva la marca por evidencia publica. Sin
    # esto, `es_tf=true` se concedia por escribir `TF:` al principio de la
    # justificacion, o sea por una etiqueta que la propia fila se pone.
    # IHF la cumple: PA2738 y PA3161 llevan marca por GO y por keyword.
    tf_por_locus = {f["locus_tag"]: f["es_tf"] == "true" for f in filas
                    if f["locus_tag"]}
    # El choque con un simbolo publico se comprobo contra el GFF, que es lo
    # que se puede saber antes de construir. Aqui se vuelve a comprobar contra
    # el diccionario ya armado, que ademas trae los simbolos que aportaron
    # KEGG, UniProt y las propias filas manuales de clase `alias`: sin esto,
    # una entidad llamada `mexL` pasaria el primer filtro (RefSeq no nombra
    # PA3678) y chocaria con el nombre que la capa manual le acaba de poner.
    simbolos_ya = {f["simbolo"].lower() for f in filas if f["simbolo"]}
    for fila in manual_entidades:
        idc = fila["id_canonico"].strip()
        if idc.lower() in simbolos_ya:
            sys.exit("manual_pao1.tsv: la fila %r choca con el simbolo de un "
                     "gen del diccionario. Esa superficie resolveria a dos "
                     "entidades y Lexico no emitiria mencion para ninguna."
                     % idc)
        simbolos_ya.add(idc.lower())
        superficies = {s.strip() for s in fila["superficies"].split("|")
                       if s.strip()}
        superficies.discard(idc)
        marca = es_tf_manual(fila)
        if marca and not any(tf_por_locus.get(m.strip())
                             for m in fila["miembros"].split("|")):
            sys.exit("manual_pao1.tsv: la fila %r se declara TF y ninguno de "
                     "sus miembros (%s) lleva la marca por evidencia publica. "
                     "Escribir 'TF:' en la justificacion no es evidencia."
                     % (idc, fila["miembros"]))
        filas.append({
            "locus_tag": "",
            "simbolo": idc,
            "alias": lista(superficies),
            "tipo": fila["clase"],
            "producto": normalizar(fila["justificacion"]),
            "es_tf": "true" if marca else "false",
            "fuente_tf": "manual" if marca else "",
            "fuente": "manual",
            "sensible_mayusculas": "",
        })

    # El ancla de la capa manual se comprobo contra el simbolo de RefSeq, pero
    # KEGG o UniProt pueden traer uno que RefSeq no tenia. Si eso pasa, el
    # `id_canonico` de la fila manual y el simbolo real dejarian de coincidir
    # sin que nada avisara, y quien leyera `manual_pao1.tsv` creeria que la
    # entidad se llama de una forma cuando el diccionario la llama de otra.
    por_locus_final = {f["locus_tag"]: f for f in filas if f["locus_tag"]}
    for locus, idc in simbolo_manual.items():
        real = por_locus_final[locus]["simbolo"]
        if real != idc:
            sys.exit("manual_pao1.tsv: la fila %r se ancla en %s, pero alguna "
                     "fuente publica ya lo llama %r. Actualiza la capa manual: "
                     "el nombre publico manda." % (idc, locus, real))

    quitados = depurar_alias(filas)
    for fila in filas:
        fila["sensible_mayusculas"] = (
            "true" if es_sensible(fila, palabras) else "false")

    indices = {
        "refseq": {locus for locus in gff if LOCUS.match(locus)},
        "kegg": set(kegg),
        "uniprot": set(uni),
        "uniprot_especie": set(esp),
        "manual": set(manual_por_locus) | {f["id_canonico"].strip()
                                           for f in manual_entidades},
    }
    return filas, indices, quitados


def depurar_alias(filas):
    """Quita los alias que no pueden servir de superficie. Devuelve el conteo.

    Dos reglas, las dos con sintoma medido:

    1. **Un alias tiene que parecer un nombre.** El campo `Gene Names` de
       UniProt trajo un `;` suelto, y una superficie asi resuelve en cualquier
       oracion que lleve punto y coma.
    2. **El simbolo de un gen le gana al alias de otro.** UniProt registra
       `rsmA` como sinonimo de `ksgA` (PA0592, la metiltransferasa ribosomal
       16S), y `rsmA` es el simbolo de PA0905, el regulador post-
       transcripcional que el corpus nombra 2004 veces en 102 documentos. Con
       las dos superficies vivas, `Lexico` las marca como ambiguas y **no
       emite mencion para ninguna** (regla 4 de §1.2), asi que la colision no
       se reparte el dano: se pierden los dos genes. Quitar el alias, que es
       el derivado, conserva el gen que si se llama asi.

    Sin estas dos reglas quedaban 33 superficies ambiguas; con ellas, la
    mayoria eran alias de UniProt pisando simbolos de RefSeq.
    """
    simbolos = {}
    for fila in filas:
        if fila["simbolo"]:
            simbolos[fila["simbolo"].lower()] = fila["simbolo"]
    quitados = collections.Counter()
    for fila in filas:
        conservados = []
        for alias in fila["alias"].split("|"):
            if not alias:
                continue
            if not ALIAS_SANO.match(alias):
                quitados["forma"] += 1
                continue
            dueno = simbolos.get(alias.lower())
            if dueno is not None and dueno != fila["simbolo"]:
                quitados["choca_con_un_simbolo"] += 1
                continue
            conservados.append(alias)
        fila["alias"] = lista(conservados)
    return quitados


def _es_bound_moiety(locus, simbolo, moieties):
    """CollecTF nombra al TF en forma de proteina (`AmrZ`) o por locus tag."""
    formas = {locus}
    if simbolo:
        formas.add(simbolo)
        formas.add(simbolo[:1].upper() + simbolo[1:])
    return bool(formas & set(moieties))


def superficies_de(fila):
    """Todas las cadenas por las que se puede reconocer la fila."""
    superficies = set()
    if fila["locus_tag"]:
        superficies.add(fila["locus_tag"])
    if fila["simbolo"]:
        superficies.add(fila["simbolo"])
    superficies.update(a for a in fila["alias"].split("|") if a)
    return superficies


def es_sensible(fila, palabras):
    """Regla de `sensible_mayusculas` de §2.

    `true` si alguna superficie de la fila, en minusculas, tiene 3 caracteres
    o menos, o esta en `palabras_comunes.txt`. Medido en 60 documentos con
    reconocimiento insensible contra sensible: `cat` 38 vs 2, `his` 47 vs 3,
    `fur` 32 vs 13, `map` 70 vs 44. La diferencia son falsos positivos puros.
    """
    for s in superficies_de(fila):
        bajo = s.lower()
        if len(bajo) <= 3 or bajo in palabras:
            return True
    return False


# --------------------------------------------------------------- procedencia

def corroborar_simbolos(gff, kegg, uni, esp):
    """Los simbolos del GFF que ninguna otra fuente confirma para ese locus.

    NO PREGUNTA QUE DICE SER, MIDE QUE ES
    =====================================

    `verificar_procedencia()` comprueba que cada fila declare las cargas que
    de verdad la contienen, y eso es util contra una columna `fuente`
    inventada, pero es ciego ante el ataque que importa: si alguien edita el
    GFF del cache y le mete nombres, la fila los declara con `refseq` y el GFF
    los contiene, asi que todo cuadra. El verificador estaba midiendo con el
    mismo archivo que tenia que vigilar.

    Esto mide otra cosa: **si las tres bases coinciden**. RefSeq, KEGG y
    UniProt se descargan por separado, de tres servidores distintos, y cada
    una nombra los genes de PAO1 por su cuenta. Que las tres llamen `mexT` a
    PA2492 es una medicion; que solo lo haga el archivo que el atacante puede
    editar, no.

    Medido en la descarga honesta del 2026-08-20, sobre los 1766 locus tags
    que RefSeq nombra: 1689 llevan el mismo simbolo en KEGG **y** en UniProt,
    76 en una de las dos, y 1 en ninguna (`ercS` de PA1976, que UniProt
    escribe `ercS'`). El ataque demostrado inyecto 142 nombres en genes que
    RefSeq deja sin simbolo: los 142 salen aqui sin corroborar y el script no
    escribe.

    Limite honesto de lo que esto cubre: quien envenene dos de las tres
    cargas de forma coherente vuelve a pasar. Sube el precio del ataque de un
    archivo a dos, y lo deja visible en el manifiesto de las dos.

    Devuelve [(locus_tag, simbolo), ...] en orden genomico.
    """
    sueltos = []
    for locus, gen in gff.items():
        simbolo = gen["simbolo"]
        if not LOCUS.match(locus) or not simbolo:
            continue
        bajo = simbolo.lower()
        otros = set()
        if locus in kegg and kegg[locus][0]:
            otros.add(kegg[locus][0].lower())
        for entrada in list(uni.get(locus, [])) + list(esp.get(locus, [])):
            primario, sinonimos = _nombres_uniprot(entrada)
            if primario:
                otros.add(primario.lower())
            otros.update(x.lower() for x in sinonimos)
        if bajo not in otros:
            sueltos.append((locus, simbolo))
    return sueltos


def verificar_procedencia(filas, indices, gff, uni, esp, moieties, manual):
    """Comprueba fila por fila que `fuente` y `fuente_tf` dicen la verdad.

    Es el guardian que distingue un diccionario derivado de fuentes publicas
    de uno fabricado copiando el patron de oro. No basta con prohibir el valor
    `oro`: quien copie el oro y escriba `refseq` pasaria esa prohibicion sin
    despeinarse. Lo que no puede falsificar es que el locus tag este de verdad
    en el GFF que se descargo y cuyo sha256 quedo en el manifiesto del cache.

    Devuelve la lista de problemas; vacia si todo cuadra.
    """
    problemas = []
    manual_tf = {f["id_canonico"].strip() for f in manual if es_tf_manual(f)}
    for fila in filas:
        locus = fila["locus_tag"]
        idc = fila["simbolo"] or locus
        clave = locus or idc
        declaradas = [f for f in fila["fuente"].split("|") if f]
        if not declaradas:
            problemas.append("Fila %s: sin procedencia declarada." % idc)
        for token in declaradas:
            if token == "oro":
                problemas.append("oro")
            elif token not in FUENTES_VALIDAS:
                problemas.append("Fila %s: fuente %r fuera del enum."
                                 % (idc, token))
            elif clave not in indices[token]:
                problemas.append(
                    "Fila %s declara la fuente %r y esa carga no la contiene."
                    % (idc, token))
        # Y al reves: una carga que si trae la fila tiene que estar declarada.
        for token in FUENTES_VALIDAS:
            if clave in indices[token] and token not in declaradas:
                problemas.append("Fila %s esta en la carga %r y no la declara."
                                 % (idc, token))

        for token in [t for t in fila["fuente_tf"].split("|") if t]:
            if token not in FUENTES_TF_VALIDAS:
                problemas.append("Fila %s: fuente_tf %r fuera del enum."
                                 % (idc, token))
            elif token == "producto_refseq":
                if not PRODUCTO_TF.search(gff.get(locus, {}).get("producto", "")):
                    problemas.append(
                        "Fila %s declara producto_refseq y el producto de "
                        "RefSeq no lo respalda." % idc)
            elif token == "collectf":
                if not _es_bound_moiety(locus, fila["simbolo"], moieties):
                    problemas.append(
                        "Fila %s declara collectf y no es bound_moiety de "
                        "ningun sitio del GFF." % idc)
            elif token == "manual":
                if idc not in manual_tf and locus not in manual_tf:
                    problemas.append(
                        "Fila %s declara la marca manual y manual_pao1.tsv no "
                        "la justifica como TF." % idc)
            else:
                entradas = list(uni.get(locus, [])) + list(esp.get(locus, []))
                if not any(token in marcas_tf_uniprot(e) for e in entradas):
                    problemas.append(
                        "Fila %s declara %r y ninguna entrada de UniProt lo "
                        "respalda." % (idc, token))
    return problemas


# ------------------------------------------------------------------ operones

def derivar_operones(filas, gff):
    """`operones_pao1.tsv`, derivado del diccionario. Nunca copiado de una lista.

    Regla de §2 Salida B: genes con locus tags consecutivos cuyos simbolos son
    prefijo de tres minusculas mas una mayuscula se agrupan; grupos adyacentes
    de prefijos distintos se unen con guion. Se emiten todas las sub-corridas
    contiguas de longitud >= 2 de cada corrida maximal.

    Dos precisiones que la regla escrita no traia, y por que:

    1. Los miembros van en **orden de transcripcion**, no de locus tag
       ascendente. Verificado en el GFF: `mexCD-oprJ` va en la hebra menos
       (PA4597 oprJ, PA4598 mexD, PA4599 mexC), asi que por locus tag
       ascendente el nombre que sale es `oprJ-mexDC`, que no existe en ninguna
       parte. Con la hebra sale `mexCD-oprJ`, que es como lo llaman el corpus
       y dos filas del patron de oro. `mexAB-oprM` y `mexEF-oprN` salian bien
       solo porque van en la hebra mas. La hebra viene en el GFF: usarla sigue
       siendo derivar del diccionario, no copiar una lista.
    2. Una corrida no cruza un cambio de hebra. Dos genes contiguos en hebras
       opuestas son divergentes o convergentes: no comparten promotor y no
       forman operon.
    """
    por_locus = {f["locus_tag"]: f for f in filas if f["locus_tag"]}
    corridas, actual = [], []
    for locus in gff:
        if locus not in por_locus:
            continue
        simbolo = por_locus[locus]["simbolo"]
        hebra = gff[locus]["hebra"]
        if simbolo and MIEMBRO_OPERON.match(simbolo) and (
                not actual or actual[-1][2] == hebra):
            actual.append((locus, simbolo, hebra))
            continue
        if len(actual) >= 2:
            corridas.append(actual)
        actual = ([(locus, simbolo, hebra)]
                  if simbolo and MIEMBRO_OPERON.match(simbolo) else [])
    if len(actual) >= 2:
        corridas.append(actual)

    vistos, operones = set(), []
    for corrida in corridas:
        secuencia = corrida if corrida[0][2] == "+" else list(reversed(corrida))
        for i in range(len(secuencia)):
            for j in range(i + 2, len(secuencia) + 1):
                trozo = secuencia[i:j]
                nombre = nombre_de_operon([s for _, s, _ in trozo])
                if not nombre or nombre in vistos:
                    continue
                vistos.add(nombre)
                operones.append({
                    "operon": nombre,
                    "miembros": "|".join(s for _, s, _ in trozo),
                    "locus_tags": "|".join(l for l, _, _ in trozo),
                    "fuente": "refseq_adyacencia",
                })
    # Un nombre de operon que choque con el simbolo de un gen haria que esa
    # superficie resolviera a dos entidades y `Lexico` no emitiria mencion
    # (regla 4 de §1.2). Se descarta el operon, que es el derivado.
    simbolos = {f["simbolo"] for f in filas if f["simbolo"]}
    operones = [o for o in operones if o["operon"] not in simbolos]
    operones.sort(key=lambda o: o["operon"])
    return operones


def nombre_de_operon(simbolos):
    """`['mexA', 'mexB', 'oprM']` -> `'mexAB-oprM'`."""
    grupos = []
    for simbolo in simbolos:
        m = MIEMBRO_OPERON.match(simbolo)
        if not m:
            return ""
        prefijo, letra = m.group(1), m.group(2)
        if grupos and grupos[-1][0] == prefijo:
            grupos[-1][1].append(letra)
        else:
            grupos.append([prefijo, [letra]])
    return "-".join(p + "".join(letras) for p, letras in grupos)


# ------------------------------------------------------------------ CollecTF

def pmids_de_los_sitios(sitios):
    """Todos los PMIDs que citan los 532 sitios, tengan o no gen regulado.

    Se cuentan aparte de los PMIDs de los pares porque son dos cosas: un sitio
    sin `Evidence of regulation for:` es un sitio de union documentado que no
    declara blanco, asi que su articulo cuenta como bibliografia de CollecTF
    pero no sostiene ningun par.
    """
    pmids = set()
    for attrs in sitios:
        for m in re.finditer(r"\[PMID:\s*([0-9,\s]+)\]",
                             attrs.get("experiment", "")):
            for p in re.split(r"[,\s]+", m.group(1)):
                if p.isdigit():
                    pmids.add(int(p))
    return pmids


def construir_collectf(pares, pmids_en_corpus):
    filas = []
    for (tf, blanco), datos in pares.items():
        filas.append({
            "tf": tf,
            "blanco": blanco,
            "experimento": lista(datos["experimentos"]),
            "pmids": "|".join(str(p) for p in sorted(datos["pmids"])),
            "en_corpus": "true" if datos["pmids"] & pmids_en_corpus else "false",
        })
    filas.sort(key=lambda f: (f["tf"], f["blanco"]))
    return filas


def pmids_del_corpus(ruta_db, pmids):
    """Cuales de esos PMIDs ya estan en `documentos` de grn.db.

    Va por `grn_etl.db` y no por `sqlite3` a pelo: CLAUDE.md dice que solo
    `db.py` escribe SQL, y `pmids_conocidos()` ya existe justamente para esto.
    Si la base no esta no se crea una vacia -- `db.conectar()` lo haria -- : se
    avisa y `en_corpus` sale `false`.
    """
    if not os.path.exists(ruta_db):
        return set(), False
    con = basededatos.conectar(ruta_db)
    try:
        conocidos = basededatos.pmids_conocidos(con, [str(p) for p in pmids])
    finally:
        con.close()
    return {int(p) for p in conocidos if str(p).isdigit()}, True


# --------------------------------------------------------------- invariantes

def contar_ambiguas(filas):
    """Superficies que resuelven a dos entidades canonicas distintas.

    Se cuenta con la misma regla que `Lexico._registrar()`: la clave es la
    superficie tal cual si la fila es sensible a mayusculas, y en minusculas
    si no lo es.

    PUNTO CIEGO, y esta cubierto aparte: dos filas con el MISMO simbolo dan la
    misma identidad canonica (`simbolo or locus_tag`), asi que `previo != idc`
    no se cumple nunca y no se cuentan como ambiguas. No es un descuido de
    esta funcion --colapsan de verdad en una sola entidad, no en dos-- pero si
    es un dano que hay que publicar, y por eso existe `simbolos_repetidos()`,
    que mide con otra clave.
    """
    duenos, ambiguas = {}, set()
    for fila in filas:
        idc = fila["simbolo"] or fila["locus_tag"]
        sensible = fila["sensible_mayusculas"] == "true"
        for s in superficies_de(fila):
            clave = s if sensible else s.lower()
            previo = duenos.get(clave)
            if previo is not None and previo != idc:
                ambiguas.add(clave)
            else:
                duenos[clave] = idc
    return ambiguas


def simbolos_repetidos(filas):
    """{simbolo: [locus_tag, ...]} de los simbolos que dos genes comparten.

    `Lexico` usa `simbolo or locus_tag` como identidad canonica, asi que dos
    filas con el mismo simbolo colapsan en UNA entidad y una arista
    `X -> potA` acaba nombrando a tres genes a la vez. `contar_ambiguas()` no
    puede verlo porque usa esa misma expresion como clave: las dos filas dan
    la misma clave y `previo != idc` nunca es cierto. Es el mismo defecto que
    ordena todo este trabajo --el verificador que mide con la clave del objeto
    que verifica-- y por eso se cuenta aparte y con otra clave.

    No impide escribir: hoy son 13 simbolos repartidos entre 27 genes de
    RefSeq (`potA` en PA0326, PA0603 y PA3607; `aroE`, `nirD`, `lon`, `map`,
    `zwf`... por duplicado) y son asi en la fuente, no un defecto del parseo.
    Se publica para que quien lea una arista con uno de esos nombres sepa que
    el nombre no identifica un gen. Efecto medido dentro de `Lexico`:
    `_es_tf[idc]` se queda con la ultima fila del archivo, asi que `nirD`
    (PA0515 TF, PA1780 no) acaba en no-TF y `ercS` (PA1976 no, PA1992 TF)
    acaba en TF.
    """
    por_simbolo = collections.defaultdict(list)
    for fila in filas:
        if fila["simbolo"] and fila["locus_tag"]:
            por_simbolo[fila["simbolo"]].append(fila["locus_tag"])
    return {s: loci for s, loci in por_simbolo.items() if len(loci) > 1}


def sensibles_por_motivo(filas, palabras):
    """(por_longitud, solo_por_la_lista) de `sensible_mayusculas`.

    Existe para que no se pueda leer `palabras_comunes.txt` como una defensa
    activa sin comprobar si lo es. Medido sobre el diccionario versionado:
    181 filas sensibles, 181 por la clausula de longitud, **0 solo por la
    lista**, porque ninguna de las 1931 superficies alfabeticas de cuatro
    caracteres o mas del diccionario es una palabra inglesa: todas tienen la
    forma `mexA`. La lista se conserva porque el contrato la exige y porque
    documenta por que cada fila de tres letras salio sensible, pero el numero
    que este par publica es la unica forma de saber cuanto esta haciendo.
    """
    por_longitud, solo_lista = 0, 0
    for fila in filas:
        if fila["sensible_mayusculas"] != "true":
            continue
        superficies = {x.lower() for x in superficies_de(fila)}
        if any(len(x) <= 3 for x in superficies):
            por_longitud += 1
        elif superficies & palabras:
            solo_lista += 1
    return por_longitud, solo_lista


def tf_sin_forma_proteina(filas):
    """Los TF sensibles a mayusculas cuya forma de proteina no es superficie.

    `Lexico` no sintetiza la forma de proteina de una fila sensible --hacerlo
    reintroduciria el falso positivo que la sensibilidad evita-- asi que un
    gen de tres letras marcado TF cuyo alias `Rho`/`Ada` no este escrito en el
    diccionario es invisible cada vez que el articulo lo capitaliza, y no
    produce ni un candidato. No habia ningun conteo que lo mostrara: se
    descubrio a mano, gen por gen. Aqui se publica siempre, con nombre.

    No impide escribir: la reparacion es una fila de la capa manual por gen, y
    esa decision se toma midiendo el corpus (que este script no lee), no a
    ciegas. Ver `manual_pao1.tsv`.
    """
    sueltos = []
    for fila in filas:
        simbolo = fila["simbolo"]
        if fila["es_tf"] != "true" or fila["sensible_mayusculas"] != "true":
            continue
        if not simbolo:
            continue
        proteina = simbolo[:1].upper() + simbolo[1:]
        if proteina != simbolo and proteina not in superficies_de(fila):
            sueltos.append((fila["locus_tag"], simbolo, proteina))
    return sueltos


def invariantes(filas, manual, ambiguas):
    """Las condiciones de §2 que impiden escribir. Devuelve el mensaje o None."""
    for fila in filas:
        if "oro" in [t for t in fila["fuente"].split("|") if t]:
            return MSG_ORO
    if len(filas) < 5000 or len(filas) > 7000:
        return ("El diccionario tiene %d filas; PAO1 tiene del orden de 5700. "
                "Algo se rompio en el parseo del GFF." % len(filas))
    n_tf = sum(1 for f in filas if f["es_tf"] == "true")
    if not 300 <= n_tf <= 900:
        return ("Marque %d genes como TF; el orden esperado es 536. Revisa el "
                "criterio antes de escribir." % n_tf)
    vistos = set()
    for fila in filas:
        locus = fila["locus_tag"]
        if not locus:
            continue
        if locus in vistos:
            return "locus_tag %s duplicado." % locus
        vistos.add(locus)
        if not LOCUS.match(locus):
            return "locus_tag %s no casa con ^PA\\d{4}(\\.\\d)?$." % locus
    if len(manual) > 40:
        return "La capa manual tiene %d filas, el tope es 40." % len(manual)
    if len(ambiguas) > 50:
        return ("%d superficies resuelven a dos entidades distintas. Revisa "
                "los alias de uniprot_especie antes de escribir."
                % len(ambiguas))
    for fila in filas:
        etiqueta = fila["locus_tag"] or fila["simbolo"]
        if (fila["es_tf"] == "true") != bool(fila["fuente_tf"].strip()):
            return "Fila %s: es_tf y fuente_tf se contradicen." % etiqueta
        if fila["es_tf"] not in ("true", "false"):
            return "Fila %s: es_tf %r no es true ni false." % (etiqueta,
                                                               fila["es_tf"])
        if fila["tipo"] not in TIPOS_VALIDOS:
            return "Fila %s: tipo %r fuera del enum." % (etiqueta, fila["tipo"])
    return None


# --------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Construye el diccionario de genes de PAO1 (etapa 1).")
    ap.add_argument("--salida", default="etapa2/genes_pao1.tsv")
    ap.add_argument("--operones", default="etapa2/operones_pao1.tsv")
    ap.add_argument("--collectf", default="etapa2/collectf_pao1.tsv")
    ap.add_argument("--manual", default="etapa2/manual_pao1.tsv")
    ap.add_argument("--palabras", default=RUTA_PALABRAS)
    ap.add_argument("--db", default="datos/grn.db")
    ap.add_argument("--cache", default="datos_etapa2/cache_diccionario",
                    help="respuestas crudas: se guardan y se reutilizan si "
                         "casan con el sha256 de su manifiesto")
    ap.add_argument("--sin-red", action="store_true",
                    help="usa solo el cache; falla si falta cualquier respuesta")
    ap.add_argument("--refrescar-cache", action="store_true",
                    help="vuelve a pedir cada respuesta aunque este en el cache")
    ap.add_argument("--email", default=None,
                    help="correo de contacto que NCBI exige en cada peticion")
    args = ap.parse_args(argv)

    cache = Cache(args.cache, sin_red=args.sin_red,
                  refrescar=args.refrescar_cache)
    cliente = None
    if not args.sin_red:
        correo = credenciales.correo(args.email)
        if not correo:
            return ("NCBI exige un correo de contacto en cada peticion. Pasalo "
                    "con --email, exportalo en NCBI_EMAIL o escribelo en el "
                    "archivo .correo de la raiz del proyecto.")
        cliente = ClienteConCabeceras(correo, credenciales.llave())

    print("Fuentes...")
    texto_gff = gzip.decompress(
        cache.obtener("refseq_gff.gz", URL_GFF, cliente)).decode("utf-8",
                                                                 "replace")
    gff, sitios = analizar_gff(texto_gff)
    print("  RefSeq: %d genes, %d sitios de CollecTF" % (len(gff), len(sitios)))

    kegg = analizar_kegg(cache.obtener("kegg_pae.txt", URL_KEGG,
                                       cliente).decode("utf-8", "replace"))
    print("  KEGG: %d entradas" % len(kegg))

    filas_uni = analizar_uniprot(cache.paginas(
        "uniprot_proteoma", url_uniprot(CONSULTA_PROTEOMA), cliente))
    uni, _ = indexar_uniprot(filas_uni)
    print("  UniProt proteoma: %d entradas, %d locus tags de PAO1"
          % (len(filas_uni), len(uni)))

    filas_esp = analizar_uniprot(cache.paginas(
        "uniprot_especie", url_uniprot(CONSULTA_ESPECIE), cliente))
    esp, fuera = indexar_uniprot(filas_esp)
    print("  UniProt especie: %d entradas, %d locus tags de PAO1, %d "
          "descartadas por ser de otra cepa"
          % (len(filas_esp), len(esp), fuera))
    cache.cerrar()
    if not args.sin_red:
        print("  cache: %d respuestas reutilizadas, %d pedidas a la red"
              % (cache.aciertos, cache.descargas))

    # Se mide ANTES de construir nada: si las tres cargas no coinciden en como
    # se llaman los genes, lo que hay que revisar es de donde salieron, no el
    # diccionario que produzcan.
    sueltos = corroborar_simbolos(gff, kegg, uni, esp)
    print("  simbolos del GFF sin respaldo de KEGG ni de UniProt: %d de %d"
          % (len(sueltos), sum(1 for l, g in gff.items()
                               if LOCUS.match(l) and g["simbolo"])))
    if len(sueltos) > LIMITE_SIN_CORROBORAR:
        return MSG_SIN_CORROBORAR % (
            len(sueltos), LIMITE_SIN_CORROBORAR,
            "\n  ".join("%s = %s" % par for par in sueltos[:10]))

    manual = leer_manual(args.manual)
    palabras = leer_palabras_comunes(args.palabras)
    pares_collectf, moieties = analizar_sitios(sitios)

    filas, indices, quitados = construir_genes(gff, kegg, uni, esp, manual,
                                               palabras, moieties)

    problemas = verificar_procedencia(filas, indices, gff, uni, esp, moieties,
                                      manual)
    if "oro" in problemas:
        return MSG_ORO
    if problemas:
        return ("La procedencia de %d filas no cuadra con las respuestas "
                "crudas. Las tres primeras:\n  %s"
                % (len(problemas), "\n  ".join(problemas[:3])))

    ambiguas = contar_ambiguas(filas)
    fallo = invariantes(filas, manual, ambiguas)
    if fallo:
        return fallo

    operones = derivar_operones(filas, gff)
    pmids = {p for datos in pares_collectf.values() for p in datos["pmids"]}
    pmids_sitios = pmids | pmids_de_los_sitios(sitios)
    en_corpus, hay_db = pmids_del_corpus(args.db, pmids)
    if not hay_db:
        print("Aviso: %s no existe; en_corpus sale 'false' en todo CollecTF."
              % args.db)
    collectf = construir_collectf(pares_collectf, en_corpus)

    escribir_tsv(args.salida, COLUMNAS_GENES, filas)
    escribir_tsv(args.operones, COLUMNAS_OPERONES, operones)
    escribir_tsv(args.collectf, COLUMNAS_COLLECTF, collectf)
    for ruta in (args.salida, args.operones, args.collectf):
        os.replace(ruta + ".tmp", ruta)

    n_tf = sum(1 for f in filas if f["es_tf"] == "true")
    con_simbolo = sum(1 for f in filas if f["simbolo"])
    solo_producto = sum(1 for f in filas if f["fuente_tf"] == "producto_refseq")
    print("\nDiccionario: %d filas, %d con simbolo, %d marcadas como TF"
          % (len(filas), con_simbolo, n_tf))
    print("  %d de esas marcas se sostienen solo en el producto de RefSeq, que "
          "es reconocimiento por patron" % solo_producto)
    print("  superficies ambiguas (no se emite mencion para ellas): %d"
          % len(ambiguas))
    print("  alias descartados: %d por forma, %d por chocar con el simbolo de "
          "otro gen" % (quitados["forma"], quitados["choca_con_un_simbolo"]))
    por_longitud, solo_lista = sensibles_por_motivo(filas, palabras)
    print("  filas sensibles a mayusculas: %d por tener una superficie de tres "
          "caracteres o menos, %d solo por palabras_comunes.txt"
          % (por_longitud, solo_lista))
    sin_proteina = tf_sin_forma_proteina(filas)
    if sin_proteina:
        print("  %d filas marcadas TF son sensibles y no traen su forma de "
              "proteina como superficie, asi que el corpus las escribe de una "
              "forma que Lexico no vera: %s"
              % (len(sin_proteina),
                 ", ".join("%s (%s)" % (p, l) for l, _, p in sin_proteina)))
    repetidos = simbolos_repetidos(filas)
    if repetidos:
        print("  %d simbolos los comparten %d genes distintos y colapsan en "
              "una sola entidad canonica: %s"
              % (len(repetidos), sum(len(v) for v in repetidos.values()),
                 ", ".join("%s=%s" % (s, "/".join(v))
                           for s, v in sorted(repetidos.items())[:5])))
    print("Operones: %d, derivados por adyacencia de locus tags" % len(operones))
    print("CollecTF: %d pares, %d TFs, %d PMIDs en los sitios (%d en los "
          "pares), %d de esos ya en el corpus"
          % (len(collectf), len(moieties), len(pmids_sitios), len(pmids),
             len(en_corpus)))
    print("\nNingun campo de este diccionario dice 'esto es un TF' con "
          "autoridad: ver el docstring de este script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
