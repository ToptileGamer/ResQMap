from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.models import PriorityZonesResponse, PriorityZone, SummaryDashboardResponse
from app.scoring import compute_hazard_severity
from app.scoring_core import get_fusion_weights, set_fusion_weights
from pydantic import BaseModel
from typing import Optional
from app.services.data_store import get_store
from app.services.gis_layer_service import layer
from app.services.sensor_service import get_sensor_service

router = APIRouter(prefix="/hazard", tags=["hazard"])

GIS_LAYER_SUBS = {
    "rivers": "rivers",
    "elevation": "elevation",
    "population": "population_density",
}

# Panel defaults for the ranked Priority Zones view.
PANEL_DEFAULT_LIMIT = 24
PANEL_MAX_LIMIT = 100


def _reason_line(z: PriorityZone) -> str:
    """Build the concise per-zone reasons string shown in the panel."""
    return "; ".join(
        [
            f"Aerial (CV) damage score {z.cv_flood_pct:.1f}/100",
            f"Sensor-derived risk {round(z.score, 1)}/100 ({z.sensor_alerts} alert(s) nearby)",
            f"GIS-proximity risk {round(z.score, 1)}/100",
            *z.gis_risk_factors,
        ]
    )


def _top_zones_html(zones: list[PriorityZone], limit: int = PANEL_DEFAULT_LIMIT) -> str:
    rows = []
    for i, z in enumerate(zones[:limit], 1):
        rows.append(
            f"""<tr style="border-bottom:1px solid #1a2537">
                <td style="padding:8px 10px">{i}</td>
                <td style="padding:8px 10px"><strong>{z.name}</strong></td>
                <td style="padding:8px 10px"><span class="badge c-{z.severity.value}">{z.severity.value}</span></td>
                <td style="padding:8px 10px">{z.score}</td>
                <td style="padding:8px 10px">{z.sensor_alerts}</td>
                <td style="padding:8px 10px; font-size:12px; color:#9fb0c9">
                    {_reason_line(z)}
                </td>
            </tr>"""
        )
    body = "\n".join(rows) or "<tr><td colspan='6' style='padding:8px 10px'>No zones</td></tr>"
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hazard Severity — Priority Zones</title>
<style>
  body {{ background:#070b13; color:#e7edf7; font-family:Inter,-apple-system,sans-serif; padding:24px; }}
  h1 {{ font-size:18px; margin:0 0 6px; letter-spacing:-0.01em; }}
  .sub {{ color:#9fb0c9; margin:0 0 18px; font-size:13px; }}
  table {{ border-collapse:collapse; width:100%; max-width:980px; }}
  th {{ text-align:left; padding:8px 10px; color:#9fb0c9; font-size:12px; text-transform:uppercase; letter-spacing:0.04em; border-bottom:1px solid #223049; }}
  td {{ vertical-align:top; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }}
  .c-Critical {{ background:#ff3b5c22; color:#ff3b5c; }}
  .c-High {{ background:#ffd23f22; color:#ffd23f; }}
  .c-Medium {{ background:#4aa8ff22; color:#4aa8ff; }}
  .c-Low {{ background:#39d98a22; color:#39d98a; }}
  .footer {{ margin-top:18px; color:#6d7f99; font-size:12px; }}
</style>
</head>
<body>
  <h1>Hazard Severity — Priority Zones</h1>
  <p class="sub">CV result + sensor reading + GIS proximity (rivers, low elevation, population) · {len(zones)} zones · top {limit} shown · generated {datetime.now(timezone.utc).isoformat()}</p>
  <table>
    <thead>
      <tr>
        <th style="width:34px">#</th>
        <th>Zone</th>
        <th style="width:90px">Severity</th>
        <th style="width:70px">Score</th>
        <th style="width:70px">Alerts</th>
        <th>Reasons</th>
      </tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
  <p class="footer">Sources: aerial damage (CV), live sensor alerts within search radius, GeoJSON river/elevation/population layers. Simulated demonstration data.</p>
</body>
</html>
"""


@router.get("/zones", response_model=PriorityZonesResponse)
async def hazard_priority_zones(sensor_radius_km: float = 4.0) -> PriorityZonesResponse:
    """Compute hazard severity for every zone from CV + sensor + GIS inputs.

    This endpoint is the primary surface for the "Hazard Severity Scoring"
    feature: it folds aerial (CV) damage results, nearby sensor alerts, and
    GIS-proximity risk (river/drain, low elevation, population density) into a
    single 0..100 hazard score per zone, then returns zones ranked by severity.
    """
    store = get_store()
    zones = store.list_zones()
    sensor_service = get_sensor_service()

    stations = sensor_service.get_all_stations()
    readings = sensor_service.get_latest_readings()

    gis = {key: layer(sub) for key, sub in GIS_LAYER_SUBS.items()}

    zones_out: list[PriorityZone] = []
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
    critical_count = sum(1 for z in zones_out if z.severity == "Critical")
    high_count = sum(1 for z in zones_out if z.severity == "High")

    return PriorityZonesResponse(
        zones=zones_out,
        total_zones=len(zones_out),
        critical_count=critical_count,
        high_count=high_count,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/zones.html")
async def hazard_priority_zones_html(
    sensor_radius_km: float = 4.0,
    limit: int = PANEL_DEFAULT_LIMIT,
) -> str:
    """Human-readable ranked panel: top N zones with reasons.

    Query params:
        sensor_radius_km — search radius around each zone for nearby sensors.
        limit            — number of top zones to render (default {PANEL_DEFAULT_LIMIT}, max {PANEL_MAX_LIMIT}).
    """
    if not (1 <= limit <= PANEL_MAX_LIMIT):
        limit = PANEL_DEFAULT_LIMIT

    resp = await hazard_priority_zones(sensor_radius_km=sensor_radius_km)
    return _top_zones_html(resp.zones, limit=limit)


class FusionWeightsRequest(BaseModel):
    cv: Optional[float] = None
    sensor: Optional[float] = None
    gis: Optional[float] = None


@router.get("/weights")
async def get_weights() -> dict:
    """Current fusion weights (S2-1 configurable). Labelled simulated defaults."""
    return {"weights": get_fusion_weights(), "source": "simulated-defaults", "note": "POST to update; scores re-rank on next call"}


@router.post("/weights")
async def update_weights(req: FusionWeightsRequest) -> dict:
    """Update fusion weights; normalised to sum 1.0. Changing weights re-ranks zones."""
    try:
        w = set_fusion_weights(req.cv, req.sensor, req.gis)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    return {"weights": w, "source": "user-configured"}


@router.get("/summary", response_model=PriorityZonesResponse)
async def hazard_summary() -> PriorityZonesResponse:
    """Shorthand for the dashboard: current hazard-priority snapshot."""
    return await hazard_priority_zones()


@router.get("/dashboard", response_model=SummaryDashboardResponse)
async def hazard_dashboard(sensor_radius_km: float = 4.0) -> SummaryDashboardResponse:
    """Enhanced summary dashboard for the hazard view.

    Exposes affected area, zones count, people/assets at risk, sensors in alert,
    and critical/high zone counts.
    """
    zones_resp = await hazard_priority_zones(sensor_radius_km=sensor_radius_km)
    zones = zones_resp.zones

    # Affected area: sum of per-zone area_km2 across all zones.
    affected_area_km2 = round(sum(z.area_km2 for z in zones), 2)

    # People at risk: sum of per-zone population_at_risk.
    people_at_risk = sum(z.population_at_risk for z in zones)

    # Assets at risk: a proxy from population_at_risk plus high-severity zones.
    asset_base = sum(z.population_at_risk for z in zones)
    asset_extras = int(
        sum(
            (100.0 if z.severity == "Critical" else (50.0 if z.severity == "High" else 0.0))
            + z.score * 1.2
            for z in zones
        )
    )
    assets_at_risk = asset_base + asset_extras

    # Sensors in alert: count of unique sensor readings currently in alert.
    sensor_service = get_sensor_service()
    alerts = sensor_service.get_alerts()
    sensors_in_alert = len({r.sensor_id for r in alerts})

    # Sensor alert breakdown by type
    alert_breakdown = {}
    for r in alerts:
        if r.alert_level != "normal":
            alert_breakdown[r.sensor_type.value] = alert_breakdown.get(r.sensor_type.value, 0) + 1

    # Severity distribution
    severity_dist = {
        "Critical": zones_resp.critical_count,
        "High": zones_resp.high_count,
        "Medium": sum(1 for z in zones if z.severity.value == "Medium"),
        "Low": sum(1 for z in zones if z.severity.value == "Low"),
    }

    # Top risk factors across all zones
    all_reasons = []
    for z in zones:
        all_reasons.extend(z.reasons)
    reason_counts = {}
    for r in all_reasons:
        key = r.split("(")[0].strip() if "(" in r else r[:50]
        reason_counts[key] = reason_counts.get(key, 0) + 1
    top_factors = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return SummaryDashboardResponse(
        affected_area_km2=affected_area_km2,
        zones_count=zones_resp.total_zones,
        people_at_risk=people_at_risk,
        assets_at_risk=assets_at_risk,
        sensors_in_alert=sensors_in_alert,
        critical_zones=zones_resp.critical_count,
        high_zones=zones_resp.high_count,
        generated_at=zones_resp.generated_at,
        # Enhanced fields (optional in model)
        alert_breakdown=alert_breakdown,
        severity_distribution=severity_dist,
        top_risk_factors=[{"factor": k, "count": v} for k, v in top_factors],
    )


@router.get("/priority-zones")
async def priority_zones_combined(
    include_predicted: bool = False,
    predicted_weight: float | None = None,
    predicted_model: str = "ml",
    rainfall_multiplier: float = 1.0,
    horizon_hours: int = 6,
) -> dict:
    """Stage 3D: current damage + predicted risk combined (weight adjustable)."""
    import time
    from fastapi import Query
    s = time.perf_counter()
    from app.scoring_core import combined_priority, get_predicted_weight, set_predicted_weight, hazard_severity_from_score
    if predicted_weight is not None:
        set_predicted_weight(predicted_weight)
    pw = get_predicted_weight() if include_predicted else 0.0
    zones_resp = await hazard_priority_zones()
    pred_map = {}
    if include_predicted:
        from app.services.risk_service import predicted_zones as _pz
        pz = _pz(predicted_model, rainfall_multiplier, horizon_hours)
        pred_map = {z["zone_id"]: z for z in pz["zones"]}
    out = []
    for z in zones_resp.zones:
        pp = float(pred_map.get(z.id, {}).get("probability", 0.0)) if pred_map else 0.0
        combined = combined_priority(z.score, pp, pw if include_predicted else 0.0)
        out.append({"id": z.id, "name": z.name, "latitude": z.latitude, "longitude": z.longitude, "current_score": z.score, "current_severity": z.severity.value, "predicted_probability": pp, "combined_score": combined, "combined_severity": hazard_severity_from_score(combined).value, "reasons": z.reasons, "population_at_risk": z.population_at_risk})
    out.sort(key=lambda x: x["combined_score"], reverse=True)
    return {"include_predicted": include_predicted, "predicted_weight": pw, "predicted_model": predicted_model, "zones": out, "processing_ms": round((time.perf_counter() - s) * 1000, 1), "generated_at": zones_resp.generated_at.isoformat() if hasattr(zones_resp.generated_at, "isoformat") else str(zones_resp.generated_at)}


@router.post("/predicted-weight")
async def set_pw(body: dict) -> dict:
    from app.scoring_core import set_predicted_weight
    w = set_predicted_weight(float(body.get("weight", 0.25)))
    return {"predicted_weight": w}
