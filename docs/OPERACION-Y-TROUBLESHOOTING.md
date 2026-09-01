# Operación y troubleshooting

## Vista operativa

CloudFormation crea dos AWS Resource Groups y un dashboard CloudWatch:

- `<ProjectName>-<Environment>-recursos`, basado en el stack CloudFormation;
- `<ProjectName>-<Environment>-etiquetados`, basado en tags `Application` y `Environment`, útil para incluir recursos Connect que admiten tags.

Los outputs `PlatformResourceGroupArn` y `TaggedPlatformResourceGroupArn` exponen ambos grupos. El dashboard muestra:

- invocaciones y errores de las cuatro Lambdas;
- edad del mensaje más antiguo en conversaciones, campañas, multimedia y puente;
- cantidad visible en cada DLQ.

Los outputs exponen el nombre del dashboard y los log groups. La revisión Git desplegada aparece como `DeploymentRevision` y variable de entorno de funciones, lo que permite comparar AWS con el repositorio sin descargar paquetes.

## Logs

```text
/aws/apigateway/<ProjectName>-<Environment>
/aws/lambda/<ProjectName>-<Environment>-lambda-redes-sociales-ingreso
/aws/lambda/<ProjectName>-<Environment>-lambda-redes-sociales-procesador
/aws/lambda/<ProjectName>-<Environment>-lambda-redes-sociales-campanas
/aws/lambda/<ProjectName>-<Environment>-lambda-redes-sociales-multimedia
```

Busque por `requestId`, `message_id`, `contact_id`, `campaign_id`, `flow_token` o nombre de trabajo Transcribe. No pegue payloads completos en tickets; elimine teléfonos, nombres, tokens, firmas y URLs firmadas.

Ejemplo de consulta, ajustando el nombre:

```powershell
aws logs tail "/aws/lambda/proyecto-dev-lambda-redes-sociales-procesador" `
  --since 1h `
  --follow `
  --profile "mi-perfil" `
  --region us-east-1
```

## Métricas de aplicación

La Lambda emite Embedded Metric Format en `<ProjectName>/<Environment>/Messaging`, entre ellas:

- `MessagesProcessed` por canal/dirección/tipo.
- `CampaignMessagesSubmitted`.
- `TemplateDslRejected` con razón saneada.
- resultado de trabajos asíncronos cuando aplica.

El JSON EMF debe escribirse como una línea JSON válida, sin prefijo del logger; de lo contrario CloudWatch no crea la métrica.

## Alarmas

El stack vigila:

- cualquier mensaje visible en las cuatro DLQ;
- edad elevada en conversaciones, campañas o multimedia;
- errores de cada Lambda;
- respuestas 5xx de API Gateway.

Si `AlarmEmail` tiene valor, confirme manualmente la suscripción SNS. Una suscripción pendiente no notifica. `OK` no demuestra entrega funcional; el plan sintético/E2E sigue siendo necesario.

## Diagnóstico automatizado

```powershell
.\scripts\diagnose_whatsapp.ps1 `
  -ConfigFile .\config\mi-empresa.local.psd1 `
  -AwsProfile "mi-perfil" `
  -LookbackHours 24
```

El script comprueba identidad AWS, stack, revisión, recursos, runtime, mappings, colas/DLQ, presencia de claves del secreto, flows/módulo y alarmas. Lee el secreto para verificar nombres de claves, pero no debe imprimir valores. Ejecútelo solo con un perfil autorizado y una terminal cuya salida no exponga datos.

## Árbol de diagnóstico

### Meta no valida el webhook

1. Confirme URL exacta del output `WebhookUrl`.
2. Confirme `WA_VERIFY_TOKEN` idéntico, sin mostrarlo.
3. Revise log de ingreso y API 4xx/5xx.
4. Confirme que el stack/región existe y API Gateway responde.

### Meta acepta, pero Connect no recibe

1. Verifique firma: `invalid_signature` indica secreto/app incorrectos.
2. Revise cola de conversaciones: visible, en proceso, edad y DLQ.
3. Revise errores/throttles del procesador.
4. Confirme `DEFAULT_CONTACT_FLOW_ID` efectivo e instancia.
5. Confirme que el flow está activo, invoca el módulo y usa una cola válida.
6. Confirme routing profile, estado/concurrencia del agente y horario.
7. Busque `source_message_id` en atributos/contacto.

### El agente ve un chat vacío o sin contexto

1. Confirme que el primer mensaje no excedió límites de Connect.
2. Revise `initial_message`, `customer_name`, `customer_phone`, `social_user_id`.
3. Meta puede no entregar teléfono/nombre; el flow debe manejar campos vacíos.
4. Compruebe que no se abrió una segunda sesión por TTL o ID distinto.
5. Revise que el contact flow no sobrescriba atributos.

### El agente responde, pero WhatsApp no recibe

1. Confirme que `StartContactStreaming` ocurrió al crear el contacto.
2. Revise SNS, suscripción y cola puente.
3. Confirme que el evento tiene `ParticipantRole=AGENT` y contenido.
4. Revise token/número/versión Graph en Secrets Manager/parámetro.
5. Busque respuesta de Meta y estado `FAILED`.
6. Determine si la ventana de atención exige plantilla aprobada.

### Archivo entrante no abre

1. Confirme que el token cambió de `PENDING` a `READY`.
2. Revise Lambda multimedia y DLQ.
3. Confirme objeto S3, Content-Type y Content-Disposition `inline`.
4. Pruebe antes del vencimiento.
5. Si el navegador descarga, valide soporte del MIME; no haga público el bucket.

### No llega transcripción

1. Confirme que el enlace/archivo sí quedó almacenado.
2. Revise extensión, MIME y tamaño.
3. Para OCR, busque errores Textract o texto bajo confianza.
4. Para audio/video, revise trabajo Transcribe y regla EventBridge.
5. Confirme acceso de Bedrock; un fallo debe caer en orden/salida original, no perder el texto.
6. Compruebe que la sesión Connect seguía activa cuando terminó.
7. Sin voz/texto útil, la omisión de `Transcripción:` es comportamiento correcto.

### `[plantilla]` salió como texto normal

1. Primera línea no vacía debe ser `[plantilla]`.
2. Revise `TemplateDslMode` y allowlist normalizada.
3. Confirme que el mensaje procede del agente/sistema esperado.
4. Busque `TemplateDslRejected` y su razón.

### Botón no usa el flow esperado

1. Compare el ID técnico del botón, no solo su texto.
2. Revise registro `ROUTE#identidad / BUTTON#id` y TTL.
3. La ruta solo elige flow al crear sesión nueva.
4. Confirme que el flow está publicado y pertenece a la misma instancia.

### Campaña sin respuestas

1. `ACCEPTED` no equivale a `DELIVERED`.
2. Revise estado/aprobación/calidad de plantilla.
3. Confirme que el Flow está publicado y vinculado.
4. Confirme `flow_token=campaign_id`.
5. Busque respuestas en campaña y `CAMPAIGN#unassigned`.

## Manejo de DLQ

1. Detenga el reenvío automático.
2. Inspeccione una copia o use `ReceiveMessage` sin borrar.
3. Correlacione log y determine causa común.
4. Corrija código/configuración y despliegue en desarrollo.
5. Pruebe idempotencia con el mismo evento.
6. Redrive en lote pequeño y observe.
7. Documente cantidad, período, causa y resultado.

No purgue una DLQ para apagar una alarma. Los mensajes pueden ser la única evidencia de pérdida.

## Rutina recomendada

Diaria: alarmas, DLQ, cola atrasada, fallos Meta. Semanal: tasas de entrega/respuesta, latencia, expiraciones y costos. Mensual: permisos, secreto/token, retención y restauración. Trimestral: runtime, Graph API, dependencias, modelo Bedrock y prueba de rollback.
