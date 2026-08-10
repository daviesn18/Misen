# Running Mise on a Synology NAS (instead of a VPS)

Notes on what changes if the home server becomes a Synology NAS rather than a
rented VPS — and what else the box can earn its keep doing (computer backups,
Home Assistant, media).

**Assumptions.** Mise is a containerised web app (app container + Postgres),
deployed with Docker Compose, used by you and a handful of family members
rather than the public internet. If any of that is wrong, the networking and
uptime sections are the parts that shift.

---

## 1. The short version

A NAS is not a cheaper VPS. It's a different trade, and the trade only pays if
you actually want the other four jobs:

| | VPS | Synology NAS |
|---|---|---|
| Uptime | Someone else's problem | Your power, your ISP, your DSM reboots |
| Public access | Trivial, static IP | Needs a tunnel or DDNS + care |
| Cost | ~$6/mo forever | ~$1,300 up front, ~$5/mo power |
| Bulk storage | Expensive per GB | The entire point |
| Blast radius of a mistake | Rebuild the droplet | Your family photos are on it |

So the recommendation is a split, not a swap:

- **Buy the NAS** for backups, Home Assistant, and media. Those three justify
  it on their own; Mise doesn't.
- **Run Mise on the NAS** if it stays family-only — put it behind Tailscale and
  never open a port. This is the setup I'd pick.
- **Keep Mise on a small VPS** only if you want strangers (or a future public
  beta) hitting it reliably. In that case the NAS becomes its backup target and
  staging environment, which is a genuinely nice arrangement.

The failure mode worth naming up front: consolidating everything onto one box
means a DSM update that requires a reboot takes down your recipes, your lights,
and your movies at the same time. That's fine for a household. It's not fine if
someone else depends on it.

---

## 2. Buying in 2026 — three gotchas

The Synology landscape got worse in 2025 and only partly recovered. Check all
three of these against the exact model before ordering.

**a) The drive lock is mostly, not entirely, lifted.**
2025 Plus models (DS925+, DS425+, DS1525+, DS1825+) originally refused to
create storage pools on third-party drives. DSM 7.3 (October 2025) walked that
back — Seagate/WD NAS drives work again, though DSM marks them "unverified" and
nags. **The M.2 NVMe slots are still locked to Synology-branded SSDs**, so
budget for Synology NVMe if you want a read/write cache, or plan to skip cache
entirely (for this workload, skip it — more RAM helps more).

**b) Hardware transcoding is broken on the 2025 series.**
This is the big one for the media use case.
- The DS925+ uses an AMD Ryzen V1500B, which has **no integrated GPU at all**.
  No Plex/Jellyfin hardware transcoding, full stop. Transcoding falls to the
  CPU and can peg it over 90%.
- On the Intel-based 2025 models, reports are that Synology removed the kernel
  graphics driver Plex/Jellyfin rely on, so QuickSync doesn't work out of the
  box even where the silicon supports it.

If everything you own direct-plays (Apple TV, modern smart TVs, Plex clients on
the LAN), this genuinely doesn't matter. If you want to stream to phones on
mobile data, or you have subtitle burn-in, it matters a lot. Two honest ways
out: buy a UGREEN DXP or TerraMaster with an Intel QuickSync CPU instead, or
buy the Synology for storage and add a ~$150 N100 mini PC to run Plex against
an SMB mount. The second option is the one I'd take — it also gets Home
Assistant off the NAS, which fixes a separate problem (see §4b).

**c) Container Manager needs a Plus-series x86 model.**
The J/Value/ARM models can't run Docker at all. That rules them out entirely
for Mise. Current pricing: DS225+ ~$330 (2-bay), DS425+ ~$520 (4-bay),
DS925+ ~$639 (4-bay).

**Sizing I'd land on:** a 4-bay Plus model, two drives to start in SHR (~1 disk
of redundancy), leaving two bays for later expansion. RAM to 16GB minimum if
you're running Home Assistant in a VM plus a handful of containers — the stock
4GB will not be enough. Note DSM only officially blesses Synology RAM, but
third-party SODIMMs are widely used.

---

## 3. What actually changes for Mise

The `docker-compose.yml` is ~90% portable. The friction is around it:

| Concern | On a VPS | On DSM |
|---|---|---|
| Compose | Current Docker CLI | Container Manager ships an older Compose; some v3 keys and newer syntax get rejected. Test locally against its version. |
| Deploys | `git pull && docker compose up -d` over SSH | Same, but SSH is off by default and DSM updates can restart the daemon under you |
| File permissions | You own the filesystem | Bind mounts land in shared folders with DSM's UID/GID; Postgres will complain about data-dir ownership until you match it |
| Scheduled jobs | cron / systemd timers | DSM Task Scheduler (it can run as root, which is how you get backups working) |
| TLS | certbot | DSM's cert manager + free Let's Encrypt via a `yourname.synology.me` DDNS name. Don't run certbot yourself; DSM will fight you. |
| Ports | Yours | DSM squats on 80/443/5000/5001 for its own UI and reverse proxy. Put Mise on a high port and front it with DSM's built-in reverse proxy. |
| Postgres backups | `pg_dump` to object storage | `pg_dump` sidecar → a `/backups/mise` shared folder → Hyper Backup off-site. **Btrfs snapshots of a running Postgres are not a substitute for a dump.** |

Rough shape:

```
/volume1/docker/mise/          # compose file, .env
/volume1/docker/mise/pgdata/   # Postgres data (bind mount)
/volume1/backups/mise/         # nightly pg_dump output, then Hyper Backup off-site
```

Ingress: Container Manager exposes Mise on e.g. `:8080` → DSM Reverse Proxy
maps `mise.yourname.synology.me` → `localhost:8080` with the Let's Encrypt cert
attached. Then either Tailscale (family-only, nothing exposed) or a Cloudflare
Tunnel container (public, still nothing exposed) in front. **Do not port-forward
443 to a NAS that also holds your photos and backups** — the whole point of the
consolidation is that this box is now high-value.

---

## 4. The other four jobs

### a) Computer backups — the strongest case for the box

- **Active Backup for Business** (free, Plus series): full disk-image backups of
  Windows and macOS clients, with dedup across machines and central management.
  Faster and more manageable than Time Machine.
- **Time Machine over SMB** as a belt-and-braces second method for Macs — it's a
  shared folder with a quota, takes ten minutes to set up.
- **Synology Drive** for continuous sync of working files (the "I deleted it an
  hour ago" case, which image backups are bad at).

Run ABB *and* Time Machine. They fail differently.

### b) Home Assistant — works, with one real caveat

Virtual Machine Manager runs Home Assistant OS properly (full add-on store,
Supervisor, the works). 2 vCPU / 4GB RAM / 32GB disk is a comfortable
allocation; 2GB is the floor.

Two things to plan for:

1. **USB passthrough for Zigbee/Z-Wave dongles is flaky in VMM** and breaks
   across DSM updates. Use a network-attached Zigbee coordinator (SLZB-06 or
   similar, Ethernet/PoE) instead. This is the standard workaround and it's
   better anyway — the coordinator can sit centrally in the house rather than
   in whatever cupboard holds the NAS.
2. **DSM updates reboot Home Assistant.** Your lights and locks go down when you
   patch your file server. If HA ends up running anything you'd miss at 2am,
   move it to a dedicated mini PC — which is the same mini PC that solves the
   transcoding problem in §2b.

### c) Movie storage — easy, with the transcoding asterisk

Shared folder `/volume1/media`, Plex or Jellyfin in Container Manager, done.
Direct play is flawless. Re-read §2b before assuming transcoding works.

Rough capacity math: ~4GB per 1080p film, ~25GB per 4K film. 10TB usable holds
roughly 400 4K films or a lot more 1080p. Plan for the drives to be the
expensive part of this project, not the enclosure.

### d) Everything else it quietly absorbs

Photo library (Synology Photos), document scanning, an ad-blocking DNS
container, a Git remote mirror, Immich if you'd rather not use Synology Photos.
This is where the value actually accumulates.

---

## 5. Backups — the NAS is not a backup

RAID protects against a dead drive. It does not protect against ransomware, a
bad `rm`, a failed PSU taking the array with it, or the house burning down. The
whole point of moving your data home is that you now own this problem.

Minimum viable 3-2-1:

1. **Btrfs snapshots** (Snapshot Replication) on the shared folders that matter,
   hourly for `/docker` and `/homes`. Immutable-ish and instant to restore —
   this is your ransomware and oops insurance.
2. **Hyper Backup → Backblaze B2** (~$6/TB/month) for `/homes`, `/docker`,
   `/backups`, and photos. Encrypted client-side. Do *not* back up the media
   library to B2 — it's re-acquirable and it's 90% of your bytes.
3. **A UPS.** Non-negotiable with a NAS. DSM has native UPS support and will
   shut down gracefully on low battery; an unclean shutdown mid-write is how
   Btrfs volumes get interesting.
4. **Test a restore.** Once, deliberately, before you need it.

---

## 6. Cost, honestly

Five-year view, USD, rough:

| | VPS only | NAS |
|---|---|---|
| Hardware | — | ~$640 NAS + ~$450 (2×12TB) + ~$130 UPS |
| RAM upgrade | — | ~$60 |
| Running cost | ~$6/mo = $360 | ~$60/yr power = $300, + B2 ~$3/mo = $180 |
| **5-year total** | **~$360** | **~$1,760** |

The NAS is roughly 5× the cost if Mise is the only thing on it. It becomes the
obvious choice the moment you price the alternatives for the *other* jobs:
Backblaze/iCloud for two computers, cloud photo storage, and a media library
you don't have to keep re-renting. Judge it as a home-infrastructure purchase,
not as VPS arbitrage — the arbitrage argument doesn't hold and it's not the
real reason to want one.

---

## 7. What I'd actually do

1. **Buy a 4-bay Plus model + 2 drives + a UPS.** Leave two bays empty.
2. **Week one: backups only.** ABB against both computers, Time Machine, a
   Hyper Backup job to B2, snapshots on. Get the boring, high-value thing done
   and verified before anything fun.
3. **Week two: media.** Shared folder, Plex/Jellyfin, confirm direct play on
   every client you care about.
4. **Week three: Mise in Container Manager**, reachable over Tailscale only.
   Nightly `pg_dump` into `/backups/mise` via Task Scheduler, which Hyper Backup
   is already shipping off-site.
5. **Home Assistant last**, in VMM, with a network Zigbee coordinator — or on a
   separate mini PC if by then you've decided you want HA and Plex insulated
   from DSM reboots.
6. **Only open Mise to the internet** when someone outside the house actually
   needs it, and do it with a Cloudflare Tunnel rather than a port forward.

## 8. Open questions

- Family-only, or do you want Mise publicly reachable eventually? This decides
  Tailscale vs Cloudflare Tunnel, and whether the VPS stays in the picture.
- Does anything in the house need transcoding today, or does everything direct
  play? This decides Synology-only vs Synology + N100 mini PC.
- Is Home Assistant going to run anything safety-critical (locks, heating)? If
  yes, it shouldn't live on the same box as the file server.

---

### Sources

Drive policy reversal: [NAS Compares](https://nascompares.com/news/synology-reverse-the-hard-drive-policy-in-dsm-7-3-we-win/),
[How-To Geek](https://www.howtogeek.com/synology-is-walking-back-its-drive-requirements/),
[NAS Marketplace](https://nasmarketplace.com.au/pages/synology-dsm-7-3-updates-drive-compatibility-product-direction-2026).
Transcoding: [Neowin DS925+ review](https://www.neowin.net/reviews/synology-ds925-review-a-look-after-backtracking-on-locking-out-unapproved-drives/),
[blackvoid](https://www.blackvoid.club/synology-ds925-review/),
[XDA](https://www.xda-developers.com/brought-back-hardware-transcoding-on-my-synology-nas/),
[ubnas](https://ubnas.com/en/posts/best-nas-for-jellyfin/).
Models/pricing/Container Manager: [Need to Know IT](https://needtoknowit.com.au/blog/synology-nas-lineup-every-current-model-price-and-spec/).
Home Assistant on VMM: [HA community guide](https://community.home-assistant.io/t/installation-on-synology-virtual-machine-manager/281608).
Active Backup macOS: [blackvoid](https://www.blackvoid.club/synology-active-backup-for-business-macos-1-year-later/).
