import logging
from typing import NoReturn

from fastapi import FastAPI, HTTPException, Request

from app.config import AGENT_MODEL, API_VERSION_PREFIX
from app.schemas import CreateResponseRequest, build_agent_card, build_dummy_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent_cv")

app = FastAPI(title="Agent CV")

# Tipos de contenido de texto permitidos por rol (allowlist, no denylist —
# ver schema real de openresponses/openresponses verificado en el paso 6):
# los mensajes 'user' solo traen input_text; los 'assistant' (turnos previos
# reenviados por el cliente, ya que el agente es stateless) solo output_text
# o refusal. Cualquier otro tipo (input_image, input_file, o uno futuro que
# el spec agregue) se rechaza por default en vez de mantener una lista de
# tipos multimodales conocidos.
_ALLOWED_CONTENT_TYPES_BY_ROLE = {
    "user": {"input_text"},
    "assistant": {"output_text", "refusal"},
}
# El unico canal legitimo de contexto "tipo sistema" que acepta el cliente es
# el campo instructions (tratado como baja confianza en app/context.py). Un
# item de input con role system/developer seria un intento de suplantar el
# system prompt interno.
_ALLOWED_INPUT_ROLES = set(_ALLOWED_CONTENT_TYPES_BY_ROLE)


def _request_metadata(instructions: str | None, input_value: object) -> str:
    # Nunca se loguea el contenido crudo de instructions/input (ni siquiera en
    # rechazos): un payload rechazado es justo el mas propenso a traer texto
    # inesperado/sensible de terceros (hallazgo de Codex, adversarial review
    # del paso 6). El motivo del rechazo ya es suficiente evidencia de que
    # alguien lo intento.
    return (
        f"instructions_presente={instructions is not None} "
        f"instructions_len={len(instructions) if instructions else 0} "
        f"input_type={type(input_value).__name__} "
        f"input_len={len(input_value) if isinstance(input_value, (str, list)) else 0}"
    )


def _reject(reason: str, *, instructions: str | None, input_value: object) -> NoReturn:
    logger.warning(
        "Solicitud a /responses rechazada: %s — %s",
        reason,
        _request_metadata(instructions, input_value),
    )
    raise HTTPException(status_code=400, detail=reason)


def _validate_input_items(
    input_value: object, *, instructions: str | None
) -> None:
    if not isinstance(input_value, list):
        return
    for item in input_value:
        if not isinstance(item, dict):
            _reject(
                "Cada elemento de 'input' debe ser un objeto.",
                instructions=instructions,
                input_value=input_value,
            )
        if item.get("type") != "message":
            _reject(
                f"Tipo de item no soportado en 'input': {item.get('type')!r}.",
                instructions=instructions,
                input_value=input_value,
            )
        role = item.get("role")
        if role not in _ALLOWED_INPUT_ROLES:
            _reject(
                f"Rol no soportado en 'input': {role!r}. Este agente no acepta "
                "mensajes con rol 'system' ni 'developer' desde el cliente.",
                instructions=instructions,
                input_value=input_value,
            )
        content = item.get("content")
        if isinstance(content, list):
            allowed_types = _ALLOWED_CONTENT_TYPES_BY_ROLE[role]
            for part in content:
                part_type = part.get("type") if isinstance(part, dict) else None
                if part_type not in allowed_types:
                    _reject(
                        f"Contenido no soportado en 'input' (rol {role!r}, tipo "
                        f"{part_type!r}); este agente solo acepta texto.",
                        instructions=instructions,
                        input_value=input_value,
                    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{API_VERSION_PREFIX}/responses")
def create_response(request: CreateResponseRequest) -> dict:
    logger.info(
        "Request recibido en /responses — %s",
        _request_metadata(request.instructions, request.input),
    )

    def reject(reason: str) -> NoReturn:
        _reject(reason, instructions=request.instructions, input_value=request.input)

    if request.stream:
        reject("stream=true aun no esta soportado; se habilita al integrar el LLM (paso 8).")
    if request.tools or request.tool_choice is not None:
        reject("Este agente no soporta tool calling.")
    if request.previous_response_id or request.conversation:
        reject(
            "Este agente es stateless: reenvia el historial completo en 'input'; "
            "no uses previous_response_id ni conversation."
        )
    _validate_input_items(request.input, instructions=request.instructions)
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
