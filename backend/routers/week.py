"""How loaded each day is — the week the day sits in.

The week is a capacity reading rather than a calendar grid: for each day, how much of it is
spoken for, how much is left, and how much of that is your plan. The arithmetic lives in
`services.scheduling` so this route and the day view cannot describe the same day differently,
and the calendar's contribution is unioned with the plan rather than added to it — an
appointment and a block sharing an hour is one hour.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter

import calendar_service
import calendar_sync
from clock import today
from services import routines
from services.scheduling import day_span, day_stats, validate_day
from store import db

router = APIRouter()


def _window(span: list[str], zone) -> tuple[datetime, datetime]:
    """The instants a span of days covers, for the calendar's own query.

    Half-open, so the last day is included and the morning after it is not. A span whose last day
    is the last day on the calendar has no morning after it to end at, and that is clamped rather
    than raised on: the week is answerable, it simply cannot have a calendar event inside it that
    starts later than the end of time.
    """
    first = datetime.fromisoformat(f"{span[0]}T00:00:00").replace(tzinfo=zone)
    last = datetime.fromisoformat(f"{span[-1]}T00:00:00").replace(tzinfo=zone)
    try:
        return first, last + timedelta(days=1)
    except OverflowError:
        return first, datetime.max.replace(tzinfo=zone)


@router.get("/api/week")
def get_week(start: Optional[str] = None, days: int = 7) -> dict:
    """How loaded each day is — what the week view reads.

    Routines count here for the same reason they count in the day: the number this reports is
    what the day is spoken for, and a week that said Monday was empty while Monday's page showed
    the gym twice a week would be two views of one week disagreeing.

    `blocks` and `minutes` are the shape this route has always answered with, and they stay:
    `minutes` is the sum of the durations, which is what a strip of bars wants and is not what
    the day holds when two blocks overlap. Everything a capacity reading needs is added beside
    them — planned, open, counts and the calendar's own busy time, all unioned. The two numbers
    disagree only where a plan overlaps itself, and that is exactly the case worth showing.
    """
    days = max(1, min(days, 31))
    start = start or today()
    validate_day(start)
    span = day_span(start, days)
    zone = calendar_sync.server_tz()

    with db() as conn:
        rows = conn.execute(
            """SELECT day, start_min, duration_min, done
               FROM blocks
               WHERE day BETWEEN ? AND ?
               ORDER BY day, start_min""",
            (span[0], span[-1]),
        ).fetchall()
        occurrences = routines.occurrences_between(conn, span)

    # Everything the day's own page would put on the clock, in one list per day, so the two
    # views are counting the same things rather than two similar-looking queries. Rows become
    # plain mappings here: the arithmetic is handed values, not a database.
    scheduled: dict[str, list] = {day: [] for day in span}
    for row in rows:
        scheduled[row["day"]].append(dict(row))
    for day, found in occurrences.items():
        scheduled[day].extend(found)

    # Read once for the whole span rather than per day: a series master is one row whose rule
    # reaches into any of the seven, and the expansion is what trims it to this window.
    events = calendar_service.events_between(*_window(span, zone))

    out = []
    for day in span:
        stats = day_stats(day, scheduled[day], events, zone)
        out.append(
            {
                **stats,
                "blocks": stats["block_count"],
                "minutes": sum(b["duration_min"] for b in scheduled[day]),
            }
        )
    return {"start": span[0], "days": out}
