"""Shopping — a proxy over Mealie's list, plus the thing Mealie can't do.

Mealie owns storage. Companion proxies it so that check-off, aisle grouping,
and the MCP tools have one implementation rather than three. `/shopping/from-menu`
is the part that isn't a proxy: it reads a week's menu, pulls each recipe's
ingredients *at that entry's planned servings*, diffs against the pantry, and
writes only the gaps.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentPrincipal, DbSession, Principal
from app.errors import BadRequest, NotFound
from app.mealie import MealieClient, get_mealie
from app.models import MenuEntry, PantryItem
from app.scaling import scale_recipe
from app.schemas import BuildFromMenu, ShoppingAdd, ShoppingItemPatch
from app.shopping_build import collect_needed
from app.weeks import current_week_start, is_valid_week_start

router = APIRouter(prefix="/shopping", tags=["shopping"])

OTHER_AISLE = "Other"


# --- which Mealie list is ours -------------------------------------------


def _resolve_list_id(
    db: Session, principal: Principal, mealie: MealieClient
) -> str:
    """Find (or make) this household's one shopping list, and remember it.

    Mealie supports many lists; Misen has exactly one and must find the same
    one on every call. The id is cached on the household row rather than
    matched by name each time, because a rename in Mealie's UI would otherwise
    silently strand the list and start a second one.
    """
    household = principal.household
    if household.mealie_shopping_list_id:
        return household.mealie_shopping_list_id

    existing = mealie.list_shopping_lists()
    match = next((item for item in existing if item.get("name") == household.name), None)
    if match is None:
        match = mealie.create_shopping_list(household.name)

    household.mealie_shopping_list_id = str(match["id"])
    db.commit()
    return household.mealie_shopping_list_id


def _load_list(db: Session, principal: Principal, mealie: MealieClient) -> dict[str, Any]:
    """Fetch the list, healing a stale id rather than 404ing the user.

    If someone deletes the list in Mealie's UI, the cached id points at
    nothing. That's an operator's accident, not a reason to break the Shopping
    tab, so we forget the id and make a fresh list.
    """
    list_id = _resolve_list_id(db, principal, mealie)
    try:
        return mealie.get_shopping_list(list_id)
    except NotFound:
        principal.household.mealie_shopping_list_id = None
        db.commit()
        return mealie.get_shopping_list(_resolve_list_id(db, principal, mealie))


# --- serialization --------------------------------------------------------


def _item_name(item: dict[str, Any]) -> str:
    for key in ("display", "note"):
        value = item.get(key)
        if value:
            return str(value)
    food = item.get("food") or {}
    return str(food.get("name") or "Item")


def _aisle(item: dict[str, Any]) -> str:
    label = item.get("label") or {}
    return str(label.get("name") or OTHER_AISLE)


def _serialize(payload: dict[str, Any], unchecked_only: bool) -> dict[str, Any]:
    items = payload.get("listItems") or []
    total = len(items)
    checked = sum(1 for item in items if item.get("checked"))

    visible = [item for item in items if not (unchecked_only and item.get("checked"))]

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(visible, key=lambda i: (i.get("position") or 0, _item_name(i))):
        groups.setdefault(_aisle(item), []).append(
            {
                "id": str(item.get("id")),
                "name": _item_name(item),
                "checked": bool(item.get("checked")),
                "aisle": _aisle(item),
            }
        )

    # Aisles alphabetical, with the unlabelled bucket last — it's the one you
    # sweep up at the end rather than walk to.
    ordered = sorted(groups, key=lambda name: (name == OTHER_AISLE, name.lower()))

    return {
        "list_id": str(payload.get("id")),
        "groups": [{"aisle": aisle, "items": groups[aisle]} for aisle in ordered],
        "counts": {"total": total, "checked": checked, "remaining": total - checked},
    }


# --- endpoints ------------------------------------------------------------


@router.get("")
def get_list(
    principal: CurrentPrincipal,
    db: DbSession,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
    unchecked_only: Annotated[bool, Query()] = False,
) -> dict:
    """The list, grouped by aisle, with check state."""
    return _serialize(_load_list(db, principal, mealie), unchecked_only)


@router.post("", status_code=status.HTTP_201_CREATED)
def add_items(
    body: ShoppingAdd,
    principal: CurrentPrincipal,
    db: DbSession,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
) -> dict:
    list_id = _resolve_list_id(db, principal, mealie)
    mealie.create_items(
        list_id,
        [
            {"note": f"{item.name} ({item.quantity})" if item.quantity else item.name}
            for item in body.items
        ],
    )
    return _serialize(mealie.get_shopping_list(list_id), unchecked_only=False)


@router.patch("/{item_id}")
def check_item(
    item_id: str,
    body: ShoppingItemPatch,
    principal: CurrentPrincipal,
    db: DbSession,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
) -> dict:
    """Tick something off.

    Mealie wants the whole item back on a PUT, and it may merge the result into
    another row — so we read, patch, write, then re-read the list rather than
    trusting the single object it hands back.
    """
    list_id = _resolve_list_id(db, principal, mealie)
    item = mealie.get_item(item_id)
    if str(item.get("shoppingListId")) != str(list_id):
        # An id from a different household's list. Same answer as a made-up id.
        raise NotFound("That item isn't on the list.")

    item["checked"] = body.checked
    mealie.update_item(item_id, item)
    return _serialize(mealie.get_shopping_list(list_id), unchecked_only=False)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: str,
    principal: CurrentPrincipal,
    db: DbSession,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
) -> Response:
    list_id = _resolve_list_id(db, principal, mealie)
    item = mealie.get_item(item_id)
    if str(item.get("shoppingListId")) != str(list_id):
        raise NotFound("That item isn't on the list.")
    mealie.delete_item(item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/from-menu")
def build_from_menu(
    body: BuildFromMenu,
    principal: CurrentPrincipal,
    db: DbSession,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
) -> dict:
    """Build the list from a week's dinners at their planned servings.

    Two limitations are returned in the response rather than hidden, because
    the user can act on both and neither is a bug to be fixed later:

    - `skipped` says what the pantry already covers, and the matching that
      produced it is approximate. Showing the pairs lets a human spot
      "chicken stock covered by chicken" in a second.
    - `freeform_entries` lists the nights with no recipe attached. Those
      contribute no ingredients, so the list has a real gap and the app should
      say so instead of implying the week is covered.

    Rebuilding is safe: anything already on the list is reported in
    `already_listed` rather than added twice.
    """
    household = principal.household
    if body.week_start is None:
        week_start = current_week_start(household.timezone, household.week_starts_on)
    elif not is_valid_week_start(body.week_start, household.week_starts_on):
        raise BadRequest(
            f"Weeks here start on {household.week_starts_on.title()}.",
            code="bad_week_start",
        )
    else:
        week_start = body.week_start

    entries = db.execute(
        select(MenuEntry).where(
            MenuEntry.household_id == principal.household_id,
            MenuEntry.week_start == week_start,
        )
    ).scalars().all()

    pantry_names = list(
        db.execute(
            select(PantryItem.name).where(
                PantryItem.household_id == principal.household_id,
                PantryItem.used_at.is_(None),
            )
        ).scalars().all()
    )

    scaled: list[tuple[str, dict[str, Any]]] = []
    freeform: list[str] = []
    unavailable: list[str] = []

    for entry in entries:
        if entry.entry_type == "freeform":
            freeform.append(entry.title)
            continue
        try:
            recipe = mealie.get_recipe(entry.mealie_recipe_id or "")
        except NotFound:
            # The recipe was deleted in Mealie after being planned. Skip it,
            # name it, and let the rest of the week still produce a list.
            unavailable.append(entry.title)
            continue
        scaled.append((entry.title, scale_recipe(recipe, entry.servings)))

    current = _load_list(db, principal, mealie)
    existing = [_item_name(item) for item in current.get("listItems") or []]
    needed, skipped, already = collect_needed(scaled, pantry_names, existing)

    list_id = str(current["id"])
    if needed:
        mealie.create_items(list_id, [{"note": item.note()} for item in needed])

    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "added": [item.as_dict() for item in needed],
        "skipped": skipped,
        "already_listed": already,
        "freeform_entries": freeform,
        "unavailable_recipes": unavailable,
        "list": _serialize(mealie.get_shopping_list(list_id), unchecked_only=False),
    }
