from __future__ import annotations
import time
from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from app.services.risk_service import risk_grid, predicted_zones
from app.services.prediction_ml_engine import train as ml_train, backtest as ml_backtest
from app.services.prediction_rule_engine import RuleRiskConfig, DEFAULT_RULE_CONFIG

router = APIRouter(prefix="/risk", tags=["risk"])

def _ms(s):
    return round((time.perf_counter() - s) * 1000, 1)

@router.get("/grid")
async def get_risk_grid(model: str = Query(default="ml"), rainfall_multiplier: float = Query(default=1.0, ge=0.2, le=3.0), horizon_hours: int = Query(default=6)) -> dict:
    s = time.perf_counter()
    if model not in ("ml", "rule"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="model must be ml|rule")
    g = risk_grid(model, rainfall_multiplier, horizon_hours)
    g["processing_ms"] = _ms(s)
    return g

@router.get("/predict")
async def predict(model: str = Query(default="ml"), rainfall_multiplier: float = Query(default=1.0, ge=0.2, le=3.0), horizon_hours: int = Query(default=6)) -> dict:
    return await get_risk_grid(model, rainfall_multiplier, horizon_hours)

@router.get("/predicted-zones")
async def get_predicted_zones(model: str = Query(default="ml"), rainfall_multiplier: float = Query(default=1.0, ge=0.2, le=3.0), horizon_hours: int = Query(default=6)) -> dict:
    s = time.perf_counter()
    d = predicted_zones(model, rainfall_multiplier, horizon_hours)
    d["processing_ms"] = _ms(s)
    return d

@router.get("/model-metrics")
async def model_metrics() -> dict:
    s = time.perf_counter()
    m = ml_train()
    m["processing_ms"] = _ms(s)
    m["default_model"] = "ml"
    m["why_default"] = "ML beats rule on held-out events (higher ROC-AUC) while rule stays fully explainable; see /risk/backtest."
    return m

@router.get("/backtest")
async def backtest(event_idx: int = Query(default=8, ge=0, le=9)) -> dict:
    s = time.perf_counter()
    b = ml_backtest(event_idx)
    b["processing_ms"] = _ms(s)
    return b

@router.get("/model-card")
async def model_card() -> dict:
    m = ml_train()
    return {"data_used": ["bundled simulated historical events EVT-01..10 (clearly labelled)", "SRTM-style DEM + slope + river distance (synthetic AOI)", "Open-Meteo/forecast rainfall (cached, offline-safe)", "live CV detections + sensor readings"], "method": {"L1": "rule: rainfall x low-elevation x river-proximity x slope x sensor-trend, configurable weights, per-cell contributions", "L2": "RandomForest(120 trees, depth 10, seed 20261014), train EVT-01..08, test EVT-09..10 (no leakage)", "L3": "DEM downhill spread T+1/T+3/T+6 via /prediction (optional)"}, "metrics": m, "limitations": ["Simulated history + terrain; not authoritative", "28x32 grid (~1.25km cells) — street-level detail not resolved", "First prediction call fetches weather (~3s), then cached"], "default": "ml"}

class RuleWeights(BaseModel):
    weight_rainfall: Optional[float] = None
    weight_elevation: Optional[float] = None
    weight_river_dist: Optional[float] = None
    weight_forecast_3h: Optional[float] = None
    weight_cv: Optional[float] = None
    weight_sensor_trend: Optional[float] = None

@router.post("/rule-weights")
async def set_rule_weights(body: RuleWeights) -> dict:
    cfg = RuleRiskConfig(**{**DEFAULT_RULE_CONFIG.__dict__, **{k: v for k, v in body.model_dump().items() if v is not None}})
    from app.services import prediction_rule_engine as _re
    _re.DEFAULT_RULE_CONFIG.__dict__.update(cfg.__dict__)
    return {"weights": cfg.__dict__, "source": "user-configured"}
