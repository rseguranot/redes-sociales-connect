# QA conversacional de WhatsApp — 2026-09-11

Pruebas con identidad protegida y datos ficticios. Sin transferencia a agentes
reales, sin modificaciones del canal de voz y sin publicar datos operativos.

## Evidencia de WhatsApp real

| Recorrido | Resultado observado |
|---|---|
| Queja de servicio: clasificación, nombre, teléfono, sucursal, fecha, área y despedida | Completado. Una ejecución de la herramienta de correo con marca QA y una aceptación de SES; sin errores de validación. |
| Nombre ficticio inicialmente rechazado | Reproducido, corregido y repetido: ahora solicita teléfono. |
| Queja parcial → menú → información general → promociones | Corregido y repetido: solicita producto, sin volver al agente de quejas ni cerrar. No generó un segundo correo. |
| Información general → sucursales → La Romana → horario → otra consulta | Completado; lista y botones nativos, formato con negrita y viñetas, retorno al menú sin cierre. |
| Promociones → producto | Respondió opciones de catálogo. Esto no demuestra una promoción vigente ni inventario por sucursal. |
| Estatus con factura ficticia inexistente → representante | Indicó ausencia de información; cierre protegido sin transferencia real. No certifica un pedido válido. |
| Reclamación sin factura | Ofreció documentos alternativos. Se identificó y retiró el atajo que transfería al detectar un documento sin consultar el backend. |
| Reclamación con caso ficticio, después de corregir | Pidió confirmación, invocó `/getClaim` y respondió que no encontró el caso. Solicitó identificación para continuar con uno nuevo. Sin invocación de `/createClaim` en el intervalo revisado. |
| Cancelación de reclamación sin identificación | Confirmó cancelación y se despidió, sin inventar un cliente ni crear un caso. |
| Inicio después de cierre | El primer mensaje abre el menú; no se certifica resolución del contenido inicial. |

## Cambios exclusivos de chat

- Reconocer preguntas de nombre como «cómo te llamas» y «cómo se llama».
- Enviar la respuesta al nombre como dato JSON contextualizado, no como consulta nueva.
- Reiniciar contexto de negocio y sesión Bedrock al volver al menú/información general;
  conservar identidad y configuración técnica de Connect.
- Eliminar del entrypoint de chat la transferencia inmediata por documento de reclamación.
- No insinuar registro exitoso ante excepción en la rutina de finalización de quejas.

Publicación por change sets revisados del stack independiente. Sin cambios del
stack principal, webhook, agentes Bedrock compartidos ni herramientas compartidas.
Hashes del flow y hook de voz comparados con el estado anterior: sin cambios.

## Validación automatizada

- 129 tests y 9 subtests offline aprobados.
- Smoke Lex de información general, producto con marca/medida/sucursal, menú,
  entradas de estatus/reclamación/queja y cierre de representante.
- Ocho sucursales × horario/dirección/menú: 24 turnos Lex con comprobaciones.
- Regresiones Lex de nombre y cambio de tema aprobadas.
- cfn-lint sin hallazgos; cuatro reglas Guard de aislamiento aprobadas.
- `describe-events` sin errores de validación antes de ejecutar cada change set.

Los probes reproducibles están en `scripts/qa_chat_paths.py`. No sustituyen
WhatsApp E2E ni prueban la exactitud comercial actual de horarios/precios.

## Límites del reporte y pendientes

La herramienta de quejas genera correo: su identificador calculado no constituye
por sí mismo un registro persistido en CRM. SES aceptó el envío, pero no se ha
comprobado recepción en el buzón final. La herramienta compartida mantiene logs
detallados con datos personales; se inspeccionaron solo contadores/indicadores
del test y no se modificó esa función por afectar otros consumidores.

Reclamaciones tiene herramientas Salesforce de búsqueda, consulta y creación.
La consulta de solo lectura `SELECT IsSandbox FROM Organization LIMIT 1` devolvió
`IsSandbox = false`: el destino Salesforce es producción, pese al nombre dev de
la Lambda. En la primera ronda no se ejecutó `/createClaim`; la excepción
posterior autorizada para un cliente/caso ficticios se documenta abajo.
La consulta positiva de pedidos/facturas continúa pendiente: un caso CRM
de prueba no equivale a un pedido comercial de prueba.
La transferencia protegida conserva dos mensajes: anuncio y aclaración de prueba.
No están cubiertos aquí multimedia, CCP real, mensajes fuera de ventana, carga,
duplicados de webhook ni todas las posibles formulaciones de lenguaje natural.

## Creación y consulta CRM con autorización posterior explícita

Después de informar que Salesforce era producción y que se enviaría un correo
automático, el usuario autorizó expresamente crear un cliente ficticio y un caso
marcado PRUEBA QA NO PROCESAR. Esta excepción no convierte el destino en dev ni
autoriza reutilizar clientes reales como datos de pruebas.

- Se creó por API un Person Account exclusivo de QA, con identificador
  alfanumérico ficticio de tipo pasaporte y sin teléfono ni correo de personas.
  Se comprobó ausencia de colisión antes de crear y cero casos iniciales.
- Desde WhatsApp: reclamación → producto Sí → identificador QA → confirmación →
  cliente encontrado sin casos → nueva reclamación → descripción ficticia → fecha.
- El bot creó un solo caso por la herramienta normal. La consulta directa de
  Salesforce verificó persistencia, vínculo al cliente QA, origen Amazon connect
  y estado Abierto. No se usó una creación directa por API para simular éxito E2E.
- Los registros de ejecución mostraron una creación completada y un correo
  automático enviado, sin fallo de notificación. Esto prueba aceptación por SES,
  no entrega/lectura en el buzón final.
- El bot conservó que el televisor y el incidente eran ficticios, pero omitió la
  etiqueta literal PRUEBA QA de la descripción. Se reforzó por API únicamente
  el asunto y descripción del caso QA creado; no se modificaron registros reales.
- Desde WhatsApp se consultó el caso recién creado: respondió su estado abierto,
  motivo, descripción ficticia y ausencia de taller/resolución.

El cliente y el caso QA se conservan, marcados NO PROCESAR, para pruebas futuras.
No se borraron registros. Los identificadores operativos y los scripts de manejo
del fixture permanecen en el directorio local ignorado `.aws-sam`, fuera de Git.
En esta ronda no se cambió infraestructura, código del bot, voz ni agentes compartidos.

## Ampliación: cédula sintética, entrega, instalación y presentación

Ronda posterior con autorización explícita para continuar QA. Se creó otro
Person Account ficticio, con tipo Cédula e identificador sintético exclusivo,
sin teléfono ni correo reales. No representa una cédula legal válida: únicamente
prueba la búsqueda de ese campo en CRM. Dos candidatos de marcador genérico
colisionaron con registros existentes y fueron descartados sin reutilizarlos;
se comprobó ausencia de colisión antes de crear el fixture definitivo.

| Prueba real en WhatsApp | Resultado |
|---|---|
| Cédula con guiones → confirmación larga | Primera confirmación pidió repetir; se reprodujo con texto sin guiones y confirmación corta. No se atribuye el fallo solo a los guiones. |
| Cédula sin guiones → «Sí, es correcto» después del ajuste | Cliente encontrado, con su reclamación existente. |
| Nueva reclamación de entrega → descripción → fecha | Caso persistido en Salesforce con motivo Entrega y estado Abierto. |
| Nueva reclamación de instalación → descripción → fecha/hora | Caso persistido con motivo Instalación y estado Abierto. |
| «Quiero consultar el caso…» | Antes del ajuste se confundió con factura; después pidió confirmación y recuperó el caso de entrega. |
| Número equivocado → botón No → número correcto → botón Sí | Recuperó el caso de instalación; no cerró al rechazar el primer número. |
| Consulta de horarios y botón Ver dirección | Respuestas correctas para la sucursal seleccionada; negrita, lista y separación de líneas renderizadas. |
| Consulta libre multilínea con negrita, viñetas y cursiva | WhatsApp renderizó el mensaje de prueba y el bot interpretó correctamente la consulta de horario. La cursiva se observó en el mensaje entrante; negritas/viñetas también en respuestas del bot. |
| Estatus por lista → factura inexistente | Informó ausencia de información y pidió revisar el número. |
| Corrección explícita desde factura a caso | Cambió a reclamaciones, confirmó el número y recuperó el caso QA de entrega. |
| Estatus con factura real, lectura autorizada posteriormente | La API respondió HTTP 200 y WhatsApp mostró factura finalizada. No afirmó entrega física; no se modificó el pedido. |
| Solicitud de representante después de consulta positiva | Anuncio seguido de aclaración de prueba y cierre protegido. Continúan siendo dos mensajes; no certifica transferencia a agente real. |

Los dos casos nuevos fueron creados por el recorrido normal de WhatsApp, no por
una inserción directa para simular éxito. Se verificaron contra el Account QA.
En el intervalo de creación aparecieron dos registros de notificación aceptada,
sin certificar recepción en el buzón. El modelo omitió la etiqueta QA literal
en la descripción de instalación; se reforzaron por API asunto/descripción de
los casos propios. Siguen abiertos y marcados NO PROCESAR. No se alteraron
clientes reales ni se borraron registros. La conservación determinista de la
etiqueta QA por la herramienta compartida sigue siendo una limitación.

### Ajustes publicados solo en el adaptador de chat

- Confirmaciones explícitas «¿Es correcto?» presentan botones Sí/No reutilizando
  el DSL existente; preguntas abiertas no reciben botones binarios arbitrarios.
- Frases inequívocas como «Sí, es correcto» se normalizan solo cuando la pregunta
  previa es de confirmación. Negaciones y respuestas con correcciones se conservan.
- Consultas explícitas y acotadas de número de caso se dirigen a reclamaciones,
  reiniciando el contexto de factura cuando corresponde y conservando identidad.
- Preguntas se separan con una línea en blanco; `**negrita**` se adapta a
  `*negrita*` de WhatsApp; `_cursiva_` y viñetas se preservan.
- La repetición de voz del número de caso se sustituye por un único identificador
  en negrita solo cuando ambas secuencias coinciden, conservando ceros iniciales.
- Respuestas de cierre reciben formato básico, pero no nuevos botones.

Dos change sets revisados del stack independiente: único cambio directo en
código de ChatAdapter y referencias dependientes de alias/permisos/asociación.
Sin reemplazos ajenos ni modificaciones del stack principal o agentes compartidos.
Ambos stacks UPDATE_COMPLETE; hashes del flow y hook de voz sin cambios.
Validación: 136 tests + 9 subtests, cfn-lint sin hallazgos, cuatro reglas Guard,
smoke Lex de seis escenarios, nombre, cambio de tema y ocho sucursales × tres pasos.

### Datos de pedidos y autorización posterior de lectura real

El estatus de pedidos invoca una API de entregas distinta de Salesforce. Crear
un cliente o caso en CRM no crea un pedido en esa API. Inicialmente se solicitó
una factura exclusiva de QA. El usuario autorizó después consultar datos reales;
la excepción se limita a lectura, sin borrar ni modificar los pedidos utilizados.
Una búsqueda acotada de facturas marcadas con entrega encontró un registro que
la API reconoce con HTTP 200 y estatus de factura cliente finalizada. No se
publican sus identificadores ni los datos personales. Las pruebas de escritura
siguen limitadas a clientes/casos ficticios propios.
La consulta positiva se completó también en WhatsApp y coincidió con ese estado.
No se borraron facturas, pedidos ni datos reales. Que la factura esté finalizada
no certifica por sí solo entrega física. No se probaron todos los estados posibles
de pedido (pendiente, ruta, devolución, cancelación, etc.).
La reentrada tras cierre puede abrir el menú sin procesar el contenido inicial;
se observó una vez tras registro y no se atribuye a una causa confirmada.
