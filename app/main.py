from fastapi import FastAPI, HTTPException

from app.config import AGENT_MODEL, PUBLIC_BASE_URL
from app.schemas import CreateResponseRequest, build_agent_card, build_dummy_response

app = FastAPI(title="Agent CV")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/responses")
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
def agent_card() -> dict:
    return build_agent_card(PUBLIC_BASE_URL)
