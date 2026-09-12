import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReasoningParam(BaseModel):
    effort: Literal["low", "medium", "high"] | None = None


class CreateResponseRequest(BaseModel):
    model: str | None = None  # se ignora: el modelo es fijo en el servidor (paso 7)
    input: str | list[dict[str, Any]] | None = None
    instructions: str | None = None  # contexto de menor prioridad, nunca reemplaza el system prompt interno
    stream: bool = False
    tools: list[Any] | None = None
    tool_choice: Any | None = None
    previous_response_id: str | None = None
    conversation: Any | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    # NOTA para el paso 8/9: cuando este parametro se conecte a un LLM real, "validar"
    # debe significar imponer un tope maximo real (no solo comprobar que sea entero),
    # o queda abierta la puerta a inflar el costo con un valor absurdo.
    max_output_tokens: int | None = Field(default=None, ge=16)
    reasoning: ReasoningParam | None = None


def build_response(
    request: CreateResponseRequest,
    model: str,
    llm_response: dict[str, Any],
    *,
    response_id: str | None = None,
    item_id: str | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    """Arma el ResponseResource real a partir de la respuesta del LLM (paso 8).

    `llm_response` es el dict crudo devuelto por `client.converse(...)` de
    Bedrock (ver app/llm.py): `output.message.content[].text`, `stopReason`,
    `usage.inputTokens`/`outputTokens`.

    `response_id`/`item_id`/`created_at` son opcionales: sin streaming se
    generan aqui (como antes); con streaming (paso 13), el generador de
    eventos en app/main.py los fija una sola vez y los reusa en TODOS los
    eventos de la misma respuesta, incluido este snapshot final."""
    now = created_at if created_at is not None else int(time.time())
    content_parts = llm_response["output"]["message"]["content"]
    text = "".join(part.get("text", "") for part in content_parts)
    is_truncated = llm_response.get("stopReason") == "max_tokens"
    usage = llm_response.get("usage", {})

    return {
        "id": response_id or f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": now,
        "completed_at": int(time.time()),
        "status": "incomplete" if is_truncated else "completed",
        "incomplete_details": {"reason": "max_output_tokens"} if is_truncated else None,
        "model": model,
        "previous_response_id": None,
        "instructions": request.instructions,
        "output": [
            {
                "id": item_id or f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "incomplete" if is_truncated else "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "error": None,
        "tools": [],
        "tool_choice": "none",
        "truncation": "disabled",
        "parallel_tool_calls": False,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "top_p": request.top_p,
        "presence_penalty": None,
        "frequency_penalty": None,
        "top_logprobs": None,
        "temperature": request.temperature,
        "reasoning": None,
        "user": None,
        "usage": {
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "total_tokens": usage.get("inputTokens", 0) + usage.get("outputTokens", 0),
            "input_tokens_details": {"cached_tokens": usage.get("cacheReadInputTokens", 0) or 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "max_output_tokens": request.max_output_tokens,
        "max_tool_calls": None,
        "store": False,
        "background": False,
        "service_tier": "auto",
        "metadata": None,
        "safety_identifier": None,
        "prompt_cache_key": None,
    }


def build_streaming_skeleton(
    request: CreateResponseRequest, model: str, *, response_id: str, created_at: int
) -> dict[str, Any]:
    """Snapshot inicial (status "in_progress", sin output) para los eventos
    `response.created`/`response.in_progress` (paso 13). Mismos campos que
    build_response, antes de que exista una respuesta real del LLM."""
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "completed_at": None,
        "status": "in_progress",
        "incomplete_details": None,
        "model": model,
        "previous_response_id": None,
        "instructions": request.instructions,
        "output": [],
        "error": None,
        "tools": [],
        "tool_choice": "none",
        "truncation": "disabled",
        "parallel_tool_calls": False,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "top_p": request.top_p,
        "presence_penalty": None,
        "frequency_penalty": None,
        "top_logprobs": None,
        "temperature": request.temperature,
        "reasoning": None,
        "user": None,
        "usage": None,
        "max_output_tokens": request.max_output_tokens,
        "max_tool_calls": None,
        "store": False,
        "background": False,
        "service_tier": "auto",
        "metadata": None,
        "safety_identifier": None,
        "prompt_cache_key": None,
    }


def build_agent_card(public_base_url: str) -> dict[str, Any]:
    return {
        "name": "Agent CV",
        "description": (
            "Agente conversacional que responde preguntas sobre la trayectoria "
            "profesional, experiencia, proyectos y habilidades de su titular. Esta "
            "tarjeta se expone unicamente como metadata de descubrimiento para "
            "plataformas compatibles con Open Responses: NO implementa el protocolo "
            "A2A completo (no expone metodos de tareas A2A como SendMessage/GetTask; "
            "supportedInterfaces se declara solo para satisfacer el validador de "
            "tarjetas de agente, con un protocolBinding no estandar)."
        ),
        "version": "0.1.0",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "experience",
                "name": "Experiencia profesional",
                "description": "Responde preguntas sobre la trayectoria y experiencia laboral.",
                "tags": ["cv", "experiencia"],
            },
            {
                "id": "projects",
                "name": "Proyectos",
                "description": "Responde preguntas sobre proyectos realizados.",
                "tags": ["cv", "proyectos"],
            },
            {
                "id": "skills",
                "name": "Habilidades",
                "description": "Responde preguntas sobre habilidades tecnicas y blandas.",
                "tags": ["cv", "habilidades"],
            },
        ],
        # Declarado para cuando el paso 9 implemente auth real; hoy el endpoint
        # /responses NO valida todavia el token (ver limitaciones en README).
        "securitySchemes": {
            "bearerAuth": {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer",
                }
            }
        },
        "securityRequirements": [{"schemes": {"bearerAuth": {"list": []}}}],
        # supportedInterfaces es requerido por el spec de A2A (verificado contra
        # a2a.proto, rama main, v1.0.1) -- confirmado en el paso 13 que la
        # plataforma externa lo exige para su flujo de "Importar desde tarjeta
        # de agente" (sin el, el import falla: "falta name o supportedInterfaces").
        # protocolBinding "OpenResponses" es un valor NO estandar (el spec permite
        # "string de forma abierta" -- no limitado a JSONRPC/GRPC/HTTP+JSON):
        # no implementamos metodos A2A reales (SendMessage/GetTask) en esta URL,
        # asi que declarar HTTP+JSON seria afirmar algo falso. Esto solo satisface
        # el campo requerido sin mentir sobre que protocolo hay realmente ahi.
        "supportedInterfaces": [
            {
                "url": public_base_url,
                "protocolBinding": "OpenResponses",
                "protocolVersion": "1.0",
            }
        ],
        # Campo NO estandar de A2A: aqui vive la URL real de Open Responses.
        "x-openResponsesUrl": f"{public_base_url}/responses",
    }
