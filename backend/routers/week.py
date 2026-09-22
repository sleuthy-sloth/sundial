"""How loaded a span of days is — the week the day sits in."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from clock import today
from services import routines
from services.scheduling import day_span, validate_day
from store import db

router = APIRouter()


@router.get("/api/week")
def get_week(start: Optional[str] = None, days: int = 7) -> dict:
    """How loaded each day is — what the week strip shows.

    Routines count here for the same reason they count in the day: the number this reports is
    what the day is spoken for, and a week that said Monday was empty while Monday's page showed
    the gym twice a week would be two views of one week disagreeing.
    """
    days = max(1, min(days, 31))
    start = start or today()
    validate_day(start)
    span = day_span(start, days)
    with db() as conn:
        rows = conn.execute(
            """SELECT day, COUNT(*) AS blocks, SUM(duration_min) AS minutes
               FROM blocks
               WHERE day BETWEEN ? AND ?
               GROUP BY day""",
            (span[0], span[-1]),
        ).fetchall()
        occurrences = routines.occurrences_between(conn, span)
    load = {r["day"]: (r["blocks"], r["minutes"] or 0) for r in rows}
    for day, found in occurrences.items():
        blocks, minutes = load.get(day, (0, 0))
        load[day] = (blocks + len(found), minutes + sum(o["duration_min"] for o in found))
    return {
        "start": span[0],
        "days": [
            {"day": d, "blocks": load.get(d, (0, 0))[0], "minutes": load.get(d, (0, 0))[1]}
            for d in span
        ],
    }
