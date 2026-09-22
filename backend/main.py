"""sundial — a visual day planner.

One process: JSON API + the built SPA on the same origin (no CORS anywhere).
SQLite because it is one user, and `scripts/backup.py` copies it safely.

    uvicorn app:app --host 127.0.0.1 --port 6770

Assembled here, and only assembled: the routers to mount, the hooks to run around serving,
the one route that belongs to the app rather than to a part of it, and the mount that hands
everything else to the built app. The shape of the database is `bootstrap.py`; the day is
`routers/`. `app.py` is the name that command asks for, and it re-exports this.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI

import push
from bootstrap import bootstrap
from routers import blocks, calendar, data, google, week
from routers import push as push_routes  # the routes; `push` above is the sending
from spa import SpaStaticFiles
from store import db

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

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

app.include_router(blocks.router)
app.include_router(calendar.router)
app.include_router(data.router)
app.include_router(google.router)
app.include_router(push_routes.router)
app.include_router(week.router)


@app.get("/api/health")
def health() -> dict:
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"]
    return {"ok": True, "blocks": n}


# SPA. Mounted last so it only catches what the API routes above did not.
if STATIC.is_dir():
    app.mount("/", SpaStaticFiles(directory=STATIC, html=True), name="spa")
else:

    @app.get("/")
    def _no_build() -> dict:
        return {"error": "frontend not built", "fix": "cd frontend && npm run build"}
