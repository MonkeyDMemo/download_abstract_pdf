# Protocolo: lo que se mide en la tanda 2

Pre-registro de la tanda de prueba de la muestra ciega (rúbrica, enmienda 2).
Se commitea **antes** de correr cualquier medición sobre la tanda 2, y antes de
que una sesión de Claude vea un solo conteo suyo. Cualquier cambio posterior va
al final, como enmienda con fecha, y dice si es anterior o posterior a ver
alguna cifra.

## La muestra

- **De dónde sale:** 200 ítems de `salidas/revision/muestra200_t2/`, con la
  semilla 20261023. La población es de 2 670 oraciones, sin los artículos, los
  códigos ni las copias de las oraciones de la tanda 1.
- **Quién y cómo anota:** el experto, en la página de revisión, con la rúbrica
  v1 y sus enmiendas 1 y 2, después de la sesión «Calibración 2». La página
  registra el tiempo por ítem y rechaza `si` con `negada = si`.
- **Lo que no se hace:** nada se ajusta mirando la tanda 2. Ni reglas, ni
  umbrales, ni el prompt, ni el diccionario.

## Lo que se mide

**1. Las redes, con `precision-ciega` sobre la misma anotación.**

| red | cómo se arma | papel |
|---|---|---|
| oficial (`red.tsv`) | `red.py`, como hoy | la principal de la entrega |
| recomendada | `consolidar --perfil recomendado` | secundaria |
| `signo` | `consolidar --signo-lexico evidencias --voto-articulo --nombre signo` | **la principal del signo** |
| `signo_conservador` | `--signo-lexico aristas --voto-articulo` | secundaria |
| `signo_lexico` | `--signo-lexico evidencias`, sola | secundaria |
| `signo_articulo` | `--voto-articulo`, sola | secundaria |

Las redes de signo se arman en la laptop, sobre la carpeta de la corrida 4,
**antes** de que el experto termine la tanda 2. Sus huellas se anotan aquí en
una enmienda, antes de medir.

**Lo que hace cada regla** (`grn_red/signo.py`, `decisiones.md`):

- **`--signo-lexico evidencias`** da un voto léxico a cada evidencia que
  BioBERT dejó `regulates`. Es el control del punto 18 (`signo_cercano`).
- **`--signo-lexico aristas`** solo vota en las aristas sin ningún voto con
  signo de BioBERT. Los conflictos de `red.py` (votos + y − de BioBERT) no se
  tocan.
- **`--voto-articulo`** decide las aristas con votos + y −. Cada artículo vota
  por mayoría, y la arista va con la mayoría de los artículos. Si todos los
  artículos se abstienen, la arista sigue `regulates` y con `conflicto` = sí.

**Las comparaciones principales**, fijadas desde ya:

- **La precisión con dirección:** la red oficial contra el bronce, como en la
  tanda 1. Es la que confirma o no la tanda 1 sobre datos de prueba.
- **El signo:** `signo` contra la red oficial, sobre los mismos ítems, con la
  abstención como error y la diferencia pareada por bootstrap. Las dos redes
  tienen las mismas aristas y solo cambia el signo, así que la base es la
  misma.
- **Lo demás es secundario,** y se reporta sin elegir después la que mejor
  salga.

**De cada red se reporta:**
- la precisión con dirección del bronce (los 200) y de la red (los ítems cuya
  oración sostiene una arista), con su IC de Wilson;
- la diferencia pareada por bootstrap;
- la retención, del total y de las verdaderas;
- las inversiones;
- el acierto de signo con la abstención como error, «cuando lo da» y
  **«siempre +» sobre la misma base**.

**2. Ouroboros v0** (`grn_ouroboros`, exploratorio). El prompt se congela con un
commit y su huella antes de correr sobre la tanda 2.

| corrida | configuración | papel |
|---|---|---|
| principal | sin think, T = 0, semilla 42, `num_ctx` 4 096, `num_predict` 512, sin herramientas | la que se reporta primero |
| con think | T = 0.6, top_p 0.95, top_k 20, `num_ctx` 8 192 (q8_0 si no cabe), `num_predict` 4 096 | secundaria |
| con herramientas | la principal con `--herramientas todas` (o `buscar_locus`, si las demás no llegaron) | secundaria |
| tres semillas | la de think con las semillas 42, 43 y 44, si hay tiempo | variabilidad |

**De cada corrida se reporta** (`cli concordancia`):
- el acuerdo con el experto por campo;
- el κ en `relacion`;
- las matrices de confusión;
- las abstenciones, contadas como error;
- los fragmentos inválidos, marcados y no borrados;
- el tiempo por ítem;
- Ouroboros como filtro: su precisión y su retención frente al bronce.

## Sensibilidades, declaradas desde ya

- **Modelos entrenados con la base (curadas v1 y v2):** sin los ítems de
  artículos de su train ∪ dev (`precision-ciega --particion`, en el servidor).
  *E. coli*, con la misma exclusión, para comparar sobre los mismos ítems.
- **La página impide la negada anotada `si`,** así que la sensibilidad de la
  tanda 1 («negadas como `no`») debería dar 0 cambios. Se reporta igual.
- **El campo `tipo`** se compara sin salvedad en la tanda 2: la calibración 2
  repasó «activates» → `no_se`.

## Lo que no se puede concluir

- Una sola anotadora, sin κ entre humanos.
- Los intervalos tratan las oraciones como independientes. La tanda 2 no
  repite artículos de la tanda 1, pero varias oraciones de un mismo artículo
  sí pueden caer juntas.
- Ouroboros es exploratorio: su cifra no entra a la red ni a la entrega.
