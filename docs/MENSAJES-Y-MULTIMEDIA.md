# Mensajes y multimedia

## Tipos entrantes

| Tipo de Meta | Representación en Connect | Procesamiento adicional |
|---|---|---|
| `text` | Texto o Markdown compatible | Conversión conservadora de formato |
| `image` | Nombre clicable/vista previa | S3, Textract, Bedrock opcional |
| `document` | Nombre original si existe | S3; PDF compatible puede usar Textract |
| `audio` | Nombre clicable/reproductor del navegador | S3, Transcribe, Bedrock opcional |
| `video` | Nombre clicable/reproductor del navegador | S3, Transcribe cuando el formato es compatible |
| `sticker` | Nombre clicable | S3; vista depende del formato/navegador |
| `location` | Nombre/dirección y enlace a mapa | Sin descarga |
| `contacts` | Datos legibles disponibles | Sin descarga |
| `reaction` | Emoji y referencia textual | Sin descarga |
| `interactive` / `button` | Título/ID de la respuesta | Ruta de botón o respuesta Flow |

Para un tipo futuro o desconocido se muestra un marcador seguro y se registra telemetría; no se debe perder el evento silenciosamente.

## Nombre de archivo

Cuando Meta incluye `filename`, se conserva después de eliminar separadores y saltos peligrosos. Para fotos, audios, videos y stickers Meta puede no entregar el nombre original del dispositivo; en ese caso se genera uno estable y descriptivo:

```text
foto-whatsapp-AAAAMMDD-HHMMSS-identificador.jpg
audio-whatsapp-AAAAMMDD-HHMMSS-identificador.ogg
```

No es técnicamente posible recuperar un nombre que el proveedor no envió. El nombre generado evita colisiones y no revela el ID completo del proveedor.

## Vista previa segura

El agente ve un enlace Markdown cuyo texto es el nombre del archivo. El recorrido es:

```text
https://dominio-cloudfront/m/token-opaco
  └─► API valida token, estado y vencimiento
        └─► redirección breve a S3 firmado con Content-Disposition: inline
```

El bucket sigue privado. El token se almacena como hash y la distribución no cachea la respuesta. La vista previa real depende del navegador y MIME:

- JPEG, PNG, PDF, MP3/OGG/MP4 compatibles suelen abrirse/reproducirse.
- Formatos no soportados, políticas corporativas o encabezados ambiguos pueden forzar descarga.
- `inline` es una preferencia, no una garantía del navegador.

No publique una URL S3 firmada larga en el chat ni transforme el bucket en público para acortarla.

## OCR de imágenes y documentos

1. Textract devuelve bloques `LINE`, geometría y confianza.
2. Se descartan líneas bajo `OCR_MIN_CONFIDENCE` y fragmentos sin suficientes caracteres alfanuméricos.
3. Si no queda texto útil, **no se envía** `Transcripción:`.
4. Bedrock recibe IDs, texto y posición. Solo puede devolver una permutación de esos IDs para agrupar títulos/cuerpo.
5. El código verifica que cada ID aparezca exactamente una vez. Si la salida no es válida o Bedrock falla, usa orden geométrico.

La IA no corrige ortografía, no traduce, no resume y no inventa palabras. La imagen original siempre queda disponible para confirmar. Una transcripción OCR no debe usarse como dato legal sin revisión humana.

## Audio y video

1. El archivo se guarda y el enlace queda disponible antes de completar la transcripción.
2. La Lambda inicia un trabajo Amazon Transcribe con idioma fijo o detección automática.
3. EventBridge envía `COMPLETED`/`FAILED` a la cola multimedia.
4. Si existe voz, Bedrock puede agrupar segmentos en párrafos sin cambiar palabras.
5. Connect recibe únicamente:

```text
Transcripción:

Contenido reconocido por Amazon Transcribe.
```

Si no se detecta voz, no se envía texto vacío ni caracteres sin sentido; el trabajo queda auditado como completado sin voz. Si la sesión de Connect ya terminó, el archivo procesado se conserva, pero el resultado no puede insertarse en un chat cerrado.

Para operaciones multilingües use detección automática solo después de probar los idiomas reales. Un idioma fijo suele reducir latencia y ambigüedad.

## Latencia

El enlace del archivo y la transcripción son eventos separados. Textract, Transcribe y Bedrock son asíncronos o variables; no prometa que llegarán juntos. La separación mantiene el chat disponible y evita que Meta reintente el webhook por esperar IA.

Para mejorar tiempo sin perder exactitud:

- fije el idioma de Transcribe cuando sea conocido;
- mantenga Bedrock a temperatura 0 y salida estructurada;
- limite tamaño/duración;
- no ejecute OCR en archivos no compatibles;
- vigile edad de la cola multimedia y concurrencia;
- no combine multimedia con la Lambda de ingreso.

## Salida de adjuntos hacia WhatsApp

El agente puede adjuntar un archivo permitido por Connect. El procesador:

1. recupera el adjunto mediante Connect Participant;
2. valida tamaño, MIME y nombre;
3. sube el binario a Meta;
4. elige `image`, `audio`, `video` o `document` según MIME;
5. envía caption/nombre cuando aplica;
6. guarda estado de entrega.

Un MP3 puede requerir que la extensión esté habilitada en Connect. Convertir audio automáticamente implicaría una dependencia de códec y una función específica; esta versión valida y transmite formatos compatibles, no promete transcodificación universal.

## Límites configurables y del proveedor

La plataforma aplica un máximo local de bytes antes de procesar; Meta, Connect, Textract y Transcribe tienen además límites propios que cambian por formato/servicio. Consulte la documentación vigente al actualizar. Un rechazo debe ir a log/métrica y reintento controlado, no provocar un bucle.

## Privacidad

Imagen, audio, documento, ubicación, contacto y transcripción pueden contener datos personales. Defina consentimiento, retención, acceso, exportación y borrado antes de producción. Bedrock/Transcribe/Textract deben usarse en regiones y configuraciones aprobadas por la organización.
