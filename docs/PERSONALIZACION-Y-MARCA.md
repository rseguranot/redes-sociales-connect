# Personalización y marca

## Objetivo

Cada instalación debe cambiar nombre, textos, logo y namespace sin bifurcar el código. La configuración del negocio vive en un archivo local ignorado y se transforma en parámetros CloudFormation/configuración pública del frontend.

## Campos principales

| Campo | Uso |
|---|---|
| `ProjectName` | Nombre base; la plantilla combina este valor con el ambiente en la mayoría de recursos AWS |
| `Environment` | Ambiente lógico `dev` o `prod`, usado en nombres, tags y métricas |
| `StackName` | Stack por ambiente/cuenta |
| `BusinessName` | Nombre visible de la organización |
| `BusinessTagline` | Texto secundario visible |
| `BrandLogoPath` | Archivo local que se publica con la app |
| `LogoIncludesName` | Evita duplicar nombre si ya aparece en el logo |
| `Locale` | Etiqueta BCP 47 para fechas/horas del frontend y exportaciones; no traduce contenido |
| `DefaultTemplateLanguage` | Código Meta inicial de nuevos borradores; no traduce contenido |
| `AdminAppName` | Nombre mostrado en Connect |
| `AdminAppNamespace` | Identificador único de AppIntegrations |

Ejemplo ficticio:

```powershell
BusinessName = 'Empresa de ejemplo'
BusinessTagline = 'Atención por canales digitales'
BrandLogoPath = 'branding/brand-logo.svg'
LogoIncludesName = $false
Locale = 'es-DO'
DefaultTemplateLanguage = 'es'
AdminAppName = 'Atención Social'
AdminAppNamespace = 'empresa-ejemplo-social-dev'
```

## Logo

El repositorio incluye un SVG neutral. Para una instalación real:

- use SVG cuando sea posible o PNG transparente de resolución suficiente;
- elimine metadatos personales;
- mantenga relación de aspecto y espacio de seguridad;
- prepare contraste para fondo claro/oscuro;
- incluya texto alternativo o nombre visible;
- no confirme el logo del cliente en este repositorio público sin autorización.

El script debe conservar extensión/MIME al publicar. No cambie `app/src` solo para sustituir un logo; use `BrandLogoPath` y runtime config.

## Configuración pública

`app/public/config.js` puede contener:

- región;
- URL base de API;
- nombre/lema;
- ruta pública del logo;
- locale de presentación/exportación;
- idioma inicial de borradores de plantillas Meta;
- banderas visuales no sensibles.

No puede contener token Meta, app secret, verify token, teléfonos, ARN de secreto, claves AWS ni listas de usuarios.

## Aislamiento

Para cada negocio/ambiente use:

- cuenta AWS separada cuando la política lo requiera;
- una combinación única de `ProjectName` + `Environment`; puede conservar el mismo nombre base entre `dev` y `prod`;
- `StackName`, `AdminAppNamespace`, `ManagedContactFlowName` y `ConnectContextModuleName` explícitamente únicos, porque no todos reciben el sufijo de ambiente;
- secreto Meta propio;
- buckets/tablas/KMS propios;
- instancia/cola/flows Connect propios;
- dominios y CSP generados por el stack;
- configuración local fuera de Git.

No use condicionales por nombre de empresa en Python/React. Toda excepción de negocio debe ser parámetro, regla de datos o adaptador con contrato documentado.

## Checklist visual

- [ ] Logo nítido y sin deformación.
- [ ] Nombre/lema correctos y no duplicados.
- [ ] Navegación lateral usable en ancho de Agent Workspace.
- [ ] Estados vacío/carga/error visibles.
- [ ] Contraste y foco de teclado.
- [ ] Vista previa WhatsApp marcada como referencial.
- [ ] Fechas, moneda e idioma acordes al negocio.
- [ ] Sin nombres, dominios o imágenes de otra instalación.

Consulte [design-qa.md](../design-qa.md).
