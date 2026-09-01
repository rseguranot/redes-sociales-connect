# Redes Sociales Connect

Plataforma serverless reutilizable para integrar canales sociales con Amazon Connect. La versión actual conecta **WhatsApp Cloud API directamente con Meta** y Amazon Connect; no depende de AWS End User Messaging Social. La arquitectura deja un contrato canónico y puntos de extensión para incorporar Instagram Messaging, Facebook Messenger y otros canales mediante adaptadores, pero esos adaptadores todavía no están implementados.

> Estado honesto: WhatsApp es el único canal operativo incluido. Instagram Messaging, Messenger y otros productos de Meta figuran en la hoja de ruta; desplegar este repositorio no los activa.

## Qué incluye

- Texto bidireccional entre WhatsApp y agentes de Amazon Connect.
- Recepción de imagen, video, audio, documento, sticker, ubicación, contacto, reacción y respuestas interactivas.
- Envío de texto y adjuntos del agente hacia WhatsApp.
- Enlaces cortos de vista previa que redirigen temporalmente a objetos privados en S3.
- OCR de imágenes y documentos con Amazon Textract, orden asistido por Amazon Bedrock y supresión de resultados sin texto útil.
- Transcripción asíncrona de audio/video con Amazon Transcribe y organización conservadora con Bedrock.
- Botones, listas, plantillas aprobadas por Meta, WhatsApp Flows, campañas, rutas botón → contact flow y almacenamiento de respuestas.
- Lenguaje sencillo `[plantilla]` para redactar interacciones desde bloques de Amazon Connect.
- Aplicación 3P para Agent Workspace, de uso operativo opcional. La plantilla actual crea sus recursos y asociación; el repositorio incluye un modo de contexto solo para laboratorio, mientras la autenticación SSO verificable de producción debe integrarse externamente y todavía no está implementada.
- Infraestructura reproducible mediante AWS SAM/CloudFormation, colas SQS/DLQ, SNS, DynamoDB, KMS, S3, CloudFront, API Gateway, alarmas y tablero CloudWatch.

El stack usa `python3.14` como runtime predeterminado al 1 de septiembre de 2026, parametrizado mediante `LambdaRuntime`. No se considera permanente: la guía de mantenimiento incluye la migración antes de su obsolescencia.

`ProjectName` es el nombre base y `Environment` (`dev` o `prod`) forma parte de la mayoría de los nombres físicos AWS. El stack, el namespace de la app y los nombres de flow/módulo de Connect se configuran aparte y deben ser únicos cuando varios ambientes comparten una instancia.

## Arquitectura

```text
WhatsApp / Meta
      │ webhook firmado
      ▼
API Gateway ──► Lambda ingreso ──► SQS conversaciones FIFO
                                         │
                                         ▼
                                  Lambda procesador ──► Amazon Connect
                                         │                    │
                           SQS multimedia│                    │ streaming
                                         ▼                    ▼
                                Lambda multimedia ◄── SQS ◄── SNS
                                │ S3 / Textract
                                │ Transcribe / Bedrock
                                └── vista previa CloudFront

App 3P ── preview de laboratorio / SSO externo ──► API administrativa ──► SQS campañas FIFO
                                                             │
                                                             ▼
                                                    Lambda campañas ──► Meta
```

Las cuatro funciones tienen responsabilidades y límites de concurrencia independientes:

1. **Ingreso**: verificación del webhook, firma HMAC, API administrativa, sesiones de Connect, cargas y redirecciones.
2. **Procesador**: contrato canónico, sesiones de chat, tráfico en ambas direcciones, formato y enrutamiento.
3. **Campañas**: lotes, plantillas aprobadas, cotizaciones y registro de entregas.
4. **Multimedia**: descarga, almacenamiento, vista previa, OCR y transcripción.

Separarlas impide que una campaña o un trabajo de IA lento bloquee el chat en tiempo real.

## Inicio rápido

Requisitos: AWS CLI v2, AWS SAM CLI, Python compatible con el runtime configurado, Node.js/npm, una instancia de Amazon Connect y una app de Meta con WhatsApp Cloud API.

```powershell
git clone https://github.com/rseguranot/redes-sociales-connect.git
Set-Location redes-sociales-connect
Copy-Item .\config\business.example.psd1 .\config\mi-empresa.local.psd1
```

1. Cree en AWS Secrets Manager un secreto con `WA_ACCESS_TOKEN`, `WA_APP_SECRET`, `WA_BUSINESS_ACCOUNT_ID`, `WA_PHONE_NUMBER_ID` y `WA_VERIFY_TOKEN`.
2. Complete el archivo local con la instancia/cola de Connect, el ARN del secreto y la marca. No confirme ese archivo en Git.
3. Valide sin modificar AWS:

```powershell
.\scripts\deploy.ps1 `
  -ConfigFile .\config\mi-empresa.local.psd1 `
  -AwsProfile "mi-perfil" `
  -Environment dev `
  -ValidateOnly
```

4. Despliegue primero en desarrollo:

```powershell
.\scripts\deploy.ps1 `
  -ConfigFile .\config\mi-empresa.local.psd1 `
  -AwsProfile "mi-perfil" `
  -Environment dev
```

5. Confirme la suscripción de alarmas, configure en Meta el `WebhookUrl` entregado por el stack y ejecute el plan de pruebas completo antes del corte.

La guía detallada está en [Instalación para una cuenta nueva](docs/INSTALACION.md).

## Validación local

```powershell
python -m unittest discover -s tests -v
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml

Push-Location app
npm ci
npm run test:sites
npm run build
Pop-Location
```

## Límites importantes

- Dentro de la ventana de atención de WhatsApp se admiten mensajes libres e interactivos permitidos por Meta. Fuera de ella se requiere una plantilla aprobada por Meta.
- El DSL `[plantilla]` no evita la aprobación de Meta ni convierte por sí solo un contenido en plantilla de negocio aprobada.
- La IA solo organiza resultados ya extraídos; no debe inventar, corregir ni completar el contenido del cliente. Cuando no hay texto confiable, no se publica transcripción.
- Los costos dependen de Meta y de los servicios AWS consumidos. Que un servicio tenga capa gratuita no garantiza costo cero.
- La aplicación 3P es un complemento administrativo, no una segunda bandeja de agentes.
- AWS exige que una app 3P proporcione autenticación propia. `AdminAppAuthMode=connect-context-preview` es solo para laboratorios; el valor seguro predeterminado es `disabled`, que bloquea la API administrativa. El repositorio no incluye todavía un modo SSO de producción: hay que implementar un adaptador que verifique en backend tokens del IdP antes de habilitar operaciones reales.

## Documentación

El [índice de documentación](docs/00-INDICE.md) reúne arquitectura, canales, Connect, seguridad, multimedia, campañas, pruebas, operación, mantenimiento y extensibilidad.

## Seguridad

No incluya tokens, archivos de configuración locales, datos personales ni exportaciones de clientes en Git. Consulte [SECURITY.md](SECURITY.md) para reportar vulnerabilidades mediante un canal privado.

## Licencia

MIT. Consulte [LICENSE](LICENSE).
