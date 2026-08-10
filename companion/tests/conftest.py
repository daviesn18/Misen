"""Test fixtures.

Two households exist in every test that uses `client`, not just the isolation
test. That's deliberate: a bug that leaks rows across tenants only shows up
when there is a second tenant to leak from, and making that the default state
means an accidentally-unscoped query is likely to be caught by whichever test
happens to touch it rather than only by the one test looking for it.

Mealie is never contacted. `FakeMealie` implements the surface `MealieClient`
exposes, so the suite is fast, offline, and — more usefully — able to test the
failure paths (Mealie down, recipe deleted) that a live server won't produce
on demand.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

# Point the app at a scratch database before anything imports the engine.
_TMP = tempfile.mkdtemp(prefix="misen-tests-")
os.environ["MISEN_DB_PATH"] = str(Path(_TMP) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth import generate_token, hash_token  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.errors import MealieUnavailable, NotFound  # noqa: E402
from app.main import app  # noqa: E402
from app.mealie import get_mealie  # noqa: E402
from app.models import Household, Member  # noqa: E402
from app.weeks import today_in, week_start_for  # noqa: E402

# --- a Mealie that isn't there --------------------------------------------


def recipe(
    slug: str = "roast-chicken",
    name: str = "Roast Chicken",
    servings: float = 4,
    ingredients: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A Mealie recipe payload, in Mealie's own camelCase."""
    return {
        "slug": slug,
        "name": name,
        "recipeServings": servings,
        "recipeYieldQuantity": 0,
        "totalTime": "55 min",
        "image": None,
        "recipeIngredient": ingredients
        if ingredients is not None
        else [
            {
                "quantity": 2,
                "unit": {"name": "cup", "pluralName": "cups", "abbreviation": "c"},
                "food": {"name": "flour", "pluralName": "flour"},
                "note": "",
                "display": "2 cups flour",
            },
            {
                "quantity": 3,
                "unit": None,
                "food": {"name": "egg", "pluralName": "eggs"},
                "note": "",
                "display": "3 eggs",
            },
            {
                "quantity": 0,
                "unit": None,
                "food": None,
                "note": "salt to taste",
                "display": "salt to taste",
            },
        ],
        "recipeInstructions": [{"title": "", "text": "Cook it."}],
    }


class FakeMealie:
    """Stands in for MealieClient. Same methods, same return shapes."""

    def __init__(self) -> None:
        self.recipes: dict[str, dict[str, Any]] = {"roast-chicken": recipe()}
        self.lists: dict[str, dict[str, Any]] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self.down = False

    def _id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}-{self._next_id}"

    def _guard(self) -> None:
        if self.down:
            raise MealieUnavailable()

    def get_recipe(self, slug: str) -> dict[str, Any]:
        self._guard()
        if slug not in self.recipes:
            raise NotFound("That recipe isn't in the library.")
        return self.recipes[slug]

    def search_recipes(self, query=None, tags=None, limit=20):  # noqa: ANN001, ANN201
        self._guard()
        return list(self.recipes.values())[:limit]

    def list_shopping_lists(self) -> list[dict[str, Any]]:
        self._guard()
        return [{"id": lid, "name": data["name"]} for lid, data in self.lists.items()]

    def create_shopping_list(self, name: str) -> dict[str, Any]:
        self._guard()
        list_id = self._id("list")
        self.lists[list_id] = {"id": list_id, "name": name}
        return self.lists[list_id]

    def get_shopping_list(self, list_id: str) -> dict[str, Any]:
        self._guard()
        if list_id not in self.lists:
            raise NotFound("no such list")
        items = [i for i in self.items.values() if i["shoppingListId"] == list_id]
        return {**self.lists[list_id], "listItems": items}

    def create_items(self, list_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        self._guard()
        created = []
        for index, item in enumerate(items):
            item_id = self._id("item")
            self.items[item_id] = {
                "id": item_id,
                "shoppingListId": list_id,
                "note": item["note"],
                "display": item["note"],
                "quantity": item.get("quantity", 1),
                "checked": False,
                "isFood": False,
                "position": len(self.items) + index,
                "label": None,
            }
            created.append(self.items[item_id])
        return {"createdItems": created, "updatedItems": [], "deletedItems": []}

    def get_item(self, item_id: str) -> dict[str, Any]:
        self._guard()
        if item_id not in self.items:
            raise NotFound("no such item")
        return dict(self.items[item_id])

    def update_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._guard()
        if item_id not in self.items:
            raise NotFound("no such item")
        self.items[item_id].update(payload)
        return {"createdItems": [], "updatedItems": [self.items[item_id]], "deletedItems": []}

    def delete_item(self, item_id: str) -> None:
        self._guard()
        if item_id not in self.items:
            raise NotFound("no such item")
        del self.items[item_id]


# --- database and app -----------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_database() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def mealie() -> FakeMealie:
    return FakeMealie()


@pytest.fixture
def client(mealie: FakeMealie) -> Iterator[TestClient]:
    app.dependency_overrides[get_mealie] = lambda: mealie
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- households -----------------------------------------------------------


def _make_household(db: Session, name: str, members: list[tuple[str, str]]) -> dict[str, Any]:
    household = Household(name=name, timezone="America/New_York", week_starts_on="monday")
    db.add(household)
    db.flush()

    tokens: dict[str, str] = {}
    ids: dict[str, int] = {}
    for member_name, role in members:
        token = generate_token()
        member = Member(
            household_id=household.id,
            name=member_name,
            initials=member_name[0],
            color="terracotta",
            role=role,
            can_use_basil=role == "adult",
            token_hash=hash_token(token),
        )
        db.add(member)
        db.flush()
        tokens[member_name] = token
        ids[member_name] = member.id

    db.commit()
    return {"id": household.id, "tokens": tokens, "member_ids": ids}


@pytest.fixture
def households(db: Session) -> dict[str, Any]:
    """Two households, and a child in the first.

    Nick and Mara live together. Ivy is their kid, so `can_use_basil` is off.
    Sam lives somewhere else entirely and must never see any of their data.
    """
    first = _make_household(db, "Davies", [("Nick", "adult"), ("Mara", "adult"), ("Ivy", "child")])
    second = _make_household(db, "Elsewhere", [("Sam", "adult")])
    return {"first": first, "second": second}


@pytest.fixture
def auth(households: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Ready-made Authorization headers, one per person."""
    headers = {}
    for house in households.values():
        for name, token in house["tokens"].items():
            headers[name] = {"Authorization": f"Bearer {token}"}
    return headers


@pytest.fixture
def nick(auth: dict[str, dict[str, str]]) -> dict[str, str]:
    return auth["Nick"]


@pytest.fixture
def sam(auth: dict[str, dict[str, str]]) -> dict[str, str]:
    """The other household. Every isolation assertion is made through Sam."""
    return auth["Sam"]


@pytest.fixture
def monday() -> date:
    """The start of the current week, so tests aren't sensitive to the date.

    Computed in the household's timezone, not the container's. A UTC box is
    already on Tuesday while New York is still on Monday evening, and a test
    that used `date.today()` would fail for five hours a day.
    """
    return week_start_for(today_in("America/New_York"), "monday")


@pytest.fixture
def next_monday(monday: date) -> date:
    return monday + timedelta(days=7)
