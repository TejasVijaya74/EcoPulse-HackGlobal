import numpy as np

from app.data.synthetic_data import generate_synthetic_data
from app.energy.optimizer import dispatch_interval
from app.energy.physics import FlywheelStorage, flywheel_energy_kwh
from app.energy.simulator import simulate
from app.schemas import SimulationParameters
from app.services.analytics import build_optimization_comparison, create_dashboard_preview
from app.services.community_bank import allocate_community_contribution


def test_synthetic_neighborhood_data_is_hourly_deterministic_and_nonnegative():
    first = generate_synthetic_data(days=30, seed=7)
    second = generate_synthetic_data(days=30, seed=7)
    assert len(first) == 30 * 24
    assert first.equals(second)
    assert (first["solar_generation"] >= 0).all()
    assert (first["household_demand"] > 0).all()
    assert np.allclose(first["net_balance"], first["solar_generation"] - first["household_demand"])
    assert (first.loc[first["timestamp"].dt.hour.isin([0, 2, 4, 20, 22]), "solar_generation"] == 0).all()
    hourly_demand = first.groupby(first["timestamp"].dt.hour)["household_demand"].mean()
    assert hourly_demand.loc[8] > hourly_demand.loc[3]
    assert hourly_demand.loc[20] > hourly_demand.loc[3]


def test_flywheel_energy_and_capacity_bounds():
    assert flywheel_energy_kwh(100, 120) == 0.2
    storage = FlywheelStorage(10, 9.9, max_charge_kw=20, max_discharge_kw=20)
    accepted, stored = storage.charge(5)
    assert accepted < 5
    assert np.isclose(stored, accepted * storage.charging_efficiency)
    assert storage.energy_kwh <= 10
    assert stored <= 0.1 + 1e-8
    output, removed = storage.discharge(100)
    assert np.isclose(removed, output / storage.discharging_efficiency)
    assert output <= 10 * storage.discharging_efficiency
    assert removed <= 10
    assert storage.energy_kwh >= 0
    leaky_storage = FlywheelStorage(10, 8, self_discharge_per_hour=0.05)
    loss = leaky_storage.apply_self_discharge(2)
    assert np.isclose(loss, 0.8)
    assert np.isclose(leaky_storage.energy_kwh, 7.2)


def test_dispatch_respects_grid_outage_and_energy_limits():
    storage = FlywheelStorage(12, 4)
    flow = dispatch_interval(1, 10, storage, grid_available=False)
    assert flow.grid_import_kwh == 0
    assert flow.discharged_kwh > 0
    assert 0 <= storage.energy_kwh <= storage.capacity_kwh
    surplus = dispatch_interval(30, 2, storage, grid_export_limit_kw=3)
    assert surplus.grid_export_kwh <= 3
    assert surplus.curtailed_kwh >= 0
    imports = dispatch_interval(
        0,
        20,
        FlywheelStorage(0, 0),
        grid_available=True,
        grid_import_limit_kw=3,
    )
    assert imports.grid_import_kwh == 3


def test_baseline_and_optimized_comparison_uses_identical_inputs_and_conserves_energy():
    config = {
        "households": 25,
        "solar_capacity_kw": 100.0,
        "storage_capacity_kwh": 40.0,
        "initial_storage_percent": 50.0,
        "grid_import_limit_kw": 100.0,
        "grid_export_limit_kw": 30.0,
        "cloud_cover": 0.3,
        "temperature_c": 22.0,
        "demand_multiplier": 1.0,
        "grid_available": True,
        "charging_efficiency": 0.92,
        "discharging_efficiency": 0.9,
        "self_discharge_per_hour": 0.001,
        "max_charge_kw": 20.0,
        "max_discharge_kw": 20.0,
        "credit_rate": 10.0,
        "random_seed": 12,
    }
    parameter_values = {
        key: value for key, value in config.items() if key in SimulationParameters.model_fields
    }
    parameters = SimulationParameters(
        scenario="normal", duration_hours=24, **parameter_values
    )
    baseline = simulate(parameters, config, dispatch_strategy="baseline")
    optimized = simulate(parameters, config)
    comparison = build_optimization_comparison(baseline, optimized)

    assert baseline["parameters"] == optimized["parameters"]
    assert comparison["shared_inputs"] == {
        "scenario": "normal",
        "duration_hours": 24,
        "random_seed": 12,
        "storage_capacity_kwh": 40.0,
        "initial_storage_kwh": 20.0,
        "identical": True,
    }
    assert baseline["metrics"]["initial_storage_kwh"] == optimized["metrics"]["initial_storage_kwh"]
    assert baseline["metrics"]["energy_stored_kwh"] == 0
    assert baseline["metrics"]["energy_discharged_kwh"] == 0
    assert optimized["metrics"]["energy_stored_kwh"] > 0
    assert optimized["metrics"]["energy_discharged_kwh"] > 0

    for run in (baseline, optimized):
        metrics = run["metrics"]
        source_energy = (
            metrics["renewable_generated_kwh"]
            + metrics["grid_imports_kwh"]
            + metrics["initial_storage_kwh"]
        )
        accounted_energy = (
            metrics["household_consumption_kwh"]
            - metrics["unserved_energy_kwh"]
            + metrics["grid_exports_kwh"]
            + metrics["curtailed_energy_kwh"]
            + metrics["storage_losses_kwh"]
            + metrics["ending_storage_kwh"]
        )
        assert abs(source_energy - accounted_energy) < 0.05
        assert abs(metrics["energy_balance_error_kwh"]) < 0.01

    assert comparison["changes"]["grid_import_reduction_kwh"] == round(
        baseline["metrics"]["grid_imports_kwh"] - optimized["metrics"]["grid_imports_kwh"], 2
    )
    assert comparison["changes"]["unserved_energy_reduction_kwh"] == round(
        baseline["metrics"]["unserved_energy_kwh"] - optimized["metrics"]["unserved_energy_kwh"], 2
    )


def test_comparison_rejects_runs_with_different_parameters():
    baseline = {"parameters": {"duration_hours": 24}, "metrics": {}}
    optimized = {"parameters": {"duration_hours": 48}, "metrics": {}}
    try:
        build_optimization_comparison(baseline, optimized)
    except ValueError as exc:
        assert "identical parameters" in str(exc)
    else:
        raise AssertionError("Mismatched run inputs must not be compared.")


def test_dashboard_preview_includes_real_matched_comparison():
    dashboard = create_dashboard_preview(
        {
            "households": 25,
            "solar_capacity_kw": 100.0,
            "storage_capacity_kwh": 40.0,
            "initial_storage_percent": 50.0,
            "grid_import_limit_kw": 100.0,
            "grid_export_limit_kw": 30.0,
            "cloud_cover": 0.3,
            "temperature_c": 22.0,
            "demand_multiplier": 1.0,
            "grid_available": True,
            "charging_efficiency": 0.92,
            "discharging_efficiency": 0.9,
            "self_discharge_per_hour": 0.001,
            "max_charge_kw": 20.0,
            "max_discharge_kw": 20.0,
            "credit_rate": 10.0,
            "random_seed": 12,
        }
    )

    comparison = dashboard["optimization_comparison"]
    assert comparison["shared_inputs"]["identical"] is True
    assert comparison["shared_inputs"]["duration_hours"] == 48
    assert comparison["baseline"]["metrics"]["storage_utilization_percent"] == 0
    assert comparison["optimized"]["metrics"]["storage_utilization_percent"] >= 0
    assert abs(comparison["baseline"]["metrics"]["energy_balance_error_kwh"]) < 0.01
    assert abs(comparison["optimized"]["metrics"]["energy_balance_error_kwh"]) < 0.01


def test_simulation_scenarios_obey_storage_and_grid_constraints():
    config = {
        "households": 25,
        "solar_capacity_kw": 100.0,
        "storage_capacity_kwh": 40.0,
        "initial_storage_percent": 50.0,
        "grid_import_limit_kw": 100.0,
        "grid_export_limit_kw": 30.0,
        "cloud_cover": 0.3,
        "temperature_c": 22.0,
        "demand_multiplier": 1.0,
        "grid_available": True,
        "charging_efficiency": 0.92,
        "discharging_efficiency": 0.9,
        "self_discharge_per_hour": 0.001,
        "max_charge_kw": 20.0,
        "max_discharge_kw": 20.0,
        "credit_rate": 10.0,
        "random_seed": 2,
    }

    def run(scenario, dispatch_strategy="optimized"):
        parameter_values = {key: value for key, value in config.items() if key in SimulationParameters.model_fields}
        parameters = SimulationParameters(scenario=scenario, duration_hours=24, **parameter_values)
        return simulate(parameters, config, dispatch_strategy=dispatch_strategy)

    scenarios = (
        "normal",
        "heatwave",
        "heavy_cloud",
        "high_demand",
        "grid_outage",
        "low_solar",
        "evening_peak",
        "solar_surplus",
        "storage_constraints",
    )
    optimized_runs = {scenario: run(scenario) for scenario in scenarios}
    baseline_runs = {scenario: run(scenario, "baseline") for scenario in scenarios}
    normal = optimized_runs["normal"]
    heatwave = optimized_runs["heatwave"]
    cloudy = optimized_runs["heavy_cloud"]
    high_demand = optimized_runs["high_demand"]
    low_solar = optimized_runs["low_solar"]
    outage = optimized_runs["grid_outage"]
    evening_peak = optimized_runs["evening_peak"]
    solar_surplus = optimized_runs["solar_surplus"]
    storage_constraints = optimized_runs["storage_constraints"]
    assert heatwave["metrics"]["household_consumption_kwh"] > normal["metrics"]["household_consumption_kwh"]
    assert high_demand["metrics"]["household_consumption_kwh"] > normal["metrics"]["household_consumption_kwh"]
    assert cloudy["metrics"]["renewable_generated_kwh"] < normal["metrics"]["renewable_generated_kwh"]
    assert low_solar["metrics"]["renewable_generated_kwh"] < normal["metrics"]["renewable_generated_kwh"]
    assert evening_peak["metrics"]["household_consumption_kwh"] > normal["metrics"]["household_consumption_kwh"]
    assert solar_surplus["metrics"]["renewable_generated_kwh"] > normal["metrics"]["renewable_generated_kwh"]
    assert storage_constraints["parameters"]["max_charge_kw"] == config["max_charge_kw"] * 0.5
    assert storage_constraints["parameters"]["max_discharge_kw"] == config["max_discharge_kw"] * 0.5
    assert outage["metrics"]["grid_imports_kwh"] == 0
    assert 0 <= outage["metrics"]["unserved_energy_kwh"] <= outage["metrics"]["household_consumption_kwh"]
    for result in (
        *optimized_runs.values(),
    ):
        baseline = baseline_runs[result["scenario"]]
        assert baseline["parameters"] == result["parameters"]
        assert baseline["dispatch_strategy"] == "baseline"
        assert result["dispatch_strategy"] == "optimized"
        assert [
            (point["solar_generation_kw"], point["household_demand_kw"])
            for point in baseline["series"]
        ] == [
            (point["solar_generation_kw"], point["household_demand_kw"])
            for point in result["series"]
        ]
        assert baseline["metrics"]["energy_stored_kwh"] == 0
        assert baseline["metrics"]["energy_discharged_kwh"] == 0
        for dispatch_result in (baseline, result):
            assert all(
                0 <= point["storage_level_kwh"] <= config["storage_capacity_kwh"]
                for point in dispatch_result["series"]
            )
            assert all(
                point["energy_stored_kwh"]
                <= dispatch_result["parameters"]["max_charge_kw"]
                * dispatch_result["parameters"]["charging_efficiency"]
                + 0.01
                and point["energy_discharged_kwh"]
                <= dispatch_result["parameters"]["max_discharge_kw"] + 0.01
                for point in dispatch_result["series"]
            )
            assert abs(dispatch_result["metrics"]["energy_balance_error_kwh"]) < 0.01
            assert dispatch_result["metrics"]["grid_imports_kwh"] <= (
                config["grid_import_limit_kw"] * 24
            )
            assert dispatch_result["metrics"]["grid_exports_kwh"] <= (
                config["grid_export_limit_kw"] * 24
            )
            if result["scenario"] == "grid_outage":
                assert dispatch_result["metrics"]["grid_imports_kwh"] == 0
            displayed_credit_estimate = round(
                dispatch_result["metrics"]["community_contribution_kwh"] * 10, 2
            )
            assert dispatch_result["metrics"]["community_credits"] == displayed_credit_estimate

    for dispatch_result in (*optimized_runs.values(), *baseline_runs.values()):
        assert 0 <= dispatch_result["metrics"]["unserved_energy_kwh"] <= (
            dispatch_result["metrics"]["household_consumption_kwh"]
        )


def test_grid_outage_with_no_local_supply_reports_all_demand_as_unserved():
    config = {
        "households": 2,
        "solar_capacity_kw": 0.0,
        "storage_capacity_kwh": 0.0,
        "initial_storage_percent": 0.0,
        "grid_import_limit_kw": 100.0,
        "grid_export_limit_kw": 10.0,
        "cloud_cover": 0.3,
        "temperature_c": 22.0,
        "demand_multiplier": 1.0,
        "grid_available": False,
        "charging_efficiency": 0.92,
        "discharging_efficiency": 0.9,
        "self_discharge_per_hour": 0.001,
        "max_charge_kw": 20.0,
        "max_discharge_kw": 20.0,
        "credit_rate": 10.0,
        "random_seed": 2,
    }
    parameters = SimulationParameters(
        scenario="grid_outage",
        duration_hours=24,
        **{key: value for key, value in config.items() if key in SimulationParameters.model_fields},
    )

    result = simulate(parameters, config)

    assert result["metrics"]["grid_imports_kwh"] == 0
    assert result["metrics"]["unserved_energy_kwh"] == result["metrics"]["household_consumption_kwh"]
    assert abs(result["metrics"]["energy_balance_error_kwh"]) < 0.01


def test_community_bank_allocation_conserves_energy_and_microcredits():
    allocations = allocate_community_contribution(10.01, 7.5, 3)

    assert len(allocations) == 3
    assert len({item["household_id"] for item in allocations}) == 3
    assert np.isclose(sum(item["energy_kwh"] for item in allocations), 10.01)
    assert np.isclose(sum(item["credits"] for item in allocations), 75.08)
    assert allocate_community_contribution(0, 10, 3) == []
