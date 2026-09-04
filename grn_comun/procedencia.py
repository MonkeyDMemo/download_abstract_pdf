# -*- coding: utf-8 -*-
"""De donde viene cada archivo, y si los que se leen juntos son de la misma corrida.

El programa de la etapa 2 son cuatro pasos encadenados. Cada uno escribe lo que
el siguiente lee:

    extraer_pares.py -> pares.jsonl
    clasificar.py    -> predicciones.jsonl
    red.py           -> red.tsv, red_informe.json
    evaluar_*.py     -> las cifras

**El peligro es mezclar pasos de corridas distintas.** Es facil: los nombres de
archivo son siempre los mismos, asi que basta rehacer un paso y no los otros, o
copiar un archivo de una carpeta vieja. Y la evaluacion no protesta, porque cada
archivo por separado esta bien formado.

Medido antes de escribir esto: **la misma red publica 80.6% o 100.0% de
exhaustividad segun que archivo se le ponga al lado, y sale con codigo 0.**
Trece puntos de diferencia sin un solo aviso.

Ese es exactamente el genero de defecto que este trabajo vino a corregir: un
numero que no mide lo que su etiqueta dice. Por eso el guardian va antes de la
cifra que protege y no despues, porque despues ya se cito.

Comparar rutas no sirve: la ruta es la misma y el contenido cambia. Se comparan
los bytes.

Solo biblioteca estandar.
"""

import hashlib
import json
import os

# Prefijo del sha256, no el digest entero. 16 hexadecimales son 64 bits: de
# sobra para descartar una confusion accidental, que es de lo que protege esto.
# No protege de un adversario, y no pretende hacerlo.
LARGO = 16


def huella(ruta):
    """El sha256 del contenido, recortado. None si el archivo no esta.

    Se lee por bloques: `pares.jsonl` puede pasar de los 100 MB y no hay razon
    para cargarlo entero solo para medirlo.
    """
    if not ruta or not os.path.exists(ruta):
        return None
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()[:LARGO]


def sellar(rutas):
    """{nombre: {ruta, huella, bytes}} para dejarlo escrito en un informe.

    Se guarda tambien el tamano porque es lo primero que mira una persona
    cuando dos huellas no casan, y responde solo la mitad de las veces
    ('ah, es que ese quedo a medias').
    """
    sello = {}
    for nombre, ruta in rutas.items():
        if not ruta:
            continue
        sello[nombre] = {
            "ruta": ruta,
            "huella": huella(ruta),
            "bytes": os.path.getsize(ruta) if os.path.exists(ruta) else None,
        }
    return sello


def sellar_como(ruta_declarada, ruta_real):
    """Mide un archivo pero lo anota bajo otro nombre.

    Existe por la escritura atomica. `red.py` escribe a `red.tsv.tmp` y solo
    al final `publicar()` lo renombra a `red.tsv`, junto con el informe donde
    va este sello. En el momento de sellar, el nombre final todavia no existe:
    medirlo directamente daba huella None, y la evaluacion siguiente rechazaba
    la cadena por una discrepancia que no era real.

    Se mide el temporal, que ya tiene el contenido definitivo, y se anota la
    ruta final, que es la que la evaluacion va a leer.
    """
    return {
        "ruta": ruta_declarada,
        "huella": huella(ruta_real),
        "bytes": os.path.getsize(ruta_real) if os.path.exists(ruta_real) else None,
    }


def leer_sello(ruta_informe, llave="huellas"):
    """El sello que dejo un paso anterior. {} si no hay informe o no lo trae.

    Devolver {} y no fallar es deliberado: un informe viejo, de antes de que
    esto existiera, no debe impedir que la evaluacion corra. Lo que si debe
    hacer es decirlo, y de eso se encarga quien llama.
    """
    if not ruta_informe or not os.path.exists(ruta_informe):
        return {}
    try:
        with open(ruta_informe, encoding="utf-8") as f:
            return json.load(f).get(llave) or {}
    except ValueError:
        return {}


def verificar(sello_esperado, rutas_ahora):
    """Compara lo que se sello contra lo que se va a leer.

    Devuelve (problemas, sin_sellar):

    - `problemas` es la lista de discrepancias, cada una en una frase que se
      pueda imprimir tal cual. Si trae algo, **no hay que seguir**.
    - `sin_sellar` son los nombres que el informe no menciona. No es un error:
      es un informe de antes, o un paso que no sello ese archivo. Se reporta
      para que quede dicho, no para abortar.
    """
    problemas, sin_sellar = [], []
    for nombre, ruta in rutas_ahora.items():
        if not ruta:
            continue
        anotado = sello_esperado.get(nombre)
        if not anotado:
            sin_sellar.append(nombre)
            continue
        ahora = huella(ruta)
        if ahora is None:
            problemas.append(
                "%s: %s no existe, y la red se hizo con uno de huella %s"
                % (nombre, ruta, anotado.get("huella")))
        elif ahora != anotado.get("huella"):
            problemas.append(
                "%s: se va a leer %s (huella %s, %s bytes) pero la red se "
                "construyo con %s (huella %s, %s bytes). Son corridas "
                "distintas."
                % (nombre, ruta, ahora,
                   os.path.getsize(ruta),
                   anotado.get("ruta"), anotado.get("huella"),
                   anotado.get("bytes")))
    return problemas, sin_sellar


def exigir(ruta_informe, rutas_ahora, salida=print, llave="huellas"):
    """Verifica y devuelve True si se puede seguir.

    El aviso de 'sin sellar' se imprime pero no detiene: sirve para que quien
    lea la salida sepa que esa parte no quedo comprobada.
    """
    sello = leer_sello(ruta_informe, llave)
    if not sello:
        salida("AVISO: %s no trae huellas de sus entradas, asi que no se puede "
               "comprobar que vengan de la misma corrida. Vuelve a correr "
               "red.py para que las escriba." % ruta_informe)
        return True

    problemas, sin_sellar = verificar(sello, rutas_ahora)
    if sin_sellar:
        salida("AVISO: sin huella anotada para %s; esa parte no queda "
               "comprobada." % ", ".join(sorted(sin_sellar)))
    if problemas:
        salida("")
        salida("ENTRADAS DE CORRIDAS DISTINTAS. No se evalua:")
        for p in problemas:
            salida("  - %s" % p)
        salida("")
        salida("Vuelve a correr la cadena completa, o apunta cada --opcion a "
               "los archivos de una misma corrida. Mezclarlos da una cifra que "
               "no mide lo que dice medir.")
        return False
    return True
