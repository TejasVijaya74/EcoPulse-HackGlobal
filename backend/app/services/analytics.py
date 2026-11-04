from app.energy.simulator import simulate
from app.schemas import SimulationParameters


def dashboard_from_result(result: dict) -> dict:
    metrics = result["metrics"]
    current = result["series"][0] if result["series"] else {}
    return {
        "simulated": True,
        "scenario": result["scenario_label"],
        "generated_at": result["created_at"],
        "current": current,
        "metrics": metrics,
        "series": result["series"],
        "baseline": result["baseline"],
    }


def create_dashboard_preview(config: dict) -> dict:
    params = SimulationParameters(
        scenario="normal",
        duration_hours=48,
        **{key: config[key] for key in SimulationParameters.model_fields if key in config},
    )
    return dashboard_from_result(simulate(params, config))

