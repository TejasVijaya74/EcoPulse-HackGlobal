import numpy as np
import pandas as pd


def generate_synthetic_data(
    days: int = 45,
    households: int = 60,
    solar_capacity_kw: float = 180.0,
    seed: int = 42,
    start: str = "2025-01-01",
) -> pd.DataFrame:
    """Create reproducible hourly weather, generation, and neighborhood load."""
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(start=start, periods=days * 24, freq="h")
    hour = timestamps.hour.to_numpy()
    day_of_year = timestamps.dayofyear.to_numpy()
    seasonal = np.sin(2 * np.pi * (day_of_year - 80) / 365)
    temperature = 18 + 9 * seasonal + 5 * np.sin(2 * np.pi * (hour - 8) / 24)
    temperature += rng.normal(0, 2.2, len(timestamps))
    daylight = np.maximum(0, np.sin(np.pi * (hour - 6) / 12))
    irradiance = daylight * np.clip(720 + 130 * seasonal + rng.normal(0, 100, len(timestamps)), 150, 1000)
    cloud_cover = np.clip(rng.beta(2.2, 4.5, len(timestamps)) + 0.08 * (1 - daylight), 0, 1)
    wind_speed = np.clip(rng.normal(12, 4, len(timestamps)), 0, 35)
    solar = solar_capacity_kw * (irradiance / 1000) * (1 - 0.78 * cloud_cover)
    solar = np.maximum(0, solar)

    morning_peak = 0.32 * np.exp(-0.5 * ((hour - 8) / 1.4) ** 2)
    evening_peak = 0.58 * np.exp(-0.5 * ((hour - 20) / 2.0) ** 2)
    overnight = np.where((hour >= 0) & (hour < 5), 0.08, 0.0)
    cooling = np.maximum(temperature - 24, 0) * 0.022
    per_home_kw = 0.42 + morning_peak + evening_peak + overnight + cooling
    demand = households * per_home_kw * np.clip(rng.normal(1.0, 0.075, len(timestamps)), 0.78, 1.25)
    demand = np.maximum(demand, 0.05)

    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "temperature": temperature,
            "solar_irradiance": irradiance,
            "cloud_cover": cloud_cover,
            "wind_speed": wind_speed,
            "solar_capacity_kw": solar_capacity_kw,
            "solar_generation": solar,
            "household_demand": demand,
        }
    )
    frame["net_balance"] = frame["solar_generation"] - frame["household_demand"]
    return frame
