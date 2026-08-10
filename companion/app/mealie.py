"""The one place that talks to Mealie.

Single client module by design (PRD §13): Mealie is an upstream we don't
control, and when a version bump changes a field name we want exactly one file
to edit. Nothing outside this module knows Mealie's URL shape or its camelCase
JSON.

Paths and payload shapes here were read off Mealie v3.22.0's own routers and
schemas, not from memory:
  GET    /api/recipes/{slug}
  GET    /api/recipes                              search + tag filter
  GET    /api/households/shopping/lists            paginated summaries
  POST   /api/households/shopping/lists
  GET    /api/households/shopping/lists/{id}       includes listItems
  POST   /api/households/shopping/items/create-bulk
  PUT    /api/households/shopping/items/{id}       returns a *collection*
  DELETE /api/households/shopping/items/{id}
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import httpx

from app.config import get_settings
from app.errors import MealieUnavailable, NotFound

logger = logging.getLogger(__name__)


class MealieClient:
    def __init__(self, base_url: str, token: str, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    # --- plumbing --------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Connection refused, DNS failure, timeout — Mealie is down or
            # unreachable, and that is a different problem from a bad request.
            logger.warning("mealie %s %s failed: %s", method, path, exc)
            raise MealieUnavailable() from exc

        if response.status_code == 404:
            raise NotFound("That recipe isn't in the library.")
        if response.status_code == 401 or response.status_code == 403:
            # Our own credential is wrong. This is an operator problem, not a
            # user problem, so it must not surface as "you can't do that".
            logger.error("mealie rejected our API token (%s)", response.status_code)
            raise MealieUnavailable("The recipe library rejected our credentials.")
        if response.status_code >= 400:
            logger.warning(
                "mealie %s %s returned %s: %s",
                method, path, response.status_code, response.text[:400],
            )
            raise MealieUnavailable()

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise MealieUnavailable("The recipe library returned something unreadable.") from exc

    # --- recipes ---------------------------------------------------------

    def get_recipe(self, slug: str) -> dict[str, Any]:
        return self._request("GET", f"/api/recipes/{slug}")

    def search_recipes(
        self, query: str | None = None, tags: list[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"perPage": limit, "page": 1}
        if query:
            params["search"] = query
        if tags:
            params["tags"] = tags
        payload = self._request("GET", "/api/recipes", params=params) or {}
        return payload.get("items", [])

    # --- shopping --------------------------------------------------------

    def list_shopping_lists(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", "/api/households/shopping/lists", params={"perPage": 100, "page": 1}
        ) or {}
        return payload.get("items", [])

    def create_shopping_list(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/api/households/shopping/lists", json={"name": name})

    def get_shopping_list(self, list_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/households/shopping/lists/{list_id}")

    def create_items(self, list_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Add items in one call.

        Everything Misen writes goes in as a non-food item (`isFood: false`),
        so Mealie stores the text verbatim instead of trying to resolve it to
        a food record and a unit record. Misen's shopping list is a list of
        things to buy, not a normalized inventory, and letting Mealie normalize
        it would mean "2 lbs chicken thighs" comes back as something else.
        """
        payload = [
            {
                "shoppingListId": list_id,
                "note": item["note"],
                "quantity": item.get("quantity", 1),
                "isFood": False,
                "checked": False,
            }
            for item in items
        ]
        return self._request(
            "POST", "/api/households/shopping/items/create-bulk", json=payload
        )

    def update_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Mealie returns a *collection* here, not the item.

        It may merge the updated item into an existing one, in which case the
        thing you updated comes back under `updatedItems` and a different id
        may have been deleted. Callers re-read the list rather than trusting a
        single object back.
        """
        return self._request(
            "PUT", f"/api/households/shopping/items/{item_id}", json=payload
        )

    def get_item(self, item_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/households/shopping/items/{item_id}")

    def delete_item(self, item_id: str) -> None:
        self._request("DELETE", f"/api/households/shopping/items/{item_id}")


@lru_cache(maxsize=1)
def _client() -> MealieClient:
    settings = get_settings()
    return MealieClient(settings.mealie_url, settings.mealie_token)


def get_mealie() -> MealieClient:
    """FastAPI dependency. Overridden wholesale in tests — every test that
    touches Mealie substitutes a fake here, so the suite never needs a live
    Mealie and never asserts against one."""
    return _client()


def close_mealie() -> None:
    if _client.cache_info().currsize:
        _client().close()
        _client.cache_clear()
