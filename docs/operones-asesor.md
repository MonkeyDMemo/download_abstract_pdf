# Operones: qué se hizo y qué falta decidir

Para el Dr. Edgardo Galán-Vásquez. Estado al 20 de octubre de 2026.

Este documento resume el trabajo de operones y lista lo que queda por decidir.
Lo técnico está en otros dos:
- [`guia-operones.md`](guia-operones.md): cómo se mantiene y cómo se regenera
  en otra máquina;
- [`catalogo-operones.md`](catalogo-operones.md): cada fuente, qué se tomó y el
  diccionario de datos.

---

## 1. En corto

- **Hay dos catálogos de operones, con papeles distintos** (sección 2). El
  del paso 1, de 3 030 operones, **detecta**. La base de operones, de 4 250
  unidades, **anota**.
- **La base es casi toda predicción:** 4 102 de 4 250 unidades (96.5 %).
- **En la corrida 4 del bronce**, 23 445 de las 29 659 oraciones candidatas
  tienen al menos un operón, nombrado o por pertenencia de sus genes.
- **Quedan decisiones suyas** (sección 7) y una pregunta para cerrar la
  decisión 3 (sección 8).

Tres nombres que conviene no mezclar:

| nombre | qué es | qué contiene |
|---|---|---|
| base de operones | la construye el paquete `grn_operones` desde las cuatro fuentes | qué genes se transcriben juntos |
| patrón de oro | `oro_pseudomonas.tsv`, armado por el equipo | 190 relaciones regulador → blanco, 181 de ellas atestiguadas en el corpus |
| base curada | GRN_experimental, del laboratorio | la red regulatoria: 5 584 interacciones |

En este documento, «oro» es el archivo de 190 relaciones y «base curada» es
GRN_experimental.

## 2. Dos catálogos, dos papeles

| | catálogo del paso 1 | base de operones |
|---|---|---|
| de dónde sale | genes consecutivos del GFF de RefSeq, en la misma hebra y con nombres que componen la cadena | ODB, BioCyc/PseudoCyc y Pseudomonas Genome DB; CDBProm marca promotores |
| tamaño | 3 030 operones | 4 250 unidades, 1 576 de más de un gen |
| para qué sirve | reconocer `mexEF-oprN` como una unidad y expandirla a PA2493, PA2494 y PA2495 | decir a qué operones pertenecen los genes de una oración |
| está en el repositorio | sí | no: lleva datos de BioCyc, cuya licencia restringe redistribuirlos |

Los dos son predicción en su mayor parte. Coinciden exactamente en genes en
325 unidades. Por qué no se juntaron está en la sección 6.

## 3. Las cuatro fuentes

| fuente | qué aporta | cómo entró | cuánto |
|---|---|---|---|
| ODB v4 | operones conocidos, cada uno con su artículo | el volcado de texto del propio sitio; su tabla paginada es una aplicación de JavaScript que no trae datos | 33 operones de PAO1 |
| BioCyc / PseudoCyc | unidades de transcripción: unas pocas experimentales y casi todas predichas por Pathway Tools | la API oficial, con cuenta | 3 774 unidades |
| Pseudomonas Genome DB | predicciones de DOOR y operones de literatura de PseudoCAP | la exportación de su curador, publicada por el laboratorio Greene y fijada a una versión | 1 290 operones, foto del 19 de julio de 2021 |
| CDBProm (IIMAS) | promotores predichos | el archivo por organismo que ofrece el sitio, bajado a mano | 1 950 promotores; marca operones, no los crea |

Las ligas exactas de cada fuente están en
[`fuentes-operones.md`](fuentes-operones.md): la que pidió el encargo, de la
que de verdad se bajó y por qué.

Del sitio de Pseudomonas Genome DB no se pudo sacar nada. Está detrás de un
desafío de Cloudflare, su `robots.txt` prohíbe la recolección automatizada y no
ofrece un archivo de operones. La exportación de su curador es la tabla que
alimenta la vista de operones de la página. Comparada con la captura de la
página de *metG*, coincide campo por campo, salvo la descripción y el tipo de
cada gen: esos no vienen en la tabla y salen de RefSeq.

## 4. Las cifras de la base

| | valor |
|---|---|
| unidades | 4 250, de ellas 1 576 de más de un gen |
| conocidas / curadas / predichas | 145 / 3 / 4 102 |
| con dos o más fuentes | 738 (717 de ellas, BioCyc y Pseudomonas Genome DB) |
| con promotor de CDBProm en el primer gen transcrito | 1 574 |
| marcadas para revisar a mano | 81 (eran 117; ver la nota de abajo) |
| alternativas (contenidas en otra unidad) | 1 072 |
| usadas para anotar el bronce | 1 219 |
| iguales en genes a un operón del catálogo del paso 1 | 325 |

Tres cautelas al leerlas:

- **«Dos o más fuentes» no es «dos confirmaciones independientes».** DOOR y
  Pathway Tools son predictores distintos, pero los dos parten de la distancia
  entre genes. Además, ODB, BioCyc y PseudoCAP pueden citar el mismo artículo.
- **Las 1 219 unidades que anotan** son las de más de un gen que no están
  contenidas en otra, más 32 alternativas de más de un gen cuya evidencia no
  es solo predicción.
- **Las que hay que revisar bajaron de 117 a 81 el 20 de octubre.** La
  revisión de adyacencia ignoraba el sufijo de los genes anotados después
  (`PA4277.1`, `PA4277.2`…), y marcaba como «no consecutivos» a 38 grupos que
  sí lo son. No cambió ninguna unidad, solo la marca.

## 5. Cómo entran al pipeline

- **Detección, en el paso 1.** Solo usa el catálogo del paso 1. En la corrida
  4 hay 7 136 menciones de 363 operones distintos.
  - 260 de esos operones están en el catálogo.
  - 103 no están, con 447 menciones.
  - Un operón que el catálogo no conoce no se expande a nada y queda en la
    lista de huecos.
- **Anotación, también en el paso 1.** La base agrega dos columnas a cada
  oración candidata: si tiene operón y cuáles.
  - 23 445 candidatas tienen al menos uno. Solo nombrando operones eran 3 603.
  - No cambia lo que se detecta: las 28 columnas que ya existían salieron
    idénticas.
- **Capa del paso 2, rehecha el 20 de octubre.** De los 72 969 pares que vio
  el clasificador, 3 422 tienen como blanco un operón y 38 307 tienen el
  blanco dentro de un operón de la base. De sus 22 267 oraciones, 17 326
  tienen operón. Antes decía 3 605: contaba como operón a IHF, PrrF y PrrH,
  que no tienen locus tag en el diccionario.
- **Entrenamiento con la base curada.** Si el blanco de un par es un operón
  del catálogo del paso 1, el par se compara con la base curada gen por gen.
  La base de operones no interviene.
- **Evaluación.** Se expande el nombre que escribió la referencia, nunca por
  deducción el que produjo el pipeline.
  - Contra el patrón de oro, 4 de las 190 relaciones coinciden por operón.
  - En la auditoría de signo, 8 de 93 oraciones se unen así, dos por cada uno
    de cuatro operones (`mexAB-oprM`, `mexCD-oprJ`, `mexJK` y `mexXY`). Por
    ejemplo, el auditor escribió `mexAB-oprM` y el pipeline nombró `mexA`.

**La pertenencia a operones no es un rasgo del paso 2.** No entra al
clasificador ni decide nada mientras siga abierta la decisión 3.

## 6. Lo que decidimos por nuestra cuenta

1. **Un paquete aparte, con cinco tablas**, que guarda lo que dijo cada
   fuente, con la huella de cada archivo, y la versión curada. El encargo
   pedía meterlo en el paquete de extracción, que está cerrado, y dentro del
   bronce habría tapado el módulo que ya expande los operones.
2. **Normalizar a locus tag con el diccionario del proyecto** (RefSeq, KEGG y
   UniProt) y no con la anotación de pseudomonas.com, que no se puede
   descargar.
3. **Pseudomonas Genome DB por la exportación de su curador.** Sacarlo del
   sitio exigiría evadir el desafío de Cloudflare.
4. **CDBProm marca y no cuenta como fuente de operones.** Da un promotor
   frente a un gen, no un operón. Contado como fuente, fabricaría 1 950
   «operones» de un gen, o haría parecer confirmado por dos fuentes cualquier
   operón con promotor.
5. **La base anota y no detecta.** Se midió el 27 de septiembre, antes de
   decidir, y las tres variantes de meterla al detector salieron peor:
   - Sumar los 71 operones con nombre de literatura resolvía 1 de los 103
     faltantes y metía 208 menciones casi todas falsas. Psl, el polisacárido,
     aportaba 155, y «amidase», 22.
   - Sumar las 1 200 unidades con nombre se comía 343 menciones de genes y
     proteínas: «CbrA-CbrB» pasaba a ser un operón y el paso 2 perdía
     regulador y blanco.
   - Reemplazar el catálogo perdía entre 3 251 y 4 554 de las 6 689 menciones
     que hoy se resuelven.
6. **El archivo de la base para el bronce no va al repositorio**, que es
   público: lleva datos de BioCyc. Cada máquina lo genera.

## 7. Lo que falta que usted decida

D1 a D7 conservan la numeración de la reunión del 25 de septiembre. D8 y D9 son
nuevas. Las recomendaciones son nuestras, y la decisión es suya.

**D1. El patrón de locus tag.** ¿Se aprueba `^PA\d{4}[a-z]?(\.\d+)?$`?
- Recupera los 58 locus que hoy quedan fuera. Entre ellos está *crcZ*
  (PA4726.11): nombrado por su locus, hoy sale como su regulador *cbrB*.
- Recupera también los 22 promotores de CDBProm con sufijo de letra.
- *Recomendación:* aprobarlo, en un cambio propio con el antes y el después.
- *Costo:* regenerar el diccionario, una corrida nueva del paso 1 y recalcular
  tres cifras: la normalización a locus tag (95.1 %), la cobertura del patrón
  de oro (84.7 %) y la precisión de la muestra de 50 (44.0 %).

**D2. Las 16 unidades de BioCyc con cita y sin código de evidencia.** ¿Son
conocidas o predichas?
- *Recomendación:* dejarlas como predichas mientras usted no las revise. La
  lista, con título, año, revista y tipo de cada uno de sus 21 artículos, está
  lista.
- Va con otra pregunta. Hoy los PMIDs se toman de toda la unidad, promotor
  incluido, y 16 de las 64 unidades con PMID lo traen solo por su promotor.
- *Recomendación:* tomarlos solo de la cita de la propia unidad, porque la
  evidencia de un promotor no es evidencia de la unidad. Antes, medir cuántas
  conocidas cambian.

**D3.** En la sección 8.

**D4. CDBProm.** ¿Se valida cómo entró?
- El archivo trae dos discrepancias:
  - el encabezado dice F/R y los datos traen D/R;
  - fin menos inicio da 80 en todas las filas (81 pb contando los dos
    extremos), y la secuencia mide 60 nt.
- Y una pregunta: cuando dos unidades con los mismos genes tienen promotores
  distintos, ¿se agrega el inicio de transcripción a la identidad de la
  unidad?
- *Recomendación:* dejar la identidad por genes, sin inicio de transcripción.
  - Las fuentes de operones, tal como entraron, no traen ese inicio.
  - La pertenencia, que es para lo que se usa la base, no depende de él.
- *Recomendación:* confirmar las dos discrepancias con los autores de
  CDBProm.

**D5.** Superada: Pseudomonas Genome DB entró por la exportación de su curador.

**D6. Tres decisiones propias.** ¿Las valida?
- las cinco tablas;
- el paquete aparte;
- normalizar con el diccionario del proyecto.

*Recomendación:* validarlas tal cual. Las razones están en la sección 6.

**D7. Los 103 operones del corpus que faltan en el catálogo del paso 1**
(*cyaAB*, *exoSTY*, *rsmZY*, *phzMS*, *lasRI*, *sodAB*…).
- *Recomendación:* no agregarlos.
  - Los mayores no son operones: son genes separados en el genoma que el
    texto abrevia juntos. *exoSTY* son PA3841, PA0044 y PA2191.
  - Solo 3 de los 103 tienen su conjunto exacto en la base de operones.
  - Agregarlos metería uniones que no se transcriben juntas.
- Se quedan como lista de huecos.

**D8 (nueva). Contar la literatura por artículo único.** Hoy dos fuentes que
citan el mismo artículo cuentan como dos respaldos.
- *Recomendación:* una columna nueva con los PMIDs distintos, conservando la
  del número de fuentes.

**D9 (nueva). Los operones en la red final.** Cuando una oración dice que un
regulador actúa sobre un operón, ¿la arista va al operón o a cada uno de sus
genes?
- *Recomendación:* expandir a cada gen con el catálogo del paso 1, como se
  acordó el 11 de septiembre (la relación alcanza a todos los genes del
  operón).
- Conservar la arista original como procedencia y marcar las expandidas,
  porque ese catálogo es predicción y una expansión falsa mete aristas falsas.
- Cómo se compara después contra la base curada depende de la decisión 3.

## 8. Decisión 3

**Estado.** Decisión 3 (abierta): respuesta verbal, probable (semana del 5 al
9 de octubre de 2026). GRN_experimental es la red regulatoria y no una fuente
de operones. Falta confirmar por escrito si alguna relación se amplió por
pertenencia a operón; hasta entonces la pertenencia solo anota.

**Por qué importa.** Puede que alguna relación de GRN_experimental se haya
ampliado por pertenencia a un operón, tomada de ODB, BioCyc o Pseudomonas
Genome DB. En ese caso, usar esa misma pertenencia como rasgo del paso 2 sería
evaluar al clasificador con la fuente que construyó la referencia. La cifra
saldría igual de bien presentada y mediría otra cosa.

**La pregunta**, reescrita el 21-oct-2026 para hacerla en persona en la
reunión del viernes 23-oct. La versión anterior empezaba por «la base de
operones es una cosa y GRN_experimental otra». Eso invitaba a repetir la
respuesta verbal, que dice qué es cada base, pero no cómo se construyó la
curada. La nueva parte de un precedente conocido: una parte de la base ya se
infirió, por homología.

> Dr. Galán, sobre cómo se construyó la base curada (GRN_experimental):
> sabemos que 2 850 de sus filas se infirieron por homología desde PA14.
> ¿Hubo también filas inferidas por pertenencia a operón? Es decir, si un
> artículo dice «LasR activa el operón rhlAB», ¿se registró solo lo que dice
> el artículo, o también una fila por cada gen del operón (LasR → rhlA y
> LasR → rhlB), sacando los genes de ODB, BioCyc o Pseudomonas Genome DB?
> Basta con sí, no o no lo sé.

**Qué cambia con cada respuesta:**

| respuesta | qué hacemos |
|---|---|
| no | Se cierra. La pertenencia puede entrar como rasgo del paso 2 y la guarda por procedencia deja de hacer falta |
| sí | La pertenencia sigue solo como anotación. Las filas ampliadas se identifican y se apartan al evaluar y al entrenar, y una guarda impide usar esa fuente como rasgo |
| no lo sé | Todo sigue como hoy: la pertenencia anota y no decide |

## 9. Correcciones a lo que se dijo el 25 de septiembre

- **Los operones con promotor no eran 1 350.**
  - El promotor se buscaba frente al primer gen de la lista, y BioCyc lista
    los genes en orden descendente de locus en las dos hebras. En 515 de 1 082
    operones ese no era el primer gen transcrito.
  - Corregido, con las mismas tres fuentes, son 1 390. Con Pseudomonas Genome
    DB, 1 574.
- **Pseudomonas Genome DB y BioCyc no comparten Pathway Tools.** Pseudomonas
  Genome DB predice con DOOR. Cuentan como fuentes distintas, y lo que sí
  comparten es la literatura.
- **La regla de evidencia de BioCyc es otra:**
  - «conocido» exige un código experimental y además un PMID;
  - con código experimental y sin PMID, la unidad es «curada»;
  - una predicción computacional con cita sigue siendo predicha, porque la
    cita suele ser la del método.
- **La decisión 5 quedó superada:** Pseudomonas Genome DB entró por la
  exportación de su curador.
- **La base no va a sustituir al catálogo del paso 1.** Ese día se dijo que
  convivían «todavía»; se midió y no conviene (sección 6).
- **La hebra se comprueba también en un clon limpio.** Ese día se dijo que no.
  Desde el 20 de octubre sale primero de la copia versionada del genoma, que
  está en todo clon; la local queda de respaldo, y hoy las dos son idénticas.
- **La decisión 3 se reformuló** para incluir Pseudomonas Genome DB y para
  preguntar por la ampliación por operón (sección 8).
