"""Stage 3: labelled-simulated historical flood events (bundled, offline-safe).

10 past events over Bengaluru AOI. Each event: center, radius, peak rainfall,
max depth profile. Deterministic seeds. Clearly labelled simulated.
Split by event (no leakage): train events 0-7, test events 8-9.
"""
from __future__ import annotations
import json, zlib
from pathlib import Path
import numpy as np
from app.config import DATA_DIR
from app.services import geospatial

HIST_PATH = DATA_DIR / "risk_history.json"
N_EVENTS = 10
TRAIN_EVENTS = list(range(8))
TEST_EVENTS = [8, 9]

def _event_params(idx: int) -> dict:
    seed = zlib.crc32(f"hist_flood_{idx}".encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return {
        "event_id": f"EVT-{idx+1:02d}",
        "center_lat": float(rng.uniform(geospatial.LAT_MIN + 0.05, geospatial.LAT_MAX - 0.05)),
        "center_lng": float(rng.uniform(geospatial.LNG_MIN + 0.05, geospatial.LNG_MAX - 0.05)),
        "radius_km": float(rng.uniform(3.0, 8.0)),
        "peak_rain_mm": float(rng.uniform(25.0, 95.0)),
        "max_depth_m": float(rng.uniform(0.3, 2.5)),
        "duration_h": int(rng.integers(6, 24)),
        "year": 2015 + idx,
        "source": "simulated-historical",
    }

def build_history(force: bool = False) -> list[dict]:
    if HIST_PATH.exists() and not force:
        try:
            return json.loads(HIST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    events = [_event_params(i) for i in range(N_EVENTS)]
    HIST_PATH.write_text(json.dumps(events, indent=2), encoding="utf-8")
    return events

def load_history() -> list[dict]:
    return build_history(False)

def event_affected_mask(event: dict, lats: np.ndarray, lngs: np.ndarray) -> np.ndarray:
    LAT, LNG = np.meshgrid(lats, lngs, indexing="ij")
    dlat = (LAT - event["center_lat"]) * 111.0
    dlng = (LNG - event["center_lng"]) * 111.0 * np.cos(np.radians(12.96))
    return np.hypot(dlat, dlng) <= event["radius_km"]
