"""Convenience launcher so `uvicorn main:app` works from the backend/ directory.

The real application lives in `app.main`.
"""

from app.main import app

__all__ = ["app"]
