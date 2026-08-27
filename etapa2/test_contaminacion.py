# -*- coding: utf-8 -*-
"""La frontera de la contaminacion (seccion 0.4 del contrato de datos).

`etapa2/oro_pseudomonas.tsv` y `etapa2/auditoria_signo.tsv` solo pueden
abrirse desde `evaluar_oro.py`, `evaluar_signo.py` y las pruebas. Esta prueba
busca esos dos nombres en el texto de todos los `.py` de `etapa2/` y falla si
aparecen fuera de la lista blanca.

Por que una prueba tan tonta merece existir
===========================================

Es la unica que impide, por descuido, el unico error que invalidaria todo el
trabajo. Si el patron de oro entra al diccionario, al generador de pares o a
la calibracion de umbrales, las metricas de las etapas 5 y 6 dejan de medir lo
que el pipeline encuentra y pasan a medir lo que le sopla el oro, y el numero
que sale sigue teniendo la misma etiqueta y la misma pinta de correcto. Ya
paso dos veces en este proyecto: un verificador de fuga que media con la misma
clave del agrupamiento (daba cero por construccion) y una metrica inflada por
ejemplos repetidos entre entrenamiento y prueba.

La verificacion adversarial demostro la version de este pipeline: un
`genes_pao1.tsv` cuyas 785 filas utiles eran copia literal del oro, rellenado
con filas vacias hasta 5700, se aceptaba sin una queja y publicaba
`cobertura_diccionario` 100.0 %, exhaustividad 81.7 % y acierto de signo
82.5 % con codigo de salida 0.

Es una prueba de texto, no de importaciones, a proposito: `open()` no es la
unica forma de leer un archivo, y lo que se quiere atrapar es que alguien
teclee el nombre.
"""

import ast
import os
import re
import unittest

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))

# Los dos archivos que no se pueden abrir desde fuera, por su nombre sin
# extension: asi tambien se atrapa `oro_pseudomonas.csv` o una variable que se
# llame `ORO_PSEUDOMONAS`.
PROTEGIDOS = ("oro_pseudomonas", "auditoria_signo")

# §0.4 nombra a los dos evaluadores. Las pruebas quedan fuera de la
# prohibicion por el mismo motivo por el que existen: comprobar que la
# evaluacion se hace bien exige abrir lo que la evaluacion abre.
LISTA_BLANCA = {
    # `verificar_oro.py` comprueba que las oraciones del oro existan donde la
    # fila dice. Entra a la lista blanca porque NO es parte del pipeline: nadie
    # lo importa, no produce nada que el pipeline consuma, y su unica salida es
    # un conteo por pantalla. Verificar el oro exige abrirlo, igual que
    # evaluarlo. Si algun dia otro modulo lo importa, esto hay que revisarlo.
    "oro_pseudomonas": {"evaluar_oro.py", "verificar_oro.py"},
    # `auditar_signo.py` PRODUCE auditoria_signo.tsv, no lo consume. Se agrega
    # a la lista blanca con esa condicion y no en general: la prueba
    # `test_auditar_signo_solo_escribe` de mas abajo comprueba que el nombre
    # aparece unicamente en su docstring y como valor de `--salida`, y que
    # ningun otro modulo lo importa. La razon de no dejarlo suelto es que la
    # frontera protege contra que el oro ENTRE al pipeline; un generador que
    # un dia empezara a releer su propia salida para «completarla» seria
    # exactamente esa entrada, y quedaria tapado por una excepcion escrita
    # anos antes. El contrato §0.4 no lo resolvia y esta es la decision.
    "auditoria_signo": {"evaluar_signo.py", "auditar_signo.py"},
}

# Los scripts del pipeline propiamente dicho. Ninguno puede nombrar los
# archivos protegidos, y se listan explicitamente para que agregar un script
# nuevo no herede el permiso por accidente.
DEL_PIPELINE = ("construir_diccionario.py", "extraer_pares.py",
                "clasificar.py", "red.py", "lexico.py", "texto.py",
                "particionar.py", "barrido.py", "diagnostico.py")


def _fuentes():
    for nombre in sorted(os.listdir(DIRECTORIO)):
        if nombre.endswith(".py"):
            ruta = os.path.join(DIRECTORIO, nombre)
            with open(ruta, encoding="utf-8") as f:
                yield nombre, f.read()


def _es_prueba(nombre):
    return nombre.startswith("test_")


class PruebasFrontera(unittest.TestCase):

    def test_el_oro_no_se_nombra_fuera_de_la_lista_blanca(self):
        intrusos = []
        for nombre, texto in _fuentes():
            if _es_prueba(nombre):
                continue
            for protegido in PROTEGIDOS:
                if protegido in texto and nombre not in LISTA_BLANCA[protegido]:
                    intrusos.append("%s nombra %s" % (nombre, protegido))
        self.assertEqual(
            [], intrusos,
            "Estos archivos nombran el patron de oro o la auditoria de signo "
            "fuera de la lista blanca de la seccion 0.4 del contrato. Si el "
            "oro entra al pipeline, la evaluacion mide el oro contra si mismo: "
            "%s" % intrusos)

    def test_la_lista_blanca_no_tiene_archivos_fantasma(self):
        """Una lista blanca que nombre un archivo inexistente es un permiso
        sin dueno: el dia que alguien cree ese archivo, hereda el permiso."""
        for protegido, archivos in LISTA_BLANCA.items():
            for archivo in archivos:
                self.assertTrue(
                    os.path.exists(os.path.join(DIRECTORIO, archivo)),
                    "La lista blanca de %s nombra %s, que no existe."
                    % (protegido, archivo))

    def test_los_scripts_del_pipeline_existen_y_estan_limpios(self):
        """Si un script del pipeline se renombra, esta prueba tiene que
        enterarse: si no, dejaria de vigilarlo en silencio."""
        for nombre in DEL_PIPELINE:
            ruta = os.path.join(DIRECTORIO, nombre)
            self.assertTrue(os.path.exists(ruta),
                            "%s no existe; actualiza DEL_PIPELINE." % nombre)
            with open(ruta, encoding="utf-8") as f:
                texto = f.read()
            for protegido in PROTEGIDOS:
                self.assertNotIn(
                    protegido, texto,
                    "%s nombra %s. Ningun script del pipeline puede leer el "
                    "patron de oro." % (nombre, protegido))

    def test_auditar_signo_solo_escribe(self):
        """`auditar_signo.py` esta en la lista blanca como PRODUCTOR.

        Se comprueba lo que justifica el permiso: que el nombre aparece solo
        en el docstring del modulo y como valor por omision de `--salida`. En
        cuanto alguien lo use para leer, esta prueba falla y hay que volver a
        decidir el permiso a la vista del caso concreto.
        """
        ruta = os.path.join(DIRECTORIO, "auditar_signo.py")
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
        arbol = ast.parse(texto)
        docstring = ast.get_docstring(arbol)
        lineas_docstring = set()
        if docstring is not None and arbol.body:
            primero = arbol.body[0]
            lineas_docstring = set(range(primero.lineno,
                                         getattr(primero, "end_lineno",
                                                 primero.lineno) + 1))
        malas = []
        for numero, linea in enumerate(texto.splitlines(), 1):
            if "auditoria_signo" not in linea:
                continue
            if numero in lineas_docstring or "--salida" in linea:
                continue
            malas.append("linea %d: %s" % (numero, linea.strip()))
        self.assertEqual(
            [], malas,
            "auditar_signo.py esta en la lista blanca solo porque escribe "
            "auditoria_signo.tsv. Aqui lo esta usando de otra forma: %s"
            % malas)

    def test_nadie_importa_auditar_signo(self):
        """El permiso de escritura no se hereda por importacion."""
        importadores = []
        for nombre, texto in _fuentes():
            if nombre == "auditar_signo.py":
                continue
            if re.search(r"^\s*(import\s+auditar_signo|from\s+auditar_signo\s)",
                         texto, re.M):
                importadores.append(nombre)
        self.assertEqual([], importadores,
                         "Estos modulos importan auditar_signo.py: %s"
                         % importadores)

    def test_el_diccionario_no_declara_procedencia_de_oro(self):
        """`oro` no es un valor valido de la columna `fuente` (§2).

        Es la misma comprobacion que hace `construir_diccionario.py` antes de
        escribir, repetida aqui sobre el archivo versionado: la del script
        protege la corrida, esta protege el repositorio de que alguien edite
        el TSV a mano.
        """
        ruta = os.path.join(DIRECTORIO, "genes_pao1.tsv")
        if not os.path.exists(ruta):
            self.skipTest("genes_pao1.tsv no esta construido")
        with open(ruta, encoding="utf-8") as f:
            columnas = f.readline().rstrip("\n").split("\t")
            i_fuente = columnas.index("fuente")
            for numero, linea in enumerate(f, 2):
                campos = linea.rstrip("\n").split("\t")
                if len(campos) <= i_fuente:
                    continue
                tokens = [t for t in campos[i_fuente].split("|") if t]
                self.assertNotIn(
                    "oro", tokens,
                    "genes_pao1.tsv linea %d declara procedencia 'oro'. Eso "
                    "hace circular la evaluacion (seccion 7 del contrato)."
                    % numero)


if __name__ == "__main__":
    unittest.main()
