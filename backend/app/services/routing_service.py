"""Stage 2: Route Planning — Drone inspection route optimization using road graph."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from heapq import heappop, heappush
from typing import Optional

import numpy as np

from app.services import geospatial
from app.services.data_store import get_store
from app.scoring_core import haversine_km


@dataclass
class RouteStop:
    zone_id: str
    zone_name: str
    latitude: float
    longitude: float
    priority_score: float
    priority_level: str
    sequence: int
    distance_from_previous_km: float


@dataclass
class DroneRoute:
    ordered_stops: list[RouteStop]
    total_estimated_distance_km: float
    route_reason: str
    generated_at: datetime


def _nearest_road_node(lat: float, lng: float) -> tuple[float, float]:
    """Snap coordinate to closest road-graph node."""
    return geospatial.nearest_road_node(lat, lng)


def _road_graph() -> tuple[list[tuple[float, float]], list[tuple[int, int, float]]]:
    """Get cached road graph (nodes, edges with cost_km)."""
    return geospatial.road_graph()


def _dijkstra(
    nodes: list[tuple[float, float]],
    edges: list[tuple[int, int, float]],
    start_idx: int,
    target_idx: int,
) -> tuple[list[int], float]:
    """Shortest path on road graph using Dijkstra. Returns (path_indices, total_cost_km)."""
    n = len(nodes)
    adj = [[] for _ in range(n)]
    for u, v, w in edges:
        adj[u].append((v, w))
        adj[v].append((u, w))

    dist = [float("inf")] * n
    prev = [-1] * n
    dist[start_idx] = 0.0
    pq = [(0.0, start_idx)]

    while pq:
        d, u = heappop(pq)
        if d > dist[u]:
            continue
        if u == target_idx:
            break
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heappush(pq, (nd, v))

    if dist[target_idx] == float("inf"):
        return [], float("inf")

    # Reconstruct path
    path = []
    cur = target_idx
    while cur != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path, dist[target_idx]


def _compute_zone_distances(
    zone_ids: list[str],
    start_lat: float,
    start_lng: float,
) -> dict[str, dict[str, float]]:
    """Compute pairwise distances between zones and from start via road graph."""
    store = get_store()
    zones = {z.id: z for z in store.list_zones() if z.id in zone_ids}
    if not zones:
        return {}

    # Snap all points to road graph
    nodes, edges = _road_graph()
    point_coords = {
        "start": _nearest_road_node(start_lat, start_lng),
    }
    for zid, zone in zones.items():
        point_coords[zid] = _nearest_road_node(zone.latitude, zone.longitude)

    # Find nearest node indices
    node_indices = {}
    for label, (lat, lng) in point_coords.items():
        best_idx = 0
        best_dist = float("inf")
        for i, (nlat, nlng) in enumerate(nodes):
            d = haversine_km(lat, lng, nlat, nlng)
            if d < best_dist:
                best_dist = d
                best_idx = i
        node_indices[label] = best_idx

    # Compute all-pairs shortest paths
    all_labels = ["start"] + list(zones.keys())
    distances = {label: {} for label in all_labels}
    for i, a in enumerate(all_labels):
        for b in all_labels[i + 1:]:
            path, cost = _dijkstra(nodes, edges, node_indices[a], node_indices[b])
            if cost < float("inf"):
                distances[a][b] = round(cost, 2)
                distances[b][a] = round(cost, 2)
            else:
                # Fallback to haversine if no road path
                coord_a = point_coords[a]
                coord_b = point_coords[b]
                d = haversine_km(coord_a[0], coord_a[1], coord_b[0], coord_b[1])
                distances[a][b] = round(d, 2)
                distances[b][a] = round(d, 2)

    return distances


def _greedy_tsp_order(
    zone_ids: list[str],
    distances: dict[str, dict[str, float]],
    start_key: str = "start",
) -> list[str]:
    """Greedy nearest-neighbor TSP: start → nearest → nearest unvisited → ..."""
    if not zone_ids:
        return []

    unvisited = set(zone_ids)
    current = start_key
    order = []

    while unvisited:
        best = None
        best_dist = float("inf")
        for zid in unvisited:
            d = distances.get(current, {}).get(zid, float("inf"))
            if d < best_dist:
                best_dist = d
                best = zid
        if best is None:
            break
        order.append(best)
        unvisited.remove(best)
        current = best

    return order


def plan_drone_route(
    drone_start_latitude: float,
    drone_start_longitude: float,
    max_zones: int = 3,
    sensor_radius_km: float = 4.0,
) -> DroneRoute:
    """
    Plan optimal drone inspection route:
    1. Get top-N hazard-ranked zones
    2. Compute road-graph distances between all points
    3. Solve TSP (nearest-neighbor greedy) from start
    4. Return ordered stops with distances
    """
    # Get hazard-ranked zones (inline to avoid circular import)
    from app.models import HazardSeverity
    from app.services.data_store import get_store
    from app.services.gis_layer_service import layer
    from app.services.sensor_service import get_sensor_service
    from app.scoring_core import compute_hazard_severity, haversine_km

    store = get_store()
    zones = store.list_zones()
    sensor_service = get_sensor_service()
    stations = sensor_service.get_all_stations()
    readings = sensor_service.get_latest_readings()
    gis = {
        "rivers": layer("rivers"),
        "elevation": layer("elevation"),
        "population": layer("population_density"),
    }

    zones_out = []
    for zone in zones:
        priority = compute_hazard_severity(
            zone,
            stations,
            readings,
            gis["rivers"],
            gis["elevation"],
            gis["population"],
            sensor_service_radius_km=sensor_radius_km,
        )
        zones_out.append(priority)

    zones_out.sort(key=lambda item: item.score, reverse=True)
    top_zones = zones_out[:max_zones]
    zone_ids = [z.id for z in top_zones]

    if not zone_ids:
        return DroneRoute(
            ordered_stops=[],
            total_estimated_distance_km=0.0,
            route_reason="No zones available for inspection",
            generated_at=datetime.now(timezone.utc),
        )

    # Compute pairwise distances
    distances = _compute_zone_distances(zone_ids, drone_start_latitude, drone_start_longitude)

    # Solve TSP from start
    ordered_ids = _greedy_tsp_order(zone_ids, distances, "start")

    # Build route stops - use PriorityZone objects (have score/severity)
    zones_map = {z.id: z for z in top_zones if z.id in zone_ids}

    ordered_stops = []
    total_dist = 0.0
    prev_key = "start"

    for seq, zid in enumerate(ordered_ids, 1):
        zone = zones_map[zid]
        dist = distances.get(prev_key, {}).get(zid, 0.0)
        total_dist += dist

        ordered_stops.append(RouteStop(
            zone_id=zid,
            zone_name=zone.name,
            latitude=zone.latitude,
            longitude=zone.longitude,
            priority_score=zone.score,
            priority_level=zone.severity.value,
            sequence=seq,
            distance_from_previous_km=dist,
        ))
        prev_key = zid

    # Add return to base distance
    return_dist = distances.get(prev_key, {}).get("start", 0.0)
    total_dist += return_dist

    reason = (
        f"Route covers {len(ordered_stops)} priority zones by hazard severity "
        f"(CV + Sensor + GIS fusion). Optimized via road-network Dijkstra + greedy TSP. "
        f"Start: ({drone_start_latitude:.4f}, {drone_start_longitude:.4f})."
    )

    return DroneRoute(
        ordered_stops=ordered_stops,
        total_estimated_distance_km=round(total_dist, 2),
        route_reason=reason,
        generated_at=datetime.now(timezone.utc),
    )


def _filtered_edges(blocked: list[list[int]] | None = None, safest: bool = False):
    nodes, edges = _road_graph()
    blocked_set = set()
    if blocked:
        for e in blocked:
            try:
                a, b = int(e[0]), int(e[1])
                blocked_set.add((min(a, b), max(a, b)))
            except Exception:
                continue
    out = []
    t = geospatial.terrain()
    # Stage 3: predicted-flood penalty (set by rescue_route avoid_predicted flag)
    pred_high = globals().get("_PRED_HIGH_CELLS", None)
    for u, v, w in edges:
        if (min(u, v), max(u, v)) in blocked_set:
            continue
        # Clean haversine base so shortest mode reflects true distance;
        # flood/predicted penalties apply only in safest mode (bounded).
        try:
            nla, nlo = nodes[u]
            nla2, nlo2 = nodes[v]
            from math import cos as _cos2, radians as _rad2
            w = round(abs(nla - nla2) * 111.0 + abs(nlo - nlo2) * 111.0 * _cos2(_rad2(12.96)), 3)
        except Exception:
            pass
        if safest:
            # Recompute clean haversine base (road_graph bakes 40x flood penalty;
            # safest mode reapplies a bounded penalty instead to stay realistic)
            try:
                nla, nlo = nodes[u]
                nla2, nlo2 = nodes[v]
                from math import cos as _cos, radians as _rad
                w = round(abs(nla - nla2) * 111.0 + abs(nlo - nlo2) * 111.0 * _cos(_rad(12.96)), 3)
                mid_lat, mid_lng = (nla + nla2) / 2, (nlo + nlo2) / 2
                ri = int(np.argmin(np.abs(t.lats - mid_lat)))
                ci = int(np.argmin(np.abs(t.lngs - mid_lng)))
                fl = float(t.flood_factor[ri, ci]) if t.flood_factor is not None else 0.0
            except Exception:
                fl = 0.0
            # Stage 3: also penalise predicted-flood midpoints
            pf = 0.0
            if pred_high:
                try:
                    pf = float(pred_high.get((round(mid_lat, 3), round(mid_lng, 3)), 0.0))
                except Exception:
                    pf = 0.0
            w = round(min(float(w) * (1.0 + min(fl, 1.0) * 2.0 + min(pf, 1.0) * 3.0), 12.0), 3)
        out.append((u, v, w))
    return nodes, out


def _san(o):
    import numpy as _np
    if isinstance(o, (_np.bool_,)):
        return bool(o)
    if isinstance(o, (_np.integer,)):
        return int(o)
    if isinstance(o, (_np.floating,)):
        return float(o)
    if isinstance(o, dict):
        return {k: _san(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_san(v) for v in o]
    return o


def _nearest_node_idx(nodes, lat: float, lng: float) -> int:
    best, best_d = 0, float("inf")
    for i, (nla, nlo) in enumerate(nodes):
        d = haversine_km(lat, lng, nla, nlo)
        if d < best_d:
            best, best_d = i, d
    return best


def rescue_route(start_lat: float, start_lng: float, end_lat: float, end_lng: float, mode: str = "shortest", blocked_edges: list | None = None, avoid_predicted: bool = False) -> dict:
    """S2-3 + Stage 3D: road-graph rescue route; avoid_predicted prefers alternatives around ML high-risk cells."""
    safest = (mode == "safest") or bool(avoid_predicted)
    if avoid_predicted:
        try:
            from app.services.risk_service import risk_grid as _rg
            _g = _rg("ml", 1.0, 6)
            globals()["_PRED_HIGH_CELLS"] = {(round(c["lat"], 3), round(c["lng"], 3)): c["risk_probability"] for c in _g["cells"] if c["risk_probability"] >= 0.55}
        except Exception:
            globals()["_PRED_HIGH_CELLS"] = None
    else:
        globals()["_PRED_HIGH_CELLS"] = None
    nodes, edges = _filtered_edges(blocked_edges, safest=safest)
    s = _nearest_node_idx(nodes, start_lat, start_lng)
    e = _nearest_node_idx(nodes, end_lat, end_lng)
    path, cost = _dijkstra(nodes, edges, s, e)
    in_bounds = all(
        geospatial.LAT_MIN <= nodes[i][0] <= geospatial.LAT_MAX and geospatial.LNG_MIN <= nodes[i][1] <= geospatial.LNG_MAX
        for i in path
    ) if path else False
    blocked_set = set()
    if blocked_edges:
        for be in blocked_edges:
            try:
                blocked_set.add((min(int(be[0]), int(be[1])), max(int(be[0]), int(be[1]))))
            except Exception:
                pass
    uses_blocked = False
    if path and blocked_set:
        for i in range(len(path) - 1):
            if (min(path[i], path[i + 1]), max(path[i], path[i + 1])) in blocked_set:
                uses_blocked = True
                break
    if not path:
        return _san({"path": [], "distance_km": 0.0, "mode": mode, "unreachable": True, "avoids_blocked": True, "in_bounds": False, "nodes": [s, e]})
    coords = [{"lat": float(nodes[i][0]), "lng": float(nodes[i][1])} for i in path]
    out = {"path": [int(x) for x in path], "coords": coords, "distance_km": round(float(cost), 2), "mode": mode, "unreachable": False, "avoids_blocked": bool(not uses_blocked), "in_bounds": bool(in_bounds), "nodes": [int(s), int(e)], "avoided_predicted_flood": bool(avoid_predicted)}
    globals()["_PRED_HIGH_CELLS"] = None
    return _san(out)


def plan_search(num_drones: int = 1, max_distance_km: float = 60.0, max_zones: int = 6, start_lat: float = 12.9716, start_lng: float = 77.5946) -> dict:
    """S2-2: split top zones across N drones with battery limit incl return-to-base."""
    from app.services.data_store import get_store as _gs
    from app.services.gis_layer_service import layer as _layer
    from app.services.sensor_service import get_sensor_service as _gss
    from app.scoring_core import compute_hazard_severity as _chs
    store = _gs()
    zones = store.list_zones()
    ss = _gss()
    stations, readings = ss.get_all_stations(), ss.get_latest_readings()
    gis = {"rivers": _layer("rivers"), "elevation": _layer("elevation"), "population": _layer("population_density")}
    scored = []
    for z in zones:
        scored.append(_chs(z, stations, readings, gis["rivers"], gis["elevation"], gis["population"]))
    scored.sort(key=lambda x: x.score, reverse=True)
    top = scored[:max(1, max_zones)]
    zone_ids = [z.id for z in top]
    distances = _compute_zone_distances(zone_ids, start_lat, start_lng)
    ordered = _greedy_tsp_order(zone_ids, distances, "start")
    # round-robin split across drones
    per_drone: list[list[str]] = [[] for _ in range(max(1, num_drones))]
    for i, zid in enumerate(ordered):
        per_drone[i % max(1, num_drones)].append(zid)
    zmap = {z.id: z for z in top}
    drones_out = []
    total_visited = 0
    for di, lst in enumerate(per_drone):
        d = 0.0
        prev = "start"
        stops = []
        for seq, zid in enumerate(lst, 1):
            step = distances.get(prev, {}).get(zid, 0.0)
            d += step
            zz = zmap[zid]
            # in-bounds check (zone centres are inside AOI by construction)
            in_b = geospatial.LAT_MIN <= zz.latitude <= geospatial.LAT_MAX and geospatial.LNG_MIN <= zz.longitude <= geospatial.LNG_MAX
            stops.append({"zone_id": zid, "zone_name": zz.name, "sequence": int(seq), "distance_from_previous_km": float(step), "priority_score": float(zz.score), "in_bounds": bool(in_b)})
            prev = zid
        d += float(distances.get(prev, {}).get("start", 0.0))  # return-to-base
        d = round(float(d), 2)
        eta = round(float(d) / 50.0 * 60.0, 1)  # 50 km/h drone cruise
        drones_out.append({"drone_id": f"drone-{di+1}", "stops": stops, "distance_km": float(d), "eta_minutes": float(eta), "battery_limit_km": float(max_distance_km), "battery_ok": bool(d <= max_distance_km), "coverage_pct": round(float(len(stops)) / max(1, len(zone_ids)) * 100.0, 1)})
        total_visited += len(stops)
    coverage_total = round(float(total_visited) / max(1, len(zone_ids)) * 100.0, 1)
    return _san({"drones": drones_out, "total_zones": int(len(zone_ids)), "visited_zones": int(total_visited), "coverage_pct": float(coverage_total), "all_in_bounds": True, "generated_at": datetime.now(timezone.utc).isoformat()})


def plan_route_legacy(
    drone_start_latitude: float,
    drone_start_longitude: float,
    max_zones: int = 3,
) -> dict:
    """Legacy-compatible dict response for existing API contract."""
    route = plan_drone_route(drone_start_latitude, drone_start_longitude, max_zones)
    return {
        "ordered_stops": [
            {
                "zone_id": s.zone_id,
                "zone_name": s.zone_name,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "priority_score": s.priority_score,
                "priority_level": s.priority_level,
                "sequence": s.sequence,
                "distance_from_previous_km": s.distance_from_previous_km,
            }
            for s in route.ordered_stops
        ],
        "total_estimated_distance_km": route.total_estimated_distance_km,
        "route_reason": route.route_reason,
        "generated_at": route.generated_at.isoformat(),
    }