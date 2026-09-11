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

## Contexto y LLM (pasos 5-8)

**Contexto del perfil (paso 5-6):** se optó por inyección directa (el perfil completo en
`app/data/profile.md` se embebe en el system prompt, `app/context.py`) en vez de RAG —
el volumen de contenido de un CV cabe cómodo en el contexto de cualquier modelo actual,
y RAG habría agregado infraestructura (vector DB, pipeline de embeddings) y riesgo de
alucinación por fallos de retrieval sin necesidad real. El teléfono personal se excluye
por regex del contenido **antes** de construir el prompt (no solo con una instrucción de
"no lo reveles" — eso sería una protección probabilística, no determinística). El campo
`instructions` del cliente se trata como contexto de baja confianza en rol `user` (nunca
`system`, que le daría la misma autoridad que el prompt interno). `/v1/responses` valida
que `input` solo traiga mensajes `user`/`assistant` con contenido de texto (allowlist por
rol, no denylist) y rechaza roles `system`/`developer` inyectados por el cliente. El
logging de auditoría solo guarda metadata (motivo de rechazo, longitudes, tipos) — nunca
el contenido crudo de `instructions`/`input`, ni siquiera en requests rechazadas.

**LLM/proveedor (paso 7-8) — historial real de la decisión, no lineal:**
1. Se aprobó inicialmente Amazon Bedrock, pero la cuenta tenía la cuota de
   tokens-por-día en cero para Claude Haiku 4.5.
2. Para no bloquear el progreso, se cambió a la API directa de Anthropic (paquete
   `anthropic`, clave en Secrets Manager). Al probar localmente, la cuenta de Anthropic
   no tenía crédito de facturación disponible.
3. Se revirtió a Bedrock (la cuota ya se había resuelto, confirmado en el Playground de
   Bedrock) — decisión final, para no gastar crédito nuevo fuera del ya asignado al
   proyecto en AWS.

Modelo final: **`us.anthropic.claude-haiku-4-5-20251001-v1:0`** — un inference profile
de cross-region **geográfico (EEUU)**, no el ID base del modelo. Verificado contra la
ficha oficial del modelo: `us-east-1` no soporta invocación **In-Region** de Claude
Haiku 4.5 vía `bedrock-runtime`, solo cross-region (Geo o Global); se eligió el
geográfico sobre el global para mantener los datos dentro de EEUU.

**IAM para Bedrock:** permiso `bedrock:InvokeModel` acotado (no `bedrock:*` ni
`foundation-model/*`) en dos statements — uno sobre el ARN del inference profile, y otro
sobre los ARN de `foundation-model` (sin account id) en las regiones destino del
profile geográfico (us-east-1/us-east-2/us-west-2), acotado con una `Condition` al
profile de arriba. Es un requisito documentado de AWS para cross-region inference: el
permiso sobre el profile por sí solo no basta. El mismo permiso, mismo alcance, se le
dio también a `agent-cv-deploy` (el usuario de despliegue local) únicamente para poder
probar el flujo real antes de desplegar — ese usuario no está gestionado por Terraform
(se creó a mano), así que a partir de esta policy Terraform gestiona un recurso sobre un
usuario externo: si ese usuario se borra o renombra desde la consola, el state de
Terraform queda desincronizado solo para ese recurso.

**Región del contenedor:** `AWS_REGION` se inyecta como variable de entorno (única
fuente de verdad, debe coincidir con `var.aws_region`) — antes de esto, `app/llm.py`
tenía un fallback (`"us-east-1"`) independiente del de Terraform, que hubiera divergido
silenciosamente si `var.aws_region` cambiara alguna vez. Mismo bug de propagación de
`environment` documentado abajo, pero de bajo riesgo aquí porque la región
prácticamente nunca cambia (a diferencia de `PUBLIC_BASE_URL`, que cambiaba en cada
reemplazo).

**Mitigación de costo puntual (no reemplaza el paso 9):** `/v1/responses` rechaza
(400, antes de invocar Bedrock) si `instructions`+`input` combinados exceden 8,000
caracteres, y el tope de `max_output_tokens` (2,048, ya validado desde el paso 2) ahora
se aplica de verdad. Esto acota el costo de *una* request — **no hay autenticación, rate
limiting ni cuota por llamador todavía**: cualquiera puede mandar muchos requests válidos
y facturar Bedrock sin control. Es exactamente el riesgo #1 documentado desde el inicio
del proyecto; se acepta temporalmente hasta el paso 9 (auth Bearer real, rate limiting,
cuotas), que ya estaba planeado para esto.

**Pendiente de limpieza (no urgente):** el secreto `agent-cv/anthropic-api-key` en
Secrets Manager (creado en el intento #2 de arriba) ya no se usa — se deja sin borrar
por ahora, sin costo real de mantenerlo.

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
  cuando el hostname cambia. (Actualización paso 8: se agregó `AWS_REGION` a
  `environment` para que la app y `iam.tf` compartan una sola fuente de verdad de
  región — esa vez sí se propagó in-place sin necesitar `-replace`, confirmado
  directamente contra la task definition real.)
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
