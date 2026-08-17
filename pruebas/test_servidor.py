# -*- coding: utf-8 -*-
"""La API del tablero, probada sin abrir un solo puerto.

manejar() es una funcion normal: recibe metodo, ruta, parametros, cuerpo
y contexto, y devuelve (codigo, objeto). Por eso aqui no hay sockets, ni
puertos ocupados, ni firewalls de por medio; se prueba la API completa
como se prueba cualquier otra funcion.

Dos invariantes se revisan en CADA peticion, dentro del ayudante pedir():
que la respuesta sobreviva a json.dumps (un sqlite3.Row olvidado en un
listado tumba el endpoint en produccion y aqui no) y que nunca se
devuelva un archivo del disco fuera de la ruta '/'.
"""

import json
import tempfile
import threading
from pathlib import Path

import servidor
from grn_etl import db, pubmed, trabajos

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

        self.cliente = ClienteFalso()
        self.ctx = servidor.Contexto(self.con, self.gestor, self.cliente,
                                     self.salida)
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
        codigo, objeto = servidor.manejar(
            metodo, ruta, params or {}, cuerpo, ctx or self.ctx)
        if isinstance(objeto, servidor.Archivo):
            # Solo '/' entrega un archivo. Cualquier otra ruta que lo haga
            # es una fuga del directorio del proyecto.
            self.assertEqual(ruta, "/", f"{ruta} devolvio un archivo")
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
        self.assertIn("NCBI_EMAIL", objeto["error"])
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
