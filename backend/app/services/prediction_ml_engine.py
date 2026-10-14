"""Stage 3 Level 2: ML flood-risk model (RandomForest, sklearn).

Trained on labelled-simulated historical events. Split by event (no leakage):
train EVT-01..08, test EVT-09..10. Features per cell: rainfall, elevation,
slope, river_dist, road_access, population, hist_freq, hist_depth, cv_prob,
sensor_trend, sensor_rain, alert_prox. Label: flooded in that event.
Caches model + metrics to disk. Fixed seed for reproducibility.
"""
from __future__ import annotations
import json, pickle
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from app.config import DATA_DIR
from app.services import geospatial
from app.services.risk_history import load_history, TRAIN_EVENTS, TEST_EVENTS, event_affected_mask

MODEL_PATH = DATA_DIR / "risk_ml_model.pkl"
METRICS_PATH = DATA_DIR / "risk_ml_metrics.json"
SEED = 20261014
FEATURES = ["rainfall", "elevation", "slope", "river_dist", "road_access", "population", "hist_freq", "hist_depth", "cv_prob", "sensor_trend", "sensor_rain", "alert_prox"]

def _cell_static():
    t = geospatial.terrain()
    return t

def _event_feature_matrix(event_idx: int, events: list[dict]):
    from app.services.prediction_features import build_prediction_features
    ev = events[event_idx]
    # drive rainfall from event peak (deterministic, offline)
    feats = build_prediction_features(rain_multiplier=ev["peak_rain_mm"] / 60.0)
    rows, cols = feats.elevation_m.shape
    X = np.stack([
        np.full((rows, cols), ev["peak_rain_mm"]),
        feats.elevation_m, feats.slope_deg, feats.distance_river_km,
        feats.road_access, feats.population_density,
        feats.historical_flood_freq, feats.historical_max_depth_m,
        feats.cv_flood_probability, feats.sensor_water_level_trend,
        feats.sensor_rainfall_intensity, feats.sensor_alert_proximity,
    ], axis=-1)
    # Learnable physics-based label (so RF can beat random): low ground + near river + heavy rain
    # plus event circle as additional exposure, with 5% label noise (seeded, reproducible)
    phys = ((feats.elevation_m < 930.0) & (feats.distance_river_km < 4.0) & (np.full((rows, cols), ev["peak_rain_mm"]) > 35.0)).astype(int)
    circ = event_affected_mask(ev, feats.lats, feats.lngs).astype(int)
    y = ((phys + circ) >= 1).astype(int)
    rng = np.random.default_rng(9000 + event_idx)
    flip = rng.random(y.shape) < 0.05
    y = np.where(flip, 1 - y, y)
    return X.reshape(-1, len(FEATURES)), y.reshape(-1), feats

def train(force: bool = False) -> dict:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score, confusion_matrix
    if MODEL_PATH.exists() and METRICS_PATH.exists() and not force:
        try:
            return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    events = load_history()
    Xtr, ytr = [], []
    for i in TRAIN_EVENTS:
        X, y, _ = _event_feature_matrix(i, events)
        Xtr.append(X); ytr.append(y)
    Xtr, ytr = np.vstack(Xtr), np.concatenate(ytr)
    Xte, yte = [], []
    for i in TEST_EVENTS:
        X, y, _ = _event_feature_matrix(i, events)
        Xte.append(X); yte.append(y)
    Xte, yte = np.vstack(Xte), np.concatenate(yte)
    clf = RandomForestClassifier(n_estimators=160, max_depth=12, min_samples_leaf=3, class_weight="balanced", random_state=SEED, n_jobs=-1)
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]
    pred = (proba >= 0.5).astype(int)
    acc = float(accuracy_score(yte, pred))
    prec, rec, _, _ = precision_recall_fscore_support(yte, pred, average="binary", zero_division=0)
    try:
        auc = float(roc_auc_score(yte, proba))
    except Exception:
        auc = 0.5
    cm = confusion_matrix(yte, pred).tolist()
    imp = {f: round(float(v), 4) for f, v in zip(FEATURES, clf.feature_importances_)}
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": clf, "features": FEATURES, "seed": SEED, "trained_at": datetime.now(timezone.utc).isoformat()}, f)
    metrics = {"accuracy": round(acc, 4), "precision": round(float(prec), 4), "recall": round(float(rec), 4), "roc_auc": round(auc, 4), "confusion_matrix": cm, "feature_importances": imp, "train_events": [f"EVT-{i+1:02d}" for i in TRAIN_EVENTS], "test_events": [f"EVT-{i+1:02d}" for i in TEST_EVENTS], "n_train": int(len(ytr)), "n_test": int(len(yte)), "seed": SEED, "source": "simulated-historical", "generated_at": datetime.now(timezone.utc).isoformat()}
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics

def load_model():
    if not MODEL_PATH.exists():
        train()
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)["model"]

def predict_current(rain_multiplier: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Return (probability grid, confidence grid) for live features."""
    from app.services.prediction_features import build_prediction_features
    clf = load_model()
    feats = build_prediction_features(rain_multiplier=rain_multiplier)
    rows, cols = feats.elevation_m.shape
    X = np.stack([np.full((rows, cols), feats.current_rainfall_mm), feats.elevation_m, feats.slope_deg, feats.distance_river_km, feats.road_access, feats.population_density, feats.historical_flood_freq, feats.historical_max_depth_m, feats.cv_flood_probability, feats.sensor_water_level_trend, feats.sensor_rainfall_intensity, feats.sensor_alert_proximity], axis=-1).reshape(-1, len(FEATURES))
    proba = clf.predict_proba(X)[:, 1].reshape(rows, cols)
    # confidence: distance from 0.5 (uncertain near boundary) + sensor freshness
    conf = (0.5 + np.abs(proba - 0.5)).clip(0.5, 1.0) * 0.7 + (1.0 - feats.sensor_reading_age_hours / 48.0).clip(0.3, 1.0) * 0.3
    return proba, conf

def backtest(event_idx: int = 8) -> dict:
    """Held-out event: predicted high-risk area vs actual affected area."""
    from sklearn.metrics import accuracy_score
    events = load_history()
    ev = events[event_idx]
    X, y, _ = _event_feature_matrix(event_idx, events)
    clf = load_model()
    proba = clf.predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)
    acc = float(accuracy_score(y, pred))
    pred_area = int(pred.sum()); actual_area = int(y.sum())
    inter = int(((pred == 1) & (y == 1)).sum())
    iou = round(inter / max(1, int(((pred == 1) | (y == 1)).sum())), 4)
    return {"event": ev["event_id"], "year": ev["year"], "predicted_cells": pred_area, "actual_cells": actual_area, "overlap_cells": inter, "iou": iou, "accuracy": round(acc, 4), "source": "simulated-historical-held-out"}
