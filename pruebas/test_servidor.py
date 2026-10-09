# -*- coding: utf-8 -*-
"""La API del tablero, probada sin abrir un solo puerto.

manejar() es una funcion normal: recibe metodo, ruta, parametros, cuerpo
y contexto, y devuelve (codigo, objeto). Por eso aqui no hay sockets, ni
puertos ocupados, ni firewalls de por medio; se prueba la API completa
como se prueba cualquier otra funcion.

Dos invariantes se revisan en CADA peticion, dentro del ayudante pedir():
que la respuesta sobreviva a json.dumps (un sqlite3.Row olvidado en un
listado tumba el endpoint en produccion y aqui no) y que nunca se
devuelva un archivo del disco fuera de los tres lugares que se sirven:
web/, la salida del fulltext y la raíz del flujo.
"""

import io
import json
import os
import re
import tempfile
import unittest.mock
import threading
from pathlib import Path

import flujo
import servidor
from grn_bronce import db as bdb
from grn_etl import credenciales, db, pubmed, trabajos

from .falsos import ClienteFalso, PruebaSinRed, jats_xml

# Tope generoso: ninguna espera real llega a un milisegundo. Esta para que
# una regresion falle en vez de colgar la suite.
ESPERA = 5.0

RAIZ = Path(__file__).resolve().parent.parent


class BasePruebaServidor(PruebaSinRed):
    """Base con una base de datos en memoria ya sembrada."""

    def setUp(self):
        super().setUp()
        self.con = db.conectar(":memory:")
        self.addCleanup(self.con.close)

        self.gestor = trabajos.Gestor()
        self.addCleanup(self.gestor.esperar, ESPERA)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.salida = tmp.name

        # La raíz del flujo también va a un temporal: ninguna prueba debe
        # leer ni escribir en el salidas/flujo de verdad de quien la corre.
        tmp_flujo = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_flujo.cleanup)
        self.flujo_raiz = tmp_flujo.name

        self.cliente = ClienteFalso()
        self.ctx = servidor.Contexto(self.con, self.gestor, self.cliente,
                                     self.salida, flujo_raiz=self.flujo_raiz)
        self.sembrar()

    # ------------------------------------------------------------ semilla

    def sembrar(self):
        self.id_pa, _ = db.alta_consulta(
            self.con, "pa", "lasR AND biofilm", "regulacion por quorum sensing")
        self.id_otra, _ = db.alta_consulta(self.con, "otra", "mexT")

        db.guardar_documentos(self.con, [
            {"pmid": "111", "titulo": "Regulacion por LasR",
             "abstract": "LasR activa a rhlR", "anio": "2020",
             "revista": "J Bacteriol", "doi": "10.1000/a", "pmcid": "PMC1",
             "autores": ["Perez AB", "Lopez C"],
             "mesh_terms": ["Pseudomonas aeruginosa"],
             "keywords": ["quorum sensing"],
             "tipos_publicacion": ["Journal Article"]},
            {"pmid": "222", "titulo": "MexT y mexEF-oprN", "abstract": "",
             "anio": "2019", "revista": "Antimicrob Agents"},
            {"pmid": "333", "titulo": "Bomba de eflujo",
             "abstract": "la represion de mexT es indirecta", "anio": "2021",
             "revista": "Mol Microbiol"},
            {"pmid": "444", "titulo": "Factor sigma AlgU",
             "abstract": "AlgU regula la alginato sintasa", "anio": "2021",
             "revista": "J Bacteriol"},
            {"pmid": "555", "titulo": "RpoS en biopelicula",
             "abstract": "RpoS es un hub", "anio": "2018",
             "revista": "Microbiology"},
        ])
        db.vincular(self.con, self.id_pa, ["111", "222", "555"])
        db.vincular(self.con, self.id_otra, ["111", "333"])

        db.registrar_descarga(self.con, "111", "xml", "ok", fuente="PMC",
                              ruta="/datos/fulltext/xml/111_PMC1.txt", tam=900)
        db.registrar_descarga(self.con, "222", "xml", "no_disponible",
                              nota="sin PMCID (no esta en PMC)")
        db.registrar_descarga(self.con, "111", "pdf", "error",
                              nota="la liga no devolvio un PDF valido")

        eje = db.abrir_ejecucion(self.con, self.id_pa)
        db.cerrar_ejecucion(self.con, eje, "ok", total_pubmed=3,
                            pmids_nuevos=3, pmids_previos=0, descargados=3)
        eje = db.abrir_ejecucion(self.con, self.id_otra)
        db.cerrar_ejecucion(self.con, eje, "error", error="NCBI rechazo la query")

    # ----------------------------------------------------------- ayudantes

    def pedir(self, metodo, ruta, params=None, cuerpo=None, ctx=None):
        usado = ctx or self.ctx
        codigo, objeto = servidor.manejar(
            metodo, ruta, params or {}, cuerpo, usado)
        if isinstance(objeto, servidor.Archivo):
            # Un archivo que salga de manejar() solo puede vivir en tres
            # lugares: web/, que es el tablero y su escudo; la carpeta de
            # salida del fulltext; y la raíz del flujo, cuyas salidas (los
            # CSV, los JSON de resumen, flujo.log) se bajan desde la pestaña
            # Pipeline. Las dos últimas salen de la línea de comandos y
            # nunca de la petición. Cualquier otro lugar es una fuga del
            # directorio del proyecto, donde están .key, la base y el
            # código. Corre en cada petición de la suite a propósito.
            permitidas = [servidor.RUTA_PAGINA.parent,
                          Path(usado.salida).resolve(),
                          Path(usado.flujo_raiz).resolve()]
            real = objeto.ruta.resolve()
            self.assertTrue(
                any(r == real or r in real.parents for r in permitidas),
                f"{ruta} devolvio un archivo de fuera: {real}")
        else:
            # Si esto truena, el endpoint no serializa y en el navegador
            # seria un 500 sin pista.
            json.dumps(objeto, ensure_ascii=False)
        return codigo, objeto

    def ok(self, metodo, ruta, params=None, cuerpo=None, esperado=200):
        codigo, objeto = self.pedir(metodo, ruta, params, cuerpo)
        self.assertEqual(codigo, esperado, objeto)
        return objeto

    def falla(self, metodo, ruta, esperado, params=None, cuerpo=None):
        codigo, objeto = self.pedir(metodo, ruta, params, cuerpo)
        self.assertEqual(codigo, esperado, objeto)
        self.assertIn("error", objeto)
        self.assertTrue(objeto["error"], "el error llego vacio")
        return objeto

    def pmids(self, respuesta):
        return [f["pmid"] for f in respuesta["filas"]]


# =========================================================== /api/estado

class PruebasEstado(BasePruebaServidor):

    def test_estado_trae_las_cifras_del_panel(self):
        r = self.ok("GET", "/api/estado")
        self.assertEqual(r["consultas"], 2)
        self.assertEqual(r["documentos"], 5)
        self.assertEqual(r["con_abstract"], 4)
        self.assertEqual(r["vinculos"], 5)

    def test_las_descargas_llegan_como_lista_de_objetos(self):
        """db.resumen las devuelve como sqlite3.Row; si no se convierten,
        json.dumps truena y el panel se queda en blanco."""
        r = self.ok("GET", "/api/estado")
        self.assertEqual(
            r["descargas"],
            [{"tipo": "pdf", "estatus": "error", "n": 1},
             {"tipo": "xml", "estatus": "no_disponible", "n": 1},
             {"tipo": "xml", "estatus": "ok", "n": 1}])

    def test_metodo_equivocado_en_una_ruta_conocida_es_404(self):
        self.falla("POST", "/api/estado", 404)


# ======================================================== /api/consultas

class PruebasConsultas(BasePruebaServidor):

    def test_listar_trae_conteo_y_ultima_corrida(self):
        filas = self.ok("GET", "/api/consultas")
        por_nombre = {f["nombre"]: f for f in filas}
        self.assertEqual(sorted(por_nombre), ["otra", "pa"])
        self.assertEqual(por_nombre["pa"]["n_documentos"], 3)
        self.assertEqual(por_nombre["pa"]["activa"], 1)
        self.assertTrue(por_nombre["pa"]["ultima_corrida"])
        # La ejecucion de 'otra' quedo en error: no cuenta como corrida ok.
        self.assertIsNone(por_nombre["otra"]["ultima_corrida"])

    def test_alta_devuelve_201_con_id_y_estado(self):
        r = self.ok("POST", "/api/consultas", cuerpo={
            "nombre": "nueva", "texto": "rpoS AND regulon",
            "descripcion": "factor sigma"}, esperado=201)
        self.assertEqual(r["estado"], "creada")
        fila = db.obtener_consulta(self.con, "nueva")
        self.assertEqual(fila["id"], r["id"])
        self.assertEqual(fila["texto"], "rpoS AND regulon")

    def test_alta_del_mismo_nombre_actualiza_en_vez_de_duplicar(self):
        self.ok("POST", "/api/consultas",
                cuerpo={"nombre": "pa", "texto": "lasR AND biofilm"},
                esperado=201)["estado"]
        r = self.ok("POST", "/api/consultas",
                    cuerpo={"nombre": "pa", "texto": "lasR OR rhlR"},
                    esperado=201)
        self.assertEqual(r["estado"], "actualizada")
        self.assertEqual(len(self.ok("GET", "/api/consultas")), 2)

    def test_alta_sin_nombre_o_sin_texto_es_400(self):
        self.falla("POST", "/api/consultas", 400, cuerpo={"texto": "x"})
        self.falla("POST", "/api/consultas", 400, cuerpo={"nombre": "x"})
        self.falla("POST", "/api/consultas", 400,
                   cuerpo={"nombre": "  ", "texto": "x"})

    def test_alta_con_cuerpo_que_no_es_objeto_es_400(self):
        self.falla("POST", "/api/consultas", 400, cuerpo=None)
        self.falla("POST", "/api/consultas", 400, cuerpo=["pa"])
        self.falla("POST", "/api/consultas", 400, cuerpo={"nombre": 7,
                                                          "texto": "x"})

    def test_editar_cambia_solo_lo_que_llega(self):
        self.ok("PUT", f"/api/consultas/{self.id_pa}",
                cuerpo={"texto": "lasR AND (biofilm OR quorum)"})
        fila = db.obtener_consulta(self.con, "pa")
        self.assertEqual(fila["texto"], "lasR AND (biofilm OR quorum)")
        self.assertEqual(fila["descripcion"], "regulacion por quorum sensing")

    def test_editar_apaga_la_consulta_con_activa_cero(self):
        """El tablero manda 1 y 0, no true y false."""
        self.ok("PUT", f"/api/consultas/{self.id_pa}", cuerpo={"activa": 0})
        self.assertEqual(db.obtener_consulta(self.con, "pa")["activa"], 0)
        self.ok("PUT", f"/api/consultas/{self.id_pa}", cuerpo={"activa": 1})
        self.assertEqual(db.obtener_consulta(self.con, "pa")["activa"], 1)

    def test_editar_con_descripcion_vacia_la_limpia(self):
        self.ok("PUT", f"/api/consultas/{self.id_pa}", cuerpo={"descripcion": ""})
        self.assertEqual(db.obtener_consulta(self.con, "pa")["descripcion"], "")

    def test_editar_sin_campos_utiles_es_400(self):
        self.falla("PUT", f"/api/consultas/{self.id_pa}", 400, cuerpo={})
        self.falla("PUT", f"/api/consultas/{self.id_pa}", 400,
                   cuerpo={"nombre": "otro"})

    def test_editar_con_texto_vacio_es_400(self):
        """Una consulta sin texto no se puede correr; mejor no dejar
        guardarla que descubrirlo en el run."""
        self.falla("PUT", f"/api/consultas/{self.id_pa}", 400,
                   cuerpo={"texto": "   "})

    def test_editar_id_inexistente_es_404_y_id_no_numerico_es_400(self):
        self.falla("PUT", "/api/consultas/9999", 404, cuerpo={"activa": 0})
        self.falla("PUT", "/api/consultas/abc", 400, cuerpo={"activa": 0})

    def test_detalle_dice_cuanto_se_llevaria_un_borrado(self):
        """La confirmacion del tablero necesita el numero exacto ANTES de
        que el usuario acepte. Antes lo sacaba midiendo el largo de una
        pagina de la bitacora, que viene con LIMIT: pasado el tope decia
        menos de lo que el borrado se lleva."""
        d = self.ok("GET", f"/api/consultas/{self.id_pa}")

        self.assertEqual(d["nombre"], "pa")
        self.assertEqual(d["texto"], "lasR AND biofilm")
        self.assertEqual(d["n_vinculos"], 3)
        self.assertEqual(d["n_ejecuciones"], 1)

    def test_lo_que_promete_el_detalle_es_lo_que_borra_el_delete(self):
        """Dos numeros sobre lo mismo: si no coinciden, la advertencia que
        el usuario acepto no era cierta."""
        d = self.ok("GET", f"/api/consultas/{self.id_pa}")

        r = self.ok("DELETE", f"/api/consultas/{self.id_pa}")

        self.assertEqual(r["borrados"], {"vinculos": d["n_vinculos"],
                                         "ejecuciones": d["n_ejecuciones"]})

    def test_detalle_de_id_inexistente_es_404_y_no_numerico_es_400(self):
        self.falla("GET", "/api/consultas/9999", 404)
        self.falla("GET", "/api/consultas/abc", 400)

    def test_borrar_dice_cuanta_trazabilidad_se_llevo(self):
        r = self.ok("DELETE", f"/api/consultas/{self.id_pa}")
        self.assertEqual(r["borrados"], {"vinculos": 3, "ejecuciones": 1})

    def test_borrar_una_consulta_no_borra_documentos_ni_deja_huerfanos(self):
        self.ok("DELETE", f"/api/consultas/{self.id_pa}")
        self.assertEqual(self.ok("GET", "/api/estado")["documentos"], 5)
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])
        # 111 estaba en las dos consultas: conserva su vinculo con 'otra'.
        docs = self.ok("GET", "/api/documentos", {"consulta": "otra"})
        self.assertEqual(sorted(self.pmids(docs)), ["111", "333"])

    def test_borrar_id_inexistente_es_404(self):
        self.falla("DELETE", "/api/consultas/9999", 404)


# ======================================================= /api/documentos

class PruebasDocumentos(BasePruebaServidor):

    def test_listado_pagina_y_trae_lo_que_pinta_la_tabla(self):
        r = self.ok("GET", "/api/documentos")
        self.assertEqual(r["total"], 5)
        self.assertEqual(r["pagina"], 1)
        self.assertEqual(r["por_pagina"], 50)
        for clave in ("pmid", "anio", "revista", "titulo", "tiene_abstract"):
            self.assertIn(clave, r["filas"][0])

    def test_el_listado_no_arrastra_el_abstract_de_cada_documento(self):
        """Cincuenta abstracts por tecla son cientos de KB en cada
        busqueda. El detalle si los trae, que es donde se leen."""
        r = self.ok("GET", "/api/documentos")
        self.assertNotIn("abstract", r["filas"][0])

    def test_filtro_por_consulta_usa_el_nombre(self):
        r = self.ok("GET", "/api/documentos", {"consulta": "pa"})
        self.assertEqual(r["total"], 3)
        self.assertEqual(sorted(self.pmids(r)), ["111", "222", "555"])

    def test_filtro_por_anio_y_por_texto(self):
        self.assertEqual(
            sorted(self.pmids(self.ok("GET", "/api/documentos", {"anio": "2021"}))),
            ["333", "444"])
        self.assertEqual(
            self.pmids(self.ok("GET", "/api/documentos", {"q": "mexEF"})), ["222"])
        self.assertEqual(
            self.pmids(self.ok("GET", "/api/documentos", {"q": "111"})), ["111"])

    def test_filtro_de_abstract_es_tri_estado(self):
        self.assertEqual(
            self.ok("GET", "/api/documentos", {"abstract": "1"})["total"], 4)
        self.assertEqual(
            self.pmids(self.ok("GET", "/api/documentos", {"abstract": "0"})), ["222"])
        self.assertEqual(
            self.ok("GET", "/api/documentos", {"abstract": ""})["total"], 5)

    def test_abstract_con_valor_raro_es_400(self):
        self.falla("GET", "/api/documentos", 400, {"abstract": "quiza"})

    def test_paginacion_sin_huecos_ni_repetidos(self):
        vistos = []
        for pagina in (1, 2, 3):
            r = self.ok("GET", "/api/documentos",
                        {"pagina": str(pagina), "por_pagina": "2"})
            self.assertEqual(r["total"], 5)
            self.assertEqual(r["pagina"], pagina)
            vistos.extend(self.pmids(r))
        self.assertEqual(sorted(vistos), ["111", "222", "333", "444", "555"])

    def test_la_pagina_corregida_se_devuelve_corregida(self):
        """Si el servidor sirve la pagina 1 y contesta 'pagina 0', el
        tablero pinta una paginacion que no corresponde a sus filas."""
        r = self.ok("GET", "/api/documentos", {"pagina": "0"})
        self.assertEqual(r["pagina"], 1)
        r = self.ok("GET", "/api/documentos", {"por_pagina": "9999"})
        self.assertEqual(r["por_pagina"], 500)

    def test_paginacion_no_numerica_es_400_y_no_500(self):
        self.falla("GET", "/api/documentos", 400, {"pagina": "abc"})
        self.falla("GET", "/api/documentos", 400, {"por_pagina": "muchos"})
        self.falla("GET", "/api/documentos", 400, {"pagina": "-1"})

    def test_detalle_trae_las_listas_ya_deserializadas(self):
        d = self.ok("GET", "/api/documentos/111")
        self.assertEqual(d["autores"], ["Perez AB", "Lopez C"])
        self.assertEqual(d["mesh_terms"], ["Pseudomonas aeruginosa"])
        self.assertEqual(d["keywords"], ["quorum sensing"])
        self.assertEqual(d["tipos_publicacion"], ["Journal Article"])
        self.assertEqual(d["abstract"], "LasR activa a rhlR")

    def test_detalle_dice_cuanto_se_llevaria_un_borrado(self):
        """La confirmacion del tablero necesita el numero exacto ANTES de
        que el usuario acepte, no despues."""
        d = self.ok("GET", "/api/documentos/111")
        self.assertEqual(d["n_vinculos"], 2)
        self.assertEqual(d["n_descargas"], 2)

    def test_detalle_de_pmid_inexistente_es_404(self):
        self.falla("GET", "/api/documentos/999999", 404)

    def test_editar_cambia_el_campo_y_deja_el_resto(self):
        self.ok("PUT", "/api/documentos/111", cuerpo={"titulo": "Otro titulo"})
        d = self.ok("GET", "/api/documentos/111")
        self.assertEqual(d["titulo"], "Otro titulo")
        self.assertEqual(d["revista"], "J Bacteriol")

    def test_vaciar_el_abstract_actualiza_el_conteo_del_panel(self):
        antes = self.ok("GET", "/api/estado")["con_abstract"]
        self.ok("PUT", "/api/documentos/111", cuerpo={"abstract": ""})
        self.assertEqual(self.ok("GET", "/api/estado")["con_abstract"], antes - 1)
        self.assertEqual(
            self.pmids(self.ok("GET", "/api/documentos", {"abstract": "0"})),
            ["111", "222"])

    def test_editar_sin_ningun_campo_editable_es_400(self):
        """Distinguir 400 de 404: mandar solo 'pmid' es una peticion mala,
        no un documento que no existe."""
        self.falla("PUT", "/api/documentos/111", 400, cuerpo={"pmid": "999"})
        self.falla("PUT", "/api/documentos/111", 400, cuerpo={})
        self.falla("PUT", "/api/documentos/111", 400, cuerpo=None)

    def test_editar_con_valor_que_no_es_texto_es_400(self):
        self.falla("PUT", "/api/documentos/111", 400, cuerpo={"anio": 2020})

    def test_editar_pmid_inexistente_es_404(self):
        self.falla("PUT", "/api/documentos/999999", 404,
                   cuerpo={"titulo": "x"})

    def test_borrar_dice_que_se_llevo_y_no_deja_huerfanos(self):
        r = self.ok("DELETE", "/api/documentos/111")
        self.assertEqual(r["borrados"], {"vinculos": 2, "descargas": 2})
        self.falla("GET", "/api/documentos/111", 404)
        self.assertEqual(self.con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.ok("GET", "/api/descargas")["total"], 1)

    def test_borrar_pmid_inexistente_es_404(self):
        self.falla("DELETE", "/api/documentos/999999", 404)

    def test_anios_disponibles_del_mas_reciente_al_mas_viejo(self):
        self.assertEqual(self.ok("GET", "/api/anios"),
                         ["2021", "2020", "2019", "2018"])


# ======================================================== /api/descargas

class PruebasDescargas(BasePruebaServidor):

    def test_listado_trae_el_titulo_del_documento(self):
        r = self.ok("GET", "/api/descargas")
        self.assertEqual(r["total"], 3)
        fila = [f for f in r["filas"] if f["pmid"] == "111" and f["tipo"] == "xml"][0]
        self.assertEqual(fila["titulo"], "Regulacion por LasR")
        self.assertEqual(fila["estatus"], "ok")
        self.assertEqual(fila["intentos"], 1)

    def test_filtros_por_tipo_y_estatus(self):
        self.assertEqual(self.ok("GET", "/api/descargas", {"tipo": "xml"})["total"], 2)
        r = self.ok("GET", "/api/descargas", {"estatus": "error"})
        self.assertEqual([f["tipo"] for f in r["filas"]], ["pdf"])

    def test_paginacion_no_numerica_es_400(self):
        self.falla("GET", "/api/descargas", 400, {"pagina": "abc"})

    def test_borrar_el_registro_devuelve_el_pmid_a_pendientes(self):
        """Es para lo que existe: un 'no_disponible' que se borra vuelve a
        salir en el proximo fulltext sin correr todo con --reintentar."""
        pendientes = [f["pmid"] for f in db.pendientes_descarga(self.con, "xml")]
        self.assertNotIn("222", pendientes)

        self.assertEqual(self.ok("DELETE", "/api/descargas/222/xml"), {"ok": True})

        pendientes = [f["pmid"] for f in db.pendientes_descarga(self.con, "xml")]
        self.assertIn("222", pendientes)

    def test_borrar_lo_que_no_existe_es_404(self):
        self.falla("DELETE", "/api/descargas/222/pdf", 404)
        self.falla("DELETE", "/api/descargas/999999/xml", 404)

    def test_la_ruta_de_borrado_necesita_pmid_y_tipo(self):
        self.falla("DELETE", "/api/descargas/222", 404)


# ====================================== /api/ejecuciones y rutas sueltas

class PruebasEjecuciones(BasePruebaServidor):

    def test_bitacora_trae_el_nombre_de_la_consulta(self):
        filas = self.ok("GET", "/api/ejecuciones")
        self.assertEqual(len(filas), 2)
        self.assertEqual({f["consulta"] for f in filas}, {"pa", "otra"})
        con_error = [f for f in filas if f["estatus"] == "error"][0]
        self.assertEqual(con_error["error"], "NCBI rechazo la query")

    def test_filtro_por_nombre_y_tope_n(self):
        filas = self.ok("GET", "/api/ejecuciones", {"nombre": "pa"})
        self.assertEqual([f["consulta"] for f in filas], ["pa"])
        self.assertEqual(len(self.ok("GET", "/api/ejecuciones", {"n": "1"})), 1)

    def test_n_no_numerico_o_absurdo_es_400(self):
        self.falla("GET", "/api/ejecuciones", 400, {"n": "todas"})
        self.falla("GET", "/api/ejecuciones", 400, {"n": "99999"})

    def test_este_endpoint_no_sirve_para_contar_ejecuciones(self):
        """Trae una pagina, no un total. El tablero contaba las ejecuciones
        de una consulta midiendo el largo de esta respuesta, y al rebasar
        el tope el numero se quedaba en el tope: la confirmacion del
        borrado prometia menos de lo que se llevaba. Para contar esta
        db.conteos_consulta()."""
        for _ in range(4):
            db.cerrar_ejecucion(
                self.con, db.abrir_ejecucion(self.con, self.id_pa), "ok")

        filas = self.ok("GET", "/api/ejecuciones", {"nombre": "pa", "n": "3"})

        self.assertEqual(len(filas), 3)
        self.assertEqual(
            db.conteos_consulta(self.con, self.id_pa)["ejecuciones"], 5)


# ========================================================= /api/trabajo

class PruebasTrabajo(BasePruebaServidor):

    def test_estado_inicial_sin_trabajo(self):
        r = self.ok("GET", "/api/trabajo")
        self.assertFalse(r["activo"])
        self.assertIsNone(r["tipo"])
        self.assertEqual(r["lineas"], [])

    def test_sin_correo_configurado_no_se_lanza_nada_pero_se_puede_ver(self):
        """El servidor arranca sin correo a proposito: ver y editar no
        necesitan a NCBI. Lo que no se puede es salir a la red."""
        ctx = servidor.Contexto(self.con, self.gestor, None, self.salida)
        codigo, objeto = self.pedir("POST", "/api/trabajo",
                                    cuerpo={"tipo": "run", "nombre": "pa"}, ctx=ctx)
        self.assertEqual(codigo, 400)
        self.assertIn("correo", objeto["error"])
        # El mensaje manda al lugar donde se arregla, que ya no es
        # reiniciar con una variable de entorno.
        self.assertIn("Credenciales", objeto["error"])
        # El resto del tablero sigue funcionando.
        codigo, _ = self.pedir("GET", "/api/documentos", ctx=ctx)
        self.assertEqual(codigo, 200)

    def test_run_de_una_consulta_inexistente_es_404_sin_lanzar_hilo(self):
        self.falla("POST", "/api/trabajo", 404,
                   cuerpo={"tipo": "run", "nombre": "no_existe"})
        self.assertFalse(self.gestor.estado()["activo"])

    def test_parametros_invalidos_del_run_son_400(self):
        self.falla("POST", "/api/trabajo", 400, cuerpo={"tipo": "correr"})
        self.falla("POST", "/api/trabajo", 400, cuerpo={"tipo": "run"})
        self.falla("POST", "/api/trabajo", 400,
                   cuerpo={"tipo": "run", "nombre": "pa", "orden": "alfabetico"})
        self.falla("POST", "/api/trabajo", 400,
                   cuerpo={"tipo": "run", "nombre": "pa", "limite": "muchos"})
        self.falla("POST", "/api/trabajo", 400,
                   cuerpo={"tipo": "run", "nombre": "pa", "limite": 0})
        self.falla("POST", "/api/trabajo", 400,
                   cuerpo={"tipo": "run", "nombre": "pa", "desde": "ayer"})
        self.assertFalse(self.gestor.estado()["activo"])

    def test_parametros_invalidos_del_fulltext_son_400(self):
        self.falla("POST", "/api/trabajo", 400, cuerpo={"tipo": "fulltext"})
        self.falla("POST", "/api/trabajo", 400,
                   cuerpo={"tipo": "fulltext", "tipo_archivo": "epub"})
        self.falla("POST", "/api/trabajo", 400,
                   cuerpo={"tipo": "fulltext", "tipo_archivo": "xml",
                           "reintentar": "quiza"})
        self.falla("POST", "/api/trabajo", 404,
                   cuerpo={"tipo": "fulltext", "tipo_archivo": "xml",
                           "nombre": "no_existe"})

    def test_un_segundo_trabajo_con_uno_en_curso_es_409(self):
        """Dos corridas en paralelo rebasan el limite de NCBI, que bloquea
        por IP: el rechazo tiene que llegar hasta el navegador."""
        arranco = threading.Event()
        seguir = threading.Event()
        self.addCleanup(seguir.set)

        def bloqueado(log):
            arranco.set()
            seguir.wait(ESPERA)
            return {"ok": 1}

        self.gestor.lanzar("run", bloqueado)
        self.assertTrue(arranco.wait(ESPERA), "el trabajo no arranco")

        objeto = self.falla("POST", "/api/trabajo", 409,
                            cuerpo={"tipo": "run", "nombre": "pa"})
        self.assertIn("en curso", objeto["error"])

        # El sondeo sigue contestando mientras tanto, que es lo que pinta
        # la consola del tablero.
        self.assertTrue(self.ok("GET", "/api/trabajo")["activo"])

        seguir.set()
        self.assertTrue(self.gestor.esperar(ESPERA))

    def test_el_cliente_de_pubmed_no_sale_en_el_estado_del_trabajo(self):
        """El estado lo pinta el navegador. Un pubmed.Cliente ahi dentro
        seria, ademas de no serializable, la API key en pantalla."""
        secreto = "CLAVE-DE-PRUEBA-NO-REAL"
        cliente = pubmed.Cliente("prueba@unam.mx", secreto)
        listo = threading.Event()

        self.gestor.lanzar("run", lambda log, cliente, nombre_consulta: listo.set(),
                           cliente=cliente, nombre_consulta="pa")
        self.assertTrue(self.gestor.esperar(ESPERA))

        crudo = json.dumps(self.ok("GET", "/api/trabajo"), ensure_ascii=False)
        self.assertNotIn(secreto, crudo)
        self.assertNotIn("Cliente", crudo)
        self.assertIn("pa", crudo)


# ============================================== la pagina y las no-rutas

class PruebasPagina(BasePruebaServidor):

    def test_la_raiz_entrega_el_tablero(self):
        codigo, objeto = self.pedir("GET", "/")
        self.assertEqual(codigo, 200)
        self.assertIsInstance(objeto, servidor.Archivo)
        self.assertEqual(objeto.ruta, RAIZ / "web" / "index.html")
        self.assertTrue(objeto.ruta.exists(), "falta web/index.html")
        self.assertIn("text/html", objeto.tipo_mime)

    def test_la_ruta_de_la_pagina_no_depende_del_directorio_de_trabajo(self):
        """Se resuelve contra __file__: 'python servidor.py' desde
        cualquier lado sirve el mismo archivo, y ningun dato de la
        peticion entra en esa ruta."""
        self.assertTrue(servidor.RUTA_PAGINA.is_absolute())

    def test_ninguna_ruta_se_sale_a_otros_archivos_del_proyecto(self):
        escapes = [
            "/../.key", "/..%2f.key", "/%2e%2e/.key", "/..%2F..%2F.key",
            "/./../.key", "/.key", "/cli.py", "/servidor.py",
            "/web/index.html", "/datos/grn.db", "/../../etc/passwd",
            "/api/../.key", "//.key", "/%2e%2e%2f%2e%2e%2fcli.py",
        ]
        for ruta in escapes:
            codigo, objeto = self.pedir("GET", ruta)
            self.assertEqual(codigo, 404, f"{ruta} no dio 404")
            self.assertNotIsInstance(objeto, servidor.Archivo)
            self.assertIn("error", objeto)

    def test_el_contenido_de_archivos_del_proyecto_no_sale_en_la_respuesta(self):
        """La prueba de arriba mira el codigo; esta mira el cuerpo. Si
        alguna vez se sirviera el directorio, aqui aparece el secreto."""
        llave = RAIZ / ".key"
        if not llave.exists():
            self.skipTest("no hay .key en esta copia del proyecto")
        secreto = llave.read_text(encoding="utf-8", errors="replace").strip()
        if not secreto:
            self.skipTest(".key esta vacio")
        for ruta in ("/../.key", "/..%2f.key", "/.key", "/api/../.key"):
            _, objeto = self.pedir("GET", ruta)
            self.assertNotIn(secreto, json.dumps(objeto, ensure_ascii=False))

    def test_la_raiz_solo_responde_a_GET(self):
        self.falla("POST", "/", 404)
        self.falla("DELETE", "/", 404)

    def test_rutas_desconocidas_de_la_api_son_404(self):
        for ruta in ("/api", "/api/nada", "/api/documentos/111/vinculos",
                     "/api/consultas/1/ejecuciones", "/api/estado/extra"):
            self.falla("GET", ruta, 404)

    def test_solo_se_acepta_un_cuerpo_declarado_como_json(self):
        """Un formulario de otra pagina puede apuntarle a 127.0.0.1 sin
        permiso de nadie, pero solo sabe mandar urlencoded, multipart o
        text/plain. Exigir JSON deja fuera esa via."""
        self.assertTrue(servidor.es_json("application/json"))
        self.assertTrue(servidor.es_json("application/json; charset=utf-8"))
        self.assertTrue(servidor.es_json("  APPLICATION/JSON  "))
        for malo in (None, "", "text/plain", "multipart/form-data",
                     "application/x-www-form-urlencoded", "text/json"):
            self.assertFalse(servidor.es_json(malo), malo)

    def test_los_mensajes_de_error_se_pueden_pintar_en_windows(self):
        """Estos mensajes los lee una persona en el tablero, asi que van en
        espanol con acentos. Lo que si truena en la consola de Windows es
        un caracter fuera de Latin-1, y de ahi el limite: cp1252 tiene las
        vocales acentuadas y la n con virgulilla, no una sigma griega."""
        casos = [
            ("GET", "/api/nada", None),
            ("GET", "/api/documentos/999999", None),
            ("PUT", "/api/consultas/abc", {"activa": 1}),
            ("POST", "/api/consultas", {"nombre": "x"}),
            ("POST", "/api/trabajo", {"tipo": "epub"}),
            ("POST", "/api/trabajo", {"tipo": "flujo", "pasos": ["magia"]}),
            ("POST", "/api/trabajo", {"tipo": "flujo", "pasos": []}),
            ("POST", "/api/trabajo/cancelar", {}),
            ("GET", "/api/flujo/no_existe", None),
            ("GET", "/api/flujo/no_existe/archivos/red.tsv", None),
        ]
        for metodo, ruta, cuerpo in casos:
            _, objeto = self.pedir(metodo, ruta, cuerpo=cuerpo)
            try:
                objeto["error"].encode("cp1252")
            except UnicodeEncodeError:
                self.fail(f"{ruta}: {objeto['error']} no cabe en cp1252")

    def test_el_id_mal_escrito_se_reclama_en_espanol_correcto(self):
        """La otra mitad de la regla: el texto que ve el usuario lleva el
        acento puesto, no se queda en ASCII."""
        _, objeto = self.pedir("PUT", "/api/consultas/abc", cuerpo={"activa": 1})

        self.assertIn("número entero", objeto["error"])

    def test_la_capa_http_no_sabe_que_motor_hay_debajo(self):
        """Atrapa db.ErrorBase y no sqlite3.Error. Si importara sqlite3,
        migrar a Postgres dejaria de tocar solo db.py, que es la promesa de
        migracion-servicio.md."""
        self.assertFalse(hasattr(servidor, "sqlite3"))
        self.assertNotIn(
            "import sqlite3",
            (RAIZ / "servidor.py").read_text(encoding="utf-8"))


# ================================== trabajos de verdad, con base en disco

class PruebasTrabajoConBase(PruebaSinRed):
    """El unico bloque que corre el ETL completo detras del endpoint.

    Necesita una base en archivo: el gestor abre su PROPIA conexion dentro
    del hilo del trabajo (sqlite3 prohibe compartirlas entre hilos) y
    ':memory:' le daria una base vacia distinta. Es lo que verifica que
    los kwargs que arma el servidor coinciden con las firmas del ETL; un
    nombre mal escrito solo se ve corriendo.
    """

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.salida = str(Path(tmp.name) / "fulltext")
        self.ruta_db = str(Path(tmp.name) / "grn.db")

        self.con = db.conectar(self.ruta_db)
        self.addCleanup(self.con.close)
        self.gestor = trabajos.Gestor(self.ruta_db)
        self.addCleanup(self.gestor.esperar, ESPERA)

        self.id_pa, _ = db.alta_consulta(self.con, "pa", "lasR AND biofilm")

    def contexto(self, cliente):
        return servidor.Contexto(self.con, self.gestor, cliente, self.salida)

    def lanzar(self, cuerpo, cliente):
        codigo, objeto = servidor.manejar(
            "POST", "/api/trabajo", {}, cuerpo, self.contexto(cliente))
        self.assertEqual(codigo, 202, objeto)
        self.assertTrue(objeto["ok"])
        self.assertTrue(self.gestor.esperar(ESPERA), "el trabajo no termino")
        estado = self.gestor.estado()
        self.assertIsNone(estado["error"], estado["lineas"])
        return estado

    def test_run_desde_el_endpoint_llena_la_base(self):
        cliente = ClienteFalso(universo=["111", "222"])
        estado = self.lanzar({"tipo": "run", "nombre": "pa", "orden": "pub_date",
                              "limite": 2, "desde": "2000", "hasta": "2024"},
                             cliente)

        self.assertEqual(estado["tipo"], "run")
        self.assertEqual(estado["resultado"]["descargados"], 2)
        self.assertEqual(db.resumen(self.con)["documentos"], 2)
        self.assertTrue(estado["lineas"], "el log del ETL no llego al tablero")

        # Los parametros que se publican son los que el tablero pinta: sin
        # el cliente, que no es serializable.
        self.assertEqual(estado["parametros"]["nombre_consulta"], "pa")
        self.assertEqual(estado["parametros"]["orden"], "pub_date")
        self.assertNotIn("cliente", estado["parametros"])

        # Y la bitacora quedo cerrada como 'ok', que es lo que lee el
        # tablero en /api/ejecuciones.
        _, filas = servidor.manejar("GET", "/api/ejecuciones", {}, None,
                                    self.contexto(cliente))
        self.assertEqual(filas[0]["estatus"], "ok")
        self.assertEqual(filas[0]["consulta"], "pa")

    def test_segundo_run_igual_no_vuelve_a_llamar_a_efetch(self):
        """La idempotencia tiene que sobrevivir al endpoint: quien aprieta
        el boton dos veces no debe re-descargar nada."""
        cliente = ClienteFalso(universo=["111", "222"])
        self.lanzar({"tipo": "run", "nombre": "pa"}, cliente)
        cliente.reiniciar()
        self.lanzar({"tipo": "run", "nombre": "pa"}, cliente)
        self.assertEqual(cliente.n_eutils("efetch.fcgi", db="pubmed"), 0)

    def test_fulltext_desde_el_endpoint_escribe_donde_dice_el_servidor(self):
        """La ruta de salida no se acepta por HTTP: un directorio que
        llega en un cuerpo JSON es permiso de escritura en todo el disco."""
        db.guardar_documentos(self.con, [{"pmid": "111", "pmcid": "PMC1"}])
        db.vincular(self.con, self.id_pa, ["111"])
        cliente = ClienteFalso(xml_pmc={"PMC1": jats_xml(cuerpo=True)})

        estado = self.lanzar(
            {"tipo": "fulltext", "tipo_archivo": "xml", "nombre": "pa",
             "limite": 5, "reintentar": False, "sin_unpaywall": True,
             "salida": "C:/no/debe/usarse"}, cliente)

        self.assertEqual(estado["resultado"]["ok"], 1)
        escritos = sorted(p.name for p in (Path(self.salida) / "xml").iterdir())
        self.assertEqual(escritos, ["111_PMC1.txt", "111_PMC1.xml"])
        self.assertFalse(Path("C:/no/debe/usarse").exists())


class PruebasLogo(BasePruebaServidor):
    """El logo institucional se sirve como archivo, no incrustado.

    Es el segundo y ultimo archivo de la lista blanca. Lo que importa
    probar no es que se sirva, sino que agregarlo no haya abierto la
    puerta al resto del directorio: ahi viven .key, la base y el codigo.
    """

    def test_el_logo_se_sirve_con_su_tipo(self):
        codigo, cuerpo = servidor.manejar("GET", "/logo.png", {}, None, self.ctx)

        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo.tipo_mime, "image/png")
        self.assertTrue(cuerpo.ruta.exists(), "el archivo del logo no esta")

    def test_el_logo_solo_se_sirve_por_GET(self):
        for metodo in ("POST", "PUT", "DELETE"):
            codigo, _ = servidor.manejar(metodo, "/logo.png", {}, None, self.ctx)
            self.assertEqual(codigo, 404, metodo)

    def test_la_lista_blanca_es_de_dos_y_por_igualdad_exacta(self):
        """Un prefijo o una variante de mayusculas no debe colarse: si la
        comparacion fuera por 'empieza con', /logo.png/../.key entraria."""
        for ruta in ("/logo.PNG", "/logo.png/../.key", "/logo.png.key",
                     "/web/logo.png", "/logo.png%00.key", "/servidor.py"):
            codigo, _ = servidor.manejar("GET", ruta, {}, None, self.ctx)
            self.assertEqual(codigo, 404, ruta)

    def test_la_pagina_apunta_al_logo_servido_y_no_a_un_archivo_local(self):
        """Si el src fuera relativo al disco, el tablero se veria bien al
        abrirlo como archivo y roto al servirlo, que es al reves de como
        se usa."""
        html = servidor.RUTA_PAGINA.read_text(encoding="utf-8")

        self.assertIn('src="/logo.png"', html)


class PruebasIntroYRed(BasePruebaServidor):
    """La pagina de entrada explica que es la herramienta, y su red animada
    no puede meter una dependencia por la puerta de atras."""

    def setUp(self):
        super().setUp()
        self.pagina = servidor.RUTA_PAGINA.read_text(encoding="utf-8")

    def test_el_tablero_no_carga_nada_de_internet(self):
        """Es la restriccion que gobierna el proyecto entero: la maquina de
        laboratorio puede no tener salida a internet. Un CDN deja el tablero
        en blanco justo ahi."""
        import re
        externos = re.findall(r'(?:src|href)\s*=\s*["\'](?:https?:)?//[^"\']*',
                              self.pagina)

        self.assertEqual(externos, [], "el tablero carga algo de fuera")

    def test_la_red_se_dibuja_sin_biblioteca_de_terceros(self):
        self.assertIn("getContext", self.pagina)
        self.assertNotIn("three.min.js", self.pagina)
        self.assertNotIn("THREE.", self.pagina)

    def test_la_animacion_respeta_a_quien_pidio_menos_movimiento(self):
        self.assertIn("prefers-reduced-motion", self.pagina)

    def test_el_subtitulo_no_amarra_la_herramienta_a_una_sola_consulta(self):
        """Sirve para cualquier corpus de PubMed, no solo para el de
        P. aeruginosa con el que se estreno."""
        cabecera = self.pagina[:self.pagina.find("</header>")]

        self.assertNotIn("aeruginosa", cabecera)

    def test_el_escudo_va_sobre_una_placa_clara(self):
        """El 87% de sus pixeles opacos son muy oscuros: sobre el fondo de la
        pagina daria 2.6:1. La placa es lo que lo hace visible sin tener que
        recolorear un escudo institucional."""
        self.assertIn("placa-logo", self.pagina)


class PruebasArchivosDeDocumento(BasePruebaServidor):
    """Las rutas que sirven el texto y el PDF de un documento.

    Es el punto mas delicado del tablero: en la raiz del proyecto viven
    .key con la llave de NCBI, la base y el codigo. Lo que hay que
    defender no es que sirvan el archivo correcto, sino que no exista
    forma de que sirvan otro.
    """

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.salida = Path(tmp.name)
        (self.salida / "xml").mkdir()
        (self.salida / "pdf").mkdir()
        self.ctx.salida = str(self.salida)

        db.guardar_documentos(self.ctx.con, [
            {"pmid": "111", "pmcid": "PMC1"},
            {"pmid": "222"},                       # en PMC no esta
        ])
        (self.salida / "xml" / "111_PMC1.txt").write_text(
            "# Titulo\n\n## ABSTRACT\n\nTexto.", encoding="utf-8")
        (self.salida / "pdf" / "111.pdf").write_bytes(b"%PDF-1.7\ncuerpo\n")

        # El senuelo: si alguna ruta se sale del directorio de salida, este
        # es el archivo que se llevaria, y la prueba lo detecta por su
        # contenido y no por el codigo de respuesta.
        self.secreto = self.salida.parent / "llave_falsa.key"
        self.secreto.write_text("SECRETO-NO-DEBE-SALIR", encoding="utf-8")
        self.addCleanup(self.secreto.unlink)

    def test_el_texto_se_sirve_como_json(self):
        codigo, cuerpo = servidor.manejar(
            "GET", "/api/documentos/111/texto", {}, None, self.ctx)

        self.assertEqual(codigo, 200)
        self.assertIn("# Titulo", cuerpo["texto"])
        self.assertEqual(cuerpo["caracteres"], len(cuerpo["texto"]))

    def test_el_texto_va_como_json_y_no_como_archivo(self):
        """Asi el tablero lo pinta con su helper y sin innerHTML: los
        articulos traen '<' y '>' de formulas y nombres de genes."""
        _, cuerpo = servidor.manejar(
            "GET", "/api/documentos/111/texto", {}, None, self.ctx)

        self.assertIsInstance(cuerpo, dict)

    def test_el_pdf_se_sirve_como_archivo_con_su_tipo(self):
        codigo, cuerpo = servidor.manejar(
            "GET", "/api/documentos/111/pdf", {}, None, self.ctx)

        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo.tipo_mime, "application/pdf")
        self.assertTrue(cuerpo.ruta.is_file())

    def test_un_documento_sin_texto_da_404_y_lo_explica(self):
        codigo, cuerpo = servidor.manejar(
            "GET", "/api/documentos/222/texto", {}, None, self.ctx)

        self.assertEqual(codigo, 404)
        self.assertIn("222", cuerpo["error"])

    def test_un_documento_que_no_existe_da_404(self):
        for recurso in ("texto", "pdf"):
            codigo, _ = servidor.manejar(
                "GET", "/api/documentos/999999/" + recurso, {}, None, self.ctx)
            self.assertEqual(codigo, 404, recurso)

    def test_no_hay_pmid_que_saque_un_archivo_del_directorio_de_salida(self):
        """La prueba que no puede faltar. Se comprueba por el contenido del
        senuelo, no por el codigo: un 200 con el archivo equivocado seria
        peor que un 500."""
        intentos = [
            "../llave_falsa.key", "..%2fllave_falsa.key",
            "..", "../..", "%2e%2e%2f%2e%2e%2fllave_falsa.key",
            "111/../../llave_falsa.key", "./111", "111%00",
            "C:/Windows/win.ini", "/etc/passwd",
        ]
        for malo in intentos:
            for recurso in ("texto", "pdf"):
                ruta = "/api/documentos/" + malo + "/" + recurso
                codigo, cuerpo = servidor.manejar(
                    "GET", ruta, {}, None, self.ctx)
                self.assertEqual(codigo, 404, ruta)
                self.assertNotIn("SECRETO", json.dumps(cuerpo, default=str), ruta)

    def test_un_pmid_que_no_es_de_digitos_ni_llega_a_la_base(self):
        """Se rechaza por patron antes de consultar nada: el PMID entra en
        el nombre de un archivo, y de esa estrechez depende que sea seguro."""
        codigo, _ = servidor.manejar(
            "GET", "/api/documentos/11a/texto", {}, None, self.ctx)

        self.assertEqual(codigo, 404)

    def test_solo_se_sirven_por_GET(self):
        for metodo in ("POST", "PUT", "DELETE"):
            for recurso in ("texto", "pdf"):
                codigo, _ = servidor.manejar(
                    metodo, "/api/documentos/111/" + recurso, {}, None, self.ctx)
                self.assertEqual(codigo, 404, metodo + " " + recurso)

    def test_un_tercer_segmento_inventado_da_404(self):
        codigo, _ = servidor.manejar(
            "GET", "/api/documentos/111/xml", {}, None, self.ctx)

        self.assertEqual(codigo, 404)

    def test_el_detalle_dice_que_descargas_tiene_el_documento(self):
        """La clase base ya le puso a 111 un xml en ok y un pdf en error;
        el detalle debe traer las dos con su estatus, que es lo que decide
        si el tablero ofrece leer, ofrecer el PDF, o explicar por que no."""
        _, doc = servidor.manejar(
            "GET", "/api/documentos/111", {}, None, self.ctx)

        estados = {d["tipo"]: d["estatus"] for d in doc["descargas"]}
        self.assertEqual(estados, {"xml": "ok", "pdf": "error"})
        self.assertNotIn("ruta", doc["descargas"][0])


class PruebasPmcidEditable(BasePruebaServidor):
    """El PMCID entra en el nombre de un archivo Y se puede editar desde el
    tablero: esta en db.COLUMNAS_EDITABLES.

    O sea que "viene de la base" no lo hace de fiar. Es el unico camino por
    el que un valor escrito por una persona podria llegar a componer una
    ruta de disco, y por eso se valida contra su patron antes de usarlo, no
    al guardarlo.
    """

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.salida = Path(tmp.name)
        (self.salida / "xml").mkdir()
        self.ctx.salida = str(self.salida)
        self.secreto = self.salida.parent / "robado.key"
        self.secreto.write_text("SECRETO", encoding="utf-8")
        self.addCleanup(self.secreto.unlink)

    def test_un_pmcid_con_travesia_no_saca_ningun_archivo(self):
        for veneno in ("../../robado.key", "../robado", "PMC1/../../robado",
                       "PMC../..", "/etc/passwd", "PMC1;rm"):
            db.actualizar_documento(self.ctx.con, "111", {"pmcid": veneno})

            codigo, cuerpo = servidor.manejar(
                "GET", "/api/documentos/111/texto", {}, None, self.ctx)

            self.assertEqual(codigo, 404, veneno)
            self.assertNotIn("SECRETO", json.dumps(cuerpo, default=str), veneno)

    def test_con_un_pmcid_valido_si_lo_sirve(self):
        """La contraparte: la validacion no puede ser tan estrecha que
        rompa el caso normal."""
        db.actualizar_documento(self.ctx.con, "111", {"pmcid": "PMC777"})
        (self.salida / "xml" / "111_PMC777.txt").write_text(
            "# Hola", encoding="utf-8")

        codigo, cuerpo = servidor.manejar(
            "GET", "/api/documentos/111/texto", {}, None, self.ctx)

        self.assertEqual(codigo, 200)
        self.assertIn("Hola", cuerpo["texto"])


class PruebasNombreDelTablero(BasePruebaServidor):

    def test_el_encabezado_dice_el_mismo_nombre_que_la_pestana(self):
        """El <title> del navegador y el encabezado tienen que coincidir:
        quien llega por un marcador o ve una captura reconoce que es el
        mismo lugar. Si alguien cambia uno y olvida el otro, esto falla."""
        import re
        pagina = servidor.RUTA_PAGINA.read_text(encoding="utf-8")
        titulo = re.search(r"<title>(.*?)</title>", pagina).group(1)
        encabezado = pagina[pagina.find("<header"):pagina.find("</header>")]
        sobre_la_red = re.search(r"<h1>(.*?)</h1>", encabezado, re.S).group(1)

        # El separador difiere a proposito: '-' en el title, '·' en la
        # pagina. Lo que tiene que coincidir son las palabras.
        palabras = lambda s: [p for p in re.split(
            r"[^\wÁÉÍÓÚÑáéíóúñ]+", re.sub(r"<[^>]+>", " ", s)) if p]
        self.assertEqual(palabras(sobre_la_red), palabras(titulo))


class PruebasConfiguracion(BasePruebaServidor):
    """Configurar el correo y la API key desde el tablero.

    La regla que gobierna todo esto: la llave se puede escribir pero
    NUNCA leer. Una llave que entra por un formulario y puede volver a
    salir por un GET es una llave que cualquier pagina abierta en el
    mismo navegador podria llevarse.
    """

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        # Se apunta el modulo a un directorio temporal para no tocar el
        # .key de verdad de quien corre la suite.
        for nombre, valor in (("ARCHIVO_LLAVE", raiz / ".key"),
                              ("ARCHIVO_CORREO", raiz / ".correo")):
            parche = unittest.mock.patch.object(credenciales, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        for var in ("NCBI_API_KEY", "NCBI_EMAIL"):
            parche = unittest.mock.patch.dict(os.environ, {}, clear=False)
            parche.start()
            self.addCleanup(parche.stop)
            os.environ.pop(var, None)
        self.ctx.correo_explicito = None
        self.LLAVE = "a" * 36

    def test_la_llave_nunca_sale_en_la_respuesta(self):
        """La prueba que no puede faltar. Se prueba en las dos rutas: la
        que la guarda y la que informa."""
        _, guardado = servidor.manejar(
            "PUT", "/api/config", {}, {"llave": self.LLAVE}, self.ctx)
        _, visto = servidor.manejar("GET", "/api/config", {}, None, self.ctx)

        for cuerpo in (guardado, visto):
            texto = json.dumps(cuerpo, ensure_ascii=False)
            self.assertNotIn(self.LLAVE, texto)
        self.assertTrue(visto["tiene_llave"])

    def test_se_dice_que_hay_llave_y_de_donde_pero_no_cual(self):
        servidor.manejar("PUT", "/api/config", {}, {"llave": self.LLAVE}, self.ctx)

        _, r = servidor.manejar("GET", "/api/config", {}, None, self.ctx)

        self.assertEqual(r["origen_llave"], "archivo")
        self.assertEqual(r["peticiones_por_segundo"], 10)
        self.assertNotIn("llave", r)

    def test_sin_llave_el_limite_es_de_tres(self):
        _, r = servidor.manejar("GET", "/api/config", {}, None, self.ctx)

        self.assertFalse(r["tiene_llave"])
        self.assertEqual(r["peticiones_por_segundo"], 3)

    def test_guardar_el_correo_deja_lanzar_trabajos(self):
        """Es el punto de todo el cambio: sin correo el lanzamiento daba
        400 y habia que reiniciar el servidor con la variable puesta."""
        _, antes = servidor.manejar("GET", "/api/config", {}, None, self.ctx)
        self.assertFalse(antes["puede_lanzar"])

        servidor.manejar("PUT", "/api/config", {},
                         {"correo": "yo@unam.mx"}, self.ctx)

        _, despues = servidor.manejar("GET", "/api/config", {}, None, self.ctx)
        self.assertTrue(despues["puede_lanzar"])
        self.assertIsNotNone(self.ctx.cliente)

    def test_un_correo_con_dedazo_se_rechaza_antes_de_guardarse(self):
        """NCBI responde 422 a un correo invalido, y en la etapa de PDF eso
        marcaba articulos como permanentemente inaccesibles. Mejor pararlo
        en el formulario."""
        for malo in ("sin-arroba", "@sindominio", "yo@", "yo@sinpunto", ""):
            codigo, _ = servidor.manejar(
                "PUT", "/api/config", {}, {"correo": malo}, self.ctx)
            self.assertEqual(codigo, 400, malo)

        _, r = servidor.manejar("GET", "/api/config", {}, None, self.ctx)
        self.assertEqual(r["correo"], "")

    def test_una_llave_de_largo_equivocado_se_rechaza(self):
        """Un pegado a medias no debe descubrirse hasta la primera
        peticion, cuando ya se marcaron articulos como fallidos."""
        for mala in ("abc", "a" * 35, "a" * 37, "-" * 36):
            codigo, _ = servidor.manejar(
                "PUT", "/api/config", {}, {"llave": mala}, self.ctx)
            self.assertEqual(codigo, 400, mala)

    def test_mandar_la_llave_vacia_la_quita(self):
        servidor.manejar("PUT", "/api/config", {}, {"llave": self.LLAVE}, self.ctx)

        servidor.manejar("PUT", "/api/config", {}, {"llave": ""}, self.ctx)

        _, r = servidor.manejar("GET", "/api/config", {}, None, self.ctx)
        self.assertFalse(r["tiene_llave"])

    def test_un_cuerpo_sin_nada_util_es_400(self):
        codigo, _ = servidor.manejar("PUT", "/api/config", {}, {}, self.ctx)

        self.assertEqual(codigo, 400)

    def test_el_correo_de_la_linea_de_comandos_gana(self):
        """Quien lo puso en --email sabia lo que hacia; el archivo no lo
        pisa."""
        credenciales.guardar_correo("archivo@unam.mx")
        self.ctx.correo_explicito = "flag@unam.mx"

        _, r = servidor.manejar("GET", "/api/config", {}, None, self.ctx)

        self.assertEqual(r["correo"], "flag@unam.mx")
        self.assertEqual(r["origen_correo"], "argumento")

    def test_config_no_acepta_otros_metodos(self):
        for metodo in ("POST", "DELETE"):
            codigo, _ = servidor.manejar(metodo, "/api/config", {}, {}, self.ctx)
            self.assertEqual(codigo, 404, metodo)


# ============================================== el flujo: lanzar y cancelar

class PruebasLanzarFlujo(BasePruebaServidor):
    """POST /api/trabajo con tipo 'flujo'.

    Nada corre de verdad: gestor.lanzar se reemplaza por uno que solo anota
    lo que se le pidió. Lo que se prueba es que llega a flujo.correr, y con
    qué argumentos; el flujo tiene sus propias pruebas.
    """

    def setUp(self):
        super().setUp()
        self.lanzados = []

        def anotar(tipo, funcion, cancelable=False, **kw):
            self.lanzados.append({"tipo": tipo, "funcion": funcion,
                                  "cancelable": cancelable, "kw": kw})

        parche = unittest.mock.patch.object(self.gestor, "lanzar",
                                            side_effect=anotar)
        parche.start()
        self.addCleanup(parche.stop)

    def lanzar(self, cuerpo, ctx=None):
        codigo, objeto = self.pedir("POST", "/api/trabajo", cuerpo=cuerpo,
                                    ctx=ctx)
        self.assertEqual(codigo, 202, objeto)
        self.assertTrue(objeto["ok"])
        return self.lanzados[-1]

    def test_el_flujo_se_lanza_sin_correo_de_ncbi(self):
        """El flujo es todo local: pedirle el correo de NCBI era bloquear
        el pipeline por una credencial que no usa."""
        sin_correo = servidor.Contexto(self.con, self.gestor, None,
                                       self.salida,
                                       flujo_raiz=self.flujo_raiz)

        lanzado = self.lanzar({"tipo": "flujo"}, ctx=sin_correo)

        self.assertEqual(lanzado["tipo"], "flujo")
        self.assertIs(lanzado["funcion"], flujo.correr)
        self.assertTrue(lanzado["cancelable"])

    def test_run_y_fulltext_siguen_pidiendo_el_correo(self):
        sin_correo = servidor.Contexto(self.con, self.gestor, None,
                                       self.salida,
                                       flujo_raiz=self.flujo_raiz)
        for cuerpo in ({"tipo": "run", "nombre": "pa"},
                       {"tipo": "fulltext", "tipo_archivo": "xml"}):
            codigo, objeto = self.pedir("POST", "/api/trabajo", cuerpo=cuerpo,
                                        ctx=sin_correo)
            self.assertEqual(codigo, 400, cuerpo)
            self.assertIn("correo", objeto["error"])
        self.assertEqual(self.lanzados, [])

    def test_sin_mas_datos_corre_todo_con_lo_del_servidor(self):
        lanzado = self.lanzar({"tipo": "flujo"})

        self.assertEqual(lanzado["kw"], {
            "corrida": None, "pasos": None, "forzar": None, "limite": None,
            "sin_reusar": False, "salida": self.flujo_raiz, "datos": None})

    def test_lo_que_manda_el_tablero_llega_validado(self):
        lanzado = self.lanzar({
            "tipo": "flujo", "corrida": 4, "pasos": ["red", "bronce", "red"],
            "forzar": [], "limite": 200, "reusar": False})

        kw = lanzado["kw"]
        self.assertEqual(kw["corrida"], 4)
        # En el orden del flujo y sin repetidos: es lo que se publica.
        self.assertEqual(kw["pasos"], ["bronce", "red"])
        self.assertIsNone(kw["forzar"])
        self.assertEqual(kw["limite"], 200)
        self.assertTrue(kw["sin_reusar"])

    def test_rutas_y_programas_nunca_llegan_del_cuerpo(self):
        """Dónde escribe, de dónde lee y con qué intérprete corre salen del
        servidor. Un 'python_bert' que llegara por HTTP sería ejecutar el
        programa que diga quien mande la petición."""
        self.ctx.datos = os.path.join(self.salida, "datos")

        lanzado = self.lanzar({
            "tipo": "flujo", "salida": "C:/no/debe/usarse",
            "datos": "C:/tampoco", "modelo": "C:/modelo_ajeno",
            "python_bert": "C:/malo.exe", "python_nlp": "C:/malo.exe",
            "reusar_de": ["C:/otra"], "rehacer_operones": True})

        kw = lanzado["kw"]
        self.assertEqual(kw["salida"], self.flujo_raiz)
        self.assertEqual(kw["datos"], self.ctx.datos)
        for clave in ("modelo", "python_bert", "python_nlp", "reusar_de",
                      "rehacer_operones"):
            self.assertNotIn(clave, kw)

    def test_cuerpos_invalidos_son_400_y_no_lanzan_nada(self):
        malos = [
            {"pasos": "bronce"},                 # no es lista
            {"pasos": ["bronce", "magia"]},      # paso que no existe
            {"pasos": []},                       # vacía sería «todos»
            {"pasos": [1, 2]},
            {"forzar": ["nada"]},
            {"forzar": "bronce"},
            {"limite": 0},
            {"limite": 100001},
            {"limite": "muchos"},
            {"corrida": 0},
            {"corrida": "la buena"},
            {"corrida": True},
            {"reusar": "quiza"},
        ]
        for extra in malos:
            cuerpo = dict({"tipo": "flujo"}, **extra)
            objeto = self.falla("POST", "/api/trabajo", 400, cuerpo=cuerpo)
            self.assertTrue(objeto["error"], extra)
        self.assertEqual(self.lanzados, [])

    def test_el_paso_que_no_existe_se_nombra_en_el_error(self):
        objeto = self.falla("POST", "/api/trabajo", 400,
                            cuerpo={"tipo": "flujo", "pasos": ["magia"]})

        self.assertIn("magia", objeto["error"])
        self.assertIn("bronce", objeto["error"])

    def test_con_otro_trabajo_en_curso_es_409(self):
        self.gestor.lanzar.side_effect = trabajos.TrabajoEnCurso(
            "ya hay un trabajo 'run' en curso; espera a que termine")

        objeto = self.falla("POST", "/api/trabajo", 409,
                            cuerpo={"tipo": "flujo"})

        self.assertIn("en curso", objeto["error"])


class PruebasCancelarTrabajo(BasePruebaServidor):
    """POST /api/trabajo/cancelar, con el gestor de verdad."""

    def test_sin_trabajo_es_409(self):
        objeto = self.falla("POST", "/api/trabajo/cancelar", 409, cuerpo={})

        self.assertIn("cancelable", objeto["error"])

    def test_sin_cuerpo_json_es_400(self):
        """Un POST sin cuerpo lo puede mandar cualquier página abierta en el
        mismo navegador, sin preflight. Exigir JSON lo deja fuera, igual que
        en el resto de las rutas que cambian algo."""
        self.falla("POST", "/api/trabajo/cancelar", 400, cuerpo=None)

    def test_solo_por_POST(self):
        for metodo in ("GET", "PUT", "DELETE"):
            self.falla(metodo, "/api/trabajo/cancelar", 404, cuerpo={})

    def test_un_run_en_curso_no_se_puede_cancelar(self):
        arranco = threading.Event()
        seguir = threading.Event()
        self.addCleanup(seguir.set)

        def bloqueado(log):
            arranco.set()
            seguir.wait(ESPERA)

        self.gestor.lanzar("run", bloqueado)
        self.assertTrue(arranco.wait(ESPERA), "el trabajo no arranco")

        self.falla("POST", "/api/trabajo/cancelar", 409, cuerpo={})
        self.assertTrue(self.ok("GET", "/api/trabajo")["activo"])

        seguir.set()
        self.assertTrue(self.gestor.esperar(ESPERA))

    def test_un_flujo_en_curso_se_cancela(self):
        arranco = threading.Event()

        def flujo_falso(log, detener):
            arranco.set()
            if detener.wait(ESPERA):
                raise RuntimeError("Cancelado a petición: paso de prueba")

        self.gestor.lanzar("flujo", flujo_falso, cancelable=True)
        self.assertTrue(arranco.wait(ESPERA), "el flujo no arranco")

        r = self.ok("POST", "/api/trabajo/cancelar", cuerpo={})
        self.assertTrue(r["ok"])
        self.assertTrue(r["trabajo"]["cancelable"])

        self.assertTrue(self.gestor.esperar(ESPERA))
        estado = self.ok("GET", "/api/trabajo")
        self.assertTrue(estado["cancelado"])
        self.assertEqual(estado["error"], "Cancelado a petición")
        self.assertNotIn("detener", estado["parametros"])
        # Terminado, ya no hay nada que cancelar.
        self.falla("POST", "/api/trabajo/cancelar", 409, cuerpo={})


# ================================================= el flujo: lo que se lee

class BasePruebaFlujo(BasePruebaServidor):
    """Una raíz del flujo con una carpeta como la que deja flujo.py.

    La raíz cuelga de un temporal propio para poner señuelos justo afuera:
    si alguna ruta se saliera de la raíz, se llevaría uno, y las pruebas lo
    detectan por su contenido y no por el código de respuesta.
    """

    CARPETA = "corrida4_run22"

    def setUp(self):
        super().setUp()
        base = tempfile.TemporaryDirectory()
        self.addCleanup(base.cleanup)
        afuera = Path(base.name)
        self.raiz = afuera / "flujo"
        self.raiz.mkdir()
        self.ctx.flujo_raiz = str(self.raiz)

        (afuera / ".key").write_text("SECRETO-DEL-FLUJO", encoding="utf-8")
        (afuera / "fuera.csv").write_text("SECRETO-DEL-FLUJO\n",
                                          encoding="utf-8")

        self.carpeta = self.raiz / self.CARPETA
        self.carpeta.mkdir()
        estado = {
            "version": 1, "carpeta": self.CARPETA, "corrida_bronce": 4,
            "modelo": "modelo_limpio_run22", "limite": None,
            "actualizado": "2026-10-08T12:00:00Z",
            "archivos": {"candidatas": "bronce_corrida4_candidatas.csv"},
            "pasos": {
                "operones": {"estatus": "omitido",
                             "nombre": flujo.NOMBRES["operones"],
                             "nota": "falta operones_base.tsv"},
                "bronce": {"estatus": "ok", "nombre": flujo.NOMBRES["bronce"],
                           "segundos": 12.5},
                "pares": {"estatus": "error", "nombre": flujo.NOMBRES["pares"],
                          "segundos": 3.1,
                          "nota": "grn_verificacion.cli terminó con código 1."
                                  "\nÚltimas líneas:\nTraceback (...)"},
            },
        }
        (self.carpeta / "estado.json").write_text(
            json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.carpeta / "red.tsv").write_text(
            "regulador\tblanco\tsigno\nLasR\trhlR\tactivator\n",
            encoding="utf-8")
        (self.carpeta / "evaluacion.json").write_text(
            json.dumps({"precision": 0.44, "n": 50}), encoding="utf-8")
        (self.carpeta / "flujo.log").write_text(
            "▶ Bronce: oraciones candidatas\n", encoding="utf-8")
        # Lo que está en la carpeta pero no se lista: otra extensión y una
        # subcarpeta.
        (self.carpeta / "notas.md").write_text("SECRETO-DEL-FLUJO",
                                               encoding="utf-8")
        (self.carpeta / "sub").mkdir()
        (self.carpeta / "sub" / "x.csv").write_text("SECRETO-DEL-FLUJO\n",
                                                    encoding="utf-8")
        # Un archivo suelto en la raíz no es una carpeta del flujo.
        (self.raiz / "suelto.json").write_text("{}", encoding="utf-8")


class PruebasEstadoDelFlujo(BasePruebaFlujo):

    def test_con_la_raiz_vacia_contesta_y_serializa(self):
        vacia = tempfile.TemporaryDirectory()
        self.addCleanup(vacia.cleanup)
        self.ctx.flujo_raiz = vacia.name

        r = self.ok("GET", "/api/flujo")

        self.assertEqual(r["pasos"], list(flujo.PASOS))
        self.assertEqual(set(r["nombres"]), set(flujo.PASOS))
        self.assertEqual(r["carpetas"], [])
        # La base de la prueba es la del paso 0, sin tablas del bronce.
        self.assertEqual(r["corridas_bronce"], [])
        for clave in ("modelo", "nlp", "reuso", "operones_base"):
            self.assertIsInstance(r["entornos"][clave], bool, clave)

    def test_una_raiz_que_todavia_no_existe_no_es_error(self):
        """Antes de la primera corrida del flujo no hay salidas/flujo."""
        self.ctx.flujo_raiz = str(self.raiz / "todavia_no")

        self.assertEqual(self.ok("GET", "/api/flujo")["carpetas"], [])

    def test_lista_la_carpeta_con_el_estatus_de_cada_paso(self):
        r = self.ok("GET", "/api/flujo")

        self.assertEqual([c["nombre"] for c in r["carpetas"]], [self.CARPETA])
        carpeta = r["carpetas"][0]
        self.assertEqual(carpeta["corrida_bronce"], 4)
        self.assertEqual(carpeta["pasos"]["bronce"], "ok")
        self.assertEqual(carpeta["pasos"]["pares"], "error")
        self.assertEqual(carpeta["pasos"]["red"], "pendiente")

    def test_lista_solo_las_corridas_terminadas_del_bronce(self):
        """Son las que el tablero ofrece para correr el flujo: una cortada
        o de otro paso no tiene CSV de candidatas que volcar."""
        con = bdb.conectar(":memory:")
        self.addCleanup(con.close)
        buena = bdb.abrir_corrida(con, "1", "identificacion", "2")
        bdb.cerrar_corrida(con, buena, "ok", None, 10, 321)
        bdb.abrir_corrida(con, "1", "identificacion", "2")   # cortada
        otra = bdb.abrir_corrida(con, "2", "verificacion", "1")
        bdb.cerrar_corrida(con, otra, "ok")
        ctx = servidor.Contexto(con, self.gestor, self.cliente, self.salida,
                                flujo_raiz=str(self.raiz))

        codigo, r = self.pedir("GET", "/api/flujo", ctx=ctx)

        self.assertEqual(codigo, 200, r)
        self.assertEqual([c["id"] for c in r["corridas_bronce"]], [buena])
        self.assertEqual(r["corridas_bronce"][0]["n_salida"], 321)


class PruebasCarpetaDelFlujo(BasePruebaFlujo):

    def test_trae_el_estado_y_los_archivos_listables(self):
        r = self.ok("GET", "/api/flujo/" + self.CARPETA)

        self.assertEqual(r["nombre"], self.CARPETA)
        self.assertEqual(r["estado"]["pasos"]["bronce"]["estatus"], "ok")
        self.assertEqual([a["nombre"] for a in r["archivos"]],
                         ["estado.json", "evaluacion.json", "flujo.log",
                          "red.tsv"])
        for archivo in r["archivos"]:
            self.assertIsInstance(archivo["bytes"], int)

    def test_lo_que_no_es_carpeta_hija_de_la_raiz_es_404(self):
        for mala in ("no_existe", "..", ".", "..%2f..", "%2e%2e",
                     "..%2fflujo", "suelto.json", self.CARPETA + "%2fsub",
                     "C:%2fWindows"):
            objeto = self.falla("GET", "/api/flujo/" + mala, 404)
            self.assertNotIn("SECRETO", json.dumps(objeto), mala)

    def test_solo_por_GET(self):
        for ruta in ("/api/flujo", "/api/flujo/" + self.CARPETA):
            for metodo in ("POST", "PUT", "DELETE"):
                self.falla(metodo, ruta, 404, cuerpo={})


class PruebasArchivosDelFlujo(BasePruebaFlujo):
    """GET /api/flujo/<carpeta>/archivos/<nombre>.

    Como con el texto y el PDF de un documento, lo que hay que defender no
    es que sirva el archivo correcto, sino que no exista forma de que sirva
    otro.
    """

    def ruta(self, nombre, carpeta=None):
        return "/api/flujo/%s/archivos/%s" % (carpeta or self.CARPETA, nombre)

    def test_un_archivo_listado_sale_como_descarga_con_su_tipo(self):
        codigo, objeto = self.pedir("GET", self.ruta("red.tsv"))

        self.assertEqual(codigo, 200)
        self.assertIsInstance(objeto, servidor.Archivo)
        self.assertEqual(objeto.ruta.resolve(),
                         (self.carpeta / "red.tsv").resolve())
        self.assertEqual(objeto.tipo_mime,
                         "text/tab-separated-values; charset=utf-8")
        self.assertEqual(objeto.descarga_como, "red.tsv")

    def test_cada_extension_que_se_lista_tiene_su_tipo(self):
        """Si flujo.ARCHIVO_VALIDO aceptara una extensión sin tipo aquí, el
        archivo se listaría en el tablero y su liga daría 404."""
        extensiones = re.search(r"\(([a-z|]+)\)\$",
                                flujo.ARCHIVO_VALIDO.pattern).group(1)
        for ext in extensiones.split("|"):
            self.assertIn(ext, servidor.TIPOS_FLUJO, ext)
        for nombre, tipo in (("evaluacion.json", "application/json"),
                             ("flujo.log", "text/plain")):
            _, objeto = self.pedir("GET", self.ruta(nombre))
            self.assertTrue(objeto.tipo_mime.startswith(tipo), nombre)

    def test_ver_abre_el_json_y_el_log_en_vez_de_bajarlos(self):
        """El tablero lee evaluacion.json para pintar las cifras, y
        flujo.log guarda entera la salida que la consola recorta."""
        for nombre in ("evaluacion.json", "flujo.log"):
            _, objeto = self.pedir("GET", self.ruta(nombre), {"ver": "1"})
            self.assertIsNone(objeto.descarga_como, nombre)
            _, objeto = self.pedir("GET", self.ruta(nombre))
            self.assertEqual(objeto.descarga_como, nombre)

    def test_ver_no_cambia_nada_en_lo_que_no_se_lee_en_la_pestana(self):
        _, objeto = self.pedir("GET", self.ruta("red.tsv"), {"ver": "1"})

        self.assertEqual(objeto.descarga_como, "red.tsv")

    def test_ver_con_valor_raro_es_400(self):
        self.falla("GET", self.ruta("red.tsv"), 400, {"ver": "quiza"})

    def test_ninguna_ruta_saca_un_archivo_de_fuera_de_la_carpeta(self):
        """La prueba que no puede faltar: travesías, subcarpetas, nombres
        sin listar, extensiones fuera de la lista y variantes de
        mayúsculas, que en Windows abrirían el mismo archivo."""
        intentos = [
            self.ruta("..%2f.key"), self.ruta("..%2f..%2f.key"),
            self.ruta("..%2ffuera.csv"), self.ruta("%2e%2e%2ffuera.csv"),
            self.ruta("..%5cfuera.csv"), self.ruta("sub%2fx.csv"),
            "/api/flujo/%s/archivos/sub/x.csv" % self.CARPETA,
            self.ruta("x.csv", carpeta="sub"),
            self.ruta("fuera.csv", carpeta=".."),
            self.ruta("fuera.csv", carpeta="..%2f"),
            self.ruta(".key", carpeta=".."),
            self.ruta("no_listado.csv"), self.ruta("notas.md"),
            self.ruta("RED.TSV"), self.ruta("Red.tsv"),
            self.ruta("red.tsv%00.key"), self.ruta("red.tsv:secreto"),
            self.ruta("estado.json", carpeta="no_existe"),
            "/api/flujo/archivos/red.tsv",
            "/api/flujo/%s/archivos" % self.CARPETA,
            "/api/flujo/%s/otros/red.tsv" % self.CARPETA,
        ]
        for ruta in intentos:
            codigo, objeto = self.pedir("GET", ruta)
            self.assertEqual(codigo, 404, ruta)
            self.assertNotIsInstance(objeto, servidor.Archivo, ruta)
            self.assertNotIn("SECRETO", json.dumps(objeto, ensure_ascii=False),
                             ruta)

    def test_solo_por_GET(self):
        for metodo in ("POST", "PUT", "DELETE"):
            self.falla(metodo, self.ruta("red.tsv"), 404, cuerpo={})


# ======================================== la entrega de archivos, en bytes

class PruebasEntregaDeArchivos(PruebaSinRed):
    """_responder_archivo sin socket: el manejador escribe en un BytesIO.

    Es la única pieza del HTTP que tiene lógica propia: manda el archivo en
    bloques, con el largo del archivo abierto y sin pasarse de él.
    """

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def manejador(self, wfile=None):
        h = servidor.ManejadorHTTP.__new__(servidor.ManejadorHTTP)
        h.wfile = wfile if wfile is not None else io.BytesIO()
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.requestline = "GET /prueba HTTP/1.1"
        h.client_address = ("127.0.0.1", 0)
        h.close_connection = False
        return h

    def partir(self, crudo):
        cabeza, cuerpo = crudo.split(b"\r\n\r\n", 1)
        lineas = cabeza.decode("latin-1").split("\r\n")
        encabezados = {}
        for linea in lineas[1:]:
            clave, valor = linea.split(":", 1)
            encabezados[clave.strip().lower()] = valor.strip()
        return lineas[0], encabezados, cuerpo

    def test_un_archivo_grande_sale_completo_y_en_bloques(self):
        datos = bytes(range(256)) * 2500           # 640 KB, más de dos bloques
        self.assertGreater(len(datos), 2 * servidor.BLOQUE_ARCHIVO)
        ruta = self.dir / "candidatas.csv"
        ruta.write_bytes(datos)
        h = self.manejador()

        h._responder_archivo(200, servidor.Archivo(
            ruta, "text/csv; charset=utf-8", descarga_como="candidatas.csv"))

        estado, enc, cuerpo = self.partir(h.wfile.getvalue())
        self.assertIn("200", estado)
        self.assertEqual(enc["content-length"], str(len(datos)))
        self.assertEqual(enc["content-disposition"],
                         'attachment; filename="candidatas.csv"')
        self.assertEqual(enc["x-content-type-options"], "nosniff")
        self.assertEqual(cuerpo, datos)
        self.assertFalse(h.close_connection)

    def test_sin_nombre_de_descarga_se_abre_en_la_pestana(self):
        """La página, el escudo y el PDF del lector no se bajan."""
        ruta = self.dir / "a.pdf"
        ruta.write_bytes(b"%PDF-1.7\n")
        h = self.manejador()

        h._responder_archivo(200, servidor.Archivo(ruta, "application/pdf"))

        _, enc, cuerpo = self.partir(h.wfile.getvalue())
        self.assertNotIn("content-disposition", enc)
        self.assertEqual(cuerpo, b"%PDF-1.7\n")

    def test_un_archivo_que_crece_no_manda_mas_de_lo_prometido(self):
        """flujo.log crece mientras el flujo corre. Con HTTP/1.1 los bytes
        de más se leerían como el principio de la siguiente respuesta."""
        ruta = self.dir / "flujo.log"
        original = b"una linea del flujo\n" * 30000      # ~600 KB
        ruta.write_bytes(original)

        class CreceAlEscribir(io.BytesIO):
            def write(this, b):
                with open(ruta, "ab") as f:
                    f.write(b"otra linea\n" * 2000)
                return io.BytesIO.write(this, b)

        h = self.manejador(CreceAlEscribir())
        h._responder_archivo(200, servidor.Archivo(
            ruta, "text/plain; charset=utf-8"))

        _, enc, cuerpo = self.partir(h.wfile.getvalue())
        self.assertEqual(int(enc["content-length"]), len(original))
        self.assertEqual(cuerpo, original)

    def test_si_quien_descarga_corta_no_truena(self):
        ruta = self.dir / "grande.csv"
        ruta.write_bytes(b"x" * (3 * servidor.BLOQUE_ARCHIVO))

        class Cortada(io.BytesIO):
            escrituras = 0

            def write(this, b):
                this.escrituras += 1
                if this.escrituras > 2:
                    raise ConnectionAbortedError("el navegador cerró")
                return io.BytesIO.write(this, b)

        h = self.manejador(Cortada())
        h._responder_archivo(200, servidor.Archivo(ruta, "text/csv"))

        self.assertTrue(h.close_connection)

    def test_un_archivo_que_ya_no_esta_es_404_en_json(self):
        h = self.manejador()

        h._responder_archivo(200, servidor.Archivo(
            self.dir / "no_esta.csv", "text/csv", descarga_como="no_esta.csv"))

        estado, enc, cuerpo = self.partir(h.wfile.getvalue())
        self.assertIn("404", estado)
        self.assertNotIn("content-disposition", enc)
        self.assertIn("no_esta.csv",
                      json.loads(cuerpo.decode("utf-8"))["error"])

    def test_el_nombre_de_la_descarga_no_parte_la_cabecera(self):
        ruta = self.dir / "a.csv"
        ruta.write_bytes(b"a\n")
        h = self.manejador()

        h._responder_archivo(200, servidor.Archivo(
            ruta, "text/csv", descarga_como='x"\r\nSet-Cookie: a=b.csv'))

        _, enc, _ = self.partir(h.wfile.getvalue())
        self.assertNotIn("set-cookie", enc)
        self.assertEqual(enc["content-disposition"],
                         'attachment; filename="x___Set-Cookie__a_b.csv"')


# ================================================== el cierre del servidor

class PruebasCierre(PruebaSinRed):
    """Al cerrar el tablero, un trabajo cancelable se cancela y se espera:
    los pasos del flujo son procesos aparte que sobrevivirían al servidor,
    y su candado impediría la siguiente corrida."""

    def setUp(self):
        super().setUp()
        self.gestor = trabajos.Gestor()
        self.addCleanup(self.gestor.esperar, ESPERA)
        self.mensajes = []

    def test_sin_trabajo_no_hace_ni_dice_nada(self):
        self.assertTrue(servidor.detener_al_cerrar(
            self.gestor, log=self.mensajes.append))
        self.assertEqual(self.mensajes, [])

    def test_un_flujo_en_curso_se_cancela_y_se_espera(self):
        arranco = threading.Event()

        def largo(log, detener):
            arranco.set()
            detener.wait(ESPERA)

        self.gestor.lanzar("flujo", largo, cancelable=True)
        self.assertTrue(arranco.wait(ESPERA))

        self.assertTrue(servidor.detener_al_cerrar(
            self.gestor, espera=ESPERA, log=self.mensajes.append))

        estado = self.gestor.estado()
        self.assertFalse(estado["activo"])
        self.assertTrue(estado["cancelado"])
        self.assertIn("cancelarlo", self.mensajes[0])
        self.assertIn("Se detuvo", self.mensajes[-1])

    def test_si_no_se_detiene_a_tiempo_lo_dice(self):
        arranco = threading.Event()
        soltar = threading.Event()
        self.addCleanup(soltar.set)

        def terco(log, detener):
            arranco.set()
            soltar.wait(ESPERA)

        self.gestor.lanzar("flujo", terco, cancelable=True)
        self.assertTrue(arranco.wait(ESPERA))

        self.assertFalse(servidor.detener_al_cerrar(
            self.gestor, espera=0.05, log=self.mensajes.append))
        self.assertIn(".flujo.lock", self.mensajes[-1])

    def test_un_run_en_curso_solo_se_avisa(self):
        arranco = threading.Event()
        seguir = threading.Event()
        self.addCleanup(seguir.set)

        def bloqueado(log):
            arranco.set()
            seguir.wait(ESPERA)

        self.gestor.lanzar("run", bloqueado)
        self.assertTrue(arranco.wait(ESPERA))

        self.assertFalse(servidor.detener_al_cerrar(
            self.gestor, espera=ESPERA, log=self.mensajes.append))
        self.assertIn("idempotente", self.mensajes[0])
        self.assertTrue(self.gestor.estado()["activo"])


# =================================================== rutas por omisión

class PruebasRutasPorOmision(PruebaSinRed):
    """Las rutas de datos siguen la precedencia de CLAUDE.md: flag, luego
    GRN_DATOS, luego ./datos. La literal 'datos/fulltext' se quitó al tocar
    el archivo, como pide la regla."""

    def test_la_salida_del_fulltext_sigue_la_precedencia(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"GRN_DATOS": "D:/lab/datos"}):
            self.assertEqual(servidor.salida_por_omision(),
                             os.path.join("D:/lab/datos", "fulltext"))
            self.assertEqual(servidor.salida_por_omision("E:/flag"),
                             os.path.join("E:/flag", "fulltext"))
        with unittest.mock.patch.dict(os.environ, {}):
            os.environ.pop("GRN_DATOS", None)
            self.assertEqual(servidor.salida_por_omision(),
                             os.path.join("datos", "fulltext"))

    def test_el_contexto_sin_rutas_usa_las_de_omision(self):
        con = db.conectar(":memory:")
        self.addCleanup(con.close)

        ctx = servidor.Contexto(con, trabajos.Gestor())

        self.assertEqual(ctx.flujo_raiz, flujo.RAIZ_FLUJO)
        self.assertIsNone(ctx.datos)


class PruebasHostDelTablero(PruebaSinRed):
    """Contra el DNS rebinding: la página hostil queda en el mismo origen
    que el tablero, pero el navegador pone su dominio en Host."""

    def test_solo_el_nombre_de_esta_maquina_con_cualquier_puerto(self):
        """El puerto no protege del rebinding y rompía el túnel SSH a otro
        puerto local (`ssh -L 8766:127.0.0.1:8765`)."""
        for host in ("127.0.0.1:8765", "localhost:8765", "LOCALHOST:8765",
                     " 127.0.0.1:8765 ", "localhost:8766", "127.0.0.1",
                     "localhost"):
            self.assertTrue(servidor.host_permitido(host), host)
        for host in (None, "", "atacante.example:8765", "evil.com",
                     "127.0.0.1.nip.io:8765", "localhost.evil.com:8765",
                     "127.0.0.2:8765"):
            self.assertFalse(servidor.host_permitido(host), host)

    def test_el_manejador_responde_403_a_otro_host(self):
        """Por `_atender` de verdad, sin socket: quitar la llamada dejaba la
        suite en verde."""
        h = servidor.ManejadorHTTP.__new__(servidor.ManejadorHTTP)
        h.wfile = io.BytesIO()
        h.request_version = "HTTP/1.1"
        h.command = "GET"
        h.requestline = "GET / HTTP/1.1"
        h.client_address = ("127.0.0.1", 0)
        h.close_connection = False
        h.path = "/"
        h.headers = {"Host": "evil.com:8765"}
        h.server = unittest.mock.Mock(server_address=("127.0.0.1", 8765))
        h._atender("GET")
        self.assertTrue(h.wfile.getvalue().startswith(b"HTTP/1.1 403"))
        self.assertTrue(h.close_connection)


# ===================================================== reglas de la página

class PruebasReglasDeLaPagina(BasePruebaServidor):

    def setUp(self):
        super().setUp()
        self.pagina = servidor.RUTA_PAGINA.read_text(encoding="utf-8")

    def test_la_pagina_nunca_asigna_html_crudo(self):
        """La regla de oro del tablero: lo que llega del servidor (títulos
        de PubMed, la nota de error de un paso, nombres de archivo) se pinta
        con textContent. Con innerHTML, un '<' de un nombre de gen o de una
        traza sería HTML corriendo en un origen que puede borrar documentos."""
        self.assertEqual(
            re.findall(r"\.(?:innerHTML|outerHTML)\s*\+?=(?!=)", self.pagina),
            [])
        self.assertNotRegex(self.pagina, r"insertAdjacentHTML\s*\(")
        self.assertNotRegex(self.pagina, r"document\.write\s*\(")

    def test_hay_pestana_pipeline_con_su_seccion(self):
        self.assertIn('data-seccion="pipeline"', self.pagina)
        self.assertIn('id="sec-pipeline"', self.pagina)
