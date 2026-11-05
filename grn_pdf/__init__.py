# -*- coding: utf-8 -*-
"""grn_pdf: texto de los PDF de acceso abierto, en el formato de los `.txt`
que `grn_etl.pubmed.jats_a_texto` deja junto a cada XML de PMC.

Existe para que el bronce lea el PDF de un artículo sin XML igual que lee el
XML: mismo `# título`, mismos `## ENCABEZADOS` que `secciones.tsv` ya
clasifica, los pies de figura y tabla al final bajo
`## PIES DE FIGURA Y TABLA`, y nada de lo que el JATS no trae (autores,
afiliaciones, cabezas de página, tablas).

**Paquete aislado.** La única pieza que importa un tercero es `extraer.py`
(PyMuPDF, aprobado en CLAUDE.md), y lo importa dentro de la función. Corre en
su propio entorno, `.venv-pdf`:

    uv venv .venv-pdf --python 3.12
    uv pip install --python .venv-pdf/Scripts/python.exe -r grn_pdf/requisitos.txt
    .venv-pdf/Scripts/python -m grn_pdf.cli convertir

Todo lo demás (`maquetar.py`, `convertir.py`, `validar.py`) es biblioteca
estándar compatible con 3.8, y el núcleo no importa este paquete: el bronce
consume sus `.txt` por archivo, como consume `operones_base.tsv`.
"""
