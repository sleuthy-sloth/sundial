"""The rules that decide when a routine happens, and what one of its days looks like.

The whole materialisation strategy lives in `occurs_on`: an occurrence is a question asked of a
rule and a date, answered the same way every time, and nothing is written down until somebody
disagrees with a day. Nothing here generates rows, nothing looks ahead, and nothing consults a
clock other than the day it was handed.

A routine can hold a checklist, and that is the one place the strategy has to be thought about
twice. An occurrence has no row, so a line of one cannot be a row either: the lines are
DEFINITIONS that belong to the rule (`routine_subtasks`), and the only thing a day can say about
them is which ones were ticked — a list of line ids, stored as text on the override row that
already exists for a day somebody changed. Ticking a line writes that row, and because the row is
the same row tomorrow's reload reads, a ticked box stays ticked instead of resetting with the
calendar. Deleting a line forgets its ticks by the same trick: the id is simply no longer one of
the rule's, and a day is read by asking the rule what its lines are.

Pure where it can be — `occurs_on` and `occurrence` take plain mappings, so they can be reasoned
about (and tested) without a database. The few functions that do read and write are at the bottom.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Mapping, Optional, Sequence

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


def checked_ids(text) -> set[str]:
    """The lines a day has ticked, read out of the stored text.

    Forgiving on purpose, like `parse_weekdays`: an id that is not one of the rule's lines is
    dropped when the day is read, which is what makes deleting a line cost its ticks and nothing
    more. An empty or unreadable value is simply an empty set — no day has to be repaired by hand
    because a column was written by an older build.
    """
    return {part.strip() for part in str(text or "").split(",") if part.strip()}


def ids_text(ids) -> str:
    """The canonical storage form: sorted and deduplicated, 'a1b2,c3d4'.

    Sorted so that the same set written twice is the same text, which is what lets the row be
    dropped the moment it stops saying anything.
    """
    return ",".join(sorted({str(i) for i in ids if str(i).strip()}))


def occurrence(
    routine: Mapping[str, Any],
    day: str,
    override: Optional[Mapping[str, Any]] = None,
    lines: Sequence[Mapping[str, Any]] = (),
) -> Optional[dict]:
    """The occurrence on this day, or None if the routine does not have one.

    `None` covers both ways an occurrence can be absent — the rule says it does not happen, or
    it happens and you skipped it. A caller drawing a day wants the same answer for both, and
    hiding it here is what stops "skipped" from leaking into every view as a special case.

    An override replaces only what it holds: a row that moved the time leaves the title to the
    routine, so renaming a routine is not undone on the one day you ran late.

    `lines` are the rule's checklist, and each one comes back with the one thing a day can say
    about it: whether it was ticked. The definitions are the rule's, so they are handed in rather
    than looked up — this function stays a function of its arguments.
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

    ticked = checked_ids(override["subtasks_done"] if override is not None else "")

    return {
        "id": occurrence_id(routine["id"], day),
        "day": day,
        "source": "routine",
        "routine_id": routine["id"],
        "occurrence_day": day,
        **fields,
        "done": bool(override["done"]) if override is not None else False,
        "subtasks": [
            {"id": line["id"], "title": line["title"], "done": line["id"] in ticked}
            for line in lines
        ],
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


def row_to_routine(row, lines: Sequence[Mapping[str, Any]] = ()) -> dict:
    """A rule as the API reports it, with its checklist.

    The lines come back as definitions — id and title, in order — because that is what they are:
    the rule's. What was ticked belongs to a day, and a day is asked about separately.
    """
    routine = dict(row)
    routine["weekdays"] = parse_weekdays(routine["weekdays"])
    routine["enabled"] = bool(routine["enabled"])
    routine["summary"] = summary(routine)
    routine["subtasks"] = [
        {"id": line["id"], "title": line["title"]} for line in lines
    ]
    return routine


def line_rows(conn, routine_ids: Sequence[str]) -> dict[str, list[dict]]:
    """Each rule's lines, in the order they were written, keyed by rule.

    One query for the whole set, the same way `subtasks.lines_of` reads a task's: the week view
    asks about seven days at once, and the rules behind them are the same handful either way.
    """
    ids = [r for r in routine_ids if r]
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT * FROM routine_subtasks WHERE routine_id IN ({marks})
            ORDER BY sort_order, rowid""",
        ids,
    ).fetchall()
    found: dict[str, list[dict]] = {}
    for row in rows:
        found.setdefault(row["routine_id"], []).append(dict(row))
    return found


def get_routine(routine_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such routine")
        lines = line_rows(conn, [routine_id]).get(routine_id, [])
    return row_to_routine(row, lines)


def list_routines() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM routines ORDER BY start_min, title").fetchall()
        lines = line_rows(conn, [row["id"] for row in rows])
    return [row_to_routine(row, lines.get(row["id"], [])) for row in rows]


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
    lines = line_rows(conn, [row["id"] for row in rows])
    rules = [row_to_routine(row, lines.get(row["id"], [])) for row in rows]

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
            one = occurrence(rule, day, marks.get((rule["id"], day)), rule["subtasks"])
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

    `subtasks_done` is a third kind of thing the row can say, and it is the reason the "says
    nothing, drop it" rule below is not simply about the overridable fields: a day whose only
    news is that the third line of the morning was ticked is a day somebody changed, and the row
    is what makes that survive a reload.
    """
    current = get_override(conn, routine_id, day)
    done = bool(fields.pop("done", current["done"] if current else False))
    # A patch states the day as it should be, so a skip that is not restated is one that has
    # been changed your mind about: editing a day you had taken out is how you put it back.
    skipped = bool(fields.pop("skipped", False))
    if skipped:
        done = False
    state = "skipped" if skipped else ("completed" if done else "modified")

    # Carried over rather than cleared by a write that says nothing about it: the editor's fields
    # and the checkboxes are two different hands on one row, and neither may erase the other.
    written = fields.pop("subtasks_done", current["subtasks_done"] if current else "")
    ticked = ids_text(checked_ids(written))

    values = {name: current[name] if current else None for name in OVERRIDABLE}
    values.update(fields)

    if state == "modified" and not ticked and all(values[name] is None for name in OVERRIDABLE):
        drop_override(conn, routine_id, day)
        return None

    columns = ", ".join((*OVERRIDABLE, "subtasks_done", "done", "updated_at"))
    marks = ", ".join("?" for _ in (*OVERRIDABLE, "subtasks_done", "done", "updated_at"))
    values_tail = (*[values[n] for n in OVERRIDABLE], ticked, int(done), now_iso())
    if current is None:
        conn.execute(
            f"""INSERT INTO routine_overrides (id, routine_id, day, state, {columns})
                VALUES (?, ?, ?, ?, {marks})""",
            (override_id, routine_id, day, state, *values_tail),
        )
    else:
        sets = ", ".join(f"{name} = ?" for name in ("state", *OVERRIDABLE, "subtasks_done",
                                                    "done", "updated_at"))
        conn.execute(
            f"""UPDATE routine_overrides SET {sets} WHERE routine_id = ? AND day = ?""",
            (state, *values_tail, routine_id, day),
        )
    return get_override(conn, routine_id, day)


def drop_override(conn, routine_id: str, day: str) -> bool:
    """Forget what was decided about one day, going back to what the rule says.

    The ticks go with it, because they are part of the same answer: "back to the routine" on a day
    whose checkboxes were all ticked means the boxes are clear again, and a route that left them
    on would be undoing half of what it says it undoes.
    """
    cur = conn.execute(
        "DELETE FROM routine_overrides WHERE routine_id = ? AND day = ?", (routine_id, day)
    )
    return cur.rowcount > 0


# ---- the lines a routine holds --------------------------------------------------------------
# Definitions that belong to the rule, and nothing else: which of them were ticked on a day is on
# that day's override, handled by `set_override` above. Read in one query for the whole set by
# `line_rows`, written one line at a time — which is what keeps a line's id stable across an edit,
# and what makes the ticks that name it keep pointing at something real.


def get_line(conn, routine_id: str, line_id: str) -> dict:
    """One line of one rule, or a 404 saying which of the two did not match.

    Named and not found is one refusal rather than two: a line id from another rule is not a thing
    this rule can be asked about, and saying so is friendlier than "no such routine" for a rule
    that plainly exists.
    """
    row = conn.execute(
        "SELECT * FROM routine_subtasks WHERE id = ? AND routine_id = ?", (line_id, routine_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "no such checklist line")
    return dict(row)


def add_line(conn, routine_id: str, line_id: str, title: str) -> None:
    """Add a line at the end of the rule's checklist, where a new step belongs."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM routine_subtasks WHERE routine_id = ?",
        (routine_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO routine_subtasks (id, routine_id, title, sort_order) VALUES (?, ?, ?, ?)",
        (line_id, routine_id, title, int(row["n"])),
    )


def rename_line(conn, routine_id: str, line_id: str, title: str) -> None:
    get_line(conn, routine_id, line_id)
    conn.execute("UPDATE routine_subtasks SET title = ? WHERE id = ?", (title, line_id))


def drop_line(conn, routine_id: str, line_id: str) -> None:
    """Remove a line from the rule.

    The rule stops listing it, so every day stops drawing it, and the ticks that name it in the
    overrides are ignored from then on because a day is read by asking the rule what its lines
    are. Nothing is cleaned up behind it: rewriting months of override rows to remove an id from a
    text field is a lot of writes to make a fact that is already invisible slightly tidier.
    """
    get_line(conn, routine_id, line_id)
    conn.execute("DELETE FROM routine_subtasks WHERE id = ?", (line_id,))


def pick_color() -> str:
    """Rotate the palette so consecutive new routines look different.

    Its own copy of `services.blocks.pick_color` rather than a shared one: the two count
    different tables, and a shared helper would have to be told which, at which point it reads
    less clearly than four lines.
    """
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM routines").fetchone()["n"]
    return PALETTE[n % len(PALETTE)]
