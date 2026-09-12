# Agent CV

Agente conversacional que expone la trayectoria profesional de Antonio Baruc Rojas
Cuapio mediante un endpoint público compatible con
[Open Responses](https://github.com/openresponses/openresponses), descubrible vía
[A2A Agent Card](https://github.com/a2aproject/A2A). Corre en AWS (ECS Fargate),
respaldado por Claude Haiku 4.5 (Amazon Bedrock).

**Producción:**
[`https://ag-e909e8c63911412d8741669959ad662b.ecs.us-east-1.on.aws`](https://ag-e909e8c63911412d8741669959ad662b.ecs.us-east-1.on.aws/health)
(`/v1/responses` requiere Bearer token; la URL cambia si el servicio se recrea desde
cero — la fuente de verdad es `terraform output ecs_service_ingress_paths`).

## Cómo funciona

- **API:** FastAPI, un único endpoint `POST /v1/responses`, contrato de Open Responses.
  Stateless — el cliente reenvía el historial completo en cada request, el servidor no
  persiste sesiones.
- **Contexto:** el perfil profesional (`app/data/profile.md`) se inyecta directamente en
  el system prompt del agente — sin RAG, sin base de datos.
- **LLM:** Claude Haiku 4.5 vía Amazon Bedrock, modelo fijo del lado del servidor
  (cualquier `model` en el request público se ignora).
- **Seguridad:** autenticación Bearer, rate limiting por IP, CORS restrictivo, límites
  de tamaño de input/tokens, guardrails contra prompt injection y alucinación.
- **Infraestructura:** Terraform → Amazon ECS Express Mode (Fargate + ALB), ECR,
  CloudWatch, Secrets Manager.
- **CI/CD:** GitHub Actions — lint/tipado/tests/build en cada Pull Request, build+push a
  ECR en cada push a `main`.

## Estructura del repositorio

```
app/               código de la aplicación (FastAPI)
  main.py          endpoint, validaciones, auth, rate limiting
  context.py       system prompt + perfil profesional
  llm.py           invocación a Amazon Bedrock
  auth.py          verificación del Bearer token
  schemas.py       contrato de Open Responses
  logging_utils.py logging estructurado (JSON)
  data/            perfil profesional (fuente del contexto del agente)
tests/             pruebas unitarias (pytest, LLM mockeado)
eval/              set de evaluación (pytest, contra un servidor real)
infra/             infraestructura como código (Terraform)
.github/workflows/ CI/CD (GitHub Actions)
```

## Uso local

Requiere Python 3.13, Docker, y credenciales de AWS con acceso a Bedrock
(`aws configure --profile agent-cv`).

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                 # completa AGENT_BEARER_TOKEN con cualquier valor
uvicorn app.main:app --reload --env-file .env
```

```bash
curl -X POST http://127.0.0.1:8000/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <tu-token-local>" \
  -d '{"input": "hola, cuentame de tu experiencia"}'
```

## Pruebas

```bash
pytest                                            # unitarias (mismas que corre CI)
ruff check . && mypy app tests eval               # lint + tipado
EVAL_BASE_URL=http://127.0.0.1:8000 pytest eval/  # set de evaluación, servidor real corriendo
```

## Despliegue

```bash
cd infra
terraform init
terraform plan -out=tfplan.binary
terraform apply tfplan.binary
```

CI/CD construye y sube la imagen a ECR en cada push a `main`; aplicar esa imagen nueva
en producción (`terraform apply`) se hace manualmente, por decisión de diseño.

## Documentación adicional

El razonamiento detrás de cada decisión técnica (elección del LLM, RAG vs. inyección
directa, seguridad, CI/CD, trade-offs aceptados y hallazgos de revisiones de seguridad)
está documentado en detalle en un registro interno del proceso, disponible bajo pedido.
