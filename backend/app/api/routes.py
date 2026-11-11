import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import DEFAULT_CONFIG, GROQ_API_KEY, WEATHERAPI_DEFAULT_LOCATION
from app.database import get_db
from app.energy.simulator import simulate
from app.ml.predictor import forecast
from app.ml.train import train_models
from app.models import (
    CommunityBankResetRecord,
    ConfigurationRecord,
    CreditTransaction,
    ModelTrainingRecord,
    SimulationRecord,
)
from app.rate_limits import rate_limit
from app.security import require_api_token
from app.schemas import AdvisorRequest, ConfigurationUpdate, ResearchTopic, SimulationParameters
from app.services.advisor import (
    AdvisorNotConfigured,
    AdvisorRateLimited,
    AdvisorTimeout,
    AdvisorUnavailable,
    ask_energy_advisor,
    build_advisor_context,
)
from app.services.analytics import (
    build_optimization_comparison,
    create_dashboard_preview,
    dashboard_from_result,
)
from app.services.carbon import build_carbon_impact
from app.services.community_bank import (
    allocate_community_contribution,
    validate_contribution_transactions,
)
from app.services.intelligence import build_weather_insights
from app.services.research import (
    ResearchInvalidResponse,
    ResearchNotConfigured,
    ResearchRateLimited,
    ResearchTimeout,
    ResearchUnavailable,
    search_research,
)
from app.services.weather import get_hourly_weather
from app.services.weatherapi import (
    WeatherAPIError,
    WeatherInvalidResponse,
    WeatherNotConfigured,
    WeatherRateLimited,
    WeatherTimeout,
    WeatherUnavailable,
    get_current as get_weatherapi_current,
    get_forecast as get_weatherapi_forecast,
    search_locations as search_weatherapi_locations,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def _protected_dependencies(
    name: str,
    client_limit: int,
    global_limit: int,
    window_seconds: int = 60,
) -> list:
    return [
        Depends(require_api_token),
        Depends(rate_limit(name, client_limit, window_seconds)),
        Depends(rate_limit(name, global_limit, window_seconds, scope="global")),
    ]


def _weather_http_exception(exc: WeatherAPIError) -> HTTPException:
    if isinstance(exc, WeatherNotConfigured):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, WeatherRateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, WeatherTimeout):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, WeatherInvalidResponse):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _research_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, ResearchNotConfigured):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ResearchRateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, ResearchTimeout):
        return HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, ResearchInvalidResponse):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ResearchUnavailable):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


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
        logger.error("Health check database query failed exception_class=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable.") from exc
    return {"status": "ok", "database": database_status, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get(
    "/dashboard",
    dependencies=[Depends(rate_limit("dashboard", 30, 60))],
)
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


@router.get(
    "/forecast",
    dependencies=[Depends(rate_limit("forecast", 20, 60))],
)
def get_forecast(
    hours: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(get_db),
) -> dict:
    config = current_config(db)
    try:
        prediction = forecast(hours, config["households"], config["solar_capacity_kw"])
    except (ValueError, OSError) as exc:
        logger.error("Forecast generation failed exception_class=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Forecast could not be generated.") from exc
    training = db.query(ModelTrainingRecord).order_by(desc(ModelTrainingRecord.trained_at)).first()
    metrics = json.loads(training.metrics_json) if training else {}
    model_version = metrics.pop("_metadata", {}).get("scikit_learn_version")
    return prediction | {
        "model_metrics": metrics,
        "model": "RandomForestRegressor",
        "model_version": model_version,
    }


@router.get(
    "/intelligence/weather/current",
    dependencies=_protected_dependencies("weather", 20, 100),
)
def weather_current(location: str | None = Query(default=None, min_length=1, max_length=120)) -> dict:
    try:
        return get_weatherapi_current(location)
    except WeatherAPIError as exc:
        raise _weather_http_exception(exc) from exc


@router.get(
    "/intelligence/weather/forecast",
    dependencies=_protected_dependencies("weather", 20, 100),
)
def weather_forecast(
    location: str | None = Query(default=None, min_length=1, max_length=120),
    days: int = Query(default=3, ge=1, le=3),
) -> dict:
    try:
        return get_weatherapi_forecast(location, days)
    except WeatherAPIError as exc:
        raise _weather_http_exception(exc) from exc


@router.get(
    "/intelligence/weather/search",
    dependencies=_protected_dependencies("weather", 20, 100),
)
def weather_location_search(query: str = Query(min_length=1, max_length=120)) -> dict:
    try:
        locations = search_weatherapi_locations(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WeatherAPIError as exc:
        raise _weather_http_exception(exc) from exc
    return {"locations": locations, "source": "WeatherAPI.com"}


@router.get(
    "/intelligence/overview",
    dependencies=_protected_dependencies("weather", 20, 100),
)
def energy_intelligence_overview(
    location: str | None = Query(default=None, min_length=1, max_length=120),
    db: Session = Depends(get_db),
) -> dict:
    config = current_config(db)
    try:
        weather_data = get_weatherapi_forecast(location or WEATHERAPI_DEFAULT_LOCATION, 3)
    except WeatherAPIError as exc:
        raise _weather_http_exception(exc) from exc
    return {
        "weather": weather_data,
        "weather_insights": build_weather_insights(weather_data, config),
        "forecast_distinction": (
            "The existing RandomForest forecast remains separate; weather adjustments are relative "
            "planning signals and do not change simulated dispatch."
        ),
    }


@router.get(
    "/intelligence/research",
    dependencies=_protected_dependencies("research", 10, 50),
)
def energy_research(topic: ResearchTopic = Query(default="solar")) -> dict:
    try:
        return search_research(topic)
    except (ResearchNotConfigured, ResearchRateLimited, ResearchTimeout, ResearchUnavailable, ResearchInvalidResponse) as exc:
        raise _research_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/simulate",
    dependencies=_protected_dependencies("simulate", 6, 30),
)
def run_simulation(parameters: SimulationParameters, db: Session = Depends(get_db)) -> dict:
    config = current_config(db)
    result = simulate(parameters, config)
    baseline_result = simulate(parameters, config, dispatch_strategy="baseline")
    result["optimization_comparison"] = build_optimization_comparison(baseline_result, result)
    result["carbon_impact"] = build_carbon_impact(
        result["metrics"],
        result["optimization_comparison"],
        result["parameters"]["households"],
    )
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
    database_operation = "insert_simulation_record"
    try:
        db.add(record)
        db.flush()
        now = datetime.now(timezone.utc)
        allocations = allocate_community_contribution(
            result["metrics"]["community_contribution_kwh"],
            result["parameters"]["credit_rate"],
            result["parameters"]["households"],
        )
        for allocation in allocations:
            db.add(
                CreditTransaction(
                    timestamp=now,
                    simulation_id=record.id,
                    household_id=allocation["household_id"],
                    energy_kwh=allocation["energy_kwh"],
                    credits=allocation["credits"],
                    transaction_type="community_contribution",
                )
            )
        database_operation = "commit_simulation_and_credit_transactions"
        db.commit()
    except SQLAlchemyError as exc:
        logger.error(
            "Simulation persistence failed endpoint=%s exception_class=%s database_operation=%s",
            "/api/v1/simulate",
            type(exc).__name__,
            database_operation,
            extra={
                "endpoint": "/api/v1/simulate",
                "exception_class": type(exc).__name__,
                "database_operation": database_operation,
            },
        )
        try:
            db.rollback()
        except SQLAlchemyError as rollback_exc:
            logger.error(
                "Rollback failed endpoint=%s exception_class=%s original_exception_class=%s database_operation=%s",
                "/api/v1/simulate",
                type(rollback_exc).__name__,
                type(exc).__name__,
                "rollback_simulation_and_credit_transactions",
                extra={
                    "endpoint": "/api/v1/simulate",
                    "exception_class": type(rollback_exc).__name__,
                    "original_exception_class": type(exc).__name__,
                    "database_operation": "rollback_simulation_and_credit_transactions",
                },
            )
        raise HTTPException(
            status_code=500,
            detail="Simulation could not be saved. No simulation or credit transactions were committed.",
        ) from exc
    result["id"] = record.id
    result["created_at"] = record.created_at.isoformat()
    return result


@router.post(
    "/advisor",
    dependencies=_protected_dependencies("advisor", 3, 15),
)
async def energy_advisor(request: AdvisorRequest, db: Session = Depends(get_db)) -> dict:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="The Energy Advisor is not configured.")

    latest = db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
    if latest:
        result = json.loads(latest.result_json)
        if "carbon_impact" not in result:
            result["carbon_impact"] = build_carbon_impact(
                result.get("metrics") or {},
                result.get("optimization_comparison"),
                (result.get("parameters") or {}).get("households"),
            )
    else:
        result = create_dashboard_preview(current_config(db))

    context = build_advisor_context(result)
    try:
        context["external_weather"] = await asyncio.to_thread(
            get_weatherapi_forecast,
            days=1,
        )
    except WeatherAPIError:
        context["external_weather"] = {"available": False, "reason": "WeatherAPI data is unavailable."}
    if request.research_topic:
        try:
            context["energy_research"] = await asyncio.to_thread(
                search_research,
                request.research_topic,
            )
        except (ResearchNotConfigured, ResearchRateLimited, ResearchTimeout, ResearchUnavailable, ResearchInvalidResponse):
            context["energy_research"] = {
                "available": False,
                "reason": "Energy research is unavailable.",
                "topic": request.research_topic,
            }

    try:
        answer = await ask_energy_advisor(request.question, context)
    except AdvisorNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AdvisorRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AdvisorTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except AdvisorUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "answer": answer,
        "scenario": result.get("scenario_label") or result.get("scenario"),
        "generated_at": result.get("created_at"),
        "simulated": True,
    }


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


@router.get(
    "/credits",
    dependencies=_protected_dependencies("credits", 15, 100),
)
def credits(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    all_rows = db.query(CreditTransaction).order_by(desc(CreditTransaction.timestamp)).all()
    simulation_ids = {row.simulation_id for row in all_rows if row.simulation_id is not None}
    simulation_records = (
        db.query(SimulationRecord).filter(SimulationRecord.id.in_(simulation_ids)).all()
        if simulation_ids
        else []
    )
    rows, rejected_count = validate_contribution_transactions(
        all_rows, {record.id: record for record in simulation_records}
    )
    by_household: dict[str, float] = {}
    household_energy: dict[str, float] = {}
    for row in rows:
        by_household[row.household_id] = by_household.get(row.household_id, 0.0) + row.credits
        household_energy[row.household_id] = household_energy.get(row.household_id, 0.0) + row.energy_kwh

    latest_simulation_query = db.query(SimulationRecord)
    reset_record = db.get(CommunityBankResetRecord, 1)
    if reset_record and reset_record.through_simulation_id is not None:
        latest_simulation_query = latest_simulation_query.filter(
            SimulationRecord.id > reset_record.through_simulation_id
        )
    latest = latest_simulation_query.order_by(desc(SimulationRecord.created_at)).first()
    if latest:
        latest_result = json.loads(latest.result_json)
        bank_parameters = latest_result.get("parameters") or {}
        bank_metrics = latest_result.get("metrics") or {}
        capacity = float(bank_parameters.get("storage_capacity_kwh", 0))
        stored = float(bank_metrics.get("ending_storage_kwh", 0))
        bank = {
            "virtual": True,
            "simulation_id": latest.id,
            "capacity_kwh": round(capacity, 2),
            "stored_energy_kwh": round(stored, 2),
            "state_of_charge_percent": round(100 * stored / capacity, 1) if capacity else 0.0,
            "energy_charged_kwh": round(float(bank_metrics.get("energy_stored_kwh", 0)), 2),
            "energy_discharged_kwh": round(float(bank_metrics.get("energy_discharged_kwh", 0)), 2),
            "community_contribution_kwh": round(
                float(bank_metrics.get("community_contribution_kwh", 0)), 2
            ),
        }
    else:
        config = current_config(db)
        capacity = float(config["storage_capacity_kwh"])
        stored = capacity * float(config["initial_storage_percent"]) / 100
        bank = {
            "virtual": True,
            "simulation_id": None,
            "capacity_kwh": round(capacity, 2),
            "stored_energy_kwh": round(stored, 2),
            "state_of_charge_percent": round(float(config["initial_storage_percent"]), 1),
            "energy_charged_kwh": 0.0,
            "energy_discharged_kwh": 0.0,
            "community_contribution_kwh": 0.0,
        }

    return {
        "total_credits": round(sum(by_household.values()), 2),
        "household_credits": [
            {
                "household_id": household,
                "energy_kwh": round(household_energy[household], 3),
                "credits": round(value, 2),
            }
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
            for row in rows[:limit]
        ],
        "energy_bank": bank,
        "excluded_transactions": rejected_count,
        "notice": (
            "Virtual storage and simulated micro-credit allocations only; not household-metered "
            "contributions, real storage, money, or a payment instrument."
        ),
    }


def _upsert_community_bank_reset(
    db: Session,
    through_simulation_id: int | None,
    reset_at: datetime,
) -> None:
    values = {
        "id": 1,
        "through_simulation_id": through_simulation_id,
        "reset_at": reset_at,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError(f"Community bank reset is not supported for {dialect!r}.")

    statement = insert(CommunityBankResetRecord).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[CommunityBankResetRecord.id],
        set_={
            "through_simulation_id": through_simulation_id,
            "reset_at": reset_at,
        },
    )
    db.execute(statement)


@router.post(
    "/credits/reset",
    dependencies=_protected_dependencies("credits_reset", 3, 10),
)
def reset_community_bank(db: Session = Depends(get_db)) -> dict:
    try:
        through_simulation_id = db.query(func.max(SimulationRecord.id)).scalar()
        contribution_query = db.query(CreditTransaction).filter(
            CreditTransaction.transaction_type == "community_contribution"
        )
        if through_simulation_id is not None:
            contribution_query = contribution_query.filter(
                or_(
                    CreditTransaction.simulation_id.is_(None),
                    CreditTransaction.simulation_id <= through_simulation_id,
                )
            )
        deleted_count = contribution_query.delete(synchronize_session=False)
        _upsert_community_bank_reset(
            db,
            through_simulation_id,
            datetime.now(timezone.utc),
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Community bank reset failed exception_class=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Community Energy Bank data could not be reset.",
        ) from exc

    return {
        "reset": True,
        "deleted_credit_transactions": deleted_count,
        "through_simulation_id": through_simulation_id,
    }


@router.get("/config")
def get_config(db: Session = Depends(get_db)) -> dict:
    return current_config(db)


@router.post(
    "/config",
    dependencies=_protected_dependencies("config", 5, 20),
)
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


@router.post(
    "/model/train",
    dependencies=_protected_dependencies("model_train", 1, 2, window_seconds=3600),
)
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
