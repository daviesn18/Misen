"""Request and response shapes.

Responses are modelled where the shape is stable (a member, a pantry item) and
left as plain dicts where it is composite and computed — the menu grid, the
scaled recipe, the aisle-grouped shopping list. A Pydantic model over those
would restate the builder function without catching anything it doesn't
already guarantee.

PATCH bodies use `exclude_unset` semantics throughout: absent means "leave it
alone", explicit `null` means "clear it". Collapsing those two is how a client
that sends a partial update accidentally wipes a field.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import DAYS, LOCATIONS

Location = Literal["fridge", "pantry", "freezer"]
DayName = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    initials: str
    color: str
    role: str


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    timezone: str
    week_starts_on: str
    members: list[MemberOut]


# --- pantry ---------------------------------------------------------------


class PantryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    quantity: str | None
    unit: str | None
    location: str
    expiry_date: date | None
    used_at: datetime | None
    added_by: int | None
    added_date: datetime
    updated_at: datetime


class PantryItemCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    quantity: str | None = Field(default=None, max_length=60)
    unit: str | None = Field(default=None, max_length=30)
    location: Location
    expiry_date: date | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("give the item a name")
        return cleaned


class PantryItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    quantity: str | None = Field(default=None, max_length=60)
    unit: str | None = Field(default=None, max_length=30)
    location: Location | None = None
    expiry_date: date | None = None
    # true finishes the item off; false puts it back on hand. Absent leaves it.
    used: bool | None = None


# --- menu -----------------------------------------------------------------


class MenuEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day_of_week: str
    meal_slot: str
    entry_type: str
    mealie_recipe_id: str | None
    title: str
    servings: int | None
    notes: str | None
    cooked_by: int | None
    updated_at: datetime
    updated_by: int | None


class MenuEntryUpsert(BaseModel):
    """One night. A recipe or a plain name — never both, never neither.

    `recipe_id` is a Mealie slug. `title` alone plans a freeform meal, which
    is the whole point of the freeform path: not every night needs a recipe,
    and making someone create one for nachos is how a meal planner stops
    getting used.
    """

    recipe_id: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    servings: int | None = Field(default=None, gt=0, le=99)
    notes: str | None = None
    cooked_by: int | None = None
    meal_slot: str = "dinner"

    @field_validator("title", "recipe_id")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


# --- shopping -------------------------------------------------------------


class ShoppingItemIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    quantity: str | None = Field(default=None, max_length=60)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("give the item a name")
        return cleaned


class ShoppingAdd(BaseModel):
    items: Annotated[list[ShoppingItemIn], Field(min_length=1, max_length=200)]


class ShoppingItemPatch(BaseModel):
    checked: bool


class BuildFromMenu(BaseModel):
    week_start: date | None = None


# --- reminders ------------------------------------------------------------


class ReminderOut(BaseModel):
    day: str | None
    hour: int | None


class ReminderUpdate(BaseModel):
    """Both fields or neither. `{"day": null}` turns the reminder off."""

    day: DayName | None = None
    hour: int | None = Field(default=None, ge=0, le=23)


__all__ = [
    "DAYS",
    "LOCATIONS",
    "BuildFromMenu",
    "HouseholdOut",
    "MemberOut",
    "MenuEntryOut",
    "MenuEntryUpsert",
    "PantryItemCreate",
    "PantryItemOut",
    "PantryItemUpdate",
    "ReminderOut",
    "ReminderUpdate",
    "ShoppingAdd",
    "ShoppingItemIn",
    "ShoppingItemPatch",
]
