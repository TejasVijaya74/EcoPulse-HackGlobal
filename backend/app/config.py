import math
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
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "").strip()
WEATHERAPI_BASE_URL = os.getenv(
    "WEATHERAPI_BASE_URL", "https://api.weatherapi.com/v1"
).strip().rstrip("/")
WEATHERAPI_DEFAULT_LOCATION = os.getenv("WEATHERAPI_DEFAULT_LOCATION", "New Delhi").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH = float(
    os.getenv("GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH", "0.716")
)
if not math.isfinite(GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH) or GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH < 0:
    raise ValueError("GRID_EMISSIONS_FACTOR_KG_CO2_PER_KWH must be a finite non-negative number.")
GRID_EMISSIONS_FACTOR_SOURCE = os.getenv(
    "GRID_EMISSIONS_FACTOR_SOURCE",
    "Central Electricity Authority (CEA), CO2 Baseline Database for the Indian Power Sector, Version 19.0",
).strip()
GRID_EMISSIONS_REPORTING_YEAR = os.getenv("GRID_EMISSIONS_REPORTING_YEAR", "2022-23").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_API_BASE_URL = os.getenv(
    "GROQ_API_BASE_URL", "https://api.groq.com/openai/v1"
).strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()

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
