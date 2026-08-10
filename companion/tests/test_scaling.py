"""Recipe scaling, and specifically the three statuses.

`scaled_awkward` is the one worth caring about. It's what lets the app be
honest about "1.5 packet yeast" instead of confidently silly, and it is easy
to regress into either always-scaled or a units engine.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.scaling import render_quantity, scale_line, scale_recipe
from tests.conftest import FakeMealie, recipe


def ingredient(quantity, unit=None, food=None, note="", display=""):  # noqa: ANN001, ANN201
    return {
        "quantity": quantity,
        "unit": {"name": unit} if unit else None,
        "food": {"name": food} if food else None,
        "note": note,
        "display": display or note,
    }


# --- quantity rendering ---------------------------------------------------


def test_whole_numbers_render_without_decimals() -> None:
    assert render_quantity(3.0) == "3"
    assert render_quantity(1.0) == "1"


def test_common_fractions_render_as_glyphs() -> None:
    assert render_quantity(1.5) == "1½"
    assert render_quantity(0.5) == "½"
    assert render_quantity(0.33) == "⅓"
    assert render_quantity(2.25) == "2¼"
    assert render_quantity(0.75) == "¾"


def test_uncommon_values_stay_decimal() -> None:
    """Better an honest 2.4 than a wrong 2½."""
    assert render_quantity(2.4) == "2.4"
    assert render_quantity(0.3) == "0.3"


# --- statuses -------------------------------------------------------------


def test_a_clean_multiply_is_scaled() -> None:
    line = scale_line(ingredient(2, unit="cup", food="flour"), 1.5)
    assert line.status == "scaled"
    assert line.quantity == 3.0
    assert "3" in line.scaled


def test_a_line_with_no_quantity_passes_through_untouched() -> None:
    line = scale_line(ingredient(0, note="salt to taste"), 3.0)
    assert line.status == "unscaled_no_quantity"
    assert line.scaled == "salt to taste"
    assert line.quantity is None


def test_a_fraction_of_a_countable_unit_is_awkward() -> None:
    """The PRD's own example: "1.5 packet yeast" is not what a person writes."""
    line = scale_line(ingredient(1, unit="packet", food="yeast"), 1.5)
    assert line.status == "scaled_awkward"
    assert line.quantity == 1.5


def test_a_fraction_of_an_unmeasured_countable_is_awkward() -> None:
    """No unit at all means the food is the unit. You can't buy 1.5 eggs."""
    line = scale_line(ingredient(3, food="egg"), 0.5)
    assert line.status == "scaled_awkward"


def test_whole_countables_are_fine() -> None:
    line = scale_line(ingredient(3, food="egg"), 2.0)
    assert line.status == "scaled"
    assert line.quantity == 6.0


def test_a_measurable_unit_may_be_fractional() -> None:
    line = scale_line(ingredient(2, unit="cup", food="flour"), 0.75)
    assert line.status == "scaled"
    assert line.quantity == 1.5


def test_scaling_below_a_measurable_floor_is_awkward() -> None:
    line = scale_line(ingredient(0.25, unit="teaspoon", food="baking powder"), 0.25)
    assert line.status == "scaled_awkward"


# --- composition ----------------------------------------------------------


def test_plurals_come_from_mealie_not_from_guessing() -> None:
    line = scale_line(
        {
            "quantity": 1,
            "unit": {"name": "cup", "pluralName": "cups"},
            "food": {"name": "onion", "pluralName": "onions"},
            "note": "",
            "display": "1 cup onion",
        },
        3.0,
    )
    assert line.scaled == "3 cups onions"


def test_a_missing_plural_uses_the_singular_rather_than_inventing_one() -> None:
    line = scale_line(ingredient(1, unit="roux", food="stock"), 2.0)
    assert line.scaled == "2 roux stock"


def test_notes_survive_scaling() -> None:
    line = scale_line(
        ingredient(2, unit="cup", food="flour", note="sifted"),
        2.0,
    )
    assert "sifted" in line.scaled


def test_no_unit_conversion_ever() -> None:
    """8 cups stays 8 cups. Going down that road has no bottom."""
    line = scale_line(ingredient(2, unit="cup", food="stock"), 4.0)
    assert "cup" in line.scaled
    assert "quart" not in line.scaled


# --- whole recipe ---------------------------------------------------------


def test_scale_recipe_computes_the_factor() -> None:
    result = scale_recipe(recipe(servings=4), servings=6)
    assert result["base_servings"] == 4
    assert result["requested_servings"] == 6
    assert result["factor"] == 1.5
    assert result["scalable"] is True


def test_a_recipe_with_no_yield_is_not_scalable() -> None:
    """Say so rather than guessing a base of 4."""
    payload = recipe(servings=0)
    payload["recipeYieldQuantity"] = 0
    result = scale_recipe(payload, servings=8)

    assert result["scalable"] is False
    assert result["factor"] == 1.0
    assert result["base_servings"] is None


def test_yield_quantity_is_used_when_servings_is_missing() -> None:
    payload = recipe(servings=0)
    payload["recipeYieldQuantity"] = 2
    assert scale_recipe(payload, servings=4)["factor"] == 2.0


def test_omitting_servings_returns_the_recipe_unscaled() -> None:
    result = scale_recipe(recipe(servings=4), servings=None)
    assert result["factor"] == 1.0
    assert result["ingredients"][0]["quantity"] == 2.0


# --- endpoint -------------------------------------------------------------


def test_scaled_endpoint(client: TestClient, nick: dict[str, str]) -> None:
    body = client.get("/recipes/roast-chicken/scaled?servings=8", headers=nick).json()

    assert body["factor"] == 2.0
    statuses = [line["status"] for line in body["ingredients"]]
    assert statuses == ["scaled", "scaled", "unscaled_no_quantity"]
    assert body["ingredients"][0]["scaled"] == "4 cups flour"
    assert body["ingredients"][1]["scaled"] == "6 eggs"
    assert body["ingredients"][2]["scaled"] == "salt to taste"


def test_scaled_endpoint_reports_awkward_lines(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    mealie.recipes["bread"] = recipe(
        slug="bread",
        name="Bread",
        servings=4,
        ingredients=[ingredient(1, unit="packet", food="yeast", display="1 packet yeast")],
    )
    body = client.get("/recipes/bread/scaled?servings=6", headers=nick).json()
    assert body["ingredients"][0]["status"] == "scaled_awkward"


def test_unknown_recipe_is_a_404(client: TestClient, nick: dict[str, str]) -> None:
    assert client.get("/recipes/nope/scaled", headers=nick).status_code == 404


def test_mealie_down_is_a_502(
    client: TestClient, nick: dict[str, str], mealie: FakeMealie
) -> None:
    mealie.down = True
    response = client.get("/recipes/roast-chicken/scaled", headers=nick)
    assert response.status_code == 502


def test_servings_bounds(client: TestClient, nick: dict[str, str]) -> None:
    assert client.get("/recipes/roast-chicken/scaled?servings=0", headers=nick).status_code == 422
    assert client.get("/recipes/roast-chicken/scaled?servings=-1", headers=nick).status_code == 422
