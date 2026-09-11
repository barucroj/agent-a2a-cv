# Agent CV

Documentación pendiente.

## Limitaciones conocidas

- `/.well-known/agent-card.json` se expone únicamente como metadata de descubrimiento
  para plataformas compatibles con Open Responses (permite usar el flujo "Importar
  desde tarjeta de agente"). **No es un agente A2A funcional**: no declara
  `supportedInterfaces` ni implementa los endpoints de tareas del protocolo A2A. La
  URL real de Open Responses vive en el campo no estándar `x-openResponsesUrl` de la
  tarjeta; si la plataforma no lo lee automáticamente, hay que pegar la "URL base" a
  mano en su formulario de alta de agente.
- El `securityScheme` de tipo Bearer declarado en la tarjeta describe la intención,
  pero el endpoint `/responses` todavía no valida ningún token — la autenticación real
  llega en el paso 9 del roadmap (rate limiting, validación de input, secretos). Esto es
  aceptable como estado temporal de desarrollo, pero es una declaración aspiracional:
  **pendiente explícito del paso 9** — confirmar que `/responses` efectivamente rechaza
  requests sin Bearer token antes de cerrar el proyecto, para que la tarjeta deje de
  declarar algo que el backend todavía no cumple.
- El spec de A2A Agent Card tiene versiones incompatibles en el propio repo oficial
  (`a2aproject/A2A`, verificado directamente): la variante v0.3 usa un campo plano
  `url` + `protocolVersion` a nivel raíz, mientras que la variante v1.0 (rama `main`
  actual) reemplaza eso por `supportedInterfaces[]` (lista de `{url, protocolBinding,
  protocolVersion}`). No hay forma de saber, sin probarlo contra la plataforma externa
  real, cuál de las dos espera su flujo de "Importar desde tarjeta de agente" — por eso
  optamos por omitir `supportedInterfaces` del todo y exponer la URL de Open Responses
  en el campo no estándar `x-openResponsesUrl` en vez de adivinar un formato.
