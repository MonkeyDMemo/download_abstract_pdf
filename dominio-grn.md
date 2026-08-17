---
inclusion: auto
name: dominio-grn
description: Contexto biologico del proyecto - Pseudomonas aeruginosa, redes de regulacion genica, nomenclatura de genes y factores de transcripcion, estructura de las consultas de PubMed. Usar al escribir queries booleanas, patrones de reconocimiento de genes, filtros de frases regulatorias o cualquier logica que dependa del significado biologico de los datos.
---

# Dominio: redes de regulacion genica

## El objetivo final

Una red de regulacion genica (GRN) es un grafo dirigido donde los nodos son
genes y las aristas son relaciones de regulacion: el factor de transcripcion
X activa o reprime al gen Y. Este ETL alimenta el proceso de extraer esas
aristas desde literatura sobre *Pseudomonas aeruginosa*.

Las tres clases de relacion que interesan:

| clase | significado | verbos tipicos en la literatura |
|---|---|---|
| `activator` | X aumenta la expresion de Y | activates, induces, upregulates, positively regulates |
| `repressor` | X disminuye la expresion de Y | represses, inhibits, downregulates, negatively regulates |
| `regulator` | X regula a Y, direccion no especificada | regulates, controls, binds the promoter of |

`regulator` no es un cajon de sastre: cubre los casos donde el articulo
establece la relacion sin resolver el signo. Perder esa distincion sesga la
red.

## Nomenclatura de genes

Convencion bacteriana estandar, relevante para cualquier reconocimiento por
patron:

- **Gen**: tres letras minusculas mas una mayuscula, en cursiva en el original.
  `lasR`, `rhlI`, `mexT`, `algU`, `pqsA`.
- **Proteina**: mismo nombre capitalizado, sin cursiva. `LasR`, `MexT`, `AlgU`.
  Son la misma entidad y deben normalizarse juntas.
- **Operon**: varias letras mayusculas o genes unidos con guion.
  `mexEF-oprN`, `pqsABCDE`.
- **Locus tag de PAO1**: `PA` mas cuatro digitos, de `PA0001` a `PA5570`.
- **Factores sigma**: `RpoS`, `RpoN`, `AlgU`, `FliA`, `SigX`. Regulan grupos
  completos de genes, asi que suelen ser hubs de la red.

## Limitacion conocida del reconocimiento por patron

Cualquier heuristica basada en estas formas produce falsos positivos: palabras
comunes de cuatro letras con la misma silueta caen en el patron. Es un punto
de partida aceptable para filtrar frases candidatas, **no** un sustituto de
reconocimiento de entidades.

Al escribir codigo que dependa de esto, dejarlo explicito en el docstring. La
sustitucion prevista es un diccionario derivado de Pseudomonas Genome DB, o un
modelo de reconocimiento de entidades biomedicas.

Esta limitacion es conocida en la literatura del area: la dependencia de
diccionarios predefinidos es el cuello de botella de escalabilidad de estos
pipelines.

## Estructura de las consultas de PubMed

Las consultas del proyecto siguen un patron de dos bloques unidos por `AND`:

1. **Organismo**: `"Pseudomonas aeruginosa"[Mesh]` mas variantes en titulo y
   resumen, incluida la abreviatura `"P. aeruginosa"[TiAb]`.
2. **Concepto regulatorio**: disyuncion larga de terminos `[TiAb]` que cubre
   regulacion transcripcional, factores sigma, sistemas de dos componentes,
   reguladores de respuesta y quorum sensing.

Notas practicas:

- `[Mesh]` busca en terminos indexados; `[TiAb]` en titulo y resumen. Se usan
  juntos porque la indexacion MeSH tarda meses y deja fuera lo mas reciente.
- Singular y plural son terminos distintos en PubMed. Hay que enumerar ambos:
  `"regulon"[TiAb] OR "regulons"[TiAb]`.
- Las consultas rebasan los 700 caracteres, por eso van en archivos bajo
  `queries/` y se envian por POST.

Al proponer variantes de consulta, mantener el patron de dos bloques y
verificar el conteo con `esearch` antes de descargar nada.

## Cobertura de acceso abierto

Se espera que solo una fraccion de los resultados tenga texto completo
disponible. Buena parte de la literatura clasica de regulacion bacteriana esta
en revistas de suscripcion. El resto se exporta como lista de pendientes.

Esto no es un defecto a resolver con mas ingenieria: es una restriccion del
dominio que hay que medir y reportar, no rodear.
