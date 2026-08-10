"""Verify every SQLite database under a directory is readable and intact.

Used by restore.sh to check an unpacked archive before any of it is laid down
over a target directory. Kept as a file rather than an inline `python -c` so
the quoting is not load-bearing and the logic can be read and tested.
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys

SKIP_SUFFIXES = ("-wal", "-shm", "-journal")


def main(argv: list[str]) -> int:
    root = pathlib.Path(argv[1] if len(argv) > 1 else "/sqlite")

    databases = sorted(
        p
        for p in root.rglob("*.db")
        if p.is_file() and not any(p.name.endswith(s) for s in SKIP_SUFFIXES)
    )
    if not databases:
        print(f"  FAIL no databases found under {root}", file=sys.stderr)
        return 1

    failed = False
    for db in databases:
        label = db.relative_to(root)

        # A file that is not a database at all raises rather than returning a
        # bad integrity result. Report it like any other failure — a traceback
        # in a cron log tells you less than one clear line.
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                status = con.execute("PRAGMA integrity_check").fetchone()[0]
                tables = con.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
                ).fetchone()[0]
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            print(f"  FAIL {label}: unreadable — {exc}", file=sys.stderr)
            failed = True
            continue

        if status != "ok":
            print(f"  FAIL {label}: {status}", file=sys.stderr)
            failed = True
        elif tables == 0:
            # Structurally valid but empty. Restoring this over live data would
            # silently wipe it, so treat it as a failure rather than a curiosity.
            print(f"  FAIL {label}: no tables — archive is likely truncated", file=sys.stderr)
            failed = True
        else:
            print(f"  ok {label} — {tables} tables")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
