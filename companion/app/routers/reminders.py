"""Plan-the-week reminder preference — PRD §9.

The scheduling itself is local to the device: `UNUserNotificationCenter`, no
APNs, no server-side scheduler. A once-weekly nudge does not justify a push
certificate and a delivery pipeline.

The *preference* still lives here, for two reasons. A reinstall shouldn't
silently lose the reminder, and Basil should be able to say "I'll nudge you
Friday" and have that be true rather than a guess about what the phone is set
to.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.auth import CurrentPrincipal, DbSession
from app.errors import BadRequest
from app.schemas import ReminderOut, ReminderUpdate

router = APIRouter(prefix="/reminders", tags=["reminders"])

DEFAULT_HOUR = 18


@router.get("", response_model=ReminderOut)
def get_reminder(principal: CurrentPrincipal) -> ReminderOut:
    return ReminderOut(
        day=principal.member.plan_reminder_day, hour=principal.member.plan_reminder_hour
    )


@router.put("", response_model=ReminderOut)
def set_reminder(
    body: ReminderUpdate, principal: CurrentPrincipal, db: DbSession
) -> ReminderOut:
    """Set the day and hour, or send `{"day": null}` to switch it off.

    An hour without a day is the one combination that means nothing, so it's
    rejected rather than quietly stored — a preference the server holds but
    can't act on is how you get a reminder that never fires and nobody can
    explain.
    """
    member = principal.member

    if body.day is None:
        if body.hour is not None:
            raise BadRequest("Pick a day for the reminder, or turn it off entirely.")
        member.plan_reminder_day = None
        member.plan_reminder_hour = None
    else:
        member.plan_reminder_day = body.day
        member.plan_reminder_hour = body.hour if body.hour is not None else DEFAULT_HOUR

    db.commit()
    db.refresh(member)
    return ReminderOut(day=member.plan_reminder_day, hour=member.plan_reminder_hour)
