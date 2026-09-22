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
    return d


def get_block(block_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such block")
    return row_to_dict(row)


def pick_color() -> int:
    """Rotate the palette so consecutive new blocks look different."""
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"]
    return n % len(PALETTE)
