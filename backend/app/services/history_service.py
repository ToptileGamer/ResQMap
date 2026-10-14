from __future__ import annotations

import zlib
from datetime import datetime, timedelta, timezone

import numpy as np

from app.models import DisasterZone, HistoryPoint, HistoryResponse


def _seed(zone: DisasterZone) -> int:
    return zlib.crc32(zone.id.encode("utf-8")) & 0xFFFFFFFF


def _simulated_history(zone: DisasterZone) -> HistoryResponse:
    """Deterministic 7-day rolling history derived from the zone's severity."""
    rng = np.random.default_rng(_seed(zone))
    now = datetime.now(timezone.utc)
    base = zone.base_weather_risk
    points: list[HistoryPoint] = []

    for step in range(28):
        t = now - timedelta(hours=6 * (27 - step))
        phase = 0.5 + 0.5 * np.sin(step / 4.0 + _seed(zone) % 7)
        rainfall = float(np.clip(base * 0.45 * phase + rng.normal(2, 6), 0, 90))
        water_level = float(np.clip(
            32 + 0.45 * rainfall + zone.flood_severity * 0.22 + rng.normal(0, 4), 0, 100
        ))
        points.append(
            HistoryPoint(
                timestamp=t,
                rainfall_mm=round(rainfall, 1),
                water_level=round(water_level, 1),
            )
        )

    return HistoryResponse(
        zone_id=zone.id,
        points=points,
        source="simulated",
        generated_at=now,
    )


def get_history(zone: DisasterZone) -> HistoryResponse:
    return _simulated_history(zone)