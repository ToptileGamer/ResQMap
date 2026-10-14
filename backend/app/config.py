from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = APP_DIR.parent
DATA_DIR = APP_DIR / "data"


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and optional .env."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ResQMap AI Backend"
    environment: str = "development"
    frontend_origin: str = "http://localhost:5173"

    openweather_api_key: str = ""
    openweather_base_url: str = "https://api.openweathermap.org/data/2.5"

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    # Placeholder for a future routing provider; unused in the MVP.
    routing_api_key: str = ""

    request_timeout_seconds: float = 8.0

    # When true, never call external APIs (OpenWeather/Open-Meteo/LLM/tiles note);
    # all services use deterministic labelled-simulated data. Real user uploads
    # (imagery, sensors, GIS, SOS) still work offline.
    offline_mode: bool = False

    def has_openweather_key(self) -> bool:
        key = self.openweather_api_key.strip()
        return bool(key) and "PASTE_YOUR_" not in key

    def has_llm_config(self) -> bool:
        key = self.llm_api_key.strip()
        base = self.llm_base_url.strip()
        model = self.llm_model.strip()
        if not key or not base or not model:
            return False
        if "PASTE_YOUR_" in key or "PASTE_YOUR_" in base or "PASTE_YOUR_" in model:
            return False
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()
