"""The ingredient splitter.

Every case here is a real line from the cookbook, not an invented one. The
splitter exists to undo a two-column PDF layout, and inventing tidy inputs for
it would test a problem nobody has.
"""

from __future__ import annotations

import pytest

from recipes.ingredients import dedupe_stutter, looks_unsplit, split_line


def parts(line: str) -> list[str]:
    return split_line(line).ingredients


def test_a_metric_run_comes_apart_at_every_quantity() -> None:
    line = (
        "900g (32oz) chicken breast 120g red enchilada sauce 80g (3 Tbsp) green "
        "chiles 400g (14oz) can of fireroasted tomatoes 2 Tbsp garlic purée"
    )
    assert parts(line) == [
        "900g (32oz) chicken breast",
        "120g red enchilada sauce",
        "80g (3 Tbsp) green chiles",
        "400g (14oz) can of fireroasted tomatoes",
        "2 Tbsp garlic purée",
    ]


def test_a_percentage_describes_the_food_and_never_splits_it() -> None:
    """"2% cottage cheese" and "1% milk" begin with a digit and are not
    quantities. Splitting there halves every dairy line in the book."""
    line = "800g (3 ⅓ cups) 2% cottage cheese 150g (⅔ cup) 1% milk"
    assert parts(line) == ["800g (3 ⅓ cups) 2% cottage cheese", "150g (⅔ cup) 1% milk"]


def test_a_hyphenated_fraction_is_a_description_too() -> None:
    assert parts("100g (½ cup) 1/3-fat cream cheese") == ["100g (½ cup) 1/3-fat cream cheese"]


def test_numbers_inside_parentheses_belong_to_the_line_already_running() -> None:
    assert parts("672g (24 oz) pasta") == ["672g (24 oz) pasta"]
    assert parts("500g (1 ¾ cups) 0% Greek yogurt (recommended: FAGE)") == [
        "500g (1 ¾ cups) 0% Greek yogurt (recommended: FAGE)"
    ]


def test_a_fraction_continues_the_integer_before_it() -> None:
    assert parts("1 ½ Tbsp salt 1 Tbsp garlic powder") == ["1 ½ Tbsp salt", "1 Tbsp garlic powder"]


def test_a_range_is_one_quantity() -> None:
    assert parts("130g (1 cup) sundried tomatoes 7–8 cloves garlic") == [
        "130g (1 cup) sundried tomatoes",
        "7–8 cloves garlic",
    ]


def test_unquantified_ingredients_split_on_their_phrase() -> None:
    line = "1 white onion Juice of 1 lime 1 ½ Tbsp salt Dash of black pepper"
    assert parts(line) == [
        "1 white onion",
        "Juice of 1 lime",
        "1 ½ Tbsp salt",
        "Dash of black pepper",
    ]


def test_the_number_after_of_belongs_to_the_phrase() -> None:
    """"Juice of 2 limes" is one ingredient. Splitting on the 2 makes two."""
    assert parts("Juice of 2 limes") == ["Juice of 2 limes"]


def test_a_unit_never_ends_an_ingredient() -> None:
    """"1 Tbsp salt" must not become "1 Tbsp" and "salt"."""
    assert parts("1 Tbsp salt 2 tsp onion powder") == ["1 Tbsp salt", "2 tsp onion powder"]


def test_a_conjunction_holds_a_phrase_together() -> None:
    assert parts("420g can of green enchilada sauce Garlic powder and salt") == [
        "420g can of green enchilada sauce",
        "Garlic powder and salt",
    ]


def test_a_longer_phrase_wins_over_the_one_inside_it() -> None:
    """"Red chili flakes" must not split into "Red" and "chili flakes"."""
    assert parts("2 tsp black pepper Red chili flakes, to taste") == [
        "2 tsp black pepper",
        "Red chili flakes, to taste",
    ]


def test_a_phrase_after_a_comma_continues_the_list() -> None:
    assert parts("Salt, pepper, garlic powder to taste") == ["Salt, pepper, garlic powder to taste"]


@pytest.mark.parametrize(
    ("stuttered", "expected"),
    [
        ("120g (½ cup) Dr Pepper½ cup) Dr Pepper cup) Dr Pepper", "120g (½ cup) Dr Pepper"),
        (
            "900g (32oz) flat cut brisket or 800g (3 ⅓ cups) 2% cottage⅓ cups) "
            "2% cottage cups) 2% cottage",
            "900g (32oz) flat cut brisket or 800g (3 ⅓ cups) 2% cottage",
        ),
        ("672g (24 oz) pasta", "672g (24 oz) pasta"),
        ("1 Tbsp salt", "1 Tbsp salt"),
    ],
)
def test_ocr_stutter_is_collapsed(stuttered: str, expected: str) -> None:
    """Photographed pages come back reading the same words two or three times.

    Verbatim from the source file, not a hypothetical.
    """
    assert dedupe_stutter(stuttered) == expected


def test_the_stutter_repair_runs_per_ingredient_not_per_line() -> None:
    """By the time the next ingredient is appended, the stutter is no longer a
    tail — so collapsing the whole line first would miss it entirely."""
    line = "120g (½ cup) Dr Pepper½ cup) Dr Pepper cup) Dr Pepper 24g (3 Tbsp) BBQ seasoning"
    assert parts(line) == ["120g (½ cup) Dr Pepper", "24g (3 Tbsp) BBQ seasoning"]


def test_a_single_ingredient_survives_untouched() -> None:
    assert parts("Chopped cilantro") == ["Chopped cilantro"]
    assert parts("3  jalapeños") == ["3 jalapeños"]


def test_empty_input_is_not_an_error() -> None:
    assert parts("") == []
    assert parts("   ") == []


def test_two_proper_nouns_in_a_fragment_raise_a_flag() -> None:
    assert looks_unsplit("1 Tbsp Italian herbs Toppings (per bowl) Extra Cheese")
    assert not looks_unsplit("200g (¾ cup) Parmigiano Reggiano")


def test_flags_are_reported_but_never_acted_on() -> None:
    """A wrong split looks correct and quietly buys the wrong thing. An unsplit
    line is visibly wrong to whoever reads the review file."""
    line = "1 Tbsp Italian herbs Toppings (per bowl)"
    result = split_line(line)
    assert result.ingredients == [line]
    assert result.suspicious == [line]
