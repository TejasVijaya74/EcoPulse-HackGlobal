from dataclasses import dataclass

from app.energy.physics import FlywheelStorage


@dataclass
class DispatchResult:
    solar_kwh: float
    demand_kwh: float
    charge_input_kwh: float
    stored_kwh: float
    discharged_kwh: float
    removed_from_storage_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    curtailed_kwh: float
    storage_loss_kwh: float
    credits_energy_kwh: float
    state: str


def dispatch_interval(
    solar_kwh: float,
    demand_kwh: float,
    storage: FlywheelStorage,
    *,
    hours: float = 1.0,
    grid_available: bool = True,
    grid_import_limit_kw: float = 250.0,
    grid_export_limit_kw: float = 120.0,
    storage_enabled: bool = True,
) -> DispatchResult:
    """Route energy deterministically; all flow values are interval kWh."""
    storage_loss = storage.apply_self_discharge(hours)
    solar, demand = max(0.0, solar_kwh), max(0.0, demand_kwh)
    charge_input = stored = discharged = removed = grid_import = grid_export = curtailed = 0.0
    if solar >= demand:
        surplus = solar - demand
        if storage_enabled:
            charge_input, stored = storage.charge(surplus, hours)
        remainder = max(0.0, surplus - charge_input)
        grid_export = min(remainder, grid_export_limit_kw * hours) if grid_available else 0.0
        curtailed = max(0.0, remainder - grid_export)
        credits_energy = stored + grid_export
        state = "Charging" if charge_input > 0 else ("Exporting" if grid_export > 0 else "Surplus")
    else:
        deficit = demand - solar
        if storage_enabled:
            discharged, removed = storage.discharge(deficit, hours)
        remaining = max(0.0, deficit - discharged)
        grid_import = min(remaining, grid_import_limit_kw * hours) if grid_available else 0.0
        curtailed = 0.0
        credits_energy = 0.0
        state = "Discharging" if discharged > 0 else ("Grid import" if grid_import > 0 else "Unserved demand")
    return DispatchResult(
        solar,
        demand,
        charge_input,
        stored,
        discharged,
        removed,
        grid_import,
        grid_export,
        curtailed,
        storage_loss + max(0.0, charge_input - stored) + max(0.0, removed - discharged),
        credits_energy,
        state,
    )
