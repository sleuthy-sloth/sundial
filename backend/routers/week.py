"""How loaded a span of days is — the week the day sits in."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from clock import today
from services.scheduling import day_span, validate_day
from store import db

router = APIRouter()


@router.get("/api/week")
def get_week(start: Optional[str] = None, days: int = 7) -> dict:
    """How loaded each day is — what the week strip shows."""
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
    load = {r["day"]: (r["blocks"], r["minutes"] or 0) for r in rows}
    return {
        "start": span[0],
        "days": [
            {"day": d, "blocks": load.get(d, (0, 0))[0], "minutes": load.get(d, (0, 0))[1]}
            for d in span
        ],
    }
