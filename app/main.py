from fastapi import FastAPI, HTTPException, Request

from app.config import AGENT_MODEL, API_VERSION_PREFIX
from app.schemas import CreateResponseRequest, build_agent_card, build_dummy_response

app = FastAPI(title="Agent CV")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{API_VERSION_PREFIX}/responses")
def create_response(request: CreateResponseRequest) -> dict:
    if request.stream:
        raise HTTPException(
            status_code=400,
            detail="stream=true aun no esta soportado; se habilita al integrar el LLM (paso 8).",
        )
    if request.tools or request.tool_choice is not None:
        raise HTTPException(status_code=400, detail="Este agente no soporta tool calling.")
    if request.previous_response_id or request.conversation:
        raise HTTPException(
            status_code=400,
            detail=(
                "Este agente es stateless: reenvia el historial completo en 'input'; "
                "no uses previous_response_id ni conversation."
            ),
        )
    return build_dummy_response(request, model=AGENT_MODEL)


@app.get("/.well-known/agent-card.json")
def agent_card(request: Request) -> dict:
    # Detras del ALB de ECS Express Mode no controlamos una URL publica fija de
    # antemano (la genera AWS al crear el servicio) — se deriva del propio
    # request en vez de una variable de entorno, para no depender de nada
    # inyectado en el contenedor al momento del deploy.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    public_base_url = f"{proto}://{host}{API_VERSION_PREFIX}"
    return build_agent_card(public_base_url)
