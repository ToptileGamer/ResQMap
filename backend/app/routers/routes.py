from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.routing_service import plan_route_legacy, plan_search, rescue_route
from typing import Optional

router = APIRouter(prefix="/routes", tags=["routes"])


class RouteRequest(BaseModel):
    drone_start_latitude: float
    drone_start_longitude: float
    max_zones: int = 3


class RouteStop(BaseModel):
    zone_id: str
    zone_name: str
    latitude: float
    longitude: float
    priority_score: float
    priority_level: str
    sequence: int
    distance_from_previous_km: float


class RouteResponse(BaseModel):
    ordered_stops: list[RouteStop]
    total_estimated_distance_km: float
    route_reason: str
    generated_at: str


@router.post("/drone", response_model=RouteResponse)
async def plan_drone_route(req: RouteRequest) -> RouteResponse:
    """
    Plan optimal drone inspection route visiting top priority zones.
    
    Uses hazard severity ranking (CV + Sensor + GIS fusion) to select zones,
    then computes road-network shortest paths (Dijkstra) and solves
    a greedy TSP for optimal visit order.
    """
    result = plan_route_legacy(
        drone_start_latitude=req.drone_start_latitude,
        drone_start_longitude=req.drone_start_longitude,
        max_zones=req.max_zones,
    )
    return result


@router.get("/drone", response_model=RouteResponse)
async def plan_drone_route_get(
    drone_start_latitude: float = Query(..., ge=-90, le=90),
    drone_start_longitude: float = Query(..., ge=-180, le=180),
    max_zones: int = Query(default=3, ge=1, le=10),
) -> RouteResponse:
    """GET variant for easier testing."""
    result = plan_route_legacy(
        drone_start_latitude=drone_start_latitude,
        drone_start_longitude=drone_start_longitude,
        max_zones=max_zones,
    )
    return result


class SearchRequest(BaseModel):
    num_drones: int = 1
    max_distance_km: float = 60.0
    max_zones: int = 6
    start_lat: float = 12.9716
    start_lng: float = 77.5946


@router.post("/search")
async def drone_search(req: SearchRequest) -> dict:
    """S2-2: coverage search split across N drones with battery limit incl return-to-base."""
    return plan_search(req.num_drones, req.max_distance_km, req.max_zones, req.start_lat, req.start_lng)


class RescueRequest(BaseModel):
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    mode: str = "shortest"
    blocked_edges: Optional[list] = None
    avoid_predicted: bool = False


@router.post("/rescue")
async def rescue(req: RescueRequest) -> dict:
    """S2-3 + Stage 3D: road-graph rescue; shortest vs safest; blocked avoided; unreachable flagged; avoid_predicted prefers alternatives."""
    if req.mode not in ("shortest", "safest"):
        raise HTTPException(status_code=400, detail="mode must be shortest|safest")
    return rescue_route(req.start_lat, req.start_lng, req.end_lat, req.end_lng, req.mode, req.blocked_edges, req.avoid_predicted)


@router.get("/rescue")
async def rescue_get(
    start_lat: float = Query(...), start_lng: float = Query(...),
    end_lat: float = Query(...), end_lng: float = Query(...),
    mode: str = Query(default="shortest"),
    avoid_predicted: bool = Query(default=False),
) -> dict:
    if mode not in ("shortest", "safest"):
        raise HTTPException(status_code=400, detail="mode must be shortest|safest")
    return rescue_route(start_lat, start_lng, end_lat, end_lng, mode, None, avoid_predicted)


@router.get("/search")
async def drone_search_get(
    num_drones: int = Query(default=1, ge=1, le=10),
    max_distance_km: float = Query(default=60.0, ge=1.0),
    max_zones: int = Query(default=6, ge=1, le=20),
) -> dict:
    return plan_search(num_drones, max_distance_km, max_zones)