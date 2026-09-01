# Seguridad y permisos

## Principios

- Credenciales solo en Secrets Manager; nunca en Git, frontend, logs o parámetros visibles.
- Validación en backend, aunque la interfaz o Connect ya oculten una función.
- Permisos mínimos por Lambda y por operador.
- Cifrado en tránsito y reposo.
- Separación de ambientes, cuentas y datos.
- Auditoría de actor, revisión desplegada y resultado, sin registrar el contenido sensible innecesariamente.

## Webhook de Meta

- El alta `GET` compara `hub.verify_token` en tiempo constante.
- Cada `POST` exige `X-Hub-Signature-256` válido con `WA_APP_SECRET`.
- Un JSON inválido o firma ausente recibe rechazo; no entra a SQS.
- Los IDs del proveedor se reclaman de forma condicional en DynamoDB para evitar duplicados.
- La respuesta HTTP rápida no significa que el mensaje ya llegó al agente; significa que fue aceptado para procesamiento.

## Secreto de Meta

Claves requeridas:

- `WA_ACCESS_TOKEN`.
- `WA_APP_SECRET`.
- `WA_BUSINESS_ACCOUNT_ID`.
- `WA_PHONE_NUMBER_ID`.
- `WA_VERIFY_TOKEN`.

Restrinja `secretsmanager:GetSecretValue` a las funciones que lo necesitan. Use una política de rotación compatible con Meta y pruebe ambos sentidos después de cada rotación. No muestre el resultado de `get-secret-value` durante diagnóstico compartido.

## Aplicación 3P, Connect y SSO

AWS exige que una aplicación 3P autentique a sus usuarios. El SDK de Agent Workspace ofrece contexto y mensajería segura dentro del iframe, pero no entrega a este backend una prueba criptográfica de identidad. Por eso el modo seguro predeterminado es `AdminAppAuthMode=disabled`.

`connect-context-preview` existe únicamente para pruebas controladas:

1. Agent Workspace carga la aplicación autorizada para el security profile.
2. El SDK de Amazon Connect obtiene el ARN/nombre del agente a través del contexto autenticado.
3. `/admin/session` acepta únicamente el origen configurado y un ARN de la instancia esperada.
4. El backend usa `DescribeUser` para confirmar que el ARN corresponde a un usuario de la instancia y leer sus routing/security profiles y acceso a la aplicación. Esto no prueba que exista una sesión activa de Agent Workspace.
5. Emite un token aleatorio, efímero, guardado solo en memoria del iframe; DynamoDB conserva su hash y vencimiento.
6. Cada ruta administrativa revalida sesión y permisos de módulo.

Estos controles reducen exposición, pero no impiden que un usuario del navegador altere el ARN enviado. No habilite este modo en producción. El repositorio no incluye un modo SSO ni un verificador de tokens: debe integrar el mismo IdP/SSO corporativo de Connect y validar su token en backend antes de habilitar la API; una sesión federada vigente evita pedir credenciales otra vez. La app nunca necesita el token de Meta ni el bearer interno del CCP.

## Roles funcionales

- **Agente**: ve/usa solo módulos explícitamente concedidos.
- **Administrador**: administra contenido/operaciones según permisos, sin poder elevar su propio acceso por interfaz.
- **Developer**: se deriva de routing/security profile configurado y puede administrar la matriz de acceso.

La autorización visual no basta. Las rutas `/admin/access-profiles`, `/admin/module-permissions` y cada acción de campañas, plantillas, encuestas o cotizaciones deben aplicar el control en backend.

## IAM de despliegue

El rol de CI/CD necesita crear/actualizar el stack y pasar exclusivamente los roles definidos por la plantilla. Según parámetros, CloudFormation administra recursos de:

- CloudFormation y S3/SAM para artefactos.
- IAM y KMS.
- Lambda y CloudWatch Logs.
- API Gateway, SQS, SNS y EventBridge.
- DynamoDB, S3 y CloudFront.
- Amazon Connect y AppIntegrations.
- Resource Groups y CloudWatch alarms/dashboard.

Evite usar `AdministratorAccess` de forma permanente. Genere una política específica a partir de un change set revisado, limite `iam:PassRole` y separe despliegue de operación. Un perfil de lectura debe bastar para diagnóstico.

## IAM de runtime

Las funciones se separan para reducir superficie:

- Ingreso: enviar a colas, sesiones/datos administrativos, carga y validaciones Connect.
- Procesador: Connect/Participant, Meta secret, datos, colas y multimedia.
- Campañas: lectura de archivos, secreto Meta y estado de campañas.
- Multimedia: S3, Textract, Transcribe, Bedrock y envío de resultado a Connect.

Los accesos de Connect que no admiten ARNs granulares pueden requerir `Resource: '*'`; compénselos con roles dedicados, condición de cuenta/instancia cuando sea posible y monitoreo.

## Protección de datos

- KMS con rotación protege los recursos del stack.
- S3 bloquea acceso público, usa versionado y políticas de ciclo de vida.
- DynamoDB usa recuperación a un punto en el tiempo y TTL para elementos temporales.
- URLs de carga y vista previa tienen vigencia corta. El enlace estable apunta a un token opaco, no al nombre de bucket ni a credenciales.
- CloudFront aplica HTTPS y encabezados de seguridad; la app limita `frame-ancestors` a dominios de Connect.
- La eliminación lógica de campañas no equivale a borrar respuestas; defina retención legal por organización.

## Datos sensibles y logs

No registre tokens, firmas, URLs S3 firmadas completas, texto confidencial, documentos, audios ni payloads de contacto completos. Use IDs correlacionables, hash cuando corresponda y métricas agregadas. Controle acceso y retención de CloudWatch Logs.

## Lista previa a producción

- [ ] Secreto sin valores por defecto ni copias en Git/CI.
- [ ] Token Meta de producción con permisos y duración adecuados.
- [ ] Perfil de despliegue de privilegio mínimo.
- [ ] KMS y protección de borrado activas.
- [ ] Buckets privados y CORS/CSP revisados.
- [ ] Security/routing profiles de Connect revisados.
- [ ] Aplicación 3P visible solo para perfiles autorizados.
- [ ] `AdminAppAuthMode=disabled` hasta implementar y probar un adaptador SSO verificable en backend; el modo preview no se usa en producción.
- [ ] Alarmas confirmadas por un destinatario real de operaciones.
- [ ] Retención, privacidad y consentimiento aprobados.
- [ ] Prueba de rotación y rollback documentada.
