-- 002: calendars, imported events, and a record of every sync decision.

CREATE TABLE IF NOT EXISTS calendars (
  ref        TEXT PRIMARY KEY,          -- CalDAV href, or the Google calendar id
  provider   TEXT NOT NULL,             -- 'icloud' | 'google'
  name       TEXT NOT NULL,
  colour     TEXT NOT NULL DEFAULT 'slate',
  enabled    INTEGER NOT NULL DEFAULT 1,
  writable   INTEGER NOT NULL DEFAULT 0,
  sync_token TEXT,                      -- incremental cursor, provider-specific
  ctag       TEXT,                      -- collection tag, for the fallback path
  last_sync  TEXT,
  last_error TEXT
);

-- Imported from a calendar. Read-only in sundial's own terms: the plan lives in
-- blocks, the outside world lives here. recurrence_id is '' rather than NULL on
-- purpose: SQLite treats NULLs as distinct in a UNIQUE constraint, so NULL would
-- let the same master be inserted twice.
CREATE TABLE IF NOT EXISTS events (
  id            TEXT PRIMARY KEY,
  calendar_ref  TEXT NOT NULL REFERENCES calendars(ref) ON DELETE CASCADE,
  provider      TEXT NOT NULL,
  uid           TEXT NOT NULL,
  recurrence_id TEXT NOT NULL DEFAULT '',
  title         TEXT NOT NULL,
  location      TEXT NOT NULL DEFAULT '',
  notes         TEXT NOT NULL DEFAULT '',
  start_utc     TEXT NOT NULL,          -- an instant, so DST cannot drift it
  end_utc       TEXT NOT NULL,
  all_day       INTEGER NOT NULL DEFAULT 0,
  rrule         TEXT,                   -- series masters only; expanded when read
  raw_ics       TEXT,                   -- what the server actually sent, for masters
  status        TEXT NOT NULL DEFAULT 'CONFIRMED',
  etag          TEXT,
  sequence      INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL,
  UNIQUE (calendar_ref, uid, recurrence_id)
);

CREATE INDEX IF NOT EXISTS events_window ON events(start_utc);

-- Every change a sync decided to make, especially the non-obvious ones. This is
-- what makes a quiet conflict policy auditable after the fact.
CREATE TABLE IF NOT EXISTS sync_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  at           TEXT NOT NULL,
  provider     TEXT NOT NULL,
  calendar_ref TEXT,
  uid          TEXT,
  action       TEXT NOT NULL,
  detail       TEXT NOT NULL DEFAULT ''
);

ALTER TABLE blocks ADD COLUMN external_uid TEXT;
