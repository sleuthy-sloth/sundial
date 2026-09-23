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
from typing import Iterator

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

    The statements of a migration are run one at a time inside a transaction opened
    here, so a migration that fails half way takes its own DDL down with it instead of
    leaving a column that the version table says is not there — a state that cannot
    then be retried, only repaired by hand. A migration's version record goes in the
    same transaction, and migrations must not open or commit transactions themselves.

    And one error is not a failure: `duplicate column name`. Replaying a migration is
    not an accident to be caught — it is the repair, and it is what `test_app.py` and
    `scripts/smoke_release.py` both do: the version records from a migration up are
    deleted and the app is started again, which is the only way to re-run the day
    repair in 003 on an installation that stored a compact date. Every later migration
    comes back with it or MAX(version) still reads past the repair. That survived as
    long as migrations only created things, which is the one shape SQLite has "if not
    exists" for; `ALTER TABLE ... ADD COLUMN` is the shape it does not, so a replay
    that was refused here would take the repair away instead of performing it. A
    column that is already there is what SQLite means by that error and it means
    nothing else, so the statement is skipped and its migration counts as applied.
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
            if conn.in_transaction:  # nothing pending outlives a migration
                conn.commit()
            conn.execute("BEGIN")
            try:
                for statement in _statements(path.read_text()):
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError as exc:
                        if not _already_there(exc):
                            raise
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
                conn.execute("COMMIT")
            except Exception:
                conn.rollback()
                raise
            current = version
            applied.append(version)
    return applied


def _statements(script: str) -> Iterator[str]:
    """A migration file cut where SQLite itself says one statement ends.

    `sqlite3.complete_statement` is the module's own lexer, so a semicolon inside a string or a
    comment does not end a statement, and a fragment with nothing but comments in it is not one
    (`conn.execute` refuses those).
    """
    fragment = ""
    for line in script.splitlines(keepends=True):
        fragment += line
        if sqlite3.complete_statement(fragment):
            if _code(fragment).strip():
                yield fragment
            fragment = ""
    if _code(fragment).strip():
        yield fragment


def _code(fragment: str) -> str:
    """The fragment with its comments cut off the end of each line, which is what SQLite reads."""
    return "\n".join(line.split("--", 1)[0] for line in fragment.splitlines())


def _already_there(exc: sqlite3.OperationalError) -> bool:
    """True for the one error a replayed migration is allowed to produce — see `migrate`."""
    return str(exc).startswith("duplicate column name:")


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
