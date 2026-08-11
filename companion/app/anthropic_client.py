"""The one place that talks to Anthropic.

Same shape as `mealie.py` and for the same reason: an upstream we don't
control gets exactly one file, and tests substitute it wholesale through the
FastAPI dependency rather than monkeypatching a module global.

Async, unlike the Mealie client. Basil's turns are long-lived streams — a
week-planning turn holds the connection open for the better part of a minute
while tools run on Anthropic's side — and blocking a worker thread for that
long to serve a two-person household is a waste of the one thing SSE is
actually good at.
"""

from __future__ import annotations

from functools import lru_cache

from anthropic import AsyncAnthropic

from app.config import get_settings


@lru_cache(maxsize=1)
def _client() -> AsyncAnthropic:
    settings = get_settings()
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        # The SDK's default read timeout assumes a request that answers. A
        # streaming turn with server-side tool calls can be quiet for a while
        # between blocks while a tool runs, and timing that out mid-plan would
        # leave the menu half-written.
        timeout=180.0,
        max_retries=2,
    )


def get_anthropic() -> AsyncAnthropic:
    """FastAPI dependency. Overridden in tests."""
    return _client()


async def close_anthropic() -> None:
    if _client.cache_info().currsize:
        await _client().close()
        _client.cache_clear()
