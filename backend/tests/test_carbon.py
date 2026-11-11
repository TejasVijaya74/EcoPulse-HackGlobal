from app.config import GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH
from app.services.carbon import build_carbon_impact


def test_carbon_uses_grid_imports_only_and_compares_matched_baseline():
    metrics = {
        "grid_imports_kwh": 1000,
        "renewable_generated_kwh": 900,
        "energy_stored_kwh": 250,
        "energy_discharged_kwh": 180,
        "grid_exports_kwh": 120,
    }
    comparison = {
        "baseline": {"metrics": {"grid_imports_kwh": 1200}},
        "optimized": {"metrics": {"grid_imports_kwh": 1000}},
    }

    impact = build_carbon_impact(metrics, comparison, 10)

    expected_emissions = round(1000 * GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH, 2)
    expected_baseline = round(1200 * GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH, 2)
    assert impact["available"] is True
    assert impact["simulated_estimate"] is True
    assert impact["community"]["estimated_emissions_kg_co2"] == expected_emissions
    assert impact["per_household"]["estimated_emissions_kg_co2"] == round(expected_emissions / 10, 2)
    assert impact["baseline"]["estimated_emissions_kg_co2"] == expected_baseline
    assert impact["avoided_emissions_kg_co2"] == round(expected_baseline - expected_emissions, 2)
    assert impact["avoided_emissions_per_household_kg_co2"] == round(
        (expected_baseline - expected_emissions) / 10, 2
    )
    assert impact["grid_emissions_factor"]["units"] == "kg CO2/kWh"
    assert impact["grid_emissions_factor"]["source"]
    assert impact["grid_emissions_factor"]["reporting_year"]
    assert "not counted separately" in impact["method"]


def test_carbon_missing_grid_imports_reports_unavailable_without_inventing_zero():
    impact = build_carbon_impact(
        {"renewable_generated_kwh": 500, "energy_discharged_kwh": 100},
        {"baseline": {"metrics": {"grid_imports_kwh": 200}}},
        5,
    )

    assert impact["available"] is False
    assert impact["community"]["estimated_emissions_kg_co2"] is None
    assert impact["per_household"]["estimated_emissions_kg_co2"] is None
    assert impact["avoided_emissions_kg_co2"] is None
    assert impact["unavailable_reason"]


def test_carbon_omits_avoidance_without_comparison_and_household_rate_without_count():
    impact = build_carbon_impact({"grid_imports_kwh": 25}, None, None)

    assert impact["available"] is True
    assert impact["community"]["estimated_emissions_kg_co2"] is not None
    assert impact["per_household"]["estimated_emissions_kg_co2"] is None
    assert impact["baseline"]["estimated_emissions_kg_co2"] is None
    assert impact["avoided_emissions_kg_co2"] is None
    assert impact["avoidance_available"] is False


def test_carbon_rejects_negative_or_non_finite_imports():
    for imports in (-1, float("nan"), float("inf"), True, "10"):
        impact = build_carbon_impact({"grid_imports_kwh": imports}, None, 1)
        assert impact["available"] is False
        assert impact["community"]["estimated_emissions_kg_co2"] is None
