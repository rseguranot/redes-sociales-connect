# Integración con Amazon Connect

## Componentes

La integración usa:

- `StartChatContact` para crear el chat con identidad, primer mensaje y atributos.
- `StartContactStreaming` para publicar mensajes del agente en un tema SNS.
- Connect Participant para continuar la conversación y recuperar adjuntos.
- Un módulo de flow que marca la versión del contexto social.
- Un contact flow mínimo administrado o un flow existente del negocio.
- Una cola de Connect existente, incluida en el routing profile de los agentes.
- Una aplicación AppIntegrations opcional para Agent Workspace.

`ApplicationSecurityProfileIds` concede visibilidad `ACCESS` sobre esa aplicación de forma aditiva. No autentica llamadas a la API administrativa ni sustituye el adaptador SSO requerido para producción.

## Flow inicial administrado

Cuando `CreateDefaultContactFlow=true`, CloudFormation crea un flow mínimo:

```text
Inicio
  └─► Invocar módulo de contexto
        └─► Establecer cola de trabajo
              └─► Transferir a cola
                    └─► Finalizar en error/desconexión
```

Requiere `ConnectQueueId` y el módulo administrado. Este flow sirve para una instalación reproducible y pruebas básicas. Un negocio puede sustituirlo por un flow propio con bots, horarios, atributos, enrutamiento o automatización; en ese caso configure `CreateDefaultContactFlow=false` y `DefaultContactFlowId` con un flow publicado.

`ManagedContactFlowName` y `ConnectContextModuleName` no reciben el valor de `Environment` automáticamente. Incluya el ambiente en esos nombres si `dev` y `prod` comparten instancia. Ambos recursos administrados usan `DeletionPolicy: RetainExceptOnCreate` y `UpdateReplacePolicy: Retain`: un rollback de la creación inicial los elimina, pero una eliminación o reemplazo posterior los conserva y puede provocar colisión de nombre al recrearlos; decida de forma explícita si se reutilizan, importan, renombran o eliminan manualmente.

Los archivos [context-module.json](../connect/context-module.json) y [default-contact-flow.example.json](../connect/default-contact-flow.example.json) son referencias legibles. La versión desplegada se encuentra también en `template.yaml`; evite editar una copia y olvidar la otra.

## Módulo de contexto

El módulo administrado establece:

| Atributo | Valor | Propósito |
|---|---|---|
| `social_context_version` | `1.0` | Versión del contrato esperado por el flow |
| `social_context_status` | `READY` | Evidencia de que el módulo se ejecutó |

La identidad ya llega en `StartChatContact`; el módulo no debe sustituirla con valores fijos. Colóquelo al principio de cualquier flow personalizado, antes del bot, condiciones o transferencia.

## Atributos entregados al contacto

### Contrato recomendado

| Atributo | Contenido |
|---|---|
| `social_schema` | `social-message/1.0` |
| `social_provider` | Adaptador, actualmente `meta_direct` |
| `social_channel` | Canal, actualmente `whatsapp` |
| `social_business_id` / `social_account_id` | ID de la WABA (`entry.id`) |
| `social_asset_id` | ID del número emisor (`metadata.phone_number_id`) |
| `social_user_id` | Identidad canónica del cliente |
| `social_parent_user_id` | Identidad padre si Meta la entrega |
| `social_username` / `social_handle` / `customer_handle` | Username cuando existe |
| `social_message_id` / `source_message_id` | ID estable del mensaje de origen |
| `social_display_name` / `customer_name` / `customer_display_name` | Nombre a presentar al agente |
| `social_phone` / `customer_phone` | Teléfono cuando Meta lo entrega |
| `initial_message` | Primer contenido visible, sujeto al límite de Connect |
| `campaign_id` | Campaña asociada, si existe |
| `button_id` | Opción interactiva seleccionada, si existe |
| `routing_rule` | Razón de una ruta especial, si aplica |

### Alias de compatibilidad

`nombre`, `nombres`, `telefono`, `whatsapp_phone`, `wa_user_id`, `wa_username`, `whatsapp_message_id`, `chatframework_Channel` y `chatframework_VendorId` se mantienen para flows existentes. Los flows nuevos deben preferir el contrato recomendado.

Un atributo puede estar vacío porque Meta no entrega siempre teléfono, username o nombre. Nunca use el nombre como clave única; use `social_user_id`.

## Uso de variables en un flow

Amazon Connect resuelve atributos antes de que el texto salga del bloque:

```text
Hola $.Attributes.customer_name,
recibimos tu solicitud desde $.Attributes.social_channel.
```

Si `customer_name` vale `Cliente de ejemplo`, el mensaje entregado será:

```text
Hola Cliente de ejemplo,
recibimos tu solicitud desde whatsapp.
```

Defina una rama de fallback cuando un dato opcional esté vacío. No muestre la expresión literal al cliente.

## Enrutamiento

La selección ocurre al abrir una sesión nueva, en este orden:

1. Un teléfono incluido explícitamente en `DevelopmentPhoneNumbers` usa `DevelopmentContactFlowId`.
2. Una respuesta a botón con ruta guardada usa el `contact_flow_id` de esa campaña.
3. Los demás contactos usan el flow predeterminado efectivo.

Una conversación ya abierta continúa en su contacto actual; no debe reiniciarse solo para cambiar de flow. Para pruebas repetibles cierre la sesión/contacto anterior y espere que expire o use una identidad de prueba nueva.

La allowlist de desarrollo es temporal. Use números E.164 normalizados, una cola aislada y un agente de prueba; elimine la excepción al terminar.

## Colas y routing profiles de Connect

CloudFormation puede crear el flow, pero reutiliza una cola de Connect existente. Antes del corte:

- la cola debe estar activa;
- debe pertenecer al routing profile del agente;
- el canal chat debe tener concurrencia disponible;
- el agente debe usar ese routing profile y estar disponible;
- horarios y transferencias del flow deben cubrir el momento de prueba.

Si el contacto aparece en cola pero no llega al agente, revise primero routing profile, estado, concurrencia y cola; no asuma que el webhook falló.

## Streaming SNS

La Lambda inicia streaming por contacto hacia `ConnectStreamingTopicArn`. La política del tema permite publicar únicamente al servicio Connect desde la cuenta/instancia esperada. SNS entrega a la cola puente SQS y la Lambda procesador transforma mensajes del agente a Meta.

Un mensaje entrante puede llegar correctamente aunque el streaming saliente falle; por eso la prueba debe ser bidireccional.

## Adjuntos de agentes

Connect debe permitir la extensión enviada y disponer de almacenamiento `ATTACHMENTS`. El procesador recupera el adjunto, valida tamaño/MIME, lo carga a Meta y envía el tipo compatible. Una extensión visible en el selector no garantiza que Meta acepte el códec.

Son dos configuraciones distintas:

- `CreateConnectAttachmentsStorage=true` crea `AWS::Connect::InstanceStorageConfig` de tipo `ATTACHMENTS` en el bucket multimedia. No lo active si la instancia ya tiene una configuración de ese tipo.
- `ConnectChatAttachmentExtensions` hace que `scripts/configure_connect_attachments.py` añada extensiones permitidas al alcance `CHAT` sin retirar las existentes. No crea almacenamiento y no garantiza compatibilidad del archivo con Meta.

## Verificaciones útiles

```powershell
aws connect describe-instance `
  --instance-id "ID-DE-INSTANCIA" `
  --profile "mi-perfil" `
  --region us-east-1

aws connect describe-contact-flow `
  --instance-id "ID-DE-INSTANCIA" `
  --contact-flow-id "ID-DE-FLOW" `
  --profile "mi-perfil" `
  --region us-east-1

aws connect describe-queue `
  --instance-id "ID-DE-INSTANCIA" `
  --queue-id "ID-DE-COLA" `
  --profile "mi-perfil" `
  --region us-east-1
```

Use comandos de lectura durante diagnóstico. No publique ni sobrescriba un flow manualmente si CloudFormation es su propietario.
