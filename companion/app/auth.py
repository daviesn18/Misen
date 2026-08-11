"""Bearer token → (member, household). The whole tenancy story starts here.

PRD §4: tenant isolation is enforced in one place, not in every handler. This
is that place. `current_principal` is the only thing that turns a request into
a household, and no route may take a household id as a parameter — a request
that could name a household could name the wrong one.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import Forbidden, Unauthorized
from app.models import Household, Member

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """sha256 hex of a bearer token. The only form the token ever takes at rest.

    No salt and no KDF, deliberately: these are 32 random bytes, not passwords.
    There is no dictionary to attack, so stretching buys nothing and would cost
    a KDF round on every single request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """A fresh member token. Printed once by provision.py, then never again."""
    return secrets.token_urlsafe(TOKEN_BYTES)


@dataclass(frozen=True)
class Principal:
    """Who is calling, and which household's data they can see."""

    member: Member
    household: Household

    @property
    def household_id(self) -> int:
        return self.household.id

    @property
    def member_id(self) -> int:
        return self.member.id


def bearer_token(request: Request) -> str:
    """The raw token as presented.

    Public because Basil needs it: `mcp_servers[].authorization_token` sends
    the caller's own token to Anthropic so the MCP server can be called back
    with the caller's exact reach. It is deliberately *not* carried on
    `Principal` — only the one route that forwards it should have to touch it.
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("Add this device to the household first.")
    return token.strip()


def current_principal(
    request: Request, db: Annotated[Session, Depends(get_db)]
) -> Principal:
    token = bearer_token(request)
    member = db.execute(
        select(Member).where(Member.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if member is None:
        raise Unauthorized()

    household = db.get(Household, member.household_id)
    if household is None:
        # A member row pointing at a missing household means someone deleted a
        # household without its members. Refuse rather than serve an untenanted
        # request — this is exactly the state isolation bugs live in.
        raise Unauthorized("This account is not set up correctly.")

    return Principal(member=member, household=household)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
DbSession = Annotated[Session, Depends(get_db)]


def require_basil(principal: CurrentPrincipal) -> Principal:
    """Capability gate for the chat routes (phase 5).

    Enforced server-side, always. The app hides the tab for members without it,
    but hiding a button is a courtesy, not a control.
    """
    if not principal.member.can_use_basil:
        raise Forbidden("Basil isn't available on this account.", code="basil_not_allowed")
    return principal
