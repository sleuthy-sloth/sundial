"""The day rules: what a day is, and whether a block fits inside one.

The day is this app's unit — a block is placed in one, an event is fetched for one, the week
strip counts them — so "is this a day" and "does this fit" are asked from more than one route.
They are stated once here, and a route reads as the request it is answering.

A refusal is raised as `HTTPException` where the rule is known. That is deliberate: the status
and the sentence are part of what this API promises, and a rule that returns a code for
somebody else to turn into one is how the two drift apart.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from fastapi import HTTPException

# The minutes in a day. A block is placed in minutes past midnight, so this is the ceiling
# both for a start and for a start plus a duration.
DAY_MIN = 1440


def validate_day(day: str) -> None:
    """Only the canonical 'YYYY-MM-DD' gets through.

    Python's parser also takes the compact 'YYYYMMDD', which used to be stored exactly
    as sent — and then matched no day or week query, because that string sorts outside
    every canonical range. A block nobody can find is worse than a refused request, so
    the shape is checked here instead of trusted from the parser.
    """
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise HTTPException(400, f"day must be YYYY-MM-DD, got {day!r}")
    try:
        _date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, f"day must be YYYY-MM-DD, got {day!r}") from None


def check_fits(start_min: int, duration_min: int) -> None:
    if start_min + duration_min > DAY_MIN:
        raise HTTPException(400, "block runs past midnight — shorten it")


def day_span(start: str, days: int) -> list[str]:
    """The days a span covers, in order, first to last.

    A start near the end of the calendar reaches past it. That is a refusal with a sentence
    in it rather than an OverflowError and a 500.
    """
    first = _date.fromisoformat(start)
    try:
        return [(first + timedelta(days=i)).isoformat() for i in range(days)]
    except OverflowError:
        raise HTTPException(400, "that range runs past the end of the calendar") from None
