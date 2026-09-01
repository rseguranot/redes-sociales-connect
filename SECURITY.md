# Política de seguridad

## Reportar una vulnerabilidad

No abra un issue público con una vulnerabilidad, token, dato personal o detalle explotable. Use **Security → Report a vulnerability** en GitHub para crear un aviso privado de seguridad.

Incluya, sin secretos reales:

- componente y versión/commit;
- impacto y condiciones;
- pasos mínimos con datos ficticios;
- evidencia redactada;
- mitigación sugerida, si existe.

No pruebe contra cuentas, números, agentes o datos de terceros sin autorización.

## Alcance

Se aceptan reportes sobre código, CloudFormation, IAM, webhook, sesiones administrativas, app 3P, aislamiento de datos, URLs de multimedia, dependencias y exposición de secretos.

Errores de configuración propios de una instalación, indisponibilidad de Meta/AWS y límites documentados no son vulnerabilidades del proyecto, aunque una configuración insegura reproducible sí puede serlo.

## Respuesta

Los mantenedores intentarán confirmar recepción, clasificar impacto, preparar una corrección y coordinar publicación. No se promete un plazo contractual. Las correcciones críticas deben incluir prueba de regresión y guía de rotación/rollback.

## Si un secreto se expone

1. Revoque/rote primero el token o credencial en su proveedor.
2. Restrinja acceso a logs/artefactos afectados.
3. Determine alcance mediante CloudTrail/Meta y registros saneados.
4. Elimine el valor de la versión actual y, si es necesario, reescriba el historial con coordinación.
5. Redepliegue, pruebe y documente el incidente.

Borrar el texto de un commit nuevo no invalida una credencial ya publicada.

## Versiones soportadas

La rama predeterminada recibe correcciones. Instalaciones antiguas deben actualizar o mantener un backport privado. Runtimes, Meta Graph API y dependencias tienen ciclos externos; consulte [Mantenimiento](docs/MANTENIMIENTO-Y-ROLLBACK.md).
