# API administrativa

## Uso previsto

La API se publica bajo el output `AdminApiBaseUrl` y está destinada a la app 3P dentro de Agent Workspace. No es una API pública para integraciones de terceros. Todas las rutas `/admin/*`, excepto la creación inicial de sesión bajo sus controles específicos, exigen origen permitido y bearer efímero.

En el código actual ese bearer solo puede emitirse con `AdminAppAuthMode=connect-context-preview`, exclusivamente para laboratorio. El valor predeterminado `disabled` bloquea la sesión y el repositorio no incluye un modo SSO de producción; todas las operaciones descritas quedan administrativamente bloqueadas hasta integrar un adaptador que valide en backend el token del IdP.

## Sesión

```http
POST /admin/session
Origin: https://distribucion-configurada
Content-Type: application/json
```

El cuerpo contiene la identidad/contexto obtenido del SDK de Connect. El backend no acepta un rol enviado por el navegador; consulta Connect y devuelve actor, rol, permisos y token de corta duración. Este intercambio solo está habilitado con `AdminAppAuthMode=connect-context-preview` y no sustituye SSO: el ARN del cuerpo puede modificarse en un navegador autorizado.

Rutas posteriores:

```http
Authorization: Bearer token-efimero
Origin: https://distribucion-configurada
```

Respuestas esperables: `503 admin_auth_not_configured`, `401 connect_session_required`, `403 invalid_app_origin` o `403 module_permission_required`. No trate estas respuestas como error de WhatsApp.

## Operaciones principales

| Ruta | Método | Propósito |
|---|---|---|
| `/admin/send` | POST | Texto, plantilla o multimedia a un destinatario |
| `/admin/quote` | POST | Plantilla opcional + documento, ordenados por destinatario |
| `/admin/campaign` | POST | Encolar campaña por lista o segmento |
| `/admin/upload` | POST | Obtener URL de carga S3 cifrada por 15 minutos |
| `/admin/templates` | GET/POST | Contenido reutilizable local |
| `/admin/surveys` | GET/POST | Borradores/definiciones locales |
| `/admin/segments` | GET/POST | Crear/importar/consultar segmentos |
| `/admin/campaigns` | GET | Estados y contadores |
| `/admin/responses` | GET | Respuestas por `campaign_id` |
| `/admin/meta-templates` | GET/POST | Catálogo o creación de plantilla Flow en Meta |
| `/admin/meta-template-management` | GET | Estados ampliados de plantillas Meta |
| `/admin/meta-flows` | GET/POST | Catálogo, creación, JSON y publicación de Flows |
| `/admin/access-profiles` | GET/POST | Visibilidad de aplicación por security profile |
| `/admin/module-permissions` | GET/POST | Matriz de permisos por módulo |
| `/admin/campaign-delete` | POST | Eliminación lógica con confirmación |
| `/admin/campaign-trash` | GET | Papelera, solo Developer |
| `/admin/campaign-restore` | POST | Restauración, solo Developer |

El contrato preciso se valida en backend; la UI no es la fuente de autorización.

## Carga y envío de documento

Primero solicite una carga:

```json
{
  "filename": "cotizacion-COT-10025.pdf",
  "content_type": "application/pdf"
}
```

La respuesta contiene `upload_url`, cabeceras KMS obligatorias, `s3_key` y vencimiento. El navegador sube directamente a S3 y luego referencia `s3_key`:

```json
{
  "to": "15555550123",
  "text": "Tu cotización está disponible.",
  "media": {
    "type": "document",
    "s3_key": "outbound/AAAA/MM/DD/archivo.pdf",
    "filename": "cotizacion-COT-10025.pdf",
    "caption": "Cotización COT-10025"
  },
  "contact_id": "contacto-de-connect"
}
```

No acepte `s3_key` de otro prefijo/tenant en una extensión futura. El enlace Meta generado es temporal.

## Envío de texto

```json
{
  "to": "15555550123",
  "text": "Tu solicitud fue recibida.",
  "agent_name": "Agente de ejemplo",
  "contact_id": "contacto-de-connect"
}
```

También se puede usar `user_id` cuando no existe teléfono. `phone` se mantiene como alias compatible; las integraciones nuevas deben preferir `to`.

## Plantilla aprobada y rutas

```json
{
  "to": "15555550123",
  "campaign_id": "camp-demo-2026-001",
  "template": {
    "name": "seguimiento_solicitud",
    "language": {"code": "es"},
    "components": [
      {
        "type": "body",
        "parameters": [{"type": "text", "text": "SOL-10025"}]
      }
    ]
  },
  "button_routes": [
    {
      "button_id": "hablar_agente",
      "contact_flow_id": "22222222-2222-2222-2222-222222222222"
    }
  ],
  "route_ttl_seconds": 604800
}
```

La API no debe aceptar un flow de otra instancia ni un botón sin ID estable. La ruta se aplica cuando la respuesta inicia un contacto nuevo.

## Campaña

Una campaña exige `campaign_id`, plantilla y destinatarios o `segment_id`. El backend:

- valida el ID;
- filtra mapeos a campos admitidos;
- divide trabajos en grupos;
- conserva orden por campaña/destinatario;
- registra actor y revisión;
- deriva estado a partir de entregas/respuestas durables.

Ejemplo mínimo:

```json
{
  "campaign_id": "camp-demo-2026-001",
  "name": "Encuesta de servicio",
  "campaign_type": "survey",
  "recipients": [
    {"to": "15555550123", "customer_name": "Cliente de ejemplo"}
  ],
  "template": {
    "name": "encuesta_servicio",
    "language": {"code": "es"}
  },
  "flow_ids": ["123456789012345"]
}
```

## Errores e idempotencia

- Validación/origen/permisos: error 4xx, no se encola.
- Aceptado: `202`, indica encolado, no entrega final.
- Error de Meta en catálogo/gestión: 502 saneado; detalles internos solo en logs.
- `request_id` e identidad forman reclamos idempotentes.
- La Lambda elimina el reclamo cuando una ejecución falla antes de completar para permitir reintento SQS.

Un consumidor externo futuro debe usar su propia autenticación, cuota, esquema versionado y autorización; no reutilice el token efímero del iframe.
