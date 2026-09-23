"""The lines under a task: reading them, and the two rules about what one may be.

A line is a `blocks` row with a `parent_id` — `migrations/008_subtasks.sql` says why — so the
writes that change one (tick it, rename it, remove it) are the writes the API already has, and
nothing here duplicates them. What is here is everything about the *relationship*: reading the
lines of a set of tasks in one query, giving a new line its place, and refusing the two shapes
that would make a checklist into something else.

Four decisions are worth reading before the code:

**One level.** A line of a line is refused, with a sentence. SQLite would hold one happily; a
checklist under a checklist is a document, and this app is a day. So there is exactly one
`parent_id` deep, and `parent_row` is the only place that decides it.

**A line has no day of its own.** `day` and `start_min` stay NULL: the line is inside its task,
so it is read with its task and never by day. That is what keeps the day's own query, the week's
counts, the inbox and the rollover from having to know lines exist — and it is why the inbox
query says `parent_id IS NULL` beside its `day IS NULL`: an inbox is a list of tasks you can give
a time to.

**A line is created as a line.** Nothing re-parents one, so `BlockPatch` has no `parent_id` and
there is no route that makes a task out of a line. Moving a line between tasks is a thing nobody
has asked for, and every way of doing it is a way to lose the ticks on it.

**Sorting is stored, not implied.** A line carries the `sort_order` it was written at, because an
export selects rows and an import re-inserts them: the order a person wrote down belongs in the
file rather than in whatever rowid SQLite hands out. Ties (two lines written at once) fall back
to the rowid, which is the order they were inserted in.
"""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException

from services.blocks import row_to_dict


def lines_of(conn, parents: Sequence[str]) -> dict[str, list[dict]]:
    """The lines of these tasks, in the order they were written, keyed by task id.

    One query for the whole set rather than one per task, because the day view asks about every
    block on the day at once and a query per block is how a page of twenty tasks becomes forty
    round trips to SQLite.
    """
    ids = [p for p in parents if p]
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM blocks WHERE parent_id IN ({marks}) ORDER BY sort_order, rowid",
        ids,
    ).fetchall()

    found: dict[str, list[dict]] = {}
    for row in rows:
        found.setdefault(row["parent_id"], []).append(row_to_dict(row))
    return found


def attach(conn, blocks: list[dict]) -> list[dict]:
    """Put each task's checklist on it, and hand the list back.

    Every block gets the key, an empty list included. A client that has to test for the key's
    absence is a client that will one day treat "no lines" and "this shape is new to me" as the
    same thing.
    """
    lines = lines_of(conn, [b["id"] for b in blocks])
    for block in blocks:
        block["subtasks"] = lines.get(block["id"], [])
    return blocks


def next_order(conn, parent_id: str) -> int:
    """Where a new line goes: after the ones already there."""
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS n FROM blocks WHERE parent_id = ?", (parent_id,)
    ).fetchone()
    return int(row["n"]) + 1


def parent_row(conn, parent_id: str):
    """The task a new line is being added to, or a refusal naming what is wrong.

    Two refusals, because they are two different mistakes. A task that is not there is a 404;
    a task that is itself a line is a 400, and the sentence says which rule it broke rather than
    leaving a client to guess that nesting is one deep.
    """
    row = conn.execute("SELECT * FROM blocks WHERE id = ?", (parent_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such block")
    if row["parent_id"] is not None:
        raise HTTPException(400, "a checklist line cannot hold lines of its own")
    return row


def check_patch(current: dict, fields: dict, unschedule: bool = False) -> None:
    """A line is inside its task: it is not scheduled, moved to a day, or sent to the inbox.

    Checked as a whole rather than field by field at the point of use, because the pair travels
    together: `unschedule` is two columns, and a line given one of the three would otherwise end
    up half scheduled — which the table's own CHECK refuses with a 500 rather than a sentence.
    """
    if current.get("parent_id") is None:
        return
    if unschedule or "day" in fields or "start_min" in fields:
        raise HTTPException(400, "a checklist line is inside its task, not on the day")
