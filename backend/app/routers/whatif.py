from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.scoring_core import get_fusion_weights, set_fusion_weights
from app.services.allocation_service import allocate_resources, allocation_summary, reset_resources
from app.services.routing_service import plan_search
from app.routers.hazard import hazard_priority_zones

router = APIRouter(prefix="/whatif", tags=["whatif"])

class WhatIfRequest(BaseModel):
    cv: Optional[float] = None
    sensor: Optional[float] = None
    gis: Optional[float] = None
    num_drones: int = 3
    num_teams: int = 2
    blocked_edges: Optional[list] = None
    max_distance_km: float = 60.0
    rainfall_multiplier: float = 1.0
    horizon_hours: int = 6
    predicted_weight: Optional[float] = None

@router.post("")
async def whatif(req: WhatIfRequest) -> dict:
    """S2-5 + Stage 3D: weights/resources/blocked/rainfall → risk, ranking, routes, allocation together."""
    import time
    s = time.perf_counter()
    old = get_fusion_weights()
    try:
        if req.cv is not None or req.sensor is not None or req.gis is not None:
            set_fusion_weights(req.cv, req.sensor, req.gis)
        from app.scoring_core import set_predicted_weight
        if req.predicted_weight is not None:
            set_predicted_weight(req.predicted_weight)
        zones = await hazard_priority_zones()
        ranking = [{"id": z.id, "name": z.name, "score": z.score, "severity": z.severity.value} for z in zones.zones]
        from app.services.risk_service import risk_grid as _rg, predicted_zones as _pz
        risk = _rg("ml", req.rainfall_multiplier, req.horizon_hours)
        predicted = _pz("ml", req.rainfall_multiplier, req.horizon_hours)
        search = plan_search(num_drones=max(1, req.num_drones), max_distance_km=req.max_distance_km, max_zones=6)
        reset_resources()
        assigns = allocate_resources(num_drones=req.num_drones, num_teams=req.num_teams) if (req.num_drones + req.num_teams) > 0 else []
        summ = allocation_summary(assigns, total_zones=zones.total_zones)
        reset_resources()
        kpis = {"zones": zones.total_zones, "critical": zones.critical_count, "high": zones.high_count, "coverage_pct": search["coverage_pct"], "unserved": summ["unserved_zones"], "utilisation_pct": summ["utilisation_pct"], "area_at_risk_km2": risk["summary"]["area_at_risk_km2"], "people_exposed": risk["summary"]["people_exposed"], "mean_risk": risk["summary"]["mean_risk"]}
        return {"weights": get_fusion_weights(), "ranking": ranking, "risk": {"mean_risk": risk["summary"]["mean_risk"], "high_cells": risk["summary"]["high_cells"], "area_at_risk_km2": risk["summary"]["area_at_risk_km2"]}, "predicted_top": predicted["zones"][:3], "routes": search, "allocation": {"assignments": [a.__dict__ for a in assigns], **summ}, "kpis": kpis, "blocked_edges": req.blocked_edges or [], "processing_ms": round((time.perf_counter() - s) * 1000, 1), "source": "simulated-whatif+prediction"}
    finally:
        set_fusion_weights(old["cv"], old["sensor"], old["gis"])
