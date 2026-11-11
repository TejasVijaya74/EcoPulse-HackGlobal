import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import websocket as telemetry


@pytest.fixture
def websocket_client(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, _model):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return None

        def get(self, *_args):
            return None

    monkeypatch.setattr(telemetry, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        telemetry,
        "create_dashboard_preview",
        lambda _config: {
            "series": [
                {
                    "solar_generation_kw": 1.0,
                    "household_demand_kw": 2.0,
                    "net_balance_kw": -1.0,
                    "storage_level_kwh": 10.0,
                    "storage_soc_percent": 50.0,
                    "grid_import_kwh": 1.0,
                    "grid_export_kwh": 0.0,
                    "credits_generated": 0.0,
                    "operating_state": "grid_import",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                }
            ]
        },
    )
    monkeypatch.setattr(telemetry, "CORS_ORIGINS", ("https://preview.example",))
    monkeypatch.setattr(telemetry, "public_demo_mode_enabled", lambda: True)
    monkeypatch.setattr(telemetry, "_active_connections", 0)
    monkeypatch.setattr(telemetry, "_active_connections_by_client", {})

    test_app = FastAPI()
    test_app.include_router(telemetry.router)
    with TestClient(test_app) as client:
        yield client


def test_telemetry_rejects_untrusted_browser_origin(websocket_client):
    with pytest.raises(WebSocketDisconnect):
        with websocket_client.websocket_connect(
            "/ws/grid-telemetry",
            headers={"origin": "https://attacker.example"},
        ):
            pass


def test_telemetry_accepts_configured_dashboard_origin(websocket_client):
    with websocket_client.websocket_connect(
        "/ws/grid-telemetry",
        headers={"origin": "https://preview.example"},
    ) as socket:
        payload = socket.receive_json()

    assert payload["simulated"] is True
    assert payload["solar_generation_kw"] == 1.0
    assert telemetry._active_connections == 0


def test_telemetry_rejects_excess_connections_for_same_client(
    websocket_client, monkeypatch
):
    monkeypatch.setattr(telemetry, "MAX_TELEMETRY_CONNECTIONS_PER_CLIENT", 1)

    with websocket_client.websocket_connect(
        "/ws/grid-telemetry",
        headers={"origin": "https://preview.example"},
    ):
        with pytest.raises(WebSocketDisconnect):
            with websocket_client.websocket_connect(
                "/ws/grid-telemetry",
                headers={"origin": "https://preview.example"},
            ):
                pass

    assert telemetry._active_connections == 0


def test_telemetry_requires_bearer_auth_when_demo_mode_is_disabled(
    websocket_client, monkeypatch
):
    monkeypatch.setattr(telemetry, "public_demo_mode_enabled", lambda: False)
    monkeypatch.setattr(
        telemetry,
        "is_valid_api_token",
        lambda value: value == "valid-test-token",
    )

    with pytest.raises(WebSocketDisconnect):
        with websocket_client.websocket_connect(
            "/ws/grid-telemetry",
            headers={"origin": "https://preview.example"},
        ) as socket:
            socket.send_json({"type": "auth", "token": "invalid"})
            socket.receive_json()

    with websocket_client.websocket_connect(
        "/ws/grid-telemetry",
        headers={"origin": "https://preview.example"},
    ) as socket:
        socket.send_json({"type": "auth", "token": "valid-test-token"})
        payload = socket.receive_json()

    assert payload["simulated"] is True
    assert telemetry._active_connections == 0
