# Ficha del modelo: BioBERT curada v1

Ficha con el formato de Mitchell et al. (2019). La evaluación sigue
`docs/protocolo-curada-v1.md`. Las cifras salen de `RESULTADOS.md` del tramo 2,
copiado en `docs/resultados-curada-v1.md`, y no se escriben a mano en ningún
otro lado.

**Estado:** completa con el tramo 2 del 16-oct-2026 (15:18 a 15:37 UTC,
código y protocolo en el commit `c48eeae`, antes `27b18f5`). Las cifras de la sección 7 son
pre-registradas: el protocolo se commiteó antes del primer entrenamiento.

## 1. Detalles del modelo

- **Qué es:** BioBERT (`dmis-lab/biobert-base-cased-v1.1`) afinado para
  clasificar la relación entre un regulador y un blanco marcados en una
  oración: `activates`, `represses` o `no_relation`. El mapa de etiquetas
  conserva `regulates`, pero esta versión no la aprende.
- **Receta:** el run 22 del barrido del asesor, sin cambios (protocolo,
  sección 3). Semilla 42, partición única por PMID 80/10/10.
- **Quién y cuándo:** el 16-oct-2026, en el servidor del asesor (RTX 3070),
  con `reentrenar` (commit `c48eeae`). Cada entrenamiento tardó cerca de un
  minuto. El del modelo desplegable recorrió 5 épocas, con su mejor dev en la
  3.
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
- **Longitud:** mediana de 79 tokens, p95 de 142 y máximo de 343. Ninguno
  pasa de 512, así que ninguno se trunca.

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

## 7. Resultados

Son las predicciones fuera de pliegue: 928 ejemplos de 96 artículos, 5
pliegues × 3 semillas.

| cifra | valor |
|---|---|
| macro-F1 (media de 3 semillas), IC95 | **0.4917**, [0.445, 0.5338] |
| sd entre semillas; mínimo y máximo | 0.0199; 0.4688 y 0.5047 |
| línea base de memorización, IC95 | 0.3817, [0.3003, 0.4642] |
| clase mayoritaria | 0.2232 |
| modelo menos línea base, IC95 | **+0.1100**, [0.0221, 0.193] |
| regla del protocolo | **supera a la línea base** |
| macro-F1 en pares nuevos (831 ejemplos): modelo / línea base | 0.4798 / 0.2308 |
| macro-F1 en pares ya vistos (97 ejemplos): modelo / línea base | 0.5014 / 1.0000 |

| clase | soporte | artículos | precisión | exhaustividad | F1 | F1 línea base |
|---|---:|---:|---:|---:|---:|---:|
| activates | 322 | 66 | 0.4970 | 0.4907 | 0.4937 | 0.3185 |
| no_relation | 467 | 60 | 0.7343 | 0.6638 | 0.6966 | 0.7049 |
| represses | 139 | 40 | 0.2498 | 0.3357 | 0.2848 | 0.1216 |

Todo sale de `docs/resultados-curada-v1.md`, que trae también las matrices y
las cifras por pliegue y semilla. Los 15 cotejos entre `clasificar.py` y el
script cuadran, ningún modelo predice una sola clase y la corrida no se desvía
del protocolo.

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
- **Lee algo de la oración, pero poco.** Supera a la línea base, y la
  ventaja viene entera de los pares nuevos (0.48 contra 0.23), que son el 90 %
  de los ejemplos y lo que importa para encontrar aristas nuevas. En los pares
  ya vistos, recordar la etiqueta acierta todo y el modelo no: ahí la base
  curada ya tiene la respuesta y no hace falta el modelo.
- **El signo es lo débil.** `represses` tiene un F1 de 0.28, con precisión de
  0.25: la mayor confusión es entre `activates` y `represses`, en las dos
  direcciones. En `no_relation` el modelo empata con la línea base.
- **Un macro-F1 de 0.49 no alcanza para dar aristas por buenas sin
  revisión.** Sirve para priorizar candidatas.
- **Si reemplaza al modelo de *E. coli* lo decide el asesor**, igual que la
  evaluación externa (el 44 %, sección 5).
- **En el flujo real (16-oct) el signo no sirve:** 744 de 1 025 aristas son
  represiones y acierta 38 de 82 en el patrón de oro (46.3 %). La v2 sin pesos
  de clase (enmienda 1, `resultados-curada-v2.md`) corrige el sesgo pero se va
  a «siempre activa» (71.4 %, igual que esa línea base). **Ninguna de las dos
  reemplaza al modelo de *E. coli***, según la regla de la enmienda 1.
