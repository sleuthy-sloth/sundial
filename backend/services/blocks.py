"""The rules that decide what a block is, away from the routes that ask.

Each of these answers a question more than one route has to ask: which colour comes next, does
this block exist, what shape does a row come back in. Keeping them here means a rule is stated
once, and a route reads as the request it is answering.
"""

from __future__ import annotations

from fastapi import HTTPException

from store import db

# The eight colours a block may be. `palette.py` names the same eight for the calendar's
# foreign colours; the two are kept apart because this list is a validation set the API
# refuses against, and that one is a lookup with RGB edges in it.
PALETTE = ["slate", "sky", "violet", "amber", "emerald", "rose", "teal", "indigo"]


def row_to_dict(row) -> dict:
    d = dict(row)
    d["done"] = bool(d["done"])
    # Every row that reaches the API says where it came from. It costs one key and it saves the
    # frontend from working out by shape whether a thing can be edited — `routine` rows are
    # occurrences of a rule, and a write against one of those goes to the rule.
    d["source"] = "block"
    return d


def get_block(block_id: str) -> dict:
    """One block, with its checklist if it has one.

    The import is inside the function because `services/subtasks.py` reads block rows through
    `row_to_dict`, and one of the two has to be the one that waits. This is the smaller half: a
    task's lines are two lines of SQL and the caller of this function has already paid for a
    connection.
    """
    from services import subtasks

    with db() as conn:
        row = conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such block")
        block = row_to_dict(row)
        subtasks.attach(conn, [block])
    return block


def pick_color() -> int:
    """Rotate the palette so consecutive new blocks look different.

    Top-level blocks only: a checklist line is not a task you put on a day, and counting them
    would step the palette along every time somebody wrote down a step.
    """
    with db() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM blocks WHERE parent_id IS NULL"
        ).fetchone()["n"]
    return n % len(PALETTE)
