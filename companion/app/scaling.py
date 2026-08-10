"""Recipe scaling — PRD §5.

Scaling lives server-side because three consumers need it (iPhone, iPad Cook
Mode, and the shopping-list diff) and three implementations would drift.

The design commitment worth restating, because every instinct pushes against
it: **this module is deliberately not clever.** No unit conversion — 8 cups
stays 8 cups, never 2 quarts. No pluralization engine — Mealie's own plural
forms are used where it has them and the singular passes through where it
doesn't. What it does instead is be *honest*: every line comes back with a
status saying whether the scaling worked, and `scaled_awkward` exists so the
UI can show "1.5 packet yeast" with a marker rather than pretending that's a
normal thing to write on a shopping list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Units you can't have a fraction of without it reading strangely. Not
# exhaustive and doesn't need to be — a miss produces a line marked `scaled`
# that should have been `scaled_awkward`, which costs the user a small marker,
# not a wrong quantity.
COUNTABLE_UNITS = frozenset(
    {
        "bag", "block", "bottle", "box", "bunch", "can", "clove", "container",
        "ear", "envelope", "fillet", "head", "jar", "loaf", "package", "packet",
        "piece", "sheet", "slice", "sprig", "stalk", "stick", "whole",
    }
)

# Rendered as unicode when the value lands close enough to one of them.
COMMON_FRACTIONS: tuple[tuple[float, str], ...] = (
    (1 / 8, "⅛"),
    (1 / 4, "¼"),
    (1 / 3, "⅓"),
    (3 / 8, "⅜"),
    (1 / 2, "½"),
    (5 / 8, "⅝"),
    (2 / 3, "⅔"),
    (3 / 4, "¾"),
    (7 / 8, "⅞"),
)

FRACTION_TOLERANCE = 0.012  # 0.33 → ⅓, but 0.3 stays 0.3
INTEGER_TOLERANCE = 1e-6
# Below an eighth of anything, a measurement stops being one. Scaling a recipe
# down far enough to ask for 0.06 tsp of baking powder produces a number that
# is arithmetically right and practically useless.
SMALLEST_SENSIBLE = 0.125

STATUS_SCALED = "scaled"
STATUS_NO_QUANTITY = "unscaled_no_quantity"
STATUS_AWKWARD = "scaled_awkward"


@dataclass
class ScaledLine:
    original: str
    scaled: str
    quantity: float | None
    unit: str | None
    food: str | None
    status: str
    # Section headings inside a recipe ("For the sauce"). Carried through so
    # the app can render them without a second pass over the raw recipe.
    section: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "scaled": self.scaled,
            "quantity": self.quantity,
            "unit": self.unit,
            "food": self.food,
            "status": self.status,
            "section": self.section,
        }


def render_quantity(value: float) -> str:
    """A number a person would write.

    1.0 → "1", 1.5 → "1½", 0.33 → "⅓", 2.4 → "2.4".
    """
    if abs(value - round(value)) < INTEGER_TOLERANCE:
        return str(int(round(value)))

    whole = int(value)
    remainder = value - whole
    for fraction, glyph in COMMON_FRACTIONS:
        if abs(remainder - fraction) < FRACTION_TOLERANCE:
            return f"{whole}{glyph}" if whole else glyph

    return f"{round(value, 2):g}"


def _name_for(entity: dict[str, Any] | None, quantity: float, *, abbreviate: bool) -> str:
    """Pick singular or plural from what Mealie actually has.

    No naive "+s". Mealie stores plural forms where a human entered one; where
    it doesn't, the singular is used unchanged. "2 cup flour" is mildly wrong
    and completely clear, which is the right trade against inventing plurals
    for words like "roux".
    """
    if not entity:
        return ""

    plural = abs(quantity - 1.0) > INTEGER_TOLERANCE

    if abbreviate and entity.get("useAbbreviation"):
        candidates = (
            ("pluralAbbreviation", "abbreviation") if plural else ("abbreviation",)
        )
        for key in candidates:
            if entity.get(key):
                return str(entity[key])

    if plural and entity.get("pluralName"):
        return str(entity["pluralName"])
    return str(entity.get("name") or "")


def _original_text(ingredient: dict[str, Any]) -> str:
    for key in ("display", "originalText", "note"):
        value = ingredient.get(key)
        if value:
            return str(value)
    return ""


def _is_countable(unit: dict[str, Any] | None, food: dict[str, Any] | None) -> bool:
    if unit:
        return str(unit.get("name", "")).strip().lower().rstrip("s") in COUNTABLE_UNITS
    # No unit at all and a named food means the food itself is the unit:
    # "3 eggs", "2 onions". You cannot buy 1.5 eggs.
    return bool(food)


def _compose(quantity: float, unit: dict[str, Any] | None, food: dict[str, Any] | None,
             note: str) -> str:
    parts = [render_quantity(quantity)]
    unit_text = _name_for(unit, quantity, abbreviate=True)
    if unit_text:
        parts.append(unit_text)
    food_text = _name_for(food, quantity, abbreviate=False)
    if food_text:
        parts.append(food_text)
    if note:
        parts.append(note)
    return " ".join(p for p in parts if p)


def scale_line(ingredient: dict[str, Any], factor: float) -> ScaledLine:
    """One Mealie ingredient, scaled. Never raises — a weird line degrades."""
    original = _original_text(ingredient)
    unit = ingredient.get("unit") or None
    food = ingredient.get("food") or None
    note = str(ingredient.get("note") or "").strip()
    section = ingredient.get("title") or None

    try:
        quantity = float(ingredient.get("quantity") or 0)
    except (TypeError, ValueError):
        quantity = 0.0

    if quantity <= 0:
        # "salt to taste", or a line Mealie's parser couldn't get a number out
        # of. It passes through untouched and the UI marks it, because
        # silently dropping it would lose an ingredient.
        return ScaledLine(
            original=original,
            scaled=original,
            quantity=None,
            unit=_name_for(unit, 1, abbreviate=False) or None,
            food=_name_for(food, 1, abbreviate=False) or None,
            status=STATUS_NO_QUANTITY,
            section=section,
        )

    scaled_quantity = quantity * factor
    status = STATUS_SCALED
    if _is_countable(unit, food) and abs(scaled_quantity - round(scaled_quantity)) > 0.01:
        status = STATUS_AWKWARD
    elif scaled_quantity < SMALLEST_SENSIBLE:
        status = STATUS_AWKWARD

    return ScaledLine(
        original=original,
        scaled=_compose(scaled_quantity, unit, food, note),
        quantity=round(scaled_quantity, 4),
        unit=_name_for(unit, scaled_quantity, abbreviate=False) or None,
        food=_name_for(food, scaled_quantity, abbreviate=False) or None,
        status=status,
        section=section,
    )


def base_servings(recipe: dict[str, Any]) -> float | None:
    """What the recipe as written serves, or None if it never says.

    Mealie has two fields here for historical reasons: `recipeServings` is the
    modern numeric one, `recipeYieldQuantity` backs the free-text yield. Either
    is a usable denominator; neither being set means scaling is not available
    for this recipe, and the endpoint says so rather than guessing 4.
    """
    for key in ("recipeServings", "recipeYieldQuantity"):
        try:
            value = float(recipe.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def scale_recipe(recipe: dict[str, Any], servings: int | None) -> dict[str, Any]:
    """A Mealie recipe scaled to a serving count.

    Returns the ingredient lines plus enough context for the client to explain
    itself: the base servings, the factor applied, and whether scaling was
    possible at all.
    """
    base = base_servings(recipe)
    requested = servings if servings and servings > 0 else None

    if base is None or requested is None:
        factor = 1.0
        scalable = base is not None
    else:
        factor = requested / base
        scalable = True

    lines = [scale_line(item, factor) for item in (recipe.get("recipeIngredient") or [])]

    return {
        "slug": recipe.get("slug"),
        "name": recipe.get("name"),
        "base_servings": base,
        "requested_servings": requested,
        "factor": round(factor, 4),
        "scalable": scalable,
        "ingredients": [line.as_dict() for line in lines],
        "instructions": [
            {"title": step.get("title") or None, "text": step.get("text") or ""}
            for step in (recipe.get("recipeInstructions") or [])
        ],
        "total_time": recipe.get("totalTime"),
        "image": recipe.get("image"),
    }
