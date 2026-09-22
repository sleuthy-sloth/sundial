"""The database's shape: the table a fresh install needs, and the migrations after it.

Two things need this answer and neither should have to import the other — the app, which runs
everything here before it serves anything, and an export, which has to describe the schema it
came out of rather than the one this code expected. The export is handed the version rather
than fetching it (`routers/data.py` passes `current_schema_version`), which is what keeps them
apart.

Named `bootstrap` and not `schema`, because `schemas/` is the request bodies.

    migrations/   numbered .sql files, applied in filename order, never edited once shipped
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from store import db

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                id           TEXT PRIMARY KEY,
                title        TEXT    NOT NULL,
                day          TEXT,                    -- 'YYYY-MM-DD', NULL = inbox
                start_min    INTEGER,                 -- minutes past midnight, NULL = inbox
                duration_min INTEGER NOT NULL DEFAULT 30,
                color        TEXT    NOT NULL DEFAULT 'slate',
                notes        TEXT    NOT NULL DEFAULT '',
                done         INTEGER NOT NULL DEFAULT 0,
                updated_at   TEXT    NOT NULL,
                CHECK (start_min IS NULL OR (start_min >= 0 AND start_min < 1440)),
                CHECK (duration_min >= 5 AND duration_min <= 1440),
                CHECK ((day IS NULL) = (start_min IS NULL))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS blocks_day ON blocks(day, start_min)")


def migrate() -> list[int]:
    """Apply every migration above the recorded version, in filename order.

    One `.sql` file per change, numbered; the number is the version. Adding a column
    later means adding a file, never editing one that has already run.

    Each migration and its version record commit together. `executescript` commits
    whatever is pending before it runs, so the transaction is opened *inside* the script
    rather than around it: a migration that fails half way takes its own DDL down with
    it instead of leaving a column that the version table says is not there — a state
    that cannot then be retried, only repaired by hand. Migrations must not open or
    commit transactions themselves.
    """
    applied: list[int] = []
    if not MIGRATIONS.is_dir():
        return applied
    with db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for path in sorted(MIGRATIONS.glob("*.sql")):
            try:
                version = int(path.name.split("_", 1)[0])
            except ValueError:
                raise RuntimeError(f"migration {path.name} must start with a number") from None
            if version <= current:
                continue
            script = (
                "BEGIN;\n"
                f"{path.read_text()}\n"
                f"INSERT INTO schema_version (version) VALUES ({version});\n"
                "COMMIT;"
            )
            try:
                conn.executescript(script)
            except Exception:
                conn.rollback()
                raise
            current = version
            applied.append(version)
    return applied


def current_schema_version(conn: sqlite3.Connection) -> int:
    """The schema the database is actually at, read rather than assumed.

    Read from the table instead of taken from the length of the migration list, because a
    database left by an older checkout can be behind this code, and an export has to
    describe the database it came out of rather than the one the code expected.
    """
    return int(conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] or 0)


def bootstrap() -> list[int]:
    """Everything a fresh or existing database needs before serving."""
    init_db()
    return migrate()
