# Contribuir

## Antes de empezar

- Abra un issue para cambios grandes de contrato, infraestructura o UI.
- No incluya nombres, cuentas, teléfonos, capturas, logos ni datos de clientes.
- No incluya tokens, secretos, URLs firmadas o configuraciones locales.
- Mantenga WhatsApp como capacidad implementada y marque adaptadores futuros con honestidad.

## Flujo

1. Cree una rama desde la rama predeterminada.
2. Haga cambios pequeños y documentados.
3. Añada pruebas para comportamiento nuevo/regresión.
4. Ejecute toda la validación.
5. Revise `git diff` y escanee secretos/PII.
6. Abra un pull request con impacto, prueba y rollback.

```powershell
python -m unittest discover -s tests -v
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml

Push-Location app
npm ci
npm run test:sites
npm run build
Pop-Location

git diff --check
```

## Convenciones

- Python: funciones pequeñas, manejo explícito de errores de AWS/proveedor y logs estructurados sin PII.
- CloudFormation: parámetros genéricos, `DeletionPolicy` para datos, tags, outputs útiles y permisos mínimos.
- Frontend: configuración de runtime, accesibilidad y autorización también en backend.
- Mensajería: preserve idempotencia, orden por conversación y DLQ.
- IA: salida estructurada, temperatura baja, validación exacta y fallback que no reescribe contenido.
- Documentación: español claro, ejemplos ficticios y estado real de cada canal.

## Cambios de contrato

Un cambio a `social-message/1.0`, atributos Connect, claves DynamoDB, DSL o API administrativa exige:

- compatibilidad/migración documentada;
- fixtures de versión anterior y nueva;
- actualización de todos los consumidores;
- plan de despliegue gradual y rollback.

## Pull request

Describa:

- problema y resultado;
- archivos/servicios afectados;
- seguridad, costos y datos;
- pruebas locales/E2E;
- parámetros/migraciones;
- rollback;
- documentación actualizada.

Para vulnerabilidades use el proceso privado de [SECURITY.md](SECURITY.md), no un pull request público inicial.
