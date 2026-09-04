# -*- coding: utf-8 -*-
"""Piezas que usan los tres pasos del pipeline.

Existe porque `procedencia` la necesitan el bronce, la verificacion y la red
por igual. Dejarla dentro de cualquiera de los tres obligaria a los otros dos
a importar de lado, que es justo lo que la regla de capas prohibe.

Solo biblioteca estandar, como todo lo que no sea el clasificador.
"""
