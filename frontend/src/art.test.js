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

test('done arrives as 0 or 1 and is read for truth, not for true', () => {
  assert.equal(dayIsClear([{ done: 1 }, { done: 1 }], [], TODAY, TODAY), true)
  assert.equal(dayIsClear([{ done: '1' }, { done: 1 }], [], TODAY, TODAY), true, 'a string from JSON')
  assert.equal(dayIsClear([{ done: 0 }], [], TODAY, TODAY), false)
})
