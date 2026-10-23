# Rúbrica para anotar relaciones de regulación

Versión 1, del 21 de octubre de 2026. Es una propuesta para validar con el
Dr. Edgardo Galán-Vásquez el viernes 23 de octubre: es la decisión a de
[`reunion-asesor-23oct.md`](reunion-asesor-23oct.md). Después de la sesión de
calibración (§7) se ajusta **una sola vez** y queda congelada. Cualquier cambio
posterior va al final, con fecha y motivo, como la enmienda de un protocolo.

Las citas `archivo:línea` son de `main` en `f05951a`.

---

## 1. Para quién y para qué

- **Para quién.** Los ayudantes que anotan, el adjudicador que resuelve los
  desacuerdos y quien saca las cifras.
- **Para qué.** Para dos cosas, las dos sobre oraciones del corpus público:
  1. **La muestra ciega.** Mide la precisión de la plata, es decir, de cada
     capa del paso 2 que acepta o descarta pares, sobre oraciones que nadie ha
     mirado. Las 50 del 11 de septiembre ya no sirven para eso: con ellas se
     midieron la sintaxis y el BioBERT, y la regla del proyecto es no volver a
     medir con lo ya visto (`hallazgos.md:220-221`).
  2. **Las candidatas nuevas.** Es una muestra de los pares que el pipeline
     propone y que la base curada no registra. Que una relación falte en la base
     no la hace falsa. Por eso la precisión de ese grupo sale de esta revisión y
     no del contraste automático (Documento de Tesis v1, p. 10).
- **Qué formaliza.** Los criterios del juicio de las 50
  (`etapa2/evaluacion/criterios_juicio.md`), que eran las notas de un juez.
  Donde esta rúbrica decide distinto, lo dice el §3.9, junto con su efecto
  sobre el 44 %.

## 2. Qué se anota

- **Un ítem es una oración y dos entidades de esa oración.** Las entidades son
  genes, proteínas, operones o ARN reguladores. Una oración con tres entidades
  puede dar tres ítems, y cada uno se anota aparte.
- **El orden no dice quién regula.** `entidad_1` es la que aparece primero en la
  oración. Decidir quién regula a quién es trabajo del anotador (§3.4).
- **Gen y proteína son la misma entidad.** `lasR` y `LasR` cuentan igual.
- **Se juzga solo la oración.** No se abre el artículo, no se consulta ninguna
  base de datos y no se usa lo que uno sepa de la biología de
  *P. aeruginosa*. Con esa regla se juzgaron las 50: la precisión se lee «solo
  desde su oración» (`bitacora.md:1619-1620`).
- **El anotador es experto, y por eso esta regla pesa más.** Juzga lo que
  afirma la oración, no lo que él sabe. Si la relación es conocida pero la
  oración no la afirma, el ítem es `no`. Mientras anota no consulta bases
  curadas: ni la del laboratorio, ni RegulonDB, ni PseudoCAP, ni CollecTF.
  Lo que se mide es si el pipeline encontró una oración que dice la relación,
  no si la relación existe. La calibración lo prueba con el ítem c21.

## 3. Definiciones

### 3.1 Relación de regulación

Hay relación cuando la oración afirma que una de las dos entidades **cambia la
expresión de la otra**. Eso incluye su transcripción, la cantidad de su ARN o de
su proteína y la actividad de su promotor.

- Vale si la oración lo dice como resultado del artículo y también si lo da por
  sabido («LasR, the activator of rhlR, …»).
- Vale para cualquier regulador: un factor de transcripción, un factor sigma, un
  sistema de dos componentes o un ARN pequeño.

### 3.2 Lo que no es relación

Los ejemplos son sintéticos, como todos los de este documento.

| caso | ejemplo | se anota |
|---|---|---|
| interacción proteína-proteína | «MvaT and MvaU form heteromeric complexes» | `no` |
| cambiar la actividad de una proteína y no su expresión: fosforilarla o secuestrarla | «RsmZ sequesters RsmA» | `no` (a validar, §9) |
| co-regulación sin vínculo: las dos son blancos de un tercero | «lasB and rhlA are both regulated by RhlR», para el par lasB–rhlA | `no` |
| solo correlación: cambian juntas sin que una cause el cambio de la otra | «pslA and pelA increased in parallel» | `no` |
| mención conjunta | «lasR, rhlR and pqsR were cloned» | `no` |
| la entidad no es lo que el diccionario cree | «a FLAG tag»: aquí *tag* no es el gen PA0010 | `no` |

El último caso no es raro. Las 568 menciones de `tag` en el corpus son jerga de
laboratorio (`bitacora.md:1730-1732`).

### 3.3 Directa, indirecta o no se sabe (columna `tipo`)

| valor | cuándo |
|---|---|
| `directa` | La oración dice que no hay intermediario. El regulador se une al promotor, al operador o a la región reguladora del blanco (EMSA, huella o ChIP, con su resultado), o la oración lo dice con «directly» o «direct target». |
| `indirecta` | La oración nombra un intermediario o una cadena: «via», «through», «by inducing Z», «indirectly». |
| `no_se` | La oración afirma la regulación sin decir si hay intermediario: «X activates Y», «Y is X-dependent», el fenotipo de un mutante o una sobreexpresión. |

**Diferencia con el acuerdo del 4 de septiembre.** Ese acuerdo
(`PLAN.md:29`) llama «directa fuerte» a la unión al promotor y a la activación
o represión explícita, e «indirecta» a la sobreexpresión y al efecto sin
mecanismo. Es un eje léxico para el bronce, y se calcula desde el disparador.
Esta rúbrica no deduce el mecanismo a partir del verbo, así que «X activates Y»
se anota `no_se`. Si el asesor prefiere que el anotador aplique su eje, cambia
una sola regla: la activación o represión explícita pasa a `directa` (§9,
punto 1).

### 3.4 Dirección

- **Se anota quién regula a quién tal como lo dice la oración.** `1>2` si
  `entidad_1` regula a `entidad_2`, `2>1` al revés, y `ninguna` cuando no hay
  relación.
- **No se decide según cuál de las dos sea factor de transcripción.** Eso
  explica las seis inversiones de las 50: el bronce orientó cada par según la
  lista de factores, y en los seis casos el regulador verdadero no estaba en esa
  lista (`hallazgos.md:173-174`).
- **La voz pasiva no cambia la dirección.** «Y is repressed by X» es X → Y.
- **Dependencia y requisito.** «Y depends on X», «X is required for Y
  expression» y «X-dependent expression of Y» son X → Y.
- **Relación recíproca.** Si la oración afirma las dos direcciones («X and Y
  regulate each other»), se anota `1>2` con «recíproca» en el comentario. El
  adjudicador la cuenta en las dos direcciones. Esta regla es provisional
  (§9, punto 4).

### 3.5 Signo

| valor | cuándo |
|---|---|
| `+` | El regulador activa, induce o aumenta la expresión del blanco, o hace falta para ella. |
| `-` | El regulador reprime, disminuye o silencia la expresión del blanco. |
| `?` | Hay regulación, pero la oración no fija el sentido. Pasa con «X-regulated», con «Y belongs to the X regulon», con «X binds the Y promoter» cuando no dice el efecto, con «under the control of» y con «X regulates/controls Y». |

- Si la oración da dos signos según la condición («represses in planktonic
  cells but activates in biofilms»), se anota `?` y las condiciones van en el
  comentario.
- El signo queda vacío cuando `relacion` es `no`.

### 3.6 Negación

- **La oración niega el efecto entre las dos entidades.** Por ejemplo: «X had no
  effect on Y expression», «Y levels were unchanged in the X mutant» o «X is not
  required for Y». Se anota `relacion = no` y `negada = si`.
- **Excepción: la unión sin efecto.** Si la oración afirma que X se une al
  promotor de Y y a la vez niega que la expresión cambie, se anota
  `relacion = dudoso` y `negada = si` (fila 6 del juicio de las 50).
- **Lo negado tiene que ser el efecto.** «LasR is not the only activator of
  rhlR» afirma que LasR activa a rhlR, así que se anota `si` y `negada = no`.
- **Cuenta solo el par marcado.** En «X activates Y but not Z», el par X–Y es
  `si` y el par X–Z es `no` con `negada = si`.

### 3.7 Especulación

- **La relación aparece como posibilidad.** Pasa con «may», «might», «could»,
  «possibly», «likely», «putative» o «we hypothesize», y con una pregunta sin
  resultado («whether X regulates Y»). Se anota `relacion = dudoso` y
  `especulativa = si` (fila 23 de las 50).
- **«Show», «demonstrate», «indicate» y «suggest» con el verbo en indicativo
  presentan una conclusión, no una posibilidad.** «These results suggest that X
  represses Y» se anota `especulativa = no`, y este punto está a validar (§9,
  punto 5). Con un modal, como en «suggest that X may repress Y», se anota
  `especulativa = si`.
- **Si la duda es sobre el mecanismo y no sobre la relación**, la relación
  cuenta. «X activates Y, possibly by binding its promoter» se anota `si`, con
  `tipo = no_se` y `especulativa = no`.
- **Un objetivo que da la relación por sentada la afirma.** «To determine how X
  activates Y, …» se anota `si` (fila 14 de las 50).
- **Un experimento descrito sin su resultado** se anota `dudoso`, con «sin
  resultado» en el comentario. Es el caso de un pie de figura «EMSA of X with
  the Y promoter» (fila 43 de las 50).

### 3.8 Fenotipo de mutante

La redacción invierte el signo. Lo que se anota es la acción de X sobre Y, no el
cambio que se ve en el mutante:

- «Y increased in the X mutant» quiere decir que X reprime a Y: X → Y, `-`.
- «Y decreased in a ΔX strain» quiere decir que X activa a Y: X → Y, `+`.
- «Overexpression of X increased Y» se anota `+`, sin invertir.
- En los tres casos, `tipo = no_se`.

Esta regla importa porque es la falla medida del modelo actual. En las 24
oraciones de fenotipo de mutante de la trampa del signo, el BioBERT de
*E. coli* acierta 2. Catorce de sus errores son inversiones de signo
(`bitacora.md:2061`).

### 3.9 Lo que cambia respecto al juicio de las 50

| caso | juicio de las 50 | esta rúbrica | efecto sobre el 44 % |
|---|---|---|---|
| la oración dice la relación al revés de como la orientó el bronce | `no` | `si`, con la dirección que dice la oración | Ninguno en la cifra con dirección. Además permite dar la cifra sin dirección, que en las 50 fue 56.0 % (`bitacora.md:1604-1605`). |
| solo correlación | `dudoso` (fila 17) | `no` | Ninguno: `dudoso` y `no` cuentan igual en la precisión. |
| efecto negado | `no` | `no`, con `negada = si` | Ninguno. |
| `tipo`, `negada` y `especulativa` | no existían | se anotan | Ninguno. |

## 4. El árbol de decisión

1. **¿Las dos entidades son lo que el texto quiere decir?** Si alguna no lo es,
   por ejemplo jerga como «FLAG tag» o una palabra común, se anota `no` con
   «entidad mal reconocida» en el comentario. Fin.
2. **¿La oración dice algo de la relación entre esas dos, o solo las nombra
   juntas?** Si es interacción proteína-proteína, actividad sin cambio de
   expresión, co-regulación, correlación o mención conjunta, se anota `no`.
   Fin.
3. **¿Niega el efecto?** Se anota `no` con `negada = si`. Fin. La excepción es
   la oración que además afirma la unión al promotor: esa va `dudoso` con
   `negada = si`, y se sigue en el paso 6.
4. **¿Plantea la relación como posibilidad o como pregunta, o describe el
   experimento sin el resultado?** Se anota `dudoso`. Si es posibilidad o
   pregunta, también `especulativa = si`. Se sigue en el paso 6.
5. **¿La atribuye a otro organismo?** Se anota `dudoso` con «otro organismo:
   …» en el comentario. Si nombra otra cepa de *P. aeruginosa* (PA14, PAK), se
   anota como cualquier otra y la cepa va en el comentario: usar esa evidencia
   es otra decisión, la e de la reunión. En los dos casos se sigue en el paso 6.
6. **Dirección.** Si el ítem llegó hasta aquí sin quedar en `dudoso`, se anota
   `si`. Después, quién actúa sobre quién: `1>2` o `2>1` (§3.4).
7. **Signo.** `+`, `-` o `?` (§3.5), aplicando la regla del mutante (§3.8).
8. **Tipo.** `directa`, `indirecta` o `no_se` (§3.3).
9. **Comentario.** Es obligatorio en tres casos:
   - cuando el ítem es `dudoso`;
   - cuando se aplicó un caso frontera; se escribe su número, de F1 a F15;
   - cuando lleva una de estas marcas: «otro organismo», «cepa …»,
     «recíproca», «condición …» o «entidad mal reconocida».

Cómo se llena cada columna según la relación:

- **`no`:** `direccion = ninguna`; `signo` y `tipo` quedan vacíos.
- **`si` o `dudoso`:** `direccion`, `signo` y `tipo` siempre llevan valor. Si la
  oración no dice el signo o el mecanismo, se anota `?` y `no_se`.
- **`negada` y `especulativa`:** siempre llevan `si` o `no`.

## 5. Casos frontera

Las oraciones son inventadas para esta rúbrica, con genes reales de
*P. aeruginosa*. No son oraciones del corpus ni del laboratorio, y no afirman
nada sobre la biología. Cada anotación va en este orden: `relacion`,
`direccion`, `signo`, `tipo`, `negada`, `especulativa`.

**F1. El fenotipo del mutante invierte el signo.**
> pvdS transcript levels were markedly higher in the fur mutant than in the
> wild-type strain.

`pvdS`, `fur` → `si`, `2>1`, `-`, `no_se`, `no`, `no`. Lo que cambia es el
mutante de *fur*: el signo es el de Fur sobre *pvdS* (§3.8).

**F2. La dirección no sale de la lista de factores.**
> Full expression of rhlR is dependent on LasR.

`rhlR`, `LasR` → `si`, `2>1`, `+`, `no_se`, `no`, `no`. El que depende es el
blanco. Las dos entidades son factores de transcripción, así que la lista de
factores no decidiría nada aquí (§3.4).

**F3. Hay regulación, pero sin sentido fijado.** Son dos oraciones.
> (a) Several Vfr-regulated genes, including toxA, were examined.
>
> (b) phzA1 is a member of the RpoS regulon.

(a) `Vfr`, `toxA` → `si`, `1>2`, `?`, `no_se`, `no`, `no`.
(b) `phzA1`, `RpoS` → `si`, `2>1`, `?`, `no_se`, `no`, `no`. Ninguna de las
dos dice si activa o reprime (§3.5).

**F4. Unión al promotor, sin efecto dicho.**
> Purified AmrZ bound specifically to the algD promoter in electrophoretic
> mobility shift assays.

`AmrZ`, `algD` → `si`, `1>2`, `?`, `directa`, `no`, `no`. Hay unión y por eso
la relación es directa, pero el efecto no se dice (§3.3 y §3.5).

**F5. Unión con la expresión sin cambio.**
> Although PhoB bound the phzA1 promoter in vitro, phzA1 transcript levels were
> unchanged in a phoB deletion mutant.

`PhoB`, `phzA1` → `dudoso`, `1>2`, `?`, `directa`, `si`, `no`. La oración
niega el efecto y afirma la unión: es la excepción del §3.6.

**F6. El efecto negado.**
> Inactivation of anr had no effect on lasB expression under aerobic
> conditions.

`anr`, `lasB` → `no`, `ninguna`, vacío, vacío, `si`, `no` (§3.6).

**F7. Una negación que no niega la relación.**
> LasR is not the only activator of rhlR transcription.

`LasR`, `rhlR` → `si`, `1>2`, `+`, `no_se`, `no`, `no`. Lo negado es «el
único», no la activación (§3.6).

**F8. La relación como posibilidad.**
> These observations suggest that RsaL may repress hcnA directly.

`RsaL`, `hcnA` → `dudoso`, `1>2`, `-`, `directa`, `no`, `si`. El «may» pone en
duda la relación misma. El tipo es lo que la oración propone (§3.7).

**F9. La duda está en el mecanismo, no en la relación.**
> PchR activates pchE transcription, possibly by binding to a conserved box
> upstream of the gene.

`PchR`, `pchE` → `si`, `1>2`, `+`, `no_se`, `no`, `no`. La unión está en duda;
por eso el tipo es `no_se` y no `directa` (§3.7).

**F10. Un objetivo que da la relación por sentada, y una pregunta abierta.**
Son dos oraciones.
> (a) To determine how ExsA activates exoS transcription, we mapped its
> promoter.
>
> (b) We next asked whether ExsA also controls exoT.

(a) `ExsA`, `exoS` → `si`, `1>2`, `+`, `no_se`, `no`, `no` (fila 14 de las 50).
(b) `ExsA`, `exoT` → `dudoso`, `1>2`, `?`, `no_se`, `no`, `si`. Es una
pregunta sin resultado (fila 23 de las 50).

**F11. Co-regulación sin vínculo.**
> Both lasB and rhlA are positively regulated by RhlR.

`lasB`, `rhlA` → `no`, `ninguna`, vacío, vacío, `no`, `no` (§3.2). En la misma
oración, los ítems `lasB`–`RhlR` y `rhlA`–`RhlR` sí son relación: `si`, `2>1`,
`+`, `no_se`, `no`, `no`.

**F12. Solo correlación.**
> Expression of pslA and pelA increased in parallel during biofilm maturation.

`pslA`, `pelA` → `no`, `ninguna`, vacío, vacío, `no`, `no` (§3.2).

**F13. Cambia la actividad, no la expresión.** Son dos oraciones.
> (a) MvaT and MvaU form heteromeric complexes in vivo.
>
> (b) The small RNA RsmZ sequesters RsmA, relieving translational repression
> of its targets.

(a) `MvaT`, `MvaU` → `no`: es interacción proteína-proteína.
(b) `RsmZ`, `RsmA` → `no`, con «actividad» en el comentario. El secuestro
cambia lo que RsmA hace, no cuánto RsmA hay. Este caso está a validar (§9,
punto 2).

**F14. Otro organismo, y otra cepa.** Son dos oraciones.
> (a) In Escherichia coli, RpoS is required for katE expression.
>
> (b) In strain PA14, LasR is required for full expression of hcnA.

(a) `RpoS`, `katE` → `dudoso`, `1>2`, `+`, `no_se`, `no`, `no`, con «otro
organismo: E. coli» en el comentario. Está a validar (§9, punto 3).
(b) `LasR`, `hcnA` → `si`, `1>2`, `+`, `no_se`, `no`, `no`, con «cepa PA14» en
el comentario.

**F15. La entidad mal reconocida.**
> A C-terminal FLAG tag was fused to RhlR to allow immunodetection.

`tag`, `RhlR` → `no`, `ninguna`, vacío, vacío, `no`, `no`, con «entidad mal
reconocida» en el comentario. Aquí *tag* es jerga, no el gen PA0010 (paso 1 del
árbol).

## 6. La hoja de anotación

Es un CSV en UTF-8 con BOM, para que Excel lea bien los acentos, como el
paquete de exportación del paso 0. Las columnas de valores van con formato de
texto: en Excel, una celda que empieza con `+` o `-` puede leerse como
fórmula.

| columna | la llena | valores |
|---|---|---|
| `id_item` | quien arma la muestra | Un código opaco. No es el PMID y no dice de qué estrato viene. |
| `oracion` | quien arma la muestra | La oración tal cual sale del corpus. |
| `entidad_1` | quien arma la muestra | La entidad que aparece primero, escrita como en la oración. |
| `entidad_2` | quien arma la muestra | La otra entidad. |
| `relacion` | el anotador | `si`, `no` o `dudoso` |
| `direccion` | el anotador | `1>2`, `2>1` o `ninguna` |
| `signo` | el anotador | `+`, `-` o `?`; vacío si `relacion = no` |
| `tipo` | el anotador | `directa`, `indirecta` o `no_se`; vacío si `relacion = no` |
| `negada` | el anotador | `si` o `no` |
| `especulativa` | el anotador | `si` o `no` |
| `comentario` | el anotador | Texto libre; obligatorio en los casos del paso 9 del árbol. |

En el texto de esta rúbrica la dirección se escribe 1 → 2 y el signo menos como
−. En la hoja van `1>2` y el guion del teclado. Así los valores se teclean igual
en cualquier máquina y no dependen de la codificación de la consola, la misma
razón por la que los identificadores del proyecto van en ASCII.

Ejemplo, con dos ítems sintéticos tomados de los casos F1 y F6:

| id_item | oracion | entidad_1 | entidad_2 | relacion | direccion | signo | tipo | negada | especulativa | comentario |
|---|---|---|---|---|---|---|---|---|---|---|
| m-0001 | pvdS transcript levels were markedly higher in the fur mutant than in the wild-type strain. | pvdS | fur | si | 2>1 | - | no_se | no | no | F1 |
| m-0002 | Inactivation of anr had no effect on lasB expression under aerobic conditions. | anr | lasB | no | ninguna | | | si | no | F6 |

**Lo que la hoja no lleva**, a propósito:

- el PMID, la sección ni el estrato del ítem;
- la orientación del bronce, el disparador, el `signo_sugerido` ni el score;
- ninguna predicción ni probabilidad de un modelo;
- ninguna etiqueta de la base curada, ni si el par está en ella.

La llave que une `id_item` con el PMID, el par y el estrato la guarda quien
arma la muestra. Si la muestra se armó con la base, esa llave se queda en el
servidor.

**De la hoja a las cifras.**

- **Precisión con dirección.** Son los `si` cuya dirección coincide con la
  que propone el pipeline, entre el total. Los `dudoso` entran al denominador y
  no al numerador, como en `unir_juicios.py`. Esta es la cifra que se compara
  con el 44 %, que contó las inversiones como `no`.
- **Precisión sin dirección.** Son todos los `si` entre el total. En las 50
  fue 56.0 %.
- **Acierto de signo.** Se mide sobre los `si` con signo `+` o `-`.
- **Cada capa de la plata se mide sobre los ítems que acepta**, con su
  retención al lado (`hallazgos.md:180`).
- **Intervalos.** Todas las proporciones llevan su intervalo de Wilson al 95 %
  (`etapa2/muestrear_precision.wilson`).
- **Concordancia.** El κ de Cohen se calcula sobre la parte doble y antes de
  adjudicar. Se mide en `relacion` y, entre los ítems donde los dos anotaron
  `si`, en `direccion` y `signo`.

## 7. El protocolo con ayudantes

**En el servicio social (22-oct-2026; enmienda 1) anota una sola persona:** un
experto del área, pagado por hora. Los puntos 4 y 5 no aplican: sin parte doble
no hay κ ni adjudicación, y eso se reporta como limitación. Los demás siguen.
El tiempo se registra por bloque de 25 ítems como mínimo. En la página de
revisión del tablero se registra por ítem, solo.

1. **Se arranca con la rúbrica v1 y la sesión de calibración.** La calibración
   la ajusta una sola vez. Anotar sin rúbrica obliga a repetir (Documento de
   Tesis v1, p. 2).
2. **Calibración.** Todos anotan las mismas oraciones (21 en la v1.1) y después se discuten
   los desacuerdos. La rúbrica se ajusta una sola vez: sale la v1.1, con fecha y
   la lista de cambios, y desde ahí queda congelada. **Las oraciones son
   sintéticas**, escritas para la sesión como los casos del §5: ninguna sale
   del corpus, de `reservas.tsv`, del conjunto ciego ni de las 50 juzgadas.
   Así discutirlas no deja vista ninguna oración que luego se mida, y la
   muestra de medición no pierde nada. Se versionan junto a esta rúbrica:
   la llave, para quien dirige, en
   [`calibracion-anotacion.md`](calibracion-anotacion.md), y la hoja de los
   ayudantes en [`calibracion-hoja.csv`](calibracion-hoja.csv).
3. **Anotación independiente.** Nadie ve lo que anotó otro.
4. **Parte doble.** El 25 % de los ítems lo anotan dos personas para medir la
   concordancia con el κ de Cohen. Si hay más de dos ayudantes, las parejas se
   rotan y se reporta el κ de cada pareja con el acuerdo observado. La
   referencia es κ ≥ 0.60, el mismo umbral que la tesis propone para el juez
   automático (p. 11). Si sale menor, se reporta como limitación: la rúbrica no
   se vuelve a ajustar con la muestra de medición.
5. **Adjudicación.** Un adjudicador decide los desacuerdos de la parte doble, y
   su etiqueta es la que entra a las cifras. Conviene que no anote la parte
   doble.
6. **Qué ven los ayudantes.** Solo oraciones del corpus público. Nunca ven la
   base curada, sus etiquetas ni la salida de los modelos, y tampoco la
   orientación ni el signo que propone el bronce. Tampoco consultan bases
   curadas mientras anotan (§2).
7. **Carga estimada.** Unas 3 horas por cada 100 oraciones por persona
   (Documento de Tesis v1, p. 2). Con ese ritmo, la calibración son unos 36
   minutos de anotación por persona, más la discusión.
8. **El juez automático.** Si se usa uno (tesis, p. 11), la muestra anotada
   sirve también para medir su concordancia con los humanos. El juez no ve las
   etiquetas.

## 8. El tamaño de la muestra

**En el servicio social (enmienda 1): una muestra única de 200.** Sale de la
misma población que el 44 %: las 5 833 oraciones con regulador y blanco, 4 864
tras las exclusiones.
- Va en una sola hoja, sin parte doble y sin candidatas nuevas:
  `cli muestra ... --n 200 --tandas 1 --fraccion-doble 0`.
- Sobre los mismos 200 ítems se calculan dos precisiones pareadas, la del
  bronce y la de la red final, más la retención de la red
  (`cli precision-ciega`).
- Con 200 el intervalo queda en ± 6.8 puntos.
- Las candidatas nuevas y la parte doble pasan a la tesis.

Lo que sigue es el diseño original, con tres anotadores posibles, y se conserva
como referencia.

Los intervalos de Wilson al 95 % para p = 0.44 se calcularon con
`etapa2/muestrear_precision.wilson` y k = round(0.44 n). La carga sale de 3 h
por cada 100 ítems; la columna «con parte doble» suma un 25 % de ítems
anotados dos veces.

| n | IC 95 % | ancho | horas-persona sin parte doble | con parte doble |
|---:|---|---:|---:|---:|
| 50 | [31.2, 57.7] | 26.5 | 1.5 | 1.9 |
| 100 | [34.7, 53.8] | 19.1 | 3.0 | 3.8 |
| 150 | [36.3, 52.0] | 15.7 | 4.5 | 5.6 |
| 200 | [37.3, 50.9] | 13.6 | 6.0 | 7.5 |
| 300 | [38.5, 49.7] | 11.2 | 9.0 | 11.3 |
| 400 | [39.2, 48.9] | 9.7 | 12.0 | 15.0 |

Con p = 0.5, que es el peor caso, cada ancho cambia 0.2 puntos o menos: la
tabla vale aunque la plata no salga en 0.44.

**Propuesta: 300 ítems.** Son 200 de la muestra ciega y 100 candidatas nuevas,
con 75 de ellos anotados dos veces. Suman 375 anotaciones, unas 11.3
horas-persona, más la calibración y la adjudicación.

**Por qué 200 en la muestra ciega:**

- **Ancho.** Con 200 el intervalo queda en ± 6.8 puntos, contra ± 9.5 con 100.
- **La retención de cada capa.** Cada capa se mide solo sobre los ítems que
  acepta. En las 50, el filtro del BioBERT retuvo 37 (`bitacora.md:664`).
  Supongamos una capa que retiene lo mismo, el 74 %, con 10 puntos más de
  precisión, es decir 54 %. Con 200 ítems acepta unos 148, y su intervalo es
  [46.0, 61.9]: queda arriba del 44 %. Con 100 ítems acepta 74, el intervalo es
  [42.8, 64.9] y no se distingue del 44 %. Esto es un escenario, no una
  medición.
- **Concordancia.** El 25 % de 200 son 50 ítems dobles para el κ; con 100
  serían 25.
- **El rendimiento.** Pasar de 200 a 300 baja el margen de ± 6.8 a ± 5.6
  puntos y cuesta un 50 % más de trabajo.

**Por qué 100 candidatas nuevas.** Dan una primera estimación de ± 9.5 puntos.
Si el contraste (`docs/contraste-curada.md`) fija otro tamaño, manda el suyo.

**De dónde sale la muestra ciega.** Sale de la misma población que las 50: las
oraciones candidatas del bronce con regulador y blanco, ahora de la corrida 4:
5 833, las mismas que en la corrida 1. El resumen del bronce decía 8 339 «con
regulador y blanco», pero contaba solo el regulador: las otras 2 506 traen un
solo TF y más de un blanco posible, y el blanco queda vacío (corregido el
22-oct). Tras las exclusiones de abajo quedan 4 864. Cada ítem es la oración
con el par que propone el bronce, sin decir cuál de los dos es el regulador.
Así la cifra se compara con el 44 %, y cada capa de la plata se mide sobre lo
que acepta. Lo que la plata saque de pares que el bronce no orientó queda fuera
de esta población; eso lo cubre la revisión de candidatas nuevas.

**Lo que queda fuera de la muestra:**

- **Las oraciones reservadas** en `reservas.tsv`: las de la muestra de 50 y las
  del conjunto ciego. El criterio es la contención con
  `entrenamiento.MINIMO_CONTENCION`, que vale 40 caracteres. Sale la oración
  igual a una reservada, la que contiene una reservada de 40 caracteres o más,
  y la que es un pedazo de 40 o más de una reservada
  (`grn_verificacion/entrenamiento.py:439-459`).

Las de la calibración no hace falta apartarlas: son sintéticas (§7, punto
2) y no están en el corpus.

**Cómo se sortea.** La semilla se escribe antes de sortear, y el script que
sortea se versiona, como `muestrear_candidatas.py` con las 50 (`PLAN.md:206`).

**Con qué comando.** `python -m grn_verificacion.cli muestra --carpeta
salidas/flujo/corrida4_run22 --reservas salidas/flujo/reservas.tsv --n 200
--salida D` (`grn_verificacion/muestra.py`). La semilla por omisión es
20261024 y la parte doble, el 25 % de cada tanda (`--semilla`,
`--fraccion-doble`). Sortea por oración, con aleatorio simple, entre las
oraciones de `capa_pares.csv` cuyo par es el que orientó el bronce. Además de
las oraciones reservadas, deja fuera los artículos de los PMID de
`reservas.tsv`, que es como ahí están las 50, y las oraciones repetidas; el
resumen dice cuántas salen por cada motivo. Si se piden más ítems de los que
quedan, no sortea. Escribe cinco archivos, y cada uno va a alguien distinto:

- `hoja_tanda1.csv`, la tanda 1: a los ayudantes.
- `hoja_tanda2_ciega.csv`, la mitad ciega de la tanda 2: al servidor, donde
  se baraja con las candidatas nuevas en una sola hoja. Así no va a los
  ayudantes.
- `dobles.csv`, solo con qué ítems anotan dos personas y su tanda: a quien
  reparte y adjudica. No lleva la orientación del bronce, porque un
  adjudicador que la ve desempata hacia el bronce.
- `llave.csv`, con el PMID, el `id_par`, la orientación del bronce y qué
  ítems son dobles: solo para el análisis. No va a los ayudantes ni a quien
  adjudica.
- `resumen.json`, con la semilla, la población, las exclusiones y las huellas
  de las entradas y de las salidas. No lleva oraciones ni PMID.

Un CSV no guarda el formato de las celdas: al abrir la hoja en Excel, las
columnas de valores se ponen en texto antes de anotar (§6).

**Cómo se reparte entre las dos tandas, y por qué.** La primera tanda lleva 100
ítems de la muestra ciega. La segunda lleva los otros 100 barajados con las 100
candidatas nuevas, en una sola hoja. Así la hoja no dice qué pares faltan en la
base, y el anotador no sabe de qué estrato viene cada ítem. Las candidatas
nuevas se sortean donde vive la base, en el servidor, y la hoja sale de ahí
solo con el visto bueno del asesor (decisión d de la reunión).

**Si la plata usa un modelo entrenado con la base.** Su precisión se reporta
también sin los artículos que ese modelo vio al entrenar. Esa marca la pone,
en el servidor, quien tiene la base, y nunca llega a la hoja.

## 9. Lo que el asesor tiene que validar

1. **«X activates Y» se anota `no_se` y no `directa`** (§3.3). El acuerdo del
   4 de septiembre lo pone como «directa fuerte» en el eje léxico
   (`PLAN.md:29`).
2. **Cambiar la actividad de una proteína, por secuestro o fosforilación, no es
   arista** (§3.2, caso F13).
3. **Una relación que la oración atribuye a otro organismo se anota `dudoso`**
   (caso F14). En las 50, la fila 27 (inducción del regulón en *E. coli*) se
   juzgó `si` y quedó marcada como discutible
   (`etapa2/evaluacion/criterios_juicio.md:22`).
4. **Relación recíproca: ¿se agrega `ambas` a `direccion`?** Mientras tanto se
   anota `1>2` con «recíproca» en el comentario (§3.4).
5. **«Suggest» con el verbo en indicativo no es especulación** (§3.7).
6. **La correlación sola pasa de `dudoso` a `no`** (§3.9). No mueve el 44 %.
7. **El tamaño: 200 ciegas más 100 candidatas nuevas, con un 25 % de parte
   doble** (§8). *En el servicio social: 200 ciegas, un anotador, sin parte
   doble (enmienda 1).*

---

## Enmiendas

Cada enmienda lleva su fecha, qué cambia, por qué y si es anterior o posterior
a ver alguna cifra de la muestra.

**Enmienda 1, 22-oct-2026, anterior al sorteo y a toda anotación.**
- **Qué cambia:**
  - anota un solo experto, pagado por hora, así que no hay parte doble, κ ni
    adjudicación;
  - la muestra es única, de 200, en una sola hoja;
  - el tiempo se registra por bloque como mínimo;
  - la regla de juzgar lo que afirma la oración y no lo que sabe el anotador
    queda explícita (§2), sin consultar bases curadas;
  - la calibración suma el ítem c21.
- **Por qué:** el servicio social cierra con la capa determinista, y el
  LLM, la parte doble y las candidatas nuevas pasan a la tesis (`decisiones.md`,
  «El LLM sobre la oración es trabajo de tesis»). La reunión del 23-oct se
  canceló, así que la rúbrica se entrega con estos valores por omisión
  (`reunion-asesor-23oct.md`).
