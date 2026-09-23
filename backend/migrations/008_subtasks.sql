-- 008: a checklist under a task.
--
-- Three things can hold a checklist, and they are three different things, which is why this is
-- four statements rather than one.
--
-- A BLOCK gets a `parent_id`. A line under a task is a `blocks` row whose parent is another
-- `blocks` row, so ticking one, renaming one and deleting one are the writes the API already
-- has, and nothing about a day full of checklists needed a second table to describe it.
--
-- That line has NO DAY OF ITS OWN: `day` and `start_min` stay NULL. It is inside its task, so it
-- is read with its task — `/api/day` nests it under the block it belongs to — and never by day.
-- The day's own query (`WHERE day = ?`) cannot see it, which is what keeps a checklist line out
-- of the day's planned minutes, out of the week's counts and out of "Left from yesterday"
-- without any of them having to remember a rule. A parent with three five-minute lines is still
-- one thirty-minute block, and an hour is still counted once.
--
-- The two queries that do read `day IS NULL` say `parent_id IS NULL` beside it, because an inbox
-- is a list of tasks you can give a time to and a rollover moves tasks: `routers/blocks.py` for
-- the inbox, `services/rollover.py` for the predicate. A line is not independently either.
--
-- `sort_order` is the order the lines were written in. Not rowid: an export selects rows and an
-- import re-inserts them, and the order a person wrote down belongs in the file rather than in a
-- number SQLite happens to hand out. It is 0 for everything that is not a line.
--
-- `ON DELETE CASCADE` is real here because `store.db()` turns foreign keys on, and SQLite does
-- apply a self-referencing one: deleting a task takes its lines with it. A line whose task is
-- gone is an orphan with no context — the same reason a line never rolls over alone.
--
-- A TEMPLATE ITEM gets a `parent_id` of the same shape in `template_blocks`: a template is a day
-- you wrote once, and "Pack for the trip" is a line of that day with three lines under it.
-- Applying copies the whole thing, so a template stores no completion state at all — a template
-- is a plan and is never done.
--
-- A ROUTINE gets a table of its own, because an occurrence is CALCULATED: there is no `blocks`
-- row to hang a parent on until somebody changes a day, and fabricating one for every occurrence
-- would break the property that makes routines cheap — nothing generates. So a routine's lines
-- are definitions that live with the rule (`routine_subtasks`), and the one fact per day — the
-- third line of this morning was ticked — is a list of line ids on the override row that already
-- exists for that day. That is what makes a ticked box stay ticked across a reload instead of
-- resetting with the calendar.
--
-- Forward-only, additive: nothing that already exists is touched.

ALTER TABLE blocks ADD COLUMN parent_id TEXT REFERENCES blocks(id) ON DELETE CASCADE;
ALTER TABLE blocks ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

-- One task's lines, in the order they were written — the only way they are ever read.
CREATE INDEX IF NOT EXISTS blocks_parent ON blocks(parent_id, sort_order);

ALTER TABLE template_blocks ADD COLUMN parent_id TEXT
    REFERENCES template_blocks(id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS routine_subtasks (
    id         TEXT PRIMARY KEY,
    routine_id TEXT    NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- One rule's lines, in order.
CREATE INDEX IF NOT EXISTS routine_subtasks_order ON routine_subtasks(routine_id, sort_order);

-- Which lines of one day of a routine were ticked: their ids, comma separated, the same way
-- `routines.weekdays` stores a set of days. Text on the override rather than a table of its own
-- because the fact belongs to the day — one row per (routine, day) is what "what I decided about
-- this day" has been since 005 — and a table would be a second place to look for one answer. An
-- id that no longer names a line is ignored when the day is read, so deleting a line costs its
-- ticks and nothing else. `done` on the override stays what it has always been: the state of the
-- block itself, which a line neither sets nor follows.
ALTER TABLE routine_overrides ADD COLUMN subtasks_done TEXT NOT NULL DEFAULT '';
