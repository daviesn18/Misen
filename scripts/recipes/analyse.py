"""Reading one ingredient line into quantity, unit, and food.

This exists because of a mistake worth recording. The first version of the
importer sent every ingredient to Mealie as free text — `note` and `display`
only, with `quantity: 0` and no food — on the grounds that Mealie's own parser
rewrites the wording and a library of quietly altered quantities is worse than
one of honest strings.

That reasoning was about *display*, and display is not the only reader. Misen
scales recipes by multiplying `quantity`, and builds shopping lists by diffing
`food` against the pantry. With both fields empty, every line came back
`unscaled_no_quantity` and `build_shopping_list` produced nothing at all:
doubling a recipe changed nothing, and the week's shopping list was empty.

So the numbers have to be structured. What keeps the original promise is that
`display` still carries the line exactly as written — Mealie is never asked to
parse anything, this module does it, and the text a person reads is untouched.

The split logic in `ingredients.py` already had to recognise a quantity to
know where one ingredient ended and the next began. This is the same knowledge
used a second time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from recipes.ingredients import VULGAR_FRACTIONS

FRACTION_VALUES = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8, "⅙": 1 / 6, "⅚": 5 / 6,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875, "⅐": 1 / 7,
    "⅑": 1 / 9, "⅒": 0.1,
}

# Canonical spelling per unit, so "Tbsp" and "tablespoons" don't become two
# different units on the same shopping list.
UNITS = {
    "g": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "mg": "mg",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "ml": "ml", "l": "l", "liter": "l", "liters": "l", "litre": "l",
    "cup": "cup", "cups": "cup",
    "tbsp": "Tbsp", "tablespoon": "Tbsp", "tablespoons": "Tbsp", "tbs": "Tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "clove": "clove", "cloves": "clove",
    "can": "can", "cans": "can",
    "packet": "packet", "packets": "packet",
    "package": "package", "packages": "package",
    "stalk": "stalk", "stalks": "stalk",
    "bunch": "bunch", "bunches": "bunch",
    "slice": "slice", "slices": "slice",
    "head": "head", "heads": "head",
    "pinch": "pinch", "pinches": "pinch",
    "dash": "dash", "dashes": "dash",
    "quart": "quart", "quarts": "quart",
    "pint": "pint", "pints": "pint",
    "gallon": "gallon", "gallons": "gallon",
    "stick": "stick", "sticks": "stick",
    "sprig": "sprig", "sprigs": "sprig",
    "bag": "bag", "bags": "bag",
    "jar": "jar", "jars": "jar",
    "box": "box", "boxes": "box",
    "bottle": "bottle", "bottles": "bottle",
    "container": "container", "containers": "container",
    "fillet": "fillet", "fillets": "fillet",
    "piece": "piece", "pieces": "piece",
    "block": "block", "blocks": "block",
}

# Units that are plural in the canonical form Mealie will render.
PLURALS = {
    "cup": "cups", "clove": "cloves", "can": "cans", "packet": "packets",
    "package": "packages", "stalk": "stalks", "bunch": "bunches",
    "slice": "slices", "head": "heads", "pinch": "pinches", "dash": "dashes",
    "quart": "quarts", "pint": "pints", "gallon": "gallons", "stick": "sticks",
    "sprig": "sprigs", "bag": "bags", "jar": "jars", "box": "boxes",
    "bottle": "bottles", "container": "containers", "fillet": "fillets",
    "piece": "pieces", "block": "blocks",
}

# Phrases that mean "some, unmeasured". The food is what follows.
UNMEASURED = ("juice of", "zest of", "dash of", "pinch of", "splash of", "handful of")

# A container word carrying the real food behind "of": "can of tomatoes".
CONTAINERS = (
    "can of", "cans of", "jar of", "jars of", "package of", "packages of",
    "packet of", "packets of", "box of", "bottle of", "bunch of",
)

_NUM = rf"\d+(?:[.,]\d+)?|[{VULGAR_FRACTIONS}]"
_LEADING_QUANTITY = re.compile(
    rf"^\s*(?P<qty>(?:{_NUM})(?:\s*[–—-]\s*(?:{_NUM}))?(?:\s+[{VULGAR_FRACTIONS}])?)"
    # "2% cottage cheese", "0% Greek yogurt" — a digit welded to a percent sign
    # is naming the food, not counting it. Without this the food becomes
    # "% cottage cheese" and the recipe asks for two of it.
    r"(?!%)"
    r"(?P<glued>[a-zA-Z]+)?\b"
)
_PARENTHETICAL = re.compile(r"^\s*\([^)]*\)")


@dataclass
class ParsedIngredient:
    quantity: float | None
    unit: str | None
    food: str | None
    note: str

    def is_usable(self) -> bool:
        """Would Misen do anything with this line?

        Scaling needs a quantity; the shopping diff needs a food. A line with
        neither is guidance to the cook — "salt to taste" — and is meant to be
        skipped. A line where *every* ingredient looks like that is a bug.
        """
        return self.quantity is not None or bool(self.food)


def _number(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    # "7–8" — take the lower bound. Buying for the smaller number and finding
    # you want more is recoverable; the reverse is a second trip.
    text = re.split(r"\s*[–—-]\s*", text)[0].strip()

    total = 0.0
    seen = False
    for part in text.split():
        if part in FRACTION_VALUES:
            total += FRACTION_VALUES[part]
            seen = True
            continue
        # "1½" written without a space.
        match = re.fullmatch(rf"(\d+)([{VULGAR_FRACTIONS}])", part)
        if match:
            total += int(match.group(1)) + FRACTION_VALUES[match.group(2)]
            seen = True
            continue
        try:
            total += float(part.replace(",", "."))
            seen = True
        except ValueError:
            return None
    return total if seen else None


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> tuple[str, str | None]:
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix + " "):
            return text[len(prefix) + 1 :].strip(), prefix
    return text, None


def analyse(line: str) -> ParsedIngredient:
    """Take one ingredient line apart. Never raises; falls back to note-only."""
    note = re.sub(r"\s+", " ", line).strip()
    rest = note

    # "Dash of black pepper" — real ingredient, no measurable amount.
    stripped, phrase = _strip_prefix(rest, UNMEASURED)
    if phrase:
        # "Juice of 1 lime" — the number counts limes, not juice, and the food
        # is the lime. Dropping it would leave "1" as a food name.
        stripped = re.sub(rf"^(?:{_NUM})\s+", "", stripped).strip()
        return ParsedIngredient(None, None, _tidy_food(stripped) or None, note)

    quantity: float | None = None
    unit: str | None = None

    match = _LEADING_QUANTITY.match(rest)
    if match:
        quantity = _number(match.group("qty"))
        if quantity is not None:
            glued = match.group("glued")
            rest = rest[match.end() :].strip()
            if glued and glued.lower() in UNITS:
                # "900g", "24oz" — the unit is welded to the number.
                unit = UNITS[glued.lower()]
            elif glued:
                # Not a unit after all ("2%"): the letters belong to the food.
                rest = f"{glued}{rest}".strip()
                quantity = None
                rest = note
        else:
            rest = note

    if quantity is not None:
        # "(32oz)", "(3 ⅓ cups)" — the same amount said a second way. The
        # original wording survives in `display`; carrying it into the food
        # name would put "(32oz) chicken breast" on a shopping list.
        rest = _PARENTHETICAL.sub("", rest).strip()

        if unit is None:
            head, _, tail = rest.partition(" ")
            if head.lower().strip(".") in UNITS:
                unit = UNITS[head.lower().strip(".")]
                rest = tail.strip()
                rest = _PARENTHETICAL.sub("", rest).strip()

    food = _tidy_food(rest)
    return ParsedIngredient(quantity, unit, food or None, note)


def _tidy_food(text: str) -> str:
    """What to call the thing, for matching against a pantry."""
    text = _PARENTHETICAL.sub("", text).strip()
    text = re.sub(r"^(?:of|each:)\s+", "", text, flags=re.I).strip()
    # "can of fire-roasted tomatoes" — the container is packaging, the food is
    # the tomatoes, and the pantry has tomatoes in it.
    stripped, container = _strip_prefix(text, CONTAINERS)
    if container:
        text = stripped
    return text.strip(" ,;:.")


def display_unit(unit: str | None, quantity: float | None) -> str | None:
    """The plural form when the count calls for it, and only where one exists."""
    if not unit:
        return None
    if quantity is not None and abs(quantity - 1.0) > 1e-6:
        return PLURALS.get(unit, unit)
    return unit
