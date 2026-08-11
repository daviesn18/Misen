"""The thirteen tools — PRD §6.

**The descriptions are the product here.** Vague tool descriptions are the
single biggest reason a model misuses or ignores a tool, so the text in each
docstring is the PRD's wording close to verbatim, and it is prescriptive about
*when* to call the tool rather than merely what it does. Change these
deliberately, not incidentally.

What is deliberately absent: no `delete_recipe`, no `delete_pantry_item`, no
household or member mutation. Destructive and administrative operations stay in
the app and in `scripts/`, where a human is looking at a confirmation dialog.
Basil can mark things used, overwrite a menu slot after confirming, and clear a
slot on explicit request; it cannot erase a recipe or change who lives here.

There is no `household_id` parameter on any tool, also deliberately: a model
that could name a household could name the wrong one. Scope comes from the
bearer token and nowhere else.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from pydantic import Field

from app.auth import CompanionTokenVerifier
from app.clients import companion, mealie
from app.shaping import (
    shape_build_result,
    shape_entry,
    shape_menu,
    shape_pantry,
    shape_recipe,
    shape_search,
    shape_shopping,
)

Location = Literal["fridge", "pantry", "freezer"]
Day = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

mcp = FastMCP(
    name="misen",
    instructions=(
        "Misen is a household's meal planner. These tools read and write the "
        "real shared menu, pantry, and shopping list that the household sees in "
        "their app — treat every write as immediately visible to everyone in the "
        "house."
    ),
    auth=CompanionTokenVerifier(),
)


# --- plumbing -------------------------------------------------------------


def _token() -> str:
    access = get_access_token()
    if access is None or not access.token:
        raise ToolError("Not signed in.")
    return access.token


# The household's timezone and week-start change approximately never, and two
# tools need them on every call. Cached per token for a few minutes so the
# common path is one HTTP call, not two.
_HOUSEHOLD_TTL = 300.0
_household_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def _household(token: str) -> dict[str, Any]:
    cached = _household_cache.get(token)
    now = time.monotonic()
    if cached and now - cached[0] < _HOUSEHOLD_TTL:
        return cached[1]

    payload = await companion().request("GET", "/household", token)
    _household_cache[token] = (now, payload)
    return payload


async def _today(token: str) -> date:
    """The household's current date, not the server's.

    A UTC box is already on tomorrow for five hours out of every evening in the
    Americas, which is exactly when someone asks what's expiring.
    """
    household = await _household(token)
    try:
        tz = ZoneInfo(household.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


async def _resolve_week_start(token: str, week_start: str | None) -> str:
    """Fill in the current week when the caller didn't name one.

    Asked of Companion rather than computed here. Week boundaries depend on the
    household's timezone *and* its `week_starts_on`, and a second
    implementation of that arithmetic is a second thing to drift.
    """
    if week_start:
        return week_start
    payload = await companion().request("GET", "/menu", token, params={"weeks": 1})
    return payload["weeks"][0]["week_start"]


# --- recipes --------------------------------------------------------------


@mcp.tool
async def search_recipes(
    query: Annotated[str | None, Field(description="Name, ingredient, or free text")] = None,
    tags: Annotated[list[str] | None, Field(description="Mealie tag names")] = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
) -> list[dict[str, Any]]:
    """Search the household's recipe library by name, ingredient, or tag.

    Call this whenever the user asks what to cook, mentions a dish or cuisine,
    or asks whether they already have a recipe for something. Prefer this over
    suggesting a recipe from your own knowledge — the household's own library
    is almost always the better answer.
    """
    _token()  # authenticate; the search itself uses the shared Mealie credential
    return shape_search(await mealie().search(query, tags, limit))


@mcp.tool
async def get_recipe(
    slug: Annotated[str, Field(description="The recipe's slug, from search_recipes")],
    servings: Annotated[int | None, Field(ge=1, le=99)] = None,
) -> dict[str, Any]:
    """Get one recipe's full ingredients and instructions, optionally scaled to
    a number of servings.

    Call this before adding a recipe to the menu, before answering questions
    about how to cook something, and before working out what needs buying. Pass
    `servings` when the user mentions cooking for a different number of people
    than usual.
    """
    params = {"servings": servings} if servings else None
    payload = await companion().request(
        "GET", f"/recipes/{slug}/scaled", _token(), params=params
    )
    return shape_recipe(payload)


# --- pantry ---------------------------------------------------------------


@mcp.tool
async def get_pantry_items(
    location: Location | None = None,
    include_used: bool = False,
) -> list[dict[str, Any]]:
    """List what the household currently has in the fridge, pantry, and
    freezer, with expiry dates where known.

    Call this before suggesting any meal, before building a shopping list, and
    any time the user asks what they can make. Items expiring within three days
    should influence what you suggest first — `expires_in_days` is computed for
    you, and is negative for anything already past its date.
    """
    token = _token()
    params: dict[str, Any] = {"include_used": include_used}
    if location:
        params["location"] = location
    items = await companion().request("GET", "/pantry", token, params=params)
    return shape_pantry(items, await _today(token))


@mcp.tool
async def add_pantry_item(
    name: str,
    location: Location,
    quantity: Annotated[str | None, Field(description="Free text: '2 lbs', 'half a jar'")] = None,
    unit: str | None = None,
    expiry_date: Annotated[str | None, Field(description="YYYY-MM-DD")] = None,
) -> dict[str, Any]:
    """Add an item to the pantry, fridge, or freezer.

    Call this when the user says they bought something, brought something home,
    or mentions having an ingredient you didn't already know about.
    """
    token = _token()
    body: dict[str, Any] = {"name": name, "location": location}
    if quantity:
        body["quantity"] = quantity
    if unit:
        body["unit"] = unit
    if expiry_date:
        body["expiry_date"] = expiry_date

    item = await companion().request("POST", "/pantry", token, json=body)
    return shape_pantry([item], await _today(token))[0]


@mcp.tool
async def update_pantry_item(
    item_id: Annotated[int, Field(description="From get_pantry_items — an id, not a name")],
    name: str | None = None,
    quantity: str | None = None,
    unit: str | None = None,
    location: Location | None = None,
    expiry_date: Annotated[str | None, Field(description="YYYY-MM-DD")] = None,
    used: Annotated[
        bool | None, Field(description="true when it's finished, eaten, or thrown out")
    ] = None,
) -> dict[str, Any]:
    """Update or finish off a pantry item.

    Call with `used=true` when the user says they used, finished, ate, or threw
    out something. Call with a changed quantity when they used part of it. Look
    the item up with `get_pantry_items` first — this takes an id, not a name.
    """
    token = _token()
    body = {
        key: value
        for key, value in {
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "location": location,
            "expiry_date": expiry_date,
            "used": used,
        }.items()
        if value is not None
    }
    if not body:
        raise ToolError("Nothing to change — pass at least one field, or used=true.")

    item = await companion().request("PATCH", f"/pantry/{item_id}", token, json=body)
    return shape_pantry([item], await _today(token))[0]


# --- menu -----------------------------------------------------------------


@mcp.tool
async def get_weekly_menu(
    week_start: Annotated[
        str | None, Field(description="YYYY-MM-DD, must be the day the week starts on")
    ] = None,
    weeks: Annotated[int, Field(ge=1, le=4)] = 2,
) -> dict[str, Any]:
    """Get planned dinners, including which nights are still open.

    Defaults to this week and next week, because the household plans ahead.
    Call this before planning anything so you don't overwrite a decided night,
    and whenever the user asks what's for dinner.
    """
    params: dict[str, Any] = {"weeks": weeks}
    if week_start:
        params["week_start"] = week_start
    payload = await companion().request("GET", "/menu", _token(), params=params)
    return shape_menu(payload)


@mcp.tool
async def set_weekly_menu(
    day: Day,
    week_start: Annotated[
        str | None,
        Field(description="YYYY-MM-DD from get_weekly_menu. Omit for the current week."),
    ] = None,
    recipe_slug: str | None = None,
    title: Annotated[
        str | None, Field(description="A plain name, for a meal with no recipe")
    ] = None,
    servings: Annotated[int | None, Field(ge=1, le=99)] = None,
    notes: str | None = None,
    cooked_by: Annotated[int | None, Field(description="A member id from get_household")] = None,
) -> dict[str, Any]:
    """Assign a meal to one night.

    Pass `recipe_slug` for a recipe from the library, or `title` alone for a
    simple meal that doesn't need one ('Nachos', 'Leftovers', 'Takeout') — not
    every night needs a recipe, and forcing one is worse than a plain title.
    Pass `servings` when cooking for more or fewer people than the recipe
    assumes. This writes to the shared menu both members see immediately, so
    confirm before replacing a night that already has a meal on it.
    """
    token = _token()
    if not recipe_slug and not title:
        raise ToolError("Give the night a recipe_slug or a title.")

    body = {
        key: value
        for key, value in {
            "recipe_id": recipe_slug,
            "title": title,
            "servings": servings,
            "notes": notes,
            "cooked_by": cooked_by,
        }.items()
        if value is not None
    }
    resolved = await _resolve_week_start(token, week_start)
    entry = await companion().request("PUT", f"/menu/{resolved}/{day}", token, json=body)
    return {"week_start": resolved, **shape_entry(entry)}


@mcp.tool
async def clear_menu_slot(
    day: Day,
    week_start: Annotated[
        str | None, Field(description="YYYY-MM-DD. Omit for the current week.")
    ] = None,
) -> dict[str, Any]:
    """Clear one planned night, making it open again.

    Call this only when the user explicitly asks to remove or cancel a meal —
    never as a step in replacing one, since `set_weekly_menu` overwrites
    directly.
    """
    token = _token()
    resolved = await _resolve_week_start(token, week_start)
    await companion().request("DELETE", f"/menu/{resolved}/{day}", token)
    return {"week_start": resolved, "day": day, "meal": None}


# --- shopping -------------------------------------------------------------


@mcp.tool
async def get_shopping_list(unchecked_only: bool = False) -> dict[str, Any]:
    """Get the current shopping list with aisle grouping and check-off state.

    Call this before carting anything, when the user asks what they need to
    buy, and after building a list to confirm what's on it. Use
    `unchecked_only=true` to get exactly the items still needed — that is the
    right input for an Instacart order.
    """
    payload = await companion().request(
        "GET", "/shopping", _token(), params={"unchecked_only": unchecked_only}
    )
    return shape_shopping(payload)


@mcp.tool
async def add_to_shopping_list(
    items: Annotated[
        list[dict[str, str]],
        Field(description="Each item is {'name': 'Milk', 'quantity': '1 gal'}; quantity optional"),
    ],
) -> dict[str, Any]:
    """Add items to the shopping list.

    Call this when the user says they need something, when a planned recipe
    needs an ingredient the pantry doesn't have, or when they ask you to add to
    the list.
    """
    cleaned = [
        {"name": item["name"], **({"quantity": item["quantity"]} if item.get("quantity") else {})}
        for item in items
        if item.get("name")
    ]
    if not cleaned:
        raise ToolError("Each item needs a name.")

    payload = await companion().request(
        "POST", "/shopping", _token(), json={"items": cleaned}
    )
    return shape_shopping(payload)


@mcp.tool
async def check_shopping_item(
    item_id: Annotated[str, Field(description="From get_shopping_list")],
    checked: bool = True,
) -> dict[str, Any]:
    """Mark a shopping item as bought or un-bought.

    Call this when the user says they picked something up or already have it.
    """
    payload = await companion().request(
        "PATCH", f"/shopping/{item_id}", _token(), json={"checked": checked}
    )
    return shape_shopping(payload)


@mcp.tool
async def build_shopping_list(
    week_start: Annotated[
        str | None, Field(description="YYYY-MM-DD. Omit for the current week.")
    ] = None,
) -> dict[str, Any]:
    """Generate the shopping list from a week's planned dinners at their planned
    serving counts, skipping anything already in the pantry.

    Call this after finishing a week's plan. Two caveats to pass on to the
    user: pantry matching is approximate, so the list needs a review; and any
    freeform meals on the menu contribute nothing, so ask what those need.
    Safe to call again — anything already on the list is not added twice.
    """
    body = {"week_start": week_start} if week_start else {}
    payload = await companion().request("POST", "/shopping/from-menu", _token(), json=body)
    return shape_build_result(payload)


# --- household ------------------------------------------------------------


@mcp.tool
async def get_household() -> dict[str, Any]:
    """Get the household's members, their names and roles, the timezone, and
    which day the week starts on.

    Call this when you need to know who's in the house — for example when
    assigning who's cooking a given night, or when the user refers to someone
    by name.
    """
    payload = await _household(_token())
    return {
        "name": payload["name"],
        "timezone": payload["timezone"],
        "week_starts_on": payload["week_starts_on"],
        "members": [
            {"id": m["id"], "name": m["name"], "role": m["role"]}
            for m in payload.get("members", [])
        ],
    }


def build_app():  # noqa: ANN201 — Starlette app, typed by FastMCP
    """The ASGI app, for uvicorn.

    Stateless: every request stands alone rather than resuming a session held
    in this process's memory. That keeps a restart from stranding an
    in-progress conversation, which matters because the client here is
    Anthropic's connector rather than something that will notice and retry.
    """
    return mcp.http_app(path="/mcp", stateless_http=True)
