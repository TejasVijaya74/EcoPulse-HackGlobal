import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import desc, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import DEFAULT_CONFIG, GROQ_API_KEY, WEATHERAPI_DEFAULT_LOCATION
from app.database import get_db
from app.energy.simulator import simulate
from app.ml.predictor import forecast
from app.ml.train import train_models
from app.models import ConfigurationRecord, CreditTransaction, ModelTrainingRecord, SimulationRecord
from app.rate_limits import rate_limit
from app.security import (
    has_valid_api_token,
    public_demo_mode_enabled,
    require_api_token,
    require_public_demo_or_api_token,
)
from app.schemas import (
    AdvisorRequest,
    ConfigurationUpdate,
    DemoSimulationParameters,
    ResearchTopic,
    SimulationParameters,
)
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


def _demo_or_protected_dependencies(
    name: str,
    client_limit: int,
    global_limit: int,
    window_seconds: int = 60,
    *,
    public_client_limit: int | None = None,
    public_global_limit: int | None = None,
    public_window_seconds: int | None = None,
) -> list:
    return [
        Depends(require_public_demo_or_api_token),
        Depends(
            _conditional_rate_limit(
                name,
                client_limit,
                window_seconds,
                public_client_limit or client_limit,
                public_window_seconds or window_seconds,
            )
        ),
        Depends(
            _conditional_rate_limit(
                name,
                global_limit,
                window_seconds,
                public_global_limit or global_limit,
                public_window_seconds or window_seconds,
                scope="global",
            )
        ),
    ]


def _conditional_rate_limit(
    name: str,
    regular_limit: int,
    regular_window_seconds: int,
    public_limit: int,
    public_window_seconds: int,
    *,
    scope: str = "client",
):
    def enforce(request: Request, db: Session = Depends(get_db)) -> None:
        public_request = _is_anonymous_public_demo(request)
        limit = public_limit if public_request else regular_limit
        window_seconds = public_window_seconds if public_request else regular_window_seconds
        bucket_name = f"public_demo_{name}" if public_request else name
        rate_limit(
            bucket_name,
            limit,
            window_seconds,
            scope=scope,
        )(request, db)

    enforce.__name__ = f"conditional_rate_limit_{scope}_{name}"
    return enforce


def _is_anonymous_public_demo(request: Request) -> bool:
    return public_demo_mode_enabled() and not has_valid_api_token(request)


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


@router.get(
    "/demo/status",
    dependencies=[
        Depends(rate_limit("demo_status", 60, 60)),
        Depends(rate_limit("demo_status", 600, 60, scope="global")),
    ],
)
def demo_status(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"public_demo_mode": public_demo_mode_enabled()}


@router.get(
    "/demo/config",
    dependencies=_demo_or_protected_dependencies("config", 30, 120),
)
def demo_config() -> dict:
    public_fields = (
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
    )
    return {key: DEFAULT_CONFIG[key] for key in public_fields}


@router.get(
    "/health",
    dependencies=[Depends(require_api_token)],
)
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
    dependencies=_demo_or_protected_dependencies("dashboard", 30, 300),
)
def dashboard(request: Request, db: Session = Depends(get_db)) -> dict:
    public_preview = _is_anonymous_public_demo(request)
    config = DEFAULT_CONFIG.copy() if public_preview else current_config(db)
    latest = (
        None
        if public_preview
        else db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
    )
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
    dependencies=_demo_or_protected_dependencies("forecast", 20, 240),
)
def get_forecast(
    request: Request,
    hours: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(get_db),
) -> dict:
    config = DEFAULT_CONFIG.copy() if _is_anonymous_public_demo(request) else current_config(db)
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
    dependencies=_demo_or_protected_dependencies(
        "weather",
        20,
        100,
        public_client_limit=10,
        public_global_limit=120,
        public_window_seconds=3600,
    ),
)
def energy_intelligence_overview(
    request: Request,
    location: str | None = Query(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[\w][\w\s,.'()-]*$",
    ),
    db: Session = Depends(get_db),
) -> dict:
    config = DEFAULT_CONFIG.copy() if _is_anonymous_public_demo(request) else current_config(db)
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
    dependencies=_demo_or_protected_dependencies(
        "research",
        10,
        50,
        public_client_limit=6,
        public_global_limit=30,
        public_window_seconds=3600,
    ),
)
def energy_research(topic: ResearchTopic = Query(default="solar")) -> dict:
    try:
        return search_research(topic)
    except (ResearchNotConfigured, ResearchRateLimited, ResearchTimeout, ResearchUnavailable, ResearchInvalidResponse) as exc:
        raise _research_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def calculate_simulation(parameters: SimulationParameters, config: dict) -> dict:
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
    return result


@router.post(
    "/demo/simulate",
    dependencies=_demo_or_protected_dependencies("simulate", 5, 50, 3600),
)
def run_demo_simulation(parameters: DemoSimulationParameters) -> dict:
    result = calculate_simulation(parameters, DEFAULT_CONFIG.copy())
    result["created_at"] = datetime.now(timezone.utc).isoformat()
    result["simulated"] = True
    result["persisted"] = False
    return result


@router.post(
    "/simulate",
    dependencies=_protected_dependencies("simulate", 6, 30),
)
def run_simulation(parameters: SimulationParameters, db: Session = Depends(get_db)) -> dict:
    result = calculate_simulation(parameters, current_config(db))
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
    dependencies=_demo_or_protected_dependencies(
        "advisor",
        3,
        15,
        public_client_limit=2,
        public_global_limit=20,
        public_window_seconds=3600,
    ),
)
async def energy_advisor(request: Request, advisor_request: AdvisorRequest, db: Session = Depends(get_db)) -> dict:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="The Energy Advisor is not configured.")

    public_preview = _is_anonymous_public_demo(request)
    latest = (
        None
        if public_preview
        else db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
    )
    if latest:
        result = json.loads(latest.result_json)
        if "carbon_impact" not in result:
            result["carbon_impact"] = build_carbon_impact(
                result.get("metrics") or {},
                result.get("optimization_comparison"),
                (result.get("parameters") or {}).get("households"),
            )
    else:
        config = DEFAULT_CONFIG.copy() if public_preview else current_config(db)
        result = create_dashboard_preview(config)

    context = build_advisor_context(result)
    try:
        context["external_weather"] = await asyncio.to_thread(
            get_weatherapi_forecast,
            days=1,
        )
    except WeatherAPIError:
        context["external_weather"] = {"available": False, "reason": "WeatherAPI data is unavailable."}
    if advisor_request.research_topic and not public_preview:
        try:
            context["energy_research"] = await asyncio.to_thread(
                search_research,
                advisor_request.research_topic,
            )
        except (ResearchNotConfigured, ResearchRateLimited, ResearchTimeout, ResearchUnavailable, ResearchInvalidResponse):
            context["energy_research"] = {
                "available": False,
                "reason": "Energy research is unavailable.",
                "topic": advisor_request.research_topic,
            }

    try:
        answer = await ask_energy_advisor(advisor_request.question, context)
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


@router.get(
    "/simulation/history",
    dependencies=_protected_dependencies("simulation_history", 30, 120),
)
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


@router.get(
    "/simulation/{simulation_id}",
    dependencies=_protected_dependencies("simulation_detail", 60, 240),
)
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

    latest = db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
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


@router.get(
    "/config",
    dependencies=_protected_dependencies("config_read", 30, 120),
)
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
