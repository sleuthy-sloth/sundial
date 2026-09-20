"""iCalendar in, the local event model out — and blocks back into iCalendar.

Pure functions: no network, no database. The transports call in here (CalDAV for
iCloud, the REST API for Google), so all the fiddly conversion lives in one place
and is testable against fixtures.

Three decisions worth knowing:

* Every event is stored as an **absolute instant** (UTC) plus an all-day flag. Local
  wall-clock time is what you see; the instant is what survives a DST change. A
  series spanning a change would otherwise move by an hour twice a year.
* A recurring master is stored **once**, with its RRULE, and expanded when a day is
  read. Materialised occurrences go stale the moment the series is edited.
* The master's **raw ICS is kept**, because expansion has to happen in the timezone
  that object names. Rebuilding an event from columns loses it.

(Not named ``calendar.py`` on purpose: that shadows the standard library module of
the same name for every dependency in the venv.)
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent


@lru_cache(maxsize=1)
def server_tz() -> ZoneInfo:
    """The zone that floating times (no TZID, no Z) belong to.

    Defaults to the machine's own timezone rather than a hard-coded one, and can be
    pinned with SUNDIAL_TZ for a box that keeps UTC while the person does not.
    """
    named = os.environ.get("SUNDIAL_TZ")
    if named:
        return ZoneInfo(named)
    local = datetime.now().astimezone().tzinfo
    key = getattr(local, "key", None)
    return ZoneInfo(key) if key else ZoneInfo("UTC")


def _utc(value, default_tz: Optional[ZoneInfo] = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=default_tz or server_tz())
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        # An all-day event is a date, not an instant. Anchoring it at UTC midnight
        # keeps it comparable; the UI renders it as a strip and ignores the time.
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    raise TypeError(f"cannot read a datetime from {value!r}")


def _is_all_day(value) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _text(component: IEvent, field: str) -> str:
    value = component.get(field)
    return "" if value is None else str(value)


def _span(component: IEvent) -> tuple[datetime, datetime]:
    """DTSTART plus DTEND, DURATION, or the RFC defaults when neither is given."""
    dtstart = component.get("DTSTART")
    if dtstart is None:
        raise ValueError("VEVENT without DTSTART")
    start = dtstart.dt
    end = component.get("DTEND")
    if end is not None:
        return _utc(start), _utc(end.dt)
    duration = component.get("DURATION")
    if duration is not None:
        return _utc(start), _utc(start + duration.dt)
    # RFC 5545: a timed event with no end lasts zero; an all-day one lasts a day.
    return _utc(start), _utc(start + (timedelta(days=1) if _is_all_day(start) else timedelta(0)))


def event_id(calendar_ref: str, uid: str, recurrence_id: str = "") -> str:
    return f"{calendar_ref}|{uid}|{recurrence_id}"


def parse_ics(ics_text: str) -> list[IEvent]:
    return [c for c in ICalendar.from_ical(ics_text).walk("VEVENT")]


def events_from_ics(
    ics_text: str,
    calendar_ref: str,
    provider: str,
    now: Optional[str] = None,
) -> tuple[list[dict], list[str]]:
    """Read a calendar object into rows, plus the uids it says are cancelled.

    Returns (rows, cancelled_uids). A cancelled instance is not a row — it is an
    instruction to remove one.
    """
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict] = []
    cancelled: list[str] = []

    for component in parse_ics(ics_text):
        uid = _text(component, "UID")
        if not uid:
            continue
        status = (_text(component, "STATUS") or "CONFIRMED").upper()
        if status == "CANCELLED":
            cancelled.append(uid)
            continue

        start, end = _span(component)
        dtstart = component.get("DTSTART").dt
        rrule = component.get("RRULE")
        recurrence_id = component.get("RECURRENCE-ID")
        sequence = component.get("SEQUENCE")
        recurrence = str(recurrence_id.dt) if recurrence_id is not None else ""

        rows.append(
            {
                "id": event_id(calendar_ref, uid, recurrence),
                "calendar_ref": calendar_ref,
                "provider": provider,
                "uid": uid,
                "recurrence_id": recurrence,
                "title": _text(component, "SUMMARY") or "(no title)",
                "location": _text(component, "LOCATION"),
                "notes": _text(component, "DESCRIPTION"),
                "start_utc": start.isoformat(timespec="seconds"),
                "end_utc": end.isoformat(timespec="seconds"),
                "all_day": 1 if _is_all_day(dtstart) else 0,
                "rrule": rrule.to_ical().decode() if rrule is not None else None,
                "raw_ics": component.to_ical().decode(),
                "status": status,
                "etag": _text(component, "X-SUNDIAL-ETAG") or None,
                "sequence": int(sequence) if sequence is not None else 0,
                "updated_at": now,
            }
        )
    return rows, cancelled


def block_to_ics(block: dict, *, tzid: Optional[str] = None, stamp: Optional[str] = None) -> bytes:
    """A block as a VEVENT. The same bytes go to CalDAV PUT and to Google, which is
    the point of generating iCalendar here rather than per provider.

    The UID is the block's own id, so a re-push updates the same event instead of
    making a second one.
    """
    if block.get("start_min") is None or block.get("day") is None:
        raise ValueError("only a scheduled block can be pushed to a calendar")

    zone = ZoneInfo(tzid) if tzid else server_tz()
    start = datetime.fromisoformat(f"{block['day']}T00:00:00").replace(tzinfo=zone)
    start += timedelta(minutes=int(block["start_min"]))
    end = start + timedelta(minutes=int(block["duration_min"]))

    event = IEvent()
    event.add("uid", f"{block['id']}@sundial")
    event.add("summary", block["title"])
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.fromisoformat(stamp) if stamp else datetime.now(timezone.utc))
    if block.get("notes"):
        event.add("description", block["notes"])

    calendar = ICalendar()
    calendar.add("prodid", "-//sundial//day planner//EN")
    calendar.add("version", "2.0")
    calendar.add_component(event)
    return calendar.to_ical()


def remote_wins(local: dict, remote: dict) -> bool:
    """Which side of a conflict to keep, for the fields a calendar owns.

    A higher SEQUENCE wins; then the later timestamp; a tie goes to the local edit,
    because he is the one looking at the screen.
    """
    if remote["sequence"] != local["sequence"]:
        return remote["sequence"] > local["sequence"]
    return remote["updated_at"] > local["updated_at"]


# The fields a remote change is allowed to own. Anything outside this list — colour,
# done, and the notes he typed into sundial — is never overwritten.
CALENDAR_OWNED = (
    "title", "location", "notes", "start_utc", "end_utc",
    "all_day", "rrule", "status", "etag", "sequence", "updated_at",
)


def fields_a_calendar_owns(row: dict) -> dict:
    """The subset a remote change may overwrite.

    Only keys the remote actually carries: a partial row (some providers omit an
    empty field) must not blank out a value we already hold.
    """
    return {key: row[key] for key in CALENDAR_OWNED if key in row}


def merge_remote(local: Optional[dict], remote: dict) -> dict:
    """What to store, given what is already there. Pure, so the rules are testable."""
    if local is None:
        return remote
    merged = dict(local)
    if remote_wins(local, remote):
        merged.update(fields_a_calendar_owns(remote))
    else:
        # Keep the remote's bookkeeping anyway, so the next sync does not see the
        # same change as new every time.
        merged["etag"] = remote.get("etag")
    return merged


def expand_series(row: dict, window_start: datetime, window_end: datetime) -> list[dict]:
    """The occurrences of a stored series inside a window.

    Expands the ICS the server gave us rather than rebuilding an event from columns:
    a weekly 09:00 event has to stay at 09:00 across a DST change, and only the
    original calendar object knows which timezone that means. The import is lazy
    because expansion only happens on the read path.
    """
    import recurring_ical_events  # noqa: PLC0415

    if not row.get("rrule") or not row.get("raw_ics"):
        return [dict(row)]

    calendar = ICalendar.from_ical(row["raw_ics"])
    out: list[dict] = []
    for occurrence in recurring_ical_events.of(calendar).between(window_start, window_end):
        start, end = _span(occurrence)
        dtstart = occurrence.get("DTSTART").dt
        out.append(
            {
                **row,
                "start_utc": start.isoformat(timespec="seconds"),
                "end_utc": end.isoformat(timespec="seconds"),
                "all_day": 1 if _is_all_day(dtstart) else 0,
            }
        )
    return out
