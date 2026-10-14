"""Deterministic synthetic geospatial model over the Bengaluru AOI.

This supplies the terrain data that the real stack would source from SRTM/GloFAS,
WorldPop and OpenStreetMap. Every value is reproducible from a fixed seed so the
demo is stable across restarts, and live Open-Meteo/GloFAS readings can be folded
in on top (see grid_service / openmeteo_service).

This is demonstration data — not authoritative for operational decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians

import numpy as np

# AOI bounding box (Bengaluru).
LAT_MIN, LAT_MAX = 12.79, 13.14
LNG_MIN, LNG_MAX = 77.44, 77.78

GRID_ROWS = 14
GRID_COLS = 16

SEED = 20261013


@dataclass(frozen=True)
class Segment:
    lat1: float
    lng1: float
    lat2: float
    lng2: float


@dataclass(frozen=True)
class Shelter:
    id: str
    name: str
    lat: float
    lng: float
    capacity: int


# Synthetic shelters standing in for OpenStreetMap amenity=shelter/hospital.
SHELTERS = [
    Shelter("shelter-chinnaswamy", "Chinnaswamy Stadium Shelter", 13.0209, 77.5990, 5000),
    Shelter("shelter-kanteerava", "Kanteerava Indoor Stadium", 12.9941, 77.5926, 4000),
    Shelter("shelter-base", "Koramangala Community Hall", 12.9352, 77.6245, 1500),
    Shelter("shelter-hebbal", "Hebbal Railway Platform", 13.0358, 77.5970, 2000),
    Shelter("shelter-whitefield", "Whitefield IT Choultry", 12.9698, 77.7499, 1200),
    Shelter("shelter-yelahanka", "Yelahanka Old Town Hall", 13.1007, 77.5963, 1800),
]

# Synthetic river network (Arkavathi / Vrishabhavathi stand-ins).
RIVERS = [
    Segment(12.8400, 77.4600, 12.9000, 77.5100),
    Segment(12.9000, 77.5100, 12.9700, 77.5200),
    Segment(12.9700, 77.5200, 13.0200, 77.5200),
    Segment(12.8300, 77.5200, 12.9000, 77.5800),
    Segment(12.9000, 77.5800, 12.9600, 77.6300),
    Segment(12.9600, 77.6300, 12.9600, 77.6900),  # Bellandur lake line
    Segment(12.9000, 77.6500, 12.9500, 77.7000),
    Segment(12.8800, 77.6000, 12.8800, 77.6800),
    Segment(13.0900, 77.5200, 13.1400, 77.5600),  # Yelahanka north line
]

# Road grid step used for the ground-search graph (~1.5 km spacing).
ROAD_STEP_LAT = 0.022
ROAD_STEP_LNG = 0.022

# Cells whose flood probability exceeds this are treated as impassable for
# ground rescue (a flooded road).
ROAD_CUTOFF = 0.42


def _gaussian(lat: float, lng: float, clat: float, clng: float, rlat: float, rlng: float) -> float:
    dlat = (lat - clat) / rlat
    dlng = (lng - clng) / rlng
    return np.exp(-(dlat**2 + dlng**2))


@dataclass
class Terrain:
    """Precomputed per-cell terrain features over the AOI grid."""

    lats: np.ndarray
    lngs: np.ndarray
    elevation: np.ndarray
    slope: np.ndarray
    distance_river: np.ndarray
    road_access: np.ndarray
    population: np.ndarray
    flood_factor: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape


_terrain_cache: Terrain | None = None


def terrain() -> Terrain:
    """Build (or return cached) per-cell terrain features."""
    global _terrain_cache
    if _terrain_cache is not None:
        return _terrain_cache

    rows, cols = GRID_ROWS, GRID_COLS
    lats = np.linspace(LAT_MAX, LAT_MIN, rows)
    lngs = np.linspace(LNG_MIN, LNG_MAX, cols)
    L, G = np.meshgrid(lats, lngs, indexing="ij")

    # --- Elevation (synthetic SRTM-style DEM in metres) ---------------------
    elev = np.full_like(L, 975.0)
    # A broad piedmont low near the city core dropping to ~885 m.
    elev -= 46.0 * _gaussian(G, L, 77.59, 12.97, 0.11, 0.15)
    # Deeper depression along the Bellandur corridor.
    elev -= 30.0 * _gaussian(G, L, 77.665, 12.935, 0.08, 0.055)
    # Koramangala / Vrishabhavathi valley basin.
    elev -= 16.0 * _gaussian(G, L, 77.60, 12.90, 0.06, 0.07)
    # Higher ground to the west (Magadi direction).
    elev += 58.0 * _gaussian(G, L, 77.44, 12.95, 0.10, 0.15)
    # Northern ridge toward Yelahanka / Devanahalli.
    elev += 46.0 * _gaussian(G, L, 77.60, 13.10, 0.15, 0.09)
    # West-northwest high (Doddaballapur edge).
    elev += 30.0 * _gaussian(G, L, 77.50, 13.12, 0.12, 0.08)
    # Eastern plateau toward the Whitefield tech corridor.
    elev += 34.0 * _gaussian(G, L, 77.74, 12.97, 0.06, 0.06)
    elev = np.clip(elev, 845.0, 1030.0)

    # --- Slope from DEM gradient (degrees) ----------------------------------
    dlat_m = (lats[1] - lats[0]) * 111320.0
    dlng_m = (lngs[1] - lngs[0]) * 111320.0 * cos(radians(12.96))
    grad_lat, grad_lng = np.gradient(elev, dlat_m, dlng_m)
    slope = np.degrees(np.arctan2(np.hypot(grad_lat, grad_lng), 1.0))

    # --- Distance to nearest river segment (km) -----------------------------
    dist_km = np.full(L.shape, np.inf)
    for r in RIVERS:
        d = _dist_to_segment_km(L, G, r)
        dist_km = np.minimum(dist_km, d)

    # --- Road access (share of immediate neighbourhood connected to grid) ---
    road = _road_access_field(L, G)

    # --- Population density (WorldPop-style, centred on dense blocs) --------
    pop = np.full_like(L, 0.10)
    pop += 0.95 * _gaussian(G, L, 77.5713, 12.9767, 0.06, 0.05)  # Majestic core
    pop += 0.85 * _gaussian(G, L, 77.6245, 12.9352, 0.05, 0.06)  # Koramangala
    pop += 0.55 * _gaussian(G, L, 77.6602, 12.8452, 0.07, 0.08)  # Electronic City
    pop += 0.70 * _gaussian(G, L, 77.7499, 12.9698, 0.05, 0.07)  # Whitefield
    pop += 0.50 * _gaussian(G, L, 77.5970, 13.0358, 0.05, 0.06)  # Hebbal
    pop += 0.40 * _gaussian(G, L, 77.5963, 13.1007, 0.06, 0.05)  # Yelahanka
    pop = np.clip(pop, 0.05, 1.0)

    _terrain_cache = Terrain(
        lats=lats,
        lngs=lngs,
        elevation=elev,
        slope=slope,
        distance_river=dist_km,
        road_access=road,
        population=pop,
        flood_factor=np.zeros(elev.shape),
    )
    return _terrain_cache


def _dist_to_segment_km(L: np.ndarray, G: np.ndarray, seg: Segment) -> np.ndarray:
    """Great-circle-ish distance from every grid cell to a lat/lng segment."""
    lat1_r, lng1_r = radians(seg.lat1), radians(seg.lng1)
    lat2_r, lng2_r = radians(seg.lat2), radians(seg.lng2)

    # Local equirectangular projection (fine for a ~40 km AOI).
    mx0, my0 = seg.lng1 * 111.0 * cos(radians(12.96)), seg.lat1 * 111.0
    mx1, my1 = seg.lng2 * 111.0 * cos(radians(12.96)), seg.lat2 * 111.0
    gx = G * 111.0 * cos(radians(12.96))
    ly = L * 111.0

    dx, dy = mx1 - mx0, my1 - my0
    length2 = dx * dx + dy * dy
    t = np.where(length2 > 0, ((gx - mx0) * dx + (ly - my0) * dy) / length2, 0.0)
    t = np.clip(t, 0.0, 1.0)
    px = mx0 + t * dx
    py = my0 + t * dy
    return np.hypot(gx - px, ly - py)  # km


def _road_access_field(L: np.ndarray, G: np.ndarray) -> np.ndarray:
    """Road coverage proxy: dense road network near the core, sparse on edges.

    Returns 0..1 where near 1 means well-served by the road network.
    """
    core = _gaussian(G, L, 77.60, 12.97, 0.22, 0.16)
    access = 0.45 + 0.55 * core
    # Remove access where terrain is genuinely disconnected (deep low ground).
    access = np.clip(access, 0.30, 1.0)
    return access


def cell_center(idx: tuple[int, int]) -> tuple[float, float]:
    """Return the (lat, lng) centre of a grid cell."""
    t = terrain()
    return float(t.lats[idx[0]]), float(t.lngs[idx[1]])


def cell_bounds(idx: tuple[int, int]) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lng, max_lng) of a grid cell."""
    t = terrain()
    r, c = idx
    half_lat = (LAT_MAX - LAT_MIN) / (2 * GRID_ROWS)
    half_lng = (LNG_MAX - LNG_MIN) / (2 * GRID_COLS)
    return (
        t.lats[r] - half_lat,
        t.lats[r] + half_lat,
        t.lngs[c] - half_lng,
        t.lngs[c] + half_lng,
    )


def nearest_road_node(lat: float, lng: float) -> tuple[float, float]:
    """Snap an arbitrary coordinate to the closest road-graph node."""
    nlat = round((lat - LAT_MIN) / ROAD_STEP_LAT)
    nlng = round((lng - LNG_MIN) / ROAD_STEP_LNG)
    nlat = int(np.clip(nlat, 0, int((LAT_MAX - LAT_MIN) / ROAD_STEP_LAT)))
    nlng = int(np.clip(nlng, 0, int((LNG_MAX - LNG_MIN) / ROAD_STEP_LNG)))
    return round(LAT_MIN + nlat * ROAD_STEP_LAT, 6), round(LNG_MIN + nlng * ROAD_STEP_LNG, 6)


def road_graph() -> tuple[list[tuple[float, float]], list[tuple[int, int, float]]]:
    """Build a lattice road graph over the AOI.

    Returns (nodes, edges) where edges are (a, b, cost_km). Flooded midpoints
    get a strong penalty so the router prefers dry roads.
    """
    t = terrain()
    lat_vals = np.arange(LAT_MIN, LAT_MAX + 1e-9, ROAD_STEP_LAT)
    lng_vals = np.arange(LNG_MIN, LNG_MAX + 1e-9, ROAD_STEP_LNG)
    nodes: list[tuple[float, float]] = []
    index: dict[tuple[int, int], int] = {}
    for r, la in enumerate(lat_vals):
        for c, lo in enumerate(lng_vals):
            index[(r, c)] = len(nodes)
            nodes.append((round(la, 6), round(lo, 6)))

    edges: list[tuple[int, int, float]] = []
    for r, la in enumerate(lat_vals):
        for c, lo in enumerate(lng_vals):
            row_idx = np.argmin(np.abs(t.lats - la))
            col_idx = np.argmin(np.abs(t.lngs - lo))
            node_flood = float(t.flood_factor[row_idx, col_idx])
            penalty = 1.0 if node_flood < ROAD_CUTOFF else 40.0
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = r + dr, c + dc
                if (nr, nc) not in index:
                    continue
                nla, nlo = lat_vals[nr], lng_vals[nc]
                dist = abs(la - nla) * 111.0 + abs(lo - nlo) * 111.0 * cos(radians(12.96))
                mid_flood = float(
                    t.flood_factor[
                        np.argmin(np.abs(t.lats - (la + nla) / 2)),
                        np.argmin(np.abs(t.lngs - (lo + nlo) / 2)),
                    ]
                )
                edge_penalty = 1.0 if mid_flood < ROAD_CUTOFF else 40.0
                edges.append((index[(r, c)], index[(nr, nc)], round(dist * max(penalty, edge_penalty), 3)))

    return nodes, edges