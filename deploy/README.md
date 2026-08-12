# Deploying Misen

Everything here is written and validated. What it hasn't been is *run against a
real host* — provisioning, DNS, live TLS, and the restore rehearsal need a VPS
and your hands. This is that runbook.

Phase 0 is done when the last checkbox in [Verify](#verify) is ticked.

---

## Before you start

Three of these block a step partway through, so it is worth having them in hand
rather than discovering it at step 6 with a half-built stack.

**Accounts and access**

- [x] A host — see [step 0](#0-pick-a-host). Oracle Cloud accounts can take a
      few hours to verify, so start that first if you're going that way
- [ ] A domain you can add DNS records to
- [ ] A Claude account per person who will plan meals — planning happens in a
      Claude Project (step 8), billed to that subscription. **No Anthropic API
      key is needed anywhere in this deployment**
- Nothing to sign up for on Mealie's side. It is self-hosted only, and the
      admin account is created by your own instance at [step 5](#5-mealie-first-run)
      from values you put in `.env`

**Decisions** — `provision.py` in step 6 takes these as arguments and there is
no interactive prompt

| | Example |
|---|---|
| Household name | `Davies` |
| Timezone | `America/New_York` — drives week boundaries and reminder times |
| Week starts on | `monday` or `sunday`. Changing it later re-anchors every stored week |
| Each member | `name:initials:color[:role]` — `Nick:N:terracotta`, `Mara:M:green`. Colors: `terracotta`, `green`, `gold`, `plum` |

Reminder day and hour are set per member from the app later, not here.

**Somewhere to keep secrets.** Step 6 prints one token per person, once, and
never again. A password manager entry per member, made before you run it.

---

## 0. Pick a host

Any x86 or ARM box with 2 GB RAM and 25 GB disk. Mealie alone wants ~1 GB, and
its compose block caps it there so the other three services have room.

Every image is multi-arch, so the architecture doesn't change anything below.
If you go with Oracle Cloud's Always Free ARM tier, **upgrade the account to Pay
As You Go on day one** — Always Free resources stay free under PAYG, but PAYG
accounts are exempt from idle reclamation, and a two-person meal planner will
sit under the 20% utilisation threshold essentially always.

### The host this was deployed to

Provisioned and checked against everything above.

| | |
|---|---|
| Instance | `misen-app-server` — Oracle Cloud, US West (San Jose) |
| Shape | `VM.Standard.A1.Flex` — 2 OCPU, 12 GB, ARM |
| Boot volume | 50 GB |
| Image | Oracle Linux 9 |
| Public IP | `64.181.237.139` — reserved |
| SSH | `opc@64.181.237.139`, key only |
| Network | VCN `misen-vcn` (10.0.0.0/16), public subnet `misen-public-subnet` (10.0.0.0/24), internet gateway on the route table |
| Ingress | 80, 443, 22 from `0.0.0.0/0`. No network security groups — the subnet's security list is the only control |
| Egress | `0.0.0.0/0`, all protocols |
| Account | Pay As You Go |

Shape and boot volume both sit inside the Always Free allowance — 4 OCPU and 24
GB across A1 instances, 200 GB of block storage — so the PAYG upgrade buys
exemption from reclamation without turning on a bill.

**Reserve the public IP before pointing DNS at it.** An ephemeral address
survives a reboot but not a stop/start, and all three records in step 2 go stale
the moment it changes.

Port 22 is open to the world here. Oracle Linux 9 ships with password
authentication off, so that rests entirely on the key — defensible, but if you
ever have a static address to work from, narrowing the rule to it costs nothing.

---

## 1. Host prep

```sh
# Docker Engine + compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker
```

On Oracle Linux the convenience script may refuse — Oracle Linux isn't among
the distributions it officially supports. If it bails, add Docker's CE
repository for RHEL 9 and `dnf install docker-ce docker-compose-plugin`
instead; the result is the same.

**Firewall: 80 and 443 only.** Caddy is the sole public entrypoint. Which tool
you use depends on the distribution, and reaching for the wrong one is the
quickest way to a host you cannot reach.

Debian and Ubuntu:

```sh
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
```

Oracle Linux 9, RHEL, Rocky, Alma — these run firewalld, and `ufw` isn't
packaged for them. Installing it from EPEL to follow the line above gives you
two firewalls disagreeing with each other:

```sh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
sudo firewall-cmd --list-all       # confirm http and https before moving on
```

On Oracle Cloud the host firewall is not enough on its own — the VCN security
list also has to allow 80 and 443 inbound, and Oracle's images have shipped
iptables rules that drop them independently of firewalld. Check that layer too:

```sh
sudo iptables -L INPUT -n --line-numbers
```

Instances are unreachable until every layer is open, and the symptom is step 4
looping on certificate errors rather than anything that names the firewall.

**Prove it from outside before going further.** Every layer above can look
correct from the host and still drop traffic at the edge, and the first thing
to discover that would otherwise be Caddy, against a rate limit of 5 failures
per hostname per hour. From your own machine, not the host, and before anything
is listening:

```sh
nc -vz -w 5 <host-ip> 80
nc -vz -w 5 <host-ip> 443
```

Nothing is bound to those ports yet, so neither will connect. What matters is
how it fails:

| Result | Meaning |
|---|---|
| `Connection refused` | The packet reached the host and the OS answered. Every layer is open — proceed. |
| Timeout, no response | Something is dropping it silently: the VCN security list, firewalld, or iptables. Fix before step 4. |

A refusal is the good outcome here. It is the host actively saying nothing is
listening yet, which is exactly true at this point and proves the path is
clear.

---

## 2. DNS

Three A records (plus AAAA if the host has IPv6), all pointing at the host:

| Record | Purpose |
|---|---|
| `mealie.misen.<domain>` | Mealie UI and API |
| `api.misen.<domain>` | Companion API |
| `mcp.misen.<domain>` | MCP server — **must be publicly reachable**, see below |

**Let these propagate before starting the stack.** Caddy requests certificates
on boot, and Let's Encrypt rate-limits failures at 5 per hostname per hour.
Confirm first:

```sh
dig +short api.misen.<domain>    # must return your host's IP
```

Testing against a flaky record? Uncomment `acme_ca` (staging) in the Caddyfile
first — staging certs are untrusted by browsers but aren't rate limited.

**`mcp.` is the one hostname that has to be reachable from the open internet.**
When Claude uses a tool, claude.ai's servers make the request to it — so it
cannot live behind a VPN, a Tailscale-only network, or an IP allowlist. The
other two could, if you ever wanted them to. This is also the record to get
right first: with planning in a Claude Project, `mcp.` being unreachable isn't
one broken feature, it's Claude not being able to see Misen at all.

**No proxying CDN in front of any of them.** A proxy that terminates TLS breaks
the certificate request, and one that buffers responses breaks the MCP stream,
which surfaces as a hang rather than an error. If DNS ever moves to Cloudflare,
these three records must be DNS-only, not orange-clouded.

### The records for this deployment

Domain `stackthelineup.com`, DNS hosted at Squarespace. Added as custom A
records — host on the left, exactly as typed into the panel:

| Host | Type | Data |
|---|---|---|
| `mealie.misen` | A | `64.181.237.139` |
| `api.misen` | A | `64.181.237.139` |
| `mcp.misen` | A | `64.181.237.139` |

Giving `mealie.misen.stackthelineup.com`, `api.misen.stackthelineup.com` and
`mcp.misen.stackthelineup.com`.

Squarespace is registrar and DNS host only — the apex is served from GitHub
Pages, and resolves to its addresses rather than to anything Squarespace runs.
The three records above sit alongside that untouched; none of this changes what
the existing site serves.

Squarespace's lowest available TTL is 30 minutes, so a wrong record is cached
for half an hour rather than the minute a 60s TTL would give you. That is the
argument for checking with `dig` before boot rather than after.

Squarespace is authoritative DNS only, with no proxy layer, so the records
resolve straight to the host. Two things to confirm in the panel: that the
domain's nameservers are still Squarespace's own (records added there do
nothing if the domain is delegated elsewhere), and that no wildcard `*` record
exists that would shadow these.

Squarespace may not expose TTL on custom records. If it doesn't, a wrong value
is expensive to walk back — cached for hours rather than minutes — so verify
with `dig` before starting the stack rather than after, and consider the
staging `acme_ca` line above for the first run.

---

## 3. Configure

```sh
git clone <this repo> misen && cd misen/deploy
cp .env.example .env
```

Fill in `.env`. The ones with no default:

| Key | How |
|---|---|
| `ACME_EMAIL` | Your email — Let's Encrypt expiry notices |
| `MEALIE_DOMAIN` / `API_DOMAIN` / `MCP_DOMAIN` | From step 2 |
| `MEALIE_DEFAULT_EMAIL` | Login for Mealie's first admin account |
| `MEALIE_DEFAULT_PASSWORD` | Its password. Generated by you, used once at step 5, then changed in the UI |
| `MEALIE_PUID` / `MEALIE_PGID` | `id -u` and `id -g` |
| `MEALIE_API_TOKEN` | Minted in step 5, blank for now |
| `DATA_DIR` / `BACKUP_DIR` | Absolute paths, e.g. `/srv/misen/data` |

Create the data directories with ownership matching `MEALIE_PUID:MEALIE_PGID`,
or Mealie will start and fail to write:

```sh
mkdir -p "$DATA_DIR"/{mealie,companion,caddy/data,caddy/config} "$BACKUP_DIR"
sudo chown -R "$(id -u):$(id -g)" "$DATA_DIR"
```

---

## 4. Start

```sh
docker compose config >/dev/null   # validates .env before anything runs
docker compose up -d --build
docker compose ps
docker compose logs -f caddy       # watch the certificates arrive
```

Certificates take 10–30 seconds on a good DNS record. Caddy won't come up until
Companion reports healthy — that dependency is deliberate, so you never serve a
public endpoint that 502s.

```sh
curl https://api.misen.<domain>/health
# {"status":"ok","service":"companion","version":"0.1.0","checks":{"database":"ok"}}
```

---

## 5. Mealie first-run

**There is no account to sign up for anywhere.** Mealie is self-hosted only —
the admin account is created by *your* instance, on its first boot, out of
`MEALIE_DEFAULT_EMAIL` and `MEALIE_DEFAULT_PASSWORD` in `.env`. So this step
cannot happen before step 4; there is nothing to log into until the container
has run once.

1. Open `https://mealie.misen.<domain>` and log in with `MEALIE_DEFAULT_EMAIL`
   and `MEALIE_DEFAULT_PASSWORD`.
2. Change the password immediately, and put the new one in the password manager.
   **`.env` stops being the source of truth the moment you do** — those two keys
   are read only on the boot that creates the admin row, and editing them later
   changes nothing.
3. Confirm signup is closed — `ALLOW_SIGNUP=false` is set, but check the UI.
   Misen provisions members itself; nobody should be able to make an account by
   finding the URL.
4. Profile → API Tokens → Generate. Put it in `.env` as `MEALIE_API_TOKEN`, then
   `docker compose up -d companion mcp` to pick it up — both services read it.

**Mealie has exactly one human user, and that is deliberate.** Members
authenticate to Companion with the tokens minted in step 6, and Companion
reaches Mealie with the single API token above. Nobody else needs a Mealie
login, which is why no SMTP server is configured here: Mealie's invitations and
password-reset emails have nothing to do. The cost of that is a forgotten admin
password needing a reset from the container rather than a "forgot password"
link — so keep it in the password manager.

**The database is SQLite, also deliberate.** Mealie's checklist points at
Postgres for larger installs; for two people SQLite is the better trade, and
`backup.sh` snapshots it through SQLite's online-backup API (see
`backup_sqlite.py`). Moving to Postgres means rewriting the backup and restore
scripts, so it is not a drop-in `.env` change.

If the login screen never appears, or the password is rejected on a *fresh*
install, check what the container actually got:

```sh
docker compose logs mealie
docker compose exec mealie env | grep -E 'BASE_URL|DEFAULT_|ALLOW_SIGNUP'
```

A wrong `BASE_URL` is the usual cause of a UI that loads but cannot log in.

---

## 6. Create the household and its tokens

The Companion database is migrated automatically on every container start, so
by now the schema exists but nobody can log in. Mint the members:

```sh
docker compose exec companion python scripts/provision.py \
    --household "Davies" \
    --timezone America/New_York \
    --week-starts-on monday \
    --member "Nick:N:terracotta" \
    --member "Mara:M:green"
```

Each `--member` is `name:initials:color[:role]`. Colors: `terracotta`, `green`,
`gold`, `plum`. Add a child with `--member "Ivy:I:gold:child"`. `role` is for
display and for recording who cooked; nothing in the API branches on it.

**The tokens print once and are never stored** — only their sha256 goes in the
database. Copy them somewhere safe before closing the terminal. If one is lost,
`--rotate <member_id>` issues a new one and invalidates the old.

Keep them to hand: the same token is what each person pastes into claude.ai in
step 8 to connect the MCP server.

Check one works:

```sh
curl -H "Authorization: Bearer <token>" https://api.misen.<domain>/me
```

For exploring the rest, import [`docs/misen.postman_collection.json`](../docs/misen.postman_collection.json)
and set `base_url` and `token`.

---

## 7. Load the recipes

The library is empty until something puts recipes in it, and an empty library
makes the next two steps hard to judge — Claude has nothing to plan with, and
the shopping list has nothing to build from.

```sh
cd ../scripts
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

export MEALIE_API_TOKEN=<the token from step 5>
python -m recipes import ../docs/recipes/stealth-health-slow-cooker.json \
    --url https://mealie.misen.<domain> --dry-run   # read this first
python -m recipes import ../docs/recipes/stealth-health-slow-cooker.json \
    --url https://mealie.misen.<domain>
```

56 recipes load. Eight more are held back automatically — their pages were
photographed in two columns and came back as fragments; they are listed with
page numbers in
[the review file](../docs/recipes/stealth-health-slow-cooker-review.md) and
want typing in by hand. A further 25 in that cookbook's contents aren't in the
source file at all.

**Re-running is safe.** Existing recipes are skipped, so a run that dies at
number forty finishes the job rather than creating forty duplicates.

Then open one in Mealie and check the ingredients read as they do in the book,
and that the servings count came across — Misen scales from that number, and a
recipe missing it can't be scaled at all.

See [`scripts/README.md`](../scripts/README.md) for other sources.

---

## 8. Connect the Claude Project

Misen has no built-in assistant. Planning happens in a Claude Project on
claude.ai with this deployment's MCP server attached as a connector, so the
conversation is billed to that person's Claude subscription and no API key
exists anywhere on this host.

Before touching claude.ai, prove the endpoint is actually reachable **from off
the host** — a curl run on the box itself proves nothing about what claude.ai
can reach:

```sh
curl -i https://mcp.misen.<domain>/mcp                       # expect 401
curl -i -H "Authorization: Bearer <token>" https://mcp.misen.<domain>/mcp
```

A 401 without the token is the correct answer: it means TLS terminated, Caddy
routed, and the MCP server answered. A timeout means DNS, the firewall, or the
VCN security list — go back to step 1's pre-flight.

Then, in claude.ai:

1. Settings → Connectors → **Add custom connector**.
2. URL: `https://mcp.misen.<domain>/mcp` — the full path, not the bare host.
3. Authenticate with that person's member token from step 6.
4. Create a Project, and enable the Misen connector on it.

Each person uses **their own** member token. The MCP server forwards whatever
token it is given to Companion, so the connector reaches exactly what that
member could reach through the app, and `cooked_by` records the right name.

Ask it something that requires a read, then something that requires a write:

> What's in the pantry?
>
> Plan dinners for next week from our recipes.

Then open Mealie or `GET /menu` and confirm the menu actually persisted. The
write path is the one worth checking by hand — a tool call that silently failed
still leaves Claude sounding confident.

| What happens | What it means |
|---|---|
| claude.ai can't add the connector | `mcp.` isn't reachable from the internet, or the URL is missing `/mcp` |
| Connector added, but every tool call fails | Token rejected. Confirm it with `curl -H "Authorization: Bearer <token>" https://api.misen.<domain>/me` |
| Tools work but the pantry looks empty | The right token for the wrong household, or the pantry genuinely is empty |
| Tool calls hang, then time out | `flush_interval -1` missing from the **mcp** block in the Caddyfile |
| Menu writes report success but nothing persists | Check `docker compose logs companion mcp` — a Mealie or database error surfaces there |

**Auth is a pasted token today, not a sign-in.** OAuth for the connector is the
next piece of work; until it lands, `--rotate` in step 6 is what revokes access,
and it cuts off the app and the connector together.

**Ordering groceries stays optional.** Misen has no Instacart code and no
longer proxies to it. Add Instacart's own MCP server to the same Project as a
second connector — get a key at
[docs.instacart.com](https://docs.instacart.com/developer_platform_api) — and
Claude can build a cart from the list it just made. That credential lives in
the claude.ai account, not on this host.

---

## 9. Backups

```sh
./backup.sh          # run once by hand and read the output
crontab -e
```

```cron
15 3 * * * cd /srv/misen/deploy && ./backup.sh >> /var/log/misen-backup.log 2>&1
```

**Then edit `backup.sh` and uncomment an off-box copy.** Until something in that
block runs, every archive lives on the same disk as the data it protects, and a
disk failure takes both.

---

## 10. Rehearse a restore

This is an acceptance criterion, not an optional extra. An untested backup is a
hope.

```sh
./restore.sh --into /srv/misen-rehearsal
```

It unpacks the newest archive, runs an integrity check on every database, and
refuses to lay anything down if one fails. Then prove Mealie actually reads it:

```sh
DATA_DIR=/srv/misen-rehearsal docker compose up -d mealie
docker compose logs mealie          # should start clean
docker compose stop mealie
rm -rf /srv/misen-rehearsal
```

---

## Verify

Phase 0 is complete when all of these hold:

- [ ] `curl https://api.misen.<domain>/health` returns 200 **from off-network** — not just from the host
- [ ] All three subdomains serve a valid, browser-trusted certificate
- [ ] `docker compose ps` shows companion `healthy`, mealie and caddy `running`
- [ ] Mealie's admin password is changed and signup is closed
- [ ] `./backup.sh` produces an archive and the cron entry exists
- [ ] An off-box copy is configured in `backup.sh`
- [ ] `./restore.sh --into …` completes and a scratch Mealie starts against it
- [ ] `curl -H "Authorization: Bearer <token>" .../me` returns the member you minted
- [ ] `curl -X POST https://mcp.misen.<domain>/mcp` returns **401** from off-network — proof it is reachable and refusing anonymous callers
- [ ] Mealie shows the imported recipes, and one spot-checked recipe has its ingredients and serving count intact
- [ ] The connector is added in claude.ai and lists all thirteen tools
- [ ] Claude can name something that is actually in the pantry
- [ ] Claude can set a menu slot, and it is still there on `GET /menu` afterwards — the write path, checked outside Claude
- [ ] A second member's token resolves to *that* member, not the first one

---

## Operating

```sh
docker compose logs -f companion       # follow one service
docker compose up -d --build companion # rebuild after a code change
docker compose down                    # stop (data survives in DATA_DIR)
docker compose pull && docker compose up -d   # upgrade — see below
```

**Upgrades.** Images are pinned in `docker-compose.yml`, so `pull` alone changes
nothing until you edit a tag. That's intentional: a Mealie major version can run
an irreversible database migration. Back up first, bump the tag deliberately,
and read Mealie's release notes.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Caddy loops on certificate errors | DNS not resolving to this host yet, or 80/443 blocked. On Oracle, check the VCN security list *and* the host firewall — firewalld and iptables both, they can disagree. |
| Mealie exits immediately | `DATA_DIR/mealie` not owned by `MEALIE_PUID:MEALIE_PGID`. |
| Companion `unhealthy`, logs show `unable to open database file` | `DATA_DIR/companion` missing or not writable by uid 10001. |
| Companion exits at boot with an Alembic traceback | A migration failed. It runs before uvicorn on purpose — the app never serves against a schema it doesn't match. Read the traceback, fix, `docker compose up -d --build companion`. |
| Every request returns 401 | No members provisioned yet (step 6), or the token was pasted with a trailing newline. |
| MCP returns 401 even with a good token | It verifies tokens by calling Companion's `/me`. If Companion is unhealthy, nobody can be verified, and 401 is the honest answer. Check `docker compose ps` first. |
| `required variable … is missing a value` | A key in `.env.example` is blank in `.env`. |
| Recipes and shopping 502 while the pantry and menu work | `MEALIE_API_TOKEN` is blank or wrong in `.env` (step 5). Companion stays healthy on purpose — only the Mealie-backed half is down. |
| claude.ai won't add the connector | `mcp.misen.<domain>` isn't reachable from the internet, or the URL is missing the `/mcp` path. Test from off-network — never from the host. |
| Claude's tool calls hang, then time out | `flush_interval -1` missing from the **mcp** block in the Caddyfile. |
| Claude says the pantry is empty when it isn't | Right token, wrong household — or a different member than you think. Check with `curl -H "Authorization: Bearer <token>" .../me`. |
| Ran out of disk | Old archives. Lower `BACKUP_RETAIN_DAYS`, confirm off-box copies are working. |
