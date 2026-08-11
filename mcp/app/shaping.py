"""Turning Companion's responses into something a model reads well.

This layer exists because the two audiences want different things. The app is a
client: it wants stable, fully-specified JSON it can decode into types. A model
is a reader: it wants short, flat, unambiguous text, and every field it doesn't
need is context it pays for and attention it can lose.

So the shapes here are narrower than Companion's. Two rules held throughout:

- **Never drop an id the model needs to act.** `update_pantry_item` and
  `check_shopping_item` take ids, so the tools that list those things must
  return them.
- **Say the awkward part out loud.** A scaled recipe with `scaled_awkward`
  lines carries a plain-English note, because a model that has to infer the
  caveat from a status enum usually won't pass it on.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def _days_until(value: str | None, today: date) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(value) - today).days
    except ValueError:
        return None


def shape_pantry(items: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Pantry rows, with the expiry arithmetic already done.

    The tool description tells the model to lead with what expires within three
    days. Handing it a date and expecting reliable date subtraction is how that
    instruction quietly stops working, so `expires_in_days` is computed here —
    in the household's timezone, negative when something is already overdue.
    """
    shaped = []
    for item in items:
        row: dict[str, Any] = {
            "id": item["id"],
            "name": item["name"],
            "location": item["location"],
        }
        if item.get("quantity"):
            row["quantity"] = item["quantity"]
        if item.get("unit"):
            row["unit"] = item["unit"]
        if item.get("expiry_date"):
            row["expiry_date"] = item["expiry_date"]
            row["expires_in_days"] = _days_until(item["expiry_date"], today)
        if item.get("used_at"):
            row["used"] = True
        shaped.append(row)
    return shaped


def shape_menu(payload: dict[str, Any]) -> dict[str, Any]:
    """The grid, with each night's entry flattened onto the day.

    `meal: null` is an open night. Companion nests the entry under a key and
    marks empty days with an explicit null entry; collapsing that saves a level
    of nesting on every one of fourteen days.
    """
    weeks = []
    for week in payload.get("weeks", []):
        days = []
        for day in week.get("days", []):
            entry = day.get("entry")
            row: dict[str, Any] = {"day": day["day"], "date": day["date"]}
            if entry is None:
                row["meal"] = None
            else:
                row["meal"] = entry["title"]
                if entry.get("mealie_recipe_id"):
                    row["recipe_slug"] = entry["mealie_recipe_id"]
                else:
                    row["freeform"] = True
                for key in ("servings", "notes", "cooked_by"):
                    if entry.get(key) is not None:
                        row[key] = entry[key]
            days.append(row)
        weeks.append(
            {
                "week_start": week["week_start"],
                "week_end": week["week_end"],
                "planned": week["planned"],
                "open": week["open"],
                "days": days,
            }
        )

    return {
        "week_starts_on": payload.get("week_starts_on"),
        "timezone": payload.get("timezone"),
        "weeks": weeks,
        # cooked_by is a member id; get_household maps ids to names.
        "note": "cooked_by is a member id — call get_household to match ids to names.",
    }


def shape_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """One menu entry, as returned after a write."""
    row: dict[str, Any] = {
        "day": entry["day_of_week"],
        "meal": entry["title"],
        "type": entry["entry_type"],
    }
    if entry.get("mealie_recipe_id"):
        row["recipe_slug"] = entry["mealie_recipe_id"]
    for key in ("servings", "notes", "cooked_by"):
        if entry.get(key) is not None:
            row[key] = entry[key]
    return row


def shape_recipe(payload: dict[str, Any]) -> dict[str, Any]:
    """A recipe at the requested scale, plus a note when scaling was imperfect."""
    ingredients = []
    awkward: list[str] = []
    for line in payload.get("ingredients", []):
        row: dict[str, Any] = {"text": line["scaled"]}
        if line["status"] != "scaled":
            row["status"] = line["status"]
        if line["status"] == "scaled_awkward":
            awkward.append(line["scaled"])
        if line.get("section"):
            row["section"] = line["section"]
        ingredients.append(row)

    shaped: dict[str, Any] = {
        "slug": payload.get("slug"),
        "name": payload.get("name"),
        "servings": payload.get("requested_servings") or payload.get("base_servings"),
        "base_servings": payload.get("base_servings"),
        "ingredients": ingredients,
        "instructions": [step["text"] for step in payload.get("instructions", [])],
    }
    if payload.get("total_time"):
        shaped["total_time"] = payload["total_time"]

    notes = []
    if not payload.get("scalable"):
        notes.append(
            "This recipe doesn't say how many it serves, so the quantities are "
            "as written and could not be scaled."
        )
    elif payload.get("factor") not in (None, 1.0):
        notes.append(f"Quantities are scaled by {payload['factor']}× from the original.")
    if awkward:
        notes.append(
            "These lines scaled to quantities a person wouldn't normally write, so "
            "round them sensibly and say so: " + "; ".join(awkward) + "."
        )
    if any(line.get("status") == "unscaled_no_quantity" for line in ingredients):
        notes.append("Lines marked unscaled_no_quantity had no quantity to scale.")
    if notes:
        shaped["scaling_notes"] = " ".join(notes)

    return shaped


def shape_search(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enough to choose a recipe, not enough to cook it. `get_recipe` does that."""
    shaped = []
    for item in items:
        row: dict[str, Any] = {"slug": item.get("slug"), "name": item.get("name")}
        if item.get("totalTime"):
            row["total_time"] = item["totalTime"]
        servings = item.get("recipeServings") or item.get("recipeYieldQuantity")
        if servings:
            row["serves"] = servings
        tags = [tag.get("name") for tag in (item.get("tags") or []) if tag.get("name")]
        if tags:
            row["tags"] = tags
        if item.get("description"):
            row["description"] = item["description"][:200]
        shaped.append(row)
    return shaped


def shape_shopping(payload: dict[str, Any]) -> dict[str, Any]:
    """Grouped by aisle, because that's the order you walk a shop in."""
    aisles = {
        group["aisle"]: [
            {"id": item["id"], "name": item["name"], "checked": item["checked"]}
            for item in group["items"]
        ]
        for group in payload.get("groups", [])
    }
    counts = payload.get("counts", {})
    return {
        "total": counts.get("total", 0),
        "checked": counts.get("checked", 0),
        "remaining": counts.get("remaining", 0),
        "aisles": aisles,
    }


def shape_build_result(payload: dict[str, Any]) -> dict[str, Any]:
    """The two caveats the tool description promises to pass on, made explicit."""
    added = [
        item["name"] + (f" ({item['quantity']})" if item.get("quantity") else "")
        for item in payload.get("added", [])
    ]
    freeform = payload.get("freeform_entries", [])
    skipped = payload.get("skipped", [])
    already = payload.get("already_listed", [])
    unavailable = payload.get("unavailable_recipes", [])

    notes = []
    if skipped:
        # Companion reports one skip per recipe that wanted the ingredient,
        # which is the right shape for a client but reads as "flour (have
        # flour), flour (have flour)" once two nights share a staple. Collapse
        # to distinct pairs, in first-seen order.
        seen: dict[tuple[str, str], None] = {}
        for entry in skipped:
            seen.setdefault((entry["ingredient"], entry["covered_by"]), None)
        pairs = ", ".join(f"{ingredient} (have {have})" for ingredient, have in seen)
        notes.append(
            "Skipped as already in the pantry — the matching is approximate, so "
            f"mention these for the user to sanity-check: {pairs}."
        )
    if freeform:
        notes.append(
            "These nights have no recipe attached and so contributed nothing to "
            f"the list: {', '.join(freeform)}. Ask what they need."
        )
    if already:
        notes.append(f"Already on the list, so not added again: {', '.join(already)}.")
    if unavailable:
        notes.append(
            "These planned recipes are no longer in the library and were skipped: "
            f"{', '.join(unavailable)}."
        )

    result: dict[str, Any] = {
        "week_start": payload.get("week_start"),
        "added": added,
        "list": shape_shopping(payload.get("list", {})),
    }
    if notes:
        result["notes"] = " ".join(notes)
    return result
