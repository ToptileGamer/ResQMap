import base64
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from typing import Optional

from app.config import get_settings
from app.models import AerialAnalysisRequest, AerialAnalysisResponse
from app.services.analysis_service import analyze_single
from app.services.data_store import get_store
from app.services.imagery_service import analyze_zone_frame_with_geojson

logger = logging.getLogger("resqmap.imagery")

router = APIRouter(prefix="/imagery", tags=["imagery"])

MAX_BYTES = 15 * 1024 * 1024


def _decode_image(image_base64: str) -> bytes:
    if image_base64.startswith("data:"):
        image_base64 = image_base64.split(",", 1)[-1]
    try:
        raw = base64.b64decode(image_base64, validate=False)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Image payload is not valid base64.") from exc
    if not raw:
        raise HTTPException(status_code=400, detail="Image payload is empty.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image is too large (limit 15 MB).")
    return raw


@router.post("/upload", response_model=AerialAnalysisResponse)
async def analyze_upload(
    zone_id: str = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(default=None),
) -> AerialAnalysisResponse:
    """Real-data image upload (multipart). Accepts JPEG/PNG up to 15 MB."""
    if file.content_type and not (file.content_type.startswith("image/") or file.content_type == "application/octet-stream"):
        raise HTTPException(status_code=400, detail=f"Expected image upload, got {file.content_type}")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (limit 15 MB)")
    store = get_store()
    zone = store.get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    result, geojson = analyze_zone_frame_with_geojson(zone, raw)
    updated = store.set_zone_overrides(zone.id, {"aerial_damage_score": result.damage_score, "flood_severity": round(0.6 * result.flood_affected_pct + 0.4 * zone.flood_severity, 1), "aerial_analyzed_at": datetime.now(timezone.utc), "aerial_analysis_note": f"Real upload {file.filename}: {result.flood_affected_pct:.0f}% flooded."})
    affected = analyze_single(updated.id, store, get_settings())
    return AerialAnalysisResponse(zone_id=updated.id, zone_name=updated.name, method=result.method, flood_affected_pct=result.flood_affected_pct, damage_score=result.damage_score, image_width=result.image_width, image_height=result.image_height, preview_base64=result.preview_base64, mask_base64=result.mask_base64, description=description or f"Real upload: {file.filename}", affected_priority_score=round(affected.priority_score, 1), affected_priority_level=affected.priority_level, geojson=geojson, analyzed_at=datetime.now(timezone.utc))


@router.post("/analyze", response_model=AerialAnalysisResponse)
async def analyze_aerial(payload: AerialAnalysisRequest) -> AerialAnalysisResponse:
    store = get_store()
    zone = store.get_zone(payload.zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{payload.zone_id}' not found")

    provided = _decode_image(payload.image_base64) if payload.image_base64 else None
    result, geojson = analyze_zone_frame_with_geojson(zone, provided)

    # Integrate the aerial observation into the zone's live readings so the
    # prioritisation model uses real (or simulated) drone evidence.
    updated = store.set_zone_overrides(
        zone.id,
        {
            "aerial_damage_score": result.damage_score,
            "flood_severity": round(0.6 * result.flood_affected_pct + 0.4 * zone.flood_severity, 1),
            "aerial_analyzed_at": datetime.now(timezone.utc),
            "aerial_analysis_note": f"Drone analysis: {result.flood_affected_pct:.0f}% flooded area detected.",
        },
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Zone '{payload.zone_id}' not found")

    affected = analyze_single(updated.id, store, get_settings())
    if affected is None:
        raise HTTPException(status_code=404, detail=f"Zone '{payload.zone_id}' not found")

    return AerialAnalysisResponse(
        zone_id=updated.id,
        zone_name=updated.name,
        method=result.method,
        flood_affected_pct=result.flood_affected_pct,
        damage_score=result.damage_score,
        image_width=result.image_width,
        image_height=result.image_height,
        preview_base64=result.preview_base64,
        mask_base64=result.mask_base64,
        description=payload.description,
        affected_priority_score=round(affected.priority_score, 1),
        affected_priority_level=affected.priority_level,
        geojson=geojson,
        analyzed_at=datetime.now(timezone.utc),
    )