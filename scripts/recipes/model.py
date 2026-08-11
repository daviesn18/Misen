"""The shape every importer produces and the Mealie uploader consumes.

Recipe Keeper and a cookbook PDF have nothing in common as inputs. They have
one thing in common as outputs, and that thing is this file — so the uploader,
the review report, and the tests are written once.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from recipes.analyse import analyse, display_unit


@dataclass
class Nutrition:
    calories: int | None = None
    protein_g: int | None = None
    carbs_g: int | None = None
    fat_g: int | None = None

    def is_empty(self) -> bool:
        return not any((self.calories, self.protein_g, self.carbs_g, self.fat_g))


@dataclass
class Recipe:
    title: str
    ingredients: list[str] = field(default_factory=list)
    # Ingredient section headings ("Slow Cooked Chicken:", "Pasta:") mapped to
    # the index of the first ingredient under them. Mealie stores these on the
    # ingredient, so they're carried separately and applied at upload.
    sections: dict[int, str] = field(default_factory=dict)
    instructions: list[str] = field(default_factory=list)
    servings: int | None = None
    nutrition: Nutrition = field(default_factory=Nutrition)
    tags: list[str] = field(default_factory=list)
    source: str = ""
    author: str = ""
    page: int | None = None
    # Everything the parser was unsure about. Never silently dropped: a recipe
    # imports with its warnings attached so a human can see what to check.
    warnings: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.title)

    def is_complete(self) -> bool:
        return bool(self.title and self.ingredients and self.instructions)

    @property
    def orphan_rate(self) -> float:
        """Share of ingredients that begin with neither a quantity nor a capital.

        "brisket or chuck eye roast", "yogurt or skyr", "fire-roasted tomatoes"
        — each of these is the tail of an ingredient whose head is three lines
        away, because the page was photographed in two columns and the OCR read
        across them. One or two is normal; a third of the list means the
        reading order was destroyed.
        """
        if not self.ingredients:
            return 0.0
        orphans = sum(1 for line in self.ingredients if _looks_like_an_orphan(line))
        return orphans / len(self.ingredients)

    @property
    def confidence(self) -> str:
        """`clean`, `check`, or `poor` — what a human needs to do about it.

        `poor` is not a failure to be hidden. It means the page came back as
        fragments and the recipe wants typing in by hand; saying so is more
        use than importing something that reads like a recipe and isn't.
        """
        # One orphan in seven is where a list stops being a list. Below that a
        # human fixes a line; above it they are reconstructing the page, and
        # retyping from the book is faster and more trustworthy.
        if self.orphan_rate > 0.15:
            return "poor"
        return "check" if self.warnings else "clean"


def _looks_like_an_orphan(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped[0].isdigit() or stripped[0] in "½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞":
        return False
    # "OR lean steak of choice" — the continuation of an alternative whose
    # first half is somewhere else on the page.
    if stripped[:3].upper() == "OR ":
        return True
    # A heading that ended up in the list rather than above it.
    if stripped.endswith(":"):
        return True
    # A real unquantified ingredient is written like one: "Chopped cilantro",
    # "Juice of 1 lime", "Salt and pepper". A wrapped fragment starts mid-phrase.
    return stripped[0].islower()


def slugify(value: str) -> str:
    """Mealie's own slug shape: lowercase, ascii, hyphenated."""
    ascii_only = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_only.lower())).strip("-")


def to_mealie(recipe: Recipe) -> dict[str, Any]:
    """A Mealie recipe payload for `PUT /api/recipes/{slug}`.

    Field names and shapes were read off Mealie v3.22.0's own schemas, not
    remembered. Three of them are not what you would guess:

    - `RecipeIngredient` has **no** `isFood` or `disableAmount`. Those belong
      to shopping list items. An ingredient carries `note`, `display`, and an
      optional `title` that is the section heading.
    - `display` is auto-computed from quantity/unit/food unless it is already
      set, so it is set here explicitly. That is what makes "900g (32oz)
      chicken breast" survive as written.
    - `nutrition` is a real model with string fields, not free text.

    Nothing is handed to Mealie's ingredient *parser* — `analyse` does that
    work here, where it can be tested — but the quantity, unit and food it
    finds are sent as structured fields, because Misen reads them. Scaling
    multiplies `quantity`; the shopping-list diff matches `food` against the
    pantry. An earlier version sent everything as free text to protect the
    wording, and the result was recipes that would not scale and weeks that
    produced an empty shopping list.

    `display` still carries the line exactly as written, so the protection
    that motivated the free-text version survives: nobody's "900g (32oz)
    chicken breast" turns into something else on the way in.
    """
    ingredients = []
    for index, text in enumerate(recipe.ingredients):
        parsed = analyse(text)
        entry: dict[str, Any] = {
            # Mealie's `note` is a qualifier — "chopped", "divided" — that it
            # appends *after* the food when composing a line. Putting the whole
            # original text there makes every scaled line read "1800 g chicken
            # breast 900g (32oz) chicken breast". The original belongs in
            # `display`, and only lines with no food need it as a note.
            "note": "" if parsed.food else text,
            "display": text,
            "quantity": parsed.quantity if parsed.quantity is not None else 0,
        }
        if parsed.unit:
            entry["unit"] = display_unit(parsed.unit, parsed.quantity)
        if parsed.food:
            entry["food"] = parsed.food
        if index in recipe.sections:
            entry["title"] = recipe.sections[index]
        ingredients.append(entry)

    payload: dict[str, Any] = {
        "name": recipe.title,
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"text": step} for step in recipe.instructions],
        "tags": [{"name": tag} for tag in recipe.tags],
        "settings": {"showNutrition": not recipe.nutrition.is_empty()},
    }
    if recipe.servings:
        # Misen scales from this. A recipe with no serving count comes back
        # `unscalable` from /recipes/{slug}/scaled — honest, but useless — so
        # it is worth carrying even when nothing else about the recipe is.
        payload["recipeServings"] = recipe.servings
    if recipe.source:
        payload["orgURL"] = recipe.source

    if not recipe.nutrition.is_empty():
        macros = recipe.nutrition
        payload["nutrition"] = {
            key: str(value)
            for key, value in {
                "calories": macros.calories,
                "proteinContent": macros.protein_g,
                "carbohydrateContent": macros.carbs_g,
                "fatContent": macros.fat_g,
            }.items()
            if value is not None
        }

    # Mealie has no author field, so attribution rides in the description —
    # which is the field anyone actually reads, and the right place for it.
    description = []
    if recipe.author:
        description.append(f"From {recipe.author}.")
    if recipe.page:
        description.append(f"Page {recipe.page}.")
    if description:
        payload["description"] = " ".join(description)

    if recipe.warnings:
        # Warnings travel with the recipe, not only in a report nobody opens
        # twice. Someone cooking this in six months should be able to see that
        # a line was recovered from a photograph.
        payload["notes"] = [{"title": "Import notes", "text": " ".join(recipe.warnings)}]

    return payload
