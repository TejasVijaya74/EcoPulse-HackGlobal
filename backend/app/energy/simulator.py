from datetime import datetime, timedelta, timezone

import numpy as np

from app.data.synthetic_data import generate_synthetic_data
from app.energy.optimizer import dispatch_interval
from app.energy.physics import FlywheelStorage
from app.schemas import SimulationParameters

SCENARIOS = {
    "normal": "Normal Conditions",
    "heatwave": "Heatwave",
    "heavy_cloud": "Heavy Cloud Cover",
    "high_demand": "High Demand",
    "grid_outage": "Grid Outage",
    "low_solar": "Low Solar Generation",
}


def simulate(parameters: SimulationParameters, config: dict) -> dict:
    overrides = parameters.model_dump(exclude_unset=True, exclude={"scenario", "duration_hours"})
    values = {**config, **overrides}
    scenario = parameters.scenario
    temperature_shift, demand_factor, solar_factor = 0.0, 1.0, 1.0
    if scenario == "heatwave":
        temperature_shift, demand_factor = 10.0, 1.28
    elif scenario == "heavy_cloud":
        values["cloud_cover"] = max(values["cloud_cover"], 0.88)
    elif scenario == "high_demand":
        demand_factor = 1.35
    elif scenario == "grid_outage":
        values["grid_available"] = False
    elif scenario == "low_solar":
        solar_factor = 0.42

    data = generate_synthetic_data(
        days=max(2, int(np.ceil(parameters.duration_hours / 24)) + 1),
        households=values["households"],
        solar_capacity_kw=values["solar_capacity_kw"],
        seed=values["random_seed"],
        start="2025-03-01",
    ).iloc[: parameters.duration_hours].copy()
    rng = np.random.default_rng(values["random_seed"] + 17)
    cloud = np.clip(values["cloud_cover"] + rng.normal(0, 0.06, len(data)), 0, 1)
    irradiance = data["solar_irradiance"].to_numpy()
    solar = values["solar_capacity_kw"] * (irradiance / 1000) * (1 - 0.78 * cloud) * solar_factor
    temperatures = data["temperature"].to_numpy() + temperature_shift + (values["temperature_c"] - 22) * 0.35
    cooling_factor = 1 + np.maximum(temperatures - 25, 0) * 0.012
    demand = data["household_demand"].to_numpy() * values["demand_multiplier"] * demand_factor * cooling_factor

    storage = FlywheelStorage(
        capacity_kwh=values["storage_capacity_kwh"],
        energy_kwh=values["storage_capacity_kwh"] * values["initial_storage_percent"] / 100,
        charging_efficiency=values["charging_efficiency"],
        discharging_efficiency=values["discharging_efficiency"],
        self_discharge_per_hour=values["self_discharge_per_hour"],
        max_charge_kw=values["max_charge_kw"],
        max_discharge_kw=values["max_discharge_kw"],
    )
    initial_storage_kwh = storage.energy_kwh
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    series = []
    totals = {
        "renewable_generated_kwh": 0.0,
        "household_consumption_kwh": 0.0,
        "energy_stored_kwh": 0.0,
        "energy_discharged_kwh": 0.0,
        "grid_imports_kwh": 0.0,
        "grid_exports_kwh": 0.0,
        "curtailed_energy_kwh": 0.0,
        "storage_losses_kwh": 0.0,
        "unserved_energy_kwh": 0.0,
        "community_credits": 0.0,
        "community_contribution_kwh": 0.0,
    }
    baseline_imports = baseline_exports = baseline_curtailment = baseline_unserved = optimized_unserved = 0.0
    credit_events = []
    for index, (solar_kw, demand_kw) in enumerate(zip(solar, demand)):
        flow = dispatch_interval(
            float(solar_kw),
            float(demand_kw),
            storage,
            grid_available=values["grid_available"],
            grid_import_limit_kw=values["grid_import_limit_kw"],
            grid_export_limit_kw=values["grid_export_limit_kw"],
        )
        baseline_net = float(solar_kw - demand_kw)
        if baseline_net < 0:
            baseline_imports += min(-baseline_net, values["grid_import_limit_kw"]) if values["grid_available"] else 0
            baseline_unserved += max(0.0, -baseline_net - (values["grid_import_limit_kw"] if values["grid_available"] else 0))
        else:
            baseline_exports += min(baseline_net, values["grid_export_limit_kw"]) if values["grid_available"] else 0
            baseline_curtailment += max(0.0, baseline_net - (values["grid_export_limit_kw"] if values["grid_available"] else 0))
        totals["renewable_generated_kwh"] += flow.solar_kwh
        totals["household_consumption_kwh"] += flow.demand_kwh
        totals["energy_stored_kwh"] += flow.stored_kwh
        totals["energy_discharged_kwh"] += flow.discharged_kwh
        totals["grid_imports_kwh"] += flow.grid_import_kwh
        totals["grid_exports_kwh"] += flow.grid_export_kwh
        totals["curtailed_energy_kwh"] += flow.curtailed_kwh
        totals["storage_losses_kwh"] += flow.storage_loss_kwh
        totals["community_contribution_kwh"] += flow.credits_energy_kwh
        totals["community_credits"] += flow.credits_energy_kwh * values["credit_rate"]
        if flow.credits_energy_kwh > 0:
            credit_events.append(
                {"timestamp": (start + timedelta(hours=index)).isoformat(), "energy_kwh": flow.credits_energy_kwh}
            )
        served_by_local = min(flow.demand_kwh, flow.solar_kwh + flow.discharged_kwh)
        served_by_grid = flow.grid_import_kwh
        optimized_unserved += max(0, flow.demand_kwh - served_by_local - served_by_grid)
        totals["unserved_energy_kwh"] = optimized_unserved
        series.append(
            {
                "timestamp": (start + timedelta(hours=index)).isoformat(),
                "solar_generation_kw": round(flow.solar_kwh, 2),
                "household_demand_kw": round(flow.demand_kwh, 2),
                "net_balance_kw": round(flow.solar_kwh - flow.demand_kwh, 2),
                "storage_level_kwh": round(storage.energy_kwh, 2),
                "storage_soc_percent": round(storage.state_of_charge * 100, 1),
                "grid_import_kwh": round(flow.grid_import_kwh, 2),
                "grid_export_kwh": round(flow.grid_export_kwh, 2),
                "curtailed_kwh": round(flow.curtailed_kwh, 2),
                "credits_generated": round(flow.credits_energy_kwh * values["credit_rate"], 2),
                "operating_state": flow.state,
            }
        )
    generated = totals["renewable_generated_kwh"]
    consumption = totals["household_consumption_kwh"]
    totals["renewable_utilization_percent"] = (
        100 * (generated - totals["curtailed_energy_kwh"]) / generated if generated else 0.0
    )
    totals["storage_utilization_percent"] = (
        100 * totals["energy_discharged_kwh"] / (values["storage_capacity_kwh"] * parameters.duration_hours)
        if values["storage_capacity_kwh"]
        else 0.0
    )
    totals["grid_dependency_percent"] = 100 * totals["grid_imports_kwh"] / consumption if consumption else 0.0
    totals["unserved_energy_kwh"] = optimized_unserved
    totals["grid_outage_served_percent"] = 100 * (1 - optimized_unserved / consumption) if consumption else 100.0
    totals["ending_storage_kwh"] = storage.energy_kwh
    totals["energy_balance_error_kwh"] = (
        generated
        + totals["grid_imports_kwh"]
        + initial_storage_kwh
        - (
            consumption
            - optimized_unserved
            + totals["grid_exports_kwh"]
            + totals["curtailed_energy_kwh"]
            + totals["storage_losses_kwh"]
            + storage.energy_kwh
        )
    )
    totals["community_contribution_kwh"] = round(totals["community_contribution_kwh"], 2)
    totals["community_credits"] = round(
        totals["community_contribution_kwh"] * values["credit_rate"], 2
    )
    totals = {key: round(float(value), 2) for key, value in totals.items()}
    return {
        "scenario": scenario,
        "scenario_label": SCENARIOS[scenario],
        "simulated": True,
        "assumptions": {
            "model": "Abstract flywheel-based storage; simulated values only, not a deployed installation.",
            "interval_hours": 1,
            "charging_efficiency": values["charging_efficiency"],
            "discharging_efficiency": values["discharging_efficiency"],
            "self_discharge_per_hour": values["self_discharge_per_hour"],
        },
        "parameters": values | {"scenario": scenario, "duration_hours": parameters.duration_hours},
        "metrics": totals,
        "baseline": {
            "grid_imports_kwh": round(baseline_imports, 2),
            "grid_exports_kwh": round(baseline_exports, 2),
            "curtailed_energy_kwh": round(baseline_curtailment, 2),
            "unserved_energy_kwh": round(baseline_unserved, 2),
            "storage_capacity_kwh": 0,
        },
        "series": series,
        "credit_events": credit_events,
        "created_at": start.isoformat(),
    }
