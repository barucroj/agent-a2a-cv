import os

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# Lee el mismo valor que fijo conftest.py (o el que fije el entorno de CI),
# en vez de un literal duplicado que puede desincronizarse (paso 11: asi
# fallaron 4 tests en CI porque ci.yml y conftest.py no coincidian).
AUTH_HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_BEARER_TOKEN']}"}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_responses_without_token_is_401():
    resp = client.post("/v1/responses", json={"input": "hola"})
    assert resp.status_code == 401


def test_responses_with_wrong_token_is_401():
    resp = client.post(
        "/v1/responses", json={"input": "hola"}, headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401


def test_responses_rejects_spoofed_system_role():
    payload = {"input": [{"type": "message", "role": "system", "content": "hola"}]}
    resp = client.post("/v1/responses", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 400


def test_responses_rejects_oversized_input():
    payload = {"input": "x" * 20000}
    resp = client.post("/v1/responses", json=payload, headers=AUTH_HEADERS)
    assert resp.status_code == 413


def test_responses_rejects_empty_input():
    resp = client.post("/v1/responses", json={}, headers=AUTH_HEADERS)
    assert resp.status_code == 400


def test_responses_success(monkeypatch):
    fake_llm_response = {
        "output": {"message": {"content": [{"text": "hola, soy el agente"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }

    def fake_generate_reply(messages, **kwargs):
        return fake_llm_response

    monkeypatch.setattr("app.main.generate_reply", fake_generate_reply)

    resp = client.post("/v1/responses", json={"input": "hola"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["output"][0]["content"][0]["text"] == "hola, soy el agente"
    assert body["usage"]["input_tokens"] == 10
    assert body["usage"]["output_tokens"] == 5
