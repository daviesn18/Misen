"""Basil — the chat proxy (PRD §7).

Nothing here contacts Anthropic. `FakeAnthropic` scripts the responses out of
the SDK's own event classes, which means the assertions are about the two
things that can actually go wrong in a proxy: what we *send* (the connector
shape, the history, the tools) and what we *keep* (the transcript, the usage,
the household boundary).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.basil import SYSTEM_PROMPT, trim_history
from app.models import ChatMessage, ChatUsage, utcnow
from tests.conftest import FakeAnthropic, turn


def sse(response: Any) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body into (event, data) pairs."""
    parsed: list[tuple[str, dict[str, Any]]] = []
    for chunk in response.text.split("\n\n"):
        if not chunk.strip():
            continue
        name: str | None = None
        data: dict[str, Any] = {}
        for line in chunk.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        assert name is not None, f"SSE chunk with no event name: {chunk!r}"
        parsed.append((name, data))
    return parsed


def say(client: TestClient, headers: dict[str, str], message: str, conversation: str | None = None):  # noqa: ANN201, E501
    body: dict[str, Any] = {"message": message}
    if conversation:
        body["conversation_id"] = conversation
    return client.post("/generate/chat", json=body, headers=headers)


def texts(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(data["text"] for name, data in events if name == "text")


def names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


# --- the happy path --------------------------------------------------------


def test_a_turn_streams_text_and_terminates_once(client: TestClient, nick: dict[str, str]) -> None:
    events = sse(say(client, nick, "what's for dinner?"))

    assert names(events)[0] == "start"
    assert names(events)[-1] == "done"
    assert texts(events) == "Sure."
    # Exactly one terminal event. A client that has to guess whether more is
    # coming shows a spinner forever.
    assert names(events).count("done") + names(events).count("error") == 1


def test_the_conversation_id_comes_back_on_the_first_event(
    client: TestClient, nick: dict[str, str]
) -> None:
    events = sse(say(client, nick, "hello"))
    started = dict(events)["start"]
    assert started["conversation_id"]
    assert dict(events)["done"]["conversation_id"] == started["conversation_id"]


def test_tool_calls_surface_as_running_then_done(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    basil.script = [turn("Planned it.", tools=["get_weekly_menu", "set_weekly_menu"])]
    events = sse(say(client, nick, "plan tuesday"))

    tools = [data for name, data in events if name == "tool"]
    assert tools == [
        {"name": "get_weekly_menu", "state": "running"},
        {"name": "get_weekly_menu", "state": "done"},
        {"name": "set_weekly_menu", "state": "running"},
        {"name": "set_weekly_menu", "state": "done"},
    ]


def test_a_failed_tool_says_so(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    basil.script = [turn("That didn't work.", tools=["get_recipe"], tool_error=True)]
    events = sse(say(client, nick, "scale it"))
    assert {"name": "get_recipe", "state": "error"} in [d for n, d in events if n == "tool"]


# --- the request we actually send -----------------------------------------


def test_the_connector_call_has_all_three_required_pieces(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """Beta flag, server declaration, and a toolset referencing it by name.

    Any one of these missing is a 400 from the API, and the failure looks
    nothing like its cause — which is exactly why it's asserted here rather
    than discovered on a phone.
    """
    say(client, nick, "hi")
    sent = basil.last

    assert sent["betas"] == ["mcp-client-2025-11-20"]
    assert sent["mcp_servers"][0]["type"] == "url"
    assert sent["mcp_servers"][0]["name"] == "misen"
    assert sent["tools"] == [{"type": "mcp_toolset", "mcp_server_name": "misen"}]
    assert sent["mcp_servers"][0]["name"] == sent["tools"][0]["mcp_server_name"]


def test_every_declared_server_has_exactly_one_toolset(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic, settings: Any
) -> None:
    settings.instacart_mcp_url = "https://mcp.instacart.test/mcp"
    settings.instacart_api_key = "instacart-key"

    say(client, nick, "order the missing stuff")
    sent = basil.last

    declared = [server["name"] for server in sent["mcp_servers"]]
    referenced = [toolset["mcp_server_name"] for toolset in sent["tools"]]
    assert sorted(declared) == sorted(referenced) == ["instacart", "misen"]


def test_instacart_is_absent_from_the_prompt_when_it_is_not_configured(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """Basil must not offer to order groceries it has no way to order."""
    say(client, nick, "hi")
    system = basil.last["system"][0]["text"]
    assert "Instacart" not in system
    assert len(basil.last["mcp_servers"]) == 1


def test_instacart_appears_in_the_prompt_once_configured(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic, settings: Any
) -> None:
    settings.instacart_mcp_url = "https://mcp.instacart.test/mcp"
    settings.instacart_api_key = "instacart-key"
    say(client, nick, "hi")
    assert "Instacart" in basil.last["system"][0]["text"]


def test_the_members_own_token_is_what_reaches_the_mcp_server(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """The MCP server is called back with the caller's credential, not a shared
    one — which is the whole reason no tool takes a household parameter."""
    say(client, nick, "hi")
    assert basil.last["mcp_servers"][0]["authorization_token"] == nick["Authorization"].split()[1]


def test_the_system_prompt_is_cached_and_carries_no_volatile_text(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    say(client, nick, "hi")
    system = basil.last["system"]

    assert system[-1]["cache_control"] == {"type": "ephemeral"}
    # The two things that would break the cache: today's date and who's asking.
    assert "Nick" not in system[0]["text"]
    assert "Davies" not in system[0]["text"]
    assert system[0]["text"].startswith(SYSTEM_PROMPT[:40])


def test_volatile_context_rides_with_the_user_message(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    say(client, nick, "what's for dinner?")
    content = basil.last["messages"][-1]["content"]

    assert content[1]["text"] == "what's for dinner?"
    context = content[0]["text"]
    assert "Davies" in context
    assert "You are talking to Nick" in context
    # Member ids, so planning "Mara cooks Thursday" doesn't need a lookup.
    assert "Mara" in context and "id " in context


# --- pause_turn ------------------------------------------------------------


def test_a_paused_turn_is_resumed_and_reads_as_one_reply(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """The normal path for "plan my week", not an edge case.

    Anthropic's server-side loop stops after ten tool calls and hands back
    `pause_turn`. A proxy that treats that as the end of the turn stops
    somewhere around Thursday and reports success.
    """
    basil.script = [
        turn("Working on it. ", tools=["get_weekly_menu"], stop_reason="pause_turn"),
        turn("All seven nights are planned.", tools=["build_shopping_list"]),
    ]
    events = sse(say(client, nick, "plan my dinners for the week"))

    assert len(basil.calls) == 2
    assert texts(events) == "Working on it. All seven nights are planned."
    assert names(events).count("done") == 1
    assert dict(events)["done"]["stop_reason"] == "end_turn"


def test_resuming_hands_back_one_growing_assistant_turn(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """Roles must alternate, and no work may be dropped.

    Appending a second assistant message would break the alternation; replacing
    the first would lose the tool calls it already made. Accumulating into one
    assistant turn is the only shape that satisfies both.
    """
    basil.script = [
        turn("One. ", tools=["get_weekly_menu"], stop_reason="pause_turn"),
        turn("Two. ", tools=["get_pantry_items"], stop_reason="pause_turn"),
        turn("Done."),
    ]
    say(client, nick, "plan the week")

    assert len(basil.calls) == 3
    final_messages = basil.calls[-1]["messages"]
    roles = [m["role"] for m in final_messages]
    assert roles == ["user", "assistant"], "roles must alternate"

    carried = [block["type"] for block in final_messages[-1]["content"]]
    assert carried.count("mcp_tool_use") == 2, "both continuations' tool calls survive"
    assert carried.count("text") == 2


def test_the_continuation_ceiling_ends_the_turn_honestly(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    from app.routers.generate import MAX_CONTINUATIONS

    basil.script = [turn("...", stop_reason="pause_turn") for _ in range(MAX_CONTINUATIONS)]
    events = sse(say(client, nick, "plan the next six months"))

    assert len(basil.calls) == MAX_CONTINUATIONS
    assert "stopped partway" in texts(events)
    assert names(events)[-1] == "done"


# --- the transcript --------------------------------------------------------


def test_a_turn_is_persisted_as_a_pair(
    client: TestClient, nick: dict[str, str], db: Session
) -> None:
    events = sse(say(client, nick, "hello"))
    conversation = dict(events)["done"]["conversation_id"]

    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation)
        .order_by(ChatMessage.id)
    ).scalars().all()

    assert [row.role for row in rows] == ["user", "assistant"]
    assert json.loads(rows[0].content) == [{"type": "text", "text": "hello"}]


def test_the_stored_user_message_has_no_context_banner(
    client: TestClient, nick: dict[str, str], db: Session
) -> None:
    """Replaying yesterday's date would state it as confidently as today's."""
    say(client, nick, "hello")
    row = db.execute(
        select(ChatMessage).where(ChatMessage.role == "user")
    ).scalars().one()
    assert "<context>" not in row.content


def test_tool_blocks_survive_into_the_next_turn(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """A transcript that drops tool blocks can't be replayed to the API."""
    basil.script = [turn("Checked.", tools=["get_pantry_items"]), turn("Yes.")]
    first = sse(say(client, nick, "what's in the fridge?"))
    conversation = dict(first)["done"]["conversation_id"]

    say(client, nick, "anything expiring?", conversation)

    replayed = basil.last["messages"]
    assert [m["role"] for m in replayed] == ["user", "assistant", "user"]
    kinds = [block["type"] for block in replayed[1]["content"]]
    assert "mcp_tool_use" in kinds and "mcp_tool_result" in kinds


def test_a_new_turn_without_a_conversation_id_starts_a_fresh_thread(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    basil.script = [turn(), turn()]
    first = dict(sse(say(client, nick, "one")))["done"]["conversation_id"]
    second = dict(sse(say(client, nick, "two")))["done"]["conversation_id"]

    assert first != second
    assert len(basil.last["messages"]) == 1, "a new thread carries no history"


def test_usage_is_logged_once_per_turn_including_the_continuations(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic, db: Session
) -> None:
    basil.script = [
        turn("a", stop_reason="pause_turn", input_tokens=100, output_tokens=10, cache_write=500),
        turn("b", input_tokens=200, output_tokens=30, cache_read=500),
    ]
    say(client, nick, "plan the week")

    rows = db.execute(select(ChatUsage)).scalars().all()
    assert len(rows) == 1, "one row per turn, not per API call"
    assert rows[0].input_tokens == 300
    assert rows[0].output_tokens == 40
    assert rows[0].cache_write_tokens == 500
    assert rows[0].cache_read_tokens == 500
    assert rows[0].model == "claude-opus-5"


# --- history ---------------------------------------------------------------


def test_history_is_replayed_on_the_next_turn(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    basil.script = [turn("Salmon."), turn("Thursday.")]
    conversation = dict(sse(say(client, nick, "what's for dinner?")))["done"]["conversation_id"]
    say(client, nick, "when?", conversation)

    replayed = basil.last["messages"]
    assert len(replayed) == 3
    assert replayed[0]["content"][0]["text"] == "what's for dinner?"
    assert replayed[-1]["content"][-1]["text"] == "when?"


def test_history_is_truncated_and_still_starts_on_a_user_turn(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic, settings: Any
) -> None:
    settings.chat_history_turns = 3
    basil.script = [turn() for _ in range(4)]

    conversation = dict(sse(say(client, nick, "one")))["done"]["conversation_id"]
    for message in ("two", "three", "four"):
        say(client, nick, message, conversation)

    replayed = basil.last["messages"]
    # Three stored messages would slice to [assistant, user, assistant]; the
    # leading orphan is dropped, then the new user turn is appended.
    assert [m["role"] for m in replayed] == ["user", "assistant", "user"]


def test_trim_history_drops_a_leading_assistant() -> None:
    history = [
        {"role": "user", "content": [{"type": "text", "text": "1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "2"}]},
        {"role": "user", "content": [{"type": "text", "text": "3"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "4"}]},
    ]
    assert [m["role"] for m in trim_history(history, 3)] == ["user", "assistant"]
    assert trim_history(history, 0) == []


# --- when it fails ---------------------------------------------------------


def test_a_mid_stream_failure_becomes_an_error_event(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    """The status line is long gone by then, so 200 + an error event it is."""
    import anthropic
    import httpx

    basil.error = anthropic.APIStatusError(
        "overloaded",
        response=httpx.Response(529, request=httpx.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    response = say(client, nick, "hi")

    assert response.status_code == 200
    events = sse(response)
    assert names(events) == ["start", "error"]
    assert events[-1][1]["code"] == "basil_failed"
    assert "try again" in events[-1][1]["message"]


def test_a_failed_turn_writes_nothing(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic, db: Session
) -> None:
    """A user message with no reply would leave the thread ending on a user
    turn, and the *next* request would then send two user messages in a row —
    which the API rejects. One failed turn would break the thread forever."""
    import anthropic
    import httpx

    basil.error = anthropic.APIStatusError(
        "boom",
        response=httpx.Response(500, request=httpx.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    say(client, nick, "hi")

    assert db.execute(select(ChatMessage)).scalars().all() == []
    assert db.execute(select(ChatUsage)).scalars().all() == []


def test_our_own_misconfiguration_is_never_the_users_fault(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    import anthropic
    import httpx

    basil.error = anthropic.APIStatusError(
        "bad key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    message = sse(say(client, nick, "hi"))[-1][1]["message"]
    assert "Nothing you did" in message


def test_no_api_key_is_a_503_before_anything_streams(
    client: TestClient, nick: dict[str, str], settings: Any
) -> None:
    settings.anthropic_api_key = ""
    response = say(client, nick, "hi")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "basil_unconfigured"


def test_no_mcp_url_is_also_a_503(client: TestClient, nick: dict[str, str], settings: Any) -> None:
    settings.mcp_url = ""
    assert say(client, nick, "hi").status_code == 503


# --- gates -----------------------------------------------------------------


def test_a_child_gets_a_friendly_403(client: TestClient, auth: dict[str, dict[str, str]]) -> None:
    response = say(client, auth["Ivy"], "hi")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "basil_not_allowed"


def test_the_daily_cap_refuses_kindly_and_the_rest_still_works(
    client: TestClient, nick: dict[str, str], settings: Any, basil: FakeAnthropic
) -> None:
    settings.daily_message_cap = 2
    basil.script = [turn(), turn()]
    say(client, nick, "one")
    say(client, nick, "two")

    response = say(client, nick, "three")
    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == "daily_cap_reached"
    assert "still work" in body["message"]
    # The cap is Basil's, not the app's.
    assert client.get("/pantry", headers=nick).status_code == 200


def test_the_cap_counts_the_households_day_not_the_servers(
    client: TestClient, nick: dict[str, str], settings: Any, db: Session, households: dict[str, Any]
) -> None:
    """A New York household's day must not end at 8pm because the box is UTC."""
    settings.daily_message_cap = 1
    db.add(
        ChatMessage(
            household_id=households["first"]["id"],
            conversation_id="old",
            member_id=households["first"]["member_ids"]["Nick"],
            role="user",
            content=json.dumps([{"type": "text", "text": "yesterday"}]),
            # Two days back is unambiguously outside today in any timezone.
            created_at=utcnow() - timedelta(days=2),
        )
    )
    db.commit()

    assert say(client, nick, "today's first").status_code == 200


def test_the_cap_is_per_member(
    client: TestClient, auth: dict[str, dict[str, str]], settings: Any, basil: FakeAnthropic
) -> None:
    settings.daily_message_cap = 1
    basil.script = [turn(), turn()]
    assert say(client, auth["Nick"], "mine").status_code == 200
    assert say(client, auth["Nick"], "again").status_code == 429
    assert say(client, auth["Mara"], "hers").status_code == 200


# --- reading it back -------------------------------------------------------


def test_conversations_lists_this_members_threads_with_a_preview(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    basil.script = [turn(), turn()]
    say(client, nick, "what can I make tonight?")
    say(client, nick, "something vegetarian")

    threads = client.get("/generate/conversations", headers=nick).json()
    assert len(threads) == 2
    previews = {thread["preview"] for thread in threads}
    assert previews == {"what can I make tonight?", "something vegetarian"}
    assert all(thread["messages"] == 2 for thread in threads)


def test_one_thread_reads_back_as_text_and_tool_names(
    client: TestClient, nick: dict[str, str], basil: FakeAnthropic
) -> None:
    basil.script = [turn("Salmon, Thursday.", tools=["get_pantry_items"])]
    conversation = dict(sse(say(client, nick, "what's expiring?")))["done"]["conversation_id"]

    body = client.get(f"/generate/conversations/{conversation}", headers=nick).json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["text"] == "Salmon, Thursday."
    assert body["messages"][1]["tools"] == ["get_pantry_items"]
    # The raw blocks stay server-side; a phone drawing bubbles has no use for
    # a tool result's JSON.
    assert "content" not in body["messages"][1]


def test_a_missing_thread_is_a_404(client: TestClient, nick: dict[str, str]) -> None:
    assert client.get("/generate/conversations/nope", headers=nick).status_code == 404


# --- the boundary ----------------------------------------------------------


def test_the_other_household_sees_none_of_it(
    client: TestClient, nick: dict[str, str], sam: dict[str, str]
) -> None:
    conversation = dict(sse(say(client, nick, "secret plans")))["done"]["conversation_id"]

    assert client.get("/generate/conversations", headers=sam).json() == []
    assert client.get(f"/generate/conversations/{conversation}", headers=sam).status_code == 404


def test_housemates_have_separate_threads_over_shared_data(
    client: TestClient, auth: dict[str, dict[str, str]], basil: FakeAnthropic
) -> None:
    """PRD §7: shared state, separate voices. Mara can plan Tuesday in her own
    thread and Nick sees the meal, not the conversation."""
    basil.script = [turn(), turn()]
    conversation = dict(sse(say(client, auth["Mara"], "planning tuesday")))["done"][
        "conversation_id"
    ]

    assert client.get("/generate/conversations", headers=auth["Nick"]).json() == []
    assert (
        client.get(f"/generate/conversations/{conversation}", headers=auth["Nick"]).status_code
        == 404
    )


def test_chat_needs_a_token(client: TestClient) -> None:
    assert client.post("/generate/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/generate/conversations").status_code == 401
