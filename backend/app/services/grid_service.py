"""Grid-cell flood-risk and priority model (Stage 2: Prioritise).

Computes, for every cell in the AOI grid:
    priority = flooded × population × vulnerability
where:
    flooded       <- DEM elevation + slope + distance to river + rainfall + zone reports
    population    <- WorldPop-style density field
    vulnerability <- low elevation / poor road access combined with density

The result is exposed both as a tabular summary and as GeoJSON for the map.

This is a transparent, explainable surrogate for an XGBoost/LightGBM grid model —
the same inputs would feed a trained booster in production.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from app.config import get_settings
from app.services import geospatial
from app.services.data_store import get_store
from app.services.openmeteo_service import get_rain_factors

WEIGHT_FLOOD = 1.0
WEIGHT_POPULATION = 1.0
WEIGHT_VULNERABILITY = 1.0

THRESHOLDS = ((0.72, "Critical"), (0.52, "High"), (0.32, "Moderate"))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def compute_flood_probability(rain_factor: float = 0.5) -> np.ndarray:
    """Return 0..1 flood probability per grid cell and cache it on the terrain."""
    t = geospatial.terrain()
    elev_norm = np.clip((t.elevation - 870.0) / (1000.0 - 870.0), 0.0, 1.0)
    river_norm = np.clip(t.distance_river / 8.0, 0.0, 1.0)
    slope_norm = np.clip(t.slope / 12.0, 0.0, 1.0)

    score = (
        (1.0 - elev_norm) * 1.3
        + (1.0 - river_norm) * 0.9
        + (1.0 - slope_norm) * 0.35
        + rain_factor * 0.55
        - 1.35
    )

    # Fold in reported flood severity from the zones (drone/field evidence).
    L, G = np.meshgrid(t.lats, t.lngs, indexing="ij")
    for zone in get_store().list_zones():
        sev = float(zone.flood_severity) / 100.0
        if sev < 0.05:
            continue
        score += sev * 1.1 * _gaussian(G, L, zone.longitude, zone.latitude, 0.06, 0.045)

    flood = sigmoid(score)
    flood = np.clip(flood, 0.0, 0.99)
    t.flood_factor = flood
    return flood


def _gaussian(lng: np.ndarray, lat: np.ndarray, clng: float, clat: float, rlng: float, rlat: float) -> np.ndarray:
    return np.exp(-(((lng - clng) / rlng) ** 2 + ((lat - clat) / rlat) ** 2))


def vulnerability() -> np.ndarray:
    """0..1 vulnerability = low ground + poor road access, emphasised near people."""
    t = geospatial.terrain()
    elev_norm = np.clip((t.elevation - 870.0) / (1000.0 - 870.0), 0.0, 1.0)
    low_ground = 1.0 - elev_norm
    poor_access = 1.0 - t.road_access
    return np.clip(0.55 * low_ground + 0.45 * poor_access, 0.0, 1.0) ** 1.1


def priority_grid(rain_factor: float | None = None) -> dict:
    """Produce the full grid summary plus GeoJSON FeatureCollection."""
    settings = get_settings()
    if rain_factor is None:
        rain_factor = get_rain_factors()[0]

    flood = compute_flood_probability(rain_factor)
    t = geospatial.terrain()
    vuln = vulnerability()
    pop = t.population

    priority = (flood * WEIGHT_FLOOD) * (pop * WEIGHT_POPULATION) * (vuln * WEIGHT_VULNERABILITY)
    priority = priority / (priority.max() + 1e-9) * 100.0  # rescale 0..100

    features = []
    rows = []
    for r in range(t.shape[0]):
        for c in range(t.shape[1]):
            cell_id = f"cell-{r:02d}-{c:02d}"
            lat, lng = t.lats[r], t.lngs[c]
            score = round(float(priority[r, c]), 1)
            level = _level(score)
            min_lat, max_lat, min_lng, max_lng = geospatial.cell_bounds((r, c))
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [min_lng, min_lat],
                        [max_lng, min_lat],
                        [max_lng, max_lat],
                        [min_lng, max_lat],
                        [min_lng, min_lat],
                    ]],
                },
                "properties": {
                    "id": cell_id,
                    "lat": round(lat, 5),
                    "lng": round(lng, 5),
                    "elevation_m": round(float(t.elevation[r, c]), 1),
                    "slope_deg": round(float(t.slope[r, c]), 2),
                    "distance_river_km": round(float(t.distance_river[r, c]), 2),
                    "road_access": round(float(t.road_access[r, c]), 3),
                    "flood_probability": round(float(flood[r, c]), 3),
                    "population_density": round(float(pop[r, c]), 3),
                    "vulnerability": round(float(vuln[r, c]), 3),
                    "priority_score": score,
                    "priority_level": level,
                },
            })
            rows.append({
                "id": cell_id,
                "lat": round(float(lat), 5),
                "lng": round(float(lng), 5),
                "elevation_m": round(float(t.elevation[r, c]), 1),
                "slope_deg": round(float(t.slope[r, c]), 2),
                "distance_river_km": round(float(t.distance_river[r, c]), 2),
                "flood_probability": round(float(flood[r, c]), 3),
                "population_density": round(float(pop[r, c]), 3),
                "vulnerability": round(float(vuln[r, c]), 3),
                "priority_score": score,
                "priority_level": level,
            })

    rows.sort(key=lambda item: item["priority_score"], reverse=True)
    priority_scores = np.asarray([row["priority_score"] for row in rows])
    total = len(rows)
    return {
        "bounds": {
            "min_lat": geospatial.LAT_MIN,
            "max_lat": geospatial.LAT_MAX,
            "min_lng": geospatial.LNG_MIN,
            "max_lng": geospatial.LNG_MAX,
        },
        "rain_factor": round(rain_factor, 3),
        "grid_shape": {"rows": geospatial.GRID_ROWS, "cols": geospatial.GRID_COLS},
        "cells": rows,
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
        "summary": {
            "total_cells": total,
            "cells_at_risk": int(np.sum(priority_scores > 30)),
            "critical_cells": int(np.sum(priority_scores >= THRESHOLDS[0][0] * 100 - 1e-9)),
            "top_priority": rows[:5] if rows else [],
        },
        "formula": "flood × population × vulnerability  (GPT surrogate, no trained booster)",
        "generated_at": datetime.now(timezone.utc),
    }


def _level(score: float) -> str:
    for threshold, level in THRESHOLDS:
        if score >= threshold * 100:
            return level
    return "Low"


def highest_priority_cells(limit: int = 24) -> list[dict]:
    """Return the top-priority cell rows, most urgent first."""
    grid = priority_grid()
    return grid["cells"][:limit]


def cells_over(threshold_score: float = 35.0) -> list[dict]:
    """Return cells with priority_score >= threshold."""
    grid = priority_grid()
    return [row for row in grid["cells"] if row["priority_score"] >= threshold_score]