# What changed, and when. Dates, and what to do about them.

## 0.10.1 — 2026-09-21

**The glance is in the app, not in somebody else's.** 0.10.0 shipped today's plan as a rich-card
payload for Cadu, an iOS client that draws cards like that. It was the wrong home for it: sundial
is a public planner, and a feature that only works if you also install a second app is not a
feature this repo should be carrying. The card script and its tests are gone. Whatever they were
for now lives where the day already is.

What they were for was knowing what you are supposed to be doing without reading a list, and the
plan says it in one line at the top of Today:

    NOW   Write the thing    until 10:30 · 30m left
    NEXT  Standup            at 11:30 · in 1h

- **On any other day it says nothing at all.** There, the same sentence would be a claim about an
  hour that has not happened yet. It is absent on an empty day and on a finished one too: the
  sections below already show what is left, and the all-clear already owns "you are done".
- **"Now" is the block's own half-open interval** — current at its starting minute, over at its
  ending minute, the rule the timeline draws with. A ticked-off block is out of the running:
  "now" pointing at work you have finished is a small lie the app does not need to tell.
- **Untimed work is never it.** Anytime has no hour to be in, and pretending it does would turn
  the inbox into a claim about what you are doing.
- **It borrows the timeline's "now" treatment** rather than inventing a second one: a solar fill
  with ink on it, measured at 5.36:1 light and 6.47:1 dark. The amber mark itself measures 4.22:1
  on `--surface-2`, so the word is a fill and the meta text is `--muted`, 4.56:1 and 5.66:1.
- **The snapshots now pin the clock.** The glance counts down, so it could never be a stable
  picture — and the timeline's now line was already drifting with the hour, passing only because a
  1.5px rule stays under the noise threshold. The shots run at a fixed 11:00, where the seeded day
  has a block in progress. The browser checks pin it as well: a block
  seeded relative to the real minute runs past midnight when the suite runs in the evening, which
  is what CI does, and a suite that passes all afternoon is not a suite.

Also fixed: the README said nothing could send a notification, which stopped being true when
notifications shipped.

Counts: 326 backend tests, 91 unit, 226 browser checks.

## 0.10.0 — 2026-09-21

Two ways out, and a glance for the phone.

**The whole database as one readable file.** `scripts/backup.py` answers "put it back": it copies
the file through SQLite, so a restore is exact and brings back everything, including what this
app has not thought about. It cannot answer "this is mine and I can read it" — a `.db` file needs
something that speaks SQLite, it carries whichever schema you happened to be running, and you
cannot read it in a text editor or diff it. So `GET /api/export` hands you one JSON file, **Your
data** in the settings offers it as a button, and `POST /api/import` puts it back.

- **Replace, not merge.** Merging sounds gentler and is the harder promise to keep: two databases
  with the same block id are one block or two depending on nothing the file records, so a merge
  has to guess, and the guess is silent. The panel says what it will do before it does it, and
  the request has to carry `"confirm": "replace everything"` — a phrase that is impossible to
  send by accident and readable when found in a log.
- **An import cannot unsubscribe you.** `push_subscriptions` is deliberately absent from the
  file: an endpoint is a capability, and anything holding one can notify that device, so it has
  no business in a file people mail to themselves. The table is left alone rather than emptied,
  which is also why restoring your data cannot silence the phone in your pocket.
- **It leaves a way back.** The database being replaced is copied first, through SQLite's own API
  rather than `cp` — the app is answering requests while this happens, and in WAL mode a plain
  copy can be missing the newest write while still looking like a perfectly good database. The
  copy's path is in the answer.
- **Every refusal is a sentence, and none of them is a 500.** A file that is not an export; one
  from a newer sundial, by format or by schema, because migrations only run forwards; one missing
  a table, which would otherwise quietly delete the part it left out; one with a column sundial
  does not know; and one that contradicts itself — two rows sharing an id, or an event naming a
  calendar the file does not carry. That last one arrived as an unhandled `IntegrityError` and
  reached the browser as a 500 with a stack trace: the worst of both, since nothing is learned
  and there is no way to tell whether it took.

**Today as a card.** `scripts/cadu_card.py` prints the day as a rich-card payload for Cadu: a
checklist of the blocks, with what is now and what is next in the summary. It reads the API
rather than the database, so it cannot disagree with the day view. It will not fake `completed`
from the clock — a block whose hour has passed is not a block that happened — and because ticking
an item is saved on the phone and never sent back, the card says so in its own summary rather
than letting you believe you have changed your plan. The payload was checked against the real
validator rather than the documentation, which is how it acquired the one key nothing local could
have known it needed: a checklist is an interactive card, and an interactive card is refused
without an `id`.

**A measured gap, left visible rather than tidied away.** The settings buttons label themselves
`--accent` on `--surface-2`, which measures **4.22:1** — just under the 4.5:1 that `styles.css`'s
own header claims for a label on its ground. The new buttons reuse that pair instead of inventing
a third look for the same panel, and the number is written down here rather than left for someone
to measure again. The one filled control, "Replace everything", uses `--on-solar` on `--solar` at
**5.36:1**.

340 backend tests, 78 frontend unit tests, 219 browser checks — including a round trip that
exports a file out of a real browser, reads it back, deletes a block, imports the file and finds
the block again.

## 0.9.1 — 2026-09-21

Notifications were being refused by Apple, and the app was saying the wrong thing about why. Both
halves of that needed fixing, and only a real phone could reveal either.

- **The contact claim is validated, and a reserved name is not a domain.** Every push service is
  handed a `sub` claim naming who to contact about the sender. It shipped as
  `mailto:sundial@localhost`, and Apple answers that with `403 BadJwtToken` — not because the
  identity was wrong, or the subscription, or the request, all of which were valid, but because
  `localhost` is not somewhere it believes an operator can be reached. The default is now a
  merely plausible domain, overridable with `SUNDIAL_VAPID_SUBJECT`, and a test guards the value
  itself, because nothing local exposes the problem: the failure lives entirely in the push
  service's answer.
- **"No device is subscribed" was a lie the panel told.** `Send one now` read only the count of
  what was sent, so a refused delivery and an empty subscriber list produced the same sentence. A
  valid Apple subscription was reported as nobody being subscribed while Apple was refusing every
  attempt — which is the one sentence that could have pointed at the cause, thrown away. There
  are three outcomes now, said separately, and the refusal carries the push service's own reason.

Both were invisible from this side: 304 backend tests passed, the subscription was stored
correctly, every request was well-formed, and Apple returned 200 to nothing. The first send that
worked returned `sent: 1, failed: []` only after the claim changed, and the four new frontend
tests pin the distinction between a refusal and an absence — including that a refusal never again
says nobody is subscribed.

## 0.9.0 — 2026-09-21

The app had two things you turn on and off, and both of them were buttons that described what
they would do instead of what is true: “Switch to dark”, “Turn on for this device”. A control
that names its own next action is a small tax every time you read it — you have to work out the
present from the future. They are switches, so they now say the present by where the thing sits.

- **One switch, two settings.** The theme in the profile and “tell me when a block starts” are
  the same question asked twice, so they are the same component rather than two controls that
  merely resemble each other. The header keeps its quick toggle; it and the profile switch are
  one setting, and the check that says so is that turning one moves the other.
- **Borrowed from uiverse.io, and rebuilt rather than pasted.** The mechanics — a real checkbox,
  a slider that translates on `:checked` — are the standard ones. Nothing else was kept: the
  survey of the library's 3,802 elements found 601 that are plain CSS with no shadow, gradient,
  blur or infinite animation, which is the bar this app's own stylesheet already sets. All 103
  background patterns are gradients, 696 of 718 loaders animate forever, and most switches hide
  their input with `display: none`.
- **The knob is ink in both states, and that is a measurement rather than a taste.** A parchment
  knob on the amber fill is 2.6:1 and disappears; ink on it is 5.36:1 light and 6.47:1 dark, so
  the track carries the state and the knob stays legible.
- **The track's edge is `--muted`, not `--line`.** A hairline composites to 1.45:1 against the
  panel, which leaves a control with no visible boundary; `--muted` is 5.16:1 light and 6.26:1
  dark, clear of the 3:1 a control edge is asked for. The amber fill is itself 2.80:1 on light
  parchment and that is allowed, because the fill is not the signal — the knob's position is, at
  13.26:1 off and 5.36:1 on.
- **The input stays a real checkbox, and stays reachable.** It is hidden by opacity over a
  full-size box, never by `display: none`, which would take it out of the tab order and put the
  control beyond a keyboard.
- **The focus ring is drawn by the track.** An invisible input has nowhere to draw one, so the
  track draws it: the same 2px solar mark at the same 2px offset as every other control. Nothing
  here opts out of the ring, and the check that asserts it presses Tab first, because a
  programmatic focus does not match `:focus-visible` and would pass while asserting nothing.

Motion is `--t-quick`, the faster of the two speeds this app has, and it is switched off along
with everything else by the reduced-motion rule. Four checks hold the switch to being a switch
rather than a styled div: it carries `role="switch"`, a keyboard can reach it, it draws the ring,
and its position agrees with the theme actually in force — which is the same principle the
notifications panel follows, that the state shown is the browser's answer and not the last thing
clicked.

## 0.8.0 — 2026-09-21

A notification is the only thing this app says without being asked, so most of the work here was
deciding how little it should say. It announces the hour a block begins and then stops: no
summary, no count of what you have not started, nothing about a day you already know about. The
app already had a service worker that could receive a push. What it did not have was anything
that could send one.

- **One notification, at the hour.** The block's title and how long it runs, and nothing else —
  because everything else this could have said would have been urgency.
- **Off until asked, per device**, from the You tab. The panel shows the browser's answer rather
  than the last thing clicked: a subscription can be dropped by the push service, or cleared
  along with the site's data, and a panel that only remembered its own click would carry on
  claiming to be on.
- **Late is not worth saying.** A block is announced only if it started inside the last ten
  minutes. Without that rule, opening the app on a Sunday evening fires a notification for every
  hour since Friday, and an app that says “you should have started this on Friday” is not a
  planner, it is an audit.
- **Once per block per day**, kept as a row rather than a flag, so midnight has nothing to reset
  and a restart has nothing to re-announce.
- **A subscription the push service has forgotten is deleted, not retried.** 404 and 410 are the
  service saying it is over. Any other failure delays that notification instead of spending it.
- **The identity is made once**, on first use, and kept as a 0600 file beside the calendar
  credentials. Deleting it is a supported repair rather than damage.
- **A “Send one now” button**, because the only other way to prove the path works is to wait for
  an hour to pass.
- **New dependency: pywebpush.** VAPID signing and the payload encryption are the two places in
  this feature where being clever means writing crypto, and there is no upside to that.

The limit is stated on the panel rather than left to be discovered on a morning nothing arrives:
sundial sends these itself, so it can only send while it is running. A notification about nine
o'clock needs the app up at nine o'clock. That is the honest shape of a program that owns one
file in your home directory.

Verified the way the rest of the app is. Fifty backend tests cover the sending side and its
restraint — announced once and not twice, silence for a block that started an hour ago, a refused
network call that delays rather than consumes. Fifteen frontend tests cover the three parties
that can each refuse a subscription, and five browser checks hold the panel to naming its state
in words and to offering no control that could only fail. Both `smoke_release.py` and
`test_app.py` replayed the third migration by deleting its version row, which stops working the
moment a fourth migration exists; they now delete from three up, which is what they always meant.

## 0.7.0 — 2026-09-21

Connecting a calendar moved out of your day. It used to sit in the rail under the inbox, so the
app's own plumbing — credentials, sync, theme — read as part of the plan; on a phone the rail
stacked above the day and spent a quarter of the screen saying so.

- **Three destinations at the foot of the app.** Today, Day, You: the plan, the clock, and the
  app's own settings. The header's Plan/Timeline switch is gone, because the bar is the switch.
  Plain text rather than glyphs, and the one you are standing in is marked with the same amber as
  the now line — 15.02:1 against the bar where the quiet two are 5.16:1.
- **Connecting lives in You.** The calendar panel, its Connect form, the theme and which version
  this copy is: all questions about the app rather than about the day, so all behind a tab you
  have to mean to open. The day's events still belong to the day, drawn on the clock in Day.
- **The rail is a desktop tool, not a phone feature.** Above 780px it returns beside the clock,
  because giving an unscheduled task an hour is a drag, and a drag needs somewhere to land. Below
  it those same tasks are in Today's Anytime section, one tap from the editor, and the day gets
  the whole screen instead of a quarter of it.
- **A first visit opens on the plan**, and after that it opens where you left off.
- **The destinations are tested the way a person uses them**: every one hit-tested at its own
  centre, each tapped and its destination asserted, and the old controls asserted *gone* — a
  stylesheet can restyle a switch into invisibility, so absence is measured in the DOM.

The keyboard walk in the suite now starts from the top of the page and judges the focus ring once
per element. Where sequential focus begins is the last thing that was clicked, and the last thing
clicked is a destination in the tab bar, which is last in the DOM; and a date field is several
stops whose focus sits inside Chromium's own shadow tree, where no author style reaches.

## 0.6.0 — 2026-09-21

The calendar comes into the day. An appointment reads in the same ink as your own plan, and it is
still not yours to move — which turned out to be two jobs, not one.

- **Appointments on the timeline.** The day's events from every switched-on calendar are drawn at
  the hour their own clock says, from the same `/api/events` answer the rail already shows. No new
  endpoint, no second source of truth about what is on your day.
- **Same ink, different line.** The title is set in the body ink at the weight a block title uses
  (13.9:1, weight 500); ownership is said by a dotted hairline where a block has a solid one, a
  `default` cursor where a block says grab, and the calendar's name in the row. The first three
  takes made an appointment quieter to show it was not yours, and quiet is a thin line away from
  invisible — the sketch where a faded row is the answer is the sketch that gets a calendar nobody
  reads.
- **A clash is drawn, not labelled.** When an appointment shares an hour with a block, the block
  gives up the right half and both stay readable. The narrowed row is the whole signal; nothing
  turns grey to say it. Two appointments contesting that half are split between lanes rather than
  stacked on top of each other.
- **Touching is not clashing.** Back-to-back blocks merge into one busy stretch, but an
  appointment starting exactly when a block ends is not an over-booked hour. Two questions, two
  rules, each with its own test.
- **Only the day you are looking at.** An answer for another day is not drawn on this one: the
  rail's events belong to whichever day it last fetched, and a stale answer arriving late would
  otherwise place yesterday's appointments onto today.
- **All-day events stay off the clock**, where they have no hour to sit at — the rail still lists
  them.
- **The layout rule is a pure function with twelve tests**, including the one that caught the
  label sitting behind the block in the sketch: the browser check hit-tests every appointment
  title at its own centre, in both themes and at phone width, because `getComputedStyle` will
  report a perfect contrast ratio for a title that is underneath something.

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
