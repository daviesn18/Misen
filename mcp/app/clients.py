"""HTTP clients for the two backends behind the tool surface.

Every Companion call carries the *caller's own* member token. The MCP server
never holds a credential that could reach a household's data on its own — it
passes through the one it was given, and Companion does the tenancy resolution
it already does for the app. That is the whole reason there is no
`household_id` parameter anywhere in this server.

Mealie is different: it is shared across the household and Companion doesn't
proxy recipe search (PRD §5), so those calls use the deployment's single Mealie
API token. Authentication still happens first — see `app/auth.py`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from app.config import get_settings

logger = logging.getLogger(__name__)


class CompanionClient:
    def __init__(self, base_url: str, timeout: float, transport: Any = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def me(self, token: str) -> dict[str, Any] | None:
        """Authenticate a token. Returns the member, or None if it's not valid.

        This is the one call that must not raise on a 401 — a bad token is an
        authentication outcome, not a tool failure, and FastMCP needs a plain
        None to answer with a spec-compliant 401.
        """
        try:
            response = await self._client.get(
                "/me", headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            logger.warning("companion unreachable during token check: %s", exc)
            return None
        if response.status_code != 200:
            return None
        return response.json()

    async def request(
        self, method: str, path: str, token: str, **kwargs: Any
    ) -> Any:
        """Call Companion as the member, and turn failures into readable text.

        Error messages matter more here than anywhere else in the project.
        When a model passes a mid-week date as `week_start`, Companion answers
        "Weeks here start on Monday" — surfacing that verbatim is what lets the
        model correct itself on the next turn instead of giving up or, worse,
        telling the user something vague and wrong.
        """
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("companion %s %s failed: %s", method, path, exc)
            raise ToolError(
                "Misen's own service is unreachable right now — nothing was changed."
            ) from exc

        if response.status_code == 204 or not response.content:
            return None

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolError("Misen returned something unreadable.") from exc

        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") or "That didn't work."
            raise ToolError(message)

        return payload


class MealieClient:
    """Recipe search only.

    Everything else about recipes goes through Companion, which owns scaling.
    Search stays direct because proxying it would mean re-implementing Mealie's
    pagination and tag filtering for no gain.
    """

    def __init__(self, base_url: str, token: str, timeout: float, transport: Any = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(
        self, query: str | None, tags: list[str] | None, limit: int
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"perPage": limit, "page": 1}
        if query:
            params["search"] = query
        if tags:
            params["tags"] = tags

        try:
            response = await self._client.get("/api/recipes", params=params)
        except httpx.HTTPError as exc:
            logger.warning("mealie search failed: %s", exc)
            raise ToolError("The recipe library is unreachable right now.") from exc

        if response.status_code in (401, 403):
            # Our own credential is wrong. An operator problem, and it must not
            # read to the model as "the user isn't allowed to search recipes".
            logger.error("mealie rejected our API token (%s)", response.status_code)
            raise ToolError("The recipe library rejected Misen's credentials.")
        if response.status_code >= 400:
            raise ToolError("The recipe library returned an error.")

        return (response.json() or {}).get("items", [])


_companion: CompanionClient | None = None
_mealie: MealieClient | None = None


def companion() -> CompanionClient:
    global _companion
    if _companion is None:
        settings = get_settings()
        _companion = CompanionClient(settings.companion_url, settings.timeout)
    return _companion


def mealie() -> MealieClient:
    global _mealie
    if _mealie is None:
        settings = get_settings()
        _mealie = MealieClient(settings.mealie_url, settings.mealie_token, settings.timeout)
    return _mealie


def set_clients(companion_client: CompanionClient, mealie_client: MealieClient) -> None:
    """Substitute both clients. Tests point them at fakes; nothing else uses it."""
    global _companion, _mealie
    _companion, _mealie = companion_client, mealie_client


async def close_clients() -> None:
    global _companion, _mealie
    for client in (_companion, _mealie):
        if client is not None:
            await client.aclose()
    _companion = _mealie = None
