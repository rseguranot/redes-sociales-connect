# Campañas, WhatsApp Flows y encuestas

## Conceptos distintos

- **Mensaje interactivo de sesión**: botones/listas enviados dentro de la ventana permitida; no es una plantilla aprobada.
- **Plantilla Meta**: contenido registrado en la WABA y sujeto a aprobación/estado de Meta; permite iniciar según sus reglas.
- **WhatsApp Flow**: formulario nativo de varias entradas/pantallas. Normalmente se abre desde un botón Flow en una plantilla.
- **Contact flow de Amazon Connect**: automatización que recorre el contacto dentro de Connect. No es un WhatsApp Flow.

Mantenga estos nombres separados en operación y soporte.

## Catálogo de plantillas Meta

La API consulta la WABA y devuelve una copia saneada de nombre, idioma, estado, categoría, header/body/footer, variables, calidad y Flows vinculados. Si Meta no está disponible, puede mostrar el último catálogo en caché marcado como obsoleto; nunca expone el token.

Solo las plantillas `APPROVED`/activas deben utilizarse para un envío real. `PENDING`, `REJECTED`, `PAUSED` o `DISABLED` se muestran para gestión, no como garantía de entrega.

## Creación de Flow

El diseñador actual genera un formulario de una pantalla con:

- entrada de texto;
- selección única;
- selección múltiple;
- lista desplegable;
- campos obligatorios/opcionales;
- botón final que completa y devuelve el payload.

Las etiquetas humanas se normalizan a claves estables, por ejemplo:

```text
"Tipo de servicio" → tipo_de_servicio
"Mantenimiento"    → 0_mantenimiento
```

El proceso correcto es:

```text
Borrador local
  └─► Crear Flow DRAFT en Meta
        └─► Subir y validar flow.json
              └─► Corregir errores de Meta
                    └─► Publicar con confirmación explícita
                          └─► Crear plantilla con botón Flow
                                └─► Esperar aprobación de la plantilla
```

Publicar y aprobar plantilla son pasos distintos. Trate un Flow publicado como inmutable: cree una nueva versión/recurso para cambios incompatibles.

## Asociación de campaña

Cada campaña recibe un `campaign_id` único y válido. Cuando la plantilla contiene un Flow, el envío agrega ese ID como `flow_token` en el botón de acción. Así, la respuesta se correlaciona sin depender del teléfono o del nombre.

```json
{
  "type": "button",
  "sub_type": "flow",
  "index": "0",
  "parameters": [
    {
      "type": "action",
      "action": {"flow_token": "camp-demo-2026-001"}
    }
  ]
}
```

## Respuesta `nfm_reply`

Meta envía el formulario como respuesta interactiva. El procesador:

1. interpreta `response_json`;
2. extrae y valida `flow_token`;
3. conserva pares `{field, value}` sin confundirlos con etiquetas visuales;
4. entrega un resumen legible al agente;
5. guarda la respuesta bajo la campaña;
6. incrementa `response_count` y `last_response_at`.

Si el token no corresponde a una campaña vigente, la respuesta se conserva bajo `CAMPAIGN#unassigned` para investigación; no se descarta.

## Modelo de datos de campaña

Ejemplo lógico con datos ficticios:

```text
ADMIN#CAMPAIGNS / CAMPAIGN#camp-demo-2026-001  → resumen/listado
CAMPAIGN#camp-demo-2026-001 / META              → configuración durable
CAMPAIGN#camp-demo-2026-001 / OUTBOUND#wamid…   → entrega por destinatario
CAMPAIGN#camp-demo-2026-001 / RESPONSE#…         → respuesta de botón o Flow
```

Una respuesta de Flow conserva:

```json
{
  "campaign_id": "camp-demo-2026-001",
  "flow_token": "camp-demo-2026-001",
  "flow_id": "123456789012345",
  "form_name": "encuesta_demo",
  "identity_id": "identidad-externa",
  "customer_name": "Cliente de ejemplo",
  "phone": "15555550123",
  "answers": [
    {"field": "tipo_de_servicio", "value": "0_mantenimiento"},
    {"field": "comentario", "value": "Deseo información"}
  ],
  "answer_summary": "Resumen legible",
  "created_at": 1788000000
}
```

El teléfono puede estar vacío. `identity_id` es la clave técnica; el nombre es solo presentación.

## Estados operativos

Una campaña no está completada por haber sido encolada:

- `PROCESSING`: faltan destinatarios aceptados.
- `SENT`: Meta aceptó los mensajes, sin condición final todavía.
- `AWAITING_RESPONSES`: encuesta entregada, esperando respuestas.
- `PARTIAL_RESPONSES`: llegó una parte.
- `COMPLETED`: entregas o respuestas alcanzaron el criterio aplicable.

`accepted`, `delivered`, `read` y `response` son métricas distintas.

## Segmentos y variables

Los segmentos pueden importar contactos y elegir teléfono primario o todos los teléfonos válidos. El mapeo de variables de plantilla solo acepta campos permitidos (`name`, `phone`, `document_id`, `email`). Un destinatario sin todos los campos requeridos se excluye; no se envía con variables vacías sin advertencia.

Los datos importados pueden contener PII. Revise consentimiento, propósito, duplicados y política de retención antes de lanzar.

## Ruta botón → contact flow

Un envío puede guardar temporalmente:

```text
ROUTE#<identidad> / BUTTON#<button_id>
  → contact_flow_id, campaign_id, ttl
```

Cuando el cliente responde y no existe una sesión activa, la Lambda abre el chat con ese contact flow. La ruta expira para no afectar interacciones futuras. Valide que el flow pertenece a la instancia y está publicado antes de guardar la ruta.

## Exportación

La app consulta respuestas por `campaign_id`, presenta una columna por pregunta y permite exportar la vista a formatos de oficina. DynamoDB sigue siendo la fuente transaccional. Si se integra Google Sheets, use un worker/cola separados, OAuth administrado y DLQ; nunca ponga credenciales de Google en el navegador ni reemplace el registro durable con una hoja.

## Eliminación y retención

La eliminación de campañas es lógica y recuperable por Developer. Las respuestas permanecen hasta su política de TTL/retención; restaurar no vuelve a enviar mensajes. Ajuste el período a la política legal de cada organización antes de producción.

## Prueba mínima

1. Cree un Flow DRAFT con datos ficticios.
2. Valide y publique solo después de revisar JSON.
3. Cree una plantilla que lo abra y espere aprobación.
4. Lance a una única identidad de prueba.
5. Complete el formulario.
6. Confirme mensaje en Connect, registro `RESPONSE`, contador y exportación.
7. Repita con token inválido para comprobar `unassigned` sin pérdida.
