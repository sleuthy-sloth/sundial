-- 004: the sending side of "a notification when a block starts".
--
-- Two tables, because two different questions get asked and they have different lifetimes.
--
-- `push_subscriptions` is who to tell: one row per browser that opted in. The endpoint is
-- the primary key rather than a surrogate id, because a push service hands out one endpoint
-- per subscription and re-subscribing the same browser (a reinstalled PWA, a re-granted
-- permission) can return either the same endpoint or a new one. Keying on it makes the same
-- one an update and a new one an insert, without the app having to guess which happened.
--
-- `push_sent` is what has already been said. A tick runs every minute, so without this a
-- block starting at 09:00 would be announced sixty times.
--
-- No foreign key from `push_sent` to `blocks`, deliberately. The row records that something
-- was said; deleting the block afterwards does not unsay it. A cascade would also turn a
-- delete into a second write that can fail, and an orphan row here is a few bytes that is
-- only ever read as part of an anti-join. Both tables are additive, so this migration
-- changes nothing that already exists.

CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint   TEXT PRIMARY KEY,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- One row per block per day: the same block fires again tomorrow, so the day is part of the
-- key rather than part of the block.
CREATE TABLE IF NOT EXISTS push_sent (
    block_id TEXT NOT NULL,
    day      TEXT NOT NULL,
    sent_at  TEXT NOT NULL,
    PRIMARY KEY (block_id, day)
);

CREATE INDEX IF NOT EXISTS push_sent_day ON push_sent(day);
