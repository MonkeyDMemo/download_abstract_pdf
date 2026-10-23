# -*- coding: utf-8 -*-
"""Pruebas del orquestador `flujo.py`, con pasos falsos.

La que no puede faltar: **la segunda corrida no repite nada**. Es la promesa
del flujo, la misma que la del paso 0 con `efetch`: correr dos veces seguidas
no gasta CPU ni vuelve a escribir archivos. Y la contraria: cambiar una
entrada rehace ese paso y los que dependen de él.

    python -m unittest discover .
"""

import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

import flujo
from grn_comun import proceso


class _Pasos(object):
    """Un `_plan` falso: `bronce` copia una entrada a un CSV de candidatas y
    `pares` copia ese CSV a `pares.jsonl`. Cada ejecución deja una marca en un
    archivo, para contar cuántas veces corrió de verdad cada paso."""

    def __init__(self, carpeta_tmp):
        self.entrada = os.path.join(carpeta_tmp, "entrada.txt")
        self.marcas = os.path.join(carpeta_tmp, "marcas.txt")
        with io.open(self.entrada, "w", encoding="utf-8") as f:
            f.write("uno")
        self.fallar = set()
        self.opcional_falla = False
        self.vistos = []

    def corridas(self, paso):
        if not os.path.exists(self.marcas):
            return 0
        with io.open(self.marcas, encoding="utf-8") as f:
            return sum(1 for l in f if l.strip() == paso)

    def _cmd(self, paso, origen, destino):
        codigo = ("import shutil, sys; "
                  "open(%r, 'a').write(%r + '\\n'); "
                  "shutil.copyfile(%r, %r)" % (self.marcas, paso, origen,
                                               destino))
        if paso in self.fallar:
            codigo = "import sys; print('se rompió'); sys.exit(4)"
        return [sys.executable, "-c", codigo]

    def __call__(self, ctx, paso):
        if paso == "bronce":
            destino = ctx.ruta("bronce_identificacion_corrida%d_20990101_"
                               "oraciones_candidatas.csv" % ctx.corrida)
            return {"comandos": [(self._cmd("bronce", self.entrada, destino),
                                  (0,), False)],
                    "entradas": [self.entrada], "parametros": {},
                    "salidas": "candidatas"}
        if paso == "pares":
            return {"comandos": [(self._cmd("pares", ctx.candidatas(),
                                            ctx.ruta("pares.jsonl")),
                                  (0,), False)],
                    "entradas": [ctx.candidatas()], "parametros": {},
                    "salidas": [ctx.ruta("pares.jsonl")]}
        if paso == "operones":
            # Como el de verdad: sin la bandera no corre nada y solo sella la
            # huella; con ella, regenera.
            destino = os.path.join(os.path.dirname(self.entrada),
                                   "operones_base.tsv")
            comandos = []
            if ctx.rehacer_operones:
                comandos = [(self._cmd("operones", self.entrada, destino),
                             (0,), False)]
            return {"comandos": comandos, "entradas": [self.entrada],
                    "parametros": {"rehacer": bool(ctx.rehacer_operones)},
                    "aviso_si_cambian": "no se regeneró",
                    "salidas": [destino]}
        if paso == "red":
            self.vistos.append(dict(datos=ctx.datos, python=ctx.python_bert))
            viejo = ctx.ruta("evaluacion_vieja.json")
            opcional = [sys.executable, "-c",
                        "import sys; sys.exit(%d)" % (1 if self.opcional_falla
                                                      else 0)]
            return {"comandos": [(self._cmd("red", ctx.ruta("pares.jsonl"),
                                            ctx.ruta("red.tsv")), (0,), False),
                                 (opcional, (0,), True)],
                    "entradas": [ctx.ruta("pares.jsonl")], "parametros": {},
                    "borrar_antes": [viejo],
                    "salidas": [ctx.ruta("red.tsv")]}
        return {"omitir": "no se prueba"}


class PruebasFlujo(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pasos = _Pasos(self.tmp.name)
        p = mock.patch.object(flujo, "_plan", self.pasos)
        p.start()
        self.addCleanup(p.stop)
        self.salida = os.path.join(self.tmp.name, "flujo")
        # El de por omisión: su carpeta se llama `corrida4_run22`. El plan es
        # falso, así que no hace falta que el checkpoint exista.
        self.modelo = flujo.MODELO_POR_OMISION

    def correr(self, pasos=("bronce", "pares"), **kw):
        return flujo.correr(corrida=4, pasos=list(pasos),
                            salida=self.salida, modelo=self.modelo,
                            sin_reusar=True, **kw)

    def estado(self):
        with io.open(os.path.join(self.salida, "corrida4_run22",
                                  "estado.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_la_segunda_corrida_no_repite_nada(self):
        r = self.correr()
        self.assertEqual(r["pasos"], {"bronce": "ok", "pares": "ok"})
        r = self.correr()
        self.assertEqual(r["pasos"], {"bronce": "saltado",
                                      "pares": "saltado"})
        self.assertEqual(self.pasos.corridas("bronce"), 1)
        self.assertEqual(self.pasos.corridas("pares"), 1)

    def test_cambiar_una_entrada_rehace_ese_paso_y_los_de_abajo(self):
        self.correr()
        with io.open(self.pasos.entrada, "w", encoding="utf-8") as f:
            f.write("dos")
        r = self.correr()
        self.assertEqual(r["pasos"], {"bronce": "ok", "pares": "ok"})
        self.assertEqual(self.pasos.corridas("pares"), 2)

    def test_forzar_rehace_solo_lo_pedido(self):
        self.correr()
        r = self.correr(forzar=["pares"])
        self.assertEqual(r["pasos"], {"bronce": "saltado", "pares": "ok"})

    def test_rehacer_operones_rehace_tambien_la_segunda_vez(self):
        """Antes la segunda corrida con la bandera y las mismas entradas
        salía «ya hecho»: la base y los crudos que lee el paso no se pueden
        huellear, y hacía falta además `--forzar operones` (pendiente 4.10)."""
        self.correr(pasos=["operones"], rehacer_operones=True)
        r = self.correr(pasos=["operones"], rehacer_operones=True)

        self.assertEqual(r["pasos"], {"operones": "ok"})
        self.assertEqual(self.pasos.corridas("operones"), 2)

    def test_sin_la_bandera_el_paso_de_operones_se_salta(self):
        destino = os.path.join(self.tmp.name, "operones_base.tsv")
        with io.open(destino, "w", encoding="utf-8") as f:
            f.write("x")
        self.correr(pasos=["operones"])
        r = self.correr(pasos=["operones"])

        self.assertEqual(r["pasos"], {"operones": "saltado"})
        self.assertEqual(self.pasos.corridas("operones"), 0)

    def test_sin_la_bandera_avisa_si_cambiaron_sus_entradas(self):
        destino = os.path.join(self.tmp.name, "operones_base.tsv")
        with io.open(destino, "w", encoding="utf-8") as f:
            f.write("x")
        self.correr(pasos=["operones"])
        with io.open(self.pasos.entrada, "w", encoding="utf-8") as f:
            f.write("dos")
        self.correr(pasos=["operones"])

        self.assertIn("AVISO: cambió", self.log())
        self.assertIn("no se regeneró", self.log())

    def test_el_aviso_se_repite_hasta_que_se_regenera(self):
        """Avisar una sola vez no bastaba: la corrida que avisaba guardaba las
        entradas nuevas, y la siguiente daba el paso por hecho con la base
        vieja. Si nadie leía esa corrida, nadie se enteraba."""
        destino = os.path.join(self.tmp.name, "operones_base.tsv")
        with io.open(destino, "w", encoding="utf-8") as f:
            f.write("x")
        self.correr(pasos=["operones"])
        with io.open(self.pasos.entrada, "w", encoding="utf-8") as f:
            f.write("dos")
        self.correr(pasos=["operones"])
        avisos = self.log().count("AVISO: cambió")

        self.correr(pasos=["operones"])
        self.assertEqual(self.log().count("AVISO: cambió"), avisos + 1)

        self.correr(pasos=["operones"], rehacer_operones=True)
        avisos = self.log().count("AVISO: cambió")
        self.correr(pasos=["operones"])
        r = self.correr(pasos=["operones"])
        self.assertEqual(r["pasos"], {"operones": "saltado"})
        self.assertEqual(self.log().count("AVISO: cambió"), avisos)

    def test_rehacer_operones_sin_el_paso_es_error_de_uso(self):
        with self.assertRaises(ValueError):
            self.correr(pasos=["bronce"], rehacer_operones=True)

    def test_una_salida_borrada_se_rehace(self):
        self.correr()
        os.remove(os.path.join(self.salida, "corrida4_run22", "pares.jsonl"))
        r = self.correr()
        self.assertEqual(r["pasos"]["pares"], "ok")

    def test_un_paso_que_falla_detiene_y_queda_escrito(self):
        self.pasos.fallar.add("pares")
        with self.assertRaises(flujo.ErrorFlujo) as ctx:
            self.correr()
        self.assertIn("se rompió", str(ctx.exception))
        estado = self.estado()
        self.assertEqual(estado["pasos"]["bronce"]["estatus"], "ok")
        self.assertEqual(estado["pasos"]["pares"]["estatus"], "error")
        self.assertFalse(os.path.exists(os.path.join(
            self.salida, "corrida4_run22", ".flujo.lock")))

    def test_cancelar_antes_de_empezar(self):
        detener = threading.Event()
        detener.set()
        with self.assertRaises(proceso.Cancelado):
            self.correr(detener=detener)
        self.assertEqual(self.pasos.corridas("bronce"), 0)

    def test_el_candado_impide_dos_corridas_sobre_la_misma_carpeta(self):
        carpeta = os.path.join(self.salida, "corrida4_run22")
        os.makedirs(carpeta)
        with io.open(os.path.join(carpeta, ".flujo.lock"), "w") as f:
            f.write("1")
        with self.assertRaises(flujo.ErrorFlujo):
            self.correr()

    def test_un_paso_desconocido_es_error_de_uso(self):
        with self.assertRaises(ValueError):
            flujo.correr(corrida=4, pasos=["nada"], salida=self.salida)

    def test_el_limite_va_en_el_nombre_de_la_carpeta(self):
        r = self.correr(limite=200)
        self.assertEqual(r["carpeta"], "corrida4_run22_limite200")

    def log(self):
        with io.open(os.path.join(self.salida, "corrida4_run22", "flujo.log"),
                     encoding="utf-8") as f:
            return f.read()

    def test_flujo_log_cuenta_tambien_lo_que_se_salto_y_los_errores(self):
        """Antes el archivo solo recibía la salida de los hijos: una segunda
        corrida, toda «ya hecho», no dejaba ni una línea en él."""
        pantalla = []
        self.correr()
        self.correr(log=pantalla.append)
        texto = self.log()
        self.assertEqual(texto.count("ya hecho"), 2)
        self.assertIn("Listo: bronce saltado, pares saltado", texto)
        # Lo que va a pantalla es lo mismo, una vez cada línea.
        self.assertEqual(sum(1 for m in pantalla if "ya hecho" in m), 2)

        self.pasos.fallar.add("pares")
        with self.assertRaises(flujo.ErrorFlujo):
            self.correr(forzar=["pares"])
        texto = self.log()
        self.assertEqual(texto.count("se rompió"), 2)    # salida del hijo y error
        self.assertIn("Falló el paso «pares»", texto)

    def test_una_lista_vacia_de_pasos_no_es_todos(self):
        """El tablero manda la lista de lo marcado; quien desmarcó todo no
        pidió correr los diez pasos."""
        with self.assertRaises(ValueError):
            flujo.correr(corrida=4, pasos=[], salida=self.salida)
        self.assertEqual(self.pasos.corridas("bronce"), 0)

    def test_un_estado_que_no_es_objeto_se_rehace(self):
        carpeta = os.path.join(self.salida, "corrida4_run22")
        os.makedirs(carpeta)
        for basura in ("[1, 2]", "7", '{"pasos": []}'):
            with io.open(os.path.join(carpeta, "estado.json"), "w",
                         encoding="utf-8") as f:
                f.write(basura)
            self.assertEqual(flujo.leer_carpeta(self.salida, "corrida4_run22")
                             ["estado"]["pasos"], {}, basura)
        r = self.correr()
        self.assertEqual(r["pasos"], {"bronce": "ok", "pares": "ok"})

    def test_otro_checkpoint_tiene_su_propia_carpeta(self):
        """Antes todo nombre con `run_22` daba `run22`: el reentrenado con la
        base curada caía en la carpeta del limpio, con su caché."""
        otro = os.path.join(self.tmp.name, "run_22_lr3e-5_ep8_bs16_wu0.1")
        r = flujo.correr(corrida=4, pasos=["bronce"], salida=self.salida,
                         modelo=otro, sin_reusar=True)
        self.assertEqual(r["carpeta"], "corrida4_run_22_lr3e-5_ep8_bs16_wu0_1")

    def test_una_carpeta_de_otro_modelo_no_se_mezcla(self):
        carpeta = os.path.join(self.salida, "corrida4_run22")
        os.makedirs(carpeta)
        with io.open(os.path.join(carpeta, "estado.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"modelo": "otro/checkpoint", "pasos": {}}, f)
        with self.assertRaises(flujo.ErrorFlujo) as ctx:
            self.correr()
        self.assertIn("otro/checkpoint", str(ctx.exception))
        self.assertEqual(self.pasos.corridas("bronce"), 0)
        self.assertFalse(os.path.exists(os.path.join(carpeta, ".flujo.lock")))

    def test_un_opcional_que_fallo_se_reintenta_y_no_deja_salidas_viejas(self):
        carpeta = os.path.join(self.salida, "corrida4_run22")
        os.makedirs(carpeta)
        vieja = os.path.join(carpeta, "evaluacion_vieja.json")
        with io.open(vieja, "w", encoding="utf-8") as f:
            f.write("{}")
        self.pasos.opcional_falla = True
        r = self.correr(pasos=["bronce", "pares", "red"])
        self.assertEqual(r["pasos"]["red"], "ok")
        self.assertFalse(os.path.exists(vieja))
        self.assertTrue(self.estado()["pasos"]["red"]["avisos"])
        # Con el aviso, la corrida siguiente no lo da por hecho.
        self.pasos.opcional_falla = False
        r = self.correr(pasos=["bronce", "pares", "red"])
        self.assertEqual(r["pasos"]["red"], "ok")
        r = self.correr(pasos=["bronce", "pares", "red"])
        self.assertEqual(r["pasos"]["red"], "saltado")

    def test_predicciones_de_otro_pares_jsonl_detienen_la_red(self):
        """Con `--pasos pares,red` se rehacían los pares y la red unía el texto
        nuevo con la predicción del viejo."""
        from grn_comun import procedencia
        carpeta = os.path.join(self.salida, "corrida4_run22")
        os.makedirs(carpeta)
        meta = os.path.join(carpeta, "predicciones_meta.json")
        with io.open(meta, "w", encoding="utf-8") as f:
            json.dump({"huella_pares": "0" * 16}, f)
        with self.assertRaises(flujo.ErrorFlujo) as ctx:
            self.correr(pasos=["bronce", "pares", "red"])
        self.assertIn("biobert", str(ctx.exception))
        # Con las predicciones de este pares.jsonl, sigue.
        with io.open(meta, "w", encoding="utf-8") as f:
            json.dump({"huella_pares": procedencia.huella(
                os.path.join(carpeta, "pares.jsonl"))}, f)
        r = self.correr(pasos=["bronce", "pares", "red"])
        self.assertEqual(r["pasos"]["red"], "ok")

    def test_datos_e_interpretes_relativos_van_absolutos_a_los_pasos(self):
        """Los pasos corren desde la raíz del repositorio: una ruta relativa
        al directorio de quien llamó apuntaba a otro lado."""
        self.correr(pasos=["bronce", "pares", "red"], datos="mis_datos",
                    python_bert=os.path.join("bin", "python"))
        visto = self.pasos.vistos[-1]
        self.assertEqual(visto["datos"], os.path.abspath("mis_datos"))
        self.assertEqual(visto["python"],
                         os.path.abspath(os.path.join("bin", "python")))
        self.assertEqual(flujo._interprete("python3"), "python3")

    def test_lo_de_fuera_del_repositorio_va_absoluto(self):
        fuera = os.path.abspath(os.path.join(flujo.RAIZ, os.pardir, "datos"))
        self.assertEqual(flujo._rel(fuera), fuera.replace(os.sep, "/"))
        self.assertEqual(flujo._rel(os.path.join(flujo.RAIZ, "etapa2",
                                                 "red.py")), "etapa2/red.py")


class PruebasPlanReal(unittest.TestCase):
    """El `_plan` de verdad, sin falsos: las demás pruebas lo reemplazan, y
    así nada vigilaba qué declara cada paso ni el `--sin-cache`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.modelo = os.path.join(self.tmp.name, "modelo")
        os.makedirs(self.modelo)
        for nombre in ("config.json", "label_mapping.json",
                       "pytorch_model.bin", "vocab.txt"):
            with io.open(os.path.join(self.modelo, nombre), "w") as f:
                f.write("x")

    def ctx(self, forzar=(), datos=None, rehacer_operones=False):
        estado = {"archivos": {"candidatas": "c.csv"}, "pasos": {}}
        return flujo._Contexto(self.tmp.name, 4, datos, self.modelo,
                               sys.executable, sys.executable, [], None,
                               rehacer_operones, estado, forzar)

    def _operones(self, existe, **kw):
        """El plan del paso operones con `operones_base.tsv` parchado: el
        archivo no está en git, y sin parche la prueba dependería de la
        máquina."""
        ruta = os.path.join(self.tmp.name, "operones_base.tsv")
        if existe:
            with io.open(ruta, "w", encoding="utf-8") as f:
                f.write("x")
        with mock.patch.object(flujo, "OPERONES_BASE", ruta):
            return flujo._plan(self.ctx(**kw), "operones")

    def test_rehacer_operones_corre_tres_comandos_y_nunca_extraer(self):
        """`extraer` sale a la red y pide credenciales; desde los crudos todo
        es local. `--datos` va antes del subcomando en este CLI."""
        plan = self._operones(False, datos="D", rehacer_operones=True)

        colas = []
        for argv, codigos, opcional in plan["comandos"]:
            i = argv.index("grn_operones.cli")
            self.assertEqual(argv[i + 1:i + 3], ["--datos", "D"])
            colas.append(argv[i + 3:])
            self.assertEqual((codigos, opcional), ((0,), False))
        self.assertEqual(colas, [["reparsear", "--fuente", "todo"], ["curar"],
                                 ["catalogo", "--paso1"]])

    def test_operones_se_omite_sin_archivo_salvo_con_la_bandera(self):
        self.assertIn("omitir", self._operones(False))
        self.assertNotIn("omitir", self._operones(False,
                                                  rehacer_operones=True))
        self.assertEqual(self._operones(True)["comandos"], [])

    def test_operones_declara_sus_entradas_reales(self):
        entradas = [os.path.normpath(e)
                    for e in self._operones(True)["entradas"]]

        for partes in (("grn_bronce", "recursos", "genes_pao1.tsv"),
                       ("grn_bronce", "recursos", "operones_pao1.tsv"),
                       ("grn_bronce", "operones.py"),
                       ("grn_operones", "fuentes.py"),
                       ("grn_operones", "db.py"),
                       ("grn_operones", "cli.py"),
                       ("construir_diccionario", "diccionario_independiente",
                        "cache", "refseq.gff.gz")):
            self.assertIn(self.rel(*partes), entradas)
        self.assertFalse(any(os.path.basename(e).startswith("test_")
                             for e in entradas))

    def rel(self, *partes):
        return os.path.join(flujo.RAIZ, *partes)

    def test_forzar_biobert_es_reclasificar(self):
        argv = flujo._plan(self.ctx(forzar=["biobert"]), "biobert")[
            "comandos"][0][0]
        self.assertIn("--sin-cache", argv)
        argv = flujo._plan(self.ctx(), "biobert")["comandos"][0][0]
        self.assertNotIn("--sin-cache", argv)

    def test_biobert_declara_todo_el_checkpoint(self):
        entradas = flujo._plan(self.ctx(), "biobert")["entradas"]
        for nombre in ("config.json", "label_mapping.json",
                       "pytorch_model.bin", "vocab.txt"):
            self.assertIn(os.path.join(self.modelo, nombre), entradas)
        self.assertIn(self.rel("etapa2", "clasificar.py"),
                      [os.path.normpath(e) for e in entradas])

    def test_evaluar_borra_justo_lo_que_escribe(self):
        """Lo de sus opcionales y su evaluacion.json: si algo falla, no
        quedan a la vista (ni en las cifras del tablero) las de antes."""
        plan = flujo._plan(self.ctx(), "evaluar")
        escritas = set([os.path.join(self.tmp.name, "evaluacion.json")])
        for argv, _codigos, opcional in plan["comandos"]:
            if opcional:
                for flag in ("--salida", "--resumen"):
                    escritas.add(argv[argv.index(flag) + 1])
        self.assertEqual(set(plan["borrar_antes"]), escritas)
        capa = flujo._plan(self.ctx(), "capa")
        self.assertEqual(set(capa["borrar_antes"]), set(capa["salidas"]))

    def test_el_paquete_va_al_final(self):
        """Solo lee la red, pero va al final: si falla, no corta la sintaxis,
        la capa ni la evaluación. Y une por `id_par`: con unos pares rehechos
        y la red vieja, sus nodos saldrían de otro texto."""
        self.assertEqual(flujo.PASOS[-1], "paquete")
        self.assertLess(flujo.PASOS.index("red"), flujo.PASOS.index("paquete"))
        self.assertEqual(flujo.NOMBRES["paquete"], "Paquete de la red")
        self.assertIn("paquete", flujo.LEEN_PREDICCIONES)

    def test_la_red_es_consolidar_con_la_configuracion_por_omision(self):
        """La misma red de `etapa2/red.py`, ahora por `grn_red.cli
        consolidar`: mismas salidas, y cambiar el código de cualquiera de los
        dos la rehace."""
        plan = flujo._plan(self.ctx(), "red")
        argv = plan["comandos"][0][0]
        self.assertEqual(argv[1:], ["-m", "grn_red.cli", "consolidar",
                                    "--carpeta", self.tmp.name])
        entradas = [os.path.normpath(e) for e in plan["entradas"]]
        for nombre in ("predicciones.jsonl", "predicciones_meta.json",
                       "pares.jsonl"):
            self.assertIn(os.path.join(self.tmp.name, nombre), entradas)
        for partes in (("grn_red", "consolidar.py"), ("grn_red", "cli.py"),
                       ("etapa2", "red.py"), ("grn_bronce", "texto.py")):
            self.assertIn(self.rel(*partes), entradas)
        self.assertEqual(plan["parametros"], {})
        self.assertEqual([os.path.basename(s) for s in plan["salidas"]],
                         ["red.tsv", "red_evidencias.tsv", "red_informe.json"])

    def test_la_red_recomendada_va_justo_despues_y_no_toca_red_tsv(self):
        """Une pares y predicciones como la red, lee el catálogo versionado
        (nunca operones_base.tsv) y escribe solo sus archivos; si falla, no
        queda a la vista la de antes."""
        self.assertEqual(flujo.PASOS.index("red_recomendada"),
                         flujo.PASOS.index("red") + 1)
        self.assertIn("red_recomendada", flujo.NOMBRES)
        self.assertIn("red_recomendada", flujo.LEEN_PREDICCIONES)
        plan = flujo._plan(self.ctx(), "red_recomendada")
        argv = plan["comandos"][0][0]
        self.assertEqual(argv[1:], ["-m", "grn_red.cli", "consolidar",
                                    "--carpeta", self.tmp.name,
                                    "--perfil", "recomendado"])
        self.assertEqual([os.path.basename(s) for s in plan["salidas"]],
                         ["red_recomendada.tsv",
                          "red_recomendada_evidencias.tsv",
                          "red_recomendada_informe.json"])
        self.assertEqual(set(plan["borrar_antes"]), set(plan["salidas"]))
        entradas = [os.path.normpath(e) for e in plan["entradas"]]
        for partes in (("grn_bronce", "recursos", "operones_pao1.tsv"),
                       ("grn_red", "consolidar.py"), ("grn_red", "paquete.py"),
                       ("etapa2", "red.py"), ("grn_bronce", "operones.py")):
            self.assertIn(self.rel(*partes), entradas)
        self.assertNotIn(os.path.normpath(flujo.OPERONES_BASE), entradas)
        self.assertEqual(plan["parametros"], {"perfil": "recomendado"})

    def test_el_paquete_declara_sus_entradas_y_borra_lo_que_escribe(self):
        """Cambiar la red, sus evidencias, los pares, el meta del modelo, el
        diccionario, el catálogo versionado o el código lo rehace. Y si
        falla, no queda a la vista el manifiesto de antes, cuyos sha256
        hablarían de otros archivos."""
        plan = flujo._plan(self.ctx(), "paquete")
        argv = plan["comandos"][0][0]
        self.assertEqual(argv[1:], ["-m", "grn_red.cli", "paquete",
                                    "--carpeta", self.tmp.name])
        entradas = [os.path.normpath(e) for e in plan["entradas"]]
        for nombre in ("red.tsv", "red_evidencias.tsv", "red_informe.json",
                       "pares.jsonl", "predicciones_meta.json"):
            self.assertIn(os.path.join(self.tmp.name, nombre), entradas)
        for partes in (("grn_bronce", "recursos", "genes_pao1.tsv"),
                       ("grn_bronce", "recursos", "operones_pao1.tsv"),
                       ("grn_red", "paquete.py"), ("grn_red", "cli.py"),
                       ("grn_red", "__init__.py"), ("etapa2", "red.py"),
                       ("etapa2", "lexico.py"), ("grn_bronce", "operones.py")):
            self.assertIn(self.rel(*partes), entradas)
        # La base de operones lleva datos de BioCyc: no entra a un paquete
        # hecho para salir de la máquina.
        self.assertNotIn(os.path.normpath(flujo.OPERONES_BASE), entradas)
        self.assertFalse(any(os.path.basename(e).startswith("test_")
                             for e in entradas))
        # estado.json se reescribe tras cada paso: como entrada, el paquete no
        # se saltaría nunca. La corrida que toma de ahí va en los parámetros.
        self.assertNotIn(os.path.join(self.tmp.name, "estado.json"), entradas)
        for partes in (("grn_comun", "procedencia.py"),
                       ("grn_comun", "archivos.py")):
            self.assertIn(self.rel(*partes), entradas)
        self.assertEqual(plan["parametros"], {"corrida_bronce": 4})
        self.assertEqual([os.path.basename(s) for s in plan["salidas"]],
                         ["nodos.tsv", "red.graphml", "manifiesto.json"])
        self.assertEqual(set(plan["borrar_antes"]), set(plan["salidas"]))

    def test_cada_paso_declara_el_codigo_que_ejecuta(self):
        ctx = self.ctx()
        esperado = {
            "pares": [("grn_bronce", "texto.py"), ("grn_bronce", "operones.py"),
                      ("etapa2", "extraer_pares.py"), ("etapa2", "lexico.py")],
            "sintaxis": [("etapa2", "extraer_pares.py"), ("etapa2", "lexico.py"),
                         ("grn_bronce", "vocabulario.py"),
                         ("grn_bronce", "texto.py")],
            "evaluar": [("grn_bronce", "operones.py"),
                        ("grn_bronce", "texto.py"),
                        ("grn_bronce", "vocabulario.py"),
                        ("grn_comun", "signo_lexico.py")],
            "paquete": [("grn_red", "paquete.py"), ("etapa2", "red.py"),
                        ("etapa2", "lexico.py"), ("grn_bronce", "operones.py")],
        }
        for paso, archivos in esperado.items():
            entradas = [os.path.normpath(e)
                        for e in flujo._plan(ctx, paso)["entradas"]]
            for partes in archivos:
                self.assertIn(self.rel(*partes), entradas, (paso, partes))

    def test_el_interprete_de_spacy_pedido_se_respeta_o_es_error(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GRN_PYTHON_NLP", None)
            self.assertIsNone(flujo._python_nlp_pedido(None))
            self.assertEqual(flujo._python_nlp_pedido(sys.executable),
                             os.path.abspath(sys.executable))
            with self.assertRaises(flujo.ErrorFlujo):
                flujo._python_nlp_pedido(
                    os.path.join(self.tmp.name, "no", "python"))
            with self.assertRaises(flujo.ErrorFlujo):
                flujo._python_nlp_pedido("python_que_no_existe_xyz")


class PruebasRedDeVerdad(unittest.TestCase):
    """Los pasos «red» y «red_recomendada» con su `_plan` de verdad y sus
    subprocesos, sobre las entradas sintéticas de `grn_red.test_consolidar`:
    la segunda corrida sale toda «saltado», y `red.tsv` es la de
    `etapa2/red.py`."""

    def test_dos_corridas_y_la_segunda_no_repite_nada(self):
        from grn_comun import procedencia
        from grn_red import test_consolidar as tc
        from grn_red.consolidar import _red
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        salida = os.path.join(tmp.name, "flujo")
        os.makedirs(salida)
        carpeta = tc._carpeta(salida, "corrida4_run22")
        meta = os.path.join(carpeta, "predicciones_meta.json")
        with io.open(meta, encoding="utf-8") as f:
            datos = json.load(f)
        datos["huella_pares"] = procedencia.huella(
            os.path.join(carpeta, "pares.jsonl"))
        with io.open(meta, "w", encoding="utf-8") as f:
            json.dump(datos, f)
        with io.open(os.path.join(carpeta, "estado.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"archivos": {"candidatas": "c.csv"}, "pasos": {}}, f)

        def correr():
            return flujo.correr(corrida=4, pasos=["red", "red_recomendada"],
                                salida=salida, modelo=flujo.MODELO_POR_OMISION,
                                sin_reusar=True)

        self.assertEqual(correr()["pasos"], {"red": "ok",
                                             "red_recomendada": "ok"})
        self.assertEqual(correr()["pasos"], {"red": "saltado",
                                             "red_recomendada": "saltado"})
        directa = tc._carpeta(tmp.name, "directa")
        _red.main(["--predicciones", os.path.join(directa, "predicciones.jsonl"),
                   "--pares", os.path.join(directa, "pares.jsonl"),
                   "--salida", os.path.join(directa, "red.tsv"),
                   "--evidencias", os.path.join(directa, "red_evidencias.tsv"),
                   "--informe", os.path.join(directa, "red_informe.json")],
                  log=lambda m: None)
        for nombre in ("red.tsv", "red_evidencias.tsv"):
            with io.open(os.path.join(carpeta, nombre), "rb") as f:
                mio = f.read()
            with io.open(os.path.join(directa, nombre), "rb") as f:
                self.assertEqual(mio, f.read(), nombre)
        self.assertTrue(os.path.isfile(os.path.join(
            carpeta, "red_recomendada.tsv")))


class PruebasArchivosParaElTablero(unittest.TestCase):
    """Los nombres llegan por HTTP: solo hijos directos y extensiones dadas."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = os.path.join(self.tmp.name, "flujo")
        self.carpeta = os.path.join(self.raiz, "corrida4_run22")
        os.makedirs(self.carpeta)
        for nombre in ("capa_pares.csv", "estado.json", "secreto.key"):
            with io.open(os.path.join(self.carpeta, nombre), "w") as f:
                f.write("{}")
        with io.open(os.path.join(self.tmp.name, "fuera.csv"), "w") as f:
            f.write("x")

    def test_un_archivo_listado_se_entrega(self):
        ruta = flujo.ruta_archivo(self.raiz, "corrida4_run22",
                                  "capa_pares.csv")
        self.assertEqual(os.path.normcase(ruta), os.path.normcase(
            os.path.realpath(os.path.join(self.carpeta, "capa_pares.csv"))))

    def test_lo_que_no_es_hijo_directo_o_tiene_otra_extension_no(self):
        for carpeta, nombre in (("corrida4_run22", "secreto.key"),
                                ("..", "fuera.csv"),
                                ("corrida4_run22", "../fuera.csv"),
                                ("corrida4_run22", "..\\fuera.csv"),
                                ("../flujo/corrida4_run22", "estado.json"),
                                ("corrida4_run22", "no_existe.csv"),
                                ("", "estado.json")):
            self.assertIsNone(flujo.ruta_archivo(self.raiz, carpeta, nombre),
                              (carpeta, nombre))

    def test_leer_carpeta_lista_solo_lo_permitido(self):
        datos = flujo.leer_carpeta(self.raiz, "corrida4_run22")
        nombres = [a["nombre"] for a in datos["archivos"]]
        self.assertIn("capa_pares.csv", nombres)
        self.assertNotIn("secreto.key", nombres)
        self.assertIsNone(flujo.leer_carpeta(self.raiz, ".."))

    def test_el_graphml_del_paquete_se_lista_y_se_entrega(self):
        with io.open(os.path.join(self.carpeta, "red.graphml"), "w",
                     encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<graphml/>\n')
        nombres = [a["nombre"] for a in flujo.leer_carpeta(
            self.raiz, "corrida4_run22")["archivos"]]
        self.assertIn("red.graphml", nombres)
        ruta = flujo.ruta_archivo(self.raiz, "corrida4_run22", "red.graphml")
        self.assertEqual(os.path.normcase(ruta), os.path.normcase(
            os.path.realpath(os.path.join(self.carpeta, "red.graphml"))))

    def test_estado_general_sin_base_ni_carpetas(self):
        vacio = os.path.join(self.tmp.name, "vacio")
        r = flujo.estado_general(None, vacio)
        self.assertEqual(r["carpetas"], [])
        self.assertEqual(list(r["pasos"]), list(flujo.PASOS))
        json.dumps(r)

    def test_una_base_sin_tablas_del_bronce_no_tiene_corridas(self):
        con = sqlite3.connect(os.path.join(self.tmp.name, "vacia.db"))
        self.addCleanup(con.close)
        self.assertEqual(flujo.estado_general(con, self.raiz)
                         ["corridas_bronce"], [])

    def test_las_corridas_del_paso_2_no_esconden_las_del_bronce(self):
        """El paso 2 también deja filas en `corridas`. Antes se tomaban las
        últimas 50 de cualquier paso y luego se filtraba: con 50 del paso 2
        encima, el selector del tablero se quedaba sin corridas del bronce."""
        from grn_bronce import db as bdb
        con = bdb.conectar(os.path.join(self.tmp.name, "grn.db"))
        self.addCleanup(con.close)
        bronce = bdb.abrir_corrida(con, "1", "baseline-deterministico", "4")
        bdb.cerrar_corrida(con, bronce, "ok", None, 10, 10)
        for _ in range(60):
            n = bdb.abrir_corrida(con, "2", "biobert-run22", "1")
            bdb.cerrar_corrida(con, n, "ok", None, 1, 1)
        corridas = flujo.estado_general(con, self.raiz)["corridas_bronce"]
        self.assertEqual([c["id"] for c in corridas], [bronce])


if __name__ == "__main__":
    unittest.main()
