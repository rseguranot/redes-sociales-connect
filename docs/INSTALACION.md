# Instalación en una cuenta nueva

## Resultado esperado

Al terminar habrá un stack independiente, un webhook de WhatsApp, cuatro Lambdas, colas/DLQ, almacenamiento, datos, una aplicación 3P asociada y un flujo de entrada de Connect. Su uso operativo es opcional y la API administrativa queda bloqueada por defecto. La instalación no cambia por sí sola el webhook activo de Meta; ese cambio se realiza al final como corte controlado.

## 1. Requisitos

### Herramientas locales

- Git.
- AWS CLI v2 con un perfil para la cuenta destino.
- AWS SAM CLI.
- Python compatible con las pruebas del repositorio.
- Node.js y npm compatibles con `app/package-lock.json`.
- PowerShell 7 recomendado para `scripts/deploy.ps1`.

Compruebe identidad y región antes de cualquier cambio:

```powershell
aws sts get-caller-identity --profile "mi-perfil"
aws configure get region --profile "mi-perfil"
sam --version
python --version
node --version
```

### Meta

- Business Portfolio y aplicación Meta administrados por la organización.
- WhatsApp Business Account (WABA).
- Número habilitado para Cloud API.
- Token de sistema o mecanismo de token adecuado para producción.
- App secret y verify token propio, aleatorio y no reutilizado.
- Permisos de la aplicación para administrar/usar los recursos seleccionados.
- URL pública de política de privacidad e instrucciones de eliminación de datos aprobadas por la organización; no improvise textos legales durante el despliegue.
- Aplicación en el modo de publicación exigido por Meta para el negocio y los usuarios reales que atenderá.
- Método de pago/configuración comercial cuando Meta lo exija para conversaciones iniciadas por la empresa.
- Plantillas aprobadas cuando se iniciarán conversaciones fuera de la ventana permitida.

### Amazon Connect

- Instancia activa en la misma región elegida para el stack.
- Chat y streaming habilitados.
- Una cola destino existente y un routing profile que la incluya.
- Agentes con permisos de chat y estado disponible para la prueba.
- Security profiles definidos para Agente, Administrador y, si se usa, Developer.
- Almacenamiento de adjuntos: créelo con el stack solo si la instancia no tiene uno compatible. Amazon Connect admite una configuración de almacenamiento por tipo; no duplique `ATTACHMENTS`.

### Servicios regionales

Verifique disponibilidad de Lambda con el runtime elegido, Textract, Transcribe, Bedrock, API Gateway, SQS, SNS, DynamoDB, S3, KMS, CloudFront y EventBridge. Autorice el modelo de Bedrock configurado antes de probar OCR/transcripciones organizadas.

## 2. Clonar y crear configuración local

```powershell
git clone https://github.com/rseguranot/redes-sociales-connect.git
Set-Location redes-sociales-connect
Copy-Item .\config\business.example.psd1 .\config\mi-empresa.local.psd1
```

El archivo local debe permanecer ignorado por Git. Use nombres únicos por cuenta y ambiente:

```powershell
@{
  ProjectName = 'empresa-social'
  StackName = 'empresa-social-dev'
  Region = 'us-east-1'
  Environment = 'dev'
  ExpectedAwsAccountId = '111122223333'

  BusinessName = 'Empresa de ejemplo'
  BusinessTagline = 'Atención por canales digitales'
  BrandLogoPath = 'branding/brand-logo.svg'
  LogoIncludesName = $false
  Locale = 'es-DO'
  DefaultTemplateLanguage = 'es'

  ConnectInstanceId = '00000000-0000-0000-0000-000000000000'
  ConnectQueueId = '11111111-1111-1111-1111-111111111111'
  CreateDefaultContactFlow = $true
  ManagedContactFlowName = '00 Redes Sociales DEV - Ingreso'
  CreateConnectContextModule = $true
  ConnectContextModuleName = '00 MOD Social DEV - Inicializar contexto'
  CreateConnectAttachmentsStorage = $false

  DefaultContactFlowId = ''
  DevelopmentContactFlowId = ''
  DevelopmentPhoneNumbers = ''

  TemplateDslMode = 'allowlist'
  TemplateDslPhoneNumbers = '15555550123'

  DeveloperRoutingProfileIds = ''
  DeveloperSecurityProfileIds = ''
  ApplicationSecurityProfileIds = @('22222222-2222-2222-2222-222222222222')
  ConnectChatAttachmentExtensions = @('mp3')
  WhatsAppSecretArn = 'arn:aws:secretsmanager:us-east-1:111122223333:secret:whatsapp/dev-AbCdEf'
  MetaGraphVersion = 'v26.0'

  OcrBedrockModelId = 'us.amazon.nova-2-lite-v1:0'
  TranscribeLanguageCode = 'es-US'
  SessionTtlSeconds = 86400
  LogRetentionDays = 30
  AdminAppName = 'Redes Sociales Connect Dev'
  AdminAppNamespace = 'redes-sociales-connect-dev'
  AdminAppAuthMode = 'disabled'
  AlarmEmail = ''
  EnableDeletionProtection = $false
}
```

La plantilla de ejemplo del repositorio es la referencia definitiva de configuración. `Locale` es una etiqueta BCP 47 usada para mostrar y exportar fechas/horas en el frontend; no traduce textos. `DefaultTemplateLanguage` inicializa el idioma de borradores de plantillas Meta; tampoco traduce contenido y debe ser un código aceptado por Meta, por ejemplo `es` o `es_DO`. Ambos valores los consume `scripts/deploy.ps1` al generar la configuración pública de la app y no son parámetros de CloudFormation.

`ProjectName` es el nombre base. La plantilla añade `Environment` a la mayoría de nombres físicos AWS, por ejemplo `empresa-social-dev-...`, por lo que el mismo nombre base puede usarse para `dev` y `prod`. `StackName`, `AdminAppNamespace`, `ManagedContactFlowName` y `ConnectContextModuleName` se pasan de forma explícita y no reciben ese sufijo automáticamente; hágalos únicos si los ambientes comparten cuenta o instancia de Connect.

`v26.0` es el valor vigente usado por el repositorio al 1 de septiembre de 2026, no una versión permanente: verifique el ciclo de Meta antes de cada despliegue. Si una clave todavía no está disponible en la versión que está instalando, use el parámetro equivalente de `template.yaml` o actualice primero el repositorio.

`AdminAppAuthMode` queda en `disabled` de forma segura y la API administrativa responde `503 admin_auth_not_configured`. Para una prueba aislada puede usar `connect-context-preview`, entendiendo que el contexto del SDK no es una afirmación criptográfica verificable por el backend. La plantilla actual solo admite esos dos valores: no incluye un modo SSO de producción. Antes de usar la app administrativamente en producción debe implementar un adaptador externo que valide en backend el token del mismo IdP de Connect; una sesión federada vigente puede evitar un segundo formulario.

## 3. Crear el secreto de Meta

El secreto debe existir antes del despliegue y contener exactamente:

```json
{
  "WA_ACCESS_TOKEN": "valor-secreto",
  "WA_APP_SECRET": "valor-secreto",
  "WA_BUSINESS_ACCOUNT_ID": "identificador-waba",
  "WA_PHONE_NUMBER_ID": "identificador-del-numero",
  "WA_VERIFY_TOKEN": "valor-aleatorio"
}
```

Créelo en Secrets Manager mediante la consola o un proceso seguro. Si usa CLI, pase `--secret-string file://...`; no escriba valores en el comando, historial, repositorio, ticket o salida de CI. El token no debe aparecer en parámetros CloudFormation ni en `app/public/config.js`.

Confirme solo la existencia y las claves, nunca los valores:

```powershell
aws secretsmanager describe-secret `
  --secret-id "arn-del-secreto" `
  --profile "mi-perfil" `
  --region us-east-1
```

## 4. Validación sin cambios

```powershell
.\scripts\deploy.ps1 `
  -ConfigFile .\config\mi-empresa.local.psd1 `
  -AwsProfile "mi-perfil" `
  -Environment dev `
  -ValidateOnly
```

Además, ejecute manualmente cuando investigue una falla de tooling:

```powershell
python -m unittest discover -s tests -v
sam validate --lint --template-file template.yaml --profile "mi-perfil" --region us-east-1
sam build --template-file template.yaml

Push-Location app
npm ci
npm run test:sites
npm run build
Pop-Location
```

No continúe si falla una prueba, `sam validate`, `sam build` o la comprobación de identidad AWS.

`ValidateOnly` valida código y esquema, pero no demuestra que todos los IDs vivos pertenezcan a la instancia. Para preparar una revisión de CloudFormation sin ejecutar recursos:

```powershell
.\scripts\deploy.ps1 `
  -ConfigFile .\config\mi-empresa.local.psd1 `
  -AwsProfile "mi-perfil" `
  -Environment dev `
  -PrepareChangeSet
```

Esta opción consulta Connect/Secrets Manager, carga artefactos de SAM y crea un change set en AWS, pero no lo ejecuta. Revise reemplazos, IAM y recursos en la consola/CLI; después ejecute el despliegue normal desde el mismo commit.

## 5. Despliegue en desarrollo

```powershell
.\scripts\deploy.ps1 `
  -ConfigFile .\config\mi-empresa.local.psd1 `
  -AwsProfile "mi-perfil" `
  -Environment dev
```

Revise el change set antes de un entorno crítico. CloudFormation debe crear únicamente recursos con el nombre base y ambiente elegidos, además de las asociaciones en la instancia indicada. Puede compartir `ProjectName` entre `dev` y `prod` porque `Environment` separa la mayoría de nombres físicos; no reutilice la misma combinación `ProjectName` + `Environment`, bucket o stack para instalaciones no relacionadas.

Registre los outputs sin incluir secretos:

- `WebhookUrl`.
- `AdminAppUrl` y `AdminApiBaseUrl`.
- `ConnectStreamingTopicArn`.
- `ManagedDefaultContactFlowArn` o `EffectiveDefaultContactFlowId`.
- `ConnectContextModuleArn`.
- `PlatformResourceGroupArn` y `TaggedPlatformResourceGroupArn`.
- `OperationsDashboardName` y nombres de log groups.
- Tabla, bucket y colas creados.
- `DeploymentRevision`.

## 6. Configurar Amazon Connect

Si el stack crea el flow administrado, confirme que invoca el módulo y apunta a la cola correcta. Si usa un flow existente, agregue el módulo de contexto al inicio y asegure que el ID configurado esté publicado.

1. Incluya la cola en el routing profile del agente de prueba.
2. Confirme que `ApplicationSecurityProfileIds` hizo visible la aplicación 3P en al menos un security profile. El helper concede `ACCESS` de forma aditiva y conserva las demás aplicaciones ya asociadas. Esta visibilidad no autentica la API; con el modo seguro `disabled` la app seguirá bloqueada hasta integrar autenticación verificable.
3. Mantenga los módulos administrativos ocultos para perfiles sin autorización.
4. Confirme que el agente inicia sesión en Agent Workspace y aparece disponible.
5. Habilite extensiones de adjuntos solo después de revisar su política; el script puede añadir extensiones configuradas sin sustituir deliberadamente el conjunto existente.

Consulte [Amazon Connect](AMAZON-CONNECT.md).

## 7. Configurar Meta sin cortar todavía

En el producto WhatsApp de la app Meta:

1. Use `WebhookUrl` como callback.
2. Use el mismo valor de `WA_VERIFY_TOKEN` guardado en Secrets Manager.
3. Confirme que la validación `GET` devuelve exactamente el challenge y que un `POST` firmado se acepta; un `POST` sin firma debe rechazarse.
4. Preserve los campos de webhook que la aplicación ya utiliza y asegure al menos `messages`; actualizar el callback de la app y suscribir la app a la WABA son operaciones distintas.
5. Consulte `/{WABA_ID}/subscribed_apps` y confirme que devuelve el App ID esperado.
6. Consulte el número y confirme `code_verification_status=VERIFIED`, nombre aprobado y `status=CONNECTED`/Cloud API según el contrato vigente.
7. No vuelva a registrar un número que ya está conectado. Si todavía requiere registro, hágalo al final, guarde el PIN de verificación en un secreto y tenga preparado el rollback del proveedor anterior.
8. Mantenga documentada la URL anterior para rollback.

El cambio de callback puede dirigir tráfico real inmediatamente. Prográmelo en una ventana de prueba y no lo mezcle con otros cambios.

## 8. Pruebas de aceptación

Ejecute [el plan completo](PRUEBAS.md) con identidades de prueba autorizadas:

- Texto en ambos sentidos y formato.
- Imagen, documento, audio, video, sticker, ubicación y contacto.
- Nombre/teléfono/identidad en atributos de Connect.
- OCR con y sin texto útil.
- Transcripción y archivo reproducible.
- Botones, listas y respuesta de Flow.
- Plantilla aprobada fuera de ventana.
- Campaña pequeña y cotización con adjunto.
- Agente de prueba, cola normal y ruta de desarrollo.
- DLQ vacías, alarmas en `OK` y logs sin secretos.

## 9. Producción

Use un stack/configuración independientes, protección de borrado, correo o canal de alarmas confirmado y una revisión Git conocida. Repita build y pruebas; no promueva artefactos editados a mano.

Después del corte observe durante el período acordado:

- errores API/Lambda;
- edad de SQS;
- DLQ;
- tasas de entrega de Meta;
- tiempos de OCR/transcripción;
- contactos en cola y sesiones activas.

La reversión del webhook debe ser una acción separada y ensayada. Consulte [Mantenimiento y rollback](MANTENIMIENTO-Y-ROLLBACK.md).
