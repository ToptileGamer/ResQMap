import logging

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.models import (
    AnalyzeAllResponse,
    ForecastResponse,
    ZoneAnalysisResponse,
    ZoneExplanationResponse,
)
from app.services.analysis_service import analyze_all, analyze_single
from app.services.data_store import get_store
from app.services.forecast_service import get_forecast
from app.services.llm_service import deterministic_explanation, generate_explanation

logger = logging.getLogger("resqmap.analysis")

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _require_analysis(zone_id: str) -> ZoneAnalysisResponse:
    analysis = analyze_single(zone_id, get_store(), get_settings())
    if analysis is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    return analysis


@router.get("/all", response_model=AnalyzeAllResponse)
async def analyze_all_zones() -> AnalyzeAllResponse:
    return analyze_all(get_store())


@router.get("/{zone_id}", response_model=ZoneAnalysisResponse)
async def analyze_zone_detail(zone_id: str) -> ZoneAnalysisResponse:
    return _require_analysis(zone_id)


@router.get("/{zone_id}/forecast", response_model=ForecastResponse)
async def forecast_zone(zone_id: str) -> ForecastResponse:
    zone = get_store().get_zone(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Zone '{zone_id}' not found")
    return get_forecast(zone, get_settings())


@router.get("/{zone_id}/explanation", response_model=ZoneExplanationResponse)
async def explain_zone(zone_id: str) -> ZoneExplanationResponse:
    analysis = _require_analysis(zone_id)
    try:
        text, source, used_llm, fallback_used = generate_explanation(analysis, get_settings())
    except Exception:  # noqa: BLE001 - explanation must never break the endpoint
        logger.exception("Explanation generation failed for %s", zone_id)
        text, source, used_llm, fallback_used = (
            deterministic_explanation(analysis),
            "deterministic_template",
            False,
            True,
        )
    return ZoneExplanationResponse(
        zone_id=analysis.zone_id,
        zone_name=analysis.zone_name,
        explanation=text,
        source=source,
        used_llm=used_llm,
        fallback_used=fallback_used,
        analysis=analysis,
    )
