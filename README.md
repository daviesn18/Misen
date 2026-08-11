# Misen

**A warm kitchen, in its place.**

A family meal planning app for iPhone and iPad. Plan the week's dinners, keep a recipe library, track what's on hand, shop the list, and chat with **Basil** — an embedded assistant that can read the pantry, write the menu, and cart the missing groceries.

Not built yet. [`docs/PRD.md`](docs/PRD.md) is the spec.

## What it is

Five sections: **Menu · Recipes · Pantry · Shopping · Basil**.

Two backends behind one reverse proxy — [Mealie](https://mealie.io) for recipes and shopping list storage, and a small FastAPI companion service for the pantry, the weekly menu, and the chat proxy. A FastMCP server sits over both and gives Claude one coherent tool surface, which is how Basil does anything useful.

## Layout

| Path | What |
|---|---|
| `companion/` | FastAPI — pantry, menu, shopping proxy, recipe scaling, chat proxy, auth |
| `mcp/` | FastMCP server — the tools Basil calls |
| `ios/` | SwiftUI app, one target, iPhone + iPad |
| `deploy/` | Compose file, Caddyfile, `.env.example`, backup script |
| `companion/scripts/` | One-off jobs against the Companion database — household provisioning |
| `docs/` | The PRD, the Postman collection, and the source documents it was built from |

## Status

| Phase | |
|---|---|
| 0 — Infrastructure | code complete, awaiting a host — see [`deploy/README.md`](deploy/README.md) |
| 1 — Companion API | done — 18 endpoints, 130 tests, [Postman collection](docs/misen.postman_collection.json) |
| 2 — Recipe migration | not started — needs the Recipe Keeper export |
| 3 — MCP server | done — 13 tools, 50 tests |
| 4 — iPhone app | not started |
| 5 — Basil | server done — chat proxy, SSE, 37 tests; the chat UI is part of the app |
| 6 — iPad + Cook Mode | not started |
| 7 — Dry run | not started |

Phase detail and acceptance criteria: [`docs/PRD.md` §12](docs/PRD.md).
