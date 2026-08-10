"""Misen Companion API.

Phase 0 ships liveness only. Pantry, menu, scaling, shopping, reminders and
the Basil chat proxy arrive in phases 1 and 5 (PRD §5).
"""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

logger = logging.getLogger(__name__)

try:
    __version__ = version("misen-companion")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+dev"

settings = get_settings()

app = FastAPI(
    title="Misen Companion",
    version=__version__,
    description="Pantry, weekly menu, recipe scaling, shopping, and Basil.",
)


@app.get("/health", tags=["ops"])
def health() -> JSONResponse:
    """Liveness. No auth — Caddy and the compose healthcheck both call this.

    Returns 503 rather than 200-with-a-sad-field when the database is
    unreachable. A healthcheck that always succeeds tells you nothing, and
    Caddy is gated on this one.
    """
    checks: dict[str, str] = {}
    healthy = True

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — report any failure, don't crash
        logger.warning("health: database unreachable: %s", exc)
        checks["database"] = "error"
        healthy = False

    body = {
        "status": "ok" if healthy else "degraded",
        "service": "companion",
        "version": __version__,
        "checks": checks,
    }
    return JSONResponse(content=body, status_code=200 if healthy else 503)
