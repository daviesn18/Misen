#!/usr/bin/env python3
"""Create a household and its members, and print their tokens once.

    python scripts/provision.py --household "Davies" --member "Nick:N:terracotta" \
                                --member "Mara:M:green"

    python scripts/provision.py --household-id 1 --member "Ivy:I:gold:child"

Each `--member` is `name:initials:color[:role]`, role defaulting to `adult`.
`role` records who someone is, for display and for `cooked_by`; nothing in the
API branches on it.

**The tokens are printed once and never stored.** Only `sha256(token)` goes in
the database, so there is no "show me the token again" — losing one means
running `--rotate` and pasting a new one into that device. At two adults and a
kid this is a two-minute job and does not justify a refresh-token flow.

The same token is what a member pastes into claude.ai when adding the MCP
server as a connector, so `--rotate` cuts off both the app and the connector.

Run it wherever the database is:

    docker compose exec companion python scripts/provision.py …
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# So this runs from a source checkout as well as from inside the image, where
# `app` is installed as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.auth import generate_token, hash_token  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import DAYS, Household, Member  # noqa: E402

VALID_COLORS = ("terracotta", "green", "gold", "plum")


def parse_member(spec: str) -> dict[str, str]:
    parts = spec.split(":")
    if len(parts) not in (3, 4):
        raise SystemExit(f"bad --member {spec!r}: expected name:initials:color[:role]")
    name, initials, color = parts[0], parts[1], parts[2]
    role = parts[3] if len(parts) == 4 else "adult"

    if color not in VALID_COLORS:
        raise SystemExit(f"bad color {color!r}: one of {', '.join(VALID_COLORS)}")
    if role not in ("adult", "child"):
        raise SystemExit(f"bad role {role!r}: adult or child")

    return {"name": name, "initials": initials, "color": color, "role": role}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--household", help="Name of a new household to create")
    parser.add_argument("--household-id", type=int, help="Add members to an existing household")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--week-starts-on", default="monday", choices=DAYS)
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        metavar="name:initials:color[:role]",
        help="Repeatable. Colors: " + ", ".join(VALID_COLORS),
    )
    parser.add_argument(
        "--rotate",
        metavar="MEMBER_ID",
        type=int,
        help="Issue a new token for an existing member, invalidating the old one",
    )
    args = parser.parse_args()

    if not any((args.household, args.household_id, args.rotate)):
        parser.error("give --household, --household-id, or --rotate")

    with Session(engine) as db:
        if args.rotate is not None:
            return rotate(db, args.rotate)

        if args.household:
            household = Household(
                name=args.household,
                timezone=args.timezone,
                week_starts_on=args.week_starts_on,
            )
            db.add(household)
            db.flush()
            print(f"household {household.id}: {household.name}")
        else:
            household = db.get(Household, args.household_id)
            if household is None:
                raise SystemExit(f"no household with id {args.household_id}")
            print(f"household {household.id}: {household.name} (existing)")

        if not args.member:
            db.commit()
            print("\nNo members given. Re-run with --household-id "
                  f"{household.id} --member name:initials:color")
            return 0

        issued: list[tuple[Member, str]] = []
        for spec in args.member:
            fields = parse_member(spec)
            token = generate_token()
            member = Member(
                household_id=household.id,
                name=fields["name"],
                initials=fields["initials"],
                color=fields["color"],
                role=fields["role"],
                token_hash=hash_token(token),
            )
            db.add(member)
            db.flush()
            issued.append((member, token))

        db.commit()
        report(issued)

    return 0


def rotate(db: Session, member_id: int) -> int:
    member = db.get(Member, member_id)
    if member is None:
        raise SystemExit(f"no member with id {member_id}")

    token = generate_token()
    member.token_hash = hash_token(token)
    db.commit()

    print(f"rotated token for {member.name} (member {member.id})")
    print("The previous token stops working immediately.\n")
    report([(member, token)])
    return 0


def report(issued: list[tuple[Member, str]]) -> None:
    width = max(len(m.name) for m, _ in issued)
    print("\n" + "=" * 72)
    print("TOKENS — copy these now. They are not stored and cannot be shown again.")
    print("=" * 72)
    for member, token in issued:
        print(f"  {member.name:<{width}}  id={member.id:<4} {member.role:<5}  {token}")
    print("=" * 72)


if __name__ == "__main__":
    raise SystemExit(main())
