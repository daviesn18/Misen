"""SQLAlchemy models — the schema in PRD §4.

Two rules hold everywhere in this file:

1. **Every tenant-scoped table carries `household_id`, and every unique
   constraint includes it.** Including where it looks redundant. The
   redundancy is the point: no query can cross tenants by joining through a
   table that forgot.

2. **Timestamps are naive UTC.** SQLite has no timezone type. A column that
   silently drops the offset on write is worse than one that never carried
   one, so `utcnow()` is the only thing that writes these and everything
   reading them knows what it has. Conversion to household-local time happens
   at the edge, from `households.timezone`.

The `CheckConstraint`s mirror the PRD DDL rather than using SQLAlchemy `Enum`,
which on SQLite compiles to a VARCHAR plus a check anyway — this way the
generated schema is the schema that was specified.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
LOCATIONS = ("fridge", "pantry", "freezer")
ROLES = ("adult", "child")


def utcnow() -> datetime:
    """Naive UTC. The only clock this schema uses."""
    return datetime.now(UTC).replace(tzinfo=None)


def _in(column: str, values: tuple[str, ...]) -> str:
    joined = ",".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


class Household(Base):
    __tablename__ = "households"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="America/New_York", server_default="America/New_York"
    )
    week_starts_on: Mapped[str] = mapped_column(
        String(10), nullable=False, default="monday", server_default="monday"
    )
    # Mealie's own tenancy is separate from ours; NULL means the default group.
    mealie_group_id: Mapped[str | None] = mapped_column(String(64))
    # Resolved lazily on first shopping call, then cached here. Mealie supports
    # many lists per household; Misen has exactly one and needs to find the
    # same one every time. Looking it up by name would break the day someone
    # renames it in Mealie's UI.
    mealie_shopping_list_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    members: Mapped[list[Member]] = relationship(back_populates="household")

    __table_args__ = (
        CheckConstraint(_in("week_starts_on", DAYS), name="ck_households_week_start"),
    )


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(
        ForeignKey("households.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    initials: Mapped[str] = mapped_column(String(4), nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str] = mapped_column(
        String(10), nullable=False, default="adult", server_default="adult"
    )
    # sha256 of the bearer token, hex. The token itself is printed once by
    # scripts/provision.py and never stored anywhere.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    plan_reminder_day: Mapped[str | None] = mapped_column(String(10))
    plan_reminder_hour: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    household: Mapped[Household] = relationship(back_populates="members")

    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="ck_members_role"),
        CheckConstraint(
            f"plan_reminder_day IS NULL OR {_in('plan_reminder_day', DAYS)}",
            name="ck_members_reminder_day",
        ),
        CheckConstraint(
            "plan_reminder_hour IS NULL OR (plan_reminder_hour BETWEEN 0 AND 23)",
            name="ck_members_reminder_hour",
        ),
    )


class PantryItem(Base):
    __tablename__ = "pantry_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[str | None] = mapped_column(String(60))
    unit: Mapped[str | None] = mapped_column(String(30))
    location: Mapped[str] = mapped_column(String(10), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    # Soft state. NULL means on hand; a timestamp means finished, and the row
    # stays queryable for a while because "we finished the salmon Tuesday" is
    # useful context on Wednesday.
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    added_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        CheckConstraint(_in("location", LOCATIONS), name="ck_pantry_location"),
        Index("idx_pantry_active", "household_id", "location", "used_at"),
    )


class MenuEntry(Base):
    __tablename__ = "menu_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    day_of_week: Mapped[str] = mapped_column(String(10), nullable=False)
    meal_slot: Mapped[str] = mapped_column(
        String(20), nullable=False, default="dinner", server_default="dinner"
    )
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # The Mealie SLUG, not the UUID — Mealie's API paths are slug-based.
    mealie_recipe_id: Mapped[str | None] = mapped_column(String(200))
    # Cache of Mealie's title when entry_type='recipe'; the source of truth
    # when entry_type='freeform'. The CHECK below keeps the two from blurring.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    servings: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    cooked_by: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("members.id"))

    __table_args__ = (
        UniqueConstraint(
            "household_id", "week_start", "day_of_week", "meal_slot", name="uq_menu_slot"
        ),
        CheckConstraint(_in("day_of_week", DAYS), name="ck_menu_day"),
        CheckConstraint("entry_type IN ('recipe','freeform')", name="ck_menu_entry_type"),
        CheckConstraint(
            "(entry_type = 'recipe' AND mealie_recipe_id IS NOT NULL)"
            " OR (entry_type = 'freeform' AND mealie_recipe_id IS NULL)",
            name="ck_menu_type_matches_recipe_id",
        ),
        CheckConstraint("servings IS NULL OR servings > 0", name="ck_menu_servings_positive"),
        Index("idx_menu_week", "household_id", "week_start"),
    )
