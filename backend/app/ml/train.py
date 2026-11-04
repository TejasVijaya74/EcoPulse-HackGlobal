from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.config import MODEL_DIR
from app.data.synthetic_data import generate_synthetic_data

TRAINING_DATA_VERSION = 3
FEATURES = [
    "hour",
    "day_of_week",
    "month",
    "temperature",
    "cloud_cover",
    "solar_irradiance",
    "wind_speed",
    "solar_physics_estimate",
    "prev_solar",
    "prev_demand",
    "solar_ma3",
    "demand_ma3",
    "solar_lag24",
    "demand_lag24",
]
def build_feature_frame(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.copy()
    timestamp = pd.to_datetime(frame["timestamp"])
    frame["hour"] = timestamp.dt.hour
    frame["day_of_week"] = timestamp.dt.dayofweek
    frame["month"] = timestamp.dt.month
    solar_capacity = frame["solar_capacity_kw"] if "solar_capacity_kw" in frame else 180.0
    frame["solar_physics_estimate"] = np.maximum(
        0.0,
        solar_capacity
        * frame["solar_irradiance"]
        / 1000
        * (1 - 0.78 * np.clip(frame["cloud_cover"], 0, 1)),
    )
    frame["prev_solar"] = frame["solar_generation"].shift(1)
    frame["prev_demand"] = frame["household_demand"].shift(1)
    frame["solar_ma3"] = frame["solar_generation"].shift(1).rolling(3, min_periods=3).mean()
    frame["demand_ma3"] = frame["household_demand"].shift(1).rolling(3, min_periods=3).mean()
    frame["solar_lag24"] = frame["solar_generation"].shift(24)
    frame["demand_lag24"] = frame["household_demand"].shift(24)
    return frame.dropna(subset=FEATURES + ["solar_generation", "household_demand"]).reset_index(drop=True)


def _scores(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
    }


def train_models(data: pd.DataFrame | None = None) -> dict:
    data = data if data is not None else generate_synthetic_data(days=60)
    featured = build_feature_frame(data)
    if len(featured) < 48:
        raise ValueError("At least 48 hourly samples are required to train forecasting models.")
    split = max(24, int(len(featured) * 0.8))
    if split >= len(featured):
        split = len(featured) - 1
    train, test = featured.iloc[:split], featured.iloc[split:]
    metrics = {}
    models = {}
    for target, filename in (
        ("solar_generation", "solar.joblib"),
        ("household_demand", "demand.joblib"),
    ):
        model = RandomForestRegressor(
            n_estimators=160,
            max_depth=14,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1,
        )
        model.fit(train[FEATURES], train[target])
        predicted = np.maximum(0, model.predict(test[FEATURES]))
        baseline = np.maximum(0, test[target].shift(1).fillna(train[target].iloc[-1]).to_numpy())
        metrics[target] = {
            "model": _scores(test[target].to_numpy(), predicted),
            "baseline": _scores(test[target].to_numpy(), baseline),
        }
        models[target] = model
        joblib.dump(model, Path(MODEL_DIR) / filename)
    return {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "model_version": sklearn.__version__,
        "training_data_version": TRAINING_DATA_VERSION,
        "samples": len(featured),
        "metrics": metrics,
        "data": data,
        "models": models,
    }
