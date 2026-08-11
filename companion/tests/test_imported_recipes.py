"""Recipes that came from the importer, not from Mealie's own scraper.

`scripts/` writes recipes into Mealie with quantity, unit and food filled in
by its own parser rather than Mealie's. That is a contract across two packages
that nothing else checks: Companion can't import `scripts`, and `scripts` has
no Mealie to read back from.

So the shape the importer produces is reproduced here and run through the two
things that consume it. The first version of the importer sent every
ingredient as free text — no quantity, no food — and the result was recipes
that silently refused to scale and weeks whose shopping list came out empty.
Both of those pass every test in the rest of this suite, because every other
fixture comes from Mealie's parser and has the fields.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from app.scaling import scale_recipe
from app.shopping_build import collect_needed


def imported(quantity: float, unit: str | None, food: str | None, display: str) -> dict[str, Any]:
    """One ingredient as `scripts/recipes/model.to_mealie` writes it, after
    Mealie has stored it and handed it back as records."""
    return {
        # `note` is a qualifier Mealie appends after the food, so the importer
        # leaves it empty whenever it has a food to give.
        "note": "" if food else display,
        "display": display,
        "quantity": quantity,
        "unit": {"name": unit, "pluralName": unit} if unit else None,
        "food": {"name": food, "pluralName": food} if food else None,
    }


def imported_recipe(slug: str = "queso-chicken-mac-n-cheese") -> dict[str, Any]:
    """A real recipe from the first imported cookbook, verbatim."""
    return {
        "slug": slug,
        "name": "Queso Chicken Mac n' Cheese",
        "recipeServings": 10,
        "recipeYieldQuantity": 0,
        "totalTime": None,
        "recipeIngredient": [
            imported(900, "g", "chicken breast", "900g (32oz) chicken breast"),
            imported(2, "Tbsp", "garlic purée", "2 Tbsp garlic purée"),
            imported(0.5, "tsp", "cayenne", "½ tsp cayenne"),
            imported(672, "g", "pasta", "672g (24 oz) pasta"),
            imported(800, "g", "2% cottage cheese", "800g (3 ⅓ cups) 2% cottage cheese"),
            imported(1, None, "onion", "1 onion"),
            # No measurable amount, but a real thing to buy.
            imported(0, None, "Chopped cilantro", "Chopped cilantro"),
        ],
        "recipeInstructions": [{"title": "", "text": "Cook it."}],
    }


# --- scaling --------------------------------------------------------------


def test_an_imported_recipe_actually_scales() -> None:
    scaled = scale_recipe(imported_recipe(), servings=20)

    assert scaled["scalable"] is True
    assert scaled["factor"] == 2.0
    statuses = [line["status"] for line in scaled["ingredients"]]
    assert statuses.count("scaled") == 6, "everything with a number must scale"
    assert statuses.count("unscaled_no_quantity") == 1, "only the cilantro"


def test_the_scaled_text_does_not_repeat_itself() -> None:
    """Mealie composes a line as quantity + unit + food + note. An importer
    that puts the whole original line in `note` produces "1800 g chicken
    breast 900g (32oz) chicken breast" — correct arithmetic, unreadable."""
    scaled = scale_recipe(imported_recipe(), servings=20)
    first = scaled["ingredients"][0]

    assert first["scaled"] == "1800 g chicken breast"
    assert first["original"] == "900g (32oz) chicken breast"


def test_the_original_wording_is_preserved() -> None:
    """The importer's whole reason for setting `display` itself."""
    scaled = scale_recipe(imported_recipe(), servings=10)
    originals = [line["original"] for line in scaled["ingredients"]]
    assert "800g (3 ⅓ cups) 2% cottage cheese" in originals


def test_a_percentage_in_a_food_name_is_not_a_quantity() -> None:
    """"2% cottage cheese" scaled by two is 1600g of the same cheese, not
    4% of anything."""
    scaled = scale_recipe(imported_recipe(), servings=20)
    line = next(i for i in scaled["ingredients"] if "cottage" in (i["food"] or ""))
    assert line["scaled"] == "1600 g 2% cottage cheese"


# --- the shopping diff ----------------------------------------------------


def test_an_imported_recipe_produces_a_shopping_list() -> None:
    scaled = scale_recipe(imported_recipe(), servings=10)
    needed, skipped, duplicates = collect_needed([("Queso Chicken", scaled)], pantry_names=[])

    assert len(needed) == 7, "every ingredient is something to buy"
    assert not skipped and not duplicates


def test_an_unmeasured_ingredient_still_reaches_the_list() -> None:
    """PRD §5: a line with a food but no quantity ("olive oil") is a real item
    and stays. Only a line with neither is guidance to the cook."""
    scaled = scale_recipe(imported_recipe(), servings=10)
    needed, _, _ = collect_needed([("Queso Chicken", scaled)], pantry_names=[])
    assert any("cilantro" in item.name.lower() for item in needed)


def test_the_pantry_diff_matches_on_the_imported_food_names() -> None:
    scaled = scale_recipe(imported_recipe(), servings=10)
    needed, skipped, _ = collect_needed(
        [("Queso Chicken", scaled)], pantry_names=["pasta", "onion"]
    )

    covered = {entry["ingredient"] for entry in skipped}
    assert "pasta" in covered and "onion" in covered
    assert not any(item.name == "pasta" for item in needed)


# --- through the API ------------------------------------------------------


def test_the_scaled_endpoint_serves_an_imported_recipe(
    client: TestClient, nick: dict[str, str], mealie: Any
) -> None:
    mealie.recipes["imported"] = imported_recipe(slug="imported")

    body = client.get("/recipes/imported/scaled?servings=30", headers=nick).json()

    assert body["scalable"] is True
    assert body["factor"] == 3.0
    assert body["ingredients"][0]["scaled"] == "2700 g chicken breast"


def test_building_a_week_from_imported_recipes_fills_the_list(
    client: TestClient, nick: dict[str, str], mealie: Any, monday: date
) -> None:
    """The end of the chain: a cookbook page becomes a shopping list."""
    mealie.recipes["imported"] = imported_recipe(slug="imported")
    client.put(
        f"/menu/{monday}/tuesday",
        headers=nick,
        json={"recipe_id": "imported", "servings": 20},
    )

    body = client.post("/shopping/from-menu", headers=nick, json={"week_start": str(monday)}).json()

    assert len(body["added"]) == 7
    doubled = next(item for item in body["added"] if "chicken" in item["name"].lower())
    assert doubled["quantity"] == "1800 g"
