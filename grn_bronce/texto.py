# -*- coding: utf-8 -*-
"""Segmentacion y pretokenizacion del corpus. Modulo compartido, seccion 1.1
del contrato de datos.

Existe para que haya UNA sola forma de partir un texto en oraciones. Si cada
etapa escribiera la suya, `evaluar_signo.py` no podria unir sus predicciones
con las 93 oraciones de la auditoria y la exactitud de signo mediria otra
cosa sin que nada fallara.

Cuatro piezas:

- `secciones()` corta el markdown por encabezados y clasifica cada bloque.
- `oraciones()` parte un cuerpo en oraciones. La logica es la de
  `auditar_signo.py:118-130`, conservada tal cual a proposito.
- `pretokenizar()` imita la pretokenizacion estilo Penn Treebank del corpus de
  entrenamiento, que es la diferencia sistematica mas grande entre nuestro
  texto (JATS limpio) y el suyo.
- `marcar()` inserta `<e1>` y `<e2>` con el espaciado exacto del
  entrenamiento.

Solo biblioteca estandar.
"""

import bisect
import os
import re

# Ruta por omision de la tabla de clases de seccion. Se lee una vez y se
# guarda en memoria: `secciones()` se llama 918 veces y abrir el archivo cada
# vez seria un sinsentido.
RUTA_SECCIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "secciones.tsv")

_CACHE_SECCIONES = {}

# Clase que se asigna a una etiqueta h2 que no aparece en secciones.tsv, y al
# texto que va antes del primer h2 (tipicamente el titulo y algun parrafo
# suelto que el extractor de JATS no supo colocar).
CLASE_DESCONOCIDA = "otra"

CLASES_VALIDAS = frozenset([
    "abstract", "introduction", "results", "discussion",
    "results_and_discussion", "background", "conclusion",
    "pie_de_figura", "excluir", CLASE_DESCONOCIDA,
])

# Solo los h2 abren seccion. `^##` seguido de otro `#` no casa, asi que un
# `### MEXT REGULATES MEXEF-OPRN` pertenece a la seccion h2 abierta y no
# fabrica una seccion nueva.
_H2 = re.compile(r"(?m)^##[ \t]+(.+?)[ \t]*$")

# Cualquier encabezado, de h1 a h6. Se borra del cuerpo.
#
# **El texto del encabezado se descarta, no se pega a la primera oracion.**
# Medido: `"## INTRODUCTION In the United States, pneumonia is..."` de 845
# caracteres. Con reconocimiento insensible a mayusculas, un
# `### MEXT REGULATES MEXEF-OPRN` producia menciones validas de `mexT` y
# `mexEF-oprN`, y la "oracion de evidencia" que se le pasaba al modelo era un
# titulo de subseccion.
_ENCABEZADO = re.compile(r"(?m)^#{1,6}[ \t]+.*$")

# Numeracion inicial del tipo "3.", "3.1", "3.1.2." de las etiquetas h2.
_NUMERACION = re.compile(r"^\s*\d+(\.\d+)*\.?\s*")

# Abreviaturas cuyo punto no termina oracion. Ancladas con `$` porque lo que
# se mira es el final del acumulado, no cualquier posicion.
ABREV = re.compile(
    r"\b(et al|e\.g|i\.e|vs|cf|Fig|Figs|Tab|approx|ca|no|No|spp|sp|"
    r"subsp|str|var|Dr|Prof|St|Inc|Ltd|min|sec|hr|h|mL|mg|kb|bp)\.$")

# Inicial suelta: "P." de "P. aeruginosa", "E." de "E. coli".
#
# **Esta guarda no es opcional.** Medido sobre 60 textos completos: dispara en
# el 15.9 % de los cortes crudos, y `P.` sola son 2110 de esas veces. Sin
# ella, una de cada seis oraciones del corpus se parte en medio de
# `P. aeruginosa`, justo donde suele estar el sujeto de la frase regulatoria.
_INICIAL = re.compile(r"\b[A-Z]\.$")

# Puntuacion que el entrenamiento separa con espacios. El guion va al final de
# la clase para que se lea como literal y no como rango.
#
# Medido en los tres .jsonl del asesor: `,` precedida de espacio 4309 veces
# contra 21 pegada; `.` separada 2187 contra 133; `(` y `)` separados 1846
# veces cada uno; y los guiones tambien (`MalE - SoxS`, `two - component`).
_PUNTUACION = re.compile(r"([.,;:?!()\[\]{}\"'/%=<>-])")

# Tramos que se copian verbatim aunque lleven puntuacion dentro. No es una
# excepcion cosmetica: era la unica familia de diferencias sistematicas que
# quedaba entre el texto que generamos y el que el modelo vio.
#
# Sintoma medido byte a byte, no leyendo codigo: se despojaron de sus
# marcadores las 1249 filas de `para_colab/entity_marked_train.jsonl` --texto
# que YA viene pretokenizado por el extractor del asesor-- y se volvieron a
# pasar por `pretokenizar()`. Con la regla anterior 96 de 1249 (7.7 %) salian
# distintas, y todas por dos causas: el numero partido (`46.5` -> `46 . 5`,
# `1,000` -> `1 , 000`, el DOI `10.1042` -> `10 . 1042`) y la entidad HTML
# partida (`&amp;` -> `&amp ;`). El entrenamiento no parte ninguna de las dos
# ni una sola vez, en ninguno de los tres archivos.
#
# En el corpus real eso tocaba el 4.7 % de las oraciones candidatas, y no un
# 4.7 % cualquiera: los decimales estan en RESULTS y en los pies de figura,
# que es justo donde se reportan los cambios de expresion. `P < 0 . 05` y
# `2 . 5 - fold` son piezas de wordpiece que el modelo no vio nunca, asi que
# su probabilidad es ruido con aspecto de resultado, y entra igual al voto de
# `red.py`.
#
# El punto y la coma se protegen SOLO entre digitos. Un punto final tras
# cifra ("was 5.") se sigue separando: ahi si termina la oracion, y el
# entrenamiento tambien lo separa.
_INTACTOS = re.compile(r"\d+(?:[.,]\d+)+|&(?:[A-Za-z]+|#\d+);")


def normalizar_espacios(s):
    """Colapsa todo blanco a un espacio y recorta los extremos."""
    return " ".join(s.split())


def normalizar_espacios_con_mapa(s):
    """Lo mismo que `normalizar_espacios()`, mas como deshacerlo.

    Devuelve `(texto, inverso)`, donde `inverso[i]` es la posicion en `s` del
    caracter i-esimo de `texto`. Hace falta porque el reconocimiento de
    menciones trabaja sobre la oracion YA normalizada, asi que sus offsets
    estan en unas coordenadas que no existen en el documento.

    Es el bucle de `pretokenizar()` con la direccion al reves. Alli el mapa va
    de bruto a limpio, porque lo que se traduce son tramos que el llamador ya
    tenia; aqui va de limpio a bruto, porque lo que se traduce son menciones
    que aparecieron despues. Se colapsa a mano en vez de con `str.split()` por
    el mismo motivo de siempre: un mapa de posiciones no puede desalinearse, y
    recalcular las menciones sobre el texto transformado si.
    """
    salida, inverso = [], []
    i, n = 0, len(s)
    while i < n:
        if s[i].isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            # Ni espacio inicial ni final, igual que `" ".join(s.split())`.
            if salida and j < n:
                salida.append(" ")
                inverso.append(i)
            i = j
        else:
            inverso.append(i)
            salida.append(s[i])
            i += 1
    return "".join(salida), inverso


def desnormalizar_span(inverso, ini, fin):
    """Span sobre el texto normalizado -> span sobre el texto original.

    Se traduce el ULTIMO caracter incluido y se le suma uno, nunca `fin`
    directo: `fin` es exclusivo y puede caer sobre un blanco que se colapso o
    fuera del texto, y en los dos casos el mapa no lo conoce. Es el mismo
    cuidado que ya toma `pretokenizar()` en su linea de spans.
    """
    return inverso[ini], inverso[fin - 1] + 1


def normalizar_etiqueta(bruta):
    """Etiqueta h2 -> forma canonica en minusculas.

    Quitar numeracion inicial, quitar punto final, colapsar espacios, pasar a
    minusculas. En ese orden.
    """
    e = _NUMERACION.sub("", bruta)
    e = e.strip()
    if e.endswith("."):
        e = e[:-1]
    return normalizar_espacios(e).lower()


def cargar_clases(ruta=None):
    """Lee secciones.tsv y devuelve {etiqueta normalizada: clase}."""
    ruta = ruta or RUTA_SECCIONES
    clave = os.path.abspath(ruta)
    if clave in _CACHE_SECCIONES:
        return _CACHE_SECCIONES[clave]
    mapa = {}
    with open(ruta, encoding="utf-8") as f:
        cabecera = f.readline().rstrip("\n").split("\t")
        if cabecera[:2] != ["etiqueta", "clase"]:
            raise ValueError(
                "%s no tiene el encabezado esperado 'etiqueta\\tclase'." % ruta)
        for linea in f:
            linea = linea.rstrip("\n")
            if not linea.strip():
                continue
            partes = linea.split("\t")
            if len(partes) < 2:
                continue
            etiqueta, clase = partes[0].strip().lower(), partes[1].strip()
            if clase not in CLASES_VALIDAS:
                raise ValueError(
                    "%s: la clase %r de la etiqueta %r no esta en el enum del "
                    "contrato." % (ruta, clase, etiqueta))
            mapa[etiqueta] = clase
    _CACHE_SECCIONES[clave] = mapa
    return mapa


def bloques(texto_markdown):
    """[(etiqueta normalizada, cuerpo)] en orden de aparicion.

    Devuelve la etiqueta CRUDA ya normalizada, no la clase. Existe porque el
    informe de la etapa 2 tiene que decir que etiquetas h2 desconocidas
    aparecieron y cuanto texto se llevaron, y `secciones()` ya perdio ese dato
    al traducirlo a una clase.

    El texto anterior al primer `##` sale con etiqueta vacia.
    """
    return [(etiqueta, cuerpo)
            for etiqueta, cuerpo, _tramos in bloques_con_offset(texto_markdown)]


def bloques_con_offset(texto_markdown):
    """[(etiqueta, cuerpo, tramos)], con los tramos de `traducir_span()`.

    Igual que `bloques()` -- de hecho esa funcion es un envoltorio de esta --
    pero conservando como volver de una posicion del cuerpo limpio a una del
    markdown original. Es lo que permite subrayar la evidencia sobre el
    documento entero y no sobre un bloque suelto.

    El offset de arranque de cada cuerpo sale gratis: es `m.end()` del h2 que
    lo abre. Lo que hay que arrastrar es lo otro, que `_limpiar_cuerpo()`
    borra los encabezados internos y no conserva los largos.
    """
    marcas = [(m.start(), m.end(), normalizar_etiqueta(m.group(1)))
              for m in _H2.finditer(texto_markdown)]
    salida = []
    if not marcas:
        cuerpo, tramos = _limpiar_cuerpo_con_mapa(texto_markdown, 0)
        return [("", cuerpo, tramos)]
    if marcas[0][0] > 0:
        cuerpo, tramos = _limpiar_cuerpo_con_mapa(
            texto_markdown[:marcas[0][0]], 0)
        salida.append(("", cuerpo, tramos))
    for i, (ini, fin, etiqueta) in enumerate(marcas):
        corte = marcas[i + 1][0] if i + 1 < len(marcas) else len(texto_markdown)
        cuerpo, tramos = _limpiar_cuerpo_con_mapa(
            texto_markdown[fin:corte], fin)
        salida.append((etiqueta, cuerpo, tramos))
    return salida


def _limpiar_cuerpo(cuerpo):
    """Quita los encabezados que hayan quedado dentro del bloque.

    Se sustituyen por un salto de linea, no por nada: pegar el ultimo parrafo
    de la subseccion anterior con el primero de la siguiente fabricaria una
    oracion que nadie escribio.
    """
    return _ENCABEZADO.sub("\n", cuerpo)


def _limpiar_cuerpo_con_mapa(cuerpo, base):
    """Lo mismo que `_limpiar_cuerpo()`, mas como deshacerlo.

    Devuelve `(cuerpo_limpio, tramos)`. Cada tramo es
    `(ini_limpio, fin_limpio, ini_documento)` de un trozo que sobrevivio
    intacto. Entre dos tramos hay un encabezado que se fue: ahi el mapa no es
    invertible, y por eso es una lista de tramos y no una funcion.

    `base` es donde empieza `cuerpo` dentro del markdown completo.

    El mapa es lineal a trozos en vez de por caracter porque un encabezado
    borrado desplaza TODO lo que va detras la misma cantidad. Guardar una
    entrada por caracter costaria ~260 000 entradas por corpus para decir lo
    mismo que dicen unas pocas decenas.
    """
    partes, tramos = [], []
    largo, cursor = 0, 0
    for m in _ENCABEZADO.finditer(cuerpo):
        if m.start() > cursor:
            trozo = cuerpo[cursor:m.start()]
            partes.append(trozo)
            tramos.append((largo, largo + len(trozo), base + cursor))
            largo += len(trozo)
        partes.append("\n")          # el mismo salto que mete la sustitucion
        largo += 1
        cursor = m.end()
    if cursor < len(cuerpo):
        trozo = cuerpo[cursor:]
        partes.append(trozo)
        tramos.append((largo, largo + len(trozo), base + cursor))
    return "".join(partes), tramos


def _tramo_de(tramos, posicion):
    """Indice del tramo que contiene `posicion`, o None si cayo en un hueco."""
    i = bisect.bisect_right([t[0] for t in tramos], posicion) - 1
    if i < 0:
        return None
    ini, fin, _ = tramos[i]
    return i if ini <= posicion < fin else None


def traducir_span(tramos, ini, fin):
    """Span del cuerpo limpio -> `(ini_doc, fin_doc, contiguo)`.

    `contiguo` es False cuando el span cruza un encabezado borrado: ahi ningun
    par de posiciones del documento recorta exactamente la oracion, porque en
    medio esta el titulo que se quito. Son pocas --del orden del 0.2 % de las
    oraciones-- pero **silenciosas si no se marcan**: el subrayado saldria con
    un titulo de subseccion metido dentro y nadie lo notaria salvo mirandolo.

    Devuelve `(None, None, False)` si alguna punta cae dentro del hueco.
    """
    i = _tramo_de(tramos, ini)
    j = _tramo_de(tramos, fin - 1)
    if i is None or j is None:
        return None, None, False
    a = tramos[i][2] + (ini - tramos[i][0])
    b = tramos[j][2] + (fin - 1 - tramos[j][0]) + 1
    return a, b, i == j


def secciones(texto_markdown, clases=None):
    """[(seccion, cuerpo)] en orden de aparicion. `seccion` es la clase.

    Los bloques NO se fusionan aunque repitan clase. `## ABSTRACT` aparece 1203
    veces en 914 documentos porque los resumenes estructurados convirtieron
    cada subtitulo en otro bloque; devolverlos por separado conserva el orden
    de aparicion del documento, que es lo que `n_oracion` necesita, y evita
    pegar el final de un bloque con el principio del siguiente. Quien cuente
    secciones por documento tiene que tolerar clases repetidas.
    """
    mapa = clases if clases is not None else cargar_clases()
    return [(mapa.get(etiqueta, CLASE_DESCONOCIDA) if etiqueta
             else CLASE_DESCONOCIDA, cuerpo)
            for etiqueta, cuerpo in bloques(texto_markdown)]


# El corte de oracion, como constante y no en linea, para que
# `oraciones_con_offset()` pueda recorrerlo con finditer en vez de partir con
# split. Son la misma expresion: los trozos de un split son los huecos entre
# las coincidencias de un finditer, y `\s+` no puede casar vacio, asi que no
# hay caso degenerado que los separe.
_SEP = re.compile(r"(?<=[.!?])\s+")


def oraciones_con_offset(cuerpo):
    """[(ini, fin, oracion)] con los offsets sobre `cuerpo` sin transformar.

    Misma logica de corte que `oraciones()` -- de hecho esa funcion es un
    envoltorio de esta, para que no existan dos -- mas la posicion de cada
    oracion en el texto que se recibio. Con eso se puede subrayar la evidencia
    sobre el documento original en vez de mostrarla suelta.

    Que esto se pueda hacer sin tocar los cortes depende de un detalle del
    orden: se normaliza DESPUES de partir, asi que las posiciones que decide
    `_SEP` son posiciones reales de `cuerpo`. Lo unico que hay que deshacer son
    los tres sitios que mueven caracteres sin moverse el corte: el separador de
    largo variable que `split` tiraba, el `+ " " +` que re-pega los trozos de
    una abreviatura, y el recorte de extremos.

    OJO CON EL ORIGEN. Los `.txt` del corpus se escribieron con `write_text`,
    que en Windows tradujo los saltos a CRLF. Estos offsets son en caracteres
    del texto YA leido --o sea con los saltos traducidos de vuelta a `\\n`--, no
    en bytes del archivo en disco. Quien pinte el subrayado sobre los bytes
    crudos lo vera corrido una posicion por cada linea anterior.
    """
    # Los trozos son los huecos entre separadores; se guardan como spans en
    # vez de como texto, que es toda la diferencia con re.split.
    trozos, cursor = [], 0
    for m in _SEP.finditer(cuerpo):
        trozos.append((cursor, m.start()))
        cursor = m.end()
    trozos.append((cursor, len(cuerpo)))

    crudas, ini_acc, fin_acc, acumulado = [], None, None, ""
    for a, b in trozos:
        t = cuerpo[a:b]
        if acumulado:
            acumulado = (acumulado + " " + t).strip()
            fin_acc = b
        else:
            acumulado = t
            ini_acc, fin_acc = a, b
        if ABREV.search(acumulado) or _INICIAL.search(acumulado):
            continue
        crudas.append((ini_acc, fin_acc, normalizar_espacios(acumulado)))
        acumulado = ""
    if acumulado:
        crudas.append((ini_acc, fin_acc, normalizar_espacios(acumulado)))

    # El `.strip()` de arriba y el de `normalizar_espacios` recortaron blancos
    # que el span todavia incluye. Sin esto el subrayado empieza un espacio
    # antes de la primera letra.
    salida = []
    for a, b, o in crudas:
        if not o:
            continue
        while a < b and cuerpo[a].isspace():
            a += 1
        while b > a and cuerpo[b - 1].isspace():
            b -= 1
        salida.append((a, b, o))
    return salida


def oraciones(cuerpo):
    """Lista de oraciones crudas, con espacios normalizados.

    Heuristica, suficiente para prosa cientifica. Se conserva tal cual la
    logica de `auditar_signo.py:118-130` porque las 93 oraciones evaluables de
    la auditoria de signo salieron de ella: cambiarla haria que la etapa 6 no
    pudiera unir sus filas con las predicciones, y la exactitud de signo se
    calcularia sobre un punado de filas sin que nada fallara.

    Es un envoltorio de `oraciones_con_offset()` a proposito: mientras haya una
    sola implementacion del corte, anadir offsets no puede mover una oracion.
    Dos implementaciones que "hacen lo mismo" divergen, y esta es justo la que
    no puede.
    """
    return [o for _, _, o in oraciones_con_offset(cuerpo)]


def pretokenizar(oracion, protegidos):
    """(texto_pretokenizado, spans_nuevos).

    `protegidos` es [(ini, fin), ...] en offsets de `oracion`; esos tramos se
    copian verbatim y su nuevo span se devuelve en el mismo orden en que se
    recibieron.

    **Los tramos protegidos son exactamente las menciones reconocidas.** Sin
    eso `mexEF-oprN` saldria como `mexEF - oprN`, dejaria de ser un token unico
    y el marcado `<e1> X </e1>` con `\\S+` ya no lo capturaria.

    Ademas de copiarlos verbatim se les garantiza un blanco a cada lado. Hacia
    falta: `PAO1DeltamexEF` (con la letra griega, que el tokenizador del lexico
    no admite dentro de un nombre) dejaba la mencion pegada al prefijo, y
    entonces o `marcar()` metia un espacio que no estaba --y el texto marcado
    ya no reproducia el pretokenizado, que es una invariante de la etapa 2-- o
    `<e1>` quedaba sin separacion previa, que el entrenamiento no muestra ni
    una vez en 1563 ocurrencias.

    **Regla que NO se aplica:** no se separa la frontera letra-digito. El
    entrenamiento muestra `His 6 - ArgP`, que sugeriria hacerlo, pero eso
    convertiria `PA0762` en `PA 0762` y partiria la mitad del vocabulario del
    dominio a cambio de imitar un artefacto del extractor de PDF del asesor.
    """
    orden = sorted(range(len(protegidos)), key=lambda k: protegidos[k])
    piezas = []          # (texto, indice original del protegido o None)
    cursor = 0
    for k in orden:
        ini, fin = protegidos[k]
        if ini < cursor:
            raise ValueError("Los tramos protegidos se solapan: %r"
                             % (protegidos,))
        if ini > cursor:
            piezas.append((_espaciar(oracion[cursor:ini]), None))
        piezas.append((oracion[ini:fin], k))
        cursor = fin
    if cursor < len(oracion):
        piezas.append((_espaciar(oracion[cursor:]), None))

    partes, brutos = [], {}
    largo = 0
    for texto, k in piezas:
        if k is None:
            partes.append(texto)
            largo += len(texto)
            continue
        partes.append(" ")
        largo += 1
        brutos[k] = (largo, largo + len(texto))
        partes.append(texto)
        largo += len(texto)
        partes.append(" ")
        largo += 1
    bruto = "".join(partes)

    # Colapsar blancos a mano en vez de con re.sub, para poder arrastrar los
    # spans. Un mapa de posiciones es mas barato que recalcular las menciones
    # sobre el texto ya transformado, y no puede desalinearse.
    salida, mapa = [], {}
    i, n = 0, len(bruto)
    while i < n:
        if bruto[i].isspace():
            j = i
            while j < n and bruto[j].isspace():
                j += 1
            if salida and j < n:
                salida.append(" ")
            i = j
        else:
            mapa[i] = len(salida)
            salida.append(bruto[i])
            i += 1
    texto = "".join(salida)

    spans = []
    for k in range(len(protegidos)):
        ini, fin = brutos[k]
        spans.append((mapa[ini], mapa[fin - 1] + 1))
    return texto, spans


def _espaciar(s):
    """Rodea de espacios la puntuacion de un tramo NO protegido.

    Los tramos de `_INTACTOS` --numeros con separador decimal o de millares y
    entidades HTML-- se copian tal cual, porque son la puntuacion que el
    entrenamiento nunca separa. Ver el comentario de `_INTACTOS`.
    """
    salida, cursor = [], 0
    for m in _INTACTOS.finditer(s):
        if m.start() > cursor:
            salida.append(_PUNTUACION.sub(r" \1 ", s[cursor:m.start()]))
        salida.append(m.group(0))
        cursor = m.end()
    salida.append(_PUNTUACION.sub(r" \1 ", s[cursor:]))
    return "".join(salida)


def marcar(texto, span_tf, span_target):
    """Inserta `<e1> ... </e1>` sobre el TF y `<e2> ... </e2>` sobre el blanco.

    `e1` es un ROL, no una posicion: `e1` es siempre el TF y `e2` siempre el
    blanco, aunque el blanco aparezca antes en la oracion. Medido: 0
    discrepancias en 1562 filas del entrenamiento, y el gen va antes que el TF
    en el 38.6 % de los casos sin que el marcado se reordene.

    El espaciado no es cosmetico. Los marcadores NO son tokens especiales
    --no hay `add_tokens` ni `resize_token_embeddings` en
    `bio_bert_re_finetune.py`-- asi que se parten en piezas de wordpiece. Con
    `>` pegado al nombre las piezas son otras y el modelo nunca vio eso.
    Medido: el contenido entre `<e1>` y `</e1>` empieza y termina con
    exactamente un espacio en 1563 de 1563 ocurrencias, cero excepciones.
    """
    if span_tf == span_target:
        raise ValueError("El TF y el blanco no pueden ocupar el mismo tramo.")
    a, b = (span_tf, "1"), (span_target, "2")
    (ini_p, fin_p), etq_p = a if span_tf[0] <= span_target[0] else b
    (ini_s, fin_s), etq_s = b if span_tf[0] <= span_target[0] else a
    if fin_p > ini_s:
        raise ValueError("Los tramos a marcar se solapan: %r y %r"
                         % (span_tf, span_target))
    partes = [
        texto[:ini_p],
        "<e%s> " % etq_p, texto[ini_p:fin_p], " </e%s>" % etq_p,
        texto[fin_p:ini_s],
        "<e%s> " % etq_s, texto[ini_s:fin_s], " </e%s>" % etq_s,
        texto[fin_s:],
    ]
    return normalizar_espacios("".join(partes))
