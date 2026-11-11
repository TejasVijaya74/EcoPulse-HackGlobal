from statistics import fmean


def build_weather_insights(weather: dict, config: dict) -> dict:
    """Provide relative weather adjustments without synthesizing irradiance or kWh."""
    hours = weather.get("hourly") or []
    next_day = hours[:24]
    if not next_day:
        return {
            "available": False,
            "reason": "Hourly weather forecast is unavailable.",
            "solar_method": "No solar irradiance or absolute generation is inferred from cloud cover.",
        }

    cloud_values = [hour["cloud_cover_percent"] / 100 for hour in next_day]
    temperatures = [hour["temperature_c"] for hour in next_day]
    rain_chances = [hour["chance_of_rain_percent"] for hour in next_day]
    average_cloud = fmean(cloud_values)
    baseline_cloud = min(1.0, max(0.0, float(config["cloud_cover"])))
    cloud_factor = (1 - 0.78 * average_cloud) / (1 - 0.78 * baseline_cloud)
    solar_change_percent = round((cloud_factor - 1) * 100, 1)

    baseline_temperature = float(config["temperature_c"])
    baseline_cooling = 1 + max(baseline_temperature - 25, 0) * 0.012
    forecast_cooling = fmean(1 + max(value - 25, 0) * 0.012 for value in temperatures)
    demand_change_percent = round((forecast_cooling / baseline_cooling - 1) * 100, 1)
    maximum_rain_chance = max(rain_chances, default=0.0)

    if solar_change_percent <= -10:
        solar_signal = "Potential solar shortfall risk relative to the configured cloud assumption."
    elif solar_change_percent >= 10:
        solar_signal = "Potential solar surplus opportunity relative to the configured cloud assumption."
    else:
        solar_signal = "Cloud-cover signal is near the configured solar-planning assumption."

    recommendations = []
    if solar_change_percent <= -10:
        recommendations.append(
            "Consider preserving available virtual storage before the cloudier forecast period."
        )
    if demand_change_percent >= 5:
        recommendations.append(
            "Warmer forecast conditions raise the simulator's temperature-related cooling-demand estimate."
        )
    if maximum_rain_chance >= 60:
        recommendations.append(
            "Elevated rain probability may indicate weather disruption; monitor updated forecasts."
        )
    if not recommendations:
        recommendations.append(
            "No strong weather-driven storage preparation signal was identified in the next 24 hours."
        )

    return {
        "available": True,
        "source": "WeatherAPI.com weather fields with EcoPulse relative adjustment assumptions",
        "solar_irradiance_available": False,
        "solar_method": (
            "Relative cloud-cover adjustment only: (1 - 0.78 × forecast cloud fraction) / "
            "(1 - 0.78 × configured cloud fraction). This is a planning signal, not irradiance, "
            "absolute solar generation, or dispatch."
        ),
        "average_cloud_cover_next_24h_percent": round(average_cloud * 100, 1),
        "configured_cloud_cover_percent": round(baseline_cloud * 100, 1),
        "relative_solar_potential_change_percent": solar_change_percent,
        "solar_signal": solar_signal,
        "forecast_temperature_average_c": round(fmean(temperatures), 1),
        "configured_temperature_c": round(baseline_temperature, 1),
        "estimated_temperature_related_demand_adjustment_percent": demand_change_percent,
        "maximum_rain_probability_next_24h_percent": round(maximum_rain_chance, 1),
        "recommendations": recommendations,
    }
