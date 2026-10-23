# Calibración de la anotación: las oraciones sintéticas

Versión 1.2, del 23 de octubre de 2026, para la rúbrica v1 con sus enmiendas
1 y 2 ([`rubrica-anotacion.md`](rubrica-anotacion.md)). Es el material del
punto 2 del §7: quien anota juzga estas oraciones, se discuten con él los
desacuerdos con la llave y la rúbrica se ajusta una sola vez (v1.1). La v1.1
de este documento sumó c21, que prueba la regla del experto (§2). La v1.2 suma
c22 a c27 y la sesión corta de la «Calibración 2», antes de la tanda 2.

**Este documento es la llave, y es para quien dirige la sesión.** A quien
anota se le da solo [`calibracion-hoja.csv`](calibracion-hoja.csv), con
las columnas de la rúbrica (§6) y las de anotación vacías. La llave se enseña
después de que cada quien anotó, para discutir.

## Cómo están hechas

- **Son inventadas.** Usan genes reales de *P. aeruginosa*, pero no afirman
  nada sobre su biología. No salen del corpus, de `reservas.tsv`, del conjunto
  ciego ni de las 50 juzgadas. Tampoco repiten las oraciones del §5 de la
  rúbrica: los ayudantes la tienen a la mano, y anotar un ejemplo que ya trae
  su respuesta no calibra nada.
- **Se comprobó que no son del corpus.** Ninguna comparte 40 caracteres o más
  (`entrenamiento.MINIMO_CONTENCION`) con una oración candidata de la corrida 4
  ni con el texto de los XML de PMC descargados.
- **Hay 27 ítems en 26 oraciones.** Una oración da dos ítems (c04 y c05), para
  practicar que cada par se anota aparte (§2).
- **El reparto se parece al de una muestra real:** 15 `si`, 4 `dudoso` y 8 `no`.
  `dudoso` sale por sus cuatro vías: posibilidad (c12), sin resultado (c14),
  otro organismo (c15) y unión sin efecto (c16).
  Casi todas tocan una regla que, en el juicio de las 50 o en el diseño de la
  rúbrica, dio para discutir.
- **Quedan fuera dos reglas provisionales:** la relación recíproca (§9, punto 4)
  y el eje de tipo del 4 de septiembre (§9, punto 1). Si el asesor las fija el
  viernes, se agrega un ítem para cada una.

## La llave

El orden de las columnas es el de la hoja: `relacion`, `direccion`, `signo`,
`tipo`, `negada`, `especulativa`. Un guion largo (—) quiere decir celda vacía.

| id | oración | entidad 1 | entidad 2 | anotación | regla | por qué |
|---|---|---|---|---|---|---|
| c01 | RpoN is not the only sigma factor needed for pilA expression. | RpoN | pilA | si, 1>2, +, no_se, no, no | §3.6, F7 | Lo negado es «el único», no que RpoN haga falta para pilA. Un factor sigma es regulador (§3.1). Comentario: F7. |
| c02 | During ciprofloxacin exposure, exoS expression was strongly repressed by PtrB. | exoS | PtrB | si, 2>1, -, no_se, no, no | §3.4 | La voz pasiva no cambia quién regula. El regulador es la entidad 2. |
| c03 | In the gacA deletion strain, rsmZ transcript abundance dropped about tenfold relative to the parent strain. | gacA | rsmZ | si, 1>2, +, no_se, no, no | §3.8, F1 | Baja en el mutante, así que GacA activa. Comentario: F1. |
| c04 | Transcripts of phzA1 and phzM were both more abundant in an mvaT mutant than in PAO1. | phzA1 | mvaT | si, 2>1, -, no_se, no, no | §3.8, F1 | Sube en el mutante, así que MvaT reprime. Comentario: F1. |
| c05 | (la misma oración que c04) | phzA1 | phzM | no, ninguna, —, —, no, no | §3.2, F11 | Son dos blancos del mismo regulador, sin vínculo entre ellos. Comentario: F11. |
| c06 | Overexpression of vqsM from a multicopy plasmid elevated lasI promoter activity about threefold. | vqsM | lasI | si, 1>2, +, no_se, no, no | §3.8 | Con sobreexpresión el signo no se invierte. |
| c07 | AlgU binds directly upstream of mucA and activates its transcription, as shown by ChIP and EMSA. | AlgU | mucA | si, 1>2, +, directa, no, no | §3.3 | Unión al promotor con su resultado, y además «directly». |
| c08 | LasR controls pqsH expression only indirectly, through its activation of rhlR. | LasR | pqsH | si, 1>2, ?, indirecta, no, no | §3.3, §3.5 | Nombra al intermediario. «Controls» no fija el signo, y el signo de LasR sobre rhlR no se hereda al par LasR–pqsH. |
| c09 | Transcriptome analysis placed hcnB among the genes under the control of Anr. | hcnB | Anr | si, 2>1, ?, no_se, no, no | §3.5, F3 | «Under the control of» afirma la regulación sin el sentido. Comentario: F3. |
| c10 | Deletion of pprB did not alter cupE1 transcription in planktonic cultures. | pprB | cupE1 | no, ninguna, —, —, si, no | §3.6, F6 | Se niega el efecto. Comentario: F6. |
| c11 | NarL activated narK1 but not nirS under anaerobic conditions. | NarL | nirS | no, ninguna, —, —, si, no | §3.6 | Cuenta solo el par marcado: para NarL–nirS el efecto está negado. El par NarL–narK1 sería `si`. No hace falta número F: «solo el par marcado» no tiene caso frontera. |
| c12 | CzcR might also repress oprD, which would account for the carbapenem resistance of these isolates. | CzcR | oprD | dudoso, 1>2, -, no_se, no, si | §3.7, F8 | El «might» pone en duda la relación misma. Comentario obligatorio por `dudoso`, y F8. |
| c13 | Collectively, our measurements suggest that AmpR represses mexE. | AmpR | mexE | si, 1>2, -, no_se, no, no | §3.7 | «Suggest» en indicativo, sin modal, presenta una conclusión. Está a validar (§9, punto 5): es el ítem para discutirlo. |
| c14 | Figure 5. β-galactosidase activity of a lasB-lacZ fusion in wild-type and vfr mutant backgrounds. | lasB | vfr | dudoso, 2>1, ?, no_se, no, no | §3.7 | Describe el experimento sin su resultado. Comentario: «sin resultado». |
| c15 | In Pseudomonas fluorescens, GacA is required for rsmZ expression. | GacA | rsmZ | dudoso, 1>2, +, no_se, no, no | árbol, paso 5; F14 | Lo atribuye a otro organismo. Comentario: «otro organismo: P. fluorescens», F14. A validar (§9, punto 3). |
| c16 | NorR bound a site upstream of norC in EMSA, yet norC mRNA levels did not differ between the wild type and a norR mutant. | NorR | norC | dudoso, 1>2, ?, directa, si, no | §3.6, F5 | Afirma la unión y niega el efecto: es la excepción del §3.6, la única vía a `dudoso` con `negada = si`. Comentario: F5. |
| c17 | PqsE enhances DNA binding by RhlR but leaves the abundance of rhlR mRNA unchanged. | PqsE | RhlR | no, ninguna, —, —, no, no | §3.2, F13 | Cambia la actividad de RhlR, no su expresión. Comentario: «actividad», F13. A validar (§9, punto 2): si el asesor lo revierte, va `si, 1>2, +, no_se, no, no`. |
| c18 | PqsR-dependent transcription of pqsA requires either HHQ or PQS. | PqsR | pqsA | si, 1>2, +, no_se, no, no | §3.4, F2 | «X-dependent expression of Y» es X → Y. Comentario: F2. |
| c19 | MexT represses mexS in rich medium but activates it under nitrosative stress. | MexT | mexS | si, 1>2, ?, no_se, no, no | §3.5 | Dos signos según la condición, así que va `?`. Comentario: «condición: medio rico −, estrés nitrosativo +». |
| c20 | The lasB promoter was fused to lacZ to monitor its activity in the different backgrounds. | lasB | lacZ | no, ninguna, —, —, no, no | árbol, paso 2 | Una fusión reportera es una construcción, no una relación entre dos genes. La rúbrica v1 no la trata: ver abajo. Comentario: «fusión reportera». |
| c21 | Both lasR and lasB transcripts were abundant in the sputum isolates examined here. | lasR | lasB | no, ninguna, —, —, no, no | §2, §3.2 | Cualquier experto sabe que LasR activa lasB, pero la oración solo dice que los dos transcritos abundan: es mención conjunta. Se juzga lo que afirma la oración, no lo que sabe el anotador. Comentario: «lo sabe el experto, no lo dice la oración». |
| c22 | rhlI transcription is regulated by MvaU in a growth-phase dependent manner. | rhlI | MvaU | si, 2>1, ?, no_se, no, no | §3.5 | «Regulated» afirma la regulación sin el sentido: el signo es `?`. El signo desconocido es `?`, nunca `0`. |
| c23 | The anr and dnr genes are located in different regions of the PAO1 chromosome. | anr | dnr | no, ninguna, —, —, no, no | §3.2 | Mención conjunta. Con `no`, la dirección es `ninguna`, nunca vacía, y el signo y el tipo van vacíos. |
| c24 | Contrary to earlier reports, we found no evidence that RsmA controls rhlR expression. | RsmA | rhlR | no, ninguna, —, —, si, no | §3.6, F6 | La oración niega el efecto: la relación negada se anota `no` con `negada = si`, no `si` con `negada = si`. Comentario: F6. |
| c25 | QscR represses phzA1 transcription during exponential growth. | QscR | phzA1 | si, 1>2, -, no_se, no, no | §3.5, §3.6 | Reprimir es un signo, no una negación: `si` con `-` y `negada = no`. Es el contraste con c24. |
| c26 | pqsA transcription was undetectable in a pqsR deletion mutant. | pqsA | pqsR | si, 2>1, +, no_se, no, no | §3.8, F1 | «Indetectable en el mutante» no niega la relación: dice que PqsR activa a pqsA. Comentario: F1. |
| c27 | PhoB activates phoA transcription when phosphate is limiting. | PhoB | phoA | si, 1>2, +, no_se, no, no | §3.3 | «Activates» no dice el mecanismo: el tipo es `no_se`, no `directa`. `directa` pide unión al promotor con su resultado o «directly» (c07). |

## Lo que se espera discutir

- **c21:** la regla del experto (§2). El anotador es experto y la relación es
  conocida; si la anota `si`, juzgó con lo que sabe y no con la oración. Es el
  ítem que más importa de la sesión.
- **c01 y c16:** las dos negaciones difíciles. En c01 no se niega la relación;
  c16 es la única vía a `dudoso` con `negada = si`.
- **c08:** si «controls» basta para `?` o hay que heredar el signo de la cadena.
  La rúbrica dice `?`.
- **c13 y c15:** dos reglas que la rúbrica marca como a validar. Si los
  ayudantes no coinciden, es el argumento para fijarlas en la v1.1.
- **c14:** el pie de figura. Es fácil anotarlo `si` porque el experimento
  sugiere la relación.
- **c17:** la frontera entre actividad y expresión, que es el punto 2 del §9.
- **c03 y c04:** la regla del mutante, que es la falla medida del modelo
  (§3.8). Si un ayudante la invierte aquí, la invertirá en la muestra.

## Calibración 2: antes de la tanda 2

La tanda 1 se anotó sin calibración previa y en la hoja CSV. Cuatro códigos o
reglas de la v1 se aplicaron de otra forma. Ninguna regla cambia: la sesión
las repasa con ítems sintéticos. No se citan los ítems reales de la tanda 1:
sus juicios no van al repositorio.

1. **El signo desconocido es `?`, nunca `0`.** Pasó en 43 ítems de la tanda 1.
2. **Con `relacion = no`, la dirección es `ninguna`, nunca vacía.** Pasó en 46.
3. **Una relación negada se anota `no` con `negada = si` (F6).** Hubo 5
   anotadas `si` con `negada = si`. La única vía a `negada = si` sin `no` es
   `dudoso` por la excepción F5. La página de revisión ahora rechaza `si` con
   `negada = si`.
4. **«X activates Y» sin mecanismo explícito va `tipo = no_se`** (§3.3). En
   varios casos de la tanda 1 se marcó `directa`. No cambia la precisión,
   porque `tipo` no entra en esa cifra, pero sí el acuerdo de Ouroboros en ese
   campo. Por eso, en la tanda 1 ese acuerdo se reporta con esta salvedad.

**La sesión, de unos 30 minutos:** 12 ítems, en este orden: c07, c22, c10,
c25, c01, c24, c09, c26, c16, c27, c11 y c23. Son los seis nuevos y seis de
la v1.1 que tocan las mismas reglas. Unos 22 minutos de anotación, a 3 horas
por cada 100, más la discusión. Quien anota recibe
[`calibracion2-hoja.csv`](calibracion2-hoja.csv).

**La tanda 2 se anota en la página de revisión, no en la hoja.** La página
valida los códigos de la rúbrica y registra el tiempo por ítem:

```
python servidor.py --revision salidas/revision/muestra200_t2 --abrir
```

## Dos huecos de la rúbrica v1, para el viernes

La revisión ciega de esta llave (22-oct) coincidió en todos los valores, y
encontró dos reglas que la rúbrica no fija:
- **Fusiones reporteras** (lacZ, gfp, lux). Ninguna regla las trata, y van a
  aparecer mucho en el corpus (c14 y c20 traen una). Propuesta: una fila en
  §3.2, «fusión reportera: `no`».
- **Cuándo es obligatoria la marca «condición …».** El paso 9 del árbol la pide
  cuando el ítem la «lleva», pero §3.5 solo la define para dos signos según la
  condición. Propuesta: obligatoria solo en ese caso (c19); nombrar la condición
  en otros ítems (c02, c10, c11) es opcional y no cuenta como desacuerdo.

## Después de la sesión

- Se anota en la sección «Enmiendas» de la rúbrica qué cambió, con fecha, y la
  rúbrica pasa a v1.1.
- Si una regla cambió, se corrige su fila en esta llave. Las oraciones no se
  cambian: son el registro de con qué se calibró.
