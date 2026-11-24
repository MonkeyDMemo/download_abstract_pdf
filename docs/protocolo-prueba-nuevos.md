# Protocolo: la prueba con abstracts nuevos

Registrado el 23-oct-2026, **antes de descargar nada**. Mide el pipeline
congelado sobre artículos que no existían cuando se armó el corpus. Cualquier
cambio posterior va al final, como enmienda con fecha, y dice si es anterior o
posterior a ver alguna cifra.

## Qué se descarga

- **Consultas.** Las tres de la raíz, registradas con nombre propio para no
  mezclarlas con las de agosto:
  - `nuevos_pa_regulacion`, de `pa_regulacion.txt`;
  - `nuevos_pa_reguladores`, de `pa_reguladores.txt`;
  - `nuevos_pa_evidencia_union`, de `pa_evidencia_union.txt`.
- **Fechas.** Desde el 2026/08/19, el día siguiente a la última descarga del
  corpus de la corrida 4. Esa descarga fue el 18-ago, según `cli.py log`, y el
  corpus `v0-agosto` se congeló el 4-sep.
  - La fecha que cuenta es la de **alta en PubMed** (`--tipo-fecha edat`), no
    la de publicación. Con la de publicación se perderían los registros dados
    de alta después con fecha anterior.
  - El tope es el día en que se descarga, y queda en la bitácora.
- **Entra todo lo que salga.** No se filtra a mano.
- **Lo que hay que saber de las consultas:**
  - `v0-agosto` salió casi entero de `pa_regulacion` (2 263 de 2 361
    documentos). `pa_reguladores` y `pa_evidencia_union` nunca habían corrido.
  - Por eso **todo se reporta por consulta**: `nuevos_pa_regulacion` es la
    misma distribución que el corpus, y las otras dos son poblaciones nuevas.
  - **`pa_reguladores.txt` favorece reguladores conocidos.** Nombra 18
    reguladores (lasR, rhlR, pqsR…), así que su precisión y su recall no
    representan a un regulador cualquiera.
- **Sin texto completo.** Solo abstracts: lo nuevo casi nunca tiene XML de PMC
  todavía, y mezclar fuentes cambiaría la población.

## Antes de procesar

1. **Congelamiento.** Una etiqueta de git y `docs/congelado-prueba-nuevos.json`
   con las sha256 de:
   - el modelo de *E. coli* (las huellas de `predicciones_meta.json`);
   - los umbrales;
   - `genes_pao1.tsv` y el catálogo de operones del paso 1;
   - el prompt de Ouroboros, si entra.

   Nada de eso cambia hasta reportar.
2. **Contaminación.** `grn_verificacion.cli verificar-contaminacion` tiene
   que dar 0 cruces, por PMID y por DOI. Corre en dos lugares, porque cada uno
   tiene lo suyo:
   - **En la laptop**, con `--consulta <cada consulta nueva>`, contra:
     - el corpus `v0-agosto`;
     - las reservas;
     - las tandas 1 y 2 (`--muestra`);
     - las 50 juzgadas.
   - **En el servidor**, con `--lista` y `--sin-corpus`, contra:
     - la partición de entrenamiento de las curadas v1 y v2 (`--particion`);
     - la base curada (`--base`).

     La lista son los PMIDs nuevos, públicos, y la sube el usuario.

   La calibración es sintética y no aplica. Un artículo que cruce sale de la
   prueba, y se cuenta y se declara.
3. **Corpus nuevo.** `corpus crear --nombre nuevos-<fecha>`, congelado, y el
   pipeline con las versiones del manifiesto: bronce, pares, BioBERT, red y
   capa.

## Qué se mide

- **Precisión con dirección y retención.**
  - **La muestra:** ciega, de 200 oraciones al azar de las candidatas con
    regulador y blanco del corpus nuevo. Así quedan mezcladas las que la red
    retiene y las que descarta, y quien anota no puede saber cuáles son.
  - **Quién y cómo:** la anota el experto en la página, con la rúbrica v1 y
    sus enmiendas.
  - **Qué se reporta:** las cifras salen de `precision-ciega`, igual que en
    las tandas 1 y 2: el bronce, la red sobre lo que retiene y la retención de
    las verdaderas.
- **Recall.** El experto anota de forma exhaustiva 25 abstracts al azar: todas
  las relaciones de regulación que afirman, con dirección y signo. Contra eso
  se mide qué fracción tiene su par en una candidata del bronce y qué fracción
  es arista de la red.
- **Intervalos.** Bootstrap por artículo, porque las oraciones de un mismo
  artículo no son independientes.
- **Líneas base.** Para la precisión, el bronce sin filtro. Para el signo,
  «siempre +» sobre la misma base, con la abstención como error.
- **Reporte por consulta**, y el total.

## Qué no se hace

- No se ajusta ninguna regla, umbral ni prompt con lo que salga.
- No se repite la descarga para «mejorar» la muestra.
- No se excluyen artículos después de ver sus juicios.

## Enmienda 1 (23-oct-2026): el congelamiento, hecho

Es anterior a descargar nada.

- **Lo congelado:** `docs/congelado-prueba-nuevos.json` y la etiqueta de git
  `congelado-prueba-nuevos`. Llevan:
  - las huellas del modelo de *E. coli*;
  - los umbrales y parámetros de `red.py` (0.65 / 0.70 / 0.60, mayoría 0.66);
  - la sha256 de la red de la corrida 4;
  - las de los recursos del bronce: el diccionario, el catálogo y la base de
    operones, los vocabularios y `secciones.tsv`.
- **Lo que se mide es la red oficial.** Las reglas de signo siguen apagadas;
  sus redes se miden en la tanda 2.
- **Ouroboros no entra, por omisión.** Es exploratorio, y su prompt todavía
  se ajusta con la calibración. Si entra, va con otra enmienda y la huella del
  prompt congelado.

## Enmienda 2 (4-nov-2026): Ouroboros entra, y el congelamiento comprobado

Es anterior a descargar nada.
- **El congelamiento, comprobado hoy.** Los 10 recursos del bronce, la red de
  la corrida 4 y los 5 archivos del modelo coinciden con
  `docs/congelado-prueba-nuevos.json`. Desde la etiqueta no cambió el código
  del pipeline (ETL, bronce, operones, red, puente, `etapa2/`, `flujo.py`);
  solo el de evaluación (`precision_ciega` y `concordancia`: tiempos y acuerdo
  entre humanos).
- **Ouroboros entra, exploratorio,** con el prompt congelado en la enmienda 3
  de `protocolo-tanda2.md` (`anotador_v0.md`, sha256 `0871a839…`; huellas de
  corrida `2f80f09a…` sin herramientas y `c90cf9f2…` con `buscar_locus`):
  - sobre la muestra ciega de 200 del corpus nuevo, con las tres
    configuraciones, **antes** de que el experto la anote. Se mide con
    `concordancia`, igual que en las tandas;
  - para mostrar el flujo integrado, la principal sobre todas las candidatas
    del corpus nuevo. Es descriptivo: no da ninguna cifra de calidad.
- **Ouroboros marca, no filtra:** no cambia la red oficial ni sus cifras.
- **El tope de la descarga** es hoy, 2026/11/04.
- **Calendario.** El experto anota la muestra del corpus nuevo después de
  terminar la tanda 2, y su cifra va al informe. A la revisión del 6-nov van
  solo conteos descriptivos y la contaminación.

## Enmienda 3 (24-nov-2026): los artículos nuevos, también con texto completo

Es anterior a procesar ningún PDF de los artículos nuevos. Los PDF ya estaban
bajados y de ellos solo se había mirado si son el artículo correcto.

- **Por qué.** El asesor pidió (16-nov) el embudo y la comparación de resumen
  contra texto completo también para los artículos nuevos. La limitación «sin
  texto completo» de este protocolo era práctica: lo nuevo casi no tiene XML
  de PMC. Con una llave de OpenAlex hay copia en PDF de 27 de los 40.
- **Qué no cambia.** La corrida 16 (solo resúmenes) sigue siendo la prueba de
  este protocolo y sus cifras no se tocan. El corpus `nuevos-20261104` es el
  mismo (40 artículos, misma huella). No se ajusta ninguna regla, umbral ni
  prompt.
- **Qué se agrega.** Una corrida aparte del bronce con `--con-pdf` sobre el
  mismo corpus, el flujo con el modelo congelado (`modelo_limpio_run22`) y el
  jurado v1 (enmienda 6 de `protocolo-tanda2.md`) con una oración por arista.
- **Qué PDF entran.** La regla se fijó antes de procesar y después de ver solo
  la coincidencia de títulos: firma `%PDF`; al menos 5,000 caracteres de texto
  convertido; y el título del registro de PubMed presente (≥ 60 % de sus
  palabras en los primeros 6,000 caracteres, o ≥ 80 % en todo el texto). La
  cumplen los 27. De ellos, 22 son la versión publicada y 5 la versión enviada
  a la revista (preprint): entran, y se reporta cuántas aristas dependen solo
  de esos 5.
- **Qué se reporta.** Es descriptivo y no da ninguna cifra de calidad, porque
  no hay juicio del experto sobre este corpus:
  - el embudo de artículos (descargados, con resumen, con PDF);
  - el embudo de la evidencia por origen de la oración (`cli fuentes`);
  - las aristas por dónde está su evidencia y el nivel del jurado por clase;
  - sobre los mismos 40 artículos, la red de solo resúmenes contra la red con
    PDF.
- **La muestra del experto no cambia.** Si llega a anotarse, se sortea de la
  corrida 16 como estaba escrito: mezclar fuentes ahí sí cambiaría la
  población.
- **Costo.** El jurado sobre las aristas de esta corrida, con tope de US$2 en
  Bedrock.
