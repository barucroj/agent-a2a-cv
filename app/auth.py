import hmac
import json
import os

import boto3

from app.config import BEARER_TOKEN_SECRET_NAME


def _extract_secret_value(secret_string: str) -> str:
    try:
        data = json.loads(secret_string)
    except json.JSONDecodeError:
        return secret_string.strip()
    if isinstance(data, dict):
        for key in ("AGENT_BEARER_TOKEN", "token", "value"):
            if key in data:
                return str(data[key]).strip()
    return secret_string.strip()


def _resolve_bearer_token() -> str:
    # Local: variable de entorno (.env via `uvicorn --env-file .env`). Produccion:
    # Secrets Manager (mismo patron ya usado para leer secretos del proyecto; el
    # Task Role ya tiene permiso de lectura sobre agent-cv/*, paso 4).
    env_token = os.getenv("AGENT_BEARER_TOKEN")
    if env_token:
        return env_token
    secrets_client = boto3.client("secretsmanager")
    response = secrets_client.get_secret_value(SecretId=BEARER_TOKEN_SECRET_NAME)
    return _extract_secret_value(response["SecretString"])


# Se resuelve una sola vez al importar el modulo, no en cada request.
_EXPECTED_TOKEN = _resolve_bearer_token()


def is_valid_bearer_token(authorization_header: str | None) -> bool:
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return False
    provided = authorization_header.removeprefix("Bearer ").strip()
    # hmac.compare_digest en vez de == para no filtrar el token por timing attack.
    return hmac.compare_digest(provided, _EXPECTED_TOKEN)
