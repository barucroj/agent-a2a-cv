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

**Secretos requeridos antes de que la app pueda arrancar (paso 9):** la app lee el
Bearer token real de Secrets Manager al importarse — si el secreto no existe, el
contenedor falla al iniciar (ni siquiera sirve `/health`). Crearlo a mano, **fuera de
Terraform** (igual que cualquier secreto del proyecto — así el valor nunca queda en el
state):
```
aws secretsmanager create-secret --name agent-cv/bearer-token \
  --secret-string "$(openssl rand -hex 32)" --profile agent-cv --region us-east-1
```

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

**Mitigación de costo puntual del paso 8 (superada por el paso 9, ver abajo):**
`/v1/responses` rechazaba (400, antes de invocar Bedrock) si `instructions`+`input`
combinados excedían 8,000 caracteres, y el tope de `max_output_tokens` (2,048) ya se
aplicaba de verdad — pero sin autenticación ni rate limiting, cualquiera podía mandar
muchos requests válidos y facturar Bedrock sin control (riesgo #1 documentado desde el
inicio del proyecto). Resuelto en el paso 9.

**Pendiente de limpieza (no urgente):** el secreto `agent-cv/anthropic-api-key` en
Secrets Manager (creado en el intento #2 de arriba) ya no se usa — se deja sin borrar
por ahora, sin costo real de mantenerlo.

## Seguridad (paso 9)

**Rate limiting: en la aplicación, no AWS WAF.** Se evaluó WAF (reglas rate-based) y se
descartó por complejidad desproporcionada para el alcance de este proyecto — un recurso
más para provisionar, configurar y mantener, cuando `slowapi` (librería en la propia app,
`Limiter` de 20 requests/minuto por IP) resuelve el mismo problema con una dependencia y
unas líneas de código. Queda como mejora futura posible si el proyecto necesitara
protección a nivel de red (DDoS, reglas administradas), no como pendiente de este paso.
- La IP real del llamador se obtiene del **último** valor de `X-Forwarded-For`, no el
  primero: el ALB de ECS Express Mode usa el modo `append` (default, verificado contra
  la documentación oficial de AWS) — agrega la IP real observada al final de cualquier
  valor que el cliente ya haya mandado. Tomar el primer valor habría dejado el límite
  evadible por cualquiera que mande su propio header (hallazgo real de `/codex:review`,
  corregido antes de desplegar).
- Storage en memoria (default de `slowapi`): correcto para una sola instancia
  (`desiredCount=1`); si el servicio se escalara horizontalmente, haría falta un storage
  compartido (ej. Redis).

**CORS:** la plataforma externa consume `/v1/responses` servidor-a-servidor (backend a
backend), nunca desde JavaScript en un navegador — CORS es un mecanismo que solo aplica
el navegador (controla si su JS puede *leer* la respuesta de un fetch cross-origin), así
que no afecta ese tráfico real. Se configuró en su forma más restrictiva posible
(`allow_origins=[]`, ningún origen permitido) como defensa en profundidad, sin necesidad
de whitelisting de orígenes.

**Auth Bearer real:** el token vive en Secrets Manager (`agent-cv/bearer-token`, ver
sección de infraestructura arriba) y se resuelve una sola vez al arrancar la app (mismo
patrón que el resto de secretos del proyecto). Se compara con `hmac.compare_digest`
(nunca `==`) para no filtrar el token por timing attack. Sin el header `Authorization:
Bearer <token>` correcto, `/v1/responses` responde `401` antes de tocar el LLM o
cualquier otra validación. El `securityScheme` que la agent card ya declaraba desde el
paso 2 deja de ser aspiracional: el endpoint ahora sí lo exige.

**Límites de tamaño/tokens, ya aplicados de verdad:**
- `max_output_tokens`: tope absoluto de **1024** (bajado de 2048 en el paso 8) — cierra
  el pendiente abierto desde el paso 2.
- `input`+`instructions` combinados: tope de 8,000 caracteres, rechazado con **413**
  (era 400 como parche del paso 8; se formalizó el código de estado en este paso) antes
  de invocar el LLM.

## Logging estructurado (paso 10)

Formatter JSON propio (`app/logging_utils.py`, `json.dumps` + un `logging.Formatter` a
medida) — sin librería externa, mismo criterio de proporcionalidad usado en decisiones
anteriores del proyecto. Cada línea de log de la app es un objeto JSON con `timestamp`,
`level`, `logger`, `message`, `request_id`, y cualquier campo extra que agregue el
código (`rejection_reason`, `status_code`, etc.).

**`request_id` por request:** un middleware (`app/main.py`) usa el header `X-Request-Id`
del cliente si lo manda, o genera uno nuevo (`uuid4`), lo guarda en un `contextvars` y lo
devuelve también en la respuesta. Un `logging.Filter` lo inyecta automáticamente en
**todas** las líneas de esa request (sin pasarlo a mano por cada función) — permite
seguir el rastro completo de una request específica en CloudWatch Logs Insights.

**Todos los rechazos existentes ya loguean el motivo como campo estructurado**
(`rejection_reason`), no solo en la respuesta HTTP: los 400 del paso 6 (rol `system`
falso, `tools`, multimodalidad, `previous_response_id`, tamaño excedido), el 401 del
paso 9 (token inválido/ausente), y el 429 (rate limit — se agregó un exception handler
propio que loguea antes de delegar en la respuesta default de `slowapi`).

**Decisión abierta resuelta: sí se loguea `input`/`instructions` completos** (no solo
metadata). La decisión del paso 6/8 de *no* loguear contenido crudo se tomó cuando el
endpoint era público sin ninguna autenticación — cualquiera en internet podía llenar
CloudWatch de contenido arbitrario/de terceros. Con el paso 9 ya en producción (auth
Bearer + rate limiting), esa condición cambió: solo quien tiene el token real puede
llegar al endpoint. Se prioriza el poder auditar después qué se le mandó exactamente al
agente (incluyendo intentos de prompt injection reales, no solo su categoría) sobre el
riesgo residual, ya acotado, de que un llamador autenticado incluya contenido sensible.
Se mantiene un truncado de 4,000 caracteres por campo — por seguridad operativa (no
dejar que un solo request genere un evento de log desproporcionado), no por privacidad.
**Nunca se loguea** el header `Authorization` ni el token (válido o inválido) en ningún
caso — verificado manualmente (sin rastro en los logs tras probar con un token de prueba)
y documentado como punto específico para la revisión de Codex.

**Pendiente:** `/codex:review` de este módulo no se pudo correr — el plugin agotó su
cuota de uso (disponible de nuevo el 10 de octubre). Se verificó manualmente en su lugar:
ausencia de secretos en los logs (grep), y validez del JSON en las rutas de éxito, 400,
401 y 429. Correr el review real cuando la cuota se restablezca.

## CI/CD (paso 11)

**Alcance recortado, decisión explícita** — proporcional al tamaño del proyecto y
acotado por la pérdida de cuota de Codex (ver abajo). Deliberadamente **no** incluye:
OIDC (se usan access keys de larga duración en su lugar), gate de aprobación en GitHub
Environments, ni `terraform plan`/`apply` automatizado. El despliegue real lo sigue
haciendo el operador a mano, como en todo el proyecto hasta ahora.

**`ci.yml`** — en cada Pull Request hacia `develop`: `ruff` (lint), `mypy` (tipado),
`pytest` (tests), y `docker build` (sin push, solo confirma que la imagen compila). Corre
sin supervisión.

**`cd.yml`** — en cada push a `main`: build + push a ECR, con **dos tags por build**
(`latest` y el SHA corto del commit). Nada más — ni plan ni apply. Autenticación con
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` de `agent-cv-deploy` guardadas como secrets
del repo en GitHub — **trade-off aceptado explícitamente**: OIDC habría sido la opción
más segura (sin credenciales de larga duración expuestas como secreto), pero se descartó
por tiempo, dado el alcance recortado de este paso. No hizo falta ningún permiso IAM
nuevo: `agent-cv-deploy` ya tenía `AmazonEC2ContainerRegistryFullAccess`.

**Hallazgo real de `tfsec` sobre `infra/` — aceptado con mitigación parcial, no
ignorado:** el repositorio ECR tiene `image_tag_mutability = "MUTABLE"` (severidad HIGH,
`aws-ecr-enforce-immutable-repository`) — cualquiera con permiso de push podría
sobrescribir el tag `latest` sin que se note. Pasar a `IMMUTABLE` habría roto el flujo
actual (Terraform resuelve la imagen por el tag `latest` vía `data "aws_ecr_image"`, que
depende de poder re-apuntar ese tag en cada build) y habría exigido rediseñar el
mecanismo de promoción de imágenes — desproporcionado para el alcance de este paso. En
su lugar, `cd.yml` etiqueta cada build también con el SHA corto del commit (además de
`latest`), dando trazabilidad real (siempre se puede ver en ECR qué commit generó cada
imagen histórica) sin cambiar la mutabilidad del repo ni tocar cómo Terraform la resuelve.
Dos hallazgos LOW adicionales (log group y repo ECR sin KMS customer-managed) se aceptan
tal cual — mismo criterio que los permisos amplios de `agent-cv-deploy`: la encriptación
default de AWS ya aplica, una CMK propia es complejidad sin beneficio proporcional aquí.

**Sustitución de Codex por herramientas estáticas (este paso en adelante, mientras dure
la pérdida de cuota):** `ruff`, `mypy`, `bandit`, `pip-audit` para Python, `tfsec` para
Terraform. Hallazgo real de `pip-audit`: `starlette` (dependencia transitiva de
`fastapi==0.128.8`, tope `starlette<1.0.0` en esa versión) tenía 10 CVEs conocidos en la
versión resuelta (0.52.1) — todas las versiones parchadas son `>=1.0.0`. Se actualizó
`fastapi` a `0.141.1` (permite `starlette>=0.46.0`, sin tope superior) y se fijó
`starlette==1.6.0` explícitamente; se verificó que la app y los tests siguen funcionando
igual tras la actualización antes de comitear.

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
- **Resuelto en el paso 9:** el `securityScheme` de tipo Bearer que la agent card
  declaraba desde el paso 2 era una declaración aspiracional (el endpoint no validaba
  ningún token) — ya no lo es, `/v1/responses` ahora exige el Bearer real (ver sección
  de Seguridad arriba).
- El spec de A2A Agent Card tiene versiones incompatibles en el propio repo oficial
  (`a2aproject/A2A`, verificado directamente): la variante v0.3 usa un campo plano
  `url` + `protocolVersion` a nivel raíz, mientras que la variante v1.0 (rama `main`
  actual) reemplaza eso por `supportedInterfaces[]` (lista de `{url, protocolBinding,
  protocolVersion}`). No hay forma de saber, sin probarlo contra la plataforma externa
  real, cuál de las dos espera su flujo de "Importar desde tarjeta de agente" — por eso
  optamos por omitir `supportedInterfaces` del todo y exponer la URL de Open Responses
  en el campo no estándar `x-openResponsesUrl` en vez de adivinar un formato.
