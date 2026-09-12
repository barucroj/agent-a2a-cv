"""Suite de evaluacion (paso 12). Reusable: EVAL_BASE_URL apunta a local
(default) o a produccion; AGENT_BEARER_TOKEN es el mismo de siempre.

    EVAL_BASE_URL=http://127.0.0.1:8000 pytest eval/          # local
    EVAL_BASE_URL=https://<url-real> pytest eval/ -k smoke    # produccion

No corre con el "pytest" bare de app/tests (ver testpaths en pyproject.toml):
esta suite pega contra un servidor real corriendo (local o prod), a
diferencia de tests/ que usa TestClient con el LLM mockeado.
"""

import httpx
import pytest

from eval.cases import CASES, EvalCase
from eval.conftest import send_case


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_eval_case(case: EvalCase, client: httpx.Client, record_result) -> None:
    response = send_case(client, case)
    try:
        case.check(response)
    except AssertionError as exc:
        record_result(case, response, passed=False, error=str(exc))
        raise
    else:
        record_result(case, response, passed=True, error=None)
