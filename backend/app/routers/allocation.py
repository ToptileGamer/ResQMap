from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from fastapi.responses import Response
from app.services.allocation_service import (
    allocate_resources,
    allocation_csv,
    allocation_summary,
    get_resource_status,
    reset_resources,
    upsert_drone,
    upsert_team,
    Assignment,
)

router = APIRouter(prefix="/allocation", tags=["allocation"])


class AllocationRequest(BaseModel):
    num_drones: int = 3
    num_teams: int = 2
    sensor_radius_km: float = 4.0


class AllocationResponse(BaseModel):
    assignments: List[dict]
    total_resources: int
    deployed_drones: int
    deployed_teams: int
    generated_at: str


class ResourceStatusResponse(BaseModel):
    drones: List[dict]
    teams: List[dict]
    generated_at: str


@router.post("/assign", response_model=AllocationResponse)
async def assign_resources(req: AllocationRequest) -> AllocationResponse:
    """Assign drones and teams to priority zones based on hazard severity."""
    assignments = allocate_resources(
        num_drones=req.num_drones,
        num_teams=req.num_teams,
        sensor_radius_km=req.sensor_radius_km,
    )
    
    return AllocationResponse(
        assignments=[a.__dict__ for a in assignments],
        total_resources=len(assignments),
        deployed_drones=sum(1 for a in assignments if a.resource_type == "drone"),
        deployed_teams=sum(1 for a in assignments if a.resource_type == "team"),
        generated_at=assignments[0].assigned_at.isoformat() if assignments else datetime.now(timezone.utc).isoformat(),
    )


@router.get("/status", response_model=ResourceStatusResponse)
async def resource_status() -> ResourceStatusResponse:
    """Get current status of all drones and teams."""
    status = get_resource_status()
    return ResourceStatusResponse(
        drones=status["drones"],
        teams=status["teams"],
        generated_at=status["generated_at"].isoformat(),
    )


@router.post("/reset")
async def reset_allocation() -> dict:
    """Reset all resources to available (for demo/testing)."""
    reset_resources()
    return {"message": "All resources reset to available"}


@router.post("/resources/drone")
async def edit_drone(body: dict) -> dict:
    """S2-4: create or update a drone (editable resources, labelled simulated)."""
    d = upsert_drone(body)
    return {"id": d.id, "name": d.name, "capacity_zones": d.capacity_zones, "status": d.status, "source": "simulated-editable"}


@router.post("/resources/team")
async def edit_team(body: dict) -> dict:
    """S2-4: create or update a team (editable resources)."""
    t = upsert_team(body)
    return {"id": t.id, "name": t.name, "capacity_zones": t.capacity_zones, "status": t.status, "source": "simulated-editable"}


@router.get("/summary")
async def allocation_summary_view(
    num_drones: int = Query(default=3, ge=0, le=10),
    num_teams: int = Query(default=2, ge=0, le=10),
) -> dict:
    """S2-4: allocation with utilisation %, unserved demand, quantity. Zero → clean empty."""
    reset_resources()
    if num_drones == 0 and num_teams == 0:
        s = allocation_summary([], total_zones=8)
        return {**s, "note": "zero resources → clean empty result"}
    assignments = allocate_resources(num_drones=num_drones, num_teams=num_teams)
    s = allocation_summary(assignments, total_zones=8)
    reset_resources()
    return {"assignments": [a.__dict__ for a in assignments], **s}


@router.get("/export.csv")
async def allocation_export_csv(
    num_drones: int = Query(default=3, ge=0, le=10),
    num_teams: int = Query(default=2, ge=0, le=10),
) -> Response:
    """S2-6: CSV allocation export."""
    reset_resources()
    assignments = allocate_resources(num_drones=num_drones, num_teams=num_teams) if (num_drones + num_teams) > 0 else []
    csv_text = allocation_csv(assignments)
    reset_resources()
    return Response(content=csv_text, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="allocation.csv"'})


@router.get("/by-target")
async def allocation_by_target(
    target: str = Query(default="current"),
    num_drones: int = Query(default=3, ge=0, le=10),
    num_teams: int = Query(default=2, ge=0, le=10),
    model: str = Query(default="ml"),
) -> dict:
    """Stage 3D: target=current|predicted|combined. Predicted pre-positions before flooding."""
    import time
    s = time.perf_counter()
    if target not in ("current", "predicted", "combined"):
        raise HTTPException(status_code=400, detail="target must be current|predicted|combined")
    reset_resources()
    if target == "current":
        assigns = allocate_resources(num_drones=num_drones, num_teams=num_teams) if (num_drones + num_teams) > 0 else []
        order_note = "current damage ranking"
    else:
        from app.services.risk_service import predicted_zones as _pz
        from app.services.allocation_service import DEFAULT_DRONES, DEFAULT_TEAMS, haversine_km, estimate_eta, Assignment
        from datetime import datetime, timezone as _tz
        pz = _pz(model, 1.0, 6)
        ranked = pz["zones"] if target == "predicted" else None
        if target == "combined":
            # combined = average of hazard score and predicted prob*100
            from app.routers.hazard import hazard_priority_zones
            hz = await hazard_priority_zones()
            hmap = {z.id: z.score for z in hz.zones}
            ranked = sorted(pz["zones"], key=lambda x: (hmap.get(x["zone_id"], 0) + x["probability"] * 100) / 2, reverse=True)
        assigns = []
        drones = [d for d in DEFAULT_DRONES][:num_drones]
        teams = [t for t in DEFAULT_TEAMS][:num_teams]
        used = set()
        for z in (ranked or []):
            if len([a for a in assigns if a.resource_type == "drone"]) < len(drones):
                d = drones[len([a for a in assigns if a.resource_type == "drone"])]
                dist = haversine_km(d.base_lat, d.base_lng, z["latitude"], z["longitude"])
                assigns.append(Assignment(d.id, "drone", d.name, z["zone_id"], z["zone_name"], z["probability"] * 100, "Predicted", dist, estimate_eta(dist, "drone"), datetime.now(_tz.utc)))
                used.add(z["zone_id"])
            elif len([a for a in assigns if a.resource_type == "team"]) < len(teams):
                # next unserved predicted zone
                rem = [x for x in (ranked or []) if x["zone_id"] not in used]
                if not rem:
                    break
                z2 = rem[0]
                t = teams[len([a for a in assigns if a.resource_type == "team"])]
                dist = haversine_km(t.base_lat, t.base_lng, z2["latitude"], z2["longitude"])
                assigns.append(Assignment(t.id, "team", t.name, z2["zone_id"], z2["zone_name"], z2["probability"] * 100, "Predicted", dist, estimate_eta(dist, t.type), datetime.now(_tz.utc)))
                used.add(z2["zone_id"])
            if len(assigns) >= num_drones + num_teams:
                break
        order_note = f"{target} ranking (predicted pre-positioning)"
    summ = allocation_summary(assigns, total_zones=8)
    reset_resources()
    return {"target": target, "order": order_note, "assignments": [a.__dict__ for a in assigns], **summ, "processing_ms": round((time.perf_counter() - s) * 1000, 1)}


@router.get("/suggest")
async def suggest_allocation(
    num_drones: int = Query(default=3, ge=1, le=10),
    num_teams: int = Query(default=2, ge=1, le=10),
    sensor_radius_km: float = Query(default=4.0, ge=1.0, le=20.0),
) -> AllocationResponse:
    """Get suggested allocation without actually assigning (preview)."""
    assignments = allocate_resources(
        num_drones=num_drones,
        num_teams=num_teams,
        sensor_radius_km=sensor_radius_km,
    )
    
    return AllocationResponse(
        assignments=[a.__dict__ for a in assignments],
        total_resources=len(assignments),
        deployed_drones=sum(1 for a in assignments if a.resource_type == "drone"),
        deployed_teams=sum(1 for a in assignments if a.resource_type == "team"),
        generated_at=assignments[0].assigned_at.isoformat() if assignments else datetime.now(timezone.utc).isoformat(),
    )


# Need datetime for fallback
from datetime import datetime, timezone