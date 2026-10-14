# ResQMap AI Backend

Hackathon decision-support API for flood-disaster drone inspection ranking. It
combines simulated aerial damage, population exposure, road access, shelter
distance, weather, and citizen SOS reports into an explainable priority score.

> **Prototype.** This service uses simulated demonstration data and must not be
> used as the only source for life-critical decisions.

## Table of contents

- [Setup](#setup)
- [Run](#run)
- [API surface](#api-surface)
- [Architecture diagram](#architecture-diagram)
- [Data sources](#data-sources)
- [Feature-to-requirement mapping](#feature-to-requirement-mapping)
- [Configuration](#configuration)
- [Directory layout](#directory-layout)

---

## Setup

```bash
# 1. Create an isolated environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (optional, production)
cp .env.example .env
#   - OPENWEATHER_API_KEY   # live open-meteo/OpenWeather weather enrichment
#   - LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
#   - ENVIRONMENT=production
```

The backend does not require a database. It reads its reference data from the
`app/data/` JSON files and keeps a small in-memory `DataStore` (`app/services/data_store.py`).

### Requirements

- Python 3.12+
- FastAPI, pydantic (Pydantic v2), uvicorn
- numpy, shapely, scipy, pandas
- pillow, scikit-image (aerial CV)
- numpy, pandas, scipy, scikit-image, torch/torchvision, onnxruntime (optional, AI/ML helper stack)
- reportlab (PDF export)

### Verification

```bash
# App boots and the OpenAPI schema compiles
PYTHONPATH=backend .venv/bin/python -c "from fastapi import FastAPI; from app.main import app; assert bool(app.openapi())"

# Smoke the public endpoints
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/zones
```

## Run

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Open the interactive docs:

- `/docs` — FastAPI interactive API
- `/redoc` — ReDoc UI
- `/api/health` — liveness

## API surface

| Endpoint group | Purpose |
| --- | --- |
| `GET /api/zones` | List disaster zones (reference data + live overrides) |
| `GET /api/zones/{id}` | Single zone |
| `GET /api/analysis/all` | Rank every zone by priority score |
| `GET /api/analysis/{id}` | One zone's priority analysis |
| `GET /api/analysis/{id}/forecast` | Rain/wind risk projection 24 h |
| `GET /api/analysis/{id}/explanation` | Explainable text for the zone |
| `GET /api/grid` | 14×16 cell flood-priority grid (tabular + GeoJSON) |
| `GET /api/prediction/{id}` | 24 h DEM water-spread simulation |
| `GET /api/weather` | Weather risk per zone |
| `GET /api/gis/layers` | GeoJSON layer set (admin, rivers, roads, DEM, shelters, hospitals, population density, flood hazard) |
| `GET /api/hazard/zones` | Hazard severity = CV + sensor + GIS |
| `GET /api/hazard/dashboard` | Summary dashboard |
| `POST /api/export` | GeoJSON / PDF / PNG export |
| `POST /api/imagery/analyze` | Aerial flood analysis (real base64 or synthetic) |
| `GET /api/media/samples` | Sample media files served by the backend |

## Architecture diagram

```text
┌──────────────────────────────────────────────────────────────┐
│  FastAPI app /api (main.py)                                  │
│  CORSMiddleware · validation · unhandled-exception handler   │
└───────────────┬──────────────────────────────────────────────┘
                │
        ┌─────────┴─────────┐
        │  Routers          │  /zones, /analysis, /grid, /prediction,
        │  /weather         │     /gis, /hazard, /imagery, /export, /media
        └─────────┬─────────┘
                  │
        ┌─────────┴──────────┐
        │  Services          │  analysis · grid · prediction · gis_layer ·
        │  data_store        │     weather · sensor · llm · imagery ·
        │  geospatial        │     openmeteo · forecast · history
        └─────────┬──────────┘
                  │
   ┌──────────────┼───────────────────────┐
   │              │                       │
┌──▼──────┐  ┌────▼────┐          ┌───────▼───────┐
│ JSON    │  │JSON/CSV │          │ HTTP + cache  │
│ files   │  │exports  │          │ API calls     │
│ (zones) │  │/media   │          │ Open-Meteo,   │
│ sensors │  │/geojson │          │ OpenWeather   │
│ readings│  │/pdf /png│          │ LLM provider  │
└─────────┘  └─────────┘          └───────────────┘
```

### Layered runtime view

```text
Incoming request
   │
   ▼
API routers  (HTTP contracts + response models)
   │
   ▼
Service layer  (analysis, scoring, grid, perception, GIS, sensor, weather)
   │
   ▼
Data access  (DataStore reads zones/sensors/readings JSON; in-memory overrides)
   │
   ▼
Reference data / external APIs / model code
```

### Data flow through the analysis pipeline

```text
Zone reference data
   │
   ▼
weather + forecast fetch (Open-Meteo/OpenWeather, otherwise synthetic)
   │
   ▼
scoring (deterministic weighted fusion)
   ├── aerial (CV) damage
   ├── sensor alerts (nearby station + latest reading)
   └── GIS proximity (rivers/drains, low elevation, population density)
   │
   ▼
priority score + level (Critical / High / Moderate / Low)
   │
   ▼
routes → client (Dashboard, map, hazard panel, export)
```

### Sensor-to-hazard scoring

```text
sensor station ──within 4 km──► zone
   ▲
   │
latest reading (water_level, rainfall, seismic, temperature, wind)
   └── AlertLevel: normal / watch / warning / critical
        │
        ▼
SENSOR_WEIGHTS (water_level 0.45, rainfall 0.30, wind 0.10,
temperature 0.08, seismic 0.07) + proximity bonus
        │
        ▼
sensor risk score (0–100), alert count
        ▼
Fused hazard score =
  CV damage (0.35) + sensor (0.40) + GIS (0.25),
        or 0.30/0.45/0.25 when live alerts exist
```

---

## Data sources

### Reference data (local JSON, read at startup)

| File | Contents | Model |
| --- | --- | --- |
| `app/data/zones.json` | 8 flood zones in the Bengaluru AOI, with flood severity, aerial damage score, population exposure, road access difficulty, shelter distance, base weather risk, status | `DisasterZone` |
| `app/data/sensors.json` | ~20 synthetic sensor stations (rainfall, water level, seismic, temperature, wind) | `SensorStation` |
| `app/data/sensor_readings.json` | 48 hours of synthetic per-station readings with alert levels | `SensorReading` |

### Simulation layer (`app/services/`)

| Component | Represents | Notes |
| --- | --- | --- |
| `geospatial.py` | Synthetic DEM, river network, road lattice, WorldPop-style population density | Fixed seed `20261013`, deterministic, cached |
| `grid_service.py` | 14×16 priority grid = `flood × population × vulnerability` | Rescale to 0–100 |
| `prediction_service.py` | 24 h DEM water-spread simulation | Priority-flood, no scipy dependency |
| `gis_layer_service.py` | GeoJSON admin boundaries, rivers, roads, DEM, low-lying areas, shelters, hospitals, population density, flood hazard | Shapely polygon/line conversion for the map |
| `imagery_service.py` | Aerial flood analysis: flood-masking (muddy/blue/dark-blue water segmentation), mask-to-GeoJSON, synthetic drone frames | No neural model required for the demo |
| `sensor_service.py` | Ingest, alert computation, CSV export, 48 h synthetic history | Persists on ingest |
| `weather_service.py` | Per-zone weather risk | OpenWeather if `OPENWEATHER_API_KEY`, else deterministic simulated |
| `openmeteo_service.py` | Hourly precipitation forecast, GloFAS flood advisory, SRTM elevation lookup | Cached, falls back to synthetic |
| `forecast_service.py` | 24 h rain/wind forecast per zone | OpenWeather then synthetic |
| `history_service.py` | 7-day rolling per-zone history | Deterministic |
| `llm_service.py` | Explainable text generation | Optional; deterministic fallback when no LLM is configured |
| `analysis_service.py` | `analyze_all` / `analyze_single` orchestration | Wires weather + scoring |

### External services (optional, degrade to simulated)

| Service | Used by | Env var | Fallback |
| --- | --- | --- | --- |
| Open-Meteo (forecast, GloFAS, elevation) | `openmeteo_service` | None (free, no key) | Synthetic forecast |
| OpenWeather (forecast/weather) | `weather_service`, `forecast_service` | `OPENWEATHER_API_KEY` | Deterministic simulated weather/forecast |
| LLM provider (OpenAI-compatible chat) | `llm_service` | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Deterministic template explanation |

### Export assets

- GeoJSON: generated in-memory from priority zones (+ optional GIS layers)
- PDF: reportlab landscape A4 table + methodology
- PNG: PIL map snapshot with severity legend

---

## Feature-to-requirement mapping

The original product spec lists eight features. Below is how each feature in
`backend/app/routers/` maps to the implemented capability and its acceptance
criteria.

### 1. Zone analysis (ranked disaster zones)

- **Route:** `GET /api/analysis/all`
- **Implemented by:** `analysis_service.py` → `scoring_core.py` → `analyze_zone`
- **Inputs:** zone reference data + weather risk
- **Outputs:** `priority_score`, `priority_level` (Critical/High/Moderate/Low),
  `contributing_factors`, `weather_summary`, `recommended_action`
- **Acceptance criteria:**
  - All zones reachable by `/api/analysis/all`; each has a numeric score and a
    level.
  - Results are sorted by `priority_score` descending.
  - `weather_source_summary` reports whether weather came from
    `simulated` or `openweathermap`.
  - Weighted fusion of aerial damage, population exposure, road access,
    shelter distance, and weather risk.

### 2. Forest-fire & drone imagery / aerial analysis

- **Route:** `POST /api/imagery/analyze`
- **Implemented by:** `imagery_service.py` (`analyze_zone_frame`, `mask_to_geojson`)
- **Inputs:** zone + (optional) base64 aerial frame, or synthetic frame
- **Outputs:** `flood_affected_pct`, `damage_score`, `priority_score` after the
  drone observation, `preview_base64` / `mask_base64`, GeoJSON flood mask
- **Acceptance criteria:**
  - Accepts up to 15 MB image (real or synthetic).
  - Returns a plausible flood percentage and damage score.
  - Merges the aerial result into the zone's live readings (`aerial_damage_score`,
    `flood_severity`) and re-ranks the zone.
  - Produces a lightweight GeoJSON mask of the flooded area.

### 3. Sensor & disaster data ingestion

- **Route:** `POST /api/sensor/ingest` (sensor router pattern) + sensors JSON +
  `sensor_service.py`
- **Implemented by:** `sensor_service.py` (`SensorService`)
- **Inputs:** `SensorIngestRequest` (sensor id, type, value, unit, coords)
- **Outputs:** persisted reading + updated station latest reading + alert level
- **Acceptance criteria:**
  - `get_all_stations`, `get_latest_readings`, `get_readings(hours)` return
    recorded data.
  - Alert levels are deterministic from thresholds (normal/watch/warning/critical).
  - Ingest persists to disk so restarts do not lose observations.
  - CSV export of recent readings is available.

### 4. Hazard severity scoring

- **Route:** `GET /api/hazard/zones`, `GET /api/hazard/summary`, `GET /api/hazard/dashboard`
- **Implemented by:** `scoring_core.py` (`compute_hazard_severity`), `hazard.py`
- **Inputs:** zone + stations + readings + rivers/elevation/population GeoJSON
- **Outputs:** ranked `PriorityZone` list with severity, score, reasons, `cv_flood_pct`,
  `sensor_alerts`, `gis_risk_factors`, `population_at_risk`, `area_km2`, `confidence`
- **Acceptance criteria:**
  - Three evidence streams are fused, not a single score.
  - Sensor alerts increase the sensor weight; more alerts → higher confidence.
  - GIS proximity decays with distance (river 3 km, shelter 6 km).
  - Dashboard summarizes affected area, people/assets at risk, sensors in alert,
    critical/high counts.

### 5. Flood severity detection

- **Route:** `GET /api/analysis/{id}` (severity in the returned analysis) and
  `GET /api/hazard/zones` (severity field)
- **Implemented by:** `scoring_core.py` (`hazard_severity_from_score`)
- **Outputs:** `HazardSeverity` (Low/Medium/High/Critical) mapped from the score
- **Acceptance criteria:**
  - Threshold bands map a 0–100 score to Low/Medium/High/Critical.
  - Severity is reproducible for identical inputs.

### 6. Drone analysis (aerial / CV)

- **Route:** `POST /api/imagery/analyze`
- **Implemented by:** `imagery_service.py` + `scoring_core.py` fusion
- **Acceptance criteria:**
  - Mask threshold and colour segmentation (muddy, blue, dark-blue) produce
    plausible flooded percentages on synthetic frames.
  - Output preview and mask are small base64 JPEGs.
  - The analysis is persisted as a zone override and changes the downstream
    priority.

### 7. Cloud-based disaster mapping

- **Router:** `GET /api/gis/layers` + `gis_layer_service.py`
- **Acceptance criteria:**
  - Every named layer returns a valid GeoJSON `FeatureCollection` (not some
    malformed output).
  - Layers are swappable: fetch all, or a single `admin_boundaries`/`rivers`/
    `roads`/`elevation`/`low_lying_areas`/`shelters`/`hospitals`/
    `population_density`/`flood_hazard`.
  - Map consumes the GeoJSON directly via the frontend GIS client.

### 8. Export and visualization

- **Route:** `POST /api/export` (geojson, pdf, png) + `GET /api/export/geojson`
- **Implemented by:** `export.py` + `media.py`
- **Acceptance criteria:**
  - Returns a downloadable file with the correct media type and `Content-Disposition`.
  - GeoJSON is valid JSON with a FeatureCollection schema.
  - PDF and PNG are generated binary payloads, not errors.

---

## Configuration

Environment variables (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `ResQMap AI Backend` | Startup name |
| `ENVIRONMENT` | `development` | Used in `/api/health` |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS origin |
| `OPENWEATHER_API_KEY` | empty | Live weather; server falls back to simulated weather |
| `OPENWEATHER_BASE_URL` | openweathermap URL | Weather API base |
| `LLM_API_KEY` | empty | Optional LLM |
| `LLM_BASE_URL` | empty | Optional LLM base |
| `LLM_MODEL` | empty | Optional LLM model |
| `ROUTING_API_KEY` | empty | Reserved future provider |
| `REQUEST_TIMEOUT_SECONDS` | `8` | Upstream fetch timeout |

All settings are loaded by `Settings` (pydantic-settings) and cached by
`get_settings()`.

---

## Directory layout

```text
backend/
├── app/
│   ├── __init__.py            # package marker + version
│   ├── config.py              # Settings (environment variables)
│   ├── main.py                # FastAPI app, middleware, exception handlers
│   ├── models.py              # Pydantic request/response contracts
│   ├── data/                  # reference JSON
│   │   ├── zones.json         # 8 disaster zones
│   │   ├── sensors.json       # sensor stations
│   │   └── sensor_readings.json   # 48 h readings
│   ├── routers/               # /api routes
│   │   ├── zones.py
│   │   ├── analysis.py
│   │   ├── weather.py
│   │   ├── grid.py
│   │   ├── prediction.py
│   │   ├── gis.py
│   │   ├── hazard.py
│   │   ├── imagery.py
│   │   ├── export.py
│   │   ├── media.py
│   │   └── __init__.py
│   ├── services/
│   │   ├── data_store.py      # in-memory JSON-backed store
│   │   ├── scoring_core.py    # hazard + priority scoring
│   │   ├── analysis_service.py
│   │   ├── grid_service.py
│   │   ├── prediction_service.py
│   │   ├── gis_layer_service.py
│   │   ├── weather_service.py
│   │   ├── openmeteo_service.py
│   │   ├── sensor_service.py
│   │   ├── llm_service.py
│   │   ├── imagery_service.py
│   │   ├── forecast_service.py
│   │   └── history_service.py
│   └── __pycache__/
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## S1/S2 Stage Coverage (QA 2026-10-14)
Run: `cd backend && PYTHONPATH=. python3 -m uvicorn app.main:app --port 8000` + `cd frontend && npm run dev -- --port 5174` (proxies /api → :8000).
Simulated (labelled): DEM/rivers/roads/population (seed 20261013), drone frames, sensor history, hazard fusion defaults. Live (optional): OpenWeather/Open-Meteo, LLM.
- S1-1 imagery: POST /api/imagery/analyze + GET /api/media/samples (8 PNGs); colour-segmentation flood mask + GeoJSON; area% differs per zone (92.4/93.6/93.3).
- S1-2 sensors: POST /api/sensor ingest (below→normal, above→critical verified); 20 stations with lat/lon on map; CSV via service.
- S1-3 GIS: GET /api/gis/layers (9 labelled-simulated layers); LayerPanel toggles + opacity + legend.
- S1-4 fusion: GET /api/hazard/zones fuses CV+sensor+GIS (configurable weights); reasons show contributions; weight change re-ranks (52.9→76.1 verified).
- S1-5 viz: Dashboard ZoneMap (markers, heat, GIS, hazard) + legend + opacity + popups.
- S1-6 priority: GET /api/analysis/all + /hazard/zones ranked with reasons; KPI people_at_risk 62880 verified by hand (sum exposure*120).
- S1-7 export: GET /api/export/geojson (parsed), POST /api/export pdf/png (open verified).
- S2-1 weights: GET/POST /api/hazard/weights; re-rank verified.
- S2-2 search: POST /api/routes/search (N drones, battery incl return-to-base, coverage%, in-bounds); 1 vs 3 drones + tiny-battery tested.
- S2-3 rescue: POST /api/routes/rescue (shortest|safest, blocked_edges avoided, unreachable flagged not crashed).
- S2-4 allocation: POST /api/allocation/assign + /resources/drone|team editable + /summary (utilisation, unserved, quantity; zero→empty).
- S2-5 what-if: POST /api/whatif (weights+resources+blocked → ranking+routes+allocation+KPIs).
- S2-6 export: /api/export/routes (GeoJSON), /api/allocation/export.csv, briefing PDF/PNG.

---

## Real-Data Operation (100% working site)
- SOS: `GET/POST /api/sos` + `GET /api/sos/geojson` — real user reports persisted to `app/data/sos.json` (source=real-user). Frontend SOS page creates + filters + shows source badge.
- Sensors: `POST /api/sensor` (JSON) + `POST /api/sensor/upload-csv` (CSV columns sensor_id,sensor_type,value,unit,latitude,longitude[,timestamp]) + `GET /api/sensor/export.csv`. Stations have lat/lon and render on map.
- Imagery: `POST /api/imagery/analyze` (base64) + `POST /api/imagery/upload` (multipart JPEG/PNG ≤15MB). Real uploads fold into live scores with note `Real upload <filename>`.
- GIS: `GET /api/gis/layers` (source per layer: simulated|real-upload) + `POST /api/gis/layers/upload` {layer_type, geojson FeatureCollection ≤5000 feats}. LayerPanel shows REAL/SIM badge.
- Weather/LLM: live when keys set, else labelled-simulated; `OFFLINE_MODE=true` forces synthetic with no external calls.
- Timing: every response carries `X-Processing-MS`; `/api/health` returns `processing_ms`, `offline_mode`, `data_mode`.

---

## Stage 3 — Innovation & Intelligence (Predictive Flood Risk)

Scenario: FLOOD · Region: Bengaluru AOI (12.79–13.14, 77.44–77.78). OFFLINE_MODE supported: weather/history/elevation cached or bundled; external calls only behind online flag, fail gracefully to labelled-simulated.

Architecture:
```
sensors + CV + zones ─┐
Open-Meteo forecast (cached, offline-safe) ─┤
DEM/slope/river-dist/pop (synthetic AOI, seed 20261013) ─┤
historical events EVT-01..10 (simulated, bundled risk_history.json) ─┴─► prediction_features (28x32 grid, ~1.25km cells)
   ├─► L1 rule engine (rainfall×elevation×river×slope×trend, configurable weights, per-cell contributions)
   ├─► L2 ML RandomForest(160 trees, depth 12, seed 20261014, train EVT-01..08 / test EVT-09..10)
   └─► L3 DEM downhill spread via /prediction (T+1/T+3/T+6)
        └─► /risk/grid + /risk/predicted-zones + heatmap + uncertainty(±20% rain) ─► priority-zones (current+predicted) ─► allocate(target) + rescue(avoid_predicted) + whatif + exports
```

Data sources: bundled simulated history (labelled), synthetic DEM/rivers/pop, cached Open-Meteo rainfall, live CV + sensors. All simulated data labelled in UI + README.

Model comparison (measured 2026-10-14): ML acc 0.769, prec 0.382, rec 0.405, AUC 0.631, CM [[1244,217],[197,134]]; rule conservative (mean 0.228, 0 high cells) vs ML sensitive (mean 0.274, 111 high cells). Default = ML (probabilistic + learns interactions + importances: elevation 0.20, road_access 0.14, rainfall 0.12); rule kept for full explainability. Backtest EVT-09: pred 191 vs actual 173 cells, IoU 0.22, acc 0.74.

Stage 3 requirement map: A inputs→/risk/grid cells+features; B L1/L2/L3→/risk/* + /model-metrics; C heatmap+T-slider+click+uncertainty→/risk page; D predicted weight slider→/hazard/priority-zones, target switch→/allocation/by-target, avoid_predicted→/routes/rescue, whatif recomputes all; E backtest→/risk/backtest + model card→/risk/model-card, input-sensitivity tests; F panels + /export/risk + /export/predictions.csv + /export/risk-briefing; G loading/error/empty states, responsive, this README.

Known limitations: simulated history/terrain (not authoritative); 28x32 cells (~1.25km, no street detail); first prediction ~5s (weather fetch) then cached ~ms; ML AUC modest (0.63) — honest, reported.
