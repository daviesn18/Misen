"""Reading an ingredient line into quantity, unit and food.

This module exists because of a bug, and the bug is worth stating: the first
importer sent every ingredient to Mealie as free text with no quantity and no
food. Misen scales by multiplying `quantity` and shops by matching `food`, so
every recipe silently refused to scale and every generated shopping list came
out empty. These tests are the guard on that.
"""

from __future__ import annotations

import pytest

from recipes.analyse import analyse, display_unit


@pytest.mark.parametrize(
    ("line", "quantity", "unit", "food"),
    [
        # The dominant shape in this cookbook: metric weight welded to its unit.
        ("900g (32oz) chicken breast", 900, "g", "chicken breast"),
        ("672g (24 oz) pasta", 672, "g", "pasta"),
        ("2 Tbsp garlic purée", 2, "Tbsp", "garlic purée"),
        ("½ tsp cayenne", 0.5, "tsp", "cayenne"),
        ("1 ½ Tbsp salt", 1.5, "Tbsp", "salt"),
        ("2 packets taco seasoning", 2, "packet", "taco seasoning"),
        # No unit: the food is the unit. "1 onion", not "1 of onion".
        ("1 onion", 1, None, "onion"),
        ("15 basil leaves", 15, None, "basil leaves"),
    ],
)
def test_a_quantity_and_unit_come_off_the_front(
    line: str, quantity: float, unit: str | None, food: str
) -> None:
    parsed = analyse(line)
    assert parsed.quantity == pytest.approx(quantity)
    assert parsed.unit == unit
    assert parsed.food == food


def test_a_second_measure_in_parentheses_is_not_part_of_the_food() -> None:
    """"(32oz)" is the same 900g said again. Left in, the shopping list reads
    "(32oz) chicken breast"."""
    assert analyse("800g (3 ⅓ cups) 2% cottage cheese").food == "2% cottage cheese"


def test_a_percentage_stays_with_the_food() -> None:
    """"2% cottage cheese" begins with a digit and is not a quantity. Reading
    it as one leaves "cottage cheese" priced at two of something."""
    parsed = analyse("2% cottage cheese")
    assert parsed.quantity is None
    assert parsed.food == "2% cottage cheese"


def test_a_range_takes_the_lower_bound() -> None:
    """Buying for 7 and wanting 8 is recoverable. The reverse is a second trip."""
    parsed = analyse("7–8 cloves garlic")
    assert parsed.quantity == 7
    assert parsed.unit == "clove"
    assert parsed.food == "garlic"


def test_packaging_is_not_the_food() -> None:
    """The pantry has tomatoes in it, not cans."""
    assert analyse("400g (14oz) can of fireroasted tomatoes").food == "fireroasted tomatoes"


def test_unmeasured_ingredients_keep_a_food_and_no_quantity() -> None:
    """A real thing to buy, with no amount — the PRD's "olive oil" case. It
    belongs on the shopping list; it just can't be scaled."""
    parsed = analyse("Dash of black pepper")
    assert parsed.quantity is None
    assert parsed.food == "black pepper"


def test_juice_of_counts_the_fruit_not_the_juice() -> None:
    """"Juice of 1 lime" — the 1 counts limes. Keeping it as the quantity would
    put "1 juice" on the list; dropping the food would leave a bare number."""
    parsed = analyse("Juice of 1 lime")
    assert parsed.quantity is None
    assert parsed.food == "lime"


def test_a_line_with_no_number_still_has_a_food() -> None:
    assert analyse("Chopped cilantro").food == "Chopped cilantro"


def test_units_are_spelled_one_way() -> None:
    """"Tbsp" and "tablespoons" must not become two units on one list."""
    assert analyse("2 tablespoons honey").unit == "Tbsp"
    assert analyse("2 Tbsp honey").unit == "Tbsp"
    assert analyse("3 teaspoons salt").unit == "tsp"


def test_plurals_are_used_only_where_one_exists() -> None:
    assert display_unit("cup", 2) == "cups"
    assert display_unit("cup", 1) == "cup"
    assert display_unit("g", 900) == "g", "no such thing as 900 gs"
    assert display_unit(None, 3) is None


def test_every_line_is_usable_or_deliberately_not() -> None:
    """Misen skips a line with neither a quantity nor a food — that is how
    "salt to taste" stays off the shopping list. Everything else must carry
    one, or it vanishes from the recipe entirely."""
    for line in (
        "900g (32oz) chicken breast",
        "Dash of black pepper",
        "Chopped cilantro",
        "1 onion",
    ):
        assert analyse(line).is_usable(), line
