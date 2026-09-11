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

## Validación del 11 de septiembre de 2026

Desplegado y conectado al flow restringido de pruebas. Ambos stacks terminaron
en UPDATE_COMPLETE. El cambio del stack principal conservó 42 parámetros y
modificó únicamente el alias de IA; el change set mostró el contenido del flow
de pruebas y la referencia dependiente en el entorno del procesador, sin
reemplazos ni cambio de código de este último.

Pruebas locales: 121 aprobadas y 9 subpruebas; esquema CloudFormation sin
hallazgos y cuatro reglas Guard aprobadas. Lex publicado validó producto,
contexto, menú, estatus, reclamación, queja, agente y consulta de horario.

Prueba real de WhatsApp Web, 12:43–12:49 hora local:

- Menú inicial → Información general → tres botones nativos en español.
- Precio de televisor LG → sucursal → repetición de precio → medida de 55
  pulgadas: conservó contexto y devolvió dos opciones de catálogo con precios.
- La sucursal no se presentó como inventario/precio confirmado localmente.
- Botón Otra consulta → menú, sin transferencia ni despedida.
- Estatus → petición de factura; cambio a reclamación → Sí → petición de
  documento; cambio a queja → No → petición de nombre. No se aportaron datos
  personales ni se completó el registro de casos.
- Solicitud de agente → cierre protegido del usuario de prueba. Persiste el
  anuncio previo de transferencia además de la aclaración de prueba.

Se verificaron sin cambios el contenido del flow de voz, el código del hook
anterior y las versiones de sus aliases Lex. No se certificaron precios de
tienda, resolución de pedidos, CRM, multimedia ni una transferencia real.
