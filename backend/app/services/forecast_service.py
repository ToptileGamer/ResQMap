from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone

import numpy as np

from app.config import Settings
from app.models import DisasterZone, ForecastPoint, ForecastResponse

logger = logging.getLogger("resqmap.forecast")

HOURS = 24
STEP_HOURS = 3


def _risk_from_weather(rainfall: float, wind_kmh: float) -> float:
    return round(min(100.0, max(0.0, rainfall * 1.2 + wind_kmh * 0.4)), 1)


def _simulated_forecast(zone: DisasterZone) -> ForecastResponse:
    rng = np.random.default_rng(zlib.crc32(zone.id.encode("utf-8")) & 0xFFFFFFFF)
    now = datetime.now(timezone.utc)
    points: list[ForecastPoint] = []

    for step in range(1, HOURS // STEP_HOURS + 1):
        t = now + timedelta(hours=STEP_HOURS * step)
        phase = 0.6 + 0.4 * np.sin((step - 1) / 2.0 + (rng.integers(0, 6)))
        rainfall = float(np.clip(zone.base_weather_risk * 0.5 * phase + rng.normal(2, 5), 0, 95))
        wind = float(np.clip(8 + zone.base_weather_risk * 0.4 * phase + rng.normal(0, 3), 0, 120))
        points.append(
            ForecastPoint(
                timestamp=t,
                expected_rainfall_mm=round(rainfall, 1),
                expected_wind_kmh=round(wind, 1),
                risk_projection=_risk_from_weather(rainfall, wind),
            )
        )

    return ForecastResponse(
        zone_id=zone.id,
        points=points,
        source="simulated",
        generated_at=now,
    )


def _fetch_openweather_forecast(zone: DisasterZone, settings: Settings) -> ForecastResponse | None:
    query = urllib.parse.urlencode(
        {
            "lat": zone.latitude,
            "lon": zone.longitude,
            "appid": settings.openweather_api_key,
            "units": "metric",
            "cnt": HOURS // 3,
        }
    )
    url = f"{settings.openweather_base_url.rstrip('/')}/forecast?{query}"
    try:
        with urllib.request.urlopen(url, timeout=settings.request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - fall back to simulated forecast
        logger.warning("OpenWeather forecast failed for %s: %s", zone.id, exc)
        return None

    try:
        points = []
        for item in payload.get("list", [])[: HOURS // 3]:
            rain = item.get("rain") or {}
            wind = item.get("wind") or {}
            rainfall = float(rain.get("3h", 0.0) or 0.0)
            wind_kmh = float(wind.get("speed", 0.0) or 0.0) * 3.6
            points.append(
                ForecastPoint(
                    timestamp=datetime.fromtimestamp(item.get("dt", 0), tz=timezone.utc),
                    expected_rainfall_mm=round(rainfall, 1),
                    expected_wind_kmh=round(wind_kmh, 1),
                    risk_projection=_risk_from_weather(rainfall, wind_kmh),
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected forecast payload for %s: %s", zone.id, exc)
        return None

    return ForecastResponse(
        zone_id=zone.id,
        points=points,
        source="openweathermap",
        generated_at=datetime.now(timezone.utc),
    )


def get_forecast(zone: DisasterZone, settings: Settings) -> ForecastResponse:
    if settings.has_openweather_key():
        live = _fetch_openweather_forecast(zone, settings)
        if live is not None and live.points:
            return live
    return _simulated_forecast(zone)