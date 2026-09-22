-- 006: the app's own settings, in the database rather than in one browser.
--
-- One setting so far: what to do with unfinished scheduled work when the next day is looked at.
-- It is here rather than in localStorage because of what an export promises. A setting kept in a
-- browser does not travel in a file, does not survive a fresh install, and does not follow you to
-- the other device — it is silently reset, and a setting that resets itself is worse than one
-- that was never offered. The database is the thing the export carries, so a setting that should
-- follow your data has to be a row in it.
--
-- A row per setting rather than a column per setting, so the second one is an insert and not
-- another migration. The value is stored as the text the API speaks, so a row reads in a SQLite
-- browser and a refusal can name the value it did not recognise. What a value may be is enforced
-- by the API and not by a CHECK: a CHECK in a key/value table has to name the key it belongs to,
-- which is exactly the coupling this shape exists to avoid.
--
-- Forward-only, additive: nothing that already exists is touched.

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
