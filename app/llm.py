import logging
import os

import boto3
import botocore.exceptions

from app.config import AGENT_MODEL, MAX_OUTPUT_TOKENS_CAP

logger = logging.getLogger("agent_cv")


class LLMError(Exception):
    """Fallo al invocar al proveedor del LLM (throttling, timeout, red, etc.)."""


# Se resuelve una sola vez al importar el modulo, no en cada request. Las
# credenciales las toma del entorno de ejecucion: localmente el profile de AWS
# CLI configurado, en produccion el Task Role de ECS (permiso bedrock:InvokeModel
# ya acotado en infra/iam.tf al paso 8).
_client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _split_system_and_messages(
    messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]] | None, list[dict[str, object]]]:
    # La Converse API de Bedrock espera el system prompt en un parametro
    # separado (`system`), no como un mensaje mas en `messages` (igual que la
    # API de Anthropic). build_messages() (paso 6) arma un unico mensaje
    # 'system' al inicio; se extrae aqui y el resto se traduce al formato de
    # contenido de Converse (content: [{"text": ...}]).
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    conversation: list[dict[str, object]] = [
        {"role": m["role"], "content": [{"text": m["content"]}]}
        for m in messages
        if m.get("role") != "system"
    ]
    system = [{"text": "\n\n".join(system_parts)}] if system_parts else None
    return system, conversation


def generate_reply(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    """Invoca el modelo (Bedrock Converse API) con los mensajes armados por
    app/context.py. Devuelve la respuesta cruda de `client.converse(...)`.

    reasoning.effort del request publico NO se reenvia: Converse no tiene un
    parametro equivalente para claude-haiku-4-5 (paso 8)."""
    system, conversation = _split_system_and_messages(messages)
    max_tokens = min(max_output_tokens, MAX_OUTPUT_TOKENS_CAP) if max_output_tokens else MAX_OUTPUT_TOKENS_CAP

    inference_config: dict[str, object] = {"maxTokens": max_tokens}
    if temperature is not None:
        inference_config["temperature"] = temperature
    if top_p is not None:
        inference_config["topP"] = top_p

    kwargs: dict[str, object] = {
        "modelId": AGENT_MODEL,
        "messages": conversation,
        "inferenceConfig": inference_config,
    }
    if system is not None:
        kwargs["system"] = system

    try:
        return _client.converse(**kwargs)
    except _client.exceptions.ThrottlingException as exc:
        logger.warning("Throttling de Bedrock.")
        raise LLMError("El proveedor del LLM esta limitando la tasa de requests.") from exc
    except _client.exceptions.ValidationException as exc:
        logger.error("Request invalido a Bedrock: %s", exc)
        raise LLMError("El proveedor del LLM rechazo el request.") from exc
    except _client.exceptions.AccessDeniedException as exc:
        logger.error("Acceso denegado por Bedrock.")
        raise LLMError("Fallo de permisos con el proveedor del LLM.") from exc
    except (
        _client.exceptions.ModelTimeoutException,
        _client.exceptions.ModelNotReadyException,
        _client.exceptions.ServiceUnavailableException,
        _client.exceptions.InternalServerException,
    ) as exc:
        logger.error("El proveedor del LLM no esta disponible (%s).", type(exc).__name__)
        raise LLMError("El proveedor del LLM no esta disponible en este momento.") from exc
    except botocore.exceptions.ClientError as exc:
        logger.error("Error del proveedor del LLM: %s", exc)
        raise LLMError("El proveedor del LLM devolvio un error.") from exc
    except botocore.exceptions.BotoCoreError as exc:
        logger.error("Error de conexion con el proveedor del LLM: %s", exc)
        raise LLMError("No se pudo conectar con el proveedor del LLM.") from exc
