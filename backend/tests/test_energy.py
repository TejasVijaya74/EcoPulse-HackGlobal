import numpy as np

from app.data.synthetic_data import generate_synthetic_data
from app.energy.optimizer import dispatch_interval
from app.energy.physics import FlywheelStorage, flywheel_energy_kwh
from app.energy.simulator import simulate
from app.schemas import SimulationParameters


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

    def run(scenario):
        parameter_values = {key: value for key, value in config.items() if key in SimulationParameters.model_fields}
        parameters = SimulationParameters(scenario=scenario, duration_hours=24, **parameter_values)
        return simulate(parameters, config)

    normal = run("normal")
    heatwave = run("heatwave")
    cloudy = run("heavy_cloud")
    high_demand = run("high_demand")
    low_solar = run("low_solar")
    outage = run("grid_outage")
    assert heatwave["metrics"]["household_consumption_kwh"] > normal["metrics"]["household_consumption_kwh"]
    assert high_demand["metrics"]["household_consumption_kwh"] > normal["metrics"]["household_consumption_kwh"]
    assert cloudy["metrics"]["renewable_generated_kwh"] < normal["metrics"]["renewable_generated_kwh"]
    assert low_solar["metrics"]["renewable_generated_kwh"] < normal["metrics"]["renewable_generated_kwh"]
    assert outage["metrics"]["grid_imports_kwh"] == 0
    assert 0 <= outage["metrics"]["unserved_energy_kwh"] <= outage["metrics"]["household_consumption_kwh"]
    for result in (normal, heatwave, cloudy, high_demand, low_solar, outage):
        assert all(
            0 <= point["storage_level_kwh"] <= config["storage_capacity_kwh"]
            for point in result["series"]
        )
        assert abs(result["metrics"]["energy_balance_error_kwh"]) < 0.01
        displayed_credit_estimate = round(result["metrics"]["community_contribution_kwh"] * 10, 2)
        assert result["metrics"]["community_credits"] == displayed_credit_estimate
