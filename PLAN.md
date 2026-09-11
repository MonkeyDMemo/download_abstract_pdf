# PLAN — Pipeline GRN · *Pseudomonas aeruginosa*

Actualizado: 10-sep-2026. Documento guía del repositorio.
Tres registros separados a propósito: lo **acordado** con el asesor es la fuente de verdad; lo **construido** es lo que el repositorio demuestra hoy; lo **pendiente** es la resta de los dos primeros. Nada se mueve de registro sin evidencia.

Numeración: paso 0 extracción · paso 1 identificación (bronce) · paso 2 verificación · paso 3 consolidación.
Objetivo: una GRN como grafo dirigido — nodos = genes y sus reguladores; aristas = regulador → blanco, con signo y condición.

**Dos referencias distintas, nunca intercambiables:**
- **Oro propio** — `etapa2/oro_pseudomonas.tsv`, 190 pares construidos por el equipo, seleccionados por estar atestiguados en el corpus.
- **Base curada** — `datos/validacion/GRN_experimental.xlsx`, 5 584 interacciones del laboratorio, sin filtro de encontrabilidad en texto.

Toda cifra debe declarar contra cuál se midió.

---

## 1. Acordado con el asesor

### 1.1 De la reunión del 04-sep-2026

- **Dos niveles de fuerza en la relación.** Regulación directa fuerte (unión al promotor, activación, represión explícita) frente a influencia indirecta (over-expression, regulates, sobreexpresión, efecto biológico sin mecanismo). Los disparadores que ya se extraen son lo que permite la clasificación.
- **Dos listas de disparadores**, una robusta de unión directa y otra experimental/indirecta, en lugar de una sola lista.
- **Columna de tipo de efecto** en la salida: directo / indirecto / pasivo.
- **Recursos separados en dos clases.** Específicos del organismo (genes, TFs, operones, locus tags), que cambian al pasar a otra bacteria; e inherentes o estándar (evidencia experimental, funciones biológicas, signos), reutilizables para cualquier organismo. Cambiar de organismo debe ser cambiar solo los archivos específicos.
- **Todo esto es trabajo del bronce, antes de la validación.** El bronce clasifica fuerza por léxico; el paso 2 verifica.
- **Cruce contra la base curada como entregable**: cuáles interacciones tienen su artículo entre los descargados, y cuáles serían candidatas nuevas.
- **Las interacciones por homología no son exigibles al pipeline.** Confirmado empíricamente (ver 2.4).
- **Catálogos actualizables por retroalimentación**, en base de datos, por organismo.
- **Visión de actualización recurrente**: rehacer la búsqueda periódicamente, versionar por fecha, medir qué interacciones son nuevas.

### 1.2 De acuerdos previos vigentes

- El paso 1 entrega el *dónde*, no el *sí*. Existencia y signo se deciden en el paso 2.
- El bronce se construye solo desde el texto. La base curada entra en pasos 2 y 3, nunca en la extracción.
- Tres vías de verificación sobre el mismo conjunto de evaluación: BERT del laboratorio reajustado, fine-tuning de LLM, agente con directrices.
- Fine-tuning sobre la base curada solo con partición por PMID y test retenido.
- Trazabilidad: toda fila conserva documento, fuente, offsets y la corrida que la produjo.

---

## 2. Lo que ya se tiene

Verificado contra el repositorio el 10-sep-2026.

### 2.1 Paso 0 — extracción

- Corpus congelado **v0-agosto**: 2 361 artículos; 2 354 con resumen; 918 con texto completo de PMC; 184 con PDF, ninguno procesado; 96 tienen también XML, así que solo 88 dependen del PDF.
- Control en SQLite: `consultas`, `ejecuciones`, `documentos`, `consulta_documento`, `descargas`, `corpus`, `corpus_documento`.
- Búsqueda por año de publicación (`--desde/--hasta`) y descarga incremental. Versionado con `corpus crear --nombre`.

### 2.2 Paso 1 — bronce

- **Corrida 1** sobre los 2 361 (entrada), 2 354 con texto; 7 sin resumen ni XML. 29 659 oraciones candidatas, estatus ok.
- **Tablas pobladas** en `datos/grn.db`: `texto_unidades` 273 062 · `menciones` 488 221 · `oraciones_candidatas` 29 659. El CSV y el Excel salen de consultar estas tablas.
- Menciones por clase: disparadores 153 024 · proteínas 94 674 · genes 71 865 · organismos 63 250 · funciones 60 134 · evidencia 45 274.
- Normalización a locus tag: 95.1 %, con diccionario de 5 642 filas / 5 639 genes con locus tag (RefSeq, KEGG, UniProt, más 22 filas de curación manual).
- 1 188 pares dirigidos; 307 con dos o más PMIDs distintos (la independencia no se verifica); 17 191 sin orientar.
- Exclusión de secciones y longitud: 61 etiquetas mapeadas a excluir; `MIN_ORACION=40`, `MAX_ORACION=700`.
- Recursos: `genes_pao1`, `operones_pao1`, `manual_pao1`, `palabras_comunes`, `disparadores` (239 filas, separadas por signo), `funciones_semilla`, `evidencia_experimental`, con `PROCEDENCIA.md`.

### 2.3 Evaluación contra el oro propio

- `evaluar_cobertura_bronce.py`: recall **84.7 %** (149/176) con denominador honesto; 81.1 % (154/190) sobre el total.
- Las 27 pérdidas por causa: diccionario 12, autorregulación 8, coocurrencia 7. METHODS y longitud pierden cero.
- Precisión por juicio humano sobre 50 candidatas dirigidas: 44.0 % (22/50), IC 95 % [31.2, 57.7]; 4 dudosos en el denominador. 6 de los 24 `no` son inversión de dirección: el par es correcto y el bronce lo orientó al revés (sin exigir dirección, 56.0 %). Acierto de signo no evaluable: 1 de 1.
- Muestra, juicio, criterios del juez y script del sorteo (semilla 20260904) en `etapa2/evaluacion/`; la cifra sale de `unir_juicios.py`.
- Guarda anticircularidad: `test_contaminacion.py` impide que el bronce nombre `oro_pseudomonas`.

### 2.4 Evaluación contra la base curada — medido el 10-sep-2026

**Estructura.** 5 584 filas, 8 columnas: `Source`, `Target`, `Interaction`, `Reference`, `Source_Locus_id`, `Target_Locus_id`, `Origen`, `Contributions`. Protegida por `.gitignore`, sin rastro en el historial de git.

- `Origen` (3 valores) indica en qué versión de la base vive la fila, no cómo se obtuvo: Histórica 4 824 · BioBERT 544 · Ambos 216. **No sirve para separar el denominador.**
- `Interaction` codifica solo signo: `+` 4 059 · `Unknown` 786 · `-` 598 · vacío 123 · `d` 14 · `+, +` 1 · 3 celdas con un locus corrido. Mapea uno a uno con el +/−/? del bronce.
- **La etiqueta de `Reference` sí marca procedencia:** dos variantes que dicen "homology", en **2 850 filas (51 %)**, 2 808 de ellas de Histórica. Una variante indica inferencia desde la cepa PA14.
- `Reference` son PMIDs; requiere normalizar (float con `.0`, listas por coma, etiqueta pegada, PMIDs de 7 dígitos, 1 DOI). 310 PMIDs distintos, 208 en el corpus (67.1 %).
- Locus: formato PA#### en las 5 584 filas; 3 006 distintos, de los que 1 796 (59.7 %) aparecen en `menciones`.

**Construcción del denominador exigible: 2 003 filas.**

| Exclusión | Filas | Motivo |
|---|---|---|
| Base completa | 5 584 | |
| − homología | 2 850 | El artículo citado no reporta la relación; acuerdo del asesor, confirmado abajo |
| − PMID B | 731 | Un solo artículo, con PDF y sin XML; el bronce no lee PDF, solo tiene 6 oraciones de abstract |
| **Denominador exigible** | **2 003** | `+` 1 177 · `-` 569 · `Unknown` 116 · vacío 123; 87.2 % con signo resuelto |

De esas 2 003: 1 488 (74.3 %) tienen su PMID en el corpus; de ellas 791 con XML y 697 solo abstract.

**Cobertura del bronce (corrida 1), con dos reglas:**

| Regla | Denominador completo | En corpus | Con XML | Solo abstract |
|---|---|---|---|---|
| a) par en cualquier oración candidata | 857/2 003 (42.8 %) | 656/1 488 (44.1 %) | **353/791 (44.6 %)** | 303/697 (43.5 %) |
| b) par en oración del artículo citado | 346/2 003 (17.3 %) | 346/1 488 (23.3 %) | **239/791 (30.2 %)** | 107/697 (15.4 %) |

La regla b) mide si el paso 1 recupera la evidencia citada; la a) mide lo que el paso 3 podría juntar sumando artículos. **La cifra a reportar es 30.2 %**, con la a) como complemento.

**Contraste de homología (2 850 filas, 2 823 con XML):** cobertura 4.7 % con la regla a) y **0.3 %** con la b). El bronce tiene esos artículos completos y aun así no encuentra las relaciones: el artículo citado no las dice. Queda probado que excluirlas es correcto. Si entraran, la b) con XML caería de 30.2 % a 6.9 %.

**Por qué 30.2 % y no 84.7 %.** El oro propio se construyó exigiendo que la relación estuviera atestiguada en el corpus, es decir, seleccionado para ser encontrable. La base curada no tiene ese filtro: sus relaciones existen porque son ciertas, no porque estén dichas en una oración. La brecha mide la distancia entre lo que el corpus dice en prosa y lo que la literatura sabe.

**Cautelas de la medición.** Es un piso: 917 menciones (77 ids distintos) no se pudieron llevar a locus, y una relación repartida en dos oraciones no cuenta. Mide coocurrencia, no dirección ni signo: es el techo del paso 1. La expansión de operones aporta 53 filas (sin ella, la a) con XML baja a 37.9 %). 43 filas del denominador son autorregulación y nunca pueden contar como cubiertas. La concentración sesga hacia abajo: 5 PMIDs sostienen 642 filas (32.1 %); sin ellos la b) con XML sube a 37.3 %.

---

## 3. Lo que falta hacer

### 3.1 Crítico — integridad y reproducibilidad

| # | Qué | Por qué |
|---|---|---|
| 1 | Extender la lista blanca de `test_contaminacion.py` a `GRN_experimental` y `datos/validacion` | La regla de confidencialidad frena las herramientas de Claude, no los scripts. `test_contaminacion` protege `oro_pseudomonas` y `auditoria_signo` y vigila `etapa2`, `grn_bronce` y `grn_comun`; falta cubrir `GRN_experimental` y `datos/validacion`, y tiene dos límites: distingue mayúsculas y no revisa subcarpetas. Ampliar también a comandos: un `grep` sobre la raíz recorre `datos/validacion`. Negar `Bash(grep *)` sobre rutas de datos o exigir `--exclude-dir=datos` |
| 2 | Nomenclatura de las dos referencias en repositorio y documentos | Toda cifra debe declarar contra cuál se midió |
| 3 | Crear `pyproject.toml` con el extra `[bronce]` | Un clon limpio no reproduce la exportación a Excel; openpyxl está instalado a mano |
| 4 | Alinear `CLAUDE.md` con la realidad del bronce (dice idempotente; `identificar.py` es todo-o-nada) | Documento que gobierna afirmando algo falso |
| 5 | Registrar en `corridas` las secciones excluidas y la huella de `secciones.tsv` | Si el archivo cambia, la corrida no puede decir con qué regla se hizo |

### 3.2 Lo que pidió el asesor

| # | Qué | Nota |
|---|---|---|
| 6 | Partir `disparadores.csv` en dos por fuerza: unión directa y experimental/indirecta, conservando el signo | Precursor en `etapa2/extraer_pares.py`; mide otra cosa, sirve de referencia |
| 7 | Columna `tipo_efecto` (directo / indirecto / pasivo) en `oraciones_candidatas` | Eje distinto de `tipo_relacion`, que es del paso 2 |
| 8 | Reorganizar `recursos/` en `organismo/` y `estandar/`; mover a recursos el patrón de organismo, hoy en `vocabulario.py` | Decidir dónde va `palabras_comunes.txt` |
| 9 | Vía del bronce que produzca la clasificación de fuerza antes de la validación | No existe ni como rama de git ni como vía del pipeline |

### 3.3 Cruce contra la base curada — parcialmente resuelto

| # | Qué | Estado |
|---|---|---|
| 10 | Vocabulario de `Origen`, `Interaction`, `Reference` | **Hecho** (2.4) |
| 11 | Decidir dónde vive el cargador de la base curada | Pendiente. No cabe en ningún paquete: `grn_etl` y `etapa2` son biblioteca estándar; `grn_bronce` no puede leer validación; `grn_verificacion` está fuera de alcance. Opciones: adelantar `grn_verificacion/`, o leer el xlsx con `zipfile` + XML estándar desde `etapa2/`. Hoy la medición vive en scripts de un solo uso, no reproducible |
| 12 | Cruce de PMIDs con normalización | **Hecho** (2.4). Falta persistirlo como script versionado |
| 13 | Separar el denominador por origen | **Hecho**: 2 003 filas exigibles, vía la etiqueta de homología |
| 14 | Reportar candidatas nuevas: pares del bronce ausentes de la base curada | Pendiente. Entregable que el asesor quiere ver |
| 26 | Adoptar el vocabulario de signo de `Interaction` como tabla de equivalencias en el paso 2 | `+`/`-`/`Unknown` ↔ `+`/`-`/`?`. Sin tocar el bronce. `d` sin mapear hasta que el asesor lo defina |

### 3.4 Bronce v1, cierre

| # | Qué | Nota |
|---|---|---|
| 15 | Llenar los 50 juicios y correr `unir_juicios.py` | **Hecho** el 11-sep (2.3): 44.0 % (22/50) |
| 16 | Regla de autorregulación con bandera propia | Oro: 84.7 % → 89.2 %. Base curada: 43 filas del denominador hoy imposibles |
| 17 | Cerrar los huecos del diccionario | Mayor causa de pérdida en ambas referencias: 12 de 27 en el oro; 917 menciones (77 ids) sin locus en el cruce |
| 18 | Disparador dominante | Sube el signo utilizable de 114 a ~675 pares. También desbloquea la medición de signo, hoy imposible: 14 de las 22 relaciones juzgadas traen `signo_sugerido` sin resolver y queda 1 evaluable. No arregla la inversión del fenotipo del mutante |
| 19 | Lista `requiere_contexto` para símbolos ambiguos (`tag` = PA0010, 568 menciones de jerga) | |
| 20 | Pruebas para `unir_juicios.py`, `evaluar_cobertura_bronce.py` y el subcomando `pares` | Tres piezas sin cobertura |
| 27 | Revisar el 2.º PMID más frecuente del denominador: 179 filas, XML disponible, 25.1 % de cobertura | O reporta en tablas, o hay un patrón de redacción que el bronce no capta |
| 28 | Unificar la cifra de autorregulación | El comentario de `evaluar_cobertura_bronce.py` dice 10 filas / 5.7 %, la bitácora mezcla 4.5 puntos con 5.7 %, y lo medido es 8 de 176 (4.5 puntos) y 11 de 190 (5.8 puntos). Tres cifras para lo mismo en tres lugares |
| 29 | Versionar el script que sorteó la muestra de 50 | **Hecho** el 11-sep: `etapa2/evaluacion/muestrear_candidatas.py` reproduce el archivo fila por fila |
| 30 | Inversión de dirección | 6 de 24 errores de la muestra son pares correctos mal orientados. Hoy la dirección sale de `es_tf`; revisar los 6 casos para ver si son dos TF, ninguno, o sintaxis contraria a la heurística. Candidato: parseo de dependencias con scispaCy |

### 3.5 Diferido

| # | Qué | Nota |
|---|---|---|
| 21 | Bronce incremental por (método, versión) | Hoy es todo-o-nada; la clave única de `texto_unidades` incluye `corrida_id`. Bloquea la recurrencia |
| 22 | Comando que encadene re-búsqueda → texto completo → corpus nuevo → bronce, y diff entre versiones de corpus | Visión de actualización mensual del asesor |
| 23 | Procesamiento de PDF con PyMuPDF | **Baja prioridad, confirmado con datos:** solo 66 filas del denominador (9.5 % de las que tienen solo abstract) ganarían texto. En el corpus, solo 88 documentos dependen del PDF: los otros 96 con PDF ya tienen XML. PMID B quedó fuera del denominador por inalcanzable |
| 24 | Ventana de contexto para las 7 pérdidas de coocurrencia del oro | Caso por caso |
| 25 | Segundo eje de fuerza: la del método experimental | Distinto del eje léxico que pidió el asesor. Decidir si entra |

---

## 4. Preguntas para el asesor

1. **Confirmar la exclusión de homología** del denominador exigible (2 850 filas), y qué hacer con las 66 que traen además una cita directa.
2. **Posible error de captura en la base:** 15 filas con etiqueta de homología terminan en PA15, PA16… hasta PA29, un número distinto en cada una, todas con signo `-`. El patrón sugiere un arrastre de celda en Excel. Observación, no conclusión.
3. **Qué significa `d`** en `Interaction` (14 filas), y si el vacío de BioBERT (123 filas) equivale a `Unknown`.
4. **¿"Histórica" y "Validada" son la misma base?** Los dos valores de `Origen` usan nombres distintos para lo que parece lo mismo.
5. **Las 515 filas del denominador cuyo artículo no está en el corpus** (25.7 %) son el argumento más fuerte para la query refinada pendiente del grupo de OPM.
6. **¿La actualización recurrente es requisito o visión?** De la respuesta depende si el punto 21 sube de prioridad.
