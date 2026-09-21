"""The sync engine: credentials in, transport called, rules applied, database written.

This is the only module that touches both the network and the database. It is deliberately
the smallest of the three, because everything fiddly is already separated out — the ICS
conversion and conflict rules have no network, the transport has no database, and what is
left here is the order of operations and the two rules that stop a bad sync from eating
events (see `_reconcile`).

Read-only: nothing here writes to a calendar. `calendar_sync.block_to_ics` exists for the
day pushing is worth doing, and is not called.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from caldav import CalDavClient, CalDavError, Credentials, NotConfigured, load_credentials
from store import db

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "icloud.env"

WINDOW_BACK_DAYS = 7
WINDOW_FORWARD_DAYS = 60
STALE_AFTER_SECONDS = 15 * 60

# The fields a person means by "it changed". etag, sequence and updated_at move on every
# sync and are bookkeeping, so counting them would report changes that did not happen.
CONTENT_FIELDS = ("title", "location", "notes", "start_utc", "end_utc", "all_day", "rrule", "status")

EVENT_COLUMNS = (
    "id", "calendar_ref", "provider", "uid", "recurrence_id", "title", "location", "notes",
    "start_utc", "end_utc", "all_day", "rrule", "raw_ics", "status", "etag", "sequence",
    "updated_at",
)


def config_path() -> Path:
    return Path(os.environ.get("SUNDIAL_ICLOUD_ENV", DEFAULT_CONFIG))


def configuration() -> tuple[Optional[Credentials], str]:
    """(credentials, why not). Read fresh every time, so pasting a password into the file
    is enough — a service restart to pick up a credential is a bad trade for a home box."""
    try:
        return load_credentials(config_path()), ""
    except NotConfigured as exc:
        return None, str(exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(stamp: Optional[str]) -> Optional[datetime]:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Outcome:
    ref: str
    name: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: bool = False
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "ref": self.ref,
            "name": self.name,
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "error": self.error,
        }


# --------------------------------------------------------------------- reading back


def calendars() -> list[dict]:
    """What we know, with how many events each holds."""
    with db() as conn:
        rows = conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM events e WHERE e.calendar_ref = c.ref) AS events
               FROM calendars c ORDER BY c.name"""
        ).fetchall()
    return [dict(r) for r in rows]


def last_sync() -> Optional[str]:
    with db() as conn:
        row = conn.execute("SELECT MAX(last_sync) AS at FROM calendars").fetchone()
    return row["at"]


def events_between(start: datetime, end: datetime) -> list[dict]:
    """Stored events overlapping a window, series expanded, earliest first.

    A recurring master is stored once with its start wherever it started, so it has to be
    read whenever its rule reaches into the window — the expansion is what trims it.
    """
    start_iso, end_iso = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
    with db() as conn:
        rows = conn.execute(
            """SELECT e.* FROM events e
               JOIN calendars c ON c.ref = e.calendar_ref
               WHERE c.enabled = 1
                 AND ((e.start_utc < ? AND e.end_utc > ?) OR (e.rrule IS NOT NULL AND e.start_utc < ?))
               ORDER BY e.start_utc""",
            (end_iso, start_iso, end_iso),
        ).fetchall()

    import calendar_sync as cs  # noqa: PLC0415  (lazy: only the read path needs recurrence)

    out: list[dict] = []
    for row in rows:
        out.extend(cs.expand_series(dict(row), start, end))
    out.sort(key=lambda e: (e["start_utc"], e["title"]))
    return out


def recent_log(limit: int = 20) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------- writing


def _log(conn, calendar_ref: Optional[str], uid: Optional[str], action: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO sync_log (at, provider, calendar_ref, uid, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (_now_iso(), "icloud", calendar_ref, uid, action, detail),
    )


def _store_calendars(conn, found: list[dict]) -> None:
    """Record the calendars the server listed, keeping local choices and event rows.

    `enabled` belongs to the person, not the server: a calendar switched off here is
    switched off, however many times it comes back in a listing.
    """
    for calendar in found:
        existing = conn.execute("SELECT ref FROM calendars WHERE ref = ?", (calendar["ref"],)).fetchone()
        if existing is None:
            # ctag starts NULL on purpose. It is a cursor, not a description: storing the
            # value we just listed would make the sync that follows compare it against
            # itself and skip the fetch — so a first sync would import nothing, and keep
            # importing nothing, until something else in the calendar changed.
            conn.execute(
                """INSERT INTO calendars (ref, provider, name, colour, enabled, writable, ctag, last_sync)
                   VALUES (?, ?, ?, ?, 1, ?, NULL, NULL)""",
                (calendar["ref"], calendar["provider"], calendar["name"], calendar["colour"],
                 calendar["writable"]),
            )
            _log(conn, calendar["ref"], None, "calendar", f"found {calendar['name']}")
        else:
            conn.execute(
                "UPDATE calendars SET name = ?, colour = ?, writable = ? WHERE ref = ?",
                (calendar["name"], calendar["colour"], calendar["writable"], calendar["ref"]),
            )


def _upsert_events(conn, rows: list[dict]) -> tuple[int, int, int]:
    """(added, updated, unchanged) — updated means a field a person would notice."""
    import calendar_sync as cs  # noqa: PLC0415

    added = updated = unchanged = 0
    for row in rows:
        local = conn.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone()
        if local is None:
            conn.execute(
                f"INSERT INTO events ({', '.join(EVENT_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in EVENT_COLUMNS)})",
                tuple(row.get(column) for column in EVENT_COLUMNS),
            )
            added += 1
            _log(conn, row["calendar_ref"], row["uid"], "import", row["title"])
            continue

        before = dict(local)
        merged = cs.merge_remote(before, row)
        changed = [f for f in CONTENT_FIELDS if before.get(f) != merged.get(f)]
        if not changed:
            unchanged += 1
            # Only the bookkeeping moves, so keep the new ETag without pretending the
            # event changed. Without this the next sync sees the same difference again.
            conn.execute("UPDATE events SET etag = ?, updated_at = ? WHERE id = ?",
                         (merged.get("etag"), merged.get("updated_at"), row["id"]))
            continue
        conn.execute(
            f"UPDATE events SET {', '.join(f'{c} = ?' for c in EVENT_COLUMNS)} WHERE id = ?",
            (*(merged.get(column) for column in EVENT_COLUMNS), row["id"]),
        )
        updated += 1
        _log(conn, row["calendar_ref"], row["uid"], "update", ", ".join(changed))
    return added, updated, unchanged


def _known_ids(rows: list[dict]) -> set[str]:
    return {row["id"] for row in rows}


def _reconcile(conn, ref: str, seen: set[str], window_start: datetime, window_end: datetime) -> int:
    """Delete events this calendar says are gone. The dangerous half of a sync.

    Two rules, and both are load-bearing:

    * Only ever called after a fetch that completed. A REPORT that errored, timed out or
      came back malformed must not look like "these events stopped existing" — the caller
      simply does not get here.
    * Only rows the server was actually asked about. That means an event starting inside
      the window, and a series only when its first occurrence is inside it. A weekly
      meeting that began in March is never deleted because it did not appear in a
      September query.

    Rows outside both are left exactly as they are — a plan is informed by what happened
    last week, and the window moves.
    """
    start_iso, end_iso = window_start.isoformat(timespec="seconds"), window_end.isoformat(timespec="seconds")
    candidates = conn.execute(
        """SELECT id, uid, title, rrule, start_utc FROM events
           WHERE calendar_ref = ? AND start_utc >= ? AND start_utc < ?""",
        (ref, start_iso, end_iso),
    ).fetchall()

    removed = 0
    for row in candidates:
        if row["id"] in seen:
            continue
        conn.execute("DELETE FROM events WHERE id = ?", (row["id"],))
        removed += 1
        _log(conn, ref, row["uid"], "remove", f"{row['title']} — no longer on the server")
    return removed


# --------------------------------------------------------------------- the sync


def sync(*, if_stale_seconds: int = 0, transport=None, client: Optional[CalDavClient] = None) -> dict:
    """Fetch every enabled calendar, store what changed, and say what happened.

    if_stale_seconds exists so the interface can ask on every open without hammering
    iCloud: an unanswered question is cheaper than a round trip, and a 15-minute-old
    answer is fine for a calendar.
    """
    credentials, why = configuration()
    if credentials is None and client is None:
        raise NotConfigured(why)

    at = last_sync()
    moment = _parse(at)
    if if_stale_seconds and at and moment is not None:
        if (datetime.now(timezone.utc) - moment).total_seconds() < if_stale_seconds:
            return {"skipped": "fresh", "last_sync": at, "calendars": [], "totals": _totals([])}

    window_start = datetime.now(timezone.utc) - timedelta(days=WINDOW_BACK_DAYS)
    window_end = window_start + timedelta(days=WINDOW_BACK_DAYS + WINDOW_FORWARD_DAYS)

    session = client
    if session is None:
        assert credentials is not None  # guaranteed by the guard above
        session = CalDavClient(credentials, transport=transport)
    try:
        found = session.calendars()
        with db() as conn:
            if found:
                _store_calendars(conn, found)
            else:
                # A listing that came back empty is a server having a bad day, not a person
                # deleting every calendar: do not disable anything on the strength of it.
                _log(conn, None, None, "error", "the server listed no calendars; nothing changed")

        outcomes: list[Outcome] = []
        for calendar in found:
            ref = calendar["ref"]
            name = calendar["name"]
            with db() as conn:
                stored = conn.execute("SELECT * FROM calendars WHERE ref = ?", (ref,)).fetchone()
            if stored is None or not stored["enabled"]:
                continue
            # Only a calendar that has actually been read once can be skipped on the
            # strength of its ctag; before that the cursor means nothing.
            if stored["last_sync"] and stored["ctag"] and stored["ctag"] == calendar["ctag"]:
                outcomes.append(Outcome(ref, name, skipped=True))
                with db() as conn:
                    conn.execute("UPDATE calendars SET last_sync = ?, last_error = NULL WHERE ref = ?",
                                 (_now_iso(), ref))
                continue

            try:
                rows, cancelled = session.events(ref, window_start, window_end)
            except CalDavError as exc:
                outcomes.append(Outcome(ref, name, error=str(exc)))
                with db() as conn:
                    conn.execute("UPDATE calendars SET last_error = ?, last_sync = ? WHERE ref = ?",
                                 (str(exc), _now_iso(), ref))
                    _log(conn, ref, None, "error", str(exc))
                continue

            # The fetch completed, so absence now means something. Everything above this
            # line may fail freely; below it, the deleting starts.
            with db() as conn:
                added, updated, unchanged = _upsert_events(conn, rows)
                seen = _known_ids(rows)
                cancelled_removed = 0
                for uid in cancelled:
                    gone = conn.execute(
                        "DELETE FROM events WHERE calendar_ref = ? AND uid = ?", (ref, uid)
                    ).rowcount
                    if gone:
                        cancelled_removed += gone
                        _log(conn, ref, uid, "remove", "the server says cancelled")
                removed = cancelled_removed + _reconcile(conn, ref, seen, window_start, window_end)
                conn.execute(
                    "UPDATE calendars SET ctag = ?, last_sync = ?, last_error = NULL WHERE ref = ?",
                    (calendar["ctag"], _now_iso(), ref),
                )
            outcomes.append(Outcome(ref, name, added=added, updated=updated, removed=removed,
                                    unchanged=unchanged))

        return {
            "at": _now_iso(),
            "window": {"start": window_start.isoformat(timespec="seconds"),
                       "end": window_end.isoformat(timespec="seconds")},
            "calendars": [o.as_dict() for o in outcomes],
            "totals": _totals(outcomes),
        }
    finally:
        if client is None:
            session.close()


def _totals(outcomes: list[Outcome]) -> dict:
    return {
        "added": sum(o.added for o in outcomes),
        "updated": sum(o.updated for o in outcomes),
        "removed": sum(o.removed for o in outcomes),
        "errors": sum(1 for o in outcomes if o.error),
    }

