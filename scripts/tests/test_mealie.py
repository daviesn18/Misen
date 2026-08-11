"""The Mealie payload and the uploader.

Field names here were read off Mealie v3.22.0's own schemas. These tests exist
so that a version bump which renames one of them fails here rather than in a
library of ninety silently mangled recipes.
"""

from __future__ import annotations

import httpx
import pytest

from recipes.mealie import MealieUploader, import_recipes
from recipes.model import Nutrition, Recipe, slugify, to_mealie


def a_recipe(**overrides) -> Recipe:  # noqa: ANN003
    base = {
        "title": "Queso Chicken Mac n' Cheese",
        "ingredients": ["900g (32oz) chicken breast", "672g (24 oz) pasta"],
        "sections": {0: "Slow Cooked Chicken", 1: "Pasta"},
        "instructions": ["Dice the chicken.", "Boil the pasta."],
        "servings": 10,
        "nutrition": Nutrition(calories=540, protein_g=46, carbs_g=62, fat_g=13),
        "author": "Tom Walsh",
        "page": 22,
    }
    return Recipe(**{**base, "tags": ["slow cooker"], **overrides})


# --- the payload ----------------------------------------------------------


def test_ingredient_text_survives_exactly_as_written() -> None:
    """`display` is auto-computed from quantity/unit/food unless it is set.
    Leaving it empty is how "900g (32oz) chicken breast" turns into something
    else on the way in."""
    first = to_mealie(a_recipe())["recipeIngredient"][0]
    assert first["display"] == "900g (32oz) chicken breast"


def test_ingredients_carry_the_numbers_misen_reads() -> None:
    """The regression this whole module exists for. Misen scales by
    multiplying `quantity` and shops by matching `food`; an earlier version
    sent free text only, and every recipe refused to scale while every
    generated shopping list came out empty."""
    first = to_mealie(a_recipe())["recipeIngredient"][0]
    assert first["quantity"] == 900
    assert first["unit"] == "g"
    assert first["food"] == "chicken breast"


def test_note_is_a_qualifier_not_a_copy_of_the_line() -> None:
    """Mealie appends `note` after the food when it composes a line, so the
    original text there makes every scaled line read
    "1800 g chicken breast 900g (32oz) chicken breast"."""
    assert to_mealie(a_recipe())["recipeIngredient"][0]["note"] == ""


def test_a_line_with_no_food_keeps_its_text_as_the_note() -> None:
    """Otherwise the ingredient reaches Mealie with nothing to display."""
    entry = to_mealie(a_recipe(ingredients=["Salt to taste"], sections={}))
    ingredient = entry["recipeIngredient"][0]
    assert ingredient["display"] == "Salt to taste"
    assert ingredient["note"] == "Salt to taste" or ingredient.get("food")


def test_every_ingredient_is_something_misen_can_use() -> None:
    """A line with neither a quantity nor a food is skipped by the shopping
    diff. One or two of those is "salt to taste"; all of them is the bug."""
    for ingredient in to_mealie(a_recipe())["recipeIngredient"]:
        assert ingredient.get("quantity") or ingredient.get("food")


def test_ingredients_carry_no_shopping_list_fields() -> None:
    """`isFood` and `disableAmount` belong to shopping list items, not recipe
    ingredients. Mealie rejects neither — it ignores them, which is worse."""
    entry = to_mealie(a_recipe())["recipeIngredient"][0]
    assert "isFood" not in entry
    assert "disableAmount" not in entry


def test_section_headings_ride_on_the_ingredient_that_starts_them() -> None:
    ingredients = to_mealie(a_recipe())["recipeIngredient"]
    assert ingredients[0]["title"] == "Slow Cooked Chicken"
    assert ingredients[1]["title"] == "Pasta"


def test_servings_are_carried_because_misen_scales_from_them() -> None:
    assert to_mealie(a_recipe())["recipeServings"] == 10


def test_nutrition_uses_mealies_field_names() -> None:
    nutrition = to_mealie(a_recipe())["nutrition"]
    assert nutrition == {
        "calories": "540",
        "proteinContent": "46",
        "carbohydrateContent": "62",
        "fatContent": "13",
    }


def test_nutrition_is_omitted_when_there_is_none() -> None:
    payload = to_mealie(a_recipe(nutrition=Nutrition()))
    assert "nutrition" not in payload
    assert payload["settings"]["showNutrition"] is False


def test_attribution_lands_in_the_description() -> None:
    """Mealie has no author field, and a recipe from someone else's book should
    say so."""
    assert "Tom Walsh" in to_mealie(a_recipe())["description"]


def test_warnings_travel_with_the_recipe() -> None:
    payload = to_mealie(a_recipe(warnings=["Read from a photo."]))
    assert payload["notes"] == [{"title": "Import notes", "text": "Read from a photo."}]


def test_a_clean_recipe_carries_no_notes() -> None:
    assert "notes" not in to_mealie(a_recipe())


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Queso Chicken Mac n' Cheese", "queso-chicken-mac-n-cheese"),
        ("Jalapeño Popper Mac N Cheese", "jalapeno-popper-mac-n-cheese"),
        ("Tzatziki Chicken & Harissa Spiced Rice", "tzatziki-chicken-harissa-spiced-rice"),
    ],
)
def test_slugs_match_mealies_shape(title: str, expected: str) -> None:
    assert slugify(title) == expected


# --- the uploader ---------------------------------------------------------


class FakeMealie:
    """Mealie's two-call create, including the detail that catches people out:
    `POST /api/recipes` returns a bare JSON string, not an object."""

    def __init__(self, existing: list[str] | None = None, fail_on: str | None = None) -> None:
        self.recipes: dict[str, dict] = {slug: {} for slug in (existing or [])}
        self.fail_on = fail_on
        self.creates = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/recipes":
            items = [{"slug": slug} for slug in self.recipes]
            return httpx.Response(200, json={"items": items, "totalPages": 1})
        if request.method == "POST" and path == "/api/recipes":
            self.creates += 1
            import json as _json

            name = _json.loads(request.content)["name"]
            if self.fail_on and self.fail_on in name:
                return httpx.Response(500, json={"detail": "boom"})
            slug = slugify(name)
            self.recipes[slug] = {}
            return httpx.Response(201, json=slug)
        if request.method == "PUT" and path.startswith("/api/recipes/"):
            import json as _json

            self.recipes[path.rsplit("/", 1)[1]] = _json.loads(request.content)
            return httpx.Response(200, json={})
        return httpx.Response(404)  # pragma: no cover


def uploader_for(fake: FakeMealie) -> MealieUploader:
    up = MealieUploader("https://mealie.test", "token")
    up._client = httpx.Client(
        base_url="https://mealie.test",
        transport=httpx.MockTransport(fake.handler),
    )
    return up


def test_a_recipe_is_created_then_filled() -> None:
    fake = FakeMealie()
    report = import_recipes(uploader_for(fake), [a_recipe()])

    assert report.created == ["Queso Chicken Mac n' Cheese"]
    stored = fake.recipes["queso-chicken-mac-n-cheese"]
    assert stored["recipeServings"] == 10
    assert len(stored["recipeIngredient"]) == 2


def test_rerunning_skips_what_is_already_there() -> None:
    """A hundred recipes over a home connection will fail somewhere. The fix
    must never be "delete everything and start again"."""
    fake = FakeMealie(existing=["queso-chicken-mac-n-cheese"])
    report = import_recipes(uploader_for(fake), [a_recipe()])

    assert report.skipped == ["Queso Chicken Mac n' Cheese"]
    assert report.created == []
    assert fake.creates == 0


def test_one_bad_recipe_does_not_end_the_run() -> None:
    fake = FakeMealie(fail_on="Broken")
    recipes = [a_recipe(), a_recipe(title="Broken One"), a_recipe(title="Third One")]
    report = import_recipes(uploader_for(fake), recipes)

    assert len(report.created) == 2
    assert [title for title, _ in report.failed] == ["Broken One"]


def test_the_slug_mealie_returns_is_the_one_used() -> None:
    """Mealie owns its slugs and will change one on a collision. Updating the
    locally computed slug instead would write to the wrong recipe, or nothing."""
    fake = FakeMealie()
    uploader = uploader_for(fake)
    slug = uploader.create(a_recipe(title="Café Ragù"))
    assert slug == "cafe-ragu"
    assert fake.recipes[slug]["name"] == "Café Ragù"


# --- confidence -----------------------------------------------------------


def test_a_clean_recipe_is_clean() -> None:
    assert a_recipe().confidence == "clean"


def test_a_warning_alone_means_check_not_poor() -> None:
    """An OCR'd page that came out in the right order is fine to import — it
    just wants a human's eye. Refusing it would throw away good recipes."""
    recipe = a_recipe(warnings=["Read from a photo."])
    assert recipe.confidence == "check"


def test_a_page_that_came_back_as_fragments_is_poor() -> None:
    """Two-column OCR read across the columns: the tail of each ingredient
    lands three lines from its head. Verbatim from the Beef Birria page."""
    recipe = a_recipe(
        ingredients=[
            "1790g (64oz) flat cut",
            "brisket or chuck eye roast",
            "OR lean steak of choice",
            "10 guajillo chiles",
            "Seasonings & Spices:",
            "ground cumin, dried",
        ],
        sections={},
        warnings=["Read from a photo."],
    )
    assert recipe.orphan_rate > 0.15
    assert recipe.confidence == "poor"


def test_ordinary_unquantified_ingredients_are_not_fragments() -> None:
    """"Chopped cilantro" and "Juice of 1 lime" have no leading digit and are
    perfectly good ingredients. Counting them would condemn clean recipes."""
    recipe = a_recipe(
        ingredients=["Chopped cilantro", "Juice of 1 lime", "Salt and pepper", "2 onions"],
        sections={},
    )
    assert recipe.orphan_rate == 0.0
