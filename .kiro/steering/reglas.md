---
inclusion: always
---

# Reglas del proyecto

Este archivo no contiene reglas propias a proposito. Las reglas viven en dos
documentos que se mantienen vivos, y aqui solo se referencian, para que Kiro y
Claude Code lean exactamente lo mismo.

Antes habia cinco `.md` sueltos en la raiz con front matter de steering que
**Kiro nunca leyo**: el steering de workspace vive en `.kiro/steering/`, no en
la raiz. El resultado fue que las reglas se duplicaron y empezaron a divergir
sin que nadie lo notara. Una sola fuente por tema evita repetirlo.

## Las reglas de trabajo

#[[file:CLAUDE.md]]

## El plan: los cuatro pasos, sus tablas y sus contratos

#[[file:PLAN.md]]

## Lo que no esta aqui

- **Los hechos medidos** viven en `docs/hallazgos.md`. `CLAUDE.md` conserva
  solo la regla que sale de cada uno y apunta ahi; asi lo que se carga en cada
  sesion no crece con la evidencia, pero la evidencia no se pierde.
- **Las decisiones de diseno y su porque** estan en `docs/decisiones.md`.
- **Que se hizo y cuando** esta en `docs/bitacora.md`.
- **El contexto biologico** (nomenclatura de genes, estructura de las consultas
  de PubMed) esta en `dominio-grn.md`, que se carga por descripcion y no
  siempre: no hace falta para tocar el tablero.
- **La ruta a servicio compartido** (limitador de tasa, PostgreSQL, encolado)
  esta en `migracion-servicio.md`, tambien bajo demanda.
