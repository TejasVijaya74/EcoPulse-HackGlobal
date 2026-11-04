import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPException as HTTPClientError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from app.config import RANDOM_SEED, WEATHER_LATITUDE, WEATHER_LONGITUDE, WEATHER_TIMEZONE
from app.data.synthetic_data import generate_synthetic_data

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ATTRIBUTION_URL = "https://open-meteo.com/"
REQUEST_TIMEOUT_SECONDS = 5
CACHE_TTL_SECONDS = 1800
FAILURE_CACHE_TTL_SECONDS = 60

_cache: dict[tuple[str, str, str, int], tuple[float, dict | None, str | None]] = {}
_cache_lock = threading.Lock()


def _configured_coordinates() -> tuple[float, float] | None:
    if not WEATHER_LATITUDE or not WEATHER_LONGITUDE:
        return None
    try:
        latitude, longitude = float(WEATHER_LATITUDE), float(WEATHER_LONGITUDE)
    except ValueError:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def solar_generation_from_weather(
    solar_capacity_kw: float,
    shortwave_radiation_w_m2: float,
    cloud_cover_fraction: float,
) -> float:
    """Estimate solar power using the same capacity/irradiance/cloud model as synthetic data."""
    return max(
        0.0,
        solar_capacity_kw
        * max(0.0, shortwave_radiation_w_m2)
        / 1000
        * (1 - 0.78 * min(1.0, max(0.0, cloud_cover_fraction))),
    )


def _timezone() -> ZoneInfo:
    try:
        return ZoneInfo(WEATHER_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def forecast_start() -> datetime:
    return datetime.now(_timezone()).replace(minute=0, second=0, microsecond=0)


def _cache_key(latitude: float, longitude: float, timezone_name: str, forecast_days: int):
    return (f"{latitude:.5f}", f"{longitude:.5f}", timezone_name, forecast_days)


def _fetch_open_meteo(latitude: float, longitude: float, forecast_days: int) -> dict:
    params = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,cloud_cover,shortwave_radiation,wind_speed_10m",
            "forecast_days": forecast_days,
            "timezone": WEATHER_TIMEZONE,
        }
    )
    with urlopen(f"{OPEN_METEO_URL}?{params}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read())
    if not isinstance(body, dict):
        raise ValueError("Open-Meteo returned an invalid response document.")
    hourly = body.get("hourly", {})
    if not isinstance(hourly, dict):
        raise ValueError("Open-Meteo response has an invalid hourly section.")
    required = ("time", "temperature_2m", "cloud_cover", "shortwave_radiation", "wind_speed_10m")
    if any(not isinstance(hourly.get(key), list) for key in required):
        raise ValueError("Open-Meteo response is missing hourly weather fields.")
    lengths = {len(hourly[key]) for key in required}
    if len(lengths) != 1 or not lengths or not next(iter(lengths)):
        raise ValueError("Open-Meteo returned incomplete hourly weather data.")
    records = []
    for values in zip(*(hourly[key] for key in required)):
        stamp, temperature, cloud_percent, irradiance, wind = values
        numeric_values = (temperature, cloud_percent, irradiance, wind)
        if not isinstance(stamp, str) or any(
            not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric_values
        ):
            raise ValueError("Open-Meteo returned invalid hourly weather values.")
        try:
            datetime.fromisoformat(stamp)
        except ValueError as exc:
            raise ValueError("Open-Meteo returned an invalid hourly timestamp.") from exc
        if not 0 <= cloud_percent <= 100:
            raise ValueError("Open-Meteo returned cloud cover outside 0-100%.")
        records.append(
            {
                "timestamp": stamp,
                "temperature": float(temperature),
                "cloud_cover": float(cloud_percent) / 100,
                "solar_irradiance": max(0.0, float(irradiance)),
                "wind_speed": max(0.0, float(wind)),
            }
        )
    return {"hours": records}


def _weather_response(latitude: float, longitude: float, forecast_days: int) -> tuple[dict | None, str | None]:
    key = _cache_key(latitude, longitude, WEATHER_TIMEZONE, forecast_days)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1], cached[2]
        try:
            response = _fetch_open_meteo(latitude, longitude, forecast_days)
            _cache[key] = (now + CACHE_TTL_SECONDS, response, None)
            return response, None
        except (URLError, TimeoutError, OSError, HTTPClientError, ValueError) as exc:
            reason = f"Open-Meteo unavailable: {exc}"
            _cache[key] = (now + FAILURE_CACHE_TTL_SECONDS, None, reason)
            return None, reason


def _synthetic_hours(hours: int, solar_capacity_kw: float, start: datetime) -> list[dict]:
    frame = generate_synthetic_data(
        days=max(2, int(np.ceil(hours / 24)) + 1),
        solar_capacity_kw=solar_capacity_kw,
        seed=RANDOM_SEED,
        start=start.replace(tzinfo=None).isoformat(sep=" "),
    ).iloc[:hours]
    return [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "temperature": float(row.temperature),
            "cloud_cover": float(row.cloud_cover),
            "solar_irradiance": float(row.solar_irradiance),
            "wind_speed": float(row.wind_speed),
            "solar_physics_estimate_kw": solar_generation_from_weather(
                solar_capacity_kw, float(row.solar_irradiance), float(row.cloud_cover)
            ),
        }
        for index, row in enumerate(frame.itertuples(index=False))
    ]


def get_hourly_weather(hours: int, solar_capacity_kw: float) -> dict:
    """Return cached weather or deterministic synthetic weather for each forecast hour."""
    start = forecast_start()
    coordinates = _configured_coordinates()
    fallback_reason = None
    records = None
    if coordinates is None:
        if WEATHER_LATITUDE or WEATHER_LONGITUDE:
            fallback_reason = "Weather coordinates are invalid; using synthetic weather."
        else:
            fallback_reason = "Weather coordinates are not configured; using synthetic weather."
    else:
        try:
            ZoneInfo(WEATHER_TIMEZONE)
        except ZoneInfoNotFoundError:
            fallback_reason = f"Unknown weather timezone {WEATHER_TIMEZONE!r}; using synthetic weather."
        else:
            latitude, longitude = coordinates
            response, fallback_reason = _weather_response(
                latitude, longitude, min(16, max(1, int(np.ceil((hours + 24) / 24))))
            )
            if response:
                available = {}
                for record in response["hours"]:
                    local_time = datetime.fromisoformat(record["timestamp"])
                    if local_time.tzinfo is None:
                        local_time = local_time.replace(tzinfo=_timezone())
                    available[local_time.replace(minute=0, second=0, microsecond=0)] = record
                candidate = []
                for index in range(hours):
                    timestamp = start + timedelta(hours=index)
                    record = available.get(timestamp)
                    if record is None:
                        fallback_reason = "Open-Meteo did not return the full forecast window."
                        candidate = []
                        break
                    candidate.append(
                        {
                            **record,
                            "timestamp": timestamp.isoformat(),
                            "solar_physics_estimate_kw": solar_generation_from_weather(
                                solar_capacity_kw, record["solar_irradiance"], record["cloud_cover"]
                            ),
                        }
                    )
                if candidate:
                    records = candidate
    if records is not None:
        return {
            "hours": records,
            "source": "open-meteo",
            "label": "Real weather-informed ML estimates",
            "fallback_reason": None,
            "attribution_url": OPEN_METEO_ATTRIBUTION_URL,
        }
    return {
        "hours": _synthetic_hours(hours, solar_capacity_kw, start),
        "source": "synthetic",
        "label": "Synthetic weather fallback estimates",
        "fallback_reason": fallback_reason,
        "attribution_url": OPEN_METEO_ATTRIBUTION_URL,
    }


def clear_weather_cache() -> None:
    with _cache_lock:
        _cache.clear()
