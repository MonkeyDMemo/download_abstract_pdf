# PLAN — Pipeline GRN · *Pseudomonas aeruginosa*

Actualizado: 11-sep-2026; la tabla 3.1 (crítico), al 28-sep-2026; filas 11, 18, 30, 33, 36 y 37, al 8-oct-2026; §1.4 y fila 34, al 16-oct-2026. Documento guía del repositorio.
Tres registros separados a propósito: lo **acordado** con el asesor es la fuente de verdad; lo **construido** es lo que el repositorio demuestra hoy; lo **pendiente** es la resta de los dos primeros. Nada se mueve de registro sin evidencia.

Numeración: paso 0 extracción · paso 1 identificación (bronce) · paso 2 verificación · paso 3 consolidación.
Objetivo: una GRN como grafo dirigido — nodos = genes y sus reguladores; aristas = regulador → blanco, con signo y condición.

**Dos referencias distintas, nunca intercambiables:**
- **Oro propio** — `etapa2/oro_pseudomonas.tsv`, 190 pares construidos por el equipo, seleccionados por estar atestiguados en el corpus.
- **Base curada** — `datos/validacion/GRN_experimental.xlsx`, 5 584 interacciones del laboratorio, sin filtro de encontrabilidad en texto.

Toda cifra debe declarar contra cuál se midió.

---

## 1. Acordado con el asesor

### 1.1 De la reunión del 11-sep-2026

- **Operones.** Cuando el texto dice que un regulador actúa sobre un operón (ej. "ambos operones pel y psl son directamente regulados por AmrZ"), la relación alcanza a todos los genes que ese operón contiene, no a uno solo. Acordado: agregar una columna de operón en el bronce, extraer el distinto de operones encontrados, y documentar los catálogos de operón → genes.
- **El 44 % como línea base aceptada.** Se presentó como precisión de un sistema sin entrenar, juzgada a mano sobre 50 abstracts. El asesor lo aceptó en ese marco; se recalculará al conectar el clasificador.
- **Conectar el bronce con la capa de evaluación (silver)** usando el BioBERT ya entrenado, ahora que existen la base de evaluación y la salida tabular.
- **Pendiente heredado**: ampliar los catálogos de funciones biológicas y revisar las proteínas, que no avanzó esta semana.
- **Nomenclatura**: la capa se llama **silver** en el repositorio. En la sesión se dijo "Silva"; se unifica en silver para no duplicar vocabulario.

### 1.2 De la reunión del 04-sep-2026

- **Dos niveles de fuerza en la relación.** Regulación directa fuerte (unión al promotor, activación, represión explícita) frente a influencia indirecta (over-expression, regulates, sobreexpresión, efecto biológico sin mecanismo). Los disparadores que ya se extraen son lo que permite la clasificación.
- **Dos listas de disparadores**, una robusta de unión directa y otra experimental/indirecta, en lugar de una sola lista.
- **Columna de tipo de efecto** en la salida: directo / indirecto / pasivo.
- **Recursos separados en dos clases.** Específicos del organismo (genes, TFs, operones, locus tags), que cambian al pasar a otra bacteria; e inherentes o estándar (evidencia experimental, funciones biológicas, signos), reutilizables para cualquier organismo. Cambiar de organismo debe ser cambiar solo los archivos específicos.
- **Todo esto es trabajo del bronce, antes de la validación.** El bronce clasifica fuerza por léxico; el paso 2 verifica.
- **Cruce contra la base curada como entregable**: cuáles interacciones tienen su artículo entre los descargados, y cuáles serían candidatas nuevas.
- **Las interacciones por homología no son exigibles al pipeline.** Confirmado empíricamente (ver 2.4).
- **Catálogos actualizables por retroalimentación**, en base de datos, por organismo.
- **Visión de actualización recurrente**: rehacer la búsqueda periódicamente, versionar por fecha, medir qué interacciones son nuevas.

### 1.3 De acuerdos previos vigentes

- El paso 1 entrega el *dónde*, no el *sí*. Existencia y signo se deciden en el paso 2.
- El bronce se construye solo desde el texto. La base curada entra en pasos 2 y 3, nunca en la extracción.
- Tres vías de verificación sobre el mismo conjunto de evaluación: BERT del laboratorio reajustado, fine-tuning de LLM, agente con directrices.
- Fine-tuning sobre la base curada solo con partición por PMID y test retenido.
- Trazabilidad: toda fila conserva documento, fuente, offsets y la corrida que la produjo.

### 1.4 De la reunión del 25-sep-2026 (operones)

Lo único acordado es el pedido. El resto son siete decisiones que se le pidieron al asesor y que siguen sin respuesta escrita. El guion de la reunión es `docs/reunion-asesor-25sep.md`, con su fe de erratas. El estado y nuestras recomendaciones están en `docs/operones-asesor.md`.

- **Pedido: los operones de PAO1 tal como los muestra Pseudomonas Genome DB.** Entraron el 27-sep por la exportación de su curador. El sitio está tras un desafío de Cloudflare y no ofrece descarga de operones.
- **Lo que quedó por decidir:**
  - **D1, patrón de locus tag:** pendiente.
  - **D2, las 16 unidades de BioCyc con cita y sin código de evidencia:** pendiente.
  - **D3, decisión 3 (abierta):** respuesta verbal, probable (semana del 5 al 9 de octubre de 2026). GRN_experimental es la red regulatoria y no una fuente de operones. Falta confirmar por escrito si alguna relación se amplió por pertenencia a operón; hasta entonces la pertenencia solo anota.
  - **D4, CDBProm y la clave de la unidad:** pendiente.
  - **D5, el volcado de PGD:** superada el 27-sep.
  - **D6, las tres decisiones propias:** pendiente.
  - **D7, los 103 operones fuera del catálogo:** pendiente; es la fila 34.
- **El 16-oct se agregaron dos decisiones:** D8, contar la literatura por PMID único, y D9, operones en la red, expandidos o como anotación.

---

## 2. Lo que ya se tiene

Verificado contra el repositorio el 10-sep-2026.

### 2.1 Paso 0 — extracción

- Corpus congelado **v0-agosto**: 2 361 artículos; 2 354 con resumen; 918 con texto completo de PMC; 184 con PDF, ninguno procesado; 96 tienen también XML, así que solo 88 dependen del PDF.
- Control en SQLite: `consultas`, `ejecuciones`, `documentos`, `consulta_documento`, `descargas`, `corpus`, `corpus_documento`.
- Búsqueda por año de publicación (`--desde/--hasta`) y descarga incremental. Versionado con `corpus crear --nombre`.
- Desde el 13-oct-2026: más de 10 000 resultados se parten solos por fecha de publicación (`pubmed.tramos_por_fecha`), cada lote de efetch se guarda y vincula al llegar, `run --pausa` espera entre lotes, `ejecuciones.parametros` registra lo pedido (fechas, límite, tramos), y `export --formato zip` / el botón «Exportar» del tablero arman el paquete por consulta (CSV, JSONL, XML y LEEME). Motivo: la consulta de plantas transgénicas (83 638 resultados) se había corrido por año con límite 1 000 y dejó 5 540 documentos truncados como corridas «ok».

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
- **23-oct-2026: el 44 % recalculado con los tres modelos** como filtro, sobre las mismas 50:
  - *E. coli*: 16/37 = 43.2 %, retiene 16 de las 22 correctas.
  - Curada v1: 5/9 = 55.6 % [26.7, 81.1], retiene 5 de 22.
  - Curada v2: 16/28 = 57.1 % [39.1, 73.5], retiene 16 de 22. Su signo acierta 9/12, contra un 73.3 % de «siempre +» que no sale de la misma base. La v2 se eligió después de ver las 50, así que es exploratoria.
  - **El signo con su línea base sobre los mismos ítems** (`evaluar`, desde el 23-oct). Con *E. coli*, de las 15 `si` con signo claro:
    - cuando BioBERT da signo, 11/11, contra 9/11 de «siempre +» en las mismas;
    - con la abstención como error, 11/15 contra 11/15. El 73.3 % era esta segunda base.
    - Las curadas se recalculan en el servidor (`servidor-cierre.md` §6). Con n = 11 no se concluye nada sobre el signo.
  - Separar los pares que cada modelo vio al entrenar: el código está (`evaluar --particion`) y corre en el servidor.
- Guarda anticircularidad: `test_contaminacion.py` impide que el bronce nombre `oro_pseudomonas`.

### 2.4 Evaluación contra la base curada — medido el 10-sep-2026

**Estructura.** 5 584 filas, 8 columnas: `Source`, `Target`, `Interaction`, `Reference`, `Source_Locus_id`, `Target_Locus_id`, `Origen`, `Contributions`. Protegida por `.gitignore`, sin rastro en el historial de git.

- `Origen` (3 valores) indica en qué versión de la base vive la fila, no cómo se obtuvo: Histórica 4 824 · BioBERT 544 · Ambos 216. **No sirve para separar el denominador.**
- `Interaction` codifica solo signo: `+` 4 059 · `Unknown` 786 · `-` 598 · vacío 123 · `d` 14 · `+, +` 1 · 3 celdas con un locus corrido. Mapea uno a uno con el +/−/? del bronce.
- **La etiqueta de `Reference` sí marca procedencia:** dos variantes que dicen "homology", en **2 850 filas (51 %)**, 2 808 de ellas de Histórica. Una variante indica inferencia desde la cepa PA14.
- `Reference` son PMIDs; requiere normalizar (float con `.0`, listas por coma, etiqueta pegada, PMIDs de 7 dígitos, 1 DOI). 310 PMIDs distintos, 208 en el corpus (67.1 %).
- **Nota del 15-oct-2026** (tramo 1 de `reentrenar`, solo conteos, sin abrir el archivo). Los 310 son identificadores distintos: **309 PMIDs y 1 DOI**. La única fila sin PMID es la del DOI, y `validacion.pmids_de` cuenta los DOIs aparte; el 67.1 % se calculó con 310 en el denominador. `Origen` no trae los tres valores literales: son etiquetas de 26 a 28 caracteres que contienen «Histórica», «BioBERT» o «Ambos» (con estos conteos exactos); el lector las reconoce por palabra clave desde el commit 7a8b01b. Todo lo demás de esta sección cuadró.
- Locus: formato PA#### en 5 578 de las 5 584 filas; las otras 6 tienen un locus inválido, según el lector versionado (23-oct-2026). Son 3 006 distintos, de los que 1 796 (59.7 %) aparecen en `menciones`.

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

**Nota del 23-oct-2026: el contraste versionado.** Es `cli contraste` sobre la corrida 4, corrido en el servidor; el informe filtrado está en `salidas/contraste/CONTRASTE.md`. La base coincide en los 14 conteos de esta sección.

| | versionado (corrida 4) | esta sección (corrida 1) |
|---|---:|---:|
| filas con dos locus válidos | 5 578 | 5 584 |
| − homología | 2 850 | 2 850 |
| − archivo de exclusiones | 651 | 731 |
| **exigibles** | **2 077** | **2 003** |
| en el corpus / con XML / solo abstract | 1 562 / 859 / 703 | 1 488 / 791 / 697 |
| autorregulación | 46 | 43 |

- **Conciliación:** 2 077 = 2 003 − 6 + 80, contada en el servidor el 23-oct.
  - Las 6 son filas con un locus inválido.
  - Las 80 citan el artículo excluido junto con otro, y se quedan: una fila sale por el archivo solo si **todos** sus PMIDs están en él (`motivo_de`).
  - Ninguna fila de homología cita el artículo excluido, así que el orden de las dos exclusiones no mueve nada.
- **Cobertura, con expansión:**
  - regla a), 43.1 % en todas y 45.3 % con XML;
  - regla b), 17.6 % en todas y **30.2 % (259/859) [27.2, 33.3] con XML**;
  - sin expansión, la b) con XML da 24.8 %.
- **La red, en el estrato sin BioBERT:**
  - **dirigido, 41.2 % (642/1 560) [38.7, 43.6]**; solo al revés, 2.1 %;
  - orientación, 95.3 % (642/674): Histórica 505/536 y Ambos 137/138;
  - el estrato BioBERT, circular, va aparte, con 30.2 %.
- **El techo de la regla a)** sobre esas 1 560 es 720 (46.2 %) [43.7, 48.6]. La red encuentra 674 en alguna dirección, todas dentro del techo: 0 fuera, como debe ser.
- **El signo.** De las 605 dirigidas con signo en la base, 319 coinciden, 47 contradicen, 155 son `regulates` y 84 son mixtas.
  - Cuando la red da signo, acierta **319/366 [83.3, 90.2]**, contra 280/366 (76.5 %) [71.9, 80.6] de «siempre activa» en las mismas.
  - **Con la abstención como error, la red pierde:** 319/605 (52.7 %) [48.7, 56.7], contra 448/605 (74.0 %) [70.4, 77.4] de «siempre activa». El 39.5 % se queda sin signo.
  - Se escribe 319/366, y no «87.2 %», porque esa cifra ya significa otra cosa en la tabla de arriba.
- **Candidatas nuevas:** 7 849, reportadas como candidatas.
- **Concentración:** 5 artículos reúnen 672 de las 2 077 (32.4 %).
- **La red recomendada** (`contraste --red recomendada`, el mismo día; `salidas/contraste/CONTRASTE_recomendada.md`):
  - Tiene 10 592 aristas: 8 747 llevadas a locus, 131 sin locus, 181 de autorregulación con un solo locus y 1 533 expandidas, que se omiten porque no tienen evidencia propia.
  - Da 9 012 pares de locus, los 9 011 de `red.tsv` más uno, y el mismo dirigido, 642/1 560.
  - **Signo:** 313/360 cuando lo da, contra 276/360 de «siempre activa»; con la abstención como error, 313/605.
  - **Candidatas nuevas:** 7 850.
  - Sus autorregulaciones marcadas le cambian el signo a 28 pares que `red.tsv` ya tenía.

### 2.5 Precisión ciega con un experto — tanda 1, 23-oct-2026

La muestra ciega es de 200 oraciones de la misma población que el 44 % (las candidatas con regulador y blanco de la corrida 4, sin las reservas). Un experto pagado por hora anotó 198 de los 200, de 152 PMIDs, con la red de *E. coli*. Resultaron 144 `si`, 23 `dudoso` y 31 `no`.

| | con dirección | sin exigirla |
|---|---|---|
| bronce (198) | **53.0 % (105/198) [46.1, 59.9]** | 72.7 % |
| red, en los 142 cuya oración sostiene una arista | **61.3 % (87/142) [53.1, 68.9]** | 77.5 % |

- **Diferencia pareada,** red menos bronce: **[+3.7, +12.6]** por bootstrap.
- **Retención:** 71.7 % del total y **82.9 % de las verdaderas (87/105)**.
- **Inversiones:** 39 de 144 (27.1 %) [20.5, 34.9]. Es la pérdida más grande; ver la fila 30. Entre los `si` que la red retiene son 23 de 110 (20.9 %) [14.4, 29.4].
- **Signo de la red,** con su «siempre +» sobre los mismos ítems (`precision-ciega` v2, 23-oct):
  - cuando lo da, 42/48 (87.5 %) [75.3, 94.1], contra 35/48 (72.9 %);
  - con la abstención como error, 42/60 (70.0 %) [57.5, 80.1], contra 41/60 (68.3 %): **empata con «siempre +»**.
  - El 70.7 % que se citaba era la base del bronce, 53/75.
  - Tomar el signo por (par, oración) en vez de por par no movió ninguna de las dos cifras.
- **Sensibilidad,** con las 5 negadas anotadas `si` tratadas como `no`: 51.0 % y 59.9 %, diferencia [+4.3, +13.2].
- **Normalización:** solo de códigos, 46 direcciones vacías y 43 signos `0`.
- **Sin tiempos ni κ.**
- **Diseño desde aquí** (rúbrica, enmienda 2): la tanda 1 es de desarrollo y la tanda 2 de prueba. La tanda 2 sale sin los PMIDs ni los códigos de la tanda 1, y toda regla nueva se reporta en ella.

---

## 3. Lo que falta hacer

Lo que está abierto en todo el proyecto, no solo en estas tablas, está junto y
con sus fuentes en [`docs/pendientes.md`](docs/pendientes.md), al 28-sep-2026.

### 3.0 Calendario del cierre técnico — propuesto, por validar el 23-oct-2026

*Actualizado el 22-oct-2026: la reunión del 23 se canceló. El servicio social
se entrega con decisiones por omisión (`docs/reunion-asesor-23oct.md`, ahora
hoja de entrega), un anotador experto sobre 200 ítems y el LLM pasado a la
tesis. La tabla queda como el plan original.*

Del Documento de Tesis v1 (20-oct-2026), marcado **[Nuestro]**: es propuesta
del autor y no acuerdo con el asesor hasta el viernes 23. La parte técnica del
servicio social cierra en 15 días, en cuatro carriles paralelos; noviembre
queda para el informe, diciembre para la revisión, y el cierre es el
29-dic-2026.

| Carril | Fechas | Qué |
|---|---|---|
| Decisiones con el Dr. Galán | 23-oct | rúbrica, nube, CollecTF, calendario |
| Claude Code: código | 21 al 27-oct | alineación v2 de la sintaxis, contraste con la base curada, la red versionada |
| Servidor: BioBERT | 21 al 30-oct | métricas y 5 pliegues por PMID (cumplido el 16-oct con curada-v1) |
| Anotación con ayudantes | 24-oct al 2-nov | muestra ciega y candidatas nuevas; arranca con la rúbrica ya validada |
| Claude Code: plata y oro | 28-oct al 3-nov | LLM sobre el residuo, consolidación |
| Cierre técnico | 4-nov | |

Si una fase se atrasa, se recorta en este orden: el agente revisor con
Strands, las pruebas del tablero con Playwright y el NER complementario. El
contraste con la base curada y la red no se recortan.

### 3.1 Crítico — integridad y reproducibilidad

| # | Qué | Por qué | Estado |
|---|---|---|---|
| 1 | Extender la lista blanca de `test_contaminacion.py` a `GRN_experimental` y `datos/validacion` | La regla de confidencialidad frena las herramientas de Claude, no los scripts. `test_contaminacion` protege `oro_pseudomonas` y `auditoria_signo` y vigila `etapa2`, `grn_bronce` y `grn_comun`; falta cubrir `GRN_experimental` y `datos/validacion`, y tiene dos límites: distingue mayúsculas y no revisa subcarpetas. Ampliar también a comandos: un `grep` sobre la raíz recorre `datos/validacion`. Negar `Bash(grep *)` sobre rutas de datos o exigir `--exclude-dir=datos` | **Hecho en código** (verificado el 28-sep): protege los cuatro nombres, sin distinguir mayúsculas, entra en subcarpetas y vigila también `grn_operones`. Para comandos rige la regla de CLAUDE.md (herramienta `Grep`, no `grep -r`) |
| 2 | Nomenclatura de las dos referencias en repositorio y documentos | Toda cifra debe declarar contra cuál se midió | Pendiente |
| 3 | Crear `pyproject.toml` con el extra `[bronce]` | Un clon limpio no reproduce la exportación a Excel; openpyxl está instalado a mano | **Hecho** el 28-sep: extras `[bronce]` (openpyxl, PyMuPDF) y `[operones]` (openpyxl); el núcleo sin dependencias |
| 4 | Alinear `CLAUDE.md` con la realidad del bronce (dice idempotente; `identificar.py` es todo-o-nada) | Documento que gobierna afirmando algo falso | **Hecho** el 28-sep: CLAUDE.md dice ahora que el bronce es idempotente por corrida, no por unidad, y deja la regla por unidad como meta (punto 21) |
| 5 | Registrar en `corridas` las secciones excluidas y la huella de `secciones.tsv` | Si el archivo cambia, la corrida no puede decir con qué regla se hizo | **Hecho** el 28-sep: `parametros` guarda la huella de los siete recursos que lee la identificación (diccionario, catálogo de operones, cuatro vocabularios, `secciones.tsv`), las clases fuera y cuántas etiquetas caen en ellas (61; cuáles son lo fija la huella de `secciones.tsv`, que está versionado). Si un recurso cambia sin subir VERSION, `exportar` avisa |
| 36 | `etapa2/test_clasificar.py`: dos pruebas de `PruebasMainSinTorch` fallan donde torch se importa | Suponen que `import torch` falla y no lo fuerzan: en el `.venv` `main()` sigue hasta cargar un checkpoint falso (sin `model_type`, pesos vacíos) y da `ValueError` del tokenizador. Pasan con el Python del sistema solo porque ahí torch está roto. No afecta la clasificación real. Arreglo de prueba, permitido en `etapa2` congelada: `mock.patch.dict(sys.modules, {"torch": None, "transformers": None})` alrededor de `C.main()` en `correr()`; probado en una copia | **Hecho** el 8-oct: `correr()` envuelve `C.main()` en `mock.patch.dict(sys.modules, {"torch": None, "transformers": None})`; etapa2 da 525 en verde con el `.venv` |
| 37 | `etapa2/test_extraer_pares.py` falla en un clon limpio | Lee los `entity_marked_*.jsonl` del asesor en `etapa2/para_colab/`, que están en `.gitignore`, y no se salta si faltan (1 error de `setUpClass`, 2 errores, 1 falla). `traspaso-maquina-nueva.md` y `migracion-maquina.md` piden parar si una prueba falla, así que hoy frenan una máquina sana. Arreglo: `skipUnless` con el motivo, y que la guía de traspaso copie los `.jsonl` también a `etapa2/para_colab/` (la comprobación 4 los sigue leyendo de la raíz) | **Hecho** el 8-oct (la parte de código): las pruebas que leen los `.jsonl` se saltan con el motivo cuando faltan. Queda corregir la guía de traspaso |

### 3.2 Lo que pidió el asesor

| # | Qué | Nota |
|---|---|---|
| 6 | Partir `disparadores.csv` en dos por fuerza: unión directa y experimental/indirecta, conservando el signo | Precursor en `etapa2/extraer_pares.py`; mide otra cosa, sirve de referencia |
| 7 | Columna `tipo_efecto` (directo / indirecto / pasivo) en `oraciones_candidatas` | Eje distinto de `tipo_relacion`, que es del paso 2 |
| 8 | Reorganizar `recursos/` en `organismo/` y `estandar/`; mover a recursos el patrón de organismo, hoy en `vocabulario.py` | Decidir dónde va `palabras_comunes.txt` |
| 9 | Vía del bronce que produzca la clasificación de fuerza antes de la validación | No existe ni como rama de git ni como vía del pipeline |
| 31 | Columna de operón en la salida del bronce, con el distinto de operones encontrados | **Hecho** (17-sep, corrida 2): 7 136 menciones de operón, 363 operones distintos, 3 603 candidatas afectadas (12.1 %), 393 con operón como blanco. Expansión única en `grn_bronce/operones.py`; `etapa2/evaluar_oro.py` delega ahí. El bronce guarda la mención del operón y su expansión a genes por separado |
| 32 | Ampliar catálogos de funciones biológicas y revisar las proteínas | **Limpieza hecha** (17-sep, corrida 3): emparejamiento normalizado por mayúsculas y guiones (recupera las 329 menciones sin categoría, aporta 2 243 nuevas), `regulation` movida a `contexto_regulatorio.csv` con tipo y columna propios, `western blot` añadido y 8 filas redundantes quitadas de `evidencia_experimental.csv`. **Corte de virulencia hecho** (corrida 4): `virulence_molecule` / `virulence_phenotype` / `virulence_general`, con la última marcada como señal débil y no como atributo de nodo; el escenario clínico salió a `infection_type`, que se amplió a 38 términos y se quedó en 0.73 % de las candidatas, documentado como señal débil. **Bombas de expulsión: decidido que NO entran como función.** `MexAB-OprM` y las demás familias se quedan como operón y como genes; `efflux` (6 términos, 1 126 menciones) ya cubre el concepto. Razón: la misma mención produciría tres filas en tres ejes distintos, que es exactamente el solapamiento que se deshizo al sacar `regulation`. **Queda pendiente de medir** anaerobiosis y respiración microaerobia, y metabolismo de fosfato. Antes de añadirlos se les aplica la regla de `recursos/PROCEDENCIA.md`: menciones, candidatas y reparto por sección. Si se comportan como `infection_type` —el grueso de las menciones en resumen, introducción o METHODS, y una fracción minúscula de candidatas—, no entran |
| 33 | Conectar el bronce con la capa silver usando el BioBERT entrenado | **En curso** desde el 8-oct: `grn_verificacion/puente.py` lleva las candidatas del bronce a `clasificar.py` con el mismo marcado del entrenamiento, `capa.py` arma la tabla oración + funciones + operones + BioBERT y `evaluar.py` recalcula el 44 %. Todo lo corre `python flujo.py`. **Corrió el 8-oct** sobre la corrida 4: 72 969 pares, 81.8 % de predicciones reutilizadas del 27-ago. Sobre las 50 juzgadas el filtro no sube la precisión (43.2 % con umbral contra 44.0 %) y retiene 16 de las 22 correctas; el signo, donde lo da, acierta 11 de 11. Ver la bitácora del 8-oct. **23-oct:** el 44 % con los tres modelos está en 2.3 |
| 34 | Los 103 operones del corpus ausentes del catálogo del paso 1 | **Espera criterio del asesor** (D7, §1.4). Son 447 menciones; los mayores, cyaAB, exoSTY, rsmZY, phzMS, lasRI y sodAB. **Medido el 27-sep:** los mayores no son operones, sino genes separados en el genoma que el texto abrevia juntos, y solo 3 de los 103 tienen su conjunto exacto en la base de operones. Completarlos tal cual metería uniones que no se cotranscriben. **Recomendación:** dejarlos como lista de huecos (`docs/operones-asesor.md` §7). Listado completo en `salidas/operones_corrida2_20260917.csv` |

### 3.3 Cruce contra la base curada — parcialmente resuelto

| # | Qué | Estado |
|---|---|---|
| 10 | Vocabulario de `Origen`, `Interaction`, `Reference` | **Hecho** (2.4) |
| 11 | Decidir dónde vive el cargador de la base curada | **Decidido el 8-oct:** `grn_verificacion/validacion.py`, solo estándar, con la ruta por argumento (la guarda de contaminación sigue con la lista blanca vacía). Corre en el servidor del asesor, donde vive el `.xlsx`; lo usa `entrenamiento.py` para la supervisión distante. Las tablas `validacion_interacciones` y `particion` quedan propuestas, sin aplicar |
| 12 | Cruce de PMIDs con normalización | **Hecho** (2.4). **Versionado el 21-oct** en `grn_verificacion/contraste.py` (`cli contraste`), que reproduce el 2.4 y mide además el recall de la red. Probado con bases sintéticas; falta correrlo contra la base real, donde viva la base (`docs/contraste-curada.md`). **Corrido el 23-oct en el servidor**: denominador 2 077 conciliado con 2 003, regla b) con XML 30.2 %, red dirigida 41.2 % (2.4, nota del 23-oct). **Fase 2, el mismo día:** suma la línea base «siempre activa», la orientación por estrato, el techo de la regla a) y `--red NOMBRE`, que contrasta la red recomendada |
| 13 | Separar el denominador por origen | **Hecho**: 2 003 filas exigibles, vía la etiqueta de homología |
| 14 | Reportar candidatas nuevas: pares del bronce ausentes de la base curada | **Código listo el 21-oct:** `cli contraste` escribe las aristas de la red que la base no tiene, en las dos direcciones, solo en la carpeta confidencial; al informe va su conteo. Falta correrlo contra la base real. Entregable que el asesor quiere ver. **Corrido el 23-oct:** 7 849 candidatas nuevas, cuya lista se queda en la carpeta confidencial; al informe va solo el conteo |
| 26 | Adoptar el vocabulario de signo de `Interaction` como tabla de equivalencias en el paso 2 | `+`/`-`/`Unknown` ↔ `+`/`-`/`?`. Sin tocar el bronce. `d` sin mapear hasta que el asesor lo defina |

### 3.4 Bronce v1, cierre

| # | Qué | Nota |
|---|---|---|
| 15 | Llenar los 50 juicios y correr `unir_juicios.py` | **Hecho** el 11-sep (2.3): 44.0 % (22/50) |
| 16 | Regla de autorregulación con bandera propia | Oro: 84.7 % → 89.2 %. Base curada: 43 filas del denominador hoy imposibles |
| 17 | Cerrar los huecos del diccionario | Mayor causa de pérdida en ambas referencias: 12 de 27 en el oro; 917 menciones (77 ids) sin locus en el cruce |
| 18 | Disparador dominante | Sube el signo utilizable de 114 a ~675 pares. También desbloquea la medición de signo, hoy imposible: 14 de las 22 relaciones juzgadas traen `signo_sugerido` sin resolver y queda 1 evaluable. No arregla la inversión del fenotipo del mutante **8-oct, medido sin tocar el bronce** (`grn_verificacion/evaluar.py`, sobre los 1 186 pares dirigidos de la corrida 4, techo 674): con signo único, el bronce de hoy da 114; el control léxico (el disparador con signo, + o −, más cercano; solo estándar), 537 (contradictorios de 194 a 137); la sintaxis, 166 (contradictorios 47, pero 483 pares sin disparador en el árbol). Es consistencia, no acierto: falta medir el acierto contra signos juzgados y elegir la regla de la v5. **23-oct:** en la tanda 1 la red da signo en 48 de los 60 `si` bien orientados con signo y acierta 42. El voto léxico (por evidencia o por arista) y el voto por artículo entran como parámetros apagados de `consolidar`, y se miden solo en la tanda 2. **En código desde el 23-oct** (`grn_red/signo.py`, fase 3): las cuatro redes (`signo`, `signo_conservador`, `signo_lexico`, `signo_articulo`) están armadas sobre la corrida 4 y cambian el signo de 571, 464, 375 y 202 aristas; sus huellas están en `docs/protocolo-tanda2.md`, enmienda 1 |
| 19 | Lista `requiere_contexto` para símbolos ambiguos (`tag` = PA0010, 568 menciones de jerga) | |
| 20 | Pruebas para `unir_juicios.py`, `evaluar_cobertura_bronce.py` y el subcomando `pares` | Tres piezas sin cobertura |
| 27 | Revisar el 2.º PMID más frecuente del denominador: 179 filas, XML disponible, 25.1 % de cobertura | O reporta en tablas, o hay un patrón de redacción que el bronce no capta. **23-oct:** los 5 artículos con más filas reúnen 672 de las 2 077 exigibles; la medición de tablas (`cli tablas`) corre en el servidor. **Medido el 23-oct con `main`** (igual que la primera corrida, hecha con el código aún sin revisar): 3 de los 5 artículos no tienen XML (367 filas; uno está fuera del corpus y dos solo tienen abstract). El 2.º sí: de sus 191 filas, la regla b) cubre 3, y en las otras 188 falta del XML al menos uno de los dos locus (en 113, los dos). Lo probable es que la base cite su material suplementario, que no viene en el XML, y no una redacción que el bronce no capte |
| 28 | Unificar la cifra de autorregulación | El comentario de `evaluar_cobertura_bronce.py` dice 10 filas / 5.7 %, la bitácora mezcla 4.5 puntos con 5.7 %, y lo medido es 8 de 176 (4.5 puntos) y 11 de 190 (5.8 puntos). Tres cifras para lo mismo en tres lugares |
| 29 | Versionar el script que sorteó la muestra de 50 | **Hecho** el 11-sep: `etapa2/evaluacion/muestrear_candidatas.py` reproduce el archivo fila por fila |
| 30 | Inversión de dirección | 6 de 24 errores de la muestra son pares correctos mal orientados. Hoy la dirección sale de `es_tf`; revisar los 6 casos para ver si son dos TF, ninguno, o sintaxis contraria a la heurística. Candidato: parseo de dependencias con scispaCy. **8-oct:** revisados los 6 a mano en `docs/ficha-invertidos-punto30.md` (en los seis el regulador verdadero no es TF; el BioBERT no puede corregirlos); la sintaxis con spaCy de `grn_bronce/sintaxis.py` se mide contra esa ficha. **Medido:** corrige 1 de los 4 recuperables (la 20; se esperaban 2), no rompe ninguna de las 22 `si` y confirma 6. No cumple el criterio (≥ 3 de 4 y 0 rotas): la dirección sintáctica queda como columna informativa de la capa. La 8 falla por la regla «X-dependent»; no se ajusta con estas 50. **21-oct, alineación v2** (`sintaxis.py` VERSION 2): la mención que pierde en `filter_spans` se alinea a su contenedor, y los pares `sin_alineacion` bajan de 8 485 a 0 sin cambiar ninguna otra línea. De esos pares, 600 ahora se orientan y 4 646 salen `mismo_token`. D1 sigue en 1 de 4, así que la dirección sintáctica sigue informativa (`docs/plan-sintaxis-bronce.md` §7). **23-oct, tanda 1:** 39 de 144 relaciones verdaderas (27.1 %) tienen la dirección contraria a la del bronce, contra 6 de 28 en las 50. Es la pérdida más grande; las reglas de dirección se proponen con la tanda 1 y se miden en la tanda 2 |
| 35 | Nomenclatura PA14 | 377 locus tags `PA14_#####` distintos, 837 menciones en 83 documentos, ninguno reconocido por `genes_pao1.tsv`. Es una causa medible de los huecos del diccionario (punto 17) y es la cepa de la que provienen las 2 850 interacciones por homología de la base curada. Evaluar un mapeo PA14 → PAO1 por ortología. **El orden importa: arreglar el tokenizador va después del mapeo, no antes.** `_TOKEN` de `etapa2/lexico.py` no incluye el guion bajo, así que parte `PA14_23420` en `PA14` y un número que ya no llega a token; hoy eso **pierde en silencio sin fabricar falsos positivos** (cero menciones con `texto='PA14'` en las corridas 2 y 3). Arreglarlo antes del mapeo solo produciría un token que el diccionario tampoco sabe resolver |

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
