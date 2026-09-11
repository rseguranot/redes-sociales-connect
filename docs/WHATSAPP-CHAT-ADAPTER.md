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
