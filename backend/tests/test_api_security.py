from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.api import routes
from app.api.routes import router
from app.config import DEFAULT_CONFIG
from app.database import Base, get_db
from app.middleware import RequestSizeLimitMiddleware
from app.rate_limits import _client_bucket, _consume_window, ensure_rate_limit_storage
from app.services.weatherapi import WeatherTimeout
from app import security

TEST_TOKEN = "test-api-access-token-for-isolated-tests-32"


def valid_config():
    return DEFAULT_CONFIG.copy()


@pytest.fixture
def isolated_client(tmp_path):
    database_path = tmp_path / "api-security.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        ensure_rate_limit_storage(connection)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.add_middleware(RequestSizeLimitMiddleware)
    test_app.state.test_engine = engine
    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as client:
        yield client
    engine.dispose()


@pytest.fixture
def configured_api_token(monkeypatch):
    monkeypatch.setattr(security, "API_ACCESS_TOKEN", TEST_TOKEN)
    return TEST_TOKEN


def test_health_and_configuration_read_require_auth(
    isolated_client, configured_api_token
):
    denied_health = isolated_client.get("/api/v1/health")
    health = isolated_client.get(
        "/api/v1/health",
        headers={"Authorization": f"Bearer {configured_api_token}"},
    )
    denied = isolated_client.get("/api/v1/config")
    config = isolated_client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {configured_api_token}"},
    )

    assert denied_health.status_code == 401
    assert health.status_code == 200
    assert health.json()["database"] == "connected"
    assert denied.status_code == 401
    assert config.status_code == 200
    assert config.json()["households"] == 60


def test_public_demo_exposes_only_safe_preview_data_and_stateless_simulation(
    isolated_client, monkeypatch
):
    monkeypatch.setattr(security, "PUBLIC_DEMO_MODE", True)
    monkeypatch.setattr(
        routes,
        "get_hourly_weather",
        lambda *_args: {
            "source": "synthetic",
            "label": "Synthetic weather",
            "fallback_reason": None,
            "attribution_url": "https://open-meteo.com/",
        },
    )
    monkeypatch.setattr(
        routes,
        "forecast",
        lambda hours, *_args: {"forecast": [{"hour": index} for index in range(hours)]},
    )
    monkeypatch.setattr(
        routes,
        "calculate_simulation",
        lambda *_args: {"scenario_label": "Normal Conditions", "series": [], "metrics": {}},
    )
    with isolated_client.app.state.test_engine.connect() as connection:
        simulations_before = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM simulations"
        ).scalar_one()
        credits_before = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM credit_transactions"
        ).scalar_one()

    status = isolated_client.get("/api/v1/demo/status")
    config = isolated_client.get("/api/v1/demo/config")
    dashboard = isolated_client.get("/api/v1/dashboard")
    forecast = isolated_client.get("/api/v1/forecast")
    simulation = isolated_client.post(
        "/api/v1/demo/simulate",
        json={"scenario": "normal", "duration_hours": 24, "households": 2},
    )

    assert status.status_code == 200
    assert status.json() == {"public_demo_mode": True}
    assert status.headers["cache-control"] == "no-store"
    assert config.status_code == 200
    assert set(config.json()) == {
        "households",
        "solar_capacity_kw",
        "storage_capacity_kwh",
        "initial_storage_percent",
        "grid_import_limit_kw",
        "grid_export_limit_kw",
        "cloud_cover",
        "temperature_c",
        "demand_multiplier",
        "grid_available",
        "random_seed",
    }
    assert dashboard.status_code == 200
    assert forecast.status_code == 200
    assert simulation.status_code == 200
    assert simulation.json()["persisted"] is False
    assert simulation.json()["simulated"] is True
    with isolated_client.app.state.test_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM simulations"
        ).scalar_one() == simulations_before
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM credit_transactions"
        ).scalar_one() == credits_before
    assert "API_ACCESS_TOKEN" not in config.text
    assert "DATABASE_URL" not in config.text


def test_public_provider_endpoints_and_advisor_fail_safely_without_nested_research(
    isolated_client, monkeypatch
):
    monkeypatch.setattr(security, "PUBLIC_DEMO_MODE", True)
    monkeypatch.setattr(routes, "GROQ_API_KEY", "test-only-groq-key")
    monkeypatch.setattr(
        routes,
        "get_weatherapi_forecast",
        lambda *_args, **_kwargs: {"source": "WeatherAPI.com", "current": {}},
    )
    monkeypatch.setattr(routes, "build_weather_insights", lambda *_args: {"available": True})
    research_calls = []

    def unexpected_research(topic):
        research_calls.append(topic)
        return {"available": True, "topic": topic}

    monkeypatch.setattr(routes, "search_research", unexpected_research)
    monkeypatch.setattr(
        routes,
        "get_weatherapi_forecast",
        lambda *_args, **_kwargs: {"source": "WeatherAPI.com", "current": {}},
    )

    async def advisor_answer(_question, context):
        return "Safe demo answer."

    monkeypatch.setattr(routes, "ask_energy_advisor", advisor_answer)
    weather = isolated_client.get("/api/v1/intelligence/overview?location=New%20Delhi")
    research = isolated_client.get("/api/v1/intelligence/research?topic=solar")
    answer = isolated_client.post(
        "/api/v1/advisor",
        json={"question": "Explain simulated grid imports", "research_topic": "solar"},
    )

    assert weather.status_code == 200
    assert research.status_code == 200
    assert answer.status_code == 200
    assert answer.json()["answer"] == "Safe demo answer."
    assert research_calls == ["solar"]

    def missing_weather(*_args, **_kwargs):
        from app.services.weatherapi import WeatherNotConfigured

        raise WeatherNotConfigured("WeatherAPI is not configured.")

    def missing_research(_topic):
        from app.services.research import ResearchNotConfigured

        raise ResearchNotConfigured("Energy research is not configured.")

    monkeypatch.setattr(routes, "get_weatherapi_forecast", missing_weather)
    monkeypatch.setattr(routes, "search_research", missing_research)
    unavailable_weather = isolated_client.get("/api/v1/intelligence/overview")
    unavailable_research = isolated_client.get(
        "/api/v1/intelligence/research?topic=solar"
    )

    assert unavailable_weather.status_code == 503
    assert unavailable_weather.json()["detail"] == "WeatherAPI is not configured."
    assert unavailable_research.status_code == 503
    assert unavailable_research.json()["detail"] == "Energy research is not configured."


def test_public_mode_keeps_private_and_mutating_routes_protected(
    isolated_client, monkeypatch
):
    monkeypatch.setattr(security, "PUBLIC_DEMO_MODE", True)
    protected_reads = (
        "/api/v1/health",
        "/api/v1/config",
        "/api/v1/credits",
        "/api/v1/simulation/history",
        "/api/v1/simulation/1",
        "/api/v1/intelligence/weather/current",
    )
    for path in protected_reads:
        assert isolated_client.get(path).status_code == 401

    assert isolated_client.post("/api/v1/config", json=valid_config()).status_code == 401
    assert isolated_client.post(
        "/api/v1/simulate",
        json={"scenario": "normal", "duration_hours": 24},
    ).status_code == 401
    assert isolated_client.post("/api/v1/model/train").status_code == 401


def test_public_input_validation_and_request_size_limit(isolated_client, monkeypatch):
    monkeypatch.setattr(security, "PUBLIC_DEMO_MODE", True)
    invalid_requests = (
        isolated_client.get("/api/v1/forecast?hours=49"),
        isolated_client.get("/api/v1/intelligence/research?topic=unsupported"),
        isolated_client.get("/api/v1/intelligence/overview?location=Delhi%2Fprivate"),
        isolated_client.post(
            "/api/v1/demo/simulate",
            json={"scenario": "normal", "duration_hours": 49},
        ),
        isolated_client.post(
            "/api/v1/demo/simulate",
            json={"scenario": "normal", "households": 251},
        ),
        isolated_client.post("/api/v1/advisor", json={"question": "   "}),
    )
    assert all(response.status_code == 422 for response in invalid_requests)

    too_large = isolated_client.post(
        "/api/v1/advisor",
        content=b'{"question":"' + b"x" * 16_384 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert too_large.status_code == 413
    assert too_large.json()["detail"] == "Request body is too large."


def test_public_rate_limit_returns_retry_after(isolated_client, monkeypatch):
    monkeypatch.setattr(security, "PUBLIC_DEMO_MODE", True)
    monkeypatch.setattr("app.rate_limits.time.time", lambda: 1_800_000_000)

    responses = [isolated_client.get("/api/v1/demo/status") for _ in range(61)]

    assert all(response.status_code == 200 for response in responses[:60])
    assert responses[60].status_code == 429
    assert int(responses[60].headers["retry-after"]) > 0


def test_public_routes_require_auth_when_demo_mode_is_disabled(
    isolated_client, configured_api_token, monkeypatch
):
    monkeypatch.setattr(security, "PUBLIC_DEMO_MODE", False)

    for path in (
        "/api/v1/dashboard",
        "/api/v1/forecast",
        "/api/v1/demo/config",
        "/api/v1/intelligence/overview",
        "/api/v1/intelligence/research",
    ):
        assert isolated_client.get(path).status_code == 401
    assert isolated_client.post(
        "/api/v1/demo/simulate",
        json={"scenario": "normal", "duration_hours": 24},
    ).status_code == 401
    assert isolated_client.get("/api/v1/demo/status").json() == {
        "public_demo_mode": False
    }


def test_protected_operation_fails_closed_when_token_is_not_configured(
    isolated_client, monkeypatch
):
    monkeypatch.setattr(security, "API_ACCESS_TOKEN", "")

    response = isolated_client.post("/api/v1/config", json=valid_config())

    assert response.status_code == 503
    assert response.json()["detail"] == "Protected API operations are not configured."


def test_short_configured_token_fails_closed(isolated_client, monkeypatch):
    monkeypatch.setattr(security, "API_ACCESS_TOKEN", "too-short")

    response = isolated_client.post("/api/v1/config", json=valid_config())

    assert response.status_code == 503


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic dXNlcjpwYXNz", "Bearer wrong-token"],
)
def test_missing_or_invalid_bearer_token_is_rejected(
    isolated_client, configured_api_token, authorization
):
    headers = {"Authorization": authorization} if authorization else {}

    response = isolated_client.post(
        "/api/v1/config",
        json=valid_config(),
        headers=headers,
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_config_update_requires_and_accepts_bearer_token(
    isolated_client, configured_api_token
):
    headers = {"Authorization": f"Bearer {configured_api_token}"}
    updated = isolated_client.get("/api/v1/config", headers=headers).json()
    updated["households"] = 12

    denied = isolated_client.post("/api/v1/config", json=updated)
    allowed = isolated_client.post(
        "/api/v1/config",
        json=updated,
        headers={"Authorization": f"Bearer {configured_api_token}"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["households"] == 12
    assert isolated_client.get("/api/v1/config", headers=headers).json()["households"] == 12


def test_provider_endpoint_requires_auth_and_preserves_response_shape(
    isolated_client, configured_api_token, monkeypatch
):
    calls = []

    def get_current(location):
        calls.append(location)
        return {
            "source": "WeatherAPI.com",
            "location": {"name": location or "New Delhi"},
            "current": {"temperature_c": 24.0},
        }

    monkeypatch.setattr(routes, "get_weatherapi_current", get_current)

    denied = isolated_client.get("/api/v1/intelligence/weather/current")
    allowed = isolated_client.get(
        "/api/v1/intelligence/weather/current?location=Delhi",
        headers={"Authorization": f"Bearer {configured_api_token}"},
    )

    assert denied.status_code == 401
    assert calls == ["Delhi"]
    assert allowed.status_code == 200
    assert allowed.json()["source"] == "WeatherAPI.com"
    assert allowed.json()["current"]["temperature_c"] == 24.0


def test_weather_provider_timeout_returns_safe_gateway_error(
    isolated_client, configured_api_token, monkeypatch
):
    def timeout(_location):
        raise WeatherTimeout("WeatherAPI request timed out.")

    monkeypatch.setattr(routes, "get_weatherapi_current", timeout)

    response = isolated_client.get(
        "/api/v1/intelligence/weather/current",
        headers={"Authorization": f"Bearer {configured_api_token}"},
    )

    assert response.status_code == 504
    assert response.json()["detail"] == "WeatherAPI request timed out."
    assert configured_api_token not in response.text


def test_unauthorized_requests_do_not_write_rate_limit_rows(
    isolated_client, configured_api_token
):
    responses = [
        isolated_client.post(
            "/api/v1/config",
            json=valid_config(),
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses] == [401] * 6
    with isolated_client.app.state.test_engine.connect() as connection:
        count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM api_rate_limit_windows"
        ).scalar_one()
    assert count == 0


def test_rate_limit_returns_retry_after_for_authenticated_requests(
    isolated_client, configured_api_token, monkeypatch
):
    monkeypatch.setattr("app.rate_limits.time.time", lambda: 1_800_000_000)
    headers = {"Authorization": f"Bearer {configured_api_token}"}
    responses = [
        isolated_client.post(
            "/api/v1/config",
            json=valid_config(),
            headers=headers,
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [200] * 5
    assert responses[5].status_code == 429
    assert int(responses[5].headers["retry-after"]) > 0


def test_forwarded_headers_do_not_change_rate_limit_client_identity():
    def request_with_forwarded_ip(forwarded_ip):
        return Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", forwarded_ip.encode("ascii"))],
                "client": ("192.0.2.10", 12345),
                "server": ("testserver", 80),
                "scheme": "http",
                "method": "GET",
                "path": "/",
                "query_string": b"",
            }
        )

    assert _client_bucket(request_with_forwarded_ip("198.51.100.1"), "test") == (
        _client_bucket(request_with_forwarded_ip("203.0.113.1"), "test")
    )


def test_rate_limit_counter_is_shared_between_database_sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shared-limits.sqlite'}")
    with engine.begin() as connection:
        ensure_rate_limit_storage(connection)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    first_session = test_session()
    second_session = test_session()
    try:
        assert _consume_window(first_session, "global:test-shared", 1, 60) == 0
        assert _consume_window(second_session, "global:test-shared", 1, 60) > 0
    finally:
        first_session.close()
        second_session.close()
        engine.dispose()


def test_concurrent_requests_increment_one_shared_rate_limit_window(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-limits.sqlite'}",
        connect_args={"timeout": 10},
    )
    with engine.begin() as connection:
        ensure_rate_limit_storage(connection)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def consume():
        with test_session() as db:
            return _consume_window(db, "global:concurrent-test", 5, 60)

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            retry_afters = list(executor.map(lambda _index: consume(), range(32)))
        assert retry_afters.count(0) == 5
        assert sum(retry_after > 0 for retry_after in retry_afters) == 27
    finally:
        engine.dispose()


def test_simulation_remains_compatible_when_authorized(
    isolated_client, configured_api_token
):
    response = isolated_client.post(
        "/api/v1/simulate",
        json={"scenario": "normal", "duration_hours": 24, "households": 2, "random_seed": 17},
        headers={"Authorization": f"Bearer {configured_api_token}"},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["simulated"] is True
    assert result["parameters"]["households"] == 2
    assert result["optimization_comparison"]["shared_inputs"]["identical"] is True
