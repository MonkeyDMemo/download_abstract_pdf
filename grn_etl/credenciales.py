# -*- coding: utf-8 -*-
"""De donde salen el correo y la API key de NCBI.

Existe para que el CLI y el tablero las busquen igual, y sobre todo para
que las busquen SOLAS. Antes solo se miraba el entorno, asi que en cada
sesion habia que exportar a mano una llave que ya estaba en el disco; el
dia que se olvidaba, el lanzamiento fallaba con un 400 y el motivo no
estaba a la vista.

El orden es: entorno primero, archivo despues. El entorno gana porque es
lo que permite correr una vez con otra cuenta sin tocar nada.

Los archivos van en la raiz del proyecto y los cubre el .gitignore:

    .key      la API key, una linea. Ya existia con esa forma.
    .correo   el correo de contacto, una linea.

El correo no es un secreto pero si es un dato personal, y NCBI lo recibe
en cada peticion: no tiene por que acabar en un repositorio publico.
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_LLAVE = RAIZ / ".key"
ARCHIVO_CORREO = RAIZ / ".correo"

# Lo que NCBI acepta como llave: 36 caracteres alfanumericos. Se valida
# antes de guardar para que un pegado a medias no se descubra hasta la
# primera peticion, cuando ya se marcaron articulos como fallidos.
LARGO_LLAVE = 36


def _leer(archivo):
    try:
        return archivo.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def correo(explicito=None):
    """El correo de contacto: argumento, entorno o archivo, en ese orden."""
    return (explicito or os.environ.get("NCBI_EMAIL")
            or _leer(ARCHIVO_CORREO)) or None


def llave():
    """La API key: entorno o archivo. Nunca se pasa por argumento.

    No hay flag de linea de comandos para la llave a proposito: quedaria
    en el historial del shell y en la lista de procesos de la maquina.
    """
    return (os.environ.get("NCBI_API_KEY") or _leer(ARCHIVO_LLAVE)) or None


def origen_llave():
    """De donde salio la llave, para poder decirlo sin decir cual es."""
    if os.environ.get("NCBI_API_KEY"):
        return "entorno"
    if _leer(ARCHIVO_LLAVE):
        return "archivo"
    return "ninguno"


def origen_correo():
    if os.environ.get("NCBI_EMAIL"):
        return "entorno"
    if _leer(ARCHIVO_CORREO):
        return "archivo"
    return "ninguno"


def parece_correo(valor):
    """Validacion deliberadamente floja: un arroba y un punto despues.

    Validar correos a fondo es un pozo sin fondo y aqui no hace falta: lo
    unico que importa es atajar el dedazo evidente, porque NCBI responde
    422 a un correo invalido y eso, en la etapa de PDF, marcaba articulos
    como permanentemente inaccesibles.
    """
    valor = (valor or "").strip()
    if len(valor) < 5 or valor.count("@") != 1:
        return False
    usuario, dominio = valor.split("@")
    return bool(usuario) and "." in dominio and not dominio.startswith(".")


def parece_llave(valor):
    valor = (valor or "").strip()
    return len(valor) == LARGO_LLAVE and valor.isalnum()


def guardar_correo(valor):
    """Escribe el correo en .correo. Devuelve el valor ya limpio."""
    valor = (valor or "").strip()
    if not parece_correo(valor):
        raise ValueError("ese correo no tiene forma de correo")
    ARCHIVO_CORREO.write_text(valor + "\n", encoding="utf-8")
    return valor


def guardar_llave(valor):
    """Escribe la API key en .key.

    Se escribe al mismo archivo que ya la guardaba, no a uno nuevo: el
    .gitignore lo cubre desde siempre y no se agrega un lugar mas donde
    pueda quedarse olvidada una credencial.
    """
    valor = (valor or "").strip()
    if not parece_llave(valor):
        raise ValueError(
            f"la API key de NCBI son {LARGO_LLAVE} caracteres alfanumericos")
    ARCHIVO_LLAVE.write_text(valor + "\n", encoding="utf-8")
    return valor


def borrar_llave():
    """Quita la llave guardada. El limite baja a 3 peticiones/segundo."""
    try:
        ARCHIVO_LLAVE.unlink()
        return True
    except OSError:
        return False
