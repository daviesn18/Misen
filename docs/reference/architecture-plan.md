# Meal Planning App — Architecture & Build Plan

## 1. Why the architecture isn't "just Mealie"

Mealie is excellent at recipes (scraping, OCR import, video import), shopping lists, and multi-user households. It deliberately does **not** do pantry/fridge inventory tracking — the maintainers have said outright that keeping a digital pantry in sync with a real one is a losing battle for a general-purpose tool, so they don't try.

That means your five sections split across two data sources:

| Section | Backed by |
|---|---|
| Recipes | **Mealie** (existing API, scraper, OCR, video import) |
| Shopping List | **Mealie** (existing API) |
| Pantry / Fridge Items | **Custom companion API** (new, small) |
| Weekly Menu | **Custom companion API** (new, small — this is *your* concept, not Mealie's) |
| Generate a Recipe | **Claude Project**, reading/writing both of the above via MCP |

This isn't more infrastructure than "just Mealie" would have been — it's roughly the same VPS, one extra lightweight service sitting next to Mealie's container. Given your Postman/FastAPI comfort, this is a Saturday, not a redesign.

## 2. Components

```
┌─────────────────────────────┐
│   SwiftUI App (iOS/iPadOS)  │  ← your new native build
│  Recipes | Weekly Menu |    │
│  Pantry | Shopping | Gen    │
└──────────┬─────────┬────────┘
           │         │
     Mealie API   Companion API (FastAPI)
           │         │
     ┌─────▼───┐ ┌───▼──────┐
     │ Mealie  │ │ Postgres │  ← pantry_items, weekly_menu,
     │(SQLite) │ │ /SQLite  │    generation_sessions
     └────┬────┘ └────┬─────┘
          │            │
          └─────┬──────┘
                │
         MCP Server (FastMCP, HTTP)
                │
   ┌────────────▼────────────┐
   │   Claude Project          │
   │  "Meal Planning"          │
   │  + Instacart connector    │
   └────────────────────────────┘
```

All four backend pieces (Mealie, Companion API, Postgres, MCP server) live on the same VPS behind one reverse proxy with HTTPS. The MCP server is the only thing Claude talks to — it internally calls both Mealie's API and your Companion API, so from Claude's perspective there's just one set of tools.

## 3. Companion API — data model (new, custom)

```sql
CREATE TABLE pantry_items (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    quantity TEXT,
    unit TEXT,
    location TEXT,          -- 'pantry' | 'fridge' | 'freezer'
    added_date TIMESTAMP DEFAULT now(),
    expiry_date DATE
);

CREATE TABLE weekly_menu (
    id SERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    day_of_week TEXT NOT NULL,      -- 'monday'...'sunday'
    meal_slot TEXT DEFAULT 'dinner',
    mealie_recipe_id TEXT,          -- FK reference into Mealie, not a local copy
    notes TEXT
);

CREATE TABLE generation_sessions (
    id SERIAL PRIMARY KEY,
    created_date TIMESTAMP DEFAULT now(),
    week_start DATE,
    summary TEXT,                   -- what Claude decided and why
    instacart_order_placed BOOLEAN DEFAULT false
);
```

Keep `weekly_menu` referencing Mealie recipe IDs rather than duplicating recipe content — Mealie stays the single source of truth for what a recipe actually is.

## 4. Recipe import & entry plan

**One-time migration from Recipe Keeper:**
1. Export from Recipe Keeper: Settings → Import/Export → Export to Recipe Keeper `.zip`.
2. Write a Python script (one-off, not part of the app) that unzips it, parses each recipe's HTML, and POSTs it to Mealie's `/api/recipes` create endpoint (or uses Mealie's "paste HTML/JSON" import path under the hood). This is a scripting task, not a service — run it once, verify counts, done.

**Ongoing recipe entry (inside your new app), all backed by Mealie's *existing* import features — you're not building parsers:**
- **From URL** → Mealie's built-in scraper endpoint, supports hundreds of recipe sites.
- **From PDF/photo** → Mealie's OCR/AI image import endpoint.
- **Manual entry** → straightforward POST with title/ingredients/steps to Mealie's create endpoint.

Your SwiftUI "Add Recipe" screen is just three thin forms hitting three Mealie endpoints. No custom parsing logic needed anywhere in this flow.

## 5. MCP tool surface (what Claude can call)

Recipes & shopping (proxy straight to Mealie):
- `search_recipes(query, tags?)`
- `get_recipe(id)`
- `get_shopping_list()`
- `add_to_shopping_list(items[])`

Pantry & menu (hit the Companion API):
- `get_pantry_items()`
- `update_pantry_item(name, quantity, unit, location)`
- `get_weekly_menu(week_start)`
- `set_weekly_menu(week_start, day, recipe_id)`
- `log_generation_session(week_start, summary)`

Keep descriptions specific about *when* to use each tool (e.g. "call this when the user says they bought groceries or used something up") — vague descriptions are the #1 reason models misuse or ignore tools.

## 6. Instacart — you may not need to build anything

You already have an Instacart connector available to Claude (search + cart tools). Rather than building any ordering logic yourself, the Claude Project can:
1. Read `get_pantry_items()` + the recipes on the weekly menu.
2. Diff ingredients needed vs. pantry on hand.
3. Use the Instacart connector directly to search for and cart the missing items.

This means the "order what I don't have" step is a prompting/orchestration problem inside the Claude Project, not an engineering problem — no Instacart API integration for you to write.

## 7. End-to-end flow (matches what you described)

1. You (or your wife) tell the Claude Project: *"plan my recipes for the week."*
2. Claude calls `search_recipes()` / `get_pantry_items()` via MCP, reasons about what to cook.
3. Claude calls `set_weekly_menu()` for each day — this immediately shows up in the app's Weekly Menu tab, since the app reads live from the same Companion API.
4. Claude diffs the week's required ingredients against pantry, then uses the Instacart connector to cart what's missing.
5. You review/approve the Instacart cart (per Claude's standing rule: it confirms before placing paid orders).
6. As you cook through the week, you update Pantry in the app (or just tell Claude "we used the chicken," which calls `update_pantry_item`).

## 8. Suggested build phases

1. **Infra**: Mealie + Postgres + Companion API skeleton + MCP server, all on one VPS, HTTPS via reverse proxy.
2. **Migration**: Recipe Keeper → Mealie import script; verify your full recipe library made it over cleanly.
3. **MCP tools**: build and test the tool list above against Claude Desktop locally before wiring the app.
4. **SwiftUI app**: five sections, Recipes/Shopping hitting Mealie, Pantry/Weekly Menu hitting Companion API — this is where Claude Design + Claude Code come in.
5. **Claude Project**: system prompt/instructions for meal planning behavior, MCP server connected, Instacart connector connected.
6. **Dry run**: one full week end-to-end before trusting it unsupervised.

## 9. Open decisions before build starts

- VPS provider/spec (a $6/mo box is plenty to start).
- Postgres vs. SQLite for the Companion API (SQLite is fine at household scale, simpler ops).
- ~~Whether "Generate a Recipe" lives inside the app or is just "open the Claude app"~~ — **decided: embedded chat**, see below.

## 10. Embedded AI chat — implementation notes

Since this is family-only, light-usage, and explicitly a place to practice building on the API, "Generate a Recipe" becomes a real chat interface inside the app, not a hand-off to Claude.ai.

**Don't call the Anthropic API directly from the SwiftUI client.** An API key shipped inside an app binary can be extracted, even from a TestFlight build only your family uses — it's just bad practice to have a raw key living in client code. Instead, the Companion API (which already exists for pantry/menu) gets one more job: it holds the API key server-side and proxies chat requests.

```
SwiftUI app  →  POST /generate/chat  →  Companion API  →  Anthropic Messages API
                (your own auth)          (holds API key)    (with mcp_servers param
                                                              pointing at your MCP
                                                              server, so Claude can
                                                              read pantry/recipes and
                                                              write the weekly menu
                                                              mid-conversation)
```

This also means the embedded chat and the "ask Claude Project from claude.ai" path can share the exact same MCP server — same tools, same recipe/pantry access, just two different front doors.

**New pieces needed:**

- **Companion API — `/generate/chat` endpoint**: accepts a message + conversation id, calls `POST https://api.anthropic.com/v1/messages` with `mcp_servers` set to your MCP server's URL, returns the response (stream it if you want the "typing" feel in the app — SSE over the same connection).
- **New table — `chat_messages`**: `id, conversation_id, user_id, role, content, created_at`. Conversations are scoped per household member (you and your wife each have your own thread history, not a shared one) — `user_id` is what keeps them separate. Lets a conversation persist if the app is closed mid-planning, and gives you a simple history view for free.
- **Auth between app and Companion API**: a distinct token per household member, both for separating conversations correctly and so you don't leave the endpoint open to the internet with zero auth — it spends real API credits per request.
- **Shared context, separate threads**: even though your and your wife's chats are separate, both hit the same pantry/recipe/weekly-menu data via MCP — so if she plans Tuesday's dinner in her thread, you'll see it on the shared Weekly Menu tab even though you can't see her conversation that produced it.
- **Model choice**: for a lightweight, mostly-tool-calling assistant like this, Claude Haiku 4.5 is worth starting with — cheap, fast, and meal planning + tool orchestration doesn't need frontier reasoning. Easy to swap the model string later if you want more nuance in the "what can I make tonight" conversations.
- **SwiftUI side**: a fairly standard chat view (message list + input bar) — this is the one screen where you're genuinely building new UI/UX rather than a thin CRUD form, so it's a reasonable place to spend your Claude Design time.
