# Pendientes al 28 de septiembre de 2026

Todo lo que sigue abierto en el proyecto, junto en un solo lugar. Sale de leer
`PLAN.md`, la bitácora completa, `CLAUDE.md`, `decisiones.md`, `hallazgos.md`,
`catalogo-operones.md`, la documentación de `etapa2/`, las guías de máquina,
los comentarios del código y el steering de Kiro, y de comprobar cada punto
contra el código y los documentos más nuevos (`main` en `d05b9c3`). Lo que una
entrada posterior ya cerró no está aquí.

Es una foto con fecha, no un segundo tablero. El estado de cada punto se lleva
en `PLAN.md`: cuando algo se cierre, se marca allá y en la bitácora. Los
números entre corchetes, como **[18]**, son filas de la sección 3 del PLAN.

**Lo que cambió el 23-oct-2026** (detalle en la bitácora de ese día):

- **Cerrados:**
  - 7.2 [12] y [14]: el contraste corrió en el servidor. El denominador
    versionado es 2 077 (conciliado con 2 003), la regla b) con XML da 30.2 %
    y la red dirigida 41.2 %. Hay 7 849 candidatas nuevas.
  - 7.3 [33]: el 44 % con los tres modelos (PLAN §2.3).
  - 7.6: la tanda 1 de la muestra ciega está anotada (PLAN §2.5).
- **Avanzados:**
  - 2.3 [30]: 39 de 144 inversiones en la tanda 1 (27.1 %). Es la pérdida
    más grande; las reglas se proponen con la tanda 1 y se miden en la 2.
  - 2.1 [18]: el voto léxico y el voto por artículo entran como parámetros
    apagados de `consolidar` (fase 3). Las cuatro redes ya están armadas, con
    sus huellas en `protocolo-tanda2.md`, y se miden en la tanda 2.
- **Nuevos:**
  - sortear y anotar la tanda 2 (de prueba), en la página, con la calibración 2
    antes;
  - las mediciones del servidor:
    - **ya corrieron** (fase 2): «siempre activa» sobre las 366 y las 605, el
      techo de la regla a), la conciliación y el contraste de la red
      recomendada. Falta confirmarlas con `main`;
    - **falta** rehacer las tablas con el código revisado, y la precisión de
      v1 y v2 sin su entrenamiento (`servidor-cierre.md` §4 a §6);
  - ~~recalcular la línea base «siempre +» del signo sobre los mismos ítems~~:
    **hecho** en la fase 2. En la tanda 1, 42/60 contra 41/60; en las 50,
    11/15 contra 11/15;
  - Ouroboros v0, exploratorio y fuera del flujo;
  - `docs/protocolo-tanda2.md` antes de evaluar la tanda 2;
  - la prueba con abstracts nuevos: el código (`run --tipo-fecha`,
    `verificar-contaminacion`) y el protocolo ya están; falta el congelamiento;
  - preguntar al asesor dos permisos: Bedrock (por omisión no) y publicar las
    oraciones con los juicios (por omisión no).

**Lo que cambió el 21 y el 22-oct-2026** (detalle en la bitácora de esos días):

- **Cerrados:**
  - la alineación de menciones de la sintaxis (nuevo del 8-oct): con la v2,
    los pares `sin_alineacion` bajan de 8 485 a 0 (`plan-sintaxis-bronce.md`
    §7);
  - 7.1, la parte de `grn_red/`: se abrió el 21-oct para el paquete de la red
    (`nodos.tsv`, `red.graphml` y `manifiesto.json`). Las reglas de
    consolidación siguen fuera hasta que las revise el asesor.
- **Avanzados:**
  - 1.1: la pregunta de la decisión 3 se reescribió (`operones-asesor.md` §8)
    y se hace en persona el viernes 23;
  - 2.3 [30]: con la v2 se orientan 600 de los pares que no se alineaban,
    pero D1 sigue en 1 de 4 y el criterio sigue sin cumplirse;
  - 7.2 [11] → [12] → [14]: `cli contraste` versiona el cruce, mide el recall
    de la red (7.16) y escribe las candidatas nuevas solo en la carpeta
    confidencial. Está probado con bases sintéticas; falta correrlo contra la
    base real, y lo corre el usuario (`contraste-curada.md`);
  - 7.6: la guía es `rubrica-anotacion.md`, y `cli muestra` sortea la muestra
    ciega. El sorteo espera a que el asesor valide la rúbrica.
- **Nuevos:**
  - GO en `nodos.tsv`: hoy la función es el producto de RefSeq, porque bajar
    GO de UniProt es red;
  - `muestra.py` usa dos funciones privadas de `entrenamiento.py`
    (`_reservada` y `_pmid_valido`): hacerlas públicas al tocar ese archivo.
- **Cerrado también:** 4.3, la tabla del release 22.1 de PGD, que mandó el
  curador. No cambia la base del paso 1.
- **Encontrado y arreglado:** la fila del resumen del bronce decía «con
  regulador y blanco» y contaba solo el regulador: 8 339, cuando con los dos
  son 5 833. La tesis v1 lo citó así; ya está corregida.

**Lo que cambió el 8-oct-2026** (detalle en la bitácora de ese día):

- **Cerrados:**
  - 3.2 [36].
  - 3.3 [37], la parte de código; falta la guía de traspaso.
  - 7.1: se abrió `grn_verificacion/`, y `grn_red/` sigue cerrado.
  - 9.4: el steering de Kiro quedó alineado (PGD es vía cerrada; el encolado
    lo resolvió `trabajos.Gestor`).
  - 9.8: el análisis de scispaCy quedó en `plan-sintaxis-bronce.md`.
- **Avanzados:**
  - 2.1 [18]: se midieron tres reglas de signo. Falta medir su acierto contra
    signos juzgados y elegir una.
  - 2.3 [30]: la sintaxis orienta 1 de 4 y no cumple el criterio.
  - 6.5: el tablero y el CLI del paso 0 ya siguen `GRN_DATOS`.
  - 7.3 [33]: el bronce está conectado al BioBERT y el 44 % se recalculó.
    El BioBERT entrenado con la base curada existe en dos versiones (v1, con
    pesos de clase, 16-oct; v2, sin pesos, 21-oct). Ninguna lee el signo en
    el flujo, y el de *E. coli* sigue siendo el del flujo (bitácora del 20 y
    21-oct). Falta el 44 % con los tres.
  - 9.2: se quitó la frase de «panorama»; queda la «sección 7» que CLAUDE.md
    cita y el PLAN no tiene.
  - 9.3: `menciones.tipo` y la descripción de la suite.
  - 9.5: el README da la cifra de pruebas al día.
- **Nuevos:**
  - el entrenamiento con la base curada, en el servidor
    (`entrenamiento-curada.md`): la v1 (16-oct) y la v2 sin pesos de clase
    (21-oct), con protocolo pre-registrado y su enmienda 1
    (`resultados-curada-v1.md`, `resultados-curada-v2.md`). Las dos superan
    a la línea base de memorización y **ninguna cumple el criterio del
    signo**. Abierto:
    - el 44 % con la v1, la v2 y *E. coli*: falta subir la carpeta
      `salidas/flujo/corrida4_run22` de la laptop;
    - si se sigue con el signo: un umbral por clase calibrado en dev, o
      etiquetas de signo juzgadas a mano;
    - el aviso al asesor con esta conclusión;
    - `flujo.py --modelo` da la misma carpeta a todos los checkpoints
      `run_22_…` de `reentrenar`; hoy se prueban a mano en carpetas propias
      (`entrenamiento-curada.md`, paso 6);
  - la alineación de menciones de la sintaxis: 11 % de los pares;
  - la regla «X-dependent», que orienta al revés;
  - el DDL de las tablas de validación y de sintaxis, que no está escrito;
  - mover `rutas` a `grn_comun` (4.8) pesa más ahora: la importan también el
    CLI del paso 0 y el tablero.

**Lo que cambió el 20-oct-2026** (detalle en la bitácora de ese día). Se
cerró todo lo de operones que no depende del asesor:
- **Cerrados:** 3.14, 4.1, 4.2, 4.4 a 4.8 y 4.10 a 4.19. El 4.17 se cerró
  medido y sin cambio de código.
- **Avanzado:** 4.3, con el borrador del correo al curador de PGD listo; lo
  manda el usuario.
- **Encontrado y arreglado:**
  - la capa contaba como «blanco que es operón» a IHF, PrrF y PrrH, que no
    tienen locus en el diccionario: IHF es un complejo, y PrrF y PrrH son ARN
    pequeños;
  - la revisión independiente de la rama encontró que `foto_sana` y
    `reparsear` no miraban la foto vigente, y que el aviso del paso
    `operones` salía una sola vez. Los dos quedaron arreglados con sus
    pruebas; el detalle está en `guia-operones.md` §12.
- **Sigue igual:** lo de la sección 1, que es del asesor.

**Lo que cambió el 16-oct-2026** (detalle en la bitácora de ese día). Los
operones quedaron documentados en dos documentos nuevos: `operones-asesor.md`,
para el asesor, y `guia-operones.md`, para quien los mantenga.

- **Cerrados:**
  - 1.11: el PLAN tiene la reunión del 25-sep en su §1.4.
  - 4.9: las dos guías de máquina dicen cómo regenerar `operones_base.tsv`, y
    `guia-operones.md` §8 da las tres vías.
  - 9.9: la historia del 18 al 24-sep quedó reconstruida de los commits, en
    `guia-operones.md` §0.
- **Avanzados:**
  - 1.1: el asesor respondió de palabra; falta la confirmación por escrito, y
    la pregunta está lista.
  - 1.2: el comentario de `curar.py` ya cita la regex con `\d+`.
  - 1.10: las correcciones están escritas; falta mandarlas.
  - 9.1: el §1 del PLAN ya tiene la reunión del 25-sep, y la fila 34 ya no
    dice «completar».
  - 9.3: `CLAUDE.md` ya lista las cinco tablas de `grn_operones`.
- **Nuevos**, encontrados al documentar y sin arreglar: 3.14 y 4.10 a 4.19.

## Por dónde empezar

1. **Mandarle al asesor `operones-asesor.md`, con la pregunta escrita de la
   decisión 3** (§8 de ese documento).
   - La 3 frena usar los operones como rasgo del paso 2.
   - La 1 frena la mitad del trabajo de diccionario.
   - Las dos, y el resto de las de operones, van ahí con nuestra
     recomendación.
2. **Bronce v5: disparador dominante [18] y autorregulación [16]** (2.1 y
   2.2), con el DDL de la bandera propuesto antes de escribir código.
3. **Las dos pruebas de `etapa2` [36] y [37]** (3.2 y 3.3): son arreglos de
   prueba, baratos, y hoy frenan una máquina nueva.
4. **Decidir la compuerta del paso 2** (7.1): `CLAUDE.md` y `PLAN.md` dicen
   cosas distintas, y de eso cuelga casi toda la sección 7.
5. **Poner al día `PLAN.md` y `CLAUDE.md`** (9.1 a 9.3): hoy describen la
   corrida 1 y remiten a secciones que ya no existen.

---

## 1. Preguntas y decisiones para el asesor

1. **Decisión 3 (abierta): respuesta verbal, probable (semana del 5 al 9 de
   octubre de 2026). GRN_experimental es la red regulatoria y no una fuente de
   operones. Falta confirmar por escrito si alguna relación se amplió por
   pertenencia a operón; hasta entonces la pertenencia solo anota.**
   - Mientras tanto, la pertenencia no entra como rasgo del paso 2, y no se
     monta la guarda de contaminación por procedencia (3.13).
   - La pregunta escrita y lo que cambia con cada respuesta están en
     `operones-asesor.md` §8.
   - Lo que hay que tocar cuando llegue está en `guia-operones.md` §11.
2. **Decisión 1: la regex de locus tag.** Aprobar `^PA\d{4}[a-z]?(\.\d+)?$`,
   que recupera 58 locus que hoy se pierden (entre ellos crcZ, `PA4726.11`, que
   sale como su regulador cbrB cuando el texto lo nombra por locus) y los 22
   promotores de CDBProm con sufijo de letra. Costo: regenerar el diccionario,
   una corrida nueva del bronce y recalcular 95.1 / 84.7 / 44.0; toca el
   generador y `lexico.py` de `etapa2`. `reunion-asesor-25sep.md` §2.C y §4.
3. **Decisión 2: las 16 unidades de BioCyc en `pendiente_revision`** (cita sin
   código de evidencia, 21 PMIDs): ¿conocidas o predichas? Va con otra
   pregunta: hoy los PMIDs y la evidencia se toman de todo el subárbol de la
   unidad, y 16 de las 64 con PMID lo traen solo por su promotor. Tomarlos solo
   de su `citation` cambiaría qué cuenta como conocido.
   `catalogo-operones.md` §3.2 y §8.
4. **Decisión 4: CDBProm y la clave de silver.** Validar las dos discrepancias
   del volcado (el encabezado dice F/R y los datos D/R; el rango es de 81 pb y
   la secuencia de 60 nt) y decidir si el inicio de transcripción entra en la
   clave: hoy dos unidades con los mismos genes colapsan y el promotor no dice
   a cuál pertenece. `catalogo-operones.md` §3.4, §4.3 y §8.
5. **Decisión 6: validar tres decisiones tomadas por cuenta propia.** El modelo
   bronce/silver de cinco tablas, el paquete `grn_operones/` en vez de
   `grn_etl/operones/`, y normalizar con `genes_pao1.tsv` y no con la
   anotación de pseudomonas.com (que proponía el encargo, regla 1 de
   `CONTEXTO_OPERONES.md`). `reunion-asesor-25sep.md` §4.
6. **Decisión 7 [34]: los 103 operones del corpus que no están en el
   catálogo.** El 27-sep se midió que los mayores (exoSTY, rsmZY, phzMS, lasRI,
   cyaAB) son genes separados que el texto abrevia juntos, y solo 3 de los 103
   tienen su conjunto exacto en la base de operones: completarlos tal cual
   metería uniones que no se cotranscriben. Recomendación: dejarlos como lista
   de huecos (`operones-asesor.md` §7). `decisiones.md` («La base de operones
   anota el bronce, no lo detecta»), bitácora del 27-sep (tarde).
7. **Contar la literatura de operones por PMID único.** ODB, BioCyc y
   PseudoCAP pueden citar el mismo artículo, y hoy cuentan como respaldos
   distintos en `n_fuentes`. `decisiones.md` («Lo que la integración
   destapó»), `curar.py` («La trampa de contar fuentes»).
8. **Las seis preguntas de la sección 4 del PLAN** (`PLAN.md:183-188`):
   - P1: qué hacer con las 66 filas de homología que traen además una cita
     directa. La exclusión de las 2 850 ya está acordada y medida.
   - P2: 15 filas de homología terminan en PA15…PA29, todas con signo `-`:
     ¿arrastre de celda?
   - P3: qué significa `d` (14 filas) y si el vacío (123 filas) equivale a
     `Unknown`. Frena la tabla de signo **[26]**.
   - P4: ¿«Histórica» y «Validada» son la misma base? Antes de preguntar,
     revisar la redacción: «Validada» no aparece entre los valores de `Origen`
     que registra `PLAN.md:81`.
   - P5: 515 filas del denominador (25.7 %) tienen su artículo fuera del
     corpus. Es el argumento para la query refinada del grupo de OPM (5.8).
   - P6: ¿la actualización recurrente es requisito o visión? Decide la
     prioridad de **[21]** y, por la misma visión, de **[22]**.
9. **Criterio de éxito.** La unidad de evaluación ya está resuelta de hecho
   (par y candidata en el paso 1, oración para el signo, arista en el paso 3);
   falta decidir qué valor haría útil el resultado para el laboratorio.
   `traspaso-etapa-2.md:207-217`.
10. **Corregir ante el asesor dos datos de la reunión del 25-sep.** Los
    operones con promotor no eran 1 350 (hoy son 1 574, ya con PGD), y PGD y
    BioCyc no comparten Pathway Tools. La decisión 5 (buscar un volcado de PGD)
    quedó superada: los operones entraron por la exportación de su curador.
    Bitácora del 27-sep. *Escrito el 16-oct-2026 en la fe de erratas del guion
    y en `operones-asesor.md` §9; falta mandarlo.*
11. **Registrar la reunión del 25-sep en el §1 del PLAN**, con lo que pidió ahí
    el asesor (los operones de pseudomonas.com) y las decisiones que quedaron
    sin respuesta; después, cada respuesta que llegue. *Cerrado el
    16-oct-2026: `PLAN.md` §1.4.*
12. **Aviso escrito al asesor antes de usar Claude Code en la máquina del
    laboratorio.** Solo aplica si se usa ahí; hoy el trabajo corre en la
    laptop. `CLAUDE.md:548-552`.

## 2. Paso 1 (bronce): lo siguiente

1. **Bronce v5: disparador dominante [18].** Que cada relación tome el signo
   del disparador más específico de su oración, no la unión de todos. El techo
   es pasar de 114 a 675 pares con signo utilizable (cifras de la corrida 1),
   limpia los 195 contradictorios y desbloquea la medición de signo, hoy con 1
   caso evaluable de 22. La muestra de 50 está anclada a la corrida 1: medir
   exige recalcular `signo_sugerido` sobre esas 50 oraciones o sortear otra.
   `PLAN.md:160`, `bitacora.md:1026-1074`, `identificar.py:46-48`.
2. **Bronce v5: bandera de autorregulación [16].** `identificar.py` exige dos
   genes distintos, así que MexT → mexT no sale. Emitirla con bandera propia
   sube el oro de 84.7 % a 89.2 % y habilita 43 filas del denominador de la
   base curada. Dos condiciones: la bandera es columna nueva (proponer el DDL y
   esperar confirmación), y el evaluador congelado
   `evaluar_cobertura_bronce.py:232-241` marca toda autorregulación como no
   cubierta, así que el 89.2 % no aparece sin tocarlo. `PLAN.md:158`.
3. **Dirección [30].** 6 de los 24 errores de la muestra son pares correctos
   orientados al revés: revisar si son dos TF, ninguno, o sintaxis contraria a
   `es_tf`. El candidato que propone el PLAN, scispaCy, se descartó el 27-sep
   por seis bloqueantes (0.5.4 no instala en Python 3.12, entre ellos); el PLAN
   no lo recoge (9.8). `PLAN.md:166`, `bitacora.md:202-205`.
4. **Diccionario [17]: la mayor causa de pérdida** en las dos referencias (12
   de 27 en el oro; 917 menciones y 77 ids sin locus en el cruce). Todo cambio
   toca `etapa2`, donde viven el generador y una de las dos copias que vigila
   `test_recursos.py`. Los frentes:
   - la regex de la decisión 1 (1.2);
   - la capa de sinónimos desde NCBI Gene (`gene_info` más un
     `sinonimos_manual.tsv` con autor, fecha y PMID): diseñada y no empezada,
     y las «tres condiciones acordadas» no están escritas en el repositorio
     (`reunion-asesor-25sep.md` §3 y §6);
   - **[35]** PA14 → PAO1 por ortología: 377 locus `PA14_#####`, 837
     menciones. Primero el mapeo y solo después el tokenizador, que hoy parte
     el guion bajo. `PLAN.md:167` y `PLAN.md:83` se contradicen sobre si toda
     la homología viene de PA14;
   - 101 blancos de CollecTF que el diccionario solo conoce por locus tag
     (`avance-seminario-2.md:125-141`);
   - 16 locus de PGD que no están en `genes_pao1.tsv` (PA0632, PA0822,
     PA2245…), por los que 4 operones salen como no adyacentes
     (`bitacora.md:318-323`);
   - llegar a 55 de 55 factores del oro: cambiar la firma de las 22 filas
     manuales por una cita de UniProt; confirmar que las clases `complejo` y
     `familia` de IHF y PrrF estén cerradas en el resto del flujo
     (`lexico.py` no las trata); y una decisión escrita para CpxR, cuya
     asignación habitual contradice a RefSeq, y para PirR, sin corroboración
     pública (`decisiones.md:644-660, 722-731`).
5. **Símbolos ambiguos [19].** Las 568 menciones de `tag` (PA0010) son jerga
   («FLAG tag»). La regla de `CLAUDE.md` descarta borrar la entrada, así que
   queda exigir contexto. `palabras_comunes.txt:111` lo anota como PA1751. Ojo
   con el nombre: la bitácora también llama «requiere_contexto» a las 7
   pérdidas de **[24]**. `PLAN.md:161`, `bitacora.md:888-902`.
6. **El segundo PMID más frecuente del denominador [27]:** 179 filas, con XML
   y 25.1 % de cobertura. Depende del cruce versionado (7.2). `PLAN.md:163`.
7. **Fuerza de la relación [6], [7], [9], [25].** Partir `disparadores.csv`
   en unión directa y experimental o indirecta **[6]** (`directly binds` ya
   entró el 17-sep); la columna `tipo_efecto` **[7]**, que es DDL; la vía
   léxica de fuerza **[9]**; y decidir si entra un segundo eje por método
   experimental **[25]**. `PLAN.md:133-136, 177`.
8. **Reorganizar `recursos/` en `organismo/` y `estandar/` [8]**, y ubicar ahí
   también `operones_base.tsv`. `PLAN.md:135`.
9. **Lo que queda del [32].** Medir anaerobiosis y respiración microaerobia, y
   metabolismo de fosfato, antes de añadirlos; «revisar las proteínas» no
   tiene estado; los demás candidatos del análisis de n-gramas siguen fuera, y
   el script que los produjo no está versionado. `PLAN.md:138`,
   `bitacora.md:545-569`.
10. **Siete términos viven en dos vocabularios**: regulon, transcriptional
    regulator, transcriptional activator, transcriptional repressor, negative
    regulator, positive regulator y autoregulation están en `disparadores.csv`
    y en `contexto_regulatorio.csv`, así que la misma mención sale en dos ejes.
    Es el argumento con el que se rechazó meter las bombas de expulsión como
    función, y aquí no se decidió. `PROCEDENCIA.md:299-302`.
11. **El score no está calibrado.** Sirve para ordenar, no como umbral, hasta
    medir si mejora la precisión. `identificar.py:169-175`.
12. **Catálogos actualizables por retroalimentación, en la base y por
    organismo.** Acuerdo del 04-sep sin fila en el PLAN. `PLAN.md:36`.

## 3. Integridad y pruebas

1. **Nomenclatura de las dos referencias [2].** Los nombres están definidos
   (`PLAN.md:9-13`); falta aplicarlos en el código y los documentos. Ejemplos:
   `grn_bronce/cli.py:486` dice «referencia del proyecto», y la bitácora del
   27-sep llama «base curada» a la base de operones.
2. **[36] `test_clasificar` falla donde torch se importa.** Dos pruebas de
   `PruebasMainSinTorch` suponen que `import torch` falla; en el `.venv` siguen
   hasta un checkpoint falso. El arreglo, de cuatro líneas y ya probado en una
   copia, es `mock.patch.dict(sys.modules, {"torch": None, "transformers":
   None})` alrededor de `C.main()`. Detalle en la bitácora del 28-sep.
3. **[37] `test_extraer_pares` falla en un clon limpio.** Pide los
   `entity_marked_*.jsonl` del asesor en `etapa2/para_colab/`, que git no
   trae, y no se salta si faltan. Arreglo: `skipUnless` con el motivo, y que la
   guía de traspaso copie los `.jsonl` también ahí.
4. **`pares --corrida N` y `operones --corrida N` no validan la corrida.** Con
   un id que no existe, o una corrida rehecha, escriben un CSV vacío sin decir
   por qué, y `--corrida 0` cae en la última `ok`. Además, `pares` escribe
   `pares_candidatos_<día>.csv` sin la corrida en el nombre: dos corridas el
   mismo día se pisan, el mismo defecto que costó la corrida 3.
   `bitacora.md:81-86`, `grn_bronce/cli.py:504-511, 552`.
5. **Pruebas para `unir_juicios.py`, `evaluar_cobertura_bronce.py` y el
   subcomando `pares` [20]**: tres piezas que producen cifras citadas.
6. **Unificar la cifra de autorregulación [28].** Circulan 10 filas y 5.7 %,
   4.5 puntos, 8 de 176 y 11 de 190, en más lugares de los tres que dice el
   PLAN (también `extraer_pares.py:95, 544` y `test_extraer_pares.py:18,
   447`).
7. **Relaciones en disputa del oro.** Solo 1 de 5 está marcada; faltan nombrar
   las otras cuatro y una columna `disputa` alimentada por `verificar_oro.py`
   (el denominador pasaría de 176 a 172). `bitacora.md:922-927, 1014-1019`.
8. **Tres de las cinco formas de inflar una cifra siguen abiertas.**
   `--disputadas` vacía el denominador con solo exigir una justificación
   (85.1 % → 100.0 %, con código 0); `evaluacion_oro.json` no copia los
   umbrales ni las filas excluidas que sí guarda `red_informe.json` (80.6 %
   contra 93.8 %); y el manifiesto del caché lo escribe el mismo script que
   descarga. `decisiones.md:791-827`.
9. **Dos juicios discutibles de la muestra de 50**: las filas 14 (mvfR →
   pqsA) y 27 (RpoS → dinB). Si pasan a «no», la precisión baja a 40.0 %.
   `criterios_juicio.md:22`, `bitacora.md:786-788`.
10. **24 aristas nuevas sin explicar** tras la corrección del diccionario del
    27-ago (8 653 − 189 + 24 = 8 488). `hallazgos.md:54-56`.
11. **`palabras_comunes.txt` cita mal locus tags** (al menos hemE, minD y pilI,
    que son PA5034, PA3244 y PA0410) y un «191» que no corresponde a nada. Hay
    que corregir las dos copias a la vez, o falla `test_recursos.py`.
    `bitacora.md:1098-1100`, `PROCEDENCIA.md:208-212`.
12. **Línea base de coocurrencia**: medir si el clasificador supera a «los dos
    genes aparecen juntos»; hoy el 95.1 % mide el extractor, no el modelo.
    `etapa2/README.md:269-272`.
13. **Guarda de contaminación por procedencia de operones**, cuando llegue la
    decisión 3 (1.1).
14. **Ninguna prueba ejercita el paso `operones` del flujo**: ni omitido cuando
    falta `operones_base.tsv`, ni con `--rehacer-operones`.
    `pruebas/test_flujo.py`, `guia-operones.md` §6. *Cerrado el 20-oct-2026.*

## 4. Catálogo de operones

1. **Tomar el `common-name` de BioCyc**: 94 unidades lo traen y salen sin
   nombre. Se arregla sin red (`reparsear --fuente biocyc`, `curar`,
   `catalogo --paso1`) y cambia `operones_base.tsv` y su huella. *Cerrado el
   20-oct-2026, con la columna «Nombre en BioCyc» en el catálogo.*
2. **`es_adyacente` ignora el sufijo `.N`**: 38 de los 55 no adyacentes tienen
   algún locus `.N`, y nadie ha revisado cuántos son falsos.
   `catalogo-operones.md` §4.3. *Cerrado el 20-oct-2026: el sufijo cuenta.*
3. **Pedir a PGD la tabla del release 22.1** (6-oct-2023) con permiso escrito,
   a pseudocap-mail@sfu.ca o gwinsor@sfu.ca. La que entró es del 19-jul-2021.
   Se carga con `--archivo`, `--url` o `PGD_OPERONES_URL`. *Cerrado el
   22-oct-2026: el curador la mandó el 21-oct y entró como foto vigente
   (`guia-operones.md` §8, D). No cambia `operones_base.tsv`.*
4. **Una fuente que parsea cero filas sale del catálogo sin aviso.** Una página
   de desafío guardada y pasada con `--archivo`, un XML de BioCyc sin unidades
   o un `genes.xml` sin `accession-1` cierran la extracción como completa con 0
   filas; y un cuerpo que no es XML lanza `ET.ParseError`, que no atrapan ni
   `extraer` ni `reparsear`. *Cerrado el 20-oct-2026: la foto vigente es la
   última completa con filas, también para `foto_sana` y `reparsear`, y lo
   ilegible es formato desconocido.*
5. **La lista de revisión para el asesor no es reproducible.**
   `operones_conflictos.csv` ya trae las `pendiente_revision`; falta versionar
   el enriquecimiento con PubMed (título, año, revista y tipo por PMID),
   propuesto como `exportar --pendientes`. *Cerrado el 20-oct-2026.*
6. **Prueba y fixture de `parsear_odb`**, que hoy solo se probó contra el
   volcado real. *Cerrado el 20-oct-2026.*
7. **La hebra puede variar entre máquinas**: sale primero del caché local
   ignorado (`datos_etapa2/cache_diccionario/refseq_gff.gz`) y solo si falta de
   la copia versionada. *Cerrado el 20-oct-2026: primero la versionada, y
   `curar` dice cuál usó.*
8. **Mover `rutas` de `grn_bronce` a `grn_comun`.** *Cerrado el 20-oct-2026,
   con un puente en `grn_bronce` para los importadores que faltan.*
9. **Las guías de máquina no dicen cómo generar `operones_base.tsv`**
   (`catalogo --paso1`, con cuenta de BioCyc): en una máquina nueva el bronce
   reporta «recurso ausente». *Cerrado el 16-oct-2026: nota en las dos guías
   de máquina y las tres vías en `guia-operones.md` §8. Con la base copiada no
   hace falta la cuenta de BioCyc.*

Los que siguen se encontraron el 16-oct-2026, al documentar los operones. El
detalle de cada uno está en `guia-operones.md` §12.

10. **Las entradas del paso `operones` de `flujo.py` están incompletas.**
    Declara `operones_pao1.tsv`, `curar.py` y `exportar.py`. No declara la
    base de datos, los crudos, el resto del paquete, `genes_pao1.tsv`, el GFF
    ni `grn_bronce/operones.py`. Un cambio en ellos no rehace el paso, y hoy
    hace falta `--forzar operones`. *Cerrado el 20-oct-2026: declara lo que se
    puede huellear, `--rehacer-operones` corre siempre, y sin la bandera avisa
    en cada corrida hasta que se regenera.*
11. **`extraer` y `reparsear` salen con 0 aunque falle una fuente** por
    credenciales, red o un crudo que falta. En cambio, un XML ilegible o un
    `--archivo` que no existe terminan con traza. *Cerrado el 20-oct-2026.*
12. **Una extracción fallida cuenta como corrida fallida.** Pasa en dos casos:
    - la que no trae archivos queda incompleta, como CDBProm en cada
      `extraer --fuente todo` sin `--url` ni `CDBPROM_URL`;
    - la que falla antes de bajar queda abierta, como BioCyc sin
      credenciales.

    A la segunda, `curar` pide revisar la foto. *Cerrado el 20-oct-2026: sin
    intento no se abre extracción, y lo que falla a medias la cierra.*
13. **`extraer --archivo` exige el correo de contacto** aunque no haga ninguna
    petición. *Cerrado el 20-oct-2026.*
14. **El CSV de conflictos no trae `nombre`**: la unidad solo se identifica
    por sus locus. *Cerrado el 20-oct-2026.*
15. **Código muerto:** `fuentes.URL_ODB_TABLA` y `--max-paginas`, que se acepta
    y no hace nada. *Cerrado el 20-oct-2026, junto con `EVIDENCIA_CURADA`.*
16. **La ruta del crudo es la de la máquina que bajó.** `reparsear` usa
    `operones_descargas.ruta` tal cual, y una ruta de Windows no se resuelve en
    Linux. *Cerrado el 20-oct-2026: se busca bajo la raíz de datos de hoy y
    manda la huella.*
17. **La autorregulación por operón cuenta operones sintéticos.**
    `etapa2/extraer_pares.py` usa `lexico.miembros_operon`, que incluye las
    concatenaciones del texto, mientras el resto del proyecto expande solo por
    tabla. *Cerrado el 20-oct-2026 sin cambio de código.* Medido, son 12 de los
    8 000 pares marcados, y en la mayoría la marca es correcta. Contarlos solo
    por tabla metía una arista falsa. El detalle está en `guia-operones.md` §12.
18. **`pares_informe.json` no sella `operones_pao1.tsv`**, con el que el
    puente expande el blanco de un par. Sí sella `genes_pao1.tsv`. *Cerrado
    el 20-oct-2026.*
19. **La capa corrida a mano puede mezclar dos versiones de la base:**
    `operones_en_oracion` viene del bronce, y `operones_del_blanco` del
    `operones_base.tsv` del momento. Por el flujo no pasa. *Cerrado el
    20-oct-2026: la capa se niega.*

## 5. Paso 0 y NCBI

1. **Retiro del OA Service de PMC**: mover `liga_pdf_pmc()` al PMC Cloud
   Service. No está comprobado que ya haya dejado de contestar.
   `CLAUDE.md:655-661`.
2. **Correo de mantenedor separado del de quien corre**, y registrar `tool` y
   `email` con NCBI. Decidir también qué correo va a Unpaywall (`etl.py:216`).
3. **Detectar `{"error":"API rate limit exceeded"}`**, que hoy revienta
   después en el parseo con un mensaje que no dice lo que pasa.
4. **Aviso de exención de NCBI**, que es obligatorio: pie del tablero, epílogo
   del CLI y párrafo del README.
5. **Avisar de la hora**: NCBI pide los trabajos grandes en fin de semana o
   entre 21:00 y 5:00, hora del Este. Desde el 13-oct `ingestar()` lo recuerda
   en el log cuando la corrida pasa de 100 peticiones; falta estimarlo antes
   de lanzar y hacerlo también en `fulltext`.
6. **EPost y el History server.** Subir el lote de 200 a 500 ya se puede con
   `run --lote`; EPost tendría que conservar lo de pedir solo la diferencia.
7. **Umbral para dejar E-utilities**: si el corpus llega a decenas de miles de
   artículos, la vía es la descarga local de MEDLINE. La segmentación
   automática por fechas ya existe (13-oct, `pubmed.tramos_por_fecha`) y
   resuelve el tope de 10 000 por consulta; una consulta de 83 638 son ~480
   peticiones y todavía cabe. El umbral sigue siendo el volumen sostenido.
8. **Query refinada del grupo de OPM** (externa), para los artículos de la base
   curada que faltan en el corpus. Ya no hace falta partirla a mano: `run` la
   parte solo si pasa de 10 000.
9. **Aviso de exención de NCBI**: el README y el `LEEME.txt` de cada paquete
   exportado ya lo llevan (13-oct); faltan el pie del tablero y el epílogo del
   CLI (punto 4 de esta lista).
10. **Pedir por biblioteca lo que no es de acceso abierto** (`export
    --pendientes`; Elsevier, por su API de TDM). Las cifras de 607 y 738 son
    del corte del 17-ago.
11. **Ampliar el corpus con los 607 PDFs de PMC fuera del subset abierto**:
    pospuesto hasta tener la precisión medida.
12. **La consulta de plantas transgénicas** (`queries/plantas_transgenicas.txt`,
    83 638 resultados): borrar `Dr_edgardo_solicitudv1` (sus 10 corridas
    llevaban límite 1 000 y dejaron 5 540 documentos truncados), registrarla
    como `plantas_transgenicas` y correrla sin límite de noche o en fin de
    semana. Los 5 540 documentos se conservan y se vuelven a vincular sin
    bajarlos otra vez.

## 6. Deuda técnica

1. **Limitador de tasa por instancia.** La solución que proponen los documentos
   (Redis) no es biblioteca estándar: hay que aprobarla o buscar otra. Aun con
   un trabajo a la vez, el CLI y el tablero corriendo juntos suman tasa.
2. **SQLite de un solo escritor.** Pasar a Postgres ya no tocaría solo
   `grn_etl/db.py`: también `grn_bronce/db.py`, `grn_operones/db.py` y los
   scripts de `etapa2` que abren la base con `sqlite3`. Y pide un driver fuera
   de la estándar. Con este y el anterior se podría subir el tope de un trabajo
   a la vez.
3. **El PDF no alimenta al bronce [23]**: medir cuánto texto útil sale con
   PyMuPDF (aprobado, no instalado). Solo 88 documentos dependen del PDF y 66
   filas del denominador ganarían texto.
4. **`lexico.py` y las copias del diccionario viven en `etapa2`.** Mudarlos es
   una «mudanza de módulos», que la congelación sí permite, ajustando sus
   importadores (`extraer_pares.py:116`, `test_diccionario.py:50`,
   `test_extraer_pares.py:51`). Es prerrequisito para migrar `etapa2`.
5. **`GRN_DATOS`**: el CLI del paso 0, el tablero y varios scripts de `etapa2`
   lo ignoran; donde apunta fuera del repositorio, sin `--db` usan
   `./datos/grn.db`. Se corrige al tocar cada archivo.
6. **Acentos a medias** en `grn_bronce/cli.py`, `exportar.py` y
   `PROCEDENCIA.md`: normalizar cada archivo entero de una pasada.
7. **50 archivos versionados con CRLF** en el checkout, pese a `eol=lf` en
   `.gitattributes`. Lo mitigan `huella_texto` y la prueba de divergencia.
8. **El candado de `flujo.py`** (`.flujo.lock`, O_EXCL) no revisa si el PID
   que lo tomó sigue vivo: una corrida muerta por SIGKILL lo deja puesto y hay
   que borrarlo a mano. `reentrenar.py` usa `fcntl.flock`, que el núcleo
   suelta solo (9-oct-2026).
9. **El conjunto ciego trae columna `pmid` y nadie la usa.** `cli reservas`
   reserva sus oraciones, no sus 29 artículos. Reservar los artículos, o sus
   6 pares, haría que la trampa del signo siguiera siendo externa para un
   modelo entrenado con la base; el 9-oct se decidió no hacerlo y declararlo
   en `RESULTADOS.md`.

## 7. Pasos 2 y 3

1. **La compuerta.** `CLAUDE.md` prohíbe crear `grn_verificacion/` y
   `grn_red/`, y migrar `etapa2`, hasta que el paso 1 reporte métricas, y lo
   sigue llamando «en construcción»; `PLAN.md:139` dice que ya las tiene, y
   `PLAN.md:147` que `grn_verificacion` está fuera de alcance. Hay que
   decidirlo.
2. **Cargador de la base curada [11] → cruce de PMIDs versionado [12] →
   candidatas nuevas para el asesor [14].** El cruce se midió, pero vive en
   scripts de un solo uso. Una de las dos opciones para el cargador, un script
   nuevo en `etapa2`, choca con la congelación.
3. **Conectar el bronce con el BioBERT [33]** y recalcular el 44 %, como se
   acordó.
4. **Tabla de equivalencias de signo [26]**, que espera la P3 y tendrá que
   tratar además una celda `+, +` y tres con un locus corrido.
5. **Las otras dos vías de verificación**: fine-tuning de un LLM y un agente
   con directrices, sobre un conjunto de evaluación común que tampoco existe.
6. **Guía de anotación y conjunto anotado de PAO1: el obstáculo de fondo.** Sin
   él no hay cifra defendible sobre *P. aeruginosa*, no se pueden calibrar los
   umbrales 0.65 / 0.70 / 0.60 (hoy solo con el dev de *E. coli*), y
   `no_relation` sigue siendo un artefacto del marcado (el 98.4 % comparte
   ventana con una positiva).
7. **Inversión por fenotipo del mutante** (`red.py --invertir-fenotipo`):
   subiría el signo por oración de 36.6 % a ~51.6 %. Bloqueada por la
   congelación.
8. **Reentrenar con `<e1>`/`<e2>` como tokens y sin minúsculas** (GPU).
9. **Rigor del número del clasificador**: brazo de control con partición al
   azar, barrido con varias semillas (el código ya está, falta GPU),
   validación cruzada por PMID, y escribir con su script por qué subió el
   número al quitar la fuga. Para el modelo de la base curada ya está hecho
   (16-oct): validación cruzada por artículo, 3 semillas e intervalo por
   bootstrap. Falta para el de *E. coli*.
10. **Juicio humano de las 112 filas prioritarias** de la muestra de 250
    aristas. La columna `veredicto` está llena, pero es casi la pasada
    automática: 31.7 % y 16.8 % son, en la práctica, cifras automáticas.
11. **Cascada de decisión**: medir el reparto 78 / 19 / 3 y hacer ablación por
    capa.
12. **Operones en la red: expansión o anotación** (paso 3). El catálogo con
    nivel de evidencia puede informarlo; la pertenencia como rasgo espera la
    decisión 3. Es la D9 de `operones-asesor.md` §7, con la recomendación de
    expandir con el catálogo del paso 1 y conservar la arista original como
    procedencia.
13. **Independencia de los 307 pares con dos o más PMIDs.**
14. **RegulomePA como contraste.**
15. **Texto completo contra resumen**: el modelo ya corrió sobre todo el
    corpus; falta partir el resultado por fuente.
16. **Recall del bronce contra la referencia**, sobre aristas, en el paso 3.
17. **Servidor del asesor**: el symlink roto `model_ckpt_best`, el stub
    `infer_pseudo.py`, el orden de etiquetas de `config.yaml` y los
    `optimizer.pt` (~40 GB).

## 8. Diferido

1. **[21] Bronce incremental**: cambia la clave de `texto_unidades`, así que
   es DDL. Su prioridad depende de la P6.
2. **[22] Re-búsqueda encadenada** y diff entre versiones de corpus.
3. **[24] Ventana de contexto** para las 7 pérdidas de coocurrencia del oro,
   caso por caso.
4. **Eje agudo-crónico** como condición de documento en el paso 2, si hace
   falta.

## 9. Documentación, entorno y limpieza

1. **`PLAN.md`**: el §2 describe la corrida 1 (488 221 menciones, 239
   disparadores) y no la 4; la fila 30 todavía propone scispaCy; los
   pendientes de `grn_operones` no tienen filas. El §1 ya tiene la reunión del
   25-sep, y la fila 34 ya no dice «completar» (16-oct).
2. **Referencias colgantes a `PLAN.md`**: `CLAUDE.md:547` remite a una
   «sección 7» que no existe; `CLAUDE.md:560` dice que los pasos 2 y 3 están
   descritos ahí como panorama (se quitaron en `96d80db`); `CLAUDE.md`, el
   README y el steering lo describen con «sus tablas y sus contratos».
3. **`CLAUDE.md`**: `menciones.tipo` toma ocho valores, no siete (falta
   `contexto_regulatorio`, desde la corrida 3); el modelo de datos no lista las
   cinco tablas de `grn_operones` (resuelto el 16-oct); la carpeta `queries/`
   no existe (las consultas están en la raíz); y la descripción de la suite de
   la raíz omite `grn_operones`.
4. **Steering de Kiro**: `dominio-grn.md` prevé un diccionario desde PGD, que
   es vía cerrada; `migracion-servicio.md` da por pendiente el encolado, que ya
   resolvió `trabajos.Gestor`.
5. **README**: la estructura omite `grn_bronce`, `grn_comun`, `etapa2` y
   `credenciales.py`; dice 349 pruebas (hoy 633); manda empezar por
   `informe-seminario-1.md`, que no menciona el bronce; y falta el aviso de
   NCBI (5.4).
6. **`etapa2/README.md` y el informe** dicen que la inferencia no ha corrido
   (corrió el 27-ago) y que hay cinco huecos (quedan tres); además, 180 contra
   179 verificadas.
7. **`traspaso-maquina-nueva.md` §5 está vencida**: pide correr el pipeline,
   meter `verificar_oro.py`, corregir 180 contra 179 y cerrar cinco huecos.
8. **Versionar el análisis de scispaCy**, que hoy solo existe en la
   conversación del 27-sep.
9. **La bitácora no tiene entradas del 18 al 24-sep**, cuando se construyó
   `grn_operones`. *Cerrado el 16-oct-2026: reconstruido de los commits en
   `guia-operones.md` §0.*
10. **La rama `etapa2-reparticion`** está fusionada en `main` y sin borrar, en
    local y en `origin`.
11. **El torch del Python del sistema está roto** desde la instalación fallida
    del 27-ago: limpiarlo o dejarlo. Explica por qué ahí pasan las pruebas del
    punto 36.
