# Companion API

Pantry, weekly menu, recipe scaling, shopping proxy, reminders. FastAPI over
SQLite. [PRD §5](../docs/PRD.md) is the spec; this is how to work on it.

## Layout

| Path | What |
|---|---|
| `app/models.py` | The schema. Every tenant-scoped table carries `household_id`. |
| `app/auth.py` | Bearer token → `(member, household)`. The only thing that resolves a tenant. |
| `app/mealie.py` | The only module that knows Mealie's URL shape or its camelCase JSON. |
| `app/scaling.py` | Quantity arithmetic and the three per-line statuses. Pure. |
| `app/shopping_build.py` | The menu → list diff. Pure. |
| `app/routers/` | HTTP only — the thinking happens in the modules above. |
| `scripts/provision.py` | Creates households and mints member tokens. |

## Running it

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

export MISEN_DB_PATH=./misen.db
export MISEN_MEALIE_URL=http://localhost:9000
export MISEN_MEALIE_TOKEN=<a Mealie API token>

.venv/bin/alembic upgrade head
.venv/bin/python scripts/provision.py --household "Test" --member "You:Y:terracotta"
.venv/bin/uvicorn app.main:app --reload
```

Interactive docs at `/docs`. The token from `provision.py` goes in the
`Authorization: Bearer …` header; it prints once and is never stored.

## Tests

```sh
.venv/bin/pytest          # 128 tests, no network, no Mealie
.venv/bin/ruff check .
```

Mealie is never contacted — `tests/conftest.py` substitutes a fake through the
`get_mealie` dependency. That keeps the suite fast, but the real reason is that
the failure paths worth testing (Mealie down, a recipe deleted mid-week) are
ones a live server won't produce on demand.

**Two households exist in every test**, not just the isolation ones. A query
that forgets its `household_id` is far more likely to be caught by whichever
test happens to touch it than by the one test looking for it.
`tests/test_isolation.py` also fails the build if a new tenant-scoped table
arrives without an isolation assertion.

## Migrations

```sh
.venv/bin/alembic revision --autogenerate -m "what changed"
.venv/bin/alembic upgrade head
.venv/bin/alembic check        # fails if models and migrations have drifted
```

`alembic/env.py` takes the database URL from application settings, never from
`alembic.ini`, so a migration cannot run against a different file than the app
is using. `render_as_batch` is on because SQLite can't `ALTER` most things in
place.

The container runs `alembic upgrade head` before uvicorn on every start. It's a
no-op at head, and it means a rebuild after a schema change needs no second
command.

## Conventions

**Repositories take `household_id` first, always.** No handler constructs a
query without it, and lookups filter by id *and* household in the same query —
fetching by primary key and then checking ownership leaks existence through the
difference between 403 and 404.

**One error envelope.** `{"error": {"code", "message"}}`, and `message` is shown
directly to a person standing in a kitchen. `502` means Mealie specifically —
the two backends fail independently and the user should know which half is down.

**PATCH bodies use `exclude_unset`.** Absent means "leave it alone"; explicit
`null` means "clear it". Collapsing the two is how a partial update wipes a
field.
