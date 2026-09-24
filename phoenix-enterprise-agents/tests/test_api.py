import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def test_api_invoke_and_auth(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("PHOENIX_ENABLED", "false")
    monkeypatch.setenv("API_KEY", "test-key")
    from phoenix_agents.config import get_settings

    get_settings.cache_clear()
    from phoenix_agents.api.app import app

    with TestClient(app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        url = "/v1/agents/policy_qa/invoke"
        body = {"input": "Can I use a public AI chatbot with confidential data?"}
        assert client.post(url, json=body).status_code == 401
        resp = client.post(url, json=body, headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        # feedback requires an active tracing client
        fb = client.post("/v1/feedback", headers={"X-API-Key": "test-key"},
                         json={"span_id": "abcdef123456", "value": 1.0})
        assert fb.status_code == 503
    get_settings.cache_clear()
