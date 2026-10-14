from fastapi import APIRouter, HTTPException

from app.models import DisasterZone, HistoryResponse
from app.services.data_store import get_store
from app.services.history_service import get_history

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[DisasterZone])
async def list_zones() -> list[DisasterZone]:
    return get_store().list_zones()


@router.get("/{zone_id}", response_model=DisasterZone)
async def get_zone(zone_id: str) -> DisasterZone:
    zone = get_store().get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    return zone


@router.get("/{zone_id}/history", response_model=HistoryResponse)
async def get_zone_history(zone_id: str) -> HistoryResponse:
    zone = get_store().get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    return get_history(zone)
