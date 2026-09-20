-- 003: a day is 'YYYY-MM-DD', and nothing else.
--
-- The date parser also accepts the compact form ('20260921'), and the value was stored
-- exactly as it arrived. The row existed but no query could find it: compared as text,
-- '20260921' sorts after every canonical date in its own week, so it fell outside the
-- range the day and week endpoints ask for. The API refuses that shape now; this
-- repairs what was already written, so an existing plan comes back rather than needing
-- to be retyped.
--
-- A one-off data repair, not a constraint: SQLite cannot add a CHECK to an existing
-- table without rebuilding it, and the guard belongs at the door anyway.

UPDATE blocks
   SET day = substr(day, 1, 4) || '-' || substr(day, 5, 2) || '-' || substr(day, 7, 2)
 WHERE day IS NOT NULL
   AND length(day) = 8
   AND day GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
   AND substr(day, 5, 2) BETWEEN '01' AND '12'
   AND substr(day, 7, 2) BETWEEN '01' AND '31';
