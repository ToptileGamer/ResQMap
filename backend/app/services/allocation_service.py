"""Stage 2: Resource Allocation — Assign drones/teams to priority zones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.models import PriorityZone
from app.services.data_store import get_store
from app.services.gis_layer_service import layer
from app.services.sensor_service import get_sensor_service
from app.scoring_core import compute_hazard_severity, haversine_km


@dataclass
class Drone:
    id: str
    name: str
    base_lat: float
    base_lng: float
    max_range_km: float = 30.0
    status: str = "available"  # available, deployed, charging, maintenance
    current_zone: Optional[str] = None
    eta_minutes: int = 0
    capacity_zones: int = 3
    assigned_count: int = 0


@dataclass
class Team:
    id: str
    name: str
    type: str  # ground, boat, helicopter
    base_lat: float
    base_lng: float
    max_range_km: float = 50.0
    status: str = "available"
    current_zone: Optional[str] = None
    eta_minutes: int = 0
    capacity_zones: int = 4
    assigned_count: int = 0


def upsert_drone(d: dict) -> Drone:
    for ex in DEFAULT_DRONES:
        if ex.id == d.get("id"):
            for k in ("name", "base_lat", "base_lng", "max_range_km", "status", "capacity_zones"):
                if k in d and d[k] is not None:
                    setattr(ex, k, d[k])
            return ex
    nd = Drone(d.get("id", f"drone-{len(DEFAULT_DRONES)+1:02d}"), d.get("name", "Custom drone"), float(d.get("base_lat", 12.97)), float(d.get("base_lng", 77.59)), float(d.get("max_range_km", 30.0)), d.get("status", "available"), None, 0, int(d.get("capacity_zones", 3)), 0)
    DEFAULT_DRONES.append(nd)
    return nd


def upsert_team(t: dict) -> Team:
    for ex in DEFAULT_TEAMS:
        if ex.id == t.get("id"):
            for k in ("name", "type", "base_lat", "base_lng", "max_range_km", "status", "capacity_zones"):
                if k in t and t[k] is not None:
                    setattr(ex, k, t[k])
            return ex
    nt = Team(t.get("id", f"team-{len(DEFAULT_TEAMS)+1:02d}"), t.get("name", "Custom team"), t.get("type", "ground"), float(t.get("base_lat", 12.97)), float(t.get("base_lng", 77.59)), float(t.get("max_range_km", 50.0)), t.get("status", "available"), None, 0, int(t.get("capacity_zones", 4)), 0)
    DEFAULT_TEAMS.append(nt)
    return nt


@dataclass
class Assignment:
    resource_id: str
    resource_type: str  # drone, team
    resource_name: str
    zone_id: str
    zone_name: str
    priority_score: float
    severity: str
    distance_km: float
    eta_minutes: int
    assigned_at: datetime


# Default drone fleet (simulated)
DEFAULT_DRONES = [
    Drone("drone-01", "DJI Matrice 300", 12.9716, 77.5946, 30.0),
    Drone("drone-02", "DJI Matrice 350", 12.9352, 77.6245, 35.0),
    Drone("drone-03", "DJI Mavic 3E", 12.9698, 77.7499, 25.0),
    Drone("drone-04", "senseFly eBee X", 13.0358, 77.5970, 40.0),
    Drone("drone-05", "Quantum Trinity F90+", 12.9063, 77.4827, 50.0),
]

# Default response teams (simulated)
DEFAULT_TEAMS = [
    Team("team-01", "Bangalore Fire Rescue", "ground", 12.9767, 77.5713, 40.0),
    Team("team-02", "Karnataka SDRF", "boat", 12.9352, 77.6245, 30.0),
    Team("team-03", "NDRF Battalion", "ground", 13.1007, 77.5963, 50.0),
    Team("team-04", "Air Force Helicopter", "helicopter", 12.9500, 77.6000, 100.0),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 2)


def estimate_eta(distance_km: float, resource_type: str) -> int:
    """Estimate ETA in minutes based on distance and resource type."""
    speeds = {
        "drone": 50.0,  # km/h
        "ground": 30.0,
        "boat": 15.0,
        "helicopter": 120.0,
    }
    speed = speeds.get(resource_type, 30.0)
    return max(5, int((distance_km / speed) * 60))


def _get_hazard_zones(sensor_radius_km: float = 4.0):
    """Compute hazard severity for all zones (inline to avoid circular import)."""
    from app.models import HazardSeverity
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
    return zones_out


def allocate_resources(
    num_drones: int = 3,
    num_teams: int = 2,
    sensor_radius_km: float = 4.0,
) -> list[Assignment]:
    """
    Greedy allocation: assign closest available resources to highest-priority zones.
    
    Strategy:
    1. Get hazard-ranked zones (CV + Sensor + GIS fusion)
    2. Sort zones by hazard score descending
    3. For each zone, find closest available drone/team
    4. Assign if within range and resource available
    """
    # Get hazard-ranked zones
    zones = _get_hazard_zones(sensor_radius_km=sensor_radius_km)
    
    # Filter to available resources
    available_drones = [d for d in DEFAULT_DRONES if d.status == "available"][:num_drones]
    available_teams = [t for t in DEFAULT_TEAMS if t.status == "available"][:num_teams]
    
    assignments: list[Assignment] = []
    assigned_zones: set[str] = set()
    
    # Assign drones to top zones
    for zone in zones:
        if len(assignments) >= num_drones + num_teams:
            break
            
        if zone.id in assigned_zones:
            continue
            
        # Find closest available drone (respect capacity)
        best_drone = None
        best_dist = float('inf')
        for drone in available_drones:
            if drone.assigned_count >= drone.capacity_zones:
                continue
            dist = haversine_km(drone.base_lat, drone.base_lng, zone.latitude, zone.longitude)
            if dist <= drone.max_range_km and dist < best_dist:
                best_dist = dist
                best_drone = drone
        
        if best_drone:
            eta = estimate_eta(best_dist, "drone")
            assignments.append(Assignment(
                resource_id=best_drone.id,
                resource_type="drone",
                resource_name=best_drone.name,
                zone_id=zone.id,
                zone_name=zone.name,
                priority_score=zone.score,
                severity=zone.severity.value,
                distance_km=best_dist,
                eta_minutes=eta,
                assigned_at=datetime.now(timezone.utc),
            ))
            best_drone.status = "deployed"
            best_drone.current_zone = zone.id
            best_drone.eta_minutes = eta
            best_drone.assigned_count += 1
            assigned_zones.add(zone.id)
    
    # Assign teams to next priority zones
    for zone in zones:
        if len(assignments) >= num_drones + num_teams:
            break
            
        if zone.id in assigned_zones:
            continue
            
        # Find closest available team (respect capacity)
        best_team = None
        best_dist = float('inf')
        for team in available_teams:
            if team.assigned_count >= team.capacity_zones:
                continue
            dist = haversine_km(team.base_lat, team.base_lng, zone.latitude, zone.longitude)
            if dist <= team.max_range_km and dist < best_dist:
                best_dist = dist
                best_team = team
        
        if best_team:
            eta = estimate_eta(best_dist, best_team.type)
            assignments.append(Assignment(
                resource_id=best_team.id,
                resource_type="team",
                resource_name=best_team.name,
                zone_id=zone.id,
                zone_name=zone.name,
                priority_score=zone.score,
                severity=zone.severity.value,
                distance_km=best_dist,
                eta_minutes=eta,
                assigned_at=datetime.now(timezone.utc),
            ))
            best_team.status = "deployed"
            best_team.current_zone = zone.id
            best_team.eta_minutes = eta
            best_team.assigned_count += 1
            assigned_zones.add(zone.id)

    return assignments


def allocation_summary(assignments: list, total_zones: int = 8) -> dict:
    """S2-4: utilisation %, unserved demand, quantity. Zero resources → clean empty."""
    if not assignments:
        return {"assignments": [], "total": 0, "unserved_zones": total_zones, "unserved_list": [], "utilisation_pct": 0.0, "quantity": {"drones": 0, "teams": 0}}
    served = {a.zone_id for a in assignments}
    from app.services.data_store import get_store as _gs2
    all_ids = [z.id for z in _gs2().list_zones()]
    unserved = [z for z in all_ids if z not in served]
    cap_total = sum(d.capacity_zones for d in DEFAULT_DRONES) + sum(t.capacity_zones for t in DEFAULT_TEAMS)
    util = round(len(assignments) / max(1, cap_total) * 100.0, 1)
    return {"total": len(assignments), "unserved_zones": len(unserved), "unserved_list": unserved, "utilisation_pct": util, "quantity": {"drones": sum(1 for a in assignments if a.resource_type == "drone"), "teams": sum(1 for a in assignments if a.resource_type == "team")}}


def get_resource_status() -> dict:
    """Get current status of all resources."""
    return {
        "drones": [
            {
                "id": d.id,
                "name": d.name,
                "base_lat": d.base_lat,
                "base_lng": d.base_lng,
                "max_range_km": d.max_range_km,
                "status": d.status,
                "current_zone": d.current_zone,
                "eta_minutes": d.eta_minutes,
                "capacity_zones": d.capacity_zones,
                "assigned_count": d.assigned_count,
            }
            for d in DEFAULT_DRONES
        ],
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "type": t.type,
                "base_lat": t.base_lat,
                "base_lng": t.base_lng,
                "max_range_km": t.max_range_km,
                "status": t.status,
                "current_zone": t.current_zone,
                "eta_minutes": t.eta_minutes,
                "capacity_zones": t.capacity_zones,
                "assigned_count": t.assigned_count,
            }
            for t in DEFAULT_TEAMS
        ],
        "generated_at": datetime.now(timezone.utc),
    }


def reset_resources() -> None:
    """Reset all resources to available (for demo/testing)."""
    for d in DEFAULT_DRONES:
        d.status = "available"
        d.current_zone = None
        d.eta_minutes = 0
        d.assigned_count = 0
    for t in DEFAULT_TEAMS:
        t.status = "available"
        t.current_zone = None
        t.eta_minutes = 0
        t.assigned_count = 0


def allocation_csv(assignments: list) -> str:
    import io, csv
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["resource_id", "resource_type", "resource_name", "zone_id", "zone_name", "priority_score", "severity", "distance_km", "eta_minutes"])
    for a in assignments:
        w.writerow([a.resource_id, a.resource_type, a.resource_name, a.zone_id, a.zone_name, a.priority_score, a.severity, a.distance_km, a.eta_minutes])
    return out.getvalue()