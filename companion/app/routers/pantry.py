"""Pantry — PRD §5.

Note what "used" means here: a timestamp, not a delete. `PATCH {"used": true}`
sets `used_at`, the item drops out of the default view, and it stays queryable
for a while because "we finished the salmon Tuesday" is context worth having
on Wednesday. `DELETE` is the other thing — the undo path for an item added by
mistake — and it really does remove the row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentPrincipal, DbSession
from app.errors import BadRequest, NotFound
from app.models import PantryItem, utcnow
from app.schemas import Location, PantryItemCreate, PantryItemOut, PantryItemUpdate

router = APIRouter(prefix="/pantry", tags=["pantry"])


def _get_owned(db: Session, household_id: int, item_id: int) -> PantryItem:
    """Fetch by id *and* household. Never by id alone.

    A handler that looks a row up by primary key and then checks ownership
    leaks existence through the difference between 403 and 404. Filtering on
    both in the query means a neighbouring household's item is simply not
    there.
    """
    item = db.execute(
        select(PantryItem).where(
            PantryItem.id == item_id, PantryItem.household_id == household_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFound("That item isn't in the pantry.")
    return item


@router.get("", response_model=list[PantryItemOut])
def list_items(
    principal: CurrentPrincipal,
    db: DbSession,
    location: Annotated[Location | None, Query()] = None,
    include_used: Annotated[bool, Query()] = False,
) -> list[PantryItem]:
    query = select(PantryItem).where(PantryItem.household_id == principal.household_id)
    if location:
        query = query.where(PantryItem.location == location)
    if not include_used:
        query = query.where(PantryItem.used_at.is_(None))

    # Expiring first — the whole reason to look at a pantry list is to notice
    # what needs using. Items without a date sort after those with one.
    return list(
        db.execute(
            query.order_by(
                PantryItem.used_at.is_(None).desc(),
                PantryItem.expiry_date.is_(None),
                PantryItem.expiry_date,
                PantryItem.name,
            )
        ).scalars().all()
    )


@router.post("", response_model=PantryItemOut, status_code=status.HTTP_201_CREATED)
def add_item(
    body: PantryItemCreate, principal: CurrentPrincipal, db: DbSession
) -> PantryItem:
    item = PantryItem(
        household_id=principal.household_id,
        name=body.name,
        quantity=body.quantity,
        unit=body.unit,
        location=body.location,
        expiry_date=body.expiry_date,
        added_by=principal.member_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=PantryItemOut)
def update_item(
    item_id: int, body: PantryItemUpdate, principal: CurrentPrincipal, db: DbSession
) -> PantryItem:
    item = _get_owned(db, principal.household_id, item_id)
    fields = body.model_dump(exclude_unset=True)

    if not fields:
        raise BadRequest("Nothing to update.")

    # `used` is a verb, not a column. Everything else maps straight across.
    if "used" in fields:
        item.used_at = utcnow() if fields.pop("used") else None

    for key, value in fields.items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, principal: CurrentPrincipal, db: DbSession) -> Response:
    """A real delete — the undo path for a mis-added item.

    "We finished it" is `PATCH {"used": true}`. Conflating the two would throw
    away the history that makes the pantry worth reading.
    """
    item = _get_owned(db, principal.household_id, item_id)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
