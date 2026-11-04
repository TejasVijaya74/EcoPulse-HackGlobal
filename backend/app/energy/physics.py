from dataclasses import dataclass


def flywheel_energy_kwh(moment_of_inertia_kg_m2: float, angular_velocity_rad_s: float) -> float:
    """Return ideal rotational kinetic energy converted from joules to kWh."""
    if moment_of_inertia_kg_m2 < 0 or angular_velocity_rad_s < 0:
        raise ValueError("Moment of inertia and angular velocity must be non-negative.")
    return 0.5 * moment_of_inertia_kg_m2 * angular_velocity_rad_s**2 / 3_600_000


@dataclass
class FlywheelStorage:
    capacity_kwh: float
    energy_kwh: float
    charging_efficiency: float = 0.92
    discharging_efficiency: float = 0.90
    self_discharge_per_hour: float = 0.001
    max_charge_kw: float = 100.0
    max_discharge_kw: float = 100.0

    def __post_init__(self) -> None:
        if self.capacity_kwh < 0:
            raise ValueError("Storage capacity must be non-negative.")
        if not 0 < self.charging_efficiency <= 1 or not 0 < self.discharging_efficiency <= 1:
            raise ValueError("Storage efficiencies must be in the range (0, 1].")
        if not 0 <= self.self_discharge_per_hour <= 1:
            raise ValueError("Self-discharge must be in the range [0, 1] per hour.")
        if self.max_charge_kw < 0 or self.max_discharge_kw < 0:
            raise ValueError("Storage power limits must be non-negative.")
        self.energy_kwh = min(max(self.energy_kwh, 0), self.capacity_kwh)

    @property
    def state_of_charge(self) -> float:
        return self.energy_kwh / self.capacity_kwh if self.capacity_kwh else 0.0

    def apply_self_discharge(self, hours: float) -> float:
        if hours < 0:
            raise ValueError("Elapsed time must be non-negative.")
        lost = self.energy_kwh * min(1.0, self.self_discharge_per_hour * hours)
        self.energy_kwh = max(0.0, self.energy_kwh - lost)
        return lost

    def charge(self, available_input_kwh: float, hours: float = 1.0) -> tuple[float, float]:
        if hours < 0:
            raise ValueError("Elapsed time must be non-negative.")
        accepted = min(
            max(0.0, available_input_kwh),
            self.max_charge_kw * hours,
            max(0.0, self.capacity_kwh - self.energy_kwh) / self.charging_efficiency,
        )
        stored = accepted * self.charging_efficiency
        self.energy_kwh = min(self.capacity_kwh, self.energy_kwh + stored)
        return accepted, stored

    def discharge(self, requested_output_kwh: float, hours: float = 1.0) -> tuple[float, float]:
        if hours < 0:
            raise ValueError("Elapsed time must be non-negative.")
        output = min(
            max(0.0, requested_output_kwh),
            self.max_discharge_kw * hours,
            self.energy_kwh * self.discharging_efficiency,
        )
        removed = output / self.discharging_efficiency
        self.energy_kwh = max(0.0, self.energy_kwh - removed)
        return output, removed
