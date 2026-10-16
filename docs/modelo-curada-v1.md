# Ficha del modelo: BioBERT curada v1

Ficha con el formato de Mitchell et al. (2019). La evaluación sigue
`docs/protocolo-curada-v1.md`. Las cifras salen de `RESULTADOS.md` del tramo 2,
copiado en `docs/resultados-curada-v1.md`, y no se escriben a mano en ningún
otro lado.

**Estado:** esqueleto. Las secciones marcadas «(tramo 2)» se llenan cuando
termine la corrida.

## 1. Detalles del modelo

- **Qué es:** BioBERT (`dmis-lab/biobert-base-cased-v1.1`) afinado para
  clasificar la relación entre un regulador y un blanco marcados en una
  oración: `activates`, `represses` o `no_relation`. El mapa de etiquetas
  conserva `regulates`, pero esta versión no la aprende.
- **Receta:** el run 22 del barrido del asesor, sin cambios (protocolo,
  sección 3). Semilla 42, partición única por PMID 80/10/10.
- **Quién y cuándo:** (tramo 2: fecha, commit del código y del protocolo).
- **Dónde vive:** en el servidor del asesor, en `<runs>/run_22_…` de la
  corrida `curada-v1`. No se distribuye: se entrenó con datos confidenciales
  del laboratorio.
- **Antecesor:** el modelo de *E. coli* (`docs/ficha-modelo-bert.md`), con
  otro organismo y una métrica reportada con fuga.

## 2. Uso previsto

- **Para:** el paso 2 del pipeline (verificación). Clasifica los pares
  candidatos que el bronce encuentra en la literatura de *P. aeruginosa*, por
  `etapa2/clasificar.py`, dentro de `flujo.py`.
- **No es para:**
  - dar una relación por cierta sin revisión: es supervisión distante (sección
    9);
  - otros organismos;
  - las relaciones sin signo (`regulates`), que esta versión no aprende.

## 3. Factores

- **Artículo:** los ejemplos de un artículo no son independientes. Toda la
  evaluación corta y remuestrea por artículo.
- **Par ya visto o nuevo:** si el par regulador → blanco aparece en el
  entrenamiento. Separa memorizar de leer la oración.
- **Longitud:** los ejemplos que pasan de 512 tokens se truncan (tramo 2:
  cuántos).

## 4. Métricas

La primaria y la regla de decisión son las del protocolo (secciones 5 y 6):
macro-F1 sobre {activates, no_relation, represses}, de las predicciones fuera
de pliegue de 5 pliegues por artículo × 3 semillas, con IC95 por bootstrap de
artículos y la diferencia pareada contra la línea base de memorización.

## 5. Datos de evaluación

- **Validación cruzada:** cada ejemplo es test una vez, predicho por un
  modelo que no vio su artículo.
- **Externa (pendiente del asesor):** las 50 candidatas juzgadas a mano (el
  44 %), reservadas desde el 8-oct (protocolo, sección 10).

## 6. Datos de entrenamiento

- **Origen:** la base curada v2, por supervisión distante
  (`grn_verificacion/entrenamiento.py`), con las reservas fuera.
- **Conteos por clase y artículos:** los del protocolo, sección 2.

## 7. Resultados (tramo 2)

| cifra | valor |
|---|---|
| macro-F1 (media de 3 semillas), IC95 | |
| sd entre semillas; mínimo y máximo | |
| línea base de memorización, IC95 | |
| modelo menos línea base, IC95 | |
| regla del protocolo | |
| macro-F1 en pares nuevos (modelo / línea base) | |

Por clase y matrices: `docs/resultados-curada-v1.md`, sección 8.

## 8. Consideraciones éticas y de datos

- La base curada y sus derivados (ejemplos, particiones, predicciones, el
  modelo) son confidenciales y no salen del servidor. Al repositorio, que es
  público, llegan solo conteos y métricas, filtrados (`RESULTADOS.md`).
- Las salidas del modelo sobre el corpus público tampoco salen del servidor
  sin el visto bueno del asesor.
- No hay datos personales.

## 9. Advertencias y recomendaciones

- La métrica es contra etiquetas de supervisión distante, no contra juicio
  humano (protocolo, sección 11).
- En el flujo la proporción de pares sin relación es mucho mayor que aquí, así
  que la precisión será menor.
- (tramo 2: lo que digan los estratos y la regla del protocolo, y si el modelo
  reemplaza al de *E. coli*, que lo decide el asesor.)
