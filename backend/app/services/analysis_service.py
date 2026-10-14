from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.models import AnalyzeAllResponse, ZoneAnalysisResponse
from app.scoring_core import analyze_zone
from app.services.data_store import DataStore
from app.services.weather_service import get_weather


def analyze_single(zone_id: str, store: DataStore, settings: Settings) -> ZoneAnalysisResponse | None:
    zone = store.get_zone(zone_id)
    if zone is None:
        return None
    weather = get_weather(zone, settings)
    return analyze_zone(zone, weather)


def analyze_all(store: DataStore, settings: Settings | None = None) -> AnalyzeAllResponse:
    settings = settings or get_settings()
    results: list[ZoneAnalysisResponse] = []
    weather_source_summary: dict[str, int] = {}

    for zone in store.list_zones():
        weather = get_weather(zone, settings)
        weather_source_summary[weather.source] = weather_source_summary.get(weather.source, 0) + 1
        results.append(analyze_zone(zone, weather))

    results.sort(key=lambda item: item.priority_score, reverse=True)
    return AnalyzeAllResponse(
        results=results,
        total_zones=len(results),
        critical_count=sum(1 for item in results if item.priority_level == "Critical"),
        high_count=sum(1 for item in results if item.priority_level == "High"),
        weather_source_summary=weather_source_summary,
        generated_at=datetime.now(timezone.utc),
    )
