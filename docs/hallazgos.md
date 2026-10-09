# Hallazgos medidos

Cada entrada es un hecho con su medicion y su fecha. `CLAUDE.md` conserva solo
la **regla derivada** de cada uno y apunta aqui; asi el documento que se carga
en cada sesion no crece con la evidencia, pero la evidencia no se pierde.

Formato de cada entrada: que se observo, como se midio, que regla salio de ahi.
Si un hallazgo se invalida despues, no se borra: se le agrega la correccion con
su propia fecha, porque saber que algo dejo de ser cierto es tan util como el
hecho original.

---

## Colisiones de simbolos de gen con palabras inglesas

**27 de agosto de 2026.**

Un simbolo de gen puede ser una palabra comun del ingles cuando se lee en
minusculas. La comprobacion original preguntaba si la superficie *tal como se
escribe* (`folD`) era palabra inglesa; no lo es. Pero el emparejamiento del
lexico es insensible a mayusculas, asi que lo que importa es su forma en
minusculas, y por ahi se colaban cuatro:

| gen | colisiona con | menciones | en minuscula |
|---|---|---|---|
| `folD` (PA1796) | fold, de "a 3-fold increase" | 1166 | 1151 |
| `hemE` (PA5034) | heme | 123 | 118 |
| `pilI` (PA0410) | pili | 136 | 115 |
| `minD` (PA3244) | mind | — | — |

**Como se detecto.** No lo encontro ninguna metrica. Salio al preparar la
muestra de precision: la arista `AlgU -> folD` traia 16 articulos de respaldo y
**ninguna de sus oraciones de evidencia mencionaba el gen**. `folD` llego a ser
el segundo blanco mas citado de toda la tabla de evidencias.

**Cuanto pesaba.** Las cuatro sostenian **193 de 8653 aristas**. Activar
`sensible_mayusculas` elimino **189** sin tocar una sola arista ajena a ellas;
sobrevivieron 4 con evidencia coherente (`Anr->hemE`, y `ChpA`, `PilG`, `PilH`
hacia `pilI`, que son el sistema quimiosensor del cluster pil). De las 133
aristas con blanco `folD`, en **cero** casos la oracion representativa escribia
`folD` con mayusculas exactas; 27 traian literalmente "N-fold".

**Lo mas incomodo del hallazgo.** Al corregirlo, **ninguna metrica se movio ni
una decima**. El patron de oro cubre 190 relaciones de seis subsistemas y no
contenia ninguna de esas 189. Es decir: 189 falsos positivos entraron y
salieron de la red sin que nada lo notara. Una referencia mide lo que cubre y
es ciega a lo que cae fuera.

**Regla derivada.** La defensa no es una lista negra que borra entradas del
diccionario, sino la columna `sensible_mayusculas`, que exige coincidencia
exacta de mayusculas para esa fila. Una lista negra sobre la palabra habria
borrado tambien las cuatro aristas correctas.

**Pendiente.** La correccion no solo quito 189 aristas: tambien **aparecieron
24** que antes no estaban (8653 - 189 + 24 = 8488). Ningun documento lo
explica todavia.

---

## `cap` es vocabulario de *E. coli*, no de *P. aeruginosa*

**3 de septiembre de 2026.**

Un plan de trabajo proponia `fur` y `cap` como los dos ejemplos de la lista
negra de colisiones. **`cap` no existe en PAO1**: cero coincidencias como
simbolo y como alias en las 5642 filas de `genes_pao1.tsv`, y tampoco esta en
`palabras_comunes.txt`. `fur` si (PA4764, `es_tf=true`, sensible a mayusculas).

CAP es el nombre clasico de la proteina activadora por catabolito de
*Escherichia coli* (= CRP). En *P. aeruginosa* el homologo se llama **`vfr`**
(PA0652, "cAMP-regulatory protein"), que si esta en el diccionario.

**Por que importa mas de lo que parece.** El clasificador heredado se entreno
con *E. coli* y se aplica a *P. aeruginosa*. Encontrar vocabulario de *E. coli*
en documentos de planeacion es la misma clase de arrastre, y sugiere revisar
cualquier nombre de gen que llegue de ese lado antes de darlo por bueno.

**Regla derivada.** Sospechar de todo simbolo que venga del lado de *E. coli*
y comprobarlo contra `genes_pao1.tsv` antes de usarlo.

---

## Pseudomonas Genome DB responde 403

**Medido el 20 de agosto de 2026 y de nuevo el 3 de septiembre.**

`pseudomonas.com` devuelve **HTTP 403 Forbidden** a `urllib.request`, incluida
la peticion con User-Agent de navegador. Es proteccion de bot, no filtro de
User-Agent: no hay cabecera que lo resuelva.

**Regla derivada.** Pasarla exigiria un navegador headless, que es a la vez
dependencia y evasion, y las dos cosas estan prohibidas. El diccionario PAO1 se
construye desde **RefSeq GFF + KEGG + UniProt** mas una capa manual con tope de
40 filas y justificacion en prosa obligatoria. La procedencia completa, con
versiones y fechas, esta en `grn_bronce/recursos/PROCEDENCIA.md`.

**Consecuencia para quien planee.** Cualquier documento que pida "construir el
diccionario desde Pseudomonas Genome DB" esta pidiendo algo que ya se probo dos
veces y no funciona. No es un pendiente: es una via cerrada con alternativa en
produccion.

### Tercera medición, 27 de septiembre de 2026: el sitio entero, y los operones

Se volvió a medir porque el asesor pidió los operones tal como los muestra la
página (`feature/show/?id=…&view=operons`). Se hizo una petición por URL con
`urllib`, dos segundos entre cada una y sin nada que imite un navegador.

- **Todo el host está detrás de un desafío administrado de Cloudflare.** Las
  nueve URLs probadas contestaron igual: 403, `Server: cloudflare`,
  `Cf-Mitigated: challenge` y una página «Just a moment...». La lista incluye
  `robots.txt`, `/strain/download`, los archivos estáticos de `/downloads/`
  (el CSV, el GFF y los ortólogos de PAO1), el export CSV de `feature/list` y
  la vista de operones. Una ruta inventada contesta lo mismo, así que el 403
  no dice si una URL existe.
- **El `robots.txt`** (Wayback, agosto de 2025) prohíbe la recolección
  automatizada sin permiso escrito del operador.
- **No hay archivo bulk de operones.** La página de descargas del release
  22.1 (Wayback, febrero de 2025) ofrece por cepa FASTA, anotación en
  CSV/GFF/GBK/GTF y ortólogos, y nada con operones. Solo existen en la vista
  HTML de cada gen, y rasparlos exigiría pasar el desafío: sigue cerrado.
- **Los operones de PGD son DOOR más PseudoCAP, no Pathway Tools.** Lo dicen
  Winsor et al. 2011 (doi:10.1093/nar/gkq869: «precise operon predictions
  based on the Database of Prokaryotic Operons (DOOR)») y Lee et al. 2023
  (doi:10.1128/msystems.00342-22, Métodos). `CONTEXTO_OPERONES.md` y
  `grn_operones/curar.py` decían Pathway Tools y trataban a PGD y BioCyc como
  una sola fuente. Se corrigió.

**La vía que sí funciona.** Geoff Winsor, curador de PGD, entregó la tabla de
operones de PAO1 al laboratorio Greene para Lee et al. 2023, y ellos la
publicaron con licencia BSD-3: `greenelab/core-accessory-interactome`, commit
`25539b82`, `data/metadata/PAO1-operons-2021-07-19.csv`.

- Responde 200 a `urllib`.
- Trae 1 290 operones en 3 816 filas: 1 165 de DOOR y 125 de PseudoCAP con
  75 PMIDs.
- Coincide campo por campo con la vista de la página, comprobado con
  `metG-PA3483`.
- Es la fuente `pgd` de `grn_operones` (`fuentes.URL_PGD`).
- Límite: es una foto del 19 de julio de 2021, y el release vigente (22.1) es
  del 6 de octubre de 2023. Una versión nueva se pide a pseudocap-mail@sfu.ca,
  que es como la consiguió el laboratorio Greene.

**Regla derivada.** Los operones de PGD entran por esa exportación, con
procedencia y huella. El diccionario sigue sin PGD: su anotación está tras el
mismo desafío.

---

## El BioBERT no sube la precisión del bronce, pero acierta el signo donde lo da

**8 de octubre de 2026.**

Se conectó el bronce de la corrida 4 con el clasificador run22 y se volvió a
medir sobre las mismas 50 oraciones juzgadas el 11-sep, con las reglas de
`unir_juicios.py` (el dudoso va al denominador). Unieron 50 de 50 y P0
reproduce 22 de 50.

| | valor | IC 95 % (Wilson) |
|---|---|---|
| P0, bronce solo | 22/50 = 44.0 % | 31.2-57.7 |
| P1, con el filtro del BioBERT y umbral | 16/37 = 43.2 % | 28.7-59.1 |
| R1, correctas retenidas | 16/22 = 72.7 % | 51.8-86.8 |
| E1, incorrectas descartadas | 6/24 = 25.0 % | 12.0-44.9 |
| signo, donde lo da | 11/11, incluidas 2 represiones | 74.1-100 |
| «siempre +» sobre las 15 con signo claro | 11/15 = 73.3 % | 48.0-89.1 |

**Lo observado:**
- El filtro descarta en la misma proporción las buenas y las malas, así que
  sobre esta muestra no separa.
- Pasar a `no` las dos filas discutibles (14 y 27) no cambia la conclusión:
  40.0 % contra 40.5 %.
- El signo acierta las 11 que cubre, pero deja 4 de 15 sin signo.
- Las seis invertidas no las puede arreglar el BioBERT: en las seis el
  regulador verdadero no es TF, y el modelo solo pone TF como `<e1>`.

**Regla derivada.**
- La predicción del BioBERT entra a la capa como columna, **no como filtro**.
  Descartar por un umbral sin calibrar tira tantas relaciones buenas como
  malas.
- Toda cifra de precisión va con su retención al lado (R1).
- El signo de 11/11 se cita con su n y su cobertura, nunca solo.

---

## La sintaxis v1 orienta poco y no rompe nada; el control léxico del disparador cubre más

**8 de octubre de 2026.** Medido con `grn_bronce/sintaxis.py` v1 (spaCy 3.7.5,
`en_core_sci_md` 0.5.4) sobre las 29 659 candidatas de la corrida 4: 76 453
pares no ordenados en 96 s de CPU.

**Dirección (punto 30).** La ficha de los 6 invertidos se escribió antes de
correr (`ficha-invertidos-punto30.md`).
- Esperaba 2 de 4 recuperables y salió **1 de 4** (la línea 20).
- **0 de las 22 correctas se rompería**, y 6 se confirman.
- La línea 8 falla por la regla nominal: en «RhlR-dependent phenotypes» la
  regla pone a RhlR de regulador, cuando el sujeto (pqsE) es el regulador.
- Sobre los 72 969 pares de la capa: 6 446 concuerdan con el orden del
  BioBERT, 4 103 lo invierten y 55 036 quedan sin orientar.
- **8 128 pares (11 %) tienen una mención que no se alineó con los tokens**
  (4 874 menciones).

**Signo (punto 18).** Sobre los 1 186 pares dirigidos del bronce, con 674 de
techo:

| regla | signo único | contradictorio | sin signo |
|---|---|---|---|
| bronce: la unión de los disparadores | 114 | 194 | 512 solo `?` |
| control léxico: el disparador con signo (+ o −) más cercano | 537 | 137 | 512 sin disparador con signo |
| sintaxis: el disparador dominante en el árbol | 166 | 47 | 361 solo `?` + 483 sin disparador |

La primera medición del control léxico (200, 104, 635) venía de un código que
aceptaba también los «?»: un «regulates» cercano le ganaba a un «represses»
lejano. Con la regla fijada antes de medir, la que dice la tabla, son 537 de
674. **Esto mide consistencia entre oraciones, no acierto:** que un par
tenga un solo signo no dice que sea el correcto.

**Regla derivada.**
- La dirección sintáctica no reorienta el bronce: no cumple el criterio
  fijado de antemano (≥ 3 de 4 y 0 rotas). Queda como columna informativa.
- Las reglas no se ajustan con estas 50 oraciones, que ya están vistas. La v2
  se mide contra una muestra nueva.
- Para el signo de la v5, el control léxico es el candidato barato: solo
  estándar y con el 80 % del techo. La sintaxis deja menos contradicciones a
  costa de perder pares. Antes de adoptar uno hay que medir su acierto contra
  signos juzgados, no solo su consistencia.
