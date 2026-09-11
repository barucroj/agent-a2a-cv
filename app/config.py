import os

# Prefijo de version montado por la app (ver app/main.py). Unica fuente de verdad:
# usarlo tambien en cualquier valor default que represente la URL publica del servicio.
API_VERSION_PREFIX = "/v1"

# URL publica donde queda expuesto este servicio (cambia entre local y AWS).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", f"http://localhost:8000{API_VERSION_PREFIX}")

# Modelo fijo del lado servidor. Pendiente de decidir en el paso 7 del roadmap;
# cualquier "model" recibido en el request publico se ignora.
AGENT_MODEL = os.getenv("AGENT_MODEL", "pending")
