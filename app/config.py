import os

# URL publica donde queda expuesto este servicio (cambia entre local y AWS).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000/v1")

# Modelo fijo del lado servidor. Pendiente de decidir en el paso 7 del roadmap;
# cualquier "model" recibido en el request publico se ignora.
AGENT_MODEL = os.getenv("AGENT_MODEL", "pending")
