# Roadmap

Sundial is built one phase at a time. A phase is one pull request against `main`. It ends with the
suites green, the README and CHANGELOG updated, and the next phase starting from what the last one
merged.

The order is deliberate and mostly enforced by the work itself. Nearly every phase edits the README
and the CHANGELOG, most add a migration, and several build on the migration before them — so these
run one after another rather than side by side. Each entry below carries the decisions that are
already settled, so that starting a phase does not mean deciding it again.

## Where it stands

Landed, in order: the backend split into routers; recurring routines and their exceptions; unfinished
work offered the next day; reusable day templates; a week that reads as capacity; and checklists
under a task. Migrations `001`–`008`. One process over one SQLite file, installable as a PWA, and the
day readable at a glance on a phone.

Everything below is not built yet. The README's [Status](README.md#status) section lists what the app
deliberately does not do; this file lists what it is going to.

## The phases

### A day with no time yet

Today a block cannot have a day without a start time — the schema says so — which is why typing
`Laundry tomorrow` throws the word *tomorrow* away and files the item in Anytime. Tomorrow is one of
the most natural things a person says to a day planner, so this phase makes it storable.

Settled: `day` may be set with `start_min` NULL. The two "no time" states stay distinct — no day at
all is still the inbox, and *on this day, no time yet* is its own state, not "Anytime", which already
means the inbox. An unscheduled block fills no span: it adds nothing to the day's planned minutes and
takes nothing out of what is left. It sorts after every timed block. It rolls forward like anything
else unfinished. Putting it into a slot sets its start time rather than making a second copy of it.

The week view was written when every block on a day had a start, so this phase also reconciles it.

### Next open slot, duplicate and move

Let a task be dropped into the first gap that fits it, duplicated, or moved to another day.

Settled: moving a task carries its checklist, and duplicating one copies it — a copy with an empty
shell where the steps were is worse than no copy. Moving an unscheduled task into a slot sets its
start time; it does not leave a duplicate behind in Anytime.

### Quick entry: one line, no guessing

Type `Dentist fri @14 30m` and get a task with a day, a time and a length. Deterministic, offline,
no model anywhere near it.

The whole grammar is a table of examples, and the table is the specification — including what
*refuses*. Settled: `@7` is 07:00, not 19:00, unless the hour is written `pm`. Two clocks or two
lengths refuse rather than pick one, and the refused words stay in the title where the person can see
them. A length with no time leaves the task unscheduled. An empty title falls back to the line as
typed. Nothing is ever guessed, and no dependency is added for date phrases — a small fixed table of
day words over primitives the app already has does the job.

The parser returns the character ranges it consumed, so the field can show what it understood as it
is typed. That is the part that makes a parser trustworthy rather than mysterious.

### Search and a command palette

Find a block by name across the whole history, and run the app's own actions from the keyboard.

Settled: a plain `LIKE` over titles and notes rather than FTS5 — an FTS virtual table is not a plain
table, and the export dumps plain tables, so search would have cost a migration and a rebuild on
import for no gain on a single-user database. Ranking is a fixed order (title substring, then title
words, then notes, then most recent), not a relevance score. The primary affordance is a visible
button in the header with the keyboard chord as a convenience, because `Cmd+K` belongs to the browser
in an ordinary tab and this should not pretend otherwise. With a connection, search runs on the
server because history is not on the client; without one, it filters the day the app has. Calendar
events stay out of the results — search is for what you wrote.

### Google Calendar, read-only

The code is written and switched off. This phase turns it on and changes nothing else: imports stay
one-way, and nothing the app does writes to your calendar.

### A CalDAV address that is not iCloud

Fastmail, Nextcloud, Radicale, and anything else that speaks the same dialect.

Settled: a stored calendar reference is namespaced per provider, because two servers can serve
different calendars under the same path and silently overwriting one with the other is the failure
mode worth designing against. The calendar data is the easy half; discovery — `.well-known`, the
current user principal, the calendar home — is where the work is.

### Docker

A container that runs the same process over a mounted SQLite file. The data directory is documented,
the file it writes is the same file the bare-metal install writes, and no credentials are baked into
a layer.

### Remote access

The documents, not the feature. **The app has no authentication of any kind** — that is the first
thing this has to say, in those words, before it suggests how anyone might expose it. A day planner
on a private network is fine; a day planner on the open internet with no lock on the door is a
different thing entirely, and the writing has to make the difference obvious.

### Time tracking

Planned time already exists, as the length on a block. Actual time does not. This phase adds it:
started and stopped by hand, stored as sessions rather than as one number per task, one timer running
at a time, and a total that is never compared to the estimate and never turns red. It survives a
reload, and a timer started offline is not lost or counted twice when the connection comes back.

No ambient tracking, no idle detection, no summary of where the day went. Numbers the person asked
for, and nothing that interprets them.

### Releases and distribution

Seventeen tags, no GitHub Releases, and the version written in three places that disagree with each
other. This fixes that and publishes what has accumulated.

Settled: tag numbers follow the order things *land*, not the order they were planned in. Published
numbers are a one-way door, and a number that goes backwards cannot be repaired.

### Linting and static checks

Ruff and ESLint, versions pinned so a linter update is a commit and not a surprise. The date/time
rules stay off: naive datetimes are a decision in this codebase, not an oversight, and a lint rule
that fights a decision teaches people to ignore lint.

### Repository polish

Topics, Discussions, and the small incongruities — a contributing guide that describes a branch
arrangement the project does not use, and similar.

## An open question: a native iOS app

Not a phase, because it is not decided and it is not clearly the right thing to do.

The app is a client of a server that runs on your own hardware. That shape is what makes this
question interesting, because it splits into three very different amounts of work:

- **A native client for the existing server.** The Swift app talks to the same HTTP/JSON API the
  browser does. The rules that matter — how a day is counted, how a routine expands, when something
  rolls over — already live on the server, so the client is mostly presentation. The browser client
  is around 6,400 lines that would be rewritten rather than converted. Weeks of work, not months,
  and nothing on the server changes.
- **A native app with its own backend.** Reimplement the server in Swift with SQLite: migrations,
  export and import, CalDAV, Google, notifications. That is a second implementation of the same
  schema, permanently, and every phase above would then need building twice. The one to avoid.
- **A native shell around the existing client.** WKWebView with native chrome, real notifications
  instead of web push, and widgets. Days of work. The web client and its checks stay exactly as they
  are, and individual screens can move to SwiftUI later if they earn it.

What native genuinely buys, and what it costs, is worth saying plainly. It buys dependable background
notifications (web push on iOS needs the app on the home screen and does not wake reliably), widgets
and Live Activities, Shortcuts, and the absence of Safari's quirks — including the keyboard chords a
browser reserves for itself. It costs the thing that makes this app easy to recommend: a web client
works on anything, and a native one works on an iPhone. It also means an App Store account and,
sooner or later, real authentication, which does not exist today.

**The recommendation is the third option, and not yet.** The stack is deliberately simple, and the
reason to want it native — the notifications — is available without touching the client that already
works.

## What the work has to respect

These constrain every phase above, and are the reason some of them are shaped the way they are.

- **No AI in the app.** No generated plans, no suggestions, no summaries, no model calls, no network
  dependency in the core. Quick entry is deterministic parsing and always will be.
- **Nothing that keeps score.** No streaks, points, badges, red overdue states, or language that
  makes an unfinished day feel like a failure. A day is a plan, not a performance.
- **Local-first and single-user.** It runs on your hardware, over one file, with no account and no
  cloud in the path.
- **The calendar is read-only.** Imports come in; nothing goes out.
- **Migrations are forward-only, and a shipped migration is never edited.**
- **Everything stored is exportable.** New stored data belongs in the JSON export, a file written by
  an older version still imports, and credentials, tokens and push endpoints never appear in one.
- **Keyboard reachable, visible focus, 44px targets, and `prefers-reduced-motion` honoured.**
- **The stack stays.** FastAPI, React, Vite and SQLite are not replaced, and working subsystems are
  not rewritten for style.
