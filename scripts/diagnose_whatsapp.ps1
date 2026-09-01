[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string] $ConfigFile,
  [Parameter(Mandatory)] [string] $AwsProfile,
  [ValidateRange(1, 168)] [int] $LookbackHours = 24
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# AWS CLI is Python-based and some Connect flows contain emoji. Force UTF-8 so
# Windows console code pages cannot truncate otherwise valid JSON responses.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedConfig = Resolve-Path -LiteralPath $ConfigFile
$cfg = Import-PowerShellDataFile -LiteralPath $resolvedConfig
$failures = 0
$warnings = 0

function Write-Check([ValidateSet('PASS', 'WARN', 'FAIL', 'INFO')] [string] $Status, [string] $Message) {
  switch ($Status) {
    'PASS' { Write-Host "[PASS] $Message" -ForegroundColor Green }
    'WARN' { $script:warnings++; Write-Host "[WARN] $Message" -ForegroundColor Yellow }
    'FAIL' { $script:failures++; Write-Host "[FAIL] $Message" -ForegroundColor Red }
    default { Write-Host "[INFO] $Message" }
  }
}

function Invoke-AwsJson([string[]] $Arguments) {
  $raw = & aws @Arguments 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "AWS CLI falló: aws $($Arguments -join ' ')`n$($raw -join "`n")"
  }
  $text = $raw -join "`n"
  if ([string]::IsNullOrWhiteSpace($text)) { return $null }
  return $text | ConvertFrom-Json
}

function Get-Map($Rows, [string] $KeyProperty, [string] $ValueProperty) {
  $map = @{}
  foreach ($row in @($Rows)) { $map[[string]$row.$KeyProperty] = [string]$row.$ValueProperty }
  return $map
}

function Get-LambdaMetricSum([string] $FunctionName, [string] $MetricName) {
  $endTime = (Get-Date).ToUniversalTime()
  $startTime = $endTime.AddHours(-$LookbackHours)
  $response = Invoke-AwsJson @(
    'cloudwatch', 'get-metric-statistics', '--namespace', 'AWS/Lambda',
    '--metric-name', $MetricName, '--dimensions', "Name=FunctionName,Value=$FunctionName",
    '--start-time', $startTime.ToString('yyyy-MM-ddTHH:mm:ssZ'),
    '--end-time', $endTime.ToString('yyyy-MM-ddTHH:mm:ssZ'),
    '--period', '3600', '--statistics', 'Sum',
    '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
  )
  $values = @($response.Datapoints | ForEach-Object {
    if ($_.PSObject.Properties['Sum']) { [double]$_.Sum }
  })
  if ($values.Count -eq 0) { return 0 }
  $sum = ($values | Measure-Object -Sum).Sum
  return [double]$sum
}

foreach ($required in @('ProjectName', 'StackName', 'Region', 'ConnectInstanceId', 'WhatsAppSecretArn')) {
  if (-not $cfg.ContainsKey($required) -or [string]::IsNullOrWhiteSpace([string]$cfg[$required])) {
    throw "Falta '$required' en $resolvedConfig."
  }
}

Write-Host "Diagnóstico WhatsApp: $($cfg.ProjectName)"
Write-Host "Stack: $($cfg.StackName) | Región: $($cfg.Region) | Ventana: ${LookbackHours}h"

$identity = Invoke-AwsJson @('sts', 'get-caller-identity', '--profile', $AwsProfile, '--output', 'json')
Write-Check PASS "Perfil AWS válido; cuenta $($identity.Account)."

$stackResponse = Invoke-AwsJson @(
  'cloudformation', 'describe-stacks', '--stack-name', [string]$cfg.StackName,
  '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
)
$stack = $stackResponse.Stacks[0]
if ([string]$stack.StackStatus -match '(_COMPLETE|IMPORT_COMPLETE)$' -and [string]$stack.StackStatus -notmatch 'ROLLBACK') {
  Write-Check PASS "CloudFormation está en $($stack.StackStatus)."
}
else { Write-Check FAIL "CloudFormation está en $($stack.StackStatus)." }

$outputs = Get-Map $stack.Outputs 'OutputKey' 'OutputValue'
$parameters = Get-Map $stack.Parameters 'ParameterKey' 'ParameterValue'
$localRevision = (& git -C $repoRoot rev-parse --short=12 HEAD 2>$null)
$deployedRevision = [string]$outputs['DeploymentRevision']
if ([string]::IsNullOrWhiteSpace($deployedRevision)) {
  Write-Check WARN 'El stack todavía no publica DeploymentRevision; se habilitará en el próximo despliegue de esta plantilla.'
}
elseif ($deployedRevision -eq $localRevision) {
  Write-Check PASS "La revisión desplegada coincide con Git: $localRevision."
}
else {
  Write-Check WARN "Git local es $localRevision y AWS declara $deployedRevision. Valide la rama antes de actualizar."
}
$null = & git -C $repoRoot diff --quiet
$trackedDirty = $LASTEXITCODE -ne 0
$null = & git -C $repoRoot diff --cached --quiet
$stagedDirty = $LASTEXITCODE -ne 0
if ($trackedDirty -or $stagedDirty) {
  Write-Check WARN 'El repositorio contiene cambios sin commit; no lo use como referencia exacta de producción.'
}
else { Write-Check PASS 'El repositorio no contiene cambios sin commit.' }

$resourceResponse = Invoke-AwsJson @(
  'cloudformation', 'list-stack-resources', '--stack-name', [string]$cfg.StackName,
  '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
)
$resources = @($resourceResponse.StackResourceSummaries)
$badResources = @($resources | Where-Object { [string]$_.ResourceStatus -match 'FAILED|ROLLBACK' })
if ($badResources.Count -eq 0) { Write-Check PASS "Los $($resources.Count) recursos del stack no muestran fallas." }
else { Write-Check FAIL "Hay $($badResources.Count) recursos fallidos o en rollback." }

$runtime = [string]$parameters['LambdaRuntime']
$lambdaResources = @($resources | Where-Object ResourceType -eq 'AWS::Lambda::Function')
foreach ($resource in $lambdaResources) {
  $function = Invoke-AwsJson @(
    'lambda', 'get-function-configuration', '--function-name', [string]$resource.PhysicalResourceId,
    '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
  )
  if ($function.State -eq 'Active' -and $function.LastUpdateStatus -eq 'Successful') {
    Write-Check PASS "$($function.FunctionName): Active, actualización Successful, runtime $($function.Runtime)."
  }
  else { Write-Check FAIL "$($function.FunctionName): State=$($function.State), LastUpdateStatus=$($function.LastUpdateStatus)." }
  if ($runtime -and $function.Runtime -ne $runtime) {
    Write-Check FAIL "$($function.FunctionName) usa $($function.Runtime), pero el stack declara $runtime."
  }
  $errors = Get-LambdaMetricSum $function.FunctionName 'Errors'
  $throttles = Get-LambdaMetricSum $function.FunctionName 'Throttles'
  if ($errors -gt 0) { Write-Check WARN "$($function.FunctionName): $errors errores durante las últimas ${LookbackHours}h." }
  else { Write-Check PASS "$($function.FunctionName): sin errores durante las últimas ${LookbackHours}h." }
  if ($throttles -gt 0) { Write-Check WARN "$($function.FunctionName): $throttles throttles durante las últimas ${LookbackHours}h." }
  $mappings = Invoke-AwsJson @(
    'lambda', 'list-event-source-mappings', '--function-name', [string]$function.FunctionName,
    '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
  )
  foreach ($mapping in @($mappings.EventSourceMappings)) {
    if ($mapping.State -eq 'Enabled') { Write-Check PASS "$($function.FunctionName): event source mapping habilitado." }
    else { Write-Check FAIL "$($function.FunctionName): event source mapping en $($mapping.State)." }
  }
}

$queueResources = @($resources | Where-Object ResourceType -eq 'AWS::SQS::Queue')
foreach ($resource in $queueResources) {
  $attributes = Invoke-AwsJson @(
    'sqs', 'get-queue-attributes', '--queue-url', [string]$resource.PhysicalResourceId,
    '--attribute-names', 'ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible', 'ApproximateNumberOfMessagesDelayed',
    '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
  )
  $visible = [int]$attributes.Attributes.ApproximateNumberOfMessages
  $inFlight = [int]$attributes.Attributes.ApproximateNumberOfMessagesNotVisible
  $delayed = [int]$attributes.Attributes.ApproximateNumberOfMessagesDelayed
  $isDlq = [string]$resource.LogicalResourceId -match 'DeadLetterQueue'
  if ($isDlq -and $visible -gt 0) {
    Write-Check FAIL "$($resource.LogicalResourceId) contiene $visible mensajes. Inspeccione sin borrarlos."
  }
  elseif ($isDlq) { Write-Check PASS "$($resource.LogicalResourceId) está vacía." }
  else { Write-Check INFO "$($resource.LogicalResourceId): visibles=$visible, en-proceso=$inFlight, demorados=$delayed." }
}

$secretResponse = Invoke-AwsJson @(
  'secretsmanager', 'get-secret-value', '--secret-id', [string]$cfg.WhatsAppSecretArn,
  '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
)
$secret = $secretResponse.SecretString | ConvertFrom-Json
$requiredSecretKeys = @('WA_ACCESS_TOKEN', 'WA_APP_SECRET', 'WA_BUSINESS_ACCOUNT_ID', 'WA_PHONE_NUMBER_ID', 'WA_VERIFY_TOKEN')
$missingSecretKeys = @($requiredSecretKeys | Where-Object { -not $secret.PSObject.Properties[$_] -or [string]::IsNullOrWhiteSpace([string]$secret.$_) })
if ($missingSecretKeys.Count -eq 0) { Write-Check PASS 'Secrets Manager contiene las cinco claves requeridas; sus valores no fueron mostrados.' }
else { Write-Check FAIL "Faltan claves en Secrets Manager: $($missingSecretKeys -join ', ')." }
$secret = $null
$secretResponse = $null

$flowIds = @()
if ($cfg.ContainsKey('DefaultContactFlowId') -and -not [string]::IsNullOrWhiteSpace([string]$cfg.DefaultContactFlowId)) {
  $flowIds += [string]$cfg.DefaultContactFlowId
}
if (-not [string]::IsNullOrWhiteSpace([string]$outputs['EffectiveDefaultContactFlowId'])) {
  $flowIds += [string]$outputs['EffectiveDefaultContactFlowId']
}
if ($cfg.ContainsKey('DevelopmentContactFlowId') -and -not [string]::IsNullOrWhiteSpace([string]$cfg.DevelopmentContactFlowId)) {
  $flowIds += [string]$cfg.DevelopmentContactFlowId
}
foreach ($flowId in $flowIds | Select-Object -Unique) {
  $flowResponse = Invoke-AwsJson @(
    'connect', 'describe-contact-flow', '--instance-id', [string]$cfg.ConnectInstanceId,
    '--contact-flow-id', $flowId, '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
  )
  $flow = $flowResponse.ContactFlow
  if ($flow.State -eq 'ACTIVE' -or $flow.Status -eq 'PUBLISHED') {
    Write-Check PASS "Flow '$($flow.Name)' está publicado/activo."
  }
  else { Write-Check FAIL "Flow '$($flow.Name)' no está activo: State=$($flow.State), Status=$($flow.Status)." }
}

$modules = Invoke-AwsJson @(
  'connect', 'list-contact-flow-modules', '--instance-id', [string]$cfg.ConnectInstanceId,
  '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
)
$contextModuleName = if ($cfg.ContainsKey('ConnectContextModuleName')) { [string]$cfg.ConnectContextModuleName } else { '00 MOD Social - Inicializar contexto' }
$contextModule = @($modules.ContactFlowModulesSummaryList | Where-Object Name -eq $contextModuleName)
if ($contextModule.Count -eq 0) {
  Write-Check WARN "No existe el módulo esperado '$contextModuleName'. Consulte docs/AMAZON-CONNECT.md."
}
elseif ([string]$contextModule[0].State -ieq 'active') { Write-Check PASS 'El módulo inicial de contexto social está activo.' }
else { Write-Check FAIL "El módulo inicial de contexto social está en estado $($contextModule[0].State)." }

$alarms = Invoke-AwsJson @(
  'cloudwatch', 'describe-alarms', '--alarm-name-prefix', [string]$cfg.ProjectName,
  '--profile', $AwsProfile, '--region', [string]$cfg.Region, '--output', 'json'
)
$activeAlarms = @($alarms.MetricAlarms | Where-Object StateValue -eq 'ALARM')
if ($activeAlarms.Count -eq 0) { Write-Check PASS 'No hay alarmas CloudWatch activas para el proyecto.' }
else { Write-Check FAIL "Alarmas activas: $(($activeAlarms.AlarmName) -join ', ')." }

Write-Host "Resultado: $failures fallas, $warnings advertencias."
if ($failures -gt 0) { exit 1 }
exit 0
