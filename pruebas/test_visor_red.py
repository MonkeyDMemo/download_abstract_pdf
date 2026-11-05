# -*- coding: utf-8 -*-
"""El visor de la red: autocontenido y a prueba de oraciones raras."""

import csv
import io
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import visor_red  # noqa: E402


def _tsv(ruta, columnas, filas):
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        e = csv.DictWriter(f, fieldnames=columnas, delimiter="\t",
                           lineterminator="\n")
        e.writeheader()
        e.writerows(filas)


class PruebasVisor(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.c = tmp.name
        _tsv(os.path.join(self.c, "red.tsv"),
             ["tf", "blanco", "signo", "conflicto", "n_evidencias",
              "n_articulos"],
             [{"tf": "LasR", "blanco": "lasB", "signo": "activates",
               "conflicto": "false", "n_evidencias": "5", "n_articulos": "2"}])
        _tsv(os.path.join(self.c, "red_evidencias.tsv"),
             ["tf", "blanco", "id_par", "pmid", "seccion", "probabilidad",
              "oracion"],
             [{"tf": "LasR", "blanco": "lasB", "id_par": "p%d" % i,
               "pmid": str(i), "seccion": "abstract",
               "probabilidad": str(0.5 + i / 10),
               "oracion": "LasR activates lasB </script><!-- %d" % i}
              for i in range(5)])
        self.salida = os.path.join(self.c, "visor.html")

    def _datos(self, html):
        m = re.search(r'<script id="datos" type="application/json">(.*?)'
                      r'</script>', html, re.S)
        self.assertIsNotNone(m)
        return json.loads(m.group(1)) if m else None

    def test_las_oraciones_no_cierran_el_script(self):
        visor_red.escribir(self.c, self.salida)
        with io.open(self.salida, encoding="utf-8") as f:
            html = f.read()
        self.assertEqual(html.count("</script>"), 2)
        self.assertNotIn("<!-- ", html.split('id="datos"')[1].split("</script>")[0])
        datos = self._datos(html)
        self.assertIn("</script>", datos["aristas"][0][7][0][2])

    def test_lleva_las_oraciones_de_mayor_probabilidad_hasta_el_tope(self):
        datos = visor_red.datos_de_carpeta(self.c, max_oraciones=3)
        oraciones = datos["aristas"][0][7]
        self.assertEqual(len(oraciones), 3)
        self.assertEqual([o[0] for o in oraciones], ["4", "3", "2"])
        self.assertFalse(datos["juez"])

    def test_no_carga_nada_de_internet(self):
        """Se abre sin red. Los enlaces a PubMed son a propósito: no se
        cargan, se siguen con un clic."""
        visor_red.escribir(self.c, self.salida)
        with io.open(self.salida, encoding="utf-8") as f:
            html = f.read()
        cargados = re.findall(r'src\s*=\s*["\'](?:https?:)?//', html)
        cargados += re.findall(r'<link[^>]*href\s*=\s*["\'](?:https?:)?//',
                               html)
        cargados += re.findall(r'@import|url\(\s*["\']?(?:https?:)?//', html)
        self.assertEqual(cargados, [])
        enlaces = re.findall(r'href="(https?://[^/"$]+)', html)
        self.assertEqual(set(enlaces), {"https://pubmed.ncbi.nlm.nih.gov"})


if __name__ == "__main__":
    unittest.main()
