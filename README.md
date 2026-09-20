# sundial

A visual day planner that runs on my own hardware. Tasks sit in an inbox until you
drag them onto a 24-hour timeline; the plan lives server-side, so every device sees
the same day.

Named for the obvious: a day, drawn as a dial.

## Run it

```
bash run.sh          # builds the SPA if missing, then serves everything on :6770
```

Open http://127.0.0.1:6770. A fresh clone needs the dependencies first:

```
env -u PYTHONPATH python3 -m venv backend/.venv
env -u PYTHONPATH backend/.venv/bin/pip install -r backend/requirements.txt
bash scripts/setup_frontend.sh          # npm install + build
```

(`env -u PYTHONPATH` matters on this host: the agent's shell injects its own
`PYTHONPATH`, and pip then silently installs a hollow venv.)

## How it is put together

One Python process serves the API and the built SPA on the same origin, so there is
no CORS to get wrong and no second port to think about. SQLite holds a single table;
a backup is `cp backend/sundial.db backup.db`.

```
backend/app.py        API + the block rules (FastAPI)
backend/test_app.py   12 tests over those rules
frontend/src/App.jsx  the timeline, inbox and editor
frontend/e2e/         UI check that drives a real browser
```

The whole data model is one table, `blocks`. A block is in the inbox while its `day`
and `start_min` are NULL, and scheduled once they are set. Those two travel together:
the API refuses one without the other, because a block sitting "nowhere at 14:00" is
a bug waiting to happen.

## Using it

- Type in the inbox box, press Enter. Nothing gets a time until you give it one.
- Drag an inbox item onto the timeline to schedule it. It lands under the pointer.
- Drag a block to move it; drag its bottom edge to change the length.
- Double-click empty timeline space for a 30-minute block.
- Click a block for colour, notes, length, done, delete.

## Checks

```
cd backend  && env -u PYTHONPATH .venv/bin/pytest -q     # the API rules
cd frontend && npm run check:ui                          # the UI, with real drags
```

The UI check drives headless Chromium with real mouse input and then reads the API
back to confirm the server agrees with what the screen did. It derives its
expectations from the API rather than hardcoding counts, seeds its own data, and
deletes exactly what it created.

## Not built yet

Recurring routines, notifications, and the agent that turns a paragraph of
brain-dump into a scheduled day. The API is already the seam for that last one — it
is a `POST /api/blocks`.
