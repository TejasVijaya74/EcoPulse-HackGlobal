from datetime import datetime

import joblib
import numpy as np
import pandas as pd

from app.config import MODEL_DIR
from app.data.synthetic_data import generate_synthetic_data
from app.ml.train import FEATURES, build_feature_frame, train_models
from app.services.weather import get_hourly_weather, solar_generation_from_weather


def load_models() -> tuple[dict, dict]:
    paths = {"solar_generation": MODEL_DIR / "solar.joblib", "household_demand": MODEL_DIR / "demand.joblib"}
    if not all(path.exists() for path in paths.values()):
        training = train_models()
        models, metrics = training["models"], training["metrics"]
    else:
        models = {name: joblib.load(path) for name, path in paths.items()}
        metrics = {}
    for model in models.values():
        model.set_params(n_jobs=1)
    return models, metrics


def forecast(hours: int = 24, households: int = 60, solar_capacity_kw: float = 180.0) -> dict:
    models, _ = load_models()
    weather = get_hourly_weather(hours, solar_capacity_kw)
    historical = build_feature_frame(generate_synthetic_data(days=60, households=60, solar_capacity_kw=180))
    history = historical.tail(24).copy()
    start = datetime.fromisoformat(weather["hours"][0]["timestamp"])
    outputs = []
    for offset in range(hours):
        weather_hour = weather["hours"][offset]
        timestamp = datetime.fromisoformat(weather_hour["timestamp"])
        row = {
            "hour": timestamp.hour,
            "day_of_week": timestamp.weekday(),
            "month": timestamp.month,
            "temperature": weather_hour["temperature"],
            "cloud_cover": weather_hour["cloud_cover"],
            "solar_irradiance": weather_hour["solar_irradiance"],
            "wind_speed": weather_hour["wind_speed"],
            "solar_physics_estimate": solar_generation_from_weather(
                180.0, weather_hour["solar_irradiance"], weather_hour["cloud_cover"]
            ),
            "prev_solar": float(history["solar_generation"].iloc[-1]),
            "prev_demand": float(history["household_demand"].iloc[-1]),
            "solar_ma3": float(history["solar_generation"].tail(3).mean()),
            "demand_ma3": float(history["household_demand"].tail(3).mean()),
            "solar_lag24": float(history["solar_generation"].iloc[-24]) if len(history) >= 24 else float(history["solar_generation"].iloc[0]),
            "demand_lag24": float(history["household_demand"].iloc[-24]) if len(history) >= 24 else float(history["household_demand"].iloc[0]),
        }
        features = pd.DataFrame([row], columns=FEATURES)
        solar_reference = max(0.0, float(models["solar_generation"].predict(features)[0]))
        demand_reference = max(0.0, float(models["household_demand"].predict(features)[0]))
        solar = solar_reference * solar_capacity_kw / 180
        demand = demand_reference * households / 60
        outputs.append(
            {
                "timestamp": timestamp.isoformat(),
                "solar_generation_kw": round(solar, 2),
                "household_demand_kw": round(demand, 2),
                "net_energy_balance_kw": round(solar - demand, 2),
            }
        )
        history = pd.concat(
            [
                history,
                pd.DataFrame(
                    [
                        {
                            "timestamp": timestamp,
                            "solar_generation": solar_reference,
                            "household_demand": demand_reference,
                            "temperature": weather_hour["temperature"],
                            "cloud_cover": weather_hour["cloud_cover"],
                            "solar_irradiance": weather_hour["solar_irradiance"],
                            "wind_speed": weather_hour["wind_speed"],
                            "solar_capacity_kw": solar_capacity_kw,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        ).tail(24)
    # Uncertainty bands are approximate 12% of the recent signal, not formal prediction intervals.
    for record in outputs:
        solar_margin = max(2.0, record["solar_generation_kw"] * 0.12)
        demand_margin = max(2.0, record["household_demand_kw"] * 0.12)
        record["solar_uncertainty_kw"] = round(solar_margin, 2)
        record["demand_uncertainty_kw"] = round(demand_margin, 2)
        record["solar_lower_kw"] = round(max(0.0, record["solar_generation_kw"] - solar_margin), 2)
        record["solar_upper_kw"] = round(record["solar_generation_kw"] + solar_margin, 2)
        record["demand_lower_kw"] = round(max(0.0, record["household_demand_kw"] - demand_margin), 2)
        record["demand_upper_kw"] = round(record["household_demand_kw"] + demand_margin, 2)
    return {
        "forecast": outputs,
        "weather_source": weather["source"],
        "weather_label": weather["label"],
        "weather_fallback_reason": weather["fallback_reason"],
        "weather_attribution_url": weather["attribution_url"],
        "uncertainty_label": "Approximate +/-12% planning band; not a calibrated prediction interval.",
    }
