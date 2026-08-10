#!/usr/bin/env bash
#
# Misen restore.
#
#   ./restore.sh                          rehearse the newest archive into a scratch dir
#   ./restore.sh backups/misen-….tar.gz   rehearse a specific archive
#   ./restore.sh --into /srv/misen-test   rehearse into a chosen directory
#   ./restore.sh --force                  restore in place, over live data
#
# Rehearsing is the default on purpose. An untested backup is a hope, and the
# only way to find out an archive is bad is to unpack it and look — which you
# want to do on a scratch directory at a calm moment, not over production at a
# panicked one.
#
# The rehearsal is a phase 0 acceptance criterion. Run it once before trusting
# any of this.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Explicit environment beats .env — see the note in backup.sh.
_ENV_DATA_DIR="${DATA_DIR-}"
_ENV_BACKUP_DIR="${BACKUP_DIR-}"

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

BACKUP_DIR="${_ENV_BACKUP_DIR:-${BACKUP_DIR:-./backups}}"
DATA_DIR="${_ENV_DATA_DIR:-${DATA_DIR:-./data}}"
PYTHON_IMAGE="python:3.13-slim"

ARCHIVE=""
TARGET=""
FORCE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --into)    TARGET="$2"; shift 2 ;;
        --force)   FORCE=1; shift ;;
        -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
        *)         ARCHIVE="$1"; shift ;;
    esac
done

# --- Pick an archive --------------------------------------------------------
if [[ -z "$ARCHIVE" ]]; then
    ARCHIVE="$(ls -1t "$BACKUP_DIR"/misen-*.tar.gz 2>/dev/null | head -n1 || true)"
    [[ -n "$ARCHIVE" ]] || { echo "no archives found in $BACKUP_DIR" >&2; exit 1; }
    echo "==> newest archive: $ARCHIVE"
fi
[[ -f "$ARCHIVE" ]] || { echo "not a file: $ARCHIVE" >&2; exit 1; }
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

# --- Decide where it lands --------------------------------------------------
if [[ "$FORCE" -eq 1 ]]; then
    TARGET="${TARGET:-$DATA_DIR}"
    echo
    echo "  !! IN-PLACE RESTORE"
    echo "  !! This overwrites live data in: $TARGET"
    echo "  !! Stop the stack first:  docker compose down"
    echo
    read -r -p "  Type 'restore' to continue: " CONFIRM
    [[ "$CONFIRM" == "restore" ]] || { echo "aborted"; exit 1; }
else
    TARGET="${TARGET:-./restore-rehearsal-$(date +%Y%m%d-%H%M%S)}"
    echo "==> rehearsing into $TARGET (live data untouched)"
fi

mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/misen-restore-XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

echo "--> unpacking"
tar -xzf "$ARCHIVE" -C "$STAGING"

# --- Verify before touching the target --------------------------------------
echo "--> verifying databases"
docker run --rm \
    -v "$STAGING/sqlite:/sqlite:ro" \
    -v "$SCRIPT_DIR/verify_sqlite.py:/verify_sqlite.py:ro" \
    "$PYTHON_IMAGE" \
    python /verify_sqlite.py /sqlite

# --- Lay it down ------------------------------------------------------------
# The files archive was created with `tar -C "$DATA_DIR" mealie`, so it already
# contains a top-level `mealie/` directory and unpacks straight into TARGET.
echo "--> restoring files"
if [[ -f "$STAGING/files/mealie.tar.gz" ]]; then
    tar -xzf "$STAGING/files/mealie.tar.gz" -C "$TARGET"
fi

# Databases go on top, overwriting the excluded placeholders if any exist.
mkdir -p "$TARGET/companion" "$TARGET/mealie"
if [[ -d "$STAGING/sqlite/companion" ]]; then
    cp -a "$STAGING/sqlite/companion/." "$TARGET/companion/"
fi
if [[ -d "$STAGING/sqlite/mealie" ]]; then
    cp -a "$STAGING/sqlite/mealie/." "$TARGET/mealie/"
fi

echo
echo "==> restored to $TARGET"
if [[ "$FORCE" -eq 1 ]]; then
    echo "    Fix ownership before starting, or Mealie will fail to write:"
    echo "      sudo chown -R ${MEALIE_PUID:-1000}:${MEALIE_PGID:-1000} \"$TARGET/mealie\""
    echo "      docker compose up -d"
else
    echo "    Rehearsal only — live data was not touched."
    echo "    To prove Mealie actually reads it, point a scratch stack at this dir:"
    echo "      DATA_DIR=\"$TARGET\" docker compose up -d mealie"
    echo "    Then clean up:  rm -rf \"$TARGET\""
fi
