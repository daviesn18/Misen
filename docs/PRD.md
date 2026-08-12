# Misen — Product Requirements

> **Product:** Misen · **Assistant:** Claude, in a Claude Project · *"A warm kitchen, in its place."*
>
> Status: approved for build. Last updated 2026-08-12 (rev 3).
>
> **Rev 3 replaces Basil with a Claude Project.** The in-app chat assistant and
> its Anthropic API proxy are gone; planning happens on claude.ai against the
> same MCP server. Decision 7 records the reasoning.

---

## 1. Problem and product

Two people cook dinner most nights and are bad at deciding what. The recipes live in Recipe Keeper, the pantry lives in someone's head, the shopping list lives on a phone notepad, and the weekly plan doesn't exist — so Tuesday at 6pm is a negotiation, and half the fresh food bought on Sunday gets thrown out on Friday.

Misen puts those four things in one place and exposes all of them to an assistant that can act on them. Four peer sections:

| Section | Job |
|---|---|
| **Menu** | This week and next week's dinners. Review, swap, remove, fill open nights. The flagship screen. |
| **Recipes** | The library. Browse, search, add three ways, scale to any number of servings. |
| **Pantry** | What's on hand across fridge / pantry / freezer, with expiry nudges. |
| **Shopping** | The list, grouped by aisle, checked off in the store. |

**The assistant is not one of them.** Planning conversations happen in a Claude
Project on claude.ai, which reaches all four through Misen's MCP server: it
reads the recipes and the pantry, writes the menu, and builds the shopping
list. Misen itself never calls a model.

The bet is unchanged — the assistant is the reason the other four stay current.
Nobody maintains a digital pantry for its own sake; people maintain it when
saying "we used the chicken" out loud is the whole interaction and something
useful happens as a result. What rev 3 changes is where that sentence gets
said: in Claude, not in a fifth tab.

The cost, stated plainly: planning means switching apps, and on a phone that is
a real difference. What it buys is no API key, no per-message billing, no chat
UI to build, and a far more capable assistant than a 16k-token proxy would have
been.

### Users

One household at launch — two adults, both trusted equally, sharing menu, pantry, and shopping list. Conversation history is per person, held by claude.ai rather than by Misen. But the data model is multi-household and multi-member from the first migration (decision 9), so adding kids is a row insert and adding a second household is a configuration change rather than a rewrite.

Members carry a `role` of `adult` or `child`. It records who someone is — for display, and for `cooked_by` — and the app uses it to decide what to put in front of a kid. **Nothing in the API branches on it.**

Rev 2 had a `can_use_basil` boolean here, off for children, justified as cost control over a paid endpoint. With no paid endpoint there is nothing to control: assistant access is now a claude.ai account, granted or not granted outside Misen entirely. The column is gone.

### Platforms

iPhone and iPad, both first-class, iOS/iPadOS 17+. The iPad is not a stretched phone — it is the in-kitchen device, and it gets a two-column layout plus **Cook Mode**, a full-screen step-by-step view designed to be read from across a counter with wet hands. See §8.

### Non-goals for v1

Stated explicitly so they don't creep in:

- No calorie, macro, or nutrition tracking. The design shows a `420 cal` field on recipe cards — that is whatever Mealie happens to have parsed, displayed as-is, not a feature.
- No sharing, social, publishing, or export.
- **No multi-household *UI*.** The schema supports it from day one; there is no household switcher, no invite flow, and no signup. Adding a second household in v1 means inserting rows by hand. This is the deliberate line: the expensive part (retrofitting a tenant key onto every table and query) is done now, the cheap part (a picker and an invite email) is deferred until it's actually wanted.
- No Android, no web client.
- No breakfast or lunch planning. `meal_slot` exists in the schema and defaults to `dinner`; nothing writes anything else in v1.
- No in-app grocery ordering. See decision 2.
- No unit conversion or ingredient normalization. Recipe scaling multiplies quantities; it does not convert cups to grams or re-pluralize "1 eggs".
- No push-notification server. Reminders are local (decision 12).

### What "done" looks like

One full week planned, shopped, and cooked using only Misen, with no fallback to Recipe Keeper, the notepad, or the Instacart app for anything except the final checkout tap — and at least one of those dinners cooked from the iPad on the counter.

---

## 2. Decisions

Rows marked **assumed** were my recommendation on an unanswered question. Decisions 9–13 are new in rev 2. Decisions 2, 6, and 7 were revised in rev 3, when Basil was replaced by a Claude Project; the original reasoning is kept rather than overwritten, because what changed was a premise, not a mistake.

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Recipe backend | **Mealie** | URL scraping, image/AI import, image hosting, shopping list — the bulk of the boring work, already built. Cost: a second service to operate and an API shape we don't control. |
| 2 | Instacart | **Cut the in-app button.** Shopping list gets a full API + MCP tools so an assistant can do it. | The design's "Order missing on Instacart" button and the plan's "no Instacart integration needed" contradicted each other. Resolution: no Instacart code anywhere in v1, but the list is fully readable and writable through the tools. Ordering is a conversation, not a button. **Rev 3:** Instacart's own MCP server is added to the Claude Project as a second connector, so the credential lives in a claude.ai account rather than in Misen's `.env` — which is closer to the original intent than proxying was. |
| 3 | Hosting | **One small VPS, Docker Compose, Caddy** | ~$6/mo, real domain, automatic HTTPS, reachable from anywhere including claude.ai later. |
| 4 | Offline | **SwiftData cache + optimistic writes**, queued sync, last-write-wins | The Shopping tab's entire job happens in a grocery store with bad signal. Largest single chunk of client work in the project and worth it. |
| 5 | Pantry precision | **assumed** — presence + free-text quantity + optional expiry. Nothing auto-decrements. | Structured quantities with auto-decrement need unit normalization ("1 onion" vs "150g onion") and drift from reality within days. Free text is what people actually maintain, and it's enough to answer "what can I make tonight". |
| 6 | Auth | **assumed** — one bearer token per member, in Keychain | Static tokens identify a member, scope every request to a household, and need zero login UI. Rotation means re-pasting; fine at household scale. **Rev 3:** the same token is pasted into claude.ai to authenticate the connector, so one credential covers both the app and the assistant and `--rotate` revokes both at once. |
| 7 | MCP access | **Revised in rev 3 — claude.ai is the only front door.** Bearer auth today; OAuth is the next work item. | Rev 2 read: *"bearer auth, in-app Basil first; OAuth for claude.ai deferred. Getting Basil working beats getting a second front door. Adding OAuth later doesn't change the tools."* That last clause is what made this reversible, and it held — the thirteen tools were built against Basil and needed no change to serve a Claude Project. What changed is that the second front door turned out to be the better one: it costs no API key, no chat UI, and no per-message billing, and Claude in a Project is more capable than the proxy would have been. Bearer tokens still work; OAuth removes the paste. |
| 8 | Repo & build order | **assumed** — monorepo, backend first | Backend and MCP can be built *and tested* in a Linux container; iOS can't be compiled without Xcode. Verify the API first, then write the app against something known-good. |
| 9 | Multi-household | **Tenant key from the first migration.** No switcher UI in v1. | Retrofitting `household_id` onto a live database means touching every table, every query, every index, and every MCP tool — with real data in flight. Adding it now costs one column and a `WHERE` clause per query. This is the single highest-return change in rev 2. |
| 10 | iPad | **Two-column `NavigationSplitView` + Cook Mode** | The iPad is the counter device. A stretched iPhone layout wastes it, and Cook Mode is the feature that makes the app useful *during* cooking rather than only before it. |
| 11 | Recipe scaling | **Client-side multiplier on parsed quantities, honest degradation on unparsed ones** | Mealie parses ingredients into `quantity / unit / food / note` when it can and leaves free text when it can't. Scaling multiplies the parsed number and leaves unparsed lines alone with a visible marker. No unit math, no pluralization. |
| 12 | Notifications | **assumed** — local notifications, scheduled on-device, no APNs | A weekly "plan next week" reminder does not justify an Apple push certificate, a device-token registry, and a server-side scheduler. Local notifications get 95% of the value for ~2% of the work. The 5% lost is smart cancellation when offline — see §9. |
| 13 | Freeform meals | **A menu slot can hold a recipe reference *or* a plain title** | Nachos does not need a recipe. Forcing every planned night through the recipe library is the kind of rigidity that makes people stop planning. Freeform meals contribute nothing to the shopping list, and `build_shopping_list` returns them in `freeform_entries` so the caller can ask about them. |

### Repo layout

```
/companion   FastAPI service — pantry, menu, shopping proxy, chat proxy, auth
/mcp         FastMCP server — the tools, calls Mealie + Companion
/ios         SwiftUI app (iPhone + iPad, one target)
/deploy      docker-compose.yml, Caddyfile, .env.example, backup script
/scripts     one-off jobs (Recipe Keeper migration, household/token provisioning)
/docs        this file, plus reference/
```

---

## 3. Architecture

```
              ┌──────────────────────────────────────────┐
              │        Misen (SwiftUI, iOS + iPadOS)     │
              │  iPhone: 5 tabs   iPad: split + Cook Mode│
              └─────┬──────────────────────────────┬─────┘
                    │                              │
      Mealie API (read + import)                   │  Companion API
      Bearer: shared Mealie token                  │  Bearer: per-member token
                    │                              │
            ┌───────▼──────┐            ┌──────────▼─────────────┐
            │    Mealie    │            │   Companion (FastAPI)  │
            │   + SQLite   │            │   + SQLite             │
            │   + images   │            │  households, members,  │
            │   + groups   │            │  pantry, menu, chat    │
            └───────┬──────┘            └─────┬──────────────┬───┘
                    │                         │              │ POST /v1/messages
                    └──────────┬──────────────┘              │ (mcp_servers → ↓)
                               │                             │
                     ┌─────────▼─────────┐                   │
                     │  MCP (FastMCP)    │◄──────────────────┘
                     │  13 tools, HTTP   │◄─── claude.ai (deferred, OAuth)
                     └───────────────────┘

     All four containers behind one Caddy reverse proxy, one domain, HTTPS.
```

**The app talks to two APIs, not one.** Mealie directly for recipe reads and imports; Companion for everything else. The one exception is the shopping list — it lives in Mealie but is proxied through Companion so check-off state, aisle grouping, and the MCP tools have a single implementation.

**The MCP server is the only thing Claude talks to.** It fans out to both backends internally, so a model sees one coherent tool surface. Rev 2 valued this because "Basil-in-the-app and a future Claude Project get identical capabilities for free" — rev 3 collects on exactly that: dropping Basil cost the tool surface nothing, because it was never built for Basil specifically.

It also makes `mcp.` the load-bearing hostname. It is no longer one feature's dependency; it is the whole assistant.

**Recipes stay in Mealie, always.** `menu_entries` holds a reference, never a copy.

### Multi-household and Mealie

This is the one place decision 9 bumps into decision 1, and it needs stating plainly: **Mealie has its own tenancy model — groups — and it is not automatically aligned with ours.**

For v1 (one household) this is invisible: one Mealie group, one household. To keep it invisible later, `households.mealie_group_id` exists from the first migration and every Mealie call is made with the calling household's group context. A second household means a second Mealie group, not a second Mealie.

The alternative — one shared recipe library across households — is a legitimate product choice (extended family sharing recipes) but it is a *different* product, and picking it later is easy if the group id is nullable. Picking it later without the column is not.

### Loose coupling to Mealie

1. Pin the Mealie image to an explicit version tag. Never `:latest`.
2. All Mealie access goes through one client module per consumer (`MealieClient.swift`, `mealie.py`). When Mealie's API shifts, exactly two files change.

---

## 4. Data model

SQLite for v1 — household scale, one writer at a time, simple ops, trivially backed up. Migrate to Postgres when concurrent writes start conflicting or the file exceeds ~1GB. Use Alembic from the first commit; retrofitting migrations onto a database with real data in it is unpleasant.

**Every tenant-scoped table carries `household_id` and every unique constraint includes it.** No exceptions, including tables where it looks redundant. The redundancy is the point — it means no query can accidentally cross tenants because it joined through a table that forgot.

```sql
CREATE TABLE households (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    timezone         TEXT NOT NULL DEFAULT 'America/New_York',  -- week boundaries + reminders
    week_starts_on   TEXT NOT NULL DEFAULT 'monday',
    mealie_group_id  TEXT,                    -- see §3; NULL = the default group
    mealie_shopping_list_id TEXT,             -- resolved on first use, then cached
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE members (
    id                  INTEGER PRIMARY KEY,
    household_id        INTEGER NOT NULL REFERENCES households(id),
    name                TEXT NOT NULL,        -- 'Nick', 'Mara'
    initials            TEXT NOT NULL,        -- 'N', 'M'
    color               TEXT NOT NULL,        -- 'terracotta' | 'green' | 'gold' | 'plum'
    role                TEXT NOT NULL DEFAULT 'adult' CHECK (role IN ('adult','child')),
    token_hash          TEXT NOT NULL UNIQUE, -- sha256 of the bearer token; never the token
    plan_reminder_day   TEXT,                 -- 'friday' | 'saturday' | NULL = off
    plan_reminder_hour  INTEGER,              -- 0–23, household-local
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_members_household ON members(household_id);

CREATE TABLE pantry_items (
    id           INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id),
    name         TEXT NOT NULL,
    quantity     TEXT,                        -- free text: '2 lbs', 'half a jar', NULL
    unit         TEXT,
    location     TEXT NOT NULL CHECK (location IN ('fridge','pantry','freezer')),
    expiry_date  DATE,
    used_at      TIMESTAMP,                   -- soft state; NULL = on hand
    added_by     INTEGER REFERENCES members(id),
    added_date   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_pantry_active ON pantry_items(household_id, location, used_at);

CREATE TABLE menu_entries (
    id                INTEGER PRIMARY KEY,
    household_id      INTEGER NOT NULL REFERENCES households(id),
    week_start        DATE NOT NULL,          -- always the household's week_starts_on day
    day_of_week       TEXT NOT NULL CHECK (day_of_week IN
                        ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')),
    meal_slot         TEXT NOT NULL DEFAULT 'dinner',
    entry_type        TEXT NOT NULL CHECK (entry_type IN ('recipe','freeform')),
    mealie_recipe_id  TEXT,                   -- Mealie SLUG. NOT NULL iff entry_type='recipe'.
    title             TEXT NOT NULL,          -- cache if 'recipe'; source of truth if 'freeform'
    servings          INTEGER,                -- planned servings; NULL = recipe's own default
    notes             TEXT,
    cooked_by         INTEGER REFERENCES members(id),
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by        INTEGER REFERENCES members(id),
    UNIQUE (household_id, week_start, day_of_week, meal_slot),
    CHECK ((entry_type = 'recipe' AND mealie_recipe_id IS NOT NULL)
        OR (entry_type = 'freeform' AND mealie_recipe_id IS NULL))
);
CREATE INDEX idx_menu_week ON menu_entries(household_id, week_start);

```

### Notes on the schema

**Tenant isolation is enforced in one place, not in every handler.** A FastAPI dependency resolves the bearer token to `(member, household)` and every repository function takes `household_id` as its first argument. No handler ever constructs a query without it. Add one test that walks every table and asserts a second household's data is invisible — that test is the whole defense, and it is worth writing on day one while there is only one household to break.

**`mealie_recipe_id` is the slug, not the UUID.** Mealie's API paths are slug-based and search returns slugs, so storing the slug avoids a lookup on every read. The tradeoff — renaming a recipe changes its slug and orphans the reference — is handled by `title`.

**`title` does double duty, deliberately.** For `entry_type='recipe'` it is a denormalized cache of Mealie's title: it lets the Menu tab draw fourteen day cards (two weeks) without fourteen fetches into Mealie, and it degrades a deleted recipe to a readable title with an "unavailable" state instead of a blank row. For `entry_type='freeform'` it is the source of truth — "Nachos", typed by a human. The `CHECK` constraint keeps the two cases from blurring.

**An empty night is the absence of a row.** `GET /menu` synthesizes the full grid; the database only stores what's planned.

**`servings` is nullable and means "the recipe's default".** Storing a copy of the recipe's own serving count would be a second cache to keep fresh for no benefit. Scale factor is computed at read time as `planned / recipe_base`, and is `1.0` when `servings IS NULL`. Freeform entries may carry `servings` for the human's benefit; nothing computes from it.

**`used_at` is a soft state, not a delete.** "We finished the salmon Tuesday" is useful context on Wednesday. Used items are hidden from the default Pantry view, purged after 30 days by a job, and stay visible to `get_pantry_items(include_used=true)`.

**There are no chat tables.** Rev 2 had `chat_messages` and `chat_usage` here, to hold Basil's transcript and per-turn token spend. With planning in a Claude Project, the transcript lives in claude.ai and there is no spend to record. Both were dropped in rev 3 by editing the initial migration in place — it had never been applied to a database, so nothing's history diverged.

**`mealie_shopping_list_id` was added during phase 1.** Mealie supports many shopping lists per household; Misen has exactly one and has to find the same one on every call. Matching by name looked simpler until you notice that renaming the list in Mealie's UI would strand it and silently start a second. The id is resolved once, cached here, and re-resolved if it ever points at nothing.

**Timestamps are naive UTC.** SQLite has no timezone type, so a column that accepts an aware datetime silently drops the offset on write. One clock (`utcnow()`), one meaning, and conversion to household-local time happens at the edge from `households.timezone`.

**Reminder preferences live server-side even though scheduling is local.** Two columns, and it means a reinstall doesn't silently lose the reminder and anything reading the household — the app, or Claude through `get_household` — can say "you get nudged Friday" from a stored fact rather than a guess.

**Dropped from rev 1:** `generation_sessions` and `sync_log` (last-write-wins with `updated_at` / `updated_by` on the rows is sufficient — see §8). Rev 2 kept `generation_sessions` out on the grounds that `chat_messages` did its job better; rev 3 drops that table too, so neither exists and the reasoning behind a plan lives wherever the conversation does.

---

## 5. Companion API

All endpoints require `Authorization: Bearer <member token>`. The token resolves to a member *and* a household; no request ever names a household explicitly. All mutations return the full updated resource so the client can reconcile without a follow-up read.

| Method | Path | Purpose | MCP tool |
|---|---|---|---|
| `GET` | `/health` | Liveness. No auth. | — |
| `GET` | `/me` | The calling member — id, name, initials, color, role, capabilities. Validates the token at launch. | — |
| `GET` | `/household` | The household — name, timezone, `week_starts_on`, and all members with names and roles. | `get_household` |
| `GET` | `/pantry` | `?location=` `?include_used=` | `get_pantry_items` |
| `POST` | `/pantry` | Add an item | `add_pantry_item` |
| `PATCH` | `/pantry/{id}` | Update any field; `{"used": true}` sets `used_at` | `update_pantry_item` |
| `DELETE` | `/pantry/{id}` | Hard delete (the Add-form's undo path, not "mark used") | — |
| `GET` | `/menu` | `?week_start=` `?weeks=2` — the grid, filled or empty, with titles and servings | `get_weekly_menu` |
| `PUT` | `/menu/{week_start}/{day}` | Upsert one slot — recipe **or** freeform. `{"recipe_id": null, "title": "Nachos"}` plans a freeform meal. | `set_weekly_menu` |
| `DELETE` | `/menu/{week_start}/{day}` | Clear a slot, making the night open again | `clear_menu_slot` |
| `GET` | `/recipes/{slug}/scaled` | `?servings=` — ingredients with quantities multiplied, plus per-line scaling status | `get_recipe` |
| `GET` | `/shopping` | The list, grouped by aisle, with check state | `get_shopping_list` |
| `POST` | `/shopping` | Add items (array) | `add_to_shopping_list` |
| `PATCH` | `/shopping/{id}` | Toggle checked | `check_shopping_item` |
| `DELETE` | `/shopping/{id}` | Remove an item | — |
| `POST` | `/shopping/from-menu` | Build the list from a week's recipes at planned servings, diffed against pantry | `build_shopping_list` |
| `GET` | `/reminders` | This member's reminder preference | — |
| `PUT` | `/reminders` | Set day + hour, or `null` to disable | — |

Two MCP tools have no row here on purpose. `search_recipes` goes straight from the MCP server to Mealie — proxying search would mean re-implementing pagination and tag filtering for no gain, and the app calls Mealie directly for the same reason. `get_recipe` maps to `/recipes/{slug}/scaled` because scaling is the one recipe operation Companion owns.

### `/menu` returns two weeks by default

The Menu tab shows this week and next week, so the endpoint returns both in one round trip — fourteen slots, each either an entry or an explicit empty marker. `?weeks=1` for a single week; `?week_start=` to page further out. The response includes the household's `week_starts_on` and computed week boundaries so the client never does timezone math itself.

### `/recipes/{slug}/scaled` is where scaling lives

Scaling happens server-side, not in the app, for one reason: three consumers need it (iPhone, iPad Cook Mode, and the shopping-list diff) and three implementations would drift. The endpoint fetches the recipe from Mealie, computes `factor = requested_servings / recipe_servings`, and returns each ingredient line with:

```json
{ "original": "2 cups flour", "scaled": "3 cups flour",
  "quantity": 3, "unit": "cups", "food": "flour", "status": "scaled" }
{ "original": "salt to taste", "scaled": "salt to taste",
  "quantity": null, "status": "unscaled_no_quantity" }
{ "original": "1 packet yeast", "scaled": "1.5 packet yeast",
  "quantity": 1.5, "status": "scaled_awkward" }
```

Three statuses, and the third is the honest one. `scaled` is a clean multiply. `unscaled_no_quantity` is a line Mealie couldn't parse a number out of — it passes through untouched and the UI marks it. `scaled_awkward` is a multiply that produced something a human wouldn't write: a fraction of a countable unit, or a value below a sensible floor. The app shows these with a subtle marker rather than hiding the problem.

Quantities render as fractions where they're close to common ones (`1.5 → 1½`, `0.33 → ⅓`) and as decimals otherwise. **No unit conversion.** 8 cups stays 8 cups, not 2 quarts. Scaling a recipe by 3 and getting "3 eggs, 4.5 cups flour, salt to taste" is correct and useful; trying to be cleverer than that is a rabbit hole with no bottom.

### `/shopping` is a proxy, and that matters

Mealie owns shopping list storage. Companion proxies it so check-off, aisle grouping, and the MCP tools have one implementation. The proxy also does the thing Mealie can't: `/shopping/from-menu` reads a week's menu, pulls each recipe's ingredients **at that entry's planned servings**, diffs against `pantry_items`, and writes only the gaps.

Two deliberate limitations, both surfaced in the UI rather than hidden:

- **The pantry diff is dumb** — case-insensitive substring match on name. It will miss "scallions" vs "green onions" and will occasionally suggest buying something you have. That's the right amount of engineering: the list is a starting point a human edits in the store, and Claude can be asked to sanity-check it, which is a better use of a model than a Levenshtein threshold.
- **Freeform entries contribute nothing.** "Nachos" has no ingredients, so the generated list has a gap. The response returns `freeform_entries: ["Nachos"]` so the app can say "3 nights are freeform — add anything you need for those" and Claude can ask directly.

**Rebuilding is safe.** "Generate the list" is a button someone presses more than once as a week fills in, and `build_shopping_list`'s own tool description tells the model to call it after finishing a plan. Anything already on the list comes back in `already_listed` instead of being added a second time — Mealie merges duplicate *food* items but not the free-text ones Misen writes, so without this the second press silently doubles the list. Explicit `POST /shopping` is not deduplicated: if someone asks for two of a thing, they get two.

**Ingredient lines that are instructions don't become items.** A line with neither a parsed food nor a quantity — "salt to taste", "freshly ground pepper" — is guidance to the cook, and a shopping list cluttered with them is one people stop reading. A line with a food but no quantity ("olive oil") is a real item and stays.

The response also carries `unavailable_recipes`: a recipe deleted in Mealie after being planned is named and skipped rather than failing the whole build.

### Errors

Standard HTTP codes with `{"error": {"code": "...", "message": "..."}}`. The client surfaces `message` directly, so keep it human-readable. `502` specifically means "Mealie is unreachable" and the client says so — the two backends fail independently and the user should know which half is down.

---

## 6. MCP tool surface

One FastMCP server over HTTP, bearer auth. Thirteen tools. It calls Mealie and Companion internally; a model never sees the seam.

**Tool descriptions are the highest-leverage text in this project.** Vague descriptions are the biggest reason models misuse or ignore tools, and the fix is being prescriptive about *when* to call each one. The descriptions below are the spec, not a paraphrase — write them into the code close to verbatim.

| Tool | Signature | Description to ship |
|---|---|---|
| `search_recipes` | `(query, tags=None, limit=20)` | "Search the household's recipe library by name, ingredient, or tag. Call this whenever the user asks what to cook, mentions a dish or cuisine, or asks whether they already have a recipe for something. Prefer this over suggesting a recipe from your own knowledge — the household's own library is almost always the better answer." |
| `get_recipe` | `(slug, servings=None)` | "Get one recipe's full ingredients and instructions, optionally scaled to a number of servings. Call this before adding a recipe to the menu, before answering questions about how to cook something, and before working out what needs buying. Pass `servings` when the user mentions cooking for a different number of people than usual." |
| `get_pantry_items` | `(location=None, include_used=False)` | "List what the household currently has in the fridge, pantry, and freezer, with expiry dates where known. Call this before suggesting any meal, before building a shopping list, and any time the user asks what they can make. Items expiring within three days should influence what you suggest first." |
| `add_pantry_item` | `(name, quantity=None, unit=None, location, expiry_date=None)` | "Add an item to the pantry, fridge, or freezer. Call this when the user says they bought something, brought something home, or mentions having an ingredient you didn't already know about." |
| `update_pantry_item` | `(item_id, ...fields, used=None)` | "Update or finish off a pantry item. Call with `used=true` when the user says they used, finished, ate, or threw out something. Call with a changed quantity when they used part of it. Look the item up with `get_pantry_items` first — this takes an id, not a name." |
| `get_weekly_menu` | `(week_start=None, weeks=2)` | "Get planned dinners, including which nights are still open. Defaults to this week and next week, because the household plans ahead. Call this before planning anything so you don't overwrite a decided night, and whenever the user asks what's for dinner." |
| `set_weekly_menu` | `(week_start, day, recipe_slug=None, title=None, servings=None, notes=None, cooked_by=None)` | "Assign a meal to one night. Pass `recipe_slug` for a recipe from the library, or `title` alone for a simple meal that doesn't need one ('Nachos', 'Leftovers', 'Takeout') — not every night needs a recipe, and forcing one is worse than a plain title. Pass `servings` when cooking for more or fewer people than the recipe assumes. This writes to the shared menu both members see immediately, so confirm before replacing a night that already has a meal on it." |
| `clear_menu_slot` | `(week_start, day)` | "Clear one planned night, making it open again. Call this only when the user explicitly asks to remove or cancel a meal — never as a step in replacing one, since `set_weekly_menu` overwrites directly." |
| `get_shopping_list` | `(unchecked_only=False)` | "Get the current shopping list with aisle grouping and check-off state. Call this before carting anything, when the user asks what they need to buy, and after building a list to confirm what's on it. Use `unchecked_only=true` to get exactly the items still needed — that is the right input for an Instacart order." |
| `add_to_shopping_list` | `(items: list[{name, quantity}])` | "Add items to the shopping list. Call this when the user says they need something, when a planned recipe needs an ingredient the pantry doesn't have, or when they ask you to add to the list." |
| `check_shopping_item` | `(item_id, checked=True)` | "Mark a shopping item as bought or un-bought. Call this when the user says they picked something up or already have it." |
| `build_shopping_list` | `(week_start=None)` | "Generate the shopping list from a week's planned dinners at their planned serving counts, skipping anything already in the pantry. Call this after finishing a week's plan. Two caveats to pass on to the user: pantry matching is approximate, so the list needs a review; and any freeform meals on the menu contribute nothing, so ask what those need." |
| `get_household` | `()` | "Get the household's members, their names and roles, the timezone, and which day the week starts on. Call this when you need to know who's in the house — for example when assigning who's cooking a given night, or when the user refers to someone by name." |

### What is deliberately absent

No `delete_recipe`, no `delete_pantry_item`, no household or member mutation. Destructive and administrative operations stay in the app or in `scripts/`, where a human is looking at a confirmation dialog. Claude can mark things used, overwrite a menu slot after confirming, and clear a slot on explicit request; it cannot erase a recipe or change who lives here.

That boundary matters more in rev 3 than it did in rev 2. Under Basil the tool surface was reachable only through a prompt Misen wrote; now it is reachable from a Claude Project, where the instructions are whatever the member typed. The tools are the control, and they always were — this is why they were specced as the control rather than the prompt.

### Tenancy in MCP

The MCP bearer token *is* the Companion token — the same string, not a parallel one. The server verifies it with `GET /me` and forwards it on every call, so it is stateless: no database, no token store, and no credential that could reach a household's data on its own. There is no `household_id` parameter on any tool, deliberately: a model that could name a household could name the wrong one.

This settles §10's "the MCP server holds its own bearer token per member" the simpler way. A second token per member means a second secret store, a second rotation path, and a second thing to fall out of sync — for identical blast radius, since the tool surface covers most of the API anyway. In phase 5 Companion already has the member's plaintext token in the request it is serving, so it passes that straight through as `mcp_servers[].authorization_token` without minting anything. The cost, stated plainly: that token is handed to Anthropic so their servers can call ours. Rotation is `provision.py --rotate` and it invalidates both paths at once, which is the upside of there being only one.

---

## 7. The Claude Project

Misen has no assistant of its own. Planning happens in a **Claude Project on
claude.ai** with Misen's MCP server attached as a custom connector.

```
claude.ai Project  ──MCP over HTTPS──►  mcp.misen.<domain>  ──►  Companion
   member token as                      13 tools                └──►  Mealie
   connector auth                       stateless, forwards
                                        the caller's token
```

Nothing in Misen calls a model, holds an API key, or streams a token. The whole
assistant is the tool surface in §6 plus a connector.

### Why this replaced Basil

Rev 2 specced Basil: a chat tab, a server-side proxy to the Messages API with
the MCP server attached, an SSE path, a transcript table, and a daily spend cap.
It was built and tested. Rev 3 removed it.

The argument is that Basil was a **second front door onto capabilities that
already existed**, and the more expensive one:

| | Basil | Claude Project |
|---|---|---|
| Model access | Anthropic API key, metered per message | Each member's own Claude subscription |
| Capability | A 16k-token proxy with a fixed prompt | Claude, with Projects, memory, artifacts |
| Cost to build | Proxy, SSE, transcript, cap, chat UI | A connector, and OAuth to remove the paste |
| Where planning happens | Inside Misen | claude.ai — a different app |

That last row is the real cost and it is not small: on a phone, planning means
leaving Misen. Rev 3 accepts it. The four tabs are for *looking things up and
checking things off* — the two things you do standing in a kitchen or a store —
and planning is a sit-down activity that was always going to be a conversation.

**This was anticipated.** Decision 7 deferred OAuth on the grounds that "adding
OAuth later doesn't change the tools", and §3 justified the MCP server partly
because "a future Claude Project gets identical capabilities for free". Both
held exactly: the thirteen tools moved over unchanged.

### Setup

Per member, once:

1. Add a custom connector in claude.ai pointing at `https://mcp.misen.<domain>/mcp`.
2. Authenticate with that member's own token from `provision.py`.
3. Create a Project and enable the connector on it.

**Each member uses their own token.** The MCP server forwards whatever it is
given, so a connector reaches exactly what that member could reach through the
app, and `cooked_by` records the right name. Sharing one token would work and
would be wrong — it makes two people indistinguishable in the menu history.

The Project's custom instructions are where Basil's system prompt went, minus
everything that was scaffolding. Worth keeping from it:

- **Ask before overwriting a planned night.** The tools allow it; the habit
  shouldn't be silent.
- **Plan around what's in the pantry and what expires first.** This is the
  whole point of the pantry existing.
- **Freeform nights are fine.** Not every dinner needs a recipe; `set_weekly_menu`
  takes a plain title, and offering "or just do leftovers" is a feature.
- **Build the shopping list after finishing a plan**, and say what was skipped
  as already on hand.

Unlike a system prompt Misen shipped, these are editable by the person using
them, which is the right place for taste to live.

### What the household loses

Stated plainly rather than buried:

- **No assistant on the phone in the kitchen.** "What can I make tonight?" now
  means opening Claude.
- **No shared assistant state.** Each member's conversations are their own, in
  their own account. The *data* is still shared — if Mara plans Tuesday, Nick
  sees it on the Menu tab immediately — but there is no household transcript.
- **A Claude subscription per planner**, rather than one metered API key for the
  household.

### Instacart, still without any Instacart code

Decision 2 said: no Instacart code anywhere in v1, but the list is fully
readable and writable through the tools. That survives rev 3 intact, and gets
simpler — Instacart publishes its own remote MCP server, so it is added to the
same Project as a **second connector**.

Misen ships zero lines of Instacart integration and now also holds zero
Instacart credentials: the key lives in the member's claude.ai account. Get one
at [docs.instacart.com](https://docs.instacart.com/developer_platform_api).

The standing rule is unchanged and matters most here: **show the cart and get
approval before any paid order.**

---

## 8. The app

Native SwiftUI, one target, iOS/iPadOS 17+ (SwiftData requires it). `NavigationStack` on iPhone, `NavigationSplitView` on iPad, `@Observable` throughout. The HTML in the design handoff is the visual and interaction spec — recreate it in idiomatic SwiftUI, don't port it.

### Design system

Ship the tokens as a `Theme` enum before building any screen. Every view reads from it. Full table in [`reference/design-handoff.md`](reference/design-handoff.md); the anchors:

| | |
|---|---|
| App background | `#F6EEE0` cream |
| Surface | `#FFFFFF` |
| Ink / muted / faint | `#2A241E` / `#8C8175` / `#A79B8B` |
| Primary (terracotta) | `#C4573A` — active tab, FAB, primary buttons, user bubble |
| Herb green | `#5E7C4F` — completed checks, progress |
| Accent brown | `#B08247` — eyebrows, day labels |
| Display type | Newsreader (serif), embedded |
| UI type | DM Sans, embedded |

Six meal-placeholder gradients at 140°, assigned by hashing the recipe slug so a recipe always gets the same color. Real Mealie images replace them where available. Embed both fonts; a first pass with `.serif` + system unblocks layout, but the serif display face is most of the app's character.

### iPhone — five tabs

| Screen | Spec |
|---|---|
| **Menu** | **Two weeks.** Segmented control at the top: `This Week` / `Next Week`, with the serif date range below it and a dot indicator when the other week has open nights. Overlapping member avatars top-right. Two stat cards (dinners planned / nights open) for the visible week. Seven day cards: date block, 56×56 thumbnail, serif title, `55 min · serves 4 · You` meta, peach **Swap** chip + ghost **Remove**. Recipe entries show a serving stepper when tapped. Freeform entries show the title with a small "no recipe" glyph in place of the thumbnail gradient and no time/serves meta. Empty state: dashed `＋ Plan a dinner`, which opens a picker offering **Choose a recipe** or **Just a name** (see below). |
| **Recipes** | Serif header + round terracotta **+** FAB. Search field. Horizontal filter chips (All dinners / Quick / Vegetarian / Favorites / Slow-cook) wired to real Mealie tag filtering. Editorial split cards: 118px image left, category eyebrow + favorite heart + serif title + `⏱ 55 min · serves 4 · 420 cal`. |
| **Recipe detail** | Serif title, hero image, a **servings stepper** in the header that rescales ingredient quantities live via `/recipes/{slug}/scaled`. Scaled lines render the new quantity; `unscaled_no_quantity` lines render unchanged in muted text; `scaled_awkward` lines get a small `~` marker. A "Cook" button — on iPhone it's a focused full-screen step view, on iPad it's Cook Mode. |
| **Add Recipe sheet** | Bottom sheet, grabber, three options: **Paste a link** → Mealie scraper, **Snap a photo** → Mealie OCR/AI import, **Write it yourself** → manual form. |
| **Add Recipe (manual)** | Full-screen. Cancel / "New Recipe" / Save. Dashed photo tile, serif title field, Time / Serves / Category row, dynamic Ingredients rows, dynamic Steps rows. |
| **Plan a meal** | New, small. Two paths: **Choose a recipe** opens a searchable picker over the library; **Just a name** is a single text field and a Save button. Both land on the same `PUT /menu/{week}/{day}`. The freeform path must be no more than two taps and a word — the moment it feels like data entry, people stop planning. |
| **Pantry** | Segmented Fridge / Pantry / Freezer, active = white pill with terracotta text. Rows: square check (fills green), name + quantity, expiry chip — amber `#FBEBD3`/`#B0632F` at ≤3 days, red `#F8DAD3`/`#C0392B` at today-or-overdue. Used items strike through at 45% opacity, then leave on next refresh. Dashed `＋ Add item`. |
| **Add Pantry Item** | Full-screen. Serif name field, "Store in" segmented (active = terracotta), Quantity + Unit, optional use-by date, quick-add chips (Milk, Eggs, Butter, Onions, Rice). |
| **Shopping** | Header + green progress bar. Inset white cards grouped by aisle. Round check rings fill green; checked rows strike through and fade. A banner when the generated list had freeform gaps. **No Instacart button** (decision 2), and no "ask the assistant" footer either — ordering is a conversation that happens in the Claude Project (§7). |

There is no fifth tab. The design source has a Basil screen — green leaf avatar, chat bubbles, suggestion chips — and rev 3 drops it; see §7 for what replaced it.

Tab bar: 4 tabs, 24px stroked icons, active terracotta, inactive faint. SF Symbols where they fit; custom for the dish glyph.

### iPad — split view and Cook Mode

**Layout.** `NavigationSplitView` with a persistent sidebar (the four sections as a list, not a tab bar) and a two-column content/detail area. The wins are concrete: the Menu shows both weeks side by side with no segmented control; Recipes shows the list and the selected recipe together; Pantry shows all three locations as columns instead of a segmented control; Shopping shows aisles in a multi-column grid so a full list fits without scrolling. Same views, different container — not a second codebase.

**Cook Mode** is the reason the iPad matters, and it is a distinct screen rather than a bigger recipe detail:

- Full screen, no chrome, no sidebar.
- One step at a time in large serif type, readable from three feet away across a counter.
- The ingredient list stays pinned in a side column at the current scale factor, each line tappable to check off as it goes in.
- Swipe or tap large left/right zones to move between steps — targets sized for a knuckle, because hands are wet or covered in flour.
- `isIdleTimerDisabled = true` for the duration, restored on exit. A screen that sleeps mid-recipe is the entire reason people prop a cookbook open instead.
- A step count and progress indicator so you can see where you are at a glance.
- Optional timers: when a step's text contains a duration ("simmer for 20 minutes"), offer a one-tap timer. Detection is a simple regex over common phrasings and it is fine for it to miss some — a missed timer costs nothing, and a wrong one is only ever a suggestion the user taps or ignores.

Cook Mode is available on iPhone too, in a single-column form, but it is designed for the iPad and that's where it should be evaluated.

### Offline and sync

The contract, precisely, because this is where client bugs live:

**Cached in SwiftData:** pantry items, this week's and next week's menu, the shopping list, recipe list metadata + thumbnails, and full bodies of recipes on the menu (so Cook Mode works in a kitchen with bad wifi).

**Never cached:** full bodies of recipes not on the menu (fetched on open, cached opportunistically after), and anything from the Add Recipe flows.

**Reads** render from cache immediately, then refresh in the background and diff. No blocking spinner on any tab open, ever.

**Writes** apply locally and enqueue a mutation. The UI never waits on the network for a check-off, a swap, a pantry toggle, or a serving change. The queue drains on connectivity, on foreground, and on a 30-second timer.

**Conflicts** resolve last-write-wins on `updated_at`. With two adults in one house this is nearly always correct and always explainable. Both members checking the same shopping item is idempotent — no conflict, no UI.

**Failure** after three retries drops the mutation into a visible "couldn't sync" state on the affected row with a retry affordance. Silent data loss is the one unacceptable outcome; a visibly stuck row is fine.

**Scaling is computed server-side but cached client-side** per `(slug, servings)`, so a scaled recipe opened once works in Cook Mode offline.

---

## 9. Notifications

**Local notifications only. No APNs, no device tokens, no server-side scheduler.** A once-weekly reminder does not justify a push certificate and a delivery pipeline.

**The reminder.** Default Friday 5pm household-local, configurable to Saturday and to any hour, or off. Copy names the gap rather than nagging: *"Next week has 5 open nights — plan them now so there's time to order."* Tapping opens the Menu tab on **next** week.

**Scheduling.** `UNUserNotificationCenter` with a repeating weekly trigger, registered at first launch after permission and re-registered whenever the preference changes. Preferences persist to `PUT /reminders` so a reinstall recovers them and `get_household` can report them accurately.

**Conditional cancellation** is where local notifications are weaker than push, and the mitigation is worth stating. If next week is already fully planned, the reminder is noise. So:

- On every foreground and on a `BGAppRefreshTask`, the app counts open nights next week and either schedules the reminder or cancels it.
- The pending notification's body is rewritten with the current count at the same time.

The failure mode: if the app hasn't been opened or background-refreshed since the week was planned, a stale reminder fires for a week that's already full. That is a minor annoyance, roughly once in a while, and it is the entire cost of not running a push server. If it turns out to grate, APNs from Companion is the upgrade path and nothing else in the design has to change.

**Permission** is requested contextually — after the first week is successfully planned, not at first launch. Asking for notification permission on a cold start, before the app has demonstrated it's worth hearing from, is how you get denied.

**Not in v1:** expiry notifications ("your salmon expires tomorrow"). Tempting, and the data supports it, but a notification per expiring item is how an app gets muted, and getting the frequency right needs real usage data. Revisit after the dry run.

---

## 10. Auth

Tokens generated by `scripts/provision.py`, which creates a household, its members, and one token each: 32 random bytes, base64url. Plaintext printed once, never stored — only `sha256(token)` goes in `members.token_hash`.

Distribution is manual: paste into each device at first launch through a one-field setup screen. Stored in Keychain with `kSecAttrAccessibleAfterFirstUnlock`. Every request sends `Authorization: Bearer <token>`; Companion hashes, looks up, and resolves `(member, household)`.

`role` is a label, not a permission: nothing in the API branches on it, so there is no server-side capability check to get wrong. Tenant scoping is the control that matters, and it is enforced in one dependency (§4).

**The connector is authenticated with the member's own token.** The MCP server verifies it against Companion's `/me` and forwards it on every call, holding no credentials itself — so a Claude Project reaches exactly what that member could reach through the app, and no more. OAuth is the next work item; it removes the paste without changing that property.

The MCP server holds its own bearer token per member, passed by Companion in `mcp_servers[].authorization_token`.

Rotation: re-run the script, update the row, re-paste. At household scale this is a two-minute job and does not justify a refresh-token flow.

**What this does not protect against:** a stolen unlocked device. Accepted — the blast radius is a meal plan and a grocery list.

---

## 11. Infrastructure

**Host:** one VPS, 2GB RAM minimum (Mealie alone wants ~1GB), 25GB disk. $6–12/mo.

**Compose:** four services — `mealie`, `companion`, `mcp`, `caddy`. Named volumes for Mealie's data and images and for the companion SQLite file. Every image pinned to an explicit version tag.

**Caddy:** three subdomains (`mealie.`, `api.`, `mcp.`), automatic HTTPS. Only Caddy publishes ports; the rest are on the internal network.

**Secrets** in `.env`, gitignored, with a committed `.env.example` listing every key and no values. After rev 3 there is exactly one: `MEALIE_API_TOKEN`. No model API key exists anywhere in the deployment, and the MCP server has no token of its own — callers present theirs.

**Backups** — nightly cron, 30-day retention, off-box:
1. `sqlite3 .backup` on the companion DB (never `cp` a live SQLite file)
2. Same for Mealie's DB
3. `tar` of Mealie's image directory — the one genuinely unrecoverable asset, since recipes could be re-scraped but photos of your own cooking could not

**Restore is tested once, during phase 0, on a scratch host.** An untested backup is a hope.

---

## 12. Build phases

Each phase has a "done when" someone else could verify.

**Phase 0 — Infrastructure.** Compose up on the VPS, Caddy serving three subdomains over HTTPS, Companion answering `/health`, backup cron installed and a restore rehearsed.
*Done when:* `curl https://api.misen.<domain>/health` returns 200 from off-network, and a restore from last night's backup produced a working Mealie on a scratch host.

**Phase 1 — Companion API.** Full schema with Alembic including household scoping, all pantry / menu / shopping / scaling / reminder endpoints, auth with roles, tests.
*Done when:* a Postman collection exercises every endpoint in §5 including failure paths; `pytest` is green with the shopping diff and the scaling statuses covered; and **the cross-tenant isolation test passes** — a second household's token sees none of the first household's rows on any endpoint.
**Done.** 128 tests, [`docs/misen.postman_collection.json`](misen.postman_collection.json) covering all 18 endpoints, and `tests/test_isolation.py` — which includes a guard that fails the build when a new tenant-scoped table arrives without an isolation assertion. Chat endpoints are phase 5; their tables ship in the phase 1 migration so the schema migrates once.

**Phase 2 — Recipe migration.** One-off script: an export or a cookbook → parse → POST to Mealie.
*Done when:* recipe count matches the export, and ten spot-checked recipes have intact ingredients, steps, and images.
**Importer built** (`scripts/`), 53 tests. Rev 1 assumed one input — a Recipe Keeper `.zip` — and the first real input was a cookbook PDF converted to markdown, so the pipeline is now parser-plus-shared-uploader rather than one script. Recipe Keeper is still to write and still waiting on the export.
**On "images":** a converted PDF has none. The photographs are what the *text* was lost to, not an asset that came along with it. Recipes imported this way have no image and that criterion cannot be met from this input.
**Ingredients are parsed by the importer, not by Mealie.** Quantity, unit and food are filled in by `scripts/recipes/analyse.py`; `display` keeps the line as printed. This is not an optimisation — §5's scaling multiplies `quantity` and §5's shopping diff matches `food`, so an importer that writes free text produces recipes that refuse to scale and weeks with an empty shopping list. The first version did exactly that. `companion/tests/test_imported_recipes.py` pins the contract from the reading side.

**On "count matches":** it does not, and saying so is the point. Of 89 recipes in that cookbook's contents, 64 parsed and 25 exist only as photographs. Of the 64, eight came back as fragments and are marked for retyping. The importer reports all three numbers rather than importing 64 and calling it done.

**Phase 3 — MCP server.** Thirteen tools with the §6 descriptions, bearer auth, calling both backends.
*Done when:* connected to a real Claude client, a single conversation plans three dinners *including one freeform*, scales one recipe to 6 servings, adds two pantry items, and builds a shopping list — with every write visible in the database and correctly scoped to the household.
**Done, mechanically.** 51 tests, plus that exact scenario driven end to end by a real MCP client against a real MCP server and a real Companion, asserting the rows in SQLite and that a second household sees none of them. What has *not* happened is a human connecting a Claude client to it, which needs the host — the judgement half of this criterion (do the descriptions make a model reach for the right tool?) can't be checked from here. **After rev 3 this criterion is the product**, not a phase-3 checkpoint: it is now phase 5's acceptance test too.

**Phase 4 — iPhone app.** Theme, four tabs, the two-week Menu, the plan-a-meal flow, scaling UI, three forms, SwiftData cache, sync queue, local notifications.
*Done when:* running on both phones from TestFlight; every screen matches the design at a glance; airplane mode on Shopping still checks items off and syncs on reconnect; a recipe scaled to 8 servings shows sensible quantities and honest markers on the lines that didn't scale; and the Friday reminder fires with an accurate open-night count.

**Phase 5 — The Claude Project.** Connector setup per member, Project instructions, and OAuth so members sign in rather than pasting a token.
*Done when:* "plan my dinners for the week" in the Project produces seven filled nights visible on the Menu tab, at least one of which Claude correctly chose to make freeform; the shopping list builds from them with pantry items skipped; and a second member's connector resolves to *that* member.
**Rewritten in rev 3.** The previous phase 5 built Basil — three endpoints, 37 tests, SSE, `pause_turn` handling — and it worked. It was removed rather than shipped; see §7. What survives is the part that was never Basil-specific: the thirteen tools, unchanged.
**Not done:** everything here needs the host. Connector setup and the acceptance run above are blocked on phase 0, and OAuth is unstarted — the two facts to establish first are what claude.ai's custom connectors require for auth, and what FastMCP's current auth API offers. Bearer tokens work in the meantime.

**Phase 6 — iPad and Cook Mode.** `NavigationSplitView`, two-week side-by-side Menu, multi-column Pantry and Shopping, Cook Mode with scaled ingredients, wake lock, and step timers.
*Done when:* a real dinner is cooked start to finish from the iPad on the counter without the screen sleeping, without leaving Cook Mode, and with the ingredient checklist used.

**Phase 7 — Dry run.** One real week, end to end, both members, no fallbacks to the old tools.
*Done when:* it's Sunday, the week happened, and there is a written list of what broke.

**Deferred past v1:** OAuth on the MCP server for claude.ai, a household switcher and invite flow, breakfast/lunch slots, the Instacart Developer API, expiry notifications, unit conversion.

---

## 13. Risks and open questions

**Pantry drift is still the one that decides whether this works.** Every other risk is technical. If the pantry stops reflecting the fridge, Claude's suggestions degrade to guesses and trust goes with them. Rev 3 makes this slightly worse, not better: the pantry is now updated in one app and read in another, so "we used the chicken" has to survive a context switch. Mitigations: quick-add chips, a visible expiry view, and making "we used the chicken" a one-sentence interaction. Watch it during phase 7 — if the pantry is wrong by Wednesday, that's the signal to reconsider decision 5 toward a lighter staples-checklist model rather than a heavier structured one.

**Scope grew meaningfully in rev 2, and phase 4 is where it lands.** Multi-household is nearly free (a column and a `WHERE`), but the two-week Menu, scaling UI, freeform planning, and notifications all hit the same phase, and phase 6 adds a second layout plus a genuinely new screen. If something has to give, **Cook Mode timers and the multi-column iPad Pantry are the first cuts** — they're polish. The two-week Menu and freeform meals are not; they change whether the app fits how the week actually works.

**Scaling will produce awkward output sometimes.** "1.5 packet yeast" is not wrong, exactly, but it isn't what a person would write. The `scaled_awkward` status exists so the UI can be honest rather than confidently silly. Accepted; the alternative is a units and pluralization engine, which is a project.

**Mealie coupling, now with tenancy.** An upstream breaking change hits recipes, shopping, *and* the group mapping. Mitigated by pinned versions and single client modules. Accepted.

**Local notifications can fire stale.** Bounded, understood, documented in §9. Accepted for v1.

**API spend is no longer a risk.** Rev 2 bounded it with a daily cap and a `chat_usage` table. Rev 3 removes the spend entirely — the deployment holds no model API key, and conversations bill to each member's own Claude subscription.

**`mcp.` is now a single point of failure for the assistant.** Under Basil, an unreachable MCP host degraded one feature and the app kept working. Now it is the difference between Claude being able to see Misen and not. The app itself is unaffected — it talks to Companion directly — but "plan my week" stops working entirely. Mitigation is the same as for everything else on that box: it is one Caddy site and one container, and `deploy/README.md` step 8 tests it from off-host.

**No Xcode in the dev container.** The backend and MCP server can be built and tested there; the iOS app can be written but not compiled. Expect a round of compile-error fixing when phase 4 first opens in Xcode — and phase 6 doubles the surface area for that, since split-view layout problems only appear at runtime. Budget for it rather than being surprised.

**Open — worth deciding before phase 4:** what should the Menu tab's **Swap** actually do? The prototype cycles a hardcoded pool. Rev 2 listed "ask Basil for one alternative inline" as the most interesting option; with no in-app assistant that is off the table, which leaves (a) open the recipe picker or (b) cycle recipes tagged for that slot. (a) is predictable and honest. Not blocking until the Menu tab is built.

**Open, and now the main one:** does planning in a separate app actually hold up over a few weeks? This is the bet rev 3 makes and it is not provable from here. Watch it during phase 7 alongside pantry drift — if planning stops happening because it means leaving Misen, the answer is not to rebuild Basil but to ask what the Menu tab could do on its own.

**Settled in rev 3:** assistant access is a claude.ai account, not a Misen permission. `can_use_basil` is gone and there is no per-member spend allowance to design, because there is no spend.

---

## References

- [`reference/architecture-plan.md`](reference/architecture-plan.md) — original systems plan. Two byte-identical copies were supplied; one is archived here. Superseded by this document where they disagree.
- [`reference/design-handoff.md`](reference/design-handoff.md) — the design handoff. Authoritative for all visual and interaction detail; §8 summarizes rather than replaces it, and extends it for iPad, two-week Menu, scaling, and freeform meals, none of which the prototype covers.
