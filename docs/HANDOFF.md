# Handoff — where Misen stands, and what's next

Last updated 2026-08-12. Written to be read cold, from a new session, with no
prior context.

---

## Read this first: the branch topology is a trap

**`main` is a two-line stub.** It contains a README saying "Mise / Meal Planning
& Recipe Book" and nothing else. The real codebase has never been merged down.

```
main                              ← 2-line stub, ignore it
 └── claude/misen-prd-planning-a2iel3   ← the actual codebase
      └── claude/oracle-setup-verify-6mi6cl   ← current work, all deploy + rev 3
```

Consequences:

- **Cloning on the host must specify the branch.** `git clone -b
  claude/oracle-setup-verify-6mi6cl <repo>` — a default clone gets the stub and
  nothing works.
- A PR from this branch targets `claude/misen-prd-planning-a2iel3`, not `main`.
- **No PR has ever been opened on this repo, and nothing has been merged.**

Whether to collapse this chain down to `main` is an open decision — see the end.

---

## What's done

Everything below is committed and pushed to `claude/oracle-setup-verify-6mi6cl`.

| Commit | What |
|---|---|
| `3f64868` | Recorded the provisioned Oracle host; fixed step 1 for Oracle Linux |
| `982dcba` | DNS plan for `stackthelineup.com` |
| `c1476b2` | Outside-in firewall pre-flight; corrected the apex to GitHub Pages |
| `aa36b95` | **Remove Basil** |
| `a2343cf` | **Docs for the Claude Project** (PRD rev 3, runbook, Postman) |

### The architecture change, in one paragraph

Misen was specced with **Basil** — an in-app chat tab backed by a server-side
proxy to the Anthropic Messages API. That was removed. Planning now happens in a
**Claude Project on claude.ai** with Misen's MCP server attached as a custom
connector. The thirteen MCP tools already covered the workflow and needed no
change. PRD decision 7 had anticipated exactly this and deferred only the auth
work. Full reasoning is in [`PRD.md`](PRD.md) §7.

What this did *not* change: the Oracle server is still required. Mealie holds
the recipes, Companion owns pantry/menu/shopping state, and `mcp.` must be
publicly reachable so claude.ai's servers can call it. If anything that
hostname matters more now — it is the only way Claude can see Misen at all.

### Verified state of the code

Re-runnable; these all passed at the time of writing:

```sh
cd companion && uv sync --all-extras && uv run pytest -q   # 136 passed
cd companion && uv run ruff check .                        # clean
cd mcp       && uv sync --all-extras && uv run pytest -q   # 51 passed
cd mcp       && uv run ruff check .                        # clean
cd companion && uv run alembic check                       # no drift from models
```

Also confirmed: the app boots and `/health` returns 200 with `ANTHROPIC_API_KEY`
unset, `alembic upgrade head` produces exactly `households, members,
menu_entries, pantry_items`, and `provision.py` issues tokens against a fresh
migrated database.

---

## What's next

### 1. Deploy to the host — blocked on nothing but hands

Phase 0 is code-complete and has never been run against a real machine. Follow
[`deploy/README.md`](../deploy/README.md); it is written to be standalone.

Outstanding, all user-side on the box at `opc@64.181.237.139`:

- [ ] Install Docker. **On Oracle Linux 9 the `get.docker.com` script may
      refuse** — fall back to the Docker CE repo for RHEL 9 plus
      `dnf install docker-ce docker-compose-plugin`
- [ ] Open the firewall with **`firewall-cmd`, not `ufw`.** Oracle Linux 9 is
      RHEL-derived and runs firewalld; `ufw` is not packaged for it, and
      installing it from EPEL gives you two firewalls disagreeing
- [ ] Check `iptables -L INPUT -n` too — Oracle images have shipped rules that
      drop 80/443 independently of firewalld
- [ ] Clone with `-b claude/oracle-setup-verify-6mi6cl` (see above)
- [ ] `mkdir -p /srv/misen/{data,backups}` with ownership matching PUID/PGID
- [ ] Fill and place `deploy/.env` — copy from `deploy/.env.example`, which is
      current. Three values need filling: `ACME_EMAIL`, `MEALIE_DEFAULT_EMAIL`,
      and later `MEALIE_API_TOKEN` (minted in step 5)
- [ ] Terminate the stray reserved IP `147.224.9.3` — created accidentally
      during the console walkthrough, attached to nothing, and billable

**Run the outside-in pre-flight before starting Caddy.** From your own machine,
not the host, before anything is listening:

```sh
nc -vz -w 5 64.181.237.139 80
nc -vz -w 5 64.181.237.139 443
```

`Connection refused` is the *good* outcome — the packet reached the host and the
OS answered, so every layer is open. A timeout means something is dropping
silently. Getting this wrong burns Let's Encrypt's rate limit of 5 failures per
hostname per hour.

### 2. OAuth for the connector — the real next build task

Until this lands, each member pastes their own bearer token into claude.ai as
the connector credential. That works. OAuth removes the paste.

**Two facts to establish first.** Neither could be checked from the container
this was planned in — its network policy blocked outbound HTTPS. Both change the
shape of the work, and both are cheap to look up:

1. **What claude.ai's custom connectors require for auth.** The plan assumed
   OAuth 2.1 + PKCE, Protected Resource Metadata (RFC 9728) for discovery, and
   Dynamic Client Registration (RFC 7591), with no static-token option. **If a
   bearer/header option exists, most of this collapses to configuration.**
2. **FastMCP's current auth API.** The plan assumed an `OAuthProxy` presenting a
   DCR-capable face while using a fixed upstream registration, plus JWT
   verification helpers. Class names may differ.

**The design constraint that matters.** `mcp/app/auth.py` is deliberately
stateless: it verifies a caller's token with `GET /me` against Companion and
forwards that same token on every call, so the MCP server holds no credentials
and reaches exactly what its caller could. The naive OAuth implementation breaks
this — an OAuth access token isn't a Companion token, so the MCP server would
need a store mapping identity to member credentials, reintroducing the second
secret store that file's docstring explains was deliberately avoided.

**Avoid it by teaching Companion to accept both.** Companion's auth dependency
resolves *either* a member bearer token *or* an OAuth JWT to a `Member`. The MCP
server keeps doing exactly what it does now; `CompanionTokenVerifier` needs no
changes at all.

Work implied by that approach:

- `companion/`: add `email` to `Member` (unique within a household); extend
  `provision.py --member` to carry it; in `app/auth.py`, when the credential is
  a JWT, verify against the provider's JWKS, match the verified email claim to a
  member, reject unknown emails. **Keep member tokens working** — the iOS app
  uses them, and so does `--rotate`.
- `mcp/`: configure the upstream provider (Google is the obvious pick — both
  members have accounts, and identity ties to a real account rather than a
  pasted string); serve `/.well-known/oauth-protected-resource`; return a
  `WWW-Authenticate` challenge on unauthenticated calls so claude.ai can
  discover the authorization server.
- `deploy/`: new `.env` keys for the OAuth client; confirm the Caddy `mcp` block
  doesn't swallow the `.well-known` path.

The database has still never been created, so schema changes remain free — edit
the initial migration in place, as `aa36b95` did, rather than stacking
migrations. **This stops being true the moment the host is deployed.** If
deployment happens first, OAuth's schema change needs a real migration.

**The risk worth naming:** the failure that matters in auth work is not a broken
login, it's one member's credential resolving to the *other* member. The
acceptance test is running the whole workflow as the second member and
confirming they get their own identity.

### 3. Acceptance test for the pivot

Not runnable until the host is up. In a Project with the connector attached:

1. *"What's in the pantry?"* → `get_pantry_items` returns real rows
2. *"Plan dinners for next week from our recipes."* → `search_recipes` +
   `get_recipe`, then `set_weekly_menu` per night
3. **Open Mealie or `GET /menu` and confirm the menu actually persisted.** The
   write path is the one most likely to fail silently — a tool call that failed
   still leaves Claude sounding confident
4. *"Build the shopping list."* → `build_shopping_list`, pantry items skipped
5. Repeat as the second member; confirm they get their own identity

---

## Facts worth not rediscovering

**The host.** Oracle Cloud, instance `misen-app-server`, US West (San Jose),
`VM.Standard.A1.Flex` 2 OCPU / 12 GB ARM, 50 GB boot, Oracle Linux 9. SSH
`opc@64.181.237.139`, key only. VCN `misen-vcn` (10.0.0.0/16), subnet
`misen-public-subnet` (10.0.0.0/24). Ingress 80/443/22 from `0.0.0.0/0`, no
NSGs. **Pay As You Go is live** — this matters, PAYG accounts are exempt from
idle reclamation and a two-person meal planner would otherwise sit under the
20% utilisation threshold permanently. The IP is **reserved**, not ephemeral.

**DNS.** Domain `stackthelineup.com`, registered and DNS-hosted at Squarespace.
Three A records added and confirmed resolving to `64.181.237.139`:
`mealie.misen`, `api.misen`, `mcp.misen`. **Squarespace's TTL floor is 30
minutes** — verify records with `dig` *before* starting Caddy, because a mistake
is cached for half an hour. The apex and `www` are served by **GitHub Pages**
(`185.199.108–111.153`), not Squarespace; leave them alone.

**A sandbox artifact that produced a false positive.** A TCP connect test from
the dev container showed `64.181.237.139:80` and `:443` as OPEN before anything
was deployed. This was wrong — the sandbox intercepts those ports and completes
handshakes locally. It was caught by testing the *unattached* stray IP
`147.224.9.3`, which also came back "open". **Port reachability cannot be tested
from the dev container.** Use `nc -vz` from a real machine.

**Outbound HTTPS is blocked in the dev container** (proxy returns 403 to
CONNECT), so live reachability checks and doc lookups aren't possible from
there. DNS resolution *does* work — `getent hosts` is fine.

---

## Open decisions

- **Merge down to `main`?** `main` is still the two-line stub. The whole project
  lives on two stacked feature branches. Nothing forces a decision, but the
  longer it waits the stranger the repo looks to anyone new — including the
  clone step in the runbook, which has to name a branch.
- **Open a PR?** None exists. If one is opened it targets
  `claude/misen-prd-planning-a2iel3`.
- **Does planning in a separate app hold up?** This is the bet rev 3 makes and
  it can't be settled in advance. PRD §13 flags it as the main open question:
  if planning stops happening because it means leaving Misen, the answer is not
  to rebuild Basil but to ask what the Menu tab could do on its own.
