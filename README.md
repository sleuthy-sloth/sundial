# sundial

A visual day planner that runs on your own hardware. The day is a list you can read at a
glance and a 24-hour canvas you can drag blocks around on, over one SQLite file and a
single process.

![The sun on the left, a crescent moon on the right, and a ruler of hours between them](frontend/public/brand/sundial-readme-banner.webp)

[![tests](https://github.com/sleuthy-sloth/sundial/actions/workflows/tests.yml/badge.svg)](https://github.com/sleuthy-sloth/sundial/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![python 3.13](https://img.shields.io/badge/python-3.13-3776ab.svg)
![node 22+](https://img.shields.io/badge/node-22%2B-5fa04e.svg)

![The to-do list: the day in sections, with one task already done](docs/screenshots/todo-light.png)

| The 24-hour canvas | On a phone | Dark |
|:--:|:--:|:--:|
| ![The calendar view](docs/screenshots/calendar-light.png) | ![The phone layout](docs/screenshots/phone.png) | ![The dark theme](docs/screenshots/todo-dark.png) |

## What it does

Two views of the same day, switched from the header. It remembers which one you were in.

**Plan** — the way in. The day is cut into Anytime, Morning, Afternoon and Evening, each
with a count and the span it actually covers. Rows sit on hairlines with the time in the
gutter: a slim colour edge, the title, how long it takes, and a square to fill when it is
done. Adding to a section puts the task *after* whatever is already in that part of the
day rather than on top of it. Anytime is the inbox.

**Timeline** — a 24-hour canvas. Drag a block to move it, drag its bottom edge to change
the length, drag from the inbox to schedule it, double-click empty space for a short
block.

Shared by both: a header that reads like an instrument (the day, the time now, and which
view you are in), light and dark themes that follow your system, the free time between
tasks drawn and named rather than implied, and a detail panel for icon, colour, notes,
length, start time, done and delete. An emoji still earns its place on a timeline block,
where it helps you find one at a glance.

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

### The look

Parchment ground, ink text, solar amber for now and for selection, twilight for evening —
and nothing decorative after that. The two views are one ledger seen two ways: a rail with a
faint hour rule, blocks hanging off a thin spine, open intervals drawn as measured, named
bands. Rows are separated by a hairline, not raised on cards; the colour you pick for a task
is a slim edge rather than a pastel bubble; completion is a square you fill rather than a
hollow circle. Time is set in IBM Plex Mono and everything else in Atkinson Hyperlegible
Next, both self-hosted, so the columns of numbers line up and nothing is fetched from
anywhere.

Contrast is measured, not guessed, and the numbers are in the comments beside each token in
`styles.css`. Nothing rests with a shadow: the only one in the app appears while you are
holding something. Motion explains time and manipulation only — a block snapping as you drag
it, a task filling its box and then leaving the list a beat later, under a reduce-motion
setting that turns all of it off.

The built app is served with an explicit cache policy rather than the browser's guess: the
shell, the manifest and the service worker must be revalidated on every request, while the
content-hashed files under `/assets` are kept for a year. That split is what lets an
upgrade arrive on the phone instead of being shadowed by yesterday's copy.

### The artwork

Three states get a picture: an empty timeline, an empty inbox, and a day that is genuinely
finished. They are the only raster images in the app. Each is drawn twice, once per theme, and
both files sit in the DOM with CSS choosing between them — so the right one is showing at the
first paint, and a dark-theme reader never sees the light one flash past. They are decorative:
each state's own sentence is still what explains it, and the artwork is hidden from a screen
reader rather than described twice.

The originals are in `art/source/`, and the files the app ships are built from them by
`scripts/make_art.py`: 800px wide, under 60KB each, and light and dark the same pixel size so
switching theme cannot move the page. The script takes the highest quality that still fits the
budget rather than a fixed one — flat line art with paper grain costs more to encode than a
photograph does, and guessing a quality number is how a budget quietly stops being met.

One step in it is worth knowing about. The supplied illustrations are drawn on their own ground,
and the dark ones are about 15/255 lighter than this app's dark ground, so putting them straight
on the canvas shows a rectangle of the wrong beige. So each file is matched to the surface it is
actually placed on — the page for the dial and the low sun, the rail's own panel colour for the
tray, because the rail is measurably lighter than the page — by shifting only the pixels within
40/255 of the original ground. The strokes, the grain and the amber beam do not move.

The dial is the exception, because it sits on the hour rules: its ground is keyed out instead, so
the rules run underneath the drawing rather than stopping at its edges. Both shapes are verified
in `--check`, along with the budgets, the matching dimensions and the absence of metadata, and CI
runs it — a change to the palette cannot quietly leave the artwork sitting on a tile.

```
env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py           # rebuild them
env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py --check   # verify the budgets
env -u PYTHONPATH backend/.venv/bin/python scripts/make_icons.py         # the icon and favicon
```

The social card is `frontend/public/brand/sundial-og.jpg` (1200x630) and the banner at the top
of this file is that directory's `sundial-readme-banner.webp` (2560x320).

### The app icon

Drawn, not traced: the dial, its twelve hour ticks, the triangular gnomon, the pedestal it stands
on and the amber shadow that gnomon casts are all geometry, and every number is a fraction of the
dial's radius measured off the reference. Nothing here carries a JPEG artefact, and the colours
are read out of `styles.css`, so the icon cannot drift from the ledger it belongs to.

It is generated in two layouts, because a launcher picks the shape rather than asking:

- **`standard`** — the dial at 78% of the canvas: 32, 48, 180, 192 and 512px, the apple-touch
  icon, and `favicon.svg`, which is the same geometry as vector.
- **`maskable`** — the dial at 70%, so the whole ring and every other element sit inside the
  central safe circle with charcoal still reaching every edge. Android may keep as little as the
  middle 70% of a maskable icon; at 78% it would take the edge of the ring.

`--check` measures where the ink actually ends in both layouts rather than trusting the geometry
to have worked out, and CI runs it. The vector and the raster are compared against each other in
the browser suite too: a browser paints the SVG and Pillow draws the PNGs, and two renderers can
drift apart without either looking wrong on its own.

**Link previews need one setting.** The app writes the card into its own `og:` and `twitter:`
tags, but with no host set those stay relative: a visitor's browser resolves them and a crawler
will not. Set `VITE_APP_URL` in `frontend/.env` to your own address and rebuild. There is no
default, deliberately — a wrong address baked into a build is worse than no preview.

**GitHub's repository card is a manual step.** Nothing in this repo can set it: the social
preview is uploaded by hand, once, at Settings → Social preview → *Upload an image*, and the file
to upload is `frontend/public/brand/sundial-og.jpg`. Changing it later means uploading again,
not committing.

```
backend/app.py              the API and the block rules (FastAPI)
backend/calendar_sync.py    iCalendar ⇄ the local event model, and the conflict rules
backend/migrations/         numbered .sql files, applied on boot
backend/spa.py              serving the built app, and how long each file may be kept
backend/test_*.py           82 tests
scripts/smoke_release.py    the release path: fresh start, upgrade, restore
scripts/make_art.py         the artwork, and the budgets CI checks it against
scripts/make_icons.py       the app icon and favicon: measured geometry, two layouts
frontend/src/App.jsx        state and layout only
frontend/src/art.js         when the all-clear artwork is allowed to appear
frontend/src/components/    Header, Agenda, Row, Timeline, Block, Inbox, Editor, Glyph,
                            LedgerArt
frontend/src/assets/        the empty-state artwork, and the two self-hosted fonts
frontend/e2e/ui_check.mjs   141 browser checks, with real mouse input
frontend/e2e/screenshot.mjs regenerates the images above
frontend/src/art.test.js    unit tests for the all-clear rule (node --test)
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
cd backend  && env -u PYTHONPATH .venv/bin/pytest -q   # 82 tests
cd frontend && npm test                                # 25 unit tests, node --test
cd frontend && npm run check:ui                        # 141 browser checks
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

v0.1.2. The last two were about trust rather than features: it keeps what you type, the day
view describes the day accurately, and an upgrade now reaches the phone on its own. The
honest gaps:

- **Calendar sync is half built.** Two providers, one model: the schema, the iCalendar
  conversion and the conflict rules are written and tested; the transports are not. iCloud
  will be CalDAV with an app-specific password. Google cannot be, because password-based
  CalDAV was switched off in 2024, so it needs the REST API behind OAuth.
- No repeating tasks or routines yet.
- Notifications: the service worker is in place and listening, nothing sends yet.
- The timeline opens at the hour you are in, which it never actually did: the column was
  taller than its container, so it never scrolled and the jump-to-now was a no-op.

MIT licensed — see [LICENSE](LICENSE).
