import math
from typing import Any

from app.config import (
    GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH,
    GRID_EMISSIONS_FACTOR_SOURCE,
    GRID_EMISSIONS_REPORTING_YEAR,
)


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _emissions(imports_kwh: float) -> float:
    return round(imports_kwh * GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH, 2)


def build_carbon_impact(
    metrics: dict,
    optimization_comparison: dict | None,
    household_count: int | None,
) -> dict:
    """Estimate operational CO2 from grid imports only; storage flows are not added."""
    factor = GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH
    imports = _nonnegative_number(metrics.get("grid_imports_kwh"))
    households = (
        household_count
        if isinstance(household_count, int) and not isinstance(household_count, bool) and household_count > 0
        else None
    )
    estimate = _emissions(imports) if imports is not None else None
    per_household = round(estimate / households, 2) if estimate is not None and households else None

    baseline_metrics = (
        optimization_comparison.get("baseline", {}).get("metrics")
        if isinstance(optimization_comparison, dict)
        else None
    )
    baseline_imports = (
        _nonnegative_number(baseline_metrics.get("grid_imports_kwh"))
        if isinstance(baseline_metrics, dict)
        else None
    )
    baseline_emissions = _emissions(baseline_imports) if baseline_imports is not None else None
    avoided_emissions = (
        round(baseline_emissions - estimate, 2)
        if baseline_emissions is not None and estimate is not None
        else None
    )
    avoided_per_household = (
        round(avoided_emissions / households, 2)
        if avoided_emissions is not None and households
        else None
    )

    available = imports is not None
    return {
        "simulated_estimate": True,
        "label": "Simulated estimate; not measured emissions.",
        "method": "Grid-import emissions only; renewable generation and storage flows are not counted separately.",
        "grid_emissions_factor": {
            "value": factor,
            "units": "kg CO2/kWh",
            "source": GRID_EMISSIONS_FACTOR_SOURCE,
            "reporting_year": GRID_EMISSIONS_REPORTING_YEAR,
        },
        "community": {
            "grid_imports_kwh": imports,
            "estimated_emissions_kg_co2": estimate,
            "household_count": households,
        },
        "per_household": {"estimated_emissions_kg_co2": per_household},
        "baseline": {
            "grid_imports_kwh": baseline_imports,
            "estimated_emissions_kg_co2": baseline_emissions,
            "per_household_kg_co2": (
                round(baseline_emissions / households, 2)
                if baseline_emissions is not None and households
                else None
            ),
        },
        "avoided_emissions_kg_co2": avoided_emissions,
        "avoided_emissions_per_household_kg_co2": avoided_per_household,
        "available": available,
        "unavailable_reason": None if available else "Grid-import energy is unavailable or invalid.",
        "avoidance_available": baseline_emissions is not None and estimate is not None,
    }
