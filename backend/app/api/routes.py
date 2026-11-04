import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from app.config import DEFAULT_CONFIG
from app.database import get_db
from app.energy.simulator import simulate
from app.ml.predictor import forecast
from app.ml.train import train_models
from app.models import ConfigurationRecord, CreditTransaction, ModelTrainingRecord, SimulationRecord
from app.schemas import ConfigurationUpdate, SimulationParameters
from app.services.analytics import create_dashboard_preview, dashboard_from_result
from app.services.weather import get_hourly_weather

router = APIRouter(prefix="/api/v1")


def current_config(db: Session) -> dict:
    record = db.get(ConfigurationRecord, 1)
    if record is None:
        return DEFAULT_CONFIG.copy()
    return json.loads(record.values_json)


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return {"status": "ok", "database": database_status, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    config = current_config(db)
    latest = db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
    if latest:
        result = dashboard_from_result(json.loads(latest.result_json))
    else:
        result = create_dashboard_preview(config)
    weather = get_hourly_weather(1, config["solar_capacity_kw"])
    result["weather"] = {
        "source": weather["source"],
        "label": weather["label"],
        "fallback_reason": weather["fallback_reason"],
        "attribution_url": weather["attribution_url"],
    }
    return result


@router.get("/forecast")
def get_forecast(
    hours: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(get_db),
) -> dict:
    config = current_config(db)
    try:
        prediction = forecast(hours, config["households"], config["solar_capacity_kw"])
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Forecast could not be generated: {exc}") from exc
    training = db.query(ModelTrainingRecord).order_by(desc(ModelTrainingRecord.trained_at)).first()
    metrics = json.loads(training.metrics_json) if training else {}
    model_version = metrics.pop("_metadata", {}).get("scikit_learn_version")
    return prediction | {
        "model_metrics": metrics,
        "model": "RandomForestRegressor",
        "model_version": model_version,
    }


@router.post("/simulate")
def run_simulation(parameters: SimulationParameters, db: Session = Depends(get_db)) -> dict:
    config = current_config(db)
    result = simulate(parameters, config)
    normal_parameters = parameters.model_copy(
        update={"scenario": "normal", "grid_available": True if parameters.scenario == "grid_outage" else parameters.grid_available}
    )
    normal_result = result if parameters.scenario == "normal" else simulate(normal_parameters, config)
    result["normal_comparison"] = {
        "scenario_label": "Normal Conditions",
        "metrics": normal_result["metrics"],
    }
    record = SimulationRecord(
        scenario=parameters.scenario,
        parameters_json=json.dumps(result["parameters"]),
        result_json=json.dumps(result),
    )
    db.add(record)
    db.flush()
    total_energy = result["metrics"]["community_contribution_kwh"]
    total_credits = result["metrics"]["community_credits"]
    households = max(1, result["parameters"]["households"])
    now = datetime.now(timezone.utc)
    for index in range(households):
        energy_share = total_energy / households
        if energy_share > 0:
            db.add(
                CreditTransaction(
                    timestamp=now,
                    simulation_id=record.id,
                    household_id=f"HH-{index + 1:03d}",
                    energy_kwh=energy_share,
                    credits=total_credits / households,
                    transaction_type="community_contribution",
                )
            )
    db.commit()
    result["id"] = record.id
    result["created_at"] = record.created_at.isoformat()
    return result


@router.get("/simulation/history")
def simulation_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    records = db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).limit(limit).all()
    return {
        "items": [
            {
                "id": record.id,
                "created_at": record.created_at.isoformat(),
                "scenario": record.scenario,
                "metrics": json.loads(record.result_json)["metrics"],
            }
            for record in records
        ]
    }


@router.get("/simulation/{simulation_id}")
def simulation_detail(simulation_id: int, db: Session = Depends(get_db)) -> dict:
    record = db.get(SimulationRecord, simulation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    return json.loads(record.result_json) | {"id": record.id, "created_at": record.created_at.isoformat()}


@router.get("/credits")
def credits(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.query(CreditTransaction).order_by(desc(CreditTransaction.timestamp)).limit(limit).all()
    totals = (
        db.query(CreditTransaction.household_id, CreditTransaction.credits)
        .order_by(CreditTransaction.household_id)
        .all()
    )
    by_household: dict[str, float] = {}
    for household_id, earned in totals:
        by_household[household_id] = by_household.get(household_id, 0.0) + earned
    return {
        "total_credits": round(sum(by_household.values()), 2),
        "household_credits": [
            {"household_id": household, "credits": round(value, 2)}
            for household, value in sorted(by_household.items())
        ],
        "transactions": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat(),
                "household_id": row.household_id,
                "energy_kwh": round(row.energy_kwh, 3),
                "credits": round(row.credits, 2),
                "transaction_type": row.transaction_type,
                "simulation_id": row.simulation_id,
            }
            for row in rows
        ],
        "notice": "Simulated incentive ledger only; credits are not money or a payment instrument.",
    }


@router.get("/config")
def get_config(db: Session = Depends(get_db)) -> dict:
    return current_config(db)


@router.post("/config")
def update_config(parameters: ConfigurationUpdate, db: Session = Depends(get_db)) -> dict:
    record = db.get(ConfigurationRecord, 1)
    values = parameters.model_dump()
    if record is None:
        record = ConfigurationRecord(id=1, values_json=json.dumps(values))
        db.add(record)
    else:
        record.values_json = json.dumps(values)
        record.updated_at = datetime.now(timezone.utc)
    db.commit()
    return values


@router.post("/model/train")
def retrain_models(db: Session = Depends(get_db)) -> dict:
    try:
        result = train_models()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    training = ModelTrainingRecord(
        trained_at=datetime.now(timezone.utc),
        metrics_json=json.dumps(
            {
                **result["metrics"],
                "_metadata": {
                    "scikit_learn_version": result["model_version"],
                    "training_data_version": result["training_data_version"],
                },
            }
        ),
        samples=result["samples"],
    )
    db.add(training)
    db.commit()
    return {
        "trained_at": training.trained_at.isoformat(),
        "samples": training.samples,
        "model_version": result["model_version"],
        "training_data_version": result["training_data_version"],
        "metrics": result["metrics"],
    }
