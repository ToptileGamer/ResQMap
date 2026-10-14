"""Free Open-Meteo sources: hourly forecast, GloFAS river-discharge flood
advisory and elevation lookup. Every fetch falls back to deterministic
synthetic values so the app works offline.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from app.config import Settings, get_settings
from app.models import ForecastPoint, ForecastResponse

logger = logging.getLogger("resqmap.openmeteo")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

CACHE_MINUTES = 10.0
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str) -> object | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    fetched_at, payload = entry
    if (datetime.now(timezone.utc) - fetched_at).total_seconds() > CACHE_MINUTES * 60:
        return None
    return payload


def _cache_put(key: str, payload: object) -> None:
    _cache[key] = (datetime.now(timezone.utc), payload)


def _get_json(url: str, params: dict, timeout: float = 6.0) -> dict | None:
    try:
        if get_settings().offline_mode:
            return None
    except Exception:
        pass
    query = urllib.parse.urlencode(params)
    full = f"{url}?{query}"
    try:
        with urllib.request.urlopen(full, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - network errors fall back to synthetic
        logger.warning("Open-Meteo %s failed: %s", url, exc)
        return None


def get_forecast(
    zone,
    settings: Settings,
    hours: int = 24,
    step_hours: int = 3,
) -> ForecastResponse:
    """Return the forecast for one zone (Open-Meteo live, else synthetic)."""
    key = f"forecast:{zone.id}:{hours}"
    cached = _cached(key)
    if cached is not None:
        return cached

    payload = _get_json(
        FORECAST_URL,
        {
            "latitude": zone.latitude,
            "longitude": zone.longitude,
            "hourly": "precipitation,wind_speed_10m",
            "forecast_days": max(2, hours // 24 + 1),
            "timezone": "UTC",
        },
    )

    now = datetime.now(timezone.utc)
    if payload and payload.get("hourly"):
        times = payload["hourly"].get("time", [])
        rain = payload["hourly"].get("precipitation", [])
        wind = payload["hourly"].get("wind_speed_10m", [])
        starts_at = datetime.fromisoformat(times[0].replace("Z", "+00:00")) if times else None
        points: list[ForecastPoint] = []
        for i, hour_step in enumerate(range(1, hours // step_hours + 1)):
            index = hour_step * step_hours - step_hours
            if index >= len(rain):
                break
            # take the max rain across the step window
            window = rain[index : index + step_hours]
            rainfall = float(np.max(window)) if window else 0.0
            wind_kmh = float(wind[index]) if index < len(wind) else 0.0
            ts = (starts_at or now) + timedelta(hours=hour_step * step_hours)
            points.append(
                ForecastPoint(
                    timestamp=ts,
                    expected_rainfall_mm=round(rainfall, 1),
                    expected_wind_kmh=round(wind_kmh, 1),
                    risk_projection=_risk(rainfall, wind_kmh),
                )
            )

        result = ForecastResponse(
            zone_id=zone.id,
            points=points,
            source="open-meteo",
            generated_at=now,
        )
        if points:
            _cache_put(key, result)
            return result

    return _synthetic_forecast(zone, hours, step_hours, now)


def _risk(rainfall: float, wind_kmh: float) -> float:
    return round(min(100.0, max(0.0, rainfall * 1.2 + wind_kmh * 0.4)), 1)


def _synthetic_forecast(zone, hours: int, step_hours: int, now: datetime) -> ForecastResponse:
    import zlib

    rng = np.random.default_rng(zlib.crc32(zone.id.encode("utf-8")) & 0xFFFFFFFF)
    points: list[ForecastPoint] = []
    base = float(zone.base_weather_risk)
    for step in range(1, hours // step_hours + 1):
        t = now + timedelta(hours=step * step_hours)
        phase = 0.6 + 0.4 * np.sin(step / 2.0 + rng.integers(0, 6))
        rainfall = float(np.clip(base * 0.5 * phase + rng.normal(2, 5), 0, 95))
        wind = float(np.clip(8 + base * 0.4 * phase + rng.normal(0, 3), 0, 120))
        points.append(
            ForecastPoint(
                timestamp=t,
                expected_rainfall_mm=round(rainfall, 1),
                expected_wind_kmh=round(wind, 1),
                risk_projection=_risk(rainfall, wind),
            )
        )
    return ForecastResponse(
        zone_id=zone.id,
        points=points,
        source="synthetic",
        generated_at=now,
    )


def get_rain_factors() -> tuple[float, list[float]]:
    """Return (current rain_factor 0..1, hourly accumulation over +24h).

    Uses the highest-rainfall zone forecast when no live call succeeds so the
    whole AOI shares one coherent driving signal.
    """
    key = "rain_factors"
    cached = _cached(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    settings = get_settings()
    zones = _all_zones()
    max_hr = 0.0
    hourly_accum = [0.0] * 24
    for zone in zones[:4]:
        fc = get_forecast(zone, settings, hours=24, step_hours=3)
        for i, p in enumerate(fc.points):
            hour_idx = min(23, i * 3)
            spread = p.expected_rainfall_mm / max(1, 3)
            hourly_accum[hour_idx] = max(hourly_accum[hour_idx], spread)
        peak = max((p.expected_rainfall_mm for p in fc.points), default=0.0)
        max_hr = max(max_hr, peak)

    current = float(np.clip(max_hr / 60.0, 0.05, 1.0))
    _cache_put(key, (current, hourly_accum))
    return current, hourly_accum


def _all_zones():
    from app.services.data_store import get_store

    return get_store().list_zones()


def get_elevation(lat: float, lng: float, settings: Settings) -> Optional[float]:
    """Look up SRTM elevation (m) for a coordinate, else None."""
    key = f"elevation:{lat:.4f}:{lng:.4f}"
    cached = _cached(key)
    if cached is not None:
        return float(cached)  # type: ignore[arg-type]
    payload = _get_json(ELEVATION_URL, {"latitude": lat, "longitude": lng})
    if payload and payload.get("elevation") is not None:
        value = float(payload["elevation"])
        _cache_put(key, value)
        return value
    return None


def get_flood_advisory(lat: float, lng: float, settings: Settings) -> dict:
    """Return GloFAS river-discharge advisory, else synthetic summarised values."""
    key = f"flood:{lat:.4f}:{lng:.4f}"
    cached = _cached(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    payload = _get_json(FLOOD_URL, {"latitude": lat, "longitude": lng, "daily": "river_discharge", "daily_code": "river_discharge_above_threshold", "forecast_days": 7})
    result: dict = {"source": "synthetic", "discharge": [], "advisory": "No live GloFAS data; simulated values used."}
    if payload and payload.get("daily"):
        times = payload["daily"].get("time", [])
        discharge = payload["daily"].get("river_discharge", [])
        below = payload["daily"].get("river_discharge_above_threshold")
        points = []
        for i, ts in enumerate(times):
            points.append({
                "date": ts,
                "discharge": discharge[i] if i < len(discharge) else 0.0,
                "above_threshold": bool(below[i]) if i < len(below) else False,
            })
        if points:
            result = {"source": "open-meteo-glofas", "discharge": points, "advisory": "Live GloFAS advisory."}
            _cache_put(key, result)
    else:
        _cache_put(key, result)
    return result