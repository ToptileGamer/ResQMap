"""API routers for ResQMap."""

from fastapi import APIRouter

from app.routers import (
    analysis,
    export,
    grid,
    gis,
    hazard,
    imagery,
    media,
    prediction,
    sensor,
    weather,
    zones,
)

router = APIRouter(prefix="/api")

router.include_router(zones.router)
router.include_router(analysis.router)
router.include_router(weather.router)
router.include_router(imagery.router)
router.include_router(grid.router)
router.include_router(prediction.router)
router.include_router(media.router)
router.include_router(gis.router)
router.include_router(hazard.router)
router.include_router(sensor.router)
