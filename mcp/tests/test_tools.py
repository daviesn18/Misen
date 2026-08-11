"""The thirteen tools, driven over the MCP protocol.

Two things get most of the attention here. **Shaping**, because the tool
results are what a model reads and a wrong shape is a wrong answer. And **error
text**, because a model recovers from a mistake only if the tool tells it what
was wrong — a generic failure just makes it give up or, worse, tell the user
something confident and false.
"""

from __future__ import annotations

from tests.conftest import WEEK, FakeCompanion


async def call(connect, name: str, args: dict | None = None):  # noqa: ANN001, ANN201
    async with connect() as client:
        return (await client.call_tool(name, args or {})).data


async def error(connect, name: str, args: dict) -> str:  # noqa: ANN001
    async with connect() as client:
        result = await client.call_tool(name, args, raise_on_error=False)
    assert result.is_error, f"{name} was expected to fail"
    return result.content[0].text


# --- recipes --------------------------------------------------------------


async def test_search_recipes(connect) -> None:  # noqa: ANN001
    results = await call(connect, "search_recipes", {"query": "chicken"})
    assert [r["slug"] for r in results] == ["roast-chicken"]
    assert results[0]["name"] == "Roast Chicken"
    assert results[0]["tags"] == ["Quick"]


async def test_search_returns_enough_to_choose_not_enough_to_cook(connect) -> None:  # noqa: ANN001
    """Ingredients and steps come from get_recipe. Putting them in search
    results would blow up the context for a list the model is only skimming."""
    results = await call(connect, "search_recipes", {})
    assert "ingredients" not in results[0]
    assert "instructions" not in results[0]


async def test_search_survives_mealie_being_down(connect, fake_mealie) -> None:  # noqa: ANN001
    fake_mealie.down = True
    assert "unreachable" in (await error(connect, "search_recipes", {})).lower()


async def test_get_recipe_unscaled(connect) -> None:  # noqa: ANN001
    recipe = await call(connect, "get_recipe", {"slug": "roast-chicken"})
    assert recipe["name"] == "Roast Chicken"
    assert recipe["ingredients"][0]["text"] == "2 cups flour"
    assert recipe["instructions"] == ["Cook it."]


async def test_get_recipe_scaled(connect) -> None:  # noqa: ANN001
    recipe = await call(connect, "get_recipe", {"slug": "roast-chicken", "servings": 8})
    assert recipe["servings"] == 8
    assert recipe["ingredients"][0]["text"] == "4 cups flour"
    assert "scaled by 2" in recipe["scaling_notes"]


async def test_awkward_lines_are_called_out_in_words(connect) -> None:  # noqa: ANN001
    """A model that has to infer the caveat from a status enum usually won't
    pass it on. The note gives it language to use."""
    recipe = await call(connect, "get_recipe", {"slug": "roast-chicken", "servings": 6})
    awkward = [i for i in recipe["ingredients"] if i.get("status") == "scaled_awkward"]
    assert awkward, "1 packet yeast × 1.5 should be awkward"
    assert "round them sensibly" in recipe["scaling_notes"]
    assert "yeast" in recipe["scaling_notes"]


async def test_unquantified_lines_are_flagged_not_dropped(connect) -> None:  # noqa: ANN001
    recipe = await call(connect, "get_recipe", {"slug": "roast-chicken", "servings": 8})
    salt = [i for i in recipe["ingredients"] if "salt" in i["text"]]
    assert salt and salt[0]["status"] == "unscaled_no_quantity"


async def test_unknown_recipe_says_so(connect) -> None:  # noqa: ANN001
    message = await error(connect, "get_recipe", {"slug": "nope"})
    assert "isn't in the library" in message


# --- pantry ---------------------------------------------------------------


async def test_add_and_list_pantry_items(connect) -> None:  # noqa: ANN001
    added = await call(
        connect,
        "add_pantry_item",
        {"name": "Salmon", "location": "fridge", "quantity": "2 fillets"},
    )
    assert added["name"] == "Salmon"
    assert added["quantity"] == "2 fillets"

    items = await call(connect, "get_pantry_items", {})
    assert [i["name"] for i in items] == ["Salmon"]
    assert "id" in items[0], "the id is needed for update_pantry_item"


def household_today():  # noqa: ANN201
    """Today in the household's timezone — the same frame the server uses.

    Deliberately not `date.today()`. A UTC container is already on tomorrow for
    the five hours of a New York evening, which is exactly when someone asks
    what needs using up, and a test written in the wrong frame would fail
    nightly for reasons that look like a bug in the feature rather than in the
    test.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date()


async def test_expiry_arithmetic_is_done_for_the_model(connect) -> None:  # noqa: ANN001
    """The description tells the model to lead with what expires within three
    days. Handing it a bare date and hoping is how that stops working."""
    from datetime import timedelta

    soon = (household_today() + timedelta(days=2)).isoformat()
    await call(
        connect,
        "add_pantry_item",
        {"name": "Milk", "location": "fridge", "expiry_date": soon},
    )
    items = await call(connect, "get_pantry_items", {})
    assert items[0]["expires_in_days"] == 2


async def test_overdue_items_are_negative(connect) -> None:  # noqa: ANN001
    from datetime import timedelta

    past = (household_today() - timedelta(days=3)).isoformat()
    await call(connect, "add_pantry_item", {"name": "Cream", "location": "fridge",
                                            "expiry_date": past})
    items = await call(connect, "get_pantry_items", {})
    assert items[0]["expires_in_days"] == -3


async def test_location_filter(connect) -> None:  # noqa: ANN001
    await call(connect, "add_pantry_item", {"name": "Rice", "location": "pantry"})
    await call(connect, "add_pantry_item", {"name": "Peas", "location": "freezer"})
    items = await call(connect, "get_pantry_items", {"location": "freezer"})
    assert [i["name"] for i in items] == ["Peas"]


async def test_marking_used_hides_it_but_keeps_it(connect) -> None:  # noqa: ANN001
    added = await call(connect, "add_pantry_item", {"name": "Salmon", "location": "fridge"})
    await call(connect, "update_pantry_item", {"item_id": added["id"], "used": True})

    assert await call(connect, "get_pantry_items", {}) == []
    kept = await call(connect, "get_pantry_items", {"include_used": True})
    assert kept[0]["name"] == "Salmon" and kept[0]["used"] is True


async def test_updating_part_of_a_quantity(connect) -> None:  # noqa: ANN001
    added = await call(connect, "add_pantry_item", {"name": "Flour", "location": "pantry",
                                                    "quantity": "1 bag"})
    updated = await call(connect, "update_pantry_item", {"item_id": added["id"],
                                                         "quantity": "half a bag"})
    assert updated["quantity"] == "half a bag"


async def test_an_empty_update_is_refused_with_a_hint(connect) -> None:  # noqa: ANN001
    message = await error(connect, "update_pantry_item", {"item_id": 1})
    assert "used=true" in message


async def test_updating_a_missing_item_says_so(connect) -> None:  # noqa: ANN001
    message = await error(connect, "update_pantry_item", {"item_id": 9999, "used": True})
    assert "isn't in the pantry" in message


# --- menu -----------------------------------------------------------------


async def test_empty_menu_is_a_full_grid(connect) -> None:  # noqa: ANN001
    menu = await call(connect, "get_weekly_menu", {})
    assert len(menu["weeks"]) == 2
    assert len(menu["weeks"][0]["days"]) == 7
    assert all(day["meal"] is None for day in menu["weeks"][0]["days"])
    assert menu["weeks"][0]["open"] == 7


async def test_plan_a_recipe_night(connect) -> None:  # noqa: ANN001
    entry = await call(
        connect,
        "set_weekly_menu",
        {"week_start": WEEK, "day": "monday", "recipe_slug": "roast-chicken", "servings": 6},
    )
    assert entry["meal"] == "Roast Chicken"
    assert entry["type"] == "recipe"
    assert entry["servings"] == 6


async def test_plan_a_freeform_night(connect) -> None:  # noqa: ANN001
    """Not every night needs a recipe, and the tool must make that as easy as
    the recipe path — otherwise the model will invent a recipe for nachos."""
    entry = await call(connect, "set_weekly_menu",
                       {"week_start": WEEK, "day": "friday", "title": "Nachos"})
    assert entry["meal"] == "Nachos"
    assert entry["type"] == "freeform"
    assert "recipe_slug" not in entry


async def test_week_start_defaults_to_the_current_week(connect) -> None:  # noqa: ANN001
    """Asked of Companion rather than computed here, so there is only one
    implementation of week arithmetic in the system."""
    entry = await call(connect, "set_weekly_menu", {"day": "tuesday", "title": "Pasta"})
    assert entry["week_start"] == WEEK


async def test_a_night_needs_a_recipe_or_a_name(connect) -> None:  # noqa: ANN001
    message = await error(connect, "set_weekly_menu", {"day": "monday"})
    assert "recipe_slug or a title" in message


async def test_a_bad_week_start_explains_itself(connect) -> None:  # noqa: ANN001
    """The single most important error message in this server.

    A model will get week_start wrong; it recovers only because Companion's
    message names the rule and this layer passes it through untouched.
    """
    message = await error(connect, "set_weekly_menu",
                          {"week_start": "2026-08-12", "day": "monday", "title": "x"})
    assert "Monday" in message


async def test_planning_an_unknown_recipe_says_so(connect) -> None:  # noqa: ANN001
    message = await error(connect, "set_weekly_menu",
                          {"week_start": WEEK, "day": "monday", "recipe_slug": "nope"})
    assert "isn't in the library" in message


async def test_an_unknown_cook_is_named_as_the_problem(connect) -> None:  # noqa: ANN001
    message = await error(
        connect,
        "set_weekly_menu",
        {"week_start": WEEK, "day": "monday", "title": "x", "cooked_by": 99},
    )
    assert "has that id" in message


async def test_planned_nights_show_up_in_the_grid(connect) -> None:  # noqa: ANN001
    async with connect() as client:
        await client.call_tool("set_weekly_menu",
                               {"week_start": WEEK, "day": "monday",
                                "recipe_slug": "roast-chicken"})
        await client.call_tool("set_weekly_menu",
                               {"week_start": WEEK, "day": "tuesday", "title": "Nachos"})
        menu = (await client.call_tool("get_weekly_menu", {"weeks": 1})).data

    days = {day["day"]: day for day in menu["weeks"][0]["days"]}
    assert days["monday"]["meal"] == "Roast Chicken"
    assert days["monday"]["recipe_slug"] == "roast-chicken"
    assert days["tuesday"]["freeform"] is True
    assert days["wednesday"]["meal"] is None
    assert menu["weeks"][0]["planned"] == 2
    assert menu["weeks"][0]["open"] == 5


async def test_the_menu_explains_that_cooked_by_is_an_id(connect) -> None:  # noqa: ANN001
    menu = await call(connect, "get_weekly_menu", {"weeks": 1})
    assert "get_household" in menu["note"]


async def test_clearing_a_night(connect) -> None:  # noqa: ANN001
    async with connect() as client:
        await client.call_tool("set_weekly_menu",
                               {"week_start": WEEK, "day": "monday", "title": "Nachos"})
        cleared = (await client.call_tool("clear_menu_slot",
                                          {"week_start": WEEK, "day": "monday"})).data
        menu = (await client.call_tool("get_weekly_menu", {"weeks": 1})).data

    assert cleared["meal"] is None
    assert menu["weeks"][0]["planned"] == 0


async def test_clearing_an_empty_night_says_so(connect) -> None:  # noqa: ANN001
    message = await error(connect, "clear_menu_slot", {"week_start": WEEK, "day": "sunday"})
    assert "Nothing planned" in message


# --- shopping -------------------------------------------------------------


async def test_shopping_list_starts_empty(connect) -> None:  # noqa: ANN001
    shopping = await call(connect, "get_shopping_list", {})
    assert shopping == {"total": 0, "checked": 0, "remaining": 0, "aisles": {}}


async def test_add_to_shopping_list(connect) -> None:  # noqa: ANN001
    shopping = await call(
        connect,
        "add_to_shopping_list",
        {"items": [{"name": "Milk", "quantity": "1 gal"}, {"name": "Eggs"}]},
    )
    names = [item["name"] for item in shopping["aisles"]["Other"]]
    assert names == ["Milk (1 gal)", "Eggs"]
    assert shopping["total"] == 2


async def test_shopping_items_carry_ids_for_checking_off(connect) -> None:  # noqa: ANN001
    added = await call(connect, "add_to_shopping_list", {"items": [{"name": "Milk"}]})
    item_id = added["aisles"]["Other"][0]["id"]

    checked = await call(connect, "check_shopping_item", {"item_id": item_id})
    assert checked["checked"] == 1
    assert checked["remaining"] == 0


async def test_unchecked_only_still_reports_the_total(connect) -> None:  # noqa: ANN001
    """The progress figure needs the whole list; the shopping needs the rest."""
    async with connect() as client:
        added = (await client.call_tool(
            "add_to_shopping_list", {"items": [{"name": "Milk"}, {"name": "Eggs"}]}
        )).data
        await client.call_tool(
            "check_shopping_item", {"item_id": added["aisles"]["Other"][0]["id"]}
        )
        remaining = (await client.call_tool("get_shopping_list",
                                            {"unchecked_only": True})).data

    assert remaining["total"] == 2
    assert len(remaining["aisles"]["Other"]) == 1


async def test_items_need_names(connect) -> None:  # noqa: ANN001
    message = await error(connect, "add_to_shopping_list", {"items": [{"quantity": "2"}]})
    assert "needs a name" in message


async def test_build_shopping_list_passes_on_both_caveats(connect) -> None:  # noqa: ANN001
    """The tool description promises to tell the user two things. If they
    aren't in the result, the model can't."""
    async with connect() as client:
        await client.call_tool("set_weekly_menu",
                               {"week_start": WEEK, "day": "monday",
                                "recipe_slug": "roast-chicken"})
        await client.call_tool("set_weekly_menu",
                               {"week_start": WEEK, "day": "tuesday", "title": "Nachos"})
        built = (await client.call_tool("build_shopping_list", {"week_start": WEEK})).data

    assert built["added"] == ["flour (2 cups)"]
    assert "approximate" in built["notes"]
    assert "Nachos" in built["notes"]


async def test_repeated_pantry_skips_are_collapsed(connect) -> None:  # noqa: ANN001
    """Two nights sharing a staple should not read as "yeast (have yeast),
    yeast (have yeast)" — that noise scales with the size of the week."""
    async with connect() as client:
        for day in ("monday", "tuesday", "wednesday"):
            await client.call_tool("set_weekly_menu",
                                   {"week_start": WEEK, "day": day,
                                    "recipe_slug": "roast-chicken"})
        built = (await client.call_tool("build_shopping_list", {"week_start": WEEK})).data

    assert built["notes"].count("yeast (have yeast)") == 1


async def test_build_defaults_to_this_week(connect) -> None:  # noqa: ANN001
    built = await call(connect, "build_shopping_list", {})
    assert built["week_start"] == WEEK


# --- household ------------------------------------------------------------


async def test_get_household(connect) -> None:  # noqa: ANN001
    household = await call(connect, "get_household", {})
    assert household["name"] == "Davies"
    assert household["week_starts_on"] == "monday"
    assert {m["name"] for m in household["members"]} == {"Nick", "Mara", "Ivy"}
    assert [m for m in household["members"] if m["name"] == "Ivy"][0]["role"] == "child"


async def test_household_does_not_leak_credentials(connect) -> None:  # noqa: ANN001
    """Companion returns capability flags; the model has no use for them and
    they read like something it should act on."""
    household = await call(connect, "get_household", {})
    assert "token_hash" not in str(household)
    assert all(set(m) == {"id", "name", "role"} for m in household["members"])


async def test_the_household_is_fetched_once_per_run(connect, fake_companion) -> None:  # noqa: ANN001
    """Two tools need the timezone on every call. Without the cache, listing
    the pantry costs two round trips instead of one."""
    async with connect() as client:
        await client.call_tool("get_household", {})
        await client.call_tool("get_pantry_items", {})
        await client.call_tool("get_household", {})

    assert fake_companion.calls.count(("GET", "/household")) == 1


async def test_a_broken_household_call_does_not_break_the_pantry(
    connect, fake_companion: FakeCompanion  # noqa: ANN001
) -> None:
    """The cache is an optimisation; the pantry is the point.

    Companion's /household is only needed for the timezone, so if it fails the
    tool should still fail loudly rather than return items with silently wrong
    expiry maths.
    """
    fake_companion.fail_paths = {"/household"}
    message = await error(connect, "get_pantry_items", {})
    assert "unreachable" in message.lower()
