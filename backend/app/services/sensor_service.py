"""Sensor data ingestion and management service."""

from __future__ import annotations

import json
import threading
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import DATA_DIR
from app.models import (
    AlertLevel,
    SensorDataResponse,
    SensorIngestRequest,
    SensorReading,
    SensorStation,
    SensorType,
)

SENSORS_PATH = DATA_DIR / "sensors.json"
READINGS_PATH = DATA_DIR / "sensor_readings.json"


# Default thresholds for each sensor type (warning, critical)
DEFAULT_THRESHOLDS = {
    SensorType.RAINFALL: (50.0, 100.0),  # mm/hr
    SensorType.WATER_LEVEL: (2.0, 4.0),  # meters
    SensorType.SEISMIC: (4.0, 6.0),  # magnitude
    SensorType.TEMPERATURE: (35.0, 40.0),  # celsius
    SensorType.WIND: (60.0, 90.0),  # km/h
}

# Units for each sensor type
SENSOR_UNITS = {
    SensorType.RAINFALL: "mm/hr",
    SensorType.WATER_LEVEL: "m",
    SensorType.SEISMIC: "magnitude",
    SensorType.TEMPERATURE: "°C",
    SensorType.WIND: "km/h",
}


class SensorService:
    """Manages sensor stations and their readings."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stations: dict[str, SensorStation] = {}
        self._readings: list[SensorReading] = []
        self._load_data()
        if not self._stations:
            self._initialize_synthetic_stations()

    def _load_data(self) -> None:
        """Load stations and readings from JSON files."""
        if SENSORS_PATH.exists():
            with self._lock:
                raw = json.loads(SENSORS_PATH.read_text(encoding="utf-8"))
                for item in raw:
                    station = SensorStation.model_validate(item)
                    self._stations[station.id] = station
        if READINGS_PATH.exists():
            with self._lock:
                raw = json.loads(READINGS_PATH.read_text(encoding="utf-8"))
                self._readings = [SensorReading.model_validate(r) for r in raw]

    def _save_data(self) -> None:
        """Persist stations and readings to JSON files."""
        with self._lock:
            SENSORS_PATH.write_text(
                json.dumps([s.model_dump(mode="json") for s in self._stations.values()], indent=2),
                encoding="utf-8",
            )
            READINGS_PATH.write_text(
                json.dumps([r.model_dump(mode="json") for r in self._readings], indent=2),
                encoding="utf-8",
            )

    def _initialize_synthetic_stations(self) -> None:
        """Create synthetic sensor stations around Bengaluru AOI."""
        np.random.seed(20261014)
        stations_data = [
            # Rainfall sensors
            ("rain-bommanahalli", "Bommanahalli Rain Gauge", SensorType.RAINFALL, 12.9000, 77.6200),
            ("rain-koramangala", "Koramangala Rain Gauge", SensorType.RAINFALL, 12.9352, 77.6245),
            ("rain-bellandur", "Bellandur Rain Gauge", SensorType.RAINFALL, 12.9304, 77.6784),
            ("rain-whitefield", "Whitefield Rain Gauge", SensorType.RAINFALL, 12.9698, 77.7499),
            ("rain-yelahanka", "Yelahanka Rain Gauge", SensorType.RAINFALL, 13.1007, 77.5963),
            ("rain-majestic", "Majestic Rain Gauge", SensorType.RAINFALL, 12.9767, 77.5713),
            ("rain-hebbal", "Hebbal Rain Gauge", SensorType.RAINFALL, 13.0358, 77.5970),
            ("rain-electronic", "Electronic City Rain Gauge", SensorType.RAINFALL, 12.8452, 77.6602),
            # Water level sensors (near rivers/lakes)
            ("wl-bellandur-lake", "Bellandur Lake Level", SensorType.WATER_LEVEL, 12.9300, 77.6750),
            ("wl-vrishabhavathi", "Vrishabhavathi River", SensorType.WATER_LEVEL, 12.9600, 77.5200),
            ("wl-arkavathi", "Arkavathi River Gauge", SensorType.WATER_LEVEL, 12.8800, 77.6500),
            ("wl-hebbal-lake", "Hebbal Lake Level", SensorType.WATER_LEVEL, 13.0380, 77.5980),
            ("wl-yelahanka-lake", "Yelahanka Lake Level", SensorType.WATER_LEVEL, 13.1050, 77.5980),
            # Seismic sensors
            ("seis-bommasandra", "Bommasandra Seismic", SensorType.SEISMIC, 12.8000, 77.6800),
            ("seis-nandi", "Nandi Hills Seismic", SensorType.SEISMIC, 13.3700, 77.6800),
            # Temperature sensors
            ("temp-city-center", "City Center Temp", SensorType.TEMPERATURE, 12.9716, 77.5946),
            ("temp-whitefield", "Whitefield Temp", SensorType.TEMPERATURE, 12.9698, 77.7499),
            ("temp-electronic", "Electronic City Temp", SensorType.TEMPERATURE, 12.8452, 77.6602),
            # Wind sensors
            ("wind-kempegowda", "Kempegowda Airport Wind", SensorType.WIND, 13.1986, 77.7066),
            ("wind-city", "City Wind Station", SensorType.WIND, 12.9716, 77.5946),
        ]

        for sid, name, stype, lat, lng in stations_data:
            warn_thresh, crit_thresh = DEFAULT_THRESHOLDS[stype]
            station = SensorStation(
                id=sid,
                name=name,
                sensor_type=stype,
                latitude=lat,
                longitude=lng,
                unit=SENSOR_UNITS[stype],
                threshold_warning=warn_thresh,
                threshold_critical=crit_thresh,
                is_active=True,
            )
            self._stations[sid] = station

        self._save_data()
        self._generate_synthetic_readings()

    def _generate_synthetic_readings(self) -> None:
        """Generate synthetic historical readings for all stations."""
        now = datetime.now(timezone.utc)
        for station in self._stations.values():
            warn, crit = DEFAULT_THRESHOLDS[station.sensor_type]
            base_value = warn * 0.6  # Start below warning
            # Add variation based on location and type
            seed = zlib.crc32(station.id.encode()) & 0xFFFFFFFF
            rng = np.random.default_rng(seed)

            for i in range(48):  # 48 hours of history
                t = now - timedelta(hours=48 - i)
                # Simulate diurnal and random variation
                hour = t.hour
                diurnal = 0.2 * np.sin(2 * np.pi * hour / 24)
                noise = rng.normal(0, 0.1)
                if station.sensor_type == SensorType.RAINFALL:
                    # Rainfall is sporadic
                    value = max(0, base_value * (1 + diurnal + noise) + rng.exponential(5))
                elif station.sensor_type == SensorType.WATER_LEVEL:
                    value = max(0, base_value * (1 + diurnal + noise) + rng.uniform(-0.3, 0.5))
                elif station.sensor_type == SensorType.SEISMIC:
                    value = max(0, rng.exponential(1.5))  # Rare events
                elif station.sensor_type == SensorType.TEMPERATURE:
                    value = 28 + 4 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 1)
                else:  # WIND
                    value = max(0, 15 + 10 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 5))

                alert = self._compute_alert_level(station.sensor_type, value, warn, crit)
                reading = SensorReading(
                    sensor_id=station.id,
                    sensor_type=station.sensor_type,
                    value=round(value, 2),
                    unit=station.unit,
                    timestamp=t,
                    latitude=station.latitude,
                    longitude=station.longitude,
                    alert_level=alert,
                    threshold_warning=warn,
                    threshold_critical=crit,
                )
                self._readings.append(reading)
                # Update station's latest reading
                if station.latest_reading is None or reading.timestamp > station.latest_reading.timestamp:
                    station.latest_reading = reading
                station.readings_history.append(reading)

        self._save_data()

    def _compute_alert_level(
        self, sensor_type: SensorType, value: float, warn: float, crit: float
    ) -> AlertLevel:
        if value >= crit:
            return AlertLevel.CRITICAL
        if value >= warn:
            return AlertLevel.WARNING
        if value >= warn * 0.7:
            return AlertLevel.WATCH
        return AlertLevel.NORMAL

    def get_all_stations(self) -> list[SensorStation]:
        return list(self._stations.values())

    def get_station(self, sensor_id: str) -> Optional[SensorStation]:
        return self._stations.get(sensor_id)

    def get_readings(
        self, sensor_id: Optional[str] = None, hours: int = 24, sensor_type: Optional[SensorType] = None
    ) -> list[SensorReading]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        readings = [r for r in self._readings if r.timestamp >= cutoff]
        if sensor_id:
            readings = [r for r in readings if r.sensor_id == sensor_id]
        if sensor_type:
            readings = [r for r in readings if r.sensor_type == sensor_type]
        return sorted(readings, key=lambda r: r.timestamp, reverse=True)

    def get_latest_readings(self) -> list[SensorReading]:
        """Get the most recent reading for each active station."""
        latest = {}
        for r in self._readings:
            if r.sensor_id not in latest or r.timestamp > latest[r.sensor_id].timestamp:
                latest[r.sensor_id] = r
        return list(latest.values())

    def get_alerts(self, min_level: AlertLevel = AlertLevel.WATCH) -> list[SensorReading]:
        latest = self.get_latest_readings()
        level_order = {AlertLevel.NORMAL: 0, AlertLevel.WATCH: 1, AlertLevel.WARNING: 2, AlertLevel.CRITICAL: 3}
        min_val = level_order[min_level]
        return [r for r in latest if level_order[r.alert_level] >= min_val]

    def ingest_reading(self, req: SensorIngestRequest) -> SensorReading:
        """Ingest a new sensor reading."""
        station = self._stations.get(req.sensor_id)
        if not station:
            # Create station on the fly
            warn = req.threshold_warning or DEFAULT_THRESHOLDS[req.sensor_type][0]
            crit = req.threshold_critical or DEFAULT_THRESHOLDS[req.sensor_type][1]
            station = SensorStation(
                id=req.sensor_id,
                name=f"Auto-created {req.sensor_type.value}",
                sensor_type=req.sensor_type,
                latitude=req.latitude,
                longitude=req.longitude,
                unit=req.unit or SENSOR_UNITS[req.sensor_type],
                threshold_warning=warn,
                threshold_critical=crit,
            )
            self._stations[req.sensor_id] = station

        timestamp = req.timestamp or datetime.now(timezone.utc)
        warn = station.threshold_warning or DEFAULT_THRESHOLDS[req.sensor_type][0]
        crit = station.threshold_critical or DEFAULT_THRESHOLDS[req.sensor_type][1]
        alert = self._compute_alert_level(req.sensor_type, req.value, warn, crit)

        reading = SensorReading(
            sensor_id=req.sensor_id,
            sensor_type=req.sensor_type,
            value=req.value,
            unit=req.unit or station.unit,
            timestamp=timestamp,
            latitude=req.latitude,
            longitude=req.longitude,
            alert_level=alert,
            threshold_warning=warn,
            threshold_critical=crit,
        )

        with self._lock:
            self._readings.append(reading)
            station.latest_reading = reading
            station.readings_history.append(reading)
            # Keep only last 1000 readings per station
            if len(station.readings_history) > 1000:
                station.readings_history = station.readings_history[-1000:]
            self._save_data()

        return reading

    def ingest_batch(self, requests: list[SensorIngestRequest]) -> list[SensorReading]:
        return [self.ingest_reading(r) for r in requests]

    def get_all_data(self) -> SensorDataResponse:
        return SensorDataResponse(
            stations=self.get_all_stations(),
            readings=self.get_latest_readings(),
            alerts=self.get_alerts(),
            generated_at=datetime.now(timezone.utc),
        )

    def generate_csv(self, hours: int = 24) -> str:
        """Generate CSV export of recent readings."""
        import io
        import csv

        readings = self.get_readings(hours=hours)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["sensor_id", "sensor_type", "value", "unit", "timestamp", "latitude", "longitude", "alert_level"])
        for r in readings:
            writer.writerow([
                r.sensor_id, r.sensor_type.value, r.value, r.unit,
                r.timestamp.isoformat(), r.latitude, r.longitude, r.alert_level.value
            ])
        return output.getvalue()


_sensor_service: Optional[SensorService] = None


def get_sensor_service() -> SensorService:
    global _sensor_service
    if _sensor_service is None:
        _sensor_service = SensorService()
    return _sensor_service