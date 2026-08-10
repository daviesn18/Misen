"""One error envelope, everywhere.

PRD §5: `{"error": {"code": "...", "message": "..."}}`. The client surfaces
`message` directly to the user, so every message here is written to be read by
a person standing in a kitchen, not by a developer reading a log.

FastAPI's defaults produce `{"detail": ...}` in three different shapes
(`HTTPException`, `RequestValidationError`, unhandled). All three are
reshaped below so the client has exactly one parse path.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(HTTPException):
    """An error with a code the client can branch on and a message it can show."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message


class NotFound(ApiError):
    def __init__(self, message: str = "That doesn't exist.") -> None:
        super().__init__(404, "not_found", message)


class BadRequest(ApiError):
    def __init__(self, message: str, code: str = "bad_request") -> None:
        super().__init__(400, code, message)


class Unauthorized(ApiError):
    def __init__(self, message: str = "Sign in again — that token isn't valid.") -> None:
        super().__init__(401, "unauthorized", message)


class Forbidden(ApiError):
    def __init__(self, message: str, code: str = "forbidden") -> None:
        super().__init__(403, code, message)


class MealieUnavailable(ApiError):
    """502 specifically means "Mealie is unreachable".

    The two backends fail independently and the user should be told which half
    is down — "recipes are unavailable, the menu still works" is actionable in
    a way that a generic 500 is not.
    """

    def __init__(self, message: str = "Can't reach the recipe library right now.") -> None:
        super().__init__(502, "mealie_unavailable", message)


def _envelope(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _envelope(exc.code, exc.message, exc.status_code)

    # Registered on Starlette's base class, not FastAPI's subclass. An
    # unmatched route is raised by the router itself as the *base* exception,
    # so a handler bound only to `fastapi.HTTPException` never sees it and 404s
    # come back as `{"detail": "Not Found"}` — a second response shape for the
    # client to parse, arrived at by accident.
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope("http_error", str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's error list is precise but unreadable. Surface the first
        # problem in plain language and keep the rest out of the user's face.
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query"))
        detail = first.get("msg", "That request wasn't valid.")
        message = f"{location}: {detail}" if location else detail
        return _envelope("invalid_request", message, 422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback, return a sentence. Internal detail in a response
        # body helps an attacker and confuses everyone else.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _envelope("internal_error", "Something went wrong on our end.", 500)
