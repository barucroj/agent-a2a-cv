import os

# Debe fijarse ANTES de importar app.main (que importa app.auth, la cual
# resuelve el Bearer token al importarse) para que el test no intente llamar
# a Secrets Manager real.
os.environ.setdefault("AGENT_BEARER_TOKEN", "test-token-for-ci")
os.environ.setdefault("AWS_REGION", "us-east-1")
