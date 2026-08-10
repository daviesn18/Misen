"""Consistent SQLite backups via the online backup API.

Runs inside a throwaway `python:3.13-slim` container with the data directories
mounted, so it depends on nothing being installed on the host and works whether
or not the stack is running.

Why not `cp`: a live SQLite database has in-flight pages in the WAL. Copying the
.db file mid-write produces an archive that restores to a corrupt or
silently-stale database. `Connection.backup()` takes a proper consistent
snapshot while writers continue.

Databases are discovered rather than named, because the exact filename Mealie
uses is its business and may change between versions.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SKIP_SUFFIXES = ("-wal", "-shm", "-journal")


def find_databases(root: Path) -> list[Path]:
    """Every *.db under root, excluding SQLite's sidecar files."""
    return sorted(
        p
        for p in root.rglob("*.db")
        if p.is_file() and not any(p.name.endswith(s) for s in SKIP_SUFFIXES)
    )


def backup_one(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Opening read-write: in WAL mode SQLite may need to create a -shm file even
    # to read, so a read-only handle can fail on an otherwise healthy database.
    source = sqlite3.connect(src)
    try:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    # A backup that cannot be read back is not a backup.
    check = sqlite3.connect(dest)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        raise RuntimeError(f"integrity check failed for {dest}: {result}")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: backup_sqlite.py <out_dir> <src_dir> [src_dir ...]", file=sys.stderr)
        return 2

    out_dir = Path(argv[1])
    sources = [Path(a) for a in argv[2:]]

    total = 0
    for src_root in sources:
        if not src_root.is_dir():
            print(f"  ! {src_root} is not a directory, skipping", file=sys.stderr)
            continue

        databases = find_databases(src_root)
        if not databases:
            print(f"  ! no .db files under {src_root}", file=sys.stderr)
            continue

        for db in databases:
            relative = db.relative_to(src_root)
            dest = out_dir / src_root.name / relative
            backup_one(db, dest)
            size_mb = dest.stat().st_size / 1_048_576
            print(f"  ok {src_root.name}/{relative} ({size_mb:.1f} MB)")
            total += 1

    if total == 0:
        print("no databases backed up", file=sys.stderr)
        return 1

    print(f"{total} database(s) backed up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
