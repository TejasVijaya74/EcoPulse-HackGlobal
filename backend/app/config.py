import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
MODEL_DIR = APP_DIR / "ml" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'ecopulse.db'}")
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
CORS_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        f"{FRONTEND_ORIGIN},http://127.0.0.1:5173,https://ecopulse-frontend-p55z.onrender.com",
    ).split(",")
    if origin.strip()
)
WEATHER_LATITUDE = os.getenv("WEATHER_LATITUDE", "").strip()
WEATHER_LONGITUDE = os.getenv("WEATHER_LONGITUDE", "").strip()
WEATHER_TIMEZONE = os.getenv("WEATHER_TIMEZONE", "UTC").strip() or "UTC"

DEFAULT_CONFIG = {
    "households": 60,
    "solar_capacity_kw": 180.0,
    "storage_capacity_kwh": 320.0,
    "initial_storage_percent": 55.0,
    "grid_import_limit_kw": 250.0,
    "grid_export_limit_kw": 120.0,
    "cloud_cover": 0.35,
    "temperature_c": 22.0,
    "demand_multiplier": 1.0,
    "grid_available": True,
    "charging_efficiency": 0.92,
    "discharging_efficiency": 0.90,
    "self_discharge_per_hour": 0.001,
    "max_charge_kw": 100.0,
    "max_discharge_kw": 100.0,
    "credit_rate": 10.0,
    "random_seed": RANDOM_SEED,
}
