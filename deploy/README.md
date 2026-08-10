# Deploying Misen

Everything here is written and validated. What it hasn't been is *run against a
real host* — provisioning, DNS, live TLS, and the restore rehearsal need a VPS
and your hands. This is that runbook.

Phase 0 is done when the last checkbox in [Verify](#verify) is ticked.

---

## 0. Pick a host

Any x86 or ARM box with 2 GB RAM and 25 GB disk. Mealie alone wants ~1 GB, and
its compose block caps it there so the other three services have room.

Every image is multi-arch, so the architecture doesn't change anything below.
If you go with Oracle Cloud's Always Free ARM tier, **upgrade the account to Pay
As You Go on day one** — Always Free resources stay free under PAYG, but PAYG
accounts are exempt from idle reclamation, and a two-person meal planner will
sit under the 20% utilisation threshold essentially always.

---

## 1. Host prep

```sh
# Docker Engine + compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker

# Firewall: 80 and 443 only. Caddy is the sole public entrypoint.
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
sudo ufw --force enable
```

On Oracle Cloud, `ufw` is not enough — the VCN security list also has to allow
80 and 443 inbound, and Oracle images ship iptables rules that drop them.
Instances are unreachable until both layers are open.

---

## 2. DNS

Three A records (plus AAAA if the host has IPv6), all pointing at the host:

| Record | Purpose |
|---|---|
| `mealie.misen.<domain>` | Mealie UI and API |
| `api.misen.<domain>` | Companion API |
| `mcp.misen.<domain>` | MCP server — create it now, it stays unused until phase 3 |

**Let these propagate before starting the stack.** Caddy requests certificates
on boot, and Let's Encrypt rate-limits failures at 5 per hostname per hour.
Confirm first:

```sh
dig +short api.misen.<domain>    # must return your host's IP
```

Testing against a flaky record? Uncomment `acme_ca` (staging) in the Caddyfile
first — staging certs are untrusted by browsers but aren't rate limited.

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
| `MEALIE_PUID` / `MEALIE_PGID` | `id -u` and `id -g` |
| `MCP_TOKEN` | `openssl rand -base64 32` |
| `ANTHROPIC_API_KEY` | console.anthropic.com — phase 5, can stay blank now |
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

1. Open `https://mealie.misen.<domain>` and log in with `MEALIE_DEFAULT_EMAIL`
   and the password Mealie printed in its logs on first boot
   (`docker compose logs mealie | grep -i password`).
2. Change the password immediately.
3. Confirm signup is closed — `ALLOW_SIGNUP=false` is set, but check the UI.
   Misen provisions members itself; nobody should be able to make an account by
   finding the URL.
4. Profile → API Tokens → Generate. Put it in `.env` as `MEALIE_API_TOKEN`, then
   `docker compose up -d companion` to pick it up.

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
`gold`, `plum`. Add a child with `--member "Ivy:I:gold:child"` — children are
created with Basil switched off.

**The tokens print once and are never stored** — only their sha256 goes in the
database. Copy them somewhere safe before closing the terminal. If one is lost,
`--rotate <member_id>` issues a new one and invalidates the old.

Check one works:

```sh
curl -H "Authorization: Bearer <token>" https://api.misen.<domain>/me
```

For exploring the rest, import [`docs/misen.postman_collection.json`](../docs/misen.postman_collection.json)
and set `base_url` and `token`.

---

## 7. Backups

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

## 8. Rehearse a restore

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
| Caddy loops on certificate errors | DNS not resolving to this host yet, or 80/443 blocked. On Oracle, check the VCN security list *and* the instance's iptables. |
| Mealie exits immediately | `DATA_DIR/mealie` not owned by `MEALIE_PUID:MEALIE_PGID`. |
| Companion `unhealthy`, logs show `unable to open database file` | `DATA_DIR/companion` missing or not writable by uid 10001. |
| Companion exits at boot with an Alembic traceback | A migration failed. It runs before uvicorn on purpose — the app never serves against a schema it doesn't match. Read the traceback, fix, `docker compose up -d --build companion`. |
| Every request returns 401 | No members provisioned yet (step 6), or the token was pasted with a trailing newline. |
| `required variable … is missing a value` | A key in `.env.example` is blank in `.env`. |
| Recipes and shopping 502 while the pantry and menu work | `MEALIE_API_TOKEN` is blank or wrong in `.env` (step 5). Companion stays healthy on purpose — only the Mealie-backed half is down. |
| Basil replies arrive all at once instead of streaming | `flush_interval -1` missing from the api block in the Caddyfile. |
| Ran out of disk | Old archives. Lower `BACKUP_RETAIN_DAYS`, confirm off-box copies are working. |
