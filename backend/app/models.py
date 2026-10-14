from datetime import datetime
from typing import Any, Literal, Optional
from enum import Enum

from pydantic import BaseModel, Field


class SensorType(str, Enum):
    RAINFALL = "rainfall"
    WATER_LEVEL = "water_level"
    SEISMIC = "seismic"
    TEMPERATURE = "temperature"
    WIND = "wind"


class AlertLevel(str, Enum):
    NORMAL = "normal"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


class DisasterZone(BaseModel):
    id: str
    name: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    disaster_type: str = "flood"
    flood_severity: float = Field(..., ge=0, le=100)
    aerial_damage_score: float = Field(..., ge=0, le=100)
    population_exposure: float = Field(..., ge=0, le=100)
    road_access_difficulty: float = Field(..., ge=0, le=100)
    shelter_distance_km: float = Field(..., ge=0)
    base_weather_risk: float = Field(..., ge=0, le=100)
    status: str
    last_updated: datetime

    # Filled in when a drone aerial analysis has been applied to this zone.
    aerial_analyzed_at: Optional[datetime] = None
    aerial_analysis_note: Optional[str] = None

    # Sensor-related fields
    sensors_nearby: int = 0
    sensors_in_alert: int = 0


class HistoryPoint(BaseModel):
    timestamp: datetime
    rainfall_mm: float
    water_level: float = Field(..., ge=0, le=100)


class HistoryResponse(BaseModel):
    zone_id: str
    points: list[HistoryPoint]
    source: str
    generated_at: datetime


class ForecastPoint(BaseModel):
    timestamp: datetime
    expected_rainfall_mm: float
    expected_wind_kmh: float
    risk_projection: float


class ForecastResponse(BaseModel):
    zone_id: str
    points: list[ForecastPoint]
    source: str
    generated_at: datetime


class AerialAnalysisRequest(BaseModel):
    zone_id: str
    image_base64: Optional[str] = None
    description: Optional[str] = None


class AerialAnalysisResponse(BaseModel):
    zone_id: str
    zone_name: str
    method: Literal["color_segmentation", "synthetic_seed"]
    flood_affected_pct: float = Field(..., ge=0, le=100)
    damage_score: float = Field(..., ge=0, le=100)
    image_width: int
    image_height: int
    preview_base64: str
    mask_base64: str
    description: Optional[str] = None
    affected_priority_score: float
    affected_priority_level: str
    geojson: Optional[dict[str, Any]] = None
    analyzed_at: datetime


class WeatherRisk(BaseModel):
    zone_id: str
    rainfall_mm: float = Field(..., ge=0)
    wind_speed_kmh: float = Field(..., ge=0)
    weather_condition: str
    weather_risk_score: float = Field(..., ge=0, le=100)
    source: str
    fetched_at: datetime
    status_message: Optional[str] = None


class ZoneAnalysisResponse(BaseModel):
    zone_id: str
    zone_name: str
    priority_score: float
    priority_level: Literal["Critical", "High", "Moderate", "Low"]
    contributing_factors: list[str]
    weather_summary: str
    weather: WeatherRisk
    recommended_action: str
    updated_at: datetime


class AnalyzeAllResponse(BaseModel):
    results: list[ZoneAnalysisResponse]
    total_zones: int
    critical_count: int
    high_count: int
    weather_source_summary: dict[str, int]
    generated_at: datetime


class ZoneExplanationResponse(BaseModel):
    zone_id: str
    zone_name: str
    explanation: str
    source: Literal["deterministic_template", "llm", "llm_fallback"]
    used_llm: bool
    fallback_used: bool
    analysis: ZoneAnalysisResponse


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


class RootResponse(BaseModel):
    message: str
    docs: str
    health: str


# ---------------------------------------------------------------------------
# Stage 2: grid prioritisation
# ---------------------------------------------------------------------------

class Bounds(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float


class GridCell(BaseModel):
    id: str
    lat: float
    lng: float
    elevation_m: float
    slope_deg: float
    distance_river_km: float
    flood_probability: float = Field(..., ge=0, le=1)
    population_density: float = Field(..., ge=0, le=1)
    vulnerability: float = Field(..., ge=0, le=1)
    priority_score: float = Field(..., ge=0, le=100)
    priority_level: Literal["Critical", "High", "Moderate", "Low"]


class GridResponse(BaseModel):
    bounds: Bounds
    rain_factor: float
    grid_shape: dict[str, int]
    cells: list[GridCell]
    geojson: dict[str, Any]
    summary: dict[str, Any]
    formula: str
    generated_at: datetime


# ---------------------------------------------------------------------------
# Stage 3: spread prediction
# ---------------------------------------------------------------------------

class SpreadStep(BaseModel):
    hours: int
    label: str
    flooded_cells: int
    flood_extent_pct: float


class SpreadResponse(BaseModel):
    zone_id: str
    zone_name: str
    method: str
    model: str
    rain_factor: float
    steps: list[SpreadStep]
    expansions: list[dict[str, Any]]
    rain_multiplier: float = Field(default=1.0, ge=0.5, le=4.0)
    selected_lat: float
    selected_lng: float
    generated_at: datetime


# ---------------------------------------------------------------------------
# Sensor data models
# ---------------------------------------------------------------------------

class SensorReading(BaseModel):
    sensor_id: str
    sensor_type: SensorType
    value: float
    unit: str
    timestamp: datetime
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    alert_level: AlertLevel = AlertLevel.NORMAL
    threshold_warning: Optional[float] = None
    threshold_critical: Optional[float] = None


class SensorStation(BaseModel):
    id: str
    name: str
    sensor_type: SensorType
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    unit: str
    threshold_warning: Optional[float] = None
    threshold_critical: Optional[float] = None
    is_active: bool = True
    latest_reading: Optional[SensorReading] = None
    readings_history: list[SensorReading] = []


class SensorDataResponse(BaseModel):
    stations: list[SensorStation]
    readings: list[SensorReading]
    alerts: list[SensorReading]
    generated_at: datetime


class SensorIngestRequest(BaseModel):
    sensor_id: str
    sensor_type: SensorType
    value: float
    unit: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timestamp: Optional[datetime] = None
    threshold_warning: Optional[float] = None
    threshold_critical: Optional[float] = None


# ---------------------------------------------------------------------------
# GIS / GeoJSON layer models
# ---------------------------------------------------------------------------

class GISLayerType(str, Enum):
    ADMIN_BOUNDARIES = "admin_boundaries"
    RIVERS = "rivers"
    ROADS = "roads"
    ELEVATION = "elevation"
    LOW_LYING_AREAS = "low_lying_areas"
    SHELTERS = "shelters"
    HOSPITALS = "hospitals"
    POPULATION_DENSITY = "population_density"
    FLOOD_HAZARD = "flood_hazard"


class GISLayer(BaseModel):
    id: str
    name: str
    layer_type: GISLayerType
    geojson: dict[str, Any]
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0, le=1)
    description: Optional[str] = None
    source: str = "simulated"
    style: Optional[dict[str, Any]] = None


class GISLayersResponse(BaseModel):
    layers: list[GISLayer]
    bounds: dict[str, float]
    generated_at: datetime


# ---------------------------------------------------------------------------
# Fused visualization models
# ---------------------------------------------------------------------------

class HazardSeverity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class PriorityZone(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    severity: HazardSeverity
    score: float
    reasons: list[str]
    cv_flood_pct: float
    sensor_alerts: int
    gis_risk_factors: list[str]
    population_at_risk: int
    area_km2: float
    confidence: float


class PriorityZonesResponse(BaseModel):
    zones: list[PriorityZone]
    total_zones: int
    critical_count: int
    high_count: int
    generated_at: datetime


class SummaryDashboardResponse(BaseModel):
    affected_area_km2: float
    zones_count: int
    people_at_risk: int
    assets_at_risk: int
    sensors_in_alert: int
    critical_zones: int
    high_zones: int
    generated_at: datetime
    alert_breakdown: dict[str, int] = {}
    severity_distribution: dict[str, int] = {}
    top_risk_factors: list[dict[str, object]] = []


# ---------------------------------------------------------------------------
# Export models
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    format: Literal["geojson", "pdf", "png"]
    layers: Optional[list[str]] = None
    bounds: Optional[dict[str, float]] = None


class ExportResponse(BaseModel):
    success: bool
    file_path: Optional[str] = None
    download_url: Optional[str] = None
    message: str
