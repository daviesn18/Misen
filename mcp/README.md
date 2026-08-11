# MCP server

The thirteen tools Basil calls. [PRD §6](../docs/PRD.md) is the spec.

FastMCP over streamable HTTP. It calls Companion and Mealie internally; a model
never sees the seam.

## The two things worth knowing before changing anything

**It is stateless and holds no member credentials.** The bearer token a caller
presents is the member's own Companion token. Verification is a `GET /me`
against Companion, and every tool call forwards that same token onward — so
this server can reach exactly what its caller could reach and nothing more.
There is no database, no token store, and no `household_id` parameter on any
tool. Scope comes from the token or it doesn't exist.

This simplifies PRD §10, which had the MCP server holding its own per-member
token. A second token per member is a second secret store, a second rotation
path, and a second thing to fall out of sync — for identical blast radius,
since the tool surface covers most of the API anyway. Rotation is
`provision.py --rotate`, and it invalidates both paths at once.

**The tool descriptions are the product.** Vague descriptions are the single
biggest reason a model misuses or ignores a tool. Each docstring in
`app/server.py` is the PRD's wording close to verbatim and is prescriptive
about *when* to call the tool, not just what it does.
`tests/test_auth.py::test_descriptions_still_match_the_prd` fails if they drift
apart, and the fix is to update both — they are meant to stay one thing.

## Layout

| Path | What |
|---|---|
| `app/server.py` | The thirteen tools and their descriptions |
| `app/shaping.py` | Companion's JSON → what a model reads well. Pure. |
| `app/clients.py` | The only code that talks to Companion or Mealie |
| `app/auth.py` | Token verification, delegated to Companion |

## Running it

```sh
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

export MISEN_COMPANION_URL=http://localhost:8000
export MISEN_MEALIE_URL=http://localhost:9000
export MISEN_MEALIE_TOKEN=<a Mealie API token>

.venv/bin/uvicorn app.main:app --port 8001
```

The endpoint is `/mcp`. It answers 401 to anything without a valid member
token, including the healthcheck — which is why the container's healthcheck
uses `http.client` and accepts any status rather than only a 200.

## Tests

```sh
.venv/bin/pytest        # 50 tests, no network
.venv/bin/ruff check .
```

Companion and Mealie are faked at the HTTP layer with `httpx.MockTransport`, so
the real client code runs — URL building, header injection, status handling,
error-message extraction. The tools are driven over the MCP protocol against
the ASGI app rather than called as Python functions, so argument validation and
the auth middleware are exercised too.

Two things about the test setup that will otherwise cost an afternoon:

- **The lifespan must run.** It starts FastMCP's session manager. Without it
  every request fails with a task-group error that looks nothing like the real
  problem.
- **`connect()` and `raw()` are factories, not async fixtures.** anyio cancel
  scopes are task-bound and pytest-asyncio does not guarantee an async
  generator fixture tears down in the task that set it up, which surfaces as
  "attempted to exit cancel scope in a different task" long after the
  assertions have passed.

## Deployment

Public reachability is not optional for this service. When Basil uses a tool,
**Anthropic's servers make the request to `mcp.misen.<domain>`** — so unlike
Companion, it cannot sit behind a VPN or a private network. That is the single
constraint that decides where Misen can be hosted.
