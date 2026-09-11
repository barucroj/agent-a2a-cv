# Agent CV

Documentación pendiente.

## Infraestructura (paso 4)

Stack: Terraform (state local, nunca se sube — ver `.gitignore`), Amazon ECR, Amazon ECS
Express Mode (Fargate + ALB provisionados automáticamente), CloudWatch. Todo vive en
`infra/`.

**Levantar la infraestructura** (requiere `aws configure --profile agent-cv` ya hecho):

```
cd infra
terraform init
terraform plan -out=tfplan.binary   # revisar antes de aplicar
terraform apply tfplan.binary
```

Por una dependencia circular (el servicio necesita que la imagen ya exista en ECR), la
primera vez hay que hacerlo en 2 fases:
1. `terraform apply -target=aws_ecr_repository.agent_cv` (y el resto de recursos IAM/log
   group que no dependen de la imagen).
2. Build + push de la imagen a ECR (ver `Dockerfile`).
3. `terraform apply` completo — ya con la imagen existente, crea el servicio.

El `image` del contenedor se resuelve por **digest real** vía `data "aws_ecr_image"`
(no por tag mutable), para no arriesgarse a desplegar un build viejo por accidente.

**Pendiente para el paso 11 (CI/CD):** hoy el `apply` inicial en una cuenta limpia falla
duro con `ImageNotFoundException` hasta hacer el bootstrap de 2 fases de arriba —
detectado por `/codex:review`. Se evaluó (y por ahora se descartó) resolverlo con un
default de imagen placeholder (`public.ecr.aws/nginx/nginx:latest`) condicionado por una
variable, para que el `apply` inicial "tenga éxito" sin el bootstrap manual: se descartó
porque cambia un fallo ruidoso e inmediato por un deploy silenciosamente no-funcional
(puerto/healthcheck no coinciden con nginx), justo el tipo de inconsistencia que este
proyecto evita a propósito. Si el paso 11 automatiza el despliegue vía CI/CD sin
intervención humana, revisar esto de nuevo con un mecanismo explícito (ej. un job de
bootstrap en el pipeline), no un placeholder silencioso.

**Bajar la infraestructura** (para no seguir gastando crédito):

```
cd infra
terraform destroy
```

## Limitaciones conocidas

- **Cómputo: ECS Express Mode, no App Runner.** El plan original de este proyecto era
  AWS App Runner, pero [AWS cerró App Runner a nuevos clientes](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)
  y recomienda explícitamente Amazon ECS Express Mode como reemplazo — mismo nivel de
  simplicidad operativa (una llamada, dos roles IAM, y AWS aprovisiona Fargate + ALB +
  autoscaling), sobre el feature set completo de ECS.
- **Bug conocido del provider de Terraform** (`hashicorp/terraform-provider-aws#45792`):
  cambios al bloque `environment` de `aws_ecs_express_gateway_service` no se propagan
  con `terraform apply` normal (in-place) — Terraform reporta éxito y actualiza su state,
  pero AWS nunca recibe el cambio real (confirmado comparando el state contra la task
  definition real en ECS). El workaround usado aquí es forzar un reemplazo completo:
  `terraform apply -replace=aws_ecs_express_gateway_service.agent_cv`. Cualquier cambio
  futuro a `primary_container.environment` en este recurso probablemente necesite el
  mismo workaround hasta que el bug se resuelva río arriba. Nota: un reemplazo completo
  genera una URL pública nueva (el hostname lo asigna AWS al azar) — por eso la app
  deriva `PUBLIC_BASE_URL` del header `Host`/`X-Forwarded-Proto` de cada request en vez
  de una variable de entorno inyectada al desplegar, así no hay que reconfigurar nada
  cuando el hostname cambia.
- **Permisos IAM amplios en el usuario de despliegue** (`agent-cv-deploy`, perfil
  `agent-cv`): tiene `IAMFullAccess` y `AmazonECS_FullAccess` adjuntos directamente (no
  políticas acotadas por recurso). Aceptado como trade-off de velocidad para este
  proyecto — Terraform necesita crear/gestionar roles IAM y todos los recursos de ECS
  Express Mode dinámicamente, y acotar esos permisos al mínimo exacto habría requerido
  iterar la política cada vez que se agregara un recurso nuevo.

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
