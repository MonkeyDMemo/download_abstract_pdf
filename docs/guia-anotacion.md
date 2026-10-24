# Guía rápida para anotar

## Qué hay que hacer

Cada fila trae una oración de un artículo sobre *Pseudomonas aeruginosa* y dos entidades marcadas (entidad_1 y entidad_2). Juzga **solo lo que la oración afirma** sobre esas dos entidades.

- No uses lo que sabes del organismo ni consultes bases de datos, artículos o internet: la pregunta es qué dice la oración, no si es cierto.
- Si un caso te deja con dudas, decide lo mejor que puedas y explícalo en «comentario». Mejor no preguntarme caso por caso, para no influir en tu juicio.
- Cada campo tiene sus opciones: botones en la página web, o un menú en la hoja «Anotar» si usas Excel. Si usas el CSV, escribe exactamente esos valores.

## relacion: si / no / dudoso

- **si**: la oración afirma que una entidad cambia la expresión de la otra (su transcripción, su ARN, su proteína o la actividad de su promotor). Vale aunque lo dé por sabido («LasR, the activator of rhlR, …»). Vale para cualquier regulador: factor de transcripción, factor sigma, sistema de dos componentes o ARN pequeño.
- **no**:
  - interacción proteína-proteína;
  - cambio de actividad sin cambio de expresión (fosforilar, secuestrar);
  - las dos reguladas por un tercero;
  - solo correlación;
  - solo se mencionan juntas;
  - una entidad no es lo que parece (p. ej. «FLAG tag»: escribe «entidad mal reconocida»);
  - la oración **niega** el efecto (marca también negada = si).
- **dudoso**:
  - la relación aparece como posibilidad o pregunta («may», «might», «could», «putative», «whether…»): marca también especulativa = si;
  - se describe un experimento sin su resultado: comentario «sin resultado»;
  - la relación se atribuye a otro organismo: comentario «otro organismo: …»;
  - la oración afirma la unión al promotor pero niega el efecto: marca también negada = si.

## direccion: 1>2 / 2>1 / ninguna

- **1>2** si entidad_1 regula a entidad_2; **2>1** al revés; **ninguna** si relacion = no.
- Se anota como lo dice la oración, no según cuál sea el factor de transcripción.
- La voz pasiva no cambia la dirección: «Y is repressed by X» es X → Y.
- «Y depends on X», «X is required for Y expression» y «X-dependent expression of Y» son X → Y.
- Si la oración afirma las dos direcciones, anota 1>2 y escribe «recíproca» en el comentario.

## signo: + / - / ?

- **+**: el regulador activa, induce o aumenta la expresión, o es necesario para ella.
- **-**: el regulador reprime, disminuye o silencia la expresión.
- **?**: hay regulación, pero la oración no dice el sentido («regulates», «controls», «under the control of», «belongs to the X regulon», «binds the promoter» sin decir el efecto). **Usa «?», nunca 0.**
- Si el signo cambia según la condición, anota «?» y explícalo en el comentario.
- **Mutantes, ojo, porque la redacción invierte el signo:** «Y aumentó en el mutante de X» quiere decir que X reprime a Y (–). «Y disminuyó en ΔX» quiere decir que X activa a Y (+). «La sobreexpresión de X aumentó Y» es + y no se invierte.

## tipo: directa / indirecta / no_se

- **directa**: la oración dice que no hay intermediario. El regulador se une al promotor u operador del blanco (EMSA, huella o ChIP, con su resultado), o la oración dice «directly» o «direct target».
- **indirecta**: la oración nombra un intermediario («via», «through», «by inducing Z», «indirectly»).
- **no_se**: la oración afirma la regulación sin decir el mecanismo. **«X activates Y» sin más es no_se, no directa.** Lo mismo con «Y is X-dependent», un mutante o una sobreexpresión.

## negada: si / no

- **si**: la oración niega el efecto entre las dos («had no effect on», «unchanged in the X mutant», «not required for»). En ese caso relacion = no (o dudoso, si además afirma la unión al promotor).
- Lo negado tiene que ser el efecto: «LasR is not the only activator of rhlR» afirma la relación, así que va si y negada = no.

## especulativa: si / no

- **si**: con «may», «might», «could», «possibly», «likely», «putative», «we hypothesize» o una pregunta sin resultado. La relacion va dudoso.
- **no**: «show», «demonstrate», «indicate» y «suggest» en indicativo presentan una conclusión («These results suggest that X represses Y»). Con un modal («suggest that X may repress Y») sí es especulativa.
- Si la duda es solo sobre el mecanismo, la relación cuenta: «X activates Y, possibly by binding its promoter» es si, tipo no_se, especulativa no.

## Cómo queda cada fila

- **relacion = no**: direccion = ninguna; signo y tipo vacíos.
- **relacion = si o dudoso**: direccion, signo y tipo siempre con valor. Si la oración no lo dice, «?» y «no_se».
- **negada y especulativa** siempre con si o no.
- **comentario** es obligatorio si es dudoso, y cuando aplica otro organismo o cepa, recíproca, condición o entidad mal reconocida.

## Tiempo

En la página web el tiempo se registra solo. En Excel o CSV, anota la hora de inicio y de fin de cada bloque de 25 filas (en Excel, en la hoja «Tiempo») y apunta las pausas.

## Al terminar

- **En la página web:** pulsa «Exportar CSV» y mándame ese archivo. Lo que vas guardando se queda en tu navegador: si cambias de computadora, usa «Descargar respaldo» e «Importar respaldo».
- **En Excel:** guarda el archivo y mándamelo tal cual.

¡Mil gracias!
