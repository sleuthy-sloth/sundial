import test from 'node:test'
import assert from 'node:assert/strict'
import { dayIsClear } from './art.js'

const TODAY = '2026-09-20'
// done arrives from SQLite as 0 or 1, not as a boolean
const block = (done) => ({ id: Math.round(done * 100 + Math.random() * 10), done, start_min: 540, duration_min: 30 })

test('a day that had plans and has none left is clear', () => {
  assert.equal(dayIsClear([block(1), block(1)], [], TODAY, TODAY), true)
})

test('one thing left means the day is not clear', () => {
  assert.equal(dayIsClear([block(1), block(0)], [], TODAY, TODAY), false)
})

test('something still in the inbox is not a finished day', () => {
  // the inbox is unscheduled work: it still has a time to be given, so the day is not over
  assert.equal(dayIsClear([block(1)], [block(0)], TODAY, TODAY), false)
})

test('an empty day is empty, not finished', () => {
  // the one case that would otherwise get a medal for doing nothing
  assert.equal(dayIsClear([], [], TODAY, TODAY), false)
})

test('finished is a fact about today, not about a date', () => {
  assert.equal(dayIsClear([block(1)], [], '2026-09-19', TODAY), false, 'yesterday')
  assert.equal(dayIsClear([block(1)], [], '2026-09-21', TODAY), false, 'tomorrow')
})

test('yesterday\u2019s unfinished work is not today\u2019s, in either direction', () => {
  // The rollover keeps its own list and never merges into this one, and this is the test that
  // would go red if it ever did. A block left on yesterday is not a plan for today, so it cannot
  // fill today's ledger — and it must not be able to stop it reading as clear either, because
  // "clear" is a statement about the day you are in.
  const leftOver = { id: 'y1', title: 'Call dentist', done: 0, start_min: 540, duration_min: 20 }
  assert.equal(dayIsClear([], [], TODAY, TODAY), false, 'today had no plans, so it is empty')
  assert.equal(
    dayIsClear([leftOver], [], TODAY, TODAY),
    false,
    'and an unfinished block of any day is not a finished one',
  )
  assert.equal(
    dayIsClear([block(1), block(1)], [], TODAY, TODAY),
    true,
    'a today that is done is clear whatever yesterday looks like',
  )
})

test('done arrives as 0 or 1 and is read for truth, not for true', () => {
  assert.equal(dayIsClear([{ done: 1 }, { done: 1 }], [], TODAY, TODAY), true)
  assert.equal(dayIsClear([{ done: '1' }, { done: 1 }], [], TODAY, TODAY), true, 'a string from JSON')
  assert.equal(dayIsClear([{ done: 0 }], [], TODAY, TODAY), false)
})
