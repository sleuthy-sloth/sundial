# sundial

A visual day planner that runs on your own hardware. The day is a list you can read at a
glance and a 24-hour canvas you can drag blocks around on, over one SQLite file and a
single process.

[![tests](https://github.com/sleuthy-sloth/sundial/actions/workflows/tests.yml/badge.svg)](https://github.com/sleuthy-sloth/sundial/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![python 3.13](https://img.shields.io/badge/python-3.13-3776ab.svg)
![node 22+](https://img.shields.io/badge/node-22%2B-5fa04e.svg)

![The to-do list: the day in sections, with one task already done](docs/screenshots/todo-light.png)

| The 24-hour canvas | On a phone | Dark |
|:--:|:--:|:--:|
| ![The calendar view](docs/screenshots/calendar-light.png) | ![The phone layout](docs/screenshots/phone.png) | ![The dark theme](docs/screenshots/todo-dark.png) |

## What it does

Two views of the same day, switched from the bar at the bottom. It remembers which one
you were in.

**To-do** — the way in. The day is cut into Anytime, Morning, Afternoon and Evening, each
with a count. White cards, a coloured icon circle, a checkbox on the right, and a time
range once a task has one. Adding to a section puts the task *after* whatever is already
in that part of the day rather than on top of it. Anytime is the inbox.

**Calendar** — a 24-hour canvas. Drag a block to move it, drag its bottom edge to change
the length, drag from the inbox to schedule it, double-click empty space for a short
block.

Shared by both: a week strip (today in the accent colour, the day you are viewing on a
pill), light and dark themes that follow your system, an activity icon per task, the free
time between tasks drawn rather than implied, and a detail panel for icon, colour, notes,
length, start time, done and delete.

Install it to your phone's home screen from Safari or Chrome — it is a real PWA, with an
offline shell. The service worker already handles a push notification; nothing sends one
yet, and nothing can until a sending side exists.

### The house rules

These are features, not styling:

- Nothing signals lateness with red or with urgency. A task from this morning you never
  got to simply sits there.
- No streaks, no scores, no "you missed three tasks", no confetti.
- Empty states are honest and quiet.
- 44px touch targets, and every primary action is reachable with one thumb.
- Dark mode, larger text and reduced motion are all honoured.

**No AI, deliberately.** No co-planner, no automatic prioritising, no suggestions. If you
do want an assistant drafting your day, point one at the API — it is a `POST /api/blocks`.

## Run it

```
bash run.sh          # builds the app if it is missing, then serves everything on :6770
```

Open <http://127.0.0.1:6770>. A fresh clone needs its dependencies first:

```
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt   # runtime + tests
bash scripts/setup_frontend.sh          # npm install + build
```

(If your shell exports a `PYTHONPATH`, run the pip line as `env -u PYTHONPATH …`: an
inherited one makes pip install into a hollow venv.)

## How it is put together

One Python process serves the API and the built app on the same origin, so there is no
CORS to get wrong and no second port to think about. SQLite holds the data, in WAL mode:
`scripts/backup.py` is how you copy it (see [Backup and restore](#backup-and-restore)).

```
backend/app.py              the API and the block rules (FastAPI)
backend/calendar_sync.py    iCalendar ⇄ the local event model, and the conflict rules
backend/migrations/         numbered .sql files, applied on boot
backend/test_*.py           77 tests
scripts/smoke_release.py    the release path: fresh start, upgrade, restore
frontend/src/App.jsx        state and layout only
frontend/src/components/    Header, WeekStrip, Agenda, TaskCard, Timeline, Block,
                            Inbox, Editor, TabBar, Glyph
frontend/e2e/ui_check.mjs   91 browser checks, with real mouse input
frontend/e2e/screenshot.mjs regenerates the images above
frontend/src/saving.test.js unit tests for the editing pieces (node --test)
frontend/src/time.test.js   unit tests for the day arithmetic (node --test)
scripts/backup.py           copy the database safely, and put a copy back
deploy/sundial.service      systemd user unit
```

The plan itself is one table, `blocks`. A block is in the inbox while its `day` and
`start_min` are NULL, and scheduled once they are set. Those two travel together — the
API refuses one without the other, because a block sitting "nowhere at 14:00" is a bug
waiting to happen.

Imported calendar events live in their own table rather than in `blocks`, because a
calendar holds things that are not plans: an all-day event is a date rather than an
instant, and a multi-day event cannot fit an invariant that says a block stays inside one
day. Keeping them apart means `blocks` keeps meaning "the day I made", and sync only has
to move rows between two shapes it owns.

## Backup and restore

The database runs in WAL mode, so a committed write sits in `sundial.db-wal` until a
checkpoint folds it into the main file. **Copying `sundial.db` by hand can therefore miss
the thing you just saved** — and the copy is still a valid database, so nothing complains
until you go looking for a row that is not there. Copy it through SQLite instead:

```
python3 scripts/backup.py                # writes backend/sundial-<date>.db
python3 scripts/backup.py --to ~/plans.db
```

To put one back, stop the service first:

```
systemctl --user stop sundial
python3 scripts/backup.py --restore ~/plans.db
systemctl --user start sundial
```

A restore keeps the database it replaced beside it as `sundial.replaced-<date>.db`, and
removes the old `-wal`/`-shm` files, which belong to the database being replaced rather
than the one arriving.

Back up before upgrading. Reverting to the previous version does not undo a migration:
the new schema stays, and the old code no longer knows how to read it.

## Checks

```
cd backend  && env -u PYTHONPATH .venv/bin/pytest -q   # 77 tests
cd frontend && npm test                                # 18 unit tests, node --test
cd frontend && npm run check:ui                        # 91 browser checks
env -u PYTHONPATH backend/.venv/bin/python scripts/smoke_release.py
```

The browser checks drive headless Chromium with real mouse input — actual drags, not
synthesised events — then read the API back to confirm the server agrees with what the
screen did. They derive their expectations from the API instead of hardcoding counts,
seed their own data, and delete exactly what they created. They also hold requests open,
answer them out of order and fail them on purpose, because a phone on a bad connection
does all three and none of it may lose what was typed.

To regenerate the screenshots above, start a second instance against a throwaway database
and run the shooter. It refuses to run against a database that already has plans in it:

```
SUNDIAL_DB=/tmp/shots.db PORT=6771 bash run.sh &
cd frontend && npm run shots
```

## Deploying

The app binds `127.0.0.1:6770` and expects something in front of it. On a tailnet, one
command gives you HTTPS that only your own devices can reach:

```
tailscale serve --bg --https=8445 http://127.0.0.1:6770
```

**There is no login.** sundial trusts whoever reaches the port, which is the right trade for
one person's planner on a private tailnet and the wrong one for anything public. Keep it on
a tailnet or behind a proxy that authenticates. `tailscale serve` is private to your own
devices; `tailscale funnel` on the same port would publish the day to the internet.

`deploy/sundial.service` is a systemd user unit — adjust the paths to where you cloned
this, then:

```
install -Dm644 deploy/sundial.service ~/.config/systemd/user/sundial.service
systemctl --user daemon-reload && systemctl --user enable --now sundial
loginctl enable-linger $USER       # so it keeps running with nobody logged in
```

Use a unit rather than a hand-started process. A process started from a shell does not
come back after a reboot, and the failure is quiet: the reverse proxy keeps its mapping
while the port behind it is empty, so the app looks dead from a phone while every check
you run on the host still passes.

## Branches

`main` is the published state. Work lands on `development` and merges into `main` when it
is ready, so what is on `main` is always a version that runs.

## Status

v0.1.1. This one was about trust rather than features: it keeps what you type, and the day
view describes the day accurately. The honest gaps:

- **Calendar sync is half built.** Two providers, one model: the schema, the iCalendar
  conversion and the conflict rules are written and tested; the transports are not. iCloud
  will be CalDAV with an app-specific password. Google cannot be, because password-based
  CalDAV was switched off in 2024, so it needs the REST API behind OAuth.
- No repeating tasks or routines yet.
- Notifications: the service worker is in place and listening, nothing sends yet.
- After an upgrade the service worker can still serve the previous app until the page is
  reloaded. Versioned assets are the fix; a hard reload is the workaround.
- On a wide window the timeline is taller than the viewport, so the page scrolls instead
  of the timeline, and the scroll-to-now when you open a day does nothing.

MIT licensed — see [LICENSE](LICENSE).
