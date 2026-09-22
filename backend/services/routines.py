"""The rules that decide when a routine happens, and what one of its days looks like.

The whole materialisation strategy lives in `occurs_on`: an occurrence is a question asked of a
rule and a date, answered the same way every time, and nothing is written down until somebody
disagrees with a day. Nothing here generates rows, nothing looks ahead, and nothing consults a
clock other than the day it was handed.

Pure where it can be — `occurs_on` and `occurrence` take plain mappings, so they can be reasoned
about (and tested) without a database. The few functions that do read and write are at the bottom.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Mapping, Optional

from fastapi import HTTPException

from clock import now_iso
from services.blocks import PALETTE
from store import db

# The five rules a routine may have. The stored text is the API's text, so a row is readable in
# a SQLite browser and a refusal can name the value it did not recognise.
KINDS = ("daily", "weekdays", "weekends", "selected_weekdays", "weekly_interval")

# ISO weekday numbers, which is what Python's `isoweekday()` and the stored text both use:
# 1 is Monday, 7 is Sunday.
WEEKDAYS = (1, 2, 3, 4, 5)
WEEKEND = (6, 7)

# The values an override may replace. `state` and `done` are not on this list: they are not
# fields of the block, they are what the override *is*.
OVERRIDABLE = ("title", "start_min", "duration_min", "color", "icon", "notes")

# States an override may hold. `completed` and `done` are the same statement, which the
# migration's CHECK enforces rather than trusting this module to.
STATES = ("modified", "skipped", "completed")


def parse_weekdays(value) -> list[int]:
    """A set of days as [1, 3, 5], from either the stored text or the API's list.

    Both, because the same routine is read back through this function twice: once as the row
    that was written and once as the payload the API hands out, and a rule that only understood
    one of them would answer "no occurrences" for the other. Anything unreadable is skipped
    rather than raised on — an empty set of days is already a valid answer.
    """
    parts = value if isinstance(value, (list, tuple, set)) else str(value or "").split(",")
    days = []
    for part in parts:
        text = str(part).strip()
        if text.isdigit() and 1 <= int(text) <= 7:
            days.append(int(text))
    return days


def weekdays_text(days) -> str:
    """The canonical storage form: sorted, deduplicated, '1,3,5'."""
    return ",".join(str(d) for d in sorted({int(d) for d in days}))


def occurs_on(routine: Mapping[str, Any], day: str) -> bool:
    """Does this routine produce an occurrence on this day?

    Every branch is calendar arithmetic on `datetime.date` and nothing else. That is what makes
    the answer DST-proof: a day is a day, and the clock the app keeps is minutes past midnight
    for that day, so no rule here can be moved by an hour that a timezone gained or lost — there
    is no local time in this module to move.

    The bounds are inclusive at both ends and are compared as the strings they are stored as,
    which is a real comparison because every stored day is canonical `YYYY-MM-DD`.
    """
    if not routine["enabled"]:
        return False
    if day < routine["start_date"]:
        return False
    end = routine.get("end_date")
    if end is not None and day > end:
        return False

    kind = routine["recurrence_kind"]
    if kind == "daily":
        return True
    if kind not in KINDS:
        # A rule this code does not know cannot be said to apply. Silence, not a guess.
        return False
    date = _date.fromisoformat(day)
    if kind == "weekdays":
        return date.isoweekday() in WEEKDAYS
    if kind == "weekends":
        return date.isoweekday() in WEEKEND
    if kind == "selected_weekdays":
        return date.isoweekday() in parse_weekdays(routine.get("weekdays", ""))

    # weekly_interval: the same weekday every N weeks, counted from the day it starts. Every
    # multiple of seven days lands on the same weekday, so a multiple of 7*N is the whole rule —
    # there is no separate "which weekday" to drift out of step with the anchor.
    anchor = _date.fromisoformat(routine["start_date"])
    weeks = max(1, int(routine.get("interval_weeks") or 1))
    return (date - anchor).days % (7 * weeks) == 0


def occurrence_id(routine_id: str, day: str) -> str:
    """The id a virtual occurrence is known by, for as long as nobody has touched it.

    Namespaced on purpose. An occurrence has no row, so this id must never be handed to
    `/api/blocks/{id}` and find something; the prefix is what makes that impossible rather than
    unlikely, and it is also how the frontend tells the two apart when it holds both in one list.
    """
    return f"routine:{routine_id}:{day}"


def parse_occurrence_id(value: str) -> Optional[tuple[str, str]]:
    """The routine and day behind an occurrence id, or None if this is not one."""
    parts = str(value).split(":")
    if len(parts) != 3 or parts[0] != "routine":
        return None
    return parts[1], parts[2]


def occurrence(
    routine: Mapping[str, Any], day: str, override: Optional[Mapping[str, Any]] = None
) -> Optional[dict]:
    """The occurrence on this day, or None if the routine does not have one.

    `None` covers both ways an occurrence can be absent — the rule says it does not happen, or
    it happens and you skipped it. A caller drawing a day wants the same answer for both, and
    hiding it here is what stops "skipped" from leaking into every view as a special case.

    An override replaces only what it holds: a row that moved the time leaves the title to the
    routine, so renaming a routine is not undone on the one day you ran late.
    """
    if not occurs_on(routine, day):
        return None
    if override is not None and override["state"] == "skipped":
        return None

    fields = {name: routine[name] for name in OVERRIDABLE}
    if override is not None:
        for name in OVERRIDABLE:
            if override[name] is not None:
                fields[name] = override[name]

    return {
        "id": occurrence_id(routine["id"], day),
        "day": day,
        "source": "routine",
        "routine_id": routine["id"],
        "occurrence_day": day,
        **fields,
        "done": bool(override["done"]) if override is not None else False,
        "updated_at": (override["updated_at"] if override is not None else routine["updated_at"]),
    }


def summary(routine: Mapping[str, Any]) -> str:
    """How the rule reads in a sentence. Kept beside the rule so the two cannot disagree."""
    kind = routine["recurrence_kind"]
    if kind == "daily":
        return "every day"
    if kind == "weekdays":
        return "every weekday"
    if kind == "weekends":
        return "every weekend"
    if kind == "selected_weekdays":
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = parse_weekdays(routine.get("weekdays", ""))
        return " · ".join(names[d - 1] for d in days) if days else "on no days"
    weeks = max(1, int(routine.get("interval_weeks") or 1))
    return "every week" if weeks == 1 else f"every {weeks} weeks"


# ---- reading and writing -------------------------------------------------------------------
# Below here is the part that needs a database. It is deliberately thin: every decision worth
# arguing about is above, and every refusal worth reading is the router's.


def row_to_routine(row) -> dict:
    routine = dict(row)
    routine["weekdays"] = parse_weekdays(routine["weekdays"])
    routine["enabled"] = bool(routine["enabled"])
    routine["summary"] = summary(routine)
    return routine


def get_routine(routine_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such routine")
    return row_to_routine(row)


def list_routines() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM routines ORDER BY start_min, title"
        ).fetchall()
    return [row_to_routine(r) for r in rows]


def occurrences_between(conn, days: list[str]) -> dict[str, list[dict]]:
    """Every routine occurrence across a span of days, grouped by day.

    Read, not written: asking for a week does not create anything, so looking at next month costs
    the same as looking at tomorrow and leaves the database exactly as it was. Two queries for
    the whole span rather than one per day, because the week view asks about seven days and the
    rules that reach them are the same set either way.
    """
    if not days:
        return {}
    first, last = days[0], days[-1]
    rows = conn.execute(
        """SELECT * FROM routines
           WHERE enabled = 1 AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)""",
        (last, first),
    ).fetchall()
    rules = [row_to_routine(row) for row in rows]

    marks: dict[tuple[str, str], dict] = {}
    if rules:
        names = ",".join("?" for _ in rules)
        for row in conn.execute(
            f"""SELECT * FROM routine_overrides
                 WHERE routine_id IN ({names}) AND day BETWEEN ? AND ?""",
            (*[r["id"] for r in rules], first, last),
        ):
            marks[(row["routine_id"], row["day"])] = dict(row)

    found = {day: [] for day in days}
    for day in days:
        for rule in rules:
            one = occurrence(rule, day, marks.get((rule["id"], day)))
            if one is not None:
                found[day].append(one)
    return found


def occurrences_on(conn, day: str) -> list[dict]:
    """Every routine occurrence for one day, ready for the day view."""
    return occurrences_between(conn, [day])[day]


def get_override(conn, routine_id: str, day: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM routine_overrides WHERE routine_id = ? AND day = ?", (routine_id, day)
    ).fetchone()
    return dict(row) if row is not None else None


def set_override(
    conn, routine_id: str, day: str, override_id: str, **fields
) -> Optional[dict]:
    """Put one day's opinion in place, creating the row if this is the first one.

    Returns the row, or `None` when there is no row any more — an occurrence that has been put
    back to exactly what the rule says is not an override, and keeping one would freeze that day
    against the next rename. The caller reads the occurrence back either way.

    The invariant the migration declares in SQL is maintained here instead of by an UPDATE that
    would have to reason about which of two columns moved: `state` and `done` are always written
    together, from one decision, so they cannot end up disagreeing.
    """
    current = get_override(conn, routine_id, day)
    done = bool(fields.pop("done", current["done"] if current else False))
    # A patch states the day as it should be, so a skip that is not restated is one that has
    # been changed your mind about: editing a day you had taken out is how you put it back.
    skipped = bool(fields.pop("skipped", False))
    if skipped:
        done = False
    state = "skipped" if skipped else ("completed" if done else "modified")

    values = {name: current[name] if current else None for name in OVERRIDABLE}
    values.update(fields)

    if state == "modified" and all(values[name] is None for name in OVERRIDABLE):
        drop_override(conn, routine_id, day)
        return None

    updated_at = now_iso()
    if current is None:
        conn.execute(
            f"""INSERT INTO routine_overrides
                  (id, routine_id, day, state, {', '.join(OVERRIDABLE)}, done, updated_at)
                VALUES (?, ?, ?, ?, {', '.join('?' for _ in OVERRIDABLE)}, ?, ?)""",
            (override_id, routine_id, day, state, *[values[n] for n in OVERRIDABLE], int(done),
             updated_at),
        )
    else:
        conn.execute(
            f"""UPDATE routine_overrides
                   SET state = ?, {', '.join(f'{n} = ?' for n in OVERRIDABLE)}, done = ?,
                       updated_at = ?
                 WHERE routine_id = ? AND day = ?""",
            (state, *[values[n] for n in OVERRIDABLE], int(done), updated_at, routine_id, day),
        )
    return get_override(conn, routine_id, day)


def drop_override(conn, routine_id: str, day: str) -> bool:
    """Forget what was decided about one day, going back to what the rule says."""
    cur = conn.execute(
        "DELETE FROM routine_overrides WHERE routine_id = ? AND day = ?", (routine_id, day)
    )
    return cur.rowcount > 0


def pick_color() -> str:
    """Rotate the palette so consecutive new routines look different.

    Its own copy of `services.blocks.pick_color` rather than a shared one: the two count
    different tables, and a shared helper would have to be told which, at which point it reads
    less clearly than four lines.
    """
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM routines").fetchone()["n"]
    return PALETTE[n % len(PALETTE)]
