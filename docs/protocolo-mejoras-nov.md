# Protocolo: mejoras de noviembre, medidas contra la base curada

24-nov-2026. Es anterior a registrar los PDF de OpenAlex del corpus de agosto,
a correr la red con ellos y a medir cualquier variante contra la base. El
usuario aprobó las opciones A a D; la E espera el permiso del asesor.

## Línea base

La corrida 20 (`salidas/flujo/corrida20_run22`), contraste del 5-nov-2026
(`salidas/contraste/CONTRASTE_corrida20.md`), estrato «sin BioBERT», 1,560
filas exigibles:

| Medida | Corrida 20 |
|---|---|
| Recall dirigido | 689/1,560 (44.2 %) |
| Cualquier dirección | 721/1,560 (46.2 %) |
| Orientación | 689/721 (95.6 %) |
| Techo (regla a con expansión) | 764/1,560 (49.0 %) |
| Acuerdo de signo, con abstención | 321/649 (49.5 %) |
| «Siempre activa», con abstención | 486/649 (74.9 %) |

## Las opciones: una regla cada una, sin variantes

- **A. Más texto.** Entran los PDF de OpenAlex del corpus `v0-agosto` que
  pasan `grn_etl.openalex.es_el_articulo`, en la versión que OpenAlex guarde
  (publicada o enviada; se cuenta cuántos de cada una). Bronce `--con-pdf
  --rehacer --conservar-anteriores` (la corrida 20 no se borra), el flujo con
  el mismo modelo (`modelo_limpio_run22`) y los mismos umbrales, y el jurado
  v1 como en la corrida 20: una oración por arista y una segunda para las
  aristas sin respaldo con 2 o más artículos.
- **B1. Dirección con el jurado.** Toda arista de nivel `al_reves` con
  `votos_si` ≥ 2 se voltea (el regulador pasa a blanco). Si la arista volteada
  ya está en la red, no se duplica. Las demás no cambian.
- **B2. Signo con el jurado.** Si la red dice `regulates`, el jurado da `+` o
  `-` (`signo_agente`) y el nivel es alta o media (o es una arista volteada
  por B1), el signo pasa a `activates` o `represses`. Una arista a la que la
  red ya le dio signo no cambia.
- **D. Cortes por nivel de confianza.** Cuatro redes derivadas, de menor a
  mayor: solo alta; alta y media; alta, media y las volteadas por B1; toda la
  red con B1.
- **C. Clasificador entrenado con los veredictos del jurado.** Va después y
  lleva su propio registro antes de entrenar: qué artículos se excluyen (los
  de las tandas 1 y 2), la muestra al azar de validación y la regla de
  adopción.
- **E. Los artículos que cita la base y no están en el corpus.** No se hace
  sin permiso del asesor: la lista de artículos citados sale de la base, y de
  la base solo salen conteos.

## Qué se reporta

Sobre la base completa, estrato «sin BioBERT», con el comando `contraste` de
`origin/main` y solo conteos:

- para A, B1 y B1+B2 (sobre la corrida 20 y sobre la corrida de A): las seis
  medidas de la línea base;
- para cada corte de D: aristas, recall dirigido y pares que la base no
  registra.

Los intervalos del contraste son optimistas: las filas de un mismo artículo
no son independientes y 5 artículos reúnen 672 filas exigibles.

## Cómo se lee

- **A** mejora si el recall dirigido y el techo suben. Se reporta también
  cuánto del aumento viene de artículos en versión enviada.
- **B1** mejora si el recall dirigido sube y la orientación no baja de 95.6 %.
- **B2** se compara contra la red (49.5 %) y contra «siempre activa»
  (74.9 %), las dos con abstención. Si no supera a «siempre activa», el
  resultado es ese: el signo sigue sin ganarle a la línea base.
- **La base mide cobertura, dirección y signo; no mide errores.** Un par que
  la base no registra puede ser una relación nueva. Los «pares que la base no
  registra» de cada corte se reportan como conteo, no como falsos positivos.
- Nada de esto cambia la red oficial (`corrida4_run22`) ni las cifras de las
  tandas del experto.

## Por qué no se parte la base en dos mitades

Cada opción lleva una sola regla, fijada aquí. No se elige entre variantes
mirando la base, así que no hay selección que proteger. Si después se quiere
barrer un umbral contra la base, antes se parte por artículo con semilla fija
y se registra aquí como enmienda.
