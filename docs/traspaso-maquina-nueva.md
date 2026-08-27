# Traspaso a otra máquina

Cómo levantar este proyecto en una computadora nueva y seguir donde se quedó.
Escrito el 21 de agosto de 2026, con el árbol en `adc7b93`.

**Lo primero, porque es lo que más se olvida:** clonar el repositorio no basta.
El código versionado pesa **780 KB**; los datos que necesita para funcionar pesan
**1.15 GB y están fuera de git**, a propósito. Si copias solo el repositorio,
tienes un programa que no puede correr.

---

## 1. Qué hay que llevarse

| qué | tamaño | ¿se puede regenerar? |
|---|---|---|
| El repositorio (`git clone`) | 780 KB | sí, está en GitHub |
| `datos/` — la base y los textos completos | **728 MB** | sí, pero son horas de descarga y tráfico a NCBI. **Cópialo** |
| `modelo_limpio_run22/` — el modelo entrenado | **415 MB** | sí, tres horas de GPU en Colab. **Cópialo** |
| `datos_etapa2/` — partición, caché del diccionario | 6.2 MB | en parte; ver abajo. **Cópialo** |
| `entity_marked_{train,dev,test}.jsonl` | 532 KB | **no.** Son del asesor |
| `ecoli_curated.tsv`, `bio_bert_re_finetune.py` | 428 KB | **no.** Son del asesor |
| `salidas/` — las diapositivas | 4 MB | no |
| `.key`, `.correo` | 2 KB | sí, se vuelven a escribir |

**Lo que sí conviene regenerar en vez de copiar:** nada. Todo lo regenerable es
determinista y reproduce el mismo archivo byte por byte, así que copiarlo ahorra
tiempo sin perder nada. Pero es útil saber qué *podrías* rehacer si algo se
pierde:

- `datos_etapa2/por_pmid/` sale de `particionar.py` con semilla 20260819, y
  reproduce los tres `.jsonl` exactos —siempre que tengas los originales del
  asesor.
- `datos_etapa2/cache_diccionario/` son las descargas de RefSeq, KEGG y UniProt.
  `construir_diccionario.py --sin-red` las usa para reproducir
  `etapa2/genes_pao1.tsv` byte por byte; está comprobado.

### La forma práctica de moverlo

Comprime todo lo que no está en git en un solo archivo y súbelo por separado:

```bash
tar czf grn_datos.tar.gz \
  datos/ datos_etapa2/ modelo_limpio_run22/ salidas/ \
  entity_marked_*.jsonl ecoli_curated.tsv bio_bert_re_finetune.py
```

Las credenciales **no van ahí**: se escriben a mano en la máquina nueva.

---

## 2. Cómo queda la máquina nueva

### Qué instalar

```bash
git clone https://github.com/MonkeyDMemo/download_abstract_pdf.git
cd download_abstract_pdf
tar xzf ../grn_datos.tar.gz            # los datos, al mismo nivel

python3 --version                       # 3.8 o mayor; aquí se usó 3.12.10
pip install torch transformers          # lo ÚNICO que hay que instalar
```

Esa última línea es la única dependencia del proyecto, y la necesita **un solo
archivo**: `etapa2/clasificar.py`. Todo lo demás corre con biblioteca estándar.

### Las credenciales

```bash
echo "TU_LLAVE_DE_NCBI"  > .key
echo "tu@correo.com"     > .correo
```

O como variables de entorno `NCBI_API_KEY` y `NCBI_EMAIL`, que ganan sobre los
archivos. Los dos archivos están en `.gitignore`.

### Qué tamaño de máquina

Conviene ser franco: **el atorón no era el tamaño de la computadora.** Era que
`torch` no estaba instalado. Con eso resuelto, una máquina modesta alcanza para
el paso siguiente.

| para qué | qué hace falta |
|---|---|
| Correr el pipeline completo una vez | CPU basta. 8 GB de RAM, 30 GB de disco. Tarda horas, pero termina |
| Que tarde minutos en vez de horas | Una GPU modesta. En AWS, `g4dn.xlarge` (T4) |
| Reentrenar el modelo | GPU de verdad, o seguir usando Colab, que ya está resuelto |

Son **65 223 pares candidatos** los que hay que pasar por el modelo. Esa es la
cuenta que decide si vale la pena la GPU.

---

## 3. Comprobar que quedó bien, antes de correr nada

Cuatro comprobaciones, en orden. Si alguna falla, no sigas.

```bash
# 1. El código está sano: 831 pruebas, menos de 10 segundos
python -m unittest discover           # → Ran 349 tests, OK
python -m unittest discover etapa2    # → Ran 482 tests, OK (skipped=3)

# 2. La base llegó completa
python cli.py estado
#    → 2 361 documentos, 2 354 con abstract, 5 331 vínculos, 6 consultas
```

Si `discover etapa2` reporta **0 saltadas** en vez de 3, es buena señal: quiere
decir que `torch` ya está instalado y las pruebas del clasificador corrieron.

```bash
# 3. El diccionario se reproduce desde el caché
python etapa2/construir_diccionario.py --sin-red --salida /tmp/genes.tsv
diff /tmp/genes.tsv etapa2/genes_pao1.tsv      # → sin diferencias

# 4. La partición se reproduce
python etapa2/particionar.py --por pmid --salida /tmp/particion
#    → "Particion limpia", contaminación 0.0 %
```

Las comprobaciones 3 y 4 son las que confirman que los datos llegaron íntegros.
Si el diccionario no reproduce byte por byte, el caché se corrompió en el
traslado.

---

## 4. El paso 1: la primera cifra sobre *P. aeruginosa*

Es lo único que falta para que el proyecto deje de tener un instrumento y pase a
tener una medición. **No falta escribir nada. Falta ejecutarlo.**

Las banderas de abajo están comprobadas contra el `--help` de cada programa el
21 de agosto de 2026. **Ojo con `clasificar.py`: su entrada es `--entrada`, no
`--pares`** —los otros tres sí usan `--pares`—.

```bash
# 1. los pares candidatos del corpus
python etapa2/extraer_pares.py \
    --salida  datos_etapa2/pares.jsonl \
    --informe datos_etapa2/pares_informe.json

# 2. el modelo les pone signo. LA PARTE LENTA
python etapa2/clasificar.py \
    --entrada datos_etapa2/pares.jsonl \
    --modelo  modelo_limpio_run22 \
    --salida  datos_etapa2/predicciones.jsonl \
    --meta    datos_etapa2/predicciones_meta.json \
    --dispositivo auto

# 3. se arma la red
python etapa2/red.py \
    --predicciones datos_etapa2/predicciones.jsonl \
    --pares        datos_etapa2/pares.jsonl \
    --salida       datos_etapa2/red.tsv \
    --informe      datos_etapa2/red_informe.json

# 4. se compara contra las 190 relaciones
python etapa2/evaluar_oro.py \
    --red          datos_etapa2/red.tsv \
    --pares        datos_etapa2/pares.jsonl \
    --predicciones datos_etapa2/predicciones.jsonl \
    --genes        etapa2/genes_pao1.tsv \
    --resumen      datos_etapa2/evaluacion_oro.json
```

### Dos banderas que importan en una máquina nueva

**`--reanudar`** en `clasificar.py` continúa una corrida a medias desde
`<salida>.parcial`. En una corrida de horas por CPU esto es la diferencia entre
perder el trabajo y no perderlo. Si se cae, relanza el mismo comando con
`--reanudar` añadido.

**`--dispositivo {auto,cpu,cuda}`** decide dónde corre el modelo. `auto` usa la
GPU si la encuentra. Si quieres comprobar primero que todo funciona, corre con
`--limite 200` para pasar solo doscientos pares y ver que la salida tiene buena
pinta antes de lanzar los 65 223.

### Qué esperar en cada paso

| paso | qué sale | cuánto tarda |
|---|---|---|
| `extraer_pares` | ~65 223 pares, ~1 935 entidades reconocidas por nombre | ~20 s |
| `clasificar` | una etiqueta y cuatro probabilidades por par | horas en CPU, minutos en GPU |
| `red.py` | las aristas, con su signo y su respaldo | segundos |
| `evaluar_oro` | la comparación contra las 190 relaciones | segundos |

### Sobre los umbrales

`red.py` decide qué evidencias cuentan con tres umbrales, y **mover esos umbrales
mueve el resultado entre 80.6 % y 93.8 % de exhaustividad sobre las mismas
predicciones**. Por omisión usa 0.65 / 0.70 / 0.60 y avisa en pantalla que son
los de omisión.

Si los cambias, `evaluacion_oro.json` **no los registra** —es uno de los cinco
huecos abiertos—, así que anótalos tú. Y si quieres calibrarlos con datos en vez
de a ojo, `clasificar.py --calibrar` los deriva de un conjunto etiquetado y
escribe un `umbrales_sugeridos.json` que `red.py --umbrales` sabe leer.

### Prepárate para que salga rechazado

Esto no es pesimismo, es cómo está diseñado. `evaluar_oro.py` exige que el
resultado **despegue de dos líneas base**: el azar y contestar siempre la clase
más común. Un modelo entrenado en *E. coli* bien puede no lograrlo en otra
especie.

**Si sale con código 2, el sistema funcionó.** Es la medición que este proyecto
existe para poder hacer, y un resultado negativo medido bien vale más que un
número bonito que no significa nada. Lo que no se vale es no correrlo.

### Guarda todo lo de la corrida

`red.py` deja un `red_informe.json` con qué archivos consumió y con qué umbrales.
**Guárdalo junto al resultado.** Hoy `evaluar_oro.py` no lo lee —es uno de los
cinco huecos abiertos— así que la trazabilidad depende de que tú lo conserves.

---

## 5. Lo que está pendiente, en orden

1. **Correr el pipeline** (arriba). Desbloquea todo lo demás.
2. **El brazo de control**: la misma partición repartida a nivel de ejemplo. Es
   lo único que permitiría atribuir la mejora contra 0.8721 a una causa y no a
   tres. No necesita GPU, necesita programarse en `particionar.py`.
3. **Varias semillas**: reentrenar la misma configuración la movió 0.0125 en
   prueba sin cambiar nada. Sin dispersión, el orden de la tabla de 24 significa
   menos de lo que parece.
4. **Cerrar los cinco huecos** documentados en `decisiones.md`, empezando por el
   más barato: que `evaluar_oro.py` exija que sus cuatro archivos vengan de la
   misma corrida.
5. **Anotar un conjunto de PAO1.** El cuello de botella real, y el único que no
   es problema de código.

### Sueltos, chicos

- **`verificar_oro.py` no está en el repositorio.** Se escribió un verificador
  que comprueba que cada oración del patrón de oro exista donde la fila dice, y
  vive fuera del árbol. Debería entrar, con una prueba que lo corra.
- **El informe dice «180 verificadas» y la cuenta independiente da 179.** Las dos
  que no cierran son ediciones menores —a una le quitaron las barras de error,
  otra está recortada—, no invenciones. Hay que corregir el número o documentar
  la diferencia.
- **Pendientes de las diapositivas**: la propuesta del ensamble con adjudicación
  en la lámina 11, el cuadro de «Aporte al diseño» donde GeneReL aparece como
  plantilla de pipeline con LLM cuando no se usó ningún modelo generativo, y la
  errata `Stepfucntions` en la lámina 2.

---

## 6. Trampas conocidas, para no tropezar dos veces

**El orden de las etiquetas está cruzado.** `bio_bert_re_finetune.py` trae
`LABELS_DEFAULT = [activates, represses, regulates, no_relation]` y el modelo
entrenado usa `[activates, no_relation, regulates, represses]`. Están
intercambiadas «reprime» y «sin relación». Por eso `particionar.py` escribe un
`label_mapping.json` en cada carpeta: **pásalo siempre al entrenamiento.**

**Reentrenar no es determinista, ni fijando la semilla.** La misma configuración
con la misma semilla y los mismos datos dio 0.9028 y 0.8903 en prueba. No es un
error: en GPU, la selección de núcleos de cálculo y las sumas del paso hacia
atrás no garantizan el mismo orden de operaciones.

**El programa detecta al tramposo torpe y no al cuidadoso.** Hay cinco maneras
conocidas de inflar una cifra que todavía funcionan, cada una con el ataque que
la demuestra en `decisiones.md`. Mientras sigan abiertas, una cifra de este
pipeline solo vale acompañada del registro de su corrida.

**No subas `datos/` ni el modelo a git.** Están en `.gitignore` por peso, y los
archivos del asesor además porque son trabajo de otra persona y el remoto es
público. Hay una prueba, `test_contaminacion.py`, que falla si el patrón de oro
se filtra donde no debe.

**Respeta los límites de NCBI.** El limitador de tasa vive en la instancia de
`pubmed.Cliente`, así que dos procesos en paralelo creen cada uno que respetan el
límite mientras el conjunto lo rebasa. NCBI bloquea por dirección IP: un proceso
mal portado deja sin servicio a todo el laboratorio. **En una máquina nueva y más
grande la tentación de paralelizar es mayor; no lo hagas hasta que exista el
limitador compartido.**

---

## 7. Por dónde seguir leyendo

| para qué | dónde |
|---|---|
| Entender el proyecto desde cero, sin dar nada por sabido | la página «El proyecto explicado desde cero» |
| El panorama completo con todas las cifras y sus fuentes | [`informe-seminario-1.md`](informe-seminario-1.md) |
| Por qué se decidió cada cosa como se decidió | [`decisiones.md`](decisiones.md) |
| El detalle de la contaminación, la partición y el barrido | [`../etapa2/README.md`](../etapa2/README.md) |
| Qué se heredó del servidor del asesor | [`ficha-modelo-bert.md`](ficha-modelo-bert.md) |
| Cómo se opera el ETL | [`../README.md`](../README.md) |
