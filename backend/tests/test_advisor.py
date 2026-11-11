import asyncio

import httpx
import pytest

from app.services import advisor


def test_advisor_context_and_instructions_explain_simulation_energy_accounting():
    context = advisor.build_advisor_context(
        {
            "simulated": True,
            "scenario_label": "Normal Conditions",
            "parameters": {
                "duration_hours": 48,
                "households": 60,
                "storage_capacity_kwh": 320.0,
                "initial_storage_percent": 55.0,
                "charging_efficiency": 0.92,
                "discharging_efficiency": 0.9,
                "self_discharge_per_hour": 0.001,
            },
            "assumptions": {
                "model": "Abstract flywheel-based storage; simulated values only.",
                "interval_hours": 1,
            },
            "metrics": {
                "renewable_generated_kwh": 1277.16,
                "household_consumption_kwh": 1715.48,
                "grid_imports_kwh": 396.68,
                "grid_exports_kwh": 0.0,
                "initial_storage_kwh": 176.0,
                "energy_stored_kwh": 600.5,
                "energy_discharged_kwh": 694.35,
                "storage_losses_kwh": 134.36,
                "ending_storage_kwh": 0.0,
                "curtailed_energy_kwh": 0.0,
                "unserved_energy_kwh": 0.0,
                "storage_utilization_percent": 4.52,
                "energy_balance_error_kwh": 0.0,
            },
        }
    )

    assert context["simulated"] is True
    assert context["energy_balance"]["renewable_generated_kwh"] == 1277.16
    assert context["energy_balance"]["initial_storage_kwh"] == 176.0
    assert context["storage_accounting"]["energy_discharged_kwh"] == 694.35
    assert context["storage_accounting"]["capacity_kwh"] == 320.0
    assert context["storage_accounting"]["storage_utilization_percent"] == 4.52
    assert context["duration_hours"] == 48
    assert context["assumptions"]["interval_hours"] == 1
    assert context["simulation_parameters"]["duration_hours"] == 48
    instructions = advisor.SYSTEM_INSTRUCTIONS.lower()
    assert (
        "renewable generation + grid imports + initial storage = household consumption - "
        "unserved energy + grid exports + curtailment + storage losses + ending storage"
    ) in instructions
    assert "derived metrics" in instructions
    assert "planning inputs" in instructions
    assert "storage discharge is an internal transfer" in instructions
    assert "never add discharged energy to solar generation" in instructions
    assert "discharged energy came from initial storage" in instructions
    assert "not state of charge" in instructions
    assert "do not invent missing values" in instructions
    assert "causal claims not established" in instructions


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
    assert "Use supplied values for numerical claims" in messages[0]["content"]
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
