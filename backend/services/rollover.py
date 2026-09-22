"""The answer to "does this day have work left on it that is standing on the days before it".

One query and one decision, both narrow. A block is left from yesterday when it is unfinished,
still scheduled, and was on the day immediately before the day being looked at. Nothing here
moves anything: this module says what qualifies, and the two routes that can act on it — a tap on
the rollover row, and the setting that acts by itself — are ordinary writes to `/api/blocks`.

Three kinds of thing are deliberately outside the question:

    a calendar event      `events` is a different table, and an event is context rather than plan
    a routine occurrence  an occurrence is not a row; it is drawn from a rule and a date, so a
                          blocks-only query cannot see one. That is the point: a routine already
                          has an occurrence on today, and rolling yesterday's forward would be
                          the same hour twice on the same day
    a finished block      `done = 0` is part of the predicate

`day IS NOT NULL` is the one clause that reads as redundant and is not. A block with no day is in
the inbox, and an inbox item can never be "yesterday's" — there is no day of its own for it to have
been left on. It is also what makes moving these safe to repeat: the row that is moved to Today, or
back to Anytime, stops matching the predicate the moment it happens, so no marker is needed to
remember that it was already dealt with and none is written.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from services.blocks import row_to_dict

# Unfinished, scheduled, and on this day. Ordered the way the day it was is ordered, so the list
# reads as the plan it was.
UNFINISHED = "SELECT * FROM blocks WHERE day = ? AND done = 0 AND day IS NOT NULL ORDER BY start_min"


def day_before(day: str) -> str:
    """The calendar day before a canonical day. A day is 1440 minutes here, DST included."""
    return (_date.fromisoformat(day) - timedelta(days=1)).isoformat()


def unfinished_on(conn, day: str) -> list[dict]:
    """The blocks left unfinished on this day, in the order they were meant to happen."""
    return [row_to_dict(r) for r in conn.execute(UNFINISHED, (day,))]


def leftover_for(conn, day: str, today: str) -> list[dict]:
    """"Left from yesterday" for the day being looked at — empty for any day but today.

    The section belongs to the day you are in. Yesterday's own page already shows those blocks in
    their own sections, and tomorrow's page is not a place to be told about today, so a day that is
    not today gets an empty list rather than a second version of itself. `today` is an argument
    rather than a call to the clock because the caller already knows it from the request, and a
    function that reads the clock cannot be asked what it would say about a Tuesday in March.
    """
    if day != today:
        return []
    return unfinished_on(conn, day_before(day))
