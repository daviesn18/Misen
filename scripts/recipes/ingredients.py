"""Splitting one run-together line back into separate ingredients.

A cookbook PDF lays ingredients out in two narrow columns. Converting it to
text flattens that, and every line arrives looking like this:

    900g (32oz) chicken breast 120g red enchilada sauce 80g (3 Tbsp) green
    chiles 2 Tbsp garlic purée 1 Tbsp salt Dash of black pepper

Six ingredients, one line, no separator. Nothing downstream works until they
come apart: Mealie parses each *line* into a food and a quantity, and Misen's
shopping-list diff reads those foods. One line in means one shopping item that
reads like a paragraph.

The split is a scan for two kinds of boundary:

1. **A quantity.** A bare number or fraction that isn't inside parentheses and
   isn't part of the thing being described. This is nearly all of them and it
   is high confidence.
2. **A known unquantified phrase** — "Dash of", "Juice of", "Salt and pepper".
   These carry no number, so nothing structural marks them. The list below was
   read off this cookbook rather than imagined, and it is deliberately made of
   *phrases*: a bare "Salt" would split "Salt and pepper" down the middle, and
   a bare "Red" would cut "Red Boat fish sauce" in half.

What it will not do is guess. A fragment that still looks like it holds a
missed boundary is flagged rather than split, because a wrong split is worse
than an unsplit line — the unsplit one is visibly wrong when a human reads the
review file, and the wrong one looks fine and quietly buys the wrong thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VULGAR_FRACTIONS = "½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞⅐⅑⅒"

# A token that is purely a number: 900, 2.5, 1/3, 7–8, ½, 1½.
_NUMBER = rf"(?:\d+(?:[.,]\d+)?(?:[–—-]\d+(?:[.,]\d+)?)?|\d+/\d+|[{VULGAR_FRACTIONS}])"
_PURE_NUMBER = re.compile(rf"^{_NUMBER}[{VULGAR_FRACTIONS}]?$")

# The conversion glues metric quantities to their unit — "900g", "1790g",
# "15g", "400ml". These are quantities and they are how most ingredients in
# this cookbook begin, so failing to recognise them fails almost every split.
_GLUED_UNIT = re.compile(rf"^{_NUMBER}(?:g|kg|mg|oz|ml|l|lb|lbs)$", re.I)

# Words that mean the number after them belongs to the phrase already running,
# not to a new ingredient: "Juice of 2 limes" is one thing, not two.
_CARRIES_ON = {
    "of", "or", "to", "and", "plus", "about", "up", "at", "least", "with",
    "per", "each", "recommended:", "approx", "approximately", "&", "+",
}

# Unquantified ingredients, as phrases. Matched case-insensitively at a word
# boundary. Order matters only in that longer phrases are tried first.
UNQUANTIFIED_PHRASES = (
    "juice of",
    "zest of",
    "dash of",
    "pinch of",
    "splash of",
    "handful of",
    "a dash of",
    "a pinch of",
    "salt and pepper",
    "salt, pepper",
    "salt and black pepper",
    "salt to taste",
    "salt, to taste",
    "black pepper",
    "garlic powder and salt",
    "garlic powder",
    "onion powder",
    "red chili flakes",
    "chili flakes",
    "red pepper flakes",
    "chopped cilantro",
    "chopped green onions",
    "chopped parsley",
    "fresh cilantro",
    "fresh parsley",
    "fresh basil",
    "optional:",
    "salt",
)

# Words that follow a quantity and are still part of it. Used only to decide
# whether a number is starting something new, never to reformat the text.
_UNITS = {
    "g", "kg", "mg", "oz", "lb", "lbs", "ml", "l", "cup", "cups", "tbsp", "tsp",
    "tablespoon", "tablespoons", "teaspoon", "teaspoons", "clove", "cloves",
    "can", "cans", "packet", "packets", "package", "packages", "stalk", "stalks",
    "bunch", "bunches", "slice", "slices", "head", "heads", "pinch", "dash",
    "quart", "quarts", "pint", "pints", "gallon", "gallons", "stick", "sticks",
}


@dataclass
class SplitLine:
    """The result of taking one flattened line apart."""

    ingredients: list[str] = field(default_factory=list)
    # Fragments the scanner believes still contain a boundary it couldn't place.
    # These are reported, never silently accepted.
    suspicious: list[str] = field(default_factory=list)


def _is_quantity(token: str) -> bool:
    """A bare quantity: 900g, 2, 1/3, 7–8, ½, 1½, 24oz.

    Not "2%", not "1/3-fat", not "1%" — a digit welded to a percent sign or a
    hyphenated word is describing the food ("2% cottage cheese"), not counting
    it, and treating it as a quantity cuts every dairy line in half.
    """
    return bool(_PURE_NUMBER.match(token) or _GLUED_UNIT.match(token))


def _blocked_by_previous(previous: str) -> bool:
    """Guards shared by both kinds of boundary.

    Whatever follows a unit, a number, a conjunction or an article belongs to
    the ingredient already being described. Without this, "1 Tbsp salt" splits
    into a quantity and a mystery, and "Garlic powder and salt" splits into
    two half-sentences.
    """
    cleaned = previous.lower().strip(".,;:")
    return (
        cleaned in _CARRIES_ON
        or cleaned in _UNITS
        or cleaned in {"a", "an", "the"}
        or bool(_PURE_NUMBER.match(cleaned))
    )


def _phrase_at(text: str, position: int) -> str | None:
    lowered = text.lower()
    for phrase in sorted(UNQUANTIFIED_PHRASES, key=len, reverse=True):
        end = position + len(phrase)
        if not lowered.startswith(phrase, position):
            continue
        # Must end on a word boundary, so "salt" doesn't match inside "salted".
        if end < len(text) and (text[end].isalnum() or text[end] == "-"):
            continue
        return phrase
    return None


def _boundaries(line: str) -> list[int]:
    """Character offsets where a new ingredient starts."""
    offsets: list[int] = []
    depth = 0
    tokens: list[str] = []
    starts: list[int] = []

    for match in re.finditer(r"\S+", line):
        tokens.append(match.group())
        starts.append(match.start())

    # How far a matched phrase already reaches. "Red chili flakes" matches at
    # "Red"; without this, "chili flakes" matches again two words later and
    # splits the phrase down the middle.
    claimed_to = 0

    for index, token in enumerate(tokens):
        position = starts[index]

        # A token inside parentheses is part of the line already running:
        # "(3 ⅓ cups)" is how much of the previous food, not a new one.
        inside = depth > 0 or token.startswith("(")
        if (
            index > 0
            and position >= claimed_to
            and not inside
            and not _blocked_by_previous(tokens[index - 1])
        ):
            phrase = _phrase_at(line, position)
            # A phrase after a comma is the next item of a list that is already
            # running — "Salt, pepper, garlic powder to taste" is one line, not
            # three. A *quantity* after a comma is still a new ingredient
            # ("boneless, skinless chicken thighs 45g balsamic vinegar").
            if phrase and tokens[index - 1].endswith(","):
                phrase = None

            if _is_quantity(token) or phrase:
                offsets.append(position)
            if phrase:
                claimed_to = position + len(phrase)

        depth += token.count("(") - token.count(")")
        depth = max(depth, 0)

    return offsets


def dedupe_stutter(line: str) -> str:
    """Undo the OCR reading the same words two or three times.

    Pages that were photographed come back like this, verbatim from the source:

        120g (½ cup) Dr Pepper½ cup) Dr Pepper cup) Dr Pepper

    The tail repeats with a few characters shaved off each pass. Find the
    longest ending that also occurs earlier, and cut everything after that
    first occurrence. Ten characters is the floor — shorter than that and a
    line could legitimately end with a phrase it used before.
    """
    for length in range(len(line) // 2, 9, -1):
        tail = line[-length:]
        first = line.find(tail)
        if first != -1 and first + length < len(line):
            return line[: first + length].strip()
    return line


def split_line(line: str) -> SplitLine:
    """Take one flattened ingredient line apart. Never raises."""
    line = re.sub(r"\s+", " ", line).strip()
    if not line:
        return SplitLine()

    cuts = [0, *_boundaries(line), len(line)]
    pieces = [line[a:b].strip(" ,;") for a, b in zip(cuts, cuts[1:], strict=False)]
    # Per piece, not per line: the stutter sits at the end of one ingredient,
    # and by the time the next one has been appended it is no longer a tail.
    pieces = [dedupe_stutter(p) for p in pieces if p]

    result = SplitLine(ingredients=pieces)
    result.suspicious = [p for p in pieces if looks_unsplit(p)]
    return result


# A capitalised word arriving mid-fragment after a lowercase word is the shape
# of a boundary that was missed. It is also the shape of "Parmigiano Reggiano"
# and "Roma tomatoes", so this only ever raises a flag for a human — it never
# causes a split.
_MID_CAPITAL = re.compile(r"(?<=[a-z]) (?!of\b|and\b|or\b|to\b)([A-Z][a-z]{2,})")


def looks_unsplit(fragment: str) -> bool:
    """Does this fragment probably still hold two ingredients?"""
    if len(fragment) > 90:
        return True
    hits = _MID_CAPITAL.findall(fragment)
    # One capitalised word is usually a brand or a proper noun (Hatch, Roma,
    # Greek, Reggiano). Two or more in one short fragment is a smell.
    return len(hits) >= 2


def split_lines(lines: list[str]) -> SplitLine:
    combined = SplitLine()
    for line in lines:
        one = split_line(line)
        combined.ingredients.extend(one.ingredients)
        combined.suspicious.extend(one.suspicious)
    return combined
