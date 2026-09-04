# -*- coding: utf-8 -*-
"""El corte de oracion y sus offsets.

Esta prueba llena un hueco que hasta ahora solo cubria un guardian de tiempo
de corrida. `evaluar_signo.py` une las filas de la auditoria de signo con las
predicciones comparando el TEXTO de la oracion --no hay identificador estable--
y aborta si se unen menos de 80 de 93. Hoy se unen 84: cuatro filas de margen.
O sea que hasta ahora, mover un corte de oracion se descubria corriendo la
evaluacion, y solo si el dano pasaba de cierto tamano.

Aqui se descubre al correr las pruebas, y con una sola oracion que cambie.

POR QUE ESTO NO ES CIRCULARIDAD
===============================
El paquete bronce no puede leer las referencias de evaluacion: de eso va el
docstring de `__init__.py`. Esta prueba abre la auditoria y aun asi no rompe
esa regla, por dos razones que conviene dejar escritas.

La primera es que usa UNICAMENTE la columna `oracion`. Nunca mira
`signo_correcto`, ni `tf`, ni `blanco`. Las 93 filas funcionan aqui como un
corpus de oraciones biomedicas reales cuya segmentacion se conoce, no como un
patron contra el que medir aciertos. Si manana la columna del signo cambiara
entera, esta prueba daria exactamente lo mismo.

La segunda es que es una PRUEBA, y la frontera lo contempla: el guardian de
`test_contaminacion.py` exime a los archivos con prefijo de prueba por el mismo
motivo por el que existen, comprobar que la evaluacion se hace bien exige abrir
lo que la evaluacion abre.

    python -m unittest discover .
"""

import glob
import io
import os
import sys
import unittest

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)

from grn_bronce import texto as T

AUDITORIA = os.path.join(_RAIZ, "etapa2", "auditoria_signo.tsv")
CORPUS = os.path.join(_RAIZ, "datos", "fulltext", "xml")

# Lo que produjo la corrida del 27 de agosto sobre el corpus v0-agosto. No es
# adorno: `n_oracion` es el indice de la oracion dentro del documento y entra
# al sha1 que forma `id_par`, asi que una oracion de mas o de menos recorre
# TODOS los identificadores del corpus y ninguna union posterior cuadra.
DOCUMENTOS_V0 = 918
ORACIONES_V0 = 259895

# El corpus vive fuera de git. En una copia limpia del repositorio no hay nada
# que recorrer, y eso no es un fallo.
HAY_CORPUS = (os.path.isdir(CORPUS)
              and bool(glob.glob(os.path.join(CORPUS, "*.txt"))))


def oraciones_auditadas():
    """Las 93 oraciones evaluables, y nada mas de ese archivo."""
    with io.open(AUDITORIA, encoding="utf-8") as f:
        columnas = f.readline().rstrip("\n").split("\t")
        for linea in f:
            if not linea.strip():
                continue
            fila = dict(zip(columnas, linea.rstrip("\n").split("\t")))
            if fila.get("evaluable") == "true":
                yield fila["oracion"]


class PruebasGolden(unittest.TestCase):
    """El corte, fijado contra el dato y no contra la memoria."""

    @classmethod
    def setUpClass(cls):
        cls.oraciones = list(oraciones_auditadas())

    def test_son_93_y_no_otro_numero(self):
        """Si la auditoria cambia de tamano, las cifras de signo publicadas
        dejan de referirse a lo mismo y hay que decirlo, no absorberlo."""
        self.assertEqual(len(self.oraciones), 93)

    def test_ninguna_se_parte_al_volver_a_segmentarla(self):
        """La condicion exacta que necesita la union de la etapa 6: cada
        oracion auditada tiene que seguir siendo UNA oracion."""
        parten = [o for o in self.oraciones if T.oraciones(o) != [o]]

        self.assertEqual(
            parten, [],
            "%d de 93 oraciones auditadas cambiaron al segmentarlas de nuevo; "
            "la union de evaluar_signo.py va a caer por debajo de su guardian "
            "de 80." % len(parten))

    def test_el_span_de_cada_una_recorta_su_propio_texto(self):
        for o in self.oraciones:
            for ini, fin, texto in T.oraciones_con_offset(o):
                self.assertEqual(T.normalizar_espacios(o[ini:fin]), texto)


class PruebasOffsets(unittest.TestCase):

    def test_el_span_apunta_al_texto_sin_transformar(self):
        """Un span que no recorta la misma frase es un subrayado que senala
        otra cosa, y nada delata el error salvo mirarlo."""
        cuerpo = "MexT  activates\n\nmexEF-oprN.   The operon follows."

        salida = T.oraciones_con_offset(cuerpo)

        self.assertEqual(len(salida), 2)
        for ini, fin, texto in salida:
            self.assertEqual(T.normalizar_espacios(cuerpo[ini:fin]), texto)

    def test_el_span_no_se_come_los_blancos_de_los_extremos(self):
        """El separador que split tiraba tiene largo variable. Si el span lo
        incluye, el subrayado empieza antes de la primera letra."""
        cuerpo = "Uno.     Dos."

        (a1, b1, _), (a2, b2, _) = T.oraciones_con_offset(cuerpo)

        self.assertFalse(cuerpo[a1].isspace())
        self.assertFalse(cuerpo[b1 - 1].isspace())
        self.assertFalse(cuerpo[a2].isspace())
        self.assertFalse(cuerpo[b2 - 1].isspace())

    def test_oraciones_es_un_envoltorio_y_no_una_segunda_implementacion(self):
        """Dos implementaciones que hacen lo mismo divergen. Esta es justamente
        la que no puede."""
        cuerpo = ("MexT acts in P. aeruginosa PAO1. See Fig. 3 for details. "
                  "The mexEF-oprN operon follows.")

        self.assertEqual(
            T.oraciones(cuerpo),
            [o for _, _, o in T.oraciones_con_offset(cuerpo)])

    def test_la_guarda_de_abreviatura_conserva_el_span_completo(self):
        """Cuando ABREV re-pega dos trozos, el span tiene que abarcar los dos:
        el espacio que los une no existe en el texto original."""
        cuerpo = "See Fig. 3 for details."

        salida = T.oraciones_con_offset(cuerpo)

        self.assertEqual(len(salida), 1)
        ini, fin, texto = salida[0]
        self.assertEqual(cuerpo[ini:fin], cuerpo)
        self.assertEqual(texto, cuerpo)


class PruebasMapaInverso(unittest.TestCase):
    """De las coordenadas de la oracion normalizada a las del texto crudo.

    El reconocimiento de menciones trabaja sobre la oracion ya normalizada, o
    sea en unas coordenadas que no existen en el documento. Sin este mapa, un
    subrayado de gen se pinta desplazado tantas posiciones como blancos se
    hayan colapsado antes de el.
    """

    def test_produce_lo_mismo_que_la_funcion_de_siempre(self):
        """Si divergieran, habria dos normalizaciones distintas y el mapa
        traduciria a un texto que nadie mas produce."""
        for s in ["  MexT   activates\n\n mexEF-oprN. ",
                  "sin blancos raros",
                  "\t\ttabulado\ty todo\n",
                  ""]:
            texto, _inverso = T.normalizar_espacios_con_mapa(s)

            self.assertEqual(texto, T.normalizar_espacios(s))

    def test_hay_una_entrada_por_caracter_de_salida(self):
        s = "  MexT   activates  mexEF-oprN.  "

        texto, inverso = T.normalizar_espacios_con_mapa(s)

        self.assertEqual(len(inverso), len(texto))

    def test_desnormalizar_devuelve_el_texto_original_de_la_mencion(self):
        """El caso que importa: la mencion se reconocio sobre el texto
        normalizado y hay que pintarla sobre el crudo."""
        crudo = "MexT   activates\n\nmexEF-oprN in PAO1."
        texto, inverso = T.normalizar_espacios_con_mapa(crudo)
        ini = texto.index("mexEF-oprN")

        a, b = T.desnormalizar_span(inverso, ini, ini + len("mexEF-oprN"))

        self.assertEqual(crudo[a:b], "mexEF-oprN")

    def test_el_fin_del_span_no_se_traduce_directo(self):
        """`fin` es exclusivo y puede caer sobre un blanco colapsado, que el
        mapa no conoce. Traducirlo directo daria KeyError o la posicion de
        otro caracter; hay que traducir el ultimo incluido y sumar uno."""
        crudo = "MexT     activates"
        texto, inverso = T.normalizar_espacios_con_mapa(crudo)

        a, b = T.desnormalizar_span(inverso, 0, len("MexT"))

        self.assertEqual(crudo[a:b], "MexT")
        self.assertTrue(crudo[b].isspace())


class PruebasBloques(unittest.TestCase):
    """El segundo mapa: del cuerpo limpio al markdown original."""

    def test_bloques_es_un_envoltorio_de_bloques_con_offset(self):
        md = "# Titulo\n\n## RESULTS\nMexT activates mexEF-oprN.\n"

        self.assertEqual(
            T.bloques(md),
            [(e, c) for e, c, _ in T.bloques_con_offset(md)])

    def test_el_span_recorta_la_oracion_en_el_documento_entero(self):
        """El punto de todo esto: subrayar sobre el documento, no sobre un
        bloque suelto que ya nadie tiene."""
        md = ("# Titulo\n\n## RESULTS\nMexT activates mexEF-oprN. "
              "The operon follows.\n")

        for _etiqueta, cuerpo, tramos in T.bloques_con_offset(md):
            for ini, fin, oracion in T.oraciones_con_offset(cuerpo):
                a, b, contiguo = T.traducir_span(tramos, ini, fin)
                self.assertTrue(contiguo)
                self.assertEqual(T.normalizar_espacios(md[a:b]), oracion)

    def test_la_oracion_que_cruza_un_encabezado_se_marca(self):
        """`_limpiar_cuerpo()` borra los encabezados internos, asi que una
        oracion partida por uno no tiene span contiguo: el del documento
        incluiria el titulo. Son pocas, y silenciosas si no se marcan."""
        md = ("## RESULTS\nThe operon was induced\n"
              "### DETAIL OF THE ASSAY\nby MexT.\n")

        (_etiqueta, cuerpo, tramos), = T.bloques_con_offset(md)
        (ini, fin, oracion), = T.oraciones_con_offset(cuerpo)
        a, b, contiguo = T.traducir_span(tramos, ini, fin)

        self.assertEqual(oracion, "The operon was induced by MexT.")
        self.assertFalse(contiguo)
        self.assertIn("DETAIL OF THE ASSAY", md[a:b])


@unittest.skipUnless(HAY_CORPUS, "sin datos/fulltext/xml (no esta en git)")
class PruebasCorpus(unittest.TestCase):
    """Sobre el corpus entero, no sobre una muestra."""

    @classmethod
    def setUpClass(cls):
        cls.textos = sorted(glob.glob(os.path.join(CORPUS, "*.txt")))

    def test_todos_los_spans_reconstruyen_su_oracion(self):
        malos, total = [], 0
        for ruta in self.textos:
            with io.open(ruta, encoding="utf-8") as f:
                md = f.read()
            for _etiqueta, cuerpo in T.bloques(md):
                for ini, fin, texto in T.oraciones_con_offset(cuerpo):
                    total += 1
                    if T.normalizar_espacios(cuerpo[ini:fin]) != texto:
                        if len(malos) < 5:
                            malos.append((os.path.basename(ruta), texto[:60]))

        self.assertEqual(malos, [], "hay spans que no reconstruyen")
        self.assertGreater(total, 0)

    def test_los_spans_del_documento_recortan_su_oracion(self):
        """La version fuerte: no sobre el cuerpo del bloque, sino sobre el
        markdown completo, que es donde se pinta el subrayado."""
        malos, contiguas, cruzan = [], 0, 0
        for ruta in self.textos:
            with io.open(ruta, encoding="utf-8") as f:
                md = f.read()
            for _etiqueta, cuerpo, tramos in T.bloques_con_offset(md):
                for ini, fin, oracion in T.oraciones_con_offset(cuerpo):
                    a, b, contiguo = T.traducir_span(tramos, ini, fin)
                    self.assertIsNotNone(a)
                    if not contiguo:
                        cruzan += 1
                        continue
                    contiguas += 1
                    if T.normalizar_espacios(md[a:b]) != oracion:
                        if len(malos) < 5:
                            malos.append((os.path.basename(ruta), oracion[:60]))

        self.assertEqual(malos, [], "spans que no recortan su oracion")
        # No se afirma un numero exacto de no contiguas --depende del corpus--
        # pero si que sigan siendo una minoria clara. Si esto se dispara, algo
        # cambio en como se limpian los encabezados.
        self.assertLess(cruzan, contiguas * 0.02)

    def test_el_numero_de_oraciones_no_se_movio(self):
        """Solo si el corpus es el mismo que congelo v0-agosto. `n_oracion`
        entra al sha1 de `id_par`: una oracion de mas reescribe todos los
        identificadores y ninguna union posterior cuadra."""
        if len(self.textos) != DOCUMENTOS_V0:
            self.skipTest("el corpus tiene %d documentos, no los %d de "
                          "v0-agosto" % (len(self.textos), DOCUMENTOS_V0))

        total = 0
        for ruta in self.textos:
            with io.open(ruta, encoding="utf-8") as f:
                md = f.read()
            for _etiqueta, cuerpo in T.bloques(md):
                total += len(T.oraciones_con_offset(cuerpo))

        self.assertEqual(total, ORACIONES_V0)


if __name__ == "__main__":
    unittest.main()
