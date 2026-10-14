from __future__ import annotations

import json
import logging
import urllib.request

from app.config import Settings
from app.models import ZoneAnalysisResponse

logger = logging.getLogger("resqmap.llm")


def deterministic_explanation(analysis: ZoneAnalysisResponse) -> str:
    factors = "; ".join(analysis.contributing_factors) or "no dominant factors"
    return (
        f"{analysis.zone_name} is rated {analysis.priority_level} with a priority score of "
        f"{analysis.priority_score:.0f}/100. The main drivers are: {factors}. "
        f"Weather context: {analysis.weather_summary} "
        f"Recommended action: {analysis.recommended_action}"
    )


def _build_base_url(raw: str) -> str:
    base = raw.strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base


def _call_llm(analysis: ZoneAnalysisResponse, settings: Settings) -> str | None:
    try:
        prompt = (
            "You are a disaster-response decision-support assistant. In 2-4 concise sentences, "
            "explain to an incident commander why this flood zone received its priority score and "
            "what they should do. Do not invent data beyond what is given.\n\n"
            f"Zone: {analysis.zone_name}\n"
            f"Priority score: {analysis.priority_score:.0f}/100 ({analysis.priority_level})\n"
            f"Contributing factors: {', '.join(analysis.contributing_factors)}\n"
            f"Weather: {analysis.weather_summary}\n"
            f"Recommended action: {analysis.recommended_action}"
        )

        body = json.dumps(
            {
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": "You produce brief, factual operational explanations."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 220,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{_build_base_url(settings.llm_base_url)}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.llm_api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=settings.request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001 - never let provider issues break the API
        logger.warning("LLM call failed, using deterministic fallback: %s", exc)
        return None


def generate_explanation(
    analysis: ZoneAnalysisResponse, settings: Settings
) -> tuple[str, str, bool, bool]:
    """Return (explanation, source, used_llm, fallback_used)."""
    if settings.offline_mode:
        return deterministic_explanation(analysis), "deterministic_template", False, False
    if settings.has_llm_config():
        text = _call_llm(analysis, settings)
        if text:
            return text, "llm", True, False
        return deterministic_explanation(analysis), "llm_fallback", False, True
    return deterministic_explanation(analysis), "deterministic_template", False, False
