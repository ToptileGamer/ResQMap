"""Stage 3 unified risk service: rule vs ML, horizons, uncertainty, predicted zones."""
from __future__ import annotations
from datetime import datetime, timezone
import numpy as np
from app.services import geospatial
from app.services.prediction_features import build_prediction_features, PRED_GRID_ROWS, PRED_GRID_COLS
from app.services.prediction_rule_engine import compute_rule_risk_grid, RuleRiskConfig, DEFAULT_RULE_CONFIG
from app.services.prediction_ml_engine import predict_current, train as ml_train
from app.services.data_store import get_store
from app.services.gis_layer_service import layer as gis_layer

RISK_WEIGHTS = {"rule": {"rainfall": 1.0, "elevation": 0.8}, "default_model": "ml"}

def _level(p: float) -> str:
    if p >= 0.75: return "Critical"
    if p >= 0.55: return "High"
    if p >= 0.35: return "Medium"
    return "Low"

def _cell_geojson_cells(cells: list[dict], prob_key="risk_probability") -> dict:
    feats = []
    t_rows, t_cols = PRED_GRID_ROWS, PRED_GRID_COLS
    lat_min, lat_max = geospatial.LAT_MIN, geospatial.LAT_MAX
    lng_min, lng_max = geospatial.LNG_MIN, geospatial.LNG_MAX
    dlat = (lat_max - lat_min) / t_rows
    dlng = (lng_max - lng_min) / t_cols
    for c in cells:
        la, lo = c["lat"], c["lng"]
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[lo-dlng/2, la-dlat/2],[lo+dlng/2, la-dlat/2],[lo+dlng/2, la+dlat/2],[lo-dlng/2, la+dlat/2],[lo-dlng/2, la-dlat/2]]]}, "properties": {k: c.get(k) for k in ("cell_id","risk_probability","risk_level","confidence","population_exposed") if k in c}})
    return {"type": "FeatureCollection", "features": feats, "source": "simulated-prediction"}

def risk_grid(model: str = "ml", rainfall_multiplier: float = 1.0, horizon_hours: int = 6) -> dict:
    import time
    s = __import__("time").perf_counter()
    feats = build_prediction_features(rain_multiplier=rainfall_multiplier, horizon_hours=horizon_hours)
    rows, cols = feats.elevation_m.shape
    cells = []
    if model == "rule":
        out = compute_rule_risk_grid(rain_multiplier=rainfall_multiplier, horizon_hours=horizon_hours)
        for c in out["cells"]:
            cells.append({"cell_id": c["cell_id"], "lat": feats.lats[int(c["cell_id"].split("-")[1])], "lng": feats.lngs[int(c["cell_id"].split("-")[2])], "risk_probability": round(c["risk_probability"], 3), "risk_level": c["risk_level"], "confidence": round(c["confidence"], 3), "population_exposed": c["population_exposed"], "factors": {"rainfall": round(c["contrib_rainfall"],3), "elevation": round(c["contrib_elevation"],3), "river": round(c["contrib_river_dist"],3), "forecast": round(c["contrib_forecast"],3), "cv": round(c["contrib_cv"],3), "sensor": round(c["contrib_sensor_trend"]+c["contrib_sensor_rain"]+c["contrib_sensor_alerts"],3), "historical": round(c["contrib_historical"],3), "population": round(c["contrib_population"],3)}})
        cmp_model = "rule"
    else:
        proba, conf = predict_current(rain_multiplier=rainfall_multiplier)
        # horizon scaling: longer horizon slightly higher risk
        scale = {0: 0.9, 3: 0.95, 6: 1.0, 12: 1.08}.get(horizon_hours, 1.0)
        proba = (proba * scale).clip(0, 0.99)
        for r in range(rows):
            for c in range(cols):
                p = round(float(proba[r, c]), 3)
                cells.append({"cell_id": f"pred-{r:02d}-{c:02d}", "lat": float(feats.lats[r]), "lng": float(feats.lngs[c]), "risk_probability": p, "risk_level": _level(p), "confidence": round(float(conf[r, c]), 3), "population_exposed": int(feats.population_density[r, c] * 2.0 * 10000), "factors": {"rainfall": round(float(feats.current_rainfall_mm) / 50.0, 3), "elevation": round(float(1.0 - (feats.elevation_m[r, c]-850)/180), 3), "river": round(float(1.0 - feats.distance_river_km[r, c]/10.0), 3), "forecast": round(float(feats.forecast_rainfall_6h[r, c]/60.0), 3), "cv": round(float(feats.cv_flood_probability[r, c]), 3), "sensor": round(float(feats.sensor_alert_proximity[r, c]), 3), "historical": round(float(feats.historical_flood_freq[r, c]), 3), "population": round(float(feats.population_density[r, c]), 3)}})
        cmp_model = "ml"
    # uncertainty band: rainfall +/-20%
    probs = np.array([c["risk_probability"] for c in cells])
    unc = {"low_rain": round(float((probs*0.85).mean()),3), "base": round(float(probs.mean()),3), "high_rain": round(float((probs*1.15).clip(0,1).mean()),3)}
    area_km2 = round(float((probs >= 0.55).sum() * 1.56), 2)
    people = int(sum(c["population_exposed"] for c in cells if c["risk_probability"] >= 0.55))
    ms = round((__import__("time").perf_counter() - s) * 1000, 1)
    return {"model": cmp_model, "rainfall_multiplier": rainfall_multiplier, "horizon_hours": horizon_hours, "grid_shape": {"rows": rows, "cols": cols}, "bounds": {"min_lat": geospatial.LAT_MIN, "max_lat": geospatial.LAT_MAX, "min_lng": geospatial.LNG_MIN, "max_lng": geospatial.LNG_MAX}, "cells": cells, "geojson": _cell_geojson_cells(cells), "summary": {"mean_risk": round(float(probs.mean()),3), "max_risk": round(float(probs.max()),3), "high_cells": int((probs>=0.55).sum()), "area_at_risk_km2": area_km2, "people_exposed": people}, "uncertainty": unc, "processing_ms": ms, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "simulated-prediction"}

def predicted_zones(model: str = "ml", rainfall_multiplier: float = 1.0, horizon_hours: int = 6) -> dict:
    g = risk_grid(model, rainfall_multiplier, horizon_hours)
    store = get_store()
    out = []
    for z in store.list_zones():
        # nearest cells within ~2km
        near = [c for c in g["cells"] if abs(c["lat"]-z.latitude)*111 < 2.5 and abs(c["lng"]-z.longitude)*111*0.9 < 2.5]
        if not near:
            near = sorted(g["cells"], key=lambda c: abs(c["lat"]-z.latitude)+abs(c["lng"]-z.longitude))[:4]
        prob = round(sum(c["risk_probability"] for c in near)/len(near), 3)
        conf = round(sum(c["confidence"] for c in near)/len(near), 3)
        # top 3 factors by mean
        import collections
        agg = collections.Counter()
        for c in near:
            for k, v in c["factors"].items():
                agg[k] += v
        top3 = [k for k, _ in agg.most_common(3)]
        reason = f"Predicted {prob*100:.0f}% flood likelihood in {horizon_hours}h driven by {', '.join(top3)} (model={model}, simulated)."
        pop = sum(c["population_exposed"] for c in near)
        out.append({"zone_id": z.id, "zone_name": z.name, "latitude": z.latitude, "longitude": z.longitude, "probability": prob, "confidence": conf, "risk_level": _level(prob), "top_factors": top3, "reason": reason, "population_exposed": pop, "nearest_shelter_km": round(min(((z.latitude-s.lat)**2+((z.longitude-s.lng)*0.9)**2)**0.5*111 for s in geospatial.SHELTERS),2)})
    out.sort(key=lambda x: x["probability"], reverse=True)
    return {"model": model, "horizon_hours": horizon_hours, "rainfall_multiplier": rainfall_multiplier, "zones": out, "processing_ms": g["processing_ms"], "generated_at": g["generated_at"], "source": "simulated-prediction"}
