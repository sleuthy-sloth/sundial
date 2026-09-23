"""The day, and the blocks that make it up: read, add, change, remove."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException

from clock import now_iso, today
from schemas.blocks import BlockIn, BlockPatch
from services import rollover, routines, subtasks
from services.blocks import PALETTE, get_block, pick_color, row_to_dict
from services.scheduling import check_fits, validate_day
from store import db

router = APIRouter()


@router.get("/api/day")
def get_day(day: Optional[str] = None) -> dict:
    """Everything the UI needs for one day: that day's blocks plus the inbox.

    Routine occurrences are merged in with the blocks rather than handed over in a list of their
    own, because on the page they are blocks — they are drawn on the clock, counted in the day's
    planned time, ticked off and dragged. They carry `source: "routine"` and the routine and day
    they came from, which is everything the frontend needs to send a write to the rule instead of
    to a row: nothing is written for an occurrence until you change it.

    A task's checklist is nested on it rather than listed beside it — `block["subtasks"]`, in the
    order the lines were written. A line has no day of its own, so it is not in this query, not in
    the day's plan and not in `minutes` anywhere: it is read here because it is part of the task,
    and it travels with the task everywhere the task goes.

    `leftover` is the fourth list and the only one that is not on the day it is about: the
    unfinished blocks of the day before, which Today offers to take in. It is empty for every day
    except today, and it is read and not acted on — this route never moves anything. See
    `services/rollover.py` for why a routine occurrence and a calendar event can never be in it,
    and why a checklist line never is either.
    """
    day = day or today()
    validate_day(day)
    today_iso = today()
    with db() as conn:
        scheduled = conn.execute(
            "SELECT * FROM blocks WHERE day = ? ORDER BY start_min", (day,)
        ).fetchall()
        # `parent_id IS NULL` is what keeps a checklist line out of the inbox. A line has no day
        # of its own either, so without it every step of every task would be waiting for a time.
        inbox = conn.execute(
            "SELECT * FROM blocks WHERE day IS NULL AND parent_id IS NULL"
            " ORDER BY updated_at DESC"
        ).fetchall()
        occurrences = routines.occurrences_on(conn, day)
        leftover = rollover.leftover_for(conn, day, today_iso)
        # One query per list, inside the connection that read them: no task is read without its
        # lines, so no caller has to remember to ask for them.
        blocks = subtasks.attach(conn, [row_to_dict(r) for r in scheduled])
        inbox_items = subtasks.attach(conn, [row_to_dict(r) for r in inbox])
        leftover = subtasks.attach(conn, leftover)

    blocks.extend(occurrences)
    # One list in the order the day happens. A block and an occurrence on the same minute are
    # ordered blocks first, so a day full of routines never hides your own plan underneath it.
    blocks.sort(key=lambda b: (b["start_min"], b["source"] != "block", b["title"]))

    return {
        "day": day,
        "today": today_iso,
        "blocks": blocks,
        "inbox": inbox_items,
        "leftover": leftover,
    }


def _create_line(block_id: str, title: str, parent_id: str, body: BlockIn) -> dict:
    """Write a checklist line under its task, and answer with it.

    A line takes its task's colour, which nothing draws: it sits inside the task's own edge. It is
    filled in rather than left to the column's default so that a file read by hand, or a template
    copied later, never shows a line claiming a colour of its own.
    """
    with db() as conn:
        parent = subtasks.parent_row(conn, parent_id)
        conn.execute(
            """INSERT INTO blocks
                 (id, title, day, start_min, duration_min, color, icon, notes, done, updated_at,
                  parent_id, sort_order)
               VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (block_id, title, body.duration_min, parent["color"], body.icon.strip(), body.notes,
             now_iso(), parent["id"], subtasks.next_order(conn, parent["id"])),
        )
    return get_block(block_id)


@router.post("/api/blocks", status_code=201)
def create_block(body: BlockIn) -> dict:
    """A task, or a line under one.

    `parent_id` is the whole difference, and the two shapes do not mix: a request that gives a
    line both a parent and a day is refused rather than half stored, because the day's own query
    cannot see a line and one written onto a day would quietly be missing from every list that
    shows it.
    """
    block_id = uuid.uuid4().hex[:12]
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a block needs a title")
    if body.color is not None and body.color not in PALETTE:
        raise HTTPException(400, f"unknown color {body.color!r}")
    if body.parent_id is not None:
        if body.day is not None or body.start_min is not None:
            raise HTTPException(400, "a checklist line is inside its task, not on the day")
        return _create_line(block_id, title, body.parent_id, body)
    color = body.color or PALETTE[pick_color()]
    if body.day is not None:
        validate_day(body.day)
        if body.start_min is None:
            raise HTTPException(400, "a scheduled block needs start_min")
    if body.start_min is not None and body.day is None:
        raise HTTPException(400, "start_min needs a day")
    if body.start_min is not None:
        check_fits(body.start_min, body.duration_min)
    with db() as conn:
        conn.execute(
            """INSERT INTO blocks
                 (id, title, day, start_min, duration_min, color, icon, notes, done, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (block_id, title, body.day, body.start_min,
             body.duration_min, color, body.icon.strip(), body.notes, now_iso()),
        )
    return get_block(block_id)


@router.patch("/api/blocks/{block_id}")
def patch_block(block_id: str, body: BlockPatch) -> dict:
    current = get_block(block_id)
    fields = body.model_dump(exclude_unset=True, exclude={"unschedule"})

    if body.unschedule:
        fields |= {"day": None, "start_min": None}

    # A checklist line is inside its task: it is not scheduled, moved to a day, or sent to the
    # inbox. Ticking one, renaming one and changing its length are the writes it does have.
    subtasks.check_patch(current, fields, unschedule=body.unschedule)

    # Only the scheduling pair may be nulled. Every other field has a NOT NULL column
    # behind it, so an explicit null travelled to SQLite and came back as a 500.
    for key, value in fields.items():
        if value is None and key not in ("day", "start_min"):
            raise HTTPException(400, f"{key} cannot be null")

    if "title" in fields:
        fields["title"] = fields["title"].strip()
        if not fields["title"]:
            raise HTTPException(400, "a block needs a title")
    if "color" in fields and fields["color"] not in PALETTE:
        raise HTTPException(400, f"unknown color {fields['color']!r}")

    # Day and start travel together: dragging onto the timeline sets both, and
    # clearing one without the other would leave a block scheduled nowhere.
    if "day" in fields and "start_min" not in fields:
        if fields["day"] is None:
            fields["start_min"] = None
        elif current["start_min"] is None:
            raise HTTPException(400, "scheduling a block needs start_min too")
    if "start_min" in fields and "day" not in fields:
        if fields["start_min"] is None:
            fields["day"] = None
        elif current["day"] is None:
            fields["day"] = current["day"] or today()

    # Judge the block as it will be, not the fragment that arrived: a pair written in
    # one request can still land half scheduled, and that is what the CHECK is for.
    day = fields.get("day", current["day"])
    start_min = fields.get("start_min", current["start_min"])
    duration = fields.get("duration_min", current["duration_min"])
    if (day is None) != (start_min is None):
        raise HTTPException(400, "a block is either scheduled or in the inbox, not half of each")
    if day is not None:
        validate_day(day)
        check_fits(start_min, duration)

    if not fields:
        return current
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE blocks SET {sets} WHERE id = ?", (*fields.values(), block_id))
    return get_block(block_id)


@router.delete("/api/blocks/{block_id}", status_code=204)
def delete_block(block_id: str) -> None:
    with db() as conn:
        cur = conn.execute("DELETE FROM blocks WHERE id = ?", (block_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such block")
