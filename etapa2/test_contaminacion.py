# -*- coding: utf-8 -*-
"""La frontera de la contaminacion (seccion 0.4 del contrato de datos).

Cuatro nombres que el pipeline no puede teclear: el patron de oro
(`oro_pseudomonas`), la auditoria de signo (`auditoria_signo`), la base curada
del laboratorio (`GRN_experimental`) y la carpeta donde vive
(`datos/validacion`). Esta prueba los busca en el texto de todos los `.py` de
los paquetes vigilados, subcarpetas incluidas y sin distinguir mayusculas, y
falla si aparecen fuera de la lista blanca.

Por que una prueba tan tonta merece existir
===========================================

Es la unica que impide, por descuido, el unico error que invalidaria todo el
trabajo. Si el patron de oro o la base curada entran al diccionario, al
generador de pares o a la calibracion de umbrales, las metricas dejan de medir
lo que el pipeline encuentra y pasan a medir lo que le sopla la referencia, y
el numero que sale sigue teniendo la misma etiqueta y la misma pinta de
correcto. Ya paso dos veces en este proyecto: un verificador de fuga que media
con la misma clave del agrupamiento (daba cero por construccion) y una metrica
inflada por ejemplos repetidos entre entrenamiento y prueba.

La verificacion adversarial demostro la version de este pipeline: un
`genes_pao1.tsv` cuyas 785 filas utiles eran copia literal del oro, rellenado
con filas vacias hasta 5700, se aceptaba sin una queja y publicaba
`cobertura_diccionario` 100.0 %, exhaustividad 81.7 % y acierto de signo
82.5 % con codigo de salida 0.

Es una prueba de texto, no de importaciones, a proposito: `open()` no es la
unica forma de leer un archivo, y lo que se quiere atrapar es que alguien
teclee el nombre.

Lo que NO atrapa, y es deliberado
=================================

Protege contra el error honesto, no contra la evasion. Un nombre partido en
dos cadenas y concatenado, una ruta que llega por `GRN_DATOS` o por un archivo
de configuracion, un `glob` sobre `*.xlsx` o un `pathlib` armado con variables
pasan sin que la prueba lo note, y convertirla en un analisis de flujo no vale
lo que cuesta: quien quiera evadirla puede, y quien no quiere, teclea el
nombre. Mira solo `.py`: cuadernos, `.sh` y `.ps1` quedan fuera. No vigila
`grn_etl/` ni los scripts de la raiz, que no producen filas del pipeline. Los
`test_*` quedan exentos. Si revisa archivos que git ignora, como
`etapa2/para_colab/`, y es a proposito: lo que se quiere atrapar es el script
local que alguien corre hoy, este o no en el historial.
"""

import ast
import os
import re
import tempfile
import unittest

DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIRECTORIO)

# Los paquetes que esta prueba vigila. Al sacar modulos de `etapa2/` hacia
# `grn_bronce/` la prueba dejaria de verlos, y el guardian se debilitaria sin
# que nada avisara: exactamente el modo de fallo que vino a impedir. Cualquier
# paquete nuevo que produzca filas del pipeline se agrega aqui.
VIGILADOS = ("etapa2", "grn_bronce", "grn_comun")

# Los nombres que no se pueden teclear, cada uno con la expresion que lo
# atrapa. Sin distinguir mayusculas: `ORO_PSEUDOMONAS` como constante o
# `Grn_Experimental.xlsx` nombran el mismo archivo, y la version anterior de
# esta prueba prometia atraparlos y no lo hacia. `datos/validacion` se busca
# como componente de ruta --`datos`, separadores, `validacion`; o `validacion`
# entre comillas o diagonales-- para que la «validacion cruzada» de un texto
# de ayuda no dispare la guarda. El `_` entra entre los separadores porque
# `DATOS_VALIDACION` es la forma honesta de escribirlo como constante.
PROTEGIDOS = {
    "oro_pseudomonas": re.compile(r"oro_pseudomonas", re.I),
    "auditoria_signo": re.compile(r"auditoria_signo", re.I),
    "GRN_experimental": re.compile(r"grn_experimental", re.I),
    "datos/validacion": re.compile(
        r"datos[\W_]{1,8}validacion|[\"'/\\]validacion[\"'/\\]", re.I),
}

# §0.4 nombra a los dos evaluadores. Las pruebas quedan fuera de la
# prohibicion por el mismo motivo por el que existen: comprobar que la
# evaluacion se hace bien exige abrir lo que la evaluacion abre.
LISTA_BLANCA = {
    # `verificar_oro.py` comprueba que las oraciones del oro existan donde la
    # fila dice. Entra a la lista blanca porque NO es parte del pipeline: nadie
    # lo importa, no produce nada que el pipeline consuma, y su unica salida es
    # un conteo por pantalla. Verificar el oro exige abrirlo, igual que
    # evaluarlo. Si algun dia otro modulo lo importa, esto hay que revisarlo.
    # `evaluar_cobertura_bronce.py` mide cuantas relaciones del oro
    # llegan a coocurrir en una oracion candidata del paso 1. Entra por
    # la misma razon que los otros dos y con la misma condicion: es un
    # EVALUADOR. Nadie lo importa, no produce ningun archivo que el
    # pipeline consuma, y su salida es un informe. Vive aqui y no en
    # grn_bronce precisamente porque el paquete bronce no puede abrir el
    # oro: si la referencia entrara en la logica que extrae, las cifras
    # dejarian de medir lo que el pipeline encuentra.
    "oro_pseudomonas": {"evaluar_oro.py", "verificar_oro.py",
                        "evaluar_cobertura_bronce.py"},
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
    # La base curada y su carpeta todavia no tienen a nadie en la lista
    # blanca: el cargador que decida el punto 11 del plan entra aqui cuando
    # exista, no antes, porque la prueba de los archivos fantasma exige que
    # cada nombre de la lista exista.
    "GRN_experimental": set(),
    "datos/validacion": set(),
}

# Los scripts del pipeline propiamente dicho. Ninguno puede nombrar los
# archivos protegidos, y se listan explicitamente para que agregar un script
# nuevo no herede el permiso por accidente.
DEL_PIPELINE = ("construir_diccionario.py", "extraer_pares.py",
                "clasificar.py", "red.py", "lexico.py", "texto.py",
                "particionar.py", "barrido.py", "diagnostico.py")


def _ruta_de(nombre):
    """Donde vive un script del pipeline, sin que importe que paquete lo tiene.

    Los modulos se estan mudando de `etapa2/` a `grn_bronce/`; esta prueba no
    tiene por que enterarse de cada paso de esa mudanza, solo de que el archivo
    siga existiendo en alguno de los paquetes vigilados.
    """
    for paquete in VIGILADOS:
        ruta = os.path.join(RAIZ, paquete, nombre)
        if os.path.exists(ruta):
            return ruta
    return os.path.join(DIRECTORIO, nombre)


def _fuentes(raiz=RAIZ, vigilados=VIGILADOS):
    """(ruta relativa, nombre, texto) de cada `.py` de los paquetes vigilados.

    Entra en las subcarpetas: `etapa2/para_colab/` y `etapa2/evaluacion/`
    tienen scripts, y con `os.listdir` la prueba no los veia. Se saltan
    `__pycache__` y las carpetas ocultas. Se lee con `errors="replace"`: los
    nombres protegidos son ASCII, y un archivo ajeno mal codificado no tiene
    por que tumbar la guarda.
    """
    for paquete in vigilados:
        carpeta = os.path.join(raiz, paquete)
        if not os.path.isdir(carpeta):
            continue
        for actual, subcarpetas, nombres in os.walk(carpeta):
            subcarpetas[:] = sorted(
                s for s in subcarpetas
                if s != "__pycache__" and not s.startswith("."))
            for nombre in sorted(nombres):
                if not nombre.endswith(".py"):
                    continue
                ruta = os.path.join(actual, nombre)
                with open(ruta, encoding="utf-8", errors="replace") as f:
                    texto = f.read()
                yield os.path.relpath(ruta, raiz), nombre, texto


def _es_prueba(nombre):
    return nombre.startswith("test_")


def _en_primer_nivel(relativa):
    """La lista blanca vale para `etapa2/evaluar_oro.py`, no para un archivo
    con el mismo nombre metido en una subcarpeta: el permiso es del archivo
    concreto, no del nombre."""
    return relativa.count(os.sep) == 1


class PruebasFrontera(unittest.TestCase):

    def test_el_oro_no_se_nombra_fuera_de_la_lista_blanca(self):
        intrusos = []
        for relativa, nombre, texto in _fuentes():
            if _es_prueba(nombre):
                continue
            for protegido, patron in PROTEGIDOS.items():
                permitido = (_en_primer_nivel(relativa)
                             and nombre in LISTA_BLANCA[protegido])
                if patron.search(texto) and not permitido:
                    intrusos.append("%s nombra %s" % (relativa, protegido))
        self.assertEqual(
            [], intrusos,
            "Estos archivos nombran el patron de oro, la auditoria de signo o "
            "la base curada fuera de la lista blanca de la seccion 0.4 del "
            "contrato. Si la referencia entra al pipeline, la evaluacion la "
            "mide contra si misma: %s" % intrusos)

    def test_la_lista_blanca_no_tiene_archivos_fantasma(self):
        """Una lista blanca que nombre un archivo inexistente es un permiso
        sin dueno: el dia que alguien cree ese archivo, hereda el permiso."""
        for protegido, archivos in LISTA_BLANCA.items():
            for archivo in archivos:
                self.assertTrue(
                    os.path.exists(_ruta_de(archivo)),
                    "La lista blanca de %s nombra %s, que no existe."
                    % (protegido, archivo))

    def test_los_scripts_del_pipeline_existen_y_estan_limpios(self):
        """Si un script del pipeline se renombra, esta prueba tiene que
        enterarse: si no, dejaria de vigilarlo en silencio."""
        for nombre in DEL_PIPELINE:
            ruta = _ruta_de(nombre)
            self.assertTrue(os.path.exists(ruta),
                            "%s no existe; actualiza DEL_PIPELINE." % nombre)
            with open(ruta, encoding="utf-8") as f:
                texto = f.read()
            for protegido, patron in PROTEGIDOS.items():
                self.assertIsNone(
                    patron.search(texto),
                    "%s nombra %s. Ningun script del pipeline puede leer la "
                    "referencia con la que se evalua." % (nombre, protegido))

    def test_auditar_signo_solo_escribe(self):
        """`auditar_signo.py` esta en la lista blanca como PRODUCTOR.

        Se comprueba lo que justifica el permiso: que el nombre aparece solo
        en el docstring del modulo y como valor por omision de `--salida`. En
        cuanto alguien lo use para leer, esta prueba falla y hay que volver a
        decidir el permiso a la vista del caso concreto.
        """
        ruta = _ruta_de("auditar_signo.py")
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
        patron = PROTEGIDOS["auditoria_signo"]
        malas = []
        for numero, linea in enumerate(texto.splitlines(), 1):
            if not patron.search(linea):
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
        for relativa, nombre, texto in _fuentes():
            if nombre == "auditar_signo.py":
                continue
            if re.search(r"^\s*(import\s+auditar_signo|from\s+auditar_signo\s)",
                         texto, re.M):
                importadores.append(relativa)
        self.assertEqual([], importadores,
                         "Estos modulos importan auditar_signo.py: %s"
                         % importadores)

    def test_la_guarda_atrapa_variantes(self):
        """Las formas en que alguien teclearia un nombre protegido sin
        querer, y las frases parecidas que no deben disparar la guarda."""
        deben = ["ORO_PSEUDOMONAS", "Grn_Experimental.xlsx",
                 "Auditoria_Signo.tsv", "DATOS_VALIDACION",
                 'os.path.join("datos", "validacion")',
                 r"datos\validacion", "DATOS/VALIDACION/", "'validacion'"]
        no_deben = ["validacion cruzada", '"validacion cruzada (--folds 5)"',
                    "evidencia_experimental", "GRN_DATOS"]

        def atrapa(cadena):
            return any(p.search(cadena) for p in PROTEGIDOS.values())

        self.assertEqual([], [c for c in deben if not atrapa(c)],
                         "Estas formas del nombre pasan sin que la guarda las "
                         "vea.")
        self.assertEqual([], [c for c in no_deben if atrapa(c)],
                         "Estas frases inocentes disparan la guarda.")

    def test_fuentes_recorre_subcarpetas(self):
        """Lo que motivo el cambio: un `.py` en una subcarpeta del paquete
        tiene que aparecer, y `__pycache__` y las carpetas ocultas no."""
        with tempfile.TemporaryDirectory() as raiz:
            paquete = os.path.join(raiz, "paq")
            os.makedirs(os.path.join(paquete, "sub", "__pycache__"))
            os.makedirs(os.path.join(paquete, ".oculta"))
            for rel in ("arriba.py",
                        os.path.join("sub", "abajo.py"),
                        os.path.join("sub", "__pycache__", "cache.py"),
                        os.path.join(".oculta", "oculto.py"),
                        os.path.join("sub", "datos.txt")):
                with open(os.path.join(paquete, rel), "w",
                          encoding="utf-8") as f:
                    f.write("# nada\n")
            vistos = [rel for rel, _, _ in _fuentes(raiz, ("paq",))]
        self.assertEqual([os.path.join("paq", "arriba.py"),
                          os.path.join("paq", "sub", "abajo.py")], vistos)
        self.assertTrue(_en_primer_nivel(vistos[0]))
        self.assertFalse(_en_primer_nivel(vistos[1]))

    def test_el_diccionario_no_declara_procedencia_de_oro(self):
        """`oro` no es un valor valido de la columna `fuente` (§2).

        Es la misma comprobacion que hace `construir_diccionario.py` antes de
        escribir, repetida aqui sobre el archivo versionado: la del script
        protege la corrida, esta protege el repositorio de que alguien edite
        el TSV a mano.
        """
        ruta = _ruta_de("genes_pao1.tsv")
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
