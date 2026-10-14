"""Deterministic GeoJSON layer service for the Bengaluru AOI.

This is demonstration data built from the same synthetic terrain model the rest
of the stack uses. It stands in for real SRTM / OSM / WorldPop / administrative
source data and is not authoritative for life-critical decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
from shapely import GeometryCollection, LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from app.services.geospatial import (
    LAT_MAX,
    LAT_MIN,
    LNG_MAX,
    LNG_MIN,
    GRID_COLS,
    GRID_ROWS,
    RIVERS,
    SHELTERS,
    Terrain,
    _gaussian,
    cell_bounds,
    terrain,
)

BOUNDS: dict[str, float] = {
    "min_lat": LAT_MIN,
    "max_lat": LAT_MAX,
    "min_lng": LNG_MIN,
    "max_lng": LNG_MAX,
}

_ADMIN_COLORS = {
    "Karnataka": "#2b8cbe",
    "Bengaluru Urban": "#fdae61",
    "Bengaluru City": "#d94800",
    "Ward Zone A": "#5e4fa2",
    "Ward Zone B": "#3288bd",
    "Ward Zone C": "#66c2a5",
    "Ward Zone D": "#abdda4",
}


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": features,
        "generated_by": "resqmap-gis-layer-service",
    }


def _poly(
    ring_latlng: list[tuple[float, float]],
    props: dict[str, Any],
    geom_type: str = "Polygon",
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": geom_type, "coordinates": [list(ring_latlng)]},
        "properties": props,
    }


def _as_list(geom: Any) -> list[Any]:
    if geom is None:
        return []
    if geom.geom_type == "MultiPolygon":
        return [list(geom.geoms)]
    if geom.geom_type == "GeometryCollection":
        out: list[Any] = []
        for g in geom.geoms:
            if g.geom_type == "MultiPolygon":
                out.append(list(g.geoms))
            elif g.geom_type == "Polygon":
                out.append([list(g.exterior.coords)])
        return out
    if geom.geom_type == "Polygon":
        return [list(geom.exterior.coords)]
    return []


def _bbox(geom: Polygon | MultiPolygon | GeometryCollection) -> list[float]:
    if geom.geom_type == "GeometryCollection":
        xs, ys = [], []
        for g in geom.geoms:
            if g.geom_type in ("Polygon", "MultiPolygon"):
                x, y = g.exterior.coords.xy
                xs.extend(x)
                ys.extend(y)
        if xs:
            return [min(ys), min(xs), max(ys), max(xs)]
        return []
    x, y = geom.exterior.coords.xy if geom.geom_type == "Polygon" else geom.geoms[0].exterior.coords.xy
    xs = list(x)
    ys = list(y)
    return [min(ys), min(xs), max(ys), max(xs)]


def _quad_idx_to_polygons() -> list[Polygon]:
    """Tile the AOI into a quadtree-ish admin patchwork so boundaries exist."""
    rows, cols = GRID_ROWS, GRID_COLS
    polys: list[Polygon] = []
    for r in range(rows):
        for c in range(cols):
            min_lat, max_lat, min_lng, max_lng = cell_bounds((r, c))
            polys.append(
                Polygon(
                    [
                        (min_lng, min_lat),
                        (max_lng, min_lat),
                        (max_lng, max_lat),
                        (min_lng, max_lat),
                        (min_lng, min_lat),
                    ]
                )
            )
    return polys


def _admin_boundary_polys() -> list[Polygon]:
    """Fake nested administrative boundaries: state -> district -> city -> wards."""
    core = Polygon(
        [
            (77.50, 12.84),
            (77.78, 12.84),
            (77.78, 13.14),
            (77.50, 13.14),
            (77.50, 12.84),
        ]
    )
    # Bengaluru Urban district (slightly inset from state edge).
    district = Polygon(
        [
            (77.52, 12.86),
            (77.76, 12.86),
            (77.76, 13.12),
            (77.52, 13.12),
            (77.52, 12.86),
        ]
    )
    # Bengaluru city (core metro).
    city = Polygon(
        [
            (77.54, 12.90),
            (77.74, 12.90),
            (77.74, 13.10),
            (77.54, 13.10),
            (77.54, 12.90),
        ]
    )
    # Ward patches (rough concentric rings around the Majestic core).
    wards: list[Polygon] = []
    cx, cy = 77.62, 12.99
    for ring, name in enumerate(["Ward Zone A", "Ward Zone B", "Ward Zone C", "Ward Zone D"], start=1):
        r = 0.04 * ring + 0.02
        ward = Polygon(
            [
                (cx - r, cy - r),
                (cx + r, cy - r),
                (cx + r, cy + r),
                (cx - r, cy + r),
                (cx - r, cy - r),
            ]
        )
        wards.append(ward)
    return [core, district, city, *wards]


def admin_boundaries() -> dict[str, Any]:
    """Nested administrative boundaries: state, district, city, wards."""
    polys = _admin_boundary_polys()
    labels = ["Karnataka", "Bengaluru Urban", "Bengaluru City", "Ward Zone A", "Ward Zone B", "Ward Zone C", "Ward Zone D"]
    features: list[dict[str, Any]] = []
    for poly, label in zip(polys, labels):
        coords = list(poly.exterior.coords)
        features.append(
            _poly(
                coords,
                {
                    "name": label,
                    "level": labels.index(label),
                    "type": "administrative",
                    "source": "simulated",
                },
            )
        )
    return _feature_collection(features)


def rivers() -> dict[str, Any]:
    """River / drain network as MultiLineString GeoJSON."""
    lines: list[LineString] = []
    for seg in RIVERS:
        lines.append(LineString([(seg.lng1, seg.lat1), (seg.lng2, seg.lat2)]))
    geom = LineString()
    if lines:
        geom = unary_union(lines) if len(lines) > 1 else lines[0]
    elif isinstance(geom, LineString):
        geom = geom
    else:
        geom = LineString()
    coords: list[list[list[float]]] = []
    if geom.geom_type == "MultiLineString":
        coords = [list(ln.coords) for ln in geom.geoms]
    elif geom.geom_type == "LineString":
        coords = [list(geom.coords)]
    features: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        features.append(
            _poly(
                list(ln.coords),
                {
                    "name": _river_name_for_segment(i),
                    "type": "river",
                    "length_km": _seg_length_km(ln),
                    "source": "simulated",
                },
                geom_type="LineString",
            )
        )
    return _feature_collection(features)


def _river_name_for_segment(idx: int) -> str:
    names = [
        "Arkavathi (simulated)",
        "Arkavathi middle reach",
        "Arkavathi to lake corridor",
        "Vrishabhavathi north",
        "Vrishabhavathi middle",
        "Bellandur lake outflow",
        "Koramangala drain",
        "Hebbal channel",
        "Yelahanka north drain",
    ]
    return names[idx] if idx < len(names) else f"Drain segment {idx+1}"


def _seg_length_km(ln: LineString) -> float:
    c = np.array(ln.coords)
    if len(c) < 2:
        return 0.0
    dx = (c[1:, 0] - c[:-1, 0]) * 111.0 * np.cos(np.radians(12.96))
    dy = (c[1:, 1] - c[:-1, 1]) * 111.0
    return float(np.sum(np.hypot(dx, dy)))


def roads() -> dict[str, Any]:
    """Road network as a lattice of primary/secondary roads over the AOI."""
    from app.services.geospatial import ROAD_STEP_LAT, ROAD_STEP_LNG, nearest_road_node

    nodes: list[tuple[float, float]] = []
    index: dict[tuple[int, int], int] = {}
    lat_vals = np.arange(LAT_MIN, LAT_MAX + 1e-9, ROAD_STEP_LAT)
    lng_vals = np.arange(LNG_MIN, LNG_MAX + 1e-9, ROAD_STEP_LNG)
    for r, la in enumerate(lat_vals):
        for c, lo in enumerate(lng_vals):
            index[(r, c)] = len(nodes)
            nodes.append((round(float(la), 6), round(float(lo), 6)))

    features: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    def _edge(a: int, b: int, kind: str) -> None:
        if (a, b) in seen or (b, a) in seen:
            return
        seen.add((a, b))
        p1, p2 = nodes[a], nodes[b]
        features.append(
            _poly(
                [p1, p2],
                {
                    "name": f"Road {a}-{b}",
                    "type": kind,
                    "length_km": _great_circle_km(p1, p2),
                    "source": "simulated",
                },
                geom_type="LineString",
            )
        )

    for idx, (r, c) in enumerate(index):
        la, lo = nodes[idx]
        # Primary roads every 3 nodes, secondary otherwise.
        kind_lat = "primary" if r % 3 == 0 else "secondary"
        kind_lng = "primary" if c % 3 == 0 else "secondary"
        if (r + 1, c) in index:
            _edge(idx, index[(r + 1, c)], kind_lat)
        if (r, c + 1) in index:
            _edge(idx, index[(r, c + 1)], kind_lng)

    return _feature_collection(features)


def _great_circle_km(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    dx = abs(p1[0] - p2[0]) * 111.0 * np.cos(np.radians(12.96))
    dy = abs(p1[1] - p2[1]) * 111.0
    return float(np.hypot(dx, dy))


def elevation_dem() -> dict[str, Any]:
    """Raster elevation as a floating-point grid encoded as a single polygon
    per cell with elevation value as a property (raster-as-vector demo)."""
    t = terrain()
    features: list[dict[str, Any]] = []
    for r in range(t.elevation.shape[0]):
        for c in range(t.elevation.shape[1]):
            min_lat, max_lat, min_lng, max_lng = cell_bounds((r, c))
            elev = float(t.elevation[r, c])
            features.append(
                _poly(
                    [
                        (min_lng, min_lat),
                        (max_lng, min_lat),
                        (max_lng, max_lat),
                        (min_lng, max_lat),
                        (min_lng, min_lat),
                    ],
                    {
                        "elevation_m": round(elev, 1),
                        "slope_deg": round(float(t.slope[r, c]), 2),
                        "source": "simulated SRTM-style",
                    },
                )
            )
    return _feature_collection(features)


def low_lying_areas() -> dict[str, Any]:
    """Cells below an elevation threshold merged into flooded-prone polygons."""
    t = terrain()
    threshold = 935.0  # metres — below this is low-lying in this AOI's range.
    polys: list[Polygon] = []
    for r in range(t.elevation.shape[0]):
        for c in range(t.elevation.shape[1]):
            if float(t.elevation[r, c]) <= threshold:
                min_lat, max_lat, min_lng, max_lng = cell_bounds((r, c))
                polys.append(
                    Polygon(
                        [
                            (min_lng, min_lat),
                            (max_lng, min_lat),
                            (max_lng, max_lat),
                            (min_lng, max_lat),
                            (min_lng, min_lat),
                        ]
                    )
                )
    if not polys:
        return _feature_collection([])
    merged = unary_union(polys)
    features: list[dict[str, Any]] = []
    if merged.geom_type == "Polygon":
        merged_polys = [merged]
    elif merged.geom_type == "MultiPolygon":
        merged_polys = list(merged.geoms)
    else:
        merged_polys = []
    for mp in merged_polys:
        coords = list(mp.exterior.coords)
        features.append(
            _poly(
                coords,
                {
                    "name": "Low-lying area",
                    "elevation_threshold_m": threshold,
                    "area_km2": round(_polygon_area_km2(mp), 3),
                    "flood_risk": "high",
                    "source": "simulated",
                },
            )
        )
    return _feature_collection(features)


def _polygon_area_km2(poly: Polygon) -> float:
    x, y = poly.exterior.coords.xy
    xs = np.array(x)
    ys = np.array(y)
    # Approximate area using local equirectangular scaling.
    dx = np.diff(xs) * 111.0 * np.cos(np.radians(12.96))
    dy = np.diff(ys) * 111.0
    # shoelace on scaled coords
    x2 = np.append(xs[:-1] * dx, 0)
    area = 0.5 * np.abs(np.sum(x2 * np.roll(ys, -1) - x2 * ys))
    return float(area)


def shelters() -> dict[str, Any]:
    """Shelter points from the synthetic shelter dataset."""
    features: list[dict[str, Any]] = []
    for sh in SHELTERS:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [sh.lng, sh.lat]},
                "properties": {
                    "name": sh.name,
                    "id": sh.id,
                    "capacity": sh.capacity,
                    "type": "shelter",
                    "source": "simulated OSM amenity=shelter",
                },
            }
        )
    return _feature_collection(features)


def hospitals() -> dict[str, Any]:
    """Hospital points derived from shelters with high capacity and a couple of
    dedicated synthetic hospitals for the demo."""
    synthetic_hospitals = [
        {"id": "hospital-bangalore-medical", "name": "Bangalore Medical College", "lat": 12.9712, "lng": 77.6414, "capacity": 1200},
        {"id": "hospital-nimhans", "name": "NIMHANS Trauma Centre", "lat": 12.9365, "lng": 77.6081, "capacity": 800},
        {"id": "hospital-bsp", "name": "Bowring & Lady Curzon Hospital", "lat": 12.9752, "lng": 77.5643, "capacity": 650},
    ]
    features: list[dict[str, Any]] = []
    for h in synthetic_hospitals:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [h["lng"], h["lat"]]},
                "properties": {
                    "name": h["name"],
                    "id": h["id"],
                    "capacity": h["capacity"],
                    "type": "hospital",
                    "source": "simulated OSM amenity=hospital",
                },
            }
        )
    # Also promote any shelter with capacity >= 2000 to a hospital-feature as a
    # triage centre stand-in, so the layer is not empty.
    for sh in SHELTERS:
        if sh.capacity >= 2000:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [sh.lng, sh.lat]},
                    "properties": {
                        "name": f"{sh.name} (Triage Centre)",
                        "id": f"triage-{sh.id}",
                        "capacity": sh.capacity,
                        "type": "hospital_triage",
                        "source": "simulated",
                    },
                }
            )
    return _feature_collection(features)


def population_density() -> dict[str, Any]:
    """WorldPop-style population density grid as a vectorised polygon layer."""
    t = terrain()
    features: list[dict[str, Any]] = []
    for r in range(t.population.shape[0]):
        for c in range(t.population.shape[1]):
            min_lat, max_lat, min_lng, max_lng = cell_bounds((r, c))
            density = float(t.population[r, c])
            # Headcount proxy: density scaled to cell area in km^2.
            cell_area_km2 = (max_lat - min_lat) * (max_lng - min_lng) * 111.0 * 111.0 * np.cos(np.radians(12.96))
            headcount = round(density * cell_area_km2 * 12000, 0)  # demographic scaling factor
            features.append(
                _poly(
                    [
                        (min_lng, min_lat),
                        (max_lng, min_lat),
                        (max_lng, max_lat),
                        (min_lng, max_lat),
                        (min_lng, min_lat),
                    ],
                    {
                        "density_index": round(density, 3),
                        "estimated_population": int(headcount),
                        "source": "simulated WorldPop-style",
                    },
                )
            )
    return _feature_collection(features)


_SERVICE: dict[str, Any] = {
    "admin_boundaries": admin_boundaries,
    "rivers": rivers,
    "roads": roads,
    "elevation": elevation_dem,
    "low_lying_areas": low_lying_areas,
    "shelters": shelters,
    "hospitals": hospitals,
    "population_density": population_density,
    # flood_hazard mirrors low-lying areas for the demo so it is never empty.
    "flood_hazard": low_lying_areas,
}


_CUSTOM_LAYERS: dict[str, dict[str, Any]] = {}


def set_custom_layer(layer_type: str, geojson: dict[str, Any]) -> None:
    _CUSTOM_LAYERS[layer_type] = geojson


def get_layer_source(layer_type: str) -> str:
    return "real-upload" if layer_type in _CUSTOM_LAYERS else "simulated"


def layer(layer_type: str) -> dict[str, Any]:
    if layer_type in _CUSTOM_LAYERS:
        return _CUSTOM_LAYERS[layer_type]
    builder = _SERVICE.get(layer_type)
    if builder is None:
        return _feature_collection([])
    return builder()


def bounds_for_layer(layer_type: str) -> dict[str, float]:
    return BOUNDS
