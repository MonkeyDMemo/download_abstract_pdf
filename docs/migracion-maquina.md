# Mudanza a otra máquina

Cómo levantar este proyecto en una máquina virtual más grande, qué copiar, y
qué correr al llegar.

Escrito el 21 de agosto de 2026, con el proyecto en el estado que describe
[`informe-seminario-1.md`](informe-seminario-1.md).

---

## Por qué la mudanza

**El programa local de inferencia está escrito y probado, y nunca ha corrido
con el modelo real.** No existen `pares.jsonl`, `red.tsv` ni
`evaluacion_oro.json` en disco.

El motivo es concreto y no es de diseño: `etapa2/clasificar.py` es **la única
pieza del proyecto que necesita `torch` y `transformers`**, y en la laptop no
están instalados. Todo lo demás corre con biblioteca estándar.

**Medido el 21 de agosto en la laptop** (Ryzen 9 6900HX, 8 núcleos): son
**65 223 pares** y el clasificador va a 16-17 pares por segundo en CPU, o sea
**unos 70 minutos** para el corpus entero. No hace falta GPU: la GPU se
necesitó para el barrido, que ya cerró en Colab.

Y como la laptop lo hace en poco más de una hora, **la mudanza dejó de ser
necesaria para esto**. El documento se conserva porque sigue valiendo para
llevarlo a otra máquina cuando convenga.

---

## Qué tiene que viajar

El repositorio son 2 MB. Lo pesado está fuera de git a propósito.

| qué | tamaño | cómo llega | por qué no está en git |
|---|---|---|---|
| El repositorio | 2 MB | `git clone` | — |
| `datos/fulltext/` | **719 MB** | copiar | el corpus; se puede rebajar (ver abajo) |
| `datos/grn.db` | 8.4 MB | copiar | la base con 2 361 documentos |
| `modelo_limpio_run22/` | **415 MB** | copiar o bajar de Drive | pesos del modelo |
| `.key` y `.correo` | 64 bytes | **escribir a mano** | son credenciales |
| `datos_etapa2/por_pmid/` | 540 KB | copiar o regenerar | lo regenera `particionar.py` |

**Total: ~1.15 GB.** En una copia por red conviene comprimir `datos/fulltext`,
que son archivos de texto y bajan mucho.

### Si el ancho de banda aprieta

`datos/fulltext/` trae el JATS crudo (`.xml`) **y** el texto derivado (`.txt`).
Para correr la inferencia **solo hacen falta los `.txt`**: son los que lee
`extraer_pares.py`. Los `.xml` se conservan por si hay que reprocesar, pero se
pueden dejar atrás y bajar después. Eso recorta la copia a menos de la mitad.

`datos/grn.db` **sí es imprescindible**: de ahí salen los resúmenes, que son
parte del universo de evaluación.

### Las credenciales no se copian, se reescriben

`.key` y `.correo` están en el `.gitignore` y **no deben viajar en un archivo
comprimido ni por correo**. En la máquina nueva se vuelven a escribir, o se
ponen en `NCBI_API_KEY` y `NCBI_EMAIL`.

Solo hacen falta si se va a volver a descargar del PubMed. Para correr la
inferencia sobre el corpus que ya está, no.

---

## Montar la máquina nueva

```bash
git clone https://github.com/MonkeyDMemo/download_abstract_pdf.git
cd download_abstract_pdf

# el corpus y el modelo, copiados aparte
mkdir -p datos datos_etapa2
# ... copiar datos/fulltext, datos/grn.db, modelo_limpio_run22/

python3 -m venv .venv && source .venv/bin/activate

# La rueda de CPU son 122 MB. Sin --index-url, pip baja la de CUDA: 2.5 GB
# de los que aquí no se usa nada.
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers

python3 -m unittest discover           # 349, el ETL
python3 -m unittest discover etapa2    # 518, la etapa 2
```

**El entorno virtual no es preferencia, es necesidad en Windows.** El Python de
la Microsoft Store instala en
`AppData/Local/Packages/PythonSoftwareFoundation.../LocalCache/local-packages/`,
que son 138 caracteres antes de empezar; torch trae rutas de licencias anidadas
(`flash-attention/third_party/aiter/3rdparty/composable_kernel/docs`) y la
instalación muere con `WinError 206: el nombre del archivo o la extensión es
demasiado largo`. Un venv dentro del proyecto deja la ruta en 79 caracteres y
entra sin problema, **sin permisos de administrador**.

**Las 867 pruebas tienen que pasar antes de tocar nada.** Ninguna necesita
`torch` ni red: si alguna falla, el problema es de la copia, no del código.

### Versiones

Para el **barrido** hay que fijar `transformers==4.44.2`, `numpy<2` y
`pandas==2.2.3`; el porqué está en `../etapa2/README.md`. Eso vale para
reentrenar, que se hace en Colab.

Para **solo inferir** no hace falta fijar nada, y está comprobado: el
checkpoint carga sin problema con **torch 2.13.0+cpu y transformers 5.16.1**.
`clasificar.py` únicamente carga los pesos y llama al modelo, sin
`TrainingArguments` ni `Trainer`, que es donde estaban las incompatibilidades.

---

## Antes de correr: dos guardianes

Esto es lo más importante del documento y va antes de la primera corrida, no
después.

El informe declara que **hoy la misma red publica 80.6 % o 100.0 % de
exhaustividad según qué archivo se le ponga al lado, y sale con código 0**. Si
el programa se corre antes de arreglarlo, la primera cifra sobre
*P. aeruginosa* —la que va a encabezar el capítulo— puede salir equivocada por
veinte puntos sin que nada lo avise.

Es el mismo error que este trabajo vino a corregir: un número que se mide a sí
mismo. **El guardián tiene que existir antes que el número que protege**, porque
después ya se citó.

**Los dos que bloqueaban ya están puestos** (21 de agosto), antes de la primera
corrida y no después:

1. **La cadena.** `red.py` sella el sha256 de sus entradas y de su salida en
   `red_informe.json`, y `evaluar_oro.py` y `evaluar_signo.py` se niegan a
   correr si lo que van a leer no coincide. Vive en `etapa2/procedencia.py`.
2. **La cobertura del oro.** El indicador anterior era un cociente cuyo
   denominador crecía al contaminar, así que **bajaba** con un 12 % de filas
   copiadas. El nuevo mide contra el vocabulario del patrón, que es fijo:
   honesto 0.619, contaminado 1.000.

Los otros tres huecos —registrar umbrales y filas excluidas en el JSON, acotar
`--disputadas`— pueden esperar a después de la primera corrida.

### Y borrar un archivo

Ya está hecho, pero conviene saber por qué: `datos_etapa2/predicciones_meta.json`
era de una **prueba de humo con un modelo falso** —decía
`"transformers": "0.0-falso"` y 101 ejemplos— y se podía confundir con un
resultado. Si al copiar aparece otra vez, bórralo.

---

## El orden de ejecución

Cada paso escribe en `datos_etapa2/` y el siguiente lo lee. Los valores por
omisión ya apuntan a los archivos correctos, así que en el caso normal no hay
que pasar rutas.

```bash
# 1. Pares candidatos del corpus.  Sin torch, ~minutos.
python3 etapa2/extraer_pares.py
#    -> datos_etapa2/pares.jsonl, pares_informe.json

# 2. El clasificador.  ES EL UNICO PASO QUE NECESITA torch.
python3 etapa2/clasificar.py --modelo modelo_limpio_run22 --dispositivo cpu
#    -> datos_etapa2/predicciones.jsonl, predicciones_meta.json
#    Es reanudable: --reanudar retoma si se corta.
#    Conviene probar primero con --limite 200 y ver que el reparto de clases
#    no sea degenerado antes de soltar los 65 223. En CPU son ~70 minutos.
#    Con --avance 2000 imprime el ritmo y lo que falta.

# 3. Agregar las predicciones en aristas unicas.
python3 etapa2/red.py
#    -> datos_etapa2/red.tsv, red_evidencias.tsv, red_informe.json

# 4. Las dos evaluaciones.
python3 etapa2/evaluar_oro.py     # exhaustividad y acierto de signo
python3 etapa2/evaluar_signo.py   # oracion por oracion, las 93 evaluables
#    -> datos_etapa2/evaluacion_{oro,signo}.{tsv,json}
```

### Qué mirar en cada paso

**Después del 1**, `pares_informe.json`: cuántos pares salieron y qué fracción
del diccionario se usó de verdad. La corrida del 21 de agosto dio **65 223
pares** sobre 2 361 documentos, con 3 059 de las 8 743 entidades del
diccionario vistas en el corpus. Una desviación grande de ahí indica que el
reconocimiento cambió.

**Después del 2**, el reparto de clases del `predicciones_meta.json`. Un
clasificador que contesta casi siempre lo mismo es la señal de que el
checkpoint o el orden de etiquetas está mal. Ojo con esto último: el
`label_mapping.json` del checkpoint es
`["activates", "no_relation", "regulates", "represses"]`, y el
`LABELS_DEFAULT` del script de entrenamiento del servidor trae otro orden que
**intercambia `represses` con `no_relation`**.

**Después del 3**, `red_informe.json`: cuántas aristas quedaron y con qué
umbrales. Los de hoy son 0.65 / 0.70 / 0.60 y **no están calibrados**: vienen
del servidor sin justificación documentada.

**Después del 4**, la comparación contra la clase mayoritaria. `evaluar_oro.py`
la calcula sobre el mismo subconjunto que evalúa: si el modelo no le gana, la
cifra no vale. Un clasificador constante saca 69.8 % sin leer nada.

---

## Lo que queda pendiente después

En el orden que recomienda el informe, con un cambio:

1. **Explicar por qué el número subió** al quitar la contaminación. Es la
   pregunta más probable en la defensa y ya está medida la respuesta: de los
   116 ejemplos del test viejo con la ventana en entrenamiento, **86 tenían
   etiqueta compatible pero 30 la tenían distinta**, o sea que el 19 % del test
   castigaba al modelo por memorizar. El test contaminado no era solo más
   fácil: estaba en parte envenenado.
2. **La primera cifra sobre *P. aeruginosa*** — los cuatro pasos de arriba.
3. **El brazo de control** en `particionar.py`, para atribuir la diferencia
   contra 0.8721 a una causa y no a tres.
4. **Varias semillas** (`barrido.py --semillas 42,43,44`), en Colab. Reentrenar
   la misma configuración *con la misma semilla* la movió 0.0125 en prueba, así
   que las diferencias entre configuraciones vecinas están dentro del ruido.
5. **Anotar un conjunto de PAO1** por muestreo de incertidumbre. Es el trabajo
   de fondo y **conviene arrancarlo en paralelo desde ya**: es lo único cuyo
   plazo no se acorta metiéndole más máquina.

---

## Lo que la máquina nueva NO resuelve

Conviene decirlo para no esperar de más de la mudanza:

- **El conjunto anotado de PAO1** sigue necesitando a una persona leyendo.
- **`no_relation` no es una clase semántica** —485 de sus 493 ejemplos comparten
  ventana y par con una fila positiva— y eso no lo arregla ni más cómputo ni
  otra partición.
- **El barrido ya cerró.** No hay que repetirlo; los 24 resultados están en
  `etapa2/barrido_resumen.csv`.

La mudanza destraba una cosa concreta y bien acotada: poder correr el
clasificador. Es bastante, porque es lo que produce la primera cifra sobre la
especie de la tesis, pero no es todo.
