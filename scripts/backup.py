"""Copy the sundial database, and put a copy back.

    python3 scripts/backup.py                      # a timestamped copy beside it
    python3 scripts/backup.py --to ~/plans.db      # or wherever you keep them
    python3 scripts/backup.py --restore ~/plans.db # stop the service first

Copying the file by hand is not the same thing, which is why this exists. The database
runs in WAL mode, so a committed write lives in `sundial.db-wal` until a checkpoint
folds it into the main file. A `cp` of the main file taken while the app is answering
requests can therefore be missing the thing you just saved — and it is a perfectly
valid database, so nothing complains until you go looking for a row that is not there.
SQLite's own backup API reads through the WAL and writes a consistent copy instead.

Standard library only, deliberately: the moment you need this is the moment you may not
have the app's dependencies installed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "backend" / "sundial.db"


def default_db_path() -> Path:
    """Where the database is. Mirrors app.py's default and its override."""
    return Path(os.environ.get("SUNDIAL_DB", DEFAULT_DB))


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def backup(db_path: Path, dest: Path) -> Path:
    """A consistent copy of `db_path` at `dest`, taken with the app running."""
    db_path, dest = Path(db_path), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(db_path))
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dest


def check(path: Path) -> None:
    """Refuse anything that is not a sundial database."""
    path = Path(path)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"{path} is not a database: {exc}") from None
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        state = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"{path} is not a database: {exc}") from None
    finally:
        conn.close()
    if "blocks" not in tables:
        raise ValueError(f"{path} has no blocks table — that is not a sundial database")
    if state != "ok":
        raise ValueError(f"{path} fails its integrity check: {state}")


def restore(backup_path: Path, db_path: Path) -> Path | None:
    """Put a copy back, keeping the database it replaces.

    The `-wal` and `-shm` files beside the live database belong to the database being
    replaced, not to the one arriving. Leaving them in place mixes the two — SQLite
    would replay the old write-ahead log over the restored file. That is why the
    service should be stopped first.
    """
    backup_path, db_path = Path(backup_path), Path(db_path)
    check(backup_path)

    kept = None
    if db_path.exists():
        kept = db_path.with_name(f"{db_path.stem}.replaced-{stamp()}{db_path.suffix}")
        backup(db_path, kept)

    shutil.copyfile(backup_path, db_path)
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy the sundial database, or put a copy back.")
    parser.add_argument("--db", type=Path, default=None, help="the database to work on")
    parser.add_argument("--to", type=Path, default=None, help="where the copy should go")
    parser.add_argument(
        "--restore", type=Path, default=None, metavar="FILE", help="put this copy back"
    )
    args = parser.parse_args(argv)

    db_path = args.db or default_db_path()
    if not db_path.exists():
        print(f"there is no database at {db_path}", file=sys.stderr)
        return 1

    if args.restore:
        kept = restore(args.restore, db_path)
        print(f"restored {db_path} from {args.restore}")
        if kept:
            print(f"the database it replaced is kept at {kept}")
        print("restart the service: systemctl --user restart sundial")
        return 0

    dest = args.to or db_path.with_name(f"{db_path.stem}-{stamp()}{db_path.suffix}")
    backup(db_path, dest)
    print(f"{dest} ({dest.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
