from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app.config import Settings
from app.models import DisasterZone, WeatherRisk

logger = logging.getLogger("resqmap.weather")

_SIMULATED_MESSAGES = {
    "no_key": "Simulated weather (no OPENWEATHER_API_KEY configured).",
    "auth": "OpenWeather rejected the API key; using simulated weather. Check OPENWEATHER_API_KEY in backend/.env.",
    "http_error": "OpenWeather returned an error; using simulated weather.",
    "network": "Could not reach the OpenWeather service; using simulated weather.",
}


def _simulated_weather(zone: DisasterZone, reason: str = "no_key") -> WeatherRisk:
    """Deterministic fallback derived from the zone's base weather risk.

    Used when no OpenWeather API key is configured or the upstream call fails,
    so the demo always returns a coherent, explainable value.
    """
    base = zone.base_weather_risk
    rainfall = round(base * 0.9, 1)
    wind = round(8.0 + base * 0.45, 1)
    if rainfall >= 60:
        condition = "Heavy rain"
    elif rainfall >= 30:
        condition = "Moderate rain"
    elif rainfall >= 10:
        condition = "Light rain"
    else:
        condition = "Overcast"
    risk = round(min(100.0, max(0.0, 0.6 * base + 0.4 * min(100.0, rainfall))), 1)
    return WeatherRisk(
        zone_id=zone.id,
        rainfall_mm=rainfall,
        wind_speed_kmh=wind,
        weather_condition=condition,
        weather_risk_score=risk,
        source="simulated",
        fetched_at=datetime.now(timezone.utc),
        status_message=_SIMULATED_MESSAGES.get(reason, "Live weather unavailable; using simulated weather."),
    )


def _fetch_openweather(zone: DisasterZone, settings: Settings) -> tuple[WeatherRisk | None, str | None]:
    """Return (live_weather, failure_reason). failure_reason is None on success."""
    query = urllib.parse.urlencode(
        {
            "lat": zone.latitude,
            "lon": zone.longitude,
            "appid": settings.openweather_api_key,
            "units": "metric",
        }
    )
    url = f"{settings.openweather_base_url.rstrip('/')}/weather?{query}"
    try:
        with urllib.request.urlopen(url, timeout=settings.request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        logger.warning("OpenWeather HTTP %s for %s", exc.code, zone.id)
        return None, ("auth" if exc.code in (401, 403) else "http_error")
    except Exception as exc:  # noqa: BLE001 - fall back to simulated weather
        logger.warning("OpenWeather request failed for %s: %s", zone.id, exc)
        return None, "network"

    try:
        rain = payload.get("rain") or {}
        wind = payload.get("wind") or {}
        weather_list = payload.get("weather") or [{}]
        rainfall = float(rain.get("1h", 0.0) or 0.0)
        wind_kmh = float(wind.get("speed", 0.0) or 0.0) * 3.6
        condition = str(weather_list[0].get("main", "Unknown"))
    except Exception as exc:  # noqa: BLE001 - fall back to simulated weather
        logger.warning("Unexpected OpenWeather payload for %s: %s", zone.id, exc)
        return None, "network"

    risk = round(min(100.0, max(0.0, rainfall * 1.2 + wind_kmh * 0.4)), 1)
    return (
        WeatherRisk(
            zone_id=zone.id,
            rainfall_mm=round(rainfall, 1),
            wind_speed_kmh=round(wind_kmh, 1),
            weather_condition=condition,
            weather_risk_score=risk,
            source="openweathermap",
            fetched_at=datetime.now(timezone.utc),
            status_message=None,
        ),
        None,
    )


def get_weather(zone: DisasterZone, settings: Settings) -> WeatherRisk:
    if settings.offline_mode:
        return _simulated_weather(zone, "offline-mode")
    if not settings.has_openweather_key():
        return _simulated_weather(zone, "no_key")

    live, reason = _fetch_openweather(zone, settings)
    if live is not None:
        return live
    return _simulated_weather(zone, reason or "network")