"""Week arithmetic, in one place.

The client never does timezone math (PRD §5) — which only works if the server
is rigorous about it. "This week" depends on two household settings: the
timezone that decides what day it is, and `week_starts_on` that decides where
the week begins. Both live on the household row, and every date in an API
response is computed here.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import DAYS

DAY_INDEX = {name: i for i, name in enumerate(DAYS)}  # monday == 0, matching date.weekday()


def day_name(value: date) -> str:
    return DAYS[value.weekday()]


def today_in(timezone_name: str) -> date:
    """The household's current date.

    A UTC server serving an America/New_York household is wrong about what day
    it is for five hours out of every twenty-four, which is exactly the window
    in which someone plans dinner.
    """
    try:
        tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        # A bad timezone string shouldn't take the menu down. UTC is wrong by
        # a few hours; a 500 is wrong all the way.
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def day_start_utc(timezone_name: str, day: date) -> datetime:
    """Naive-UTC instant at which `day` began in the household's timezone.

    Daily counters (Basil's message cap) have to roll over at the household's
    midnight, not the server's. Comparing against a UTC date would give a New
    York household a day that ends at 8pm.
    """
    try:
        tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    local_midnight = datetime.combine(day, time.min, tzinfo=tz)
    return local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def week_start_for(value: date, week_starts_on: str) -> date:
    """The start of the week containing `value`, per the household's setting."""
    start_index = DAY_INDEX[week_starts_on]
    delta = (value.weekday() - start_index) % 7
    return value - timedelta(days=delta)


def current_week_start(timezone_name: str, week_starts_on: str) -> date:
    return week_start_for(today_in(timezone_name), week_starts_on)


def week_days(week_start: date) -> list[tuple[str, date]]:
    """The seven (day_name, date) pairs of a week, in order from its start."""
    return [
        (day_name(week_start + timedelta(days=offset)), week_start + timedelta(days=offset))
        for offset in range(7)
    ]


def is_valid_week_start(value: date, week_starts_on: str) -> bool:
    return day_name(value) == week_starts_on
