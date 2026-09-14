# WhatsApp AI: despliegue productivo

Estado al 2026-09-11: **activado para contactos nuevos del número productivo**.
Bot independiente desplegado y stack del canal actualizado mediante change sets
sin reemplazos. Un primer plan con reemplazo condicional ajeno al alcance no se
ejecutó. Se preservaron las propiedades efectivas de los recursos no relacionados.

## Recursos y separación

`scripts/build_production_chat_template.py` genera `connect/chat-production.json`
a partir de los recursos independientes de chat y del flujo de pruebas. Crea
otro bot Lex, alias, hooks, alarmas y flujo, sin modificar voz ni el bot de pruebas.
Todos los identificadores operativos se suministran mediante parámetros privados.

El flujo productivo respeta el horario y la cola indicados. Puede suprimir la
transferencia únicamente para un ID social estable y dos teléfonos de prueba
declarados como parámetros privados. Compara cada campo con su origen correcto;
nunca deriva teléfono desde username o BSUID. Esas identidades reciben un cierre
de prueba y se desconectan. Para cualquier otro cliente, una solicitud explícita
de representante va al horario/cola aun si falta un atributo opcional de captura.
Los errores del bot intentan atención humana; los errores de cola se informan sin
prometer una devolución de llamada que no esté implementada.

## Procedimiento de activación

1. Construir y empaquetar el template generado mediante SAM.
2. Crear y revisar un change set CREATE. No ejecutar cambios con errores de
   validación ni reemplazos ajenos al alcance. Obtener autorización de ejecución.
3. Desplegar y comprobar el bot/flujo antes de cambiar el número productivo.
4. En el stack del canal, desplegar el procesador y configurar
   `ProductionAiContactFlowId` y `ProductionAiSenderAssetIds` con el flow nuevo y
   el ID exacto del número empresarial de Meta. Conservar los demás parámetros.
   Guardar estos valores también en la configuración privada de despliegue.
5. Revisar el segundo change set: sólo procesador/configuración relacionada.
6. Probar WhatsApp real, recepción por un agente y atributos del historial.
   Comprobar que voz y rutas de otros números no cambiaron.

El enrutamiento aplica a **contactos nuevos** de los activos configurados, sin
allowlist de clientes. Las sesiones activas conservan su contacto. Los destinos
explícitos de campañas conservan prioridad; otros activos conservan sus rutas.
Para revertir el enrutamiento, vaciar los dos parámetros mediante change set;
no eliminar recursos ni interrumpir conversaciones activas.

## Contexto para agentes e historial

El adaptador persiste mediante `UpdateContactAttributes` una lista explícita:
nombre/teléfono declarados, servicio, documento, referencia de caso o factura,
detalle, lugar, fecha, área y prioridad, cuando existen en la sesión del bot.
También conserva el último mensaje del cliente, la última respuesta y el estado
de transferencia. Son atributos `social_*` del contacto, no volcados del evento.

`social_collected_name` y `social_collected_phone` **no sustituyen** a
`social_display_name` o `social_phone`. `social_collected_data_source` indica
`conversation_unverified`: escribir una cédula no acredita la identidad.
No se usa el identificador de correo interno como número de caso CRM.

`social_context_status` distingue persistencia, fallo y falta de ContactId.
Un fallo de persistencia no repite la acción de negocio. Las trazas de ese fallo
no incluyen contenido ni identificadores del cliente.

Persistir atributos no significa que el CCP estándar muestre automáticamente
una ficha. Se debe verificar la interfaz de agente y el historial con un contacto
real antes de declarar completa esa parte. No publicar PII en evidencias o Git.

## Evidencia local

Pruebas del adaptador, diálogo, aislamiento y estructura de producción; pruebas
del procesador en proceso separado; cfn-lint y reglas de Guard. Estas pruebas no
sustituyen la validación E2E posterior al despliegue.

## Historial de siete días y firma de agentes

`ContactHistoryDays=7` habilita captura desde la activación, no una importación
retroactiva. DynamoDB separa el historial por activo empresarial e identidad
estable; no enlaza personas por nombre. Cada mensaje vence a los siete días y
la API filtra la fecha explícitamente aunque TTL todavía no lo haya eliminado.
Se guardan texto y nombres de adjuntos; las URLs se omiten. Los archivos y
transcripciones originales continúan en Connect. El último agente se conserva
como registro independiente y puede ser anterior a la ventana de mensajes.

La aplicación muestra contexto recopilado, último agente y mensajes paginados.
`GET /admin/contact-history` exige sesión de aplicación y una capacidad aleatoria
del contacto activo, suministrada por el SDK de Connect. No permite seleccionar
la identidad o partición desde el cliente. No registrar esta capacidad en logs.
No sustituye ni amplía la autenticación general existente de la aplicación.

`AgentMessageSignature=true` antepone el nombre de participante humano al texto
o pie compatible, después de interpretar el DSL. No firma respuestas del bot.
WhatsApp conserva el remitente empresarial; el nombre aparece dentro del mensaje.
Eventos internos de visibilidad exclusiva de agentes no se envían al cliente.

## Validación posterior al despliegue

- Stack del bot CREATE_COMPLETE; canal e instalación de pruebas UPDATE_COMPLETE.
- 53 pruebas pytest, 50 del procesador, 31 del ingreso y 24 de la aplicación
  aprobadas; compilación de la aplicación y seis escenarios Lex aprobados.
- WhatsApp real: menú, entrada de queja, botón No, captura de nombre ficticio y
  solicitud de agente. No se creó una queja ni un caso CRM en esta ronda.
- Un agente real aceptó y respondió; WhatsApp mostró su nombre en negrita.
  No se ejecutó el cierre personal de pruebas. El contacto luego finalizó.
- Se verificaron atributos recopilados, historial CUSTOMER/SYSTEM/AGENT y
  registro del último agente. Vista local con datos ficticios validada; aplicación
  publicada e invalidación CDN completada. **Pendiente confirmar visualmente el
  panel en la sesión de un agente real**: el contacto terminó antes de solicitarlo.
- Hashes del flow y hook de voz sin cambios. No certifica todas las variantes
  de negocio, multimedia, recepción en buzón ni mensajes fuera de ventana Meta.
