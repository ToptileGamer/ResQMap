from fastapi import APIRouter, HTTPException, Query

from app.models import SpreadResponse
from app.services.data_store import get_store
from app.services.prediction_service import prediction_for_zone

router = APIRouter(prefix="/prediction", tags=["prediction"])


@router.get("/{zone_id}", response_model=SpreadResponse)
async def prediction_zone(
    zone_id: str,
    rain_multiplier: float = Query(default=1.0, ge=0.5, le=4.0),
    include_geojson: bool = Query(default=False),
) -> SpreadResponse:
    store = get_store()
    if store.get_zone(zone_id) is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    result = prediction_for_zone(zone_id, rain_multiplier, include_geojson)
    result["rain_multiplier"] = rain_multiplier
    return result


@router.get("", response_model=SpreadResponse)
async def prediction_district(
    zone_id: str | None = None,
    rain_multiplier: float = Query(default=1.0, ge=0.5, le=4.0),
    include_geojson: bool = Query(default=False),
) -> SpreadResponse:
    """Spread across the whole district; zone_id only changes the focus label."""
    if zone_id is None or get_store().get_zone(zone_id) is None:
        zone_id = "district"
    result = prediction_for_zone(zone_id, rain_multiplier, include_geojson)
    result["rain_multiplier"] = rain_multiplier
    return result