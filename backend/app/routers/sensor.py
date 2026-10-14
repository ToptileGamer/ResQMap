from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.config import get_settings
from app.models import SensorDataResponse, SensorIngestRequest, SensorReading, SensorStation, SensorType
from app.services.data_store import get_store
from app.services.sensor_service import get_sensor_service

router = APIRouter(prefix="/sensor", tags=["sensor"])


@router.get("", response_model=SensorDataResponse)
async def list_sensors() -> SensorDataResponse:
    """Return all stations, their latest readings, and current alerts."""
    return get_sensor_service().get_all_data()


@router.get("/stations", response_model=list[SensorStation])
async def list_stations() -> list[SensorStation]:
    """List every managed sensor station."""
    return get_sensor_service().get_all_stations()


@router.get("/stations/{sensor_id}", response_model=SensorStation)
async def get_station(sensor_id: str) -> SensorStation:
    """Get a single station (404 if it does not exist)."""
    station = get_sensor_service().get_station(sensor_id)
    if station is None:
        raise HTTPException(status_code=404, detail=f"Sensor station '{sensor_id}' not found")
    return station


@router.get("/stations/{sensor_id}/readings", response_model=list[SensorReading])
async def get_station_readings(
    sensor_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    sensor_type: str | None = Query(default=None, description="Optional sensor_type filter (rainfall, water_level, seismic, temperature, wind)"),
) -> list[SensorReading]:
    """Return recent readings for one station, optionally filtered by type."""
    sensor_type_enum = None
    if sensor_type is not None:
        try:
            from app.models import SensorType

            sensor_type_enum = SensorType(sensor_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown sensor_type '{sensor_type}'")
    readings = get_sensor_service().get_readings(
        sensor_id=sensor_id, hours=hours, sensor_type=sensor_type_enum
    )
    if not readings:
        raise HTTPException(status_code=404, detail=f"No readings for sensor '{sensor_id}' in the last {hours} hours")
    return readings


@router.post("", response_model=SensorReading)
async def ingest_sensor(req: SensorIngestRequest) -> SensorReading:
    """Ingest one sensor observation.

    Persists the reading, updates the station's latest reading, recomputes the
    alert level, and writes the observation to disk.
    """
    reading = get_sensor_service().ingest_reading(req)
    return reading


@router.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)) -> dict:
    """Real-data CSV upload: sensor_id,sensor_type,value,unit,latitude,longitude[,timestamp]."""
    import csv, io
    from datetime import datetime
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV too large (limit 5 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 text")
    reader = csv.DictReader(io.StringIO(text))
    required = {"sensor_id", "sensor_type", "value", "latitude", "longitude"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=400, detail=f"CSV needs columns: {sorted(required)}")
    svc = get_sensor_service()
    ok, errors = 0, []
    for i, row in enumerate(reader, 2):
        try:
            req = SensorIngestRequest(
                sensor_id=row["sensor_id"].strip(),
                sensor_type=SensorType(row["sensor_type"].strip()),
                value=float(row["value"]),
                unit=(row.get("unit") or "").strip() or "unknown",
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                timestamp=datetime.fromisoformat(row["timestamp"]) if row.get("timestamp") else None,
            )
            svc.ingest_reading(req)
            ok += 1
        except Exception as e:
            errors.append(f"row {i}: {e}")
            if len(errors) > 20:
                break
    return {"ingested": ok, "errors": errors, "source": "real-user-csv", "filename": file.filename}


@router.get("/export.csv")
async def export_csv(hours: int = Query(default=24, ge=1, le=168)):
    from fastapi.responses import Response
    csv_text = get_sensor_service().generate_csv(hours=hours)
    return Response(content=csv_text, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="sensors.csv"'})
