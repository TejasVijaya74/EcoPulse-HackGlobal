import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import desc

from app.database import SessionLocal
from app.models import SimulationRecord
from app.services.analytics import create_dashboard_preview
from app.api.routes import current_config

router = APIRouter()


@router.websocket("/ws/grid-telemetry")
async def grid_telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    simulation_id = None
    sample_index = 0
    try:
        while True:
            with SessionLocal() as db:
                latest = db.query(SimulationRecord).order_by(desc(SimulationRecord.created_at)).first()
                if latest:
                    series = json.loads(latest.result_json)["series"]
                    if latest.id != simulation_id:
                        simulation_id = latest.id
                        sample_index = 0
                else:
                    series = create_dashboard_preview(current_config(db))["series"]
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
        return
