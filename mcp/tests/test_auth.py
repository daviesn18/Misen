"""Auth, and the tenancy story that depends on it.

The MCP server holds no member credential of its own. Everything here checks
that the caller's token is the only thing granting access, and that it is
passed through rather than substituted.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import VALID_TOKEN, FakeCompanion

MCP_PROBE = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


async def test_a_valid_token_connects(connect) -> None:  # noqa: ANN001
    async with connect() as client:
        assert len(await client.list_tools()) == 13


async def test_a_bad_token_is_rejected(raw) -> None:  # noqa: ANN001
    async with raw("not-a-real-token") as http:
        response = await http.post("/mcp", json=MCP_PROBE, headers=MCP_HEADERS)
    assert response.status_code == 401


async def test_no_token_is_rejected(raw) -> None:  # noqa: ANN001
    async with raw() as http:
        response = await http.post("/mcp", json=MCP_PROBE, headers=MCP_HEADERS)
    assert response.status_code == 401


async def test_a_401_says_how_to_authenticate(raw) -> None:  # noqa: ANN001
    """The MCP spec wants a WWW-Authenticate header on a 401 so a client knows
    what to do next. Getting this wrong makes a connector fail opaquely."""
    async with raw("nope") as http:
        response = await http.post("/mcp", json=MCP_PROBE, headers=MCP_HEADERS)
    assert "www-authenticate" in {key.lower() for key in response.headers}


async def test_the_callers_token_is_forwarded_not_a_server_credential(
    connect, fake_companion: FakeCompanion  # noqa: ANN001
) -> None:
    """The whole tenancy design in one assertion.

    Companion's fake rejects anything that isn't the member's own token, so a
    successful call proves the MCP server forwarded what it was given rather
    than holding a credential of its own.
    """
    async with connect() as client:
        await client.call_tool("get_pantry_items", {})
    assert ("GET", "/pantry") in fake_companion.calls


async def test_token_check_failure_is_a_401_not_a_500(
    raw, fake_companion: FakeCompanion  # noqa: ANN001
) -> None:
    """If Companion is down we cannot verify anyone, and "unauthenticated" is
    the honest answer — not a tool that half-works."""
    fake_companion.down = True
    async with raw(VALID_TOKEN) as http:
        response = await http.post("/mcp", json=MCP_PROBE, headers=MCP_HEADERS)
    assert response.status_code == 401


async def test_a_broken_endpoint_reads_as_a_service_problem(
    connect, fake_companion: FakeCompanion  # noqa: ANN001
) -> None:
    """The model should be told Misen is broken, not invent a reason.

    Note this is *not* the same as Companion being wholly down: the server is
    stateless, so every request re-verifies the token, and a total outage
    surfaces one step earlier as the 401 above.
    """
    fake_companion.fail_paths = {"/pantry"}
    async with connect() as client:
        result = await client.call_tool("get_pantry_items", {}, raise_on_error=False)
    assert result.is_error
    assert "unreachable" in result.content[0].text.lower()


# --- the shape of the surface --------------------------------------------


async def test_no_tool_accepts_a_household_parameter(connect) -> None:  # noqa: ANN001
    """A model that could name a household could name the wrong one."""
    async with connect() as client:
        for tool in await client.list_tools():
            params = set(tool.inputSchema.get("properties", {}))
            assert not {"household", "household_id"} & params, f"{tool.name} takes a household"


async def test_the_absent_tools_stay_absent(connect) -> None:  # noqa: ANN001
    """Destructive and administrative operations belong in the app, where a
    human is looking at a confirmation dialog."""
    async with connect() as client:
        names = {tool.name for tool in await client.list_tools()}
    forbidden = {
        "delete_recipe",
        "delete_pantry_item",
        "delete_shopping_item",
        "add_member",
        "update_household",
        "remove_member",
    }
    assert not names & forbidden


# A distinctive phrase from each tool's description in PRD §6. These are the
# highest-leverage text in the project, so drift between the spec and the
# shipped strings should break the build rather than go unnoticed.
PRD_PHRASES = {
    "search_recipes": "the household's own library is almost always the better answer",
    "get_recipe": "before adding a recipe to the menu",
    "get_pantry_items": "Items expiring within three days should influence what you suggest first",
    "add_pantry_item": "when the user says they bought something",
    "update_pantry_item": "this takes an id, not a name",
    "get_weekly_menu": "so you don't overwrite a decided night",
    "set_weekly_menu": "not every night needs a recipe",
    "clear_menu_slot": "never as a step in replacing one",
    "get_shopping_list": "the right input for an Instacart order",
    "add_to_shopping_list": "when the user says they need something",
    "check_shopping_item": "when the user says they picked something up",
    "build_shopping_list": "pantry matching is approximate",
    "get_household": "when you need to know who's in the house",
}


async def test_descriptions_still_match_the_prd(connect) -> None:  # noqa: ANN001
    """Vague descriptions are the main reason models misuse tools, so the
    prescriptive half of each one is load-bearing text, not documentation.

    If this fails because a description was improved, update PRD §6 too — the
    spec and the shipped string are meant to stay one thing.
    """
    async with connect() as client:
        descriptions = {t.name: (t.description or "") for t in await client.list_tools()}

    for name, phrase in PRD_PHRASES.items():
        collapsed = " ".join(descriptions[name].split())
        assert phrase in collapsed, f"{name} no longer matches the PRD: {phrase!r}"


async def test_the_thirteen_tools_are_the_thirteen_in_the_prd(connect) -> None:  # noqa: ANN001
    async with connect() as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {
        "search_recipes",
        "get_recipe",
        "get_pantry_items",
        "add_pantry_item",
        "update_pantry_item",
        "get_weekly_menu",
        "set_weekly_menu",
        "clear_menu_slot",
        "get_shopping_list",
        "add_to_shopping_list",
        "check_shopping_item",
        "build_shopping_list",
        "get_household",
    }


async def test_basils_prompt_only_names_tools_that_exist(connect) -> None:  # noqa: ANN001
    """Basil's system prompt lives in the *other* service, and names tools by hand.

    Companion has no way to import this package, so nothing but this assertion
    stands between a renamed tool and a system prompt that instructs the model
    to call something that isn't there. The failure mode is quiet — Claude just
    does something else — so it's worth one cross-directory read.
    """
    prompt_source = (
        Path(__file__).resolve().parents[2] / "companion" / "app" / "basil.py"
    ).read_text()
    # Tools are referenced in the prompt as `backticked_names`.
    referenced = {
        name
        for name in re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", prompt_source)
        if name.startswith(("get_", "set_", "add_", "clear_", "build_", "check_", "search_"))
    }

    async with connect() as client:
        available = {tool.name for tool in await client.list_tools()}

    assert referenced, "no tool names found in the prompt — did the format change?"
    assert referenced <= available, (
        f"Basil's prompt names tools the MCP server doesn't have: "
        f"{sorted(referenced - available)}"
    )
