"""The whole database as one JSON file, and putting it back.

This is the "leave whenever" guarantee. `scripts/backup.py` copies the database, which
is the right shape for a restore — it brings back everything, exactly, including things
this app has not thought about. A copy is not the same as an exit, though: a `.db` file
is only readable by something that speaks SQLite, it carries the schema you happened to
be running, and it cannot be read in a text editor or diffed in git. So there are two
ways out, and they answer different questions. `backup.py` answers "put it back". This
answers "it is mine, and I can read it".

What is in here: every table a person would sit down and call their own data.

What is deliberately not:

    push_subscriptions   an endpoint is a capability, not content. Anyone holding one
                         can send a notification to that device, so it does not belong
                         in a file people mail to themselves — and a device restored
                         somewhere else must subscribe on its own. Importing never
                         touches this table, which also means restoring your data
                         cannot silently unsubscribe the phone in your pocket.
    sqlite_sequence      SQLite's own counter for autoincrement columns, not data. It
                         rebuilds itself.

Nothing secret is at risk in a run of the mill export, because no credential lives in
the database: the iCloud and Google identities are files (`icloud.env`, `google.env`),
and this module never reads them.

Standard library only, like `backup.py`, for the same reason: the moment you need this
is the moment the app's dependencies might not be installed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# What a reader should find in the file. `format` is the thing to check before parsing
# anything else, and it is spelled out rather than implied by the filename because a
# filename is the first thing a person renames.
FORMAT = "sundial-export"
VERSION = 1

# Every table carried, in an order that satisfies the foreign keys when it is put back:
# `events` references `calendars`, so calendars go in first. Deletion walks it backwards.
TABLES: tuple[str, ...] = ("calendars", "blocks", "events", "sync_log", "push_sent")

# Present in the database, absent from the file, on purpose. Each entry is the sentence
# the refusal or the documentation will use, so the reason travels with the decision.
NOT_CARRIED = {
    "push_subscriptions": (
        "each device's notification endpoint is a capability rather than content, "
        "so it is not exported and is left alone by an import"
    ),
    "sqlite_sequence": "SQLite's own counter for autoincrement columns",
}

SCALARS = (str, int, float, bool, type(None))


class ExportError(ValueError):
    """A file that will not be imported, with a sentence saying why."""


def database_file(conn: sqlite3.Connection) -> Path:
    """The file this connection is actually using.

    Asked of the connection rather than taken from a module constant, because a constant
    is bound when `app` is imported: with a second instance, or under test, that constant
    names the wrong database and the safety copy lands beside it.
    """
    for _, name, path in conn.execute("PRAGMA database_list"):
        if name == "main" and path:
            return Path(path)
    raise ExportError("this connection is not backed by a database file")


def keep_copy(conn: sqlite3.Connection, db_path: Path) -> Path:
    """A consistent copy of the database that an import is about to replace.

    An import is the one act here that can lose everything in one request, so it leaves a
    way back — the same move `scripts/backup.py --restore` makes, for the same reason.
    Taken through SQLite's own API rather than `cp` because the app is answering requests
    while this happens, and in WAL mode a plain copy can be missing the newest write while
    still looking like a perfectly good database.

    Kept beside the database and named for the moment, so the newest one is obvious and
    the old ones can just be deleted.
    """
    db_path = Path(db_path)
    dest = db_path.with_name(f"{db_path.stem}.replaced-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
    target = sqlite3.connect(str(dest))
    try:
        conn.backup(target)
    finally:
        target.close()
    return dest


def dump(conn: sqlite3.Connection, schema_version: int) -> dict[str, Any]:
    """Every row of every carried table, plus enough to know what this document is."""
    tables: dict[str, list[dict[str, Any]]] = {}
    for name in TABLES:
        tables[name] = [dict(row) for row in conn.execute(f"SELECT * FROM {name}")]
    return {
        "format": FORMAT,
        "version": VERSION,
        "schema_version": int(schema_version),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tables": tables,
    }


def counts(payload: dict[str, Any]) -> dict[str, int]:
    """How many of each thing the document holds — what a UI shows before importing."""
    return {name: len(payload.get("tables", {}).get(name, [])) for name in TABLES}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def check(payload: Any, schema_version: int) -> dict[str, list[dict[str, Any]]]:
    """Validate a document completely, and return its tables.

    Everything is checked before a single row is written, because the alternative is
    finding out halfway through a destructive import. The messages name the field and
    say what was expected — an import is a rare enough act that the sentence is the
    whole user interface for it.

    Three refusals matter more than the rest. A document that is not a sundial export
    at all. A document from a *newer* sundial, which is refused rather than partly
    understood, because migrations only run forwards. And a document missing a table
    the format promises: absent and empty look identical once imported, so a partial
    file would quietly delete the part it left out.
    """
    if not isinstance(payload, dict):
        raise ExportError("that file is not a sundial export (it is not a JSON object)")
    if payload.get("format") != FORMAT:
        raise ExportError(
            f"that file is not a sundial export (expected \"format\": \"{FORMAT}\", "
            f"found {payload.get('format')!r})"
        )

    version = payload.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ExportError("that file has no usable \"version\" field")
    if version > VERSION:
        raise ExportError(
            f"that file was written by a newer sundial (format {version}, this one speaks "
            f"{VERSION}). Upgrade sundial before importing it"
        )

    found_schema = payload.get("schema_version")
    if not isinstance(found_schema, int) or isinstance(found_schema, bool):
        raise ExportError("that file has no usable \"schema_version\" field")
    if found_schema > schema_version:
        raise ExportError(
            f"that file comes from a newer sundial (schema {found_schema}, this one is at "
            f"{schema_version}). Upgrade sundial before importing it"
        )

    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise ExportError("that file has no \"tables\" object")

    missing = [name for name in TABLES if name not in tables]
    if missing:
        raise ExportError(
            f"that file is missing the {', '.join(missing)} table(s) — a complete export "
            "carries all of them, and importing a partial one would delete what it left out"
        )

    for name in TABLES:
        rows = tables[name]
        if not isinstance(rows, list):
            raise ExportError(f'"{name}" should be a list of rows, not {type(rows).__name__}')
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ExportError(f"row {index} of \"{name}\" is not an object")
            if not row:
                raise ExportError(f"row {index} of \"{name}\" is empty")
            for key, value in row.items():
                if not isinstance(value, SCALARS):
                    raise ExportError(
                        f'"{name}" row {index} has a {type(value).__name__} for "{key}"; '
                        "values should be text, numbers, true/false or null"
                    )
    return {name: tables[name] for name in TABLES}


def unknown_columns(payload: Any, conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Columns the file mentions that the table does not have.

    Reported rather than ignored. A column that survives validation but not insertion is
    the one case where a "successful" import has silently dropped something, and a typo
    in a hand-made file is exactly how that happens.
    """
    out: dict[str, list[str]] = {}
    for name in TABLES:
        rows = payload.get("tables", {}).get(name) or []
        known = _columns(conn, name)
        extra = sorted({k for row in rows if isinstance(row, dict) for k in row} - known)
        if extra:
            out[name] = extra
    return out


def replace(conn: sqlite3.Connection, tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Put a validated document in place of everything currently in the database.

    Replaces rather than merges. Merging sounds gentler and is the harder promise to
    keep: two databases with the same block id are the same block or two blocks
    depending on nothing the file records, so a merge has to guess, and the guess is
    silent. It also cannot be undone by reading the result. "This is my data now" is
    the honest version of the button, and the UI says so before it runs.

    Not atomic by construction here — the caller's transaction is. `store.db()` commits
    on the way out and rolls back on an exception, and the explicit rollback below means
    a failure part way through leaves the database exactly as it was.
    """
    try:
        for name in reversed(TABLES):  # children before parents, for the foreign keys
            conn.execute(f"DELETE FROM {name}")
        written: dict[str, int] = {}
        for name in TABLES:  # parents before children, for the same reason
            for row in tables[name]:
                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO {name} ({columns}) VALUES ({marks})", list(row.values()))
            written[name] = len(tables[name])
    except Exception:
        conn.rollback()
        raise
    return written
