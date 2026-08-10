"""The two-week menu, the freeform path, and week arithmetic."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.conftest import FakeMealie


def test_empty_menu_is_a_full_grid(client: TestClient, nick: dict[str, str]) -> None:
    """An empty night is the absence of a row, but never the absence of a day."""
    body = client.get("/menu", headers=nick).json()

    assert len(body["weeks"]) == 2, "the Menu tab shows this week and next"
    for week in body["weeks"]:
        assert len(week["days"]) == 7
        assert all(day["entry"] is None for day in week["days"])
        assert week["planned"] == 0
        assert week["open"] == 7


def test_weeks_are_consecutive_and_start_on_the_household_day(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    body = client.get("/menu", headers=nick).json()
    first, second = body["weeks"]

    assert first["week_start"] == monday.isoformat()
    assert first["week_end"] == (monday + timedelta(days=6)).isoformat()
    assert second["week_start"] == (monday + timedelta(days=7)).isoformat()
    assert body["week_starts_on"] == "monday"
    assert [d["day"] for d in first["days"]][0] == "monday"


def test_plan_a_recipe(client: TestClient, nick: dict[str, str], monday: date) -> None:
    entry = client.put(
        f"/menu/{monday}/tuesday",
        headers=nick,
        json={"recipe_id": "roast-chicken", "servings": 6},
    ).json()

    assert entry["entry_type"] == "recipe"
    assert entry["mealie_recipe_id"] == "roast-chicken"
    assert entry["title"] == "Roast Chicken", "the title is cached from Mealie"
    assert entry["servings"] == 6
    assert entry["updated_by"] is not None


def test_plan_a_freeform_meal(client: TestClient, nick: dict[str, str], monday: date) -> None:
    """Not every night needs a recipe. This path must stay two taps and a word."""
    entry = client.put(f"/menu/{monday}/friday", headers=nick, json={"title": "Nachos"}).json()

    assert entry["entry_type"] == "freeform"
    assert entry["mealie_recipe_id"] is None
    assert entry["title"] == "Nachos"


def test_a_night_needs_a_recipe_or_a_name(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    response = client.put(f"/menu/{monday}/friday", headers=nick, json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_menu_entry"


def test_planning_a_recipe_that_does_not_exist_fails_loudly(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    """Catching the typo here is cheap. Catching it at dinner time is not."""
    response = client.put(
        f"/menu/{monday}/friday", headers=nick, json={"recipe_id": "no-such-recipe"}
    )
    assert response.status_code == 404


def test_a_client_supplied_title_avoids_the_mealie_round_trip(
    client: TestClient, nick: dict[str, str], monday: date, mealie: FakeMealie
) -> None:
    """The app already has the recipe on screen; planning shouldn't fail
    because Mealie happens to be restarting."""
    mealie.down = True
    entry = client.put(
        f"/menu/{monday}/friday",
        headers=nick,
        json={"recipe_id": "roast-chicken", "title": "Roast Chicken"},
    ).json()
    assert entry["title"] == "Roast Chicken"


def test_mealie_being_down_is_a_502_not_a_500(
    client: TestClient, nick: dict[str, str], monday: date, mealie: FakeMealie
) -> None:
    """The user should be told which half is down."""
    mealie.down = True
    response = client.put(
        f"/menu/{monday}/friday", headers=nick, json={"recipe_id": "roast-chicken"}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "mealie_unavailable"


def test_upsert_overwrites_rather_than_duplicating(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    client.put(f"/menu/{monday}/wednesday", headers=nick, json={"title": "Nachos"})
    client.put(f"/menu/{monday}/wednesday", headers=nick, json={"title": "Tacos"})

    week = client.get(f"/menu?week_start={monday}&weeks=1", headers=nick).json()["weeks"][0]
    wednesday = next(d for d in week["days"] if d["day"] == "wednesday")
    assert wednesday["entry"]["title"] == "Tacos"
    assert week["planned"] == 1


def test_switching_a_recipe_night_to_freeform_clears_the_slug(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    """The CHECK constraint would reject a half-and-half row; make sure the
    handler never builds one."""
    client.put(f"/menu/{monday}/thursday", headers=nick, json={"recipe_id": "roast-chicken"})
    entry = client.put(
        f"/menu/{monday}/thursday", headers=nick, json={"title": "Leftovers"}
    ).json()

    assert entry["entry_type"] == "freeform"
    assert entry["mealie_recipe_id"] is None


def test_planned_and_open_counts_drive_the_stat_cards(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    client.put(f"/menu/{monday}/monday", headers=nick, json={"title": "Nachos"})
    client.put(f"/menu/{monday}/tuesday", headers=nick, json={"title": "Pasta"})

    week = client.get(f"/menu?week_start={monday}&weeks=1", headers=nick).json()["weeks"][0]
    assert week["planned"] == 2
    assert week["open"] == 5


def test_next_week_can_be_planned_ahead(
    client: TestClient, nick: dict[str, str], monday: date, next_monday: date
) -> None:
    """"Maybe I already have plans for next week that I want to put in."""
    client.put(f"/menu/{next_monday}/saturday", headers=nick, json={"title": "Birthday dinner"})

    body = client.get("/menu", headers=nick).json()
    saturday = next(d for d in body["weeks"][1]["days"] if d["day"] == "saturday")
    assert saturday["entry"]["title"] == "Birthday dinner"
    assert body["weeks"][0]["planned"] == 0


def test_a_mid_week_date_is_not_a_week_start(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    wednesday = monday + timedelta(days=2)
    response = client.get(f"/menu?week_start={wednesday}", headers=nick)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_week_start"
    assert "Monday" in response.json()["error"]["message"]


def test_clearing_a_slot(client: TestClient, nick: dict[str, str], monday: date) -> None:
    client.put(f"/menu/{monday}/monday", headers=nick, json={"title": "Nachos"})
    assert client.delete(f"/menu/{monday}/monday", headers=nick).status_code == 204

    week = client.get(f"/menu?week_start={monday}&weeks=1", headers=nick).json()["weeks"][0]
    assert week["days"][0]["entry"] is None
    assert week["open"] == 7


def test_clearing_an_empty_slot_is_a_404(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    assert client.delete(f"/menu/{monday}/monday", headers=nick).status_code == 404


def test_invalid_day_name_is_rejected(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    response = client.put(f"/menu/{monday}/funday", headers=nick, json={"title": "Nachos"})
    assert response.status_code == 422


def test_servings_must_be_positive(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    response = client.put(
        f"/menu/{monday}/monday", headers=nick, json={"title": "Nachos", "servings": 0}
    )
    assert response.status_code == 422


def test_a_deleted_recipe_degrades_to_its_title(
    client: TestClient, nick: dict[str, str], monday: date, mealie: FakeMealie
) -> None:
    """The reason `title` is denormalized: a blank row is useless, a title is not."""
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})
    del mealie.recipes["roast-chicken"]

    week = client.get(f"/menu?week_start={monday}&weeks=1", headers=nick).json()["weeks"][0]
    assert week["days"][0]["entry"]["title"] == "Roast Chicken"


def test_the_grid_does_not_fetch_mealie(
    client: TestClient, nick: dict[str, str], monday: date, mealie: FakeMealie
) -> None:
    """Fourteen day cards must not mean fourteen fetches into Mealie."""
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})
    mealie.down = True

    assert client.get("/menu", headers=nick).status_code == 200


def test_weeks_parameter_bounds(client: TestClient, nick: dict[str, str]) -> None:
    assert len(client.get("/menu?weeks=1", headers=nick).json()["weeks"]) == 1
    assert len(client.get("/menu?weeks=4", headers=nick).json()["weeks"]) == 4
    assert client.get("/menu?weeks=0", headers=nick).status_code == 422
    assert client.get("/menu?weeks=99", headers=nick).status_code == 422


def test_cooked_by_must_be_a_housemate(
    client: TestClient, nick: dict[str, str], households: dict, monday: date
) -> None:
    mara_id = households["first"]["member_ids"]["Mara"]
    entry = client.put(
        f"/menu/{monday}/monday", headers=nick, json={"title": "Nachos", "cooked_by": mara_id}
    ).json()
    assert entry["cooked_by"] == mara_id

    response = client.put(
        f"/menu/{monday}/tuesday", headers=nick, json={"title": "Pasta", "cooked_by": 9999}
    )
    assert response.status_code == 400


def test_week_start_for_handles_every_start_day() -> None:
    from app.weeks import week_start_for

    wednesday = date(2026, 8, 12)
    assert week_start_for(wednesday, "monday") == date(2026, 8, 10)
    assert week_start_for(wednesday, "sunday") == date(2026, 8, 9)
    assert week_start_for(wednesday, "wednesday") == wednesday
    assert week_start_for(wednesday, "thursday") == date(2026, 8, 6)
