"""Who am I, and who lives here."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.auth import CurrentPrincipal, DbSession
from app.models import Member
from app.schemas import HouseholdOut, MemberOut

router = APIRouter(tags=["household"])


@router.get("/me", response_model=MemberOut)
def me(principal: CurrentPrincipal) -> Member:
    """The calling member. The app hits this at launch to validate its token."""
    return principal.member


@router.get("/household", response_model=HouseholdOut)
def household(principal: CurrentPrincipal, db: DbSession) -> HouseholdOut:
    members = db.execute(
        select(Member)
        .where(Member.household_id == principal.household_id)
        .order_by(Member.id)
    ).scalars().all()

    return HouseholdOut(
        id=principal.household.id,
        name=principal.household.name,
        timezone=principal.household.timezone,
        week_starts_on=principal.household.week_starts_on,
        members=[MemberOut.model_validate(m) for m in members],
    )
