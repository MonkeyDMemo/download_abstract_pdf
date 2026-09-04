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
