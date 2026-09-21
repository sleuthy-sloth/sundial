/** Unit tests for what the calendar panel says. Run: cd frontend && npm test
 *
 * The cases worth pinning: "never synced" must be sayable (a blank space and a fresh
 * install are different facts), a sync that changed nothing must be silent, and a stamp
 * that cannot be parsed must not become "Invalid Date" on screen.
 */

import assert from 'node:assert/strict'
import test from 'node:test'

import { ago, clock, eventTime, hasLooked, statusLine, syncNote } from './calendar.js'

const totals = (over = {}) => ({ added: 0, updated: 0, removed: 0, errors: 0, ...over })
const NOW = Date.parse('2026-09-21T12:00:00Z')

test('a sync that found nothing says nothing', () => {
  assert.equal(syncNote({ totals: totals() }), '')
  assert.equal(syncNote({ skipped: 'fresh', totals: totals() }), '')
  assert.equal(syncNote(null), '')
})

test('a sync that did something says what, in the order it matters', () => {
  assert.equal(syncNote({ totals: totals({ added: 3 }) }), '3 new')
  assert.equal(syncNote({ totals: totals({ added: 3, removed: 1, updated: 2 }) }),
    '3 new · 2 updated · 1 removed')
  assert.equal(syncNote({ totals: totals({ errors: 1 }) }), '1 failed')
})

test('how long ago, in words a person would use', () => {
  assert.equal(ago('2026-09-21T11:59:40Z', NOW), 'just now')
  assert.equal(ago('2026-09-21T11:48:00Z', NOW), '12 min ago')
  assert.equal(ago('2026-09-21T09:00:00Z', NOW), '3 h ago')
  assert.equal(ago('2026-09-20T12:00:00Z', NOW), 'yesterday')
  assert.equal(ago('2026-09-18T12:00:00Z', NOW), '3 days ago')
})

test('a stamp that makes no sense says nothing rather than Invalid Date', () => {
  assert.equal(ago('', NOW), '')
  assert.equal(ago('not a date', NOW), '')
  assert.equal(ago(null, NOW), '')
})

test('never synced is a sentence, not a blank', () => {
  assert.equal(statusLine(null), 'checking…')
  assert.equal(statusLine({ configured: false }), 'not connected')
  assert.equal(statusLine({ configured: true, last_sync: null }), 'never synced')
  assert.equal(
    statusLine({ configured: true, last_sync: '2026-09-21T11:48:00Z' }, '2 new', NOW),
    'synced 12 min ago · 2 new',
  )
  assert.equal(
    statusLine({ configured: true, last_sync: '2026-09-21T11:48:00Z' }, '', NOW),
    'synced 12 min ago',
  )
})

test('losing the credentials does not hide what is already stored', () => {
  // A calendar that was synced and whose config file has since moved: the panel says it
  // cannot sync, and still says when it last did.
  assert.equal(
    statusLine({ configured: false, last_sync: '2026-09-21T11:48:00Z', calendars: [{}] }, '', NOW),
    'not connected · last synced 12 min ago',
  )
})

test('nothing read yet is blank, and something read can say it found nothing', () => {
  assert.equal(hasLooked(null), false)
  assert.equal(hasLooked({ configured: true, last_sync: null, calendars: [] }), false)
  assert.equal(hasLooked({ configured: false, last_sync: null, calendars: [{}] }), true)
  assert.equal(hasLooked({ configured: true, last_sync: '2026-09-21T11:48:00Z' }), true)
})

test('an all-day event is not given a time it does not have', () => {
  assert.equal(eventTime({ all_day: 1, start_utc: '2026-09-21T07:00:00Z' }), 'all day')
  const timed = eventTime({ all_day: 0, start_utc: '2026-09-21T21:00:00Z' })
  assert.match(timed, /^\d\d:\d\d$/, timed)
  assert.equal(clock('rubbish'), '')
})

test('a time is read in the reader\'s own zone, not the server\'s', () => {
  // 21:00Z is the afternoon in California and the small hours in Europe: the browser
  // decides, which is why this is computed here rather than sent by the API.
  const iso = '2026-09-21T21:00:00Z'
  assert.equal(clock(iso), eventTime({ all_day: 0, start_utc: iso }))
  assert.equal(clock(iso), `${String(new Date(iso).getHours()).padStart(2, '0')}:${String(new Date(iso).getMinutes()).padStart(2, '0')}`)
})
