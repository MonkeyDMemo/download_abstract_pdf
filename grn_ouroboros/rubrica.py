"""La rúbrica que Ouroboros tiene que respetar: columnas, etiquetas y la forma
de su respuesta.

Las columnas y los valores cerrados no se escriben aquí: salen de
`revision.py`, que es el que valida lo que guarda el experto en la página de
revisión. Si la rúbrica cambia ahí, cambia aquí, y el juez no puede quedarse
con una versión vieja de las etiquetas mientras el experto usa otra.

La respuesta del modelo es un objeto JSON con los seis campos cerrados de la
hoja, el comentario y dos campos que la hoja no tiene:

- `fragmento`: el pedazo literal de la oración que sostiene el juicio. Si no
  está tal cual en la oración, el veredicto se queda pero se marca
  (`evidencia_invalida`).
- `motivo`: una o dos frases de por qué. No entra a la hoja.

El orden de las propiedades importa: con `format`, Ollama genera en ese orden,
y pedir primero el fragmento y el motivo hace que el modelo cite la oración
antes de decidir las etiquetas, en vez de justificar después lo que ya eligió.

Biblioteca estándar y Python 3.8.
"""

import hashlib
import json
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import revision  # noqa: E402

COLUMNAS_HOJA = list(revision.COLUMNAS_HOJA)
COLUMNAS_ITEM = list(revision.COLUMNAS_ITEM)
COLUMNAS_VALORES = list(revision.COLUMNAS_VALORES)
OPCIONES = dict((c, tuple(v)) for c, v in revision.OPCIONES.items())

# Los seis campos con valores cerrados, en el orden de la hoja. Son los que se
# comparan con el experto o con la llave; el comentario es texto libre.
CAMPOS_CERRADOS = [c for c in COLUMNAS_VALORES if c in OPCIONES]

# Sube cada vez que cambia la forma de la respuesta: entra a la llave de la
# caché, así que un veredicto con el esquema viejo no se reutiliza.
VERSION_ESQUEMA = 1

# Con relación = no, el signo y el tipo van vacíos (§4): el esquema tiene que
# admitir la cadena vacía o el modelo no podría escribir un «no» válido.
_ADMITEN_VACIO = ("signo", "tipo")

CAMPOS_RESPUESTA = ["fragmento", "motivo"] + CAMPOS_CERRADOS + ["comentario"]


def esquema():
    """El JSON Schema de la respuesta, nuevo en cada llamada para que nadie
    lo modifique por accidente. Es el que va en `format`."""
    propiedades = {
        "fragmento": {"type": "string"},
        "motivo": {"type": "string"},
    }
    for campo in CAMPOS_CERRADOS:
        valores = list(OPCIONES[campo])
        if campo in _ADMITEN_VACIO:
            valores.append("")
        propiedades[campo] = {"type": "string", "enum": valores}
    propiedades["comentario"] = {"type": "string"}
    return {"type": "object", "properties": propiedades,
            "required": list(CAMPOS_RESPUESTA),
            "additionalProperties": False}


def huella_esquema():
    """sha256 del esquema serializado en su orden: el orden cambia lo que
    genera el modelo, así que dos esquemas con las mismas claves en otro
    orden no son el mismo."""
    texto = json.dumps(esquema(), ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def validar_valores(valores):
    """(limpios, errores, avisos) de `revision.validar`: la misma regla que
    aplica la página de revisión al guardar lo que anota el experto."""
    return revision.validar(valores)


def validar_respuesta(objeto):
    """(valores, extras, errores_esquema, errores_rubrica, avisos) de lo que
    respondió el modelo.

    - `valores`: las columnas de anotación de la hoja, ya limpias por
      `revision.validar`.
    - `extras`: el fragmento y el motivo.
    - `errores_esquema`: lo que no tiene la forma pedida (un campo que falta,
      uno de más, un valor fuera de su lista).
    - `errores_rubrica`: lo que tiene la forma pero una combinación que la
      rúbrica prohíbe («no» con signo, «si» con negada = sí...).
    - `avisos`: lo que `revision.validar` señala sin bloquear.

    Con cualquier error el ítem es abstención; se separan para que el informe
    diga si el modelo no siguió el formato o no siguió la rúbrica.
    """
    if not isinstance(objeto, dict):
        return {}, {}, ["La respuesta no es un objeto JSON."], [], []
    errores = []
    faltan = [c for c in CAMPOS_RESPUESTA if c not in objeto]
    if faltan:
        errores.append("Faltan campos: %s." % ", ".join(faltan))
    sobran = sorted(str(c)[:40] for c in objeto if c not in CAMPOS_RESPUESTA)
    if sobran:
        errores.append("Campos que la respuesta no lleva: %s."
                       % ", ".join(sobran))
    for campo in CAMPOS_RESPUESTA:
        valor = objeto.get(campo, "")
        if not isinstance(valor, str):
            errores.append("«%s» tiene que ser texto." % campo)
            continue
        if campo in OPCIONES:
            permitidos = OPCIONES[campo] + (("",) if campo in _ADMITEN_VACIO
                                            else ())
            if valor.strip() not in permitidos:
                errores.append("«%s» no es una etiqueta de la rúbrica."
                               % campo)
    if errores:
        return {}, {}, errores, [], []
    valores = dict((c, objeto[c]) for c in COLUMNAS_VALORES)
    limpios, errores_rubrica, avisos = validar_valores(valores)
    extras = {"fragmento": objeto["fragmento"], "motivo": objeto["motivo"]}
    return limpios, extras, [], errores_rubrica, avisos
