# Canales y capacidades

## Matriz de implementación

| Canal | Recepción | Envío | Multimedia | Interacciones | Estado |
|---|---:|---:|---:|---:|---|
| WhatsApp Cloud API | Sí | Sí | Sí | Botones, listas, plantillas y Flows | Implementado |
| Instagram Messaging | No | No | No | No | Adaptador planificado |
| Facebook Messenger | No | No | No | No | Adaptador planificado |
| Threads | No | No | No | No | Evaluación; no implementado |
| Otro proveedor/red | No | No | No | No | Requiere adaptador y pruebas |

El nombre del proyecto expresa el objetivo multicanal, no una afirmación de que todos los canales estén listos. La infraestructura desplegada hoy solo crea el webhook `/webhook/whatsapp` y usa credenciales de WhatsApp.

## WhatsApp implementado

### Entrada

- Texto y formato compatible.
- Imagen, video, audio, nota de voz, documento y sticker.
- Ubicación con enlace de mapa.
- Contactos con teléfonos, correo, organización, dirección y URL cuando Meta los entrega.
- Reacciones.
- Respuestas de botón y lista.
- Respuestas `nfm_reply` de WhatsApp Flow.
- Estados de entrega y lectura.

### Salida

- Texto durante una conversación habilitada por Meta.
- Mensajes interactivos de botones o listas dentro de sus reglas.
- Plantillas de Meta previamente aprobadas.
- Documentos, imágenes, video y audio cuando el tipo/tamaño es aceptado por Meta.
- Archivos adjuntos enviados por el agente a través de Connect cuando son recuperables y compatibles.
- Campañas, cotizaciones y asociación de botones con contact flows.

### Soporte condicionado

Un tipo reconocido por el código puede ser rechazado por Meta, Connect, Transcribe, Textract o el navegador por MIME, códec, tamaño, versión o política. La matriz de aceptación debe probarse en cada cuenta y región; consulte [Pruebas](PRUEBAS.md).

## Ventana de atención y plantillas Meta

Los mensajes libres o interactivos no sustituyen las reglas de WhatsApp Business Platform:

- Dentro de la ventana de servicio permitida por Meta se puede responder con contenido admitido.
- Para iniciar una conversación o escribir fuera de esa ventana se usa una plantilla aprobada y vigente.
- La app puede crear/listar recursos en Meta según permisos, pero el estado final de aprobación pertenece a Meta.
- Un error de formato puede normalizarse de forma determinista; nunca se debe cambiar silenciosamente el sentido comercial o legal mediante IA.

## Qué exige cada canal futuro

Un adaptador nuevo debe resolver, como mínimo:

1. Verificación/firma del webhook.
2. Identidad estable del usuario y del negocio.
3. Normalización de texto, multimedia, respuestas y estados.
4. Envío saliente y carga/descarga segura de archivos.
5. Límites de ventana, plantillas, permisos y rate limits propios.
6. Idempotencia, reintentos, DLQ, métricas y pruebas contractuales.
7. Mapeo claro de capacidades ausentes. No debe fingir botones o formatos no soportados.

Consulte [Extensión por adaptadores](EXTENSION-POR-ADAPTADORES.md).
