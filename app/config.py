import os

# Prefijo de version montado por la app (ver app/main.py).
API_VERSION_PREFIX = "/v1"

# Modelo fijo del lado servidor (decidido en el paso 7-8: Amazon Bedrock).
# Es el inference profile geografico "us." (no el ID base): claude-haiku-4-5
# en us-east-1 no soporta invocacion In-Region via bedrock-runtime, solo
# cross-region (verificado contra la ficha oficial del modelo). El permiso
# IAM correspondiente vive en infra/iam.tf. Cualquier "model" recibido en el
# request publico se ignora.
AGENT_MODEL = os.getenv("AGENT_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# Tope duro de tokens de salida por respuesta (paso 8): protege contra abuso de
# costo via un max_output_tokens absurdamente alto en el request publico.
MAX_OUTPUT_TOKENS_CAP = 2048
