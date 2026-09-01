# Extensión por adaptadores

## Estado actual

El núcleo define `social-message/1.0`, pero el código operativo solo incluye el adaptador `meta_direct` para WhatsApp. Esta guía describe la frontera recomendada; no implica que Instagram, Messenger o Threads funcionen hoy.

## Regla de diseño

```text
Payload del proveedor
  └─► adaptador de entrada
        └─► social-message/1.0
              ├─► sesión/Connect
              ├─► datos/campañas
              ├─► multimedia
              └─► adaptador de salida
```

El núcleo no debe leer campos crudos de Instagram/Messenger en sus reglas de campaña o Connect. El adaptador es responsable de traducirlos.

## Contrato mínimo del adaptador

Un canal nuevo debe implementar conceptualmente:

```text
verify_subscription(request) -> response
verify_signature(raw_body, headers) -> bool
split_webhook(payload) -> eventos idempotentes
to_canonical(event) -> social-message/1.0
send(identity, canonical_outbound) -> provider_message_id
fetch_media(provider_media) -> bytes + mime + filename?
upload_media(bytes, mime, filename) -> provider_media_id
normalize_status(event) -> accepted|sent|delivered|read|failed
capabilities() -> matriz explícita
```

También debe definir rate limits, reintentos, ventana de atención, plantillas, identidad, adjuntos y errores permanentes/transitorios.

## Identidad

No asuma que todos los canales entregan teléfono:

```json
{
  "id": "identidad-estable-del-canal",
  "phone": "",
  "user_id": "identidad-estable-del-canal",
  "parent_user_id": "",
  "username": "usuario_visible",
  "name": "Nombre visible"
}
```

La clave de conversación debe incluir canal/proveedor/activo del negocio para evitar colisiones. Connect recibe `social_channel`, `social_provider`, `social_business_id` y `social_user_id`.

## Capacidades

No intente emular silenciosamente una capacidad ausente. Ejemplo de registro:

```json
{
  "channel": "canal_demo",
  "inbound": ["text", "image"],
  "outbound": ["text"],
  "interactive": [],
  "templates": false,
  "flows": false,
  "delivery_receipts": true
}
```

La app y API deben deshabilitar acciones no soportadas y explicar el motivo.

## Rutas y secretos

Cada proveedor debe tener:

- endpoint propio, por ejemplo `/webhook/<canal>`;
- secreto separado con ARN propio;
- firma/verificación propia;
- permisos IAM mínimos;
- métricas con dimensión `Channel`;
- prefijo de idempotencia y DLQ correlacionable.

No coloque credenciales de varios negocios/canales en un único secreto si eso amplía innecesariamente el impacto de una filtración.

## Adaptador Instagram Messaging

Antes de implementarlo valide con documentación Meta vigente:

- tipo de cuenta y vinculación a página/app;
- permisos y App Review;
- firma del webhook;
- IDs scoped y su estabilidad;
- ventanas y etiquetas de mensajería;
- adjuntos/quick replies disponibles;
- estados de entrega y rate limits.

Después cree fixtures reales redactados, mapeo canónico, envío, multimedia y E2E. No reutilice `WA_PHONE_NUMBER_ID` como activo de Instagram.

## Adaptador Facebook Messenger

Debe tratar Page ID/PSID, permisos de página, políticas de mensajería, quick replies/templates, attachments y webhooks como un contrato separado. Compartir Graph API no hace iguales a Messenger y WhatsApp.

## Threads y otros productos

Primero confirme que existe una API oficial de mensajería adecuada al caso de uso, sus permisos y políticas. Si solo hay publicación/lectura y no conversación privada, marque el canal como no compatible con Connect Chat; no construya una integración sobre endpoints no oficiales.

## Pruebas contractuales

Cada adaptador añade:

- fixtures de texto, identidad, respuesta, status y multimedia;
- firma válida/inválida;
- mismo evento dos veces;
- ausencia de teléfono/nombre;
- error permanente/transitorio;
- archivo no soportado/sobre límite;
- prueba de que `to_canonical` cumple schema;
- prueba E2E bidireccional en sandbox;
- verificación de que otro canal sigue funcionando.

## Versionado

Cambios compatibles agregan campos opcionales. Cambios que alteren semántica crean `social-message/2.0` con migración/consumidores duales. No renombre campos en producción sin período de compatibilidad.

## Ruta de implementación recomendada

1. Documento de capacidades/políticas.
2. Fixtures y contrato canónico.
3. Adaptador de entrada y firma.
4. Adaptador de salida y estados.
5. Multimedia.
6. Parámetros/secretos/CloudFormation.
7. UI condicionada por capabilities.
8. Métricas/alarmas/diagnóstico.
9. E2E y rollout por allowlist/activo.
10. Actualizar la matriz de [Canales](CANALES-Y-CAPACIDADES.md) solo al demostrar operación.
