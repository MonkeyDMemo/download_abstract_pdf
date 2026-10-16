# -*- coding: utf-8 -*-
"""Mas de 10,000 resultados: la consulta se parte por fecha y se une entera.

NBK25499: PubMed solo entrega los primeros 10,000 de un conjunto, y la
receta de subir retstart no aplica a PubMed. Antes el ETL fallaba a
proposito y pedia partir por anio a mano. Una consulta de 83 638 articulos
corrida asi, con limite, dejo 5 540 documentos truncados que la bitacora
presentaba como corridas 'ok'. Estas pruebas fijan la particion automatica:
nada se trunca, nada se duplica, y lo que no se puede partir falla con el
dia y el conteo en el mensaje.

El tope se parchea a 50 para no fabricar 10,000 ids por prueba.
"""

import datetime
import unittest.mock

from grn_etl import pubmed

from .falsos import ClienteFalso, PruebaSinRed

TOPE = 50


def universo_fechado(n=120, anio_inicial=1995, anios=11):
    """n PMIDs repartidos en `anios` anios, sin dos en el mismo dia.

    anio = i % 11, mes = i % 12, dia = i % 27: el minimo comun multiplo de
    los tres modulos es 1 188 > 120, asi que no hay dos PMIDs con la misma
    fecha y un tope de 1 obliga a un tramo por PMID. Cada anio recibe 10 u
    11 PMIDs.
    """
    fechas = {}
    for i in range(n):
        fechas[str(700000 + i)] = "%04d/%02d/%02d" % (
            anio_inicial + i % anios, 1 + i % 12, 1 + i % 27)
    return fechas


def parchar_tope(prueba, tope=TOPE):
    parche = unittest.mock.patch.object(pubmed, "TOPE_ESEARCH", tope)
    parche.start()
    prueba.addCleanup(parche.stop)


def esearch_con_fechas(cliente):
    return [c[2] for c in cliente.llamadas
            if c[1] == "esearch.fcgi" and "mindate" in c[2]]


class PruebasFechas(PruebaSinRed):

    def test_una_fecha_corta_se_expande_al_primero_o_al_ultimo_dia(self):
        self.assertEqual(pubmed._fecha("2021"), datetime.date(2021, 1, 1))
        self.assertEqual(pubmed._fecha("2021", fin=True), datetime.date(2021, 12, 31))
        self.assertEqual(pubmed._fecha("2021/02"), datetime.date(2021, 2, 1))
        self.assertEqual(pubmed._fecha("2021/02", fin=True), datetime.date(2021, 2, 28))
        self.assertEqual(pubmed._fecha("2024/02", fin=True), datetime.date(2024, 2, 29))
        self.assertEqual(pubmed._fecha("2021/03/05", fin=True), datetime.date(2021, 3, 5))

    def test_una_fecha_mal_escrita_es_ErrorPubMed_con_la_fecha(self):
        for mala in ("ayer", "2021/13", "2021/02/30", "2021/1/2/3", ""):
            with self.assertRaises(pubmed.ErrorPubMed) as ctx:
                pubmed._fecha(mala)
            self.assertIn(repr(mala)[1:-1], str(ctx.exception))

    def test_el_punto_medio_se_alinea_al_anio_y_dentro_del_anio_a_dias(self):
        d = datetime.date
        self.assertEqual(pubmed._punto_medio(d(1700, 1, 1), d(2999, 12, 31)),
                         d(2349, 12, 31))
        self.assertEqual(pubmed._punto_medio(d(1990, 6, 15), d(1995, 3, 10)),
                         d(1992, 12, 31))
        # Dos anios seguidos: el corte cae en el 31 de diciembre del primero.
        self.assertEqual(pubmed._punto_medio(d(2020, 12, 31), d(2021, 1, 1)),
                         d(2020, 12, 31))
        # Dentro de un anio ya no hay 31 de diciembre que sirva: mitad de dias.
        self.assertEqual(pubmed._punto_medio(d(2020, 1, 1), d(2020, 12, 31)),
                         d(2020, 7, 1))
        self.assertEqual(pubmed._punto_medio(d(2020, 3, 5), d(2020, 3, 6)),
                         d(2020, 3, 5))


class PruebasTramos(PruebaSinRed):

    def setUp(self):
        super().setUp()
        parchar_tope(self)
        self.fechas = universo_fechado()
        self.universo = sorted(self.fechas)
        self.mensajes = []

    def log(self, msg):
        self.mensajes.append(msg)

    def test_hasta_el_tope_es_una_sola_peticion_y_sin_fechas(self):
        cliente = ClienteFalso(universo=self.universo[:40], fechas=self.fechas)

        total, pmids = pubmed.buscar_pmids(cliente, "q", log=self.log)

        self.assertEqual((total, pmids), (40, self.universo[:40]))
        self.assertEqual(cliente.n_eutils("esearch.fcgi"), 1)
        self.assertNotIn("datetype", cliente.llamadas[0][2])
        self.assertEqual(self.mensajes, [])

    def test_pasar_del_tope_parte_por_fecha_y_la_union_es_el_universo(self):
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)
        tramos = []

        total, pmids = pubmed.buscar_pmids(cliente, "q", tramos=tramos,
                                           log=self.log)

        self.assertEqual(total, 120)
        self.assertEqual(sorted(pmids), self.universo, "se perdio o sobro algo")
        self.assertEqual(len(pmids), 120, "hay PMIDs repetidos")
        self.assertTrue(tramos)
        for t in tramos:
            self.assertLessEqual(t["n"], TOPE)
            self.assertNotIn("pmids", t, "los tramos van a la bitacora sin ids")
        for antes, despues in zip(tramos, tramos[1:]):
            self.assertLess(antes["hasta"], despues["desde"], "no son cronologicos")
        for params in esearch_con_fechas(cliente):
            self.assertEqual(params["datetype"], "pdat")
            self.assertEqual(params["retmax"], str(TOPE))
        self.assertTrue(any("se parte por fecha" in m for m in self.mensajes))

    def test_los_tramos_se_alinean_al_anio_y_son_los_esperados(self):
        """Con 10-11 articulos por anio de 1995 a 2005 y tope 50, la
        biseccion alineada al anio da exactamente estos cinco tramos. Si
        cambia la regla del punto medio, esta prueba lo dice."""
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)
        tramos = []

        pubmed.buscar_pmids(cliente, "q", tramos=tramos)

        self.assertEqual(
            [(t["desde"], t["hasta"], t["n"]) for t in tramos],
            [("1995/01/01", "1997/12/31", 33), ("1998/01/01", "1999/12/31", 22),
             ("2000/01/01", "2002/12/31", 33), ("2003/01/01", "2004/12/31", 22),
             ("2005/01/01", "2024/12/31", 10)])
        # 1 esearch inicial + 21 nodos del arbol: las mitades vacias cuestan
        # una peticion cada una y se descartan. Frente a 419 efetch para
        # 83 638 articulos, es ruido.
        self.assertLessEqual(cliente.n_eutils("esearch.fcgi"), 22)

    def test_un_dia_que_rebasa_el_tope_falla_con_el_dia_y_el_tope(self):
        """Un solo dia no se puede partir mas. Devolver 50 de 60 seria
        truncar en silencio, que es justo lo que esto vino a quitar."""
        fechas = {str(900000 + i): "2020/03/05" for i in range(60)}
        cliente = ClienteFalso(universo=sorted(fechas), fechas=fechas)

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.buscar_pmids(cliente, "q")

        mensaje = str(ctx.exception)
        self.assertIn("2020/03/05", mensaje)
        self.assertIn("60", mensaje)
        self.assertIn(str(TOPE), mensaje)

    def test_con_limite_no_se_parte_aunque_rebase(self):
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)

        total, pmids = pubmed.buscar_pmids(cliente, "q", limite=5)

        self.assertEqual((total, len(pmids)), (120, 5))
        self.assertEqual(cliente.n_eutils("esearch.fcgi"), 1)

    def test_las_fechas_del_usuario_acotan_la_particion(self):
        parchar_tope(self, 20)
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)
        tramos = []

        total, pmids = pubmed.buscar_pmids(cliente, "q", mindate="1998",
                                           maxdate="2001", tramos=tramos)

        esperados = sorted(p for p, f in self.fechas.items()
                           if "1998/01/01" <= f <= "2001/12/31")
        self.assertEqual(sorted(pmids), esperados)
        self.assertEqual(total, len(esperados))
        primero = cliente.llamadas[0][2]
        self.assertEqual((primero["mindate"], primero["maxdate"]),
                         ("1998/01/01", "2001/12/31"))
        for t in tramos:
            self.assertGreaterEqual(t["desde"], "1998/01/01")
            self.assertLessEqual(t["hasta"], "2001/12/31")
        self.assertGreater(len(tramos), 1)

    def test_una_fecha_corta_viaja_como_dia_completo(self):
        cliente = ClienteFalso(universo=self.universo[:10], fechas=self.fechas)

        pubmed.buscar_pmids(cliente, "q", mindate="1995", maxdate="1996/02")

        params = cliente.llamadas[0][2]
        self.assertEqual(params["datetype"], "pdat")
        self.assertEqual(params["mindate"], "1995/01/01")
        self.assertEqual(params["maxdate"], "1996/02/29")

    def test_un_rango_al_reves_o_una_fecha_rota_no_llegan_a_ncbi(self):
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.buscar_pmids(cliente, "q", mindate="2022", maxdate="2021")
        self.assertIn("al reves", str(ctx.exception))
        with self.assertRaises(pubmed.ErrorPubMed):
            pubmed.buscar_pmids(cliente, "q", mindate="ayer")
        self.assertEqual(cliente.llamadas, [])

    def test_mas_de_max_tramos_es_error(self):
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)

        with self.assertRaises(pubmed.ErrorPubMed) as ctx:
            pubmed.tramos_por_fecha(cliente, "q", pubmed.FECHA_MINIMA,
                                    pubmed.FECHA_MAXIMA, tope=1, max_tramos=10)

        self.assertIn("10 tramos", str(ctx.exception))

    def test_la_union_menor_que_el_total_avisa_fuerte(self):
        """Cinco PMIDs sin fecha: la busqueda sin fechas los cuenta y ningun
        tramo los trae. Se avisa con la diferencia; la corrida sigue."""
        fechas = dict(self.fechas)
        for p in self.universo[:5]:
            del fechas[p]
        cliente = ClienteFalso(universo=self.universo, fechas=fechas)

        total, pmids = pubmed.buscar_pmids(cliente, "q", log=self.log)

        self.assertEqual((total, len(pmids)), (120, 115))
        avisos = [m for m in self.mensajes if "AVISO" in m]
        self.assertEqual(len(avisos), 1)
        self.assertIn("faltan 5", avisos[0])

    def test_un_articulo_con_dos_fechas_cae_en_dos_tramos_y_se_cuenta_una_vez(self):
        fechas = dict(self.fechas)
        fechas[self.universo[0]] = [fechas[self.universo[0]], "2003/06/06"]
        cliente = ClienteFalso(universo=self.universo, fechas=fechas)

        total, pmids = pubmed.buscar_pmids(cliente, "q", log=self.log)

        self.assertEqual((total, len(pmids)), (120, 120))
        self.assertFalse(any("AVISO" in m for m in self.mensajes))
        self.assertTrue(any("dos tramos" in m for m in self.mensajes))

    def test_los_avisos_de_ncbi_no_se_repiten_por_tramo(self):
        cliente = ClienteFalso(universo=self.universo, fechas=self.fechas)
        cliente.avisos_esearch = ["quorum sensin"]
        avisos = []

        pubmed.buscar_pmids(cliente, "q", avisos=avisos)

        self.assertEqual(len(avisos), 1)
        self.assertIn("quorum sensin", avisos[0])


class PruebasIterarArticulos(PruebaSinRed):

    def test_rinde_por_lote_con_el_avance_y_cubre_todo_sin_repetir(self):
        cliente = ClienteFalso(universo=["1", "2", "3", "4", "5"])

        lotes = list(pubmed.iterar_articulos(cliente, ["1", "2", "3", "4", "5"], 2))

        self.assertEqual([(len(r), h, t) for r, h, t in lotes],
                         [(2, 2, 5), (2, 4, 5), (1, 5, 5)])
        self.assertEqual(cliente.pmids_pedidos(), ["1", "2", "3", "4", "5"])
        self.assertEqual(cliente.n_eutils("efetch.fcgi"), 3)

    def test_traer_articulos_sigue_devolviendo_todo_de_una_vez(self):
        cliente = ClienteFalso(universo=["1", "2", "3"])
        avances = []

        regs = pubmed.traer_articulos(cliente, ["1", "2", "3"], 2,
                                      al_avanzar=lambda *a: avances.append(a))

        self.assertEqual([r["pmid"] for r in regs], ["1", "2", "3"])
        self.assertEqual(avances, [(2, 3, 2), (3, 3, 1)])


class PruebasFallasPorLlamada(PruebaSinRed):
    """La falla por callable del cliente falso, que usan las pruebas del
    guardado por lote: falla solo en la n-esima llamada."""

    def test_falla_solo_en_la_llamada_indicada(self):
        cliente = ClienteFalso(
            universo=["1", "2", "3", "4"],
            fallas={"efetch.fcgi": lambda n, params: (
                pubmed.ErrorPubMed("se cayo") if n == 2 else None)})

        lotes = pubmed.iterar_articulos(cliente, ["1", "2", "3", "4"], 2)
        regs, _, _ = next(lotes)
        self.assertEqual(len(regs), 2)
        with self.assertRaises(pubmed.ErrorPubMed):
            next(lotes)
