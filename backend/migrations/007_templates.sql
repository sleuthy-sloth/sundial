-- 007: templates — a day structure written once and used again.
--
-- A template is not a routine, and the difference is the whole reason both exist. A routine
-- says "this happens every Wednesday" and lands on the calendar by itself. A template says
-- "this is what a workday looks like", sits still until you ask for it, and is never applied
-- to a day you did not name. Nothing here recurs, and nothing here writes to a day by itself.
--
-- Two tables, and the split is the same one `routines` uses: the thing, and the rows that make
-- it up. `templates` holds the name. `template_blocks` holds the items in order, and it is
-- named for what an applied item becomes — each row is copied into a real block on the day the
-- template is applied, which is why the columns are the block columns and not a shape of their
-- own. An item is not a block: it has no `day` (a template is day-agnostic; the day is given at
-- apply time), and it has no `done` (a template is a plan, not a record — an applied block
-- always starts unfinished, because it has not happened yet).
--
-- `start_min` is nullable here on purpose. NULL is the plan's "Anytime": an item with no hour
-- lands in the inbox when it is applied. That is the one column where a template item is
-- allowed to say less than a block.
--
-- `sort_order` rather than relying on rowid: the list is what you wrote, in the order you wrote
-- it, and an edit that moves a line should not depend on insertion order surviving a rewrite.
-- The whole list is replaced on every save (`services/templates.py` says why), so this column is
-- the only thing carrying the order across one.
--
-- Overlaps are allowed, here and when applied. Sundial has never had an overlap rule and a
-- template is not the place to invent one: two items at nine o'clock produce two blocks at nine
-- o'clock, which is a thing the day view already draws.
--
-- Forward-only, additive: nothing that already exists is touched.
--
-- `ON DELETE CASCADE` is real here because `store.db()` turns foreign keys on: deleting a
-- template takes its items with it rather than leaving rows pointing at a template that is gone.

CREATE TABLE IF NOT EXISTS templates (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_blocks (
    id           TEXT PRIMARY KEY,
    template_id  TEXT    NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    -- Minutes past midnight, or NULL for "Anytime". Absolute, like a block's, so applying is a
    -- copy rather than an arithmetic problem.
    start_min    INTEGER,
    duration_min INTEGER NOT NULL,
    color        TEXT    NOT NULL,
    icon         TEXT    NOT NULL DEFAULT '',
    notes        TEXT    NOT NULL DEFAULT '',
    sort_order   INTEGER NOT NULL DEFAULT 0,
    CHECK (start_min IS NULL OR (start_min >= 0 AND start_min < 1440)),
    CHECK (duration_min >= 5 AND duration_min <= 1440)
);

-- Read one template's items, in order, which is the only way they are ever read.
CREATE INDEX IF NOT EXISTS template_blocks_order ON template_blocks(template_id, sort_order);
