[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string] $ConfigFile,
  [Parameter(Mandatory)] [string] $AwsProfile,
  [ValidateSet('dev', 'prod')] [string] $Environment = 'dev',
  [switch] $ValidateOnly,
  [switch] $PrepareChangeSet,
  [switch] $SkipTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedConfig = Resolve-Path -LiteralPath $ConfigFile
$cfg = Import-PowerShellDataFile -LiteralPath $resolvedConfig
$samBuildDir = Join-Path $repoRoot ".aws-sam/build-$Environment-$PID"
$deploymentRevision = (git -C $repoRoot rev-parse --short=12 HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($deploymentRevision)) {
  $deploymentRevision = 'unknown'
}

function Require-Config([string] $Name) {
  if (-not $cfg.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace([string]$cfg[$Name])) {
    throw "Falta '$Name' en $resolvedConfig."
  }
}

@(
  'ProjectName', 'StackName', 'Region', 'ConnectInstanceId',
  'WhatsAppSecretArn', 'BusinessName',
  'BusinessTagline', 'AdminAppName', 'AdminAppNamespace', 'BrandLogoPath'
) | ForEach-Object { Require-Config $_ }

function Get-ConfigValue([string] $Name, $DefaultValue) {
  if ($cfg.ContainsKey($Name)) { return $cfg[$Name] }
  return $DefaultValue
}

function ConvertTo-ConfigBoolean($Value, [string] $Name) {
  if ($Value -is [bool]) { return [bool]$Value }
  $parsed = $false
  if ([bool]::TryParse([string]$Value, [ref]$parsed)) { return $parsed }
  throw "'$Name' debe ser `$true o `$false."
}

$createManagedFlow = ConvertTo-ConfigBoolean (Get-ConfigValue 'CreateDefaultContactFlow' $true) 'CreateDefaultContactFlow'
$createContextModule = ConvertTo-ConfigBoolean (Get-ConfigValue 'CreateConnectContextModule' $true) 'CreateConnectContextModule'
$createAttachmentsStorage = ConvertTo-ConfigBoolean (Get-ConfigValue 'CreateConnectAttachmentsStorage' $false) 'CreateConnectAttachmentsStorage'
$defaultContactFlowId = [string](Get-ConfigValue 'DefaultContactFlowId' '')
$connectQueueId = [string](Get-ConfigValue 'ConnectQueueId' '')
if ($cfg.ContainsKey('Environment') -and [string]$cfg.Environment -ne $Environment) {
  throw "El archivo declara Environment='$($cfg.Environment)', pero el comando solicitó '$Environment'."
}
if (-not $createManagedFlow -and [string]::IsNullOrWhiteSpace($defaultContactFlowId)) {
  throw "DefaultContactFlowId es obligatorio cuando CreateDefaultContactFlow es false."
}
if ($createManagedFlow -and [string]::IsNullOrWhiteSpace($connectQueueId)) {
  throw "ConnectQueueId es obligatorio cuando CreateDefaultContactFlow es true."
}
if ($createManagedFlow -and -not $createContextModule) {
  throw "El flow administrado requiere CreateConnectContextModule=true."
}

$account = [string](aws sts get-caller-identity --profile $AwsProfile --query Account --output text)
$account = $account.Trim()
if ($LASTEXITCODE -ne 0 -or $account -notmatch '^\d{12}$') { throw "No fue posible validar el perfil AWS '$AwsProfile'." }
$expectedAccount = [string](Get-ConfigValue 'ExpectedAwsAccountId' '')
if ($expectedAccount -and $expectedAccount -notmatch '^\d{12}$') {
  throw 'ExpectedAwsAccountId debe contener exactamente 12 dígitos.'
}
if ($expectedAccount -and $account -ne $expectedAccount) {
  throw "El perfil '$AwsProfile' apunta a la cuenta $account, pero la configuración exige $expectedAccount."
}
Write-Host "Cuenta validada: $account ($AwsProfile)"

Push-Location $repoRoot
try {
  if (-not $SkipTests) {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas Python.' }

    Push-Location (Join-Path $repoRoot 'app')
    try {
      if (Test-Path -LiteralPath (Join-Path $repoRoot 'app/node_modules')) {
        npm ls --depth=0
        if ($LASTEXITCODE -ne 0) { throw 'Las dependencias instaladas no coinciden con package-lock.json.' }
      }
      else {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw 'Falló npm ci.' }
      }
      npm run test:sites
      if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas de la aplicación.' }
    }
    finally { Pop-Location }
  }

  sam validate --lint --template-file template.yaml --profile $AwsProfile --region $cfg.Region
  if ($LASTEXITCODE -ne 0) { throw 'La plantilla SAM no es válida.' }
  sam build --template-file template.yaml --build-dir $samBuildDir
  if ($LASTEXITCODE -ne 0) { throw 'Falló sam build.' }

  if ($ValidateOnly) {
    Write-Host 'Validación local y de esquema completa. No se modificó AWS.'
    return
  }

  aws connect describe-instance --instance-id $cfg.ConnectInstanceId --profile $AwsProfile --region $cfg.Region --output json | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'La instancia Amazon Connect no existe o no es accesible.' }
  if ($createManagedFlow) {
    aws connect describe-queue --instance-id $cfg.ConnectInstanceId --queue-id $connectQueueId --profile $AwsProfile --region $cfg.Region --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'ConnectQueueId no identifica una cola accesible en la instancia configurada.' }
  }
  elseif ($defaultContactFlowId) {
    aws connect describe-contact-flow --instance-id $cfg.ConnectInstanceId --contact-flow-id $defaultContactFlowId --profile $AwsProfile --region $cfg.Region --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'DefaultContactFlowId no identifica un flow accesible en la instancia configurada.' }
  }
  aws secretsmanager describe-secret --secret-id $cfg.WhatsAppSecretArn --profile $AwsProfile --region $cfg.Region --output json | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'WhatsAppSecretArn no existe o no es accesible. Cree el secreto antes de preparar o ejecutar el despliegue.' }

  $protection = if ($Environment -eq 'prod') { 'true' } else { 'false' }
  if ($cfg.ContainsKey('EnableDeletionProtection')) {
    $protection = (ConvertTo-ConfigBoolean $cfg.EnableDeletionProtection 'EnableDeletionProtection').ToString().ToLowerInvariant()
  }
  $alarmEmail = if ($cfg.ContainsKey('AlarmEmail')) { [string]$cfg.AlarmEmail } else { '' }

  $overrides = [ordered]@{
    ProjectName = [string]$cfg.ProjectName
    Environment = [string]$Environment
    DeploymentRevision = [string]$deploymentRevision
    ConnectInstanceId = [string]$cfg.ConnectInstanceId
    DefaultContactFlowId = $defaultContactFlowId
    CreateDefaultContactFlow = $createManagedFlow.ToString().ToLowerInvariant()
    ManagedContactFlowName = [string](Get-ConfigValue 'ManagedContactFlowName' '00 Redes Sociales - Ingreso')
    ConnectQueueId = $connectQueueId
    CreateConnectContextModule = $createContextModule.ToString().ToLowerInvariant()
    ConnectContextModuleName = [string](Get-ConfigValue 'ConnectContextModuleName' '00 MOD Social - Inicializar contexto')
    CreateConnectAttachmentsStorage = $createAttachmentsStorage.ToString().ToLowerInvariant()
    DevelopmentContactFlowId = if ($cfg.ContainsKey('DevelopmentContactFlowId')) { [string]$cfg.DevelopmentContactFlowId } else { '' }
    DevelopmentPhoneNumbers = if ($cfg.ContainsKey('DevelopmentPhoneNumbers')) { [string]$cfg.DevelopmentPhoneNumbers } else { '' }
    TemplateDslMode = if ($cfg.ContainsKey('TemplateDslMode')) { [string]$cfg.TemplateDslMode } else { 'disabled' }
    TemplateDslPhoneNumbers = if ($cfg.ContainsKey('TemplateDslPhoneNumbers')) { [string]$cfg.TemplateDslPhoneNumbers } else { '' }
    DeveloperRoutingProfileIds = if ($cfg.ContainsKey('DeveloperRoutingProfileIds')) { [string]$cfg.DeveloperRoutingProfileIds } else { '' }
    DeveloperSecurityProfileIds = if ($cfg.ContainsKey('DeveloperSecurityProfileIds')) { [string]$cfg.DeveloperSecurityProfileIds } else { '' }
    WhatsAppSecretArn = [string]$cfg.WhatsAppSecretArn
    MetaGraphVersion = [string](Get-ConfigValue 'MetaGraphVersion' 'v26.0')
    OcrBedrockModelId = if ($cfg.ContainsKey('OcrBedrockModelId')) { [string]$cfg.OcrBedrockModelId } else { 'us.amazon.nova-2-lite-v1:0' }
    TranscribeLanguageCode = if ($cfg.ContainsKey('TranscribeLanguageCode')) { [string]$cfg.TranscribeLanguageCode } else { 'es-US' }
    SessionTtlSeconds = [string](Get-ConfigValue 'SessionTtlSeconds' 86400)
    LogRetentionDays = [string](Get-ConfigValue 'LogRetentionDays' 30)
    AlarmEmail = $alarmEmail
    EnableDeletionProtection = $protection
    AdminAppName = [string]$cfg.AdminAppName
    AdminAppNamespace = [string]$cfg.AdminAppNamespace
    AdminAppAuthMode = [string](Get-ConfigValue 'AdminAppAuthMode' 'disabled')
    BusinessDisplayName = [string]$cfg.BusinessName
    BusinessTagline = [string]$cfg.BusinessTagline
  }
  $deployArguments = @(
    'deploy',
    '--template-file', (Join-Path $samBuildDir 'template.yaml'),
    '--stack-name', [string]$cfg.StackName,
    '--resolve-s3',
    '--capabilities', 'CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM',
    '--profile', $AwsProfile,
    '--region', [string]$cfg.Region,
    '--no-confirm-changeset',
    '--no-fail-on-empty-changeset'
  )
  $parameterOverrides = [ordered]@{}
  foreach ($entry in $overrides.GetEnumerator()) {
    # SAM CLI rechaza `Parameter=`. Los opcionales vacíos ya declaran Default: ''.
    if ([string]::IsNullOrEmpty([string]$entry.Value)) { continue }
    $parameterOverrides[[string]$entry.Key] = [string]$entry.Value
  }
  # El archivo JSON evita que PowerShell/cmd dividan valores con espacios antes
  # de que SAM CLI los interprete (nombres de flow, aplicación y negocio).
  # JSON es un subconjunto válido de YAML; se usa .yaml porque SAM CLI mantiene
  # deshabilitado su lector .json para este argumento en versiones actuales.
  $parameterOverridesPath = Join-Path $samBuildDir 'parameter-overrides.yaml'
  $parameterOverridesJson = $parameterOverrides | ConvertTo-Json -Depth 3 -Compress
  $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($parameterOverridesPath, $parameterOverridesJson, $utf8WithoutBom)
  $deployArguments += @('--parameter-overrides', "file://$parameterOverridesPath")
  $deployArguments += @(
    '--tags',
    "Application=$($cfg.ProjectName)",
    "Environment=$Environment",
    'ManagedBy=AWS-SAM'
  )
  if ($PrepareChangeSet) { $deployArguments += '--no-execute-changeset' }

  & sam @deployArguments
  if ($LASTEXITCODE -ne 0) { throw 'Falló el despliegue de CloudFormation.' }
  if ($PrepareChangeSet) {
    Write-Host 'Change set preparado y no ejecutado. Revíselo en CloudFormation antes de continuar.'
    return
  }

  $chatExtensions = if ($cfg.ContainsKey('ConnectChatAttachmentExtensions')) {
    @($cfg.ConnectChatAttachmentExtensions)
  }
  else {
    @('mp3')
  }
  python (Join-Path $repoRoot 'scripts/configure_connect_attachments.py') `
    --profile $AwsProfile `
    --region $cfg.Region `
    --instance-id $cfg.ConnectInstanceId `
    --extensions $chatExtensions
  if ($LASTEXITCODE -ne 0) { throw 'No fue posible configurar las extensiones de adjuntos de Amazon Connect.' }

  $outputsJson = aws cloudformation describe-stacks `
    --stack-name $cfg.StackName `
    --profile $AwsProfile `
    --region $cfg.Region `
    --query 'Stacks[0].Outputs' `
    --output json
  $outputs = @{}
  ($outputsJson | ConvertFrom-Json) | ForEach-Object { $outputs[$_.OutputKey] = $_.OutputValue }

  $applicationSecurityProfileIds = @()
  if ($cfg.ContainsKey('ApplicationSecurityProfileIds')) {
    foreach ($value in @($cfg.ApplicationSecurityProfileIds)) {
      $applicationSecurityProfileIds += ([string]$value -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    }
  }
  if ($applicationSecurityProfileIds.Count -gt 0) {
    python (Join-Path $repoRoot 'scripts/configure_connect_application.py') `
      --profile $AwsProfile `
      --region $cfg.Region `
      --instance-id $cfg.ConnectInstanceId `
      --namespace $cfg.AdminAppNamespace `
      --security-profile-ids $applicationSecurityProfileIds
    if ($LASTEXITCODE -ne 0) { throw 'No fue posible autorizar la aplicación en los security profiles configurados.' }
  }
  else {
    Write-Warning 'La aplicación 3P fue creada, pero ApplicationSecurityProfileIds está vacío. Autorice al menos un perfil antes de intentar abrirla.'
  }

  $brandSource = Resolve-Path -LiteralPath (Join-Path $repoRoot $cfg.BrandLogoPath)
  $brandExtension = [System.IO.Path]::GetExtension([string]$brandSource).ToLowerInvariant()
  if ($brandExtension -notin @('.svg', '.png', '.jpg', '.jpeg', '.webp')) {
    throw "El logo debe ser SVG, PNG, JPG, JPEG o WebP; se recibió '$brandExtension'."
  }
  $brandFileName = "brand-logo$brandExtension"
  $brandTarget = Join-Path $repoRoot "app/public/assets/$brandFileName"
  if ([System.IO.Path]::GetFullPath($brandSource) -ne [System.IO.Path]::GetFullPath($brandTarget)) {
    Copy-Item -LiteralPath $brandSource -Destination $brandTarget -Force
  }

  $runtimeConfig = [ordered]@{
    region = $cfg.Region
    apiBaseUrl = $outputs.AdminApiBaseUrl
    businessName = $cfg.BusinessName
    businessTagline = $cfg.BusinessTagline
    brandLogoUrl = "/assets/$brandFileName"
    logoIncludesName = if ($cfg.ContainsKey('LogoIncludesName')) { ConvertTo-ConfigBoolean $cfg.LogoIncludesName 'LogoIncludesName' } else { $false }
    locale = [string](Get-ConfigValue 'Locale' 'es')
    defaultTemplateLanguage = [string](Get-ConfigValue 'DefaultTemplateLanguage' 'es')
  }
  $runtimeJson = $runtimeConfig | ConvertTo-Json
  $configText = "window.__SOCIAL_HUB_CONFIG__ = $runtimeJson;"
  Set-Content -LiteralPath (Join-Path $repoRoot 'app/public/config.js') -Value $configText -Encoding utf8NoBOM

  Push-Location (Join-Path $repoRoot 'app')
  try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Falló la compilación de la aplicación.' }
  }
  finally { Pop-Location }

  aws s3 sync (Join-Path $repoRoot 'app/dist/client') "s3://$($outputs.AdminAppBucketName)" --delete --profile $AwsProfile --region $cfg.Region
  if ($LASTEXITCODE -ne 0) { throw 'Falló la publicación del frontend.' }
  aws cloudfront create-invalidation --distribution-id $outputs.AdminAppDistributionId --paths '/*' --profile $AwsProfile | Out-Null

  Write-Host "Despliegue completo: $($outputs.AdminAppUrl)"
  Write-Host "Webhook de Meta: $($outputs.WebhookUrl)"
  Write-Host "SNS de salida para Connect: $($outputs.ConnectStreamingTopicArn)"
  Write-Host 'Siguiente paso: completar el corte controlado de Meta descrito en docs/INSTALACION.md.'
}
finally {
  Pop-Location
}
