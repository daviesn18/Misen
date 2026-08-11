"""The cookbook parser, against the shapes the real conversion produces.

The fixture below is not a tidy invented cookbook. It reproduces the four
things that actually go wrong in the file this was written for: titles that
are plain text, ingredient columns flattened onto one line, a page whose text
survives only as OCR inside an image block, and a page listed in the contents
that is not in the document at all.
"""

from __future__ import annotations

import pytest

from recipes.cookbook import parse_cookbook, parse_toc

FIXTURE = """\
#### TABLE OF CONTENTS

###### **MEALS**

|Queso Chicken Mac n' Cheese|**22**|
|---|---|
|Missing Photo Recipe|**23**|
|Pineapple Teriyaki Pulled Pork|**24**|
|**.**<br>Chili Mac|**25**|

###### **PROTEINS**

|Butter Chicken|**83**|
|---|---|

# MEALS

Queso Chicken Mac n' Cheese

###### **Per Serving: makes 10**

###### **540 Calories**

###### **46G Protein 62G Carbs 13G Fat**

###### **ingredients**

###### **Slow Cooked Chicken:**

900g (32oz) chicken breast 2 Tbsp garlic purée 1 Tbsp salt

###### **Pasta:**

672g (24 oz) pasta

###### **instructions**

1. Dice the **chicken breast** and add to the slow cooker. Cover and cook on
high for 2-3 hours.

2. Bring a pot of salted water to a boil, add **pasta** ,

- then drain and set aside.

> back to table of contents 22

<!-- Start of picture text -->
SS<br>i (a SF Sa. sysi<br>- FIRE R<br>: < Ske<br>
<!-- End of picture text -->

Pineapple teriyaki pulled pork

###### **Per Serving: makes 10**

<!-- Start of picture text -->
580 Calories 44g Protein 59g Carbs 17g Fat<br>ingredients<br>Pork & Marinade:<br>1790g (64oz) Pork loin 100g soy sauce<br>1 Pineapple (400g) 80g honey<br>instructions<br>1.Cut the pork loin into four large pieces and place them in the slow cooker.<br>
<!-- End of picture text -->

- 1.Cut the **pork loin** into four large pieces and place them in the slow cooker.

- 2.Shred the pork with two forks.

> back to table of contents 24

<!-- Start of picture text -->
480 Calories<br><!-- End of picture text -->

###### **Per Serving: makes 8**

###### **ingredients**

###### **Beef:**

500g ground beef 1 onion

###### **instructions**

1. Brown the **beef** .

> back to table of contents 25

Butter Chicken

###### **Per Serving: makes 7**

###### **ingredients**

###### **Chicken:**

1000g chicken thighs 2 Tbsp butter

###### **instructions**

1. Cook it.

> back to table of contents 83
"""


@pytest.fixture
def parsed():  # noqa: ANN201
    return parse_cookbook(FIXTURE, author="Tom Walsh", origin="Test Cookbook")


def by_title(parsed, title):  # noqa: ANN001, ANN201
    return next(r for r in parsed.recipes if r.title == title)


# --- the contents ---------------------------------------------------------


def test_the_contents_is_the_list_of_what_should_exist() -> None:
    entries = parse_toc(FIXTURE)
    assert [e.title for e in entries] == [
        "Queso Chicken Mac n' Cheese",
        "Missing Photo Recipe",
        "Pineapple Teriyaki Pulled Pork",
        "Chili Mac",
        "Butter Chicken",
    ]


def test_a_placeholder_cell_does_not_shift_the_page_numbers() -> None:
    """Rows arrive as `|**.**<br>Chili Mac|**25**|`. Zipping the "." against
    the page number would put Chili Mac on no page at all."""
    entries = {e.title: e.page for e in parse_toc(FIXTURE)}
    assert entries["Chili Mac"] == 25


def test_the_protein_section_is_tagged(parsed) -> None:  # noqa: ANN001
    assert "protein-only" in by_title(parsed, "Butter Chicken").tags


# --- ordinary pages -------------------------------------------------------


def test_a_clean_page_parses_whole(parsed) -> None:  # noqa: ANN001
    recipe = by_title(parsed, "Queso Chicken Mac n' Cheese")
    assert recipe.servings == 10
    assert recipe.page == 22
    assert recipe.nutrition.calories == 540
    assert recipe.nutrition.protein_g == 46
    assert recipe.ingredients == [
        "900g (32oz) chicken breast",
        "2 Tbsp garlic purée",
        "1 Tbsp salt",
        "672g (24 oz) pasta",
    ]
    assert recipe.sections == {0: "Slow Cooked Chicken", 3: "Pasta"}


def test_a_wrapped_step_is_rejoined_not_filed_as_an_ingredient(parsed) -> None:  # noqa: ANN001
    """The converter wraps long steps onto a stray bullet. Left alone it lands
    in the shopping list as a sentence, and the step stays cut off mid-phrase."""
    recipe = by_title(parsed, "Queso Chicken Mac n' Cheese")
    assert recipe.instructions[1].endswith("then drain and set aside.")
    assert not any("drain" in line for line in recipe.ingredients)


def test_the_contents_capitalisation_wins(parsed) -> None:  # noqa: ANN001
    """The body prints "Pineapple teriyaki pulled pork"; the contents has it
    properly cased, and that is what a person will search for."""
    assert by_title(parsed, "Pineapple Teriyaki Pulled Pork")


# --- damaged pages --------------------------------------------------------


def test_a_photographed_page_is_recovered_from_its_ocr(parsed) -> None:  # noqa: ANN001
    recipe = by_title(parsed, "Pineapple Teriyaki Pulled Pork")
    assert "1790g (64oz) Pork loin" in recipe.ingredients
    assert "100g soy sauce" in recipe.ingredients
    assert any("photo" in w for w in recipe.warnings), "the reader must be told"


def test_ocr_noise_is_thrown_away(parsed) -> None:  # noqa: ANN001
    """`SS<br>i (a SF Sa. sysi` is a photograph of food, not a recipe."""
    for recipe in parsed.recipes:
        assert not any("sysi" in line for line in recipe.ingredients)


def test_a_title_lost_to_an_image_is_recovered_from_the_page_number(parsed) -> None:  # noqa: ANN001
    """The name was part of the photo; the page footer survived, and the
    contents knows what is printed on page 25."""
    recipe = by_title(parsed, "Chili Mac")
    assert recipe.ingredients == ["500g ground beef", "1 onion"]
    assert any("table of contents" in w for w in recipe.warnings)


def test_a_page_that_is_not_in_the_file_is_reported_not_dropped(parsed) -> None:  # noqa: ANN001
    assert [m.title for m in parsed.missing] == ["Missing Photo Recipe"]


def test_nothing_is_counted_twice(parsed) -> None:  # noqa: ANN001
    titles = [r.title for r in parsed.recipes]
    assert len(titles) == len(set(titles))
    assert len(parsed.recipes) + len(parsed.missing) == len(parse_toc(FIXTURE))


def test_every_parsed_recipe_is_usable(parsed) -> None:  # noqa: ANN001
    assert parsed.partial == []
    for recipe in parsed.recipes:
        assert recipe.is_complete()
        assert recipe.author == "Tom Walsh"
        assert recipe.source == "Test Cookbook"
