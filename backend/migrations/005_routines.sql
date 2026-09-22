-- 005: repeating planning blocks — the routine, and the days you changed on it.
--
-- Two tables, and the reason there are two is the whole design.
--
-- A routine is a rule: "Mon · Wed · Fri, 06:30–07:30". Its occurrences are not rows. A year of
-- a daily routine is 365 rows nobody asked for, and every one of them is a copy that can drift
-- from the rule — edit the ring time and you inherit three hundred rows saying the old one. So
-- nothing generates. An occurrence exists when the rule says it does, calculated from the
-- calendar the day it is asked for, and the day you ask about is the day you get.
--
-- That leaves exactly one thing rows are needed for: the days you decided something different.
-- You went on Saturday, the gym was shut on Monday, you did the ring at 06:00 this morning.
-- Each of those is one row in `routine_overrides`, keyed by routine and day, and it is the only
-- place an occurrence can be altered. Editing one occurrence never touches the rule, and
-- editing the rule never touches a day you already had an opinion about.
--
-- `state` and `done` both exist, and they are not free to disagree: the CHECK below makes
-- "completed" and "done = 1" the same statement in two columns, so no reader has to guess which
-- one won. `skipped` is the third state, and it is the only one that hides the occurrence.
--
-- The override columns other than `state`/`done` are nullable on purpose: NULL means "as the
-- routine says", so a row that only moves the time does not freeze the title against a later
-- rename. An override disappears entirely once it says nothing.
--
-- Forward-only, additive: nothing that already exists is touched.
--
-- `ON DELETE CASCADE` is real here because `store.db()` turns foreign keys on; deleting a
-- routine takes its overrides with it rather than leaving rows pointing at a rule that is gone.

CREATE TABLE IF NOT EXISTS routines (
    id             TEXT PRIMARY KEY,
    title          TEXT    NOT NULL,
    -- Minutes past midnight, and required: a routine is a planning block, and a planning block
    -- with no time of day would be an inbox item that repeats — a different feature, and not
    -- one the day view could draw.
    start_min      INTEGER NOT NULL,
    duration_min   INTEGER NOT NULL,
    color          TEXT    NOT NULL,
    icon           TEXT    NOT NULL DEFAULT '',
    notes          TEXT    NOT NULL DEFAULT '',
    recurrence_kind TEXT   NOT NULL,
    -- Canonical ISO weekday numbers, comma separated: '1,3,5' is Mon, Wed, Fri. Stored as text
    -- because that is what the rule is — a set of days — and it reads in a SQLite browser.
    weekdays       TEXT    NOT NULL DEFAULT '',
    interval_weeks INTEGER NOT NULL DEFAULT 1,
    start_date     TEXT    NOT NULL,
    end_date       TEXT,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1,
    CHECK (recurrence_kind IN
           ('daily', 'weekdays', 'weekends', 'selected_weekdays', 'weekly_interval')),
    CHECK (start_min >= 0 AND start_min < 1440),
    CHECK (duration_min >= 5 AND duration_min <= 1440),
    CHECK (interval_weeks >= 1 AND interval_weeks <= 52),
    CHECK (enabled IN (0, 1)),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

-- The day view asks "which rules apply on this date", not "which of these will ever apply", so
-- the range it filters on is (start_date, end_date) and the indexed columns are those two.
CREATE INDEX IF NOT EXISTS routines_dates ON routines(start_date, end_date);

CREATE TABLE IF NOT EXISTS routine_overrides (
    id            TEXT PRIMARY KEY,
    routine_id    TEXT    NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    day           TEXT    NOT NULL,
    state         TEXT    NOT NULL,
    start_min     INTEGER,
    duration_min  INTEGER,
    title         TEXT,
    color         TEXT,
    icon          TEXT,
    notes         TEXT,
    done          INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT    NOT NULL,
    UNIQUE (routine_id, day),
    CHECK (state IN ('modified', 'skipped', 'completed')),
    CHECK (done IN (0, 1)),
    -- One statement in two columns: completed is done, and only completed is done.
    CHECK (done = (state = 'completed')),
    CHECK (start_min IS NULL OR (start_min >= 0 AND start_min < 1440)),
    CHECK (duration_min IS NULL OR (duration_min >= 5 AND duration_min <= 1440))
);

CREATE INDEX IF NOT EXISTS routine_overrides_day ON routine_overrides(day);
