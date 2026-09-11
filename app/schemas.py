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


def build_dummy_response(request: CreateResponseRequest, model: str) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": now,
        "completed_at": now,
        "status": "completed",
        "incomplete_details": None,
        "model": model,
        "previous_response_id": None,
        "instructions": request.instructions,
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "Este es un esqueleto del endpoint /responses (paso 2 del "
                            "roadmap). Todavia no hay un LLM conectado."
                        ),
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
            "A2A completo (no declara supportedInterfaces ni endpoints de tareas A2A)."
        ),
        "version": "0.1.0",
        "capabilities": {
            "streaming": False,
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
        # Campo NO estandar de A2A: aqui vive la URL real de Open Responses,
        # ya que "supportedInterfaces" es para bindings A2A nativos que no tenemos.
        "x-openResponsesUrl": f"{public_base_url}/responses",
    }
