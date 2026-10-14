"""S1+S2 automated checks (minimal, evidence-backed)."""
import sys
sys.path.insert(0, "backend")
from app.scoring_core import get_fusion_weights, set_fusion_weights, compute_hazard_severity
from app.services.data_store import get_store
from app.services.gis_layer_service import layer
from app.services.sensor_service import get_sensor_service, SensorService, SensorType
from app.services.routing_service import plan_search, rescue_route
from app.services.allocation_service import allocate_resources, allocation_summary, reset_resources

def test_cv_samples_differ():
    from app.services.imagery_service import analyze_zone_frame
    store = get_store()
    pcts = set()
    for zid in ["zone-koramangala", "zone-bellandur", "zone-whitefield"]:
        z = store.get_zone(zid)
        r, g = analyze_zone_frame.__wrapped__(z, None) if hasattr(analyze_zone_frame, "__wrapped__") else (None, None)
    # use service directly
    from app.services import imagery_service as im
    vals = []
    for zid in ["zone-koramangala", "zone-bellandur", "zone-whitefield"]:
        z = store.get_zone(zid)
        res, gj = im.analyze_zone_frame_with_geojson(z, None)
        assert gj["type"] == "FeatureCollection"
        vals.append(res.flood_affected_pct)
    assert len(set(vals)) >= 2, f"masks should differ: {vals}"

def test_sensor_thresholds():
    s = SensorService.__new__(SensorService)
    assert s._compute_alert_level(SensorType.RAINFALL, 5.0, 50.0, 100.0).value == "normal"
    assert s._compute_alert_level(SensorType.RAINFALL, 120.0, 50.0, 100.0).value == "critical"

def test_weights_rerank():
    old = get_fusion_weights()
    try:
        set_fusion_weights(0.8, 0.1, 0.1)
        w1 = get_fusion_weights()
        from app.routers.hazard import hazard_priority_zones
        import asyncio
        r1 = asyncio.run(hazard_priority_zones())
        set_fusion_weights(0.1, 0.1, 0.8)
        r2 = asyncio.run(hazard_priority_zones())
        assert [z.id for z in r1.zones] != [z.id for z in r2.zones] or [z.score for z in r1.zones] != [z.score for z in r2.zones]
    finally:
        set_fusion_weights(old["cv"], old["sensor"], old["gis"])

def test_search_bounds_battery():
    r1 = plan_search(num_drones=1, max_distance_km=500, max_zones=4)
    assert r1["coverage_pct"] == 100.0
    assert r1["all_in_bounds"] is True
    for d in r1["drones"]:
        assert d["battery_ok"] is True
        for s in d["stops"]:
            assert s["in_bounds"] is True
    r2 = plan_search(num_drones=3, max_distance_km=1, max_zones=6)
    assert any(d["battery_ok"] is False for d in r2["drones"])

def test_routing_blocked_and_unreachable():
    base = rescue_route(12.9716, 77.5946, 12.9352, 77.6245, "shortest", None)
    assert not base["unreachable"] and base["in_bounds"]
    assert len(base["path"]) >= 2
    blocked = [[base["path"][0], base["path"][1]]]
    alt = rescue_route(12.9716, 77.5946, 12.9352, 77.6245, "shortest", blocked)
    assert alt["avoids_blocked"] is True
    for i in range(len(alt["path"]) - 1):
        assert (min(alt["path"][i], alt["path"][i+1]), max(alt["path"][i], alt["path"][i+1])) not in {(min(blocked[0][0], blocked[0][1]), max(blocked[0][0], blocked[0][1]))}
    far = rescue_route(12.9716, 77.5946, 0.0, 0.0, "shortest", None)
    assert "unreachable" in far  # flagged, not crash

def test_allocation_capacity_and_zero():
    reset_resources()
    a = allocate_resources(num_drones=2, num_teams=1)
    assert len(a) == 3
    s = allocation_summary(a, total_zones=8)
    assert s["utilisation_pct"] > 0 and s["unserved_zones"] >= 0
    z = allocation_summary([], total_zones=8)
    assert z["total"] == 0 and z["utilisation_pct"] == 0.0
    reset_resources()
