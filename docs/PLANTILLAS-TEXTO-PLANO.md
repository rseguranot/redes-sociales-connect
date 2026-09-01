# Plantillas interactivas en texto plano

## Propósito

El DSL permite que una persona no técnica escriba contenido estructurado en un bloque de mensaje de Amazon Connect. La Lambda procesador reconoce el marcador, valida el contenido y produce texto, botones o una lista de WhatsApp.

El DSL solo se interpreta cuando la primera línea no vacía es `[plantilla]`. Un mensaje normal conserva su comportamiento normal.

## Activación gradual

| `TemplateDslMode` | Comportamiento |
|---|---|
| `disabled` | Nunca interpreta el DSL |
| `allowlist` | Solo para `TemplateDslPhoneNumbers` |
| `enabled` | Para todos los contactos |

Empiece con `allowlist`, una identidad de prueba y un flow aislado. Activar el parser no cambia mensajes que no comienzan con `[plantilla]`.

## Etiquetas

```text
[plantilla]
[nombre]
[titulo]
[informacion]
[pregunta]
[opcion]
[pie]
```

Reglas de lectura:

- No distingue mayúsculas/minúsculas ni acentos en etiquetas.
- `[texto]` y `[mensaje]` son alias de `[informacion]`.
- `[footer]` es alias de `[pie]`.
- `[opción]`, `[opcion 1]`, `[opcion 2]`, etc. se interpretan como opciones.
- El contenido puede empezar en la misma línea y continuar hasta la siguiente etiqueta.
- Una etiqueta desconocida, un segundo `[plantilla]` o texto fuera de sección rechaza el mensaje.
- `[nombre]` identifica el borrador para humanos; no es el título visible.
- Debe existir `[informacion]` o `[pregunta]`.

## Caso 1: información sin acciones

Entrada:

```text
[plantilla]
[nombre] Aviso de disponibilidad
[titulo] Cotización disponible

[informacion]
Hola $.Attributes.customer_name,

Tu cotización número $.Attributes.numero_cotizacion está disponible.

[pie] Equipo comercial
```

Salida conceptual:

```text
*Cotización disponible*

Hola Cliente de ejemplo,

Tu cotización número COT-10025 está disponible.

Equipo comercial
```

Sin opciones, WhatsApp recibe texto normal. `[pie]` se coloca separado al final porque un mensaje de texto libre no tiene componente `footer` nativo.

## Caso 2: pregunta con botones

```text
[plantilla]
[titulo] Confirmación de cita

[informacion]
Hola $.Attributes.customer_name,
tu cita es el $.Attributes.fecha a las $.Attributes.hora.

[pregunta] ¿Deseas confirmar la cita?

[opcion 1] Confirmar
[opcion 2] Reprogramar
[opcion 3] Cancelar

[pie] Atención al cliente
```

De una a tres opciones produce botones. La pregunta queda con exactamente un `*` a cada lado:

```text
*¿Deseas confirmar la cita?*
```

Si la entrada ya era `*¿Deseas confirmar la cita?*`, no se duplican los marcadores.

## Caso 3: lista

```text
[plantilla]
[titulo] Menú principal

[pregunta] ¿Qué departamento necesitas?

[opcion] Ventas
[opcion] Compras
[opcion] Facturación
[opcion] Servicio técnico
[opcion] Otro

[pie] Selecciona una opción
```

De cuatro a diez opciones produce una lista con botón `Ver opciones`. Más de diez se rechaza.

## Caso 4: contenido con título y pregunta opcional

Las secciones son independientes. Es válido tener:

- título + información, sin pregunta ni acciones;
- información + pregunta, sin título;
- título + información + pregunta + opciones;
- solo pregunta + opciones.

El parser determina el tipo por la cantidad de opciones, no por palabras como “menú” o signos de interrogación.

## Variables

Amazon Connect resuelve variables de flow antes de publicar el mensaje:

```text
Hola $.Attributes.customer_name
```

La Lambda también puede resolver, cuando los conoce, estos alias de identidad:

- `$.Attributes.nombre` / `{nombre}`.
- `$.Attributes.nombres` / `{nombres}`.
- `$.Attributes.customer_name` / `{customer_name}`.
- `$.Attributes.customer_display_name` / `{customer_display_name}`.
- `$.Attributes.telefono` / `{telefono}`.
- `$.Attributes.customer_phone` / `{customer_phone}`.
- `$.Attributes.whatsapp_phone` / `{whatsapp_phone}`.

Una variable de negocio como `$.Attributes.numero_cotizacion` debe existir en el contacto y resolverse en Connect. Si no existe, podría llegar literalmente; agregue validación/fallback en el flow.

## Conversión y límites

| Opciones | Resultado | Límite aplicado |
|---:|---|---|
| 0 | Texto informativo | Hasta 4096 caracteres renderizados |
| 1–3 | Botones reply | Cuerpo 1–1024; etiqueta visible hasta 20 |
| 4–10 | Lista | Cuerpo 1–4096; etiqueta visible hasta 24 |

Título y pie interactivos se limitan a 60 caracteres. Las etiquetas largas se acortan de forma determinista con puntos suspensivos; el ID interno permanece estable a partir de la opción y su posición.

No se usa IA para “arreglar” un mensaje inválido en tiempo real. Los límites son deterministas y un rechazo explícito es más seguro que cambiar el sentido de una opción. La métrica/log `TemplateDslRejected` permite encontrar y corregir el bloque de Connect.

## Formato WhatsApp ↔ Connect

WhatsApp usa `*texto*` para negrita; Connect Markdown usa `**texto**`. La conversión de mensajes entrantes evita mostrar simultáneamente formato y asteriscos. Los marcadores incompletos se conservan como texto para no alterar el contenido.

## Qué no hace el DSL

- No registra ni aprueba plantillas en Meta.
- No permite iniciar libremente una conversación fuera de la ventana de atención.
- No incluye todavía etiquetas arbitrarias para URL, llamada o WhatsApp Flow.
- No debe aceptar destinos o IDs escritos por usuarios sin validación en un catálogo autorizado.

Para Flows y plantillas aprobadas use el módulo correspondiente de la app/API. Consulte [Campañas, Flows y encuestas](CAMPANAS-FLOWS-Y-ENCUESTAS.md).
