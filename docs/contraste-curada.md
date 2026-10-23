# El contraste con la base curada

Guía de `python -m grn_verificacion.cli contraste`
(`grn_verificacion/contraste.py`). Rehace la medición del 10-sep-2026
(PLAN.md 2.4) sobre cualquier carpeta del flujo, y le suma la red.

El contraste responde dos preguntas:

1. **¿Llega el paso 1 a la evidencia?** Es la cobertura del bronce: de las
   filas de la base, cuántas tienen sus dos locus juntos en una oración
   candidata.
2. **¿La recupera la red?** Es el recall de `red.tsv`: cuántas filas son una
   arista en la dirección de la base, cuántas solo al revés, y si el signo
   coincide.

Lo único que sale de la máquina es un informe en Markdown con conteos,
proporciones e intervalos. Lo que deriva fila por fila de la base se queda en
una carpeta confidencial, fuera de todo repositorio.

## Qué mide

### La cobertura del bronce: las reglas a) y b)

Una fila está cubierta cuando sus dos locus (`Source_Locus_id` y
`Target_Locus_id`) aparecen juntos en una oración candidata del bronce. La
coocurrencia no tiene dirección ni signo. Es el techo del paso 1: lo que no
coocurre en una candidata, el paso 2 no lo ve nunca.

- **Regla a)**: el par está en cualquier oración candidata del corpus. Mide lo
  que el paso 3 podría juntar sumando artículos.
- **Regla b)**: el par está en una oración candidata de un artículo que la
  fila cita. Mide si el paso 1 recupera la evidencia citada. En PLAN.md 2.4 la
  cifra a reportar es la b) con XML, con la a) como complemento.

Cada cifra sale como `k/n (porcentaje) [intervalo de Wilson al 95 %]`, con
`evaluar.proporcion`, el mismo cálculo que usa el 44 %.

### Los grupos

| grupo | qué filas |
|---|---|
| todas | todo el denominador |
| en el corpus | las que citan algún artículo que el bronce leyó |
| con XML | de esas, las que citan alguno del que el bronce tuvo el texto completo |
| solo abstract | las del corpus que no citan ninguno con XML |

El corpus es lo que dice el CSV de menciones del bronce (una cota inferior:
ver las cautelas). El CSV es el que nombra `estado.json` en
`archivos.candidatas`, con el sufijo de menciones en vez del de candidatas: la
carpeta guarda varios volcados fechados. Un artículo es «con
XML» si alguna de sus unidades viene del texto completo. Una fila con varios
PMIDs es «con XML» si alguno lo es: con uno basta para que el bronce haya
podido leer la evidencia completa.

### Con y sin la expansión de operones

**Con expansión**, los locus de una oración son `genes_locus_tag` más
`genes_expandidos`: un operón nombrado cuenta por sus genes. Así se midió
PLAN.md 2.4. La expansión aportaba 53 filas a la a) con XML: sin ella, la
cifra bajaba de 44.6 % a 37.9 %.

**Sin expansión** cuentan solo los genes que el texto nombra.

La expansión sale del catálogo y no del texto. Una oración que solo nombra
`mexAB-oprM` pone juntos a sus tres genes, así que una fila entre dos genes
del mismo operón queda cubierta sin que el texto la diga. El informe dice
cuántas filas cubre solo la expansión.

### La red: dirigido, al revés y el signo

Las aristas de `red.tsv` tienen nombres (`MexT`, `mexT`), no locus. Sus locus
salen de sus evidencias. Cada evidencia de `red_evidencias.tsv` trae un
`id_par`, y el par de `pares.jsonl` trae `tf_locus` y `target_locus`, con el
operón ya expandido a sus genes. Una arista hacia un operón da un par dirigido
por cada gen.

Por cada fila de la base:

- **dirigido**: la red tiene la arista regulador → blanco, como la base;
- **solo al revés**: la red solo tiene blanco → regulador. El par es correcto
  y la dirección no;
- **cualquier dirección**: una de las dos.

El signo se juzga en las filas dirigidas que tienen `+` o `-` en la base:
`+` contra activates y `-` contra represses. Un `?` no tiene signo con qué
comparar, y la `d` nadie ha dicho qué significa (PLAN.md, pregunta 3). Hay
dos resultados que no cuentan como acuerdo y se cuentan aparte:

- una arista `regulates`, sin signo resuelto;
- un par «mixto», cuyas aristas no dicen todas lo mismo. Pasa cuando el texto
  nombra al gen y a la proteína con signos distintos.

### Los estratos de `Origen`, y por qué BioBERT va aparte

El recall se reporta por estrato: Histórica, Ambos, otro y BioBERT. La cifra
principal es **«sin BioBERT»**, que junta los tres primeros.

Las filas con `Origen` BioBERT las propuso el modelo del asesor, entrenado con
la misma receta del run 22 que el modelo que clasifica los pares de la red.
Medir el recall de la red sobre ellas es medir al modelo contra sus propias
propuestas, y la cifra sale alta por construcción. Por eso van en su propio
estrato y nunca dentro de la cifra principal.

«Ambos» sí entra a la principal: la versión histórica de la base también
tiene esas filas, así que no dependen solo del modelo. Es el mismo criterio de
`datos-entrenamiento`, que excluye BioBERT de los positivos y deja entrar
«Ambos».

### Solo los artículos de test (`--solo-pmids`)

Sirve para una red armada con un modelo entrenado con la base, como
`curada-v1`. Ese modelo vio en el entrenamiento las oraciones de los artículos
de train y dev con la etiqueta que les da la base. El recall sobre esas filas
mediría memoria, no lectura.

Con `--solo-pmids`, el recall se calcula solo sobre los artículos de test, y
en las dos puntas:

- **Las filas de la base**: se evalúan solo las filas cuyos PMIDs están
  **todos** en el archivo. Una fila que cita un artículo de test y otro que no
  pudo entrar al entrenamiento por el otro. Queda fuera, y el informe la
  cuenta como «mezcla».
- **La red**: cuentan solo las aristas con evidencia en alguno de esos
  artículos.

Un límite que el informe repite: el signo de una arista lo decidió `red.py`
con todas sus evidencias, incluidas las de artículos de entrenamiento.

### Las candidatas nuevas

Son los pares de locus de la red que la base no registra en ninguna dirección
y en ninguna fila: tampoco en las de homología, las de BioBERT ni las del
artículo excluido. Son la parte de la red que la base no confirma ni
contradice, y la materia prima del paso 3. La lista es confidencial: su
complemento dice qué registra la base.

## El denominador

| | filas en PLAN.md 2.4 | por qué |
|---|---:|---|
| Base | 5 584 | |
| fuera por homología | 2 850 | el artículo citado no reporta la relación |
| fuera por el archivo de exclusiones | 731 | el artículo que el bronce no puede leer |
| **exigibles** | **2 003** | |
| en el corpus | 1 488 | |
| con XML | 791 | |
| solo abstract | 697 | |
| autorregulación | 43 | se quedan y nunca cuentan como cubiertas |

- **Homología.** La reconoce `validacion.py`: `Reference` dice «homolog». Con
  el texto completo a la mano, la regla b) cubría el 0.3 % de esas filas en
  la corrida 1, así que excluirlas es lo correcto. El informe repite ese
  contraste con la corrida que se mida.
- **El archivo de exclusiones (`--excluir-pmids`).** Por aquí llega el
  artículo de 731 filas que PLAN.md 2.4 llama «PMID B». Tiene PDF y no tiene
  XML, y el bronce no lee PDF: de ese artículo solo hay 6 oraciones de
  abstract. **Su PMID no se escribe en el repositorio** (que es público), ni
  en código, ni en pruebas, ni en documentos. Llega en un archivo con el
  formato de `reservas.tsv` que vive fuera del clon.
  - Sale una fila cuando todos sus PMIDs están en el archivo; una que cita
    también otro artículo se queda.
  - La homología se descuenta antes, como en PLAN.md 2.4.
  - Sin el archivo, el informe avisa que el denominador conserva esas filas.
- **Autorregulación.** Una fila «X regula a X» se queda en el denominador y
  nunca cuenta como cubierta. El bronce exige dos genes distintos por oración
  y `red.py` descarta la autorregulación. No es que no se encuentre: la regla
  la excluye por construcción.
- **Sin PMID.** La fila del DOI se queda. Sin artículo citado no hay regla b),
  y la fila cuenta fuera del corpus.

La columna de PLAN.md 2.4 es una referencia, no un criterio. Con otro corpus
cambian los artículos con XML, y una base nueva cambia todo. Si la carpeta es
de la corrida 1, el informe pone además la cobertura junto a la de PLAN.md
2.4 (857/2 003, 346/2 003, 239/791 y el resto de la tabla). Eso también es
comparación y no criterio: el diccionario y el lector pudieron cambiar desde
el 10-sep.

## Lo que sí detiene: el cotejo de la base

Antes de contar nada, la base se coteja contra `reentrenar.BASE_ESPERADA`,
que son los 14 conteos de PLAN.md 2.4 conciliados el 15-oct: filas, signo,
origen, homología, PMIDs distintos, filas sin PMID y DOIs. Si uno no
coincide, el contraste se detiene sin escribir nada. Las diferencias salen en
la terminal como conteos.

Puede ser otra versión de la base o el lector. Se decide con el asesor, y
seguir con `--aceptar-base-distinta` es una decisión que queda escrita en la
sección 1 del informe.

Otras dos guardas detienen el contraste:

- **Los pares no son los de la red.** `red_informe.json` sella la huella del
  `pares.jsonl` con el que se armó la red. Si no es la del `pares.jsonl` de
  la carpeta, se detiene: la unión por `id_par` no fallaría y llevaría las
  aristas a los locus de otro diccionario. Sin sello, avisa.
- **Faltan `id_par`.** Si un `id_par` de `red_evidencias.tsv` no está en
  `pares.jsonl`, también se detiene.

## Qué se publica y qué no

**El informe (`--informe`)** es lo único publicable. Antes de escribirse
pasa por `reentrenar.verificar_publicable`, el mismo filtro de
`RESULTADOS.md`: si trajera una ruta absoluta, un locus PA#### o un número con
forma de PMID, no se escribe nada. Los conteos van con los miles separados
por espacio, para que ninguno tenga siete u ocho cifras seguidas. Las líneas
de la terminal pasan por el mismo filtro.

**La carpeta confidencial (`--confidencial`)** tiene que quedar fuera del
repositorio y de cualquier copia de git: lo comprueba
`entrenamiento.exigir_fuera_del_repositorio`, y el mensaje de error no dice
la ruta. Se crea con permisos 700. Lleva tres archivos:

| archivo | qué lleva | por qué es confidencial |
|---|---|---|
| `cobertura_por_fila.tsv` | una fila por interacción de la base: fila de Excel, motivo (exigible, homología, excluida), locus, signo, origen, PMIDs, grupo, y qué la cubre (`a_` y `b_`, con y sin expansión; `red`, `red_signo`, `juicio_signo`; con `--solo-pmids`, `test` y `red_test`) | es la base fila por fila |
| `candidatas_nuevas.tsv` | los pares de locus de la red que la base no registra, con su signo, las aristas (por nombre) y los PMIDs | su complemento dice qué registra la base |
| `contraste.json` | los parámetros, las huellas de cada entrada (la de la base incluida) y el resultado en conteos | ata el informe a las entradas sin publicar la huella de la base |

Con `--sin-red` no hay `candidatas_nuevas.tsv`, y se borra el de una corrida
anterior: si se quedara, se leería como de esta.

Las rutas de `--base` y `--confidencial` no se imprimen nunca. Un error sale
por su mensaje filtrado, o solo por su tipo, y nunca como traceback.

## Cómo correrlo

Lo corre el usuario o, desde el 23-oct-2026, Hermes, la sesión de Claude del
usuario en el servidor, que entra por SSH con llave y tiene el VoBo del asesor.
Lo hace con los comandos de `docs/servidor-cierre.md` y reporta solo el informe
filtrado. La sesión de la laptop no lo lanza: prueba el código con la base
sintética de `grn_verificacion/test_contraste.py` y lee solo el informe. Nadie
abre la carpeta confidencial en una sesión, ni ajusta nada mirando lo que hay
en ella (`CLAUDE.md`, Confidencialidad).

Antes de darle la base, las pruebas con el mismo intérprete. Son datos
sintéticos y no leen la base:

```bash
$PY -m unittest grn_verificacion.test_contraste
```

### En el servidor del asesor

La base ya está ahí y el entorno es el de `entrenamiento-curada.md`
(`entorno.sh`, con `PY`, `RAIZ` y `BASE_CURADA`).

**1. La carpeta del flujo**, desde la laptop. Son salidas del corpus público.
Basta con estos archivos de la carpeta, por ejemplo
`salidas/flujo/corrida4_run22`:

- `estado.json`;
- los dos CSV del bronce que nombra `estado.json` (el de
  `_oraciones_candidatas.csv` y su `_menciones.csv`, con la misma fecha);
- `red.tsv`, `red_evidencias.tsv`, `red_informe.json` y `pares.jsonl`.

```powershell
$D = "salidas\flujo\corrida4_run22"
ssh asesor "mkdir -p grn-guillermo/flujo/corrida4_run22"
scp "$D\estado.json" "$D\red.tsv" "$D\red_evidencias.tsv" "$D\red_informe.json" "$D\pares.jsonl" asesor:grn-guillermo/flujo/corrida4_run22/
scp "$D\bronce_identificacion_corrida4_<fecha>_oraciones_candidatas.csv" "$D\bronce_identificacion_corrida4_<fecha>_menciones.csv" asesor:grn-guillermo/flujo/corrida4_run22/
```

**2. El archivo de exclusiones**, una sola vez, fuera del clon. El PMID lo
teclea el usuario. No va al repositorio ni a una sesión de Claude:

```bash
printf '# PMID B de PLAN.md 2.4\npmid\t%s\n' '<PMID B>' > "$RAIZ/excluir_pmid_b.tsv"
chmod 600 "$RAIZ/excluir_pmid_b.tsv"
```

**3. El contraste:**

```bash
cd ~/grn-guillermo/download_abstract_pdf && source ~/grn-guillermo/entorno.sh
$PY -m grn_verificacion.cli contraste --base "$BASE_CURADA" \
    --carpeta "$RAIZ/flujo/corrida4_run22" \
    --excluir-pmids "$RAIZ/excluir_pmid_b.tsv" \
    --informe "$RAIZ/resultados/contraste-corrida4/CONTRASTE.md" \
    --confidencial "$RAIZ/datos/contraste-corrida4"
```

`--base` sale de `BASE_CURADA` si no se da. Si la base no cuadra con PLAN.md
2.4, se detiene con código 1 y dice qué conteos difieren.

**4. El informe a la laptop.** Solo el informe:

```powershell
scp asesor:grn-guillermo/resultados/contraste-corrida4/CONTRASTE.md salidas\contraste\
```

### En la laptop

Si la base está también en la laptop, fuera del clon, el comando es el mismo
con rutas locales. La carpeta confidencial va fuera del repositorio: no sirve
`datos/` del clon, que está dentro.

```powershell
.venv\Scripts\python -m grn_verificacion.cli contraste --base "<ruta local del .xlsx>" `
    --carpeta salidas\flujo\corrida4_run22 `
    --excluir-pmids "$HOME\grn-confidencial\excluir_pmid_b.tsv" `
    --informe salidas\contraste\CONTRASTE.md `
    --confidencial "$HOME\grn-confidencial\contraste-corrida4"
```

### Con un modelo entrenado con la base

Para la red de un modelo como `curada-v1`, primero se arma su carpeta del
flujo con ese modelo. El archivo de `--solo-pmids` lleva los PMIDs del test de
la partición, con el mismo formato. Sale del test de la partición, que es
confidencial, así que se escribe en la carpeta confidencial:

```bash
$PY -c "import json, sys; ps = sorted({str(json.loads(l)['pmid']) for l in open(sys.argv[1]) if l.strip()}, key=int); open(sys.argv[2], 'w').write(''.join('pmid\t%s\n' % p for p in ps))" \
    "$RAIZ/datos/curada-v1/por_pmid/entity_marked_test.jsonl" "$RAIZ/datos/contraste-curada-v1/solo_test.tsv"
$PY -m grn_verificacion.cli contraste --base "$BASE_CURADA" \
    --carpeta "$RAIZ/flujo/corrida4_curada-v1" \
    --excluir-pmids "$RAIZ/excluir_pmid_b.tsv" \
    --solo-pmids "$RAIZ/datos/contraste-curada-v1/solo_test.tsv" \
    --informe "$RAIZ/resultados/contraste-curada-v1/CONTRASTE.md" \
    --confidencial "$RAIZ/datos/contraste-curada-v1"
```

Las cifras de la red completa salen igual, pero para ese modelo las que valen
son las de la sección «Solo los artículos de test».

### Códigos de salida

| código | qué pasó |
|---|---|
| 0 | terminó y escribió todo |
| 1 | se detuvo por un error, con el mensaje filtrado (un cotejo que no cuadra, una entrada que falta, la carpeta confidencial dentro de un repositorio, una red de otros pares) |
| 2 | falta `--base` y no hay `BASE_CURADA` |
| 3 | interrumpido |

## Cautelas

- **Es un piso.** Una mención que el bronce no llevó a locus no cuenta, y una
  relación repartida en dos oraciones tampoco. El 10-sep, 917 menciones (77 ids
  distintos) no se pudieron llevar a locus.
- **La concentración sesga.** Pocos artículos sostienen muchas filas: el
  10-sep, cinco PMIDs reunían el 32.1 % del denominador. El intervalo de
  Wilson trata las filas como independientes y por eso es optimista. El
  informe dice cuántas filas reúnen los cinco artículos mayores.
- **El reconocimiento de genes es por diccionario.** Produce falsos positivos
  y no sustituye al reconocimiento de entidades: una coocurrencia es un
  candidato, no una relación.
- **Un artículo sin ninguna mención** no aparece en el CSV de menciones, y sus
  filas cuentan como fuera del corpus. Por eso «en el corpus», calculado desde
  las menciones, es una cota inferior de lo que el bronce leyó: el corpus
  congelado puede tener artículos de más que no dejaron ni la mención del
  organismo.
