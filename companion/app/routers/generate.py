"""Basil — the chat proxy (PRD §7).

Three endpoints: one that streams a turn, two that read the transcript back.

**Why the API key lives here.** An Anthropic key shipped in an app binary is
extractable from a TestFlight build in about a minute, and it bills to us
without limit. It never leaves the server; the app authenticates with its own
member token like it does everywhere else.

**Why the MCP token is the caller's own.** `mcp_servers[].authorization_token`
is sent to Anthropic, whose servers then call our MCP server with it. Using the
caller's Misen token means the tools can reach exactly what the caller could
reach — Nick's conversation cannot write to a household Nick can't write to,
because the credential itself is scoped. There is no second secret to rotate.

**The tool loop is not ours.** With the MCP connector, Anthropic calls the
tools; we never see a `tool_use` we have to answer. What we *do* have to handle
is `pause_turn`: the server-side loop stops after ten tool calls and hands the
turn back unfinished. Planning a week is fourteen menu writes plus a shopping
build, so this is not an edge case — it is the normal path, and a proxy that
ignores it stops halfway through Thursday.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

import anthropic
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anthropic_client import get_anthropic
from app.auth import DbSession, Principal, bearer_token, require_basil
from app.basil import (
    context_block,
    mcp_servers,
    new_conversation_id,
    system_blocks,
    toolsets,
    trim_history,
    user_content,
)
from app.config import get_settings
from app.db import SessionLocal
from app.errors import ApiError, NotFound
from app.models import ChatMessage, ChatUsage, Member
from app.weeks import current_week_start, day_start_utc, today_in

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["basil"])

# How many times a single turn may be resumed after `pause_turn`. Each
# continuation buys another ten tool calls. Planning a full week from scratch
# lands around fourteen; six is headroom without being an infinite loop, which
# is the failure mode that would quietly cost real money.
MAX_CONTINUATIONS = 6

BasilPrincipal = Annotated[Principal, Depends(require_basil)]


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]
    # Absent starts a new thread. The id comes back on the `start` event so the
    # client can send it with the next turn.
    conversation_id: str | None = Field(default=None, max_length=64)

    @field_validator("message")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("say something to Basil")
        return cleaned


class BasilUnconfigured(ApiError):
    """503, not 500. The operator hasn't finished setting Basil up, and the
    person holding the phone can't do anything about it — so say that, rather
    than implying they did something wrong."""

    def __init__(self, message: str) -> None:
        super().__init__(503, "basil_unconfigured", message)


class DailyCapReached(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(429, "daily_cap_reached", message)


# --- SSE -------------------------------------------------------------------


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


# --- transcript ------------------------------------------------------------


def _blocks(message: ChatMessage) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(message.content)
    except json.JSONDecodeError:
        # A row we can't parse is a row we can't replay. Dropping it loses a
        # turn; sending it loses the whole conversation to a 400.
        logger.warning("chat message %s is not valid JSON, skipping", message.id)
        return []
    return loaded if isinstance(loaded, list) else []


def _load_history(
    db: Session, household_id: int, member_id: int, conversation_id: str, max_turns: int
) -> list[dict[str, Any]]:
    """Replay the thread as the API's own message list.

    Scoped by member *and* household. Two members of one house have separate
    threads over shared data (PRD §7) — Nick planning Tuesday shows on Mara's
    Menu tab without her seeing the conversation that produced it.
    """
    rows = db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.household_id == household_id,
            ChatMessage.member_id == member_id,
            ChatMessage.conversation_id == conversation_id,
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
    ).scalars().all()

    messages = [{"role": row.role, "content": _blocks(row)} for row in rows]
    return trim_history([m for m in messages if m["content"]], max_turns)


def _messages_today(db: Session, household_id: int, member_id: int, timezone: str) -> int:
    since = day_start_utc(timezone, today_in(timezone))
    return db.execute(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.household_id == household_id,
            ChatMessage.member_id == member_id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= since,
        )
    ).scalar_one()


def _text_of(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        block.get("text", "") for block in blocks if block.get("type") == "text"
    ).strip()


def _tools_of(blocks: list[dict[str, Any]]) -> list[str]:
    return [block["name"] for block in blocks if block.get("type") == "mcp_tool_use"]


# --- the turn --------------------------------------------------------------


async def _run_turn(
    client: anthropic.AsyncAnthropic,
    *,
    request_kwargs: dict[str, Any],
    messages: list[dict[str, Any]],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Stream one logical turn, resuming across `pause_turn`.

    Yields `(event_name, payload)` pairs and finally one `("__result__", ...)`
    carrying the assembled assistant blocks and the accumulated usage. The
    caller decides what to persist, so a turn that dies mid-stream writes
    nothing rather than leaving an orphaned half-message in the transcript.
    """
    assistant_blocks: list[dict[str, Any]] = []
    tool_names: dict[str, str] = {}
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    stop_reason: str | None = None

    for _ in range(MAX_CONTINUATIONS):
        async with client.beta.messages.stream(
            **request_kwargs, messages=messages
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    yield "text", {"text": event.text}
                elif event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "mcp_tool_use":
                        tool_names[block.id] = block.name
                        yield "tool", {"name": block.name, "state": "running"}
                elif event.type == "content_block_stop":
                    block = event.content_block
                    if block.type == "mcp_tool_result":
                        yield "tool", {
                            "name": tool_names.get(block.tool_use_id, "a tool"),
                            "state": "error" if block.is_error else "done",
                        }
            final = await stream.get_final_message()

        usage["input_tokens"] += final.usage.input_tokens
        usage["output_tokens"] += final.usage.output_tokens
        usage["cache_read_tokens"] += final.usage.cache_read_input_tokens or 0
        usage["cache_write_tokens"] += final.usage.cache_creation_input_tokens or 0
        assistant_blocks.extend(block.model_dump(mode="json") for block in final.content)
        stop_reason = final.stop_reason

        if stop_reason != "pause_turn":
            break

        # Resume by handing the assistant's work back. The docs show replacing
        # the message list with a single assistant message; we *accumulate*
        # into one instead, because on a second pause the replacement would
        # drop the first continuation's tool calls, and appending a second
        # assistant message would break the alternating-role rule. One growing
        # assistant turn satisfies both.
        messages = _with_assistant(messages, assistant_blocks)
    else:
        # Ran out of continuations. Everything so far is real and worth
        # keeping; the user is told the turn was cut short rather than being
        # left to wonder why Friday is empty.
        logger.warning("basil hit the continuation ceiling with stop_reason=%s", stop_reason)
        yield "text", {
            "text": "\n\n(I ran long and stopped partway — ask me to carry on.)"
        }

    yield "__result__", {
        "blocks": assistant_blocks,
        "usage": usage,
        "stop_reason": stop_reason or "end_turn",
    }


def _with_assistant(
    messages: list[dict[str, Any]], assistant_blocks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """History + user turn + the single accumulating assistant turn.

    The block list is copied, not aliased. `assistant_blocks` keeps growing
    after this returns, and a request holding a live reference to it would
    describe a different conversation depending on when you looked at it.
    """
    base = messages[:-1] if messages and messages[-1]["role"] == "assistant" else messages
    return [*base, {"role": "assistant", "content": list(assistant_blocks)}]


# --- routes ----------------------------------------------------------------


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    principal: BasilPrincipal,
    db: DbSession,
    client: Annotated[anthropic.AsyncAnthropic, Depends(get_anthropic)],
) -> StreamingResponse:
    """One turn with Basil, streamed as SSE.

    The event protocol, which the app depends on:

        event: start   {"conversation_id": "..."}
        event: text    {"text": "..."}            — append to the bubble
        event: tool    {"name": "...", "state": "running"|"done"|"error"}
        event: done    {"conversation_id","stop_reason","usage":{...}}
        event: error   {"code","message"}         — show it, stop the spinner

    Exactly one terminal event arrives, `done` or `error`. Tool *names* go over
    the wire, not phrases: turning `get_pantry_items` into "Checking the
    pantry" is presentation, and the app already owns presentation.

    Failures that can be known before the first byte — no API key, capability
    off, daily cap — are real HTTP status codes. Everything after that has to
    be an `error` event, because the status line is long gone.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise BasilUnconfigured("Basil isn't switched on yet — the server has no API key.")
    if not settings.mcp_url:
        raise BasilUnconfigured("Basil isn't switched on yet — the tool server isn't configured.")

    household = principal.household
    used_today = _messages_today(db, household.id, principal.member_id, household.timezone)
    if used_today >= settings.daily_message_cap:
        raise DailyCapReached(
            f"That's {settings.daily_message_cap} messages to Basil today — "
            "back tomorrow. The menu and the list still work."
        )

    conversation_id = body.conversation_id or new_conversation_id()
    today = today_in(household.timezone)
    week_start = current_week_start(household.timezone, household.week_starts_on)
    members = db.execute(
        select(Member).where(Member.household_id == household.id).order_by(Member.id)
    ).scalars().all()

    context = context_block(household, principal.member, list(members), today, week_start)
    history = _load_history(
        db, household.id, principal.member_id, conversation_id, settings.chat_history_turns
    )

    request_kwargs: dict[str, Any] = {
        "model": settings.chat_model,
        "max_tokens": settings.chat_max_tokens,
        "betas": ["mcp-client-2025-11-20"],
        "system": system_blocks(settings),
        "mcp_servers": mcp_servers(settings, bearer_token(request)),
        "tools": toolsets(settings),
    }
    turn = [*history, {"role": "user", "content": user_content(context, body.message)}]

    # Everything the generator needs, captured now. The request-scoped session
    # is closed before a StreamingResponse starts producing bytes (FastAPI
    # exits `yield` dependencies first), so the stream opens its own.
    household_id = household.id
    member_id = principal.member_id
    model = settings.chat_model

    async def stream() -> AsyncIterator[str]:
        yield _sse("start", {"conversation_id": conversation_id})

        result: dict[str, Any] | None = None
        try:
            async for name, payload in _run_turn(
                client, request_kwargs=request_kwargs, messages=turn
            ):
                if name == "__result__":
                    result = payload
                else:
                    yield _sse(name, payload)
        except anthropic.APIStatusError as exc:
            logger.warning("anthropic returned %s: %s", exc.status_code, exc)
            yield _sse("error", {"code": "basil_failed", "message": _friendly(exc)})
            return
        except anthropic.APIError as exc:
            logger.warning("anthropic request failed: %s", exc)
            yield _sse(
                "error",
                {"code": "basil_unreachable", "message": "I couldn't reach Basil just then."},
            )
            return
        except Exception:
            logger.exception("basil turn failed")
            yield _sse(
                "error",
                {"code": "internal_error", "message": "Something went wrong on our end."},
            )
            return

        if result is None:  # pragma: no cover — _run_turn always finishes with one
            yield _sse("error", {"code": "internal_error", "message": "Basil said nothing."})
            return

        # Both messages land together or neither does. A user message with no
        # reply would leave the thread ending on a user turn, and the next
        # request would send two user messages in a row — which the API
        # rejects, turning one failed turn into a permanently broken thread.
        with SessionLocal() as session:
            session.add(
                ChatMessage(
                    household_id=household_id,
                    conversation_id=conversation_id,
                    member_id=member_id,
                    role="user",
                    content=json.dumps([{"type": "text", "text": body.message}]),
                )
            )
            session.add(
                ChatMessage(
                    household_id=household_id,
                    conversation_id=conversation_id,
                    member_id=member_id,
                    role="assistant",
                    content=json.dumps(result["blocks"]),
                )
            )
            session.add(
                ChatUsage(
                    household_id=household_id,
                    conversation_id=conversation_id,
                    member_id=member_id,
                    model=model,
                    **result["usage"],
                )
            )
            session.commit()

        yield _sse(
            "done",
            {
                "conversation_id": conversation_id,
                "stop_reason": result["stop_reason"],
                "usage": result["usage"],
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Belt and braces alongside Caddy's `flush_interval -1`. Any proxy
            # that buffers this response turns a live conversation into a wall
            # of text arriving at once.
            "X-Accel-Buffering": "no",
        },
    )


def _friendly(exc: anthropic.APIStatusError) -> str:
    if exc.status_code == 429:
        return "Basil is busy right now — try again in a moment."
    if exc.status_code in (401, 403):
        # Our key, not their token. Never phrase this as the user's problem.
        return "Basil isn't configured correctly. Nothing you did."
    if exc.status_code >= 500:
        return "Basil is having trouble right now — try again in a moment."
    return "Basil couldn't handle that one."


@router.get("/conversations")
def conversations(principal: BasilPrincipal, db: DbSession) -> list[dict[str, Any]]:
    """This member's threads, newest first, with enough to draw a list row."""
    rows = db.execute(
        select(
            ChatMessage.conversation_id,
            func.min(ChatMessage.created_at).label("started_at"),
            func.max(ChatMessage.created_at).label("last_at"),
            func.count().label("messages"),
        )
        .where(
            ChatMessage.household_id == principal.household_id,
            ChatMessage.member_id == principal.member_id,
        )
        .group_by(ChatMessage.conversation_id)
        .order_by(func.max(ChatMessage.created_at).desc())
    ).all()

    out = []
    for row in rows:
        first = db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.household_id == principal.household_id,
                ChatMessage.member_id == principal.member_id,
                ChatMessage.conversation_id == row.conversation_id,
                ChatMessage.role == "user",
            )
            .order_by(ChatMessage.created_at, ChatMessage.id)
            .limit(1)
        ).scalar_one_or_none()
        out.append(
            {
                "conversation_id": row.conversation_id,
                "started_at": row.started_at,
                "last_message_at": row.last_at,
                "messages": row.messages,
                "preview": _text_of(_blocks(first))[:120] if first else "",
            }
        )
    return out


@router.get("/conversations/{conversation_id}")
def conversation(
    conversation_id: str, principal: BasilPrincipal, db: DbSession
) -> dict[str, Any]:
    """One thread, rendered for display rather than for replay.

    Text and the tool names, not the raw content blocks. The blocks exist so
    *we* can replay the conversation to the model; a phone drawing chat bubbles
    has no use for a tool result's JSON, and shipping it would put the pantry
    over the wire a second time for every message ever sent.
    """
    rows = db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.household_id == principal.household_id,
            ChatMessage.member_id == principal.member_id,
            ChatMessage.conversation_id == conversation_id,
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
    ).scalars().all()

    if not rows:
        raise NotFound("That conversation doesn't exist.")

    messages = []
    for row in rows:
        blocks = _blocks(row)
        entry: dict[str, Any] = {
            "role": row.role,
            "text": _text_of(blocks),
            "created_at": row.created_at,
        }
        tools = _tools_of(blocks)
        if tools:
            entry["tools"] = tools
        messages.append(entry)

    return {"conversation_id": conversation_id, "messages": messages}
