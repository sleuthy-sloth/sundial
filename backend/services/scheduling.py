"""The day rules: what a day is, whether a block fits inside one, and what a day is made of.

The day is this app's unit — a block is placed in one, an event is fetched for one, the week
strip counts them — so "is this a day", "does this fit" and "how full is it" are asked from
more than one route. They are stated once here, and a route reads as the request it is
answering.

A refusal is raised as `HTTPException` where the rule is known. That is deliberate: the status
and the sentence are part of what this API promises, and a rule that returns a code for
somebody else to turn into one is how the two drift apart.

The arithmetic below is the other convention, and the difference is the point. Nothing in it
raises: it returns values, and a caller with a sentence to write writes it. A refusal here would
mean an unreadable row could take a whole week down instead of one day being reported empty.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional, Sequence

from fastapi import HTTPException

# The minutes in a day. A block is placed in minutes past midnight, so this is the ceiling
# both for a start and for a start plus a duration.
DAY_MIN = 1440

# A busy stretch, as half-open minutes past midnight: [from, to). A block ending at 10:00 and
# one starting at 10:00 do not overlap, which is the whole reason the end is not included.
Span = tuple[int, int]


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


# ---- what a day is made of -----------------------------------------------------------------
# The arithmetic behind "how full is this day", kept pure and kept here so the week view and
# the day's own tally cannot disagree about it. A block nested inside another is not two hours
# of your life, and an hour your calendar and your plan share is one hour.
#
# The merge rule is the frontend's `occupied()` — `span.from <= last.to`, so overlapping, nested
# AND merely touching spans are one stretch — written down a second time on purpose. The day
# view does this in the browser and the week view does it here; if they ever disagree about the
# same day, the person reading both is the one who finds out.


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """The busy stretches, sorted, with overlaps and touches merged.

    Merging is not tidying. A block nested inside another ends earlier than its parent, so the
    gap that appears to follow it is time that is already spoken for: without this, a full
    afternoon reads as free.
    """
    merged: list[Span] = []
    for start, end in sorted((int(s), int(e)) for s, e in spans if e > s):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def union_minutes(spans: Iterable[Span]) -> int:
    """How much of a day a set of spans takes up, each minute counted once."""
    return sum(end - start for start, end in merge_spans(spans))


def block_spans(blocks: Iterable[Mapping]) -> list[Span]:
    """The blocks that are on a clock, as spans.

    An inbox item has no hour — the table's own CHECK keeps `day` and `start_min` empty
    together — so it sits on no timeline and counts towards no day. A row that has a day but
    no hour yet is skipped here for the same reason from the other side: it has been put
    somewhere without being given a time, so it takes up no minutes. Reading its missing hour
    as midnight would invent a stretch of planned time nobody planned.
    """
    return [
        (b["start_min"], b["start_min"] + b["duration_min"])
        for b in blocks
        if b.get("start_min") is not None and (b.get("duration_min") or 0) > 0
    ]


def _instant(value) -> Optional[datetime]:
    """A stored timestamp, or None if it is not one. Unreadable is not worth an exception
    here: one bad row should cost its own event, not the week it sits in."""
    if not value:
        return None
    try:
        found = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    # The column is `start_utc`, so a row stored without an offset is read as UTC rather than
    # as this machine's zone: an old row must not move by an hour when the zone changes.
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def event_spans(events: Iterable[Mapping], day: str, zone) -> list[Span]:
    """The calendar's events placed on one day's clock, in minutes past local midnight.

    Events are stored as instants; a day is a wall clock, so each one is measured from that
    day's own midnight and clamped to it. An appointment running in from yesterday comes out
    negative and clamps at zero rather than landing at a confident wrong hour — the same thing
    the day view does in the browser (`appointments()`), for the same reason.

    An all-day event is a date rather than an instant — `calendar_sync` anchors it at UTC
    midnight — so it has no hour to sit at and takes the whole of the day it is dated.
    """
    midnight = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=zone)
    spans: list[Span] = []
    for event in events:
        if event.get("all_day"):
            if str(event.get("start_utc", ""))[:10] == day:
                spans.append((0, DAY_MIN))
            continue
        start, end = _instant(event.get("start_utc")), _instant(event.get("end_utc"))
        if start is None or end is None:
            continue
        # Real elapsed time from this day's midnight, not wall-clock arithmetic: the hours a
        # zone gains or loses are hours of the day, and an event either side of one has to
        # keep the length it actually had.
        start_min = round((start - midnight).total_seconds() / 60)
        end_min = round((end - midnight).total_seconds() / 60)
        start_min, end_min = max(0, min(DAY_MIN, start_min)), max(0, min(DAY_MIN, end_min))
        if end_min > start_min:
            spans.append((start_min, end_min))
    return spans


def day_stats(day: str, blocks: Sequence[Mapping], events: Sequence[Mapping], zone) -> dict:
    """Everything a day in the week view knows about itself.

    `open_minutes` is the day minus ONE union of everything on it — not the day minus the plan
    minus the calendar. Your block and an appointment can share an hour, and subtracting them
    separately counts that hour of your life twice and calls it free.

    Completed blocks stay in the plan: they happen where they happen, and the day view has
    always counted a finished block's time as spent rather than as room to fill.
    """
    scheduled = [b for b in blocks if b.get("start_min") is not None]
    plan = block_spans(scheduled)
    calendar = event_spans(events, day, zone)
    return {
        "day": day,
        # A week where a busy Wednesday is described as 165 minutes when 120 of them are the
        # same ninety minutes twice is a week that lies about the only thing it reports.
        "planned_minutes": union_minutes(plan),
        "open_minutes": max(0, DAY_MIN - union_minutes([*plan, *calendar])),
        # Counted over every row on the day, not only the ones with an hour. A block can be put
        # on a day before it is given a time, and it is still a block on that day; what it must
        # not do is contribute minutes, because a missing hour read as midnight would invent
        # hours of planned time that nobody planned.
        "block_count": len(blocks),
        "completed_count": sum(1 for b in blocks if b.get("done")),
        "calendar_busy_minutes": union_minutes(calendar),
    }
