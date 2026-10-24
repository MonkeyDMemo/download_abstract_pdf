"""La frontera de grn_ouroboros, por AST y por texto.

- Nadie fuera del paquete importa Strands, Strands Evals, `ollama`, pydantic
  ni el paquete mismo. Dentro, esas cuatro solo se importan dentro de una
  función: el paquete tiene que importarse sin ellas.
- Todo el paquete se lee con la gramática de Python 3.8, y ninguna anotación
  usa lo que el 3.8 evalúa y no entiende (`list[str]`, `str | None`).
- `print` solo en `cli.py`.
- El prompt no comparte 40 caracteres seguidos con las oraciones candidatas
  del corpus, con la hoja de la calibración ni con los ejemplos entre
  comillas de la rúbrica. Un prompt con oraciones de la hoja infla el acuerdo
  que se mide con ella, y uno con oraciones del corpus puede llevar una de
  las tandas.
- Los requisitos del servidor y el extra `[ouroboros]` de `pyproject.toml`
  fijan las mismas versiones.

Atrapa el descuido, no la evasión: un import armado con cadenas concatenadas
pasa, como en `etapa2/test_contaminacion.py`.

    python -m unittest grn_ouroboros.test_frontera
"""

import ast
import csv
import glob
import io
import os
import re
import unittest

from grn_ouroboros import agente

PAQUETE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PAQUETE)
NOMBRE = os.path.basename(PAQUETE)

TERCEROS = ("strands", "strands_evals", "ollama", "pydantic")

# Lo que el recorrido no mira: las carpetas ocultas (los .venv*, .claude con
# sus worktrees, .git), las salidas y los datos, que no son código del
# proyecto, y lo que dejan pip y Python. Un worktree dentro de .claude es otra
# copia de todo el repositorio, con su propio grn_ouroboros.
EXCLUIDAS = ("salidas", "datos", "build", "dist", "venv", "__pycache__",
             "node_modules")

CARPETA_CORRIDA4 = os.path.join(RAIZ, "salidas", "flujo", "corrida4_run22")
PATRON_CANDIDATAS = "bronce_identificacion_corrida4_*_oraciones_candidatas.csv"
RUTA_HOJA_CALIBRACION = os.path.join(RAIZ, "docs", "calibracion-hoja.csv")
RUTA_RUBRICA = os.path.join(RAIZ, "docs", "rubrica-anotacion.md")
LARGO = 40

GENERICOS = ("list", "dict", "tuple", "set", "frozenset", "type")


def _excluida(nombre):
    return (nombre.startswith(".") or nombre in EXCLUIDAS
            or nombre.endswith(".egg-info"))


def _fuentes(raiz=RAIZ):
    """(ruta relativa, texto) de cada .py del repositorio."""
    for actual, carpetas, archivos in os.walk(raiz):
        carpetas[:] = sorted(c for c in carpetas if not _excluida(c))
        for nombre in sorted(archivos):
            if nombre.endswith(".py"):
                ruta = os.path.join(actual, nombre)
                with io.open(ruta, encoding="utf-8", errors="replace") as f:
                    yield os.path.relpath(ruta, raiz), f.read()


def _del_paquete(relativa):
    return relativa.split(os.sep, 1)[0] == NOMBRE


def _raiz_de(nombre):
    return (nombre or "").split(".", 1)[0]


def _importados(arbol):
    """(línea, módulo) de cada import del árbol, también los de
    `importlib.import_module("x")` y `__import__("x")` con cadena fija."""
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                yield nodo.lineno, alias.name
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0:
                yield nodo.lineno, nodo.module or ""
        elif isinstance(nodo, ast.Call) and nodo.args:
            funcion = nodo.func
            nombre = (funcion.attr if isinstance(funcion, ast.Attribute)
                      else getattr(funcion, "id", ""))
            primero = nodo.args[0]
            if (nombre in ("import_module", "__import__")
                    and isinstance(primero, ast.Constant)
                    and isinstance(primero.value, str)):
                yield nodo.lineno, primero.value


def _imports_al_cargar(arbol):
    """Los imports que corren al importar el módulo: los que no están dentro
    de una función. Los del cuerpo de una clase también corren."""
    pendientes = list(ast.iter_child_nodes(arbol))
    while pendientes:
        nodo = pendientes.pop()
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda)):
            continue
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                yield nodo.lineno, alias.name
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
            yield nodo.lineno, nodo.module or ""
        pendientes.extend(ast.iter_child_nodes(nodo))


def _anotaciones(arbol):
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = nodo.args
            argumentos = (getattr(a, "posonlyargs", []) + a.args
                          + a.kwonlyargs + [x for x in (a.vararg, a.kwarg)
                                            if x is not None])
            for arg in argumentos:
                if arg.annotation is not None:
                    yield arg.annotation
            if nodo.returns is not None:
                yield nodo.returns
        elif isinstance(nodo, ast.AnnAssign):
            yield nodo.annotation


def _anotacion_moderna(anotacion):
    for nodo in ast.walk(anotacion):
        if (isinstance(nodo, ast.Subscript)
                and isinstance(nodo.value, ast.Name)
                and nodo.value.id in GENERICOS):
            return True
        if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.BitOr):
            return True
    return False


def _futuro_de_anotaciones(arbol):
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names)
               for n in arbol.body)


# ------------------------------------------------- 40 caracteres seguidos

def normalizar(texto):
    """Sin el formato de Markdown (`*`, `` ` ``) y con los espacios
    colapsados: una oración pegada al prompt con cursivas o partida en dos
    líneas sigue siendo la misma."""
    return re.sub(r"\s+", " ", (texto or "").replace("*", "")
                  .replace("`", "")).strip()


class Ventanas(object):
    """Los tramos de LARGO y de la mitad de LARGO de un texto, para buscar
    si otro comparte LARGO caracteres seguidos con él.

    Para no probar cada posición del otro texto: un tramo común de 40
    contiene uno de 20 que empieza en una posición múltiplo de 21, porque
    entre sus primeras 21 posiciones siempre hay una. Se buscan esos de 20
    entre todos los del texto, y solo donde aparece uno se confirma el de 40.
    Con 17 MB de candidatas, es la diferencia entre segundos y un minuto.
    """

    def __init__(self, texto, largo=LARGO):
        t = normalizar(texto)
        self.largo = largo
        self.medio = largo // 2
        self.paso = largo - self.medio + 1
        self.largas = set(t[i:i + largo] for i in range(len(t) - largo + 1))
        self.medias = set(t[i:i + self.medio]
                          for i in range(len(t) - self.medio + 1))

    def comparte(self, otro):
        t = normalizar(otro)
        for p in range(0, len(t) - self.medio + 1, self.paso):
            if t[p:p + self.medio] not in self.medias:
                continue
            for d in range(self.paso):
                if 0 <= p - d and t[p - d:p - d + self.largo] in self.largas:
                    return True
        return False


def _oraciones_csv(ruta):
    with io.open(ruta, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            yield fila.get("oracion") or ""


def ejemplos_de_la_rubrica(ruta=RUTA_RUBRICA):
    """Los ejemplos entre comillas de la rúbrica: lo que va entre «» (aunque
    cruce un salto de línea) y cada bloque de citas (`> ...`)."""
    with io.open(ruta, encoding="utf-8") as f:
        texto = f.read()
    ejemplos = re.findall(r"«([^»]+)»", texto)
    bloque = []
    for linea in texto.splitlines() + [""]:
        if linea.lstrip().startswith(">"):
            bloque.append(linea.lstrip()[1:])
        elif bloque:
            ejemplos.append(" ".join(bloque))
            bloque = []
    return ejemplos


class PruebasImportaciones(unittest.TestCase):

    def test_nadie_de_fuera_importa_terceros_ni_el_paquete(self):
        prohibidos = set(TERCEROS) | {NOMBRE}
        intrusos, vistos = [], 0
        for relativa, texto in _fuentes():
            if _del_paquete(relativa):
                continue
            vistos += 1
            try:
                arbol = ast.parse(texto)
            except SyntaxError as e:
                intrusos.append("%s no se puede leer (línea %s)"
                                % (relativa, e.lineno))
                continue
            for linea, modulo in _importados(arbol):
                if _raiz_de(modulo) in prohibidos:
                    intrusos.append("%s:%d importa %s"
                                    % (relativa, linea, modulo))
        self.assertGreater(vistos, 50, "el recorrido no vio el repositorio")
        self.assertEqual(intrusos, [])

    def test_dentro_del_paquete_solo_dentro_de_funciones(self):
        al_cargar = []
        for relativa, texto in _fuentes(PAQUETE):
            for linea, modulo in _imports_al_cargar(ast.parse(texto)):
                if _raiz_de(modulo) in TERCEROS:
                    al_cargar.append("%s:%d importa %s"
                                     % (relativa, linea, modulo))
        self.assertEqual(al_cargar, [])

    def test_la_guarda_ve_los_imports(self):
        codigo = ("import os\nfrom strands import Agent\n"
                  "def f():\n    import ollama\n"
                  "class C:\n    import pydantic\n"
                  "importlib.import_module('strands_evals.types')\n")
        arbol = ast.parse(codigo)
        self.assertEqual([m for _l, m in _importados(arbol)],
                         ["os", "strands", "ollama", "pydantic",
                          "strands_evals.types"])
        self.assertEqual(sorted(m for _l, m in _imports_al_cargar(arbol)),
                         ["os", "pydantic", "strands"])


class PruebasPython38(unittest.TestCase):

    def test_todo_el_paquete_parsea_con_la_gramatica_de_3_8(self):
        malos, vistos = [], 0
        for relativa, texto in _fuentes(PAQUETE):
            vistos += 1
            try:
                ast.parse(texto, filename=relativa, feature_version=(3, 8))
            except SyntaxError as e:
                malos.append("%s:%s" % (relativa, e.lineno))
        self.assertGreater(vistos, 10)
        self.assertEqual(malos, [])

    def test_ninguna_anotacion_que_el_3_8_no_evalua(self):
        """`feature_version` no las atrapa: son gramática válida, y truenan
        al definir la función."""
        malas = []
        for relativa, texto in _fuentes(PAQUETE):
            arbol = ast.parse(texto)
            if _futuro_de_anotaciones(arbol):
                continue
            for anotacion in _anotaciones(arbol):
                if _anotacion_moderna(anotacion):
                    malas.append("%s:%d" % (relativa, anotacion.lineno))
        self.assertEqual(malas, [])

    def test_la_guarda_de_anotaciones(self):
        arbol = ast.parse("def f(a: list[str], b: 'x', c: int | None) -> "
                          "dict:\n    pass\n")
        self.assertEqual([_anotacion_moderna(a) for a in _anotaciones(arbol)],
                         [True, False, True, False])

    def test_print_solo_en_cli(self):
        con_print = []
        for relativa, texto in _fuentes(PAQUETE):
            nombre = os.path.basename(relativa)
            if nombre == "cli.py" or nombre.startswith("test_"):
                continue
            for nodo in ast.walk(ast.parse(texto)):
                if (isinstance(nodo, ast.Call)
                        and getattr(nodo.func, "id", "") == "print"):
                    con_print.append("%s:%d" % (relativa, nodo.lineno))
        self.assertEqual(con_print, [])


class PruebasPrompt(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ventanas = Ventanas(agente.leer_prompt())

    def test_la_busqueda_encuentra_lo_que_comparte(self):
        prompt = agente.leer_prompt()
        trozo = normalizar(prompt)[1000:1000 + LARGO]
        self.assertTrue(self.ventanas.comparte("Al principio. " + trozo
                                               + " y al final."))
        self.assertFalse(self.ventanas.comparte(trozo[:LARGO - 1]))
        # Partido en dos líneas en un espacio, y con cursivas, sigue
        # contando.
        i = trozo.index(" ", 5)
        self.assertTrue(self.ventanas.comparte(
            trozo[:i] + "\n  " + trozo[i + 1:].replace(" ", " *", 1)))

    def test_ni_las_oraciones_candidatas_del_corpus(self):
        rutas = sorted(glob.glob(os.path.join(CARPETA_CORRIDA4,
                                              PATRON_CANDIDATAS)))
        if not rutas:
            self.skipTest("no está %s en salidas/flujo/corrida4_run22/: el "
                          "corpus del bronce no vive en esta copia del "
                          "repositorio" % PATRON_CANDIDATAS)
        vistas, comparten = set(), 0
        for ruta in rutas:
            for oracion in _oraciones_csv(ruta):
                if oracion in vistas:
                    continue
                vistas.add(oracion)
                if self.ventanas.comparte(oracion):
                    comparten += 1
        self.assertGreater(len(vistas), 1000)
        # Solo el conteo: el mensaje no puede llevar la oración.
        self.assertEqual(comparten, 0, "%d oraciones candidatas comparten %d "
                                       "caracteres con el prompt"
                         % (comparten, LARGO))

    def test_ni_la_hoja_de_la_calibracion(self):
        oraciones = list(_oraciones_csv(RUTA_HOJA_CALIBRACION))
        self.assertEqual(len(oraciones), 27)
        self.assertEqual([i for i, o in enumerate(oraciones, 1)
                          if self.ventanas.comparte(o)], [])

    def test_ni_los_ejemplos_de_la_rubrica(self):
        ejemplos = ejemplos_de_la_rubrica()
        self.assertGreater(len(ejemplos), 10)
        self.assertEqual([i for i, e in enumerate(ejemplos, 1)
                          if self.ventanas.comparte(e)], [])


class PruebasRequisitos(unittest.TestCase):

    def test_el_servidor_y_el_extra_fijan_lo_mismo(self):
        with io.open(os.path.join(PAQUETE, "requisitos-servidor.txt"),
                     encoding="utf-8") as f:
            requisitos = set(l.strip() for l in f
                             if l.strip() and not l.lstrip().startswith("#"))
        with io.open(os.path.join(RAIZ, "pyproject.toml"),
                     encoding="utf-8") as f:
            # Hasta el «]» que cierra la línea: el de «[ollama]» no la cierra.
            bloque = re.search(r"^ouroboros\s*=\s*\[(.*?)\]\s*$", f.read(),
                               re.M | re.S)
        self.assertIsNotNone(bloque, "pyproject.toml no tiene el extra")
        extra = re.findall(r'"([^"]+)"', bloque.group(1))
        self.assertEqual(set(r.split(";")[0].strip() for r in extra),
                         requisitos)
        self.assertTrue(all("python_version >= '3.10'" in r for r in extra))
        self.assertTrue(all("==" in r for r in requisitos))


if __name__ == "__main__":
    unittest.main()
