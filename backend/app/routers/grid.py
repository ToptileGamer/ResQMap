from fastapi import APIRouter

from app.models import GridResponse
from app.services.grid_service import priority_grid

router = APIRouter(prefix="/grid", tags=["grid"])


@router.get("", response_model=GridResponse)
async def get_grid() -> GridResponse:
    return priority_grid()


@router.get("/top", response_model=list[dict])
async def top_cells() -> list[dict]:
    grid = priority_grid()
    return grid["cells"][:20]