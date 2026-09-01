# Control visual y funcional de la app 3P

## Entorno

- Probar dentro de Amazon Connect Agent Workspace, no solo en una pestaña directa.
- Cubrir anchos habituales del panel y zoom 80 %, 100 %, 125 % y 200 %.
- Probar Chrome/Edge administrados que use la organización.
- Usar configuración y datos ficticios.

## Navegación lateral

- [ ] El menú permanece legible sin cubrir contenido.
- [ ] Estado activo es evidente por color y texto.
- [ ] Íconos tienen etiqueta accesible.
- [ ] Solo aparecen módulos permitidos para el perfil.
- [ ] Navegación por teclado conserva foco visible.

## Sesión Connect

- [ ] Con `AdminAppAuthMode=disabled`, se muestra un bloqueo seguro y no se habilitan módulos administrativos.
- [ ] En laboratorio, `connect-context-preview` no muestra formulario y se identifica claramente como no apto para producción.
- [ ] Tras implementar SSO, una sesión federada vigente no pide de nuevo correo, contraseña ni código; sin sesión, el IdP aplica su recorrido normal.
- [ ] El estado de carga describe la comprobación en curso sin afirmar que el contexto SDK es autenticación verificable.
- [ ] Acceso directo fuera de Agent Workspace muestra error seguro.
- [ ] Token efímero o sesión SSO vencidos permiten reintentar sin perder datos no enviados.
- [ ] Nombre/rol del agente se muestran solo cuando fueron validados.

## Formularios

- [ ] Etiquetas, ayuda y errores están asociados al control.
- [ ] Validación ocurre antes de encolar.
- [ ] Botón de envío indica progreso y evita doble clic.
- [ ] Límites de Meta se explican cerca del campo.
- [ ] Una acción irreversible requiere confirmación específica.
- [ ] Fechas/horas/moneda respetan la localización configurada.

## Vista previa WhatsApp

- [ ] Se identifica como referencial, no captura exacta del dispositivo.
- [ ] Título, información, pregunta, pie y botones respetan jerarquía.
- [ ] Negrita no muestra asteriscos duplicados.
- [ ] Variables sin resolver son visibles como error antes de enviar.
- [ ] Nombre del archivo es clicable y no muestra URL larga.
- [ ] Texto largo/Unicode no rompe el panel.

## Campañas y encuestas

- [ ] Diferencia entre borrador, publicado y aprobado es clara.
- [ ] `accepted`, `delivered`, `read` y `responses` no se mezclan.
- [ ] Tipo de campaña filtra plantillas compatibles.
- [ ] Mapeo de variables muestra destinatarios excluidos.
- [ ] Respuestas filtradas y exportadas coinciden.
- [ ] Papelera/restauración visible solo al rol autorizado.

## Estados

- [ ] Carga, vacío, éxito, error 4xx, error 5xx y caché obsoleta tienen diseño propio.
- [ ] Un `202` dice “aceptado/encolado”, no “entregado”.
- [ ] Error no expone token, ARN sensible, stack trace ni payload.
- [ ] Reintento no duplica campaña/cotización.

## Marca y accesibilidad

- [ ] Logo no se deforma y tiene contraste.
- [ ] Nombre no se duplica si el logo ya lo incluye.
- [ ] No quedan textos o activos de otra instalación.
- [ ] Contraste WCAG AA para texto/controles principales.
- [ ] Orden de tabulación, lector de pantalla y mensajes de error probados.
- [ ] El significado no depende solo de color.

## Evidencia

Capture por caso: commit, ambiente, perfil/rol ficticio, tamaño de panel, resultado y defecto. Redacte nombre, teléfono, contenido, URL firmada e identificadores antes de compartir. No guarde evidencia de clientes en el repositorio público.
