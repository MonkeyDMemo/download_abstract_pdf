# PLAN — Pipeline GRN · *Pseudomonas aeruginosa*

Actualizado: 02-sep-2026. Documento guía del repositorio. Define qué construye cada paso, qué entrega y cómo se conectan.

## 1. Panorama

Objetivo: una red de regulación génica (GRN) construida desde la literatura. La red es un grafo dirigido: nodos = genes y sus productos reguladores (factores de transcripción y factores sigma); aristas = relación regulador → gen blanco, con signo (activación / represión / desconocido) y, cuando el texto lo dice, condición. La red resultante se compara contra la red curada del laboratorio (data de validación).

| Paso | Nombre | Capa | Estado | Entrega |
|---|---|---|---|---|
| 0 | Extracción | — | cerrado | corpus versionado: abstracts, XML de PMC, PDF, con estado en SQLite |
| 1 | Identificación de elementos | bronce | foco actual | menciones normalizadas con offsets y oraciones candidatas con score |
| 2 | Verificación | bronce → silver | siguiente | relaciones candidatas con signo, condición y confianza |
| 3 | Consolidación | silver → gold | posterior | tabla de aristas verificadas, red agregada, diff contra data de validación |

Regla de capas: bronce se construye solo desde el texto. La data de validación entra en el paso 2 (evaluación y, con partición por PMID, entrenamiento) y en el paso 3 (diff). Queda fuera de la lógica de extracción.

Toda fila de cualquier tabla conserva `doc_id`, `pmid`, la fuente del texto y la corrida que la produjo (método, versión, fecha). Todo es exportable a CSV/Parquet.

## 2. Repositorio: decisión y estructura

**Decisión: un solo repositorio, un paquete por paso.** Copiar el proyecto a otra carpeta para empezar de cero produce dos bases de código divergentes y tira el historial del ETL. La sensación de "empezar limpio" se obtiene con un paquete nuevo dentro del mismo repositorio.

Regla para elegir:
- El repositorio contiene solo `grn_etl/`, `cli.py`, `.kiro/`, `tests/` y configuración → opción A: se queda como está y se agrega `grn_bronce/`.
- El repositorio arrastra scripts sueltos de las primeras iteraciones (los módulos 06–09 u otros) → opción B: repositorio nuevo `grn-pipeline`, se copian solo `grn_etl/`, `cli.py`, `.kiro/`, `.gitignore` y `tests/`; el viejo se archiva.

En ambos casos, antes de tocar nada:

```bash
git tag -a v0-extraccion -m "Paso 0 cerrado"
git checkout -b bronce
```

Estructura objetivo:

```
grn-pipeline/
├── PLAN.md                    <- este documento
├── pyproject.toml             <- extras por paso: [bronce], [verificacion]
├── .kiro/steering/reglas.md   <- apunta a CLAUDE.md y a este archivo
├── grn_etl/                   <- paso 0, cerrado; solo correcciones de errores
│   ├── db.py                  <- unico modulo con SQL del paso 0
│   ├── pubmed.py              <- clientes E-utilities, PMC, Unpaywall
│   ├── resolvers.py           <- cascada de resolucion de PDF
│   ├── downloader.py
│   ├── etl.py                 <- orquestacion
│   └── cli.py                 <- grn-etl: query, run, fulltext, estado, export
├── grn_bronce/                <- paso 1, en construccion
│   ├── db.py                  <- tablas del bronce; no toca tablas del paso 0
│   ├── texto.py               <- lectura de fuentes y segmentacion en oraciones
│   ├── diccionario.py         <- locus tags PAO1, sinonimos, lista negra
│   ├── menciones.py           <- matching por diccionario e ingesta de PubTator
│   ├── disparadores.py        <- vocabulario de verbos de regulacion
│   ├── candidatos.py          <- co-ocurrencia y score
│   ├── indice.py              <- embeddings (bloque 3)
│   ├── llm_local.py           <- Ollama (bloque 4)
│   └── cli.py                 <- grn-bronce: texto, menciones, candidatos, corrida
├── grn_verificacion/          <- paso 2, futuro
├── grn_red/                   <- paso 3, futuro
├── datos/                     <- ignorado por git: grn.db, fulltext/, diccionarios/
├── docs/
└── tests/
```

Convenciones que se conservan del paso 0: capas con dependencia en una sola dirección (`cli → orquestación → db / clientes`), sin `print()` fuera de `cli.py`, credenciales solo en variables de entorno, español sin acentos en identificadores. Diferencia con el paso 0: `grn_etl` se mantiene con librería estándar; `grn_bronce` sí usa terceros (PyMuPDF, scispaCy o pysbd, numpy; sentence-transformers y el cliente de Ollama como extras opcionales). Cada paso instala sus dependencias con `pip install -e .[bronce]`.

Todos los pasos comparten un solo archivo SQLite (`datos/grn.db`). Cada paquete crea y administra únicamente sus tablas.

## 3. Paso 0 — Extracción (cerrado)

**Responsabilidad única:** dado un conjunto de consultas de PubMed, obtener los documentos, su texto completo cuando exista, y registrar el estado de todo. Nada de interpretación del contenido.

**Entradas:** consultas registradas en `consultas`. La query refinada del Dr. se registra como consulta canónica en cuanto llegue.

**Salidas (contrato que consume el paso 1):**

| Tabla | Contenido | Campos que usa el paso 1 |
|---|---|---|
| `documentos` | un artículo, único por PMID | `pmid`, `doi`, `titulo`, `abstract`, `anio`, `revista`, `fecha_ingesta` |
| `consulta_documento` | qué consulta trajo qué documento | `consulta_id`, `pmid` |
| `descargas` | estado de texto completo por PMID y tipo (`xml` / `pdf`) | `pmid`, `tipo`, `ruta`, `sha256`, `estado`, `fuente`, `fecha` |
| `ejecuciones` | cada corrida de una consulta | trazabilidad |

Archivos en disco: `datos/fulltext/{pmid}.xml` (JATS de PMC) y `datos/fulltext/{pmid}.pdf`.

**Adición única permitida en el paso 0: el corpus versionado.** Dos tablas que siguen el mismo patrón N a N del ETL:

- `corpus`: `corpus_id`, `nombre` (p. ej. `v1`), `consulta_id`, `fecha_corte`, `n_documentos`, `hash_pmids`.
- `corpus_documento`: `corpus_id`, `pmid`.

Comando: `grn-etl corpus crear --nombre v1 --consulta <id>`. Se ejecuta después de correr la consulta canónica del Dr. y de correr `fulltext` sobre ella. A partir de ahí, el paso 1 recibe un `corpus_id`; cualquier métrica se reporta contra ese corpus.

**Cómo toma el paso 1 la información del paso 0:**

1. Lee `corpus_documento` para el `corpus_id` indicado. Esa es la lista completa de PMIDs; ninguna otra.
2. Por cada PMID toma el abstract de `documentos`, siempre.
3. Toma el texto completo en este orden: `descargas.tipo = 'xml'` con `estado = 'ok'` → `descargas.tipo = 'pdf'` con `estado = 'ok'` → ninguno. OCR queda reservado a PDF escaneados y se agrega después.
4. Solo lectura sobre las tablas del paso 0. El paso 1 nunca llama a las API de documentos; sus únicas llamadas externas son fuentes de anotación (Pseudomonas Genome DB, PubTator 3.0).

**Pendientes del paso 0 (única actividad permitida además de correcciones):** registrar la query canónica; ejecutar `fulltext` sobre ella y medir cobertura de XML y PDF; crear `corpus v1`. El soporte para XML de PMC ya existe en `descargas`; el pendiente es ejecutarlo sobre el corpus y reportar la cobertura.

## 4. Paso 1 — Identificación de elementos (capa bronce)

**Objetivo:** por cada documento del corpus, localizar dónde están los elementos y dónde puede haber una relación. Entrega el *dónde*; la decisión de si la relación existe y su signo pertenece al paso 2.

**Prioridad, en orden:** genes y proteínas normalizados a locus tag (nodos); relación con signo y condición (aristas); función biológica (atributo del nodo); evidencia experimental y organismo (metadata). El conjunto completo se nombra "funciones biológicas", como en la pizarra del Dr.

**Tablas del bronce (las crea `grn_bronce/db.py`):**

| Tabla | Campos |
|---|---|
| `corridas` | `corrida_id`, `paso`, `metodo`, `version`, `parametros`, `fecha`, `corpus_id` |
| `texto_unidades` | `unidad_id`, `pmid`, `fuente_texto` (abstract / xml / pdf), `seccion`, `num_oracion`, `texto`, `offset_ini`, `offset_fin`, `corrida_id` |
| `menciones` | `mencion_id`, `unidad_id`, `tipo` (gen / proteina / disparador / funcion / evidencia / organismo), `texto`, `id_normalizado`, `offset_ini`, `offset_fin`, `metodo`, `corrida_id` |
| `oraciones_candidatas` | `unidad_id`, `entidades` (lista de `mencion_id`), `disparador`, `score`, `metodo`, `corrida_id` |

Reglas: los offsets son absolutos sobre el texto original de la unidad, para reproducir el subrayado. Idempotencia por corrida: una corrida procesa solo las unidades sin resultado para su par (`metodo`, `version`). Toda fila apunta a su `corrida_id` y, por la unidad, a su PMID y fuente.

**Orden de construcción:**

| Bloque | Qué | Terminado cuando |
|---|---|---|
| 1. Esqueleto | tablas, lectura de fuentes (abstract, JATS de PMC, PDF con PyMuPDF), segmentación con scispaCy o pysbd, diccionario PAO1 con sinónimos y lista negra de colisiones (`fur`, `cap`) | `texto_unidades` poblada para todo el corpus; diccionario cargado con conteo de entradas |
| 2. Baseline | matching por diccionario, disparadores léxicos, co-ocurrencia de dos entidades o más por oración con score; ingesta de PubTator 3.0 por lote de PMIDs como segunda fuente de menciones | `menciones` y `oraciones_candidatas` pobladas; tasa de normalización y acuerdo diccionario vs PubTator reportados |
| 3. Embeddings | modelo local de sentence-transformers, índice en numpy o FAISS plano, consultas semilla con plantillas de regulación | precisión@k sobre la muestra de evaluación |
| 4. LLM local | Ollama, salida JSON estricta, batch multihilo | calidad y costo (tokens y minutos por 1,000 abstracts) reportados |
| 2b (opcional) | parseo de dependencias con scispaCy para pre-asignar dirección regulador → blanco en oraciones simples | se activa solo si el baseline da buena precisión en pares |

Contexto de oración anterior y siguiente (±1) como entrada de cualquier modelo de etiquetado, tomado del paper compartido por el Dr.

**Métricas del paso:** tasa de normalización, cobertura de menciones por documento, precisión y recall contra la muestra de evaluación, precisión@k de candidatas, costo por 1,000 abstracts.

**Terminado significa:** `texto_unidades`, `menciones` y `oraciones_candidatas` pobladas sobre el corpus v1; tabla comparativa de los métodos con precisión@k, recall estimado y costo; decisión escrita de qué alimenta al paso 2.

**Extensión prevista (diseño, sin implementar ahora):** el identificador es configurable por vocabulario (organismo, tipo de relación), para que el mismo módulo sirva a otras bacterias o a PPI cambiando diccionario y disparadores.

## 5. Paso 2 — Verificación (panorama)

**Entrada:** tripletas (regulador candidato, gen blanco candidato, oración) construidas desde `oraciones_candidatas` y `menciones`.

**Tres vías sobre el mismo conjunto de evaluación:** BERT del laboratorio re-fine-tuneado; fine-tuning de un LLM (local u OpenAI); agente con directrices y base de evaluación como filtro. La plantilla de prompt del paper compartido ("dada la oración, entre estas opciones, ¿qué relación hay entre la entidad 1 y la 2?") se reutiliza con nuestro conjunto de etiquetas.

**Salida:** `relaciones_candidatas`: `regulador_id`, `blanco_id`, `signo` (activacion / represion / desconocido), `condicion` (texto libre), `tipo_relacion` (regulacion_tx / ppi / otra), `confianza`, `unidad_id` de evidencia, `evidencia_experimental`, `metodo`, `corrida_id`. Alcance de tesis: `regulacion_tx`; el resto se almacena etiquetado.

**Data de validación:** tabla `validacion_interacciones` cargada desde el dump del Dr. (`regulador`, `blanco`, `signo`, `pmid_fuente`). Uso: referencia de evaluación; para fine-tuning, solo con partición por PMID registrada en `particion` (`pmid`, `split`). Antes de usar los párrafos etiquetados del laboratorio como conjunto de prueba: conocer con qué se entrenó el BERT previo.

## 6. Paso 3 — Consolidación (panorama)

**Silver:** promoción de `relaciones_candidatas` a `aristas` cuando la verificación supera el umbral de confianza. Campos: `regulador`, `blanco`, `signo`, `condicion`, `evidencia_experimental`, `pmids` (agregados), `n_evidencias`, `confianza`. Único nivel visible para consumidores.

**Gold:** red agregada desde `aristas` y diff contra `validacion_interacciones`: coincide, falta, candidata nueva. Las candidatas nuevas bien soportadas por texto pasan a curación con el Dr. Export a GraphML para Cytoscape; la tabla de aristas en CSV/Parquet es el producto principal.

## 7. Cómputo y entorno de trabajo

**Orden:** local → máquina del laboratorio → AWS bajo demanda.

| Dónde | Qué corre |
|---|---|
| Local | plan, reestructura del repositorio, bloques 1 y 2 del bronce (CPU) |
| Máquina del laboratorio (GPU) | bloques 3 y 4 del bronce, fine-tuning del paso 2, evaluaciones |
| AWS (EC2 con GPU o SageMaker, S3 como espejo de `datos/`) | solo cuando se cumple un disparador |

**Disparadores para pasar a AWS:** el modelo no cabe en la VRAM con batch de 8 y 512 tokens; un experimento supera 4 horas de pared; la GPU está ocupada por otros usuarios del laboratorio. Cuenta personal: usuario IAM acotado con MFA, alarma de presupuesto, instancias spot para experimentos interrumpibles, apagar al terminar.

**En la máquina del laboratorio:** usuario y carpeta propios; venv propio; el repositorio se clona por git, sin copias sueltas; `datos/` vive fuera del repositorio y con respaldo; `.env` sin commit; verificar `nvidia-smi` y versión de CUDA antes de instalar torch. SQLite es un solo escritor: el archivo `grn.db` se mueve entre entornos como snapshot, nunca se edita en dos lugares a la vez.

**Claude Code en la máquina del laboratorio:** aviso por escrito al Dr. de que se usa y de que el código y los fragmentos de archivo abiertos en sesión se envían a Anthropic; trabajo restringido a la carpeta propia y al repositorio; los datos de la base v2 y los párrafos etiquetados quedan fuera de toda sesión. Un `CLAUDE.md` en la raíz replica las reglas del steering de Kiro (capas, sin `print()` fuera de `cli.py`, credenciales en variables de entorno, español sin acentos en identificadores) y agrega: no leer `datos/`, `*.db` ni archivos fuera del repositorio. `.claude/settings.json`, versionado, refuerza lo anterior con reglas `deny` sobre `datos/`, `*.db` y `.env`. Sesión con la cuenta personal; sin credenciales en perfiles de shell compartidos.

**Documentación:** `docs/bitacora.md` con entradas fechadas por sesión de trabajo (qué se corrió, con qué versión, resultado, decisión). Cada experimento queda además como fila en `corridas`, así que la bitácora registra decisiones y la base registra hechos.

## 8. Próximos pasos

1. Ejecutar la regla de la sección 2 (opción A o B); crear `tag v0-extraccion` y rama `bronce`.
2. Agregar `grn_bronce/` con `db.py`, `texto.py` y el CLI mínimo; actualizar la estructura en `CLAUDE.md`.
3. Correr `fulltext` sobre el corpus actual y reportar cobertura de XML y PDF.
4. Construir el diccionario PAO1 desde Pseudomonas Genome DB.
5. Poblar `texto_unidades` sobre el corpus actual (bloque 1). Al llegar la query del Dr.: consulta canónica, `fulltext`, `corpus v1`, y re-ejecución del bloque 1 sobre el corpus congelado.
