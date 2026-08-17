---
inclusion: always
---

# Producto: ETL de PubMed para redes de regulacion genica

## Que es

Servicio de ingesta de literatura biomedica desde PubMed. Recibe consultas
booleanas, descarga abstracts por lotes y mantiene el estado en una base de
datos. Opcionalmente descarga texto completo (XML de PMC o PDF de acceso
abierto) en un segundo lote.

Es la primera etapa de un pipeline mas largo cuyo objetivo final es inferir
relaciones regulatorias entre factores de transcripcion y genes en
*Pseudomonas aeruginosa*, para construir una red de regulacion genica (GRN).

## Quien lo usa

Miembros de un laboratorio de investigacion, no un solo desarrollador. Esto
manda sobre varias decisiones de diseno:

- La base de datos es la fuente de verdad compartida, no archivos locales.
- Las consultas se registran con nombre para que otros las reutilicen.
- Las corridas quedan en bitacora: quien corrio que y con que resultado.
- Nada depende de que un humano este mirando la terminal.

Se opera por CLI (`cli.py`) y por un tablero HTTP local (`servidor.py`), que
son dos frentes sobre las mismas capas. El siguiente paso es exponerlo como
servicio compartido; lo que falta para eso esta en `migracion-servicio.md`.

## Que problema resuelve

Sin esto, cada estudiante corre su propio script, baja los mismos articulos
otra vez, y nadie sabe que ya se descargo. El valor central es **no volver a
descargar lo que ya se tiene** y **saber en todo momento que se tiene**.

## Principios de producto

1. **Idempotencia sobre todo.** Correr una consulta dos veces no debe generar
   trafico de descarga la segunda vez. Cualquier cambio que rompa esto es un
   defecto grave, no una regresion menor.

2. **Reanudable.** Una corrida interrumpida a la mitad se retoma sin perder lo
   hecho. El estado vive en la base despues de cada lote, no al final.

3. **Simple antes que completo.** Se prefiere una funcion clara que hace una
   cosa sobre una abstraccion generica. No se agregan capas por si acaso.

4. **Solo acceso abierto.** El sistema descarga unicamente lo que PMC y
   Unpaywall exponen legalmente. No se implementa nada que evada muros de
   pago. Lo que no es abierto se exporta como lista de pendientes para que el
   usuario lo consiga por su biblioteca institucional.

5. **Ciudadano respetuoso de las APIs.** NCBI bloquea por IP, no por usuario.
   Rebasar el limite de peticiones deja sin servicio a todo el laboratorio.

## Fuera de alcance

- Analisis de texto, extraccion de relaciones o construccion de la red. Eso
  vive en modulos posteriores que consumen la salida de este ETL.
- Fuentes distintas a PubMed/PMC (Scopus, Web of Science, etc.).

El tablero local (`servidor.py` mas `web/index.html`) si esta dentro: es la
misma logica del CLI vista por el navegador, sin dependencias y atado a
127.0.0.1. Lo que sigue fuera de alcance es una interfaz publica o multiusuario
con autenticacion.
