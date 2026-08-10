"""Shopping — the proxy, and the menu diff.

The diff is where the interesting decisions live, and both of its documented
limitations get a test: the pantry match is approximate, and freeform meals
contribute nothing. Neither is a bug, and both must stay visible in the
response rather than becoming a silent gap in the list.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.shopping_build import NeededItem, collect_needed, in_pantry, normalize
from tests.conftest import FakeMealie, recipe


def names_on(body: dict) -> list[str]:
    return [item["name"] for group in body["groups"] for item in group["items"]]


# --- the proxy ------------------------------------------------------------


def test_empty_list(client: TestClient, nick: dict[str, str]) -> None:
    body = client.get("/shopping", headers=nick).json()
    assert body["groups"] == []
    assert body["counts"] == {"total": 0, "checked": 0, "remaining": 0}


def test_add_items(client: TestClient, nick: dict[str, str]) -> None:
    body = client.post(
        "/shopping",
        headers=nick,
        json={"items": [{"name": "Milk", "quantity": "1 gal"}, {"name": "Eggs"}]},
    ).json()

    assert sorted(names_on(body)) == ["Eggs", "Milk (1 gal)"]
    assert body["counts"]["total"] == 2


def test_quantity_rides_in_the_text_not_in_mealies_float(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    """"2 lbs" in a float field becomes 2, and the pounds are gone."""
    client.post(
        "/shopping", headers=nick, json={"items": [{"name": "Chicken", "quantity": "2 lbs"}]}
    )
    stored = next(iter(mealie.items.values()))
    assert stored["note"] == "Chicken (2 lbs)"


def test_check_and_uncheck(client: TestClient, nick: dict[str, str]) -> None:
    added = client.post("/shopping", headers=nick, json={"items": [{"name": "Milk"}]}).json()
    item_id = added["groups"][0]["items"][0]["id"]

    checked = client.patch(f"/shopping/{item_id}", headers=nick, json={"checked": True}).json()
    assert checked["counts"] == {"total": 1, "checked": 1, "remaining": 0}

    unchecked = client.patch(f"/shopping/{item_id}", headers=nick, json={"checked": False}).json()
    assert unchecked["counts"]["checked"] == 0


def test_unchecked_only_filters_but_still_counts_everything(
    client: TestClient, nick: dict[str, str]
) -> None:
    """The progress bar needs the total; the list needs the remainder."""
    added = client.post(
        "/shopping", headers=nick, json={"items": [{"name": "Milk"}, {"name": "Eggs"}]}
    ).json()
    item_id = added["groups"][0]["items"][0]["id"]
    client.patch(f"/shopping/{item_id}", headers=nick, json={"checked": True})

    body = client.get("/shopping?unchecked_only=true", headers=nick).json()
    assert len(names_on(body)) == 1
    assert body["counts"]["total"] == 2


def test_delete_an_item(client: TestClient, nick: dict[str, str]) -> None:
    added = client.post("/shopping", headers=nick, json={"items": [{"name": "Milk"}]}).json()
    item_id = added["groups"][0]["items"][0]["id"]

    assert client.delete(f"/shopping/{item_id}", headers=nick).status_code == 204
    assert client.get("/shopping", headers=nick).json()["counts"]["total"] == 0


def test_the_list_is_reused_not_recreated(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    client.post("/shopping", headers=nick, json={"items": [{"name": "Milk"}]})
    client.post("/shopping", headers=nick, json={"items": [{"name": "Eggs"}]})
    assert len(mealie.lists) == 1


def test_a_list_deleted_in_mealie_heals(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    """An operator's accident in Mealie's UI shouldn't break the Shopping tab."""
    client.post("/shopping", headers=nick, json={"items": [{"name": "Milk"}]})
    mealie.lists.clear()
    mealie.items.clear()

    body = client.get("/shopping", headers=nick).json()
    assert body["counts"]["total"] == 0
    assert len(mealie.lists) == 1


def test_aisles_are_grouped_with_other_last(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    client.post(
        "/shopping",
        headers=nick,
        json={"items": [{"name": "Milk"}, {"name": "Apples"}, {"name": "Foil"}]},
    )
    for item in mealie.items.values():
        if item["note"] == "Milk":
            item["label"] = {"name": "Dairy"}
        elif item["note"] == "Apples":
            item["label"] = {"name": "Produce"}

    body = client.get("/shopping", headers=nick).json()
    assert [group["aisle"] for group in body["groups"]] == ["Dairy", "Produce", "Other"]


def test_mealie_down_is_a_502(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    mealie.down = True
    assert client.get("/shopping", headers=nick).status_code == 502


def test_adding_nothing_is_rejected(client: TestClient, nick: dict[str, str]) -> None:
    assert client.post("/shopping", headers=nick, json={"items": []}).status_code == 422


# --- the matcher ----------------------------------------------------------


def test_normalize_drops_noise_and_plurals() -> None:
    assert normalize("2 large, fresh Chicken Breasts") == "2 chicken breast"


def test_matching_is_substring_in_both_directions() -> None:
    assert in_pantry("chicken thighs", ["chicken"]) == "chicken"
    assert in_pantry("chicken", ["boneless chicken thighs"]) == "boneless chicken thighs"
    assert in_pantry("flour", ["rice", "sugar"]) is None


def test_the_matcher_is_admittedly_dumb() -> None:
    """Documented in the PRD, asserted here so nobody "fixes" it by accident.

    Making this pass would mean an ingredient ontology, which is a different
    project. The list is a starting point a human edits in the shop.
    """
    assert in_pantry("scallions", ["green onions"]) is None


def test_quantities_of_the_same_unit_add_up() -> None:
    item = NeededItem(name="flour", quantities=[(2.0, "cup"), (1.0, "cup")])
    assert item.quantity_text() == "3 cup"


def test_mismatched_units_are_listed_rather_than_faked() -> None:
    item = NeededItem(name="butter", quantities=[(2.0, "cup"), (1.0, "tablespoon")])
    assert item.quantity_text() == "2 cup + 1 tablespoon"


def test_collect_needed_aggregates_across_recipes() -> None:
    scaled = [
        ("A", {"ingredients": [{"food": "flour", "quantity": 2, "unit": "cup"}]}),
        ("B", {"ingredients": [{"food": "flour", "quantity": 1, "unit": "cup"}]}),
    ]
    needed, _, _ = collect_needed(scaled, [])
    assert len(needed) == 1
    assert needed[0].sources == ["A", "B"]
    assert needed[0].note() == "flour (3 cup)"


# --- from-menu ------------------------------------------------------------


def test_from_menu_builds_the_list_at_planned_servings(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    client.put(
        f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken", "servings": 8}
    )

    body = client.post("/shopping/from-menu", headers=nick, json={}).json()

    added = {item["name"]: item["quantity"] for item in body["added"]}
    assert added["flour"] == "4 cups", "doubled from 2 cups for 8 servings"
    # Plural comes from Mealie's own plural form, applied at the scaled count.
    assert added["eggs"] == "6"


def test_from_menu_skips_what_the_pantry_covers(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    client.post("/pantry", headers=nick, json={"name": "flour", "location": "pantry"})
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})

    body = client.post("/shopping/from-menu", headers=nick, json={}).json()

    assert "flour" not in [item["name"] for item in body["added"]]
    assert body["skipped"] == [{"ingredient": "flour", "covered_by": "flour"}]


def test_a_used_up_pantry_item_does_not_cover_anything(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    item = client.post(
        "/pantry", headers=nick, json={"name": "flour", "location": "pantry"}
    ).json()
    client.patch(f"/pantry/{item['id']}", headers=nick, json={"used": True})
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})

    body = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert "flour" in [i["name"] for i in body["added"]]


def test_freeform_nights_are_reported_as_a_gap(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    """"Nachos" has no ingredients, so the list has a real hole. Say so."""
    client.put(f"/menu/{monday}/monday", headers=nick, json={"title": "Nachos"})
    client.put(f"/menu/{monday}/tuesday", headers=nick, json={"title": "Takeout"})

    body = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert sorted(body["freeform_entries"]) == ["Nachos", "Takeout"]
    assert body["added"] == []


def test_a_recipe_deleted_in_mealie_does_not_sink_the_week(
    client: TestClient, nick: dict[str, str], monday: date, mealie: FakeMealie
) -> None:
    mealie.recipes["stew"] = recipe(slug="stew", name="Stew")
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})
    client.put(f"/menu/{monday}/tuesday", headers=nick, json={"recipe_id": "stew"})
    del mealie.recipes["stew"]

    body = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert body["unavailable_recipes"] == ["Stew"]
    assert body["added"], "the rest of the week still produced a list"


def test_from_menu_writes_to_the_shared_list(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})
    client.post("/shopping/from-menu", headers=nick, json={})

    listed = names_on(client.get("/shopping", headers=nick).json())
    assert any("flour" in name for name in listed)


def test_from_menu_defaults_to_this_week(
    client: TestClient, nick: dict[str, str], monday: date, next_monday: date
) -> None:
    client.put(f"/menu/{next_monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})

    this_week = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert this_week["added"] == []
    assert this_week["week_start"] == monday.isoformat()

    next_week = client.post(
        "/shopping/from-menu", headers=nick, json={"week_start": next_monday.isoformat()}
    ).json()
    assert next_week["added"]


def test_from_menu_rejects_a_mid_week_date(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    from datetime import timedelta

    response = client.post(
        "/shopping/from-menu",
        headers=nick,
        json={"week_start": (monday + timedelta(days=3)).isoformat()},
    )
    assert response.status_code == 400


def test_note_only_lines_do_not_become_shopping_items() -> None:
    """"salt to taste" is an instruction to the cook, not a thing to buy.

    A list cluttered with these is a list people stop reading, so lines with
    neither a food nor a quantity are dropped. A line with a food but no
    quantity — "olive oil" — is a real item and survives.
    """
    scaled = [
        (
            "A",
            {
                "ingredients": [
                    {"food": None, "quantity": None, "scaled": "salt to taste"},
                    {"food": "olive oil", "quantity": None, "unit": None},
                ]
            },
        )
    ]
    needed, _, _ = collect_needed(scaled, [])
    assert [item.name for item in needed] == ["olive oil"]


def test_rebuilding_does_not_duplicate(
    client: TestClient, nick: dict[str, str], monday: date
) -> None:
    """"Build the list" is a button people press twice as a week fills in."""
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})

    first = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert first["added"]
    assert first["already_listed"] == []
    total = first["list"]["counts"]["total"]

    second = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert second["added"] == []
    assert sorted(second["already_listed"]) == sorted(i["name"] for i in first["added"])
    assert second["list"]["counts"]["total"] == total


def test_rebuilding_still_adds_a_newly_planned_night(
    client: TestClient, nick: dict[str, str], monday: date, mealie: FakeMealie
) -> None:
    """Skipping duplicates must not mean skipping everything."""
    client.put(f"/menu/{monday}/monday", headers=nick, json={"recipe_id": "roast-chicken"})
    client.post("/shopping/from-menu", headers=nick, json={})

    mealie.recipes["stew"] = recipe(
        slug="stew",
        name="Stew",
        ingredients=[
            {
                "quantity": 2,
                "unit": {"name": "pound", "pluralName": "pounds"},
                "food": {"name": "beef", "pluralName": "beef"},
                "note": "",
                "display": "2 pounds beef",
            }
        ],
    )
    client.put(f"/menu/{monday}/tuesday", headers=nick, json={"recipe_id": "stew"})

    second = client.post("/shopping/from-menu", headers=nick, json={}).json()
    assert [item["name"] for item in second["added"]] == ["beef"]
    assert second["already_listed"]
