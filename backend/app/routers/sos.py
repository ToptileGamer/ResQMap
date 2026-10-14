"""Citizen SOS reports — real user-generated data, persisted to JSON."""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.config import DATA_DIR
from app.services.data_store import get_store

router = APIRouter(prefix="/sos", tags=["sos"])
SOS_PATH = DATA_DIR / "sos.json"

class SosCreate(BaseModel):
    zone_id: str
    reporter_name: str = "anonymous"
    emergency_type: str = "other"
    severity: int = Field(default=3, ge=1, le=5)
    people_affected: int = Field(default=1, ge=0)
    description: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class SosReport(SosCreate):
    id: str
    created_at: datetime
    source: str = "real-user"

def _load() -> list[dict]:
    if not SOS_PATH.exists():
        return []
    try:
        return json.loads(SOS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save(rows: list[dict]) -> None:
    SOS_PATH.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

@router.get("")
async def list_sos(zone_id: Optional[str] = Query(default=None)) -> list[dict]:
    rows = _load()
    if zone_id:
        rows = [r for r in rows if r.get("zone_id") == zone_id]
    return sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)

@router.get("/geojson")
async def sos_geojson(zone_id: Optional[str] = Query(default=None)) -> dict:
    rows = await list_sos(zone_id)
    feats = []
    for r in rows:
        la, lo = r.get("latitude"), r.get("longitude")
        if la is None or lo is None:
            continue
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]}, "properties": {k: v for k, v in r.items() if k not in ("latitude", "longitude")}})
    return {"type": "FeatureCollection", "features": feats, "source": "real-user"}

@router.post("", response_model=dict)
async def create_sos(body: SosCreate) -> dict:
    store = get_store()
    zone = store.get_zone(body.zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{body.zone_id}' not found")
    lat = body.latitude if body.latitude is not None else zone.latitude
    lng = body.longitude if body.longitude is not None else zone.longitude
    rep = {"id": f"sos-{uuid.uuid4().hex[:8]}", "zone_id": body.zone_id, "reporter_name": body.reporter_name, "emergency_type": body.emergency_type, "severity": body.severity, "people_affected": body.people_affected, "description": body.description, "latitude": lat, "longitude": lng, "created_at": datetime.now(timezone.utc).isoformat(), "source": "real-user"}
    rows = _load()
    rows.append(rep)
    _save(rows)
    return rep
