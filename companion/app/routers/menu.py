"""The weekly menu — PRD §5.

Two things here are worth reading before changing anything.

**An empty night is the absence of a row.** The database stores only what's
planned; `GET /menu` synthesizes the full grid. That means the response always
has seven days per week whether or not anything is on them, and the client
never has to reason about a missing key.

**Freeform meals are first-class.** `{"title": "Nachos"}` with no `recipe_id`
plans a night, and that path has to stay as cheap as it reads. The `CHECK`
constraint in the schema is what keeps a half-freeform, half-recipe row from
ever existing.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentPrincipal, DbSession, Principal
from app.errors import BadRequest, NotFound
from app.mealie import MealieClient, get_mealie
from app.models import Member, MenuEntry
from app.schemas import DayName, MenuEntryOut, MenuEntryUpsert
from app.weeks import current_week_start, is_valid_week_start, week_days

router = APIRouter(prefix="/menu", tags=["menu"])

MAX_WEEKS = 8


def _require_week_start(value: date, week_starts_on: str) -> date:
    if not is_valid_week_start(value, week_starts_on):
        raise BadRequest(
            f"Weeks here start on {week_starts_on.title()}, so {value.isoformat()} "
            f"isn't the start of one.",
            code="bad_week_start",
        )
    return value


def _serialize_week(week_start: date, entries: list[MenuEntry]) -> dict:
    by_day = {entry.day_of_week: entry for entry in entries}
    days = []
    planned = 0
    for name, day_date in week_days(week_start):
        entry = by_day.get(name)
        if entry is not None:
            planned += 1
        days.append(
            {
                "day": name,
                "date": day_date.isoformat(),
                "entry": MenuEntryOut.model_validate(entry).model_dump(mode="json")
                if entry
                else None,
            }
        )
    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "days": days,
        "planned": planned,
        "open": 7 - planned,
    }


@router.get("")
def get_menu(
    principal: CurrentPrincipal,
    db: DbSession,
    week_start: Annotated[date | None, Query()] = None,
    weeks: Annotated[int, Query(ge=1, le=MAX_WEEKS)] = 2,
) -> dict:
    """The grid, filled or empty. Two weeks by default.

    The Menu tab shows this week *and* next week, so returning both in one
    round trip is the difference between one request on tab open and two.
    """
    household = principal.household
    if week_start is None:
        start = current_week_start(household.timezone, household.week_starts_on)
    else:
        start = _require_week_start(week_start, household.week_starts_on)

    last = start + timedelta(days=7 * weeks - 1)
    entries = db.execute(
        select(MenuEntry).where(
            MenuEntry.household_id == principal.household_id,
            MenuEntry.week_start >= start,
            MenuEntry.week_start <= last,
        )
    ).scalars().all()

    grouped: dict[date, list[MenuEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.week_start, []).append(entry)

    return {
        "timezone": household.timezone,
        "week_starts_on": household.week_starts_on,
        "weeks": [
            _serialize_week(start + timedelta(days=7 * offset),
                            grouped.get(start + timedelta(days=7 * offset), []))
            for offset in range(weeks)
        ],
    }


def _resolve_title(
    body: MenuEntryUpsert, mealie: MealieClient
) -> tuple[str, str, str | None]:
    """Work out (entry_type, title, recipe_slug) from a partly-filled body.

    When a recipe is named without a title we fetch it from Mealie — both to
    get the title we cache and to refuse a slug that doesn't exist, which is
    the only moment we can catch a typo cheaply. When the client sends both, we
    trust it: the app already has the recipe on screen, and a second round trip
    to confirm what it just read would make planning fail whenever Mealie is
    briefly down.
    """
    if body.recipe_id:
        if body.title:
            return "recipe", body.title, body.recipe_id
        recipe = mealie.get_recipe(body.recipe_id)
        title = (recipe or {}).get("name") or body.recipe_id
        return "recipe", title, body.recipe_id

    if body.title:
        return "freeform", body.title, None

    raise BadRequest(
        "Give this night a recipe or a name.", code="empty_menu_entry"
    )


def _check_member(db: Session, principal: Principal, member_id: int | None) -> None:
    if member_id is None:
        return
    exists = db.execute(
        select(Member.id).where(
            Member.id == member_id, Member.household_id == principal.household_id
        )
    ).scalar_one_or_none()
    if exists is None:
        raise BadRequest("Nobody in this household has that id.", code="unknown_member")


@router.put("/{week_start}/{day}", response_model=MenuEntryOut)
def upsert_slot(
    week_start: date,
    day: DayName,
    body: MenuEntryUpsert,
    principal: CurrentPrincipal,
    db: DbSession,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
) -> MenuEntry:
    """Plan one night. Overwrites whatever was there."""
    _require_week_start(week_start, principal.household.week_starts_on)
    _check_member(db, principal, body.cooked_by)
    entry_type, title, slug = _resolve_title(body, mealie)

    entry = db.execute(
        select(MenuEntry).where(
            MenuEntry.household_id == principal.household_id,
            MenuEntry.week_start == week_start,
            MenuEntry.day_of_week == day,
            MenuEntry.meal_slot == body.meal_slot,
        )
    ).scalar_one_or_none()

    if entry is None:
        entry = MenuEntry(
            household_id=principal.household_id,
            week_start=week_start,
            day_of_week=day,
            meal_slot=body.meal_slot,
        )
        db.add(entry)

    entry.entry_type = entry_type
    entry.title = title
    entry.mealie_recipe_id = slug
    entry.servings = body.servings
    entry.notes = body.notes
    entry.cooked_by = body.cooked_by
    entry.updated_by = principal.member_id

    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{week_start}/{day}", status_code=status.HTTP_204_NO_CONTENT)
def clear_slot(
    week_start: date,
    day: DayName,
    principal: CurrentPrincipal,
    db: DbSession,
    meal_slot: Annotated[str, Query()] = "dinner",
) -> Response:
    """Make a night open again."""
    entry = db.execute(
        select(MenuEntry).where(
            MenuEntry.household_id == principal.household_id,
            MenuEntry.week_start == week_start,
            MenuEntry.day_of_week == day,
            MenuEntry.meal_slot == meal_slot,
        )
    ).scalar_one_or_none()
    if entry is None:
        raise NotFound("Nothing planned for that night.")

    db.delete(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
