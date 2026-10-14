from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.models import GISLayer, GISLayerType, GISLayersResponse
from app.services.gis_layer_service import layer, bounds_for_layer, set_custom_layer, get_layer_source

router = APIRouter(prefix="/gis", tags=["gis"])

_LAYER_META: list[tuple[GISLayerType, str, str]] = [
    (GISLayerType.ADMIN_BOUNDARIES, "Administrative Boundaries", "Nested state/district/city/ward boundaries"),
    (GISLayerType.RIVERS, "Rivers & Drainage", "River and drain network (simulated Arkavathi / Vrishabhavathi stand-ins)"),
    (GISLayerType.ROADS, "Roads", "Primary and secondary road lattice over the AOI"),
    (GISLayerType.ELEVATION, "Elevation Model", "SRTM-style DEM cell grid with elevation and slope"),
    (GISLayerType.LOW_LYING_AREAS, "Low-Lying Areas", "Areas below the flood-prone elevation threshold"),
    (GISLayerType.SHELTERS, "Shelters", "Community shelters and triage centres"),
    (GISLayerType.HOSPITALS, "Hospitals", "Hospitals and hospital triage centres"),
    (GISLayerType.POPULATION_DENSITY, "Population Density", "WorldPop-style density grid with estimated population"),
    (GISLayerType.FLOOD_HAZARD, "Flood Hazard", "Derived flood-hazard layer (currently mirrors low-lying areas)"),
]


@router.get("/layers", response_model=GISLayersResponse)
async def gis_layers(
    layer_type: GISLayerType | None = Query(
        None, description="If provided, return only this layer. Otherwise return all layers."
    ),
) -> GISLayersResponse:
    bounds = bounds_for_layer("admin_boundaries")
    now = datetime.now(timezone.utc)

    if layer_type is not None:
        geojson = layer(layer_type.value)
        return GISLayersResponse(
            layers=[
                GISLayer(
                    id=f"layer-{layer_type.value}",
                    name=dict(_LABEL_FOR_TYPE).get(layer_type.value, layer_type.value),
                    layer_type=layer_type,
                    geojson=geojson,
                    visible=True,
                    opacity=1.0,
                    description=dict(_DESC_FOR_TYPE).get(layer_type.value),
                    source=get_layer_source(layer_type.value),
                )
            ],
            bounds=bounds,
            generated_at=now,
        )

    layers: list[GISLayer] = []
    for lt, name, desc in _LAYER_META:
        geojson = layer(lt.value)
        layers.append(
            GISLayer(
                id=f"layer-{lt.value}",
                name=name,
                layer_type=lt,
                geojson=geojson,
                visible=True,
                opacity=1.0,
                description=desc,
                source=get_layer_source(lt.value),
            )
        )

    # Flood hazard layer is derived from low-lying areas for the demo.
    if GISLayerType.FLOOD_HAZARD not in [lt for lt, *_ in _LAYER_META]:
        ll_geojson = layer(GISLayerType.LOW_LYING_AREAS.value)
        layers.append(
            GISLayer(
                id="layer-flood_hazard",
                name="Flood Hazard",
                layer_type=GISLayerType.FLOOD_HAZARD,
                geojson=ll_geojson,
                visible=True,
                opacity=0.55,
                description="Derived flood-hazard footprint (high-risk low-lying cells).",
                source="simulated",
                style={"fillOpacity": 0.55, "color": "#d94800", "weight": 1},
            )
        )

    return GISLayersResponse(layers=layers, bounds=bounds, generated_at=now)


@router.post("/layers/upload")
async def upload_layer(body: dict) -> dict:
    """Real-data GeoJSON upload: {layer_type, geojson}. Source becomes real-upload."""
    lt = str(body.get("layer_type", "")).strip()
    gj = body.get("geojson")
    valid = {t.value for t in GISLayerType}
    if lt not in valid:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"layer_type must be one of {sorted(valid)}")
    if not isinstance(gj, dict) or gj.get("type") != "FeatureCollection" or not isinstance(gj.get("features"), list):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="geojson must be a FeatureCollection with features[]")
    if len(gj["features"]) > 5000:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Too many features (limit 5000)")
    set_custom_layer(lt, gj)
    return {"layer_type": lt, "features": len(gj["features"]), "source": "real-upload"}


_LABEL_FOR_TYPE = {lt.value: name for lt, name, _ in _LAYER_META}
_DESC_FOR_TYPE = {lt.value: desc for lt, _, desc in _LAYER_META}
