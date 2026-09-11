# QA conversacional de WhatsApp — 2026-09-11

Pruebas con identidad protegida y datos ficticios. Sin transferencia a agentes
reales, sin modificaciones del canal de voz y sin publicar datos operativos.

## Evidencia de WhatsApp real

| Recorrido | Resultado observado |
|---|---|
| Queja de servicio: clasificación, nombre, teléfono, sucursal, fecha, área y despedida | Completado. Una ejecución de la herramienta de correo con marca QA y una aceptación de SES; sin errores de validación. |
| Nombre ficticio inicialmente rechazado | Reproducido, corregido y repetido: ahora solicita teléfono. |
| Queja parcial → menú → información general → promociones | Corregido y repetido: solicita producto, sin volver al agente de quejas ni cerrar. No generó un segundo correo. |
| Información general → sucursales → La Romana → horario → otra consulta | Completado; lista y botones nativos, formato con negrita y viñetas, retorno al menú sin cierre. |
| Promociones → producto | Respondió opciones de catálogo. Esto no demuestra una promoción vigente ni inventario por sucursal. |
| Estatus con factura ficticia inexistente → representante | Indicó ausencia de información; cierre protegido sin transferencia real. No certifica un pedido válido. |
| Reclamación sin factura | Ofreció documentos alternativos. Se identificó y retiró el atajo que transfería al detectar un documento sin consultar el backend. |
| Reclamación con caso ficticio, después de corregir | Pidió confirmación, invocó `/getClaim` y respondió que no encontró el caso. Solicitó identificación para continuar con uno nuevo. Sin invocación de `/createClaim` en el intervalo revisado. |
| Cancelación de reclamación sin identificación | Confirmó cancelación y se despidió, sin inventar un cliente ni crear un caso. |
| Inicio después de cierre | El primer mensaje abre el menú; no se certifica resolución del contenido inicial. |

## Cambios exclusivos de chat

- Reconocer preguntas de nombre como «cómo te llamas» y «cómo se llama».
- Enviar la respuesta al nombre como dato JSON contextualizado, no como consulta nueva.
- Reiniciar contexto de negocio y sesión Bedrock al volver al menú/información general;
  conservar identidad y configuración técnica de Connect.
- Eliminar del entrypoint de chat la transferencia inmediata por documento de reclamación.
- No insinuar registro exitoso ante excepción en la rutina de finalización de quejas.

Publicación por change sets revisados del stack independiente. Sin cambios del
stack principal, webhook, agentes Bedrock compartidos ni herramientas compartidas.
Hashes del flow y hook de voz comparados con el estado anterior: sin cambios.

## Validación automatizada

- 129 tests y 9 subtests offline aprobados.
- Smoke Lex de información general, producto con marca/medida/sucursal, menú,
  entradas de estatus/reclamación/queja y cierre de representante.
- Ocho sucursales × horario/dirección/menú: 24 turnos Lex con comprobaciones.
- Regresiones Lex de nombre y cambio de tema aprobadas.
- cfn-lint sin hallazgos; cuatro reglas Guard de aislamiento aprobadas.
- `describe-events` sin errores de validación antes de ejecutar cada change set.

Los probes reproducibles están en `scripts/qa_chat_paths.py`. No sustituyen
WhatsApp E2E ni prueban la exactitud comercial actual de horarios/precios.

## Límites del reporte y pendientes

La herramienta de quejas genera correo: su identificador calculado no constituye
por sí mismo un registro persistido en CRM. SES aceptó el envío, pero no se ha
comprobado recepción en el buzón final. La herramienta compartida mantiene logs
detallados con datos personales; se inspeccionaron solo contadores/indicadores
del test y no se modificó esa función por afectar otros consumidores.

Reclamaciones tiene herramientas Salesforce de búsqueda, consulta y creación.
La consulta de solo lectura `SELECT IsSandbox FROM Organization LIMIT 1` devolvió
`IsSandbox = false`: el destino Salesforce es producción, pese al nombre dev de
la Lambda. No se ejecutó `/createClaim`. No se certifica creación de un caso ni
consulta positiva de un pedido sin un sandbox y un cliente/pedido de prueba
conocido. Hace falta ese entorno para completar la prueba de escritura.
La transferencia protegida conserva dos mensajes: anuncio y aclaración de prueba.
No están cubiertos aquí multimedia, CCP real, mensajes fuera de ventana, carga,
duplicados de webhook ni todas las posibles formulaciones de lenguaje natural.
