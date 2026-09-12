"""Config del set de evaluacion: URL base configurable (local o produccion),
Bearer token, reintento respetando el rate limit real (paso 9 -- este set no
se salta ningun control de produccion), y generacion de eval/report.md al
terminar la corrida (input/categoria/criterio/resultado real por caso)."""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from eval.cases import EvalCase
from eval.checks import extract_text

EVAL_BASE_URL = os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:8000")
EVAL_BEARER_TOKEN = os.environ.get("AGENT_BEARER_TOKEN", "")
_REPORT_PATH = Path(__file__).parent / "report.md"
_RESULTS_KEY: pytest.StashKey[list[dict]] = pytest.StashKey()


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=EVAL_BASE_URL, timeout=60.0) as c:
        yield c


def _auth_header(case: EvalCase) -> dict[str, str]:
    if case.auth == "none":
        return {}
    if case.auth == "wrong":
        return {"Authorization": "Bearer token-incorrecto-de-prueba"}
    return {"Authorization": f"Bearer {EVAL_BEARER_TOKEN}"}


def send_case(client: httpx.Client, case: EvalCase) -> httpx.Response:
    """POST /v1/responses respetando el rate limit real: si da 429, espera y
    reintenta -- este set no tiene un atajo para saltarse el limite.

    slowapi (ventana fija "20 por minuto") no manda header Retry-After
    (verificado directamente), asi que se usan intentos suficientes para
    cruzar una ventana completa (15 x 5s = 75s) en vez de asumir un numero
    arbitrario -- una corrida con 20+ casos naturalmente choca contra su
    propio limite al menos una vez."""
    for _ in range(15):
        response = client.post(
            "/v1/responses", json=case.payload, headers=_auth_header(case)
        )
        if response.status_code != 429:
            return response
        time.sleep(int(response.headers.get("Retry-After", "5")))
    return response


def _summarize(response: httpx.Response) -> str:
    if response.status_code == 200:
        text = extract_text(response)
        return text[:500] + ("..." if len(text) > 500 else "")
    return f"{response.status_code}: {response.text[:300]}"


@pytest.fixture
def record_result(request: pytest.FixtureRequest):
    results = request.config.stash.get(_RESULTS_KEY, None)
    if results is None:
        results = []
        request.config.stash[_RESULTS_KEY] = results

    def _record(case: EvalCase, response: httpx.Response, passed: bool, error: str | None) -> None:
        results.append(
            {
                "id": case.id,
                "category": case.category,
                "criterio": case.criterio,
                "payload": case.payload,
                "status_code": response.status_code,
                "actual": _summarize(response),
                "passed": passed,
                "error": error,
            }
        )

    return _record


def pytest_sessionfinish(session: pytest.Session) -> None:
    results = session.config.stash.get(_RESULTS_KEY, [])
    if not results:
        return

    lines = ["# Reporte de evaluacion (paso 12)", ""]
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    lines.append(f"**{passed}/{total} casos pasaron.**")
    lines.append("")

    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    lines.append("## Resumen por categoria")
    lines.append("")
    for category, items in by_category.items():
        cat_passed = sum(1 for r in items if r["passed"])
        lines.append(f"- **{category}**: {cat_passed}/{len(items)}")
    lines.append("")

    lines.append("## Detalle por caso")
    for r in results:
        estado = "PASA" if r["passed"] else "**FALLA**"
        lines.append(f"### `{r['id']}` ({r['category']}) — {estado}")
        lines.append(f"- **Criterio:** {r['criterio']}")
        lines.append(f"- **Request:** `{r['payload']}`")
        lines.append(f"- **Resultado real:** {r['actual']}")
        if r["error"]:
            lines.append(f"- **Error:** {r['error']}")
        lines.append("")

    _REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
