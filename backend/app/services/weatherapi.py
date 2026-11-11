import copy
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.config import WEATHERAPI_BASE_URL, WEATHERAPI_DEFAULT_LOCATION, WEATHERAPI_KEY

REQUEST_TIMEOUT_SECONDS = 8.0
CACHE_TTL_SECONDS = 900
MAX_FORECAST_DAYS = 3
MAX_CACHE_ENTRIES = 256

_cache: OrderedDict[tuple, tuple[float, dict | list]] = OrderedDict()
_cache_lock = threading.Lock()


class WeatherAPIError(Exception):
    pass


class WeatherNotConfigured(WeatherAPIError):
    pass


class WeatherRateLimited(WeatherAPIError):
    pass


class WeatherTimeout(WeatherAPIError):
    pass


class WeatherUnavailable(WeatherAPIError):
    pass


class WeatherInvalidResponse(WeatherAPIError):
    pass


def _validate_config() -> None:
    parsed = urlsplit(WEATHERAPI_BASE_URL)
    if not WEATHERAPI_KEY:
        raise WeatherNotConfigured("WeatherAPI is not configured.")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise WeatherNotConfigured("WeatherAPI configuration is invalid.")


def _request(endpoint: str, params: dict) -> dict | list:
    _validate_config()
    cache_key = (endpoint, *sorted((key, str(value)) for key, value in params.items()))
    now = time.monotonic()
    with _cache_lock:
        expired_keys = [key for key, (expires_at, _) in _cache.items() if expires_at <= now]
        for key in expired_keys:
            del _cache[key]
        cached = _cache.get(cache_key)
        if cached and cached[0] > now:
            _cache.move_to_end(cache_key)
            return copy.deepcopy(cached[1])

    url = f"{WEATHERAPI_BASE_URL}/{endpoint}.json"
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(url, params={"key": WEATHERAPI_KEY, **params})
    except httpx.TimeoutException as exc:
        raise WeatherTimeout("WeatherAPI request timed out.") from exc
    except httpx.RequestError as exc:
        raise WeatherUnavailable("WeatherAPI is temporarily unavailable.") from exc

    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        if response.status_code >= 400:
            raise WeatherUnavailable("WeatherAPI returned an error.") from exc
        raise WeatherInvalidResponse("WeatherAPI returned malformed JSON.") from exc
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        if isinstance(error, dict) and error.get("code") in (2007, 2009):
            raise WeatherRateLimited("WeatherAPI request quota is currently unavailable.")
        if isinstance(error, dict) and error.get("code") in (2006, 2008):
            raise WeatherNotConfigured("WeatherAPI rejected its credentials or quota.")
        raise WeatherUnavailable("WeatherAPI returned an error response.")
    if response.status_code == 429:
        raise WeatherRateLimited("WeatherAPI request quota is currently unavailable.")
    if response.status_code in {401, 403}:
        raise WeatherNotConfigured("WeatherAPI credentials were rejected.")
    if response.status_code >= 400:
        raise WeatherUnavailable("WeatherAPI returned an error.")
    if not isinstance(payload, (dict, list)):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid response document.")

    with _cache_lock:
        expired_keys = [
            key for key, (expires_at, _) in _cache.items() if expires_at <= time.monotonic()
        ]
        for key in expired_keys:
            del _cache[key]
        _cache[cache_key] = (time.monotonic() + CACHE_TTL_SECONDS, copy.deepcopy(payload))
        _cache.move_to_end(cache_key)
        while len(_cache) > MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)
    return payload


def _discard_cached_request(endpoint: str, params: dict) -> None:
    cache_key = (endpoint, *sorted((key, str(value)) for key, value in params.items()))
    with _cache_lock:
        _cache.pop(cache_key, None)


def _number(value, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WeatherInvalidResponse(f"WeatherAPI returned an invalid {name} value.")
    number = float(value)
    if minimum is not None and number < minimum or maximum is not None and number > maximum:
        raise WeatherInvalidResponse(f"WeatherAPI returned an out-of-range {name} value.")
    return number


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WeatherInvalidResponse(f"WeatherAPI returned an invalid {name} value.")
    return value.strip()


def _condition(value) -> str:
    if not isinstance(value, dict):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid weather condition.")
    return _text(value.get("text"), "condition")


def _parse_location(value: dict) -> dict:
    if not isinstance(value, dict):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid location.")
    return {
        "name": _text(value.get("name"), "location name"),
        "region": value.get("region") if isinstance(value.get("region"), str) else "",
        "country": _text(value.get("country"), "country"),
        "local_time": value.get("localtime") if isinstance(value.get("localtime"), str) else None,
    }


def _parse_current(value: dict) -> dict:
    if not isinstance(value, dict):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid current-conditions section.")
    return {
        "observed_at": value.get("last_updated") if isinstance(value.get("last_updated"), str) else None,
        "temperature_c": _number(value.get("temp_c"), "temperature"),
        "feels_like_c": _number(value.get("feelslike_c"), "feels-like temperature"),
        "cloud_cover_percent": _number(value.get("cloud"), "cloud cover", 0, 100),
        "humidity_percent": _number(value.get("humidity"), "humidity", 0, 100),
        "wind_kph": _number(value.get("wind_kph"), "wind speed", 0),
        "gust_kph": _number(value.get("gust_kph"), "wind gust", 0),
        "precipitation_mm": _number(value.get("precip_mm"), "precipitation", 0),
        "condition": _condition(value.get("condition")),
        "is_day": bool(value.get("is_day")),
    }


def _parse_hour(value: dict) -> dict:
    if not isinstance(value, dict):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid hourly forecast record.")
    stamp = _text(value.get("time"), "forecast time")
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise WeatherInvalidResponse("WeatherAPI returned an invalid forecast timestamp.") from exc
    return {
        "time": stamp,
        "temperature_c": _number(value.get("temp_c"), "temperature"),
        "cloud_cover_percent": _number(value.get("cloud"), "cloud cover", 0, 100),
        "humidity_percent": _number(value.get("humidity"), "humidity", 0, 100),
        "wind_kph": _number(value.get("wind_kph"), "wind speed", 0),
        "gust_kph": _number(value.get("gust_kph"), "wind gust", 0),
        "chance_of_rain_percent": _number(value.get("chance_of_rain"), "rain chance", 0, 100),
        "precipitation_mm": _number(value.get("precip_mm"), "precipitation", 0),
        "condition": _condition(value.get("condition")),
    }


def _parse_alerts(value) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, dict) or not isinstance(value.get("alert", []), list):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid alerts section.")
    alerts = []
    for alert in value.get("alert", []):
        if not isinstance(alert, dict):
            continue
        title = alert.get("headline") or alert.get("event") or alert.get("desc")
        if not isinstance(title, str) or not title.strip():
            continue
        alerts.append(
            {
                "title": title.strip(),
                "description": alert.get("desc") if isinstance(alert.get("desc"), str) else "",
                "severity": alert.get("severity") if isinstance(alert.get("severity"), str) else None,
                "effective_at": alert.get("effective") if isinstance(alert.get("effective"), str) else None,
                "expires_at": alert.get("expires") if isinstance(alert.get("expires"), str) else None,
            }
        )
    return alerts


def get_current(location: str | None = None) -> dict:
    query = (location or WEATHERAPI_DEFAULT_LOCATION).strip()
    if not query:
        raise WeatherNotConfigured("Set a default location or provide a location.")
    payload = _request("current", {"q": query})
    try:
        if not isinstance(payload, dict):
            raise WeatherInvalidResponse("WeatherAPI returned an invalid current-weather document.")
        current = payload.get("current")
        if not isinstance(current, dict):
            raise WeatherInvalidResponse("WeatherAPI response is missing current conditions.")
        return {
            "source": "WeatherAPI.com",
            "source_url": "https://www.weatherapi.com/",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "location": _parse_location(payload.get("location")),
            "current": _parse_current(current),
        }
    except WeatherInvalidResponse:
        _discard_cached_request("current", {"q": query})
        raise


def get_forecast(location: str | None = None, days: int = 3) -> dict:
    query = (location or WEATHERAPI_DEFAULT_LOCATION).strip()
    if not query:
        raise WeatherNotConfigured("Set a default location or provide a location.")
    if not 1 <= days <= MAX_FORECAST_DAYS:
        raise ValueError(f"Forecast days must be between 1 and {MAX_FORECAST_DAYS}.")
    payload = _request(
        "forecast",
        {"q": query, "days": days, "alerts": "yes", "aqi": "no"},
    )
    try:
        if not isinstance(payload, dict):
            raise WeatherInvalidResponse("WeatherAPI returned an invalid forecast document.")
        forecast_data = payload.get("forecast")
        if not isinstance(forecast_data, dict) or not isinstance(forecast_data.get("forecastday"), list):
            raise WeatherInvalidResponse("WeatherAPI response is missing forecast data.")

        hourly = []
        daily = []
        for day in forecast_data["forecastday"]:
            if not isinstance(day, dict):
                raise WeatherInvalidResponse("WeatherAPI returned an invalid daily forecast.")
            day_data = day.get("day")
            if not isinstance(day_data, dict):
                raise WeatherInvalidResponse("WeatherAPI returned an invalid daily forecast.")
            daily.append(
                {
                    "date": _text(day.get("date"), "forecast date"),
                    "minimum_temperature_c": _number(day_data.get("mintemp_c"), "minimum temperature"),
                    "maximum_temperature_c": _number(day_data.get("maxtemp_c"), "maximum temperature"),
                    "chance_of_rain_percent": _number(
                        day_data.get("daily_chance_of_rain"), "daily rain chance", 0, 100
                    ),
                    "total_precipitation_mm": _number(
                        day_data.get("totalprecip_mm"), "daily precipitation", 0
                    ),
                    "condition": _condition(day_data.get("condition")),
                }
            )
            day_hours = day.get("hour")
            if not isinstance(day_hours, list):
                raise WeatherInvalidResponse("WeatherAPI response is missing hourly forecast data.")
            hourly.extend(_parse_hour(hour) for hour in day_hours)

        location_data = _parse_location(payload.get("location"))
        local_time = location_data["local_time"]
        if isinstance(local_time, str):
            try:
                local_now = datetime.fromisoformat(local_time).replace(minute=0, second=0, microsecond=0)
            except ValueError as exc:
                raise WeatherInvalidResponse("WeatherAPI returned an invalid local timestamp.") from exc
            hourly = [
                hour for hour in hourly if datetime.fromisoformat(hour["time"]) >= local_now
            ]

        alerts_container = payload.get("alerts", {})
        return {
            "source": "WeatherAPI.com",
            "source_url": "https://www.weatherapi.com/",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "location": location_data,
            "current": _parse_current(payload.get("current")),
            "hourly": hourly,
            "daily": daily,
            "alerts": _parse_alerts(alerts_container),
        }
    except WeatherInvalidResponse:
        _discard_cached_request(
            "forecast",
            {"q": query, "days": days, "alerts": "yes", "aqi": "no"},
        )
        raise


def search_locations(query: str) -> list[dict]:
    search = query.strip()
    if not search:
        raise ValueError("Location search must not be blank.")
    payload = _request("search", {"q": search})
    if not isinstance(payload, list):
        raise WeatherInvalidResponse("WeatherAPI returned an invalid location-search document.")
    locations = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            locations.append(
                {
                    "name": _text(item.get("name"), "location name"),
                    "region": item.get("region") if isinstance(item.get("region"), str) else "",
                    "country": _text(item.get("country"), "country"),
                    "latitude": _number(item.get("lat"), "latitude", -90, 90),
                    "longitude": _number(item.get("lon"), "longitude", -180, 180),
                }
            )
        except WeatherInvalidResponse:
            continue
    return locations[:8]


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
