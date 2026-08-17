# -*- coding: utf-8 -*-
"""Gestor de trabajos en segundo plano.

Lo que se prueba aqui es concurrencia, asi que la regla es que ninguna
prueba se cuelgue: toda espera lleva timeout y falla si se agota. Nada de
sleeps para "dar tiempo"; la sincronizacion va con threading.Event, que
ademas hace las pruebas instantaneas.
"""

import json
import shutil
import tempfile
import threading
from pathlib import Path

from grn_etl import db, trabajos

from .falsos import ClienteFalso, PruebaSinRed

# Tope generoso: en una maquina sana ninguna espera llega ni a un
# milisegundo. Solo esta para que una regresion falle en vez de colgar la
# suite completa.
ESPERA = 5.0


class BasePruebaTrabajos(PruebaSinRed):

    def setUp(self):
        super().setUp()
        self.gestor = trabajos.Gestor()
        # Se registra primero, o sea que corre al final: si una asercion
        # falla a media corrida, este cleanup impide dejar hilos vivos
        # arrastrandose al resto de la suite.
        self.addCleanup(self._cerrar_gestor)

    def _cerrar_gestor(self):
        self.gestor.esperar(ESPERA)

    def esperar_evento(self, evento, que):
        self.assertTrue(evento.wait(ESPERA), f"tiempo agotado esperando {que}")

    def esperar_fin(self):
        self.assertTrue(self.gestor.esperar(ESPERA),
                        "el trabajo no termino a tiempo")


# ------------------------------------------------------ un trabajo a la vez

class PruebasExclusion(BasePruebaTrabajos):

    def test_un_segundo_lanzar_con_uno_activo_lanza_TrabajoEnCurso(self):
        """Dos corridas en paralelo rebasan el limite de tasa de NCBI (que
        bloquea por IP) y chocan al escribir en SQLite. El gestor lo
        impide desde la puerta."""
        arranco = threading.Event()
        seguir = threading.Event()
        self.addCleanup(seguir.set)

        def bloqueado(log):
            arranco.set()
            seguir.wait(ESPERA)
            return {"ok": 1}

        self.gestor.lanzar("run", bloqueado)
        self.esperar_evento(arranco, "que arranque el primer trabajo")

        with self.assertRaises(trabajos.TrabajoEnCurso):
            self.gestor.lanzar("fulltext", bloqueado)

        estado = self.gestor.estado()
        self.assertTrue(estado["activo"])
        self.assertEqual(estado["tipo"], "run")

        seguir.set()
        self.esperar_fin()

    def test_el_segundo_trabajo_no_pisa_el_estado_del_primero(self):
        """El rechazo tiene que ser total: si dejara la etiqueta o las
        lineas del intento rechazado, el tablero mostraria un trabajo que
        nunca corrio."""
        arranco = threading.Event()
        seguir = threading.Event()
        self.addCleanup(seguir.set)

        def bloqueado(log, marca):
            log(f"corriendo {marca}")
            arranco.set()
            seguir.wait(ESPERA)
            return {"marca": marca}

        self.gestor.lanzar("run", bloqueado, marca="uno")
        self.esperar_evento(arranco, "que arranque el primer trabajo")

        with self.assertRaises(trabajos.TrabajoEnCurso):
            self.gestor.lanzar("fulltext", bloqueado, marca="dos")

        seguir.set()
        self.esperar_fin()

        estado = self.gestor.estado()
        self.assertEqual(estado["tipo"], "run")
        self.assertEqual(estado["parametros"], {"marca": "uno"})
        self.assertEqual(estado["resultado"], {"marca": "uno"})
        self.assertEqual([l["texto"] for l in estado["lineas"]],
                         ["corriendo uno"])

    def test_al_terminar_el_gestor_acepta_otro_trabajo(self):
        def corto(log, marca):
            log(f"corriendo {marca}")
            return {"marca": marca}

        self.gestor.lanzar("run", corto, marca="uno")
        self.esperar_fin()
        self.assertFalse(self.gestor.estado()["activo"])

        self.gestor.lanzar("fulltext", corto, marca="dos")
        self.esperar_fin()

        estado = self.gestor.estado()
        self.assertEqual(estado["tipo"], "fulltext")
        self.assertEqual(estado["resultado"], {"marca": "dos"})
        self.assertIsNone(estado["error"])
        # Las lineas son las del trabajo en curso, no la suma de todos.
        self.assertEqual([l["texto"] for l in estado["lineas"]],
                         ["corriendo dos"])


# --------------------------------------------------------------- excepciones

class PruebasErrores(BasePruebaTrabajos):

    def test_una_excepcion_queda_en_error_y_no_deja_el_gestor_trabado(self):
        """Si un trabajo que truena dejara el gestor apartado, nadie del
        laboratorio podria lanzar nada hasta reiniciar el servidor."""
        def truena(log):
            log("buscando en PubMed...")
            raise ValueError("No existe la consulta 'pa_regulacion'")

        self.gestor.lanzar("run", truena)
        self.esperar_fin()

        estado = self.gestor.estado()
        self.assertFalse(estado["activo"])
        self.assertIn("ValueError", estado["error"])
        self.assertIn("No existe la consulta", estado["error"])
        self.assertIsNone(estado["resultado"])
        self.assertIsNotNone(estado["terminado_en"])

        # Y el gestor sigue sirviendo.
        self.gestor.lanzar("fulltext", lambda log: {"ok": 1})
        self.esperar_fin()
        estado = self.gestor.estado()
        self.assertIsNone(estado["error"])
        self.assertEqual(estado["resultado"], {"ok": 1})

    def test_el_error_tambien_queda_en_las_lineas(self):
        def truena(log):
            log("primera linea")
            raise RuntimeError("HTTP 400 de NCBI: query mal formada")

        self.gestor.lanzar("run", truena)
        self.esperar_fin()

        lineas = [l["texto"] for l in self.gestor.estado()["lineas"]]
        self.assertEqual(lineas[0], "primera linea")
        self.assertIn("query mal formada", lineas[-1])


# ---------------------------------------------------------- captura del log

class PruebasLineas(BasePruebaTrabajos):

    def test_las_lineas_llegan_a_estado_con_su_hora(self):
        def hablador(log):
            log("Buscando en PubMed (orden: relevance)...")
            log("Ya en la base: 12   por descargar: 3")

        self.gestor.lanzar("run", hablador)
        self.esperar_fin()

        lineas = self.gestor.estado()["lineas"]
        self.assertEqual(
            [l["texto"] for l in lineas],
            ["Buscando en PubMed (orden: relevance)...",
             "Ya en la base: 12   por descargar: 3"],
        )
        for l in lineas:
            # Misma marca ISO 8601 UTC que db.ahora(), para que el tablero
            # las pueda ordenar contra ejecuciones.iniciada_en.
            self.assertRegex(
                l["t"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_el_deque_respeta_el_tope_de_400(self):
        """Una corrida de fulltext escribe una linea por articulo. Sin
        tope, el JSON de estado() crece hasta volver inutil el sondeo."""
        self.assertEqual(trabajos.MAX_LINEAS, 400)

        def ruidoso(log):
            for i in range(trabajos.MAX_LINEAS + 120):
                log(f"linea {i}")

        self.gestor.lanzar("fulltext", ruidoso)
        self.esperar_fin()

        lineas = self.gestor.estado()["lineas"]
        self.assertEqual(len(lineas), 400)
        self.assertEqual(lineas[0]["texto"], "linea 120")
        self.assertEqual(lineas[-1]["texto"], "linea 519")

    def test_las_lineas_se_pueden_leer_mientras_el_trabajo_corre(self):
        """El tablero sondea con el trabajo en curso; esa es la razon de
        que el lock no se sostenga durante la corrida."""
        escribio = threading.Event()
        seguir = threading.Event()
        self.addCleanup(seguir.set)

        def a_medias(log):
            log("efetch 200/1000")
            escribio.set()
            seguir.wait(ESPERA)
            log("efetch 1000/1000")

        self.gestor.lanzar("run", a_medias)
        self.esperar_evento(escribio, "la primera linea")

        estado = self.gestor.estado()
        self.assertTrue(estado["activo"])
        self.assertEqual([l["texto"] for l in estado["lineas"]],
                         ["efetch 200/1000"])
        self.assertIsNone(estado["terminado_en"])

        seguir.set()
        self.esperar_fin()
        self.assertEqual(len(self.gestor.estado()["lineas"]), 2)


# --------------------------------------------------------- forma del estado

class PruebasEstado(BasePruebaTrabajos):

    def test_estado_devuelve_una_copia(self):
        def trabajo(log, nombre):
            log("una linea")
            return {"nuevos": 3}

        self.gestor.lanzar("run", trabajo, nombre="pa_regulacion")
        self.esperar_fin()

        prestado = self.gestor.estado()
        prestado["lineas"].append({"t": "x", "texto": "intruso"})
        prestado["lineas"][0]["texto"] = "pisado"
        prestado["parametros"]["nombre"] = "otra_consulta"
        prestado["resultado"]["nuevos"] = 999

        estado = self.gestor.estado()
        self.assertEqual([l["texto"] for l in estado["lineas"]], ["una linea"])
        self.assertEqual(estado["parametros"], {"nombre": "pa_regulacion"})
        self.assertEqual(estado["resultado"], {"nuevos": 3})

    def test_estado_sin_trabajos_es_neutro_y_serializable(self):
        estado = self.gestor.estado()

        self.assertFalse(estado["activo"])
        self.assertIsNone(estado["tipo"])
        self.assertIsNone(estado["iniciado_en"])
        self.assertIsNone(estado["terminado_en"])
        self.assertIsNone(estado["error"])
        self.assertIsNone(estado["resultado"])
        self.assertEqual(estado["parametros"], {})
        self.assertEqual(estado["lineas"], [])
        json.dumps(estado)

    def test_los_parametros_no_serializables_no_llegan_al_json(self):
        """El endpoint devuelve estado() tal cual. Un pubmed.Cliente en
        'parametros' tronaria json.dumps, y ademas no le dice nada a quien
        mira el tablero."""
        cliente = ClienteFalso(universo=["111"])

        def trabajo(log, cliente, nombre, limite, orden, desde):
            return {"ok": 1}

        self.gestor.lanzar("run", trabajo, cliente=cliente, nombre="pa",
                           limite=50, orden="pub_date", desde=None)
        self.esperar_fin()

        estado = self.gestor.estado()
        self.assertIsNone(estado["error"])
        self.assertEqual(estado["parametros"], {
            "nombre": "pa", "limite": 50, "orden": "pub_date", "desde": None,
        })
        json.dumps(estado)

    def test_iniciado_y_terminado_en_iso_utc(self):
        self.gestor.lanzar("run", lambda log: None)
        self.esperar_fin()

        estado = self.gestor.estado()
        patron = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$"
        self.assertRegex(estado["iniciado_en"], patron)
        self.assertRegex(estado["terminado_en"], patron)
        self.assertLessEqual(estado["iniciado_en"], estado["terminado_en"])

    def test_esperar_sin_trabajos_devuelve_de_inmediato(self):
        self.assertTrue(self.gestor.esperar(0))


# ------------------------------------------------------- conexion por hilo

class PruebasConexion(BasePruebaTrabajos):
    """sqlite3 prohibe usar una conexion desde otro hilo, asi que el
    trabajo abre la suya con la ruta que guarda el gestor."""

    def setUp(self):
        super().setUp()
        carpeta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, carpeta, True)
        self.ruta = str(Path(carpeta) / "grn.db")
        self.gestor = trabajos.Gestor(self.ruta)

    def test_el_trabajo_recibe_su_propia_conexion_y_lo_escrito_persiste(self):
        def alta(con, log):
            log("dando de alta la consulta")
            id_, resultado = db.alta_consulta(
                con, "pa_regulacion", "lasR AND mexT", "prueba")
            return {"id": id_, "estado": resultado}

        self.gestor.lanzar("run", alta)
        self.esperar_fin()

        estado = self.gestor.estado()
        self.assertIsNone(estado["error"])
        self.assertEqual(estado["resultado"]["estado"], "creada")

        # Se lee desde el hilo principal, con otra conexion: si el trabajo
        # no hubiera hecho commit, aqui no habria nada.
        con = db.conectar(self.ruta)
        self.addCleanup(con.close)
        fila = db.obtener_consulta(con, "pa_regulacion")
        self.assertEqual(fila["texto"], "lasR AND mexT")

    def test_sin_ruta_de_base_el_gestor_no_inyecta_conexion(self):
        visto = {}

        def trabajo(log, **kw):
            visto["kw"] = dict(kw)

        gestor = trabajos.Gestor()
        gestor.lanzar("run", trabajo, nombre="pa")
        self.assertTrue(gestor.esperar(ESPERA), "el trabajo no termino")

        self.assertEqual(visto["kw"], {"nombre": "pa"})


class PruebasArranqueFallido(PruebaSinRed):
    """Si el hilo no arranca, el gestor no puede quedarse apartado.

    Quien baja la bandera _activo en el caso normal es el propio hilo del
    trabajo, en su finally. Si el hilo nunca arranco, ese finally no
    existe: sin este arreglo el gestor queda ocupado por un trabajo que no
    corrio y nadie puede lanzar nada hasta reiniciar el servidor.
    """

    def test_un_start_que_falla_libera_el_gestor(self):
        import threading

        g = trabajos.Gestor()
        original = threading.Thread.start

        def start_roto(self):
            raise RuntimeError("can't start new thread")

        threading.Thread.start = start_roto
        try:
            with self.assertRaises(RuntimeError):
                g.lanzar("run", lambda **kw: None)
        finally:
            threading.Thread.start = original

        self.assertFalse(g.estado()["activo"],
                         "el gestor quedo apartado por un trabajo que nunca corrio")
        self.assertIn("hilo", g.estado()["error"])

        # Y de verdad acepta el siguiente
        listo = threading.Event()
        g.lanzar("run", lambda **kw: listo.set())
        self.assertTrue(listo.wait(10))
        self.assertTrue(g.esperar(10))


class PruebasEsperarSinCarrera(PruebaSinRed):
    """esperar() no puede alcanzar al hilo antes de que arranque.

    Si lanzar() publicara self._hilo antes de start(), un esperar()
    concurrente veria un hilo sin arrancar y join() lanzaria
    'cannot join thread before it is started'. Pasa en el cierre ordenado
    del servidor: un Ctrl-C justo mientras alguien lanza un trabajo.
    """

    def test_esperar_concurrente_con_lanzar_no_truena(self):
        import threading

        real = threading.Thread.start
        en_medio = threading.Event()
        soltar = threading.Event()

        def start_lento(self):
            # Ensancha la ventana entre construir el hilo y arrancarlo,
            # que es donde vivia la carrera.
            if self.name.startswith("trabajo-"):
                en_medio.set()
                soltar.wait(5)
            return real(self)

        g = trabajos.Gestor()
        fallos = []
        threading.Thread.start = start_lento
        try:
            lanzador = threading.Thread(
                target=lambda: g.lanzar("run", lambda **kw: None))
            lanzador.start()
            self.assertTrue(en_medio.wait(5))

            def espiar():
                try:
                    g.esperar(timeout=5)
                except Exception as e:
                    fallos.append(f"{type(e).__name__}: {e}")

            espia = threading.Thread(target=espiar)
            espia.start()
            soltar.set()
            lanzador.join(10)
            espia.join(10)
        finally:
            threading.Thread.start = real
            soltar.set()

        self.assertEqual(fallos, [], "esperar() truena en plena ventana de arranque")
        self.assertTrue(g.esperar(10))

    def test_un_start_fallido_no_deja_hilo_publicado(self):
        import threading

        g = trabajos.Gestor()
        real = threading.Thread.start
        threading.Thread.start = lambda self: (_ for _ in ()).throw(
            RuntimeError("can't start new thread"))
        try:
            with self.assertRaises(RuntimeError):
                g.lanzar("run", lambda **kw: None)
        finally:
            threading.Thread.start = real

        # esperar() no debe encontrarse un hilo sin arrancar
        self.assertTrue(g.esperar(5))
        self.assertFalse(g.estado()["activo"])
