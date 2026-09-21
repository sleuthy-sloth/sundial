"""The database handle, in its own module because more than one thing opens it.

`app.py` needs a connection to serve a request; the calendar sync needs one to store
what it fetched, and it is called from a background-ish path rather than a request
handler. Keeping the handle here stops those two importing each other.

    SUNDIAL_DB   the database file. Defaults to backend/sundial.db.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SUNDIAL_DB", ROOT / "sundial.db"))


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """One connection per use: commit it, roll it back, and close it either way.

    Two things this settles. A connection's own `with` block commits or rolls back but
    does not close it, so the handle — and whatever reader it held on the WAL — lived
    until the garbage collector happened to run. And foreign keys are off by default in
    SQLite, per connection, so the `ON DELETE CASCADE` in 002 was decorative: deleting a
    calendar left its events behind.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
