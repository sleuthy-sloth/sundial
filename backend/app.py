"""sundial — a visual day planner.

One process: JSON API + the built SPA on the same origin (no CORS anywhere).
SQLite because it is one user, and `scripts/backup.py` copies it safely.

    uvicorn app:app --host 127.0.0.1 --port 6770
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

import calendar_service
import calendar_sync
import credentials
import export
import google_oauth
import push
from caldav import CalDavError, NotConfigured
from calendar_errors import CalendarError
from spa import SpaStaticFiles
from store import DB_PATH, db  # noqa: F401  (DB_PATH is re-exported: tests and backup use it)

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"
STATIC = ROOT / "static"

PALETTE = ["slate", "sky", "violet", "amber", "emerald", "rose", "teal", "indigo"]
DAY_MIN = 1440


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


class SubscribeIn(BaseModel):
    """A browser's push subscription, exactly as `PushManager.subscribe` hands it over."""

    endpoint: str
    keys: dict[str, str] = Field(default_factory=dict)


class UnsubscribeIn(BaseModel):
    endpoint: str


# How often the app asks whether anything has come due. A minute is the resolution of the
# plan itself — blocks are placed to the minute — so a finer tick would only spend battery
# to be more precise than the thing it is reporting on.
TICK_SECONDS = 60


def _announce_once() -> dict:
    with db() as conn:
        return push.tick(conn)


async def _announce_loop() -> None:
    """Say what has come due, once a minute, for as long as the app is running.

    In a thread, because the send is a blocking network call and this loop shares a process
    with the day: a push service taking its time must not make the app feel slow. The first
    tick is a whole interval away, which is also what stops a restart from re-announcing the
    minute it was restarted in.
    """
    while True:
        try:
            await asyncio.sleep(TICK_SECONDS)
            await asyncio.to_thread(_announce_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A notification that could not be sent is not a reason to stop serving the plan.
            # Nothing was recorded, so nothing is lost and the next tick tries again.
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    announces = asyncio.create_task(_announce_loop())
    try:
        yield
    finally:
        announces.cancel()
        with suppress(asyncio.CancelledError):
            await announces


app = FastAPI(
    title="sundial",
    version="0.5.0",
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


# ----------------------------------------------------------------------- calendar


class SyncIn(BaseModel):
    if_stale_seconds: int = Field(default=0, ge=0, le=86400)


class CalendarPatch(BaseModel):
    ref: str = Field(min_length=1, max_length=500)
    enabled: bool


@app.get("/api/calendars")
def get_calendars() -> dict:
    """What is connected, and what is not — as a normal answer either way.

    An unconfigured calendar is not an error: it is the state a fresh install is in, and
    the interface should be able to say what to do about it instead of showing a failure.
    """
    credentials, why = calendar_service.configuration()
    providers = []
    for source in calendar_service.sources():
        entry = {
            "provider": source.provider,
            "configured": source.configured,
            "why": source.why,
            "last_error": calendar_service.provider_error(source.provider),
        }
        if source.provider == "google":
            entry["account"] = getattr(source.credentials, "account", "") if source.configured else ""
            # Built and tested end to end, and not switched on in the interface: the
            # credentials step cannot be walked until somebody has been through Google's
            # console, so the app says so rather than offering a button that fails.
            entry["coming_soon"] = True
        providers.append(entry)
    return {
        # Kept as the iCloud answer: it is what the rail's Sync control reads, and iCloud is
        # the provider that ships.
        "configured": credentials is not None,
        "why": why,
        "last_sync": calendar_service.last_sync(),
        "calendars": calendar_service.calendars(),
        "providers": providers,
    }


class CredentialsIn(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    fields: dict[str, str] = Field(default_factory=dict)


@app.post("/api/calendars/credentials")
def save_calendar_credentials(body: CredentialsIn) -> dict:
    """Take a credential from the panel and write it into that provider's file.

    The only route in sundial that accepts something secret that a person typed. It answers
    with the provider's state — never with what it was given — and it does not log: the value
    came from a form, and a form is not a reason for a secret to end up in a log file. Which
    keys are allowed, and why, is `credentials.py`.

    Read back rather than assumed: the reply says `configured` only if the provider's own
    reader agrees, so a write that landed somewhere useless cannot look like success.
    """
    try:
        target = credentials.save(body.provider, body.fields)
    except credentials.Refused as exc:
        raise HTTPException(400, str(exc)) from None

    source = next((s for s in calendar_service.sources() if s.provider == target.provider), None)
    return {
        "provider": target.provider,
        # `configured` and `why` come from the provider's own reader rather than from "the
        # write did not raise": for Google, credentials saved without a refresh token are
        # half a connection, and the reply has to be able to say which half is missing.
        "configured": bool(source and source.configured),
        "why": source.why if source else "",
    }


@app.post("/api/calendars/sync")
def sync_calendars(body: Optional[SyncIn] = None) -> dict:
    try:
        return calendar_service.sync(if_stale_seconds=(body or SyncIn()).if_stale_seconds)
    except NotConfigured as exc:
        raise HTTPException(400, str(exc)) from None
    except CalendarError as exc:
        # The sync could not start at all — bad credentials, no route, a server that
        # answered nonsense. A single calendar failing inside a working sync is reported
        # in the body instead, because the rest of the sync did happen.
        raise HTTPException(502, str(exc)) from None


@app.patch("/api/calendars")
def patch_calendar(body: CalendarPatch) -> dict:
    """Switch a calendar off, or back on. A local decision: it survives the next sync."""
    with db() as conn:
        changed = conn.execute(
            "UPDATE calendars SET enabled = ? WHERE ref = ?", (1 if body.enabled else 0, body.ref)
        ).rowcount
    if not changed:
        raise HTTPException(404, "no such calendar")
    return {"ref": body.ref, "enabled": body.enabled}


@app.get("/api/events")
def get_events(day: Optional[str] = None) -> dict:
    """The calendar's own events for one day, series expanded.

    A day rather than a range: this app's unit is the day, and the day is a wall-clock
    thing, so a caller does not get to send instants that disagree with it.
    """
    day = day or today()
    _validate_day(day)
    zone = calendar_sync.server_tz()
    start = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=zone)
    end = start + timedelta(days=1)
    events = calendar_service.events_between(start, end)
    return {"day": day, "count": len(events), "events": events}


@app.get("/api/push/key")
def push_key() -> dict:
    """What a browser needs in order to subscribe, and how many already have.

    The count is here rather than in a status endpoint of its own because the settings panel
    has to be able to tell "you turned this on" from "you turned this on and it is gone" —
    a subscription the push service has forgotten is deleted by the sender, and the panel is
    the only place that becomes visible.
    """
    with db() as conn:
        subscribers = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {"public_key": push.public_key(), "subscribers": subscribers}


@app.post("/api/push/subscribe", status_code=201)
def push_subscribe(body: SubscribeIn) -> dict:
    """Keep a browser's subscription. Re-subscribing updates rather than doubles."""
    try:
        sub = push.subscription(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    with db() as conn:
        push.remember(conn, sub)
        subscribers = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {"endpoint": sub["endpoint"], "subscribers": subscribers}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: UnsubscribeIn) -> dict:
    """Forget one subscription. Turning it off has to work from the device that turned it on.

    A POST rather than a DELETE with the endpoint in the path: an endpoint is a URL with
    slashes and a query string, and a path parameter that has to be escaped twice is a bug
    waiting for the one subscription whose endpoint contains something awkward.
    """
    with db() as conn:
        removed = push.forget(conn, body.endpoint)
        subscribers = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {"removed": bool(removed), "subscribers": subscribers}


@app.post("/api/push/test")
def push_test() -> dict:
    """Send one notification now, so the path can be proved without waiting for an hour."""
    with db() as conn:
        return push.nudge(conn)


IMPORT_CONFIRMATION = "replace everything"


class ImportIn(BaseModel):
    """An import has to say what it is, because what it is is "replace everything"."""

    confirm: str = ""
    document: dict


@app.get("/api/export")
def export_all() -> Response:
    """Everything sundial holds, as one JSON file.

    Served as a download rather than left to be fetched and saved by hand, because the
    filename is the only part of this that a person has to get right.
    """
    with db() as conn:
        document = export.dump(conn, current_schema_version(conn))
    return Response(
        content=json.dumps(document, indent=2, sort_keys=True) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="sundial-{today()}.json"'},
    )


@app.post("/api/import")
def import_all(body: ImportIn) -> dict:
    """Replace everything in the database with the contents of an export.

    Destructive on purpose, and confirmed on purpose: merging sounds gentler but has to
    guess whether two rows with the same id are one thing or two, and it guesses silently.
    "This is my data now" is a promise that can be kept, and the panel says so first.

    Two things it does not do. It does not touch `push_subscriptions`, so restoring your
    data cannot unsubscribe the phone in your pocket. And it does not leave you without a
    way back: the database being replaced is copied first, and the copy is named in the
    answer.
    """
    if body.confirm.strip().lower() != IMPORT_CONFIRMATION:
        raise HTTPException(
            400,
            f'an import replaces everything in sundial. Send "confirm": '
            f'"{IMPORT_CONFIRMATION}" to mean it',
        )
    with db() as conn:
        try:
            tables = export.check(body.document, current_schema_version(conn))
        except export.ExportError as exc:
            raise HTTPException(400, str(exc)) from None
        unknown = export.unknown_columns(body.document, conn)
        if unknown:
            named = ", ".join(f"{t}.{', '.join(c)}" for t, c in unknown.items())
            raise HTTPException(
                400,
                f"that file has columns sundial does not know: {named}. Nothing was changed",
            )
        kept = export.keep_copy(conn, export.database_file(conn))
        try:
            written = export.replace(conn, tables)
        except sqlite3.IntegrityError as exc:
            # A file whose rows contradict each other: two blocks sharing one id, or an event
            # naming a calendar the file does not carry. Left unhandled this is a 500 with a
            # stack trace and no explanation, which is the worst of both — the person learns
            # nothing and cannot tell whether it took. `replace` has already rolled back, so
            # the honest answer is available: a refusal that names what SQLite objected to.
            raise HTTPException(
                400, f"that file contradicts itself: {exc}. Nothing was changed"
            ) from None
        left_alone = conn.execute(
            "SELECT COUNT(*) AS n FROM push_subscriptions"
        ).fetchone()["n"]
    return {
        "replaced": written,
        "kept": str(kept),
        "left_alone": {"push_subscriptions": left_alone},
    }


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


# ------------------------------------------------------------------- google, coming soon


PENDING = google_oauth.Pending()


def _google_configuration() -> Optional[google_oauth.Configuration]:
    try:
        return google_oauth.load_configuration(google_oauth.config_path())
    except NotConfigured:
        return None


def google_redirect(request: Request) -> str:
    """Where Google sends the browser back to.

    Taken from the request's own origin unless google.env names one, so the repository never
    has to contain a hostname — the same reasoning as VITE_APP_URL — and set explicitly only
    when something in front of the app rewrites Host.
    """
    configured = _google_configuration()
    if configured is not None and configured.redirect_uri:
        return configured.redirect_uri
    return str(request.base_url).rstrip("/") + "/oauth/google/callback"


def _page(title: str, body: str, *, ok: bool) -> HTMLResponse:
    """The one page in this app that is not the app.

    A browser arrives at these two routes rather than fetch(), so they answer with HTML. It
    matters more than usual here: Google refuses to render its consent screen inside an
    embedded webview, which is what the phone's client is, so the flow finishes in Safari
    and lands on this page rather than back inside the app.
    """
    accent = "#8A5A2B" if ok else "#8D5A5A"
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)} — sundial</title></head>"
        "<body style=\"background:#F4F1E8;color:#25231F;font:16px/1.6 system-ui,sans-serif;"
        "margin:0;padding:2.5rem 1.5rem\"><main style=\"max-width:32rem;margin:0 auto\">"
        f"<h1 style=\"font-size:.8rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;"
        f"color:{accent}\">{html.escape(title)}</h1>"
        f"<p>{body}</p>"
        f"<p><a href=\"/\" style=\"color:{accent}\">Back to sundial</a></p>"
        "</main></body></html>"
    )


@app.get("/oauth/google/start")
def google_start(request: Request):
    """Send the browser to Google's consent screen.

    The scope asked for is `calendar.readonly`: read-only in the grant itself, not only in
    this app's behaviour, so the token cannot write to a calendar even if it is misused.
    """
    configuration = _google_configuration()
    if configuration is None:
        raise HTTPException(400, "Google is not set up yet: create google.env with a client id "
                                 "and secret from console.cloud.google.com")
    redirect = google_redirect(request)
    pending = PENDING.start(redirect)
    return RedirectResponse(
        google_oauth.authorize_url(
            configuration,
            redirect_uri=redirect,
            state=pending.state,
            challenge=google_oauth.challenge_for(pending.verifier),
        ),
        status_code=302,
    )


@app.get("/oauth/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
) -> HTMLResponse:
    """Where Google sends the browser back to, with an authorization code.

    Every failure here is a page rather than a JSON error, because the thing looking at it is
    a person in a browser tab. None of them carry a credential: the code, the verifier and
    the tokens are never named in what is rendered.
    """
    if error:
        return _page("Google said no",
                     f"Google refused the connection: {html.escape(error)}.", ok=False)
    if not code:
        return _page("Nothing to connect",
                     "That address did not carry an authorization code.", ok=False)

    try:
        pending = PENDING.claim(state)
    except CalendarError as exc:
        return _page("That link has expired", html.escape(str(exc)), ok=False)

    configuration = _google_configuration()
    if configuration is None:
        return _page("Google is not set up",
                     "The credentials went missing between starting and finishing. "
                     "Check that google.env is still there.", ok=False)

    try:
        tokens = google_oauth.exchange(
            configuration,
            code=code,
            verifier=pending.verifier,
            redirect_uri=pending.redirect_uri,
        )
    except CalendarError as exc:
        return _page("Google refused", html.escape(str(exc)), ok=False)

    google_oauth.save(
        google_oauth.config_path(),
        GOOGLE_REFRESH_TOKEN=tokens.refresh_token,
        GOOGLE_ACCOUNT=tokens.account,
    )
    return _page(
        "Connected",
        "sundial can now read your Google calendars"
        + (f" ({html.escape(tokens.account)})" if tokens.account else "")
        + ", and nothing else — the permission it holds cannot change anything. Google is "
        "not switched on in the interface yet, so this is as far as it goes for now.",
        ok=True,
    )


# SPA. Mounted last so it only catches what the API routes above did not.
if STATIC.is_dir():
    app.mount("/", SpaStaticFiles(directory=STATIC, html=True), name="spa")
else:

    @app.get("/")
    def _no_build() -> dict:
        return {"error": "frontend not built", "fix": "cd frontend && npm run build"}
