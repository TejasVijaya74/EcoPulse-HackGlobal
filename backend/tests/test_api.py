import logging

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as OrmSession
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import CreditTransaction, SimulationRecord


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


def test_exact_production_simulation_payload_persists_multiple_credit_records():
    with TestClient(app) as client:
        response = client.post("/api/v1/simulate", json=production_simulation_payload())

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

        with SessionLocal() as db:
            transactions = (
                db.query(CreditTransaction)
                .filter(CreditTransaction.simulation_id == result["id"])
                .all()
            )
        assert len(transactions) > 1
        assert len(transactions) <= 60
        assert all(row.transaction_type == "community_contribution" for row in transactions)


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


def test_simulation_persistence_failure_rolls_back_and_logs_context(caplog):
    with TestClient(app, raise_server_exceptions=False) as client:
        with SessionLocal() as db:
            simulations_before = db.query(SimulationRecord).count()
            credits_before = db.query(CreditTransaction).count()

        def fail_commit(_session):
            raise SQLAlchemyError("injected commit failure with non-sensitive test details")

        event.listen(OrmSession, "before_commit", fail_commit)
        try:
            with caplog.at_level(logging.ERROR, logger="app.api.routes"):
                response = client.post("/api/v1/simulate", json=production_simulation_payload())
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
        assert failure_records[0].exc_info is not None
        assert "injected commit failure" in caplog.text
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
