# Plan de tesis: el LLM en la plata, y la puerta que decide si entra

Del 22 de octubre de 2026. **Es plan de la tesis, no del servicio social, y no
es un protocolo pre-registrado.** Nada de esto corre antes del cierre técnico
del 4 de noviembre. Cuando la tesis arranque, se convierte en protocolo, con
fecha y commit antes de correr ningún modelo, como `protocolo-curada-v1.md` y
su enmienda 1. Por qué el LLM salió del servicio social está en
`decisiones.md`, en la entrada «El LLM sobre la oración es trabajo de tesis».

## De dónde sale

Una revisión externa de la arquitectura multiagente del Documento de Tesis v1
(22-oct) y el cálculo de potencia de abajo. Resumen de lo que quedó:

- **Las herramientas deterministas se quedan:** locus, TF, operón y GO son
  búsquedas exactas. Los LLM solo leen la oración.
- **Un agente entra solo si quitarlo empeora una métrica medida.** Hoy serían
  un lector sobre el residuo y un juez.
- **AgentCore y Gateway son despliegue, no ciencia:** van a trabajo futuro,
  con el servicio actualizable.
- **El veredicto cita su evidencia por offsets de la oración.** Una
  comprobación determinista verifica que el fragmento existe y contiene el
  disparador, con los offsets de `menciones`. El motivo en prosa es un
  complemento.
- **El juez es local y de otra familia que el extractor y que Claude.** Las
  182 de la trampa, la rúbrica y la calibración se prepararon con Claude, y
  esa es la misma objeción que limita el 91.4 %.

## La puerta

1. **Selección.** Cinco modelos abiertos, con el mismo prompt, sobre las 182
   oraciones del conjunto ciego de la trampa del signo. Gana el de mayor
   acierto de signo en sus 93 evaluables. Las 182 ya están gastadas por el
   91.4 % y se usan solo para elegir.
   - **Desempate por hardware:** si el mejor que cabe en la RTX 3070 (8 GB,
     cuantizado) queda a 5 puntos o menos del ganador, se elige el local. Así
     regenerar los veredictos no depende de EC2.
   - **Sin EC2,** la puerta corre igual con el mejor modelo local.
2. **La puerta se decide en una muestra ciega nueva,** nunca en la que eligió
   el modelo. Los ítems son los `si` con signo `+` o `-`.
   - **La abstención cuenta como error.** Es lo que vive el curador. Los ítems
     comunes se reportan aparte y no deciden.
   - **Referencias:** «siempre activa», el control léxico y el BioBERT de
     *E. coli*. El criterio contra cada una está por decidir: ver «Abierto».
   - **Guarda de existencia:** si la precisión de existencia de lo que el
     agente acepta es peor que la del bronce, con el límite superior del IC de
     la diferencia bajo 0, no pasa aunque gane en el signo.
   - **Tres resultados:** pasa, no pasa y no concluyente. Un resultado no
     concluyente se reporta así, con su n y su potencia, y nunca como «el LLM
     no sirve».
3. **El juez:** κ ≥ 0.60 contra la etiqueta adjudicada en 100 aristas, y solo
   si el κ entre humanos de la parte doble llega a 0.60.
4. **La caché:** cada veredicto se guarda con la huella de todo lo que lo
   decide:
   - la oración marcada;
   - el modelo y la huella de sus pesos;
   - la cuantización;
   - el motor y su versión (Ollama o vLLM);
   - el prompt;
   - la temperatura, la semilla, top_p y el máximo de tokens.

   Es el patrón de la caché del BioBERT (`grn_verificacion/puente.py`). La red
   se reconstruye desde los veredictos guardados: regenerar puede variar,
   reconstruir no.

## El cálculo de potencia (22-oct), y por qué no cabe en el servicio social

El cálculo corre en la laptop, sin modelos ni red. Simula la prueba pareada
de la puerta: un modelo con 85 % de acierto contra una referencia, con
correlación ρ entre los aciertos de los dos, IC 95 % normal de la diferencia y
4 000 repeticiones.

- **Cuántos ítems salen.**
  - Población: 5 833 oraciones con regulador y blanco.
  - Solo el 16.6 % trae un `signo_sugerido` léxico sin ambigüedad (632 `+` y
    336 `-`).
  - De 200 oraciones al azar, con una precisión de 44 a 54 % y la oración
    fijando el signo en el 40 a 60 % de las verdaderas, quedan **unos 35 a
    65 ítems.**
- **Potencia contra «siempre activa» (0.75):**

  | ítems con signo | ρ = 0 | ρ = 0.2 | ρ = 0.4 |
  |---:|---:|---:|---:|
  | 50 | 0.24 | 0.32 | 0.41 |
  | 80 | 0.35 | 0.43 | 0.54 |
  | 110 | 0.46 | 0.56 | 0.69 |
  | 140 | 0.56 | 0.66 | 0.79 |

- **Para 0.8 de potencia con 10 puntos de ventaja (0.85 contra 0.75):** hacen
  falta 150 ítems con signo (ρ = 0.4), 200 (ρ = 0.2) o 250 (ρ = 0).
- **Con 15 puntos de ventaja (0.85 contra 0.70),** unos 100-110 bastan.

La muestra de 200 del servicio social da la precisión con ± 6.8 puntos. **No
alcanza para decidir el signo.** La puerta necesita un estrato aparte de
oraciones con disparador con signo, que son el 43 % de la población:
- unas 300 oraciones más llevan a unos 150-170 ítems con signo;
- ese estrato solo decide la puerta y no entra a la precisión general.

## Abierto, para cuando arranque la tesis

- **El criterio frente al BioBERT de *E. coli*.** Su signo en el patrón de oro
  es 87.6 % (92/105). Exigirle superioridad puede volver la puerta
  inalcanzable aunque el LLM ayude. La alternativa es no inferioridad, con un
  margen fijado de antemano, más superioridad contra «siempre activa» y el
  control léxico.
- **Quién anota el estrato y la parte doble.** Con un solo anotador no hay κ.
- **El experimento central de la tesis: esfuerzo y confianza.** Curadores
  revisan aristas con y sin el veredicto y la evidencia del agente, y se mide:
  - el tiempo por arista;
  - el acierto;
  - cuántas veces aceptan un veredicto equivocado, que es el sesgo de
    automatización.

  Responde a «¿acelera la curación?», que ningún F1 responde solo.
