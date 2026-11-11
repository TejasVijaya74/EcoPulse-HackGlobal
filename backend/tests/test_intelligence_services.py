from datetime import datetime, timedelta

import httpx
import pytest

from app.services import intelligence, research, weatherapi


class MockResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


class MockClient:
    def __init__(self, *, timeout):
        self.timeout = timeout
        self.get_response = MockResponse({})
        self.post_response = MockResponse({})
        self.get_error = None
        self.post_error = None
        self.get_request = None
        self.post_request = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url, *, params):
        self.get_request = (url, params)
        if self.get_error:
            raise self.get_error
        return self.get_response

    def post(self, url, *, json):
        self.post_request = (url, json)
        if self.post_error:
            raise self.post_error
        return self.post_response


def current_payload():
    return {
        "location": {
            "name": "New Delhi",
            "region": "Delhi",
            "country": "India",
            "localtime": "2026-11-10 10:25",
        },
        "current": {
            "last_updated": "2026-11-10 10:15",
            "temp_c": 24.5,
            "feelslike_c": 25.0,
            "cloud": 40,
            "humidity": 55,
            "wind_kph": 10.0,
            "gust_kph": 15.0,
            "precip_mm": 0.0,
            "condition": {"text": "Partly cloudy"},
            "is_day": 1,
        },
    }


def forecast_payload():
    start = datetime.fromisoformat("2026-11-10 10:00")
    hours = []
    for offset in range(24):
        stamp = start + timedelta(hours=offset)
        hours.append(
            {
                "time": stamp.strftime("%Y-%m-%d %H:%M"),
                "temp_c": 25 + offset / 10,
                "cloud": 40,
                "humidity": 55,
                "wind_kph": 10,
                "gust_kph": 15,
                "chance_of_rain": 20,
                "precip_mm": 0,
                "condition": {"text": "Partly cloudy"},
            }
        )
    return {
        **current_payload(),
        "forecast": {
            "forecastday": [
                {
                    "date": "2026-11-10",
                    "day": {
                        "mintemp_c": 18,
                        "maxtemp_c": 30,
                        "daily_chance_of_rain": 20,
                        "totalprecip_mm": 0,
                        "condition": {"text": "Partly cloudy"},
                    },
                    "hour": hours,
                }
            ]
        },
        "alerts": {
            "alert": [
                {
                    "headline": "Heat notice",
                    "desc": "Weather alert summary.",
                    "severity": "Moderate",
                    "effective": "2026-11-10 12:00",
                    "expires": "2026-11-10 18:00",
                }
            ]
        },
    }


def test_weatherapi_current_parsing_and_request(monkeypatch):
    client = MockClient(timeout=weatherapi.REQUEST_TIMEOUT_SECONDS)
    client.get_response = MockResponse(current_payload())
    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "test-weather-key")
    monkeypatch.setattr(weatherapi.httpx, "Client", lambda **kwargs: client)
    weatherapi.clear_cache()

    result = weatherapi.get_current("Delhi")

    assert result["source"] == "WeatherAPI.com"
    assert result["location"]["country"] == "India"
    assert result["current"]["temperature_c"] == 24.5
    assert result["current"]["cloud_cover_percent"] == 40
    assert client.get_request[0].endswith("/current.json")
    assert client.get_request[1]["q"] == "Delhi"
    assert client.get_request[1]["key"] == "test-weather-key"


def test_weatherapi_forecast_parses_hourly_daily_alerts_without_irradiance(monkeypatch):
    client = MockClient(timeout=weatherapi.REQUEST_TIMEOUT_SECONDS)
    client.get_response = MockResponse(forecast_payload())
    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "test-weather-key")
    monkeypatch.setattr(weatherapi.httpx, "Client", lambda **kwargs: client)
    weatherapi.clear_cache()

    result = weatherapi.get_forecast(days=1)

    assert result["current"]["condition"] == "Partly cloudy"
    assert result["daily"][0]["maximum_temperature_c"] == 30
    assert result["alerts"][0]["title"] == "Heat notice"
    assert len(result["hourly"]) == 24
    assert all("solar_irradiance" not in hour for hour in result["hourly"])
    assert client.get_request[0].endswith("/forecast.json")
    assert client.get_request[1]["alerts"] == "yes"


def test_weatherapi_rejects_malformed_and_out_of_range_payloads(monkeypatch):
    client = MockClient(timeout=weatherapi.REQUEST_TIMEOUT_SECONDS)
    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "test-weather-key")
    monkeypatch.setattr(weatherapi.httpx, "Client", lambda **kwargs: client)
    weatherapi.clear_cache()

    client.get_response = MockResponse({"location": {}, "current": {}})
    with pytest.raises(weatherapi.WeatherInvalidResponse):
        weatherapi.get_current()

    bad_payload = current_payload()
    bad_payload["current"]["cloud"] = 140
    client.get_response = MockResponse(bad_payload)
    weatherapi.clear_cache()
    with pytest.raises(weatherapi.WeatherInvalidResponse):
        weatherapi.get_current()


def test_weatherapi_missing_key_timeout_and_quota_are_explicit(monkeypatch):
    client = MockClient(timeout=weatherapi.REQUEST_TIMEOUT_SECONDS)
    monkeypatch.setattr(weatherapi.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "")
    with pytest.raises(weatherapi.WeatherNotConfigured):
        weatherapi.get_current()

    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "test-weather-key")
    client.get_error = httpx.ReadTimeout("private request details")
    with pytest.raises(weatherapi.WeatherTimeout):
        weatherapi.get_current()

    client.get_error = None
    client.get_response = MockResponse({}, status_code=429)
    weatherapi.clear_cache()
    with pytest.raises(weatherapi.WeatherRateLimited):
        weatherapi.get_current()

    client.get_response = MockResponse(
        {"error": {"code": 2007, "message": "quota"}},
        status_code=403,
    )
    weatherapi.clear_cache()
    with pytest.raises(weatherapi.WeatherRateLimited):
        weatherapi.get_current()


def test_weatherapi_location_search_filters_invalid_locations(monkeypatch):
    client = MockClient(timeout=weatherapi.REQUEST_TIMEOUT_SECONDS)
    client.get_response = MockResponse(
        [
            {"name": "Delhi", "region": "Delhi", "country": "India", "lat": 28.6, "lon": 77.2},
            {"name": "Invalid", "region": "", "country": "India", "lat": 120, "lon": 10},
        ]
    )
    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "test-weather-key")
    monkeypatch.setattr(weatherapi.httpx, "Client", lambda **kwargs: client)
    weatherapi.clear_cache()

    locations = weatherapi.search_locations("Delhi")

    assert len(locations) == 1
    assert locations[0]["latitude"] == 28.6


def test_weatherapi_success_cache_is_bounded(monkeypatch):
    client = MockClient(timeout=weatherapi.REQUEST_TIMEOUT_SECONDS)
    client.get_response = MockResponse(current_payload())
    monkeypatch.setattr(weatherapi, "WEATHERAPI_KEY", "test-weather-key")
    monkeypatch.setattr(weatherapi, "MAX_CACHE_ENTRIES", 2)
    monkeypatch.setattr(weatherapi.httpx, "Client", lambda **kwargs: client)
    weatherapi.clear_cache()

    for location in ("Delhi", "Mumbai", "Pune"):
        weatherapi.get_current(location)

    assert len(weatherapi._cache) == 2
    assert all(key[0] == "current" for key in weatherapi._cache)
    weatherapi.clear_cache()


def test_weather_insights_are_relative_and_never_infer_irradiance_or_absolute_generation():
    payload = forecast_payload()
    payload["hourly"] = [
        {
            "cloud_cover_percent": 80,
            "temperature_c": 35,
            "chance_of_rain_percent": 75,
        }
        for _ in range(24)
    ]
    result = intelligence.build_weather_insights(
        payload,
        {"cloud_cover": 0.35, "temperature_c": 22.0},
    )

    assert result["available"] is True
    assert result["solar_irradiance_available"] is False
    assert result["relative_solar_potential_change_percent"] < 0
    assert result["estimated_temperature_related_demand_adjustment_percent"] > 0
    assert "solar_generation_kwh" not in result
    assert "solar_irradiance" not in result
    assert result["recommendations"]


def test_tavily_parser_deduplicates_and_preserves_only_returned_dates():
    parsed = research.parse_tavily_results(
        {
            "results": [
                {
                    "title": "Storage report",
                    "content": "Summary from source.",
                    "url": "https://example.org/report?utm_source=feed",
                    "published_date": "2026-11-01",
                },
                {
                    "title": "Duplicate report",
                    "content": "Duplicate summary.",
                    "url": "https://example.org/report",
                },
                {
                    "title": "Unsafe link",
                    "content": "Should not be returned.",
                    "url": "javascript:alert(1)",
                    "published_date": "invented-date",
                },
            ]
        },
        "storage",
    )

    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["source_domain"] == "example.org"
    assert parsed["results"][0]["published_date"] == "2026-11-01"
    assert parsed["results"][0]["source_url"].endswith("utm_source=feed")
    assert parsed["results"][0].get("published_date") is not None


def test_tavily_search_uses_bounded_news_request_and_caches_results(monkeypatch):
    client = MockClient(timeout=research.REQUEST_TIMEOUT_SECONDS)
    client.post_response = MockResponse(
        {
            "results": [
                {
                    "title": "Solar update",
                    "content": "A source-backed snippet.",
                    "url": "https://news.example/solar",
                    "published_date": "2026-11-03",
                }
            ]
        }
    )
    monkeypatch.setattr(research, "TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: client)
    research.clear_cache()

    result = research.search_research("solar")
    cached = research.search_research("solar")

    assert result == cached
    assert result["results"][0]["source_url"] == "https://news.example/solar"
    assert client.post_request[0] == research.TAVILY_SEARCH_URL
    assert client.post_request[1]["api_key"] == "test-tavily-key"
    assert client.post_request[1]["max_results"] == 6
    assert client.post_request[1]["topic"] == "news"
    research.clear_cache()


def test_tavily_missing_key_timeout_quota_and_malformed_response(monkeypatch):
    client = MockClient(timeout=research.REQUEST_TIMEOUT_SECONDS)
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(research, "TAVILY_API_KEY", "")
    with pytest.raises(research.ResearchNotConfigured):
        research.search_research("solar")

    monkeypatch.setattr(research, "TAVILY_API_KEY", "test-tavily-key")
    client.post_error = httpx.ReadTimeout("private request details")
    research.clear_cache()
    with pytest.raises(research.ResearchTimeout):
        research.search_research("solar")

    client.post_error = None
    client.post_response = MockResponse({}, status_code=429)
    with pytest.raises(research.ResearchRateLimited):
        research.search_research("solar")

    client.post_response = MockResponse({"unexpected": []})
    with pytest.raises(research.ResearchInvalidResponse):
        research.search_research("solar")
