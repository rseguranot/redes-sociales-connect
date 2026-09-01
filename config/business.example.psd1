@{
  # Identidad de la instalación. Use minúsculas, números y guiones en ProjectName.
  ProjectName = 'empresa-redes-sociales'
  StackName = 'empresa-redes-sociales-dev'
  Region = 'us-east-1'
  Environment = 'dev'
  ExpectedAwsAccountId = '111111111111' # Evita desplegar accidentalmente en otra cuenta.

  BusinessName = 'Nombre de la empresa'
  BusinessTagline = 'Comunicaciones seguras'
  BrandLogoPath = 'branding/brand-logo.svg'
  LogoIncludesName = $false
  Locale = 'es'
  DefaultTemplateLanguage = 'es'

  # Amazon Connect. Por defecto CloudFormation crea un flow mínimo portable que
  # inicializa el contexto social y transfiere el contacto a ConnectQueueId.
  ConnectInstanceId = '00000000-0000-0000-0000-000000000000'
  CreateDefaultContactFlow = $true
  ManagedContactFlowName = '00 Redes Sociales - Ingreso'
  ConnectQueueId = '00000000-0000-0000-0000-000000000000'
  DefaultContactFlowId = ''
  CreateConnectContextModule = $true
  ConnectContextModuleName = '00 MOD Social - Inicializar contexto'
  CreateConnectAttachmentsStorage = $false

  # Enrutamiento controlado de desarrollo. Nunca publique números reales en Git.
  DevelopmentContactFlowId = ''
  DevelopmentPhoneNumbers = ''
  TemplateDslMode = 'disabled'
  TemplateDslPhoneNumbers = ''
  DeveloperRoutingProfileIds = ''
  DeveloperSecurityProfileIds = ''
  # Perfiles que podrán abrir inicialmente la aplicación 3P. El helper conserva
  # cualquier otra aplicación que ya tengan asociada.
  ApplicationSecurityProfileIds = @('00000000-0000-0000-0000-000000000000')
  ConnectChatAttachmentExtensions = @('mp3')

  # Debe apuntar a un secreto existente de Secrets Manager. El secreto contiene
  # WA_ACCESS_TOKEN, WA_APP_SECRET, WA_BUSINESS_ACCOUNT_ID, WA_PHONE_NUMBER_ID y
  # WA_VERIFY_TOKEN; no coloque esos valores directamente en este archivo.
  WhatsAppSecretArn = 'arn:aws:secretsmanager:us-east-1:111111111111:secret:whatsapp-prod-xxxxxx'
  MetaGraphVersion = 'v26.0'
  OcrBedrockModelId = 'us.amazon.nova-2-lite-v1:0'
  TranscribeLanguageCode = 'es-US' # Use 'auto' únicamente para atención multilingüe.
  SessionTtlSeconds = 86400
  LogRetentionDays = 30

  AdminAppName = 'Empresa Redes Sociales'
  AdminAppNamespace = 'empresa-redes-sociales'
  # El modo preview no autentica criptográficamente al agente. Mantenga disabled
  # en producción y use SSO con el mismo IdP de Connect.
  AdminAppAuthMode = 'disabled'
  AlarmEmail = ''
  EnableDeletionProtection = $false
}
