import os

# Prefijo de version montado por la app (ver app/main.py).
API_VERSION_PREFIX = "/v1"

# Modelo fijo del lado servidor. Pendiente de decidir en el paso 7 del roadmap;
# cualquier "model" recibido en el request publico se ignora.
AGENT_MODEL = os.getenv("AGENT_MODEL", "pending")
