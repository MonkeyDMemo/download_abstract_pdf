# Ficha de los 6 pares invertidos (punto 30 del PLAN)

Escrita el 8-oct-2026 **antes de mirar cualquier salida de la sintaxis**, como
pide el punto 30: primero se revisan a mano los casos y se fija qué se espera,
después se mide. Las líneas son de `etapa2/evaluacion/juicio_consolidado.csv`,
con el encabezado como línea 1, y los juicios son los del 11-sep
(`criterios_juicio.md`). El usuario la confirmó el mismo 8-oct, ya con la
sintaxis corrida, sin cambiar nada de lo que se esperaba.

**El patrón común:** en los seis, el regulador verdadero no es TF en
`genes_pao1.tsv` (pqsE, ybeY, pilY1, deaD, fleN). El bronce orientó hacia el
único TF de la oración, que es lo que hace su heurística `es_tf`. El BioBERT
solo marca TF como `<e1>`, así que **no puede corregir ninguno**: solo una
regla que no dependa de `es_tf`, como la sintaxis.

| Línea | Bronce | Verdad | Redacción | ¿La sintaxis v1 podría orientarlo? |
|---|---|---|---|---|
| 8 | rhlR → pqsE | pqsE → RhlR | «Deletion of pqsE … resulted in … defects in RhlR-dependent phenotypes»: mutante por pérdida, sin palabra de aumento, así que `clasificar()` la da como `otra` | **Probable.** pqsE está en el sujeto nominal de «resulted»; la regla activa lo pondría de regulador. El signo estaría invertido por ser deleción, pero aquí se mide dirección. |
| 11 | rpoS → ybeY | ybeY → rpoS | «overexpression of ybeY resulted in a higher rpoS mRNA level»: `fenotipo_mutante` | **No, por diseño.** La regla v1 deja sin orientar toda oración de fenotipo de mutante. |
| 20 | algR → pilY1 | PilY1 → algR | «PilY1 functions by transcriptionally repressing the levels of algR»: activa | **Probable.** PilY1 es el sujeto y algR cuelga del verbo de represión. |
| 41 | exsA → deaD | DeaD → ExsA | «DeaD … due to its stimulatory effect on the synthesis of … ExsA»: nominal con correferencia («its») | **Difícil.** Hace falta resolver «its» → DeaD, que la v1 no hace. |
| 44 | fleQ → fleN | FleN → FleQ | «The ATPase activity of FleQ is regulated via … FleN, through protein-protein interaction» | Aunque se oriente, **sigue siendo `no`**: es proteína-proteína. |
| 50 | fleQ → fleN | FleN → FleQ | estructura FleQ-FleN, sin verbo de regulación entre ellos | Igual que la 44: proteína-proteína. |

**Lo que se espera, fijado antes de correr:** de las cuatro recuperables (8,
11, 20, 41), la v1 debería orientar bien dos (8 y 20); la 11 queda sin orientar
por la regla del mutante, y la 41 es improbable. El criterio fijado el 8-oct para
reorientar el bronce con la sintaxis es **al menos 3 de 4 y ninguna de las 22
`si` rota**, así que lo esperable es que la v1 **no** lo cumpla con estas
reglas, y que la sintaxis quede como columna informativa. Si sale mejor que
esto, se sospecha antes de celebrar: son 50 oraciones ya vistas, desarrollo y
no prueba.

## Lo que salió (8-oct, después de fijar lo de arriba)

Medido con `python flujo.py --corrida 4` (`sintaxis.py` v1, `en_core_sci_md`
0.5.4) y escrito en `salidas/flujo/corrida4_run22/evaluacion.json`. La
sintaxis corrió **antes de que el usuario confirmara esta ficha**; lo de
arriba no se tocó después de correrla.

| Línea | Esperado | Salió | Regla que decidió |
|---|---|---|---|
| 8 | orienta bien | **concuerda con el bronce (mal)** | nominal: «RhlR-dependent phenotypes» pone a RhlR de regulador y gana a la activa |
| 11 | sin orientar | sin orientar | `fenotipo_mutante` |
| 20 | orienta bien | **orienta bien** (pilY1 → algR) | activa, «repressing» |
| 41 | improbable | sin orientar | ninguna («propose», sin correferencia) |
| 44 | proteína-proteína | sin orientar | ninguna |
| 50 | proteína-proteína | sin orientar | la mención no se alineó con los tokens |

- **D1: 1 de 4 recuperables** (IC 95 % 4.6-69.9 %), 1 de 6 en total. Se
  esperaban 2; la diferencia es la línea 8.
- **D2: ninguna de las 22 `si` se rompería** (0/22, IC 0-14.9 %). La sintaxis
  confirma 6 de las 22 y deja 16 sin orientar.
- **El criterio (≥ 3 de 4 y 0 rotas) no se cumple**, como se esperaba. La
  dirección sintáctica queda como columna informativa de la capa.

La línea 8 enseña un modo de fallo: «X-dependent» dice de quién depende un
fenotipo, no quién regula a quién, y aquí el regulador verdadero (pqsE) está
en el sujeto de la oración. **No se ajustó la regla con esta muestra**: estas 50
ya están vistas, y corregirla aquí la haría parecer mejor sin probar nada.
Queda para la v2, medida contra una muestra nueva.
