# -*- coding: utf-8 -*-
"""El signo léxico de un par en una oración: el del disparador con signo más
cercano al tramo entre sus dos menciones.

Es el «control léxico» del punto 18 del PLAN, el que mide la evaluación del
paso 2 (`grn_verificacion/evaluar.py`), y desde el 23-oct-2026 también un voto
posible de la red (`grn_red/signo.py`, apagado por omisión). Vive aquí y no en
ninguno de los dos para que los dos lean la misma función: con una copia en
cada lado, la regla que se mide en la muestra ciega y la que vota en la red
podían separarse sin que nada avisara, y la cifra de la tanda 2 hablaría de
otra regla.

El algoritmo es el de `evaluar._signo_cercano` del 8-oct-2026, sin cambios.
Sus peculiaridades quedan escritas porque forman parte de lo que se mide, y
`grn_comun/test_signo_lexico.py` las fija:

- **Cada mención se ubica con `str.find`:** su primera aparición en la
  oración, que no siempre es la del par marcado. Una mención vacía «se
  encuentra» en la posición 0, y una que no aparece deja al par sin signo.
- **El tramo va del inicio de la primera mención al inicio de la segunda**,
  no a su final. Un disparador está dentro solo si cabe entero en ese tramo.
- **Fuera del tramo, la distancia es `min(|d_ini - fin|, |ini - d_fin|)`**,
  medida en caracteres.
- **En un empate de distancia gana el primero** que devuelve
  `vocab.disparadores_en`, que los entrega en orden de aparición.

Los «?» no cuentan: la regla, fijada antes de medir, es «el disparador con
signo más cercano». La primera medición del 8-oct también aceptaba «?», y un
«regulates» cercano le ganaba a un «represses» lejano: daba 200 pares con
signo único en lugar de 537.

Es una propuesta léxica, no reconocimiento de relaciones. Un disparador
cercano no dice que la oración afirme esa relación, ni con ese signo: la
negación, la voz pasiva y el fenotipo del mutante lo invierten
(`grn_bronce/recursos/disparadores.csv`).

Biblioteca estándar y Python 3.8.
"""


def signo_cercano(oracion, mencion_1, mencion_2, vocab):
    """«+» o «-», el signo del disparador con signo más cercano al tramo entre
    las dos menciones, o "" si la oración no tiene ninguno o alguna mención no
    aparece en ella.

    `vocab` es cualquier objeto con `disparadores_en(oracion)` que devuelva
    `[(ini, fin, palabra, signo)]`, como `grn_bronce.vocabulario.Vocabulario`.
    El orden de las menciones no importa: el tramo va de la menor a la mayor.
    """
    a = oracion.find(mencion_1)
    b = oracion.find(mencion_2)
    if a < 0 or b < 0:
        return ""
    ini, fin = min(a, b), max(a, b)
    mejor, mejor_d = "", None
    for d_ini, d_fin, _palabra, signo in vocab.disparadores_en(oracion):
        if signo not in ("+", "-"):
            continue
        if ini <= d_ini and d_fin <= fin:
            dist = 0
        else:
            dist = min(abs(d_ini - fin), abs(ini - d_fin))
        if mejor_d is None or dist < mejor_d:
            mejor, mejor_d = signo, dist
    return mejor
