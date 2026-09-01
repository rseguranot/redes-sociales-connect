# Mantenimiento, versiones y rollback

## Fuente de verdad

- Git identifica el código y la documentación.
- CloudFormation identifica la infraestructura efectiva.
- `DeploymentRevision` relaciona ambos.
- Secrets Manager contiene credenciales, fuera de Git.
- Meta conserva estado real de plantillas, Flows, número y webhooks.
- DynamoDB/S3 conservan estado y datos operativos.

No edite recursos del stack manualmente salvo procedimiento de incidente documentado; la deriva dificulta rollback y réplica.

## Cadencia

### Cada cambio

1. Rama y descripción de impacto.
2. Pruebas unitarias/frontend.
3. `sam validate --lint` y `sam build`.
4. Escaneo de secretos/PII.
5. Change set revisado.
6. Despliegue y E2E en desarrollo.
7. Aprobación y promoción del mismo commit.
8. Observación de alarmas/colas/entregas.

### Mensual

- alarmas y DLQ;
- permisos Connect/IAM;
- token/secreto y su vencimiento;
- costos, retención, tamaños y concurrencia;
- recuperación DynamoDB/S3.

### Trimestral

- runtimes Lambda soportados;
- versión Meta Graph API y cambios de webhook;
- versiones de WhatsApp Flows;
- dependencias Python/npm;
- modelo/perfil Bedrock y disponibilidad regional;
- límites Textract/Transcribe/Connect;
- prueba de rollback y restauración.

## Runtime de Python

`LambdaRuntime` evita incrustar el runtime en cada función. Cuando AWS anuncie obsolescencia:

El valor predeterminado del repositorio es `python3.14` al 1 de septiembre de 2026. Confirme soporte en la región antes de cada despliegue; el parámetro existe precisamente para migrar sin reescribir cuatro funciones.

Use como fuente el calendario de [runtimes de AWS Lambda](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html), no una fecha copiada en un ticket antiguo.

1. Seleccione una versión soportada en la región/arquitectura.
2. Cree una rama de migración y cambie el parámetro/valor por defecto.
3. Revise compatibilidad de boto3/botocore y sintaxis.
4. Ejecute tests, lint/build y análisis de dependencias.
5. Despliegue en desarrollo y pruebe los cuatro modos.
6. Compare latencia, memoria, errores y resultados OCR/transcripción.
7. Promueva antes de la fecha en que AWS bloquee actualizaciones.

No espere al fin de soporte ni cambie producción directamente. El diagnóstico compara runtime de funciones con el declarado por el stack.

## Meta Graph API

`MetaGraphVersion` debe avanzar de forma deliberada:

El repositorio usa `v26.0` por defecto al 1 de septiembre de 2026. Esa referencia solo indica el punto de partida probado del código; no asegura vigencia futura ni autoriza saltarse versiones.

Use el [changelog oficial de Meta Graph API](https://developers.facebook.com/docs/graph-api/changelog/) y la documentación de WhatsApp Cloud API como fuentes de migración.

1. Revise changelog y versión admitida por WhatsApp.
2. Identifique campos/IDs/estados/errores que cambian.
3. Añada fixtures y pruebas contractuales.
4. Pruebe webhook, descarga/subida de media, plantillas, Flows y estados.
5. Cambie desarrollo, observe y luego producción.

Nunca use “latest” implícito. Una versión de API y una plantilla aprobada tienen ciclos distintos.

## Registro de la aplicación en AWS

Desde el 30 de julio de 2026, myApplications dejó de aceptar aplicaciones nuevas o actualizaciones, y AWS mantiene Application Manager/AppRegistry sin altas nuevas para nuevos clientes. No agregue una dependencia nueva a esos servicios para “agrupar” este producto. La unidad de aplicación soportada aquí es:

```text
stack AWS SAM/CloudFormation
  + tags Application/Environment/ManagedBy
  + AWS Resource Groups
  + dashboard y alarmas CloudWatch
```

Revise periódicamente los avisos oficiales de [myApplications](https://docs.aws.amazon.com/awsconsolehelpdocs/latest/gsg/document-history.html) y [Application Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/application-manager-availability-change.html), pero no migre por moda: cualquier reemplazo debe poder crearse en cuentas nuevas, declararse en CloudFormation y probarse sin cambios manuales.

## Bedrock, Textract y Transcribe

- Mantenga el ID de modelo como parámetro.
- Verifique autorización y disponibilidad antes del despliegue.
- La salida de Bedrock debe seguir esquema y permutación exacta; el fallback conserva texto.
- Versione prompts con tests que demuestren no reescritura.
- Cambiar idioma Transcribe exige prueba con audios reales autorizados.
- Cambios de modelo no deben promoverse solo por calidad visual; compare exactitud, latencia y costo.

## Dependencias y frontend

- Use `npm ci`, no una instalación no bloqueada.
- Revise CVE y licencias antes de actualizar.
- No confirme `node_modules`, builds ni config de un negocio.
- Compile una vez por commit/ambiente con config pública generada.
- Verifique Agent Workspace, CSP y responsive después de dependencias de Connect.

## Despliegue seguro

- Use stacks separados para `dev` y `prod`.
- `ProjectName` es el nombre base y `Environment` participa en la mayoría de nombres físicos; mantenga única cada combinación. `StackName`, `AdminAppNamespace` y los nombres de flow/módulo de Connect deben aislarse explícitamente.
- Revise reemplazos de KMS, bucket, tabla, Flow y AppIntegrations.
- Active protección de borrado en producción.
- Mantenga `DeletionPolicy`/`UpdateReplacePolicy: Retain` para datos y recursos difíciles de recrear.
- Evite cambiar `ProjectName` en un stack existente: cambia nombres físicos.
- El flow y módulo Connect administrados usan `Retain`; pueden permanecer tras borrar/reemplazar el stack. Antes de recrear, decida si importarlos, reutilizarlos, renombrarlos o eliminarlos manualmente para evitar colisiones.
- No mezcle despliegue y corte de webhook en una sola acción irreversible.

## Rollback de aplicación/Lambda

1. Identifique último commit aceptado y estado de datos.
2. Genere/inspeccione un change set desde ese commit.
3. Actualice el stack; deje que CloudFormation revierta funciones/configuración.
4. Reconstruya y publique la app desde el mismo commit; invalide CloudFront.
5. No restaure un bundle manual sin registrar revisión.
6. Ejecute smoke bidireccional y observe DLQ.

El stack actual no usa aliases/versiones Lambda como mecanismo de cambio de tráfico. El rollback es una actualización CloudFormation al artefacto anterior; una futura estrategia canary requerirá alias, CodeDeploy y alarmas específicas.

## Rollback del webhook Meta

1. Conserve callback y verify token de la integración anterior antes del corte.
2. Si la nueva entrada falla, revierta únicamente el callback/suscripción.
3. Evite dos procesadores activos sobre los mismos eventos.
4. No purgue colas; decida qué eventos pueden redirigirse sin duplicar.
5. Verifique ambos sentidos en la ruta restaurada.

Cambiar el webhook no revierte campañas ya enviadas ni respuestas almacenadas.

## Rollback de Flows/plantillas

No “edite hacia atrás” un Flow publicado. Use una plantilla/Flow anterior aún válido o cree una nueva versión. Deshabilite campañas que apunten al recurso defectuoso; conservar IDs es esencial para respuestas tardías.

## Datos

- No borre el stack como método de rollback.
- PITR de DynamoDB restaura a una tabla nueva; ensaye reconexión.
- Versionado S3 permite recuperar objetos, pero no reabre una sesión Connect.
- TTL es borrado eventual; no lo use como borrado inmediato contractual.
- Una restauración debe preservar correlación `campaign_id`, `message_id`, `contact_id` e identidad.

## Registro de cambios

Cada release debe registrar:

- versión/commit;
- parámetros/runtimes/API/modelo cambiados;
- migraciones de datos o Connect;
- pruebas realizadas;
- riesgos y rollback exacto;
- ventana de observación y responsable operativo.
