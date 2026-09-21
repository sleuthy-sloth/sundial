# What changed, and when. Dates, and what to do about them.

## 0.2.1 — 2026-09-20

Illustrations, and the things a link to this needs.

### Added

- **Artwork for three states**, drawn twice each: an empty timeline, an empty inbox, and a day
  that is genuinely finished. They are the only raster images in the app, they sit straight on
  the canvas with no frame or shadow, and every state keeps its own sentence — the picture is
  what makes the state feel like a room rather than an error. Both themes are in the DOM with
  CSS choosing, so the right one is there at the first paint; the hidden file is not even
  fetched, because a lazy image with no layout box is never in the viewport.
- **An all-clear that has to be earned.** The low-sun pair appears once, at the foot of the
  plan, and only when today had plans and has none left: something still in the inbox, or an
  empty day, does not count. The rule is a pure function (`src/art.js`) with its own tests,
  because "done" and "empty" being different words is the whole point.
- **A favicon**, vector, following the reader's colour scheme the way the app does — plus a
  32px PNG for browsers that will not take an SVG.
- **Real maskable icons**, drawn with the mark inset so Android's crop cannot take the ticks
  (measured at 0.332 of the width, against the 0.4 the safe zone allows).
- **A social card and a README banner**, and the `og:`/`twitter:` tags to point at the card.

### Changed

- The **app icon now follows the stylesheet**: `make_icons.py` reads `--bg`, `--text` and
  `--solar` out of `styles.css` instead of repeating them, so the mark cannot drift away from
  the ledger it belongs to. It was still the pre-redesign blue.
- `theme-color` and the manifest follow the ledger's ground too — the browser chrome had been
  left on the old greys.
- The README says what the app actually does again. Three claims had survived the 0.2.0
  redesign: the view switch at the bottom, white cards with an icon circle, and the week strip.

### Notes

- The supplied illustrations are drawn on their own ground, and the dark ones are about 15/255
  lighter than this app's dark ground — put on the canvas unchanged they showed as rectangles.
  Each file is now matched to the surface it is placed on (the page, or the rail's lighter panel
  for the tray), and the dial's ground is keyed out rather than matched, so the hour rules run
  underneath it. `--check`, which CI runs, fails if either drifts.
- Link previews need `VITE_APP_URL` set in `frontend/.env` and a rebuild. GitHub's own
  repository card is a manual upload and cannot be set from here — see the README.

## 0.2.0 — 2026-09-20

The look, rebuilt around time rather than cards.

### Changed

- **The day is a ledger.** Parchment ground, ink text, solar amber for now and selection,
  twilight for evening. The eight task colours survive as a slim edge instead of a pastel
  bubble; rows sit on hairlines instead of cards; the icon circle is gone.
- **One scale, one spine.** `--hour-h` is 72px, so half an hour is 36px — enough to hold a
  title and a time. Hour rules are faint, open intervals of 30 minutes or more are named, and
  blocks hang off a hairline spine. `--gutter` is in rem so a time never truncates.
- **The header is an instrument.** `SUN 20 SEP` and the time now, a labelled `Plan | Timeline`
  switch in place of the floating capsule, and the week strip and serif weekday are gone.
  The day name itself opens the date picker, so the date is not stated twice.
- **Type is self-hosted**: Atkinson Hyperlegible Next and IBM Plex Mono (OFL), 63KB total,
  hashed like any other asset.
- **Finishing a task has a shape.** The square fills, the row holds for half a second so you
  can read what you checked, then it leaves the list and lands in a counted finished group at
  the foot of its section. It is optimistic — the tap lands before the network answers — and a
  failed write puts the row back. Under reduce-motion there is no travel at all.
- **24-hour time throughout.** It was 12-hour in the list and 24-hour on the timeline; two
  formats for one day was the kind of detail that makes an app feel assembled.
- The completion control is drawn at 19px inside a 44px target.

### Fixed

- **The timeline scrolls, and opens where you are.** The column was taller than its container,
  so the scroller never scrolled and the jump-to-now silently did nothing.

## Unreleased

- The browser checks wait for an outcome instead of betting the machine is fast enough.
  Seven of them asserted against the API or a freshly loaded day a fixed 300-400ms after
  the click that caused it. On a slow CI runner that bet loses, and it did: the delete and
  empty-day checks failed there while passing everywhere else. They poll now, with a
  timeout that still fails the check rather than hanging. Against a backend deliberately
  slowed to 600ms a call, the old suite fails five checks; this one passes all 95.

## 0.1.2 — 2026-09-20

### Fixed

- **An upgrade reaches the phone by itself.** The server sent no `Cache-Control` at all,
  which left the browser to guess a lifetime from each file's age — and it guessed wrong
  for the two files whose names never change, so a phone could keep opening the previous
  app (and the previous service worker) for a while after a deploy. The shell, the
  manifest and the worker now say `no-cache` and are revalidated on every request, while
  the content-hashed files under `/assets` are served as `immutable` for a year, which is
  what their names allow. A worker taking over mid-visit now reloads on the way out rather
  than under the reader's hands, so opening the app shows the new one.

### Added

- `backend/test_spa.py` — the cache policy, pinned against a directory shaped like the
  build so it needs no build to run, plus browser checks that read the headers off the
  live app and confirm the worker is the one serving the page.

## 0.1.1 — 2026-09-20

Nothing here should surprise you when you upgrade: no migration is destructive, and the
database is repaired rather than refused.

### Fixed

- **Typing survives the network.** The editor keeps a draft per field, sends one write at
  a time per block, and ignores a reply that arrived after a newer one. A failed save
  keeps what you typed on screen and can be retried. Before this, a delay or a reordered
  reply could put the old text back, and a failed capture lost what you had written.
- **Editing one block no longer fights another.** Writes are queued per block, and a day
  that loads late can no longer replace the day you are looking at.
- **The API refuses what the database cannot store.** Nulls, blank titles, unknown
  colours and malformed dates come back as 400s instead of 500s or empty rows. Days are
  stored in one canonical form; `migrations/003_canonical_days.sql` repairs rows that
  were not.
- **A half-applied migration cannot strand the database.** Migrations run in a
  transaction, and a connection is closed when the request is done with it.
- **Free time and the day's tally are honest.** A block nested inside another is no
  longer counted twice, so "free" means free.
- **Scheduling puts things where you are looking.** The editor used today's date even
  when you were reading another day. There is now a Day field, and a date and a start
  time are set together.
- **A cancelled gesture writes nothing.** A system gesture or a phone call no longer
  moves a block. An item dragged near midnight takes the latest position that fits.
- **You can use it without a mouse, and with larger text.** Blocks take Enter and Space,
  the editor takes Escape, the phone opens with focus on the panel rather than on the
  keyboard, and sizes are in rem so the browser's text setting is honoured.

### Added

- `scripts/backup.py` — a copy of the database taken through SQLite, not with `cp`,
  because a WAL database has committed writes outside the main file.
- `frontend/src/time.test.js` and `frontend/src/saving.test.js` — the unit tests the
  frontend never had, run in CI.
- `scripts/smoke_release.py` — the release path in one command: a fresh database, an
  upgrade with plans already in it, and a restore from a copy. It runs in CI, and it is
  the only place the migrations are exercised the way the service runs them.
- Browser checks for slow, reordered and failed requests, for the keyboard, for a
  cancelled drag, for a touch tap, and for double text size at phone width.

### Changed

- Dependencies are pinned exactly, split into `backend/requirements.txt` (runtime) and
  `backend/requirements-dev.txt` (tests, which includes the runtime). Direct dependencies
  are pinned; what they pull in is not, which is the one gap left in reproducing a build.
- `caldav` was listed and never imported. Removed.

## 0.1.0

First version: one day, two views over it — an agenda and a timeline — with an inbox for
what has no time yet, SQLite underneath, and one Python process serving both the API and
the app.
