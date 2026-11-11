from app.energy.simulator import simulate
from app.schemas import SimulationParameters
from app.services.carbon import build_carbon_impact

COMPARISON_METRICS = (
    "renewable_generated_kwh",
    "household_consumption_kwh",
    "initial_storage_kwh",
    "energy_stored_kwh",
    "energy_discharged_kwh",
    "grid_imports_kwh",
    "grid_exports_kwh",
    "curtailed_energy_kwh",
    "storage_losses_kwh",
    "ending_storage_kwh",
    "storage_utilization_percent",
    "renewable_utilization_percent",
    "grid_dependency_percent",
    "unserved_energy_kwh",
    "energy_balance_error_kwh",
)


def build_optimization_comparison(baseline: dict, optimized: dict) -> dict:
    baseline_parameters = baseline["parameters"]
    optimized_parameters = optimized["parameters"]
    if baseline_parameters != optimized_parameters:
        raise ValueError("Baseline and optimized runs must use identical parameters.")

    baseline_metrics = baseline["metrics"]
    optimized_metrics = optimized["metrics"]
    for metric in ("renewable_generated_kwh", "household_consumption_kwh"):
        if baseline_metrics[metric] != optimized_metrics[metric]:
            raise ValueError(f"Baseline and optimized runs must have identical {metric}.")

    baseline_values = {key: baseline_metrics[key] for key in COMPARISON_METRICS}
    optimized_values = {key: optimized_metrics[key] for key in COMPARISON_METRICS}
    initial_storage_kwh = (
        optimized_parameters["storage_capacity_kwh"]
        * optimized_parameters["initial_storage_percent"]
        / 100
    )
    return {
        "shared_inputs": {
            "scenario": optimized_parameters["scenario"],
            "duration_hours": optimized_parameters["duration_hours"],
            "random_seed": optimized_parameters["random_seed"],
            "storage_capacity_kwh": optimized_parameters["storage_capacity_kwh"],
            "initial_storage_kwh": round(initial_storage_kwh, 2),
            "identical": True,
        },
        "baseline": {"dispatch_strategy": "baseline", "metrics": baseline_values},
        "optimized": {"dispatch_strategy": "optimized", "metrics": optimized_values},
        "changes": {
            "grid_import_reduction_kwh": round(
                baseline_metrics["grid_imports_kwh"] - optimized_metrics["grid_imports_kwh"], 2
            ),
            "grid_export_change_kwh": round(
                optimized_metrics["grid_exports_kwh"] - baseline_metrics["grid_exports_kwh"], 2
            ),
            "renewable_utilization_change_percentage_points": round(
                optimized_metrics["renewable_utilization_percent"]
                - baseline_metrics["renewable_utilization_percent"],
                2,
            ),
            "grid_dependency_change_percentage_points": round(
                optimized_metrics["grid_dependency_percent"]
                - baseline_metrics["grid_dependency_percent"],
                2,
            ),
            "energy_stored_change_kwh": round(
                optimized_metrics["energy_stored_kwh"] - baseline_metrics["energy_stored_kwh"], 2
            ),
            "energy_discharged_change_kwh": round(
                optimized_metrics["energy_discharged_kwh"]
                - baseline_metrics["energy_discharged_kwh"],
                2,
            ),
            "unserved_energy_reduction_kwh": round(
                baseline_metrics["unserved_energy_kwh"] - optimized_metrics["unserved_energy_kwh"], 2
            ),
            "storage_losses_change_kwh": round(
                optimized_metrics["storage_losses_kwh"] - baseline_metrics["storage_losses_kwh"], 2
            ),
            "ending_storage_change_kwh": round(
                optimized_metrics["ending_storage_kwh"] - baseline_metrics["ending_storage_kwh"], 2
            ),
        },
    }


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
        "optimization_comparison": result.get("optimization_comparison"),
        "carbon_impact": result.get("carbon_impact")
        or build_carbon_impact(
            metrics,
            result.get("optimization_comparison"),
            (result.get("parameters") or {}).get("households"),
        ),
    }


def create_dashboard_preview(config: dict) -> dict:
    params = SimulationParameters(
        scenario="normal",
        duration_hours=48,
        **{key: config[key] for key in SimulationParameters.model_fields if key in config},
    )
    result = simulate(params, config)
    baseline = simulate(params, config, dispatch_strategy="baseline")
    result["optimization_comparison"] = build_optimization_comparison(baseline, result)
    result["carbon_impact"] = build_carbon_impact(
        result["metrics"], result["optimization_comparison"], params.households
    )
    return dashboard_from_result(result)
