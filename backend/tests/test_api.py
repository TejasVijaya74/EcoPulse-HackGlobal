import logging

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from fastapi.testclient import TestClient

from app.database import SessionLocal, get_db
from app.main import app, fastapi_app
from app.models import CreditTransaction, SimulationRecord
from app.config import CORS_ORIGINS

FRONTEND_ORIGIN = CORS_ORIGINS[0]


def production_simulation_payload():
    return {
        "scenario": "normal",
        "households": 60,
        "solar_capacity_kw": 180,
        "storage_capacity_kwh": 320,
        "initial_storage_percent": 55,
        "grid_import_limit_kw": 250,
        "grid_export_limit_kw": 120,
        "cloud_cover": 0.35,
        "temperature_c": 22,
        "demand_multiplier": 1,
        "grid_available": True,
        "duration_hours": 48,
        "random_seed": 42,
    }


def grid_outage_payload():
    return {
        "scenario": "grid_outage",
        "households": 2,
        "solar_capacity_kw": 30,
        "storage_capacity_kwh": 5,
        "initial_storage_percent": 50,
        "grid_import_limit_kw": 100,
        "grid_export_limit_kw": 10,
        "cloud_cover": 0.6,
        "temperature_c": 22,
        "demand_multiplier": 1,
        "grid_available": False,
        "duration_hours": 24,
        "random_seed": 4,
    }


def test_health_and_forecast_api():
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["database"] == "connected"
        response = client.get("/api/v1/forecast")
        assert response.status_code == 200
        body = response.json()
        assert len(body["forecast"]) == 24
        assert body["model"] == "RandomForestRegressor"
        assert body["model_version"]
        assert body["model_metrics"]["solar_generation"]["model"]["mae"] >= 0
        assert body["model_metrics"]["household_demand"]["baseline"]["rmse"] >= 0
        assert all(point["solar_generation_kw"] >= 0 for point in body["forecast"])
        assert all(point["household_demand_kw"] >= 0 for point in body["forecast"])
        assert "solar_lower_kw" in body["forecast"][0]
        assert body["weather_source"] in {"open-meteo", "synthetic"}
        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["weather"]["source"] in {"open-meteo", "synthetic"}
        carbon = dashboard.json()["carbon_impact"]
        assert carbon["simulated_estimate"] is True
        assert carbon["grid_emissions_factor"]["units"] == "kg CO2/kWh"
        assert carbon["grid_emissions_factor"]["source"]
        assert carbon["grid_emissions_factor"]["reporting_year"]
        with client.websocket_connect(
            "/ws/grid-telemetry", headers={"origin": FRONTEND_ORIGIN}
        ) as socket:
            telemetry = socket.receive_json()
            assert telemetry["simulated"] is True
            assert telemetry["solar_generation_kw"] >= 0


def test_health_database_failure_does_not_expose_database_details(monkeypatch, caplog):
    class BrokenDatabase:
        def execute(self, _statement):
            raise RuntimeError("postgresql://test-user:test-password@db.example/test")

    def broken_database():
        yield BrokenDatabase()

    monkeypatch.setitem(fastapi_app.dependency_overrides, get_db, broken_database)
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database unavailable."
    assert "test-password" not in response.text
    assert "test-password" not in caplog.text


def test_forecast_failure_returns_safe_error(monkeypatch, caplog):
    from app.api import routes

    def fail_forecast(*_args):
        raise ValueError("private-model-path")

    monkeypatch.setattr(routes, "forecast", fail_forecast)
    with TestClient(app) as client:
        with caplog.at_level(logging.ERROR, logger="app.api.routes"):
            response = client.get("/api/v1/forecast")

    assert response.status_code == 500
    assert response.json()["detail"] == "Forecast could not be generated."
    assert "private-model-path" not in response.text
    assert "private-model-path" not in caplog.text


def test_advisor_endpoint_requires_configured_backend_key(monkeypatch, auth_headers):
    from app.services import advisor

    monkeypatch.setattr(advisor, "GROQ_API_KEY", "")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/advisor",
            json={"question": "Explain grid imports"},
            headers=auth_headers,
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "The Energy Advisor is not configured."


def test_advisor_endpoint_returns_only_advisor_errors_without_breaking_dashboard(
    monkeypatch, auth_headers
):
    from app.api import routes
    from app.services.advisor import AdvisorTimeout

    async def timeout(_question, _context):
        raise AdvisorTimeout("The Energy Advisor request timed out. Please try again.")

    monkeypatch.setattr(routes, "GROQ_API_KEY", "backend-test-key")
    monkeypatch.setattr(routes, "ask_energy_advisor", timeout)
    with TestClient(app) as client:
        advisor_response = client.post(
            "/api/v1/advisor",
            json={"question": "Explain storage"},
            headers=auth_headers,
        )
        dashboard_response = client.get("/api/v1/dashboard")

    assert advisor_response.status_code == 504
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["metrics"]


def test_advisor_receives_optional_weather_and_research_context(monkeypatch, auth_headers):
    from app.api import routes

    captured = {}

    async def advisor_answer(question, context):
        captured["question"] = question
        captured["context"] = context
        return "The supplied figures show the requested trend."

    monkeypatch.setattr(routes, "GROQ_API_KEY", "backend-test-key")
    monkeypatch.setattr(
        routes,
        "get_weatherapi_forecast",
        lambda **_kwargs: {"source": "WeatherAPI.com", "current": {"temperature_c": 24}},
    )
    monkeypatch.setattr(
        routes,
        "search_research",
        lambda topic: {
            "source": "Tavily Search",
            "topic": topic,
            "results": [{"title": "Source", "source_url": "https://example.org/source"}],
        },
    )
    monkeypatch.setattr(routes, "ask_energy_advisor", advisor_answer)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/advisor",
            json={"question": "How does the forecast affect storage?", "research_topic": "storage"},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    assert captured["question"] == "How does the forecast affect storage?"
    assert captured["context"]["external_weather"]["source"] == "WeatherAPI.com"
    assert captured["context"]["energy_research"]["topic"] == "storage"
    assert captured["context"]["energy_research"]["results"][0]["source_url"] == "https://example.org/source"


def test_optional_intelligence_provider_failures_do_not_block_simulation(
    monkeypatch, auth_headers
):
    from app.api import routes
    from app.services.research import ResearchNotConfigured
    from app.services.weatherapi import WeatherNotConfigured

    def missing_weather(*_args, **_kwargs):
        raise WeatherNotConfigured("WeatherAPI is not configured.")

    def missing_research(_topic):
        raise ResearchNotConfigured("Energy research is not configured.")

    monkeypatch.setattr(routes, "get_weatherapi_forecast", missing_weather)
    monkeypatch.setattr(routes, "search_research", missing_research)

    with TestClient(app) as client:
        weather = client.get("/api/v1/intelligence/overview", headers=auth_headers)
        research = client.get(
            "/api/v1/intelligence/research?topic=solar", headers=auth_headers
        )
        simulation = client.post(
            "/api/v1/simulate",
            json=grid_outage_payload(),
            headers=auth_headers,
        )
        result = simulation.json()
        detail = (
            client.get(f"/api/v1/simulation/{result['id']}").json()
            if simulation.status_code == 200
            else {}
        )

    assert weather.status_code == 503
    assert research.status_code == 503
    assert simulation.status_code == 200, simulation.text
    assert result["metrics"]["grid_imports_kwh"] == 0
    assert "external_weather" not in result
    assert "energy_research" not in result
    assert "weather" not in detail
    assert "external_weather" not in detail
    assert "energy_research" not in detail


def test_cors_allows_frontend_get_and_preflight_and_rejects_other_origins(monkeypatch):
    monkeypatch.setattr(app, "allow_origins", [FRONTEND_ORIGIN])
    with TestClient(app) as client:
        response = client.get("/api/v1/config", headers={"Origin": FRONTEND_ORIGIN})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN

        preflight = client.options(
            "/api/v1/config",
            headers={
                "Origin": FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
        allowed_methods = preflight.headers["access-control-allow-methods"]
        assert all(
            method in allowed_methods
            for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        )

        disallowed = client.get(
            "/api/v1/config", headers={"Origin": "https://untrusted.example"}
        )
        assert disallowed.status_code == 200
        assert "access-control-allow-origin" not in disallowed.headers


def test_cors_headers_are_added_to_unhandled_error_responses(monkeypatch):
    monkeypatch.setattr(app, "allow_origins", [FRONTEND_ORIGIN])

    def raise_error():
        raise RuntimeError("test error")

    fastapi_app.add_api_route("/_test/cors-error", raise_error, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/_test/cors-error", headers={"Origin": FRONTEND_ORIGIN}
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_simulation_is_saved_and_creates_credit_ledger_entries(auth_headers):
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/simulate",
            json=grid_outage_payload(),
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["id"]
        assert result["metrics"]["grid_imports_kwh"] == 0
        detail = client.get(f"/api/v1/simulation/{result['id']}")
        assert detail.status_code == 200
        history = client.get("/api/v1/simulation/history")
        assert any(item["id"] == result["id"] for item in history.json()["items"])
        ledger = client.get("/api/v1/credits").json()
        assert ledger["total_credits"] >= result["metrics"]["community_credits"]
        simulation_transactions = [
            item for item in ledger["transactions"] if item["simulation_id"] == result["id"]
        ]
        assert len(simulation_transactions) == 2
        assert all(item["transaction_type"] == "community_contribution" for item in simulation_transactions)
        assert abs(
            sum(item["energy_kwh"] for item in simulation_transactions)
            - result["metrics"]["community_contribution_kwh"]
        ) <= 0.00001
        assert abs(
            sum(item["credits"] for item in simulation_transactions)
            - result["metrics"]["community_credits"]
        ) <= 0.001
        assert ledger["energy_bank"]["virtual"] is True
        assert ledger["energy_bank"]["capacity_kwh"] == result["parameters"]["storage_capacity_kwh"]
        assert ledger["energy_bank"]["community_contribution_kwh"] == result["metrics"]["community_contribution_kwh"]


def test_exact_production_simulation_payload_persists_multiple_credit_records(auth_headers):
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/simulate",
            json=production_simulation_payload(),
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        result = response.json()
        assert {
            "id",
            "created_at",
            "scenario_label",
            "parameters",
            "metrics",
            "series",
            "baseline",
            "normal_comparison",
        } <= result.keys()
        assert result["parameters"]["households"] == 60
        carbon = result["carbon_impact"]
        assert carbon["available"] is True
        assert carbon["community"]["estimated_emissions_kg_co2"] == round(
            carbon["community"]["grid_imports_kwh"]
            * carbon["grid_emissions_factor"]["value"],
            2,
        )
        assert carbon["avoidance_available"] is True
        comparison = result["optimization_comparison"]
        assert comparison["shared_inputs"]["identical"] is True
        assert comparison["shared_inputs"]["duration_hours"] == result["parameters"]["duration_hours"]
        assert comparison["shared_inputs"]["random_seed"] == result["parameters"]["random_seed"]
        assert comparison["baseline"]["metrics"]["initial_storage_kwh"] == comparison["optimized"]["metrics"]["initial_storage_kwh"]
        assert abs(comparison["baseline"]["metrics"]["energy_balance_error_kwh"]) < 0.01
        assert abs(comparison["optimized"]["metrics"]["energy_balance_error_kwh"]) < 0.01

        with SessionLocal() as db:
            transactions = (
                db.query(CreditTransaction)
                .filter(CreditTransaction.simulation_id == result["id"])
                .all()
            )
        assert len(transactions) > 1
        assert len(transactions) <= 60
        assert all(row.transaction_type == "community_contribution" for row in transactions)


def test_scenario_laboratory_options_are_available_through_simulation_api(auth_headers):
    with TestClient(app) as client:
        for scenario in ("evening_peak", "solar_surplus", "storage_constraints"):
            payload = {**production_simulation_payload(), "scenario": scenario}
            response = client.post(
                "/api/v1/simulate",
                json=payload,
                headers=auth_headers,
            )

            assert response.status_code == 200, response.text
            result = response.json()
            assert result["scenario"] == scenario
            assert result["optimization_comparison"]["shared_inputs"]["identical"] is True
            assert abs(result["metrics"]["energy_balance_error_kwh"]) < 0.01
            assert result["carbon_impact"]["available"] is True
            assert result["carbon_impact"]["community"]["grid_imports_kwh"] == result["metrics"]["grid_imports_kwh"]


def test_duplicate_household_transaction_invalidates_simulation_contribution_in_totals(
    auth_headers,
):
    with TestClient(app) as client:
        credits_before = client.get("/api/v1/credits").json()["total_credits"]
        response = client.post(
            "/api/v1/simulate",
            json=production_simulation_payload(),
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        result = response.json()

        with SessionLocal() as db:
            original = (
                db.query(CreditTransaction)
                .filter(CreditTransaction.simulation_id == result["id"])
                .first()
            )
            assert original is not None
            duplicate = CreditTransaction(
                timestamp=original.timestamp,
                simulation_id=original.simulation_id,
                household_id=original.household_id,
                energy_kwh=original.energy_kwh,
                credits=original.credits,
                transaction_type=original.transaction_type,
            )
            db.add(duplicate)
            db.commit()
            duplicate_id = duplicate.id

        try:
            ledger = client.get("/api/v1/credits").json()
            assert ledger["total_credits"] == credits_before
            assert ledger["excluded_transactions"] >= 2
            assert all(item["simulation_id"] != result["id"] for item in ledger["transactions"])
        finally:
            with SessionLocal() as db:
                duplicate = db.get(CreditTransaction, duplicate_id)
                if duplicate:
                    db.delete(duplicate)
                    db.commit()


def test_credit_transaction_type_column_fits_generated_value():
    transaction_type = "community_contribution"
    column = CreditTransaction.__table__.c.transaction_type

    assert len(transaction_type) == 22
    assert len(transaction_type) > 20
    assert column.type.length == 40
    assert len(transaction_type) <= column.type.length


def test_credit_transaction_schema_constraints_match_inserted_values():
    table = CreditTransaction.__table__
    columns = table.c

    assert set(table.primary_key.columns.keys()) == {"id"}
    assert columns.id.nullable is False
    assert columns.timestamp.type.timezone is True
    assert columns.timestamp.nullable is False
    assert columns.simulation_id.type.python_type is int
    assert columns.simulation_id.nullable is True
    assert not columns.simulation_id.foreign_keys
    assert columns.household_id.type.length == 40
    assert columns.household_id.nullable is False
    assert columns.energy_kwh.type.python_type is float
    assert columns.energy_kwh.nullable is False
    assert columns.credits.type.python_type is float
    assert columns.credits.nullable is False
    assert columns.transaction_type.type.length == 40
    assert columns.transaction_type.nullable is False
    assert not [constraint for constraint in table.constraints if getattr(constraint, "unique", False)]


def test_simulation_persistence_failure_rolls_back_and_logs_context(caplog, auth_headers):
    with TestClient(app, raise_server_exceptions=False) as client:
        with SessionLocal() as db:
            simulations_before = db.query(SimulationRecord).count()
            credits_before = db.query(CreditTransaction).count()

        def fail_commit(session):
            if any(
                isinstance(instance, (SimulationRecord, CreditTransaction))
                for instance in session.new
            ):
                raise SQLAlchemyError(
                    "injected commit failure with non-sensitive test details"
                )

        event.listen(OrmSession, "before_commit", fail_commit)
        try:
            with caplog.at_level(logging.ERROR, logger="app.api.routes"):
                response = client.post(
                    "/api/v1/simulate",
                    json=production_simulation_payload(),
                    headers=auth_headers,
                )
        finally:
            event.remove(OrmSession, "before_commit", fail_commit)

        assert response.status_code == 500
        assert "No simulation or credit transactions were committed" in response.json()["detail"]
        assert "injected commit failure" not in response.text
        failure_records = [
            record
            for record in caplog.records
            if record.name == "app.api.routes"
            and record.getMessage().startswith("Simulation persistence failed ")
        ]
        assert len(failure_records) == 1
        assert failure_records[0].endpoint == "/api/v1/simulate"
        assert failure_records[0].exception_class == "SQLAlchemyError"
        assert failure_records[0].database_operation == "commit_simulation_and_credit_transactions"
        assert failure_records[0].exc_info is None
        assert "injected commit failure" not in caplog.text
        with SessionLocal() as db:
            assert db.query(SimulationRecord).count() == simulations_before
            assert db.query(CreditTransaction).count() == credits_before


def test_simulation_uses_saved_config_and_explicit_parameters_override_it(auth_headers):
    with TestClient(app) as client:
        original = client.get("/api/v1/config").json()
        changed = {**original, "households": 4, "solar_capacity_kw": 0}
        try:
            response = client.post(
                "/api/v1/config",
                json=changed,
                headers=auth_headers,
            )
            assert response.status_code == 200

            base_payload = {"scenario": "normal", "duration_hours": 24, "random_seed": 12}
            from_config = client.post(
                "/api/v1/simulate",
                json=base_payload,
                headers=auth_headers,
            )
            assert from_config.status_code == 200, from_config.text
            result = from_config.json()
            assert result["parameters"]["households"] == 4
            assert result["parameters"]["solar_capacity_kw"] == 0
            assert result["metrics"]["renewable_generated_kwh"] == 0

            explicit = client.post(
                "/api/v1/simulate",
                json={**base_payload, "households": 8, "solar_capacity_kw": 50},
                headers=auth_headers,
            )
            assert explicit.status_code == 200, explicit.text
            override_result = explicit.json()
            assert override_result["parameters"]["households"] == 8
            assert override_result["parameters"]["solar_capacity_kw"] == 50
            assert override_result["metrics"]["renewable_generated_kwh"] > 0
        finally:
            restored = client.post(
                "/api/v1/config",
                json=original,
                headers=auth_headers,
            )
            assert restored.status_code == 200
