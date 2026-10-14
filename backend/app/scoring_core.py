from __future__ import annotations

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt

from app.models import (
    DisasterZone,
    GISLayer,
    HazardSeverity,
    PriorityZone,
    SensorReading,
    SensorStation,
    SensorType,
    WeatherRisk,
    ZoneAnalysisResponse,
)


def analyze_zone(
    zone: DisasterZone,
    weather: WeatherRisk,
    now: datetime | None = None,
) -> ZoneAnalysisResponse:
    """Legacy re-export of the original zone analysis used by analysis routes.

    This mirrors the original app/scoring.py public API so that the existing
    routers/services (analysis_service, imagery_service) continue to work
    without changes.
    """
    now = now or datetime.now(timezone.utc)

    components = {
        "flood_severity": zone.flood_severity,
        "aerial_damage": zone.aerial_damage_score,
        "population_exposure": zone.population_exposure,
        "road_access": zone.road_access_difficulty,
        "weather": weather.weather_risk_score,
        "shelter": (_shelter_risk(zone.shelter_distance_km) if hasattr(__import__('app.scoring_core'), '_shelter_risk') else zone.shelter_distance_km / 6.0 * 100.0),
    }

    score = sum(WEIGHTS[key] * value for key, value in components.items())
    score = round(clamp(score), 1)
    level = priority_level_for(score)

    return ZoneAnalysisResponse(
        zone_id=zone.id,
        zone_name=zone.name,
        priority_score=score,
        priority_level=level,
        contributing_factors=_contributing_factors(zone, weather.weather_risk_score),
        weather_summary=weather_summary_for(weather),
        weather=weather,
        recommended_action=recommended_action_for(zone, level, weather),
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Legacy helpers (kept minimal to avoid duplicating the original file).
# ---------------------------------------------------------------------------


def _shelter_risk(shelter_distance_km: float) -> float:
    return clamp((shelter_distance_km / 6.0) * 100.0)


def priority_level_for(score: float) -> str:
    for threshold, level in LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return "Low"


def recommended_action_for(zone: DisasterZone, level: str, weather: WeatherRisk) -> str:
    if level == "Critical":
        return (
            f"Dispatch a drone inspection to {zone.name} immediately, coordinate evacuation of "
            f"exposed residents, and confirm shelter access."
        )
    if level == "High":
        return (
            f"Schedule a drone inspection of {zone.name} in the next wave and verify road access "
            f"while weather risk is {round(weather.weather_risk_score)}/100."
        )
    if level == "Moderate":
        return (
            f"Include {zone.name} in routine drone monitoring and re-assess if weather or SOS "
            f"pressure increases."
        )
    return f"Monitor {zone.name} remotely; no immediate drone dispatch required."


def weather_summary_for(weather: WeatherRisk) -> str:
    return (
        f"{weather.weather_condition}, {weather.rainfall_mm:g} mm rainfall, "
        f"{weather.wind_speed_kmh:g} km/h wind (risk {round(weather.weather_risk_score)}/100, "
        f"source: {weather.source})."
    )


def _contributing_factors(
    zone: DisasterZone,
    weather_risk: float,
) -> list[str]:
    components = {
        "flood_severity": (zone.flood_severity, f"Flood severity rated {round(zone.flood_severity)}/100"),
        "aerial_damage": (zone.aerial_damage_score, f"Aerial damage score {round(zone.aerial_damage_score)}/100"),
        "population_exposure": (zone.population_exposure, f"Population exposure {round(zone.population_exposure)}/100"),
        "road_access": (zone.road_access_difficulty, f"Road access difficulty {round(zone.road_access_difficulty)}/100"),
        "weather": (weather_risk, f"Weather risk {round(weather_risk)}/100"),
        "shelter": (shelter_risk(zone.shelter_distance_km), f"Shelter {zone.shelter_distance_km:g} km away"),
    }

    ranked = sorted(
        ((weight * value, label) for key, (value, label) in components.items() for weight in [WEIGHTS[key]]),
        key=lambda item: item[0],
        reverse=True,
    )

    factors = [label for score, label in ranked[:4] if score > 0]
    if not factors:
        factors.append("Low readings across all monitored factors")
    return factors


def shelter_risk(shelter_distance_km: float) -> float:
    return _shelter_risk(shelter_distance_km)


# ---------------------------------------------------------------------------
# Existing flood-response weights (sum to 1.0).
# ---------------------------------------------------------------------------
WEIGHTS = {
    "flood_severity": 0.244,
    "aerial_damage": 0.2,
    "population_exposure": 0.2,
    "road_access": 0.133,
    "weather": 0.167,
    "shelter": 0.056,
}

# Thresholds for mapping a 0-100 score onto an operational priority level.
LEVEL_THRESHOLDS = (
    (75.0, "Critical"),
    (55.0, "High"),
    (35.0, "Moderate"),
)

# ---------------------------------------------------------------------------
# Hazard-severity scoring: CV result + sensor reading + GIS proximity.
# Configurable fusion weights (S2-1). Normalised to sum 1.0 on set.
# ---------------------------------------------------------------------------
FUSION_WEIGHTS = {"cv": 0.35, "sensor": 0.40, "gis": 0.25}
FUSION_ALERT_BOOST = True
# Stage 3: predicted-risk weight in combined priority (adjustable slider)
PREDICTED_RISK_WEIGHT = 0.25


def get_predicted_weight() -> float:
    return float(PREDICTED_RISK_WEIGHT)


def set_predicted_weight(w: float) -> float:
    global PREDICTED_RISK_WEIGHT
    PREDICTED_RISK_WEIGHT = float(max(0.0, min(0.8, w)))
    return float(PREDICTED_RISK_WEIGHT)


def combined_priority(current_score_0_100: float, predicted_prob_0_1: float, predicted_weight: float | None = None) -> float:
    pw = float(predicted_weight) if predicted_weight is not None else float(PREDICTED_RISK_WEIGHT)
    pw = max(0.0, min(0.8, pw))
    return round(float(current_score_0_100) * (1.0 - pw) + float(predicted_prob_0_1) * 100.0 * pw, 1)


def get_fusion_weights() -> dict:
    return dict(FUSION_WEIGHTS)


def set_fusion_weights(cv: float | None = None, sensor: float | None = None, gis: float | None = None) -> dict:
    global FUSION_WEIGHTS
    w = dict(FUSION_WEIGHTS)
    if cv is not None:
        w["cv"] = float(cv)
    if sensor is not None:
        w["sensor"] = float(sensor)
    if gis is not None:
        w["gis"] = float(gis)
    total = w["cv"] + w["sensor"] + w["gis"]
    if total <= 0:
        raise ValueError("weights must sum > 0")
    for k in w:
        w[k] = round(w[k] / total, 4)
    FUSION_WEIGHTS = w
    return dict(FUSION_WEIGHTS)

# GIS proximity weights (sum to 1.0). These reward closeness to risk multipliers
# and high population exposure.
GIS_WEIGHTS = {
    "river": 0.4,
    "low_elevation": 0.35,
    "population": 0.25,
}

# Sensor alert weights (sum to 1.0). Water-level and rainfall are the most
# directly relevant signals for flood response; wind and temperature are softer.
SENSOR_WEIGHTS = {
    SensorType.WATER_LEVEL: 0.45,
    SensorType.RAINFALL: 0.30,
    SensorType.WIND: 0.10,
    SensorType.TEMPERATURE: 0.08,
    SensorType.SEISMIC: 0.07,
}

# Alert-to-risk mapping: how much a given alert level contributes at full weight.
ALERT_VALUE = {
    "normal": 0.0,
    "watch": 0.35,
    "warning": 0.70,
    "critical": 1.0,
}

# GIS proximity decay constants (km) — higher = slower decay.
GIS_DECAY = {
    "river": 3.0,
    "shelter": 6.0,
}

# Elevation thresholds used to translate DEM height into a 0..100 exposure score.
LOW_ELEV_MIN = 870.0   # metres
LOW_ELEV_MAX = 1000.0  # metres


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 3)


def _river_proximity_risk_km(d_km: float) -> float:
    """0..1 river-proximity risk; closer to a river == higher risk."""
    return clamp(1.0 - d_km / GIS_DECAY["river"])


def _population_exposure_from_density(density_index: float) -> float:
    """Translate a 0..1 density index into a 0..100 population-exposure score."""
    return clamp(density_index * 100.0)


def _elevation_risk_m(elevation_m: float) -> float:
    """0..100 low-elevation risk: lower ground == higher flood exposure."""
    if elevation_m <= LOW_ELEV_MIN:
        return 100.0
    if elevation_m >= LOW_ELEV_MAX:
        return 0.0
    return clamp((LOW_ELEV_MAX - elevation_m) / (LOW_ELEV_MAX - LOW_ELEV_MIN) * 100.0)


def _nearest_river_km(lat: float, lng: float, rivers_geojson: dict) -> float:
    """Return distance in km to the nearest river/drain segment feature."""
    features = rivers_geojson.get("features", [])
    best = 999.0
    for feat in features:
        geom = feat.get("geometry")
        if geom is None or geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue
        for i in range(len(coords) - 1):
            d = _seg_distance_km(lat, lng, coords[i], coords[i + 1])
            if d < best:
                best = d
    return best


def _seg_distance_km(lat: float, lng: float, a: list[float], b: list[float]) -> float:
    """Perpendicular distance (km) from a point to a lat/lng segment."""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    dx = (bx - ax) * 111.0 * cos(radians(12.96))
    dy = (by - ay) * 111.0
    if dx == 0.0 and dy == 0.0:
        return haversine_km(lat, lng, ay, ax)
    px = (lng - ax) * 111.0 * cos(radians(12.96))
    py = (lat - ay) * 111.0
    t = (px * dx + py * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx = ax + t * (bx - ax)
    cy = ay + t * (by - ay)
    return haversine_km(lat, lng, cy, cx)


def _nearest_elevation_km(lat: float, lng: float, elevation_geojson: dict) -> float:
    """Return the elevation (m) of the nearest elevation-grid cell."""
    best_val = 975.0
    best_dist = 999.0
    for feat in elevation_geojson.get("features", []):
        geom = feat.get("geometry")
        if geom is None or geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates", [[]])[0]
        if not coords:
            continue
        clat = sum(c[1] for c in coords) / len(coords)
        clng = sum(c[0] for c in coords) / len(coords)
        d = haversine_km(lat, lng, clat, clng)
        if d < best_dist:
            best_dist = d
            best_val = float(feat.get("properties", {}).get("elevation_m", 975.0))
    return best_val


def _nearest_population_density(lat: float, lng: float, population_geojson: dict) -> float:
    """Return the density index of the nearest population-density grid cell."""
    best_val = 0.0
    best_dist = 999.0
    for feat in population_geojson.get("features", []):
        geom = feat.get("geometry")
        if geom is None or geom.get("type") != "Polygon":
            continue
        coords = geom.get("coordinates", [[]])[0]
        if not coords:
            continue
        clat = sum(c[1] for c in coords) / len(coords)
        clng = sum(c[0] for c in coords) / len(coords)
        d = haversine_km(lat, lng, clat, clng)
        if d < best_dist:
            best_dist = d
            best_val = float(feat.get("properties", {}).get("density_index", 0.0))
    return best_val


def _sensor_zone_risk(
    zone: DisasterZone,
    stations: list[SensorStation],
    readings: list[SensorReading],
    sensor_service_radius_km: float = 4.0,
) -> tuple[float, int, list[str]]:
    """Compute sensor-derived hazard contribution for a zone.

    Returns (0..100 risk score, count of sensors in alert, list of reason strings).
    """
    reasons: list[str] = []
    weighted_alert_sum = 0.0
    weight_sum = 0.0
    nearby_alert_count = 0

    for station in stations:
        d = haversine_km(zone.latitude, zone.longitude, station.latitude, station.longitude)
        if d > sensor_service_radius_km:
            continue

        latest = station.latest_reading
        if latest is None:
            continue

        w = SENSOR_WEIGHTS.get(station.sensor_type, 0.1)
        alert_val = ALERT_VALUE.get(latest.alert_level.value, 0.0)

        # Proximity bonus: sensors nearer the zone count a bit more.
        prox = clamp(1.0 - d / sensor_service_radius_km)
        effective_w = w * (0.8 + 0.2 * prox)

        weighted_alert_sum += effective_w * alert_val
        weight_sum += effective_w

        if latest.alert_level != "normal":
            nearby_alert_count += 1
            label = station.sensor_type.value
            reasons.append(
                f"{station.name} ({label}) at {latest.value:.1f} {latest.unit} — "
                f"{latest.alert_level.value}"
            )

    if weight_sum <= 0:
        return 0.0, 0, reasons

    sensor_score = clamp((weighted_alert_sum / weight_sum) * 100.0)
    return round(sensor_score, 1), nearby_alert_count, reasons


def _gis_zone_risk(
    zone: DisasterZone,
    rivers_geojson: dict,
    elevation_geojson: dict,
    population_geojson: dict,
) -> tuple[float, list[str]]:
    """Compute GIS-proximity hazard contribution for a zone.

    Returns (0..100 combined risk score, list of reason strings).
    """
    reasons: list[str] = []

    river_km = _nearest_river_km(zone.latitude, zone.longitude, rivers_geojson)
    river_risk = _river_proximity_risk_km(river_km) * 100.0
    if river_km < 999.0:
        reasons.append(f"River/drain {river_km:.2f} km away (proximity risk {round(river_risk)}/100)")
    else:
        reasons.append("No river/drain within modelled AOI")

    elev = _nearest_elevation_km(zone.latitude, zone.longitude, elevation_geojson)
    elev_risk = _elevation_risk_m(elev)
    reasons.append(f"Elevation {elev:.1f} m (low-ground risk {round(elev_risk)}/100)")

    density = _nearest_population_density(zone.latitude, zone.longitude, population_geojson)
    pop_risk = _population_exposure_from_density(density)
    reasons.append(f"Population density index {density:.3f} (exposure {round(pop_risk)}/100)")

    gis_score = (
        GIS_WEIGHTS["river"] * river_risk
        + GIS_WEIGHTS["low_elevation"] * elev_risk
        + GIS_WEIGHTS["population"] * pop_risk
    )
    return round(clamp(gis_score), 1), reasons


def hazard_severity_from_score(score: float) -> HazardSeverity:
    """Map a 0..100 hazard score onto HazardSeverity."""
    if score >= 75.0:
        return HazardSeverity.CRITICAL
    if score >= 55.0:
        return HazardSeverity.HIGH
    if score >= 35.0:
        return HazardSeverity.MEDIUM
    return HazardSeverity.LOW


def compute_hazard_severity(
    zone: DisasterZone,
    stations: list[SensorStation],
    readings: list[SensorReading],
    rivers_geojson: dict,
    elevation_geojson: dict,
    population_geojson: dict,
    sensor_service_radius_km: float = 4.0,
) -> PriorityZone:
    """Combine CV result + sensor reading + GIS proximity into a hazard score.

    Inputs:
        zone           — DisasterZone (includes aerial_damage_score from CV)
        stations       — all sensor stations (for proximity search)
        readings       — recent readings (for alert enrichment)
        rivers_geojson — GeoJSON FeatureCollection of river/drain segments
        elevation_geojson — GeoJSON FeatureCollection of elevation cells
        population_geojson — GeoJSON FeatureCollection of population density cells
    """
    sensor_score, sensor_alert_count, sensor_reasons = _sensor_zone_risk(
        zone, stations, readings, sensor_service_radius_km
    )
    gis_score, gis_reasons = _gis_zone_risk(
        zone, rivers_geojson, elevation_geojson, population_geojson
    )

    # Final hazard score is a weighted blend of the three evidence sources.
    cv_score = clamp(float(zone.aerial_damage_score))
    cv_weight = FUSION_WEIGHTS["cv"]
    sensor_weight = FUSION_WEIGHTS["sensor"]
    gis_weight = FUSION_WEIGHTS["gis"]
    if FUSION_ALERT_BOOST and sensor_alert_count > 0:
        # Boost sensor influence when there are live alerts nearby.
        sensor_weight = round(min(0.9, sensor_weight + 0.05), 4)
        cv_weight = round(max(0.05, cv_weight - 0.05), 4)

    hazard_score = round(
        clamp(cv_score * cv_weight + sensor_score * sensor_weight + gis_score * gis_weight),
        1,
    )
    severity = hazard_severity_from_score(hazard_score)

    reasons = [
        f"Aerial (CV) damage score {round(cv_score)}/100",
        f"Sensor-derived risk {round(sensor_score)}/100 ({sensor_alert_count} alert(s) nearby)",
        f"GIS-proximity risk {round(gis_score)}/100",
        *sensor_reasons,
        *gis_reasons,
    ]

    # Population-at-risk proxy from the zone's population_exposure field.
    population_at_risk = int(zone.population_exposure * 120)

    return PriorityZone(
        id=zone.id,
        name=zone.name,
        latitude=zone.latitude,
        longitude=zone.longitude,
        severity=severity,
        score=hazard_score,
        reasons=reasons,
        cv_flood_pct=round(float(zone.aerial_damage_score), 1),
        sensor_alerts=sensor_alert_count,
        gis_risk_factors=gis_reasons,
        population_at_risk=population_at_risk,
        area_km2=0.25,
        confidence=round(
            min(100.0, 30.0 + sensor_alert_count * 10.0 + (100.0 - abs(cv_score - sensor_score)) * 0.3),
            1,
        ),
    )

# ---------------------------------------------------------------------------
# Legacy re-export: only the original analyze_zone is expected here by the
# existing routers/services. It is defined in scoring.py's original body and
# is re-exported so the rest of the app does not break.
# ---------------------------------------------------------------------------



