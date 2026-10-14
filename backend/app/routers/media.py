from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Response

from app.config import DATA_DIR, get_settings

logger = logging.getLogger("resqmap.media")

router = APIRouter(prefix="/media", tags=["media"])

BASE = Path(__file__).resolve().parent.parent.parent / "media"
SAMPLES = BASE / "samples"


def _file(path: Path) -> Response:
    if not path.exists():
        return Response(status_code=404, content="Missing media file.")
    content_type, encoding = mimetypes.guess_type(str(path))
    return Response(content=path.read_bytes(), media_type=content_type or "application/octet-stream", headers={"Content-Length": str(path.stat().st_size)})


@router.get("/samples", response_model=list[dict])
async def list_samples() -> list[dict]:
    if not SAMPLES.exists():
        return []
    return [
        {"filename": p.name, "path": str(p.relative_to(BASE)), "size": p.stat().st_size, "mtime": p.stat().st_mtime}
        for p in SAMPLES.iterdir() if p.is_file()
    ]


@router.get("/samples/{filename}")
async def get_sample(filename: str) -> Response:
    safe = filename.replace("..", "").replace("/", "")
    return _file(SAMPLES / safe)
