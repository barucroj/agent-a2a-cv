import json
import logging
import uuid
from typing import NoReturn

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth import is_valid_bearer_token
from app.config import AGENT_MODEL, API_VERSION_PREFIX
from app.context import build_messages
from app.llm import LLMError, generate_reply
from app.logging_utils import configure_logging, request_id_var
from app.schemas import CreateResponseRequest, build_agent_card, build_response

configure_logging()
logger = logging.getLogger("agent_cv")

app = FastAPI(title="Agent CV")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    # Usa X-Request-Id del cliente si lo manda (permite correlacionar con sus
    # propios logs), o genera uno nuevo. Se propaga automaticamente a TODAS
    # las lineas de log de esta request via request_id_var + RequestIdFilter
    # (app/logging_utils.py), sin pasarlo a mano por cada funcion.
    incoming_id = request.headers.get("x-request-id")
    request_id = incoming_id if incoming_id else uuid.uuid4().hex
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-Id"] = request_id
    return response

# CORS mas restrictivo posible: la plataforma externa consume /v1/responses
# server-to-server (backend a backend), nunca desde JavaScript en un
# navegador. CORS es un mecanismo que solo aplica el navegador -- un cliente
# no-navegador ignora estos headers por completo -- asi que allow_origins=[]
# no afecta el trafico real y bloquea cualquier intento futuro de uso desde
# un navegador, sin necesidad de whitelisting de origenes.
app.add_middleware(CORSMiddleware, allow_origins=[])


def _rate_limit_key(request: Request) -> str:
    # El conector real a este contenedor es el ALB de ECS Express Mode, no el
    # cliente -- request.client.host por si solo seria la IP del ALB para
    # todos los llamadores. El ALB usa modo "append" (default, verificado
    # contra la doc oficial): agrega la IP real observada al FINAL de
    # cualquier X-Forwarded-For que el cliente ya haya mandado. Tomar el
    # primer valor seria tomar uno que el propio llamador puede inventar y
    # rotar para evadir el limite; el ultimo es el unico que el ALB controla.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


# Storage en memoria (default de slowapi): correcto mientras el servicio
# corra en una sola instancia (desiredCount=1, paso 4); si se escala
# horizontalmente hace falta un storage_uri compartido (ej. Redis).
limiter = Limiter(key_func=_rate_limit_key)
app.state.limiter = limiter


def _handle_rate_limit_exceeded(request: Request, exc: RateLimitExceeded):
    # Log propio con motivo estructurado antes de delegar en la respuesta
    # default de slowapi (mismo formato/headers que ya arma la libreria).
    logger.warning(
        "Solicitud rechazada por rate limit",
        extra={"rejection_reason": "rate_limit_exceeded", "status_code": 429},
    )
    return _rate_limit_exceeded_handler(request, exc)


app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)

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

# Tope minimo de tamano de request (paso 8, parche puntual): protege contra el
# escenario mas obvio de abuso de costo -- muchos requests con payloads
# grandes -- mientras llega el paso 9 (auth, rate limiting, CORS, cuotas por
# llamador). No reemplaza el paso 9, solo evita dejar el endpoint totalmente
# sin freno de tamano en el tiempo que toma llegar ahi.
_MAX_INPUT_CHARS = 8000


def _input_char_length(input_value: object) -> int:
    if isinstance(input_value, str):
        return len(input_value)
    if isinstance(input_value, list):
        return len(json.dumps(input_value))
    return 0


# Paso 10: se loguea instructions/input completos (Opcion A, aprobada
# explicitamente) -- el endpoint ya no es publico sin control (paso 9: auth
# Bearer + rate limiting), asi que el riesgo que motivo "solo metadata" en el
# paso 6/8 (cualquiera en internet podia llenar los logs de basura/datos de
# terceros) ya no aplica igual. Se mantiene un truncado por seguridad (no por
# privacidad): un solo request no debe poder generar un evento de log
# desproporcionadamente grande.
_LOG_CONTENT_MAX_CHARS = 4000


def _stringify_for_log(value: object) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > _LOG_CONTENT_MAX_CHARS:
        return text[:_LOG_CONTENT_MAX_CHARS] + f"...<truncado, {len(text)} chars totales>"
    return text


def _request_log_fields(instructions: str | None, input_value: object) -> dict[str, str]:
    return {
        "instructions": _stringify_for_log(instructions),
        "input": _stringify_for_log(input_value),
    }


def _reject(
    reason: str, *, instructions: str | None, input_value: object, status_code: int = 400
) -> NoReturn:
    logger.warning(
        "Solicitud a /responses rechazada",
        extra={
            "rejection_reason": reason,
            "status_code": status_code,
            **_request_log_fields(instructions, input_value),
        },
    )
    raise HTTPException(status_code=status_code, detail=reason)


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
@limiter.limit("20/minute")
def create_response(request: Request, body: CreateResponseRequest) -> dict:
    # Auth Bearer real, antes de cualquier otro trabajo: sin el header
    # correcto, 401 sin tocar el LLM ni el resto de las validaciones. Nunca se
    # loguea el header Authorization ni el token (ni el valido ni el
    # invalido) -- solo la categoria del rechazo.
    if not is_valid_bearer_token(request.headers.get("authorization")):
        logger.warning(
            "Solicitud a /responses rechazada",
            extra={"rejection_reason": "invalid_or_missing_token", "status_code": 401},
        )
        raise HTTPException(status_code=401, detail="Token de autorizacion invalido o ausente.")

    logger.info(
        "Request recibido en /responses",
        extra=_request_log_fields(body.instructions, body.input),
    )

    def reject(reason: str, status_code: int = 400) -> NoReturn:
        _reject(
            reason,
            instructions=body.instructions,
            input_value=body.input,
            status_code=status_code,
        )

    total_chars = len(body.instructions or "") + _input_char_length(body.input)
    if total_chars > _MAX_INPUT_CHARS:
        reject(
            "El contenido combinado de 'input' e 'instructions' excede el "
            f"limite de {_MAX_INPUT_CHARS} caracteres.",
            status_code=413,
        )
    # 'input' es opcional en el schema, pero una conversacion vacia no tiene
    # nada que responder: sin este chequeo, Bedrock la rechaza con un error
    # de validacion que terminaria devolviendose como 502 (como si fuera una
    # falla nuestra) en vez de 400 (error del cliente).
    if not body.input:
        reject("El campo 'input' es requerido y no puede estar vacio.")
    if isinstance(body.input, list) and not any(
        isinstance(item, dict) and item.get("role") == "user" and item.get("content")
        for item in body.input
    ):
        reject("El 'input' debe incluir al menos un mensaje con rol 'user' y contenido no vacio.")
    if body.stream:
        reject("Este agente no soporta stream=true.")
    if body.tools or body.tool_choice is not None:
        reject("Este agente no soporta tool calling.")
    if body.previous_response_id or body.conversation:
        reject(
            "Este agente es stateless: reenvia el historial completo en 'input'; "
            "no uses previous_response_id ni conversation."
        )
    _validate_input_items(body.input, instructions=body.instructions)

    messages = build_messages(body.instructions, body.input)
    try:
        llm_response = generate_reply(
            messages,
            temperature=body.temperature,
            top_p=body.top_p,
            max_output_tokens=body.max_output_tokens,
        )
    except LLMError as exc:
        logger.error(
            "Fallo al generar respuesta del LLM",
            extra={"status_code": 502, "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return build_response(body, model=AGENT_MODEL, llm_response=llm_response)


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
