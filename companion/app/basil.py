"""Who Basil is, and what gets sent to the model.

Everything in this file is pure: prompt text, request assembly, history
trimming. The streaming, the database writes, and the usage accounting live in
`routers/generate.py`. Splitting them means the interesting decisions — what
Basil is told, how much history it sees, which tools it gets — can be asserted
directly without a fake API in the way.

**The system prompt is static, deliberately.** No date, no member name, no
household. It carries a `cache_control` breakpoint, and the cached prefix is
matched by exact bytes: interpolating today's date would invalidate the cache
on the first request of every day, and interpolating the member's name would
give Nick and Mara separate caches of the same text. Volatile context rides
along with the current user message instead (`context_block`), which costs a
few hundred uncached tokens per turn and saves the whole prefix.
"""

from __future__ import annotations

import secrets
from datetime import date
from typing import Any

from app.config import Settings
from app.models import Household, Member

SERVER_NAME = "misen"
INSTACART_SERVER_NAME = "instacart"

SYSTEM_PROMPT = """\
You are Basil, the meal-planning helper inside Misen — a private app for one \
household's kitchen. You have tools that read and write that household's real \
pantry, weekly menu, recipe library, and shopping list.

## Voice

Warm, brief, practical. You are someone who cooks, not a nutritionist and not \
a chatbot. Answer in a sentence or two unless asked for more. This renders in \
chat bubbles on a phone, so long answers are wrong answers: no preamble, no \
restating the question, no bulleted list where a sentence works.

## What you plan

Dinners. Misen has one meal slot a night and that is on purpose. Monday to \
Thursday are time-pressured and should lean fast; a weekend can take a project.

## Look before you plan

Use the tools. Do not guess, and do not ask the user for something a tool \
would tell you.

- `get_weekly_menu` **first**, always, before planning anything. It returns \
this week and next. A night that already has a meal is a decision somebody \
made — leave it alone.
- `get_pantry_items` before suggesting anything. Lead with what is expiring: \
if something is within about three days, let it shape the suggestion and say \
why — "the salmon wants using by Thursday".
- `search_recipes` before inventing. The household's own library is the point \
of the app. If you suggest something that isn't in it, say plainly that it's a \
new idea rather than a saved recipe.
- `get_recipe` when you need ingredients or timing. Pass `servings` and the \
quantities come back already scaled. If the result carries `scaling_notes`, \
pass that caveat on instead of quietly rounding it away.

## Writing is real

The menu is shared. What you plan here appears on everyone's Menu tab within \
seconds, under their name.

- Confirm before overwriting a night that already has a meal. "Tuesday has \
salmon — replace it?" is one short question, not a paragraph.
- Never clear a night unless you were asked to.
- Never mark a pantry item used unless the user said they used it. Planning a \
recipe is not evidence that anything was eaten.
- After a week is planned, *offer* to build the shopping list. Don't build it \
unasked.

## Freeform nights are real options

Not every night needs a recipe. `set_weekly_menu` takes a plain title — \
"Leftovers", "Takeout", "Nachos" — and a week of seven ambitious recipes is a \
week that doesn't actually happen. When a week is looking overloaded, say so \
and offer one.

## The shopping list

`build_shopping_list` diffs the week's planned recipes against the pantry. It \
matches ingredient names loosely on purpose, so it will sometimes skip \
something that is really needed — "scallions" and "green onions" don't match. \
When it reports what it skipped, name those items so the user can check them. \
Freeform nights contribute no ingredients; ask what's needed for those.

## When something goes wrong

If a tool fails, say in plain words what didn't work and what still did — \
"the recipe library isn't answering, but I've got the pantry". Don't retry \
silently more than once, and don't paper over a failure with a guess.\
"""

INSTACART_PROMPT = """\

## Ordering

Once a week is planned and the list is built, you can offer to put the missing \
items into an Instacart order. Get the items with `get_shopping_list` using \
`unchecked_only=true` — those are exactly the things still needed — then use \
the Instacart tools to create the order for the user to review.

Show what you are about to cart and get a clear yes before creating it. A plan \
is not approval to spend money. After it exists, hand over the link and stop; \
the user does the checkout.\
"""


def new_conversation_id() -> str:
    """Short, unguessable, and not a database id.

    Conversation ids appear in URLs (`/generate/conversations/{id}`). They are
    still authorized against the caller's member and household on every read —
    this is not a secret — but a sequential integer would invite guessing at
    a boundary that has no reason to be guessable.
    """
    return secrets.token_urlsafe(9)


def system_blocks(settings: Settings) -> list[dict[str, Any]]:
    """The system prompt, with the cache breakpoint on the last block.

    Tools are sent before the system prompt in the cached prefix, so one
    breakpoint here covers the toolset definitions as well — and those are the
    expensive part, since Anthropic expands the MCP toolset into thirteen full
    tool schemas on every request.
    """
    text = SYSTEM_PROMPT
    if instacart_configured(settings):
        text += INSTACART_PROMPT
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def instacart_configured(settings: Settings) -> bool:
    return bool(settings.instacart_mcp_url and settings.instacart_api_key)


def mcp_servers(settings: Settings, member_token: str) -> list[dict[str, Any]]:
    """The servers Anthropic will connect to on our behalf.

    `authorization_token` is the caller's *own* Misen token. The MCP server
    verifies it against `/me` and can therefore reach exactly what its caller
    could reach — no household parameter, no second credential, no way for one
    member's conversation to act as another.
    """
    servers: list[dict[str, Any]] = [
        {
            "type": "url",
            "name": SERVER_NAME,
            "url": settings.mcp_url,
            "authorization_token": member_token,
        }
    ]
    if instacart_configured(settings):
        servers.append(
            {
                "type": "url",
                "name": INSTACART_SERVER_NAME,
                "url": settings.instacart_mcp_url,
                "authorization_token": settings.instacart_api_key,
            }
        )
    return servers


def toolsets(settings: Settings) -> list[dict[str, Any]]:
    """One toolset per declared server — the API rejects any other count.

    Every server in `mcp_servers` must be referenced by exactly one
    `mcp_toolset` in `tools`. Both halves are built from the same condition so
    they cannot drift apart into a 400.
    """
    sets: list[dict[str, Any]] = [{"type": "mcp_toolset", "mcp_server_name": SERVER_NAME}]
    if instacart_configured(settings):
        sets.append({"type": "mcp_toolset", "mcp_server_name": INSTACART_SERVER_NAME})
    return sets


def context_block(
    household: Household,
    member: Member,
    members: list[Member],
    today: date,
    week_start: date,
) -> str:
    """The volatile facts, rebuilt every turn and prepended to the user's message.

    Member ids are listed because `set_weekly_menu` takes `cooked_by` as an id
    and the menu comes back carrying ids. Handing them over here costs one line
    and saves a `get_household` call on most conversations.
    """
    others = ", ".join(f"{m.name} ({m.role}, id {m.id})" for m in members if m.id != member.id)
    lines = [
        f"Today is {today.strftime('%A, %-d %B %Y')}.",
        f"This is the {household.name} household, timezone {household.timezone}.",
        f"Weeks start on {household.week_starts_on}; this week began {week_start.isoformat()}.",
        f"You are talking to {member.name} (id {member.id}).",
    ]
    if others:
        lines.append(f"Also in the household: {others}.")
    return "\n".join(lines)


def user_content(context: str, text: str) -> list[dict[str, Any]]:
    """The current turn: fresh context, then what the person actually typed.

    Two blocks rather than one string so the stored transcript can keep only
    the second. Replaying yesterday's context banner would tell the model the
    wrong date with the same confidence as the right one.
    """
    return [
        {"type": "text", "text": f"<context>\n{context}\n</context>"},
        {"type": "text", "text": text},
    ]


def trim_history(messages: list[dict[str, Any]], max_turns: int) -> list[dict[str, Any]]:
    """Keep the most recent `max_turns` messages, starting from a user turn.

    Two rules the API enforces and this has to respect: a conversation begins
    with a user message, and roles alternate. Slicing a long history can land
    on an assistant message, so the leading orphan is dropped rather than sent.
    """
    trimmed = messages[-max_turns:] if max_turns > 0 else []
    while trimmed and trimmed[0].get("role") != "user":
        trimmed = trimmed[1:]
    return trimmed
