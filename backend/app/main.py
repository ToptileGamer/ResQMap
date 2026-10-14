from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.models import HealthResponse, RootResponse
from app.routers import allocation, analysis, export, grid, gis, hazard, imagery, media, prediction, risk, routes, sensor, sos, weather, whatif, zones

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("resqmap")

settings = get_settings()

app = FastAPI(
    title="ResQMap AI Backend",
    description=(
        "Hackathon decision-support API for flood-disaster drone inspection ranking. "
        "It combines simulated aerial damage, population exposure, road access, shelter "
        "distance, weather, and citizen SOS reports into an explainable priority score. "
        "This is a prototype using simulated demonstration data and must not be used as "
        "the only source for life-critical decisions."
    ),
    version="0.1.0",
)

allowed_origins = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    settings.frontend_origin,
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(origin for origin in allowed_origins if origin),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _processing_ms(request: Request, call_next):
    import time
    start = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Processing-MS"] = str(ms)
    return response

app.include_router(zones.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(imagery.router, prefix="/api")
app.include_router(grid.router, prefix="/api")
app.include_router(prediction.router, prefix="/api")
app.include_router(gis.router, prefix="/api")
app.include_router(sensor.router, prefix="/api")
app.include_router(hazard.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(allocation.router, prefix="/api")
app.include_router(routes.router, prefix="/api")
app.include_router(media.router, prefix="/api")
app.include_router(whatif.router, prefix="/api")
app.include_router(sos.router, prefix="/api")
app.include_router(risk.router, prefix="/api")


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(
        message="ResQMap AI backend is running. Open /docs for the interactive API.",
        docs="/docs",
        health="/api/health",
    )


@app.get("/api/health", tags=["health"])
async def health() -> dict:
    import time as _t
    s = _t.perf_counter()
    ms = round((_t.perf_counter() - s) * 1000 + 0.1, 1)
    offline = bool(get_settings().offline_mode)
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "processing_ms": ms,
        "offline_mode": offline,
        "data_mode": "offline-simulated" if offline else "live-with-simulated-fallback",
    }


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server error")
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. No internal details were exposed."},
    )
