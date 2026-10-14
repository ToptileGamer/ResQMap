from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.models import WeatherRisk
from app.services.data_store import get_store
from app.services.weather_service import get_weather

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("", response_model=list[WeatherRisk])
async def list_weather() -> list[WeatherRisk]:
    settings = get_settings()
    return [get_weather(zone, settings) for zone in get_store().list_zones()]


@router.get("/{zone_id}", response_model=WeatherRisk)
async def get_zone_weather(zone_id: str) -> WeatherRisk:
    zone = get_store().get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    return get_weather(zone, get_settings())
