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

import { CONFIRMATION, FORMAT, TABLES, VERSION, describe, summarize } from './datafile.js'

const PY = new URL('../../backend/export.py', import.meta.url)
// The phrase is required by the import route, which lives in the router; this reads the module
// that owns it rather than the `app` name that assembles the app.
const DATA_PY = new URL('../../backend/routers/data.py', import.meta.url)

/** A complete, valid document: one of everything, so nothing is missing by accident. */
function good(overrides = {}) {
  return {
    format: FORMAT,
    version: VERSION,
    schema_version: 4,
    exported_at: '2026-09-21T12:00:00+00:00',
    tables: {
      calendars: [{ ref: 'home' }],
      blocks: [{ id: 'b1' }, { id: 'b2' }],
      events: [{ id: 'e1' }],
      sync_log: [],
      push_sent: [],
    },
    ...overrides,
  }
}

test('a complete export is described in terms a person counts things in', () => {
  const seen = summarize(good())
  assert.equal(seen.ok, true)
  assert.deepEqual(seen.counts, {
    calendars: 1, blocks: 2, events: 1, sync_log: 0, push_sent: 0,
  })
  assert.equal(seen.says, '2 blocks, 1 event and 1 calendar')
})

test('an empty export says so rather than listing zeroes', () => {
  const seen = summarize(
    good({ tables: { calendars: [], blocks: [], events: [], sync_log: [], push_sent: [] } }),
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
  const tuple = /^TABLES: tuple\[str, \.\.\.\] = \(([^)]+)\)/m.exec(src)?.[1]
  assert.deepEqual(
    tuple?.split(',').map((part) => part.trim().replace(/"/g, '')),
    TABLES,
    'the tables carried should be the same list in both halves of the format',
  )
})

test('the confirmation phrase matches the one the server requires', () => {
  // Sent, not merely displayed: the panel builds the request body from this constant, so a
  // mismatch is an import that always fails with a 400 nobody can explain.
  const src = readFileSync(DATA_PY, 'utf8')
  assert.equal(/^IMPORT_CONFIRMATION = "(.+)"$/m.exec(src)?.[1], CONFIRMATION)
})
