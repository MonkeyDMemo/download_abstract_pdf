# Sintaxis con spaCy en el bronce: el plan, sus correcciones y lo medido

Este documento versiona el plan «scispaCy en el bronce» que el usuario escribió
el 27-sep-2026 (estaba suelto en la raíz como `plan-scispacy-bronce.md`), el
análisis de ese mismo día que lo dejó «no aprobable tal como está», y lo que se
implementó y midió el 8-oct-2026. Cierra el pendiente 9.8.

Cubre los puntos 30 (inversión de dirección) y 18 (disparador dominante) del
PLAN. El NER complementario (17/35) quedó diferido.

---

## 1. El plan original, en una página

- **Objetivo.** Usar el árbol de dependencias de spaCy, con el modelo
  biomédico `en_core_sci_md` de scispaCy, para orientar los pares (quién
  regula a quién) y elegir el disparador dominante de cada oración.
- **Restricciones que respetaba.** No re-segmentar (el corte de oración está
  congelado con 93 golden), método opcional con su propio `(metodo, version)`,
  terceros solo con aprobación y en un extra.
- **Fases.** 0 entorno; 1 `grn_bronce/sintaxis.py` como función pura; 2 tabla
  `sintaxis_candidatas`; 3 orquestación y CLI; 4 NER con
  `en_ner_bionlp13cg_md`; 5 evaluación definida antes de correr; 6 cierre.

## 2. Lo que el análisis del 27-sep corrigió

Seis bloqueantes, y cómo quedó cada uno el 8-oct, más un cambio de criterio:

| # | Bloqueante | Cómo quedó |
|---|---|---|
| 1 | La métrica «114 frente al oro de 190, ≥ 400» mezclaba poblaciones: los 114 son pares dirigidos de la corrida 1, con techo de 675 | El punto 18 se mide sobre los pares dirigidos de la corrida 4, con el mismo agregado, contra su techo; y con un **control léxico** solo estándar al lado (`grn_verificacion/evaluar.py`) |
| 2 | «12 pérdidas por diccionario» juntaba dos docenas distintas; un `gen_propuesto` sin locus no cuenta como cobertura | Diferido con el NER (fase 4) |
| 3 | El DDL rompía `borrar_corrida` (llave foránea sin `ON DELETE` hacia `texto_unidades`) | **Sin tabla por ahora**: la salida es un JSONL. La tabla futura no lleva llave foránea hacia las filas del bronce |
| 4 | `UNIQUE(candidata_id, corrida_id)` no admite una fila por par (hasta 56 pares ordenados por oración) | Una línea por oración y **par no ordenado**; la clave futura incluye las dos entidades |
| 5 | scispaCy 0.5.4 no instala en Python 3.12 | **No hizo falta el paquete scispacy**: spaCy 3.7.5 carga `en_core_sci_md` 0.5.4 solo |
| 6 | No existía `pyproject.toml` | Existe; el extra `[bronce-nlp]` quedó declarado el 8-oct |
| 7 | El criterio de dirección del plan («recupera ≥ 4/6 sin perder ninguno de los 22») contaba las líneas 44 y 50, que son proteína-proteína y siguen siendo `no` aunque se orienten | Cambiado en el plan aprobado el 8-oct, **antes de correr**: al menos 3 de los 4 recuperables (8, 11, 20 y 41) y ninguna de las 22 `si` rota (`ficha-invertidos-punto30.md`) |

Y los importantes:

- La prueba de humo con «P. aeruginosa» como un solo token no podía pasar; se
  redefinió: una sola oración por unidad, y toda mención alinea o queda
  `sin_alineacion` **sin excepción**.
- «LasR/RhlR» es un token con dos menciones: el `merge` daba E102. Se usa
  `spacy.util.filter_spans` antes de fusionar.
- «Sentencizador anulado» no aplicaba: en este modelo corta el parser. Se fija
  `is_sent_start` antes de parsear.
- `menciones` no tiene `es_tf`: se toma de `lexico.es_tf`.
- La muestra de 50 es de la corrida 1 y no tiene `candidata_id`: se une por
  texto normalizado y par.
- El punto 30 pedía revisar a mano los 6 invertidos **antes** de construir:
  `docs/ficha-invertidos-punto30.md`, escrita antes de mirar resultados.

## 3. El entorno (`.venv-nlp`)

spaCy 3.7 exige numpy < 2 y el `.venv` del proyecto tiene el numpy 2 de torch,
así que la sintaxis vive en su propio venv:

```bash
.venv/Scripts/python -m venv .venv-nlp
.venv-nlp/Scripts/python -m pip install "spacy==3.7.5" "numpy>=1.26,<2"
.venv-nlp/Scripts/python -m pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_md-0.5.4.tar.gz
.venv-nlp/Scripts/python -m pip install "weasel>=0.3,<0.4.2" "typer>=0.9,<0.10" "click>=8.0,<8.2"
.venv-nlp/Scripts/python -m pip uninstall -y typer-slim
.venv-nlp/Scripts/python -m grn_bronce.cli sintaxis --diagnostico
```

Las dos últimas líneas de instalación existen porque pip eligió un typer que ya
no instala click, y spaCy 3.7.5 importa click al cargar. Versiones que quedaron:
spaCy 3.7.5, numpy 1.26.4, thinc 8.2.5, typer 0.9.4, click 8.1.8, weasel 0.4.1,
`en_core_sci_md` 0.5.4. En una máquina sin PyPI se instala desde los `.whl` y el
`.tar.gz` guardados en `GRN_DATOS/wheels/` con `pip install --no-index`.

Lo que el modelo hace distinto de lo esperado, y las reglas toman en cuenta:
no hay etiqueta `agent` (el «by» de la pasiva llega como `nmod` con `case`),
las relativas son `acl:relcl`, y el tokenizador deja `LasR/RhlR` y
`LasR-dependent` como un solo token.

## 4. Lo implementado

`grn_bronce/sintaxis.py` es el único módulo que importa spaCy, dentro de sus
funciones; se corre con `python -m grn_bronce.cli sintaxis` desde `.venv-nlp`,
y el flujo (`flujo.py`) lo invoca por subproceso. Sin el entorno, el paso queda
omitido.

- **Entrada:** el CSV de candidatas del bronce, sin re-segmentar.
- **Salida:** una línea por oración y par no ordenado de entidades del
  diccionario, **sea o no TF**, con `regulador_sintactico`, `voz`, `negada`,
  `lema_dominante`, `disparador_dominante`, `signo_dominante` y el `camino`.
  Es lo que permite orientar reguladores que no son TF, que el BioBERT no ve.
- **Reglas v1**, congeladas antes de mirar salidas reales y escritas solo con
  oraciones sintéticas: activa (`nsubj` → regulador), pasiva («by» → regulador),
  nominal («expression of X by Y», «Y-dependent/-mediated»), fenotipo de
  mutante sin orientar, negación, más relativas, verbos coordinados y `xcomp`
  que heredan sujeto, preposiciones de contexto, verbos inversos (require,
  depend…), predicados copulativos y «effect of Y on X».
- **Pruebas:** `grn_bronce/test_sintaxis.py`, 40, sintéticas; con el `.venv`
  se saltan las 5 que necesitan spaCy.

## 5. Lo medido sobre la corrida 4 (8-oct-2026)

Sobre las 29 659 oraciones candidatas, en CPU:

| medida | valor |
|---|---|
| tiempo, con la carga del modelo | 96 s (96.9 s el paso completo del flujo) |
| líneas (oración × par) | 76 453 |
| oraciones que el parser partió en más de un árbol | 0 |
| pares orientados | 10 299 (13.5 %), en 6 917 oraciones |
| de esos, con regulador que no es TF | 3 853 (37 %) |
| negados | 1 211 |
| `sin_alineacion` | 8 485 pares, por 4 874 de 93 154 menciones (5.2 %) que comparten token con otra (barra, guion) |

`voz`: activa 6 486 · pasiva 1 333 · nominal 2 480 · mutante 4 023 ·
indeterminada 53 646. El 70 % indeterminado refleja reglas conservadoras a
propósito en oraciones con varias entidades.

**Esto son mediciones, no calidad.** La calidad se mide contra la ficha de los
6 invertidos y las 50 juzgadas (`evaluar.py`, métricas D1 y D2), declaradas
desarrollo, no prueba. Lo que decide si la sintaxis puede reorientar el bronce
es el criterio fijado antes de correr (fila 7 de la sección 2): al menos 3 de
los 4 recuperables y ninguna de las 22 relaciones correctas rota.

## 6. Lo que sigue

- **v2 de la alineación:** partir en los límites de mención los tokens que
  comparten dos menciones («LasR/RhlR») antes de fusionar. Cambia la salida, así
  que va con `VERSION = "2"`. *(21-oct: partir el token se descarta; la v2 que
  sí se hace, su porqué y su criterio están en la §7.)*
- **Tabla propia** con la clave `(corrida, unidad, entidad_a, entidad_b)` y sin
  llave foránea hacia las filas del bronce, cuando se confirme su DDL.
- **NER (fase 4)**, después del mapeo PA14 → PAO1 (punto 35) y con la métrica
  corregida.
- **Muestra nueva y ciega** para probar las reglas: las 50 ya se miraron.

## 7. v2 de la alineación: criterio fijado antes de correr (21-oct-2026)

Esta sección se escribió y entró a git **antes** de cambiar el código y de
correr la v2 sobre la corrida 4. Lo que salga se compara contra esto, y esto no
se toca después: solo se llena el «Resultado» de abajo.

### Qué cambia

En la v1, cuando el tokenizador deja dos menciones en un solo token
(«LasR/RhlR», «FleQ-FleN»), las dos se expanden al mismo tramo, `filter_spans`
conserva uno y la otra mención se queda sin token: todos sus pares salen
`sin_alineacion`. Son los 8 485 pares de la §5, por 4 874 menciones.

La v2 no toca el `Doc`. `preparar_doc` alinea, filtra y fusiona igual que en la
v1; lo nuevo es que la mención que pierde en `filter_spans` y cuyo tramo cabe
**entero** dentro de un tramo conservado se alinea al token de ese tramo
(`contenedores`, calculado con offsets de caracteres antes de fusionar). Un
traslape parcial no se asigna y sigue `sin_alineacion`.

Si las dos entidades de un par caen en el mismo token, el par sale con una voz
nueva, `mismo_token`, sin orientar: entre las dos no hay camino que leer. Con
una tercera entidad, cada una ocupa el token compartido y se orienta como la
otra. `VERSION` pasa a `"2"`; las reglas de orientación siguen siendo las v1 y
`CAMPOS` no cambia.

### Por qué no se parte el token

La §6 proponía partirlo en los límites de mención. Se descarta por dos razones:

1. **Partirlo cambia los tokens que ve el parser en toda la oración.** El árbol
   de los pares que la v1 ya alinea se movería sin que nadie lo midiera, y lo
   que se ganara en los pares recuperados se pagaría con cambios sin revisar en
   los demás. Sin partir, el `Doc` es el mismo y esos pares salen idénticos
   (C3).
2. **Fabrica relaciones.** En «PqsE/RhlR-dependent», partir le dejaría el sufijo
   solo a RhlR (`RhlR-dependent`), y la regla del sufijo propondría RhlR → PqsE,
   una relación que el texto no dice. Con el token entero, las dos menciones
   llevan el sufijo, como en el texto, y entre ellas no se orienta nada.

### Criterios

| # | Criterio | Dónde se lee |
|---|---|---|
| C1 | Pares `sin_alineacion` de 8 485 a **849 o menos**, y menciones sin alinear de 4 874 a **487 o menos** | `sin_alineacion_despues` de la comparación; `menciones_sin_alineacion` en el resumen del paso, en `flujo.log` |
| C2 | Ninguna de las 22 relaciones `si` de la muestra de 50 se rompe: **D2 sigue en 0/22** | `D2_si_que_se_romperian` de `evaluacion.json` |
| C3 | **Cero** líneas cambiadas fuera de `sin_alineacion`: el `Doc` es idéntico al de la v1 | `cambiadas_fuera_de_sin_alineacion` de la comparación |
| C4 | Las mismas **76 453** claves `(pmid, fuente_texto, num_oracion, a, b)` | `claves_antes`, `claves_despues`, `claves_solo_antes` y `claves_solo_despues` de la comparación |

La comparación la hace `sintaxis --comparar`, que no necesita spaCy:

```bash
python -m grn_bronce.cli sintaxis --comparar RESPALDO_V1/sintaxis.jsonl \
    --salida salidas/flujo/corrida4_run22/sintaxis.jsonl --json COMPARACION.json
```

Una línea «cambiada» es una cuya versión v1 no era `sin_alineacion` y cuya
versión v2 difiere en algún campo distinto de `version`.

### Lo que se reporta sin decidir

- **D1**, que se espera en 1 de 4, sin cambio: las líneas 8, 11, 20 y 41 no
  fallan por alineación (`ficha-invertidos-punto30.md`). La 50 pasa de
  `sin_alineacion` a `mismo_token` y sigue sin orientar.
- Cuántos pares recuperados quedan orientados, y con qué voz (`recuperadas`,
  `recuperadas_orientadas` y `recuperadas_por_voz` de la comparación).
- El punto 18 (`disparador_dominante_punto_18` de `evaluacion.json`): los pares
  recuperados traen lema, disparador y signo donde antes no traían nada.

### La regla

Antes de correr la v2 se respalda el `sintaxis.jsonl` de la v1 y se anota su
sha256. Si C1, C2, C3 y C4 se cumplen, la v2 queda en el flujo. Si alguno no se
cumple, se revierte el merge de `sintaxis-v2`, se vuelve a correr el paso y el
sha256 de `sintaxis.jsonl` tiene que volver a ser el del respaldo v1.

### Resultado

Corrida del 21-oct-2026 sobre la corrida 4, con `flujo.py --corrida 4`. La v1
de la comparación es la salida de la línea base de esa misma mañana, que tiene
la misma huella que la del 20-oct (`9bbb34c9b5c6115f`). La comparación se hizo
con `grn_bronce.cli sintaxis --comparar`, y su JSON quedó en
`salidas/respaldos/corrida4_run22_v1_20261021/comparacion_v1_v2.json`.

| criterio | umbral | v1 | v2 | |
|---|---|---:|---:|---|
| C1, pares `sin_alineacion` | ≤ 849 | 8 485 | 0 | cumple |
| C1, menciones sin alinear | ≤ 487 | 4 874 | 0 | cumple |
| C2, relaciones `si` que se romperían (D2) | 0 de 22 | 0 | 0 | cumple |
| C3, líneas cambiadas fuera de `sin_alineacion` | 0 | — | 0 | cumple |
| C4, claves (pmid, fuente, oración, a, b) | 76 453 iguales | 76 453 | 76 453, sin repetidas | cumple |

**La v2 queda en el flujo.** Lo que se reporta sin decidir:

- **Las 8 485 líneas que antes no se alineaban:**
  - 4 646 salen `mismo_token`, porque son el par de las dos menciones de un mismo token;
  - 3 041 salen `indeterminada`;
  - 600 quedan orientadas (382 activa, 90 pasiva, 128 nominal);
  - 198 son `mutante`.
  Las 4 874 menciones que perdían en `filter_spans` se alinean ahora a su contenedor.
- **D1 sigue en 1 de 4** (la línea 20), como se esperaba: las líneas 8, 11 y 41 no fallaban por alineación.
- **El punto 18 no se mueve:** la sintaxis sigue con 166 pares de signo único y 47 contradictorios, sobre 1 186 dirigidos.
- **El 44 % no cambia:** `evaluacion.json` da lo mismo que con la v1 en todas las métricas D y de precisión.
- **verificar-corrida sale con código 0 antes y después.** Una tercera corrida del flujo sale toda «saltado».

---

## Anexo: el plan original, tal como se escribió el 27-sep-2026

Se conserva sin cambios; las correcciones están en las secciones 2 a 6.

### Plan: scispaCy en el bronce (paso 1)

Fecha: 2026-09-27. Estado: propuesta, sin cambios en el repositorio.

Cubre los puntos 30 (inversión de dirección), 18 (disparador dominante) y 17/35 (huecos del diccionario, PA14) de `PLAN.md`.

Tres restricciones del repositorio que el plan respeta:
- El corte de oración está congelado (93 golden). scispaCy consume `texto_unidades.texto` tal cual y nunca re-segmenta.
- Todo tercero en `grn_bronce/` requiere aprobación previa y extra en `pyproject.toml`. scispaCy es método opcional: sin él, el bronce corre igual.
- Cada método nuevo es una corrida propia con su par `(metodo, version)`. Nada se mezcla con la corrida 1.

#### Fase 0. Aprobación y entorno

1. Aprobar `spacy`, `scispacy`, `en_core_sci_md` (tagger, parser, lematizador; GENIA + OntoNotes) y `en_ner_bionlp13cg_md` (NER, clase `GENE_OR_GENE_PRODUCT`).
2. Extra separado `[bronce-nlp]` en `pyproject.toml`, distinto de `[bronce]`.
3. Modelos por URL con versión fijada; `.whl` en `GRN_DATOS/wheels/` e instalación con `pip install --no-index` en la máquina sin PyPI.
4. Prueba de humo en Linux y Windows: `mexEF-oprN`, `PA14_23420` y `P. aeruginosa` deben quedar como un token cada uno.
5. Verificar scispaCy 0.5.x ↔ spaCy 3.7.x ↔ Python 3.12.

Salida: import confinado a un módulo; el resto del bronce corre sin el extra.

#### Fase 1. `grn_bronce/sintaxis.py`, función pura

Único módulo que importa spaCy; import dentro de la función (patrón de `etapa2/clasificar.py`). Sin base, sin print.

Entrada: `texto`, menciones `(offset_ini, offset_fin, tipo, id_normalizado, es_tf)`, disparadores con offsets.

Procesamiento:
1. `nlp(texto)` con sentencizador anulado.
2. `doc.char_span(ini, fin, alignment_mode="expand")` por mención y `retokenize().merge()`: cada entidad es un nodo del árbol.
3. Por par ordenado de genes: camino más corto, verbo o nominalización gobernante, lema.
4. Orientación: sujeto activo (`nsubj`) → regulador; agente pasivo (`agent`/`by`) → regulador; nominalización "expression of X by Y"; patrón de mutante ("increased in the mexT mutant") marcado `mutante`, sin orientar.

Salida por par: `regulador_sintactico`, `blanco_sintactico`, `disparador_dominante`, `lema_dominante`, `voz` (`activa`, `pasiva`, `nominal`, `mutante`, `sin_camino`, `sin_alineacion`), `camino`, `longitud_camino`.

Pruebas `grn_bronce/test_sintaxis.py` con oraciones sintéticas (nunca del laboratorio): activa, pasiva, nominalización, mutante, coordinación, relativa, tres entidades. `skipUnless` si el modelo falta.

#### Fase 2. DDL propuesto (pendiente de confirmación)

```sql
CREATE TABLE IF NOT EXISTS sintaxis_candidatas (
    id                   INTEGER PRIMARY KEY,
    candidata_id         INTEGER NOT NULL REFERENCES oraciones_candidatas(id),
    unidad_id            INTEGER NOT NULL REFERENCES texto_unidades(id),
    regulador_sintactico TEXT,
    blanco_sintactico    TEXT,
    disparador_dominante TEXT,
    lema_dominante       TEXT,
    voz                  TEXT,
    camino               TEXT,
    longitud_camino      INTEGER,
    concuerda_baseline   INTEGER,
    modelo               TEXT NOT NULL,
    metodo               TEXT NOT NULL,
    corrida_id           INTEGER NOT NULL REFERENCES corridas(id),
    UNIQUE (candidata_id, corrida_id)
);
CREATE INDEX IF NOT EXISTS ix_sint_corrida ON sintaxis_candidatas(corrida_id);
```

`concuerda_baseline` = 1 si coincide con `regulador_candidato`/`blanco_candidato`. `modelo` guarda nombre y versión.

SQL solo en `grn_bronce/db.py`: `guardar_sintaxis()`, `candidatas_pendientes_sintaxis()` con `(metodo, version)` en el `ON` del `LEFT JOIN`, `SQL_CANDIDATAS` con `LEFT JOIN sintaxis_candidatas`.

#### Fase 3. Orquestación y CLI

- `grn_bronce/orientar.py`: `orientar(con, corrida_id, corrida_base, log)`. Lotes de 500 con commit. Reanudable.
- `METODO = "scispacy-dependencias"`, `VERSION = "1"`, `paso = "1"`, `parametros = {modelo, version_modelo, corrida_base}`.
- `python -m grn_bronce.cli sintaxis --corrida-base 4 [--limite N]`.
- CPU; ~30 000 candidatas, del orden de 10 a 20 min. Se mide y se anota.

#### Fase 4. NER complementario (huecos del diccionario)

- `grn_bronce/ner.py` con `en_ner_bionlp13cg_md`; devuelve spans `GENE_OR_GENE_PRODUCT` que no solapan con menciones del diccionario.
- Persistir en `menciones` con `tipo = 'gen_propuesto'`, `metodo = 'scispacy-ner'`, corrida propia, `id_normalizado` NULL. Documentar el octavo tipo en `CLAUDE.md`.
- Reporte `salidas/gen_propuesto_<fecha>.csv`: superficie, n_menciones, n_documentos, sección predominante, tres ejemplos.
- Filtros: regex `PA\d{4}` y `PA14_\d{5}` (PA14 en columna aparte para ortología); `palabras_comunes.txt`; cruce contra `genes_pao1.tsv` para medir pérdidas por mayúsculas o guion. Sospechar de vocabulario de E. coli.
- Ámbito: unidades con menos de dos genes de diccionario.

Decisión abierta: `gen_propuesto` como tipo nuevo frente a tabla `menciones_ner`. Propuesta: tipo nuevo por simplicidad.

#### Fase 5. Evaluación (definida antes de correr)

| Pregunta | Referencia | Métrica | Umbral |
|---|---|---|---|
| ¿Corrige la inversión? | Muestra de 50 (corrida 1) | Dirección en los 22 correctos y los 6 invertidos | Recupera ≥ 4/6 sin perder ninguno de los 22 |
| ¿Sube el signo utilizable? | Oro propio, 190 | Pares con `lema_dominante` único vs 114 | ≥ 400 |
| ¿El NER cierra huecos? | Oro propio, 12 pérdidas por diccionario | Cuántas salen como `gen_propuesto` | ≥ 6 |
| ¿Ruido del NER? | 100 `gen_propuesto` al azar, juicio manual | Precisión | Se reporta; decide el asesor |

Scripts en `etapa2/evaluacion/`, biblioteca estándar, leen por `sqlite3`. `test_contaminacion.py` sigue vigente.

#### Fase 6. Cierre

- Cumple: `exportar.py` añade columnas sintácticas; `regulador_candidato` conserva el baseline. Decidir si el paso 2 recibe `lema_dominante`.
- No cumple: tabla conservada, método documentado como descartado en `docs/decisiones.md`.
- Siempre: `docs/bitacora.md`, `docs/hallazgos.md`, `CLAUDE.md` (extra, tabla, tipo), `PLAN.md` puntos 30, 18, 17.

#### Riesgos

- Portabilidad: método aparte; baseline sigue canónico.
- Offsets: `char_span` None → `voz = 'sin_alineacion'`, contado.
- Oraciones largas: `longitud_camino` permite filtrar.
- Deriva de modelo: cambio de modelo sube `VERSION`.
- Falsa mejora: lo que importa son los 6 invertidos y cuántos correctos rompe.

#### Orden

Fase 0 → 1 → confirmación DDL → 2 y 3 → corrida → 5 (dirección) → 4 → 5 (NER) → 6. Rama `sintaxis-bronce`.
