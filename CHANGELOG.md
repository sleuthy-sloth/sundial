# What changed, and when. Dates, and what to do about them.

## 0.5.0 — 2026-09-21

A credential can be typed into the panel — the step that was missing between a sync that works
and a setup that works.

- **Connect from the calendar rail.** An Apple ID and an app-specific password, written into
  `icloud.env` at 0600. Until now, connecting meant editing a file on the box, which for a
  single-user app served from a Pi is most of the work.
- **One write path, one allowlist.** `env_file.py` is the 0600-by-rename writer both credential
  files now use — extracted rather than copied — and `credentials.py` is the table of which keys
  each file may hold. The refresh token is deliberately not in that table: Google's callback
  owns it, and a route that could accept one could point sundial at somebody else's calendar.
- **A value cannot smuggle in a second key.** The file is one key per line, so a value holding a
  line break is refused rather than written. That rule and the allowlist were both checked by
  removing them and watching the tests fail.
- **The reply is a state, never an echo.** Saving answers with whether that provider is
  configured and why not. What was typed is never returned, logged, or repeated in an error.
- **"Saved" is not "worked".** The panel says connected as soon as the file is right; the sync
  it then runs is the only thing that can say whether the password is, so a wrong password reads
  as a calendar error and not as a form error.
- **The suite cleans up after itself.** The browser check that types a credential writes to a
  file the suite is told about and removes it again — and fails with instructions rather than
  writing the repository's own `icloud.env` if it is not told where that file is.
- **iCloud is still the only provider switched on.** Google gained a way to receive its client
  id and secret; it still says "coming soon".

## 0.4.0 — 2026-09-21

Google, built and not switched on — plus the second provider the engine needed to have.

- **A second provider, without touching the first.** The sync engine now asks each provider for
  a session and a list of calendars, and runs the same conflict rules over both. iCloud's rules
  are unchanged, and a test pins the two providers' mappings to each other so they cannot drift.
- **Google over the REST API, not CalDAV.** Google's CalDAV endpoint only accepts the full
  `calendar` scope, which is write access to every calendar in the account. REST accepts
  `calendar.readonly`, so the grant itself is read-only and "nothing goes back out" survives.
- **An OAuth flow that is finished, not sketched**: PKCE, a single-use state, a token file
  written 0600, and a `describe()` that redacts the client secret, the refresh token, the code
  and the PKCE verifier from anything Google's error body might quote back.
- **A provider is a thing that can fail on its own.** One provider refusing to list its
  calendars no longer takes the other's sync down with it, and a failure that belongs to a
  whole provider — no calendar row to hang it on — is reported where the rail can see it.
- **`palette.py` and `calendar_errors.py`**: the eight colours and the error vocabulary both
  transports share, rather than duplicated "just for now".
- **The interface says "coming soon", in words.** No dead button: while Google has no
  credentials there is a sentence, not a control that could only fail.
- **iCloud is untouched.** Same credentials file, same 7-back/60-forward window, same rules.

## 0.3.0 — 2026-09-21

Calendar sync: the half that was missing. The schema, the iCalendar conversion and the
conflict rules were already written and tested, and nothing could get an event in. Now
iCloud does, read-only, over CalDAV with an app-specific password.

### Added

- **A CalDAV transport** (`backend/caldav.py`): principal and calendar-home discovery, the
  calendar list with each one's own colour and ctag, and a `calendar-query` REPORT over a
  time window. No database in it, so the protocol is tested against scripted HTTP replies
  and the storage rules are tested without a server.
- **A sync engine** (`backend/calendar_service.py`) and the endpoints that expose it:
  `GET /api/calendars`, `POST /api/calendars/sync` (with `if_stale_seconds`, so opening a
  view can ask without hammering iCloud), `PATCH /api/calendars` to switch a calendar off,
  and `GET /api/events?day=` for the day's own events.
- **The calendar panel**, in the rail: what is connected, when it last synced, each calendar
  with its colour and a shown/hidden control, and what is on the day. Read-only, and the
  only controls in it change what sundial does, never the calendar.
- `scripts/check_calendar.py`: connect by hand, list the calendars, count the events, and
  `--sync` to store them. Exit codes meant for a timer — 0 fine, 1 not configured, 2 refused.
- `docs/calendar-sync.md`, the specification, including why a fetch has to complete before
  anything is deleted from it.

### Changed

- `backend/store.py` holds the database handle, so the API and the sync engine can both open
  a connection without importing each other.
- `httpx` is a runtime dependency now rather than only a test one.
- The README's status section had been sitting at v0.1.2 through three releases.

### Fixed

- **A first sync imported nothing at all.** Discovery stored each calendar's ctag, and the
  sync that followed compared that value against itself and skipped the fetch — so a newly
  connected calendar stayed empty until something else in iCloud happened to change. A ctag
  is a cursor, not a description: it is written only after a fetch that worked.
- Event rows were stamped with the *object's* own href as their `calendar_ref` instead of the
  collection's. With foreign keys enforced that insert fails outright. The type checker
  found it; a test now pins the collection in place.
- The panel hid stored events whenever the credentials file was missing, so moving the
  config looked like losing the calendar. Being able to sync and having already synced are
  different facts: the status line says "not connected · last synced 12 min ago", and the
  events stay visible.
- The automatic sync fired before the status had loaded, so a rail built to say
  "add icloud.env" instead displayed a filesystem path as its note.

### Notes

- **What a sync may delete is bounded twice.** Only a fetch that completed may reconcile at
  all — a REPORT that answered 500 must not read as "these events stopped existing" — and
  only rows that fetch actually asked about, which means an event starting inside the window
  and a series only when its first occurrence is. Falsified by removing the first rule: the
  test fails and both stored events are gone.
- Mapping a calendar's colour onto sundial's eight took four attempts, all documented in
  `_colour_distance`. Distance in RGB put Apple's red on amber. So did redmean. So did plain
  Euclidean distance in Lab — because rose is a dark *desaturated* brick, and amber carries
  more red in every one of those spaces. Red's hue is 25° from rose's and 48° from amber's,
  and hue is what the person picking a colour meant.
- **The visual snapshots were passing on luck.** A tightened threshold caught
  `desktop-timeline-light` differing by 0.16% of pixels with a mean of 1.06 — the timeline's
  scroll position follows the clock (half an hour before now, minus 60px), so a couple of
  minutes between two runs shifts the whole column a couple of pixels. Every earlier pass had
  simply happened to land in the same minute. The snapshot block now freezes the page's clock
  at a fixed moment, so the pictures contain a fixed time, and a difference in them is a real
  difference.
- The social-card check fetched the *address the page advertises*. Since a deployment sets
  `VITE_APP_URL` so crawlers get an absolute address, that fetch is cross-origin from whatever
  server the checks run against, and it took the run down with an uncaught `TypeError`. It now
  fetches the same path from the server under test and checks the advertised address
  separately — the more interesting assertion, as it happens.
- The timeline click check assumed the app's pixel scale rather than measuring it; at an exact
  half-step boundary that decided which way the snap went. It reads `--hour-h` from the page
  now, and allows a snap step of rounding.
- An edit arriving in the same second as our own sync is deferred rather than applied: the
  inherited rule is that a tie goes to the local copy, and the clock cannot separate the two.
  It is not lost — the next sync takes it. A `SEQUENCE` bump decides it immediately, which is
  what a calendar actually sends.

## 0.2.3 — 2026-09-21

Focus, semantics, and a way to see a visual change before it ships.

### Added

- **One focus treatment for the whole app.** `:focus-visible` only, so a mouse click does not ring
  every button anyone touches; a 2px solar ring with a 2px offset, which measures 4.3:1 against the
  ground it is drawn on — clear of the 3:1 WCAG asks of a non-text indicator. Two capture fields
  used to remove the outline and change their border colour instead, which is a one-pixel signal a
  colour-blind reader cannot see at all; the border stays as a second cue and the ring is back.
- **Automated accessibility checks** in the browser suite: axe-core over the plan in light and the
  timeline in dark, a real tab-through that measures the ring at every stop (15 stops, minimum
  contrast 4.3:1), and a guard that fails if `outline: none` reappears in the built stylesheet.
- **Visual regression snapshots**: desktop in both themes, the phone plan, three empty states, and
  the icon under its launcher masks. Baselines are committed and the diff runs in the browser, so
  there is no image library in the toolchain.
- **`CONTRIBUTING.md`**, and `main` is protected: both CI jobs required, force pushes and deletions
  blocked, a pull request required of anyone who is not the owner, and linear history deliberately
  off because the repo merges with `--no-ff`.

### Changed

- **A row is a container, not a control.** It was a `role="button"` with a real checkbox button
  inside it — an interactive control nested in an interactive control, which a screen reader cannot
  announce and which some browsers cannot reach by keyboard at all. The completion square and the
  button that opens the editor are siblings now. Timeline blocks are real `<button>`s for the same
  reason, which also deletes the hand-written Enter/Space handler that the browser supplies itself.
- Every `<button>` in the app states its type, because the default is `submit`.

### Fixed

- **Text on a solar fill** was parchment-on-amber in the dark theme: 1.96:1, caught by axe. There is
  an `--on-solar` token now (6.0:1), because the token for ink is not the token for ink on amber.
- **The page had no `h1`.** The day is one now, with the date-picker button inside the heading rather
  than a heading inside a button.
- **The timeline was a scroll region with nothing focusable in it**: unreachable without a mouse.
  It is a tab stop, with an inset ring so the focus is not clipped by its own box.

### Notes

- The "opens at the hour you are in" check asserted `scrollTop > 0`, which is false for the first
  eighty minutes of every day: the app scrolls to half an hour ago minus 60px, so just after
  midnight the correct position IS the top. It passed all evening and failed at 00:20 with nothing
  wrong in the app — and the released build behaved identically, which is what proved it was the
  check and not the code. It now computes the position the app's own rule implies.
- `art/source/` holds the as-received copies, not the artist's masters: their own EXIF credits a
  photo manager, i.e. they were re-encoded before they arrived. `art/source/README.md` documents
  what that costs and what improves with a real original; `make_art.py --check` records their hashes
  and refuses to let one be swapped quietly.
- `VITE_APP_URL` is set at deployment in `frontend/.env.local` (gitignored), so the social tags are
  absolute on the box that serves them while the repo stays free of that host's name.

## 0.2.2 — 2026-09-20

An app icon that is geometry, in the two shapes a launcher asks for.

### Changed

- **The icon is redrawn from the reference as clean vector geometry**: the ring, twelve hour
  ticks, the triangular gnomon, the trapezoidal pedestal it stands on, and the amber wedge the
  gnomon casts. Every measurement is a fraction of the dial's radius, so nothing is traced and
  nothing carries a JPEG artefact.
- **Two layouts.** `standard` puts the dial at 78% of the canvas (32, 48, 180, 192 and 512px, the
  apple-touch icon, and `favicon.svg`); `maskable` puts it at 70% so Android's crop cannot reach
  the ring, with charcoal still solid to every edge. Before, one inset served both jobs: the mark
  was small in a favicon and still only just inside a round mask.
- The favicon is the mark as vector, and the manifest now declares every size it ships.

### Verified, not assumed

- `--check` measures where the ink actually ends in each layout and fails if it leaves the safe
  circle — falsified by drawing the maskable at 78%, which it caught.
- The maskable file is previewed under a circle, a squircle, a rounded square and two Android
  adaptive masks before being committed (`docs/screenshots/art/icon-masks.png`). The standard file
  under the same masks shows what the wrong layout costs: a round mask takes its ring.
- A browser check rasterises `favicon.svg` and `icon-512.png` and compares them, because a
  browser paints one and Pillow draws the other, and two renderers can drift apart without either
  looking wrong alone.

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
