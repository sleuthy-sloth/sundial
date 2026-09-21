# Calendar sync: what it is, and what it deliberately is not

Read-only calendar context for sundial. Your calendar comes in; nothing goes back out.
This is the specification the first slice was built against, kept because the reasoning is
the part that goes stale, not the code.

## Why read-only

The plan lives in `blocks`. The outside world lives in `events`. They are separate tables
because they are separate things: an all-day event is a date rather than an instant, a
series is a rule rather than an occurrence, and something someone else added to a shared
calendar is not yours to mark done.

`sundial` is not a calendar client. You do not manage your calendar here — you see it while
you decide how to spend a day. So the first slice imports and never writes, which means a
bug in it can annoy you by showing the wrong thing but cannot damage your actual calendar.
`block_to_ics` exists and is tested for the day pushing is worth doing; it is not wired up.

## Why iCloud first

Because of credentials, not preference. iCloud speaks CalDAV behind an app-specific
password: generate one at appleid.apple.com, paste two lines into a file, done. Google
switched password-based CalDAV off in 2024, so it needs an OAuth client, a consent flow
and refresh handling — a later slice, and the transport boundary below is what keeps it
from being a rewrite.

## The pieces

    backend/caldav.py            the transport: CalDAV in, rows out. No database.
    backend/calendar_sync.py     the pure half, already written: ICS ⇄ rows, conflict rules
    backend/calendar_service.py  the engine: config, transport, rules, database, sync_log
    scripts/check_calendar.py    a live check you run once by hand

The split matters. `calendar_sync.py` has no network and no database, so the fiddly parts
(instants across DST, all-day, recurrence) are testable against inline ICS. `caldav.py` has
a network but no database, so it is testable against scripted HTTP responses. Only the
engine touches both, and it is small.

## The protocol, in the order it is spoken

1. `PROPFIND` the endpoint (`Depth: 0`) for `current-user-principal` → who I am.
2. `PROPFIND` the principal for `calendar-home-set` → where my calendars are.
3. `PROPFIND` the home (`Depth: 1`) for `resourcetype`, `displayname`, `supported-calendar-
   component-set`, the colour and a ctag → which collections are calendars, and have any of
   them changed since last time.
4. `REPORT` `calendar-query` per calendar with a `time-range`, asking for `getetag` and
   `calendar-data` → the objects themselves, each with its ETag.

Apple's colour arrives as `#RRGGBBAA` in `http://apple.com/ns/ical/`. It is mapped to the
nearest of sundial's eight palette names rather than stored raw, because those eight are a
validated app colour, not a style choice.

## The window

   seven days back, sixty forward, recomputed at every sync.

Back because a plan is informed by what just happened; forward because a week strip wants to
know how loaded next Tuesday is. Everything outside it is left alone — not deleted, not
updated. The window is a rolling one, so an event that drifts out of it the day after
tomorrow is still yours and still stored.

## What is safe when something goes wrong

The one destructive thing a sync can do is decide an event is gone. Two rules bound it:

- **Only a complete fetch may reconcile.** A `REPORT` that errored, timed out, or came back
  as anything other than a well-formed 207 leaves every stored row for that calendar exactly
  as it was. A partial answer must never look like "these events stopped existing".
- **Only in-window rows are candidates.** Something we hold from outside the window was
  never asked about, so its absence from the answer means nothing.

Every change a sync makes is written to `sync_log`, including—especially—the removals. The
schema comment says why: it is what makes a quiet conflict policy auditable after the fact.
If a sync ever deletes your events by mistake, the log is how you find out what it thought
it saw.

## Conflict rules

Inherited from `calendar_sync.py`, unchanged here: a higher `SEQUENCE` wins, then the later
timestamp, and a tie keeps the local edit because he is the one looking at the screen. A
remote change may only overwrite the fields a calendar owns; colour, done and anything typed
into sundial are never touched. A remote value that arrives empty does not blank a value we
already hold.

## Configuration

`icloud.env` at the repo root — gitignored, read at every sync, never stored in the
database, never logged, never returned by the API:

    ICLOUD_USERNAME=you@example.com
    ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
    ICLOUD_CALDAV_URL=https://caldav.icloud.com/      # optional; any CalDAV server

Read per sync rather than at boot, so pasting a password does not need a service restart. A
missing file, a missing key, or a file with the wrong shape all produce the same honest
state: not configured, and here is what to create.

## Scheduling

No daemon and no timer in this slice. The calendar view asks for a sync when it opens, and
the server skips that request if it synced within the last fifteen minutes, so switching
views does not hammer iCloud. A `Sync now` control forces one. If you want it to happen
while nobody is looking, point a systemd timer at `scripts/check_calendar.py --sync`.

## Deliberately not in this slice

- Pushing blocks out (the conversion exists, the transport call does not).
- Google (OAuth).
- Incremental sync via RFC 6578 `sync-collection`. A ctag comparison decides whether to
  refetch at all; when it does, it refetches the window. Windows are small enough that this
  is honest, and the failure mode of a hand-rolled sync-token is a silently missing event.
- Events on the timeline. The next slice: they need a visual language that says "this is not
  yours to move" without shouting, and that is design work, not plumbing.
