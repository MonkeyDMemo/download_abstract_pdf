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
