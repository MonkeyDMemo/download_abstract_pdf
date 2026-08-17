# -*- coding: utf-8 -*-
"""Suite de pruebas del ETL. Nada de aqui toca la red.

Se corre desde la raiz del proyecto:

    python -m unittest discover              # toda la suite
    python -m unittest pruebas.test_idempotencia -v

La raiz tiene que ser el directorio de arranque para que 'grn_etl' sea
importable. Con '-s pruebas' hay que dar tambien '-t .'.
"""
