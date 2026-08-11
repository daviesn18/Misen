"""Fixtures.

Companion and Mealie are both faked at the HTTP layer with
`httpx.MockTransport`, which means the real `CompanionClient` and
`MealieClient` code runs — URL building, header injection, status handling,
error-message extraction. Faking the client objects instead would skip exactly
the code most likely to be wrong.

The tools are driven through a real in-memory `Client` over the MCP protocol
rather than called as Python functions. That way the tests exercise argument
validation, the auth verifier, and the JSON round trip — everything a real
caller goes through.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

VALID_TOKEN = "test-member-token"

MEMBER = {
    "id": 1,
    "name": "Nick",
    "initials": "N",
    "color": "terracotta",
    "role": "adult",
    "can_use_basil": True,
}

HOUSEHOLD = {
    "id": 1,
    "name": "Davies",
    "timezone": "America/New_York",
    "week_starts_on": "monday",
    "members": [
        MEMBER,
        {"id": 2, "name": "Mara", "initials": "M", "color": "green", "role": "adult",
         "can_use_basil": True},
        {"id": 3, "name": "Ivy", "initials": "I", "color": "gold", "role": "child",
         "can_use_basil": False},
    ],
}

WEEK = "2026-08-10"


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


class FakeCompanion:
    """Just enough of the Companion API, with the same response shapes.

    Every handler here mirrors a real endpoint verified in phase 1's own suite;
    the point is to test the MCP layer's shaping and error handling, not to
    re-test Companion.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        # `down` takes the whole service out, including token verification —
        # which surfaces as a 401, because an unverifiable token is exactly
        # that. `fail_paths` breaks one endpoint while /me keeps working, which
        # is what a tool call hitting a broken route actually looks like.
        self.down = False
        self.fail_paths: set[str] = set()
        self.pantry: list[dict[str, Any]] = []
        self.menu: dict[tuple[str, str], dict[str, Any]] = {}
        self.shopping: list[dict[str, Any]] = []
        self._next_id = 1

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("companion is down")

        path = request.url.path
        method = request.method
        self.calls.append((method, path))

        if path in self.fail_paths:
            raise httpx.ConnectError(f"{path} is unreachable")

        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token != VALID_TOKEN:
            return _error(401, "unauthorized", "Sign in again — that token isn't valid.")

        body = json.loads(request.content) if request.content else {}
        params = dict(request.url.params)

        if path == "/me":
            return httpx.Response(200, json=MEMBER)
        if path == "/household":
            return httpx.Response(200, json=HOUSEHOLD)
        if path == "/pantry":
            return self._pantry(method, body, params)
        if path.startswith("/pantry/"):
            return self._pantry_item(method, path, body)
        if path == "/menu":
            return self._menu(params)
        if path.startswith("/menu/"):
            return self._menu_slot(method, path, body)
        if path == "/shopping":
            return self._shopping(method, body, params)
        if path == "/shopping/from-menu":
            return self._from_menu(body)
        if path.startswith("/shopping/"):
            return self._shopping_item(method, path, body)
        if path.endswith("/scaled"):
            return self._scaled(path, params)

        return _error(404, "http_error", "Not Found")

    # --- pantry ---
    def _pantry(self, method: str, body: dict, params: dict) -> httpx.Response:
        if method == "POST":
            item = {
                "id": self._id(), "name": body["name"], "quantity": body.get("quantity"),
                "unit": body.get("unit"), "location": body["location"],
                "expiry_date": body.get("expiry_date"), "used_at": None, "added_by": 1,
                "added_date": "2026-08-10T12:00:00", "updated_at": "2026-08-10T12:00:00",
            }
            self.pantry.append(item)
            return httpx.Response(201, json=item)

        items = self.pantry
        if params.get("include_used", "false").lower() != "true":
            items = [i for i in items if not i["used_at"]]
        if params.get("location"):
            items = [i for i in items if i["location"] == params["location"]]
        return httpx.Response(200, json=items)

    def _pantry_item(self, method: str, path: str, body: dict) -> httpx.Response:
        item_id = int(path.rsplit("/", 1)[1])
        item = next((i for i in self.pantry if i["id"] == item_id), None)
        if item is None:
            return _error(404, "not_found", "That item isn't in the pantry.")
        if method == "PATCH":
            if "used" in body:
                item["used_at"] = "2026-08-10T18:00:00" if body.pop("used") else None
            item.update(body)
            return httpx.Response(200, json=item)
        return httpx.Response(204)

    # --- menu ---
    def _menu(self, params: dict) -> httpx.Response:
        weeks = int(params.get("weeks", 2))
        start = params.get("week_start", WEEK)
        if start != WEEK and start != "2026-08-17":
            return _error(400, "bad_week_start",
                          f"Weeks here start on Monday, so {start} isn't the start of one.")

        from datetime import date, timedelta
        base = date.fromisoformat(start)
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        out = []
        for offset in range(weeks):
            week_start = (base + timedelta(days=7 * offset)).isoformat()
            days = []
            planned = 0
            for index, name in enumerate(names):
                entry = self.menu.get((week_start, name))
                if entry:
                    planned += 1
                days.append({
                    "day": name,
                    "date": (date.fromisoformat(week_start) + timedelta(days=index)).isoformat(),
                    "entry": entry,
                })
            out.append({
                "week_start": week_start,
                "week_end": (date.fromisoformat(week_start) + timedelta(days=6)).isoformat(),
                "days": days, "planned": planned, "open": 7 - planned,
            })
        return httpx.Response(200, json={
            "timezone": "America/New_York", "week_starts_on": "monday", "weeks": out,
        })

    def _menu_slot(self, method: str, path: str, body: dict) -> httpx.Response:
        _, _, week, day = path.split("/")
        if week not in (WEEK, "2026-08-17"):
            return _error(400, "bad_week_start", "Weeks here start on Monday.")
        if method == "DELETE":
            if (week, day) not in self.menu:
                return _error(404, "not_found", "Nothing planned for that night.")
            del self.menu[(week, day)]
            return httpx.Response(204)

        if body.get("cooked_by") not in (None, 1, 2, 3):
            return _error(400, "unknown_member", "Nobody in this household has that id.")
        if body.get("recipe_id") and body["recipe_id"] != "roast-chicken":
            return _error(404, "not_found", "That recipe isn't in the library.")

        recipe = body.get("recipe_id")
        entry = {
            "id": self._id(), "day_of_week": day, "meal_slot": "dinner",
            "entry_type": "recipe" if recipe else "freeform",
            "mealie_recipe_id": recipe,
            "title": body.get("title") or ("Roast Chicken" if recipe else ""),
            "servings": body.get("servings"), "notes": body.get("notes"),
            "cooked_by": body.get("cooked_by"),
            "updated_at": "2026-08-10T12:00:00", "updated_by": 1,
        }
        self.menu[(week, day)] = entry
        return httpx.Response(200, json=entry)

    # --- recipes ---
    def _scaled(self, path: str, params: dict) -> httpx.Response:
        slug = path.split("/")[2]
        if slug != "roast-chicken":
            return _error(404, "not_found", "That recipe isn't in the library.")
        servings = int(params["servings"]) if params.get("servings") else None
        factor = (servings / 4) if servings else 1.0
        return httpx.Response(200, json={
            "slug": slug, "name": "Roast Chicken", "base_servings": 4.0,
            "requested_servings": servings, "factor": factor, "scalable": True,
            "total_time": "55 min", "image": None,
            "ingredients": [
                {"original": "2 cups flour", "scaled": f"{2 * factor:g} cups flour",
                 "quantity": 2 * factor, "unit": "cups", "food": "flour",
                 "status": "scaled", "section": None},
                {"original": "1 packet yeast", "scaled": f"{1 * factor:g} packet yeast",
                 "quantity": factor, "unit": "packet", "food": "yeast",
                 "status": "scaled" if float(factor).is_integer() else "scaled_awkward",
                 "section": None},
                {"original": "salt to taste", "scaled": "salt to taste", "quantity": None,
                 "unit": None, "food": None, "status": "unscaled_no_quantity", "section": None},
            ],
            "instructions": [{"title": None, "text": "Cook it."}],
        })

    # --- shopping ---
    def _list_payload(self) -> dict[str, Any]:
        groups: dict[str, list] = {}
        for item in self.shopping:
            groups.setdefault(item["aisle"], []).append(item)
        checked = sum(1 for i in self.shopping if i["checked"])
        return {
            "list_id": "list-1",
            "groups": [{"aisle": a, "items": groups[a]} for a in sorted(groups)],
            "counts": {"total": len(self.shopping), "checked": checked,
                       "remaining": len(self.shopping) - checked},
        }

    def _shopping(self, method: str, body: dict, params: dict) -> httpx.Response:
        if method == "POST":
            for item in body["items"]:
                name = item["name"]
                if item.get("quantity"):
                    name = f"{name} ({item['quantity']})"
                self.shopping.append({
                    "id": f"item-{self._id()}", "name": name, "checked": False, "aisle": "Other",
                })
            return httpx.Response(201, json=self._list_payload())
        payload = self._list_payload()
        if params.get("unchecked_only", "false").lower() == "true":
            for group in payload["groups"]:
                group["items"] = [i for i in group["items"] if not i["checked"]]
            payload["groups"] = [g for g in payload["groups"] if g["items"]]
        return httpx.Response(200, json=payload)

    def _shopping_item(self, method: str, path: str, body: dict) -> httpx.Response:
        item_id = path.rsplit("/", 1)[1]
        item = next((i for i in self.shopping if i["id"] == item_id), None)
        if item is None:
            return _error(404, "not_found", "That item isn't on the list.")
        if method == "DELETE":
            self.shopping.remove(item)
            return httpx.Response(204)
        item["checked"] = body["checked"]
        return httpx.Response(200, json=self._list_payload())

    def _from_menu(self, body: dict) -> httpx.Response:
        week = body.get("week_start") or WEEK
        if week not in (WEEK, "2026-08-17"):
            return _error(400, "bad_week_start", "Weeks here start on Monday.")
        entries = [e for (w, _), e in self.menu.items() if w == week]
        freeform = [e["title"] for e in entries if e["entry_type"] == "freeform"]
        recipe_nights = [e for e in entries if e["entry_type"] == "recipe"]
        added = []
        if recipe_nights:
            added = [{"name": "flour", "quantity": "2 cups", "sources": ["Roast Chicken"]}]
            for item in added:
                self.shopping.append({
                    "id": f"item-{self._id()}", "name": f"{item['name']} ({item['quantity']})",
                    "checked": False, "aisle": "Other",
                })
        return httpx.Response(200, json={
            "week_start": week, "week_end": "2026-08-16", "added": added,
            # One skip per recipe that wanted it — the real Companion does the
            # same, and the shaping layer is what collapses the duplicates.
            "skipped": [{"ingredient": "yeast", "covered_by": "yeast"}] * len(recipe_nights),
            "already_listed": [], "freeform_entries": freeform,
            "unavailable_recipes": [], "list": self._list_payload(),
        })


class FakeMealie:
    def __init__(self) -> None:
        self.down = False
        self.recipes = [
            {"slug": "roast-chicken", "name": "Roast Chicken", "totalTime": "55 min",
             "recipeServings": 4, "tags": [{"name": "Quick"}],
             "description": "A weeknight roast."},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("mealie is down")
        params = dict(request.url.params)
        items = self.recipes
        if params.get("search"):
            needle = params["search"].lower()
            items = [r for r in items if needle in r["name"].lower()]
        return httpx.Response(200, json={"items": items[: int(params.get("perPage", 20))]})


@pytest.fixture
def fake_companion() -> FakeCompanion:
    return FakeCompanion()


@pytest.fixture
def fake_mealie() -> FakeMealie:
    return FakeMealie()


@pytest.fixture(autouse=True)
def wired(fake_companion: FakeCompanion, fake_mealie: FakeMealie) -> Iterator[None]:
    from app import clients, server

    companion = clients.CompanionClient(
        "http://companion:8000", 5.0, transport=httpx.MockTransport(fake_companion.handler)
    )
    mealie = clients.MealieClient(
        "http://mealie:9000", "fake", 5.0, transport=httpx.MockTransport(fake_mealie.handler)
    )
    clients.set_clients(companion, mealie)
    server._household_cache.clear()
    yield
    server._household_cache.clear()


def _factory(app: Any):  # noqa: ANN202
    """An httpx client that speaks to the ASGI app directly.

    No sockets, but every other layer is real: headers, status codes, the auth
    middleware's 401. FastMCP's in-memory transport skips auth entirely, which
    would leave the one thing most worth testing untested.
    """

    def build(headers=None, timeout=None, auth=None, **kwargs):  # noqa: ANN001, ANN202
        kwargs.pop("follow_redirects", None)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
            **kwargs,
        )

    return build


@asynccontextmanager
async def _serve() -> AsyncIterator[Any]:
    """The MCP app with its lifespan running.

    The lifespan is non-negotiable: it starts FastMCP's session manager, and
    without it every request fails with a task-group error that looks nothing
    like the real problem.
    """
    from app.server import build_app

    app = build_app()
    async with app.router.lifespan_context(app):
        yield app


@asynccontextmanager
async def _connect(token: str = VALID_TOKEN) -> AsyncIterator[Client]:
    async with _serve() as app:
        transport = StreamableHttpTransport(
            "http://testserver/mcp", auth=token, httpx_client_factory=_factory(app)
        )
        async with Client(transport) as client:
            yield client


@asynccontextmanager
async def _raw(token: str | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """A plain HTTP client, for asserting on status codes directly.

    Auth rejection is easier to assert here than through the MCP client, whose
    failures arrive wrapped in an anyio ExceptionGroup — and a raw 401 is
    exactly what Anthropic's connector will see, so it is the more faithful
    assertion anyway.
    """
    async with _serve() as app:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
        ) as http:
            yield http


# Both are handed to tests as factories rather than as ready-made async
# fixtures, so the context is entered and exited inside the test's own task.
# anyio cancel scopes are task-bound, and pytest-asyncio does not guarantee
# that an async generator fixture tears down in the task that set it up —
# which surfaces as "attempted to exit cancel scope in a different task",
# long after the assertions have already passed.


@pytest.fixture
def connect():  # noqa: ANN201
    """`async with connect() as client:` — Nick by default, any token on request."""
    return _connect


@pytest.fixture
def raw():  # noqa: ANN201
    """`async with raw(token) as http:` for direct status-code assertions."""
    return _raw
