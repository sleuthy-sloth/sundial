-- 001: an activity icon per block, so a block reads as a picture before a word.
ALTER TABLE blocks ADD COLUMN icon TEXT NOT NULL DEFAULT '';
