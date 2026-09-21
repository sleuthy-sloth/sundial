"""The backup and restore path.

The risk these cover: `cp sundial.db backup.db`, which the README recommended, copies
the main file only. In WAL mode a committed write lives in `sundial.db-wal` until a
checkpoint, so a copy taken while the app is serving can be missing the row that was
just saved — and it looks like a perfectly good database either way.

Run with:  cd backend && .venv/bin/pytest -q
"""

import importlib.util
import pathlib
import shutil
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("sundial_backup", ROOT / "scripts" / "backup.py")
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


def write_db(path, values):
    """A self-contained database holding `values`, with nothing left in a WAL."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS blocks (v TEXT)")
        conn.executemany("INSERT INTO blocks VALUES (?)", [(v,) for v in values])
        conn.commit()
    finally:
        conn.close()
    return path


def rows_in(path):
    """How many rows a database holds, or why it cannot be read at all."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"unreadable: {exc}"
    try:
        return conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    except sqlite3.Error as exc:
        return f"unreadable: {exc}"
    finally:
        conn.close()


def test_a_backup_keeps_a_row_a_plain_file_copy_loses(tmp_path):
    live = tmp_path / "live.db"
    writer = sqlite3.connect(live)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE blocks (v TEXT)")
        writer.execute("INSERT INTO blocks VALUES ('committed, still in the WAL')")
        writer.commit()

        wal = pathlib.Path(str(live) + "-wal")
        assert wal.exists() and wal.stat().st_size > 0, "expected the write to sit in the WAL"

        copied = tmp_path / "copied.db"
        shutil.copy(live, copied)  # what the README used to tell you to do
        saved = backup.backup(live, tmp_path / "saved.db")

        assert rows_in(saved) == 1, "the backup is missing a committed row"
        assert rows_in(copied) != 1, "the plain copy happened to be complete"
    finally:
        writer.close()


def test_a_backup_is_a_valid_database_and_leaves_the_live_one_alone(tmp_path):
    live = write_db(tmp_path / "live.db", ["a", "b"])

    saved = backup.backup(live, tmp_path / "nested" / "saved.db")

    conn = sqlite3.connect(saved)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert rows_in(saved) == 2
    assert rows_in(live) == 2


def test_restore_replaces_the_database_and_clears_the_old_wal(tmp_path):
    live = write_db(tmp_path / "live.db", ["first"])
    saved = backup.backup(live, tmp_path / "saved.db")

    # The live database moves on, and the write is still in the WAL when we restore:
    # that WAL belongs to the database being replaced, not to the one coming in.
    live_conn = sqlite3.connect(live)
    live_conn.execute("PRAGMA journal_mode=WAL")
    live_conn.execute("INSERT INTO blocks VALUES ('second')")
    live_conn.commit()
    wal = pathlib.Path(str(live) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0

    replaced = backup.restore(saved, live)

    assert rows_in(live) == 1, "the restore did not take"
    assert not wal.exists(), "the replaced database's WAL was left beside the restored one"
    assert replaced is not None and rows_in(replaced) == 2, "the database being replaced was lost"

    live_conn.close()


def test_restore_refuses_a_file_that_is_not_a_database(tmp_path):
    junk = tmp_path / "not.db"
    junk.write_text("this is not a database")
    live = write_db(tmp_path / "live.db", ["keep me"])

    with pytest.raises(ValueError):
        backup.restore(junk, live)

    assert rows_in(live) == 1, "a refused restore changed the database anyway"


def test_restore_refuses_a_database_without_our_tables(tmp_path):
    stranger = write_db(tmp_path / "stranger.db", ["someone else's data"])
    conn = sqlite3.connect(stranger)
    try:
        conn.execute("DROP TABLE blocks")
        conn.commit()
    finally:
        conn.close()
    live = write_db(tmp_path / "live.db", ["keep me"])

    with pytest.raises(ValueError):
        backup.restore(stranger, live)

    assert rows_in(live) == 1


def test_the_default_path_is_the_backend_database(monkeypatch):
    monkeypatch.delenv("SUNDIAL_DB", raising=False)
    assert backup.default_db_path() == ROOT / "backend" / "sundial.db"


def test_the_environment_overrides_the_path(monkeypatch, tmp_path):
    monkeypatch.setenv("SUNDIAL_DB", str(tmp_path / "elsewhere.db"))
    assert backup.default_db_path() == tmp_path / "elsewhere.db"
