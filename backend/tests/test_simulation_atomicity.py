import logging

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.main import app
from app.models import CreditTransaction, SimulationRecord


def test_credit_insert_failure_rolls_back_simulation_and_returns_safe_error(caplog):
    payload = {
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
    with SessionLocal() as db:
        simulations_before = db.query(SimulationRecord).count()
        credits_before = db.query(CreditTransaction).count()

    def fail_credit_insert(_mapper, _connection, _transaction):
        raise SQLAlchemyError("injected credit transaction insert failure")

    event.listen(CreditTransaction, "before_insert", fail_credit_insert)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            with caplog.at_level(logging.ERROR, logger="app.api.routes"):
                response = client.post("/api/v1/simulate", json=payload)
    finally:
        event.remove(CreditTransaction, "before_insert", fail_credit_insert)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Simulation could not be saved. No simulation or credit transactions were committed."
    )
    assert "injected credit transaction insert failure" not in response.text
    with SessionLocal() as db:
        assert db.query(SimulationRecord).count() == simulations_before
        assert db.query(CreditTransaction).count() == credits_before
