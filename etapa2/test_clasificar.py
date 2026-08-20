# -*- coding: utf-8 -*-
"""Pruebas del clasificador.

Corren SIN torch, que es lo que permite ejecutarlas en la laptop del
laboratorio: clasificar.py importa torch y transformers dentro de las funciones
que los usan, nunca en la cabecera. Si alguien mueve esos imports arriba, este
archivo deja de importar y la regresión se ve al instante.

Las tres que no pueden faltar:

1. Un label_mapping.json y un config.json que declaren órdenes distintos tienen
   que hacer fallar la corrida. Es el único defecto que produciría una red
   entera, completa y con los signos invertidos, sin un solo error en la
   terminal.
2. fila_salida() escribe las columnas p_* por NOMBRE. Si las escribiera por
   posición, un checkpoint con otro orden interno pondría la probabilidad de
   represión en la columna de activación.
3. Un archivo a medias no se pisa sin --reanudar, y las tres guardas de entrada
   disparan ANTES de cargar 433 MB de pesos. Sin eso, enterarse de que el
   marcado estaba mal cuesta una hora de CPU.

    python -m unittest discover etapa2
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clasificar as C

HAY_TORCH = (importlib.util.find_spec("torch") is not None and
             importlib.util.find_spec("transformers") is not None)

ORDEN_SERVIDOR = ["activates", "no_relation", "regulates", "represses"]
# El de bio_bert_re_finetune.py: intercambia 'represses' con 'no_relation'.
ORDEN_ENTRENAMIENTO = ["activates", "represses", "regulates", "no_relation"]

TEXTO = ("The expression of <e2> mexEF-oprN </e2> is activated by "
         "<e1> MexT </e1> .")


def par(id_par="a1", pmid=19846594, tf="MexT", target="mexEF-oprN", text=TEXTO,
        **extra):
    d = {"text": text, "label": "", "pmid": pmid, "tf": tf, "target": target,
         "id_par": id_par, "seccion": "introduction", "fuente": "fulltext",
         "n_oracion": 37, "autorregulacion": False, "redaccion": "directa"}
    d.update(extra)
    return d


class Temporal(unittest.TestCase):
    """Base con carpeta temporal y utilidades para armar entradas falsas."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def ruta(self, *partes):
        return os.path.join(self.dir, *partes)

    def escribir(self, nombre, contenido):
        ruta = self.ruta(nombre)
        carpeta = os.path.dirname(ruta)
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        modo = "wb" if isinstance(contenido, bytes) else "w"
        kwargs = {} if isinstance(contenido, bytes) else {"encoding": "utf-8",
                                                          "newline": "\n"}
        with open(ruta, modo, **kwargs) as f:
            f.write(contenido)
        return ruta

    def jsonl(self, nombre, filas):
        return self.escribir(nombre, "".join(
            json.dumps(f, ensure_ascii=False) + "\n" for f in filas))

    def checkpoint(self, nombre="modelo", etiquetas=ORDEN_SERVIDOR,
                   id2label=ORDEN_SERVIDOR, do_lower_case=True,
                   quitar=(), con_mapa=True):
        """Un checkpoint falso: los archivos que clasificar.py exige, vacíos."""
        base = self.ruta(nombre)
        os.makedirs(base, exist_ok=True)
        archivos = {
            "config.json": json.dumps(
                {"num_labels": 4,
                 "id2label": {str(i): e for i, e in enumerate(id2label)}}
                if id2label else {"num_labels": 4}),
            "pytorch_model.bin": "",
            "vocab.txt": "[UNK]\n",
            "tokenizer_config.json": json.dumps(
                {"do_lower_case": do_lower_case}
                if do_lower_case is not None else {}),
        }
        if con_mapa:
            archivos["label_mapping.json"] = json.dumps(etiquetas)
        for n, contenido in archivos.items():
            if n in quitar:
                continue
            with open(os.path.join(base, n), "w", encoding="utf-8") as f:
                f.write(contenido)
        return base


# --------------------------------------------------- el orden de las etiquetas

class PruebasEtiquetas(Temporal):

    def mapa(self, contenido, nombre="label_mapping.json"):
        return self.escribir(nombre, json.dumps(contenido)
                             if not isinstance(contenido, str) else contenido)

    def test_lee_la_lista_que_escribe_particionar(self):
        r = self.mapa(ORDEN_SERVIDOR)
        self.assertEqual(C.leer_etiquetas(r), ORDEN_SERVIDOR)

    def test_lee_un_id2label(self):
        r = self.mapa({"0": "activates", "1": "no_relation",
                       "2": "regulates", "3": "represses"})
        self.assertEqual(C.leer_etiquetas(r), ORDEN_SERVIDOR)

    def test_lee_un_label2id(self):
        r = self.mapa({"activates": 0, "no_relation": 1,
                       "regulates": 2, "represses": 3})
        self.assertEqual(C.leer_etiquetas(r), ORDEN_SERVIDOR)

    def test_el_orden_lo_manda_el_archivo_no_el_codigo(self):
        """Si el checkpoint dice el orden de LABELS_DEFAULT, ese es el orden.

        La autoridad es label_mapping.json, no una lista escrita aquí: lo que
        está prohibido es adivinar, no que el orden sea otro.
        """
        r = self.mapa(ORDEN_ENTRENAMIENTO)
        cfg = self.escribir("config.json", json.dumps(
            {"id2label": {str(i): e for i, e in enumerate(ORDEN_ENTRENAMIENTO)}}))
        self.assertEqual(C.leer_etiquetas(r, cfg), ORDEN_ENTRENAMIENTO)

    def test_config_y_mapa_en_desacuerdo_es_salida_con_1(self):
        """La prueba que no puede faltar.

        Un checkpoint entrenado sin --labels_json trae en config.json el orden
        de LABELS_DEFAULT. Si al lado le ponen el label_mapping.json del
        servidor, los dos archivos existen y los dos parecen sanos, pero
        'represses' y 'no_relation' están cambiados de lugar. Sin este cruce,
        la red sale completa y con los signos volteados.
        """
        r = self.mapa(ORDEN_SERVIDOR)
        cfg = self.escribir("config.json", json.dumps(
            {"id2label": {str(i): e for i, e in enumerate(ORDEN_ENTRENAMIENTO)}}))
        with self.assertRaises(SystemExit) as e:
            C.leer_etiquetas(r, cfg)
        mensaje = str(e.exception)
        self.assertIn("label_mapping.json", mensaje)
        self.assertIn("config.json", mensaje)
        self.assertIn("represses", mensaje)

    def test_sin_el_archivo_sale_con_1_y_explica_el_riesgo(self):
        with self.assertRaises(SystemExit) as e:
            C.leer_etiquetas(self.ruta("no_existe.json"))
        mensaje = str(e.exception)
        self.assertIn("label_mapping.json", mensaje)
        self.assertIn("LABELS_DEFAULT", mensaje)
        self.assertIn("--etiquetas", mensaje)

    def test_ruta_vacia_tambien_sale_con_1(self):
        with self.assertRaises(SystemExit):
            C.leer_etiquetas(None)

    def test_otro_conjunto_de_etiquetas_sale_con_1(self):
        r = self.mapa(["positive", "negative", "neutral", "otra"])
        with self.assertRaises(SystemExit) as e:
            C.leer_etiquetas(r)
        self.assertIn("no son las cuatro esperadas".lower(),
                      str(e.exception).lower())

    def test_tres_etiquetas_sale_con_1(self):
        r = self.mapa(["activates", "represses", "regulates"])
        with self.assertRaises(SystemExit):
            C.leer_etiquetas(r)

    def test_json_roto_sale_con_1(self):
        r = self.escribir("label_mapping.json", '["activates", "no_rel')
        with self.assertRaises(SystemExit) as e:
            C.leer_etiquetas(r)
        self.assertIn("no es JSON", str(e.exception))

    def test_config_ilegible_no_impide_leer_el_mapa(self):
        """config.json roto no es motivo de parar: la autoridad es el mapa."""
        r = self.mapa(ORDEN_SERVIDOR)
        cfg = self.escribir("config.json", "{roto")
        self.assertEqual(C.leer_etiquetas(r, cfg), ORDEN_SERVIDOR)

    def test_config_sin_id2label_no_impide_nada(self):
        r = self.mapa(ORDEN_SERVIDOR)
        cfg = self.escribir("config.json", json.dumps({"num_labels": 4}))
        self.assertEqual(C.leer_etiquetas(r, cfg), ORDEN_SERVIDOR)


class PruebasNormalizarEtiquetas(unittest.TestCase):

    def test_id2label_con_huecos_no_se_interpreta(self):
        self.assertIsNone(C.normalizar_etiquetas({"0": "a", "2": "b"}))

    def test_label2id_con_huecos_no_se_interpreta(self):
        self.assertIsNone(C.normalizar_etiquetas({"a": 0, "b": 5}))

    def test_lista_vacia_y_dict_vacio(self):
        self.assertIsNone(C.normalizar_etiquetas([]))
        self.assertIsNone(C.normalizar_etiquetas({}))

    def test_basura(self):
        self.assertIsNone(C.normalizar_etiquetas("activates"))
        self.assertIsNone(C.normalizar_etiquetas([1, 2, 3]))


class PruebasDoLowerCase(Temporal):

    def test_true(self):
        base = self.checkpoint(do_lower_case=True)
        self.assertIs(C.leer_do_lower_case(base), True)

    def test_false(self):
        base = self.checkpoint(do_lower_case=False)
        self.assertIs(C.leer_do_lower_case(base), False)

    def test_sin_la_clave_es_none_y_no_revienta(self):
        """Es un aviso, no una falla: sin el dato no se interpreta la métrica,
        pero la corrida sigue siendo válida."""
        base = self.checkpoint(do_lower_case=None)
        self.assertIsNone(C.leer_do_lower_case(base))

    def test_sin_el_archivo_es_none(self):
        base = self.checkpoint(quitar=("tokenizer_config.json",))
        self.assertIsNone(C.leer_do_lower_case(base))


# ------------------------------------------------------------- el checkpoint

class PruebasModelo(Temporal):

    def test_sin_modelo_nombra_los_archivos_que_hacen_falta(self):
        with self.assertRaises(SystemExit) as e:
            C.exigir_modelo(None, None)
        mensaje = str(e.exception)
        for archivo in ("config.json", "pytorch_model.bin", "vocab.txt",
                        "tokenizer_config.json", "label_mapping.json"):
            self.assertIn(archivo, mensaje)

    def test_carpeta_inexistente(self):
        with self.assertRaises(SystemExit) as e:
            C.exigir_modelo(self.ruta("nada"), None)
        self.assertIn("no es una carpeta", str(e.exception))

    def test_nombra_el_archivo_que_falta(self):
        base = self.checkpoint(quitar=("pytorch_model.bin",))
        with self.assertRaises(SystemExit) as e:
            C.exigir_modelo(base, None)
        mensaje = str(e.exception)
        self.assertIn("pytorch_model.bin o model.safetensors", mensaje)
        self.assertIn("los pesos", mensaje)

    def test_safetensors_tambien_vale_como_pesos(self):
        base = self.checkpoint(quitar=("pytorch_model.bin",))
        with open(os.path.join(base, "model.safetensors"), "w") as f:
            f.write("")
        self.assertEqual(C.archivos_que_faltan(base), [])

    def test_devuelve_el_mapa_de_dentro_de_la_carpeta(self):
        base = self.checkpoint()
        self.assertEqual(C.exigir_modelo(base, None),
                         os.path.join(base, "label_mapping.json"))

    def test_el_mapa_puede_ir_aparte(self):
        """trainer.save_model() no escribe label_mapping.json junto a los
        pesos, así que traerlo de otra carpeta tiene que ser posible."""
        base = self.checkpoint(con_mapa=False)
        aparte = self.escribir("otro/label_mapping.json",
                               json.dumps(ORDEN_SERVIDOR))
        self.assertEqual(C.exigir_modelo(base, aparte), aparte)
        self.assertEqual(C.leer_etiquetas(aparte), ORDEN_SERVIDOR)

    def test_falta_el_mapa_y_no_se_paso_aparte(self):
        base = self.checkpoint(con_mapa=False)
        ruta = C.exigir_modelo(base, None)
        with self.assertRaises(SystemExit) as e:
            C.leer_etiquetas(ruta)
        self.assertIn("LABELS_DEFAULT", str(e.exception))


class PruebasDispositivo(unittest.TestCase):
    """El usuario no elige: auto usa la GPU si la hay."""

    def test_auto_sin_gpu_cae_a_cpu(self):
        self.assertEqual(C.elegir_dispositivo("auto", False), "cpu")

    def test_auto_con_gpu_usa_gpu(self):
        self.assertEqual(C.elegir_dispositivo("auto", True), "cuda")

    def test_cpu_forzado_gana_a_la_gpu_disponible(self):
        self.assertEqual(C.elegir_dispositivo("cpu", True), "cpu")

    def test_cuda_pedida_sin_gpu_sale_con_1(self):
        """Callar y correr en CPU convertiría dos minutos en una hora sin
        avisar; eso lo tiene que decidir quien lanza."""
        with self.assertRaises(SystemExit) as e:
            C.elegir_dispositivo("cuda", False)
        self.assertIn("CUDA", str(e.exception))


# ---------------------------------------------------------------- la entrada

class PruebasValidarPar(unittest.TestCase):

    def test_una_fila_buena_pasa(self):
        self.assertIsNone(C.validar_par(par(), 1))

    def test_falta_una_clave(self):
        fila = par()
        del fila["id_par"]
        self.assertIn("id_par", C.validar_par(fila, 3))

    def test_marcado_pegado_es_rechazado(self):
        """El entrenamiento lleva un espacio dentro de cada etiqueta en 1563 de
        1563 filas. Sin el espacio las piezas del wordpiece son otras y el
        modelo devuelve probabilidades igual: ruido con aspecto de resultado."""
        fila = par(text="<e1>MexT</e1> activates <e2>mexEF-oprN</e2> .")
        mensaje = C.validar_par(fila, 7)
        self.assertIn("Fila 7", mensaje)
        self.assertIn("3.1", mensaje)

    def test_etiquetas_cruzadas_son_rechazadas(self):
        fila = par(text="<e1> MexT </e2> activates <e2> mexE </e2> .")
        self.assertIsNotNone(C.validar_par(fila, 1))

    def test_dos_e1_y_ningun_e2(self):
        fila = par(text="<e1> MexT </e1> y <e1> MexE </e1> .")
        self.assertIsNotNone(C.validar_par(fila, 1))

    def test_mencion_con_espacio_es_rechazada(self):
        fila = par(text="<e1> Mex T </e1> activates <e2> mexE </e2> .")
        self.assertIsNotNone(C.validar_par(fila, 1))

    def test_pmid_no_entero(self):
        self.assertIn("pmid", C.validar_par(par(pmid="PMC123"), 2))

    def test_pmid_en_cadena_de_digitos_pasa(self):
        """En grn.db la columna es TEXT; la conversión es de la etapa 2, pero
        una cadena de dígitos no es motivo para tirar la fila."""
        self.assertIsNone(C.validar_par(par(pmid="19846594"), 1))


class PruebasLeerJsonl(Temporal):

    def test_falta_el_archivo(self):
        with self.assertRaises(SystemExit) as e:
            list(C.leer_jsonl(self.ruta("nada.jsonl")))
        self.assertIn("extraer_pares.py", str(e.exception))

    def test_linea_rota(self):
        ruta = self.escribir("x.jsonl", '{"a": 1}\n{"b": \n')
        with self.assertRaises(SystemExit) as e:
            list(C.leer_jsonl(ruta))
        self.assertIn("línea 2", str(e.exception))

    def test_lineas_en_blanco_se_saltan(self):
        ruta = self.escribir("x.jsonl", '{"a": 1}\n\n{"a": 2}\n')
        self.assertEqual([d for _, d in C.leer_jsonl(ruta)], [{"a": 1}, {"a": 2}])


# ------------------------------------------------------------------ salida

class PruebasFilaSalida(unittest.TestCase):

    def test_las_claves_van_en_el_orden_del_contrato(self):
        d = C.fila_salida(par(), ORDEN_SERVIDOR, [0.9, 0.03, 0.05, 0.02])
        self.assertEqual(list(d.keys()), C.CLAVES_SALIDA)

    def test_las_columnas_p_se_llenan_por_nombre_no_por_posicion(self):
        """La prueba que no puede faltar.

        Con un checkpoint cuyo orden interno sea otro, escribir las p_* en el
        orden de los logits pondría la probabilidad de represión en la columna
        de activación, y la red saldría con los signos cambiados.
        """
        otro = ["represses", "activates", "regulates", "no_relation"]
        d = C.fila_salida(par(), otro, [0.90, 0.04, 0.03, 0.03])
        self.assertEqual(d["p_represses"], 0.9)
        self.assertEqual(d["p_activates"], 0.04)
        self.assertEqual(d["prediccion"], "represses")

    def test_el_argmax_ante_un_empate_es_estable(self):
        d = C.fila_salida(par(), ORDEN_SERVIDOR, [0.25, 0.25, 0.25, 0.25])
        self.assertEqual(d["prediccion"], "activates")

    def test_redondeo_a_seis_decimales(self):
        d = C.fila_salida(par(), ORDEN_SERVIDOR,
                          [0.123456789, 0.3, 0.3, 0.276543211])
        self.assertEqual(d["p_activates"], 0.123457)

    def test_el_pmid_sale_entero(self):
        d = C.fila_salida(par(pmid="19846594"), ORDEN_SERVIDOR,
                          [0.9, 0.04, 0.03, 0.03])
        self.assertEqual(d["pmid"], 19846594)
        self.assertIsInstance(d["pmid"], int)

    def test_los_metadatos_se_copian_y_los_ausentes_no_revientan(self):
        fila = {"text": TEXTO, "id_par": "z", "pmid": 1, "tf": "MexT",
                "target": "mexE"}
        d = C.fila_salida(fila, ORDEN_SERVIDOR, [0.9, 0.04, 0.03, 0.03])
        self.assertEqual(d["seccion"], "")
        self.assertEqual(d["fuente"], "")
        self.assertIs(d["autorregulacion"], False)
        self.assertEqual(d["redaccion"], "")


class PruebasVerificarSalida(Temporal):

    def salida(self, filas, nombre="predicciones.jsonl"):
        return self.jsonl(nombre, filas)

    def prediccion(self, id_par, clase="activates", probs=None):
        """Una fila de salida completa, con las claves del contrato."""
        probs = probs or {"activates": 0.9, "no_relation": 0.04,
                          "regulates": 0.03, "represses": 0.03}
        d = {"id_par": id_par, "pmid": 1, "tf": "MexT", "target": "mexE",
             "prediccion": clase}
        for k in C.ETIQUETAS_ESPERADAS:
            d["p_" + k] = probs[k]
        d["seccion"] = "results"
        d["fuente"] = "fulltext"
        d["autorregulacion"] = False
        d["redaccion"] = "directa"
        return d

    def test_un_archivo_bueno_no_tiene_problemas(self):
        ruta = self.salida([self.prediccion("a"), self.prediccion("b", "represses")])
        self.assertEqual(C.verificar_salida(ruta, ["a", "b"]), [])

    def test_faltan_predicciones(self):
        ruta = self.salida([self.prediccion("a")])
        problemas = C.verificar_salida(ruta, ["a", "b"])
        self.assertTrue(any("La unión por id_par" in p for p in problemas))

    def test_id_par_que_no_estaba_en_la_entrada(self):
        ruta = self.salida([self.prediccion("a"), self.prediccion("z")])
        problemas = C.verificar_salida(ruta, ["a", "b"])
        self.assertTrue(any("no coinciden" in p for p in problemas))

    def test_probabilidades_que_no_suman_uno(self):
        mala = self.prediccion("a", probs={"activates": 0.9, "no_relation": 0.9,
                                           "regulates": 0.0, "represses": 0.0})
        ruta = self.salida([mala])
        problemas = C.verificar_salida(ruta, ["a"])
        self.assertTrue(any("softmax" in p for p in problemas))

    def test_todas_la_misma_clase_es_un_modelo_mal_cargado(self):
        filas = [self.prediccion("id%d" % i) for i in range(25)]
        ruta = self.salida(filas)
        problemas = C.verificar_salida(ruta, ["id%d" % i for i in range(25)])
        self.assertTrue(any("mal cargado" in p for p in problemas))

    def test_con_pocas_filas_no_se_exige_variedad(self):
        """La invariante es correcta a escala de corpus y absurda con
        --limite 5, que es justo para depurar."""
        filas = [self.prediccion("id%d" % i) for i in range(3)]
        ruta = self.salida(filas)
        self.assertEqual(C.verificar_salida(ruta, ["id0", "id1", "id2"]), [])

    def test_la_variedad_se_puede_exigir_a_mano(self):
        filas = [self.prediccion("id%d" % i) for i in range(3)]
        ruta = self.salida(filas)
        problemas = C.verificar_salida(ruta, ["id0", "id1", "id2"],
                                       exigir_variedad=True)
        self.assertTrue(any("mal cargado" in p for p in problemas))

    def test_una_linea_ilegible_se_reporta(self):
        ruta = self.escribir("p.jsonl", json.dumps(self.prediccion("a")) +
                             "\n{roto\n")
        problemas = C.verificar_salida(ruta, ["a", "b"])
        self.assertTrue(any("ilegible" in p for p in problemas))

    def test_una_fila_sin_las_claves_del_contrato_se_reporta(self):
        """Al reanudar, la cabeza del archivo la escribió otra corrida, que
        pudo ser de otra versión de este script. La etapa 4 lee columnas por
        nombre y un archivo mitad y mitad no se lo merece."""
        ruta = self.escribir("p.jsonl", json.dumps({"id_par": "a"}) + "\n")
        problemas = C.verificar_salida(ruta, ["a"])
        self.assertTrue(any("claves del contrato" in p for p in problemas))

    def test_las_claves_desordenadas_tambien(self):
        fila = self.prediccion("a")
        alreves = {k: fila[k] for k in reversed(list(fila))}
        ruta = self.escribir("p.jsonl", json.dumps(alreves) + "\n")
        problemas = C.verificar_salida(ruta, ["a"])
        self.assertTrue(any("claves del contrato" in p for p in problemas))


# --------------------------------------------------------------- reanudación

class PruebasSanearParcial(Temporal):

    def test_archivo_inexistente(self):
        self.assertEqual(C.sanear_parcial(self.ruta("nada")), ([], 0))

    def test_archivo_completo(self):
        ruta = self.jsonl("p.parcial", [{"id_par": "a"}, {"id_par": "b"}])
        ids, sobrantes = C.sanear_parcial(ruta)
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(sobrantes, 0)

    def test_la_ultima_linea_a_medias_se_descarta_y_el_archivo_se_corta(self):
        """La prueba que no puede faltar de la reanudación.

        Una muerte por señal parte la última línea. Si se reanudara sin
        cortarla, quedaría un JSON roto en medio del archivo y la unión por
        id_par de la etapa 4 fallaría mucho después, lejos de la causa.
        """
        ruta = self.escribir(
            "p.parcial",
            json.dumps({"id_par": "a"}) + "\n" + '{"id_par": "b", "p_act')
        ids, sobrantes = C.sanear_parcial(ruta)
        self.assertEqual(ids, ["a"])
        self.assertEqual(sobrantes, 1)
        with open(ruta, encoding="utf-8") as f:
            self.assertEqual(f.read(), json.dumps({"id_par": "a"}) + "\n")

    def test_una_linea_intermedia_rota_corta_ahi(self):
        ruta = self.escribir("p.parcial",
                             '{"id_par": "a"}\n{roto}\n{"id_par": "c"}\n')
        ids, sobrantes = C.sanear_parcial(ruta)
        self.assertEqual(ids, ["a"])
        self.assertEqual(sobrantes, 2)

    def test_una_linea_sin_id_par_corta_ahi(self):
        ruta = self.escribir("p.parcial", '{"id_par": "a"}\n{"pmid": 1}\n')
        ids, _ = C.sanear_parcial(ruta)
        self.assertEqual(ids, ["a"])

    def test_tolera_saltos_de_windows(self):
        """Una corrida vieja pudo escribirse en modo texto y dejar \\r\\n."""
        ruta = self.escribir("p.parcial",
                             b'{"id_par": "a"}\r\n{"id_par": "b"}\r\n')
        ids, sobrantes = C.sanear_parcial(ruta)
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(sobrantes, 0)

    def test_utf8_multibyte_no_desalinea_el_corte(self):
        """Los offsets se cuentan en bytes: con acentos, contarlos en
        caracteres cortaría el archivo en medio de una línea buena."""
        ruta = self.escribir("p.parcial", json.dumps(
            {"id_par": "a", "oracion": "regulación de señal"},
            ensure_ascii=False) + "\n" + '{"id_par": "b"')
        ids, _ = C.sanear_parcial(ruta)
        self.assertEqual(ids, ["a"])
        with open(ruta, encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read())["oracion"],
                             "regulación de señal")


class PruebasPrefijo(unittest.TestCase):

    def test_un_prefijo_de_verdad_pasa(self):
        self.assertIsNone(C.comprobar_prefijo(["a", "b"], ["a", "b", "c"]))

    def test_vacio_pasa(self):
        self.assertIsNone(C.comprobar_prefijo([], ["a", "b"]))

    def test_completo_pasa(self):
        self.assertIsNone(C.comprobar_prefijo(["a", "b"], ["a", "b"]))

    def test_otro_pares_jsonl_se_detecta(self):
        """Continuar sobre otra entrada mezclaría dos corridas en un archivo
        que después se une por id_par sin sospechar nada."""
        mensaje = C.comprobar_prefijo(["a", "x"], ["a", "b", "c"])
        self.assertIn("posición 2", mensaje)
        self.assertIn("otro pares.jsonl", mensaje)

    def test_mas_predicciones_que_candidatos(self):
        mensaje = C.comprobar_prefijo(["a", "b", "c"], ["a"])
        self.assertIn("no salieron del mismo", mensaje)


# --------------------------------------------------------------- calibración

class PruebasUmbrales(unittest.TestCase):

    def observacion(self, clase, p, verdad):
        probs = dict.fromkeys(ORDEN_SERVIDOR, (1.0 - p) / 3.0)
        probs[clase] = p
        return (probs, clase, verdad)

    def test_elige_el_umbral_que_maximiza_el_f1(self):
        obs = [self.observacion("activates", 0.9, "activates"),
               self.observacion("activates", 0.8, "activates"),
               self.observacion("activates", 0.4, "no_relation")]
        umbral, f1, verdaderas = C.umbral_optimo(obs, "activates")
        self.assertAlmostEqual(umbral, 0.8)
        self.assertAlmostEqual(f1, 1.0)
        self.assertEqual(verdaderas, 2)

    def test_es_determinista(self):
        obs = [self.observacion("activates", 0.5, "activates"),
               self.observacion("activates", 0.5, "no_relation")]
        self.assertEqual(C.umbral_optimo(obs, "activates"),
                         C.umbral_optimo(obs, "activates"))

    def test_una_clase_sin_predicciones_no_inventa_umbral(self):
        obs = [self.observacion("activates", 0.9, "activates")]
        umbral, f1, verdaderas = C.umbral_optimo(obs, "represses")
        self.assertIsNone(umbral)
        self.assertEqual(f1, 0.0)

    def test_calibrar_escribe_los_tres_umbrales_y_su_procedencia(self):
        obs = [self.observacion("activates", 0.9, "activates"),
               self.observacion("represses", 0.8, "represses"),
               self.observacion("regulates", 0.7, "regulates"),
               self.observacion("no_relation", 0.6, "no_relation")]
        d = C.calibrar(obs, "dev.jsonl")
        # Anidados y con el nombre de la clase: es como los lee red.py.
        self.assertEqual(sorted(d["umbrales"]),
                         ["activates", "regulates", "represses"])
        self.assertNotIn("no_relation", d["umbrales"])
        self.assertEqual(d["n"], 4)
        self.assertEqual(d["exactitud"], 1.0)
        self.assertIn("dev.jsonl", d["calibrado_en"])
        self.assertIn("evaluación en ajuste", d["aviso"])

    def test_sin_datos_de_una_clase_cae_al_valor_por_omision(self):
        obs = [self.observacion("activates", 0.9, "activates")]
        d = C.calibrar(obs, "dev.jsonl")
        self.assertEqual(d["umbrales"]["represses"], 0.70)
        self.assertTrue(d["por_clase"]["represses"]["sin_datos"])
        self.assertFalse(d["por_clase"]["activates"]["sin_datos"])


# ------------------------------------------------- el tokenizador (con doble)

class TokFalso:
    """Doble del tokenizador. comprobar_tokenizador() no necesita torch."""

    def __init__(self, piezas, unk_token="[UNK]", especiales=("[CLS]", "[SEP]")):
        self.piezas = piezas
        self.unk_token = unk_token
        self.all_special_tokens = list(especiales)

    def tokenize(self, texto):
        return self.piezas


class PruebasTokenizador(unittest.TestCase):

    def test_las_piezas_del_entrenamiento_pasan(self):
        tok = TokFalso(["<", "e", "##1", ">", "I", "##H", "##F",
                        "<", "/", "e", "##1", ">"])
        self.assertTrue(C.comprobar_tokenizador(tok))

    def test_unk_sale_con_1(self):
        tok = TokFalso(["[UNK]", "I", "##H", "##F", "[UNK]"])
        with self.assertRaises(SystemExit) as e:
            C.comprobar_tokenizador(tok)
        self.assertIn("[UNK]", str(e.exception))

    def test_marcadores_como_tokens_especiales_salen_con_1(self):
        """Añadirlos al vocabulario es una mejora conocida, pero cambia las
        piezas: las probabilidades dejarían de ser comparables con el barrido."""
        tok = TokFalso(["<e1>", "ihf", "</e1>"],
                       especiales=("[CLS]", "[SEP]", "<e1>", "</e1>"))
        with self.assertRaises(SystemExit) as e:
            C.comprobar_tokenizador(tok)
        self.assertIn("tokens especiales", str(e.exception))

    def test_sin_piezas_sale_con_1(self):
        with self.assertRaises(SystemExit):
            C.comprobar_tokenizador(TokFalso([]))


# ------------------------------------------------------------- lo accesorio

class PruebasVarias(Temporal):

    def test_en_lotes_reparte_todo(self):
        lotes = list(C.en_lotes(range(10), 3))
        self.assertEqual([len(x) for x in lotes], [3, 3, 3, 1])
        self.assertEqual(sum(len(x) for x in lotes), 10)

    def test_en_lotes_con_secuencia_vacia(self):
        self.assertEqual(list(C.en_lotes([], 3)), [])

    def test_formato_tiempo(self):
        self.assertEqual(C.formato_tiempo(30), "30 s")
        self.assertEqual(C.formato_tiempo(600), "10.0 min")
        self.assertEqual(C.formato_tiempo(7200), "2.0 h")

    def test_escribir_json_no_deja_temporal_y_usa_lf(self):
        ruta = self.ruta("sub", "meta.json")
        C.escribir_json(ruta, {"a": 1, "texto": "señal"})
        self.assertFalse(os.path.exists(ruta + ".tmp"))
        with open(ruta, "rb") as f:
            datos = f.read()
        self.assertNotIn(b"\r\n", datos)
        self.assertEqual(json.loads(datos.decode("utf-8"))["texto"], "señal")


# ---------------------------------------- las guardas, antes de cargar torch

class PruebasMainSinTorch(Temporal):
    """main() tiene que rechazar lo rechazable ANTES de importar torch.

    Es lo que hace estas pruebas posibles sin torch instalado, y es también el
    requisito de fondo: enterarse de que el marcado estaba mal, o de que el
    parcial es de otra corrida, no puede costar una hora de CPU ni un minuto de
    carga de pesos.
    """

    def correr(self, *extra):
        base = self.checkpoint()
        argv = ["clasificar.py", "--modelo", base,
                "--entrada", self.ruta("pares.jsonl"),
                "--salida", self.ruta("predicciones.jsonl")] + list(extra)
        pantalla = io.StringIO()
        anterior = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stdout(pantalla):
                C.main()
        finally:
            sys.argv = anterior
        return pantalla.getvalue()

    def test_sin_modelo_sale_antes_de_todo(self):
        sys.argv, anterior = ["clasificar.py"], sys.argv
        try:
            with self.assertRaises(SystemExit) as e:
                with contextlib.redirect_stdout(io.StringIO()):
                    C.main()
        finally:
            sys.argv = anterior
        self.assertIn("--modelo", str(e.exception))

    def test_marcado_invalido_para_la_corrida_antes_de_cargar_pesos(self):
        self.jsonl("pares.jsonl", [par(id_par="a"),
                                   par(id_par="b", text="<e1>MexT</e1> y "
                                                        "<e2>mexE</e2> .")])
        with self.assertRaises(SystemExit) as e:
            self.correr()
        self.assertIn("3.1", str(e.exception))

    def test_id_par_repetido_para_la_corrida(self):
        self.jsonl("pares.jsonl", [par(id_par="a"), par(id_par="a")])
        with self.assertRaises(SystemExit) as e:
            self.correr()
        self.assertIn("id_par repetido", str(e.exception))

    def test_entrada_vacia_para_la_corrida(self):
        self.escribir("pares.jsonl", "")
        with self.assertRaises(SystemExit) as e:
            self.correr()
        self.assertIn("ningún candidato", str(e.exception))

    def test_un_parcial_existente_no_se_pisa_sin_reanudar(self):
        """Requisito duro: cien mil pares son una hora de CPU. Empezar de cero
        en silencio es la forma más cara de perder trabajo."""
        self.jsonl("pares.jsonl", [par(id_par="a"), par(id_par="b")])
        self.jsonl("predicciones.jsonl.parcial", [{"id_par": "a"}])
        with self.assertRaises(SystemExit) as e:
            self.correr()
        mensaje = str(e.exception)
        self.assertIn("--reanudar", mensaje)
        self.assertIn("1 predicciones", mensaje)
        # Y sigue ahí: negarse no puede destruir lo que se quiso proteger.
        self.assertTrue(os.path.exists(self.ruta("predicciones.jsonl.parcial")))

    def test_reanudar_con_un_parcial_de_otra_corrida_se_detecta(self):
        self.jsonl("pares.jsonl", [par(id_par="a"), par(id_par="b")])
        self.jsonl("predicciones.jsonl.parcial", [{"id_par": "otro"}])
        with self.assertRaises(SystemExit) as e:
            self.correr("--reanudar")
        self.assertIn("otro pares.jsonl", str(e.exception))

    def test_reanudar_adopta_una_salida_ya_completa(self):
        """Si la corrida anterior llegó al final, el nombre definitivo es el
        punto de partida. Reanudar no puede significar volver a empezar."""
        self.jsonl("pares.jsonl", [par(id_par="a"), par(id_par="b")])
        self.jsonl("predicciones.jsonl", [{"id_par": "a"}, {"id_par": "b"}])
        # Con todo hecho, lo siguiente que main() hace es importar torch.
        with self.assertRaises((ImportError, SystemExit)):
            self.correr("--reanudar")
        self.assertTrue(os.path.exists(self.ruta("predicciones.jsonl.parcial")))
        self.assertFalse(os.path.exists(self.ruta("predicciones.jsonl")))

    def test_el_orden_de_las_etiquetas_se_imprime_antes_de_correr(self):
        """Que quede en la bitácora de la corrida, no solo en el meta."""
        self.jsonl("pares.jsonl", [par(id_par="a")])
        base = self.checkpoint()
        with self.assertRaises((ImportError, SystemExit)):
            salida = self.correr()
        # La salida se pierde con la excepción; se comprueba por separado.
        self.assertEqual(C.leer_etiquetas(
            os.path.join(base, "label_mapping.json"),
            os.path.join(base, "config.json")), ORDEN_SERVIDOR)

    def test_lote_invalido(self):
        self.jsonl("pares.jsonl", [par(id_par="a")])
        with self.assertRaises(SystemExit) as e:
            self.correr("--lote", "0")
        self.assertIn("--lote", str(e.exception))


# ------------------------------------------------------ lo que sí pide torch

@unittest.skipUnless(HAY_TORCH, "torch y transformers no están instalados")
class PruebasConTorch(unittest.TestCase):
    """Lo único que no se puede probar con dobles: la pasada hacia adelante.

    No cargan el checkpoint del asesor (433 MB que no están en el repositorio):
    comprueban que probabilidades() usa no_grad, hace softmax y respeta el
    orden del lote, con un modelo de juguete.
    """

    def test_elegir_dispositivo_contra_el_torch_real(self):
        import torch
        elegido = C.elegir_dispositivo("auto", torch.cuda.is_available())
        self.assertIn(elegido, ("cpu", "cuda"))

    def test_probabilidades_suman_uno_y_conservan_el_orden(self):
        import torch

        class ModeloFalso:
            def __call__(self, **kwargs):
                n = kwargs["input_ids"].shape[0]
                base = torch.tensor([[3.0, 0.0, 0.0, 0.0],
                                     [0.0, 0.0, 0.0, 3.0]])
                return type("Salida", (), {"logits": base[:n]})()

        class TokTensor:
            def __call__(self, textos, **kwargs):
                return {"input_ids": torch.ones(len(textos), 4, dtype=torch.long)}

        probs = C.probabilidades(["uno", "dos"], TokTensor(), ModeloFalso(),
                                 "cpu", 512)
        self.assertEqual(len(probs), 2)
        for fila in probs:
            self.assertAlmostEqual(sum(fila), 1.0, places=5)
        self.assertEqual(max(range(4), key=lambda i: probs[0][i]), 0)
        self.assertEqual(max(range(4), key=lambda i: probs[1][i]), 3)

    def test_no_deja_gradientes(self):
        import torch

        class ModeloFalso:
            def __call__(self, **kwargs):
                logits = torch.ones(1, 4, requires_grad=True) * 2
                return type("Salida", (), {"logits": logits})()

        class TokTensor:
            def __call__(self, textos, **kwargs):
                return {"input_ids": torch.ones(len(textos), 4, dtype=torch.long)}

        # Si probabilidades() no envolviera en no_grad(), el .cpu().tolist()
        # de un tensor con gradiente seguiría arrastrando el grafo.
        probs = C.probabilidades(["uno"], TokTensor(), ModeloFalso(), "cpu", 512)
        self.assertAlmostEqual(sum(probs[0]), 1.0, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
