"""Stage 3: Predictive Feature Engineering.

Builds per-cell feature tables combining:
- Weather (current + forecast rainfall)
- Geography (DEM elevation, slope, distance to rivers)
- Historical flood extents (simulated from past events)
- Live state (CV detections, sensor readings)
- Sensor trends (rising/falling water levels)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from app.services import geospatial
from app.services.grid_service import compute_flood_probability
from app.services.openmeteo_service import get_forecast, get_rain_factors
from app.services.sensor_service import get_sensor_service
from app.services.data_store import get_store
from app.services.gis_layer_service import layer
from app.config import get_settings


# Grid resolution for prediction (finer than Stage 2's 14x16)
PRED_GRID_ROWS = 28   # ~1.25 km per cell
PRED_GRID_COLS = 32   # ~1.25 km per cell


@dataclass
class PredictionFeatureSet:
    """Per-cell features for flood risk prediction."""
    # Grid geometry
    cell_ids: np.ndarray          # (rows, cols) string IDs
    lats: np.ndarray              # (rows,)
    lngs: np.ndarray              # (cols,)
    
    # Static geographic features
    elevation_m: np.ndarray       # (rows, cols)
    slope_deg: np.ndarray         # (rows, cols)
    distance_river_km: np.ndarray # (rows, cols)
    road_access: np.ndarray       # (rows, cols) 0..1
    population_density: np.ndarray # (rows, cols) 0..1
    
    # Weather features
    current_rainfall_mm: float
    forecast_rainfall_3h: np.ndarray      # (rows, cols) - next 3h
    forecast_rainfall_6h: np.ndarray      # (rows, cols) - next 6h
    forecast_rainfall_12h: np.ndarray     # (rows, cols) - next 12h
    forecast_rainfall_24h: np.ndarray     # (rows, cols) - next 24h
    forecast_wind_kmh: float
    
    # Historical features
    historical_flood_freq: np.ndarray     # (rows, cols) 0..1 frequency
    historical_max_depth_m: np.ndarray    # (rows, cols) metres
    
    # Live state features
    cv_flood_probability: np.ndarray      # (rows, cols) 0..1 from CV
    sensor_water_level_trend: np.ndarray  # (rows, cols) -1..1 rising/falling
    sensor_rainfall_intensity: np.ndarray # (rows, cols) mm/hr
    sensor_alert_proximity: np.ndarray    # (rows, cols) 0..1 nearby alerts
    
    # Sensor metadata
    sensor_reading_age_hours: np.ndarray  # (rows, cols) hours since reading


def _interpolate_to_grid(
    source_lats: np.ndarray,
    source_lngs: np.ndarray,
    source_data: np.ndarray,
    target_lats: np.ndarray,
    target_lngs: np.ndarray,
) -> np.ndarray:
    """Bilinear interpolation from source grid to target grid."""
    from scipy import interpolate
    
    # Handle edge cases
    if source_data.ndim == 1:
        source_data = source_data.reshape(-1, 1)
    
    f = interpolate.RegularGridInterpolator(
        (source_lats[::-1], source_lngs),  # lat decreasing
        source_data[::-1, :] if source_data.shape[0] == len(source_lats) else source_data.T,
        bounds_error=False,
        fill_value=0.0,
    )
    
    # Create target meshgrid
    T_LAT, T_LNG = np.meshgrid(target_lats[::-1], target_lngs, indexing="ij")
    points = np.column_stack([T_LAT.ravel(), T_LNG.ravel()])
    
    result = f(points).reshape(len(target_lats), len(target_lngs))
    return result


def build_prediction_features(
    rain_multiplier: float = 1.0,
    horizon_hours: int = 12,
) -> PredictionFeatureSet:
    """Build complete per-cell feature table for the prediction grid."""
    
    # --- 1. Get prediction grid coordinates ---
    rows, cols = PRED_GRID_ROWS, PRED_GRID_COLS
    lat_min, lat_max = geospatial.LAT_MIN, geospatial.LAT_MAX
    lng_min, lng_max = geospatial.LNG_MIN, geospatial.LNG_MAX
    
    pred_lats = np.linspace(lat_max, lat_min, rows)
    pred_lngs = np.linspace(lng_min, lng_max, cols)
    PRED_LAT, PRED_LNG = np.meshgrid(pred_lats, pred_lngs, indexing="ij")
    
    cell_ids = np.array([[f"pred-{r:02d}-{c:02d}" for c in range(cols)] for r in range(rows)])
    
    # --- 2. Get base terrain (14x16) and interpolate to prediction grid (28x32) ---
    base_terrain = geospatial.terrain()
    base_lats = base_terrain.lats
    base_lngs = base_terrain.lngs
    
    elevation_m = _interpolate_to_grid(base_lats, base_lngs, base_terrain.elevation, pred_lats, pred_lngs)
    slope_deg = _interpolate_to_grid(base_lats, base_lngs, base_terrain.slope, pred_lats, pred_lngs)
    distance_river_km = _interpolate_to_grid(base_lats, base_lngs, base_terrain.distance_river, pred_lats, pred_lngs)
    road_access = _interpolate_to_grid(base_lats, base_lngs, base_terrain.road_access, pred_lats, pred_lngs)
    population_density = _interpolate_to_grid(base_lats, base_lngs, base_terrain.population, pred_lats, pred_lngs)
    
    # --- 3. Weather features ---
    rain_factor, hourly_accum = get_rain_factors()
    rain_factor = float(rain_factor) * rain_multiplier
    current_rainfall_mm = sum(hourly_accum[:3]) / 3.0 * rain_multiplier  # current ~3h average
    forecast_wind_kmh = 10.0  # placeholder
    
    # Build forecast rainfall arrays for different horizons
    forecast_rainfall_3h = np.full((rows, cols), sum(hourly_accum[:3]) * rain_multiplier)
    forecast_rainfall_6h = np.full((rows, cols), sum(hourly_accum[:6]) * rain_multiplier)
    forecast_rainfall_12h = np.full((rows, cols), sum(hourly_accum[:12]) * rain_multiplier)
    forecast_rainfall_24h = np.full((rows, cols), sum(hourly_accum[:24]) * rain_multiplier)
    
    # --- 4. Historical flood frequency (simulated from past events) ---
    historical_flood_freq = _generate_historical_flood_freq(PRED_LAT, PRED_LNG, rows, cols)
    historical_max_depth_m = _generate_historical_max_depth(PRED_LAT, PRED_LNG, rows, cols)
    
    # --- 5. Live CV flood probability (from existing grid_service) ---
    cv_flood_prob = compute_flood_probability(rain_factor)
    cv_flood_prob = _interpolate_to_grid(
        geospatial.terrain().lats, geospatial.terrain().lngs, cv_flood_prob, 
        pred_lats, pred_lngs
    )
    
    # --- 6. Sensor features ---
    sensor_water_level_trend, sensor_rainfall_intensity, sensor_alert_proximity, sensor_reading_age = \
        _build_sensor_features(PRED_LAT, PRED_LNG, pred_lats, pred_lngs, rows, cols)
    
    return PredictionFeatureSet(
        cell_ids=cell_ids,
        lats=pred_lats,
        lngs=pred_lngs,
        elevation_m=elevation_m,
        slope_deg=slope_deg,
        distance_river_km=distance_river_km,
        road_access=road_access,
        population_density=population_density,
        current_rainfall_mm=current_rainfall_mm,
        forecast_rainfall_3h=forecast_rainfall_3h,
        forecast_rainfall_6h=forecast_rainfall_6h,
        forecast_rainfall_12h=forecast_rainfall_12h,
        forecast_rainfall_24h=forecast_rainfall_24h,
        forecast_wind_kmh=forecast_wind_kmh,
        historical_flood_freq=historical_flood_freq,
        historical_max_depth_m=historical_max_depth_m,
        cv_flood_probability=cv_flood_prob,
        sensor_water_level_trend=sensor_water_level_trend,
        sensor_rainfall_intensity=sensor_rainfall_intensity,
        sensor_alert_proximity=sensor_alert_proximity,
        sensor_reading_age_hours=sensor_reading_age,
    )


def _generate_historical_flood_freq(lat_grid: np.ndarray, lng_grid: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """Generate simulated historical flood frequency from past events.
    
    Uses deterministic seed based on location for reproducibility.
    Simulates 10 past flood events with varying extents.
    """
    import zlib
    freq = np.zeros((rows, cols), dtype=float)
    n_events = 10
    
    for event_idx in range(n_events):
        # Each event has a random center and radius
        seed = zlib.crc32(f"hist_flood_{event_idx}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        
        # Event center biased toward low-lying areas
        center_lat = float(rng.uniform(geospatial.LAT_MIN + 0.05, geospatial.LAT_MAX - 0.05))
        center_lng = float(rng.uniform(geospatial.LNG_MIN + 0.05, geospatial.LNG_MAX - 0.05))
        radius_km = float(rng.uniform(3.0, 8.0))
        
        # Distance from each cell to event center
        lat_diff = (lat_grid - center_lat) * 111.0
        lng_diff = (lng_grid - center_lng) * 111.0 * np.cos(np.radians(12.96))
        dist_km = np.hypot(lat_diff, lng_diff)
        
        # Flood if within radius, with probability decaying at edges
        affected = dist_km <= radius_km
        edge_prob = np.clip(1.0 - dist_km / radius_km, 0.0, 1.0)
        freq[affected] += edge_prob[affected]
    
    return freq / n_events


def _generate_historical_max_depth(lat_grid: np.ndarray, lng_grid: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """Generate historical maximum flood depth (metres)."""
    import zlib
    max_depth = np.zeros((rows, cols), dtype=float)
    n_events = 10
    
    for event_idx in range(n_events):
        seed = zlib.crc32(f"hist_flood_{event_idx}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        
        center_lat = float(rng.uniform(geospatial.LAT_MIN + 0.05, geospatial.LAT_MAX - 0.05))
        center_lng = float(rng.uniform(geospatial.LNG_MIN + 0.05, geospatial.LNG_MAX - 0.05))
        radius_km = float(rng.uniform(3.0, 8.0))
        max_event_depth = float(rng.uniform(0.3, 2.5))
        
        lat_diff = (lat_grid - center_lat) * 111.0
        lng_diff = (lng_grid - center_lng) * 111.0 * np.cos(np.radians(12.96))
        dist_km = np.hypot(lat_diff, lng_diff)
        
        affected = dist_km <= radius_km
        depth_profile = max_event_depth * np.clip(1.0 - dist_km[affected] / radius_km, 0.0, 1.0)
        max_depth[affected] = np.maximum(max_depth[affected], depth_profile)
    
    return max_depth


def _build_sensor_features(
    lat_grid: np.ndarray,
    lng_grid: np.ndarray,
    pred_lats: np.ndarray,
    pred_lngs: np.ndarray,
    rows: int,
    cols: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build sensor-derived features for the prediction grid."""
    sensor_svc = get_sensor_service()
    stations = sensor_svc.get_all_stations()
    latest_readings = sensor_svc.get_latest_readings()
    
    water_trend = np.zeros((rows, cols), dtype=float)
    rainfall_intensity = np.zeros((rows, cols), dtype=float)
    alert_proximity = np.zeros((rows, cols), dtype=float)
    reading_age = np.full((rows, cols), 24.0, dtype=float)  # default 24h
    
    if not latest_readings:
        return water_trend, rainfall_intensity, alert_proximity, reading_age
    
    # For each cell, find nearby sensors and aggregate
    for r in range(rows):
        for c in range(cols):
            cell_lat = lat_grid[r, c]
            cell_lng = lng_grid[r, c]
            
            nearby_sensors = []
            for reading in latest_readings:
                station = next((s for s in stations if s.id == reading.sensor_id), None)
                if not station:
                    continue
                
                from app.scoring_core import haversine_km
                dist = haversine_km(cell_lat, cell_lng, station.latitude, station.longitude)
                
                if dist <= 8.0:  # 8km search radius
                    nearby_sensors.append((dist, reading, station))
            
            if not nearby_sensors:
                continue
            
            # Weight by inverse distance
            total_weight = sum(1.0 / max(d, 0.1) for d, _, _ in nearby_sensors)
            
            # Water level trend (approximated from current vs 6h ago)
            trend_sum = 0.0
            rain_sum = 0.0
            alert_sum = 0.0
            age_sum = 0.0
            
            for dist, reading, station in nearby_sensors:
                weight = (1.0 / max(dist, 0.1)) / total_weight
                
                # Water level trend: compare current to 6h ago
                if station.sensor_type.value == "water_level":
                    hist = sensor_svc.get_readings(
                        sensor_id=station.id, hours=6, 
                        sensor_type=type(station.sensor_type)(station.sensor_type.value)
                    )
                    if len(hist) >= 2:
                        trend = hist[0].value - hist[-1].value  # positive = rising
                        trend_sum += weight * np.clip(trend, -1.0, 1.0)
                
                # Rainfall intensity
                if station.sensor_type.value == "rainfall":
                    rain_sum += weight * reading.value
                
                # Alert proximity
                if reading.alert_level.value in ("watch", "warning", "critical"):
                    alert_sum += weight
                
                # Reading age
                age_hours = (datetime.now(timezone.utc) - reading.timestamp).total_seconds() / 3600
                age_sum += weight * age_hours
            
            water_trend[r, c] = trend_sum
            rainfall_intensity[r, c] = rain_sum
            alert_proximity[r, c] = alert_sum
            reading_age[r, c] = age_sum
    
    return water_trend, rainfall_intensity, alert_proximity, reading_age