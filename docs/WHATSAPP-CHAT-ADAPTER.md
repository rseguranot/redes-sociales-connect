# Respuestas conversacionales de WhatsApp

`connect/chat-adapter.yaml` crea un alias Lex dedicado y un adaptador de presentación. El adaptador invoca una versión numérica del hook de negocio existente; no modifica ese hook ni los aliases de voz. Su ARN de salida se pasa como `DevelopmentAiBotAliasArn` al flow limitado por allowlist.

El bot puede devolver directamente el mismo DSL que los agentes. El primer renglón no vacío debe ser `[plantilla]`, en singular. No debe incluir cercas Markdown ni texto antes de ese marcador.

```text
[plantilla]
[informacion]
Para orientarte correctamente:
[pregunta]
¿Tu consulta corresponde a un producto comprado en Plaza Lama?
[opcion] Sí
[opcion] No
```

El procesador convierte 1–3 opciones en botones y 4–10 en una lista. La selección vuelve al bot como texto, igual que si el cliente la hubiera escrito. Las opciones deben describir la acción y conservar el contexto en atributos de sesión; no son una validación de identidad ni autorización para ejecutar una transacción.

El adaptador conserva la sucursal para las acciones de horario/dirección y para un “sí” inmediatamente posterior a una oferta de horario. Ofrece confirmaciones producto/servicio con botones y presenta horarios en líneas separadas. Usa `*negrita*`, `_cursiva_`, saltos de línea y emojis moderados compatibles con texto de WhatsApp.

Las fechas de promoción explícitas ya vencidas generan una aclaración; no se muestran como ofertas vigentes. Los campos técnicos de promociones no se publican como respuesta comercial. Esto no sustituye la validación de actualidad de la fuente comercial.

El adaptador no registra eventos ni mensajes. El hook de negocio preexistente conserva su configuración de logs: revisar su política de privacidad por separado. La prueba se limita al alias del flow de WhatsApp; no modifica mensajes normales de agentes.

Despliegue: validar y construir la plantilla SAM, preparar un change set con `BotId`, `BotVersion`, `BusinessHookArn` versionado y `ConnectInstanceArn` desde configuración privada. Revisar antes de ejecutar. Después actualizar el parámetro del flow mediante un segundo change set. Para revertir, restaurar el alias anterior en ese parámetro. Este stack auxiliar no representa un ambiente dev completo.

Validación del 2026-09-11: prueba real en WhatsApp Web de consulta libre de sucursal → botones nativos → respuesta escrita “sí” → horario con negrita/viñetas → botón de dirección conservando la sucursal. La validación demuestra transporte y continuidad de esas rutas, no certifica la actualidad de todos los datos del catálogo.

## Corrección de contexto de televisores

El adaptador reconoce consultas de precio de televisor en singular y plural. El
hook versionado existente tiene una expresión `televisores?` que no reconoce el
singular `televisor`; se normaliza la búsqueda a `televisores` sin modificar el
hook compartido con otros canales.

Los atributos `chat_product_*` conservan campos extraídos de producto: marca,
medida, modelo, tecnología y sucursal. No almacenan el transcript completo.
Una sucursal aportada como respuesta corta completa la consulta comercial, no
dispara una consulta de horarios. Si falta medida/modelo, el bot permite indicar
la medida o pulsar `Ver opciones` para consultar el catálogo sin ella. Las
peticiones explícitas de agente, queja, reclamación, cierre o información de
sucursal quedan a cargo del hook existente y abandonan el contexto de producto.

`Otra consulta`, `menú` y `otro producto` devuelven el menú de cinco opciones sin
llamar a la ruta de transferencia del hook. La sucursal indicada no certifica
inventario ni precio local: las respuestas del catálogo lo aclaran expresamente.

Validación local inicial: 115 pruebas y 9 subpruebas aprobadas. Incluye la secuencia
precio de televisor LG → sucursal → reiteración de precio → medida, cambios de
marca/medida, modelo/tecnología, menú y salidas de contexto. Esta corrección
se desplegó después en el bot independiente de chat y se verificó en WhatsApp
real. Véase [aislamiento de Lex](WHATSAPP-LEX-ISOLATION.md) para la validación
actual, límites y procedimiento de reversión.
No amplía el alcance a resolución de pedidos ni registro de casos CRM.
