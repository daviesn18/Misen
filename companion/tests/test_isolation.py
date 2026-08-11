"""Cross-tenant isolation — a phase 1 acceptance criterion.

PRD §4: "Add one test that walks every table and asserts a second household's
data is invisible — that test is the whole defense, and it is worth writing on
day one while there is only one household to break."

This is that test. It writes real data as Nick and then, as Sam from an
entirely different household, tries every way the API offers to see or touch
it. Sam should find nothing and be able to change nothing.

The `test_every_tenant_table_is_covered` test at the bottom is the part that
keeps this honest over time: it fails when a new tenant-scoped table is added
without a corresponding assertion here, so the defence can't silently rot as
the schema grows.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base


@pytest.fixture
def nicks_data(client: TestClient, nick: dict[str, str], monday: date) -> dict:
    """A pantry item, a planned recipe night, a freeform night, a shopping item."""
    item = client.post(
        "/pantry",
        headers=nick,
        json={"name": "Salmon", "location": "fridge", "quantity": "2 fillets"},
    ).json()

    client.put(
        f"/menu/{monday}/monday",
        headers=nick,
        json={"recipe_id": "roast-chicken", "servings": 4},
    )
    client.put(f"/menu/{monday}/tuesday", headers=nick, json={"title": "Nachos"})

    shopping = client.post(
        "/shopping", headers=nick, json={"items": [{"name": "Milk", "quantity": "1 gal"}]}
    ).json()

    client.put("/reminders", headers=nick, json={"day": "friday", "hour": 17})

    return {
        "pantry_id": item["id"],
        "shopping_item_id": shopping["groups"][0]["items"][0]["id"],
    }


# --- reads ----------------------------------------------------------------


def test_pantry_is_invisible_across_households(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    assert client.get("/pantry", headers=sam).json() == []
    assert client.get("/pantry?include_used=true", headers=sam).json() == []


def test_menu_is_invisible_across_households(
    client: TestClient, sam: dict[str, str], nicks_data: dict, monday: date
) -> None:
    body = client.get(f"/menu?week_start={monday}", headers=sam).json()
    entries = [day["entry"] for week in body["weeks"] for day in week["days"]]
    assert all(entry is None for entry in entries), "Sam can see the Davies menu"


def test_household_shows_only_your_own_members(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    body = client.get("/household", headers=sam).json()
    assert body["name"] == "Elsewhere"
    assert [m["name"] for m in body["members"]] == ["Sam"]


def test_shopping_list_is_separate(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    body = client.get("/shopping", headers=sam).json()
    assert body["counts"]["total"] == 0
    assert body["groups"] == []


def test_reminders_are_per_member(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    assert client.get("/reminders", headers=sam).json() == {"day": None, "hour": None}


# --- writes ---------------------------------------------------------------


def test_cannot_read_another_households_pantry_item(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    response = client.patch(
        f"/pantry/{nicks_data['pantry_id']}", headers=sam, json={"used": True}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_cannot_delete_another_households_pantry_item(
    client: TestClient, sam: dict[str, str], nick: dict[str, str], nicks_data: dict
) -> None:
    assert (
        client.delete(f"/pantry/{nicks_data['pantry_id']}", headers=sam).status_code == 404
    )
    # And it really is still there.
    assert len(client.get("/pantry", headers=nick).json()) == 1


def test_cannot_clear_another_households_menu_slot(
    client: TestClient, sam: dict[str, str], nick: dict[str, str], nicks_data: dict, monday: date
) -> None:
    assert client.delete(f"/menu/{monday}/monday", headers=sam).status_code == 404

    body = client.get(f"/menu?week_start={monday}&weeks=1", headers=nick).json()
    assert body["weeks"][0]["days"][0]["entry"]["title"] == "Roast Chicken"


def test_writing_the_same_slot_does_not_collide(
    client: TestClient, sam: dict[str, str], nick: dict[str, str], nicks_data: dict, monday: date
) -> None:
    """Same week, same day, two households. Two rows, not one.

    This is the case the composite unique constraint exists for — a constraint
    on (week_start, day, slot) alone would have made Sam's Monday overwrite
    Nick's.
    """
    client.put(f"/menu/{monday}/monday", headers=sam, json={"title": "Pizza"})

    nicks = client.get(f"/menu?week_start={monday}&weeks=1", headers=nick).json()
    sams = client.get(f"/menu?week_start={monday}&weeks=1", headers=sam).json()

    assert nicks["weeks"][0]["days"][0]["entry"]["title"] == "Roast Chicken"
    assert sams["weeks"][0]["days"][0]["entry"]["title"] == "Pizza"


def test_cannot_check_off_another_households_shopping_item(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    response = client.patch(
        f"/shopping/{nicks_data['shopping_item_id']}", headers=sam, json={"checked": True}
    )
    assert response.status_code == 404


def test_cannot_delete_another_households_shopping_item(
    client: TestClient, sam: dict[str, str], nicks_data: dict
) -> None:
    assert (
        client.delete(f"/shopping/{nicks_data['shopping_item_id']}", headers=sam).status_code
        == 404
    )


def test_cannot_assign_a_cook_from_another_household(
    client: TestClient, sam: dict[str, str], households: dict, monday: date
) -> None:
    """Sam cannot put Nick on the hook for Wednesday."""
    nick_id = households["first"]["member_ids"]["Nick"]
    response = client.put(
        f"/menu/{monday}/wednesday",
        headers=sam,
        json={"title": "Pasta", "cooked_by": nick_id},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_member"


# --- chat -----------------------------------------------------------------


def test_conversations_are_invisible_across_households(
    client: TestClient, nick: dict[str, str], sam: dict[str, str]
) -> None:
    response = client.post("/generate/chat", headers=nick, json={"message": "plan tuesday"})
    first_payload = next(
        line[len("data: ") :] for line in response.text.splitlines() if line.startswith("data: ")
    )
    conversation = json.loads(first_payload)["conversation_id"]

    assert client.get("/generate/conversations", headers=sam).json() == []
    # Sam holding the exact id still finds nothing — the id is not the control.
    assert client.get(f"/generate/conversations/{conversation}", headers=sam).status_code == 404
    assert client.get(f"/generate/conversations/{conversation}", headers=nick).status_code == 200


def test_chat_usage_is_recorded_against_the_right_household(
    client: TestClient, nick: dict[str, str], db, households: dict
) -> None:
    """`chat_usage` has no endpoint, so this asserts the column directly.

    It is the row that answers "is Basil expensive?", and a spend question
    answered across two households is worse than no answer.
    """
    from app.models import ChatUsage

    client.post("/generate/chat", headers=nick, json={"message": "hi"})

    rows = db.execute(select(ChatUsage)).scalars().all()
    assert [row.household_id for row in rows] == [households["first"]["id"]]


# --- the guard that keeps this file honest --------------------------------

# Tables asserted on above. Adding a tenant-scoped table without adding
# coverage here should break the build, not pass quietly.
COVERED = {
    "pantry_items",
    "menu_entries",
    "members",
    "households",
    "chat_messages",
    "chat_usage",
}


def test_every_tenant_table_is_covered() -> None:
    tables = set(Base.metadata.tables)
    uncovered = tables - COVERED
    assert not uncovered, (
        f"New table(s) {sorted(uncovered)} have no cross-tenant isolation test. "
        f"Add one here, or add the name to COVERED with a reason."
    )


def test_every_tenant_table_carries_household_id() -> None:
    """The structural half of the same defence.

    A table without `household_id` cannot be scoped by the one dependency that
    does the scoping, so it would have to be scoped by hand in every handler —
    which is exactly the pattern the PRD rules out.
    """
    for name, table in Base.metadata.tables.items():
        if name == "households":
            continue
        assert "household_id" in table.columns, f"{name} is not tenant-scoped"
