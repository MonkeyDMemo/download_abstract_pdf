# -*- coding: utf-8 -*-
"""ETL de literatura de PubMed para redes de regulacion genica.

La dependencia va en una sola direccion:

    cli.py  ->  etl.py  ->  db.py
                        ->  pubmed.py

Este archivo no importa los submodulos a proposito: quien los necesite
los pide por nombre (from grn_etl import db, etl, pubmed). Asi importar
'pubmed' en una prueba no arrastra sqlite3 ni al reves.
"""

__version__ = "0.1.0"
