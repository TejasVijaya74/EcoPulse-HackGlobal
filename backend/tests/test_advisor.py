import asyncio

import httpx
import pytest

from app.services import advisor


class MockResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {"choices": [{"message": {"content": "Imports drive the estimate."}}]}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", advisor.GROQ_CHAT_COMPLETIONS_URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("upstream error", request=request, response=response)

    def json(self):
        return self._body


class MockAsyncClient:
    def __init__(self, *, timeout):
        self.timeout = timeout
        self.response = MockResponse()
        self.request = None
        self.error = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, url, *, headers, json):
        self.request = {"url": url, "headers": headers, "json": json}
        if self.error:
            raise self.error
        return self.response


def configured_client(monkeypatch):
    client = MockAsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    monkeypatch.setattr(advisor, "GROQ_API_KEY", "server-only-test-key")
    monkeypatch.setattr(advisor, "GROQ_MODEL", "test-model")
    monkeypatch.setattr(advisor.httpx, "AsyncClient", lambda **kwargs: client)
    return client


def test_advisor_uses_backend_key_and_only_supplied_simulation_context(monkeypatch):
    client = configured_client(monkeypatch)

    answer = asyncio.run(
        advisor.ask_energy_advisor(
            "Why is grid dependency high?",
            {"metrics": {"grid_dependency_percent": 42.5}},
        )
    )

    assert answer == "Imports drive the estimate."
    assert client.request["url"] == advisor.GROQ_CHAT_COMPLETIONS_URL
    assert client.request["headers"]["Authorization"] == "Bearer server-only-test-key"
    assert client.request["json"]["model"] == "test-model"
    assert client.request["json"]["max_completion_tokens"] == 500
    messages = client.request["json"]["messages"]
    assert "Use only the supplied context" in messages[0]["content"]
    assert '"grid_dependency_percent": 42.5' in messages[1]["content"]
    assert "server-only-test-key" not in messages[1]["content"]


def test_advisor_requires_backend_api_key_and_valid_secure_base_url(monkeypatch):
    monkeypatch.setattr(advisor, "GROQ_API_KEY", "")
    with pytest.raises(advisor.AdvisorNotConfigured):
        asyncio.run(advisor.ask_energy_advisor("Explain imports", {"metrics": {}}))

    configured_client(monkeypatch)
    monkeypatch.setattr(advisor, "GROQ_API_BASE_URL", "http://insecure.example/v1")
    with pytest.raises(advisor.AdvisorNotConfigured, match="configuration is invalid"):
        asyncio.run(advisor.ask_energy_advisor("Explain imports", {"metrics": {}}))


def test_advisor_maps_timeout_and_rate_limit(monkeypatch):
    client = configured_client(monkeypatch)

    client.error = httpx.ReadTimeout("timed out")
    with pytest.raises(advisor.AdvisorTimeout):
        asyncio.run(advisor.ask_energy_advisor("Explain imports", {"metrics": {}}))

    client.error = None
    client.response = MockResponse(status_code=429)
    with pytest.raises(advisor.AdvisorRateLimited):
        asyncio.run(advisor.ask_energy_advisor("Explain imports", {"metrics": {}}))


def test_advisor_maps_upstream_and_malformed_response_errors(monkeypatch):
    client = configured_client(monkeypatch)

    client.response = MockResponse(status_code=503)
    with pytest.raises(advisor.AdvisorUnavailable):
        asyncio.run(advisor.ask_energy_advisor("Explain imports", {"metrics": {}}))

    client.response = MockResponse(body={"choices": []})
    with pytest.raises(advisor.AdvisorUnavailable):
        asyncio.run(advisor.ask_energy_advisor("Explain imports", {"metrics": {}}))
