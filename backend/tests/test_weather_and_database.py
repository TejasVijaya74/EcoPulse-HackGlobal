import io
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import numpy as np

from app import database
from app.ml import predictor
from app.services import weather


def test_open_meteo_parser_requests_hourly_weather_fields(monkeypatch):
    observed = {}
    payload = {
        "hourly": {
            "time": ["2026-07-01T10:00"],
            "temperature_2m": [19.5],
            "cloud_cover": [40],
            "shortwave_radiation": [625],
            "wind_speed_10m": [11.2],
        }
    }

    def open_url(url, timeout):
        observed["url"] = url
        observed["timeout"] = timeout
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(weather, "urlopen", open_url)
    parsed = weather._fetch_open_meteo(47.6, -122.3, 2)

    query = parse_qs(urlparse(observed["url"]).query)
    assert query["hourly"] == ["temperature_2m,cloud_cover,shortwave_radiation,wind_speed_10m"]
    assert query["forecast_days"] == ["2"]
    assert observed["timeout"] == weather.REQUEST_TIMEOUT_SECONDS
    assert parsed["hours"][0] == {
        "timestamp": "2026-07-01T10:00",
        "temperature": 19.5,
        "cloud_cover": 0.4,
        "solar_irradiance": 625.0,
        "wind_speed": 11.2,
    }


def test_open_meteo_weather_is_cached_and_converted(monkeypatch):
    weather.clear_weather_cache()
    monkeypatch.setattr(weather, "WEATHER_LATITUDE", "47.6")
    monkeypatch.setattr(weather, "WEATHER_LONGITUDE", "-122.3")
    monkeypatch.setattr(weather, "WEATHER_TIMEZONE", "UTC")
    start = weather.forecast_start()
    calls = []

    def fetch(latitude, longitude, forecast_days):
        calls.append((latitude, longitude, forecast_days))
        return {
            "hours": [
                {
                    "timestamp": (start + timedelta(hours=index)).isoformat(),
                    "temperature": 18.0,
                    "cloud_cover": 0.5,
                    "solar_irradiance": 500.0,
                    "wind_speed": 7.0,
                }
                for index in range(48)
            ]
        }

    monkeypatch.setattr(weather, "_fetch_open_meteo", fetch)
    forecast = weather.get_hourly_weather(2, 100)
    cached = weather.get_hourly_weather(2, 100)

    assert forecast["source"] == "open-meteo"
    assert forecast["hours"][0]["solar_physics_estimate_kw"] == 30.5
    assert forecast["hours"][0]["wind_speed"] == 7.0
    assert cached == forecast
    assert len(calls) == 1
    weather.clear_weather_cache()


def test_weather_failure_falls_back_to_synthetic(monkeypatch):
    weather.clear_weather_cache()
    monkeypatch.setattr(weather, "WEATHER_LATITUDE", "47.6")
    monkeypatch.setattr(weather, "WEATHER_LONGITUDE", "-122.3")
    monkeypatch.setattr(weather, "WEATHER_TIMEZONE", "UTC")

    def fail(*_args):
        raise OSError("offline")

    monkeypatch.setattr(weather, "_fetch_open_meteo", fail)
    result = weather.get_hourly_weather(3, 80)

    assert result["source"] == "synthetic"
    assert len(result["hours"]) == 3
    assert "offline" in result["fallback_reason"]
    assert all(item["solar_physics_estimate_kw"] >= 0 for item in result["hours"])
    weather.clear_weather_cache()


def test_ml_forecast_receives_weather_features(monkeypatch):
    start = weather.forecast_start()
    hours = [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "temperature": 21.0 + index,
            "cloud_cover": 0.25,
            "solar_irradiance": 400.0 + index,
            "wind_speed": 8.0,
            "solar_physics_estimate_kw": 90.0,
        }
        for index in range(2)
    ]
    monkeypatch.setattr(
        predictor,
        "get_hourly_weather",
        lambda count, capacity: {
            "hours": hours[:count],
            "source": "open-meteo",
            "label": "Real weather-informed ML estimates",
            "fallback_reason": None,
            "attribution_url": weather.OPEN_METEO_ATTRIBUTION_URL,
        },
    )
    observed = []

    class Model:
        def __init__(self, value):
            self.value = value

        def set_params(self, **_kwargs):
            return self

        def predict(self, features):
            observed.append(features.iloc[0].to_dict())
            return np.array([self.value])

    monkeypatch.setattr(
        predictor,
        "load_models",
        lambda: ({"solar_generation": Model(30), "household_demand": Model(20)}, {}),
    )
    result = predictor.forecast(2, households=12, solar_capacity_kw=90)

    assert result["weather_source"] == "open-meteo"
    assert result["forecast"][0]["solar_generation_kw"] == 15
    assert result["forecast"][0]["household_demand_kw"] == 4
    assert observed[0]["temperature"] == 21
    assert observed[0]["cloud_cover"] == 0.25
    assert observed[0]["solar_irradiance"] == 400
    assert observed[0]["wind_speed"] == 8
    assert observed[0]["solar_physics_estimate"] == 180 * 0.4 * (1 - 0.78 * 0.25)


def test_postgresql_url_normalization_does_not_connect():
    url = database.normalize_database_url("postgresql://eco:secret@db.example/energy")
    assert url.startswith("postgresql+psycopg://eco:secret@db.example/energy")
