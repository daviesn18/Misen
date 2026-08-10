"""Turning a week's menu into a shopping list.

Pure functions, no HTTP, so the interesting part is testable on its own.

The matching here is deliberately dumb — case-insensitive substring, both
directions — and the PRD says so out loud. It will miss "scallions" against
"green onions" and it will occasionally tell you to buy something you already
have. That is the right amount of engineering for a list a human edits while
standing in a shop, and the failure is visible and cheap in both directions.
The alternative is an ingredient ontology, which is a different project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.scaling import render_quantity

# Words that carry no signal when matching a pantry item against an ingredient.
# Without this, "chicken" fails to match "boneless chicken breasts, fresh".
NOISE = frozenset(
    {
        "a", "an", "and", "chopped", "diced", "fresh", "frozen", "ground", "large",
        "medium", "minced", "of", "or", "organic", "raw", "small", "the", "thinly",
        "to", "sliced",
    }
)


def normalize(value: str) -> str:
    """Lowercase, strip punctuation, drop noise words and trailing plurals."""
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in value.lower())
    words = [w.rstrip("s") if len(w) > 3 else w for w in cleaned.split() if w not in NOISE]
    return " ".join(words).strip()


def in_pantry(ingredient_name: str, pantry_names: list[str]) -> str | None:
    """The pantry item that covers this ingredient, or None.

    Substring in either direction: "chicken thighs" is covered by a pantry
    entry of "chicken", and a pantry entry of "boneless chicken thighs" covers
    an ingredient of "chicken thighs".
    """
    needle = normalize(ingredient_name)
    if not needle:
        return None
    for original in pantry_names:
        candidate = normalize(original)
        if not candidate:
            continue
        if needle in candidate or candidate in needle:
            return original
    return None


@dataclass
class NeededItem:
    """One line destined for the shopping list."""

    name: str
    quantities: list[tuple[float | None, str | None]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def quantity_text(self) -> str | None:
        """Combine what several recipes each asked for.

        Same unit and all numeric → add them up. Anything else → list them,
        because "2 cups + 1 tbsp" is honest and "3" would be a lie.
        """
        parts = [q for q in self.quantities if q[0] is not None]
        if not parts:
            return None
        units = {unit for _, unit in parts}
        if len(units) == 1:
            total = sum(quantity for quantity, _ in parts)  # type: ignore[misc]
            unit = parts[0][1]
            return f"{render_quantity(total)} {unit}".strip() if unit else render_quantity(total)
        return " + ".join(
            f"{render_quantity(quantity)} {unit}".strip() if unit else render_quantity(quantity)
            for quantity, unit in parts  # type: ignore[arg-type]
        )

    def note(self) -> str:
        """What Mealie stores as the item text.

        The quantity rides along in parentheses rather than in Mealie's numeric
        `quantity` field, because that field is a float and most real
        quantities aren't — "2 lbs" would land as `2` with the pounds dropped,
        and a list that says "2 chicken thighs" when it meant two pounds of
        them is worse than no quantity at all.
        """
        quantity = self.quantity_text()
        return f"{self.name} ({quantity})" if quantity else self.name

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "quantity": self.quantity_text(), "sources": self.sources}


def strip_quantity(text: str) -> str:
    """"flour (4 cups)" → "flour". The inverse of `NeededItem.note()`."""
    head, _, tail = text.partition(" (")
    return head if tail.endswith(")") else text


def collect_needed(
    scaled_recipes: list[tuple[str, dict[str, Any]]],
    pantry_names: list[str],
    already_listed: list[str] | None = None,
) -> tuple[list[NeededItem], list[dict[str, str]], list[str]]:
    """Diff a week's scaled recipes against the pantry and the current list.

    `scaled_recipes` is [(menu entry title, scale_recipe() output)].
    Returns (what to buy, what the pantry already covers, what the list
    already has).

    The third of those is what makes rebuilding safe. "Generate the list from
    the week's dinners" is a button someone presses more than once as a week
    fills in, and without this the second press silently doubles everything.
    """
    on_list = {normalize(strip_quantity(text)) for text in (already_listed or [])}
    needed: dict[str, NeededItem] = {}
    skipped: list[dict[str, str]] = []
    duplicates: list[str] = []

    for source_title, recipe in scaled_recipes:
        for line in recipe.get("ingredients", []):
            food = line.get("food")
            if food:
                name = food
                quantity = (line.get("quantity"), line.get("unit"))
            elif line.get("quantity") is not None:
                # Mealie got a number but couldn't name the food. The scaled
                # text is the most faithful thing we have, and it already
                # carries its own quantity.
                name = line.get("scaled") or line.get("original") or ""
                quantity = (None, None)
            else:
                # Neither a food nor a quantity: "salt to taste", "freshly
                # ground pepper". These are instructions to the cook, not
                # things to put in a trolley, and a list cluttered with them
                # is a list people stop reading.
                continue

            if not name.strip():
                continue

            key = normalize(name) or name.lower()
            if key in on_list:
                if name not in duplicates:
                    duplicates.append(name)
                continue

            covered = in_pantry(name, pantry_names)
            if covered:
                skipped.append({"ingredient": name, "covered_by": covered})
                continue

            item = needed.setdefault(key, NeededItem(name=name))
            item.quantities.append(quantity)
            if source_title not in item.sources:
                item.sources.append(source_title)

    return list(needed.values()), skipped, duplicates
