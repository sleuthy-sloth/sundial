"""The rules that decide what a template is, away from the routes that ask.

A template is a plan you wrote once and can put on a day. It is not a routine: nothing here
recurs, nothing here writes to a day by itself, and the only day involved is the one handed to
`apply`. That is the whole difference, and it is why this module has no calendar logic in it —
no weekdays, no interval, no end date. There is nothing to work out from a date.

Three decisions are worth reading before the code:

**Applying is purely additive.** New `blocks` rows go in for each item and nothing else is read,
moved or modified. There is deliberately no overlap check: `services/scheduling.py` refuses only
a block that runs past midnight, the app has never had an overlap rule, and the plan says
collisions are allowed — so there is no conflict-resolution logic here to get wrong.

**One transaction.** Every item of one apply is inserted inside a single `store.db()` block, so
an apply either lands whole or does not land at all. The alternative — the frontend posting each
block — can fail half way and leave a day that is half a workday with no way to tell which half.

**Nothing is recorded about an apply.** No provenance table, no undo entry. The plan's "apply
twice" is additive, not reversible, and a ledger of what came from where would be new user data
needing its own export plumbing. The ids come back, so a caller that wants to offer "remove the
ones just added" can — and that is a delete, which already exists.

The list of items is *replaced* on every save rather than diffed. Item ids are therefore not
stable across an edit, which is fine because nothing outside this table ever refers to one:
applied blocks are copies, not references.

**A line under an item is a row in the same table**, with a `parent_id` pointing at the item it
belongs to, and one level deep like a block's checklist. It carries a name and a length and no
hour of its own: "Passport" is not at nine o'clock, "Pack for the trip" is. Applying copies the
lines too, in order, and they land as lines of the new task. A template is never done, so nothing
here stores whether a line was ticked — there is no day for it to have been ticked on.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from clock import now_iso
from store import db


def item_rows(conn, template_id: str) -> list[dict]:
    """One template's rows, in the order they were written, lines included.

    Flat, because that is what the table is; `row_to_template` is where they are nested.
    """
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM template_blocks WHERE template_id = ? ORDER BY sort_order, rowid",
            (template_id,),
        )
    ]


def row_to_template(conn, row) -> dict:
    """A template with its items, which is the only shape it is ever handed out in.

    An item's lines are nested on it, the same way a block's are on `/api/day`: a line is part of
    the item it was written under, and a client that had to pair two lists up would eventually
    pair them up wrongly.
    """
    template = dict(row)
    rows = item_rows(conn, template["id"])
    lines: dict[str, list[dict]] = {}
    for item in rows:
        if item["parent_id"] is not None:
            lines.setdefault(item["parent_id"], []).append(item)
    template["items"] = [
        {**item, "subtasks": lines.get(item["id"], [])}
        for item in rows
        if item["parent_id"] is None
    ]
    return template


def list_templates() -> list[dict]:
    """Every template, by name — the order the list under You reads in."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM templates ORDER BY name COLLATE NOCASE, created_at"
        ).fetchall()
        return [row_to_template(conn, row) for row in rows]


def get_template(template_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such template")
        return row_to_template(conn, row)


def write_items(conn, template_id: str, items: list[dict]) -> None:
    """The whole ordered list, in place of whatever was there, lines included.

    Replace rather than diff. A template list is short and hand-written, the order is the thing
    being edited, and a diff would have to decide whether a moved line is one change or three —
    a question with no right answer and a real chance of a half-applied edit. `sort_order` is
    the position in the list handed in, counted straight through the lines as well as the items,
    so the order survives a read that only knows how to sort rows.

    A line is written with no hour of its own (`start_min` NULL) however it arrived: the hour on
    an item is when the task happens, and a step inside it does not have one to have. Its colour
    is the item's, so nothing draws a colour a line did not choose.
    """
    conn.execute("DELETE FROM template_blocks WHERE template_id = ?", (template_id,))
    order = 0
    for item in items:
        item_id = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO template_blocks
                 (id, template_id, title, start_min, duration_min, color, icon, notes, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, template_id, item["title"], item["start_min"], item["duration_min"],
             item["color"], item.get("icon", ""), item.get("notes", ""), order),
        )
        order += 1
        for line in item.get("subtasks", []):
            conn.execute(
                """INSERT INTO template_blocks
                     (id, template_id, title, start_min, duration_min, color, icon, notes,
                      sort_order, parent_id)
                   VALUES (?, ?, ?, NULL, ?, ?, '', '', ?, ?)""",
                (uuid.uuid4().hex[:12], template_id, line["title"],
                 line.get("duration_min", 30), item["color"], order, item_id),
            )
            order += 1


def create_template(name: str, items: list[dict]) -> dict:
    template_id = uuid.uuid4().hex[:12]
    stamp = now_iso()
    with db() as conn:
        conn.execute(
            "INSERT INTO templates (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (template_id, name, stamp, stamp),
        )
        write_items(conn, template_id, items)
    return get_template(template_id)


def rename_template(template_id: str, name: str) -> dict:
    with db() as conn:
        cur = conn.execute(
            "UPDATE templates SET name = ?, updated_at = ? WHERE id = ?",
            (name, now_iso(), template_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(404, "no such template")
    return get_template(template_id)


def put_items(template_id: str, items: list[dict]) -> dict:
    get_template(template_id)  # 404 before anything is written
    with db() as conn:
        write_items(conn, template_id, items)
        conn.execute(
            "UPDATE templates SET updated_at = ? WHERE id = ?", (now_iso(), template_id)
        )
    return get_template(template_id)


def delete_template(template_id: str) -> None:
    """The template and its items. `ON DELETE CASCADE` takes the items, with foreign keys on."""
    with db() as conn:
        cur = conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such template")


def duplicate_template(template_id: str, name: str | None = None) -> dict:
    """A copy of the whole thing: the items, their hours and their order.

    Not a link to the original — the copy is a template of its own from the moment it exists,
    which is what makes duplicating a useful way to start one ("Workday" becomes "Workday, term
    time" and the first is left alone).
    """
    source = get_template(template_id)
    return create_template(name or f"{source['name']} copy", source["items"])


def apply_template(template_id: str, day: str) -> dict:
    """Put every item on a day as a real block, and answer with what was made.

    The items are copied, not referenced: from here on they are this day's blocks, editable and
    deletable like any other, and changing the template later changes nothing about a day it
    was already applied to. A template is a starting point, not a standing rule.

    An item with no `start_min` becomes an inbox block — the same NULL pair a block uses for
    Anytime — which is the plan's "a template item with no start_min should land in Anytime".

    A line under an item lands as a line under the block, in the order it was written, and
    contributes nothing to the day: the task keeps its own hour and the checklist travels inside
    it, exactly as a checklist typed on the day itself. `created` lists the tasks — the blocks a
    caller would offer to take back off the day — because removing a task takes its lines with it.
    """
    source = get_template(template_id)
    if not source["items"]:
        raise HTTPException(400, f"{source['name']} has nothing in it to add")

    stamp = now_iso()
    created: list[str] = []
    with db() as conn:
        for item in source["items"]:
            block_id = uuid.uuid4().hex[:12]
            conn.execute(
                """INSERT INTO blocks
                     (id, title, day, start_min, duration_min, color, icon, notes, done,
                      updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (block_id, item["title"], day if item["start_min"] is not None else None,
                 item["start_min"], item["duration_min"], item["color"], item["icon"],
                 item["notes"], stamp),
            )
            for order, line in enumerate(item["subtasks"]):
                conn.execute(
                    """INSERT INTO blocks
                         (id, title, day, start_min, duration_min, color, icon, notes, done,
                          updated_at, parent_id, sort_order)
                       VALUES (?, ?, NULL, NULL, ?, ?, '', '', 0, ?, ?, ?)""",
                    (uuid.uuid4().hex[:12], line["title"], line["duration_min"],
                     item["color"], stamp, block_id, order),
                )
            created.append(block_id)

    return {"template_id": source["id"], "name": source["name"], "day": day, "created": created}
