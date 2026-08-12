# Misen

**A warm kitchen, in its place.**

A family meal planning app for iPhone and iPad. Plan the week's dinners, keep a recipe library, track what's on hand, and shop the list. Planning with Claude happens in a Claude Project on claude.ai, which reaches the same data through Misen's MCP server — it can read the pantry, write the menu, and build the shopping list.

Not built yet. [`docs/PRD.md`](docs/PRD.md) is the spec.

## What it is

Four sections: **Menu · Recipes · Pantry · Shopping**.

Two backends behind one reverse proxy — [Mealie](https://mealie.io) for recipes and shopping list storage, and a small FastAPI companion service for the pantry and the weekly menu. A FastMCP server sits over both and gives Claude one coherent tool surface. Misen itself never calls a model: the assistant is Claude, in a Project, holding a connector to that server.

## Layout

| Path | What |
|---|---|
| `companion/` | FastAPI — pantry, menu, shopping proxy, recipe scaling, auth |
| `mcp/` | FastMCP server — the tools Claude calls |
| `ios/` | SwiftUI app, one target, iPhone + iPad |
| `deploy/` | Compose file, Caddyfile, `.env.example`, backup script |
| `companion/scripts/` | One-off jobs against the Companion database — household provisioning |
| `scripts/` | Recipe importers — cookbook and export files into Mealie |
| `docs/` | The PRD, the Postman collection, and the source documents it was built from |

## Status

| Phase | |
|---|---|
| 0 — Infrastructure | code complete, awaiting a host — see [`deploy/README.md`](deploy/README.md) |
| 1 — Companion API | done — 18 endpoints, 136 tests, [Postman collection](docs/misen.postman_collection.json) |
| 2 — Recipe migration | importer built, 53 tests — 56 recipes ready to load, [review](docs/recipes/stealth-health-slow-cooker-review.md) |
| 3 — MCP server | done — 13 tools, 51 tests |
| 4 — iPhone app | not started |
| 5 — Claude Project | connector setup, and OAuth so members sign in rather than pasting a token |
| 6 — iPad + Cook Mode | not started |
| 7 — Dry run | not started |

Phase detail and acceptance criteria: [`docs/PRD.md` §12](docs/PRD.md).
