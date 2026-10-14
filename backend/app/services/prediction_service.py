"""Stage 3: Predict — DEM-based water-spread simulation (optimized).

Given the current grid flood probability and the forecast rainfall accumulation,
we simulate how the water body spreads over the next 24h. Water moves downhill:
high cells flood later, low cells flood first, and cells one ring away from
existing water wet up as water rises (a simple priority-flood).

No trained booster is needed — this is an explainable DEM + rainfall model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

import numpy as np

from app.services import geospatial
from app.services.grid_service import compute_flood_probability
from app.services.openmeteo_service import get_rain_factors

# Time steps shown on the slider.
STEP_LABELS = [(0, "Now"), (6, "+6h"), (12, "+12h"), (24, "+24h")]

# Cells with flood_probability above this are "wet" at time zero.
WET_CUTOFF = 0.52

# Pre-computed cell bounds and GeoJSON geometry for fast reuse
_cell_geojson_cache: dict | None = None
_cell_polygons: np.ndarray | None = None


def _init_cell_geojson_cache():
    """Pre-compute cell polygons and properties for fast GeoJSON generation."""
    global _cell_geojson_cache, _cell_polygons
    if _cell_geojson_cache is not None:
        return

    t = geospatial.terrain()
    rows, cols = t.shape
    features = []
    polygons = np.empty((rows, cols), dtype=object)

    for r in range(rows):
        for c in range(cols):
            min_lat, max_lat, min_lng, max_lng = geospatial.cell_bounds((r, c))
            poly = {
                "type": "Polygon",
                "coordinates": [[
                    [min_lng, min_lat],
                    [max_lng, min_lat],
                    [max_lng, max_lat],
                    [min_lng, max_lat],
                    [min_lng, min_lat],
                ]],
            }
            polygons[r, c] = poly
            features.append({
                "type": "Feature",
                "geometry": poly,
                "properties": {
                    "id": f"cell-{r:02d}-{c:02d}",
                    "lat": round(float(t.lats[r]), 5),
                    "lng": round(float(t.lngs[c]), 5),
                    "elevation_m": round(float(t.elevation[r, c]), 1),
                    "slope_deg": round(float(t.slope[r, c]), 2),
                    "distance_river_km": round(float(t.distance_river[r, c]), 2),
                    "road_access": round(float(t.road_access[r, c]), 3),
                    "population_density": round(float(t.population[r, c]), 3),
                },
            })

    _cell_geojson_cache = {
        "type": "FeatureCollection",
        "features": features,
    }
    _cell_polygons = polygons


def _wet_extent(probs: np.ndarray) -> np.ndarray:
    """Cells currently wet plus neighbours one ring out (transition zone)."""
    wet = probs >= WET_CUTOFF
    return _dilate(wet, iterations=1)


def _dilate(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    """4-neighbour morphological dilation (no scipy dependency)."""
    out = mask.copy()
    for _ in range(iterations):
        padded = np.pad(out.astype(int), 1, mode="constant")
        grown = np.zeros_like(out)
        nrows, ncols = out.shape
        for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            grown |= padded[1 + dr: 1 + dr + nrows, 1 + dc: 1 + dc + ncols].astype(bool)
        out = grown
    return out


@lru_cache(maxsize=1)
def _get_base_flood_probability() -> np.ndarray:
    """Cached base flood probability (recomputes only when cache expires)."""
    rain_factor, _ = get_rain_factors()
    return compute_flood_probability(rain_factor)


def _spread_masks(base_flood: np.ndarray, steps_hours: list[int], rain_multiplier: float = 1.0) -> list[np.ndarray]:
    """Return the wet mask at each requested hour using vectorized operations."""
    _, hourly_accum = get_rain_factors()

    results = []
    base_wet = base_flood >= WET_CUTOFF

    for hours in steps_hours:
        if hours <= 0:
            results.append(_dilate(base_wet, iterations=1))
            continue

        # Accumulated rainfall up to this hour
        accum = float(sum(hourly_accum[:max(1, hours)]))
        rise = float(np.clip((base_flood.mean() * 0.12 + accum * 0.05) * rain_multiplier, 0.0, 0.30))

        # Water preferentially climbs to neighbours as rainfall accumulates
        dilation_iters = max(1, int(round(hours / 6)))
        grown = _dilate(base_wet, iterations=dilation_iters)

        # Threshold drops with rainfall, allowing more cells to flood
        wet = base_flood >= max(WET_CUTOFF - rise, 0.10)
        wet |= grown

        # Knock out genuinely high ground that cannot plausibly flood
        wet &= base_flood >= 0.10
        results.append(wet)

    return results


def spread_geometries(steps: list[int], rain_multiplier: float = 1.0) -> list[np.ndarray]:
    """Return the wet mask at each requested hour (cached base flood)."""
    base_flood = _get_base_flood_probability()
    return _spread_masks(base_flood, steps, rain_multiplier)


def prediction_for_zone(
    zone_id: str,
    rain_multiplier: float = 1.0,
    include_geojson: bool = False,
) -> dict:
    """Build the spread series for a given zone's location (or the whole AOI)."""
    from app.services.data_store import get_store

    store = get_store()
    zone = store.get_zone(zone_id)

    base_flood = _get_base_flood_probability()
    masks = _spread_masks(base_flood, [h for h, _ in STEP_LABELS], rain_multiplier)

    t = geospatial.terrain()
    total = t.elevation.size

    steps_out = []
    expansions = []

    if include_geojson:
        _init_cell_geojson_cache()

    for (hours, label), mask in zip(STEP_LABELS, masks):
        flooded_count = int(np.sum(mask))
        steps_out.append({
            "hours": hours,
            "label": label,
            "flooded_cells": flooded_count,
            "flood_extent_pct": round(float(flooded_count) / total * 100.0, 2),
        })

        if include_geojson and _cell_geojson_cache is not None:
            # Fast path: filter pre-computed features by wet mask
            wet_indices = np.where(mask.flatten())[0]
            features = [_cell_geojson_cache["features"][i] for i in wet_indices]
            # Update flood_probability in properties
            for idx, feat in zip(wet_indices, features):
                r, c = divmod(idx, t.shape[1])
                feat["properties"]["flood_probability"] = round(float(base_flood[r, c]), 3)
                feat["properties"]["labels"] = [label]

            expansions.append({
                "label": label,
                "geojson": {"type": "FeatureCollection", "features": features},
            })
        else:
            expansions.append({"label": label, "geojson": None})

    zone_name = zone.name if zone else zone_id
    zone_lat = zone.latitude if zone else (geospatial.LAT_MIN + (geospatial.LAT_MAX - geospatial.LAT_MIN) / 2)
    zone_lng = zone.longitude if zone else (geospatial.LNG_MIN + (geospatial.LNG_MAX - geospatial.LNG_MIN) / 2)

    return {
        "zone_id": zone_id,
        "zone_name": zone_name,
        "method": "DEM water-spread simulation (priority-flood, no trained booster)",
        "model": "synthetic-DEM + open-meteo rainfall",
        "rain_factor": round(float(get_rain_factors()[0]), 3),
        "steps": steps_out,
        "expansions": [exp["geojson"] for exp in expansions if exp["geojson"] is not None],
        "selected_lat": zone_lat,
        "selected_lng": zone_lng,
        "generated_at": datetime.now(timezone.utc),
    }