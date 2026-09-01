# Aplicación 3P para Amazon Connect

## Alcance

La aplicación web de `app/` es una consola administrativa opcional integrada en Amazon Connect Agent Workspace. Complementa el CCP; **no sustituye la bandeja omnicanal ni muestra un chat paralelo**.

Módulos incluidos en la implementación actual:

- cotizaciones y envío de adjuntos;
- catálogo/gestión de plantillas;
- segmentos y campañas;
- diseñador y publicación de WhatsApp Flows;
- respuestas y exportación;
- configuración de acceso por perfil.

La interfaz se incluye para que la solución sea reproducible aunque una instalación decida sustituirla por otra herramienta.

En la plantilla actual, CloudFormation siempre crea el bucket, la distribución, `AWS::AppIntegrations::Application` y su asociación con Connect. “Opcional” se refiere al uso operativo: con `AdminAppAuthMode=disabled` el sitio puede estar asociado/visible, pero sus funciones administrativas permanecen bloqueadas.

## Acceso y autenticación

La interfaz no incluye un formulario propio. Sin embargo, AWS documenta que las aplicaciones 3P deben proporcionar su propia autenticación; el SDK entrega contexto dentro del iframe, pero no un token de identidad criptográficamente verificable por este backend.

Por seguridad, `AdminAppAuthMode` usa `disabled` de forma predeterminada:

- `disabled`: las rutas administrativas rechazan el inicio de sesión de la app.
- `connect-context-preview`: habilita el recorrido actual solo para un laboratorio controlado. Valida origen, instancia, usuario, perfiles y permiso de aplicación, pero un navegador autorizado aún puede alterar los datos enviados al backend; no es autenticación de producción.

La solución definitiva es federar la app con el mismo IdP/SSO usado por Connect. Con una sesión SSO vigente el agente no vuelve a escribir correo, contraseña ni código, y el backend recibe una identidad verificable. Ese adaptador no está implementado en este repositorio: `template.yaml` solo acepta `disabled` y `connect-context-preview`. Debe añadirse y probarse antes de habilitar la consola administrativa en producción. Consulte la [guía oficial de SSO para aplicaciones 3P](https://docs.aws.amazon.com/connect/latest/adminguide/3p-apps-sso.html) y la [guía de autenticación del Agent Workspace](https://docs.aws.amazon.com/agentworkspace/latest/devguide/getting-started-authentication.html).

El recorrido de laboratorio es:

```text
Agent Workspace autenticado
  └─► carga aplicación autorizada
        └─► SDK obtiene identidad/contexto
              └─► POST /admin/session
                    └─► backend consulta Amazon Connect
                          └─► token efímero en memoria
```

La aplicación usa los paquetes oficiales de Amazon Connect para obtener datos del agente/contacto. El backend valida que:

- el `Origin` coincide con la distribución CloudFront configurada;
- el ARN pertenece a la instancia esperada;
- `DescribeUser` confirma que el ARN corresponde a un usuario de esa instancia y obtiene sus routing/security profiles; no demuestra una sesión activa de Agent Workspace;
- sus routing/security profiles permiten acceso;
- el perfil tiene permiso `ACCESS` sobre la aplicación;
- el módulo solicitado está concedido.

El token de sesión administrativa del modo de laboratorio dura pocos minutos y DynamoDB almacena su hash, no el valor. La app lo mantiene en memoria, no en un archivo de configuración. Las credenciales de Meta y el token interno del CCP nunca se envían al navegador.

## Roles y módulos

El backend deriva rol y permisos de Amazon Connect:

- `agent`: uso operativo concedido.
- `admin`: gestión según permisos del security profile.
- `developer`: routing/security profile incluido explícitamente en parámetros de despliegue.

Developer puede administrar la visibilidad y matriz de permisos. La interfaz oculta controles no autorizados, pero cada endpoint vuelve a comprobarlos. Un perfil no debe poder concederse a sí mismo un rol superior desde el navegador.

## Contexto del contacto

Cuando hay un contacto activo, la app puede usar nombre, teléfono/identidad y `contact_id` para prellenar una cotización. Si no hay contacto activo, una operación de campaña usa sus destinatarios explícitos. La app no debe asumir que siempre existe teléfono: algunas identidades sociales solo contienen ID/username.

## Despliegue

CloudFormation crea:

- bucket S3 privado con versionado;
- CloudFront con Origin Access Control y encabezados de seguridad;
- `AWS::AppIntegrations::Application` con alcance `CROSS_CONTACTS`;
- asociación con la instancia Connect;
- permisos mínimos de lectura de agente/contacto;
- API administrativa dentro del mismo HTTP API.

El script genera `app/public/config.js` con valores públicos de runtime: región, URL de API, nombre, lema, logo, `Locale` y `DefaultTemplateLanguage`. Ese archivo nunca debe contener secretos o IDs personales.

Build reproducible:

```powershell
Push-Location app
npm ci
npm run test:sites
npm run build
Pop-Location
```

El script de despliegue publica `dist/client`, elimina archivos obsoletos del bucket e invalida CloudFront.

## Asignación en Connect

Después del primer despliegue:

1. Confirme la asociación de AppIntegrations.
2. Autorice la aplicación en un security profile de prueba.
3. Abra Agent Workspace con un usuario de ese perfil.
4. En laboratorio, habilite explícitamente `connect-context-preview` y compruebe el recorrido. En producción, mantenga `disabled` hasta implementar el adaptador SSO externo; después compruebe que el backend valida el token y que una sesión federada vigente no muestra otro formulario.
5. Compruebe que otro perfil sin acceso no la ve.
6. Pruebe permisos de cada módulo con un agente, un administrador y un Developer.

Ocultar otras aplicaciones 3P es una decisión de configuración de Connect, no de este frontend. No elimine asociaciones ajenas desde CloudFormation.

## Cabeceras y navegador

- `frame-ancestors` limita el iframe a dominios de Amazon Connect.
- `connect-src` permite la API propia y APIs necesarias de AWS.
- HTTPS, HSTS, `nosniff` y política de referrer reducen exposición.
- S3 no sirve archivos públicamente; solo CloudFront puede leer el origen.
- CORS no es autorización. La API exige origen, sesión y permisos.

## Limitaciones

- El modo `connect-context-preview` no demuestra al backend la identidad del agente de forma criptográfica y no debe habilitarse en producción.
- El repositorio no contiene todavía un valor `sso` para `AdminAppAuthMode` ni el verificador de tokens del IdP; desplegar CloudFormation no completa por sí solo la autenticación de producción.
- Una sesión activa del navegador no sustituye permisos de Connect.
- La app no puede garantizar la aprobación de una plantilla Meta.
- Las exportaciones descargadas quedan bajo la política del equipo del usuario.
- La app no es un CRM ni un repositorio documental permanente.
- Cambios visuales no deben alterar el contrato de API sin versión/pruebas.

Consulte [API administrativa](API-ADMINISTRATIVA.md), [Seguridad](SEGURIDAD-Y-PERMISOS.md) y [Control visual](../design-qa.md).
