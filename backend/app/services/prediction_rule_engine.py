"""Stage 3: Level 1 - Explainable Rule-Based Flood Risk Engine.

Computes per-cell flood risk probability using interpretable rules:
risk = f(rainfall, elevation, slope, river_dist, soil_moisture, population, sensor_trend)

All weights are configurable. Output includes per-factor contributions for explainability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.services import geospatial
from app.services.prediction_features import PredictionFeatureSet, build_prediction_features
from app.config import get_settings


@dataclass
class RuleRiskConfig:
    """Configurable weights for rule-based risk factors."""
    # Core physical factors
    weight_rainfall: float = 1.0
    weight_elevation: float = 0.8
    weight_slope: float = 0.4
    weight_river_dist: float = 0.9
    weight_road_access: float = 0.3
    
    # Dynamic factors
    weight_forecast_3h: float = 0.6
    weight_forecast_6h: float = 0.4
    weight_forecast_12h: float = 0.3
    weight_forecast_24h: float = 0.2
    
    # Live state
    weight_cv: float = 0.5
    weight_sensor_trend: float = 0.4
    weight_sensor_rain: float = 0.3
    weight_sensor_alerts: float = 0.4
    
    # Historical
    weight_hist_freq: float = 0.3
    weight_hist_depth: float = 0.2
    
    # Population exposure multiplier
    weight_population: float = 0.5


DEFAULT_RULE_CONFIG = RuleRiskConfig()


@dataclass
class CellRiskResult:
    """Risk result for a single cell with factor breakdown."""
    cell_id: str
    lat: float
    lng: float
    risk_probability: float          # 0..1
    risk_level: str                  # Low/Medium/High/Critical
    confidence: float                # 0..1
    
    # Factor contributions (sum to risk_probability)
    contrib_rainfall: float
    contrib_elevation: float
    contrib_slope: float
    contrib_river_dist: float
    contrib_forecast: float
    contrib_cv: float
    contrib_sensor_trend: float
    contrib_sensor_rain: float
    contrib_sensor_alerts: float
    contrib_historical: float
    contrib_population: float
    
    # Raw factor values (for UI display)
    raw_rainfall_mm: float
    raw_elevation_m: float
    raw_slope_deg: float
    raw_river_dist_km: float
    raw_forecast_3h_mm: float
    raw_cv_prob: float
    raw_sensor_trend: float
    raw_sensor_rain: float
    raw_alert_proximity: float
    raw_hist_freq: float
    raw_population: float
    
    # Metadata
    population_exposed: int
    nearest_shelter_km: float
    nearest_hospital_km: float


def _normalize(value: np.ndarray, min_val: float, max_val: float, invert: bool = False) -> np.ndarray:
    """Normalize array to 0..1 range, optionally inverted."""
    norm = np.clip((value - min_val) / (max_val - min_val), 0.0, 1.0)
    return 1.0 - norm if invert else norm


def _risk_level_from_prob(prob: float) -> str:
    if prob >= 0.75:
        return "Critical"
    elif prob >= 0.55:
        return "High"
    elif prob >= 0.35:
        return "Medium"
    return "Low"


def _confidence_from_factors(
    sensor_age: np.ndarray,
    cv_prob: np.ndarray,
    sensor_count: np.ndarray,
) -> np.ndarray:
    """Compute confidence based on data freshness and coverage."""
    # Base confidence from sensor freshness (newer = more confident)
    age_confidence = np.clip(1.0 - sensor_age / 24.0, 0.3, 1.0)
    
    # CV confidence (higher prob = more confident in detection)
    cv_confidence = np.clip(0.5 + cv_prob * 0.5, 0.4, 1.0)
    
    # Sensor coverage confidence
    coverage_confidence = np.clip(0.5 + sensor_count * 0.1, 0.5, 1.0)
    
    return (age_confidence * 0.4 + cv_confidence * 0.3 + coverage_confidence * 0.3)


def compute_rule_risk(
    features,
    config: RuleRiskConfig | None = None,
) -> list[CellRiskResult]:
    """Compute rule-based flood risk for all cells."""
    if config is None:
        config = DEFAULT_RULE_CONFIG
    
    rows, cols = features.elevation_m.shape
    results = []
    
    # Pre-compute normalized factors
    rain_norm = _normalize(features.current_rainfall_mm, 0.0, 50.0)
    elev_norm = _normalize(features.elevation_m, 850.0, 1030.0, invert=True)
    slope_norm = _normalize(features.slope_deg, 0.0, 15.0)
    river_norm = _normalize(features.distance_river_km, 0.0, 10.0, invert=True)
    road_norm = _normalize(features.road_access, 0.0, 1.0, invert=True)
    
    forecast_3h_norm = _normalize(features.forecast_rainfall_3h, 0.0, 40.0)
    forecast_6h_norm = _normalize(features.forecast_rainfall_6h, 0.0, 60.0)
    forecast_12h_norm = _normalize(features.forecast_rainfall_12h, 0.0, 80.0)
    forecast_24h_norm = _normalize(features.forecast_rainfall_24h, 0.0, 120.0)
    
    cv_norm = features.cv_flood_probability
    sensor_trend_norm = _normalize(features.sensor_water_level_trend, -1.0, 1.0)
    sensor_rain_norm = _normalize(features.sensor_rainfall_intensity, 0.0, 30.0)
    sensor_alert_norm = features.sensor_alert_proximity
    
    hist_freq_norm = features.historical_flood_freq
    hist_depth_norm = _normalize(features.historical_max_depth_m, 0.0, 2.5)
    pop_norm = features.population_density
    
    for r in range(rows):
        for c in range(cols):
            cell_id = features.cell_ids[r, c]
            lat = float(features.lats[r])
            lng = float(features.lngs[c])
            
            # Compute weighted contributions (per-cell scalars)
            c_rain = float(config.weight_rainfall * rain_norm)
            c_elev = float(config.weight_elevation * elev_norm[r, c])
            c_slope = float(config.weight_slope * slope_norm[r, c])
            c_river = float(config.weight_river_dist * river_norm[r, c])
            c_road = float(config.weight_road_access * road_norm[r, c])
            contrib_rainfall, contrib_elevation, contrib_slope, contrib_river, contrib_road = c_rain, c_elev, c_slope, c_river, c_road

            contrib_forecast = float(
                config.weight_forecast_3h * forecast_3h_norm[r, c] +
                config.weight_forecast_6h * forecast_6h_norm[r, c] +
                config.weight_forecast_12h * forecast_12h_norm[r, c] +
                config.weight_forecast_24h * forecast_24h_norm[r, c]
            )

            contrib_cv = float(config.weight_cv * cv_norm[r, c])
            contrib_sensor_trend = float(config.weight_sensor_trend * sensor_trend_norm[r, c])
            contrib_sensor_rain = float(config.weight_sensor_rain * sensor_rain_norm[r, c])
            contrib_sensor_alerts = float(config.weight_sensor_alerts * sensor_alert_norm[r, c])

            contrib_historical = float(
                config.weight_hist_freq * hist_freq_norm[r, c] +
                config.weight_hist_depth * hist_depth_norm[r, c]
            )
            
            contrib_population = float(config.weight_population * pop_norm[r, c])

            # Sum all contributions (all scalars now)
            total_score = float(
                contrib_rainfall + contrib_elevation + contrib_slope + contrib_river + contrib_road +
                contrib_forecast + contrib_cv + contrib_sensor_trend + contrib_sensor_rain +
                contrib_sensor_alerts + contrib_historical + contrib_population
            )
            
            # Normalize to 0..1 probability
            # Max possible score if all factors at max
            max_possible = (
                config.weight_rainfall + config.weight_elevation + config.weight_slope +
                config.weight_river_dist + config.weight_road_access +
                config.weight_forecast_3h + config.weight_forecast_6h + 
                config.weight_forecast_12h + config.weight_forecast_24h +
                config.weight_cv + config.weight_sensor_trend + config.weight_sensor_rain +
                config.weight_sensor_alerts + config.weight_hist_freq + config.weight_hist_depth +
                config.weight_population
            )
            
            risk_prob = float(np.clip(total_score / max_possible, 0.0, 1.0))
            risk_level = _risk_level_from_prob(risk_prob)
            
            # Confidence
            sensor_count = 1.0 if features.sensor_alert_proximity[r, c] > 0 else 0.0
            confidence = float(_confidence_from_factors(
                np.array([features.sensor_reading_age_hours[r, c]]),
                np.array([features.cv_flood_probability[r, c]]),
                np.array([sensor_count]),
            )[0])
            
            # Population exposed estimate
            cell_area_km2 = ((geospatial.LAT_MAX - geospatial.LAT_MIN) / rows * 111.0) * \
                           ((geospatial.LNG_MAX - geospatial.LNG_MIN) / cols * 111.0 * np.cos(np.radians(12.96)))
            pop_exposed = int(features.population_density[r, c] * cell_area_km2 * 10000)
            
            # Nearest shelter/hospital (approximate from grid)
            shelter_km = float(np.min([
                np.hypot(lat - s.lat, (lng - s.lng) * np.cos(np.radians(12.96))) * 111.0
                for s in geospatial.SHELTERS
            ]))
            hospital_km = float(np.min([
                np.hypot(lat - h.lat, (lng - h.lng) * np.cos(np.radians(12.96))) * 111.0
                for h in geospatial.SHELTERS  # using shelters as hospitals too
            ]))
            
            results.append(CellRiskResult(
                cell_id=cell_id,
                lat=lat,
                lng=lng,
                risk_probability=risk_prob,
                risk_level=risk_level,
                confidence=confidence,
                contrib_rainfall=float(contrib_rainfall),
                contrib_elevation=float(contrib_elevation),
                contrib_slope=float(contrib_slope),
                contrib_river_dist=float(contrib_river),
                contrib_forecast=float(contrib_forecast),
                contrib_cv=float(contrib_cv),
                contrib_sensor_trend=float(contrib_sensor_trend),
                contrib_sensor_rain=float(contrib_sensor_rain),
                contrib_sensor_alerts=float(contrib_sensor_alerts),
                contrib_historical=float(contrib_historical),
                contrib_population=float(contrib_population),
                raw_rainfall_mm=float(features.current_rainfall_mm),
                raw_elevation_m=float(features.elevation_m[r, c]),
                raw_slope_deg=float(features.slope_deg[r, c]),
                raw_river_dist_km=float(features.distance_river_km[r, c]),
                raw_forecast_3h_mm=float(features.forecast_rainfall_3h[r, c]),
                raw_cv_prob=float(cv_norm[r, c]),
                raw_sensor_trend=float(features.sensor_water_level_trend[r, c]),
                raw_sensor_rain=float(features.sensor_rainfall_intensity[r, c]),
                raw_alert_proximity=float(features.sensor_alert_proximity[r, c]),
                raw_hist_freq=float(hist_freq_norm[r, c]),
                raw_population=float(pop_norm[r, c]),
                population_exposed=pop_exposed,
                nearest_shelter_km=shelter_km,
                nearest_hospital_km=hospital_km,
            ))
    
    return results


def compute_rule_risk_grid(
    rain_multiplier: float = 1.0,
    horizon_hours: int = 12,
    config: Optional[RuleRiskConfig] = None,
) -> dict:
    """Entry point: build features and compute rule-based risk grid."""
    features = build_prediction_features(rain_multiplier, horizon_hours)
    cell_results = compute_rule_risk(features, config)
    
    rows, cols = features.elevation_m.shape
    risk_grid = np.zeros((rows, cols))
    level_grid = np.zeros((rows, cols), dtype=int)
    confidence_grid = np.zeros((rows, cols))
    
    level_map = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    
    for res in cell_results:
        r, c = map(int, res.cell_id.split("-")[1:3])
        risk_grid[r, c] = res.risk_probability
        level_grid[r, c] = level_map.get(res.risk_level, 0)
        confidence_grid[r, c] = res.confidence
    
    # Summary stats
    total_cells = rows * cols
    critical_cells = int(np.sum(level_grid == 3))
    high_cells = int(np.sum(level_grid == 2))
    medium_cells = int(np.sum(level_grid == 1))
    low_cells = int(np.sum(level_grid == 0))
    
    return {
        "bounds": {
            "min_lat": float(geospatial.LAT_MIN),
            "max_lat": float(geospatial.LAT_MAX),
            "min_lng": float(geospatial.LNG_MIN),
            "max_lng": float(geospatial.LNG_MAX),
        },
        "grid_shape": {"rows": rows, "cols": cols},
        "risk_probability": risk_grid.tolist(),
        "risk_level": level_grid.tolist(),
        "confidence": confidence_grid.tolist(),
        "cells": [res.__dict__ for res in cell_results],
        "summary": {
            "total_cells": total_cells,
            "critical_cells": critical_cells,
            "high_cells": high_cells,
            "medium_cells": medium_cells,
            "low_cells": low_cells,
            "mean_risk": float(risk_grid.mean()),
            "max_risk": float(risk_grid.max()),
        },
        "config_used": {
            "rain_multiplier": rain_multiplier,
            "horizon_hours": horizon_hours,
            "weights": config.__dict__ if config else DEFAULT_RULE_CONFIG.__dict__,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }