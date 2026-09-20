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

Two views, switched from the bar at the bottom; the app remembers which one you were in.

**To-do** (the way in) — the day cut into Anytime / Morning / Afternoon / Evening, each
with a count. White cards, a coloured icon circle, a checkbox on the right. Adding to a
section drops the task after whatever is already in that part of the day rather than on
top of it. "Anytime" is the inbox.

**Calendar** — a 24-hour canvas. Drag to move a block, drag its bottom edge to change
the length, drag from the inbox rail to schedule, double-click empty space for a short
block.

Shared by both: the week strip (today in purple, the day you are viewing on a pill), a
`☀`/`☾` theme switch that is remembered and follows your system by default, and a
detail panel for icon, colour, notes, length, start time, done and delete.

Add it to your iPhone home screen from Safari — it is a real PWA, with an offline
shell and a service worker already listening for notifications.

## Checks

```
cd backend  && env -u PYTHONPATH .venv/bin/pytest -q     # the API rules
cd frontend && npm run check:ui                          # the UI, with real drags
```

The UI check drives headless Chromium with real mouse input and then reads the API
back to confirm the server agrees with what the screen did. It derives its
expectations from the API rather than hardcoding counts, seeds its own data, and
deletes exactly what it created.

## Deployed

Live on the tailnet only, nothing public:

```
https://planner.example.ts.net:8445/
```

`tailscale serve --https=8445` points at `127.0.0.1:6770`. The app runs under the
systemd user unit in `deploy/sundial.service`, installed to
`~/.config/systemd/user/`:

```
systemctl --user status sundial
systemctl --user restart sundial
journalctl --user -u sundial -n 50          # or tail the journal
```

Because it is a unit rather than a hand-started process it comes back after a
reboot (needs `loginctl enable-linger USER`, already on). **A process started by
hand from a shell does not** — that is exactly how this kept serving 502s to a phone
while looking fine on the Pi.

## Not built yet

Recurring routines, notifications, and the agent that turns a paragraph of
brain-dump into a scheduled day. The API is already the seam for that last one — it
is a `POST /api/blocks`.
