"""Misen Companion API.

Every endpoint in PRD §5: pantry, weekly menu, recipe scaling, shopping, and
reminders. Planning conversations happen in a Claude Project talking to the MCP
server, which reaches this API with the caller's own token — so there is no
chat surface here.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.errors import install_error_handlers
from app.mealie import close_mealie
from app.routers import menu, meta, pantry, recipes, reminders, shopping

logger = logging.getLogger(__name__)

try:
    __version__ = version("misen-companion")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0+dev"

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # One pooled httpx client serves every Mealie call; close it on the way out
    # so a reload doesn't leak sockets.
    close_mealie()


app = FastAPI(
    title="Misen Companion",
    version=__version__,
    description="Pantry, weekly menu, recipe scaling, shopping, and reminders.",
    lifespan=lifespan,
)

install_error_handlers(app)

app.include_router(meta.router)
app.include_router(pantry.router)
app.include_router(menu.router)
app.include_router(recipes.router)
app.include_router(shopping.router)
app.include_router(reminders.router)


@app.get("/health", tags=["ops"])
def health() -> JSONResponse:
    """Liveness. No auth — Caddy and the compose healthcheck both call this.

    Returns 503 rather than 200-with-a-sad-field when the database is
    unreachable. A healthcheck that always succeeds tells you nothing, and
    Caddy is gated on this one.

    Mealie is deliberately *not* checked here. The two backends fail
    independently, and marking Companion unhealthy because Mealie is
    restarting would take the pantry and the menu down with the recipes.
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
