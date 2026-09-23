/** Unit tests for what the "your data" panel says before it offers you a button.
 *  Run: cd frontend && npm test
 *
 * The refusals carry the weight here. A file that is not an export, a partial one, and one from
 * a newer sundial are the three ways a person picks the wrong file, and each ends as a sentence
 * they have to be able to act on — one of which says "upgrade", which is no use at all if the
 * panel instead reports a parse error somewhere further along.
 *
 * The last block is the interesting one: the export format is a contract between this module and
 * `backend/export.py`, and a contract with two copies needs something that fails when they drift.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  CONFIRMATION,
  FORMAT,
  TABLES,
  TABLES_BY_VERSION,
  VERSION,
  describe,
  summarize,
} from './datafile.js'

const PY = new URL('../../backend/export.py', import.meta.url)
// The phrase is required by the import route, which lives in the router; this reads the module
// that owns it rather than the `app` name that assembles the app.
const DATA_PY = new URL('../../backend/routers/data.py', import.meta.url)

/** A complete, valid document: one of everything, so nothing is missing by accident. */
function good(overrides = {}) {
  return {
    format: FORMAT,
    version: VERSION,
    schema_version: 7,
    exported_at: '2026-09-21T12:00:00+00:00',
    tables: {
      calendars: [{ ref: 'home' }],
      routines: [],
      routine_subtasks: [],
      routine_overrides: [],
      templates: [],
      template_blocks: [],
      blocks: [{ id: 'b1' }, { id: 'b2' }],
      events: [{ id: 'e1' }],
      sync_log: [],
      push_sent: [],
      settings: [],
    },
    ...overrides,
  }
}

test('a complete export is described in terms a person counts things in', () => {
  const seen = summarize(good())
  assert.equal(seen.ok, true)
  assert.deepEqual(seen.counts, {
    calendars: 1, routines: 0, routine_subtasks: 0, routine_overrides: 0, templates: 0,
    template_blocks: 0, blocks: 2, events: 1, sync_log: 0, push_sent: 0, settings: 0,
  })
  assert.equal(seen.says, '2 blocks, 1 event and 1 calendar')
})

test('routines are counted out loud, and their overrides are not', () => {
  // "5 routine_overrides" is a word to read and nothing to know; "2 routines" is a thing you
  // have, and the panel is telling you what is about to land on top of it.
  const seen = summarize(
    good({
      tables: {
        ...good().tables,
        routines: [{ id: 'r1' }, { id: 'r2' }],
        routine_overrides: [{ id: 'o1' }, { id: 'o2' }, { id: 'o3' }, { id: 'o4' }],
      },
    }),
  )
  assert.equal(seen.says, '2 blocks, 2 routines, 1 event and 1 calendar')
})

test('a file from before routines is a whole file, not an incomplete one', () => {
  // The server accepts it, so the panel has to as well: refusing it here would be a refusal with
  // a wrong sentence on it, and the button the person needs would never appear.
  const older = { ...good(), version: 1 }
  older.tables = { ...older.tables }
  for (const name of TABLES) if (!TABLES_BY_VERSION[1].includes(name)) delete older.tables[name]

  const seen = summarize(older)
  assert.equal(seen.ok, true, seen.why)
  assert.equal(seen.counts.routines, 0)
  assert.equal(seen.counts.blocks, 2)
})

test('a file from before checklists is a whole file, not an incomplete one', () => {
  // Version 4 was written by the release before this one, which had no `routine_subtasks` table
  // and never promised one. A version 4 file that is missing it has not been edited.
  const older = { ...good(), version: 4 }
  older.tables = { ...older.tables }
  for (const name of TABLES) if (!TABLES_BY_VERSION[4].includes(name)) delete older.tables[name]

  const seen = summarize(older)
  assert.equal(seen.ok, true, seen.why)
  assert.equal(seen.counts.routine_subtasks, 0)
  assert.equal(seen.counts.blocks, 2)
})

test('a current file missing the routines table is still caught', () => {
  const current = good()
  delete current.tables.routines
  const seen = summarize(current)
  assert.equal(seen.ok, false)
  assert.match(seen.why, /no routines/)
})

test('a file from before settings is a whole file, and one missing them today is not', () => {
  // Version 2 promised routines and no settings, so a version 2 file without the table is complete
  // — the server takes it, and refusing it here would be a refusal with a wrong sentence on it.
  const older = { ...good(), version: 2 }
  older.tables = { ...older.tables }
  delete older.tables.settings
  delete older.tables.templates
  delete older.tables.template_blocks
  assert.equal(summarize(older).ok, true, summarize(older).why)

  const current = good()
  delete current.tables.settings
  const seen = summarize(current)
  assert.equal(seen.ok, false)
  assert.match(seen.why, /no settings/)
})

test('a file from before templates is a whole file, and one missing them today is not', () => {
  // Version 3 promised settings and no templates. The check that matters is the one that came
  // with the version bump: a file written by the release before templates must still import,
  // because its absence is a fact about that file rather than a loss from this one.
  const older = { ...good(), version: 3 }
  older.tables = { ...older.tables }
  delete older.tables.templates
  delete older.tables.template_blocks
  const ok = summarize(older)
  assert.equal(ok.ok, true, ok.why)
  assert.equal(ok.counts.templates, 0)

  const current = good()
  delete current.tables.template_blocks
  const seen = summarize(current)
  assert.equal(seen.ok, false)
  assert.match(seen.why, /no template_blocks/)
})

test('a template is counted out loud, and its lines are not', () => {
  // The same rule as routines: "2 templates" is a thing you have. Nine template items are the
  // contents of one of them, and counting them in the sentence would be counting the wrong thing.
  const seen = summarize(
    good({
      tables: {
        ...good().tables,
        templates: [{ id: 't1' }, { id: 't2' }],
        template_blocks: Array.from({ length: 9 }, (_, i) => ({ id: `i${i}` })),
      },
    }),
  )
  assert.equal(seen.says, '2 blocks, 2 templates, 1 event and 1 calendar')
})

test('an empty export says so rather than listing zeroes', () => {
  const seen = summarize(
    good({
      tables: {
        calendars: [], routines: [], routine_subtasks: [], routine_overrides: [], templates: [],
        template_blocks: [], blocks: [], events: [], sync_log: [], push_sent: [], settings: [],
      },
    }),
  )
  assert.equal(seen.says, 'nothing at all')
})

test('a file that is not a sundial export is refused', () => {
  for (const rubbish of [{ hello: 'world' }, [1, 2, 3], 'a string', null, 42]) {
    const seen = summarize(rubbish)
    assert.equal(seen.ok, false, `${JSON.stringify(rubbish)} was accepted`)
    assert.match(seen.why, /not a sundial export/)
  }
})

test('a file from a newer sundial says to upgrade', () => {
  // Migrations only run forwards, so the useful sentence names the fix rather than the field.
  const seen = summarize(good({ version: VERSION + 1 }))
  assert.equal(seen.ok, false)
  assert.match(seen.why, /newer sundial/)
  assert.match(seen.why, /upgrade/i)
})

test('a partial export is refused, and names what is missing', () => {
  const partial = good()
  delete partial.tables.events
  const seen = summarize(partial)
  assert.equal(seen.ok, false)
  assert.match(seen.why, /incomplete/)
  assert.match(seen.why, /events/, 'the sentence should name the table that is missing')
})

test('a table that is present but is not a list is refused', () => {
  // `"events": {}` would pass a truthiness check and then count as undefined rows.
  const seen = summarize(good({ tables: { ...good().tables, events: {} } }))
  assert.equal(seen.ok, false)
  assert.match(seen.why, /events/)
})

test('describe counts one thing without an "and"', () => {
  assert.equal(describe({ blocks: 1, events: 0, calendars: 0 }), '1 block')
  assert.equal(describe({ blocks: 3, events: 0, calendars: 0 }), '3 blocks')
  assert.equal(describe({ blocks: 0, events: 2, calendars: 1 }), '2 events and 1 calendar')
})

// ---- the contract between this module and the server ------------------------------------
// These read the Python rather than trusting a comment, because the failure they guard against
// is silent: a format that drifts is not an error anywhere, it is an import that refuses a file
// the app itself wrote, or accepts one it should not.

test('the format, version and table list match backend/export.py', () => {
  const src = readFileSync(PY, 'utf8')
  assert.equal(/^FORMAT = "(.+)"$/m.exec(src)?.[1], FORMAT)
  assert.equal(Number(/^VERSION = (\d+)$/m.exec(src)?.[1]), VERSION)

  // Names out of the tuple rather than the whole text: the list is written one name per line
  // now, and a parser that falls over on formatting is a test that fails for the wrong reason.
  const names = (block) => [...(block ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
  const tuple = /^TABLES: tuple\[str, \.\.\.\] = \(([\s\S]+?)^\)$/m.exec(src)?.[1]
  assert.deepEqual(names(tuple), TABLES, 'the tables carried should be the same in both halves')

  const older = /^\s+1: \(([^)]+)\),$/m.exec(src)?.[1]
  assert.deepEqual(
    names(older),
    TABLES_BY_VERSION[1],
    'what an old file promised has to be the same list in both halves too',
  )
  const before = /^\s+2: \(([^)]+)\),$/m.exec(src)?.[1]
  assert.deepEqual(
    names(before),
    TABLES_BY_VERSION[2],
    'and so does the version that carried routines and no settings',
  )
  assert.deepEqual(TABLES_BY_VERSION[VERSION], TABLES, 'the newest version is the whole list')
})

test('the confirmation phrase matches the one the server requires', () => {
  // Sent, not merely displayed: the panel builds the request body from this constant, so a
  // mismatch is an import that always fails with a 400 nobody can explain.
  const src = readFileSync(DATA_PY, 'utf8')
  assert.equal(/^IMPORT_CONFIRMATION = "(.+)"$/m.exec(src)?.[1], CONFIRMATION)
})
