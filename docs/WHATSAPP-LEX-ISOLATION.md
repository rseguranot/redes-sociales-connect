# Lex y lógica de negocio independientes para chat

`connect/chat-isolated.json` crea un bot Lex nuevo, su versión y alias, un rol
Lex propio, una Lambda de presentación y una Lambda de negocio exclusiva. La
asociación con Connect es administrada por CloudFormation. No acepta como
parámetros un bot ni una Lambda de voz: las referencias son recursos del stack.

La lógica en `src/chat_business/` parte de una copia inmutable del hook
preexistente. La migración mecánica elimina impresiones de conversaciones y
eventos y convierte los identificadores operativos predeterminados en variables
obligatorias. Sólo se conserva la emisión de métricas técnicas sin contenido.
La copia no se sincroniza automáticamente con futuras versiones del hook de voz.
El adaptador incorpora el contexto comercial y las respuestas interactivas.

`scripts/bootstrap_chat_isolation.py` documenta la migración inicial: sólo lee
AWS, verifica la cuenta y la versión numérica de origen, transforma el esquema
Lex contra el esquema CloudFormation oficial, y rechaza sobrescribir código de
chat modificado. Los parámetros reales se escriben en `.aws-sam/`, fuera de Git.
No debe ejecutarse como parte de cada despliegue: la fuente de chat ya es propia.

## Alcance y límites

- Voz conserva su bot, versiones, aliases, Lambda, roles y contact flow.
- Chat comparte las fuentes Q/Bedrock y los servicios de negocio existentes,
  pero no su configuración conversacional Lex ni el ejecutable Lambda de voz.
- Cambiar una fuente de conocimiento o un agente Bedrock compartido todavía
  puede afectar a ambos canales; esta separación no clona esos servicios.
- El enrutamiento se limita al flow de prueba con allowlist. No es un ambiente
  dev completo, ni una activación del bot para todos los clientes.
- No se añade resolución automática de pedidos ni persistencia CRM nueva.
- No hay registro de conversaciones Lex en el nuevo alias. Logs Lambda tienen
  retención de 30 días y política Retain; no se imprime el evento del cliente.

## Publicación y reversión

1. Ejecutar pytest, cfn-lint y `connect/chat-isolated.guard`. Las reglas Guard
   son específicas de aislamiento/privacidad; no certifican todo un framework.
2. Construir y empaquetar SAM; crear y revisar el change set del stack de chat.
3. Crear los recursos sin modificar todavía el parámetro del flow existente.
4. Probar el nuevo Lex y verificar que su Lambda sólo invoca la Lambda propia.
5. Cambiar exclusivamente `DevelopmentAiBotAliasArn` mediante un change set
   que conserve los demás parámetros y el template existente.
6. Verificar WhatsApp real con el usuario protegido y comprobar voz sin cambios.

Para revertir el enrutamiento, restaurar el valor anterior de ese único
parámetro mediante CloudFormation. No eliminar bots o Lambdas anteriores
durante la validación. Consultar IDs/ARNs en outputs; no publicarlos en Git.
