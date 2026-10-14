from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR
from app.models import DisasterZone

ZONES_PATH = DATA_DIR / "zones.json"


class DataStore:
    """In-memory data store backed by JSON files.

    Zones are read-only reference data; live observations (e.g. drone
    analysis) are layered on top as in-memory overrides.
    """

    def __init__(self, zones_path: Path = ZONES_PATH) -> None:
        self._zones_path = zones_path
        self._lock = threading.Lock()
        self._zones: dict[str, DisasterZone] = {}
        self._overrides: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._zones = {zone.id: zone for zone in self._load_zones()}

    def _load_zones(self) -> list[DisasterZone]:
        if not self._zones_path.exists():
            return []
        raw = json.loads(self._zones_path.read_text(encoding="utf-8"))
        return [DisasterZone.model_validate(item) for item in raw]

    def set_zone_overrides(self, zone_id: str, values: dict) -> DisasterZone | None:
        """Apply live observations (e.g. drone analysis) to a zone.

        Overrides are layered on top of the static reference data whenever a
        zone is served, so any later analysis automatically uses the updated
        readings. Returns the updated zone, or None if the zone is unknown.
        """
        with self._lock:
            base = self._zones.get(zone_id)
            if base is None:
                return None
            merged = {**base.model_dump(), **values}
            self._overrides[zone_id] = merged
            updated = DisasterZone.model_validate(merged)
            self._zones[zone_id] = updated
        return updated

    def _apply_overrides(self, zone: DisasterZone) -> DisasterZone:
        with self._lock:
            overrides = self._overrides.get(zone.id)
        if not overrides:
            return zone
        return DisasterZone.model_validate({**zone.model_dump(), **overrides})

    def list_zones(self) -> list[DisasterZone]:
        return [self._apply_overrides(zone) for zone in self._zones.values()]

    def get_zone(self, zone_id: str) -> DisasterZone | None:
        zone = self._zones.get(zone_id)
        return self._apply_overrides(zone) if zone is not None else None


_store: DataStore | None = None


def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store
