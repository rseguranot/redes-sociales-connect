# Vista nativa de agentes para WhatsApp

La vista se integra con el espacio de trabajo nativo de Amazon Connect. No exige
abrir la aplicación React ni iniciar una sesión administrativa adicional. Su guía
es independiente de la vista y del flujo telefónico.

## Contenido

- Último agente que respondió y fecha, obtenidos del historial persistido.
- Identidad `social_`, teléfono únicamente cuando Meta lo proporciona, datos
  declarados durante la conversación, servicio, factura, caso y solicitud.
- Mensajes disponibles de cliente, bot y agentes durante los últimos siete días,
  empezando por los más recientes. `Anteriores` permite recorrer el historial;
  `Actualizar / más recientes` reinicia la consulta.
- Los mensajes largos continúan en páginas sucesivas. No se resume el texto con
  IA. Los sobres JSON de menús se presentan como texto y opciones legibles.
- Los nombres de adjuntos se conservan cuando existen en el archivo; sus enlaces
  portadores no se publican. Los originales permanecen en Connect.

El historial comienza en la fecha de activación de su captura; no hay importación
retroactiva. La vista no recupera información que nunca se archivó. No debe
confundirse el último agente persistido con el agente asignado actualmente.

## Integración y seguridad

`NativeAgentView` es `AWS::Connect::View`. `NativeAgentGuide` usa ShowView y una
Lambda de solo lectura (`src/agent_view/app.py`). El evento `DefaultAgentUI` se
establece únicamente cuando `social_channel` es `whatsapp`. Las acciones y
transiciones anteriores del flujo se conservan.

La guía obtiene el contacto relacionado desde Amazon Connect y resuelve su
identidad mediante el mapeo inmutable `HISTORY_CONTACT#`. No acepta una partición,
nombre, teléfono ni token arbitrarios del navegador para buscar clientes. Consulta
solo ese ámbito empresarial/identidad, con corte de siete días, paginación y
permisos de DynamoDB limitados a las particiones de historial. La clave de cifrado
se permite exclusivamente para descifrar a través de DynamoDB. No tiene permisos
de escritura de clientes, envío de WhatsApp ni lectura de Secrets Manager.

El registro del flujo está desactivado; la Lambda no imprime eventos ni contenido.
Un error de carga muestra un aviso con reintento y no desconecta al cliente. La
guía es un contacto interno distinto; terminarla no termina el WhatsApp original.

## Despliegue

`scripts/deploy_native_agent_view.py` toma los nombres de stacks, perfil y cuenta
como argumentos. Lee las plantillas desplegadas, conserva parámetros, valida con
cfn-lint y consulta `describe-events` del change set. `--execute` ejecuta el plan;
`--include-direct-route` vincula además el ingreso directo del stack principal.
Los IDs de vista y guía se consultan en los outputs; no se publican en Git.

Se rechazan cambios ajenos, eliminaciones y reemplazos reales. La dependencia
condicional de la asociación Lambda se admite solo con plantilla de asociación y
nombre de función intactos, causada exclusivamente por la reevaluación de su ARN.
Se verifican los identificadores físicos después. Para el ingreso directo, la
reevaluación del ARN de flow en el procesador se admite únicamente con su recurso
intacto; código y configuración efectivos deben coincidir antes/después.

## Validación del 14 de septiembre de 2026

- Stack de chat y stack principal terminaron en `UPDATE_COMPLETE`. La ruta AI y
  la ruta de ingreso directo tienen el evento de guía exclusivo de WhatsApp.
  Código y configuración efectiva del procesador principal se verificaron sin cambios.
- 136 tests y 9 subtests: historial, aislamiento, paginación, mensajes largos,
  adaptador y procesador. La suite nueva es `tests/test_native_agent_view.py`.
- Vista publicada y reconocida en el editor nativo de Connect.
- Tres páginas del historial de una identidad privada autorizada validaron el
  esquema real de la vista y devolvieron mensajes y el campo de último agente.
- Una guía interna, sin cola ni streaming a Meta, vinculada al contacto de prueba
  emitió el mensaje interactivo de ShowView con historial, sin la vista de error.
  Se cerró exclusivamente esa guía; el chat de cliente no se cerró ni se le envió
  ningún mensaje. Esto verifica la ejecución de la guía, no la aceptación de un
  chat por un agente real.
- La primera publicación de la guía revirtió por un parámetro de invocación
  inválido. Se eliminó el valor literal vacío, se explicitó la invocación
  síncrona y se republicó. La consulta real detectó después la necesidad de
  `kms:Decrypt`, corregida mediante otro change set. No se sustituyó la vista de
  voz. Un grupo de logs vacío quedó retenido por la primera reversión.
- cfn-lint no informó errores en la versión final. Conserva una advertencia de
  dependencia redundante en la guía y las advertencias previas del stack principal.
  No se ejecutó cfn-guard: no estaba disponible; no se declara certificación de
  cumplimiento automatizada.

**Pendiente de aceptación:** un agente debe recibir un WhatsApp nuevo, comprobar
la apertura automática y recorrer `Anteriores` y `Actualizar` con el contacto
activo. Repetir con otro agente para confirmar la experiencia de transferencia.
Las sesiones previas que ya pasaron el punto de asignación de guía no se migran.

Referencias: [invocación de guías](https://docs.aws.amazon.com/connect/latest/adminguide/how-to-invoke-a-flow-sg.html),
[ShowView](https://docs.aws.amazon.com/es_es/connect/latest/devguide/participant-actions-showview.html),
[CloudFormation View](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-connect-view.html).
