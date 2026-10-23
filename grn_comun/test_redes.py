"""Los nombres de archivo de una red, una sola fuente para el paso 2 y el 3."""

import unittest

from grn_comun import redes


class PruebasNombres(unittest.TestCase):

    def test_sin_nombre_son_los_de_la_red_oficial(self):
        self.assertEqual(redes.archivos_de_red(),
                         ("red.tsv", "red_evidencias.tsv", "red_informe.json"))

    def test_con_nombre(self):
        self.assertEqual(redes.archivos_de_red("signo"),
                         ("red_signo.tsv", "red_signo_evidencias.tsv",
                          "red_signo_informe.json"))

    def test_rechaza_lo_que_no_cabe_en_un_nombre_de_archivo(self):
        for malo in ("", "Signo", "signo\n", "signo-2", "a" * 41,
                     "evidencias", "informe", None, 3, "../x"):
            with self.subTest(nombre=malo):
                self.assertFalse(redes.nombre_valido(malo))
                if malo is not None:
                    with self.assertRaises(ValueError):
                        redes.archivos_de_red(malo)

    def test_el_salto_de_linea_final_no_pasa(self):
        """`match` con `$` lo aceptaba; `fullmatch` no."""
        self.assertIsNotNone(redes.re.match(r"^[a-z0-9_]{1,40}$", "x\n"))
        self.assertFalse(redes.nombre_valido("x\n"))

    def test_consolidar_usa_esta_fuente(self):
        from grn_red import consolidar
        self.assertIs(consolidar.NOMBRE_VALIDO, redes.NOMBRE_VALIDO)
        self.assertEqual(consolidar.nombres_de_salida("recomendada"),
                         redes.archivos_de_red("recomendada"))


if __name__ == "__main__":
    unittest.main()
