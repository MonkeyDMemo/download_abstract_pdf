# -*- coding: utf-8 -*-
"""Paso 1 del pipeline: identificacion de elementos (capa bronce).

Localiza DONDE estan los genes y donde puede haber una relacion. La decision
de si la relacion existe y cual es su signo pertenece al paso 2.

Se construye solo desde el texto de los documentos. Las referencias de
evaluacion (el patron de oro, CollecTF, la auditoria de signo) quedan fuera
de este paquete a proposito: si el bronce pudiera leerlas, la circularidad
seria posible y habria que detectarla en tiempo de corrida en vez de que sea
imposible por construccion.

Solo biblioteca estandar.
"""
