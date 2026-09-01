# Índice de documentación

Esta documentación describe una plataforma genérica. Los ejemplos usan nombres, teléfonos, cuentas e identificadores ficticios.

## Diseño y capacidades

- [Arquitectura](ARQUITECTURA.md): recorridos de datos, cuatro Lambdas, colas, persistencia y decisiones técnicas.
- [Canales y capacidades](CANALES-Y-CAPACIDADES.md): matriz honesta de WhatsApp, Instagram, Messenger y otros canales.
- [Amazon Connect](AMAZON-CONNECT.md): flow inicial, módulo de contexto, colas, atributos, streaming y enrutamiento.
- [Mensajes y multimedia](MENSAJES-Y-MULTIMEDIA.md): tipos de mensaje, vista previa, OCR, transcripción y adjuntos.
- [Plantillas en texto plano](PLANTILLAS-TEXTO-PLANO.md): gramática `[plantilla]`, botones, listas y variables.
- [Campañas, WhatsApp Flows y encuestas](CAMPANAS-FLOWS-Y-ENCUESTAS.md): ciclo de plantillas Meta, respuestas y datos.
- [Extensión por adaptadores](EXTENSION-POR-ADAPTADORES.md): cómo añadir canales sin romper el núcleo.

## Implementación

- [Instalación](INSTALACION.md): requisitos y despliegue paso a paso en una cuenta nueva.
- [Aplicación 3P](APLICACION-3P.md): integración en Agent Workspace, modo de laboratorio y adaptador SSO de producción pendiente de implementación.
- [API administrativa](API-ADMINISTRATIVA.md): contrato, autenticación y operaciones disponibles.
- [Seguridad y permisos](SEGURIDAD-Y-PERMISOS.md): IAM, secretos, cifrado, protección de datos y controles.
- [Personalización y marca](PERSONALIZACION-Y-MARCA.md): nombres, logo, textos y aislamiento por negocio.

## Calidad y operación

- [Plan de pruebas](PRUEBAS.md): validación local, integración y aceptación.
- [Operación y troubleshooting](OPERACION-Y-TROUBLESHOOTING.md): tablero, logs, métricas, alarmas y diagnóstico.
- [Mantenimiento y rollback](MANTENIMIENTO-Y-ROLLBACK.md): versiones, Graph API, runtime de Python, cambios y reversión.
- [Control visual de la app](../design-qa.md): lista de comprobación de interfaz y accesibilidad.

## Orden recomendado

Para una primera instalación lea, en este orden: Arquitectura → Canales → Instalación → Seguridad → Amazon Connect → Pruebas → Operación.
