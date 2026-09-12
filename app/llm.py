import logging
import os
from collections.abc import Iterator
from typing import NoReturn

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


def _build_converse_kwargs(
    messages: list[dict[str, str]],
    *,
    temperature: float | None,
    top_p: float | None,
    max_output_tokens: int | None,
) -> dict[str, object]:
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
    return kwargs


def _handle_bedrock_exception(exc: Exception) -> NoReturn:
    # Traduce los errores conocidos de Bedrock/botocore a LLMError; cualquier
    # otra excepcion se re-lanza tal cual (fallar ruidoso ante algo
    # inesperado, no esconderlo detras de un LLMError generico). Compartido
    # entre generate_reply (error al momento de la llamada) y
    # generate_reply_stream (error al momento de la llamada O durante la
    # iteracion del stream -- ver iter_stream_events).
    if isinstance(exc, _client.exceptions.ThrottlingException):
        logger.warning("Throttling de Bedrock.")
        raise LLMError("El proveedor del LLM esta limitando la tasa de requests.") from exc
    if isinstance(exc, _client.exceptions.ValidationException):
        logger.error("Request invalido a Bedrock: %s", exc)
        raise LLMError("El proveedor del LLM rechazo el request.") from exc
    if isinstance(exc, _client.exceptions.AccessDeniedException):
        logger.error("Acceso denegado por Bedrock.")
        raise LLMError("Fallo de permisos con el proveedor del LLM.") from exc
    if isinstance(
        exc,
        (
            _client.exceptions.ModelTimeoutException,
            _client.exceptions.ModelNotReadyException,
            _client.exceptions.ServiceUnavailableException,
            _client.exceptions.InternalServerException,
        ),
    ):
        logger.error("El proveedor del LLM no esta disponible (%s).", type(exc).__name__)
        raise LLMError("El proveedor del LLM no esta disponible en este momento.") from exc
    if isinstance(exc, botocore.exceptions.ClientError):
        logger.error("Error del proveedor del LLM: %s", exc)
        raise LLMError("El proveedor del LLM devolvio un error.") from exc
    if isinstance(exc, botocore.exceptions.BotoCoreError):
        logger.error("Error de conexion con el proveedor del LLM: %s", exc)
        raise LLMError("No se pudo conectar con el proveedor del LLM.") from exc
    raise exc


def generate_reply(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
) -> dict:
    """Invoca el modelo (Bedrock Converse API, no streaming) con los mensajes
    armados por app/context.py. Devuelve la respuesta cruda de
    `client.converse(...)`.

    reasoning.effort del request publico NO se reenvia: Converse no tiene un
    parametro equivalente para claude-haiku-4-5 (paso 8)."""
    kwargs = _build_converse_kwargs(
        messages, temperature=temperature, top_p=top_p, max_output_tokens=max_output_tokens
    )
    try:
        return _client.converse(**kwargs)
    except Exception as exc:  # noqa: BLE001 -- _handle_bedrock_exception reclasifica o re-lanza
        _handle_bedrock_exception(exc)


def generate_reply_stream(
    messages: list[dict[str, str]],
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
) -> Iterator[dict]:
    """Invoca el modelo (Bedrock ConverseStream API) y devuelve un iterador de
    eventos crudos de Bedrock (paso 13: soporte de streaming, requerido por
    la plataforma externa que manda stream=true por default).

    Cada evento trae EXACTAMENTE una de estas claves (confirmado contra el
    modelo real de botocore, no supuesto): messageStart, contentBlockStart,
    contentBlockDelta (delta.text es el texto incremental que nos interesa),
    contentBlockStop, messageStop (stopReason), metadata (usage). La
    traduccion a eventos de streaming de Open Responses vive en app/main.py."""
    kwargs = _build_converse_kwargs(
        messages, temperature=temperature, top_p=top_p, max_output_tokens=max_output_tokens
    )
    try:
        response = _client.converse_stream(**kwargs)
        yield from response["stream"]
    except Exception as exc:  # noqa: BLE001 -- _handle_bedrock_exception reclasifica o re-lanza
        _handle_bedrock_exception(exc)
