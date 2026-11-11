import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import desc

from app.config import CORS_ORIGINS, DEFAULT_CONFIG
from app.database import SessionLocal
from app.models import SimulationRecord
from app.services.analytics import create_dashboard_preview
from app.api.routes import current_config
from app.security import is_valid_api_token, public_demo_mode_enabled

router = APIRouter()
MAX_TELEMETRY_CONNECTIONS = 100
MAX_TELEMETRY_CONNECTIONS_PER_CLIENT = 5
_active_connections = 0
_active_connections_by_client: dict[str, int] = {}


@router.websocket("/ws/grid-telemetry")
async def grid_telemetry(websocket: WebSocket) -> None:
    global _active_connections
    origin = websocket.headers.get("origin")
    if origin and origin not in CORS_ORIGINS:
        await websocket.close(code=1008)
        return

    client_host = websocket.client.host if websocket.client else "unknown"
    client_connections = _active_connections_by_client.get(client_host, 0)
    if (
        _active_connections >= MAX_TELEMETRY_CONNECTIONS
        or client_connections >= MAX_TELEMETRY_CONNECTIONS_PER_CLIENT
    ):
        await websocket.close(code=1013)
        return

    _active_connections += 1
    _active_connections_by_client[client_host] = client_connections + 1
    simulation_id = None
    sample_index = 0
    try:
        await websocket.accept()
        if not public_demo_mode_enabled():
            try:
                auth_message = await asyncio.wait_for(websocket.receive_text(), timeout=5)
                if len(auth_message.encode("utf-8")) > 1024:
                    await websocket.close(code=1008)
                    return
                credentials = json.loads(auth_message)
            except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
                await websocket.close(code=1008)
                return
            if (
                not isinstance(credentials, dict)
                or credentials.get("type") != "auth"
                or not is_valid_api_token(credentials.get("token"))
            ):
                await websocket.close(code=1008)
                return

        while True:
            with SessionLocal() as db:
                public_preview = public_demo_mode_enabled()
                latest = (
                    None
                    if public_preview
                    else db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
                )
                if latest:
                    series = json.loads(latest.result_json)["series"]
                    if latest.id != simulation_id:
                        simulation_id = latest.id
                        sample_index = 0
                else:
                    config = DEFAULT_CONFIG if public_preview else current_config(db)
                    series = create_dashboard_preview(config)["series"]
            if not series:
                await websocket.send_json({"type": "error", "message": "No telemetry samples available."})
                await asyncio.sleep(2)
                continue
            sample = series[sample_index % len(series)]
            sample_index += 1
            await websocket.send_json(
                {
                    "solar_generation_kw": sample["solar_generation_kw"],
                    "household_demand_kw": sample["household_demand_kw"],
                    "net_balance_kw": sample["net_balance_kw"],
                    "storage_level_kwh": sample["storage_level_kwh"],
                    "storage_soc_percent": sample["storage_soc_percent"],
                    "grid_imports_kwh": sample["grid_import_kwh"],
                    "grid_exports_kwh": sample["grid_export_kwh"],
                    "credits_generated": sample["credits_generated"],
                    "operating_state": sample["operating_state"],
                    "timestamp": sample["timestamp"],
                    "simulated": True,
                }
            )
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        _active_connections -= 1
        remaining_connections = _active_connections_by_client[client_host] - 1
        if remaining_connections:
            _active_connections_by_client[client_host] = remaining_connections
        else:
            del _active_connections_by_client[client_host]
