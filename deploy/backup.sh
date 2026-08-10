#!/usr/bin/env bash
#
# Misen nightly backup.
#
#   ./backup.sh
#
# Produces  $BACKUP_DIR/misen-YYYY-mm-dd-HHMMSS.tar.gz  containing:
#   sqlite/companion/…   consistent snapshot of the Companion database
#   sqlite/mealie/…      consistent snapshot of Mealie's database
#   files/mealie/…       everything else in Mealie's data dir — recipe images,
#                        which are the one genuinely unrecoverable asset here
#
# Safe to run while the stack is up. Cron example in deploy/README.md.
#
# This is only half a backup strategy. An archive sitting on the same disk as
# the thing it backs up does not survive losing the disk. Copy it off-box —
# see the OFFSITE hook at the end.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Capture anything set explicitly in the environment before .env is sourced,
# so `DATA_DIR=/somewhere ./backup.sh` wins over the file. This matches how
# docker compose resolves the same variables; the alternative silently ignores
# your override and costs an afternoon to notice.
_ENV_DATA_DIR="${DATA_DIR-}"
_ENV_BACKUP_DIR="${BACKUP_DIR-}"
_ENV_RETAIN="${BACKUP_RETAIN_DAYS-}"

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

DATA_DIR="${_ENV_DATA_DIR:-${DATA_DIR:-./data}}"
BACKUP_DIR="${_ENV_BACKUP_DIR:-${BACKUP_DIR:-./backups}}"
BACKUP_RETAIN_DAYS="${_ENV_RETAIN:-${BACKUP_RETAIN_DAYS:-30}}"
PYTHON_IMAGE="python:3.13-slim"

DATA_DIR="$(cd "$DATA_DIR" 2>/dev/null && pwd || { echo "DATA_DIR not found: $DATA_DIR" >&2; exit 1; })"
mkdir -p "$BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

STAMP="$(date +%Y-%m-%d-%H%M%S)"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/misen-backup-XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

echo "==> Misen backup $STAMP"

# --- 1. Databases, via the SQLite online backup API -------------------------
echo "--> databases"
mkdir -p "$STAGING/sqlite"
docker run --rm \
    -v "$DATA_DIR/companion:/src/companion" \
    -v "$DATA_DIR/mealie:/src/mealie" \
    -v "$STAGING/sqlite:/out" \
    -v "$SCRIPT_DIR/backup_sqlite.py:/backup_sqlite.py:ro" \
    "$PYTHON_IMAGE" \
    python /backup_sqlite.py /out /src/companion /src/mealie

# --- 2. Everything else in Mealie's data dir --------------------------------
# Recipe images above all. Database files are excluded because step 1 already
# captured them properly; a live .db swept into a tar is exactly the corrupt
# artefact this script exists to avoid.
echo "--> files"
mkdir -p "$STAGING/files"
tar -czf "$STAGING/files/mealie.tar.gz" \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' --exclude='*.db-journal' \
    -C "$DATA_DIR" mealie

# --- 3. Seal the archive ----------------------------------------------------
ARCHIVE="$BACKUP_DIR/misen-$STAMP.tar.gz"
tar -czf "$ARCHIVE" -C "$STAGING" .
echo "--> wrote $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# --- 4. Prune ---------------------------------------------------------------
DELETED="$(find "$BACKUP_DIR" -maxdepth 1 -name 'misen-*.tar.gz' -mtime "+$BACKUP_RETAIN_DAYS" -print -delete | wc -l)"
if [[ "$DELETED" -gt 0 ]]; then
    echo "--> pruned $DELETED archive(s) older than ${BACKUP_RETAIN_DAYS}d"
fi

# --- 5. Off-box ------------------------------------------------------------
# Uncomment and adapt one of these. Until something here runs, a disk failure
# takes the backups with it.
#
# rclone copy "$ARCHIVE" remote:misen-backups/
# scp "$ARCHIVE" user@elsewhere:/backups/misen/
# restic backup "$ARCHIVE"

echo "==> done"
