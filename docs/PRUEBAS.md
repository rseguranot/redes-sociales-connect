# Plan de pruebas

## Principios

- Probar primero en cuenta/instancia/cola/número de desarrollo.
- Usar identidades ficticias o autorizadas.
- Separar validación técnica, integración y aceptación de negocio.
- Capturar IDs/tiempos/estados; redactar PII y secretos.
- Una respuesta HTTP 200/202 no demuestra entrega de extremo a extremo.

## 1. Pruebas locales obligatorias

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

Antes de commit:

```powershell
git diff --check
rg -n -i "access[_-]?token|app[_-]?secret|password|secret-string" . `
  --glob '!app/package-lock.json' `
  --glob '!docs/*.md'
```

Revise cada coincidencia: nombres de variables/documentación son válidos; valores reales no.

## 2. Infraestructura

- `ValidateOnly` termina sin modificar AWS.
- Change set solo contiene recursos esperados.
- Cuatro Lambdas activas con runtime/revisión correcta.
- Event source mappings habilitados.
- SQS cifradas, DLQ asociadas y vacías.
- SNS policy restringida a Connect de la cuenta/instancia.
- S3 privado, versionado y ciclo de vida.
- DynamoDB PITR/TTL y protección según ambiente.
- Flow/módulo activos y cola correcta.
- Dashboard existe; alarmas en `OK`; suscripción confirmada.
- El Resource Group basado en stack lista la aplicación y el grupo basado en tags incluye los recursos compatibles del ambiente, incluidos flow/módulo Connect etiquetados.

## 3. Matriz de mensajes

Para cada caso anote hora, ID Meta, contact ID, resultado Connect, resultado de respuesta y estado final:

| Caso | Cliente → agente | Agente → cliente |
|---|---:|---:|
| Texto simple | Obligatorio | Obligatorio |
| Negrita/cursiva/tachado/código | Obligatorio | Obligatorio |
| Emoji y Unicode | Obligatorio | Obligatorio |
| Imagen JPEG/PNG | Obligatorio | Obligatorio |
| PDF | Obligatorio | Obligatorio |
| Audio/nota de voz | Obligatorio | Obligatorio |
| Video compatible | Obligatorio | Obligatorio |
| Sticker | Obligatorio | No aplicable en salida actual |
| Ubicación | Obligatorio | No aplicable en salida actual |
| Contacto | Obligatorio | No aplicable en salida actual |
| Reacción | Obligatorio | No aplicable en salida actual |
| Botón/lista | Obligatorio | Obligatorio dentro de ventana |
| Plantilla aprobada | Respuesta | Obligatorio fuera de ventana |

Incluya archivos pequeños, cercanos al límite y no soportados. Un rechazo claro y sin pérdida/reintento infinito es un resultado válido para un formato no admitido.

## 4. Identidad y Connect

- Nombre y teléfono aparecen cuando Meta los entrega.
- `social_user_id` existe aun sin teléfono.
- Display name no excede límites y puede incluir teléfono sin duplicarlo.
- Atributos canónicos y alias están disponibles en el flow.
- Módulo marca `social_context_version/status`.
- Número/identidad normal recorre el flow predeterminado.
- Identidad allowlist recorre el flow/cola de desarrollo.
- Identidad fuera de allowlist no se desvía.
- Agente correcto recibe el contacto por routing profile, no por casualidad.
- Sesión existente conserva conversación; sesión cerrada abre contacto nuevo.

## 5. Multimedia e IA

- El enlace usa nombre original cuando Meta lo entrega.
- Cuando no existe nombre, el generado es legible y único.
- Link corto abre antes del vencimiento y falla después.
- S3 permanece privado; no aparece una URL firmada larga en chat.
- Navegador previsualiza tipos compatibles y descarga de forma segura los demás.
- Imagen con texto claro genera `Transcripción:` exacta y organizada.
- Imagen sin texto útil no genera basura.
- Texto en columnas se ordena sin alterar palabras/IDs.
- Audio con voz genera transcripción; audio silencioso no envía texto vacío.
- Falla de Bedrock conserva orden geométrico/salida Transcribe.
- Sesión cerrada conserva artefacto y registra imposibilidad de entregar transcripción.

## 6. DSL `[plantilla]`

- Mensaje sin marcador queda sin cambios.
- Modo `disabled`, `allowlist` y `enabled`.
- Información sin opciones.
- Pregunta sin asteriscos y ya marcada; salida con un solo par.
- 1, 2 y 3 botones.
- 4 y 10 opciones como lista.
- 11 opciones rechazadas.
- Título/pie en límites y por encima.
- `[pie]` nativo solo con interacción; texto separado sin opciones.
- Variables resueltas, vacías y desconocidas.
- Etiquetas alias/acentuadas y etiqueta desconocida.
- Métrica `TemplateDslRejected` visible.

## 7. Campañas, cotizaciones y Flows

- App lista solo plantillas utilizables en el selector operativo.
- Carga de PDF usa KMS y URL vencida deja de funcionar.
- Cotización con plantilla + documento conserva orden por destinatario.
- Segmento deduplica teléfonos según estrategia.
- Variables se mapean solo con campos presentes.
- Campaña pequeña registra `accepted/delivered/read` por separado.
- Flow DRAFT valida, publica con confirmación y aparece en catálogo.
- Plantilla Flow pasa por aprobación antes de usar.
- `nfm_reply` llega al agente y a DynamoDB con `flow_token`.
- Token desconocido se guarda en `unassigned`.
- Respuestas/exportación coinciden con datos almacenados.
- Eliminación lógica requiere nombre/permiso; restauración no reenvía.
- Botón con ruta inicia el contact flow esperado en una sesión nueva.

## 8. App 3P y seguridad

- En laboratorio, el modo preview funciona solo al habilitarlo explícitamente.
- Tras implementar el adaptador SSO externo, producción recibe una identidad verificable y una sesión federada vigente evita un segundo formulario. El repositorio actual no ofrece un modo de autenticación de producción listo para activar.
- Con `AdminAppAuthMode=disabled`, `/admin/session` devuelve `503 admin_auth_not_configured`.
- Acceso directo fuera de Connect no obtiene sesión.
- Origin incorrecto, token ausente/vencido y rol falso se rechazan.
- Perfil autorizado ve la app; perfil no autorizado no.
- Agente, admin y Developer ven únicamente sus módulos/acciones.
- El frontend no contiene secretos al inspeccionar bundle/red.
- CSP/CORS y buckets privados pasan revisión.
- Logs no muestran tokens, firma, URLs completas ni documentos.

## 9. Resiliencia

- Repetir el mismo webhook no duplica contacto/mensaje.
- Falla transitoria de Meta/S3/Connect produce reintento.
- Agotar reintentos lleva a DLQ y activa alarma.
- Una campaña lenta no aumenta edad de conversaciones.
- Multimedia lenta no bloquea el texto inicial.
- Throttling se observa y recupera sin desorden por conversación.
- Rollback restaura versión funcional y no elimina datos.

## Evidencia mínima

Conserve de forma segura:

- commit/revisión y stack;
- fecha, ambiente y ejecutor;
- casos y resultado esperado/real;
- IDs correlacionables redactados;
- capturas sin datos personales;
- dashboard/alarmas antes y después;
- defectos y decisión de aceptación.

No confirme evidencias con PII en este repositorio público.
