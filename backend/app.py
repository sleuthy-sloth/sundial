"""sundial — a visual day planner.

One process: JSON API + the built SPA on the same origin (no CORS anywhere).
SQLite because it is one user, and `scripts/backup.py` copies it safely.

    uvicorn app:app --host 127.0.0.1 --port 6770
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from spa import SpaStaticFiles

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SUNDIAL_DB", ROOT / "sundial.db"))
MIGRATIONS = ROOT / "migrations"
STATIC = ROOT / "static"

PALETTE = ["slate", "sky", "violet", "amber", "emerald", "rose", "teal", "indigo"]
DAY_MIN = 1440


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


def bootstrap() -> list[int]:
    """Everything a fresh or existing database needs before serving."""
    init_db()
    return migrate()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return _date.today().isoformat()


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["done"] = bool(d["done"])
    return d


# --------------------------------------------------------------------------- api


class BlockIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    day: Optional[str] = None
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: int = Field(default=30, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: str = Field(default="", max_length=8)
    notes: str = ""


class BlockPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    day: Optional[str] = None
    start_min: Optional[int] = Field(default=None, ge=0, lt=DAY_MIN)
    duration_min: Optional[int] = Field(default=None, ge=5, le=DAY_MIN)
    color: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=8)
    notes: Optional[str] = None
    done: Optional[bool] = None
    unschedule: bool = False  # move the block back to the inbox


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    yield


app = FastAPI(
    title="sundial",
    version="0.1.2",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/api/health")
def health() -> dict:
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"]
    return {"ok": True, "blocks": n}


@app.get("/api/day")
def get_day(day: Optional[str] = None) -> dict:
    """Everything the UI needs for one day: that day's blocks plus the inbox."""
    day = day or today()
    _validate_day(day)
    with db() as conn:
        scheduled = conn.execute(
            "SELECT * FROM blocks WHERE day = ? ORDER BY start_min", (day,)
        ).fetchall()
        inbox = conn.execute(
            "SELECT * FROM blocks WHERE day IS NULL ORDER BY updated_at DESC"
        ).fetchall()
    return {
        "day": day,
        "today": today(),
        "blocks": [row_to_dict(r) for r in scheduled],
        "inbox": [row_to_dict(r) for r in inbox],
    }


@app.get("/api/week")
def get_week(start: Optional[str] = None, days: int = 7) -> dict:
    """How loaded each day is — what the week strip shows."""
    days = max(1, min(days, 31))
    start = start or today()
    _validate_day(start)
    first = _date.fromisoformat(start)
    try:
        span = [(first + timedelta(days=i)).isoformat() for i in range(days)]
    except OverflowError:
        # A start near the end of the calendar reaches past it: a refusal, not a 500.
        raise HTTPException(400, "that range runs past the end of the calendar") from None
    with db() as conn:
        rows = conn.execute(
            """SELECT day, COUNT(*) AS blocks, SUM(duration_min) AS minutes
               FROM blocks
               WHERE day BETWEEN ? AND ?
               GROUP BY day""",
            (span[0], span[-1]),
        ).fetchall()
    load = {r["day"]: (r["blocks"], r["minutes"] or 0) for r in rows}
    return {
        "start": span[0],
        "days": [
            {"day": d, "blocks": load.get(d, (0, 0))[0], "minutes": load.get(d, (0, 0))[1]}
            for d in span
        ],
    }


@app.post("/api/blocks", status_code=201)
def create_block(body: BlockIn) -> dict:
    block_id = uuid.uuid4().hex[:12]
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "a block needs a title")
    if body.color is not None and body.color not in PALETTE:
        raise HTTPException(400, f"unknown color {body.color!r}")
    color = body.color or PALETTE[_pick_color()]
    if body.day is not None:
        _validate_day(body.day)
        if body.start_min is None:
            raise HTTPException(400, "a scheduled block needs start_min")
    if body.start_min is not None and body.day is None:
        raise HTTPException(400, "start_min needs a day")
    if body.start_min is not None:
        _check_fits(body.start_min, body.duration_min)
    with db() as conn:
        conn.execute(
            """INSERT INTO blocks
                 (id, title, day, start_min, duration_min, color, icon, notes, done, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (block_id, title, body.day, body.start_min,
             body.duration_min, color, body.icon.strip(), body.notes, now_iso()),
        )
    return _get_block(block_id)


@app.patch("/api/blocks/{block_id}")
def patch_block(block_id: str, body: BlockPatch) -> dict:
    current = _get_block(block_id)
    fields = body.model_dump(exclude_unset=True, exclude={"unschedule"})

    if body.unschedule:
        fields |= {"day": None, "start_min": None}

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
        _validate_day(day)
        _check_fits(start_min, duration)

    if not fields:
        return current
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db() as conn:
        conn.execute(f"UPDATE blocks SET {sets} WHERE id = ?", (*fields.values(), block_id))
    return _get_block(block_id)


@app.delete("/api/blocks/{block_id}", status_code=204)
def delete_block(block_id: str) -> None:
    with db() as conn:
        cur = conn.execute("DELETE FROM blocks WHERE id = ?", (block_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such block")


def _get_block(block_id: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM blocks WHERE id = ?", (block_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such block")
    return row_to_dict(row)


def _validate_day(day: str) -> None:
    """Only the canonical 'YYYY-MM-DD' gets through.

    Python's parser also takes the compact 'YYYYMMDD', which used to be stored exactly
    as sent — and then matched no day or week query, because that string sorts outside
    every canonical range. A block nobody can find is worse than a refused request, so
    the shape is checked here instead of trusted from the parser.
    """
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise HTTPException(400, f"day must be YYYY-MM-DD, got {day!r}")
    try:
        _date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, f"day must be YYYY-MM-DD, got {day!r}") from None


def _check_fits(start_min: int, duration_min: int) -> None:
    if start_min + duration_min > DAY_MIN:
        raise HTTPException(400, "block runs past midnight — shorten it")


def _pick_color() -> int:
    """Rotate the palette so consecutive new blocks look different."""
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"]
    return n % len(PALETTE)


# SPA. Mounted last so it only catches what the API routes above did not.
if STATIC.is_dir():
    app.mount("/", SpaStaticFiles(directory=STATIC, html=True), name="spa")
else:

    @app.get("/")
    def _no_build() -> dict:
        return {"error": "frontend not built", "fix": "cd frontend && npm run build"}
