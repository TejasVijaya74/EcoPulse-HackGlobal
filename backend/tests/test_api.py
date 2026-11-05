from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import CreditTransaction, SimulationRecord


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
        with client.websocket_connect("/ws/grid-telemetry") as socket:
            telemetry = socket.receive_json()
            assert telemetry["simulated"] is True
            assert telemetry["solar_generation_kw"] >= 0


def test_simulation_is_saved_and_creates_credit_ledger_entries():
    with TestClient(app) as client:
        response = client.post("/api/v1/simulate", json=grid_outage_payload())
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
            sum(item["credits"] for item in simulation_transactions)
            - result["metrics"]["community_credits"]
        ) <= 0.02


def test_credit_transaction_type_column_fits_generated_value():
    transaction_type = "community_contribution"
    column = CreditTransaction.__table__.c.transaction_type

    assert len(transaction_type) == 22
    assert len(transaction_type) > 20
    assert column.type.length == 40
    assert len(transaction_type) <= column.type.length


def test_simulation_persistence_failure_rolls_back_all_rows():
    with TestClient(app, raise_server_exceptions=False) as client:
        with SessionLocal() as db:
            simulations_before = db.query(SimulationRecord).count()
            credits_before = db.query(CreditTransaction).count()

        def fail_commit(_session):
            raise SQLAlchemyError("injected commit failure")

        event.listen(OrmSession, "before_commit", fail_commit)
        try:
            response = client.post("/api/v1/simulate", json=grid_outage_payload())
        finally:
            event.remove(OrmSession, "before_commit", fail_commit)

        assert response.status_code == 500
        assert "No simulation or credit transactions were committed" in response.json()["detail"]
        with SessionLocal() as db:
            assert db.query(SimulationRecord).count() == simulations_before
            assert db.query(CreditTransaction).count() == credits_before


def test_simulation_uses_saved_config_and_explicit_parameters_override_it():
    with TestClient(app) as client:
        original = client.get("/api/v1/config").json()
        changed = {**original, "households": 4, "solar_capacity_kw": 0}
        try:
            response = client.post("/api/v1/config", json=changed)
            assert response.status_code == 200

            base_payload = {"scenario": "normal", "duration_hours": 24, "random_seed": 12}
            from_config = client.post("/api/v1/simulate", json=base_payload)
            assert from_config.status_code == 200, from_config.text
            result = from_config.json()
            assert result["parameters"]["households"] == 4
            assert result["parameters"]["solar_capacity_kw"] == 0
            assert result["metrics"]["renewable_generated_kwh"] == 0

            explicit = client.post(
                "/api/v1/simulate",
                json={**base_payload, "households": 8, "solar_capacity_kw": 50},
            )
            assert explicit.status_code == 200, explicit.text
            override_result = explicit.json()
            assert override_result["parameters"]["households"] == 8
            assert override_result["parameters"]["solar_capacity_kw"] == 50
            assert override_result["metrics"]["renewable_generated_kwh"] > 0
        finally:
            restored = client.post("/api/v1/config", json=original)
            assert restored.status_code == 200
