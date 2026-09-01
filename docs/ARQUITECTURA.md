# Arquitectura

## Objetivo

La plataforma traduce eventos sociales a un contrato interno estable y los entrega a Amazon Connect. WhatsApp Cloud API es el adaptador implementado. AWS SNS, SQS y Lambda transportan eventos internos; **SNS no es el proveedor de WhatsApp**.

## Recorrido cliente → agente

1. Meta envía un webhook HTTPS a API Gateway.
2. La Lambda de ingreso valida `X-Hub-Signature-256` con `WA_APP_SECRET`. El `GET` de alta se valida con `WA_VERIFY_TOKEN`.
3. Cada unidad se encola en la FIFO de conversaciones. La conversación es el grupo de mensajes y el ID estable del proveedor participa en la deduplicación.
4. La Lambda procesador normaliza el evento a `social-message/1.0`, reclama el ID para idempotencia y recupera o crea la sesión de chat.
5. `StartChatContact` entrega el primer contenido y los atributos normalizados al contact flow. Para una sesión existente usa la conexión de participante.
6. El contact flow inicial invoca el módulo de contexto, selecciona la cola y transfiere el contacto al agente.
7. Si hay multimedia, el mensaje visible se entrega primero y el trabajo pesado se procesa en una cola separada.

## Recorrido agente → cliente

1. Al crear el chat, el procesador inicia el streaming del contacto hacia un tema SNS.
2. SNS publica cada evento en la cola puente SQS.
3. La Lambda procesador ignora eventos que no corresponden al agente, transforma el texto o adjunto y llama Meta Graph API.
4. El ID de Meta se guarda para correlacionar estados `sent`, `delivered`, `read` o errores posteriores.

## Campañas y cotizaciones

1. En laboratorio, la app 3P usa el contexto del SDK para abrir una sesión efímera; no es autenticación de producción. En producción, este paso debe sustituirse por un adaptador SSO externo que verifique el token del IdP en backend, todavía no incluido en el repositorio.
2. La API valida formato, permisos y destinatarios; los archivos se cargan directamente a S3 con URL firmada.
3. Cada destinatario se encola en la FIFO de campañas.
4. La Lambda de campañas envía texto, documento o plantilla aprobada y registra la entrega.
5. Una respuesta o botón puede iniciar un contact flow específico. El envío masivo no abre un chat de Connect hasta que el cliente interactúa.

## Multimedia

1. El adaptador conserva ID, MIME, nombre original cuando existe y descripción.
2. La Lambda multimedia obtiene el archivo desde Meta, valida tamaño/tipo y lo almacena cifrado en S3.
3. Activa un token corto. CloudFront consulta la API, que comprueba vigencia y redirige a una URL S3 `inline` de pocos minutos.
4. Imágenes/documentos compatibles pasan por Textract; audio/video compatible inicia Transcribe.
5. Bedrock puede ordenar los fragmentos sin reescribir las palabras. El resultado aparece como `Transcripción:` solo si supera los filtros de utilidad.

## Cuatro Lambdas

| Función lógica | Código | Responsabilidad | Por qué está separada |
|---|---|---|---|
| Ingreso | `src/ingress/app.py` | Webhook, sesiones, API administrativa, carga y redirección | Debe responder rápido y validar seguridad |
| Procesador | `src/processor/app.py`, modo `conversation` | Chat, contrato canónico, formato, sesiones, Meta y Connect | Latencia interactiva y orden por conversación |
| Campañas | mismo módulo, modo `campaign` | Trabajos salientes, lotes y entregas | Concurrencia limitada para no afectar chat |
| Multimedia | mismo módulo, modo `media` | S3, OCR, transcripción y eventos asíncronos | Tareas lentas y de mayor memoria |

Compartir módulo de código no significa compartir ejecución: CloudFormation crea cuatro funciones, roles, límites, colas, logs y alarmas distintos.

## Mensajería interna

| Recurso | Tipo | Productor principal | Consumidor | DLQ |
|---|---|---|---|---|
| Conversaciones | SQS FIFO | Lambda ingreso/procesador | Lambda procesador | FIFO propia |
| Campañas | SQS FIFO | API administrativa | Lambda campañas | FIFO propia |
| Multimedia | SQS estándar | Lambda procesador/EventBridge | Lambda multimedia | estándar propia |
| Puente Connect | SNS → SQS estándar | Amazon Connect | Lambda procesador | estándar propia |

Las FIFO conservan el orden **dentro** de cada conversación o destinatario, pero permiten procesar conversaciones distintas en paralelo. Una DLQ nunca se redirige a producción sin identificar la causa y comprobar idempotencia.

## Datos y cifrado

- DynamoDB mantiene sesiones, reclamos idempotentes, rutas, campañas, entregas, respuestas y permisos de módulos.
- S3 mantiene multimedia entrante/saliente, adjuntos de Connect y archivos temporales.
- KMS cifra DynamoDB, S3, SNS y logs/secretos donde corresponde.
- Los buckets bloquean acceso público; CloudFront no expone el objeto de forma permanente.
- Los recursos con datos usan retención y, cuando está habilitado, protección contra borrado y recuperación a un punto en el tiempo.

### Valores de retención actuales

| Dato temporal | Valor predeterminado |
|---|---:|
| Reclamo idempotente de mensaje | 7 días |
| Sesión de conversación | `SessionTtlSeconds` (24 h por defecto) + margen de 7 días en TTL |
| Ruta de botón | 7 días, ajustable por envío |
| Enlace corto multimedia | 24 horas |
| Estado temporal de Transcribe | 24 horas |
| Campaña, entrega y respuesta | 395 días |
| Objetos S3 bajo `inbound/` | 90 días; versiones no actuales 30 días |

Son valores técnicos iniciales, no una política legal universal. Cámbielos de forma explícita y pruebe restauración/borrado antes de almacenar datos reales.

## Contrato canónico

```json
{
  "schema": "social-message/1.0",
  "channel": "whatsapp",
  "provider": "meta_direct",
  "business_id": "identificador-del-canal",
  "sender_asset_id": "identificador-del-activo-emisor",
  "conversation_key": "identidad-externa-estable",
  "customer": {
    "id": "identidad-canónica",
    "phone": "15555550123",
    "user_id": "",
    "parent_user_id": "",
    "username": "cliente_demo",
    "name": "Cliente de ejemplo"
  },
  "message": {
    "id": "wamid.ejemplo",
    "type": "text",
    "text": "Hola",
    "reply_id": "",
    "reply_to": "",
    "media": {},
    "flow_response": {}
  }
}
```

Los adaptadores futuros deben producir este contrato y no saltarse idempotencia, seguridad, observabilidad ni reglas de Connect.

## Infraestructura como aplicación

`template.yaml` es la unidad desplegable. AWS SAM/CloudFormation crea y etiqueta recursos; dos AWS Resource Groups permiten consultar tanto el stack completo como los recursos compatibles con tags `Application`/`Environment`, y CloudWatch centraliza la operación. No se requiere un registro manual paralelo para considerar el stack una aplicación.

Desde el 30 de julio de 2026, AWS ya no permite crear o actualizar aplicaciones en myApplications y mantiene Application Manager/AppRegistry sin altas nuevas para nuevos clientes. Por eso esta solución no depende de esos catálogos: usa el stack SAM, tags, AWS Resource Groups y el dashboard CloudWatch, mecanismos desplegables y verificables con la misma plantilla. Consulte el [historial de myApplications](https://docs.aws.amazon.com/awsconsolehelpdocs/latest/gsg/document-history.html) y el [aviso de Application Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/application-manager-availability-change.html).
