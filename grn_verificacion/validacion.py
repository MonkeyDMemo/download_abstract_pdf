"""Lectura de la base curada del laboratorio, por ruta y sin dependencias.

La base curada es un .xlsx confidencial que vive en el servidor del asesor.
Este módulo no sabe cómo se llama ni dónde está: la ruta llega siempre como
argumento, y `etapa2/test_contaminacion.py` impide teclear su nombre o su
carpeta en el código. Devuelve interacciones normalizadas, que se quedan en la
memoria del proceso, y conteos, que son lo único que puede salir de esa
máquina: números y categorías del esquema, jamás un gen, un locus o un PMID.

El esquema y sus rarezas se midieron el 10-sep-2026 (PLAN.md, sección 2.4):
ocho columnas; `Interaction` solo codifica el signo (`+`, `-`, `Unknown`,
vacío, `d`, un `+, +` y tres celdas con un locus corrido); `Reference` trae
PMIDs que hay que normalizar (flotantes con `.0`, listas, una etiqueta pegada,
PMIDs de 7 dígitos, un DOI), y dos variantes de su etiqueta dicen «homology».

Por qué biblioteca estándar y no openpyxl
-----------------------------------------
Esto corre en el servidor del asesor con el Python del entorno conda
`pseudoRE`, que es suyo y donde no se instala nada. Con openpyxl, el lector
funcionaría o no según lo que otra persona haya instalado en un entorno ajeno,
justo en la única máquina donde vive la base. Además `grn_verificacion` es
núcleo del proyecto: biblioteca estándar y Python 3.8 (CLAUDE.md). Un .xlsx es
un zip de XML, y leer valores (sin estilos, fórmulas evaluadas ni fechas) cabe
en un centenar de líneas de `zipfile` y `xml.etree`.
"""

import decimal
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

# La misma forma de locus tag que `etapa2/extraer_pares.py` y `lexico.py`,
# para que un locus de la base y uno del diccionario se comparen igual. El
# sufijo `.1` existe en PAO1 (genes partidos en la anotación).
LOCUS = re.compile(r"^PA[0-9]{4}(\.[0-9])?$")

# Las columnas que se leen. Las otras tres (`Source`, `Target`,
# `Contributions`) no se piden a propósito: los nombres de gen no hacen falta
# porque se compara por locus, y lo que no se lee no se puede filtrar a ningún
# lado. Exigirlas haría fallar la lectura si alguien las renombra, sin ganar
# nada.
COLUMNAS_USADAS = ("Interaction", "Reference", "Source_Locus_id",
                   "Target_Locus_id", "Origen")

# `origen` se guarda como identificador ASCII; la etiqueta con acento es para
# el humano que lee el resumen. «otro» junta cualquier valor que no sea uno de
# los tres medidos, para que un valor inesperado se cuente sin copiarse.
ORIGENES = ("historica", "biobert", "ambos", "otro")
ETIQUETA_ORIGEN = {"historica": "Histórica", "biobert": "BioBERT",
                   "ambos": "Ambos", "otro": "otro"}

SIGNOS = ("+", "-", "?", "d")

_TIPO_DOCUMENTO = "/officeDocument"
_TIPO_HOJA = "/worksheet"
_TIPO_CADENAS = "/sharedStrings"

# Excel escapa los caracteres de control como `_xHHHH_` (un retorno de carro
# llega como `_x000D_`). Sin deshacerlo, `12345678_x000D_` partía en dígitos
# sueltos y el PMID se perdía.
_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")

_DOI = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?\b10\.[0-9]{4,9}/[^\s,;]+", re.I)
_CIENTIFICA = re.compile(r"^[0-9]+(?:\.[0-9]+)?[eE]\+?[0-9]+$")
_DECIMAL_CERO = re.compile(r"^[0-9]+\.0+$")
_DIGITOS = re.compile(r"[0-9]+")
_SEPARADOR = re.compile(r"[,;\s]+")
_SIGNO_PARTES = re.compile(r"[,;]")
# Guiones que un procesador de texto pone en lugar del menos.
_MENOS = (u"−", u"–", u"—")


# ---------------------------------------------------------------- el .xlsx

def _local(etiqueta):
    """El nombre sin espacio de nombres: `{...}row` -> `row`.

    Se compara por nombre local porque hay dos espacios de nombres para lo
    mismo (el transicional de Excel y el estricto de ISO 29500), y un archivo
    guardado en modo estricto no debe leerse como vacío.
    """
    return etiqueta.rsplit("}", 1)[-1]


def _xml(libro, nombre):
    try:
        datos = libro.read(nombre)
    except KeyError:
        return None
    try:
        return ET.fromstring(datos)
    except ET.ParseError:
        raise ValueError("La parte %s del .xlsx no es XML válido: el archivo "
                         "está dañado." % nombre)


def _relaciones(libro, parte):
    """{Id: (tipo, ruta dentro del zip)} de las relaciones de `parte`.

    La parte raíz del paquete es "", cuyas relaciones viven en `_rels/.rels`.
    """
    carpeta, archivo = posixpath.split(parte)
    raiz = _xml(libro, posixpath.join(carpeta, "_rels", archivo + ".rels"))
    salida = {}
    if raiz is None:
        return salida
    for rel in raiz:
        if (_local(rel.tag) != "Relationship"
                or rel.get("TargetMode") == "External"):
            continue
        destino = rel.get("Target") or ""
        if destino.startswith("/"):
            ruta = destino.lstrip("/")
        else:
            ruta = posixpath.normpath(posixpath.join(carpeta, destino))
        salida[rel.get("Id")] = (rel.get("Type") or "", ruta)
    return salida


def _desescapar(texto):
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), texto)


def _texto_rico(elemento):
    """El texto de un `<si>` o un `<is>`: `<t>` directo o corridas `<r><t>`.

    La guía fonética (`<rPh>`) se salta: es la lectura de un texto japonés
    escrita encima, no parte del valor de la celda.
    """
    partes = []
    for hijo in elemento:
        nombre = _local(hijo.tag)
        if nombre == "t":
            partes.append(hijo.text or "")
        elif nombre == "r":
            for nieto in hijo:
                if _local(nieto.tag) == "t":
                    partes.append(nieto.text or "")
    return _desescapar("".join(partes))


def _cadenas(libro, rels):
    ruta = "xl/sharedStrings.xml"
    for tipo, destino in rels.values():
        if tipo.endswith(_TIPO_CADENAS):
            ruta = destino
    raiz = _xml(libro, ruta)
    if raiz is None:
        return []
    return [_texto_rico(si) for si in raiz if _local(si.tag) == "si"]


def _hojas(libro):
    """([(nombre, ruta)] de las hojas de cálculo en el orden del libro, rels).

    El orden sale de `workbook.xml` y la ruta de sus relaciones, no del nombre
    del archivo: Excel numera `sheetN.xml` en el orden en que se crearon las
    hojas, no en el que se ven, así que la primera hoja visible puede vivir en
    `sheet3.xml`.
    """
    parte = "xl/workbook.xml"
    for tipo, destino in _relaciones(libro, "").values():
        if tipo.endswith(_TIPO_DOCUMENTO):
            parte = destino
    raiz = _xml(libro, parte)
    if raiz is None:
        raise ValueError("El archivo no trae libro de cálculo: no es un .xlsx.")
    rels = _relaciones(libro, parte)
    hojas = []
    for elemento in raiz.iter():
        if _local(elemento.tag) != "sheet":
            continue
        rid = None
        for llave, valor in elemento.attrib.items():
            if llave.startswith("{") and _local(llave) == "id":
                rid = valor
        tipo, ruta = rels.get(rid, ("", None))
        # Una hoja de gráfico ocupa lugar en la lista pero no tiene celdas.
        if ruta and tipo.endswith(_TIPO_HOJA):
            hojas.append((elemento.get("name") or "", ruta))
    return hojas, rels


def _elegir_hoja(hojas, hoja):
    if hoja is None:
        return hojas[0][1]
    if isinstance(hoja, int) and not isinstance(hoja, bool):
        if 0 <= hoja < len(hojas):
            return hojas[hoja][1]
        raise ValueError("El libro tiene %d hojas de cálculo; no hay una en la "
                         "posición %d." % (len(hojas), hoja))
    for nombre, ruta in hojas:
        if nombre == hoja:
            return ruta
    raise ValueError("El libro no tiene una hoja llamada %r (tiene %d)."
                     % (hoja, len(hojas)))


def _entero(texto, defecto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return defecto


def _columna(referencia):
    """`AB12` -> 27, indexada desde 0. -1 si la referencia no trae letras."""
    n = 0
    for ch in referencia.upper():
        if "A" <= ch <= "Z":
            n = n * 26 + ord(ch) - 64
        else:
            break
    return n - 1


def _valor(celda, cadenas):
    """El valor de una celda como texto crudo."""
    tipo = celda.get("t") or "n"
    v, en_linea = None, None
    for hijo in celda:
        nombre = _local(hijo.tag)
        if nombre == "v":
            v = hijo.text or ""
        elif nombre == "is":
            en_linea = hijo
    if tipo == "s":
        if v is None or not v.strip():
            return ""
        i = _entero(v.strip(), -1)
        # El mensaje no repite el valor: aunque aquí sea un índice, la regla
        # es que nada de la base viaje en un error.
        if not 0 <= i < len(cadenas):
            raise ValueError("Una celda apunta a una cadena compartida que no "
                             "existe: el .xlsx está dañado.")
        return cadenas[i]
    if tipo == "inlineStr":
        if en_linea is not None:
            return _texto_rico(en_linea)
        return _desescapar(v or "")
    if tipo == "b":
        if v is None:
            return ""
        return "TRUE" if v.strip() == "1" else "FALSE"
    # n (número), str (resultado de fórmula), e (error), d (fecha ISO): el
    # texto tal cual lo guardó el programa que escribió el archivo.
    return _desescapar(v) if v is not None else ""


def _filas(raiz, cadenas):
    datos = None
    for elemento in raiz.iter():
        if _local(elemento.tag) == "sheetData":
            datos = elemento
            break
    if datos is None:
        return []
    filas, previo = [], 0
    for fila in datos:
        if _local(fila.tag) != "row":
            continue
        # Sin atributo `r`, la fila es la siguiente de la anterior (así lo
        # escriben algunos generadores que no son Excel).
        numero = _entero(fila.get("r"), previo + 1)
        previo = numero
        valores, columna = [], -1
        for celda in fila:
            if _local(celda.tag) != "c":
                continue
            col = _columna(celda.get("r") or "")
            columna = col if col >= 0 else columna + 1
            if columna >= len(valores):
                valores.extend([""] * (columna + 1 - len(valores)))
            valores[columna] = _valor(celda, cadenas)
        filas.append((numero, valores))
    return filas


def leer_xlsx(ruta, hoja=None):
    """(encabezados, filas) de una hoja de un .xlsx.

    `hoja` es el nombre de la hoja, su posición entre las hojas de cálculo
    (desde 0) o None para la primera en el orden del libro.

    `encabezados` es la primera fila con algún valor. `filas` es una lista de
    `(numero, valores)` con las filas que siguen: el número de fila de Excel,
    para poder señalar una fila sin copiar su contenido, y los valores como
    texto crudo. Los números se dejan como los escribió el programa que guardó
    el archivo («12345678», «12345678.0», «1.2345678E7»): normalizarlos es
    trabajo de quien sabe qué hay en esa columna. Una celda que falta, porque
    la fila tiene huecos, sale como "".

    Las filas que Excel omite por vacías no aparecen; las que trae vacías sí,
    y quien las consume decide qué hacer con ellas.
    """
    try:
        libro = zipfile.ZipFile(ruta)
    except zipfile.BadZipFile:
        # Sin la ruta: la CLI imprime este mensaje tal cual, y la ruta de
        # --base dice dónde vive la base curada en el servidor.
        raise ValueError("El archivo de --base no es un .xlsx legible: no es "
                         "un archivo zip.")
    with libro:
        hojas, rels = _hojas(libro)
        if not hojas:
            raise ValueError("El libro no tiene hojas de cálculo.")
        parte_hoja = _elegir_hoja(hojas, hoja)
        cadenas = _cadenas(libro, rels)
        raiz = _xml(libro, parte_hoja)
        if raiz is None:
            raise ValueError("El libro declara una hoja que no está dentro del "
                             "archivo: el .xlsx está dañado.")
        filas = _filas(raiz, cadenas)

    encabezados, datos = None, []
    for numero, valores in filas:
        if encabezados is None:
            if any(v.strip() for v in valores):
                encabezados = valores
            continue
        datos.append((numero, valores))
    return (encabezados or []), datos


# ------------------------------------------------------- la normalización

def _sin_acentos(texto):
    return "".join(ch for ch in unicodedata.normalize("NFKD", texto)
                   if not unicodedata.combining(ch))


def _entero_de_cientifica(token):
    try:
        valor = decimal.Decimal(token)
    except decimal.InvalidOperation:
        return []
    if valor != valor.to_integral_value():
        return []
    return [str(int(valor))]


def pmids_de(referencia):
    """(pmids, dois, descartados) de una celda de `Reference`.

    `pmids` son cadenas de 7 u 8 dígitos, sin repetir y en el orden en que
    aparecen. Lo que se normaliza, y por qué:

    - un flotante con `.0` («12345678.0») o en notación científica
      («1.2345678E7»), que es como queda un PMID cuando la columna pasó por un
      tipo numérico;
    - listas separadas por coma, punto y coma o espacio;
    - una etiqueta pegada al número («12345678homology», «PMID:12345678»): se
      toman las corridas de dígitos del fragmento;
    - PMIDs de 7 dígitos, que son legítimos (artículos anteriores a 1990).

    Los DOIs se quitan antes de buscar dígitos y se cuentan en `dois`: sus
    números no son PMIDs y no hay con qué traducirlos sin salir a la red. En
    `descartados` caen las corridas de 5 o más dígitos que no tienen largo de
    PMID, que suelen ser PMIDs truncados; las cortas («PA14», un año) no se
    cuentan porque no lo son.
    """
    texto = referencia or ""
    dois = len(_DOI.findall(texto))
    texto = _DOI.sub(" ", texto)
    pmids, descartados = [], 0
    for token in _SEPARADOR.split(texto):
        if not token:
            continue
        # La notación científica va antes que las corridas de dígitos: leída
        # como corridas, «1.2345678E7» daría «2345678», un PMID de 7 dígitos
        # que nadie escribió.
        if _CIENTIFICA.match(token):
            candidatos = _entero_de_cientifica(token)
        elif _DECIMAL_CERO.match(token):
            candidatos = [token.split(".", 1)[0]]
        else:
            candidatos = _DIGITOS.findall(token)
        for candidato in candidatos:
            candidato = candidato.lstrip("0")
            if 7 <= len(candidato) <= 8:
                if candidato not in pmids:
                    pmids.append(candidato)
            elif len(candidato) >= 5:
                descartados += 1
    return pmids, dois, descartados


def signo_de(celda):
    """(signo, motivo) de una celda de `Interaction`.

    `+` y `+, +` -> '+'; `-` -> '-'; `Unknown` y vacío -> '?'; `d` se conserva
    tal cual porque nadie ha dicho qué significa (PLAN.md, pregunta 3) y el
    constructor de ejemplos lo excluye. Si la celda trae un locus (la fila
    está corrida) o cualquier otra cosa, el signo es None y `motivo` dice por
    qué: 'locus_corrido' o 'no_reconocido'.
    """
    texto = (celda or "").strip()
    if LOCUS.match(texto.upper()):
        return None, "locus_corrido"
    if not texto or texto.lower() == "unknown":
        return "?", None
    for menos in _MENOS:
        texto = texto.replace(menos, "-")
    partes = [p.strip() for p in _SIGNO_PARTES.split(texto) if p.strip()]
    if partes and all(p == "+" for p in partes):
        return "+", None
    if partes and all(p == "-" for p in partes):
        return "-", None
    if texto.lower() == "d":
        return "d", None
    return None, "no_reconocido"


def origen_de(celda):
    """'historica', 'biobert', 'ambos' u 'otro'; sin acentos ni mayúsculas."""
    texto = _sin_acentos((celda or "").strip().lower())
    return texto if texto in ("historica", "biobert", "ambos") else "otro"


def _indice_columnas(encabezados):
    indice = {}
    for i, nombre in enumerate(encabezados):
        clave = (nombre or "").strip().lower()
        if clave and clave not in indice:
            indice[clave] = i
    faltan = [c for c in COLUMNAS_USADAS if c.lower() not in indice]
    if faltan:
        raise ValueError(
            "A la base le faltan las columnas %s. Se esperan %s en la primera "
            "fila con valores." % (", ".join(faltan), ", ".join(COLUMNAS_USADAS)))
    return indice


def _celda(valores, indice, columna):
    i = indice[columna.lower()]
    return valores[i] if i < len(valores) else ""


def conteos_vacios():
    return {
        "filas": 0,
        "filas_vacias": 0,
        "interacciones": 0,
        "locus_invalido": 0,
        "signo": {"+": 0, "-": 0, "?": 0, "d": 0, "ilegible": 0},
        "signo_locus_corrido": 0,
        "origen": dict((o, 0) for o in ORIGENES),
        "homologia": 0,
        "menciones_pmid": 0,
        "pmids_distintos": 0,
        "filas_sin_pmid": 0,
        "dois_descartados": 0,
        "numeros_descartados": 0,
    }


def normalizar(encabezados, filas):
    """(interacciones, conteos) a partir de lo que devuelve `leer_xlsx`.

    Cada interacción es un dict:

    - `fila_origen`: el número de fila de Excel, para rastrearla en el
      servidor sin copiarla;
    - `regulador`, `blanco`: locus PA#### (de `Source_Locus_id` y
      `Target_Locus_id`);
    - `signo`: '+', '-', '?', 'd', o None si la celda no se pudo leer (traía
      un locus corrido u otra cosa). Esas filas se conservan porque sus dos
      locus sí son válidos: no pueden dar positivos, pero el par sigue siendo
      curado, y quien arme negativos tiene que verlo;
    - `pmids`: lista de cadenas, ver `pmids_de()`;
    - `origen`: 'historica', 'biobert', 'ambos' u 'otro';
    - `homologia`: True si `Reference` dice «homolog». El artículo citado no
      reporta la relación (cobertura de 0.3 % con la regla b de PLAN.md 2.4).

    Una fila cuyo regulador o blanco no tiene forma de locus se cuenta en
    `locus_invalido` y se descarta: sin locus no se puede comparar con nada.

    Los conteos por signo, origen, homología y PMIDs son sobre todas las filas
    con algún valor, para poder ponerlos al lado de los de PLAN.md 2.4;
    `interacciones` es lo que sobrevive. Ningún conteo lleva contenido.
    """
    indice = _indice_columnas(encabezados)
    c = conteos_vacios()
    interacciones = []
    pmids_vistos = set()
    for numero, valores in filas:
        if not any((v or "").strip() for v in valores):
            c["filas_vacias"] += 1
            continue
        c["filas"] += 1

        signo, motivo = signo_de(_celda(valores, indice, "Interaction"))
        if signo is None:
            c["signo"]["ilegible"] += 1
            if motivo == "locus_corrido":
                c["signo_locus_corrido"] += 1
        else:
            c["signo"][signo] += 1

        origen = origen_de(_celda(valores, indice, "Origen"))
        c["origen"][origen] += 1

        referencia = _celda(valores, indice, "Reference")
        homologia = "homolog" in referencia.lower()
        if homologia:
            c["homologia"] += 1
        pmids, dois, descartados = pmids_de(referencia)
        c["dois_descartados"] += dois
        c["numeros_descartados"] += descartados
        c["menciones_pmid"] += len(pmids)
        pmids_vistos.update(pmids)
        if not pmids:
            c["filas_sin_pmid"] += 1

        regulador = _celda(valores, indice, "Source_Locus_id").strip().upper()
        blanco = _celda(valores, indice, "Target_Locus_id").strip().upper()
        if not (LOCUS.match(regulador) and LOCUS.match(blanco)):
            c["locus_invalido"] += 1
            continue

        interacciones.append({
            "fila_origen": numero,
            "regulador": regulador,
            "blanco": blanco,
            "signo": signo,
            "pmids": pmids,
            "origen": origen,
            "homologia": homologia,
        })
    c["pmids_distintos"] = len(pmids_vistos)
    c["interacciones"] = len(interacciones)
    return interacciones, c


def leer_base(ruta, hoja=None):
    """`leer_xlsx` más `normalizar`: (interacciones, conteos)."""
    encabezados, filas = leer_xlsx(ruta, hoja)
    return normalizar(encabezados, filas)
